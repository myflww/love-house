"""Real disposable HTTP boundaries for historical-chat import."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from http.server import ThreadingHTTPServer

from nkb import Brain
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller


class DialogueImportHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="love-house-chat-import-test-")
        self.root = Path(self.temp.name)
        self.host = MemoryHost(self.root, key_store=KeyStore(allow_keychain=False),
                               organizer_transport=Mock(side_effect=AssertionError("No model calls during import")))
        self.host.organizer.stop()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_controller(self.host))
        self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.client = build_opener(ProxyHandler({}))
        self.other = self.host.manager.create_library("另一只独立的鱼")["id"]
        self.host.port_for("default")
        self.host.port_for(self.other)
        self.payload = {"name": "旧窗口.json", "format": "json", "content": json.dumps({"id": "historical-window",
            "messages": [{"role": "user", "content": "我的旧约定是周六去看海。", "timestamp": 1700000000},
                         {"role": "assistant", "content": "当然，我也很期待。", "timestamp": 1700000001}]}, ensure_ascii=False)}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.host.stop(); self.temp.cleanup()

    def req(self, path, body, library="default", token=None):
        headers = {"Content-Type": "application/json", "X-NKB-Library": library}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(f"http://127.0.0.1:{self.server.server_port}" + path,
                          data=json.dumps(body, ensure_ascii=False).encode(), headers=headers)
        try:
            with self.client.open(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def preview(self, payload=None, library="default"):
        status, result = self.req("/api/dialogue-import/preview", payload or self.payload, library)
        self.assertEqual(status, 200, result)
        return result

    def apply(self, payload=None, library="default"):
        payload = payload or self.payload
        preview = self.preview(payload, library)
        return self.req("/api/dialogue-import/apply", {**payload, "confirm": True,
                        "expected_fingerprint": preview["fingerprint"]}, library)

    def test_preview_is_read_only_in_memory_and_on_disk(self):
        before = self.host.snapshot("default")
        disk = self.host.manager.path_for("default").read_bytes()
        result = self.preview()
        self.assertTrue(result["read_only"])
        self.assertEqual(result["added"], 1)
        self.assertEqual(self.host.snapshot("default"), before)
        self.assertEqual(self.host.manager.path_for("default").read_bytes(), disk)

    def test_apply_requires_both_confirmation_and_content_fingerprint(self):
        preview = self.preview()
        for extra in [{}, {"confirm": True}, {"confirm": True, "expected_fingerprint": "wrong"},
                      {"confirm": False, "expected_fingerprint": preview["fingerprint"]}]:
            with self.subTest(extra=extra):
                self.assertEqual(self.req("/api/dialogue-import/apply", {**self.payload, **extra})[0], 400)
                self.assertFalse(self.host.snapshot("default")["nodes"])

    def test_success_persists_exactly_once_and_does_not_learn_persona(self):
        preview = self.preview()
        calls = []
        original = Brain.persist
        def persist(brain):
            calls.append(brain.path)
            return original(brain)
        with patch.object(Brain, "persist", persist), \
             patch("nkb.companion.persona.learn_from_dialogue", side_effect=AssertionError("Do not infer persona during import")):
            status, result = self.req("/api/dialogue-import/apply", {**self.payload, "confirm": True,
                                      "expected_fingerprint": preview["fingerprint"]})
        self.assertEqual(status, 200, result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], self.host.manager.path_for("default"))
        saved = self.host.snapshot("default")
        reopened = Brain.open(calls[0])
        self.assertEqual(len(reopened.nodes), 1)
        self.assertNotIn("companion_persona", saved["meta"])
        node = next(iter(saved["nodes"].values()))
        self.assertEqual(node["event_at"], 1700000000)
        self.assertEqual(node["meta"]["provenance"], "imported_record")
        self.assertFalse(node["meta"]["confirmed"])
        self.assertEqual(len(node["meta"]["import_messages"]), 2)

    def test_persist_failure_rolls_back_entire_memory_batch_and_old_disk(self):
        self.host.transact("default", lambda b: b.add("不能丢失的旧记忆", "原文", impact=.9, session_id="old"))
        before = self.host.snapshot("default")
        path = self.host.manager.path_for("default")
        disk = path.read_bytes()
        preview = self.preview()
        with patch.object(Brain, "persist", side_effect=OSError("fake disk full")):
            status, _ = self.req("/api/dialogue-import/apply", {**self.payload, "confirm": True,
                                    "expected_fingerprint": preview["fingerprint"]})
        self.assertEqual(status, 500)
        self.assertEqual(self.host.snapshot("default"), before)
        self.assertEqual(path.read_bytes(), disk)
        self.assertEqual(self.apply()[0], 200)

    def test_graph_selected_library_never_changes_explicit_import_target(self):
        self.host.manager.select(self.other)
        other_before = self.host.snapshot(self.other)
        status, result = self.apply()
        self.assertEqual(status, 200, result)
        self.assertEqual(len(self.host.snapshot("default")["nodes"]), 1)
        self.assertEqual(self.host.snapshot(self.other), other_before)
        # Same file intentionally imported into another identity remains local.
        self.assertEqual(self.apply(library=self.other)[0], 200)
        self.assertEqual(len(self.host.snapshot(self.other)["nodes"]), 1)

    def test_bearer_cannot_call_desktop_import_or_override_library(self):
        connection = self.host.new_connection({"host": "agent", "name": "isolated", "library_id": "default",
                                               "session_scope": "connection"})["connection"]
        token = self.host.connections.get(connection["id"], secret=True)["token"]
        for path in ("/api/dialogue-import/preview", "/api/dialogue-import/apply"):
            self.assertEqual(self.req(path, self.payload, self.other, token)[0], 403)
        self.assertEqual(self.req("/api/dialogue-import/preview", {**self.payload, "library_id": self.other})[0], 400)
        self.assertFalse(self.host.snapshot("default")["nodes"])
        self.assertFalse(self.host.snapshot(self.other)["nodes"])

    def test_repeat_import_is_idempotent_and_forget_cannot_resurrect(self):
        status, first = self.apply()
        self.assertEqual(status, 200, first)
        self.assertEqual(self.apply()[1]["added"], 0)
        self.host.forget_memory("default", first["ids"][0])
        status, repeated = self.apply()
        self.assertEqual(status, 200, repeated)
        self.assertEqual(repeated["added"], 0)
        self.assertFalse(self.host.snapshot("default")["nodes"])

    def test_full_capacity_rejects_import_without_evicting_old_memory(self):
        def fill(brain):
            brain.config.max_nodes = 1
            brain.add("保留旧节点", "不能因导入驱逐")
        self.host.transact("default", fill)
        before = self.host.snapshot("default")
        self.assertEqual(self.req("/api/dialogue-import/preview", self.payload)[0], 400)
        self.assertEqual(self.host.snapshot("default"), before)

    def test_payload_change_after_preview_is_rejected(self):
        preview = self.preview()
        status, _ = self.req("/api/dialogue-import/apply", {**self.payload,
                            "content": self.payload["content"].replace("看海", "看山"),
                            "confirm": True, "expected_fingerprint": preview["fingerprint"]})
        self.assertEqual(status, 400)
        self.assertFalse(self.host.snapshot("default")["nodes"])

    @unittest.skipUnless(shutil.which("node"), "Node optional for UI behavior checks")
    def test_actual_async_ui_preview_confirm_and_stale_library_guards(self):
        script = Path(__file__).parent / "js/dialogue-import-ui.test.cjs"
        result = subprocess.run([shutil.which("node"), "--test", str(script)], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
