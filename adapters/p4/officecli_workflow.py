from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from adapters.p4 import officecli_adapter as office

ROOT = Path(__file__).resolve().parents[2]
BEFORE_TEXT = "Isolated editable text before revision"
AFTER_TEXT = "Isolated editable text after revision"
NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


class OfficeWorkflowError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.receipt = {"state": "failed_evidence_retained", "passed": False, "receipt_path": None,
                        "errors": [{"stage": "preflight", "code": code, "message": message}]}


def inspect_text_pptx(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)) or sum(member.file_size for member in members) > 4 * 1024 * 1024:
            raise ValueError("Duplicate OOXML parts or inspection byte limit exceeded")
        if archive.testzip() is not None:
            raise ValueError("OOXML ZIP integrity check failed")
        required = {"[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml",
                    "ppt/_rels/presentation.xml.rels", "ppt/slides/slide1.xml"}
        if not required.issubset(names):
            raise ValueError("Required presentation OOXML parts are missing")
        documents = {name: ET.fromstring(archive.read(name)) for name in names
                     if name.endswith((".xml", ".rels"))}
    overrides = {element.get("PartName"): element.get("ContentType") for element in documents["[Content_Types].xml"]
                 if element.tag.endswith("}Override")}
    defaults = {element.get("Extension"): element.get("ContentType") for element in documents["[Content_Types].xml"]
                if element.tag.endswith("}Default")}
    presentation = documents["ppt/presentation.xml"]
    slide_ids = presentation.findall("p:sldIdLst/p:sldId", NAMESPACES)
    relationships = list(documents["ppt/_rels/presentation.xml.rels"])
    referenced_slides = [relationship for relationship in relationships
                         if relationship.get("Type", "").endswith("/slide")]
    linked_slide = len(slide_ids) == 1 and len(referenced_slides) == 1
    if linked_slide:
        relationship = referenced_slides[0]
        linked_slide = (slide_ids[0].get(f"{{{NAMESPACES['r']}}}id") == relationship.get("Id")
                        and posixpath.normpath(posixpath.join("ppt", relationship.get("Target", ""))).lstrip("/")
                        == "ppt/slides/slide1.xml")
    slide = documents["ppt/slides/slide1.xml"]
    shapes = slide.findall("p:cSld/p:spTree/p:sp", NAMESPACES)
    shape_texts = ["\n".join("".join(element.text or "" for element in paragraph.findall(".//a:t", NAMESPACES))
                             for paragraph in shape.findall("p:txBody/a:p", NAMESPACES))
                   for shape in shapes]
    checks = {
        "presentation_content_types": overrides.get("/ppt/presentation.xml", defaults.get("xml"))
            == "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        "package_references_presentation": any(relationship.get("Type", "").endswith("/officeDocument")
            and posixpath.normpath(relationship.get("Target", "")).lstrip("/") == "ppt/presentation.xml"
            for relationship in documents["_rels/.rels"]),
        "one_referenced_slide": linked_slide and sum(name.startswith("ppt/slides/slide")
                                                     and name.endswith(".xml") for name in names) == 1,
        "native_text_shapes": len(shapes) == 2 and all(shape_texts),
        "no_nontext_slide_objects": not any(slide.findall(f".//p:{tag}", NAMESPACES)
                                             for tag in ("pic", "graphicFrame", "oleObj", "grpSp", "cxnSp")),
        "no_embedded_assets": not any(name.startswith(("ppt/media/", "ppt/embeddings/"))
                                      or name.lower().endswith(".bin") for name in names),
        "no_external_relationships": not any(relationship.get("TargetMode", "").casefold() == "external"
                                              for name, document in documents.items() if name.endswith(".rels")
                                              for relationship in document),
    }
    return {"checker": "independent_python_zipfile_elementtree", "checks": checks,
            "passed": all(checks.values()), "native_shape_count": len(shapes), "shape_texts": shape_texts}


def _error(error: Exception, stage: str) -> dict:
    return {"stage": stage, "type": type(error).__name__, "message": str(error)}


class _ObservedAdapter(office.OfficeCliAdapter):
    def __init__(self, workspace: Path, actions: list, save):
        self.workflow_actions = actions
        self.save = save
        super().__init__(workspace, office.DEFAULT_BINARY)

    def _invoke(self, arguments: list[str]) -> dict:
        count = len(self.receipts)
        try:
            result = super()._invoke(arguments)
        except Exception as error:
            result = dict(self.receipts[-1]) if len(self.receipts) > count else {
                "arguments": arguments, "exit_code": None, "stdout": "", "stderr": "",
                "owned_process_exit_observed": False,
            }
            result.update(status="failed", error=_error(error, arguments[0]))
            self.workflow_actions.append(result)
            self.save()
            raise
        self.workflow_actions.append(dict(result, status="completed"))
        self.save()
        return result


def _get_matches(result: dict, expected: str) -> bool:
    payload = json.loads(result["stdout"])
    data = payload.get("data", {})
    matches = data.get("results", [])
    return (payload.get("success") is True and data.get("matches") == 1
            and len(matches) == 1 and matches[0].get("text") == expected)


def run(workspace: Path, output: Path | None = None, title: str = "Isolated OfficeCLI text task") -> dict:
    """Create/edit a new text-task.pptx; output is a new JSON receipt inside workspace."""
    try:
        development = ROOT / ".dev"
        original = Path(workspace)
        workspace = original.resolve(strict=True)
        if (development.resolve(strict=True) != development or original.is_symlink() or not workspace.is_dir()
                or not workspace.is_relative_to(development) or workspace == development):
            raise ValueError("Use an existing separate project .dev workspace")
    except (OSError, ValueError, TypeError) as error:
        raise OfficeWorkflowError("unsafe_workspace", str(error)) from error
    try:
        receipt_path = Path(output) if output is not None else Path("officecli-workflow-receipt.json")
        if not receipt_path.is_absolute():
            receipt_path = workspace / receipt_path
        if (receipt_path.suffix != ".json" or receipt_path.is_symlink()
                or receipt_path.resolve().parent != workspace):
            raise OfficeWorkflowError("unsafe_output", "Receipt must be a new local JSON file inside workspace")
        if receipt_path.exists():
            raise OfficeWorkflowError("receipt_exists", "Never overwrite a preexisting receipt")
    except (OSError, TypeError) as error:
        raise OfficeWorkflowError("unsafe_output", str(error)) from error
    filename = "text-task.pptx"
    path = workspace / filename
    report = {
        "schema_version": 1, "kind": "isolated_officecli_text_task",
        "observed_at": datetime.now(timezone.utc).isoformat(), "state": "running", "passed": False,
        "workspace": str(workspace), "receipt_path": str(receipt_path),
        "version": office.PINNED_VERSION, "binary_path": str(office.DEFAULT_BINARY), "binary_sha256": None,
        "actions": [], "errors": [], "checks": {}, "ooxml": {},
        "artifact": {"path": str(path), "sha256_before_edit": None, "sha256": None, "bytes": None},
        "protected_configurations_before": None, "protected_configurations_after": None,
        "cleanup": {"close_attempted": False, "close_succeeded": False},
        "retry_count": 0, "professional_design_quality": "not_claimed", "visual_review": "not_run",
        "P7": False, "installation_performed": False,
    }
    try:
        with receipt_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except OSError as error:
        raise OfficeWorkflowError("receipt_unwritable", str(error)) from error

    def save():
        try:
            receipt_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            report["passed"] = False
            report["state"] = "failed_evidence_retained"
            report["errors"].append(_error(error, "receipt_write"))
            failure = OfficeWorkflowError("receipt_unwritable", str(error))
            failure.receipt = report
            raise failure from error

    adapter = None
    new_target_admitted = False
    stage = "input"
    try:
        report["protected_configurations_before"] = office.protected_snapshot()
        if path.exists() or path.is_symlink():
            raise FileExistsError("Never use or overwrite a preexisting presentation")
        new_target_admitted = True
        if (not isinstance(title, str) or not title.strip() or len(title.encode("utf-8")) > 2048
                or any((ord(character) < 32 and character not in "\t\n\r")
                       or ord(character) in (65534, 65535) for character in title)
                or title in (BEFORE_TEXT, AFTER_TEXT)):
            raise ValueError("Title must be distinct, nonempty bounded XML-compatible text")
        stage = "initialize"
        report["binary_sha256"] = office.digest(office.DEFAULT_BINARY)
        adapter = _ObservedAdapter(workspace, report["actions"], save)
        if adapter.protected != report["protected_configurations_before"]:
            raise PermissionError("Protected configuration changed before task creation")
        stage = "create"
        adapter.create(filename)
        stage = "add"
        adapter.action("add", filename, "/", "--type", "slide", "--prop", f"title={title}")
        adapter.action("add", filename, "/slide[1]", "--type", "shape", "--prop", f"text={BEFORE_TEXT}",
                       "--prop", "x=2cm", "--prop", "y=4cm", "--prop", "width=22cm", "--prop", "height=3cm")
        stage = "independent_ooxml_before"
        before = inspect_text_pptx(path)
        report["ooxml"]["before"] = before
        matches = [index for index, text in enumerate(before["shape_texts"], 1) if text == BEFORE_TEXT]
        if not before["passed"] or len(matches) != 1 or title not in before["shape_texts"]:
            raise ValueError("Independent OOXML inspection cannot identify a unique native text target")
        target = f"/slide[1]/shape[{matches[0]}]"
        report["selector"] = target
        stage = "get_before"
        original = adapter.action("get", filename, target, "--json")
        report["checks"]["native_get_before_exact"] = _get_matches(original, BEFORE_TEXT)
        if not report["checks"]["native_get_before_exact"]:
            raise ValueError("Native get does not match the independently inspected text")
        report["artifact"]["sha256_before_edit"] = office.digest(path)
        stage = "set"
        adapter.action("set", filename, target, "--prop", f"text={AFTER_TEXT}")
        stage = "get_after"
        revised = adapter.action("get", filename, target, "--json")
        report["checks"]["native_get_after_exact"] = _get_matches(revised, AFTER_TEXT)
        if not report["checks"]["native_get_after_exact"]:
            raise ValueError("Native get does not confirm the exact revised text")
        stage = "view"
        outline = adapter.action("view", filename, "outline")
        report["checks"]["outline_contains_title"] = title in outline["stdout"]
    except Exception as error:
        report["errors"].append(_error(error, stage))
    finally:
        if adapter is not None and filename in adapter.owned:
            report["cleanup"]["close_attempted"] = True
            try:
                adapter.action("close", filename)
                report["cleanup"]["close_succeeded"] = True
            except Exception as error:
                report["errors"].append(_error(error, "close"))
        try:
            report["protected_configurations_after"] = office.protected_snapshot()
        except Exception as error:
            report["errors"].append(_error(error, "protected_snapshot_after"))
        if new_target_admitted and path.is_file() and not path.is_symlink():
            try:
                report["artifact"].update(sha256=office.digest(path), bytes=path.stat().st_size)
                after = inspect_text_pptx(path)
                report["ooxml"]["after"] = after
                before_texts = report["ooxml"].get("before", {}).get("shape_texts", [])
                report["checks"]["independent_ooxml_revision"] = (
                    after["passed"] and before_texts.count(BEFORE_TEXT) == 1
                    and after["shape_texts"].count(AFTER_TEXT) == 1 and title in after["shape_texts"]
                    and BEFORE_TEXT not in after["shape_texts"])
            except Exception as error:
                report["ooxml"]["after"] = {"passed": False, "error": _error(error, "independent_ooxml_after")}
                report["errors"].append(_error(error, "independent_ooxml_after"))
        actions = report["actions"]
        artifact = report["artifact"]
        report["checks"].update(
            required_command_sequence=[action["arguments"][0] for action in actions]
            == ["--version", "create", "add", "add", "get", "set", "get", "view", "close"],
            native_commands_succeeded=bool(actions) and all(action["exit_code"] == 0
                and action["owned_process_exit_observed"] and action["status"] == "completed" for action in actions),
            protected_configurations_unchanged=report["protected_configurations_before"] is not None
            and report["protected_configurations_after"] == report["protected_configurations_before"],
            artifact_hash_changed_on_edit=bool(artifact["sha256_before_edit"] and artifact["sha256"]
                                               and artifact["sha256_before_edit"] != artifact["sha256"]),
            target_close_succeeded=report["cleanup"]["close_succeeded"],
        )
        report["passed"] = not report["errors"] and all(report["checks"].values())
        report["state"] = "completed_bounded_task" if report["passed"] else "failed_evidence_retained"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="OfficeCLI task restricted to an existing project .dev workspace")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--output", type=Path, help="New JSON receipt inside workspace")
    parser.add_argument("--title", default="Isolated OfficeCLI text task")
    arguments = parser.parse_args()
    try:
        report = run(arguments.workspace, arguments.output, arguments.title)
    except OfficeWorkflowError as error:
        report = error.receipt
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
