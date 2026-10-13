use rusqlite::Connection;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::store::Store;
use wuji4::strict_json;

fn old_workspace() -> PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/migration-acceptance")
        .join(format!("{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(root.join(".wuji4")).unwrap();
    let database = Connection::open(root.join(".wuji4/state.sqlite")).unwrap();
    database.execute_batch(include_str!("../src/state_schema.sql")).unwrap();
    let canonical = fs::canonicalize(&root).unwrap();
    let root_hash = strict_json::sha256(canonical.to_string_lossy().as_bytes());
    let scope = format!("project:{}",&root_hash[..24]);
    database.execute("INSERT INTO workspace_meta(singleton,scope,root_hash,last_clock_ms) VALUES(1,?1,?2,0)",
        rusqlite::params![scope,root_hash]).unwrap();
    root
}

#[test]
fn schema2_unowned_observation_and_init_leave_database_untouched() {
    let root = old_workspace();
    let path = root.join(".wuji4/state.sqlite");
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),original);
    let database = Connection::open(&path).unwrap();
    assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),2);
    let tables: i64 = database.query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('knowledge_records','experience_records','resource_events')",[],|row|row.get(0)).unwrap();
    assert_eq!(tables,0);
}

#[test]
fn schema2_unowned_collision_is_rejected_before_migration() {
    let root = old_workspace();
    let path = root.join(".wuji4/state.sqlite");
    let database = Connection::open(&path).unwrap();
    database.execute("CREATE TABLE experience_records(existing TEXT)",[]).unwrap();
    drop(database);
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),original);
    let database = Connection::open(&path).unwrap();
    assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),2);
    let partial: i64 = database.query_row("SELECT count(*) FROM sqlite_master WHERE name IN ('knowledge_records','resource_events')",[],|row|row.get(0)).unwrap();
    assert_eq!(partial,0);
}

#[test]
fn schema3_empty_owner_binding_does_not_authorize_transfer_migration() {
    let root = old_workspace();
    let path = root.join(".wuji4/state.sqlite");
    let database = Connection::open(&path).unwrap();
    database.execute_batch(include_str!("../src/resource_schema.sql")).unwrap();
    database.execute("INSERT INTO resource_events VALUES('preserve','hash','{}')",[]).unwrap();
    drop(database);
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
    let database = Connection::open(&path).unwrap();
    database.execute("CREATE TABLE received_resources(existing TEXT)",[]).unwrap();
    drop(database);
    let collision = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),collision);
    let database = Connection::open(&path).unwrap();
    assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),3);
    assert_eq!(database.query_row("SELECT count(*) FROM sqlite_master WHERE name='resource_transfers'",[],|row|row.get::<_,i64>(0)).unwrap(),0);
    database.execute("DROP TABLE received_resources",[]).unwrap();
    drop(database);
    let restored = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),restored);
    let database = Connection::open(&path).unwrap();
    assert_eq!(database.query_row("SELECT payload_hash FROM resource_events WHERE event_key='preserve'",[],|row|row.get::<_,String>(0)).unwrap(),"hash");
}

#[test]
fn schema4_empty_owner_binding_does_not_authorize_catalog_migration() {
    let root = old_workspace();
    let path = root.join(".wuji4/state.sqlite");
    let database = Connection::open(&path).unwrap();
    database.execute_batch(include_str!("../src/resource_schema.sql")).unwrap();
    database.execute_batch(include_str!("../src/transfer_schema.sql")).unwrap();
    drop(database);
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
    let database = Connection::open(&path).unwrap();
    database.execute("CREATE TABLE task_catalog_locks(existing TEXT)",[]).unwrap();
    drop(database);
    let collision = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),collision);
    let database = Connection::open(&path).unwrap();
    assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),4);
    let mut columns = database.prepare("PRAGMA table_info(tasks)").unwrap();
    assert!(!columns.query_map([],|row|row.get::<_,String>(1)).unwrap().any(|name|name.unwrap()=="catalog_binding_hash"));
    drop(columns);
    database.execute("DROP TABLE task_catalog_locks",[]).unwrap();
    drop(database);
    let restored = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),restored);
}

#[test]
fn schema5_empty_owner_binding_does_not_authorize_received_migration() {
    let root=old_workspace();
    let path=root.join(".wuji4/state.sqlite");
    let database=Connection::open(&path).unwrap();
    database.execute_batch(include_str!("../src/resource_schema.sql")).unwrap();
    database.execute_batch(include_str!("../src/transfer_schema.sql")).unwrap();
    database.execute_batch(include_str!("../src/task_catalog_schema.sql")).unwrap();
    database.execute("INSERT INTO resource_events VALUES('preserve-received-upgrade','prior','{}')",[]).unwrap();
    drop(database);
    let original=fs::read(&path).unwrap();
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
    let database=Connection::open(&path).unwrap();
    database.execute("CREATE TABLE received_resource_versions(existing TEXT)",[]).unwrap();
    drop(database);
    let collision=fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),collision);
    let database=Connection::open(&path).unwrap();
    assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),5);
    assert_eq!(database.query_row("SELECT payload_hash FROM resource_events WHERE event_key='preserve-received-upgrade'",[],|row|row.get::<_,String>(0)).unwrap(),"prior");
    database.execute("DROP TABLE received_resource_versions",[]).unwrap();
    drop(database);
    let restored=fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
    assert_eq!(fs::read(&path).unwrap(),restored);
}

#[test]
fn bound_schema2_downgrade_is_rejected_without_recreating_owner_table() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/migration-acceptance")
        .join(format!("bound-{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(&root).unwrap();
    drop(Store::open(&root).unwrap());
    let path = root.join(".wuji4/state.sqlite");
    let database = Connection::open(&path).unwrap();
    database.pragma_update(None,"user_version",2).unwrap();
    let owner: String = database.query_row("SELECT owner_sid FROM local_resource_acl",[],|row|row.get(0)).unwrap();
    drop(database);
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
    let database = Connection::open(&path).unwrap();
    assert_eq!(database.query_row("SELECT owner_sid FROM local_resource_acl",[],|row|row.get::<_,String>(0)).unwrap(),owner);
    assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),2);
}

fn bound_schema6() -> PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/migration-acceptance")
        .join(format!("schema6-{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(&root).unwrap();
    drop(Store::open(&root).unwrap());
    let mut database = Connection::open(root.join(".wuji4/state.sqlite")).unwrap();
    database.pragma_update(None,"foreign_keys","OFF").unwrap();
    let transaction = database.transaction().unwrap();
    transaction.execute("DROP INDEX live_artifact_path",[]).unwrap();
    let legacy = include_str!("../src/artifact_history_migration.sql")
        .replace("artifacts_next","artifacts_legacy")
        .replace("path TEXT NOT NULL,","path TEXT NOT NULL UNIQUE,")
        .replace("CREATE UNIQUE INDEX live_artifact_path ON artifacts(path) WHERE state IN ('produced','validated','adopted');","")
        .replace("PRAGMA user_version = 7;","PRAGMA user_version = 6;");
    transaction.execute_batch(&legacy).unwrap();
    transaction.commit().unwrap();
    root
}

#[test]
fn owned_schema6_artifact_migration_preserves_history_references_and_live_uniqueness() {
    let root = bound_schema6();
    let path = root.join(".wuji4/state.sqlite");
    let database = Connection::open(&path).unwrap();
    database.execute_batch("INSERT INTO tasks(id,scope,graph_revision,release_id,plan_hash,max_parallel,retry_cap,revision_cap,deadline_ms,status) SELECT 'task',scope,1,'local','hash',1,1,1,9999999999999,'succeeded' FROM workspace_meta;
        INSERT INTO nodes(task_id,id,revision,owner,form,spec_json,state,input_hash) VALUES('task','node',1,'local','program','{}','succeeded','input');
        INSERT INTO attempts(id,task_id,node_id,graph_revision,node_revision,input_hash,owner,state,spec_json) VALUES('original','task','node',1,1,'input','local','accepted','{}');
        INSERT INTO artifacts(id,task_id,node_id,attempt_id,path,sha256,bytes,revision,producer,state) VALUES('original','task','node','original','result.txt','original-hash',5,1,'local','adopted');
        INSERT INTO validations(id,artifact_id,artifact_hash,graph_revision,validator,requirement_ids_json,verdict) VALUES('review','original','original-hash',1,'independent','[]','pass');
        INSERT INTO resource_events VALUES('preserve-owner-migration','hash','{}');").unwrap();
    let owner: String = database.query_row("SELECT owner_sid FROM local_resource_acl",[],|row|row.get(0)).unwrap();
    drop(database);
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
    drop(Store::open(&root).unwrap());
    let database = Connection::open(&path).unwrap();
    database.pragma_update(None,"foreign_keys","ON").unwrap();
    assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),7);
    assert_eq!(database.query_row("SELECT owner_sid FROM local_resource_acl",[],|row|row.get::<_,String>(0)).unwrap(),owner);
    assert_eq!(database.query_row("SELECT sha256 || ':' || state FROM artifacts WHERE id='original'",[],|row|row.get::<_,String>(0)).unwrap(),"original-hash:adopted");
    assert_eq!(database.query_row("SELECT artifact_id FROM validations WHERE id='review'",[],|row|row.get::<_,String>(0)).unwrap(),"original");
    assert_eq!(database.query_row("SELECT payload_hash FROM resource_events WHERE event_key='preserve-owner-migration'",[],|row|row.get::<_,String>(0)).unwrap(),"hash");
    database.execute("INSERT INTO attempts(id,task_id,node_id,graph_revision,node_revision,input_hash,owner,state,spec_json) VALUES('new','task','node',1,1,'input','local','produced','{}')",[]).unwrap();
    let insert = "INSERT INTO artifacts(id,task_id,node_id,attempt_id,path,sha256,bytes,revision,producer,state) VALUES('new','task','node','new','result.txt','new-hash',6,1,'local','produced')";
    assert!(database.execute(insert,[]).is_err());
    database.execute("UPDATE artifacts SET state='invalidated' WHERE id='original'",[]).unwrap();
    database.execute(insert,[]).unwrap();
    assert!(database.execute("UPDATE artifacts SET state='adopted' WHERE id='original'",[]).is_err());
    assert_eq!(database.query_row("SELECT count(*) FROM pragma_foreign_key_check",[],|row|row.get::<_,i64>(0)).unwrap(),0);
    drop(database);
    drop(Store::open_existing(&root).unwrap());
}

#[test]
fn schema6_without_owner_or_with_revocation_is_not_migrated() {
    for revoke in [false,true] {
        let root = bound_schema6();
        let path = root.join(".wuji4/state.sqlite");
        let database = Connection::open(&path).unwrap();
        if revoke { database.execute("UPDATE local_resource_acl SET enabled=0",[]).unwrap(); }
        else { database.execute("DELETE FROM local_resource_acl",[]).unwrap(); }
        drop(database);
        let original = fs::read(&path).unwrap();
        assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::AuthorityDenied);
        assert_eq!(fs::read(&path).unwrap(),original);
    }
}

#[test]
fn schema6_migration_collision_and_broken_references_roll_back_without_mutation() {
    for collision in [false,true] {
        let root = bound_schema6();
        let path = root.join(".wuji4/state.sqlite");
        let database = Connection::open(&path).unwrap();
        if collision { database.execute("CREATE TABLE artifacts_next(existing TEXT)",[]).unwrap(); }
        else {
            database.pragma_update(None,"foreign_keys","OFF").unwrap();
            database.execute("INSERT INTO validations VALUES('orphan','missing','hash',1,'reviewer','[]','pass')",[]).unwrap();
        }
        drop(database);
        let original = fs::read(&path).unwrap();
        assert!(Store::open(&root).is_err());
        assert_eq!(fs::read(&path).unwrap(),original);
        let database = Connection::open(&path).unwrap();
        assert_eq!(database.pragma_query_value(None,"user_version",|row|row.get::<_,i64>(0)).unwrap(),6);
        assert_eq!(database.query_row("SELECT count(*) FROM sqlite_master WHERE name='live_artifact_path'",[],|row|row.get::<_,i64>(0)).unwrap(),0);
    }
}

#[test]
fn owned_schema7_cannot_downgrade_to_bypass_migration_guards() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/migration-acceptance")
        .join(format!("schema7-{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(&root).unwrap();
    drop(Store::open(&root).unwrap());
    let path = root.join(".wuji4/state.sqlite");
    let database = Connection::open(&path).unwrap();
    database.pragma_update(None,"user_version",6).unwrap();
    drop(database);
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
}

#[test]
fn schema6_unknown_artifact_columns_are_not_silently_dropped() {
    let root = bound_schema6();
    let path = root.join(".wuji4/state.sqlite");
    let database = Connection::open(&path).unwrap();
    database.execute("ALTER TABLE artifacts ADD COLUMN external_note TEXT",[]).unwrap();
    drop(database);
    let original = fs::read(&path).unwrap();
    assert_eq!(Store::open(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(&path).unwrap(),original);
}
