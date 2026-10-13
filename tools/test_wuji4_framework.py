import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import wuji4 as framework


class Wuji4FrameworkTests(unittest.TestCase):
    def status_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        source = root / "legion/skills/wuji-legion-4-0"
        home = root / "home"
        installed = home / ".agents/skills/wuji-legion-codex-4-0"
        agents = home / ".codex/AGENTS.md"
        for name in framework.CORE_SKILL_FILES:
            for base in (source, installed):
                path = base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"fixture core file: {name}\n".encode("utf-8"))
        agents.parent.mkdir(parents=True)
        agents.write_text("# 无极军团 4.0\n新对话默认遵守4.0入口。\n白帽是阿极的内置判断。\n", encoding="utf-8")
        manifest = root / "legion/task-entry.json"
        manifest.write_text(json.dumps({"schema_version": 1, "entry": "skills/wuji-legion-4-0/SKILL.md",
                                        "routes": {}, "installed": False,
                                        "automatic_discovery_enabled": False, "P7": False}), encoding="utf-8")
        delegation = root / "delegation-manifest.json"
        delegation.write_text("{}", encoding="utf-8")
        for patcher in (
            mock.patch.object(framework, "ROOT", root),
            mock.patch.object(framework, "PACK", root / "legion"),
            mock.patch.object(framework, "MANIFEST", manifest),
            mock.patch.object(framework, "SOURCE_SKILL", source),
            mock.patch.object(framework, "CONFIG", home / ".codex/config.toml"),
            mock.patch.object(framework, "load_active", return_value={"version": "1.7", "sha256": "fixture"}),
            mock.patch.object(framework.run_legion_task, "EXECUTABLE", root / "wuji4.exe"),
            mock.patch.object(framework.run_legion_task, "DELEGATION_MANIFEST", delegation),
            mock.patch.object(Path, "home", return_value=home),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        return source, installed, agents

    def test_office_failed_state_without_status_exits_nonzero_and_retains_receipt(self):
        failed = {"receipt": {"state": "failed_evidence_retained", "passed": False,
                              "errors": [{"stage": "create", "message": "failure retained"}]}, "P7": False}
        output = io.StringIO()
        arguments = ["wuji4.py", "run-office", "unused-workspace", "confirm-isolated-officecli-task"]
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(framework, "_workflow_result", return_value=failed), redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                framework.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue()), failed)

    def test_confirmation_is_checked_before_professional_execution(self):
        for arguments in (["run-office", "unused-workspace", "not-confirmed"],
                          ["run-video", "unused-workspace", "source.png", "not-confirmed"],
                          ["run-office-doc", "unused-workspace", "{}", "not-confirmed"]):
            with self.subTest(arguments=arguments), mock.patch.object(sys, "argv", ["wuji4.py", *arguments]):
                with mock.patch.object(framework, "_workflow_result") as execute, mock.patch("sys.stderr", io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        framework.main()
                self.assertEqual(caught.exception.code, 1)
                execute.assert_not_called()

    def test_office_document_dispatch_binds_request_and_confirmation(self):
        result = {"receipt": {"passed": True, "result_state": "completed_bounded_task"}, "P7": False}
        arguments = ["wuji4.py", "run-office-doc", "workspace", '{"schema_version":1}',
                     "confirm-isolated-office-document-task", "--receipt", "receipt.json"]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
                framework, "_office_document_workflow_result", return_value=result) as execute, redirect_stdout(output):
            framework.main()
        execute.assert_called_once_with("workspace", '{"schema_version":1}', "receipt.json")
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_video_result_requires_completion_and_returns_failure_nonzero(self):
        for passed in (True, False):
            result = {"receipt": {"passed": passed,
                                 "result_state": "completed_bounded_task" if passed else "failed_evidence_retained"},
                      "P7": False}
            arguments = ["wuji4.py", "run-video", "unused-workspace", "source.png", "confirm-isolated-video-task"]
            output = io.StringIO()
            with self.subTest(passed=passed), mock.patch.object(sys, "argv", arguments), mock.patch.object(
                    framework, "_workflow_result", return_value=result) as execute, redirect_stdout(output):
                if passed:
                    framework.main()
                else:
                    with self.assertRaises(SystemExit) as caught:
                        framework.main()
                    self.assertEqual(caught.exception.code, 1)
            self.assertEqual(json.loads(output.getvalue()), result)
            execute.assert_called_once_with("isolated-png-to-video", "adapters.p4.ffmpeg_workflow",
                                            "unused-workspace", None, "source.png")

    def test_status_separates_frozen_source_policy_from_matching_installed_core(self):
        source, installed, agents = self.status_fixture()
        result = framework.status()

        self.assertEqual(result["communicator"], "aji")
        self.assertEqual(result["active_plan"]["version"], "1.7")
        self.assertTrue(result["entry"]["installed"])
        self.assertFalse(result["entry"]["source_policy"]["installed"])
        self.assertFalse(result["entry"]["source_policy"]["automatic_discovery_enabled"])
        self.assertFalse(result["entry"]["source_policy"]["P7"])
        self.assertFalse(result["entry"]["automatic_discovery_enabled"])
        self.assertFalse(result["entry"]["P7"])
        self.assertTrue(result["runtime"]["global_installation"])
        self.assertEqual(result["runtime"]["global_installation_basis"],
                         "core_skill_file_set_and_byte_hash_match_only")
        observed = result["entry"]["core_skill_observation"]
        self.assertEqual(observed["state"], "source_match")
        self.assertEqual(observed["path"], str(installed))
        self.assertEqual(observed["source_path"], str(source))
        self.assertEqual(set(observed["file_hashes"]), set(framework.CORE_SKILL_FILES))
        for item in observed["file_hashes"].values():
            self.assertEqual(item["source_sha256"], item["installed_sha256"])
            self.assertTrue(item["matches"])
        entry = result["entry"]["global_agents_observation"]
        self.assertEqual(entry["path"], str(agents))
        self.assertTrue(entry["default_entry_rule_present"])
        self.assertTrue(entry["white_hat_rule_present"])
        self.assertEqual(entry["new_chat_behavior"], "unverified")
        self.assertFalse(entry["content_exported"])
        self.assertFalse(result["protected_codex_configuration"]["content_read"])
        self.assertIsNone(result["protected_codex_configuration"]["sha256"])
        self.assertFalse(result["P7"])
        self.assertEqual(result["authority"], "existing Rust/SQLite workspace only; no second task database")

    def test_status_missing_or_extra_core_files_do_not_count_as_installed(self):
        _, installed, _ = self.status_fixture()
        target = installed / "references/research.md"
        content = target.read_bytes()
        target.unlink()
        result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        self.assertFalse(result["runtime"]["global_installation"])
        self.assertEqual(result["entry"]["core_skill_observation"]["missing_files"], ["references/research.md"])
        target.write_bytes(content)
        (installed / "extra.txt").write_bytes(b"extra")
        result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        self.assertEqual(result["entry"]["core_skill_observation"]["unexpected_files"], ["extra.txt"])
        self.assertEqual(result["entry"]["core_skill_observation"]["state"], "source_mismatch")

    def test_status_stale_core_bytes_do_not_count_as_installed(self):
        _, installed, _ = self.status_fixture()
        (installed / "SKILL.md").write_bytes(b"stale core")
        result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        observed = result["entry"]["core_skill_observation"]
        self.assertEqual(observed["state"], "source_mismatch")
        self.assertFalse(observed["file_hashes"]["SKILL.md"]["matches"])

    def test_status_missing_installed_root_is_not_an_installation(self):
        _, installed, _ = self.status_fixture()
        installed.rename(installed.with_name("unrelated-core"))
        result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        self.assertEqual(result["entry"]["core_skill_observation"]["state"], "missing")

    def test_status_unexpected_nested_directory_is_not_traversed_or_installed(self):
        _, installed, _ = self.status_fixture()
        (installed / "references/extra").mkdir()
        result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        self.assertEqual(result["entry"]["core_skill_observation"]["unexpected_files"], ["references/extra/"])

    def test_status_source_file_set_mismatch_cannot_be_installed(self):
        source, _, _ = self.status_fixture()
        (source / "references/leader-routing.md").unlink()
        result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        self.assertEqual(result["entry"]["core_skill_observation"]["reason"], "source_file_set_mismatch")

    def test_status_observation_permission_failure_is_unknown_not_installed(self):
        _, installed, _ = self.status_fixture()
        original = Path.iterdir

        def denied(path):
            if path == installed:
                raise PermissionError("fixture permission failure")
            return original(path)

        with mock.patch.object(Path, "iterdir", denied):
            result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        self.assertEqual(result["entry"]["core_skill_observation"]["state"], "unknown")

    def test_status_linked_core_path_is_rejected_without_reading_target(self):
        _, installed, _ = self.status_fixture()
        original = Path.lstat

        def linked(path):
            if path == installed.parent:
                return types.SimpleNamespace(st_mode=0, st_file_attributes=0x400)
            return original(path)

        with mock.patch.object(Path, "lstat", linked), mock.patch.object(framework, "digest", wraps=framework.digest) as hashed:
            result = framework.status()
        self.assertFalse(result["entry"]["installed"])
        self.assertEqual(result["entry"]["core_skill_observation"]["state"], "invalid_path")
        self.assertFalse(any(call.args[0].is_relative_to(installed) for call in hashed.call_args_list))

    def test_status_global_rule_observation_never_claims_new_chat_behavior(self):
        _, _, agents = self.status_fixture()
        agents.write_text("# 无极军团 4.0\n手动入口。\n", encoding="utf-8")
        result = framework.status()
        observed = result["entry"]["global_agents_observation"]
        self.assertTrue(result["entry"]["installed"])
        self.assertFalse(observed["default_entry_rule_present"])
        self.assertFalse(observed["white_hat_rule_present"])
        self.assertEqual(observed["new_chat_behavior"], "unverified")
        agents.unlink()
        observed = framework.status()["entry"]["global_agents_observation"]
        self.assertEqual(observed["state"], "missing")
        self.assertFalse(observed["default_entry_rule_present"])
        agents.write_bytes(b"\xff")
        observed = framework.status()["entry"]["global_agents_observation"]
        self.assertEqual(observed["state"], "unknown")
        self.assertIsNone(observed["default_entry_rule_present"])

    def test_status_reads_only_declared_core_and_agents_not_configuration(self):
        source, installed, agents = self.status_fixture()
        allowed = {framework.MANIFEST, framework.run_legion_task.DELEGATION_MANIFEST, agents}
        allowed.update(base / name for base in (source, installed) for name in framework.CORE_SKILL_FILES)
        read_bytes = Path.read_bytes
        read_text = Path.read_text
        iterdir = Path.iterdir

        def bounded_bytes(path):
            self.assertIn(path, allowed)
            return read_bytes(path)

        def bounded_text(path, *args, **kwargs):
            self.assertIn(path, allowed)
            return read_text(path, *args, **kwargs)

        def bounded_inventory(path):
            self.assertIn(path, {source, source / "references", installed, installed / "references"})
            return iterdir(path)

        with mock.patch.object(Path, "read_bytes", bounded_bytes), mock.patch.object(
                Path, "read_text", bounded_text), mock.patch.object(Path, "iterdir", bounded_inventory):
            result = framework.status()
        self.assertTrue(result["entry"]["installed"])
        self.assertFalse(result["protected_codex_configuration"]["content_read"])

    def test_doctor_checks_project_pack_and_existing_isolated_rust_cli_without_config_write(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        config = Path(temporary.name) / "config.toml"
        config.write_bytes(b"fixture configuration")
        patcher = mock.patch.object(framework, "CONFIG", config)
        patcher.start()
        self.addCleanup(patcher.stop)
        before_content = framework.CONFIG.read_bytes()
        before_mtime = framework.CONFIG.stat().st_mtime_ns

        result = framework.doctor()

        self.assertTrue(result["passed"], result)
        self.assertTrue(result["checks"]["active_baseline"])
        self.assertTrue(result["checks"]["manifest_policy"])
        self.assertTrue(result["checks"]["pack_files"])
        self.assertTrue(result["checks"]["rust_cli"])
        self.assertTrue(framework.run_legion_task.EXECUTABLE.is_file())
        self.assertIn("entry", result["details"]["pack_files"])
        self.assertIn("engineering", result["details"]["pack_files"])
        self.assertEqual(before_content, framework.CONFIG.read_bytes())
        self.assertEqual(before_mtime, framework.CONFIG.stat().st_mtime_ns)
        self.assertFalse(result["P7"])

    def test_route_loads_only_needed_chat_or_professional_context(self):
        chat = framework.run_legion_task.route("chat")
        professional = framework.run_legion_task.route("engineering")

        self.assertTrue(chat["direct_answer"])
        self.assertFalse(professional["direct_answer"])
        self.assertEqual(len(chat["context"]), 1)
        self.assertEqual(len(professional["context"]), 2)
        self.assertEqual(professional["context"][0], chat["context"][0])
        self.assertTrue(professional["context"][1]["path"].endswith("references/engineering.md"))
        self.assertFalse(professional["execution_authority"])

    def test_delegate_command_exposes_staff_handoff_without_changing_codex_config(self):
        request = {
            "task_id": "cli-meta-route",
            "goal": "检查元指令变更路径",
            "domain": "prompt_meta",
            "typed_intents": ["meta_instruction"],
            "inputs": ["visible-agents-md"],
            "deliverables": ["route-receipt"],
            "acceptance_ids": ["goal-explicit"],
        }
        with tempfile.TemporaryDirectory(dir=framework.ROOT / ".dev" / "core-test-workspaces") as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            config = Path(temporary) / "config.toml"
            config.write_bytes(b"fixture configuration")
            patcher = mock.patch.object(framework, "CONFIG", config)
            patcher.start()
            self.addCleanup(patcher.stop)
            before_content = framework.CONFIG.read_bytes()
            arguments = ["wuji4.py", "delegate", str(request_path)]
            output = io.StringIO()
            with mock.patch.object(sys, "argv", arguments), redirect_stdout(output):
                framework.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["staff_decision"], "recipe_selected")
            self.assertEqual(result["return_path"], ["expert", "leader", "staff", "aji"])
            self.assertFalse(result["runtime_admission"])
            self.assertEqual(before_content, framework.CONFIG.read_bytes())

    def test_capabilities_reads_existing_tool_contracts_without_generic_dispatch(self):
        result = framework.capabilities()

        self.assertEqual(result["communicator"], "aji")
        self.assertEqual(result["active_plan"]["version"], "1.7")
        self.assertTrue(result["tools"])
        self.assertIn("officecli", {tool["id"] for tool in result["tools"]})
        self.assertIn("no generic dispatch fallback", result["selection_rule"])
        self.assertFalse(result["P7"])

    def test_unknown_route_is_rejected_without_all_expert_fallback(self):
        with self.assertRaisesRegex(ValueError, "no all-expert fallback"):
            framework.run_legion_task.route("all-experts")

    def test_run_copy_requires_confirmation_and_delegates_existing_workspace(self):
        with tempfile.TemporaryDirectory(dir=framework.ROOT / ".dev" / "core-test-workspaces") as temporary:
            workspace = Path(temporary)
            (workspace / "source.txt").write_text("framework delegation test", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit scoped confirmation"):
                framework.run_legion_task.run_copy(workspace, "framework-copy", "source.txt", "result.txt", "not-confirmed")
            self.assertFalse((workspace / ".wuji4").exists())

            result = framework.run_legion_task.run_copy(
                workspace, "framework-copy", "source.txt", "result.txt", "confirm-isolated-legion-file-copy"
            )
            self.assertTrue(result["completed"])
            self.assertTrue((workspace / ".wuji4" / "state.sqlite").is_file())
            self.assertEqual((workspace / "source.txt").read_bytes(), (workspace / "result.txt").read_bytes())

            arguments = [
                "wuji4.py",
                "run-copy",
                str(workspace),
                "framework-copy-replay",
                "source.txt",
                "result.txt",
                "confirm-isolated-legion-file-copy",
            ]
            with mock.patch.object(framework.run_legion_task, "run_copy", return_value={"completed": True}) as delegated:
                output = io.StringIO()
                with mock.patch.object(sys, "argv", arguments), redirect_stdout(output):
                    framework.main()

            delegated.assert_called_once_with(
                str(workspace), "framework-copy-replay", "source.txt", "result.txt", "confirm-isolated-legion-file-copy"
            )
            self.assertEqual(json.loads(output.getvalue()), {"completed": True})

    def test_professional_workflow_wrapper_keeps_receipt_and_input_inside_workspace(self):
        with tempfile.TemporaryDirectory(dir=framework.ROOT / ".dev" / "core-test-workspaces") as temporary:
            workspace = Path(temporary)
            input_path = workspace / "input.png"
            input_path.write_bytes(b"declared input")
            module = types.ModuleType("test_professional_workflow")
            calls = []

            def run(*, workspace, output=None, input_path=None):
                calls.append((workspace, output, input_path))
                return {"status": "bounded_real_probe_passed"}

            module.run = run
            with mock.patch.dict(sys.modules, {module.__name__: module}):
                result = framework._workflow_result("test-operation", module.__name__, str(workspace),
                                                    "receipt.json", "input.png")

            self.assertEqual(result["operation"], "test-operation")
            self.assertEqual(result["receipt"]["status"], "bounded_real_probe_passed")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], workspace)
            self.assertEqual(calls[0][1], workspace / "receipt.json")
            self.assertEqual(calls[0][2], input_path)

    def test_professional_workflow_wrapper_rejects_nested_receipt_and_missing_input(self):
        with tempfile.TemporaryDirectory(dir=framework.ROOT / ".dev" / "core-test-workspaces") as temporary:
            workspace = Path(temporary)
            module = types.ModuleType("test_professional_workflow_rejection")
            module.run = lambda **kwargs: {"status": "unexpected"}
            with mock.patch.dict(sys.modules, {module.__name__: module}):
                with self.assertRaisesRegex(ValueError, "receipt"):
                    framework._workflow_result("test-operation", module.__name__, str(workspace), "nested/receipt.json")
                with self.assertRaisesRegex(ValueError, "input"):
                    framework._workflow_result("test-operation", module.__name__, str(workspace), input_relative="missing.png")


if __name__ == "__main__":
    unittest.main()
