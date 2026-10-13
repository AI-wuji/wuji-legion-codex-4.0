use crate::contracts::Schemas;
use crate::error::{Error, ErrorKind, Result};
use crate::graph::ExactRef;
use crate::policy::Workspace;
use crate::resources::{ResourceKind,current_resource_resolved,exact,record_event,replay,require_record_scope,resource_write_authority,valid_event};
use crate::store::{Store,check_clock,wall_clock};
use crate::strict_json;
use rusqlite::{Connection,OptionalExtension,TransactionBehavior,params};
use serde::{Deserialize,Serialize};
use serde_json::{Value,json};
use std::path::{Path,PathBuf};

pub struct LocalTransferPermit { source: PathBuf, target: PathBuf }

impl LocalTransferPermit {
    pub fn confirm(source: &Path, target: &Path, confirmation: &str) -> Result<Self> {
        if confirmation != "confirm-isolated-resource-transfer" {
            return Err(Error::new(ErrorKind::AuthorityDenied,"explicit two-workspace isolated transfer confirmation required"));
        }
        let source = Workspace::open(source)?;
        let target = Workspace::open(target)?;
        let development = std::fs::canonicalize(Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev"))?;
        if Workspace::conflicts(source.root(),target.root()) || !source.root().starts_with(&development) || !target.root().starts_with(&development) {
            return Err(Error::new(ErrorKind::ScopeDenied,"transfer requires disjoint project .dev workspaces"));
        }
        Ok(Self { source:source.root().to_owned(),target:target.root().to_owned() })
    }

    pub(crate) fn check(&self, source: &Store, target: &Store) -> Result<()> {
        if self.source != source.workspace.root() || self.target != target.workspace.root() || source.scope == target.scope {
            return Err(Error::new(ErrorKind::ScopeDenied,"transfer permit is bound to exact source and target workspaces"));
        }
        crate::local_identity::require(&source.connection,&source.workspace,&source.scope)?;
        crate::local_identity::require(&target.connection,&target.workspace,&target.scope)?;
        Ok(())
    }
}

#[derive(Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TransferPayload {
    schema_version: u64,
    pub(crate) transfer_id: String,
    pub(crate) kind: String,
    source_root: PathBuf,
    source_scope: String,
    target_root: PathBuf,
    target_scope: String,
    pub(crate) source_reference: ExactRef,
    pub(crate) envelope: Value,
    authority: String,
}

fn checked_payload(text: &str, checksum: &str, source: &Store, target: &Store, permit: &LocalTransferPermit) -> Result<TransferPayload> {
    permit.check(source,target)?;
    checked_payload_grant(text,checksum,&source.scope,&target.scope,permit)
}

pub(crate) fn checked_payload_grant(text: &str, checksum: &str, source_scope: &str, target_scope: &str, permit: &LocalTransferPermit) -> Result<TransferPayload> {
    let value = strict_json::parse(text.as_bytes())?;
    if strict_json::digest(&value)? != checksum { return Err(Error::new(ErrorKind::HashMismatch,"immutable transfer payload changed")); }
    let payload: TransferPayload = serde_json::from_value(value)?;
    if payload.schema_version != 1 || payload.source_root != permit.source || payload.target_root != permit.target
        || payload.source_scope != source_scope || payload.target_scope != target_scope || payload.authority != "isolated-development-only"
        || payload.source_reference.scope != source_scope {
        return Err(Error::new(ErrorKind::ScopeDenied,"transfer payload identity or authority differs from granted workspaces"));
    }
    let kind = match payload.kind.as_str() {
        "KnowledgeRecord" => ResourceKind::Knowledge,"ExperienceCandidate" => ResourceKind::Experience,
        _ => return Err(Error::new(ErrorKind::Shape,"transfer resource kind invalid")),
    };
    Schemas::frozen()?.check_envelope(&payload.envelope)?;
    if exact(&payload.envelope,kind)? != payload.source_reference {
        return Err(Error::new(ErrorKind::HashMismatch,"transfer envelope differs from originating exact reference"));
    }
    Ok(payload)
}

pub(crate) fn received_knowledge(source: &Connection, target: &Connection, source_scope: &str, target_scope: &str,
    permit: &LocalTransferPermit, reference: &ExactRef) -> Result<Option<Value>> {
    crate::local_identity::require(source,&Workspace::open(&permit.source)?,source_scope)?;
    crate::local_identity::require(target,&Workspace::open(&permit.target)?,target_scope)?;
    let source_row: Option<(String,String,String,String)> = source.query_row(
        "SELECT transfer_id,payload_hash,payload_json,state FROM resource_transfers WHERE kind='KnowledgeRecord' AND resource_id=?1",
        [&reference.id],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).optional()?;
    let Some((id,checksum,text,state)) = source_row else { return Ok(None); };
    if !["transfer_pending","shared_ref"].contains(&state.as_str()) {
        return Err(Error::new(ErrorKind::ValidationStale,"knowledge origin ownership is not frozen"));
    }
    let payload = checked_payload_grant(&text,&checksum,source_scope,target_scope,permit)?;
    if payload.kind != "KnowledgeRecord" || payload.source_reference != *reference {
        return Err(Error::new(ErrorKind::Reference,"moved knowledge differs from exact dependency revision"));
    }
    let target_row: Option<(String,String,String,String,i64)> = target.query_row(
        "SELECT payload_hash,payload_json,source_scope,state,owner_revision FROM received_resources WHERE transfer_id=?1 AND kind='KnowledgeRecord' AND resource_id=?2",
        params![id,reference.id],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?))).optional()?;
    let (target_hash,target_text,origin,state,revision) = target_row.ok_or_else(||Error::new(ErrorKind::ValidationStale,"knowledge target has not durably acknowledged ownership"))?;
    if target_hash != checksum || origin != source_scope {
        return Err(Error::new(ErrorKind::HashMismatch,"knowledge target acknowledgement differs from source intent"));
    }
    let received = checked_payload_grant(&target_text,&target_hash,source_scope,target_scope,permit)?;
    if received.transfer_id != id || received.source_reference != *reference || state != "active_local" || revision != 1 {
        return Err(Error::new(ErrorKind::ValidationStale,"knowledge target retired or origin content revision no longer current"));
    }
    Ok(Some(received.envelope))
}

impl Store {
    pub fn begin_resource_transfer(&mut self, target: &Store, permit: &LocalTransferPermit,
        kind: ResourceKind, reference: &ExactRef, transfer_id: &str) -> Result<Value> {
        permit.check(self,target)?;
        valid_event(transfer_id)?;
        Schemas::frozen()?.check_definition("ExactRef",&serde_json::to_value(reference)?)?;
        let revision = i64::try_from(reference.revision).map_err(|_|Error::new(ErrorKind::RevisionConflict,"source resource revision exceeds SQLite range"))?;
        if reference.scope != self.scope || reference.r#type != kind.contract() {
            return Err(Error::new(ErrorKind::ScopeDenied,"transfer source must be exact same-scope resource"));
        }
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        crate::local_identity::require(&target.connection,&target.workspace,&target.scope)?;
        require_record_scope(&transaction,kind,&reference.id,&self.scope)?;
        let previous: Option<(String,String,String)> = transaction.query_row("SELECT payload_json,payload_hash,state FROM resource_transfers WHERE transfer_id=?1",[transfer_id],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
        if let Some((text,checksum,state)) = previous {
            let payload = checked_payload_grant(&text,&checksum,&self.scope,&target.scope,permit)?;
            if payload.transfer_id != transfer_id || payload.source_reference != *reference || payload.kind != kind.contract() {
                return Err(Error::new(ErrorKind::EventConflict,"transfer ID already identifies another move"));
            }
            return Ok(json!({"transfer_id":transfer_id,"source_reference":reference,"state":state,"target_scope":target.scope,"runtime_or_global_admission":false}));
        }
        resource_write_authority(&transaction,kind,&reference.id)?;
        let stored: Option<(String,String)> = transaction.query_row(&format!("SELECT envelope_json,content_hash FROM {} WHERE id=?1 AND revision=?2 AND state='active_local'",kind.table()),params![reference.id,revision],|row|Ok((row.get(0)?,row.get(1)?))).optional()?;
        let (text,hash) = stored.ok_or_else(||Error::new(ErrorKind::ValidationStale,"only a reviewed local resource can transfer"))?;
        let envelope = strict_json::parse(text.as_bytes())?;
        if hash != reference.sha256 || exact(&envelope,kind)? != *reference { return Err(Error::new(ErrorKind::HashMismatch,"transfer source identity changed")); }
        let now = wall_clock()?;
        check_clock(&transaction,now)?;
        current_resource_resolved(&transaction,&self.workspace,&self.scope,kind,&envelope,now,
            &mut |reference| received_knowledge(&transaction,&target.connection,&self.scope,&target.scope,permit,reference))?;
        let payload = TransferPayload { schema_version:1,transfer_id:transfer_id.into(),kind:kind.contract().into(),
            source_root:permit.source.clone(),source_scope:self.scope.clone(),target_root:permit.target.clone(),target_scope:target.scope.clone(),
            source_reference:reference.clone(),envelope,authority:"isolated-development-only".into() };
        let value = serde_json::to_value(payload)?;
        let checksum = strict_json::digest(&value)?;
        let encoded = String::from_utf8(strict_json::canonical(&value)?).unwrap();
        transaction.execute("INSERT INTO resource_transfers(transfer_id,kind,resource_id,resource_revision,payload_hash,payload_json,state) VALUES(?1,?2,?3,?4,?5,?6,'transfer_pending')",params![transfer_id,kind.contract(),reference.id,revision,checksum,encoded])?;
        transaction.commit()?;
        Ok(json!({"transfer_id":transfer_id,"source_reference":reference,"payload_hash":checksum,"state":"transfer_pending","target_scope":target.scope,"runtime_or_global_admission":false}))
    }

    pub fn accept_resource_transfer(&mut self, source: &Store, permit: &LocalTransferPermit, transfer_id: &str) -> Result<Value> {
        permit.check(source,self)?;
        valid_event(transfer_id)?;
        let stored: Option<(String,String,String)> = source.connection.query_row("SELECT payload_json,payload_hash,state FROM resource_transfers WHERE transfer_id=?1",[transfer_id],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
        let (text,checksum,state) = stored.ok_or_else(||Error::new(ErrorKind::Reference,"source has no durable transfer intent"))?;
        if !["transfer_pending","shared_ref"].contains(&state.as_str()) { return Err(Error::new(ErrorKind::ValidationStale,"source transfer is not frozen")); }
        let payload = checked_payload(&text,&checksum,source,self,permit)?;
        let kind = if payload.kind == "KnowledgeRecord" { ResourceKind::Knowledge } else { ResourceKind::Experience };
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        crate::local_identity::require(&source.connection,&source.workspace,&source.scope)?;
        let previous: Option<String> = transaction.query_row("SELECT payload_hash FROM received_resources WHERE transfer_id=?1",[transfer_id],|row|row.get(0)).optional()?;
        if let Some(previous) = previous {
            if previous != checksum { return Err(Error::new(ErrorKind::EventConflict,"received transfer ID has another payload")); }
            drop(transaction);
            return self.resource_transfer_ack(source,permit,transfer_id);
        }
        if state != "transfer_pending" { return Err(Error::new(ErrorKind::ValidationStale,"a finalized transfer cannot create a missing target fact")); }
        let local: bool = transaction.query_row(&format!("SELECT EXISTS(SELECT 1 FROM {} WHERE id=?1)",kind.table()),[&payload.source_reference.id],|row|row.get(0))?;
        if local { return Err(Error::new(ErrorKind::OwnerConflict,"target already has a local writable identity with this resource ID")); }
        let now = wall_clock()?;
        check_clock(&transaction,now)?;
        current_resource_resolved(&source.connection,&source.workspace,&source.scope,kind,&payload.envelope,now,
            &mut |reference| received_knowledge(&source.connection,&transaction,&source.scope,&self.scope,permit,reference))?;
        transaction.execute("INSERT INTO received_resources VALUES(?1,?2,?3,?4,?5,?6,1,'active_local')",params![transfer_id,payload.source_scope,payload.kind,payload.source_reference.id,checksum,text])?;
        transaction.commit()?;
        self.resource_transfer_ack(source,permit,transfer_id)
    }

    pub fn resource_transfer_ack(&self, source: &Store, permit: &LocalTransferPermit, transfer_id: &str) -> Result<Value> {
        permit.check(source,self)?;
        valid_event(transfer_id)?;
        let stored: Option<(String,String,i64,String)> = self.connection.query_row("SELECT payload_json,payload_hash,owner_revision,state FROM received_resources WHERE transfer_id=?1",[transfer_id],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).optional()?;
        let (text,checksum,revision,state) = stored.ok_or_else(||Error::new(ErrorKind::Reference,"target ACK not found; do not retry external actions blindly"))?;
        let payload = checked_payload(&text,&checksum,source,self,permit)?;
        let source_hash: Option<String> = source.connection.query_row("SELECT payload_hash FROM resource_transfers WHERE transfer_id=?1 AND state IN ('transfer_pending','shared_ref')",[transfer_id],|row|row.get(0)).optional()?;
        if source_hash.as_deref() != Some(&checksum) || payload.transfer_id != transfer_id {
            return Err(Error::new(ErrorKind::HashMismatch,"ACK does not match the exact frozen source transfer"));
        }
        let content_status=crate::received::content_status(&self.connection,transfer_id,revision,&state)?;
        Ok(json!({"transfer_id":transfer_id,"payload_hash":checksum,"source_reference":payload.source_reference,
            "owning_scope":self.scope,"owner_revision":revision,"state":state,"target_fact_recorded":true,
            "owner_content":content_status,
            "runtime_or_global_admission":false,"reuse_eligibility":"must-query-current-evidence"}))
    }

    pub fn finalize_resource_transfer(&mut self, target: &Store, permit: &LocalTransferPermit, transfer_id: &str) -> Result<Value> {
        permit.check(self,target)?;
        let ack = target.resource_transfer_ack(self,permit,transfer_id)?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        crate::local_identity::require(&target.connection,&target.workspace,&target.scope)?;
        check_clock(&transaction,wall_clock()?)?;
        let changed = transaction.execute("UPDATE resource_transfers SET state='shared_ref',ack_json=?1 WHERE transfer_id=?2 AND payload_hash=?3 AND state IN ('transfer_pending','shared_ref')",params![serde_json::to_string(&ack)?,transfer_id,ack["payload_hash"].as_str().unwrap()])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"source transfer differs from target's queryable ACK")); }
        transaction.commit()?;
        Ok(json!({"transfer_id":transfer_id,"source_state":"shared_ref","source_writable":false,"ack":ack,"production_or_global_admission":false}))
    }

    pub fn query_received_resource(&self, source: &Store, permit: &LocalTransferPermit, transfer_id: &str) -> Result<Value> {
        let ack = self.resource_transfer_ack(source,permit,transfer_id)?;
        if ack["state"] != "active_local" { return Err(Error::new(ErrorKind::ValidationStale,"received resource is retired")); }
        let (text,checksum): (String,String) = self.connection.query_row("SELECT payload_json,payload_hash FROM received_resources WHERE transfer_id=?1",[transfer_id],|row|Ok((row.get(0)?,row.get(1)?)))?;
        let payload = checked_payload(&text,&checksum,source,self,permit)?;
        let content=crate::received::current_view(&self.connection,&self.workspace,source,&self.scope,permit,transfer_id,wall_clock()?)?;
        Ok(json!({"ack":ack,"origin_scope":payload.source_scope,"owning_scope":self.scope,"envelope":payload.envelope,
            "owner_content":content,"envelope_is_immutable_origin_snapshot":true,
            "classification":"project_private","runtime_or_global_admission":false,"read_authority":"explicit-two-isolated-workspace-grant"}))
    }

    pub fn retire_received_resource(&mut self, source: &Store, permit: &LocalTransferPermit, transfer_id: &str, expected_revision: u64, key: &str) -> Result<Value> {
        permit.check(source,self)?;
        valid_event(key)?;
        let operation = strict_json::digest(&json!({"operation":"retire-received-resource","transfer_id":transfer_id,"expected_revision":expected_revision,"source_scope":source.scope,"target_scope":self.scope}))?;
        let expected = i64::try_from(expected_revision).map_err(|_|Error::new(ErrorKind::RevisionConflict,"owner revision overflow"))?;
        let next = expected.checked_add(1).ok_or_else(||Error::new(ErrorKind::RevisionConflict,"owner revision overflow"))?;
        self.resource_transfer_ack(source,permit,transfer_id)?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        crate::local_identity::require(&source.connection,&source.workspace,&source.scope)?;
        if let Some(result) = replay(&transaction,key,&operation)? { return Ok(result); }
        check_clock(&transaction,wall_clock()?)?;
        let changed = transaction.execute("UPDATE received_resources SET state='retired',owner_revision=?1 WHERE transfer_id=?2 AND owner_revision=?3 AND state='active_local'",params![next,transfer_id,expected])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"received resource owner revision/state changed")); }
        let result = json!({"transfer_id":transfer_id,"state":"retired","owning_scope":self.scope,"owner_revision":next,"source_writable":false});
        record_event(&transaction,key,&operation,&result)?;
        transaction.commit()?;
        Ok(result)
    }
}
