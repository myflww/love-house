"""Product wiring: actual capture -> bounded organizer -> provenance -> recall, offline."""
import json
from pathlib import Path
import tempfile
import unittest

from nkb.service.host import MemoryHost
from nkb.service.credentials import KeyStore

class OrganizerServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.requests=[]
        def transport(request,*,timeout):
            payload=json.loads(json.loads(request.data)['messages'][1]['content']);self.requests.append(payload)
            source=payload['raw'][0];quote=source['roles']['user']
            output={'version':1,'operations':[{'action':'remember','layer':'preference','key':'user.drink',
                     'text':'用户偏爱无糖茶','aliases':['饮品偏好','喝什么'],
                     'certainty':'clear','domain':'real','evidence':[{'id':source['id'],'role':'user','quote':quote}]}]}
            return {'choices':[{'message':{'content':json.dumps(output,ensure_ascii=False)},'finish_reason':'stop'}]}
        self.host=MemoryHost(Path(self.temp.name),key_store=KeyStore(allow_keychain=False),organizer_transport=transport)
        self.config=self.host.new_connection({'name':'测试鱼','host':'api','library_id':'default'})
        self.cid=self.config['connection']['id'];self.token=self.config['config']['connectionToken']
    def tearDown(self):
        self.host.stop();self.temp.cleanup()
    def capture(self,eid='one',user='我喜欢喝无糖茶。'):
        return self.host.accept(self.cid,self.token,{'session_id':'real-client-session','event_id':eid,
           'normalized':{'type':'turn','turn_id':eid,'status':'complete','user':user,'assistant':'我记住这个偏好了。'}})
    def enable(self):
        return self.host.organizer_settings('default',{'enabled':True,'provider_mode':'separate',
                    'base_url':'https://offline.invalid/v1','model':'FAKE-organizer','api_key':'FAKE-SESSION-KEY','save_key':False})
    def test_capture_then_model_organization_and_semantic_recall(self):
        receipt=self.capture()
        self.assertEqual(receipt['status'],'saved');self.assertEqual(self.requests,[])
        preview=self.host.organizer.preview('default')
        self.assertFalse(preview['will_call_model']);self.assertEqual(preview['raw_count'],1)
        self.assertEqual(self.requests,[])
        self.enable();result=self.host.organizer.run_once('default')
        self.assertEqual(result['status'],'done',result);self.assertEqual(len(self.requests),1)
        snapshot=self.host.snapshot('default');derived=[n for n in snapshot['nodes'].values() if n['meta'].get('source')=='organizer']
        self.assertEqual(len(derived),1);self.assertEqual(derived[0]['text'],'我喜欢喝无糖茶。')
        self.assertEqual(derived[0]['meta']['organizer_summary'],'用户偏爱无糖茶')
        self.assertEqual(derived[0]['meta']['organizer_evidence'][0]['role'],'user')
        packet=self.host.context(self.cid,self.token,{'session_id':'another-window','query':'饮品偏好'})
        self.assertIn(derived[0]['id'],packet['memory_ids'])
        self.assertEqual(self.host.organizer_view('default')['status']['completed'],1)
        self.assertNotIn('FAKE-SESSION-KEY',json.dumps(snapshot))
        self.assertNotIn('FAKE-SESSION-KEY',json.dumps(self.host.organizer_view('default')))
        other=self.host.manager.create_library('另一只鱼')['id']
        self.assertEqual(self.host.snapshot(other)['nodes'],{})
    def test_pause_does_not_drop_archives_and_resume_can_process_backlog(self):
        receipt=self.capture();self.assertEqual(self.host.organizer.run_once('default')['status'],'paused')
        self.assertIsNotNone(self.host.read_archive('default',receipt['receipt_id']))
        self.assertEqual(self.requests,[])
        self.enable();self.assertEqual(self.host.organizer.run_once('default')['status'],'done')
    def test_paused_fact_does_not_reenter_context_via_its_raw_evidence(self):
        receipt=self.capture();self.enable();self.host.organizer.run_once('default')
        graph=self.host.snapshot('default');fact=next(n for n in graph['nodes'].values() if n['meta'].get('source')=='organizer')
        from nkb.service.controls import set_enabled
        self.host.transact('default',lambda b:set_enabled(b,fact['id'],False))
        packet=self.host.context(self.cid,self.token,{'session_id':'real-client-session','query':'无糖茶饮品偏好'})
        self.assertNotIn('我喜欢喝无糖茶。',packet['packet'])
        self.assertEqual(packet['history'],[])
        self.assertIsNotNone(self.host.read_archive('default',receipt['receipt_id']))
        self.host.transact('default',lambda b:set_enabled(b,fact['id'],True))
        self.assertIn(fact['id'],self.host.context(self.cid,self.token,{'session_id':'real-client-session','query':'饮品偏好'})['memory_ids'])
    def test_forgotten_source_cannot_be_organized_or_replayed(self):
        receipt=self.capture();self.enable();self.host.organizer.run_once('default')
        raw=next(n for n in self.host.snapshot('default')['nodes'].values() if n['meta'].get('source')=='conversation_turn')
        removed=self.host.forget_memory('default',raw['id'])
        self.assertTrue(removed['forgotten']);self.assertEqual(self.host.snapshot('default')['nodes'],{})
        self.assertIsNone(self.host.read_archive('default',receipt['receipt_id']))
        replay=self.capture();self.assertEqual(replay['status'],'forgotten')
        self.host.enqueue_archives('default');self.host.organizer.run_once('default')
        self.assertEqual(len(self.requests),1);self.assertEqual(self.host.snapshot('default')['nodes'],{})

if __name__=='__main__':unittest.main()
