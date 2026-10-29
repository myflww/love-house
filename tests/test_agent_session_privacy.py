"""Default generic capture is one real host window, before any receipt write."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from http.server import ThreadingHTTPServer
from nkb.service.agent_client import event_from_hook, event_from_tool
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller


class AgentSessionPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.host=MemoryHost(Path(self.temp.name),key_store=KeyStore(allow_keychain=False),
            organizer_transport=lambda *_a,**_k: self.fail('Raw recall must not call an organizer model'))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host))
        self.host.controller_port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()
        created=self.host.new_connection({'name':'单窗口记忆','host':'agent','library_id':'default'})
        self.cid=created['connection']['id']
        self.token=self.host.connections.get(self.cid,secret=True)['token']

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.host.stop();self.temp.cleanup()

    def test_setup_text_describes_actual_scope_instead_of_promising_single_window_for_all_mode(self):
        single=self.host.connection_config(self.cid)
        self.assertIn('默认只接收首个真实完整hook绑定的窗口',single['agent_setup_text'])
        advanced=self.host.new_connection({'name':'用户明确选择全部','host':'agent','library_id':'default','session_scope':'connection'})
        self.assertIn('高级整连接范围',advanced['agent_setup_text'])
        self.assertNotIn('其他窗口不记录',advanced['agent_setup_text'])
        self.assertFalse(advanced['connection_config_public']['window_only'])

    def request(self,path,data,token=None):
        request=Request('http://127.0.0.1:'+str(self.server.server_port)+path,
            data=json.dumps(data,ensure_ascii=False).encode(),
            headers={'Content-Type':'application/json','Authorization':'Bearer '+(token or self.token)})
        try:
            with urlopen(request,timeout=10) as response:return response.status,json.load(response)
        except HTTPError as response:return response.code,json.load(response)

    def event(self,data):return self.request('/api/connections/'+self.cid+'/events',data)

    def tool(self,name,arguments=None):
        return self.request('/api/connections/'+self.cid+'/tool',{'name':name,'arguments':arguments or {}})

    def hook(self,sid='chosen-window',rid='first',status='complete',kind='turn'):
        data={'session_id':sid,'turn_id':rid,'status':status,'type':kind,
              'user':'本窗口真实原话','assistant':'本窗口真实回复','text':'真实工具观察'}
        return event_from_hook(data)

    def counts(self):
        with self.host.connections.db() as db:
            return db.execute('SELECT COUNT(*) FROM receipts WHERE connection_id=?',(self.cid,)).fetchone()[0]

    def scope(self):return self.host.connections.get(self.cid)['session_scope']

    def test_new_generic_connections_default_to_next_real_window_and_old_explicit_all_remains(self):
        self.assertEqual(self.scope(),'next_session')
        old=self.host.new_connection({'name':'显式全连接','host':'agent','library_id':'default','session_scope':'connection'})
        self.assertEqual(old['connection']['session_scope'],'connection')

    def test_heartbeat_and_all_read_surfaces_do_not_claim_a_pending_window(self):
        self.assertEqual(self.request('/api/connections/'+self.cid+'/heartbeat',{})[0],200)
        for name,args in [('memory_status',{}),('memory_bootstrap',{}),('memory_list',{}),
                          ('memory_context',{'query':'有没有旧记忆'}),('memory_context',{'query':'看看旧记忆','session_id':'a-read-only-window'})]:
            code,result=self.tool(name,args)
            self.assertEqual(code,200,result)
            self.assertEqual(self.scope(),'next_session')
        self.assertEqual(self.counts(),0)

    def test_partial_observation_and_manual_records_cannot_claim_or_write_raw(self):
        attempts=[self.hook(status='partial'),self.hook(kind='tool'),
            event_from_tool('memory_record_turn',{'session_id':'other','request_id':'m','user':'其它窗口原话','assistant':'其它窗口回复'})]
        for event in attempts:
            status,result=self.event(event)
            self.assertEqual(status,200,result)
            self.assertFalse(result['accepted']);self.assertFalse(result['saved'])
            self.assertEqual(result['code'],'awaiting_window_binding')
            self.assertNotIn('其它窗口原话',json.dumps(result,ensure_ascii=False))
        status,result=self.tool('memory_remember',{'text':'不应采集的手动内容','session_id':'other'})
        self.assertEqual(status,200,result);self.assertEqual(result['code'],'awaiting_window_binding')
        self.assertEqual(self.scope(),'next_session');self.assertEqual(self.counts(),0)
        self.assertEqual(self.host.snapshot('default')['nodes'],{})

    def test_only_complete_real_hook_can_bind_then_original_is_recallable_without_model_key(self):
        for mutate in [lambda e:e['record'].update(schema='love-house-agent-tool/v1'),
                       lambda e:e['normalized'].update(assistant=''),
                       lambda e:e['normalized'].update(origin='manual_record')]:
            event=self.hook();mutate(event)
            self.assertEqual(self.event(event)[1]['code'],'awaiting_window_binding')
        code,result=self.event(self.hook())
        self.assertEqual(code,200,result);self.assertTrue(result['accepted'])
        self.assertEqual(result['bound_session_id'],'chosen-window');self.assertEqual(self.scope(),'chosen-window')
        self.assertEqual(self.counts(),1)
        code,context=self.tool('memory_context',{'query':'本窗口真实原话','session_id':'chosen-window'})
        self.assertEqual(code,200,context);self.assertIn('本窗口真实原话',json.dumps(context,ensure_ascii=False))
        self.assertFalse(self.host.organizer_view('default')['provider']['credential_ready'])

    def test_fixed_window_rejects_foreign_hook_tool_and_remember_before_receipts(self):
        self.assertTrue(self.event(self.hook())[1]['accepted']);before=self.host.snapshot('default')
        code,foreign=self.event(self.hook('other-window','foreign'))
        self.assertEqual(code,200,foreign);self.assertEqual(foreign['code'],'scope_conflict');self.assertFalse(foreign['accepted'])
        code,manual=self.event(event_from_tool('memory_record_turn',{'session_id':'other-window','request_id':'bad',
            'user':'FOREIGN-NOT-TO-BE-COLLECTED','assistant':'foreign reply'}))
        self.assertEqual(code,200,manual);self.assertEqual(manual['code'],'ignored_scope')
        code,remember=self.tool('memory_remember',{'session_id':'other-window','text':'FOREIGN-NOT-TO-BE-COLLECTED'})
        self.assertEqual(code,200,remember);self.assertEqual(remember['code'],'ignored_scope')
        self.assertEqual(self.counts(),1);self.assertEqual(self.host.snapshot('default'),before)
        with self.host.connections.db() as db:
            self.assertFalse(any('FOREIGN-NOT-TO-BE-COLLECTED' in row[0] for row in db.execute('SELECT payload FROM receipts')))

    def test_fixed_context_requires_matching_real_session_and_never_falls_back_to_placeholder(self):
        self.assertTrue(self.event(self.hook())[1]['accepted'])
        for args in [{'query':'原话'},{'query':'原话','session_id':'other-window'}]:
            code,result=self.tool('memory_context',args)
            self.assertEqual(code,400,result);self.assertNotIn('本窗口真实原话',json.dumps(result,ensure_ascii=False))
        for name in ('memory_bootstrap','memory_list'):
            self.assertEqual(self.tool(name)[0],200)
        self.assertEqual(self.scope(),'chosen-window')

    def test_same_window_manual_suggestion_and_persona_are_allowed_only_after_binding(self):
        pending={'text':'温柔的人格','user_request':'请导入人格：温柔的人格','explicit':True,
                 'session_id':'chosen-window','request_id':'persona'}
        self.assertEqual(self.tool('memory_persona_import',pending)[1]['code'],'awaiting_window_binding')
        self.assertTrue(self.event(self.hook())[1]['accepted'])
        code,remember=self.tool('memory_remember',{'text':'本窗口建议保留的偏好','session_id':'chosen-window'})
        self.assertEqual(code,200,remember);self.assertTrue(remember.get('id'))
        self.assertTrue(self.tool('memory_persona_import',pending)[1]['accepted'])
        self.assertEqual(self.counts(),2)

    def test_racing_first_complete_hooks_bind_one_window_and_never_store_loser(self):
        barrier=threading.Barrier(2)
        def submit(sid):
            barrier.wait()
            return sid,self.event(self.hook(sid,sid))[1]
        with ThreadPoolExecutor(max_workers=2) as workers:results=list(workers.map(submit,['window-a','window-b']))
        accepted=[(sid,r) for sid,r in results if r.get('accepted')]
        rejected=[(sid,r) for sid,r in results if not r.get('accepted')]
        self.assertEqual(len(accepted),1,results);self.assertEqual(len(rejected),1,results)
        self.assertEqual(self.scope(),accepted[0][0]);self.assertEqual(rejected[0][1]['code'],'scope_conflict')
        self.assertEqual(self.counts(),1)

    def test_reopening_store_keeps_binding_and_does_not_enroll_another_window(self):
        self.assertTrue(self.event(self.hook())[1]['accepted'])
        from nkb.service.connections import ConnectionStore
        reopened=ConnectionStore(Path(self.temp.name))
        self.assertEqual(reopened.get(self.cid)['session_scope'],'chosen-window')
        self.assertFalse(self.event(self.hook('after-restart-other','later'))[1]['accepted'])
        self.assertTrue(self.event(self.hook('chosen-window','later'))[1]['accepted'])
        self.assertEqual(self.counts(),2)

    def test_harness_fixed_scope_still_rejects_other_window_before_raw_receipt(self):
        created=self.host.connections.create('独立Harness窗口','harness','default','chosen-harness-window')
        cid=created['id'];token=self.host.connections.get(cid,secret=True)['token']
        def send(sid):
            event={'session_id':sid,'event_id':sid,'event_type':'turn/end',
                   'record':{'schema':'deepseek-harness-event/v1','normalized':{'type':'turn',
                   'status':'complete','turn_id':sid,'user':'正确窗口才应保存','assistant':'实际回复'}}}
            return self.request('/api/connections/'+cid+'/events',event,token)
        self.assertEqual(send('unconfigured-window')[0],400)
        with self.host.connections.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts WHERE connection_id=?',(cid,)).fetchone()[0],0)
        self.assertTrue(send('chosen-harness-window')[1]['accepted'])
        self.assertEqual(send('another-unconfigured-window')[0],400)
        with self.host.connections.db() as db:
            rows=db.execute('SELECT session_id FROM receipts WHERE connection_id=?',(cid,)).fetchall()
        self.assertEqual([row[0] for row in rows],['chosen-harness-window'])

