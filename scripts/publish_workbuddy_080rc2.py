#!/usr/bin/env python3
"""Publish frozen, independently tested 0.8.0rc2 bytes without replacing releases.

The metadata is deliberately disabled until exact completed-run/artifact hashes
are filled. No private signing keys, passwords, chats or developer APKs publish.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import verify_signed_080rc2 as verify

ROOT=Path(__file__).resolve().parents[1]
REPOSITORY='myflww/love-house'
BASE='/repos/'+REPOSITORY+'/'
TAG='v0.8.0rc2'
BRANCH='codex/workbuddy-publish-080rc2'
TITLE='爱之屋 0.8.0rc2 · WorkBuddy 连接修复与移动端更新'
SCHEMA='love-house-workbuddy-080rc2-publication/v1'
APK='LoveHouse-0.8.0rc2-Android.apk'
EXE='LoveHouse-Setup-0.8.0rc2-Windows-x64.exe'
PORTABLE='LoveHouse-0.8.0rc2-Windows-x64.zip'
CHECKSUMS='Windows-SHA256SUMS.txt'
PROOF='WorkBuddy-080rc2-verification.json'
DOCS={'WORKBUDDY-CONNECTION.md':'docs/WORKBUDDY-CONNECTION.md',
      'MACOS-080RC2-WORKBUDDY-HANDOFF.md':'docs/MACOS-080RC2-WORKBUDDY-HANDOFF.md'}
NOTES='docs/RELEASE-080RC2.md'
PUBLIC_NAMES={APK,EXE,PORTABLE,CHECKSUMS,PROOF,*DOCS,'ReleaseNotes-0.8.0rc2.md','SHA256SUMS.txt'}
SOURCE_RUNS={
    'windows':('release.yml',{'windows'}),
    'android':('android.yml',{'android (28)','android (36)'}),
    'android_remote':('android-remote-gateway.yml',{'real-webview (28)','real-webview (36)'}),
    'ios':('ios-portal.yml',{'ios'}),
    'regression':('ci.yml',{'test (py3.11)','test (py3.12)','test (py3.13)'}),
}
POST_FREEZE_FILES={
    'scripts/publish_workbuddy_080rc2.py','scripts/workbuddy-080rc2-publication.json',
    'tests/test_publish_workbuddy_080rc2.py',
    'scripts/verify_signed_080rc2.py','scripts/android-080rc2-signing-candidate.json',
    'tests/test_verify_signed_080rc2.py','PUBLIC_SOURCE_MANIFEST.json',
    NOTES,*DOCS.values(),
}
HEX40=re.compile('[0-9a-f]{40}')
HEX64=re.compile('[0-9a-f]{64}')


class PublicationError(ValueError):
    """Controlled diagnostics, never remote response bodies or credentials."""


def require(condition,message):
    if not condition:raise PublicationError(message)


def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def checked_bytes(raw,entry):
    require(identity(raw)=={k:entry[k] for k in ('bytes','sha256')},'Artifact bytes differ from pinned publication metadata')


def entry_valid(entry,*,artifact=False,maximum=800*1024*1024,extra=()):
    require(isinstance(entry,dict) and type(entry.get('bytes')) is int and 0<entry['bytes']<=maximum
            and bool(HEX64.fullmatch(str(entry.get('sha256','')))),'Artifact hash/size metadata is incomplete')
    require(set(entry)=={'bytes','sha256',*extra,*({'id','name'} if artifact else set())},'Artifact metadata contains unreviewed fields')
    if artifact:
        require(type(entry.get('id')) is int and entry['id']>0 and isinstance(entry.get('name'),str)
                and bool(re.fullmatch('[A-Za-z0-9_.-]{1,100}',entry['name'])),'Artifact identity metadata is incomplete')


def validate_metadata(value):
    require(isinstance(value,dict) and value.get('schema')==SCHEMA and value.get('ready') is True,
            'Publication metadata is not enabled and complete')
    require(set(value)=={'schema','ready','source_commit','signed_head','source_runs','signed_run','windows_artifact',
        'windows_evidence_artifact','android_build_artifact','windows_files','signed_artifacts','notes_path','release_notes','doc_assets'},
        'Publication metadata contains unreviewed fields')
    for key in ('source_commit','signed_head'):
        require(bool(HEX40.fullmatch(str(value.get(key,'')))) and value[key]!='0'*40,'Frozen source or signing head is missing')
    require(isinstance(value.get('source_runs'),dict) and set(value['source_runs'])==set(SOURCE_RUNS),'The full source CI set is required')
    for run in [*value['source_runs'].values(),value.get('signed_run')]:
        require(type(run) is int and run>0,'Completed CI run IDs are required')
    for key in ('windows_artifact','windows_evidence_artifact','android_build_artifact'):
        entry_valid(value.get(key),artifact=True)
    require(value['windows_artifact']['name']=='love-house-windows-x64'
            and value['windows_evidence_artifact']['name']=='windows-test-evidence'
            and value['android_build_artifact']['name'] in ('android-unsigned-api-28','android-unsigned-api-36'),
            'Unexpected source-build artifact names')
    require(isinstance(value.get('windows_files'),dict) and set(value['windows_files'])=={EXE,PORTABLE,CHECKSUMS},'Exactly three original Windows build files are required')
    for entry in value['windows_files'].values():entry_valid(entry)
    signed=value.get('signed_artifacts')
    require(isinstance(signed,list) and len(signed)==4,'All four signed upgrade emulator artifacts are required')
    seen=set()
    for entry in signed:
        entry_valid(entry,artifact=True,maximum=30*1024*1024,extra=('api_level','from_version_code'))
        pair=(entry.get('api_level'),entry.get('from_version_code'))
        require(type(pair[0]) is int and type(pair[1]) is int and pair[0] in (28,36) and pair[1] in (1,2)
                and pair not in seen,'Signed upgrade matrix has a duplicate or unknown cell')
        require(entry['name']==f'original-signed-080rc2-api-{pair[0]}-from-{pair[1]}','Signed artifact name differs from its matrix cell')
        seen.add(pair)
    require(value.get('notes_path')==NOTES and isinstance(value.get('doc_assets'),dict)
            and set(value['doc_assets'])==set(DOCS),'Only the reviewed release and platform instructions may publish')
    for name,path in DOCS.items():
        entry=value['doc_assets'][name];entry_valid(entry,maximum=1024*1024,extra=('path',))
        require(entry.get('path')==path,'A platform document path differs from the reviewed allowlist')
    entry_valid(value.get('release_notes'),maximum=1024*1024)
    return value


def git(root,*args):
    try:return subprocess.check_output(['git','-C',str(root),*args],text=True,encoding='utf-8',stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.SubprocessError):raise PublicationError('Frozen repository snapshot could not be verified') from None


def verify_source(root,metadata,publication):
    require(bool(HEX40.fullmatch(publication)),'Publication commit identity is missing')
    require(git(root,'rev-parse','HEAD')==publication,'Checkout differs from the publishing commit')
    for source in (metadata['source_commit'],metadata['signed_head']):
        git(root,'merge-base','--is-ancestor',source,publication)
    changed=git(root,'diff','--name-only',metadata['source_commit'],publication).splitlines()
    for name in changed:
        # CI-only QA/workflow differences support a publisher fork from main's
        # workflow tree when GitHub's token cannot create a new workflow tag.
        allowed=(name in POST_FREEZE_FILES or name.startswith('android/upgrade-qa/')
                 or bool(re.fullmatch(r'\.github/workflows/[A-Za-z0-9_.-]+\.yml',name)))
        require(allowed,'Production files changed after the frozen tested source')
    require(not git(root,'status','--porcelain','--untracked-files=no'),'Publishing checkout has tracked modifications')


def safe_zip(raw,*,maximum_total=900*1024*1024):
    try:
        archive=zipfile.ZipFile(io.BytesIO(raw))
        names=set();total=0
        for item in archive.infolist():
            name=item.filename
            require(name not in names and '\\' not in name and '\x00' not in name and not name.startswith('/')
                    and all(part not in ('','..','.') for part in name.rstrip('/').split('/'))
                    and not re.match('[A-Za-z]:',name),'Artifact ZIP paths are unsafe or duplicated')
            require((item.external_attr>>16)&0o170000!=0o120000,'Artifact ZIP contains a symlink')
            require(not item.flag_bits&1,'Encrypted artifacts are not accepted')
            total+=item.file_size;names.add(name)
            require(total<=maximum_total,'Artifact ZIP exceeds the reviewed uncompressed budget')
        require(archive.testzip() is None,'Artifact ZIP CRC failed')
        return archive
    except (zipfile.BadZipFile,RuntimeError):raise PublicationError('Artifact is not a valid bounded ZIP') from None


def unsigned_payload(raw):
    with safe_zip(raw,maximum_total=120*1024*1024) as archive:
        result={name:archive.read(name) for name in archive.namelist()
                if not name.endswith('/') and not re.fullmatch(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))',name,re.I)}
    require('AndroidManifest.xml' in result and 'classes.dex' in result,'Expected compiled Android payload is missing')
    return result


def checked_report(candidate,report,api,old,transcript,seed,upgraded,screenshot):
    require(report.get('schema')=='love-house-android-080rc2-verification/v1'
            and report.get('candidate')==candidate and report.get('signature_and_metadata')=='passed'
            and report.get('api_level')==api and report.get('from_version_code')==old,
            'Signed evidence does not identify the fixed APK and upgrade matrix')
    identities=report.get('identities',{})
    require(identities.get('apk')=={'package':verify.APP_ID,'version_code':'3','version_name':'0.8.0rc2','min_sdk':['26'],'target_sdk':['36']},
            'Signed application package/version differs from this release')
    harness=identities.get('test_apk',{})
    require(harness.get('package')==verify.APP_ID+'.test' and harness.get('runner')=='androidx.test.runner.AndroidJUnitRunner'
            and harness.get('target_package')==verify.APP_ID,'Signed instrumentation targets another package')
    counts=verify.parse_instrumentation(transcript)
    require(counts=={'tests':6,'failures':0,'errors':0,'skipped':0} and report.get('instrumentation')==counts,
            'Every signed emulator cell must pass all six tests without skips')
    verify.parse_probe(seed,'seed',old,api);verify.parse_probe(upgraded,'verify',old,api)
    upgrade={'passed':True,'from_version_code':old,'to_version_code':3,
             'seed_probe_sha256':hashlib.sha256(seed.encode()).hexdigest(),
             'verify_probe_sha256':hashlib.sha256(upgraded.encode()).hexdigest()}
    require(report.get('upgrade_preservation')==upgrade and report.get('instrument_sha256')==hashlib.sha256(transcript.encode()).hexdigest(),
            'Upgrade-preservation report differs from actual probe transcripts')
    verify.valid_png(screenshot)
    return {'api_level':api,'from_version_code':old,'instrumentation':counts,'upgrade_preservation':upgrade,
            'instrumentation_sha256':hashlib.sha256(transcript.encode()).hexdigest(),
            'screenshot_sha256':hashlib.sha256(screenshot).hexdigest()}


class StorageRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        parsed=urllib.parse.urlsplit(newurl)
        allowed=parsed.hostname in {'release-assets.githubusercontent.com','github-releases.githubusercontent.com'} or bool(
            re.fullmatch(r'productionresults[a-z0-9-]*\.blob\.core\.windows\.net',parsed.hostname or ''))
        require(req.get_method()=='GET' and parsed.scheme=='https' and allowed and not parsed.username and not parsed.password,
                'Unexpected GitHub asset redirect')
        return urllib.request.Request(newurl,headers={'User-Agent':'LoveHouse-080rc2-Publisher'})


class GitHub:
    def __init__(self,token):
        require(bool(token),'Repository publication token is unavailable')
        self.token=token;self.opener=urllib.request.build_opener(StorageRedirect())
    def request(self,method,path,*,payload=None,content=None,upload=False,binary=False,expected_bytes=0,missing=False):
        require(path.startswith(BASE) and method in ('GET','POST','PATCH'),'Publication request is outside the fixed repository')
        if method=='PATCH':require(bool(re.fullmatch(re.escape(BASE)+r'releases/[0-9]+',path)),'Only this release metadata may update')
        headers={'Authorization':'Bearer '+self.token,'User-Agent':'LoveHouse-080rc2-Publisher','X-GitHub-Api-Version':'2026-03-10',
                 'Accept':('application/vnd.github.raw+json' if '/git/blobs/' in path else 'application/octet-stream') if binary else 'application/vnd.github+json'}
        if payload is not None:content=json.dumps(payload,ensure_ascii=False).encode();headers['Content-Type']='application/json'
        elif content is not None:headers['Content-Type']='application/octet-stream'
        url=('https://uploads.github.com' if upload else 'https://api.github.com')+path
        try:
            with self.opener.open(urllib.request.Request(url,headers=headers,data=content,method=method),timeout=120) as response:
                raw=response.read(expected_bytes+1 if binary else 5*1024*1024)
        except urllib.error.HTTPError as exc:
            if missing and exc.code==404:return None
            raise PublicationError('GitHub rejected a verified publication operation (HTTP '+str(exc.code)+')') from None
        if binary:
            require(len(raw)==expected_bytes,'Downloaded byte count differs from pinned metadata');return raw
        try:return json.loads(raw)
        except ValueError:raise PublicationError('GitHub metadata response was not bounded valid JSON') from None
    def pages(self,path,key=None):
        items=[]
        for page in range(1,21):
            value=self.request('GET',path+('&' if '?' in path else '?')+'per_page=100&page='+str(page))
            batch=value[key] if key else value
            require(isinstance(batch,list),'GitHub paginated metadata is incomplete')
            items.extend(batch)
            if len(batch)<100:return items
        raise PublicationError('GitHub listing exceeded the reviewed pagination budget')


def validate_run(client,run_id,head,workflow,jobs):
    run=client.request('GET',BASE+'actions/runs/'+str(run_id))
    require(run.get('head_sha')==head and run.get('status')=='completed' and run.get('conclusion')=='success'
            and run.get('path')=='.github/workflows/'+workflow and run.get('repository',{}).get('full_name')==REPOSITORY,
            'Required CI did not complete successfully for the exact frozen head')
    found=client.pages(BASE+'actions/runs/'+str(run_id)+'/jobs',key='jobs')
    names=[j.get('name') for j in found]
    require(len(names)==len(set(names)) and jobs<=set(names),'Required CI matrix jobs are missing or duplicated')
    require(all(j.get('status')=='completed' and j.get('conclusion')=='success' for j in found if j.get('name') in jobs),
            'Required CI matrix contains a skipped or failed job')
    return {'id':run_id,'head_sha':head,'workflow':workflow,'url':'https://github.com/'+REPOSITORY+'/actions/runs/'+str(run_id)}


def download_artifact(client,entry,run_id,head):
    item=client.request('GET',BASE+'actions/artifacts/'+str(entry['id']))
    require(not item.get('expired') and item.get('name')==entry['name'] and item.get('digest')=='sha256:'+entry['sha256']
            and item.get('workflow_run',{}).get('id')==run_id and item.get('workflow_run',{}).get('head_sha')==head,
            'Artifact identity, digest, or exact CI head differs from reviewed metadata')
    raw=client.request('GET',BASE+'actions/artifacts/'+str(entry['id'])+'/zip',binary=True,expected_bytes=entry['bytes'])
    checked_bytes(raw,entry);return raw


def local_document(root,path,entry):
    source=root/path
    require(source.is_file() and not source.is_symlink() and source.resolve().is_relative_to(root.resolve()),'Public instruction is not an ordinary allowlisted file')
    raw=source.read_bytes();checked_bytes(raw,entry);raw.decode('utf-8');return raw


def input_build_provenance(client,root,source_commit,build_report):
    require(isinstance(build_report,dict) and build_report.get('schema')=='love-house-android-build/v1',
            'Original Android build verification metadata is missing')
    recorded=build_report.get('source_commit')
    require(isinstance(recorded,str) and bool(HEX40.fullmatch(recorded)) and recorded!='0'*40,
            'Original Android build commit identity is invalid')
    commit=client.request('GET',BASE+'git/commits/'+recorded)
    require(isinstance(commit,dict) and commit.get('sha')==recorded and isinstance(commit.get('tree'),dict),
            'Original Android build commit could not be verified in this repository')
    recorded_tree=commit['tree'].get('sha')
    frozen_tree=git(root,'rev-parse',source_commit+'^{tree}')
    require(isinstance(recorded_tree,str) and bool(HEX40.fullmatch(recorded_tree))
            and bool(HEX40.fullmatch(frozen_tree)) and recorded_tree==frozen_tree,
            'Original Android build commit tree differs from the frozen source tree')
    return {'input_build_commit':recorded,'input_build_tree':recorded_tree,'frozen_tree_match':True}


def collect_assets(client,root,metadata,publication):
    candidate=verify.validate_candidate(json.loads((root/'scripts/android-080rc2-signing-candidate.json').read_text('utf-8')))
    require(candidate['source_commit']==metadata['source_commit'],'Signed APK source differs from frozen desktop/mobile source')
    runs={key:validate_run(client,metadata['source_runs'][key],metadata['source_commit'],workflow,jobs)
          for key,(workflow,jobs) in SOURCE_RUNS.items()}
    signed_jobs={f'verify ({api}, {old})' for api in (28,36) for old in (1,2)}
    signed_run=validate_run(client,metadata['signed_run'],metadata['signed_head'],'android-original-signing-080rc2.yml',signed_jobs)
    assets={}
    raw=download_artifact(client,metadata['windows_artifact'],metadata['source_runs']['windows'],metadata['source_commit'])
    with safe_zip(raw) as archive:
        require(set(archive.namelist())=={EXE,PORTABLE,CHECKSUMS},'Windows build artifact contains unexpected release files')
        for name,entry in metadata['windows_files'].items():
            assets[name]=archive.read(name);checked_bytes(assets[name],entry)
    lines=assets[CHECKSUMS].decode('ascii').splitlines()
    parsed=[re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)',line) for line in lines]
    require(len(parsed)==2 and all(parsed),'Windows checksum manifest has invalid entries')
    checksums={match[2]:match[1] for match in parsed}
    require(checksums=={name:metadata['windows_files'][name]['sha256'] for name in (EXE,PORTABLE)},
            'Windows checksum manifest does not describe the original tested installers')
    raw=download_artifact(client,metadata['windows_evidence_artifact'],metadata['source_runs']['windows'],metadata['source_commit'])
    windows_reports={}
    with safe_zip(raw,maximum_total=100*1024*1024) as archive:
        for name in ('installed-backend.json','installed-native.json','portable-consumer.json','installed-consumer.json'):
            require(name in archive.namelist(),'Required actual Windows process evidence is missing')
            result=json.loads(archive.read(name))
            require(result.get('ok') is True and result.get('process_complete') is True,'Windows installed/native process did not finish successfully')
            windows_reports[name]=identity(archive.read(name))
    accepted=None;matrix=[]
    for entry in metadata['signed_artifacts']:
        raw=download_artifact(client,entry,metadata['signed_run'],metadata['signed_head'])
        with safe_zip(raw,maximum_total=50*1024*1024) as archive:
            require(set(archive.namelist())=={APK,'verification.json','upgrade-seed.txt','upgrade-verify.txt','instrumentation.txt','android-smoke.png'},
                    'Signed verification artifact has extra files or lacks required evidence')
            apk=archive.read(APK);verify.checked_bytes(apk,candidate['apk'])
            require(accepted is None or accepted==apk,'Signed emulator jobs tested different APK bytes');accepted=apk
            matrix.append(checked_report(candidate,json.loads(archive.read('verification.json')),entry['api_level'],entry['from_version_code'],
                archive.read('instrumentation.txt').decode('utf-8'),archive.read('upgrade-seed.txt').decode('utf-8'),
                archive.read('upgrade-verify.txt').decode('utf-8'),archive.read('android-smoke.png')))
    raw=download_artifact(client,metadata['android_build_artifact'],metadata['source_runs']['android'],metadata['source_commit'])
    with safe_zip(raw,maximum_total=100*1024*1024) as archive:
        name='LoveHouse-0.8.0rc2-Android-unsigned.apk'
        require(name in archive.namelist() and 'verification.json' in archive.namelist(),
                'Original source CI unsigned Android build or verification metadata is missing')
        unsigned=archive.read(name)
        input_build=input_build_provenance(client,root,metadata['source_commit'],json.loads(archive.read('verification.json')))
        require(unsigned_payload(unsigned)==unsigned_payload(accepted),'Final signed app payload differs from the tested source build')
    assets[APK]=accepted
    for name,path in DOCS.items():assets[name]=local_document(root,path,metadata['doc_assets'][name])
    notes=local_document(root,NOTES,metadata['release_notes']);assets['ReleaseNotes-0.8.0rc2.md']=notes
    proof={'schema':SCHEMA,'tag':TAG,'source_commit':metadata['source_commit'],'publication_commit':publication,
           'signed_head':metadata['signed_head'],'certificate_sha256':verify.CERT,'application_id':verify.APP_ID,
           'android_version_name':'0.8.0rc2','android_version_code':3,'source_runs':runs,'signed_run':signed_run,
           'signed_upgrade_matrix':sorted(matrix,key=lambda x:(x['api_level'],x['from_version_code'])),
           'windows_process_reports':windows_reports,'windows_evidence_artifact':metadata['windows_evidence_artifact'],
           'android_build_artifact':metadata['android_build_artifact'],'unsigned_android_apk':identity(unsigned),**input_build,
           'signed_android_apk':candidate['apk'],'physical_android_phone_tested':False,'physical_iphone_tested':False,
           'native_macos_release_built':False,'assets':{name:identity(raw) for name,raw in sorted(assets.items())}}
    assets[PROOF]=(json.dumps(proof,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
    assets['SHA256SUMS.txt']=''.join(hashlib.sha256(raw).hexdigest()+'  '+name+'\n' for name,raw in sorted(assets.items())).encode('ascii')
    return assets,notes.decode('utf-8')


def tag_commit(client):
    value=client.request('GET',BASE+'git/ref/tags/'+TAG,missing=True)
    if value is None:return None
    obj=value['object']
    for _ in range(6):
        require(bool(HEX40.fullmatch(str(obj.get('sha','')))),'Release tag identity is invalid')
        if obj.get('type')=='commit':return obj['sha']
        require(obj.get('type')=='tag','Release tag does not resolve to a commit')
        obj=client.request('GET',BASE+'git/tags/'+obj['sha'])['object']
    raise PublicationError('Release tag nesting exceeds the reviewed budget')


def checked_asset_map(entries,assets):
    by_name={item['name']:item for item in entries}
    require(len(by_name)==len(entries) and not set(by_name)-set(assets),'Existing release contains unexpected or duplicate asset names')
    for name,item in by_name.items():
        expected=identity(assets[name])
        require(item.get('size')==expected['bytes'] and item.get('digest')=='sha256:'+expected['sha256']
                and item.get('state')=='uploaded','Existing release bytes differ; assets will not be overwritten')
    return by_name


def publish(client,publication,assets,notes):
    require(set(assets)==PUBLIC_NAMES,'Only the reviewed nine public release files may be uploaded')
    existing_tag=tag_commit(client)
    require(existing_tag in (None,publication),'Existing tag targets another commit and will not be moved')
    matches=[item for item in client.pages(BASE+'releases') if item.get('tag_name')==TAG]
    require(len(matches)<=1,'Duplicate drafts exist for this release tag')
    release=matches[0] if matches else client.request('POST',BASE+'releases',payload={
        'tag_name':TAG,'target_commitish':publication,'name':TITLE,'body':notes,'draft':True,'prerelease':True,'make_latest':'false'})
    require(release.get('tag_name')==TAG and release.get('target_commitish')==publication and release.get('prerelease') is True
            and release.get('name')==TITLE and release.get('body')==notes and type(release.get('id')) is int,
            'Existing release identity/text differs from this reviewed publication')
    path=BASE+'releases/'+str(release['id'])
    existing=checked_asset_map(client.pages(path+'/assets'),assets)
    require(release.get('draft') or set(existing)==set(assets),'Public release is incomplete and will not be mutated')
    # Validate every collision before any mutation, then append missing draft files.
    for name,raw in sorted(assets.items()):
        if name in existing:
            old=client.request('GET',BASE+'releases/assets/'+str(existing[name]['id']),binary=True,expected_bytes=len(raw))
            require(old==raw,'Existing matching-name asset bytes differ from the verified files')
        else:
            require(release.get('draft') is True,'Public release assets cannot be appended or replaced')
            client.request('POST',path+'/assets?name='+urllib.parse.quote(name,safe=''),content=raw,upload=True)
    final_assets=checked_asset_map(client.pages(path+'/assets'),assets)
    require(set(final_assets)==set(assets),'Uploaded release asset set is incomplete')
    if release.get('draft'):
        release=client.request('PATCH',path,payload={'draft':False,'prerelease':True,'make_latest':'false'})
    require(release.get('draft') is False and release.get('prerelease') is True and tag_commit(client)==publication,
            'Final public prerelease does not point to the verified publication commit')
    return release


def anonymous_downloads(assets):
    opener=urllib.request.build_opener(StorageRedirect())
    for name,expected in sorted(assets.items()):
        request=urllib.request.Request('https://github.com/'+REPOSITORY+'/releases/download/'+TAG+'/'+urllib.parse.quote(name),
                                       headers={'User-Agent':'LoveHouse-080rc2-Anonymous-Verification'})
        with opener.open(request,timeout=120) as response:raw=response.read(len(expected)+1)
        require(raw==expected,'Anonymous public release download differs from the tested files')


def main():
    try:
        require(os.environ.get('GITHUB_REPOSITORY')==REPOSITORY and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,
                'Publication is restricted to the reviewed repository branch')
        metadata=validate_metadata(json.loads((ROOT/'scripts/workbuddy-080rc2-publication.json').read_text('utf-8')))
        publication=os.environ.get('GITHUB_SHA','');verify_source(ROOT,metadata,publication)
        client=GitHub(os.environ.get('GH_TOKEN',''))
        assets,notes=collect_assets(client,ROOT,metadata,publication)
        release=publish(client,publication,assets,notes)
        anonymous_downloads(assets)
        print(json.dumps({'ok':True,'url':release['html_url'],'anonymous_verified_assets':len(assets)}))
        return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
        message=str(exc) if isinstance(exc,(PublicationError,verify.VerificationError)) else 'Publication verification could not complete'
        print(json.dumps({'ok':False,'error':message}));return 1


if __name__=='__main__':raise SystemExit(main())
