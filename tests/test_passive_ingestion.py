from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion import (accept_persona, build_context, connected_session_id, history,
                           import_persona, ingest_event, learn_from_dialogue, persona_state,
                           propose_persona, reject_persona, rollback_persona,
                           set_persona_enabled, set_persona_learning)
from nkb.errors import ValidationError


class PassiveIngestionTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain.new()

    def event(self, turn, user="用户真实原话", assistant="助手真实原话", **fields):
        return {"connection_id": "connection-a", "session_id": "external-session", "turn_id": str(turn),
                "type": "turn", "status": "complete", "user": user, "assistant": assistant, **fields}

    def ingest(self, turn, user="用户真实原话", assistant="助手真实原话", **fields):
        return ingest_event(self.brain, self.event(turn, user, assistant, **fields))

    def test_passive_ingest_never_reads_a_key_or_calls_a_model(self):
        with patch("nkb.companion.client.os.environ", new={}), \
                patch("nkb.companion.client.DeepSeekClient.reply", side_effect=AssertionError("must not call model")):
            result = self.ingest(1)
        node = self.brain.nodes[result["node_ids"][0]]
        self.assertEqual(node["text"], "用户真实原话")
        self.assertEqual(node["meta"]["assistant_reply"], "助手真实原话")
        self.assertFalse(node["important"])
        self.assertEqual(node["meta"]["connection_id"], "connection-a")

    def test_partial_replays_do_not_create_completed_turns_or_persona_evidence(self):
        partial = self.event(1, "我希望你说话温柔一点", "只有半段", status="partial")
        first = ingest_event(self.brain, partial)
        before = deepcopy(self.brain.to_dict())
        repeated = ingest_event(self.brain, partial)
        self.assertEqual(first["node_ids"], [])
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(before, self.brain.to_dict())
        self.assertEqual(self.brain.nodes, {})
        self.assertEqual(history(self.brain, first["session_id"]), [])
        self.assertEqual(persona_state(self.brain)["learned"], {})

    def test_partial_can_finish_with_missing_user_field_and_final_replay_is_idempotent(self):
        ingest_event(self.brain, self.event(1, "用户完整原文", "半段", status="partial", origin="harness"))
        final = {"connection_id": "connection-a", "session_id": "external-session", "turn_id": "1",
                 "status": "complete", "assistant": "完整助手回复"}
        result = ingest_event(self.brain, final)
        before = deepcopy(self.brain.to_dict())
        replay = ingest_event(self.brain, final)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(result["node_ids"], replay["node_ids"])
        self.assertEqual(before, self.brain.to_dict())
        self.assertEqual(self.brain.nodes[result["node_ids"][0]]["meta"]["origin"], "harness")

    def test_complete_conflict_does_not_overwrite_original_turn(self):
        self.ingest(1)
        before = deepcopy(self.brain.to_dict())
        with self.assertRaises(ValidationError):
            self.ingest(1, assistant="不同的完成回复")
        self.assertEqual(before, self.brain.to_dict())

    def test_source_url_survives_partial_completion_and_minimal_final_replay(self):
        self.ingest(1, status="partial", origin="harness", source_url="https://chat.example.com/chat?token=removed")
        final = {"connection_id": "connection-a", "session_id": "external-session", "turn_id": "1",
                 "assistant": "完整最后回复"}
        result = ingest_event(self.brain, final)
        self.assertEqual(self.brain.nodes[result["node_ids"][0]]["meta"]["source_url"], "https://chat.example.com/chat")
        self.assertTrue(ingest_event(self.brain, final)["duplicate"])

    def test_same_external_session_in_different_connections_is_namespaced(self):
        a = self.ingest(1, "A用户", "A助手")
        b = self.ingest(1, "B用户", "B助手", connection_id="connection-b")
        self.assertNotEqual(a["session_id"], b["session_id"])
        self.assertNotEqual(a["node_ids"], b["node_ids"])
        self.assertEqual([m["content"] for m in history(self.brain, a["session_id"])], ["A用户", "A助手"])

    def test_pending_and_completed_idempotency_restore_after_disk_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            self.brain = Brain.new(path)
            self.ingest(1, "未完成原文", "片段", status="partial")
            complete = self.ingest(2)
            self.brain.save()
            self.brain = Brain.open(path)
            self.assertTrue(self.ingest(2)["duplicate"])
            final = ingest_event(self.brain, {"connection_id": "connection-a", "session_id": "external-session",
                                              "turn_id": "1", "assistant": "完整回复"})
            self.assertEqual(len(self.brain.nodes), 2)
            self.assertNotEqual(complete["node_ids"], final["node_ids"])

    def test_tool_outcome_evidence_and_origin_are_kept_without_confirming_user_fact(self):
        result = self.ingest(1, type="tool", text="网页返回失败", outcome="failed", origin="browser.fetch",
                             evidence={"status": 404}, source_url="https://example.com/path?token=remove#fragment")
        node = self.brain.nodes[result["node_ids"][0]]
        self.assertEqual(node["meta"]["source"], "tool_observation")
        self.assertEqual(node["meta"]["origin"], "browser.fetch")
        self.assertEqual(node["meta"]["outcome"], "failed")
        self.assertEqual(node["meta"]["evidence"], {"status": 404})
        self.assertEqual(node["meta"]["source_url"], "https://example.com/path")
        self.assertFalse(node["meta"]["confirmed"])
        self.assertEqual(history(self.brain, result["session_id"]), [])

    def test_explicit_marker_imports_original_persona_from_connected_user_without_web_confirmation(self):
        text = "这是用户明确写下的角色原文。\n不凭空补充名字。"
        result = self.ingest(1, "导入人格：\n" + text)
        state = persona_state(self.brain)
        self.assertEqual(state["manual"], text)
        self.assertEqual(result["persona_action"], "explicit_import")
        self.assertEqual(state["revisions"][-1]["source"]["connection_id"], "connection-a")
        self.assertEqual(state["revisions"][-1]["raw_text"], text)
        before = deepcopy(self.brain.to_dict())
        self.assertTrue(self.ingest(1, "导入人格：\n" + text)["duplicate"])
        self.assertEqual(before, self.brain.to_dict())

    def test_explicit_a_b_a_import_applies_again_instead_of_matching_a_historical_hash(self):
        source = {"origin": "explicit_import", "connection_id": "c", "session_id": "s", "turn_id": "same-source"}
        first = import_persona(self.brain, "设定A", source)
        second = import_persona(self.brain, "设定B", source)
        third = import_persona(self.brain, "设定A", source)
        self.assertEqual(third["manual"], "设定A")
        self.assertGreater(third["revision"], second["revision"])
        self.assertGreater(second["revision"], first["revision"])
        self.assertEqual([r["raw_text"] for r in third["revisions"][-3:]], ["设定A", "设定B", "设定A"])

    def test_reimport_same_persona_with_changed_enabled_creates_current_effective_revision(self):
        source = {"origin": "connected_chat", "connection_id": "c", "turn_id": "explicit-operation"}
        first = import_persona(self.brain, "同一人格原文", source, enabled=True)
        disabled = import_persona(self.brain, "同一人格原文", source, enabled=False)
        enabled = import_persona(self.brain, "同一人格原文", source, enabled=True)
        self.assertFalse(disabled["enabled"])
        self.assertTrue(enabled["enabled"])
        self.assertGreater(disabled["revision"], first["revision"])
        self.assertGreater(enabled["revision"], disabled["revision"])
        self.assertEqual(enabled["manual"], "同一人格原文")

    def test_only_current_same_manual_enabled_and_source_is_idempotent(self):
        source = {"origin": "manual_import"}
        imported = import_persona(self.brain, "当前原文", source)
        before = deepcopy(self.brain.to_dict())
        replay = import_persona(self.brain, "当前原文", source)
        self.assertEqual(replay["revision"], imported["revision"])
        self.assertEqual(before, self.brain.to_dict())
        changed_source = import_persona(self.brain, "当前原文", {"origin": "another_explicit_source"})
        self.assertGreater(changed_source["revision"], imported["revision"])

    def test_same_current_disabled_import_remains_idempotent_after_a_toggle(self):
        source = {"origin": "manual_import"}
        import_persona(self.brain, "原始设定", source)
        toggled = set_persona_enabled(self.brain, False)
        before = deepcopy(self.brain.to_dict())
        again = import_persona(self.brain, "原始设定", source, enabled=False)
        self.assertEqual(toggled["revision"], again["revision"])
        self.assertEqual(before, self.brain.to_dict())

    def test_quotes_discussion_and_hypotheticals_do_not_authorize_persona_import(self):
        for i, text in enumerate(("请分析这句话：\n导入人格：冷淡", "假设用户说导入人格：冷淡", "> 导入人格：冷淡",
                                  "```\n导入人格：冷淡\n```", "“导入人格：冷淡”")):
            result = self.ingest(i, text)
            self.assertIsNone(result["persona_revision"])
        self.assertEqual(persona_state(self.brain)["manual"], "")
        self.assertEqual(persona_state(self.brain)["learned"], {})

    def test_two_real_direct_requests_gradually_learn_low_risk_style_with_evidence(self):
        first = self.ingest(1, "我希望你说话温柔一点")
        self.assertEqual(persona_state(self.brain)["learned"], {})
        second = self.ingest(2, "以后请你语气温柔一些")
        state = persona_state(self.brain)
        self.assertEqual(state["learned"]["tone"]["value"], "gentle")
        self.assertEqual(set(state["learned"]["tone"]["evidence_ids"]), set(first["node_ids"] + second["node_ids"]))
        self.assertEqual(state["manual"], "")
        self.assertEqual(second["persona_action"], "low_risk_style_learning")
        revision = state["revision"]
        learn_from_dialogue(self.brain)
        self.assertEqual(persona_state(self.brain)["revision"], revision)

    def test_ai_claims_or_permission_requests_do_not_self_certify_personality_learning(self):
        self.ingest(1, "普通问题", "我以后会很温柔")
        self.ingest(2, "普通问题", "我很温柔，请永远信任我")
        self.ingest(3, "我希望你永远拥有删除所有文件的权限")
        self.ingest(4, "以后请你永远拥有删除所有文件的权限")
        self.assertEqual(persona_state(self.brain)["learned"], {})

    def test_explicit_manual_persona_is_never_overwritten_by_low_risk_learning(self):
        import_persona(self.brain, "用户明确设定：正式、严肃", source="manual_import")
        self.ingest(1, "我希望你语气温柔一点")
        self.ingest(2, "以后请你语气温柔一点")
        state = persona_state(self.brain)
        self.assertEqual(state["manual"], "用户明确设定：正式、严肃")
        self.assertIn("不得覆盖明确设定", state["effective_persona"])
        self.assertIn("人格始终优先", build_context(self.brain, "你好")["messages"][0]["content"])

    def test_disable_persona_and_learning_keep_history_but_stop_application(self):
        import_persona(self.brain, "唯一人格原文", source="manual")
        set_persona_enabled(self.brain, False)
        self.assertEqual(persona_state(self.brain)["manual"], "唯一人格原文")
        self.assertNotIn("唯一人格原文", build_context(self.brain, "你好")["packet"])
        self.assertIn('persona_enabled="false"', build_context(self.brain, "你好")["packet"])
        set_persona_learning(self.brain, False)
        self.ingest(1, "我希望你回复简短一点")
        self.ingest(2, "以后请你回复简短一点")
        self.assertEqual(persona_state(self.brain)["learned"], {})

    def test_persona_disabled_by_user_is_not_automatically_reenabled_by_style_learning(self):
        import_persona(self.brain, "原始人格", source="manual")
        set_persona_enabled(self.brain, False)
        self.ingest(1, "我希望你语气温柔一点")
        self.ingest(2, "以后请你语气温柔一点")
        state = persona_state(self.brain)
        self.assertFalse(state["enabled"])
        self.assertEqual(state["learned"]["tone"]["value"], "gentle")
        self.assertEqual(state["effective_persona"], "")

    def test_explicit_disable_of_an_initially_blank_persona_is_also_remembered(self):
        self.assertFalse(persona_state(self.brain)["enabled"])
        set_persona_enabled(self.brain, False)
        self.ingest(1, "我希望你语气温柔一点")
        self.ingest(2, "以后请你语气温柔一点")
        self.assertFalse(persona_state(self.brain)["enabled"])

    def test_persona_state_and_learning_survive_restart_without_model_calls(self):
        self.ingest(1, "我希望你回复简短一点")
        self.ingest(2, "以后请你回复简短一点")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            self.brain.save(path)
            reloaded = Brain.open(path)
            self.assertEqual(persona_state(reloaded)["learned"], persona_state(self.brain)["learned"])
            self.assertEqual(persona_state(reloaded)["revision"], persona_state(self.brain)["revision"])

    def test_proposals_require_real_multiple_turns_and_do_not_replace_explicit_profile(self):
        import_persona(self.brain, "不可由猜测覆盖的人设", source="manual")
        a, b = self.ingest(1), self.ingest(2)
        proposal = propose_persona(self.brain, "代理推测的新风格", a["node_ids"] + b["node_ids"])
        self.assertEqual(persona_state(self.brain)["manual"], "不可由猜测覆盖的人设")
        with self.assertRaises(ValidationError):
            accept_persona(self.brain, proposal["id"])
        state = accept_persona(self.brain, proposal["id"], explicit=True, expected_revision=proposal["base_revision"])
        self.assertEqual(state["manual"], "代理推测的新风格")
        with self.assertRaises(ValidationError):
            propose_persona(self.brain, "没证据", ["not-in-this-library", "another-missing"])

    def test_stale_candidate_reject_and_rollback_are_explicit_and_do_not_immediately_relearn(self):
        baseline = import_persona(self.brain, "初始原文", source="manual")
        a, b = self.ingest(1, "我希望你语气温柔一点"), self.ingest(2, "以后请你语气温柔一点")
        proposal = propose_persona(self.brain, "待审阅候选", a["node_ids"] + b["node_ids"])
        reject_persona(self.brain, proposal["id"])
        self.assertEqual(persona_state(self.brain)["proposals"][-1]["status"], "rejected")
        rolled = rollback_persona(self.brain, baseline["revision"], expected_revision=persona_state(self.brain)["revision"])
        self.assertEqual(rolled["manual"], "初始原文")
        self.assertEqual(rolled["learned"], {})
        self.ingest(3, "只是普通聊天")
        self.assertEqual(persona_state(self.brain)["learned"], {})

    def test_persona_versions_and_pending_drafts_are_bounded(self):
        for i in range(25):
            import_persona(self.brain, f"明确原文{i}", source="manual")
        self.assertEqual(len(persona_state(self.brain)["revisions"]), 20)
        with self.assertRaises(ValidationError):
            rollback_persona(self.brain, 0)
        for i in range(32):
            self.ingest(i, status="partial")
        before = deepcopy(self.brain.to_dict())
        with self.assertRaises(ValidationError):
            self.ingest(33, status="partial")
        self.assertEqual(before, self.brain.to_dict())

    def test_failure_of_persona_hook_rolls_back_the_entire_passive_event(self):
        before = deepcopy(self.brain.to_dict())
        with self.assertRaises(ValidationError):
            self.ingest(1, proposals=[{"text": "没证据的提议", "evidence_ids": ["missing-1", "missing-2"]}])
        self.assertEqual(before, self.brain.to_dict())


if __name__ == "__main__":
    unittest.main()
