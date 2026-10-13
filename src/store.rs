use crate::contracts::Schemas;
use crate::error::{Error, ErrorKind, Result};
use crate::graph::{self, ExactRef, ExecutionForm, Node, Workflow};
use crate::policy::{ActorContext, Operation, Role, Workspace};
use crate::strict_json;
use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const APPLICATION_ID: i64 = 1465201712;
const SCHEMA_VERSION: i64 = 7;
const SQLITE_SOURCE_ID: &str = "2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc";

pub(crate) fn bounded_file(path: &Path) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    fs::File::open(path)?.take(strict_json::MAX_INPUT_BYTES as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > strict_json::MAX_INPUT_BYTES { return Err(Error::new(ErrorKind::BudgetExhausted, "local text artifact exceeds 1 MiB")); }
    Ok(bytes)
}

pub struct Store {
    pub(crate) connection: Connection,
    pub(crate) workspace: Workspace,
    pub(crate) scope: String,
}

#[derive(Debug)]
pub struct LocalClaim {
    pub(crate) attempt_id: String,
    pub(crate) task_id: String,
    pub(crate) node_id: String,
    pub(crate) graph_revision: i64,
    pub(crate) node_revision: i64,
    pub(crate) input_hash: String,
    pub(crate) owner: String,
}

impl LocalClaim {
    pub fn attempt_id(&self) -> &str { &self.attempt_id }
}

pub(crate) fn wall_clock() -> Result<i64> {
    let millis = SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|_| Error::new(ErrorKind::ClockUntrusted, "clock before epoch"))?.as_millis();
    i64::try_from(millis).map_err(|_| Error::new(ErrorKind::ClockUntrusted, "clock overflow"))
}

pub(crate) fn check_clock(transaction: &Transaction<'_>, now: i64) -> Result<()> {
    let previous: i64 = transaction.query_row("SELECT last_clock_ms FROM workspace_meta WHERE singleton=1", [], |row| row.get(0))?;
    if now < previous { return Err(Error::new(ErrorKind::ClockUntrusted, "clock moved backwards")); }
    transaction.execute("UPDATE workspace_meta SET last_clock_ms=?1 WHERE singleton=1", [now])?;
    Ok(())
}

pub(crate) fn event_replay(transaction: &Transaction<'_>, key: &str, payload_hash: &str) -> Result<Option<Value>> {
    let stored: Option<(String, String)> = transaction.query_row("SELECT payload_hash,result_json FROM events WHERE event_key=?1", [key], |row| Ok((row.get(0)?, row.get(1)?))).optional()?;
    match stored {
        Some((hash, result)) if hash == payload_hash => Ok(Some(strict_json::parse(result.as_bytes())?)),
        Some(_) => Err(Error::new(ErrorKind::EventConflict, "same event key has different payload")),
        None => Ok(None),
    }
}

pub(crate) fn event_insert(transaction: &Transaction<'_>, key: &str, task: &str, payload_hash: &str, result: &Value) -> Result<()> {
    transaction.execute("INSERT INTO events(event_key,task_id,payload_hash,result_json) VALUES(?1,?2,?3,?4)", params![key, task, payload_hash, String::from_utf8(strict_json::canonical(result)?).unwrap()])?;
    Ok(())
}

impl Store {
    pub fn open(approved_root: &Path) -> Result<Self> {
        Self::open_mode(approved_root, true)
    }

    pub fn open_existing(approved_root: &Path) -> Result<Self> {
        Self::open_mode(approved_root, false)
    }

    fn open_mode(approved_root: &Path, create: bool) -> Result<Self> {
        if rusqlite::version() != "3.53.4" {
            return Err(Error::new(ErrorKind::MigrationUnsupported, "unexpected linked SQLite version"));
        }
        let engine = Connection::open_in_memory()?;
        let source_id: String = engine.query_row("SELECT sqlite_source_id()",[],|row| row.get(0))?;
        if source_id != SQLITE_SOURCE_ID { return Err(Error::new(ErrorKind::MigrationUnsupported,"linked SQLite source identity differs from exact pin")); }
        let workspace = Workspace::open(approved_root)?;
        let internal = workspace.resolve(Path::new(".wuji4"))?;
        if !internal.exists() {
            if !create { return Err(Error::new(ErrorKind::Reference, "workspace has not been initialized")); }
            fs::create_dir(&internal)?;
        }
        let database = workspace.resolve(Path::new(".wuji4/state.sqlite"))?;
        let existed = database.exists();
        if !existed && !create { return Err(Error::new(ErrorKind::Reference, "workspace database missing")); }
        let initial_identity = if existed { None } else { Some(crate::local_identity::current()?) };
        if !existed { OpenOptions::new().write(true).create_new(true).open(&database)?; }
        let mut connection = if existed {
            Connection::open_with_flags(&database,rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?
        } else { Connection::open(&database)? };
        connection.busy_timeout(Duration::from_millis(500))?;
        connection.pragma_update(None, "foreign_keys", "ON")?;
        let application: i64 = connection.pragma_query_value(None, "application_id", |row| row.get(0))?;
        let version: i64 = connection.pragma_query_value(None, "user_version", |row| row.get(0))?;
        let root_hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
        let scope = format!("project:{}", &root_hash[..24]);
        if existed {
            if application != APPLICATION_ID || (version != SCHEMA_VERSION && !([2,3,4,5,6].contains(&version) && create)) {
                return Err(Error::new(ErrorKind::MigrationUnsupported, "unknown or newer database; no mutation"));
            }
            let stored: (String, String) = connection.query_row("SELECT scope,root_hash FROM workspace_meta WHERE singleton=1", [], |row| Ok((row.get(0)?, row.get(1)?)))?;
            if stored != (scope.clone(), root_hash.clone()) {
                return Err(Error::new(ErrorKind::ScopeDenied, "workspace identity mismatch"));
            }
            crate::local_identity::require(&connection,&workspace,&scope)?;
            if [2,3,4,5].contains(&version) {
                return Err(Error::new(ErrorKind::MigrationUnsupported,"legacy resource owner migration is not authorized; database left unchanged"));
            }
            connection = Connection::open_with_flags(&database,rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE)?;
            connection.busy_timeout(Duration::from_millis(500))?;
            connection.pragma_update(None,"foreign_keys","ON")?;
            crate::local_identity::require(&connection,&workspace,&scope)?;
            if version == 6 { Self::upgrade_artifact_history(&mut connection,&workspace,&scope)?; }
        } else {
            let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            transaction.execute_batch(include_str!("state_schema.sql"))?;
            transaction.execute_batch(include_str!("resource_schema.sql"))?;
            transaction.execute_batch(include_str!("transfer_schema.sql"))?;
            transaction.execute_batch(include_str!("task_catalog_schema.sql"))?;
            transaction.execute_batch(include_str!("received_schema.sql"))?;
            transaction.execute("INSERT INTO workspace_meta(singleton,scope,root_hash,last_clock_ms) VALUES(1,?1,?2,?3)", params![scope, root_hash, wall_clock()?])?;
            crate::local_identity::initialize(&transaction,&workspace,&scope,initial_identity.as_ref().unwrap())?;
            transaction.pragma_update(None,"user_version",SCHEMA_VERSION)?;
            transaction.commit()?;
        }
        if rusqlite::version() != "3.53.4" {
            return Err(Error::new(ErrorKind::MigrationUnsupported, "unexpected linked SQLite version"));
        }
        Ok(Self { connection, workspace, scope })
    }

    fn upgrade_artifact_history(connection: &mut Connection, workspace: &Workspace, scope: &str) -> Result<()> {
        connection.pragma_update(None,"foreign_keys","OFF")?;
        let result = (|| {
            let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let application: i64 = transaction.pragma_query_value(None,"application_id",|row|row.get(0))?;
            let version: i64 = transaction.pragma_query_value(None,"user_version",|row|row.get(0))?;
            if application != APPLICATION_ID || version != 6 {
                return Err(Error::new(ErrorKind::MigrationUnsupported,"artifact migration source changed; no mutation"));
            }
            crate::local_identity::require(&transaction,workspace,scope)?;
            let columns: String = transaction.query_row("SELECT group_concat(name,',') FROM (SELECT name FROM pragma_table_xinfo('artifacts') ORDER BY cid)",[],|row|row.get(0))?;
            let extensions: i64 = transaction.query_row("SELECT count(*) FROM sqlite_master WHERE tbl_name='artifacts' AND type IN ('index','trigger') AND sql IS NOT NULL",[],|row|row.get(0))?;
            if columns != "id,task_id,node_id,attempt_id,path,sha256,bytes,revision,producer,state" || extensions != 0 {
                return Err(Error::new(ErrorKind::MigrationUnsupported,"unexpected artifact schema extensions; no mutation"));
            }
            transaction.execute_batch(include_str!("artifact_history_migration.sql"))?;
            let violations: i64 = transaction.query_row("SELECT count(*) FROM pragma_foreign_key_check",[],|row|row.get(0))?;
            if violations != 0 {
                return Err(Error::new(ErrorKind::MigrationUnsupported,"artifact migration would leave broken references; rolled back"));
            }
            transaction.commit()?;
            Ok(())
        })();
        connection.pragma_update(None,"foreign_keys","ON")?;
        result
    }

    pub fn scope(&self) -> &str { &self.scope }

    pub fn local_role_ref(&self) -> ExactRef {
        let source = json!({"resources":strict_json::sha256(include_bytes!("resources.rs")),"resource_schema":strict_json::sha256(include_bytes!("resource_schema.sql")),"local_identity":strict_json::sha256(include_bytes!("local_identity.rs")),"store":strict_json::sha256(include_bytes!("store.rs")),"local_state":strict_json::sha256(include_bytes!("local_state.rs")),"revisions":strict_json::sha256(include_bytes!("revisions.rs")),"checkpoint":strict_json::sha256(include_bytes!("checkpoint.rs")),"policy":strict_json::sha256(include_bytes!("policy.rs")),"graph":strict_json::sha256(include_bytes!("graph.rs")),"schema":strict_json::sha256(include_bytes!("state_schema.sql")),"contracts":strict_json::sha256(include_bytes!("contracts.rs")),"contract_schema":strict_json::sha256(include_bytes!("../schemas/contracts.schema.json")),"error":strict_json::sha256(include_bytes!("error.rs")),"manifest":strict_json::sha256(include_bytes!("../Cargo.toml")),"dependency_lock":strict_json::sha256(include_bytes!("../Cargo.lock")),"strict_json":strict_json::sha256(include_bytes!("strict_json.rs"))});
        let identity = json!({"base":source,"received":strict_json::sha256(include_bytes!("received.rs")),"received_schema":strict_json::sha256(include_bytes!("received_schema.sql")),"transfers":strict_json::sha256(include_bytes!("transfers.rs")),"transfer_schema":strict_json::sha256(include_bytes!("transfer_schema.sql")),"task_catalog":strict_json::sha256(include_bytes!("task_catalog.rs")),"task_catalog_schema":strict_json::sha256(include_bytes!("task_catalog_schema.sql")),"registry":strict_json::sha256(include_bytes!("registry.rs")),"registry_schema":strict_json::sha256(include_bytes!("registry_schema.sql")),"composer":strict_json::sha256(include_bytes!("composer.rs"))});
        let identity = json!({"base":identity,"artifact_history_migration":strict_json::sha256(include_bytes!("artifact_history_migration.sql"))});
        ExactRef { id:"program/local-file-writer".into(), r#type:"file".into(), scope:self.scope.clone(), revision:1, sha256:strict_json::digest(&identity).expect("static source identity"), release:"test-local-core-1".into(), schema_version:1 }
    }

    pub fn plan(&mut self, envelope: &Value) -> Result<Value> {
        self.plan_internal(envelope, None)
    }

    pub(crate) fn plan_internal(&mut self, envelope: &Value, native: Option<&crate::native_execution::NativeDevelopmentPermit>) -> Result<Value> {
        self.plan_internal_bound(envelope,native,None)
    }

    pub(crate) fn plan_internal_bound(&mut self, envelope: &Value, native: Option<&crate::native_execution::NativeDevelopmentPermit>, catalog: Option<&crate::task_catalog::TaskCatalogBinding>) -> Result<Value> {
        let actor = ActorContext::trusted_local(&self.scope,Role::Aji);
        actor.require(&self.scope,Operation::Plan)?;
        Schemas::frozen()?.check_envelope(envelope)?;
        if envelope["contract_type"] != "WorkflowPlan" || envelope["metadata"]["authority"] != "review_proposal" || envelope["metadata"]["owner"].as_str() != Some(actor.id()) {
            return Err(Error::new(ErrorKind::AuthorityDenied, "external JSON can only propose a WorkflowPlan"));
        }
        if envelope["metadata"]["scope"].as_str() != Some(self.scope.as_str()) {
            return Err(Error::new(ErrorKind::ScopeDenied, "plan scope mismatch"));
        }
        let workflow: Workflow = serde_json::from_value(envelope["payload"].clone())?;
        if envelope["metadata"]["id"].as_str() != Some(workflow.workflow_id.as_str()) || envelope["metadata"]["revision"] != 1 {
            return Err(Error::new(ErrorKind::RevisionConflict, "initial plan identity/revision"));
        }
        let ids: Vec<_> = workflow.nodes.iter().map(|node| node.id.clone()).collect();
        graph::dependency_order(&ids, &workflow.edges)?;
        if ids.len() > 256 { return Err(Error::new(ErrorKind::BudgetExhausted, "P2 plan node cap 256")); }
        for node in &workflow.nodes {
            let local_checks = ["local.file-readable", "local.hash-current", "local.utf8"];
            if let Some(permit) = native {
                permit.check_node(&self.workspace, &self.scope, node)?;
            } else {
                if node.execution_form != ExecutionForm::Program {
                    return Err(Error::new(ErrorKind::HostUnknown, "P2 native/model role is not admitted"));
                }
                if node.role_ref != self.local_role_ref() || node.owner != "local-executor" || node.acceptance_ids.len() != local_checks.len() || local_checks.iter().any(|required| !node.acceptance_ids.iter().any(|actual| actual == required)) {
                    return Err(Error::new(ErrorKind::Reference, "local handler role/checks are exact; no arbitrary professional acceptance"));
                }
            }
            if node.revision != 1 || node.status != "planned" || node.acceptance_ids.is_empty() {
                return Err(Error::new(ErrorKind::Shape, "new node needs revision 1/planned/acceptance"));
            }
            if node.role_ref.scope != self.scope || node.role_ref.release != workflow.catalog_version || node.inputs.iter().any(|input| input.scope != self.scope || input.release != workflow.catalog_version) {
                return Err(Error::new(ErrorKind::ScopeDenied, "node reference scope/release mismatch"));
            }
            Self::check_inputs(&self.connection,&self.workspace,&self.scope,node)?;
            for path in node.read_roots.iter().chain(&node.write_roots) { self.workspace.resolve(Path::new(path))?; }
            for path in &node.write_roots { self.workspace.output(Path::new(path))?; }
        }
        let plan_hash = strict_json::object_digest(envelope)?;
        let binding_hash = catalog.map(|binding| binding.digest()).transpose()?;
        let event_hash = strict_json::digest(&json!({"plan_hash":plan_hash,"catalog_binding_hash":binding_hash}))?;
        let key = format!("plan:{}",strict_json::digest(&json!([self.scope,workflow.workflow_id]))?);
        let now = wall_clock()?;
        let duration = i64::try_from(workflow.budget.wall_ms).map_err(|_| Error::new(ErrorKind::BudgetExhausted, "deadline overflow"))?;
        let deadline = now.checked_add(duration).ok_or_else(|| Error::new(ErrorKind::BudgetExhausted, "deadline overflow"))?;
        let parallel = i64::try_from(workflow.budget.max_parallel_workers).map_err(|_| Error::new(ErrorKind::BudgetExhausted, "parallel quota overflow"))?;
        let retry_cap = i64::try_from(workflow.budget.max_extra_retries).map_err(|_| Error::new(ErrorKind::BudgetExhausted, "retry quota overflow"))?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_clock(&transaction, now)?;
        if let Some(result) = event_replay(&transaction, &key, &event_hash)? { transaction.commit()?; return Ok(result); }
        let revision_cap = i64::try_from(workflow.budget.max_point_revisions).map_err(|_| Error::new(ErrorKind::BudgetExhausted,"revision cap overflow"))?;
        transaction.execute("INSERT INTO tasks(id,scope,graph_revision,release_id,plan_hash,max_parallel,retry_cap,revision_cap,deadline_ms,status) VALUES(?1,?2,1,?3,?4,?5,?6,?7,?8,'planned')", params![workflow.workflow_id, self.scope, workflow.catalog_version, plan_hash, parallel, retry_cap, revision_cap, deadline])?;
        transaction.execute("INSERT INTO task_plans(task_id,graph_revision,plan_hash,envelope_json) VALUES(?1,1,?2,?3)",params![workflow.workflow_id,plan_hash,serde_json::to_string(envelope)?])?;
        if let Some(binding) = catalog {
            transaction.execute("UPDATE tasks SET catalog_binding_hash=?2 WHERE id=?1",params![workflow.workflow_id,binding_hash])?;
            transaction.execute("INSERT INTO task_catalog_locks VALUES(?1,?2,?3)",params![workflow.workflow_id,binding_hash,serde_json::to_string(binding)?])?;
        }
        for node in &workflow.nodes {
            let spec = serde_json::to_string(node)?;
            let input_hash = strict_json::digest(&json!({"node":node,"release":workflow.catalog_version}))?;
            let form = match node.execution_form { ExecutionForm::Program => "program", ExecutionForm::Model => "model", ExecutionForm::NativeAction => "native_action" };
            transaction.execute("INSERT INTO nodes(task_id,id,revision,owner,form,spec_json,state,input_hash) VALUES(?1,?2,1,?3,?4,?5,'planned',?6)", params![workflow.workflow_id,node.id,node.owner,form,spec,input_hash])?;
        }
        for edge in &workflow.edges {
            transaction.execute("INSERT INTO dependencies(task_id,source,target) VALUES(?1,?2,?3)", params![workflow.workflow_id,edge.from,edge.to])?;
        }
        let result = json!({"task_id":workflow.workflow_id,"graph_revision":1,"state":"planned","plan_hash":plan_hash,"native_execution":false});
        event_insert(&transaction, &key, &workflow.workflow_id, &event_hash, &result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn claim_local(&mut self, task_id: &str, node_id: &str) -> Result<LocalClaim> {
        self.refresh_local_evidence()?;
        self.claim_current(task_id,node_id)
    }

    pub(crate) fn replayed_local_claim(&self, task: &str, node: &str) -> Result<Option<LocalClaim>> {
        ActorContext::trusted_local(&self.scope,Role::Executor).require(&self.scope,Operation::Write)?;
        let found = self.connection.query_row("SELECT a.id,a.graph_revision,a.node_revision,a.input_hash,a.owner FROM attempts a JOIN tasks t ON t.id=a.task_id JOIN nodes n ON n.task_id=a.task_id AND n.id=a.node_id JOIN invocations i ON i.attempt_id=a.id JOIN slots s ON s.attempt_id=a.id WHERE a.task_id=?1 AND a.node_id=?2 AND t.scope=?3 AND a.graph_revision=t.graph_revision AND a.node_revision=n.revision AND a.input_hash=n.input_hash AND a.owner='local-executor' AND a.state IN ('produced','accepted') AND i.state='observed' AND s.host_class='test_local'",params![task,node,self.scope],|row| Ok(LocalClaim { attempt_id:row.get(0)?,task_id:task.into(),node_id:node.into(),graph_revision:row.get(1)?,node_revision:row.get(2)?,input_hash:row.get(3)?,owner:row.get(4)? })).optional()?;
        Ok(found)
    }

    fn claim_current(&mut self, task_id: &str, node_id: &str) -> Result<LocalClaim> {
        self.claim_internal(task_id, node_id, None)
    }

    pub(crate) fn claim_internal(&mut self, task_id: &str, node_id: &str, native: Option<&crate::native_execution::NativeDevelopmentPermit>) -> Result<LocalClaim> {
        ActorContext::trusted_local(&self.scope,Role::Staff).require(&self.scope,Operation::Claim)?;
        let _catalog_guard = self.hold_task_catalog(task_id)?;
        let expected_role = self.local_role_ref();
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        let task: (i64, i64, i64, i64, i64) = transaction.query_row("SELECT graph_revision,max_parallel,retry_cap,retries_used,deadline_ms FROM tasks WHERE id=?1 AND scope=?2 AND status NOT IN ('cancel_requested','cancelled','succeeded')", params![task_id,self.scope], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?)))?;
        if now >= task.4 { return Err(Error::new(ErrorKind::LeaseExpired, "task deadline passed")); }
        let node: (i64,String,String,String,String,String,i64) = transaction.query_row("SELECT revision,owner,form,state,input_hash,spec_json,attempts_used FROM nodes WHERE task_id=?1 AND id=?2", params![task_id,node_id], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?,row.get(6)?)))?;
        if native.is_none() {
            if node.2 != "program" { return Err(Error::new(ErrorKind::HostUnknown, "native model/tool observation and fee precondition are unknown")); }
            if node.1 != "local-executor" { return Err(Error::new(ErrorKind::AuthorityDenied, "local driver cannot impersonate assigned owner")); }
        }
        if node.3 == "blocked" { return Err(Error::new(ErrorKind::ValidationStale,"node blocked; reconcile evidence and revise before claiming")); }
        if !["planned","ready","failed"].contains(&node.3.as_str()) { return Err(Error::new(ErrorKind::RevisionConflict, "node not claimable")); }
        let reviewing = native.is_some() && node.1 == "native-validation";
        let pending: i64 = transaction.query_row("SELECT count(*) FROM dependencies d JOIN nodes n ON n.task_id=d.task_id AND n.id=d.source WHERE d.task_id=?1 AND d.target=?2 AND n.state<>'succeeded' AND NOT(?3 AND n.state='produced' AND n.form='model' AND n.owner='native-engineering')", params![task_id,node_id,reviewing], |row| row.get(0))?;
        if pending != 0 { return Err(Error::new(ErrorKind::DependencyNotAccepted, "upstream not accepted")); }
        let mut dependency_artifacts = transaction.prepare("SELECT a.path,a.sha256 FROM dependencies d JOIN artifacts a ON a.task_id=d.task_id AND a.node_id=d.source WHERE d.task_id=?1 AND d.target=?2 AND (a.state='adopted' OR (?3 AND a.state='produced'))")?;
        let adopted: Vec<(String,String)> = dependency_artifacts.query_map(params![task_id,node_id,reviewing], |row| Ok((row.get(0)?,row.get(1)?)))?.collect::<std::result::Result<_,_>>()?;
        drop(dependency_artifacts);
        for (path, hash) in adopted {
            if strict_json::sha256(&bounded_file(&self.workspace.resolve(Path::new(&path))?)?) != hash {
                return Err(Error::new(ErrorKind::ValidationStale, "adopted dependency file changed"));
            }
        }
        if node.6 > 0 && task.3 >= task.2 { return Err(Error::new(ErrorKind::BudgetExhausted, "task retry cap")); }
        let open_slots: i64 = transaction.query_row("SELECT count(*) FROM slots s JOIN attempts a ON a.id=s.attempt_id WHERE a.task_id=?1 AND s.state<>'closed'", [task_id], |row| row.get(0))?;
        if open_slots >= task.1 { return Err(Error::new(ErrorKind::BudgetExhausted, "local slot cap")); }
        let workspace_slots: i64 = transaction.query_row("SELECT count(*) FROM slots WHERE state<>'closed'", [], |row| row.get(0))?;
        if workspace_slots >= 2 { return Err(Error::new(ErrorKind::BudgetExhausted, "P2 local workload policy cap 2; not a native quota")); }
        let proposed: Node = serde_json::from_str(&node.5)?;
        if let Some(permit) = native {
            permit.check_node(&self.workspace, &self.scope, &proposed)?;
        } else if proposed.role_ref != expected_role {
            return Err(Error::new(ErrorKind::Reference, "local implementation binding changed; no latest fallback"));
        }
        let mut active = transaction.prepare("SELECT a.spec_json FROM attempts a JOIN slots s ON s.attempt_id=a.id WHERE s.state<>'closed'")?;
        let active_specs: Vec<String> = active.query_map([], |row| row.get(0))?.collect::<std::result::Result<_,_>>()?;
        drop(active);
        for spec in active_specs {
            let other: Node = serde_json::from_str(&spec)?;
            for write in &proposed.write_roots {
                let path = self.workspace.resolve(Path::new(write))?;
                for conflicting in other.read_roots.iter().chain(&other.write_roots) {
                    if Workspace::conflicts(&path, &self.workspace.resolve(Path::new(conflicting))?) { return Err(Error::new(ErrorKind::OwnerConflict, "active read/write intersection")); }
                }
            }
            for read in &proposed.read_roots {
                let path = self.workspace.resolve(Path::new(read))?;
                for write in &other.write_roots {
                    if Workspace::conflicts(&path, &self.workspace.resolve(Path::new(write))?) { return Err(Error::new(ErrorKind::OwnerConflict, "active write/read intersection")); }
                }
            }
        }
        let attempt_id = strict_json::digest(&json!({"scope":self.scope,"task":task_id,"node":node_id,"graph_revision":task.0,"node_revision":node.0,"ordinal":node.6+1,"input_hash":node.4}))?;
        let duration = if native.is_some() { 300_000 } else { 30_000 };
        let expires = now.checked_add(duration).ok_or_else(|| Error::new(ErrorKind::LeaseExpired, "lease overflow"))?.min(task.4);
        Self::check_inputs(&transaction,&self.workspace,&self.scope,&proposed)?;
        transaction.execute("INSERT INTO attempts(id,task_id,node_id,graph_revision,node_revision,input_hash,owner,state,spec_json) VALUES(?1,?2,?3,?4,?5,?6,?7,'claimed',?8)", params![attempt_id,task_id,node_id,task.0,node.0,node.4,node.1,node.5])?;
        transaction.execute("INSERT INTO leases(attempt_id,owner,expires_ms,state) VALUES(?1,?2,?3,'active')", params![attempt_id,node.1,expires])?;
        let host = if native.is_some() { "codex_native" } else { "test_local" };
        transaction.execute("INSERT INTO slots(attempt_id,host_class,state) VALUES(?1,?2,'reserved')", params![attempt_id,host])?;
        transaction.execute("INSERT INTO invocations(attempt_id,request_key,state,effect_class) VALUES(?1,?1,'intent','project_write')", [&attempt_id])?;
        transaction.execute("UPDATE nodes SET state='claimed',attempts_used=attempts_used+1 WHERE task_id=?1 AND id=?2", params![task_id,node_id])?;
        if node.6 > 0 { transaction.execute("UPDATE tasks SET retries_used=retries_used+1 WHERE id=?1", [task_id])?; }
        transaction.execute("UPDATE tasks SET status='active' WHERE id=?1", [task_id])?;
        transaction.commit()?;
        Ok(LocalClaim { attempt_id, task_id:task_id.into(), node_id:node_id.into(), graph_revision:task.0, node_revision:node.0, input_hash:node.4, owner:node.1 })
    }

    pub(crate) fn current_binding(transaction: &Transaction<'_>, claim: &LocalClaim) -> Result<(i64,String,String)> {
        let state: (i64,i64,String,String,i64,String,String,String) = transaction.query_row("SELECT t.graph_revision,n.revision,n.input_hash,a.owner,l.expires_ms,l.state,a.state,t.status FROM attempts a JOIN tasks t ON t.id=a.task_id JOIN nodes n ON n.task_id=a.task_id AND n.id=a.node_id JOIN leases l ON l.attempt_id=a.id WHERE a.id=?1", [&claim.attempt_id], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?,row.get(6)?,row.get(7)?)))?;
        if state.0 != claim.graph_revision || state.1 != claim.node_revision || state.2 != claim.input_hash || state.3 != claim.owner || ["superseded","expired","failed"].contains(&state.6.as_str()) || ["cancel_requested","cancelled"].contains(&state.7.as_str()) {
            return Err(Error::new(ErrorKind::StaleReceipt, "claim revision/input/owner no longer current"));
        }
        Ok((state.4,state.5,state.6))
    }

    pub(crate) fn current_claim(transaction: &Transaction<'_>, claim: &LocalClaim, now: i64) -> Result<()> {
        let state = Self::current_binding(transaction, claim)?;
        if state.1 != "active" || now >= state.0 { return Err(Error::new(ErrorKind::LeaseExpired, "claim lease inactive or expired")); }
        Ok(())
    }

    fn begin_local_dispatch(&mut self, claim: &LocalClaim, target: &Path, content: &[u8]) -> Result<Node> {
        self.refresh_local_evidence()?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        Self::current_claim(&transaction, claim, now)?;
        let state: String = transaction.query_row("SELECT state FROM invocations WHERE attempt_id=?1", [&claim.attempt_id], |row| row.get(0))?;
        if state != "intent" { return Err(Error::new(ErrorKind::UnknownSubmission, "dispatch already attempted; query required")); }
        let spec: String = transaction.query_row("SELECT spec_json FROM nodes WHERE task_id=?1 AND id=?2", params![claim.task_id,claim.node_id], |row| row.get(0))?;
        Self::check_inputs(&transaction,&self.workspace,&self.scope,&serde_json::from_str::<Node>(&spec)?)?;
        transaction.execute("UPDATE invocations SET state='dispatching',expected_output_path=?2,expected_output_hash=?3,expected_output_bytes=?4 WHERE attempt_id=?1", params![claim.attempt_id,target.to_string_lossy(),strict_json::sha256(content),content.len() as i64])?;
        transaction.execute("UPDATE attempts SET state='dispatched' WHERE id=?1", [&claim.attempt_id])?;
        transaction.execute("UPDATE slots SET state='open' WHERE attempt_id=?1", [&claim.attempt_id])?;
        transaction.execute("UPDATE nodes SET state='running' WHERE task_id=?1 AND id=?2", params![claim.task_id,claim.node_id])?;
        transaction.commit()?;
        Ok(serde_json::from_str(&spec)?)
    }

    pub fn write_local_file(&mut self, claim: &LocalClaim, output: &Path, bytes: &[u8]) -> Result<Value> {
        let actor = ActorContext::trusted_local(&self.scope,Role::Executor);
        actor.require(&self.scope,Operation::Write)?;
        if claim.owner != actor.id() { return Err(Error::new(ErrorKind::AuthorityDenied,"claim is not owned by local handler")); }
        if bytes.len() > strict_json::MAX_INPUT_BYTES || std::str::from_utf8(bytes).is_err() { return Err(Error::new(ErrorKind::Shape, "local text handler requires <=1 MiB UTF-8")); }
        let target = self.workspace.output(output)?;
        let spec_json: String = self.connection.query_row("SELECT spec_json FROM nodes WHERE task_id=?1 AND id=?2", params![claim.task_id,claim.node_id], |row| row.get(0))?;
        let spec: Node = serde_json::from_str(&spec_json)?;
        if !spec.write_roots.iter().any(|root| self.workspace.resolve(Path::new(root)).is_ok_and(|allowed| target.starts_with(allowed))) {
            return Err(Error::new(ErrorKind::PathDenied, "output is not in assigned write set"));
        }
        self.refresh_local_evidence()?;
        let candidate = json!({"attempt_id":claim.attempt_id,"host_class":"test_local","path":target,"sha256":strict_json::sha256(bytes),"bytes":bytes.len(),"state":"produced","native_execution":false});
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_clock(&transaction,wall_clock()?)?;
        Self::current_binding(&transaction,claim)?;
        if let Some(replayed) = event_replay(&transaction,&format!("produced:{}",claim.attempt_id),&strict_json::digest(&candidate)?)? {
            if bounded_file(&self.workspace.resolve(output)?)? != bytes { return Err(Error::new(ErrorKind::ValidationStale,"idempotent receipt cannot adopt changed file")); }
            transaction.commit()?;
            return Ok(replayed);
        }
        transaction.commit()?;
        let _catalog_guard = self.hold_task_catalog(&claim.task_id)?;
        self.begin_local_dispatch(claim, &target, bytes)?;
        let mut file = OpenOptions::new().write(true).create_new(true).open(&target)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        let current_path = self.workspace.resolve(output)?;
        let actual = bounded_file(&current_path)?;
        if current_path != target || actual.as_slice() != bytes { return Err(Error::new(ErrorKind::ValidationStale, "written artifact does not match locked output intent")); }
        let hash = strict_json::sha256(&actual);
        let result = json!({"attempt_id":claim.attempt_id,"host_class":"test_local","path":current_path,"sha256":hash,"bytes":actual.len(),"state":"produced","native_execution":false});
        let payload_hash = strict_json::digest(&result)?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        Self::current_claim(&transaction, claim, now)?;
        let key = format!("produced:{}",claim.attempt_id);
        if let Some(replayed) = event_replay(&transaction, &key, &payload_hash)? { transaction.commit()?; return Ok(replayed); }
        transaction.execute("INSERT INTO artifacts(id,task_id,node_id,attempt_id,path,sha256,bytes,revision,producer,state) VALUES(?1,?2,?3,?1,?4,?5,?6,1,?7,'produced')", params![claim.attempt_id,claim.task_id,claim.node_id,current_path.to_string_lossy(),hash,actual.len() as i64,claim.owner])?;
        transaction.execute("UPDATE invocations SET state='observed',result_hash=?2 WHERE attempt_id=?1", params![claim.attempt_id,hash])?;
        transaction.execute("UPDATE attempts SET state='produced' WHERE id=?1", [&claim.attempt_id])?;
        transaction.execute("UPDATE slots SET state='completed_open' WHERE attempt_id=?1", [&claim.attempt_id])?;
        transaction.execute("UPDATE nodes SET state='produced' WHERE task_id=?1 AND id=?2", params![claim.task_id,claim.node_id])?;
        event_insert(&transaction,&key,&claim.task_id,&payload_hash,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn verify_local_file(&mut self, claim: &LocalClaim) -> Result<Value> {
        self.refresh_local_evidence()?;
        let actor = ActorContext::trusted_local(&self.scope,Role::Verifier);
        actor.require(&self.scope,Operation::Verify)?;
        let stored: Option<(String,String,String)> = self.connection.query_row("SELECT path,sha256,producer FROM artifacts WHERE attempt_id=?1 AND state IN ('produced','validated','adopted')", [&claim.attempt_id], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
        let (path, expected_hash, producer) = stored.ok_or_else(|| Error::new(ErrorKind::ValidationStale,"no current artifact remains for this attempt"))?;
        let validator = actor.id();
        if producer == validator { return Err(Error::new(ErrorKind::SelfReview, "producer cannot accept own output")); }
        let actual_path = self.workspace.resolve(Path::new(&path))?;
        let actual = bounded_file(&actual_path)?;
        if strict_json::sha256(&actual) != expected_hash || std::str::from_utf8(&actual).is_err() {
            return Err(Error::new(ErrorKind::ValidationStale, "artifact changed or UTF-8 invalid"));
        }
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        Self::current_binding(&transaction, claim)?;
        if strict_json::sha256(&bounded_file(&self.workspace.resolve(Path::new(&path))?)?) != expected_hash {
            return Err(Error::new(ErrorKind::ValidationStale, "artifact changed before commit"));
        }
        let spec_json: String = transaction.query_row("SELECT spec_json FROM nodes WHERE task_id=?1 AND id=?2", params![claim.task_id,claim.node_id], |row| row.get(0))?;
        let spec: Node = serde_json::from_str(&spec_json)?;
        Self::check_inputs(&transaction,&self.workspace,&self.scope,&spec)?;
        let result = json!({"attempt_id":claim.attempt_id,"artifact_hash":expected_hash,"validator":validator,"checks":["actual-file","current-hash","utf8","independent-validator"],"state":"succeeded","host_class":"test_local","professional_or_native_verified":false});
        let payload_hash = strict_json::digest(&result)?;
        let key = format!("verify:{}",claim.attempt_id);
        if let Some(replayed) = event_replay(&transaction,&key,&payload_hash)? { transaction.commit()?; return Ok(replayed); }
        Self::current_claim(&transaction, claim, now)?;
        transaction.execute("INSERT INTO validations(id,artifact_id,artifact_hash,graph_revision,validator,requirement_ids_json,verdict) VALUES(?1,?1,?2,?3,?4,?5,'pass')", params![claim.attempt_id,expected_hash,claim.graph_revision,validator,serde_json::to_string(&spec.acceptance_ids)?])?;
        for requirement in &spec.acceptance_ids {
            transaction.execute("INSERT INTO acceptance_links(task_id,node_id,requirement_id,validation_id) VALUES(?1,?2,?3,?4)", params![claim.task_id,claim.node_id,requirement,claim.attempt_id])?;
        }
        transaction.execute("UPDATE artifacts SET state='adopted' WHERE attempt_id=?1", [&claim.attempt_id])?;
        transaction.execute("UPDATE attempts SET state='accepted' WHERE id=?1", [&claim.attempt_id])?;
        transaction.execute("UPDATE nodes SET state='succeeded' WHERE task_id=?1 AND id=?2", params![claim.task_id,claim.node_id])?;
        event_insert(&transaction,&key,&claim.task_id,&payload_hash,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn close_local_handler(&mut self, claim: &LocalClaim) -> Result<()> {
        self.refresh_local_evidence()?;
        ActorContext::trusted_local(&self.scope,Role::Executor).require(&self.scope,Operation::Close)?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let invocation: String = transaction.query_row("SELECT state FROM invocations WHERE attempt_id=?1", [&claim.attempt_id], |row| row.get(0))?;
        if !["observed","intent"].contains(&invocation.as_str()) { return Err(Error::new(ErrorKind::UnknownSubmission, "unknown local handler cannot be declared closed")); }
        let evidence = if invocation == "intent" { "trusted-local-never-dispatched" } else { "trusted-test-local-synchronous-handler-returned" };
        transaction.execute("UPDATE slots SET state='closed',close_evidence=?2 WHERE attempt_id=?1 AND host_class='test_local'", params![claim.attempt_id,evidence])?;
        if invocation == "intent" {
            transaction.execute("UPDATE attempts SET state='failed' WHERE id=?1 AND state='claimed'",[&claim.attempt_id])?;
            transaction.execute("UPDATE nodes SET state='failed' WHERE task_id=?1 AND id=?2 AND state='claimed'",params![claim.task_id,claim.node_id])?;
        }
        transaction.execute("UPDATE leases SET state='ended' WHERE attempt_id=?1", [&claim.attempt_id])?;
        Self::finalize_local_task(&transaction,&claim.task_id)?;
        transaction.commit()?;
        Ok(())
    }


    pub fn cancel_local_task(&mut self, task_id: &str, expected_graph_revision: i64) -> Result<Value> {
        ActorContext::trusted_local(&self.scope,Role::Aji).require(&self.scope,Operation::Cancel)?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_clock(&transaction,wall_clock()?)?;
        let current: i64 = transaction.query_row("SELECT graph_revision FROM tasks WHERE id=?1 AND scope=?2",params![task_id,self.scope],|row| row.get(0))?;
        if current != expected_graph_revision { return Err(Error::new(ErrorKind::RevisionConflict,"cancel graph revision is stale")); }
        let payload_hash = strict_json::digest(&json!({"task":task_id,"scope":self.scope,"graph_revision":current,"operation":"cancel-local"}))?;
        let key = format!("cancel:{payload_hash}");
        if let Some(result) = event_replay(&transaction,&key,&payload_hash)? { transaction.commit()?; return Ok(result); }
        transaction.execute("UPDATE slots SET state='closed',close_evidence='trusted-local-never-dispatched' WHERE host_class='test_local' AND attempt_id IN (SELECT a.id FROM attempts a JOIN invocations i ON i.attempt_id=a.id WHERE a.task_id=?1 AND i.state='intent')",[task_id])?;
        transaction.execute("UPDATE slots SET state='closed',close_evidence='trusted-local-observed-synchronous-handler-returned' WHERE host_class='test_local' AND attempt_id IN (SELECT a.id FROM attempts a JOIN invocations i ON i.attempt_id=a.id WHERE a.task_id=?1 AND i.state='observed')",[task_id])?;
        transaction.execute("UPDATE leases SET state='ended' WHERE attempt_id IN (SELECT a.id FROM attempts a JOIN slots s ON s.attempt_id=a.id WHERE a.task_id=?1 AND s.state='closed')",[task_id])?;
        let open: i64 = transaction.query_row("SELECT count(*) FROM attempts a JOIN slots s ON s.attempt_id=a.id WHERE a.task_id=?1 AND s.state<>'closed'",[task_id],|row| row.get(0))?;
        let state = if open == 0 { "cancelled" } else { "cancel_requested" };
        transaction.execute("UPDATE tasks SET status=?2 WHERE id=?1",params![task_id,state])?;
        transaction.execute("UPDATE nodes SET state=?2 WHERE task_id=?1 AND state<>'succeeded'",params![task_id,state])?;
        let result = json!({"task_id":task_id,"graph_revision":current,"state":state,"open_slots":open,"files_deleted":0,"native_closed":false});
        event_insert(&transaction,&key,task_id,&payload_hash,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn recover(&mut self) -> Result<Value> {
        self.refresh_local_evidence()?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_clock(&transaction,wall_clock()?)?;
        let changed = transaction.execute("UPDATE invocations SET state='unknown' WHERE state='dispatching'", [])?;
        transaction.execute("UPDATE attempts SET state='unknown' WHERE state<>'superseded' AND id IN (SELECT attempt_id FROM invocations WHERE state='unknown')", [])?;
        transaction.execute("UPDATE slots SET state='release_unverified' WHERE attempt_id IN (SELECT attempt_id FROM invocations WHERE state='unknown') AND state<>'closed'", [])?;
        transaction.execute("UPDATE nodes SET state='blocked' WHERE state NOT IN ('cancel_requested','cancelled') AND (task_id,id) IN (SELECT task_id,node_id FROM attempts WHERE state='unknown')", [])?;
        transaction.commit()?;
        Ok(json!({"new_unknown_invocations":changed,"action":"query-required-no-redispatch","native_verified":false}))
    }

    pub fn status(&self) -> Result<Value> {
        let slots: i64 = self.connection.query_row("SELECT count(*) FROM slots WHERE state<>'closed'", [], |row| row.get(0))?;
        let unknown: i64 = self.connection.query_row("SELECT count(*) FROM invocations WHERE state='unknown'", [], |row| row.get(0))?;
        let tasks: i64 = self.connection.query_row("SELECT count(*) FROM tasks", [], |row| row.get(0))?;
        Ok(json!({"scope":self.scope,"sqlite_version":rusqlite::version(),"schema_version":SCHEMA_VERSION,"tasks":tasks,"open_slots":slots,"unknown_invocations":unknown,"admitted_local_program_ref":self.local_role_ref(),"host_class":"test_local","effective_model":"unknown","effective_effort":"unknown","effective_native_quota":"unknown","native_verified":false}))
    }

    pub fn task_status(&self, task: &str) -> Result<Value> {
        let row: Option<(i64,String,String,i64,i64,i64,i64,i64)> = self.connection.query_row("SELECT graph_revision,plan_hash,status,retry_cap,retries_used,revision_cap,revisions_used,deadline_ms FROM tasks WHERE id=?1 AND scope=?2",params![task,self.scope],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?,row.get(6)?,row.get(7)?))).optional()?;
        let (revision,hash,state,retry_cap,retries,revision_cap,revisions,deadline) = row.ok_or_else(|| Error::new(ErrorKind::Reference,"task is not in current scope"))?;
        Ok(json!({"task_id":task,"scope":self.scope,"graph_revision":revision,"plan_hash":hash,"state":state,"retry_cap":retry_cap,"retries_used":retries,"revision_cap":revision_cap,"revisions_used":revisions,"deadline_ms":deadline,"host_class":"test_local","native_verified":false}))
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);
    include!("store_product_tests.rs");

    fn workspace(label: &str) -> PathBuf {
        let sequence = SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/core-test-workspaces").join(format!("{label}-{}-{now}-{sequence}",std::process::id()));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn rehash(envelope: &mut Value) {
        envelope["metadata"]["content_hash"] = json!(strict_json::object_digest(envelope).unwrap());
    }

    fn plan(store: &Store, task: &str, names: &[(&str,&str)], dependencies: &[(&str,&str)], parallel: u64) -> Value {
        let nodes: Vec<Value> = names.iter().map(|(id, path)| json!({"id":id,"role_ref":store.local_role_ref(),"owner":"local-executor","revision":1,"inputs":[],"read_roots":[],"write_roots":[path],"acceptance_ids":["local.file-readable","local.hash-current","local.utf8"],"status":"planned","execution_form":"program"})).collect();
        let edges: Vec<Value> = dependencies.iter().map(|(source,target)| json!({"from":source,"to":target,"predicate":"depends-on"})).collect();
        let mut envelope = json!({
            "schema_version":1,"contract_type":"WorkflowPlan",
            "payload":{"workflow_id":task,"version":"1","catalog_version":"test-local-core-1","nodes":nodes,"edges":edges,"budget":{"max_candidates":8,"max_query_objects":20,"max_hops":3,"target_contract_bytes":1024,"target_evidence_bytes":1024,"hard_bytes_limit":null,"measured_tokens":null,"effective_token_limit":null,"wall_ms":60000,"max_parallel_workers":parallel,"max_extra_retries":6,"max_point_revisions":2,"max_no_progress":2}},
            "metadata":{"id":task,"type":"WorkflowPlan","scope":store.scope(),"schema_version":1,"revision":1,"owner":"aji-local","authority":"review_proposal","status":"proposal","source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,"updated_at_utc_ms":1,"valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]}
        });
        rehash(&mut envelope);
        envelope
    }

    fn count(store: &Store, table: &str) -> i64 {
        store.connection.query_row(&format!("SELECT count(*) FROM {table}"), [], |row| row.get(0)).unwrap()
    }

    #[test]
    fn actual_file_validation_and_close_are_separate() {
        let root = workspace("actual-file");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        let receipt = store.write_local_file(&claim,Path::new("result.txt"),"实际本地文件".as_bytes()).unwrap();
        assert_eq!(receipt["host_class"],"test_local");
        assert_eq!(fs::read(root.join("result.txt")).unwrap(),"实际本地文件".as_bytes());
        assert_eq!(store.status().unwrap()["open_slots"],1);
        let verification = store.verify_local_file(&claim).unwrap();
        assert_eq!(store.verify_local_file(&claim).unwrap(),verification);
        assert_eq!(store.status().unwrap()["open_slots"],1);
        assert_eq!(count(&store,"acceptance_links"),3);
        store.close_local_handler(&claim).unwrap();
        assert_eq!(store.status().unwrap()["open_slots"],0);
        assert_eq!(store.verify_local_file(&claim).unwrap(),verification);
        assert!(!store.status().unwrap()["native_verified"].as_bool().unwrap());
    }

    #[test]
    fn plan_replay_and_changed_payload_conflict() {
        let root = workspace("idempotency");
        let mut store = Store::open(&root).unwrap();
        let mut blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        let result = store.plan(&blueprint).unwrap();
        assert_eq!(store.plan(&blueprint).unwrap(),result);
        assert_eq!(count(&store,"tasks"),1);
        blueprint["payload"]["budget"]["wall_ms"] = json!(60001);
        rehash(&mut blueprint);
        assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::EventConflict);
        assert_eq!(count(&store,"tasks"),1);
    }

    #[test]
    fn cycle_rolls_back_plan() {
        let root = workspace("cycle");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt")],&[("first","second"),("second","first")],2);
        assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::DependencyCycle);
        assert_eq!(count(&store,"tasks"),0);
        assert_eq!(count(&store,"nodes"),0);
    }

    #[test]
    fn prerequisite_blocks_until_independent_acceptance() {
        let root = workspace("dependency");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt")],&[("first","second")],2);
        store.plan(&blueprint).unwrap();
        assert_eq!(store.claim_local("task","second").unwrap_err().kind,ErrorKind::DependencyNotAccepted);
        assert_eq!(count(&store,"slots"),0);
        let first = store.claim_local("task","first").unwrap();
        store.write_local_file(&first,Path::new("first.txt"),b"first").unwrap();
        assert_eq!(store.claim_local("task","second").unwrap_err().kind,ErrorKind::DependencyNotAccepted);
        store.verify_local_file(&first).unwrap();
        store.close_local_handler(&first).unwrap();
        store.claim_local("task","second").unwrap();
    }

    #[test]
    fn changed_adopted_upstream_never_unlocks_downstream() {
        let root = workspace("stale-upstream");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt")],&[("first","second")],2);
        store.plan(&blueprint).unwrap();
        let first = store.claim_local("task","first").unwrap();
        store.write_local_file(&first,Path::new("first.txt"),b"first").unwrap();
        store.verify_local_file(&first).unwrap();
        store.close_local_handler(&first).unwrap();
        fs::write(root.join("first.txt"),b"changed").unwrap();
        assert_eq!(store.claim_local("task","second").unwrap_err().kind,ErrorKind::ValidationStale);
        assert_eq!(count(&store,"attempts"),1);
    }

    #[test]
    fn two_handles_cannot_claim_same_node() {
        let root = workspace("cas");
        let mut first = Store::open(&root).unwrap();
        let blueprint = plan(&first,"task",&[("write","result.txt")],&[],2);
        first.plan(&blueprint).unwrap();
        let mut second = Store::open_existing(&root).unwrap();
        first.claim_local("task","write").unwrap();
        assert_eq!(second.claim_local("task","write").unwrap_err().kind,ErrorKind::RevisionConflict);
        assert_eq!(count(&second,"attempts"),1);
        assert_eq!(count(&second,"slots"),1);
    }

    #[test]
    fn independent_file_reservations_do_not_conflict() {
        let root = workspace("independent");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt")],&[],2);
        store.plan(&blueprint).unwrap();
        let first = store.claim_local("task","first").unwrap();
        let second = store.claim_local("task","second").unwrap();
        assert_eq!(store.status().unwrap()["open_slots"],2);
        store.write_local_file(&first,Path::new("first.txt"),b"first").unwrap();
        store.write_local_file(&second,Path::new("second.txt"),b"second").unwrap();
        store.verify_local_file(&first).unwrap();
        store.verify_local_file(&second).unwrap();
        assert_eq!(count(&store,"validations"),2);
        assert_eq!(store.status().unwrap()["open_slots"],2);
    }

    #[test]
    fn conflicting_writes_have_no_second_attempt() {
        let root = workspace("conflict");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("first","same.txt"),("second","same.txt")],&[],2);
        store.plan(&blueprint).unwrap();
        store.claim_local("task","first").unwrap();
        assert_eq!(store.claim_local("task","second").unwrap_err().kind,ErrorKind::OwnerConflict);
        assert_eq!(count(&store,"attempts"),1);
    }

    #[test]
    fn cross_task_write_conflicts_share_workspace() {
        let root = workspace("cross-task");
        let mut store = Store::open(&root).unwrap();
        let first = plan(&store,"one",&[("write","same.txt")],&[],2);
        let second = plan(&store,"two",&[("write","same.txt")],&[],2);
        store.plan(&first).unwrap();
        store.plan(&second).unwrap();
        store.claim_local("one","write").unwrap();
        assert_eq!(store.claim_local("two","write").unwrap_err().kind,ErrorKind::OwnerConflict);
        assert_eq!(count(&store,"attempts"),1);
    }

    #[test]
    fn changed_output_invalidates_validation() {
        let root = workspace("changed-output");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        store.write_local_file(&claim,Path::new("result.txt"),b"original").unwrap();
        fs::write(root.join("result.txt"),b"changed").unwrap();
        assert_eq!(store.verify_local_file(&claim).unwrap_err().kind,ErrorKind::ValidationStale);
        assert_eq!(count(&store,"acceptance_links"),0);
    }

    #[test]
    fn expired_lease_does_not_write_or_release_slot() {
        let root = workspace("expired");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        store.connection.execute("UPDATE leases SET expires_ms=0",[]).unwrap();
        assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"not-written").unwrap_err().kind,ErrorKind::LeaseExpired);
        assert!(!root.join("result.txt").exists());
        assert_eq!(store.status().unwrap()["open_slots"],1);
    }

    #[test]
    fn late_revision_cannot_write() {
        let root = workspace("late");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        store.connection.execute("UPDATE tasks SET graph_revision=2",[]).unwrap();
        assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"late").unwrap_err().kind,ErrorKind::StaleReceipt);
        assert!(!root.join("result.txt").exists());
        assert_eq!(store.status().unwrap()["open_slots"],1);
    }

    #[test]
    fn crash_after_intent_dispatch_recovers_unknown_without_release() {
        let root = workspace("recovery");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        store.begin_local_dispatch(&claim,&root.join("result.txt"),b"expected").unwrap();
        drop(store);
        let mut reopened = Store::open_existing(&root).unwrap();
        assert_eq!(reopened.recover().unwrap()["new_unknown_invocations"],1);
        assert_eq!(reopened.status().unwrap()["open_slots"],1);
        assert_eq!(reopened.status().unwrap()["unknown_invocations"],1);
        assert_eq!(reopened.close_local_handler(&claim).unwrap_err().kind,ErrorKind::UnknownSubmission);
        assert!(reopened.claim_local("task","write").is_err());
        let expected: String = reopened.connection.query_row("SELECT expected_output_path FROM invocations",[],|row| row.get(0)).unwrap();
        assert_eq!(Path::new(&expected),root.join("result.txt"));
        assert!(!root.join("result.txt").exists());
    }

    #[test]
    fn unknown_database_is_not_migrated_or_overwritten() {
        let root = workspace("foreign-db");
        fs::create_dir(root.join(".wuji4")).unwrap();
        let database = root.join(".wuji4/state.sqlite");
        let connection = Connection::open(&database).unwrap();
        connection.execute_batch("CREATE TABLE user_data(value TEXT); INSERT INTO user_data VALUES('preserve')").unwrap();
        drop(connection);
        let before = strict_json::sha256(&fs::read(&database).unwrap());
        assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
        assert_eq!(before,strict_json::sha256(&fs::read(&database).unwrap()));
    }

    #[test]
    fn read_only_open_does_not_initialize() {
        let root = workspace("read-only");
        assert!(Store::open_existing(&root).is_err());
        assert!(!root.join(".wuji4").exists());
    }

    #[test]
    fn user_authority_json_does_not_grant_permission() {
        let root = workspace("authority");
        let mut store = Store::open(&root).unwrap();
        let mut blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        blueprint["metadata"]["authority"] = json!("user_explicit");
        rehash(&mut blueprint);
        assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::AuthorityDenied);
        assert_eq!(count(&store,"tasks"),0);
    }

    #[test]
    fn arbitrary_acceptance_and_role_are_not_admitted() {
        let root = workspace("local-boundary");
        let mut store = Store::open(&root).unwrap();
        let mut blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        blueprint["payload"]["nodes"][0]["acceptance_ids"] = json!(["all-ComfyUI-behavior-correct"]);
        rehash(&mut blueprint);
        assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::Reference);
        blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        blueprint["payload"]["nodes"][0]["role_ref"]["sha256"] = json!("0".repeat(64));
        rehash(&mut blueprint);
        assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::Reference);
    }

    #[test]
    fn native_model_unknown_is_not_a_program_success() {
        let root = workspace("native-boundary");
        let mut store = Store::open(&root).unwrap();
        let mut blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        blueprint["payload"]["nodes"][0]["execution_form"] = json!("model");
        rehash(&mut blueprint);
        assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::HostUnknown);
        assert_eq!(count(&store,"tasks"),0);
    }

    #[test]
    fn parent_path_and_unassigned_output_rejected() {
        let root = workspace("path-boundary");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","../outside.txt")],&[],1);
        assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::PathDenied);
        let blueprint = plan(&store,"task",&[("write","assigned.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        assert_eq!(store.write_local_file(&claim,Path::new("unassigned.txt"),b"bad").unwrap_err().kind,ErrorKind::PathDenied);
        assert!(!root.join("unassigned.txt").exists());
    }

    #[test]
    fn clock_backwards_rolls_back_claim() {
        let root = workspace("clock");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let future = wall_clock().unwrap()+60000;
        store.connection.execute("UPDATE workspace_meta SET last_clock_ms=?1",[future]).unwrap();
        assert_eq!(store.claim_local("task","write").unwrap_err().kind,ErrorKind::ClockUntrusted);
        assert_eq!(count(&store,"attempts"),0);
    }

    #[test]
    fn self_review_is_rejected() {
        let root = workspace("self-review");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        store.write_local_file(&claim,Path::new("result.txt"),b"text").unwrap();
        store.connection.execute("UPDATE artifacts SET producer='local-file-validator'",[]).unwrap();
        assert_eq!(store.verify_local_file(&claim).unwrap_err().kind,ErrorKind::SelfReview);
        assert_eq!(count(&store,"validations"),0);
    }

    #[test]
    fn reserved_control_directory_is_not_an_output_scope() {
        let root = workspace("reserved-output");
        let mut store = Store::open(&root).unwrap();
        for target in [".wuji4/state.sqlite-journal", ".git/hooks/post-checkout", ".codex/config.toml"] {
            let blueprint = plan(&store,"task",&[("write",target)],&[],1);
            assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::PathDenied);
        }
        assert_eq!(count(&store,"tasks"),0);
    }

    #[test]
    fn linked_engine_source_id_is_pinned() {
        let root = workspace("sqlite-source");
        let store = Store::open(&root).unwrap();
        let source: String = store.connection.query_row("SELECT sqlite_source_id()",[],|row| row.get(0)).unwrap();
        assert_eq!(source,"2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc");
    }

    #[test]
    fn cancel_before_dispatch_has_trusted_local_no_action_proof() {
        let root = workspace("cancel-prepared");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        let result = store.cancel_local_task("task",1).unwrap();
        assert_eq!(result["state"],"cancelled");
        assert_eq!(result["open_slots"],0);
        assert_eq!(store.cancel_local_task("task",1).unwrap(),result);
        assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"not-written").unwrap_err().kind,ErrorKind::StaleReceipt);
        assert!(!root.join("result.txt").exists());
    }

    #[test]
    fn cancel_unknown_does_not_release_or_revive_after_recovery() {
        let root = workspace("cancel-unknown");
        let mut store = Store::open(&root).unwrap();
        let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
        store.plan(&blueprint).unwrap();
        let claim = store.claim_local("task","write").unwrap();
        store.begin_local_dispatch(&claim,&root.join("result.txt"),b"expected").unwrap();
        let result = store.cancel_local_task("task",1).unwrap();
        assert_eq!(result["state"],"cancel_requested");
        assert_eq!(result["open_slots"],1);
        store.recover().unwrap();
        let state: String = store.connection.query_row("SELECT state FROM nodes",[],|row| row.get(0)).unwrap();
        assert_eq!(state,"cancel_requested");
        assert_eq!(store.status().unwrap()["open_slots"],1);
        assert!(store.claim_local("task","write").is_err());
    }

    #[test]
    fn attempt_identity_is_not_ambiguous_string_joining() {
        let root = workspace("attempt-id");
        let mut store = Store::open(&root).unwrap();
        let first = plan(&store,"a/b",&[("c","first.txt")],&[],1);
        let second = plan(&store,"a",&[("b/c","second.txt")],&[],1);
        store.plan(&first).unwrap();
        store.plan(&second).unwrap();
        let first_claim = store.claim_local("a/b","c").unwrap();
        let second_claim = store.claim_local("a","b/c").unwrap();
        assert_ne!(first_claim.attempt_id(),second_claim.attempt_id());
        assert_eq!(first_claim.attempt_id().len(),64);
    }
}
