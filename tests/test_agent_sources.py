"""Source registration/SDK tests use only synthetic identities and loopback."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from nkb.errors import ValidationError
from nkb.service.connections import ConnectionStore
from nkb.service.agent_sources import AgentSourceRegistry
from nkb.service.source_client import (SourceClient, SourceClientError, validate_config,
                                       validate_base_url, _write_private_json)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='love-house-source-test-')
        self.root=Path(self.temp.name);self.connections=ConnectionStore(self.root)
        self.registry=AgentSourceRegistry(self.root,self.connections)

    def tearDown(self):self.temp.cleanup()

    def register(self,library='one',adapter='sdk',**extra):
        return self.registry.register(library,{'name':'合成活动来源','adapter':adapter,'runtime_agent_id':'runtime-fish-a',**extra})

    def test_two_sources_share_one_agent_without_sharing_credentials(self):
        a=self.register(adapter='astrbot');b=self.register(adapter='sdk')
        self.assertEqual(len(self.registry.list('one')),2)
        self.assertNotEqual(a['source']['id'],b['source']['id'])
        self.assertEqual(a['source']['agent_id'],b['source']['agent_id'])
        ca=json.loads(Path(a['private_path']).read_text());cb=json.loads(Path(b['private_path']).read_text())
        self.assertNotEqual(ca['token'],cb['token'])
        self.assertNotIn(ca['token'],json.dumps(self.registry.list('one')))
        self.assertNotIn('private_path',json.dumps(self.registry.list('one')))
        self.assertEqual(self.connections.get(ca['connection_id'])['session_scope'],'connection')
        self.assertFalse(a['source']['full_activity_coverage_verified'])
        if os.name!='nt':
            self.assertEqual(stat.S_IMODE(Path(a['private_path']).stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(Path(a['private_path']).parent.stat().st_mode),0o700)

    def test_registration_validates_before_any_connection_or_private_file(self):
        for data in [{'name':'x','adapter':'sdk','runtime_agent_id':''},
                     {'name':'x','adapter':'sdk','runtime_agent_id':'a','api_key':'FAKE-NOT-A-KEY'},
                     {'name':'x','adapter':'unknown','runtime_agent_id':'a'},
                     {'name':'x','adapter':'sdk','runtime_agent_id':'a','platforms':['*','qq']}]:
            with self.subTest(data=data),self.assertRaises(ValidationError):self.registry.register('one',data)
        self.assertEqual(self.connections.list(),[])
        self.assertEqual(list(self.registry.directory.glob('*.json')),[])

    def test_registration_file_failure_rolls_back_source_and_connection(self):
        with patch('nkb.service.agent_sources._write_private_json',side_effect=OSError('fake full disk')):
            with self.assertRaises(OSError):self.register()
        self.assertEqual(self.connections.list(),[]);self.assertEqual(self.registry.list('one'),[])

    def test_registered_identity_is_checked_before_receive_and_old_windows_unchanged(self):
        bundle=self.register(platforms=['qq']);source=bundle['source']
        c=self.connections.get(source['connection_id'],secret=True)
        e={'source_id':source['id'],'runtime_agent_id':'runtime-fish-a','library_id':'one',
           'platform':'qq','session_id':'qq:one','event_id':'m1',
           'record':{'normalized':{'type':'turn','status':'complete','user':'合成原话','assistant':'合成回复'}}}
        self.registry.check_source_event(c,e)
        for extra in [{'source_id':'source_'+'0'*32},{'runtime_agent_id':'another-fish'},
                      {'agent_id':'other'},{'library_id':'other'},{'platform':'browser'}]:
            with self.subTest(extra=extra),self.assertRaises(ValidationError):
                self.registry.check_source_event(c,{**e,**extra})
        old=self.connections.create('旧单窗','agent','one','next_session')
        self.registry.check_source_event(self.connections.get(old['id'],secret=True),{'arbitrary':'old adapter contract'})
        self.assertEqual(self.connections.get(old['id'])['session_scope'],'next_session')
        self.assertFalse(self.connections.activity('one')['events'])

    def test_unknown_normalization_and_nested_identity_conflicts_are_not_queued(self):
        bundle=self.register();s=bundle['source'];c=self.connections.get(s['connection_id'],secret=True)
        e={'source_id':s['id'],'runtime_agent_id':s['runtime_agent_id'],'platform':'browser',
           'record':{'normalized':{'type':'action','status':'complete'}}}
        with self.assertRaises(ValidationError):self.registry.check_source_event(c,e)
        e['record']['normalized']={'type':'tool','library_id':'other'}
        with self.assertRaises(ValidationError):self.registry.check_source_event(c,e)
        e['record']={'raw_event':{'agent_id':'quoted-third-party'}}
        self.registry.check_source_event(c,e)  # External quoted data cannot override authority.

    def test_context_removes_verified_identity_but_rejects_unknown_arguments(self):
        bundle=self.register();s=bundle['source'];c=self.connections.get(s['connection_id'],secret=True)
        data={'source_id':s['id'],'runtime_agent_id':s['runtime_agent_id'],'agent_id':'one','library_id':'one',
              'query':'旧约定','session_id':'new-window','max_chars':2000}
        self.assertEqual(self.registry.check_context(c,data),{'query':'旧约定','session_id':'new-window','max_chars':2000})
        for bad in ({**data,'library_id':'other'},{**data,'provider':'arbitrary'},{'query':'no source'}):
            with self.assertRaises(ValidationError):self.registry.check_context(c,bad)

    def test_normalized_evidence_cannot_forge_source_platform_or_occurrence_time(self):
        bundle=self.register();s=bundle['source'];c=self.connections.get(s['connection_id'],secret=True)
        base={'source_id':s['id'],'runtime_agent_id':s['runtime_agent_id'],'platform':'browser','occurred_at':1000,
              'record':{'normalized':{'type':'tool','text':'实际看到天气','status':'complete','evidence':{}}}}
        for evidence in [{'platform':'qq'},{'source_id':'other'},{'source_runtime_agent_id':'other'},
                         {'source_event_at':999},{'source_event_at':True}]:
            event=deepcopy(base);event['record']['normalized']['evidence']=evidence
            with self.subTest(evidence=evidence),self.assertRaises(ValidationError):self.registry.check_source_event(c,event)
        base['record']['normalized']['evidence']['source_event_at']=1000
        self.registry.check_source_event(c,base)

    def test_pause_and_disconnect_refresh_private_config_and_stop_new_spooling(self):
        bundle=self.register();s=bundle['source'];client=SourceClient(bundle['private_path'],timeout=.05)
        self.registry.set_enabled(s['id'],False)
        with self.assertRaises(SourceClientError):client.record_observation('实际观察','s','e',platform='browser')
        self.assertEqual(client.status()['pending'],0)
        self.registry.set_enabled(s['id'],True)
        result=client.record_observation('实际观察','s','e',platform='browser')
        self.assertTrue(result['queued'])
        self.registry.set_enabled(s['id'],False,disconnect=True)
        self.assertTrue(client.status()['revoked']);self.assertEqual(client.status()['pending'],1)
        self.assertEqual(client.drain()['status'],'paused')
        self.assertNotIn('token',json.dumps(self.registry.get(s['id'])))

    def test_source_paths_cannot_be_selected_by_untrusted_id(self):
        for value in ('../../private','source_'+'a'*31,'source_'+'g'*32):
            with self.assertRaises(ValidationError):self.registry.configuration(value)


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='love-house-source-sdk-test-');self.root=Path(self.temp.name)
        self.connections=ConnectionStore(self.root);self.registry=AgentSourceRegistry(self.root,self.connections)
        self.bundle=self.registry.register('one',{'name':'测试宿主','adapter':'astrbot','runtime_agent_id':'runtime-a','platforms':['qq','browser']})
        self.path=Path(self.bundle['private_path']);self.cfg=json.loads(self.path.read_text());self.events=[];self.online=True;self.redirect=None
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,body,status=200):
                raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if owner.redirect:
                    self.send_response(307);self.send_header('Location',owner.redirect);self.send_header('Content-Length','0');self.end_headers();return
                try:
                    c=owner.connections.authenticate(owner.cfg['connection_id'],self.headers.get('Authorization','')[7:])
                    if self.path.endswith('/context'):
                        clean=owner.registry.check_context(c,body)
                        return self.respond({'library_id':'one','memory_context':{'records':[{'value':'合成往事'}]},'query':clean['query']})
                    owner.registry.check_source_event(c,body)
                    result=owner.connections.receive(c,body);owner.events.append(body)
                    return self.respond({**result,'library_id':'one'})
                except Exception:return self.respond({'error':'safe test rejection'},403)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.registry.configuration(self.bundle['source']['id'],base_url='http://127.0.0.1:'+str(self.server.server_port))
        self.client=SourceClient(self.path,timeout=.2)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def test_actual_dialogue_and_cross_platform_observation_are_scoped_durable(self):
        a=self.client.record_dialogue('晚上想看海','我们去查潮汐吧','qq-window','one',platform='qq',delivery_status='generated')
        b=self.client.record_observation('查到当地潮汐时间','browser-task','two',platform='browser',source_url='https://example.test/tide?token=REMOVE#f',outcome='observed')
        self.assertTrue(a['archive_committed']);self.assertTrue(b['archive_committed']);self.assertEqual(self.client.status()['pending'],0)
        self.assertEqual({e['library_id'] for e in self.events},{'one'})
        turn=self.events[0]['record']['normalized'];self.assertEqual(turn['evidence']['delivery_status'],'generated')
        self.assertEqual(self.events[1]['record']['normalized']['source_url'],'https://example.test/tide')
        self.assertNotIn(self.cfg['token'],json.dumps(self.events))
        context=self.client.read_context('刚刚看海的约定','new-conversation')
        self.assertEqual(context['library_id'],'one');self.assertIn('合成往事',json.dumps(context,ensure_ascii=False))

    def test_retry_without_explicit_timestamp_is_idempotent_across_client_restart(self):
        first=self.client.record_dialogue('原话','真实可见回复','s','same',platform='qq')
        second=SourceClient(self.path,timeout=.2).record_dialogue('原话','真实可见回复','s','same',platform='qq')
        self.assertFalse(first['duplicate']);self.assertTrue(second['duplicate'])
        self.assertEqual(len(self.connections.archives('one')),1)
        with self.assertRaises(SourceClientError):self.client.record_dialogue('不同原话','真实可见回复','s','same',platform='qq')

    def test_offline_spool_survives_restart_and_only_acknowledged_source_is_removed(self):
        def offline(request,**kw):raise OSError('synthetic offline')
        client=SourceClient(self.path,transport=offline)
        result=client.record_observation('在网页看到了海边天气','s','off',platform='browser',details={'api_key':'FAKE-SHOULD-NOT-BE-STORED','nested':{'authorization':'FAKE-OTHER','stage':'observed'}})
        self.assertTrue(result['queued']);self.assertEqual(client.status()['pending'],1)
        queue=list(Path(self.cfg['outbox_dir']).glob('*.json'));self.assertEqual(len(queue),1)
        self.assertNotIn('FAKE-SHOULD',queue[0].read_text());self.assertNotIn('FAKE-OTHER',queue[0].read_text())
        if os.name!='nt':self.assertEqual(stat.S_IMODE(queue[0].stat().st_mode),0o600)
        restored=SourceClient(self.path,timeout=.2);self.assertEqual(restored.drain()['pending'],0)
        self.assertEqual(len(self.connections.archives('one')),1)

    def test_wrong_identity_or_unregistered_platform_does_not_touch_outbox(self):
        event={'source_id':'source_'+'0'*32,'runtime_agent_id':'runtime-a','library_id':'one','platform':'qq','session_id':'s','event_id':'e'}
        with self.assertRaises(SourceClientError):self.client.submit_event(event)
        with self.assertRaises(SourceClientError):self.client.record_observation('wrong platform','s','e',platform='unregistered')
        self.assertEqual(self.client.status()['pending'],0);self.assertEqual(self.events,[])

    def test_response_cannot_move_memory_to_another_identity(self):
        client=SourceClient(self.path,transport=lambda req,**kw:{'library_id':'other','accepted':True,'status':'saved'})
        queued=client.record_observation('原文仍需保存','s','e',platform='qq')
        self.assertTrue(queued['queued']);self.assertEqual(queued['reason'],'scope_mismatch')
        with self.assertRaises(SourceClientError):client.read_context('不能跨库','s')

    def test_configuration_and_endpoints_do_not_accept_vendor_keys_or_public_plaintext(self):
        for url in ('http://example.test','https://user:password@example.test','https://example.test/?token=FAKE','file:///tmp/x'):
            with self.assertRaises(SourceClientError):validate_base_url(url)
        self.assertEqual(validate_base_url('https://memory.example.test/service/'),'https://memory.example.test/service')
        with self.assertRaises(SourceClientError):validate_config({**self.cfg,'api_key':'FAKE-NOT-A-KEY'})
        with self.assertRaises(SourceClientError):validate_config({**self.cfg,'outbox_dir':str(self.root/'another-source')})

    def test_local_runtime_hint_finds_new_controller_port(self):
        cfg=json.loads(self.path.read_text());cfg['base_url']='http://127.0.0.1:1';_write_private_json(self.path,cfg)
        runtime=Path(cfg['runtime_dir']);runtime.mkdir();(runtime/'app.json').write_text(json.dumps({'service_version':'0.4.0','controller_port':self.server.server_port}))
        result=self.client.record_observation('重启后观察','s','port',platform='browser')
        self.assertTrue(result['accepted']);self.assertEqual(self.client.status()['pending'],0)

    def test_vendor_copy_imports_without_project_packages(self):
        source=Path(__file__).resolve().parents[1]/'nkb/service/source_client.py'
        spec=importlib.util.spec_from_file_location('standalone_source_sdk',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module.SCHEMA,'love-house-agent-source/v1')
        self.assertFalse(module.SourceClient(self.path).status()['full_activity_coverage_verified'])

    def test_redirect_does_not_forward_source_credential_to_another_service(self):
        observed=[]
        class Trap(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):observed.append(self.headers.get('Authorization'));self.send_response(200);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Trap)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        try:
            self.redirect='http://127.0.0.1:'+str(server.server_port)+'/capture'
            result=self.client.record_observation('原文保留本地','s','redirect',platform='browser')
            self.assertTrue(result['queued']);self.assertFalse(result['archive_committed'])
            self.assertEqual(observed,[])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
