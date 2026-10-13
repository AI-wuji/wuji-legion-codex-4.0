#![cfg(windows)]

use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use wuji4::error::{ErrorKind, Result};
use wuji4::graph::ExactRef;
use wuji4::received::ReceivedDelta;
use wuji4::resources::{LocalResourceReviewPermit, ResourceKind};
use wuji4::store::Store;
use wuji4::strict_json;
use wuji4::transfers::LocalTransferPermit;

fn workspace(label: &str) -> PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/resource-acl")
        .join(format!("{}-{}-{}",label,std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(&root).unwrap();
    root
}

fn seal(envelope: &mut Value) {
    envelope["metadata"]["content_hash"] = json!(strict_json::object_digest(envelope).unwrap());
}

fn metadata(id: &str, kind: &str, scope: &str) -> Value {
    json!({"id":id,"type":kind,"scope":scope,"schema_version":1,"revision":1,
        "owner":"aji-local","authority":"review_proposal","status":"proposal",
        "source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,"updated_at_utc_ms":1,
        "valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]})
}

fn setup(label: &str) -> (PathBuf, Store, Value, ExactRef, LocalResourceReviewPermit) {
    let root = workspace(label);
    fs::write(root.join("source.txt"),b"private source evidence").unwrap();
    let mut store = Store::open(&root).unwrap();
    let source = store.register_local_input("private/evidence",Path::new("source.txt")).unwrap();
    let mut envelope = json!({"schema_version":1,"contract_type":"KnowledgeRecord",
        "metadata":metadata("knowledge/private","KnowledgeRecord",store.scope()),
        "payload":{"knowledge_id":"knowledge/private","scope":store.scope(),"source_refs":[source],
            "location":"source.txt:1","sha256":source.sha256,"authority":"review_proposal",
            "claim":"private claim sentinel","method":"private method sentinel",
            "derived_refs":[],"freshness":"current","conflicts":[]}});
    seal(&mut envelope);
    let proposed = store.propose_resource(ResourceKind::Knowledge,&envelope,0,"propose").unwrap();
    let reference: ExactRef = serde_json::from_value(proposed["reference"].clone()).unwrap();
    let permit = LocalResourceReviewPermit::confirm_isolated(&root,"confirm-isolated-project-resource-review").unwrap();
    store.review_resource_local(&permit,ResourceKind::Knowledge,&reference,"review").unwrap();
    (root,store,envelope,reference,permit)
}

fn database(root: &Path) -> Connection {
    Connection::open(root.join(".wuji4/state.sqlite")).unwrap()
}

fn denied(result: Result<Value>, expected: ErrorKind) {
    let error = result.unwrap_err();
    assert_eq!(error.kind,expected);
    assert!(!error.detail.contains("private claim sentinel"));
    assert!(!error.detail.contains("private method sentinel"));
    assert!(!error.detail.contains("private source evidence"));
}

fn deny_all(store: &mut Store, envelope: &Value, reference: &ExactRef,
    permit: &LocalResourceReviewPermit, expected: ErrorKind) {
    denied(store.query_resources(ResourceKind::Knowledge,"",8),expected);
    denied(store.query_resources(ResourceKind::Experience,"",8),expected);
    for event in ["propose","new-propose"] {
        denied(store.propose_resource(ResourceKind::Knowledge,envelope,0,event),expected);
    }
    for event in ["review","new-review"] {
        denied(store.review_resource_local(permit,ResourceKind::Knowledge,reference,event),expected);
    }
    for event in ["retire","new-retire"] {
        denied(store.retire_resource(ResourceKind::Knowledge,reference,event),expected);
    }
}

#[test]
fn t22_current_owner_consumes_knowledge_and_experience_after_reopen() {
    let (root,mut store,envelope,reference,permit) = setup("current-owner");
    let connection = database(&root);
    let owner: String = connection.query_row("SELECT owner_sid FROM local_resource_acl",[],|row|row.get(0)).unwrap();
    assert!(owner.starts_with("S-1-"));
    assert_ne!(owner,"aji-local");
    let mut experience = json!({"schema_version":1,"contract_type":"ExperienceCandidate",
        "metadata":metadata("experience/private","ExperienceCandidate",store.scope()),
        "payload":{"scope":store.scope(),"trigger":"private-trigger","method":"scoped private method",
            "evidence":envelope["payload"]["source_refs"],"counterexamples":["Not another user's preference"],
            "expiry_utc_ms":null,"type":"failure_condition","knowledge_refs":[reference]}});
    seal(&mut experience);
    let proposed = store.propose_resource(ResourceKind::Experience,&experience,0,"experience-propose").unwrap();
    let experience_ref: ExactRef = serde_json::from_value(proposed["reference"].clone()).unwrap();
    store.review_resource_local(&permit,ResourceKind::Experience,&experience_ref,"experience-review").unwrap();
    drop(store);
    let mut reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"][0]["envelope"],envelope);
    assert_eq!(reopened.query_resources(ResourceKind::Experience,"private-trigger",8).unwrap()["entries"][0]["envelope"],experience);
    reopened.retire_resource(ResourceKind::Experience,&experience_ref,"experience-retire").unwrap();
    assert!(reopened.query_resources(ResourceKind::Experience,"",8).unwrap()["entries"].as_array().unwrap().is_empty());
}

#[test]
fn t22_json_owner_or_token_fields_cannot_grant_authority() {
    let (root,mut store,envelope,_,_) = setup("forged-json");
    let connection = database(&root);
    let owner: String = connection.query_row("SELECT owner_sid FROM local_resource_acl",[],|row|row.get(0)).unwrap();
    let mut forged = envelope.clone();
    forged["metadata"]["owner"] = json!(owner);
    seal(&mut forged);
    denied(store.propose_resource(ResourceKind::Knowledge,&forged,0,"forged-owner"),ErrorKind::AuthorityDenied);
    let mut forged = envelope.clone();
    forged["trusted_identity"] = json!({"sid":owner,"username":"Administrator","token":"trusted"});
    seal(&mut forged);
    assert!(store.propose_resource(ResourceKind::Knowledge,&forged,0,"forged-token").is_err());
    connection.execute("UPDATE local_resource_acl SET enabled=0",[]).unwrap();
    denied(store.propose_resource(ResourceKind::Knowledge,&envelope,0,"propose"),ErrorKind::AuthorityDenied);
    assert_eq!(connection.query_row("SELECT count(*) FROM knowledge_records",[],|row|row.get::<_,i64>(0)).unwrap(),1);
}

#[test]
fn t22_revocation_denies_every_operation_including_historical_replays() {
    let (root,mut store,envelope,reference,permit) = setup("revoked");
    let retired = store.retire_resource(ResourceKind::Knowledge,&reference,"retire").unwrap();
    assert_eq!(store.retire_resource(ResourceKind::Knowledge,&reference,"retire").unwrap(),retired);
    let connection = database(&root);
    connection.execute("UPDATE local_resource_acl SET enabled=0",[]).unwrap();
    deny_all(&mut store,&envelope,&reference,&permit,ErrorKind::AuthorityDenied);
    assert_eq!(connection.query_row("SELECT count(*) FROM resource_events",[],|row|row.get::<_,i64>(0)).unwrap(),3);
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
}

#[test]
fn t22_another_owner_sid_denies_open_and_all_live_operations() {
    let (root,mut store,envelope,reference,permit) = setup("other-owner");
    store.retire_resource(ResourceKind::Knowledge,&reference,"retire").unwrap();
    let connection = database(&root);
    let owner: String = connection.query_row("SELECT owner_sid FROM local_resource_acl",[],|row|row.get(0)).unwrap();
    let other = if owner == "S-1-5-18" { "S-1-5-19" } else { "S-1-5-18" };
    connection.execute("UPDATE local_resource_acl SET owner_sid=?1",[other]).unwrap();
    deny_all(&mut store,&envelope,&reference,&permit,ErrorKind::AuthorityDenied);
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
}

#[test]
fn t22_scope_is_rechecked_after_store_open_before_queries_and_replays() {
    let (root,mut store,envelope,reference,permit) = setup("scope-changed");
    store.retire_resource(ResourceKind::Knowledge,&reference,"retire").unwrap();
    let connection = database(&root);
    let scope = store.scope().to_owned();
    connection.execute("UPDATE workspace_meta SET scope='project:other'",[]).unwrap();
    deny_all(&mut store,&envelope,&reference,&permit,ErrorKind::ScopeDenied);
    connection.execute("UPDATE workspace_meta SET scope=?1",[&scope]).unwrap();
    connection.execute("UPDATE local_resource_acl SET scope='project:other'",[]).unwrap();
    deny_all(&mut store,&envelope,&reference,&permit,ErrorKind::ScopeDenied);
    connection.execute("UPDATE local_resource_acl SET scope=?1,root_hash='changed'",[&scope]).unwrap();
    deny_all(&mut store,&envelope,&reference,&permit,ErrorKind::ScopeDenied);
}

#[test]
fn t22_record_scope_change_denies_mutations_and_does_not_leak_query_content() {
    let (root,mut store,envelope,reference,permit) = setup("record-scope");
    let connection = database(&root);
    connection.execute("UPDATE knowledge_records SET scope='project:other'",[]).unwrap();
    let query = store.query_resources(ResourceKind::Knowledge,"",8).unwrap();
    assert!(query["entries"].as_array().unwrap().is_empty());
    assert!(query["rejected"].as_array().unwrap().is_empty());
    denied(store.propose_resource(ResourceKind::Knowledge,&envelope,0,"propose"),ErrorKind::ScopeDenied);
    denied(store.review_resource_local(&permit,ResourceKind::Knowledge,&reference,"review"),ErrorKind::ScopeDenied);
    denied(store.retire_resource(ResourceKind::Knowledge,&reference,"retire"),ErrorKind::ScopeDenied);
    let mut foreign = envelope;
    foreign["metadata"]["scope"] = json!("project:other");
    foreign["payload"]["scope"] = json!("project:other");
    seal(&mut foreign);
    connection.execute("UPDATE knowledge_records SET scope=?1,content_hash=?2,envelope_json=?3",
        params![store.scope(),strict_json::object_digest(&foreign).unwrap(),serde_json::to_string(&foreign).unwrap()]).unwrap();
    denied(store.query_resources(ResourceKind::Knowledge,"",8),ErrorKind::ScopeDenied);
}

#[test]
fn t22_cross_project_input_and_relocated_database_are_rejected() {
    let (root,store,envelope,reference,_) = setup("origin");
    let (_,mut other,_,_,other_permit) = setup("destination");
    denied(other.propose_resource(ResourceKind::Knowledge,&envelope,0,"foreign-propose"),ErrorKind::ScopeDenied);
    denied(other.review_resource_local(&other_permit,ResourceKind::Knowledge,&reference,"foreign-review"),ErrorKind::ScopeDenied);
    denied(other.retire_resource(ResourceKind::Knowledge,&reference,"foreign-retire"),ErrorKind::ScopeDenied);
    drop(store);
    let moved = workspace("relocated");
    fs::create_dir(moved.join(".wuji4")).unwrap();
    fs::copy(root.join(".wuji4/state.sqlite"),moved.join(".wuji4/state.sqlite")).unwrap();
    let before = fs::read(moved.join(".wuji4/state.sqlite")).unwrap();
    assert_eq!(Store::open(&moved).err().unwrap().kind,ErrorKind::ScopeDenied);
    assert_eq!(fs::read(moved.join(".wuji4/state.sqlite")).unwrap(),before);
}

#[test]
fn t22_legacy_database_cannot_be_silently_claimed_or_migrated() {
    for version in [2,6] {
        let (root,store,_,_,_) = setup("legacy");
        drop(store);
        let connection = database(&root);
        connection.execute("DROP TABLE local_resource_acl",[]).unwrap();
        connection.pragma_update(None,"user_version",version).unwrap();
        drop(connection);
        let before = fs::read(root.join(".wuji4/state.sqlite")).unwrap();
        assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
        assert_eq!(fs::read(root.join(".wuji4/state.sqlite")).unwrap(),before);
        assert!(Store::open_existing(&root).is_err());
        assert_eq!(fs::read(root.join(".wuji4/state.sqlite")).unwrap(),before);
    }
}

#[test]
fn t22_empty_or_unknown_owner_authorization_is_not_repaired() {
    for mutation in [
        "DELETE FROM local_resource_acl",
        "DROP TABLE local_resource_acl; CREATE TABLE local_resource_acl(untrusted_owner TEXT)",
        "PRAGMA ignore_check_constraints=ON; UPDATE local_resource_acl SET acl_version=2",
    ] {
        let (root,mut store,envelope,reference,permit) = setup("invalid-binding");
        let connection = database(&root);
        connection.execute_batch(mutation).unwrap();
        drop(connection);
        let before = fs::read(root.join(".wuji4/state.sqlite")).unwrap();
        deny_all(&mut store,&envelope,&reference,&permit,ErrorKind::AuthorityDenied);
        assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
        assert_eq!(fs::read(root.join(".wuji4/state.sqlite")).unwrap(),before);
    }
}

#[test]
fn t22_transfer_scope_is_rechecked_before_new_intent_and_replay() {
    for stage in 0..3 {
        let (source_root,mut source,_,reference,_) = setup("transfer-record-scope");
        let target_root = workspace("transfer-record-scope-target");
        let mut target = Store::open(&target_root).unwrap();
        let permit = LocalTransferPermit::confirm(&source_root,&target_root,"confirm-isolated-resource-transfer").unwrap();
        if stage > 0 {
            source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move").unwrap();
        }
        if stage == 2 {
            target.accept_resource_transfer(&source,&permit,"move").unwrap();
            source.finalize_resource_transfer(&target,&permit,"move").unwrap();
        }
        let connection = database(&source_root);
        connection.execute("UPDATE knowledge_records SET scope='project:other'",[]).unwrap();
        assert!(source.query_resources(ResourceKind::Knowledge,"",8).unwrap()["entries"].as_array().unwrap().is_empty());
        denied(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move"),ErrorKind::ScopeDenied);
        assert_eq!(connection.query_row("SELECT count(*) FROM resource_transfers",[],|row|row.get::<_,i64>(0)).unwrap(),if stage == 0 { 0 } else { 1 });
        connection.execute("UPDATE knowledge_records SET scope=?1",[source.scope()]).unwrap();
        let replayed = source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move").unwrap();
        assert_eq!(replayed["state"],if stage == 2 { "shared_ref" } else { "transfer_pending" });
    }
}

#[test]
fn t22_transfer_replay_validates_immutable_source_intent() {
    for finalized in [false,true] {
        let (source_root,mut source,_,reference,_) = setup("transfer-intent-integrity");
        let target_root = workspace("transfer-intent-integrity-target");
        let mut target = Store::open(&target_root).unwrap();
        let permit = LocalTransferPermit::confirm(&source_root,&target_root,"confirm-isolated-resource-transfer").unwrap();
        source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move").unwrap();
        if finalized {
            target.accept_resource_transfer(&source,&permit,"move").unwrap();
            source.finalize_resource_transfer(&target,&permit,"move").unwrap();
        }
        let connection = database(&source_root);
        let (text,hash): (String,String) = connection.query_row(
            "SELECT payload_json,payload_hash FROM resource_transfers WHERE transfer_id='move'",[],|row|Ok((row.get(0)?,row.get(1)?))).unwrap();
        connection.execute("UPDATE resource_transfers SET payload_hash=?1",["0".repeat(64)]).unwrap();
        denied(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move"),ErrorKind::HashMismatch);
        let mut payload = strict_json::parse(text.as_bytes()).unwrap();
        payload["source_scope"] = json!("project:other");
        connection.execute("UPDATE resource_transfers SET payload_json=?1,payload_hash=?2",
            params![serde_json::to_string(&payload).unwrap(),strict_json::digest(&payload).unwrap()]).unwrap();
        denied(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move"),ErrorKind::ScopeDenied);
        let mut payload = strict_json::parse(text.as_bytes()).unwrap();
        payload["envelope"]["payload"]["claim"] = json!("replaced transfer claim");
        connection.execute("UPDATE resource_transfers SET payload_json=?1,payload_hash=?2",
            params![serde_json::to_string(&payload).unwrap(),strict_json::digest(&payload).unwrap()]).unwrap();
        denied(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move"),ErrorKind::HashMismatch);
        connection.execute("UPDATE resource_transfers SET payload_json=?1,payload_hash=?2",params![text,hash]).unwrap();
        assert_eq!(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move").unwrap()["state"],
            if finalized { "shared_ref" } else { "transfer_pending" });
        assert_eq!(connection.query_row("SELECT count(*) FROM resource_transfers",[],|row|row.get::<_,i64>(0)).unwrap(),1);
    }
}

#[test]
fn t22_transfer_and_received_replays_recheck_both_open_store_owners() {
    for revoke_source in [true,false] {
        let (source_root,mut source,envelope,reference,_) = setup("transfer-source");
        let target_root = workspace("transfer-target");
        fs::write(target_root.join("owner.txt"),b"owner scoped evidence").unwrap();
        let mut target = Store::open(&target_root).unwrap();
        let evidence = target.register_local_input("owner/evidence",Path::new("owner.txt")).unwrap();
        let permit = LocalTransferPermit::confirm(&source_root,&target_root,"confirm-isolated-resource-transfer").unwrap();
        source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move").unwrap();
        target.accept_resource_transfer(&source,&permit,"move").unwrap();
        source.finalize_resource_transfer(&target,&permit,"move").unwrap();
        let view = target.query_received_resource(&source,&permit,"move").unwrap();
        assert_eq!(view["envelope"],envelope);
        let parent: ExactRef = serde_json::from_value(view["owner_content"]["reference"].clone()).unwrap();
        let mut delta = json!({"schema_version":1,"contract_type":"ResourceDelta",
            "metadata":metadata("delta/acl","ResourceDelta",target.scope()),
            "payload":{"target_type":"KnowledgeRecord","target_id":reference.id,"operation":"update",
                "expected_revision":parent.revision,"scope":target.scope(),"evidence":[evidence],
                "reason":"bounded owner revision","idempotency_key":"owner-propose","revalidation_refs":[parent]}});
        seal(&mut delta);
        let request = ReceivedDelta { delta,changes:serde_json::from_value(json!({"claim":"changed private claim"})).unwrap(),knowledge_bindings:Vec::new() };
        let proposed = target.propose_received_delta(&source,&permit,"move",&request,"confirm-isolated-received-content-delta").unwrap();
        let owner_ref: ExactRef = serde_json::from_value(proposed["reference"].clone()).unwrap();
        let review = LocalResourceReviewPermit::confirm_isolated(&target_root,"confirm-isolated-project-resource-review").unwrap();
        target.review_received_delta(&source,&permit,&review,"move",&owner_ref,"owner-review").unwrap();
        target.retire_received_resource(&source,&permit,"move",2,"owner-retire").unwrap();
        let denied_root = if revoke_source { &source_root } else { &target_root };
        let connection = database(denied_root);
        connection.execute("UPDATE local_resource_acl SET enabled=0",[]).unwrap();
        denied(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move"),ErrorKind::AuthorityDenied);
        denied(target.accept_resource_transfer(&source,&permit,"move"),ErrorKind::AuthorityDenied);
        denied(source.finalize_resource_transfer(&target,&permit,"move"),ErrorKind::AuthorityDenied);
        denied(target.resource_transfer_ack(&source,&permit,"move"),ErrorKind::AuthorityDenied);
        denied(target.query_received_resource(&source,&permit,"move"),ErrorKind::AuthorityDenied);
        denied(target.retire_received_resource(&source,&permit,"move",2,"owner-retire"),ErrorKind::AuthorityDenied);
        denied(target.propose_received_delta(&source,&permit,"move",&request,"confirm-isolated-received-content-delta"),ErrorKind::AuthorityDenied);
        denied(target.review_received_delta(&source,&permit,&review,"move",&owner_ref,"owner-review"),ErrorKind::AuthorityDenied);
        connection.execute("UPDATE local_resource_acl SET enabled=1,scope='project:changed-after-open'",[]).unwrap();
        denied(source.begin_resource_transfer(&target,&permit,ResourceKind::Knowledge,&reference,"move"),ErrorKind::ScopeDenied);
        denied(target.accept_resource_transfer(&source,&permit,"move"),ErrorKind::ScopeDenied);
        denied(source.finalize_resource_transfer(&target,&permit,"move"),ErrorKind::ScopeDenied);
        denied(target.resource_transfer_ack(&source,&permit,"move"),ErrorKind::ScopeDenied);
        denied(target.query_received_resource(&source,&permit,"move"),ErrorKind::ScopeDenied);
        denied(target.retire_received_resource(&source,&permit,"move",2,"owner-retire"),ErrorKind::ScopeDenied);
        denied(target.propose_received_delta(&source,&permit,"move",&request,"confirm-isolated-received-content-delta"),ErrorKind::ScopeDenied);
        denied(target.review_received_delta(&source,&permit,&review,"move",&owner_ref,"owner-review"),ErrorKind::ScopeDenied);
    }
}
