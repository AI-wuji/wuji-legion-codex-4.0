use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{BTreeMap,BTreeSet};
use std::fs;
use std::path::{Path,PathBuf};
use std::time::{SystemTime,UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::registry::{CatalogFile,CatalogRegistry,LocalCatalogPermit,ReleaseBundle,ReleaseManifest};
use wuji4::strict_json;

fn setup() -> (PathBuf,CatalogRegistry,LocalCatalogPermit) {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/catalog-acceptance")
        .join(format!("{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(&root).unwrap();
    let permit = LocalCatalogPermit::confirm(&root,"confirm-isolated-local-catalog").unwrap();
    let registry = CatalogRegistry::init(&root,&permit).unwrap();
    (root,registry,permit)
}

fn fragment(scope: &str, release: &str, id: &str, dependencies: Vec<ExactRef>, fields: Value) -> (ExactRef,Value) {
    let value = json!({"id":id,"scope":scope,"release":release,"revision":1,"dependencies":dependencies,
        "conflicts":[],"fields":fields,"required_fields":[],"allowed_slots":{}});
    let reference = ExactRef { id:id.into(),r#type:"file".into(),scope:scope.into(),release:release.into(),revision:1,
        sha256:strict_json::digest(&value).unwrap(),schema_version:1 };
    (reference,value)
}

fn bundle(registry: &CatalogRegistry, release: &str, consumers: usize) -> ReleaseBundle {
    let (base,value) = fragment(registry.scope(),release,"white-hat",vec![],json!({"authorization_required":true}));
    let mut manifest = ReleaseManifest { schema_version:1,scope:registry.scope().into(),release:release.into(),
        required_roots:vec![base.clone()],files:vec![CatalogFile { path:"white-hat.json".into(),reference:base.clone() }] };
    let mut definitions = BTreeMap::from([("white-hat.json".into(),value)]);
    for index in 0..consumers {
        let id = format!("consumer-{index:03}");
        let (reference,value) = fragment(registry.scope(),release,&id,vec![base.clone()],json!({id.clone():index}));
        let path = format!("{id}.json");
        manifest.files.push(CatalogFile { path:path.clone(),reference });
        definitions.insert(path,value);
    }
    ReleaseBundle { manifest,definitions }
}

#[test]
fn catalog_stage_and_composition_validation_are_not_activation_or_professional_admission() {
    let (_,mut registry,permit) = setup();
    let candidate = bundle(&registry,"r1",3);
    let lock = registry.stage(&permit,&candidate).unwrap();
    assert_eq!(registry.stage(&permit,&candidate).unwrap(),lock);
    assert!(registry.status().unwrap()["active_release"].is_null());
    assert_eq!(registry.publish_local(&permit,&lock,0,"premature").unwrap_err().kind,ErrorKind::ValidationStale);
    let validation = registry.validate_local(&permit,&lock).unwrap();
    assert_eq!(validation["consumer_compositions"].as_object().unwrap().len(),4);
    assert_eq!(validation["professional_effectiveness"],"not_claimed");
    assert_eq!(validation["runtime_or_global_admission"],false);
    let first = registry.publish_local(&permit,&lock,0,"publish").unwrap();
    assert_eq!(first,registry.publish_local(&permit,&lock,0,"publish").unwrap());
    assert_eq!(registry.publish_local(&permit,&lock,1,"publish").unwrap_err().kind,ErrorKind::EventConflict);
    assert_eq!(registry.publish_local(&permit,&lock,0,"another").unwrap_err().kind,ErrorKind::RevisionConflict);
    assert_eq!(registry.status().unwrap()["pointer_revision"],1);
}

#[test]
fn t52_complete_large_impact_requires_all_pages_and_repairs_corrupt_derived_index() {
    let (root,mut registry,permit) = setup();
    let candidate = bundle(&registry,"r1",35);
    let source = candidate.manifest.required_roots[0].clone();
    let lock = registry.stage(&permit,&candidate).unwrap();
    registry.validate_local(&permit,&lock).unwrap();
    registry.publish_local(&permit,&lock,0,"publish").unwrap();
    let mut seen = BTreeSet::new();
    let mut offset = 0;
    loop {
        let page = registry.impact_page(&lock,&source,offset,7).unwrap();
        assert_eq!(page["total"],36);
        assert_eq!(page["complete"],false);
        for reference in page["references"].as_array().unwrap() {
            assert!(seen.insert(reference["id"].as_str().unwrap().to_owned()));
        }
        match page["next_offset"].as_u64() { Some(next) => offset=next as usize,None => break }
    }
    assert_eq!(seen.len(),36);
    assert_eq!(registry.impact_page(&lock,&source,0,64).unwrap()["complete"],true);
    let database = Connection::open(root.join(".wuji4-catalog/registry.sqlite")).unwrap();
    database.execute("DELETE FROM catalog_consumers WHERE consumer_id='consumer-031'",[]).unwrap();
    assert_eq!(registry.impact_page(&lock,&source,0,7).unwrap_err().kind,ErrorKind::ValidationStale);
    registry.repair_index(&permit,&lock).unwrap();
    assert_eq!(registry.impact_page(&lock,&source,0,64).unwrap()["total"],36);
    database.execute("INSERT INTO catalog_consumers VALUES('r1','white-hat','not-defined')",[]).unwrap();
    assert_eq!(registry.impact_page(&lock,&source,0,7).unwrap_err().kind,ErrorKind::ValidationStale);
    registry.repair_index(&permit,&lock).unwrap();
    assert_eq!(registry.status().unwrap()["pointer_revision"],1);
    let mut wrong = source;
    wrong.revision=2;
    assert_eq!(registry.impact_page(&lock,&wrong,0,7).unwrap_err().kind,ErrorKind::Reference);
}

#[test]
fn catalog_pointer_restart_fixed_locks_withdrawal_and_historical_replay_are_distinct() {
    let (root,mut registry,permit) = setup();
    let first = bundle(&registry,"r1",2);
    let first_lock = registry.stage(&permit,&first).unwrap();
    registry.validate_local(&permit,&first_lock).unwrap();
    let published = registry.publish_local(&permit,&first_lock,0,"publish-r1").unwrap();
    let old_task_lock = registry.lock_active().unwrap();
    let second = bundle(&registry,"r2",2);
    let second_lock = registry.stage(&permit,&second).unwrap();
    assert_eq!(registry.lock_active().unwrap(),old_task_lock);
    registry.validate_local(&permit,&second_lock).unwrap();
    registry.publish_local(&permit,&second_lock,1,"publish-r2").unwrap();
    drop(registry);
    let mut registry = CatalogRegistry::open_existing(&root).unwrap();
    assert_eq!(registry.lock_active().unwrap(),second_lock);
    assert_eq!(registry.compose_locked(&old_task_lock,&first.manifest.required_roots,&BTreeMap::new(),10000).unwrap()["release"],"r1");
    registry.withdraw(&permit,&old_task_lock,2,"withdraw-r1").unwrap();
    assert_eq!(registry.lock_active().unwrap(),second_lock);
    assert_eq!(registry.compose_locked(&old_task_lock,&first.manifest.required_roots,&BTreeMap::new(),10000).unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(registry.publish_local(&permit,&first_lock,0,"publish-r1").unwrap(),published);
    assert_eq!(registry.lock_active().unwrap(),second_lock);
    assert_eq!(registry.publish_local(&permit,&first_lock,3,"resurrect").unwrap_err().kind,ErrorKind::ValidationStale);
    registry.withdraw(&permit,&second_lock,3,"withdraw-active").unwrap();
    assert!(registry.status().unwrap()["active_release"].is_null());
}

#[test]
fn catalog_current_file_hash_and_scope_are_checked_even_for_unrelated_requested_root() {
    let (root,mut registry,permit) = setup();
    let candidate = bundle(&registry,"r1",2);
    let lock = registry.stage(&permit,&candidate).unwrap();
    registry.validate_local(&permit,&lock).unwrap();
    registry.publish_local(&permit,&lock,0,"publish").unwrap();
    fs::write(root.join(".wuji4-catalog/releases/r1/consumer-001.json"),b"{}").unwrap();
    assert_eq!(registry.compose_locked(&lock,&candidate.manifest.required_roots,&BTreeMap::new(),10000).unwrap_err().kind,ErrorKind::HashMismatch);
    assert_eq!(registry.status().unwrap_err().kind,ErrorKind::HashMismatch);
    registry.withdraw(&permit,&lock,1,"safety-withdraw").unwrap();
    assert!(registry.status().unwrap()["active_release"].is_null());
    let (_,other,_) = setup();
    assert_eq!(other.compose_locked(&lock,&candidate.manifest.required_roots,&BTreeMap::new(),10000).unwrap_err().kind,ErrorKind::ScopeDenied);
}
