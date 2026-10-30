"""核心行为测试。只用标准库： python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nkb import Brain, bigram, dice                # noqa: E402
from nkb import render                             # noqa: E402
from nkb.adapters import mcp as mcp_server         # noqa: E402
from nkb.core.seed import demo_brain               # noqa: E402
from nkb.ingest import split_markdown              # noqa: E402

DAY = 86400.0


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "brain.json"

    def tearDown(self):
        self.tmp.cleanup()


class TestBasics(Temp):
    def test_bigrams_keeps_cjk_and_ascii(self):
        self.assertIn("咖啡", bigram("手冲咖啡"))
        self.assertIn("ab", bigram("abc"))
        self.assertEqual(bigram(""), set())

    def test_dice_bounds(self):
        self.assertAlmostEqual(dice({"a"}, {"a"}), 1.0)
        self.assertEqual(dice({"a"}, {"b"}), 0.0)
        self.assertEqual(dice(set(), {"a"}), 0.0)

    def test_add_rejects_empty_label(self):
        b = Brain.new()
        with self.assertRaises(ValueError):
            b.add("   ")

    def test_add_duplicate_id_rejected(self):
        b = Brain.new()
        b.add("甲", id="fixed")
        with self.assertRaises(ValueError):
            b.add("乙", id="fixed")

    def test_link_and_strengthen(self):
        b = Brain.new()
        a = b.add("甲")
        c = b.add("乙")
        w1 = b.link(a, c, 0.4)
        w2 = b.link(a, c, 0.4)
        self.assertGreater(w2, w1)
        self.assertLessEqual(w2, 1.0)
        self.assertEqual(len(b.edges), 1)

    def test_no_self_link(self):
        b = Brain.new()
        a = b.add("甲")
        with self.assertRaises(ValueError):
            b.link(a, a)


class TestRecall(Temp):
    def build(self):
        b = Brain.new()
        ids = {}
        ids["a"] = b.add("激活扩散", "从查询点燃节点，沿边扩散。", tags=["检索"])
        ids["b"] = b.add("赫布学习", "一起被召回就互相加强。", tags=["学习"])
        ids["c"] = b.add("遗忘曲线", "按半衰期指数衰减。", tags=["学习"])
        b.link(ids["a"], ids["b"], 0.8)
        b.link(ids["b"], ids["c"], 0.6)
        return b, ids

    def test_seed_and_two_hop(self):
        b, ids = self.build()
        r = b.recall("激活扩散", steps=2)
        self.assertTrue(r["hits"])
        self.assertEqual(r["hits"][0]["id"], ids["a"])
        self.assertEqual(r["hits"][0]["depth"], 0)
        depths = {h["id"]: h["depth"] for h in r["hits"]}
        self.assertIn(ids["b"], depths)
        self.assertEqual(depths[ids["b"]], 1)

    def test_path_is_explainable(self):
        b, ids = self.build()
        r = b.recall("激活扩散")
        hit = next(h for h in r["hits"] if h["id"] == ids["b"])
        self.assertEqual(hit["path"][0], ids["a"])
        self.assertEqual(hit["path_labels"][0], "激活扩散")

    def test_no_match_returns_empty_not_guess(self):
        b, _ = self.build()
        r = b.recall("量子色动力学")
        self.assertEqual(r["hits"], [])
        self.assertIn("没有命中", r["note"])

    def test_scores_normalised(self):
        b, _ = self.build()
        r = b.recall("激活扩散")
        self.assertLessEqual(max(h["score"] for h in r["hits"]), 1.0)


class TestLearning(Temp):
    def test_reinforce_saturates_below_one(self):
        b = Brain.new()
        a = b.add("甲")
        c = b.add("乙")
        for _ in range(60):
            b.reinforce([a, c], lr=0.5)
        self.assertLess(b.edges["|".join(sorted((a, c)))]["w"], 1.0)
        self.assertGreater(b.edges["|".join(sorted((a, c)))]["w"], 0.98)

    def test_reinforce_counts_pairs(self):
        b = Brain.new()
        ids = [b.add(f"节点{i}") for i in range(4)]
        info = b.reinforce(ids)
        self.assertEqual(info["nodes"], 4)
        self.assertEqual(info["pairs"], 6)   # C(4,2)

    def test_forget_is_graded(self):
        b = Brain.new()
        ep = b.add("一次经历", kind="episode", salience=0.9)
        cp = b.add("一个概念", kind="concept", salience=0.9)
        b.forget(now=__import__("time").time() + 300 * DAY)
        self.assertNotIn(ep, b.nodes)      # 半衰期 60 天 → 已跌破阈值
        self.assertIn(cp, b.nodes)         # 概念不衰减

    def test_decay_keeps_important_episode(self):
        b = Brain.new()
        ep = b.add("刚发生的事", kind="episode", salience=0.5)
        b.reinforce([ep])                  # 回血一次
        b.forget(now=__import__("time").time() + 1 * DAY)
        self.assertIn(ep, b.nodes)
        self.assertLess(b.nodes[ep]["salience"], 0.9)


class TestStorage(Temp):
    def test_roundtrip(self):
        b = Brain.new(self.path, name="往返")
        a = b.add("甲", "正文", tags=["x"], salience=0.7)
        c = b.add("乙")
        b.link(a, c, 0.55)
        b.save()

        again = Brain.open(self.path)
        self.assertEqual(again.name, "往返")
        self.assertEqual(len(again.nodes), 2)
        self.assertEqual(again.edges["|".join(sorted((a, c)))]["w"], 0.55)
        self.assertEqual(again.nodes[a]["tags"], ["x"])

    def test_open_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            Brain.open(Path(self.tmp.name) / "nope.json")

    def test_json_is_readable(self):
        b = Brain.new(self.path, name="可读")
        b.add("甲")
        b.save()
        raw = json.loads(self.path.read_text("utf-8"))
        self.assertEqual(raw["version"], 1)
        self.assertIn("half_life", raw)


class TestIngestAndRender(Temp):
    def test_split_markdown_by_heading(self):
        pairs = split_markdown("# 一\n正文一\n\n## 二\n正文二")
        self.assertEqual([p[0] for p in pairs], ["一", "二"])
        self.assertIn("正文一", pairs[0][1])

    def test_split_without_heading_falls_back_to_paragraphs(self):
        pairs = split_markdown("段落甲\n\n段落乙")
        self.assertEqual(len(pairs), 2)

    def test_ingest_is_idempotent(self):
        from nkb.ingest import ingest_dir
        src = Path(self.tmp.name) / "docs"
        src.mkdir()
        (src / "a.md").write_text("# 标题\n内容内容", encoding="utf-8")
        b = Brain.new()
        first = ingest_dir(b, src, verbose=False)
        second = ingest_dir(b, src, verbose=False)
        self.assertEqual(first["added"], 1)
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["skipped"], 1)

    def test_render_contains_scores_and_guardrail(self):
        b = demo_brain()
        r = b.recall("为什么不用向量库")
        md = render.to_markdown(r)
        self.assertIn("<knowledge", md)
        self.assertIn("不要用相似内容替代", md)
        self.assertIn("说没有", md)

    def test_render_empty_is_explicit(self):
        b = demo_brain()
        md = render.to_markdown(b.recall("完全无关的东西 zzz"))
        self.assertIn('hits="0"', md)


class TestMCP(unittest.TestCase):
    def setUp(self):
        self.brain = demo_brain()

    def test_initialize(self):
        resp = mcp_server.handle(self.brain, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(resp["result"]["serverInfo"]["name"], "neural-kb")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_notification_gets_no_reply(self):
        self.assertIsNone(mcp_server.handle(self.brain, {
            "jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list_shape(self):
        resp = mcp_server.handle(self.brain, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("kb_recall", names)
        for t in resp["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_tool_call_returns_content(self):
        res = mcp_server.call_tool(self.brain, "kb_recall", {"query": "赫布学习", "k": 3})
        self.assertIn("content", res)
        self.assertEqual(res["content"][0]["type"], "text")
        self.assertIn("赫布", res["content"][0]["text"])

    def test_unknown_tool_is_error_not_crash(self):
        res = mcp_server.call_tool(self.brain, "kb_nope", {})
        self.assertTrue(res.get("isError"))

    def test_bad_argument_is_error(self):
        res = mcp_server.call_tool(self.brain, "kb_add", {})
        self.assertTrue(res.get("isError"))

    def test_unknown_method(self):
        resp = mcp_server.handle(self.brain, {
            "jsonrpc": "2.0", "id": 9, "method": "nope"})
        self.assertEqual(resp["error"]["code"], -32601)

    def test_add_then_recall_roundtrip(self):
        r1 = mcp_server.call_tool(self.brain, "kb_add",
                                  {"label": "测试节点", "text": "一条通过 MCP 写入的知识",
                                   "kind": "fact"})
        self.assertFalse(r1.get("isError"))
        r2 = mcp_server.call_tool(self.brain, "kb_recall", {"query": "MCP 写入", "k": 5})
        self.assertIn("测试节点", r2["content"][0]["text"])


class TestDemo(unittest.TestCase):
    def test_demo_is_connected(self):
        b = demo_brain()
        self.assertGreaterEqual(len(b.nodes), 8)
        self.assertGreater(len(b.edges), 8)
        for nid in b.nodes:
            self.assertTrue(b.neighbors(nid), f"{nid} 是孤岛")

    def test_every_hit_has_path(self):
        b = demo_brain()
        for h in b.recall("检索是怎么工作的", steps=3)["hits"]:
            self.assertTrue(h["path"])
            self.assertEqual(len(h["path"]), len(h["path_labels"]))


if __name__ == "__main__":
    unittest.main()
