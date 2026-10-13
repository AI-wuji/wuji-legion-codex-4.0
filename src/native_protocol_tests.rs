use super::*;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn fixture() -> (PathBuf, Value) {
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".dev/core-test-workspaces").join(format!("native-prepared-{}-{stamp}", std::process::id()));
    fs::create_dir_all(&root).unwrap();
    fs::write(root.join("source.txt"), b"declared test input; no model called").unwrap();
    let roles = prepared_roles(&root).unwrap();
    let scope = roles["scope"].as_str().unwrap();
    let input = json!({"id":"user/source","type":"file","scope":scope,"revision":1,"sha256":strict_json::sha256(b"declared test input; no model called"),"release":PREPARATION_RELEASE,"schema_version":1});
    let nodes: Vec<_> = roles["roles"].as_array().unwrap().iter().map(|entry| {
        let role = &entry["candidate"];
        let kind = entry["kind"].as_str().unwrap();
        json!({"id":kind,"role_ref":entry["reference"],"owner":format!("p2-{kind}"),"revision":1,"inputs":[input.clone()],"read_roots":["source.txt"],"write_roots":[format!("{kind}-result.txt")],"acceptance_ids":role["required_checks"],"status":"planned","execution_form":"model"})
    }).collect();
    let mut envelope = json!({"schema_version":1,"contract_type":"WorkflowPlan","payload":{"workflow_id":"native-prepared-test","version":"1","catalog_version":PREPARATION_RELEASE,"nodes":nodes,"edges":[{"from":"engineering","to":"validation","predicate":"depends-on"}],"budget":{"max_candidates":8,"max_query_objects":20,"max_hops":3,"target_contract_bytes":1024,"target_evidence_bytes":1024,"hard_bytes_limit":null,"measured_tokens":null,"effective_token_limit":null,"wall_ms":60000,"max_parallel_workers":2,"max_extra_retries":6,"max_point_revisions":2,"max_no_progress":2}},"metadata":{"id":"native-prepared-test","type":"WorkflowPlan","scope":scope,"schema_version":1,"revision":1,"owner":"aji-local","authority":"review_proposal","status":"proposal","source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,"updated_at_utc_ms":1,"valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]}});
    seal(&mut envelope);
    (root, envelope)
}

fn seal(envelope: &mut Value) { envelope["metadata"]["content_hash"] = strict_json::object_digest(envelope).unwrap().into(); }

fn assert_error(root: &Path, envelope: &mut Value, expected: ErrorKind) {
    seal(envelope);
    let error = prepare(root, envelope, "engineering", InvocationKind::Code).err().unwrap();
    assert_eq!(error.kind, expected, "{error}");
}

#[test]
fn text_inherits_and_explicit_upgrade_requests_do_not_use_fallback() {
    assert_eq!(REQUESTED_MODEL, "gpt-6.1-sol");
    for (kind, effort) in [(InvocationKind::Text,"inherit"),(InvocationKind::Code,"high"),(InvocationKind::Repair,"xhigh"),(InvocationKind::Planning,"xhigh")] { assert_eq!(kind.requested_effort(), effort); }
    for forbidden in ["gpt-6.1-sol", "auto", "low", "gpt-5.5"] { assert_eq!(InvocationKind::parse(forbidden).unwrap_err().kind, ErrorKind::Shape); }
}

#[test]
fn two_candidates_have_five_elements_and_remain_unadmitted() {
    let (root, _) = fixture();
    let roles = prepared_roles(&root).unwrap();
    assert_eq!(roles["roles"].as_array().unwrap().len(), 2);
    for entry in roles["roles"].as_array().unwrap() {
        for field in ["goal","inputs","process","output","acceptance"] { assert!(!entry["candidate"]["five_elements"][field].is_null()); }
        assert_eq!(entry["candidate"]["runtime_admission"], false);
        assert_eq!(entry["candidate"]["effectiveness"], "not_run");
    }
    assert!(!root.join(".wuji4").exists());
}

#[test]
fn native_candidate_is_deterministic_read_only_and_cannot_dispatch() {
    let (root, envelope) = fixture();
    let prepared = prepare(&root,&envelope,"engineering",InvocationKind::Code).unwrap();
    let repeated = prepare(&root,&envelope,"engineering",InvocationKind::Code).unwrap();
    assert_eq!(prepared.report(), repeated.report());
    assert_eq!(prepared.ensure_dispatchable().unwrap_err().kind, ErrorKind::HostUnknown);
    let report = prepared.report();
    assert_eq!(report["candidate_messages"]["thread_start"]["params"]["model"], REQUESTED_MODEL);
    assert_eq!(report["candidate_messages"]["turn_start_unbound"]["params"]["effort"], "high");
    assert_eq!(report["candidate_messages"]["thread_start"]["params"]["sandbox"], "read-only");
    assert_eq!(report["candidate_messages"]["turn_start_unbound"]["params"]["sandboxPolicy"]["networkAccess"], false);
    assert_eq!(report["runtime_admission"], false);
    assert_eq!(report["effective"]["model"], "unknown");
    assert!(!root.join("engineering-result.txt").exists());
    assert!(!root.join(".wuji4").exists());
    assert_eq!(prepare(&root,&envelope,"engineering",InvocationKind::Repair).unwrap().report()["requested_effort"], "xhigh");

}

#[test]
fn imported_model_authority_or_host_receipt_is_not_accepted() {
    let (root, mut envelope) = fixture();
    envelope["metadata"]["authority"] = "user_explicit".into();
    assert_error(&root,&mut envelope,ErrorKind::AuthorityDenied);
    envelope["metadata"]["authority"] = "review_proposal".into();
    envelope["payload"]["effective_model"] = REQUESTED_MODEL.into();
    assert_error(&root,&mut envelope,ErrorKind::Shape);
    envelope["payload"].as_object_mut().unwrap().remove("effective_model");
    envelope["payload"]["host_receipt"] = json!({"fee":0,"closed":true});
    assert_error(&root,&mut envelope,ErrorKind::Shape);
}

#[test]
fn stale_role_or_omitted_hard_check_cannot_prepare() {
    let (root, mut envelope) = fixture();
    envelope["payload"]["nodes"][0]["role_ref"]["sha256"] = "a".repeat(64).into();
    assert_error(&root,&mut envelope,ErrorKind::Reference);
    let (root, mut envelope) = fixture();
    envelope["payload"]["nodes"][0]["acceptance_ids"].as_array_mut().unwrap().pop();
    assert_error(&root,&mut envelope,ErrorKind::RequiredWeakened);
}

#[test]
fn scope_and_release_are_exact_even_for_preparation() {
    let (root, mut envelope) = fixture();
    envelope["payload"]["nodes"][0]["inputs"][0]["scope"] = "project:elsewhere".into();
    assert_error(&root,&mut envelope,ErrorKind::ScopeDenied);
    let (root, mut envelope) = fixture();
    envelope["payload"]["catalog_version"] = "active".into();
    assert_error(&root,&mut envelope,ErrorKind::Reference);
}

#[test]
fn validator_is_independent_with_required_producer_dependency() {
    let (root, mut envelope) = fixture();
    let review = prepare(&root,&envelope,"validation",InvocationKind::Code).unwrap();
    assert_eq!(review.report()["requested_effort"], "high");
    assert_eq!(prepare(&root,&envelope,"validation",InvocationKind::Repair).err().unwrap().kind, ErrorKind::Reference);
    envelope["payload"]["nodes"][1]["owner"] = "p2-engineering".into();
    assert_error(&root,&mut envelope,ErrorKind::SelfReview);
    envelope["payload"]["nodes"][1]["owner"] = "p2-validation".into();
    envelope["payload"]["edges"] = json!([]);
    assert_error(&root,&mut envelope,ErrorKind::DependencyNotAccepted);
}

#[test]
fn unsafe_paths_missing_inputs_and_cycles_are_independent_failures() {
    let (root, mut envelope) = fixture();
    envelope["payload"]["nodes"][0]["write_roots"] = json!([".codex/config.toml"]);
    assert_error(&root,&mut envelope,ErrorKind::PathDenied);
    envelope["payload"]["nodes"][0]["write_roots"] = json!(["source.txt"]);
    assert_error(&root,&mut envelope,ErrorKind::PathDenied);
    envelope["payload"]["nodes"][0]["write_roots"] = json!(["engineering-result.txt"]);
    envelope["payload"]["nodes"][0]["inputs"] = json!([]);
    assert_error(&root,&mut envelope,ErrorKind::Shape);
    let (root, mut envelope) = fixture();
    envelope["payload"]["edges"].as_array_mut().unwrap().push(json!({"from":"validation","to":"engineering","predicate":"depends-on"}));
    assert_error(&root,&mut envelope,ErrorKind::DependencyCycle);
}

#[test]
fn hard_byte_budget_rejects_without_silent_truncation() {
    let (root, mut envelope) = fixture();
    envelope["payload"]["budget"]["hard_bytes_limit"] = 1.into();
    assert_error(&root,&mut envelope,ErrorKind::BudgetExhausted);
}

#[test]
fn text_preparation_omits_model_and_effort_without_claiming_effective_inheritance() {
    let (root, envelope) = fixture();
    let prepared = prepare(&root, &envelope, "engineering", InvocationKind::Text).unwrap();
    let report = prepared.report();
    assert_eq!(report, prepare(&root, &envelope, "engineering", InvocationKind::Text).unwrap().report());
    assert_eq!(report["requested_model"], "inherit_current_selection");
    assert_eq!(report["requested_effort"], "inherit");
    for message in ["thread_start", "turn_start_unbound"] {
        let params = report["candidate_messages"][message]["params"].as_object().unwrap();
        assert!(!params.contains_key("model"));
        assert!(!params.contains_key("effort"));
        assert!(!params.contains_key("config"));
        assert_eq!(params["approvalPolicy"], "never");
    }
    assert_eq!(report["candidate_messages"]["thread_start"]["params"]["sandbox"], "read-only");
    assert_eq!(report["candidate_messages"]["turn_start_unbound"]["params"]["sandboxPolicy"]["networkAccess"], false);
    let expected_hash = strict_json::digest(&json!({
        "thread": report["candidate_messages"]["thread_start"],
        "turn": report["candidate_messages"]["turn_start_unbound"]
    })).unwrap();
    assert_eq!(report["request_template_hash"], expected_hash);
    assert_eq!(report["role_ref"], envelope["payload"]["nodes"][0]["role_ref"]);
    assert_eq!(report["plan_object_hash"], strict_json::object_digest(&envelope).unwrap());
    assert_eq!(report["state"], "prepared");
    assert_eq!(report["runtime_admission"], false);
    assert_eq!(report["dispatchable"], false);
    assert_eq!(report["generation_submitted"], false);
    assert_eq!(report["effective"]["model"], "unknown");
    assert_eq!(report["effective"]["effort"], "unknown");
    let boundary = report["selection_boundary"].as_str().unwrap();
    assert!(boundary.contains("current conversation"));
    assert!(boundary.contains("not an independent CLI disk default"));
    assert_eq!(prepared.ensure_dispatchable().unwrap_err().kind, ErrorKind::HostUnknown);
    assert!(!root.join("engineering-result.txt").exists());
    assert!(!root.join(".wuji4").exists());
}

#[test]
fn explicit_upgrade_preparations_preserve_high_and_xhigh_without_claiming_selection() {
    let (root, envelope) = fixture();
    for (kind, effort) in [(InvocationKind::Code, "high"), (InvocationKind::Repair, "xhigh"), (InvocationKind::Planning, "xhigh")] {
        let prepared = prepare(&root, &envelope, "engineering", kind).unwrap();
        let report = prepared.report();
        assert_eq!(report["requested_model"], REQUESTED_MODEL);
        assert_eq!(report["requested_effort"], effort);
        assert_eq!(report["candidate_messages"]["thread_start"]["params"]["model"], REQUESTED_MODEL);
        assert_eq!(report["candidate_messages"]["turn_start_unbound"]["params"]["model"], REQUESTED_MODEL);
        assert_eq!(report["candidate_messages"]["turn_start_unbound"]["params"]["effort"], effort);
        assert_eq!(report["effective"]["model"], "unknown");
        assert_eq!(report["effective"]["effort"], "unknown");
        let boundary = report["selection_boundary"].as_str().unwrap();
        assert!(boundary.contains("explicit user-requested"));
        assert!(boundary.contains("not automatic difficulty classification"));
        assert!(boundary.contains("downgrade"));
        assert_eq!(prepared.ensure_dispatchable().unwrap_err().kind, ErrorKind::HostUnknown);
    }
}

#[test]
fn text_preparation_keeps_scope_budget_and_validator_role_boundaries() {
    let (root, mut envelope) = fixture();
    assert_eq!(prepare(&root, &envelope, "validation", InvocationKind::Text).err().unwrap().kind, ErrorKind::Reference);
    envelope["payload"]["nodes"][0]["inputs"][0]["scope"] = "project:elsewhere".into();
    seal(&mut envelope);
    assert_eq!(prepare(&root, &envelope, "engineering", InvocationKind::Text).err().unwrap().kind, ErrorKind::ScopeDenied);
    let (root, mut envelope) = fixture();
    envelope["payload"]["budget"]["hard_bytes_limit"] = 1.into();
    seal(&mut envelope);
    assert_eq!(prepare(&root, &envelope, "engineering", InvocationKind::Text).err().unwrap().kind, ErrorKind::BudgetExhausted);
}
