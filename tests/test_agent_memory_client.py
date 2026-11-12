"""Vendor-free connector contract, real loopback HTTP and disposable offline spools."""
from __future__ import annotations
import hashlib,json,os,stat,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from nkb.service.agent_client import (AgentClient,AgentConnectionError,make_agent_config,validate_config,
                                      event_from_hook,event_from_tool,HOOK_SCHEMA,TOOL_SCHEMA)

ROOT=Path(__file__).resolve().parents[1]
TOKEN='FAKE-LOCAL-MEMORY-TOKEN-NOT-A-VENDOR-KEY'
CID='conn_test_agent'

class LocalMemoryService:
 def __init__(self,*,receipts=None,redirect=None):
  self.receipts=receipts if receipts is not None else {};self.posts=[];self.gui_library='another-library';self.revoked=False;self.redirect=redirect
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def respond(self,body,status=200):
    raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   def do_GET(self):
    if self.path=='/api/health':return self.respond({'ok':True,'name':'爱之屋记忆服务','version':'0.4.2','protocol_version':'0.4.0'})
    return self.respond({},404)
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
    if self.path.split('/')[3]!=CID or self.headers.get('Authorization')!='Bearer '+TOKEN or owner.revoked:return self.respond({'error':'credential rejected '+TOKEN},403)
    owner.posts.append((self.path,body))
    if owner.redirect:
     self.send_response(307);self.send_header('Location',owner.redirect);self.send_header('Content-Length','0');self.end_headers();return
    if self.path.endswith('/heartbeat'):return self.respond({'ok':True,'host_online':True,'archive_status':'tools_only'})
    if self.path.endswith('/tool'):
     name=body['name']
     if name=='memory_status':return self.respond({'library_id':'agent-library','capture_mode':'tools_only','archive_status':'tools_only','pending':0})
     if name=='memory_context':return self.respond({'schema':'love-house-memory-context/v1','records':[{'id':'known','value':'原话'}],'library_id':'agent-library'})
     return self.respond({'saved':True,'library_id':'agent-library'})
    if self.path.endswith('/events'):
     identity=(body['session_id'],body['event_id']);encoded=json.dumps(body,sort_keys=True,ensure_ascii=False)
     old=owner.receipts.get(identity)
     if old and old['body']!=encoded:return self.respond({'error':'event conflict'},409)
     status='archived' if body['normalized']['status']=='partial' else 'saved'
     owner.receipts[identity]={'body':encoded,'library_id':'agent-library','event':body,'status':status}
     return self.respond({'accepted':True,'duplicate':bool(old),'receipt_id':hashlib.sha256(str(identity).encode()).hexdigest(),'status':status,'library_id':'agent-library'})
    return self.respond({},404)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
  self.port=self.server.server_port
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join()

class AgentMemoryClientTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.services=[];self.clients=[]
  self.connection={'id':CID,'library_id':'agent-library','token':TOKEN,'enabled':True,'revoked':False}
  self.bundle=make_agent_config(self.root,self.connection,persist=True);self.path=Path(self.bundle['private_path'])
  self.client=self.new_client()
 def tearDown(self):
  for client in self.clients:client.stop()
  for service in self.services:service.close()
  self.temp.cleanup()
 def new_client(self,**kwargs):
  client=AgentClient(self.path,timeout=.5,poll_seconds=.05,**kwargs);self.clients.append(client);return client
 def start_service(self,**kwargs):
  service=LocalMemoryService(**kwargs);self.services.append(service)
  runtime=self.root/'.runtime';runtime.mkdir(exist_ok=True)
  (runtime/(str(time.time_ns())+'.json')).write_text(json.dumps({'pid':os.getpid(),'controller_port':service.port,'service_version':'0.4.0'}))
  return service
 def wait_for(self,predicate):
  deadline=time.monotonic()+4
  while not predicate() and time.monotonic()<deadline:time.sleep(.02)
  self.assertTrue(predicate())
 def turn(self,rid='one'):
  return {'session_id':'real-window','turn_id':rid,'user':'真实用户原话','assistant':'真实助手原话','status':'complete'}
 def test_config_is_dynamic_private_and_contains_no_vendor_or_token_in_public_code(self):
  other=self.root/'not-persisted';bundle=make_agent_config(other,self.connection)
  self.assertFalse(Path(bundle['private_path']).exists());self.assertFalse(other.exists())
  public=json.dumps(self.bundle,ensure_ascii=False)
  self.assertNotIn(TOKEN,public);self.assertNotIn('OPENAI_API_KEY',public);self.assertNotIn('DEEPSEEK_API_KEY',public)
  if os.name != "nt":self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
  command=next(iter(self.bundle['mcp_config']['mcpServers'].values()))
  self.assertEqual(command['args'][-2:],['--connection-config',str(self.path)])
  self.assertNotIn('PYTHONHOME',command['env'])
  self.assertTrue(self.bundle['requires_host_hook_for_automatic_capture'])
 def test_offline_record_is_durable_then_acknowledged_and_replayed_once(self):
  result=self.client.submit_hook(self.turn());self.assertFalse(result['saved']);self.assertTrue(result['local_queue_committed']);self.assertEqual(result['status'],'queued_offline')
  pending=list((self.root/'agent-outbox'/CID).glob('*.json'));self.assertEqual(len(pending),1)
  if os.name != "nt":self.assertEqual(stat.S_IMODE(pending[0].stat().st_mode),0o600)
  self.assertIn('真实用户原话',pending[0].read_text());self.assertNotIn(TOKEN,pending[0].read_text())
  service=self.start_service();self.assertEqual(self.client.drain()['pending'],0);self.assertEqual(len(service.receipts),1)
  replay=self.client.submit_hook(self.turn());self.assertTrue(replay['saved']);self.assertTrue(replay['duplicate']);self.assertEqual(len(service.receipts),1)
 def test_peer_draining_before_submitter_receipt_is_a_queue_state_not_data_loss(self):
  service=self.start_service();peer=self.new_client();enqueue=self.client._enqueue
  def delivered_by_peer(event):
   key=enqueue(event);self.assertEqual(peer.drain()['pending'],0);return key
  with patch.object(self.client,'_enqueue',side_effect=delivered_by_peer):
   result=self.client.submit_hook(self.turn('peer-won-delivery'))
  self.assertTrue(result['local_queue_committed']);self.assertFalse(result['saved'])
  self.assertEqual(result['pending'],0);self.assertEqual(len(service.receipts),1)
  received=next(iter(service.receipts.values()))['event']['normalized']
  self.assertEqual((received['user'],received['assistant']),('真实用户原话','真实助手原话'))

 def test_background_reconnect_finds_changed_port_without_changing_agent_or_gui_binding(self):
  receipts={};self.client.start();self.client.submit_hook(self.turn('before'))
  first=self.start_service(receipts=receipts);self.wait_for(lambda:self.client.pending_count()==0)
  first.close();self.services.remove(first)
  self.client.submit_hook(self.turn('after'))
  second=self.start_service(receipts=receipts);self.assertNotEqual(first.port,second.port);second.gui_library='third-library'
  self.wait_for(lambda:self.client.pending_count()==0)
  self.assertEqual(len(receipts),2);self.assertTrue(all(r['library_id']=='agent-library' for r in receipts.values()))
  self.assertEqual(self.client.status()['library_id'],'agent-library')
 def test_transient_incomplete_health_response_does_not_kill_reconnect_worker(self):
  from http.client import IncompleteRead
  from urllib.request import build_opener,ProxyHandler
  self.client.submit_hook(self.turn());self.start_service();delegate=build_opener(ProxyHandler({}))
  class BrokenResponse:
   def __init__(self,url):self.url=url
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def geturl(self):return self.url
   def read(self,*args):raise IncompleteRead(b'',5)
  class OnceBrokenOpener:
   first=True
   def open(self,request,timeout):
    if self.first and request.full_url.endswith('/api/health'):
     self.first=False;return BrokenResponse(request.full_url)
    return delegate.open(request,timeout=timeout)
  recovering=self.new_client(opener=OnceBrokenOpener());recovering.start()
  self.wait_for(lambda:recovering.pending_count()==0)

 def test_paused_or_revoked_config_stops_new_collection_but_keeps_pending(self):
  self.client.submit_hook(self.turn());self.assertEqual(self.client.pending_count(),1)
  make_agent_config(self.root,{**self.connection,'enabled':False},persist=True)
  with self.assertRaises(AgentConnectionError):self.client.submit_hook(self.turn('paused'))
  service=self.start_service();self.assertEqual(self.client.drain()['status'],'paused');self.assertEqual(service.receipts,{})
  make_agent_config(self.root,self.connection,persist=True);self.client.drain();self.assertEqual(len(service.receipts),1)
  make_agent_config(self.root,{**self.connection,'enabled':False,'revoked':True,'token':''},persist=True)
  self.assertEqual(self.client.status()['status'],'paused')
  with self.assertRaises(AgentConnectionError):self.client.submit_hook(self.turn('revoked'))
  self.assertEqual(self.client.pending_count(),0)
 def test_server_revocation_does_not_redirect_record_into_a_new_library(self):
  service=self.start_service();service.revoked=True
  result=self.client.submit_hook(self.turn());self.assertFalse(result['saved']);self.assertTrue(result['queued']);self.assertEqual(result['reason'],'connection_rejected')
  self.assertEqual(service.receipts,{});self.assertEqual(self.client.pending_count(),1)
  self.assertNotIn(TOKEN,json.dumps(self.client.status()))
 def test_hook_and_manual_tool_are_distinct_and_unknown_credentials_are_not_archived(self):
  service=self.start_service()
  hook=event_from_hook({**self.turn(),'api_key':'DO-NOT-KEEP','authorization':'DO-NOT-KEEP'})
  tool=event_from_tool('memory_record_turn',{'session_id':'real-window','request_id':'manual','user':'真实用户原话','assistant':'真实助手原话','source_session_id':'real-window','source_event_id':'one'})
  self.assertEqual(hook['record']['schema'],HOOK_SCHEMA);self.assertEqual(tool['record']['schema'],TOOL_SCHEMA)
  self.assertEqual(hook['normalized']['origin'],'agent_host_hook');self.assertEqual(tool['normalized']['origin'],'manual_record')
  self.assertNotIn('DO-NOT-KEEP',json.dumps(hook));self.assertNotIn('normalized',hook['record'])
  self.assertTrue(self.client.submit_event(hook)['saved']);self.assertTrue(self.client.submit_event(tool)['saved'])
  self.assertEqual(self.client.status()['capture_mode'],'tools_only')
  partial=self.client.submit_hook({**self.turn('partial'),'assistant':'','status':'partial'})
  self.assertTrue(partial['archive_committed']);self.assertFalse(partial['saved'])
 def test_source_url_credentials_rejected_query_removed_and_conflicting_id_not_overwritten(self):
  event=event_from_tool('memory_event',{'session_id':'s','request_id':'e','text':'页面结果','source_url':'https://example.test/page?token=SECRET#x','outcome':'failed'})
  self.assertEqual(event['normalized']['source_url'],'https://example.test/page');self.assertNotIn('SECRET',json.dumps(event))
  with self.assertRaises(AgentConnectionError):event_from_tool('memory_event',{'session_id':'s','request_id':'e','text':'x','source_url':'https://user:password@example.test/','outcome':'success'})
  self.client.submit_hook(self.turn())
  with self.assertRaises(AgentConnectionError) as caught:self.client.submit_hook({**self.turn(),'assistant':'不同的回复'})
  self.assertEqual(caught.exception.code,'event_conflict');self.assertEqual(self.client.pending_count(),1)
 def test_redirect_and_environment_proxy_cannot_transmit_memory_elsewhere(self):
  # The redirect/proxy target is not a discoverable memory controller.
  # Registering both as the same credential/PID makes coarse Windows mtimes
  # choose the target directly instead of exercising the redirect boundary.
  target=LocalMemoryService();self.services.append(target)
  source=self.start_service(redirect=f'http://127.0.0.1:{target.port}/steal')
  with patch.dict(os.environ,{'HTTP_PROXY':f'http://127.0.0.1:{target.port}','ALL_PROXY':f'http://127.0.0.1:{target.port}'}):
   result=self.new_client().submit_hook(self.turn())
  self.assertFalse(result['saved']);self.assertEqual(target.posts,[]);self.assertEqual(self.client.pending_count(),1)
  self.assertEqual(source.posts[0][0],f'/api/connections/{CID}/events')
 def test_nonlocal_configuration_and_bad_ready_pid_or_port_are_not_accepted(self):
  config=json.loads(self.path.read_text());config['server_url']='https://remote.example'
  with self.assertRaises(AgentConnectionError):validate_config(config)
  runtime=self.root/'.runtime';runtime.mkdir();(runtime/'bad.json').write_text(json.dumps({'pid':-1,'controller_port':443,'url':'https://remote.example'}))
  with self.assertRaises(AgentConnectionError):self.client.discover()
  self.assertFalse(self.client.status()['connected'])
 def test_cli_hook_queues_real_roles_without_printing_content_or_credentials(self):
  command=[sys.executable,str(ROOT/'desktop/agent_memory_hook.py'),'--connection-config',str(self.path)]
  result=subprocess.run(command,input=json.dumps({**self.turn(),'api_key':'DO-NOT-KEEP'}),capture_output=True,text=True,cwd=self.root,timeout=5)
  self.assertEqual(result.returncode,0,result.stderr);response=json.loads(result.stdout)
  self.assertEqual(response['status'],'queued_offline');self.assertFalse(response['saved'])
  self.assertNotIn('真实用户原话',result.stdout);self.assertNotIn(TOKEN,result.stdout+result.stderr)
  item=json.loads(next((self.root/'agent-outbox'/CID).glob('*.json')).read_text())
  self.assertEqual(item['event']['normalized']['assistant'],'真实助手原话');self.assertNotIn('DO-NOT-KEEP',json.dumps(item))
 def test_cli_mcp_initializes_and_lists_tools_without_service_or_vendor_key(self):
  messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'memory_status','arguments':{}}}]
  result=subprocess.run([sys.executable,str(ROOT/'desktop/agent_memory_bridge.py'),'--connection-config',str(self.path)],
        input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,text=True,cwd=self.root,timeout=6)
  self.assertEqual(result.returncode,0,result.stderr);responses=[json.loads(s) for s in result.stdout.splitlines()]
  self.assertEqual(responses[0]['result']['serverInfo']['name'],'love-house-agent-memory')
  self.assertIn('automatic full-turn capture requires a real host turn-end hook',responses[0]['result']['instructions'])
  self.assertEqual({t['name'] for t in responses[1]['result']['tools']},
    {'memory_context','memory_remember','memory_record_turn','memory_event','memory_status',
     'memory_persona','memory_persona_import','memory_bootstrap','memory_list','memory_read'})
  self.assertFalse(responses[2]['result']['structuredContent']['connected']);self.assertNotIn(TOKEN,result.stdout+result.stderr)


 def test_acknowledged_conflicting_retry_does_not_block_a_later_independent_turn(self):
  service=self.start_service();self.assertTrue(self.client.submit_hook(self.turn())['saved'])
  conflict=self.client.submit_hook({**self.turn(),'assistant':'a changed body with same event id'})
  self.assertEqual(conflict['reason'],'event_conflict');self.assertEqual(self.client.pending_count(),1)
  self.assertTrue(self.client.submit_hook(self.turn('next-independent'))['saved'])
  self.assertEqual(len(service.receipts),2);self.assertEqual(self.client.pending_count(),1)

 def test_local_write_failure_is_explicit_not_a_fake_queued_success(self):
  with patch('nkb.service.agent_client._atomic_json',side_effect=OSError('disk full '+TOKEN)):
   with self.assertRaises(AgentConnectionError) as error:self.client.submit_hook(self.turn())
  self.assertEqual(error.exception.code,'outbox_io_error');self.assertNotIn(TOKEN,str(error.exception))
  self.assertEqual(self.client.pending_count(),0)

 def test_two_independent_hook_clients_do_not_overwrite_conflicting_pending_ids(self):
  second=self.new_client();barrier=threading.Barrier(2);results=[]
  def send(client,assistant):
   barrier.wait()
   try:results.append(client.submit_hook({**self.turn(),'assistant':assistant}))
   except AgentConnectionError as exc:results.append(exc.code)
  threads=[threading.Thread(target=send,args=(client,text)) for client,text in ((self.client,'first exact reply'),(second,'different exact reply'))]
  for t in threads:t.start()
  for t in threads:t.join(timeout=3)
  self.assertEqual(len(results),2);self.assertEqual(results.count('event_conflict'),1)
  self.assertEqual(self.client.pending_count(),1)

class RealControllerAgentConnectorTests(unittest.TestCase):
 """Compose the reusable client with the actual product Controller, still fully offline."""
 def setUp(self):
  from nkb.service.host import MemoryHost,make_controller
  from nkb.service.credentials import KeyStore
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.Host=MemoryHost;self.Controller=make_controller;self.Keys=KeyStore
  self.host=None;self.server=None;self.thread=None;self.boot()
  other=self.host.manager.create_library('另一个Agent')['id'];self.bound=other
  bundle=self.host.new_connection({'name':'纯记忆连接','host':'agent','library_id':other,'session_scope':'connection'})
  self.cid=bundle['connection']['id'];self.path=Path(bundle['private_path']);self.client=AgentClient(self.path,timeout=2,poll_seconds=.05)
 def boot(self):
  self.host=self.Host(self.root,key_store=self.Keys(allow_keychain=False))
  self.server=ThreadingHTTPServer(('127.0.0.1',0),self.Controller(self.host));self.host.controller_port=self.server.server_port
  self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
  directory=self.root/'.runtime';directory.mkdir(exist_ok=True)
  (directory/'app.json').write_text(json.dumps({'pid':os.getpid(),'controller_port':self.server.server_port,'service_version':'0.4.0'}))
 def shutdown(self):
  if self.server:self.server.shutdown();self.server.server_close();self.thread.join();self.server=None
  if self.host:self.host.stop();self.host=None
 def tearDown(self):
  self.client.stop();self.shutdown();self.temp.cleanup()
 def test_actual_manual_tool_stays_tools_only_hook_verifies_capture_and_both_sources_remain(self):
  self.host.manager.select('default')
  status=self.client.status();self.assertTrue(status['connected']);self.assertFalse(status['automatic_memory'])
  manual=self.client.tool('memory_record_turn',{'session_id':'known-window','request_id':'manual','user':'我喜欢温水。','assistant':'我会尊重这个偏好。'})
  self.assertTrue(manual['saved']);self.assertEqual(self.client.status()['capture_mode'],'tools_only')
  hook=self.client.submit_hook({'session_id':'known-window','turn_id':'host-turn','user':'我喜欢温水。','assistant':'我会尊重这个偏好。','status':'complete'})
  self.assertTrue(hook['saved']);status=self.client.status();self.assertTrue(status['automatic_memory'])
  snapshot=self.host.snapshot(self.bound)
  self.assertEqual(len(snapshot['nodes']),2)
  self.assertEqual(sum(bool(n['meta'].get('duplicate_of')) for n in snapshot['nodes'].values()),1)
  self.assertEqual(self.host.snapshot('default')['nodes'],{})
  context=self.client.tool('memory_context',{'query':'温水','session_id':'another-window'})
  self.assertEqual(context['schema'],'love-house-memory-context/v1');self.assertEqual(context['identity']['library_id'],self.bound)
  self.assertEqual(len(context['records']),1)
  self.assertNotIn(TOKEN,json.dumps(context))
 def test_intentionally_forgotten_event_ack_is_not_reported_as_an_archived_memory(self):
  event={'session_id':'w','turn_id':'forget-turn','user':'用户明确删除前的原文。','assistant':'当时的真实回复。','status':'complete'}
  self.assertTrue(self.client.submit_hook(event)['saved'])
  nid=next(iter(self.host.snapshot(self.bound)['nodes']))
  self.host.forget_memory(self.bound,nid)
  replay=self.client.submit_hook(event)
  self.assertEqual(replay['status'],'forgotten');self.assertTrue(replay['forgotten'])
  self.assertFalse(replay['saved']);self.assertFalse(replay['archive_committed']);self.assertFalse(replay['queued'])
  self.assertEqual(self.host.snapshot(self.bound)['nodes'],{})
  self.assertEqual(self.client.pending_count(),0)

 def test_opening_product_again_drains_offline_hook_without_a_running_mcp_process(self):
  old_port=self.server.server_port;self.shutdown()
  queued=self.client.submit_hook({'session_id':'w','turn_id':'offline-turn','user':'电脑服务暂停时上报的真实原文。','assistant':'先保存在本机待发送队列。','status':'complete'})
  self.assertEqual(queued['status'],'queued_offline');self.assertEqual(self.client.pending_count(),1)
  self.boot();self.assertNotEqual(old_port,self.server.server_port)
  deadline=time.monotonic()+7
  while self.client.pending_count() and time.monotonic()<deadline:time.sleep(.05)
  self.assertEqual(self.client.pending_count(),0)
  self.assertEqual(len(self.host.snapshot(self.bound)['nodes']),1)
  self.assertEqual(self.client.status()['library_id'],self.bound)
  self.assertEqual(self.host.snapshot('default')['nodes'],{})

if __name__=='__main__':unittest.main()
