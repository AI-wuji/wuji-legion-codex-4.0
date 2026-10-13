from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "tools" / "native_dag_validator.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("input exceeds bounded adapter size")
    return data


def under_root(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError("path escapes project root")
    return resolved


def validate(source: Path, report: Path) -> dict:
    source = under_root(source)
    report = report.resolve()
    if report != ROOT and ROOT not in report.parents:
        raise ValueError("report escapes project root")
    bounded(source)
    command = [sys.executable, "-B", str(VALIDATOR), str(source)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.stderr:
        raise RuntimeError("validator wrote unexpected stderr")
    result = json.loads(completed.stdout)
    evidence = {
        "schema_version": 1,
        "adapter": "p4/software-repair/local-dag-validator",
        "status": "passed" if result.get("passed") is True else "failed",
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "artifact_sha256": sha256(source),
        "validator": str(VALIDATOR.relative_to(ROOT)).replace("\\", "/"),
        "validator_sha256": sha256(VALIDATOR),
        "command": command,
        "runtime": {"python": sys.version, "platform": platform.platform()},
        "exit_code": completed.returncode,
        "result": result,
        "scope": "project-local-test-workspace",
        "native_or_professional_claim": False,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(json.dumps({"status": "error", "detail": "usage: software_repair_adapter.py SOURCE REPORT"}, ensure_ascii=False))
        return 2
    try:
        evidence = validate(Path(args[0]), Path(args[1]))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "detail": str(error)[:240]}, ensure_ascii=False))
        return 1
    print(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
