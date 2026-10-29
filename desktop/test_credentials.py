"""Credential tests use fake helper storage and fresh FAKE scope IDs only."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nkb.service.credentials import KeyStore, KeyStoreError  # noqa: E402
from nkb.service import credentials  # noqa: E402


@unittest.skipIf(os.name == "nt", "POSIX executable fake-helper contract; Windows WinCred is covered by test_credentials_windows")
class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fake-credential-test-")
        self.directory = Path(self.temp.name)
        self.state = self.directory / "FAKE-state.json"
        self.helper = self.directory / "FAKE-helper"
        self.helper.write_text("#!/usr/bin/python3\n" +
            "import json,sys\nfrom pathlib import Path\n" +
            "state=Path(" + repr(str(self.state)) + ")\n" +
            "data=json.loads(state.read_text()) if state.exists() else {}\n" +
            "request=json.load(sys.stdin)\nassert len(sys.argv)==1\n" +
            "op=request['op'];account=request['account']\n" +
            "if op=='set': data[account]=request['value'];response={'ok':True}\n" +
            "elif op=='get': response={'ok':True,'found':account in data,'value':data.get(account,'')}\n" +
            "elif op=='delete': data.pop(account,None);response={'ok':True}\n" +
            "else: response={'ok':False}\n" +
            "state.write_text(json.dumps(data));print(json.dumps(response))\n", encoding="utf-8")
        self.helper.chmod(0o700)
        self.scope = "FAKE-ONLY-" + uuid.uuid4().hex
        self.store = KeyStore(helper=self.helper, allow_source_build=False)

    def tearDown(self):
        self.temp.cleanup()

    def ref(self, provider="fake-provider", library="fake-library", connection="fake-connection"):
        return {"provider": provider, "library_id": library, "connection_id": connection, "test_id": self.scope}

    def test_persisted_set_get_delete_and_ui_metadata_never_returns_value(self):
        ref = self.ref()
        key = "FAKE-NOT-A-PROVIDER-KEY-" + uuid.uuid4().hex
        metadata = self.store.set(ref, key)
        self.assertEqual(metadata, {"storage": "keychain", "key_saved": True, "credential_ready": True})
        self.assertEqual(set(metadata), {"storage", "key_saved", "credential_ready"})
        self.assertNotIn(key, json.dumps(metadata))
        self.assertEqual(self.store.get(ref), key)
        self.assertEqual(self.store.metadata(ref), metadata)
        self.assertFalse(self.store.delete(ref)["credential_ready"])
        self.assertEqual(self.store.get(ref), "")
        self.assertEqual(json.loads(self.state.read_text()), {})

    def test_provider_library_and_connection_are_independent(self):
        self.store.set(self.ref(), "FAKE-A")
        self.store.set(self.ref(connection="other"), "FAKE-B")
        self.assertEqual(self.store.get(self.ref()), "FAKE-A")
        self.assertEqual(self.store.get(self.ref(connection="other")), "FAKE-B")
        self.assertEqual(self.store.get(self.ref(library="other")), "")
        self.assertEqual(self.store.get(self.ref(provider="other")), "")
        self.assertEqual(self.store.get(dict(reversed(list(self.ref().items())))), "FAKE-A")

    def test_unavailable_keychain_falls_back_truthfully_to_process_session(self):
        store = KeyStore(helper=self.directory / "does-not-exist", allow_source_build=False)
        ref = self.ref()
        self.assertEqual(store.set(ref, "FAKE-SESSION"), {"storage": "session", "key_saved": False, "credential_ready": True})
        self.assertEqual(store.get(ref), "FAKE-SESSION")
        other_instance = KeyStore(allow_keychain=False)
        self.assertEqual(other_instance.get(ref), "FAKE-SESSION")
        other_instance.delete(ref)
        self.assertEqual(store.get(ref), "")

    def test_wrong_or_empty_scope_does_not_fall_back_to_any_environment_key(self):
        with self.assertRaises(ValueError):
            self.store.set("", "FAKE")
        with self.assertRaises(ValueError):
            self.store.set({"provider": "fake"}, "FAKE")
        with self.assertRaises(ValueError):
            self.store.set(self.ref(), "", persist=True)
        self.assertEqual(self.store.get(self.ref()), "")

    def test_fresh_source_metadata_and_get_do_not_compile_or_spawn(self):
        fresh = self.directory / "fresh-source"
        (fresh / "desktop").mkdir(parents=True)
        (fresh / "desktop/Keychain.swift").write_text("// Fresh, deliberately uncompiled fingerprint " + uuid.uuid4().hex)
        store = KeyStore(allow_source_build=True)
        with patch.object(credentials, "_SOURCE_ROOT", fresh), patch.object(credentials.subprocess, "run", side_effect=AssertionError("read attempted a subprocess")):
            started = time.monotonic()
            self.assertEqual(store.metadata(self.ref()), {"storage": "none", "key_saved": False, "credential_ready": False})
            self.assertEqual(store.get(self.ref()), "")
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertFalse((fresh / "desktop/.build").exists())

    def test_unwritable_source_helper_falls_back_without_claiming_persistence(self):
        store = KeyStore(allow_source_build=True)
        ref = self.ref()
        with patch.object(credentials, "_source_helper", side_effect=PermissionError("FAKE-read-only-source")):
            self.assertEqual(store.set(ref, "FAKE-READONLY"), {"storage": "session", "key_saved": False, "credential_ready": True})
            self.assertEqual(store.get(ref), "FAKE-READONLY")
        KeyStore(allow_keychain=False).delete(ref)


if __name__ == "__main__":
    unittest.main()
