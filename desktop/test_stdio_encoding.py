"""Real protocol subprocesses must use UTF-8 even under a legacy Windows codec."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


DESKTOP = Path(__file__).resolve().parent


class StdioEncodingTests(unittest.TestCase):
    def run_protocol(self, script, arguments, payload):
        environment = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp936:strict",
                           PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-X", "utf8=0", str(DESKTOP / script), *arguments],
                              input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=environment, timeout=15, check=False)

    def connection_config(self, root):
        path = root / "FAKE 中文连接.json"
        path.write_text(json.dumps({
            "schema": "love-house-agent-connection/v1", "connection_id": "conn_encoding_fixture",
            "library_id": "default", "token": "FAKE-NOT-A-REAL-LOCAL-TOKEN",
            "runtime_dir": str(root / "runtime"), "outbox_dir": str(root / "outbox"),
            "enabled": True, "revoked": False, "session_scope": "window_encoding",
        }, ensure_ascii=False), encoding="utf-8")
        return path

    def test_legacy_and_connection_bound_mcp_emit_utf8_json_only_under_cp936(self):
        messages = [{"jsonrpc": "2.0", "id": "FAKE-中文-🌻", "method": "initialize"},
                    {"jsonrpc": "2.0", "id": "FAKE-工具-🧠", "method": "tools/list"}]
        payload = ("\n".join(json.dumps(message, ensure_ascii=False) for message in messages) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="love-house-stdio-encoding-") as directory:
            root = Path(directory)
            configuration = self.connection_config(root)
            for script, arguments in (("harness_bridge.py", ["--runtime-dir", str(root / "legacy-runtime")]),
                                      ("agent_memory_bridge.py", ["--connection-config", str(configuration)])):
                with self.subTest(script=script):
                    response = self.run_protocol(script, arguments, payload)
                    self.assertEqual(response.returncode, 0, response.stderr.decode("utf-8", errors="replace"))
                    self.assertEqual(response.stderr, b"")
                    self.assertNotIn(b"\xef\xbb\xbf", response.stdout)
                    self.assertNotIn(b"\r", response.stdout)
                    rows = [json.loads(line) for line in response.stdout.decode("utf-8").splitlines()]
                    self.assertEqual([row["id"] for row in rows], [message["id"] for message in messages])
                    self.assertIn("memory_bootstrap", {tool["name"] for tool in rows[1]["result"]["tools"]})
                    self.assertIn("记忆".encode("utf-8"), response.stdout)

    def test_turn_hook_reads_utf8_and_queues_exact_unicode_originals_under_cp936(self):
        event = {"session_id": "window_encoding", "turn_id": "FAKE-轮次-🌻",
                 "status": "complete", "user": "FAKE用户原话：喜欢向日葵🌻，不喝咖啡。",
                 "assistant": "FAKE助手原话：已理解这个区别🧠。"}
        with tempfile.TemporaryDirectory(prefix="love-house-hook-encoding-") as directory:
            root = Path(directory)
            configuration = self.connection_config(root)
            response = self.run_protocol("agent_memory_hook.py", ["--connection-config", str(configuration)],
                                         json.dumps(event, ensure_ascii=False).encode("utf-8"))
            self.assertEqual(response.returncode, 0, response.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(response.stderr, b"")
            result = json.loads(response.stdout.decode("utf-8"))
            self.assertFalse(result["saved"])
            self.assertTrue(result["queued"])
            self.assertEqual(result["status"], "queued_offline")
            queued = list((root / "outbox").glob("*.json"))
            self.assertEqual(len(queued), 1)
            normalized = json.loads(queued[0].read_text("utf-8"))["event"]["normalized"]
            self.assertEqual(normalized["user"], event["user"])
            self.assertEqual(normalized["assistant"], event["assistant"])


if __name__ == "__main__":
    unittest.main()
