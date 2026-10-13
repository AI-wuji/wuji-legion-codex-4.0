use crate::error::{Error, ErrorKind, Result};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ExactRef {
    pub id: String,
    pub r#type: String,
    pub scope: String,
    pub revision: u64,
    pub sha256: String,
    pub release: String,
    pub schema_version: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionForm { Model, Program, NativeAction }

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Node {
    pub id: String,
    pub role_ref: ExactRef,
    pub owner: String,
    pub revision: u64,
    pub inputs: Vec<ExactRef>,
    pub read_roots: Vec<String>,
    pub write_roots: Vec<String>,
    pub acceptance_ids: Vec<String>,
    pub status: String,
    pub execution_form: ExecutionForm,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Edge { pub from: String, pub to: String, pub predicate: String }

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Budget {
    pub max_candidates: u64,
    pub max_query_objects: u64,
    pub max_hops: u64,
    pub target_contract_bytes: u64,
    pub target_evidence_bytes: u64,
    pub hard_bytes_limit: Option<u64>,
    pub measured_tokens: Option<u64>,
    pub effective_token_limit: Option<u64>,
    pub wall_ms: u64,
    pub max_parallel_workers: u64,
    pub max_extra_retries: u64,
    pub max_point_revisions: u64,
    pub max_no_progress: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Workflow {
    pub workflow_id: String,
    pub version: String,
    pub catalog_version: String,
    pub nodes: Vec<Node>,
    pub edges: Vec<Edge>,
    pub budget: Budget,
}

pub fn dependency_order(nodes: &[String], edges: &[Edge]) -> Result<Vec<String>> {
    if nodes.len() > 4096 { return Err(Error::new(ErrorKind::BudgetExhausted,"dependency graph cap 4096 nodes")); }
    let mut indegree: BTreeMap<String, usize> = nodes.iter().map(|id| (id.clone(), 0)).collect();
    if indegree.len() != nodes.len() { return Err(Error::new(ErrorKind::Shape, "duplicate node id")); }
    let mut successors: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for edge in edges {
        if edge.predicate != "depends-on" || !indegree.contains_key(&edge.from) || !indegree.contains_key(&edge.to) {
            return Err(Error::new(ErrorKind::Reference, "invalid dependency endpoint or predicate"));
        }
        if edge.from == edge.to { return Err(Error::new(ErrorKind::DependencyCycle, format!("cycle path: {} -> {}",edge.from,edge.to))); }
        if successors.entry(edge.from.clone()).or_default().insert(edge.to.clone()) {
            *indegree.get_mut(&edge.to).unwrap() += 1;
        } else {
            return Err(Error::new(ErrorKind::Shape, "duplicate dependency"));
        }
    }
    let mut ready: BTreeSet<_> = indegree.iter().filter(|(_, count)| **count == 0).map(|(id, _)| id.clone()).collect();
    let mut result = Vec::new();
    while let Some(id) = ready.pop_first() {
        result.push(id.clone());
        for target in successors.get(&id).into_iter().flatten() {
            let count = indegree.get_mut(target).unwrap();
            *count -= 1;
            if *count == 0 { ready.insert(target.clone()); }
        }
    }
    if result.len() != nodes.len() {
        let mut finished = BTreeSet::new();
        for start in indegree.keys() {
            if finished.contains(start) { continue; }
            let mut path = vec![start.clone()];
            let mut active = BTreeMap::from([(start.clone(),0usize)]);
            let mut pending = vec![(start.clone(),0usize)];
            while let Some((current,index)) = pending.last().cloned() {
                let children: Vec<_> = successors.get(&current).into_iter().flatten().cloned().collect();
                if index >= children.len() {
                    pending.pop(); path.pop(); active.remove(&current); finished.insert(current);
                    continue;
                }
                pending.last_mut().unwrap().1 += 1;
                let target = &children[index];
                if let Some(position) = active.get(target) {
                    let mut cycle = path[*position..].to_vec(); cycle.push(target.clone());
                    return Err(Error::new(ErrorKind::DependencyCycle,format!("cycle path: {}",cycle.join(" -> "))));
                }
                if !finished.contains(target) {
                    active.insert(target.clone(),path.len()); path.push(target.clone()); pending.push((target.clone(),0));
                }
            }
        }
        return Err(Error::new(ErrorKind::DependencyCycle,"unresolved cyclic graph"));
    }
    Ok(result)
}

pub fn affected(start: &[String], edges: &[Edge]) -> BTreeSet<String> {
    let mut seen: BTreeSet<_> = start.iter().cloned().collect();
    let mut pending = start.to_vec();
    while let Some(source) = pending.pop() {
        for edge in edges.iter().filter(|edge| edge.from == source) {
            if seen.insert(edge.to.clone()) { pending.push(edge.to.clone()); }
        }
    }
    seen
}

#[cfg(test)]
mod tests {
    use super::*;
    fn edge(from: &str, to: &str) -> Edge { Edge { from: from.into(), to: to.into(), predicate: "depends-on".into() } }

    #[test]
    fn dag_and_full_impact() {
        let nodes = vec!["a".into(), "b".into(), "c".into(), "d".into()];
        let edges = vec![edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")];
        assert_eq!(dependency_order(&nodes, &edges).unwrap(), nodes);
        assert_eq!(affected(&["a".into()], &edges).len(), 4);
        let mut cyclic = edges;
        cyclic.push(edge("d", "a"));
        assert_eq!(dependency_order(&nodes, &cyclic).unwrap_err().kind, ErrorKind::DependencyCycle);
    }

    #[test]
    fn dangling_and_duplicate_edges() {
        let nodes = vec!["a".into(), "b".into()];
        assert!(dependency_order(&nodes, &[edge("a", "missing")]).is_err());
        assert!(dependency_order(&nodes, &[edge("a", "b"), edge("a", "b")]).is_err());
    }
}
