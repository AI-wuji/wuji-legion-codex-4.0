use crate::error::{Error, ErrorKind, Result};
use crate::graph::{ExactRef, Node};
use crate::native_protocol::{self, InvocationKind, PREPARATION_RELEASE, REQUESTED_MODEL};
use crate::native_wire::NativeObservationTracker;
use crate::policy::Workspace;
use crate::store::{bounded_file, check_clock, event_insert, wall_clock, LocalClaim, Store};
use crate::strict_json;
use rusqlite::{params, TransactionBehavior};
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

pub struct NativeDevelopmentPermit {
    scope: String,
    root: PathBuf,
}

impl NativeDevelopmentPermit {
    pub fn confirm_isolated_no_added_fee(approved_root: &Path, confirmation: &str) -> Result<Self> {
        if confirmation != "confirm-isolated-no-added-fee" {
            return Err(Error::new(ErrorKind::AuthorityDenied, "explicit operator confirmation required; business JSON cannot authorize generation"));
        }
        let workspace = Workspace::open(approved_root)?;
        let development_root = fs::canonicalize(env!("CARGO_MANIFEST_DIR"))?;
        if !workspace.root().starts_with(&development_root) || workspace.root() == development_root {
            return Err(Error::new(ErrorKind::ScopeDenied, "P2 native development must use a separate workspace within this project"));
        }
        let hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
        Ok(Self { scope: format!("project:{}", &hash[..24]), root: workspace.root().to_owned() })
    }

    pub(crate) fn check_scope(&self, workspace: &Workspace, scope: &str) -> Result<()> {
        if self.root != workspace.root() || self.scope != scope {
            return Err(Error::new(ErrorKind::ScopeDenied, "native permit cannot be replayed in another workspace"));
        }
        Ok(())
    }

    pub(crate) fn check_node(&self, workspace: &Workspace, scope: &str, node: &Node) -> Result<()> {
        self.check_scope(workspace, scope)?;
        let role = native_protocol::check_node(workspace, scope, node)?;
        let owner = match role["kind"].as_str() {
            Some("engineering") => "native-engineering",
            Some("validation") => "native-validation",
            _ => return Err(Error::new(ErrorKind::Reference, "only the two P2 bounded candidates are allowed")),
        };
        if node.owner != owner || node.write_roots.len() != 1 || node.read_roots.len() != node.inputs.len() {
            return Err(Error::new(ErrorKind::AuthorityDenied, "native candidate requires its exact owner, one new output and complete bounded inputs"));
        }
        for path in &node.read_roots {
            let bytes = bounded_file(&workspace.output(Path::new(path))?)?;
            let hash = strict_json::sha256(&bytes);
            if !node.inputs.iter().any(|input| input.sha256 == hash) {
                return Err(Error::new(ErrorKind::Reference, "native read file is not bound to an adopted input hash"));
            }
        }
        Ok(())
    }
}

pub struct NativeDriverPaths {
    python: PathBuf,
    codex: PathBuf,
    catalog: PathBuf,
}

impl NativeDriverPaths {
    pub fn new(python: &Path, codex: &Path, catalog: &Path) -> Result<Self> {
        for path in [python, codex, catalog] {
            if !path.is_absolute() || !path.is_file() {
                return Err(Error::new(ErrorKind::PathDenied, "native driver paths must be explicit existing absolute files"));
            }
        }
        let catalog = fs::canonicalize(catalog)?;
        if !catalog.starts_with(fs::canonicalize(env!("CARGO_MANIFEST_DIR"))?) {
            return Err(Error::new(ErrorKind::PathDenied, "isolated catalog must remain in the development project"));
        }
        let document = strict_json::parse(&bounded_file(&catalog)?)?;
        let models = document["models"].as_array().ok_or_else(|| Error::new(ErrorKind::Shape, "isolated catalog requires models"))?;
        if models.len() != 1 || models[0]["slug"] != REQUESTED_MODEL {
            return Err(Error::new(ErrorKind::ScopeDenied, "isolated catalog must preserve the requested model without fallback"));
        }
        Ok(Self { python: fs::canonicalize(python)?, codex: fs::canonicalize(codex)?, catalog })
    }
}

struct OwnedNativeResult {
    report: Value,
    observation: Value,
    transport_provenance: Value,
    text: Vec<u8>,
}

fn protocol_frame_without_driver_metadata(frame: &Value, index: usize) -> Result<(Value, Option<Value>)> {
    let object = frame.as_object().ok_or_else(|| Error::new(ErrorKind::Shape, "native driver observation must be an object"))?;
    let mut protocol = object.clone();
    let provenance = protocol.remove("transport_provenance");
    let Some(provenance) = provenance else {
        return Ok((Value::Object(protocol), None));
    };
    if object.contains_key("method") || !object.contains_key("id") {
        return Err(Error::new(ErrorKind::Shape, "transport_provenance is allowed only on reconstructed RPC responses"));
    }
    let provenance_object = provenance.as_object().ok_or_else(|| Error::new(ErrorKind::Shape, "transport_provenance must be an object"))?;
    if provenance_object.keys().any(|key| !["source", "envelope", "request_id_known"].contains(&key.as_str()))
        || provenance_object.len() != 3
        || provenance_object.get("source").and_then(Value::as_str) != Some("NativeSession.request")
        || provenance_object.get("envelope").and_then(Value::as_str) != Some("reconstructed")
        || provenance_object.get("request_id_known") != Some(&Value::Bool(true))
    {
        return Err(Error::new(ErrorKind::Shape, "transport_provenance is not the bounded native driver's declared reconstruction metadata"));
    }
    Ok((
        Value::Object(protocol),
        Some(json!({
            "frame_index": index,
            "request_id": object.get("id"),
            "source": provenance_object["source"],
            "envelope": provenance_object["envelope"],
            "request_id_known": provenance_object["request_id_known"],
            "authority": "metadata_only",
            "used_for_protocol_matching": false,
        })),
    ))
}

impl OwnedNativeResult {
    fn from_driver(report: Value, effort: &str) -> Result<Self> {
        let frames = report["observations"].as_array().ok_or_else(|| Error::new(ErrorKind::HostUnknown, "owned native driver omitted transport observations"))?;
        let mut tracker = NativeObservationTracker::new(REQUESTED_MODEL, effort, 1, 2)?;
        let mut transport_provenance = Vec::new();
        for (index, frame) in frames.iter().enumerate() {
            let (protocol_frame, provenance) = protocol_frame_without_driver_metadata(frame, index)?;
            if let Some(provenance) = provenance { transport_provenance.push(provenance); }
            tracker.observe_frame(&protocol_frame)?;
        }
        let observation = tracker.report();
        if observation["turn_completed_observed"] != true || observation["turn_status"] != "completed" {
            let status = report["status"].as_str().unwrap_or("unknown");
            let phase = report["failure_phase"].as_str().unwrap_or("unknown");
            let detail = report["failure_detail"].as_str().unwrap_or("no bounded driver detail");
            return Err(Error::new(ErrorKind::UnknownSubmission, format!("no successful matched native completion; status={status}; phase={phase}; detail={detail}; no redispatch")));
        }
        if report["thread_id"] != observation["thread_id"] || report["turn_id"] != observation["turn_id"] {
            return Err(Error::new(ErrorKind::Reference, "owned driver result has conflicting native identities"));
        }
        let text = report["generated_text"].as_str().ok_or_else(|| Error::new(ErrorKind::Shape, "native generated text required"))?.as_bytes().to_vec();
        if text.is_empty() || text.len() > strict_json::MAX_INPUT_BYTES {
            return Err(Error::new(ErrorKind::BudgetExhausted, "native artifact must contain 1..1048576 UTF-8 bytes"));
        }
        Ok(Self { report, observation, transport_provenance: json!({
            "schema_version": 1,
            "authority": "metadata_only",
            "used_for_protocol_matching": false,
            "records": transport_provenance,
        }), text })
    }
}

fn invoke_owned(paths: &NativeDriverPaths, root: &Path, thread_params: &Value, turn_params: &Value) -> Result<Value> {
    let project = Path::new(env!("CARGO_MANIFEST_DIR"));
    for (relative, expected) in [
        ("tools/native_task_driver.py", include_bytes!("../tools/native_task_driver.py").as_slice()),
        ("tools/native_host_session.py", include_bytes!("../tools/native_host_session.py").as_slice()),
    ] {
        if fs::read(project.join(relative))? != expected {
            return Err(Error::new(ErrorKind::HashMismatch, "native driver source changed after build; rebuild native execution before execution"));
        }
    }
    let bootstrap = r#"import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'tools'))
from native_host_session import NativeSession
from native_task_driver import run_task
request = json.loads(sys.stdin.buffer.read(1048577))
session = NativeSession([sys.argv[2], '-c', 'model_catalog_json=' + json.dumps(sys.argv[3]), 'app-server'], Path(sys.argv[4]))
result = run_task(session, request['thread_params'], request['turn_params'], timeout=180, close_timeout=90)
print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
"#;
    let mut command = Command::new(&paths.python);
    command.args(["-B", "-c", bootstrap]).arg(project).arg(&paths.codex).arg(&paths.catalog).arg(root)
        .current_dir(root).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let payload = strict_json::canonical(&json!({"thread_params":thread_params,"turn_params":turn_params}))?;
    if payload.len() > strict_json::MAX_INPUT_BYTES {
        return Err(Error::new(ErrorKind::BudgetExhausted, "native request exceeds bounded transport size"));
    }
    let mut child = command.spawn()?;
    let stdout = child.stdout.take().ok_or_else(|| Error::new(ErrorKind::Io, "owned stdout missing"))?;
    let stderr = child.stderr.take().ok_or_else(|| Error::new(ErrorKind::Io, "owned stderr missing"))?;
    let (sender, receiver) = mpsc::sync_channel(1);
    let output_reader = thread::spawn(move || {
        let mut output = Vec::new();
        let result = stdout.take(strict_json::MAX_INPUT_BYTES as u64 + 1).read_to_end(&mut output).map(|_| output);
        let _ = sender.send(result);
    });
    let error_reader = thread::spawn(move || {
        let mut reader = stderr;
        let mut buffer = [0u8; 4096];
        while matches!(reader.read(&mut buffer), Ok(count) if count > 0) {}
    });
    let write_result = child.stdin.take().ok_or_else(|| Error::new(ErrorKind::Io, "owned stdin missing"))?.write_all(&payload);
    let observed = if write_result.is_ok() { receiver.recv_timeout(Duration::from_secs(310)).ok() } else { None };
    if observed.is_none() { let _ = child.kill(); }
    let exit = child.wait()?;
    let _ = output_reader.join();
    let _ = error_reader.join();
    let output = observed.ok_or_else(|| Error::new(ErrorKind::UnknownSubmission, "owned native driver timed out or submission is unknown; no retry"))??;
    if !exit.success() { return Err(Error::new(ErrorKind::UnknownSubmission, "owned native driver failed; no raw stderr or automatic retry")); }
    strict_json::parse_protocol(&output)
}

impl Store {
    pub fn register_native_input(&mut self, permit: &NativeDevelopmentPermit, id: &str, input: &Path) -> Result<ExactRef> {
        permit.check_scope(&self.workspace, &self.scope)?;
        self.register_input_for_release(id, input, PREPARATION_RELEASE)
    }

    pub fn plan_native_development(&mut self, permit: &NativeDevelopmentPermit, envelope: &Value) -> Result<Value> {
        permit.check_scope(&self.workspace, &self.scope)?;
        self.plan_internal(envelope, Some(permit))
    }

    /// Execute an explicitly user-requested Sol high/xhigh upgrade target in an isolated host.
    /// This API does not classify task difficulty, know the current conversation selection,
    /// or authorize downgrading it. Text inheritance requires a trusted baseline handoff
    /// and is rejected before evidence refresh, claims, writes or host startup.
    pub fn run_native_development(&mut self, permit: &NativeDevelopmentPermit, paths: &NativeDriverPaths, task: &str, node: &str, kind: InvocationKind) -> Result<Value> {
        if kind == InvocationKind::Text {
            return Err(Error::new(ErrorKind::HostUnknown, "Text inheritance requires a trusted current-conversation model/effort baseline handoff; this independent CLI host cannot know it; no disk-default or Sol medium fallback, no side effects or host startup"));
        }
        permit.check_scope(&self.workspace, &self.scope)?;
        self.refresh_local_evidence()?;
        let plan: String = self.connection.query_row("SELECT envelope_json FROM task_plans WHERE task_id=?1 AND graph_revision=(SELECT graph_revision FROM tasks WHERE id=?1 AND scope=?2)", params![task,self.scope], |row| row.get(0))?;
        let envelope = strict_json::parse(plan.as_bytes())?;
        let prepared = native_protocol::prepare(self.workspace.root(), &envelope, node, kind)?;
        let mut thread_params = prepared.report()["candidate_messages"]["thread_start"]["params"].clone();
        thread_params["config"] = json!({"model_reasoning_effort":kind.requested_effort(),"features.multi_agent":false,"features.shell_tool":false,"web_search":"disabled"});
        let mut turn_params = prepared.report()["candidate_messages"]["turn_start_unbound"]["params"].clone();
        let specification: Node = serde_json::from_value(envelope["payload"]["nodes"].as_array().unwrap().iter().find(|value| value["id"] == node).ok_or_else(|| Error::new(ErrorKind::Reference, "native node missing"))?.clone())?;
        let mut context = Vec::new();
        for relative in &specification.read_roots {
            let bytes = bounded_file(&self.workspace.output(Path::new(relative))?)?;
            context.push(json!({"path":relative,"sha256":strict_json::sha256(&bytes),"content":std::str::from_utf8(&bytes).map_err(|_| Error::new(ErrorKind::Shape, "native input must be UTF-8"))?}));
        }
        let mut candidates = Vec::new();
        if specification.owner == "native-validation" {
            let mut statement = self.connection.prepare("SELECT a.path,a.sha256,n.spec_json FROM dependencies d JOIN artifacts a ON a.task_id=d.task_id AND a.node_id=d.source JOIN nodes n ON n.task_id=d.task_id AND n.id=d.source WHERE d.task_id=?1 AND d.target=?2 AND a.state IN ('produced','adopted')")?;
            let rows: Vec<(String,String,String)> = statement.query_map(params![task,node], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?.collect::<std::result::Result<_,_>>()?;
            for (path, hash, source_specification) in rows {
                let bytes = bounded_file(&self.workspace.output(Path::new(&path))?)?;
                if strict_json::sha256(&bytes) != hash { return Err(Error::new(ErrorKind::ValidationStale, "review candidate changed")); }
                let source: Node = serde_json::from_str(&source_specification)?;
                candidates.push(json!({"path":path,"sha256":hash,"content":std::str::from_utf8(&bytes).map_err(|_| Error::new(ErrorKind::Shape, "review candidate UTF-8 required"))?,"required_checks":source.acceptance_ids}));
            }
        }
        let instruction = if specification.owner == "native-validation" {
            "Independently review the supplied candidate and adopted inputs. Return only JSON containing verdict (pass or fail), artifact_hash (the candidate sha256), and check_results (all candidate and reviewer required-check IDs mapped to true or false). Missing real regression or behavior evidence must be false, not invented. No grade, wording or model-output field grants authority or closes the host. Do not write files or run tools."
        } else {
            "Return only the complete UTF-8 content of the single assigned output file, without fences or claims of file writes, validation, authority or host exit. This is an explicitly authorized P2 isolated proposal; the Rust owner materializes and independently validates it."
        };
        let prompt = json!({"instruction":instruction,"task_id":task,"graph_revision":envelope["metadata"]["revision"],"node":specification,"adopted_inputs":context,"review_candidates":candidates});
        turn_params["input"] = json!([{"type":"text","text":String::from_utf8(strict_json::canonical(&prompt)?).unwrap()}]);
        let claim = self.claim_internal(task, node, Some(permit))?;
        let target = self.workspace.output(Path::new(&specification.write_roots[0]))?;
        {
            let _catalog_guard = self.hold_task_catalog(task)?;
            let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let now = wall_clock()?;
            check_clock(&transaction, now)?;
            Self::current_claim(&transaction, &claim, now)?;
            Self::check_inputs(&transaction, &self.workspace, &self.scope, &specification)?;
            transaction.execute("UPDATE invocations SET state='dispatching',expected_output_path=?2 WHERE attempt_id=?1 AND state='intent'", params![claim.attempt_id,target.to_string_lossy()])?;
            transaction.execute("UPDATE attempts SET state='dispatched' WHERE id=?1", [&claim.attempt_id])?;
            transaction.execute("UPDATE nodes SET state='running' WHERE task_id=?1 AND id=?2", params![task,node])?;
            transaction.execute("UPDATE slots SET state='open' WHERE attempt_id=?1 AND host_class='codex_native'", [&claim.attempt_id])?;
            transaction.commit()?;
        }
        let result = invoke_owned(paths, self.workspace.root(), &thread_params, &turn_params)
            .and_then(|report| OwnedNativeResult::from_driver(report, kind.requested_effort()))
            .and_then(|result| self.record_native_proposal(&claim, &specification, &target, result));
        match result {
            Ok(receipt) => Ok(receipt),
            Err(error) => {
                let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
                transaction.execute("UPDATE invocations SET state='unknown' WHERE attempt_id=?1", [&claim.attempt_id])?;
                transaction.execute("UPDATE attempts SET state='unknown' WHERE id=?1 AND state='dispatched'", [&claim.attempt_id])?;
                transaction.execute("UPDATE slots SET state='release_unverified' WHERE attempt_id=?1 AND host_class='codex_native'", [&claim.attempt_id])?;
                transaction.commit()?;
                Err(error)
            }
        }
    }

    fn record_native_proposal(&mut self, claim: &LocalClaim, specification: &Node, target: &Path, result: OwnedNativeResult) -> Result<Value> {
        let hash = strict_json::sha256(&result.text);
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        Self::current_claim(&transaction, claim, now)?;
        Self::check_inputs(&transaction, &self.workspace, &self.scope, specification)?;
        if self.workspace.output(Path::new(&specification.write_roots[0]))? != target {
            return Err(Error::new(ErrorKind::PathDenied, "native output mapping changed before materialization"));
        }
        let mut file = OpenOptions::new().write(true).create_new(true).open(target)?;
        file.write_all(&result.text)?;
        file.sync_all()?;
        if bounded_file(target)? != result.text {
            return Err(Error::new(ErrorKind::ValidationStale, "native output changed during materialization"));
        }
        let closed = result.observation["thread_closed_observed"] == true;
        let receipt = json!({"attempt_id":claim.attempt_id,"task_id":claim.task_id,"node_id":claim.node_id,"state":"produced","host_class":"codex_native","path":target,"sha256":hash,"bytes":result.text.len(),"transport_observation":result.observation,"driver_transport_provenance":result.transport_provenance,"thread_closed_observed":closed,"owned_process_exit":result.report.get("owned_process_exit"),"native_generation_observed":true,"independent_acceptance":"pending","formal_role_activated":false,"backend_effective_model":"unknown","backend_effective_effort":"unknown"});
        transaction.execute("INSERT INTO artifacts(id,task_id,node_id,attempt_id,path,sha256,bytes,revision,producer,state) VALUES(?1,?2,?3,?1,?4,?5,?6,1,?7,'produced')", params![claim.attempt_id,claim.task_id,claim.node_id,target.to_string_lossy(),hash,result.text.len() as i64,claim.owner])?;
        transaction.execute("UPDATE invocations SET state='observed',result_hash=?2,expected_output_hash=?2,expected_output_bytes=?3 WHERE attempt_id=?1", params![claim.attempt_id,hash,result.text.len() as i64])?;
        transaction.execute("UPDATE attempts SET state='produced' WHERE id=?1", [&claim.attempt_id])?;
        transaction.execute("UPDATE nodes SET state='produced' WHERE task_id=?1 AND id=?2", params![claim.task_id,claim.node_id])?;
        transaction.execute("UPDATE slots SET state=?2,close_evidence=?3 WHERE attempt_id=?1 AND host_class='codex_native'", params![claim.attempt_id,if closed { "closed" } else { "release_unverified" },if closed { Some(serde_json::to_string(&receipt["transport_observation"])?)} else { None }])?;
        if closed { transaction.execute("UPDATE leases SET state='ended' WHERE attempt_id=?1", [&claim.attempt_id])?; }
        event_insert(&transaction, &format!("native-produced:{}",claim.attempt_id), &claim.task_id, &strict_json::digest(&receipt)?, &receipt)?;
        transaction.commit()?;
        Ok(receipt)
    }

    pub fn accept_native_development(&mut self, permit: &NativeDevelopmentPermit, task: &str, producer: &str, reviewer: &str) -> Result<Value> {
        permit.check_scope(&self.workspace, &self.scope)?;
        self.refresh_local_evidence()?;
        if producer == reviewer { return Err(Error::new(ErrorKind::SelfReview, "native producer cannot review itself")); }
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = wall_clock()?;
        check_clock(&transaction, now)?;
        let (revision,deadline,status): (i64,i64,String) = transaction.query_row("SELECT graph_revision,deadline_ms,status FROM tasks WHERE id=?1 AND scope=?2", params![task,self.scope], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?;
        if now >= deadline || ["cancel_requested","cancelled"].contains(&status.as_str()) { return Err(Error::new(ErrorKind::StaleReceipt, "native acceptance task expired or cancelled")); }
        let mut artifacts = Vec::new();
        let mut threads = Vec::new();
        let mut required = Vec::new();
        for (node_id,expected_kind) in [(producer,"engineering"),(reviewer,"validation")] {
            let (attempt,path,hash,owner,spec_json,attempt_revision): (String,String,String,String,String,i64) = transaction.query_row("SELECT a.attempt_id,a.path,a.sha256,a.producer,n.spec_json,t.graph_revision FROM artifacts a JOIN nodes n ON n.task_id=a.task_id AND n.id=a.node_id JOIN attempts t ON t.id=a.attempt_id JOIN slots s ON s.attempt_id=t.id WHERE a.task_id=?1 AND a.node_id=?2 AND a.state='produced' AND t.state='produced' AND s.host_class='codex_native'", params![task,node_id], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?)))?;
            if attempt_revision != revision { return Err(Error::new(ErrorKind::StaleReceipt, "native result belongs to old graph")); }
            let specification: Node = serde_json::from_str(&spec_json)?;
            let role = native_protocol::resolve_role(&specification, &self.scope)?;
            if role["kind"] != expected_kind || owner != specification.owner { return Err(Error::new(ErrorKind::SelfReview, "native reviewer identity or role mismatch")); }
            Self::check_inputs(&transaction, &self.workspace, &self.scope, &specification)?;
            let bytes = bounded_file(&self.workspace.output(Path::new(&path))?)?;
            if strict_json::sha256(&bytes) != hash { return Err(Error::new(ErrorKind::ValidationStale, "native artifact changed before independent acceptance")); }
            let event_json: String = transaction.query_row("SELECT result_json FROM events WHERE event_key=?1 AND task_id=?2", params![format!("native-produced:{attempt}"),task], |row| row.get(0))?;
            let event = strict_json::parse(event_json.as_bytes())?;
            if event["attempt_id"] != attempt || event["sha256"] != hash || event["native_generation_observed"] != true { return Err(Error::new(ErrorKind::HostUnknown, "native artifact has no matched trusted invocation event")); }
            let thread_id = event["transport_observation"]["thread_id"].as_str().filter(|value| !value.is_empty()).ok_or_else(|| Error::new(ErrorKind::HostUnknown, "matched native thread identity missing"))?;
            threads.push(thread_id.to_owned());
            required.extend(specification.acceptance_ids.clone());
            artifacts.push((attempt,path,hash,owner,bytes,specification.acceptance_ids));
        }
        if threads[0] == threads[1] || artifacts[0].3 == artifacts[1].3 { return Err(Error::new(ErrorKind::SelfReview, "native validation requires a different real thread and owner")); }
        let dependency: i64 = transaction.query_row("SELECT count(*) FROM dependencies WHERE task_id=?1 AND source=?2 AND target=?3", params![task,producer,reviewer], |row| row.get(0))?;
        if dependency != 1 { return Err(Error::new(ErrorKind::DependencyNotAccepted, "reviewer was not bound to this candidate producer")); }
        let review = strict_json::parse(&artifacts[1].4)?;
        let checks = review["check_results"].as_object().ok_or_else(|| Error::new(ErrorKind::Shape, "native review requires exact required-check results"))?;
        if review["verdict"] != "pass" || review["artifact_hash"] != artifacts[0].2 || checks.len() != required.len() || required.iter().any(|requirement| checks.get(requirement) != Some(&Value::Bool(true))) {
            return Err(Error::new(ErrorKind::ValidationStale, "native independent review failed, omitted evidence or reviewed a different artifact"));
        }
        for (artifact,node_id) in artifacts.iter().zip([producer,reviewer]) {
            if bounded_file(&self.workspace.output(Path::new(&artifact.1))?)? != artifact.4 { return Err(Error::new(ErrorKind::ValidationStale, "native artifact changed before acceptance commit")); }
            let validation_id = format!("native-review:{}:{}",artifacts[1].0,artifact.0);
            transaction.execute("INSERT INTO validations(id,artifact_id,artifact_hash,graph_revision,validator,requirement_ids_json,verdict) VALUES(?1,?2,?3,?4,?5,?6,'pass')", params![validation_id,artifact.0,artifact.2,revision,artifacts[1].3,serde_json::to_string(&artifact.5)?])?;
            for requirement in &artifact.5 {
                transaction.execute("INSERT INTO acceptance_links(task_id,node_id,requirement_id,validation_id) VALUES(?1,?2,?3,?4)", params![task,node_id,requirement,validation_id])?;
            }
            transaction.execute("UPDATE artifacts SET state='adopted' WHERE id=?1", [&artifact.0])?;
            transaction.execute("UPDATE attempts SET state='accepted' WHERE id=?1", [&artifact.0])?;
            transaction.execute("UPDATE nodes SET state='succeeded' WHERE task_id=?1 AND id=?2", params![task,node_id])?;
        }
        Self::finalize_local_task(&transaction, task)?;
        let receipt = json!({"task_id":task,"producer":producer,"reviewer":reviewer,"artifact_hash":artifacts[0].2,"review_hash":artifacts[1].2,"native_threads":threads,"independent_model_review":"pass","required_checks":required,"scope":"P2 isolated bounded task only; not universal professional effectiveness or backend attestation","formal_experts_activated":0});
        event_insert(&transaction, &format!("native-accept:{}:{}",artifacts[0].0,artifacts[1].0), task, &strict_json::digest(&receipt)?, &receipt)?;
        transaction.commit()?;
        Ok(receipt)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn text_execution_fails_closed_before_refresh_claims_or_host_startup() {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/core-test-workspaces")
            .join(format!("native-text-rejected-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let mut store = Store::open(&root).unwrap();
        let permit = NativeDevelopmentPermit::confirm_isolated_no_added_fee(&root, "confirm-isolated-no-added-fee").unwrap();
        fs::write(root.join("input.txt"), b"registered original").unwrap();
        store.register_native_input(&permit, "user/input", Path::new("input.txt")).unwrap();
        // A refresh would invalidate this registered evidence. Text must reject before it.
        fs::write(root.join("input.txt"), b"changed after registration").unwrap();
        let before: i64 = store.connection.query_row("SELECT total_changes()", [], |row| row.get(0)).unwrap();
        let database = root.join(".wuji4/state.sqlite");
        let before_database = fs::read(&database).unwrap();
        // Intentionally missing executables/catalog: no process is started by this test.
        let paths = NativeDriverPaths {
            python: root.join("must-not-start-python.exe"),
            codex: root.join("must-not-start-codex.exe"),
            catalog: root.join("must-not-read-catalog.json"),
        };
        let error = store.run_native_development(&permit, &paths, "unplanned-task", "unplanned-node", InvocationKind::Text).unwrap_err();
        assert_eq!(error.kind, ErrorKind::HostUnknown);
        assert!(error.detail.contains("trusted current-conversation model/effort baseline handoff"));
        assert!(error.detail.contains("no disk-default or Sol medium fallback"));
        let after: i64 = store.connection.query_row("SELECT total_changes()", [], |row| row.get(0)).unwrap();
        assert_eq!(before, after, "no evidence refresh, claims or DB changes");
        assert_eq!(fs::read(&database).unwrap(), before_database);
        assert_eq!(fs::read(root.join("input.txt")).unwrap(), b"changed after registration");
        for table in ["tasks", "attempts", "invocations", "slots", "artifacts"] {
            let count: i64 = store.connection.query_row(&format!("SELECT count(*) FROM {table}"), [], |row| row.get(0)).unwrap();
            assert_eq!(count, 0, "Text must not allocate or dispatch: {table}");
        }
        assert!(!paths.python.exists());
        assert!(!paths.codex.exists());
        assert!(!paths.catalog.exists());
    }
}
