#[test]
fn registered_input_is_exact_scoped_and_read_bounded() {
    let root = workspace("input-register");
    fs::write(root.join("source.txt"),b"source").unwrap();
    let mut store = Store::open(&root).unwrap();
    let reference = store.register_local_input("user/source",Path::new("source.txt")).unwrap();
    assert_eq!(store.register_local_input("user/source",Path::new("source.txt")).unwrap(),reference);
    assert_eq!(count(&store,"input_files"),1);
    let mut blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    blueprint["payload"]["nodes"][0]["inputs"] = json!([reference]);
    rehash(&mut blueprint);
    assert_eq!(store.plan(&blueprint).unwrap_err().kind,ErrorKind::PathDenied);
    blueprint["payload"]["nodes"][0]["read_roots"] = json!(["source.txt"]);
    rehash(&mut blueprint);
    store.plan(&blueprint).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    store.write_local_file(&claim,Path::new("result.txt"),b"real derived output").unwrap();
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    assert_eq!(store.connection.query_row("SELECT status FROM tasks",[],|row| row.get::<_,String>(0)).unwrap(),"succeeded");
}

#[test]
fn input_change_persistently_invalidates_full_downstream_without_release() {
    let root = workspace("input-invalidate");
    fs::write(root.join("source.txt"),b"original").unwrap();
    let mut store = Store::open(&root).unwrap();
    let reference = store.register_local_input("user/source",Path::new("source.txt")).unwrap();
    let mut blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt"),("third","third.txt")],&[("first","second"),("second","third")],2);
    blueprint["payload"]["nodes"][0]["inputs"] = json!([reference]);
    blueprint["payload"]["nodes"][0]["read_roots"] = json!(["source.txt"]);
    rehash(&mut blueprint);
    store.plan(&blueprint).unwrap();
    let first = store.claim_local("task","first").unwrap();
    store.write_local_file(&first,Path::new("first.txt"),b"first").unwrap();
    store.verify_local_file(&first).unwrap();
    let second = store.claim_local("task","second").unwrap();
    fs::write(root.join("source.txt"),b"changed").unwrap();
    let result = store.refresh_local_evidence().unwrap();
    assert_eq!(result["affected_nodes"],3);
    assert_eq!(count(&store,"acceptance_links"),0);
    assert_eq!(store.status().unwrap()["open_slots"],2);
    assert_eq!(store.write_local_file(&second,Path::new("second.txt"),b"late").unwrap_err().kind,ErrorKind::StaleReceipt);
    drop(store);
    let mut reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.connection.query_row("SELECT count(*) FROM nodes WHERE state='blocked'",[],|row| row.get::<_,i64>(0)).unwrap(),3);
    let next = reopened.register_local_input("user/source",Path::new("source.txt")).unwrap();
    assert_eq!(next.revision,2);
    assert_eq!(reopened.claim_local("task","third").unwrap_err().kind,ErrorKind::ValidationStale);
    assert!(root.join("first.txt").exists());
}

fn revision(blueprint: &Value, changed: &[(&str,&str)], affected: &[&str], next: i64) -> Value {
    let mut revised = blueprint.clone();
    revised["metadata"]["revision"] = json!(next);
    revised["payload"]["version"] = json!(next.to_string());
    for node in revised["payload"]["nodes"].as_array_mut().unwrap() {
        let id = node["id"].as_str().unwrap().to_owned();
        if affected.contains(&id.as_str()) { node["revision"] = json!(node["revision"].as_u64().unwrap()+1); }
        if let Some((_,path)) = changed.iter().find(|(name,_)| *name == id) { node["write_roots"] = json!([path]); }
    }
    rehash(&mut revised);
    revised
}

#[test]
fn graph_cas_retains_unrelated_adoption_and_rejects_old_result() {
    let root = workspace("graph-cas");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt"),("independent","other.txt")],&[("first","second")],2);
    store.plan(&blueprint).unwrap();
    let other = store.claim_local("task","independent").unwrap();
    store.write_local_file(&other,Path::new("other.txt"),b"preserved").unwrap();
    store.verify_local_file(&other).unwrap();
    store.close_local_handler(&other).unwrap();
    let first = store.claim_local("task","first").unwrap();
    let revised = revision(&blueprint,&[("first","first-v2.txt")],&["first","second"],2);
    let result = store.revise_local_plan(&revised,1,"user-change-1").unwrap();
    assert_eq!(result["affected_nodes"],json!(["first","second"]));
    assert_eq!(store.revise_local_plan(&revised,1,"user-change-1").unwrap(),result);
    assert_eq!(store.revise_local_plan(&revised,1,"different-change").unwrap_err().kind,ErrorKind::RevisionConflict);
    assert_eq!(count(&store,"task_plans"),2);
    assert_eq!(count(&store,"acceptance_links"),3);
    assert_eq!(store.status().unwrap()["open_slots"],1);
    assert_eq!(store.write_local_file(&first,Path::new("first-v2.txt"),b"late").unwrap_err().kind,ErrorKind::StaleReceipt);
    store.close_local_handler(&first).unwrap();
    let fresh = store.claim_local("task","first").unwrap();
    store.write_local_file(&fresh,Path::new("first-v2.txt"),b"new").unwrap();
    store.verify_local_file(&fresh).unwrap();
    store.close_local_handler(&fresh).unwrap();
    assert_eq!(fs::read(root.join("other.txt")).unwrap(),b"preserved");
}

#[test]
fn graph_revisions_cannot_reset_budget_or_repeat_no_progress() {
    let root = workspace("revision-budget");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","one.txt")],&[],1);
    store.plan(&blueprint).unwrap();
    let mut reset = revision(&blueprint,&[("write","two.txt")],&["write"],2);
    reset["payload"]["budget"]["max_extra_retries"] = json!(999);
    rehash(&mut reset);
    assert_eq!(store.revise_local_plan(&reset,1,"reset").unwrap_err().kind,ErrorKind::BudgetExhausted);
    let unchanged = revision(&blueprint,&[],&[],2);
    assert_eq!(store.revise_local_plan(&unchanged,1,"no-progress").unwrap_err().kind,ErrorKind::RevisionConflict);
    let second = revision(&blueprint,&[("write","two.txt")],&["write"],2);
    store.revise_local_plan(&second,1,"two").unwrap();
    let third = revision(&second,&[("write","three.txt")],&["write"],3);
    store.revise_local_plan(&third,2,"three").unwrap();
    let fourth = revision(&third,&[("write","four.txt")],&["write"],4);
    assert_eq!(store.revise_local_plan(&fourth,3,"four").unwrap_err().kind,ErrorKind::BudgetExhausted);
    assert_eq!(count(&store,"task_plans"),3);
}

#[test]
fn old_attempt_keeps_immutable_path_reservation_after_revision() {
    let root = workspace("immutable-lock");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","old.txt")],&[],2);
    store.plan(&blueprint).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    let revised = revision(&blueprint,&[("write","new.txt")],&["write"],2);
    store.revise_local_plan(&revised,1,"move-target").unwrap();
    let another = plan(&store,"other-task",&[("write","old.txt")],&[],2);
    store.plan(&another).unwrap();
    assert_eq!(store.claim_local("other-task","write").unwrap_err().kind,ErrorKind::OwnerConflict);
    store.close_local_handler(&claim).unwrap();
    store.claim_local("other-task","write").unwrap();
}

#[test]
fn t19_actual_defect_has_file_evidence_and_bounded_independently_verified_repair() {
    let root = workspace("t19-evidenced-repair");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    store.plan(&blueprint).unwrap();
    let original = store.claim_local("task","write").unwrap();
    store.write_local_file(&original,Path::new("result.txt"),b"original accepted result").unwrap();
    store.verify_local_file(&original).unwrap();
    store.close_local_handler(&original).unwrap();
    fs::write(root.join("result.txt"),b"changed after acceptance").unwrap();
    let defect_hash = strict_json::sha256(&fs::read(root.join("result.txt")).unwrap());
    assert_eq!(store.verify_local_file(&original).unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(store.execution_summary("task").unwrap()["result_state"],"incomplete");
    assert_eq!(count(&store,"acceptance_links"),0);
    let repaired = revision(&blueprint,&[("write","repaired.txt")],&["write"],2);
    let result = store.repair_local_plan(&repaired,1,"actual-file-drift").unwrap();
    assert_eq!(result["affected_nodes"],json!(["write"]));
    assert_eq!(store.repair_local_plan(&repaired,1,"actual-file-drift").unwrap(),result);
    assert_eq!(result["defect_nodes"],json!(["write"]));
    assert_eq!(store.task_status("task").unwrap()["revisions_used"],0);
    let current = store.claim_local("task","write").unwrap();
    store.write_local_file(&current,Path::new("repaired.txt"),b"repaired accepted result").unwrap();
    let checked = store.verify_local_file(&current).unwrap();
    assert_eq!(checked["validator"],"local-file-validator");
    assert_eq!(checked["professional_or_native_verified"],false);
    store.close_local_handler(&current).unwrap();
    assert_eq!(store.execution_summary("task").unwrap()["result_state"],"completed_bounded_task");
    assert_eq!(strict_json::sha256(&fs::read(root.join("result.txt")).unwrap()),defect_hash);
    assert_eq!(repaired["payload"]["budget"],blueprint["payload"]["budget"]);
    assert_eq!(count(&store,"validations"),2);
    assert_eq!(count(&store,"task_plans"),2);
    drop(store);
    let mut reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.execution_summary("task").unwrap()["result_state"],"completed_bounded_task");
    assert_eq!(reopened.status().unwrap()["open_slots"],0);
}

#[test]
fn t19_clean_review_does_not_invent_three_findings_or_repeat_dispatch() {
    let root = workspace("t19-no-manufactured-defects");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    store.plan(&blueprint).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    store.write_local_file(&claim,Path::new("result.txt"),b"already satisfies the actual checks").unwrap();
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    let unchanged = revision(&blueprint,&[],&[],2);
    assert_eq!(store.repair_local_plan(&unchanged,1,"force-three-findings").unwrap_err().kind,ErrorKind::RevisionConflict);
    let manufactured = revision(&blueprint,&[("write","unneeded.txt")],&["write"],2);
    assert_eq!(store.repair_local_plan(&manufactured,1,"invented-defect").unwrap_err().kind,ErrorKind::ValidationStale);
    assert_eq!(store.task_status("task").unwrap()["revisions_used"],0);
    assert_eq!(count(&store,"invocations"),1);
    assert_eq!(count(&store,"task_plans"),1);
    assert_eq!(store.execution_summary("task").unwrap()["result_state"],"completed_bounded_task");
}

#[test]
fn t19_pinned_no_progress_cap_stops_rework_before_mutation_and_survives_reopen() {
    let root = workspace("t19-no-progress-cap");
    let mut store = Store::open(&root).unwrap();
    let mut blueprint = plan(&store,"task",&[("write","first.txt")],&[],1);
    blueprint["payload"]["budget"]["max_point_revisions"] = json!(8);
    blueprint["payload"]["budget"]["max_no_progress"] = json!(1);
    rehash(&mut blueprint);
    store.plan(&blueprint).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    store.write_local_file(&claim,Path::new("first.txt"),b"actual accepted result").unwrap();
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    fs::write(root.join("first.txt"),b"actual corrupt output").unwrap();
    let second = revision(&blueprint,&[("write","second.txt")],&["write"],2);
    store.repair_local_plan(&second,1,"first-repair").unwrap();
    drop(store);
    let mut reopened = Store::open_existing(&root).unwrap();
    let third = revision(&second,&[("write","third.txt")],&["write"],3);
    for event in ["next-repair","different-event-does-not-reset-budget"] {
        assert_eq!(reopened.repair_local_plan(&third,2,event).unwrap_err().kind,ErrorKind::BudgetExhausted);
    }
    assert_eq!(reopened.task_status("task").unwrap()["graph_revision"],2);
    assert_eq!(reopened.task_status("task").unwrap()["revisions_used"],0);
    assert_eq!(count(&reopened,"task_plans"),2);
    assert_eq!(count(&reopened,"attempts"),1);
    assert!(!root.join("third.txt").exists());
}

#[test]
fn t19_real_validation_resets_consecutive_guard_but_not_aggregate_revision_budget() {
    let root = workspace("t19-progress-not-budget-reset");
    let mut store = Store::open(&root).unwrap();
    let mut blueprint = plan(&store,"task",&[("write","first.txt")],&[],1);
    blueprint["payload"]["budget"]["max_no_progress"] = json!(1);
    rehash(&mut blueprint);
    store.plan(&blueprint).unwrap();
    let original = store.claim_local("task","write").unwrap();
    store.write_local_file(&original,Path::new("first.txt"),b"actual accepted result").unwrap();
    store.verify_local_file(&original).unwrap();
    store.close_local_handler(&original).unwrap();
    fs::write(root.join("first.txt"),b"actual corrupt output").unwrap();
    let second = revision(&blueprint,&[("write","second.txt")],&["write"],2);
    store.repair_local_plan(&second,1,"first-repair").unwrap();
    let claim = store.claim_local("task","write").unwrap();
    store.write_local_file(&claim,Path::new("second.txt"),b"independently checked progress").unwrap();
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    fs::write(root.join("second.txt"),b"new actual corruption after verified progress").unwrap();
    let third = revision(&second,&[("write","third.txt")],&["write"],3);
    store.repair_local_plan(&third,2,"second-repair").unwrap();
    let fourth = revision(&third,&[("write","fourth.txt")],&["write"],4);
    assert_eq!(store.repair_local_plan(&fourth,3,"cannot-reset-total").unwrap_err().kind,ErrorKind::BudgetExhausted);
    assert_eq!(store.task_status("task").unwrap()["revisions_used"],0);
    assert_eq!(count(&store,"task_plans"),3);
}

#[test]
fn t19_normal_user_revisions_do_not_count_as_unverified_repairs() {
    let root = workspace("t19-normal-user-revisions");
    let mut store = Store::open(&root).unwrap();
    let mut blueprint = plan(&store,"task",&[("write","first.txt")],&[],1);
    blueprint["payload"]["budget"]["max_point_revisions"] = json!(4);
    blueprint["payload"]["budget"]["max_no_progress"] = json!(1);
    rehash(&mut blueprint);
    store.plan(&blueprint).unwrap();
    let second = revision(&blueprint,&[("write","second.txt")],&["write"],2);
    store.revise_local_plan(&second,1,"user-requirement-one").unwrap();
    let third = revision(&second,&[("write","third.txt")],&["write"],3);
    store.revise_local_plan(&third,2,"user-requirement-two").unwrap();
    assert_eq!(store.task_status("task").unwrap()["revisions_used"],2);
    assert_eq!(count(&store,"attempts"),0);
    assert_eq!(count(&store,"task_plans"),3);
}

#[test]
fn t19_repair_cap_is_per_defect_node_and_cannot_reset_through_event_names() {
    let root = workspace("t19-per-node-repair-cap");
    let mut store = Store::open(&root).unwrap();
    let mut blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt")],&[],2);
    store.plan(&blueprint).unwrap();
    for (node,path) in [("first","first.txt"),("second","second.txt")] {
        let claim = store.claim_local("task",node).unwrap();
        store.write_local_file(&claim,Path::new(path),b"verified initial result").unwrap();
        store.verify_local_file(&claim).unwrap();
        store.close_local_handler(&claim).unwrap();
    }
    for (index,node,old_path,new_path) in [(2,"first","first.txt","first-r1.txt"),(3,"second","second.txt","second-r1.txt"),(4,"first","first-r1.txt","first-r2.txt"),(5,"second","second-r1.txt","second-r2.txt")] {
        fs::write(root.join(old_path),b"one actual defect").unwrap();
        let proposal = revision(&blueprint,&[(node,new_path)],&[node],index);
        let result = store.repair_local_plan(&proposal,index-1,&format!("defect-{index}")).unwrap();
        assert_eq!(result["defect_nodes"],json!([node]));
        let claim = store.claim_local("task",node).unwrap();
        store.write_local_file(&claim,Path::new(new_path),b"independently revalidated repair").unwrap();
        store.verify_local_file(&claim).unwrap();
        store.close_local_handler(&claim).unwrap();
        blueprint = proposal;
    }
    fs::write(root.join("first-r2.txt"),b"third defect for same node").unwrap();
    let third = revision(&blueprint,&[("first","first-r3.txt")],&["first"],6);
    assert_eq!(store.repair_local_plan(&third,5,"new-id-cannot-reset-node-cap").unwrap_err().kind,ErrorKind::BudgetExhausted);
    assert_eq!(store.task_status("task").unwrap()["revisions_used"],0);
    assert_eq!(store.task_status("task").unwrap()["retries_used"],4);
    assert_eq!(count(&store,"task_plans"),5);
    assert!(!root.join("first-r3.txt").exists());
}

#[test]
fn t19_two_independent_defects_can_be_repaired_without_unrelated_rework() {
    let root = workspace("t19-independent-defects");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt")],&[],2);
    store.plan(&blueprint).unwrap();
    for (node,path) in [("first","first.txt"),("second","second.txt")] {
        let claim = store.claim_local("task",node).unwrap();
        store.write_local_file(&claim,Path::new(path),b"verified initial result").unwrap();
        store.verify_local_file(&claim).unwrap();
        store.close_local_handler(&claim).unwrap();
        fs::write(root.join(path),b"independent actual corruption").unwrap();
    }
    let second = revision(&blueprint,&[("first","first-r1.txt")],&["first"],2);
    let result = store.repair_local_plan(&second,1,"only-first-defect").unwrap();
    assert_eq!(result["affected_nodes"],json!(["first"]));
    assert_eq!(result["defect_nodes"],json!(["first"]));
    let claim = store.claim_local("task","first").unwrap();
    store.write_local_file(&claim,Path::new("first-r1.txt"),b"verified first repair").unwrap();
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    let summary = store.execution_summary("task").unwrap();
    assert_eq!(summary["results"].as_array().unwrap().len(),1);
    assert_eq!(summary["unmet_nodes"][0]["node"],"second");
    assert_eq!(fs::read(root.join("second.txt")).unwrap(),b"independent actual corruption");
    let third = revision(&second,&[("second","second-r1.txt")],&["second"],3);
    let result = store.repair_local_plan(&third,2,"only-second-defect").unwrap();
    assert_eq!(result["affected_nodes"],json!(["second"]));
    let claim = store.claim_local("task","second").unwrap();
    store.write_local_file(&claim,Path::new("second-r1.txt"),b"verified second repair").unwrap();
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    assert_eq!(store.execution_summary("task").unwrap()["result_state"],"completed_bounded_task");
}

#[test]
fn t19_lost_artifact_can_be_repaired_at_original_path_without_invented_spec_change() {
    let root = workspace("t19-lost-artifact");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    store.plan(&blueprint).unwrap();
    let original = store.claim_local("task","write").unwrap();
    store.write_local_file(&original,Path::new("result.txt"),b"original result").unwrap();
    store.verify_local_file(&original).unwrap();
    store.close_local_handler(&original).unwrap();
    fs::remove_file(root.join("result.txt")).unwrap();
    let proposal = revision(&blueprint,&[],&["write"],2);
    let result = store.repair_local_plan(&proposal,1,"actual-missing-output").unwrap();
    assert_eq!(result["defect_nodes"],json!(["write"]));
    let claim = store.claim_local("task","write").unwrap();
    store.write_local_file(&claim,Path::new("result.txt"),b"regenerated original result").unwrap();
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    assert_eq!(store.execution_summary("task").unwrap()["result_state"],"completed_bounded_task");
    assert_eq!(count(&store,"validations"),2);
    assert_eq!(count(&store,"artifacts"),2);
    let history: (String,String,String) = store.connection.query_row("SELECT path,sha256,state FROM artifacts WHERE attempt_id=?1",[original.attempt_id()],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).unwrap();
    assert_eq!(history,(store.workspace.resolve(Path::new("result.txt")).unwrap().to_string_lossy().into_owned(),strict_json::sha256(b"original result"),"invalidated".into()));
    assert!(store.connection.execute("UPDATE artifacts SET state='adopted' WHERE attempt_id=?1",[original.attempt_id()]).is_err());
    assert_eq!(fs::read(root.join("result.txt")).unwrap(),b"regenerated original result");
    drop(store);
    let mut reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.execution_summary("task").unwrap()["result_state"],"completed_bounded_task");
    assert_eq!(count(&reopened,"artifacts"),2);
}

#[cfg(windows)]
#[test]
fn t10_actual_windows_links_case_aliases_and_retargeted_paths_fail_closed() {
    let root = workspace("t10-windows-boundary");
    let outside = workspace("t10-separate-private-root");
    fs::write(outside.join("private.txt"),b"must not be read from another project").unwrap();
    let make_junction = |link: &Path| {
        let created = std::process::Command::new("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
            .args(["-NoProfile","-NonInteractive","-Command","$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:WUJI_TEST_LINK -Target $env:WUJI_TEST_TARGET | Out-Null"])
            .env("WUJI_TEST_LINK",link).env("WUJI_TEST_TARGET",&outside).output().unwrap();
        assert!(created.status.success(),"junction creation failed: {:?}",created);
    };
    make_junction(&root.join("escape"));
    let mut store = Store::open(&root).unwrap();
    assert_eq!(store.register_local_input("private",Path::new("escape/private.txt")).unwrap_err().kind,ErrorKind::PathDenied);
    let escaped = plan(&store,"escape-task",&[("write","escape/result.txt")],&[],1);
    assert_eq!(store.plan(&escaped).unwrap_err().kind,ErrorKind::PathDenied);
    for path in [".WUJI4/state.sqlite",".CoDeX/config.toml",".AGENTS/skills/entry.md","output/../outside.txt"] {
        let denied = plan(&store,"reserved",&[("write",path)],&[],1);
        assert_eq!(store.plan(&denied).unwrap_err().kind,ErrorKind::PathDenied);
    }
    let aliases = plan(&store,"aliases",&[("first","Result.txt"),("second","result.TXT")],&[],2);
    store.plan(&aliases).unwrap();
    let first = store.claim_local("aliases","first").unwrap();
    assert_eq!(store.claim_local("aliases","second").unwrap_err().kind,ErrorKind::OwnerConflict);
    assert_eq!(count(&store,"attempts"),1);
    store.close_local_handler(&first).unwrap();
    fs::create_dir(root.join("retarget")).unwrap();
    let retargeted = plan(&store,"retargeted",&[("write","retarget/result.txt")],&[],1);
    store.plan(&retargeted).unwrap();
    let claim = store.claim_local("retargeted","write").unwrap();
    fs::remove_dir(root.join("retarget")).unwrap();
    make_junction(&root.join("retarget"));
    assert_eq!(store.write_local_file(&claim,Path::new("retarget/result.txt"),b"must not escape").unwrap_err().kind,ErrorKind::PathDenied);
    assert!(!outside.join("result.txt").exists());
    store.close_local_handler(&claim).unwrap();
    assert_eq!(store.status().unwrap()["open_slots"],0);
    assert_eq!(fs::read(outside.join("private.txt")).unwrap(),b"must not be read from another project");
}

#[test]
fn checkpoint_is_durable_but_cannot_resolve_unknown_or_extend_lease() {
    let root = workspace("checkpoint");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    store.plan(&blueprint).unwrap();
    let checkpoint = store.checkpoint_local("task").unwrap();
    let id = checkpoint["checkpoint_id"].as_str().unwrap();
    assert_eq!(store.inspect_checkpoint(id).unwrap()["reusable_as_context"],true);
    let claim = store.claim_local("task","write").unwrap();
    assert_eq!(store.inspect_checkpoint(id).unwrap()["reusable_as_context"],false);
    store.begin_local_dispatch(&claim,&store.workspace.output(Path::new("result.txt")).unwrap(),b"possible").unwrap();
    fs::write(root.join("result.txt"),b"possible").unwrap();
    store.recover().unwrap();
    let query = store.inspect_local_attempt(claim.attempt_id()).unwrap();
    assert_eq!(query["file_observation"]["matches_intent"],true);
    assert_eq!(query["file_observation"]["ownership_proven_by_content"],false);
    assert_eq!(query["invocation_state"],"unknown");
    assert_eq!(store.status().unwrap()["open_slots"],1);
    assert_eq!(count(&store,"artifacts"),0);
    assert_eq!(store.close_local_handler(&claim).unwrap_err().kind,ErrorKind::UnknownSubmission);
    fs::write(Path::new(checkpoint["path"].as_str().unwrap()),b"tampered").unwrap();
    assert_eq!(store.inspect_checkpoint(id).unwrap_err().kind,ErrorKind::HashMismatch);
}

#[test]
fn prior_schema_id_is_preserved_without_silent_migration() {
    let root = workspace("old-schema");
    let store = Store::open(&root).unwrap();
    store.connection.pragma_update(None,"user_version",1).unwrap();
    drop(store);
    let database = root.join(".wuji4/state.sqlite");
    let original = fs::read(&database).unwrap();
    assert_eq!(Store::open_existing(&root).err().unwrap().kind,ErrorKind::MigrationUnsupported);
    assert_eq!(fs::read(database).unwrap(),original);
}

#[test]
fn invalidated_unknown_attempt_cannot_be_revived_by_recovery() {
    let root = workspace("unknown-no-revival");
    fs::write(root.join("source.txt"),b"original").unwrap();
    let mut store = Store::open(&root).unwrap();
    let reference = store.register_local_input("source",Path::new("source.txt")).unwrap();
    let mut blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    blueprint["payload"]["nodes"][0]["inputs"] = json!([reference]);
    blueprint["payload"]["nodes"][0]["read_roots"] = json!(["source.txt"]);
    rehash(&mut blueprint);
    store.plan(&blueprint).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    store.begin_local_dispatch(&claim,&store.workspace.output(Path::new("result.txt")).unwrap(),b"possible").unwrap();
    fs::write(root.join("source.txt"),b"changed").unwrap();
    store.recover().unwrap();
    assert_eq!(store.inspect_local_attempt(claim.attempt_id()).unwrap()["attempt_state"],"superseded");
    assert_eq!(store.status().unwrap()["unknown_invocations"],1);
    assert_eq!(store.status().unwrap()["open_slots"],1);
    assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"late").unwrap_err().kind,ErrorKind::StaleReceipt);
}

#[test]
fn closing_last_observed_local_slot_finalizes_requested_cancellation() {
    let root = workspace("cancel-finalize");
    let mut store = Store::open(&root).unwrap();
    store.plan(&plan(&store,"task",&[("write","result.txt")],&[],1)).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    store.write_local_file(&claim,Path::new("result.txt"),b"kept").unwrap();
    store.connection.execute("UPDATE tasks SET status='cancel_requested'",[]).unwrap();
    store.connection.execute("UPDATE nodes SET state='cancel_requested'",[]).unwrap();
    store.close_local_handler(&claim).unwrap();
    assert_eq!(store.connection.query_row("SELECT status FROM tasks",[],|row| row.get::<_,String>(0)).unwrap(),"cancelled");
    assert_eq!(store.status().unwrap()["open_slots"],0);
    assert_eq!(fs::read(root.join("result.txt")).unwrap(),b"kept");
}

#[test]
fn declared_input_copy_requires_exact_source_and_has_separate_validation() {
    let root = workspace("input-copy");
    fs::write(root.join("source.txt"),"真实输入".as_bytes()).unwrap();
    fs::write(root.join("unassigned.txt"),b"not adopted").unwrap();
    let mut store = Store::open(&root).unwrap();
    let reference = store.register_local_input("source",Path::new("source.txt")).unwrap();
    let mut blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    blueprint["payload"]["nodes"][0]["inputs"] = json!([reference]);
    blueprint["payload"]["nodes"][0]["read_roots"] = json!(["source.txt"]);
    rehash(&mut blueprint);
    store.plan(&blueprint).unwrap();
    assert_eq!(store.copy_local_input("task","write",Path::new("unassigned.txt"),Path::new("result.txt")).unwrap_err().kind,ErrorKind::Reference);
    assert_eq!(count(&store,"attempts"),0);
    let result = store.copy_local_input("task","write",Path::new("source.txt"),Path::new("result.txt")).unwrap();
    assert_eq!(result["professional_or_native_verified"],false);
    assert_eq!(result["status"]["open_slots"],0);
    assert_eq!(fs::read(root.join("result.txt")).unwrap(),"真实输入".as_bytes());
    assert_eq!(store.copy_local_input("task","write",Path::new("source.txt"),Path::new("result.txt")).unwrap(),result);
    assert_eq!(count(&store,"attempts"),1);
    assert_eq!(count(&store,"validations"),1);
}

#[test]
fn repeated_write_replays_without_redispatch_and_changed_payload_conflicts() {
    let root = workspace("write-replay");
    let mut store = Store::open(&root).unwrap();
    store.plan(&plan(&store,"task",&[("write","result.txt")],&[],1)).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    let produced = store.write_local_file(&claim,Path::new("result.txt"),b"same").unwrap();
    assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"same").unwrap(),produced);
    assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"different").unwrap_err().kind,ErrorKind::EventConflict);
    store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"same").unwrap(),produced);
    assert_eq!(count(&store,"artifacts"),1);
    assert_eq!(count(&store,"attempts"),1);
    assert_eq!(fs::read(root.join("result.txt")).unwrap(),b"same");
}

struct OwnedProcess(std::process::Child);

impl Drop for OwnedProcess {
    fn drop(&mut self) {
        if self.0.try_wait().is_ok_and(|status| status.is_none()) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

fn fixture(root: &Path, mode: &str) -> OwnedProcess {
    OwnedProcess(std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact","store::tests::process_fixture","--nocapture"])
        .env("WUJI4_PRODUCT_FIXTURE_ROOT",root).env("WUJI4_PRODUCT_FIXTURE_MODE",mode)
        .stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::piped()).spawn().unwrap())
}

fn await_file(path: &Path) {
    let deadline = std::time::Instant::now()+Duration::from_secs(15);
    while !path.exists() {
        assert!(std::time::Instant::now()<deadline,"fixture handshake timeout: {}",path.display());
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[test]
fn process_fixture() {
    let Ok(root) = std::env::var("WUJI4_PRODUCT_FIXTURE_ROOT") else { return; };
    let root = PathBuf::from(root);
    let expected = Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/core-test-workspaces");
    assert!(root.starts_with(expected));
    let mode = std::env::var("WUJI4_PRODUCT_FIXTURE_MODE").unwrap();
    let mut store = Store::open_existing(&root).unwrap();
    if mode.starts_with("write-") {
        let node = mode.strip_prefix("write-").unwrap();
        let claim = store.claim_local("task",node).unwrap();
        fs::write(root.join(format!("{mode}.ready")),b"reserved-local-slot").unwrap();
        await_file(&root.join("release-write"));
        store.write_local_file(&claim,Path::new(&format!("{node}.txt")),node.as_bytes()).unwrap();
        store.verify_local_file(&claim).unwrap();
        store.close_local_handler(&claim).unwrap();
        return;
    }
    if mode.starts_with("claim-") {
        fs::write(root.join(format!("{mode}.ready")),b"ready").unwrap();
        await_file(&root.join("release-claim"));
        match store.claim_local("task","write") {
            Ok(_) => println!("CLAIM_OK"),
            Err(error) => { assert_eq!(error.kind,ErrorKind::RevisionConflict); println!("CLAIM_REJECTED"); }
        }
        return;
    }
    if mode == "uncommitted" {
        let transaction = store.connection.transaction_with_behavior(TransactionBehavior::Immediate).unwrap();
        transaction.execute("UPDATE tasks SET graph_revision=99,status='blocked'",[]).unwrap();
        fs::write(root.join("crash.ready"),b"transaction-uncommitted").unwrap();
        await_file(&root.join("never-release-transaction"));
        transaction.commit().unwrap();
        return;
    }
    let claim = store.claim_local("task","write").unwrap();
    let target = store.workspace.output(Path::new("result.txt")).unwrap();
    store.begin_local_dispatch(&claim,&target,b"process-owned-output").unwrap();
    if mode == "after-file-sync" {
        let mut file = OpenOptions::new().write(true).create_new(true).open(target).unwrap();
        file.write_all(b"process-owned-output").unwrap();
        file.sync_all().unwrap();
        drop(file);
    }
    fs::write(root.join("crash.ready"),b"dispatch-committed").unwrap();
    await_file(&root.join("never-release-handler"));
}

#[test]
fn two_os_processes_have_one_claim_winner() {
    let root = workspace("process-claim");
    let mut store = Store::open(&root).unwrap();
    store.plan(&plan(&store,"task",&[("write","result.txt")],&[],2)).unwrap();
    drop(store);
    let mut first = fixture(&root,"claim-one");
    let mut second = fixture(&root,"claim-two");
    await_file(&root.join("claim-one.ready"));
    await_file(&root.join("claim-two.ready"));
    fs::write(root.join("release-claim"),b"both-may-start").unwrap();
    assert!(first.0.wait().unwrap().success());
    assert!(second.0.wait().unwrap().success());
    let reopened = Store::open_existing(&root).unwrap();
    assert_eq!(count(&reopened,"attempts"),1);
    assert_eq!(reopened.status().unwrap()["open_slots"],1);
}

#[test]
fn independent_file_handlers_run_in_two_os_processes() {
    let root = workspace("process-two-files");
    let mut store = Store::open(&root).unwrap();
    store.plan(&plan(&store,"task",&[("first","first.txt"),("second","second.txt")],&[],2)).unwrap();
    drop(store);
    let mut first = fixture(&root,"write-first");
    let mut second = fixture(&root,"write-second");
    await_file(&root.join("write-first.ready"));
    await_file(&root.join("write-second.ready"));
    assert_eq!(Store::open_existing(&root).unwrap().status().unwrap()["open_slots"],2);
    fs::write(root.join("release-write"),b"both-local-handlers-may-write").unwrap();
    assert!(first.0.wait().unwrap().success());
    assert!(second.0.wait().unwrap().success());
    let reopened = Store::open_existing(&root).unwrap();
    assert_eq!(fs::read(root.join("first.txt")).unwrap(),b"first");
    assert_eq!(fs::read(root.join("second.txt")).unwrap(),b"second");
    assert_eq!(count(&reopened,"validations"),2);
    assert_eq!(count(&reopened,"acceptance_links"),6);
    assert_eq!(reopened.status().unwrap()["open_slots"],0);
    assert_eq!(reopened.connection.query_row("SELECT status FROM tasks",[],|row| row.get::<_,String>(0)).unwrap(),"succeeded");
}

fn killed_dispatch(mode: &str) {
    let root = workspace(mode);
    let mut store = Store::open(&root).unwrap();
    store.plan(&plan(&store,"task",&[("write","result.txt")],&[],1)).unwrap();
    drop(store);
    let mut child = fixture(&root,mode);
    await_file(&root.join("crash.ready"));
    child.0.kill().unwrap();
    child.0.wait().unwrap();
    let mut reopened = Store::open_existing(&root).unwrap();
    reopened.recover().unwrap();
    assert_eq!(reopened.status().unwrap()["unknown_invocations"],1);
    assert_eq!(reopened.status().unwrap()["open_slots"],1);
    assert_eq!(count(&reopened,"artifacts"),0);
    assert_eq!(count(&reopened,"acceptance_links"),0);
    let attempt: String = reopened.connection.query_row("SELECT id FROM attempts",[],|row| row.get(0)).unwrap();
    let observation = reopened.inspect_local_attempt(&attempt).unwrap();
    assert_eq!(observation["invocation_state"],"unknown");
    assert_eq!(observation["file_observation"]["readable"],mode=="after-file-sync");
    if mode == "after-file-sync" { assert_eq!(observation["file_observation"]["matches_intent"],true); }
    for _ in 0..3 {
        reopened.recover().unwrap();
        let queried = reopened.inspect_local_attempt(&attempt).unwrap();
        assert_eq!(queried["invocation_state"],"unknown");
        assert_eq!(queried["redispatch_permitted"],false);
        assert_eq!(queried["slots_released"],0);
        assert_eq!(queried["native_verified"],false);
        assert!(reopened.claim_local("task","write").is_err());
        assert_eq!(count(&reopened,"invocations"),1);
        assert_eq!(count(&reopened,"artifacts"),0);
        assert_eq!(count(&reopened,"acceptance_links"),0);
    }
}

#[test]
fn os_kill_after_dispatch_requires_query_and_holds_slot() { killed_dispatch("after-dispatch"); }

#[test]
fn os_kill_after_file_sync_cannot_fabricate_producer_receipt() { killed_dispatch("after-file-sync"); }

#[test]
fn os_kill_in_transaction_rolls_back_graph_change() {
    let root = workspace("process-rollback");
    let mut store = Store::open(&root).unwrap();
    store.plan(&plan(&store,"task",&[("write","result.txt")],&[],1)).unwrap();
    drop(store);
    let mut child = fixture(&root,"uncommitted");
    await_file(&root.join("crash.ready"));
    child.0.kill().unwrap();
    child.0.wait().unwrap();
    let reopened = Store::open_existing(&root).unwrap();
    let revision: i64 = reopened.connection.query_row("SELECT graph_revision FROM tasks",[],|row| row.get(0)).unwrap();
    assert_eq!(revision,1);
    assert_eq!(count(&reopened,"attempts"),0);
    assert_eq!(reopened.status().unwrap()["open_slots"],0);
}

#[test]
fn t11_full_local_revision_revalidates_only_affected_chain_and_preserves_history() {
    let root = workspace("t11-full-revision");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("first","first.txt"),("second","second.txt"),("independent","other.txt")],&[("first","second")],2);
    store.plan(&blueprint).unwrap();
    let mut prior_claims = Vec::new();
    for (node,path,content) in [("first","first.txt",b"first".as_slice()),("second","second.txt",b"second".as_slice()),("independent","other.txt",b"preserved".as_slice())] {
        let claim = store.claim_local("task",node).unwrap();
        store.write_local_file(&claim,Path::new(path),content).unwrap();
        store.verify_local_file(&claim).unwrap();
        store.close_local_handler(&claim).unwrap();
        prior_claims.push(claim);
    }
    assert_eq!(store.task_status("task").unwrap()["state"],"succeeded");
    let revised = revision(&blueprint,&[("first","first-v2.txt"),("second","second-v2.txt")],&["first","second"],2);
    let result = store.revise_local_plan(&revised,1,"changed-user-requirement").unwrap();
    assert_eq!(result["affected_nodes"],json!(["first","second"]));
    assert_eq!(count(&store,"acceptance_links"),3);
    assert_eq!(count(&store,"validations"),3);
    assert_eq!(store.revise_local_plan(&revised,1,"changed-user-requirement").unwrap(),result);
    assert_eq!(store.revise_local_plan(&revised,1,"stale-other-event").unwrap_err().kind,ErrorKind::RevisionConflict);
    assert!(store.verify_local_file(&prior_claims[0]).is_err());
    assert_eq!(store.claim_local("task","second").unwrap_err().kind,ErrorKind::DependencyNotAccepted);
    for (node,path,content) in [("first","first-v2.txt",b"new-first".as_slice()),("second","second-v2.txt",b"new-second".as_slice())] {
        let claim = store.claim_local("task",node).unwrap();
        store.write_local_file(&claim,Path::new(path),content).unwrap();
        let checked = store.verify_local_file(&claim).unwrap();
        assert_eq!(checked["professional_or_native_verified"],false);
        store.close_local_handler(&claim).unwrap();
    }
    assert_eq!(count(&store,"acceptance_links"),9);
    assert_eq!(count(&store,"validations"),5);
    assert_eq!(count(&store,"task_plans"),2);
    assert_eq!(fs::read(root.join("first.txt")).unwrap(),b"first");
    assert_eq!(fs::read(root.join("second.txt")).unwrap(),b"second");
    assert_eq!(fs::read(root.join("other.txt")).unwrap(),b"preserved");
    drop(store);
    let reopened = Store::open_existing(&root).unwrap();
    assert_eq!(reopened.task_status("task").unwrap()["state"],"succeeded");
    assert_eq!(reopened.status().unwrap()["open_slots"],0);
    assert_eq!(count(&reopened,"validations"),5);
}

#[test]
fn t12_full_local_repeated_events_never_create_second_dispatch_or_change_artifact() {
    let root = workspace("t12-event-replay");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    let planned = store.plan(&blueprint).unwrap();
    let claim = store.claim_local("task","write").unwrap();
    let produced = store.write_local_file(&claim,Path::new("result.txt"),b"one actual dispatch").unwrap();
    let verified = store.verify_local_file(&claim).unwrap();
    store.close_local_handler(&claim).unwrap();
    for _ in 0..20 {
        assert_eq!(store.plan(&blueprint).unwrap(),planned);
        assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"one actual dispatch").unwrap(),produced);
        assert_eq!(store.verify_local_file(&claim).unwrap(),verified);
        store.close_local_handler(&claim).unwrap();
    }
    assert_eq!(store.write_local_file(&claim,Path::new("result.txt"),b"conflicting replay").unwrap_err().kind,ErrorKind::EventConflict);
    assert_eq!(count(&store,"tasks"),1);
    assert_eq!(count(&store,"attempts"),1);
    assert_eq!(count(&store,"invocations"),1);
    assert_eq!(count(&store,"validations"),1);
    assert_eq!(count(&store,"artifacts"),1);
    assert_eq!(fs::read(root.join("result.txt")).unwrap(),b"one actual dispatch");
    assert_eq!(store.status().unwrap()["open_slots"],0);
    assert_eq!(produced["host_class"],"test_local");
}

#[test]
fn t18_changed_adopted_file_needs_new_revision_and_independent_current_validation() {
    let root = workspace("t18-revalidation");
    let mut store = Store::open(&root).unwrap();
    let blueprint = plan(&store,"task",&[("write","result.txt")],&[],1);
    store.plan(&blueprint).unwrap();
    let old = store.claim_local("task","write").unwrap();
    store.write_local_file(&old,Path::new("result.txt"),b"original validated output").unwrap();
    let prior = store.verify_local_file(&old).unwrap();
    store.close_local_handler(&old).unwrap();
    fs::write(root.join("result.txt"),b"modified outside producer").unwrap();
    assert!(store.verify_local_file(&old).is_err());
    assert_eq!(count(&store,"acceptance_links"),0);
    assert_eq!(count(&store,"validations"),1);
    assert_eq!(store.task_status("task").unwrap()["state"],"blocked");
    let revised = revision(&blueprint,&[("write","current.txt")],&["write"],2);
    store.revise_local_plan(&revised,1,"revalidate-changed-output").unwrap();
    assert!(store.write_local_file(&old,Path::new("current.txt"),b"old receipt cannot authorize new file").is_err());
    let current = store.claim_local("task","write").unwrap();
    store.write_local_file(&current,Path::new("current.txt"),b"new independently validated output").unwrap();
    assert_eq!(count(&store,"acceptance_links"),0);
    let accepted = store.verify_local_file(&current).unwrap();
    assert_ne!(prior,accepted);
    store.close_local_handler(&current).unwrap();
    assert_eq!(count(&store,"acceptance_links"),3);
    assert_eq!(count(&store,"validations"),2);
    assert_eq!(fs::read(root.join("result.txt")).unwrap(),b"modified outside producer");
    assert_eq!(store.task_status("task").unwrap()["graph_revision"],2);
    assert_eq!(store.task_status("task").unwrap()["state"],"succeeded");
}
