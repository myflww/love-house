"""Real isolated Controller requests, with fake installers/processes/credentials.

Set LOVE_HOUSE_UPGRADE_OLD_SOURCE to an existing public 0.10.2rc1 checkout for the
cross-version source proof. Ordinary CI also runs the complete HTTP protocol
against its real current Controller, preserving its existing SQLite schema.
An independent pre-purpose fixture tests the older factual-purpose migration.
Actual EXE/window/install proof remains in the dedicated Windows release job.
"""
import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import windows_upgrade_smoke as smoke


class FixtureCredentials:
    """Only random test scopes under one disposable directory; no native APIs."""
    def __init__(self,path):self.path=Path(path)
    def call(self,operation,account,value=None):
        values=json.loads(self.path.read_text('utf-8')) if self.path.exists() else {}
        if operation=='get':return {'ok':True,'value':values.get(account,''),'found':account in values}
        if operation=='set':values[account]=value
        elif operation=='delete':values.pop(account,None)
        else:raise AssertionError('Unexpected synthetic credential operation')
        self.path.write_text(json.dumps(values),encoding='utf-8')
        return {'ok':True}


def controller_worker(source,data,credentials):
    sys.path.insert(0,str(source))
    sys.path.insert(0,str(Path(source)/'desktop'))
    import windows_app
    from nkb.service.credentials import KeyStore
    factory=KeyStore(allow_source_build=False,windows_backend=FixtureCredentials(credentials))
    windows_app.KeyStore=lambda **kwargs:factory
    original=windows_app.MemoryHost
    def host(*args,**kwargs):
        def blocked(*args,**kwargs):raise AssertionError('Source protocol proof must not call a model')
        return original(*args,organizer_transport=blocked,**kwargs)
    windows_app.MemoryHost=host
    runtime=windows_app.ControllerRuntime(data,testing=True).start()
    try:
        print(json.dumps({'url':runtime.url.rstrip('/'),'version':windows_app.__version__}),flush=True)
        sys.stdin.readline()
    finally:runtime.stop()


class UpgradeSmokeTests(unittest.TestCase):
    def test_release_uses_latest_public_installer_and_explicit_default_migration(self):
        self.assertEqual(smoke.OLD_VERSION,'0.10.2rc1')
        self.assertEqual(smoke.NEW_VERSION,'0.10.3rc1')
        self.assertEqual(smoke.OLD_SETUP_SHA256,'9c69fb782ecddab43ef35c1df075780175e013b7533c039d53ddcb81cebb8d64')
        prior={'enabled':False,'base_url':'https://synthetic-upgrade.invalid/v1','model':'FAKE',
            'max_input_chars':18000,'daily_call_limit':100,'daily_char_limit':200000,
            'batch_size':6,'provider_id':'separate','provider_mode':'separate','connection_id':''}
        migrated=smoke.upgraded_organizer_settings(prior)
        self.assertEqual(migrated,{**prior,'max_input_chars':0,'daily_call_limit':0,'daily_char_limit':0,
            'context_window':0,'max_output_tokens':0,'reasoning_effort':'auto'})
        explicit={**prior,'max_input_chars':32000,'context_window':32768,'max_output_tokens':8192,'reasoning_effort':'high'}
        self.assertEqual(smoke.upgraded_organizer_settings(explicit),{**explicit,'daily_call_limit':0,'daily_char_limit':0})

    def test_full_http_protocol_preserves_existing_schema_with_real_disposable_controllers(self):
        from nkb.service.credentials import KeyStore
        fixture=tempfile.TemporaryDirectory(prefix='upgrade-api-proof-')
        self.addCleanup(fixture.cleanup)
        fixture_root=Path(fixture.name).resolve()
        credentials=fixture_root/'synthetic-credentials.json'
        backend=FixtureCredentials(credentials)
        store=KeyStore(allow_source_build=False,windows_backend=backend)
        requests=[];phases=[]
        old_source=Path(os.environ.get('LOVE_HOUSE_UPGRADE_OLD_SOURCE',str(ROOT))).resolve()
        test=self
        class SourceApp(smoke.App):
            def start(self,version):
                # Lifecycle alone is substituted: every request below uses the
                # real source Controller. No native window readiness is claimed.
                self.old=version==smoke.OLD_VERSION
                source=old_source if self.old else ROOT
                self.process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--fixture-controller',
                    str(source),str(self.data),str(credentials)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,text=True,encoding='utf-8',env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1'})
                line=self.process.stdout.readline()
                test.assertTrue(line,'Source fixture Controller did not start')
                ready=json.loads(line);self.base=ready['url'];phases.append(ready['version'])
                with self.client.open(self.base+'/',timeout=15) as response:response.read()
                return self
            def request(self,path,*args,**kwargs):
                result=super().request(path,*args,**kwargs)
                requests.append((path,kwargs.get('status',200)))
                return result
            def close(self,*,strict=True):
                if self.process and self.process.poll() is None:
                    self.process.stdin.write('stop\n');self.process.stdin.flush();self.process.wait(timeout=20)
                    if strict:test.assertEqual(self.process.returncode,0,self.process.stderr.read())
                    self.process.stdin.close();self.process.stdout.close();self.process.stderr.close()
        # Deliberately retain an unresolved spelling, just as Windows TEMP can
        # contain an 8.3 profile name. run() canonicalizes its installer paths.
        alias=fixture_root/'path-spelling';alias.mkdir()
        old=alias/'..'/'old.exe';new=alias/'..'/'new.exe'
        old.write_bytes(b'SYNTHETIC old installer');new.write_bytes(b'SYNTHETIC new installer')
        real_digest=smoke.digest
        def digest(path):return smoke.OLD_SETUP_SHA256 if Path(path).resolve()==old.resolve() else real_digest(path)
        def install(setup,destination):
            destination.mkdir(parents=True,exist_ok=True)
            (destination/'LoveHouse.exe').write_bytes(b'SYNTHETIC process substituted by Controller')
        with patch.object(smoke,'App',SourceApp),patch.object(smoke,'install',side_effect=install),\
             patch.object(smoke,'digest',side_effect=digest),\
             patch.object(smoke,'sys',SimpleNamespace(platform='win32',version_info=sys.version_info,exc_info=sys.exc_info)),\
             patch.dict(os.environ,{'GITHUB_ACTIONS':'true','LOVE_HOUSE_DISPOSABLE_UPGRADE_RUNNER':'github-hosted'}),\
             patch('nkb.service.credentials.KeyStore',return_value=store):
            result=smoke.run(old,new)
        self.assertTrue(result['ok']);self.assertTrue(result['process_complete'])
        self.assertEqual(result['database_migration'],'passed')
        self.assertEqual(result['connections'],'passed')
        self.assertEqual(result['credential_metadata'],'passed')
        self.assertEqual(result['durable_attempts_and_budget'],'passed')
        self.assertEqual(result['organizer_schema_upgrade'],'existing_schema_preserved')
        self.assertEqual(len(phases),3)
        if 'LOVE_HOUSE_UPGRADE_OLD_SOURCE' in os.environ:self.assertEqual(phases[0],smoke.OLD_VERSION)
        self.assertEqual(phases[1:],[smoke.NEW_VERSION,smoke.NEW_VERSION])
        self.assertGreater(len(requests),40)
        self.assertIn(('/api/connections',401),requests)
        self.assertIn(('/api/persona',403),requests)
        self.assertEqual(json.loads(credentials.read_text('utf-8')),{})

    def make_queue_fixture(self,root,*,legacy=False):
        from nkb.organizer import Organizer
        def forbidden(*args,**kwargs):raise AssertionError('Queue fixture must not call a provider or access graph data')
        if legacy:
            # Construct the actual earlier schema independently. Do not mutate
            # a modern Controller's database to claim it came from an old app.
            with closing(sqlite3.connect(root/'organizer.sqlite3')) as db,db:
                db.executescript('''
                    CREATE TABLE items(library_id TEXT,raw_id TEXT,status TEXT,progress TEXT,
                      job_id TEXT,created REAL,PRIMARY KEY(library_id,raw_id));
                    CREATE TABLE jobs(id TEXT PRIMARY KEY,library_id TEXT,raw_ids TEXT,status TEXT,
                      attempts INTEGER,next_run REAL,lease_until REAL,created REAL,updated REAL,
                      input_json TEXT,guards_json TEXT,plan_json TEXT,result_json TEXT,error_code TEXT,error TEXT);
                    CREATE TABLE calls(id TEXT PRIMARY KEY,library_id TEXT,at REAL,chars INTEGER);
                ''')
        else:
            Organizer(root,snapshot=forbidden,apply=forbidden,credential=forbidden,transport=forbidden)
        with closing(sqlite3.connect(root/'organizer.sqlite3')) as db,db:
            for identity in ('synthetic-one','synthetic-two'):
                db.execute("INSERT INTO items VALUES(?,?,'pending','{}',NULL,1)",(identity,'raw-'+identity))
        return lambda:Organizer(root,snapshot=forbidden,apply=forbidden,credential=forbidden,transport=forbidden)

    def test_existing_queue_schema_preserves_both_purposes_and_all_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reload=self.make_queue_fixture(root)
            with closing(sqlite3.connect(root/'organizer.sqlite3')) as db,db:
                db.execute("ALTER TABLE jobs ADD COLUMN fixture_existing_field TEXT DEFAULT 'keep-me'")
            before=smoke.seed_ledger(root,('synthetic-one','synthetic-two'),'SYNTHETIC-preserve')
            self.assertTrue(before['purpose_column_before'])
            self.assertEqual(before['mode'],'existing_schema_preserved')
            self.assertEqual(len(before['state']['jobs']),4)
            for identity in ('synthetic-one','synthetic-two'):
                jobs=[job for job in before['state']['jobs'] if job['library_id']==identity]
                self.assertEqual({job['purpose'] for job in jobs},{'memory','persona'})
                self.assertEqual({job['attempts'] for job in jobs},{3,4})
                for job in jobs:
                    self.assertEqual(job['fixture_existing_field'],'keep-me')
                    for field in ('input_json','guards_json','plan_json','result_json'):
                        self.assertIn('SYNTHETIC-preserve',job[field])
            reload();smoke.check_ledger(root,before)
            reload();smoke.check_ledger(root,before)

    def test_independent_legacy_schema_migrates_to_memory_without_losing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);migrate=self.make_queue_fixture(root,legacy=True)
            self.assertNotIn('purpose',smoke.queue_schema(root)['jobs'])
            before=smoke.seed_ledger(root,('synthetic-one','synthetic-two'),'SYNTHETIC-legacy')
            self.assertFalse(before['purpose_column_before'])
            self.assertEqual(before['mode'],'legacy_purpose_migrated')
            self.assertEqual(len(before['state']['jobs']),2)
            self.assertNotIn('purpose',smoke.queue_schema(root)['jobs'])
            migrate();smoke.check_ledger(root,before)
            self.assertEqual({job['purpose'] for job in smoke.queue_state(root)['jobs']},{'memory'})
            migrate();smoke.check_ledger(root,before)

    def test_queue_proof_rejects_changed_purpose_payload_budget_or_existing_schema(self):
        changes=["UPDATE jobs SET purpose='memory' WHERE purpose='persona'",
                 "UPDATE jobs SET input_json='{}'", "UPDATE jobs SET guards_json='{}'",
                 "UPDATE jobs SET plan_json='{}'", "UPDATE jobs SET result_json='{}'",
                 'UPDATE jobs SET attempts=0', 'UPDATE calls SET chars=0',
                 'ALTER TABLE jobs RENAME COLUMN guards_json TO missing_guards_json']
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);self.make_queue_fixture(root)
                before=smoke.seed_ledger(root,('synthetic-one','synthetic-two'),'SYNTHETIC-negative')
                with closing(sqlite3.connect(root/'organizer.sqlite3')) as db,db:db.execute(change)
                with self.assertRaises(AssertionError):smoke.check_ledger(root,before)

    def test_cleanup_retries_only_profile_locks_and_preserves_the_initial_failure(self):
        with smoke.owned_fixture() as root:
            profile=root/'合成 数据'/'WebView2';profile.mkdir(parents=True)
            error=PermissionError(13,'SYNTHETIC lock',str(profile/'locked.pma'));error.winerror=32
            original=shutil.rmtree
            calls=[]
            def remove(path,**kwargs):
                calls.append(path)
                if len(calls)==1:raise error
                return original(path,**kwargs)
            with patch.object(smoke.shutil,'rmtree',side_effect=remove),patch.object(smoke.time,'sleep'):
                smoke.cleanup_fixture(root)
            self.assertEqual(len(calls),2)
            # Recreate the ownership marker for the context's final cleanup.
            root.mkdir();(root/'.upgrade-owner.json').write_text(json.dumps({'schema':'love-house-upgrade-owner/v1','pid':os.getpid(),'name':root.name}),encoding='utf-8')
        captured=[]
        def fail_cleanup(root):captured.append(root);raise PermissionError('SYNTHETIC cleanup')
        with patch.object(smoke,'cleanup_fixture',side_effect=fail_cleanup),self.assertRaisesRegex(ValueError,'initial'):
            with smoke.owned_fixture():raise ValueError('initial')
        for directory in captured:shutil.rmtree(directory)

    def test_window_ready_requires_new_bytes_and_the_real_pid_free_start_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'logs/startup.log';log.parent.mkdir()
            def append(value):
                with log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(value)+'\n')
            append({'event':'start','version':smoke.OLD_VERSION})
            append({'event':'window','phase':'window_ready'})
            cursor=smoke.startup_log_cursor(directory)
            self.assertFalse(smoke.window_ready(directory,cursor,smoke.OLD_VERSION))
            append({'event':'start','version':smoke.OLD_VERSION,'frozen':True})
            self.assertFalse(smoke.window_ready(directory,cursor,smoke.OLD_VERSION))
            append({'event':'window','phase':'window_ready','renderer':'edgechromium'})
            self.assertTrue(smoke.window_ready(directory,cursor,smoke.OLD_VERSION))
            self.assertFalse(smoke.window_ready(directory,cursor,smoke.NEW_VERSION))

    def test_window_ready_handles_rotation_between_start_and_ready_without_reusing_old_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'logs/startup.log';log.parent.mkdir()
            log.write_text(json.dumps({'event':'start','version':smoke.OLD_VERSION})+'\n'+
                json.dumps({'event':'window','phase':'window_ready'})+'\n',encoding='utf-8')
            cursor=smoke.startup_log_cursor(directory)
            with log.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'event':'start','version':smoke.NEW_VERSION})+'\n')
            log.replace(log.with_name('startup.1.log'))
            log.write_text(json.dumps({'event':'window','phase':'window_ready'})+'\n',encoding='utf-8')
            self.assertTrue(smoke.window_ready(directory,cursor,smoke.NEW_VERSION))
            self.assertFalse(smoke.window_ready(directory,cursor,smoke.OLD_VERSION))

    def test_cleanup_does_not_retry_other_files_or_permission_denial(self):
        with smoke.owned_fixture() as root:
            for target,number in ((root/'合成 数据'/'organizer.sqlite3',32),
                    (root/'合成 数据'/'WebView2'/'denied.pma',5)):
                error=PermissionError(13,'SYNTHETIC failure',str(target));error.winerror=number
                with patch.object(smoke.shutil,'rmtree',side_effect=error) as remove,\
                     patch.object(smoke.time,'sleep') as wait,self.assertRaises(PermissionError):
                    smoke.cleanup_fixture(root)
                self.assertEqual(remove.call_count,1);wait.assert_not_called()
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(AssertionError):smoke.cleanup_fixture(outside)
            self.assertTrue(Path(outside).exists())


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--fixture-controller':controller_worker(*sys.argv[2:])
    else:unittest.main()
