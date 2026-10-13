use crate::error::{Error, ErrorKind, Result};
use crate::contracts::Schemas;
use crate::graph::{self, Edge, ExactRef};
use crate::strict_json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all="snake_case")]
pub enum SlotKind { String, Integer, Boolean }

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FragmentData {
    id: String,
    scope: String,
    revision: u64,
    release: String,
    dependencies: Vec<ExactRef>,
    conflicts: Vec<ExactRef>,
    fields: BTreeMap<String, Value>,
    required_fields: Vec<String>,
    allowed_slots: BTreeMap<String, SlotKind>,
}

struct Fragment {
    reference: ExactRef,
    data: FragmentData,
}

pub struct PreparedCatalog {
    scope: String,
    release: String,
    required_roots: Vec<ExactRef>,
    fragments: BTreeMap<String, Fragment>,
}

impl PreparedCatalog {
    pub fn new(scope: &str, release: &str, required_roots: Vec<ExactRef>) -> Self {
        Self { scope:scope.into(),release:release.into(),required_roots,fragments:BTreeMap::new() }
    }

    pub fn register_derived_fragment(&mut self, reference: ExactRef, file_bytes: &[u8]) -> Result<()> {
        Schemas::frozen()?.check_definition("ExactRef",&serde_json::to_value(&reference)?)?;
        if reference.scope != self.scope || reference.release != self.release || reference.schema_version != 1 || reference.r#type != "file" {
            return Err(Error::new(ErrorKind::ScopeDenied,"fragment scope/release/schema/hash domain mismatch"));
        }
        if strict_json::sha256(file_bytes) != reference.sha256 { return Err(Error::new(ErrorKind::HashMismatch,"fragment file digest mismatch")); }
        let value = strict_json::parse(file_bytes)?;
        let data: FragmentData = serde_json::from_value(value)?;
        if data.id != reference.id || data.revision != reference.revision || data.scope != reference.scope || data.release != reference.release {
            return Err(Error::new(ErrorKind::Reference,"fragment exact identity mismatch"));
        }
        if let Some(previous) = self.fragments.get(&reference.id) {
            if previous.reference != reference { return Err(Error::new(ErrorKind::CompositionConflict,"same ID has incompatible exact definitions")); }
            return Ok(());
        }
        self.fragments.insert(reference.id.clone(),Fragment { reference,data });
        Ok(())
    }

    fn resolve(&self, reference: &ExactRef) -> Result<&Fragment> {
        let found = self.fragments.get(&reference.id).ok_or_else(|| Error::new(ErrorKind::Reference,format!("missing exact fragment: {}@{} in release {}",reference.id,reference.revision,reference.release)))?;
        if &found.reference != reference { return Err(Error::new(ErrorKind::Reference,format!("no latest fallback for fragment: {}@{}",reference.id,reference.revision))); }
        Ok(found)
    }

    pub fn compose(&self, roots: &[ExactRef], slots: &BTreeMap<String,Value>, hard_byte_limit: usize) -> Result<Value> {
        if hard_byte_limit > strict_json::MAX_INPUT_BYTES { return Err(Error::new(ErrorKind::BudgetExhausted,"prepared contract cap 1 MiB")); }
        if self.required_roots.iter().any(|required| !roots.contains(required)) { return Err(Error::new(ErrorKind::RequiredWeakened,"mandatory assembly root omitted")); }
        let mut pending = roots.to_vec();
        let mut closure = BTreeSet::new();
        let mut edges = Vec::new();
        while let Some(reference) = pending.pop() {
            let fragment = self.resolve(&reference)?;
            if !closure.insert(reference.id.clone()) { continue; }
            if closure.len() > 256 { return Err(Error::new(ErrorKind::BudgetExhausted,"fragment closure cap 256")); }
            for dependency in &fragment.data.dependencies {
                self.resolve(dependency)?;
                edges.push(Edge { from:dependency.id.clone(),to:reference.id.clone(),predicate:"depends-on".into() });
                pending.push(dependency.clone());
            }
        }
        let ids: Vec<String> = closure.iter().cloned().collect();
        let ordered = graph::dependency_order(&ids,&edges)?;
        for id in &ordered {
            for conflict in &self.fragments[id].data.conflicts {
                if closure.contains(&conflict.id) { self.resolve(conflict)?; return Err(Error::new(ErrorKind::CompositionConflict,"exclusive fragment selected")); }
            }
        }
        let mut fields = BTreeMap::<String,Value>::new();
        let mut field_origins = BTreeMap::<String,Vec<ExactRef>>::new();
        let mut required_fields = BTreeSet::new();
        let mut allowed_slots = BTreeMap::new();
        let mut slot_definitions = BTreeMap::<String,Vec<ExactRef>>::new();
        for id in &ordered {
            let fragment = &self.fragments[id];
            for (key,value) in &fragment.data.fields {
                if fields.get(key).is_some_and(|previous| previous != value) { return Err(Error::new(ErrorKind::CompositionConflict,format!("field conflict: {key}"))); }
                fields.insert(key.clone(),value.clone());
                field_origins.entry(key.clone()).or_default().push(fragment.reference.clone());
            }
            required_fields.extend(fragment.data.required_fields.iter().cloned());
            for (key,kind) in &fragment.data.allowed_slots {
                if allowed_slots.get(key).is_some_and(|previous| previous != kind) { return Err(Error::new(ErrorKind::CompositionConflict,"slot type conflict")); }
                allowed_slots.insert(key.clone(),kind.clone());
                slot_definitions.entry(key.clone()).or_default().push(fragment.reference.clone());
            }
        }
        for key in &required_fields {
            if !fields.contains_key(key) { return Err(Error::new(ErrorKind::RequiredWeakened,"required field lacks defining contribution")); }
        }
        let mut task_slot_origins = BTreeMap::new();
        for (key,value) in slots {
            let kind = allowed_slots.get(key).ok_or_else(|| Error::new(ErrorKind::CompositionConflict,"undeclared slot"))?;
            let compatible = match kind { SlotKind::String => value.is_string(),SlotKind::Integer => value.as_i64().is_some() || value.as_u64().is_some(),SlotKind::Boolean => value.is_boolean() };
            if !compatible { return Err(Error::new(ErrorKind::Shape,"slot type mismatch")); }
            if required_fields.contains(key) && fields.get(key) != Some(value) { return Err(Error::new(ErrorKind::RequiredWeakened,"slot would alter required invariant")); }
            fields.insert(key.clone(),value.clone());
            field_origins.entry(key.clone()).or_default().extend(slot_definitions[key].iter().cloned());
            task_slot_origins.insert(key.clone(),format!("/slots/{}",key.replace('~',"~0").replace('/',"~1")));
        }
        let mut paths = BTreeMap::<String,Vec<Vec<String>>>::new();
        let mut stack: Vec<(String,Vec<String>)> = roots.iter().map(|root| (root.id.clone(),vec![root.id.clone()])).collect();
        let mut path_count = 0;
        while let Some((id,path)) = stack.pop() {
            path_count += 1;
            if path_count > 4096 || path.len() > 128 { return Err(Error::new(ErrorKind::BudgetExhausted,"all origin paths exceed bounded preparation")); }
            paths.entry(id.clone()).or_default().push(path.clone());
            for dependency in &self.fragments[&id].data.dependencies {
                let mut next = path.clone();
                next.push(dependency.id.clone());
                stack.push((dependency.id.clone(),next));
            }
        }
        for source_paths in paths.values_mut() { source_paths.sort(); source_paths.dedup(); }
        let lock: Vec<_> = ordered.iter().map(|id| self.fragments[id].reference.clone()).collect();
        let mut result = json!({"state":"prepared","scope":self.scope,"release":self.release,"codec":"wuji-canonical-json-v1","fields":fields,"field_origins":field_origins,"task_slot_origins":task_slot_origins,"origin_paths":paths,"lock":lock,"slots":slots,"runtime_admission":false,"native_execution":false});
        let bytes = strict_json::canonical(&result)?;
        if bytes.len() > hard_byte_limit { return Err(Error::new(ErrorKind::BudgetExhausted,"required complete contract exceeds byte cap; not truncated")); }
        let hash = strict_json::sha256(&bytes);
        result["composition_hash"] = json!(hash);
        if strict_json::canonical(&result)?.len() > hard_byte_limit { return Err(Error::new(ErrorKind::BudgetExhausted,"complete prepared result including hash exceeds byte cap")); }
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(id: &str, dependencies: Vec<ExactRef>, fields: Value, required: &[&str], slots: Value) -> (ExactRef,Vec<u8>) {
        let bytes = strict_json::canonical(&json!({"id":id,"scope":"project-fixture","revision":1,"release":"fixture-1","dependencies":dependencies,"conflicts":[],"fields":fields,"required_fields":required,"allowed_slots":slots})).unwrap();
        let reference = ExactRef { id:id.into(),r#type:"file".into(),scope:"project-fixture".into(),revision:1,sha256:strict_json::sha256(&bytes),release:"fixture-1".into(),schema_version:1 };
        (reference,bytes)
    }

    #[test]
    fn deterministic_diamond_and_all_source_paths() {
        let (base,base_bytes) = fixture("base",vec![],json!({"authorization_required":true}),&["authorization_required"],json!({}));
        let (left,left_bytes) = fixture("left",vec![base.clone()],json!({"left":"code"}),&[],json!({}));
        let (right,right_bytes) = fixture("right",vec![base.clone()],json!({"right":"review"}),&[],json!({}));
        let (root,root_bytes) = fixture("root",vec![right.clone(),left.clone()],json!({"output":"file"}),&[],json!({"tone":"string"}));
        let mut catalog = PreparedCatalog::new("project-fixture","fixture-1",vec![root.clone()]);
        for (reference,bytes) in [(root.clone(),root_bytes),(right,right_bytes),(base,base_bytes),(left,left_bytes)] { catalog.register_derived_fragment(reference,&bytes).unwrap(); }
        let result = catalog.compose(&[root.clone()],&BTreeMap::new(),10000).unwrap();
        assert_eq!(result["lock"].as_array().unwrap().len(),4);
        assert_eq!(result["origin_paths"]["base"].as_array().unwrap().len(),2);
        assert_eq!(result,catalog.compose(&[root],&BTreeMap::new(),10000).unwrap());
        assert_eq!(result["runtime_admission"],false);
    }

    #[test]
    fn conflicts_and_required_weakening_fail_independently() {
        let (root,bytes) = fixture("root",vec![],json!({"authorization_required":true}),&["authorization_required"],json!({"authorization_required":"boolean","tone":"string"}));
        let mut catalog = PreparedCatalog::new("project-fixture","fixture-1",vec![root.clone()]);
        catalog.register_derived_fragment(root.clone(),&bytes).unwrap();
        assert_eq!(catalog.compose(&[],&BTreeMap::new(),10000).unwrap_err().kind,ErrorKind::RequiredWeakened);
        let slots = BTreeMap::from([("authorization_required".into(),json!(false))]);
        assert_eq!(catalog.compose(&[root.clone()],&slots,10000).unwrap_err().kind,ErrorKind::RequiredWeakened);
        let slots = BTreeMap::from([("tone".into(),json!(7))]);
        assert_eq!(catalog.compose(&[root.clone()],&slots,10000).unwrap_err().kind,ErrorKind::Shape);
        assert_eq!(catalog.compose(&[root],&BTreeMap::new(),1).unwrap_err().kind,ErrorKind::BudgetExhausted);
    }

    #[test]
    fn exact_version_scope_and_file_hash_are_distinct_guards() {
        let (reference,bytes) = fixture("root",vec![],json!({}),&[],json!({}));
        let mut catalog = PreparedCatalog::new("project-fixture","fixture-1",vec![]);
        let mut bad = reference.clone(); bad.scope="other".into();
        assert_eq!(catalog.register_derived_fragment(bad,&bytes).unwrap_err().kind,ErrorKind::ScopeDenied);
        assert_eq!(catalog.register_derived_fragment(reference.clone(),b"{}").unwrap_err().kind,ErrorKind::HashMismatch);
        catalog.register_derived_fragment(reference.clone(),&bytes).unwrap();
        let mut bad = reference; bad.revision=2;
        assert_eq!(catalog.compose(&[bad],&BTreeMap::new(),10000).unwrap_err().kind,ErrorKind::Reference);
    }

    #[test]
    fn conflicting_field_values_are_not_last_writer_wins() {
        let (first,first_bytes) = fixture("first",vec![],json!({"output":"pptx"}),&[],json!({}));
        let (second,second_bytes) = fixture("second",vec![],json!({"output":"png"}),&[],json!({}));
        let mut catalog = PreparedCatalog::new("project-fixture","fixture-1",vec![]);
        catalog.register_derived_fragment(first.clone(),&first_bytes).unwrap();
        catalog.register_derived_fragment(second.clone(),&second_bytes).unwrap();
        assert_eq!(catalog.compose(&[first,second],&BTreeMap::new(),10000).unwrap_err().kind,ErrorKind::CompositionConflict);
    }
}
