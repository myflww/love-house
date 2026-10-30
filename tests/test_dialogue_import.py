from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from nkb import Brain, Config
from nkb.companion.catalog import memory_bootstrap
from nkb.errors import ValidationError
from nkb.ingest.dialogues import import_dialogues, plan_dialogues


def export(messages, **kwargs):
    return json.dumps({"id": "old-chat-1", "title": "一起看海", "messages": messages, **kwargs}, ensure_ascii=False)


class DialogueImportTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain.new()
        self.brain.meta.update(library_id="one", long_term_archive=True)
        self.content = export([
            {"id": "u1", "role": "user", "content": "周六我们一起看海。", "timestamp": "2026-01-02T18:00:00+08:00"},
            {"id": "a1", "role": "assistant", "content": "好呀，一起看海。", "timestamp": "2026-01-02T18:01:00+08:00"}])

    def apply(self, content=None, **kwargs):
        content = self.content if content is None else content
        preview = plan_dialogues(self.brain, content=content, **kwargs)
        return import_dialogues(self.brain, content=content, confirm=True,
                                expected_fingerprint=preview["fingerprint"], **kwargs)

    def test_preview_is_pure_and_retains_roles_times_and_session(self):
        before = copy.deepcopy(self.brain.to_dict())
        result = plan_dialogues(self.brain, content=self.content)
        self.assertTrue(result["read_only"])
        self.assertEqual((result["message_count"], result["turn_count"], result["added"]), (2, 1, 1))
        self.assertEqual(result["sessions"][0]["source_id"], "old-chat-1")
        self.assertEqual(self.brain.to_dict(), before)
        self.assertFalse(result["model_calls"])

    def test_complete_turn_is_readable_historical_evidence_not_confirmed_fact(self):
        result = self.apply()
        node = self.brain.get(result["ids"][0])
        self.assertEqual(node["text"], "周六我们一起看海。")
        self.assertEqual(node["meta"]["assistant_reply"], "好呀，一起看海。")
        self.assertEqual(node["meta"]["provenance"], "imported_record")
        self.assertFalse(node["meta"]["confirmed"])
        self.assertEqual(node["event_at"], 1767348000.0)
        self.assertNotEqual(node["created"], node["event_at"])
        self.assertEqual(node["meta"]["import_messages"][1]["source_timestamp"], "2026-01-02T18:01:00+08:00")
        boot = memory_bootstrap(self.brain, "one", "一号库")
        record = boot["memory_context"]["records"][0]
        self.assertEqual(record["epistemic_status"], "historical_user_statement")
        self.assertFalse(record["assistant_statement"]["is_user_fact"])

    def test_reimport_is_idempotent_despite_filename_or_json_whitespace(self):
        first = self.apply(name="old.json")
        second = self.apply(json.dumps(json.loads(self.content), ensure_ascii=False, indent=2), name="redownload.json")
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(len(self.brain.nodes), 1)
        self.assertEqual(self.brain.get(first["ids"][0])["meta"]["import_name"], "old.json")

    def test_append_export_does_not_duplicate_previous_turn_when_session_id_present(self):
        self.apply()
        messages = json.loads(self.content)["messages"] + [
            {"role": "user", "content": "你还记得约定吗？"}, {"role": "assistant", "content": "记得。"}]
        result = self.apply(export(messages))
        self.assertEqual((result["added"], result["skipped"]), (1, 1))
        self.assertEqual(len({n["session_id"] for n in self.brain.nodes.values()}), 1)

    def test_repeated_identical_messages_at_different_positions_are_preserved(self):
        messages = [{"role": "user", "content": "晚安。"}, {"role": "assistant", "content": "晚安。"}] * 2
        result = self.apply(export(messages))
        self.assertEqual(result["added"], 2)
        self.assertEqual(len(self.brain.nodes), 2)

    def test_unpaired_user_assistant_system_and_tool_messages_are_not_fabricated_pairs(self):
        content = export([{"role": "system", "content": "这是旧窗口的角色设定，不应自动应用"},
                          {"role": "assistant", "content": "只有助手的一条旧消息"},
                          {"role": "user", "content": "缺少回复的发言"},
                          {"role": "tool", "content": "网页加载失败"}])
        preview = plan_dialogues(self.brain, content=content)
        self.assertEqual((preview["turn_count"], preview["record_count"]), (0, 4))
        self.assertIn("unpaired", {w["code"] for w in preview["warnings"]})
        self.apply(content)
        self.assertEqual({n["meta"]["speaker"] for n in self.brain.nodes.values()}, {"system", "assistant", "user", "tool"})
        self.assertNotIn("companion_persona", self.brain.meta)

    def test_missing_invalid_and_timezone_less_times_are_not_guessed(self):
        content = export([{"role": "user", "content": "甲", "timestamp": "2025-01-01 12:00:00"},
                          {"role": "assistant", "content": "乙", "timestamp": "不知道日期"},
                          {"role": "user", "content": "丙"}])
        preview = plan_dialogues(self.brain, content=content)
        self.assertTrue({"time_timezone_missing", "time_invalid", "time_missing"} <= {w["code"] for w in preview["warnings"]})
        self.apply(content)
        for node in self.brain.nodes.values():
            self.assertTrue(node["meta"]["source_time_unknown"])
            self.assertIsNone(node["meta"]["source_event_at"])
            self.assertFalse(node["event_explicit"])

    def test_millisecond_epoch_and_out_of_order_times_keep_file_order(self):
        content = export([{"role": "user", "content": "先写的用户话", "timestamp": 1767348000000},
                          {"role": "assistant", "content": "时间倒序的助手话", "timestamp": 1767347990}])
        preview = plan_dialogues(self.brain, content=content)
        self.assertIn("out_of_order", {w["code"] for w in preview["warnings"]})
        self.apply(content)
        node = next(iter(self.brain.nodes.values()))
        self.assertEqual(node["event_at"], 1767348000)
        self.assertEqual(node["meta"]["import_messages"][0]["text"], "先写的用户话")

    def test_generic_array_and_session_list(self):
        messages = [{"role": "human", "content": "你好"}, {"role": "model", "content": "你好呀"}]
        self.assertEqual(plan_dialogues(self.brain, content=json.dumps(messages))["turn_count"], 1)
        content = json.dumps({"conversations": [{"id": "a", "messages": messages}, {"id": "b", "messages": messages}]})
        result = self.apply(content)
        self.assertEqual(result["added"], 2)
        self.assertEqual(len({n["session_id"] for n in self.brain.nodes.values()}), 2)

    def test_chatgpt_mapping_uses_selected_branch_and_warns_about_others(self):
        mapping = {"root": {"parent": None, "children": ["u"], "message": None},
                   "u": {"parent": "root", "children": ["a", "old"], "message": {"author": {"role": "user"}, "content": {"parts": ["我喜欢海"]}}},
                   "a": {"parent": "u", "children": [], "message": {"author": {"role": "assistant"}, "content": {"parts": ["我们一起去"]}}},
                   "old": {"parent": "u", "children": [], "message": {"author": {"role": "assistant"}, "content": {"parts": ["未选择的回答"]}}}}
        content = json.dumps({"id": "chatgpt", "current_node": "a", "mapping": mapping}, ensure_ascii=False)
        preview = plan_dialogues(self.brain, content=content)
        self.assertIn("unchosen_branches", {w["code"] for w in preview["warnings"]})
        self.apply(content)
        self.assertNotIn("未选择的回答", json.dumps(self.brain.to_dict(), ensure_ascii=False))
        del mapping["a"]
        with self.assertRaises(ValidationError):
            plan_dialogues(self.brain, content=json.dumps({"mapping": mapping, "current_node": "a"}))

    def test_ambiguous_or_cyclic_chatgpt_branch_is_rejected(self):
        cases = [{"mapping": {"a": {"children": []}, "b": {"children": []}}},
                 {"current_node": "a", "mapping": {"a": {"parent": "a", "message": None}}}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                plan_dialogues(self.brain, content=json.dumps(value))

    def test_explicit_role_text_accepts_multiline_and_preserves_body(self):
        content = "[2026-01-02T18:00:00+08:00] 用户：第一行\n第二行\n助手：好的\n我也记住了"
        result = self.apply(content)
        node = self.brain.get(result["ids"][0])
        self.assertEqual(node["text"], "第一行\n第二行")
        self.assertEqual(node["meta"]["assistant_reply"], "好的\n我也记住了")

    def test_unattributed_text_and_preface_are_rejected_instead_of_guessing(self):
        for value in ["我今天去了海边，她说想跟我去", "导出说明\n用户：你好\n助手：你好"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                plan_dialogues(self.brain, content=value)
        self.assertFalse(self.brain.nodes)

    def test_nontext_block_and_empty_message_preserve_original_structure(self):
        raw = [{"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}]
        content = export([{"role": "system", "content": ""}, {"role": "user", "content": raw}])
        self.apply(content)
        nodes = list(self.brain.nodes.values())
        self.assertEqual(nodes[1]["meta"]["import_messages"][0]["original_content"], raw)
        self.assertEqual(nodes[0]["meta"]["import_messages"][0]["text"], "")

    def test_confirmation_and_matching_preview_required(self):
        for kwargs in [{}, {"confirm": True}, {"confirm": True, "expected_fingerprint": "wrong"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                import_dialogues(self.brain, content=self.content, **kwargs)
        self.assertFalse(self.brain.nodes)

    def test_preview_fingerprint_is_content_scoped_and_stale_import_is_rejected(self):
        preview = plan_dialogues(self.brain, content=self.content)
        with self.assertRaises(ValidationError):
            import_dialogues(self.brain, content=self.content.replace("看海", "看山"), confirm=True,
                             expected_fingerprint=preview["fingerprint"])
        self.assertFalse(self.brain.nodes)

    def test_capacity_preflight_never_evicts_existing_memory(self):
        self.brain.config.max_nodes = 1
        old = self.brain.add("不能删除的旧记录", "原文")
        before = copy.deepcopy(self.brain.to_dict())
        with self.assertRaises(ValidationError):
            self.apply()
        self.assertEqual(self.brain.to_dict(), before)
        self.assertIn(old, self.brain.nodes)

    def test_explicitly_forgotten_import_is_not_resurrected(self):
        result = self.apply()
        nid = result["ids"][0]
        self.brain.remove(nid)
        self.brain.meta["memory_tombstones"] = {"node_ids": [nid]}
        self.assertEqual(self.apply()["added"], 0)
        self.assertFalse(self.brain.nodes)

    def test_invalid_late_message_does_not_partially_import(self):
        data = json.loads(self.content)
        data["messages"].append({"role": "unknown", "content": "不能判断说话人"})
        with self.assertRaises(ValidationError):
            self.apply(json.dumps(data))
        self.assertFalse(self.brain.nodes)

    def test_batch_failure_restores_existing_anchors_edges_and_vectors(self):
        old = self.brain.add("旧锚点", "原来的记忆", impact=.9, session_id="old")
        other = self.brain.add("旧邻居", "原来的邻居", session_id="old")
        self.brain.link(old, other, .5)
        before = copy.deepcopy(self.brain.to_dict())
        vectors = copy.deepcopy(self.brain._vec)
        def fail(**kwargs):
            self.brain.nodes[old]["anchor_info"] = {"corrupted": True}
            self.brain.edges.clear()
            raise RuntimeError("fake anchor-sync failure")
        with patch.object(self.brain, "_sync_anchors", side_effect=fail), self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(self.brain.to_dict(), before)
        self.assertEqual(self.brain._vec, vectors)

    def test_scale_regression_one_anchor_sync_no_per_turn_export_learning_or_dedup(self):
        messages = [{"role": role, "content": f"第 {i} 轮 {role}"} for i in range(600) for role in ("user", "assistant")]
        original = self.brain._sync_anchors
        with patch.object(self.brain, "_sync_anchors", wraps=original) as sync, \
             patch.object(self.brain, "export", side_effect=AssertionError("no whole-graph export per turn")), \
             patch("nkb.companion.dedup.annotate_turn_recording", side_effect=AssertionError("no per-turn full dedup")), \
             patch("nkb.companion.persona.learn_from_dialogue", side_effect=AssertionError("no per-turn persona learning")):
            self.assertEqual(self.apply(export(messages))["added"], 600)
        self.assertEqual(sync.call_count, 1)

    def test_size_message_count_and_type_guards(self):
        bad = [None, "{broken", json.dumps({"messages": []}),
               export([{"role": "user", "content": "x" * 40001}]),
               export([{"role": "user", "content": "x"}] * 2001),
               json.dumps({"messages": [{"role": "user", "content": "x", "timestamp": float("nan")}]})]
        bad.extend(['{"messages":[{"role":"user","role":"assistant","content":"ambiguous"}]}',
                    '{"messages":[{"role":"user","content":"\\ud800"}]}'])
        for value in bad:
            with self.subTest(value=str(value)[:70]), self.assertRaises(ValidationError):
                plan_dialogues(self.brain, content=value)
        with self.assertRaises(ValidationError):
            plan_dialogues(self.brain, content="x" * (4 * 1024 * 1024 + 1))

    def test_demo_is_read_only_and_import_stays_in_supplied_brain(self):
        other = Brain.new()
        other.meta["library_id"] = "two"
        self.apply()
        self.assertFalse(other.nodes)
        other.meta["demo"] = True
        with self.assertRaises(ValidationError):
            plan_dialogues(other, content=self.content)

    def test_ui_uses_fixed_library_and_preview_confirmation(self):
        source = (Path(__file__).resolve().parents[1] / "nkb/viz/web/dialogue-import-ui.js").read_text()
        self.assertIn("dialogue-import/preview", source)
        self.assertIn("expected_fingerprint:draft.result.fingerprint", source)
        self.assertIn("{libraryId:o.id}", source)
        self.assertIn("!current(o)", source)
        self.assertNotIn("innerHTML", source)


if __name__ == "__main__":
    unittest.main()
