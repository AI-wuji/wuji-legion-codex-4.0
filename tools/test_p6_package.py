from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path

import package_p6


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "outputs/p6/release-manifest.json"
PACKAGE = ROOT / "outputs/p6/wuji-legion-4.0-p6-package.zip"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class P6PackageTests(unittest.TestCase):
    def test_new_archive_identity_does_not_inherit_historical_full_audit_success(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / ".dev") as temporary:
            root = Path(temporary).resolve()
            audit = root / "outputs/p6/full-audit-report.json"
            manifest = root / "outputs/p6/release-manifest.json"
            package = root / "outputs/p6/package.zip"
            audit.parent.mkdir(parents=True)
            (root / ".dev").mkdir()
            previous_bytes = json.dumps({"passed": True, "checks": {"historical_only": True},
                                         "archive_attestation": {"external_to_archive": True}}).encode("utf-8")
            audit.write_bytes(previous_bytes)
            manifest.write_bytes(b"current sidecar")
            package.write_bytes(b"current archive")
            with mock.patch.object(package_p6, "ROOT", root), mock.patch.object(
                    package_p6, "AUDIT_REPORT_PATH", audit), mock.patch.object(
                    package_p6, "MANIFEST_PATH", manifest), mock.patch.object(
                    package_p6, "PACKAGE_PATH", package):
                package_p6.update_external_archive_attestation(package_p6.sha256(package), package_p6.sha256(manifest))
            current = json.loads(audit.read_text(encoding="utf-8"))
            self.assertFalse(current["passed"])
            self.assertFalse(current["full_audit_reexecuted"])
            self.assertNotIn("checks", current)
            self.assertEqual((root / current["historical_audit"]["path"]).read_bytes(), previous_bytes)
            self.assertEqual(current["historical_audit"]["sha256"], sha256_bytes(previous_bytes))

    def test_final_audit_attests_exact_current_archive_without_being_inside_it(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("outputs/p6/full-audit-report.json", manifest["external_archive_attestations"])
        self.assertNotIn("outputs/p6/full-audit-report.json", {entry["path"] for entry in manifest["files"]})
        with zipfile.ZipFile(PACKAGE) as archive:
            self.assertNotIn("p6/outputs/p6/full-audit-report.json", archive.namelist())
        report = json.loads((ROOT / "outputs/p6/full-audit-report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["archive_attestation"]["external_to_archive"])
        self.assertEqual(report["archive_attestation"]["observed_archive_sha256"], sha256_bytes(PACKAGE.read_bytes()))
        self.assertEqual(report["archive_attestation"]["sidecar_sha256"], sha256_bytes(MANIFEST.read_bytes()))

    def test_external_sidecar_hash_matches_archive(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["archive"]["verification"], "external-sidecar")
        self.assertEqual(manifest["archive"]["sha256"], sha256_bytes(PACKAGE.read_bytes()))

    def test_embedded_manifest_does_not_self_reference_archive_hash(self) -> None:
        with zipfile.ZipFile(PACKAGE) as archive:
            embedded = json.loads(archive.read("p6/outputs/p6/release-manifest.json"))
        self.assertIsNone(embedded["archive"]["sha256"])
        self.assertEqual(embedded["archive"]["verification"], "external-sidecar")

    def test_manifest_files_are_hash_bound_inside_archive(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with zipfile.ZipFile(PACKAGE) as archive:
            names = set(archive.namelist())
            self.assertNotIn("", names)
            for path in (
                "AGENTS.md",
                "outputs/p7/global-entry-state-2026-10-05.json",
                "outputs/p7/core-skill-install-record-2026-10-05.json",
                "src/local_identity.rs",
                "src/artifact_history_migration.sql",
                "tests/p6_resource_acl.rs",
                "tools/p6_acceptance.py",
                "tools/refresh_continuation_report.py",
                "tools/build_p6_evidence_crosswalk.py",
                "tools/test_p6_evidence_crosswalk.py",
                "outputs/p6/evidence-crosswalk.json",
                "outputs/p6/remaining-work.json",
                "docs/design-deltas/027-core-completion-rework-owner-evidence-2026-10-06.md",
                "outputs/p6/continuation-2026-10-06/core-completion-execution.json",
                "outputs/p6/continuation-2026-10-06/core-completion-rust.log",
                "outputs/p6/continuation-2026-10-06/core-completion-python.log",
                "outputs/p6/continuation-2026-10-06/remaining-48-execution.json",
                "outputs/p6/continuation-2026-10-06/failed-missing-artifact-repair/core-completion-execution.json",
            ):
                self.assertIn(f"p6/{path}", names)
            for entry in manifest["files"]:
                name = f"p6/{entry['path']}"
                self.assertIn(name, names)
                content = archive.read(name)
                self.assertEqual(len(content), entry["bytes"])
                self.assertEqual(sha256_bytes(content), entry["sha256"])

    def test_archive_has_no_path_traversal(self) -> None:
        with zipfile.ZipFile(PACKAGE) as archive:
            for name in archive.namelist():
                self.assertFalse(name.startswith("/"))
                self.assertNotIn("..", Path(name).parts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
