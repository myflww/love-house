"""Configuration badges use scoped metadata, with no provider or OS credential access."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nkb.errors import ValidationError
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost


class MemoryCredentials:
    def __init__(self):
        self.values = {}
        self.readable = True

    def call(self, op, account, value=None):
        if not self.readable:
            return {'ok': False}
        if op == 'set':
            self.values[account] = value
            return {'ok': True}
        if op == 'get':
            return {'ok': True, 'value': self.values.get(account, '')}
        raise AssertionError('Unexpected credential action')


class MemoryKeychainStore(KeyStore):
    """Use the normal KeyStore metadata semantics without invoking the OS."""
    def __init__(self, backend):
        super().__init__(allow_source_build=False)
        self.backend = backend

    def _call(self, op, account, value=None, *, allow_build=False):
        return self.backend.call(op, account, value)


class OrganizerConfigurationStatusTests(unittest.TestCase):
    def setUp(self):
        self.session = patch('nkb.service.credentials._SESSION', {})
        self.session_values = self.session.start()
        self.temp = tempfile.TemporaryDirectory()
        self.backend = MemoryCredentials()
        self.calls = []
        self.host = None
        self.start()

    def start(self):
        if self.host:
            self.host.stop()
        def offline_transport(*args, **kwargs):
            self.calls.append('forbidden')
            raise AssertionError('A status check must never call a provider')
        self.host = MemoryHost(Path(self.temp.name), key_store=MemoryKeychainStore(self.backend),
                               organizer_transport=offline_transport)
        self.host.organizer.stop()

    def tearDown(self):
        self.host.stop()
        self.temp.cleanup()
        self.session.stop()

    def configure(self, library='default', **overrides):
        return self.host.organizer_settings(library, {'enabled': False, 'provider_mode': 'separate',
            'base_url': 'https://example.invalid/v1', 'model': 'synthetic-organizer-model',
            'api_key': 'FAKE-CONFIG-STATUS-KEY', 'save_key': True, **overrides})

    def test_fresh_saved_and_other_library_are_independent_without_any_call(self):
        fresh = self.host.organizer_view('default')
        self.assertEqual(fresh['configuration']['state'], 'not_configured')
        saved = self.configure()
        self.assertEqual(saved['library_id'], 'default')
        self.assertEqual(saved['configuration'], {'configured': True, 'state': 'saved',
            'scope': 'library', 'network_verified': False})
        self.assertTrue(saved['provider']['key_saved'])
        other = self.host.manager.create_library('Synthetic second library')['id']
        self.assertEqual(self.host.organizer_view(other)['configuration']['state'], 'not_configured')
        self.configure(other, api_key='', save_key=False)
        self.assertEqual(self.host.organizer_view(other)['configuration']['state'], 'credential_missing')
        self.assertEqual(self.host.organizer_view('default')['configuration']['state'], 'saved')
        self.assertEqual(self.calls, [])
        self.assertNotIn('FAKE-CONFIG-STATUS-KEY', json.dumps(saved))

    def test_saved_configuration_survives_reload_but_missing_or_locked_credential_is_not_ready(self):
        self.configure()
        self.start()
        self.assertEqual(self.host.organizer_view('default')['configuration']['state'], 'saved')
        self.backend.readable = False
        status = self.host.organizer_view('default')
        self.assertEqual(status['configuration']['state'], 'credential_missing')
        self.assertTrue(status['configuration']['configured'])
        self.assertFalse(status['provider']['model_ready'])
        self.assertEqual(self.calls, [])

    def test_session_configuration_reports_reentry_required_after_process_credentials_are_cleared(self):
        self.assertEqual(self.configure(save_key=False)['configuration']['state'], 'session_only')
        self.session_values.clear()  # Simulate the new process's empty session store.
        self.start()
        status = self.host.organizer_view('default')
        self.assertEqual(status['configuration']['state'], 'credential_missing')
        self.assertEqual(status['provider']['model'], 'synthetic-organizer-model')
        self.assertFalse(status['provider']['credential_ready'])
        self.assertEqual(self.calls, [])

    def test_invalid_save_cannot_promote_or_replace_a_confirmed_configuration(self):
        before = self.configure()
        with self.assertRaises(ValidationError):
            self.configure(model='invalid-new-model', batch_size=0)
        self.assertEqual(self.host.organizer_view('default'), {k: v for k, v in before.items()
                                                            if k != 'resumed_configuration_jobs'})
        self.assertEqual(self.calls, [])

    def test_revoked_missing_and_foreign_connections_fail_closed(self):
        own = self.host.new_connection({'name': 'Synthetic model', 'host': 'api', 'library_id': 'default'})['connection']['id']
        self.host.providers.save(own, {'model': 'synthetic', 'api_key': 'FAKE-CONNECTION-KEY'})
        view = self.host.organizer_settings('default', {'enabled': False, 'provider_mode': 'connection', 'connection_id': own})
        self.assertEqual(view['configuration']['state'], 'saved')
        with self.host.connections.db() as db:
            db.execute('UPDATE connections SET revoked=1 WHERE id=?', (own,))
        view = self.host.organizer_view('default')
        self.assertEqual(view['configuration']['state'], 'connection_unavailable')
        self.assertFalse(view['provider']['credential_ready'])
        other = self.host.manager.create_library('Synthetic foreign library')['id']
        foreign = self.host.new_connection({'name': 'Foreign', 'host': 'api', 'library_id': other})['connection']['id']
        from nkb.organizer import save_profile
        for connection in (foreign, 'missing-synthetic-connection'):
            self.host.transact('default', lambda brain: save_profile(brain, provider_id='connection:' + connection))
            view = self.host.organizer_view('default')
            self.assertEqual(view['configuration']['state'], 'connection_unavailable')
            self.assertFalse(view['provider']['model_ready'])
        self.assertEqual(self.calls, [])


class OrganizerConfigurationUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is optional for UI checks')
    def test_scoped_labels_and_async_save_read_actions(self):
        result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap',
            str(Path(__file__).parent / 'js/organizer-configuration-ui.test.cjs')],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# pass 10', result.stdout)


if __name__ == '__main__':
    unittest.main()
