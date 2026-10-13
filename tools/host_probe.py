"""Only local metadata/config observation. Never model generation or an auth probe."""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib

from preflight import ROOT, stamp, write_json

CONFIG = Path("C:/Users/Administrator/.codex/config.toml")


def cli_metadata(path: str, args: list[str]) -> dict:
    try:
        run = subprocess.run([path, *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=10)
        output = run.stdout.strip()
        return {"available": run.returncode == 0, "exit_code": run.returncode,
                "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
                "version": output if args == ["--version"] and len(output) < 120 else None,
                "json_event_flag": "--json" in output,
                "ignore_user_config_flag": "--ignore-user-config" in output,
                "ephemeral_flag": "--ephemeral" in output,
                "model_override_flag": "--model" in output,
                "config_override_flag": "--config" in output,
                "strict_config_flag": "--strict-config" in output,
                "no_daemon_flag": "--no-daemon" in output,
                "profile_help_uses_layer_file": "config.toml on top" in output}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "error_type": type(error).__name__}


def probe(config_path: Path = CONFIG) -> dict:
    result = {"schema_version": 1, "observed_at": stamp(), "host_kind": "local-codex-desktop",
              "requested_policy": {
                  "mode": "current_selection_baseline_upgrade_only",
                  "baseline_model": "inherit_current_conversation_selection",
                  "baseline_effort": "inherit_current_conversation_selection",
                  "upgrade_model": "gpt-6.1-sol", "upgrade_efforts": ["high", "xhigh"],
                  "automatic_downgrade": False, "failure_fallback_chain": False,
                  "restore_baseline_after_upgrade": True,
              },
              "effective_model": "unknown", "effective_effort": "unknown",
              "third_party_request_verified": False, "native_spawn_verified": False,
              "close_and_quota_release_verified": False, "production_changed": False,
              "config": {"path": str(config_path), "status": "missing"},
              "tools": {}, "default_concurrency": 2, "pressure_concurrency": 1,
              "effective_concurrency_cap": "unknown", "G0": "not_passed",
              "boundary": "Configured values and help are not effective host/model execution evidence."}
    if config_path.is_file():
        raw = config_path.read_bytes()
        config = tomllib.loads(raw.decode("utf-8-sig"))
        selected = {k: config[k] for k in ("model", "model_reasoning_effort", "model_provider",
                                         "tool_output_token_limit", "model_context_window",
                                         "model_auto_compact_token_limit") if k in config}
        # Never serialize config as a whole: it can contain tokens or private URLs.
        selected["status"] = "observed_not_effective"
        selected["path"] = str(config_path)
        selected["sha256"] = hashlib.sha256(raw).hexdigest()
        agents = config.get("agents", {})
        allowed = ("max_concurrent_threads_per_session", "max_threads", "max_depth",
                   "default_subagent_model", "default_subagent_reasoning_effort")
        selected["agents_observed"] = {k: agents[k] for k in allowed if k in agents}
        result["configured_concurrency_cap"] = agents.get("max_concurrent_threads_per_session", "unknown")
        for key in ("developer_instructions", "instructions"):
            if isinstance(config.get(key), str):
                selected[key + "_present"] = True
                selected[key + "_sha256"] = hashlib.sha256(config[key].encode("utf-8")).hexdigest()
        provider = config.get("model_providers", {}).get(config.get("model_provider"), {})
        selected["selected_provider"] = {"entry_present": bool(provider),
                                        "base_url_present": bool(provider.get("base_url")),
                                        "wire_api": provider.get("wire_api", "unknown"),
                                        "requires_openai_auth": provider.get("requires_openai_auth", "unknown"),
                                        "credential_values_not_emitted": True}
        profiles = config.get("profiles", {})
        selected["legacy_profile_table"] = {
            name: {k: value[k] for k in ("model", "model_reasoning_effort") if k in value}
            for name, value in profiles.items() if isinstance(value, dict)
        }
        selected["profile_layer_files"] = sorted(p.name for p in config_path.parent.glob("*.config.toml"))
        result["config"] = selected
    for name in ("codex", "rustc", "cargo", "cl", "go", "git", "node", "ffmpeg", "ffprobe", "officecli", "reaper"):
        executable = shutil.which(name)
        result["tools"][name] = {"resolved_path": executable, "on_current_path": executable is not None}
    codex = result["tools"]["codex"]["resolved_path"]
    if codex:
        result["codex_cli_version"] = cli_metadata(codex, ["--version"])
        result["codex_root_help"] = cli_metadata(codex, ["--help"])
        result["codex_exec_help"] = cli_metadata(codex, ["exec", "--help"])
    result["mount_proposal"] = {
        "kind": "explicit_upgrade_overrides_not_automatic_routing",
        "baseline": "current_conversation_selection_not_disk_defaults",
        "model_flag": ["--model", "gpt-6.1-sol"],
        "effort_config_key": "model_reasoning_effort",
        "efforts": ["high", "xhigh"],
        "baseline_handoff_required_for_independent_worker": True,
        "legacy_profiles_required": False,
        "writes_user_config": False,
        "help_observed_not_request_verified": True,
        "verification_gate": "G2",
    }
    result["unknowns"] = ["current conversation baseline model/effort and explicit high/xhigh upgrade results",
                          "effective agent quota/current occupied slots/close release",
                          "current CLI profile layer vs legacy profiles table effectiveness",
                          "source-level 3.0 install conflict and P7 field-level restore map",
                          "image/video API model/credentials/verified free allowance",
                          "REAPER isolated offline workflow and microphone device preservation"]
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    value = probe()
    write_json(ROOT / "outputs/p0/host-capabilities.json", value)
    print(json.dumps({"config_status": value["config"]["status"],
                      "configured_cap": value.get("configured_concurrency_cap", "unknown"),
                      "effective_cap": value["effective_concurrency_cap"],
                      "policy": value["requested_policy"],
                      "G0": value["G0"]}, ensure_ascii=False))
