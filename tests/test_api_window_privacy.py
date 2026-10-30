"""API forwarding cannot guess a private window ID or collect rejected windows."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from http.server import ThreadingHTTPServer

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller
from nkb.service import proxy


class APIWindowPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.host=MemoryHost(Path(self.temp.name),key_store=KeyStore(allow_keychain=False))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host))
        self.host.controller_port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()
        self.upstream=Mock()
        self.upstream.open.side_effect=lambda *_args,**_kwargs:io.BytesIO(json.dumps({
            'choices':[{'message':{'content':'FAKE 上游完整回复'},'finish_reason':'stop'}]}).encode())
        original=proxy.forward_chat
        self.proxy_patch=patch.object(proxy,'forward_chat',
            lambda handler,host,cid:original(handler,host,cid,opener=self.upstream))
        self.proxy_patch.start()

    def tearDown(self):
        self.proxy_patch.stop()
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.host.stop();self.temp.cleanup()

    def connection(self,scope):
        result=self.host.new_connection({'name':'隔离API窗口','host':'api','library_id':'default',
            'session_scope':scope,'provider':{'base_url':'https://example.invalid/v1','model':'fake-model',
            'api_key':'FAKE-NOT-A-REAL-MODEL-KEY','save_key':False}})
        cid=result['connection']['id']
        return cid,self.host.connections.get(cid,secret=True)['token']

    def chat(self,cid,token,session=None,*,text='窗口实际原话',header='X-NKB-Session',request_id=None):
        headers={'Content-Type':'application/json','Authorization':'Bearer '+token}
        if session is not None:headers[header]=session
        if request_id is not None:headers['X-NKB-Request-ID']=request_id
        body=json.dumps({'messages':[{'role':'user','content':text}]},ensure_ascii=False).encode()
        request=Request('http://127.0.0.1:'+str(self.server.server_port)+'/connections/'+cid+'/v1/chat/completions',
            data=body,headers=headers)
        try:
            with build_opener(ProxyHandler({})).open(request,timeout=10) as response:return response.status,json.load(response)
        except HTTPError as response:return response.code,json.load(response)

    def receipts(self,cid):
        with self.host.connections.db() as db:
            return [dict(r) for r in db.execute('SELECT session_id,payload FROM receipts WHERE connection_id=?',(cid,))]

    def test_single_window_missing_header_rejects_before_body_key_lookup_or_upstream(self):
        for scope in ('next_session','fixed-window'):
            with self.subTest(scope=scope):
                cid,token=self.connection(scope)
                with patch.object(self.host.providers,'credential',side_effect=AssertionError('must not read credentials')) as credential:
                    with patch.object(self.server.RequestHandlerClass,'_body',side_effect=AssertionError('must not consume body')) as body:
                        code,result=self.chat(cid,token,text='UNCONFIGURED-WINDOW-NOT-TO-CAPTURE')
                self.assertEqual(code,400,result)
                self.assertIn('X-NKB-Session',result['error'])
                body.assert_not_called();credential.assert_not_called();self.upstream.open.assert_not_called()
                self.assertEqual(self.receipts(cid),[])
                state=self.host.connections.get(cid)
                self.assertEqual(state['session_scope'],'next_session' if scope=='next_session' else 'fixed')
                self.assertEqual(state['bound_session_id'],None if scope=='next_session' else scope)
                self.assertEqual(self.host.snapshot('default')['nodes'],{})

    def test_fixed_window_wrong_header_never_calls_upstream_or_creates_raw(self):
        cid,token=self.connection('fixed-window')
        code,result=self.chat(cid,token,'another-window',text='FOREIGN-PRIVATE-UTTERANCE')
        self.assertEqual(code,400,result);self.upstream.open.assert_not_called()
        self.assertEqual(self.receipts(cid),[])
        self.assertEqual(self.host.snapshot('default')['nodes'],{})
        self.assertEqual(self.host.connections.get(cid)['bound_session_id'],'fixed-window')

    def test_next_window_binds_real_header_then_rejects_other_window_without_forwarding(self):
        cid,token=self.connection('next_session')
        code,result=self.chat(cid,token,'real-window-A',request_id='first-real-turn')
        self.assertEqual(code,200,result);self.assertEqual(self.upstream.open.call_count,1)
        self.assertEqual(self.host.connections.get(cid)['session_scope'],'next_session')
        self.assertEqual(self.host.connections.get(cid)['bound_session_id'],'real-window-A')
        before=self.host.snapshot('default')
        code,result=self.chat(cid,token,'window-B',text='WINDOW-B-MUST-NOT-ENTER-ARCHIVE')
        self.assertEqual(code,400,result);self.assertEqual(self.upstream.open.call_count,1)
        rows=self.receipts(cid);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['session_id'],'real-window-A')
        self.assertNotIn('WINDOW-B-MUST-NOT-ENTER-ARCHIVE',rows[0]['payload'])
        self.assertEqual(self.host.snapshot('default'),before)

    def test_legacy_real_session_header_alias_is_still_explicit_and_bound(self):
        cid,token=self.connection('next_session')
        code,result=self.chat(cid,token,'legacy-real-window',header='X-Neural-Session')
        self.assertEqual(code,200,result);self.assertEqual(self.upstream.open.call_count,1)
        self.assertEqual(self.host.connections.get(cid)['bound_session_id'],'legacy-real-window')
        self.assertEqual(self.receipts(cid)[0]['session_id'],'legacy-real-window')

    def test_explicit_all_connection_mode_remains_compatible_without_session_header(self):
        cid,token=self.connection('connection')
        self.assertEqual(self.chat(cid,token,request_id='default-turn')[0],200)
        self.assertEqual(self.chat(cid,token,'another-real-window',request_id='other-turn')[0],200)
        self.assertEqual(self.upstream.open.call_count,2)
        self.assertEqual(self.host.connections.get(cid)['session_scope'],'any')
        self.assertEqual({r['session_id'] for r in self.receipts(cid)}, {'api-default-session','another-real-window'})
        self.assertEqual(len(self.host.snapshot('default')['nodes']),2)

    def test_paused_single_window_preserves_forwarding_but_never_claims_or_captures(self):
        cid,token=self.connection('next_session')
        self.host.connections.toggle(cid,False)
        code,result=self.chat(cid,token,text='暂停期间不进入记忆')
        self.assertEqual(code,200,result);self.assertEqual(self.upstream.open.call_count,1)
        self.assertEqual(self.receipts(cid),[])
        self.assertEqual(self.host.connections.get(cid)['session_scope'],'next_session')
        self.assertEqual(self.host.snapshot('default')['nodes'],{})

