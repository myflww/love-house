"""Composition checks for the machine memory contract and lossless presentation."""
import json,unittest
import tests.test_memory_service as fixture
from nkb.service.credentials import KeyStore

class ProductMemoryContextTests(unittest.TestCase):
 setUp=fixture.ServiceTests.setUp
 tearDown=fixture.ServiceTests.tearDown
 req=fixture.ServiceTests.req
 connection=fixture.ServiceTests.connection
 event=fixture.ServiceTests.event
 def test_connected_agent_gets_scoped_machine_json_not_repeated_prompt_wrappers(self):
  self.host.keys=KeyStore(allow_keychain=False);self.host.providers.keys=self.host.keys
  lib=self.req('/api/libraries',{'name':'独立机器记忆'})[1]['library']['id']
  created=self.req('/api/connections',{'name':'记忆工具连接','host':'agent','library_id':lib})[1]
  cid=created['connection']['id'];token=self.host.connections.get(cid,secret=True)['token']
  self.assertEqual(self.event(cid,token,user='我不喜欢咖啡。',assistant='我会尊重你的偏好。')[0],200)
  result=self.req(f'/api/connections/{cid}/context',{'session_id':'s','query':'咖啡'},token=token)[1]
  packet=json.loads(result['packet']);self.assertEqual(packet['schema'],'love-house-memory-context/v1')
  self.assertEqual(packet['identity']['library_id'],lib);self.assertIn('不喜欢',json.dumps(packet,ensure_ascii=False))
  tool=self.req(f'/api/connections/{cid}/tool',{'name':'memory_context','arguments':{'query':'咖啡','session_id':'s'}},token=token)[1]
  self.assertEqual(tool['schema'],packet['schema']);self.assertNotIn('packet',tool);self.assertNotIn('messages',tool)
  legacy=self.req('/api/ai/context',{'query':'咖啡','origin':'harness'},lib=lib)[1]
  self.assertEqual(legacy['schema'],packet['schema']);self.assertNotIn('packet',legacy);self.assertNotIn('messages',legacy)
  self.assertNotIn('咖啡',json.dumps(self.req('/api/memory/context',{'query':'咖啡'},lib='default')[1]['memory_context']['records'],ensure_ascii=False))
 def test_confirmed_capture_aliases_fold_edges_and_counts_but_keep_original_records(self):
  self.host.keys=KeyStore(allow_keychain=False);self.host.providers.keys=self.host.keys
  manual=self.req('/api/ai/record',{'user':'同一轮用户原话','assistant':'同一轮助手原话','session_id':'window','request_id':'manual','origin':'harness'})[1]['id']
  cid,token=self.connection()
  self.assertEqual(self.event(cid,token,sid='window',user='同一轮用户原话',assistant='同一轮助手原话')[0],200)
  graph=self.req('/api/graph')[1];canonical=next(n['id'] for n in graph['nodes'] if not n.get('presentation_duplicate_of'))
  self.assertNotEqual(manual,canonical);self.assertEqual(len(graph['nodes']),2)
  def add_relation(brain):
   fact=brain.add('有来源事实','同一轮用户原话',kind='fact');brain.link(fact,manual,.35);brain.link(fact,canonical,.35);return fact
  self.host.transact('default',add_relation)
  graph=self.req('/api/graph')[1];self.assertEqual(len(graph['nodes']),3);self.assertEqual(len(graph['edges']),1)
  meta=self.host.manager.get_library('default');self.assertEqual(meta['node_count'],2);self.assertEqual(meta['raw_node_count'],3)
  self.assertEqual(meta['duplicate_count'],1)
  preview=self.req('/api/preview',{'days':0})[1];self.assertEqual(sum(bool(n.get('presentation_duplicate_of')) for n in preview['nodes']),1)
 def test_graph_revision_changes_when_organizer_adds_memory_without_a_capture_event(self):
  before=self.req('/api/activity')[1]
  self.host.transact('default',lambda b:b.add('后台整理结果','来自已存原文的整理事实',kind='fact'))
  after=self.req('/api/activity')[1]
  self.assertEqual(before['revision'],after['revision']);self.assertNotEqual(before['graph_revision'],after['graph_revision'])
  self.assertEqual(before['events'],after['events'])

if __name__=='__main__':unittest.main()
