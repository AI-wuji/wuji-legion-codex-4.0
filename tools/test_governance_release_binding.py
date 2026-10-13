import hashlib
import json
from pathlib import Path
import unittest

from p6_package_validation import strict_json


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_governance_evidence(report: dict) -> bool:
    source = ROOT / report["source"]
    test_log = ROOT / report["test_log"]
    t24 = report.get("t24_evidence", {})
    t24_path = ROOT / t24.get("path", "") if isinstance(t24, dict) else ROOT / "missing"
    return (
        report["status"] == "implemented_and_tested"
        and report["passed"] is True
        and report["runtime_admission"] is False
        and report["formal_model_experts"] == 0
        and all(report["checks"].values())
        and source.is_file()
        and test_log.is_file()
        and report["source_sha256"] == digest(source)
        and report["test_log_sha256"] == digest(test_log)
        and isinstance(t24, dict)
        and t24.get("passed") is True
        and t24_path.is_file()
        and t24.get("sha256") == digest(t24_path)
    )


class GovernanceReleaseBindingTests(unittest.TestCase):
    def test_governance_report_and_previous_archive_identity_are_bound(self):
        report = json.loads((ROOT / "outputs/p5/p5-governance-report.json").read_text(encoding="utf-8"))
        self.assertTrue(current_governance_evidence(report))
        manifest = strict_json((ROOT / "outputs/p6/release-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "local_package_created_not_installed")
        self.assertFalse(manifest["install_authorized"])
        self.assertFalse(manifest["production_modified"])
        self.assertFalse(manifest["p7"])
        archive = ROOT / manifest["archive"]["path"]
        self.assertEqual(manifest["archive"]["sha256"], digest(archive))

    def test_tampered_governance_evidence_and_in_flight_release_are_rejected(self):
        report = json.loads((ROOT / "outputs/p5/p5-governance-report.json").read_text(encoding="utf-8"))
        report["source_sha256"] = "tampered"
        self.assertFalse(current_governance_evidence(report))
        report = json.loads((ROOT / "outputs/p5/p5-governance-report.json").read_text(encoding="utf-8"))
        report["status"] = "in_flight"
        self.assertFalse(current_governance_evidence(report))
        report = json.loads((ROOT / "outputs/p5/p5-governance-report.json").read_text(encoding="utf-8"))
        report["t24_evidence"]["sha256"] = "tampered"
        self.assertFalse(current_governance_evidence(report))


if __name__ == "__main__":
    unittest.main()
