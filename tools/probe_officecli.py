from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "adapters/p4/officecli_adapter.py"
    specification = importlib.util.spec_from_file_location("wuji4_office_adapter", source)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    workspace = ROOT / ".dev" / f"officecli-probe-{time.time_ns()}"
    workspace.mkdir()
    request = urllib.request.Request("https://api.github.com/repos/iOfficeAI/OfficeCLI/releases/tags/v1.0.152",
                                     headers={"User-Agent": "wuji4-read-only-research"})
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.loads(response.read(2 * 1024 * 1024))
    asset = next(asset for asset in release["assets"] if asset["name"] == "officecli-win-x64.exe")
    if asset["digest"] != "sha256:" + module.PINNED_SHA256:
        raise RuntimeError("Installed OfficeCLI hash does not match original release attestation")
    adapter = module.OfficeCliAdapter(workspace)
    adapter.create("editable-proof.pptx")
    adapter.action("add", "editable-proof.pptx", "/", "--type", "slide", "--prop", "title=Isolated OfficeCLI verification")
    adapter.action("add", "editable-proof.pptx", "/slide[1]", "--type", "shape", "--prop", "text=Editable native text before revision",
                   "--prop", "x=2cm", "--prop", "y=4cm", "--prop", "width=22cm", "--prop", "height=3cm")
    namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                 "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    with zipfile.ZipFile(workspace / "editable-proof.pptx") as archive:
        initial = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
    matches = [index for index, shape in enumerate(initial.findall(".//p:sp", namespace), 1)
               if "Editable native text before revision" in [element.text for element in shape.findall(".//a:t", namespace)]]
    if len(matches) != 1:
        raise RuntimeError("Actual editable target is absent or ambiguous; no guessed shape index")
    target = f"/slide[1]/shape[{matches[0]}]"
    original = adapter.action("get", "editable-proof.pptx", target, "--json")
    if "Editable native text before revision" not in original["stdout"]:
        raise RuntimeError("OfficeCLI selector does not name the exact inspected OOXML target")
    before = module.digest(workspace / "editable-proof.pptx")
    adapter.action("set", "editable-proof.pptx", target, "--prop", "text=Editable native text after revision")
    inspected = adapter.action("get", "editable-proof.pptx", target, "--json")
    outline = adapter.action("view", "editable-proof.pptx", "outline")
    rendered = adapter.action("view", "editable-proof.pptx", "html")
    closed = adapter.action("close", "editable-proof.pptx")
    path = workspace / "editable-proof.pptx"
    with zipfile.ZipFile(path) as archive:
        slide = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
        namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                     "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
        texts = [element.text for element in slide.findall(".//a:t", namespace)]
        native_shapes = len(slide.findall(".//p:sp", namespace))
    output = ROOT / "outputs/p4/officecli"
    output.mkdir(exist_ok=True)
    copied = output / "editable-proof.pptx"
    if copied.exists():
        copied = output / f"editable-proof-{time.time_ns()}.pptx"
    shutil.copy2(path, copied)
    html = copied.with_suffix(".html")
    html.write_text(rendered["stdout"], encoding="utf-8")
    checks = {"binary_matches_original_release": True, "actual_version_pinned": True,
              "native_editable_shapes": native_shapes >= 1,
              "actual_text_revision_present": "Editable native text after revision" in texts,
              "old_text_removed": "Editable native text before revision" not in texts,
              "file_hash_changes_on_edit": before != module.digest(path),
              "native_get_after_edit": "Editable native text after revision" in inspected["stdout"],
              "outline_contains_actual_slide_title": "Isolated OfficeCLI verification" in outline["stdout"],
              "actual_html_export": "Editable native text after revision" in rendered["stdout"] and "<" in rendered["stdout"],
              "target_close_succeeded": closed["exit_code"] == 0,
              "configurations_unchanged": module.protected_snapshot() == adapter.protected}
    report = {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
              "kind": "real_officecli_bounded_editable_artifact", "checks": checks,
              "passed": all(checks.values()), "version": module.PINNED_VERSION,
              "original_source": "https://github.com/iOfficeAI/OfficeCLI", "license": "Apache-2.0",
              "source_release": release["html_url"], "source_published_at": release["published_at"],
              "binary_path": str(adapter.binary), "binary_sha256": module.PINNED_SHA256,
              "latest_observed": "1.0.153", "adopted_exception": "Reuse verified existing 1.0.152; no installation, self-update or global skill/configuration changes",
              "adapter_sha256": module.digest(source), "entrypoint": "explicit existing EXE path; no PATH change",
              "artifact": {"path": copied.relative_to(ROOT).as_posix(), "sha256": module.digest(copied),
                           "bytes": copied.stat().st_size, "native_editable_shapes": native_shapes},
              "html_export": {"path": html.relative_to(ROOT).as_posix(), "sha256": module.digest(html)},
              "protected_configurations_before": adapter.protected,
              "protected_configurations_after": module.protected_snapshot(), "actions": adapter.receipts,
              "professional_design_quality": "not_claimed", "browser_visual_holdout": "not_run",
              "outline_scope": "Native outline lists slide titles and counts, not all body text; body content independently checked by get/HTML/OOXML",
              "P7": False, "installation_performed": False, "shutdown": False}
    (ROOT / "outputs/p4/officecli-probe-evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks, "artifact": report["artifact"]}, ensure_ascii=False))
    if not report["passed"]:
        raise RuntimeError("OfficeCLI bounded acceptance has a failed criterion; evidence retained")


if __name__ == "__main__":
    main()
