"""Frozen-package organizer proof: synthetic HTTP API, temporary data, session key.

This helper never reads the OS credential store, real memories or a vendor API.
The executable's backend smoke calls it so freezing omissions fail the build.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import uuid

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost


def organizer_smoke(directory):
    calls=[];failures=[];key='FAKE-WINDOWS-ORGANIZER-'+uuid.uuid4().hex
    original='假数据：我喜欢没有糖的茶。'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                assert self.path=='/v1/chat/completions'
                assert self.headers.get('Authorization')=='Bearer '+key
                length=int(self.headers.get('Content-Length','0'))
                assert 0<length<200000
                body=self.rfile.read(length);assert key.encode() not in body
                data=json.loads(body)
                assert data['model']=='FAKE-WINDOWS-JSON-MODEL' and data['stream'] is False
                payload=json.loads(data['messages'][1]['content'])
                raw=payload['raw'][0];assert raw['roles']['user']==original
                calls.append(True)
                result={'version':1,'operations':[{'action':'remember','layer':'preference',
                    'key':'user.drink','text':'用户喜欢无糖茶','certainty':'clear','domain':'real',
                    'evidence':[{'id':raw['id'],'role':'user','quote':original}]}]}
                response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result,ensure_ascii=False)}}]}
                encoded=json.dumps(response,ensure_ascii=False).encode('utf-8')
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
            except Exception:
                failures.append(True)
                self.send_response(500);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    host=None;store=KeyStore(allow_source_build=False,allow_keychain=False);ref=None
    try:
        with tempfile.TemporaryDirectory(prefix='organizer-',dir=Path(directory)) as temporary:
            try:
                host=MemoryHost(Path(temporary),key_store=store)
                # No background race: this proof explicitly runs the one task.
                host.organizer.stop();host.organizer._stopping.clear()
                connection=host.new_connection({'host':'api','library_id':'default','name':'FAKE organizer proof'})
                record=host.accept(connection['connection']['id'],connection['config']['connectionToken'],
                    {'session_id':'FAKE-organizer-window','event_id':'FAKE-organizer-event','normalized':
                     {'type':'turn','turn_id':'FAKE-organizer-event','status':'complete',
                      'user':original,'assistant':'假回复：原文保留。'}})
                assert record['status']=='saved'
                base='http://127.0.0.1:'+str(server.server_port)+'/v1'
                ref=host.organizer_ref('default',base,True)
                view=host.organizer_settings('default',{'enabled':True,'provider_mode':'separate',
                    'base_url':base,'model':'FAKE-WINDOWS-JSON-MODEL','api_key':key,'save_key':False})
                assert view['provider']['credential_ready'] and view['provider']['model_ready']
                assert not view['provider']['key_saved'] and view['provider']['storage']=='session'
                outcome=host.organizer.run_once('default')
                assert outcome['status']=='done'
                graph=host.snapshot('default')
                generated=[n for n in graph['nodes'].values() if n.get('meta',{}).get('source')=='organizer']
                assert len(generated)==1 and generated[0]['text']==original
                evidence=generated[0]['meta']['organizer_evidence'][0]
                assert evidence['role']=='user' and evidence['quote']==original
                assert host.organizer.status('default')['usage_24h']['count']==1
                assert key not in json.dumps({'view':view,'outcome':outcome,'graph':graph})
                assert len(calls)==1 and not failures
            finally:
                if host:host.stop()
                if ref:store.delete(ref)
        return {'status':'passed','transport':'loopback-http','fake_api_calls':1,
                'source_evidence_preserved':True,'session_only_credential':True,
                'real_model_calls':0,'real_credentials_accessed':False,'cleanup':'removed'}
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
