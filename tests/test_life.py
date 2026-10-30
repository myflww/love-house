"""生命周期的行为测试：时效、情感权重、承诺、反思、评测。

这些测的是"过了一段时间之后会怎样"，所以都显式传 now，不依赖真实时钟。
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nkb import Brain                          # noqa: E402
from nkb import bench                         # noqa: E402
from nkb.core.lifecycle import reflect, tick  # noqa: E402

DAY = 86400.0


class TestTemporal(unittest.TestCase):
    def setUp(self):
        self.b = Brain.new()
        self.old = self.b.add("他在 A 公司做后端", kind="fact", tags=["工作"])
        self.new = self.b.add("他在 B 公司做产品", kind="fact", tags=["工作"])

    def test_supersede_hides_old_but_keeps_it(self):
        self.b.supersede(self.old, self.new)
        labels = [h["label"] for h in self.b.recall("他在哪家公司", k=5)["hits"]]
        self.assertIn("他在 B 公司做产品", labels)
        self.assertNotIn("他在 A 公司做后端", labels)
        self.assertIn(self.old, self.b.nodes)          # 没删，历史还在

    def test_include_expired_shows_history(self):
        self.b.supersede(self.old, self.new)
        labels = [h["label"] for h in
                  self.b.recall("他在哪家公司", k=5, include_expired=True)["hits"]]
        self.assertIn("他在 A 公司做后端", labels)

    def test_history_chain(self):
        self.b.supersede(self.old, self.new)
        chain = self.b.history(self.old)
        self.assertEqual([c["label"] for c in chain],
                         ["他在 A 公司做后端", "他在 B 公司做产品"])
        self.assertIsNotNone(chain[0]["valid_to"])
        self.assertIsNone(chain[1]["valid_to"])

    def test_invalidated_edge_leaves_retrieval(self):
        a = self.b.add("甲", tags=["x"])
        c = self.b.add("乙", tags=["x"])
        self.b.link(a, c, 0.9)
        self.assertEqual(len(self.b.neighbors(a)), 1)
        self.b.invalidate(a, c)
        self.assertEqual(len(self.b.neighbors(a)), 0)
        self.assertEqual(len(self.b.neighbors(a, as_of=0)), 1)   # 回看历史还在


class TestImpact(unittest.TestCase):
    def test_emotional_memory_survives_longer(self):
        b = Brain.new()
        deep = b.add("那一晚", kind="episode", impact=0.9, salience=0.6)
        flat = b.add("普通的一天", kind="episode", impact=0.0, salience=0.6)
        b.forget(now=time.time() + 260 * DAY)
        self.assertIn(deep, b.nodes)
        self.assertNotIn(flat, b.nodes)

    def test_impact_boosts_seed_score(self):
        b = Brain.new()
        b.add("同一句话", kind="fact", impact=0.0, salience=0.6)
        b.add("同一句话", kind="fact", impact=1.0, salience=0.6, id="hot")
        scores = b.seed_scores("同一句话")
        self.assertGreater(scores["hot"], max(v for k, v in scores.items() if k != "hot"))

    def test_impact_bounds(self):
        b = Brain.new()
        with self.assertRaises(ValueError):
            b.add("甲", impact=1.5)


class TestCommitment(unittest.TestCase):
    def test_due_lists_overdue_first(self):
        b = Brain.new()
        b.commit("明天要做", due=time.time() + DAY)
        b.commit("上周就该做", due=time.time() - 7 * DAY)
        rows = b.due()
        self.assertEqual(len(rows), 2)
        self.assertGreater(rows[0]["overdue_days"], 0)
        self.assertLess(rows[1]["overdue_days"], 0)

    def test_resolve_removes_from_due(self):
        b = Brain.new()
        nid = b.commit("要做的事", due=time.time())
        self.assertEqual(len(b.due()), 1)
        b.resolve(nid, "做完了")
        self.assertEqual(len(b.due()), 0)
        self.assertEqual(b.nodes[nid]["meta"]["status"], "done")

    def test_commitment_does_not_decay(self):
        b = Brain.new()
        nid = b.commit("很久以后的承诺", due=time.time() + 999 * DAY)
        b.forget(now=time.time() + 900 * DAY)
        self.assertIn(nid, b.nodes)


class TestReflection(unittest.TestCase):
    def build(self):
        b = Brain.new()
        for i, (label, tag) in enumerate([
            ("不该用向量库做关联", "设计"), ("遗忘要分级", "设计"),
            ("保留系数不能省", "设计"), ("今天天气一般", "杂事")]):
            b.add(label, f"第{i}条", kind="fact", tags=[tag], impact=0.2)
        return b

    def test_creates_and_links(self):
        b = self.build()
        r = reflect(b, min_cluster=3)
        self.assertEqual(len(r["created"]), 1)
        rid = r["created"][0]["id"]
        self.assertEqual(b.nodes[rid]["kind"], "reflection")
        self.assertEqual(len(b.neighbors(rid)), 3)
        self.assertIn("向量库", b.nodes[rid]["text"])

    def test_idempotent(self):
        b = self.build()
        reflect(b, min_cluster=3)
        again = reflect(b, min_cluster=3)
        self.assertEqual(again["created"], [])
        self.assertIn("设计", again["skipped"])

    def test_reflection_does_not_decay(self):
        b = self.build()
        r = reflect(b, min_cluster=3)
        rid = r["created"][0]["id"]
        b.forget(now=time.time() + 2000 * DAY)
        self.assertIn(rid, b.nodes)

    def test_rewrite_hook(self):
        b = self.build()
        r = reflect(b, min_cluster=3, rewrite=lambda ms: "归纳：" + str(len(ms)))
        rid = r["created"][0]["id"]
        self.assertTrue(b.nodes[rid]["text"].startswith("归纳："))


class TestTickAndBench(unittest.TestCase):
    def test_tick_reports_three_things(self):
        b = Brain.new()
        b.commit("到期的事", due=time.time() - DAY)
        r = tick(b)
        self.assertIn("forgot", r)
        self.assertIn("reflected", r)
        self.assertEqual(len(r["due"]), 1)
        self.assertIn("待办 1 件", r["summary"])

    def test_leave_one_out_runs(self):
        from nkb.core.seed import demo_brain
        b = demo_brain()
        r = bench.leave_one_out(b, k=3)
        self.assertEqual(r["cases"], len([n for n in b.nodes.values()
                                          if n["kind"] != "reflection"]))
        self.assertGreater(r["hit_rate"], 0.5)

    def test_probes_abstain(self):
        from nkb.core.seed import demo_brain
        b = demo_brain()
        r = bench.run_probes(b, [
            {"query": "为什么不用向量库", "expect": ["为什么不用向量库"]},
            {"query": "量子色动力学", "abstain": True},
        ], k=3)
        self.assertEqual(r["hit_rate"], 1.0)

    def test_save_and_reload_keeps_validity(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"
            b = Brain.new(p)
            old = b.add("旧事实", kind="fact")
            new = b.add("新事实", kind="fact")
            b.supersede(old, new)
            b.commit("承诺", due=time.time() + DAY)
            b.save()

            again = Brain.open(p)
            self.assertIsNotNone(again.nodes[old]["valid_to"])
            self.assertEqual(len(again.due()), 1)


if __name__ == "__main__":
    unittest.main()
