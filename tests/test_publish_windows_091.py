"""Publication tests use only synthetic process reports, ZIP bytes and API state."""
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import publish_windows_091 as publish

SOURCE='1'*40
PUBLICATION='2'*40


def archive(files):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as result:
        for name,raw in files.items():result.writestr(name,raw)
    return output.getvalue()


def metadata():
    entry=publish.identity(b'SYNTHETIC')
    return {'schema':publish.SCHEMA,'ready':True,'source_commit':SOURCE,
        'source_runs':{'windows':1,'regression':2,'connection':3},
        'windows_artifact':{'id':101,'name':'love-house-windows-x64',**entry},
        'windows_evidence_artifact':{'id':102,'name':'windows-test-evidence',**entry},
        'windows_files':{name:entry.copy() for name in (publish.EXE,publish.PORTABLE,publish.CHECKSUMS)},
        'astrbot_package':entry.copy(),'notes_path':publish.NOTES,'release_notes':entry.copy(),
        'doc_assets':{name:{'path':path,**entry} for name,path in publish.DOCS.items()}}


def reports():
    files={}
    for name in publish.REPORTS:
        report={'ok':True,'process_complete':True,'phase':'complete','version':publish.VERSION,
            'cleanup':{'status':'removed','isolated':True}}
        if name in publish.BACKEND_REPORTS:
            report.update(organizer=publish.ORGANIZER_REPORT.copy(),sharing_roundtrip='passed',restart='passed')
        else:
            report.update(renderer='edgechromium',controller_stopped=True,native_exports={
                **{k:'passed' for k in publish.NATIVE_EXPORT_CHECKS},'dialog_selection':'synthetic_owned_path','astrbot_sha256':'3'*64})
        files[name]=report
    return files


def report_zip(files):return archive({name:json.dumps(value).encode() for name,value in files.items()})


class FakePublisher:
    def __init__(self):
        self.release=None;self.assets={};self.mutations=[];self.tag=None
        self.historical={'id':7,'tag_name':'v0.9.0','assets':[{'name':'OLD-MAC-UNCHANGED'}]}
    def pages(self,path,key=None):
        if path==publish.BASE+'releases':return [self.historical]+([self.release] if self.release else [])
        if path.endswith('/assets'):return list(self.assets.values())
        raise AssertionError('Unexpected listing')
    def request(self,method,path,**kwargs):
        if path==publish.BASE+'git/ref/tags/'+publish.TAG:
            return {'object':{'type':'commit','sha':self.tag}} if self.tag else None
        if method=='POST' and path==publish.BASE+'releases':
            self.mutations.append((method,path));self.release={**kwargs['payload'],'id':99,
                'html_url':'https://github.com/myflww/love-house/releases/tag/'+publish.TAG}
            return deepcopy(self.release)
        if method=='POST' and '/assets?name=' in path:
            name=path.split('name=')[1];raw=kwargs['content'];self.mutations.append((method,name))
            self.assets[name]={'id':len(self.assets)+100,'name':name,'size':len(raw),'state':'uploaded',
                'digest':'sha256:'+publish.identity(raw)['sha256'],'raw':raw}
            return self.assets[name]
        if method=='PATCH':
            self.mutations.append((method,path));self.release.update(kwargs['payload']);self.tag=PUBLICATION
            return deepcopy(self.release)
        if method=='GET' and '/releases/assets/' in path:
            return next(item['raw'] for item in self.assets.values() if str(item['id'])==path.rsplit('/',1)[1])
        raise AssertionError('Unexpected mutation or request')


class WindowsPublicationTests(unittest.TestCase):
    def test_metadata_requires_exact_frozen_source_and_all_three_workflows(self):
        placeholder=json.loads((publish.ROOT/'scripts/windows-091-publication.json').read_text('utf-8'))
        if placeholder.get('ready') is not True:
            with self.assertRaises(ValueError):publish.validate_metadata(placeholder)
        good=metadata();self.assertEqual(publish.validate_metadata(good),good)
        for field,value in [('ready',False),('source_commit','0'*40),('source_commit','PENDING'),('password','SYNTHETIC')]:
            with self.subTest(field=field),self.assertRaises(ValueError):publish.validate_metadata({**good,field:value})
        for mutation in (lambda x:x['source_runs'].pop('connection'),lambda x:x['source_runs'].update(windows=True),
                lambda x:x['source_runs'].update(connection=x['source_runs']['windows']),
                lambda x:x['windows_files'].update({'PRIVATE.key':publish.identity(b'SYNTHETIC')}),
                lambda x:x['windows_artifact'].update(name='android-unsigned-api-28'),
                lambda x:x['astrbot_package'].update(sha256='PENDING'),
                lambda x:x['doc_assets']['WINDOWS-091-FIXES.md'].update(path='../private.md')):
            bad=deepcopy(good);mutation(bad)
            with self.assertRaises(ValueError):publish.validate_metadata(bad)

    def test_post_freeze_changes_are_exact_not_directory_or_workflow_wildcards(self):
        good=metadata()
        for path in publish.POST_FREEZE_FILES:
            with patch.object(publish,'git',side_effect=[PUBLICATION,'',path,'']):publish.verify_source(Path('.'),good,PUBLICATION)
        for path in ('nkb/service/host.py','desktop/windows_app.py','scripts/build_windows.py','scripts/publish_workbuddy_080rc2.py',
                '.github/workflows/other.yml','docs/private.md','android/app/build.gradle','LICENSE'):
            with patch.object(publish,'git',side_effect=[PUBLICATION,'',path]),self.assertRaises(ValueError):
                publish.verify_source(Path('.'),good,PUBLICATION)
        with patch.object(publish,'git',side_effect=[PUBLICATION,'','',' M desktop/windows_app.py']),self.assertRaises(ValueError):
            publish.verify_source(Path('.'),good,PUBLICATION)

    def test_workflow_must_have_exact_source_and_every_required_job(self):
        for workflow,jobs in publish.SOURCE_RUNS.values():
            client=Mock();client.request.return_value={'head_sha':SOURCE,'status':'completed','conclusion':'success',
                'path':'.github/workflows/'+workflow,'repository':{'full_name':publish.REPOSITORY}}
            client.pages.return_value=[{'name':name,'status':'completed','conclusion':'success'} for name in jobs]
            publish.validate_run(client,1,SOURCE,workflow,jobs)
            client.request.return_value['head_sha']='4'*40
            with self.assertRaises(ValueError):publish.validate_run(client,1,SOURCE,workflow,jobs)
            client.request.return_value['head_sha']=SOURCE
            client.pages.return_value[0]['conclusion']='skipped'
            with self.assertRaises(ValueError):publish.validate_run(client,1,SOURCE,workflow,jobs)

    def test_artifact_pin_checks_run_head_digest_size_and_original_bytes(self):
        raw=b'SYNTHETIC ZIP';entry={'id':101,'name':'love-house-windows-x64',**publish.identity(raw)}
        info={'name':entry['name'],'digest':'sha256:'+entry['sha256'],'expired':False,'workflow_run':{'id':1,'head_sha':SOURCE}}
        client=Mock();client.request.side_effect=[info,raw]
        self.assertEqual(publish.download_artifact(client,entry,1,SOURCE),raw)
        for field,value in [('expired',True),('digest','sha256:'+'0'*64),('workflow_run',{'id':2,'head_sha':SOURCE}),
                ('workflow_run',{'id':1,'head_sha':'4'*40})]:
            client.request.side_effect=None;client.request.return_value={**info,field:value}
            with self.assertRaises(ValueError):publish.download_artifact(client,entry,1,SOURCE)
        client.request.side_effect=[info,raw+b'bad']
        with self.assertRaises(ValueError):publish.download_artifact(client,entry,1,SOURCE)

    def test_reports_require_finalized_native_exports_and_real_organizer_roundtrip(self):
        good=reports();self.assertEqual(set(publish.checked_windows_reports(report_zip(good),'3'*64)),publish.REPORTS)
        for name in publish.REPORTS:
            for field,value in [('ok',1),('process_complete',False),('version','0.8.0rc2'),('phase','window_ready'),
                    ('cleanup',{'status':'failed','isolated':True})]:
                bad=deepcopy(good);bad[name][field]=value
                with self.subTest(name=name,field=field),self.assertRaises(ValueError):publish.checked_windows_reports(report_zip(bad),'3'*64)
            bad=deepcopy(good)
            if name in publish.BACKEND_REPORTS:bad[name]['organizer']['fake_api_calls']=True
            else:bad[name]['native_exports']['json_original_roles']='failed'
            with self.assertRaises(ValueError):publish.checked_windows_reports(report_zip(bad),'3'*64)
        with self.assertRaises(ValueError):publish.checked_windows_reports(report_zip({k:v for k,v in good.items() if k!='installed-native.json'}),'3'*64)
        with self.assertRaises(ValueError):publish.checked_windows_reports(report_zip(good),'4'*64)

    def test_deferred_cleanup_accepts_only_known_completed_owned_profile_lock(self):
        value={'status':'deferred_profile_lock','isolated':True,'winerror':32,'attempts':8,
            'directory':'love-house-webview2-smoke-SYNTHETIC','retained_for':'OS release of the completed test WebView2 profile'}
        publish.checked_cleanup(value)
        for field,change in [('winerror',145),('isolated',False),('directory','../private'),('retained_for','pending process'),('attempts',True)]:
            with self.assertRaises(ValueError):publish.checked_cleanup({**value,field:change})

    def test_portable_payload_matches_source_plugin_and_shared_integrity_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'extensions/astrbot-love-house';source.mkdir(parents=True)
            sdk=root/'nkb/service/source_client.py';sdk.parent.mkdir(parents=True);sdk.write_bytes(b'SYNTHETIC SDK')
            members={'LoveHouse/LoveHouse.exe':b'MZ SYNTHETIC','LoveHouse/bridge/LoveHouseBridge.exe':b'MZ SYNTHETIC bridge'}
            for name in (*publish.PLUGIN_FILES,'package.py'):
                raw=b'SYNTHETIC SDK' if name=='source_client.py' else ('SYNTHETIC '+name).encode()
                (source/name).write_bytes(raw);members['LoveHouse/_internal/extensions/astrbot-love-house/'+name]=raw
            members['LoveHouse/_internal/nkb/service/source_client.py']=sdk.read_bytes()
            def outer(members,manifest=None):
                files={publish.EXE:b'MZ SYNTHETIC setup',publish.PORTABLE:archive(members)}
                files[publish.CHECKSUMS]=(manifest if manifest is not None else ''.join(publish.identity(raw)['sha256']+'  '+name+'\n' for name,raw in files.items())).encode()
                meta={'windows_files':{name:publish.identity(raw) for name,raw in files.items()}}
                return archive(files),meta
            raw,meta=outer(members);self.assertEqual(set(publish.checked_windows_files(raw,meta,root)),set(meta['windows_files']))
            bad={**members,'LoveHouse/_internal/nkb/service/source_client.py':b'UNTESTED SDK'};raw,meta=outer(bad)
            with self.assertRaises(ValueError):publish.checked_windows_files(raw,meta,root)
            raw,meta=outer(members,'0'*64+'  '+publish.EXE+'\n'+'0'*64+'  '+publish.PORTABLE+'\n')
            with self.assertRaises(ValueError):publish.checked_windows_files(raw,meta,root)

    def test_frozen_astrbot_zip_is_exactly_eight_sources_and_shared_sdk(self):
        raw=publish.frozen_plugin(ROOT)
        self.assertEqual(raw,publish.frozen_plugin(ROOT))
        with publish.safe_zip(raw) as package:
            self.assertEqual(len(package.namelist()),8)
            self.assertEqual(package.read('astrbot_plugin_love_house/source_client.py'),(ROOT/'nkb/service/source_client.py').read_bytes())

    def test_draft_first_idempotent_resumption_does_not_modify_mac_or_old_windows(self):
        client=FakePublisher();old=deepcopy(client.historical)
        assets={name:('SYNTHETIC '+name).encode() for name in publish.PUBLIC_NAMES}
        publish.publish(client,PUBLICATION,assets,'Reviewed synthetic notes')
        self.assertEqual(client.historical,old);self.assertEqual(len(client.assets),8)
        self.assertEqual(client.mutations[0],('POST',publish.BASE+'releases'))
        mutations=deepcopy(client.mutations);publish.publish(client,PUBLICATION,assets,'Reviewed synthetic notes')
        self.assertEqual(client.mutations,mutations)

    def test_existing_mismatch_or_extra_asset_never_overwrites_or_mutates(self):
        assets={name:b'SYNTHETIC reviewed bytes' for name in publish.PUBLIC_NAMES}
        for corrupt in ('target','asset','extra','notes','actual_bytes'):
            client=FakePublisher();publish.publish(client,PUBLICATION,assets,'Reviewed notes');client.release['draft']=True
            if corrupt=='target':client.tag='4'*40
            if corrupt=='asset':next(iter(client.assets.values()))['digest']='sha256:'+'0'*64
            if corrupt=='extra':client.assets['private.key']={'name':'private.key'}
            if corrupt=='notes':client.release['body']='Unexpected existing text'
            if corrupt=='actual_bytes':next(iter(client.assets.values()))['raw']=b'SAME-DIGEST-CLAIM-IS-NOT-ENOUGH'
            before=deepcopy(client.mutations)
            with self.subTest(corrupt=corrupt),self.assertRaises(ValueError):publish.publish(client,PUBLICATION,assets,'Reviewed notes')
            self.assertEqual(client.mutations,before)
        for forbidden in ('Developer.apk','LoveHouse-Android.apk','private.key'):
            with self.assertRaises(ValueError):publish.publish(FakePublisher(),PUBLICATION,{**assets,forbidden:b'SYNTHETIC'},'Notes')

    def test_no_release_mutation_when_source_evidence_collection_fails(self):
        with (patch.dict(os.environ,{'GITHUB_REPOSITORY':publish.REPOSITORY,'GITHUB_REF':'refs/heads/'+publish.BRANCH,'GITHUB_SHA':PUBLICATION}),
              patch.object(publish,'validate_metadata',return_value=metadata()),patch.object(publish,'verify_source'),
              patch.object(publish,'GitHub'),patch.object(publish,'collect_assets',side_effect=publish.PublicationError('Synthetic invalid report')),
              patch.object(publish,'publish') as upload):
            self.assertEqual(publish.main(),1);upload.assert_not_called()

    def test_anonymous_verification_has_no_token_and_requires_every_asset_exact(self):
        assets={name:b'SYNTHETIC' for name in publish.PUBLIC_NAMES}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,maximum):return b'SYNTHETIC'
        requests=[]
        class Opener:
            def open(self,request,**kwargs):requests.append(request);return Response()
        with patch.object(publish.urllib.request,'build_opener',return_value=Opener()):publish.anonymous_downloads(assets)
        self.assertEqual(len(requests),8);self.assertTrue(all(not r.has_header('Authorization') for r in requests))
        self.assertTrue(all('/releases/download/'+publish.TAG+'/' in r.full_url for r in requests))
        with patch.object(publish.urllib.request,'build_opener',return_value=Opener()),self.assertRaises(ValueError):
            publish.anonymous_downloads({publish.EXE:b'UNTESTED'})

    def test_json_evidence_refuses_duplicate_or_nonfinite_fields(self):
        for raw in (b'{"ok":true,"ok":false}',b'{"ok":NaN}',b'{"ok":Infinity}'):
            with self.assertRaises(ValueError):publish.checked_json(raw)


if __name__=='__main__':unittest.main()
