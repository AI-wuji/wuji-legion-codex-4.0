import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import execution_baseline
import run_legion_task as legion
import test_core_cli


class LegionTaskTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core_cli.CoreCliTests("test_complete_copy_repeat_and_current_file")
        self.fixture.setUp()
        self.root = self.fixture.workspace

    def test_simple_and_professional_route_load_only_needed_context_without_agents(self):
        simple = legion.route("chat")
        self.assertTrue(simple["direct_answer"])
        self.assertFalse(simple["staff_graph_required"])
        self.assertEqual(len(simple["context"]), 1)
        professional = legion.route("engineering")
        self.assertEqual(len(professional["context"]), 2)
        self.assertIn("engineering.md", professional["context"][1]["path"])
        self.assertEqual(professional["actual_agents_started"], 0)
        self.assertFalse(professional["execution_authority"])
        for kind in ("research", "documents", "media", "evolution"):
            related = legion.route(kind)
            self.assertEqual(len(related["context"]), 2)
            self.assertIn(f"{kind}.md", related["context"][1]["path"])
            self.assertFalse(related["model_generation_submitted"])
        with self.assertRaises(ValueError):
            legion.route("all-experts")

    def test_complex_delegation_builds_aji_staff_leader_expert_return_contract_without_execution(self):
        result = legion.delegate({
            "task_id": "meta-instruction-route",
            "goal": "把元指令改得更稳定，并保留全局入口边界",
            "domain": "governance",
            "typed_intents": ["meta_instruction", "instruction_revision"],
            "inputs": ["current-agents-md"],
            "deliverables": ["revised-instruction-draft", "impact-summary"],
            "acceptance_ids": ["goal-explicit", "impact-and-reversal-identified"],
            "write_roots": [],
            "constraints": ["do-not-change-codex-config"],
        })
        self.assertEqual(result["communicator"], "aji")
        self.assertEqual(result["staff_decision"], "recipe_selected")
        self.assertEqual(result["state"], "prepared_not_executed")
        self.assertEqual(result["return_path"], ["expert", "leader", "staff", "aji"])
        self.assertEqual(result["leader_recipe"]["id"], "leader/prompt-governance")
        self.assertEqual(
            {item["role_id"] for item in result["selected_expert_refs"]},
            {"p3/method/requirement-decomposition", "p3/governance/evolution-review"},
        )
        self.assertEqual(result["actual_agents_started"], 0)
        self.assertEqual(result["formal_experts_activated"], 0)
        self.assertFalse(result["runtime_admission"])
        self.assertFalse(result["model_generation_submitted"])
        self.assertFalse(result["execution_authority"])
        self.assertTrue(all("workbuddy" not in item["catalog_ref"].lower()
                            for item in result["selected_expert_refs"]))

    def test_auto_routing_keeps_minimal_chain_and_escalates_only_for_capability_or_team(self):
        base = {
            "task_id": "auto-minimal",
            "goal": "解释一个术语",
            "domain": "general",
            "typed_intents": ["explanation"],
            "inputs": [],
            "deliverables": ["short-answer"],
            "acceptance_ids": ["direct-answer"],
            "task_class": "auto",
        }
        minimal = legion.delegate(base)
        self.assertEqual("simple", minimal["routing_signals"]["resolved_task_class"])
        self.assertEqual("minimal_chain", minimal["routing_signals"]["reason"])
        self.assertEqual(["aji"], minimal["activation_chain"])

        one_expert = legion._validate_delegation_request({
            **base, "task_id": "auto-one-expert", "requested_expert_count": 1,
        })
        self.assertEqual("simple", one_expert["task_class"])

        team = legion._validate_delegation_request({
            **base, "task_id": "auto-team", "requested_expert_count": 1,
            "team_requested": True,
        })
        self.assertEqual("complex", team["task_class"])
        self.assertEqual("professional_capability_or_team", team["routing_signals"]["reason"])

        capability = legion._validate_delegation_request({
            **base, "task_id": "auto-capability", "requires_mcp": True,
        })
        self.assertEqual("simple", capability["task_class"])

    def test_leader_expert_pipeline_is_localized_parallel_and_rejects_bad_upstream(self):
        task = {"subtask_id": "pipeline", "inputs": ["accepted-brief"]}
        members = [
            {"role_id": "p3/leaf/one", "baseline_id": "one", "assignment": "先做独立分析", "depends_on": []},
            {"role_id": "p3/leaf/two", "baseline_id": "two", "assignment": "并行做独立校验", "depends_on": []},
        ]
        pipeline = legion._build_expert_pipeline(members, task, ["artifact-accepted"], parallel_cap=2)
        self.assertEqual("leader_assigned_expert_pipeline", pipeline["mode"])
        self.assertEqual(1, len(pipeline["schedule"]["parallel_groups"]))
        self.assertTrue(all(item["member_visibility"] == "own_task_and_upstream_only"
                            for item in pipeline["tasks"]))
        contract = pipeline["tasks"][0]["input_contract"]
        rejected = legion._validate_upstream_receipt(contract, {
            "producer_task_id": "upstream",
            "artifacts": [],
            "scope": "brief",
            "acceptance_passed": False,
        })
        self.assertEqual("rework_upstream", rejected["decision"])
        accepted = legion._validate_upstream_receipt(contract, {
            "producer_task_id": "upstream",
            "artifacts": ["brief.md"],
            "scope": "brief",
            "acceptance_passed": True,
        })
        self.assertTrue(accepted["accepted"])

    def test_simple_delegation_stays_with_aji_without_staff_graph(self):
        result = legion.delegate({
            "task_id": "simple-route",
            "goal": "解释一个术语",
            "domain": "general",
            "typed_intents": ["explanation"],
            "inputs": [],
            "deliverables": ["short-answer"],
            "acceptance_ids": ["direct-answer"],
            "task_class": "simple",
        })
        self.assertEqual(result["operation"], "aji-direct")
        self.assertEqual(result["return_path"], ["aji"])
        self.assertFalse(result["staff_graph_required"])

    def test_delegation_gap_does_not_fall_back_to_all_experts(self):
        result = legion.delegate({
            "task_id": "unknown-route",
            "goal": "处理一个没有正式配方的领域任务",
            "domain": "unmapped-domain",
            "typed_intents": ["unmapped-intent"],
            "inputs": [],
            "deliverables": ["gap-report"],
            "acceptance_ids": ["gap-explicit"],
        })
        self.assertEqual(result["state"], "selection_gap")
        self.assertEqual(result["selected_expert_refs"], [])
        self.assertTrue(result["staff_graph_required"])
        self.assertIn("select one exact leader recipe for this subtask", result["not_done"])

    def test_complete_cold_leader_catalog_routes_all_recorded_roles_without_runtime_activation(self):
        manifest = json.loads((legion.DELEGATION_MANIFEST).read_text(encoding="utf-8"))
        catalog = json.loads((legion.EXPERT_CATALOG).read_text(encoding="utf-8"))
        referenced = {
            reference if isinstance(reference, str) else reference["role_id"]
            for recipe in manifest["recipes"]
            for reference in recipe["expert_refs"]
        }
        self.assertEqual(manifest["recipe_count"], len(manifest["recipes"]))
        self.assertEqual(manifest["leader_family_count"], len(manifest["leader_family_ids"]))
        catalog_ids = {role["id"] for role in catalog["roles"]}
        coverage = manifest["expert_coverage"]
        expected_referenced = (catalog_ids - set(coverage["unbound_role_ids"])) | set(coverage["out_of_catalog_role_ids"])
        self.assertEqual(expected_referenced, referenced)
        for recipe in manifest["recipes"]:
            result = legion.delegate({
                "task_id": f"catalog-{recipe['recipe_id']}",
                "goal": "验证负责人配方路由",
                "domain": recipe["domains"][0],
                "typed_intents": [recipe["typed_intents"][0]],
                "inputs": ["bounded-input"],
                "deliverables": ["bounded-receipt"],
                "acceptance_ids": [],
            })
            unresolved_recipes = {
                "meta-instruction-design", "meta-instruction-governance", "meta-instruction-model-rewrite",
                "comfyui-plugin-research", "comfyui-plugin-delivery",
                "video-production-delivery", "video-studio-delivery", "video-post-production",
            }
            if recipe["recipe_id"] in unresolved_recipes:
                self.assertEqual("selection_gap", result["staff_decision"], recipe["recipe_id"])
                self.assertTrue(result["missing_expert_refs"])
                self.assertTrue(set(result["missing_expert_refs"]).issubset(coverage["out_of_catalog_role_ids"]))
                self.assertEqual(0, result.get("actual_agents_started", 0))
                continue
            self.assertEqual("recipe_selected", result["staff_decision"], recipe["recipe_id"])
            self.assertEqual(recipe["recipe_id"], result["leader_recipe"]["recipe_id"])
            self.assertFalse(result["runtime_admission"])
            self.assertEqual(0, result["actual_agents_started"])
            self.assertEqual(0, result["formal_experts_activated"])
            self.assertFalse(result["model_generation_submitted"])
            self.assertTrue(all(item.get("role_id") and item.get("catalog_ref") for item in result["selected_expert_refs"]))

    def test_shared_experts_can_be_reused_and_broad_leader_match_stays_selection_gap(self):
        software = legion.delegate({
            "task_id": "shared-software",
            "goal": "实现一个有边界的软件变更",
            "domain": "software",
            "typed_intents": ["implementation"],
            "deliverables": ["patch"],
            "acceptance_ids": [],
        })
        bugfix = legion.delegate({
            "task_id": "shared-bugfix",
            "goal": "修复一个可复现故障",
            "domain": "bugfix",
            "typed_intents": ["bug_fix"],
            "deliverables": ["patch"],
            "acceptance_ids": [],
        })
        software_roles = {item["role_id"] for item in software["selected_expert_refs"]}
        bugfix_roles = {item["role_id"] for item in bugfix["selected_expert_refs"]}
        self.assertIn("p3/leaf/code-review", software_roles)
        self.assertIn("p3/leaf/code-review", bugfix_roles)
        broad = legion.delegate({
            "task_id": "ambiguous-engineering",
            "goal": "处理一个尚未明确类型的软件工作",
            "domain": "engineering",
            "typed_intents": [],
            "deliverables": ["selection-gap"],
            "acceptance_ids": [],
        })
        self.assertEqual("selection_gap", broad["state"])
        self.assertEqual([], broad["selected_expert_refs"])

    def test_core_skill_is_the_only_legion_entry_without_a_legacy_runtime(self):
        core_skill = (legion.PACK / "skills/wuji-legion-4-0/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: wuji-legion-4-0", core_skill)
        self.assertIn("唯一的无极军团入口", core_skill)
        self.assertIn("不要求口令", core_skill)
        self.assertIn("懒人行动", core_skill)
        self.assertNotIn("wuji-legion-codex-3-0", core_skill)
        self.assertNotIn("并列共存", core_skill)

    def work_item(self, subtask_id, domain="software", intents=None, writes=None):
        return {"subtask_id": subtask_id, "goal": "完成一个有明确边界的子任务", "domain": domain,
                "typed_intents": intents if intents is not None else ["implementation"],
                "deliverables": ["bounded-artifact"], "acceptance_ids": ["scope-locked"],
                "write_roots": writes or [], "inputs": [], "constraints": []}

    def test_composite_routes_two_leaders_with_conditional_experts_and_one_shared_budget(self):
        software = self.work_item("code", writes=[".dev/route-contract/code"])
        software["languages"] = ["python"]
        instruction = self.work_item("instruction", "prompt_meta", ["instruction_revision"],
                                     [".dev/route-contract/instruction.md"])
        result = legion.delegate({"task_id": "composite", "goal": "分别改代码和元指令",
                                  "inputs": ["shared-source"],
                                  "constraints": ["do-not-change-codex-config"],
                                  "write_roots": [".dev/route-contract"],
                                  "subtasks": [software, instruction]})
        self.assertEqual("recipes_selected", result["staff_decision"])
        self.assertEqual("prepared_not_executed", result["state"])
        self.assertEqual([["code", "instruction"]], result["parallel_preparation"]["groups"])
        self.assertTrue(result["parallel_preparation"]["parallel_eligible"])
        branches = {branch["subtask_id"]: branch for branch in result["branches"]}
        self.assertEqual("software-delivery", branches["code"]["leader_recipe"]["recipe_id"])
        self.assertEqual("meta-instruction-revision", branches["instruction"]["leader_recipe"]["recipe_id"])
        self.assertEqual({"p3/selector/code-implementation", "p3/leaf/python-engineer", "p3/leaf/code-review"},
                         {role["role_id"] for role in branches["code"]["selected_expert_refs"]})
        cold = {role["role_id"] for role in branches["code"]["cold_expert_refs"]}
        self.assertIn("p3/leaf/rust-engineer", cold)
        self.assertIn("p3/leaf/software-reverse", cold)
        for branch in result["branches"]:
            self.assertIn("shared-source", branch["required_context"]["inputs"])
            self.assertIn("do-not-change-codex-config", branch["required_context"]["constraints"])
        self.assertEqual("all_leader_and_expert_instances", result["shared_budget"]["applies_to"])
        self.assertEqual("unknown", result["shared_budget"]["effective_host_quota"])
        self.assertEqual(0, result["actual_agents_started"])
        self.assertEqual(0, result["formal_experts_activated"])
        self.assertFalse(result["execution_authority"])

    def test_dependency_and_canonical_write_conflicts_prevent_parallel_preparation(self):
        first = self.work_item("first", writes=[".dev/route-contract/shared"])
        second = self.work_item("second", writes=[".DEV/route-contract/temp/../SHARED/file.py"])
        result = legion.delegate({"task_id": "write-conflict", "goal": "共享写集应串行", "subtasks": [first, second]})
        self.assertFalse(result["parallel_preparation"]["parallel_eligible"])
        self.assertEqual([["first"], ["second"]], result["parallel_preparation"]["groups"])
        second["write_roots"] = [".dev/route-contract/other"]
        second["depends_on"] = ["first"]
        dependent = legion.delegate({"task_id": "dependency", "goal": "前置应保留", "subtasks": [second, first]})
        self.assertEqual([["first"], ["second"]], dependent["parallel_preparation"]["groups"])

    def test_selection_gap_blocks_only_affected_branch_and_its_dependents(self):
        gap = self.work_item("gap", "unmapped-domain", ["unmapped-intent"])
        downstream = self.work_item("downstream")
        downstream["depends_on"] = ["gap"]
        independent = self.work_item("independent")
        result = legion.delegate({"task_id": "local-gap", "goal": "保留独立分支", "subtasks": [gap, downstream, independent]})
        self.assertEqual("selection_gap", result["state"])
        self.assertEqual([["independent"]], result["parallel_preparation"]["groups"])
        self.assertEqual({"gap": ["gap"], "downstream": ["gap"]},
                         result["parallel_preparation"]["blocked_branches"])
        self.assertFalse(result["runtime_admission"])

    def test_composite_rejects_invalid_dependencies_duplicate_ids_and_scope_expansion(self):
        first = self.work_item("first", writes=[".dev/route-contract/first"])
        second = self.work_item("second", writes=[".dev/route-contract/second"])
        for dependencies, expected in ((["missing"], "dependencies"), (["second"], "self-reference")):
            second["depends_on"] = dependencies
            with self.subTest(dependencies=dependencies), self.assertRaisesRegex(ValueError, expected):
                legion.delegate({"task_id": "invalid", "goal": "拒绝错误图", "subtasks": [first, second]})
        second["depends_on"] = ["first"]
        first["depends_on"] = ["second"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            legion.delegate({"task_id": "cycle", "goal": "拒绝循环", "subtasks": [first, second]})
        first["depends_on"] = []
        second["depends_on"] = []
        with self.assertRaisesRegex(ValueError, "unique"):
            legion.delegate({"task_id": "duplicate", "goal": "拒绝重复ID", "subtasks": [first, first]})
        with self.assertRaisesRegex(ValueError, "parent scope"):
            legion.delegate({"task_id": "escape", "goal": "拒绝越界", "write_roots": [".dev/allowed"],
                             "subtasks": [first]})

    def test_shared_parallel_cap_is_bounded_and_does_not_claim_native_quota(self):
        subtasks = [self.work_item(f"branch-{index}") for index in range(5)]
        result = legion.delegate({"task_id": "shared-cap", "goal": "所有分支共享预算",
                                  "max_parallel_instances": 2, "subtasks": subtasks})
        self.assertTrue(all(len(group) <= 2 for group in result["parallel_preparation"]["groups"]))
        self.assertFalse(result["shared_budget"]["native_admission"])
        for cap in (0, 4, True, "2"):
            with self.subTest(cap=cap), self.assertRaisesRegex(ValueError, "construction cap"):
                legion.delegate({"task_id": "invalid-cap", "goal": "拒绝错误预算",
                                 "max_parallel_instances": cap, "subtasks": subtasks})

    def test_explicit_empty_parent_write_scope_cannot_be_expanded_by_subtask(self):
        subtask = self.work_item("write", writes=[".dev/route-contract/output.md"])
        request = {"task_id": "read-only-parent", "goal": "明确父级禁止写入",
                   "write_roots": [], "subtasks": [subtask]}
        with self.assertRaisesRegex(ValueError, "parent scope"):
            legion.delegate(request)
        request.pop("write_roots")
        self.assertEqual("prepared_not_executed", legion.delegate(request)["state"])
        request["write_roots"] = []
        subtask["write_roots"] = []
        self.assertEqual("prepared_not_executed", legion.delegate(request)["state"])

    def test_expert_conditions_are_explicit_and_goal_text_does_not_activate_languages(self):
        request = {"task_id": "conditions", "goal": "不要用Rust、Go、Cpp；只做当前代码审查",
                   "domain": "software", "typed_intents": ["software_review"],
                   "deliverables": ["review"], "acceptance_ids": []}
        result = legion.delegate(request)
        self.assertEqual({"p3/leaf/code-review"},
                         {role["role_id"] for role in result["selected_expert_refs"]})
        manifest = json.loads(legion.DELEGATION_MANIFEST.read_text(encoding="utf-8"))
        for recipe in manifest["recipes"]:
            for reference in recipe["expert_refs"]:
                selection = reference["selection"]
                task = {"typed_intents": selection.get("any_intents", []),
                        "languages": selection.get("any_languages", [])}
                self.assertTrue(legion._role_needed(reference, task)[0], reference["role_id"])
        for invalid in ({}, {"required": 1}, {"any_intents": []}, {"all_experts": True}):
            with self.subTest(selection=invalid), self.assertRaises(ValueError):
                legion._selection_rule({"role_id": "p3/leaf/code-review", "selection": invalid})

    def test_real_composite_cli_preserves_boundaries_without_native_execution(self):
        request = {"task_id": "composite-cli", "goal": "有界多主帅CLI准备",
                   "constraints": ["do-not-change-codex-config"],
                   "subtasks": [self.work_item("instruction", "prompt_meta", ["meta_instruction"]),
                                self.work_item("review", "software", ["software_review"])]}
        path = self.root / "composite-request.json"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([sys.executable, str(execution_baseline.ROOT / "tools/wuji4.py"),
                                 "delegate", str(path)], capture_output=True, encoding="utf-8", timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(0, result.returncode, result.stderr)
        prepared = json.loads(result.stdout)
        self.assertEqual("recipes_selected", prepared["staff_decision"])
        self.assertEqual(2, len(prepared["branches"]))
        self.assertFalse(prepared["model_generation_submitted"])
        self.assertEqual(0, prepared["actual_agents_started"])

    def test_actual_thin_entry_writes_validates_summarizes_and_replays_without_second_invocation(self):
        (self.root / "source.txt").write_bytes("真实隔离军团任务，不是模型生成".encode("utf-8"))
        arguments = (self.root, "legion-task", "source.txt", "output.txt", "confirm-isolated-legion-file-copy")
        first = legion.run_copy(*arguments)
        repeated = legion.run_copy(*arguments)
        self.assertEqual(first["summary"]["result_state"], "completed_bounded_task")
        self.assertTrue(first["completed"])
        self.assertEqual(repeated["summary"]["recorded_invocations"], 1)
        self.assertEqual(first["summary"]["unclosed_slots"], 0)
        self.assertFalse(first["model_generation_submitted"])
        self.assertFalse(first["P7"])
        self.assertEqual((self.root / "output.txt").read_bytes(), (self.root / "source.txt").read_bytes())
        (self.root / "output.txt").write_text("changed after validation", encoding="utf-8")
        summary = legion.call("execution-summary", self.root, "legion-task")
        self.assertEqual(summary["result_state"], "incomplete")
        self.assertTrue(summary["unmet_nodes"])
        with self.assertRaisesRegex(ValueError, "ValidationStale"):
            legion.run_copy(*arguments)
        self.assertEqual((self.root / "output.txt").read_text(encoding="utf-8"), "changed after validation")

    def test_actual_summary_recheck_does_not_keep_success_text_after_output_changes(self):
        (self.root / "source.txt").write_text("Real current-summary race input", encoding="utf-8")
        actual_call = legion.call

        def mutate_after_real_validation(*arguments):
            result = actual_call(*arguments)
            if arguments[0] == "run-local":
                (self.root / "output.txt").write_text("changed after validation", encoding="utf-8")
            return result

        with mock.patch.object(legion, "call", side_effect=mutate_after_real_validation):
            stale = legion.run_copy(self.root, "legion-summary-race", "source.txt", "output.txt", "confirm-isolated-legion-file-copy")
        self.assertFalse(stale["completed"])
        self.assertEqual(stale["summary"]["result_state"], "incomplete")
        self.assertEqual(stale["summary"]["recorded_invocations"], 1)
        self.assertIn("未通过完成检查", stale["user_summary"])
        self.assertEqual((self.root / "output.txt").read_text(encoding="utf-8"), "changed after validation")

    def test_execute_delegation_runs_leader_expert_aggregate_contract_with_fixture_io(self):
        with tempfile.TemporaryDirectory(dir=execution_baseline.ROOT / ".dev" / "core-test-workspaces") as temporary:
            root = Path(temporary).resolve()
            source = root / "source.txt"
            expert_output = root / "expert.json"
            final_output = root / "final.json"
            source.write_text("source", encoding="utf-8")
            request = {
                "task_id": "one-shot-execution",
                "goal": "执行一个有界软件分支",
                "domain": "software",
                "typed_intents": ["implementation"],
                "inputs": [str(source)],
                "deliverables": [str(final_output)],
                "acceptance_ids": ["final-check"],
                "write_roots": [str(root)],
                "constraints": ["fixture-only"],
                "task_class": "complex",
            }
            calls = []

            def bridge(role_kind, contract):
                calls.append((role_kind, contract["phase"], contract["role_id"]))
                if contract["phase"] == "plan":
                    role_id = contract["candidates"][0]["role_id"]
                    return {"status": "completed", "tasks": [{
                        "task_id": "expert-1", "role_id": role_id, "assignment": "写入专家回执",
                        "inputs": [str(source)], "deliverables": [str(expert_output)],
                        "acceptance_ids": ["expert-check"], "write_roots": [str(root)],
                        "depends_on": [], "forbidden_actions": [],
                    }], "host_evidence": {"kind": "python_fixture_not_native"}}
                if contract["phase"] == "execute":
                    path = Path(contract["task"]["deliverables"][0])
                    path.write_text("expert", encoding="utf-8")
                    return {"status": "completed", "producer_task_id": contract["task"]["task_id"],
                            "artifacts": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
                            "scope": [str(root)], "acceptance_passed": True,
                            "acceptance_ids": ["expert-check"], "revision": contract["revision"],
                            "host_evidence": {"kind": "python_fixture_not_native"}}
                path = Path(contract["work_item"]["deliverables"][0])
                path.write_text("final", encoding="utf-8")
                return {"status": "completed", "producer_task_id": contract["work_item"]["task_id"],
                        "artifacts": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
                        "scope": [str(root)], "acceptance_passed": True,
                        "acceptance_ids": ["final-check"], "revision": contract["revision"],
                        "host_evidence": {"kind": "python_fixture_not_native"}}

            result = legion.execute_delegation(request, bridge, max_rework=0)
            self.assertEqual("completed", result["execution"]["status"], result)
            self.assertEqual(["plan", "execute", "aggregate"], [phase for _, phase, _ in calls])
            self.assertEqual(3, result["execution"]["role_callbacks_invoked"])
            self.assertFalse(result["execution"]["native_execution_observed"])
            self.assertEqual("not_claimed", result["execution"]["professional_effectiveness"])
            self.assertEqual("final", final_output.read_text(encoding="utf-8"))

    def test_wrong_permission_outside_workspace_and_unassigned_parent_paths_are_rejected(self):
        (self.root / "source.txt").write_text("safe", encoding="utf-8")
        with self.assertRaises(ValueError):
            legion.run_copy(self.root, "wrong", "source.txt", "output.txt", "proposal-is-not-permission")
        with self.assertRaises(ValueError):
            legion.isolated_workspace(execution_baseline.ROOT)
        with self.assertRaises(ValueError):
            legion.isolated_workspace(execution_baseline.ROOT / ".dev/runtime-target/debug")
        with self.assertRaises(ValueError):
            legion.run_copy(self.root, "escape", "source.txt", "../escape.txt", "confirm-isolated-legion-file-copy")
        self.assertFalse((self.root / "output.txt").exists())

    def test_actual_command_returns_nonzero_for_unknown_route_without_configuration_change(self):
        result = subprocess.run([sys.executable, str(execution_baseline.ROOT / "tools/run_legion_task.py"), "route", "unknown"],
                                capture_output=True, encoding="utf-8", timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stderr)["success"])

    def test_followup_manifest_rejects_duplicate_authority_or_activation_before_loading(self):
        manifest = json.loads((legion.PACK / "task-entry.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            pack = Path(temporary)
            path = pack / "task-entry.json"
            with mock.patch.object(legion, "PACK", pack):
                for field in ("installed", "automatic_discovery_enabled", "P7"):
                    changed = dict(manifest, **{field: True})
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "isolated uninstalled"):
                        legion.route("engineering")
                    value = json.dumps(manifest)
                    path.write_text(value[:-1] + "," + json.dumps(field) + ":false}", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Duplicate"):
                        legion.route("engineering")

    def test_malformed_routes_do_not_fall_back_to_all_experts_or_load_external_content(self):
        manifest = json.loads((legion.PACK / "task-entry.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            pack = Path(temporary)
            entry = pack / manifest["entry"]
            entry.parent.mkdir(parents=True)
            entry.write_text("Isolated entry fixture", encoding="utf-8")
            with mock.patch.object(legion, "PACK", pack):
                for routes in ([], {}, {**manifest["routes"], "engineering": None},
                               {**manifest["routes"], "engineering": "../outside.md"},
                               {**manifest["routes"], "chat": "references/media.md"}):
                    (pack / "task-entry.json").write_text(json.dumps(dict(manifest, routes=routes)), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        legion.route("engineering")


if __name__ == "__main__":
    unittest.main()





