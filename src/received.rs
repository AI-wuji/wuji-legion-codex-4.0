use crate::contracts::Schemas;
use crate::error::{Error,ErrorKind,Result};
use crate::graph::ExactRef;
use crate::resources::{LocalResourceReviewPermit,ResourceKind,current_resource_resolved,registered_evidence,record_event,replay,valid_event};
use crate::store::{Store,check_clock,wall_clock};
use crate::strict_json;
use crate::transfers::{LocalTransferPermit,TransferPayload,checked_payload_grant,received_knowledge};
use rusqlite::{Connection,OptionalExtension,TransactionBehavior,params};
use serde::{Deserialize,Serialize};
use serde_json::{Value,json};
use std::collections::{BTreeMap,BTreeSet};

const VERSION_RELEASE: &str = "received-resource-1";

#[derive(Clone,Debug,Deserialize,Serialize,PartialEq)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeBinding { pub origin_ref: ExactRef, pub owner_ref: ExactRef }

#[derive(Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReceivedDelta {
    pub delta: Value,
    pub changes: BTreeMap<String,Value>,
    pub knowledge_bindings: Vec<KnowledgeBinding>,
}

#[derive(Clone,Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
struct OwnerVersion {
    schema_version: u64,
    transfer_id: String,
    resource_type: String,
    origin_ref: ExactRef,
    scope: String,
    revision: u64,
    parent_ref: Option<ExactRef>,
    delta: Option<Value>,
    content: Value,
    knowledge_bindings: Vec<KnowledgeBinding>,
    writer: String,
}

struct Origin { payload: TransferPayload, revision: u64, state: String }

fn revision(value: u64) -> Result<i64> {
    i64::try_from(value).map_err(|_|Error::new(ErrorKind::RevisionConflict,"received owner revision overflow"))
}

fn resource_kind(value: &str) -> Result<ResourceKind> {
    match value { "KnowledgeRecord" => Ok(ResourceKind::Knowledge),"ExperienceCandidate" => Ok(ResourceKind::Experience),
        _ => Err(Error::new(ErrorKind::Shape,"received resource kind invalid")) }
}

fn origin(connection: &Connection, source: &Store, scope: &str, permit: &LocalTransferPermit, id: &str) -> Result<Origin> {
    valid_event(id)?;
    let row: Option<(String,String,i64,String)> = connection.query_row(
        "SELECT payload_json,payload_hash,owner_revision,state FROM received_resources WHERE transfer_id=?1",[id],
        |row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).optional()?;
    let (text,hash,owner_revision,state) = row.ok_or_else(||Error::new(ErrorKind::Reference,"received ownership not recorded"))?;
    let payload = checked_payload_grant(&text,&hash,&source.scope,scope,permit)?;
    let frozen: Option<String> = source.connection.query_row(
        "SELECT payload_hash FROM resource_transfers WHERE transfer_id=?1 AND state IN ('transfer_pending','shared_ref')",[id],|row|row.get(0)).optional()?;
    if frozen.as_deref() != Some(&hash) || payload.transfer_id != id || owner_revision < 1 {
        return Err(Error::new(ErrorKind::HashMismatch,"received ownership differs from frozen origin intent"));
    }
    Ok(Origin { payload,revision:owner_revision as u64,state })
}

fn base_version(origin: &Origin, scope: &str) -> OwnerVersion {
    OwnerVersion { schema_version:1,transfer_id:origin.payload.transfer_id.clone(),resource_type:origin.payload.kind.clone(),
        origin_ref:origin.payload.source_reference.clone(),scope:scope.into(),revision:1,parent_ref:None,delta:None,
        content:origin.payload.envelope["payload"].clone(),knowledge_bindings:Vec::new(),writer:"aji-local".into() }
}

fn reference(version: &OwnerVersion) -> Result<ExactRef> {
    let reference = ExactRef { id:version.transfer_id.clone(),r#type:"ReceivedResourceVersion".into(),scope:version.scope.clone(),
        revision:version.revision,sha256:strict_json::digest(&serde_json::to_value(version)?)?,release:VERSION_RELEASE.into(),schema_version:1 };
    Schemas::frozen()?.check_definition("ExactRef",&serde_json::to_value(&reference)?)?;
    Ok(reference)
}

fn load_version(connection: &Connection, origin: &Origin, scope: &str, requested: u64) -> Result<(OwnerVersion,String)> {
    let row: Option<(String,String,String)> = connection.query_row(
        "SELECT version_json,content_hash,state FROM received_resource_versions WHERE transfer_id=?1 AND revision=?2",
        params![origin.payload.transfer_id,revision(requested)?],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
    let (version,state) = match row {
        Some((text,hash,state)) => {
            let value = strict_json::parse(text.as_bytes())?;
            if strict_json::digest(&value)? != hash { return Err(Error::new(ErrorKind::HashMismatch,"received immutable version hash changed")); }
            (serde_json::from_value::<OwnerVersion>(value)?,state)
        }
        None if requested == 1 => (base_version(origin,scope),if origin.revision==1 { origin.state.clone() } else { "superseded".into() }),
        None => return Err(Error::new(ErrorKind::ValidationStale,"current received content version missing")),
    };
    if version.schema_version != 1 || version.transfer_id != origin.payload.transfer_id || version.resource_type != origin.payload.kind
        || version.origin_ref != origin.payload.source_reference || version.scope != scope || version.revision != requested || version.writer != "aji-local" {
        return Err(Error::new(ErrorKind::ScopeDenied,"received version identity or provenance changed"));
    }
    if requested==1 {
        if strict_json::digest(&serde_json::to_value(&version)?)? != strict_json::digest(&serde_json::to_value(base_version(origin,scope))?)? {
            return Err(Error::new(ErrorKind::HashMismatch,"received base version differs from immutable origin"));
        }
    } else {
        let parent = version.parent_ref.as_ref().ok_or_else(||Error::new(ErrorKind::Reference,"received delta parent missing"))?;
        if parent.revision != requested-1 || parent.id != version.transfer_id || parent.scope != scope
            || parent.r#type != "ReceivedResourceVersion" || parent.release != VERSION_RELEASE || parent.schema_version != 1 || version.delta.is_none() {
            return Err(Error::new(ErrorKind::Reference,"received delta cannot skip or repin its exact parent"));
        }
        let (text,hash): (String,String) = connection.query_row(
            "SELECT version_json,content_hash FROM received_resource_versions WHERE transfer_id=?1 AND revision=?2",
            params![version.transfer_id,revision(parent.revision)?],|row|Ok((row.get(0)?,row.get(1)?)))?;
        if hash != parent.sha256 || strict_json::digest(&strict_json::parse(text.as_bytes())?)? != hash {
            return Err(Error::new(ErrorKind::HashMismatch,"received delta parent bytes changed"));
        }
    }
    Ok((version,state))
}

fn virtual_envelope(origin: &Origin, version: &OwnerVersion) -> Result<Value> {
    let mut value = origin.payload.envelope.clone();
    value["payload"] = version.content.clone();
    value["metadata"]["content_hash"] = json!(strict_json::object_digest(&value)?);
    Schemas::frozen()?.check_envelope(&value)?;
    Ok(value)
}

fn validate_delta(connection: &Connection, workspace: &crate::policy::Workspace, scope: &str, origin: &Origin,
    delta: &Value, parent: &ExactRef, bindings: &[KnowledgeBinding], now: i64) -> Result<()> {
    Schemas::frozen()?.check_envelope(delta)?;
    let metadata = &delta["metadata"];
    let payload = &delta["payload"];
    if delta["contract_type"] != "ResourceDelta" || metadata["type"] != "ResourceDelta" || metadata["owner"] != "aji-local"
        || metadata["authority"] != "review_proposal" || metadata["status"] != "proposal" || metadata["classification"] != "project_private" {
        return Err(Error::new(ErrorKind::AuthorityDenied,"received delta cannot self-authorize or promote private facts"));
    }
    if metadata["scope"] != scope || payload["scope"] != scope || payload["target_type"] != origin.payload.kind
        || payload["target_id"] != origin.payload.source_reference.id || payload["expected_revision"].as_u64() != Some(parent.revision) {
        return Err(Error::new(ErrorKind::ScopeDenied,"received delta type, identity, owner scope or parent mismatch"));
    }
    if metadata["valid_until_utc_ms"].as_i64().is_some_and(|expiry|expiry<=now) || payload["reason"].as_str().is_none_or(|text|text.trim().is_empty()) {
        return Err(Error::new(ErrorKind::ValidationStale,"received delta needs current authorization context and nonempty reason"));
    }
    let evidence: Vec<ExactRef> = serde_json::from_value(payload["evidence"].clone())?;
    if evidence.is_empty() || evidence.len()>16 { return Err(Error::new(ErrorKind::Reference,"received delta needs 1..16 actual owner evidence files")); }
    for item in evidence { registered_evidence(connection,workspace,scope,&item)?; }
    let declared: Vec<ExactRef> = serde_json::from_value(payload["revalidation_refs"].clone())?;
    let mut required=vec![parent.clone()];
    required.extend(bindings.iter().map(|binding|binding.owner_ref.clone()));
    if declared.len()!=required.len() || required.iter().any(|item|declared.iter().filter(|actual|*actual==item).count()!=1) {
        return Err(Error::new(ErrorKind::Reference,"received delta must revalidate exact parent and every explicit knowledge owner version"));
    }
    valid_event(payload["idempotency_key"].as_str().ok_or_else(||Error::new(ErrorKind::Shape,"delta event key required"))?)?;
    Ok(())
}

fn patch_content(kind: ResourceKind, current: &Value, changes: &BTreeMap<String,Value>, operation: &str) -> Result<Value> {
    if changes.len()>8 { return Err(Error::new(ErrorKind::BudgetExhausted,"received delta field budget exceeded")); }
    let allowed: &[&str] = match kind { ResourceKind::Knowledge => &["claim","method","freshness","conflicts"],
        ResourceKind::Experience => &["trigger","method","counterexamples","expiry_utc_ms","type"] };
    let mut content=current.clone();
    for (key,value) in changes {
        if !allowed.contains(&key.as_str()) { return Err(Error::new(ErrorKind::RequiredWeakened,"received delta cannot replace scope, origin, evidence, authority or unrelated professional fields")); }
        if operation=="merge" && &content[key]!=value {
            let previous=content[key].as_array().ok_or_else(||Error::new(ErrorKind::CompositionConflict,"merge cannot silently overwrite distinct scalar methods"))?;
            let additions=value.as_array().ok_or_else(||Error::new(ErrorKind::CompositionConflict,"merge requires an explicit collection"))?;
            let mut merged=previous.clone();
            for addition in additions { if !merged.contains(addition) { merged.push(addition.clone()); } }
            content[key]=json!(merged);
        } else { content[key]=value.clone(); }
    }
    Ok(content)
}

fn validate_version(connection: &Connection, workspace: &crate::policy::Workspace, source: &Store, scope: &str,
    permit: &LocalTransferPermit, origin: &Origin, version: &OwnerVersion, now: i64) -> Result<()> {
    let last_clock: i64=connection.query_row("SELECT last_clock_ms FROM workspace_meta WHERE singleton=1",[],|row|row.get(0))?;
    if now<last_clock { return Err(Error::new(ErrorKind::ClockUntrusted,"received content query clock moved backwards")); }
    let kind=resource_kind(&origin.payload.kind)?;
    let allowed: &[&str]=match kind { ResourceKind::Knowledge => &["claim","method","freshness","conflicts"],
        ResourceKind::Experience => &["trigger","method","counterexamples","expiry_utc_ms","type"] };
    for (key,value) in origin.payload.envelope["payload"].as_object().unwrap() {
        if !allowed.contains(&key.as_str()) && version.content.get(key)!=Some(value) {
            return Err(Error::new(ErrorKind::RequiredWeakened,"received view changed protected origin fields"));
        }
    }
    if let Some(delta)=&version.delta {
        let parent=version.parent_ref.as_ref().ok_or_else(||Error::new(ErrorKind::Reference,"received delta parent missing"))?;
        validate_delta(connection,workspace,scope,origin,delta,parent,&version.knowledge_bindings,now)?;
        if !["update","merge"].contains(&delta["payload"]["operation"].as_str().unwrap_or("")) {
            return Err(Error::new(ErrorKind::Shape,"reusable received content must be update or merge, not an implicit add or retirement"));
        }
    }
    if version.knowledge_bindings.len()>16 || (kind==ResourceKind::Knowledge && !version.knowledge_bindings.is_empty()) {
        return Err(Error::new(ErrorKind::Shape,"only experience may carry bounded explicit knowledge bindings"));
    }
    let declared:Vec<ExactRef>=if kind==ResourceKind::Experience { serde_json::from_value(origin.payload.envelope["payload"]["knowledge_refs"].clone())? } else { Vec::new() };
    let mut unique=BTreeSet::new();
    for binding in &version.knowledge_bindings {
        Schemas::frozen()?.check_definition("ExactRef",&serde_json::to_value(&binding.owner_ref)?)?;
        if !declared.contains(&binding.origin_ref) || !unique.insert(binding.origin_ref.id.clone()) {
            return Err(Error::new(ErrorKind::Reference,"received knowledge bindings cannot add unrelated or duplicate origin dependencies"));
        }
        if binding.owner_ref.scope!=scope || binding.owner_ref.r#type!="ReceivedResourceVersion" || binding.owner_ref.release!=VERSION_RELEASE {
            return Err(Error::new(ErrorKind::ScopeDenied,"knowledge binding must name an exact version in the same authorized owner scope"));
        }
    }
    let envelope=virtual_envelope(origin,version)?;
    current_resource_resolved(&source.connection,&source.workspace,&source.scope,kind,&envelope,now,&mut |reference| {
        if let Some(binding)=version.knowledge_bindings.iter().find(|binding|binding.origin_ref==*reference) {
            let knowledge=crate::received::origin(connection,source,scope,permit,&binding.owner_ref.id)?;
            if knowledge.state!="active_local" || knowledge.payload.kind!="KnowledgeRecord" || knowledge.payload.source_reference!=*reference {
                return Err(Error::new(ErrorKind::ValidationStale,"bound knowledge ownership or origin dependency differs"));
            }
            let (current,state)=load_version(connection,&knowledge,scope,knowledge.revision)?;
            if state!="active_local" || crate::received::reference(&current)?!=binding.owner_ref {
                return Err(Error::new(ErrorKind::ValidationStale,"bound knowledge owner content was changed, unreviewed or retired; no latest fallback"));
            }
            validate_version(connection,workspace,source,scope,permit,&knowledge,&current,now)?;
            Ok(Some(knowledge.payload.envelope))
        } else { received_knowledge(&source.connection,connection,&source.scope,scope,permit,reference) }
    })
}

pub(crate) fn current_view(connection: &Connection, workspace: &crate::policy::Workspace, source: &Store, scope: &str,
    permit: &LocalTransferPermit, id: &str, now: i64) -> Result<Value> {
    crate::local_identity::require(connection,workspace,scope)?;
    crate::local_identity::require(&source.connection,&source.workspace,&source.scope)?;
    let origin=origin(connection,source,scope,permit,id)?;
    if origin.state!="active_local" { return Err(Error::new(ErrorKind::ValidationStale,"received resource ownership is retired")); }
    let (version,state)=load_version(connection,&origin,scope,origin.revision)?;
    if state!="active_local" { return Err(Error::new(ErrorKind::ValidationStale,"received owner content awaits independent local review")); }
    validate_version(connection,workspace,source,scope,permit,&origin,&version,now)?;
    Ok(json!({"reference":reference(&version)?,"version":version,"state":state,
        "origin_is_not_rewritten":true,"not_an_origin_KnowledgeRecord_or_ExperienceCandidate_revision":true,
        "professional_effectiveness":"not_claimed","runtime_or_global_admission":false}))
}

pub(crate) fn content_status(connection: &Connection, id: &str, owner_revision: i64, ownership_state: &str) -> Result<Value> {
    let row:Option<(i64,String,String)>=connection.query_row(
        "SELECT revision,content_hash,state FROM received_resource_versions WHERE transfer_id=?1 ORDER BY revision DESC LIMIT 1",[id],
        |row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
    match row {
        Some((revision,hash,state)) if ownership_state=="retired" || revision==owner_revision =>
            Ok(json!({"content_revision":revision,"content_hash":hash,"content_state":if ownership_state=="retired" { "retired" } else { state.as_str() },
                "owner_revision_is_not_origin_revision":true})),
        None if ownership_state=="retired" || owner_revision==1 =>
            Ok(json!({"content_revision":1,"content_state":ownership_state,"owner_revision_is_not_origin_revision":true})),
        _ => Err(Error::new(ErrorKind::ValidationStale,"received ownership pointer has no matching content version")),
    }
}

impl Store {
    pub fn propose_received_delta(&mut self, source: &Store, permit: &LocalTransferPermit, id: &str,
        request: &ReceivedDelta, confirmation: &str) -> Result<Value> {
        permit.check(source,self)?;
        if confirmation!="confirm-isolated-received-content-delta" {
            return Err(Error::new(ErrorKind::AuthorityDenied,"received content update needs explicit isolated owner authorization"));
        }
        let key=request.delta["payload"]["idempotency_key"].as_str().ok_or_else(||Error::new(ErrorKind::Shape,"delta event key required"))?;
        valid_event(key)?;
        let operation_hash=strict_json::digest(&json!({"operation":"received-content-delta","transfer_id":id,"source_scope":source.scope,
            "target_scope":self.scope,"request":request}))?;
        let transaction=self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        crate::local_identity::require(&source.connection,&source.workspace,&source.scope)?;
        if let Some(result)=replay(&transaction,key,&operation_hash)? { return Ok(result); }
        let now=wall_clock()?;
        check_clock(&transaction,now)?;
        let original=origin(&transaction,source,&self.scope,permit,id)?;
        if original.state!="active_local" { return Err(Error::new(ErrorKind::ValidationStale,"retired received ownership cannot be revived by a content delta")); }
        let expected=request.delta["payload"]["expected_revision"].as_u64().ok_or_else(||Error::new(ErrorKind::Shape,"owner expected revision required"))?;
        if expected!=original.revision { return Err(Error::new(ErrorKind::RevisionConflict,"received delta expected owner revision is stale")); }
        let (previous,_)=load_version(&transaction,&original,&self.scope,expected)?;
        let parent=reference(&previous)?;
        validate_delta(&transaction,&self.workspace,&self.scope,&original,&request.delta,&parent,&request.knowledge_bindings,now)?;
        let operation=request.delta["payload"]["operation"].as_str().unwrap();
        let next=expected.checked_add(1).ok_or_else(||Error::new(ErrorKind::RevisionConflict,"received revision overflow"))?;
        revision(next)?;
        if operation=="retire" {
            if !request.changes.is_empty() || !request.knowledge_bindings.is_empty() {
                return Err(Error::new(ErrorKind::RequiredWeakened,"retirement cannot also replace content or knowledge dependencies"));
            }
            let changed=transaction.execute("UPDATE received_resources SET owner_revision=?1,state='retired' WHERE transfer_id=?2 AND owner_revision=?3 AND state='active_local'",
                params![revision(next)?,id,revision(expected)?])?;
            if changed!=1 { return Err(Error::new(ErrorKind::RevisionConflict,"received retirement CAS failed")); }
            transaction.execute("UPDATE received_resource_versions SET state='retired' WHERE transfer_id=?1 AND revision=?2",params![id,revision(expected)?])?;
            let result=json!({"transfer_id":id,"owner_revision":next,"state":"retired","source_writable":false,
                "delta":request.delta,"runtime_or_global_admission":false,"observation_kind":"historical_transaction_not_current_eligibility"});
            record_event(&transaction,key,&operation_hash,&result)?;
            transaction.commit()?;
            return Ok(result);
        }
        if !["update","merge"].contains(&operation) { return Err(Error::new(ErrorKind::Shape,"add requires original transfer admission; received delta supports update, bounded merge or retire")); }
        let content=patch_content(resource_kind(&original.payload.kind)?,&previous.content,&request.changes,operation)?;
        if content==previous.content && request.knowledge_bindings==previous.knowledge_bindings {
            return Err(Error::new(ErrorKind::RevisionConflict,"no semantic delta; retries or feedback counts are not progress"));
        }
        let version=OwnerVersion { revision:next,parent_ref:Some(parent),delta:Some(request.delta.clone()),content,
            knowledge_bindings:request.knowledge_bindings.clone(),..previous.clone() };
        validate_version(&transaction,&self.workspace,source,&self.scope,permit,&original,&version,now)?;
        let proposed=reference(&version)?;
        if expected==1 {
            transaction.execute("INSERT INTO received_resource_versions VALUES(?1,1,?2,?3,'superseded')",
                params![id,reference(&previous)?.sha256,serde_json::to_string(&previous)?])?;
        } else {
            transaction.execute("UPDATE received_resource_versions SET state='superseded' WHERE transfer_id=?1 AND revision=?2",params![id,revision(expected)?])?;
        }
        transaction.execute("INSERT INTO received_resource_versions VALUES(?1,?2,?3,?4,'candidate')",
            params![id,revision(next)?,proposed.sha256,serde_json::to_string(&version)?])?;
        let changed=transaction.execute("UPDATE received_resources SET owner_revision=?1 WHERE transfer_id=?2 AND owner_revision=?3 AND state='active_local'",
            params![revision(next)?,id,revision(expected)?])?;
        if changed!=1 { return Err(Error::new(ErrorKind::RevisionConflict,"received content pointer CAS failed")); }
        let result=json!({"transfer_id":id,"reference":proposed,"state":"candidate","source_writable":false,
            "origin_ref":version.origin_ref,"changed_fields":request.changes.keys().collect::<Vec<_>>(),
            "runtime_or_global_admission":false,"observation_kind":"historical_transaction_not_current_eligibility"});
        record_event(&transaction,key,&operation_hash,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn review_received_delta(&mut self, source: &Store, transfer: &LocalTransferPermit, review: &LocalResourceReviewPermit,
        id: &str, requested: &ExactRef, key: &str) -> Result<Value> {
        transfer.check(source,self)?;
        review.check(self)?;
        valid_event(key)?;
        let operation=strict_json::digest(&json!({"operation":"received-content-independent-local-review","source_scope":source.scope,
            "target_scope":self.scope,"transfer_id":id,"reference":requested}))?;
        let transaction=self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        crate::local_identity::require(&source.connection,&source.workspace,&source.scope)?;
        if let Some(result)=replay(&transaction,key,&operation)? { return Ok(result); }
        let now=wall_clock()?;
        check_clock(&transaction,now)?;
        let original=origin(&transaction,source,&self.scope,transfer,id)?;
        let (version,state)=load_version(&transaction,&original,&self.scope,original.revision)?;
        if original.state!="active_local" || state!="candidate" || reference(&version)?!=*requested {
            return Err(Error::new(ErrorKind::RevisionConflict,"review must match the current candidate exactly; old reviews do not activate new versions"));
        }
        validate_version(&transaction,&self.workspace,source,&self.scope,transfer,&original,&version,now)?;
        let changed=transaction.execute("UPDATE received_resource_versions SET state='active_local' WHERE transfer_id=?1 AND revision=?2 AND content_hash=?3 AND state='candidate'",
            params![id,revision(version.revision)?,requested.sha256])?;
        if changed!=1 { return Err(Error::new(ErrorKind::RevisionConflict,"received review CAS failed")); }
        let result=json!({"transfer_id":id,"reference":requested,"state":"active_local","writer":version.writer,
            "validator":"local-resource-validator","producer_reviewer_distinct":true,"review_scope":"structural-and-current-evidence-only",
            "professional_effectiveness":"not_claimed","runtime_or_global_admission":false,"source_writable":false,
            "observation_kind":"historical_review_event_not_current_eligibility"});
        record_event(&transaction,key,&operation,&result)?;
        transaction.commit()?;
        Ok(result)
    }
}
