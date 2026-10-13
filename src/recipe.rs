use crate::error::{Error,ErrorKind,Result};
use crate::graph::{Edge,ExactRef,dependency_order};
use crate::policy::Workspace;
use crate::native_protocol::InvocationKind;
use crate::registry::{CatalogRegistry,ReleaseLock};
use crate::resources::registered_evidence;
use crate::store::Store;
use crate::strict_json;
use serde::Deserialize;
use serde_json::{Value,json};
use std::collections::{BTreeMap,BTreeSet};
use std::path::Path;

#[derive(Clone,Copy,Deserialize)]
#[serde(rename_all="snake_case")]
pub enum TaskKind { Text,Code,Repair,Planning }

impl TaskKind {
    fn invocation_kind(self) -> InvocationKind {
        match self {
            Self::Text => InvocationKind::Text, Self::Code => InvocationKind::Code,
            Self::Repair => InvocationKind::Repair, Self::Planning => InvocationKind::Planning,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecipeInstance {
    pub instance_id: String,
    pub owner: String,
    pub definition_ref: ExactRef,
    pub mandatory_roots: Vec<ExactRef>,
    pub depends_on: Vec<String>,
    pub inputs: Vec<ExactRef>,
    pub write_roots: Vec<String>,
    pub acceptance_ids: Vec<String>,
    pub task_kind: TaskKind,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecipeRequest {
    pub task_id: String,
    pub release_lock: ReleaseLock,
    pub instances: Vec<RecipeInstance>,
    pub max_parallel_instances: usize,
    pub byte_cap: usize,
}

fn identity(value: &str) -> Result<()> {
    if value.is_empty() || value.len()>128 || value.chars().any(char::is_control) {
        return Err(Error::new(ErrorKind::Shape,"bounded nonempty recipe identity required"));
    }
    Ok(())
}

impl Store {
    pub fn prepare_recipe(&self, registry: &CatalogRegistry, request: &RecipeRequest) -> Result<Value> {
        identity(&request.task_id)?;
        if request.instances.is_empty() || request.instances.len()>32 || request.max_parallel_instances==0
            || request.max_parallel_instances>3 || request.byte_cap==0 || request.byte_cap>strict_json::MAX_INPUT_BYTES {
            return Err(Error::new(ErrorKind::BudgetExhausted,"bounded recipe requires 1..32 instances, construction cap 1..3 and <=1 MiB complete context"));
        }
        let mut edges=Vec::new();
        let mut paths:Vec<(String,std::path::PathBuf)>=Vec::new();
        let mut assemblies=Vec::new();
        for instance in &request.instances {
            identity(&instance.instance_id)?;
            identity(&instance.owner)?;
            if instance.inputs.len()>16 || instance.write_roots.len()>16 || instance.depends_on.len()>32
                || instance.mandatory_roots.len()>16 || instance.acceptance_ids.is_empty() || instance.acceptance_ids.len()>32 {
                return Err(Error::new(ErrorKind::BudgetExhausted,"recipe instance IO/dependency/acceptance bounds exceeded"));
            }
            let mut checks=BTreeSet::new();
            for check in &instance.acceptance_ids { identity(check)?;if !checks.insert(check) { return Err(Error::new(ErrorKind::Shape,"duplicate recipe acceptance ID")); } }
            for input in &instance.inputs { registered_evidence(&self.connection,&self.workspace,&self.scope,input)?; }
            for write in &instance.write_roots {
                let path=self.workspace.output(Path::new(write))?;
                if paths.iter().any(|(_,previous)|Workspace::conflicts(&path,previous)) {
                    return Err(Error::new(ErrorKind::OwnerConflict,"recipe instances cannot have overlapping canonical write sets"));
                }
                paths.push((instance.instance_id.clone(),path));
            }
            for upstream in &instance.depends_on { edges.push(Edge { from:upstream.clone(),to:instance.instance_id.clone(),predicate:"depends-on".into() }); }
            let mut roots=instance.mandatory_roots.clone();
            if !roots.contains(&instance.definition_ref) { roots.push(instance.definition_ref.clone()); }
            assemblies.push(roots);
        }
        let ids: Vec<_>=request.instances.iter().map(|instance|instance.instance_id.clone()).collect();
        let ordered=dependency_order(&ids,&edges)?;
        let contracts=registry.compose_many_locked(&request.release_lock,&assemblies,request.byte_cap)?;
        let mut shared=BTreeMap::new();
        let mut instances=Vec::new();
        for (instance,contract) in request.instances.iter().zip(contracts) {
            let fields=&contract["fields"];
            if fields["authorization_required"]!=true || fields["acceptance_required"]!=true {
                return Err(Error::new(ErrorKind::RequiredWeakened,"prepared experts must preserve authorization and acceptance invariants"));
            }
            for field in ["role","task","process","constraints","output","specialty","input_contract","tool_contract","acceptance_contract"] {
                if !(fields[field].is_string() || fields[field].is_array() || fields[field].is_object()) || fields[field].as_str().is_some_and(str::is_empty)
                    || fields[field].as_array().is_some_and(Vec::is_empty) || fields[field].as_object().is_some_and(serde_json::Map::is_empty) {
                    return Err(Error::new(ErrorKind::Shape,format!("shared narrow expert contract lacks {field}")));
                }
            }
            let definition_key=strict_json::digest(&json!({"reference":instance.definition_ref,"composition_hash":contract["composition_hash"]}))?;
            shared.entry(definition_key.clone()).or_insert(json!({"reference":instance.definition_ref,"compiled_contract":contract}));
            instances.push(json!({"instance_id":instance.instance_id,"owner":instance.owner,"shared_definition_key":definition_key,
                "inputs":instance.inputs,"depends_on":instance.depends_on,"acceptance_ids":instance.acceptance_ids,
                "write_roots":instance.write_roots,"requested_model":instance.task_kind.invocation_kind().requested_model(),
                "requested_effort":instance.task_kind.invocation_kind().requested_effort(),
                "selection_boundary":instance.task_kind.invocation_kind().selection_boundary(),
                "effective_model":"unknown","effective_effort":"unknown","runtime_admission":false}));
        }
        let result=json!({"state":"prepared","task_id":request.task_id,"project_scope":self.scope,"release_lock":request.release_lock,
            "instances":instances,"shared_definitions":shared,"dependency_order":ordered,"max_parallel_instances":request.max_parallel_instances,
            "quota_basis":"conservative-construction-cap-not-native-quota","actual_agents_started":0,"formal_experts_activated":0,
            "user_communicator":"aji","runtime_admission":false,"execution_authority":false});
        if strict_json::canonical(&result)?.len()>request.byte_cap { return Err(Error::new(ErrorKind::BudgetExhausted,"complete prepared recipe exceeds byte cap; no truncation")); }
        Ok(result)
    }
}

#[cfg(test)]
#[path = "recipe_tests.rs"]
mod tests;
