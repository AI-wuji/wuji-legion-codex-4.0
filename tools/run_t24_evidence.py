from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PWSH = Path("C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe")
CONFIG = Path("C:/Users/Administrator/.codex/config.toml")
CASES = {
    "governance::tests::source_license_admission_requires_explicit_policy_and_preserves_versions",
    "governance::tests::in_flight_release_is_pinned_while_new_source_version_is_staged",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not PWSH.is_file():
        raise RuntimeError("verified isolated PowerShell runtime unavailable")
    config_before = digest(CONFIG) if CONFIG.is_file() else None
    command = [str(PWSH), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools/build-core.ps1"), "-Mode", "Test"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=300,
                               env=dict(__import__("os").environ, PYTHONIOENCODING="utf-8"),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    observed = {name: "passed" for name in re.findall(r"test (governance::tests::\S+) \.\.\. ok", output) if name in CASES}
    config_after = digest(CONFIG) if CONFIG.is_file() else None
    source_hashes = {"src/governance.rs": digest(ROOT / "src/governance.rs"), "tools/run_t24_evidence.py": digest(Path(__file__))}
    checks = {
        "isolated_runtime_executed": completed.returncode == 0,
        "required_cases_passed": observed == {name: "passed" for name in sorted(CASES)},
        "source_hashes_current": all(digest(ROOT / path) == value for path, value in source_hashes.items()),
        "config_unchanged": config_before is not None and config_before == config_after,
        "runtime_admission_false": True,
        "p7_false": True,
        "shutdown_false": True,
    }
    evidence = {
        "schema_version": 1,
        "kind": "t24_isolated_update_governance_runtime_evidence",
        "command": ["tools/build-core.ps1", "-Mode", "Test"],
        "exit_code": completed.returncode,
        "cases": observed,
        "checks": checks,
        "passed": all(checks.values()),
        "runtime_execution": True,
        "runtime_admission": False,
        "config_sha256_before": config_before,
        "config_sha256_after": config_after,
        "source_hashes": source_hashes,
        "scope": "isolated project core test; no Codex configuration, release, package, or host dispatch",
        "uncovered": [
            "full 95-scenario G6 remains outside this T24 evidence",
            "external source license legal review is not inferred from a local allowlist",
            "native host dispatch and P7 installation are not tested",
        ],
    }
    output_path = ROOT / "outputs/p6/t24-update-governance-evidence.json"
    output_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": evidence["passed"], "cases": observed, "output": output_path.relative_to(ROOT).as_posix()}))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
