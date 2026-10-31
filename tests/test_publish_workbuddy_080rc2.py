"""Publication cannot bypass frozen source, four upgrade cells or append-only assets."""
from copy import deepcopy
import io
import json
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import publish_workbuddy_080rc2 as publish
from tests.test_verify_signed_080rc2 import candidate,probe

SOURCE='1'*40
PUBLICATION='2'*40


def archive(entries):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as zipped:
        for name,raw in entries.items():zipped.writestr(name,raw)
    return buffer.getvalue()


def metadata():
    value=json.loads((publish.ROOT/'scripts/workbuddy-080rc2-publication.json').read_text('utf-8'))
    value.update(ready=True,source_commit=SOURCE,signed_head='3'*40,signed_run=91)
    value['source_runs']={name:n for n,name in enumerate(publish.SOURCE_RUNS,1)}
    for n,key in enumerate(('windows_artifact','windows_evidence_artifact','android_build_artifact'),10):
        value[key].update(id=n,bytes=10,sha256='a'*64)
    for entry in value['windows_files'].values():entry.update(bytes=10,sha256='a'*64)
    for n,entry in enumerate(value['signed_artifacts'],20):entry.update(id=n,bytes=10,sha256='a'*64)
    for entry in value['doc_assets'].values():entry.update(bytes=10,sha256='a'*64)
    value['release_notes'].update(bytes=10,sha256='a'*64)
    return value


def instrumentation(count=6):
    text=''
    for index in range(count):
        for code in (1,0):
            text+=(f'INSTRUMENTATION_STATUS: class=synthetic.Fixture\nINSTRUMENTATION_STATUS: test=test{index}\n'
                   f'INSTRUMENTATION_STATUS: numtests={count}\nINSTRUMENTATION_STATUS_CODE: {code}\n')
    return text+f'OK ({count} tests)\nINSTRUMENTATION_CODE: -1\n'


def screenshot():
    def chunk(kind,raw):return struct.pack('>I',len(raw))+kind+raw+struct.pack('>I',zlib.crc32(kind+raw)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b'')


def report(api=28,old=1):
    transcript=instrumentation();seed=probe('seed',old,api);upgraded=probe('verify',old,api)
    value={'schema':'love-house-android-080rc2-verification/v1','candidate':candidate(),'signature_and_metadata':'passed',
           'api_level':api,'from_version_code':old,'identities':{'apk':{'package':publish.verify.APP_ID,'version_code':'3',
               'version_name':'0.8.0rc2','min_sdk':['26'],'target_sdk':['36']},'test_apk':{
               'package':publish.verify.APP_ID+'.test','runner':'androidx.test.runner.AndroidJUnitRunner','target_package':publish.verify.APP_ID}},
           'instrumentation':{'tests':6,'failures':0,'errors':0,'skipped':0},
           'upgrade_preservation':{'passed':True,'from_version_code':old,'to_version_code':3,
               'seed_probe_sha256':publish.identity(seed.encode())['sha256'],'verify_probe_sha256':publish.identity(upgraded.encode())['sha256']},
           'instrument_sha256':publish.identity(transcript.encode())['sha256']}
    return value,transcript,seed,upgraded,screenshot()


class FakePublisher:
    def __init__(self):
        self.release=None;self.assets={};self.mutations=[];self.tag=None
        self.historical={'id':7,'tag_name':'v0.8.0rc1','assets':[{'name':'OLD-UNCHANGED'}]}
    def pages(self,path,key=None):
        if path==publish.BASE+'releases':return [self.historical]+([self.release] if self.release else [])
        if path.endswith('/assets'):return list(self.assets.values())
        raise AssertionError('Unexpected listing')
    def request(self,method,path,**kwargs):
        if path==publish.BASE+'git/ref/tags/'+publish.TAG:
            return {'object':{'type':'commit','sha':self.tag}} if self.tag else None
        if method=='POST' and path==publish.BASE+'releases':
            self.mutations.append((method,path));self.release={**kwargs['payload'],'id':99,'html_url':'https://github.com/myflww/love-house/releases/tag/v0.8.0rc2'}
            return deepcopy(self.release)
        if method=='POST' and '/assets?name=' in path:
            name=path.split('name=')[1];raw=kwargs['content'];self.mutations.append((method,name))
            self.assets[name]={'id':len(self.assets)+100,'name':name,'size':len(raw),'state':'uploaded','digest':'sha256:'+publish.identity(raw)['sha256'],'raw':raw}
            return self.assets[name]
        if method=='PATCH':
            self.mutations.append((method,path));self.release.update(kwargs['payload']);self.tag=PUBLICATION
            return deepcopy(self.release)
        if method=='GET' and '/releases/assets/' in path:
            return next(item['raw'] for item in self.assets.values() if str(item['id'])==path.rsplit('/',1)[1])
        raise AssertionError('Unexpected mutation or request')


class WorkBuddyPublicationTests(unittest.TestCase):
    def test_disabled_placeholder_and_incomplete_matrix_fail_closed(self):
        placeholder=json.loads((publish.ROOT/'scripts/workbuddy-080rc2-publication.json').read_text('utf-8'))
        if placeholder.get('ready') is not True:
            with self.assertRaises(ValueError):publish.validate_metadata(placeholder)
        good=metadata();self.assertEqual(publish.validate_metadata(good),good)
        for key,change in [('ready',False),('source_commit','PENDING'),('signed_run',0),('signed_run',True),('password','SYNTHETIC')]:
            bad={**good,key:change}
            with self.subTest(key=key),self.assertRaises(ValueError):publish.validate_metadata(bad)
        for mutate in (lambda x:x['signed_artifacts'].pop(),lambda x:x['signed_artifacts'].__setitem__(1,deepcopy(x['signed_artifacts'][0])),
                       lambda x:x['source_runs'].pop('ios'),lambda x:x['doc_assets'][next(iter(publish.DOCS))].update(path='../private.json')):
            bad=deepcopy(good);mutate(bad)
            with self.assertRaises(ValueError):publish.validate_metadata(bad)

    def test_source_freeze_rejects_any_production_change_and_dirty_checkout(self):
        good=metadata()
        with patch.object(publish,'git',side_effect=[PUBLICATION,'','','scripts/workbuddy-080rc2-publication.json','']):
            publish.verify_source(Path('.'),good,PUBLICATION)
        for documentation in ('README.md','docs/手机版安装与使用.md'):
            with patch.object(publish,'git',side_effect=[PUBLICATION,'','',documentation,'']):
                publish.verify_source(Path('.'),good,PUBLICATION)
        for path in ('nkb/service/host.py','mobile/web/app.js','android/app/build.gradle','desktop/main.py','scripts/build_windows.py','LICENSE'):
            with patch.object(publish,'git',side_effect=[PUBLICATION,'','',path]),self.assertRaises(ValueError):
                publish.verify_source(Path('.'),good,PUBLICATION)
        with patch.object(publish,'git',side_effect=[PUBLICATION,'','','',' M nkb/service/host.py']),self.assertRaises(ValueError):
            publish.verify_source(Path('.'),good,PUBLICATION)

    @unittest.skipUnless(shutil.which('git'),'Git is required for actual UTF-8 path proof')
    def test_real_git_utf8_document_change_is_recognized_by_exact_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def run(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True,encoding='utf-8',stderr=subprocess.DEVNULL).strip()
            run('init');run('config','user.name','Synthetic Publisher QA');run('config','user.email','synthetic@example.invalid')
            (root/'docs').mkdir();document=root/'docs/手机版安装与使用.md';document.write_text('Synthetic original',encoding='utf-8')
            run('add','.');run('commit','-m','Synthetic source');source=run('rev-parse','HEAD')
            document.write_text('Synthetic updated origin guidance',encoding='utf-8')
            run('add','.');run('commit','-m','Synthetic documentation update');publication=run('rev-parse','HEAD')
            publish.verify_source(root,{'source_commit':source,'signed_head':source},publication)

    def test_zip_never_extracts_and_rejects_paths_symlinks_or_budgets(self):
        for name in ('../private','/absolute','C:/drive','a\\..\\private','a/../private'):
            with self.subTest(name=name),self.assertRaises(ValueError):publish.safe_zip(archive({name:b'fixture'}))
        with self.assertRaises(ValueError):publish.safe_zip(archive({'large':b'0123456789'}),maximum_total=3)
        item=zipfile.ZipInfo('link');item.external_attr=0o120777<<16
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as zipped:zipped.writestr(item,b'../private')
        with self.assertRaises(ValueError):publish.safe_zip(buffer.getvalue())

    def test_signed_payload_must_match_build_payload_except_signature_files(self):
        unsigned={'AndroidManifest.xml':b'SYNTHETIC manifest','classes.dex':b'SYNTHETIC code','assets/web/index.html':b'SYNTHETIC UI'}
        signed={**unsigned,'META-INF/MANIFEST.MF':b'signature manifest','META-INF/RELEASE.RSA':b'signature'}
        self.assertEqual(publish.unsigned_payload(archive(unsigned)),publish.unsigned_payload(archive(signed)))
        changed={**signed,'classes.dex':b'UNTESTED modified code'}
        self.assertNotEqual(publish.unsigned_payload(archive(unsigned)),publish.unsigned_payload(archive(changed)))

    def test_all_four_upgrade_reports_require_exact_six_tests_and_complete_probes(self):
        for api in (28,36):
            for old in (1,2):
                value,*evidence=report(api,old)
                result=publish.checked_report(candidate(),value,api,old,*evidence)
                self.assertEqual(result['instrumentation']['tests'],6)
                for field,replacement in [('api_level',27),('signature_and_metadata','failed'),('candidate',{}),('upgrade_preservation',{})]:
                    with self.assertRaises(ValueError):publish.checked_report(candidate(),{**value,field:replacement},api,old,*evidence)
                with self.assertRaises(ValueError):publish.checked_report(candidate(),value,api,old,instrumentation(5),*evidence[1:])

    def test_ci_runs_must_share_exact_source_and_complete_required_jobs(self):
        class Client:
            run={'head_sha':SOURCE,'status':'completed','conclusion':'success','path':'.github/workflows/android.yml','repository':{'full_name':publish.REPOSITORY}}
            jobs=[{'name':'android (28)','status':'completed','conclusion':'success'},{'name':'android (36)','status':'completed','conclusion':'success'}]
            def request(self,*args,**kwargs):return self.run
            def pages(self,*args,**kwargs):return self.jobs
        client=Client();publish.validate_run(client,1,SOURCE,'android.yml',{'android (28)','android (36)'})
        for field,value in [('head_sha','4'*40),('conclusion','failure'),('status','in_progress'),('path','.github/workflows/other.yml')]:
            client.run={**Client.run,field:value}
            with self.assertRaises(ValueError):publish.validate_run(client,1,SOURCE,'android.yml',{'android (28)','android (36)'})
        client.run=Client.run;client.jobs=[Client.jobs[0]]
        with self.assertRaises(ValueError):publish.validate_run(client,1,SOURCE,'android.yml',{'android (28)','android (36)'})

    def test_android_input_build_commit_requires_the_exact_frozen_git_tree(self):
        recorded='4'*40;tree='5'*40
        client=type('Client',(),{'request':lambda self,*args,**kwargs:{'sha':recorded,'tree':{'sha':tree}}})()
        build={'schema':'love-house-android-build/v1','source_commit':recorded}
        with patch.object(publish,'git',return_value=tree) as git:
            result=publish.input_build_provenance(client,Path('.'),SOURCE,build)
        self.assertEqual(result,{'input_build_commit':recorded,'input_build_tree':tree,'frozen_tree_match':True})
        git.assert_called_once_with(Path('.'),'rev-parse',SOURCE+'^{tree}')
        with patch.object(publish,'git',return_value='6'*40),self.assertRaises(ValueError):
            publish.input_build_provenance(client,Path('.'),SOURCE,build)
        # Even an identical recorded head must be fetched and tree-checked.
        build['source_commit']=recorded=SOURCE
        with patch.object(publish,'git',return_value='6'*40),self.assertRaises(ValueError):
            publish.input_build_provenance(client,Path('.'),SOURCE,build)

    def test_android_input_build_commit_rejects_missing_malformed_or_foreign_metadata(self):
        from unittest.mock import Mock
        client=Mock()
        for recorded in (None,'PENDING','../other/repository','0'*40,True):
            with self.subTest(recorded=recorded),self.assertRaises(ValueError):
                publish.input_build_provenance(client,Path('.'),SOURCE,{'schema':'love-house-android-build/v1','source_commit':recorded})
        client.request.assert_not_called()
        for response in ({'sha':'6'*40,'tree':{'sha':'5'*40}},
                         {'sha':'4'*40,'tree':{'sha':'PENDING'}},
                         {'sha':'4'*40,'tree':None}):
            client.request.return_value=response
            with patch.object(publish,'git',return_value='5'*40),self.assertRaises(ValueError):
                publish.input_build_provenance(client,Path('.'),SOURCE,{'schema':'love-house-android-build/v1','source_commit':'4'*40})

    def test_draft_first_and_idempotent_resume_never_change_prior_release(self):
        client=FakePublisher();before=deepcopy(client.historical)
        assets={name:('SYNTHETIC '+name).encode() for name in publish.PUBLIC_NAMES}
        result=publish.publish(client,PUBLICATION,assets,'Reviewed synthetic release notes')
        self.assertFalse(result['draft']);self.assertEqual(client.historical,before)
        mutations=deepcopy(client.mutations)
        publish.publish(client,PUBLICATION,assets,'Reviewed synthetic release notes')
        self.assertEqual(client.mutations,mutations)
        self.assertEqual({item[0] for item in mutations},{'POST','PATCH'})
        self.assertEqual(len(client.assets),9)

    def test_existing_mismatched_assets_or_target_are_never_overwritten(self):
        assets={name:b'SYNTHETIC reviewed bytes' for name in publish.PUBLIC_NAMES}
        for corruption in ('target','asset','extra','notes'):
            client=FakePublisher();publish.publish(client,PUBLICATION,assets,'Reviewed notes')
            client.release['draft']=True
            if corruption=='target':client.tag='4'*40
            if corruption=='asset':next(iter(client.assets.values()))['digest']='sha256:'+'0'*64
            if corruption=='extra':client.assets['private-key']={'name':'private-key'}
            if corruption=='notes':client.release['body']='Unexpected existing text'
            before=deepcopy(client.mutations)
            with self.subTest(corruption=corruption),self.assertRaises(ValueError):publish.publish(client,PUBLICATION,assets,'Reviewed notes')
            self.assertEqual(client.mutations,before)
        with self.assertRaises(ValueError):publish.publish(FakePublisher(),PUBLICATION,{**assets,'developer-test.apk':b'fixture'},'Reviewed notes')

    def test_github_redirects_strip_token_and_disallow_unknown_hosts_or_writes(self):
        handler=publish.StorageRedirect()
        request=urllib.request.Request('https://api.github.com/repos/myflww/love-house/actions/artifacts/1/zip',headers={'Authorization':'Bearer SYNTHETIC'})
        for url in ('https://productionresultssa1.blob.core.windows.net/path?signature=fixture',
                    'https://release-assets.githubusercontent.com/fixture'):
            result=handler.redirect_request(request,None,302,'',{},url)
            self.assertFalse(result.has_header('Authorization'))
        credential_url='https://'+'user:password'+'@release-assets.githubusercontent.com/file'
        for url in ('https://untrusted.example/file','http://release-assets.githubusercontent.com/file',credential_url):
            with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'',{},url)
        post=urllib.request.Request(request.full_url,data=b'fixture',method='POST')
        with self.assertRaises(ValueError):handler.redirect_request(post,None,302,'',{},'https://release-assets.githubusercontent.com/file')

    def test_actions_archives_use_json_redirect_accept_and_release_assets_stay_binary(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,maximum):return b'SYNTHETIC'
        class Opener:
            def __init__(self):self.requests=[]
            def open(self,request,**kwargs):self.requests.append(request);return Response()
        client=publish.GitHub('SYNTHETIC');client.opener=opener=Opener()
        for endpoint,expected in (
                ('actions/artifacts/123/zip','application/vnd.github+json'),
                ('releases/assets/456','application/octet-stream'),
                ('git/blobs/'+'4'*40,'application/vnd.github.raw+json')):
            raw=client.request('GET',publish.BASE+endpoint,binary=True,expected_bytes=9)
            self.assertEqual(raw,b'SYNTHETIC')
            self.assertEqual(opener.requests[-1].get_header('Accept'),expected)

    def test_api_failure_identifies_only_public_route_and_status_without_bearer(self):
        from unittest.mock import Mock
        from urllib.error import HTTPError
        client=publish.GitHub('SYNTHETIC-PRIVATE-VALUE');client.opener=Mock()
        endpoint=publish.BASE+'actions/artifacts/123/zip'
        client.opener.open.side_effect=HTTPError('https://api.github.com'+endpoint,415,'Unsupported',{},None)
        with self.assertRaises(publish.PublicationError) as raised:
            client.request('GET',endpoint,binary=True,expected_bytes=9)
        self.assertIn('GET '+endpoint,str(raised.exception));self.assertIn('HTTP 415',str(raised.exception))
        self.assertNotIn(client.token,str(raised.exception))


if __name__=='__main__':unittest.main()
