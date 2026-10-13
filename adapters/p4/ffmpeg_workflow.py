from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from adapters.p4 import media_workflow as media


ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path("C:/Users/Administrator/.codex/config.toml")
BINDING_MANIFEST = ROOT / "catalog/p4/tool-manifests.json"
VIDEO_TOOL_ID = "video-render"
VIDEO_TOOL_VERSION = "ffmpeg-7.1-observed"
VIDEO_TOOL_SERVER = "local-process"
VIDEO_TOOL_NAME = "video-render/png-to-mp4"
VIDEO_INTERFACE = {
    "schema_version": 1, "input_format": "png", "input_direct_child": True,
    "max_input_bytes": 8 * 1024 * 1024, "even_dimensions": True, "dimension_range": [2, 2048],
    "output_format": "mp4", "codec": "libx264", "duration_us": 1000000, "frames": 8,
    "audio": False, "protocol_whitelist": "file,pipe", "pattern_type": "none",
    "overwrite": False, "receipt_direct_child": True, "comfyui_fallback": False,
}


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate tool-binding JSON key")
        result[key] = value
    return result


def reviewed_binding() -> dict:
    manifest = json.loads(BINDING_MANIFEST.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("tools"), list):
        raise ValueError("The tool manifest schema is unsupported; no directory fallback")
    tools = manifest["tools"]
    identifiers = [tool.get("id") if isinstance(tool, dict) else None for tool in tools]
    if len(set(identifiers)) != len(identifiers) or identifiers.count(VIDEO_TOOL_ID) != 1:
        raise ValueError("Exact unique video tool identity is required; no directory fallback")
    tool = tools[identifiers.index(VIDEO_TOOL_ID)]
    binding = tool["reviewed_binding"]
    if (tool["status"] != "available-local-bounded" or tool["runtime_admission"] is not True
            or tool.get("version") != VIDEO_TOOL_VERSION
            or tool["adapter"] != "adapters/p4/ffmpeg_workflow.py"
            or tool["workflow_entrypoint"] != "tools/wuji4.py run-video"
            or set(binding) != {"revision", "identity", "interface", "implementation_hashes"}
            or type(binding["revision"]) is not int or binding["revision"] < 1):
        raise ValueError("Video tool version or reviewed binding is not admitted")
    matching_names = [candidate for candidate in tools
                      if isinstance(candidate, dict)
                      and isinstance(candidate.get("reviewed_binding"), dict)
                      and isinstance(candidate["reviewed_binding"].get("identity"), dict)
                      and candidate["reviewed_binding"]["identity"].get("tool") == VIDEO_TOOL_NAME]
    if len(matching_names) != 1 or matching_names[0] is not tool:
        raise ValueError("Video tool name is ambiguous; same-name dispatch is refused")
    identity = {"server": VIDEO_TOOL_SERVER, "tool": VIDEO_TOOL_NAME,
                "entrypoint": media.DEFAULT_FFMPEG.as_posix(), "binary_sha256": media.PINNED_FFMPEG_SHA256,
                "version_prefix": "ffmpeg version 7.1-essentials_build-"}
    interface_bytes = json.dumps(binding["interface"], sort_keys=True, separators=(",", ":"))
    expected_interface_bytes = json.dumps(VIDEO_INTERFACE, sort_keys=True, separators=(",", ":"))
    if binding["identity"] != identity or interface_bytes != expected_interface_bytes:
        raise ValueError("Video tool identity or interface schema drift requires independent review")
    sources = {relative: media.sha256_file(ROOT / relative) for relative in (
        "adapters/p4/ffmpeg_workflow.py", "adapters/p4/media_workflow.py", "tools/wuji4.py")}
    if binding["implementation_hashes"] != sources:
        raise ValueError("Video tool implementation drift invalidates the reviewed interface binding")
    fingerprint = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"manifest": str(BINDING_MANIFEST), "manifest_sha256": media.sha256_file(BINDING_MANIFEST),
            "tool_id": VIDEO_TOOL_ID, "version": tool["version"], "revision": binding["revision"],
            "binding_sha256": fingerprint,
            "identity": identity, "interface": VIDEO_INTERFACE, "implementation_hashes": sources}


def require_current_binding(expected: dict) -> None:
    current = reviewed_binding()
    if current != expected:
        raise ValueError("Video tool binding drifted before dispatch; refusing tool call")


def local_file(workspace: Path, requested: Path, suffix: str, *, existing: bool) -> Path:
    original = Path(requested)
    candidate = original if original.is_absolute() else workspace / original
    if candidate.is_symlink() or candidate.resolve().parent != workspace or candidate.suffix.lower() != suffix:
        raise ValueError("Only declared direct-child files in the isolated workspace are allowed")
    if existing and not candidate.is_file():
        raise ValueError("Declared input is missing")
    if not existing and candidate.exists():
        raise FileExistsError("Never overwrite a preexisting output or receipt")
    return candidate.resolve()


def run(workspace: Path, output: Path | None = None, input_path: Path | None = None,
        video: str = "video-output.mp4") -> dict:
    original_workspace = Path(workspace)
    workspace = original_workspace.resolve(strict=True)
    allowed_roots = [ROOT / ".dev/legion-task-workspaces", ROOT / ".dev/core-test-workspaces"]
    if (original_workspace.is_symlink() or not workspace.is_dir()
            or not any(workspace != root.resolve() and workspace.is_relative_to(root.resolve())
                       for root in allowed_roots)):
        raise ValueError("Video execution requires a dedicated isolated task workspace")
    receipt_path = local_file(workspace, output or Path("video-workflow-receipt.json"), ".json", existing=False)
    report = {
        "schema_version": 1, "kind": "isolated_png_to_video_task",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "result_state": "running", "passed": False,
        "receipt_path": str(receipt_path), "commands": [], "checks": {}, "artifacts": {},
        "failure": None, "retry_count": 0, "professional_effectiveness": "not_claimed",
        "audio_device_opened": False, "comfyui_submitted": False, "P7": False, "shutdown": False,
    }
    with receipt_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle)
    protected_before = media.sha256_or_missing(CONFIG)
    destination = None
    source = None
    dispatch_binding = None
    try:
        if input_path is None:
            raise ValueError("A declared PNG input is required")
        source = local_file(workspace, input_path, ".png", existing=True)
        destination = local_file(workspace, Path(video), ".mp4", existing=False)
        width, height = media.png_dimensions(source)
        if (source.stat().st_size > 8 * 1024 * 1024 or not 2 <= width <= 2048 or not 2 <= height <= 2048
                or width % 2 or height % 2):
            raise ValueError("Bounded video input requires an even-sized PNG up to 2048x2048 and 8 MiB")
        source_hash = media.sha256_file(source)
        binary = media.DEFAULT_FFMPEG
        if not binary.is_file() or binary.is_symlink() or media.sha256_file(binary) != media.PINNED_FFMPEG_SHA256:
            raise ValueError("The existing pinned ffmpeg binary is missing or changed; no fallback")
        dispatch_binding = reviewed_binding()
        report["reviewed_binding"] = dispatch_binding
        report["input"] = {"path": str(source), "sha256": source_hash, "bytes": source.stat().st_size,
                           "width": width, "height": height}
        report["binary"] = {"path": str(binary), "sha256": media.PINNED_FFMPEG_SHA256}
        report["implementation_hashes"] = {
            "adapters/p4/ffmpeg_workflow.py": media.sha256_file(Path(__file__)),
            "adapters/p4/media_workflow.py": media.sha256_file(ROOT / "adapters/p4/media_workflow.py"),
        }
        if protected_before is None:
            raise ValueError("Protected Codex configuration is unavailable")
        dispatch_guard = lambda: require_current_binding(dispatch_binding)
        media.append_process_command(report, "ffmpeg-version", [binary, "-version"], workspace, 15,
                                      before_dispatch=dispatch_guard)
        version = report["commands"][-1]["stdout"].splitlines()[0]
        report["binary"]["version_observed"] = version
        if not version.startswith("ffmpeg version 7.1-essentials_build-"):
            raise ValueError("ffmpeg version does not match the existing binding")
        media.append_process_command(report, "ffmpeg-encode", [
            binary, "-nostdin", "-hide_banner", "-v", "error", "-n",
            "-protocol_whitelist", "file,pipe", "-f", "image2", "-pattern_type", "none",
            "-loop", "1", "-framerate", "8", "-i", source,
            "-t", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1",
            "-movflags", "+faststart", destination,
        ], workspace, 30, before_dispatch=dispatch_guard)
        if not destination.is_file() or not destination.stat().st_size:
            raise ValueError("ffmpeg returned without a video artifact")
        report["artifacts"]["mp4"] = media.artifact(destination, "bounded-h264-mp4")
        media.append_process_command(report, "ffmpeg-independent-decode", [
            binary, "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-i", destination, "-map", "0:v:0", "-an", "-f", "null", "-", "-progress", "pipe:1", "-nostats",
        ], workspace, 30, before_dispatch=dispatch_guard)
        progress = dict(line.split("=", 1) for line in report["commands"][-1]["stdout"].splitlines() if "=" in line)
        report["validation"] = {"decoder": "separate_ffmpeg_process", "progress": progress,
                                "expected_frames": 8, "expected_duration_us": 1000000}
        report["checks"] = {
            "decoded_eight_frames": progress.get("frame") == "8",
            "decoded_one_second": progress.get("out_time_us") == "1000000",
            "decode_completed": progress.get("progress") == "end",
            "source_current": media.sha256_file(source) == source_hash,
            "output_current": media.sha256_file(destination) == report["artifacts"]["mp4"]["sha256"],
            "binary_current": media.sha256_file(binary) == media.PINNED_FFMPEG_SHA256,
            "reviewed_binding_current": media.sha256_file(BINDING_MANIFEST) == report["reviewed_binding"]["manifest_sha256"]
                and all(media.sha256_file(ROOT / relative) == expected
                        for relative, expected in report["reviewed_binding"]["implementation_hashes"].items()),
        }
    except Exception as error:
        report["failure"] = {"type": type(error).__name__, "code": getattr(error, "code", "video_task_failed"),
                             "message": str(error)}
    finally:
        protected_after = media.sha256_or_missing(CONFIG)
        report["configuration_protection"] = {"before_sha256": protected_before, "after_sha256": protected_after,
                                              "unchanged": protected_before is not None and protected_before == protected_after}
        report["checks"]["configuration_unchanged"] = report["configuration_protection"]["unchanged"]
        report["passed"] = report["failure"] is None and len(report["checks"]) == 8 and all(report["checks"].values())
        report["status"] = report["result_state"] = "completed_bounded_task" if report["passed"] else "failed_evidence_retained"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
