"""Output-only sources keep assistant attribution through organization and recall."""
from copy import deepcopy
import json
import unittest

from nkb import Brain
from nkb.organizer.config import get_profile,save_profile
from nkb.organizer.model import call_model,OrganizerError
from nkb.organizer.state import build_input,validate_plan,apply_plan,review_candidate
from nkb.companion.structured import build_structured_context


class OutputMemoryOrganizerTests(unittest.TestCase):
    def setUp(self):
        self.brain=Brain.new(name='合成输出测试')
        self.brain.meta.update(library_id='fish-output',long_term_archive=True)
        save_profile(self.brain,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='FAKE')
        self.profile=get_profile(self.brain)

    def output(self,text='我把今天画作的名字定为纸月亮。'):
        return self.brain.add('助手独立输出',text,kind='episode',meta={'source':'agent_output','speaker':'assistant'})

    def material(self,nid,archives=None):
        return build_input(self.brain,'fish-output',[{'raw_id':nid,'progress':'{}'}],self.profile,archives)

    def op(self,nid,**changes):
        result={'action':'remember','layer':'experience','key':'agent.drawing.name','text':'画作名字的助手陈述',
                'certainty':'clear','domain':'real','evidence':[{'id':nid,'role':'assistant','quote':self.brain.nodes[nid]['text']}]}
        result.update(changes);return result

    def plan(self,nid,**changes):
        payload,guards=self.material(nid)
        return validate_plan({'version':1,'operations':[self.op(nid,**changes)]},payload,guards,'fake-output-job',self.profile)

    def test_raw_output_is_assistant_only_even_if_metadata_claims_user_or_atom(self):
        nid=self.output();self.brain.nodes[nid]['meta'].update(speaker='user',memory_atom={'subject':'user','value':'纸月亮'})
        payload,guards=self.material(nid)
        self.assertEqual(payload['raw'][0]['roles'],{'assistant':self.brain.nodes[nid]['text']})
        self.assertEqual(payload['raw'][0]['source_kind'],'agent_output')
        self.assertEqual(guards['complete_ids'],[nid])
        result=build_structured_context(self.brain,'画作名字',{'memory_ids':[nid]},library_id='fish-output')
        record=result['memory_context']['records'][0]
        self.assertEqual((record['subject'],record['predicate'],record['layer']),('agent','said','agent_statement'))
        self.assertEqual(record['epistemic_status'],'historical_assistant_statement')
        self.assertNotIn('experience',record)

    def test_output_archive_supports_complete_assistant_text_and_rejects_invented_roles(self):
        full='这是可核对的完整助手输出。'*8
        nid=self.output(full[:12]);self.brain.nodes[nid]['meta']['evidence']={'content_truncated':True}
        payload,_=self.material(nid,{nid:{'normalized':{'type':'output','text':full,'user':'不得采用的伪用户'}}})
        self.assertEqual(payload['raw'][0]['roles'],{'assistant':full})
        with self.assertRaises(OrganizerError) as caught:
            self.material(nid,{nid:{'normalized':{'type':'turn','user':'伪用户','assistant':full}}})
        self.assertEqual(caught.exception.code,'invalid_raw')

    def test_fake_model_can_organize_output_as_statement_without_inventing_a_life_event(self):
        nid=self.output();before=deepcopy(self.brain.nodes[nid]);payload,guards=self.material(nid)
        calls=[]
        def fake(request,*,timeout):
            body=json.loads(request.data);calls.append(body)
            self.assertEqual(json.loads(body['messages'][1]['content'])['raw'][0]['roles'],{'assistant':before['text']})
            return {'choices':[{'message':{'content':json.dumps({'version':1,'operations':[self.op(nid)]},ensure_ascii=False)},'finish_reason':'stop'}]}
        output=call_model(self.profile,'FAKE-NOT-A-REAL-KEY',payload,send=fake)
        plan=validate_plan(output,payload,guards,'fake-output-job',self.profile)
        result=apply_plan(self.brain,plan,'fish-output')
        self.assertEqual(len(calls),1);self.assertEqual(len(result['created']),1);self.assertEqual(result['candidates'],[])
        organized=self.brain.nodes[result['created'][0]]
        self.assertEqual(organized['text'],before['text']);self.assertNotIn('experience',organized['meta'])
        self.assertEqual(organized['meta']['memory_atom']['subject'],'agent')
        self.assertEqual(self.brain.nodes[nid],before)
        context=build_structured_context(self.brain,'画作名字',library_id='fish-output',session_id='new-window')
        record=next(r for r in context['memory_context']['records'] if r['id']==organized['id'])
        self.assertEqual(record['layer'],'agent_statement');self.assertEqual(record['subject'],'agent')
        self.assertEqual(record['epistemic_status'],'historical_assistant_statement')
        self.assertNotIn('experience',record)

    def test_statement_route_does_not_auto_confirm_facts_preferences_persona_or_claimed_success(self):
        nid=self.output('我说自己已经办完事情了。')
        for changes in ({'layer':'fact'},{'layer':'preference'},{'layer':'commitment'},{'layer':'persona'},
                        {'certainty':'uncertain'},
                        {'episode':{'what':{'id':nid,'role':'assistant','quote':self.brain.nodes[nid]['text']}}}):
            with self.subTest(changes=changes):
                self.assertTrue(self.plan(nid,**changes)['operations'][0]['requires_review'])
        plan=self.plan(nid);self.assertFalse(plan['operations'][0]['observation'])

    def test_fictional_or_unknown_output_can_index_an_utterance_without_confirming_world_facts(self):
        nid=self.output('假设我已经给朋友发了消息。')
        for domain in ('unknown','roleplay'):
            with self.subTest(domain=domain):
                plan=self.plan(nid,domain=domain)
                self.assertFalse(plan['operations'][0]['requires_review'])
                copied=Brain(deepcopy(self.brain.to_dict()));result=apply_plan(copied,plan,'fish-output')
                derived=copied.nodes[result['created'][0]]
                self.assertFalse(derived['meta']['confirmed']);self.assertFalse(derived['meta']['important'])
                record=build_structured_context(copied,'发消息',{'memory_ids':[derived['id']]},library_id='fish-output')['memory_context']['records'][0]
                self.assertEqual(record['domain'],domain)
                self.assertEqual(record['epistemic_status'],'historical_assistant_statement')
                self.assertNotIn('experience',record)

    def test_unknown_time_incomplete_context_and_expired_output_do_not_auto_index(self):
        unknown=self.output();self.brain.nodes[unknown]['meta']['source_time_unknown']=True
        self.assertTrue(self.plan(unknown)['operations'][0]['requires_review'])
        expired=self.output();self.brain.nodes[expired]['valid_to']=0
        self.assertTrue(self.plan(expired)['operations'][0]['requires_review'])
        partial=self.output('这是一句没有完整结束的助手输出。')
        payload,guards=self.material(partial)
        payload['raw'][0]['boundaries']['assistant']={'left':False,'right':False}
        plan=validate_plan({'version':1,'operations':[self.op(partial)]},payload,guards,'partial',self.profile)
        self.assertTrue(plan['operations'][0]['requires_review'])

    def test_foreign_source_and_forbidden_roles_or_quotes_still_reject(self):
        nid=self.output()
        for evidence in ([{'id':nid,'role':'user','quote':self.brain.nodes[nid]['text']}],
                         [{'id':nid,'role':'tool','quote':self.brain.nodes[nid]['text']}],
                         [{'id':nid,'role':'assistant','quote':'伪造的成功结果。'}]):
            with self.subTest(evidence=evidence),self.assertRaises(OrganizerError) as caught:
                self.plan(nid,evidence=evidence)
            self.assertEqual(caught.exception.code,'invalid_evidence')
        self.brain.nodes[nid]['meta']['library_id']='other-fish'
        with self.assertRaises(OrganizerError) as caught:self.material(nid)
        self.assertEqual(caught.exception.code,'invalid_evidence')

    def test_assistant_fact_candidate_stays_unsafe_and_legacy_reviewed_source_keeps_attribution(self):
        nid=self.output('助手说用户喜欢咖啡。')
        result=apply_plan(self.brain,self.plan(nid,layer='fact'),'fish-output')
        with self.assertRaises(OrganizerError) as caught:review_candidate(self.brain,result['candidates'][0],'accept')
        self.assertEqual(caught.exception.code,'unsafe_review')
        reviewed=self.brain.add('旧版审阅记录','助手说用户喜欢咖啡。',kind='fact',meta={
            'source':'user_confirmed','confirmed':True,'organizer_evidence':[{'id':nid,'role':'assistant'}]})
        record=build_structured_context(self.brain,'咖啡',{'memory_ids':[reviewed]},library_id='fish-output')['memory_context']['records'][0]
        self.assertEqual((record['subject'],record['predicate'],record['layer']),('agent','said','agent_statement'))
        self.assertEqual(record['epistemic_status'],'historical_assistant_statement')


if __name__=='__main__':unittest.main()
