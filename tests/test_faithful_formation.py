"""Real quoted uncertainty remains searchable without becoming a world verdict."""
from copy import deepcopy
import unittest

from nkb import Brain
from nkb.companion.memory import record_turn
from nkb.companion.structured import build_structured_context
from nkb.organizer.config import get_profile, save_profile
from nkb.organizer.model import OrganizerConflict, OrganizerError
from nkb.organizer.state import apply_plan, build_input, fingerprint, review_candidate, validate_plan


class FaithfulFormationTests(unittest.TestCase):
    def setUp(self):
        self.brain=Brain.new()
        self.brain.meta.update(library_id='home',long_term_archive=True)
        save_profile(self.brain,enabled=True,provider_id='FAKE',base_url='https://example.invalid/v1',model='offline')
        self.profile=get_profile(self.brain)

    def raw(self,user='我可能误会了朋友为什么没有回信。',assistant='我当时猜他可能在忙。'):
        return record_turn(self.brain,user,assistant,'synthetic-window',str(len(self.brain.nodes)))

    def op(self,nid,role='user',**changes):
        body=self.brain.nodes[nid]['text'] if role=='user' else self.brain.nodes[nid]['meta']['assistant_reply']
        return {'action':'remember','layer':'fact','key':'friend.reply','text':'不作为原话使用的摘要',
                'certainty':'uncertain','domain':'unknown','evidence':[{'id':nid,'role':role,'quote':body}],**changes}

    def plan(self,ids,ops,job='synthetic-formation',target=None):
        payload,guards=build_input(self.brain,'home',[{'raw_id':nid,'progress':'{}'} for nid in ids],self.profile)
        if target and target not in {r['id'] for r in payload['related']}:
            payload['related'].append({'id':target})
            guards['existing_fingerprints'][target]=fingerprint(self.brain.nodes[target])
        return validate_plan({'version':1,'operations':ops},payload,guards,job,self.profile)

    def apply(self,nid,op,job='synthetic-formation',target=None):
        plan=self.plan([nid],[op],job,target)
        result=apply_plan(self.brain,plan,'home')
        self.assertEqual(result['candidates'],[])
        return self.brain.nodes[result['created'][0]]

    def test_uncertain_conflicting_and_roleplay_statements_form_literal_records(self):
        for index,(certainty,domain,text) in enumerate([
                ('uncertain','unknown','我可能误会了朋友为什么没有回信。'),
                ('conflict','real','我昨天以为朋友生气了，今天他说只是忙。'),
                ('clear','roleplay','小说里我住在火星，这只是故事设定。')]):
            with self.subTest(certainty=certainty,domain=domain):
                nid=self.raw(text);before=deepcopy(self.brain.nodes[nid])
                node=self.apply(nid,self.op(nid,certainty=certainty,domain=domain),str(index))
                self.assertEqual(node['text'],text)
                self.assertEqual((node['kind'],node['meta']['organizer_layer']),('episode','experience'))
                self.assertTrue(node['meta']['attributed_material'])
                self.assertFalse(node['meta']['confirmed'])
                self.assertEqual((node['meta']['domain'],node['meta']['certainty']),(domain,certainty))
                self.assertEqual(node['meta']['memory_atom']['predicate'],'recorded_statement')
                self.assertEqual(self.brain.nodes[nid],before)
                query='小说火星' if domain=='roleplay' else '朋友'
                packet=build_structured_context(self.brain,query,library_id='home',max_chars=16000)['memory_context']
                record=next(r for r in packet['records'] if r['id']==node['id'])
                self.assertNotEqual(record['interpretation'],'current_memory')
                self.assertEqual(record['domain'],domain)

    def test_assistant_claim_does_not_become_an_owner_preference_or_completed_commitment(self):
        nid=self.raw('请记下这段对话。','我猜主人喜欢咖啡，而且我说自己已经送出信了。')
        node=self.apply(nid,self.op(nid,'assistant',layer='commitment',certainty='clear',domain='real'))
        self.assertEqual(node['meta']['recorded_layer'],'commitment')
        self.assertNotIn('status',node['meta'])
        self.assertEqual(node['meta']['memory_atom']['subject'],'agent')
        self.assertEqual(node['text'],self.brain.nodes[nid]['meta']['assistant_reply'])
        self.assertFalse(node['meta']['confirmed'])

    def test_external_speaker_is_searchable_without_becoming_the_owner(self):
        nid=self.raw('我喜欢冰咖啡。')
        self.brain.nodes[nid]['meta']['evidence']={'participant_scope':'external_participant','participant_id':'FAKE-peer'}
        node=self.apply(nid,self.op(nid,layer='preference',certainty='clear',domain='real'))
        self.assertEqual(node['meta']['memory_atom']['subject'],'platform_participant')
        self.assertEqual(node['meta']['organizer_evidence'][0]['participant_id'],'FAKE-peer')
        self.assertEqual(node['kind'],'episode')

    def test_one_reply_instruction_remains_scoped_material_instead_of_a_lasting_preference(self):
        nid=self.raw('这次回答只用一句话，之后照常。')
        node=self.apply(nid,self.op(nid,layer='preference',certainty='clear',domain='real',
            atom={'subject':'user','predicate':'response.style','value':'一句话'}))
        self.assertEqual(node['kind'],'episode')
        self.assertEqual(node['meta']['recorded_layer'],'preference')
        self.assertEqual(node['meta']['memory_atom']['predicate'],'recorded_statement')
        self.assertEqual(node['text'],'这次回答只用一句话，之后照常。')

    def test_invalid_optional_atom_automatically_keeps_only_the_correct_role_literal(self):
        nid=self.raw('我们换一个暗号。','助手说暗号是蓝鲸泡泡。')
        node=self.apply(nid,self.op(nid,atom={'subject':'user','predicate':'secret.current','value':'蓝鲸泡泡'},
                                   aliases=['蓝鲸泡泡'],certainty='clear',domain='real'))
        self.assertEqual(node['text'],'我们换一个暗号。')
        self.assertEqual(node['meta']['memory_atom']['relation_status'],'verbatim_fallback')
        self.assertEqual(node['meta']['organizer_aliases'],[])
        self.assertNotIn('蓝鲸泡泡',node['text'])
        self.assertNotIn('蓝鲸泡泡',node['meta']['organizer_summary'])

    def test_uncertain_supersession_adds_a_statement_without_rewriting_the_previous_record(self):
        old=self.brain.add('旧说法','朋友昨天没有回信。',kind='fact',meta={
            'source':'user_confirmed','confirmed':True,'organizer_key':'friend.reply'})
        before=deepcopy(self.brain.nodes[old])
        nid=self.raw('也许朋友只是忙，我还不能确定。')
        node=self.apply(nid,self.op(nid,action='supersede',target_id=old),target=old)
        self.assertEqual(self.brain.nodes[old],before)
        self.assertEqual(node['meta']['memory_atom']['value'],self.brain.nodes[nid]['text'])

    def test_partial_context_is_labelled_excerpt_and_unknown_time_is_not_invented(self):
        nid=self.raw('这一段只是被提供的片段，不能补成结论。')
        self.brain.nodes[nid]['meta']['source_time_unknown']=True
        payload,guards=build_input(self.brain,'home',[{'raw_id':nid,'progress':'{}'}],self.profile)
        payload['raw'][0]['boundaries']['user']={'left':False,'right':False}
        plan=validate_plan({'version':1,'operations':[self.op(nid)]},payload,guards,'fragment',self.profile)
        node=self.brain.nodes[apply_plan(self.brain,plan,'home')['created'][0]]
        self.assertTrue(node['meta']['source_excerpt'])
        self.assertIsNone(node['meta']['memory_atom']['event_at'])
        self.assertTrue(node['meta']['source_time_unknown'])

    def test_different_occurrences_of_the_same_words_are_not_collapsed(self):
        ids=[self.raw('我当时猜朋友生气了。') for _ in range(2)]
        for i,nid in enumerate(ids):self.apply(nid,self.op(nid),str(i))
        records=[n for n in self.brain.nodes.values() if n['meta'].get('attributed_material')]
        self.assertEqual(len(records),2)
        self.assertEqual({n['meta']['organizer_sources'][0]['id'] for n in records},set(ids))

    def test_source_role_scope_and_revision_checks_still_reject_forgery_and_stale_writes(self):
        nid=self.raw();op=self.op(nid)
        for evidence in ([{'id':'foreign','role':'user','quote':'我可能误会了朋友为什么没有回信。'}],
                         [{'id':nid,'role':'tool','quote':'我可能误会了朋友为什么没有回信。'}],
                         [{'id':nid,'role':'user','quote':'根本不存在的原话'}]):
            with self.subTest(evidence=evidence),self.assertRaises(OrganizerError):
                self.plan([nid],[{**op,'evidence':evidence}])
        plan=self.plan([nid],[op]);self.brain.nodes[nid]['text']='后来出现新的原话。'
        with self.assertRaises(OrganizerConflict):apply_plan(self.brain,plan,'home')

    def test_persona_and_relationship_settings_are_not_automatically_replaced(self):
        nid=self.raw('把角色设定改成另外一种。')
        for fields in ({'layer':'persona'},{'key':'relationship.stage'}):
            plan=self.plan([nid],[self.op(nid,**fields)])
            self.assertTrue(plan['operations'][0]['requires_review'])
        self.assertNotIn('companion_profile',self.brain.meta)

    def test_new_organization_does_not_delete_or_accept_an_existing_review_backlog(self):
        nid=self.raw('这是过去留下的一条不确定说法。')
        legacy=deepcopy(self.plan([nid],[self.op(nid)])['operations'][0])
        legacy.update(action='candidate',layer='fact',requires_review=True)
        for field in ('attributed_material','statement_attribution','statement_source_revisions',
                      'recorded_action','recorded_layer','material_basis','source_excerpt'):
            legacy.pop(field,None)
        pending={'id':'legacy-review','job_id':'legacy-job','library_id':'home','status':'pending',
                 'operation':legacy,'reason':'旧版不确定候选','at':1}
        self.brain.meta['organizer_candidates']=[deepcopy(pending)]
        newer=self.raw('现在又产生了一条新的猜想。')
        plan=self.plan([newer],[self.op(newer)],'new-job')
        result=apply_plan(self.brain,plan,'home')
        self.assertEqual(len(result['created']),1)
        self.assertEqual(self.brain.meta['organizer_candidates'],[pending])
        self.assertEqual(review_candidate(self.brain,'legacy-review','reject')['status'],'rejected')


if __name__=='__main__':unittest.main()
