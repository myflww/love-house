"""Publication gates use both real test transcripts and immutable release bytes."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('android_release_publish', ROOT / 'scripts/publish_android_release.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def blob(content):
    return {'blob_sha': hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest(),
            'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}


def candidate():
    return {'schema': publisher.verify.SCHEMA, 'source_commit': 'a' * 40, 'application_id': publisher.verify.APP_ID,
            'certificate_sha256': 'b' * 64, 'version_name': '0.1.0-preview1', 'version_code': 1,
            'apk': blob(b'FAKE exact signed APK'), 'test_apk': blob(b'FAKE exact signed test APK')}


def transcript(count=5):
    pieces = []
    for index in range(count):
        for code in (1, 0):
            pieces.append('INSTRUMENTATION_STATUS: class=example.SyntheticTest\n'
                          'INSTRUMENTATION_STATUS: test=test' + str(index) + '\n'
                          'INSTRUMENTATION_STATUS: numtests=' + str(count) + '\n'
                          'INSTRUMENTATION_STATUS_CODE: ' + str(code) + '\n')
    return ''.join(pieces) + 'INSTRUMENTATION_RESULT: stream=\nOK (' + str(count) + ' tests)\nINSTRUMENTATION_CODE: -1\n'


def evidence(api_level=28, count=5):
    value = candidate()
    return {'schema': 'love-house-android-release-verification/v1', 'signature_and_metadata': 'passed',
            **{key: deepcopy(value[key]) for key in ('source_commit', 'certificate_sha256', 'apk', 'test_apk')},
            'identities': {'apk': {'package': publisher.verify.APP_ID, 'version_code': '1', 'version_name': '0.1.0-preview1',
                                   'min_sdk': ['26'], 'target_sdk': ['36']},
                           'test_apk': {'package': publisher.verify.APP_ID + '.test', 'runner': 'androidx.test.runner.AndroidJUnitRunner',
                                        'target_package': publisher.verify.APP_ID}},
            'instrumentation': {'api_level': api_level, 'installed_release_sha256': value['apk']['sha256'],
                                'tests': count, 'failures': 0, 'errors': 0, 'skipped': 0}}


class FakeGitHub:
    def __init__(self):
        self.tag = None
        self.release = None
        self.assets = {}
        self.calls = []

    def tag_commit(self):
        return self.tag

    def find_release(self):
        return deepcopy(self.release)

    def request(self, method, path, **kwargs):
        self.calls.append((method, path))
        assert method != 'DELETE', 'Publisher must never delete assets'
        if method == 'POST' and path.endswith('/releases'):
            self.release = {**kwargs['payload'], 'id': 123}
            return deepcopy(self.release)
        if method == 'GET' and '/releases/assets/' in path:
            number = int(path.rsplit('/', 1)[1])
            return next(item['content'] for item in self.assets.values() if item['id'] == number)
        if method == 'GET' and '/assets?' in path:
            return [dict(item) for item in self.assets.values()]
        if method == 'POST' and '/assets?name=' in path:
            name = path.split('name=', 1)[1]
            item = {'id': len(self.assets) + 1, 'name': name, 'content': kwargs['content'],
                    'size': len(kwargs['content']), 'state': 'uploaded'}
            self.assets[name] = item
            return dict(item)
        if method == 'PATCH':
            self.release.update(kwargs['payload'])
            self.tag = self.release['target_commitish']
            return deepcopy(self.release)
        raise AssertionError('Unexpected request')


class AndroidPreviewPublishTests(unittest.TestCase):
    def test_both_api_versions_require_matching_certificate_source_and_five_real_tests(self):
        for api in (28, 36):
            self.assertEqual(publisher.checked_evidence(candidate(), evidence(api), api, transcript())['instrumentation']['tests'], 5)
        for key in ('certificate_sha256', 'source_commit'):
            changed = evidence()
            changed[key] = 'c' * len(changed[key])
            with self.subTest(key=key), self.assertRaises(ValueError):
                publisher.checked_evidence(candidate(), changed, 28, transcript())
        with self.assertRaises(ValueError):
            publisher.checked_evidence(candidate(), evidence(count=4), 28, transcript(4))
        for key, value in [('skipped', 1), ('tests', True), ('api_level', 36), ('installed_release_sha256', 'c' * 64)]:
            changed = evidence()
            changed['instrumentation'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                publisher.checked_evidence(candidate(), changed, 28, transcript())
        with self.assertRaises(ValueError):
            publisher.checked_evidence(candidate(), evidence(), 28, transcript().replace('INSTRUMENTATION_STATUS_CODE: 0', 'INSTRUMENTATION_STATUS_CODE: -3', 1))

    def test_public_assets_are_exact_and_licenses_keep_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            license_names = ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'android/LICENSE.androidx-Apache-2.0.txt',
                             'android/THIRD_PARTY_NOTICES.md', 'assets/fonts/ark-pixel-OFL.txt')
            for name in license_names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(('FAKE original licence ' + name + '\r\n\r\n').encode())
            for api in (28, 36):
                base = root / 'build/artifacts' / ('api-' + str(api))
                base.mkdir(parents=True)
                (base / publisher.APK_NAME).write_bytes(b'FAKE exact signed APK')
                (base / 'verification.json').write_text(json.dumps(evidence(api)), encoding='utf-8')
                (base / 'instrumentation.txt').write_text(transcript(), encoding='utf-8')
                (base / 'android-smoke.png').write_bytes(b'\x89PNG\r\n\x1a\nFAKE screenshot')
            assets = publisher.collect_assets(root, candidate(), root / 'build/artifacts')
            self.assertEqual(set(assets), {publisher.APK_NAME, publisher.EVIDENCE_NAME, publisher.LICENSE_NAME, 'SHA256SUMS.txt'})
            with zipfile.ZipFile(io.BytesIO(assets[publisher.LICENSE_NAME])) as archive:
                self.assertEqual(set(archive.namelist()), set(license_names))
                for name in license_names:
                    self.assertEqual(archive.read(name), (root / name).read_bytes())
            self.assertEqual(assets[publisher.LICENSE_NAME], publisher.licence_archive(root))
            self.assertNotIn('test.apk', ' '.join(assets))

    def test_publish_creates_draft_uploads_all_assets_then_makes_prerelease(self):
        client = FakeGitHub()
        assets = {'example.apk': b'FAKE verified APK', 'SHA256SUMS.txt': b'FAKE hash'}
        result = publisher.publish(client, 'a' * 40, assets)
        self.assertTrue(result['ok'])
        self.assertFalse(client.release['draft'])
        self.assertTrue(client.release['prerelease'])
        self.assertEqual(client.release['tag_name'], publisher.TAG)
        self.assertEqual(client.calls[-1][0], 'PATCH')
        calls = len(client.calls)
        publisher.publish(client, 'a' * 40, assets)
        self.assertTrue(all(method == 'GET' for method, _ in client.calls[calls:]))

    def test_existing_target_or_asset_conflicts_never_delete_or_overwrite(self):
        client = FakeGitHub()
        assets = {'example.apk': b'FAKE verified APK'}
        publisher.publish(client, 'a' * 40, assets)
        calls = len(client.calls)
        with self.assertRaises(ValueError):
            publisher.publish(client, 'b' * 40, assets)
        self.assertEqual(len(client.calls), calls)
        client.assets['example.apk']['content'] = b'FAKE modified APK'
        calls = len(client.calls)
        with self.assertRaises(ValueError):
            publisher.publish(client, 'a' * 40, assets)
        self.assertTrue(all(method == 'GET' for method, _ in client.calls[calls:]))

    def test_download_redirect_strips_token_and_rejects_untrusted_hosts(self):
        handler = publisher.AssetRedirect()
        request = urllib.request.Request('https://api.github.com/repos/myflww/love-house/releases/assets/1',
                                         headers={'Authorization': 'Bearer FAKE_NOT_A_REAL_TOKEN'})
        redirected = handler.redirect_request(request, None, 302, '', {}, 'https://release-assets.githubusercontent.com/FAKE')
        self.assertIsNone(redirected.get_header('Authorization'))
        for url in ('http://release-assets.githubusercontent.com/FAKE', 'https://example.test/FAKE'):
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, '', {}, url)


if __name__ == '__main__':
    unittest.main()
