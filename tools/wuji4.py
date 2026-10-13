"""Project-local Wuji Legion 4.0 framework shell.

This command is deliberately thin: it validates the isolated package, routes
only the requested guidance, and delegates bounded work to the existing
task entry and Rust/SQLite workspace. It is not a resident service or a
second scheduler.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import stat
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_legion_task
from execution_baseline import load_active
from p6_package_validation import strict_json


ROOT = run_legion_task.ROOT
PACK = run_legion_task.PACK
MANIFEST = PACK / "task-entry.json"
TOOL_MANIFEST = ROOT / "catalog/p4/tool-manifests.json"
CONFIG = Path.home() / ".codex/config.toml"
SOURCE_SKILL = PACK / "skills/wuji-legion-4-0"
CORE_SKILL_FILES = (
    "SKILL.md",
    "references/documents.md",
    "references/engineering.md",
    "references/evolution.md",
    "references/leader-routing.md",
    "references/media.md",
    "references/research.md",
    "references/external-capability-adoption-2026-10-13.md",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict:
    value = strict_json(MANIFEST.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("Framework manifest schema is unsupported")
    return value


def pack_paths(value: dict) -> dict[str, Path]:
    paths = {"entry": value.get("entry")}
    routes = value.get("routes")
    if not isinstance(routes, dict):
        raise ValueError("Framework manifest routes must be an object")
    for kind, relative in routes.items():
        if relative is not None:
            paths[kind] = relative
    resolved: dict[str, Path] = {}
    for name, relative in paths.items():
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError(f"Framework manifest path for {name} must be relative")
        path = (PACK / relative).resolve()
        if not path.is_file() or not path.is_relative_to(PACK.resolve()):
            raise ValueError(f"Framework manifest path for {name} is missing or escapes the pack")
        resolved[name] = path
    return resolved


def _observation_path(path: Path, boundary: Path) -> None:
    relative = path.relative_to(boundary)
    current = boundary
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        metadata = current.lstat()
        if (stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("linked observation path is not admitted")


def _core_skill_inventory(root: Path, boundary: Path) -> dict[str, Path]:
    _observation_path(root, boundary)
    if not root.is_dir():
        raise ValueError("core skill root must be a directory")
    files = {}
    for child in root.iterdir():
        _observation_path(child, boundary)
        if child.name == "references" and child.is_dir():
            for reference in child.iterdir():
                _observation_path(reference, boundary)
                suffix = "/" if reference.is_dir() else ""
                files[f"references/{reference.name}{suffix}"] = reference
        else:
            suffix = "/" if child.is_dir() else ""
            files[f"{child.name}{suffix}"] = child
    return files


def _core_skill_observation(home: Path) -> dict:
    installed = home / ".agents/skills/wuji-legion-codex-4-0"
    result = {"path": str(installed), "source_path": str(SOURCE_SKILL),
              "installed": False, "state": "unknown", "file_hashes": {}}
    expected = set(CORE_SKILL_FILES)
    stage = "source"
    try:
        source_files = _core_skill_inventory(SOURCE_SKILL, ROOT)
        if set(source_files) != expected:
            result.update(state="source_mismatch", reason="source_file_set_mismatch")
            return result
        stage = "installed"
        installed_files = _core_skill_inventory(installed, home)
        if set(installed_files) != expected:
            result.update(state="source_mismatch", reason="installed_file_set_mismatch",
                          missing_files=sorted(expected - set(installed_files)),
                          unexpected_files=sorted(set(installed_files) - expected))
            return result
        for name in CORE_SKILL_FILES:
            if not (stat.S_ISREG(source_files[name].stat().st_mode)
                    and stat.S_ISREG(installed_files[name].stat().st_mode)):
                raise ValueError("core skill entries must be regular files")
            source_hash = digest(source_files[name])
            installed_hash = digest(installed_files[name])
            result["file_hashes"][name] = {"source_sha256": source_hash,
                                         "installed_sha256": installed_hash,
                                         "matches": source_hash == installed_hash}
        result["installed"] = all(item["matches"] for item in result["file_hashes"].values())
        result["state"] = "source_match" if result["installed"] else "source_mismatch"
    except FileNotFoundError:
        result.update(state="missing" if stage == "installed" else "source_mismatch",
                      reason=f"{stage}_path_missing")
    except ValueError:
        result.update(state="invalid_path", reason=f"{stage}_path_not_admitted")
    except OSError:
        result.update(state="unknown", reason=f"{stage}_observation_unavailable")
    return result


def _global_entry_observation(home: Path) -> dict:
    path = home / ".codex/AGENTS.md"
    result = {"path": str(path), "state": "unknown", "default_entry_rule_present": None,
              "white_hat_rule_present": None, "content_exported": False,
              "new_chat_behavior": "unverified"}
    try:
        _observation_path(path, home)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("global entry must be a regular file")
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        version_present = "无极军团" in text and "4.0" in text
        result.update(
            state="observed_rule_text_only",
            default_entry_rule_present=version_present and any(
                "默认" in line and ("入口" in line or "新对话" in line) for line in lines),
            white_hat_rule_present=version_present and any(
                "白帽" in line and any(marker in line for marker in ("内置", "核对", "判断", "通路"))
                for line in lines),
        )
    except FileNotFoundError:
        result.update(state="missing", default_entry_rule_present=False, white_hat_rule_present=False)
    except UnicodeError:
        result["state"] = "unknown"
    except ValueError:
        result["state"] = "invalid_path"
    except OSError:
        result["state"] = "unknown"
    return result


def status() -> dict:
    active = load_active()
    value = manifest()
    paths = pack_paths(value)
    home = Path.home()
    core_skill = _core_skill_observation(home)
    global_entry = _global_entry_observation(home)
    return {
        "schema_version": 1,
        "kind": "wuji_legion_4_framework_status",
        "communicator": "aji",
        "product_boundary": "project_local_entry_guidance_and_existing_tool_workflows",
        "active_plan": {"version": active["version"], "sha256": active["sha256"]},
        "entry": {
            "manifest": MANIFEST.relative_to(ROOT).as_posix(),
            "manifest_sha256": digest(MANIFEST),
            "installed": core_skill["installed"],
            "source_policy": {name: value[name] for name in ("installed", "automatic_discovery_enabled", "P7")},
            "core_skill_observation": core_skill,
            "global_agents_observation": global_entry,
            "automatic_discovery_enabled": value["automatic_discovery_enabled"],
            "P7": value["P7"],
            "pack_files": {name: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
                           for name, path in sorted(paths.items())},
        },
        "authority": "existing Rust/SQLite workspace only; no second task database",
        "capabilities": {
            "simple_tasks": "direct",
            "professional_guidance": "on_demand",
            "staff_delegation": "bounded_recipe_selection",
            "expert_catalog": "cold_metadata_only",
            "bounded_local_file_task": "available" if run_legion_task.EXECUTABLE.is_file() else "unavailable",
            "native_model_dispatch": "not_admitted",
            "professional_effectiveness": "not_claimed",
        },
        "runtime": {
            "rust_cli_path": run_legion_task.EXECUTABLE.relative_to(ROOT).as_posix(),
            "rust_cli_present": run_legion_task.EXECUTABLE.is_file(),
            "resident_service": False,
            "global_installation": core_skill["installed"],
            "global_installation_basis": "core_skill_file_set_and_byte_hash_match_only",
        },
        "staff_delegation": {
            "manifest": "catalog/p3/delegation-manifest.json",
            "manifest_sha256": digest(run_legion_task.DELEGATION_MANIFEST),
            "state": "recipe_selection_only",
            "multiple_explicit_subtasks": True,
            "conditional_expert_selection": True,
            "shared_budget": True,
            "parallel_preparation_only": True,
            "return_path": "expert -> leader -> staff -> aji",
            "runtime_admission": False,
        },
        "protected_codex_configuration": {
            "path": str(CONFIG),
            "sha256": None,
            "content_read": False,
            "content_exported": False,
            "modified_by_framework": False,
        },
        "P7": False,
        "shutdown": False,
    }


def doctor() -> dict:
    checks: dict[str, bool] = {}
    details: dict[str, object] = {}
    try:
        active = load_active()
        checks["active_baseline"] = active["version"] == "1.7"
        details["active_baseline"] = {"version": active["version"], "sha256": active["sha256"]}
    except (OSError, TypeError, ValueError, KeyError) as error:
        checks["active_baseline"] = False
        details["active_baseline_error"] = str(error)
    try:
        value = manifest()
        paths = pack_paths(value)
        checks["manifest_policy"] = (value["installed"] is False
                                      and value["automatic_discovery_enabled"] is False
                                      and value["P7"] is False)
        checks["pack_files"] = bool(paths)
        details["pack_files"] = {name: path.relative_to(ROOT).as_posix() for name, path in sorted(paths.items())}
    except (OSError, TypeError, ValueError, KeyError) as error:
        checks["manifest_policy"] = False
        checks["pack_files"] = False
        details["manifest_error"] = str(error)
    checks["rust_cli"] = run_legion_task.EXECUTABLE.is_file()
    checks["delegation_manifest"] = run_legion_task.DELEGATION_MANIFEST.is_file()
    checks["protected_config_readable"] = CONFIG.is_file()
    checks["no_global_installation"] = True
    checks["no_resident_service"] = True
    checks["P7_not_performed"] = True
    checks["shutdown_not_performed"] = True
    return {
        "schema_version": 1,
        "kind": "wuji_legion_4_framework_doctor",
        "passed": all(checks.values()),
        "checks": checks,
        "details": details,
        "authority": "self-check only; no model dispatch, installation or configuration write",
        "P7": False,
        "shutdown": False,
    }


def capabilities() -> dict:
    active = load_active()
    tools = strict_json(TOOL_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(tools.get("tools"), list):
        raise ValueError("Professional tool manifest must contain a tools list")
    entries = []
    for tool in tools["tools"]:
        if not isinstance(tool, dict) or not tool.get("id") or not tool.get("status"):
            raise ValueError("Professional tool manifest contains an invalid entry")
        entries.append({key: tool[key] for key in (
            "id", "owner", "status", "version", "entrypoint", "adapter", "bounded_evidence",
            "reason", "current_health_evidence", "health_basis", "workflow_entrypoint", "workflow_evidence",
            "action_contract", "professional_effectiveness", "runtime_admission") if key in tool})
    return {
        "schema_version": 1,
        "kind": "wuji_legion_4_framework_capabilities",
        "communicator": "aji",
        "active_plan": {"version": active["version"], "sha256": active["sha256"]},
        "source": {"path": TOOL_MANIFEST.relative_to(ROOT).as_posix(), "sha256": digest(TOOL_MANIFEST)},
        "tools": entries,
        "selection_rule": "Use only the task-relevant existing adapter after its action contract and current evidence are checked; no generic dispatch fallback.",
        "professional_effectiveness": "not_claimed_without_matched_artifact_or_holdout",
        "P7": False,
        "shutdown": False,
    }


def _professional_workspace(value: str) -> Path:
    return run_legion_task.isolated_workspace(value)


def _workflow_result(operation: str, module_name: str, workspace: str, output: str | None = None,
                     input_relative: str | None = None) -> dict:
    path = _professional_workspace(workspace)
    module = importlib.import_module(module_name)
    runner = getattr(module, "run", None)
    if not callable(runner):
        raise ValueError(f"Professional adapter {module_name} does not expose run")
    kwargs: dict[str, object] = {"workspace": path}
    if output is not None:
        original_output = path / output
        output_path = original_output.resolve()
        if output_path.parent != path or original_output.is_symlink():
            raise ValueError("Professional receipt must stay directly in the isolated workspace")
        kwargs["output"] = output_path
    if input_relative is not None:
        original_input = path / input_relative
        input_path = original_input.resolve()
        if input_path.parent != path or original_input.is_symlink() or not input_path.is_file():
            raise ValueError("Professional input must be an existing direct child of the isolated workspace")
        kwargs["input_path"] = input_path
    try:
        result = runner(**kwargs)
    except Exception as error:
        retained = getattr(error, "receipt", None)
        if not isinstance(retained, dict):
            raise
        result = retained
    if not isinstance(result, dict):
        raise ValueError("Professional adapter returned a non-object receipt")
    return {"communicator": "aji", "operation": operation, "receipt": result,
            "professional_effectiveness": "not_claimed", "P7": False, "shutdown": False}


def _media_workflow_result(workspace: str, input_relative: str, receipt_name: str | None = None) -> dict:
    path = _professional_workspace(workspace)
    original_input = path / input_relative
    input_path = original_input.resolve()
    if input_path.parent != path or original_input.is_symlink() or not input_path.is_file():
        raise ValueError("Professional input must be an existing direct child of the isolated workspace")
    module = importlib.import_module("adapters.p4.media_workflow")
    source = (module.DEFAULT_COMFY_INPUT / input_path.name).resolve(strict=True)
    if module.sha256_file(source) != module.sha256_file(input_path):
        raise ValueError("Declared media input does not match the existing ComfyUI input")
    original_receipt = path / (receipt_name or "media-workflow-receipt.json")
    receipt = original_receipt.resolve()
    if receipt.parent != path or original_receipt.is_symlink() or receipt.suffix != ".json" or receipt.exists():
        raise ValueError("Professional receipt must be a new direct-child JSON file")
    result = module.run(workspace=path, input_path=source, receipt=receipt)
    if not isinstance(result, dict):
        raise ValueError("Media adapter returned a non-object receipt")
    return {"communicator": "aji", "operation": "isolated-comfyui-ffmpeg-media", "receipt": result,
            "professional_effectiveness": "not_claimed", "P7": False, "shutdown": False}


def _office_document_workflow_result(workspace: str, request_json: str, receipt_name: str | None = None) -> dict:
    path = _professional_workspace(workspace)
    try:
        request = json.loads(request_json)
    except json.JSONDecodeError as error:
        raise ValueError("Office document request must be valid JSON") from error
    original_receipt = path / (receipt_name or "office-document-receipt.json")
    receipt = original_receipt.resolve()
    if receipt.parent != path or original_receipt.is_symlink() or receipt.suffix != ".json" or receipt.exists():
        raise ValueError("Office document receipt must be a new direct-child JSON file")
    module = importlib.import_module("adapters.p4.office_document_workflow")
    result = module.run(workspace=path, request=request, output=receipt)
    return {"communicator": "aji", "operation": "isolated-office-document", "receipt": result,
            "professional_effectiveness": "not_claimed", "P7": False, "shutdown": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Wuji Legion 4.0 project-local framework shell")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("doctor")
    commands.add_parser("capabilities")
    route_parser = commands.add_parser("route")
    route_parser.add_argument("kind")
    delegation_parser = commands.add_parser("delegate")
    delegation_parser.add_argument("request_json")
    copy_parser = commands.add_parser("run-copy")
    copy_parser.add_argument("workspace")
    copy_parser.add_argument("task")
    copy_parser.add_argument("source")
    copy_parser.add_argument("output")
    copy_parser.add_argument("confirmation")
    summary_parser = commands.add_parser("summary")
    summary_parser.add_argument("workspace")
    summary_parser.add_argument("task")
    office_parser = commands.add_parser("run-office")
    office_parser.add_argument("workspace")
    office_parser.add_argument("confirmation")
    office_parser.add_argument("--output", default=None)
    media_parser = commands.add_parser("run-media")
    media_parser.add_argument("workspace")
    media_parser.add_argument("input")
    media_parser.add_argument("confirmation")
    media_parser.add_argument("--output", default=None)
    video_parser = commands.add_parser("run-video")
    video_parser.add_argument("workspace")
    video_parser.add_argument("input")
    video_parser.add_argument("confirmation")
    video_parser.add_argument("--receipt", default=None)
    office_document_parser = commands.add_parser("run-office-doc")
    office_document_parser.add_argument("workspace")
    office_document_parser.add_argument("request_json")
    office_document_parser.add_argument("confirmation")
    office_document_parser.add_argument("--receipt", default=None)
    arguments = parser.parse_args()
    try:
        if arguments.command == "status":
            result = status()
        elif arguments.command == "doctor":
            result = doctor()
        elif arguments.command == "capabilities":
            result = capabilities()
        elif arguments.command == "route":
            result = run_legion_task.route(arguments.kind)
        elif arguments.command == "delegate":
            request_path = Path(arguments.request_json).resolve(strict=True)
            if not request_path.is_file() or request_path.stat().st_size > 32 * 1024:
                raise ValueError("Delegation request must be a bounded JSON file")
            result = run_legion_task.delegate(strict_json(request_path.read_text(encoding="utf-8")))
        elif arguments.command == "run-copy":
            result = run_legion_task.run_copy(arguments.workspace, arguments.task, arguments.source,
                                              arguments.output, arguments.confirmation)
        elif arguments.command == "run-office":
            if arguments.confirmation != "confirm-isolated-officecli-task":
                raise ValueError("An explicit scoped confirmation is required for OfficeCLI")
            result = _workflow_result("isolated-officecli-editable-pptx", "adapters.p4.officecli_workflow",
                                      arguments.workspace, arguments.output)
        elif arguments.command == "run-media":
            if arguments.confirmation != "confirm-isolated-media-task":
                raise ValueError("An explicit scoped confirmation is required for media adapters")
            result = _media_workflow_result(arguments.workspace, arguments.input, arguments.output)
        elif arguments.command == "run-video":
            if arguments.confirmation != "confirm-isolated-video-task":
                raise ValueError("An explicit scoped confirmation is required for video")
            result = _workflow_result("isolated-png-to-video", "adapters.p4.ffmpeg_workflow",
                                      arguments.workspace, arguments.receipt, arguments.input)
        elif arguments.command == "run-office-doc":
            if arguments.confirmation != "confirm-isolated-office-document-task":
                raise ValueError("An explicit scoped confirmation is required for Office document tasks")
            result = _office_document_workflow_result(arguments.workspace, arguments.request_json, arguments.receipt)
        else:
            result = run_legion_task.call("execution-summary",
                                          run_legion_task.isolated_workspace(arguments.workspace), arguments.task)
        print(json.dumps(result, ensure_ascii=False))
        receipt = result.get("receipt") if isinstance(result, dict) else None
        if isinstance(receipt, dict):
            succeeded = (receipt.get("passed") is True or
                         receipt.get("result_state") == "completed_bounded_task")
            if not succeeded:
                raise SystemExit(1)
        if arguments.command == "doctor" and not result["passed"]:
            raise SystemExit(1)
    except (ValueError, OSError, KeyError, TypeError, SystemExit) as error:
        if isinstance(error, SystemExit):
            raise
        print(json.dumps({"success": False, "error": str(error), "P7": False}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()

