from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from p6_acceptance import ROOT, SEMANTIC_CASES, SEMANTIC_PYTHON_CASES, SUPPORTING_CASES, SUPPORTING_PYTHON_CASES, digest, evaluate, semantic_cases, source_snapshot
from refresh_continuation_report import core_closeout_state, current_core_projection


class P6AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p6-ledger-test-", dir=ROOT / ".dev")
        self.root = Path(self.temporary.name).resolve()
        self.root.relative_to((ROOT / ".dev").resolve())
        self.addCleanup(self.temporary.cleanup)
        (self.root / "docs").mkdir()
        (self.root / "outputs/p6").mkdir(parents=True)
        self.specs = {"tests": [self.spec(identifier) for identifier in (*SEMANTIC_CASES, *SEMANTIC_PYTHON_CASES)] +
                      [self.spec("T08"), self.spec("T95", kind="actual_professional_artifact"),
                       self.spec("T43", gate="G7"), self.spec("T44", gate="G7"), self.spec("T74", gate="G7")]}
        (self.root / "docs/acceptance-map.json").write_text(json.dumps(self.specs), encoding="utf-8")
        names = list(dict.fromkeys([name for identifier in SEMANTIC_CASES for name in semantic_cases(identifier)] + SUPPORTING_CASES["T08"]))
        rust = self.root / "outputs/p6/rust.log"
        rust.write_text("\n".join(f"test {name} ... ok" for name in names) + "\n", encoding="utf-8")
        python = self.root / "outputs/p6/python.log"
        python_names = list(dict.fromkeys(["unit_test.Fake.test_one", *[name for cases in SEMANTIC_PYTHON_CASES.values() for name in cases]]))
        python.write_text("\n".join(f"{name.rsplit('.', 1)[-1]} ({name}) ... ok" for name in python_names) + "\n", encoding="utf-8")
        snapshot = source_snapshot(self.root)
        self.receipt = {
            "acceptance_spec_sha256": digest(self.root / "docs/acceptance-map.json"),
            "source_hashes": snapshot, "source_hashes_after": dict(snapshot),
            "rust": {"exit_code": 0, "cases": dict.fromkeys(names, "passed"),
                     "log_path": "outputs/p6/rust.log", "log_sha256": digest(rust)},
            "python": {"passed": True, "exit_code": 0, "cases": dict.fromkeys(python_names, "passed"),
                       "log_path": "outputs/p6/python.log", "log_sha256": digest(python)},
        }

    @staticmethod
    def spec(identifier, gate="G6", kind="deterministic_and_task_relevant_evidence"):
        return {"id": identifier, "name": identifier, "gate": gate, "execution_class": kind,
                "normal_spec": "normal", "negative_spec": "negative"}

    def report(self):
        return evaluate(self.root, self.specs, self.receipt)

    def test_supplementary_receipt_references_the_execution_that_was_evaluated(self):
        relative = "outputs/p6/current-core.json"
        report = evaluate(self.root, self.specs, self.receipt, receipt_path=relative)
        self.assertTrue(report["evidence_valid"])
        self.assertEqual(report["execution_receipt"], relative)
        for identifier in ("T19", "T22"):
            row = next(row for row in report["matrix"] if row["id"] == identifier)
            self.assertIn(relative, row["evidence_refs"])
            self.assertNotIn("outputs/p6/test-execution.json", row["evidence_refs"])

    def test_python_evidence_references_resolve_without_importing_software_tests(self):
        for mapping in (SEMANTIC_PYTHON_CASES, SUPPORTING_PYTHON_CASES):
            for identifier, cases in mapping.items():
                for case in cases:
                    with self.subTest(identifier=identifier, case=case):
                        module, class_name, method = case.rsplit(".", 2)
                        path = ROOT / "tools" / f"{module}.py"
                        tree = ast.parse(path.read_text(encoding="utf-8"))
                        self.assertTrue(any(
                            isinstance(node, ast.ClassDef) and node.name == class_name
                            and any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method
                                    for child in node.body)
                            for node in tree.body
                        ))

    def test_t10_maps_to_complete_actual_normal_and_negative_cases(self):
        self.assertEqual(
            SEMANTIC_CASES.get("T10"),
            "store::tests::t10_actual_windows_links_case_aliases_and_retargeted_paths_fail_closed",
        )
        self.assertEqual(semantic_cases("T10"), [
            "store::tests::t10_actual_windows_links_case_aliases_and_retargeted_paths_fail_closed",
            "store::tests::parent_path_and_unassigned_output_rejected",
            "store::tests::conflicting_writes_have_no_second_attempt",
        ])
        self.assertNotIn("T10", SUPPORTING_CASES)
        report = self.report()
        row = next(row for row in report["matrix"] if row["id"] == "T10")
        self.assertEqual(row["status"], "passed")
        self.assertIn("Windows", row["coverage"])
        self.assertIn("src/store_product_tests.rs", row["evidence_refs"])

    def test_t20_maps_to_complete_actual_normal_and_negative_cases(self):
        self.assertEqual(
            SEMANTIC_PYTHON_CASES.get("T20"),
            ["test_evidence_budget_cli.EvidenceBudgetCliTests.test_t70_actual_large_json_copy_and_paged_readback_preserve_errors_and_not_fee_limits"],
        )
        self.assertNotIn("T20", SUPPORTING_CASES)
        report = self.report()
        row = next(row for row in report["matrix"] if row["id"] == "T20")
        self.assertEqual(row["status"], "passed")
        self.assertIn("Complete normal and negative", row["coverage"])
        self.assertIn("tools/test_evidence_budget_cli.py", row["evidence_refs"])

    def test_t10_and_t20_missing_actual_records_fail_closed(self):
        cases = [("T10", "rust", case) for case in semantic_cases("T10")] + [
            ("T20", "python", case) for case in SEMANTIC_PYTHON_CASES["T20"]
        ]
        for identifier, section, case in cases:
            with self.subTest(identifier=identifier):
                receipt = json.loads(json.dumps(self.receipt))
                del receipt[section]["cases"][case]
                log_path = self.root / receipt[section]["log_path"]
                original = log_path.read_text(encoding="utf-8")
                log_path.write_text(
                    "\n".join(line for line in original.splitlines() if case not in line) + "\n",
                    encoding="utf-8",
                )
                receipt[section]["log_sha256"] = digest(log_path)
                report = evaluate(self.root, self.specs, receipt)
                self.assertTrue(report["evidence_valid"])
                row = next(row for row in report["matrix"] if row["id"] == identifier)
                self.assertEqual(row["status"], "failed_or_stale")
                log_path.write_text(original, encoding="utf-8")

    def test_t20_composer_support_does_not_replace_actual_readback(self):
        actual = SEMANTIC_PYTHON_CASES["T20"][0]
        del self.receipt["python"]["cases"][actual]
        python_log = self.root / self.receipt["python"]["log_path"]
        python_log.write_text(
            "\n".join(line for line in python_log.read_text(encoding="utf-8").splitlines() if actual not in line) + "\n",
            encoding="utf-8",
        )
        self.receipt["python"]["log_sha256"] = digest(python_log)
        component = "composer::tests::conflicts_and_required_weakening_fail_independently"
        self.receipt["rust"]["cases"][component] = "passed"
        rust_log = self.root / self.receipt["rust"]["log_path"]
        rust_log.write_text(rust_log.read_text(encoding="utf-8") + f"test {component} ... ok\n", encoding="utf-8")
        self.receipt["rust"]["log_sha256"] = digest(rust_log)
        report = self.report()
        self.assertTrue(report["evidence_valid"])
        row = next(row for row in report["matrix"] if row["id"] == "T20")
        self.assertEqual(row["status"], "failed_or_stale")
        self.assertEqual(row["test_cases"], [actual])

    def test_t10_and_t20_failed_actual_cases_override_success_flags(self):
        cases = [("T10", "rust", case) for case in semantic_cases("T10")] + [
            ("T20", "python", case) for case in SEMANTIC_PYTHON_CASES["T20"]
        ]
        for identifier, section, case in cases:
            with self.subTest(identifier=identifier, case=case):
                receipt = json.loads(json.dumps(self.receipt))
                receipt[section]["cases"][case] = "failed"
                log_path = self.root / receipt[section]["log_path"]
                original = log_path.read_text(encoding="utf-8")
                if section == "rust":
                    passing = f"test {case} ... ok"
                    failed = f"test {case} ... FAILED"
                else:
                    passing = f"{case.rsplit('.', 1)[-1]} ({case}) ... ok"
                    failed = f"{case.rsplit('.', 1)[-1]} ({case}) ... FAIL"
                log_path.write_text(original.replace(passing, failed), encoding="utf-8")
                receipt[section]["log_sha256"] = digest(log_path)
                report = evaluate(self.root, self.specs, receipt)
                self.assertTrue(report["evidence_valid"])
                row = next(row for row in report["matrix"] if row["id"] == identifier)
                self.assertEqual(row["status"], "failed_or_stale")
                log_path.write_text(original, encoding="utf-8")

    def test_t10_and_t20_reject_stale_sources_and_changed_or_missing_logs(self):
        for change in ("sources", "rust", "python"):
            with self.subTest(change=change):
                receipt = json.loads(json.dumps(self.receipt))
                if change == "sources":
                    receipt["source_hashes"]["stale.rs"] = "0" * 64
                    receipt["source_hashes_after"] = dict(receipt["source_hashes"])
                    report = evaluate(self.root, self.specs, receipt)
                else:
                    log_path = self.root / receipt[change]["log_path"]
                    original = log_path.read_bytes()
                    log_path.write_bytes(b"changed execution evidence")
                    report = evaluate(self.root, self.specs, receipt)
                    log_path.write_bytes(original)
                self.assertFalse(report["evidence_valid"])
                for identifier in ("T10", "T20"):
                    row = next(row for row in report["matrix"] if row["id"] == identifier)
                    self.assertEqual(row["status"], "failed_or_stale")
        for section in ("rust", "python"):
            with self.subTest(missing=section):
                receipt = json.loads(json.dumps(self.receipt))
                receipt[section]["log_path"] = f"outputs/p6/missing-{section}.log"
                report = evaluate(self.root, self.specs, receipt)
                self.assertFalse(report["evidence_valid"])
                for identifier in ("T10", "T20"):
                    row = next(row for row in report["matrix"] if row["id"] == identifier)
                    self.assertEqual(row["status"], "failed_or_stale")

    def test_execution_receipt_reference_cannot_escape_the_project(self):
        for relative in ("../private.json", "C:/private.json", "/private.json", "outputs\\private.json"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                evaluate(self.root, self.specs, self.receipt, receipt_path=relative)

    def test_current_receipt_reference_does_not_promote_stale_sources(self):
        (self.root / "Cargo.toml").write_text("changed", encoding="utf-8")
        report = evaluate(self.root, self.specs, self.receipt, receipt_path="outputs/p6/current-core.json")
        self.assertFalse(report["evidence_valid"])
        self.assertEqual(next(row for row in report["matrix"] if row["id"] == "T19")["status"], "failed_or_stale")

    def current_projection_fixture(self):
        configuration = self.root / "approved-config.txt"
        configuration.write_text("fixture-only", encoding="utf-8")
        receipt = json.loads(json.dumps(self.receipt))
        receipt["configuration"] = {"before_sha256": digest(configuration), "after_sha256": digest(configuration), "unchanged": True}
        receipt["core_closeout"] = {"core_closeout_complete": True}
        path = self.root / "outputs/p6/current-core.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        deployment = {"entry": {"core_skill_observation": {"installed": True, "state": "source_match"},
                                "global_agents_observation": {"default_entry_rule_present": True, "white_hat_rule_present": True}}}
        return configuration, path, deployment

    def test_current_projection_separates_scoped_closeout_from_full_acceptance(self):
        configuration, path, deployment = self.current_projection_fixture()
        report = current_core_projection(self.root, receipt_path=path.relative_to(self.root).as_posix(),
                                         deployment=deployment, config_path=configuration)
        self.assertTrue(report["evidence_valid"])
        self.assertTrue(report["closeout"]["core_closeout_complete"])
        self.assertFalse(report["full_capability_acceptance_complete"])
        self.assertFalse(report["full_spec_retested"])
        self.assertIn("T19", [row["id"] for row in report["matched_current_scenarios"]])

    def test_current_projection_recomputes_instead_of_trusting_old_complete_flag(self):
        configuration, path, deployment = self.current_projection_fixture()
        (self.root / "Cargo.toml").write_text("changed", encoding="utf-8")
        report = current_core_projection(self.root, receipt_path=path.relative_to(self.root).as_posix(),
                                         deployment=deployment, config_path=configuration)
        self.assertFalse(report["evidence_valid"])
        self.assertFalse(report["closeout"]["core_closeout_complete"])
        self.assertEqual(report["matched_current_scenarios"], [])

    def test_current_projection_denies_closeout_on_configuration_evidence_drift(self):
        configuration, path, deployment = self.current_projection_fixture()
        configuration.write_text("later-user-change", encoding="utf-8")
        report = current_core_projection(self.root, receipt_path=path.relative_to(self.root).as_posix(),
                                         deployment=deployment, config_path=configuration)
        self.assertTrue(report["evidence_valid"])
        self.assertFalse(report["configuration_preserved"])
        self.assertFalse(report["closeout"]["core_closeout_complete"])
        self.assertEqual(report["closeout"]["next_local_work"][-1]["id"], "current_configuration_evidence")
        self.assertEqual(configuration.read_text(encoding="utf-8"), "later-user-change")

    def test_current_projection_missing_receipt_keeps_work_open(self):
        report = current_core_projection(self.root, receipt_path="outputs/p6/missing.json")
        self.assertFalse(report["evidence_valid"])
        self.assertFalse(report["closeout"]["core_closeout_complete"])
        self.assertEqual(report["state"], "receipt_missing")

    def test_unreadable_configuration_denies_closeout_without_repairing_it(self):
        configuration, path, deployment = self.current_projection_fixture()
        before = configuration.read_bytes()
        with mock.patch("refresh_continuation_report.digest", side_effect=PermissionError("unreadable fixture")):
            report = current_core_projection(self.root, receipt_path=path.relative_to(self.root).as_posix(),
                                             deployment=deployment, config_path=configuration)
        self.assertTrue(report["evidence_valid"])
        self.assertFalse(report["configuration_preserved"])
        self.assertFalse(report["closeout"]["core_closeout_complete"])
        self.assertEqual(configuration.read_bytes(), before)

    def test_invalid_current_receipt_cannot_crash_or_keep_cached_complete(self):
        configuration, path, deployment = self.current_projection_fixture()
        original = path.read_text(encoding="utf-8")
        malformed_section = json.loads(original)
        malformed_section["rust"] = None
        malformed_configuration = json.loads(original)
        malformed_configuration["configuration"] = []
        for content in ("{", "[]", original.replace("{", '{"configuration": null,', 1),
                        original[:-1] + ', "untrusted": NaN}', json.dumps(malformed_section),
                        json.dumps(malformed_configuration)):
            with self.subTest(content=content[:48]):
                path.write_text(content, encoding="utf-8")
                report = current_core_projection(self.root, receipt_path=path.relative_to(self.root).as_posix(),
                                                 deployment=deployment, config_path=configuration)
                self.assertFalse(report["evidence_valid"])
                self.assertFalse(report["closeout"]["core_closeout_complete"])
                self.assertEqual(report["state"], "receipt_invalid")

    def test_execution_log_paths_must_be_canonical_not_windows_aliases(self):
        for relative in ("outputs/p6/./rust.log", "outputs//p6/rust.log", "outputs/p6/rust.log.", "outputs/p6/rust.log "):
            with self.subTest(relative=relative):
                self.receipt["rust"]["log_path"] = relative
                report = self.report()
                self.assertFalse(report["checks"]["logs_current"])
                self.assertFalse(report["evidence_valid"])

    def test_linked_log_metadata_is_rejected_before_reading_bytes(self):
        rust = self.root / self.receipt["rust"]["log_path"]
        original_lstat = Path.lstat
        original_read_bytes = Path.read_bytes
        reads = []

        def linked_metadata(path):
            metadata = original_lstat(path)
            if path == rust:
                return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=0x400)
            return metadata

        def record_read(path):
            reads.append(path)
            return original_read_bytes(path)

        with mock.patch.object(Path, "lstat", linked_metadata), mock.patch.object(Path, "read_bytes", record_read):
            report = self.report()
        self.assertFalse(report["evidence_valid"])
        self.assertNotIn(rust, reads)

    def test_log_hash_and_cases_are_bound_to_one_byte_snapshot(self):
        rust = self.root / self.receipt["rust"]["log_path"]
        passed_text = rust.read_text(encoding="utf-8")
        rust.write_text(passed_text.replace(" ... ok", " ... FAILED", 1), encoding="utf-8")
        self.receipt["rust"]["log_sha256"] = digest(rust)
        original_read_text = Path.read_text

        def changed_second_read(path, *arguments, **keywords):
            return passed_text if path == rust else original_read_text(path, *arguments, **keywords)

        with mock.patch.object(Path, "read_text", changed_second_read):
            report = self.report()
        self.assertFalse(report["checks"]["rust_case_records_match_log"])
        self.assertFalse(report["evidence_valid"])

    def test_contradictory_rust_case_records_cannot_be_last_writer_wins(self):
        rust = self.root / self.receipt["rust"]["log_path"]
        case = semantic_cases("T19")[0]
        rust.write_text(f"test {case} ... FAILED\n" + rust.read_text(encoding="utf-8"), encoding="utf-8")
        self.receipt["rust"]["log_sha256"] = digest(rust)
        report = self.report()
        self.assertFalse(report["checks"]["rust_case_records_match_log"])
        self.assertEqual(report["summary"]["passed_for_g6"], 0)

    def test_complete_semantics_only_and_partial_never_promoted(self):
        report = self.report()
        self.assertTrue(report["evidence_valid"])
        self.assertEqual(report["summary"]["passed_for_g6"], len(SEMANTIC_CASES) + len(SEMANTIC_PYTHON_CASES))
        self.assertEqual(report["summary"]["status_counts"]["partial"], 1)
        self.assertEqual(report["summary"]["status_counts"]["blocked_external"], 1)
        self.assertFalse(report["summary"]["g6_scenarios_passed"])

    def test_p7_is_deferred_not_deleted_or_treated_as_g6(self):
        report = self.report()
        self.assertEqual(report["summary"]["total"], len(SEMANTIC_CASES) + len(SEMANTIC_PYTHON_CASES) + 5)
        self.assertEqual(report["summary"]["required_for_g6"], len(SEMANTIC_CASES) + len(SEMANTIC_PYTHON_CASES) + 2)
        self.assertEqual(report["summary"]["status_counts"]["deferred_p7"], 3)

    def test_changed_source_invalidates_previously_passing_evidence(self):
        (self.root / "Cargo.toml").write_text("changed", encoding="utf-8")
        report = self.report()
        self.assertFalse(report["evidence_valid"])
        self.assertEqual(report["summary"]["passed_for_g6"], 0)

    def test_failed_rust_command_is_not_saved_as_pass(self):
        self.receipt["rust"]["exit_code"] = 1
        self.assertFalse(self.report()["evidence_valid"])

    def test_changed_or_missing_logs_invalidate_evidence(self):
        (self.root / "outputs/p6/rust.log").write_text("forged", encoding="utf-8")
        self.assertFalse(self.report()["evidence_valid"])

    def test_forged_case_map_cannot_replace_actual_log(self):
        self.receipt["rust"]["cases"]["not-actually-run"] = "passed"
        report = self.report()
        self.assertFalse(report["checks"]["rust_case_records_match_log"])
        self.assertEqual(report["summary"]["passed_for_g6"], 0)

    def test_sources_changing_during_execution_fail_closed(self):
        self.receipt["source_hashes_after"]["changed"] = "0" * 64
        self.assertFalse(self.report()["evidence_valid"])

    def test_python_case_map_cannot_replace_the_actual_verbose_log(self):
        self.receipt["python"]["cases"]["not.actually.executed"] = "passed"
        self.assertFalse(self.report()["checks"]["python_case_records_match_log"])
        self.assertEqual(self.report()["summary"]["passed_for_g6"], 0)

    def test_python_failure_exit_cannot_be_overridden_by_success_flag(self):
        self.receipt["python"]["exit_code"] = 1
        self.assertFalse(self.report()["checks"]["python_suite_passed"])

    def test_t53_requires_real_process_crash_and_dispatch_guard_not_only_component_success(self):
        missing = semantic_cases("T53")[1]
        del self.receipt["rust"]["cases"][missing]
        path = self.root / self.receipt["rust"]["log_path"]
        path.write_text(path.read_text(encoding="utf-8").replace(f"test {missing} ... ok\n", ""), encoding="utf-8")
        self.receipt["rust"]["log_sha256"] = digest(path)
        report = self.report()
        self.assertTrue(report["evidence_valid"])
        row = next(row for row in report["matrix"] if row["id"] == "T53")
        self.assertEqual(row["status"], "failed_or_stale")

    def test_received_delta_acceptance_requires_all_owner_and_dependency_cases(self):
        for identifier in ("T77", "T84"):
            missing = semantic_cases(identifier)[1]
            del self.receipt["rust"]["cases"][missing]
            path = self.root / self.receipt["rust"]["log_path"]
            path.write_text(path.read_text(encoding="utf-8").replace(f"test {missing} ... ok\n", ""), encoding="utf-8")
            self.receipt["rust"]["log_sha256"] = digest(path)
            row = next(row for row in self.report()["matrix"] if row["id"] == identifier)
            self.assertEqual(row["status"], "failed_or_stale")


    def test_python_semantic_workflows_require_actual_records_not_supporting_rust(self):
        missing = SEMANTIC_PYTHON_CASES["T83"][0]
        del self.receipt["python"]["cases"][missing]
        path = self.root / self.receipt["python"]["log_path"]
        path.write_text("\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if missing not in line) + "\n", encoding="utf-8")
        self.receipt["python"]["log_sha256"] = digest(path)
        report = self.report()
        self.assertTrue(report["evidence_valid"])
        row = next(row for row in report["matrix"] if row["id"] == "T83")
        self.assertEqual(row["status"], "failed_or_stale")

    def test_t21_requires_actual_related_task_workflow_not_only_persistence_components(self):
        missing = SEMANTIC_PYTHON_CASES["T21"][0]
        del self.receipt["python"]["cases"][missing]
        path = self.root / self.receipt["python"]["log_path"]
        path.write_text("\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if missing not in line) + "\n", encoding="utf-8")
        self.receipt["python"]["log_sha256"] = digest(path)
        row = next(row for row in self.report()["matrix"] if row["id"] == "T21")
        self.assertEqual(row["status"], "failed_or_stale")

    def test_t22_project_scope_evidence_does_not_claim_complete_user_acl(self):
        missing = semantic_cases("T22")[0]
        del self.receipt["rust"]["cases"][missing]
        rust_log = self.root / self.receipt["rust"]["log_path"]
        rust_log.write_text(rust_log.read_text(encoding="utf-8").replace(f"test {missing} ... ok\n", ""), encoding="utf-8")
        self.receipt["rust"]["log_sha256"] = digest(rust_log)
        python_log = self.root / self.receipt["python"]["log_path"]
        for case in SUPPORTING_PYTHON_CASES["T22"]:
            self.receipt["python"]["cases"][case] = "passed"
            python_log.write_text(python_log.read_text(encoding="utf-8") + f"{case.rsplit('.', 1)[-1]} ({case}) ... ok\n", encoding="utf-8")
        self.receipt["python"]["log_sha256"] = digest(python_log)
        row = next(row for row in self.report()["matrix"] if row["id"] == "T22")
        self.assertEqual(row["status"], "failed_or_stale")
        self.assertIn(missing, row["test_cases"])

    def test_t22_acl_pass_keeps_os_and_single_owner_scope_explicit(self):
        row = next(row for row in self.report()["matrix"] if row["id"] == "T22")
        self.assertEqual(row["status"], "passed")
        self.assertIn("Windows single-owner", row["coverage"])
        self.assertIn("administrator tamper resistance", row["coverage"])

    def test_closeout_does_not_stop_on_report_generation_or_historical_passes(self):
        deployment = {"entry": {"core_skill_observation": {"installed": True, "state": "source_match"},
                                "global_agents_observation": {"default_entry_rule_present": True, "white_hat_rule_present": True}}}
        acceptance = {"evidence_valid": True, "matrix": [{"id": "T19", "status": "partial"}, {"id": "T22", "status": "passed"}]}
        result = core_closeout_state(acceptance, deployment)
        self.assertFalse(result["core_closeout_complete"])
        self.assertEqual([row["id"] for row in result["next_local_work"]], ["T19"])
        acceptance["matrix"][0]["status"] = "passed"
        self.assertTrue(core_closeout_state(acceptance, deployment)["core_closeout_complete"])
        acceptance["evidence_valid"] = False
        self.assertFalse(core_closeout_state(acceptance, deployment)["core_closeout_complete"])
        acceptance["evidence_valid"] = True
        deployment["entry"]["core_skill_observation"]["state"] = "source_mismatch"
        self.assertFalse(core_closeout_state(acceptance, deployment)["core_closeout_complete"])

    def test_t19_requires_both_actual_repair_and_no_progress_negative_cases(self):
        for missing in semantic_cases("T19"):
            with self.subTest(missing=missing):
                receipt = json.loads(json.dumps(self.receipt))
                receipt["rust"]["cases"].pop(missing)
                path = self.root / receipt["rust"]["log_path"]
                original = path.read_text(encoding="utf-8")
                path.write_text(original.replace(f"test {missing} ... ok\n", ""), encoding="utf-8")
                receipt["rust"]["log_sha256"] = digest(path)
                report = evaluate(self.root, self.specs, receipt)
                self.assertTrue(report["evidence_valid"])
                row = next(row for row in report["matrix"] if row["id"] == "T19")
                self.assertEqual(row["status"], "failed_or_stale")
                path.write_text(original, encoding="utf-8")

    def test_local_revalidation_requires_complete_workflow_and_negative_cases(self):
        missing = semantic_cases("T18")[1]
        del self.receipt["rust"]["cases"][missing]
        path = self.root / self.receipt["rust"]["log_path"]
        path.write_text(path.read_text(encoding="utf-8").replace(f"test {missing} ... ok\n", ""), encoding="utf-8")
        self.receipt["rust"]["log_sha256"] = digest(path)
        row = next(row for row in self.report()["matrix"] if row["id"] == "T18")
        self.assertEqual(row["status"], "failed_or_stale")

    def test_missing_professional_implementation_is_not_blanket_external_blocker(self):
        self.specs["tests"].append(self.spec("T28", kind="actual_professional_artifact"))
        path = self.root / "docs/acceptance-map.json"
        path.write_text(json.dumps(self.specs), encoding="utf-8")
        self.receipt["acceptance_spec_sha256"] = digest(path)
        self.receipt["source_hashes"] = source_snapshot(self.root)
        self.receipt["source_hashes_after"] = dict(self.receipt["source_hashes"])
        row = next(row for row in self.report()["matrix"] if row["id"] == "T28")
        self.assertEqual(row["status"], "not_run")
        self.assertEqual(row["missing_scope"], "internal_workflow_and_matched_artifact_evidence")

    def test_t85_hash_checks_remain_partial_instead_of_complete_scenario(self):
        for identifier in ("T85",):
            self.specs["tests"].append(self.spec(identifier))
        path = self.root / "docs/acceptance-map.json"
        path.write_text(json.dumps(self.specs), encoding="utf-8")
        self.receipt["acceptance_spec_sha256"] = digest(path)
        self.receipt["source_hashes"] = source_snapshot(self.root)
        self.receipt["source_hashes_after"] = dict(self.receipt["source_hashes"])
        log_path = self.root / self.receipt["python"]["log_path"]
        with log_path.open("a", encoding="utf-8") as handle:
            for identifier in ("T85",):
                for case in SUPPORTING_PYTHON_CASES[identifier]:
                    self.receipt["python"]["cases"][case] = "passed"
                    handle.write(f"{case.rsplit('.', 1)[-1]} ({case}) ... ok\n")
        self.receipt["python"]["log_sha256"] = digest(log_path)
        report = self.report()
        self.assertTrue(report["evidence_valid"])
        for identifier in ("T85",):
            row = next(row for row in report["matrix"] if row["id"] == identifier)
            self.assertEqual(row["status"], "partial")
            self.assertTrue(row["missing_scope"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
