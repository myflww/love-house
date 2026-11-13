"""Application upgrades refresh only existing, owned Harness profile copies."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / 'extensions/deepseek-harness'
spec = importlib.util.spec_from_file_location('owned_harness_refresh', EXTENSION / 'configure.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class HarnessRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='owned-harness-upgrade-')
        self.root = Path(self.temporary.name)
        self.app = self.root / 'Harness.app'
        (self.app / 'Contents').mkdir(parents=True)
        (self.app / 'Contents/Info.plist').write_bytes(
            plistlib.dumps({'CFBundleShortVersionString': '0.2.1-rc.5'}))
        self.profile = self.root / 'profile'
        self.profile.mkdir()
        (self.profile / 'cordis.yml').write_text('[]\n', encoding='utf-8')
        self.patch = self.profile / 'cordis.patch.yml'
        self.original = '# unrelated user entry\n- insert: [{"id":"other","name":"other-plugin","config":{"keep":"opaque"}}]\n'
        self.patch.write_text(self.original, encoding='utf-8')
        self.options = {'app_path': str(self.app), 'profile_dir': str(self.profile)}
        self.connection = {'config': {'connectionId': 'owned-A', 'connectionToken': 'fixture-not-a-real-token',
            'libraryId': 'library-a', 'sessionScope': 'fixed-window-a'}, 'host_options': self.options}

    def tearDown(self):
        self.temporary.cleanup()

    def install(self, connection=None):
        return helper.configure(connection or self.connection, apply=True)

    def old_assets(self, installation):
        for name in ('index.js', 'configure.js', 'proxy.js', 'THIRD_PARTY_LICENSES.txt'):
            (installation / name).write_text('// previous bundled adapter fixture\n', encoding='utf-8')

    def test_refresh_updates_owned_copies_once_without_rewriting_private_binding_or_outbox(self):
        installed = self.install()
        private = Path(installed['connection_file'])
        installation = private.parent
        self.old_assets(installation)
        # Pausing is a private source decision and must survive an application
        # update even if the controller currently reports an enabled connection.
        settings = json.loads(private.read_text('utf-8'))
        settings['enabled'] = False
        private.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
        private_before = private.read_bytes()
        patch_before = self.patch.read_bytes()
        outbox = installation / 'retained-outbox.event.json'
        outbox.write_bytes(b'{"fixture":"pending durable source event"}')
        result = helper.refresh_owned_installation(self.connection)
        self.assertTrue(result['refreshed'])
        self.assertEqual(len(result['assets_updated']), 4)
        self.assertTrue(result['requires_harness_reload'])
        self.assertFalse(result['host_proof_updated'])
        self.assertEqual(private.read_bytes(), private_before)
        self.assertEqual(self.patch.read_bytes(), patch_before)
        self.assertEqual(outbox.read_bytes(), b'{"fixture":"pending durable source event"}')
        for name in result['assets_updated']:
            self.assertEqual((installation / name).read_bytes(), (EXTENSION / 'dist' / name).read_bytes())
        again = helper.refresh_owned_installation(self.connection)
        self.assertEqual(again['status'], 'current')
        self.assertFalse(again['refreshed'])
        self.assertNotIn('fixture-not-a-real-token', json.dumps(result))

    def test_removed_customized_or_rebound_installation_is_never_reenrolled(self):
        installed = self.install()
        private = Path(installed['connection_file'])
        installation = private.parent
        managed = self.patch.read_bytes()
        private_before = private.read_bytes()
        for change in ('removed', 'customized', 'different-private-token', 'different-owner'):
            with self.subTest(change=change):
                self.patch.write_bytes(managed)
                private.write_bytes(private_before)
                (installation / 'managed.json').write_text(json.dumps({'managed_by': helper.OWNER}))
                self.old_assets(installation)
                if change == 'removed':
                    self.patch.write_text(self.original, encoding='utf-8')
                elif change == 'customized':
                    self.patch.write_bytes(managed.replace(b'file:///', b'file:///customized-'))
                elif change == 'different-private-token':
                    settings = json.loads(private_before)
                    settings['connection_token'] = 'another-generation-fixture'
                    private.write_text(json.dumps(settings))
                else:
                    (installation / 'managed.json').write_text('{"managed_by":"other"}')
                patch_before = self.patch.read_bytes()
                binding_before = private.read_bytes()
                result = helper.refresh_owned_installation(self.connection)
                self.assertFalse(result['refreshed'])
                self.assertEqual(self.patch.read_bytes(), patch_before)
                self.assertEqual(private.read_bytes(), binding_before)
                self.assertIn('previous bundled adapter', (installation / 'index.js').read_text())

    def test_crlf_managed_entry_keeps_exact_bytes_and_refreshes_idempotently(self):
        installed = self.install()
        self.patch.write_bytes(self.patch.read_bytes().replace(b'\n', b'\r\n'))
        before = self.patch.read_bytes()
        self.old_assets(Path(installed['connection_file']).parent)
        self.assertTrue(helper.refresh_owned_installation(self.connection)['refreshed'])
        self.assertEqual(self.patch.read_bytes(), before)
        self.assertFalse(helper.refresh_owned_installation(self.connection)['refreshed'])
        self.assertEqual(self.patch.read_bytes(), before)

    @unittest.skipUnless((EXTENSION / 'node_modules/@deepseek-ai/dsh-agent/package.json').is_file(),
                         'real SDK fixtures installed by Harness compatibility CI')
    def test_upgrade_adds_current_capability_proof_to_existing_entry_and_keeps_other_settings(self):
        installed = self.install()
        private = Path(installed['connection_file'])
        private_before = private.read_bytes()
        # Simulate an existing user option in this managed plugin only.
        text = self.patch.read_text('utf-8')
        self.patch.write_text(text.replace('"host_version": "0.2.1-rc.5"',
            '"timeout_ms": 9876, "host_version": "0.2.1-rc.5"'), encoding='utf-8')
        capabilities = json.loads(helper.CAPABILITY_FILE.read_text('utf-8'))
        modules = self.app / 'Contents/Resources/app/dsh/node_modules'
        for name, contract in capabilities['packages'].items():
            source = EXTENSION / 'node_modules' / name
            target = modules / name
            target.mkdir(parents=True)
            metadata = json.loads((source / 'package.json').read_text('utf-8'))
            for filename in {metadata['main'], *contract['files'], *contract['runtime_files']}:
                (target / filename).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / filename, target / filename)
            metadata['version'] = '99.2.0-compatible-future'
            (target / 'package.json').write_text(json.dumps(metadata), encoding='utf-8')
        cordis = modules / '@deepseek-ai/cordis/package.json'
        cordis.parent.mkdir(parents=True)
        cordis.write_text('{"name":"@deepseek-ai/cordis","version":"4.1.0"}')
        result = helper.refresh_owned_installation(self.connection)
        self.assertTrue(result['host_proof_updated'])
        lines = self.patch.read_text('utf-8').splitlines()
        entry = json.loads(next(line[len('- insert: '):] for line in lines if 'connection_file' in line))[0]
        self.assertEqual(entry['config']['host_version'], '99.2.0-compatible-future')
        self.assertEqual(entry['config']['timeout_ms'], 9876)
        self.assertEqual(entry['config']['host_contract']['contract_id'], capabilities['contract_id'])
        self.assertTrue(self.patch.read_text('utf-8').startswith(self.original))
        self.assertEqual(private.read_bytes(), private_before)
        self.assertFalse(helper.refresh_owned_installation(self.connection)['refreshed'])
        self.assertIn('0.2.2-rc.2', helper.detect(self.app)['supported_versions'])
        # Follow a replacement only once the saved versioned installation has
        # disappeared; the profile and private connection stay identical.
        moved = self.root / 'replacement official Harness.app'
        self.app.rename(moved)
        with patch.object(helper, '_app_candidates', return_value=iter([moved])):
            followed = helper.refresh_owned_installation(self.connection)
        self.assertTrue(followed['host_proof_updated'])
        self.assertEqual(private.read_bytes(), private_before)
        self.assertIn(str(moved).replace('\\', '\\\\'), self.patch.read_text('utf-8'))

    def test_new_controller_boot_refreshes_installed_bindings_keeps_pause_revoke_and_window_boundaries(self):
        data = self.root / 'data'
        host = MemoryHost(data, adapter_options=self.options, key_store=KeyStore(allow_keychain=False))
        installed = {}
        try:
            other = host.manager.create_library('another isolated library')['id']
            for name, library, window in [('A', 'default', 'window-a'), ('B', other, 'window-b'),
                                           ('revoked', other, 'revoked-window'), ('removed', 'default', 'removed-window')]:
                created = host.new_connection({'name': name, 'host': 'agent', 'library_id': library,
                                               'session_scope': window})
                cid = created['connection']['id']
                configured = helper.configure(host.harness_connection_config(cid), apply=True)
                host.connections.configured(cid, host_options=self.options)
                installed[name] = (cid, configured)
            paused_cid = installed['B'][0]
            helper.set_enabled(host.harness_connection_config(paused_cid), False)
            host.connections.toggle(paused_cid, False)
            revoked_cid = installed['revoked'][0]
            helper.set_enabled(host.harness_connection_config(revoked_cid), False)
            host.connections.toggle(revoked_cid, False, disconnect=True)
            removed = installed['removed'][1]['overlay']
            self.patch.write_text(self.patch.read_text('utf-8').replace(removed, ''), encoding='utf-8')
            uninstalled = host.new_connection({'name': 'manual MCP only', 'host': 'agent', 'library_id': 'default'})['connection']['id']
            before = {name: host.connections.get(cid, secret=True) for name, (cid, _) in installed.items()}
            private_before = {name: Path(configured['connection_file']).read_bytes() for name, (_, configured) in installed.items()}
            patch_before = self.patch.read_bytes()
            self.old_assets(Path(installed['A'][1]['connection_file']).parent)
        finally:
            host.stop()
        upgraded = MemoryHost(data, adapter_options=self.options, key_store=KeyStore(allow_keychain=False))
        try:
            self.assertTrue(upgraded.harness_refresh_results[installed['A'][0]]['refreshed'])
            self.assertEqual(upgraded.harness_refresh_results[installed['B'][0]]['status'], 'current')
            self.assertNotIn(revoked_cid, upgraded.harness_refresh_results)
            self.assertNotIn(uninstalled, upgraded.harness_refresh_results)
            self.assertEqual(upgraded.harness_refresh_results[installed['removed'][0]]['status'], 'entry_missing')
            self.assertEqual(self.patch.read_bytes(), patch_before)
            for name, (cid, configured) in installed.items():
                current = upgraded.connections.get(cid, secret=True)
                for field in ('token', 'library_id', 'session_scope', 'bound_session_id', 'enabled', 'revoked', 'configured_at'):
                    self.assertEqual(current[field], before[name][field], (name, field))
                self.assertEqual(Path(configured['connection_file']).read_bytes(), private_before[name])
            private_path = Path(installed['A'][1]['connection_file'])
            self.assertEqual((private_path.parent / 'index.js').read_bytes(), (EXTENSION / 'dist/index.js').read_bytes())
        finally:
            upgraded.stop()
