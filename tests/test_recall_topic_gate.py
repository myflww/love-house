"""Topic gates preserve real alias sources, literal evidence and custom scorers."""
from copy import deepcopy
import unittest

from nkb import Brain
from nkb.companion.memory import build_context,record_turn,remember
from nkb.companion.structured import build_structured_context
from nkb.organizer.state import semantic_recall
from nkb.retrieval.scoring import OverlapScorer
from nkb.service.controls import set_enabled


class RecallTopicGateTests(unittest.TestCase):
    def brain(self):
        brain=Brain.new();brain.meta.update(library_id='synthetic-home',long_term_archive=True)
        return brain

    def alias_fixture(self):
        brain=self.brain();body='我在蓝莓小镇的海边住下了。'
        source=brain.add('原话',body,kind='episode',salience=.3,meta={
            'source':'conversation_turn','assistant_reply':'祝你安家顺利。'})
        alias=brain.add('落脚点',body,kind='fact',meta={
            'source':'organizer','organizer_layer':'fact','organizer_aliases':['居住地点'],
            'organizer_evidence':[{'id':source,'role':'user','quote':body}]})
        duplicate=brain.add('另一份独立记录',body,kind='episode',salience=.9)
        neighbor=brain.add('投影仪','遥控器在会议室抽屉。',kind='episode')
        brain.link(alias,neighbor,.95);brain.link(source,neighbor,.95)
        return brain,source,alias,duplicate,neighbor

    def test_verified_alias_selects_its_actual_source_not_identical_or_adjacent_material(self):
        brain,source,alias,duplicate,neighbor=self.alias_fixture()
        before=deepcopy(brain.to_dict())
        result=semantic_recall(brain,'安家地点')
        ids={h['id'] for h in result['hits']}
        self.assertTrue({source,alias}<=ids)
        self.assertFalse({duplicate,neighbor}&ids)
        for hit in result['hits']:
            if hit['id']==source:self.assertEqual(hit['semantic_match']['evidence_ids'],[source])
        self.assertEqual(brain.to_dict(),before)

    def test_alias_evidence_cannot_be_displaced_by_prefilter_top_k_clones(self):
        brain,source,alias,duplicate,neighbor=self.alias_fixture()
        for index in range(15):
            brain.add('落脚点'+str(index),brain.nodes[source]['text'],kind='episode',salience=.95)
        for k in (2,8):
            with self.subTest(k=k):
                ids={h['id'] for h in semantic_recall(brain,'安家地点',k=k)['hits']}
                self.assertEqual(ids,{source,alias})

    def test_direct_topic_source_cannot_be_crowded_out_by_old_graph_neighbors(self):
        brain=self.brain()
        strong=brain.add('海洋计划','海洋计划',kind='episode',salience=.95)
        source=brain.add('来源记录','这是海洋计划最初讨论的完整材料。'+20*'当天有很多现场记录。',
                         kind='episode',salience=.2)
        for index in range(15):
            old=brain.add('旧邻居'+str(index),'投影仪的遥控器在柜子里。',kind='episode')
            brain.link(strong,old,.95)
        result=semantic_recall(brain,'海洋计划',k=8)
        self.assertEqual({h['id'] for h in result['hits']},{strong,source})

    def test_literal_cannot_be_supplied_by_alias_generated_title_or_graph_neighbor(self):
        brain=self.brain()
        source=record_turn(brain,'我指的是会议室那台旧投影仪。','好的。','actual','one')
        false_source=record_turn(brain,'用户谈到了古树。','记下了。','other','two')
        fake=brain.add('另一索引','用户谈到了古树。',kind='fact',meta={
            'source':'organizer','organizer_aliases':['我指的是'],
            'organizer_evidence':[{'id':false_source,'role':'user','quote':'用户谈到了古树。'}]})
        titled=brain.add('我指的是','用户谈到了古树。',kind='fact',meta={
            'source':'organizer','organizer_aliases':['我指的是'],
            'organizer_evidence':[{'id':false_source,'role':'user','quote':'用户谈到了古树。'}]})
        brain.link(source,fake,.95);brain.link(source,titled,.95)
        result=build_structured_context(brain,'查找包含“我指的是”的原话',library_id='synthetic-home',max_chars=32000)
        records=result['memory_context']['records']
        self.assertEqual({r['id'] for r in records},{source})
        self.assertTrue(all('我指的是' in r['value'] or '我指的是' in r.get('assistant_statement',{}).get('value','') for r in records))

    def test_literal_assistant_reply_is_real_evidence_even_when_user_text_has_no_match(self):
        brain=self.brain();source=record_turn(brain,'还有一件事。','我指的是原来那条河。','actual','one')
        other=record_turn(brain,'河流后来改道了。','有这段记录。','other','two')
        brain.link(source,other,.95)
        result=build_structured_context(brain,'搜索“我指的是”',library_id='synthetic-home',max_chars=32000)
        self.assertEqual({r['id'] for r in result['memory_context']['records']},{source})
        record=result['memory_context']['records'][0]
        self.assertIn('我指的是',record['assistant_statement']['value'])
        self.assertNotIn('我指的是',record['value'])

    def test_alias_expansion_does_not_override_live_library_pause_tomb_or_missing_source(self):
        for mode in ('foreign','paused','tombstoned','missing'):
            with self.subTest(mode=mode):
                brain,source,alias,duplicate,neighbor=self.alias_fixture()
                if mode=='foreign':brain.nodes[source]['meta']['library_id']='another-library'
                elif mode=='paused':set_enabled(brain,source,False)
                elif mode=='tombstoned':brain.meta['memory_tombstones']={'node_ids':[source]}
                else:brain.remove(source)
                result=build_structured_context(brain,'安家地点',library_id='synthetic-home',max_chars=32000)
                self.assertEqual(result['memory_context']['records'],[])

    def test_custom_scorer_keeps_full_corpus_contract_and_nonlexical_hits(self):
        brain=self.brain();wanted=brain.add('星际航行','星际航行的实际经历。',kind='episode')
        other=brain.add('公园','公园散步。',kind='episode');seen=[]
        class Custom(OverlapScorer):
            def __call__(self,nodes,vecs,query,floor,encoder):
                seen.append((set(nodes),query))
                return {wanted:.9,other:.8}
        brain.scorer=Custom()
        result=semantic_recall(brain,'海洋计划',candidate_ids={wanted})
        self.assertEqual({h['id'] for h in result['hits']},{wanted})
        self.assertEqual(seen[0][0],{wanted,other})
        self.assertEqual(seen[0][1],'海洋计划')

    def test_empty_retrieval_preserves_current_session_and_does_not_order_a_stock_question(self):
        brain=self.brain();remember(brain,'我喜欢温红茶。')
        record_turn(brain,'刚才我们讨论的是书房里的清单。','我知道你指的是这段对话。','current','one')
        record_turn(brain,'其他窗口在讨论汽车。','另一段原话。','unconnected-current','two')
        result=build_context(brain,'我指的是这个',session_id='current',library_id='synthetic-home')
        self.assertEqual(result['memory_ids'],[])
        self.assertEqual(result['baseline'],[])
        self.assertEqual(len(result['history']),2)
        self.assertIn('书房',result['history'][0]['content'])
        self.assertNotIn('汽车',str(result['history']))
        self.assertNotIn('请先澄清',result['packet'])
        self.assertIn('自然回应',result['packet'])


if __name__=='__main__':unittest.main()
