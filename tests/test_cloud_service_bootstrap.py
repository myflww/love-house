"""Explicit cloud organizer bootstrapping; only synthetic keys and temporary data.

The subprocess cases deliberately leave organization disabled and use a reserved
``.invalid`` model endpoint. They never read this machine's provider variables.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock
from urllib.request import Request, ProxyHandler, build_opener
import uuid

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('love_house_cloud_launcher', ROOT / 'scripts/run_memory_service.py')
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)
ENV_NAME = 'LOVEHOUSE_TEST_ORGANIZER_SECRET'
FAKE_KEY = 'FAKE-ORGANIZER-KEY-NOT-A-REAL-PROVIDER-SECRET'


def options(**overrides):
    result = dict(organizer_key_env_name=None, organizer_base_url=None, organizer_model=None,
                  organizer_library='default', enable_organizer=False, organizer_trigger_count=20)
    result.update(overrides)
    return argparse.Namespace(**result)


def configured_options(**overrides):
    result = dict(organizer_key_env_name=ENV_NAME,
                  organizer_base_url='https://organizer-unit-test.invalid/v1', organizer_model='fake-model')
    result.update(overrides)
    return options(**result)


class ExplicitEnvironment:
    """A mapping that permits one named lookup and forbids scanning/fallback."""
    def __init__(self, value=FAKE_KEY):
        self.value = value
        self.reads = []

    def get(self, name):
        self.reads.append(name)
        if name != ENV_NAME:
            raise AssertionError('A different environment variable was requested')
        return self.value

    def __iter__(self):
        raise AssertionError('Environment enumeration is forbidden')


class CloudServiceBootstrapTests(unittest.TestCase):
    def test_default_desktop_and_headless_options_never_read_environment(self):
        environment = ExplicitEnvironment()
        self.assertIsNone(LAUNCHER.make_host_initializer(options(), environment=environment))
        self.assertEqual(environment.reads, [])

    def test_only_explicit_named_variable_is_used_as_session_key_and_defaults_disabled(self):
        environment = ExplicitEnvironment()
        host = Mock()
        initializer = LAUNCHER.make_host_initializer(configured_options(), environment=environment)
        self.assertEqual(environment.reads, [ENV_NAME])
        host.organizer_settings.assert_not_called()
        initializer(host)
        library, settings = host.organizer_settings.call_args.args
        self.assertEqual(library, 'default')
        self.assertEqual(settings, {'provider_mode': 'separate', 'base_url': 'https://organizer-unit-test.invalid/v1',
                                   'model': 'fake-model', 'api_key': FAKE_KEY, 'save_key': False,
                                   'enabled': False, 'cadence': 'batch', 'auto_trigger_count': 20})

    def test_enable_threshold_and_fixed_library_require_explicit_options(self):
        host = Mock()
        initializer = LAUNCHER.make_host_initializer(
            configured_options(enable_organizer=True, organizer_trigger_count=43, organizer_library='lib_fish'),
            environment=ExplicitEnvironment())
        initializer(host)
        library, settings = host.organizer_settings.call_args.args
        self.assertEqual(library, 'lib_fish')
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['auto_trigger_count'], 43)
        self.assertFalse(settings['save_key'])

    def test_incomplete_or_invalid_public_options_fail_before_any_secret_lookup(self):
        cases = [options(enable_organizer=True), options(organizer_key_env_name=ENV_NAME),
                 options(organizer_base_url='https://example.invalid'), options(organizer_trigger_count=21),
                 options(organizer_library='another-fish'),
                 configured_options(organizer_key_env_name='NOT A VARIABLE'),
                 configured_options(organizer_trigger_count=0), configured_options(organizer_trigger_count=501),
                 configured_options(organizer_trigger_count=True), configured_options(organizer_library='../other'),
                 configured_options(organizer_base_url='http://remote.invalid/v1'),
                 configured_options(organizer_base_url='https://'+FAKE_KEY+'@remote.invalid/v1'),
                 configured_options(organizer_base_url='https://remote.invalid/v1?key='+FAKE_KEY)]
        for args in cases:
            with self.subTest(args=args):
                environment = ExplicitEnvironment()
                with self.assertRaises(LAUNCHER.ServiceBootstrapError) as caught:
                    LAUNCHER.make_host_initializer(args, environment=environment)
                self.assertEqual(environment.reads, [])
                self.assertNotIn(FAKE_KEY, str(caught.exception))

    def test_missing_or_invalid_named_secret_has_no_fallback_or_secret_error(self):
        for value in (None, '', FAKE_KEY+'\n', FAKE_KEY+' bad', 'x'*4097):
            with self.subTest(kind=type(value).__name__):
                environment = ExplicitEnvironment(value)
                with self.assertRaises(LAUNCHER.ServiceBootstrapError) as caught:
                    LAUNCHER.make_host_initializer(configured_options(), environment=environment)
                self.assertEqual(environment.reads, [ENV_NAME])
                self.assertNotIn(FAKE_KEY, str(caught.exception))

    def test_initializer_errors_are_sanitized_and_cannot_echo_underlying_key(self):
        host = Mock()
        host.organizer_settings.side_effect = RuntimeError('backend error '+FAKE_KEY)
        initializer = LAUNCHER.make_host_initializer(configured_options(), environment=ExplicitEnvironment())
        with self.assertRaises(LAUNCHER.ServiceBootstrapError) as caught:
            initializer(host)
        self.assertNotIn(FAKE_KEY, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_real_temporary_host_holds_key_in_memory_without_writing_or_calling_model(self):
        with tempfile.TemporaryDirectory(prefix='love-house-cloud-bootstrap-unit-') as directory:
            model = Mock(side_effect=AssertionError('No model request is authorized in this test'))
            host = MemoryHost(directory, key_store=KeyStore(allow_keychain=False), organizer_transport=model)
            host.organizer.stop()
            base = 'https://'+uuid.uuid4().hex+'.invalid/v1'
            ref = host.organizer_ref('default', base, True)
            try:
                LAUNCHER.make_host_initializer(configured_options(organizer_base_url=base),
                                               environment=ExplicitEnvironment())(host)
                view = host.organizer_view('default')
                self.assertFalse(view['settings']['enabled'])
                self.assertEqual(view['settings']['auto_trigger_count'], 20)
                self.assertEqual(view['settings']['provider_id'], 'separate:session')
                self.assertEqual(view['provider']['storage'], 'session')
                self.assertTrue(view['provider']['credential_ready'])
                self.assertFalse(view['provider']['key_saved'])
                self.assertEqual(host.organizer_credential('default', view['settings'])['api_key'], FAKE_KEY)
                self.assertNotIn(FAKE_KEY, json.dumps(view))
                model.assert_not_called()
                for path in Path(directory).rglob('*'):
                    if path.is_file():
                        self.assertNotIn(FAKE_KEY.encode(), path.read_bytes(), str(path))
            finally:
                host.stop()
                host.keys.delete(ref)


@unittest.skipIf(sys.platform == 'win32', 'Cloud source launcher is POSIX, separate from Windows desktop')
class CloudServiceProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='love-house-cloud-bootstrap-process-')
        self.root = Path(self.temp.name)
        self.data = self.root / 'private-data'
        self.process = None
        self.log = None
        self.starts = 0
        self.base_url = 'https://'+uuid.uuid4().hex+'.invalid/v1'
        self.client = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def command(self, *, inject):
        command = [sys.executable, str(ROOT / 'scripts/run_memory_service.py'), '--data-dir', str(self.data), '--diagnose-startup']
        if inject:
            command += ['--organizer-key-env-name', ENV_NAME, '--organizer-base-url', self.base_url,
                        '--organizer-model', 'synthetic-cloud-model']
        return command

    def start(self, *, inject=True):
        self.starts += 1
        self.log_path = self.root / ('process-'+str(self.starts)+'.log')
        self.log = self.log_path.open('wb')
        # This environment is constructed from literals. No current provider
        # credential or another application's process configuration is read.
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
        if inject:
            environment[ENV_NAME] = FAKE_KEY
        self.process = subprocess.Popen(self.command(inject=inject), cwd=self.root, stdout=self.log,
                                        stderr=subprocess.STDOUT, env=environment)
        ready = self.data / '.runtime/app.json'
        deadline = time.monotonic()+15
        while not ready.exists() and self.process.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        if not ready.exists():
            self.fail('Disposable cloud process failed: '+self.log_path.read_text())
        self.ready = json.loads(ready.read_text())
        self.base = 'http://127.0.0.1:'+str(self.ready['controller_port'])

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                raise
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def get(self, path):
        request=Request(self.base+path)
        if path=='/api/agent/sources':
            with self.client.open(self.base+'/',timeout=5) as page:
                request.add_header('Cookie',page.headers['Set-Cookie'].split(';')[0])
        with self.client.open(request, timeout=5) as response:
            return json.load(response)

    def assert_private_key_not_on_disk_or_argv(self):
        self.assertNotIn(FAKE_KEY, ' '.join(self.command(inject=True)))
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn(FAKE_KEY.encode(), path.read_bytes(), str(path))

    def test_process_manager_can_reinject_each_restart_but_service_never_persists_key(self):
        for _ in range(2):
            self.start(inject=True)
            self.assertEqual(self.get('/api/graph')['nodes'], [])
            self.assertEqual(len(self.get('/api/libraries')['libraries']), 1)
            self.assertEqual(self.get('/api/agent/sources')['sources'], [])
            view = self.get('/api/organizer')
            self.assertFalse(view['settings']['enabled'])
            self.assertEqual(view['settings']['auto_trigger_count'], 20)
            self.assertEqual(view['provider']['storage'], 'session')
            self.assertTrue(view['provider']['credential_ready'])
            self.assertFalse(view['provider']['key_saved'])
            self.assertEqual(view['status']['calls_24h'], 0)
            self.stop()
            self.assertFalse((self.data / '.runtime/app.json').exists())
            self.assert_private_key_not_on_disk_or_argv()
        # Saved public settings do not resurrect the secret in a third process.
        self.start(inject=False)
        view = self.get('/api/organizer')
        self.assertFalse(view['settings']['enabled'])
        self.assertFalse(view['provider']['credential_ready'])
        self.assertEqual(view['status']['calls_24h'], 0)
        self.stop()
        self.assert_private_key_not_on_disk_or_argv()

    def test_injected_initializer_does_not_bypass_existing_single_writer_guard(self):
        self.start()
        ready_bytes = (self.data / '.runtime/app.json').read_bytes()
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', ENV_NAME: FAKE_KEY}
        result = subprocess.run(self.command(inject=True), cwd=self.root, capture_output=True,
                                timeout=10, env=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(FAKE_KEY.encode(), result.stdout+result.stderr)
        self.assertEqual((self.data / '.runtime/app.json').read_bytes(), ready_bytes)
        self.assertTrue(self.get('/api/health')['ok'])
        self.assert_private_key_not_on_disk_or_argv()


if __name__ == '__main__':
    unittest.main()
