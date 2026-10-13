use serde_json::{Value,json};
use std::fs;
use std::path::{Path,PathBuf};
use std::sync::atomic::{AtomicU64,Ordering};
use std::time::{SystemTime,UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::resources::{LocalResourceReviewPermit,ResourceKind};
use wuji4::store::Store;
use wuji4::strict_json;
use wuji4::transfers::LocalTransferPermit;

static ROOT_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn root(label: &str) -> PathBuf {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/transfer-acceptance")
        .join(format!("{label}-{}-{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),ROOT_SEQUENCE.fetch_add(1,Ordering::Relaxed)));
    fs::create_dir(&path).unwrap();
    path
}

fn metadata(store: &Store, id: &str, kind: &str) -> Value {
    json!({"id":id,"type":kind,"scope":store.scope(),"schema_version":1,"revision":1,"owner":"aji-local",
        "authority":"review_proposal","status":"proposal","source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,
        "updated_at_utc_ms":1,"valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]})
}

fn seal(value: &mut Value) { value["metadata"]["content_hash"] = json!(strict_json::object_digest(value).unwrap()); }

fn reviewed(store: &mut Store, kind: ResourceKind, value: &Value, event: &str, path: &Path) -> ExactRef {
    let reference: ExactRef = serde_json::from_value(store.propose_resource(kind,value,0,event).unwrap()["reference"].clone()).unwrap();
    let permit = LocalResourceReviewPermit::confirm_isolated(path,"confirm-isolated-project-resource-review").unwrap();
    store.review_resource_local(&permit,kind,&reference,&format!("review-{event}")).unwrap();
    reference
}

fn setup() -> (PathBuf,PathBuf,Store,Store,Value,ExactRef,LocalTransferPermit) {
    let source_root = root("source");
    let target_root = root("target");
    fs::write(source_root.join("evidence.txt"),b"current transfer evidence").unwrap();
    let mut source = Store::open(&source_root).unwrap();
    let target = Store::open(&target_root).unwrap();
    let evidence = source.register_local_input("user/evidence",Path::new("evidence.txt")).unwrap();
    let mut knowledge = json!({"schema_version":1,"contract_type":"KnowledgeRecord","metadata":metadata(&source,"knowledge/local","KnowledgeRecord"),
        "payload":{"knowledge_id":"knowledge/local","scope":source.scope(),"source_refs":[evidence],"location":"evidence.txt:1","sha256":evidence.sha256,
            "authority":"review_proposal","claim":"A scoped method","method":"Check original evidence before reuse","derived_refs":[],"freshness":"current","conflicts":[]}});
    seal(&mut knowledge);
    let reference = reviewed(&mut source,ResourceKind::Knowledge,&knowledge,"knowledge",&source_root);
    let permit = LocalTransferPermit::confirm(&source_root,&target_root,"confirm-isolated-resource-transfer").unwrap();
    (source_root,target_root,source,target,knowledge,reference,permit)
}

#[test]
fn transfer_crash_windows_keep_one_owner_and_query_target_before_recovery() {
    let (source_root,target_root,mut source,mut target,mut knowledge,reference,permit) = setup();
    source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move-1").unwrap();
    assert!(source.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"].as_array().unwrap().is_empty());
    assert_eq!(target.resource_transfer_ack(&source,&permit,"move-1").unwrap_err().kind,ErrorKind::Reference);
    knowledge["metadata"]["revision"] = json!(2);
    seal(&mut knowledge);
    assert_eq!(source.propose_resource(ResourceKind::Knowledge,&knowledge,1,"update-frozen").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(source.retire_resource(ResourceKind::Knowledge,&reference,"retire-frozen").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(source.finalize_resource_transfer(&target,&permit,"move-1").unwrap_err().kind,ErrorKind::Reference);
    drop(source);
    source = Store::open_existing(&source_root).unwrap();
    let ack = target.accept_resource_transfer(&source,&permit,"move-1").unwrap();
    assert_eq!(ack,target.accept_resource_transfer(&source,&permit,"move-1").unwrap());
    assert_eq!(ack["owner_revision"],1);
    assert_eq!(ack["runtime_or_global_admission"],false);
    drop(target);
    target = Store::open_existing(&target_root).unwrap();
    assert_eq!(target.resource_transfer_ack(&source,&permit,"move-1").unwrap(),ack);
    let finalized = source.finalize_resource_transfer(&target,&permit,"move-1").unwrap();
    assert_eq!(finalized["source_state"],"shared_ref");
    assert_eq!(finalized["source_writable"],false);
    assert_eq!(target.query_received_resource(&source,&permit,"move-1").unwrap()["owning_scope"],target.scope());
    target.retire_received_resource(&source,&permit,"move-1",1,"target-retire").unwrap();
    assert_eq!(target.query_received_resource(&source,&permit,"move-1").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(target.accept_resource_transfer(&source,&permit,"move-1").unwrap()["state"],"retired");
    assert_eq!(source.retire_resource(ResourceKind::Knowledge,&reference,"source-again").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(source.finalize_resource_transfer(&target,&permit,"move-1").unwrap()["ack"]["state"],"retired");
}

#[test]
fn transferred_experience_preserves_exact_knowledge_evidence_counterexamples_and_source_freshness() {
    let (source_root,_,mut source,mut target,knowledge,knowledge_ref,permit) = setup();
    let mut experience = json!({"schema_version":1,"contract_type":"ExperienceCandidate",
        "metadata":metadata(&source,"experience/local","ExperienceCandidate"),
        "payload":{"scope":source.scope(),"trigger":"repair","method":"Use only this observed repair method",
            "evidence":knowledge["payload"]["source_refs"],"counterexamples":["Not universally correct"],
            "expiry_utc_ms":null,"type":"failure_condition","knowledge_refs":[knowledge_ref]}});
    seal(&mut experience);
    let reference = reviewed(&mut source,ResourceKind::Experience,&experience,"experience",&source_root);
    source.begin_resource_transfer(&target,&permit,ResourceKind::Experience,&reference,"move-experience").unwrap();
    target.accept_resource_transfer(&source,&permit,"move-experience").unwrap();
    source.finalize_resource_transfer(&target,&permit,"move-experience").unwrap();
    let queried = target.query_received_resource(&source,&permit,"move-experience").unwrap();
    assert_eq!(queried["envelope"],experience);
    assert_eq!(queried["origin_scope"],source.scope());
    assert_eq!(queried["classification"],"project_private");
    fs::write(source_root.join("evidence.txt"),b"new evidence invalidates both types").unwrap();
    assert_eq!(target.query_received_resource(&source,&permit,"move-experience").unwrap_err().kind,ErrorKind::ValidationStale);
}

#[test]
fn transferred_knowledge_dependency_requires_real_target_ack_and_current_owner_state() {
    let (source_root,target_root,mut source,mut target,knowledge,knowledge_ref,permit) = setup();
    let mut experience = json!({"schema_version":1,"contract_type":"ExperienceCandidate",
        "metadata":metadata(&source,"experience/dependent","ExperienceCandidate"),
        "payload":{"scope":source.scope(),"trigger":"bounded repair","method":"Preserve source provenance and current ownership",
            "evidence":knowledge["payload"]["source_refs"],"counterexamples":["Moved, retired or changed knowledge is not an adopted dependency"],
            "expiry_utc_ms":null,"type":"failure_condition","knowledge_refs":[knowledge_ref]}});
    seal(&mut experience);
    let reference = reviewed(&mut source,ResourceKind::Experience,&experience,"dependent-experience",&source_root);
    source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&knowledge_ref,"move-knowledge").unwrap();
    assert_eq!(source.begin_resource_transfer(&target,&permit,ResourceKind::Experience,&reference,"move-dependent").unwrap_err().kind,ErrorKind::ValidationStale);
    target.accept_resource_transfer(&source,&permit,"move-knowledge").unwrap();
    source.finalize_resource_transfer(&target,&permit,"move-knowledge").unwrap();
    source.begin_resource_transfer(&target,&permit,ResourceKind::Experience,&reference,"move-dependent").unwrap();
    target.accept_resource_transfer(&source,&permit,"move-dependent").unwrap();
    source.finalize_resource_transfer(&target,&permit,"move-dependent").unwrap();
    let view = target.query_received_resource(&source,&permit,"move-dependent").unwrap();
    assert_eq!(view["envelope"],experience);
    assert_eq!(view["origin_scope"],source.scope());
    assert_eq!(view["owning_scope"],target.scope());
    assert_eq!(view["runtime_or_global_admission"],false);
    assert!(source.query_resources(ResourceKind::Experience,"",8).unwrap()["entries"].as_array().unwrap().is_empty());
    let database = rusqlite::Connection::open(target_root.join(".wuji4/state.sqlite")).unwrap();
    let hash: String = database.query_row("SELECT payload_hash FROM received_resources WHERE transfer_id='move-knowledge'",[],|row|row.get(0)).unwrap();
    database.execute("UPDATE received_resources SET payload_hash=?1 WHERE transfer_id='move-knowledge'",["0".repeat(64)]).unwrap();
    assert_eq!(target.query_received_resource(&source,&permit,"move-dependent").unwrap_err().kind,ErrorKind::HashMismatch);
    database.execute("UPDATE received_resources SET payload_hash=?1 WHERE transfer_id='move-knowledge'",[hash]).unwrap();
    target.retire_received_resource(&source,&permit,"move-knowledge",1,"retire-knowledge-owner").unwrap();
    assert_eq!(target.query_received_resource(&source,&permit,"move-dependent").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(source.retire_resource(ResourceKind::Knowledge,&knowledge_ref,"source-cannot-retire").unwrap_err().kind,ErrorKind::ValidationStale);
}

#[test]
fn moved_knowledge_cannot_be_resolved_through_a_different_destination_grant() {
    let (source_root,_,mut source,mut target,knowledge,knowledge_ref,permit) = setup();
    let mut experience = json!({"schema_version":1,"contract_type":"ExperienceCandidate",
        "metadata":metadata(&source,"experience/grant","ExperienceCandidate"),
        "payload":{"scope":source.scope(),"trigger":"repair","method":"Use only authorized original knowledge",
            "evidence":knowledge["payload"]["source_refs"],"counterexamples":["No implicit third workspace sharing"],
            "expiry_utc_ms":null,"type":"failure_condition","knowledge_refs":[knowledge_ref]}});
    seal(&mut experience);
    let reference = reviewed(&mut source,ResourceKind::Experience,&experience,"grant-experience",&source_root);
    source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&knowledge_ref,"move-knowledge").unwrap();
    target.accept_resource_transfer(&source,&permit,"move-knowledge").unwrap();
    source.finalize_resource_transfer(&target,&permit,"move-knowledge").unwrap();
    let other_root = root("other-destination");
    let other = Store::open(&other_root).unwrap();
    let other_permit = LocalTransferPermit::confirm(&source_root,&other_root,"confirm-isolated-resource-transfer").unwrap();
    assert_eq!(source.begin_resource_transfer(&other,&other_permit,ResourceKind::Experience,&reference,"wrong-destination").unwrap_err().kind,ErrorKind::ScopeDenied);
    assert!(other.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"].as_array().unwrap().is_empty());
}

#[test]
fn transfer_destination_scope_payload_hash_and_duplicate_local_owner_cannot_be_forged() {
    let (_,target_root,mut source,mut target,mut knowledge,reference,permit) = setup();
    source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move").unwrap();
    let mut wrong_ref = reference.clone();
    wrong_ref.revision=2;
    assert_eq!(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&wrong_ref,"move").unwrap_err().kind,ErrorKind::EventConflict);
    let wrong_root = root("wrong-target");
    let wrong_target = Store::open(&wrong_root).unwrap();
    assert_eq!(source.finalize_resource_transfer(&wrong_target,&permit,"move").unwrap_err().kind,ErrorKind::ScopeDenied);
    target.accept_resource_transfer(&source,&permit,"move").unwrap();
    knowledge["metadata"]["scope"] = json!(target.scope());
    knowledge["payload"]["scope"] = json!(target.scope());
    seal(&mut knowledge);
    assert_eq!(target.propose_resource(ResourceKind::Knowledge,&knowledge,0,"fork-local").unwrap_err().kind,ErrorKind::OwnerConflict);
    let database = rusqlite::Connection::open(target_root.join(".wuji4/state.sqlite")).unwrap();
    database.execute("UPDATE received_resources SET payload_json='{}' WHERE transfer_id='move'",[]).unwrap();
    assert_eq!(target.resource_transfer_ack(&source,&permit,"move").unwrap_err().kind,ErrorKind::HashMismatch);
    assert_eq!(source.finalize_resource_transfer(&target,&permit,"move").unwrap_err().kind,ErrorKind::HashMismatch);
}

#[test]
fn two_receivers_replay_one_target_fact_instead_of_creating_two_owners() {
    let (source_root,target_root,mut source,target,_,reference,permit) = setup();
    source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"race").unwrap();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let handles: Vec<_> = (0..2).map(|_| {
        let source_root=source_root.clone();
        let target_root=target_root.clone();
        let barrier=barrier.clone();
        std::thread::spawn(move || {
            let source=Store::open_existing(&source_root).unwrap();
            let mut target=Store::open_existing(&target_root).unwrap();
            let permit=LocalTransferPermit::confirm(&source_root,&target_root,"confirm-isolated-resource-transfer").unwrap();
            barrier.wait();
            target.accept_resource_transfer(&source,&permit,"race").unwrap()
        })
    }).collect();
    let outcomes: Vec<_> = handles.into_iter().map(|handle|handle.join().unwrap()).collect();
    assert_eq!(outcomes[0],outcomes[1]);
    let database = rusqlite::Connection::open(target_root.join(".wuji4/state.sqlite")).unwrap();
    assert_eq!(database.query_row("SELECT count(*) FROM received_resources",[],|row|row.get::<_,i64>(0)).unwrap(),1);
}
