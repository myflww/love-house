"""Isolated product acceptance: local mock upstreams and session-only FAKE keys."""
from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import threading
import unittest
import subprocess
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller


class ProductDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="love-house-product-test-")
        self.root = Path(self.temporary.name)
        profile = self.root / "isolated-harness-profile"
        profile.mkdir()
        (profile / "cordis.yml").write_text("[]\n")
        (profile / "cordis.patch.yml").write_text("[]\n")
        self.keys = KeyStore(allow_keychain=False)
        self.host = MemoryHost(self.root, key_store=self.keys, adapter_options={"profile_dir": str(profile)},
                               organizer_transport=Mock(side_effect=AssertionError("No real model transport is allowed")))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_controller(self.host))
        self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()
        self.client = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.host.stop()
        self.temporary.cleanup()

    def req(self, path, body=None, *, library=None, token=None, headers=None):
        request_headers = {"Content-Type": "application/json", "X-LoveHouse-Management": self.host.management_token, **(headers or {})}
        if library:
            request_headers["X-NKB-Library"] = library
        if token:
            request_headers["Authorization"] = "Bearer " + token
        request = Request(f"http://127.0.0.1:{self.server.server_port}" + path,
                          data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=request_headers)
        try:
            with self.client.open(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def connect(self, library="default", kind="harness", provider=None):
        status, result = self.req("/api/connections", {"name": "隔离交付测试", "host": kind,
                                                       "library_id": library, "session_scope": "connection",
                                                       **({"provider": provider} if provider else {})})
        self.assertEqual(status, 200, result)
        return result["connection"]["id"], result["config"]["connectionToken"]

    def event(self, cid, token, eid, user, assistant, raw=None):
        status, result = self.req(f"/api/connections/{cid}/events", {
            "session_id": "isolated-session", "event_id": eid, "event_type": "turn/end",
            "record": {"schema": "deepseek-harness-event/v1", "raw_event": raw or {"user": user},
                       "normalized": {"type": "turn", "status": "complete", "turn_id": eid, "user": user, "assistant": assistant}},
        }, token=token)
        self.assertEqual(status, 200, result)
        return result

    def test_provider_local_token_is_replaced_by_vendor_key_only_at_upstream_boundary(self):
        vendor = "FAKE-VENDOR-SECRET-FOR-LOCAL-MOCK-ONLY"
        cid, local = self.connect(kind="api", provider={"base_url": "https://mock-provider.example/v1", "model": "fake-model",
                                                       "api_key": vendor, "save_key": False})
        public = self.req("/api/connections")[1]
        self.assertNotIn(vendor, json.dumps(public))
        self.assertTrue(public["connections"][0]["provider"]["credential_ready"])
        response = {"choices": [{"message": {"content": "本机模拟回复"}, "finish_reason": "stop"}]}
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(response, ensure_ascii=False).encode())
        import nkb.service.proxy as proxy
        original = proxy.forward_chat
        with patch.object(proxy, "forward_chat", lambda handler, host, connection: original(handler, host, connection, opener=opener)):
            status, result = self.req(f"/connections/{cid}/v1/chat/completions", {
                "messages": [{"role": "user", "content": "隔离网关请求"}],
            }, token=local, headers={"X-NKB-Request-ID": "isolated-request"})
        self.assertEqual(status, 200, result)
        forwarded = opener.open.call_args.args[0]
        self.assertEqual(forwarded.get_header("Authorization"), "Bearer " + vendor)
        self.assertNotIn(local, forwarded.data.decode())
        with self.host.connections.db() as database:
            rows = database.execute("SELECT payload FROM receipts").fetchall()
            providers = database.execute("SELECT * FROM providers").fetchall()
        self.assertNotIn(vendor, json.dumps([dict(row) for row in providers]))
        self.assertTrue(rows)
        self.assertNotIn(vendor, rows[0]["payload"])
        self.assertNotIn(local, rows[0]["payload"])

    def test_bad_provider_address_does_not_leave_a_half_created_connection(self):
        invalid = ["http://remote.example/v1", "https://user:password@remote.example", "https://remote.example?api_key=FAKE",
                   "https://remote.example/#fragment", "https://remote.example:invalid", "https://[::1",
                   "https://bad host.example/v1", "https://mock.example:0/v1", "https://mock.example\n.evil/v1",
                   "https://mock.example\\evil/v1"]
        for address in invalid:
            with self.subTest(address=address):
                before = self.host.connections.list()
                status, result = self.req("/api/connections", {"name": "坏地址必须无副作用", "host": "api", "library_id": "default",
                                                               "provider": {"base_url": address, "model": "fake", "api_key": "FAKE-NOT-TO-BE-SAVED", "save_key": False}})
                self.assertEqual(status, 400, result)
                self.assertEqual(self.host.connections.list(), before)

    def test_forget_original_removes_derived_and_history_copy_but_keeps_other_source(self):
        cid, token = self.connect()
        a_text = "明确要求忘记的原文A-交付隔离测试"
        b_text = "必须保留的独立原文B-交付隔离测试"
        a = self.event(cid, token, "event-a", a_text, "ACK-A")
        b_history = {"request_messages": [
            {"role": "user", "content": a_text}, {"role": "assistant", "content": "ACK-A"}, {"role": "user", "content": b_text}]}
        b = self.event(cid, token, "event-b", b_text, "ACK-B", b_history)
        nodes = self.req("/api/graph")[1]["nodes"]
        aid = next(node["id"] for node in nodes if node["text"] == a_text)
        bid = next(node["id"] for node in nodes if node["text"] == b_text)
        rid = self.host.transact("default", lambda brain: brain.add("A+B派生", "共同派生结果", kind="reflection", meta={"members": [aid, bid]}))
        backup = self.host.backups.create("default")
        plan = self.host.forget_preview("default", aid)
        self.assertIn(aid, plan["node_ids"])
        self.assertIn(rid, plan["node_ids"])
        self.assertNotIn(bid, plan["node_ids"])
        status, result = self.req(f"/api/memories/{aid}/forget", {"confirm": True})
        self.assertEqual(status, 200, result)
        remaining = self.req("/api/graph")[1]["nodes"]
        self.assertEqual({node["id"] for node in remaining}, {bid})
        archive_b = self.host.read_archive("default", b["receipt_id"])
        self.assertIsNotNone(archive_b)
        self.assertNotIn(a_text, json.dumps(archive_b, ensure_ascii=False))
        self.assertIn(b_text, json.dumps(archive_b, ensure_ascii=False))
        self.assertIsNone(self.host.read_archive("default", a["receipt_id"]))
        self.assertFalse(Path(backup["path"]).exists())
        retry_b = self.event(cid, token, "event-b", b_text, "ACK-B", b_history)
        self.assertTrue(retry_b["duplicate"])
        self.assertNotIn(a_text, json.dumps(self.host.read_archive("default", b["receipt_id"]), ensure_ascii=False))
        self.event(cid, token, "event-a", a_text, "ACK-A")
        self.assertEqual({node["id"] for node in self.req("/api/graph")[1]["nodes"]}, {bid})

    def test_restore_creates_an_idle_new_library_without_credentials_or_connection_rebinding(self):
        library = self.req("/api/libraries", {"name": "隔离备份源"})[1]["library"]["id"]
        cid, token = self.connect(library)
        event = self.event(cid, token, "backup-event", "备份原文", "备份助手原文")
        self.host.organizer.stop()
        def settings(brain):
            brain.meta["organizer_profile"] = {"enabled": True, "provider_id": "connection:" + cid,
                                               "base_url": "https://fake.example/v1", "model": "fake"}
        self.host.transact(library, settings)
        source = copy.deepcopy(self.host.snapshot(library))
        backup = self.host.backups.create(library)
        restored = self.host.backups.restore(backup["id"], library, "隔离恢复副本")
        restored_id = restored["library"]["id"]
        self.assertNotEqual(restored_id, library)
        self.assertFalse(restored["connections_rebound"])
        self.assertEqual(self.host.connections.get(cid)["library_id"], library)
        self.assertEqual(self.host.connections.list(restored_id), [])
        fresh = self.host.snapshot(restored_id)
        self.assertFalse(fresh["meta"]["organizer_profile"]["enabled"])
        self.assertEqual(fresh["meta"]["organizer_profile"]["provider_id"], "")
        self.assertEqual(set(fresh["nodes"]), set(source["nodes"]))
        self.assertEqual(self.host.snapshot(library), source)
        new_receipt = next(iter(fresh["nodes"].values()))["meta"]["evidence"]["archive_receipt_id"]
        self.assertNotEqual(new_receipt, event["receipt_id"])
        self.assertIsNotNone(self.host.read_archive(restored_id, new_receipt))
        self.assertIsNone(self.host.read_archive(restored_id, event["receipt_id"]))
        self.assertIsNotNone(self.host.read_archive(library, event["receipt_id"]))

    def test_restored_organized_and_candidate_evidence_follow_the_new_archive(self):
        cid, token = self.connect()
        event = self.event(cid, token, "organized-backup", "我喜欢无糖茶", "收到")
        self.host.organizer.stop()
        raw = next(iter(self.host.snapshot("default")["nodes"].values()))
        evidence = {"id": raw["id"], "role": "user", "quote": "我喜欢无糖茶", "receipt_id": event["receipt_id"]}
        def add_derived(brain):
            nid = brain.add("饮品偏好", "我喜欢无糖茶", kind="preference", meta={"source":"organizer", "organizer_evidence":[copy.deepcopy(evidence)]})
            brain.meta["organizer_candidates"] = [{"id":"candidate-local", "status":"pending", "operation":{"evidence":[copy.deepcopy(evidence)]}}]
            brain.meta["audit_reference"] = {"nested":[{"receipt_id":event["receipt_id"]}], "text":event["receipt_id"]}
            return nid
        fact_id = self.host.transact("default", add_derived)
        before = self.host.snapshot("default")
        backup = self.host.backups.create("default")
        restored = self.host.backups.restore(backup["id"], "default")
        lib = restored["library"]["id"]
        fresh = self.host.snapshot(lib)
        expected = fresh["nodes"][raw["id"]]["meta"]["evidence"]["archive_receipt_id"]
        refs = [fresh["nodes"][fact_id]["meta"]["organizer_evidence"][0]["receipt_id"],
                fresh["meta"]["organizer_candidates"][0]["operation"]["evidence"][0]["receipt_id"],
                fresh["meta"]["audit_reference"]["nested"][0]["receipt_id"]]
        self.assertTrue(all(ref == expected for ref in refs))
        for ref in refs:
            status, archive = self.req("/api/activity/" + ref, library=lib)
            self.assertEqual(status,200,archive)
            self.assertEqual(archive["library_id"],lib)
        self.assertEqual(self.req("/api/activity/"+event["receipt_id"],library=lib)[0],404)
        self.assertEqual(fresh["meta"]["audit_reference"]["text"],event["receipt_id"])
        self.assertEqual(self.host.snapshot("default"),before)

    @unittest.skipIf(os.name == "nt", "POSIX shebang helper fixture; native Windows credential isolation is tested separately")
    def test_session_provider_policy_does_not_restore_an_older_persistent_key_after_process_restart(self):
        from nkb.service.providers import ProviderStore
        state = self.root / "FAKE-keychain.json"
        helper = self.root / "FAKE-keychain-helper"
        helper.write_text("#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\n" +
            "p=Path(" + repr(str(state)) + ")\nd=json.loads(p.read_text()) if p.exists() else {}\nr=json.load(sys.stdin);a=r['account']\n" +
            "if r['op']=='set':d[a]=r['value'];v={'ok':True}\n" +
            "elif r['op']=='delete':d.pop(a,None);v={'ok':True}\n" +
            "else:v={'ok':True,'value':d.get(a,'')}\n" +
            "p.write_text(json.dumps(d));print(json.dumps(v))\n")
        helper.chmod(0o700)
        fake_store = KeyStore(helper=helper, allow_source_build=False)
        self.host.providers = ProviderStore(self.host.connections, fake_store)
        cid, _ = self.connect(kind="api")
        self.host.providers.save(cid, {"api_key": "FAKE-OLD-PERSISTENT", "save_key": True})
        persistent_ref = self.host.providers.ref(cid, key_policy="persistent")
        self.assertEqual(fake_store.get(persistent_ref), "FAKE-OLD-PERSISTENT")
        self.host.providers.save(cid, {"api_key": "FAKE-NEW-SESSION", "save_key": False})
        self.assertEqual(self.host.providers.get(cid)["key_policy"], "session")
        self.assertEqual(self.host.providers.credential(cid)["api_key"], "FAKE-NEW-SESSION")
        self.assertEqual(fake_store.get(persistent_ref), "FAKE-OLD-PERSISTENT")
        self.host.providers.save(cid, {"api_key": "", "save_key": True})
        self.assertEqual(self.host.providers.get(cid)["key_policy"], "session")
        code = (
            "import json,sys\nfrom nkb.service.connections import ConnectionStore\n"
            "from nkb.service.credentials import KeyStore\nfrom nkb.service.providers import ProviderStore\n"
            "p=ProviderStore(ConnectionStore(sys.argv[1]),KeyStore(helper=sys.argv[2],allow_source_build=False))\n"
            "assert p.credential(sys.argv[3])['api_key']==''\nprint(json.dumps(p.public(sys.argv[3])))\n"
        )
        child = subprocess.run([sys.executable, "-B", "-c", code, str(self.root), str(helper), cid],
                               capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        restarted = json.loads(child.stdout)
        self.assertEqual(restarted["key_policy"], "session")
        self.assertFalse(restarted["credential_ready"])
        self.assertNotIn("FAKE-OLD-PERSISTENT", child.stdout)
        self.keys.delete(self.host.providers.ref(cid))

    @unittest.skipIf(os.name == "nt", "POSIX shebang helper fixture; native Windows credential isolation is tested separately")
    def test_remove_key_clears_session_even_if_fake_keychain_refuses_persistent_deletion(self):
        from nkb.service.providers import ProviderStore
        helper = self.root / "FAKE-keychain-refuses-delete"
        helper.write_text("#!/usr/bin/python3\nimport json,sys\nr=json.load(sys.stdin)\n"
                          "print(json.dumps({'ok':False} if r['op']=='delete' else {'ok':True,'value':''}))\n")
        helper.chmod(0o700)
        fake = KeyStore(helper=helper, allow_source_build=False)
        self.host.providers = ProviderStore(self.host.connections, fake)
        cid, _ = self.connect(kind="api")
        self.host.providers.save(cid, {"api_key": "FAKE-SESSION-MUST-CLEAR", "save_key": False})
        self.assertTrue(self.host.providers.public(cid)["credential_ready"])
        status, result = self.req(f"/api/connections/{cid}/provider", {"remove_key": True})
        self.assertEqual(status, 503, result)
        self.assertFalse(self.host.providers.public(cid)["credential_ready"])
        self.assertEqual(self.host.providers.credential(cid)["api_key"], "")
        self.assertNotIn("FAKE-SESSION-MUST-CLEAR", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
