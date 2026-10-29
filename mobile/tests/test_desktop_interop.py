"""Synthetic real desktop ShareStore <-> browser store migration, without personal files."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from nkb import Brain, Config
from nkb.companion.memory import save_profile
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost
from nkb.service.sharing import ShareStore, prepare_share

FIXTURE = Path(__file__).parent / "fixtures" / "desktop-share.json"
NODE = shutil.which("node")


def synthetic_desktop_package():
    brain = Brain.new(name="一只鱼 · 手机迁移", config=Config(half_life={"episode": 120}, recovery_days=365))
    turn = brain.add("无糖茶的一天🙂", "我喜欢无糖茶。原文 e\u0301 / é 不合并🙂", id="n_turn", kind="episode", meta={
        "source": "companion", "assistant_reply": "我记住啦。\n❤️", "speaker": "user",
        "evidence": {"archive_receipt_id": "receipt_one", "event_id": "原轮次"},
        "custom_original": {"quote": "原始元数据完整保留", "order": [3, 1, 2]},
    })
    fact = brain.add("饮品偏好", "用户偏爱无糖茶", id="n_fact", kind="preference", meta={
        "source": "organizer", "memory_disabled": True,
        "organizer_evidence": [{"id": turn, "role": "user", "quote": brain.nodes[turn]["text"]}],
        "memory_atom": {"evidence": [{"id": turn, "role": "user", "quote": "我喜欢无糖茶。"}], "confidence": 0.91},
    })
    brain.nodes[turn]["valid_to"] = 1234567.0
    brain.nodes[turn]["superseded_by"] = fact
    brain.link(turn, fact, 0.5)
    save_profile(brain, name="小鱼", persona="语气温柔。", user_name="朋友")
    archives = [{"id": "receipt_one", "library_id": "only", "connection_id": "synthetic_private_connection",
                 "session_id": "原窗口", "kind": "turn", "status": "saved", "received": 1234.0, "applied": 1235.0,
                 "node_ids": json.dumps([turn]), "payload": json.dumps({"session_id": "原窗口", "event_id": "原轮次", "normalized": {
                     "type": "turn", "user": brain.nodes[turn]["text"], "assistant": brain.nodes[turn]["meta"]["assistant_reply"], "status": "complete"}}, ensure_ascii=False)}]
    return prepare_share(deepcopy(brain.to_dict()), archives, library_id="only", name=brain.name, created=123456.0)


@unittest.skipUnless(NODE, "Node.js is required for the real mobile module")
class MobileDesktopInteropTests(unittest.TestCase):
    def mobile(self, value, action="roundtrip"):
        result = subprocess.run([NODE, str(Path(__file__).parent / "interop.mjs"), action], input=json.dumps(value, ensure_ascii=False),
                                encoding="utf-8", capture_output=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_checked_in_fixture_is_a_real_desktop_share(self):
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        checked = ShareStore._read(json.dumps(source, ensure_ascii=False))
        self.assertEqual(checked["counts"]["node_count"], 2)
        self.assertEqual(checked["memory"]["nodes"]["n_turn"]["meta"]["assistant_reply"], "我记住啦。\n❤️")

    def test_desktop_to_mobile_to_desktop_preserves_evidence_and_imports_idle(self):
        source = synthetic_desktop_package()
        mobile = self.mobile(source)
        package = mobile["package"]
        checked = ShareStore._read(json.dumps(package, ensure_ascii=False))
        self.assertEqual(checked["memory"]["nodes"]["n_turn"]["text"], source["memory"]["nodes"]["n_turn"]["text"])
        self.assertEqual(checked["memory"]["nodes"]["n_fact"]["meta"], source["memory"]["nodes"]["n_fact"]["meta"])
        self.assertEqual(checked["memory"]["nodes"]["n_turn"]["meta"]["custom_original"], source["memory"]["nodes"]["n_turn"]["meta"]["custom_original"])
        self.assertEqual(checked["memory"]["meta"]["companion_profile"], source["memory"]["meta"]["companion_profile"])
        self.assertEqual(checked["memory"]["edges"], source["memory"]["edges"])
        self.assertNotEqual(package["archives"][0]["id"], "receipt_one")
        self.assertEqual(package["memory"]["nodes"]["n_turn"]["meta"]["evidence"]["archive_receipt_id"], package["archives"][0]["id"])
        with tempfile.TemporaryDirectory() as directory:
            host = MemoryHost(Path(directory), key_store=KeyStore(allow_keychain=False))
            try:
                before = host.snapshot("default")
                imported = ShareStore(host).import_file(json.dumps(package, ensure_ascii=False))
                lid = imported["library"]["id"]
                self.assertNotEqual(lid, "default")
                self.assertFalse(imported["connections_rebound"])
                self.assertFalse(imported["organizer_enabled"])
                self.assertEqual(host.connections.list(lid), [])
                self.assertEqual(host.snapshot("default"), before)
                snapshot = host.snapshot(lid)
                self.assertEqual(snapshot["nodes"]["n_turn"]["text"], source["memory"]["nodes"]["n_turn"]["text"])
                self.assertFalse(snapshot["meta"]["organizer_profile"]["enabled"])
                self.assertTrue(snapshot["nodes"]["n_fact"]["meta"]["memory_disabled"])
            finally:
                host.stop()

    def test_mobile_manual_original_text_is_importable_by_desktop(self):
        record = {"title": "手机上的记忆🙂", "text": "一行原文\n第二行 e\u0301 / é", "assistant": "助手原话❤️", "tags": ["旅行", "朋友"]}
        package = self.mobile(record, "manual")["package"]
        checked = ShareStore._read(json.dumps(package, ensure_ascii=False))
        node = next(iter(checked["memory"]["nodes"].values()))
        self.assertEqual(node["text"], record["text"])
        self.assertEqual(node["meta"]["assistant_reply"], record["assistant"])
        self.assertEqual(node["tags"], record["tags"])
        self.assertEqual(checked["counts"]["node_count"], 1)

    def test_mobile_delete_cannot_restore_original_source_from_hidden_archive(self):
        source = synthetic_desktop_package()
        package = self.mobile({"package": source, "deleteId": "n_turn"})["package"]
        checked = ShareStore._read(json.dumps(package, ensure_ascii=False))
        self.assertEqual(checked["memory"]["nodes"], {})
        self.assertEqual(checked["memory"]["edges"], {})
        self.assertEqual(checked["archives"], [])


if __name__ == "__main__":
    if sys.argv[1:] == ["--write-fixture"]:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(synthetic_desktop_package(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        unittest.main()
