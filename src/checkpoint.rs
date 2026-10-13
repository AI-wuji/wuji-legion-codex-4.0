use crate::error::{Error, ErrorKind, Result};
use crate::store::{bounded_file, wall_clock, Store};
use crate::strict_json;
use rusqlite::{params, TransactionBehavior};
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

impl Store {
    pub fn inspect_local_attempt(&mut self, attempt: &str) -> Result<Value> {
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Deferred)?;
        let (task,node,graph_revision,node_revision,state,invocation,slot,host,path,hash,size): (String,String,i64,i64,String,String,String,String,Option<String>,Option<String>,Option<i64>) = transaction.query_row("SELECT a.task_id,a.node_id,a.graph_revision,a.node_revision,a.state,i.state,s.state,s.host_class,i.expected_output_path,i.expected_output_hash,i.expected_output_bytes FROM attempts a JOIN tasks t ON t.id=a.task_id JOIN invocations i ON i.attempt_id=a.id JOIN slots s ON s.attempt_id=a.id WHERE a.id=?1 AND t.scope=?2",params![attempt,self.scope],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?,row.get(6)?,row.get(7)?,row.get(8)?,row.get(9)?,row.get(10)?)))?;
        if host != "test_local" { return Err(Error::new(ErrorKind::HostUnknown,"this query is not an admitted native host adapter")); }
        let file_observation = if let Some(path) = &path {
            match self.workspace.output(Path::new(path)).and_then(|target| bounded_file(&target)) {
                Ok(bytes) => json!({"readable":true,"sha256":strict_json::sha256(&bytes),"bytes":bytes.len(),"matches_intent":hash.as_deref()==Some(strict_json::sha256(&bytes).as_str()) && size==Some(bytes.len() as i64),"ownership_proven_by_content":false}),
                Err(error) => json!({"readable":false,"error":format!("{:?}",error.kind),"ownership_proven_by_content":false}),
            }
        } else { json!({"readable":null,"reason":"no output intent dispatched"}) };
        let current: i64 = transaction.query_row("SELECT graph_revision FROM tasks WHERE id=?1",[&task],|row| row.get(0))?;
        transaction.commit()?;
        Ok(json!({"attempt_id":attempt,"task_id":task,"node_id":node,"graph_revision":graph_revision,"node_revision":node_revision,"current_graph_revision":current,"attempt_state":state,"invocation_state":invocation,"slot_state":slot,"host_class":host,"expected_path":path,"file_observation":file_observation,"handler_liveness":"unknown","redispatch_permitted":false,"slots_released":0,"native_verified":false,"boundary":"Matching bytes are an observation, not a producer receipt or exit confirmation."}))
    }

    pub fn checkpoint_local(&mut self, task: &str) -> Result<Value> {
        self.refresh_local_evidence()?;
        let snapshot = self.checkpoint_snapshot(task)?;
        let bytes = strict_json::canonical(&snapshot)?;
        if bytes.len() > strict_json::MAX_INPUT_BYTES { return Err(Error::new(ErrorKind::BudgetExhausted,"checkpoint exceeds 1 MiB; use bounded context projection")); }
        let id = strict_json::sha256(&bytes);
        let directory = self.workspace.resolve(Path::new(".wuji4/checkpoints"))?;
        if !directory.exists() { fs::create_dir(&directory)?; }
        let path = self.workspace.resolve(Path::new(&format!(".wuji4/checkpoints/{id}.json")))?;
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut file) => { file.write_all(&bytes)?; file.sync_all()?; }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists && bounded_file(&path)? == bytes => {}
            Err(error) => return Err(error.into()),
        }
        Ok(json!({"checkpoint_id":id,"path":path,"snapshot_hash":id,"execution_authority":false,"native_verified":false}))
    }

    fn checkpoint_snapshot(&mut self, task: &str) -> Result<Value> {
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Deferred)?;
        let (graph_revision,plan_hash,status,deadline,retries,revisions): (i64,String,String,i64,i64,i64) = transaction.query_row("SELECT graph_revision,plan_hash,status,deadline_ms,retries_used,revisions_used FROM tasks WHERE id=?1 AND scope=?2",params![task,self.scope],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?)))?;
        let mut statement = transaction.prepare("SELECT id,revision,state,input_hash,spec_json FROM nodes WHERE task_id=?1 ORDER BY id")?;
        let nodes: Vec<Value> = statement.query_map([task],|row| Ok(json!({"id":row.get::<_,String>(0)?,"revision":row.get::<_,i64>(1)?,"state":row.get::<_,String>(2)?,"input_hash":row.get::<_,String>(3)?,"spec_json":row.get::<_,String>(4)?})))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        let mut statement = transaction.prepare("SELECT a.id,a.state,i.state,s.state,l.state,l.expires_ms FROM attempts a JOIN invocations i ON i.attempt_id=a.id JOIN slots s ON s.attempt_id=a.id JOIN leases l ON l.attempt_id=a.id WHERE a.task_id=?1 ORDER BY a.id")?;
        let attempts: Vec<Value> = statement.query_map([task],|row| Ok(json!({"id":row.get::<_,String>(0)?,"state":row.get::<_,String>(1)?,"invocation":row.get::<_,String>(2)?,"slot":row.get::<_,String>(3)?,"lease":row.get::<_,String>(4)?,"expires_ms":row.get::<_,i64>(5)?})))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        let mut statement = transaction.prepare("SELECT id,path,sha256,revision,state FROM artifacts WHERE task_id=?1 ORDER BY id")?;
        let artifacts: Vec<Value> = statement.query_map([task],|row| Ok(json!({"id":row.get::<_,String>(0)?,"path":row.get::<_,String>(1)?,"sha256":row.get::<_,String>(2)?,"revision":row.get::<_,i64>(3)?,"state":row.get::<_,String>(4)?})))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        let snapshot = json!({"schema_version":1,"kind":"test-local-observational-checkpoint","scope":self.scope,"task_id":task,"graph_revision":graph_revision,"plan_hash":plan_hash,"task_state":status,"deadline_ms":deadline,"retries_used":retries,"revisions_used":revisions,"nodes":nodes,"attempts":attempts,"artifacts":artifacts,"observed_at_utc_ms":wall_clock()?,"execution_authority":false,"native_verified":false});
        transaction.commit()?;
        Ok(snapshot)
    }

    pub fn inspect_checkpoint(&mut self, id: &str) -> Result<Value> {
        if id.len() != 64 || !id.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()) {
            return Err(Error::new(ErrorKind::Shape,"checkpoint id must be lowercase SHA-256"));
        }
        let path = self.workspace.resolve(Path::new(&format!(".wuji4/checkpoints/{id}.json")))?;
        let bytes = bounded_file(&path)?;
        if strict_json::sha256(&bytes) != id { return Err(Error::new(ErrorKind::HashMismatch,"checkpoint changed")); }
        let snapshot = strict_json::parse(&bytes)?;
        if snapshot["scope"].as_str() != Some(self.scope.as_str()) || snapshot["execution_authority"] != false || snapshot["kind"] != "test-local-observational-checkpoint" {
            return Err(Error::new(ErrorKind::ScopeDenied,"checkpoint scope/kind is not current local observation"));
        }
        self.refresh_local_evidence()?;
        let task = snapshot["task_id"].as_str().ok_or_else(|| Error::new(ErrorKind::Shape,"checkpoint has no task id"))?;
        let mut latest = self.checkpoint_snapshot(task)?;
        let mut previous = snapshot.clone();
        latest.as_object_mut().unwrap().remove("observed_at_utc_ms");
        previous.as_object_mut().ok_or_else(|| Error::new(ErrorKind::Shape,"checkpoint object"))?.remove("observed_at_utc_ms");
        Ok(json!({"checkpoint_id":id,"reusable_as_context":previous==latest,"current_graph_revision":latest["graph_revision"],"execution_authority":false,"leases_extended":0,"slots_released":0,"unknowns_resolved":0,"native_verified":false}))
    }
}
