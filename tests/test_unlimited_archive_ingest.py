"""No count-based loss in personal archives; request/budget boundaries remain.

All fixtures are synthetic and temporary. Large history enters through the real
batched importer, not a per-node loop that repeatedly copies the whole graph.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nkb import Brain, Config
from nkb.errors import ValidationError
from nkb.ingest.dialogues import import_dialogues, plan_dialogues
from nkb.ingest.notes import import_notes, plan_notes
from nkb.organizer import Organizer, OrganizerError, apply_plan, get_profile, review_candidate, save_profile
from nkb.organizer.state import build_input, validate_plan

DAY = 1793318400.0  # One fixed synthetic day, no user's real timeline.


def chat_batch(batch, turns=1000):
    messages = []
    for index in range(turns):
        messages.extend([
            {"role": "user", "content": f"合成测试第{batch}-{index}轮原话。", "timestamp": DAY + index * 2},
            {"role": "assistant", "content": f"合成测试第{batch}-{index}轮回复。", "timestamp": DAY + index * 2 + 1},
        ])
    return json.dumps({"id": f"synthetic-day-session-{batch}", "messages": messages}, ensure_ascii=False)


def commit_batch(brain, content):
    preview = plan_dialogues(brain, content=content)
    return import_dialogues(brain, content=content, confirm=True, expected_fingerprint=preview["fingerprint"])


class UnlimitedArchiveIngestTests(unittest.TestCase):
    def brain(self, path=None):
        brain = Brain.new(path, config=Config(max_nodes=None))
        brain.meta.update(library_id="archive-test", long_term_archive=True)
        return brain

    def test_one_day_eleven_thousand_turns_survive_batched_import_save_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix="love-house-many-turns-") as folder:
            path = Path(folder) / "synthetic.brain.json"
            brain = self.brain(path)
            ids = []
            first_content = chat_batch(0)
            with patch("nkb.core.brain._now", return_value=DAY + 3600), \
                 patch.object(brain, "_sync_anchors", wraps=brain._sync_anchors) as sync, \
                 patch("nkb.companion.persona.learn_from_dialogue", side_effect=AssertionError("Import must not infer persona")):
                for batch in range(11):
                    result = commit_batch(brain, first_content if batch == 0 else chat_batch(batch))
                    self.assertEqual(result["added"], 1000)
                    ids.extend(result["ids"])
                self.assertEqual(sync.call_count, 11)  # Once per batch, not once per message.
            self.assertEqual(len(brain.nodes), 11000)
            self.assertEqual(set(brain.nodes), set(ids))
            self.assertEqual(brain.meta.get("capacity_evictions", 0), 0)
            self.assertIn("合成测试第0-0轮原话。", brain.nodes[ids[0]]["text"])
            self.assertEqual(brain.nodes[ids[0]]["meta"]["assistant_reply"], "合成测试第0-0轮回复。")
            self.assertEqual(brain.nodes[ids[0]]["meta"]["import_messages"][0]["source_event_at"], DAY)
            brain.save()
            restored = Brain.open(path)
            self.assertIsNone(restored.config.max_nodes)
            self.assertEqual(set(restored.nodes), set(ids))
            self.assertEqual(commit_batch(restored, first_content)["added"], 0)
            self.assertEqual(len(restored.nodes), 11000)

    def test_unlimited_notes_preview_commit_and_repeat(self):
        brain = self.brain()
        files = [{"name": "合成笔记.md", "text": "# 合成标题\n完整正文。\n# 第二个标题\n第二份完整正文。"}]
        before = deepcopy(brain.to_dict())
        self.assertEqual(plan_notes(brain, files)["added"], 2)
        self.assertEqual(before, brain.to_dict())
        result = import_notes(brain, files)
        self.assertEqual(result["added"], 2)
        self.assertEqual(import_notes(brain, files)["skipped"], 2)
        self.assertEqual(len(brain.nodes), 2)

    def test_explicit_numeric_library_capacity_still_preflights_without_evicting(self):
        brain = Brain.new(config=Config(max_nodes=1))
        brain.add("原有记忆", "不可因批量导入移除。", kind="episode")
        before = deepcopy(brain.to_dict())
        with self.assertRaises(ValidationError):
            commit_batch(brain, chat_batch(2, turns=1))
        with self.assertRaises(ValidationError):
            import_notes(brain, [{"name": "新笔记.md", "text": "新原文。"}], mode="whole")
        self.assertEqual(before, brain.to_dict())

    def test_per_request_message_and_note_limits_remain_in_unlimited_library(self):
        brain = self.brain()
        with self.assertRaisesRegex(ValidationError, "2000"):
            plan_dialogues(brain, content=chat_batch(1, turns=1001))
        with self.assertRaisesRegex(ValidationError, "500"):
            plan_notes(brain, [{"name": "大量笔记.md", "text": "\n".join(f"# 合成{i}\n正文{i}" for i in range(501))}])
        self.assertFalse(brain.nodes)

    def test_unlimited_dialogue_staging_failure_does_not_leave_partial_new_nodes(self):
        def encoder(text):
            if "编码失败" in text:
                raise ValueError("synthetic encoder failure")
            return {text}
        brain = Brain.new(config=Config(max_nodes=None), encode=encoder)
        brain.add("已有记录", "原文完整", kind="episode")
        before, vectors = deepcopy(brain.to_dict()), deepcopy(brain._vec)
        content = json.dumps([{"role": "user", "content": "第一条正常。"},
                              {"role": "assistant", "content": "回复。"},
                              {"role": "user", "content": "编码失败。"},
                              {"role": "assistant", "content": "回复。"}], ensure_ascii=False)
        preview = plan_dialogues(brain, content=content)
        with self.assertRaises(ValueError):
            import_dialogues(brain, content=content, confirm=True, expected_fingerprint=preview["fingerprint"])
        self.assertEqual(before, brain.to_dict())
        self.assertEqual(vectors, brain._vec)

    def organizer_plan(self, brain, *, action="remember", job="synthetic-job"):
        save_profile(brain, enabled=True, provider_id="FAKE-NO-NETWORK", base_url="https://offline.invalid/v1", model="FAKE")
        raw = brain.add("测试原话", "我喜欢温水。", kind="episode", meta={"source": "conversation_turn", "assistant_reply": "合成回复。"})
        profile = get_profile(brain)
        payload, guards = build_input(brain, "archive-test", [{"raw_id": raw, "progress": "{}"}], profile)
        output = {"version": 1, "operations": [{"action": action, "layer": "preference", "key": "drink.temperature",
                  "text": "用户喜欢温水", "evidence": [{"id": raw, "role": "user", "quote": "我喜欢温水。"}],
                  "domain": "real", "certainty": "clear", "aliases": [],
                  "atom": {"subject": "user", "predicate": "likes", "value": "温水"}}]}
        return validate_plan(output, payload, guards, job, profile), raw

    def test_unlimited_organizer_can_create_sourced_facts(self):
        brain = self.brain()
        plan, raw = self.organizer_plan(brain)
        result = apply_plan(brain, plan, "archive-test")
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(brain.nodes[raw]["text"], "我喜欢温水。")
        self.assertIn(raw, brain.nodes)

    def test_unlimited_organizer_user_review_can_accept_candidate(self):
        brain = self.brain()
        plan, raw = self.organizer_plan(brain, action="candidate")
        result = apply_plan(brain, plan, "archive-test")
        self.assertEqual(len(result["candidates"]), 1)
        approved = review_candidate(brain, result["candidates"][0], "accept")
        self.assertEqual(approved["status"], "accepted")
        self.assertIn(raw, brain.nodes)
        self.assertTrue(brain.nodes[approved["node_id"]]["meta"]["confirmed"])

    def test_explicit_organizer_numeric_capacity_keeps_original_evidence(self):
        brain = Brain.new(config=Config(max_nodes=1))
        plan, raw = self.organizer_plan(brain)
        before = deepcopy(brain.to_dict())
        with self.assertRaises(OrganizerError):
            apply_plan(brain, plan, "archive-test")
        self.assertEqual(before, brain.to_dict())
        self.assertIn(raw, brain.nodes)

    def test_organizer_queue_can_accumulate_more_than_ten_thousand_without_model_calls(self):
        with tempfile.TemporaryDirectory(prefix="love-house-many-organizer-items-") as folder:
            def blocked(*args, **kwargs):
                raise AssertionError("Enqueue must not fetch a model key or call a model")
            organizer = Organizer(folder, snapshot=blocked, apply=blocked, credential=blocked, transport=blocked)
            self.addCleanup(organizer.stop)
            raw_ids = [f"synthetic-raw-{index}" for index in range(11001)]
            queued = sum(organizer.enqueue("archive-test", raw_ids[i:i + 1000])["queued"] for i in range(0, len(raw_ids), 1000))
            self.assertEqual(queued, 11001)
            self.assertEqual(organizer.enqueue("archive-test", raw_ids[:1000])["queued"], 0)
            with organizer.db() as db:
                count = db.execute("SELECT COUNT(*) FROM items WHERE library_id=? AND status='pending'", ("archive-test",)).fetchone()[0]
            self.assertEqual(count, 11001)


if __name__ == "__main__":
    unittest.main()
