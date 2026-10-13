use crate::composer::PreparedCatalog;
use crate::contracts::Schemas;
use crate::error::{Error, ErrorKind, Result};
use crate::graph::ExactRef;
use crate::policy::Workspace;
use crate::store::bounded_file;
use crate::strict_json;
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Duration;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CatalogFile { pub path: String, pub reference: ExactRef }

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseManifest {
    pub schema_version: u64,
    pub scope: String,
    pub release: String,
    pub required_roots: Vec<ExactRef>,
    pub files: Vec<CatalogFile>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ReleaseLock {
    pub schema_version: u64,
    pub registry_scope: String,
    pub release: String,
    pub manifest_sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseBundle {
    pub manifest: ReleaseManifest,
    pub definitions: BTreeMap<String, Value>,
}

pub struct LocalCatalogPermit { root: PathBuf }

impl LocalCatalogPermit {
    pub fn confirm(root: &Path, confirmation: &str) -> Result<Self> {
        if confirmation != "confirm-isolated-local-catalog" {
            return Err(Error::new(ErrorKind::AuthorityDenied,"explicit isolated catalog confirmation required"));
        }
        let workspace = Workspace::open(root)?;
        let development = fs::canonicalize(Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev"))?;
        if !workspace.root().starts_with(&development) || workspace.root() == development {
            return Err(Error::new(ErrorKind::ScopeDenied,"catalog writes restricted to a separate project .dev workspace"));
        }
        Ok(Self { root: workspace.root().to_owned() })
    }

    fn check(&self, registry: &CatalogRegistry) -> Result<()> {
        if self.root != registry.workspace.root() {
            return Err(Error::new(ErrorKind::ScopeDenied,"catalog permit belongs to another registry"));
        }
        Ok(())
    }
}

pub struct CatalogRegistry { connection: Connection, workspace: Workspace, scope: String }

struct LoadedRelease {
    manifest: ReleaseManifest,
    catalog: PreparedCatalog,
    consumers: BTreeSet<(String, String)>,
    compositions: BTreeMap<String, String>,
}

fn identifier(value: &str) -> Result<()> {
    if value.is_empty() || value.len() > 64 || !value.bytes().all(|character| character.is_ascii_lowercase() || character.is_ascii_digit() || character == b'-') {
        return Err(Error::new(ErrorKind::Shape,"catalog release ID must be a bounded lowercase slug"));
    }
    Ok(())
}

fn file_name(value: &str) -> Result<()> {
    let stem = value.strip_suffix(".json").ok_or_else(|| Error::new(ErrorKind::PathDenied,"catalog definition must be a JSON leaf"))?;
    identifier(stem)?;
    if value == "manifest.json" {
        return Err(Error::new(ErrorKind::PathDenied,"manifest filename is reserved"));
    }
    Ok(())
}

fn immutable_file(workspace: &Workspace, path: &Path, bytes: &[u8]) -> Result<()> {
    let resolved = workspace.resolve(path)?;
    match OpenOptions::new().write(true).create_new(true).open(&resolved) {
        Ok(mut file) => { file.write_all(bytes)?; file.sync_all()?; }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if bounded_file(&resolved)? != bytes {
                return Err(Error::new(ErrorKind::HashMismatch,"immutable catalog file cannot be overwritten"));
            }
        }
        Err(error) => return Err(error.into()),
    }
    Ok(())
}

fn event(transaction: &Transaction<'_>, key: &str, hash: &str) -> Result<Option<Value>> {
    if key.is_empty() || key.len() > 128 || key.chars().any(char::is_control) {
        return Err(Error::new(ErrorKind::Shape,"bounded nonempty catalog event ID required"));
    }
    let stored: Option<(String,String)> = transaction.query_row("SELECT payload_hash,result_json FROM catalog_events WHERE event_id=?1",[key],|row| Ok((row.get(0)?,row.get(1)?))).optional()?;
    match stored {
        Some((previous,text)) if previous == hash => Ok(Some(strict_json::parse(text.as_bytes())?)),
        Some(_) => Err(Error::new(ErrorKind::EventConflict,"catalog event ID has a different payload")),
        None => Ok(None),
    }
}

fn record_event(transaction: &Transaction<'_>, key: &str, hash: &str, result: &Value) -> Result<()> {
    transaction.execute("INSERT INTO catalog_events VALUES(?1,?2,?3)",params![key,hash,serde_json::to_string(result)?])?;
    Ok(())
}

impl CatalogRegistry {
    pub fn init(root: &Path, permit: &LocalCatalogPermit) -> Result<Self> {
        if Workspace::open(root)?.root() != permit.root {
            return Err(Error::new(ErrorKind::ScopeDenied,"catalog initialization permit mismatch"));
        }
        Self::open_mode(root, true)
    }

    pub fn open_existing(root: &Path) -> Result<Self> { Self::open_mode(root, false) }

    fn open_mode(root: &Path, create: bool) -> Result<Self> {
        let workspace = Workspace::open(root)?;
        let control = workspace.resolve(Path::new(".wuji4-catalog"))?;
        if !control.exists() {
            if !create { return Err(Error::new(ErrorKind::Reference,"catalog registry not initialized")); }
            fs::create_dir(&control)?;
        }
        let database = workspace.resolve(Path::new(".wuji4-catalog/registry.sqlite"))?;
        let existed = database.exists();
        if !existed && !create { return Err(Error::new(ErrorKind::Reference,"catalog registry database missing")); }
        let mut connection = Connection::open(&database)?;
        connection.busy_timeout(Duration::from_millis(500))?;
        connection.pragma_update(None,"foreign_keys","ON")?;
        let application: i64 = connection.pragma_query_value(None,"application_id",|row|row.get(0))?;
        let version: i64 = connection.pragma_query_value(None,"user_version",|row|row.get(0))?;
        let root_hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
        let scope = format!("project:{}",&root_hash[..24]);
        if existed {
            if application != 1465201713 || version != 1 {
                return Err(Error::new(ErrorKind::MigrationUnsupported,"unknown catalog database; no migration"));
            }
            let stored: (String,String) = connection.query_row("SELECT scope,root_hash FROM registry_meta WHERE singleton=1",[],|row|Ok((row.get(0)?,row.get(1)?)))?;
            if stored != (scope.clone(),root_hash.clone()) {
                return Err(Error::new(ErrorKind::ScopeDenied,"catalog registry identity mismatch"));
            }
        } else {
            let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            transaction.execute_batch(include_str!("registry_schema.sql"))?;
            transaction.execute("INSERT INTO registry_meta(singleton,scope,root_hash) VALUES(1,?1,?2)",params![scope,root_hash])?;
            transaction.commit()?;
        }
        Ok(Self { connection,workspace,scope })
    }

    pub fn scope(&self) -> &str { &self.scope }

    pub(crate) fn begin_action_guard(&mut self) -> Result<()> {
        self.connection.execute_batch("BEGIN IMMEDIATE")?;
        Ok(())
    }

    pub fn status(&self) -> Result<Value> {
        let (release,revision): (Option<String>,i64) = self.connection.query_row("SELECT active_release,pointer_revision FROM registry_meta WHERE singleton=1",[],|row|Ok((row.get(0)?,row.get(1)?)))?;
        let active = match release { Some(release) => Some(self.lock(&release,true)?),None => None };
        Ok(json!({"scope":self.scope,"pointer_revision":revision,"active_release":active,"runtime_or_global_admission":false,"P7":false}))
    }

    fn manifest_path(&self, release: &str) -> Result<PathBuf> {
        identifier(release)?;
        self.workspace.resolve(&Path::new(".wuji4-catalog/releases").join(release).join("manifest.json"))
    }

    fn load(&self, lock: &ReleaseLock) -> Result<LoadedRelease> {
        if lock.schema_version != 1 || lock.registry_scope != self.scope {
            return Err(Error::new(ErrorKind::ScopeDenied,"locked registry scope/schema mismatch"));
        }
        let bytes = bounded_file(&self.manifest_path(&lock.release)?)?;
        if strict_json::sha256(&bytes) != lock.manifest_sha256 {
            return Err(Error::new(ErrorKind::HashMismatch,"immutable manifest changed"));
        }
        let manifest: ReleaseManifest = serde_json::from_value(strict_json::parse(&bytes)?)?;
        if manifest.schema_version != 1 || manifest.scope != self.scope || manifest.release != lock.release || manifest.files.is_empty() || manifest.files.len() > 256 || manifest.required_roots.is_empty() {
            return Err(Error::new(ErrorKind::Shape,"bounded exact catalog manifest and mandatory roots required"));
        }
        let mut catalog = PreparedCatalog::new(&manifest.scope,&manifest.release,manifest.required_roots.clone());
        let mut identities = BTreeMap::new();
        let mut paths = BTreeSet::new();
        let mut definitions = Vec::new();
        let mut total_bytes = bytes.len();
        for entry in &manifest.files {
            file_name(&entry.path)?;
            if !paths.insert(entry.path.clone()) || identities.insert(entry.reference.id.clone(),entry.reference.clone()).is_some() {
                return Err(Error::new(ErrorKind::Shape,"duplicate catalog identity or filename"));
            }
            let path = self.workspace.resolve(&Path::new(".wuji4-catalog/releases").join(&manifest.release).join(&entry.path))?;
            let file = bounded_file(&path)?;
            total_bytes += file.len();
            if total_bytes > 8 * strict_json::MAX_INPUT_BYTES { return Err(Error::new(ErrorKind::BudgetExhausted,"catalog total file cap 8 MiB")); }
            catalog.register_derived_fragment(entry.reference.clone(),&file)?;
            definitions.push((entry.reference.id.clone(),strict_json::parse(&file)?));
        }
        let mut consumers = BTreeSet::new();
        let schemas = Schemas::frozen()?;
        for (id,definition) in definitions {
            for name in ["dependencies","conflicts"] {
                let references: Vec<ExactRef> = serde_json::from_value(definition[name].clone())?;
                for reference in references {
                    schemas.check_definition("ExactRef",&serde_json::to_value(&reference)?)?;
                    if identities.get(&reference.id) != Some(&reference) {
                        return Err(Error::new(ErrorKind::Reference,"definition has an unresolved exact reference"));
                    }
                    if name == "dependencies" { consumers.insert((reference.id,id.clone())); }
                }
            }
        }
        let mut compositions = BTreeMap::new();
        for entry in &manifest.files {
            let mut roots = manifest.required_roots.clone();
            if !roots.contains(&entry.reference) { roots.push(entry.reference.clone()); }
            let prepared = catalog.compose(&roots,&BTreeMap::new(),strict_json::MAX_INPUT_BYTES)?;
            compositions.insert(entry.reference.id.clone(),prepared["composition_hash"].as_str().unwrap().to_owned());
        }
        Ok(LoadedRelease { manifest,catalog,consumers,compositions })
    }

    pub fn stage(&mut self, permit: &LocalCatalogPermit, bundle: &ReleaseBundle) -> Result<ReleaseLock> {
        permit.check(self)?;
        identifier(&bundle.manifest.release)?;
        if bundle.manifest.scope != self.scope || bundle.definitions.len() != bundle.manifest.files.len() || bundle.manifest.files.len() > 256 {
            return Err(Error::new(ErrorKind::ScopeDenied,"candidate definitions and local registry scope must match exactly"));
        }
        let directory = self.workspace.resolve(&Path::new(".wuji4-catalog/releases").join(&bundle.manifest.release))?;
        fs::create_dir_all(directory)?;
        for entry in &bundle.manifest.files {
            file_name(&entry.path)?;
            let value = bundle.definitions.get(&entry.path).ok_or_else(||Error::new(ErrorKind::Reference,"manifest definition missing"))?;
            let bytes = strict_json::canonical(value)?;
            if strict_json::sha256(&bytes) != entry.reference.sha256 {
                return Err(Error::new(ErrorKind::HashMismatch,"candidate file hash differs from exact manifest reference"));
            }
            immutable_file(&self.workspace,&Path::new(".wuji4-catalog/releases").join(&bundle.manifest.release).join(&entry.path),&bytes)?;
        }
        let bytes = strict_json::canonical(&serde_json::to_value(&bundle.manifest)?)?;
        immutable_file(&self.workspace,&self.manifest_path(&bundle.manifest.release)?,&bytes)?;
        let lock = ReleaseLock { schema_version:1,registry_scope:self.scope.clone(),release:bundle.manifest.release.clone(),manifest_sha256:strict_json::sha256(&bytes) };
        self.load(&lock)?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let previous: Option<String> = transaction.query_row("SELECT manifest_hash FROM catalog_releases WHERE release_id=?1",[&lock.release],|row|row.get(0)).optional()?;
        if previous.as_ref().is_some_and(|hash| hash != &lock.manifest_sha256) {
            return Err(Error::new(ErrorKind::HashMismatch,"release ID already has another immutable manifest"));
        }
        transaction.execute("INSERT OR IGNORE INTO catalog_releases(release_id,manifest_hash,state) VALUES(?1,?2,'candidate')",params![lock.release,lock.manifest_sha256])?;
        transaction.commit()?;
        Ok(lock)
    }

    fn registered(&self, lock: &ReleaseLock, require_published: bool) -> Result<()> {
        if lock.registry_scope != self.scope || lock.schema_version != 1 {
            return Err(Error::new(ErrorKind::ScopeDenied,"release lock belongs to another registry"));
        }
        let stored: Option<(String,String)> = self.connection.query_row("SELECT manifest_hash,state FROM catalog_releases WHERE release_id=?1",[&lock.release],|row|Ok((row.get(0)?,row.get(1)?))).optional()?;
        match stored {
            Some((hash,state)) if hash == lock.manifest_sha256 && state != "withdrawn" && (!require_published || state == "published_local") => Ok(()),
            Some((hash,_)) if hash != lock.manifest_sha256 => Err(Error::new(ErrorKind::HashMismatch,"registered manifest differs from lock")),
            _ => Err(Error::new(ErrorKind::ValidationStale,"release missing, withdrawn or not locally published")),
        }
    }

    pub fn lock(&self, release: &str, require_published: bool) -> Result<ReleaseLock> {
        identifier(release)?;
        let hash: String = self.connection.query_row("SELECT manifest_hash FROM catalog_releases WHERE release_id=?1",[release],|row|row.get(0))?;
        let lock = ReleaseLock { schema_version:1,registry_scope:self.scope.clone(),release:release.to_owned(),manifest_sha256:hash };
        self.registered(&lock,require_published)?;
        self.load(&lock)?;
        Ok(lock)
    }

    pub fn lock_active(&self) -> Result<ReleaseLock> {
        let release: Option<String> = self.connection.query_row("SELECT active_release FROM registry_meta WHERE singleton=1",[],|row|row.get(0))?;
        self.lock(&release.ok_or_else(||Error::new(ErrorKind::Reference,"no locally active catalog release"))?,true)
    }

    pub fn validate_local(&mut self, permit: &LocalCatalogPermit, lock: &ReleaseLock) -> Result<Value> {
        permit.check(self)?;
        self.registered(lock,false)?;
        let loaded = self.load(lock)?;
        let validation_hash = strict_json::digest(&json!({"lock":lock,"compositions":loaded.compositions}))?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = transaction.execute("UPDATE catalog_releases SET state='validated_local',validation_hash=?1 WHERE release_id=?2 AND manifest_hash=?3 AND state IN ('candidate','validated_local')",params![validation_hash,lock.release,lock.manifest_sha256])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"only a nonwithdrawn candidate can receive new local validation")); }
        Self::replace_index(&transaction,&lock.release,&loaded.consumers)?;
        transaction.commit()?;
        Ok(json!({"lock":lock,"validation_hash":validation_hash,"consumer_compositions":loaded.compositions,"scope":"deterministic-local-composition","professional_effectiveness":"not_claimed","runtime_or_global_admission":false}))
    }

    fn replace_index(transaction: &Transaction<'_>, release: &str, consumers: &BTreeSet<(String,String)>) -> Result<()> {
        transaction.execute("DELETE FROM catalog_consumers WHERE release_id=?1",[release])?;
        for (source,consumer) in consumers {
            transaction.execute("INSERT INTO catalog_consumers VALUES(?1,?2,?3)",params![release,source,consumer])?;
        }
        Ok(())
    }

    pub fn publish_local(&mut self, permit: &LocalCatalogPermit, lock: &ReleaseLock, expected_revision: u64, key: &str) -> Result<Value> {
        permit.check(self)?;
        let operation = strict_json::digest(&json!({"operation":"publish-local","lock":lock,"expected_revision":expected_revision}))?;
        {
            let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            if let Some(result) = event(&transaction,key,&operation)? { return Ok(result); }
        }
        self.registered(lock,false)?;
        let loaded = self.load(lock)?;
        let validation_hash = strict_json::digest(&json!({"lock":lock,"compositions":loaded.compositions}))?;
        let expected = i64::try_from(expected_revision).map_err(|_|Error::new(ErrorKind::RevisionConflict,"pointer revision overflow"))?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some(result) = event(&transaction,key,&operation)? { return Ok(result); }
        let stored: (String,String,Option<String>) = transaction.query_row("SELECT manifest_hash,state,validation_hash FROM catalog_releases WHERE release_id=?1",[&lock.release],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?;
        if stored.0 != lock.manifest_sha256 || !["validated_local","published_local"].contains(&stored.1.as_str()) || stored.2.as_deref() != Some(&validation_hash) {
            return Err(Error::new(ErrorKind::ValidationStale,"full release requires current per-consumer local validation"));
        }
        let next = expected.checked_add(1).ok_or_else(||Error::new(ErrorKind::RevisionConflict,"pointer revision overflow"))?;
        let changed = transaction.execute("UPDATE registry_meta SET active_release=?1,pointer_revision=?2 WHERE singleton=1 AND pointer_revision=?3",params![lock.release,next,expected])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"active pointer CAS failed")); }
        transaction.execute("UPDATE catalog_releases SET state='published_local' WHERE release_id=?1",[&lock.release])?;
        Self::replace_index(&transaction,&lock.release,&loaded.consumers)?;
        let result = json!({"active_release":lock,"pointer_revision":next,"runtime_or_global_admission":false,"observation_kind":"historical_transaction_result_not_current_eligibility"});
        record_event(&transaction,key,&operation,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn withdraw(&mut self, permit: &LocalCatalogPermit, lock: &ReleaseLock, expected_revision: u64, key: &str) -> Result<Value> {
        permit.check(self)?;
        if lock.registry_scope != self.scope || lock.schema_version != 1 {
            return Err(Error::new(ErrorKind::ScopeDenied,"withdrawal lock differs from registry"));
        }
        let operation = strict_json::digest(&json!({"operation":"withdraw","lock":lock,"expected_revision":expected_revision}))?;
        let expected = i64::try_from(expected_revision).map_err(|_|Error::new(ErrorKind::RevisionConflict,"pointer revision overflow"))?;
        let next = expected.checked_add(1).ok_or_else(||Error::new(ErrorKind::RevisionConflict,"pointer revision overflow"))?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some(result) = event(&transaction,key,&operation)? { return Ok(result); }
        let changed = transaction.execute("UPDATE registry_meta SET active_release=CASE WHEN active_release=?1 THEN NULL ELSE active_release END,pointer_revision=?2 WHERE singleton=1 AND pointer_revision=?3",params![lock.release,next,expected])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"withdrawal pointer CAS failed")); }
        let changed = transaction.execute("UPDATE catalog_releases SET state='withdrawn' WHERE release_id=?1 AND manifest_hash=?2 AND state!='withdrawn'",params![lock.release,lock.manifest_sha256])?;
        if changed != 1 { return Err(Error::new(ErrorKind::RevisionConflict,"withdrawal release identity/state changed")); }
        let result = json!({"withdrawn":lock,"pointer_revision":next,"new_actions_denied":true,"old_task_lock_rewritten":false});
        record_event(&transaction,key,&operation,&result)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn compose_locked(&self, lock: &ReleaseLock, roots: &[ExactRef], slots: &BTreeMap<String,Value>, byte_cap: usize) -> Result<Value> {
        self.registered(lock,true)?;
        let loaded = self.load(lock)?;
        let mut result = loaded.catalog.compose(roots,slots,byte_cap)?;
        result["release_lock"] = serde_json::to_value(lock)?;
        if strict_json::canonical(&result)?.len() > byte_cap {
            return Err(Error::new(ErrorKind::BudgetExhausted,"complete locked contract exceeds byte cap; not truncated"));
        }
        Ok(result)
    }

    pub(crate) fn compose_many_locked(&self, lock: &ReleaseLock, assemblies: &[Vec<ExactRef>], byte_cap: usize) -> Result<Vec<Value>> {
        self.registered(lock,true)?;
        let loaded=self.load(lock)?;
        let mut result=Vec::new();
        for roots in assemblies { result.push(loaded.catalog.compose(roots,&BTreeMap::new(),byte_cap)?); }
        if strict_json::canonical(&serde_json::to_value(&result)?)?.len()>byte_cap {
            return Err(Error::new(ErrorKind::BudgetExhausted,"complete recipe contracts exceed byte cap; not truncated"));
        }
        Ok(result)
    }

    pub fn repair_index(&mut self, permit: &LocalCatalogPermit, lock: &ReleaseLock) -> Result<Value> {
        permit.check(self)?;
        self.registered(lock,false)?;
        let loaded = self.load(lock)?;
        let transaction = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        Self::replace_index(&transaction,&lock.release,&loaded.consumers)?;
        transaction.commit()?;
        Ok(json!({"release_lock":lock,"derived_edges":loaded.consumers.len(),"definitions_changed":false,"active_pointer_changed":false}))
    }

    pub fn impact_page(&self, lock: &ReleaseLock, source: &ExactRef, offset: usize, page_size: usize) -> Result<Value> {
        if page_size == 0 || page_size > 64 { return Err(Error::new(ErrorKind::BudgetExhausted,"impact page size must be 1..64")); }
        self.registered(lock,false)?;
        let loaded = self.load(lock)?;
        if !loaded.manifest.files.iter().any(|entry| &entry.reference == source) {
            return Err(Error::new(ErrorKind::Reference,"impact source must match an exact manifest reference"));
        }
        let mut statement = self.connection.prepare("SELECT source_id,consumer_id FROM catalog_consumers WHERE release_id=?1 ORDER BY source_id,consumer_id LIMIT 65537")?;
        let observed: BTreeSet<(String,String)> = statement.query_map([&lock.release],|row|Ok((row.get(0)?,row.get(1)?)))?.collect::<std::result::Result<_,_>>()?;
        if observed != loaded.consumers {
            return Err(Error::new(ErrorKind::ValidationStale,"consumer index incomplete or corrupt; explicit repair required before impact"));
        }
        let mut closure = BTreeSet::from([source.id.clone()]);
        let mut pending = vec![source.id.clone()];
        while let Some(current) = pending.pop() {
            for (dependency,consumer) in &loaded.consumers {
                if dependency == &current && closure.insert(consumer.clone()) { pending.push(consumer.clone()); }
            }
        }
        if offset > closure.len() { return Err(Error::new(ErrorKind::Shape,"impact offset beyond full closure")); }
        let end = offset.saturating_add(page_size).min(closure.len());
        let ids: Vec<_> = closure.into_iter().collect();
        let references: Vec<_> = ids[offset..end].iter().map(|id| &loaded.manifest.files.iter().find(|entry| &entry.reference.id == id).unwrap().reference).collect();
        Ok(json!({"release_lock":lock,"source":source,"total":ids.len(),"offset":offset,"references":references,
            "next_offset":if end < ids.len() { Some(end) } else { None },"all_pages_required":true,"complete":end == ids.len() && offset == 0,"index_verified":true}))
    }
}
