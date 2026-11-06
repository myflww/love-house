"""Real HTTP regression for conversational phrasing versus actual topic evidence.

All examples are synthetic reports, never real user transcripts or instructions.
"""
import json
import time
import unittest

from tests import test_memory_experience_service as fixture
from nkb.service.agent_client import event_from_hook
from nkb.service.source_client import SourceClient


class ConversationalRetrievalServiceTests(unittest.TestCase):
    tearDown=fixture.MemoryExperienceServiceTests.tearDown
    connection=fixture.MemoryExperienceServiceTests.connection
    request=fixture.MemoryExperienceServiceTests.request

    def setUp(self):
        fixture.MemoryExperienceServiceTests.setUp(self)
        self.doc_text='我指的是我发给你的文档里所提供的记忆库。'
        self.emotion_text='我指的是你的情绪体检。'
        self.next_text='所以要现在选什么？'
        self.list_text='反复背清单让对话生硬，我希望自然聊天。'
        self.doc=self.capture(self.doc_text,'document')
        self.emotion=self.capture(self.emotion_text,'emotion')
        self.next=self.capture(self.next_text,'choice')
        self.list_id=self.capture(self.list_text,'list')
        def organize(brain):
            # An existing generic alias and actual graph links must not turn
            # shared conversational wording into evidence about a new topic.
            alias=brain.add('文档记忆库原话索引',self.doc_text,kind='fact',meta={
                'source':'organizer','domain':'real','organizer_layer':'fact',
                'organizer_key':'documents.memory_library','organizer_aliases':['我指的是','所以'],
                'organizer_evidence':[{'id':self.doc,'role':'user','quote':self.doc_text}]})
            baseline=brain.add('饮品偏好','我喜欢喝温水。',kind='preference',meta={
                'source':'user_confirmed','confirmed':True,'important':True,'speaker':'user'})
            brain.link(self.doc,self.next,.95);brain.link(self.emotion,self.next,.95)
            brain.link(self.list_id,self.doc,.8)
            return alias,baseline
        self.alias_id,self.baseline=self.host.transact(self.library,organize)

    def capture(self,text,turn,*,cid=None,token=None,window='window-a',library=None):
        event=event_from_hook({'session_id':window,'turn_id':turn,'status':'complete',
            'user':text,'assistant':'这是当时实际产生的合成回复。'})
        status,result=self.request(f'/api/connections/{cid or self.cid}/events',event,
            library=library,management=False,token=token or self.token)
        self.assertEqual(status,200,result)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            self.host.process_pending(library_id=library or self.library,receipt_id=result['receipt_id'])
            with self.host.connections.db() as db:
                row=db.execute('SELECT status,node_ids FROM receipts WHERE id=?',(result['receipt_id'],)).fetchone()
            if row and row['status']=='saved':return json.loads(row['node_ids'])[0]
            time.sleep(.01)
        self.fail('Synthetic HTTP dialogue did not reach the saved state')

    def context(self,query,*,cid=None,token=None,window='window-a',library=None):
        return self.request(f'/api/connections/{cid or self.cid}/context',{
            'query':query,'session_id':window,'max_chars':32000},
            library=library,management=False,token=token or self.token)

    def tool(self,query,*,cid=None,token=None,window='window-a',library=None):
        return self.request(f'/api/connections/{cid or self.cid}/tool',{
            'name':'memory_context','arguments':{'query':query,'session_id':window,'max_chars':32000}},
            library=library,management=False,token=token or self.token)

    def assert_topic_matches(self,packet):
        ids={record['id'] for record in packet['records']}
        self.assertIn(self.list_id,ids)
        unexpected={self.doc,self.emotion,self.next,self.alias_id}&ids
        self.assertFalse(unexpected,{'unrelated_values':[r['value'] for r in packet['records'] if r['id'] in unexpected],
                                     'selected_ids':sorted(ids)})
        encoded=json.dumps(packet,ensure_ascii=False)
        for text in (self.doc_text,self.emotion_text,self.next_text):self.assertNotIn(text,encoded)

    def test_context_keeps_actual_topic_and_original_question_without_boilerplate_alias_or_graph_drift(self):
        query='我指的是为什么总背清单'
        before={nid:self.host.snapshot(self.library)['nodes'][nid]['text']
                for nid in (self.doc,self.emotion,self.next,self.list_id)}
        status,result=self.context(query)
        self.assertEqual(status,200,result);self.assert_topic_matches(result['memory_context'])
        self.assertEqual(result['query'],query)
        self.assertEqual(result['messages'][-1],{'role':'user','content':query})
        self.assertEqual({nid:self.host.snapshot(self.library)['nodes'][nid]['text'] for nid in before},before)

    def test_connection_tool_uses_topic_evidence_too(self):
        status,packet=self.tool('我指的是为什么总背清单')
        self.assertEqual(status,200,packet);self.assert_topic_matches(packet)

    def test_the_same_frame_with_a_real_object_can_still_find_that_object(self):
        status,result=self.context('我指的是你的情绪体检')
        self.assertEqual(status,200,result)
        ids=set(result['memory_ids'])
        self.assertIn(self.emotion,ids)
        self.assertFalse({self.doc,self.next,self.alias_id}&ids,
            [r['value'] for r in result['memory_context']['records']])

    def test_explicit_drink_preference_question_keeps_positive_and_negative_records_without_color_baseline(self):
        drinks={}
        for text in ('测试用户喝咖啡','测试用户不喝咖啡'):
            status,created=self.request('/api/ai/remember',{'text':text,'kind':'preference','important':True})
            self.assertEqual(status,200,created)
            drinks[created['id']]=text
        status,color=self.request('/api/ai/remember',{
            'text':'测试用户喜欢蓝色','kind':'preference','important':True})
        self.assertEqual(status,200,color)
        query='我喜欢什么饮料'
        status,result=self.context(query)
        self.assertEqual(status,200,result);self.assertEqual(result['query'],query)
        rows={row['id']:row for row in result['memory_context']['records']}
        self.assertTrue(set(drinks)<=rows.keys(),[r['value'] for r in rows.values()])
        self.assertNotIn(color['id'],set(rows),[row['value'] for row in rows.values()])
        for nid,text in drinks.items():self.assertEqual(rows[nid]['value'],text)
        self.assertIn('不喝咖啡',json.dumps(result['memory_context'],ensure_ascii=False))
        for question in ('你好','我指的是这个'):
            with self.subTest(query=question):
                status,packet=self.tool(question)
                self.assertEqual(status,200,packet)
                self.assertEqual([r['id'] for r in packet['records']],[])

    def test_bare_reference_never_injects_baseline_or_an_unrelated_old_statement(self):
        for query in ('我指的是','我指的是这个'):
            with self.subTest(query=query):
                status,result=self.context(query);self.assertEqual(status,200,result)
                self.assertEqual(result['query'],query)
                self.assertEqual([r['id'] for r in result['memory_context']['records']],[])
                self.assertEqual(result['memory_context']['relations'],[])
                self.assertEqual(result['memory_ids'],[])
                status,packet=self.tool(query);self.assertEqual(status,200,packet)
                self.assertEqual([r['id'] for r in packet['records']],[])
                # Missing library evidence should not force the host to break
                # an otherwise clear current conversation with a stock question.
                self.assertNotIn('请先澄清',json.dumps(packet,ensure_ascii=False))

    def test_explicit_literal_lookup_still_finds_the_recorded_conversational_phrase(self):
        status,packet=self.tool('查找包含“我指的是”的原话')
        self.assertEqual(status,200,packet)
        ids={record['id'] for record in packet['records']}
        self.assertTrue({self.doc,self.emotion}<=ids,packet)
        encoded=json.dumps(packet,ensure_ascii=False)
        self.assertIn(self.doc_text,encoded);self.assertIn(self.emotion_text,encoded)

    def test_another_authorized_window_or_session_never_becomes_the_referent(self):
        second,token=self.connection(self.library,'window-c')
        status,shared=self.context('反复背清单',cid=second,token=token,window='window-c')
        self.assertEqual(status,200,shared)
        self.assertIn(self.list_id,shared['memory_ids'])
        for cid,secret,window in ((self.cid,self.token,'window-a'),(second,token,'window-c')):
            with self.subTest(window=window):
                status,result=self.context('我指的是这个',cid=cid,token=secret,window=window)
                self.assertEqual(status,200,result);self.assertEqual([r['id'] for r in result['memory_context']['records']],[])
                self.assertEqual(result['memory_ids'],[])
        self.assertEqual(self.context('我指的是这个',window='window-c')[0],400)
        self.assertEqual(self.context('清单',cid=second,token=self.token,window='window-c')[0],403)
        self.assertEqual(self.context('清单',library=self.other)[0],403)
        status,result=self.context('清单',cid=self.other_cid,token=self.other_token,window='window-b',library=self.other)
        self.assertEqual(status,200,result);self.assertEqual(result['memory_context']['records'],[])
        self.assertNotIn(self.list_text,json.dumps(result,ensure_ascii=False))

    def test_more_relevant_queries_do_not_bypass_disable_forget_or_connection_pause(self):
        self.assertEqual(self.context('为什么总背清单')[0],200)
        status,value=self.request(f'/api/memories/{self.list_id}/enabled',{'enabled':False})
        self.assertEqual(status,200,value)
        status,result=self.context('我指的是为什么总背清单')
        self.assertEqual(status,200,result)
        self.assertNotIn(self.list_id,result['memory_ids'])
        self.assertNotIn(self.list_text,json.dumps(result['memory_context'],ensure_ascii=False))
        self.assertEqual(self.request(f'/api/memories/{self.list_id}/enabled',{'enabled':True})[0],200)
        self.assertEqual(self.request(f'/api/memories/{self.list_id}/forget',{'confirm':True})[0],200)
        status,packet=self.tool('查找包含“清单”的原话')
        self.assertEqual(status,200,packet)
        self.assertNotIn(self.list_id,{r['id'] for r in packet['records']})
        self.assertNotIn(self.list_text,json.dumps(packet,ensure_ascii=False))
        self.host.connections.toggle(self.cid,False)
        status,rejected=self.context('我指的是为什么总背清单')
        self.assertIn(status,(400,403),rejected)
        self.assertNotIn(self.list_text,json.dumps(rejected,ensure_ascii=False))

    def test_registered_platform_recent_is_not_the_current_sessions_missing_referent(self):
        status,bundle=self.request('/api/agent/sources',{'name':'合成平台来源','adapter':'sdk',
            'runtime_agent_id':'synthetic-topic-fish','platforms':['qq']})
        self.assertEqual(status,200,bundle)
        client=SourceClient(bundle['private_path'],timeout=2)
        recorded=client.record_dialogue('我们在讨论周末去公园散步。','那就一起看湖边的花。',
            'old-platform-window','old-platform-event',platform='qq',occurred_at=time.time()-10)
        self.assertTrue(recorded['archive_committed'],recorded)
        # Merely naming a platform and saying "just now" is not a known object.
        # A different live conversation must not inherit that old turn as if it
        # supplied the current host's previous question.
        for query in ('我指的是这个','我指的是刚才QQ这个'):
            with self.subTest(query=query):
                result=client.read_context(query,'new-platform-window',max_chars=32000)
                self.assertEqual([r['id'] for r in result['memory_context']['records']],[])
                self.assertEqual(result['platform_recent_ids'],[])
                self.assertEqual(result['history'],[])
                self.assertNotIn('湖边的花',json.dumps(result['memory_context'],ensure_ascii=False))


if __name__=='__main__':unittest.main()
