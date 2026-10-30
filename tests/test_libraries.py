"""所有文件均位于临时目录，不读取真实个人库或Application Support。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from nkb import Brain
from nkb.companion import build_context, get_profile, ingest_event, persona_state, save_profile
from nkb.libraries import LibraryError, LibraryManager


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_new_registry_has_an_empty_default_without_demo_or_invented_persona(self):
        manager = LibraryManager(self.root)
        rows = manager.list_libraries()
        self.assertEqual([(r["id"], r["node_count"], r["is_demo"]) for r in rows], [("default", 0, False)])
        brain = manager.open("default")
        self.assertFalse(brain.meta.get("demo", False))
        self.assertEqual(get_profile(brain), {"name": "", "persona": "", "user_name": ""})
        self.assertEqual(persona_state(brain)["learned"], {})

    def test_legacy_default_is_mapped_in_place_without_changing_a_single_byte(self):
        legacy = self.root / "personal.brain.json"
        brain = Brain.new(legacy, name="原有个人库")
        brain.add("不能丢的原始记忆", "保留内容", meta={"source": "legacy"})
        save_profile(brain, name="原设定", persona="用户明确写过的人格")
        brain.save()
        before = legacy.read_bytes()
        manager = LibraryManager(self.root)
        self.assertEqual(manager.path_for("default"), legacy.resolve())
        self.assertEqual(legacy.read_bytes(), before)
        loaded = manager.open("default")
        self.assertEqual(loaded.name, "原有个人库")
        self.assertEqual(get_profile(loaded)["persona"], "用户明确写过的人格")
        self.assertEqual(legacy.read_bytes(), before)

    def test_library_profiles_context_and_transcripts_stay_isolated_after_restart(self):
        manager = LibraryManager(self.root)
        row = manager.create("第二个独立库")
        a, b = manager.open("default"), manager.open(row["id"])
        save_profile(a, persona="只属于A的人格")
        aid = a.add("A独有秘密", "A独有正文")
        ingest_event(a, {"connection_id": "same", "session_id": "same", "turn_id": "1",
                         "user": "A的用户原话", "assistant": "A的助手原话"})
        save_profile(b, persona="只属于B的人格")
        b.add("B独有秘密", "B独有正文")
        a.save(); b.save()
        reloaded = LibraryManager(self.root)
        a2, b2 = reloaded.open("default"), reloaded.open(row["id"])
        self.assertEqual(get_profile(a2)["persona"], "只属于A的人格")
        self.assertEqual(get_profile(b2)["persona"], "只属于B的人格")
        self.assertNotIn(aid, [hit["id"] for hit in b2.recall("A独有秘密")["hits"]])
        self.assertNotIn("A独有正文", build_context(b2, "A独有秘密")["packet"])
        self.assertNotIn("A的助手原话", str(build_context(b2, "用户原话")))
        self.assertEqual(sum(n.get("meta", {}).get("source") == "conversation_turn" for n in b2.nodes.values()), 0)

    def test_two_managers_reload_registry_before_mutations(self):
        first, second = LibraryManager(self.root), LibraryManager(self.root)
        a = first.create("由第一个实例建立")
        b = second.create("由第二个实例建立")
        self.assertEqual({r["id"] for r in first.list()}, {"default", a["id"], b["id"]})

    def test_unsafe_ids_and_duplicate_ids_never_overwrite_library_files(self):
        manager = LibraryManager(self.root)
        for value in ("../outside", "/tmp/x", "x.json/../y", "", "A B"):
            with self.subTest(value=value), self.assertRaises(LibraryError):
                manager.create("库", library_id=value)
        manager.create("原库", library_id="safe-slug")
        before = manager.path_for("safe-slug").read_bytes()
        with self.assertRaises(LibraryError):
            manager.create("覆盖企图", library_id="safe-slug")
        self.assertEqual(before, manager.path_for("safe-slug").read_bytes())

    def test_demo_is_registered_separately_and_cannot_receive_real_events(self):
        demo = self.root / "example.brain.json"
        Brain.new(demo, name="只有示例").save()
        manager = LibraryManager(self.root)
        manager.register_demo(demo)
        self.assertTrue(manager.get_library("demo")["read_only"])
        self.assertFalse(manager.get_library("default")["is_demo"])
        with self.assertRaises(ValueError):
            ingest_event(manager.open("demo"), {"connection_id": "c", "session_id": "s", "turn_id": "t",
                                                "user": "真实用户", "assistant": "真实回复"})

    def test_missing_library_is_not_silently_replaced_with_an_empty_one(self):
        manager = LibraryManager(self.root)
        row = manager.create("丢失文件测试")
        manager.path_for(row["id"]).unlink()
        self.assertFalse(manager.get_library(row["id"])["available"])
        with self.assertRaises(LibraryError):
            manager.open(row["id"])


if __name__ == "__main__":
    unittest.main()
