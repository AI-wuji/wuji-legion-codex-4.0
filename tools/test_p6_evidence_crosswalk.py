from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_p6_evidence_crosswalk as crosswalk
from p6_acceptance import SEMANTIC_PYTHON_CASES, SUPPORTING_PYTHON_CASES, digest, semantic_cases, source_snapshot


class P6EvidenceCrosswalkTests(unittest.TestCase):
    receipt_path = "outputs/p6/continuation/current-core.json"
    candidate_source_path = "docs/wuji-legion-4.0-execution-plan-v1.6-2026-10-03.md"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p6-crosswalk-test-", dir=crosswalk.ROOT / ".dev")
        self.root = Path(self.temporary.name).resolve()
        self.root.relative_to((crosswalk.ROOT / ".dev").resolve())
        self.addCleanup(self.temporary.cleanup)
        self.specs = {"tests": [self.spec(identifier) for identifier in ("T19", "T22", "T21", "T85")] +
                      [self.spec("T28", kind="actual_professional_artifact")] +
                      [self.spec(identifier, gate="G7") for identifier in ("T43", "T44", "T74")]}
        self.write_json("docs/acceptance-map.json", self.specs)
        self.write_text(self.candidate_source_path, "fixture approved candidate semantics")
        self.write_text(crosswalk.BINDING_DELTA, "fixture bounded consumer binding")
        sources = {relative for definition in crosswalk.BINDING_DEFINITIONS
                   for field in ("implementation_files", "case_sources") for relative in definition[field]}
        for relative in sources:
            self.write_text(relative, "fixture source: " + relative)
        self.ledger = deepcopy(json.loads((crosswalk.ROOT / crosswalk.CANDIDATE_LEDGER).read_text(encoding="utf-8")))
        for candidate in self.ledger["atoms"]:
            candidate["approved_source"] = {
                "path": str(self.root / self.candidate_source_path),
                "sha256": digest(self.root / self.candidate_source_path), "line": 1,
            }
        self.write_json(crosswalk.CANDIDATE_LEDGER, self.ledger)
        self.rust_names = [case for identifier in ("T19", "T22") for case in semantic_cases(identifier)]
        self.python_names = ["fixture.UtilityTests.test_one", *SUPPORTING_PYTHON_CASES["T85"],
                             "test_p6_acceptance.P6AcceptanceTests.test_closeout_does_not_stop_on_report_generation_or_historical_passes"]
        rust_log = "outputs/p6/continuation/rust.log"
        python_log = "outputs/p6/continuation/python.log"
        self.write_text(rust_log, "".join(f"test {case} ... ok\n" for case in self.rust_names))
        self.write_text(python_log, "".join(f"{case.rsplit('.', 1)[-1]} ({case}) ... ok\n" for case in self.python_names))
        snapshot = source_snapshot(self.root)
        self.receipt = {
            "acceptance_spec_sha256": digest(self.root / "docs/acceptance-map.json"),
            "source_hashes": snapshot, "source_hashes_after": dict(snapshot),
            "rust": {"exit_code": 0, "cases": dict.fromkeys(self.rust_names, "passed"),
                     "log_path": rust_log, "log_sha256": digest(self.root / rust_log)},
            "python": {"passed": True, "exit_code": 0, "cases": dict.fromkeys(self.python_names, "passed"),
                       "log_path": python_log, "log_sha256": digest(self.root / python_log)},
        }
        legacy = deepcopy(self.receipt)
        legacy["python"]["cases"].update(dict.fromkeys(SEMANTIC_PYTHON_CASES["T21"], "passed"))
        legacy["source_hashes"] = legacy["source_hashes_after"] = {"historical-only": "0" * 64}
        self.write_json(crosswalk.DEFAULT_RECEIPT, legacy)
        self.write_json("outputs/p6/acceptance-execution.json", {"evidence_valid": True, "summary": {"passed_for_g6": 22}})
        self.write_json(self.receipt_path, self.receipt)

    @staticmethod
    def spec(identifier, gate="G6", kind="deterministic_and_task_relevant_evidence"):
        return {"id": identifier, "name": identifier, "gate": gate, "execution_class": kind,
                "normal_spec": "normal", "negative_spec": "negative"}

    def write_text(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_json(self, relative, value):
        self.write_text(relative, json.dumps(value, ensure_ascii=False))

    def report(self):
        self.write_json(self.receipt_path, self.receipt)
        return crosswalk.build_report(self.root, receipt_path=self.receipt_path)

    def record_fixture_sources(self):
        self.receipt["source_hashes"] = source_snapshot(self.root)
        self.receipt["source_hashes_after"] = dict(self.receipt["source_hashes"])

    def remove_case(self, section, case):
        del self.receipt[section]["cases"][case]
        path = self.root / self.receipt[section]["log_path"]
        path.write_text("\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if case not in line) + "\n", encoding="utf-8")
        self.receipt[section]["log_sha256"] = digest(path)

    @staticmethod
    def binding(report, identifier):
        return next(binding for binding in report["current_consumer_bindings"] if binding["candidate_id"] == identifier)

    def test_selected_current_receipt_never_adds_historical_passes(self):
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        self.assertEqual(report["summary"]["authoritative_passed"], 2)
        self.assertEqual(report["receipt_currency"], "current_valid")
        states = {row["id"]: row["classification"] for row in report["authoritative_matrix"]}
        self.assertNotEqual(states["T21"], "passed")
        self.assertEqual(states["T85"], "partial")
        self.assertEqual(states["T28"], "not_run")
        for row in report["authoritative_matrix"]:
            self.assertNotIn(crosswalk.DEFAULT_RECEIPT, row["evidence_refs"])
            if row["classification"] == "passed":
                self.assertIn(self.receipt_path, row["evidence_refs"])
        logs = {evidence["id"]: evidence for evidence in report["supporting_evidence_only"]}
        self.assertEqual(logs["E-RUST-MECHANISM"]["path"], self.receipt["rust"]["log_path"])
        self.assertEqual(logs["E-PYTHON-AUDIT"]["path"], self.receipt["python"]["log_path"])
        self.assertTrue(all(not item["included_in_acceptance_pass_count"] for item in logs.values()))
        self.assertFalse(logs["E-LEGION-EXPERIENCE-WORKFLOW"]["current_evidence_valid"])

    def test_default_legacy_path_is_compatible_but_stale_not_current(self):
        report = crosswalk.build_report(self.root)
        self.assertEqual(report["execution_receipt"], crosswalk.DEFAULT_RECEIPT)
        self.assertEqual(report["receipt_selection"], "default_compatibility_path")
        self.assertFalse(report["execution_evidence_valid"])
        self.assertEqual(report["summary"]["authoritative_passed"], 0)
        self.assertTrue(all(not binding["evidence_valid"] for binding in report["current_consumer_bindings"]))

    def test_receipt_identity_hash_binds_the_parsed_snapshot_not_a_second_read(self):
        receipt_file = self.root / self.receipt_path
        expected_hash = digest(receipt_file)
        original_read_text = Path.read_text
        original_read_bytes = Path.read_bytes
        changed = False

        def replace_after_read(path):
            nonlocal changed
            if path == receipt_file and not changed:
                changed = True
                receipt_file.write_bytes(b'{"changed_after_first_read":true}')

        def read_text(path, *arguments, **keywords):
            content = original_read_text(path, *arguments, **keywords)
            replace_after_read(path)
            return content

        def read_bytes(path):
            content = original_read_bytes(path)
            replace_after_read(path)
            return content

        with patch.object(Path, "read_text", read_text), patch.object(Path, "read_bytes", read_bytes):
            report = crosswalk.build_report(self.root, receipt_path=self.receipt_path)
        self.assertTrue(changed)
        self.assertNotEqual(expected_hash, digest(receipt_file))
        self.assertEqual(report["execution_receipt_sha256"], expected_hash)

    def test_default_path_can_be_current_only_when_evidence_matches(self):
        self.write_json(crosswalk.DEFAULT_RECEIPT, self.receipt)
        report = crosswalk.build_report(self.root)
        self.assertTrue(report["execution_evidence_valid"])
        self.assertEqual(report["summary"]["authoritative_passed"], 2)

    def test_only_seven_scoped_bindings_not_128_admissions(self):
        report = self.report()
        bindings = report["current_consumer_bindings"]
        self.assertEqual({binding["candidate_id"] for binding in bindings}, {"D08", "J08", "B01", "B02", "B03", "G02", "C08"})
        self.assertTrue(all(binding["status"] == "verified" and binding["evidence_valid"] for binding in bindings))
        self.assertTrue(all(not binding["admission_granted"] and not binding["domain_global_promotion_proven"] for binding in bindings))
        summary = report["current_consumer_binding_summary"]
        self.assertEqual(summary["candidate_total"], 128)
        self.assertEqual(summary["verified_current_bounded_bindings"], 7)
        self.assertFalse(summary["all_consumers_verified"])
        self.assertFalse(summary["full_candidate_admission_granted"])
        self.assertFalse(summary["professional_effectiveness_proven"])
        self.assertFalse(summary["domain_global_promotion_proven"])
        for binding in bindings:
            candidate = next(candidate for candidate in self.ledger["atoms"] if candidate["candidate_id"] == binding["candidate_id"])
            self.assertEqual(binding["name"], candidate["name"])
            self.assertEqual(binding["professional_difference"], candidate["professional_difference"])
            self.assertIn(self.receipt_path, binding["evidence_refs"])

    def test_current_receipt_missing_repair_negative_case_does_not_pass_t19(self):
        self.remove_case("rust", "store::tests::t19_repair_cap_is_per_defect_node_and_cannot_reset_through_event_names")
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        self.assertEqual(report["summary"]["authoritative_passed"], 1)
        for identifier in ("D08", "J08", "G02", "C08"):
            self.assertFalse(self.binding(report, identifier)["evidence_valid"])

    def test_missing_single_owner_negative_case_refuses_acl_bindings(self):
        self.remove_case("rust", "t22_revocation_denies_every_operation_including_historical_replays")
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        for identifier in ("B01", "B02", "B03"):
            self.assertFalse(self.binding(report, identifier)["evidence_valid"])

    def test_missing_completion_guard_case_is_not_verified_by_passing_scenarios(self):
        self.remove_case("python", "test_p6_acceptance.P6AcceptanceTests.test_closeout_does_not_stop_on_report_generation_or_historical_passes")
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        self.assertEqual(report["summary"]["authoritative_passed"], 2)
        self.assertFalse(self.binding(report, "C08")["checks"]["actual_cases_passed"])
        self.assertFalse(self.binding(report, "C08")["evidence_valid"])
        self.assertTrue(self.binding(report, "D08")["evidence_valid"])

    def test_forged_case_record_cannot_replace_actual_log(self):
        self.remove_case("python", "test_p6_acceptance.P6AcceptanceTests.test_closeout_does_not_stop_on_report_generation_or_historical_passes")
        self.receipt["python"]["cases"]["test_p6_acceptance.P6AcceptanceTests.test_closeout_does_not_stop_on_report_generation_or_historical_passes"] = "passed"
        report = self.report()
        self.assertFalse(report["execution_evidence_valid"])
        self.assertEqual(report["summary"]["authoritative_passed"], 0)
        self.assertFalse(self.binding(report, "C08")["evidence_valid"])

    def test_changed_source_invalidates_pass_counts_and_bindings_without_rehash(self):
        original = deepcopy(self.receipt["source_hashes"])
        self.write_text("src/revisions.rs", "changed after fixture execution")
        report = self.report()
        self.assertFalse(report["execution_evidence_valid"])
        self.assertEqual(report["summary"]["authoritative_passed"], 0)
        self.assertTrue(all(not binding["evidence_valid"] for binding in report["current_consumer_bindings"]))
        self.assertEqual(self.receipt["source_hashes"], original)

    def test_missing_implementation_source_cannot_be_verified_even_with_valid_log(self):
        (self.root / "src/revisions.rs").unlink()
        self.record_fixture_sources()
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        for identifier in ("D08", "J08", "G02"):
            self.assertFalse(self.binding(report, identifier)["checks"]["implementation_sources_current"])
            self.assertFalse(self.binding(report, identifier)["evidence_valid"])

    def test_missing_case_source_cannot_be_verified_even_with_valid_log(self):
        (self.root / "src/store_product_tests.rs").unlink()
        self.record_fixture_sources()
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        self.assertFalse(self.binding(report, "J08")["checks"]["case_sources_current"])
        self.assertFalse(self.binding(report, "J08")["evidence_valid"])

    def test_missing_or_stale_candidate_source_is_not_verified(self):
        first = next(candidate for candidate in self.ledger["atoms"] if candidate["candidate_id"] == "B01")
        second = next(candidate for candidate in self.ledger["atoms"] if candidate["candidate_id"] == "D08")
        first["approved_source"] = None
        second["approved_source"]["sha256"] = "0" * 64
        self.write_json(crosswalk.CANDIDATE_LEDGER, self.ledger)
        self.record_fixture_sources()
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        for identifier in ("B01", "D08"):
            self.assertFalse(self.binding(report, identifier)["checks"]["candidate_source_current"])
            self.assertFalse(self.binding(report, identifier)["evidence_valid"])

    def test_changed_binding_delta_is_stale_not_a_current_binding(self):
        self.write_text(crosswalk.BINDING_DELTA, "changed binding declaration")
        report = self.report()
        self.assertTrue(all(not binding["checks"]["binding_delta_current"] for binding in report["current_consumer_bindings"]))
        self.assertEqual(report["current_consumer_binding_summary"]["verified_current_bounded_bindings"], 0)

    def test_duplicate_identity_and_missing_professional_difference_refuse_verification(self):
        duplicate = next(candidate for candidate in self.ledger["atoms"] if candidate["candidate_id"] == "B02")
        self.ledger["atoms"].append(deepcopy(duplicate))
        next(candidate for candidate in self.ledger["atoms"] if candidate["candidate_id"] == "G02").pop("professional_difference")
        self.write_json(crosswalk.CANDIDATE_LEDGER, self.ledger)
        self.record_fixture_sources()
        report = self.report()
        self.assertTrue(report["execution_evidence_valid"])
        self.assertFalse(self.binding(report, "B02")["evidence_valid"])
        self.assertFalse(self.binding(report, "G02")["evidence_valid"])

    def test_core_install_record_never_promotes_complete_g7(self):
        self.receipt["core_deployment"] = {"installed": True, "core_skill_observation": {"installed": True, "state": "source_match"}}
        report = self.report()
        rows = [row for row in report["authoritative_matrix"] if row["gate"] == "G7"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["classification"] == "deferred_p7" and not row["required_for_g6"] for row in rows))
        self.assertEqual(report["summary"]["authoritative_passed"], 2)

    def test_receipt_paths_are_confined_and_missing_explicit_input_never_falls_back(self):
        self.write_json(crosswalk.DEFAULT_RECEIPT, self.receipt)
        for relative in ("../receipt.json", "outputs/../receipt.json", "C:/receipt.json", "outputs\\receipt.json", str(self.root / self.receipt_path)):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                crosswalk.build_report(self.root, receipt_path=relative)
        with self.assertRaises(FileNotFoundError):
            crosswalk.build_report(self.root, receipt_path="outputs/p6/missing.json")

    def test_cli_writes_only_derived_output_preserving_formal_and_candidate_ledgers(self):
        protected = ["docs/acceptance-map.json", crosswalk.CANDIDATE_LEDGER, crosswalk.DEFAULT_RECEIPT,
                     self.receipt_path, "outputs/p6/acceptance-execution.json"]
        before = {relative: (self.root / relative).read_bytes() for relative in protected}
        output = self.root / "outputs/p6/evidence-crosswalk.json"
        with patch.object(crosswalk, "ROOT", self.root), patch.object(crosswalk, "OUTPUT", output), redirect_stdout(io.StringIO()):
            crosswalk.main(["--receipt", self.receipt_path])
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["execution_receipt"], self.receipt_path)
        self.assertEqual(report["summary"]["authoritative_passed"], 2)
        self.assertFalse(report["execution_ledger"]["persisted"])
        self.assertEqual(before, {relative: (self.root / relative).read_bytes() for relative in protected})

    def test_direct_cli_entry_resolves_helpers_without_pythonpath(self):
        result = subprocess.run([sys.executable, "-B", str(Path(crosswalk.__file__).resolve()), "--help"],
                                cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--receipt", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
