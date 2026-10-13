use crate::error::{Error, ErrorKind, Result};
use crate::strict_json;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

const MODEL: &str = "gpt-6.1-sol";
const MAX_ID_BYTES: usize = 256;

pub struct NativeObservationTracker {
    requested_effort: String,
    thread_request_id: u64,
    turn_request_id: u64,
    thread_id: Option<String>,
    turn_id: Option<String>,
    pending_turn_id: Option<String>,
    declared_model: Option<String>,
    declared_effort: Option<String>,
    declared_provider: Option<String>,
    completed_status: Option<String>,
    events: BTreeMap<&'static str, String>,
    failure: Option<(ErrorKind, String)>,
}

impl NativeObservationTracker {
    pub fn new(requested_model: &str, requested_effort: &str, thread_request_id: u64, turn_request_id: u64) -> Result<Self> {
        if requested_model != MODEL || !matches!(requested_effort, "medium" | "high" | "xhigh") {
            return Err(Error::new(ErrorKind::ScopeDenied, "native observation requires pinned model and medium/high/xhigh; no fallback"));
        }
        if thread_request_id == turn_request_id {
            return Err(Error::new(ErrorKind::Shape, "thread/start and turn/start RPC ids must be distinct"));
        }
        Ok(Self {
            requested_effort: requested_effort.into(), thread_request_id, turn_request_id,
            thread_id: None, turn_id: None, pending_turn_id: None,
            declared_model: None, declared_effort: None, declared_provider: None,
            completed_status: None, events: BTreeMap::new(), failure: None,
        })
    }

    pub fn observe_frame(&mut self, frame: &Value) -> Result<()> {
        let result = self.observe(frame);
        if let Err(error) = &result {
            if self.failure.is_none() { self.failure = Some((error.kind, error.detail.clone())); }
        }
        result
    }

    pub fn report(&self) -> Value {
        let turn_bound = self.turn_id.is_some();
        json!({
            "schema_version": 1,
            "observation_kind": "native_protocol_transport_observation_only",
            "transport_provenance": "caller_must_supply_trusted_transport_frames_not_authenticated_here",
            "frame_ingress_requirement": "trusted transport must strictly parse raw bytes; Value cannot recover duplicate JSON keys",
            "runtime_admission": false,
            "store_admission": false,
            "authority_granted": false,
            "requested_model": MODEL,
            "requested_effort": self.requested_effort,
            "thread_request_id": self.thread_request_id,
            "turn_request_id": self.turn_request_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "declared_model": self.declared_model.as_deref().unwrap_or("unknown"),
            "declared_effort": self.declared_effort.as_deref().unwrap_or("unknown"),
            "declared_provider": self.declared_provider.as_deref().unwrap_or("unknown"),
            "declaration_scope": "thread/start response only; not effective provider or per-turn execution telemetry",
            "effective_model": "unknown",
            "effective_effort": "unknown",
            "effective_provider": "unknown",
            "effective_fields_reason": "selected 0.160.0 turn schema has no effective model/provider/effort fields",
            "thread_start_response_observed": self.thread_id.is_some(),
            "turn_start_response_observed": turn_bound,
            "turn_started_observed": turn_bound && self.events.contains_key("turn/started"),
            "turn_completed_observed": turn_bound && self.events.contains_key("turn/completed"),
            "turn_status": if turn_bound { self.completed_status.as_deref().unwrap_or("unknown") } else { "unknown" },
            "thread_closed_observed": self.events.contains_key("thread/closed"),
            "close_scope": "matching thread/closed notification only; no release permission granted",
            "reroute_observed": self.events.contains_key("model/rerouted"),
            "fail_closed": self.failure.is_some(),
            "failure": self.failure.as_ref().map(|(kind, detail)| json!({"kind": format!("{kind:?}"), "detail": detail})),
            "effective_native_quota": "unknown",
            "built_in_subagent_quota": "unknown",
            "fee_observation": "unknown"
        })
    }

    fn duplicate(&self, event: &'static str, digest: &str) -> Result<bool> {
        match self.events.get(event) {
            Some(previous) if previous == digest => Ok(true),
            Some(_) => Err(Error::new(ErrorKind::EventConflict, "conflicting repeated native event")),
            None => Ok(false),
        }
    }

    fn thread_response(&mut self, payload: &Value) -> Result<()> {
        object_value(payload, "thread/start result")?;
        let thread = payload.get("thread").ok_or_else(|| Error::new(ErrorKind::Shape, "thread/start result requires thread"))?;
        object_value(thread, "thread")?;
        let thread_id = text(thread, "id")?;
        let model = text(payload, "model")?;
        let provider = text(payload, "modelProvider")?;
        let thread_provider = text(thread, "modelProvider")?;
        let effort = optional_text(payload, "reasoningEffort")?;
        if model != MODEL || effort.is_some_and(|value| value != self.requested_effort) {
            return Err(Error::new(ErrorKind::ScopeDenied, "thread/start declaration mismatches pinned request; no fallback"));
        }
        if thread_provider != provider {
            return Err(Error::new(ErrorKind::EventConflict, "thread/start provider declarations conflict"));
        }
        self.thread_id = Some(thread_id.into());
        self.declared_model = Some(model.into());
        self.declared_effort = effort.map(String::from);
        self.declared_provider = Some(provider.into());
        Ok(())
    }

    fn turn_response(&mut self, payload: &Value) -> Result<()> {
        self.require_thread()?;
        object_value(payload, "turn/start result")?;
        let turn = payload.get("turn").ok_or_else(|| Error::new(ErrorKind::Shape, "turn/start result requires turn"))?;
        let (turn_id, _status) = turn_fields(turn)?;
        self.match_turn(turn_id)?;
        if let Some(thread_id) = payload.get("threadId") {
            self.match_thread(thread_id.as_str().ok_or_else(|| Error::new(ErrorKind::Shape, "threadId must be a string"))?)?;
        }
        self.turn_id = Some(turn_id.into());
        Ok(())
    }

    fn notification(&mut self, method: &str, params: &Value) -> Result<()> {
        let event = match method {
            "turn/started" => "turn/started", "turn/completed" => "turn/completed",
            "thread/closed" => "thread/closed", "model/rerouted" => "model/rerouted",
            _ => return Ok(()),
        };
        let digest = strict_json::sha256(&strict_json::canonical_protocol(params)?);
        if self.duplicate(event, &digest)? {
            return if event == "model/rerouted" { Err(Error::new(ErrorKind::ScopeDenied, "native model reroute observed; no fallback")) } else { Ok(()) };
        }
        self.match_thread(text(params, "threadId")?)?;
        if event == "thread/closed" {
            keys(object_value(params, "thread/closed params")?, &["threadId"])?;
        } else if event == "model/rerouted" {
            if self.turn_id.is_none() {
                return Err(Error::new(ErrorKind::HostUnknown, "model reroute lacks matched turn/start RPC binding; no fallback"));
            }
            self.match_turn(text(params, "turnId")?)?;
            text(params, "fromModel")?;
            text(params, "toModel")?;
            if text(params, "reason")? != "highRiskCyberActivity" {
                return Err(Error::new(ErrorKind::Shape, "unknown 0.160.0 model reroute reason"));
            }
            self.events.insert(event, digest);
            return Err(Error::new(ErrorKind::ScopeDenied, "native model reroute observed; no fallback"));
        } else {
            let turn = params.get("turn").ok_or_else(|| Error::new(ErrorKind::Shape, "turn notification requires turn"))?;
            let (turn_id, status) = turn_fields(turn)?;
            self.match_turn(turn_id)?;
            if (event == "turn/started" && status != "inProgress") || (event == "turn/completed" && status == "inProgress") {
                return Err(Error::new(ErrorKind::Shape, "turn notification status mismatches event"));
            }
            if self.events.contains_key("thread/closed") {
                return Err(Error::new(ErrorKind::EventConflict, "new turn event after matched thread close"));
            }
            if self.turn_id.is_none() { self.pending_turn_id = Some(turn_id.into()); }
            if event == "turn/completed" { self.completed_status = Some(status.into()); }
        }
        self.events.insert(event, digest);
        Ok(())
    }

    fn require_thread(&self) -> Result<&str> {
        self.thread_id.as_deref().ok_or_else(|| Error::new(ErrorKind::HostUnknown, "thread/start RPC binding not yet observed"))
    }

    fn match_thread(&self, thread_id: &str) -> Result<()> {
        if self.require_thread()? != thread_id {
            return Err(Error::new(ErrorKind::Reference, "native event threadId mismatch"));
        }
        Ok(())
    }

    fn match_turn(&self, turn_id: &str) -> Result<()> {
        if self.turn_id.as_ref().or(self.pending_turn_id.as_ref()).is_some_and(|expected| expected != turn_id) {
            return Err(Error::new(ErrorKind::Reference, "native event turnId mismatch"));
        }
        Ok(())
    }

    fn observe(&mut self, frame: &Value) -> Result<()> {
        let bytes = strict_json::canonical_protocol(frame)?;
        if bytes.len() > strict_json::MAX_INPUT_BYTES {
            return Err(Error::new(ErrorKind::BudgetExhausted, "native frame exceeds 1 MiB"));
        }
        let object = object_value(frame, "native frame")?;
        if let Some(version) = object.get("jsonrpc") {
            if version != "2.0" { return Err(Error::new(ErrorKind::Shape, "unsupported JSON-RPC version")); }
        }
        if object.contains_key("method") {
            keys(object, &["method", "params", "jsonrpc", "emittedAtMs"])?;
            if let Some(emitted_at) = object.get("emittedAtMs") {
                if emitted_at.as_u64().is_none() { return Err(Error::new(ErrorKind::Shape, "emittedAtMs must be an unsigned transport timestamp")); }
            }
            let method = text(frame, "method")?;
            let params = object.get("params").ok_or_else(|| Error::new(ErrorKind::Shape, "notification params required"))?;
            object_value(params, "notification params")?;
            return self.notification(method, params);
        }
        keys(object, &["id", "result", "error", "jsonrpc"])?;
        let request_id = object.get("id").and_then(Value::as_u64)
            .ok_or_else(|| Error::new(ErrorKind::Shape, "native response requires an unsigned integer RPC id"))?;
        if object.contains_key("result") == object.contains_key("error") {
            return Err(Error::new(ErrorKind::Shape, "response requires exactly one result or error"));
        }
        let event = if request_id == self.thread_request_id { "thread/start response" }
            else if request_id == self.turn_request_id { "turn/start response" }
            else { return Ok(()); };
        let payload = object.get("result").or_else(|| object.get("error")).unwrap();
        let digest = strict_json::sha256(&strict_json::canonical_protocol(&json!({"result": object.get("result"), "error": object.get("error")}))?);
        if self.duplicate(event, &digest)? {
            return if object.contains_key("error") { Err(Error::new(ErrorKind::HostUnknown, "matching native RPC error; no close observed")) } else { Ok(()) };
        }
        if object.contains_key("error") {
            object_value(payload, "RPC error")?;
            if payload.get("code").and_then(Value::as_i64).is_none() || payload.get("message").and_then(Value::as_str).is_none() {
                return Err(Error::new(ErrorKind::Shape, "RPC error requires integer code and string message"));
            }
            self.events.insert(event, digest);
            return Err(Error::new(ErrorKind::HostUnknown, "matching native RPC error; no close observed"));
        }
        if request_id == self.thread_request_id { self.thread_response(payload)?; }
        else { self.turn_response(payload)?; }
        self.events.insert(event, digest);
        Ok(())
    }
}

fn object_value<'value>(value: &'value Value, label: &str) -> Result<&'value Map<String, Value>> {
    value.as_object().ok_or_else(|| Error::new(ErrorKind::Shape, format!("{label} must be an object")))
}

fn keys(object: &Map<String, Value>, allowed: &[&str]) -> Result<()> {
    if object.keys().any(|key| !allowed.contains(&key.as_str())) {
        return Err(Error::new(ErrorKind::Shape, "unexpected native envelope or close field; business JSON is not transport authority"));
    }
    Ok(())
}

fn text<'value>(value: &'value Value, field: &str) -> Result<&'value str> {
    let text = value.get(field).and_then(Value::as_str)
        .ok_or_else(|| Error::new(ErrorKind::Shape, format!("{field} must be a string")))?;
    if text.is_empty() || text.len() > MAX_ID_BYTES {
        return Err(Error::new(ErrorKind::Shape, format!("{field} must contain 1..256 bytes")));
    }
    Ok(text)
}

fn optional_text<'value>(value: &'value Value, field: &str) -> Result<Option<&'value str>> {
    match value.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(_) => text(value, field).map(Some),
    }
}

fn turn_fields(turn: &Value) -> Result<(&str, &str)> {
    object_value(turn, "turn")?;
    let turn_id = text(turn, "id")?;
    let status = text(turn, "status")?;
    if !matches!(status, "inProgress" | "completed" | "interrupted" | "failed") || turn.get("items").and_then(Value::as_array).is_none() {
        return Err(Error::new(ErrorKind::Shape, "turn requires schema status and items array"));
    }
    Ok((turn_id, status))
}

#[cfg(test)]
#[path = "native_wire_tests.rs"]
mod tests;
