import json
import os
from pathlib import Path
import subprocess
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / ".dev" / "runtime-target" / "debug" / "wuji4.exe"


class CoreCliTests(unittest.TestCase):
    def setUp(self):
        self.workspace = ROOT / ".dev" / "core-test-workspaces" / f"cli-{self._testMethodName}-{os.getpid()}-{time.time_ns()}"
        self.workspace.mkdir(parents=True)
        self.initial = self.call("init", self.workspace)

    def call(self, *arguments, expected_error=None):
        completed = subprocess.run(
            [str(EXECUTABLE), *map(str, arguments)], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if expected_error is not None:
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            result = json.loads(completed.stderr)
            self.assertEqual(result["error"], expected_error, result)
            self.assertFalse(result["success"])
            return result
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def write_json(self, name, value):
        path = self.workspace / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def seal(self, plan, name="plan.json"):
        plan["metadata"].pop("content_hash", None)
        path = self.write_json("unsealed.json", plan)
        plan["metadata"]["content_hash"] = self.call("object-hash", path)["sha256"]
        return self.write_json(name, plan)

    def plan(self, reference=None):
        return {
            "schema_version": 1, "contract_type": "WorkflowPlan",
            "payload": {
                "workflow_id": "cli-task", "version": "1",
                "catalog_version": self.initial["admitted_local_program_ref"]["release"],
                "nodes": [{
                    "id": "copy", "role_ref": self.initial["admitted_local_program_ref"],
                    "owner": "local-executor", "revision": 1,
                    "inputs": [reference] if reference else [],
                    "read_roots": ["source.txt"] if reference else [],
                    "write_roots": ["result.txt"],
                    "acceptance_ids": ["local.file-readable", "local.hash-current", "local.utf8"],
                    "status": "planned", "execution_form": "program",
                }],
                "edges": [],
                "budget": {
                    "max_candidates": 8, "max_query_objects": 20, "max_hops": 3,
                    "target_contract_bytes": 1024, "target_evidence_bytes": 1024,
                    "hard_bytes_limit": None, "measured_tokens": None, "effective_token_limit": None,
                    "wall_ms": 60000, "max_parallel_workers": 2, "max_extra_retries": 6,
                    "max_point_revisions": 2, "max_no_progress": 2,
                },
            },
            "metadata": {
                "id": "cli-task", "type": "WorkflowPlan", "scope": self.initial["scope"],
                "schema_version": 1, "revision": 1, "owner": "aji-local",
                "authority": "review_proposal", "status": "proposal",
                "source_refs": [], "evidence_refs": [],
                "created_at_utc_ms": 1, "updated_at_utc_ms": 1, "valid_until_utc_ms": None,
                "classification": "project_private", "content_hash": "0" * 64, "parent_refs": [],
            },
        }

    def prepare(self):
        (self.workspace / "source.txt").write_text("真实CLI输入，无模型生成。", encoding="utf-8")
        reference = self.call("register-input", self.workspace, "user/source", "source.txt")
        plan = self.plan(reference)
        path = self.seal(plan)
        self.call("plan", self.workspace, path)
        return plan, path

    def test_complete_copy_repeat_and_current_file(self):
        self.prepare()
        result = self.call("run-local", self.workspace, "cli-task", "copy", "source.txt", "result.txt")
        self.assertFalse(result["professional_or_native_verified"])
        self.assertEqual(result["status"]["open_slots"], 0)
        self.assertEqual(self.call("task-status", self.workspace, "cli-task")["state"], "succeeded")
        self.assertEqual((self.workspace / "result.txt").read_bytes(), (self.workspace / "source.txt").read_bytes())
        before = (self.workspace / "result.txt").stat().st_mtime_ns
        replay = self.call("run-local", self.workspace, "cli-task", "copy", "source.txt", "result.txt")
        self.assertEqual(replay, result)
        self.assertEqual((self.workspace / "result.txt").stat().st_mtime_ns, before)
        observation = self.call("attempt", self.workspace, result["produced"]["attempt_id"])
        self.assertEqual(observation["slot_state"], "closed")
        self.assertEqual(observation["attempt_state"], "accepted")

    def test_unregistered_input_not_admitted(self):
        reference = dict(self.initial["admitted_local_program_ref"])
        reference["id"] = "unregistered"
        path = self.seal(self.plan(reference))
        self.call("plan", self.workspace, path, expected_error="Reference")
        self.assertEqual(self.call("status", self.workspace)["tasks"], 0)

    def test_self_granted_authority_cannot_plan(self):
        plan = self.plan()
        plan["metadata"]["authority"] = "user_explicit"
        self.call("plan", self.workspace, self.seal(plan), expected_error="AuthorityDenied")
        self.assertEqual(self.call("status", self.workspace)["tasks"], 0)

    def test_native_request_is_not_local_success(self):
        plan = self.plan()
        plan["payload"]["nodes"][0]["execution_form"] = "model"
        self.call("plan", self.workspace, self.seal(plan), expected_error="HostUnknown")
        status = self.call("host-status")
        self.assertEqual(status["requested_model"], "inherit_current_selection")
        self.assertEqual(status["upgrade_model"], "gpt-6.1-sol")
        self.assertFalse(status["automatic_downgrade"])
        self.assertFalse(status["failure_fallback_chain"])
        self.assertEqual(status["effective_model"], "unknown")
        self.assertEqual(status["fee_precondition"], "unknown")
        self.assertFalse(status["native_host_verified"])

    def test_changed_input_persists_and_output_is_preserved(self):
        self.prepare()
        result = self.call("run-local", self.workspace, "cli-task", "copy", "source.txt", "result.txt")
        original = (self.workspace / "result.txt").read_bytes()
        (self.workspace / "source.txt").write_text("changed", encoding="utf-8")
        changed = self.call("refresh", self.workspace)
        self.assertEqual(changed["affected_nodes"], 1)
        self.assertEqual(changed["slots_released"], 0)
        self.call("run-local", self.workspace, "cli-task", "copy", "source.txt", "result.txt", expected_error="ValidationStale")
        observation = self.call("attempt", self.workspace, result["produced"]["attempt_id"])
        self.assertEqual(observation["attempt_state"], "superseded")
        self.assertEqual((self.workspace / "result.txt").read_bytes(), original)

    def test_checkpoint_is_context_only_and_tamper_fails(self):
        self.prepare()
        checkpoint = self.call("checkpoint", self.workspace, "cli-task")
        context = self.call("checkpoint-inspect", self.workspace, checkpoint["checkpoint_id"])
        self.assertTrue(context["reusable_as_context"])
        self.assertFalse(context["execution_authority"])
        self.call("run-local", self.workspace, "cli-task", "copy", "source.txt", "result.txt")
        self.assertFalse(self.call("checkpoint-inspect", self.workspace, checkpoint["checkpoint_id"])["reusable_as_context"])
        Path(checkpoint["path"]).write_text("tampered", encoding="utf-8")
        self.call("checkpoint-inspect", self.workspace, checkpoint["checkpoint_id"], expected_error="HashMismatch")

    def test_revision_cas_is_idempotent_without_budget_reset(self):
        plan, _ = self.prepare()
        plan["metadata"]["revision"] = 2
        plan["payload"]["version"] = "2"
        plan["payload"]["nodes"][0]["revision"] = 2
        plan["payload"]["nodes"][0]["write_roots"] = ["result-v2.txt"]
        path = self.seal(plan, "revised.json")
        result = self.call("revise", self.workspace, path, 1, "user-event-1")
        self.assertEqual(result["graph_revision"], 2)
        self.assertEqual(self.call("revise", self.workspace, path, 1, "user-event-1"), result)
        self.call("revise", self.workspace, path, 1, "user-event-2", expected_error="RevisionConflict")
        plan["metadata"]["revision"] = 3
        plan["payload"]["nodes"][0]["revision"] = 3
        plan["payload"]["nodes"][0]["write_roots"] = ["result-v3.txt"]
        plan["payload"]["budget"]["max_extra_retries"] = 999
        self.call("revise", self.workspace, self.seal(plan, "budget-reset.json"), 2, "reset", expected_error="BudgetExhausted")

    def test_strict_json_and_no_arbitrary_actor_command(self):
        path = self.workspace / "duplicate.json"
        path.write_text('{"value":1,"value":2}', encoding="utf-8")
        self.call("hash", path, expected_error="Shape")
        self.call("--actor", "aji", expected_error="Shape")
        self.assertFalse(self.call("help")["P7_installed"])

    def test_t19_actual_review_repair_revalidates_one_evidenced_defect_without_forced_count(self):
        plan, _ = self.prepare()
        self.call("run-local", self.workspace, "cli-task", "copy", "source.txt", "result.txt")
        before = self.call("execution-summary", self.workspace, "cli-task")
        self.assertEqual(before["result_state"], "completed_bounded_task")
        (self.workspace / "result.txt").write_text("actual drift after acceptance", encoding="utf-8")
        defective = self.call("execution-summary", self.workspace, "cli-task")
        self.assertEqual(defective["result_state"], "incomplete")
        self.assertEqual(len(defective["unmet_nodes"]), 1)
        plan["metadata"]["revision"] = 2
        plan["payload"]["version"] = "2"
        plan["payload"]["nodes"][0]["revision"] = 2
        plan["payload"]["nodes"][0]["write_roots"] = ["repaired.txt"]
        proposal = self.seal(plan, "actual-repair.json")
        revised = self.call("repair", self.workspace, proposal, 1, "one-observed-defect")
        self.assertEqual(revised["affected_nodes"], ["copy"])
        self.assertEqual(self.call("repair", self.workspace, proposal, 1, "one-observed-defect"), revised)
        self.call("run-local", self.workspace, "cli-task", "copy", "source.txt", "repaired.txt")
        repaired = self.call("execution-summary", self.workspace, "cli-task")
        self.assertEqual(repaired["result_state"], "completed_bounded_task")
        self.assertEqual(repaired["recorded_invocations"], 2)
        self.assertEqual(repaired["unclosed_slots"], 0)
        self.assertEqual((self.workspace / "repaired.txt").read_bytes(), (self.workspace / "source.txt").read_bytes())
        self.assertEqual(self.call("task-status", self.workspace, "cli-task")["revisions_used"], 0)
        plan["metadata"]["revision"] = 3
        plan["payload"]["version"] = "3"
        self.call("repair", self.workspace, self.seal(plan, "no-real-defect.json"), 2,
                  "force-three-findings", expected_error="RevisionConflict")
        self.assertEqual(self.call("execution-summary", self.workspace, "cli-task"), repaired)

    def test_cancel_is_revision_bound_and_preserves_files(self):
        self.prepare()
        self.call("cancel", self.workspace, "cli-task", 2, expected_error="RevisionConflict")
        self.assertEqual(self.call("task-status", self.workspace, "cli-task")["state"], "planned")
        result = self.call("cancel", self.workspace, "cli-task", 1)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(self.call("cancel", self.workspace, "cli-task", 1), result)
        self.assertEqual(self.call("task-status", self.workspace, "cli-task")["state"], "cancelled")
        self.assertTrue((self.workspace / "source.txt").exists())
        self.assertFalse((self.workspace / "result.txt").exists())


if __name__ == "__main__":
    unittest.main()
