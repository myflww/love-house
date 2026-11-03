"""Offline contracts for native acceptance; actual AppKit execution belongs to macOS CI."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SWIFT = (ROOT / 'desktop/AtlasApp.swift').read_text('utf-8')


class MacOSNativeSmokeContracts(unittest.TestCase):
    def test_native_requests_use_webview_session_only_for_the_exact_controller(self):
        helper = SWIFT.split('private func smokeData(', 1)[1].split('private func writeSmokeReport', 1)[0]
        self.assertIn('url.scheme == "http"', helper)
        self.assertIn('url.host == "127.0.0.1"', helper)
        self.assertIn('url.port == base.port', helper)
        self.assertIn('httpCookieStore.getAllCookies', helper)
        self.assertIn('$0.name == "LoveHouseUI"', helper)
        self.assertIn('$0.domain == "127.0.0.1"', helper)
        self.assertIn('management: token == nil', SWIFT)
        self.assertNotIn('URLSession.shared.data(from:packageURL)', SWIFT)

    def test_current_adapter_and_product_version_are_used_without_legacy_persona_claims(self):
        self.assertEqual(SWIFT.count('LoveHouse-AstrBot-0.3.0-experimental.zip'), 3)
        self.assertNotRegex(SWIFT, r'LoveHouse-AstrBot-0\.[12]\.0')
        self.assertIn('self.smokeVersion = health["version"]', SWIFT)
        self.assertIn('api/persona/import', SWIFT)
        self.assertIn('Chat material fabricated manual or model-learned persona', SWIFT)
        self.assertIn('persona["formed_traits"]', SWIFT)

    def test_acceptance_report_is_written_after_isolated_backend_cleanup(self):
        terminated = SWIFT.split('func applicationWillTerminate', 1)[1].split('private func buildMenu', 1)[0]
        self.assertLess(terminated.index('stopServer()'), terminated.index('writeSmokeReport()'))
        self.assertLess(terminated.index('removeItem(at: smokeDirectory)'), terminated.index('writeSmokeReport()'))
        report = SWIFT.split('private func writeSmokeReport', 1)[1].split('private static let smokeUpdateFixture', 1)[0]
        for field in ('"ok"', '"version"', '"process_complete"', '"isolation"', '"steps"'):
            self.assertIn(field, report)
        for secret in ('smokeConnectionToken', 'HTTPCookie', 'assistant_reply'):
            self.assertNotIn(secret, report)

    @unittest.skipUnless(shutil.which('node'), 'Node optional')
    def test_native_update_fixture_calls_fresh_check_but_never_replaces_memory_routes(self):
        fixture = re.search(r'private static let smokeUpdateFixture = #"""\n(.*?)\n    """#', SWIFT, re.S).group(1)
        # Execute the exact embedded fixture, preserving actual Request/Response
        # behavior. No server, model credential or external network is involved.
        script = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const calls=[],window={fetch:async(...args)=>{calls.push(args);return new Response('{"real_local":true}')}};
const ctx={window,URL,Response,location:{href:'http://127.0.0.1:8768/',origin:'http://127.0.0.1:8768'}};
vm.runInNewContext(FIXTURE,ctx);
(async()=>{
 let status=await(await window.fetch('/api/updates')).json();assert.equal(status.available,false);
 status=await(await window.fetch('/api/updates/check',{method:'POST'})).json();
 assert.equal(status.available,true);assert.equal(status.release.version,'99.0.0');
 assert.equal(status.release.asset_url.endsWith('LoveHouse-macOS-arm64.zip'),true);
 assert.equal(window.__nativeSmokeUpdates.calls.filter(p=>p==='/api/updates/check').length,1);
 await window.fetch('/api/organizer/preview',{method:'POST'});await window.fetch('https://other.invalid/api/updates');
 assert.equal(calls.length,2);assert.equal(calls[0][0],'/api/organizer/preview');
})().catch(e=>{console.error(e);process.exitCode=1});
'''.replace('FIXTURE', json.dumps(fixture))
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node optional')
    def test_every_native_async_javascript_probe_parses(self):
        probes = re.findall(r'callAsyncJavaScript\("""\n(.*?)\n\s*""", arguments:', SWIFT, re.S)
        self.assertGreaterEqual(len(probes), 3)
        script = 'const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;for(const source of '+json.dumps(probes)+'){new AsyncFunction(source)}'
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
