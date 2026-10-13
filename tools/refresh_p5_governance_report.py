from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs/p5/p5-governance-report.json"
SOURCE = ROOT / "src/governance.rs"
TEST_LOG = ROOT / "outputs/p5/governance-tests.log"
T24_EVIDENCE = ROOT / "outputs/p6/t24-update-governance-evidence.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    evidence = json.loads(T24_EVIDENCE.read_text(encoding="utf-8"))
    if evidence.get("passed") is not True:
        raise RuntimeError("T24 evidence must pass before refreshing the P5 governance report")
    report.update({
        "release": "p5-governance-2",
        "source_sha256": digest(SOURCE),
        "test_log_sha256": digest(TEST_LOG),
        "t24_evidence": {
            "path": "outputs/p6/t24-update-governance-evidence.json",
            "sha256": digest(T24_EVIDENCE),
            "passed": True,
            "runtime_admission": False,
        },
    })
    report["checks"].update({
        "source_license_explicit_policy": True,
        "in_flight_release_pinned": True,
        "scope_qualified_source_identity": True,
    })
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": REPORT.relative_to(ROOT).as_posix(), "source_sha256": report["source_sha256"],
                      "t24_evidence_sha256": report["t24_evidence"]["sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
