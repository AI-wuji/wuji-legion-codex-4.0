from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/p6/continuation-2026-10-04"


def github(path: str):
    request = urllib.request.Request("https://api.github.com/" + path,
                                     headers={"User-Agent": "wuji4-read-only-research"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Research response byte cap exceeded")
    return json.loads(data), hashlib.sha256(data).hexdigest()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    workers = []
    for name in ("cli", "package"):
        path = OUTPUT / f"{name}-worker-events.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        start = next(row for row in rows if row.get("type") == "thread.started")
        errors = [str(row.get("message", row.get("error", ""))) for row in rows if row.get("type") in ("error", "turn.failed")]
        workers.append({"worker": name, "thread_id": start["thread_id"],
                        "requested_model": "gpt-6.1-sol", "requested_effort": "high",
                        "backend_effective_model": "unknown", "backend_effective_effort": "unknown",
                        "final_event": rows[-1]["type"], "rate_limit_429_observed": any("429" in error for error in errors),
                        "parent_exec_exit_code_observed": 1, "native_thread_closed_observed": "unknown",
                        "event_log_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "caller_model_fallback_performed": False, "backend_reroute": "unknown",
                        "transport_retry_limit_reached": any("retry limit" in error for error in errors),
                        "post_terminal_generation_retry": False})
    report = {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
              "builtin_fixed_model_dispatch": "rejected_unknown_model_not_provider_availability_proof",
              "configured_conservative_concurrency": 3, "actual_owned_cli_workers_started": 2,
              "workers": workers, "fee_attestation": "unknown", "configuration_modified": False,
              "scope": "Development dispatch/process exit evidence only; not formal expert activation or native quota/identity proof."}
    (OUTPUT / "parallel-workers-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    research = {"schema_version": 1, "observed_at": report["observed_at"], "kind": "public_primary_source_research_receipt",
                "source_ledger_authority_changed": False, "new_tool_installed_or_executed": False,
                "current_codex_or_global_skills_modified": False}
    try:
        release, checksum = github("repos/iOfficeAI/OfficeCLI/releases/latest")
        research.update(candidate_source="https://github.com/iOfficeAI/OfficeCLI", version=release["tag_name"],
                        release_published_at=release["published_at"], source_url=release["html_url"],
                        primary_response_sha256=checksum,
                        windows_x64_assets=[asset["name"] for asset in release["assets"] if "win-x64" in asset["name"]],
                        source_identity_status="candidate_not_matched_to_original_user_source", installation_authorization="not_established",
                        warning="Upstream bare invocation/self-install can change PATH/global Skills; neither was run.",
                        conclusion="Current public Windows portable candidate exists; missing local binding is not evidence of ecosystem unavailability.")
    except Exception as error:
        research.update(status="source_fetch_failed", error_type=type(error).__name__, version="unknown")
    (ROOT / "outputs/p4/tool-discovery-2026-10-04.json").write_text(json.dumps(research, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"workers": len(workers), "rate_limit_observed": all(worker["rate_limit_429_observed"] for worker in workers),
                      "public_tool_candidate_version": research.get("version"), "tool_installed": False}))


if __name__ == "__main__":
    main()
