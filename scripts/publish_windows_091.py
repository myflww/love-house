#!/usr/bin/env python3
"""Append a Windows 0.9.1rc1 preview only after exact source/process evidence.

The frozen build is downloaded and checked before a draft is created. Existing
tags/assets are never moved or replaced. No Android or macOS assets are changed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import publish_workbuddy_080rc2 as common

ROOT=Path(__file__).resolve().parents[1]
REPOSITORY=common.REPOSITORY
BASE=common.BASE
TAG='v0.9.1rc1'
VERSION='0.9.1rc1'
BRANCH='codex/windows-091-publish'
TITLE='爱之屋 0.9.1rc1 · Windows 分享导出与记忆整理修复'
SCHEMA='love-house-windows-091-publication/v1'
EXE='LoveHouse-Setup-0.9.1rc1-Windows-x64.exe'
PORTABLE='LoveHouse-0.9.1rc1-Windows-x64.zip'
CHECKSUMS='Windows-SHA256SUMS.txt'
PLUGIN='LoveHouse-AstrBot-0.2.0-experimental.zip'
PROOF='Windows-091-verification.json'
NOTES='docs/ReleaseNotes-0.9.1rc1-Windows.md'
NOTES_ASSET='ReleaseNotes-0.9.1rc1-Windows.md'
DOCS={'WINDOWS-091-FIXES.md':'docs/WINDOWS-091-FIXES.md'}
PUBLIC_NAMES={EXE,PORTABLE,CHECKSUMS,PLUGIN,PROOF,NOTES_ASSET,'SHA256SUMS.txt',*DOCS}
SOURCE_RUNS={
    'windows':('release.yml',{'windows'}),
    'regression':('ci.yml',{'javascript','test (py3.11)','test (py3.12)','test (py3.13)'}),
    'connection':('cross-platform-connect.yml',{'real Harness CLI (ubuntu-latest)','real Harness CLI (macos-latest)'}),
}
POST_FREEZE_FILES={
    'scripts/publish_windows_091.py','scripts/windows-091-publication.json',
    'tests/test_publish_windows_091.py','.github/workflows/publish-windows-091.yml',
    'PUBLIC_SOURCE_MANIFEST.json','README.md',NOTES,*DOCS.values(),
}
PLUGIN_FILES=('__init__.py','main.py','bridge.py','source_client.py','metadata.yaml','_conf_schema.json','README.md','LICENSE')
REPORTS={'backend.json','native.json','installed-backend.json','installed-native.json',
         'portable-consumer.json','installed-consumer.json'}
BACKEND_REPORTS={'backend.json','installed-backend.json'}
NATIVE_EXPORT_CHECKS={'json_original_roles','markdown','cancel','write_error','organizer_independent_preview','foreign_origin','astrbot_zip'}
ORGANIZER_REPORT={'status':'passed','transport':'loopback-http','fake_api_calls':1,
    'source_evidence_preserved':True,'session_only_credential':True,'real_model_calls':0,
    'real_credentials_accessed':False,'cleanup':'removed'}
PublicationError=common.PublicationError
require=common.require
identity=common.identity
checked_bytes=common.checked_bytes
entry_valid=common.entry_valid
git=common.git
safe_zip=common.safe_zip
StorageRedirect=common.StorageRedirect
GitHub=common.GitHub
validate_run=common.validate_run
download_artifact=common.download_artifact
local_document=common.local_document
HEX40=common.HEX40
HEX64=common.HEX64


def checked_json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'Evidence JSON contains duplicate fields')
            result[key]=value
        return result
    def constant(value):raise PublicationError('Evidence JSON contains nonfinite values')
    return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique,parse_constant=constant)


def validate_metadata(value):
    require(isinstance(value,dict) and value.get('schema')==SCHEMA and value.get('ready') is True,
            'Publication metadata is not enabled and complete')
    require(set(value)=={'schema','ready','source_commit','source_runs','windows_artifact',
        'windows_evidence_artifact','windows_files','astrbot_package','notes_path','release_notes','doc_assets'},
        'Publication metadata contains unreviewed fields')
    require(bool(HEX40.fullmatch(str(value.get('source_commit','')))) and value['source_commit']!='0'*40,
            'The exact tested production source is missing')
    require(isinstance(value.get('source_runs'),dict) and set(value['source_runs'])==set(SOURCE_RUNS),
            'All three source CI workflows are required')
    require(all(type(run) is int and run>0 for run in value['source_runs'].values()),
            'Completed source CI run IDs are required')
    require(len(set(value['source_runs'].values()))==len(SOURCE_RUNS),'Different required workflows must identify different runs')
    for field,name in [('windows_artifact','love-house-windows-x64'),('windows_evidence_artifact','windows-test-evidence')]:
        entry_valid(value.get(field),artifact=True)
        require(value[field]['name']==name,'Unexpected Windows build/evidence artifact name')
    require(isinstance(value.get('windows_files'),dict) and set(value['windows_files'])=={EXE,PORTABLE,CHECKSUMS},
            'Exactly the tested installer, portable ZIP and Windows checksum file are required')
    for entry in value['windows_files'].values():entry_valid(entry)
    entry_valid(value.get('astrbot_package'),maximum=4*1024*1024)
    require(value.get('notes_path')==NOTES and isinstance(value.get('doc_assets'),dict) and set(value['doc_assets'])==set(DOCS),
            'Only reviewed release and Windows fix instructions may publish')
    entry_valid(value.get('release_notes'),maximum=1024*1024)
    for name,path in DOCS.items():
        entry_valid(value['doc_assets'][name],maximum=1024*1024,extra=('path',))
        require(value['doc_assets'][name]['path']==path,'Windows document path differs from the exact allowlist')
    return value


def verify_source(root,metadata,publication):
    require(bool(HEX40.fullmatch(publication)) and publication!='0'*40,'Publication commit identity is missing')
    require(git(root,'rev-parse','HEAD')==publication,'Checkout differs from the publishing commit')
    git(root,'merge-base','--is-ancestor',metadata['source_commit'],publication)
    for name in git(root,'diff','--name-only',metadata['source_commit'],publication).splitlines():
        require(name in POST_FREEZE_FILES,'Production files changed after the frozen tested source')
    require(not git(root,'status','--porcelain','--untracked-files=no'),'Publishing checkout has tracked modifications')


def frozen_plugin(root):
    """Build the same deterministic eight-source ZIP the installed app exports."""
    path=root/'extensions/astrbot-love-house/package.py'
    require(path.is_file() and not path.is_symlink(),'Frozen AstrBot packaging source is missing')
    spec=importlib.util.spec_from_file_location('love_house_windows_091_plugin_packager',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    require(tuple(module.FILES)==PLUGIN_FILES,'AstrBot package source allowlist has changed')
    payload=module.package_bytes(strict_sdk=True)
    with safe_zip(payload,maximum_total=4*1024*1024) as archive:
        require(set(archive.namelist())=={'astrbot_plugin_love_house/'+name for name in PLUGIN_FILES},
                'AstrBot ZIP contains unreviewed files')
        for name in PLUGIN_FILES:
            require(archive.read('astrbot_plugin_love_house/'+name)==(path.parent/name).read_bytes(),
                    'AstrBot archive differs from frozen plugin source')
        require(archive.read('astrbot_plugin_love_house/source_client.py')==(root/'nkb/service/source_client.py').read_bytes(),
                'AstrBot SDK differs from the frozen shared SDK')
    return payload


def checked_windows_files(raw,metadata,root):
    assets={}
    with safe_zip(raw) as archive:
        require(set(archive.namelist())=={EXE,PORTABLE,CHECKSUMS},'Windows build artifact contains unexpected release files')
        for name,entry in metadata['windows_files'].items():
            assets[name]=archive.read(name);checked_bytes(assets[name],entry)
    try:
        matches=[re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)',line) for line in assets[CHECKSUMS].decode('ascii').splitlines()]
    except UnicodeError:raise PublicationError('Windows checksum manifest is invalid') from None
    require(len(matches)==2 and all(matches),'Windows checksum manifest has invalid entries')
    require({m[2]:m[1] for m in matches}=={name:metadata['windows_files'][name]['sha256'] for name in (EXE,PORTABLE)},
            'Windows checksums differ from the exact tested installers')
    with safe_zip(assets[PORTABLE]) as archive:
        require('LoveHouse/LoveHouse.exe' in archive.namelist() and 'LoveHouse/bridge/LoveHouseBridge.exe' in archive.namelist(),
                'The portable ZIP does not contain a complete Windows application')
        prefix='LoveHouse/_internal/extensions/astrbot-love-house/'
        for name in (*PLUGIN_FILES,'package.py'):
            require(prefix+name in archive.namelist() and archive.read(prefix+name)==(root/'extensions/astrbot-love-house'/name).read_bytes(),
                    'Packaged Windows AstrBot source differs from the tested frozen source')
        sdk='LoveHouse/_internal/nkb/service/source_client.py'
        require(sdk in archive.namelist() and archive.read(sdk)==(root/'nkb/service/source_client.py').read_bytes(),
                'Packaged Windows AstrBot integrity input differs from the shared SDK')
    return assets


def checked_cleanup(value):
    require(isinstance(value,dict) and value.get('isolated') is True,'Windows smoke was not isolated')
    require(value.get('status') in ('removed','deferred_profile_lock'),'Windows smoke cleanup did not finish safely')
    if value['status']=='deferred_profile_lock':
        require(type(value.get('winerror')) is int and value['winerror'] in (32,33)
                and type(value.get('attempts')) is int and value['attempts']>0
                and isinstance(value.get('directory'),str) and value['directory'].startswith('love-house-webview2-smoke-')
                and not any(c in value['directory'] for c in ('/','\\'))
                and value.get('retained_for')=='OS release of the completed test WebView2 profile',
                'Deferred smoke cleanup does not identify an isolated completed WebView2 profile lock')


def checked_windows_reports(raw,plugin_sha):
    reports={}
    with safe_zip(raw,maximum_total=100*1024*1024) as archive:
        require(REPORTS<=set(archive.namelist()),'Required build and actual installed Windows process reports are missing')
        for name in sorted(REPORTS):
            report=checked_json(archive.read(name))
            require(isinstance(report,dict) and report.get('ok') is True and report.get('process_complete') is True
                    and report.get('version')==VERSION and report.get('phase')=='complete',
                    'Windows smoke did not finalize successfully for this product version')
            checked_cleanup(report.get('cleanup'))
            require(report.get('real_model_calls',0)==0 and report.get('real_credentials_accessed',False) is False,
                    'Process evidence used real models or credentials')
            if name in BACKEND_REPORTS:
                organizer=report.get('organizer')
                require(isinstance(organizer,dict) and set(organizer)==set(ORGANIZER_REPORT)
                        and all(type(organizer[k]) is type(v) and organizer[k]==v for k,v in ORGANIZER_REPORT.items()),
                        'Windows package did not complete the exact isolated organizer API roundtrip')
                require(report.get('sharing_roundtrip')=='passed' and report.get('restart')=='passed',
                        'Installed sharing or memory-preserving restart did not pass')
            else:
                exports=report.get('native_exports')
                require(isinstance(exports,dict) and all(exports.get(k)=='passed' for k in NATIVE_EXPORT_CHECKS)
                        and exports.get('dialog_selection')=='synthetic_owned_path' and exports.get('astrbot_sha256')==plugin_sha,
                        'Native JSON/Markdown export, cancel/error/origin, or exact AstrBot package verification did not pass')
                require(report.get('renderer')=='edgechromium' and report.get('controller_stopped') is True,
                        'Native WebView2 process did not shut down its controller')
            reports[name]={'file':identity(archive.read(name)),'checks':'passed','cleanup':report['cleanup']['status'],
                **({'organizer':ORGANIZER_REPORT} if name in BACKEND_REPORTS else {'native_exports':'passed','astrbot_sha256':plugin_sha})}
    return reports


def collect_assets(client,root,metadata,publication):
    runs={key:validate_run(client,metadata['source_runs'][key],metadata['source_commit'],workflow,jobs)
          for key,(workflow,jobs) in SOURCE_RUNS.items()}
    windows=download_artifact(client,metadata['windows_artifact'],metadata['source_runs']['windows'],metadata['source_commit'])
    evidence=download_artifact(client,metadata['windows_evidence_artifact'],metadata['source_runs']['windows'],metadata['source_commit'])
    assets=checked_windows_files(windows,metadata,root)
    plugin=frozen_plugin(root);checked_bytes(plugin,metadata['astrbot_package'])
    reports=checked_windows_reports(evidence,identity(plugin)['sha256']);assets[PLUGIN]=plugin
    for name,path in DOCS.items():assets[name]=local_document(root,path,metadata['doc_assets'][name])
    notes=local_document(root,NOTES,metadata['release_notes']);assets[NOTES_ASSET]=notes
    proof={'schema':SCHEMA,'tag':TAG,'source_commit':metadata['source_commit'],'publication_commit':publication,
        'source_runs':runs,'windows_build_artifact':metadata['windows_artifact'],
        'windows_evidence_artifact':metadata['windows_evidence_artifact'],'windows_process_reports':reports,
        'astrbot_plugin_version':'0.2.0','astrbot_source_files':list(PLUGIN_FILES),
        'native_macos_release_built':False,'android_release_built':False,'physical_windows_10_tested':False,
        'environment':'github_hosted_windows_runner','clean_consumer_machine_tested':False,
        'assets':{name:identity(raw) for name,raw in sorted(assets.items())}}
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


def publish(client,publication,assets,notes):
    require(set(assets)==PUBLIC_NAMES,'Only the eight reviewed Windows release files may be uploaded')
    require(tag_commit(client) in (None,publication),'Existing tag targets another commit and will not be moved')
    matches=[item for item in client.pages(BASE+'releases') if item.get('tag_name')==TAG]
    require(len(matches)<=1,'Duplicate drafts exist for this release tag')
    release=matches[0] if matches else client.request('POST',BASE+'releases',payload={
        'tag_name':TAG,'target_commitish':publication,'name':TITLE,'body':notes,'draft':True,'prerelease':True,'make_latest':'false'})
    require(release.get('tag_name')==TAG and release.get('target_commitish')==publication and release.get('prerelease') is True
            and release.get('name')==TITLE and release.get('body')==notes and type(release.get('id')) is int,
            'Existing release identity/text differs from the reviewed publication')
    path=BASE+'releases/'+str(release['id'])
    existing=common.checked_asset_map(client.pages(path+'/assets'),assets)
    require(release.get('draft') is True or set(existing)==set(assets),'Public release is incomplete and will not be mutated')
    # Review every collision before the first upload; never delete/replace one.
    for name,item in existing.items():
        actual=client.request('GET',BASE+'releases/assets/'+str(item['id']),binary=True,expected_bytes=len(assets[name]))
        require(actual==assets[name],'Existing matching-name asset bytes differ from the verified files')
    for name,raw in sorted(assets.items()):
        if name not in existing:
            require(release.get('draft') is True,'Public release assets cannot be appended or replaced')
            client.request('POST',path+'/assets?name='+urllib.parse.quote(name,safe=''),content=raw,upload=True)
    final=common.checked_asset_map(client.pages(path+'/assets'),assets)
    require(set(final)==set(assets),'Uploaded release asset set is incomplete')
    if release.get('draft') is True:
        release=client.request('PATCH',path,payload={'draft':False,'prerelease':True,'make_latest':'false'})
    require(release.get('draft') is False and release.get('prerelease') is True and tag_commit(client)==publication,
            'Final public prerelease does not point to the verified publication commit')
    return release


def anonymous_downloads(assets):
    opener=urllib.request.build_opener(StorageRedirect())
    for name,expected in sorted(assets.items()):
        req=urllib.request.Request('https://github.com/'+REPOSITORY+'/releases/download/'+TAG+'/'+urllib.parse.quote(name),
            headers={'User-Agent':'LoveHouse-091-Anonymous-Verification'})
        with opener.open(req,timeout=120) as response:actual=response.read(len(expected)+1)
        require(actual==expected,'Anonymous public release download differs from the tested files')


def main():
    try:
        require(os.environ.get('GITHUB_REPOSITORY')==REPOSITORY and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,
                'Publication is restricted to the reviewed repository branch')
        metadata=validate_metadata(checked_json((ROOT/'scripts/windows-091-publication.json').read_bytes()))
        publication=os.environ.get('GITHUB_SHA','');verify_source(ROOT,metadata,publication)
        client=GitHub(os.environ.get('GH_TOKEN',''))
        assets,notes=collect_assets(client,ROOT,metadata,publication)
        release=publish(client,publication,assets,notes);anonymous_downloads(assets)
        print(json.dumps({'ok':True,'url':release['html_url'],'anonymous_verified_assets':len(assets)}));return 0
    except (OSError,ValueError,KeyError,TypeError,AttributeError,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
        print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,PublicationError) else 'Publication verification could not complete'}));return 1


if __name__=='__main__':raise SystemExit(main())
