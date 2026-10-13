import copy
import math
import time

try:
    from native_host_session import ObservationTimeout, SessionError
except ImportError:
    from .native_host_session import ObservationTimeout, SessionError


# Explicit upgrade target retained for compatibility, not a default model.
MODEL = "gpt-6.1-sol"
RETURN_KEYS = frozenset({
    "thread_id",
    "turn_id",
    "generated_text",
    "observations",
    "owned_process_exit",
    "thread_closed_observed",
    "status",
    "runtime_admission",
    "store_admission",
    "backend_effective_model",
    "backend_effective_effort",
    "failure_phase",
    "failure_detail",
})


def _unknown_result():
    return {
        "thread_id": None,
        "turn_id": None,
        "generated_text": "",
        "observations": [],
        "owned_process_exit": None,
        "thread_closed_observed": False,
        "status": "unknown",
        "runtime_admission": False,
        "store_admission": False,
        "backend_effective_model": "unknown",
        "backend_effective_effort": "unknown",
        "failure_phase": None,
        "failure_detail": None,
    }


def _rpc_observation(request_id, result):
    return {
        "id": request_id,
        "result": copy.deepcopy(result),
        "transport_provenance": {
            "source": "NativeSession.request",
            "envelope": "reconstructed",
            "request_id_known": True,
        },
    }


def _nonempty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise SessionError(f"{label} must be a non-empty string")
    return value


def _thread_id(result):
    thread = result.get("thread") if isinstance(result, dict) else None
    value = thread.get("id") if isinstance(thread, dict) else None
    if not isinstance(value, str) or not value:
        raise SessionError("thread/start result did not bind a thread ID")
    return value


def _turn_id(result):
    turn = result.get("turn") if isinstance(result, dict) else None
    value = turn.get("id") if isinstance(turn, dict) else None
    if not isinstance(value, str) or not value:
        raise SessionError("turn/start result did not bind a turn ID")
    return value


def _event_turn_id(event):
    params = event.get("params") if isinstance(event, dict) else None
    if not isinstance(params, dict):
        return None
    direct = params.get("turnId")
    turn = params.get("turn")
    if "turnId" in params:
        if not isinstance(direct, str) or not direct:
            return None
        if isinstance(turn, dict) and "id" in turn and turn["id"] != direct:
            return None
        return direct
    if isinstance(turn, dict):
        value = turn.get("id")
        if isinstance(value, str) and value:
            return value
    return None


def _terminal_status(event):
    params = event.get("params") if isinstance(event, dict) else None
    turn = params.get("turn") if isinstance(params, dict) else None
    status = turn.get("status") if isinstance(turn, dict) else None
    if status is None and isinstance(params, dict):
        status = params.get("status")
    if status in {"completed", "failed", "interrupted"}:
        return status
    if status is not None:
        return None
    if event.get("method") == "turn/completed":
        return "completed"
    return None


def _agent_message_texts_from_item(item):
    if not isinstance(item, dict) or item.get("type") != "agentMessage":
        return []
    texts = []
    text = item.get("text")
    if isinstance(text, str):
        texts.append(text)
    content = item.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                value = part.get("text")
                if isinstance(value, str):
                    texts.append(value)
    message = item.get("message")
    if isinstance(message, dict):
        value = message.get("text")
        if isinstance(value, str):
            texts.append(value)
        nested = message.get("content")
        if isinstance(nested, list):
            for part in nested:
                if isinstance(part, dict):
                    value = part.get("text")
                    if isinstance(value, str):
                        texts.append(value)
    return texts


def _agent_message_items(event):
    params = event.get("params") if isinstance(event, dict) else None
    if not isinstance(params, dict):
        return []
    items = []
    if isinstance(params.get("item"), dict):
        items.append(params["item"])
    if isinstance(params.get("items"), list):
        items.extend(params["items"])
    turn = params.get("turn")
    if isinstance(turn, dict) and isinstance(turn.get("items"), list):
        items.extend(turn["items"])
    return items


def _append_agent_message_texts(event, messages, seen_item_ids):
    for item in _agent_message_items(event):
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            if item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
        messages.extend(_agent_message_texts_from_item(item))


def _valid_event(event, method, thread_id, turn_id=None):
    if not isinstance(event, dict) or "id" in event or event.get("method") != method:
        return False
    params = event.get("params")
    if not isinstance(params, dict) or params.get("threadId") != thread_id:
        return False
    if turn_id is not None and _event_turn_id(event) != turn_id:
        return False
    return True


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ObservationTimeout("Observation timed out; bounded unknown")
    return remaining


def _next_event(session, thread_id, timeout):
    next_event = getattr(session, "next_event", None)
    if not callable(next_event):
        raise SessionError("Native session lacks notification observation")
    return next_event(thread_id, timeout=timeout)


def _next_closed(session, thread_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = _next_event(session, thread_id, _remaining(deadline))
        if not isinstance(event, dict):
            raise SessionError("Host notification must be an object")
        if event.get("method") == "thread/closed":
            if not _valid_event(event, "thread/closed", thread_id):
                raise SessionError("thread/closed notification was not exact")
            if set(event["params"]) != {"threadId"}:
                raise SessionError("thread/closed notification was not exact")
            return event
    raise ObservationTimeout("Observation timed out; bounded unknown")


def run_task(session, thread_params, turn_params, timeout=180, close_timeout=90):
    result = _unknown_result()
    owned_session = session
    phase = "start"
    messages = []
    completed_status = None
    rerouted = False
    seen_item_ids = set()
    thread_request = None
    turn_request = None
    try:
        if not isinstance(thread_params, dict) or not isinstance(turn_params, dict):
            raise SessionError("thread_params and turn_params must be dictionaries")
        thread_request = copy.deepcopy(thread_params)
        turn_request = copy.deepcopy(turn_params)
        # Validate shape only; supported models/efforts belong to the host.
        # Never replace an effort or retry with an alternate model.
        for label, request in (("thread", thread_request), ("turn", turn_request)):
            for key in ("model", "effort"):
                if key in request:
                    _nonempty_string(request[key], f"{label} {key}")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise SessionError("Positive timeout required")
        if isinstance(close_timeout, bool) or not isinstance(close_timeout, (int, float)) or not math.isfinite(close_timeout) or close_timeout <= 0:
            raise SessionError("Positive close timeout required")

        owned_session.start()
        phase = "initialize"
        owned_session.request(0, "initialize", {
            "clientInfo": {"name": "wuji4-native-task-driver", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        }, timeout=timeout)
        owned_session.notify("initialized", {})

        thread_request["ephemeral"] = True
        # Omitted model/effort are left to the host configuration.
        phase = "thread/start"
        thread_result = owned_session.request(1, "thread/start", thread_request, timeout=timeout)
        result["observations"].append(_rpc_observation(1, thread_result))
        if not isinstance(thread_result, dict):
            raise SessionError("thread/start result must be an object")
        declared_model = _nonempty_string(thread_result.get("model"), "thread/start declaration model")
        if "model" in thread_request and declared_model != thread_request["model"]:
            raise SessionError("thread/start declaration model mismatches request")
        result["thread_id"] = _thread_id(thread_result)
        thread_id = result["thread_id"]

        turn_request["threadId"] = thread_id
        # Bind an omitted turn model to the thread declaration, not backend proof.
        # An explicit turn override is preserved. Omitted effort stays omitted.
        turn_request.setdefault("model", declared_model)
        phase = "turn/start"
        turn_result = owned_session.request(2, "turn/start", turn_request, timeout=timeout)
        result["observations"].append(_rpc_observation(2, turn_result))
        response_thread_id = turn_result.get("threadId")
        if response_thread_id is not None and response_thread_id != thread_id:
            raise SessionError("turn/start response threadId mismatches bound thread")
        result["turn_id"] = _turn_id(turn_result)
        turn_id = result["turn_id"]

        deadline = time.monotonic() + float(timeout)
        phase = "turn/observation"
        while completed_status is None:
            event = _next_event(owned_session, thread_id, _remaining(deadline))
            method = event.get("method") if isinstance(event, dict) else None
            if method == "turn/started":
                if _valid_event(event, method, thread_id, turn_id):
                    result["observations"].append(copy.deepcopy(event))
                continue
            if method == "item/completed":
                if _valid_event(event, method, thread_id, turn_id):
                    _append_agent_message_texts(event, messages, seen_item_ids)
                continue
            if method == "model/rerouted":
                if _valid_event(event, method, thread_id, turn_id):
                    result["observations"].append(copy.deepcopy(event))
                    rerouted = True
                continue
            if method == "turn/completed":
                if _valid_event(event, method, thread_id, turn_id):
                    completed_status = _terminal_status(event)
                    if completed_status is not None:
                        result["observations"].append(copy.deepcopy(event))
                        _append_agent_message_texts(event, messages, seen_item_ids)

        result["generated_text"] = "\n".join(messages)
        phase = "thread/unsubscribe"
        owned_session.request(3, "thread/unsubscribe", {"threadId": thread_id}, timeout=timeout)
        phase = "thread/closed"
        closed = _next_closed(owned_session, thread_id, float(close_timeout))
        result["observations"].append(copy.deepcopy(closed))
        result["thread_closed_observed"] = True
        result["status"] = "rerouted" if rerouted else completed_status
    except ObservationTimeout as error:
        result["status"] = "unknown"
        result["failure_phase"] = phase
        result["failure_detail"] = str(error)[:512] or "observation timeout"
    except (SessionError, KeyError, TypeError, ValueError) as error:
        result["status"] = "failed"
        result["failure_phase"] = phase
        result["failure_detail"] = str(error)[:512] or type(error).__name__
    finally:
        try:
            result["owned_process_exit"] = owned_session.close(timeout=close_timeout)
        except Exception:
            result["owned_process_exit"] = {
                "owned_process_exited": "unknown",
                "error": "session close result unknown",
            }
    return result
