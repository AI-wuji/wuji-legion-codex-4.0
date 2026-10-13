"""Tests extraction honesty and bounded PDF evidence, not runtime acceptance."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter

import document_audit as audit


class DocumentAuditTests(unittest.TestCase):
    def test_page_bounds(self):
        report = {"page_count": 1, "pages": [{"page": 1}]}
        self.assertEqual(audit.selected_page(report, 1), {"page": 1})
        for bad in (-1, 0, 2):
            with self.assertRaises(ValueError):
                audit.selected_page(report, bad)

    def test_external_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outside.pdf"
            path.write_bytes(b"fake")
            with self.assertRaises(ValueError):
                audit.checked_source(path)

    def test_size_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.pdf"
            path.write_bytes(b"123")
            with patch.object(audit, "SOURCES", {"test": Path(directory)}), \
                    patch.object(audit, "MAX_SOURCE_BYTES", 2):
                with self.assertRaises(ValueError):
                    audit.checked_source(path)

    def test_extraction_does_not_acknowledge_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with path.open("wb") as stream:
                writer.write(stream)
            def save(target, value):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(value), encoding="utf-8")
            with patch.object(audit, "SOURCES", {"test": root}), \
                    patch.object(audit, "REPORT_ROOT", root / "reports"), \
                    patch.object(audit, "write_json", save):
                report = audit.inspect_pdf(path)
                self.assertEqual(report["status"], "extracted_not_read")
                self.assertEqual(report["reading_records"], [])
                self.assertTrue(report["pages"][0]["visual_review_required"])
                path.write_bytes(path.read_bytes() + b"\n% changed")
                with self.assertRaises(ValueError):
                    audit.report_for(path)

    def test_same_basename_has_different_source_identity(self):
        self.assertNotEqual(audit.source_key(Path("a/notes.pdf")),
                            audit.source_key(Path("b/notes.pdf")))

    def test_coverage_requires_fresh_explicit_notes_and_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "page-0001.png"
            image.write_bytes(b"reviewed render")
            report = {"page_count": 1, "source_sha256": "source",
                      "pages": [{"page": 1}], "reading_records": []}
            output = root / "extraction.json"
            record = {"page": 1, "source_sha256": "source",
                      "render_sha256": audit.digest(image), "note": "Actually reviewed",
                      "kind": "explicit_visual_reviewer_acknowledgement"}
            for changes in ({"note": ""}, {"source_sha256": "old"},
                            {"kind": "ocr-extracted-not-read"}, {"page": 2}):
                report["reading_records"] = [{**record, **changes}]
                audit.reconcile_reading(report, output)
                self.assertFalse(report["reading_summary"]["complete"])
            report["reading_records"] = [record, record]
            audit.reconcile_reading(report, output)
            self.assertEqual(report["status"], "visual_review_complete")
            self.assertEqual(report["reading_summary"]["reviewed_pages"], [1])
            image.write_bytes(b"changed render")
            audit.reconcile_reading(report, output)
            self.assertEqual(report["status"], "extracted_not_read")


if __name__ == "__main__":
    unittest.main()
