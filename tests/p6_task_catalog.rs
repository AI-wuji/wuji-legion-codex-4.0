use rusqlite::Connection;
use serde_json::{Value,json};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path,PathBuf};
use std::time::{SystemTime,UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::registry::{CatalogFile,CatalogRegistry,LocalCatalogPermit,ReleaseBundle,ReleaseLock,ReleaseManifest};
use wuji4::store::Store;
use wuji4::strict_json;

fn setup() -> (PathBuf,PathBuf,Store,CatalogRegistry,LocalCatalogPermit) {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/task-catalog-acceptance")
        .join(format!("{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    let task = root.join("task");
    let catalog = root.join("catalog");
    fs::create_dir_all(&task).unwrap();
    fs::create_dir_all(&catalog).unwrap();
    let permit = LocalCatalogPermit::confirm(&catalog,"confirm-isolated-local-catalog").unwrap();
    let registry = CatalogRegistry::init(&catalog,&permit).unwrap();
    let store = Store::open(&task).unwrap();
    (task,catalog,store,registry,permit)
}

fn publish(registry: &mut CatalogRegistry, permit: &LocalCatalogPermit, release: &str, expected: u64) -> (ReleaseLock,ExactRef) {
    let value = json!({"id":"mandatory","scope":registry.scope(),"release":release,"revision":1,"dependencies":[],
        "conflicts":[],"fields":{"authorization_required":true,"acceptance_required":true},
        "required_fields":["authorization_required","acceptance_required"],"allowed_slots":{}});
    let reference = ExactRef { id:"mandatory".into(),r#type:"file".into(),scope:registry.scope().into(),release:release.into(),revision:1,
        sha256:strict_json::digest(&value).unwrap(),schema_version:1 };
    let bundle = ReleaseBundle { manifest:ReleaseManifest { schema_version:1,scope:registry.scope().into(),release:release.into(),
        required_roots:vec![reference.clone()],files:vec![CatalogFile { path:"mandatory.json".into(),reference:reference.clone() }] },
        definitions:BTreeMap::from([("mandatory.json".into(),value)]) };
    let lock = registry.stage(permit,&bundle).unwrap();
    registry.validate_local(permit,&lock).unwrap();
    registry.publish_local(permit,&lock,expected,&format!("publish-{release}")).unwrap();
    (lock,reference)
}

fn blueprint(store: &Store, task: &str) -> Value {
    let mut value = json!({"schema_version":1,"contract_type":"WorkflowPlan",
        "payload":{"workflow_id":task,"version":"1","catalog_version":store.local_role_ref().release,
            "nodes":[{"id":"write","role_ref":store.local_role_ref(),"owner":"local-executor","revision":1,"inputs":[],
                "read_roots":[],"write_roots":[format!("{task}.txt")],
                "acceptance_ids":["local.file-readable","local.hash-current","local.utf8"],"status":"planned","execution_form":"program"}],
            "edges":[],"budget":{"max_candidates":8,"max_query_objects":20,"max_hops":3,"target_contract_bytes":1024,
                "target_evidence_bytes":1024,"hard_bytes_limit":null,"measured_tokens":null,"effective_token_limit":null,
                "wall_ms":300000,"max_parallel_workers":2,"max_extra_retries":6,"max_point_revisions":2,"max_no_progress":2}},
        "metadata":{"id":task,"type":"WorkflowPlan","scope":store.scope(),"schema_version":1,"revision":1,"owner":"aji-local",
            "authority":"review_proposal","status":"proposal","source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,
            "updated_at_utc_ms":1,"valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]}});
    value["metadata"]["content_hash"] = json!(strict_json::object_digest(&value).unwrap());
    value
}

fn bind(store: &mut Store, catalog: &Path, task: &str, lock: &ReleaseLock, reference: &ExactRef) -> Value {
    store.plan_catalog_local(&blueprint(store,task),catalog,lock,&[reference.clone()],"confirm-isolated-catalog-task").unwrap()
}

#[test]
fn t51_task_catalog_restart_pins_old_release_without_rewriting_handler_or_inputs() {
    let (task_root,catalog,mut store,mut registry,permit) = setup();
    let (first,source) = publish(&mut registry,&permit,"r1",0);
    let prepared = bind(&mut store,&catalog,"old",&first,&source);
    assert_eq!(prepared["runtime_or_professional_admission"],false);
    assert_eq!(prepared["task_role_and_input_scope_rewritten"],false);
    assert_eq!(prepared,bind(&mut store,&catalog,"old",&first,&source));
    assert_eq!(store.plan(&blueprint(&store,"old")).unwrap_err().kind,ErrorKind::EventConflict);
    let (second,other) = publish(&mut registry,&permit,"r2",1);
    assert_eq!(store.plan_catalog_local(&blueprint(&store,"old"),&catalog,&second,&[other.clone()],"confirm-isolated-catalog-task").unwrap_err().kind,ErrorKind::EventConflict);
    bind(&mut store,&catalog,"new",&second,&other);
    drop(store);
    let mut store = Store::open_existing(&task_root).unwrap();
    let old_claim = store.claim_local("old","write").unwrap();
    store.write_local_file(&old_claim,Path::new("old.txt"),b"old pinned task").unwrap();
    store.verify_local_file(&old_claim).unwrap();
    store.close_local_handler(&old_claim).unwrap();
    let new_claim = store.claim_local("new","write").unwrap();
    store.write_local_file(&new_claim,Path::new("new.txt"),b"new pinned task").unwrap();
    store.verify_local_file(&new_claim).unwrap();
    store.close_local_handler(&new_claim).unwrap();
    let database = Connection::open(task_root.join(".wuji4/state.sqlite")).unwrap();
    let saved: String = database.query_row("SELECT binding_json FROM task_catalog_locks WHERE task_id='old'",[],|row|row.get(0)).unwrap();
    assert_eq!(serde_json::from_str::<Value>(&saved).unwrap()["release_lock"],serde_json::to_value(&first).unwrap());
    assert_eq!(registry.lock_active().unwrap(),second);
    assert_eq!(store.status().unwrap()["open_slots"],0);
}

#[test]
fn t53_withdrawal_denies_actual_new_claim_and_claimed_write_without_rewriting_history() {
    let (task_root,catalog,mut store,mut registry,permit) = setup();
    let (replacement,new_source) = publish(&mut registry,&permit,"r0",0);
    let (lock,source) = publish(&mut registry,&permit,"r1",1);
    for task in ["accepted","claimed","waiting"] { bind(&mut store,&catalog,task,&lock,&source); }
    let accepted = store.claim_local("accepted","write").unwrap();
    let receipt = store.write_local_file(&accepted,Path::new("accepted.txt"),b"accepted before withdrawal").unwrap();
    let validation = store.verify_local_file(&accepted).unwrap();
    store.close_local_handler(&accepted).unwrap();
    let claimed = store.claim_local("claimed","write").unwrap();
    registry.withdraw(&permit,&lock,2,"withdraw").unwrap();
    assert_eq!(store.claim_local("waiting","write").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(store.write_local_file(&claimed,Path::new("claimed.txt"),b"must not execute").unwrap_err().kind,ErrorKind::ValidationStale);
    assert!(!task_root.join("claimed.txt").exists());
    assert_eq!(store.status().unwrap()["open_slots"],1);
    assert_eq!(store.write_local_file(&accepted,Path::new("accepted.txt"),b"accepted before withdrawal").unwrap(),receipt);
    assert_eq!(store.verify_local_file(&accepted).unwrap(),validation);
    assert_eq!(store.plan_catalog_local(&blueprint(&store,"withdrawn-new"),&catalog,&lock,&[source.clone()],"confirm-isolated-catalog-task").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(registry.publish_local(&permit,&lock,3,"revive").unwrap_err().kind,ErrorKind::ValidationStale);
    store.close_local_handler(&claimed).unwrap();
    assert_eq!(store.status().unwrap()["open_slots"],0);
    registry.publish_local(&permit,&replacement,3,"restore-nonwithdrawn-r0").unwrap();
    assert_eq!(registry.lock_active().unwrap(),replacement);
    bind(&mut store,&catalog,"replacement",&replacement,&new_source);
    let next = store.claim_local("replacement","write").unwrap();
    store.write_local_file(&next,Path::new("replacement.txt"),b"valid replacement").unwrap();
    store.verify_local_file(&next).unwrap();
    store.close_local_handler(&next).unwrap();
}

#[test]
fn catalog_publication_crash_fixture() {
    let Ok(root) = std::env::var("WUJI4_CATALOG_CRASH_FIXTURE") else { return; };
    let root = PathBuf::from(root);
    let database = Connection::open(root.join(".wuji4-catalog/registry.sqlite")).unwrap();
    database.execute_batch("BEGIN IMMEDIATE; UPDATE registry_meta SET active_release='r1',pointer_revision=999 WHERE singleton=1; UPDATE catalog_releases SET state='withdrawn' WHERE release_id='r2';").unwrap();
    fs::write(root.join("fixture-ready.txt"),b"uncommitted transaction ready").unwrap();
    std::thread::sleep(std::time::Duration::from_secs(30));
    panic!("fixture must be killed by its owner before publication commit");
}

#[test]
fn t53_os_process_kill_before_catalog_publication_commit_preserves_pointer_and_manifest() {
    let (_,catalog,_,mut registry,permit) = setup();
    let (first,_) = publish(&mut registry,&permit,"r1",0);
    let (second,_) = publish(&mut registry,&permit,"r2",1);
    let mut command = std::process::Command::new(std::env::current_exe().unwrap());
    command.args(["--exact","catalog_publication_crash_fixture","--nocapture"])
        .env("WUJI4_CATALOG_CRASH_FIXTURE",&catalog)
        .stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().unwrap();
    let start = std::time::Instant::now();
    while !catalog.join("fixture-ready.txt").exists() && start.elapsed() < std::time::Duration::from_secs(10) {
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    let ready = catalog.join("fixture-ready.txt").exists();
    child.kill().unwrap();
    let status = child.wait().unwrap();
    assert!(ready);
    assert!(!status.success());
    drop(registry);
    let registry = CatalogRegistry::open_existing(&catalog).unwrap();
    assert_eq!(registry.lock_active().unwrap(),second);
    assert_eq!(registry.status().unwrap()["pointer_revision"],2);
    assert_eq!(registry.lock("r1",true).unwrap(),first);
    assert_eq!(registry.lock("r2",true).unwrap(),second);
}

#[test]
fn task_catalog_corrupt_missing_definition_or_binding_fails_before_reserving_slot() {
    let (task_root,catalog,mut store,mut registry,permit) = setup();
    let (lock,source) = publish(&mut registry,&permit,"r1",0);
    bind(&mut store,&catalog,"guarded",&lock,&source);
    let path = catalog.join(".wuji4-catalog/releases/r1/mandatory.json");
    let bytes = fs::read(&path).unwrap();
    fs::write(&path,b"{}").unwrap();
    assert_eq!(store.claim_local("guarded","write").unwrap_err().kind,ErrorKind::HashMismatch);
    fs::write(&path,bytes).unwrap();
    let database = Connection::open(task_root.join(".wuji4/state.sqlite")).unwrap();
    database.execute("UPDATE task_catalog_locks SET binding_json='{}' WHERE task_id='guarded'",[]).unwrap();
    assert_eq!(store.claim_local("guarded","write").unwrap_err().kind,ErrorKind::Shape);
    database.execute("DELETE FROM task_catalog_locks WHERE task_id='guarded'",[]).unwrap();
    assert_eq!(store.claim_local("guarded","write").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(store.status().unwrap()["open_slots"],0);
    assert!(!task_root.join("guarded.txt").exists());
}
