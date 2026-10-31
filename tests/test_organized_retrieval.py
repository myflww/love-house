"""Organized retrieval has its own lane; raw evidence remains intact and bounded."""
from copy import deepcopy
import json
import time
import unittest

from nkb import Brain
from nkb.companion.memory import build_context,record_turn,remember
from nkb.companion.structured import build_structured_context
from nkb.organizer.config import get_profile,save_profile
from nkb.organizer.state import build_input,validate_plan,apply_plan
from nkb.errors import ValidationError


class OrganizedRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.brain=Brain.new(name='合成召回测试')
        self.brain.meta.update(library_id='fish-one',long_term_archive=True)
        save_profile(self.brain,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='FAKE')
        self.number=0

    def raw(self,text='我把画作起名为纸月亮。'):
        self.number+=1
        return self.brain.add('助手独立输出',text,kind='episode',meta={'source':'agent_output','speaker':'assistant'})

    def organize(self,nid,key='agent.drawing.name'):
        profile=get_profile(self.brain)
        payload,guards=build_input(self.brain,'fish-one',[{'raw_id':nid,'progress':'{}'}],profile)
        plan=validate_plan({'version':1,'operations':[{'action':'remember','layer':'experience','key':key,
            'text':'助手关于画作的陈述','domain':'real','certainty':'clear',
            'evidence':[{'id':nid,'role':'assistant','quote':self.brain.nodes[nid]['text']}]}]},payload,guards,'job-'+str(self.number),profile)
        result=apply_plan(self.brain,plan,'fish-one')
        return result['created'][0]

    def build(self,query='画作起名',budget=8000,base=None):
        return build_structured_context(self.brain,query,base,max_chars=budget,library_id='fish-one',session_id='new-empty-window')

    def test_many_high_ranked_raw_nodes_cannot_push_organized_memory_out_of_retrieval(self):
        source=self.raw();derived=self.organize(source)
        self.brain.nodes[derived]['salience']=.1
        for i in range(60):
            nid=self.raw('画作起名 画作起名 '+str(i));self.brain.nodes[nid]['salience']=1
        self.assertNotIn(derived,[h['id'] for h in self.brain.recall('画作起名',k=8)['hits']])
        before=deepcopy(self.brain.to_dict());base=build_context(self.brain,'画作起名',max_chars=32000)
        self.assertIn(derived,base['memory_ids'])
        context=self.build(budget=32000,base=base)
        self.assertEqual(context['memory_ids'][0],derived)
        self.assertEqual(context['source_coverage']['organized'],1)
        self.assertLessEqual(context['source_coverage']['raw'],4)
        self.assertGreater(context['source_coverage']['raw'],0)
        self.assertEqual(before,self.brain.to_dict())

    def test_raw_is_still_available_as_bounded_fallback_without_organized_memories(self):
        for i in range(20):self.raw('画作起名讨论 '+str(i))
        context=self.build(budget=32000)
        self.assertEqual(context['source_coverage'],{'organized':0,'raw':4,'other':0})
        self.assertEqual(len(self.brain.nodes),20)

    def test_packet_coverage_counts_actual_records_after_exclusion_and_budget_omission(self):
        source=self.raw();derived=self.organize(source);manual=remember(self.brain,'画作起名需尊重作者',kind='fact')
        huge=self.raw('很长的画作原始陈述。'*2000)
        foreign=self.raw('另一条鱼的唯一秘密');self.brain.nodes[foreign]['meta']['library_id']='fish-two'
        base={'memory_ids':[huge,foreign,derived,source,manual],'history':[],'messages':[]}
        for budget in (512,1000,2000,8000):
            with self.subTest(budget=budget):
                result=self.build(budget=budget,base=base);packet=json.loads(result['packet'])
                counts={'organized':0,'raw':0,'other':0}
                for record in packet['records']:
                    kind=record['source']['kind'];counts['organized' if kind=='organizer' else 'raw' if kind=='agent_output' else 'other']+=1
                self.assertEqual(result['source_coverage'],counts)
                if 'sources' in packet['counts']:self.assertEqual(packet['counts']['sources'],counts)
                else:self.assertIn('source_coverage',packet['truncation']['omitted_fields'])
                self.assertLessEqual(len(result['packet']),budget);self.assertEqual(packet,result['memory_context'])
                self.assertNotIn(foreign,result['memory_ids'])

    def test_disabling_or_foreign_evidence_does_not_reappear_through_organized_lane(self):
        source=self.raw('画作的私密代号为ONLY_THIS_FISH。');derived=self.organize(source)
        self.brain.nodes[source]['meta']['library_id']='fish-two'
        result=self.build();self.assertNotIn(derived,result['memory_ids']);self.assertNotIn('ONLY_THIS_FISH',result['packet'])
        self.brain.nodes[source]['meta'].pop('library_id');self.brain.nodes[derived]['meta']['memory_disabled']=True
        result=self.build();self.assertNotIn(derived,result['memory_ids']);self.assertNotIn(source,result['memory_ids'])
        self.assertNotIn('ONLY_THIS_FISH',result['packet'])

    def test_changed_output_withholds_old_organized_statement_without_deleting_either_record(self):
        source=self.raw('画作旧名字为OLD_PAPER_MOON。');derived=self.organize(source)
        self.brain.nodes[source]['text']='画作的名字已经更正为新名字。'
        result=self.build(base={'memory_ids':[derived],'messages':[],'history':[]})
        self.assertEqual(result['memory_ids'],[]);self.assertNotIn('OLD_PAPER_MOON',result['packet'])
        self.assertIn(derived,self.brain.nodes);self.assertIn(source,self.brain.nodes)

    def test_latest_platform_correction_keeps_priority_over_many_organized_old_statements(self):
        for i in range(12):
            source=self.raw('QQ 中性暗号的旧整理说法 '+str(i));self.organize(source,key='agent.password.'+str(i))
        stamp=time.time()-5
        latest=record_turn(self.brain,'换一个新的中性暗号。','新的中性暗号是合成蓝莓7629。','qq-session','fresh',event_at=stamp)
        self.brain.nodes[latest]['meta']['evidence']={'platform':'qq','source_id':'source_'+'a'*32,'source_event_at':stamp}
        query='QQ 刚才最新确认的中性暗号是什么'
        result=self.build(query,budget=6000)
        self.assertEqual(result['memory_ids'][0],latest)
        record=result['memory_context']['records'][0]
        self.assertIn('合成蓝莓7629',record['assistant_statement']['value'])
        self.assertEqual(record['epistemic_status'],'historical_user_statement')
        self.assertGreater(result['source_coverage']['raw'],0)

    def test_derived_only_and_empty_control_are_causal_request_projections_not_source_deletion(self):
        source=self.raw('画作的合成名字是TEST_PAPER_MOON。');derived=self.organize(source)
        before=deepcopy(self.brain.to_dict());query='画作的合成名字是什么？'
        def projected(ids):
            return self.build(query,base={'memory_ids':ids,'history':[],'messages':[],'platform_recent_ids':[]})
        only=projected([derived]);control=projected([])
        self.assertEqual(only['source_coverage'],{'organized':1,'raw':0,'other':0})
        self.assertEqual(only['memory_ids'],[derived]);self.assertEqual(only['history'],[]);self.assertEqual(only['messages'],[])
        self.assertIn('TEST_PAPER_MOON',only['packet']);self.assertNotIn('TEST_PAPER_MOON',control['packet'])
        self.assertEqual(before,self.brain.to_dict());self.assertIn(source,self.brain.nodes)

    def test_observed_episode_causal_projection_preserves_raw_validation_but_sends_no_raw_records(self):
        reason=self.raw('因为想了解海边天气，所以我去查资料。')
        what=self.brain.add('合成实际观察','打开了海边天气资料页。',kind='episode',meta={'source':'tool_observation','outcome':'observed'})
        outcome=self.brain.add('合成结果','页面报告明天晴天，代号为TEST_CLEAR_SKY。',kind='episode',meta={'source':'tool_observation','outcome':'success'})
        ids=[reason,what,outcome];profile=get_profile(self.brain)
        refs=[{'id':reason,'role':'assistant','quote':self.brain.nodes[reason]['text']},
              {'id':what,'role':'tool','quote':self.brain.nodes[what]['text']},
              {'id':outcome,'role':'tool','quote':self.brain.nodes[outcome]['text']}]
        payload,guards=build_input(self.brain,'fish-one',[{'raw_id':nid,'progress':'{}'} for nid in ids],profile)
        plan=validate_plan({'version':1,'operations':[{'action':'remember','layer':'experience','key':'experience.synthetic.weather',
            'text':'实际天气查询经历','domain':'real','certainty':'clear','evidence':refs,
            'episode':{'what':refs[1],'reason':refs[0],'outcome':refs[2]}}]},payload,guards,'causal-episode-job',profile)
        derived=apply_plan(self.brain,plan,'fish-one')['created'][0];before=deepcopy(self.brain.to_dict())
        only=self.build('海边天气结果是什么',base={'memory_ids':[derived],'history':[],'messages':[]})
        control=self.build('海边天气结果是什么',base={'memory_ids':[],'history':[],'messages':[]})
        record=only['memory_context']['records'][0]
        self.assertEqual(record['experience']['outcome']['quote'],self.brain.nodes[outcome]['text'])
        self.assertFalse(record['experience']['reason_verified'])
        self.assertEqual(only['source_coverage'],{'organized':1,'raw':0,'other':0})
        self.assertEqual(only['memory_ids'],[derived]);self.assertNotIn('TEST_CLEAR_SKY',control['packet'])
        self.assertIn('TEST_CLEAR_SKY',only['packet']);self.assertEqual(before,self.brain.to_dict())

    def test_core_candidate_lane_never_bypasses_lifecycle_or_mutates_graph(self):
        live=self.raw();future=self.raw('未来的画作起名')
        self.brain.nodes[future]['valid_from']=time.time()+3600
        before=deepcopy(self.brain.to_dict())
        result=self.brain.recall('画作起名',candidate_ids={live,future,'missing'})
        self.assertEqual([h['id'] for h in result['hits']],[live])
        self.assertEqual(self.brain.recall('画作起名',candidate_ids=set())['hits'],[])
        with self.assertRaises(ValidationError):self.brain.recall('画作',candidate_ids='not-a-set')
        self.assertEqual(before,self.brain.to_dict())


if __name__=='__main__':unittest.main()
