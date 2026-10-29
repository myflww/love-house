from pathlib import Path
import importlib.util
import json
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'public_release', Path(__file__).resolve().parents[1] / 'scripts/prepare_public_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PublicReleaseTests(unittest.TestCase):
    def seed(self, root):
        for name, value in {
            'LICENSE': '# PolyForm Noncommercial License 1.0.0\n',
            'NOTICE': 'Required Notice: Copyright 2026 Example\n',
            'THIRD_PARTY_NOTICES.md': 'Upstream terms retained',
            'README.md': 'Example release', 'pyproject.toml': '[project]\nname="example"\n',
            'nkb/__init__.py': 'value = 1\n',
        }.items():
            p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)

    def test_allowlist_keeps_required_source_and_upstream_terms_but_excludes_user_outputs(self):
        allowed = ['nkb/core/brain.py', 'nkb/service/harness/dist/configure.js',
                   'extensions/deepseek-harness/dist/index.js', 'assets/fonts/ark-pixel-OFL.txt',
                   'assets/ui/toolbar-icons/fit.png', 'NOTICE', 'nkb/viz/art/LICENSE.three']
        denied = ['reports/installed-before.json', 'outputs/rollback/capture.sqlite3',
                  'data/user.brain.json', 'nkb/demo.brain.json', 'docs/assets/screenshot.png',
                  'references/open-source/source.js', 'extensions/deepseek-harness/node_modules/x/index.js',
                  'extensions/deepseek-harness/dist/index.js.map', '.env', '爱之屋.html']
        for p in allowed: self.assertTrue(release.is_allowed(Path(p)), p)
        for p in denied: self.assertFalse(release.is_allowed(Path(p)), p)

    def test_public_banner_and_windows_build_sources_are_allowed_but_active_svg_is_blocked(self):
        for path in ('assets/branding/project-banner.svg', 'desktop/windows-installer.iss',
                     'desktop/LoveHouse.spec', 'scripts/install.ps1', 'assets/branding/love-house.ico'):
            self.assertTrue(release.is_allowed(Path(path)), path)
        good = '<svg xmlns="http://www.w3.org/2000/svg"><title>Love House</title><rect fill="#fff" width="10" height="10"/></svg>'
        self.assertFalse(release.scan_bytes(Path('assets/banner.svg'), good.encode()))
        for fragment in ('<script>alert(1)</script>', '<foreignObject/>',
                         '<image href="https://example.test/private.png"/>',
                         '<use href="https://example.test/image.svg#id"/>',
                         '<rect onload="alert(1)"/>', '<style>@import "https://example.test/a.css";</style>',
                         '<rect fill="url(https://example.test/a.svg)"/>',
                         '<rect style="fill:red"/>', '<animate attributeName="href"/>'):
            bad = '<svg xmlns="http://www.w3.org/2000/svg">' + fragment + '</svg>'
            findings = release.scan_bytes(Path('assets/banner.svg'), bad.encode())
            self.assertIn('unsafe-svg', {f['category'] for f in findings}, fragment)

    def test_svg_entity_and_external_base_cannot_bypass_static_policy(self):
        for text in ('<!DOCTYPE svg [<!ENTITY x "boom">]><svg xmlns="http://www.w3.org/2000/svg"/>',
                     '<svg xmlns="http://www.w3.org/2000/svg" xml:base="https://example.test/"><use href="#id"/></svg>',
                     '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="u\\72l(https://example.test/a.svg)"/></svg>'):
            self.assertTrue(release.unsafe_svg(text))

    def test_secret_findings_never_include_value_and_home_path_is_rejected(self):
        value = 'sk-' + ''.join(chr(65 + i % 26) for i in range(45))
        content = ('key = "' + value + '"\n' + '/Users/' + 'private-builder/project/file.py').encode()
        findings = release.scan_bytes(Path('nkb/example.py'), content, home=Path('/Users') / 'private-builder')
        self.assertEqual({f['category'] for f in findings}, {'model-key', 'developer-home-path'})
        self.assertNotIn(value, json.dumps(findings))
        self.assertTrue(all(set(f) == {'path', 'line', 'category'} for f in findings))

    def test_synthetic_placeholder_is_allowed_but_high_entropy_literal_token_is_not(self):
        safe = b'{"api_key":"FAKE-NOT-A-REAL-KEY-123456789"}'
        actual = json.dumps({'token': ''.join(('AbcDef012345', '6789-_Xyz', 'RandomValue0987654321'))}).encode()
        self.assertFalse(release.scan_bytes(Path('tests/example.py'), safe))
        self.assertEqual(release.scan_bytes(Path('nkb/bad.json'), actual)[0]['category'], 'literal-credential')

    def test_prepare_copies_clean_source_with_relative_hashed_manifest_and_no_private_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base / 'source'; source.mkdir(); self.seed(source)
            for name in ('reports/private.json', 'data/personal.brain.json', '.env', 'dist/runtime/private.txt'):
                p = source / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('PRIVATE')
            destination = base / 'public'; result = release.prepare(source, destination)
            self.assertTrue(result['ok'])
            self.assertFalse((destination / '.env').exists())
            self.assertFalse((destination / 'reports').exists())
            manifest = json.loads((destination / 'PUBLIC_SOURCE_MANIFEST.json').read_text())
            self.assertEqual(len(manifest['files']), 6)
            self.assertTrue(all(not Path(f['path']).is_absolute() and len(f['sha256']) == 64 for f in manifest['files']))
            self.assertFalse(release.collect(destination, staged=True)[1])
            self.assertFalse(release.verify_manifest(destination, release.collect(destination, staged=True)[0]))
            (destination / 'README.md').write_text('tampered release')
            self.assertEqual(release.verify_manifest(destination, release.collect(destination, staged=True)[0])[0]['category'], 'manifest-integrity')
            with self.assertRaises(ValueError): release.prepare(source, destination)

    def test_staged_extra_private_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.seed(root)
            (root / 'brain.json').write_text('PRIVATE')
            findings = release.collect(root, staged=True)[1]
            self.assertIn('unapproved-file', {f['category'] for f in findings})

    def test_symlink_is_not_followed_when_platform_allows_link_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.seed(root)
            (root / 'brain.json').write_text('PRIVATE')
            try:
                (root / 'nkb/link.py').symlink_to(root / 'brain.json')
            except (OSError, NotImplementedError):
                self.skipTest('This runner does not grant symbolic-link creation permission')
            findings = release.collect(root, staged=True)[1]
            self.assertIn('symlink', {f['category'] for f in findings})

    def test_prepare_fails_before_copy_on_source_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base / 'source'; source.mkdir(); self.seed(source)
            token = ''.join(('MixedAbc123', 'ExtraZyx987', 'CredentialValue'))
            (source / 'nkb/config.json').write_text(json.dumps({'access_token': token}))
            destination = base / 'public'; result = release.prepare(source, destination)
            self.assertFalse(result['ok']); self.assertFalse(destination.exists())


if __name__ == '__main__': unittest.main()
