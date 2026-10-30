"""Synthetic host events prove delivery, never the host's automatic installation."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from nkb.errors import ValidationError
from nkb.service.agent_client import AgentClient, event_from_hook
from nkb.service.connections import ConnectionStore
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller


class ConnectionStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.host=MemoryHost(self.root,key_store=KeyStore(allow_keychain=False))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host))
        self.host.controller_port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()
        self.client=build_opener(ProxyHandler({}))
        self.bundle=self.host.new_connection({'name':'WorkBuddy fixture','host':'agent','library_id':'default'})
        self.cid=self.bundle['connection']['id']
        self.token=self.host.connections.get(self.cid,secret=True)['token']

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.host.stop();self.temp.cleanup()

    def request(self,path,body=None,headers=None):
        request=Request('http://127.0.0.1:'+str(self.server.server_port)+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json',**(headers or {})})
        try:response=self.client.open(request,timeout=8)
        except HTTPError as exc:response=exc
        with response:
            data=response.read()
            return response.status,(json.loads(data) if 'json' in response.headers.get('Content-Type','') else data),response.headers

    def hook(self,session='fixture-window-a',turn='one',token=None):
        event=event_from_hook({'session_id':session,'turn_id':turn,'status':'complete',
                              'user':'合成测试原话 '+session,'assistant':'合成测试最终回复 '+turn})
        return self.host.accept(self.cid,token or self.token,event)

    def status(self):
        return self.host.agent_tool(self.cid,self.token,{'name':'memory_status','arguments':{}})

    def test_binding_policy_stays_enum_and_capabilities_describe_actual_write_gate(self):
        before=self.status()
        self.assertTrue(before['can_read']);self.assertFalse(before['can_write'])
        self.assertTrue(before['read_only']);self.assertTrue(before['memory_only'])
        rejection=self.host.agent_tool(self.cid,self.token,{'name':'memory_record_turn','arguments':{
            'session_id':'manual-window','request_id':'manual-one','user':'不会抢占窗口','assistant':'不会写入'}})
        self.assertEqual(rejection['next_action'],'configure_host_turn_end_hook')
        self.assertEqual(rejection['binding_actor'],'source_adapter')
        self.assertFalse(rejection['manual_record_claims_window'])
        self.assertIn('手动补录不会占用窗口',rejection['next_action_message'])
        self.assertTrue(self.hook()['accepted'])
        connection=self.host.connections.get(self.cid)
        self.assertEqual(connection['session_scope'],'next_session')
        self.assertEqual(connection['session_scope_policy'],'next_session')
        self.assertEqual(connection['bound_session_id'],'fixture-window-a')
        after=self.status()
        self.assertTrue(after['can_write']);self.assertFalse(after['read_only'])
        self.assertEqual(after['binding_state'],'bound')
        self.host.connections.toggle(self.cid,False)
        paused=self.host.connections.get(self.cid)
        self.assertFalse(paused['can_read']);self.assertFalse(paused['can_write'])

    def test_even_multiple_hook_events_cannot_attest_automatic_host_registration(self):
        for turn in ('one','two','three'):self.hook(turn=turn)
        state=self.status()
        self.assertEqual(state['capture_mode'],'host_hook_received')
        self.assertEqual(state['connection']['archive_status'],'host_reported')
        self.assertFalse(state['automatic_memory'])
        self.assertEqual(state['capture']['hook_event_count'],3)
        self.assertEqual(state['capture']['hook_dialogues_saved'],3)
        self.assertEqual(state['capture']['automatic_dialogues_saved'],0)
        self.assertEqual(state['capture']['auto_streak'],0)
        self.assertIsNotNone(state['capture']['last_hook_at'])
        self.assertTrue(self.hook(turn='three')['duplicate'])
        self.assertEqual(self.status()['capture']['hook_event_count'],3)

    def test_bound_generic_sender_cannot_claim_other_adapter_schemas_are_automatic(self):
        self.hook()
        for schema in ('deepseek-harness-event/v1','neural-api-proxy/v1','neural-api-tool/v1'):
            event=event_from_hook({'session_id':'fixture-window-a','turn_id':schema,'status':'complete',
                                  'user':'合成宿主原话 '+schema,'assistant':'合成宿主回复'})
            event['record']['schema']=schema
            self.assertTrue(self.host.accept(self.cid,self.token,event)['accepted'])
            state=self.status()
            self.assertFalse(state['automatic_memory'])
            self.assertEqual(state['capture']['automatic_dialogues_saved'],0)
            foreign=event_from_hook({'session_id':'foreign-window','turn_id':schema,'status':'complete',
                                    'user':'FOREIGN-SCHEMA-CANNOT-BYPASS-SCOPE','assistant':'合成其它窗口回复'})
            foreign['record']['schema']=schema
            self.assertFalse(self.host.accept(self.cid,self.token,foreign)['accepted'])
        with self.host.connections.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0],4)
            self.assertFalse(any('FOREIGN-SCHEMA-CANNOT-BYPASS-SCOPE' in row[0] for row in db.execute('SELECT payload FROM receipts')))
        self.host.connections.configured(self.cid)
        self.assertFalse(self.status()['automatic_memory'])  # Earlier claims are not promoted retrospectively.
        event=event_from_hook({'session_id':'fixture-window-a','turn_id':'configured-real-adapter','status':'complete',
                              'user':'配置后合成原话','assistant':'配置后合成回复'})
        event['record']['schema']='deepseek-harness-event/v1'
        self.assertTrue(self.host.accept(self.cid,self.token,event)['accepted'])
        self.assertTrue(self.status()['automatic_memory'])
        self.assertEqual(self.status()['capture']['automatic_dialogues_saved'],1)

    def test_rebind_requires_confirmation_and_current_binding_then_invalidates_old_host(self):
        self.hook()
        before=self.host.snapshot('default')
        old_path=Path(self.bundle['private_path'])
        old_client=AgentClient(old_path)
        old_outbox=old_client.config()['outbox_dir']
        for body in ({'expected_bound_session_id':'fixture-window-a'},
                     {'confirm':True,'expected_bound_session_id':'stale-window'}):
            with self.assertRaises(ValidationError):self.host.rebind_connection(self.cid,body)
        result=self.host.rebind_connection(self.cid,{'confirm':True,'expected_bound_session_id':'fixture-window-a'})
        current=result['connection']
        self.assertEqual(current['binding_revision'],1)
        self.assertEqual(current['session_scope'],'next_session')
        self.assertIsNone(current['bound_session_id'])
        self.assertEqual(current['capture']['hook_event_count'],0)
        self.assertEqual(self.host.snapshot('default'),before)
        self.assertFalse(old_client.config()['enabled'])
        self.assertNotEqual(result['private_path'],str(old_path))
        self.assertNotEqual(AgentClient(result['private_path']).config()['outbox_dir'],old_outbox)
        with self.assertRaises(ValidationError):self.hook(turn='old-cannot-reclaim')
        new_token=self.host.connections.get(self.cid,secret=True)['token']
        self.assertNotEqual(new_token,self.token)
        self.assertTrue(self.hook(session='fixture-window-b',token=new_token)['accepted'])
        self.assertEqual(self.host.connections.get(self.cid)['bound_session_id'],'fixture-window-b')
        self.assertEqual(len(self.host.snapshot('default')['nodes']),2)
        with self.host.connections.db() as db:
            receipts=db.execute('SELECT session_id,binding_revision FROM receipts ORDER BY received').fetchall()
        self.assertEqual([tuple(r) for r in receipts],[('fixture-window-a',0),('fixture-window-b',1)])

    def test_reopening_config_repairs_failed_rebind_file_without_new_rotation(self):
        self.hook()
        original=self.host.snapshot('default')
        old_client=AgentClient(self.bundle['private_path'])
        with patch.object(self.host,'update_agent_config',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.host.rebind_connection(self.cid,{'confirm':True,'expected_bound_session_id':'fixture-window-a'})
        rotated=self.host.connections.get(self.cid,secret=True)
        self.assertEqual(rotated['binding_revision'],1)
        self.assertNotEqual(rotated['token'],self.token)
        with self.assertRaises(ValidationError):self.hook(turn='old-after-failure')
        repaired=self.host.connection_config(self.cid)
        self.assertTrue(repaired['configuration_ready'])
        self.assertTrue(Path(repaired['private_path']).is_file())
        self.assertFalse(old_client.config()['enabled'])
        self.assertTrue(old_client.config()['revoked'])
        self.assertEqual(old_client.config()['token'],'')
        self.assertEqual(self.host.connections.get(self.cid,secret=True)['token'],rotated['token'])
        self.assertEqual(repaired['connection']['binding_revision'],1)
        self.assertIsNone(repaired['connection']['bound_session_id'])
        self.assertEqual(self.host.snapshot('default'),original)
        self.assertTrue(self.hook(session='fixture-window-b',token=rotated['token'])['accepted'])

    def test_local_ui_session_is_required_for_enumeration_config_and_rebind(self):
        route='/api/connections/'+self.cid
        for path in ('/api/connections',route+'/config','/api/memory/status','/api/activity'):
            code,data,_=self.request(path)
            self.assertEqual(code,401,data)
            self.assertNotIn(self.cid,json.dumps(data))
        code,_,headers=self.request('/')
        self.assertEqual(code,200)
        cookie=headers['Set-Cookie']
        self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
        auth={'Cookie':cookie.split(';')[0]}
        self.assertEqual(self.request('/api/connections',headers=auth)[0],200)
        self.assertEqual(self.request(route+'/config',headers={**auth,'Authorization':'Bearer '+self.token})[0],403)
        self.assertEqual(self.request('/api/connections',headers={**auth,'Origin':'https://foreign.invalid'})[0],403)
        body={'confirm':True,'expected_bound_session_id':None}
        self.assertEqual(self.request(route+'/rebind',body)[0],401)
        self.assertEqual(self.request(route+'/rebind',body,{**auth,'Origin':'https://foreign.invalid'})[0],403)
        code,result,_=self.request(route+'/rebind',body,auth)
        self.assertEqual(code,200,result)
        self.assertEqual(result['connection']['binding_revision'],1)

    def test_workbuddy_install_plan_needs_ui_and_does_not_mark_harness_installed(self):
        route='/api/connections/'+self.cid+'/workbuddy/configure'
        self.assertEqual(self.request(route,{'apply':True})[0],401)
        _,_,headers=self.request('/')
        auth={'Cookie':headers['Set-Cookie'].split(';')[0]}
        with patch('nkb.service.agent_client.configure_workbuddy',return_value={
                'applied':True,'readback_verified':True,'hook_supported':False}) as configure:
            code,result,_=self.request(route,{'apply':True},auth)
        self.assertEqual(code,200,result)
        self.assertFalse(result['hook_supported'])
        configure.assert_called_once()
        self.assertIsNone(self.host.connections.get(self.cid)['configured_at'])
        self.assertEqual(self.request(route,{'apply':True,'home':'D:/not-allowed'},auth)[0],400)


class ScopeMigrationTests(unittest.TestCase):
    def test_legacy_scopes_migrate_without_losing_binding_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ConnectionStore(directory)
            cases=[('connection','any',None),('next_session','next_session',None),
                   ('fixture-existing-window','fixed','fixture-existing-window')]
            identities=[]
            for old,policy,bound in cases:
                current=store.create('Legacy fixture','agent','default','next_session')
                with store.db() as db:
                    db.execute('UPDATE connections SET session_scope=?,session_scope_policy=NULL WHERE id=?',(old,current['id']))
                identities.append((current['id'],store.get(current['id'],secret=True)['token'],policy,bound))
            reopened=ConnectionStore(directory)
            for cid,token,policy,bound in identities:
                result=reopened.get(cid,secret=True)
                self.assertEqual(result['session_scope'],policy)
                self.assertEqual(result['session_scope_policy'],policy)
                self.assertEqual(result['bound_session_id'],bound)
                self.assertEqual(result['token'],token)
                self.assertEqual(result['binding_revision'],0)
            reopened.authorize_session(identities[2][0],'fixture-existing-window')
            with self.assertRaises(ValidationError):reopened.authorize_session(identities[2][0],'foreign-window')
            self.assertEqual(ConnectionStore.adapter_scope(reopened.get(identities[2][0])),'fixture-existing-window')
            self.assertEqual(ConnectionStore.adapter_scope(reopened.get(identities[0][0])),'connection')

    def test_legacy_hook_claim_is_corrected_without_rewriting_original_payload_or_receipt_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ConnectionStore(directory)
            connection=store.create('Legacy hook fixture','agent','default','fixture-existing-window')
            secret=store.get(connection['id'],secret=True)
            event=event_from_hook({'session_id':'fixture-existing-window','turn_id':'old-one','status':'complete',
                                  'user':'旧合成原话\n逐字保留','assistant':'旧合成回复'})
            received=store.receive(secret,event)
            store.applied(received['receipt_id'],['synthetic-node-id'])
            original=store.receipt(connection['id'],'fixture-existing-window',event['event_id'])
            with store.db() as db:
                db.execute("UPDATE connections SET session_scope='fixture-existing-window',session_scope_policy=NULL,bound_session_id=NULL,archive_status='automatic_connected' WHERE id=?",(connection['id'],))
                db.execute('UPDATE receipts SET semantic_type=NULL,is_automatic=NULL,source_schema=NULL WHERE id=?',(received['receipt_id'],))
            reopened=ConnectionStore(directory)
            state=reopened.get(connection['id'])
            self.assertEqual(state['session_scope'],'fixed')
            self.assertEqual(state['bound_session_id'],'fixture-existing-window')
            self.assertEqual(state['archive_status'],'host_reported')
            self.assertFalse(state['automatic_memory'])
            self.assertEqual(state['capture']['hook_event_count'],1)
            receipt=reopened.receipt(connection['id'],'fixture-existing-window',event['event_id'])
            self.assertEqual(receipt['id'],received['receipt_id'])
            self.assertEqual(receipt['payload'],original['payload'])
            self.assertEqual(receipt['payload_hash'],original['payload_hash'])


if __name__=='__main__':unittest.main()
