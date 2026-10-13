import json
import sys
import time


def write_frame(frame, newline="\n"):
    payload = json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + newline
    sys.stdout.write(payload)
    sys.stdout.flush()


def write_chunked(frame):
    payload = (json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\r\n").encode("utf-8")
    boundaries = (3, 9, len(payload))
    start = 0
    for end in boundaries:
        sys.stdout.buffer.write(payload[start:end])
        sys.stdout.buffer.flush()
        start = end


def write_raw(payload):
    sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.buffer.flush()


def response_for(message, state):
    request_id = message["id"]
    state["received_ids"].append(request_id)
    mode = state["mode"]
    if mode == "timeout" and len(state["received_ids"]) == 1:
        return
    if mode == "duplicate":
        write_raw(f'{{"id":{request_id},"result":{{"ok":true}},"result":{{"ok":false}}}}\n')
        return
    if mode == "duplicate_nested":
        write_raw(f'{{"id":{request_id},"result":{{"value":1,"value":2}}}}\n')
        return
    if mode == "deep_json":
        depth = 10000
        write_raw(f'{{"id":{request_id},"result":{{"value":' + "[" * depth + "0" + "]" * depth + "}}\n")
    invalid_versions = {
        "jsonrpc_1": "1.0",
        "jsonrpc_future": "2.1",
        "jsonrpc_null": None,
        "jsonrpc_number": 2.0,
        "jsonrpc_bool": True,
        "jsonrpc_object": {},
        "jsonrpc_array": [],
    }
    if mode in invalid_versions:
        write_frame({"id": request_id, "jsonrpc": invalid_versions[mode], "result": {"marker": "invalid-version"}})
        return
    invalid_errors = {
        "error_null": None,
        "error_array": [],
        "error_string": "fixture rejection",
        "error_empty": {},
        "error_missing_code": {"message": "fixture rejection"},
        "error_missing_message": {"code": 409},
        "error_bool_code": {"code": True, "message": "fixture rejection"},
        "error_false_code": {"code": False, "message": "fixture rejection"},
        "error_float_code": {"code": 409.0, "message": "fixture rejection"},
        "error_fraction_code": {"code": 409.5, "message": "fixture rejection"},
        "error_string_code": {"code": "409", "message": "fixture rejection"},
        "error_null_code": {"code": None, "message": "fixture rejection"},
        "error_null_message": {"code": 409, "message": None},
        "error_number_message": {"code": 409, "message": 7},
        "error_bool_message": {"code": 409, "message": True},
        "error_array_message": {"code": 409, "message": []},
        "error_object_message": {"code": 409, "message": {}},
    }
    if mode in invalid_errors:
        write_frame({"id": request_id, "error": invalid_errors[mode]})
        return
    if mode == "missing_payload":
        write_frame({"id": request_id})
        return
    if mode == "both_payloads":
        write_frame({"id": request_id, "result": {}, "error": {"code": 409, "message": "fixture rejection"}})
        return
    if mode == "oversize":
        write_frame({"id": request_id, "result": {"value": "x" * 512}})
        return
    if mode == "burst" and len(state["received_ids"]) == 1:
        for index in range(3):
            write_frame({
                "method": "turn/progress",
                "params": {"threadId": "thread-1", "index": index},
            })
    if mode == "notifications" and len(state["received_ids"]) == 1:
        write_frame({
            "method": "turn/completed",
            "params": {"threadId": "thread-1", "marker": "wrong-method"},
        })
        write_frame({
            "method": "turn/started",
            "params": {"threadId": "other-thread", "marker": "wrong-thread"},
        })
        write_frame({
            "method": "turn/started",
            "params": {"threadId": "thread-1", "marker": "right"},
        })
    if mode == "bool_id" and len(state["received_ids"]) == 1:
        write_frame({"id": True, "result": {"marker": "wrong-id-type"}})
    if mode == "wrong_id" and len(state["received_ids"]) == 1:
        write_frame({"id": request_id + 1000, "result": {"marker": "wrong-id"}})
    if mode in ("bidirectional", "bidirectional_result", "bidirectional_error", "bidirectional_null_method", "bidirectional_empty_method") and len(state["received_ids"]) == 1:
        server_request = {"id": request_id, "method": "server/request", "params": {}}
        if mode == "bidirectional_error":
            server_request["error"] = {"code": 409, "message": "not a client response"}
        elif mode != "bidirectional":
            server_request["result"] = {"marker": "not a client response"}
        if mode == "bidirectional_null_method":
            server_request["method"] = None
        elif mode == "bidirectional_empty_method":
            server_request["method"] = ""
        write_frame(server_request)
    result = {
        "ok": True,
        "method": message.get("method"),
        "params": message.get("params"),
        "receivedIds": list(state["received_ids"]),
        "receivedNotifications": list(state["received_notifications"]),
    }
    response = {"id": request_id, "result": result}
    if mode in ("jsonrpc_2", "rpc_error_jsonrpc_2"):
        response["jsonrpc"] = "2.0"
    if mode == "chunked":
        write_chunked(response)
    elif mode in ("rpc_error", "rpc_error_jsonrpc_2") and len(state["received_ids"]) == 1:
        del response["result"]
        response["error"] = {"code": 409, "message": "fixture rejection"}
        if mode == "rpc_error_jsonrpc_2":
            response["error"] = {"code": -32601, "message": "", "data": {"detail": ["fixture"]}}
        write_frame(response)
    else:
        write_frame(response)


def run(mode):
    state = {"mode": mode, "received_ids": [], "received_notifications": []}
    for raw_line in sys.stdin.buffer:
        try:
            message = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, ValueError):
            return 2
        if not isinstance(message, dict):
            return 3
        if "id" in message:
            response_for(message, state)
            if mode == "exit_after_response":
                return 0
        else:
            state["received_notifications"].append(message)
    if mode == "linger":
        time.sleep(30)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) == 2 else "basic"))
