"""Real shared-engine HTTP, scoped credentials, and lossless migration gates."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android/app/src/main/python"))
sys.path.insert(0, str(ROOT / "scripts"))
import lovehouse_android as android
import prepare_android_engine as packaging
from nkb.service.updates import select_release, target_platform
from nkb._version import __version__


class Vault:
    """A synthetic Java protocol substitute; no system credentials are read."""
    def __init__(self): self.values = {}
    def call(self, op, account, value):
        if op == "set": self.values[account] = value
        elif op == "delete": self.values.pop(account, None)
        return json.dumps({"ok": True, **({"value": self.values.get(account, "")} if op == "get" else {})})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "love-house-engine"
        self.vault = Vault()
        self.url = json.loads(android.start(self.root, self.vault, port=0))["url"]
    def tearDown(self):
        android.stop()
        self.temporary.cleanup()
    def request(self, path, payload=None, management=False, extra_headers=None):
        headers = {"Content-Type": "application/json"}
        headers.update(extra_headers or {})
        if management: headers["X-LoveHouse-Management"] = android._runtime["host"].management_token
        request = urllib.request.Request(self.url.rstrip("/") + path, headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None)
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10)

    def test_same_core_root_cookie_and_foreign_management_rejected(self):
        self.assertEqual(json.loads(android.start(self.root, self.vault))["url"], self.url)
        with self.assertRaises(ValueError): android.start(self.root / "other", self.vault)
        with self.request("/",management=True) as response:
            html = response.read().decode()
            self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn('id="personaPanel"', html)
        self.assertIn('id="organizerPanel"', html)
        self.assertIn('/android-native.js', html)
        with self.request('/android-native.js',management=True) as response:
            self.assertIn('手机接入说明', response.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/api/connections')
        self.assertEqual(denied.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/api/graph')
        self.assertEqual(denied.exception.code,401)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/',extra_headers={'Origin':'https://untrusted.invalid'})
        host = android._runtime['host']
        private = host.port_for(host.manager.default_id)
        for method in ('GET', 'POST'):
            request = urllib.request.Request(f'http://127.0.0.1:{private}/api/graph', method=method,
                data=b'{}' if method == 'POST' else None, headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5)
            self.assertEqual(denied.exception.code, 401)
        with self.request('/api/graph', management=True) as response:
            self.assertIn('nodes', json.load(response))
        with self.request('/api/health') as response:
            self.assertEqual(json.load(response)['version'], __version__)

    def test_credential_scope_persistence_and_deletion(self):
        keys = android._runtime['host'].keys
        one = {'provider':'example', 'library_id':'one'}
        other = {'provider':'example', 'library_id':'other'}
        self.assertEqual(keys.set(one,'FAKE-ANDROID-TEST-CREDENTIAL')['storage'], 'android_keystore')
        self.assertEqual(keys.get(one),'FAKE-ANDROID-TEST-CREDENTIAL')
        self.assertEqual(keys.get(other),'')
        android.stop()
        self.url=json.loads(android.start(self.root,self.vault,port=0))['url']
        keys=android._runtime['host'].keys
        self.assertTrue(keys.metadata(one)['key_saved'])
        keys.delete(one)
        self.assertEqual(keys.get(one),'')

    def test_actual_http_mcp_and_turn_hook_keep_one_window_and_library(self):
        host = android._runtime['host']
        first = host.manager.default_id
        second = host.manager.create_library('Synthetic separate')['id']
        with self.request('/api/connections', {'host':'agent', 'library_id':first,
                          'name':'Synthetic phone agent','session_scope':'next_session'}, True) as response:
            descriptor = json.load(response)
        cid = descriptor['connection']['id']
        self.assertNotIn('command', json.dumps(descriptor['mcp_config']))
        authorization = descriptor['remote_config']['headers']['Authorization']
        headers = {'Authorization':authorization,'Accept':'application/json, text/event-stream',
                   'MCP-Protocol-Version':'2025-11-25'}
        message = {'jsonrpc':'2.0','id':1,'method':'tools/call',
                   'params':{'name':'memory_status','arguments':{}}}
        with self.request('/mcp/'+cid, message, extra_headers=headers) as response:
            self.assertIn('structuredContent', json.load(response)['result'])
        hook_path='/api/remote/connections/'+cid+'/events'
        turn={'session_id':'synthetic-window-one','turn_id':'synthetic-turn-one',
              'status':'complete','user':'我们的合成测试暗号是红茶纸鹤。','assistant':'记住这个合成约定。'}
        with self.request(hook_path, turn, extra_headers={'Authorization':authorization}) as response:
            self.assertLess(response.status,300)
        self.assertEqual(host.connections.get(cid)['bound_session_id'],'synthetic-window-one')
        self.assertGreater(len(host.snapshot(first)['nodes']),0)
        self.assertEqual(len(host.snapshot(second)['nodes']),0)
        count = len(host.snapshot(first)['nodes'])
        with self.request(hook_path,{**turn,'session_id':'synthetic-other-window','turn_id':'other'},
                          extra_headers=headers) as response:
            rejected = json.load(response)
        self.assertFalse(rejected['accepted'])
        self.assertEqual(len(host.snapshot(first)['nodes']),count)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/mcp/'+cid,message,extra_headers={**headers,'X-NKB-Library':second})
        # This connection's bearer cannot enumerate controller connections.
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/connections',extra_headers={'Authorization':authorization})
        self.assertTrue(host.delete_library(first)['deleted'])

    def test_import_is_independent_idempotent_and_survives_process_restart(self):
        original = json.loads((ROOT/'mobile/tests/fixtures/desktop-share.json').read_text())
        staged=self.root.parent/'engine-imports'/'synthetic.json'
        staged.parent.mkdir()
        staged.write_text(json.dumps(original))
        before = len(android._runtime['host'].manager.list_libraries())
        result = json.loads(android.import_legacy(staged))
        self.assertTrue(result['imported'])
        self.assertTrue(staged.exists())
        self.assertEqual(len(android._runtime['host'].manager.list_libraries()), before+1)
        first = android._runtime['host'].snapshot(result['library_id'])
        self.assertEqual(len(first['nodes']),len(original['memory']['nodes']))
        original['created'] = 1
        staged.write_text(json.dumps(original))
        duplicate = json.loads(android.import_legacy(staged))
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate['library_id'], result['library_id'])
        android.stop()
        self.url=json.loads(android.start(self.root,self.vault,port=0))['url']
        self.assertEqual(android._runtime['host'].snapshot(result['library_id'])['nodes'],first['nodes'])
        self.assertTrue(json.loads(android.import_legacy(staged))['duplicate'])
        elsewhere = self.root.parent/'outside.json'
        elsewhere.write_text(staged.read_text())
        with self.assertRaises(ValueError): android.import_legacy(elsewhere)
        linked = staged.parent/'link.json'
        linked.symlink_to(elsewhere)
        with self.assertRaises(ValueError): android.import_legacy(linked)

    def test_failed_or_corrupt_receipt_does_not_duplicate_a_committed_migration_after_restart(self):
        from nkb.storage.jsonfile import JsonFileStorage
        staged = self.root.parent / 'engine-imports' / 'synthetic-receipt-failure.json'
        staged.parent.mkdir()
        original = (ROOT / 'mobile/tests/fixtures/desktop-share.json').read_bytes()
        staged.write_bytes(original)
        host = android._runtime['host']
        before = len(host.manager.list_libraries())
        save = JsonFileStorage.save

        def fail_only_auxiliary_receipt(storage, *args, **kwargs):
            if storage.path.name == 'legacy-imports.json':
                raise OSError('SYNTHETIC auxiliary receipt write failure')
            return save(storage, *args, **kwargs)

        with patch.object(JsonFileStorage, 'save', fail_only_auxiliary_receipt):
            result = json.loads(android.import_legacy(staged))
        self.assertTrue(result['imported'])
        self.assertFalse(result['receipt_recorded'])
        self.assertEqual(len(host.manager.list_libraries()), before + 1)
        imported = host.snapshot(result['library_id'])
        fingerprint = imported['meta']['shared_import']['source_fingerprint']
        self.assertRegex(fingerprint, r'^[0-9a-f]{64}$')
        android.stop()
        (self.root / 'legacy-imports.json').write_text('{SYNTHETIC incomplete receipt', encoding='utf-8')
        self.url = json.loads(android.start(self.root, self.vault, port=0))['url']
        host = android._runtime['host']
        # The durable graph mark recovers without overwriting either the staged
        # old share or the imported original wording, despite corrupt bookkeeping.
        recovered = json.loads(android.import_legacy(staged))
        self.assertTrue(recovered['duplicate'])
        self.assertEqual(recovered['library_id'], result['library_id'])
        self.assertEqual(len(host.manager.list_libraries()), before + 1)
        self.assertEqual(host.snapshot(result['library_id'])['nodes'], imported['nodes'])
        self.assertEqual(staged.read_bytes(), original)

    def test_internal_import_fingerprint_is_strict_and_untrusted_share_cannot_set_it(self):
        from nkb.errors import ValidationError
        host = android._runtime['host']
        original = json.loads((ROOT / 'mobile/tests/fixtures/desktop-share.json').read_text())
        before = len(host.manager.list_libraries())
        for wrong in (True, {}, '', 'f' * 63, 'F' * 64, 'not-a-fingerprint'):
            with self.subTest(fingerprint=wrong), self.assertRaises(ValidationError):
                host.sharing.import_file(original, source_fingerprint=wrong)
            self.assertEqual(len(host.manager.list_libraries()), before)
        original['memory']['meta']['shared_import'] = {'source_fingerprint': 'f' * 64}
        result = host.sharing.import_file(json.dumps(original))
        actual = host.snapshot(result['library']['id'])['meta']['shared_import']
        self.assertNotIn('source_fingerprint', actual)


class AndroidUpdateTests(unittest.TestCase):
    def test_android_never_offers_wrong_architecture_or_uninstallable_apk(self):
        self.assertEqual(target_platform('Android','aarch64'),('android','arm64'))
        def release(name):
            return [{'tag_name':'v0.10.7rc1','draft':False,'prerelease':True,
                     'html_url':'https://github.com/myflww/love-house/releases/tag/v0.10.7rc1',
                     'assets':[{'name':name,'browser_download_url':'https://github.com/myflww/love-house/releases/download/v0.10.7rc1/'+name}]}]
        for name in ['LoveHouse-0.10.7rc1-Windows-x64.zip', 'LoveHouse-0.10.7rc1-Android-unsigned.apk',
                     'LoveHouse-0.10.7rc1-Android-debug.apk','LoveHouse-0.10.7rc1-Android-x64.apk',
                     'LoveHouse-0.10.7rc1-Android-QA-ONLY.apk','LoveHouse-0.10.7rc1-Android-source.apk',
                     'OtherApp-0.10.7rc1-Android.apk']:
            self.assertIsNone(select_release(release(name),'android','arm64','preview')[0])
        self.assertIsNotNone(select_release(release('LoveHouse-0.10.7rc1-Android.apk'),'android','arm64','preview')[0])


class EnginePackagingTests(unittest.TestCase):
    def seed(self, root):
        for name in ('nkb/service/host.py','android/app/src/main/python/lovehouse_android/__init__.py'):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# Synthetic fixture\n')
        for name in ('LICENSE','NOTICE','THIRD_PARTY_NOTICES.md'):
            (root/name).write_text('Synthetic fixture licence\n')
    def test_private_source_or_symlink_is_rejected_before_replacing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.seed(root)
            result = packaging.prepare(root)
            output = root / result['output']
            old = (output/'nkb/service/host.py').read_bytes()
            (root/'nkb/secret.brain.json').write_text('{}')
            with self.assertRaises(ValueError): packaging.prepare(root)
            self.assertEqual((output/'nkb/service/host.py').read_bytes(),old)
            (root/'nkb/secret.brain.json').unlink()
            (root/'nkb/link.py').symlink_to(root/'NOTICE')
            with self.assertRaises(ValueError): packaging.prepare(root)


if __name__ == '__main__': unittest.main()
