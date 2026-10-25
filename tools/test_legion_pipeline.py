"""Contract/execution fixtures, NOT native-host or professional effectiveness tests.

Callbacks are controlled Python fixtures; artifacts are real temporary files.
Barriers prove overlapping callback execution, not parallel native model turns.
"""

from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest

from legion_pipeline import execute_branch


class LegionPipelineFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="legion-pipeline-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.txt"
        self.source.write_text("declared source", encoding="utf-8")
        self.work = {"task_id": "branch", "goal": "bounded fixture work",
                     "inputs": [str(self.source)], "deliverables": [str(self.root / "final.txt")],
                     "acceptance_ids": ["final-checked"], "write_roots": [str(self.root)],
                     "constraints": ["fixture-only"],
                     "forbidden_actions": ["modify-codex-config", "publish-external"]}
        self.branch = {"subtask_id": "branch", "state": "prepared_not_executed",
                       "leader_recipe": {"id": "leader/software"},
                       "selected_expert_refs": [{"role_id": "expert/one"}, {"role_id": "expert/two"}],
                       "required_context": {"write_roots": [str(self.root)]}}
        self.tasks = [self.task("a"), self.task("b", role="expert/two")]
        self.calls = []
        self.lock = threading.Lock()

    def task(self, key, *, role="expert/one", dependencies=None, roots=None):
        output_dir = self.root / key
        return {"task_id": key, "role_id": role, "assignment": f"local assignment {key}",
                "inputs": [str(self.source)], "deliverables": [str(output_dir / "artifact.txt")],
                "acceptance_ids": [f"checked-{key}"],
                "write_roots": roots if roots is not None else [str(output_dir)],
                "depends_on": dependencies or []}

    def receipt(self, task, revision, *, write=True):
        artifacts = []
        for name in task["deliverables"]:
            path = Path(name)
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{task['task_id']} revision {revision}", encoding="utf-8")
            artifacts.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return {"status": "completed", "producer_task_id": task["task_id"], "artifacts": artifacts,
                "scope": list(task["write_roots"]), "acceptance_passed": True,
                "acceptance_ids": list(task["acceptance_ids"]), "revision": revision,
                "host_evidence": {"kind": "python_fixture_not_native"}}

    def bridge(self, role_kind, contract):
        phase = contract["phase"]
        role_id = contract.get("role_id")
        payload = contract
        self.assertEqual("leader" if phase in ("plan", "aggregate") else "expert", role_kind)
        with self.lock:
            self.calls.append((phase, role_id, deepcopy(payload)))
        if phase == "plan":
            return {"status": "completed", "tasks": deepcopy(self.tasks),
                    "host_evidence": {"kind": "python_fixture_not_native"}}
        if phase == "execute":
            return self.receipt(payload["task"], payload["revision"],
                                write=bool(payload["task"]["write_roots"]))
        if phase == "aggregate":
            return self.receipt(payload["work_item"], payload["revision"],
                                write=bool(payload["work_item"]["write_roots"]))
        self.fail(f"unexpected phase: {phase}")

    def run_branch(self, bridge=None, **limits):
        return execute_branch(self.branch, self.work, bridge or self.bridge, **limits)

    def counts(self):
        return Counter(payload["task"]["task_id"] for phase, _, payload in self.calls if phase == "execute")

    def test_plan_execute_aggregate_calls_and_current_artifact_evidence(self):
        result = self.run_branch()
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual(["plan", "execute", "execute", "aggregate"], [call[0] for call in self.calls])
        self.assertEqual("leader/software", self.calls[0][1])
        self.assertEqual("leader/software", self.calls[-1][1])
        self.assertEqual(4, result["callback_invocations"])
        self.assertFalse(result["runtime_admission"])
        self.assertFalse(result["formal_admission"])
        self.assertEqual("not_claimed", result["professional_effectiveness"])
        self.assertTrue(all(event["callback_result"]["host_evidence"]["kind"] == "python_fixture_not_native"
                            for event in result["execution_evidence"]))
        artifact = result["receipt"]["artifacts"][0]
        self.assertEqual(hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest(), artifact["sha256"])

    def test_barrier_proves_actual_callback_overlap_and_dependency_wait(self):
        self.tasks.append(self.task("c", dependencies=["a", "b"]))
        barrier = threading.Barrier(2)
        finished = set()
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            phase, payload = phase, payload
            if phase == "execute":
                key = payload["task"]["task_id"]
                if key in ("a", "b"):
                    barrier.wait(timeout=5)
                    result = self.bridge(role_kind, contract)
                    with self.lock:
                        finished.add(key)
                    return result
                self.assertEqual({"a", "b"}, finished)
                self.assertEqual({"a", "b"}, {r["producer_task_id"] for r in payload["upstream_receipts"]})
            return self.bridge(role_kind, contract)
        result = self.run_branch(bridge, parallel_cap=2)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual(Counter(a=1, b=1, c=1), self.counts())

    def test_expert_payload_is_local_and_callback_mutation_cannot_change_other_tasks(self):
        self.tasks[1]["depends_on"] = ["a"]
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            if phase == "execute":
                payload = payload
                self.assertEqual({"phase", "role_id", "task", "revision", "constraints",
                                  "forbidden_actions", "upstream_receipts"}, set(payload))
                self.assertEqual(set(self.tasks[0]) | {"forbidden_actions"}, set(payload["task"]))
                self.assertNotIn("tasks", payload)
                self.assertNotIn("candidates", payload)
                self.assertNotIn("leader_recipe", payload)
                self.assertEqual(self.work["forbidden_actions"], payload["forbidden_actions"])
                self.assertEqual(self.work["forbidden_actions"], payload["task"]["forbidden_actions"])
                if payload["task"]["task_id"] == "a":
                    self.assertEqual([], payload["upstream_receipts"])
                else:
                    self.assertEqual(["a"], [r["producer_task_id"] for r in payload["upstream_receipts"]])
                result = self.bridge(role_kind, contract)
                payload["task"]["write_roots"].append(str(self.root.parent))
                return result
            return self.bridge(role_kind, contract)
        result = self.run_branch(bridge)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertNotIn(str(self.root.parent), self.tasks[0]["write_roots"])


    def test_plan_cannot_weaken_inherited_forbidden_actions(self):
        def bridge(role_kind, contract):
            if contract["phase"] == "plan":
                result = self.bridge(role_kind, contract)
                for task in result["tasks"]:
                    task["forbidden_actions"] = ["modify-codex-config"]
                return result
            return self.bridge(role_kind, contract)
        result = self.run_branch(bridge)
        self.assertEqual("failed", result["status"])
        self.assertEqual(["plan"], [call[0] for call in self.calls])
        self.assertIn("forbidden_actions", result["failures"][0]["reason"])

    def test_same_selected_role_can_run_multiple_independent_tasks(self):
        self.tasks = [self.task("a", role="expert/one"), self.task("b", role="expert/one")]
        result = self.run_branch()
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual(Counter(a=1, b=1), self.counts())
        self.assertEqual({"expert/one"}, {role for phase, role, _ in self.calls if phase == "execute"})

    def test_forbidden_actions_are_inherited_by_plan_experts_and_aggregate(self):
        result = self.run_branch()
        self.assertEqual("completed", result["status"], result["failures"])
        for phase, _, contract in self.calls:
            self.assertEqual(self.work["forbidden_actions"], contract["forbidden_actions"])
        for _, _, contract in self.calls:
            if contract["phase"] == "execute":
                self.assertEqual(self.work["forbidden_actions"],
                                 contract["task"]["forbidden_actions"])

    def test_aggregate_receives_only_normalized_accepted_receipts(self):
        received = []
        def bridge(role_kind, contract):
            if contract["phase"] == "aggregate":
                received.extend(deepcopy(contract["expert_receipts"]))
                self.assertTrue(all(item["status"] == "completed" and
                                    item["acceptance_passed"] is True and
                                    item["producer_task_id"] in {"a", "b"}
                                    for item in item_list(contract["expert_receipts"])))
            return self.bridge(role_kind, contract)
        def item_list(items):
            return items
        result = self.run_branch(bridge)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual({"a", "b"}, {item["producer_task_id"] for item in received})

    def test_bad_hash_reworks_only_producer_and_downstream_waits(self):
        self.tasks.append(self.task("c", dependencies=["a"]))
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            result = self.bridge(role_kind, contract)
            if phase == "execute" and payload["task"]["task_id"] == "a":
                if payload["revision"] == 1:
                    result["artifacts"][0]["sha256"] = "0" * 64
            if phase == "execute" and payload["task"]["task_id"] == "c":
                self.assertEqual(2, payload["upstream_receipts"][0]["revision"])
            return result
        result = self.run_branch(bridge)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual(Counter(a=2, b=1, c=1), self.counts())
        self.assertEqual("rework_upstream", result["failures"][0]["decision"])
        self.assertEqual("a", result["rework_events"][0]["producer_task_id"])

    def test_current_upstream_file_change_is_rechecked_before_dispatch(self):
        self.tasks = [self.task("a"), self.task("b"), self.task("c", dependencies=["a", "b"])]
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            result = self.bridge(role_kind, contract)
            if phase == "execute" and payload["task"]["task_id"] == "b":
                Path(self.tasks[0]["deliverables"][0]).write_text("changed after receipt", encoding="utf-8")
            return result
        result = self.run_branch(bridge, parallel_cap=1)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual(Counter(a=2, b=1, c=1), self.counts())
        self.assertEqual(2, result["expert_receipts"]["a"]["revision"])

    def test_rework_limit_blocks_only_descendants_and_finishes_independent_expert(self):
        self.tasks.append(self.task("c", dependencies=["a"]))
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            result = self.bridge(role_kind, contract)
            if phase == "execute" and payload["task"]["task_id"] == "a":
                result["acceptance_passed"] = False
            return result
        result = self.run_branch(bridge, max_rework=1)
        self.assertEqual("failed", result["status"])
        self.assertEqual(Counter(a=2, b=1), self.counts())
        self.assertEqual("rework_exhausted", result["task_states"]["a"])
        self.assertEqual("blocked", result["task_states"]["c"])
        self.assertEqual("accepted", result["task_states"]["b"])
        self.assertNotIn("aggregate", [call[0] for call in self.calls])

    def test_unknown_and_callback_exception_never_blindly_retry_or_aggregate(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                self.calls.clear()
                def bridge(role_kind, contract):
                    phase, payload = contract["phase"], contract
                    if phase == "execute":
                        self.bridge(role_kind, contract)
                        if raises:
                            raise RuntimeError("host submission state unknown")
                        return {"status": "unknown"}
                    return self.bridge(role_kind, contract)
                result = self.run_branch(bridge, parallel_cap=1, max_rework=3)
                self.assertEqual("unknown", result["status"])
                self.assertEqual(Counter(a=1), self.counts())
                self.assertEqual("pending", result["task_states"]["b"])
                self.assertNotIn("aggregate", [call[0] for call in self.calls])

    def test_missing_or_running_status_is_unknown_not_rework(self):
        for value in ({}, {"status": "running"}, None):
            with self.subTest(value=value):
                def bridge(role_kind, contract):
                    phase, payload = contract["phase"], contract
                    if phase == "execute":
                        return value
                    return self.bridge(role_kind, contract)
                result = self.run_branch(bridge, parallel_cap=1)
                self.assertEqual("unknown", result["status"])
                self.assertEqual(2, result["callback_invocations"])
                self.assertEqual([], result["rework_events"])

    def test_parallel_cap_one_serializes_actual_callbacks(self):
        result = self.run_branch(parallel_cap=1)
        self.assertEqual("completed", result["status"])
        self.assertEqual(["a", "b"], [p["task"]["task_id"] for phase, _, p in self.calls if phase == "execute"])

    def test_conflicting_canonical_write_scopes_never_overlap(self):
        shared = self.root / "shared"
        self.tasks[0]["write_roots"] = [str(shared)]
        self.tasks[0]["deliverables"] = [str(shared / "a.txt")]
        self.tasks[1]["write_roots"] = [str(shared / "unused" / "..")]
        self.tasks[1]["deliverables"] = [str(shared / "b.txt")]
        active, peak = 0, 0
        intervals = []
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            nonlocal active, peak
            if phase != "execute":
                return self.bridge(role_kind, contract)
            key = payload["task"]["task_id"]
            with self.lock:
                active += 1
                peak = max(peak, active)
                intervals.append((key, "start"))
            result = self.bridge(role_kind, contract)
            with self.lock:
                intervals.append((key, "end"))
                active -= 1
            return result
        result = self.run_branch(bridge, parallel_cap=2)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual(1, peak)
        self.assertEqual([("a", "start"), ("a", "end"), ("b", "start"), ("b", "end")], intervals)

    def test_unknown_role_escape_cycle_and_missing_dependency_rejected_before_experts(self):
        original = deepcopy(self.tasks)
        variants = []
        changed = deepcopy(original)
        changed[0]["role_id"] = "expert/not-selected"
        variants.append(changed)
        changed = deepcopy(original)
        changed[0]["write_roots"] = [str(self.root.parent)]
        variants.append(changed)
        changed = deepcopy(original)
        changed[0]["depends_on"] = ["b"]
        changed[1]["depends_on"] = ["a"]
        variants.append(changed)
        changed = deepcopy(original)
        changed[0]["depends_on"] = ["missing"]
        variants.append(changed)
        changed = deepcopy(original)
        changed[0]["inputs"] = ["not-declared"]
        variants.append(changed)
        changed = deepcopy(original)
        changed[0]["deliverables"] = [str(self.root.parent / "escape.txt")]
        variants.append(changed)
        for tasks in variants:
            with self.subTest(tasks=tasks):
                self.tasks, self.calls = tasks, []
                result = self.run_branch()
                self.assertEqual("failed", result["status"])
                self.assertEqual(["plan"], [call[0] for call in self.calls])

    def test_all_task_fields_are_required_and_typed(self):
        original = deepcopy(self.tasks)
        for field in original[0]:
            with self.subTest(field=field):
                self.tasks = deepcopy(original)
                del self.tasks[0][field]
                result = self.run_branch()
                self.assertEqual("failed", result["status"])
        for field in ("inputs", "deliverables", "acceptance_ids", "write_roots", "depends_on"):
            with self.subTest(field=field):
                self.tasks = deepcopy(original)
                self.tasks[0][field] = "not-a-list"
                self.assertEqual("failed", self.run_branch()["status"])

    def test_empty_and_duplicate_task_ids_and_self_dependency_rejected(self):
        original = deepcopy(self.tasks)
        for key in ("", "a", "branch"):
            self.tasks = deepcopy(original)
            self.tasks[1]["task_id"] = key
            self.assertEqual("failed", self.run_branch()["status"])
        self.tasks = deepcopy(original)
        self.tasks[0]["depends_on"] = ["a"]
        self.assertEqual("failed", self.run_branch()["status"])

    def test_pseudo_receipts_wrong_producer_scope_hash_revision_and_acceptance_rejected(self):
        variants = [lambda r: r.update(producer_task_id="someone-else"),
                    lambda r: r.update(scope=[str(self.root.parent)]),
                    lambda r: r["artifacts"][0].update(sha256="0" * 64),
                    lambda r: r.update(revision=True),
                    lambda r: r.update(revision=99),
                    lambda r: r.update(acceptance_ids=["wrong-check"]),
                    lambda r: r.update(acceptance_passed=1),
                    lambda r: r.update(artifacts=[]),
                    lambda r: r["artifacts"][0].update(path=str(self.root / "missing.txt"))]
        for mutate in variants:
            with self.subTest(mutate=mutate):
                self.calls = []
                def bridge(role_kind, contract):
                    phase, payload = contract["phase"], contract
                    result = self.bridge(role_kind, contract)
                    if phase == "execute":
                        mutate(result)
                    return result
                result = self.run_branch(bridge, max_rework=0)
                self.assertEqual("failed", result["status"])
                self.assertTrue(any(f["decision"] == "rework_upstream" for f in result["failures"]))
                self.assertNotIn("aggregate", [call[0] for call in self.calls])

    def test_real_valid_hash_cannot_legitimize_out_of_scope_artifact(self):
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            result = self.bridge(role_kind, contract)
            if phase == "execute":
                result["artifacts"] = [{"path": str(self.source),
                                        "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}]
            return result
        self.assertEqual("failed", self.run_branch(bridge, max_rework=0)["status"])

    def test_read_only_branch_and_expert_allow_empty_write_roots_and_scope(self):
        self.work["write_roots"] = []
        self.work["deliverables"] = [str(self.source)]
        self.branch["required_context"]["write_roots"] = []
        self.tasks = [self.task("a", roots=[])]
        self.tasks[0]["deliverables"] = [str(self.source)]
        before = self.source.read_bytes()
        result = self.run_branch()
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual([], result["receipt"]["scope"])
        self.assertEqual(before, self.source.read_bytes())

    def test_read_only_branch_rejects_writable_plan(self):
        self.work["write_roots"] = []
        self.work["deliverables"] = [str(self.source)]
        self.branch["required_context"]["write_roots"] = []
        result = self.run_branch()
        self.assertEqual("failed", result["status"])
        self.assertEqual(["plan"], [call[0] for call in self.calls])

    def test_aggregate_is_called_only_after_all_experts_and_is_validated_and_reworked(self):
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            if phase == "aggregate":
                self.assertEqual({"a", "b"}, {r["producer_task_id"] for r in payload["expert_receipts"]})
            result = self.bridge(role_kind, contract)
            if phase == "aggregate" and payload["revision"] == 1:
                result["producer_task_id"] = "fake-final-producer"
            return result
        result = self.run_branch(bridge)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual(Counter(a=1, b=1), self.counts())
        self.assertEqual(2, result["receipt"]["revision"])
        self.assertEqual(2, sum(phase == "aggregate" for phase, _, _ in self.calls))

    def test_aggregate_failure_unknown_and_missing_final_artifact_never_complete(self):
        for status in ("unknown", "failed", "missing"):
            with self.subTest(status=status):
                self.calls = []
                def bridge(role_kind, contract):
                    phase, payload = contract["phase"], contract
                    result = self.bridge(role_kind, contract)
                    if phase == "aggregate":
                        if status == "missing":
                            Path(result["artifacts"][0]["path"]).unlink()
                        else:
                            result["status"] = status
                    return result
                result = self.run_branch(bridge, max_rework=0)
                self.assertEqual("unknown" if status == "unknown" else "failed", result["status"])
                self.assertIsNone(result["receipt"])
                self.assertEqual(1, sum(phase == "aggregate" for phase, _, _ in self.calls))

    def test_bad_branch_and_limits_fail_without_callback(self):
        for limits in ({"parallel_cap": True}, {"parallel_cap": 0}, {"parallel_cap": 4},
                       {"max_rework": -1}, {"max_rework": True}, {"max_rework": 4}):
            with self.subTest(limits=limits):
                result = self.run_branch(**limits)
                self.assertEqual("failed", result["status"])
                self.assertEqual(0, result["callback_invocations"])
        self.branch["state"] = "selection_gap"
        self.assertEqual(0, self.run_branch()["callback_invocations"])

    def test_plan_unknown_is_not_retried_and_has_no_experts(self):
        def bridge(role_kind, contract):
            phase, payload = contract["phase"], contract
            self.assertEqual("plan", phase)
            return {"status": "unknown"}
        result = self.run_branch(bridge, max_rework=3)
        self.assertEqual("unknown", result["status"])
        self.assertEqual(1, result["callback_invocations"])




class DirectExpertExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="legion-direct-experts-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.txt"
        self.source.write_text("declared source", encoding="utf-8")
        self.work = {"task_id": "branch", "goal": "bounded direct work",
                     "inputs": [str(self.source)], "deliverables": [str(self.root / "final.txt")],
                     "acceptance_ids": ["final-checked"], "write_roots": [str(self.root)],
                     "constraints": ["fixture-only"], "forbidden_actions": ["publish-external"]}

    def task(self, key, *, role="expert/search", dependencies=None):
        output_dir = self.root / key
        return {"task_id": key, "role_id": role, "assignment": f"local assignment {key}",
                "inputs": [str(self.source)], "deliverables": [str(output_dir / "artifact.txt")],
                "acceptance_ids": [f"checked-{key}"], "write_roots": [str(output_dir)],
                "depends_on": dependencies or []}

    def receipt(self, task, revision):
        artifacts = []
        for name in task["deliverables"]:
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{task['task_id']} revision {revision}", encoding="utf-8")
            artifacts.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return {"status": "completed", "producer_task_id": task["task_id"], "artifacts": artifacts,
                "scope": list(task["write_roots"]), "acceptance_passed": True,
                "acceptance_ids": list(task["acceptance_ids"]), "revision": revision,
                "host_evidence": {"kind": "python_fixture_not_native"}}

    def test_direct_experts_skips_leader_and_runs_same_role_instances_in_parallel(self):
        from legion_pipeline import execute_direct_experts
        tasks = [self.task("direct-a"), self.task("direct-b")]
        barrier = threading.Barrier(2)
        def bridge(role_kind, contract):
            self.assertEqual("expert", role_kind)
            self.assertEqual("execute", contract["phase"])
            barrier.wait(timeout=5)
            return self.receipt(contract["task"], contract["revision"])
        result = execute_direct_experts(self.work, tasks, bridge, parallel_cap=2)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual("aji", result["aggregation_owner"])
        self.assertEqual({"direct-a", "direct-b"}, set(result["expert_receipts"]))
        self.assertEqual(2, result["callback_invocations"])

    def test_direct_expert_dependencies_wait_for_completed_upstream(self):
        from legion_pipeline import execute_direct_experts
        first = self.task("direct-first")
        second = self.task("direct-second", dependencies=["direct-first"])
        completed = set()
        def bridge(role_kind, contract):
            task = contract["task"]
            if task["task_id"] == "direct-second":
                self.assertEqual({"direct-first"}, {item["producer_task_id"]
                                                     for item in contract["upstream_receipts"]})
            result = self.receipt(task, contract["revision"])
            completed.add(task["task_id"])
            return result
        result = execute_direct_experts(self.work, [first, second], bridge, parallel_cap=2)
        self.assertEqual("completed", result["status"], result["failures"])
        self.assertEqual({"direct-first", "direct-second"}, completed)

    def test_direct_read_only_expert_returns_structured_result_without_acceptance_gate(self):
        from legion_pipeline import execute_direct_experts
        work = {"task_id": "read-task", "goal": "Search read-only sources", "inputs": [],
                "deliverables": ["source findings"], "acceptance_ids": ["source-findings"],
                "write_roots": [], "constraints": [], "forbidden_actions": ["write-files"]}
        task = {"task_id": "github-search", "role_id": "expert/search",
                "assignment": "Search only GitHub sources", "inputs": [],
                "deliverables": ["source findings"], "acceptance_ids": ["source-findings"],
                "write_roots": [], "depends_on": []}
        def bridge(role_kind, contract):
            return {"status": "completed", "producer_task_id": contract["task"]["task_id"],
                    "revision": contract["revision"], "result": {"findings": ["project A"]},
                    "sources": ["https://github.com/example/project"]}
        result = execute_direct_experts(work, [task], bridge)
        self.assertEqual("completed", result["status"], result["failures"])
        receipt = result["expert_receipts"]["github-search"]
        self.assertEqual({"findings": ["project A"]}, receipt["result"])
        self.assertNotIn("acceptance_passed", receipt)
    def test_direct_expert_unknown_blocks_only_dependents_and_continues_independent(self):
        from legion_pipeline import execute_direct_experts
        tasks = [self.task("direct-a"),
                 self.task("direct-downstream", dependencies=["direct-a"]),
                 self.task("direct-independent")]
        calls = []
        def bridge(role_kind, contract):
            task_id = contract["task"]["task_id"]
            calls.append(task_id)
            if task_id == "direct-a":
                return {"status": "unknown"}
            return self.receipt(contract["task"], contract["revision"])
        result = execute_direct_experts(self.work, tasks, bridge, parallel_cap=1)
        self.assertEqual("unknown", result["status"])
        self.assertEqual(["direct-a", "direct-independent"], calls)
        self.assertNotIn("direct-downstream", calls)
        self.assertIn("direct-independent", result["expert_receipts"])
        self.assertEqual("blocked", result["task_states"]["direct-downstream"])

if __name__ == "__main__":
    unittest.main()
