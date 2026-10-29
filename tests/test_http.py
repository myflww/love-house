"""HTTP integration tests use temporary brains and ephemeral loopback ports only."""
from __future__ import annotations

import copy
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nkb import Brain  # noqa: E402
from nkb.adapters.http import MAX_BODY_BYTES, make_handler  # noqa: E402


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "temporary-brain.json"
        self.brain = Brain.new(self.path, name="HTTP 测试")
        self.first = self.brain.add("记忆网络", "一条测试记忆", kind="episode")
        self.brain.save()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.brain))
        self.port = self.server.server_port
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self, method, route, data=None, *, raw=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        request_headers = dict(headers or {})
        if raw is not None:
            body = raw
        elif data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        else:
            body = None
        if method == "POST":
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, route, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            values = dict(response.getheaders())
            if values.get("Content-Type", "").startswith("application/json") and content:
                content = json.loads(content)
            return response.status, content, values
        finally:
            connection.close()

    def test_get_snapshot_and_security_headers(self):
        status, graph, headers = self.request("GET", "/api/graph")
        self.assertEqual(status, 200)
        self.assertEqual(graph["nodes"][0]["id"], self.first)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/api/health")[1]["ok"], True)

    def test_add_preserves_impact_and_metadata(self):
        status, result, _ = self.request("POST", "/api/add", {
            "label": "重要的相遇", "text": "这条信息要能回读", "kind": "episode",
            "tags": ["朋友"], "impact": -0.8, "salience": 0.9,
            "meta": {"source": "temporary test"},
        }, headers={"Origin": self.origin})
        self.assertEqual(status, 200, result)
        saved = Brain.open(self.path)
        self.assertEqual(saved.nodes[result["id"]]["impact"], -0.8)
        self.assertEqual(saved.nodes[result["id"]]["meta"]["source"], "temporary test")
        status, node, _ = self.request("GET", "/api/node?id=" + quote(result["id"]))
        self.assertEqual(status, 200)
        self.assertEqual(node["text"], "这条信息要能回读")

    def test_add_event_time_and_session(self):
        event_at = time.time() - 100
        status, result, _ = self.request("POST", "/api/add", {
            "label": "同一次对话", "event_at": event_at, "session_id": "test-session",
        })
        self.assertEqual(status, 200, result)
        saved = Brain.open(self.path).nodes[result["id"]]
        self.assertEqual(saved["event_at"], event_at)
        self.assertEqual(saved["session_id"], "test-session")

    def test_existing_write_routes(self):
        status, added, _ = self.request("POST", "/api/add", {"label": "记忆网络的连接"})
        self.assertEqual(status, 200)
        ids = [self.first, added["id"]]
        self.assertEqual(self.request("POST", "/api/link", {"a": ids[0], "b": ids[1], "w": 0.4})[0], 200)
        self.assertEqual(self.request("POST", "/api/reinforce", {"ids": ids})[0], 200)
        status, recall, _ = self.request("POST", "/api/recall", {
            "query": "记忆网络", "k": 5, "steps": 3, "damping": 0.6,
            "learn": True, "format": "md",
        })
        self.assertEqual(status, 200, recall)
        self.assertIn("reinforced", recall)
        self.assertIn("markdown", recall)

    def test_json_must_be_a_valid_object_with_finite_numbers(self):
        invalid = [b"{", b"[]", b"null", b'"text"', b"",
                   b'{"label":"x","impact":NaN}', b'{"label":"x","impact":Infinity}',
                   b'{"label":"x","meta":{"a":1e999}}', b'{"label":"x","label":"y"}',
                   b'{"label":"\\ud800"}',
                   b'{"label":"\xff"}']
        before = self.path.read_bytes()
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/add", raw=body)[0], 400)
        self.assertEqual(self.path.read_bytes(), before)

    def test_field_types_and_ranges_are_validated_before_mutation(self):
        invalid = [
            ("/api/add", {"label": []}),
            ("/api/add", {"label": " "}),
            ("/api/add", {"label": "x", "tags": "abc"}),
            ("/api/add", {"label": "x", "salience": True}),
            ("/api/add", {"label": "x", "impact": 1.1}),
            ("/api/add", {"label": "x", "meta": []}),
            ("/api/add", {"label": "x", "event_at": "today"}),
            ("/api/add", {"label": "x", "session_id": 2}),
            ("/api/add", {"label": "x", "meta": {"event_at": -1}}),
            ("/api/recall", {"query": "x", "k": "8"}),
            ("/api/recall", {"query": "x", "steps": -1}),
            ("/api/recall", {"query": "x", "damping": 1.1}),
            ("/api/recall", {"query": "x", "learn": "false"}),
            ("/api/link", {"a": self.first, "b": self.first, "w": -0.1}),
            ("/api/reinforce", {"ids": []}),
            ("/api/preview", {"days": -1}),
        ]
        before = self.path.read_bytes()
        for route, body in invalid:
            with self.subTest(route=route, body=body):
                self.assertEqual(self.request("POST", route, body)[0], 400)
        self.assertEqual(self.path.read_bytes(), before)

    def test_request_size_and_content_type(self):
        self.assertEqual(self.request("POST", "/api/add", raw=b"{}", headers={
            "Content-Length": str(MAX_BODY_BYTES + 1)})[0], 413)
        self.assertEqual(self.request("POST", "/api/add", raw=b"{}", headers={
            "Content-Length": "bad"})[0], 400)
        self.assertEqual(self.request("POST", "/api/add", raw=b"{}", headers={
            "Content-Type": "text/plain"})[0], 400)

    def test_unknown_routes_and_missing_nodes(self):
        self.assertEqual(self.request("GET", "/does-not-exist")[0], 404)
        self.assertEqual(self.request("POST", "/does-not-exist")[0], 404)
        self.assertEqual(self.request("OPTIONS", "/does-not-exist")[0], 404)
        self.assertEqual(self.request("GET", "/api/node")[0], 400)
        self.assertEqual(self.request("GET", "/api/node?id=missing")[0], 404)
        self.assertEqual(self.request("POST", "/api/link", {"a": self.first, "b": "missing"})[0], 404)
        self.assertEqual(self.request("POST", "/api/reinforce", {"ids": ["missing"]})[0], 404)

    def test_origin_and_host_protection(self):
        before = self.path.read_bytes()
        for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"},
                        {"Origin": f"http://127.0.0.1:{self.port + 1}"},
                        {"Host": f"evil.example:{self.port}"},
                        {"Host": "127.0.0.1:1"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", "/api/add", {"label": "拒绝"},
                                              headers=headers)[0], 403)
                self.assertEqual(self.request("GET", "/api/graph", headers=headers)[0], 403)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.request("GET", "/api/health", headers={
            "Host": f"localhost:{self.port}", "Origin": f"http://localhost:{self.port}"})[0], 200)
        self.assertEqual(self.request("OPTIONS", "/api/add", headers={
            "Origin": "https://evil.example"})[0], 403)

    def test_preview_is_read_only_and_forget_cannot_jump_into_future(self):
        before_disk = self.path.read_bytes()
        before_memory = copy.deepcopy(self.brain.to_dict())
        status, result, _ = self.request("POST", "/api/preview", {"days": 250})
        self.assertEqual(status, 200, result)
        self.assertEqual(self.path.read_bytes(), before_disk)
        self.assertEqual(self.brain.to_dict(), before_memory)
        status, error, _ = self.request("POST", "/api/forget", {"days": 250})
        self.assertEqual(status, 400)
        self.assertIn("/api/preview", error["error"])
        self.assertEqual(self.path.read_bytes(), before_disk)
        with patch.object(self.brain, "forget", wraps=self.brain.forget) as forget:
            self.assertEqual(self.request("POST", "/api/forget", {})[0], 200)
            forget.assert_called_once_with()

    def test_concurrent_writes_and_reads_share_one_operation_lock(self):
        # A short delay makes save-only locking fail deterministically: another
        # request would enter add/export while persistence is still in progress.
        active = 0
        overlap = []
        guard = threading.Lock()
        original_add = self.brain.add
        original_persist = self.brain.persist
        original_export = self.brain.export

        def add(*args, **kwargs):
            with guard:
                if active:
                    overlap.append("add during save")
            return original_add(*args, **kwargs)

        def persist():
            nonlocal active
            with guard:
                active += 1
            try:
                time.sleep(0.005)
                return original_persist()
            finally:
                with guard:
                    active -= 1

        def export(*args, **kwargs):
            with guard:
                if active:
                    overlap.append("snapshot during save")
            return original_export(*args, **kwargs)

        def work(index):
            if index % 3:
                return self.request("POST", "/api/add", {"label": f"并发节点 {index}"})[0]
            return self.request("GET", "/api/graph")[0]

        with patch.object(self.brain, "add", add), patch.object(self.brain, "persist", persist), \
                patch.object(self.brain, "export", export):
            with ThreadPoolExecutor(max_workers=8) as executor:
                statuses = list(executor.map(work, range(30)))
        self.assertEqual(statuses, [200] * 30)
        self.assertEqual(overlap, [])
        saved = Brain.open(self.path)
        self.assertEqual(len(saved.nodes), 21)
        self.assertEqual(set(saved.nodes), set(self.brain.nodes))
        for key in saved.edges:
            self.assertTrue(all(nid in saved.nodes for nid in key.split("|")))

    def test_unexpected_errors_do_not_expose_internal_details(self):
        with patch.object(self.brain, "export", side_effect=RuntimeError("secret/private/path")):
            status, result, _ = self.request("GET", "/api/graph")
        self.assertEqual(status, 500)
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("RuntimeError", json.dumps(result))

    def test_failed_persistence_rolls_back_in_memory_transaction(self):
        before_memory = copy.deepcopy(self.brain.to_dict())
        before_vectors = copy.deepcopy(self.brain._vec)
        before_disk = self.path.read_bytes()
        with patch.object(self.brain, "persist", side_effect=OSError("private/path")):
            status, error, _ = self.request("POST", "/api/add", {"label": "不能保存的节点"})
        self.assertEqual(status, 500)
        self.assertNotIn("private", json.dumps(error))
        self.assertEqual(self.brain.to_dict(), before_memory)
        self.assertEqual(self.brain._vec, before_vectors)
        self.assertEqual(self.path.read_bytes(), before_disk)

    def test_failed_response_render_does_not_commit_learning(self):
        before_memory = copy.deepcopy(self.brain.to_dict())
        before_disk = self.path.read_bytes()
        with patch("nkb.adapters.http.render.to_markdown", side_effect=RuntimeError("failed")):
            status, _, _ = self.request("POST", "/api/recall", {
                "query": "记忆网络", "learn": True, "format": "md",
            })
        self.assertEqual(status, 500)
        self.assertEqual(self.brain.to_dict(), before_memory)
        self.assertEqual(self.path.read_bytes(), before_disk)


if __name__ == "__main__":
    unittest.main()
