use rusqlite::Connection;
use serde_json::{Value,json};
use std::fs;
use std::path::{Path,PathBuf};
use std::sync::atomic::{AtomicU64,Ordering};
use std::time::{SystemTime,UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::received::{KnowledgeBinding,ReceivedDelta};
use wuji4::resources::{LocalResourceReviewPermit,ResourceKind};
use wuji4::store::Store;
use wuji4::strict_json;
use wuji4::transfers::LocalTransferPermit;

static FIXTURE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn fixture_root(timestamp: u128) -> PathBuf {
    let base=Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/received-delta-acceptance");
    fs::create_dir_all(&base).unwrap();
    let sequence=FIXTURE_SEQUENCE.fetch_add(1,Ordering::Relaxed);
    let root=base.join(format!("{}-{timestamp}-{sequence}",std::process::id()));
    fs::create_dir(&root).unwrap();
    root
}

#[test]
fn received_delta_fixture_same_clock_tick_has_unique_exclusive_parallel_roots() {
    let timestamp=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    let threads:Vec<_>=(0..32).map(|_|std::thread::spawn(move ||fixture_root(timestamp))).collect();
    let roots:std::collections::HashSet<_>=threads.into_iter().map(|thread|thread.join().unwrap()).collect();
    assert_eq!(roots.len(),32);
    assert!(roots.iter().all(|root|root.is_dir()));
}

struct Fixture {
    source_root: PathBuf,
    target_root: PathBuf,
    source: Store,
    target: Store,
    permit: LocalTransferPermit,
    owner_evidence: ExactRef,
    knowledge: Value,
    experience: Value,
    knowledge_ref: ExactRef,
}

fn metadata(scope: &str, id: &str, kind: &str) -> Value {
    json!({"id":id,"type":kind,"scope":scope,"schema_version":1,"revision":1,"owner":"aji-local",
        "authority":"review_proposal","status":"proposal","source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,
        "updated_at_utc_ms":1,"valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]})
}

fn seal(value: &mut Value) { value["metadata"]["content_hash"]=json!(strict_json::object_digest(value).unwrap()); }

impl Fixture {
    fn new() -> Self {
        let root=fixture_root(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos());
        let source_root=root.join("source");
        let target_root=root.join("target");
        fs::create_dir_all(&source_root).unwrap();
        fs::create_dir_all(&target_root).unwrap();
        fs::write(source_root.join("origin.txt"),b"original private observation").unwrap();
        fs::write(target_root.join("owner.txt"),b"explicit owner-scoped revision evidence").unwrap();
        let mut source=Store::open(&source_root).unwrap();
        let mut target=Store::open(&target_root).unwrap();
        let source_evidence=source.register_local_input("user/origin",Path::new("origin.txt")).unwrap();
        let owner_evidence=target.register_local_input("user/owner",Path::new("owner.txt")).unwrap();
        let review=LocalResourceReviewPermit::confirm_isolated(&source_root,"confirm-isolated-project-resource-review").unwrap();
        let mut knowledge=json!({"schema_version":1,"contract_type":"KnowledgeRecord","metadata":metadata(source.scope(),"knowledge/local","KnowledgeRecord"),
            "payload":{"knowledge_id":"knowledge/local","scope":source.scope(),"source_refs":[source_evidence],"location":"origin.txt:1",
                "sha256":source_evidence.sha256,"authority":"review_proposal","claim":"original private claim","method":"preserved original method",
                "derived_refs":[],"freshness":"current","conflicts":[]}});
        seal(&mut knowledge);
        let knowledge_ref:ExactRef=serde_json::from_value(source.propose_resource(ResourceKind::Knowledge,&knowledge,0,"propose-knowledge").unwrap()["reference"].clone()).unwrap();
        source.review_resource_local(&review,ResourceKind::Knowledge,&knowledge_ref,"review-knowledge").unwrap();
        let mut experience=json!({"schema_version":1,"contract_type":"ExperienceCandidate","metadata":metadata(source.scope(),"experience/local","ExperienceCandidate"),
            "payload":{"scope":source.scope(),"trigger":"bounded repair","method":"preserved professional repair detail",
                "evidence":[source_evidence],"counterexamples":["not a global rule"],"expiry_utc_ms":null,"type":"failure_condition","knowledge_refs":[knowledge_ref]}});
        seal(&mut experience);
        let experience_ref:ExactRef=serde_json::from_value(source.propose_resource(ResourceKind::Experience,&experience,0,"propose-experience").unwrap()["reference"].clone()).unwrap();
        source.review_resource_local(&review,ResourceKind::Experience,&experience_ref,"review-experience").unwrap();
        let permit=LocalTransferPermit::confirm(&source_root,&target_root,"confirm-isolated-resource-transfer").unwrap();
        for (kind,reference,id) in [(ResourceKind::Knowledge,&knowledge_ref,"move-knowledge"),(ResourceKind::Experience,&experience_ref,"move-experience")] {
            source.begin_resource_transfer(&target,&permit,kind,reference,id).unwrap();
            target.accept_resource_transfer(&source,&permit,id).unwrap();
            source.finalize_resource_transfer(&target,&permit,id).unwrap();
        }
        Self { source_root,target_root,source,target,permit,owner_evidence,knowledge,experience,knowledge_ref }
    }

    fn view(&self, id: &str) -> Value { self.target.query_received_resource(&self.source,&self.permit,id).unwrap() }

    fn request(&self, id: &str, parent: &ExactRef, key: &str, operation: &str, changes: Value, bindings: Vec<KnowledgeBinding>) -> ReceivedDelta {
        let mut refs=vec![parent.clone()];
        refs.extend(bindings.iter().map(|binding|binding.owner_ref.clone()));
        let kind=if id=="move-knowledge" { "KnowledgeRecord" } else { "ExperienceCandidate" };
        let resource=if id=="move-knowledge" { "knowledge/local" } else { "experience/local" };
        let mut delta=json!({"schema_version":1,"contract_type":"ResourceDelta","metadata":metadata(self.target.scope(),&format!("delta/{key}"),"ResourceDelta"),
            "payload":{"target_type":kind,"target_id":resource,"operation":operation,"expected_revision":parent.revision,
                "scope":self.target.scope(),"evidence":[self.owner_evidence],"reason":"explicit bounded owner revision with preserved provenance",
                "idempotency_key":key,"revalidation_refs":refs}});
        seal(&mut delta);
        ReceivedDelta { delta,changes:serde_json::from_value(changes).unwrap(),knowledge_bindings:bindings }
    }

    fn propose(&mut self, id: &str, request: &ReceivedDelta) -> Value {
        self.target.propose_received_delta(&self.source,&self.permit,id,request,"confirm-isolated-received-content-delta").unwrap()
    }

    fn review(&mut self, id: &str, reference: &ExactRef, key: &str) -> Value {
        let review=LocalResourceReviewPermit::confirm_isolated(&self.target_root,"confirm-isolated-project-resource-review").unwrap();
        self.target.review_received_delta(&self.source,&self.permit,&review,id,reference,key).unwrap()
    }
}

fn owner_ref(view: &Value) -> ExactRef { serde_json::from_value(view["owner_content"]["reference"].clone()).unwrap() }
fn proposed_ref(view: &Value) -> ExactRef { serde_json::from_value(view["reference"].clone()).unwrap() }

#[test]
fn received_delta_cas_and_reopen_preserve_origin_and_require_independent_current_review() {
    let mut fixture=Fixture::new();
    let first=owner_ref(&fixture.view("move-knowledge"));
    let original=fixture.knowledge.clone();
    let request=fixture.request("move-knowledge",&first,"update-knowledge","update",json!({"method":"owner-scoped revised method"}),vec![]);
    let result=fixture.propose("move-knowledge",&request);
    assert_eq!(result["state"],"candidate");
    assert_eq!(result["runtime_or_global_admission"],false);
    assert_eq!(result,fixture.propose("move-knowledge",&request));
    let reference=proposed_ref(&result);
    assert_eq!(reference.revision,2);
    assert_eq!(reference.scope,fixture.target.scope());
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-knowledge").unwrap_err().kind,ErrorKind::ValidationStale);
    let stale=fixture.request("move-knowledge",&first,"stale-parent","update",json!({"method":"must not overwrite"}),vec![]);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&stale,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::RevisionConflict);
    fixture.target=Store::open_existing(&fixture.target_root).unwrap();
    let ack=fixture.target.resource_transfer_ack(&fixture.source,&fixture.permit,"move-knowledge").unwrap();
    assert_eq!(ack["owner_content"]["content_state"],"candidate");
    assert_eq!(ack["owner_content"]["content_revision"],2);
    let review=fixture.review("move-knowledge",&reference,"independent-review");
    assert_eq!(review["producer_reviewer_distinct"],true);
    assert_eq!(review["professional_effectiveness"],"not_claimed");
    let current=fixture.view("move-knowledge");
    assert_eq!(current["envelope"],original);
    assert_eq!(current["owner_content"]["version"]["content"]["method"],"owner-scoped revised method");
    assert_eq!(current["owner_content"]["version"]["content"]["source_refs"],original["payload"]["source_refs"]);
    assert_eq!(current["owner_content"]["version"]["origin_ref"],serde_json::to_value(&fixture.knowledge_ref).unwrap());
    assert_eq!(current["origin_scope"],fixture.source.scope());
    assert_eq!(fixture.source.propose_resource(ResourceKind::Knowledge,&original,1,"source-cannot-write").unwrap_err().kind,ErrorKind::ValidationStale);
    let database=Connection::open(fixture.source_root.join(".wuji4/state.sqlite")).unwrap();
    let saved:String=database.query_row("SELECT envelope_json FROM knowledge_records WHERE id='knowledge/local' AND revision=1",[],|row|row.get(0)).unwrap();
    assert_eq!(serde_json::from_str::<Value>(&saved).unwrap(),original);
}

#[test]
fn received_exact_knowledge_rebinding_never_follows_latest_or_replays_old_review_as_current() {
    let mut fixture=Fixture::new();
    let knowledge_first=owner_ref(&fixture.view("move-knowledge"));
    let experience_first=owner_ref(&fixture.view("move-experience"));
    let update=fixture.request("move-knowledge",&knowledge_first,"knowledge-v2","update",json!({"method":"new owner method"}),vec![]);
    let knowledge_second=proposed_ref(&fixture.propose("move-knowledge",&update));
    fixture.review("move-knowledge",&knowledge_second,"review-k2");
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-experience").unwrap_err().kind,ErrorKind::ValidationStale);
    let binding=KnowledgeBinding { origin_ref:fixture.knowledge_ref.clone(),owner_ref:knowledge_second.clone() };
    let update=fixture.request("move-experience",&experience_first,"bind-experience-v2","update",json!({}),vec![binding]);
    let experience_second=proposed_ref(&fixture.propose("move-experience",&update));
    let reviewed=fixture.review("move-experience",&experience_second,"review-e2");
    let view=fixture.view("move-experience");
    assert_eq!(view["envelope"],fixture.experience);
    assert_eq!(view["owner_content"]["version"]["content"],fixture.experience["payload"]);
    assert_eq!(view["owner_content"]["version"]["knowledge_bindings"][0]["owner_ref"],serde_json::to_value(&knowledge_second).unwrap());
    let update=fixture.request("move-knowledge",&knowledge_second,"knowledge-v3","update",json!({"method":"later owner method"}),vec![]);
    let knowledge_third=proposed_ref(&fixture.propose("move-knowledge",&update));
    fixture.review("move-knowledge",&knowledge_third,"review-k3");
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-experience").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(reviewed,fixture.review("move-experience",&experience_second,"review-e2"));
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-experience").unwrap_err().kind,ErrorKind::ValidationStale);
    let binding=KnowledgeBinding { origin_ref:fixture.knowledge_ref.clone(),owner_ref:knowledge_third };
    let update=fixture.request("move-experience",&experience_second,"bind-experience-v3","update",json!({}),vec![binding]);
    let experience_third=proposed_ref(&fixture.propose("move-experience",&update));
    fixture.review("move-experience",&experience_third,"review-e3");
    assert_eq!(owner_ref(&fixture.view("move-experience")),experience_third);
}

#[test]
fn received_delta_permission_origin_fields_evidence_and_parent_revalidation_fail_closed() {
    let mut fixture=Fixture::new();
    let parent=owner_ref(&fixture.view("move-knowledge"));
    for field in ["scope","source_refs","authority","derived_refs","knowledge_id","location"] {
        let request=fixture.request("move-knowledge",&parent,&format!("deny-{field}"),"update",json!({field:"must not change provenance"}),vec![]);
        assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::RequiredWeakened);
    }
    let mut request=fixture.request("move-knowledge",&parent,"owner-grant","update",json!({"method":"bounded method"}),vec![]);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&request,"business-json-says-approved").unwrap_err().kind,ErrorKind::AuthorityDenied);
    request.delta["metadata"]["authority"]=json!("user_explicit");
    seal(&mut request.delta);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::AuthorityDenied);
    request.delta["metadata"]["authority"]=json!("review_proposal");
    request.delta["payload"]["scope"]=json!(fixture.source.scope());
    seal(&mut request.delta);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::Shape);
    request.delta["payload"]["scope"]=json!(fixture.target.scope());
    request.delta["payload"]["revalidation_refs"]=json!([]);
    seal(&mut request.delta);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::Reference);
    request.delta["payload"]["revalidation_refs"]=json!([parent]);
    request.delta["payload"]["evidence"][0]["sha256"]=json!("0".repeat(64));
    seal(&mut request.delta);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(fixture.target.resource_transfer_ack(&fixture.source,&fixture.permit,"move-knowledge").unwrap()["owner_revision"],1);
}

#[test]
fn received_merge_preserves_professional_details_and_does_not_overwrite_conflicting_scalars() {
    let mut fixture=Fixture::new();
    let parent=owner_ref(&fixture.view("move-experience"));
    let request=fixture.request("move-experience",&parent,"merge-counterexample","merge",json!({"counterexamples":["additional failure condition","additional failure condition"]}),vec![]);
    let reference=proposed_ref(&fixture.propose("move-experience",&request));
    fixture.review("move-experience",&reference,"review-merge");
    let view=fixture.view("move-experience");
    assert_eq!(view["owner_content"]["version"]["content"]["counterexamples"],json!(["not a global rule","additional failure condition"]));
    assert_eq!(view["owner_content"]["version"]["content"]["method"],fixture.experience["payload"]["method"]);
    assert_eq!(view["owner_content"]["version"]["content"]["evidence"],fixture.experience["payload"]["evidence"]);
    let request=fixture.request("move-experience",&reference,"conflicting-merge","merge",json!({"method":"silently replace professional method"}),vec![]);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-experience",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::CompositionConflict);
    let request=fixture.request("move-experience",&reference,"no-progress","update",json!({}),vec![]);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-experience",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::RevisionConflict);
}

#[test]
fn received_owner_evidence_or_origin_change_and_tampered_version_invalidate_current_reuse() {
    let mut fixture=Fixture::new();
    let parent=owner_ref(&fixture.view("move-knowledge"));
    let request=fixture.request("move-knowledge",&parent,"current-owner-evidence","update",json!({"method":"current evidence bound method"}),vec![]);
    let reference=proposed_ref(&fixture.propose("move-knowledge",&request));
    fixture.review("move-knowledge",&reference,"review-current");
    let database=Connection::open(fixture.target_root.join(".wuji4/state.sqlite")).unwrap();
    let original:String=database.query_row("SELECT version_json FROM received_resource_versions WHERE transfer_id='move-knowledge' AND revision=2",[],|row|row.get(0)).unwrap();
    database.execute("UPDATE received_resource_versions SET version_json='{}' WHERE transfer_id='move-knowledge' AND revision=2",[]).unwrap();
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-knowledge").unwrap_err().kind,ErrorKind::HashMismatch);
    database.execute("UPDATE received_resource_versions SET version_json=?1 WHERE transfer_id='move-knowledge' AND revision=2",[original]).unwrap();
    fs::write(fixture.target_root.join("owner.txt"),b"changed owner evidence").unwrap();
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-knowledge").unwrap_err().kind,ErrorKind::ValidationStale);
    fs::write(fixture.target_root.join("owner.txt"),b"explicit owner-scoped revision evidence").unwrap();
    assert_eq!(owner_ref(&fixture.view("move-knowledge")),reference);
    fs::write(fixture.source_root.join("origin.txt"),b"changed original source").unwrap();
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-knowledge").unwrap_err().kind,ErrorKind::ValidationStale);
}

#[test]
fn received_delta_retirement_and_historical_replay_never_revive_source_or_target() {
    let mut fixture=Fixture::new();
    let parent=owner_ref(&fixture.view("move-knowledge"));
    let request=fixture.request("move-knowledge",&parent,"retire-owner","retire",json!({}),vec![]);
    let receipt=fixture.propose("move-knowledge",&request);
    assert_eq!(receipt["state"],"retired");
    assert_eq!(receipt,fixture.propose("move-knowledge",&request));
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-knowledge").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(fixture.target.query_received_resource(&fixture.source,&fixture.permit,"move-experience").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(fixture.target.accept_resource_transfer(&fixture.source,&fixture.permit,"move-knowledge").unwrap()["state"],"retired");
    assert_eq!(fixture.source.finalize_resource_transfer(&fixture.target,&fixture.permit,"move-knowledge").unwrap()["source_writable"],false);
    let request=fixture.request("move-knowledge",&parent,"cannot-revive","update",json!({"method":"revive"}),vec![]);
    assert_eq!(fixture.target.propose_received_delta(&fixture.source,&fixture.permit,"move-knowledge",&request,"confirm-isolated-received-content-delta").unwrap_err().kind,ErrorKind::ValidationStale);
}

#[test]
fn received_delta_two_connections_have_one_revision_winner_and_no_duplicate_writable_fact() {
    let fixture=Fixture::new();
    let parent=owner_ref(&fixture.view("move-knowledge"));
    let barrier=std::sync::Arc::new(std::sync::Barrier::new(2));
    let handles:Vec<_>=(0..2).map(|index| {
        let source_root=fixture.source_root.clone();
        let target_root=fixture.target_root.clone();
        let request=fixture.request("move-knowledge",&parent,&format!("race-{index}"),"update",json!({"method":format!("method {index}")}),vec![]);
        let barrier=barrier.clone();
        std::thread::spawn(move || {
            let source=Store::open_existing(&source_root).unwrap();
            let mut target=Store::open_existing(&target_root).unwrap();
            let permit=LocalTransferPermit::confirm(&source_root,&target_root,"confirm-isolated-resource-transfer").unwrap();
            barrier.wait();
            target.propose_received_delta(&source,&permit,"move-knowledge",&request,"confirm-isolated-received-content-delta")
        })
    }).collect();
    let results:Vec<_>=handles.into_iter().map(|handle|handle.join().unwrap()).collect();
    assert_eq!(results.iter().filter(|result|result.is_ok()).count(),1);
    assert_eq!(results.into_iter().find(|result|result.is_err()).unwrap().unwrap_err().kind,ErrorKind::RevisionConflict);
    let database=Connection::open(fixture.target_root.join(".wuji4/state.sqlite")).unwrap();
    assert_eq!(database.query_row("SELECT count(*) FROM received_resource_versions WHERE transfer_id='move-knowledge' AND revision=2",[],|row|row.get::<_,i64>(0)).unwrap(),1);
    assert_eq!(database.query_row("SELECT count(*) FROM knowledge_records WHERE id='knowledge/local'",[],|row|row.get::<_,i64>(0)).unwrap(),0);
}
