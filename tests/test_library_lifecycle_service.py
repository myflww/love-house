"""Recoverable library deletion stops writers and preserves independent identities."""
import io,json,tempfile,threading,unittest,urllib.request,urllib.error,hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer
from nkb.service.host import MemoryHost,make_controller
from nkb.service.credentials import KeyStore
from nkb.core.atlas import atlas_brain

class LibraryLifecycleServiceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  atlas_brain(self.root/'framework-example.brain.json').save()
  self.host=MemoryHost(self.root,with_demo=True,key_store=KeyStore(allow_keychain=False))
  self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host));self.host.controller_port=self.server.server_port
  self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01});self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.host.stop();self.temp.cleanup()
 def req(self,path,data=None,lib=None,token=None):
  headers={'Content-Type':'application/json'}
  if lib:headers['X-NKB-Library']=lib
  if token:headers['Authorization']='Bearer '+token
  req=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
  try:
   with urllib.request.urlopen(req,timeout=8) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def connection(self,lib='default'):
  result=self.req('/api/connections',{'name':'库删除验收','host':'api','library_id':lib})[1]
  return result['connection']['id'],result['config']['connectionToken']
 def event(self,cid,token,eid='one'):
  return self.req(f'/api/connections/{cid}/events',{'session_id':'window','event_id':eid,
      'normalized':{'type':'turn','turn_id':eid,'status':'complete','user':'保留的用户原话','assistant':'保留的助手原话'}},token=token)
 def test_delete_disconnects_default_without_erasing_it_and_restore_stays_disconnected(self):
  cid,token=self.connection();self.assertEqual(self.event(cid,token)[0],200)
  before=self.host.snapshot('default');preview=self.req('/api/libraries/default/delete-preview',{})[1]
  self.assertTrue(preview['recoverable']);self.assertEqual(preview['connections_to_disconnect'],1)
  self.assertEqual(self.req('/api/libraries/default/delete',{})[0],400)
  status,deleted=self.req('/api/libraries/default/delete',{'confirm':True});self.assertEqual(status,200,deleted)
  self.assertNotEqual(self.host.manager.default_id,'default')
  self.assertEqual(self.req('/api/graph',lib='default')[0],404)
  self.assertNotEqual(self.event(cid,token,eid='late')[0],200)
  self.assertTrue(self.host.manager.legacy_path.exists() or self.root.joinpath('libraries/default.brain.json').exists())
  self.assertEqual(len(self.req('/api/libraries/trash')[1]['libraries']),1)
  status,restored=self.req('/api/libraries/default/restore',{'confirm':True});self.assertEqual(status,200,restored)
  after=self.req('/api/graph',lib='default')[1]
  self.assertEqual({n['text'] for n in after['nodes']},{n['text'] for n in before['nodes'].values()})
  self.assertTrue(self.host.connections.get(cid)['revoked']);self.assertFalse(restored['connections_rebound'])
  self.assertFalse(self.req('/api/organizer',lib='default')[1]['settings']['enabled'])
 def test_example_can_be_removed_without_reappearing_on_restart(self):
  example=self.root/'framework-example.brain.json';digest=hashlib.sha256(example.read_bytes()).digest()
  status,result=self.req('/api/libraries/demo/delete',{'confirm':True});self.assertEqual(status,200,result)
  self.assertTrue(self.host.manager.demo_suppressed);self.assertEqual(hashlib.sha256(example.read_bytes()).digest(),digest)
  other=MemoryHost(self.root,with_demo=True,key_store=KeyStore(allow_keychain=False))
  try:self.assertFalse(any(x['id']=='demo' for x in other.manager.list_libraries()))
  finally:other.stop()
  self.assertEqual(self.req('/api/libraries/demo/restore',{'confirm':True})[0],200)
  self.assertEqual(len(self.req('/api/graph',lib='demo')[1]['nodes']),225)
  self.assertEqual(hashlib.sha256(example.read_bytes()).digest(),digest)
 def test_received_pending_raw_waits_in_trash_and_indexes_only_as_history_after_restore(self):
  self.host.stopping.set();self.host.worker.join(timeout=3)
  cid,token=self.connection();c=self.host.connections.authenticate(cid,token)
  receipt=self.host.connections.receive(c,{'session_id':'window','event_id':'pending',
   'normalized':{'type':'turn','turn_id':'pending','status':'complete','user':'已接收的历史原文','assistant':'历史助手回复'}})
  self.assertEqual(self.req('/api/libraries/default/delete',{'confirm':True})[0],200)
  self.host.process_pending()
  self.assertEqual(self.host.connections.pending()[0]['attempts'],0)
  self.assertEqual(self.req('/api/libraries/default/restore',{'confirm':True})[0],200)
  self.host.process_pending();self.assertEqual(len(self.req('/api/graph',lib='default')[1]['nodes']),1)
  self.assertTrue(self.host.connections.get(cid)['revoked'])
  self.assertFalse(self.req('/api/organizer',lib='default')[1]['settings']['enabled'])
 def test_deleting_other_library_does_not_change_current_library(self):
  other=self.req('/api/libraries',{'name':'另一只Agent'})[1]['library']['id']
  self.req('/api/library/select',{'library_id':'default'})
  self.assertEqual(self.req('/api/libraries/'+other+'/delete',{'confirm':True})[0],200)
  self.assertEqual(self.host.manager.selected_id,'default')
  self.assertEqual(self.req('/api/graph')[0],200)
