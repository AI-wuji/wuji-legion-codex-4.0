"""P0 PDF extraction/render evidence; never marks documents read automatically."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from preflight import ROOT, SOURCES, digest, is_link, stamp, write_json

REPORT_ROOT = ROOT / "outputs/p0/documents"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_PAGES = 1000


def reconcile_reading(report: dict, report_path: Path) -> dict:
    """Derive page coverage from explicit acknowledgements and retained image hashes."""
    covered = set()
    for record in report.get("reading_records", []):
        number = record.get("page")
        if (not isinstance(number, int) or not 1 <= number <= report["page_count"]
                or record.get("source_sha256") != report["source_sha256"]
                or record.get("kind") != "explicit_visual_reviewer_acknowledgement"
                or not record.get("note", "").strip()):
            continue
        image = report_path.parent / f"page-{number:04}.png"
        if image.is_file() and not any(is_link(item) for item in [image, *image.parents]):
            if digest(image) == record.get("render_sha256"):
                covered.add(number)
    for page in report["pages"]:
        page["read_status"] = ("visual_reviewed" if page["page"] in covered
                               else "extracted_not_read")
    complete = len(covered) == report["page_count"] and report["page_count"] > 0
    report["status"] = ("visual_review_complete" if complete else
                        "visual_review_partial" if covered else "extracted_not_read")
    report["reading_summary"] = {
        "scope": "Rendered PDF pages only; external links, embedded media and template assets are separate.",
        "reviewed_pages": sorted(covered),
        "missing_pages": sorted(set(range(1, report["page_count"] + 1)) - covered),
        "complete": complete,
    }
    return report


def checked_source(path: Path) -> Path:
    path = path.absolute()
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise ValueError("expected an existing source PDF")
    if any(is_link(parent) for parent in [path, *path.parents]):
        raise ValueError("source links/reparse points are not followed")
    resolved = path.resolve()
    if not any(root.is_dir() and resolved.is_relative_to(root.resolve())
               for root in SOURCES.values()):
        raise ValueError("PDF is outside approved material roots")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("source size exceeds bounded PDF audit; select a scoped workflow")
    return resolved


def source_key(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:20]


def inspect_pdf(path: Path) -> dict:
    from pypdf import PdfReader
    path = checked_source(path)
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    source_hash = digest(path)
    reader = PdfReader(str(path), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted source requires a separate authorized reading workflow")
    if len(reader.pages) > MAX_PAGES:
        raise ValueError("page budget exceeded")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        resources = page.get("/Resources")
        resources = resources.get_object() if resources else {}
        xobjects = resources.get("/XObject")
        xobjects = xobjects.get_object() if xobjects else {}
        subtypes = [str(value.get_object().get("/Subtype", "unknown"))
                    for value in xobjects.values()]
        pages.append({"page": number, "text": text, "text_chars": len(text.strip()),
                      "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                      "xobject_subtypes": subtypes,
                      "visual_review_required": bool(xobjects) or len(text.strip()) < 80,
                      "read_status": "extracted_not_read"})
    if before != (path.stat().st_size, path.stat().st_mtime_ns):
        raise ValueError("source changed during extraction")
    report = {"schema_version": 1, "source": str(path), "source_sha256": source_hash,
              "observed_at": stamp(), "page_count": len(pages), "pages": pages,
              "reading_records": [], "status": "extracted_not_read", "G0": "not_passed",
              "boundary": "Text extraction and PNG rendering do not acknowledge reading."}
    report_path = REPORT_ROOT / source_key(path) / "extraction.json"
    if report_path.exists():
        prior = json.loads(report_path.read_text(encoding="utf-8"))
        if prior.get("source_sha256") == source_hash:
            report["reading_records"] = prior.get("reading_records", [])
        else:
            report["invalidated_reading_records"] = prior.get("reading_records", [])
    reconcile_reading(report, report_path)
    write_json(report_path, report)
    return report


def report_for(path: Path) -> tuple[dict, Path]:
    path = checked_source(path)
    output = REPORT_ROOT / source_key(path) / "extraction.json"
    if not output.exists():
        raise ValueError("inspect source before reading or rendering")
    report = json.loads(output.read_text(encoding="utf-8"))
    if digest(path) != report["source_sha256"]:
        raise ValueError("source hash changed; inspection and review must be refreshed")
    return report, output


def selected_page(report: dict, number: int) -> dict:
    if not 1 <= number <= report["page_count"]:
        raise ValueError("page number outside source")
    return report["pages"][number - 1]


def render_page(path: Path, number: int) -> dict:
    report, report_path = report_for(path)
    selected_page(report, number)
    executable = shutil.which("pdftoppm")
    if not executable:
        raise ValueError("bundled Poppler pdftoppm is unavailable; do not pretend rendered")
    prefix = report_path.parent / f"page-{number:04}"
    result = subprocess.run([executable, "-f", str(number), "-l", str(number),
                             "-singlefile", "-scale-to", "1800", "-png",
                             str(path.resolve()), str(prefix)], capture_output=True,
                            timeout=45, check=False)
    image = prefix.with_suffix(".png")
    if result.returncode or not image.is_file():
        raise ValueError(f"page render failed (exit {result.returncode})")
    from PIL import Image
    with Image.open(image) as decoded:
        decoded.verify()
    if digest(checked_source(path)) != report["source_sha256"]:
        raise ValueError("source changed during render")
    receipt = {"source_sha256": report["source_sha256"], "page": number,
               "image": str(image), "image_sha256": digest(image),
               "status": "rendered_not_reviewed", "observed_at": stamp()}
    write_json(prefix.with_suffix(".json"), receipt)
    return receipt


def record_visual(path: Path, page: int, source_hash: str, image_hash: str, note: str) -> dict:
    report, report_path = report_for(path)
    selected_page(report, page)
    prefix = report_path.parent / f"page-{page:04}"
    receipt = json.loads(prefix.with_suffix(".json").read_text(encoding="utf-8"))
    if (source_hash != report["source_sha256"] or source_hash != receipt["source_sha256"]
            or image_hash != receipt["image_sha256"]
            or digest(prefix.with_suffix(".png")) != image_hash or not note.strip()):
        raise ValueError("review acknowledgement is stale or missing concrete findings")
    report["reading_records"].append({"page": page, "source_sha256": source_hash,
        "render_sha256": image_hash, "note": note.strip(), "recorded_at": stamp(),
        "kind": "explicit_visual_reviewer_acknowledgement"})
    reconcile_reading(report, report_path)
    write_json(report_path, report)
    return {"page": page, "status": "visual-review-recorded", "G0": "not_passed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "read", "render", "record-visual"])
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--page", type=int)
    parser.add_argument("--source-sha256")
    parser.add_argument("--image-sha256")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    if args.command == "inspect":
        result = inspect_pdf(args.path)
        print(json.dumps({"source": result["source"],
                          "source_sha256": result["source_sha256"],
                          "page_count": result["page_count"], "status": result["status"],
                          "reading_summary": result["reading_summary"], "G0": result["G0"]},
                         ensure_ascii=False))
        return
    if args.page is None:
        parser.error("--page is required")
    if args.command == "read":
        report, _ = report_for(args.path)
        print(json.dumps(selected_page(report, args.page), ensure_ascii=False))
    elif args.command == "render":
        print(json.dumps(render_page(args.path, args.page), ensure_ascii=False))
    else:
        print(json.dumps(record_visual(args.path, args.page, args.source_sha256,
                                       args.image_sha256, args.note), ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
