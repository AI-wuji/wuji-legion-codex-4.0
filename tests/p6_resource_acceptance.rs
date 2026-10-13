use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::resources::{LocalResourceReviewPermit, ResourceKind};
use wuji4::store::Store;
use wuji4::strict_json;

fn workspace(label: &str) -> PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/resource-acceptance")
        .join(format!("{}-{}-{}", label,std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(&root).unwrap();
    root
}

fn seal(envelope: &mut Value) {
    envelope["metadata"]["content_hash"] = json!(strict_json::object_digest(envelope).unwrap());
}

fn metadata(id: &str, kind: &str, scope: &str, revision: u64) -> Value {
    json!({"id":id,"type":kind,"scope":scope,"schema_version":1,"revision":revision,
        "owner":"aji-local","authority":"review_proposal","status":"proposal",
        "source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,"updated_at_utc_ms":1,
        "valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]})
}

fn knowledge(store: &Store, source: &ExactRef, revision: u64) -> Value {
    let mut value = json!({"schema_version":1,"contract_type":"KnowledgeRecord",
        "metadata":metadata("knowledge/method", "KnowledgeRecord", store.scope(),revision),
        "payload":{"knowledge_id":"knowledge/method","scope":store.scope(),"source_refs":[source],
            "location":"source.txt:1","sha256":source.sha256,"authority":"review_proposal",
            "claim":"A source-bound, project-private method proposal","method":"Check current source before reuse",
            "derived_refs":[],"freshness":"current","conflicts":[]}});
    seal(&mut value);
    value
}

fn experience(store: &Store, source: &ExactRef, knowledge: &ExactRef, revision: u64) -> Value {
    let mut value = json!({"schema_version":1,"contract_type":"ExperienceCandidate",
        "metadata":metadata("experience/regression", "ExperienceCandidate", store.scope(),revision),
        "payload":{"scope":store.scope(),"trigger":"software-repair","method":"Preserve a regression tied to this project",
            "evidence":[source],"counterexamples":["Not a general user preference or universal factual claim"],
            "expiry_utc_ms":null,"type":"failure_condition","knowledge_refs":[knowledge]}});
    seal(&mut value);
    value
}

fn setup(label: &str) -> (PathBuf, Store, ExactRef, LocalResourceReviewPermit) {
    let root = workspace(label);
    fs::write(root.join("source.txt"), b"source evidence").unwrap();
    let mut store = Store::open(&root).unwrap();
    let source = store.register_local_input("user/evidence", Path::new("source.txt")).unwrap();
    let permit = LocalResourceReviewPermit::confirm_isolated(&root,"confirm-isolated-project-resource-review").unwrap();
    (root,store,source,permit)
}

fn propose_reviewed_knowledge(store: &mut Store, source: &ExactRef, permit: &LocalResourceReviewPermit) -> ExactRef {
    let envelope = knowledge(store,source,1);
    let result = store.propose_resource(ResourceKind::Knowledge,&envelope,0,"knowledge-propose").unwrap();
    let reference: ExactRef = serde_json::from_value(result["reference"].clone()).unwrap();
    store.review_resource_local(permit,ResourceKind::Knowledge,&reference,"knowledge-review").unwrap();
    reference
}

#[test]
fn resource_candidates_persist_without_automatic_activation() {
    let (root,mut store,source,_) = setup("persist");
    let envelope = knowledge(&store,&source,1);
    let first = store.propose_resource(ResourceKind::Knowledge,&envelope,0,"candidate-1").unwrap();
    assert_eq!(first["state"],"candidate");
    assert_eq!(first["runtime_admission"],false);
    assert_eq!(store.propose_resource(ResourceKind::Knowledge,&envelope,0,"candidate-1").unwrap(),first);
    drop(store);
    let mut reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.propose_resource(ResourceKind::Knowledge,&envelope,0,"candidate-1").unwrap(),first);
    assert_eq!(reopened.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"].as_array().unwrap().len(),0);
    let mut changed = envelope;
    changed["payload"]["claim"] = json!("Different payload with the same event key");
    seal(&mut changed);
    assert_eq!(reopened.propose_resource(ResourceKind::Knowledge,&changed,0,"candidate-1").unwrap_err().kind,ErrorKind::EventConflict);
}

#[test]
fn resource_knowledge_experience_and_project_scope_are_distinct() {
    let (root,mut store,source,permit) = setup("types");
    let knowledge_ref = propose_reviewed_knowledge(&mut store,&source,&permit);
    let envelope = experience(&store,&source,&knowledge_ref,1);
    let reference: ExactRef = serde_json::from_value(store.propose_resource(ResourceKind::Experience,&envelope,0,"experience-propose").unwrap()["reference"].clone()).unwrap();
    store.review_resource_local(&permit,ResourceKind::Experience,&reference,"experience-review").unwrap();
    assert_eq!(store.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"].as_array().unwrap().len(),1);
    assert_eq!(store.query_resources(ResourceKind::Experience,"software-repair",8).unwrap()["entries"].as_array().unwrap().len(),1);
    assert_eq!(store.query_resources(ResourceKind::Experience,"unrelated",8).unwrap()["entries"].as_array().unwrap().len(),0);
    assert_eq!(store.propose_resource(ResourceKind::Knowledge,&envelope,0,"wrong-kind").unwrap_err().kind,ErrorKind::Shape);
    drop(store);
    let reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.query_resources(ResourceKind::Experience,"software-repair",8).unwrap()["entries"].as_array().unwrap().len(),1);
    let (_,mut other,_,_) = setup("other-project");
    assert_eq!(other.propose_resource(ResourceKind::Experience,&envelope,0,"cross-scope").unwrap_err().kind,ErrorKind::ScopeDenied);
    assert_eq!(other.review_resource_local(&permit,ResourceKind::Experience,&reference,"cross-permit").unwrap_err().kind,ErrorKind::ScopeDenied);
}

#[test]
fn t23_retired_experience_never_reappears_after_query_or_reopen() {
    let (root,mut store,source,permit) = setup("retirement");
    let knowledge_ref = propose_reviewed_knowledge(&mut store,&source,&permit);
    let envelope = experience(&store,&source,&knowledge_ref,1);
    let reference: ExactRef = serde_json::from_value(store.propose_resource(ResourceKind::Experience,&envelope,0,"experience-propose").unwrap()["reference"].clone()).unwrap();
    store.review_resource_local(&permit,ResourceKind::Experience,&reference,"experience-review").unwrap();
    assert_eq!(store.query_resources(ResourceKind::Experience,"software-repair",8).unwrap()["entries"].as_array().unwrap().len(),1);
    let retired = store.retire_resource(ResourceKind::Experience,&reference,"retire-exp").unwrap();
    assert_eq!(store.retire_resource(ResourceKind::Experience,&reference,"retire-exp").unwrap(),retired);
    assert_eq!(store.query_resources(ResourceKind::Experience,"software-repair",8).unwrap()["entries"].as_array().unwrap().len(),0);
    assert_eq!(store.review_resource_local(&permit,ResourceKind::Experience,&reference,"resurrect-exp").unwrap_err().kind,ErrorKind::RevisionConflict);
    drop(store);
    let reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.query_resources(ResourceKind::Experience,"software-repair",8).unwrap()["entries"].as_array().unwrap().len(),0);
    assert_eq!(reopened.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"].as_array().unwrap().len(),1);
}

#[test]
fn source_change_and_knowledge_retirement_invalidate_linked_experience() {
    let (root,mut store,source,permit) = setup("source-change");
    let knowledge_ref = propose_reviewed_knowledge(&mut store,&source,&permit);
    let envelope = experience(&store,&source,&knowledge_ref,1);
    let reference: ExactRef = serde_json::from_value(store.propose_resource(ResourceKind::Experience,&envelope,0,"experience-propose").unwrap()["reference"].clone()).unwrap();
    store.review_resource_local(&permit,ResourceKind::Experience,&reference,"experience-review").unwrap();
    fs::write(root.join("source.txt"),b"new evidence").unwrap();
    for kind in [ResourceKind::Knowledge,ResourceKind::Experience] {
        let result = store.query_resources(kind,"",8).unwrap();
        assert!(result["entries"].as_array().unwrap().is_empty());
        assert_eq!(result["rejected"].as_array().unwrap().len(),1);
    }
    fs::write(root.join("source.txt"),b"source evidence").unwrap();
    store.retire_resource(ResourceKind::Knowledge,&knowledge_ref,"retire-knowledge").unwrap();
    let result = store.query_resources(ResourceKind::Experience,"software-repair",8).unwrap();
    assert!(result["entries"].as_array().unwrap().is_empty());
    assert_eq!(result["rejected"].as_array().unwrap().len(),1);
}

#[test]
fn resource_updates_are_cas_and_not_public_authority() {
    let (_,mut store,source,permit) = setup("revision");
    let first = propose_reviewed_knowledge(&mut store,&source,&permit);
    let mut revised = knowledge(&store,&source,2);
    revised["payload"]["claim"] = json!("Revised scoped candidate");
    seal(&mut revised);
    assert_eq!(store.propose_resource(ResourceKind::Knowledge,&revised,0,"bad-cas").unwrap_err().kind,ErrorKind::RevisionConflict);
    let second: ExactRef = serde_json::from_value(store.propose_resource(ResourceKind::Knowledge,&revised,1,"good-cas").unwrap()["reference"].clone()).unwrap();
    assert_eq!(store.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"][0]["reference"]["revision"],1);
    store.review_resource_local(&permit,ResourceKind::Knowledge,&second,"review-second").unwrap();
    assert_eq!(store.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"][0]["reference"]["revision"],2);
    assert_eq!(store.review_resource_local(&permit,ResourceKind::Knowledge,&first,"revive-first").unwrap_err().kind,ErrorKind::RevisionConflict);
    let mut forged = knowledge(&store,&source,3);
    forged["metadata"]["authority"] = json!("user_explicit");
    seal(&mut forged);
    assert_eq!(store.propose_resource(ResourceKind::Knowledge,&forged,2,"self-authorize").unwrap_err().kind,ErrorKind::AuthorityDenied);
}

#[test]
fn empty_evidence_false_hash_and_missing_counterexamples_fail_closed() {
    let (_,mut store,source,permit) = setup("untrusted");
    let mut invalid = knowledge(&store,&source,1);
    invalid["payload"]["source_refs"] = json!([]);
    seal(&mut invalid);
    assert_eq!(store.propose_resource(ResourceKind::Knowledge,&invalid,0,"empty-evidence").unwrap_err().kind,ErrorKind::Reference);
    let mut invalid = knowledge(&store,&source,1);
    invalid["payload"]["sha256"] = json!("0".repeat(64));
    seal(&mut invalid);
    assert_eq!(store.propose_resource(ResourceKind::Knowledge,&invalid,0,"false-hash").unwrap_err().kind,ErrorKind::HashMismatch);
    let knowledge_ref = propose_reviewed_knowledge(&mut store,&source,&permit);
    let mut invalid = experience(&store,&source,&knowledge_ref,1);
    invalid["payload"]["counterexamples"] = json!([]);
    seal(&mut invalid);
    assert_eq!(store.propose_resource(ResourceKind::Experience,&invalid,0,"no-counterexample").unwrap_err().kind,ErrorKind::Shape);
}
