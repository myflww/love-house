"""An existing generic MCP identity can use the real Harness host event adapter."""
from __future__ import annotations
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller

ROOT=Path(__file__).resolve().parents[1]

class AgentHarnessCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=self.root/'Harness.app';(self.app/'Contents').mkdir(parents=True)
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'0.2.1-rc.3'}))
        self.profile=self.root/'profile';self.profile.mkdir();(self.profile/'cordis.yml').write_text('[]\n')
        self.original='# user config stays\n[]\n';(self.profile/'cordis.patch.yml').write_text(self.original)
        self.host=MemoryHost(self.root/'data',key_store=KeyStore(allow_keychain=False),adapter_options={'profile_dir':str(self.profile)})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host));self.host.controller_port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        runtime=self.host.root/'.runtime';runtime.mkdir(exist_ok=True)
        (runtime/'fixture.json').write_text(json.dumps({'pid':os.getpid(),'controller_port':self.server.server_port,'service_version':'0.4.0'}))
        created=self.host.new_connection({'name':'已有MCP身份','host':'agent','library_id':'default'})
        self.cid=created['connection']['id'];self.token=self.host.connections.get(self.cid,secret=True)['token']
        self.client=build_opener(ProxyHandler({}))
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.host.stop();self.temp.cleanup()
    def req(self,path,data,token=None):
        headers={'Content-Type':'application/json','X-LoveHouse-Management':self.host.management_token}
        if token:headers['Authorization']='Bearer '+token
        request=Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=json.dumps(data).encode(),headers=headers)
        try:
            with self.client.open(request,timeout=8) as response:return response.status,json.load(response)
        except HTTPError as response:return response.code,json.load(response)
    def install(self):
        code,result=self.req('/api/connections/'+self.cid+'/configure',{'apply':True,'app_path':str(self.app)})
        self.assertEqual(code,200,result);self.assertTrue(result['applied']);return result
    def turn(self,sid='actual-harness-window',status='complete',reason='completed'):
        return {'session_id':sid,'event_id':sid+status,'event_type':'turn/end','record':{'schema':'deepseek-harness-event/v1',
                'raw_event':{'type':'turn/end','data':{'turn':1,'reason':{'kind':reason}}},'session_origin':'root',
                'normalized':{'type':'turn','status':status,'turn_id':sid+':1','user':'自动上报的实际用户发言','assistant':'实际完整回复'}}}
    def test_existing_mcp_identity_installs_harness_and_does_not_expose_its_private_token(self):
        before=self.host.connection_config(self.cid);self.assertIn('harness',before['auto_capture'])
        self.assertNotIn(self.token,json.dumps(before));self.assertFalse(before['auto_capture']['harness']['configured'])
        installed=self.install();private=json.loads(Path(installed['connection_file']).read_text())
        self.assertEqual((private['connection_id'],private['library_id'],private['connection_token'],private['connection_host']),
                         (self.cid,'default',self.token,'agent'))
        self.assertEqual(Path(installed['backup']).read_text(),self.original)
        after=self.host.connection_config(self.cid)
        self.assertTrue(after['auto_capture']['harness']['supported']);self.assertTrue(after['auto_capture']['harness']['configured'])
        self.assertNotIn(self.token,json.dumps(after));self.assertEqual(after['connection']['host'],'agent')
        self.assertEqual(after['connection']['archive_status'],'waiting');self.assertEqual(len(self.host.connections.list()),1)
    def test_only_installed_complete_harness_turn_can_claim_and_other_windows_never_write_receipts(self):
        endpoint='/api/connections/'+self.cid+'/events'
        self.assertEqual(self.req(endpoint,self.turn(),self.token)[1]['code'],'awaiting_window_binding')
        self.install()
        for e in [self.turn(status='partial'),self.turn(reason='aborted')]:
            self.assertEqual(self.req(endpoint,e,self.token)[1]['code'],'awaiting_window_binding')
        incomplete=self.turn();incomplete['record']['session_origin']='subagent'
        self.assertEqual(self.req(endpoint,incomplete,self.token)[1]['code'],'awaiting_window_binding')
        self.assertEqual(self.host.connections.activity()['events'],[])
        code,accepted=self.req(endpoint,self.turn(),self.token)
        self.assertEqual(code,200,accepted);self.assertTrue(accepted['accepted']);self.assertEqual(accepted['status'],'saved')
        self.assertEqual(self.host.connections.get(self.cid)['archive_status'],'automatic_connected')
        self.assertEqual(self.req(endpoint,self.turn('foreign-window'),self.token)[1]['code'],'scope_conflict')
        self.assertEqual(len(self.host.connections.activity()['events']),1)
    def test_pause_resume_disconnect_control_the_installed_plugin_as_well_as_mcp(self):
        installed=self.install();path=Path(installed['connection_file'])
        for enabled in (False,True):
            code,result=self.req('/api/connections/'+self.cid+'/enabled',{'enabled':enabled})
            self.assertEqual(code,200,result);self.assertTrue(result['host_change']['applied'])
            self.assertEqual(json.loads(path.read_text())['enabled'],enabled)
        code,result=self.req('/api/connections/'+self.cid+'/disconnect',{})
        self.assertEqual(code,200,result);self.assertFalse(json.loads(path.read_text())['enabled'])
        self.assertTrue(result['host_change']['source_capture_disabled'])
        self.assertNotIn(installed['plugin_config']['connection_file'],(self.profile/'cordis.patch.yml').read_text())
    @unittest.skipUnless(shutil.which('node'),'Node required for the shipped Harness plugin transport')
    def test_shipped_node_plugin_automatically_saves_real_roles_with_no_manual_memory_tool(self):
        installed=self.install()
        script="""
import {HostAdapter} from '__PLUGIN__';
const adapter=new HostAdapter({connection_file:process.argv[1],host_version:'0.2.1-rc.3',state_dir:process.argv[2],timeout_ms:2500});
const session={id:'node-host-window',header:{}};let seq=0;
const emit=(type,data)=>adapter.capture(session,{type,data,seq:seq++,time:Date.now()});
emit('turn/start',{turn:1});
emit('user/message',{id:'actual-user',role:'user',source:{kind:'user'},content:[{type:'text',text:'宿主自动提供的真实原话'}]});
emit('assistant/message',{turn:1,message:{id:'actual-assistant',role:'assistant',source:{kind:'model'},content:[{type:'text',text:'宿主自动提供的真实回复'}]}});
emit('turn/end',{turn:1,reason:{kind:'completed'}});
await adapter.flush();await adapter.dispose();
""".replace('__PLUGIN__',(ROOT/'extensions/deepseek-harness/dist/index.js').as_uri())
        result=subprocess.run([shutil.which('node'),'--input-type=module','-e',script,installed['connection_file'],str(self.root/'node-outbox')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        current=self.host.connections.get(self.cid);self.assertEqual(current['session_scope'],'next_session')
        self.assertEqual(current['bound_session_id'],'node-host-window')
        self.assertEqual(current['archive_status'],'automatic_connected');self.assertEqual(current['capture']['complete_dialogues_saved'],1)
        nodes=self.host.snapshot('default')['nodes'];self.assertEqual(len(nodes),1)
        self.assertIn('宿主自动提供的真实原话',json.dumps(nodes,ensure_ascii=False))
        self.assertIn('宿主自动提供的真实回复',json.dumps(nodes,ensure_ascii=False))
        self.assertFalse(list((self.root/'node-outbox').rglob('*.event.json')))

if __name__=='__main__':unittest.main()
