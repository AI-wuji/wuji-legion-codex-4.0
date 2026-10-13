import copy
import unittest
from unittest.mock import patch

from native_host_session import ObservationTimeout, SessionError
from native_task_driver import MODEL, RETURN_KEYS, run_task


class FakeSession:
    def __init__(self, events=None, timeout=False):
        self.events = list(events or [])
        self.timeout = timeout
        self.calls = []
        self.event_calls = []
        self.closed = []
        self.started = 0
        self.results = {
            0: {"ok": True},
            1: {
                "thread": {"id": "thread-1", "modelProvider": "fixture"},
                "model": MODEL,
            },
            2: {"turn": {"id": "turn-1", "status": "inProgress", "items": []}},
            3: {"status": "unsubscribed"},
        }

    def start(self):
        self.started += 1

    def request(self, request_id, method, params, timeout=30):
        self.calls.append(("request", request_id, method, copy.deepcopy(params)))
        return copy.deepcopy(self.results[request_id])

    def notify(self, method, params):
        self.calls.append(("notify", method, copy.deepcopy(params)))

    def next_event(self, thread_id, timeout=30):
        self.event_calls.append((thread_id, timeout))
        if self.timeout:
            raise ObservationTimeout("fixture timeout")
        if not self.events:
            raise ObservationTimeout("fixture timeout")
        return copy.deepcopy(self.events.pop(0))

    def close(self, timeout=5):
        self.closed.append(timeout)
        return {"owned_process_exited": True, "exit_code": 0}


def started(turn_id="turn-1"):
    return {
        "method": "turn/started",
        "params": {
            "threadId": "thread-1",
            "turn": {"id": turn_id, "status": "inProgress", "items": []},
        },
    }


def item(text, turn_id="turn-1"):
    return {
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": turn_id,
            "item": {"type": "agentMessage", "text": text},
        },
    }


def completed(turn_id="turn-1", text=None):
    event = {
        "method": "turn/completed",
        "params": {
            "threadId": "thread-1",
            "turn": {"id": turn_id, "status": "completed", "items": []},
        },
    }
    if text is not None:
        event["params"]["turn"]["items"] = [{"type": "agentMessage", "text": text}]
    return event


def closed():
    return {"method": "thread/closed", "params": {"threadId": "thread-1"}}


class NativeTaskDriverTests(unittest.TestCase):
    def test_success_preserves_bindings_and_returns_only_declared_keys(self):
        session = FakeSession([started(), item("first"), item("second"), completed(), closed()])
        thread_params = {"model": MODEL, "sandbox": {"type": "read-only"}}
        turn_params = {"model": MODEL, "effort": "xhigh", "input": {"nested": ["value"]}}
        original_thread = copy.deepcopy(thread_params)
        original_turn = copy.deepcopy(turn_params)

        result = run_task(session, thread_params, turn_params, timeout=1, close_timeout=2)

        self.assertEqual(RETURN_KEYS, set(result))
        self.assertEqual("thread-1", result["thread_id"])
        self.assertEqual("turn-1", result["turn_id"])
        self.assertEqual("first\nsecond", result["generated_text"])
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["thread_closed_observed"])
        self.assertEqual({"owned_process_exited": True, "exit_code": 0}, result["owned_process_exit"])
        self.assertEqual(original_thread, thread_params)
        self.assertEqual(original_turn, turn_params)
        self.assertEqual(1, session.started)
        self.assertEqual(2, session.closed[0])
        self.assertEqual(5, len(session.event_calls))
        self.assertEqual("thread-1", session.event_calls[0][0])
        calls = session.calls
        self.assertEqual(("request", 0, "initialize", {
            "clientInfo": {"name": "wuji4-native-task-driver", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        }), calls[0])
        self.assertEqual(("notify", "initialized", {}), calls[1])
        self.assertEqual(True, calls[2][3]["ephemeral"])
        self.assertEqual(MODEL, calls[2][3]["model"])
        self.assertEqual("thread-1", calls[3][3]["threadId"])
        self.assertEqual(MODEL, calls[3][3]["model"])
        self.assertEqual("xhigh", calls[3][3]["effort"])
        self.assertEqual(("request", 3, "thread/unsubscribe", {"threadId": "thread-1"}), calls[4])
        self.assertEqual([1, 2, "turn/started", "turn/completed", "thread/closed"],
                         [observation.get("id", observation.get("method")) for observation in result["observations"]])
        self.assertEqual("reconstructed", result["observations"][0]["transport_provenance"]["envelope"])
        self.assertNotIn("first", repr(result["observations"]))

    def test_arbitrary_baseline_model_and_none_effort_are_preserved(self):
        for model in ("gpt-6-astra", "custom/baseline-v2"):
            with self.subTest(model=model):
                session = FakeSession([started(), completed(text="baseline"), closed()])
                session.results[1]["model"] = model
                thread_params = {"model": model}
                turn_params = {"model": model, "effort": "none"}
                original = copy.deepcopy((thread_params, turn_params))

                result = run_task(session, thread_params, turn_params, timeout=1, close_timeout=1)

                self.assertEqual("completed", result["status"])
                self.assertEqual(RETURN_KEYS, set(result))
                self.assertEqual(model, session.calls[2][3]["model"])
                self.assertEqual(model, session.calls[3][3]["model"])
                self.assertEqual("none", session.calls[3][3]["effort"])
                self.assertEqual(original, (thread_params, turn_params))
                self.assertEqual("unknown", result["backend_effective_model"])
                self.assertEqual("unknown", result["backend_effective_effort"])

    def test_omitted_model_and_effort_inherit_without_sol_default(self):
        session = FakeSession([started(), completed(), closed()])
        session.results[1]["model"] = "host-configured-model"
        thread_params = {"sandbox": {"type": "read-only"}}
        turn_params = {"input": {"nested": ["value"]}}
        original = copy.deepcopy((thread_params, turn_params))

        result = run_task(session, thread_params, turn_params, timeout=1, close_timeout=1)

        self.assertEqual("completed", result["status"])
        self.assertNotIn("model", session.calls[2][3])
        self.assertNotIn("effort", session.calls[2][3])
        self.assertEqual("host-configured-model", session.calls[3][3]["model"])
        self.assertNotIn("effort", session.calls[3][3])
        self.assertEqual(original, (thread_params, turn_params))
        self.assertEqual("unknown", result["backend_effective_model"])
        self.assertEqual("unknown", result["backend_effective_effort"])

    def test_explicit_thread_upgrade_preserves_requested_effort(self):
        for effort in ("high", "xhigh"):
            with self.subTest(effort=effort):
                session = FakeSession([started(), completed(), closed()])
                result = run_task(session, {"model": MODEL}, {"effort": effort},
                                  timeout=1, close_timeout=1)
                self.assertEqual("completed", result["status"])
                self.assertEqual(MODEL, session.calls[2][3]["model"])
                self.assertEqual(MODEL, session.calls[3][3]["model"])
                self.assertEqual(effort, session.calls[3][3]["effort"])
                self.assertEqual("unknown", result["backend_effective_model"])

    def test_explicit_turn_model_can_override_thread_declaration(self):
        for model, effort in ((MODEL, "high"), (MODEL, "xhigh"), ("other-model", "none")):
            with self.subTest(model=model, effort=effort):
                session = FakeSession([started(), completed(), closed()])
                session.results[1]["model"] = "baseline-model"
                thread_params = {"model": "baseline-model"}
                turn_params = {"model": model, "effort": effort}
                original = copy.deepcopy((thread_params, turn_params))

                result = run_task(session, thread_params, turn_params, timeout=1, close_timeout=1)

                self.assertEqual("completed", result["status"])
                self.assertEqual("baseline-model", session.calls[2][3]["model"])
                self.assertEqual(model, session.calls[3][3]["model"])
                self.assertEqual(effort, session.calls[3][3]["effort"])
                self.assertEqual(original, (thread_params, turn_params))
                self.assertEqual("unknown", result["backend_effective_model"])
                self.assertEqual("unknown", result["backend_effective_effort"])

    def test_effort_strings_are_forwarded_without_a_local_support_enum(self):
        # A valid string is not proof of host support; the host owns validation.
        for effort in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "future-host-effort"):
            with self.subTest(effort=effort):
                session = FakeSession([started(), completed(), closed()])
                result = run_task(session, {}, {"effort": effort}, timeout=1, close_timeout=1)
                self.assertEqual("completed", result["status"])
                self.assertEqual(effort, session.calls[3][3]["effort"])
                self.assertEqual("unknown", result["backend_effective_effort"])

    def test_invalid_model_and_effort_inputs_fail_before_session_start(self):
        for scope in ("thread", "turn"):
            for field in ("model", "effort"):
                for value in (None, "", " \t\n", False, 7, [], {}):
                    with self.subTest(scope=scope, field=field, value=value):
                        session = FakeSession()
                        thread_params, turn_params = {}, {}
                        target = thread_params if scope == "thread" else turn_params
                        target[field] = value
                        original = copy.deepcopy((thread_params, turn_params))

                        result = run_task(session, thread_params, turn_params, timeout=1, close_timeout=1)

                        self.assertEqual("failed", result["status"])
                        self.assertEqual("start", result["failure_phase"])
                        self.assertIn(f"{scope} {field}", result["failure_detail"])
                        self.assertEqual(0, session.started)
                        self.assertEqual([], session.calls)
                        self.assertEqual(1, len(session.closed))
                        self.assertEqual(original, (thread_params, turn_params))
                        self.assertEqual(RETURN_KEYS, set(result))

    def test_missing_or_malformed_thread_model_declarations_fail_closed(self):
        for requested in ({}, {"model": MODEL}):
            for declaration in (None, "", " \t", False, 7, [], {}):
                with self.subTest(requested=requested, declaration=declaration):
                    session = FakeSession()
                    session.results[1]["model"] = declaration
                    result = run_task(session, requested, {}, timeout=1, close_timeout=1)
                    self.assertEqual("failed", result["status"])
                    self.assertEqual("thread/start", result["failure_phase"])
                    self.assertIsNone(result["thread_id"])
                    self.assertFalse(any(call[0] == "request" and call[2] == "turn/start"
                                         for call in session.calls))
                    self.assertEqual(1, len(session.closed))
                    self.assertEqual("unknown", result["backend_effective_model"])
        session = FakeSession()
        del session.results[1]["model"]
        result = run_task(session, {}, {}, timeout=1, close_timeout=1)
        self.assertEqual("failed", result["status"])
        self.assertEqual("thread/start", result["failure_phase"])
        self.assertIsNone(result["turn_id"])

    def test_non_object_thread_receipt_is_a_bounded_failure(self):
        for receipt in (None, "bad-receipt", [], 7):
            with self.subTest(receipt=receipt):
                session = FakeSession()
                session.results[1] = receipt
                result = run_task(session, {}, {}, timeout=1, close_timeout=1)
                self.assertEqual("failed", result["status"])
                self.assertEqual("thread/start", result["failure_phase"])
                self.assertIn("must be an object", result["failure_detail"])
                self.assertEqual([], session.event_calls)
                self.assertEqual(1, len(session.closed))

    def test_thread_declaration_must_match_an_explicit_request(self):
        for requested, declared in (("baseline-model", MODEL), (MODEL, "baseline-model")):
            with self.subTest(requested=requested, declared=declared):
                session = FakeSession()
                session.results[1]["model"] = declared
                result = run_task(session, {"model": requested}, {"model": declared, "effort": "none"},
                                  timeout=1, close_timeout=1)
                self.assertEqual("failed", result["status"])
                self.assertEqual("thread/start", result["failure_phase"])
                self.assertIn("mismatches request", result["failure_detail"])
                self.assertEqual(requested, session.calls[2][3]["model"])
                self.assertFalse(any(call[0] == "request" and call[2] == "turn/start"
                                     for call in session.calls))
                self.assertEqual(1, len(session.closed))

    def test_host_rejection_does_not_change_effort_or_resubmit(self):
        session = FakeSession()
        request = session.request

        def reject_effort(request_id, method, params, timeout=30):
            response = request(request_id, method, params, timeout=timeout)
            if method == "turn/start":
                raise SessionError("fixture host rejects unsupported effort")
            return response

        with patch.object(session, "request", side_effect=reject_effort):
            result = run_task(session, {}, {"effort": "host-unsupported"}, timeout=1, close_timeout=1)

        self.assertEqual("failed", result["status"])
        self.assertEqual("turn/start", result["failure_phase"])
        turn_calls = [call for call in session.calls if call[0] == "request" and call[2] == "turn/start"]
        self.assertEqual(1, len(turn_calls))
        self.assertEqual("host-unsupported", turn_calls[0][3]["effort"])
        self.assertEqual("unknown", result["backend_effective_effort"])
        self.assertEqual(1, len(session.closed))

    def test_nested_inputs_are_not_mutated_even_by_session_requests(self):
        session = FakeSession([started(), completed(), closed()])
        session.results[1]["model"] = "baseline-model"
        thread_params = {"model": "baseline-model", "metadata": {"values": ["original"]}}
        turn_params = {"effort": "none", "input": {"values": ["original"]}}
        original = copy.deepcopy((thread_params, turn_params))
        request = session.request

        def mutate_nested(request_id, method, params, timeout=30):
            if method == "thread/start":
                params["metadata"]["values"].append("session-mutated")
            if method == "turn/start":
                params["input"]["values"].append("session-mutated")
            return request(request_id, method, params, timeout=timeout)

        with patch.object(session, "request", side_effect=mutate_nested):
            result = run_task(session, thread_params, turn_params, timeout=1, close_timeout=1)

        self.assertEqual("completed", result["status"])
        self.assertEqual(original, (thread_params, turn_params))
        self.assertIn("session-mutated", session.calls[2][3]["metadata"]["values"])
        self.assertIn("session-mutated", session.calls[3][3]["input"]["values"])

    def test_reroute_is_observed_without_fallback_or_backend_claims(self):
        reroute = {"method": "model/rerouted", "params": {
            "threadId": "thread-1", "turnId": "turn-1", "model": "rerouted-model",
        }}
        foreign_reroute = copy.deepcopy(reroute)
        foreign_reroute["params"]["turnId"] = "foreign"
        session = FakeSession([started(), foreign_reroute, reroute, completed(), closed()])
        session.results[1]["model"] = "baseline-model"

        result = run_task(session, {}, {"effort": "none"}, timeout=1, close_timeout=1)

        self.assertEqual("rerouted", result["status"])
        self.assertTrue(result["thread_closed_observed"])
        self.assertIn(reroute, result["observations"])
        self.assertNotIn(foreign_reroute, result["observations"])
        self.assertEqual("unknown", result["backend_effective_model"])
        self.assertEqual("unknown", result["backend_effective_effort"])
        self.assertEqual(1, len([call for call in session.calls
                                if call[0] == "request" and call[2] == "turn/start"]))
        self.assertFalse(result["runtime_admission"])
        self.assertFalse(result["store_admission"])

    def test_turn_receipt_cannot_bind_a_foreign_thread(self):
        session = FakeSession([started(), completed(), closed()])
        session.results[1]["model"] = "baseline-model"
        session.results[2]["threadId"] = "foreign-thread"

        result = run_task(session, {}, {"effort": "none"}, timeout=1, close_timeout=1)

        self.assertEqual("failed", result["status"])
        self.assertEqual("turn/start", result["failure_phase"])
        self.assertEqual("thread-1", result["thread_id"])
        self.assertIsNone(result["turn_id"])
        self.assertEqual([], session.event_calls)
        self.assertEqual(1, len(session.closed))

    def test_foreign_turn_notifications_are_not_claimed(self):
        session = FakeSession([
            started("foreign"),
            item("foreign-text", "foreign"),
            started(),
            item("owned-text"),
            completed("foreign"),
            completed(),
            closed(),
        ])

        result = run_task(session, {}, {"effort": "medium"}, timeout=1, close_timeout=1)

        self.assertEqual("owned-text", result["generated_text"])
        methods = [observation["method"] for observation in result["observations"] if "method" in observation]
        self.assertEqual(["turn/started", "turn/completed", "thread/closed"], methods[0:])
        self.assertNotIn("foreign", repr(result["observations"]))

    def test_timeout_is_unknown_without_generation_retry(self):
        session = FakeSession(timeout=True)

        result = run_task(session, {}, {"effort": "high"}, timeout=1, close_timeout=1)

        self.assertEqual("unknown", result["status"])
        self.assertEqual(1, len([call for call in session.calls if call[0] == "request" and call[2] == "turn/start"]))
        self.assertEqual({"owned_process_exited": True, "exit_code": 0}, result["owned_process_exit"])
        self.assertFalse(result["thread_closed_observed"])

    def test_turn_completion_items_are_preserved_and_close_has_own_budget(self):
        session = FakeSession([started(), completed(text="completed-text"), closed()])
        result = run_task(session, {}, {"effort": "high"}, timeout=0.1, close_timeout=2)
        self.assertEqual("completed-text", result["generated_text"])
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["thread_closed_observed"])

    def test_same_agent_message_id_is_not_collected_twice(self):
        event = completed()
        event["params"]["turn"]["items"] = [{"type": "agentMessage", "id": "message-1", "text": "same"}]
        item_event = item("same")
        item_event["params"]["item"]["id"] = "message-1"
        session = FakeSession([started(), item_event, event, closed()])
        result = run_task(session, {}, {"effort": "high"}, timeout=1, close_timeout=1)
        self.assertEqual("same", result["generated_text"])

    def test_conflicting_turn_ids_cannot_claim_foreign_completion(self):
        foreign = completed("foreign", text="foreign-text")
        foreign["params"]["turnId"] = "turn-1"
        session = FakeSession([started(), foreign, completed(text="owned-text"), closed()])

        result = run_task(session, {}, {"effort": "high"}, timeout=1, close_timeout=1)

        self.assertEqual("completed", result["status"])
        self.assertEqual("owned-text", result["generated_text"])
        self.assertNotIn("foreign", repr(result["observations"]))
        self.assertEqual(1, len(session.closed))

    def test_foreign_notifications_cannot_extend_observation_deadline(self):
        clock = [0.0]
        session = FakeSession([started("foreign"), completed(text="late-text"), closed()])
        next_event = session.next_event

        def advance_clock(thread_id, timeout=30):
            event = next_event(thread_id, timeout=timeout)
            clock[0] = 2.0
            return event

        with patch("native_task_driver.time.monotonic", side_effect=lambda: clock[0]), patch.object(
            session, "next_event", side_effect=advance_clock
        ):
            result = run_task(session, {}, {"effort": "high"}, timeout=1, close_timeout=1)

        self.assertEqual("unknown", result["status"])
        self.assertEqual("turn/observation", result["failure_phase"])
        self.assertEqual("", result["generated_text"])
        self.assertEqual(1, len(session.event_calls))
        self.assertFalse(result["thread_closed_observed"])
        self.assertFalse(any(call[0] == "request" and call[2] == "thread/unsubscribe" for call in session.calls))
        self.assertEqual(1, len(session.closed))

    def test_completed_output_survives_close_timeout_without_claiming_release(self):
        session = FakeSession([started(), item("first"), completed(text="second")])

        result = run_task(session, {}, {"effort": "high"}, timeout=1, close_timeout=1)

        self.assertEqual("unknown", result["status"])
        self.assertEqual("thread/closed", result["failure_phase"])
        self.assertEqual("first\nsecond", result["generated_text"])
        self.assertFalse(result["thread_closed_observed"])
        self.assertFalse(result["runtime_admission"])
        self.assertFalse(result["store_admission"])
        self.assertEqual(1, len(session.closed))
        self.assertEqual(1, len([call for call in session.calls if call[0] == "request" and call[2] == "turn/start"]))


if __name__ == "__main__":
    unittest.main()
