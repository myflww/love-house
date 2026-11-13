"""Reject incomplete signed-upgrade evidence without installing anything."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import android_release_identity as identity
import verify_android_signed_upgrade as upgrade


class AndroidReleaseIdentityTests(unittest.TestCase):
    def test_package_and_engine_must_be_the_same_single_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'android/app').mkdir(parents=True)
            (root / 'nkb').mkdir()
            gradle = root / 'android/app/build.gradle'
            core = root / 'nkb/_version.py'
            gradle.write_text("versionCode 5\nversionName '0.10.7rc1'\n")
            core.write_text("__version__ = '0.10.7rc1'\n")
            self.assertEqual(identity.release_identity(root), ('0.10.7rc1', 5))
            core.write_text("__version__ = '0.10.6rc1'\n")
            with self.assertRaises(ValueError): identity.release_identity(root)
            core.write_text("__version__ = '0.10.7rc1'\n")
            gradle.write_text(gradle.read_text() + "versionName '0.10.7rc1'\n")
            with self.assertRaises(ValueError): identity.release_identity(root)


class AndroidSignedUpgradeTests(unittest.TestCase):
    def transcript(self, mode='verify', api=36, code=5):
        expected = {'mode': mode, 'protocol': 'love-house-ui-upgrade/v1', 'target_package': upgrade.APP_ID,
                    'ok': 'true', 'api_level': str(api), 'from_version_code': '4',
                    'expected_version_code': str(4 if mode == 'seed' else code),
                    'same_original_certificate': 'true', 'original_text_preserved': 'true',
                    'assistant_reply_preserved': 'true', 'tags_preserved': 'true'}
        return ''.join(f'INSTRUMENTATION_RESULT: {k}={v}\n' for k, v in expected.items()) + 'INSTRUMENTATION_CODE: -1\n'

    def test_actual_public_old_version_and_each_restart_require_complete_receipts(self):
        for api in (28, 36):
            for mode in ('seed', 'verify'):
                upgrade.parse_probe(self.transcript(mode, api), mode, api, 5)
        text = self.transcript()
        for wrong in (text.replace('from_version_code=4', 'from_version_code=3'),
                      text.replace('expected_version_code=5', 'expected_version_code=4'),
                      text.replace('original_text_preserved=true', 'original_text_preserved=false'),
                      text + 'INSTRUMENTATION_RESULT: ok=true\n',
                      text.replace('INSTRUMENTATION_CODE: -1', 'INSTRUMENTATION_CODE: 0')):
            with self.assertRaises(ValueError): upgrade.parse_probe(wrong, 'verify', 36, 5)

    def test_signed_bytes_and_exact_frozen_input_receipt_are_both_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = {key: Path(temporary) / (key + '.apk') for key in ('apk', 'test_apk')}
            for key, path in paths.items(): path.write_bytes(('SYNTHETIC ' + key).encode())
            value = {'source_commit': 'a' * 40, 'application_id': upgrade.APP_ID,
                     'version_name': '0.10.7rc1', 'version_code': 5,
                     'certificate_sha256': upgrade.ORIGINAL_CERT,
                     'source_archive': {'sha256': 'b' * 64}, 'apk': {'sha256': 'c' * 64}, 'test_apk': {'sha256': 'd' * 64}}
            receipt = {key: value[key] for key in ('source_commit', 'application_id', 'version_name', 'version_code', 'certificate_sha256')}
            receipt.update(schema='love-house-android-original-signing/v1', same_original_signer=True,
                           payload_preserved=True, signature_and_metadata='passed',
                           source_archive=value['source_archive'], inputs={key: value[key] for key in paths},
                           signed={key: {'path': path.name, 'bytes': path.stat().st_size, 'sha256': upgrade.sha(path),
                                         'certificate_sha256': upgrade.ORIGINAL_CERT, 'qa_only': key == 'test_apk'}
                                   for key, path in paths.items()})
            upgrade.validate_receipt(receipt, value, paths)
            for field, wrong in (('source_commit', 'e' * 40), ('payload_preserved', False),
                                 ('certificate_sha256', 'f' * 64), ('version_code', 4)):
                candidate = dict(receipt, **{field: wrong})
                with self.assertRaises(ValueError): upgrade.validate_receipt(candidate, value, paths)
            paths['apk'].write_bytes(b'SYNTHETIC swapped payload')
            with self.assertRaises(ValueError): upgrade.validate_receipt(receipt, value, paths)


if __name__ == '__main__':
    unittest.main()
