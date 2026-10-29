"""Bound-library inheritance and complete read access, using disposable local data."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from nkb.core.brain import Brain
from nkb.companion.catalog import memory_bootstrap, memory_catalog, memory_read
from nkb.companion.memory import record_turn
from nkb.errors import ValidationError
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller


class MemoryInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host = MemoryHost(self.root, key_store=KeyStore(allow_keychain=False))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_controller(self.host))
        self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.other = self.host.manager.create_library('另一个独立的Agent')['id']
        self.a, self.ta = self.connection('default')
        self.b, self.tb = self.connection(self.other)
        self.na = self.add('default', 'A库独有的原话，不喜欢咖啡。')
        self.nb = self.add(self.other, 'B库独有的秘密，喜欢咖啡。')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.host.stop(); self.temp.cleanup()

    def connection(self, lib):
        result = self.host.new_connection({'name': '固定库连接', 'host': 'agent', 'library_id': lib})
        cid = result['connection']['id']
        return cid, self.host.connections.get(cid, secret=True)['token']

    def add(self, lib, text):
        return self.host.transact(lib, lambda b: b.add(text[:20], text, kind='fact',
                                                    meta={'source': 'user_confirmed', 'confirmed': True}))

    def api(self, path, data=None, token=None, lib=None):
        headers = {'Content-Type': 'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + token
        if lib: headers['X-NKB-Library'] = lib
        req = urllib.request.Request('http://127.0.0.1:' + str(self.server.server_port) + path,
                                     data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def tool(self, name, args=None, cid=None, token=None):
        return self.api('/api/connections/' + (cid or self.a) + '/tool',
                        {'name': name, 'arguments': args or {}}, token or self.ta)

    def test_new_connection_to_existing_library_inherits_old_sessions_without_copy_or_reset(self):
        def old_turns(brain):
            record_turn(brain, '我喜欢温水。', '我会记住这个偏好。', 'old-window-1', 'one')
            record_turn(brain, '我的生日是六月三日。', '生日会好好庆祝。', 'old-window-2', 'two')
        self.host.transact('default', old_turns)
        before = self.host.snapshot('default')
        cid, token = self.connection('default')
        status, bootstrap = self.tool('memory_bootstrap', cid=cid, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(bootstrap['identity']['library_id'], 'default')
        self.assertEqual(bootstrap['total_memories'], 3)
        material = json.dumps(bootstrap, ensure_ascii=False)
        self.assertIn('温水', material); self.assertIn('六月三日', material)
        self.assertNotIn('B库独有的秘密', material)
        status, context = self.tool('memory_context', {'query': '温水', 'session_id': 'genuinely-new-window'}, cid=cid, token=token)
        self.assertEqual(status, 200)
        self.assertIn('温水', json.dumps(context, ensure_ascii=False))
        self.assertEqual(self.host.snapshot('default'), before)

    def test_gui_selection_other_library_does_not_rebind_bootstrap_persona_or_read(self):
        self.host.manager.select(self.other)
        for name, args in [('memory_bootstrap', {}), ('memory_list', {}), ('memory_read', {'memory_id': self.na})]:
            status, result = self.tool(name, args)
            self.assertEqual(status, 200)
            self.assertEqual(result['identity']['library_id'], 'default')
            self.assertNotIn('B库独有的秘密', json.dumps(result, ensure_ascii=False))
        persona = self.tool('memory_persona')[1]
        self.assertNotIn('B库独有的秘密', json.dumps(persona, ensure_ascii=False))

    def test_persona_and_same_source_ids_in_two_libraries_stay_independent(self):
        for cid, token, text in [(self.a,self.ta,'A人格：温柔的鲸鱼娘'),(self.b,self.tb,'B人格：严谨的记录员')]:
            result=self.tool('memory_persona_import',{'text':text,'user_request':'请导入这个人格：'+text,
                         'explicit':True,'session_id':'same-source-window','request_id':'same-source-turn'},cid,token)
            self.assertEqual(result[0],200)
            self.assertTrue(result[1]['accepted'])
        self.host.manager.select(self.other)
        a=self.tool('memory_bootstrap')[1]
        b=self.tool('memory_bootstrap',cid=self.b,token=self.tb)[1]
        self.assertIn('A人格',json.dumps(a,ensure_ascii=False));self.assertNotIn('B人格',json.dumps(a,ensure_ascii=False))
        self.assertIn('B人格',json.dumps(b,ensure_ascii=False));self.assertNotIn('A人格',json.dumps(b,ensure_ascii=False))

    def test_cross_library_memory_ids_and_cursor_are_rejected(self):
        self.add(self.other, 'B库第二条')
        catalog = self.tool('memory_list', {'limit': 1}, self.b, self.tb)[1]
        self.assertTrue(catalog['next_cursor'])
        for name, args in [('memory_read', {'memory_id': self.nb}), ('memory_list', {'cursor': catalog['next_cursor']})]:
            status, result = self.tool(name, args)
            self.assertEqual(status, 400)
            self.assertNotIn('B库独有的秘密', json.dumps(result, ensure_ascii=False))
        self.assertEqual(self.tool('memory_list', {}, self.a, self.tb)[0], 403)

    def test_local_memory_token_cannot_be_vendor_key_for_another_api_connection(self):
        target = self.host.new_connection({'name':'高级转发', 'host':'api', 'library_id':self.other})['connection']['id']
        # Reject before reading memory or opening any upstream, even with no saved vendor key.
        status, result = self.api('/connections/'+target+'/v1/chat/completions',
                                  {'messages':[{'role':'user','content':'hello'}]}, self.ta)
        self.assertEqual(status, 403)
        self.assertNotIn('B库独有', json.dumps(result,ensure_ascii=False))
        self.assertEqual(self.api('/api/connections/'+self.a+'/tool?library_id='+self.other,
             {'name':'memory_list','arguments':{}},self.ta)[0],403)

    def test_server_rejects_override_extra_parameters_and_forged_confirmation(self):
        for name, args in [('memory_bootstrap', {'library_id': self.other}),
                           ('memory_context', {'query': 'x', 'library_id': self.other}),
                           ('memory_persona', {'library_id': self.other}),
                           ('memory_remember', {'text': 'x', 'session_id': 's', 'confirmed': True}),
                           ('memory_remember', {'text': 'x', 'session_id': 's', 'source_ids': [self.nb]}),
                           ('memory_list', {'limit': True})]:
            self.assertEqual(self.tool(name, args)[0], 400)
        path = '/api/connections/' + self.a + '/tool'
        self.assertEqual(self.api(path, {'name': 'memory_list', 'arguments': {}, 'library_id': self.other}, self.ta)[0], 400)
        self.assertEqual(self.api(path, {'name': 'memory_list', 'arguments': {}}, self.ta, self.other)[0], 403)
        path = '/api/connections/' + self.a + '/context'
        self.assertEqual(self.api(path, {'query': 'x', 'session_id': 's', 'library_id': self.other}, self.ta)[0], 400)

    def test_connection_bearer_cannot_use_desktop_cross_library_management_surface(self):
        for path in ['/api/libraries', '/api/graph?library_id=' + self.other,
                     '/api/activity', '/api/connections/' + self.b + '/config']:
            self.assertEqual(self.api(path, token=self.ta)[0], 403)
        self.assertEqual(self.api('/api/library/select', {'library_id': self.other}, self.ta)[0], 403)
        self.assertEqual(self.api('/api/memory/bootstrap', {}, self.ta, self.other)[0], 403)
        # This GUI-local route remains explicitly scoped by header without Agent credentials.
        self.assertEqual(self.api('/api/memory/bootstrap', {}, lib=self.other)[1]['identity']['library_id'], self.other)

    def test_page_all_records_then_read_original_and_assistant_in_chunks(self):
        ids = {self.na}
        for i in range(34): ids.add(self.add('default', '同库完整目录条目' + str(i)))
        dialogue = self.host.transact('default', lambda b: record_turn(b, '原话前半。不喜欢被曲解。' * 80,
                                                                       '助手实际回复。' * 85, 'old-window', 'full'))
        ids.add(dialogue)
        cursor, seen = None, []
        while True:
            args = {'limit': 7}
            if cursor: args['cursor'] = cursor
            status, page = self.tool('memory_list', args)
            self.assertEqual(status, 200)
            seen.extend(r['id'] for r in page['entries'])
            cursor = page['next_cursor']
            if cursor is None: break
        self.assertEqual(set(seen), ids); self.assertEqual(len(seen), len(ids))
        source = self.host.snapshot('default')['nodes'][dialogue]
        for field, expected in [('value', source['text']), ('assistant', source['meta']['assistant_reply'])]:
            offset, chunks = 0, []
            while True:
                status, read = self.tool('memory_read', {'memory_id': dialogue, 'field': field, 'offset': offset,
                                                        'max_chars': 37, 'revision': page['revision']})
                self.assertEqual(status, 200)
                self.assertNotIn('value', read['record'])
                chunks.append(read['text']); offset = read['next_offset']
                if offset is None: break
            self.assertEqual(''.join(chunks), expected)

    def test_stale_cursor_and_chunk_revision_fail_after_memory_changes(self):
        self.add('default', '更多记录')
        page = self.tool('memory_list', {'limit': 1})[1]
        self.assertTrue(page['next_cursor'])
        self.add('default', '读取期间新增')
        self.assertEqual(self.tool('memory_list', {'cursor': page['next_cursor']})[0], 400)
        self.assertEqual(self.tool('memory_read', {'memory_id': self.na, 'revision': page['revision']})[0], 400)

    def test_paused_merged_fact_blocks_even_sources_outside_recent_quote_window(self):
        from nkb.service.controls import set_enabled
        raw=self.host.transact('default',lambda b:record_turn(b,'早期私人原话','真实回答','old','one'))
        fact=self.host.transact('default',lambda b:b.add('整理事实','早期私人原话',kind='fact',
             meta={'source':'organizer','organizer_evidence':[],
                   'organizer_sources':[{'id':raw,'role':'user'}]}))
        self.host.transact('default',lambda b:set_enabled(b,fact,False))
        for nid in (raw,fact):self.assertEqual(self.tool('memory_read',{'memory_id':nid})[0],400)
        boot=self.tool('memory_bootstrap')[1]
        context=self.tool('memory_context',{'query':'早期私人原话','session_id':'new-window'})[1]
        self.assertNotIn('早期私人原话',json.dumps(boot,ensure_ascii=False))
        self.assertNotIn('早期私人原话',json.dumps(context,ensure_ascii=False))

    def test_paused_deleted_duplicate_and_foreign_tagged_nodes_not_available_to_agent(self):
        from nkb.service.controls import set_enabled
        paused = self.add('default', '暂不使用的私人材料')
        self.host.transact('default', lambda b: set_enabled(b, paused, False))
        tagged = self.host.transact('default', lambda b: b.add('错误归属', '不应进入本库Agent', meta={'library_id': self.other}))
        first = self.host.transact('default', lambda b: record_turn(b, '真实原话', '实际回复', 'same', 'one'))
        second = self.host.transact('default', lambda b: record_turn(b, '真实原话', '实际回复', 'same', 'two', origin='agent_host_hook'))
        from nkb.companion.dedup import confirm_duplicate, recording_version
        self.host.transact('default', lambda b: confirm_duplicate(b, second, [first],
                           {nid: recording_version(b.get(nid)) for nid in (first, second)}))
        page = self.tool('memory_list')[1]
        self.assertEqual(page['total'], 2)
        for nid in [paused, tagged]: self.assertEqual(self.tool('memory_read', {'memory_id': nid})[0], 400)
        self.host.forget_memory('default', self.na)
        self.assertEqual(self.tool('memory_read', {'memory_id': self.na})[0], 400)
        self.assertNotIn('暂不使用的私人材料', json.dumps(self.tool('memory_bootstrap')[1], ensure_ascii=False))

    def test_legacy_stdio_bridge_is_explicitly_bound_and_no_longer_lists_all_libraries(self):
        spec = importlib.util.spec_from_file_location('inheritance_legacy_bridge', Path(__file__).resolve().parents[1] / 'desktop/harness_bridge.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        runtime = self.root / '.runtime'; runtime.mkdir(exist_ok=True)
        (runtime / 'app.json').write_text(json.dumps({'pid': os.getpid(), 'controller_port': self.server.server_port,
                                                     'service_version': '0.4.0'}))
        self.host.manager.select('default')
        bridge = module.Bridge(runtime, self.other)
        original = bridge._request
        paths = []
        def request(port, path, body=None):
            paths.append(path); return original(port, path, body)
        bridge._request = request
        state = bridge.call_tool('memory_status', {})
        self.assertFalse(state.get('isError'), state)
        self.assertEqual(state['structuredContent']['library_id'], self.other)
        self.assertNotIn('/api/libraries', paths)
        boot = bridge.call_tool('memory_bootstrap', {})
        self.assertEqual(boot['structuredContent']['identity']['library_id'], self.other)
        self.assertNotIn('A库独有的原话', json.dumps(boot, ensure_ascii=False))
        context = bridge.call_tool('memory_context', {'query': '咖啡', 'session_id': 'new'})
        self.assertEqual(context['structuredContent']['identity']['library_id'], self.other)


class LargeInheritanceTests(unittest.TestCase):
    def test_bootstrap_is_bounded_and_catalog_reaches_more_than_thousand_records(self):
        brain = Brain.new()
        for i in range(1002): brain.add('记忆' + str(i), '完整原文' + str(i), kind='fact')
        bootstrap = memory_bootstrap(brain, 'default', '完整库', max_chars=2000)
        self.assertEqual(bootstrap['total_memories'], 1002)
        self.assertFalse(bootstrap['all_memory_loaded'])
        cursor, ids = None, []
        while True:
            page = memory_catalog(brain, 'default', '完整库', cursor=cursor, limit=100)
            ids.extend(r['id'] for r in page['entries']); cursor = page['next_cursor']
            if not cursor: break
        self.assertEqual(len(ids), 1002)
        self.assertEqual(len(set(ids)), 1002)


if __name__ == '__main__': unittest.main()
