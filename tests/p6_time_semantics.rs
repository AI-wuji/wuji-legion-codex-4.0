use serde_json::{Value,json};
use std::fs;
use std::path::{Path,PathBuf};
use std::sync::atomic::{AtomicU64,Ordering};
use std::time::{SystemTime,UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::store::Store;
use wuji4::strict_json;
use wuji4::time::{Rounding,TimeConversion,TimeQuantity,TimeUnit};

static NEXT_FIXTURE_ID: AtomicU64 = AtomicU64::new(0);

fn setup() -> (PathBuf,Store,ExactRef) {
    let base=Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/time-acceptance");
    fs::create_dir_all(&base).unwrap();
    let root=loop {
        let candidate=base.join(format!("{}-{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),NEXT_FIXTURE_ID.fetch_add(1,Ordering::Relaxed)));
        match fs::create_dir(&candidate) {
            Ok(())=>break candidate,
            Err(error) if error.kind()==std::io::ErrorKind::AlreadyExists=>continue,
            Err(error)=>panic!("unable to create isolated time fixture: {error}"),
        }
    };
    fs::write(root.join("origin.txt"),b"isolated timeline origin and adopted profile fixture").unwrap();
    let mut store=Store::open(&root).unwrap();
    let origin=store.register_local_input("user/origin",Path::new("origin.txt")).unwrap();
    (root,store,origin)
}

fn basis(root: &Path,store: &mut Store,origin: &ExactRef,id: &str,unit: &str,numerator: u64,denominator: u64) -> ExactRef {
    let rate=json!({"unit":unit,"per_unit":"second","profile_ref":origin,"value":{"numerator":numerator,"denominator":denominator}});
    let rate_path=format!("{id}-rate.json");
    fs::write(root.join(&rate_path),strict_json::canonical(&rate).unwrap()).unwrap();
    let rate_reference=store.register_local_input(&format!("user/{id}-rate"),Path::new(&rate_path)).unwrap();
    let value=json!({"unit":unit,"origin_ref":origin,"rate":rate_reference});
    let path=format!("{id}.json");
    fs::write(root.join(&path),strict_json::canonical(&value).unwrap()).unwrap();
    store.register_local_input(&format!("user/{id}"),Path::new(&path)).unwrap()
}

fn duration(numerator: i64,denominator: u64) -> TimeQuantity {
    TimeQuantity { numerator,denominator,unit:TimeUnit::Second,basis_ref:None,rounding:Rounding::Exact }
}

fn convert(store: &Store,quantity: TimeQuantity,unit: TimeUnit,basis: Option<ExactRef>,rounding: Rounding) -> Value {
    store.convert_time(&TimeConversion { quantity,target_unit:unit,target_basis_ref:basis,rounding }).unwrap()
}

#[test]
fn t64_units_adopted_versions_current_hashes_and_explicit_rounding_are_separate() {
    let (root,mut store,origin)=setup();
    let frames=basis(&root,&mut store,&origin,"frames","frame",30000,1001);
    let samples=basis(&root,&mut store,&origin,"samples","sample",48000,1);
    let exact=convert(&store,duration(1,1),TimeUnit::Frame,Some(frames.clone()),Rounding::Exact);
    assert_eq!(exact["quantity"]["numerator"],30000);
    assert_eq!(exact["quantity"]["denominator"],1001);
    assert_eq!(exact["measured_media_profile"],"not_claimed");
    assert_eq!(convert(&store,duration(1,1),TimeUnit::Frame,Some(frames.clone()),Rounding::NearestEven)["quantity"]["numerator"],30);
    let frames_quantity=TimeQuantity { numerator:30000,denominator:1,unit:TimeUnit::Frame,basis_ref:Some(frames.clone()),rounding:Rounding::Exact };
    let seconds=convert(&store,frames_quantity.clone(),TimeUnit::Second,None,Rounding::Exact);
    assert_eq!(seconds["quantity"]["numerator"],1001);
    assert_eq!(convert(&store,frames_quantity,TimeUnit::Sample,Some(samples.clone()),Rounding::Exact)["quantity"]["numerator"],48048000);
    assert_eq!(store.convert_time(&TimeConversion { quantity:duration(1,1),target_unit:TimeUnit::Sample,target_basis_ref:Some(frames.clone()),rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::Shape);
    let mut nonexistent=frames.clone();
    nonexistent.revision=2;
    assert_eq!(store.convert_time(&TimeConversion { quantity:duration(1,1),target_unit:TimeUnit::Frame,target_basis_ref:Some(nonexistent),rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::Reference);
    fs::write(root.join("frames.json"),b"changed profile").unwrap();
    assert_eq!(store.convert_time(&TimeConversion { quantity:duration(1,1),target_unit:TimeUnit::Frame,target_basis_ref:Some(frames),rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::ValidationStale);
    fs::write(root.join("unadopted.json"),b"{}").unwrap();
    let forged=ExactRef { id:"user/unadopted".into(),sha256:strict_json::sha256(b"{}"),..samples };
    assert_eq!(store.convert_time(&TimeConversion { quantity:duration(1,1),target_unit:TimeUnit::Sample,target_basis_ref:Some(forged),rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::Reference);
}

#[test]
fn nearest_even_negative_floor_ceil_invalid_bases_and_integer_overflow_fail_safely() {
    let (root,mut store,origin)=setup();
    for (numerator,expected) in [(1,0),(3,2),(5,2),(-1,0),(-3,-2),(-5,-2)] {
        assert_eq!(convert(&store,duration(numerator,2),TimeUnit::Second,None,Rounding::NearestEven)["quantity"]["numerator"],expected);
    }
    assert_eq!(convert(&store,duration(-1,2),TimeUnit::Second,None,Rounding::Floor)["quantity"]["numerator"],-1);
    assert_eq!(convert(&store,duration(-1,2),TimeUnit::Second,None,Rounding::Ceil)["quantity"]["numerator"],0);
    assert_eq!(store.convert_time(&TimeConversion { quantity:duration(1,0),target_unit:TimeUnit::Second,target_basis_ref:None,rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::Shape);
    assert_eq!(store.convert_time(&TimeConversion { quantity:duration(1,1),target_unit:TimeUnit::Tick,target_basis_ref:None,rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::Reference);
    let fast=basis(&root,&mut store,&origin,"fast","sample",u64::MAX,1);
    assert_eq!(store.convert_time(&TimeConversion { quantity:duration(i64::MAX,1),target_unit:TimeUnit::Sample,target_basis_ref:Some(fast),rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::BudgetExhausted);
}

#[test]
fn unrelated_origins_are_not_implicitly_rebased_and_cross_scope_bases_are_denied() {
    let (root,mut store,origin)=setup();
    let frames=basis(&root,&mut store,&origin,"frames","frame",24,1);
    fs::write(root.join("other.txt"),b"another origin").unwrap();
    let other=store.register_local_input("user/other",Path::new("other.txt")).unwrap();
    let samples=basis(&root,&mut store,&other,"samples","sample",48000,1);
    let quantity=TimeQuantity { numerator:24,denominator:1,unit:TimeUnit::Frame,basis_ref:Some(frames.clone()),rounding:Rounding::Exact };
    assert_eq!(store.convert_time(&TimeConversion { quantity,target_unit:TimeUnit::Sample,target_basis_ref:Some(samples),rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::Reference);
    let (_,other_store,_)=setup();
    assert_eq!(other_store.convert_time(&TimeConversion { quantity:duration(1,1),target_unit:TimeUnit::Frame,target_basis_ref:Some(frames),rounding:Rounding::Exact }).unwrap_err().kind,ErrorKind::ScopeDenied);
}
