use crate::error::{Error,ErrorKind,Result};
use crate::graph::Node;
use crate::store::Store;
use crate::strict_json;
use rusqlite::{OptionalExtension,TransactionBehavior,params};
use serde_json::{Value,json};
use std::collections::BTreeMap;

impl Store {
    pub fn execution_summary(&mut self, task: &str) -> Result<Value> {
        self.refresh_local_evidence()?;
        let transaction=self.connection.transaction_with_behavior(TransactionBehavior::Deferred)?;
        let (revision,release,state):(i64,String,String)=transaction.query_row("SELECT graph_revision,release_id,status FROM tasks WHERE id=?1 AND scope=?2",params![task,self.scope],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?;
        let mut statement=transaction.prepare("SELECT id,state,spec_json FROM nodes WHERE task_id=?1 ORDER BY id LIMIT 257")?;
        let nodes:Vec<(String,String,String)>=statement.query_map([task],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        if nodes.len()>256 { return Err(Error::new(ErrorKind::BudgetExhausted,"execution summary exceeds task node bound; no silent truncation")); }
        let mut node_counts=BTreeMap::<String,usize>::new();
        let mut results=Vec::new();
        let mut unmet=Vec::new();
        for (id,node_state,text) in nodes {
            *node_counts.entry(node_state.clone()).or_default()+=1;
            let node:Node=serde_json::from_str(&text)?;
            if node_state!="succeeded" { unmet.push(json!({"node":id,"state":node_state}));continue; }
            let artifact:Option<(String,String,String,i64)>=transaction.query_row("SELECT id,path,sha256,bytes FROM artifacts WHERE task_id=?1 AND node_id=?2 AND state='adopted'",params![task,id],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).optional()?;
            let Some((artifact,path,hash,bytes))=artifact else { return Err(Error::new(ErrorKind::ValidationStale,"succeeded node has no current adopted artifact")); };
            let mut checks=Vec::new();
            for requirement in node.acceptance_ids {
                let validation:Option<(String,String,String)>=transaction.query_row("SELECT v.id,v.validator,v.verdict FROM acceptance_links l JOIN validations v ON v.id=l.validation_id WHERE l.task_id=?1 AND l.node_id=?2 AND l.requirement_id=?3 AND v.artifact_id=?4 AND v.artifact_hash=?5",params![task,id,requirement,artifact,hash],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
                let Some((validation,validator,verdict))=validation else { return Err(Error::new(ErrorKind::ValidationStale,"required acceptance lacks an exact current validation link")); };
                if verdict!="pass" { return Err(Error::new(ErrorKind::ValidationStale,"required acceptance is not passed")); }
                checks.push(json!({"requirement_id":requirement,"validation_id":validation,"validator":validator,"verdict":verdict}));
            }
            results.push(json!({"node":id,"artifact_id":artifact,"path":path,"sha256":hash,"bytes":bytes,"acceptance":checks}));
        }
        let mut statement=transaction.prepare("SELECT s.host_class,s.state,i.state FROM slots s JOIN attempts a ON a.id=s.attempt_id JOIN invocations i ON i.attempt_id=a.id WHERE a.task_id=?1 LIMIT 1025")?;
        let calls:Vec<(String,String,String)>=statement.query_map([task],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?.collect::<std::result::Result<_,_>>()?;
        drop(statement);
        if calls.len()>1024 { return Err(Error::new(ErrorKind::BudgetExhausted,"execution summary attempt bound exceeded")); }
        let mut hosts=BTreeMap::<String,usize>::new();
        let mut open=0;
        let mut unknown=0;
        for (host,slot,invocation) in &calls {
            *hosts.entry(host.clone()).or_default()+=1;
            open+=usize::from(slot!="closed");
            unknown+=usize::from(invocation=="unknown" || invocation=="dispatching");
        }
        let completed=state=="succeeded" && unmet.is_empty() && open==0 && unknown==0;
        let result=json!({"communicator":"aji","task_id":task,"project_scope":self.scope,"graph_revision":revision,"locked_execution_release":release,
            "task_state":state,"result_state":if completed { "completed_bounded_task" } else { "incomplete" },"results":results,"unmet_nodes":unmet,
            "node_state_counts":node_counts,"recorded_invocations":calls.len(),"recorded_host_classes":hosts,"unclosed_slots":open,"unknown_invocations":unknown,
            "actual_model_thread_count":"unknown","effective_model":"unknown","effective_effort":"unknown","formal_experts_activated":0,
            "verification_scope":"project-database-current-artifact-and-required-acceptance-links","native_or_professional_effectiveness":"not_claimed",
            "P7":false,"shutdown":false});
        if strict_json::canonical(&result)?.len()>strict_json::MAX_INPUT_BYTES { return Err(Error::new(ErrorKind::BudgetExhausted,"complete execution summary exceeds 1 MiB")); }
        transaction.commit()?;
        Ok(result)
    }
}
