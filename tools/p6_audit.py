from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONFIG_HASH = "f37efee8358d33ff6b848a6c207b974c501dde0d548a7cfe4d4b052cd1d6e4fc"
CONFIG = Path("C:/Users/Administrator/.codex/config.toml")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def package_consistency(release_manifest: dict) -> dict[str, object]:
    from p6_package_validation import package_consistency as validate_package
    return validate_package(ROOT, release_manifest)


def main() -> None:
    from datetime import datetime, timedelta, timezone
    from p6_acceptance import evaluate
    from build_p3_catalog import quality_current
    from execution_baseline import load_active, frozen_observation
    core_cutover = load("outputs/p7/global-4-only-cutover-2026-10-05.json")
    active = load_active(ROOT)
    gates = load("docs/phase-gates.json")
    p2 = load("outputs/p2/native-real-execution-report-2026-10-03.json")
    p3 = load("outputs/p3/p3-quality-report.json")
    p4 = load("catalog/p4/tool-manifests.json")
    p5 = load("outputs/p5/p5-governance-report.json")
    release_manifest = load("outputs/p6/release-manifest.json")
    baseline = load("docs/design-baseline-1.json")
    receipt = load("outputs/p6/test-execution.json")
    acceptance = evaluate(ROOT, load("docs/acceptance-map.json"), receipt)
    from refresh_continuation_report import current_core_projection
    core_projection = current_core_projection(ROOT)
    package = package_consistency(release_manifest)
    frozen = []
    for entry in baseline["files"]:
        frozen.append(frozen_observation(ROOT, entry, active))
    blocked_tools = [tool["id"] for tool in p4["tools"] if tool["status"] == "blocked"]
    current_config_hash = sha256(CONFIG) if CONFIG.is_file() else None
    protection = receipt.get("configuration", {})
    config_preserved = (
        current_config_hash is not None and protection.get("unchanged_during_run") is True
        and protection.get("before", {}).get("sha256") == current_config_hash
        and protection.get("after", {}).get("sha256") == current_config_hash
    )
    summary = acceptance["summary"]
    report = {
        "schema_version": 1, "release": "p6-audit-2", "phase": "P6",
        "status": "in_progress_internal_work_and_explicit_external_limits",
        "scope": "full_capability_acceptance_not_core_entry_readiness",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "date": str(datetime.now(timezone(timedelta(hours=8))).date()),
        "checks": {
            "g2_historical_native_bounded_acceptance": gates["gates"]["G2"]["status"] == "passed" and p2["acceptance"]["g2_closed"] is True,
            "g3_cold_catalog": gates["gates"]["G3"]["status"] == "passed" and quality_current(ROOT,p3),
            "g4_full_professional_acceptance": gates["gates"]["G4"]["status"] == "passed",
            "g5_governance_core": gates["gates"]["G5"].get("deterministic_governance_core_passed") is True and p5["passed"] is True and acceptance["evidence_valid"],
            "g5_full_scope_acceptance": all(row["status"] == "passed" for row in acceptance["matrix"] if row["gate"] == "G5"),
            "rust_full_tests": acceptance["checks"]["rust_command_passed"] and acceptance["evidence_valid"],
            "python_full_tests": acceptance["checks"]["python_suite_passed"] and acceptance["evidence_valid"],
            "test_execution_evidence_current": acceptance["evidence_valid"],
            "p6_package_consistency": package["passed"],
            "active_execution_baseline_current": active["version"] == "1.7",
            "frozen_p1_history_preserved_and_authorized_supersession": all(item["preserved"] for item in frozen),
            "current_codex_config_unchanged_during_run": config_preserved,
            "effective_model_effort_quota_fee_attested": gates["gates"]["G2"].get("native_host_verified") is True and not gates["gates"]["G2"].get("unknowns"),
            "g6_required_scenarios_passed": summary["g6_scenarios_passed"],
            "p7_not_performed": gates["P7"] is False,
            "shutdown_not_performed": gates["shutdown"] is False,
            "core_4_only_cutover_recorded": core_cutover["status"] == "global_entry_cutover_verified",
            "legacy_global_mount_retired": not Path(core_cutover["legacy"]["global_mount_removed"]).exists(),
        },
        "acceptance_matrix": {
            "total": summary["total"], "verification_status_counts": summary["status_counts"],
            "passed": summary["passed_for_g6"], "required_for_g6": summary["required_for_g6"],
            "not_run_or_pending": summary["required_for_g6"] - summary["passed_for_g6"],
            "deferred_p7": summary["status_counts"].get("deferred_p7", 0),
            "scope": "95 frozen scenarios retained; 92 G6 scenarios and 3 separately authorized G7 scenarios. Partial/blocked/deferred are not passed.",
        },
        "test_counts": {"rust_passed": receipt["rust"]["tests_passed"], "python_run": receipt["python"]["tests_run"]},
        "configuration_protection": {
            "scope": "historical_full_suite_receipt_not_current_core_supplement",
            "current_sha256": current_config_hash, "unchanged_during_this_run": config_preserved,
            "historical_expected_sha256": EXPECTED_CONFIG_HASH,
            "matches_historical_baseline": current_config_hash == EXPECTED_CONFIG_HASH,
            "historical_difference_actor": "unknown", "content_exported": False,
            "restored_or_modified_by_this_audit": False,
        },
        "active_execution_baseline": {key: active[key] for key in ("version", "plan", "sha256")},
        "core_entry": {
            "status": core_cutover["status"],
            "cutover_record": "outputs/p7/global-4-only-cutover-2026-10-05.json",
            "full_capability_acceptance_is_separate": True,
            "peripheral_validation": "deferred_until_a_real_task_requires_it",
        },
        "current_core_supplement": core_projection,
        "frozen_files": frozen, "blocked_tools": blocked_tools,
        "remaining_required_evidence": [
            "Matched professional image/video/audio holdouts and editable project workflows",
            "Office workflows beyond the verified bounded text-PPTX and XLSX structural chain, including approved DOCX rendering and professional document/design effectiveness",
            "REAPER isolated offline project/reopen/render and microphone protection evidence",
            "Effective backend model/effort/quota/fee attestations",
            "Remaining 92-scope G6 acceptance scenarios; 3 G7 scenarios remain separately authorized",
        ],
        "reports": {
            "g2": "outputs/p2/native-real-execution-report-2026-10-03.json",
            "g3": "outputs/p3/p3-quality-report.json", "g4": "catalog/p4/tool-manifests.json",
            "g5": "outputs/p5/p5-governance-report.json",
            "rust_tests": "outputs/p6/rust-full-tests.log", "python_tests": "outputs/p6/python-tool-tests.log",
            "test_execution": "outputs/p6/test-execution.json", "acceptance_execution": "outputs/p6/acceptance-execution.json",
            "release_manifest": "outputs/p6/release-manifest.json", "package": "outputs/p6/wuji-legion-4.0-p6-package.zip",
            "evidence_crosswalk": "outputs/p6/evidence-crosswalk.json",
        },
        "package_consistency": package, "production_modified_by_this_run": False,
        "archive_attestation": {
            "external_to_archive": True,
            "archive_path": release_manifest["archive"]["path"],
            "declared_archive_sha256": release_manifest["archive"]["sha256"],
            "observed_archive_sha256": sha256(ROOT / release_manifest["archive"]["path"]),
            "sidecar_path": "outputs/p6/release-manifest.json",
            "sidecar_sha256": sha256(ROOT / "outputs/p6/release-manifest.json"),
            "audit_does_not_mutate_declared_archive_files": True,
        },
        "P7": False, "shutdown": False,
    }
    report["passed"] = all(report["checks"].values()) and not blocked_tools
    if report["passed"]:
        report["status"] = "passed_p0_p6_not_installed"
    elif core_projection["closeout"]["core_closeout_complete"]:
        report["status"] = "current_core_complete_full_capability_acceptance_pending"
    (ROOT / "outputs/p6/full-audit-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "passed": report["passed"], "checks": report["checks"], "acceptance": report["acceptance_matrix"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

