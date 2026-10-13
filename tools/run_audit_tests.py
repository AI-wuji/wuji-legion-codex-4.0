"""Run the bounded core suite unless software tests are explicitly requested."""

import argparse
import sys
import unittest

from preflight import ROOT, stamp, write_json


CORE_TEST_MODULES = (
    "test_baseline_rebase",
    "test_catalog_transfer_time_cli",
    "test_cli_help",
    "test_core_cli",
    "test_decision_audit",
    "test_design_audit",
    "test_document_audit",
    "test_evidence_budget_cli",
    "test_execution_baseline",
    "test_experience_workflows",
    "test_governance_release_binding",
    "test_host_probe",
    "test_legion_task",
    "test_native_dag_validator",
    "test_native_host_session",
    "test_native_preparation",
    "test_native_task_driver",
    "test_p3_catalog",
    "test_p6_acceptance",
    "test_p6_evidence_crosswalk",
    "test_p6_package",
    "test_p6_package_validation",
    "test_preflight",
    "test_regression_scope",
    "test_resource_cli",
    "test_selector_workflows",
    "test_whitehat_entry",
    "test_wuji4_framework",
)


def build_suite(include_software_tests=False):
    loader = unittest.defaultTestLoader
    if include_software_tests:
        return loader.discover(str(ROOT / "tools"), pattern="test_*.py")
    return loader.loadTestsFromNames(CORE_TEST_MODULES)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-software-tests", action="store_true",
                        help="Explicitly include tests that may launch external software or inspect its evidence.")
    return parser.parse_args()


if __name__ == "__main__":
    from p6_acceptance import source_snapshot

    options = arguments()
    suite = build_suite(options.include_software_tests)
    before = source_snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    after = source_snapshot()
    report = {"schema_version": 1, "observed_at": stamp(), "kind": "owned_local_core_tests",
              "software_tests_requested": options.include_software_tests,
              "test_modules": list(CORE_TEST_MODULES) if not options.include_software_tests else "explicit_full_discovery",
              "tests_run": result.testsRun, "passed": result.wasSuccessful() and before == after,
              "failures": [str(case) for case, _ in result.failures],
              "errors": [str(case) for case, _ in result.errors],
              "skipped": [str(case) for case, _ in result.skipped],
              "source_hashes_before": before, "source_hashes": after,
              "sources_unchanged": before == after,
              "runtime_acceptance_scenarios_run": 0, "G0": "not_passed",
              "boundary": "Core tests do not prove professional effects, live model execution or backend quota release."}
    write_json(ROOT / "outputs/p0/audit-tests.json", report)
    sys.exit(0 if report["passed"] else 1)
