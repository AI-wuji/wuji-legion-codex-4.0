import copy
import unittest

from decision_audit import preserve_method_bindings, primary_review_state


class DecisionAuditTests(unittest.TestCase):
    def setUp(self):
        self.current = {"candidate_id": "A01", "name": "goal", "input": "request",
                        "output": "proposal", "consumer_and_counterexample": "not a file list",
                        "target_module_proposal": "intake", "professional_difference": "not a file list",
                        "approved_source": {"sha256": "current"}, "admission": "not_admitted",
                        "runtime": "not_implemented", "primary_method_attribution": "pending"}
        self.previous = {**copy.deepcopy(self.current),
                         "method_source_bindings": [{"source_id": "read-source", "lines": [1, 2]}],
                         "primary_method_attribution": "recorded_candidate_only",
                         "method_binding_reviewed_at": "2026-10-03",
                         "admission": "untrusted_claim", "runtime": "untrusted_claim"}

    def test_preserves_method_bindings_not_runtime_claims(self):
        previous = copy.deepcopy(self.previous)
        result = preserve_method_bindings(self.current, self.previous)
        self.assertEqual(result["method_source_bindings"], previous["method_source_bindings"])
        self.assertEqual(result["admission"], "not_admitted")
        self.assertEqual(result["runtime"], "not_implemented")
        self.assertEqual(self.previous, previous)

    def test_changed_semantics_or_baseline_do_not_inherit_review(self):
        for key in ("name", "input", "output", "professional_difference", "approved_source"):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.previous)
                changed[key] = "changed"
                result = preserve_method_bindings(copy.deepcopy(self.current), changed)
                self.assertNotIn("method_source_bindings", result)
                self.assertEqual(result["primary_method_attribution"], "pending")

    def test_missing_previous_is_safe(self):
        result = preserve_method_bindings(self.current, None)
        self.assertNotIn("method_source_bindings", result)
        self.assertEqual(result["primary_method_attribution"], "pending")

    def test_source_review_preserved_for_same_decision(self):
        decision = {"treatment": "native-tool", "target": "cold-index", "reason": "optional"}
        source = {**decision, "primary_review": "partial_metadata_snapshot_review"}
        self.assertEqual(primary_review_state(source, decision), "partial_metadata_snapshot_review")

    def test_changed_source_decision_invalidates_primary_review(self):
        source = {"treatment": "native-tool", "target": "old-target", "reason": "old",
                  "primary_review": "partial_metadata_snapshot_review"}
        decision = {"treatment": "native-tool", "target": "new-target", "reason": "new"}
        self.assertEqual(primary_review_state(source, decision), "pending_before_admission")

    def test_rejected_source_cannot_inherit_admission_claim(self):
        decision = {"treatment": "reject", "target": "none", "reason": "excluded"}
        self.assertEqual(primary_review_state({**decision, "primary_review": "admitted"}, decision),
                         "not_required_for_rejected_runtime")


if __name__ == "__main__":
    unittest.main()
