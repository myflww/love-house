"""Review backlogs must not cap storage or stall otherwise valid memory work."""
from copy import deepcopy
import json
import unittest

from nkb import Brain
from nkb.companion import record_turn
from nkb.companion.retention import enable_temporal_retention
from nkb.organizer.config import get_profile, save_profile
from nkb.organizer.model import OrganizerError
from nkb.organizer.state import (apply_plan, build_input, forget_plan_data,
                                 review_candidate, rollback, validate_plan)


class OrganizerCandidateCapacityTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain.new(name="合成候选积压测试")
        self.brain.meta["library_id"] = "synthetic-library"
        enable_temporal_retention(self.brain)
        save_profile(self.brain, enabled=True, base_url="https://offline.invalid/v1", model="FAKE")
        self.profile = get_profile(self.brain)
        self.raw_id = record_turn(self.brain, "我喜欢温水。", "我会记得。", "synthetic-window", "one")
        self.raw = deepcopy(self.brain.nodes[self.raw_id])
        self.job_number = 0

    def operation(self, *, key="drink.temperature", action="candidate"):
        return {"action": action, "layer": "preference", "key": key, "text": "饮水偏好",
                "certainty": "clear", "domain": "real", "evidence": [
                    {"id": self.raw_id, "role": "user", "quote": "我喜欢温水。"}]}

    def plan(self, operations):
        self.job_number += 1
        payload, guards = build_input(self.brain, "synthetic-library",
            [{"raw_id": self.raw_id, "progress": "{}"}], self.profile)
        if self.profile['max_input_chars']:
            self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False)), self.profile["max_input_chars"])
        return validate_plan({"version": 1, "operations": operations}, payload, guards,
                             f"synthetic-job-{self.job_number}", self.profile)

    def apply(self, operations):
        plan = self.plan(operations)
        return plan, apply_plan(self.brain, plan, "synthetic-library")

    def seed_backlog(self):
        # Every existing candidate is produced through normal strict validation,
        # rather than injecting abbreviated or invalid objects into metadata.
        for batch in range(10):
            self.apply([self.operation(key=f"review.{batch}.{index}") for index in range(10)])
        self.assertEqual(len(self.brain.meta["organizer_candidates"]), 100)
        return deepcopy(self.brain.meta["organizer_candidates"])

    def test_over_one_hundred_candidates_do_not_block_valid_facts_or_auto_accept_reviews(self):
        previous = self.seed_backlog()
        plan, result = self.apply([self.operation(action="remember"), self.operation(key="review.more")])
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(len(self.brain.meta["organizer_candidates"]), 101)
        self.assertEqual(self.brain.meta["organizer_candidates"][:100], previous)
        self.assertTrue(all(c["status"] == "pending" for c in self.brain.meta["organizer_candidates"]))
        self.assertEqual(self.brain.nodes[self.raw_id], self.raw)
        self.assertEqual(self.brain.nodes[result["created"][0]]["text"], "我喜欢温水。")
        duplicate = apply_plan(self.brain, plan, "synthetic-library")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(self.brain.meta["organizer_candidates"]), 101)

    def test_candidate_after_old_limit_can_be_reviewed_without_discarding_backlog(self):
        previous = self.seed_backlog()
        _, result = self.apply([self.operation(key="review.after-limit")])
        candidate_id = result["candidates"][0]
        self.assertEqual(review_candidate(self.brain, candidate_id, "accept")["status"], "accepted")
        self.assertEqual(len(self.brain.meta["organizer_candidates"]), 101)
        self.assertEqual(self.brain.meta["organizer_candidates"][:100], previous)
        self.apply([self.operation(key="review.after-accept")])
        self.assertEqual(len(self.brain.meta["organizer_candidates"]), 102)

    def test_rollback_and_privacy_reset_keep_their_existing_scope_above_old_limit(self):
        previous = self.seed_backlog()
        plan, _ = self.apply([self.operation(key="review.new-one"), self.operation(key="review.new-two")])
        self.assertEqual(len(self.brain.meta["organizer_candidates"]), 102)
        rollback(self.brain, plan["job_id"])
        self.assertEqual(self.brain.meta["organizer_candidates"], previous)
        self.apply([self.operation(key="review.after-undo")])
        counts = forget_plan_data(self.brain, [self.raw_id])
        self.assertEqual(counts["candidates"], 101)
        self.assertEqual(self.brain.meta["organizer_candidates"], [])
        self.assertEqual(self.brain.nodes[self.raw_id], self.raw)

    def test_per_request_operation_bound_is_still_enforced(self):
        before = deepcopy(self.brain.to_dict())
        with self.assertRaises(OrganizerError) as caught:
            self.plan([self.operation(key=f"review.{i}") for i in range(self.profile["max_ops"] + 1)])
        self.assertEqual(caught.exception.code, "invalid_output")
        self.assertEqual(self.brain.to_dict(), before)

    def test_adaptive_snapshot_discards_legacy_count_cap_before_organizing(self):
        saved = deepcopy(self.brain.to_dict())
        saved["config"]["max_nodes"] = 1
        self.brain = Brain(saved)
        self.assertIsNone(self.brain.config.max_nodes)
        _, result = self.apply([self.operation(action="remember")])
        self.assertEqual(len(result["created"]), 1)
        self.assertGreater(len(self.brain.nodes), 1)
        self.assertEqual(self.brain.nodes[self.raw_id], self.raw)

    def test_nonadaptive_explicit_node_limit_remains_enforced_without_eviction(self):
        self.brain.meta.pop("memory_retention")
        self.brain.config.max_nodes = 1
        before = deepcopy(self.brain.to_dict())
        with self.assertRaises(OrganizerError) as caught:
            self.apply([self.operation(action="remember")])
        self.assertEqual(caught.exception.code, "memory_capacity")
        self.assertEqual(self.brain.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
