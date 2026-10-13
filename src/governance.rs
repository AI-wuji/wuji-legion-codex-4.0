use crate::error::{Error, ErrorKind, Result};
use crate::strict_json;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

const MAX_GOVERNANCE_TEXT: usize = 256;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceRecord {
    pub id: String,
    pub scope: String,
    pub locator: String,
    pub sha256: String,
    pub read_scope: String,
    pub license: String,
    pub version: String,
    pub license_evidence_ref: String,
}

impl SourceRecord {
    pub fn reference_key(&self) -> String { format!("{}::{}@{}", self.scope, self.id, self.version) }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LicensePolicy {
    pub scope: String,
    pub allowed_licenses: BTreeSet<String>,
    pub denied_licenses: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InFlightLock {
    pub task_id: String,
    pub scope: String,
    pub release: String,
    pub release_sha256: String,
    pub source_refs: Vec<String>,
    pub lock_sha256: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DeltaProposal {
    pub idempotency_key: String,
    pub scope: String,
    pub expected_revision: u64,
    pub operation: String,
    pub payload: Value,
    pub evidence_refs: Vec<String>,
}

#[derive(Debug, Default)]
pub struct GovernanceState {
    revisions: BTreeMap<String, u64>,
    events: BTreeMap<String, (String, Value)>,
    consumers: BTreeMap<String, BTreeSet<String>>,
    revoked: BTreeSet<String>,
    releases: BTreeMap<String, String>,
    source_admissions: BTreeMap<String, (String, SourceRecord)>,
    in_flight: BTreeMap<String, InFlightLock>,
    completed_tasks: BTreeSet<String>,
}

impl GovernanceState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register_consumer(&mut self, source: &str, consumer: &str) -> Result<()> {
        if source.is_empty() || consumer.is_empty() || source == consumer {
            return Err(Error::new(ErrorKind::Shape, "source and consumer must be distinct non-empty refs"));
        }
        self.consumers.entry(source.to_owned()).or_default().insert(consumer.to_owned());
        Ok(())
    }

    pub fn apply_delta(&mut self, proposal: &DeltaProposal) -> Result<Value> {
        if proposal.idempotency_key.is_empty() || proposal.scope.is_empty() || proposal.operation.is_empty() {
            return Err(Error::new(ErrorKind::Shape, "delta identity, scope and operation are required"));
        }
        if proposal.evidence_refs.is_empty() || proposal.evidence_refs.iter().any(String::is_empty) {
            return Err(Error::new(ErrorKind::Reference, "delta requires non-empty evidence refs"));
        }
        let payload_hash = strict_json::digest(&json!({
            "scope": proposal.scope,
            "expected_revision": proposal.expected_revision,
            "operation": proposal.operation,
            "payload": proposal.payload,
            "evidence_refs": proposal.evidence_refs,
        }))?;
        if let Some((stored_hash, result)) = self.events.get(&proposal.idempotency_key) {
            if stored_hash == &payload_hash {
                return Ok(result.clone());
            }
            return Err(Error::new(ErrorKind::EventConflict, "idempotency key has a different delta payload"));
        }
        let current = self.revisions.get(&proposal.scope).copied().unwrap_or(0);
        if proposal.expected_revision != current {
            return Err(Error::new(ErrorKind::RevisionConflict, "delta expected revision is stale"));
        }
        let next = current.checked_add(1).ok_or_else(|| Error::new(ErrorKind::RevisionConflict, "delta revision overflow"))?;
        self.revisions.insert(proposal.scope.clone(), next);
        let result = json!({
            "idempotency_key": proposal.idempotency_key,
            "scope": proposal.scope,
            "revision": next,
            "operation": proposal.operation,
            "payload_hash": payload_hash,
            "evidence_refs": proposal.evidence_refs,
            "state": "accepted_candidate",
        });
        self.events.insert(proposal.idempotency_key.clone(), (payload_hash, result.clone()));
        Ok(result)
    }

    pub fn impact_closure(&self, source: &str) -> Vec<String> {
        let mut visited = BTreeSet::new();
        let mut queue = VecDeque::from([source.to_owned()]);
        while let Some(current) = queue.pop_front() {
            if !visited.insert(current.clone()) {
                continue;
            }
            if let Some(children) = self.consumers.get(&current) {
                for child in children {
                    queue.push_back(child.clone());
                }
            }
        }
        visited.into_iter().collect()
    }

    pub fn revoke(&mut self, reference: &str) -> Result<()> {
        if reference.is_empty() {
            return Err(Error::new(ErrorKind::Shape, "revoked reference must be non-empty"));
        }
        self.revoked.insert(reference.to_owned());
        Ok(())
    }

    pub fn is_active(&self, reference: &str) -> bool {
        !self.revoked.contains(reference)
    }

    pub fn admit_source(
        &mut self,
        policy: &LicensePolicy,
        source: &SourceRecord,
        expected_revision: u64,
        idempotency_key: &str,
        evidence_refs: &[String],
    ) -> Result<Value> {
        validate_license_policy(policy)?;
        validate_source(source)?;
        validate_event_key(idempotency_key)?;
        validate_evidence_refs(evidence_refs)?;
        if policy.scope != source.scope {
            return Err(Error::new(ErrorKind::ScopeDenied, "source and license policy scopes must match"));
        }
        if policy.denied_licenses.contains(&source.license) || !policy.allowed_licenses.contains(&source.license) {
            return Err(Error::new(ErrorKind::AuthorityDenied, "source license is not admitted by the explicit policy"));
        }
        let source_ref = source.reference_key();
        let payload_hash = strict_json::digest(&json!({
            "operation": "admit-source", "policy": policy, "source": source,
            "expected_revision": expected_revision, "evidence_refs": evidence_refs,
        }))?;
        if let Some((stored_hash, result)) = self.events.get(idempotency_key) {
            if stored_hash == &payload_hash { return Ok(result.clone()); }
            return Err(Error::new(ErrorKind::EventConflict, "idempotency key has a different source admission"));
        }
        let current = self.revisions.get(&source.scope).copied().unwrap_or(0);
        if current != expected_revision {
            return Err(Error::new(ErrorKind::RevisionConflict, "source admission expected revision is stale"));
        }
        let source_hash = strict_json::digest(&serde_json::to_value(source)?)?;
        if let Some((existing_hash, existing)) = self.source_admissions.get(&source_ref) {
            if existing_hash == &source_hash && existing == source {
                return Err(Error::new(ErrorKind::EventConflict, "source version is already admitted with another event"));
            }
            return Err(Error::new(ErrorKind::HashMismatch, "source version identity was reused with different content"));
        }
        let next = current.checked_add(1).ok_or_else(|| Error::new(ErrorKind::RevisionConflict, "source revision overflow"))?;
        self.revisions.insert(source.scope.clone(), next);
        self.source_admissions.insert(source_ref.clone(), (source_hash.clone(), source.clone()));
        let result = json!({
            "source_ref": source_ref, "source": source, "license": source.license,
            "license_status": "allowed_by_explicit_policy", "revision": next,
            "source_hash": source_hash, "evidence_refs": evidence_refs,
            "state": "accepted_candidate", "runtime_admission": false,
        });
        self.events.insert(idempotency_key.to_owned(), (payload_hash, result.clone()));
        Ok(result)
    }

    pub fn begin_in_flight(
        &mut self,
        task_id: &str,
        scope: &str,
        release: &str,
        release_sha256: &str,
        source_refs: &[String],
        idempotency_key: &str,
    ) -> Result<Value> {
        validate_event_key(idempotency_key)?;
        let lock = self.build_in_flight_lock(task_id, scope, release, release_sha256, source_refs)?;
        let payload_hash = strict_json::digest(&json!({"operation":"begin-in-flight","lock":lock,"idempotency_key":idempotency_key}))?;
        if let Some((stored_hash, result)) = self.events.get(idempotency_key) {
            if stored_hash == &payload_hash { return Ok(result.clone()); }
            return Err(Error::new(ErrorKind::EventConflict, "idempotency key has a different in-flight lock"));
        }
        if self.completed_tasks.contains(task_id) {
            return Err(Error::new(ErrorKind::ValidationStale, "completed task IDs cannot be rebound"));
        }
        if let Some(existing) = self.in_flight.get(task_id) {
            if existing == &lock {
                return Err(Error::new(ErrorKind::EventConflict, "in-flight task is already locked with another event"));
            }
            return Err(Error::new(ErrorKind::ValidationStale, "in-flight task is pinned and cannot be hot-replaced"));
        }
        let result = json!({"task_id":task_id,"state":"in_flight","task_lock":lock,"hot_update":false,"runtime_admission":false});
        self.in_flight.insert(task_id.to_owned(), lock);
        self.events.insert(idempotency_key.to_owned(), (payload_hash, result.clone()));
        Ok(result)
    }

    pub fn update_in_flight(
        &self,
        task_id: &str,
        scope: &str,
        release: &str,
        release_sha256: &str,
        source_refs: &[String],
    ) -> Result<Value> {
        let current = self.in_flight.get(task_id)
            .ok_or_else(|| Error::new(ErrorKind::Reference, "in-flight task lock is missing"))?;
        let requested = self.build_in_flight_lock(task_id, scope, release, release_sha256, source_refs)?;
        if current != &requested {
            return Err(Error::new(ErrorKind::ValidationStale, "in-flight task is pinned; update requires a new task lock"));
        }
        Ok(json!({"task_id":task_id,"state":"in_flight","task_lock":current,"hot_update":false,"replayed":true}))
    }

    pub fn complete_in_flight(&mut self, task_id: &str, release_sha256: &str, idempotency_key: &str) -> Result<Value> {
        validate_event_key(idempotency_key)?;
        validate_sha256(release_sha256, "release hash")?;
        let current = self.in_flight.get(task_id)
            .ok_or_else(|| Error::new(ErrorKind::Reference, "in-flight task lock is missing"))?;
        if current.release_sha256 != release_sha256 {
            return Err(Error::new(ErrorKind::ValidationStale, "completion release does not match the in-flight lock"));
        }
        let payload_hash = strict_json::digest(&json!({"operation":"complete-in-flight","task_id":task_id,"release_sha256":release_sha256}))?;
        if let Some((stored_hash, result)) = self.events.get(idempotency_key) {
            if stored_hash == &payload_hash { return Ok(result.clone()); }
            return Err(Error::new(ErrorKind::EventConflict, "idempotency key has a different completion"));
        }
        let lock = self.in_flight.remove(task_id).expect("checked above");
        self.completed_tasks.insert(task_id.to_owned());
        let result = json!({"task_id":task_id,"state":"completed","task_lock":lock,"hot_update":false});
        self.events.insert(idempotency_key.to_owned(), (payload_hash, result.clone()));
        Ok(result)
    }

    pub fn in_flight_lock(&self, task_id: &str) -> Option<&InFlightLock> {
        self.in_flight.get(task_id)
    }

    fn build_in_flight_lock(
        &self,
        task_id: &str,
        scope: &str,
        release: &str,
        release_sha256: &str,
        source_refs: &[String],
    ) -> Result<InFlightLock> {
        validate_identifier(task_id, "task ID")?;
        validate_identifier(scope, "scope")?;
        validate_identifier(release, "release")?;
        validate_sha256(release_sha256, "release hash")?;
        if source_refs.is_empty() || source_refs.len() > 256 || source_refs.iter().any(|value| value.is_empty() || value.len() > MAX_GOVERNANCE_TEXT || value.chars().any(char::is_control)) {
            return Err(Error::new(ErrorKind::Reference, "in-flight lock requires bounded source references"));
        }
        let mut normalized = source_refs.to_vec();
        normalized.sort();
        normalized.dedup();
        if normalized.len() != source_refs.len() {
            return Err(Error::new(ErrorKind::Shape, "in-flight source references must be unique"));
        }
        for source_ref in &normalized {
            let (_, source) = self.source_admissions.get(source_ref)
                .ok_or_else(|| Error::new(ErrorKind::Reference, "in-flight lock references an unadmitted source"))?;
            if source.scope != scope {
                return Err(Error::new(ErrorKind::ScopeDenied, "in-flight source scope differs from task scope"));
            }
            if !self.is_active(source_ref) {
                return Err(Error::new(ErrorKind::ValidationStale, "in-flight lock references a revoked source"));
            }
        }
        let lock_sha256 = strict_json::digest(&json!({"task_id":task_id,"scope":scope,"release":release,
            "release_sha256":release_sha256,"source_refs":normalized}))?;
        Ok(InFlightLock { task_id: task_id.to_owned(), scope: scope.to_owned(), release: release.to_owned(),
            release_sha256: release_sha256.to_owned(), source_refs: normalized, lock_sha256 })
    }

    pub fn transition_release(&mut self, release: &str, target: &str) -> Result<Value> {
        if release.is_empty() || target.is_empty() {
            return Err(Error::new(ErrorKind::Shape, "release and target are required"));
        }
        let current = self.releases.get(release).map(String::as_str).unwrap_or("candidate").to_owned();
        let valid = matches!((current.as_str(), target), ("candidate", "validated") | ("validated", "published") | ("published", "withdrawn") | ("withdrawn", "candidate"));
        if !valid {
            return Err(Error::new(ErrorKind::RevisionConflict, "invalid release transition"));
        }
        self.releases.insert(release.to_owned(), target.to_owned());
        Ok(json!({"release": release, "from": current, "to": target, "state": target}))
    }
}

fn validate_identifier(value: &str, label: &str) -> Result<()> {
    if value.is_empty() || value.len() > MAX_GOVERNANCE_TEXT || value.chars().any(char::is_control) {
        return Err(Error::new(ErrorKind::Shape, format!("{label} must be bounded and non-empty")));
    }
    Ok(())
}

fn validate_sha256(value: &str, label: &str) -> Result<()> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()) {
        return Err(Error::new(ErrorKind::Shape, format!("{label} must be a lowercase SHA-256")));
    }
    Ok(())
}

fn validate_source(source: &SourceRecord) -> Result<()> {
    for (value, label) in [
        (&source.id, "source ID"), (&source.scope, "source scope"), (&source.locator, "source locator"),
        (&source.read_scope, "source read scope"), (&source.license, "source license"),
        (&source.version, "source version"), (&source.license_evidence_ref, "license evidence ref"),
    ] {
        validate_identifier(value, label)?;
    }
    validate_sha256(&source.sha256, "source hash")
}

fn validate_license_policy(policy: &LicensePolicy) -> Result<()> {
    validate_identifier(&policy.scope, "license policy scope")?;
    if policy.allowed_licenses.is_empty() || policy.allowed_licenses.len() > 64 || policy.denied_licenses.len() > 64 {
        return Err(Error::new(ErrorKind::Shape, "license policy must have a bounded explicit allowlist"));
    }
    for license in policy.allowed_licenses.iter().chain(policy.denied_licenses.iter()) {
        validate_identifier(license, "license identifier")?;
    }
    Ok(())
}

fn validate_event_key(value: &str) -> Result<()> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        return Err(Error::new(ErrorKind::Shape, "bounded nonempty governance event ID required"));
    }
    Ok(())
}

fn validate_evidence_refs(values: &[String]) -> Result<()> {
    if values.is_empty() || values.len() > 256 || values.iter().any(|value| value.is_empty() || value.len() > MAX_GOVERNANCE_TEXT || value.chars().any(char::is_control)) {
        return Err(Error::new(ErrorKind::Reference, "governance evidence refs must be bounded and non-empty"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn proposal(key: &str, revision: u64, payload: Value) -> DeltaProposal {
        DeltaProposal {
            idempotency_key: key.to_owned(),
            scope: "project:test".to_owned(),
            expected_revision: revision,
            operation: "experience.delta".to_owned(),
            payload,
            evidence_refs: vec!["evidence:test".to_owned()],
        }
    }

    #[test]
    fn same_delta_replays_and_different_payload_conflicts() {
        let mut state = GovernanceState::new();
        let first = state.apply_delta(&proposal("k1", 0, json!({"value": 1}))).unwrap();
        assert_eq!(first["revision"], 1);
        assert_eq!(state.apply_delta(&proposal("k1", 0, json!({"value": 1}))).unwrap(), first);
        assert_eq!(state.apply_delta(&proposal("k1", 0, json!({"value": 2}))).unwrap_err().kind, ErrorKind::EventConflict);
    }

    #[test]
    fn stale_revision_and_missing_evidence_fail_closed() {
        let mut state = GovernanceState::new();
        let mut missing = proposal("k1", 0, json!({}));
        missing.evidence_refs.clear();
        assert_eq!(state.apply_delta(&missing).unwrap_err().kind, ErrorKind::Reference);
        state.apply_delta(&proposal("k1", 0, json!({}))).unwrap();
        assert_eq!(state.apply_delta(&proposal("k2", 0, json!({}))).unwrap_err().kind, ErrorKind::RevisionConflict);
    }

    #[test]
    fn impact_closure_is_complete_and_revocation_is_local() {
        let mut state = GovernanceState::new();
        state.register_consumer("source", "atom").unwrap();
        state.register_consumer("atom", "bundle").unwrap();
        state.register_consumer("bundle", "role").unwrap();
        state.register_consumer("other", "unrelated").unwrap();
        assert_eq!(state.impact_closure("source"), vec!["atom", "bundle", "role", "source"]);
        state.revoke("bundle").unwrap();
        assert!(!state.is_active("bundle"));
        assert!(state.is_active("role"));
    }

    #[test]
    fn release_transitions_are_one_way_until_withdrawal() {
        let mut state = GovernanceState::new();
        state.transition_release("r1", "validated").unwrap();
        state.transition_release("r1", "published").unwrap();
        state.transition_release("r1", "withdrawn").unwrap();
        state.transition_release("r1", "candidate").unwrap();
        assert_eq!(state.transition_release("r1", "published").unwrap_err().kind, ErrorKind::RevisionConflict);
    }

    fn source(version: &str, license: &str) -> SourceRecord {
        SourceRecord { id: "research-source".into(), scope: "project:test".into(),
            locator: "https://example.invalid/source".into(), sha256: "a".repeat(64),
            read_scope: "project:test".into(), license: license.into(), version: version.into(),
            license_evidence_ref: "evidence:license".into() }
    }

    fn license_policy() -> LicensePolicy {
        LicensePolicy { scope: "project:test".into(), allowed_licenses: BTreeSet::from(["MIT".into()]),
            denied_licenses: BTreeSet::new() }
    }

    #[test]
    fn source_license_admission_requires_explicit_policy_and_preserves_versions() {
        let mut state = GovernanceState::new();
        assert_eq!(state.admit_source(&license_policy(), &source("1", "UNKNOWN"), 0, "source-unknown", &["evidence:license".into()]).unwrap_err().kind, ErrorKind::AuthorityDenied);
        let first = state.admit_source(&license_policy(), &source("1", "MIT"), 0, "source-1", &["evidence:license".into()]).unwrap();
        assert_eq!(first["license_status"], "allowed_by_explicit_policy");
        assert_eq!(state.admit_source(&license_policy(), &source("2", "MIT"), 1, "source-2", &["evidence:license".into()]).unwrap()["revision"], 2);
        let mut other_scope = source("1", "MIT");
        other_scope.scope = "project:other".into();
        other_scope.read_scope = "project:other".into();
        let other_policy = LicensePolicy { scope: "project:other".into(), ..license_policy() };
        assert_ne!(source("1", "MIT").reference_key(), other_scope.reference_key());
        assert_eq!(state.admit_source(&other_policy, &other_scope, 0, "source-other", &["evidence:license".into()]).unwrap()["revision"], 1);
        assert!(state.in_flight_lock("missing").is_none());
    }

    #[test]
    fn in_flight_release_is_pinned_while_new_source_version_is_staged() {
        let mut state = GovernanceState::new();
        let first = source("1", "MIT");
        let first_ref = first.reference_key();
        state.admit_source(&license_policy(), &first, 0, "source-1", &["evidence:license".into()]).unwrap();
        let lock = state.begin_in_flight("task-1", "project:test", "release-1", &"b".repeat(64), std::slice::from_ref(&first_ref), "task-1-lock").unwrap();
        let old_lock = lock["task_lock"].clone();
        let second = source("2", "MIT");
        let second_ref = second.reference_key();
        state.admit_source(&license_policy(), &second, 1, "source-2", &["evidence:license".into()]).unwrap();
        assert_eq!(state.update_in_flight("task-1", "project:test", "release-1", &"b".repeat(64), std::slice::from_ref(&first_ref)).unwrap()["task_lock"], old_lock);
        assert_eq!(state.update_in_flight("task-1", "project:test", "release-2", &"c".repeat(64), std::slice::from_ref(&second_ref)).unwrap_err().kind, ErrorKind::ValidationStale);
        assert_eq!(state.in_flight_lock("task-1").unwrap().release, "release-1");
        assert_eq!(state.begin_in_flight("task-1", "project:test", "release-2", &"c".repeat(64), std::slice::from_ref(&second_ref), "task-1-hot-replace").unwrap_err().kind, ErrorKind::ValidationStale);
        state.complete_in_flight("task-1", &"b".repeat(64), "task-1-complete").unwrap();
        assert!(state.in_flight_lock("task-1").is_none());
    }
}

