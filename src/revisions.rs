use crate::contracts::Schemas;
use crate::error::{Error, ErrorKind, Result};
use crate::graph::{self, ExecutionForm, Node, Workflow};
use crate::local_state::{edges, invalidate, specifications};
use crate::policy::{ActorContext, Operation, Role};
use crate::store::{check_clock, event_insert, event_replay, wall_clock, Store};
use crate::strict_json;
use rusqlite::{params, TransactionBehavior};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::path::Path;

fn behavior(node: &Node) -> Result<String> {
    let mut value = serde_json::to_value(node)?;
    value.as_object_mut().unwrap().remove("revision");
    strict_json::digest(&value)
}

impl Store {
    pub fn revise_local_plan(&mut self, envelope: &Value, expected: i64, event_id: &str) -> Result<Value> {
        self.revise_local_plan_internal(envelope,expected,event_id,false)
    }

    pub fn repair_local_plan(&mut self, envelope: &Value, expected: i64, event_id: &str) -> Result<Value> {
        self.revise_local_plan_internal(envelope,expected,event_id,true)
    }

    fn revise_local_plan_internal(&mut self, envelope: &Value, expected: i64, event_id: &str, repair: bool) -> Result<Value> {
        ActorContext::trusted_local(&self.scope,Role::Aji).require(&self.scope,Operation::Revise)?;
        if expected < 1 || event_id.is_empty() || event_id.len() > 128 {
            return Err(Error::new(ErrorKind::Shape,"revision needs predecessor and bounded user event id"));
        }
        Schemas::frozen()?.check_envelope(envelope)?;
        if envelope["contract_type"] != "WorkflowPlan" || envelope["metadata"]["authority"] != "review_proposal" || envelope["metadata"]["owner"] != "aji-local" || envelope["metadata"]["scope"].as_str() != Some(self.scope.as_str()) {
            return Err(Error::new(ErrorKind::AuthorityDenied,"only local user plan proposal can revise this scope"));
        }
        let workflow: Workflow = serde_json::from_value(envelope["payload"].clone())?;
        let next = expected.checked_add(1).ok_or_else(|| Error::new(ErrorKind::RevisionConflict,"graph revision overflow"))?;
        if envelope["metadata"]["id"].as_str() != Some(workflow.workflow_id.as_str()) || envelope["metadata"]["revision"].as_i64() != Some(next) {
            return Err(Error::new(ErrorKind::RevisionConflict,"proposal must name next graph revision"));
        }
        let ids: Vec<_> = workflow.nodes.iter().map(|node| node.id.clone()).collect();
        graph::dependency_order(&ids,&workflow.edges)?;
        if ids.len() > 256 { return Err(Error::new(ErrorKind::BudgetExhausted,"P2 plan node cap 256")); }
        let role = self.local_role_ref();
        let plan_hash = strict_json::object_digest(envelope)?;
        let mut event = json!({"expected":expected,"plan_hash":plan_hash,"event":event_id,"scope":self.scope});
        if repair { event["mode"] = json!("evidenced-repair"); }
        let payload_hash = strict_json::digest(&event)?;
        let key = format!("revise:{}",strict_json::digest(&json!([self.scope,workflow.workflow_id,event_id]))?);
        let _catalog_guard = self.hold_task_catalog(&workflow.workflow_id)?;
        self.refresh_local_evidence()?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_clock(&transaction,wall_clock()?)?;
        if let Some(replayed) = event_replay(&transaction,&key,&payload_hash)? { transaction.commit()?; return Ok(replayed); }
        let (current,status,used,cap): (i64,String,i64,i64) = transaction.query_row("SELECT graph_revision,status,revisions_used,revision_cap FROM tasks WHERE id=?1 AND scope=?2",params![workflow.workflow_id,self.scope],|row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?)))?;
        if current != expected || ["cancel_requested","cancelled"].contains(&status.as_str()) {
            return Err(Error::new(ErrorKind::RevisionConflict,"stale/cancelled graph cannot be revised"));
        }
        if !repair && used >= cap { return Err(Error::new(ErrorKind::BudgetExhausted,"explicit local user-plan revision cap")); }
        let prior_json: String = transaction.query_row("SELECT envelope_json FROM task_plans WHERE task_id=?1 AND graph_revision=?2",params![workflow.workflow_id,current],|row| row.get(0))?;
        let prior = strict_json::parse(prior_json.as_bytes())?;
        if prior["payload"]["budget"] != envelope["payload"]["budget"] || prior["payload"]["catalog_version"] != envelope["payload"]["catalog_version"] {
            return Err(Error::new(ErrorKind::BudgetExhausted,"revision cannot reset task budget or repin catalog"));
        }
        let previous = specifications(&transaction,&workflow.workflow_id)?;
        let proposed: BTreeSet<_> = ids.iter().cloned().collect();
        if previous.keys().any(|id| !proposed.contains(id)) {
            return Err(Error::new(ErrorKind::Shape,"P2 removal unsupported; preserve historical node identity"));
        }
        let old_edges = edges(&transaction,&workflow.workflow_id)?;
        let mut seeds = BTreeSet::new();
        for node in &workflow.nodes {
            if node.execution_form != ExecutionForm::Program { return Err(Error::new(ErrorKind::HostUnknown,"native/model role remains unadmitted")); }
            let checks = ["local.file-readable","local.hash-current","local.utf8"];
            if node.role_ref != role || node.owner != "local-executor" || node.status != "planned" || node.acceptance_ids.len() != checks.len() || checks.iter().any(|check| !node.acceptance_ids.iter().any(|actual| actual == check)) {
                return Err(Error::new(ErrorKind::Reference,"local handler/checks are exact"));
            }
            if node.role_ref.release != workflow.catalog_version || node.inputs.iter().any(|input| input.release != workflow.catalog_version) { return Err(Error::new(ErrorKind::Reference,"reference release differs from catalog")); }
            Self::check_inputs(&transaction,&self.workspace,&self.scope,node)?;
            for path in node.read_roots.iter().chain(&node.write_roots) { self.workspace.resolve(Path::new(path))?; }
            for path in &node.write_roots { self.workspace.output(Path::new(path))?; }
            match previous.get(&node.id) {
                Some(old) if behavior(old)? == behavior(node)? => {}
                _ => { seeds.insert(node.id.clone()); }
            }
        }
        let old_pairs: BTreeSet<_> = old_edges.iter().map(|edge| (edge.from.clone(),edge.to.clone())).collect();
        let new_pairs: BTreeSet<_> = workflow.edges.iter().map(|edge| (edge.from.clone(),edge.to.clone())).collect();
        seeds.extend(old_pairs.symmetric_difference(&new_pairs).map(|(_,target)| target.clone()));
        let mut live = transaction.prepare("SELECT id FROM nodes WHERE task_id=?1 AND state IN ('claimed','running','produced','validating','blocked','failed')")?;
        let live_ids: Vec<String> = live.query_map([&workflow.workflow_id],|row| row.get(0))?.collect::<std::result::Result<_,_>>()?;
        drop(live);
        if !repair { seeds.extend(live_ids); }
        let mut defect_nodes = BTreeSet::<String>::new();
        if repair {
            let mut statement = transaction.prepare(
                "SELECT DISTINCT i.node_id FROM invalidations i JOIN nodes n ON n.task_id=i.task_id AND n.id=i.node_id WHERE i.task_id=?1 AND i.reason='local-input-or-output-no-longer-current' AND n.state<>'succeeded' AND i.graph_revision>=COALESCE((SELECT MAX(v.graph_revision) FROM validations v JOIN artifacts a ON a.id=v.artifact_id WHERE a.task_id=i.task_id AND a.node_id=i.node_id AND v.verdict='pass'),0)")?;
            defect_nodes = statement.query_map([&workflow.workflow_id],|row| row.get(0))?.collect::<std::result::Result<_,_>>()?;
            drop(statement);
            for node in &workflow.nodes {
                if defect_nodes.contains(&node.id) && previous.get(&node.id).is_some_and(|old| node.revision > old.revision) {
                    seeds.insert(node.id.clone());
                }
            }
        }
        if seeds.is_empty() { return Err(Error::new(ErrorKind::RevisionConflict,"no semantic change; no progress is not a new revision")); }
        let combined: Vec<_> = old_edges.iter().chain(&workflow.edges).cloned().collect();
        let affected = graph::affected(&seeds.into_iter().collect::<Vec<_>>(),&combined);
        if repair {
            defect_nodes.retain(|node| affected.contains(node));
            if defect_nodes.is_empty() {
                return Err(Error::new(ErrorKind::ValidationStale,"repair requires an actual unresolved local evidence invalidation, not caller-declared findings"));
            }
            let permitted = graph::affected(&defect_nodes.iter().cloned().collect::<Vec<_>>(),&old_edges);
            if affected != permitted || !proposed.is_subset(&previous.keys().cloned().collect()) || old_pairs != new_pairs {
                return Err(Error::new(ErrorKind::ScopeDenied,"bounded repair may only revise the evidenced defect chain; structural user changes require revise"));
            }
            let mut statement = transaction.prepare("SELECT result_json FROM events WHERE task_id=?1 AND event_key LIKE 'revise:%' ORDER BY event_key LIMIT 2049")?;
            let texts: Vec<String> = statement.query_map([&workflow.workflow_id],|row| row.get(0))?.collect::<std::result::Result<_,_>>()?;
            drop(statement);
            if texts.len() > 2048 { return Err(Error::new(ErrorKind::BudgetExhausted,"repair history exceeds bounded review window")); }
            let history: Vec<Value> = texts.iter().map(|text| strict_json::parse(text.as_bytes())).collect::<Result<_>>()?;
            for node in &defect_nodes {
                let last_verified: i64 = transaction.query_row(
                    "SELECT COALESCE(MAX(v.graph_revision),0) FROM validations v JOIN artifacts a ON a.id=v.artifact_id WHERE a.task_id=?1 AND a.node_id=?2 AND v.verdict='pass'",params![workflow.workflow_id,node],|row| row.get(0))?;
                let repairs: Vec<&Value> = history.iter().filter(|result| result["defect_nodes"].as_array().is_some_and(|nodes| nodes.iter().any(|item| item.as_str()==Some(node)))).collect();
                let without_progress = repairs.iter().filter(|result| result["graph_revision"].as_i64().is_some_and(|revision| revision>last_verified)).count() as u64;
                if repairs.len() as u64 >= workflow.budget.max_point_revisions || without_progress >= workflow.budget.max_no_progress {
                    return Err(Error::new(ErrorKind::BudgetExhausted,format!("evidenced node {node} reached its pinned repair or no-progress cap")));
                }
            }
        }
        for node in &workflow.nodes {
            let required = match previous.get(&node.id) {
                Some(old) if affected.contains(&node.id) => old.revision.checked_add(1).ok_or_else(|| Error::new(ErrorKind::RevisionConflict,"node revision overflow"))?,
                Some(old) => old.revision,
                None => 1,
            };
            if node.revision != required { return Err(Error::new(ErrorKind::RevisionConflict,format!("node {} must have revision {}",node.id,required))); }
        }
        let changed = transaction.execute("UPDATE tasks SET graph_revision=?3,plan_hash=?4,revisions_used=revisions_used+?5,status='active' WHERE id=?1 AND graph_revision=?2",params![workflow.workflow_id,expected,next,plan_hash,i64::from(!repair)])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"graph compare-and-swap lost")); }
        let existing_affected = affected.iter().filter(|id| previous.contains_key(*id)).cloned().collect();
        invalidate(&transaction,&workflow.workflow_id,&existing_affected,if repair { "evidenced-local-repair" } else { "user-graph-revision" })?;
        for node in &workflow.nodes {
            let hash = strict_json::digest(&json!({"node":node,"release":workflow.catalog_version}))?;
            let spec = serde_json::to_string(node)?;
            if previous.contains_key(&node.id) {
                if affected.contains(&node.id) {
                    transaction.execute("UPDATE nodes SET revision=?3,spec_json=?4,input_hash=?5,state='planned' WHERE task_id=?1 AND id=?2",params![workflow.workflow_id,node.id,node.revision as i64,spec,hash])?;
                }
            } else {
                transaction.execute("INSERT INTO nodes(task_id,id,revision,owner,form,spec_json,state,input_hash) VALUES(?1,?2,1,?3,'program',?4,'planned',?5)",params![workflow.workflow_id,node.id,node.owner,spec,hash])?;
            }
        }
        transaction.execute("DELETE FROM dependencies WHERE task_id=?1",[&workflow.workflow_id])?;
        for edge in &workflow.edges { transaction.execute("INSERT INTO dependencies(task_id,source,target) VALUES(?1,?2,?3)",params![workflow.workflow_id,edge.from,edge.to])?; }
        transaction.execute("INSERT INTO task_plans(task_id,graph_revision,plan_hash,envelope_json) VALUES(?1,?2,?3,?4)",params![workflow.workflow_id,next,plan_hash,serde_json::to_string(envelope)?])?;
        transaction.execute("UPDATE tasks SET status='active' WHERE id=?1",[&workflow.workflow_id])?;
        let mut result = json!({"task_id":workflow.workflow_id,"graph_revision":next,"affected_nodes":affected,"plan_hash":plan_hash,"slots_released":0,"history_retained":true,"native_execution":false});
        if repair { result["defect_nodes"] = json!(defect_nodes); result["revision_reason"] = json!("evidenced-local-repair"); }
        event_insert(&transaction,&key,&workflow.workflow_id,&payload_hash,&result)?;
        transaction.commit()?;
        Ok(result)
    }
}
