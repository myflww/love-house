"""Reject incomplete signatures, wrong upgrade paths and forged emulator evidence."""
from copy import deepcopy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_signed_080rc2 as verify

FIXTURE_SOURCE='1'*40


def entry(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def candidate():
    return {'schema':verify.SCHEMA,'source_commit':FIXTURE_SOURCE,'handoff_commit':FIXTURE_SOURCE,
            'application_id':verify.APP_ID,'version_name':'0.8.0rc2','version_code':3,
            'certificate_sha256':verify.CERT,'apk':entry(b'SYNTHETIC signed main'),'test_apk':entry(b'SYNTHETIC signed test')}


def probe(mode='seed',from_code=1,api=28):
    fields={'ok':'true','mode':mode,'protocol':'love-house-ui-upgrade/v1','target_package':verify.APP_ID,
            'from_version_code':str(from_code),'expected_version_code':str(from_code) if mode=='seed' else '3',
            'api_level':str(api),'same_original_certificate':'true','original_text_preserved':'true',
            'assistant_reply_preserved':'true','tags_preserved':'true'}
    return ''.join('INSTRUMENTATION_RESULT: '+key+'='+value+'\n' for key,value in fields.items())+'INSTRUMENTATION_CODE: -1\n'


class Signed080rc2Tests(unittest.TestCase):
    def setUp(self):
        self.source=patch.object(verify,'SOURCE',FIXTURE_SOURCE)
        self.production=patch.object(verify,'PRODUCTION_SOURCE',FIXTURE_SOURCE)
        self.source.start();self.production.start()
        self.addCleanup(self.source.stop);self.addCleanup(self.production.stop)

    def test_pinned_source_original_signer_and_release_identity(self):
        good=candidate()
        self.assertEqual(verify.validate_candidate(good),good)
        for key,value in [('schema','unknown'),('source_commit','2'*40),('handoff_commit','2'*40),
                          ('version_code',2),('version_code',True),('version_name','0.8.0rc1'),
                          ('certificate_sha256','2'*64),('application_id','another.app')]:
            bad=deepcopy(good);bad[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):verify.validate_candidate(bad)
        for size in (0,True,verify.MAX_APK+1):
            bad=deepcopy(good);bad['apk']['bytes']=size
            with self.assertRaises(ValueError):verify.validate_candidate(bad)
        for key in ('blob_sha','sha256'):
            bad=deepcopy(good);bad['apk'][key]='PENDING'
            with self.assertRaises(ValueError):verify.validate_candidate(bad)
        for key in ('token','private_key','password'):
            bad=deepcopy(good);bad[key]='SYNTHETIC'
            with self.assertRaises(ValueError):verify.validate_candidate(bad)
            bad=deepcopy(good);bad['apk'][key]='SYNTHETIC'
            with self.assertRaises(ValueError):verify.validate_candidate(bad)

    def test_unfilled_or_zero_source_and_same_app_test_fail_closed(self):
        for source in ('SOURCE_COMMIT_PENDING','0'*40):
            with patch.object(verify,'SOURCE',source),self.assertRaises(ValueError):verify.validate_candidate(candidate())
        value=candidate();value['test_apk']=value['apk']
        with self.assertRaises(ValueError):verify.validate_candidate(value)

    def test_source_freeze_checks_all_asset_build_inputs_and_local_modifications(self):
        with patch.object(verify,'run',side_effect=['','','']) as runner:
            verify.verify_source_snapshot()
        checks=[list(call.args[0]) for call in runner.call_args_list]
        self.assertIn(FIXTURE_SOURCE+'^{commit}',checks[0])
        for path in ('android','mobile/web','scripts/prepare_public_release.py','scripts/prepare_mobile_assets.py','LICENSE','NOTICE','THIRD_PARTY_NOTICES.md'):
            self.assertIn(path,checks[1]);self.assertIn(path,checks[2])
        for outputs in (['','mobile/web/app.js\n'],['','','android/app/build.gradle\n']):
            with patch.object(verify,'run',side_effect=outputs),self.assertRaises(ValueError):verify.verify_source_snapshot()

    def test_exact_signed_content_requires_size_sha256_and_git_blob(self):
        raw=b'SYNTHETIC exact signed bytes';good=entry(raw)
        verify.checked_bytes(raw,good)
        for key,value in [('bytes',len(raw)+1),('sha256','0'*64),('blob_sha','0'*40)]:
            with self.assertRaises(ValueError):verify.checked_bytes(raw,{**good,key:value})

    def test_all_four_matrix_paths_require_both_complete_probes(self):
        for code in (1,2):
            for api in (28,36):
                for mode in ('seed','verify'):
                    result=verify.parse_probe(probe(mode,code,api),mode,code,api)
                    self.assertEqual(result,{'ok':True,'mode':mode,'api_level':api,'from_version_code':code})

    def test_evidence_cannot_be_reused_across_api_or_starting_version(self):
        for text,mode,code,api in [(probe('seed',1,28),'seed',2,28),(probe('verify',1,28),'verify',1,36),
                                   (probe('seed',2,36),'verify',2,36)]:
            with self.assertRaises(ValueError):verify.parse_probe(text,mode,code,api)
        for code,api in [(True,28),(3,28),(1,27),(1,True)]:
            with self.assertRaises(ValueError):verify.parse_probe(probe(),'seed',code,api)

    def test_failed_missing_duplicate_or_incomplete_preservation_reports_are_rejected(self):
        good=probe()
        for malformed in ('','INSTRUMENTATION_CODE: -1\n',good.replace('CODE: -1','CODE: 0'),good.replace('ok=true','ok=false'),
                          good.replace('tags_preserved=true','tags_preserved=false'),
                          good.replace('INSTRUMENTATION_RESULT: original_text_preserved=true\n',''),
                          good+'INSTRUMENTATION_CODE: -1\n',good+'Process crashed\n',good+'INSTRUMENTATION_RESULT: api_level=28\n'):
            with self.assertRaises(ValueError):verify.parse_probe(malformed,'seed',1,28)

    def test_old_public_cache_must_match_the_selected_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'old.apk';target.write_bytes(b'SYNTHETIC old release')
            fake={1:{'bytes':len(target.read_bytes()),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'url':'https://github.com/unused'}}
            with patch.object(verify,'UPGRADE_FROM',fake):verify.fetch_old(target,1)
            with self.assertRaises(ValueError):verify.fetch_old(target,2)
            with self.assertRaises(ValueError):verify.fetch_old(target,True)

    def test_public_redirect_never_forwards_authorization_and_rejects_unknown_origins(self):
        request=urllib.request.Request('https://github.com/myflww/love-house/releases/download/a/b',headers={'Authorization':'Bearer SYNTHETIC'})
        handler=verify.PublicRedirect()
        next_request=handler.redirect_request(request,None,302,'',{},'https://release-assets.githubusercontent.com/synthetic.apk')
        self.assertFalse(next_request.has_header('Authorization'))
        for url in ('https://untrusted.example/file','http://github.com/file'):
            with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'',{},url)
        with self.assertRaises(ValueError):verify.NoRedirect().redirect_request(request,None,302,'',{},'https://api.github.com/other')

    def test_screenshot_is_complete_and_crc_checked(self):
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b'')
        verify.valid_png(raw)
        for broken in (b'not a PNG',raw[:-1],raw+b'extra',raw[:30]+bytes([raw[30]^1])+raw[31:]):
            with self.assertRaises(ValueError):verify.valid_png(broken)


if __name__=='__main__':unittest.main()
