"""独立复现实验的回归：编辑、历史泄漏、真实关系和导入节点身份。"""
from __future__ import annotations

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.errors import ValidationError
from nkb.ingest import ingest_text
from nkb.adapters import mcp
from nkb.core.lifecycle import reflect

T0 = 1_700_000_000.0
DAY = 86400.0


class EngineRegressionTests(unittest.TestCase):
    def setUp(self):
        self.clock_patch = patch("nkb.core.brain._now", return_value=T0)
        self.clock = self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.brain = Brain.new()

    def at(self, timestamp):
        self.clock.return_value = timestamp

    def snapshot_node(self, nid, at=None):
        return next(n for n in self.brain.export(as_of=at)["nodes"] if n["id"] == nid)

    def test_impact_edit_settles_old_decay_before_applying_new_half_life(self):
        nid = self.brain.add("一条可编辑经历", kind="episode", salience=0.8)
        self.at(T0 + 60 * DAY)
        self.brain.update(nid, impact=0.5)
        n = self.brain.nodes[nid]
        self.assertAlmostEqual(self.snapshot_node(nid)["effective_salience"], 0.4)
        self.assertEqual(n["reinforced"], T0)
        self.assertEqual(n["recalls"], 0)
        self.assertEqual(n["decay_at"], T0 + 60 * DAY)
        self.at(T0 + 120 * DAY)
        self.assertAlmostEqual(self.snapshot_node(nid)["effective_salience"],
                               0.4 * 0.5 ** (60 / (60 * 1.75)), places=7)

    def test_kind_edit_does_not_restore_original_undecayed_salience(self):
        nid = self.brain.add("经历成为概念", kind="episode", salience=0.8)
        self.at(T0 + 60 * DAY)
        self.brain.update(nid, kind="concept")
        self.assertAlmostEqual(self.snapshot_node(nid)["effective_salience"], 0.4)
        self.at(T0 + 1000 * DAY)
        self.assertAlmostEqual(self.snapshot_node(nid)["effective_salience"], 0.4)
        self.assertEqual(self.brain.nodes[nid]["reinforced"], T0)
        self.assertEqual(self.brain.nodes[nid]["recalls"], 0)

    def test_body_edit_does_not_reset_the_200_day_recovery_window(self):
        nid = self.brain.add("普通经历", "旧正文", kind="episode", salience=0.8)
        self.at(T0 + 190 * DAY)
        self.brain.update(nid, text="修改过的正文")
        self.assertEqual(self.snapshot_node(nid)["state"], "dormant")
        self.assertEqual(self.brain.nodes[nid]["reinforced"], T0)
        self.at(T0 + 201 * DAY)
        self.assertEqual(self.brain.reinforce([nid])["nodes"], 0)
        self.brain.forget()
        self.assertNotIn(nid, self.brain.nodes)

    def test_all_mutable_fields_reject_invalid_values_atomically(self):
        nid = self.brain.add("保留原记录", "原正文", kind="episode", session_id="s")
        other = self.brain.add("第二条真实记录")
        self.brain.link(nid, other)
        invalid = [{"label": None}, {"label": "  "}, {"text": None}, {"text": []},
                   {"kind": None}, {"kind": " "}, {"tags": None}, {"tags": "tag"},
                   {"tags": [1]}, {"impact": True}, {"impact": float("nan")},
                   {"impact": 1.01}, {"salience": None}, {"salience": -1},
                   {"meta": []}, {"meta": None}, {"meta": ""},
                   {"meta": {"important": "true"}}, {"session_id": []},
                   {"session_id": " "}, {"event_at": None},
                   {"event_at": float("inf")}, {"meta": {"event_at": "yesterday"}},
                   {"meta": {"session_id": 123}}]
        self.at(T0 + 60 * DAY)
        for fields in invalid:
            with self.subTest(fields=fields):
                before = deepcopy(self.brain.to_dict())
                vectors = deepcopy(self.brain._vec)
                with self.assertRaises(ValidationError):
                    self.brain.update(nid, **fields)
                self.assertEqual(before, self.brain.to_dict())
                self.assertEqual(vectors, self.brain._vec)

    def test_edit_preserves_identity_creation_and_actual_recall_counters(self):
        nid = self.brain.add("原标签", "原文", kind="episode")
        self.at(T0 + 10)
        self.brain.reinforce([nid])
        self.at(T0 + 20)
        self.brain.update(nid, label="  编辑后的标签  ", text="新正文", kind=" fact ",
                          tags=["新标签"], impact=0.2, meta={"important": False},
                          id="不能改写", created=1, recalls=999, reinforced=1)
        n = self.brain.nodes[nid]
        self.assertEqual((n["id"], n["created"], n["recalls"], n["reinforced"]), (nid, T0, 1, T0 + 10))
        self.assertEqual((n["label"], n["kind"], n["text"]), ("编辑后的标签", "fact", "新正文"))
        self.assertEqual(n["tags"], ["新标签"])
        self.assertEqual(n["impact"], 0.2)
        self.assertEqual(n["updated"], T0 + 20)

    def test_metadata_is_copied_instead_of_accepting_future_outside_mutations(self):
        incoming = {"nested": {"value": "真实原文"}}
        nid = self.brain.add("元数据来源", meta=incoming)
        incoming["nested"]["value"] = "不能偷偷写进去"
        self.assertEqual(self.brain.nodes[nid]["meta"]["nested"]["value"], "真实原文")
        update = {"nested": {"value": "明确编辑"}}
        self.brain.update(nid, meta=update)
        update["nested"]["value"] = "另一段未授权变动"
        self.assertEqual(self.brain.nodes[nid]["meta"]["nested"]["value"], "明确编辑")

    def test_clearing_session_removes_legacy_alias_and_stays_cleared_after_reload(self):
        anchor = self.brain.add("会话锚点", kind="episode", impact=0.8,
                                session_id="s", event_at=T0 - 10)
        source = self.brain.add("有旧别名的记录", kind="episode", meta={"session_id": "s"})
        self.assertIn(source, self.brain.nodes[anchor]["anchor_info"]["after_ids"])
        self.at(T0 + 1)
        self.brain.update(source, session_id=None)
        self.assertIsNone(self.brain.nodes[source]["session_id"])
        self.assertNotIn("session_id", self.brain.nodes[source]["meta"])
        self.assertNotIn(source, self.brain.nodes[anchor]["anchor_info"]["after_ids"])
        reloaded = Brain(deepcopy(self.brain.to_dict()))
        self.assertIsNone(reloaded.nodes[source]["session_id"])
        self.assertNotIn(self.brain._key(anchor, source), reloaded.edges)

    def test_explicit_event_edits_synchronize_metadata_aliases(self):
        nid = self.brain.add("带时间别名", kind="fact", meta={"session_id": "old", "event_at": T0 - 10})
        self.at(T0 + 1)
        self.brain.update(nid, event_at=T0 - 5, session_id=" new ")
        n = self.brain.nodes[nid]
        self.assertEqual(n["event_at"], n["meta"]["event_at"])
        self.assertEqual((n["session_id"], n["meta"]["session_id"]), ("new", "new"))

    def test_episode_doc_role_changes_update_real_context_membership(self):
        anchor = self.brain.add("隐式经历锚点", kind="episode", impact=0.8,
                                session_id="s", event_at=T0 - 10)
        source = self.brain.add("默认文档", kind="doc", session_id="s")
        self.assertFalse(self.brain.nodes[source]["event_recorded"])
        self.at(T0 + 1)
        self.brain.update(source, kind="episode")
        self.assertTrue(self.brain.nodes[source]["event_recorded"])
        self.assertIn(source, self.brain.nodes[anchor]["anchor_info"]["after_ids"])
        self.at(T0 + 2)
        self.brain.update(source, kind="doc")
        self.assertFalse(self.brain.nodes[source]["event_recorded"])
        self.assertNotIn(source, self.brain.nodes[anchor]["anchor_info"]["after_ids"])
        self.assertNotIn(self.brain._key(anchor, source), self.brain.edges)

    def test_explicit_event_provenance_survives_reload_and_kind_change(self):
        source = self.brain.add("明确记过时间", kind="episode", event_at=T0 - 20)
        reloaded = Brain(deepcopy(self.brain.to_dict()))
        self.at(T0 + 1)
        reloaded.update(source, kind="fact")
        self.assertTrue(reloaded.nodes[source]["event_recorded"])
        self.assertTrue(reloaded.nodes[source]["event_explicit"])

    def test_document_import_does_not_fabricate_experience_or_emotional_anchors(self):
        anchor = self.brain.add("文档不属于经历", kind="episode", impact=0.8, session_id="s")
        result = ingest_text(self.brain, "# 导入说明\n只是一段文档正文", link=False)
        self.assertEqual(result["added"], 1)
        docs = [n for n in self.brain.nodes.values() if n["kind"] == "doc"]
        self.assertEqual(len(docs), 1)
        self.assertFalse(docs[0]["event_recorded"])
        self.assertEqual(docs[0]["impact"], 0)
        self.assertEqual(self.brain.nodes[anchor]["anchor_info"]["context_snippets"], [])

    def test_past_recall_never_returns_a_later_edited_body_even_with_expired_enabled(self):
        nid = self.brain.add("历史唯一标题", "当时原文", kind="concept")
        self.at(T0 + 100)
        self.brain.update(nid, text="未来改写秘密正文", tags=["后来秘密标签"], meta={"secret": "未来秘密元数据"})
        for expired in (False, True):
            result = self.brain.recall("历史唯一标题", as_of=T0 + 1, include_expired=expired)
            self.assertEqual(result["hits"], [])
        projected = self.snapshot_node(nid, T0 + 1)
        self.assertFalse(projected["history_available"])
        self.assertIn("旧正文未保存", projected["history_note"])
        self.assertNotIn("秘密", json.dumps(projected, ensure_ascii=False))
        self.assertEqual(self.snapshot_node(nid)["text"], "未来改写秘密正文")

    def test_past_export_omits_uncreated_nodes_and_future_references(self):
        old = self.brain.add("当时已知事实", kind="fact")
        self.at(T0 + 100)
        future = self.brain.add("后来事实秘密标题", "秘密正文", kind="fact")
        self.brain.supersede(old, future, at=T0 + 100)
        result = self.brain.export(as_of=T0 + 1)
        self.assertNotIn(future, [n["id"] for n in result["nodes"]])
        self.assertNotIn("秘密", json.dumps(result, ensure_ascii=False))
        self.assertIsNone(next(n for n in result["nodes"] if n["id"] == old)["superseded_by"])
        self.assertEqual(result["stats"]["nodes"], 1)

    def test_past_expired_recall_does_not_bypass_future_creation_check(self):
        old = self.brain.add("旧的alpha", kind="fact")
        self.at(T0 + 100)
        new = self.brain.add("未来alpha秘密", kind="fact")
        self.brain.supersede(old, new, at=T0 - 1)
        result = self.brain.recall("alpha", as_of=T0 + 1, include_expired=True)
        self.assertNotIn(new, [h["id"] for h in result["hits"]])

    def test_past_export_and_recall_do_not_reuse_later_created_or_strengthened_edges(self):
        a = self.brain.add("alpha种子", kind="concept")
        b = self.brain.add("完全不同终点", kind="concept")
        self.at(T0 + 100)
        self.brain.link(a, b, 0.9)
        self.assertEqual(self.brain.export(as_of=T0 + 1)["edges"], [])
        self.assertEqual([h["id"] for h in self.brain.recall("alpha", as_of=T0 + 1)["hits"]], [a])
        self.at(T0 + 200)
        self.brain.reinforce([a, b])
        self.assertEqual(self.brain.export(as_of=T0 + 101)["edges"], [])
        self.assertEqual([h["id"] for h in self.brain.recall("alpha", as_of=T0 + 101)["hits"]], [a])

    def test_zero_overlap_auto_link_does_not_create_a_fabricated_relationship(self):
        a = self.brain.add("量子颜色", kind="doc")
        b = self.brain.add("烤面包", kind="doc")
        self.assertEqual(self.brain.auto_link(b), [])
        self.assertEqual(self.brain.edges, {})
        similar = self.brain.add("量子颜色说明", kind="doc")
        self.assertEqual(self.brain.auto_link(similar)[0][0], a)

    def test_auto_link_does_not_attach_future_or_expired_source_nodes(self):
        self.brain.add("alpha已知概念", kind="concept")
        self.at(T0 + 100)
        future = self.brain.add("alpha未来事件", kind="episode", event_at=T0 + 200)
        self.assertEqual(self.brain.auto_link(future), [])
        expired = self.brain.add("alpha普通经历", kind="episode")
        self.at(T0 + 201 * DAY)
        self.assertEqual(self.brain.auto_link(expired), [])

    def test_encoder_failure_during_update_does_not_partially_modify_nodes_or_edges(self):
        def encode(text):
            if "使编码失败" in text:
                raise RuntimeError("expected encoder failure")
            return {text}
        b = Brain.new(encode=encode)
        nid = b.add("原节点")
        before = deepcopy(b.to_dict())
        vectors = deepcopy(b._vec)
        with self.assertRaises(RuntimeError):
            b.update(nid, label="使编码失败", meta={"important": True})
        self.assertEqual(before, b.to_dict())
        self.assertEqual(vectors, b._vec)

    def test_reflection_does_not_launder_superseded_sources_into_permanent_current_facts(self):
        members = [self.brain.add(f"员工在A公司{i}", kind="fact", tags=["工作"]) for i in range(3)]
        rid = reflect(self.brain, now=T0)["created"][0]["id"]
        self.at(T0 + 10)
        replacement = self.brain.add("员工已在B公司", kind="fact")
        self.brain.supersede(members[0], replacement)
        before = deepcopy(self.brain.to_dict())
        self.assertNotIn(rid, [h["id"] for h in self.brain.recall("员工在A公司")["hits"]])
        self.assertIn(rid, [h["id"] for h in self.brain.recall("员工在A公司", include_expired=True)["hits"]])
        state = self.snapshot_node(rid)
        self.assertEqual(state["state"], "forgotten")
        self.assertEqual(state["invalidation_reason"], "source_invalidated")
        self.assertEqual(state["invalidated_members"], [members[0]])
        self.assertEqual(before, self.brain.to_dict())

    def test_age_forgetting_of_sources_does_not_erase_valid_consolidation(self):
        members = [self.brain.add(f"共同学习经验{i}", kind="episode", tags=["学习"]) for i in range(3)]
        rid = reflect(self.brain, now=T0)["created"][0]["id"]
        self.at(T0 + 201 * DAY)
        self.brain.forget()
        self.assertTrue(all(nid not in self.brain.nodes for nid in members))
        self.assertIn(rid, [h["id"] for h in self.brain.recall("共同学习经验")["hits"]])
        self.assertTrue(self.snapshot_node(rid)["recoverable"])

    def test_removing_explicitly_invalid_source_cannot_reactivate_its_old_reflection(self):
        members = [self.brain.add(f"旧工作事实{i}", kind="fact", tags=["工作"]) for i in range(3)]
        rid = reflect(self.brain, now=T0)["created"][0]["id"]
        self.at(T0 + 10)
        new = self.brain.add("已纠正的工作事实", kind="fact")
        self.brain.supersede(members[0], new)
        self.brain.remove(members[0])
        self.assertFalse(self.snapshot_node(rid)["recoverable"])
        self.assertEqual(self.snapshot_node(rid)["invalidated_members"], [members[0]])
        reloaded = Brain(deepcopy(self.brain.to_dict()))
        self.assertNotIn(rid, [h["id"] for h in reloaded.recall("旧工作事实")["hits"]])

    def test_mcp_failed_persistence_rolls_back_every_mutating_tool(self):
        a = self.brain.add("alpha知识一")
        b = self.brain.add("alpha知识二")
        cases = [("kb_add", {"label": "不能保留的新增节点"}),
                 ("kb_link", {"a": a, "b": b}),
                 ("kb_recall", {"query": "alpha知识", "learn": True})]
        for name, args in cases:
            with self.subTest(name=name):
                before = deepcopy(self.brain.to_dict())
                vectors = deepcopy(self.brain._vec)
                with patch.object(self.brain, "persist", side_effect=OSError("expected save failure")):
                    result = mcp.call_tool(self.brain, name, args)
                self.assertTrue(result["isError"])
                self.assertEqual(before, self.brain.to_dict())
                self.assertEqual(vectors, self.brain._vec)

    def test_mcp_failed_render_does_not_commit_learning(self):
        self.brain.add("触发学习的知识")
        before = deepcopy(self.brain.to_dict())
        with patch("nkb.adapters.mcp.render.to_markdown", side_effect=RuntimeError("expected render failure")), \
                patch.object(self.brain, "persist") as persist:
            result = mcp.call_tool(self.brain, "kb_recall", {"query": "触发学习的知识", "learn": True})
        self.assertTrue(result["isError"])
        self.assertEqual(before, self.brain.to_dict())
        persist.assert_not_called()

    def test_mcp_readonly_queries_and_preview_never_persist_or_change_graph(self):
        self.brain.add("只读知识")
        before = deepcopy(self.brain.to_dict())
        with patch.object(self.brain, "persist") as persist:
            for name, args in (("kb_recall", {"query": "只读知识"}),
                               ("kb_recall", {"query": "只读知识", "learn": False}),
                               ("kb_preview", {"days": 200})):
                self.assertFalse(mcp.call_tool(self.brain, name, args).get("isError"))
        persist.assert_not_called()
        self.assertEqual(before, self.brain.to_dict())


if __name__ == "__main__":
    unittest.main()
