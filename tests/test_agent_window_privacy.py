"""No foreign-window text reaches disk, even with the memory service offline."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from nkb.service.agent_client import AgentClient,AgentConnectionError,make_agent_config,validate_config,event_from_tool
from tests.test_agent_memory_client import LocalMemoryService
import tests.test_agent_memory_client as connector_fixture

ROOT=Path(__file__).resolve().parents[1]


class AgentWindowPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.secret={'id':'conn_test_agent','library_id':'agent-library','token':'FAKE-ONLY-LOCAL-MEMORY-TOKEN',
                     'session_scope':'next_session','enabled':True,'revoked':False}
        self.bundle=make_agent_config(self.root,self.secret,persist=True);self.path=Path(self.bundle['private_path'])
        self.client=AgentClient(self.path,timeout=.3);self.services=[]
    def tearDown(self):
        self.client.stop()
        for service in self.services:service.close()
        self.temp.cleanup()
    def hook(self,sid='window-A',turn='one',text='OWN-WINDOW-TEXT'):
        return {'session_id':sid,'turn_id':turn,'status':'complete','user':text,'assistant':'Actual reply '+text}
    def all_disk_bytes(self):return b'\n'.join(p.read_bytes() for p in self.root.rglob('*') if p.is_file())
    def service(self):
        # The old fixture uses its own explicit token, copied only to the fake config.
        from tests.test_agent_memory_client import TOKEN
        self.secret['token']=TOKEN;make_agent_config(self.root,self.secret,persist=True)
        service=LocalMemoryService();self.services.append(service)
        runtime=self.root/'.runtime';runtime.mkdir(exist_ok=True)
        (runtime/'app.json').write_text(json.dumps({'pid':os.getpid(),'controller_port':service.port,'service_version':'0.4.0'}))
        return service

    def test_unbound_manual_partial_and_tool_are_not_collected_or_used_to_claim(self):
        cases=[lambda:self.client.submit_hook({**self.hook(text='DO-NOT-COLLECT-PARTIAL'),'status':'partial'}),
               lambda:self.client.submit_hook({'type':'tool','session_id':'window-B','turn_id':'tool','text':'DO-NOT-COLLECT-TOOL','outcome':'success'}),
               lambda:self.client.submit_tool_record('memory_record_turn',{'session_id':'window-B','request_id':'manual','user':'DO-NOT-COLLECT-MANUAL','assistant':'reply'}),
               lambda:self.client.tool('memory_remember',{'session_id':'window-B','text':'DO-NOT-COLLECT-REMEMBER'})]
        for send in cases:
            result=send();self.assertEqual(result['status'],'awaiting_window_binding')
            self.assertFalse(result['saved']);self.assertFalse(result['queued']);self.assertFalse(result['local_queue_committed'])
        self.assertIsNone(self.client.config()['bound_session_id']);self.assertEqual(self.client.pending_count(),0)
        self.assertNotIn(b'DO-NOT-COLLECT',self.all_disk_bytes())

    def test_full_hook_claims_locally_offline_and_restart_rejects_foreign_before_parsing_text(self):
        own=self.client.submit_hook(self.hook());self.assertEqual(own['status'],'queued_offline')
        self.assertEqual(self.client.config()['bound_session_id'],'window-A')
        restarted=AgentClient(self.path,timeout=.3)
        foreign={**self.hook('window-B',text='FOREIGN-PRIVATE-TEXT'),'assistant':'\ud800'}
        with patch('nkb.service.agent_client._atomic_json') as write:
            result=restarted.submit_hook(foreign)
            self.assertEqual(result['status'],'ignored_scope');write.assert_not_called()
        self.assertFalse(result['queued']);self.assertEqual(restarted.pending_count(),1)
        self.assertNotIn(b'FOREIGN-PRIVATE-TEXT',self.all_disk_bytes())

    def test_existing_fixed_session_filters_manual_and_tool_before_outbox(self):
        self.secret['session_scope']='configured-window';make_agent_config(self.root,self.secret,persist=True)
        self.assertEqual(self.client.config()['bound_session_id'],'configured-window')
        result=self.client.submit_tool_record('memory_event',{'session_id':'wrong-window','request_id':'tool',
               'text':'FOREIGN-OBSERVATION','source_url':'https://example.test/','outcome':'observed'})
        self.assertEqual(result['status'],'ignored_scope');self.assertNotIn(b'FOREIGN-OBSERVATION',self.all_disk_bytes())
        accepted=self.client.submit_tool_record('memory_record_turn',{'session_id':'configured-window','request_id':'manual','user':'Own manual text','assistant':'Own actual reply'})
        self.assertTrue(accepted['queued']);self.assertEqual(self.client.pending_count(),1)

    def test_make_config_pause_resume_revoke_and_preview_preserve_local_claim(self):
        self.client.submit_hook(self.hook())
        for change in ({},{'enabled':False},{'enabled':True},{'enabled':False,'revoked':True,'token':''}):
            result=make_agent_config(self.root,{**self.secret,**change},persist=True)
            self.assertEqual(self.client.config()['bound_session_id'],'window-A')
            self.assertEqual(result['connection_config_public']['bound_session_id'],'window-A')
            preview=make_agent_config(self.root,{**self.secret,**change},persist=False)
            self.assertEqual(preview['connection_config_public']['bound_session_id'],'window-A')
        self.assertEqual(self.client.pending_count(),1)

    def test_two_real_hook_processes_racing_can_claim_only_one_window_and_persist_only_its_text(self):
        command=[sys.executable,str(ROOT/'desktop/agent_memory_hook.py'),'--connection-config',str(self.path)]
        processes=[subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                     text=True,encoding='utf-8',cwd=ROOT) for _ in range(2)]
        results=[];barrier=threading.Barrier(2)
        def send(index):
            barrier.wait();data=self.hook('window-'+str(index),text='EXCLUSIVE-SECRET-'+str(index))
            out,err=processes[index].communicate(json.dumps(data),timeout=8)
            results.append((index,processes[index].returncode,json.loads(out),out+err))
        threads=[threading.Thread(target=send,args=(i,)) for i in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=10)
        self.assertEqual(len(results),2)
        self.assertTrue(all(code==0 for _,code,_,_ in results))
        self.assertEqual(sorted(r['status'] for _,_,r,_ in results),['ignored_scope','queued_offline'])
        winner=next(i for i,_,r,_ in results if r['queued'])
        self.assertEqual(self.client.config()['bound_session_id'],'window-'+str(winner))
        self.assertEqual(self.client.pending_count(),1)
        self.assertIn(('EXCLUSIVE-SECRET-'+str(winner)).encode(),self.all_disk_bytes())
        self.assertNotIn(('EXCLUSIVE-SECRET-'+str(1-winner)).encode(),self.all_disk_bytes())
        self.assertTrue(all('EXCLUSIVE-SECRET' not in logs for _,_,_,logs in results))

    def test_reads_and_heartbeat_cannot_claim_local_window(self):
        self.service()
        self.client.heartbeat();self.client.status();self.client.tool('memory_context',{'query':'read-only','session_id':'agent-default'})
        self.assertIsNone(self.client.config()['bound_session_id']);self.assertEqual(self.client.pending_count(),0)

    def test_server_conflict_does_not_rebind_or_discard_own_offline_queue(self):
        self.client.submit_hook(self.hook())
        updated=make_agent_config(self.root,{**self.secret,'session_scope':'server-other-window'},persist=True)
        self.assertTrue(updated['connection_config_public']['scope_conflict'])
        self.assertEqual(self.client.config()['bound_session_id'],'window-A')
        self.service()
        with patch.object(self.client,'_post',return_value={'accepted':False,'saved':False,'status':'scope_conflict','code':'scope_conflict'}):
            result=self.client.drain()
        self.assertEqual(result['status'],'scope_conflict');self.assertEqual(result['pending'],1)
        self.assertEqual(self.client.config()['bound_session_id'],'window-A')
        self.assertNotIn(b'server-other-window',self.all_disk_bytes())

    def test_old_configs_without_scope_remain_explicit_connection_compatible(self):
        old=json.loads(self.path.read_text());old.pop('session_scope');old.pop('bound_session_id')
        self.path.write_text(json.dumps(old))
        self.assertEqual(validate_config(old)['session_scope'],'connection')
        self.assertTrue(self.client.submit_hook(self.hook('old-window-A'))['queued'])
        self.assertTrue(self.client.submit_hook(self.hook('old-window-B','two'))['queued'])
        self.assertEqual(self.client.pending_count(),2)

    def test_direct_manual_envelope_cannot_bypass_first_hook_gate(self):
        event=event_from_tool('memory_record_turn',{'session_id':'window-B','request_id':'manual',
                'user':'DO-NOT-COLLECT-DIRECT','assistant':'Actual old reply'})
        result=self.client.submit_event(event)
        self.assertEqual(result['status'],'awaiting_window_binding');self.assertEqual(self.client.pending_count(),0)
        self.assertNotIn(b'DO-NOT-COLLECT',self.all_disk_bytes())


class RealControllerWindowPrivacyTests(unittest.TestCase):
    boot=connector_fixture.RealControllerAgentConnectorTests.boot
    shutdown=connector_fixture.RealControllerAgentConnectorTests.shutdown
    tearDown=connector_fixture.RealControllerAgentConnectorTests.tearDown
    def setUp(self):
        connector_fixture.RealControllerAgentConnectorTests.setUp(self)
        self.client.stop()
        bundle=self.host.new_connection({'name':'只记一个实际窗口','host':'agent','library_id':self.bound})
        self.cid=bundle['connection']['id'];self.path=Path(bundle['private_path'])
        self.client=AgentClient(self.path,timeout=2,poll_seconds=.05)
        self.assertEqual(self.client.config()['session_scope'],'next_session')
    def test_offline_claim_then_server_ack_config_sync_and_foreign_window_never_reaches_service(self):
        self.shutdown()
        own={'session_id':'chosen-real-window','turn_id':'one','status':'complete','user':'OWN-WINDOW-RECORD','assistant':'Actual own reply'}
        self.assertEqual(self.client.submit_hook(own)['status'],'queued_offline')
        self.assertEqual(self.client.config()['bound_session_id'],'chosen-real-window')
        self.boot()
        self.host.drain_agent_outboxes()
        self.assertEqual(self.client.pending_count(),0)
        self.assertEqual(self.host.connections.get(self.cid)['session_scope'],'chosen-real-window')
        self.assertEqual(self.client.config()['bound_session_id'],'chosen-real-window')
        result=self.client.submit_hook({**own,'session_id':'another-global-window','turn_id':'two','user':'FOREIGN-NEVER-ON-DISK'})
        self.assertEqual(result['status'],'ignored_scope')
        self.assertEqual(len(self.host.connections.activity(self.bound)['events']),1)
        contents=b'\n'.join(p.read_bytes() for p in self.root.rglob('*') if p.is_file())
        self.assertNotIn(b'FOREIGN-NEVER-ON-DISK',contents)
        context=self.client.tool('memory_context',{'query':'OWN-WINDOW','session_id':'chosen-real-window'})
        self.assertIn('OWN-WINDOW-RECORD',json.dumps(context,ensure_ascii=False))
    def test_readonly_queries_do_not_claim_server_or_local_window(self):
        self.client.status();self.client.tool('memory_bootstrap',{})
        self.client.tool('memory_context',{'query':'read only','session_id':'not-the-recording-window'})
        self.assertEqual(self.host.connections.get(self.cid)['session_scope'],'next_session')
        self.assertIsNone(self.client.config()['bound_session_id'])
        result=self.client.submit_tool_record('memory_record_turn',{'session_id':'wrong','request_id':'manual','user':'DO-NOT-COLLECT','assistant':'reply'})
        self.assertEqual(result['status'],'awaiting_window_binding')
        self.assertEqual(self.host.connections.activity(self.bound)['events'],[])



if __name__=='__main__':unittest.main()
