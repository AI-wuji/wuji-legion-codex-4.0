from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from p6_acceptance import ROOT
import p6_package_validation as validation
from package_p6 import SOURCE_PATH_MIGRATIONS, retained_manifest_entries


class PackageValidationTests(unittest.TestCase):
    def test_known_source_rename_is_explicit_and_does_not_drop_unknown_missing_paths(self):
        old_path, current_path = next(iter(SOURCE_PATH_MIGRATIONS.items()))
        previous = {"files": [{"path": old_path}, {"path": current_path}, {"path": "missing-unrelated.md"}]}
        self.assertEqual(retained_manifest_entries(previous), [
            {"path": current_path}, {"path": "missing-unrelated.md"}])
        self.assertEqual(previous["files"][0]["path"], old_path)
        with self.assertRaisesRegex(ValueError, "Duplicate retained"):
            retained_manifest_entries({"files": [{"path": "src/lib.rs"}, {"path": "src/lib.rs"}]})

    def test_final_archive_audit_is_external_and_cannot_self_reenter_the_package_closure(self):
        for path in ("outputs/p6/full-audit-report.json", "OUTPUTS/P6/FULL-AUDIT-REPORT.JSON"):
            with self.assertRaises(ValueError):
                validation.validate_package_file_path(path)
        previous = {"files": [{"path": "src/lib.rs"}, {"path": "outputs/p6/full-audit-report.json"}]}
        self.assertEqual(retained_manifest_entries(previous), [{"path": "src/lib.rs"}])
        self.assertEqual(len(previous["files"]), 2)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p6-package-validation-", dir=ROOT / ".dev")
        self.root = Path(self.temporary.name).resolve()
        self.root.relative_to((ROOT / ".dev").resolve())
        self.addCleanup(self.temporary.cleanup)
        (self.root / "src").mkdir()
        (self.root / "src/lib.rs").write_bytes(b"pub fn current() {}")
        (self.root / "outputs/p6").mkdir(parents=True)
        content = (self.root / "src/lib.rs").read_bytes()
        self.embedded = {
            "schema_version": 1, "release": "test-1", "phase": "P6", "status": "not-installed",
            "baseline": {"id": "test", "path": "docs/baseline.json"},
            "files": [{"path": "src/lib.rs", "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
            "archive": {"path": "outputs/p6/test.zip", "sha256": None, "verification": "external-sidecar"},
            "install_authorized": False,
        }
        self.manifest = copy.deepcopy(self.embedded)
        self.manifest["embedded_manifest"] = {"path": validation.EMBEDDED_MANIFEST_PATH,
                                              "archive_sha256": None, "archive_hash_scope": "external-sidecar"}
        self.write_archive()

    def write_archive(self, embedded=None, extra=None, duplicate=False):
        package = self.root / "outputs/p6/test.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("p6/src/lib.rs", (self.root / "src/lib.rs").read_bytes())
                archive.writestr(validation.EMBEDDED_MANIFEST_PATH, json.dumps(embedded or self.embedded))
                if extra:
                    archive.writestr(extra, b"unexpected")
                if duplicate:
                    archive.writestr("p6/src/lib.rs", b"different")
        self.manifest["archive"]["sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()

    def result(self):
        return validation.package_consistency(self.root, self.manifest)

    def test_valid_archive_and_source_closure(self):
        self.assertTrue(self.result()["passed"], self.result())

    def test_tampered_embedded_identity_is_rejected(self):
        embedded = copy.deepcopy(self.embedded)
        embedded["release"] = "forged"
        self.write_archive(embedded=embedded)
        self.assertFalse(self.result()["embedded_manifest_valid"])

    def test_tampered_embedded_file_declarations_are_rejected(self):
        embedded = copy.deepcopy(self.embedded)
        embedded["files"][0]["sha256"] = "0" * 64
        self.write_archive(embedded=embedded)
        self.assertFalse(self.result()["passed"])

    def test_embedded_manifest_type_substitutions_are_rejected(self):
        variants = [
            ("schema_version", dict(self.embedded, schema_version=True)),
            ("install_authorized", dict(self.embedded, install_authorized=0)),
        ]
        embedded = copy.deepcopy(self.embedded)
        embedded["files"][0]["bytes"] = float(embedded["files"][0]["bytes"])
        variants.append(("file_size", embedded))
        for field, embedded in variants:
            with self.subTest(field=field):
                self.write_archive(embedded=embedded)
                result = self.result()
                self.assertFalse(result["embedded_manifest_valid"], result)
                self.assertFalse(result["passed"], result)

    def test_embedded_manifest_object_key_order_does_not_affect_validation(self):
        embedded = dict(reversed(list(self.embedded.items())))
        embedded["files"] = [dict(reversed(list(entry.items()))) for entry in self.embedded["files"]]
        self.write_archive(embedded=embedded)
        self.assertTrue(self.result()["passed"], self.result())

    def test_duplicate_zip_members_are_rejected(self):
        self.write_archive(duplicate=True)
        self.assertFalse(self.result()["passed"])

    def test_duplicate_manifest_members_are_rejected(self):
        self.manifest["files"].append(copy.deepcopy(self.manifest["files"][0]))
        self.assertFalse(self.result()["passed"])

    def test_windows_absolute_backslash_and_traversal_are_rejected(self):
        for value in ("C:/escape", "\\\\server\\file", "p6\\..\\escape", "../escape", "/escape", "p6//file", "p6/NUL.txt"):
            with self.subTest(path=value):
                self.write_archive(extra=value)
                self.assertFalse(self.result()["passed"])

    def test_extra_members_are_not_a_closed_package(self):
        self.write_archive(extra="p6/extra.txt")
        self.assertFalse(self.result()["archive_entries_closed"])

    def test_changed_source_is_not_hash_bound(self):
        (self.root / "src/lib.rs").write_bytes(b"changed")
        self.assertFalse(self.result()["declared_files_match"])

    def test_missing_source_fails_without_exception(self):
        self.manifest["files"][0]["path"] = "src/missing.rs"
        self.assertFalse(self.result()["passed"])

    def test_decompression_and_entry_caps_fail_before_reading(self):
        with patch.object(validation, "MAX_TOTAL_UNCOMPRESSED_BYTES", 10):
            self.assertFalse(self.result()["passed"])
        with patch.object(validation, "MAX_ARCHIVE_ENTRIES", 1):
            self.assertFalse(self.result()["passed"])

    def test_private_or_runtime_files_cannot_be_declared(self):
        for value in (".dev/auth.json", "target/lib.rs", "src/.env", "src/state.sqlite", "src/private.key"):
            with self.subTest(path=value):
                with self.assertRaises(ValueError):
                    validation.validate_package_file_path(value)

    def test_invalid_zip_or_manifest_fails_closed(self):
        (self.root / "outputs/p6/test.zip").write_bytes(b"not-a-zip")
        self.manifest["archive"]["sha256"] = hashlib.sha256(b"not-a-zip").hexdigest()
        self.assertFalse(self.result()["passed"])
        self.assertFalse(validation.package_consistency(self.root, {})["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
