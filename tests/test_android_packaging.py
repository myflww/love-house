"""Offline Android packaging boundaries and non-empty instrumentation gates."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The preparation script imports its sibling, just as its command-line entry does.
import sys
sys.path.insert(0, str(ROOT / 'scripts'))
assets = load('android_mobile_assets', 'prepare_mobile_assets.py')
public = load('android_public_source', 'prepare_public_release.py')
results = load('android_test_results', 'check_android_test_results.py')


class MobileAssetPackagingTests(unittest.TestCase):
    def seed(self, root):
        web = root / 'mobile/web'
        web.mkdir(parents=True)
        (web / 'index.html').write_text('<!doctype html><html lang="zh"><body>假数据 爱之屋</body></html>', encoding='utf-8')
        (web / 'app.js').write_text('window.example = "中文🌸";', encoding='utf-8')
        (web / 'manifest.webmanifest').write_text('{"name":"Example"}', encoding='utf-8')
        for name, content in {'LICENSE': '# PolyForm Noncommercial License 1.0.0\n',
                              'NOTICE': 'Required Notice: Example',
                              'THIRD_PARTY_NOTICES.md': 'Retain upstream licence notices.'}.items():
            (root / name).write_text(content, encoding='utf-8')
        return web

    def test_byte_exact_bundle_has_relative_hashes_and_only_reviewed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = self.seed(root)
            (root / 'resources/runtime').mkdir(parents=True)
            (root / 'resources/runtime/private.exe').write_bytes(b'FAKE desktop runtime')
            value = assets.prepare(root)
            output = root / value['generated']
            self.assertTrue(value['ok'])
            self.assertEqual((output / 'web/app.js').read_bytes(), (web / 'app.js').read_bytes())
            self.assertEqual((output / 'web/LICENSE').read_bytes(), (root / 'LICENSE').read_bytes())
            marker = json.loads((output / assets.MARKER).read_text('utf-8'))
            self.assertEqual(marker['schema'], assets.SCHEMA)
            self.assertTrue(all(not Path(row['path']).is_absolute() and len(row['sha256']) == 64 for row in marker['files']))
            self.assertFalse(any(path.suffix == '.exe' for path in output.rglob('*')))

    def test_private_json_databases_keys_and_caches_cannot_enter_bundle(self):
        for name in ('backup.json', 'memory.brain.json', 'private.sqlite3', 'signing.jks', '.env',
                     'node_modules/private.js', 'data/private.js'):
            with self.subTest(asset=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                web = self.seed(root)
                path = web / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('FAKE private material', encoding='utf-8')
                with self.assertRaises(ValueError):
                    assets.prepare(root)
                self.assertFalse((root / 'android/app/build/generated/mobileAssets').exists())

    def test_only_the_byte_exact_original_font_notice_is_an_approved_text_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = self.seed(root)
            approved = root / 'assets/fonts/ark-pixel-OFL.txt'
            approved.parent.mkdir(parents=True)
            approved.write_bytes(b'FAKE approved font licence fixture')
            supplied = web / assets.FONT_LICENSE
            supplied.parent.mkdir(parents=True)
            supplied.write_bytes(approved.read_bytes())
            value = assets.prepare(root)
            self.assertEqual((root / value['generated'] / 'web' / assets.FONT_LICENSE).read_bytes(), approved.read_bytes())
            supplied.write_bytes(b'FAKE modified terms')
            with self.assertRaises(ValueError):
                assets.prepare(root)
            supplied.write_bytes(approved.read_bytes())
            (web / 'private-note.txt').write_bytes(b'FAKE private notes')
            with self.assertRaises(ValueError):
                assets.prepare(root)

    def test_rejected_secret_is_never_printed_or_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = self.seed(root)
            secret = 'sk-' + ''.join(chr(65 + index % 26) for index in range(40))
            (web / 'app.js').write_text('const credential="' + secret + '";', encoding='utf-8')
            with self.assertRaises(ValueError) as caught:
                assets.prepare(root)
            self.assertNotIn(secret, str(caught.exception))
            self.assertFalse((root / 'android/app/build/generated/mobileAssets').exists())

    def test_unknown_output_is_preserved_and_outside_build_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.seed(root)
            output = root / 'android/app/build/generated/mobileAssets'
            output.mkdir(parents=True)
            sentinel = output / 'private.txt'
            sentinel.write_text('FAKE preserve me', encoding='utf-8')
            with self.assertRaises(ValueError):
                assets.prepare(root)
            self.assertEqual(sentinel.read_text('utf-8'), 'FAKE preserve me')
            other = root / 'user-memory'
            with self.assertRaises(ValueError):
                assets.prepare(root, other)
            self.assertFalse(other.exists())

    def test_owned_generated_assets_can_refresh_without_deleting_parent_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = self.seed(root)
            first = assets.prepare(root)
            output = root / first['generated']
            sentinel = output.parent / 'other-build.txt'
            sentinel.write_text('FAKE keep sibling', encoding='utf-8')
            (web / 'app.js').unlink()
            assets.prepare(root)
            self.assertFalse((output / 'web/app.js').exists())
            self.assertEqual(sentinel.read_text('utf-8'), 'FAKE keep sibling')

    def test_symlink_source_is_refused_without_reading_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = self.seed(root)
            private = root / 'private.txt'
            private.write_text('FAKE private target', encoding='utf-8')
            try:
                (web / 'link.js').symlink_to(private)
            except (OSError, NotImplementedError):
                self.skipTest('Host does not permit symbolic link creation')
            with self.assertRaises(ValueError):
                assets.prepare(root)

    def test_source_allowlist_accepts_native_code_and_excludes_generated_or_private_assets(self):
        for name in ('android/settings.gradle', 'android/app/src/main/AndroidManifest.xml',
                     'android/app/src/main/java/example/MainActivity.java', 'android/gradle.properties',
                     'mobile/web/index.html', 'mobile/web/manifest.webmanifest', 'mobile/web/assets/ark-pixel-OFL.txt',
                     'mobile/tests/core.test.mjs'):
            self.assertTrue(public.is_allowed(Path(name)), name)
        for name in ('android/local.properties', 'android/signing.properties', 'android/private.jks',
                     'android/.gradle/private.json', 'android/app/build/outputs/report.json',
                     'android/app/src/main/assets/backup.json', 'mobile/web/backup.json'):
            self.assertFalse(public.is_allowed(Path(name)), name)

    def test_manifest_has_only_offline_app_privileges_and_no_automatic_backup(self):
        manifest = ET.parse(ROOT / 'android/app/src/main/AndroidManifest.xml').getroot()
        ns = '{http://schemas.android.com/apk/res/android}'
        self.assertEqual(manifest.findall('uses-permission'), [])
        application = manifest.find('application')
        self.assertEqual(application.get(ns + 'allowBackup'), 'false')
        self.assertEqual(application.get(ns + 'usesCleartextTraffic'), 'false')
        activity = application.find('activity')
        self.assertEqual(activity.get(ns + 'name'), 'io.github.myflww.lovehouse.MainActivity')
        self.assertEqual(activity.get(ns + 'exported'), 'true')


class AndroidInstrumentationEvidenceTests(unittest.TestCase):
    def report(self, root, cases, **counts):
        attributes = {'tests': str(len(cases)), 'failures': '0', 'errors': '0', 'skipped': '0'}
        attributes.update({key: str(value) for key, value in counts.items()})
        suite = ET.Element('testsuite', attributes)
        for children in cases:
            case = ET.SubElement(suite, 'testcase', {'name': 'FAKE-test'})
            for child in children:
                ET.SubElement(case, child)
        ET.ElementTree(suite).write(root / 'TEST-example.xml', encoding='utf-8')

    def test_actual_passing_cases_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.report(root, [[], []])
            self.assertEqual(results.check(root)['tests'], 2)

    def test_missing_empty_or_inconsistent_reports_never_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                results.check(root)
            self.report(root, [])
            with self.assertRaises(ValueError):
                results.check(root)
            self.report(root, [[]], tests=2)
            with self.assertRaises(ValueError):
                results.check(root)

    def test_failure_or_skip_cannot_be_hidden_by_zero_summary_counts(self):
        for reason in ('failure', 'error', 'skipped'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.report(root, [[reason]])
                with self.assertRaises(ValueError):
                    results.check(root)


if __name__ == '__main__':
    unittest.main()
