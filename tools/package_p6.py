from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from p6_package_validation import EXTERNAL_ARCHIVE_ATTESTATIONS, confined_path, manifest_file_entries, package_consistency, strict_json, validate_package_file_path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "outputs/p6/release-manifest.json"
PACKAGE_PATH = ROOT / "outputs/p6/wuji-legion-4.0-p6-package.zip"
AUDIT_REPORT_PATH = ROOT / "outputs/p6/full-audit-report.json"
STAGING_PATH = ROOT / "release/p6"
SOURCE_PATH_MIGRATIONS = {
    "docs/design-deltas/026-budget-semantics-and-gpt-6.1-sol-context-correction-2026-10-06.md":
        "docs/design-deltas/026-budget-semantics-and-gpt-6.1-sol-context-correction-2026-10-05.md",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retained_manifest_entries(previous: dict) -> list[dict[str, object]]:
    retained = []
    paths = {}
    for entry in previous["files"]:
        if entry["path"].casefold() in EXTERNAL_ARCHIVE_ATTESTATIONS:
            continue
        current_path = SOURCE_PATH_MIGRATIONS.get(entry["path"], entry["path"])
        if current_path in paths:
            previous_path = paths[current_path]
            if previous_path != entry["path"] and (previous_path in SOURCE_PATH_MIGRATIONS or entry["path"] in SOURCE_PATH_MIGRATIONS):
                continue
            raise ValueError("Duplicate retained package source path")
        paths[current_path] = entry["path"]
        retained.append(dict(entry, path=current_path))
    return retained


def manifest_files() -> list[dict[str, object]]:
    previous = strict_json(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = retained_manifest_entries(previous)
    listed_paths = {entry["path"] for entry in entries}
    for path in (
        "tools/package_p6.py",
        "tools/test_p6_package.py",
        "tools/build_p6_evidence_crosswalk.py",
        "docs/progress.md",
        "outputs/p6/evidence-crosswalk.json",
        "outputs/p4/comfyui-probe-evidence.json",
        "outputs/p4/comfyui-probe-output.png",
        "outputs/p4/ffmpeg-probe-evidence.json",
        "outputs/p4/ffmpeg-probe-video.mp4",
        "tools/p6_package_validation.py",
        "tools/test_p6_package_validation.py",
        "tools/p6_acceptance.py",
        "tools/test_p6_acceptance.py",
        "tools/run_p6_regressions.py",
        "tools/run_audit_tests.py",
        "tools/test_regression_scope.py",
        "docs/current-acceptance-status-2026-10-07.md",
        "docs/core-only-closeout-2026-10-07.md",
        "tools/test_cli_help.py",
        "outputs/p6/test-execution.json",
        "outputs/p6/acceptance-execution.json",
        "outputs/p6/rust-full-tests.log",
        "outputs/p6/python-tool-tests.log",
        "outputs/p6/continuation-2026-10-06/core-completion-execution.json",
        "outputs/p6/continuation-2026-10-06/core-completion-rust.log",
        "outputs/p6/continuation-2026-10-06/core-completion-python.log",
        "outputs/p6/continuation-2026-10-06/remaining-48-execution.json",
        "outputs/p6/continuation-2026-10-06/failed-missing-artifact-repair/core-completion-execution.json",
        "outputs/p6/continuation-2026-10-06/failed-missing-artifact-repair/core-completion-rust.log",
        "outputs/p6/continuation-2026-10-06/failed-missing-artifact-repair/core-completion-python.log",
        "outputs/p6/continuation-2026-10-04/parallel-workers-report.json",
        "outputs/p4/tool-discovery-2026-10-04.json",
        "outputs/p4/officecli-probe-evidence.json",
        "outputs/p4/officecli-framework-workflow-evidence.json",
        "outputs/p4/office-document-workflow-evidence.json",
        "outputs/p4/office-documents/sheet-output.xlsx",
        "outputs/p4/office-documents/word-output.docx",
        "outputs/p4/office-documents/sheet-receipt.json",
        "outputs/p4/office-documents/word-receipt.json",
        "outputs/p4/office-documents/sheet-framework-output.json",
        "outputs/p4/office-documents/word-framework-output.json",
        "outputs/p4/media-framework-failure-evidence.json",
        "outputs/p4/media-contract-probe-evidence.json",
        "outputs/p4/video-framework-workflow-evidence.json",
        "outputs/p4/video-framework-output.mp4",
        "outputs/p4/history/video-before-reviewed-binding.json",
        "outputs/p4/history/video-before-reviewed-binding.mp4",
        "outputs/p7/research/codex-skills.html",
        "outputs/p7/research/windows-shutdown.html",
        "AGENTS.md",
        "outputs/p7/global-entry-state-2026-10-05.json",
        "outputs/p7/core-skill-install-record-2026-10-05.json",
        "outputs/p7/global-4-only-cutover-2026-10-05.json",
        "outputs/p7/global-4-only-regression-2026-10-05.log",
        "outputs/p6/remaining-work.json",
        "outputs/p0/primary-method-snapshots/STD-FFMPEG-IMAGE2.html",
        "outputs/p6/continuation-2026-10-05/test-execution-failed-release-cycle.json",
        "outputs/p6/continuation-2026-10-05/python-failed-release-cycle.log",
        "outputs/p6/continuation-2026-10-05/acceptance-before-coverage-review.json",
        "outputs/p0/primary-method-snapshots/STD-RUST-PATHBUF.html",
        "outputs/p0/primary-method-snapshots/STD-RUST-I128.html",
        "outputs/p6/selector-workflow-evidence.json",
        "outputs/p1/plan-1.7-review.json",
        "outputs/p2/legion-first-task-receipt.json",
        "outputs/p2/legion-first-task-current-recheck.json",
        "outputs/p2/framework-doctor-current.json",
        "outputs/p2/framework-capabilities-current.json",
        "outputs/p2/legion-first-task-source.txt",
        "outputs/p2/legion-first-task-result.txt",
        "outputs/p5/legion-experience-task-receipt.json",
        "outputs/p5/experience-workflow-evidence.json",
        "outputs/p2/prepared-role-source-refresh.json",
        "outputs/p2/catalog-history/engineering-revision-2.json",
        "outputs/p2/catalog-history/validation-revision-2.json",
        "outputs/p6/continuation-2026-10-04/local-parallel-repair-report.json",
        "outputs/p6/continuation-2026-10-04/test-execution-failed-clock-collision.json",
        "outputs/p6/continuation-2026-10-04/rust-full-tests-failed-clock-collision.log",
    ):
        if path not in listed_paths:
            entries.append({"path": path})
            listed_paths.add(path)
    office_proof = ROOT / "outputs/p4/officecli-probe-evidence.json"
    if office_proof.is_file():
        office_evidence = strict_json(office_proof.read_text(encoding="utf-8"))
        for artifact in (office_evidence["artifact"], office_evidence["html_export"]):
            path = validate_package_file_path(artifact["path"])
            if path not in listed_paths:
                entries.append({"path": path})
                listed_paths.add(path)
    media_proof = ROOT / "outputs/p4/media-contract-probe-evidence.json"
    if media_proof.is_file():
        for artifact in strict_json(media_proof.read_text(encoding="utf-8"))["artifacts"]:
            path = validate_package_file_path(artifact["path"])
            if path not in listed_paths:
                entries.append({"path": path})
                listed_paths.add(path)
    for directory, suffixes in (("src", {".rs", ".sql"}), ("schemas", {".json"}),
                                ("catalog", {".json"}), ("adapters", {".py", ".json"}),
                                ("tests", {".rs"}), ("tools", {".py", ".ps1", ".rs", ".toml", ".lock"}),
                                ("docs", {".md", ".json", ".tsv"}), ("legion", {".md", ".json"})):
        for source in sorted((ROOT / directory).rglob("*")):
            if source.is_file() and source.suffix in suffixes:
                relative = source.relative_to(ROOT).as_posix()
                if relative not in listed_paths:
                    validate_package_file_path(relative)
                    entries.append({"path": relative})
                    listed_paths.add(relative)
    files = []
    for entry in entries:
        relative = validate_package_file_path(entry["path"])
        source = confined_path(ROOT, relative)
        if not source.is_file():
            raise FileNotFoundError(relative)
        files.append(
            {
                "path": entry["path"],
                "bytes": source.stat().st_size,
                "sha256": sha256(source),
            }
        )
    files = sorted(files, key=lambda entry: str(entry["path"]))
    manifest_file_entries(files, PACKAGE_PATH.relative_to(ROOT).as_posix())
    return files


def base_manifest(files: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "release": "p6-local-package-5",
        "phase": "P6",
        "status": "local_package_created_not_installed",
        "baseline": {
            "path": "docs/design-baseline-1.json",
            "id": "baseline-1.1",
        },
        "files": files,
        "archive": {
            "path": "outputs/p6/wuji-legion-4.0-p6-package.zip",
            "sha256": None,
            "verification": "external-sidecar",
        },
        "install_authorized": False,
        "production_modified": False,
        "external_archive_attestations": sorted(EXTERNAL_ARCHIVE_ATTESTATIONS),
        "source_path_migrations": SOURCE_PATH_MIGRATIONS,
        "p7": False,
        "limitations": [
            "G4 incomplete: some professional adapters/holdouts remain unimplemented; specific external limits are separately recorded",
            "G6 blocked while its 92 required scenarios remain incomplete; 3 G7 scenarios need separate authorization",
            "effective backend/model/quota/fee attestations remain unknown",
        ],
    }


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_external_archive_attestation(archive_hash: str, manifest_hash: str) -> None:
    previous_bytes = AUDIT_REPORT_PATH.read_bytes()
    previous = strict_json(previous_bytes.decode("utf-8"))
    attestation = previous.get("archive_attestation")
    if not isinstance(attestation, dict) or attestation.get("external_to_archive") is not True:
        raise ValueError("External archive attestation is missing or not external")
    if sha256(PACKAGE_PATH) != archive_hash or sha256(MANIFEST_PATH) != manifest_hash:
        raise ValueError("Archive or sidecar changed before external attestation")
    previous_hash = hashlib.sha256(previous_bytes).hexdigest()
    history = confined_path(ROOT, f".dev/package-attestations/{previous_hash}.json")
    history.parent.mkdir(parents=True, exist_ok=True)
    if history.exists() and history.read_bytes() != previous_bytes:
        raise ValueError("Historical audit preservation conflicts")
    history.write_bytes(previous_bytes)
    report = {
        "schema_version": 1, "kind": "external_archive_identity_only",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "archive_identity_checked_full_acceptance_pending",
        "full_audit_reexecuted": False, "passed": False,
        "historical_audit": {"path": history.relative_to(ROOT).as_posix(), "sha256": previous_hash},
        "archive_attestation": {
            "external_to_archive": True,
            "archive_path": PACKAGE_PATH.relative_to(ROOT).as_posix(),
            "declared_archive_sha256": archive_hash,
            "observed_archive_sha256": archive_hash,
            "sidecar_path": MANIFEST_PATH.relative_to(ROOT).as_posix(),
            "sidecar_sha256": manifest_hash,
            "audit_does_not_mutate_declared_archive_files": True,
        },
    }
    write_json(AUDIT_REPORT_PATH, report)


def write_deterministic_zip(stage: Path) -> None:
    PACKAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(PACKAGE_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in sorted(stage.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, source.read_bytes())


def main() -> None:
    for destination in (MANIFEST_PATH, PACKAGE_PATH, STAGING_PATH):
        confined_path(ROOT, destination.relative_to(ROOT).as_posix())
    files = manifest_files()
    embedded = base_manifest(files)
    external = json.loads(json.dumps(embedded))

    development = confined_path(ROOT, ".dev")
    with tempfile.TemporaryDirectory(prefix="p6-package-", dir=development) as temporary:
        Path(temporary).resolve().relative_to(development.resolve())
        stage = Path(temporary) / "p6"
        stage.mkdir(parents=True)
        for entry in files:
            relative = Path(str(entry["path"]))
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(confined_path(ROOT, entry["path"]), destination)
        write_json(stage / "outputs/p6/release-manifest.json", embedded)
        write_deterministic_zip(stage.parent)

    archive_hash = sha256(PACKAGE_PATH)
    external["archive"] = {
        "path": "outputs/p6/wuji-legion-4.0-p6-package.zip",
        "sha256": archive_hash,
        "verification": "external-sidecar",
    }
    external["embedded_manifest"] = {
        "path": "p6/outputs/p6/release-manifest.json",
        "archive_sha256": None,
        "archive_hash_scope": "external-sidecar",
    }
    consistency = package_consistency(ROOT, external)
    if not consistency["passed"]:
        raise ValueError(f"New package consistency failed: {consistency}")
    write_json(MANIFEST_PATH, external)
    update_external_archive_attestation(archive_hash, sha256(MANIFEST_PATH))

    STAGING_PATH.mkdir(parents=True, exist_ok=True)
    for relative in EXTERNAL_ARCHIVE_ATTESTATIONS:
        stale_attestation = confined_path(ROOT, (STAGING_PATH / relative).relative_to(ROOT).as_posix())
        stale_attestation.unlink(missing_ok=True)
    for entry in files:
        relative = Path(str(entry["path"]))
        destination = confined_path(ROOT, (STAGING_PATH / relative).relative_to(ROOT).as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(confined_path(ROOT, entry["path"]), destination)
    write_json(STAGING_PATH / "outputs/p6/release-manifest.json", embedded)

    print(
        json.dumps(
            {
                "package": str(PACKAGE_PATH.relative_to(ROOT)),
                "package_sha256": archive_hash,
                "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
                "embedded_manifest_archive_sha256": None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
