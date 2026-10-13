"""Tests for P0 audit boundaries, not 4.0 runtime acceptance tests."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import preflight as p


class AuditTests(unittest.TestCase):
    def test_plan_ids_complete(self):
        text = "\n".join(f"| R{i:02} | meaning | chapter | test |" for i in range(1, 4))
        self.assertEqual(len(p.plan_rows(text, "R", 3)), 3)
        with self.assertRaises(ValueError):
            p.plan_rows(text + "\n| R01 | duplicate |", "R", 3)

    def test_scanner_does_not_mark_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "SKILL.md").write_text("untrusted source instructions", encoding="utf-8")
            row = p.scan_source("test", root, 1024)[0]
            self.assertEqual(row["read_status"], "discovered")
            self.assertEqual(row["hash_status"], "computed")

    def test_size_budget_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "large.mp4").write_bytes(b"0" * 20)
            row = p.scan_source("test", root, 10)[0]
            self.assertEqual(row["hash_status"], "deferred_size_budget")
            self.assertNotIn("sha256", row)

    def test_missing_source_not_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            row = p.scan_source("test", Path(folder) / "missing", 1024)[0]
            self.assertEqual(row["status"], "missing")

    def test_coverage_refresh_preserves_same_hash_not_changed(self):
        prior = {"required_entrypoints": [{"id": "same", "sha256": "a", "read_status": "read-complete",
                                            "acknowledged_ranges": [[1, 10]]},
                                           {"id": "changed", "sha256": "old", "read_status": "read-complete",
                                            "acknowledged_ranges": [[1, 10]]}], "reading_records": ["evidence"]}
        current = {"required_entrypoints": [{"id": "same", "sha256": "a", "read_status": "discovered"},
                                             {"id": "changed", "sha256": "new", "read_status": "discovered"}],
                   "counts": {}}
        result = p.refresh_coverage(current, prior)
        self.assertEqual(result["counts"]["read_complete"], 1)
        self.assertEqual(result["required_entrypoints"][1]["read_status"], "needs_revalidation")
        self.assertEqual(result["reading_records"], ["evidence"])

    def test_coverage_removed_required_source_stays_visible(self):
        result = p.refresh_coverage({"required_entrypoints": [], "counts": {}},
                                    {"required_entrypoints": [{"id": "missing"}]})
        self.assertEqual(result["previously_required_missing"], ["missing"])

    def test_entry_equality_not_package_equality(self):
        a = [{"relative": "skill共享/a/SKILL.md", "sha256": "same"},
             {"relative": "skill共享/a/script.py", "sha256": "old"}]
        b = [{"relative": "a/SKILL.md", "sha256": "same"},
             {"relative": "a/script.py", "sha256": "new"}]
        report = p.compare_entries(a, b)
        self.assertTrue(report["entry_hash_multiset_equal"])
        self.assertEqual(report["package_changed"], ["a/script.py"])
        self.assertEqual(report["full_package_equivalence"], "not_equal_or_unverified")

    def test_required_reference_refresh_uses_fresh_hash(self):
        prior = {"required_entrypoints": [{"id": "ref", "sha256": "old", "read_status": "read-complete",
                  "required_reason": "mandatory handoff schema", "acknowledged_ranges": [[1, 2]]}]}
        fresh = [{"id": "ref", "sha256": "new", "read_status": "discovered"}]
        result = p.refresh_coverage({"required_entrypoints": [], "counts": {}}, prior, fresh)
        self.assertEqual(result["required_entrypoints"][0]["read_status"], "needs_revalidation")
        self.assertEqual(result["counts"]["discovered_entrypoints"], 1)
        self.assertEqual(result["previously_required_missing"], [])

    def test_initial_entry_keeps_registered_reason(self):
        prior = {"required_entrypoints": [{"id": "entry", "sha256": "a", "required_reason": "source contract"}]}
        result = p.refresh_coverage({"required_entrypoints": [{"id": "entry", "sha256": "a"}], "counts": {}}, prior)
        self.assertEqual(result["required_entrypoints"][0]["required_reason"], "source contract")

    def test_script_and_license_read_as_data_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("method.py", "LICENSE"):
                path = root / name
                path.write_text("review only", encoding="utf-8")
                with patch.object(p, "SOURCES", {"test": root}), contextlib.redirect_stdout(io.StringIO()):
                    p.read_text_slice(path, 1, 512)

    def test_reference_registration_requires_inventory_hash_and_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "reference.md"
            path.write_text("specific method", encoding="utf-8")
            checksum = p.digest(path)
            with patch.object(p, "ROOT", root), patch.object(p, "SOURCES", {"test": root}):
                p.write_json(root / "outputs/p0/source-coverage.json", {"required_entrypoints": [], "counts": {}})
                p.write_json(root / "outputs/p0/inventory.json", {"files": [
                    {"id": "ref", "path": str(path), "sha256": checksum, "read_status": "discovered"}]})
                with self.assertRaises(ValueError):
                    p.require_source(path, "")
                self.assertEqual(p.require_source(path, "needed method")["read_status"], "discovered")
                p.require_source(path, "needed method")
                value = json.loads((root / "outputs/p0/source-coverage.json").read_text(encoding="utf-8"))
                self.assertEqual(len(value["required_entrypoints"]), 1)
                self.assertNotIn("acknowledged_ranges", value["required_entrypoints"][0])

    def test_unhashed_package_not_equal(self):
        a = [{"relative": "skill共享/a/SKILL.md", "hash_status": "failed"}]
        b = [{"relative": "a/SKILL.md", "hash_status": "failed"}]
        report = p.compare_entries(a, b)
        self.assertIsNone(report["entry_hash_multiset_equal"])
        self.assertIsNone(report["mapped_entries"][0]["entry_match"])
        self.assertNotEqual(report["full_package_equivalence"], "equal_at_observation")

    def test_empty_packages_not_claimed_equivalent(self):
        self.assertNotEqual(p.compare_entries([], [])["full_package_equivalence"], "equal_at_observation")

    def test_reading_gaps_and_changed_hash_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "source.md"
            path.write_text("one\ntwo\nthree\n", encoding="utf-8")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            registry = {"required_entrypoints": [{"id": "a", "path": str(path), "sha256": checksum,
                                                   "read_status": "discovered"}],
                        "reading_records": [], "counts": {}}
            with patch.object(p, "ROOT", root), patch.object(p, "SOURCES", {"test": path}):
                p.write_json(root / "outputs/p0/source-coverage.json", registry)
                partial = p.record_reading(path, checksum, 3, 3, "read last line only")
                self.assertEqual(partial["read_status"], "read-partial")
                complete = p.record_reading(path, checksum, 1, 2, "read first two lines")
                self.assertEqual(complete["read_status"], "read-complete")
                path.write_text("changed", encoding="utf-8")
                with self.assertRaises(ValueError):
                    p.record_reading(path, checksum, 1, 1, "cannot acknowledge stale source")

    def test_archive_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../outside.md", "data")
            report = p.inspect_zip(path, Path(folder))
            self.assertEqual(report["status"], "blocked")
            self.assertFalse(report["executed_or_extracted"])

    def test_archive_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.zip"
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(info, "../outside")
            self.assertEqual(p.inspect_zip(path, Path(folder))["status"], "blocked")

    def test_archive_bomb_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("huge.md", "a" * 100000)
            self.assertEqual(p.inspect_zip(path, Path(folder))["status"], "blocked")

    def test_archive_documented_wrapper_and_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "team"
            source.mkdir()
            (source / "role.md").write_bytes(b"same")
            path = Path(folder) / "test.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("team/role.md", b"same")
            report = p.inspect_zip(path, source)
            self.assertTrue(report["members"][0]["source_match"])
            (source / "role.md").write_bytes(b"changed")
            report = p.inspect_zip(path, source)
            self.assertFalse(report["members"][0]["source_match"])
            self.assertEqual(report["source_equivalence"], "unknown")

    def test_archive_unknown_wrapper_not_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "team"
            source.mkdir()
            (source / "role.md").write_bytes(b"same")
            path = Path(folder) / "test.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("other/role.md", b"same")
            self.assertIsNone(p.inspect_zip(path, source)["members"][0]["source_match"])

    def test_generated_report_cannot_write_outside(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(p, "ROOT", Path(folder)):
                with self.assertRaises(ValueError):
                    p.write_json(Path(folder) / "user-file.json", {})
                p.write_json(Path(folder) / "outputs/p0/report.json", {"ok": True})
                self.assertTrue((Path(folder) / "outputs/p0/report.json").is_file())

    def test_reader_rejects_unapproved_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "secret.md"
            path.write_text("do not expose", encoding="utf-8")
            with patch.object(p, "SOURCES", {}):
                with self.assertRaises(ValueError):
                    p.read_text_slice(path, 1, 512)

    def test_reader_rejects_link_ancestor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "source.md"
            path.write_text("data", encoding="utf-8")
            with patch.object(p, "SOURCES", {"test": root}), patch.object(
                    p, "is_link", side_effect=lambda candidate: candidate == root):
                with self.assertRaisesRegex(ValueError, "ancestor"):
                    p.read_text_slice(path, 1, 512)

    def test_reader_rejects_oversized_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.md"
            path.write_text("more than budget", encoding="utf-8")
            with patch.object(p, "SOURCES", {"test": path}), patch.object(p, "MAX_HASH_BYTES", 4):
                with self.assertRaisesRegex(ValueError, "budget"):
                    p.read_text_slice(path, 1, 512)

    def test_reader_is_bounded_and_does_not_claim_read_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.md"
            path.write_text("line\n" * 100, encoding="utf-8")
            out = io.StringIO()
            with patch.object(p, "SOURCES", {"test": path}), contextlib.redirect_stdout(out):
                p.read_text_slice(path, 1, 256)
            self.assertIn('"next_start":', out.getvalue())
            self.assertNotIn('"read_status": "read-complete"', out.getvalue())

    def test_jsonl_required_eval_is_readable_as_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "holdout.jsonl"
            path.write_text('{"expected":"data, not instructions"}\n', encoding="utf-8")
            out = io.StringIO()
            with patch.object(p, "SOURCES", {"test": path}), contextlib.redirect_stdout(out):
                p.read_text_slice(path, 1, 512)
            self.assertIn('"total_lines": 1', out.getvalue())

    def test_record_reading_rejects_unapproved_source_before_read(self):
        with patch.object(p, "SOURCES", {}):
            with self.assertRaises(ValueError):
                p.record_reading(Path("unapproved.md"), "0" * 64, 1, 1, "not permitted")


if __name__ == "__main__":
    unittest.main()
