"""回归测试：统一投影、200 天唤醒、情绪锚点和有限真实时期摘录。"""
from __future__ import annotations

from copy import deepcopy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nkb import Brain, Config
from nkb.core.lifecycle import reflect
from nkb.errors import ConfigError, ValidationError

DAY = 86400.0
T0 = 1_800_000_000.0
CLOCK = "nkb.core.brain._now"


def node(snapshot, nid):
    return next(n for n in snapshot["nodes"] if n["id"] == nid)


class MemoryHelpers:
    def make(self, **config):
        with patch(CLOCK, return_value=T0):
            return Brain.new(config=Config(**config))

    def add(self, brain, label="一次经历", **kwargs):
        with patch(CLOCK, return_value=T0):
            return brain.add(label, kind=kwargs.pop("kind", "episode"), **kwargs)


class LifecycleTests(MemoryHelpers, unittest.TestCase):

    def test_decay_is_idempotent_and_piecewise_equivalent_for_nodes_and_edges(self):
        b = self.make()
        a = self.add(b, salience=0.8)
        c = self.add(b, "另一次经历", salience=0.7)
        with patch(CLOCK, return_value=T0):
            b.link(a, c, 0.8)
        once = Brain(deepcopy(b.to_dict()))
        b.forget(now=T0 + 30 * DAY)
        first = deepcopy(b.to_dict())
        b.forget(now=T0 + 30 * DAY)
        self.assertEqual(first, b.to_dict())
        b.forget(now=T0 + 60 * DAY)
        once.forget(now=T0 + 60 * DAY)
        self.assertAlmostEqual(b.nodes[a]["salience"], 0.4)
        self.assertAlmostEqual(b.nodes[a]["salience"], once.nodes[a]["salience"])
        key = b._key(a, c)
        self.assertAlmostEqual(b.edges[key]["w"], once.edges[key]["w"])

    def test_preview_and_export_are_deeply_read_only_and_share_formula(self):
        b = self.make()
        nid = self.add(b, salience=0.8, meta={"nested": {"x": 1}})
        before = deepcopy(b.to_dict())
        snapshot = b.preview(days=60, now=T0)
        self.assertEqual(before, b.to_dict())
        self.assertEqual(node(snapshot, nid)["state"], "fading")
        self.assertEqual(node(snapshot, nid)["effective_salience"], 0.4)
        self.assertEqual(snapshot["as_of"], T0 + 60 * DAY)
        self.assertEqual(node(snapshot, nid), node(b.export(as_of=T0 + 60 * DAY), nid))
        snapshot["nodes"][0]["meta"]["nested"]["x"] = 9
        self.assertEqual(b.nodes[nid]["meta"]["nested"]["x"], 1)
        b.forget(now=T0 + 60 * DAY)
        self.assertAlmostEqual(b.nodes[nid]["salience"], 0.4)

    def test_very_weak_memory_survives_until_recovery_boundary_and_can_wake(self):
        b = self.make(half_life={"episode": 1.0})
        nid = self.add(b, salience=0.2)
        b.forget(now=T0 + 199 * DAY)
        self.assertIn(nid, b.nodes)
        self.assertEqual(node(b.export(as_of=T0 + 199 * DAY), nid)["state"], "dormant")
        result = b.reinforce([nid], now=T0 + 200 * DAY)
        self.assertEqual(result["reinforced_ids"], [nid])
        self.assertGreater(b.nodes[nid]["salience"], 0.33)
        self.assertEqual(b.nodes[nid]["reinforced"], T0 + 200 * DAY)

    def test_outside_recovery_boundary_cannot_be_reinforced_or_recalled(self):
        b = self.make()
        nid = self.add(b, "唯一经历")
        before = deepcopy(b.nodes[nid])
        result = b.reinforce([nid], now=T0 + 200 * DAY + 1)
        self.assertEqual(result["nodes"], 0)
        self.assertEqual(before, b.nodes[nid])
        self.assertEqual(b.recall("唯一经历", as_of=T0 + 201 * DAY)["hits"], [])
        self.assertEqual(node(b.export(as_of=T0 + 201 * DAY), nid)["state"], "forgotten")
        b.forget(now=T0 + 201 * DAY)
        self.assertNotIn(nid, b.nodes)

    def test_reinforce_uses_effective_baseline_without_waiting_for_tick(self):
        b = self.make()
        nid = self.add(b, salience=0.8)
        b.reinforce([nid], bump=0.5, now=T0 + 60 * DAY)
        self.assertAlmostEqual(b.nodes[nid]["salience"], 0.7)

    def test_protected_core_and_anchor_survive_but_expired_fact_cannot_revive(self):
        b = self.make()
        important = self.add(b, "重要原则", salience=0.96)
        anchor = self.add(b, "那天的情绪冲击", impact=-0.75)
        with patch(CLOCK, return_value=T0):
            old = b.add("过时事实", kind="fact", impact=0.9)
            new = b.add("新的事实", kind="fact")
            b.supersede(old, new)
        snapshot = b.export(as_of=T0 + 1000 * DAY)
        self.assertEqual(node(snapshot, important)["protection_reason"], "important")
        self.assertEqual(node(snapshot, anchor)["protection_reason"], "emotional_anchor")
        self.assertFalse(node(snapshot, old)["recoverable"])
        self.assertEqual(b.reinforce([old], now=T0 + DAY)["nodes"], 0)
        b.forget(now=T0 + 1000 * DAY)
        self.assertIn(important, b.nodes)
        self.assertIn(anchor, b.nodes)
        self.assertIn(old, b.nodes)  # 时效历史仍可审计

    def test_expired_node_cannot_bridge_two_live_memories(self):
        b = self.make()
        a = self.add(b, "alpha needle", kind="concept")
        bridge = self.add(b, "旧桥梁", kind="fact")
        target = self.add(b, "完全不同的终点", kind="concept")
        with patch(CLOCK, return_value=T0):
            b.link(a, bridge, 0.9)
            b.link(bridge, target, 0.9)
        b.nodes[bridge]["valid_to"] = T0 + 1
        result = b.recall("alpha needle", as_of=T0 + DAY, steps=3)
        self.assertNotIn(target, [hit["id"] for hit in result["hits"]])
        self.assertNotIn(bridge, [step["to"] for step in result["trail"]])

    def test_kind_filter_applies_to_entire_expansion_graph(self):
        b = self.make()
        seed = self.add(b, "alpha needle", kind="concept")
        bridge = self.add(b, "某次事件", kind="episode")
        target = self.add(b, "另一个理论", kind="concept")
        with patch(CLOCK, return_value=T0):
            b.link(seed, bridge, 0.9)
            b.link(bridge, target, 0.9)
        result = b.recall("alpha needle", kinds=["concept"], as_of=T0 + 1, steps=3)
        self.assertEqual([hit["id"] for hit in result["hits"]], [seed])

    def test_invalidated_edge_not_resurrected_by_hebbian_learning(self):
        b = self.make()
        a = self.add(b, "一个概念", kind="concept")
        c = self.add(b, "另一个概念", kind="concept")
        with patch(CLOCK, return_value=T0):
            b.link(a, c)
            b.invalidate(a, c)
        before = deepcopy(b.edges[b._key(a, c)])
        self.assertEqual(b.reinforce([a, c], now=T0 + DAY)["pairs"], 0)
        self.assertEqual(before, b.edges[b._key(a, c)])

    def test_future_effective_fact_is_not_recalled_early_and_cycles_are_rejected(self):
        b = self.make()
        old = self.add(b, "alpha旧事实", kind="fact")
        new = self.add(b, "alpha新事实", kind="fact")
        with patch(CLOCK, return_value=T0):
            b.supersede(old, new, at=T0 + DAY)
        self.assertEqual([h["id"] for h in b.recall("alpha", as_of=T0 + 1)["hits"]], [old])
        self.assertEqual([h["id"] for h in b.recall("alpha", as_of=T0 + 2 * DAY)["hits"]], [new])
        before = deepcopy(b.to_dict())
        with self.assertRaises(ValidationError):
            b.supersede(new, old)
        self.assertEqual(before, b.to_dict())

    def test_reflection_does_not_repackage_forgotten_or_expired_fragments(self):
        b = self.make()
        for i in range(3):
            self.add(b, f"旧经历{i}", tags=["相同标签"])
        result = reflect(b, min_cluster=3, now=T0 + 201 * DAY)
        self.assertEqual(result["created"], [])


class AnchorTests(MemoryHelpers, unittest.TestCase):
    def event(self, b, label, offset, **kwargs):
        return self.add(b, label, event_at=T0 - 10000 + offset,
                        session_id=kwargs.pop("session_id", "真实会话"), **kwargs)

    def test_impact_threshold_is_exact_not_rounded(self):
        b = self.make()
        below = self.add(b, impact=0.74999)
        equal = self.add(b, impact=-0.75)
        snapshot = b.export(as_of=T0)
        self.assertFalse(node(snapshot, below)["is_anchor"])
        self.assertTrue(node(snapshot, equal)["is_anchor"])

    def test_context_uses_event_time_not_ingestion_order_and_is_bounded(self):
        b = self.make(context_before=2, context_after=2)
        anchor = self.event(b, "情绪锚点", 1000, impact=0.8)
        wrong_session = self.event(b, "别的会话", 990, session_id="另一会话")
        for offset in (1400, 700, 1300, 900, 800, 1100, 1200):
            self.event(b, str(offset), offset)
        info = node(b.export(as_of=T0), anchor)["anchor_info"]
        self.assertEqual([b.nodes[nid]["label"] for nid in info["before_ids"]], ["800", "900"])
        self.assertEqual([b.nodes[nid]["label"] for nid in info["after_ids"]], ["1100", "1200"])
        self.assertNotIn(wrong_session, info["before_ids"])
        self.assertEqual(len(info["context_snippets"]), 4)

    def test_no_session_or_far_event_cannot_be_guessed_into_context(self):
        b = self.make(context_window_hours=1)
        no_session = self.add(b, "没有会话", impact=0.8)
        anchor = self.event(b, "会话锚点", 9000, impact=0.8)
        self.event(b, "太久以前", 0)
        snapshot = b.export(as_of=T0)
        self.assertEqual(node(snapshot, no_session)["anchor_info"]["context_snippets"], [])
        self.assertIsNotNone(node(snapshot, no_session)["anchor_info"]["note"])
        self.assertEqual(node(snapshot, anchor)["anchor_info"]["before_ids"], [])

    def test_bridge_uses_only_real_events_and_total_per_anchor_is_bounded(self):
        b = self.make(bridge_max_events=3, context_before=0, context_after=0)
        first = self.event(b, "第一次冲击", 0, impact=0.8)
        actual = [self.event(b, f"真实小事{i}", i * 100) for i in range(1, 10)]
        middle = self.event(b, "第二次冲击", 1100, impact=0.8)
        actual.extend(self.event(b, f"后来小事{i}", 1100 + i * 100) for i in range(1, 10))
        last = self.event(b, "第三次冲击", 2200, impact=0.8)
        snapshot = b.export(as_of=T0)
        for nid in (first, middle, last):
            info = node(snapshot, nid)["anchor_info"]
            self.assertLessEqual(len(info["bridge_ids"]), 3)
            self.assertTrue(set(info["bridge_ids"]) <= set(actual))
            self.assertLessEqual(len(info["context_snippets"]), 3)
        self.assertEqual(len(b.nodes), 21)  # 锚点机制没有编造或补写节点

    def test_finite_excerpts_survive_original_event_forgetting_and_future_writes(self):
        b = self.make(context_before=1, context_after=1, bridge_max_events=0)
        before = self.event(b, "锚点前的真实小事", 100, text="原文" * 300)
        anchor = self.event(b, "重要时刻", 200, impact=0.9)
        after = self.event(b, "锚点后的真实小事", 300, text="真实发生")
        with patch(CLOCK, return_value=T0 + 201 * DAY):
            b.forget(now=T0 + 201 * DAY)
            self.assertNotIn(before, b.nodes)
            self.assertNotIn(after, b.nodes)
            b.add("很久以后的一件事", kind="episode", session_id="真实会话")
        info = node(b.export(as_of=T0 + 201 * DAY), anchor)["anchor_info"]
        self.assertEqual(info["before_ids"], [before])
        self.assertEqual(info["after_ids"], [after])
        self.assertEqual(len(info["context_snippets"]), 2)
        self.assertTrue(all(len(s["excerpt"]) <= 240 for s in info["context_snippets"]))
        self.assertTrue(all(s["source_present"] is False and s["is_excerpt"] for s in info["context_snippets"]))
        hit = b.recall("重要时刻", as_of=T0 + 201 * DAY)["hits"][0]
        self.assertEqual(hit["id"], anchor)
        self.assertEqual(len(hit["context_snippets"]), 2)

    def test_export_edges_include_temporal_and_lifecycle_status(self):
        b = self.make()
        before = self.event(b, "真实前事", 100)
        anchor = self.event(b, "情绪锚点", 200, impact=0.8)
        snapshot = b.export(as_of=T0)
        edge = next(e for e in snapshot["edges"] if {e["source"], e["target"]} == {before, anchor})
        self.assertTrue(edge["active"])
        self.assertIn("valid_from", edge)
        self.assertIn("valid_to", edge)
        self.assertEqual(edge["anchor_relations"][0]["kind"], "context_before")

    def test_explicit_delete_also_removes_retained_source_excerpt(self):
        b = self.make(context_before=1)
        before = self.event(b, "应当删除的原记录", 100)
        anchor = self.event(b, "保留的锚点", 200, impact=0.8)
        b.remove(before)
        info = node(b.export(as_of=T0), anchor)["anchor_info"]
        self.assertNotIn(before, info["before_ids"])
        self.assertFalse(any(s["id"] == before for s in info["context_snippets"]))

    def test_changing_existing_source_session_removes_old_context_and_automatic_edge(self):
        b = self.make()
        anchor = self.event(b, "仍在原会话的锚点", 100, impact=0.8)
        source = self.event(b, "需要移动会话的来源", 200, text="正文")
        self.assertIn(source, b.nodes[anchor]["anchor_info"]["after_ids"])
        with patch(CLOCK, return_value=T0 + 100):
            b.update(source, session_id="另一会话")
        info = node(b.export(as_of=T0 + 101), anchor)["anchor_info"]
        self.assertEqual(info["after_ids"], [])
        self.assertFalse(any(s["id"] == source for s in info["context_snippets"]))
        self.assertNotIn(b._key(source, anchor), b.edges)

    def test_existing_bridge_source_revalidates_session_and_actual_event_time(self):
        b = self.make(context_before=0, context_after=0)
        first = self.event(b, "第一个真实锚点", 100, impact=0.8)
        source = self.event(b, "桥接的小事", 200)
        second = self.event(b, "第二个真实锚点", 300, impact=0.8)
        self.assertIn(source, b.nodes[first]["anchor_info"]["bridge_ids"])
        with patch(CLOCK, return_value=T0 + 100):
            b.update(source, session_id="其他会话")
        for anchor in (first, second):
            info = node(b.export(as_of=T0 + 101), anchor)["anchor_info"]
            self.assertEqual(info["bridge_ids"], [])
            self.assertEqual(info["context_snippets"], [])
            self.assertNotIn(b._key(anchor, source), b.edges)

    def test_existing_source_time_change_reclassifies_context_instead_of_archiving_old_role(self):
        b = self.make()
        source = self.event(b, "移动实际发生时间的事件", 100)
        anchor = self.event(b, "实际情绪时刻", 200, impact=0.8)
        with patch(CLOCK, return_value=T0 + 100):
            b.update(source, event_at=T0 - 10000 + 300)
        info = node(b.export(as_of=T0 + 101), anchor)["anchor_info"]
        self.assertNotIn(source, info["before_ids"])
        self.assertIn(source, info["after_ids"])

    def test_past_recall_cannot_leak_later_recorded_backdated_context_even_after_archival(self):
        b = self.make()
        anchor = self.event(b, "历史锚点唯一标题", 100, impact=0.8)
        with patch(CLOCK, return_value=T0 + 100):
            future = b.add("后来才记录的秘密标题", "后来秘密正文", kind="episode",
                           event_at=T0 - 10000 + 200, session_id="真实会话")
        self.assertIn(future, b.nodes[anchor]["anchor_info"]["after_ids"])
        past = T0 + 1
        info = node(b.export(as_of=past), anchor)["anchor_info"]
        self.assertEqual(info["after_ids"], [])
        hit = next(h for h in b.recall("历史锚点唯一标题", as_of=past)["hits"] if h["id"] == anchor)
        self.assertNotIn("后来秘密", json.dumps(hit, ensure_ascii=False))
        self.assertNotIn(future, json.dumps(hit))
        with patch(CLOCK, return_value=T0 + 202 * DAY):
            b.forget(now=T0 + 202 * DAY)
        self.assertNotIn(future, b.nodes)
        hit = next(h for h in b.recall("历史锚点唯一标题", as_of=past)["hits"] if h["id"] == anchor)
        self.assertEqual(hit["context_snippets"], [])
        self.assertEqual(hit["anchor_info"]["after_ids"], [])

    def test_past_projection_excludes_future_event_and_not_yet_formed_bridge(self):
        b = self.make(context_before=0, context_after=0)
        first = self.event(b, "最早锚点", 100, impact=0.8)
        source = self.event(b, "当时已知小事", 200)
        with patch(CLOCK, return_value=T0 + 100):
            second = b.add("后来锚点", kind="episode", impact=0.8,
                           event_at=T0 - 10000 + 300, session_id="真实会话")
        info = node(b.export(as_of=T0 + 1), first)["anchor_info"]
        self.assertEqual(info["bridge_ids"], [])
        self.assertEqual(info["bridges"], [])
        self.assertEqual(info["context_snippets"], [])
        self.assertIn(source, b.nodes[first]["anchor_info"]["bridge_ids"])
        self.assertEqual(b.nodes[first]["anchor_info"]["bridges"][0]["other_anchor"], second)

    def test_past_projection_excludes_context_with_future_event_time(self):
        b = self.make()
        anchor = self.add(b, "时间锚点", impact=0.8, session_id="会话", event_at=T0 - 1)
        future = self.add(b, "还没有发生的正文", session_id="会话", event_at=T0 + 100)
        with patch(CLOCK, return_value=T0 + 200):
            b.update(anchor, text="触发重新计算")
        self.assertIn(future, b.nodes[anchor]["anchor_info"]["after_ids"])
        info = node(b.export(as_of=T0 + 1), anchor)["anchor_info"]
        self.assertEqual(info["after_ids"], [])
        self.assertEqual(info["context_snippets"], [])


class ConfigAndCapacityTests(MemoryHelpers, unittest.TestCase):
    def test_environment_overrides_saved_and_explicit_configuration_on_initialization(self):
        saved = {"config": Config(recovery_days=100, k=3).to_dict()}
        with patch.dict(os.environ, {"NKB_RECOVERY_DAYS": "365", "NKB_K": "11", "NKB_ANCHOR_THRESHOLD": "0.8"}):
            b = Brain(saved, config=Config(recovery_days=150, k=5))
            self.assertEqual(b.config.recovery_days, 365)
            self.assertEqual(b.config.k, 11)
            self.assertEqual(b.config.anchor_threshold, 0.8)
            self.assertEqual(Brain.new().config.recovery_days, 365)

    def test_reflection_at_capacity_skips_without_evicting_or_partially_writing(self):
        b = self.make(max_nodes=3)
        for i in range(3):
            self.add(b, f"容量内真实经历{i}", tags=["共同标签"])
        before = deepcopy(b.to_dict())
        result = reflect(b, now=T0 + 1)
        self.assertEqual(result["created"], [])
        self.assertEqual(result["skipped"], ["共同标签"])
        self.assertEqual(result["skip_reasons"][0]["reason"], "capacity_limit")
        self.assertEqual(before, b.to_dict())

    def test_multiple_reflections_respect_remaining_capacity_budget(self):
        b = self.make(max_nodes=4)
        members = [self.add(b, f"双标签经历{i}", tags=["标签甲", "标签乙"]) for i in range(3)]
        with patch(CLOCK, return_value=T0 + 1):
            result = reflect(b, now=T0 + 1, max_new=2)
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(len(b.nodes), 4)
        self.assertTrue(all(nid in b.nodes for nid in members))
        self.assertEqual(result["skip_reasons"][0]["reason"], "capacity_limit")

    def test_full_configuration_roundtrip(self):
        cfg = Config(recovery_days=123, anchor_threshold=0.8, context_before=1,
                     context_after=3, context_window_hours=2, bridge_window_hours=8,
                     bridge_max_events=4, max_nodes=50, edge_half_life=25,
                     salience_bump=0.25, damping=0.5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brain.json"
            b = Brain.new(path, config=cfg)
            b.save()
            self.assertEqual(Brain.open(path).config.to_dict(), cfg.to_dict())

    def test_old_half_life_only_data_still_loads(self):
        b = Brain({"half_life": {"episode": 45}})
        self.assertEqual(b.config.half_life["episode"], 45)
        self.assertEqual(b.config.recovery_days, 200)

    def test_configuration_rejects_nonfinite_wrong_types_and_unbounded_counts(self):
        for invalid in ({"recovery_days": 0}, {"anchor_threshold": 1.1},
                        {"context_before": -1}, {"context_after": 1.2},
                        {"bridge_max_events": True}, {"max_nodes": 0},
                        {"context_window_hours": float("nan")},
                        {"edge_half_life": float("inf")}, {"half_life": {"episode": -2}}):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                Config(**invalid)

    def test_capacity_reclaims_weakest_and_never_silently_drops_protected_core(self):
        b = self.make(max_nodes=2)
        protected = self.add(b, "重要核心", impact=0.9)
        weak = self.add(b, "普通边缘", salience=0.1)
        replacement = self.add(b, "新来的真实记忆")
        self.assertEqual(set(b.nodes), {protected, replacement})
        self.assertEqual(b.meta["last_capacity_evicted_ids"], [weak])
        b.update(replacement, meta={"important": True})
        before = deepcopy(b.to_dict())
        with self.assertRaises(ValidationError):
            self.add(b, "放不下的记忆")
        self.assertEqual(before, b.to_dict())

    def test_bad_input_does_not_evict_anything_or_partially_update(self):
        b = self.make(max_nodes=1)
        nid = self.add(b, "原记录")
        before = deepcopy(b.to_dict())
        with self.assertRaises(ValidationError):
            self.add(b, "坏记录", event_at=float("nan"))
        with self.assertRaises(ValidationError):
            b.update(nid, label="会被回滚", salience=float("nan"))
        self.assertEqual(before, b.to_dict())


if __name__ == "__main__":
    unittest.main()
