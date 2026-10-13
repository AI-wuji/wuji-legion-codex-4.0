use crate::contracts::Schemas;
use crate::error::{Error, ErrorKind, Result};
use crate::graph::{self, ExactRef, ExecutionForm, Node, Workflow};
use crate::policy::Workspace;
use crate::strict_json;
use serde_json::{json, Value};
use std::path::Path;

pub const REQUESTED_MODEL: &str = "gpt-6.1-sol";
pub const PREPARATION_RELEASE: &str = "p2-native-preparation-1";
const UNBOUND_THREAD: &str = "<trusted-thread-id-not-yet-bound>";
const ENGINEERING: &[u8] = include_bytes!("../catalog/p2/engineering.json");
const VALIDATION: &[u8] = include_bytes!("../catalog/p2/validation.json");

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InvocationKind { Text, Code, Repair, Planning }

impl InvocationKind {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "text" => Ok(Self::Text), "code" => Ok(Self::Code),
            "repair" => Ok(Self::Repair), "planning" => Ok(Self::Planning),
            _ => Err(Error::new(ErrorKind::Shape, "unknown invocation kind; no model or effort override")),
        }
    }

    pub fn requested_model(self) -> &'static str {
        match self { Self::Text => "inherit_current_selection", _ => REQUESTED_MODEL }
    }

    pub fn selection_boundary(self) -> &'static str {
        match self {
            Self::Text => "Prepared inheritance of the current conversation model and effort only; not an independent CLI disk default or an effective selection. A separate host requires a trusted current-conversation baseline handoff.",
            _ => "Prepared explicit user-requested Sol high/xhigh upgrade target only; not automatic difficulty classification, an effective selection or authorization to downgrade the current conversation model or effort.",
        }
    }

    pub fn requested_effort(self) -> &'static str {
        match self { Self::Text => "inherit", Self::Code => "high", Self::Repair | Self::Planning => "xhigh" }
    }
}

pub struct PreparedNativeRequest {
    report: Value,
}

impl PreparedNativeRequest {
    pub fn report(&self) -> &Value { &self.report }

    pub fn ensure_dispatchable(&self) -> Result<()> {
        Err(Error::new(ErrorKind::HostUnknown, "preparation has no trusted host, fee, model, quota, scope or delegation permit; no submission"))
    }
}

fn workspace_scope(workspace: &Workspace) -> String {
    let hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
    format!("project:{}", &hash[..24])
}

fn role_bytes(kind: &str) -> Result<&'static [u8]> {
    match kind {
        "engineering" => Ok(ENGINEERING), "validation" => Ok(VALIDATION),
        _ => Err(Error::new(ErrorKind::Reference, "only two P2 minimum prepared roles are available")),
    }
}

fn role_reference(scope: &str, bytes: &[u8], role: &Value) -> Result<ExactRef> {
    if role["state"] != "prepared" || role["runtime_admission"] != false || role["effectiveness"] != "not_run" || role["release"] != PREPARATION_RELEASE {
        return Err(Error::new(ErrorKind::Reference, "role is not the prepared P2 candidate"));
    }
    let reference = ExactRef {
        id: role["id"].as_str().ok_or_else(|| Error::new(ErrorKind::Shape, "role id required"))?.into(),
        r#type: "file".into(), scope: scope.into(), revision: role["revision"].as_u64().ok_or_else(|| Error::new(ErrorKind::Shape, "prepared role revision required"))?,
        sha256: strict_json::sha256(bytes), release: PREPARATION_RELEASE.into(), schema_version: 1,
    };
    Schemas::frozen()?.check_definition("ExactRef", &serde_json::to_value(&reference)?)?;
    Ok(reference)
}

pub fn prepared_roles(approved_root: &Path) -> Result<Value> {
    let workspace = Workspace::open(approved_root)?;
    let scope = workspace_scope(&workspace);
    let mut roles = Vec::new();
    for kind in ["engineering", "validation"] {
        let bytes = role_bytes(kind)?;
        let role = strict_json::parse(bytes)?;
        roles.push(json!({"kind":kind,"reference":role_reference(&scope,bytes,&role)?,"candidate":role}));
    }
    Ok(json!({"state":"prepared","scope":scope,"release":PREPARATION_RELEASE,"roles":roles,"runtime_admission":false,"formal_model_experts":0,"native_host_verified":false,"P3_batch_generation":false}))
}

pub(crate) fn resolve_role(node: &Node, scope: &str) -> Result<Value> {
    for kind in ["engineering", "validation"] {
        let bytes = role_bytes(kind)?;
        let role = strict_json::parse(bytes)?;
        if node.role_ref == role_reference(scope, bytes, &role)? { return Ok(role); }
    }
    Err(Error::new(ErrorKind::Reference, "node role must match exact prepared P2 bytes/revision/release; no latest fallback"))
}

fn check_node_with_output_policy(workspace: &Workspace, scope: &str, node: &Node, require_new_output: bool) -> Result<Value> {
    if node.execution_form != ExecutionForm::Model || node.status != "planned" {
        return Err(Error::new(ErrorKind::Shape, "native preparation only accepts planned model nodes"));
    }
    let role = resolve_role(node, scope)?;
    if node.inputs.is_empty() || node.read_roots.is_empty() || node.write_roots.is_empty() {
        return Err(Error::new(ErrorKind::Shape, "bounded native proposal needs declared inputs and read/write file paths"));
    }
    if node.inputs.iter().any(|reference| reference.scope != scope || reference.release != PREPARATION_RELEASE) {
        return Err(Error::new(ErrorKind::ScopeDenied, "native input scope/release mismatch"));
    }
    let checks = role["required_checks"].as_array().ok_or_else(|| Error::new(ErrorKind::Shape, "role checks missing"))?;
    if checks.len() != node.acceptance_ids.len() || checks.iter().any(|check| !node.acceptance_ids.iter().any(|actual| check.as_str() == Some(actual.as_str()))) {
        return Err(Error::new(ErrorKind::RequiredWeakened, "prepared role required checks cannot be removed or replaced"));
    }
    for path in &node.read_roots {
        let resolved = workspace.output(Path::new(path))?;
        if !resolved.is_file() { return Err(Error::new(ErrorKind::PathDenied, "G2 candidate reads must be existing bounded files, not whole directories")); }
    }
    for path in &node.write_roots {
        let resolved = workspace.output(Path::new(path))?;
        if resolved == workspace.root() || resolved.is_dir() {
            return Err(Error::new(ErrorKind::PathDenied, "G2 candidate output must name a file, not a whole directory"));
        }
        if require_new_output && resolved.exists() { return Err(Error::new(ErrorKind::PathDenied, "G2 prepared output must be a new version path; no overwrite permission")); }
    }
    Ok(role)
}

pub(crate) fn check_node(workspace: &Workspace, scope: &str, node: &Node) -> Result<Value> {
    check_node_with_output_policy(workspace, scope, node, true)
}

pub fn prepare(approved_root: &Path, envelope: &Value, node_id: &str, kind: InvocationKind) -> Result<PreparedNativeRequest> {
    Schemas::frozen()?.check_envelope(envelope)?;
    let workspace = Workspace::open(approved_root)?;
    let scope = workspace_scope(&workspace);
    if envelope["contract_type"] != "WorkflowPlan" || envelope["metadata"]["authority"] != "review_proposal" || envelope["metadata"]["owner"] != "aji-local" {
        return Err(Error::new(ErrorKind::AuthorityDenied, "preparation accepts a proposal only, not imported authority or successful receipts"));
    }
    if envelope["metadata"]["scope"].as_str() != Some(scope.as_str()) {
        return Err(Error::new(ErrorKind::ScopeDenied, "native proposal workspace scope mismatch"));
    }
    let workflow: Workflow = serde_json::from_value(envelope["payload"].clone())?;
    if envelope["metadata"]["id"].as_str() != Some(workflow.workflow_id.as_str()) || workflow.catalog_version != PREPARATION_RELEASE {
        return Err(Error::new(ErrorKind::Reference, "native proposal identity/preparation release mismatch"));
    }
    if workflow.nodes.len() > 256 { return Err(Error::new(ErrorKind::BudgetExhausted, "P2 native proposal node cap 256")); }
    let ids: Vec<_> = workflow.nodes.iter().map(|node| node.id.clone()).collect();
    graph::dependency_order(&ids, &workflow.edges)?;
    let mut selected = None;
    for node in &workflow.nodes {
        let role = check_node_with_output_policy(&workspace, &scope, node, node.id == node_id)?;
        if role["kind"] == "validation" {
            let producers: Vec<_> = workflow.edges.iter().filter(|edge| edge.to == node.id).map(|edge| workflow.nodes.iter().find(|upstream| upstream.id == edge.from).unwrap()).collect();
            if producers.is_empty() { return Err(Error::new(ErrorKind::DependencyNotAccepted, "independent review needs an explicit producer dependency")); }
            if producers.iter().any(|producer| producer.owner == node.owner) {
                return Err(Error::new(ErrorKind::SelfReview, "reviewer cannot be its upstream producer"));
            }
        }
        if node.id == node_id { selected = Some((node, role)); }
    }
    let (node, role) = selected.ok_or_else(|| Error::new(ErrorKind::Reference, "requested node not in proposal"))?;
    if role["kind"] == "validation" && kind != InvocationKind::Code {
        return Err(Error::new(ErrorKind::Reference, "code validator uses the explicit code upgrade request; no expert expansion"));
    }
    let cwd = workspace.root().to_str().ok_or_else(|| Error::new(ErrorKind::PathDenied, "native cwd must be Unicode"))?;
    let instructions = format!("P2 preparation only. You must not dispatch other agents, install, publish, pay, change Codex/plugins/audio, widen the file scope or grant yourself authority. Research existing applicable evidence first. Aji is the sole user communicator. Return version-bound proposals and real evidence gaps; never claim host close from task completion. Independent acceptance is required. Role candidate: {}", String::from_utf8(strict_json::canonical(&role)?).map_err(|_| Error::new(ErrorKind::Shape, "canonical UTF-8"))?);
    let task = json!({"workflow_id":workflow.workflow_id,"graph_revision":envelope["metadata"]["revision"],"node":node,"input_ref_status":"declared_not_verified_or_adopted_by_preparation","file_scope_status":"proposed_not_authorized"});
    let mut thread = json!({"method":"thread/start","id":1,"params":{"model":REQUESTED_MODEL,"cwd":cwd,"approvalPolicy":"never","sandbox":"read-only","ephemeral":true,"developerInstructions":instructions}});
    let mut turn = json!({"method":"turn/start","id":2,"params":{"threadId":UNBOUND_THREAD,"model":REQUESTED_MODEL,"effort":kind.requested_effort(),"cwd":cwd,"approvalPolicy":"never","sandboxPolicy":{"type":"readOnly","networkAccess":false},"input":[{"type":"text","text":String::from_utf8(strict_json::canonical(&task)?).map_err(|_| Error::new(ErrorKind::Shape, "canonical UTF-8"))?}]}});
    if kind == InvocationKind::Text {
        // Omission is a prepared inheritance contract, not proof of a new host's baseline.
        for message in [&mut thread, &mut turn] {
            let params = message["params"].as_object_mut().unwrap();
            params.remove("model");
            params.remove("effort");
        }
    }
    let request_hash = strict_json::digest(&json!({"thread":thread,"turn":turn}))?;
    let report = json!({
        "state":"prepared","runtime_admission":false,"dispatchable":false,"generation_submitted":false,
        "scope":scope,"preparation_release":PREPARATION_RELEASE,
        "workflow_id":workflow.workflow_id,"node_id":node.id,"node_revision":node.revision,
        "graph_revision":envelope["metadata"]["revision"],"plan_object_hash":strict_json::object_digest(envelope)?,
        "role_ref":node.role_ref,"requested_model":kind.requested_model(),"requested_effort":kind.requested_effort(),
        "selection_boundary":kind.selection_boundary(),
        "request_template_hash":request_hash,"thread_binding":"unbound_requires_trusted_transport",
        "transport":"codex-app-server-0.160.0-stdio-candidate-no-process-started",
        "candidate_messages":{"thread_start":thread,"turn_start_unbound":turn},
        "effective":{"model":"unknown","effort":"unknown","native_capacity":"unknown","fee_precondition":"unknown","closed_or_released":"unknown"},
        "blockers":["trusted_model_and_effort_acceptance","known_no_fee_precondition","native_capacity_and_real_exit","explicit_delegation_if_required","current_adopted_input_bindings","trusted_action_scope","runtime_role_admission"],
        "boundary":"Candidate messages are not dispatch permits, running threads, observed receipts, professional validation, scope grants or G2 success. Read-only model output would still need a separate authorized file materializer."
    });
    let bytes = strict_json::canonical(&report)?.len();
    let cap = workflow.budget.hard_bytes_limit.unwrap_or(strict_json::MAX_INPUT_BYTES as u64).min(strict_json::MAX_INPUT_BYTES as u64);
    if bytes as u64 > cap { return Err(Error::new(ErrorKind::BudgetExhausted, "native prepared contract exceeds hard byte cap; no silent truncation")); }
    Ok(PreparedNativeRequest { report })
}

#[cfg(test)]
#[path = "native_protocol_tests.rs"]
mod tests;
