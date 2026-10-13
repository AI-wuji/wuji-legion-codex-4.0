import json
from pathlib import Path
import tempfile
import unittest

import execution_baseline as baseline


class ExecutionBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=baseline.ROOT / ".dev")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "docs").mkdir()
        self.prior_plan = self.root / "docs/prior.md"
        self.prior_plan.write_text("Historical complete requirement fixture", encoding="utf-8")
        self.plan = self.root / "docs/active.md"
        self.plan.write_text("Approved task-first revision fixture", encoding="utf-8")
        self.prior = self.root / "docs/prior.json"
        counts = {"requirements": 72, "acceptance_scenarios": 95}
        self.prior.write_text(json.dumps({"version": "1.6", "sha256": baseline.digest(self.prior_plan), "preserved_baseline_counts": counts}), encoding="utf-8")
        self.value = {"version": "1.7", "plan": str(self.plan), "sha256": baseline.digest(self.plan),
                      "P7": "separate_approval", "shutdown": False, "preserved_baseline_counts": counts,
                      "prior_baseline": {"version": "1.6", "plan": str(self.prior_plan), "sha256": baseline.digest(self.prior_plan),
                                         "manifest": "docs/prior.json", "manifest_sha256": baseline.digest(self.prior), "retained_read_only": True},
                      "authorized_design_supersessions": {"docs/execution-baseline.json": {
                          "historical_snapshot": "docs/prior.json", "historical_sha256": baseline.digest(self.prior), "reason": "explicit test approval"}}}
        self.save()

    def save(self):
        (self.root / "docs/execution-baseline.json").write_text(json.dumps(self.value), encoding="utf-8")

    def test_approved_revision_preserves_original_and_declares_only_actual_supersession(self):
        self.assertEqual(baseline.load_active(self.root)["version"], "1.7")
        entry = {"path": "docs/execution-baseline.json", "sha256": baseline.digest(self.prior)}
        result = baseline.frozen_observation(self.root, entry, self.value)
        self.assertFalse(result["unchanged"])
        self.assertTrue(result["preserved"])
        self.assertTrue(result["authorized_supersession"])

    def test_changed_active_or_original_hash_is_rejected(self):
        for path in (self.plan, self.prior_plan, self.prior):
            original = path.read_bytes()
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                baseline.load_active(self.root)
            path.write_bytes(original)

    def test_removed_scope_other_frozen_override_and_p7_expansion_are_rejected(self):
        original = json.dumps(self.value)
        for mutation in ("counts", "override", "p7", "shutdown"):
            self.value = json.loads(original)
            if mutation == "counts":
                self.value["preserved_baseline_counts"]["acceptance_scenarios"] = 20
            elif mutation == "override":
                self.value["authorized_design_supersessions"]["docs/architecture.md"] = {}
            elif mutation == "p7":
                self.value["P7"] = "authorized"
            else:
                self.value["shutdown"] = True
            self.save()
            with self.assertRaises(ValueError):
                baseline.load_active(self.root)

    def test_current_production_map_keeps_all_95_and_only_three_p7_scenarios(self):
        mapping = baseline.build_execution_map()
        self.assertEqual(mapping["total"], 95)
        self.assertEqual(mapping["required_for_g6"], 92)
        self.assertFalse(mapping["removed_scenarios"])
        self.assertTrue(all(row["requirement_changed"] is False for row in mapping["rows"]))

    def test_active_budget_semantics_override_frozen_acceptance_wording(self):
        rows = {row["id"]: row for row in baseline.build_execution_map()["rows"]}
        self.assertIn("单项工具/函数返回摘要预算", rows["T70"]["normal_spec"])
        self.assertIn("gpt-6.1-sol官方1050000上下文", rows["T71"]["normal_spec"])
        self.assertIn("272000当gpt-6.1-sol完整上下文", rows["T71"]["negative_spec"])

    def test_duplicate_authority_or_version_keys_are_rejected(self):
        path = self.root / "docs/execution-baseline.json"
        for key, value in (("version", "1.7"), ("P7", "separate_approval")):
            original = json.dumps(self.value)
            path.write_text(original[:-1] + "," + json.dumps(key) + ":" + json.dumps(value) + "}", encoding="utf-8")
            with self.assertRaises(ValueError):
                baseline.load_active(self.root)


if __name__ == "__main__":
    unittest.main()
