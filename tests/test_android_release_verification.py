"""Public APK digest boundaries and truthful raw Android test evidence."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import unittest
import io
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('android_release_verify', ROOT / 'scripts/verify_android_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def blob(content):
    return {'blob_sha': hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\0' + content).hexdigest(),
            'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}


def manifest():
    return {'schema': release.SCHEMA, 'source_commit': 'a' * 40, 'application_id': release.APP_ID,
            'version_name': '0.1.0-preview1', 'version_code': 1, 'certificate_sha256': 'b' * 64,
            'apk': blob(b'FAKE main APK'), 'test_apk': blob(b'FAKE test APK')}


def transcript(code=0):
    return ('INSTRUMENTATION_STATUS: class=example.SyntheticTest\n'
            'INSTRUMENTATION_STATUS: test=keepsOriginalUnicode\n'
            'INSTRUMENTATION_STATUS: numtests=1\nINSTRUMENTATION_STATUS_CODE: 1\n'
            'INSTRUMENTATION_STATUS: class=example.SyntheticTest\n'
            'INSTRUMENTATION_STATUS: test=keepsOriginalUnicode\n'
            'INSTRUMENTATION_STATUS: numtests=1\nINSTRUMENTATION_STATUS_CODE: ' + str(code) + '\n'
            'INSTRUMENTATION_RESULT: stream=\nTime: 1.23\n\nOK (1 test)\n\nINSTRUMENTATION_CODE: -1\n')


class SignedAndroidCandidateTests(unittest.TestCase):
    def test_engine_upgrade_keeps_original_certificate_and_rejects_version_drift(self):
        value = manifest()
        value.update(version_name='0.10.6rc1', version_code=4,
                     certificate_sha256=release.ORIGINAL_CERT)
        self.assertEqual(release.validate_manifest(value), value)
        for key, wrong in [('certificate_sha256', 'b' * 64),
                           ('version_name', '0.10.7rc1'), ('version_code', 3)]:
            candidate = dict(value, **{key: wrong})
            with self.subTest(field=key), self.assertRaises(ValueError):
                release.validate_manifest(candidate)

    def test_engine_package_rejects_missing_abis_extra_libraries_and_permissions(self):
        names = ['assets/web/index.html', 'assets/chaquopy/app.imy', 'assets/chaquopy/build.json']
        names += ['lib/' + abi + '/' + library for abi in release.ENGINE_ABIS
                  for library in release.ENGINE_LIBRARIES]
        permission = "uses-permission: name='android.permission.INTERNET'\n"
        def check(entries, permissions=permission, engine=True):
            content = io.BytesIO()
            with zipfile.ZipFile(content, 'w') as writer:
                for name in entries:
                    writer.writestr(name, b'FAKE bounded packaging fixture')
            content.seek(0)
            with zipfile.ZipFile(content) as archive:
                return release.validate_package_contents(archive, permissions, engine=engine)
        check(names)
        for missing in ('assets/web/index.html', 'assets/chaquopy/app.imy',
                        'lib/x86_64/libpython3.12.so'):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                check([name for name in names if name != missing])
        for extra in ('lib/arm64-v8a/libunexpected.so', 'lib/armeabi-v7a/libpython3.12.so'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                check(names + [extra])
        for permissions in ('', permission + "uses-permission: name='android.permission.RECORD_AUDIO'\n",
                            permission + "uses-permission-sdk-m: name='android.permission.CAMERA'\n"):
            with self.subTest(permissions=permissions), self.assertRaises(ValueError):
                check(names, permissions)
        check(['assets/web/index.html'], '', engine=False)
        with self.assertRaises(ValueError):
            check(names, '', engine=False)

    def test_badging_attributes_allow_extra_fields_and_any_order_without_changing_identity(self):
        lines = (
            "package: name='" + release.APP_ID + "' versionCode='1' versionCodeMajor='0' versionName='0.1.0-preview1' compileSdkVersion='36'",
            "package: versionName='0.1.0-preview1' compileSdkVersion='36' versionCodeMajor='0' name='" + release.APP_ID + "' versionCode='1'",
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(release.badging_identity(line + "\nsdkVersion:'26'\ntargetSdkVersion:'36'\n"),
                                 {'package': release.APP_ID, 'version_code': '1', 'version_name': '0.1.0-preview1',
                                  'min_sdk': ['26'], 'target_sdk': ['36']})

    def test_badging_missing_duplicate_or_prefix_only_identity_attributes_are_rejected(self):
        valid = "package: name='" + release.APP_ID + "' versionCode='1' versionName='0.1.0-preview1'"
        invalid = (valid + " versionCode='2'", valid + " name='another.package'", valid + " versionName='other'",
                   valid.replace(" versionCode='1'", " versionCodeMajor='1'"),
                   valid.replace(" versionName='0.1.0-preview1'", ''), valid + '\n' + valid)
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                release.badging_identity(text)

    def test_manifest_has_a_fixed_identity_bounded_blobs_and_explicit_certificate(self):
        value = manifest()
        self.assertEqual(release.validate_manifest(value), value)
        for field, invalid in [('source_commit', '../private'), ('application_id', 'another.app'),
                               ('certificate_sha256', 'invalid'), ('version_code', True)]:
            changed = deepcopy(value)
            changed[field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError):
                release.validate_manifest(changed)
        for length in (0, True, release.MAX_APK_BYTES + 1):
            changed = deepcopy(value)
            changed['apk']['bytes'] = length
            with self.assertRaises(ValueError):
                release.validate_manifest(changed)

    def test_content_must_match_size_sha256_and_actual_git_blob_identity(self):
        content = b'FAKE signed APK bytes'
        entry = blob(content)
        release.verify_bytes(content, entry)
        for field, changed in [('bytes', len(content) + 1), ('sha256', '0' * 64), ('blob_sha', '0' * 40)]:
            invalid = dict(entry, **{field: changed})
            with self.subTest(field=field), self.assertRaises(ValueError):
                release.verify_bytes(content, invalid)

    def test_certificate_requires_one_real_sha256_signer(self):
        output = 'Signer #1 certificate SHA-256 digest: ' + 'A' * 64 + '\n'
        self.assertEqual(release.signer_digest(output), 'a' * 64)
        for invalid in ('FAKE not signed', output + output.replace('#1', '#2')):
            with self.assertRaises(ValueError):
                release.signer_digest(invalid)

    def test_instrumentation_target_is_read_from_apk_manifest(self):
        tree = ('  E: instrumentation (line=6)\n'
                '    A: android:name(0x01010003)="androidx.test.runner.AndroidJUnitRunner" (Raw: "androidx.test.runner.AndroidJUnitRunner")\n'
                '    A: android:targetPackage(0x01010021)="' + release.APP_ID + '" (Raw: "' + release.APP_ID + '")\n')
        self.assertEqual(release.instrumentation_identity(tree), ('androidx.test.runner.AndroidJUnitRunner', release.APP_ID))
        with self.assertRaises(ValueError):
            release.instrumentation_identity(tree.replace(release.APP_ID, 'another.target'))

    def test_real_complete_nonempty_test_sequence_is_required(self):
        self.assertEqual(release.parse_instrumentation(transcript())['tests'], 1)
        for invalid in ('OK (0 tests)\nINSTRUMENTATION_CODE: -1\n', transcript().replace('OK (1 test)', 'OK (2 tests)'),
                        transcript().replace('INSTRUMENTATION_CODE: -1', 'INSTRUMENTATION_CODE: 0'),
                        transcript().replace('INSTRUMENTATION_STATUS_CODE: 1', 'INSTRUMENTATION_STATUS_CODE: 0')):
            with self.assertRaises(ValueError):
                release.parse_instrumentation(invalid)

    def test_failures_errors_ignored_and_assumption_skips_never_pass(self):
        for code in (-1, -2, -3, -4):
            with self.subTest(code=code), self.assertRaises(ValueError):
                release.parse_instrumentation(transcript(code))


if __name__ == '__main__':
    unittest.main()
