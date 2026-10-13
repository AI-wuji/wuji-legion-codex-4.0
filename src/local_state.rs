use crate::error::{Error, ErrorKind, Result};
use crate::graph::{self, Edge, ExactRef, Node};
use crate::policy::{ActorContext, Operation, Role, Workspace};
use crate::store::{bounded_file, check_clock, wall_clock, Store};
use crate::strict_json;
use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

pub(crate) fn specifications(connection: &Connection, task: &str) -> Result<BTreeMap<String, Node>> {
    let mut statement = connection.prepare("SELECT id,spec_json FROM nodes WHERE task_id=?1 ORDER BY id")?;
    let rows: Vec<(String, String)> = statement.query_map([task], |row| Ok((row.get(0)?,row.get(1)?)))?.collect::<std::result::Result<_,_>>()?;
    rows.into_iter().map(|(id, spec)| Ok((id,serde_json::from_str(&spec)?))).collect()
}

pub(crate) fn edges(connection: &Connection, task: &str) -> Result<Vec<Edge>> {
    let mut statement = connection.prepare("SELECT source,target FROM dependencies WHERE task_id=?1 ORDER BY source,target")?;
    let rows = statement.query_map([task], |row| Ok(Edge { from:row.get(0)?,to:row.get(1)?,predicate:"depends-on".into() }))?.collect::<std::result::Result<_,_>>()?;
    Ok(rows)
}

pub(crate) fn invalidate(transaction: &Transaction<'_>, task: &str, nodes: &BTreeSet<String>, reason: &str) -> Result<()> {
    for node in nodes {
        transaction.execute("DELETE FROM acceptance_links WHERE task_id=?1 AND node_id=?2",params![task,node])?;
        transaction.execute("UPDATE artifacts SET state='invalidated' WHERE task_id=?1 AND node_id=?2 AND state<>'invalidated'",params![task,node])?;
        transaction.execute("UPDATE attempts SET state='superseded' WHERE task_id=?1 AND node_id=?2 AND state<>'superseded'",params![task,node])?;
        let changed = transaction.execute("UPDATE nodes SET state='blocked' WHERE task_id=?1 AND id=?2 AND state NOT IN ('blocked','cancel_requested','cancelled','superseded')",params![task,node])?;
        if changed != 0 {
            transaction.execute("INSERT INTO invalidations(task_id,node_id,graph_revision,reason) SELECT id,?2,graph_revision,?3 FROM tasks WHERE id=?1",params![task,node,reason])?;
        }
    }
    transaction.execute("UPDATE tasks SET status='blocked' WHERE id=?1 AND status NOT IN ('cancel_requested','cancelled')",[task])?;
    Ok(())
}

impl Store {
    pub fn copy_local_input(&mut self, task: &str, node: &str, input: &Path, output: &Path) -> Result<Value> {
        ActorContext::trusted_local(&self.scope,Role::Executor).require(&self.scope,Operation::Write)?;
        self.refresh_local_evidence()?;
        let path = self.workspace.resolve(input)?;
        let bytes = bounded_file(&path)?;
        std::str::from_utf8(&bytes).map_err(|_|Error::new(ErrorKind::Shape,"local copy handler requires UTF-8 before claiming any slot"))?;
        let spec_json: String = self.connection.query_row("SELECT spec_json FROM nodes WHERE task_id=?1 AND id=?2",params![task,node],|row| row.get(0))?;
        let spec: Node = serde_json::from_str(&spec_json)?;
        Self::check_inputs(&self.connection,&self.workspace,&self.scope,&spec)?;
        let mut bound = false;
        for reference in &spec.inputs {
            let registered: String = self.connection.query_row("SELECT path FROM input_files WHERE id=?1 AND revision=?2 AND state='adopted_user_input'",params![reference.id,reference.revision as i64],|row| row.get(0))?;
            if self.workspace.resolve(Path::new(&registered))? == path && reference.sha256 == strict_json::sha256(&bytes) { bound = true; }
        }
        if !bound { return Err(Error::new(ErrorKind::Reference,"copy source must be a current exact node input")); }
        let claim = match self.replayed_local_claim(task,node)? { Some(claim) => claim,None => self.claim_local(task,node)? };
        let produced = self.write_local_file(&claim,output,&bytes)?;
        let verified = self.verify_local_file(&claim)?;
        self.close_local_handler(&claim)?;
        Ok(json!({"operation":"local-utf8-input-copy","produced":produced,"verification":verified,"status":self.status()?,"professional_or_native_verified":false}))
    }

    pub(crate) fn check_inputs(connection: &Connection, workspace: &Workspace, scope: &str, node: &Node) -> Result<()> {
        let mut unique = BTreeSet::new();
        for reference in &node.inputs {
            if !unique.insert((&reference.id,reference.revision)) {
                return Err(Error::new(ErrorKind::Reference,"duplicate exact input"));
            }
            let revision = i64::try_from(reference.revision).map_err(|_| Error::new(ErrorKind::Reference,"input revision overflow"))?;
            let stored: Option<(String,String,String,String,String)> = connection.query_row("SELECT path,sha256,scope,release_id,state FROM input_files WHERE id=?1 AND revision=?2",params![reference.id,revision],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?))).optional()?;
            let (path,hash,input_scope,release,state) = stored.ok_or_else(|| Error::new(ErrorKind::Reference,"input has not been registered and adopted by local user"))?;
            if reference.r#type != "file" || reference.schema_version != 1 || reference.scope != scope || input_scope != scope || reference.release != release || reference.sha256 != hash || state != "adopted_user_input" {
                return Err(Error::new(ErrorKind::ValidationStale,"exact input is not currently adopted"));
            }
            let input_path = workspace.resolve(Path::new(&path))?;
            if !node.read_roots.iter().any(|root| workspace.resolve(Path::new(root)).is_ok_and(|allowed| Workspace::contains(&allowed,&input_path))) {
                return Err(Error::new(ErrorKind::PathDenied,"input is outside assigned read set"));
            }
            let bytes = bounded_file(&input_path)?;
            if strict_json::sha256(&bytes) != hash {
                return Err(Error::new(ErrorKind::ValidationStale,"registered input file changed"));
            }
        }
        Ok(())
    }

    pub fn register_local_input(&mut self, id: &str, input: &Path) -> Result<ExactRef> {
        self.register_input_for_release(id, input, &self.local_role_ref().release.clone())
    }

    pub(crate) fn register_input_for_release(&mut self, id: &str, input: &Path, release: &str) -> Result<ExactRef> {
        self.register_input_mode(id,input,release,false)
    }

    pub fn register_local_binary_input(&mut self, id: &str, input: &Path, confirmation: &str) -> Result<ExactRef> {
        if confirmation!="confirm-isolated-binary-media-input" {
            return Err(Error::new(ErrorKind::AuthorityDenied,"explicit isolated binary-input confirmation required"));
        }
        let development=std::fs::canonicalize(Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev"))?;
        if !self.workspace.root().starts_with(&development) || self.workspace.root()==development {
            return Err(Error::new(ErrorKind::ScopeDenied,"binary-input development admission restricted to a separate .dev workspace"));
        }
        self.register_input_mode(id,input,&self.local_role_ref().release.clone(),true)
    }

    fn register_input_mode(&mut self, id: &str, input: &Path, release: &str, allow_binary: bool) -> Result<ExactRef> {
        ActorContext::trusted_local(&self.scope,Role::Aji).require(&self.scope,Operation::Register)?;
        if id.is_empty() || id.len() > 128 || id.chars().any(char::is_control) {
            return Err(Error::new(ErrorKind::Shape,"input id must be 1..128 bytes without control characters"));
        }
        self.refresh_local_evidence()?;
        let target = self.workspace.resolve(input)?;
        let bytes = bounded_file(&target)?;
        if !allow_binary { std::str::from_utf8(&bytes).map_err(|_| Error::new(ErrorKind::Shape,"local input must be UTF-8"))?; }
        let hash = strict_json::sha256(&bytes);
        let release = release.to_owned();
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_clock(&transaction,wall_clock()?)?;
        let mut statement = transaction.prepare("SELECT a.spec_json FROM attempts a JOIN slots s ON s.attempt_id=a.id WHERE s.state<>'closed'")?;
        let active: Vec<String> = statement.query_map([],|row| row.get(0))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        for spec in active {
            let node: Node = serde_json::from_str(&spec)?;
            for write in node.write_roots {
                if Workspace::conflicts(&target,&self.workspace.resolve(Path::new(&write))?) {
                    return Err(Error::new(ErrorKind::OwnerConflict,"input intersects a live write reservation"));
                }
            }
        }
        if self.workspace.resolve(input)? != target || bounded_file(&target)? != bytes {
            return Err(Error::new(ErrorKind::ValidationStale,"input changed during registration"));
        }
        let current: Option<(i64,String,String,String)> = transaction.query_row("SELECT revision,path,sha256,release_id FROM input_files WHERE id=?1 AND state='adopted_user_input'",[id],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).optional()?;
        let revision = if let Some((revision,path,old_hash,old_release)) = current {
            if path == target.to_string_lossy() && old_hash == hash && old_release == release {
                transaction.commit()?;
                return Ok(ExactRef { id:id.into(),r#type:"file".into(),scope:self.scope.clone(),revision:revision as u64,sha256:hash,release,schema_version:1 });
            }
            transaction.execute("UPDATE input_files SET state='superseded' WHERE id=?1 AND state='adopted_user_input'",[id])?;
            revision.checked_add(1).ok_or_else(|| Error::new(ErrorKind::RevisionConflict,"input revision overflow"))?
        } else {
            let previous: i64 = transaction.query_row("SELECT coalesce(max(revision),0) FROM input_files WHERE id=?1",[id],|row| row.get(0))?;
            previous.checked_add(1).ok_or_else(|| Error::new(ErrorKind::RevisionConflict,"input revision overflow"))?
        };
        transaction.execute("INSERT INTO input_files(id,revision,path,sha256,bytes,scope,release_id,state) VALUES(?1,?2,?3,?4,?5,?6,?7,'adopted_user_input')",params![id,revision,target.to_string_lossy(),hash,bytes.len() as i64,self.scope,release])?;
        transaction.commit()?;
        self.refresh_local_evidence()?;
        Ok(ExactRef { id:id.into(),r#type:"file".into(),scope:self.scope.clone(),revision:revision as u64,sha256:hash,release,schema_version:1 })
    }

    pub fn refresh_local_evidence(&mut self) -> Result<Value> {
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_clock(&transaction,wall_clock()?)?;
        let mut statement = transaction.prepare("SELECT id,revision,path,sha256 FROM input_files WHERE state='adopted_user_input'")?;
        let inputs: Vec<(String,i64,String,String)> = statement.query_map([],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?)))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        let mut changed_inputs = 0;
        for (id,revision,path,hash) in inputs {
            let unchanged = self.workspace.resolve(Path::new(&path)).and_then(|path| bounded_file(&path)).is_ok_and(|bytes| strict_json::sha256(&bytes) == hash);
            if !unchanged {
                changed_inputs += transaction.execute("UPDATE input_files SET state='invalidated' WHERE id=?1 AND revision=?2",params![id,revision])?;
            }
        }
        let mut statement = transaction.prepare("SELECT id FROM tasks ORDER BY id")?;
        let tasks: Vec<String> = statement.query_map([],|row| row.get(0))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        let mut affected_nodes = 0;
        let mut diagnostics = Vec::new();
        for task in tasks {
            let specs = specifications(&transaction,&task)?;
            let mut seeds = Vec::new();
            for (id,node) in &specs {
                if let Err(error) = Self::check_inputs(&transaction,&self.workspace,&self.scope,node) {
                    if matches!(error.kind,ErrorKind::Storage | ErrorKind::Shape) { return Err(error); }
                    diagnostics.push(json!({"node_id":id,"error":format!("{:?}",error.kind),"detail":error.detail}));
                    seeds.push(id.clone());
                }
            }
            let mut statement = transaction.prepare("SELECT node_id,path,sha256 FROM artifacts WHERE task_id=?1 AND state<>'invalidated'")?;
            let artifacts: Vec<(String,String,String)> = statement.query_map([&task],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?.collect::<std::result::Result<_,_>>()?;
            drop(statement);
            for (node,path,hash) in artifacts {
                if !self.workspace.resolve(Path::new(&path)).and_then(|path| bounded_file(&path)).is_ok_and(|bytes| strict_json::sha256(&bytes) == hash) { seeds.push(node); }
            }
            if !seeds.is_empty() {
                let affected = graph::affected(&seeds,&edges(&transaction,&task)?);
                affected_nodes += affected.len();
                invalidate(&transaction,&task,&affected,"local-input-or-output-no-longer-current")?;
            }
        }
        transaction.commit()?;
        Ok(json!({"changed_input_files":changed_inputs,"affected_nodes":affected_nodes,"diagnostics":diagnostics,"slots_released":0,"files_deleted":0,"native_verified":false}))
    }

    pub(crate) fn finalize_local_task(transaction: &Transaction<'_>, task: &str) -> Result<()> {
        let (state,open,pending): (String,i64,i64) = transaction.query_row("SELECT status,(SELECT count(*) FROM attempts a JOIN slots s ON s.attempt_id=a.id WHERE a.task_id=t.id AND s.state<>'closed'),(SELECT count(*) FROM nodes n WHERE n.task_id=t.id AND n.state<>'succeeded') FROM tasks t WHERE t.id=?1",[task],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?;
        if open == 0 && state == "cancel_requested" {
            transaction.execute("UPDATE tasks SET status='cancelled' WHERE id=?1",[task])?;
            transaction.execute("UPDATE nodes SET state='cancelled' WHERE task_id=?1 AND state='cancel_requested'",[task])?;
        } else if open == 0 && pending == 0 && !["cancelled","cancel_requested"].contains(&state.as_str()) {
            transaction.execute("UPDATE tasks SET status='succeeded' WHERE id=?1",[task])?;
        }
        Ok(())
    }
}
