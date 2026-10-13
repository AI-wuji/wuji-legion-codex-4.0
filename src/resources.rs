use crate::contracts::Schemas;
use crate::error::{Error, ErrorKind, Result};
use crate::graph::ExactRef;
use crate::policy::Workspace;
use crate::store::{Store, bounded_file, check_clock, wall_clock};
use crate::strict_json;
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

const RESOURCE_RELEASE: &str = "project-resource-1";

fn sql_revision(value: u64) -> Result<i64> {
    i64::try_from(value).map_err(|_| Error::new(ErrorKind::Shape,"resource revision exceeds SQLite integer range"))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResourceKind { Knowledge, Experience }

impl ResourceKind {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "knowledge" => Ok(Self::Knowledge), "experience" => Ok(Self::Experience),
            _ => Err(Error::new(ErrorKind::Shape, "resource kind must be knowledge or experience")),
        }
    }

    pub(crate) fn table(self) -> &'static str {
        match self { Self::Knowledge => "knowledge_records", Self::Experience => "experience_records" }
    }

    pub(crate) fn contract(self) -> &'static str {
        match self { Self::Knowledge => "KnowledgeRecord", Self::Experience => "ExperienceCandidate" }
    }
}

pub struct LocalResourceReviewPermit { root: PathBuf }

impl LocalResourceReviewPermit {
    pub fn confirm_isolated(root: &Path, confirmation: &str) -> Result<Self> {
        if confirmation != "confirm-isolated-project-resource-review" {
            return Err(Error::new(ErrorKind::AuthorityDenied, "explicit isolated development review confirmation required"));
        }
        let workspace = Workspace::open(root)?;
        let development = std::fs::canonicalize(Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev"))?;
        if !workspace.root().starts_with(&development) || workspace.root() == development {
            return Err(Error::new(ErrorKind::ScopeDenied, "local resource activation is restricted to a separate .dev workspace"));
        }
        Ok(Self { root: workspace.root().to_owned() })
    }

    pub(crate) fn check(&self, store: &Store) -> Result<()> {
        if self.root != store.workspace.root() {
            return Err(Error::new(ErrorKind::ScopeDenied, "resource review permit belongs to a different workspace"));
        }
        Ok(())
    }
}

pub(crate) fn exact(envelope: &Value, kind: ResourceKind) -> Result<ExactRef> {
    let metadata = &envelope["metadata"];
    Ok(ExactRef {
        id: metadata["id"].as_str().ok_or_else(|| Error::new(ErrorKind::Shape, "resource id missing"))?.to_owned(),
        r#type: kind.contract().to_owned(),
        scope: metadata["scope"].as_str().ok_or_else(|| Error::new(ErrorKind::Shape, "resource scope missing"))?.to_owned(),
        revision: metadata["revision"].as_u64().ok_or_else(|| Error::new(ErrorKind::Shape, "resource revision missing"))?,
        sha256: strict_json::object_digest(envelope)?, release: RESOURCE_RELEASE.to_owned(), schema_version: 1,
    })
}

pub(crate) fn registered_evidence(connection: &Connection, workspace: &Workspace, scope: &str, reference: &ExactRef) -> Result<Vec<u8>> {
    if reference.scope != scope || reference.r#type != "file" || reference.schema_version != 1 {
        return Err(Error::new(ErrorKind::ScopeDenied, "evidence must be an exact registered file in this project scope"));
    }
    let stored: Option<(String, String, String, String)> = connection.query_row(
        "SELECT path,sha256,release_id,state FROM input_files WHERE id=?1 AND revision=?2 AND scope=?3",
        params![reference.id, sql_revision(reference.revision)?, scope],
        |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).optional()?;
    let (path, hash, release, state) = stored.ok_or_else(|| Error::new(ErrorKind::Reference, "resource evidence was not registered"))?;
    if reference.sha256 != hash || reference.release != release || state != "adopted_user_input" {
        return Err(Error::new(ErrorKind::ValidationStale, "resource evidence is no longer currently adopted"));
    }
    let bytes = bounded_file(&workspace.resolve(Path::new(&path))?)?;
    if strict_json::sha256(&bytes) != hash {
        return Err(Error::new(ErrorKind::ValidationStale, "resource evidence file changed"));
    }
    Ok(bytes)
}

fn references(value: &Value) -> Result<Vec<ExactRef>> {
    let references: Vec<ExactRef> = serde_json::from_value(value.clone())?;
    if references.is_empty() || references.len() > 16 {
        return Err(Error::new(ErrorKind::Reference, "resource requires 1..16 bounded evidence references"));
    }
    Ok(references)
}

pub(crate) fn current_resource(connection: &Connection, workspace: &Workspace, scope: &str,
    kind: ResourceKind, envelope: &Value, now: i64) -> Result<()> {
    current_resource_resolved(connection,workspace,scope,kind,envelope,now,&mut |_| Ok(None))
}

pub(crate) fn current_resource_resolved(connection: &Connection, workspace: &Workspace, scope: &str,
    kind: ResourceKind, envelope: &Value, now: i64,
    resolve: &mut impl FnMut(&ExactRef) -> Result<Option<Value>>) -> Result<()> {
    crate::local_identity::require(connection,workspace,scope)?;
    let last_clock: i64 = connection.query_row("SELECT last_clock_ms FROM workspace_meta WHERE singleton=1",[],|row|row.get(0))?;
    if now < last_clock { return Err(Error::new(ErrorKind::ClockUntrusted,"resource query clock moved backwards")); }
    let payload = &envelope["payload"];
    if payload["scope"] != scope || envelope["metadata"]["scope"] != scope {
        return Err(Error::new(ErrorKind::ScopeDenied, "resource payload/metadata scope must match project"));
    }
    let field = if kind == ResourceKind::Knowledge { "source_refs" } else { "evidence" };
    let evidence = references(&payload[field])?;
    for reference in &evidence {
        registered_evidence(connection, workspace, scope, &reference)?;
    }
    if kind == ResourceKind::Knowledge {
        if payload["sha256"] != evidence[0].sha256 {
            return Err(Error::new(ErrorKind::HashMismatch, "knowledge primary source hash differs from exact evidence"));
        }
        if payload["freshness"] != "current" || payload["conflicts"].as_array().is_none_or(|items| !items.is_empty()) {
            return Err(Error::new(ErrorKind::ValidationStale, "stale or disputed knowledge is not reusable"));
        }
        if payload["knowledge_id"] != envelope["metadata"]["id"] || payload["claim"].as_str().is_none_or(str::is_empty) {
            return Err(Error::new(ErrorKind::Reference, "knowledge identity and nonempty claim required"));
        }
    } else {
        if payload["expiry_utc_ms"].as_i64().is_some_and(|expiry| expiry <= now) {
            return Err(Error::new(ErrorKind::ValidationStale, "experience expired"));
        }
        if payload["trigger"].as_str().is_none_or(str::is_empty) || payload["method"].as_str().is_none_or(str::is_empty)
            || payload["counterexamples"].as_array().is_none_or(|items| items.is_empty() || items.iter().any(|item| item.as_str().is_none_or(str::is_empty))) {
            return Err(Error::new(ErrorKind::Shape, "experience requires trigger, method and explicit counterexamples"));
        }
        for reference in references(&payload["knowledge_refs"])? {
            if reference.scope != scope || reference.r#type != ResourceKind::Knowledge.contract()
                || reference.release != RESOURCE_RELEASE || reference.schema_version != 1 {
                return Err(Error::new(ErrorKind::ScopeDenied, "experience knowledge reference must be exact and same scope"));
            }
            let knowledge = match resolve(&reference)? {
                Some(knowledge) => knowledge,
                None => {
                    require_record_scope(connection,ResourceKind::Knowledge,&reference.id,scope)?;
                    resource_write_authority(connection,ResourceKind::Knowledge,&reference.id)?;
                    let stored: Option<(String,String)> = connection.query_row(
                        "SELECT envelope_json,content_hash FROM knowledge_records WHERE id=?1 AND revision=?2 AND scope=?3 AND state='active_local'",
                        params![reference.id,sql_revision(reference.revision)?,scope],|row|Ok((row.get(0)?,row.get(1)?))).optional()?;
                    let (text,hash) = stored.ok_or_else(||Error::new(ErrorKind::ValidationStale,"experience knowledge version was retired or superseded"))?;
                    if hash != reference.sha256 { return Err(Error::new(ErrorKind::HashMismatch,"experience knowledge digest mismatch")); }
                    strict_json::parse(text.as_bytes())?
                }
            };
            if exact(&knowledge,ResourceKind::Knowledge)? != reference {
                return Err(Error::new(ErrorKind::HashMismatch,"resolved knowledge envelope differs from exact origin reference"));
            }
            current_resource(connection, workspace, scope, ResourceKind::Knowledge, &knowledge, now)?;
        }
    }
    if envelope["metadata"]["valid_until_utc_ms"].as_i64().is_some_and(|expiry| expiry <= now) {
        return Err(Error::new(ErrorKind::ValidationStale, "resource metadata expired"));
    }
    Ok(())
}

pub(crate) fn replay(transaction: &Transaction<'_>, event: &str, hash: &str) -> Result<Option<Value>> {
    let stored: Option<(String,String)> = transaction.query_row(
        "SELECT payload_hash,result_json FROM resource_events WHERE event_key=?1", [event],
        |row| Ok((row.get(0)?,row.get(1)?))).optional()?;
    match stored {
        Some((previous, result)) if previous == hash => Ok(Some(strict_json::parse(result.as_bytes())?)),
        Some(_) => Err(Error::new(ErrorKind::EventConflict, "resource event key already has a different payload")),
        None => Ok(None),
    }
}

pub(crate) fn record_event(transaction: &Transaction<'_>, event: &str, hash: &str, result: &Value) -> Result<()> {
    transaction.execute("INSERT INTO resource_events(event_key,payload_hash,result_json) VALUES(?1,?2,?3)",
        params![event,hash,String::from_utf8(strict_json::canonical(result)?).unwrap()])?;
    Ok(())
}

pub(crate) fn valid_event(event: &str) -> Result<()> {
    if event.is_empty() || event.len() > 128 || event.chars().any(char::is_control) {
        return Err(Error::new(ErrorKind::Shape, "bounded nonempty resource event key required"));
    }
    Ok(())
}

pub(crate) fn require_record_scope(connection: &Connection, kind: ResourceKind, id: &str, scope: &str) -> Result<()> {
    let mismatch: bool = connection.query_row(&format!("SELECT EXISTS(SELECT 1 FROM {} WHERE id=?1 AND scope<>?2)",kind.table()),
        params![id,scope], |row| row.get(0))?;
    if mismatch { return Err(Error::new(ErrorKind::ScopeDenied,"resource identity has a version in another scope")); }
    Ok(())
}

pub(crate) fn resource_write_authority(connection: &Connection, kind: ResourceKind, id: &str) -> Result<()> {
    let frozen: bool = connection.query_row("SELECT EXISTS(SELECT 1 FROM resource_transfers WHERE kind=?1 AND resource_id=?2)",params![kind.contract(),id],|row|row.get(0))?;
    if frozen { return Err(Error::new(ErrorKind::ValidationStale,"resource ownership is frozen for transfer or moved to a read-only shared reference")); }
    let received: bool = connection.query_row("SELECT EXISTS(SELECT 1 FROM received_resources WHERE kind=?1 AND resource_id=?2)",params![kind.contract(),id],|row|row.get(0))?;
    if received { return Err(Error::new(ErrorKind::OwnerConflict,"resource ID is owned by a received transfer; cannot create a second local writable fact")); }
    Ok(())
}

impl Store {
    pub fn propose_resource(&mut self, kind: ResourceKind, envelope: &Value,
        expected_revision: u64, event: &str) -> Result<Value> {
        valid_event(event)?;
        Schemas::frozen()?.check_envelope(envelope)?;
        if envelope["contract_type"] != kind.contract() || envelope["metadata"]["type"] != kind.contract() {
            return Err(Error::new(ErrorKind::Shape, "resource knowledge/experience type mismatch"));
        }
        if envelope["metadata"]["authority"] != "review_proposal" || envelope["metadata"]["classification"] != "project_private"
            || envelope["metadata"]["owner"] != "aji-local" || envelope["metadata"]["status"] != "proposal" {
            return Err(Error::new(ErrorKind::AuthorityDenied, "candidate cannot self-grant public or user authority"));
        }
        if kind == ResourceKind::Knowledge && envelope["payload"]["authority"] != "review_proposal" {
            return Err(Error::new(ErrorKind::AuthorityDenied, "local knowledge remains a review proposal, not universal truth"));
        }
        let reference = exact(envelope, kind)?;
        let operation = strict_json::digest(&json!({"kind":kind.contract(),"envelope":envelope,"expected_revision":expected_revision}))?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        if reference.scope != self.scope || envelope["payload"]["scope"] != self.scope {
            return Err(Error::new(ErrorKind::ScopeDenied,"proposal belongs to another resource scope"));
        }
        require_record_scope(&transaction,kind,&reference.id,&self.scope)?;
        if let Some(result) = replay(&transaction, event, &operation)? { return Ok(result); }
        resource_write_authority(&transaction,kind,&reference.id)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        current_resource(&transaction, &self.workspace, &self.scope, kind, envelope, now)?;
        let current: i64 = transaction.query_row(&format!("SELECT coalesce(max(revision),0) FROM {} WHERE id=?1",kind.table()),
            [&reference.id], |row| row.get(0))?;
        if current != sql_revision(expected_revision)? || sql_revision(reference.revision)? != current.checked_add(1).ok_or_else(|| Error::new(ErrorKind::RevisionConflict,"resource revision overflow"))? {
            return Err(Error::new(ErrorKind::RevisionConflict, "resource expected revision is stale"));
        }
        let encoded = String::from_utf8(strict_json::canonical(envelope)?).unwrap();
        transaction.execute(&format!("INSERT INTO {}(id,revision,scope,content_hash,envelope_json,state) VALUES(?1,?2,?3,?4,?5,'candidate')",kind.table()),
            params![reference.id,sql_revision(reference.revision)?,self.scope,reference.sha256,encoded])?;
        let result = json!({"reference":reference,"state":"candidate","runtime_admission":false,"production_or_global_admission":false,"observation_kind":"historical_transaction_result_not_current_eligibility"});
        record_event(&transaction, event, &operation, &result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn review_resource_local(&mut self, permit: &LocalResourceReviewPermit,
        kind: ResourceKind, reference: &ExactRef, event: &str) -> Result<Value> {
        permit.check(self)?;
        valid_event(event)?;
        Schemas::frozen()?.check_definition("ExactRef", &serde_json::to_value(reference)?)?;
        if reference.scope != self.scope || reference.r#type != kind.contract() || reference.release != RESOURCE_RELEASE || reference.schema_version != 1 {
            return Err(Error::new(ErrorKind::ScopeDenied, "local review reference differs from resource type/scope/release"));
        }
        let operation = strict_json::digest(&json!({"operation":"local-isolated-review","reference":reference}))?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        require_record_scope(&transaction,kind,&reference.id,&self.scope)?;
        if let Some(result) = replay(&transaction, event, &operation)? { return Ok(result); }
        resource_write_authority(&transaction,kind,&reference.id)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        let stored: Option<(String,String,String)> = transaction.query_row(
            &format!("SELECT envelope_json,content_hash,state FROM {} WHERE id=?1 AND revision=?2 AND scope=?3",kind.table()),
            params![reference.id,sql_revision(reference.revision)?,self.scope], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
        let (text,hash,state) = stored.ok_or_else(|| Error::new(ErrorKind::Reference,"resource candidate not recorded"))?;
        if hash != reference.sha256 || strict_json::object_digest(&strict_json::parse(text.as_bytes())?)? != hash {
            return Err(Error::new(ErrorKind::HashMismatch,"resource candidate hash differs from reviewed reference"));
        }
        if state != "candidate" {
            return Err(Error::new(ErrorKind::RevisionConflict,"only a candidate may receive a new local review"));
        }
        let latest: i64 = transaction.query_row(&format!("SELECT max(revision) FROM {} WHERE id=?1",kind.table()),
            [&reference.id], |row| row.get(0))?;
        if latest != sql_revision(reference.revision)? { return Err(Error::new(ErrorKind::RevisionConflict,"a newer candidate exists")); }
        current_resource(&transaction, &self.workspace, &self.scope, kind, &strict_json::parse(text.as_bytes())?, now)?;
        transaction.execute(&format!("UPDATE {} SET state='superseded' WHERE id=?1 AND scope=?2 AND state='active_local'",kind.table()), params![reference.id,self.scope])?;
        transaction.execute(&format!("UPDATE {} SET state='active_local' WHERE id=?1 AND revision=?2 AND scope=?3",kind.table()), params![reference.id,sql_revision(reference.revision)?,self.scope])?;
        let result = json!({"reference":reference,"state":"active_local","authority":"isolated-development-review", "runtime_admission":false,"professional_effectiveness":"not_claimed","global_admission":false,"observation_kind":"historical_transaction_result_not_current_eligibility"});
        record_event(&transaction,event,&operation,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn retire_resource(&mut self, kind: ResourceKind, reference: &ExactRef, event: &str) -> Result<Value> {
        valid_event(event)?;
        Schemas::frozen()?.check_definition("ExactRef", &serde_json::to_value(reference)?)?;
        if reference.scope != self.scope || reference.r#type != kind.contract() || reference.release != RESOURCE_RELEASE || reference.schema_version != 1 {
            return Err(Error::new(ErrorKind::ScopeDenied,"retirement is limited to the exact same-scope resource"));
        }
        let operation = strict_json::digest(&json!({"operation":"retire","reference":reference}))?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        require_record_scope(&transaction,kind,&reference.id,&self.scope)?;
        if let Some(result) = replay(&transaction,event,&operation)? { return Ok(result); }
        resource_write_authority(&transaction,kind,&reference.id)?;
        check_clock(&transaction,wall_clock()?)?;
        let changed = transaction.execute(&format!("UPDATE {} SET state='retired' WHERE id=?1 AND revision=?2 AND content_hash=?3 AND scope=?4 AND state IN ('candidate','active_local')",kind.table()),
            params![reference.id,sql_revision(reference.revision)?,reference.sha256,self.scope])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"resource already changed, missing or retired")); }
        let result = json!({"reference":reference,"state":"retired","scope":self.scope});
        record_event(&transaction,event,&operation,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn query_resources(&self, kind: ResourceKind, trigger: &str, cap: usize) -> Result<Value> {
        if cap == 0 || cap > 64 || trigger.len() > 1024 {
            return Err(Error::new(ErrorKind::BudgetExhausted,"resource query requires cap 1..64 and bounded exact trigger"));
        }
        let transaction = self.connection.unchecked_transaction()?;
        crate::local_identity::require(&transaction,&self.workspace,&self.scope)?;
        let mut statement = transaction.prepare(&format!("SELECT id,revision,envelope_json,content_hash FROM {} WHERE scope=?1 AND state='active_local' AND NOT EXISTS(SELECT 1 FROM resource_transfers WHERE kind=?2 AND resource_id=id) ORDER BY id LIMIT 513",kind.table()))?;
        let rows: Vec<(String,i64,String,String)> = statement.query_map(params![self.scope,kind.contract()], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?)))?.collect::<std::result::Result<_,_>>()?;
        if rows.len() > 512 { return Err(Error::new(ErrorKind::BudgetExhausted,"resource scan cap exceeded; narrow scope")); }
        let now = wall_clock()?;
        let mut entries = Vec::new();
        let mut rejected = Vec::new();
        for (id,revision,text,hash) in rows {
            require_record_scope(&transaction,kind,&id,&self.scope)?;
            let envelope = strict_json::parse(text.as_bytes())?;
            let reference = exact(&envelope,kind)?;
            if reference.scope != self.scope || envelope["payload"]["scope"] != self.scope {
                return Err(Error::new(ErrorKind::ScopeDenied,"stored resource envelope belongs to another scope"));
            }
            if reference.id != id || sql_revision(reference.revision)? != revision {
                return Err(Error::new(ErrorKind::HashMismatch,"stored resource row differs from its envelope identity"));
            }
            if reference.sha256 != hash { return Err(Error::new(ErrorKind::HashMismatch,"stored resource changed")); }
            if kind == ResourceKind::Experience && !trigger.is_empty() && envelope["payload"]["trigger"] != trigger { continue; }
            match current_resource(&transaction,&self.workspace,&self.scope,kind,&envelope,now) {
                Ok(()) => entries.push(json!({"reference":reference,"envelope":envelope})),
                Err(error) if matches!(error.kind, ErrorKind::ValidationStale | ErrorKind::Reference | ErrorKind::HashMismatch | ErrorKind::PathDenied | ErrorKind::Io) =>
                    rejected.push(json!({"reference":reference,"reason":format!("{:?}",error.kind)})),
                Err(error) => return Err(error),
            }
            if entries.len() > cap { return Err(Error::new(ErrorKind::BudgetExhausted,"matching resources exceed cap; no silent truncation")); }
        }
        Ok(json!({"scope":self.scope,"kind":kind.contract(),"entries":entries,"rejected":rejected,
            "runtime_admission":false,"professional_effectiveness":"not_claimed","global_admission":false}))
    }
}
