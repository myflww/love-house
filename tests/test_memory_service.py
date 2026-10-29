from __future__ import annotations
import copy,io,json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from nkb.service.host import MemoryHost,make_controller
from nkb.core.atlas import atlas_brain
from nkb.storage.jsonfile import JsonFileStorage

class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  atlas_brain(self.root/'framework-example.brain.json').save()
  self.host=MemoryHost(self.root,with_demo=True)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host));self.host.controller_port=self.server.server_port
  self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01});self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.host.stop();self.tmp.cleanup()
 def req(self,path,data=None,lib=None,token=None):
  headers={'Content-Type':'application/json'}
  if lib:headers['X-NKB-Library']=lib
  if token:headers['Authorization']='Bearer '+token
  request=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=10) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def connection(self,lib='default',scope='connection',host='harness'):
  result=self.req('/api/connections',{'name':'测试连接','host':host,'library_id':lib,'session_scope':scope})[1]
  return result['connection']['id'],result['config']['connectionToken']
 def event(self,cid,token,sid='s',eid='1',user='用户原文',assistant='助手原文'):
  return self.req(f'/api/connections/{cid}/events',{'session_id':sid,'event_id':eid,'event_type':'turn/end',
   'record':{'schema':'deepseek-harness-event/v1','raw_event':{'type':'turn/end','attachments':[{'id':'attachment-ref'}]},
    'normalized':{'type':'turn','turn_id':eid,'status':'complete','user':user,'assistant':assistant}}},token=token)
 def test_first_launch_and_new_libraries_are_empty_and_isolated(self):
  status,libraries=self.req('/api/libraries');self.assertEqual(status,200);self.assertEqual(libraries['selected_id'],'default')
  self.assertEqual(self.req('/api/graph')[1]['nodes'],[])
  new=self.req('/api/libraries',{'name':'另一只鱼'})[1]['library']['id']
  self.assertEqual(self.req('/api/graph',lib=new)[1]['nodes'],[])
  cid,token=self.connection('default');self.req('/api/library/select',{'library_id':new})
  self.assertEqual(self.event(cid,token)[0],200)
  self.assertEqual(len(self.req('/api/graph',lib='default')[1]['nodes']),1)
  self.assertEqual(len(self.req('/api/graph',lib=new)[1]['nodes']),0)
 def test_completed_turn_is_automatic_idempotent_and_raw_event_preserved(self):
  cid,token=self.connection();first=self.event(cid,token)[1];second=self.event(cid,token)[1]
  self.assertTrue(first['accepted']);self.assertTrue(second['duplicate'])
  graph=self.req('/api/graph')[1];self.assertEqual(len(graph['nodes']),1)
  self.assertEqual(graph['nodes'][0]['text'],'用户原文')
  self.assertEqual(graph['nodes'][0]['meta']['assistant_reply'],'助手原文')
  row=self.host.connections.receipt(cid,'s','1');payload=json.loads(row['payload'])
  self.assertEqual(payload['record']['raw_event']['attachments'][0]['id'],'attachment-ref')
  self.assertEqual(self.req('/api/connections')[1]['connections'][0]['archive_status'],'automatic_connected')
 def test_specific_and_next_session_scope_enforced(self):
  cid,token=self.connection(scope='next_session')
  self.assertEqual(self.event(cid,token,sid='window-a')[0],200)
  self.assertEqual(self.host.connections.get(cid)['session_scope'],'window-a')
  self.assertEqual(self.event(cid,token,sid='window-b')[0],400)
  self.assertEqual(len(self.req('/api/graph')[1]['nodes']),1)
 def test_partial_stays_archive_and_does_not_fake_memory(self):
  cid,token=self.connection()
  result=self.req(f'/api/connections/{cid}/events',{'session_id':'s','event_id':'part','record':{'normalized':{'type':'turn','status':'partial','turn_id':'p','user':'半句','assistant':''}}},token=token)[1]
  self.assertTrue(result['accepted']);self.assertEqual(self.req('/api/graph')[1]['nodes'],[])
  self.assertEqual(self.host.connections.get(cid)['archive_status'],'waiting')
 def test_accepted_event_survives_graph_failure_and_retries(self):
  cid,token=self.connection();self.host.port_for('default')
  with patch.object(JsonFileStorage,'save',side_effect=OSError('disk write failure')):
   result=self.event(cid,token)[1]
  self.assertTrue(result['accepted']);self.assertEqual(result['status'],'retry')
  self.assertEqual(self.req('/api/graph')[1]['nodes'],[])
  self.host.process_pending();self.assertEqual(len(self.req('/api/graph')[1]['nodes']),1)
  self.assertEqual(self.host.connections.pending(),[])
 def test_wrong_token_pause_and_demo_binding_rejected(self):
  cid,token=self.connection()
  self.assertEqual(self.event(cid,'wrong')[0],400)
  self.req(f'/api/connections/{cid}/enabled',{'enabled':False})
  self.assertEqual(self.event(cid,token)[0],400)
  self.assertEqual(self.req('/api/connections',{'name':'bad','host':'harness','library_id':'demo','session_scope':'connection'})[0],400)
  self.assertEqual(self.req('/api/add',{'label':'must not contaminate demo'},lib='demo')[0],400)
 def test_persona_import_and_learning_from_connected_dialogue(self):
  cid,token=self.connection()
  self.assertEqual(self.event(cid,token,eid='persona',user='导入人格：\n你是一个温柔简短的伙伴。')[0],200)
  state=self.req('/api/persona')[1];self.assertIn('温柔简短',state['text'])
  self.assertEqual(self.event(cid,token,eid='feedback-1',user='我希望你说话幽默一点。')[0],200)
  self.assertEqual(self.event(cid,token,eid='feedback-2',user='以后请你说话幽默一点。')[0],200)
  self.assertTrue(self.req('/api/persona')[1]['learned'])
 def test_api_proxy_records_without_model_tool_calls_and_replays(self):
  cid,token=self.connection(host='api')
  response={'id':'mock','model':'deepseek-flash','choices':[{'message':{'role':'assistant','content':'模拟真实网络回复'},'finish_reason':'stop'}]}
  class MockResponse(io.BytesIO):
   pass
  opener=unittest.mock.Mock();opener.open.return_value=MockResponse(json.dumps(response).encode())
  from nkb.service.proxy import forward_chat
  import nkb.service.proxy as proxy
  original=proxy.forward_chat
  def wrapped(handler,host,c):return original(handler,host,c,opener=opener)
  with patch.object(proxy,'forward_chat',wrapped):
   url=f'http://127.0.0.1:{self.server.server_port}/connections/{cid}/v1/chat/completions'
   payload={'model':'deepseek-flash','messages':[{'role':'user','content':'代理接入测试'}]}
   req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer NOT_A_REAL_KEY','X-NKB-Request-ID':'request-one'})
   with urllib.request.urlopen(req,timeout=10) as r:self.assertEqual(json.load(r),response)
   with urllib.request.urlopen(req,timeout=10) as r:self.assertEqual(r.headers['X-NKB-Replayed'],'true')
  opener.open.assert_called_once();self.assertEqual(len(self.req('/api/graph')[1]['nodes']),1)
  row=self.host.connections.receipt(cid,'api-default-session','request-one');self.assertNotIn('NOT_A_REAL_KEY',row['payload'])

 def test_streaming_proxy_captures_unicode_only_after_done(self):
  cid,token=self.connection(host='api')
  chunks=[b'data: {"choices":[{"delta":{"content":"', '你好'.encode()[:2], '你好'.encode()[2:], b'"}}]}\n\n', b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n', b'data: [DONE]\n\n']
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read1(self,n):return chunks.pop(0) if chunks else b''
  opener=unittest.mock.Mock();opener.open.return_value=Response()
  import nkb.service.proxy as proxy
  original=proxy.forward_chat
  with patch.object(proxy,'forward_chat',lambda h,host,c:original(h,host,c,opener=opener)):
   req=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}/connections/{cid}/v1/chat/completions',
       data=json.dumps({'stream':True,'messages':[{'role':'user','content':'流式测试'}]}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer FAKE'})
   with urllib.request.urlopen(req,timeout=10) as response:wire=response.read()
  self.assertIn(b'[DONE]',wire)
  nodes=self.req('/api/graph')[1]['nodes'];self.assertEqual(len(nodes),1)
  self.assertEqual(nodes[0]['meta']['assistant_reply'],'你好')
 def test_paused_proxy_does_not_store_or_inject_but_still_chats(self):
  cid,token=self.connection(host='api');self.host.connections.toggle(cid,False)
  result={'choices':[{'message':{'content':'暂停时仍可聊天'},'finish_reason':'stop'}]}
  opener=unittest.mock.Mock();opener.open.return_value=io.BytesIO(json.dumps(result).encode())
  import nkb.service.proxy as proxy
  original=proxy.forward_chat
  with patch.object(proxy,'forward_chat',lambda h,host,c:original(h,host,c,opener=opener)):
   req=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}/connections/{cid}/v1/chat/completions',
       data=json.dumps({'messages':[{'role':'user','content':'不记忆'}]}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer FAKE'})
   with urllib.request.urlopen(req,timeout=10) as response:self.assertEqual(response.headers['X-NKB-Capture'],'paused')
  self.assertEqual(len(json.loads(opener.open.call_args.args[0].data)['messages']),1)
  self.assertEqual(self.req('/api/graph')[1]['nodes'],[])
  self.assertEqual(self.host.connections.activity()['events'],[])
 def test_heartbeat_is_not_completed_capture(self):
  cid,token=self.connection(scope='next_session')
  self.assertEqual(self.req(f'/api/connections/{cid}/heartbeat',{'host_version':'0.2.1-rc.3'},token=token)[0],200)
  row=self.host.connections.get(cid);self.assertTrue(row['host_online']);self.assertEqual(row['archive_status'],'waiting')
  self.assertEqual(row['session_scope'],'next_session');self.assertEqual(self.host.connections.activity()['events'],[])

 def test_reused_provider_call_id_in_later_turn_keeps_both_tools(self):
  cid,token=self.connection()
  for turn in ('turn-a','turn-b'):
   status,r=self.req(f'/api/connections/{cid}/events',{'session_id':'s','event_id':turn,'event_type':'tool/result',
    'record':{'normalized':{'type':'tool','turn_id':turn,'call_id':'call-1','tool_name':'browser','outcome':'observed','content':'结果 '+turn}}},token=token)
   self.assertEqual(status,200,r)
  self.assertEqual(len(self.req('/api/graph')[1]['nodes']),2)

if __name__=='__main__':unittest.main()
