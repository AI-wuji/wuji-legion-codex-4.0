"""One-shot branch execution through a caller-owned native host bridge.

invoke_role(role_kind, contract) -> dict must be thread safe and bounded, and own
host timeouts/closure. role_kind is leader or expert; contract.phase is plan,
execute or aggregate. Plan returns
{status: completed, tasks: [...]}; execution/aggregation return receipts with
status, producer_task_id, artifacts [{path, sha256}], scope (path or path list),
acceptance_passed, acceptance_ids and revision. The bridge may attach
host_evidence; this module preserves it without treating it as formal admission.

Paths are absolute or relative to PROJECT_ROOT. Deliverables are concrete file
paths, not prose labels. A read-only task can return existing declared inputs
as its deliverables with write_roots=[] and scope=[]. Expert payloads contain
only their own contract, inherited constraints, revision and accepted upstream
receipts. Path checks validate contracts/receipts; the host owns OS permissions.
No host is installed, model selected, thread fabricated, or database created.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from copy import deepcopy
import hashlib
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TASK_FIELDS = ("task_id", "role_id", "assignment", "inputs", "deliverables",
                "acceptance_ids", "write_roots", "depends_on")


class ContractError(ValueError):
    """A bounded task or artifact contract was not satisfied."""


def _text(value, label, limit=4096):
    if (not isinstance(value, str) or not value.strip()
            or len(value.encode("utf-8")) > limit
            or any(ord(c) < 32 for c in value)):
        raise ContractError(f"{label}: nonempty bounded text required")
    return value


def _strings(value, label, *, nonempty=False):
    if not isinstance(value, list) or len(value) > 32 or (nonempty and not value):
        raise ContractError(f"{label}: bounded string list required")
    result = [_text(v, label) for v in value]
    if len(set(result)) != len(result):
        raise ContractError(f"{label}: duplicate values")
    return result


def _path(value):
    return (PROJECT_ROOT / _text(value, "path")).resolve()


def _inside(path, roots):
    return any(path == root or path.is_relative_to(root) for root in roots)


def _roots(values):
    return [_path(v) for v in values]


def _conflict(left, right):
    return any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
               for a in _roots(left) for b in _roots(right))


def _work_contract(work_item):
    if not isinstance(work_item, dict):
        raise ContractError("work_item: object required")
    task_id = _text(work_item.get("task_id", work_item.get("subtask_id")), "task_id", 128)
    return {
        "task_id": task_id,
        "goal": _text(work_item.get("goal"), "goal"),
        "inputs": _strings(work_item.get("inputs"), "inputs"),
        "deliverables": _strings(work_item.get("deliverables"), "deliverables", nonempty=True),
        "acceptance_ids": _strings(work_item.get("acceptance_ids"), "acceptance_ids", nonempty=True),
        "write_roots": _strings(work_item.get("write_roots"), "write_roots"),
        "constraints": _strings(work_item.get("constraints", []), "constraints"),
        "forbidden_actions": _strings(work_item.get("forbidden_actions", []),
                                      "forbidden_actions"),
    }


def _validate_plan(raw_tasks, work, candidates):
    if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= 16:
        raise ContractError("plan.tasks: 1..16 local tasks required")
    tasks = {}
    parent_roots = _roots(work["write_roots"])
    for raw in raw_tasks:
        if not isinstance(raw, dict) or any(field not in raw for field in _TASK_FIELDS):
            raise ContractError("plan task: all local task fields required")
        task = {"task_id": _text(raw["task_id"], "task_id", 128),
                "role_id": _text(raw["role_id"], "role_id", 256),
                "assignment": _text(raw["assignment"], "assignment")}
        for key in _TASK_FIELDS[3:]:
            task[key] = _strings(raw[key], key, nonempty=key in ("deliverables", "acceptance_ids"))
        task["forbidden_actions"] = _strings(
            raw.get("forbidden_actions", work["forbidden_actions"]), "forbidden_actions")
        if not set(work["forbidden_actions"]).issubset(task["forbidden_actions"]):
            raise ContractError("plan: forbidden_actions must inherit branch permissions")
        if task["task_id"] in tasks or task["task_id"] == work["task_id"]:
            raise ContractError("plan: duplicate or parent task_id")
        if task["role_id"] not in candidates:
            raise ContractError("plan: unknown or unselected role_id")
        if not set(task["inputs"]).issubset(work["inputs"]):
            raise ContractError("plan: inputs exceed declared branch inputs")
        if any(not _inside(root, parent_roots) for root in _roots(task["write_roots"])):
            raise ContractError("plan: write_roots exceed branch scope")
        allowed = _roots(task["write_roots"] or task["inputs"])
        if any(not _inside(_path(path), allowed) for path in task["deliverables"]):
            raise ContractError("plan: deliverables exceed task scope")
        tasks[task["task_id"]] = task
    seen = set()
    pending = set(tasks)
    for task in tasks.values():
        if (task["task_id"] in task["depends_on"]
                or not set(task["depends_on"]).issubset(tasks)):
            raise ContractError("plan: unknown or self dependency")
    while pending:
        ready = {key for key in pending if set(tasks[key]["depends_on"]).issubset(seen)}
        if not ready:
            raise ContractError("plan: dependency cycle")
        seen.update(ready)
        pending.difference_update(ready)
    return tasks


def _validate_receipt(task, raw, revision):
    if not isinstance(raw, dict):
        raise ContractError("receipt: object required")
    if raw.get("status") != "completed":
        raise ContractError("receipt: producer did not complete")
    if raw.get("producer_task_id") != task["task_id"]:
        raise ContractError("receipt: exact producer_task_id required")
    if type(raw.get("revision")) is not int or raw["revision"] != revision:
        raise ContractError("receipt: exact current revision required")
    if raw.get("acceptance_passed") is not True:
        raise ContractError("receipt: acceptance did not pass")
    accepted = _strings(raw.get("acceptance_ids"), "receipt.acceptance_ids", nonempty=True)
    if not set(task["acceptance_ids"]).issubset(accepted):
        raise ContractError("receipt: required acceptance_ids missing")
    scope = raw.get("scope")
    if isinstance(scope, str):
        scope = [scope]
    scope = _strings(scope, "receipt.scope")
    permitted = _roots(task["write_roots"] or task["inputs"])
    scope_roots = _roots(scope)
    if any(not _inside(root, permitted) for root in scope_roots):
        raise ContractError("receipt: scope exceeds task scope")
    if task["write_roots"] and not scope_roots:
        raise ContractError("receipt: writable producer requires scope")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
        raise ContractError("receipt: nonempty bounded artifacts required")
    checked = []
    paths = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ContractError("receipt: artifact object required")
        path = _path(artifact.get("path"))
        sha = artifact.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ContractError("receipt: sha256 required")
        if not _inside(path, scope_roots or permitted) or not _inside(path, permitted):
            raise ContractError("receipt: artifact exceeds scope")
        if path in paths or not path.is_file():
            raise ContractError("receipt: duplicate or missing artifact")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != sha:
            raise ContractError("receipt: current artifact hash mismatch")
        paths.add(path)
        checked.append({"path": str(path), "sha256": sha})
    if not set(_roots(task["deliverables"])).issubset(paths):
        raise ContractError("receipt: declared deliverable missing")
    result = {"status": "completed", "producer_task_id": task["task_id"],
              "artifacts": checked, "scope": [str(p) for p in scope_roots],
              "acceptance_passed": True, "acceptance_ids": accepted, "revision": revision}
    return result


def make_native_role_invoker(session_factory, request_builder, *, timeout=180, close_timeout=90):
    """Adapt the existing native_task_driver to the one-shot role bridge.

    The caller owns the NativeSession command, model/effort request and prompt
    construction. This adapter only performs one bounded role turn, parses the
    role's JSON receipt, and preserves host observation fields. It never starts
    a resident service, selects a fallback model, or turns a fixture result
    into formal role admission.
    """
    if not callable(session_factory) or not callable(request_builder):
        raise ContractError("native role bridge requires session_factory and request_builder")

    def invoke(role_kind, contract):
        if role_kind not in {"leader", "expert"} or not isinstance(contract, dict):
            return {"status": "failed", "failure": "invalid native role contract"}
        try:
            from native_task_driver import run_task
            request = request_builder(role_kind, deepcopy(contract))
            if not isinstance(request, dict) or not isinstance(request.get("thread"), dict) or not isinstance(request.get("turn"), dict):
                return {"status": "failed", "failure": "request_builder must return thread and turn objects"}
            session = session_factory(role_kind, deepcopy(contract))
            observed = run_task(session, request["thread"], request["turn"],
                               timeout=timeout, close_timeout=close_timeout)
            host_evidence = {"native": True, "driver_status": observed.get("status"),
                             "thread_id": observed.get("thread_id"), "turn_id": observed.get("turn_id"),
                             "thread_closed_observed": observed.get("thread_closed_observed"),
                             "backend_effective_model": observed.get("backend_effective_model", "unknown"),
                             "backend_effective_effort": observed.get("backend_effective_effort", "unknown")}
            if observed.get("status") != "completed":
                return {"status": observed.get("status", "unknown"), "host_evidence": host_evidence,
                        "failure": observed.get("failure_detail") or observed.get("failure_phase")}
            generated = observed.get("generated_text")
            if not isinstance(generated, str) or not generated.strip():
                return {"status": "failed", "host_evidence": host_evidence,
                        "failure": "native role returned no JSON receipt"}
            import json
            try:
                payload = json.loads(generated)
            except (TypeError, ValueError) as error:
                return {"status": "failed", "host_evidence": host_evidence,
                        "failure": f"native role returned malformed JSON: {str(error)[:256]}"}
            if not isinstance(payload, dict):
                return {"status": "failed", "host_evidence": host_evidence,
                        "failure": "native role receipt must be an object"}
            payload["host_evidence"] = host_evidence
            return payload
        except Exception as error:
            return {"status": "unknown", "failure": f"{type(error).__name__}: {str(error)[:512]}"}

    return invoke


def execute_branch(branch, work_item, invoke_role, parallel_cap=2, max_rework=1, execution_slots=None):
    """Execute one selected branch using actual caller-supplied role callbacks.

    This is finite, in-process execution. Completed receipts are re-read before
    downstream dispatch and aggregation. Invalid receipts ask their producer
    for bounded rework; only affected descendants are invalidated. An exception,
    missing/unsupported callback status or unknown result has unknown submission
    semantics, stops new dispatch and is never retried. Existing concurrent calls
    are collected; the bridge is responsible for observing host termination.
    """
    evidence, failures, reworks = [], [], []
    receipts, attempts, states, tasks = {}, {}, {}, {}
    work = None
    leader_receipt = None

    def finish(status):
        return {"status": status, "producer_task_id": work["task_id"] if work else None,
                "receipt": leader_receipt, "expert_receipts": deepcopy(receipts),
                "task_states": dict(states), "execution_evidence": deepcopy(evidence),
                "failures": deepcopy(failures), "rework_events": deepcopy(reworks),
                "callback_invocations": len(evidence), "runtime_admission": False,
                "formal_admission": False, "professional_effectiveness": "not_claimed",
                "execution_basis": "callback_returns_and_current_file_hash_checks"}

    def invoke(role_kind, contract):
        if role_kind not in {"leader", "expert"} or not isinstance(contract, dict):
            return {"status": "failed", "failure": "invalid bridge invocation contract"}
        try:
            if execution_slots is not None:
                execution_slots.acquire()
            result = invoke_role(role_kind, deepcopy(contract))
            return deepcopy(result)
        except Exception as error:
            return {"status": "unknown", "failure": f"{type(error).__name__}: {str(error)[:512]}"}
        finally:
            if execution_slots is not None:
                execution_slots.release()

    def observe(phase, role_id, task_id, revision, raw):
        # Host evidence is retained as bridge-supplied observation, not authority.
        evidence.append({"phase": phase, "role_id": role_id, "task_id": task_id,
                         "revision": revision, "callback_result": deepcopy(raw)})
        return not isinstance(raw, dict) or raw.get("status") not in ("completed", "failed")

    def reject(code, task_id, reason):
        failures.append({"decision": code, "producer_task_id": task_id, "reason": str(reason)[:512]})

    def descendants(key):
        found = set()
        changed = True
        while changed:
            changed = False
            for other, task in tasks.items():
                if other != key and other not in found and set(task["depends_on"]) & ({key} | found):
                    found.add(other)
                    changed = True
        return found

    def rework(key, reason):
        reject("rework_upstream", key, reason)
        receipts.pop(key, None)
        state = "pending" if attempts[key] < 1 + max_rework else "rework_exhausted"
        states[key] = state
        for dependent in descendants(key):
            receipts.pop(dependent, None)
            if states[dependent] != "unknown":
                states[dependent] = "pending" if state == "pending" else "blocked"
        reworks.append({"producer_task_id": key, "revision": attempts[key],
                        "decision": state, "reason": str(reason)[:512]})

    try:
        if type(parallel_cap) is not int or not 1 <= parallel_cap <= 3:
            raise ContractError("parallel_cap: integer in 1..3 required")
        if type(max_rework) is not int or not 0 <= max_rework <= 3:
            raise ContractError("max_rework: integer in 0..3 required")
        if not callable(invoke_role):
            raise ContractError("invoke_role: caller-owned bridge required")
        if execution_slots is not None and not hasattr(execution_slots, "acquire"):
            raise ContractError("execution_slots: semaphore-like shared budget required")
        work = _work_contract(work_item)
        if not isinstance(branch, dict) or branch.get("state") == "selection_gap":
            raise ContractError("branch: selected branch required")
        if "subtask_id" in branch and branch["subtask_id"] != work_item.get("subtask_id", work["task_id"]):
            raise ContractError("branch: subtask identity mismatch")
        leader = branch.get("leader_recipe")
        if not isinstance(leader, dict):
            raise ContractError("branch: selected leader required")
        leader_id = _text(leader.get("id"), "leader.id", 256)
        references = branch.get("selected_expert_refs")
        if not isinstance(references, list) or not 1 <= len(references) <= 16:
            raise ContractError("branch: selected candidates required")
        candidates = [_text(ref.get("role_id"), "candidate.role_id", 256)
                      for ref in references if isinstance(ref, dict)]
        if len(candidates) != len(references):
            raise ContractError("branch: malformed candidates")
        context = branch.get("required_context", {})
        if "write_roots" in context and any(not _inside(root, _roots(context["write_roots"]))
                                             for root in _roots(work["write_roots"])):
            raise ContractError("work_item: exceeds branch write_roots")
        if any(not _inside(_path(path), _roots(work["write_roots"] or work["inputs"]))
               for path in work["deliverables"]):
            raise ContractError("work_item: deliverables exceed authorized scope")
        raw = invoke("leader", {"phase": "plan", "role_id": leader_id,
                                "work_item": work, "candidates": deepcopy(references),
                                "forbidden_actions": list(work["forbidden_actions"]),
                                "revision": 1})
        if observe("plan", leader_id, work["task_id"], 1, raw):
            reject("unknown", work["task_id"], "leader plan submission/completion unknown")
            return finish("unknown")
        if raw["status"] != "completed":
            raise ContractError("leader plan failed")
        tasks = _validate_plan(raw.get("tasks"), work, set(candidates))
        attempts = {key: 0 for key in tasks}
        states = {key: "pending" for key in tasks}
    except (ContractError, OSError, TypeError, KeyError, ValueError) as error:
        reject("invalid_contract", work["task_id"] if work else None, error)
        return finish("failed")

    aggregate_attempts = 0
    with ThreadPoolExecutor(max_workers=parallel_cap) as pool:
        while True:
            # Current-file checks are the input gate, not an acceptance boolean alone.
            invalid = False
            for key in list(receipts):
                if key not in receipts:
                    continue
                try:
                    _validate_receipt(tasks[key], receipts[key], attempts[key])
                except (ContractError, OSError) as error:
                    rework(key, error)
                    invalid = True
            ready = [key for key in tasks if states[key] == "pending"
                     and all(states[dep] == "accepted" for dep in tasks[key]["depends_on"])]
            group = []
            for key in ready:
                if attempts[key] >= 1 + max_rework:
                    states[key] = "rework_exhausted"
                    for dependent in descendants(key):
                        states[dependent] = "blocked"
                    reject("rework_exhausted", key, "producer invocation limit reached")
                    continue
                if all(not _conflict(tasks[key]["write_roots"], tasks[other]["write_roots"])
                       for other in group):
                    group.append(key)
                if len(group) == parallel_cap:
                    break
            if group:
                futures = {}
                for key in group:
                    attempts[key] += 1
                    states[key] = "running"
                    payload = {"phase": "execute", "role_id": tasks[key]["role_id"],
                               "task": tasks[key], "revision": attempts[key],
                               "constraints": work["constraints"],
                               "forbidden_actions": list(tasks[key]["forbidden_actions"]),
                               "upstream_receipts": [receipts[dep] for dep in tasks[key]["depends_on"]]}
                    if attempts[key] > 1:
                        payload["rework_reason"] = next((event["reason"] for event in reversed(reworks)
                                                        if event["producer_task_id"] == key),
                                                       "accepted upstream revision changed")
                    futures[key] = pool.submit(invoke, "expert", payload)
                unknown = False
                for key, future in futures.items():
                    raw = future.result()
                    if observe("execute", tasks[key]["role_id"], key, attempts[key], raw):
                        states[key] = "unknown"
                        reject("unknown", key, "expert submission/completion unknown; no retry")
                        unknown = True
                        continue
                    try:
                        receipts[key] = _validate_receipt(tasks[key], raw, attempts[key])
                        states[key] = "accepted"
                    except (ContractError, OSError) as error:
                        rework(key, error)
                if unknown:
                    return finish("unknown")
                continue
            if any(state != "accepted" for state in states.values()):
                reject("blocked", work["task_id"], "required experts have not all been accepted")
                return finish("failed")
            if invalid:
                continue
            if aggregate_attempts >= 1 + max_rework:
                reject("rework_exhausted", work["task_id"], "aggregate invocation limit reached")
                return finish("failed")
            aggregate_attempts += 1
            accepted_expert_receipts = []
            try:
                for key in tasks:
                    accepted_expert_receipts.append(
                        _validate_receipt(tasks[key], receipts[key], attempts[key]))
            except (ContractError, OSError) as error:
                reject("rework_upstream", work["task_id"], error)
                return finish("failed")
            raw = invoke("leader", {"phase": "aggregate", "role_id": leader_id,
                                    "work_item": work, "revision": aggregate_attempts,
                                    "forbidden_actions": list(work["forbidden_actions"]),
                                    "expert_receipts": accepted_expert_receipts})
            if observe("aggregate", leader_id, work["task_id"], aggregate_attempts, raw):
                reject("unknown", work["task_id"], "leader aggregate unknown; no retry")
                return finish("unknown")
            try:
                checked = _validate_receipt(work, raw, aggregate_attempts)
                # Aggregation must not silently corrupt an already accepted input.
                for key in list(receipts):
                    _validate_receipt(tasks[key], receipts[key], attempts[key])
                leader_receipt = checked
                return finish("completed")
            except (ContractError, OSError) as error:
                reject("rework_upstream", work["task_id"], error)
                reworks.append({"producer_task_id": work["task_id"], "revision": aggregate_attempts,
                                "decision": "retry_aggregate", "reason": str(error)[:512]})
