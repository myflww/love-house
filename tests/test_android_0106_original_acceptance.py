"""Reject synthetic pass receipts which do not prove the requested real mode."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / 'scripts/verify_android_0106.py').is_file():
    SCRIPTS = ROOT / 'scripts'
else:
    SCRIPTS = ROOT / 'source/scripts'
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / 'verify_android_0106.py'
if not SCRIPT.is_file():
    SCRIPT = Path(__file__).with_name('verify_android_0106.py')
SPEC = importlib.util.spec_from_file_location('android0106_acceptance', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

def receipt(mode='verify', api=36):
    fields = {'mode': mode, 'protocol': 'love-house-original-upgrade-0106/v1', 'ok': 'true',
              'api_level': str(api), 'original_certificate': 'true',
              'version_code': '3' if mode == 'seed' else '4', 'model_calls': '0'}
    return '\n'.join('INSTRUMENTATION_RESULT: '+key+'='+value for key, value in fields.items())+'\nINSTRUMENTATION_CODE: -1\n'

class ProbeReceiptTests(unittest.TestCase):
    def test_signing_receipt_must_bind_source_unsigned_inputs_and_signed_outputs(self):
        import copy
        receipt = {'schema': 'love-house-android-0106-original-signing/v1', 'source_commit': module.SOURCE,
                   'same_original_signer': True, 'payload_preserved': True, 'signature_and_metadata': 'passed',
                   'application_id': module.APP, 'version_name': '0.10.6rc1', 'version_code': 4,
                   'certificate_sha256': module.CERT,
                   'input_manifest_sha256': '6976945a77dd1a9f5bc1de2c56370eb5fa3580923f5af069f3faf76b494360ec',
                   'apksigner_jar_sha256': '3716d9311e55d2b0918a2fd9d54ba9e406c5f6abeea700b287f11259bc163dec',
                   'source_archive': dict(zip(('bytes', 'sha256'), module.SOURCE_ARCHIVE)),
                   'inputs': {key: dict(zip(('bytes', 'sha256'), val)) for key, val in module.UNSIGNED_INPUTS.items()},
                   'signed': {}}
        value = {'artifacts': {}}
        for key, (size, sha) in module.EXPECTED.items():
            value['artifacts'][key] = {'bytes': size, 'sha256': sha}
            receipt['signed'][key] = {'bytes': size, 'sha256': sha, 'certificate_sha256': module.CERT,
                'qa_only': key == 'test_apk', 'identity': {'package': module.APP + ('.test' if key == 'test_apk' else ''),
                    'version_code': '' if key == 'test_apk' else '4', 'version_name': '' if key == 'test_apk' else '0.10.6rc1',
                    'min_sdk': ['26'], 'target_sdk': ['36']}}
        module.validate_signing_receipt(receipt, value)
        mutations = [('source_commit',), ('same_original_signer',), ('certificate_sha256',),
                     ('input_manifest_sha256',), ('source_archive', 'sha256'), ('inputs', 'apk', 'sha256'),
                     ('inputs', 'test_apk', 'bytes'), ('signed', 'apk', 'sha256'),
                     ('signed', 'test_apk', 'certificate_sha256'), ('signed', 'apk', 'qa_only'),
                     ('signed', 'test_apk', 'identity', 'version_code')]
        for keys in mutations:
            bad = copy.deepcopy(receipt); target = bad
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = 'invalid'
            with self.assertRaises(ValueError):
                module.validate_signing_receipt(bad, value)

    def test_every_fixed_mode_requires_exact_api_and_original_certificate(self):
        for mode in module.MODES:
            for api in (28, 36):
                value = module.parse_probe(receipt(mode, api), mode, api)
                self.assertIs(value['ok'], True)
                self.assertEqual(value['api_level'], api)
                self.assertEqual(value['mode'], mode)

    def test_reject_other_api_other_mode_duplicate_or_missing_pass_fields(self):
        bad = [receipt(api=28), receipt(mode='seed'), receipt().replace('ok=true', 'ok=false'),
               receipt().replace('original_certificate=true', 'original_certificate=false'),
               receipt().replace('model_calls=0', 'model_calls=1'),
               receipt().replace('version_code=4', 'version_code=3'),
               receipt()+'INSTRUMENTATION_RESULT: ok=true\n',
               receipt().replace('INSTRUMENTATION_RESULT: ok=true\n', ''),
               receipt().replace('INSTRUMENTATION_CODE: -1', 'INSTRUMENTATION_CODE: 1'),
               receipt()+'INSTRUMENTATION_RESULT: error_stage=failed\n',
               receipt()+'INSTRUMENTATION_FAILED: rejected\n']
        for text in bad:
            with self.assertRaises(ValueError):
                module.parse_probe(text, 'verify', 36)

    def test_legacy_webview_cannot_become_full_engine_proof(self):
        scope = module.scope_for(28, {'major': 66})
        self.assertFalse(scope['full_engine_verified'])
        self.assertTrue(scope['partial'])
        self.assertEqual(scope['expected_tests'], 7)
        with self.assertRaises(ValueError):
            module.scope_for(36, {'major': 66})
        self.assertTrue(module.scope_for(36, {'major': 140})['full_engine_verified'])

    def test_part_paths_and_digests_are_enforced_before_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            part = root/'release-handoff/0.10.6rc1/app/part-0000.bin'
            part.parent.mkdir(parents=True)
            part.write_bytes(b'reviewed APK example')
            raw = part.read_bytes()
            metadata = {'bytes': len(raw), 'sha256': module.digest(raw), 'blob_sha': module.blob(raw),
                        'parts': [{'path': part.relative_to(root).as_posix(), 'bytes': len(raw),
                                   'sha256': module.digest(raw), 'blob_sha': module.blob(raw)}]}
            with patch.object(module, 'ROOT', root):
                self.assertEqual(module.assemble(metadata, root/'checked.apk').read_bytes(), raw)
                for name in ('../outside.bin', 'release-handoff/0.10.6rc1/../../escape.bin',
                             'release-handoff/0.10.6rc1/app\\escape.bin'):
                    bad = dict(metadata, parts=[dict(metadata['parts'][0], path=name)])
                    with self.assertRaises(ValueError):
                        module.assemble(bad, root/'rejected.apk')
                part.write_bytes(b'altered')
                with self.assertRaises(ValueError):
                    module.assemble(metadata, root/'tampered.apk')
                self.assertFalse((root/'tampered.apk').exists())

    def test_only_exact_frozen_public_candidates_are_accepted(self):
        import json
        metadata = {'schema': 'love-house-android-0106-candidate/v1', 'source_commit': module.SOURCE,
                    'build_run_id': 42439732197, 'application_id': module.APP, 'version_name': '0.10.6rc1',
                    'version_code': 4, 'certificate_sha256': module.CERT, 'old_apk': module.OLD,
                    'artifacts': {key: {'bytes': size, 'sha256': sha} for key, (size, sha) in module.EXPECTED.items()}}
        metadata['artifacts']['extra_qa'] = {}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root/'candidate.json'
            with patch.object(module, 'ROOT', root):
                path.write_text(json.dumps(metadata))
                self.assertEqual(module.candidate(path)['source_commit'], module.SOURCE)
                for key, bad_value in [('source_commit', '0'*40), ('version_code', True),
                                       ('build_run_id', 0), ('certificate_sha256', '0'*64)]:
                    bad = dict(metadata, **{key: bad_value});path.write_text(json.dumps(bad))
                    with self.assertRaises(ValueError):
                        module.candidate(path)

if __name__ == '__main__':
    unittest.main()
