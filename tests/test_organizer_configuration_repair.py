"""Configuration repair uses disposable libraries and a real loopback fake API.

No user credential store, remote provider or paid API is contacted.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import ssl

from nkb.errors import ValidationError
from nkb.organizer.model import call_model, OrganizerError
from nkb.service import credentials
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost


KEY='FAKE-CONFIGURATION-REPAIR-KEY'
NEW_KEY='FAKE-REPAIRED-CONFIGURATION-KEY'


class OrganizerConfigurationRepairTests(unittest.TestCase):
    def setUp(self):
        self.session=patch.object(credentials,'_SESSION',{});self.session.start()
        self.tmp=tempfile.TemporaryDirectory();self.requests=[];self.api_status=200
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append({'authorization':self.headers.get('Authorization'),
                                       'path':self.path,'data':data})
                status=owner.api_status
                if status!=200:
                    value={'error':{'message':KEY+' remote private diagnostics'}}
                else:
                    raw=json.loads(data['messages'][1]['content'])['raw'][0]
                    value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(
                        {'version':1,'operations':[{'action':'remember','layer':'preference',
                         'key':'user.drink','text':'用户喜欢无糖茶','certainty':'clear','domain':'real',
                         'evidence':[{'id':raw['id'],'role':'user','quote':raw['roles']['user']}]}]},
                        ensure_ascii=False)}}]}
                body=json.dumps(value,ensure_ascii=False).encode('utf-8')
                self.send_response(status);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.api=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.api.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.api.server_port)+'/v1'
        self.host=MemoryHost(Path(self.tmp.name),key_store=KeyStore(allow_keychain=False))
        self.host.organizer.stop();self.host.organizer._stopping.clear()
        c=self.host.new_connection({'name':'合成测试鱼','host':'api','library_id':'default'})
        self.connection=c
        self.host.accept(c['connection']['id'],c['config']['connectionToken'],
            {'session_id':'synthetic-session','event_id':'one','normalized':
             {'type':'turn','turn_id':'one','status':'complete','user':'我喜欢喝无糖茶。','assistant':'记住了。'}})

    def tearDown(self):
        self.host.stop();self.api.shutdown();self.api.server_close();self.thread.join(timeout=2)
        self.tmp.cleanup();self.session.stop()

    def configure(self,**data):
        return self.host.organizer_settings('default',{'enabled':True,'provider_mode':'separate',
            'base_url':self.base,'model':'synthetic-json-model','api_key':KEY,'save_key':False,**data})

    def usage(self):
        return self.host.organizer.status('default')['usage_24h']['count']

    def exhaust(self):
        result=None
        for _ in range(3):
            with self.host.organizer.db() as db:db.execute("UPDATE jobs SET next_run=0 WHERE library_id='default'")
            result=self.host.organizer.run_once('default')
        self.assertEqual(result['status'],'failed',result)
        return result

    def test_real_http_request_records_only_validated_plan_and_does_not_expose_credential(self):
        view=self.configure();self.assertTrue(view['provider']['model_ready'])
        result=self.host.organizer.run_once('default')
        self.assertEqual(result['status'],'done',result);self.assertEqual(len(self.requests),1)
        self.assertEqual(self.requests[0]['path'],'/v1/chat/completions')
        self.assertEqual(self.requests[0]['authorization'],'Bearer '+KEY)
        graph=self.host.snapshot('default')
        derived=[n for n in graph['nodes'].values() if n['meta'].get('source')=='organizer']
        self.assertEqual(len(derived),1);self.assertEqual(derived[0]['text'],'我喜欢喝无糖茶。')
        for value in (graph,result,self.host.organizer_view('default')):
            self.assertNotIn(KEY,json.dumps(value))

    def test_invalid_settings_and_header_credentials_never_replace_a_working_key(self):
        self.configure();before=self.host.snapshot('default')
        for data in ({'api_key':NEW_KEY,'batch_size':0},{'api_key':NEW_KEY,'daily_call_limit':0},
                     {'api_key':NEW_KEY,'base_url':'https://'+'user:secret@example.invalid/v1'},
                     {'api_key':'BAD KEY'},{'api_key':'密钥不是ASCII'}, {'api_key':'x'*4097},
                     {'api_key':NEW_KEY,'save_key':'false'}):
            with self.subTest(fields=tuple(data)):
                with self.assertRaises(ValidationError):self.configure(**data)
                current=self.host.organizer_credential('default',self.host.organizer_view('default')['settings'])
                self.assertEqual(current['api_key'],KEY)
                self.assertEqual(before,self.host.snapshot('default'))
        self.assertEqual(self.requests,[]);self.assertEqual(self.usage(),0)

    def test_missing_model_consumes_no_call_budget_and_is_recovered_after_config_repair(self):
        self.configure(model='')
        self.assertFalse(self.host.organizer_view('default')['provider']['model_ready'])
        failed=self.exhaust();self.assertEqual(failed['code'],'missing_model')
        self.assertEqual(self.requests,[]);self.assertEqual(self.usage(),0)
        result=self.configure()
        self.assertEqual(result['resumed_configuration_jobs'],1)
        self.assertEqual(result['batches'][0]['attempts'],0)
        self.assertEqual(self.host.organizer.run_once('default')['status'],'done')
        self.assertEqual(self.usage(),1)

    def test_new_capture_between_snapshot_and_queue_claim_is_not_misreported_as_deleted(self):
        self.configure();self.assertEqual(self.host.organizer.run_once('default')['status'],'done')
        original_claim=self.host.organizer._claim
        def claim_after_capture(*args,**kwargs):
            c=self.connection
            accepted=self.host.accept(c['connection']['id'],c['config']['connectionToken'],
                {'session_id':'synthetic-session','event_id':'captured-after-snapshot','normalized':
                 {'type':'turn','turn_id':'captured-after-snapshot','status':'complete',
                  'user':'后来我还喜欢喝桂花茶。','assistant':'保留这条后到的原文。'}})
            self.assertEqual(accepted['status'],'saved')
            return original_claim(*args,**kwargs)
        with patch.object(self.host.organizer,'_claim',side_effect=claim_after_capture):
            result=self.host.organizer.run_once('default')
        self.assertEqual(result['status'],'done',result)
        self.assertEqual(len(self.requests),2)
        self.assertEqual(self.host.organizer_view('default')['status']['failed'],0)

    def test_auth_failure_has_actionable_safe_error_and_only_changed_key_requeues_it(self):
        self.configure();self.api_status=401
        failed=self.exhaust();self.assertEqual(failed['code'],'provider_authentication')
        self.assertIn('401',failed['error']);self.assertNotIn(KEY,failed['error'])
        self.assertEqual(self.usage(),3)
        self.assertEqual(self.configure()['resumed_configuration_jobs'],0)
        self.api_status=200
        repaired=self.configure(api_key=NEW_KEY)
        self.assertEqual(repaired['resumed_configuration_jobs'],1)
        self.assertEqual(self.usage(),3)
        result=self.host.organizer.run_once('default')
        self.assertEqual(result['status'],'done',result);self.assertEqual(self.usage(),4)
        self.assertEqual(self.requests[-1]['authorization'],'Bearer '+NEW_KEY)

    def old_false_deletion(self):
        self.configure()
        job=self.host.organizer._claim('default',self.host.organizer_view('default')['settings'],True)
        with self.host.organizer.db() as db:
            db.execute("UPDATE jobs SET status='failed',error_code='source_deleted',error='来源已删除，未重新整理' WHERE id=?",(job['id'],))
            db.execute("UPDATE items SET status='failed' WHERE job_id=?",(job['id'],))
        return job

    def test_explicit_run_recovers_an_old_false_deletion_once_without_resetting_attempts_or_budget(self):
        job=self.old_false_deletion()
        self.assertEqual(self.host.organizer.run_once('default',flush=False)['status'],'waiting')
        self.assertEqual(self.requests,[])
        result=self.host.organizer.run_once('default')
        self.assertEqual(result['status'],'done',result)
        self.assertEqual(self.host.organizer_view('default')['batches'][0]['attempts'],2)
        self.assertEqual(self.usage(),1)
        self.assertEqual(self.host.organizer.repair_source_jobs('default'),0)
        self.assertEqual(self.host.organizer.run_once('default')['status'],'waiting')
        self.assertEqual(len(self.requests),1)

    def test_missing_archive_disabled_source_and_cached_plan_are_not_false_deletion_repairs(self):
        job=self.old_false_deletion()
        with patch.object(self.host.organizer,'read_archive',return_value=None):
            self.assertEqual(self.host.organizer.repair_source_jobs('default'),0)
        raw=next(n for n in self.host.snapshot('default')['nodes'].values() if n['meta'].get('source')=='conversation_turn')
        def disabled(brain):brain.nodes[raw['id']]['meta']['memory_disabled']=True
        self.host.transact('default',disabled)
        self.assertEqual(self.host.organizer.repair_source_jobs('default'),0)
        self.host.transact('default',lambda brain:brain.nodes[raw['id']]['meta'].pop('memory_disabled'))
        with self.host.organizer.db() as db:db.execute("UPDATE jobs SET plan_json='{}' WHERE id=?",(job['id'],))
        self.assertEqual(self.host.organizer.repair_source_jobs('default'),0)
        self.assertEqual(self.requests,[]);self.assertEqual(self.usage(),0)

    def test_forgetting_during_false_deletion_proof_cannot_requeue_or_send_original(self):
        job=self.old_false_deletion()
        read=self.host.organizer.read_archive
        raw=next(iter(self.host.snapshot('default')['nodes'].values()))
        def forget_after_read(library_id,receipt_id):
            archive=read(library_id,receipt_id)
            self.host.forget_memory(library_id,raw['id'])
            return archive
        with patch.object(self.host.organizer,'read_archive',side_effect=forget_after_read):
            self.assertEqual(self.host.organizer.repair_source_jobs('default'),0)
        self.assertEqual(self.host.organizer.run_once('default')['status'],'waiting')
        self.assertEqual(self.requests,[])
        self.assertEqual(self.host.organizer_view('default')['batches'][0]['status'],'cancelled')

    def test_quota_and_invalid_evidence_tasks_are_not_revived_by_key_change(self):
        self.configure();self.api_status=429
        failed=self.exhaust();self.assertEqual(failed['code'],'rate_limited')
        self.assertIn('429',failed['error']);self.assertEqual(self.usage(),3)
        self.assertEqual(self.configure(api_key=NEW_KEY)['resumed_configuration_jobs'],0)
        with self.host.organizer.db() as db:
            db.execute("UPDATE jobs SET error_code='invalid_evidence' WHERE id=?",(failed['job_id'],))
        self.assertEqual(self.configure(api_key=KEY)['resumed_configuration_jobs'],0)
        self.assertEqual(len(self.requests),3)

    def test_recovery_is_scoped_and_cannot_revive_rejected_or_completed_jobs(self):
        self.configure(model='');failed=self.exhaust()
        other=self.host.manager.create_library('另一只合成鱼')['id']
        with self.host.organizer.db() as db:
            row=dict(db.execute('SELECT * FROM jobs WHERE id=?',(failed['job_id'],)).fetchone())
            columns=','.join(row);marks=','.join('?' for _ in row)
            for jid,library,status in [('other-library',other,'failed'),('already-done','default','done'),
                                       ('user-rejected','default','rejected')]:
                copy={**row,'id':jid,'library_id':library,'status':status}
                db.execute(f'INSERT INTO jobs({columns}) VALUES({marks})',tuple(copy.values()))
        self.assertEqual(self.configure()['resumed_configuration_jobs'],1)
        with self.host.organizer.db() as db:
            statuses={r['id']:r['status'] for r in db.execute('SELECT id,status FROM jobs')}
        self.assertEqual(statuses['other-library'],'failed');self.assertEqual(statuses['already-done'],'done')
        self.assertEqual(statuses['user-rejected'],'rejected')


class SafeProviderDiagnosticsTests(unittest.TestCase):
    def test_http_status_and_certificate_failures_are_classified_without_provider_text(self):
        settings={'base_url':'https://example.invalid/v1','model':'synthetic'}
        for status,code in ((400,'provider_request_rejected'),(401,'provider_authentication'),(402,'provider_insufficient_balance'),
                            (403,'provider_access_denied'),(404,'provider_not_found'),(422,'provider_request_rejected'),
                            (429,'rate_limited'),(503,'provider_unavailable'),(418,'provider_http_error')):
            with self.subTest(status=status):
                def fail(*args,**kwargs):raise HTTPError('https://example.invalid/?secret='+KEY,status,KEY,{},None)
                with self.assertRaises(OrganizerError) as caught:call_model(settings,KEY,{},fail)
                self.assertEqual(caught.exception.code,code);self.assertNotIn(KEY,str(caught.exception))
        def tls(*args,**kwargs):raise URLError(ssl.SSLCertVerificationError(KEY))
        with self.assertRaises(OrganizerError) as caught:call_model(settings,KEY,{},tls)
        self.assertEqual(caught.exception.code,'tls_error');self.assertNotIn(KEY,str(caught.exception))


if __name__=='__main__':unittest.main()
