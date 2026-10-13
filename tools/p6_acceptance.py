from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from p6_package_validation import confined_path

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_CASES = {
    "T10": "store::tests::t10_actual_windows_links_case_aliases_and_retargeted_paths_fail_closed",
    "T11": "store::tests::t11_full_local_revision_revalidates_only_affected_chain_and_preserves_history",
    "T12": "store::tests::t12_full_local_repeated_events_never_create_second_dispatch_or_change_artifact",
    "T13": "store::tests::os_kill_after_dispatch_requires_query_and_holds_slot",
    "T18": "store::tests::t18_changed_adopted_file_needs_new_revision_and_independent_current_validation",
    "T19": ["store::tests::t19_actual_defect_has_file_evidence_and_bounded_independently_verified_repair",
            "store::tests::t19_clean_review_does_not_invent_three_findings_or_repeat_dispatch",
            "store::tests::t19_pinned_no_progress_cap_stops_rework_before_mutation_and_survives_reopen",
            "store::tests::t19_real_validation_resets_consecutive_guard_but_not_aggregate_revision_budget",
            "store::tests::t19_normal_user_revisions_do_not_count_as_unverified_repairs",
            "store::tests::t19_repair_cap_is_per_defect_node_and_cannot_reset_through_event_names",
            "store::tests::t19_two_independent_defects_can_be_repaired_without_unrelated_rework",
            "store::tests::t19_lost_artifact_can_be_repaired_at_original_path_without_invented_spec_change"],
    "T22": ["t22_current_owner_consumes_knowledge_and_experience_after_reopen",
            "t22_json_owner_or_token_fields_cannot_grant_authority",
            "t22_revocation_denies_every_operation_including_historical_replays",
            "t22_another_owner_sid_denies_open_and_all_live_operations",
            "t22_scope_is_rechecked_after_store_open_before_queries_and_replays",
            "t22_record_scope_change_denies_mutations_and_does_not_leak_query_content",
            "t22_cross_project_input_and_relocated_database_are_rejected",
            "t22_legacy_database_cannot_be_silently_claimed_or_migrated",
            "t22_empty_or_unknown_owner_authorization_is_not_repaired",
            "t22_transfer_scope_is_rechecked_before_new_intent_and_replay",
            "t22_transfer_replay_validates_immutable_source_intent",
            "t22_transfer_and_received_replays_recheck_both_open_store_owners"],
    "T23": "t23_retired_experience_never_reappears_after_query_or_reopen",
    "T24": ["governance::tests::source_license_admission_requires_explicit_policy_and_preserves_versions",
            "governance::tests::in_flight_release_is_pinned_while_new_source_version_is_staged",
            "governance::tests::release_transitions_are_one_way_until_withdrawal"],
    "T46": "t46_deterministic_compilation_and_field_origins",
    "T47": "t47_diamond_deduplication_and_incompatible_versions",
    "T48": "t48_cycles_and_missing_references_stop_preparation",
    "T49": "t49_allowed_slots_preserve_white_hat_and_acceptance",
    "T52": "t52_complete_large_impact_requires_all_pages_and_repairs_corrupt_derived_index",
    "T53": "t53_withdrawal_denies_actual_new_claim_and_claimed_write_without_rewriting_history",
    "T77": "received_delta_cas_and_reopen_preserve_origin_and_require_independent_current_review",
    "T84": "received_delta_cas_and_reopen_preserve_origin_and_require_independent_current_review",
    "T64": "t64_units_adopted_versions_current_hashes_and_explicit_rounding_are_separate",
}
SEMANTIC_PREREQUISITES = {
    "T10": ["store::tests::parent_path_and_unassigned_output_rejected",
            "store::tests::conflicting_writes_have_no_second_attempt"],
    "T19": ["owned_schema6_artifact_migration_preserves_history_references_and_live_uniqueness",
            "schema6_without_owner_or_with_revocation_is_not_migrated",
            "schema6_migration_collision_and_broken_references_roll_back_without_mutation",
            "owned_schema7_cannot_downgrade_to_bypass_migration_guards",
            "schema6_unknown_artifact_columns_are_not_silently_dropped"],
    "T22": ["local_identity::tests::t22_whoami_csv_accepts_only_one_valid_sid_without_trusting_username",
            "local_identity::tests::t22_whoami_csv_rejects_malformed_or_multiple_identities"],
    "T11": ["store::tests::graph_cas_retains_unrelated_adoption_and_rejects_old_result",
            "store::tests::graph_revisions_cannot_reset_budget_or_repeat_no_progress"],
    "T12": ["store::tests::plan_replay_and_changed_payload_conflict",
            "store::tests::repeated_write_replays_without_redispatch_and_changed_payload_conflicts"],
    "T13": ["store::tests::os_kill_after_file_sync_cannot_fabricate_producer_receipt",
            "store::tests::checkpoint_is_durable_but_cannot_resolve_unknown_or_extend_lease"],
    "T18": ["store::tests::changed_output_invalidates_validation",
            "store::tests::changed_adopted_upstream_never_unlocks_downstream"],
    "T53": ["t53_os_process_kill_before_catalog_publication_commit_preserves_pointer_and_manifest",
            "t51_task_catalog_restart_pins_old_release_without_rewriting_handler_or_inputs",
            "task_catalog::tests::short_catalog_action_guard_serializes_withdrawal_without_holding_model_wait"],
    "T77": ["received_exact_knowledge_rebinding_never_follows_latest_or_replays_old_review_as_current",
            "received_delta_retirement_and_historical_replay_never_revive_source_or_target",
            "transferred_knowledge_dependency_requires_real_target_ack_and_current_owner_state",
            "moved_knowledge_cannot_be_resolved_through_a_different_destination_grant",
            "received_owner_evidence_or_origin_change_and_tampered_version_invalidate_current_reuse"],
    "T84": ["received_delta_permission_origin_fields_evidence_and_parent_revalidation_fail_closed",
            "received_merge_preserves_professional_details_and_does_not_overwrite_conflicting_scalars",
            "received_delta_two_connections_have_one_revision_winner_and_no_duplicate_writable_fact",
            "received_delta_retirement_and_historical_replay_never_revive_source_or_target"],
}

SEMANTIC_PYTHON_CASES = {
    "T20": ["test_evidence_budget_cli.EvidenceBudgetCliTests.test_t70_actual_large_json_copy_and_paged_readback_preserve_errors_and_not_fee_limits"],
    "T21": ["test_experience_workflows.ExperienceWorkflowTests.test_t21_reviewed_exact_experience_drives_related_task_and_rejects_stale_or_universal"],
    "T70": ["test_evidence_budget_cli.EvidenceBudgetCliTests.test_t70_actual_large_json_copy_and_paged_readback_preserve_errors_and_not_fee_limits"],
    "T05": ["test_selector_workflows.SelectorWorkflowTests.test_t05_actual_subset_selection_provides_needed_source_and_excludes_unrelated_bodies"],
    "T06": ["test_selector_workflows.SelectorWorkflowTests.test_t06_actual_ambiguity_requires_narrowing_not_fake_confidence_or_truncation"],
    "T83": ["test_selector_workflows.SelectorWorkflowTests.test_t83_actual_direct_tiers_have_measured_roundtrips_full_sources_and_stale_rejection"],
    "T71": [
        "test_evidence_budget_cli.EvidenceBudgetCliTests.test_configuration_cli_rejects_effective_fields_and_update_replay",
        "test_host_probe.HostProbeTests.test_secrets_urls_and_instructions_not_emitted",
        "test_host_probe.HostProbeTests.test_missing_config_is_unknown_not_auth_failure",
    ],
}


def semantic_cases(identifier: str) -> list[str]:
    selected = SEMANTIC_CASES[identifier]
    cases = list(selected) if isinstance(selected, list) else [selected]
    return [*cases, *SEMANTIC_PREREQUISITES.get(identifier, [])]


SUPPORTING_CASES = {
    "T05": ["selector::tests::typed_selection_and_antitrigger_do_not_load_body"],
    "T06": ["selector::tests::ambiguous_selection_and_candidate_overflow_are_not_confidence"],
    "T08": ["store::tests::independent_file_reservations_do_not_conflict"],
    "T09": ["store::tests::two_os_processes_have_one_claim_winner"],
    "T11": ["store::tests::graph_cas_retains_unrelated_adoption_and_rejects_old_result"],
    "T12": ["store::tests::repeated_write_replays_without_redispatch_and_changed_payload_conflicts"],
    "T13": ["store::tests::os_kill_after_dispatch_requires_query_and_holds_slot"],
    "T14": ["store::tests::expired_lease_does_not_write_or_release_slot"],
    "T18": ["store::tests::changed_output_invalidates_validation"],
    "T45": ["composer::tests::deterministic_diamond_and_all_source_paths"],
    "T50": ["store::tests::user_authority_json_does_not_grant_permission"],
    "T07": ["shared_exact_expert_has_distinct_instances_and_never_reports_started_agents"],
    "T51": ["catalog_stage_and_composition_validation_are_not_activation_or_professional_admission",
            "t51_task_catalog_restart_pins_old_release_without_rewriting_handler_or_inputs"],
    "T57": ["selector::tests::typed_selection_and_antitrigger_do_not_load_body"],
    "T62": ["composer::tests::deterministic_diamond_and_all_source_paths"],
    "T63": ["composer::tests::exact_version_scope_and_file_hash_are_distinct_guards"],
    "T66": ["store::tests::two_os_processes_have_one_claim_winner", "store::tests::os_kill_in_transaction_rolls_back_graph_change"],
    "T70": ["strict_json::tests::strict_input_failures"],
    "T83": ["selector::tests::tier_direct_source_is_hash_bound_and_not_fake_hot_loading", "selector::tests::index_change_revokes_projection_and_id_only_fallback_is_rejected"],
    "T21": ["resource_candidates_persist_without_automatic_activation", "resource_updates_are_cas_and_not_public_authority"],
}


SUPPORTING_PYTHON_CASES = {
    "T85": [
        "test_p4_tool_binding.P4ToolBindingTests.test_video_binding_includes_exact_version_schema_and_identity",
        "test_p4_tool_binding.P4ToolBindingTests.test_video_binding_rejects_same_name_alias_and_directory_fallback",
        "test_p4_tool_binding.P4ToolBindingTests.test_video_dispatch_rejects_binding_drift_before_process_start",
        "test_p4_tool_binding.P4ToolBindingTests.test_framework_video_evidence_binds_current_sources_artifact_and_real_decode",
        "test_p4_tool_binding.P4ToolBindingTests.test_manifest_binds_current_tool_versions_contracts_and_evidence",
        "test_p4_tool_binding.P4ToolBindingTests.test_changed_binding_evidence_is_not_accepted_as_current",
        "test_ffmpeg_workflow.FfmpegWorkflowTests.test_actual_video_task_decodes_eight_frames_and_never_overwrites",
        "test_ffmpeg_workflow.FfmpegWorkflowTests.test_changed_binary_is_rejected_without_automatic_fallback",
        "test_ffmpeg_workflow.FfmpegWorkflowTests.test_configuration_change_revokes_completion",
        "test_ffmpeg_workflow.FfmpegWorkflowTests.test_schema_identity_duplicate_and_source_drift_are_denied_before_real_dispatch",
        "test_ffmpeg_workflow.FfmpegWorkflowTests.test_binding_changed_during_real_encoding_revokes_completion",
    ],
    "T42": [
        "test_wuji4_framework.Wuji4FrameworkTests.test_status_separates_frozen_source_policy_from_matching_installed_core",
        "test_wuji4_framework.Wuji4FrameworkTests.test_status_stale_core_bytes_do_not_count_as_installed",
        "test_p6_package.P6PackageTests.test_manifest_files_are_hash_bound_inside_archive",
        "test_p6_package.P6PackageTests.test_external_sidecar_hash_matches_archive",
    ],
    "T82": [
        "test_preflight.AuditTests.test_reference_registration_requires_inventory_hash_and_reason",
        "test_preflight.AuditTests.test_unhashed_package_not_equal",
        "test_p3_catalog.P3CatalogTests.test_all_catalog_source_links_match_current_file_bytes",
    ],
    "T93": [
        "test_execution_baseline.ExecutionBaselineTests.test_current_production_map_keeps_all_95_and_only_three_p7_scenarios",
        "test_execution_baseline.ExecutionBaselineTests.test_removed_scope_other_frozen_override_and_p7_expansion_are_rejected",
        "test_wuji4_framework.Wuji4FrameworkTests.test_status_global_rule_observation_never_claims_new_chat_behavior",
    ],
    "T94": [
        "test_p6_package_validation.PackageValidationTests.test_valid_archive_and_source_closure",
        "test_p6_package_validation.PackageValidationTests.test_changed_source_is_not_hash_bound",
        "test_execution_baseline.ExecutionBaselineTests.test_changed_active_or_original_hash_is_rejected",
    ],
    "T56": [
        "test_preflight.AuditTests.test_reference_registration_requires_inventory_hash_and_reason",
        "test_preflight.AuditTests.test_required_reference_refresh_uses_fresh_hash",
        "test_p3_catalog.P3CatalogTests.test_all_catalog_source_links_match_current_file_bytes",
        "test_wuji4_framework.Wuji4FrameworkTests.test_capabilities_reads_existing_tool_contracts_without_generic_dispatch",
    ],
    "T65": [
        "test_wuji4_framework.Wuji4FrameworkTests.test_status_reads_only_declared_core_and_agents_not_configuration",
        "test_wuji4_framework.Wuji4FrameworkTests.test_route_loads_only_needed_chat_or_professional_context",
        "test_wuji4_framework.Wuji4FrameworkTests.test_capabilities_reads_existing_tool_contracts_without_generic_dispatch",
        "test_wuji4_framework.Wuji4FrameworkTests.test_run_copy_requires_confirmation_and_delegates_existing_workspace",
    ],
    "T67": [
        "test_p3_catalog.P3CatalogTests.test_all_catalog_source_links_match_current_file_bytes",
        "test_p3_catalog.P3CatalogTests.test_old_quality_flag_cannot_override_changed_missing_or_forged_source_lock",
        "test_execution_baseline.ExecutionBaselineTests.test_current_production_map_keeps_all_95_and_only_three_p7_scenarios",
    ],
    "T91": [
        "test_p3_catalog.P3CatalogTests.test_each_role_has_contract_sources_and_boundaries",
        "test_p3_catalog.P3CatalogTests.test_composition_references_shared_components_without_duplicate_public_bodies",
        "test_wuji4_framework.Wuji4FrameworkTests.test_capabilities_reads_existing_tool_contracts_without_generic_dispatch",
    ],
    "T92": [
        "test_host_probe.HostProbeTests.test_secrets_urls_and_instructions_not_emitted",
        "test_host_probe.HostProbeTests.test_missing_config_is_unknown_not_auth_failure",
        "test_wuji4_framework.Wuji4FrameworkTests.test_status_global_rule_observation_never_claims_new_chat_behavior",
    ],
    "T75": [
        "test_document_audit.DocumentAuditTests.test_coverage_requires_fresh_explicit_notes_and_image",
        "test_render_reading_batch.ReadingBatchTests.test_invalid_ranges_never_render",
        "test_render_reading_batch.ReadingBatchTests.test_results_keep_page_order",
    ],
    "T76": [
        "test_preflight.AuditTests.test_entry_equality_not_package_equality",
        "test_preflight.AuditTests.test_unhashed_package_not_equal",
        "test_preflight.AuditTests.test_empty_packages_not_claimed_equivalent",
    ],
    "T90": [
        "test_preflight.AuditTests.test_required_reference_refresh_uses_fresh_hash",
        "test_p3_catalog.P3CatalogTests.test_all_catalog_source_links_match_current_file_bytes",
        "test_execution_baseline.ExecutionBaselineTests.test_current_production_map_keeps_all_95_and_only_three_p7_scenarios",
    ],
    "T19": [
        "test_decision_audit.DecisionAuditTests.test_changed_source_decision_invalidates_primary_review",
        "test_decision_audit.DecisionAuditTests.test_rejected_source_cannot_inherit_admission_claim",
        "test_experience_workflows.ExperienceWorkflowTests.test_t21_reviewed_exact_experience_drives_related_task_and_rejects_stale_or_universal",
    ],
    "T86": [
        "test_experience_workflows.ExperienceWorkflowTests.test_t21_reviewed_exact_experience_drives_related_task_and_rejects_stale_or_universal",
        "test_experience_workflows.ExperienceWorkflowTests.test_t22_scope_and_review_permit_are_rechecked_before_private_reuse",
        "test_resource_cli.ResourceCliTests.test_propose_review_query_retire_with_the_documented_argument_counts",
        "test_resource_cli.ResourceCliTests.test_review_requires_explicit_isolated_permit",
    ],
    "T54": [
        "test_decision_audit.DecisionAuditTests.test_changed_source_decision_invalidates_primary_review",
        "test_decision_audit.DecisionAuditTests.test_rejected_source_cannot_inherit_admission_claim",
        "test_experience_workflows.ExperienceWorkflowTests.test_t21_reviewed_exact_experience_drives_related_task_and_rejects_stale_or_universal",
    ],
    "T58": [
        "test_design_audit.DesignAuditTests.test_current_design_map",
        "test_p3_catalog.P3CatalogTests.test_each_role_has_contract_sources_and_boundaries",
        "test_wuji4_framework.Wuji4FrameworkTests.test_unknown_route_is_rejected_without_all_expert_fallback",
    ],
    "T59": [
        "test_design_audit.DesignAuditTests.test_current_design_map",
        "test_p3_catalog.P3CatalogTests.test_composition_references_shared_components_without_duplicate_public_bodies",
        "test_p3_catalog.P3CatalogTests.test_quality_report_passes_without_claiming_effectiveness",
    ],
    "T60": [
        "test_decision_audit.DecisionAuditTests.test_changed_semantics_or_baseline_do_not_inherit_review",
        "test_p3_catalog.P3CatalogTests.test_composition_references_shared_components_without_duplicate_public_bodies",
        "test_selector_workflows.SelectorWorkflowTests.test_t06_actual_ambiguity_requires_narrowing_not_fake_confidence_or_truncation",
    ],
    "T61": [
        "test_design_audit.DesignAuditTests.test_current_design_map",
        "test_p4_tool_binding.P4ToolBindingTests.test_video_binding_includes_exact_version_schema_and_identity",
        "test_wuji4_framework.Wuji4FrameworkTests.test_capabilities_reads_existing_tool_contracts_without_generic_dispatch",
    ],
    "T22": ["test_experience_workflows.ExperienceWorkflowTests.test_t22_scope_and_review_permit_are_rechecked_before_private_reuse"],
    "T89": ["test_catalog_transfer_time_cli.CatalogTransferTimeCliTests.test_execution_summary_does_not_promote_planning_or_stale_output_to_completion",
            "test_legion_task.LegionTaskTests.test_actual_thin_entry_writes_validates_summarizes_and_replays_without_second_invocation",
            "test_legion_task.LegionTaskTests.test_actual_summary_recheck_does_not_keep_success_text_after_output_changes"],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(root: Path = ROOT) -> dict[str, str]:
    paths = {root / name for name in ("Cargo.toml", "Cargo.lock", "AGENTS.md", "docs/execution-authorization.md",
                                    "docs/acceptance-map.json", "docs/execution-baseline.json", "docs/design-baseline-1.json",
                                    "docs/wuji-legion-4.0-execution-plan-v1.6-2026-10-03.md",
                                    "docs/wuji-legion-4.0-execution-plan-v1.7-2026-10-04.md", "docs/execution-baseline-v1.6.json",
                                    "docs/plan-execution-map-v1.7.json",
                                    "docs/legion-quickstart.md",
                                    "docs/goal-execution-boundaries-2026-10-05.md",
                                    "outputs/p7/research/codex-skills.html",
                                    "outputs/p7/research/windows-shutdown.html",
                                    "outputs/p3/p3-quality-report.json",
                                    "outputs/p0/atom-evidence-ledger.json", "outputs/p0/primary-method-snapshots/STD-RUST-PATHBUF.html",
                                    "outputs/p0/primary-method-snapshots/STD-RUST-I128.html",
                                    "outputs/p0/primary-method-snapshots/STD-FFMPEG-IMAGE2.html",
                                    "outputs/p0/source-coverage.json", "outputs/p0/source-baseline.json",
                                    "outputs/p0/upstream-version-review.json", "outputs/p0/required-source-integrity-refresh.json",
                                    "outputs/p0/conversation-requirement-map.json", "outputs/p0/requirement-map.json",
                                    "docs/source-scope-update-2026-10-03.md", "docs/source-dispositions.tsv",
                                    "docs/source-decisions.md", "docs/p0-source-reconciliation-2026-10-03.md")}
    paths.update((root / "docs/design-deltas").glob("*.md"))
    paths.update((root / "legion").rglob("*.md"))
    paths.update((root / "legion").rglob("*.json"))
    for directory, pattern in (("src", "*.rs"), ("src", "*.sql"), ("tests", "*.rs"),
                               ("tools", "*.py"), ("tools", "*.ps1"), ("adapters", "*.py"),
                               ("schemas", "*.json"), ("catalog", "*.json")):
        paths.update((root / directory).rglob(pattern))
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths) if path.is_file()}


def rust_cases_from_log(text: str) -> dict[str, str]:
    records = {}
    for name, state in re.findall(r"^test (\S+) \.\.\. (ok|FAILED)\s*$", text, re.MULTILINE):
        mapped = "passed" if state == "ok" else "failed"
        if name in records and records[name] != mapped:
            raise ValueError("Conflicting repeated Rust case outcomes")
        records[name] = mapped
    return records


def python_cases_from_log(text: str) -> dict[str, str]:
    records = {}
    for name, state in re.findall(r"^[A-Za-z0-9_]+ \(([^)\n]+)\) \.\.\. (ok|FAIL|ERROR|skipped[^\n]*)$", text, re.MULTILINE):
        mapped = {"ok": "passed", "FAIL": "failed", "ERROR": "error"}.get(state, "skipped")
        if name in records and records[name] != mapped:
            raise ValueError("Conflicting repeated Python case outcomes")
        records[name] = mapped
    return records


def office_artifact_checks(root: Path, receipt: dict) -> dict:
    result = {"receipt_current": False, "adapter_current": False, "artifact_current": False,
              "native_editable_text": False, "html_current": False, "protected_config_current": False,
              "owned_actions_succeeded": False, "original_binary_current": False}
    try:
        proof_path = root / "outputs/p4/officecli-probe-evidence.json"
        result["receipt_current"] = receipt.get("tool_evidence_hashes", {}).get("outputs/p4/officecli-probe-evidence.json") == digest(proof_path)
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        binary = Path("C:/Users/Administrator/AppData/Local/OfficeCli/officecli.exe")
        result["original_binary_current"] = (
            proof["version"] == "1.0.152" and proof["original_source"] == "https://github.com/iOfficeAI/OfficeCLI"
            and proof["source_release"] == "https://github.com/iOfficeAI/OfficeCLI/releases/tag/v1.0.152"
            and proof["binary_sha256"] == "047705402974c3690a4437e55f620d03afac4beba4fdd28fdb59af610a3afff2"
            and binary.resolve() == Path(proof["binary_path"]).resolve() and binary.is_file() and digest(binary) == proof["binary_sha256"]
        )
        required_checks = {"binary_matches_original_release", "actual_version_pinned", "native_editable_shapes",
                           "actual_text_revision_present", "old_text_removed", "file_hash_changes_on_edit",
                           "native_get_after_edit", "outline_contains_actual_slide_title", "actual_html_export",
                           "target_close_succeeded", "configurations_unchanged"}
        result["owned_actions_succeeded"] = (
            required_checks.issubset(proof["checks"]) and all(proof["checks"][key] is True for key in required_checks)
            and len(proof["actions"]) >= 9 and proof["actions"][-1]["arguments"][0] == "close"
            and all(action["exit_code"] == 0 and action["owned_process_exit_observed"] is True
                    and action["auto_install"] is False and action["auto_update"] is False
                    and action["auto_resident"] is False for action in proof["actions"])
        )
        result["adapter_current"] = proof["adapter_sha256"] == digest(root / "adapters/p4/officecli_adapter.py")
        from p6_package_validation import confined_path
        artifact = confined_path(root, proof["artifact"]["path"])
        result["artifact_current"] = artifact.is_file() and proof["artifact"]["sha256"] == digest(artifact) and proof["artifact"]["bytes"] == artifact.stat().st_size
        with zipfile.ZipFile(artifact) as archive:
            if archive.getinfo("ppt/slides/slide1.xml").file_size > 1024 * 1024:
                raise ValueError("Bounded slide XML exceeded")
            slide = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
            texts = [element.text for element in slide.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t")]
            result["native_editable_text"] = "Editable native text after revision" in texts and "Editable native text before revision" not in texts
        html = confined_path(root, proof["html_export"]["path"])
        result["html_current"] = proof["html_export"]["sha256"] == digest(html) and "Editable native text after revision" in html.read_text(encoding="utf-8")
        before = proof["protected_configurations_before"]
        after = proof["protected_configurations_after"]
        allowed_root = Path("C:/Users/Administrator/.officecli").resolve()
        allowed_config = Path("C:/Users/Administrator/.codex/config.toml").resolve()
        transition_path = root / "outputs/p7/global-4-only-cutover-2026-10-05.json"
        transition = json.loads(transition_path.read_text(encoding="utf-8"))
        transition_config = transition["config"]
        authorized_current_config = (
            transition.get("schema_version") == 1
            and transition.get("kind") == "wuji_legion_global_4_only_cutover"
            and transition.get("status") == "global_entry_cutover_verified"
            and transition.get("authorization") == (
                "2026-10-05 user explicitly required global 4.0 only, removal of 3.0 runtime entries, and no shutdown"
            )
            and Path(transition_config["path"]).resolve() == allowed_config
            and transition_config.get("changed_field") == "developer_instructions"
            and transition_config.get("outside_entry_block_byte_identical") is True
            and transition_config.get("other_toml_fields_identical") is True
            and transition_config.get("model_provider_profiles_reasoning_mcp_and_plugin_configuration_unchanged") is True
            and transition_config.get("after_sha256") == digest(allowed_config)
        )
        result["protected_config_unchanged_during_action"] = before == after and bool(after)
        result["protected_config_current"] = result["protected_config_unchanged_during_action"] and all(
            (Path(path).resolve() == allowed_config or Path(path).resolve().is_relative_to(allowed_root))
            and Path(path).is_file()
            and (digest(Path(path)) == checksum or (Path(path).resolve() == allowed_config and authorized_current_config))
            for path, checksum in after.items())
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ET.ParseError):
        return result
    return result


def office_document_artifact_checks(root: Path) -> dict:
    result = {
        "evidence_current": False,
        "implementation_current": False,
        "manifest_current": False,
        "sheet_receipt_current": False,
        "sheet_framework_output_current": False,
        "sheet_artifact_current": False,
        "word_receipt_current": False,
        "word_framework_output_current": False,
        "word_artifact_current": False,
        "summary_current": False,
        "configuration_current": False,
        "word_required_render": False,
    }
    try:
        proof_path = root / "outputs/p4/office-document-workflow-evidence.json"
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        manifest_path = root / "catalog/p4/tool-manifests.json"
        expected_implementation = {
            relative: digest(root / relative)
            for relative in (
                "adapters/p4/office_document_workflow.py",
                "adapters/p4/officecli_adapter.py",
                "tools/wuji4.py",
                "catalog/p4/tool-manifests.json",
            )
        }
        result["implementation_current"] = proof["implementation_hashes"] == expected_implementation
        result["manifest_current"] = proof["binding_refresh"]["manifest_sha256"] == digest(manifest_path)
        formats = proof["formats"]
        configuration_checks = []
        for name in ("sheet", "word"):
            current = formats[name]
            receipt = current["receipt"]
            framework_output = current["framework_output"]
            artifact = current["artifact"]
            receipt_path = confined_path(root, receipt["path"])
            framework_path = confined_path(root, framework_output["path"])
            artifact_path = confined_path(root, artifact["path"])
            result[f"{name}_receipt_current"] = (
                receipt_path.is_file()
                and receipt["sha256"] == digest(receipt_path)
                and receipt["bytes"] == receipt_path.stat().st_size
            )
            result[f"{name}_framework_output_current"] = (
                framework_path.is_file()
                and framework_output["sha256"] == digest(framework_path)
                and framework_output["bytes"] == framework_path.stat().st_size
            )
            result[f"{name}_artifact_current"] = (
                artifact_path.is_file()
                and artifact["sha256"] == digest(artifact_path)
                and artifact["bytes"] == artifact_path.stat().st_size
            )
            receipt_value = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt_artifact = receipt_value["artifacts"]["office_file"]
            receipt_artifact_path = Path(receipt_artifact["path"]).resolve()
            root_path = root.resolve()
            receipt_artifact_within_root = receipt_artifact_path.is_relative_to(root_path)
            result[f"{name}_artifact_current"] &= (
                receipt_artifact_within_root
                and receipt_artifact["sha256"] == artifact["sha256"]
                and receipt_artifact["bytes"] == artifact["bytes"]
                and receipt_artifact_path.is_file()
                and digest(receipt_artifact_path) == receipt_artifact["sha256"]
                and receipt_artifact_path.stat().st_size == receipt_artifact["bytes"]
            )
            configuration_checks.append(
                receipt_value["configuration_protection"]["unchanged"] is True
                and receipt_value["configuration_protection"]["before"] == receipt_value["configuration_protection"]["after"]
            )
        result["configuration_current"] = bool(configuration_checks) and all(configuration_checks)
        sheet = formats["sheet"]
        word = formats["word"]
        sheet_checks = sheet["checks"]
        word_checks = word["checks"]
        sheet_structural = all(value is True for value in sheet_checks.values())
        word_structural = all(value is True for key, value in word_checks.items() if key != "rendered_pages")
        result["summary_current"] = (
            proof["summary"]["sheet_bounded_success"] is sheet_structural
            and proof["summary"]["word_structure_and_officecli_readback"] is word_structural
            and proof["summary"]["word_required_render"] is word_checks["rendered_pages"]
            and proof["summary"]["word_render_blocked_external"] is (word["render"]["status"] == "blocked_external")
            and proof["summary"]["configuration_unchanged"] is result["configuration_current"]
        )
        result["word_required_render"] = word_checks["rendered_pages"] is True
        result["evidence_current"] = (
            proof["schema_version"] == 1
            and proof["kind"] == "real_office_document_bounded_workflow"
            and proof["P7"] is False
            and proof["shutdown"] is False
            and sheet["passed"] is True
            and sheet["result_state"] == "completed_bounded_task"
            and sheet_structural
            and word["passed"] is False
            and word["result_state"] == "failed_evidence_retained"
            and word_structural
            and word["render"]["status"] == "blocked_external"
            and result["implementation_current"]
            and result["manifest_current"]
            and result["sheet_receipt_current"]
            and result["sheet_framework_output_current"]
            and result["sheet_artifact_current"]
            and result["word_receipt_current"]
            and result["word_framework_output_current"]
            and result["word_artifact_current"]
            and result["summary_current"]
            and result["configuration_current"]
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return result
    return result


def evaluate(root: Path, specs: dict, receipt: dict, *, receipt_path: str = "outputs/p6/test-execution.json") -> dict:
    confined_path(root, receipt_path)
    checks = {
        "spec_hash_current": receipt.get("acceptance_spec_sha256") == digest(root / "docs/acceptance-map.json"),
        "sources_current": receipt.get("source_hashes") == source_snapshot(root),
        "sources_stable_during_execution": receipt.get("source_hashes") == receipt.get("source_hashes_after"),
        "rust_command_passed": receipt.get("rust", {}).get("exit_code") == 0,
        "python_suite_passed": receipt.get("python", {}).get("passed") is True and receipt.get("python", {}).get("exit_code") == 0,
        "logs_current": True,
        "rust_case_records_match_log": False,
        "python_case_records_match_log": False,
    }
    for section in ("rust", "python"):
        evidence = receipt.get(section, {})
        try:
            path = confined_path(root, evidence.get("log_path"))
            if not path.is_file():
                checks["logs_current"] = False
                continue
            content = path.read_bytes()
            checks["logs_current"] &= evidence.get("log_sha256") == hashlib.sha256(content).hexdigest()
            text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            if section == "rust":
                records = rust_cases_from_log(text)
                checks["rust_case_records_match_log"] = evidence.get("cases") == records
            else:
                records = python_cases_from_log(text)
                checks["python_case_records_match_log"] = bool(records) and evidence.get("cases") == records
        except (OSError, ValueError):
            checks["logs_current"] = False
    valid = all(checks.values())
    rust_cases = receipt.get("rust", {}).get("cases", {})
    office_checks = office_artifact_checks(root, receipt)
    office_valid = valid and all(office_checks.values())
    office_document_checks = office_document_artifact_checks(root)
    office_document_valid = valid and office_document_checks["evidence_current"]
    matrix = []
    for spec in specs["tests"]:
        identifier = spec["id"]
        row = {
            "id": identifier, "name": spec["name"], "gate": spec["gate"],
            "execution_class": spec["execution_class"], "normal_spec": spec["normal_spec"],
            "negative_spec": spec["negative_spec"], "status": "not_run", "evidence_refs": [],
            "required_for_g6": spec["gate"] != "G7",
        }
        if spec["gate"] == "G7":
            row.update(status="deferred_p7", reason="P7 requires separate approval and a new session; excluded only from G6 scope, not deleted.")
        elif identifier in SEMANTIC_CASES:
            cases = semantic_cases(identifier)
            row["test_cases"] = cases
            row["coverage"] = "Complete normal and negative deterministic local scenario; no model/professional/production admission claim."
            row["status"] = "passed" if valid and all(rust_cases.get(case) == "passed" for case in cases) else "failed_or_stale"
            test_source = {"T11": "src/store_product_tests.rs", "T12": "src/store_product_tests.rs", "T13": "src/store_product_tests.rs", "T18": "src/store_product_tests.rs", "T19": "src/store_product_tests.rs", "T22": "tests/p6_resource_acl.rs", "T23": "tests/p6_resource_acceptance.rs", "T24": "src/governance.rs", "T52": "tests/p6_catalog_registry.rs", "T53": "tests/p6_task_catalog.rs", "T64": "tests/p6_time_semantics.rs", "T77": "tests/p6_received_delta.rs", "T84": "tests/p6_received_delta.rs"}.get(identifier, "tests/p6_semantic_acceptance.rs")
            row["evidence_refs"] = ["outputs/p6/test-execution.json", test_source]
            if identifier == "T10":
                row["coverage"] = "Complete normal and negative Windows deterministic local path scenario: canonicalization, write locking, link escapes, case aliases and retargeting after claim; no native/model or professional admission claim."
                row["evidence_refs"] = ["outputs/p6/test-execution.json", "src/store_product_tests.rs", "src/store.rs", "src/policy.rs"]
            elif identifier == "T22":
                row["coverage"] = "Windows single-owner resource ACL and project scope are rechecked for live operations and replay, including transfer/received consumption. System whoami supplies the current token SID. No DACL changes, administrator tamper resistance, multi-tenant service or global promotion claim."
        elif identifier in SEMANTIC_PYTHON_CASES:
            cases = SEMANTIC_PYTHON_CASES[identifier]
            test_source = {"T20": "tools/test_evidence_budget_cli.py", "T21": "tools/test_experience_workflows.py", "T24": "tools/test_governance_release_binding.py",
                           "T70": "tools/test_evidence_budget_cli.py",
                           "T71": "tools/test_evidence_budget_cli.py",
                           "T85": "tools/test_p4_tool_binding.py"}.get(identifier, "tools/test_selector_workflows.py")
            row.update(test_cases=cases,
                       coverage="Complete normal and negative isolated CLI workflow; no professional/native admission, fee guarantee or comparative speed claim.",
                       status="passed" if valid and all(receipt.get("python", {}).get("cases", {}).get(case) == "passed" for case in cases) else "failed_or_stale",
                       evidence_refs=["outputs/p6/test-execution.json", test_source])
        elif identifier == "T95":
            row.update(status="passed" if office_valid else "blocked_external",
                       evidence_refs=["outputs/p4/officecli-probe-evidence.json", "outputs/p6/test-execution.json"],
                       coverage="Existing exact original OfficeCLI release, explicit native entrypoint, real create/get/edit/HTML/OOXML/close and configuration protection; no installer, formal design quality or P7 claim.")
        elif identifier == "T29":
            if office_document_valid:
                row.update(status="partial", evidence_refs=["outputs/p4/office-document-workflow-evidence.json", "outputs/p4/office-documents/sheet-receipt.json", "outputs/p4/office-documents/word-receipt.json"],
                           reason="Bounded XLSX formulas/readback and DOCX structure/readback are current; approved rendering is externally unavailable and professional document/design effectiveness remains unverified.")
            else:
                row.update(status="failed_or_stale", evidence_refs=["outputs/p4/office-document-workflow-evidence.json"],
                           reason="Office document evidence is missing, stale, or inconsistent with its current implementation or artifacts.")
        elif identifier in SUPPORTING_CASES:
            cases = SUPPORTING_CASES[identifier]
            row["test_cases"] = cases
            if valid and all(rust_cases.get(case) == "passed" for case in cases):
                row.update(status="partial", evidence_refs=["outputs/p6/test-execution.json"],
                           reason="Local component behavior executed; missing full task/professional/native criteria are not proven.")
        elif identifier in SUPPORTING_PYTHON_CASES:
            cases = SUPPORTING_PYTHON_CASES[identifier]
            row["test_cases"] = cases
            if valid and all(receipt.get("python", {}).get("cases", {}).get(case) == "passed" for case in cases):
                row.update(status="partial", evidence_refs=["outputs/p6/test-execution.json"],
                           reason="Current local CLI execution summary verified; complete native/professional and simple-dialogue behavior remains unproven.")
                if identifier == "T22":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_experience_workflows.py"],
                               reason="Real project scope and explicit review-permit checks reject private cross-project reuse; complete per-user identity/ACL behavior remains unimplemented.",
                               missing_scope="per_user_identity_and_acl")
                elif identifier == "T24":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_governance_release_binding.py"],
                               reason="Report/source/log and prior archive identity checked; complete source/license admission and actual in-flight update governance are not covered by these checks.",
                               missing_scope="complete_update_admission_and_in_flight_execution")
                elif identifier == "T85":
                    row.update(
                        evidence_refs=[
                            "outputs/p6/test-execution.json",
                            "tools/test_p4_tool_binding.py",
                            "tools/test_ffmpeg_workflow.py",
                            "outputs/p4/video-framework-workflow-evidence.json",
                            "catalog/p4/tool-manifests.json",
                        ],
                        reason=(
                            "Current bounded video binding verifies exact local server/tool identity, version, "
                            "interface schema, implementation hashes, alias/fallback rejection and dispatch-time "
                            "binding/configuration drift refusal; a real eight-frame encode and independent decode "
                            "also passed. T85 remains partial because complete MCP/API/cloud discovery, native "
                            "professional effectiveness, and trusted identity/quota/fee attestations are not proven."
                        ),
                        missing_scope="complete_tool_discovery_and_professional_native_attestations",
                    )
                elif identifier == "T71":
                    row.update(
                        evidence_refs=["outputs/p6/test-execution.json", "tools/test_evidence_budget_cli.py", "tools/test_host_probe.py"],
                        coverage="Complete deterministic local configuration/evidence boundary: configured, observed, effective and unknown states stay distinct; forged effective values and stale declarations fail closed.",
                    )
                elif identifier == "T42":
                    row.update(
                        evidence_refs=["outputs/p6/test-execution.json", "tools/test_wuji4_framework.py", "tools/test_p6_package.py"],
                        reason="Current package closure, manifest hash binding and explicit uninstalled policy are verified; actual Codex installation, new-session activation and rollback rehearsal remain outside this evidence.",
                        missing_scope="actual_install_activation_and_rollback_rehearsal",
                    )
                elif identifier == "T82":
                    row.update(
                        evidence_refs=["outputs/p6/test-execution.json", "tools/test_preflight.py", "tools/test_p3_catalog.py"],
                        reason="Source inventory hashes, reasons and current catalog links are checked; complete candidate-by-candidate research adoption and task acceptance closure remain unproven.",
                        missing_scope="complete_candidate_research_adoption_closure",
                    )
                elif identifier == "T93":
                    row.update(
                        evidence_refs=["outputs/p6/test-execution.json", "tools/test_execution_baseline.py", "tools/test_wuji4_framework.py"],
                        reason="The active baseline preserves all 95 scenarios, keeps P7 separate and rejects historical scope expansion; full conversation-to-decision trace coverage remains unproven.",
                        missing_scope="complete_conversation_decision_trace",
                    )
                elif identifier == "T94":
                    row.update(
                        evidence_refs=["outputs/p6/test-execution.json", "tools/test_p6_package_validation.py", "tools/test_execution_baseline.py"],
                        reason="Current package/source closure rejects changed or missing bound sources and preserves the independent v1.7 baseline; complete third-party provenance and all no-copy attestations remain unproven.",
                        missing_scope="complete_rewrite_provenance_attestation",
                    )
                elif identifier == "T56":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_preflight.py", "tools/test_p3_catalog.py", "tools/test_wuji4_framework.py"],
                               reason="Current source inventory, catalog links and capability contracts are hash-bound; full method/script/asset execution handoff for every source remains unproven.",
                               missing_scope="complete_source_to_execution_asset_handoff")
                elif identifier == "T65":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_wuji4_framework.py"],
                               reason="Project-local status, route, capability and confirmed CLI entry behavior are current; distinct API/MCP/UI runtime identities and receipts remain unproven.",
                               missing_scope="distinct_api_mcp_ui_current_runtime_evidence")
                elif identifier == "T67":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_p3_catalog.py", "tools/test_execution_baseline.py"],
                               reason="Current source locks and role/catalog references are checked; complete shared-definition propagation across every role, adapter and regression remains unproven.",
                               missing_scope="complete_shared_upgrade_propagation_closure")
                elif identifier == "T91":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_p3_catalog.py", "tools/test_wuji4_framework.py"],
                               reason="Narrow role contracts, source boundaries and non-duplicated composition references are current; real role instances, style packages and professional IO acceptance remain unproven.",
                               missing_scope="real_role_instance_and_professional_io_evidence")
                elif identifier == "T92":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_host_probe.py", "tools/test_wuji4_framework.py"],
                               reason="Local host class, configured-versus-effective unknowns and project boundary are checked; API/DSH effective host observations remain unknown.",
                               missing_scope="api_dsh_effective_host_observation")
                elif identifier == "T75":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_document_audit.py", "tools/test_render_reading_batch.py"],
                               reason="Bounded document page selection and explicit visual-review freshness checks are current; the required mixed-material project coverage and complete page/segment reading closure remain unproven.",
                               missing_scope="complete_mixed_material_reading_coverage")
                elif identifier == "T76":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_preflight.py"],
                               reason="Entry/package equality, unhashed package rejection and empty-package non-equivalence are verified; the historical D-path redirect and every 58-entry/57-hash mirror asset still need direct current equivalence evidence.",
                               missing_scope="complete_historical_mirror_equivalence")
                elif identifier == "T90":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_preflight.py", "tools/test_p3_catalog.py", "tools/test_execution_baseline.py"],
                               reason="Fresh source references, current catalog links and preserved baseline counts are verified; item-by-item course/technical field-to-execution-asset closure remains unproven.",
                               missing_scope="complete_course_field_execution_asset_closure")
                elif identifier == "T19":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_decision_audit.py", "tools/test_experience_workflows.py"],
                               reason="Changed-source review invalidation, rejected-source admission blocking and exact reviewed experience consumption are current; a complete bounded human/agent review loop with finite rework accounting remains unproven.",
                               missing_scope="complete_review_rework_loop_and_budget")
                elif identifier == "T86":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_experience_workflows.py", "tools/test_resource_cli.py"],
                               reason="Exact reviewed experience, scope/review-permit checks and local resource retirement are current; professional holdouts, cost/coverage evidence and full distillation admission remain unproven.",
                               missing_scope="professional_distillation_admission_and_retirement_evidence")
                elif identifier == "T54":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_decision_audit.py", "tools/test_experience_workflows.py"],
                               reason="Source-review invalidation and exact experience consumption reject single-source universalization; two-channel and domain/global evidence closure remains unproven.",
                               missing_scope="two_channel_domain_global_generalization_evidence")
                elif identifier == "T58":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_design_audit.py", "tools/test_p3_catalog.py", "tools/test_wuji4_framework.py"],
                               reason="Current design map, role contracts and unknown-route rejection constrain decomposition; complete consumer-backed atom sizing and measured interfaces remain unproven.",
                               missing_scope="complete_consumer_backed_granularity_evidence")
                elif identifier == "T59":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_design_audit.py", "tools/test_p3_catalog.py"],
                               reason="Design and catalog checks preserve shared composition and non-effectiveness claims; independent failure coverage for every atom/value/package/recipe layer remains unproven.",
                               missing_scope="complete_atom_value_package_recipe_failure_closure")
                elif identifier == "T60":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_decision_audit.py", "tools/test_p3_catalog.py", "tools/test_selector_workflows.py"],
                               reason="Changed semantics, shared-component boundaries and ambiguity narrowing are checked; full semantic equivalence and professional-difference corpus remains unproven.",
                               missing_scope="complete_semantic_merge_difference_corpus")
                elif identifier == "T61":
                    row.update(evidence_refs=["outputs/p6/test-execution.json", "tools/test_design_audit.py", "tools/test_p4_tool_binding.py", "tools/test_wuji4_framework.py"],
                               reason="Design, tool binding and capability views distinguish schema/program/entry contracts; model instruction adherence and all representation propagation remain unproven.",
                               missing_scope="complete_multi_representation_propagation_evidence")
        elif spec["execution_class"] == "protocol_plus_actual_native_host":
            row.update(status="blocked_external", reason="Requires matched real professional artifact/holdout or actual native identity/effort/exit/capacity evidence; local/mock tests cannot substitute.")
        elif spec["execution_class"] == "actual_professional_artifact":
            row.update(status="not_run", reason="Full professional workflow/holdout implementation and current matched evidence are incomplete; this is not automatically an external blocker.",
                       missing_scope="internal_workflow_and_matched_artifact_evidence")
        row["evidence_refs"] = [receipt_path if reference == "outputs/p6/test-execution.json" else reference
                                for reference in row["evidence_refs"]]
        matrix.append(row)
    counts = Counter(row["status"] for row in matrix)
    required = [row for row in matrix if row["required_for_g6"]]
    return {
        "schema_version": 1, "release": "p6-acceptance-execution-1",
        "execution_receipt": receipt_path,
        "acceptance_spec_sha256": digest(root / "docs/acceptance-map.json"),
        "checks": checks, "evidence_valid": valid, "matrix": matrix,
        "office_artifact_checks": office_checks,
        "office_document_artifact_checks": office_document_checks,
        "summary": {"total": len(matrix), "status_counts": dict(counts),
                    "required_for_g6": len(required), "passed_for_g6": sum(row["status"] == "passed" for row in required),
                    "g6_scenarios_passed": bool(required) and all(row["status"] == "passed" for row in required)},
        "authority": "Frozen specs unchanged; current executed evidence only. Partial/blocked/deferred are not passed.",
    }


def main() -> None:
    specs = json.loads((ROOT / "docs/acceptance-map.json").read_text(encoding="utf-8"))
    receipt = json.loads((ROOT / "outputs/p6/test-execution.json").read_text(encoding="utf-8"))
    report = evaluate(ROOT, specs, receipt)
    (ROOT / "outputs/p6/acceptance-execution.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
