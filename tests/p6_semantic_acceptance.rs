use serde_json::{Value, json};
use std::collections::BTreeMap;
use wuji4::composer::PreparedCatalog;
use wuji4::error::ErrorKind;
use wuji4::graph::{Edge, ExactRef, dependency_order};
use wuji4::strict_json;

fn fragment(id: &str, revision: u64, dependencies: Vec<ExactRef>, fields: Value,
    required: Vec<&str>, slots: Value) -> (ExactRef, Vec<u8>) {
    let bytes = strict_json::canonical(&json!({
        "id": id, "scope": "project:p6-acceptance", "revision": revision,
        "release": "p6-test-1", "dependencies": dependencies, "conflicts": [],
        "fields": fields, "required_fields": required, "allowed_slots": slots,
    })).unwrap();
    let reference = ExactRef {
        id: id.to_owned(), r#type: "file".to_owned(),
        scope: "project:p6-acceptance".to_owned(), revision,
        sha256: strict_json::sha256(&bytes), release: "p6-test-1".to_owned(), schema_version: 1,
    };
    (reference, bytes)
}

fn diamond() -> Vec<(ExactRef, Vec<u8>)> {
    let base = fragment("white-hat", 1, vec![], json!({"authorization_required": true}),
        vec!["authorization_required"], json!({}));
    let engineering = fragment("engineering", 1, vec![base.0.clone()],
        json!({"engineering_check": "regression"}), vec![], json!({}));
    let validation = fragment("validation", 1, vec![base.0.clone()],
        json!({"validation_check": "independent"}), vec![], json!({}));
    let lead = fragment("lead", 1, vec![validation.0.clone(), engineering.0.clone()],
        json!({"output": "editable-artifact"}), vec![], json!({"tone": "string"}));
    vec![base, engineering, validation, lead]
}

fn catalog(entries: &[(ExactRef, Vec<u8>)], roots: Vec<ExactRef>) -> PreparedCatalog {
    let mut prepared = PreparedCatalog::new("project:p6-acceptance", "p6-test-1", roots);
    for (reference, bytes) in entries {
        prepared.register_derived_fragment(reference.clone(), bytes).unwrap();
    }
    prepared
}

#[test]
fn t46_deterministic_compilation_and_field_origins() {
    let entries = diamond();
    let root = entries[3].0.clone();
    let first = catalog(&entries, vec![root.clone()])
        .compose(&[root.clone()], &BTreeMap::new(), 64 * 1024).unwrap();
    let mut reversed = entries.clone();
    reversed.reverse();
    let second = catalog(&reversed, vec![root.clone()])
        .compose(&[root.clone()], &BTreeMap::new(), 64 * 1024).unwrap();
    assert_eq!(strict_json::canonical(&first).unwrap(), strict_json::canonical(&second).unwrap());
    assert_eq!(first["composition_hash"], second["composition_hash"]);
    assert_eq!(first["lock"].as_array().unwrap().len(), 4);
    for (reference, _) in &entries {
        assert!(!first["origin_paths"][&reference.id].as_array().unwrap().is_empty());
    }
    for field in first["fields"].as_object().unwrap().keys() {
        assert!(!first["field_origins"][field].as_array().unwrap().is_empty());
    }
    let mut changed = entries.clone();
    changed[3] = fragment("lead", 2, vec![entries[1].0.clone(), entries[2].0.clone()],
        json!({"output": "different-artifact"}), vec![], json!({"tone": "string"}));
    let changed_root = changed[3].0.clone();
    let result = catalog(&changed, vec![changed_root.clone()])
        .compose(&[changed_root], &BTreeMap::new(), 64 * 1024).unwrap();
    assert_ne!(first["composition_hash"], result["composition_hash"]);
    assert_eq!(first["runtime_admission"], false);
}

#[test]
fn t47_diamond_deduplication_and_incompatible_versions() {
    let entries = diamond();
    let root = entries[3].0.clone();
    let mut prepared = catalog(&entries, vec![root.clone()]);
    let result = prepared.compose(&[root.clone(), root], &BTreeMap::new(), 64 * 1024).unwrap();
    assert_eq!(result["lock"].as_array().unwrap().len(), 4);
    assert_eq!(result["origin_paths"]["white-hat"].as_array().unwrap().len(), 2);
    let alternate = fragment("white-hat", 2, vec![],
        json!({"authorization_required": true}), vec!["authorization_required"], json!({}));
    assert_eq!(prepared.register_derived_fragment(alternate.0, &alternate.1).unwrap_err().kind,
        ErrorKind::CompositionConflict);
    let unrestricted = catalog(&entries, vec![]);
    let mut obsolete = entries[0].0.clone();
    obsolete.revision = 2;
    assert_eq!(unrestricted.compose(&[obsolete], &BTreeMap::new(), 64 * 1024).unwrap_err().kind,
        ErrorKind::Reference);
}

#[test]
fn t48_cycles_and_missing_references_stop_preparation() {
    let nodes = vec!["base".to_owned(), "lead".to_owned()];
    let forward = Edge { from: "base".to_owned(), to: "lead".to_owned(),
        predicate: "depends-on".to_owned() };
    assert_eq!(dependency_order(&nodes, &[forward.clone()]).unwrap(), nodes);
    let backward = Edge { from: "lead".to_owned(), to: "base".to_owned(),
        predicate: "depends-on".to_owned() };
    let error = dependency_order(&nodes, &[forward, backward]).unwrap_err();
    assert_eq!(error.kind, ErrorKind::DependencyCycle);
    assert!(error.detail.contains("base -> lead -> base"));
    let entries = diamond();
    let root = entries[3].0.clone();
    let incomplete = catalog(&entries[1..], vec![root.clone()]);
    let error = incomplete.compose(&[root], &BTreeMap::new(), 64 * 1024).unwrap_err();
    assert_eq!(error.kind, ErrorKind::Reference);
    assert!(error.detail.contains("missing"));
    assert!(error.detail.contains("white-hat@1"));
}

#[test]
fn t49_allowed_slots_preserve_white_hat_and_acceptance() {
    let entry = fragment("professional", 1, vec![], json!({
        "authorization_required": true, "acceptance_required": true,
        "professional_method": "engineering-regression",
    }), vec!["authorization_required", "acceptance_required"],
        json!({"tone": "string", "authorization_required": "boolean", "acceptance_required": "boolean"}));
    let prepared = catalog(&[entry.clone()], vec![entry.0.clone()]);
    let allowed = BTreeMap::from([("tone".to_owned(), json!("concise"))]);
    let result = prepared.compose(&[entry.0.clone()], &allowed, 64 * 1024).unwrap();
    assert_eq!(result["fields"]["authorization_required"], true);
    assert_eq!(result["fields"]["acceptance_required"], true);
    assert_eq!(result["fields"]["professional_method"], "engineering-regression");
    for field in ["authorization_required", "acceptance_required"] {
        let weakening = BTreeMap::from([(field.to_owned(), json!(false))]);
        assert_eq!(prepared.compose(&[entry.0.clone()], &weakening, 64 * 1024).unwrap_err().kind,
            ErrorKind::RequiredWeakened);
    }
    let undeclared = BTreeMap::from([("professional_method".to_owned(), json!("generic"))]);
    assert_eq!(prepared.compose(&[entry.0.clone()], &undeclared, 64 * 1024).unwrap_err().kind,
        ErrorKind::CompositionConflict);
    assert_eq!(prepared.compose(&[], &BTreeMap::new(), 64 * 1024).unwrap_err().kind,
        ErrorKind::RequiredWeakened);
}
