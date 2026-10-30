"""The simplified UI is grounded in real connection metadata, never window guesses.

All HTTP, Harness configuration and model traffic below are isolated fixtures.
No real Harness profile, credential store or personal conversation is touched.
"""
from __future__ import annotations

import json
import os
import plistlib
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller


class ConnectionOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="love-house-onboarding-")
        self.root = Path(self.temporary.name).resolve()
        self.profile = self.root / "isolated-profile"
        self.profile.mkdir()
        (self.profile / "cordis.yml").write_text("[]\n")
        self.original_patch = "# fixture comment stays\n- insert:\n    - id: fixture-other-plugin\n      name: fixture-other-plugin\n      config: {opaque_setting: KEEP-THIS-FIXTURE}\n"
        (self.profile / "cordis.patch.yml").write_text(self.original_patch)
        self.app = self.root / "Harness.app"
        (self.app / "Contents").mkdir(parents=True)
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.2.1-rc.3"}))
        self.host = MemoryHost(self.root / "data", key_store=KeyStore(allow_keychain=False),
                               adapter_options={"profile_dir": str(self.profile)})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_controller(self.host))
        self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.thread.start()
        self.client = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.host.stop()
        self.temporary.cleanup()

    def req(self, path, body=None, *, library=None, token=None):
        headers = {"Content-Type": "application/json"}
        if library:
            headers["X-NKB-Library"] = library
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(f"http://127.0.0.1:{self.server.server_port}" + path,
                          data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=headers)
        try:
            with self.client.open(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def connection(self, library="default", kind="harness", scope="next_session", provider=None):
        code, result = self.req("/api/connections", {"name": "隔离对话连接", "host": kind,
            "library_id": library, "session_scope": scope, **({"provider": provider} if provider else {})})
        self.assertEqual(code, 200, result)
        return result["connection"]["id"], result["config"]["connectionToken"]

    def event(self, cid, token, sid="existing-window-123", event="one"):
        return self.req(f"/api/connections/{cid}/events", {
            "session_id": sid, "event_id": event, "event_type": "turn/end",
            "record": {"schema": "deepseek-harness-event/v1", "normalized": {
                "type": "turn", "status": "complete", "turn_id": event,
                "user": "这是一轮临时验收对话。", "assistant": "这是临时验收回复。"}},
        }, token=token)

    def test_one_harness_action_can_plan_apply_then_show_truthful_progress(self):
        cid, token = self.connection()
        created = self.host.connections.get(cid)
        self.assertIsNone(created["configured_at"])
        self.assertFalse(created["host_online"])
        self.assertEqual(created["archive_status"], "waiting")

        route = f"/api/connections/{cid}/configure"
        code, plan = self.req(route, {"apply": False, "app_path": str(self.app)})
        self.assertEqual(code, 200, plan)
        self.assertTrue(plan["supported"])
        self.assertFalse(plan["applied"])
        self.assertIsNone(self.host.connections.get(cid)["configured_at"])
        self.assertEqual((self.profile / "cordis.patch.yml").read_text(), self.original_patch)
        self.assertFalse(Path(plan["connection_file"]).exists())

        # A single human button can perform these sequential calls; the apply
        # endpoint itself repeats validation and backs up its own patch changes.
        code, installed = self.req(route, {"apply": True, "app_path": str(self.app)})
        self.assertEqual(code, 200, installed)
        self.assertTrue(installed["applied"])
        self.assertEqual(Path(installed["backup"]).read_text(), self.original_patch)
        self.assertTrue((self.profile / "cordis.patch.yml").read_text().startswith(self.original_patch))
        if os.name != "nt":  # Windows private storage uses user ACLs, not Unix mode bits.
            self.assertEqual(Path(installed["connection_file"]).stat().st_mode & 0o777, 0o600)
        self.assertNotIn(token, json.dumps(installed))
        configured = self.host.connections.get(cid)
        self.assertIsNotNone(configured["configured_at"])
        self.assertEqual(configured["archive_status"], "waiting")

        self.assertEqual(self.req(f"/api/connections/{cid}/heartbeat", {
            "host_version": "0.2.1-rc.3", "adapter_version": "0.4.0"}, token=token)[0], 200)
        online = self.host.connections.get(cid)
        self.assertTrue(online["host_online"])
        self.assertEqual(online["session_scope"], "next_session")
        self.assertEqual(online["archive_status"], "waiting")
        self.assertEqual(self.host.connections.activity()["events"], [])

        # Window IDs come from host events, not a window-title picker. An existing
        # window can be the first human-message session after loading the plugin.
        self.assertEqual(self.event(cid, token)[0], 200)
        bound = self.host.connections.get(cid)
        self.assertEqual(bound["session_scope"], "existing-window-123")
        self.assertEqual(bound["archive_status"], "automatic_connected")
        self.assertEqual(self.event(cid, token, sid="unrelated-window", event="two")[0], 400)
        self.assertEqual(len(self.req("/api/graph")[1]["nodes"]), 1)

    def test_unsupported_harness_is_not_applied_or_reported_as_connected(self):
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "99.0.0-unverified"}))
        cid, _ = self.connection()
        code, result = self.req(f"/api/connections/{cid}/configure", {"apply": True, "app_path": str(self.app)})
        self.assertEqual(code, 400, result)
        self.assertEqual((self.profile / "cordis.patch.yml").read_text(), self.original_patch)
        self.assertIsNone(self.host.connections.get(cid)["configured_at"])
        self.assertEqual(self.host.connections.get(cid)["archive_status"], "waiting")

    def test_detect_passes_the_isolated_profile_before_the_helper_reads_anything(self):
        helper = self.root / "detect-contract"
        helper.mkdir()
        (helper / "configure.py").write_text(
            "def detect(app_path=None, profile_dir=None):\n"
            "    if profile_dir is None: raise RuntimeError('Do not inspect a default user profile in this fixture')\n"
            "    return {'detected': True, 'supported': False, 'helper_received_profile': str(profile_dir)}\n")
        with patch("nkb.service.host.harness_resources", return_value=helper):
            code, result = self.req("/api/adapters/harness/detect")
        self.assertEqual(code, 200, result)
        self.assertEqual(result["helper_received_profile"], str(self.profile))

    def test_harness_connection_address_is_not_an_api_gateway_fallback(self):
        cid, token = self.connection()
        # The form must show Harness actions here, never suggest pasting this
        # host connection's generated URL into an API client.
        code, result = self.req(f"/connections/{cid}/v1/chat/completions", {
            "messages": [{"role": "user", "content": "此请求不得被转给任何上游。"}]}, token=token)
        self.assertEqual(code, 403, result)
        self.assertEqual(self.host.connections.activity()["events"], [])

    def test_explicit_detection_is_read_only_and_custom_paths_stay_with_the_applied_connection(self):
        alternate=self.root/'another profile';alternate.mkdir()
        (alternate/'cordis.yml').write_text('[]\n')
        before=dict(self.host.adapter_options)
        code,detected=self.req('/api/adapters/harness/detect',{'app_path':str(self.app),'profile_dir':str(alternate)})
        self.assertEqual(code,200,detected)
        self.assertTrue(detected['supported'])
        self.assertEqual(detected['profile_dir'],str(alternate))
        self.assertEqual(self.host.adapter_options,before)
        self.assertFalse((alternate/'.neural-knowledge').exists())
        cid,_=self.connection()
        route=f'/api/connections/{cid}/configure'
        code,plan=self.req(route,{'apply':False,'app_path':str(self.app),'profile_dir':str(alternate)})
        self.assertEqual(code,200,plan)
        self.assertEqual(self.host.connections.host_options(cid),{})
        code,installed=self.req(route,{'apply':True,'app_path':str(self.app),'profile_dir':str(alternate)})
        self.assertEqual(code,200,installed)
        self.assertTrue(installed['applied'])
        options=self.host.connections.host_options(cid)
        self.assertEqual(options,{'app_path':str(self.app),'profile_dir':str(alternate)})
        from nkb.service.connections import ConnectionStore
        self.assertEqual(ConnectionStore(self.host.root).host_options(cid),options)
        reopened=self.host.connection_config(cid)
        self.assertEqual(reopened['host_options'],options)
        self.assertTrue(reopened['setup']['supported'])
        self.assertEqual(reopened['setup']['detected']['profile_dir'],str(alternate))
        other,_=self.connection()
        self.assertEqual(self.host.connection_config(other)['host_options']['profile_dir'],str(self.profile))
        code,paused=self.req(f'/api/connections/{cid}/enabled',{'enabled':False})
        self.assertEqual(code,200,paused)
        self.assertTrue(paused['host_change']['applied'])
        self.assertFalse(json.loads(Path(installed['connection_file']).read_text())['enabled'])
        self.assertEqual((self.profile/'cordis.patch.yml').read_text(),self.original_patch)

    def test_detect_rejects_invalid_paths_without_mutation(self):
        for value in (42,{},'\x00bad'):
            with self.subTest(value=value):
                code,result=self.req('/api/adapters/harness/detect',{'app_path':value,'profile_dir':str(self.profile)})
                self.assertEqual(code,400,result)
        self.assertEqual((self.profile/'cordis.patch.yml').read_text(),self.original_patch)

    def test_api_capture_remains_in_its_original_library_when_another_library_is_viewed(self):
        requests = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "payload": payload})
                body = json.dumps({"choices": [{"message": {"content": "来自本机模拟上游的回复。"}, "finish_reason": "stop"}]}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        try:
            other = self.req("/api/libraries", {"name": "正在浏览的空白库"})[1]["library"]["id"]
            cid, local = self.connection(scope="connection", kind="api", provider={
                "base_url": f"http://127.0.0.1:{upstream.server_port}/v1", "model": "local-test-model",
                "api_key": "FAKE-LOCAL-UPSTREAM-KEY", "save_key": False})
            self.req("/api/library/select", {"library_id": other})
            code, result = self.req(f"/connections/{cid}/v1/chat/completions", {
                "messages": [{"role": "user", "content": "只在此临时库保存的真实HTTP验收。"}]}, token=local)
            self.assertEqual(code, 200, result)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["authorization"], "Bearer FAKE-LOCAL-UPSTREAM-KEY")
            self.assertEqual(requests[0]["path"], "/v1/chat/completions")

            connections = self.req("/api/connections")[1]["connections"]
            libraries = self.req("/api/libraries")[1]
            catalog = {item["id"]: item for item in libraries["libraries"]}
            self.assertEqual(libraries["selected_id"], other)
            self.assertEqual(catalog[other]["node_count"], 0)
            self.assertEqual(catalog[connections[0]["library_id"]]["node_count"], 1)
            self.assertEqual(connections[0]["library_id"], "default")
            self.assertEqual(connections[0]["archive_status"], "automatic_connected")
            self.assertNotIn("FAKE-LOCAL-UPSTREAM-KEY", json.dumps(connections))
            # Opening the target library changes the view, not the connection.
            self.req("/api/library/select", {"library_id": "default"})
            self.assertEqual(self.host.connections.get(cid)["library_id"], "default")
            self.assertEqual(self.req("/api/graph", library=other)[1]["nodes"], [])
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
