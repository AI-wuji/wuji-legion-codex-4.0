import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.p4 import officecli_workflow as workflow

PACKAGE_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def write_text_fixture(path, texts, *, external=False, image=False, target="slides/slide1.xml",
                       absolute=False, default_content_type=False):
    namespaces = workflow.NAMESPACES
    presentation = ET.Element(f"{{{namespaces['p']}}}presentation")
    slide_list = ET.SubElement(presentation, f"{{{namespaces['p']}}}sldIdLst")
    ET.SubElement(slide_list, f"{{{namespaces['p']}}}sldId", {
        "id": "256", f"{{{namespaces['r']}}}id": "rId1"})
    slide = ET.Element(f"{{{namespaces['p']}}}sld")
    tree = ET.SubElement(ET.SubElement(slide, f"{{{namespaces['p']}}}cSld"), f"{{{namespaces['p']}}}spTree")
    for text in texts:
        shape = ET.SubElement(tree, f"{{{namespaces['p']}}}sp")
        body = ET.SubElement(shape, f"{{{namespaces['p']}}}txBody")
        for paragraph in text.split("\n"):
            native_paragraph = ET.SubElement(body, f"{{{namespaces['a']}}}p")
            native_run = ET.SubElement(native_paragraph, f"{{{namespaces['a']}}}r")
            ET.SubElement(native_run, f"{{{namespaces['a']}}}t").text = paragraph
    if image:
        ET.SubElement(tree, f"{{{namespaces['p']}}}pic")
    relationships = ET.Element(f"{{{PACKAGE_RELATIONSHIPS}}}Relationships")
    ET.SubElement(relationships, f"{{{PACKAGE_RELATIONSHIPS}}}Relationship", {
        "Id": "rId1", "Type": namespaces["r"] + "/slide", "Target": "/ppt/" + target if absolute else target})
    if external:
        ET.SubElement(relationships, f"{{{PACKAGE_RELATIONSHIPS}}}Relationship", {
            "Id": "rId2", "Type": namespaces["r"] + "/hyperlink",
            "Target": "https://example.invalid", "TargetMode": "External"})
    root_relationships = ET.Element(f"{{{PACKAGE_RELATIONSHIPS}}}Relationships")
    ET.SubElement(root_relationships, f"{{{PACKAGE_RELATIONSHIPS}}}Relationship", {
        "Id": "rId1", "Type": namespaces["r"] + "/officeDocument",
        "Target": "/ppt/presentation.xml" if absolute else "ppt/presentation.xml"})
    content_types = ET.Element(f"{{{CONTENT_TYPES}}}Types")
    ET.SubElement(content_types, f"{{{CONTENT_TYPES}}}{'Default' if default_content_type else 'Override'}", {
        "Extension" if default_content_type else "PartName": "xml" if default_content_type else "/ppt/presentation.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"})
    documents = {"[Content_Types].xml": content_types, "_rels/.rels": root_relationships,
                 "ppt/presentation.xml": presentation, "ppt/_rels/presentation.xml.rels": relationships,
                 "ppt/slides/slide1.xml": slide}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, document in documents.items():
            archive.writestr(name, ET.tostring(document, encoding="utf-8", xml_declaration=True))


class OfficeCliWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="officecli-workflow-test-", dir=ROOT / ".dev")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name).resolve()
        self.binary = self.workspace / "fixture.exe"
        self.binary.write_bytes(b"unit test binary fixture, never executed")
        self.configuration = self.workspace / "protected-fixture.toml"
        self.configuration.write_bytes(b"protected fixture")
        self.calls = []
        self.texts = []
        self.failure = None
        self.timeout = None
        self.ignore_set = False
        self.corrupt_after_set = False
        self.change_configuration = False
        self.get_response = None
        self.version = workflow.office.PINNED_VERSION
        original_digest = workflow.office.digest

        def digest(path):
            return workflow.office.PINNED_SHA256 if Path(path) == self.binary else original_digest(Path(path))

        patches = [patch.object(workflow.office, "DEFAULT_BINARY", self.binary),
                   patch.object(workflow.office, "digest", side_effect=digest),
                   patch.object(workflow.office, "protected_snapshot", side_effect=lambda: {
                       str(self.configuration): original_digest(self.configuration)}),
                   patch.object(workflow.office.subprocess, "run", side_effect=self.native)]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    def native(self, arguments, **options):
        self.calls.append(arguments[1:])
        self.assertEqual(Path(options["cwd"]), self.workspace)
        for setting in ("OFFICECLI_NO_AUTO_INSTALL", "OFFICECLI_SKIP_UPDATE", "OFFICECLI_NO_AUTO_RESIDENT"):
            self.assertEqual(options["env"][setting], "1")
        operation = arguments[1]
        if operation == self.timeout:
            raise subprocess.TimeoutExpired(arguments, 30)
        if operation == self.failure:
            if operation == "create":
                Path(arguments[2]).write_bytes(b"partial failed create")
            return subprocess.CompletedProcess(arguments, 9, b"", b"deliberate fixture failure")
        if operation == "--version":
            return subprocess.CompletedProcess(arguments, 0, self.version.encode(), b"")
        path = Path(arguments[2])
        output = "ok"
        if operation == "create":
            write_text_fixture(path, [])
        elif operation == "add":
            properties = [value for value in arguments if value.startswith(("title=", "text="))]
            self.texts.append(properties[0].split("=", 1)[1])
            write_text_fixture(path, self.texts)
        elif operation == "set":
            if not self.ignore_set:
                self.texts[-1] = workflow.AFTER_TEXT
                write_text_fixture(path, self.texts)
            if self.corrupt_after_set:
                path.write_bytes(b"corrupted artifact despite native success")
            if self.change_configuration:
                self.configuration.write_bytes(b"unexpected protected fixture change")
        elif operation == "get":
            text = workflow.AFTER_TEXT if self.ignore_set and any(call[0] == "set" for call in self.calls) else self.texts[-1]
            output = self.get_response if self.get_response is not None else json.dumps({
                "success": True, "data": {"matches": 1, "results": [{"text": text}]}})
        elif operation == "view":
            self.assertEqual(arguments[-1], "outline")
            output = self.texts[0]
        return subprocess.CompletedProcess(arguments, 0, output.encode("utf-8"), b"")

    def execute(self, **arguments):
        result = workflow.run(self.workspace, **arguments)
        self.assertEqual(result, json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8")))
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["professional_design_quality"], "not_claimed")
        self.assertFalse(result["P7"])
        return result

    def test_success_records_commands_hashes_protection_and_independent_ooxml(self):
        result = self.execute(title="Editable text & <native>")
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["state"], "completed_bounded_task")
        self.assertEqual(result["selector"], "/slide[1]/shape[2]")
        self.assertEqual(result["artifact"]["sha256"], hashlib.sha256(Path(result["artifact"]["path"]).read_bytes()).hexdigest())
        self.assertEqual(result["protected_configurations_before"], result["protected_configurations_after"])
        self.assertTrue(result["ooxml"]["after"]["passed"])
        self.assertTrue(all(action["exit_code"] == 0 for action in result["actions"]))

    def test_custom_output_is_only_a_local_receipt(self):
        result = self.execute(output=Path("custom-receipt.json"))
        self.assertTrue(result["passed"])
        self.assertEqual(Path(result["receipt_path"]), self.workspace / "custom-receipt.json")

    def test_outside_and_root_workspaces_raise_identifiable_error_without_native_calls(self):
        for workspace in (ROOT, ROOT / ".dev", self.workspace / "missing"):
            with self.subTest(workspace=workspace), self.assertRaises(workflow.OfficeWorkflowError) as caught:
                workflow.run(workspace)
            self.assertEqual(caught.exception.code, "unsafe_workspace")
            self.assertFalse(caught.exception.receipt["passed"])
        self.assertEqual(self.calls, [])

    def test_external_output_and_preexisting_receipt_are_never_modified(self):
        outside = ROOT / "forbidden-officecli-receipt.json"
        with self.assertRaises(workflow.OfficeWorkflowError) as caught:
            workflow.run(self.workspace, outside)
        self.assertEqual(caught.exception.code, "unsafe_output")
        existing = self.workspace / "existing.json"
        existing.write_bytes(b"untouched receipt")
        with self.assertRaises(workflow.OfficeWorkflowError) as caught:
            workflow.run(self.workspace, existing)
        self.assertEqual(caught.exception.code, "receipt_exists")
        self.assertEqual(existing.read_bytes(), b"untouched receipt")
        self.assertEqual(self.calls, [])

    def test_preexisting_pptx_is_not_read_or_overwritten(self):
        path = self.workspace / "text-task.pptx"
        path.write_bytes(b"existing user fixture, never treated as input")
        result = self.execute()
        self.assertFalse(result["passed"])
        self.assertEqual(path.read_bytes(), b"existing user fixture, never treated as input")
        self.assertIsNone(result["artifact"]["sha256"])
        self.assertEqual(self.calls, [])

    def test_invalid_title_preserves_failed_receipt_without_execution(self):
        result = self.execute(title="unsafe\x00title")
        self.assertFalse(result["passed"])
        self.assertEqual(result["errors"][0]["stage"], "input")
        self.assertEqual(self.calls, [])

    def test_nonzero_exit_preserves_original_failure_and_closes_once_without_retry(self):
        self.failure = "set"
        result = self.execute()
        self.assertFalse(result["passed"])
        failure = next(action for action in result["actions"] if action["arguments"][0] == "set")
        self.assertEqual(failure["exit_code"], 9)
        self.assertEqual(failure["stderr"], "deliberate fixture failure")
        self.assertEqual([call[0] for call in self.calls].count("set"), 1)
        self.assertEqual([call[0] for call in self.calls].count("close"), 1)
        self.assertTrue(Path(result["artifact"]["path"]).is_file())

    def test_partial_failed_create_is_hashed_and_not_retried(self):
        self.failure = "create"
        result = self.execute()
        self.assertFalse(result["passed"])
        self.assertIsNotNone(result["artifact"]["sha256"])
        self.assertFalse(result["ooxml"]["after"]["passed"])
        self.assertEqual([call[0] for call in self.calls], ["--version", "create"])

    def test_timeout_retains_unknown_exit_and_does_not_retry(self):
        self.timeout = "set"
        result = self.execute()
        failure = next(action for action in result["actions"] if action["arguments"][0] == "set")
        self.assertFalse(result["passed"])
        self.assertIsNone(failure["exit_code"])
        self.assertFalse(failure["owned_process_exit_observed"])
        self.assertEqual(failure["error"]["type"], "TimeoutExpired")
        self.assertEqual([call[0] for call in self.calls].count("set"), 1)

    def test_close_failure_is_recorded_without_retry(self):
        self.failure = "close"
        result = self.execute()
        self.assertFalse(result["passed"])
        self.assertFalse(result["cleanup"]["close_succeeded"])
        self.assertEqual([call[0] for call in self.calls].count("close"), 1)

    def test_changed_protection_aborts_downstream_execution(self):
        self.change_configuration = True
        result = self.execute()
        self.assertFalse(result["checks"]["protected_configurations_unchanged"])
        self.assertFalse(result["passed"])
        self.assertEqual([call[0] for call in self.calls][-1], "set")
        self.assertEqual(result["actions"][-1]["error"]["type"], "PermissionError")

    def test_wrong_version_aborts_before_document_creation(self):
        self.version = "unexpected-version"
        result = self.execute()
        self.assertFalse(result["passed"])
        self.assertEqual([call[0] for call in self.calls], ["--version"])
        self.assertFalse(Path(result["artifact"]["path"]).exists())

    def test_invalid_get_reply_fails_closed_before_set(self):
        self.get_response = "not json"
        result = self.execute()
        self.assertFalse(result["passed"])
        self.assertNotIn("set", [call[0] for call in self.calls])
        self.assertEqual(result["errors"][0]["type"], "JSONDecodeError")

    def test_independent_check_detects_native_success_without_actual_revision(self):
        self.ignore_set = True
        result = self.execute()
        self.assertTrue(result["checks"]["native_get_after_exact"])
        self.assertFalse(result["checks"]["independent_ooxml_revision"])
        self.assertFalse(result["passed"])

    def test_corrupted_output_is_hashed_and_fails_independent_check(self):
        self.corrupt_after_set = True
        result = self.execute()
        self.assertFalse(result["passed"])
        self.assertIsNotNone(result["artifact"]["sha256"])
        self.assertFalse(result["ooxml"]["after"]["passed"])

    def test_independent_inspector_rejects_images_external_links_and_wrong_slide_reference(self):
        path = self.workspace / "inspector-fixture.pptx"
        for options in ({"external": True}, {"image": True}, {"target": "slides/missing.xml"}):
            with self.subTest(options=options):
                write_text_fixture(path, ["Title", "Body"], **options)
                self.assertFalse(workflow.inspect_text_pptx(path)["passed"])

    def test_inspector_accepts_package_absolute_targets_and_default_content_types(self):
        path = self.workspace / "opc-content-type-fixture.pptx"
        for options in ({"absolute": True}, {"default_content_type": True},
                        {"absolute": True, "default_content_type": True}):
            with self.subTest(options=options):
                write_text_fixture(path, ["Title", "Body"], **options)
                self.assertTrue(workflow.inspect_text_pptx(path)["passed"])


@unittest.skipUnless(os.environ.get("WUJI4_OFFICECLI_LIVE") == "1", "Explicit opt-in for existing pinned OfficeCLI")
class OfficeCliLiveWorkflowTests(unittest.TestCase):
    def test_real_isolated_task(self):
        workspace = Path(tempfile.mkdtemp(prefix="officecli-workflow-live-", dir=ROOT / ".dev"))
        result = workflow.run(workspace)
        print("\nOfficeCLI live receipt: " + result["receipt_path"])
        self.assertTrue(result["passed"], json.dumps(result, ensure_ascii=False))
        self.assertTrue(result["checks"]["protected_configurations_unchanged"])
        self.assertEqual(result["ooxml"]["after"]["native_shape_count"], 2)
        self.assertEqual(result["artifact"]["sha256"], workflow.office.digest(Path(result["artifact"]["path"])))


if __name__ == "__main__":
    unittest.main()
