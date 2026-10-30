"""Registered sources through the real Controller and headless CLI, disposable data only."""
from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller
from nkb.service.source_client import SourceClient, SourceClientError

ROOT=Path(__file__).resolve().parents[1]


class AgentSourceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='love-house-source-controller-test-')
        self.root=Path(self.temp.name)
        self.model=Mock(side_effect=AssertionError('This acceptance must not call a model'))
        self.host=MemoryHost(self.root,key_store=KeyStore(allow_keychain=False),organizer_transport=self.model)
        self.host.organizer.stop()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host))
        self.host.controller_port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.http=build_opener(ProxyHandler({}))
        self.other=self.host.manager.create_library('另一只独立的鱼')['id']

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.host.stop();self.temp.cleanup()

    def api(self,path,body=None,lib='default',token=None):
        headers={'X-NKB-Library':lib}
        if token:headers['Authorization']='Bearer '+token
        if body is not None:headers['Content-Type']='application/json'
        request=Request(self.base+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),headers=headers)
        try:
            with self.http.open(request,timeout=10) as r:return r.status,json.load(r)
        except HTTPError as error:return error.code,json.load(error)

    def source(self,lib='default',adapter='astrbot',platforms=None):
        status,value=self.api('/api/agent/sources',{'name':'合成活动来源','adapter':adapter,'runtime_agent_id':'stable-fish-one','platforms':platforms or ['qq','browser']},lib)
        self.assertEqual(status,200,value)
        cfg=json.loads(Path(value['private_path']).read_text())
        self.assertNotIn(cfg['token'],json.dumps(value))
        return value,cfg,SourceClient(value['private_path'],timeout=1)

    def test_two_platform_sources_share_fixed_identity_but_not_another_agent(self):
        _,ca,a=self.source(adapter='astrbot');_,cb,b=self.source(adapter='sdk')
        self.host.manager.select(self.other)
        first=a.record_dialogue('我们约好周六去看海。','好呀，记住这个约定。','qq-conversation','qq-1',platform='qq',occurred_at=1700000000)
        second=b.record_observation('看到了当地周六的潮汐预报。','browser-task','web-1',platform='browser',outcome='observed',occurred_at=1700000030)
        self.assertTrue(first['archive_committed']);self.assertTrue(second['archive_committed'])
        snapshot=self.host.snapshot('default')
        self.assertEqual(len(snapshot['nodes']),2)
        self.assertFalse(self.host.snapshot(self.other)['nodes'])
        self.assertNotEqual(ca['connection_id'],cb['connection_id'])
        self.assertTrue(all(n['meta']['evidence']['source_runtime_agent_id']=='stable-fish-one' for n in snapshot['nodes'].values()))
        self.assertEqual({n['meta']['evidence']['platform'] for n in snapshot['nodes'].values()},{'qq','browser'})
        self.assertEqual(len(self.host.connections.archives('default')),2)
        self.model.assert_not_called()

    def test_sdk_context_uses_only_the_bound_library_and_new_session(self):
        _,cfg,client=self.source()
        self.host.transact('default',lambda brain:brain.add('合成旧约定','约好周六去看海。'))
        self.host.transact(self.other,lambda brain:brain.add('另一只鱼的秘密','OTHER_AGENT_SECRET'))
        self.host.manager.select(self.other)
        context=client.read_context('周六看海的约定','completely-new-platform-session')
        self.assertEqual(context['library_id'],'default')
        self.assertIn('看海',json.dumps(context,ensure_ascii=False))
        self.assertNotIn('OTHER_AGENT_SECRET',json.dumps(context))
        self.assertEqual(self.host.sources.get(cfg['source_id'])['agent_id'],'default')

    def test_mismatched_source_agent_library_platform_are_rejected_before_raw_receipts(self):
        _,cfg,_=self.source(platforms=['qq'])
        event={'source_id':cfg['source_id'],'runtime_agent_id':cfg['runtime_agent_id'],'library_id':'default',
               'session_id':'qq-private','event_id':'rejected','platform':'qq','occurred_at':1700000000,
               'record':{'normalized':{'type':'turn','status':'complete','user':'不得保存的错身份原文','assistant':'回复'}}}
        path='/api/connections/'+cfg['connection_id']+'/events'
        for extra in ({'source_id':'source_'+'0'*32},{'runtime_agent_id':'another-agent'},
                      {'library_id':self.other},{'platform':'browser'}):
            with self.subTest(extra=extra):
                status,_=self.api(path,{**event,**extra},token=cfg['token'])
                self.assertEqual(status,400)
                self.assertFalse(self.host.connections.archives('default'))
        event['record']['normalized']['type']='unknown_action'
        self.assertEqual(self.api(path,event,token=cfg['token'])[0],400)
        self.assertFalse(self.host.connections.pending())

    def test_context_requires_registered_identity_not_just_a_bearer(self):
        _,cfg,_=self.source()
        path='/api/connections/'+cfg['connection_id']+'/context'
        for body in ({'query':'old memory','session_id':'s'},
                     {'source_id':cfg['source_id'],'runtime_agent_id':'other','query':'old memory','session_id':'s'}):
            self.assertEqual(self.api(path,body,token=cfg['token'])[0],400)
        self.assertFalse(self.host.connections.archives('default'))

    def test_pause_and_revoke_update_private_config_before_new_raw_content(self):
        bundle,cfg,client=self.source()
        sid=cfg['source_id'];endpoint='/api/agent/sources/'+sid
        self.assertEqual(self.api(endpoint+'/enabled',{'enabled':False})[0],200)
        with self.assertRaises(SourceClientError):client.record_dialogue('暂停后不采集','reply','s','p',platform='qq')
        self.assertEqual(client.status()['pending'],0);self.assertFalse(self.host.connections.archives('default'))
        self.assertEqual(self.api(endpoint+'/enabled',{'enabled':True})[0],200)
        self.assertTrue(client.record_dialogue('恢复后的合成原话','reply','s','p',platform='qq')['archive_committed'])
        self.assertEqual(self.api(endpoint+'/disconnect',{'confirm':True})[0],200)
        self.assertTrue(client.status()['revoked'])
        with self.assertRaises(SourceClientError):client.record_observation('断开后不采集','s','r',platform='browser')
        self.assertEqual(len(self.host.connections.archives('default')),1)

    def test_registered_source_token_cannot_reach_management_or_old_mcp_tools(self):
        _,cfg,_=self.source()
        for route,body in [('/api/agent/sources',None),('/api/retention',None),('/api/agent/sources',{'name':'forged'})]:
            with self.subTest(route=route):self.assertEqual(self.api(route,body,token=cfg['token'])[0],403)
        tool='/api/connections/'+cfg['connection_id']+'/tool'
        self.assertEqual(self.api(tool,{'name':'memory_status','arguments':{}},token=cfg['token'])[0],403)
        self.assertEqual(self.api('/api/connections/'+cfg['connection_id']+'/context',
            {'source_id':cfg['source_id'],'runtime_agent_id':cfg['runtime_agent_id'],'query':'x','session_id':'s'},
            lib=self.other,token=cfg['token'])[0],403)

    def test_source_management_checks_owner_library_and_config_returns_no_token_or_mcp(self):
        bundle,cfg,_=self.source();sid=cfg['source_id']
        for action,body in [('config',{}),('enabled',{'enabled':False}),('disconnect',{'confirm':True})]:
            self.assertEqual(self.api('/api/agent/sources/'+sid+'/'+action,body,lib=self.other)[0],400)
        code,listed=self.api('/api/agent/sources')
        self.assertEqual(code,200);self.assertEqual(len(listed['sources']),1)
        self.assertNotIn(cfg['token'],json.dumps(listed));self.assertNotIn('private_path',json.dumps(listed))
        code,descriptor=self.api('/api/agent/sources/'+sid+'/config',{})
        self.assertEqual(code,200,descriptor);self.assertTrue(Path(descriptor['private_path']).is_file())
        self.assertNotIn(cfg['token'],json.dumps(descriptor))
        code,legacy=self.api('/api/connections/'+cfg['connection_id']+'/config')
        self.assertEqual(code,200);self.assertEqual(legacy['mode'],'registered_source')
        self.assertEqual(legacy['host_config'],'');self.assertNotIn('mcpServers',json.dumps(legacy))

    def test_config_action_rejects_unread_body_overrides(self):
        _,cfg,_=self.source()
        self.assertEqual(self.api('/api/agent/sources/'+cfg['source_id']+'/config',{'library_id':self.other})[0],400)

    def test_deleting_library_revokes_registered_source_and_never_builds_legacy_mcp(self):
        library=self.host.manager.create_library('用于回收站测试的鱼')['id']
        bundle,cfg,client=self.source(library)
        with patch('nkb.service.agent_client.make_agent_config',side_effect=AssertionError('Do not make an old MCP file')):
            code,result=self.api('/api/libraries/'+library+'/delete',{'confirm':True},lib=library)
        self.assertEqual(code,200,result)
        self.assertTrue(client.status()['revoked']);self.assertFalse(client.status()['enabled'])
        with self.assertRaises(SourceClientError):client.record_observation('不能再记录','s','removed',platform='qq')
        self.assertFalse(self.host.connections.archives(library))

    def test_original_offline_time_and_external_participant_are_preserved(self):
        bundle,cfg,client=self.source()
        def offline(*args,**kwargs):raise OSError('synthetic offline')
        paused=SourceClient(bundle['private_path'],transport=offline)
        queued=paused.record_dialogue('我喜欢海边。','听起来很美。','qq','old',platform='qq',occurred_at=1600000000,
                                    details={'sender_id':'SYNTHETIC_PLATFORM_PEER','participant_role':'platform_sender'})
        self.assertTrue(queued['queued']);self.assertFalse(self.host.snapshot('default')['nodes'])
        self.assertEqual(client.drain()['pending'],0)
        node=next(iter(self.host.snapshot('default')['nodes'].values()))
        self.assertEqual(node['event_at'],1600000000)
        self.assertEqual(node['meta']['evidence']['participant_scope'],'external_participant')
        self.assertEqual(node['meta']['evidence']['participant_id'],'SYNTHETIC_PLATFORM_PEER')
        self.assertFalse(node['meta'].get('confirmed',False))
        material=client.read_context('喜欢海边','after-reconnect')
        records=material['memory_context']['records']
        self.assertTrue(records);self.assertTrue(any(r['epistemic_status']!='user_confirmed_statement' for r in records))


@unittest.skipIf(sys.platform=='win32','POSIX headless launcher is separate from Windows desktop')
class HeadlessSourceCLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='love-house-headless-source-test-');self.root=Path(self.temp.name)
        self.data=self.root/'private-data';self.log_path=self.root/'process.log';self.log=self.log_path.open('wb')
        self.process=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_memory_service.py'),'--data-dir',str(self.data),'--diagnose-startup'],
                                      cwd=self.root,stdout=self.log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        ready=self.data/'.runtime/app.json';deadline=time.monotonic()+15
        while not ready.exists() and self.process.poll() is None and time.monotonic()<deadline:time.sleep(.03)
        if not ready.exists():
            self.process.terminate();self.process.wait(timeout=8);self.log.close()
            self.fail('Disposable headless service did not become ready: '+self.log_path.read_text())
        self.ready=json.loads(ready.read_text());self.client=build_opener(ProxyHandler({}))
        self.base='http://127.0.0.1:'+str(self.ready['controller_port'])

    def tearDown(self):
        if self.process.poll() is None:self.process.terminate()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait();raise
        self.log.close();self.temp.cleanup()

    def get(self,path):
        with self.client.open(self.base+path,timeout=5) as r:return json.load(r)

    def test_real_headless_process_starts_blank_without_demo_gui_or_model(self):
        health=self.get('/api/health');self.assertTrue(health['ok']);self.assertEqual(health['mode'],'storage')
        libraries=self.get('/api/libraries')['libraries']
        self.assertEqual(len(libraries),1);self.assertFalse(libraries[0]['is_demo'])
        self.assertEqual(self.get('/api/graph')['nodes'],[])
        self.assertEqual(self.get('/api/agent/sources')['sources'],[])
        self.assertFalse((self.data/'framework-example.brain.json').exists())
        self.assertFalse(self.get('/api/organizer')['settings']['enabled'])
        self.process.terminate();self.assertEqual(self.process.wait(timeout=10),0)
        self.assertFalse((self.data/'.runtime/app.json').exists())

    def test_real_configuration_cli_defaults_to_host_platforms_and_never_prints_token(self):
        command=[sys.executable,str(ROOT/'scripts/configure_agent_source.py'),'--data-dir',str(self.data),
                 '--name','合成AstrBot来源','--adapter','astrbot','--runtime-agent-id','synthetic-fish']
        result=subprocess.run(command,cwd=self.root,text=True,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        bundle=json.loads(result.stdout);cfg=json.loads(Path(bundle['private_path']).read_text())
        self.assertEqual(cfg['platforms'],['*'])
        self.assertNotIn(cfg['token'],result.stdout+result.stderr)
        self.assertFalse(bundle['source']['full_activity_coverage_verified'])
        if os.name!='nt':self.assertEqual(stat.S_IMODE(Path(bundle['private_path']).stat().st_mode),0o600)
        self.assertEqual(len(self.get('/api/agent/sources')['sources']),1)
        recorded=SourceClient(bundle['private_path'],timeout=2).record_observation('在服务器观察到的合成结果','s','one',platform='qq')
        self.assertTrue(recorded['archive_committed'])
        self.assertEqual(len(self.get('/api/graph')['nodes']),1)

    def test_configuration_cli_cannot_register_into_another_live_service_via_stale_ready_file(self):
        stale=self.root/'stale-data';(stale/'.runtime').mkdir(parents=True)
        (stale/'.runtime/app.json').write_text(json.dumps({**self.ready,'pid':2147483647}))
        before=self.get('/api/agent/sources')['sources']
        command=[sys.executable,str(ROOT/'scripts/configure_agent_source.py'),'--data-dir',str(stale),
                 '--name','不能误登记到A服务','--adapter','sdk','--runtime-agent-id','fish-b']
        result=subprocess.run(command,cwd=self.root,text=True,capture_output=True,timeout=15)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.get('/api/agent/sources')['sources'],before)


if __name__=='__main__':unittest.main()
