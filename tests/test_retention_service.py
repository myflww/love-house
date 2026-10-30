"""Real local HTTP and transaction wiring for adaptive personal-memory policy."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from http.server import ThreadingHTTPServer

from nkb import Brain
from nkb.errors import StorageError
from nkb.libraries import LibraryManager
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller
from nkb.utils import DAY


class RetentionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="love-house-retention-service-")
        self.root = Path(self.temp.name)
        manager = LibraryManager(self.root)
        self.other = manager.create_library("另一只独立的鱼")["id"]
        self.node_id = "same-opaque-node-id"
        self.created = time.time() - 3 * DAY
        self.texts = {"default": "默认存档的专属约定是周六一起去看海", self.other: "另一份独立存档只去山里看星星"}
        self.original_nodes = {}
        for library_id, text in self.texts.items():
            brain = Brain.open(manager.path_for(library_id))
            brain.add("一起去看海的专属约定" if library_id == "default" else "独立存档的山里约定", text,
                      kind="fact", id=self.node_id, salience=.8,
                      meta={"source": "user_confirmed", "confirmed": True})
            node = brain.nodes[self.node_id]
            for field in ("created", "reinforced", "decay_at", "event_at", "valid_from"):
                node[field] = self.created
            brain.save()
            self.original_nodes[library_id] = deepcopy(brain.nodes)
        self.transport = Mock(side_effect=AssertionError("Retention never calls a model"))
        self.host = MemoryHost(self.root, key_store=KeyStore(allow_keychain=False), organizer_transport=self.transport)
        self.host.organizer.stop()
        self.host.port_for("default"); self.host.port_for(self.other)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_controller(self.host))
        self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.client = build_opener(ProxyHandler({}))
        self.connections = {}
        for library in self.texts:
            result = self.host.new_connection({"host": "agent", "name": "固定存档测试连接", "library_id": library,
                                               "session_scope": "connection"})
            cid = result["connection"]["id"]
            self.connections[library] = (cid, self.host.connections.get(cid, secret=True)["token"])

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.host.stop(); self.temp.cleanup()

    def req(self, path, body=None, *, library="default", token=None):
        headers = {"X-NKB-Library": library}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(f"http://127.0.0.1:{self.server.server_port}" + path,
                          data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=headers)
        try:
            with self.client.open(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def context(self, library="default", *, header=None):
        cid, token = self.connections[library]
        return self.req(f"/api/connections/{cid}/context", {"query": self.texts[library], "session_id": "real-test-window"},
                        library=header or library, token=token)

    def queue(self, kind="recall", *, library="default", at=None):
        stamp = time.time() - 300 if at is None else at
        self.host.usage.enqueue(library, [self.node_id], kind, at=stamp)
        return self.host.usage.pending(library)

    def test_existing_personal_libraries_migrate_without_changing_any_old_node(self):
        for library in self.texts:
            snapshot = self.host.snapshot(library)
            self.assertIsNone(snapshot["config"]["max_nodes"])
            self.assertTrue(snapshot["meta"]["long_term_archive"])
            self.assertEqual(snapshot["meta"]["memory_retention"]["mode"], "adaptive")
            self.assertEqual(snapshot["nodes"], self.original_nodes[library])
            reopened = Brain.open(self.host.manager.path_for(library))
            self.assertIsNone(reopened.config.max_nodes)
            self.assertEqual(reopened.nodes, self.original_nodes[library])

    def test_authenticated_context_keeps_graph_and_disk_read_only_but_queues_usage(self):
        self.host.manager.select(self.other)
        before = self.host.snapshot("default")
        disk = self.host.manager.path_for("default").read_bytes()
        status, result = self.context()
        self.assertEqual(status, 200, result)
        records = result["memory_context"]["records"]
        self.assertIn(self.node_id, {r["id"] for r in records})
        self.assertIn(self.texts["default"], json.dumps(records, ensure_ascii=False))
        self.assertNotIn(self.texts[self.other], json.dumps(result, ensure_ascii=False))
        self.assertEqual(self.host.snapshot("default"), before)
        self.assertEqual(self.host.manager.path_for("default").read_bytes(), disk)
        pending = self.host.usage.pending("default")
        self.assertEqual([(r["node_id"], r["kind"]) for r in pending], [(self.node_id, "recall")])
        self.assertEqual(self.host.usage.pending(self.other), [])

    def test_browsing_bootstrap_catalog_read_handoff_and_preview_do_not_enqueue(self):
        before = self.host.snapshot("default")
        routes = [("/api/memory/bootstrap", {}), ("/api/memory/list", {}),
                  ("/api/memory/read", {"memory_id": self.node_id}),
                  ("/api/memory/handoff", {"profile": "S"}), ("/api/preview", {"days": 30}),
                  ("/api/retention", None)]
        for path, body in routes:
            with self.subTest(path=path):
                status, result = self.req(path, body)
                self.assertEqual(status, 200, result)
        self.assertEqual(self.host.usage.pending("default"), [])
        self.assertEqual(self.host.snapshot("default"), before)

    def test_next_same_library_transaction_applies_original_use_time_once(self):
        at = time.time() - 600
        rows = self.queue(at=at)
        writes = []
        persist = Brain.persist
        def save(brain):
            writes.append(brain.path)
            return persist(brain)
        with patch.object(Brain, "persist", save):
            self.host.transact("default", lambda brain: {"id": brain.add("真实新增的测试记忆", "新原文")})
        node = self.host.snapshot("default")["nodes"][self.node_id]
        usage = node["meta"]["memory_usage"]
        self.assertEqual(usage["last_recall_at"], at)
        self.assertEqual(usage["recall_count"], 1)
        self.assertEqual(node["text"], self.texts["default"])
        self.assertEqual(writes, [self.host.manager.path_for("default")])
        self.assertEqual(self.host.usage.pending("default"), [])
        self.assertEqual(self.host.usage.applied(rows), 0)

    def test_another_library_save_never_applies_queued_use_to_same_id_elsewhere(self):
        rows = self.queue()
        before = self.host.snapshot(self.other)
        self.host.transact(self.other, lambda brain: {"id": brain.add("另一库写入", "另一库原文")})
        node = self.host.snapshot(self.other)["nodes"][self.node_id]
        self.assertEqual(node, before["nodes"][self.node_id])
        self.assertNotIn("memory_usage", node["meta"])
        self.assertEqual(self.host.usage.pending("default"), rows)

    def test_callback_failure_keeps_graph_disk_and_usage_pending_unchanged(self):
        rows = self.queue()
        before = self.host.snapshot("default")
        disk = self.host.manager.path_for("default").read_bytes()
        def failed(brain):
            brain.add("不能半写", "FAKE failing body")
            raise RuntimeError("FAKE callback failure")
        with self.assertRaises(RuntimeError):
            self.host.transact("default", failed)
        self.assertEqual(self.host.snapshot("default"), before)
        self.assertEqual(self.host.manager.path_for("default").read_bytes(), disk)
        self.assertEqual(self.host.usage.pending("default"), rows)

    def test_persist_failure_rolls_back_use_and_body_then_pending_can_retry(self):
        rows = self.queue()
        before = self.host.snapshot("default")
        disk = self.host.manager.path_for("default").read_bytes()
        with patch.object(Brain, "persist", side_effect=OSError("FAKE disk full")):
            with self.assertRaises(OSError):
                self.host.transact("default", lambda brain: {"id": brain.add("未提交", "不能留下")})
        self.assertEqual(self.host.snapshot("default"), before)
        self.assertEqual(self.host.manager.path_for("default").read_bytes(), disk)
        self.assertEqual(self.host.usage.pending("default"), rows)
        self.host.transact("default", lambda brain: {"saved": True})
        self.assertEqual(self.host.snapshot("default")["nodes"][self.node_id]["meta"]["memory_usage"]["recall_count"], 1)

    def test_ack_failure_does_not_lie_about_http_save_and_retry_does_not_boost_twice(self):
        rows = self.queue()
        with patch.object(self.host.usage, "applied", side_effect=StorageError("FAKE journal ack unavailable")):
            status, result = self.req("/api/retention/settings", {"forgetting_pace": "gentle"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["settings"]["forgetting_pace"], "gentle")
        node = self.host.snapshot("default")["nodes"][self.node_id]
        self.assertEqual(node["meta"]["memory_usage"]["recall_count"], 1)
        self.assertEqual(self.host.usage.pending("default"), rows)
        self.assertEqual(self.req("/api/retention/settings", {"forgetting_pace": "balanced"})[0], 200)
        node = self.host.snapshot("default")["nodes"][self.node_id]
        self.assertEqual(node["meta"]["memory_usage"]["recall_count"], 1)
        self.assertEqual(self.host.usage.pending("default"), [])

    def test_connection_bearer_and_headers_cannot_use_or_configure_other_library(self):
        cid, token = self.connections["default"]
        other_token = self.connections[self.other][1]
        payload = {"query": "看海", "session_id": "test-window"}
        for path, body in [("/api/retention", None), ("/api/retention/settings", {"forgetting_pace": "fast"})]:
            self.assertEqual(self.req(path, body, library=self.other, token=token)[0], 403)
        self.assertEqual(self.req(f"/api/connections/{cid}/context", payload, library=self.other, token=token)[0], 403)
        self.assertEqual(self.req(f"/api/connections/{cid}/context", payload, token=other_token)[0], 403)
        self.assertEqual(self.req("/api/retention/settings", {"library_id": self.other})[0], 400)
        self.assertEqual(self.host.usage.pending("default"), [])
        self.assertEqual(self.host.usage.pending(self.other), [])

    def test_explicit_forget_purges_scoped_usage_and_later_save_cannot_revive_it(self):
        self.queue()
        other_rows = self.queue(library=self.other)
        self.host.forget_memory("default", self.node_id)
        self.assertEqual(self.host.usage.pending("default"), [])
        self.assertEqual(self.host.usage.pending(self.other), other_rows)
        self.assertNotIn(self.node_id, self.host.snapshot("default")["nodes"])
        self.host.transact("default", lambda brain: {"saved": True})
        self.assertNotIn(self.node_id, self.host.snapshot("default")["nodes"])
        self.assertIn(self.node_id, self.host.snapshot("default")["meta"]["memory_tombstones"]["node_ids"])

    def test_fixed_days_expiry_count_caps_and_disabling_policy_are_rejected(self):
        before = self.host.snapshot("default")
        for value in ({"days": 30}, {"recent_days": 30}, {"retention_days": 200}, {"max_nodes": 10000},
                      {"mode": "off"}, {"enabled": False}, {"forgetting_pace": "unknown"}):
            with self.subTest(value=value):
                self.assertEqual(self.req("/api/retention/settings", value)[0], 400)
        self.assertEqual(self.host.snapshot("default"), before)

    def test_usage_metadata_failure_never_blocks_context_or_actual_body_save(self):
        with patch.object(self.host.usage, "enqueue", side_effect=StorageError("FAKE journal unavailable")):
            self.assertEqual(self.context()[0], 200)
        with patch.object(self.host.usage, "pending", side_effect=StorageError("FAKE journal unavailable")):
            result = self.host.transact("default", lambda brain: {"id": brain.add("正文优先保存", "这条原文不能因usage故障丢失")})
        self.assertIn(result["id"], self.host.snapshot("default")["nodes"])
        with patch.object(self.host.usage, "counts", side_effect=StorageError("FAKE journal unavailable")):
            status, result = self.req("/api/retention")
        self.assertEqual(status, 200, result)
        self.assertFalse(result["usage"]["available"])

    def test_default_retention_settings_save_is_local_and_never_calls_model(self):
        nodes = self.host.snapshot("default")["nodes"]
        status, result = self.req("/api/retention/settings", {})
        self.assertEqual(status, 200, result)
        self.assertTrue(result["enabled"])
        self.assertFalse(result["count_eviction"])
        self.assertFalse(result["automatic_deletion"])
        self.assertIsNone(result["node_limit"])
        self.assertFalse(result["will_call_model"])
        self.assertEqual(self.host.snapshot("default")["nodes"], nodes)
        self.transport.assert_not_called()

    def test_opt_out_with_failed_ack_does_not_replay_old_use_after_reenable(self):
        self.queue()
        with patch.object(self.host.usage, "applied", side_effect=StorageError("FAKE failed opt-out ack")):
            self.assertEqual(self.req("/api/retention/settings", {"usage_reinforcement":False})[0],200)
        self.assertEqual(len(self.host.usage.pending("default")),1)
        self.assertNotIn("memory_usage", self.host.snapshot("default")["nodes"][self.node_id]["meta"])
        self.assertEqual(self.req("/api/retention/settings", {"usage_reinforcement":True})[0],200)
        node=self.host.snapshot("default")["nodes"][self.node_id]
        self.assertNotIn("memory_usage",node["meta"])
        self.assertEqual(self.host.usage.pending("default"),[])

    def test_opt_out_pending_larger_than_page_stays_discarded_after_reenable(self):
        def add_nodes(brain):
            return [brain.add('仅合成旧使用'+str(i),'测试用原文',kind='episode') for i in range(257)]
        ids=self.host.transact('default',add_nodes)
        self.host.usage.enqueue('default',ids,'recall',at=time.time())
        self.assertEqual(self.req('/api/retention/settings',{'usage_reinforcement':False})[0],200)
        # The normal pending page contains 256 records; the unseen remainder
        # must not become a practice when this user opts in again.
        self.assertEqual(len(self.host.usage.pending('default')),1)
        self.assertEqual(self.req('/api/retention/settings',{'usage_reinforcement':True})[0],200)
        snapshot=self.host.snapshot('default')
        self.assertTrue(all('memory_usage' not in snapshot['nodes'][nid]['meta'] for nid in ids))
        self.assertEqual(self.host.usage.pending('default'),[])


if __name__ == "__main__":
    unittest.main()
