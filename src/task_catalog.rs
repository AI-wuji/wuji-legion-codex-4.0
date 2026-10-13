use crate::error::{Error, ErrorKind, Result};
use crate::graph::ExactRef;
use crate::policy::Workspace;
use crate::registry::{CatalogRegistry, LocalCatalogPermit, ReleaseLock};
use crate::store::Store;
use crate::strict_json;
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TaskCatalogBinding {
    registry_root: PathBuf,
    release_lock: ReleaseLock,
    roots: Vec<ExactRef>,
    composition_sha256: String,
}

pub(crate) struct CatalogActionGuard { _registry: CatalogRegistry }

impl TaskCatalogBinding {
    pub(crate) fn digest(&self) -> Result<String> { strict_json::digest(&serde_json::to_value(self)?) }

    pub(crate) fn hold(&self) -> Result<CatalogActionGuard> {
        LocalCatalogPermit::confirm(&self.registry_root,"confirm-isolated-local-catalog")?;
        let mut registry = CatalogRegistry::open_existing(&self.registry_root)?;
        registry.begin_action_guard()?;
        let composition = registry.compose_locked(&self.release_lock,&self.roots,&BTreeMap::new(),65536)?;
        if strict_json::digest(&composition)? != self.composition_sha256 {
            return Err(Error::new(ErrorKind::HashMismatch,"task catalog composition changed; no current-pointer fallback"));
        }
        Ok(CatalogActionGuard { _registry: registry })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::{CatalogFile,ReleaseBundle,ReleaseManifest};
    use std::fs;
    use std::time::{SystemTime,UNIX_EPOCH};

    #[test]
    fn short_catalog_action_guard_serializes_withdrawal_without_holding_model_wait() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/catalog-action-guard")
            .join(format!("{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
        fs::create_dir_all(&root).unwrap();
        let permit = LocalCatalogPermit::confirm(&root,"confirm-isolated-local-catalog").unwrap();
        let mut registry = CatalogRegistry::init(&root,&permit).unwrap();
        let value = json!({"id":"base","scope":registry.scope(),"release":"r1","revision":1,"dependencies":[],
            "conflicts":[],"fields":{"authorization_required":true},"required_fields":["authorization_required"],"allowed_slots":{}});
        let reference = ExactRef { id:"base".into(),r#type:"file".into(),scope:registry.scope().into(),release:"r1".into(),
            revision:1,sha256:strict_json::digest(&value).unwrap(),schema_version:1 };
        let bundle = ReleaseBundle { manifest:ReleaseManifest { schema_version:1,scope:registry.scope().into(),release:"r1".into(),
            required_roots:vec![reference.clone()],files:vec![CatalogFile { path:"base.json".into(),reference:reference.clone() }] },
            definitions:BTreeMap::from([("base.json".into(),value)]) };
        let lock = registry.stage(&permit,&bundle).unwrap();
        registry.validate_local(&permit,&lock).unwrap();
        registry.publish_local(&permit,&lock,0,"publish").unwrap();
        let composition = registry.compose_locked(&lock,&[reference.clone()],&BTreeMap::new(),65536).unwrap();
        let binding = TaskCatalogBinding { registry_root:fs::canonicalize(&root).unwrap(),release_lock:lock.clone(),
            roots:vec![reference],composition_sha256:strict_json::digest(&composition).unwrap() };
        let guard = binding.hold().unwrap();
        assert_eq!(registry.withdraw(&permit,&lock,1,"withdraw").unwrap_err().kind,ErrorKind::Storage);
        assert_eq!(registry.lock_active().unwrap(),lock);
        drop(guard);
        registry.withdraw(&permit,&lock,1,"withdraw").unwrap();
        assert_eq!(binding.hold().err().unwrap().kind,ErrorKind::ValidationStale);
    }
}

impl Store {
    pub fn plan_catalog_local(&mut self, envelope: &Value, registry_root: &Path, lock: &ReleaseLock,
        roots: &[ExactRef], confirmation: &str) -> Result<Value> {
        if confirmation != "confirm-isolated-catalog-task" {
            return Err(Error::new(ErrorKind::AuthorityDenied,"explicit isolated task catalog binding required"));
        }
        LocalCatalogPermit::confirm(self.workspace.root(),"confirm-isolated-local-catalog")?;
        LocalCatalogPermit::confirm(registry_root,"confirm-isolated-local-catalog")?;
        let mut registry = CatalogRegistry::open_existing(registry_root)?;
        registry.begin_action_guard()?;
        let composition = registry.compose_locked(lock,roots,&BTreeMap::new(),65536)?;
        let binding = TaskCatalogBinding {
            registry_root: Workspace::open(registry_root)?.root().to_owned(), release_lock:lock.clone(),
            roots:roots.to_vec(), composition_sha256:strict_json::digest(&composition)?,
        };
        let result = self.plan_internal_bound(envelope,None,Some(&binding))?;
        Ok(json!({"planned":result,"catalog_binding":binding,"runtime_or_professional_admission":false,
            "task_role_and_input_scope_rewritten":false}))
    }

    pub(crate) fn hold_task_catalog(&self, task: &str) -> Result<Option<CatalogActionGuard>> {
        let row: Option<(Option<String>,Option<String>,Option<String>)> = self.connection.query_row(
            "SELECT t.catalog_binding_hash,b.binding_hash,b.binding_json FROM tasks t LEFT JOIN task_catalog_locks b ON b.task_id=t.id WHERE t.id=?1 AND t.scope=?2",
            rusqlite::params![task,self.scope], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
        let Some((required,stored,text)) = row else {
            return Err(Error::new(ErrorKind::Reference,"catalog guard task not found"));
        };
        match (required,stored,text) {
            (None,None,None) => Ok(None),
            (Some(required),Some(stored),Some(text)) if required == stored => {
                let binding: TaskCatalogBinding = serde_json::from_value(strict_json::parse(text.as_bytes())?)?;
                if binding.digest()? != required {
                    return Err(Error::new(ErrorKind::HashMismatch,"task catalog binding hash changed"));
                }
                Ok(Some(binding.hold()?))
            }
            _ => Err(Error::new(ErrorKind::ValidationStale,"task catalog binding missing or inconsistent")),
        }
    }
}
