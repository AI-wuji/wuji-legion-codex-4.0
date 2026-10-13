from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from p6_acceptance import ROOT, digest, rust_cases_from_log, source_snapshot
from run_audit_tests import arguments, build_suite


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        self.cases = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases[test.id()] = "passed"

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.cases[test.id()] = "failed"

    def addError(self, test, error):
        super().addError(test, error)
        self.cases[test.id()] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.cases[test.id()] = "skipped"


def config_observation() -> dict:
    path = Path("C:/Users/Administrator/.codex/config.toml")
    return {"path": str(path), "sha256": digest(path) if path.is_file() else None,
            "content_exported": False, "modified_by_runner": False}


def main() -> None:
    options = arguments()
    started = datetime.now(timezone.utc).isoformat()
    before = source_snapshot()
    configuration_before = config_observation()
    logs = ROOT / "outputs/p6"
    logs.mkdir(parents=True, exist_ok=True)
    powershell = Path("C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe")
    if not powershell.is_file():
        raise RuntimeError("Verified isolated PowerShell runtime unavailable; no install or global environment change")
    command = [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "tools/build-core.ps1"), "-Mode", "Test"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=300,
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    rust_log = completed.stdout + completed.stderr
    rust_path = logs / "rust-full-tests.log"
    rust_path.write_bytes(rust_log)
    rust_text = rust_log.decode("utf-8", errors="replace")
    cases = rust_cases_from_log(rust_text)
    python_path = logs / "python-tool-tests.log"
    suite = build_suite(options.include_software_tests)
    with python_path.open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordedResult).run(suite)
    after = source_snapshot()
    configuration_after = config_observation()
    tool_evidence = ROOT / "outputs/p4/officecli-probe-evidence.json"
    receipt = {
        "schema_version": 1, "kind": "owned_local_regression_execution",
        "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "acceptance_spec_sha256": digest(ROOT / "docs/acceptance-map.json"),
        "source_hashes": before, "source_hashes_after": after,
        "tool_evidence_hashes": {tool_evidence.relative_to(ROOT).as_posix(): digest(tool_evidence)} if tool_evidence.is_file() else {},
        "rust": {"command": command, "exit_code": completed.returncode, "cases": cases,
                 "tests_passed": sum(value == "passed" for value in cases.values()),
                 "log_path": rust_path.relative_to(ROOT).as_posix(), "log_sha256": digest(rust_path)},
        "python": {"exit_code": 0 if result.wasSuccessful() else 1, "passed": result.wasSuccessful(),
                   "software_tests_requested": options.include_software_tests,
                   "tests_run": result.testsRun, "cases": result.cases,
                   "skipped": len(result.skipped), "log_path": python_path.relative_to(ROOT).as_posix(),
                   "log_sha256": digest(python_path)},
        "configuration": {"before": configuration_before, "after": configuration_after,
                          "unchanged_during_run": configuration_before["sha256"] is not None and configuration_before["sha256"] == configuration_after["sha256"],
                          "historical_expected_sha256": "f37efee8358d33ff6b848a6c207b974c501dde0d548a7cfe4d4b052cd1d6e4fc",
                          "historical_difference_actor": "unknown"},
        "native_or_professional_acceptance": False, "P7": False, "shutdown": False,
    }
    (logs / "test-execution.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    passed = completed.returncode == 0 and result.wasSuccessful() and before == after and receipt["configuration"]["unchanged_during_run"]
    print(json.dumps({"passed": passed, "rust_passed": receipt["rust"]["tests_passed"], "python_run": result.testsRun,
                      "sources_stable": before == after, "config_unchanged": receipt["configuration"]["unchanged_during_run"]}))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
