"""Optional model reading index: explicit consent, one library, shared atomic budget."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from nkb.errors import ValidationError
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller
from nkb.service.sharing import ShareStore
from nkb.service.share_summary import ReadingSummaryService

KEY = 'FAKE-READING-KEY-123456'


class ReadingSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.requests = []; self.reply = '{"summary":"关于小鱼和无糖茶的阅读索引。"}'
        self.intercept = None
        def transport(request, *, timeout):
            self.requests.append(request)
            if self.intercept: return self.intercept(request)
            return {'choices': [{'message': {'content': self.reply}, 'finish_reason': 'stop'}]}
        self.host = MemoryHost(Path(self.temp.name), key_store=KeyStore(allow_keychain=False), organizer_transport=transport)
        self.host.sharing = ShareStore(self.host); self.service = ReadingSummaryService(self.host)
        self.host.share_summaries = self.service
        self.host.transact('default', lambda b: b.add('小鱼饮品', '我偏爱无糖茶。', kind='concept'))
        self.other = self.host.manager.create_library('别的鱼')['id']
        self.host.transact(self.other, lambda b: b.add('另一只鱼', '这是另一库绝不能发送给前一个模型的内容。', kind='concept'))

    def tearDown(self):
        self.host.stop(); self.temp.cleanup()

    def configure(self, lib='default', **settings):
        self.host.organizer_settings(lib, {'enabled': False, 'provider_mode': 'separate',
                'base_url': 'https://reading.invalid/v1', 'model': 'FAKE-READING-MODEL',
                'api_key': KEY, 'save_key': False, **settings})

    def revision(self, lib='default'): return self.host.sharing.preview(lib)['content_revision']
    def generate(self, lib='default', **kwargs):
        return self.service.generate(lib, expected_revision=kwargs.pop('expected_revision', self.revision(lib)), confirm=kwargs.pop('confirm', True), **kwargs)
    def usage(self, lib='default'):
        with self.host.organizer.db() as db: return self.host.organizer._budget(db, lib)

    def test_open_preview_and_full_download_do_not_call_model_or_require_key(self):
        before = self.host.snapshot('default'); preview = self.host.sharing.preview('default')
        content = self.host.sharing.download('default', expected_revision=preview['content_revision'])
        self.assertIn('我偏爱无糖茶。', content['content'])
        self.assertEqual(self.requests, []); self.assertEqual(self.usage()['count'], 0)
        self.assertEqual(self.host.snapshot('default'), before)
        with self.assertRaises(ValidationError): self.generate()
        self.assertEqual(self.requests, []); self.assertEqual(self.usage()['count'], 0)

    def test_consent_and_current_revision_required_before_network_or_budget(self):
        self.configure()
        for confirm in (False, None, 1, 'true'):
            with self.assertRaises(ValidationError): self.generate(confirm=confirm)
        for revision in (None, '', 'wrong', 42):
            with self.assertRaises(ValidationError): self.generate(expected_revision=revision)
        self.assertEqual(self.requests, []); self.assertEqual(self.usage()['count'], 0)

    def test_success_uses_configured_model_and_shared_budget_but_never_mutates_raw_memory(self):
        self.configure(); original = self.host.snapshot('default'); revision = self.revision()
        result = self.generate(); self.assertTrue(result['model_called']); self.assertTrue(result['full_archive_unchanged'])
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]; payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'FAKE-READING-MODEL'); self.assertEqual(request.full_url, 'https://reading.invalid/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + KEY)
        self.assertNotIn(KEY, request.data.decode()); self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(self.usage()['count'], 1); self.assertEqual(self.usage()['chars'], result['input_chars'])
        self.assertEqual(original, self.host.snapshot('default'))
        summary = self.service.resolve('default', result['summary_id'], revision)
        summary['text'] = 'caller mutation'
        self.assertNotEqual(self.service.resolve('default', result['summary_id'], revision)['text'], 'caller mutation')
        full = json.loads(self.host.sharing.download('default', reading_summary=result['reading_summary'])['content'])
        self.assertIn('我偏爱无糖茶。', json.dumps(full, ensure_ascii=False))
        self.assertTrue(full['reading_summary']['not_full_memory'])
        self.assertEqual(self.requests, [request])

    def test_request_contains_only_this_library_and_high_confidence_credentials_are_scrubbed(self):
        self.configure()
        def private(b):
            node = next(iter(b.nodes.values())); node['meta']['api_key'] = 'BODY_STRUCT_SECRET'
            node['text'] += '\n凭据 api_key=' + 'Z'*24 + '\n位置 /Users/PRIVATE/secret.txt'
            node['text'] += '\n这是以前随手粘贴在原文里的无前缀凭据：' + KEY
        self.host.transact('default', private)
        result = self.generate(); body = self.requests[0].data.decode()
        for secret in ('BODY_STRUCT_SECRET', 'Z'*24, '/Users/PRIVATE', '这是另一库绝不能发送给前一个模型的内容。', KEY):
            self.assertNotIn(secret, body)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertIn('我偏爱无糖茶。', body)

    def test_another_library_cannot_borrow_key_cache_or_budget(self):
        self.configure(); result = self.generate()
        with self.assertRaises(ValidationError): self.generate(self.other)
        with self.assertRaises(ValidationError): self.service.resolve(self.other, result['summary_id'], result['content_revision'])
        self.assertEqual(len(self.requests), 1); self.assertEqual(self.usage(self.other)['count'], 0)
        self.configure(self.other, daily_call_limit=1)
        self.generate(self.other)
        self.assertEqual(self.usage('default')['count'], 1); self.assertEqual(self.usage(self.other)['count'], 1)

    def test_call_limit_includes_other_organizer_calls_and_full_download_remains_available(self):
        self.configure(daily_call_limit=1)
        with self.host.organizer.db() as db: db.execute('INSERT INTO calls VALUES(?,?,?,?)', ('background', 'default', time.time(), 100))
        with self.assertRaises(ValidationError): self.generate()
        self.assertEqual(self.requests, []); self.assertEqual(self.usage()['count'], 1)
        self.assertTrue(self.host.sharing.download('default')['content'])

    def test_input_character_limit_checked_atomically_before_transport(self):
        self.configure(daily_char_limit=3000)
        with self.host.organizer.db() as db: db.execute('INSERT INTO calls VALUES(?,?,?,?)', ('background', 'default', time.time(), 2950))
        with self.assertRaises(ValidationError): self.generate()
        self.assertEqual(self.requests, []); self.assertEqual(self.usage()['chars'], 2950)

    def test_network_failure_counts_attempt_but_does_not_echo_exception_key_or_touch_source(self):
        self.configure(); original = self.host.snapshot('default')
        def fail(request): raise RuntimeError('provider echo ' + KEY)
        self.intercept = fail
        with self.assertRaises(ValidationError) as error: self.generate()
        self.assertNotIn(KEY, str(error.exception)); self.assertEqual(self.usage()['count'], 1)
        self.assertEqual(self.host.snapshot('default'), original)
        self.assertTrue(self.host.sharing.download('default')['content'])

    def test_malformed_truncated_or_key_echo_output_not_cached(self):
        self.configure()
        encoded_key = '{"summary":"' + ''.join('\\u%04x' % ord(c) for c in KEY) + '"}'
        for content in ('plain text', '{"summary":""}', json.dumps({'summary': KEY}), encoded_key, '{"summary":"ok","all_loaded":true}'):
            self.reply = content
            with self.assertRaises(ValidationError) as error: self.generate()
            self.assertNotIn(KEY, str(error.exception))
        self.intercept = lambda request: {'choices': [{'message': {'content': '{"summary":"half"}'}, 'finish_reason': 'length'}]}
        with self.assertRaises(ValidationError): self.generate()
        self.assertEqual(self.usage()['count'], 6); self.assertEqual(self.service._summaries, {})

    def test_changed_revision_during_request_drops_summary_after_counting_call(self):
        self.configure(); before = self.revision()
        def change(request):
            self.host.transact('default', lambda b: b.add('新内容', '模型请求期间到达的新记忆。'))
            return {'choices': [{'message': {'content': '{"summary":"过时索引"}'}, 'finish_reason': 'stop'}]}
        self.intercept = change
        with self.assertRaises(ValidationError): self.generate(expected_revision=before)
        self.assertEqual(self.usage()['count'], 1); self.assertEqual(self.service._summaries, {})
        self.assertNotEqual(self.revision(), before)

    def test_forgotten_or_edited_source_invalidates_cache_even_if_client_supplies_old_revision(self):
        self.configure(); result = self.generate()
        nid = next(iter(self.host.snapshot('default')['nodes']))
        self.host.forget_memory('default', nid)
        for revision in (self.revision(), result['content_revision']):
            with self.assertRaises(ValidationError): self.service.resolve('default', result['summary_id'], revision)
        self.assertNotIn('我偏爱无糖茶。', self.host.sharing.download('default')['content'])

    def test_expired_cache_and_bad_identifiers_rejected(self):
        self.configure(); result = self.generate()
        with self.service._lock: self.service._summaries[result['summary_id']]['created'] -= 1801
        with self.assertRaises(ValidationError): self.service.resolve('default', result['summary_id'], result['content_revision'])
        for identifier in (['bad'], {'id': 'bad'}, 23):
            with self.assertRaises(ValidationError): self.service.resolve('default', identifier, result['content_revision'])

    def test_single_library_concurrency_rejects_duplicate_network_action(self):
        self.configure(); entered = threading.Event(); release = threading.Event(); result = []
        def wait(request):
            entered.set(); self.assertTrue(release.wait(3))
            return {'choices': [{'message': {'content': '{"summary":"第一份"}'}, 'finish_reason': 'stop'}]}
        self.intercept = wait
        thread = threading.Thread(target=lambda: result.append(self.generate())); thread.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaises(ValidationError): self.generate()
        finally: release.set(); thread.join(4)
        self.assertEqual(len(result), 1); self.assertEqual(len(self.requests), 1); self.assertEqual(self.usage()['count'], 1)


class ShareHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.calls = []
        def transport(request, *, timeout):
            self.calls.append(request)
            return {'choices': [{'message': {'content': '{"summary":"一个中文阅读索引。"}'}, 'finish_reason': 'stop'}]}
        self.host = MemoryHost(Path(self.temp.name), key_store=KeyStore(allow_keychain=False), organizer_transport=transport)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_controller(self.host)); self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}); self.thread.start()
        self.host.transact('default', lambda b: b.add('测试记忆', '这是本库的一句真实验收文字。', kind='concept'))

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.host.stop(); self.temp.cleanup()

    def req(self, path, data, token=None, lib='default', management=False):
        headers = {'Content-Type': 'application/json', 'X-NKB-Library': lib}
        if management: headers['X-LoveHouse-Management']=self.host.management_token
        if token: headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}' + path, data=json.dumps(data, ensure_ascii=False).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response: return response.status, json.load(response)
        except urllib.error.HTTPError as error: return error.code, json.load(error)

    def test_http_preview_download_summary_and_new_library_import_are_wired(self):
        status, preview = self.req('/api/sharing/preview', {})
        self.assertEqual(status, 200, preview); self.assertNotIn('summary_provider',preview)
        status,provider=self.req('/api/sharing/summary-provider',{},management=True)
        self.assertEqual(status,200,provider);self.assertFalse(provider['summary_provider']['credential_ready'])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.req('/api/sharing/download', {'expected_revision': preview['content_revision']})[0], 400)
        status, download = self.req('/api/sharing/download', {'confirm': True, 'expected_revision': preview['content_revision']})
        self.assertEqual(status, 200, download); self.assertIn('这是本库的一句真实验收文字。', download['content'])
        self.assertEqual(self.req('/api/sharing/import-preview', {'content': download['content']})[0], 200)
        self.assertEqual(self.req('/api/sharing/import', {'content': download['content']})[0], 400)
        status, imported = self.req('/api/sharing/import', {'confirm': True, 'content': download['content'], 'name': '全新独立副本'})
        self.assertEqual(status, 200, imported); self.assertNotEqual(imported['library']['id'], 'default')
        self.assertFalse(imported['connections_rebound']); self.assertFalse(imported['organizer_enabled'])
        self.assertEqual(self.calls, [])

    def test_agent_bearer_cannot_export_import_or_trigger_model(self):
        config = self.host.new_connection({'name': '绑定的Agent', 'host': 'agent', 'library_id': 'default'})
        token = self.host.connections.get(config['connection']['id'], secret=True)['token']
        for action in ('preview', 'download', 'summary', 'summary-provider', 'import-preview', 'import'):
            status, result = self.req('/api/sharing/' + action, {'confirm': True, 'content': '{}'}, token=token)
            self.assertEqual(status, 403, result)
        self.assertEqual(self.calls, [])

    def test_full_preview_and_download_never_wait_for_or_read_broken_organizer_state(self):
        with patch.object(self.host,'organizer_view',side_effect=RuntimeError('broken optional organizer')) as organizer:
            status,preview=self.req('/api/sharing/preview',{})
            self.assertEqual(status,200,preview);self.assertNotIn('summary_provider',preview)
            status,download=self.req('/api/sharing/download',{'confirm':True,'expected_revision':preview['content_revision']})
            self.assertEqual(status,200,download);self.assertIn('这是本库的一句真实验收文字。',download['content'])
            organizer.assert_not_called()

    def test_optional_provider_metadata_requires_management_and_never_returns_keys(self):
        self.assertEqual(self.req('/api/sharing/summary-provider',{})[0],401)
        self.host.organizer_settings('default',{'enabled':True,'provider_mode':'separate','base_url':'https://model.test/v1','model':'reader','api_key':KEY,'save_key':False})
        status,result=self.req('/api/sharing/summary-provider',{},management=True)
        self.assertEqual(status,200,result);self.assertTrue(result['summary_provider']['credential_ready'])
        self.assertNotIn(KEY,json.dumps(result))

    def test_large_json_file_over_default_one_mib_body_limit_imports_as_new_library(self):
        def seed(b):
            for i in range(16): b.add(f'长记录{i}', '大份记忆文件需要完整导入。'*2000, kind='concept')
        self.host.transact('default', seed)
        status, preview = self.req('/api/sharing/preview', {}); self.assertEqual(status, 200, preview)
        status, download = self.req('/api/sharing/download', {'confirm': True, 'expected_revision': preview['content_revision']})
        self.assertEqual(status, 200, download); self.assertGreater(len(download['content'].encode()), 1024*1024)
        status, result = self.req('/api/sharing/import-preview', {'content': download['content']})
        self.assertEqual(status, 200, result)
        status, result = self.req('/api/sharing/import', {'confirm': True, 'content': download['content'], 'name': '大份记忆分享副本'})
        self.assertEqual(status, 200, result); self.assertEqual(result['counts']['node_count'], 17)

    def test_model_summary_http_uses_same_revision_and_no_credentials_in_response(self):
        self.host.organizer_settings('default', {'enabled': False, 'provider_mode': 'separate', 'base_url': 'https://reading.invalid/v1',
                                               'model': 'FAKE-READING-MODEL', 'api_key': KEY, 'save_key': False})
        status, preview = self.req('/api/sharing/preview', {}); self.assertEqual(status, 200, preview)
        status,provider=self.req('/api/sharing/summary-provider',{},management=True)
        self.assertEqual(status,200,provider);self.assertTrue(provider['summary_provider']['credential_ready']); self.assertNotIn(KEY, json.dumps(provider))
        status, summary = self.req('/api/sharing/summary', {'confirm': True, 'expected_revision': preview['content_revision']})
        self.assertEqual(status, 200, summary); self.assertNotIn(KEY, json.dumps(summary))
        status, download = self.req('/api/sharing/download', {'confirm': True, 'expected_revision': preview['content_revision'], 'summary_id': summary['summary_id']})
        self.assertEqual(status, 200, download)
        value = json.loads(download['content']); self.assertEqual(value['reading_summary']['text'], '一个中文阅读索引。')
        self.assertEqual(len(self.calls), 1)
        self.host.transact('default', lambda b: b.add('changed', '导出前来了新的记录'))
        status, result = self.req('/api/sharing/download', {'confirm': True, 'expected_revision': preview['content_revision'], 'summary_id': summary['summary_id']})
        self.assertEqual(status, 400, result)


if __name__ == '__main__': unittest.main()
