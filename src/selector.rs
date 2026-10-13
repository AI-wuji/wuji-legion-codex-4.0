use crate::contracts::Schemas;
use crate::error::{Error, ErrorKind, Result};
use crate::graph::ExactRef;
use crate::policy::Workspace;
use crate::store::bounded_file;
use crate::strict_json;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all="snake_case")]
pub enum CandidateKind { Leaf, Method, Style, Recipe }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProjectionTier { Brief, Overview, Source }

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FileReference { path: String, reference: ExactRef }

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    reference: ExactRef,
    kind: CandidateKind,
    domain: String,
    all_intents: BTreeSet<String>,
    anti_intents: BTreeSet<String>,
    brief: String,
    overview: FileReference,
    source: FileReference,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IndexFile {
    schema_version: u64,
    scope: String,
    release: String,
    state: String,
    entries: Vec<Entry>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SelectionRequest {
    pub domain: String,
    pub kind: CandidateKind,
    pub intents: BTreeSet<String>,
    pub max_candidates: usize,
}

pub struct PreparedIndex {
    workspace: Workspace,
    path: PathBuf,
    reference: ExactRef,
    metadata_bytes: usize,
    entries: BTreeMap<String,Entry>,
    groups: BTreeMap<(String,CandidateKind),Vec<String>>,
}

impl PreparedIndex {
    pub fn open(root: &Path, path: &Path, reference: ExactRef) -> Result<Self> {
        Schemas::frozen()?.check_definition("ExactRef",&serde_json::to_value(&reference)?)?;
        if reference.r#type != "file" || reference.schema_version != 1 { return Err(Error::new(ErrorKind::Reference,"index needs exact file schema1 reference")); }
        let workspace = Workspace::open(root)?;
        let root_hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
        if reference.scope != format!("project:{}",&root_hash[..24]) { return Err(Error::new(ErrorKind::ScopeDenied,"index scope is not approved workspace identity")); }
        let path = workspace.resolve(path)?;
        let bytes = bounded_file(&path)?;
        if strict_json::sha256(&bytes) != reference.sha256 { return Err(Error::new(ErrorKind::HashMismatch,"index digest differs from locked reference")); }
        let index: IndexFile = serde_json::from_value(strict_json::parse(&bytes)?)?;
        if index.scope != reference.scope || index.release != reference.release || index.schema_version != 1 || index.state != "prepared" {
            return Err(Error::new(ErrorKind::Reference,"only exact prepared index is supported; this is not active catalog admission"));
        }
        if index.entries.len() > 512 { return Err(Error::new(ErrorKind::BudgetExhausted,"prepared metadata cap 512")); }
        let mut entries = BTreeMap::new();
        let mut groups = BTreeMap::<_,Vec<_>>::new();
        for entry in index.entries {
            for target in [&entry.reference,&entry.overview.reference,&entry.source.reference] {
                Schemas::frozen()?.check_definition("ExactRef",&serde_json::to_value(target)?)?;
                if target.scope != index.scope || target.release != index.release || target.r#type != "file" || target.schema_version != 1 {
                    return Err(Error::new(ErrorKind::ScopeDenied,"index entry scope/release/schema differs"));
                }
            }
            if entry.domain.is_empty() || entry.domain.len() > 128 || entry.brief.len() > 1024 || entry.all_intents.is_empty() || entry.all_intents.len() > 32 || entry.anti_intents.len() > 32 || !entry.all_intents.is_disjoint(&entry.anti_intents) {
                return Err(Error::new(ErrorKind::Shape,"candidate needs bounded typed triggers, anti-triggers and brief"));
            }
            if entry.reference != entry.source.reference { return Err(Error::new(ErrorKind::Reference,"candidate identity must exactly name its cold source")); }
            groups.entry((entry.domain.clone(),entry.kind)).or_default().push(entry.reference.id.clone());
            if entries.insert(entry.reference.id.clone(),entry).is_some() { return Err(Error::new(ErrorKind::Reference,"duplicate candidate id")); }
        }
        for group in groups.values_mut() { group.sort(); }
        Ok(Self { workspace,path,reference,metadata_bytes:bytes.len(),entries,groups })
    }

    fn current(&self) -> Result<()> {
        let bytes = bounded_file(&self.workspace.resolve(&self.path)?)?;
        if strict_json::sha256(&bytes) != self.reference.sha256 { return Err(Error::new(ErrorKind::ValidationStale,"prepared index source changed; reopen with reviewed exact reference")); }
        Ok(())
    }

    pub fn select(&self, request: &SelectionRequest) -> Result<Value> {
        self.current()?;
        if request.max_candidates == 0 || request.max_candidates > 64 || request.intents.len() > 64 {
            return Err(Error::new(ErrorKind::BudgetExhausted,"selection needs 1..64 candidate cap and <=64 typed intents"));
        }
        let group = self.groups.get(&(request.domain.clone(),request.kind));
        let mut selected = Vec::new();
        let mut examined = 0;
        for id in group.into_iter().flatten() {
            examined += 1;
            let entry = &self.entries[id];
            if entry.all_intents.is_subset(&request.intents) && entry.anti_intents.is_disjoint(&request.intents) {
                selected.push(entry.reference.clone());
                if selected.len() > request.max_candidates { return Err(Error::new(ErrorKind::BudgetExhausted,"matching group exceeds cap; narrow typed domain/intents, do not silently truncate")); }
            }
        }
        let state = match selected.len() { 0 => "none",1 => "selected",_ => "ambiguous" };
        Ok(json!({"state":state,"candidates":selected,"source_index_ref":self.reference,"examined_metadata_entries":examined,"index_bytes_read_this_call":self.metadata_bytes,"professional_body_bytes_read":0,"runtime_admission":false,"native_execution":false,"confidence":null}))
    }

    pub fn project(&self, reference: &ExactRef, tier: ProjectionTier, byte_cap: usize) -> Result<Value> {
        self.current()?;
        if byte_cap > strict_json::MAX_INPUT_BYTES { return Err(Error::new(ErrorKind::BudgetExhausted,"projection hard cap 1 MiB")); }
        let entry = self.entries.get(&reference.id).ok_or_else(|| Error::new(ErrorKind::Reference,"candidate is not in locked index"))?;
        if &entry.reference != reference { return Err(Error::new(ErrorKind::Reference,"no latest/id-only fallback for candidate")); }
        let source_path = self.workspace.resolve(Path::new(&entry.source.path))?;
        let source_bytes = bounded_file(&source_path)?;
        if strict_json::sha256(&source_bytes) != entry.source.reference.sha256 {
            return Err(Error::new(ErrorKind::HashMismatch,"locked source changed; derived brief/overview/source must be reviewed again"));
        }
        let source_validation_bytes = source_bytes.len();
        let mut loaded = 0;
        let (tier_name,content,content_ref) = match tier {
            ProjectionTier::Brief => ("brief",entry.brief.clone(),self.reference.clone()),
            ProjectionTier::Overview | ProjectionTier::Source => {
                let file = if tier == ProjectionTier::Overview { &entry.overview } else { &entry.source };
                let bytes = if tier == ProjectionTier::Source { source_bytes } else {
                    bounded_file(&self.workspace.resolve(Path::new(&file.path))?)?
                };
                if strict_json::sha256(&bytes) != file.reference.sha256 { return Err(Error::new(ErrorKind::HashMismatch,"requested cold content changed")); }
                loaded = bytes.len();
                let content = String::from_utf8(bytes).map_err(|_| Error::new(ErrorKind::Shape,"projection requires UTF-8 text"))?;
                (if tier == ProjectionTier::Overview { "overview" } else { "source" },content,file.reference.clone())
            }
        };
        let additional_projection_bytes = if tier == ProjectionTier::Overview { loaded } else { 0 };
        let result = json!({"tier":tier_name,"candidate_ref":reference,"source_index_ref":self.reference,"content_ref":content_ref,"content":content,"content_bytes_read":loaded,"source_validation_bytes_read":source_validation_bytes,"file_bytes_read_this_call":self.metadata_bytes+source_validation_bytes+additional_projection_bytes,"index_bytes_read_this_call":self.metadata_bytes,"runtime_admission":false,"execution_authority":false});
        if strict_json::canonical(&result)?.len() > byte_cap { return Err(Error::new(ErrorKind::BudgetExhausted,"complete projection exceeds cap; source is not silently truncated")); }
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime,UNIX_EPOCH};

    fn exact(scope: &str, id: &str, bytes: &[u8]) -> ExactRef {
        ExactRef { id:id.into(),r#type:"file".into(),scope:scope.into(),revision:1,sha256:strict_json::sha256(bytes),release:"fixture-1".into(),schema_version:1 }
    }

    fn fixture(duplicate: bool) -> (PathBuf,ExactRef,ExactRef) {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/core-test-workspaces").join(format!("selector-{}-{now}",std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let workspace = Workspace::open(&root).unwrap();
        let root_hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
        let scope = format!("project:{}",&root_hash[..24]);
        let source = exact(&scope,"fixture/source",b"cold method fixture");
        let overview = exact(&scope,"fixture/overview",b"overview fixture");
        fs::write(root.join("source.txt"),b"cold method fixture").unwrap();
        fs::write(root.join("overview.txt"),b"overview fixture").unwrap();
        let entry = json!({"reference":source,"kind":"method","domain":"engineering","all_intents":["bounded-file"],"anti_intents":["publishing"],"brief":"bounded file method fixture","overview":{"path":"overview.txt","reference":overview},"source":{"path":"source.txt","reference":source}});
        let mut entries = vec![entry.clone()];
        if duplicate {
            let mut second = entry;
            second["reference"]["id"] = json!("fixture/second");
            second["source"]["reference"]["id"] = json!("fixture/second");
            entries.push(second);
        }
        let bytes = strict_json::canonical(&json!({"schema_version":1,"scope":scope,"release":"fixture-1","state":"prepared","entries":entries})).unwrap();
        let index = exact(&scope,"fixture/index",&bytes);
        fs::write(root.join("index.json"),bytes).unwrap();
        (root,index,source)
    }

    fn request() -> SelectionRequest {
        SelectionRequest { domain:"engineering".into(),kind:CandidateKind::Method,intents:BTreeSet::from(["bounded-file".into()]),max_candidates:8 }
    }

    #[test]
    fn typed_selection_and_antitrigger_do_not_load_body() {
        let (root,index,_) = fixture(false);
        fs::write(root.join("source.txt"),b"changed before selection").unwrap();
        let prepared = PreparedIndex::open(&root,Path::new("index.json"),index).unwrap();
        let result = prepared.select(&request()).unwrap();
        assert_eq!(result["state"],"selected");
        assert_eq!(result["professional_body_bytes_read"],0);
        assert_eq!(result["runtime_admission"],false);
        let mut negative = request();
        negative.intents.insert("publishing".into());
        assert_eq!(prepared.select(&negative).unwrap()["state"],"none");
        negative.domain = "unrelated".into();
        assert_eq!(prepared.select(&negative).unwrap()["examined_metadata_entries"],0);
    }

    #[test]
    fn ambiguous_selection_and_candidate_overflow_are_not_confidence() {
        let (root,index,_) = fixture(true);
        let prepared = PreparedIndex::open(&root,Path::new("index.json"),index).unwrap();
        assert_eq!(prepared.select(&request()).unwrap()["state"],"ambiguous");
        let mut limited = request(); limited.max_candidates = 1;
        assert_eq!(prepared.select(&limited).unwrap_err().kind,ErrorKind::BudgetExhausted);
    }

    #[test]
    fn tier_direct_source_is_hash_bound_and_not_fake_hot_loading() {
        let (root,index,source) = fixture(false);
        let prepared = PreparedIndex::open(&root,Path::new("index.json"),index).unwrap();
        let brief = prepared.project(&source,ProjectionTier::Brief,10000).unwrap();
        assert_eq!(brief["content_bytes_read"],0);
        assert_eq!(brief["source_validation_bytes_read"],19);
        assert_eq!(prepared.project(&source,ProjectionTier::Brief,1).unwrap_err().kind,ErrorKind::BudgetExhausted);
        let direct = prepared.project(&source,ProjectionTier::Source,10000).unwrap();
        assert_eq!(direct["content"],"cold method fixture");
        assert_eq!(direct["content_bytes_read"],19);
        fs::write(root.join("source.txt"),b"changed").unwrap();
        assert_eq!(prepared.project(&source,ProjectionTier::Brief,10000).unwrap_err().kind,ErrorKind::HashMismatch);
        assert_eq!(prepared.project(&source,ProjectionTier::Source,10000).unwrap_err().kind,ErrorKind::HashMismatch);
        assert_eq!(prepared.project(&source,ProjectionTier::Overview,10000).unwrap_err().kind,ErrorKind::HashMismatch);
    }

    #[test]
    fn index_change_revokes_projection_and_id_only_fallback_is_rejected() {
        let (root,index,mut source) = fixture(false);
        let prepared = PreparedIndex::open(&root,Path::new("index.json"),index).unwrap();
        source.revision = 2;
        assert_eq!(prepared.project(&source,ProjectionTier::Brief,10000).unwrap_err().kind,ErrorKind::Reference);
        fs::write(root.join("index.json"),b"changed index").unwrap();
        assert_eq!(prepared.select(&request()).unwrap_err().kind,ErrorKind::ValidationStale);
    }
}
