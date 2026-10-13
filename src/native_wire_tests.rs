use super::*;

fn tracker() -> NativeObservationTracker {
    NativeObservationTracker::new(MODEL, "high", 10, 20).unwrap()
}

fn thread_response() -> Value {
    json!({"id":10,"result":{"model":MODEL,"reasoningEffort":"high","modelProvider":"declared-provider",
        "thread":{"id":"thread-a","modelProvider":"declared-provider"}}})
}

fn turn(status: &str) -> Value {
    json!({"id":"turn-a","status":status,"items":[]})
}

fn turn_response() -> Value { json!({"id":20,"result":{"turn":turn("inProgress")}}) }

fn notification(method: &str, status: &str) -> Value {
    json!({"method":method,"params":{"threadId":"thread-a","turn":turn(status)}})
}

fn close() -> Value { json!({"method":"thread/closed","params":{"threadId":"thread-a"}}) }

fn bound() -> NativeObservationTracker {
    let mut tracker = tracker();
    tracker.observe_frame(&thread_response()).unwrap();
    tracker.observe_frame(&turn_response()).unwrap();
    tracker
}

fn deny(tracker: &mut NativeObservationTracker, frame: &Value, kind: ErrorKind) {
    assert_eq!(tracker.observe_frame(frame).unwrap_err().kind, kind);
    assert_eq!(tracker.report()["fail_closed"], true);
    assert_unadmitted(tracker);
}

fn assert_unadmitted(tracker: &NativeObservationTracker) {
    let report = tracker.report();
    for field in ["runtime_admission", "store_admission", "authority_granted"] { assert_eq!(report[field], false, "{field}"); }
    for field in ["effective_model", "effective_effort", "effective_provider", "effective_native_quota", "built_in_subagent_quota", "fee_observation"] {
        assert_eq!(report[field], "unknown", "{field}");
    }
}

#[test]
fn constructor_pins_model_efforts_and_distinct_rpc_ids() {
    for effort in ["medium", "high", "xhigh"] {
        let tracker = NativeObservationTracker::new(MODEL, effort, 0, u64::MAX).unwrap();
        assert_eq!(tracker.report()["requested_effort"], effort);
        assert_unadmitted(&tracker);
    }
    for model in ["", "auto", "gpt-5", "GPT-6.1-sol", "gpt-6.1-sol "] {
        assert_eq!(NativeObservationTracker::new(model, "high", 10, 20).err().unwrap().kind, ErrorKind::ScopeDenied);
    }
    for effort in ["", "low", "auto", "High", "high "] {
        assert_eq!(NativeObservationTracker::new(MODEL, effort, 10, 20).err().unwrap().kind, ErrorKind::ScopeDenied);
    }
    assert_eq!(NativeObservationTracker::new(MODEL, "high", 10, 10).err().unwrap().kind, ErrorKind::Shape);
}

#[test]
fn matched_lifecycle_only_observes_and_does_not_authorize() {
    let mut tracker = bound();
    assert_eq!(tracker.report()["declared_model"], MODEL);
    assert_eq!(tracker.report()["declared_effort"], "high");
    assert_eq!(tracker.report()["declared_provider"], "declared-provider");
    tracker.observe_frame(&notification("turn/started", "inProgress")).unwrap();
    tracker.observe_frame(&notification("turn/completed", "completed")).unwrap();
    assert_eq!(tracker.report()["turn_completed_observed"], true);
    assert_eq!(tracker.report()["thread_closed_observed"], false);
    tracker.observe_frame(&json!({"id":30,"result":{"status":"unsubscribed"}})).unwrap();
    assert_eq!(tracker.report()["thread_closed_observed"], false);
    tracker.observe_frame(&close()).unwrap();
    for field in ["thread_start_response_observed", "turn_start_response_observed", "turn_started_observed", "turn_completed_observed", "thread_closed_observed"] {
        assert_eq!(tracker.report()[field], true, "{field}");
    }
    assert_eq!(tracker.report()["turn_status"], "completed");
    assert_eq!(tracker.report()["fail_closed"], false);
    assert_unadmitted(&tracker);
}

#[test]
fn emitted_transport_timestamp_is_accepted_without_authority() {
    let mut tracker = bound();
    let mut frame = notification("turn/started", "inProgress");
    frame["emittedAtMs"] = json!(1791043600747u64);
    tracker.observe_frame(&frame).unwrap();
    assert_eq!(tracker.report()["turn_started_observed"], true);
    assert_eq!(tracker.report()["authority_granted"], false);
}

#[test]
fn absent_or_null_thread_effort_is_unknown_not_requested_high() {
    for missing in [true, false] {
        let mut frame = thread_response();
        if missing { frame["result"].as_object_mut().unwrap().remove("reasoningEffort"); }
        else { frame["result"]["reasoningEffort"] = Value::Null; }
        let mut tracker = tracker();
        tracker.observe_frame(&frame).unwrap();
        assert_eq!(tracker.report()["declared_effort"], "unknown");
        assert_eq!(tracker.report()["requested_effort"], "high");
        assert_unadmitted(&tracker);
    }
}

#[test]
fn mismatching_declarations_fail_closed_without_binding() {
    for (field, value, expected) in [("model","other",ErrorKind::ScopeDenied), ("reasoningEffort","medium",ErrorKind::ScopeDenied), ("modelProvider","other",ErrorKind::EventConflict)] {
        let mut frame = thread_response();
        frame["result"][field] = json!(value);
        let mut tracker = tracker();
        deny(&mut tracker, &frame, expected);
        assert!(tracker.report()["thread_id"].is_null());
    }
}

#[test]
fn wrong_rpc_id_never_binds_and_unrelated_ack_never_closes() {
    let mut tracker = tracker();
    let mut frame = thread_response();
    frame["id"] = json!(11);
    tracker.observe_frame(&frame).unwrap();
    frame = turn_response();
    frame["id"] = json!(21);
    tracker.observe_frame(&frame).unwrap();
    tracker.observe_frame(&json!({"id":30,"error":{"code":-1,"message":"unrelated"}})).unwrap();
    assert!(tracker.report()["thread_id"].is_null());
    assert!(tracker.report()["turn_id"].is_null());
    assert_eq!(tracker.report()["fail_closed"], false);
    assert_eq!(tracker.report()["thread_closed_observed"], false);
}

#[test]
fn identical_events_are_idempotent_including_key_order_and_jsonrpc() {
    let mut tracker = tracker();
    for mut frame in [thread_response(), turn_response(), notification("turn/started", "inProgress"), notification("turn/completed", "completed"), close()] {
        tracker.observe_frame(&frame).unwrap();
        let before = tracker.report();
        frame["jsonrpc"] = json!("2.0");
        for _ in 0..4 { tracker.observe_frame(&frame).unwrap(); assert_eq!(tracker.report(), before); }
    }
    assert!(tracker.events.len() <= 6);
}

#[test]
fn conflicting_duplicate_rpc_payload_preserves_bound_identity() {
    for is_thread in [true, false] {
        let mut tracker = bound();
        let mut frame = if is_thread { thread_response() } else { turn_response() };
        if is_thread { frame["result"]["thread"]["id"] = json!("other"); }
        else { frame["result"]["turn"]["id"] = json!("other"); }
        deny(&mut tracker, &frame, ErrorKind::EventConflict);
        assert_eq!(tracker.report()["thread_id"], "thread-a");
        assert_eq!(tracker.report()["turn_id"], "turn-a");
    }
}

#[test]
fn conflicting_duplicate_notification_does_not_replace_observation() {
    let mut tracker = bound();
    let mut frame = notification("turn/completed", "completed");
    tracker.observe_frame(&frame).unwrap();
    frame["params"]["turn"]["status"] = json!("failed");
    deny(&mut tracker, &frame, ErrorKind::EventConflict);
    assert_eq!(tracker.report()["turn_status"], "completed");
    assert_eq!(tracker.report()["thread_closed_observed"], false);
}

#[test]
fn foreign_thread_and_turn_notifications_fail_closed() {
    for method in ["turn/started", "turn/completed", "thread/closed"] {
        let mut tracker = bound();
        let mut frame = if method == "thread/closed" { close() } else { notification(method, if method == "turn/started" { "inProgress" } else { "completed" }) };
        frame["params"]["threadId"] = json!("foreign");
        deny(&mut tracker, &frame, ErrorKind::Reference);
        assert_eq!(tracker.report()["thread_closed_observed"], false);
    }
    for method in ["turn/started", "turn/completed"] {
        let mut tracker = bound();
        let mut frame = notification(method, if method == "turn/started" { "inProgress" } else { "completed" });
        frame["params"]["turn"]["id"] = json!("foreign");
        deny(&mut tracker, &frame, ErrorKind::Reference);
        assert_eq!(tracker.report()["turn_completed_observed"], false);
    }
}

#[test]
fn early_turn_notifications_need_matching_rpc_before_reporting_turn() {
    let mut tracker = tracker();
    tracker.observe_frame(&thread_response()).unwrap();
    tracker.observe_frame(&notification("turn/started", "inProgress")).unwrap();
    tracker.observe_frame(&notification("turn/completed", "completed")).unwrap();
    assert_eq!(tracker.report()["turn_started_observed"], false);
    assert_eq!(tracker.report()["turn_completed_observed"], false);
    assert!(tracker.report()["turn_id"].is_null());
    tracker.observe_frame(&turn_response()).unwrap();
    assert_eq!(tracker.report()["turn_started_observed"], true);
    assert_eq!(tracker.report()["turn_completed_observed"], true);
    assert_eq!(tracker.report()["thread_closed_observed"], false);
}

#[test]
fn pending_notification_cannot_bind_a_different_rpc_turn() {
    let mut tracker = tracker();
    tracker.observe_frame(&thread_response()).unwrap();
    tracker.observe_frame(&notification("turn/started", "inProgress")).unwrap();
    let mut frame = turn_response();
    frame["result"]["turn"]["id"] = json!("other");
    deny(&mut tracker, &frame, ErrorKind::Reference);
    assert!(tracker.report()["turn_id"].is_null());
    assert_eq!(tracker.report()["turn_started_observed"], false);
}

#[test]
fn unbound_thread_close_or_turn_response_is_not_trusted() {
    for frame in [close(), turn_response(), notification("turn/started", "inProgress")] {
        let mut tracker = tracker();
        deny(&mut tracker, &frame, ErrorKind::HostUnknown);
        assert_eq!(tracker.report()["thread_closed_observed"], false);
    }
}

#[test]
fn terminal_turns_are_not_closes_even_when_failed_or_interrupted() {
    for status in ["completed", "failed", "interrupted"] {
        let mut tracker = bound();
        tracker.observe_frame(&notification("turn/completed", status)).unwrap();
        assert_eq!(tracker.report()["turn_status"], status);
        assert_eq!(tracker.report()["thread_closed_observed"], false);
        assert_unadmitted(&tracker);
    }
}

#[test]
fn terminal_status_in_start_response_is_not_a_completed_notification() {
    for status in ["completed", "failed", "interrupted"] {
        let mut tracker = tracker();
        tracker.observe_frame(&thread_response()).unwrap();
        let mut frame = turn_response();
        frame["result"]["turn"]["status"] = json!(status);
        tracker.observe_frame(&frame).unwrap();
        assert_eq!(tracker.report()["turn_start_response_observed"], true);
        assert_eq!(tracker.report()["turn_completed_observed"], false);
        assert_eq!(tracker.report()["thread_closed_observed"], false);
    }
}

#[test]
fn rpc_errors_are_idempotent_failures_and_never_close() {
    for request_id in [10, 20] {
        let mut tracker = if request_id == 10 { tracker() } else {
            let mut tracker = tracker();
            tracker.observe_frame(&thread_response()).unwrap();
            tracker
        };
        let frame = json!({"id":request_id,"error":{"code":-32000,"message":"timeout"}});
        deny(&mut tracker, &frame, ErrorKind::HostUnknown);
        let before = tracker.report();
        deny(&mut tracker, &frame, ErrorKind::HostUnknown);
        assert_eq!(tracker.report(), before);
        assert_eq!(tracker.report()["thread_closed_observed"], false);
        if request_id == 20 {
            tracker.observe_frame(&close()).unwrap();
            assert_eq!(tracker.report()["thread_closed_observed"], true);
            assert_eq!(tracker.report()["fail_closed"], true);
        }
    }
}

#[test]
fn silence_and_unsubscribe_notifications_do_not_create_close_evidence() {
    let mut tracker = bound();
    for _ in 0..4 { assert_eq!(tracker.report()["thread_closed_observed"], false); }
    for status in ["unsubscribed", "notSubscribed", "notLoaded"] {
        tracker.observe_frame(&json!({"id":30,"result":{"status":status}})).unwrap();
    }
    tracker.observe_frame(&json!({"method":"thread/unsubscribed","params":{"threadId":"thread-a"}})).unwrap();
    assert_eq!(tracker.report()["thread_closed_observed"], false);
    assert_eq!(tracker.events.len(), 2);
}

#[test]
fn matching_reroute_is_sticky_fail_closed_and_duplicate_safe() {
    let mut tracker = bound();
    let frame = json!({"method":"model/rerouted","params":{"threadId":"thread-a","turnId":"turn-a",
        "fromModel":MODEL,"toModel":"other","reason":"highRiskCyberActivity"}});
    deny(&mut tracker, &frame, ErrorKind::ScopeDenied);
    assert_eq!(tracker.report()["reroute_observed"], true);
    let before = tracker.report();
    deny(&mut tracker, &frame, ErrorKind::ScopeDenied);
    assert_eq!(tracker.report(), before);
    let mut changed = frame.clone();
    changed["params"]["toModel"] = json!(MODEL);
    deny(&mut tracker, &changed, ErrorKind::EventConflict);
    tracker.observe_frame(&close()).unwrap();
    assert_eq!(tracker.report()["fail_closed"], true);
    assert_eq!(tracker.report()["thread_closed_observed"], true);
    assert_unadmitted(&tracker);
}

#[test]
fn reroute_wrong_thread_or_turn_cannot_match() {
    for field in ["threadId", "turnId"] {
        let mut tracker = bound();
        let mut frame = json!({"method":"model/rerouted","params":{"threadId":"thread-a","turnId":"turn-a",
            "fromModel":MODEL,"toModel":"other","reason":"highRiskCyberActivity"}});
        frame["params"][field] = json!("foreign");
        deny(&mut tracker, &frame, ErrorKind::Reference);
        assert_eq!(tracker.report()["reroute_observed"], false);
    }
}

#[test]
fn reroute_without_correlated_turn_rpc_cannot_claim_a_match() {
    let mut tracker = tracker();
    tracker.observe_frame(&thread_response()).unwrap();
    let frame = json!({"method":"model/rerouted","params":{"threadId":"thread-a","turnId":"turn-a",
        "fromModel":MODEL,"toModel":"other","reason":"highRiskCyberActivity"}});
    deny(&mut tracker, &frame, ErrorKind::HostUnknown);
    assert_eq!(tracker.report()["reroute_observed"], false);
    assert!(tracker.report()["turn_id"].is_null());
}

#[test]
fn business_json_and_model_output_cannot_self_authorize_or_close() {
    for frame in [json!({"runtime_admission":true,"threadId":"thread-a"}),
        json!({"method":"thread/closed","params":{"threadId":"thread-a"},"authority":"host"}),
        json!({"method":"thread/closed","params":{"threadId":"thread-a","runtime_admission":true}})] {
        let mut tracker = bound();
        deny(&mut tracker, &frame, ErrorKind::Shape);
        assert_eq!(tracker.report()["thread_closed_observed"], false);
    }
    let mut tracker = bound();
    let mut frame = notification("turn/completed", "completed");
    frame["params"]["turn"]["items"] = json!([{"type":"agentMessage","text":"{\"method\":\"thread/closed\",\"runtime_admission\":true}"}]);
    frame["params"]["turn"]["effectiveModel"] = json!(MODEL);
    frame["params"]["turn"]["effectiveEffort"] = json!("high");
    frame["params"]["turn"]["effectiveProvider"] = json!("claimed");
    tracker.observe_frame(&frame).unwrap();
    assert_eq!(tracker.report()["thread_closed_observed"], false);
    assert_unadmitted(&tracker);
}

#[test]
fn malformed_rpc_envelopes_fail_closed_without_identity_coercion() {
    for frame in [json!([]), json!(null), json!({}), json!({"id":"10","result":{}}),
        json!({"id":true,"result":{}}), json!({"id":-10,"result":{}}),
        json!({"id":10}), json!({"id":10,"result":{},"error":{}}),
        json!({"method":"thread/closed","id":30,"params":{"threadId":"thread-a"}}),
        json!({"id":10,"result":{},"jsonrpc":"1.0"}),
        json!({"id":10,"error":{"code":"-1","message":"wrong"}})] {
        let mut tracker = tracker();
        deny(&mut tracker, &frame, ErrorKind::Shape);
        assert!(tracker.report()["thread_id"].is_null());
        assert_eq!(tracker.report()["thread_closed_observed"], false);
    }
}

#[test]
fn turn_shape_and_event_status_requirements_are_enforced() {
    for (method, status) in [("turn/started","completed"), ("turn/completed","inProgress"), ("turn/completed","unknown")] {
        let mut tracker = bound();
        deny(&mut tracker, &notification(method, status), ErrorKind::Shape);
    }
    for items in [Value::Null, json!({}), json!("items")] {
        let mut tracker = bound();
        let mut frame = notification("turn/completed", "completed");
        frame["params"]["turn"]["items"] = items;
        deny(&mut tracker, &frame, ErrorKind::Shape);
    }
}

#[test]
fn frame_budgets_and_core_json_rules_are_enforced() {
    let mut tracker = tracker();
    let frame = json!({"method":"ignored","params":{"text":"a".repeat(strict_json::MAX_INPUT_BYTES)}});
    deny(&mut tracker, &frame, ErrorKind::BudgetExhausted);
    let mut tracker = NativeObservationTracker::new(MODEL, "high", 10, 20).unwrap();
    deny(&mut tracker, &json!({"id":10.5,"result":{}}), ErrorKind::Shape);
    let mut tracker = NativeObservationTracker::new(MODEL, "high", 10, 20).unwrap();
    let mut nested = Value::Null;
    for _ in 0..130 { nested = json!([nested]); }
    deny(&mut tracker, &nested, ErrorKind::BudgetExhausted);
}

#[test]
fn new_turn_event_after_real_close_conflicts_without_erasing_close() {
    let mut tracker = bound();
    tracker.observe_frame(&close()).unwrap();
    deny(&mut tracker, &notification("turn/started", "inProgress"), ErrorKind::EventConflict);
    assert_eq!(tracker.report()["thread_closed_observed"], true);
}

#[test]
fn schema_sources_confirm_field_assumptions_without_claiming_execution() {
    let thread: Value = serde_json::from_str(include_str!("../.dev/native-protocol-schema-0.160.0/v2/ThreadStartResponse.json")).unwrap();
    for field in ["model", "modelProvider", "reasoningEffort", "thread"] { assert!(thread["properties"].get(field).is_some()); }
    let turn: Value = serde_json::from_str(include_str!("../.dev/native-protocol-schema-0.160.0/v2/TurnStartResponse.json")).unwrap();
    assert!(turn["properties"].get("turn").is_some());
    assert!(turn["properties"].get("threadId").is_none());
    for field in ["model", "modelProvider", "effort", "effectiveModel", "effectiveEffort", "effectiveProvider"] {
        assert!(turn["definitions"]["Turn"]["properties"].get(field).is_none(), "{field}");
    }
    let close: Value = serde_json::from_str(include_str!("../.dev/native-protocol-schema-0.160.0/v2/ThreadClosedNotification.json")).unwrap();
    assert_eq!(close["required"], json!(["threadId"]));
    let evidence: Value = serde_json::from_str(include_str!("../outputs/p2/native-protocol-source-evidence.json")).unwrap();
    assert_eq!(evidence["local_protocol"]["cli_version"], "0.160.0");
    assert_eq!(evidence["local_protocol"]["generation_submitted"], false);
    assert_unadmitted(&tracker());
}

#[test]
fn protocol_mcp_numbers_are_accepted_without_coercing_rpc_ids() {
    let mut tracker = bound();
    let mut completed = notification("turn/completed", "completed");
    completed["params"]["turn"]["items"] = json!([{
        "type":"mcpToolCall","arguments":{"strength":0.25},"result":{"ratio":0.5}
    }]);
    tracker.observe_frame(&completed).unwrap();
    assert_eq!(tracker.report()["turn_completed_observed"], true);
    tracker.observe_frame(&completed).unwrap();
    let mut malformed = thread_response();
    malformed["id"] = json!(10.0);
    deny(&mut tracker, &malformed, ErrorKind::Shape);
    assert_unadmitted(&tracker);
}
