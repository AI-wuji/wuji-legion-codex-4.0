from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from p6_acceptance import digest, evaluate, semantic_cases
from p6_package_validation import confined_path, strict_json


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/p6/evidence-crosswalk.json"
DEFAULT_RECEIPT = "outputs/p6/test-execution.json"
CANDIDATE_LEDGER = "outputs/p0/atom-evidence-ledger.json"
BINDING_DELTA = "docs/design-deltas/027-core-completion-rework-owner-evidence-2026-10-06.md"
BINDING_DEFINITIONS = (
    {
        "candidate_id": "D08", "name": "无进展停止判定",
        "implementation_files": ["src/revisions.rs"],
        "case_sources": ["src/store_product_tests.rs"], "scenario_ids": ["T19"],
        "actual_cases": {"rust": [
            "store::tests::t19_pinned_no_progress_cap_stops_rework_before_mutation_and_survives_reopen",
            "store::tests::t19_real_validation_resets_consecutive_guard_but_not_aggregate_revision_budget",
            "store::tests::t19_repair_cap_is_per_defect_node_and_cannot_reset_through_event_names",
        ]},
        "scope": "Finite evidenced local repair: per-defect cap, no-progress guard and non-resettable aggregate budget.",
        "unverified_scope": "Model/professional repair and all-consumer/domain/global promotion.",
    },
    {
        "candidate_id": "J08", "name": "返工归属精确选择",
        "implementation_files": ["src/revisions.rs"],
        "case_sources": ["src/store_product_tests.rs"], "scenario_ids": ["T19"],
        "actual_cases": {"rust": [
            "store::tests::t19_actual_defect_has_file_evidence_and_bounded_independently_verified_repair",
            "store::tests::t19_two_independent_defects_can_be_repaired_without_unrelated_rework",
            "store::tests::t19_clean_review_does_not_invent_three_findings_or_repeat_dispatch",
        ]},
        "scope": "repair_local_plan targets evidenced defect nodes and successors, preserving unrelated work.",
        "unverified_scope": "Native expert reassignment, every workflow and professional effectiveness.",
    },
    *({
        "candidate_id": identifier, "name": name,
        "implementation_files": ["src/local_identity.rs", "src/resources.rs", "src/transfers.rs", "src/received.rs"],
        "case_sources": ["tests/p6_resource_acl.rs", "src/local_identity.rs"], "scenario_ids": ["T22"],
        "actual_cases": {"rust": semantic_cases("T22")},
        "scope": scope,
        "unverified_scope": "OS DACL enforcement, administrator/same-SID database tampering, non-Windows identity, multi-tenant service and public/global admission.",
    } for identifier, name, scope in (
        ("B01", "数据scope适配判定", "Windows single-owner project/root/scope checks for resource use and transfer/received replay; no private cross-project reuse."),
        ("B02", "读取权检查", "Current SID and live owner enable state gate local resource queries, including already-open Stores and replay."),
        ("B03", "动作授权适配", "Local resource proposal/review/retirement/transfer consumption requires current owner authority; JSON owner/token fields do not grant it. No payment/sending/tool permission is granted."),
    )),
    {
        "candidate_id": "G02", "name": "内容完整性核验",
        "implementation_files": ["src/store.rs", "src/revisions.rs"],
        "case_sources": ["src/store_product_tests.rs"], "scenario_ids": ["T19"],
        "actual_cases": {"rust": [
            "store::tests::t19_actual_defect_has_file_evidence_and_bounded_independently_verified_repair",
            "store::tests::t19_lost_artifact_can_be_repaired_at_original_path_without_invented_spec_change",
        ]},
        "scope": "Independent current file-byte/hash validation after T19 repair, including original-path regeneration and preserved invalidated history.",
        "unverified_scope": "Integrity is not authority or truth; no current installed-seven-file observation, all-package or professional acceptance is inferred.",
    },
    {
        "candidate_id": "C08", "name": "完成声明资格检查",
        "implementation_files": ["tools/refresh_continuation_report.py", "tools/p6_acceptance.py"],
        "case_sources": ["tools/test_p6_acceptance.py"], "scenario_ids": ["T19", "T22"],
        "actual_cases": {"python": [
            "test_p6_acceptance.P6AcceptanceTests.test_closeout_does_not_stop_on_report_generation_or_historical_passes",
        ]},
        "scope": "core_closeout_state rejects stale/partial T19/T22 evidence and mismatching core deployment; generating a report is not completion.",
        "unverified_scope": "This verifies the local completion guard, not actual present deployment, independent new-chat behavior, full professional completion or G7.",
    },
)


def source_evidence(root: Path, receipt: dict, relative: str) -> dict:
    expected = receipt.get("source_hashes", {}).get(relative)
    after = receipt.get("source_hashes_after", {}).get(relative)
    try:
        path = confined_path(root, relative)
        current = isinstance(expected, str) and expected == after and path.is_file() and digest(path) == expected
    except (OSError, ValueError):
        current = False
    return {"path": relative, "receipt_sha256": expected, "current": current}


def candidate_source_evidence(root: Path, receipt: dict, candidate: dict) -> dict:
    source = candidate.get("approved_source", {})
    if not isinstance(source, dict):
        return {"path": None, "current": False}
    try:
        value = source["path"]
        path = Path(value)
        relative = path.relative_to(root.resolve()).as_posix() if path.is_absolute() else value
        evidence = source_evidence(root, receipt, relative)
        evidence.update(candidate_sha256=source.get("sha256"), line=source.get("line"))
        evidence["current"] = evidence["current"] and evidence["receipt_sha256"] == source.get("sha256")
        return evidence
    except (KeyError, TypeError, ValueError):
        return {"path": source.get("path"), "current": False}


def current_consumer_bindings(root: Path, receipt: dict, execution: dict, receipt_path: str) -> tuple[list[dict], dict]:
    try:
        ledger = strict_json(confined_path(root, CANDIDATE_LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    candidates = ledger.get("atoms", [])
    if not isinstance(candidates, list):
        candidates = []
    ledger_evidence = source_evidence(root, receipt, CANDIDATE_LEDGER)
    delta_evidence = source_evidence(root, receipt, BINDING_DELTA)
    states = {row["id"]: row["status"] for row in execution["matrix"]}
    bindings = []
    for definition in BINDING_DEFINITIONS:
        matches = [candidate for candidate in candidates
                   if isinstance(candidate, dict) and candidate.get("candidate_id") == definition["candidate_id"]]
        candidate = matches[0] if len(matches) == 1 else {}
        approved_source = candidate_source_evidence(root, receipt, candidate)
        implementation = [source_evidence(root, receipt, relative) for relative in definition["implementation_files"]]
        case_sources = [source_evidence(root, receipt, relative) for relative in definition["case_sources"]]
        checks = {
            "execution_current": execution["evidence_valid"] is True,
            "candidate_identity_matches": len(matches) == 1 and candidate.get("name") == definition["name"],
            "professional_difference_preserved": isinstance(candidate.get("professional_difference"), str) and bool(candidate["professional_difference"].strip()),
            "candidate_ledger_current": ledger_evidence["current"],
            "binding_delta_current": delta_evidence["current"],
            "candidate_source_current": approved_source["current"],
            "implementation_sources_current": all(source["current"] for source in implementation),
            "case_sources_current": all(source["current"] for source in case_sources),
            "complete_scenarios_passed": all(states.get(identifier) == "passed" for identifier in definition["scenario_ids"]),
            "actual_cases_passed": all(receipt.get(section, {}).get("cases", {}).get(case) == "passed"
                                      for section, cases in definition["actual_cases"].items() for case in cases),
        }
        valid = all(checks.values())
        bindings.append({
            **definition,
            "name": candidate.get("name", definition["name"]),
            "professional_difference": candidate.get("professional_difference"),
            "historical_candidate_state": {"admission": candidate.get("admission"), "runtime": candidate.get("runtime")},
            "status": "verified" if valid else "not_verified",
            "evidence_valid": valid, "checks": checks,
            "missing_or_stale": [key for key, passed in checks.items() if not passed],
            "candidate_source": approved_source,
            "implementation_source_evidence": implementation, "case_source_evidence": case_sources,
            "evidence_refs": [receipt_path, CANDIDATE_LEDGER, BINDING_DELTA,
                              *definition["implementation_files"], *definition["case_sources"]],
            "admission_granted": False, "domain_global_promotion_proven": False,
        })
    return bindings, {
        "candidate_total": len(candidates), "selected_bindings": len(bindings),
        "verified_current_bounded_bindings": sum(binding["evidence_valid"] for binding in bindings),
        "all_consumers_verified": False, "full_candidate_admission_granted": False,
        "professional_effectiveness_proven": False, "domain_global_promotion_proven": False,
        "candidate_ledger_source": ledger_evidence, "binding_delta_source": delta_evidence,
        "boundary": "Allowlisted existing consumers only; the historical candidate ledger is unchanged. Verification is receipt-bound local evidence, not all 128 candidates implemented/admitted or complete professional/global promotion.",
    }


def build_report(root: Path, *, receipt_path: str = DEFAULT_RECEIPT) -> dict:
    receipt_file = confined_path(root, receipt_path)
    acceptance = strict_json((root / "docs/acceptance-map.json").read_text(encoding="utf-8"))
    receipt_content = receipt_file.read_bytes()
    receipt = strict_json(receipt_content.decode("utf-8"))
    execution = evaluate(root, acceptance, receipt, receipt_path=receipt_path)
    bindings, binding_summary = current_consumer_bindings(root, receipt, execution, receipt_path)
    matrix = [
        {"id": row["id"], "gate": row["gate"], "execution_class": row["execution_class"],
         "authoritative_status": row["status"], "classification": row["status"],
         "required_for_g6": row["required_for_g6"], "evidence_refs": row["evidence_refs"],
         "test_cases": row.get("test_cases", []), "coverage": row.get("coverage"), "reason": row.get("reason")}
        for row in execution["matrix"]
    ]
    report = {
        "schema_version": 1,
        "release": "p6-evidence-crosswalk-3",
        "status": "supporting_evidence_separated_from_authoritative_acceptance",
        "authority": "Derived evaluation of only the selected receipt against current sources/logs/specs; no saved execution ledger or historical full suite supplies current passes. Frozen specs unchanged; component/partial/native/professional evidence remain distinct.",
        "execution_ledger": {"kind": "in_memory_evaluation", "receipt": receipt_path, "persisted": False},
        "execution_receipt": receipt_path,
        "execution_receipt_sha256": hashlib.sha256(receipt_content).hexdigest(),
        "execution_evidence_valid": execution["evidence_valid"],
        "execution_checks": execution["checks"],
        "receipt_selection": "default_compatibility_path" if receipt_path == DEFAULT_RECEIPT else "explicit_project_relative_path",
        "receipt_currency": "current_valid" if execution["evidence_valid"] else "historical_or_invalid_not_current_evidence",
        "current_consumer_bindings": bindings,
        "current_consumer_binding_summary": binding_summary,
        "summary": {
            "acceptance_total": len(matrix),
            "authoritative_not_run": sum(item["classification"] == "not_run" for item in matrix),
            "authoritative_passed": execution["summary"]["passed_for_g6"],
            "status_counts": execution["summary"]["status_counts"],
            "required_for_g6": execution["summary"]["required_for_g6"],
            "supporting_evidence_only_records": 0,
            "blocked_external_scopes": 1,
            "internal_incomplete_scopes": 3,
            "deferred_p7_scopes": 1,
        },
        "authoritative_matrix": matrix,
        "supporting_evidence_only": [
            {
                "id": "E-REVIEWED-VIDEO-BINDING",
                "kind": "actual_bound_local_video_dispatch_and_independent_decode",
                "path": "outputs/p4/video-framework-workflow-evidence.json",
                "boundary": "Current local process/tool/schema/implementation binding plus real eight-frame video and drift refusals; not all MCP/API tool discovery or full T85/professional acceptance.",
            },
            {
                "id": "E-OFFICE-DOCUMENT-BOUNDED",
                "kind": "actual_bounded_word_and_xlsx_document_workflow",
                "path": "outputs/p4/office-document-workflow-evidence.json",
                "boundary": "XLSX formula/cached-value and OfficeCLI readback passed; DOCX structure/readback passed but the approved renderer was unavailable, so no Word completion or professional-effectiveness claim is made.",
            },
            {
                "id": "E-LEGION-TASK",
                "kind": "actual_bounded_isolated_utf8_task",
                "path": "outputs/p2/legion-first-task-receipt.json",
                "current_recheck": "outputs/p2/legion-first-task-current-recheck.json",
                "boundary": "Real file artifact, independent bytes/hash/UTF-8 checks and one invocation on replay; not model repair or full professional acceptance.",
            },
            {
                "id": "E-WUJI4-FRAMEWORK",
                "kind": "actual_project_local_framework_smoke",
                "path": "outputs/p2/framework-doctor-current.json",
                "boundary": "Project-local status/doctor/on-demand route plus one existing Rust/SQLite bounded file task; no resident service, second database, model dispatch, installation or professional effectiveness claim.",
            },
            {
                "id": "E-WUJI4-CAPABILITIES",
                "kind": "existing_tool_contract_view",
                "path": "outputs/p2/framework-capabilities-current.json",
                "boundary": "Read-only view of existing bounded adapters and their contracts; does not execute tools, grant permissions, prove professional effectiveness or add generic dispatch.",
            },
            {
                "id": "E-LEGION-EXPERIENCE",
                "kind": "local_exact_experience_followup_and_invalidation",
                "path": "outputs/p5/legion-experience-task-receipt.json",
                "boundary": "Local reviewed candidate used in current manifest guard/regression and refused after source change; not autonomous model evolution or public/global admission.",
            },
            {
                "id": "E-LEGION-EXPERIENCE-WORKFLOW",
                "kind": "actual_cli_related_task_and_scope_regression",
                "path": "outputs/p5/experience-workflow-evidence.json",
                "boundary": "Historical T21 adoption and T22 project/review-permit supporting checks are not current passes. Current T22 single-owner Windows ACL is evaluated from the selected receipt; no multi-tenant, autonomous model or global admission claim.",
            },
            {
                "id": "E-G2-U",
                "kind": "bounded_native_acceptance",
                "path": "outputs/p2/native-real-execution-report-2026-10-03.json",
                "boundary": "Supports the bounded u task lifecycle and independent acceptance only; not the 95-scenario matrix or host capability claims.",
            },
            {
                "id": "E-G3-COLD",
                "kind": "cold_catalog_quality",
                "path": "outputs/p3/p3-quality-report.json",
                "boundary": "Supports catalog structure and cold-state checks only; not expert effectiveness or runtime admission.",
            },
            {
                "id": "E-G4-LOCAL",
                "kind": "deterministic_local_adapter",
                "path": "outputs/p4/software-repair-u-evidence.json",
                "boundary": "Supports local software-repair file validation only; not ComfyUI, OfficeCLI, video, or audio professional artifacts.",
            },
            {
                "id": "E-G4-COMFYUI-BOUNDED",
                "kind": "bounded_real_comfyui_probe",
                "path": "outputs/p4/comfyui-probe-evidence.json",
                "boundary": "Supports one real local LoadImage -> ImageScale -> SaveImage chain and artifact validation only; not professional image quality or full G4 effectiveness.",
            },
            {
                "id": "E-G4-FFMPEG-BOUNDED",
                "kind": "bounded_real_ffmpeg_probe",
                "path": "outputs/p4/ffmpeg-probe-evidence.json",
                "boundary": "Supports one real local PNG -> H.264 MP4 render and decode validation only; not professional video editing, audio, or full G4 effectiveness.",
            },
            {
                "id": "E-G5-GOVERNANCE",
                "kind": "governance_core_tests",
                "path": "outputs/p5/p5-governance-report.json",
                "boundary": "Supports deterministic delta/CAS/impact/revocation mechanics only; not model or professional effectiveness.",
            },
            {
                "id": "E-RUST-MECHANISM",
                "kind": "mechanism_tests",
                "path": receipt.get("rust", {}).get("log_path"),
                "boundary": "Only the Rust cases in the selected receipt/log; no historical full-suite, task-relevant native or professional acceptance substitution.",
            },
            {
                "id": "E-PYTHON-AUDIT",
                "kind": "audit_helper_tests",
                "path": receipt.get("python", {}).get("log_path"),
                "boundary": "Only the Python cases in the selected receipt/log; helper behavior does not substitute for all acceptance scenarios.",
            },
        ],
        "internal_incomplete": [
            {
                "id": "B-G4-COMFYUI-HOLDOUT",
                "scope": "Professional ComfyUI artifact and quality holdout",
                "reason": "Historical bounded probe evidence is not revalidated here; current professional effectiveness and holdout acceptance remain unproven.",
            },
            {
                "id": "B-G4-MEDIA",
                "scope": "Professional video editing, audio and REAPER real artifacts",
                "reason": "Historical bounded render evidence is not revalidated here; current professional editing/audio and holdout acceptance remain unproven.",
            },
            {
                "id": "B-G6-HOLDOUT",
                "scope": "Professional holdout and effectiveness evidence",
                "reason": "No valid professional holdout execution is recorded.",
            },
        ],
        "blocked_external": [
            {
                "id": "B-G6-HOST",
                "scope": "Effective backend model, effort, quota, and fee attestations",
                "reason": "Host capability facts remain unknown and are not inferred from configuration or self-report.",
            },
        ],
        "deferred_p7": [
            {
                "id": "B-G7-INSTALL",
                "scope": "Complete G7 new-session behavior, representative task, and production recovery rehearsal",
                "core_installation_authorization": "separately_authorized_core_only",
                "core_installation_record": "outputs/p7/core-skill-install-record-2026-10-05.json",
                "authorization_ref": "docs/execution-authorization.md",
                "reason": "Core-only installation was separately authorized and recorded; this does not prove complete G7. The crosswalk neither rechecks global installation nor performs deployment, new-session activation or production recovery.",
            },
        ],
    }
    for evidence in report["supporting_evidence_only"]:
        selected_log = evidence["id"] in {"E-RUST-MECHANISM", "E-PYTHON-AUDIT"}
        evidence["status"] = ("current_selected_log" if execution["evidence_valid"] else "stale_selected_log") if selected_log else "historical_supporting_only_not_revalidated"
        evidence["current_evidence_valid"] = selected_log and execution["evidence_valid"]
        evidence["included_in_acceptance_pass_count"] = False
    report["summary"]["supporting_evidence_only_records"] = len(report["supporting_evidence_only"])
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Derive a current evidence crosswalk without rewriting frozen acceptance or historical receipts.")
    parser.add_argument("--receipt", default=DEFAULT_RECEIPT, help="Project-relative POSIX path to the actual execution receipt (legacy default retained, freshness checked).")
    args = parser.parse_args(argv)
    report = build_report(ROOT, receipt_path=args.receipt)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUTPUT), "summary": report["summary"]}))


if __name__ == "__main__":
    main()
