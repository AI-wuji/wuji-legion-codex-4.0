use serde_json::{Value,json};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path,PathBuf};
use std::sync::atomic::{AtomicU64,Ordering};
use std::time::{SystemTime,UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::recipe::{RecipeRequest,RecipeInstance,TaskKind};
use wuji4::registry::{CatalogRegistry,CatalogFile,LocalCatalogPermit,ReleaseBundle,ReleaseManifest};
use wuji4::store::Store;
use wuji4::strict_json;

static NEXT_ROOT_ID: AtomicU64 = AtomicU64::new(0);

fn root(label: &str) -> PathBuf {
    let base=Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/recipe-acceptance");
    fs::create_dir_all(&base).unwrap();
    loop {
        let candidate=base.join(format!("{label}-{}-{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),NEXT_ROOT_ID.fetch_add(1,Ordering::Relaxed)));
        match fs::create_dir(&candidate) {
            Ok(())=>return candidate,
            Err(error) if error.kind()==std::io::ErrorKind::AlreadyExists=>continue,
            Err(error)=>panic!("unable to create isolated recipe fixture: {error}"),
        }
    }
}

fn fragment(registry: &CatalogRegistry,id: &str,dependencies: Vec<ExactRef>,fields: Value,required: &[&str]) -> (ExactRef,Value) {
    let value=json!({"id":id,"scope":registry.scope(),"release":"r1","revision":1,"dependencies":dependencies,
        "conflicts":[],"fields":fields,"required_fields":required,"allowed_slots":{}});
    (ExactRef { id:id.into(),r#type:"file".into(),scope:registry.scope().into(),release:"r1".into(),revision:1,
        sha256:strict_json::digest(&value).unwrap(),schema_version:1 },value)
}

fn setup() -> (Store,CatalogRegistry,RecipeRequest) {
    let workspace=root("workspace");
    let catalog=root("catalog");
    let mut store=Store::open(&workspace).unwrap();
    fs::write(workspace.join("input.txt"),b"task-specific project data").unwrap();
    let input=store.register_local_input("user/input",Path::new("input.txt")).unwrap();
    let permit=LocalCatalogPermit::confirm(&catalog,"confirm-isolated-local-catalog").unwrap();
    let mut registry=CatalogRegistry::init(&catalog,&permit).unwrap();
    let (policy,policy_value)=fragment(&registry,"policy",vec![],json!({"authorization_required":true,"acceptance_required":true}),&["authorization_required","acceptance_required"]);
    let (expert,expert_value)=fragment(&registry,"narrow-reader",vec![policy.clone()],json!({"role":"project-text-reader","task":"read current source",
        "process":["inspect exact input","return bounded analysis"],"constraints":["do not invent evidence"],"output":"bounded text result",
        "specialty":"local UTF-8 source analysis","input_contract":"registered project file","tool_contract":"read-only bounded input",
        "acceptance_contract":"current source, bounded output and separate review"}),&[]);
    let bundle=ReleaseBundle { manifest:ReleaseManifest { schema_version:1,scope:registry.scope().into(),release:"r1".into(),required_roots:vec![policy.clone()],
        files:vec![CatalogFile { path:"policy.json".into(),reference:policy.clone() },CatalogFile { path:"reader.json".into(),reference:expert.clone() }] },
        definitions:BTreeMap::from([("policy.json".into(),policy_value),("reader.json".into(),expert_value)]) };
    let lock=registry.stage(&permit,&bundle).unwrap();
    registry.validate_local(&permit,&lock).unwrap();
    registry.publish_local(&permit,&lock,0,"publish").unwrap();
    let instances=(0..2).map(|index|RecipeInstance { instance_id:format!("instance-{index}"),owner:format!("lead-{index}"),definition_ref:expert.clone(),
        mandatory_roots:vec![policy.clone()],depends_on:vec![],inputs:vec![input.clone()],write_roots:vec![format!("outputs/{index}.txt")],
        acceptance_ids:vec!["source-current".into(),"bounded-output".into()],task_kind:if index==0 { TaskKind::Code } else { TaskKind::Text } }).collect();
    (store,registry,RecipeRequest { task_id:"recipe-task".into(),release_lock:lock,instances,max_parallel_instances:2,byte_cap:100000 })
}

#[test]
fn shared_exact_expert_has_distinct_instances_and_never_reports_started_agents() {
    let (store,registry,request)=setup();
    let prepared=store.prepare_recipe(&registry,&request).unwrap();
    assert_eq!(prepared["shared_definitions"].as_object().unwrap().len(),1);
    assert_eq!(prepared["instances"].as_array().unwrap().len(),2);
    assert_eq!(prepared["instances"][0]["requested_model"],"gpt-6.1-sol");
    assert_eq!(prepared["instances"][0]["requested_effort"],"high");
    assert_eq!(prepared["instances"][1]["requested_model"],"inherit_current_selection");
    assert_eq!(prepared["instances"][1]["requested_effort"],"inherit");
    assert_eq!(prepared["actual_agents_started"],0);
    assert_eq!(prepared["execution_authority"],false);
    assert_eq!(prepared["runtime_admission"],false);
    assert_eq!(prepared["user_communicator"],"aji");
}

#[test]
fn cyclic_recipe_overlapping_writes_unsafe_paths_and_quotas_are_not_dispatched() {
    let (store,registry,mut request)=setup();
    request.instances[1].write_roots=request.instances[0].write_roots.clone();
    assert_eq!(store.prepare_recipe(&registry,&request).unwrap_err().kind,ErrorKind::OwnerConflict);
    request.instances[1].write_roots=vec!["outputs/../escape.txt".into()];
    assert_eq!(store.prepare_recipe(&registry,&request).unwrap_err().kind,ErrorKind::PathDenied);
    request.instances[1].write_roots=vec!["outputs/other.txt".into()];
    request.instances[0].depends_on=vec!["instance-1".into()];
    request.instances[1].depends_on=vec!["instance-0".into()];
    assert_eq!(store.prepare_recipe(&registry,&request).unwrap_err().kind,ErrorKind::DependencyCycle);
    request.instances[0].depends_on.clear();
    request.instances[1].depends_on.clear();
    request.max_parallel_instances=4;
    assert_eq!(store.prepare_recipe(&registry,&request).unwrap_err().kind,ErrorKind::BudgetExhausted);
    request.max_parallel_instances=2;
    request.byte_cap=80;
    assert_eq!(store.prepare_recipe(&registry,&request).unwrap_err().kind,ErrorKind::BudgetExhausted);
}

#[test]
fn recipe_cannot_omit_mandatory_policy_or_use_cross_project_input() {
    let (store,registry,mut request)=setup();
    request.instances[0].mandatory_roots.clear();
    assert_eq!(store.prepare_recipe(&registry,&request).unwrap_err().kind,ErrorKind::RequiredWeakened);
    let (other,_,_)=setup();
    assert_eq!(other.prepare_recipe(&registry,&request).unwrap_err().kind,ErrorKind::ScopeDenied);
}
