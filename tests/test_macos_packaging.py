"""Portable checks for the Mac build boundaries; actual Swift/WKWebView runs on Mac CI."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('macos_builder_contract', 'scripts/build_macos.py')
runtime = load('macos_runtime_contract', 'scripts/fetch_macos_runtime.py')


class MacPackagingTests(unittest.TestCase):
    def test_runtime_pin_matches_the_existing_redistribution_provenance(self):
        proof = runtime.verify_provenance()
        self.assertEqual(proof['python_version'], '3.12.14')
        self.assertEqual(proof['target_triple'], 'aarch64-apple-darwin')
        self.assertEqual(proof['archive_sha256'], runtime.SHA256)

    def test_bad_archive_never_reaches_extraction_or_creates_a_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'untrusted.tar.zst'
            archive.write_bytes(b'not the approved runtime')
            with patch.object(runtime.subprocess, 'run', side_effect=AssertionError('Do not extract invalid bytes')):
                with self.assertRaisesRegex(ValueError, 'SHA256'):
                    runtime.fetch(root / 'output', archive=archive)
            self.assertFalse((root / 'output').exists())

    def test_runtime_environment_drops_developer_python_and_dyld_overrides(self):
        with patch.dict(builder.os.environ, {'PYTHONPATH':'FAKE', 'PYTHONSTARTUP':'FAKE', 'PYTHONUSERBASE':'FAKE',
                                             'DYLD_LIBRARY_PATH':'FAKE', 'PYTHONHOME':'FAKE'}):
            env = builder.clean_environment(Path('/synthetic/bundled-python'))
        self.assertEqual(env['PYTHONHOME'], str(Path('/synthetic/bundled-python')))
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')
        for key in ('PYTHONPATH','PYTHONSTARTUP','PYTHONUSERBASE','DYLD_LIBRARY_PATH'):
            self.assertNotIn(key, env)

    def test_real_http_session_cookie_is_used_only_for_management_not_bearer_events(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Set-Cookie', 'LoveHouseUI=FAKE-LOCAL-MANAGEMENT; Path=/; HttpOnly; SameSite=Strict')
                    self.end_headers()
                    self.wfile.write(b'<html></html>')
                    return
                self.respond()

            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                self.respond()

            def respond(self):
                observed.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'ok':True}).encode())

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            client = builder.SmokeController(base)
            self.assertTrue(client.api('/api/connections')['ok'])
            self.assertTrue(client.api('/api/connections/synthetic/events', {}, library='synthetic-library',
                                       credential='FAKE-SOURCE-TOKEN')['ok'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertIn('LoveHouseUI=', observed[0]['Cookie'])
        self.assertNotIn('Cookie', observed[1])
        self.assertEqual(observed[1]['Authorization'], 'Bearer FAKE-SOURCE-TOKEN')
        self.assertEqual(observed[1]['X-Nkb-Library'], 'synthetic-library')
        self.assertEqual(observed[1]['Origin'], base)

    def test_single_window_builder_sequence_uses_real_controller_hooks_and_restart(self):
        from nkb.service.credentials import KeyStore
        from nkb.service.host import MemoryHost, make_controller
        from nkb.service.httpd import LoopbackHTTPServer

        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            state = {}

            def start():
                host = MemoryHost(data, key_store=KeyStore(allow_keychain=False))
                server = LoopbackHTTPServer(('127.0.0.1', 0), make_controller(host))
                host.controller_port = server.server_port
                thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.01})
                thread.start()
                state.update(host=host, server=server, thread=thread)
                runtime = data/'.runtime'
                runtime.mkdir(exist_ok=True)
                (runtime/'app.json').write_text(json.dumps({'pid':os.getpid(), 'controller_port':server.server_port,
                                                           'service_version':'0.4.0'}), encoding='utf-8')
                state['controller'] = builder.SmokeController(f'http://127.0.0.1:{server.server_port}')

            def stop():
                if not state.get('server'):
                    return
                state['server'].shutdown()
                state['server'].server_close()
                state['thread'].join(timeout=10)
                self.assertFalse(state['thread'].is_alive())
                state['host'].stop()
                state['server'] = None

            def api(path, body=None, library=None):
                return state['controller'].api(path, body, library)

            def execute(command, payload):
                result = subprocess.run([command['command'], *command['args']], input=payload,
                                        env={**os.environ, **command['env']}, cwd=directory,
                                        capture_output=True, text=True, encoding='utf-8', timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertEqual(result.stderr, '')
                return json.loads(result.stdout)

            try:
                start()
                builder.smoke_single_window(api, execute, start, stop, data)
            finally:
                stop()

    def test_current_version_and_plugin_resource_match_the_core_and_actual_package(self):
        from nkb._version import __version__
        self.assertEqual(builder.project_version(), __version__)
        metadata = (ROOT/'extensions/astrbot-love-house/metadata.yaml').read_text('utf-8')
        import re
        version = re.search(r'^version:\s*v?([^\s]+)', metadata, re.M).group(1)
        self.assertEqual(builder.ASTRBOT_PACKAGE, 'LoveHouse-AstrBot-' + version + '-experimental.zip')


if __name__ == '__main__':
    unittest.main()
