import json
from pathlib import Path
import unittest
from unittest.mock import patch

import p6_acceptance
from p6_acceptance import ROOT, digest, office_artifact_checks, office_document_artifact_checks


class OfficeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.proof = ROOT / "outputs/p4/officecli-probe-evidence.json"
        self.receipt = {"tool_evidence_hashes": {"outputs/p4/officecli-probe-evidence.json": digest(self.proof)}}

    def test_real_original_entrypoint_uses_canonical_windows_identity_not_case_string(self):
        checks = office_artifact_checks(ROOT, self.receipt)
        self.assertTrue(checks["original_binary_current"], checks)
        self.assertTrue(checks["protected_config_unchanged_during_action"], checks)
        self.assertTrue(all(checks.values()), checks)

    def test_unrecorded_protected_config_change_invalidates_evidence(self):
        actual_digest = digest
        target = Path("C:/Users/Administrator/.codex/config.toml").resolve()
        with patch.object(
            p6_acceptance,
            "digest",
            side_effect=lambda path: "0" * 64 if Path(path).resolve() == target else actual_digest(path),
        ):
            checks = office_artifact_checks(ROOT, self.receipt)
        self.assertFalse(checks["protected_config_current"], checks)

    def test_stale_probe_receipt_is_not_formal_acceptance(self):
        self.receipt["tool_evidence_hashes"]["outputs/p4/officecli-probe-evidence.json"] = "0" * 64
        self.assertFalse(office_artifact_checks(ROOT, self.receipt)["receipt_current"])

    def test_changed_adapter_invalidates_the_old_tool_probe(self):
        actual_digest = digest
        target = ROOT / "adapters/p4/officecli_adapter.py"
        with patch.object(p6_acceptance, "digest", side_effect=lambda path: "0" * 64 if path == target else actual_digest(path)):
            self.assertFalse(office_artifact_checks(ROOT, self.receipt)["adapter_current"])

    def test_changed_artifact_invalidates_current_acceptance(self):
        actual_digest = digest
        evidence = json.loads(self.proof.read_text(encoding="utf-8"))
        target = ROOT / evidence["artifact"]["path"]
        with patch.object(p6_acceptance, "digest", side_effect=lambda path: "0" * 64 if path == target else actual_digest(path)):
            self.assertFalse(office_artifact_checks(ROOT, self.receipt)["artifact_current"])

    def test_document_workflow_evidence_is_current_but_render_remains_external(self):
        checks = office_document_artifact_checks(ROOT)
        self.assertTrue(checks["evidence_current"], checks)
        self.assertFalse(checks["word_required_render"], checks)

    def test_changed_document_implementation_invalidates_document_evidence(self):
        actual_digest = digest
        target = ROOT / "adapters/p4/office_document_workflow.py"
        with patch.object(p6_acceptance, "digest", side_effect=lambda path: "0" * 64 if path == target else actual_digest(path)):
            checks = office_document_artifact_checks(ROOT)
        self.assertFalse(checks["implementation_current"], checks)
        self.assertFalse(checks["evidence_current"], checks)

    def test_changed_document_artifact_invalidates_document_evidence(self):
        actual_digest = digest
        evidence = json.loads((ROOT / "outputs/p4/office-document-workflow-evidence.json").read_text(encoding="utf-8"))
        target = ROOT / evidence["formats"]["sheet"]["artifact"]["path"]
        with patch.object(p6_acceptance, "digest", side_effect=lambda path: "0" * 64 if path == target else actual_digest(path)):
            checks = office_document_artifact_checks(ROOT)
        self.assertFalse(checks["sheet_artifact_current"], checks)
        self.assertFalse(checks["evidence_current"], checks)


if __name__ == "__main__":
    unittest.main()
