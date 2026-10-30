"""Gates for fixed original-key APKs and truthful, complete upgrade evidence."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest
import zlib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))
sys.path.insert(0, str(HERE.parent / 'handoff/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_signed_080 as verify


def entry(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def candidate():
    return {'schema': verify.SCHEMA, 'source_commit': verify.PRODUCTION_SOURCE, 'handoff_commit': verify.SOURCE,
            'application_id': verify.APP_ID, 'version_name': '0.8.0rc1', 'version_code': 2,
            'certificate_sha256': verify.CERT, 'apk': entry(b'FAKE signed main'), 'test_apk': entry(b'FAKE signed test')}


def probe(mode='seed'):
    values = {'ok': 'true', 'mode': mode, 'protocol': 'love-house-ui-upgrade/v1', 'target_package': verify.APP_ID,
              'expected_version_code': '1' if mode == 'seed' else '2', 'api_level': '28',
              'same_original_certificate': 'true', 'original_text_preserved': 'true',
              'assistant_reply_preserved': 'true', 'tags_preserved': 'true'}
    return ''.join('INSTRUMENTATION_RESULT: ' + key + '=' + value + '\n' for key, value in values.items()) + 'INSTRUMENTATION_CODE: -1\n'


class SignedOriginalKey080Tests(unittest.TestCase):
    def test_only_fixed_source_identity_original_certificate_and_bounded_bytes(self):
        good = candidate()
        self.assertEqual(verify.validate_candidate(good), good)
        for key, value in [('schema', 'unknown'), ('source_commit', 'a' * 40), ('handoff_commit', 'a' * 40),
                           ('certificate_sha256', 'a' * 64), ('application_id', 'another.app'),
                           ('version_name', '0.1.0-preview1'), ('version_code', True)]:
            wrong = deepcopy(good); wrong[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify.validate_candidate(wrong)
        for length in (True, 0, verify.MAX_APK + 1):
            wrong = deepcopy(good); wrong['apk']['bytes'] = length
            with self.assertRaises(ValueError): verify.validate_candidate(wrong)

    def test_signed_content_must_match_all_three_public_identities(self):
        raw = b'FAKE exact signed bytes'
        good = entry(raw)
        verify.checked_bytes(raw, good)
        for key, value in [('bytes', len(raw) + 1), ('sha256', '0' * 64), ('blob_sha', '0' * 40)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify.checked_bytes(raw, dict(good, **{key: value}))

    def test_probe_requires_success_and_complete_mode_specific_memory_preservation(self):
        for mode in ('seed', 'verify'):
            self.assertTrue(verify.parse_probe(probe(mode), mode)['ok'])
        for malformed in (probe().replace('CODE: -1', 'CODE: 0'), probe().replace('ok=true', 'ok=false'),
                          probe().replace('mode=seed', 'mode=verify'), probe().replace('tags_preserved=true', 'tags_preserved=false'),
                          probe().replace('INSTRUMENTATION_RESULT: original_text_preserved=true\n', ''),
                          probe() + 'INSTRUMENTATION_CODE: -1\n', probe() + 'Process crashed\n'):
            with self.assertRaises(ValueError): verify.parse_probe(malformed, 'seed')

    def test_false_or_empty_probe_output_cannot_pass(self):
        for malformed in ('', 'INSTRUMENTATION_CODE: -1\n', 'INSTRUMENTATION_RESULT: ok=true\nINSTRUMENTATION_CODE: -1\n'):
            with self.assertRaises(ValueError): verify.parse_probe(malformed, 'verify')

    def test_png_evidence_requires_real_complete_crc_checked_chunks(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        raw = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
        raw += chunk(b'IDAT', zlib.compress(b'\0\0\0\0')) + chunk(b'IEND', b'')
        verify.valid_png(raw)
        for invalid in (b'FAKE screenshot', raw[:-1], raw + b'extra', raw[:30] + bytes([raw[30] ^ 1]) + raw[31:]):
            with self.assertRaises(ValueError): verify.valid_png(invalid)


if __name__ == '__main__':
    unittest.main()
