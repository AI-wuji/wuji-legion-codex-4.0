"""Only revision/audit integrity checks, not language experiments or runtime gates."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import baseline_rebase as rebase
import preflight


class RevisionTests(unittest.TestCase):
    def test_merge_preserves_implementation_and_verification_status(self):
        old = [{"id": "R01", "baseline_fields": ["old"], "implementation": "pending",
                "verification": "not_run", "adopted": False}]
        fresh = [{"id": "R01", "baseline_fields": ["revised"], "implementation": "new"}]
        merged = rebase.merge_plan_rows(old, fresh)
        self.assertEqual(merged[0]["implementation"], "pending")
        self.assertEqual(merged[0]["verification"], "not_run")
        self.assertFalse(merged[0]["adopted"])
        self.assertEqual(merged[0]["baseline_fields_history"], [["old"]])
        self.assertEqual(old[0]["baseline_fields"], ["old"])

    def test_duplicate_missing_or_extra_ids_rejected(self):
        row = {"id": "R01", "baseline_fields": ["text"]}
        for old, fresh in [([row, row], [row]), ([row], [row, row]),
                           ([row], []), ([row], [{"id": "R02", "baseline_fields": []}])]:
            with self.assertRaises(ValueError):
                rebase.merge_plan_rows(old, fresh)

    def test_repeated_rebase_does_not_duplicate_history(self):
        old = [{"id": "R01", "baseline_fields": ["old"]}]
        fresh = [{"id": "R01", "baseline_fields": ["new"]}]
        first = rebase.merge_plan_rows(old, fresh)
        self.assertEqual(first, rebase.merge_plan_rows(first, fresh))

    def test_active_baseline_rejects_changed_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            docs = root / "docs"
            docs.mkdir()
            plan = docs / "plan.md"
            manifest = docs / "execution-baseline.json"
            content = b"reviewed plan"
            plan.write_bytes(content)
            expected = {"version": "1.6", "plan": "docs/plan.md",
                        "sha256": hashlib.sha256(content).hexdigest()}
            manifest.write_text(json.dumps({**expected, "P7": "separate_approval",
                                           "shutdown": False}), encoding="utf-8")
            with patch.object(preflight, "ROOT", root):
                self.assertEqual(preflight.active_baseline(), expected)
                plan.write_text("unreviewed change", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "differs from approved hash"):
                    preflight.active_baseline()

    def test_active_baseline_rejects_other_version_or_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"
            docs = root / "docs"
            docs.mkdir(parents=True)
            plan = docs / "plan.md"
            manifest = docs / "execution-baseline.json"
            outside_plan = Path(folder) / "outside.md"
            content = b"reviewed plan"
            plan.write_bytes(content)
            outside_plan.write_bytes(content)
            with patch.object(preflight, "ROOT", root):
                for version, location, error in [
                        ("1.5", "docs/plan.md", "Unsupported or unauthorized execution baseline"),
                        ("1.6", str(outside_plan), "current project file"),
                        ("1.6", "../outside.md", "current project file"),
                        ("1.6", "docs/missing.md", "current project file")]:
                    with self.subTest(version=version, plan=location):
                        manifest.write_text(json.dumps({"version": version, "plan": location,
                                                       "sha256": hashlib.sha256(content).hexdigest(),
                                                       "P7": "separate_approval", "shutdown": False}), encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, error):
                            preflight.active_baseline()


if __name__ == "__main__":
    unittest.main()
