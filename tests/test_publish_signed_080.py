"""Append-only public release behavior and actual transcript gates."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import struct
import tempfile
import unittest
import urllib.parse
import urllib.request
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'source' / 'love-house-d4130f8aec3882a30a7d237a5d29122509a2dc0d' / 'scripts'))
sys.path.insert(0, str(HERE))
import publish_signed_080 as pub


BODY = '''# 爱之屋 0.8.0rc1：Windows 修复版与移动端预览

本次先提供已测试的 Windows 修复版、移动端入口和 Android 原密钥签名交接。macOS 新一轮功能仍在开发。

## 下载与使用

- Windows x64：Windows text unchanged.
- Android：本次提供开发交接包，仍未签名。
- iPhone / Android 浏览器：Browser text unchanged.

## 给原 Android 签名电脑的接手任务

Old instructions.

## 已验证的范围

Windows and macOS evidence unchanged.
'''
RUN_URL = 'https://github.com/myflww/love-house/actions/runs/123456'


def blob(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def candidate():
    return {'schema': pub.verify.SCHEMA, 'source_commit': '382c5ee45f66016af7117c2ad5a9c16cc2a75f9e', 'handoff_commit': pub.TARGET,
            'application_id': pub.verify.APP_ID, 'version_name': '0.8.0rc1', 'version_code': 2,
            'certificate_sha256': pub.verify.CERT,
            'apk': blob(b'SYNTHETIC signed upgrade app'), 'test_apk': blob(b'SYNTHETIC signed developer harness')}


def transcript():
    text = ''
    for index in range(6):
        for code in (1, 0):
            text += ('INSTRUMENTATION_STATUS: class=example.SyntheticTest\n'
                     'INSTRUMENTATION_STATUS: test=case' + str(index) + '\n'
                     'INSTRUMENTATION_STATUS: numtests=6\nINSTRUMENTATION_STATUS_CODE: ' + str(code) + '\n')
    return text + 'INSTRUMENTATION_RESULT: stream=\nOK (6 tests)\nINSTRUMENTATION_CODE: -1\n'


def probe(mode, api=28):
    fields = {'ok': 'true', 'mode': mode, 'protocol': 'love-house-ui-upgrade/v1', 'target_package': pub.verify.APP_ID,
              'expected_version_code': '1' if mode == 'seed' else '2', 'api_level': str(api),
              'same_original_certificate': 'true', 'original_text_preserved': 'true',
              'assistant_reply_preserved': 'true', 'tags_preserved': 'true'}
    return ''.join('INSTRUMENTATION_RESULT: ' + key + '=' + value + '\n' for key,value in fields.items()) + 'INSTRUMENTATION_CODE: -1\n'


def png():
    def chunk(kind, raw):
        return struct.pack('>I',len(raw)) + kind + raw + struct.pack('>I',zlib.crc32(kind+raw)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0)) + chunk(b'IDAT',zlib.compress(b'\0\0\0\0\0')) + chunk(b'IEND',b'')


def report(value, api):
    instrument, seed, restored = transcript(), probe('seed', api), probe('verify', api)
    return {'schema': 'love-house-android-080-verification/v1', 'candidate': value, 'api_level': api,
            'signature_and_metadata': 'passed',
            'identities': {'apk': {'package': pub.verify.APP_ID, 'version_code': '2', 'version_name': '0.8.0rc1',
                                  'min_sdk': ['26'], 'target_sdk': ['36']},
                           'test_apk': {'package': pub.verify.APP_ID + '.test',
                                        'runner': 'androidx.test.runner.AndroidJUnitRunner', 'target_package': pub.verify.APP_ID}},
            'instrumentation': {'tests': 6, 'failures': 0, 'errors': 0, 'skipped': 0},
            'instrument_sha256': hashlib.sha256(instrument.encode()).hexdigest(),
            'upgrade_preservation': {'passed': True, 'from_version_code': 1, 'to_version_code': 2,
                                     'seed_probe_sha256': hashlib.sha256(seed.encode()).hexdigest(),
                                     'verify_probe_sha256': hashlib.sha256(restored.encode()).hexdigest()}}


def original_assets():
    return [{'name': name, 'id': value[0], 'size': value[1], 'digest': 'sha256:' + value[2], 'state': 'uploaded'}
            for name, value in pub.ORIGINAL_ASSETS.items()]


class FakeGitHub:
    def __init__(self):
        self.release = {'id': pub.RELEASE_ID, 'tag_name': pub.TAG, 'draft': False, 'prerelease': True,
                        'target_commitish': pub.TARGET, 'body': BODY}
        self.assets = original_assets()
        self.contents = {}
        self.calls = []
        self.change_original_after_upload = False

    def request(self, method, path, **kwargs):
        self.calls.append((method, path))
        if method == 'GET' and path == pub.API_BASE:
            return deepcopy(self.release)
        if method == 'GET' and path == pub.API_BASE + '/assets?per_page=100':
            return deepcopy(self.assets)
        if method == 'GET' and '/releases/assets/' in path:
            return self.contents[int(path.rsplit('/', 1)[1])]
        if method == 'POST' and path.startswith(pub.API_BASE + '/assets?name='):
            name = urllib.parse.unquote(path.split('name=', 1)[1])
            assert name not in {entry['name'] for entry in self.assets}, 'Would overwrite an asset'
            content = kwargs['content']
            item = {'id': 900000 + len(self.contents), 'name': name, 'size': len(content), 'state': 'uploaded',
                    'digest': 'sha256:' + hashlib.sha256(content).hexdigest()}
            self.assets.append(item)
            self.contents[item['id']] = content
            if self.change_original_after_upload:
                self.assets[0]['digest'] = 'sha256:' + '0' * 64
            return deepcopy(item)
        if method == 'PATCH' and path == pub.API_BASE:
            assert set(kwargs['payload']) == {'body'}
            self.release['body'] = kwargs['payload']['body']
            return deepcopy(self.release)
        raise AssertionError('Unexpected API mutation')


class PublishSigned080Tests(unittest.TestCase):
    def test_collect_requires_both_actual_success_sequences_and_upgrade_preservation(self):
        value = candidate()
        with tempfile.TemporaryDirectory(prefix='test-publish080-', dir=HERE) as temporary:
            root = Path(temporary).resolve()
            self.assertTrue(root.is_relative_to(HERE.resolve()))
            artifacts = root / 'build/android080-artifacts'
            for api in (28, 36):
                target = artifacts / ('api-' + str(api))
                target.mkdir(parents=True)
                (target / pub.APK_NAME).write_bytes(b'SYNTHETIC signed upgrade app')
                (target / 'verification.json').write_text(json.dumps(report(value, api)), encoding='utf-8', newline='\n')
                (target / 'instrumentation.txt').write_text(transcript(), encoding='utf-8', newline='\n')
                (target / 'upgrade-seed.txt').write_text(probe('seed',api), encoding='utf-8', newline='\n')
                (target / 'upgrade-verify.txt').write_text(probe('verify',api), encoding='utf-8', newline='\n')
                (target / 'android-smoke.png').write_bytes(png())
            assets = pub.collect_assets(root, value, artifacts)
            self.assertEqual(set(assets), {pub.APK_NAME, pub.EVIDENCE_NAME, pub.CHECKSUMS_NAME})
            evidence = json.loads(assets[pub.EVIDENCE_NAME])
            self.assertFalse(evidence['physical_android_phone_tested'])
            self.assertTrue(evidence['emulators']['28']['upgrade_preservation']['passed'])
            (artifacts / 'api-36/upgrade-verify.txt').write_text(probe('verify',36).replace('ok=true', 'ok=false'), encoding='utf-8', newline='\n')
            with self.assertRaises(ValueError):
                pub.collect_assets(root, value, artifacts)
        valid = report(value, 28)
        for field, modified in [('candidate', dict(value, version_code=3)), ('api_level', 36),
                                ('instrumentation', {'tests': 6, 'failures': 0, 'errors': 0, 'skipped': 1}),
                                ('upgrade_preservation', dict(valid['upgrade_preservation'], passed=False))]:
            altered = deepcopy(valid); altered[field] = modified
            with self.subTest(field=field), self.assertRaises(ValueError):
                pub.checked_evidence(value, altered, 28, transcript(), probe('seed'), probe('verify'))

    def test_append_keeps_original_eight_assets_and_non_android_body(self):
        client = FakeGitHub()
        assets = {pub.APK_NAME: b'APP', pub.EVIDENCE_NAME: b'REPORT', pub.CHECKSUMS_NAME: b'CHECKSUMS'}
        before = deepcopy(client.assets)
        result = pub.publish(client, assets, RUN_URL)
        self.assertTrue(result['ok'])
        self.assertEqual(client.assets[:8], before)
        self.assertEqual(len(client.assets), 11)
        self.assertTrue(all(method in {'GET', 'POST', 'PATCH'} for method, _ in client.calls))
        self.assertIn('Windows text unchanged.', client.release['body'])
        self.assertIn('Windows and macOS evidence unchanged.', client.release['body'])
        self.assertIn('Browser text unchanged.', client.release['body'])
        self.assertIn('这不是实体手机验收', client.release['body'])
        client.calls.clear()
        pub.publish(client, assets, RUN_URL)
        self.assertTrue(all(method == 'GET' for method, _ in client.calls), 'Identical retry should only read')

    def test_original_asset_change_and_new_name_conflicts_never_overwrite(self):
        assets = {pub.APK_NAME: b'APP', pub.EVIDENCE_NAME: b'REPORT', pub.CHECKSUMS_NAME: b'CHECKSUMS'}
        client = FakeGitHub(); client.assets[0]['size'] += 1
        with self.assertRaises(ValueError):
            pub.publish(client, assets, RUN_URL)
        self.assertFalse(any(method != 'GET' for method, _ in client.calls))
        client = FakeGitHub()
        client.assets.append({'id': 1, 'name': pub.APK_NAME, 'size': 3, 'state': 'uploaded'})
        client.contents[1] = b'BAD'
        with self.assertRaises(ValueError):
            pub.publish(client, assets, RUN_URL)
        self.assertFalse(any(method != 'GET' for method, _ in client.calls))
        client = FakeGitHub(); client.change_original_after_upload = True
        with self.assertRaises(ValueError):
            pub.publish(client, assets, RUN_URL)
        self.assertFalse(any(method == 'PATCH' for method, _ in client.calls))

    def test_body_rewrite_rejects_unknown_structure_and_does_not_duplicate_section(self):
        first = pub.rewritten_body(BODY, RUN_URL, 'a' * 64)
        second = pub.rewritten_body(first, RUN_URL, 'a' * 64)
        self.assertEqual(first, second)
        self.assertEqual(first[first.index('## 已验证的范围'):], BODY[BODY.index('## 已验证的范围'):])
        with self.assertRaises(ValueError):
            pub.rewritten_body(BODY.replace('## 已验证的范围', 'unexpected'), RUN_URL, 'a' * 64)

    def test_asset_download_redirect_drops_the_repository_bearer(self):
        request = urllib.request.Request('https://api.github.com/repos/myflww/love-house/releases/assets/1',
                                         headers={'Authorization': 'Bearer DO-NOT-FORWARD'})
        redirect = pub.AssetRedirect().redirect_request(request, None, 302, '', {}, 'https://release-assets.githubusercontent.com/object?signature=synthetic')
        self.assertIsNone(redirect.get_header('Authorization'))
        with self.assertRaises(ValueError):
            pub.AssetRedirect().redirect_request(request, None, 302, '', {}, 'https://example.invalid/object')


if __name__ == '__main__':
    unittest.main()
