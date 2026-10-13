use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::store::Store;
use wuji4::strict_json;

fn unique_name(label: &str) -> String {
    format!(
        "{}-{}-{}",
        label,
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    )
}

fn workspace(label: &str) -> (PathBuf, Store) {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(".dev/evidence-budgets")
        .join(unique_name(label));
    fs::create_dir_all(&root).unwrap();
    let store = Store::open(&root).unwrap();
    (root, store)
}

fn register_bytes(store: &mut Store, root: &Path, name: &str, bytes: &[u8]) -> ExactRef {
    fs::write(root.join(name), bytes).unwrap();
    store.register_local_input(name, Path::new(name)).unwrap()
}

fn register_json(store: &mut Store, root: &Path, name: &str, value: &Value) -> ExactRef {
    register_bytes(store, root, name, &serde_json::to_vec(value).unwrap())
}

fn decode_hex(value: &str) -> Vec<u8> {
    assert_eq!(value.len() % 2, 0);
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|digits| {
            let text = std::str::from_utf8(digits).unwrap();
            u8::from_str_radix(text, 16).unwrap()
        })
        .collect()
}

fn declaration(host: &str, model: &str) -> Value {
    json!({
        "schema_version": 1,
        "host_class": host,
        "model": model,
        "config_revision": 1,
        "values": {
            "tool_output_token_limit": 4096,
            "model_auto_compact_token_limit": 240000,
            "auto_compact_scope": "task",
            "configured_context_window": null,
            "skills_max_context_tokens": 90000,
            "max_threads": 3
        }
    })
}

fn assert_configuration_is_not_effective(observation: &Value) {
    assert_eq!(observation["requested_model"], "inherit_current_selection");
    assert_eq!(observation["upgrade_model"], "gpt-6.1-sol");
    assert_eq!(observation["automatic_downgrade"], false);
    assert_eq!(observation["failure_fallback_chain"], false);
    assert_eq!(observation["configured_state"], "configured_only");
    assert_eq!(
        observation["observed"]["kind"],
        "current_registered_file_bytes_and_hash_only"
    );
    assert_eq!(observation["active_config_observed"], false);
    assert_eq!(observation["observed"]["active_config_observed"], false);
    assert_eq!(observation["native_host_verified"], false);
    assert_eq!(observation["observed"]["native_host_verified"], false);
    assert_eq!(observation["execution_authority"], false);
    assert_eq!(observation["runtime_admission"], false);
    assert_eq!(observation["fee_hard_limit"], false);
    assert_eq!(observation["budget_semantics"]["fee_hard_limit"], false);
    assert_eq!(
        observation["budget_semantics"]["directory_budget_calculated"],
        false
    );
    assert_eq!(
        observation["budget_semantics"]["effective_window_used_for_calculation"],
        false
    );
    assert_eq!(
        observation["budget_semantics"]["other_model_context_window_reused"],
        false
    );
    for effective in observation["effective"].as_object().unwrap().values() {
        assert_eq!(effective, "unknown");
    }
    for field in ["context_window", "directory_budget", "model", "effort", "quota"] {
        assert_eq!(observation["effective"][field], "unknown");
    }
}

#[test]
fn evidence_pages_reassemble_large_unicode_json_without_filtering_failure_or_permissions() {
    let (root, mut store) = workspace("unicode");
    let evidence = json!({
        "state": "failed",
        "body": "完整证据✅🧭权限边界".repeat(1200),
        "errors": [{"kind": "AuthorityDenied", "detail": "不能用美化掩盖失败"}],
        "permissions": {"allowed": ["read"], "denied": ["publish", "charge", "execute"]},
        "safety": {"white_hat": true, "execution_authority": false, "unknowns": ["effective_effort"]}
    });
    let bytes = serde_json::to_vec(&evidence).unwrap();
    assert!(bytes.len() > 4096);
    let reference = register_bytes(&mut store, &root, "unicode.json", &bytes);
    let mut offset = 0;
    let mut reconstructed = Vec::new();
    let mut saw_utf8_fragment = false;
    loop {
        let page = store.read_evidence_page(&reference, offset, 137).unwrap();
        assert_eq!(page["reference"], serde_json::to_value(&reference).unwrap());
        assert_eq!(page["sha256"], reference.sha256);
        assert_eq!(page["total_bytes"], bytes.len());
        assert_eq!(page["offset"], offset);
        assert_eq!(page["encoding"], "hex");
        assert_eq!(page["engineering_page_byte_limit"], 16384);
        assert_eq!(page["full_evidence_retained"], true);
        assert_eq!(page["evidence_truncated"], false);
        assert_eq!(page["failure_fields_filtered"], false);
        assert_eq!(page["safety_fields_filtered"], false);
        assert_eq!(page["fee_hard_limit"], false);
        assert_eq!(page["execution_authority"], false);
        assert_eq!(page["runtime_admission"], false);
        assert_eq!(page["native_host_verified"], false);
        let serialized = serde_json::to_vec(&page).unwrap();
        assert_eq!(strict_json::parse(&serialized).unwrap(), page);
        let chunk = decode_hex(page["page_hex"].as_str().unwrap());
        assert!(chunk.len() <= 137);
        assert_eq!(page["page_bytes"], chunk.len());
        assert_eq!(page["page_sha256"], strict_json::sha256(&chunk));
        saw_utf8_fragment |= std::str::from_utf8(&chunk).is_err();
        let next_offset = usize::try_from(page["next_offset"].as_u64().unwrap()).unwrap();
        assert_eq!(next_offset, offset + chunk.len());
        assert_eq!(page["complete"], next_offset == bytes.len());
        reconstructed.extend_from_slice(&chunk);
        if page["complete"] == true {
            break;
        }
        assert!(next_offset > offset);
        offset = next_offset;
    }
    assert!(saw_utf8_fragment);
    assert_eq!(reconstructed, bytes);
    let restored = strict_json::parse(&reconstructed).unwrap();
    assert_eq!(restored, evidence);
    assert_eq!(restored["state"], "failed");
    assert_eq!(restored["errors"][0]["kind"], "AuthorityDenied");
    assert_eq!(restored["permissions"]["denied"], json!(["publish", "charge", "execute"]));
    assert_eq!(restored["safety"]["execution_authority"], false);
    assert_eq!(fs::read(root.join("unicode.json")).unwrap(), bytes);
}

#[test]
fn evidence_page_byte_boundaries_and_eof_are_explicit_without_silent_truncation() {
    let (root, mut store) = workspace("boundaries");
    let bytes = "界".repeat(7000).into_bytes();
    let reference = register_bytes(&mut store, &root, "boundary.txt", &bytes);
    let maximum = store.read_evidence_page(&reference, 0, 16384).unwrap();
    assert_eq!(maximum["page_bytes"], 16384);
    assert_eq!(maximum["next_offset"], 16384);
    assert_eq!(maximum["complete"], false);
    assert_eq!(decode_hex(maximum["page_hex"].as_str().unwrap()), bytes[..16384]);
    assert_eq!(store.read_evidence_page(&reference, 0, 1).unwrap()["page_bytes"], 1);
    for invalid in [0, 16385, usize::MAX] {
        assert_eq!(
            store.read_evidence_page(&reference, 0, invalid).unwrap_err().kind,
            ErrorKind::BudgetExhausted
        );
    }
    for invalid in [bytes.len() + 1, usize::MAX] {
        assert_eq!(
            store.read_evidence_page(&reference, invalid, 1).unwrap_err().kind,
            ErrorKind::Shape
        );
    }
    let tail = store.read_evidence_page(&reference, bytes.len() - 1, 16384).unwrap();
    assert_eq!(tail["page_bytes"], 1);
    assert_eq!(tail["next_offset"], bytes.len());
    assert_eq!(tail["complete"], true);
    let eof = store.read_evidence_page(&reference, bytes.len(), 1).unwrap();
    assert_eq!(eof["page_hex"], "");
    assert_eq!(eof["page_bytes"], 0);
    assert_eq!(eof["offset"], bytes.len());
    assert_eq!(eof["next_offset"], bytes.len());
    assert_eq!(eof["complete"], true);
    let empty = register_bytes(&mut store, &root, "empty.txt", b"");
    let empty_page = store.read_evidence_page(&empty, 0, 16384).unwrap();
    assert_eq!(empty_page["total_bytes"], 0);
    assert_eq!(empty_page["page_hex"], "");
    assert_eq!(empty_page["complete"], true);
    assert_eq!(store.read_evidence_page(&empty, 1, 1).unwrap_err().kind, ErrorKind::Shape);
}

#[test]
fn every_evidence_page_rechecks_scope_registration_release_and_current_file_hash() {
    let (root, mut store) = workspace("freshness");
    let reference = register_bytes(&mut store, &root, "current.txt", b"original evidence");
    assert_eq!(store.read_evidence_page(&reference, 0, 1).unwrap()["complete"], false);
    let mut wrong_scope = reference.clone();
    wrong_scope.scope = "project/private-other".into();
    assert_eq!(store.read_evidence_page(&wrong_scope, 0, 1).unwrap_err().kind, ErrorKind::ScopeDenied);
    let mut unregistered = reference.clone();
    unregistered.id = "unregistered/evidence".into();
    assert_eq!(store.read_evidence_page(&unregistered, 0, 1).unwrap_err().kind, ErrorKind::Reference);
    let mut wrong_hash = reference.clone();
    wrong_hash.sha256 = "0".repeat(64);
    assert_eq!(store.read_evidence_page(&wrong_hash, 0, 1).unwrap_err().kind, ErrorKind::ValidationStale);
    let mut wrong_release = reference.clone();
    wrong_release.release = "not-the-adopted-release".into();
    assert_eq!(store.read_evidence_page(&wrong_release, 0, 1).unwrap_err().kind, ErrorKind::ValidationStale);
    fs::write(root.join("current.txt"), b"changed evidence").unwrap();
    assert_eq!(store.read_evidence_page(&reference, 1, 1).unwrap_err().kind, ErrorKind::ValidationStale);
    let updated = store.register_local_input("current.txt", Path::new("current.txt")).unwrap();
    assert!(updated.revision > reference.revision);
    assert_eq!(store.read_evidence_page(&reference, 0, 1).unwrap_err().kind, ErrorKind::ValidationStale);
    assert_eq!(store.read_evidence_page(&updated, 0, 16384).unwrap()["complete"], true);
    drop(store);
    let reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.read_evidence_page(&reference, 0, 1).unwrap_err().kind, ErrorKind::ValidationStale);
    assert_eq!(reopened.read_evidence_page(&updated, 0, 16384).unwrap()["sha256"], updated.sha256);
}

#[test]
fn budget_values_are_configured_only_with_unknown_effective_window_and_no_fee_promise() {
    let (root, mut store) = workspace("configured-only");
    let mut value = declaration("local_codex", "gpt-6.1-sol");
    value["values"]["tool_output_token_limit"] = json!(240000);
    value["values"]["model_auto_compact_token_limit"] = json!(90000);
    let reference = register_json(&mut store, &root, "configured.json", &value);
    let observation = store.budget_configuration(&reference).unwrap();
    assert_configuration_is_not_effective(&observation);
    assert_eq!(observation["configured"], value);
    assert_eq!(observation["source_ref"], serde_json::to_value(&reference).unwrap());
    assert_eq!(observation["observed"]["source_ref"], observation["source_ref"]);
    assert_eq!(observation["observed"]["sha256"], reference.sha256);
    assert_eq!(observation["observed"]["total_bytes"], fs::metadata(root.join("configured.json")).unwrap().len());
    assert_eq!(observation["configured"]["values"]["configured_context_window"], Value::Null);
    assert_eq!(observation["effective"]["directory_budget"], "unknown");
    assert_eq!(observation["host_schema_fingerprint"].as_str().unwrap().len(), 64);
    assert_eq!(store.budget_configuration(&reference).unwrap(), observation);
    let omitted = json!({"schema_version":1,"host_class":"test_local","model":"gpt-6.1-sol","config_revision":1,"values":{}});
    let optional_ref = register_json(&mut store, &root, "optional.json", &omitted);
    let optional = store.budget_configuration(&optional_ref).unwrap();
    assert_configuration_is_not_effective(&optional);
    assert_eq!(optional["configured"]["values"].as_object().unwrap().len(), 6);
    assert!(optional["configured"]["values"].as_object().unwrap().values().all(Value::is_null));
}

#[test]
fn budget_host_and_source_fingerprints_cannot_be_injected_or_reused_as_current_observations() {
    let (root, mut store) = workspace("host-fingerprints");
    let mut fingerprints = Vec::new();
    let mut observations = Vec::new();
    for host in ["local_codex", "managed_api", "dsh", "test_local"] {
        let value = declaration(host, "gpt-6.1-sol");
        let name = format!("{host}.json");
        let reference = register_json(&mut store, &root, &name, &value);
        let observed = store.budget_configuration(&reference).unwrap();
        assert_configuration_is_not_effective(&observed);
        assert_eq!(observed["configured"]["host_class"], host);
        fingerprints.push(observed["host_schema_fingerprint"].as_str().unwrap().to_owned());
        observations.push(observed);
    }
    let unique: std::collections::BTreeSet<_> = fingerprints.iter().collect();
    assert_eq!(unique.len(), 4);
    let mut forged = declaration("local_codex", "gpt-6.1-sol");
    forged["host_schema_fingerprint"] = observations[1]["host_schema_fingerprint"].clone();
    let forged_ref = register_json(&mut store, &root, "foreign-fingerprint.json", &forged);
    assert_eq!(store.budget_configuration(&forged_ref).unwrap_err().kind, ErrorKind::Shape);
    let mut forged_observation = declaration("local_codex", "gpt-6.1-sol");
    forged_observation["observed"] = observations[2]["observed"].clone();
    let forged_observation_ref = register_json(&mut store, &root, "foreign-observation.json", &forged_observation);
    assert_eq!(store.budget_configuration(&forged_observation_ref).unwrap_err().kind, ErrorKind::Shape);
    let source_ref: ExactRef = serde_json::from_value(observations[0]["source_ref"].clone()).unwrap();
    let (other_root, mut other) = workspace("other-host-source");
    let other_ref = register_json(&mut other, &other_root, "local_codex.json", &declaration("local_codex", "gpt-6.1-sol"));
    assert_eq!(other_ref.sha256, source_ref.sha256);
    assert_eq!(other.budget_configuration(&source_ref).unwrap_err().kind, ErrorKind::ScopeDenied);
    assert_ne!(other.budget_configuration(&other_ref).unwrap()["host_schema_fingerprint"], observations[0]["host_schema_fingerprint"]);
}

#[test]
fn budget_updates_invalidate_old_exact_sources_and_do_not_revive_old_observations() {
    let (root, mut store) = workspace("budget-update");
    let first = declaration("local_codex", "gpt-6.1-sol");
    let reference = register_json(&mut store, &root, "budget.json", &first);
    let old_observation = store.budget_configuration(&reference).unwrap();
    let mut updated = declaration("managed_api", "gpt-6.1-sol");
    updated["config_revision"] = json!(2);
    fs::write(root.join("budget.json"), serde_json::to_vec(&updated).unwrap()).unwrap();
    assert_eq!(store.budget_configuration(&reference).unwrap_err().kind, ErrorKind::ValidationStale);
    let next = store.register_local_input("budget.json", Path::new("budget.json")).unwrap();
    assert!(next.revision > reference.revision);
    let next_observation = store.budget_configuration(&next).unwrap();
    assert_configuration_is_not_effective(&next_observation);
    assert_ne!(next_observation["host_schema_fingerprint"], old_observation["host_schema_fingerprint"]);
    assert_eq!(store.budget_configuration(&reference).unwrap_err().kind, ErrorKind::ValidationStale);
    fs::write(root.join("budget.json"), serde_json::to_vec(&first).unwrap()).unwrap();
    assert_eq!(store.budget_configuration(&next).unwrap_err().kind, ErrorKind::ValidationStale);
    assert_eq!(store.budget_configuration(&reference).unwrap_err().kind, ErrorKind::ValidationStale);
    let restored = store.register_local_input("budget.json", Path::new("budget.json")).unwrap();
    assert!(restored.revision > next.revision);
    assert_ne!(store.budget_configuration(&restored).unwrap()["host_schema_fingerprint"], old_observation["host_schema_fingerprint"]);
    drop(store);
    let reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.budget_configuration(&reference).unwrap_err().kind, ErrorKind::ValidationStale);
    assert_configuration_is_not_effective(&reopened.budget_configuration(&restored).unwrap());
}

#[test]
fn another_models_declared_272000_window_never_becomes_requested_model_or_directory_budget() {
    let (root, mut store) = workspace("foreign-model-window");
    let mut value = declaration("managed_api", "different-model");
    value["values"]["configured_context_window"] = json!(272000);
    let reference = register_json(&mut store, &root, "foreign-model.json", &value);
    let observation = store.budget_configuration(&reference).unwrap();
    assert_configuration_is_not_effective(&observation);
    assert_eq!(observation["configured"]["model"], "different-model");
    assert_eq!(observation["configured"]["values"]["configured_context_window"], 272000);
    assert_eq!(observation["effective"]["directory_budget"], "unknown");
    assert_eq!(observation["effective"]["context_window"], "unknown");
}

#[test]
fn budget_declarations_reject_effective_injection_unknown_fields_and_invalid_shapes() {
    let (root, mut store) = workspace("budget-shapes");
    let original = declaration("local_codex", "gpt-6.1-sol");
    let mut invalid = Vec::new();
    for field in ["effective", "observed", "execution_authority", "requested_model", "extra"] {
        let mut value = original.clone();
        value[field] = json!({"context_window":272000,"directory_budget":5440,"model":"other","effort":"high"});
        invalid.push(value);
    }
    for field in ["effective", "effective_context_window", "effort", "quota", "extra"] {
        let mut value = original.clone();
        value["values"][field] = json!(5440);
        invalid.push(value);
    }
    for schema in [0, 2] {
        let mut value = original.clone();
        value["schema_version"] = json!(schema);
        invalid.push(value);
    }
    let mut zero_revision = original.clone();
    zero_revision["config_revision"] = json!(0);
    invalid.push(zero_revision);
    let mut bad_host = original.clone();
    bad_host["host_class"] = json!("unknown-host");
    invalid.push(bad_host);
    for model in ["".to_owned(), " ".to_owned(), " model".to_owned(), "model\n".to_owned(), "x".repeat(129), "界".repeat(43)] {
        let mut value = original.clone();
        value["model"] = json!(model);
        invalid.push(value);
    }
    for scope in ["".to_owned(), " task".to_owned(), "task\n".to_owned(), "x".repeat(129)] {
        let mut value = original.clone();
        value["values"]["auto_compact_scope"] = json!(scope);
        invalid.push(value);
    }
    for field in ["tool_output_token_limit", "model_auto_compact_token_limit", "configured_context_window", "skills_max_context_tokens", "max_threads"] {
        for supplied in [json!(-1), json!(1.5), json!("90000"), json!(true)] {
            let mut value = original.clone();
            value["values"][field] = supplied;
            invalid.push(value);
        }
    }
    for (index, value) in invalid.iter().enumerate() {
        let name = format!("invalid-{index}.json");
        let reference = register_json(&mut store, &root, &name, value);
        assert_eq!(store.budget_configuration(&reference).unwrap_err().kind, ErrorKind::Shape, "invalid declaration {index}");
    }
    let duplicate = br#"{"schema_version":1,"host_class":"local_codex","model":"gpt-6.1-sol","config_revision":1,"values":{"max_threads":3,"max_threads":7}}"#;
    let duplicate_ref = register_bytes(&mut store, &root, "duplicate.json", duplicate);
    assert_eq!(store.budget_configuration(&duplicate_ref).unwrap_err().kind, ErrorKind::Shape);
}

#[test]
fn budget_configuration_requires_exact_registered_isolated_project_evidence() {
    let (root, mut store) = workspace("budget-registration");
    let reference = register_json(&mut store, &root, "budget.json", &declaration("test_local", "gpt-6.1-sol"));
    let mut wrong_scope = reference.clone();
    wrong_scope.scope = "project/other".into();
    assert_eq!(store.budget_configuration(&wrong_scope).unwrap_err().kind, ErrorKind::ScopeDenied);
    let mut unregistered = reference.clone();
    unregistered.id = "unregistered/budget".into();
    assert_eq!(store.budget_configuration(&unregistered).unwrap_err().kind, ErrorKind::Reference);
    let mut wrong_hash = reference.clone();
    wrong_hash.sha256 = "0".repeat(64);
    assert_eq!(store.budget_configuration(&wrong_hash).unwrap_err().kind, ErrorKind::ValidationStale);
    let mut wrong_release = reference.clone();
    wrong_release.release = "foreign-budget-release".into();
    assert_eq!(store.budget_configuration(&wrong_release).unwrap_err().kind, ErrorKind::ValidationStale);
    let outside = std::env::temp_dir().join(unique_name("wuji-budget-outside-dev"));
    fs::create_dir_all(&outside).unwrap();
    let mut outside_store = Store::open(&outside).unwrap();
    let outside_ref = register_json(&mut outside_store, &outside, "budget.json", &declaration("local_codex", "gpt-6.1-sol"));
    assert_eq!(outside_store.budget_configuration(&outside_ref).unwrap_err().kind, ErrorKind::ScopeDenied);
}
