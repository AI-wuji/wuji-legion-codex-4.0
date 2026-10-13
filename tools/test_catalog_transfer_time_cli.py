import json
import subprocess
import unittest

import test_core_cli
import test_resource_cli

EXECUTABLE = test_core_cli.EXECUTABLE


class CatalogTransferTimeCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core_cli.CoreCliTests("test_complete_copy_repeat_and_current_file")
        self.fixture.setUp()
        self.root = self.fixture.workspace

    def catalog(self):
        confirmation = "confirm-isolated-local-catalog"
        status = self.fixture.call("catalog-init", self.root, confirmation)
        scope = status["scope"]
        base = {"id": "policy", "scope": scope, "release": "r1", "revision": 1, "dependencies": [], "conflicts": [],
                "fields": {"authorization_required": True, "acceptance_required": True},
                "required_fields": ["authorization_required", "acceptance_required"], "allowed_slots": {}}
        path = self.fixture.write_json("policy-input.json", base)
        reference = {"id": "policy", "scope": scope, "release": "r1", "revision": 1, "type": "file", "schema_version": 1,
                     "sha256": self.fixture.call("hash", path)["sha256"]}
        expert = {"id": "reader", "scope": scope, "release": "r1", "revision": 1, "dependencies": [reference], "conflicts": [],
                  "fields": {name: f"scoped {name} contract" for name in ("role", "task", "process", "constraints", "output",
                              "specialty", "input_contract", "tool_contract", "acceptance_contract")},
                  "required_fields": [], "allowed_slots": {}}
        expert_path = self.fixture.write_json("reader-input.json", expert)
        expert_ref = dict(reference, id="reader", sha256=self.fixture.call("hash", expert_path)["sha256"])
        bundle = {"manifest": {"schema_version": 1, "scope": scope, "release": "r1", "required_roots": [reference],
                              "files": [{"path": "policy.json", "reference": reference}, {"path": "reader.json", "reference": expert_ref}]},
                  "definitions": {"policy.json": base, "reader.json": expert}}
        bundle_path = self.fixture.write_json("bundle.json", bundle)
        lock = self.fixture.call("catalog-stage", self.root, bundle_path, confirmation)
        lock_path = self.fixture.write_json("lock.json", lock)
        self.fixture.call("catalog-validate-local", self.root, lock_path, confirmation)
        return confirmation, lock, lock_path, reference, expert_ref

    def test_catalog_commands_are_real_and_parallel_pointer_publish_has_one_winner(self):
        confirmation, lock, path, reference, _ = self.catalog()
        processes = [subprocess.Popen([str(EXECUTABLE), "catalog-publish-local", str(self.root), str(path), "0", key, confirmation],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) for key in ("first", "second")]
        results = [(process.returncode, output, error) for process in processes for output, error in [process.communicate(timeout=30)]]
        self.assertEqual(sum(code == 0 for code, _, _ in results), 1, results)
        self.assertEqual([json.loads(error)["error"] for code, _, error in results if code], ["RevisionConflict"])
        self.assertEqual(self.fixture.call("catalog-lock", self.root, "active"), lock)
        source_path = self.fixture.write_json("source-ref.json", reference)
        impact = self.fixture.call("catalog-impact", self.root, path, source_path, 0, 10)
        self.assertEqual(impact["total"], 2)
        self.assertTrue(impact["complete"])
        self.fixture.call("catalog-repair-index", self.root, path, confirmation)
        self.fixture.call("catalog-withdraw", self.root, path, 1, "withdraw", confirmation)
        self.assertIsNone(self.fixture.call("catalog-status", self.root)["active_release"])

    def test_catalog_bound_actual_cli_copy_and_withdrawal_retain_exact_task_lock(self):
        confirmation, lock, lock_path, policy, _ = self.catalog()
        self.fixture.call("catalog-publish-local", self.root, lock_path, 0, "publish", confirmation)
        (self.root / "source.txt").write_text("actual catalog-bound copy", encoding="utf-8")
        reference = self.fixture.call("register-input", self.root, "user/source", "source.txt")
        roots_path = self.fixture.write_json("roots.json", [policy])
        plan_path = self.fixture.seal(self.fixture.plan(reference))
        prepared = self.fixture.call("plan-catalog-local", self.root, self.root, plan_path, lock_path, roots_path,
                                     "confirm-isolated-catalog-task")
        self.assertFalse(prepared["runtime_or_professional_admission"])
        self.assertFalse(prepared["task_role_and_input_scope_rewritten"])
        self.assertEqual(prepared["catalog_binding"]["release_lock"], lock)
        self.fixture.call("plan", self.root, plan_path, expected_error="EventConflict")
        self.fixture.call("run-local", self.root, "cli-task", "copy", "source.txt", "result.txt")
        self.assertEqual((self.root / "result.txt").read_text(encoding="utf-8"), "actual catalog-bound copy")
        pending = self.fixture.plan(reference)
        pending["payload"]["workflow_id"] = "pending"
        pending["metadata"]["id"] = "pending"
        pending["payload"]["nodes"][0]["write_roots"] = ["pending.txt"]
        pending_path = self.fixture.seal(pending, "pending-plan.json")
        self.fixture.call("plan-catalog-local", self.root, self.root, pending_path, lock_path, roots_path,
                          "confirm-isolated-catalog-task")
        self.fixture.call("catalog-withdraw", self.root, lock_path, 1, "withdraw", confirmation)
        self.fixture.call("run-local", self.root, "pending", "copy", "source.txt", "pending.txt",
                          expected_error="ValidationStale")
        self.assertFalse((self.root / "pending.txt").exists())
        self.assertEqual(self.fixture.call("status", self.root)["open_slots"], 0)
        self.fixture.call("run-local", self.root, "cli-task", "copy", "source.txt", "result.txt")
        self.assertEqual((self.root / "result.txt").read_text(encoding="utf-8"), "actual catalog-bound copy")

    def test_prepared_recipe_shares_exact_definition_without_started_agent_claims(self):
        confirmation, lock, path, policy, expert = self.catalog()
        self.fixture.call("catalog-publish-local", self.root, path, 0, "publish", confirmation)
        request = {"task_id": "recipe-cli", "release_lock": lock, "max_parallel_instances": 2, "byte_cap": 100000,
                   "instances": [{"instance_id": f"instance-{index}", "owner": f"lead-{index}", "definition_ref": expert,
                                  "mandatory_roots": [policy], "depends_on": [], "inputs": [], "write_roots": [f"outputs/{index}.txt"],
                                  "acceptance_ids": ["independent-review"], "task_kind": "code"} for index in range(2)]}
        result = self.fixture.call("prepare-recipe", self.root, self.root, self.fixture.write_json("recipe.json", request))
        self.assertEqual(result["state"], "prepared")
        self.assertEqual(len(result["shared_definitions"]), 1)
        self.assertEqual(result["actual_agents_started"], 0)
        self.assertFalse(result["runtime_admission"])

    def test_actual_process_transfer_ack_and_target_retirement_never_reactivate_source(self):
        resource = test_resource_cli.ResourceCliTests("test_review_requires_explicit_isolated_permit")
        resource.setUp()
        source = resource.fixture.workspace
        envelope = resource.fixture.seal(resource.knowledge(), "knowledge.json")
        proposal = resource.fixture.call("resource-propose", source, "knowledge", envelope, 0, "propose")
        reference_path = resource.fixture.write_json("resource-ref.json", proposal["reference"])
        resource.fixture.call("resource-review-local", source, "knowledge", reference_path, "review", "confirm-isolated-project-resource-review")
        permit = "confirm-isolated-resource-transfer"
        resource.fixture.call("transfer-begin", source, self.root, "knowledge", reference_path, "move", permit)
        resource.fixture.call("transfer-ack", source, self.root, "move", permit, expected_error="Reference")
        processes = [subprocess.Popen([str(EXECUTABLE), "transfer-accept", str(source), str(self.root), "move", permit],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) for _ in range(2)]
        results = [(process.returncode, json.loads(output)) for process in processes for output, error in [process.communicate(timeout=30)]]
        self.assertEqual([code for code, _ in results], [0, 0])
        self.assertEqual(results[0][1], results[1][1])
        finalized = resource.fixture.call("transfer-finalize", source, self.root, "move", permit)
        self.assertEqual(finalized["source_state"], "shared_ref")
        self.assertFalse(finalized["source_writable"])
        self.assertFalse(resource.fixture.call("transfer-query", source, self.root, "move", permit)["runtime_or_global_admission"])
        resource.fixture.call("transfer-retire", source, self.root, "move", 1, "retire-target", permit)
        resource.fixture.call("transfer-query", source, self.root, "move", permit, expected_error="ValidationStale")

    def test_time_conversion_and_explicit_binary_registration_preserve_text_boundary(self):
        conversion = {"quantity": {"numerator": -3, "denominator": 2, "unit": "second", "basis_ref": None, "rounding": "exact"},
                      "target_unit": "second", "target_basis_ref": None, "rounding": "nearest_even"}
        result = self.fixture.call("convert-time", self.root, self.fixture.write_json("time.json", conversion))
        self.assertEqual(result["quantity"]["numerator"], -2)
        self.assertFalse(result["runtime_authority"])
        (self.root / "opaque.bin").write_bytes(b"\xff\x00\x81")
        self.fixture.call("register-input", self.root, "user/opaque", "opaque.bin", expected_error="Shape")
        self.fixture.call("register-binary-input", self.root, "user/opaque", "opaque.bin", "wrong", expected_error="AuthorityDenied")
        binary = self.fixture.call("register-binary-input", self.root, "user/opaque", "opaque.bin", "confirm-isolated-binary-media-input")
        candidate = self.fixture.plan(binary)
        candidate["payload"]["nodes"][0]["read_roots"] = ["opaque.bin"]
        plan = self.fixture.seal(candidate)
        self.fixture.call("plan", self.root, plan)
        self.fixture.call("run-local", self.root, "cli-task", "copy", "opaque.bin", "result.txt", expected_error="Shape")
        self.assertEqual(self.fixture.call("status", self.root)["open_slots"], 0)

    def test_execution_summary_does_not_promote_planning_or_stale_output_to_completion(self):
        (self.root / "source.txt").write_text("current source", encoding="utf-8")
        reference = self.fixture.call("register-input", self.root, "user/source", "source.txt")
        plan = self.fixture.seal(self.fixture.plan(reference))
        self.fixture.call("plan", self.root, plan)
        before = self.fixture.call("execution-summary", self.root, "cli-task")
        self.assertEqual(before["result_state"], "incomplete")
        self.assertEqual(before["recorded_invocations"], 0)
        self.fixture.call("run-local", self.root, "cli-task", "copy", "source.txt", "result.txt")
        completed = self.fixture.call("execution-summary", self.root, "cli-task")
        self.assertEqual(completed["result_state"], "completed_bounded_task")
        self.assertEqual(completed["recorded_host_classes"], {"test_local": 1})
        self.assertEqual(completed["actual_model_thread_count"], "unknown")
        self.assertEqual(completed["formal_experts_activated"], 0)
        (self.root / "result.txt").write_text("changed output", encoding="utf-8")
        self.assertEqual(self.fixture.call("execution-summary", self.root, "cli-task")["result_state"], "incomplete")

    def test_read_set_prefix_cannot_authorize_a_different_sibling_file(self):
        (self.root / "data").mkdir()
        (self.root / "data/one-other.txt").write_text("private sibling", encoding="utf-8")
        reference = self.fixture.call("register-input", self.root, "user/sibling", "data/one-other.txt")
        candidate = self.fixture.plan(reference)
        candidate["payload"]["nodes"][0]["read_roots"] = ["data/one"]
        self.fixture.call("plan", self.root, self.fixture.seal(candidate), expected_error="PathDenied")
        self.assertEqual(self.fixture.call("status", self.root)["open_slots"], 0)


if __name__ == "__main__":
    unittest.main()
