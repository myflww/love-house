"""Concurrent, explicitly connected windows share only their chosen library."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from http.server import ThreadingHTTPServer

from nkb.companion import connected_session_id, history
from nkb.core.brain import Brain
from nkb.service.agent_client import event_from_hook
from nkb.service.connections import ConnectionStore
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller


class MultiWindowServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = MemoryHost(Path(self.temp.name), key_store=KeyStore(allow_keychain=False),
            organizer_transport=lambda *_a, **_k: self.fail('No model calls during window tests'))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_controller(self.host))
        self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.host.stop(); self.temp.cleanup()

    def request(self, cid, token, action, data):
        request = Request(f'http://127.0.0.1:{self.server.server_port}/api/connections/{cid}/{action}',
            data=json.dumps(data, ensure_ascii=False).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=20) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            return response.code, json.load(response)

    def connection(self, library, window, host='agent'):
        result = self.host.new_connection({'name': '已授权窗口 ' + window, 'host': host,
            'library_id': library, 'session_scope': window})
        cid = result['connection']['id']
        return cid, self.host.connections.get(cid, secret=True)['token']

    def event(self, window, turn, text):
        return event_from_hook({'session_id': window, 'turn_id': turn, 'status': 'complete',
            'user': text, 'assistant': '实际回复 ' + text})

    def parallel(self, work):
        barrier = threading.Barrier(len(work))
        def run(call):
            barrier.wait(timeout=10)
            return call()
        with ThreadPoolExecutor(max_workers=len(work)) as pool:
            return list(pool.map(run, work))

    def test_parallel_import_and_recall_keep_library_and_window_history_boundaries(self):
        other = self.host.manager.create_library('另一个独立记忆库')['id']
        # Same host-supplied session and turn IDs in different bindings must not collide.
        bindings = [(library, f'window-{index}', *self.connection(library, f'window-{index}'))
            for library in ('default', other) for index in range(3)]
        for turn in ('one', 'two'):
            results = self.parallel([
                lambda library=library, window=window, cid=cid, token=token:
                    self.request(cid, token, 'events', self.event(window, turn,
                        f'并发约定 {library} {window} {turn}'))
                for library, window, cid, token in bindings])
            for code, result in results:
                self.assertEqual(code, 200, result)
                self.assertTrue(result['accepted'], result)
        # A successful durable receipt may still await the existing graph worker.
        self.host.process_pending()
        self.assertEqual(self.host.connections.pending(), [])
        self.host.manager.select(other)
        results = self.parallel([
            lambda library=library, window=window, cid=cid, token=token:
                self.request(cid, token, 'context', {'query': '并发约定',
                    'session_id': window, 'max_chars': 32000})
            for library, window, cid, token in bindings])
        for (library, window, cid, _token), (code, context) in zip(bindings, results):
            self.assertEqual(code, 200, context)
            self.assertEqual(context['library_id'], library)
            self.assertEqual(context['connection_id'], cid)
            records = context['memory_context']['records']
            serialized = json.dumps(records, ensure_ascii=False)
            # Both other explicitly connected windows of this library are recallable.
            for index in range(3):
                self.assertIn(f'并发约定 {library} window-{index}', serialized)
            foreign = other if library == 'default' else 'default'
            self.assertNotIn(f'并发约定 {foreign}', serialized)
            brain = Brain(self.host.snapshot(library))
            rows = history(brain, connected_session_id(cid, window))
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(f' {window} ' in item['content'] for item in rows))
        for library in ('default', other):
            self.assertEqual(len(self.host.snapshot(library)['nodes']), 6)

        before = {library: self.host.snapshot(library) for library in ('default', other)}
        denied = self.parallel([
            lambda cid=cid, token=token:
                self.request(cid, token, 'events', self.event('unconnected-window', 'private',
                    'UNCONNECTED-WINDOW-MUST-NOT-REACH-DISK'))
            for _library, _window, cid, token in bindings])
        for code, result in denied:
            self.assertEqual(code, 200, result)
            self.assertFalse(result['accepted'], result)
            self.assertEqual(result['code'], 'scope_conflict')
        denied_reads = self.parallel([
            lambda cid=cid, token=token:
                self.request(cid, token, 'context', {'query': '并发约定', 'session_id': 'unconnected-window'})
            for _library, _window, cid, token in bindings])
        self.assertTrue(all(code == 400 for code, _ in denied_reads), denied_reads)
        for library in ('default', other):
            self.assertEqual(self.host.snapshot(library), before[library])
        files=[]
        for path in Path(self.temp.name).rglob('*'):
            if not path.is_file():continue
            try:files.append(path.read_bytes())
            except FileNotFoundError:
                # SQLite may unlink its shared-memory lock/index file as the
                # last reader closes. It contains no dialogue body; persistent
                # databases and WAL payloads must still be read successfully.
                if not path.name.endswith('.sqlite3-shm'):raise
        contents = b'\n'.join(files)
        self.assertNotIn(b'UNCONNECTED-WINDOW-MUST-NOT-REACH-DISK', contents)

    def test_same_event_replayed_concurrently_is_one_durable_record(self):
        cid, token = self.connection('default', 'fixed-window')
        event = self.event('fixed-window', 'same-turn', '同一原文只保存一次')
        results = self.parallel([lambda: self.request(cid, token, 'events', event) for _ in range(8)])
        for code, result in results:
            self.assertEqual(code, 200, result)
            self.assertTrue(result['accepted'], result)
        self.assertEqual(sum(not result['duplicate'] for _code, result in results), 1)
        self.host.process_pending()
        self.assertEqual(len(self.host.connections.activity('default')['events']), 1)
        self.assertEqual(len(self.host.snapshot('default')['nodes']), 1)

    def test_independent_store_writers_share_the_same_durable_idempotency_guard(self):
        cid, _token = self.connection('default', 'fixed-window')
        connection = self.host.connections.get(cid, secret=True)
        event = self.event('fixed-window', 'same-turn', '多个写入方重试同一原文')
        # Separate stores have separate process-local locks, just as independent
        # local import/recovery processes do. Dedup must also be atomic in SQLite.
        stores = [ConnectionStore(self.temp.name) for _ in range(8)]
        results = self.parallel([
            lambda store=store: store.receive(connection, event) for store in stores])
        self.assertTrue(all(result['accepted'] for result in results))
        self.assertEqual(sum(not result['duplicate'] for result in results), 1)
        self.host.process_pending()
        self.assertEqual(len(self.host.connections.activity('default')['events']), 1)
        self.assertEqual(len(self.host.snapshot('default')['nodes']), 1)


if __name__ == '__main__':
    unittest.main()
