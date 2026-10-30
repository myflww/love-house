from contextlib import closing
"""Automatic tool observation is not proof of a completed dialogue capture."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from nkb.service.connections import ConnectionStore
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost,make_controller


class CaptureStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.model_calls=[]
        def transport(*args,**kwargs):self.model_calls.append(True);raise AssertionError('No model is required for raw recall')
        self.host=MemoryHost(self.root,key_store=KeyStore(allow_keychain=False),organizer_transport=transport,
                             adapter_options={'profile_dir':str(self.root/'FAKE-harness-profile')})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host));self.host.controller_port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        c=self.host.new_connection({'name':'Fake Harness自动采集','host':'harness','library_id':'default'})['connection']
        self.cid=c['id'];self.token=self.host.connections.get(self.cid,secret=True)['token']
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.host.stop();self.temp.cleanup()
    def send(self,kind,normalized=None,*,eid=None,schema='deepseek-harness-event/v1'):
        event={'session_id':'actual-window','event_id':eid or kind,'event_type':kind,
               'record':{'schema':schema,'raw_event':{'type':kind,'data':{'shape':'fake fixture only'}}}}
        if normalized is not None:event['record']['normalized']=normalized
        return self.host.accept(self.cid,self.token,event)
    def status(self):return self.host.connections.get(self.cid)
    def test_raw_events_and_tool_observation_do_not_claim_complete_chat_then_turn_is_recallable_without_ai(self):
        self.send('user/message');self.send('assistant/message')
        self.assertEqual(self.status()['archive_status'],'waiting')
        self.send('tool/result',{'type':'tool','turn_id':'turn-1','call_id':'call-1','text':'真实工具观察：操作失败','outcome':'failed'})
        before=self.status();self.assertEqual(before['archive_status'],'observations_only')
        self.assertEqual(before['capture']['raw_events_only'],2)
        self.assertEqual(before['capture']['automatic_tool_observations_saved'],1)
        self.assertEqual(before['capture']['automatic_dialogues_saved'],0)
        self.assertIsNone(before['capture']['last_dialogue_at'])
        self.send('turn/end',{'type':'turn','turn_id':'turn-1','status':'complete','reason':'completed',
                             'user':'我喜欢温水，但不喜欢咖啡。','assistant':'我会尊重这个有来源的偏好。'})
        after=self.status();self.assertEqual(after['archive_status'],'automatic_connected')
        self.assertEqual(after['capture']['automatic_dialogues_saved'],1)
        self.assertEqual(after['capture']['complete_dialogues_saved'],1)
        self.assertIsNotNone(after['capture']['last_dialogue_at'])
        context=self.host.context(self.cid,self.token,{'session_id':'brand-new-window','query':'温水 咖啡'})
        raw=[r for r in context['memory_context']['records'] if r['layer']=='dialogue']
        self.assertEqual(len(raw),1);self.assertEqual(raw[0]['value'],'我喜欢温水，但不喜欢咖啡。')
        self.assertFalse(self.host.organizer_view('default')['settings']['enabled'])
        self.assertEqual(self.model_calls,[])
    def test_partial_turn_stays_raw_even_after_successful_tool_observation(self):
        self.send('tool/result',{'type':'tool','turn_id':'one','call_id':'c','text':'观察完成','outcome':'observed'})
        self.send('turn/end',{'type':'turn','turn_id':'one','status':'partial','user':'未完成用户原话','assistant':'未完成回复'})
        state=self.status();self.assertEqual(state['archive_status'],'observations_only')
        self.assertEqual(state['capture']['complete_dialogues_saved'],0)
        self.assertEqual(state['capture']['raw_events_only'],1)
    def test_manually_recorded_turn_is_not_proof_of_automatic_dialogue(self):
        self.send('agent/tool-memory_record_turn',{'type':'turn','turn_id':'manual-one','status':'complete',
                  'user':'人工补录的原话','assistant':'人工补录的回复'},schema='love-house-agent-tool/v1')
        state=self.status();self.assertEqual(state['archive_status'],'tools_only')
        self.assertEqual(state['capture']['complete_dialogues_saved'],1)
        self.assertEqual(state['capture']['automatic_dialogues_saved'],0)
    def test_forgotten_completed_turn_no_longer_appears_as_saved_dialogue(self):
        self.send('turn/end',{'type':'turn','turn_id':'forget-one','status':'complete','user':'用户之后要忘记的完整原话','assistant':'实际回复'})
        nid=next(iter(self.host.snapshot('default')['nodes']))
        self.assertEqual(self.status()['capture']['complete_dialogues_saved'],1)
        self.host.forget_memory('default',nid)
        state=self.status();self.assertEqual(state['capture']['complete_dialogues_saved'],0)
        self.assertEqual(state['archive_status'],'waiting')
    def test_raw_dialogue_is_excluded_while_current_tool_checks_are_still_running(self):
        self.send('user/message');self.send('assistant/message')
        context=self.host.context(self.cid,self.token,{'session_id':'actual-window','query':'尚在执行的这一轮'})
        self.assertEqual(context['memory_context']['records'],[])
        self.assertEqual(self.status()['capture']['complete_dialogues_saved'],0)
        self.assertEqual(self.model_calls,[])


class CaptureStatusMigrationTests(unittest.TestCase):
    def test_previous_tool_only_automatic_flag_is_corrected_without_rewriting_raw_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.sqlite3';payload=json.dumps({'record':{'schema':'deepseek-harness-event/v1',
                 'normalized':{'type':'tool','turn_id':'old-one','text':'旧原文\n保持逐字','outcome':'observed'}}},ensure_ascii=False,indent=2)
            digest=hashlib.sha256(payload.encode()).hexdigest()
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE connections(id TEXT PRIMARY KEY,name TEXT,host TEXT,library_id TEXT,session_scope TEXT,token TEXT,enabled INTEGER,revoked INTEGER,created REAL,last_received REAL,archive_status TEXT,error TEXT)')
                db.execute('INSERT INTO connections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('old','旧连接','harness','default','connection','FAKE-token',1,0,1,2,'automatic_connected',None))
                db.execute('CREATE TABLE receipts(id TEXT PRIMARY KEY,connection_id TEXT,library_id TEXT,session_id TEXT,kind TEXT,status TEXT,payload TEXT,payload_hash TEXT,received REAL,attempts INTEGER DEFAULT 0,error TEXT,applied REAL,node_ids TEXT)')
                db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',('receipt','old','default','window','tool/result','saved',payload,digest,2,1,None,3,'["fake-node"]'))
            store=ConnectionStore(directory);state=store.get('old')
            self.assertEqual(state['archive_status'],'observations_only')
            self.assertEqual(state['capture']['automatic_dialogues_saved'],0)
            self.assertEqual(state['capture']['automatic_tool_observations_saved'],1)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT payload,payload_hash FROM receipts').fetchone(),(payload,digest))
            store=ConnectionStore(directory)
            self.assertEqual(store.get('old')['capture'],state['capture'])


if __name__=='__main__':unittest.main()
