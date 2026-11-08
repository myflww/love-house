"""Upstream runtime notices survive both independently packaged Android surfaces."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_android_engine as engine
import prepare_mobile_assets as mobile


class AndroidRuntimeLicenseTests(unittest.TestCase):
    def seed(self, root):
        for directory in ('nkb/service', 'android/app/src/main/python/lovehouse_android', 'mobile/web'):
            (root / directory).mkdir(parents=True)
        (root / 'nkb/service/host.py').write_text('"""Synthetic engine fixture."""\n')
        (root / 'android/app/src/main/python/lovehouse_android/__init__.py').write_text('"""Synthetic lifecycle fixture."""\n')
        (root / 'mobile/web/index.html').write_text('<!doctype html><title>Synthetic mobile fixture</title>')
        for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
            shutil.copyfile(ROOT / name, root / name)
        shutil.copytree(ROOT / 'android/licenses', root / 'android/licenses')
        for name in ('THIRD_PARTY_NOTICES.md', 'LICENSE.androidx-Apache-2.0.txt'):
            shutil.copyfile(ROOT / 'android' / name, root / 'android' / name)

    def test_fixed_upstream_notice_digests_and_exact_copy_to_both_bundles(self):
        manifest = json.loads((ROOT / 'android/licenses/provenance.json').read_text())
        self.assertEqual(manifest['embedded_runtime']['python'], '3.12.15-0')
        self.assertEqual(manifest['embedded_runtime']['chaquopy'], '17.2.0')
        self.assertTrue(manifest['ca_bundle']['matches_embedded_gradle_resource'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.seed(root)
            engine_result = engine.prepare(root)
            mobile_result = mobile.prepare(root)
            full = root / engine_result['output'] / 'lovehouse_android/licenses'
            offline = root / mobile_result['generated'] / 'web/android-licenses'
            for entry in manifest['files']:
                content = (ROOT / 'android/licenses' / entry['file']).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry['sha256'])
                self.assertEqual((full / 'android/licenses' / entry['file']).read_bytes(), content)
                self.assertEqual((offline / 'licenses' / entry['file']).read_bytes(), content)
            # Shared product notices are not overwritten by Android runtime terms.
            self.assertEqual((full / 'THIRD_PARTY_NOTICES.md').read_bytes(), (ROOT / 'THIRD_PARTY_NOTICES.md').read_bytes())
            self.assertEqual((full / 'android/THIRD_PARTY_NOTICES.md').read_bytes(), (ROOT / 'android/THIRD_PARTY_NOTICES.md').read_bytes())

    def test_unreviewed_private_material_or_symlink_cannot_hide_in_notices(self):
        for kind in ('secret', 'symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.seed(root)
                path = root / 'android/licenses/LICENSE.unreviewed.txt'
                if kind == 'secret':
                    path.write_text('credential="sk-' + 'Z' * 40 + '"')
                else:
                    path.symlink_to(root / 'NOTICE')
                for builder in (engine.prepare, mobile.prepare):
                    with self.assertRaises(ValueError):
                        builder(root)


if __name__ == '__main__':
    unittest.main()
