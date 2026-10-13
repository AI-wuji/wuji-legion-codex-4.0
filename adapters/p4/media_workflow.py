from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable
import urllib.error
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORE = ROOT / ".dev/runtime-target/debug/wuji4.exe"
DEFAULT_COMFY_ENDPOINT = "http://127.0.0.1:8898"
DEFAULT_COMFY_INPUT = Path("E:/COMFYUI_dapao1/ComfyUI/input")
DEFAULT_COMFY_OUTPUT = Path("E:/COMFYUI_dapao1/ComfyUI/output")
DEFAULT_FFMPEG = Path(
    "E:/COMFYUI_dapao1/python_dapao313/Lib/site-packages/"
    "imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
)
PINNED_FFMPEG_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"
MAX_PROCESS_OUTPUT = 64 * 1024
MAX_HTTP_RESPONSE = 4 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class WorkflowFailure(RuntimeError):
    def __init__(self, code: str, message: str, details: object | None = None, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.exit_code = exit_code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_or_missing(path: Path) -> str | None:
    try:
        return sha256_file(path) if path.is_file() else None
    except OSError:
        return None


def confined(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise WorkflowFailure("path_scope_denied", f"{label} escapes its declared root", {
            "path": str(resolved),
            "root": str(root.resolve()),
        }) from error
    return resolved


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise WorkflowFailure("input_not_png", "declared input is not a PNG file", {"path": str(path)})
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width <= 0 or height <= 0:
        raise WorkflowFailure("input_png_shape_invalid", "declared PNG has invalid dimensions", {
            "width": width,
            "height": height,
        })
    return width, height


def bounded_text(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    if len(text) > MAX_PROCESS_OUTPUT:
        return text[:MAX_PROCESS_OUTPUT] + "...[truncated]"
    return text


def build_workflow(input_name: str, filename_prefix: str) -> dict[str, dict[str, object]]:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": input_name}},
        "2": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["1", 0],
                "upscale_method": "nearest-exact",
                "width": 64,
                "height": 64,
                "crop": "disabled",
            },
        },
        "3": {
            "class_type": "SaveImage",
            "inputs": {"images": ["2", 0], "filename_prefix": filename_prefix},
        },
    }


def append_process_command(
    receipt: dict[str, object],
    phase: str,
    argv: list[object],
    cwd: Path,
    timeout: float,
    parse_json: bool = False,
    before_dispatch: Callable[[], None] | None = None,
) -> object | None:
    started = time.monotonic()
    normalized = [str(item) for item in argv]
    record: dict[str, object] = {
        "kind": "process",
        "phase": phase,
        "argv": normalized,
        "cwd": str(cwd),
        "exit_code": None,
        "owned_process_exit_observed": False,
    }
    try:
        environment = dict(os.environ)
        environment.pop("FFREPORT", None)
        if before_dispatch is not None:
            try:
                before_dispatch()
            except Exception as error:
                record.update({
                    "error": str(error),
                    "dispatch_guard": "rejected",
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                })
                receipt["commands"].append(record)
                raise
        completed = subprocess.run(
            normalized,
            cwd=cwd,
            env=environment,
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as error:
        record.update({"error": str(error), "duration_ms": round((time.monotonic() - started) * 1000, 2)})
        receipt["commands"].append(record)
        raise WorkflowFailure("executable_unavailable", f"{phase} executable is unavailable", {
            "argv": normalized,
            "error": str(error),
        }) from error
    except subprocess.TimeoutExpired as error:
        record.update({"error": "timeout", "duration_ms": round((time.monotonic() - started) * 1000, 2)})
        receipt["commands"].append(record)
        raise WorkflowFailure("command_timeout", f"{phase} exceeded its bounded timeout", {
            "argv": normalized,
            "timeout_seconds": timeout,
        }) from error

    if len(completed.stdout) + len(completed.stderr) > MAX_PROCESS_OUTPUT:
        retained = []
        for stream_name, content in (("stdout", completed.stdout), ("stderr", completed.stderr)):
            log_path = cwd / f"{phase}-{uuid.uuid4().hex}-{stream_name}.log"
            with log_path.open("xb") as handle:
                handle.write(content)
            retained.append({"stream": stream_name, "path": str(log_path), "sha256": sha256_file(log_path),
                             "bytes": len(content)})
        record.update(exit_code=completed.returncode, owned_process_exit_observed=True, retained_output=retained)
        receipt["commands"].append(record)
        raise WorkflowFailure("command_output_exceeded", f"{phase} output retained in full; response bound exceeded")
    record.update({
        "exit_code": completed.returncode,
        "owned_process_exit_observed": True,
        "stdout": bounded_text(completed.stdout),
        "stderr": bounded_text(completed.stderr),
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
    })
    receipt["commands"].append(record)
    if completed.returncode != 0:
        raise WorkflowFailure("command_failed", f"{phase} returned a non-zero exit", {
            "argv": normalized,
            "exit_code": completed.returncode,
            "stderr": bounded_text(completed.stderr),
        })
    if not parse_json:
        return None
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowFailure("command_invalid_json", f"{phase} did not return JSON", {
            "stdout": bounded_text(completed.stdout),
        }) from error


def core_call(receipt: dict[str, object], core: Path, workspace: Path, phase: str, *arguments: object) -> object:
    result = append_process_command(receipt, phase, [core, *arguments], workspace, 30, parse_json=True)
    if result is None:
        raise WorkflowFailure("core_contract_missing_response", f"{phase} returned no contract response")
    return result


def append_http_command(
    receipt: dict[str, object],
    phase: str,
    endpoint: str,
    method: str,
    payload: object | None,
    timeout: float,
) -> object:
    url = endpoint.rstrip("/") + "/" + phase
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    started = time.monotonic()
    record: dict[str, object] = {
        "kind": "http",
        "phase": phase,
        "method": method,
        "url": url,
        "http_status": None,
        "duration_ms": None,
    }
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_HTTP_RESPONSE + 1)
            record["http_status"] = response.status
    except urllib.error.HTTPError as error:
        raw = error.read(MAX_PROCESS_OUTPUT)
        record.update({
            "http_status": error.code,
            "response": bounded_text(raw),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        })
        receipt["commands"].append(record)
        raise WorkflowFailure("comfyui_http_error", f"ComfyUI {phase} returned HTTP {error.code}", {
            "url": url,
            "http_status": error.code,
            "response": bounded_text(raw),
        }) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        record.update({
            "error": str(error),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        })
        receipt["commands"].append(record)
        raise WorkflowFailure("comfyui_unavailable", "ComfyUI endpoint is unavailable", {
            "url": url,
            "error": str(error),
        }) from error

    if len(raw) > MAX_HTTP_RESPONSE:
        record.update({"error": "response exceeds bounded size", "duration_ms": round((time.monotonic() - started) * 1000, 2)})
        receipt["commands"].append(record)
        raise WorkflowFailure("comfyui_response_too_large", f"ComfyUI {phase} response exceeds bound")
    record.update({
        "response": bounded_text(raw),
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
    })
    receipt["commands"].append(record)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowFailure("comfyui_invalid_json", f"ComfyUI {phase} did not return JSON", {
            "url": url,
            "response": bounded_text(raw),
        }) from error


def observed_comfy_version(stats: object) -> str | None:
    if not isinstance(stats, dict):
        return None
    for key in ("version", "comfyui_version"):
        value = stats.get(key)
        if isinstance(value, str):
            return value
    system = stats.get("system")
    if isinstance(system, dict):
        for key in ("version", "comfyui_version"):
            value = system.get(key)
            if isinstance(value, str):
                return value
    return None


def node_is_present(value: object, node: str) -> bool:
    if not isinstance(value, dict):
        return False
    if node in value:
        return True
    return all(key in value for key in ("input", "output", "name"))


def output_image_path(history: object, output_root: Path) -> tuple[Path, dict[str, object]]:
    if not isinstance(history, dict) or not history:
        raise WorkflowFailure("comfyui_history_empty", "ComfyUI completed without history output")
    entry = next(iter(history.values()))
    if not isinstance(entry, dict):
        raise WorkflowFailure("comfyui_history_invalid", "ComfyUI history shape is invalid")
    outputs = entry.get("outputs")
    node_output = outputs.get("3") if isinstance(outputs, dict) else None
    images = node_output.get("images") if isinstance(node_output, dict) else None
    image = images[0] if isinstance(images, list) and images else None
    if not isinstance(image, dict) or not isinstance(image.get("filename"), str):
        raise WorkflowFailure("comfyui_output_missing", "ComfyUI SaveImage produced no declared PNG")
    if image.get("type") not in (None, "output"):
        raise WorkflowFailure("comfyui_output_not_persistent", "ComfyUI output is not a persistent output file", image)
    filename = Path(image["filename"])
    subfolder = Path(str(image.get("subfolder", "")))
    source = confined(output_root / subfolder / filename, output_root, "ComfyUI output")
    if not source.is_file():
        raise WorkflowFailure("comfyui_output_missing", "ComfyUI declared output file does not exist", {
            "path": str(source),
            "image": image,
        })
    return source, image


def artifact(path: Path, kind: str) -> dict[str, object]:
    result: dict[str, object] = {
        "kind": kind,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if path.suffix.lower() == ".png":
        result["png_dimensions"] = dict(zip(("width", "height"), png_dimensions(path)))
    return result


def write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_isolated_workspace(workspace: Path, run_id: str) -> Path:
    base = confined(workspace, ROOT / ".dev", "media workspace")
    if not base.is_dir() or base == (ROOT / ".dev").resolve():
        raise WorkflowFailure("workspace_invalid", "media workspace must be an existing directory below .dev", {
            "path": str(base),
        })
    isolated = base / f"media-{run_id}"
    isolated.mkdir(parents=False, exist_ok=False)
    return isolated


def execute(
    input_path: Path,
    workspace: Path,
    receipt_path: Path,
    *,
    comfy_endpoint: str = DEFAULT_COMFY_ENDPOINT,
    comfy_input_root: Path = DEFAULT_COMFY_INPUT,
    comfy_output_root: Path = DEFAULT_COMFY_OUTPUT,
    ffmpeg: Path = DEFAULT_FFMPEG,
    core: Path = DEFAULT_CORE,
    output_path: Path | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, object]]:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:12]}"
    codex_config = Path.home() / ".codex/config.toml"
    receipt: dict[str, object] = {
        "schema_version": 1,
        "workflow": "bounded-comfyui-image-scale-to-mp4",
        "run_id": run_id,
        "status": "running",
        "result_state": "running",
        "process_exit_code": None,
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "input": {"declared_path": str(input_path.resolve())},
        "isolation": {"project_root": str(ROOT), "workspace": None, "workspace_confined_to": str((ROOT / ".dev").resolve())},
        "versions": {},
        "workflow_graph": None,
        "commands": [],
        "artifacts": {},
        "failure": None,
        "configuration_protection": {
            "path": str(codex_config),
            "before_sha256": sha256_or_missing(codex_config),
            "after_sha256": None,
            "unchanged": None,
        },
        "audio_protection": {"audio_device_opened": False, "audio_configuration_changed": False},
        "professional_effectiveness": "not_claimed",
        "native_or_professional_effectiveness": False,
        "P7": False,
    }

    try:
        if receipt["configuration_protection"]["before_sha256"] is None:
            raise WorkflowFailure("protected_configuration_unreadable", "Protected configuration cannot be verified")
        source = input_path.resolve()
        input_root = comfy_input_root.resolve()
        output_root = comfy_output_root.resolve()
        if not source.is_file():
            raise WorkflowFailure("input_missing", "declared PNG input does not exist", {"path": str(source)})
        if source.suffix.lower() != ".png":
            raise WorkflowFailure("input_not_png", "declared input must have a .png suffix", {"path": str(source)})
        source = confined(source, input_root, "declared PNG input")
        width, height = png_dimensions(source)
        receipt["input"].update({
            "path": str(source),
            "sha256": sha256_file(source),
            "bytes": source.stat().st_size,
            "png_dimensions": {"width": width, "height": height},
            "comfyui_input_name": source.relative_to(input_root).as_posix(),
        })
        if not core.is_file():
            raise WorkflowFailure("core_unavailable", "Rust/SQLite media contract CLI is unavailable", {"path": str(core)})
        if not ffmpeg.is_file():
            raise WorkflowFailure("ffmpeg_unavailable", "existing ffmpeg entry is unavailable", {"path": str(ffmpeg)})
        if ffmpeg.resolve() != DEFAULT_FFMPEG.resolve() or sha256_file(ffmpeg) != PINNED_FFMPEG_SHA256:
            raise WorkflowFailure("ffmpeg_binding_changed", "Existing ffmpeg binary no longer matches the bounded binding")
        base_workspace = confined(workspace, ROOT / ".dev", "media workspace")
        receipt_path = receipt_path.resolve()
        isolated = prepare_isolated_workspace(base_workspace, run_id)
        receipt["isolation"]["workspace"] = str(isolated)
        requested_output = None
        if output_path is not None:
            requested_output = confined(output_path, base_workspace, "media output")
            if (requested_output.parent != base_workspace or requested_output.exists()
                    or output_path.is_symlink() or requested_output.suffix.lower() != ".mp4"):
                raise WorkflowFailure("output_not_mp4", "requested media output must have an .mp4 suffix", {
                    "path": str(requested_output),
                })
        staged_input = isolated / "input.png"
        shutil.copyfile(source, staged_input)
        receipt["artifacts"]["staged_input"] = artifact(staged_input, "declared-input-copy")

        help_result = core_call(receipt, core, isolated, "rust-cli-help", "help")
        if isinstance(help_result, dict):
            receipt["versions"]["core_cli"] = {
                "path": str(core),
                "version_observed": help_result.get("version"),
                "binary_sha256": sha256_file(core),
            }
        init_result = core_call(receipt, core, isolated, "rust-cli-init", "init", isolated)
        receipt["contract"] = {"init": init_result}
        input_ref = core_call(
            receipt,
            core,
            isolated,
            "rust-cli-register-input",
            "register-binary-input",
            isolated,
            "user/media-input",
            "input.png",
            "confirm-isolated-binary-media-input",
        )
        receipt["contract"]["input_ref"] = input_ref
        refresh_result = core_call(receipt, core, isolated, "rust-cli-refresh-input", "refresh", isolated)
        receipt["contract"]["refresh"] = refresh_result

        stats = append_http_command(receipt, "system_stats", comfy_endpoint, "GET", None, min(5.0, timeout))
        receipt["versions"]["comfyui"] = {
            "endpoint": comfy_endpoint,
            "version_observed": observed_comfy_version(stats),
        }
        for node in ("LoadImage", "ImageScale", "SaveImage"):
            node_info = append_http_command(receipt, f"object_info/{node}", comfy_endpoint, "GET", None, min(5.0, timeout))
            if not node_is_present(node_info, node):
                raise WorkflowFailure("comfyui_node_missing", f"ComfyUI node {node} is not available", {"response": node_info})

        prefix = f"wuji4_media_{run_id}"
        graph = build_workflow(source.relative_to(input_root).as_posix(), prefix)
        receipt["workflow_graph"] = graph
        prompt_result = append_http_command(receipt, "prompt", comfy_endpoint, "POST", {
            "prompt": graph,
            "client_id": f"wuji4-media-{run_id}",
        }, min(5.0, timeout))
        prompt_id = prompt_result.get("prompt_id") if isinstance(prompt_result, dict) else None
        if not isinstance(prompt_id, str) or not prompt_id:
            raise WorkflowFailure("comfyui_prompt_rejected", "ComfyUI did not return a prompt_id", prompt_result)

        deadline = time.monotonic() + timeout
        history: object = {}
        while time.monotonic() < deadline:
            history = append_http_command(receipt, f"history/{prompt_id}", comfy_endpoint, "GET", None, min(5.0, timeout))
            if isinstance(history, dict) and prompt_id in history:
                prompt_history = history[prompt_id]
                status = prompt_history.get("status", {}) if isinstance(prompt_history, dict) else {}
                if isinstance(status, dict) and status.get("status_str") in ("error", "failed"):
                    raise WorkflowFailure("comfyui_execution_failed", "ComfyUI workflow execution failed", status)
                if isinstance(prompt_history, dict) and isinstance(prompt_history.get("outputs"), dict):
                    break
            time.sleep(0.25)
        else:
            raise WorkflowFailure("comfyui_execution_timeout", "ComfyUI workflow did not finish within its bound", {"prompt_id": prompt_id})

        comfy_output, output_declaration = output_image_path(history, output_root)
        generated_png = isolated / "comfy-output.png"
        shutil.copyfile(comfy_output, generated_png)
        receipt["artifacts"]["comfy_output"] = artifact(generated_png, "comfyui-save-image")
        receipt["comfy_output_declaration"] = output_declaration
        output_ref = core_call(
            receipt,
            core,
            isolated,
            "rust-cli-register-comfy-output",
            "register-binary-input",
            isolated,
            "user/comfy-output",
            "comfy-output.png",
            "confirm-isolated-binary-media-input",
        )
        receipt["contract"]["comfy_output_ref"] = output_ref

        version_bytes = append_process_command(receipt, "ffmpeg-version", [ffmpeg, "-version"], isolated, 15)
        version_record = receipt["commands"][-1]
        version_text = ""
        if isinstance(version_record, dict):
            version_text = str(version_record.get("stdout", "")).splitlines()[0] if version_record.get("stdout") else ""
        receipt["versions"]["ffmpeg"] = {"path": str(ffmpeg), "version_observed": version_text, "binary_sha256": sha256_file(ffmpeg)}
        mp4 = isolated / "media-output.mp4"
        append_process_command(receipt, "ffmpeg-encode-mp4", [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
            "-protocol_whitelist", "file,pipe", "-f", "image2", "-pattern_type", "none",
            "-loop", "1", "-framerate", "8", "-i", generated_png,
            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4,
        ], isolated, 30)
        if not mp4.is_file() or mp4.stat().st_size == 0:
            raise WorkflowFailure("ffmpeg_output_missing", "ffmpeg returned success without an MP4 artifact")
        append_process_command(receipt, "ffmpeg-independent-decode", [
            ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", mp4, "-f", "null", "-",
        ], isolated, 30)
        receipt["artifacts"]["mp4"] = artifact(mp4, "ffmpeg-bounded-mp4")
        if requested_output is not None:
            with requested_output.open("xb") as target, mp4.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, target)
            receipt["artifacts"]["requested_output"] = artifact(requested_output, "requested-output-copy")
        mp4_ref = core_call(
            receipt,
            core,
            isolated,
            "rust-cli-register-mp4",
            "register-binary-input",
            isolated,
            "user/media-output",
            "media-output.mp4",
            "confirm-isolated-binary-media-input",
        )
        receipt["contract"]["mp4_ref"] = mp4_ref
        receipt["status"] = "completed_bounded_media_task"
        receipt["result_state"] = "completed_bounded_task"
        return_code = 0
    except WorkflowFailure as error:
        receipt["status"] = "failed_real_error"
        receipt["result_state"] = "failed_real_error"
        receipt["failure"] = {"code": error.code, "message": error.message, "details": error.details}
        return_code = error.exit_code
    except Exception as error:
        receipt["status"] = "failed_unexpected_error"
        receipt["result_state"] = "failed_unexpected_error"
        receipt["failure"] = {"code": "unexpected_error", "message": str(error), "details": {"type": type(error).__name__}}
        return_code = 1
    finally:
        protection = receipt["configuration_protection"]
        protection["after_sha256"] = sha256_or_missing(codex_config)
        protection["unchanged"] = (protection["before_sha256"] is not None
                                    and protection["before_sha256"] == protection["after_sha256"])
        if not protection["unchanged"]:
            receipt["status"] = receipt["result_state"] = "failed_real_error"
            receipt["failure"] = {"code": "protected_configuration_changed", "message": "Protected configuration could not be verified unchanged"}
            return_code = 1
        receipt["process_exit_code"] = return_code
        receipt["finished_at_utc"] = utc_now()
        receipt["configuration_protection"] = protection
        receipt_path = receipt_path.resolve()
        write_receipt(receipt_path, receipt)
    return return_code, receipt


def run(
    workspace: Path,
    output: Path | None = None,
    *,
    input_path: Path | None = None,
    receipt: Path | None = None,
    comfy_endpoint: str = DEFAULT_COMFY_ENDPOINT,
    comfy_input_root: Path = DEFAULT_COMFY_INPUT,
    comfy_output_root: Path = DEFAULT_COMFY_OUTPUT,
    ffmpeg: Path = DEFAULT_FFMPEG,
    core: Path = DEFAULT_CORE,
    timeout: float = 30.0,
) -> dict[str, object]:
    if Path(workspace).is_symlink():
        raise WorkflowFailure("workspace_invalid", "media workspace cannot be a symbolic link")
    base_workspace = confined(workspace, ROOT / ".dev", "media workspace")
    if base_workspace == (ROOT / ".dev").resolve():
        raise WorkflowFailure("workspace_invalid", "media workspace must be a separate directory below .dev", {
            "path": str(base_workspace),
        })
    if not base_workspace.exists():
        base_workspace.mkdir(parents=True, exist_ok=False)
    if not base_workspace.is_dir() or base_workspace.is_symlink():
        raise WorkflowFailure("workspace_invalid", "media workspace must be a separate directory below .dev", {
            "path": str(base_workspace),
        })
    original_receipt = Path(receipt) if receipt is not None else base_workspace / "media-workflow-receipt.json"
    receipt_path = original_receipt.resolve()
    if (receipt_path.parent != base_workspace or receipt_path.suffix != ".json"
            or original_receipt.is_symlink() or receipt_path.exists()):
        raise WorkflowFailure("receipt_exists", "media receipt must be a new declared file", {
            "path": str(receipt_path),
        })
    if input_path is None:
        raise WorkflowFailure("input_missing", "A declared media input is required")
    with receipt_path.open("x", encoding="utf-8") as handle:
        json.dump({"status": "running", "P7": False}, handle)
    source = input_path
    _, evidence = execute(
        source,
        base_workspace,
        receipt_path,
        comfy_endpoint=comfy_endpoint,
        comfy_input_root=comfy_input_root,
        comfy_output_root=comfy_output_root,
        ffmpeg=ffmpeg,
        core=core,
        output_path=output,
        timeout=timeout,
    )
    return evidence


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description="Run one bounded real ComfyUI-to-ffmpeg media task.")
    argument_parser.add_argument("--input", required=True, type=Path)
    argument_parser.add_argument("--receipt", type=Path)
    argument_parser.add_argument("--workspace", type=Path, required=True)
    argument_parser.add_argument("--output", type=Path)
    argument_parser.add_argument("--comfy-endpoint", default=DEFAULT_COMFY_ENDPOINT)
    argument_parser.add_argument("--comfy-input-root", type=Path, default=DEFAULT_COMFY_INPUT)
    argument_parser.add_argument("--comfy-output-root", type=Path, default=DEFAULT_COMFY_OUTPUT)
    argument_parser.add_argument("--ffmpeg", type=Path, default=DEFAULT_FFMPEG)
    argument_parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    argument_parser.add_argument("--timeout", type=float, default=30.0)
    return argument_parser


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        evidence = run(
            arguments.workspace,
            arguments.output,
            input_path=arguments.input,
            receipt=arguments.receipt,
            comfy_endpoint=arguments.comfy_endpoint,
            comfy_input_root=arguments.comfy_input_root,
            comfy_output_root=arguments.comfy_output_root,
            ffmpeg=arguments.ffmpeg,
            core=arguments.core,
            timeout=arguments.timeout,
        )
        print(json.dumps(evidence, ensure_ascii=False))
        return int(evidence["process_exit_code"] or 0)
    except WorkflowFailure as error:
        print(json.dumps({
            "status": "failed_before_receipt",
            "failure": {"code": error.code, "message": error.message, "details": error.details},
        }, ensure_ascii=False))
        return error.exit_code
    except Exception as error:
        print(json.dumps({"status": "failed_before_receipt", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
