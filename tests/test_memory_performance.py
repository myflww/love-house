"""Scale and wiring regressions using synthetic memories, never personal data.

Run this file with --benchmark for descriptive timings.  Tests assert work
counts and rollback semantics rather than machine-dependent millisecond limits.
"""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import ThreadingHTTPServer
import json
from statistics import median
import sys
import threading
from time import perf_counter
import time
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.adapters.http import make_handler
from nkb.companion import dedup
from nkb.companion.ingestion import ingest_event
from nkb.companion.memory import record_turn
from nkb.companion.persona import learn_from_dialogue, persona_state
from nkb.core import transaction
from nkb.errors import ValidationError


def synthetic_brain(count=4000):
    seed = Brain.new()
    nid = seed.add("合成对话", "合成测试：今天一起整理书桌，之后喝一杯不加糖的红茶。",
                   kind="episode", salience=.55, session_id="synthetic-only",
                   meta={"source": "conversation_turn", "important": False,
                         "assistant_reply": "这是合成助手原文，用于本次离线性能复核，不涉及真实聊天。" * 3})
    data = seed.to_dict()
    row = deepcopy(data["nodes"][nid])
    data["nodes"] = {}
    for index in range(count):
        node = deepcopy(row)
        node["id"] = f"turn_synthetic_{index:05d}"
        node["label"] = f"合成对话{index}"
        node["created"] += index * .000001
        node["text"] += str(index)
        data["nodes"][node["id"]] = node
    return Brain(data)


def event(**extra):
    return {"connection_id": "synthetic-connection", "session_id": "synthetic-session",
            "turn_id": "synthetic-new", "user": "合成新对话", "assistant": "合成回复",
            "type": "turn", "status": "complete", **extra}


class MemoryPerformanceTests(unittest.TestCase):
    def test_persona_learning_projects_only_recent_100_turns_without_exporting_the_graph(self):
        brain = synthetic_brain()
        rows = list(brain.nodes.values())
        rows[-2]["text"] = "我希望你说话温柔一点"
        rows[-1]["text"] = "以后请你语气温柔一些"
        before = deepcopy(brain.nodes)
        with patch.object(brain, "export", side_effect=AssertionError("must not export graph")), \
                patch.object(brain, "_node_state", wraps=brain._node_state) as states:
            result = learn_from_dialogue(brain)
        self.assertTrue(result["changed"])
        self.assertEqual(states.call_count, 100)
        self.assertEqual(brain.nodes, before)
        learned = persona_state(brain)["learned"]["tone"]
        self.assertEqual(learned["value"], "gentle")
        self.assertEqual(learned["evidence_ids"], [rows[-2]["id"], rows[-1]["id"]])

    def test_persona_learning_still_rechecks_lifecycle_and_ignores_nonturn_nodes(self):
        brain = synthetic_brain(6)
        rows = list(brain.nodes.values())
        for node in rows:
            node["text"] = "我希望你说话温柔一点"
        rows[0]["meta"]["source"] = "local"
        rows[1]["meta"]["memory_disabled"] = True
        rows[2]["valid_from"] = rows[2]["created"] + 100000
        rows[3]["valid_to"] = rows[3]["created"] - 1
        # One valid statement plus an ignored statement must not become two.
        state = persona_state(brain)
        state["learning_ignored_ids"] = [rows[5]["id"]]
        brain.meta["companion_persona"] = state
        self.assertFalse(learn_from_dialogue(brain)["changed"])
        self.assertEqual(persona_state(brain)["learned"], {})

    def test_completed_event_runs_duplicate_annotation_once_and_replay_does_not_run_it(self):
        brain = synthetic_brain()
        with patch.object(dedup, "annotate_turn_recording", wraps=dedup.annotate_turn_recording) as annotations:
            first = ingest_event(brain, event())
            self.assertEqual(annotations.call_count, 1)
            replay = ingest_event(brain, event())
            self.assertEqual(annotations.call_count, 1)
        self.assertFalse(first["duplicate"])
        self.assertTrue(replay["duplicate"])

    def test_single_pass_keeps_cross_capture_identity_and_archive_receipt_sources(self):
        brain = Brain.new()
        manual = record_turn(brain, "同一段原文", "同一段回复", "window-one", "manual",
                             external_session_id="window-one")
        result = ingest_event(brain, event(user="同一段原文", assistant="同一段回复",
                                          source_session_id="window-one", origin="harness_hook",
                                          evidence={"archive_receipt_id": "synthetic-receipt"}))
        passive = result["record_node_ids"][0]
        self.assertEqual(result["node_ids"], [passive])
        self.assertTrue(dedup.is_duplicate(brain.get(manual), brain))
        self.assertEqual(brain.get(passive)["meta"]["evidence"]["archive_receipt_id"], "synthetic-receipt")
        sources = brain.get(manual)["meta"]["recording_sources"]
        self.assertTrue(any(item.get("archive_receipt_id") == "synthetic-receipt" for item in sources))
        # An identical pair in an unrelated window remains independent.
        other = record_turn(brain, "同一段原文", "同一段回复", "window-two", "manual")
        self.assertFalse(dedup.is_duplicate(brain.get(other), brain))

    def test_standalone_failure_restores_old_nodes_and_alias_annotations(self):
        brain = Brain.new()
        record_turn(brain, "同一段原文", "同一段回复", "window-one", "manual")
        before = deepcopy(brain.to_dict())
        vectors = deepcopy(brain._vec)
        with self.assertRaises(ValidationError):
            ingest_event(brain, event(user="同一段原文", assistant="同一段回复",
                                     source_session_id="window-one", proposals="invalid"))
        self.assertEqual(brain.to_dict(), before)
        self.assertEqual(brain._vec, vectors)
        # The failed context was cleaned up, so a later standalone call works.
        self.assertFalse(ingest_event(brain, event())["duplicate"])

    def test_controller_transaction_has_one_snapshot_and_failed_save_restores_everything(self):
        brain = synthetic_brain()
        handler = make_handler(brain)
        before = deepcopy(brain.to_dict())
        vectors = deepcopy(brain._vec)
        with patch.object(transaction, "deepcopy", wraps=transaction.deepcopy) as snapshots, \
                patch.object(brain, "persist", side_effect=OSError("synthetic disk failure")), \
                self.assertRaises(OSError):
            handler.memory_transaction(lambda current: ingest_event(current, event()))
        self.assertEqual(snapshots.call_count, 1)
        self.assertEqual(brain.to_dict(), before)
        self.assertEqual(brain._vec, vectors)
        self.assertIs(brain.half_life, brain.config.half_life)

    def test_caught_nested_failure_cannot_be_committed_by_an_outer_callback(self):
        brain = Brain.new()
        before = deepcopy(brain.to_dict())
        def callback(current):
            try:
                ingest_event(current, event(proposals="invalid"))
            except ValidationError:
                pass
            current.meta["must_not_commit"] = True
            return {"ok": True}
        with patch.object(brain, "persist", wraps=brain.persist) as saved, self.assertRaises(ValidationError):
            make_handler(brain).memory_transaction(callback)
        saved.assert_not_called()
        self.assertEqual(brain.to_dict(), before)

    def test_invalid_response_rolls_back_all_transaction_state_before_persistence(self):
        for invalid in (float("nan"), {"set"}, "\ud800"):
            with self.subTest(kind=type(invalid).__name__):
                brain = Brain.new(name="原始名字")
                brain.add("旧节点", "旧内容")
                before = deepcopy(brain.to_dict())
                vectors = deepcopy(brain._vec)
                def callback(current):
                    current.name = "不能留下的名字"
                    current.config.k = 42
                    current.half_life["episode"] = 1
                    current.add("不能留下的新节点", "合成新内容")
                    return {"unsupported": invalid}
                with patch.object(brain, "persist", wraps=brain.persist) as saved, self.assertRaises(ValidationError):
                    make_handler(brain).memory_transaction(callback)
                saved.assert_not_called()
                self.assertEqual(brain.to_dict(), before)
                self.assertEqual(brain._vec, vectors)
                self.assertIs(brain.half_life, brain.config.half_life)

    def test_same_brain_transactions_are_serialized_across_threads_with_independent_guards(self):
        brain = Brain.new()
        handler = make_handler(brain)
        barrier = threading.Barrier(4)
        def run(_):
            barrier.wait(timeout=3)
            for _ in range(5):
                def callback(current):
                    number = current.meta.get("synthetic_counter", 0)
                    time.sleep(.001)
                    current.meta["synthetic_counter"] = number + 1
                    return {"count": number + 1}
                handler.memory_transaction(callback)
        with patch.object(transaction, "deepcopy", wraps=transaction.deepcopy) as snapshots:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(run, range(4)))
        self.assertEqual(brain.meta["synthetic_counter"], 20)
        self.assertEqual(snapshots.call_count, 20)

    def test_http_response_encoding_failure_does_not_save_the_mutation(self):
        brain = Brain.new()
        handler = make_handler(brain)
        original = handler._route_post
        before = deepcopy(brain.to_dict())
        def invalid_response(instance, path, data):
            original(instance, path, data)
            return {"invalid": {"synthetic_set"}}
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            with patch.object(handler, "_route_post", new=invalid_response), \
                    patch.object(brain, "persist", wraps=brain.persist) as saved:
                client.request("POST", "/api/add", body=json.dumps({"label": "不能留下的新增"}),
                               headers={"Content-Type": "application/json"})
                response = client.getresponse()
                result = json.loads(response.read())
            self.assertEqual(response.status, 400, result)
            self.assertIn("未保存", result["error"])
            saved.assert_not_called()
            self.assertEqual(brain.to_dict(), before)
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)

    def test_http_ingest_uses_one_snapshot_for_4000_node_graph(self):
        brain = synthetic_brain()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(brain))
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            with patch.object(transaction, "deepcopy", wraps=transaction.deepcopy) as snapshots, \
                    patch.object(dedup, "annotate_turn_recording", wraps=dedup.annotate_turn_recording) as annotations:
                client.request("POST", "/api/ingest", body=json.dumps(event()).encode(),
                               headers={"Content-Type": "application/json"})
                response = client.getresponse()
                result = json.loads(response.read())
            self.assertEqual(response.status, 200, result)
            self.assertEqual(snapshots.call_count, 1)
            self.assertEqual(annotations.call_count, 1)
            self.assertEqual(len(brain.nodes), 4001)
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)


def benchmark():
    brain = synthetic_brain()
    def measure(callback):
        values = []
        for _ in range(3):
            started = perf_counter()
            callback()
            values.append((perf_counter() - started) * 1000)
        return round(median(values), 2)
    # Full snapshots are deliberately retained once: this is a removed-work
    # optimization, not an unverified incremental transaction rewrite.
    result = {"fixture": "4000 short synthetic turns, 0 edges; no persistence/network",
              "nodes": len(brain.nodes), "rounds": 3,
              "rollback_snapshot_ms": measure(lambda: deepcopy({k: getattr(brain, k) for k in transaction._FIELDS})),
              "persona_learning_ms": measure(lambda: learn_from_dialogue(brain))}
    from nkb.companion.catalog import memory_bootstrap, memory_catalog, memory_read
    result.update({"catalog_ms": measure(lambda: memory_catalog(brain, "default", "合成库", limit=25)),
                   "memory_read_ms": measure(lambda: memory_read(brain, "default", "合成库", memory_id=next(iter(brain.nodes)))),
                   "bootstrap_ms": measure(lambda: memory_bootstrap(brain, "default", "合成库", max_chars=12000)),
                   "brain_rebuild_ms": measure(lambda: Brain(brain.to_dict())),
                   "recall_ms": measure(lambda: brain.recall("红茶"))})
    result["completed_event_ms"] = measure(lambda: ingest_event(brain, event(turn_id=str(perf_counter()))))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    benchmark() if "--benchmark" in sys.argv else unittest.main()
