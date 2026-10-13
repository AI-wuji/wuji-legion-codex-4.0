from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / ".dev/runtime-target/debug/wuji4.exe"
FFMPEG = Path("E:/COMFYUI_dapao1/python_dapao313/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe")


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def main() -> None:
    codex = Path("C:/Users/Administrator/.codex/config.toml")
    protected_before = digest(codex)
    suffix = str(time.time_ns())
    workspace = ROOT / ".dev/media-recipe-probes" / suffix
    workspace.mkdir(parents=True, exist_ok=False)
    workspace.resolve().relative_to((ROOT / ".dev").resolve())
    receipts = []

    def call(*arguments: object, expected_error: str | None = None):
        completed = subprocess.run([str(CORE), *map(str, arguments)], cwd=workspace,
                                   capture_output=True, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if len(completed.stdout) + len(completed.stderr) > 1024 * 1024:
            raise RuntimeError("Core probe response exceeds complete evidence bound")
        text = completed.stderr if expected_error else completed.stdout
        value = json.loads(text.decode("utf-8"))
        passed = completed.returncode != 0 and value.get("error") == expected_error if expected_error else completed.returncode == 0
        receipts.append({"arguments": list(map(str, arguments)), "exit_code": completed.returncode,
                         "owned_process_exit_observed": True, "expected_error": expected_error, "matched": passed})
        if not passed:
            raise RuntimeError({"arguments": arguments, "exit_code": completed.returncode, "value": value})
        return value

    initial = call("init", workspace)

    def write_json(name: str, value: dict) -> Path:
        path = workspace / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def register(name: str, binary: bool = False):
        if binary:
            return call("register-binary-input", workspace, f"user/{name}", name, "confirm-isolated-binary-media-input")
        return call("register-input", workspace, f"user/{name}", name)

    def contract(name: str, kind: str, payload: dict):
        value = {"schema_version": 1, "contract_type": kind, "payload": payload,
                 "metadata": {"id": name, "type": kind, "scope": initial["scope"], "schema_version": 1, "revision": 1,
                              "owner": "aji-local", "authority": "review_proposal", "status": "proposal", "source_refs": [],
                              "evidence_refs": [], "created_at_utc_ms": 1, "updated_at_utc_ms": 1, "valid_until_utc_ms": None,
                              "classification": "project_private", "parent_refs": []}}
        path = write_json(name, value)
        value["metadata"]["content_hash"] = call("object-hash", path)["sha256"]
        write_json(name, value)
        return register(name)

    def quantity(numerator: int, denominator: int = 1):
        return {"numerator": numerator, "denominator": denominator, "unit": "second", "basis_ref": None, "rounding": "exact"}

    audio = workspace / "synthetic-original.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"".join(struct.pack("<h", round(1024 * math.sin(2 * math.pi * 400 * sample / 8000))) for sample in range(8000)))
    with wave.open(str(audio), "rb") as observed:
        profile = {"sample_rate": observed.getframerate(), "sample_frames": observed.getnframes(), "channels": observed.getnchannels()}
    audio_ref = register(audio.name, True)
    (workspace / "rights.txt").write_text("Original synthetic test signal generated in this isolated project; not external music or professional composition.", encoding="utf-8")
    rights = register("rights.txt")
    story = contract("story.json", "StoryPlan", {"text": "A local music-first contract fixture", "version": 1,
        "segment_ids": ["segment"], "duration_target": quantity(2), "narrative_functions": ["technical evidence"],
        "emotion_curve": ["neutral"], "invariants": ["no external publication"], "voice_roles": []})
    cue = contract("cue.json", "MusicCuePlan", {"cue_id": "cue", "story_segment_ref": story, "emotion": "neutral", "density": "sparse",
        "asset": audio_ref, "rights": rights, "start": quantity(0), "end": quantity(1), "transition": "none", "phrase_anchors": [],
        "beat_anchors": [], "ducking": [], "lock_level": "adopted"})
    shot = contract("shot.json", "ShotPlan", {"shot_id": "shot", "story_refs": [story], "music_refs": [cue], "start": quantity(0), "end": quantity(4, 5),
        "camera": "static", "action": "technical fixture", "visual_refs": [], "dialogue_ref": None, "srt_ref": None,
        "sound_intent": "actual synthetic audio", "transition": "none", "generation_requirements": ["no professional quality claim"]})
    request = {"story_ref": story, "music_refs": [cue], "shot_refs": [shot], "timeline_ref": None}
    request_path = write_json("request.json", request)
    prepared = call("validate-media-chain", workspace, request_path)
    invalid = json.loads(json.dumps(request))
    invalid["music_refs"][0]["revision"] += 1
    call("validate-media-chain", workspace, write_json("invalid-request.json", invalid), expected_error="Reference")
    environment = dict(os.environ)
    environment.pop("FFREPORT", None)
    decoded = subprocess.run([str(FFMPEG), "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file,pipe",
                              "-i", str(audio), "-f", "null", "-"], cwd=workspace, env=environment,
                             capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if decoded.returncode != 0:
        raise RuntimeError(decoded.stderr.decode("utf-8", errors="replace"))
    destination = ROOT / "outputs/p4/media-contract-proof" / suffix
    destination.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for name in (audio.name, "rights.txt", "story.json", "cue.json", "shot.json", "request.json"):
        target = destination / name
        shutil.copyfile(workspace / name, target)
        artifacts.append({"path": target.relative_to(ROOT).as_posix(), "sha256": digest(target), "bytes": target.stat().st_size})
    protected_after = digest(codex)
    evidence = {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(), "scope": "bounded-isolated-music-first-contract-preparation",
        "passed": protected_before == protected_after and all(row["matched"] for row in receipts) and prepared["state"] == "prepared",
        "core_binary_sha256": digest(CORE), "sources": {name: digest(ROOT / name) for name in ("src/media.rs", "src/time.rs", "tools/probe_media_contracts.py")},
        "artifacts": artifacts, "actual_pcm_profile": profile, "core_process_receipts": receipts, "prepared": prepared,
        "ffmpeg": {"binary_path": str(FFMPEG), "binary_sha256": digest(FFMPEG), "decode_exit_code": decoded.returncode,
                   "owned_process_exit_observed": True, "audio_device_opened": False, "FFREPORT_disabled": True},
        "protected_codex_configuration": {"before": protected_before, "after": protected_after, "unchanged": protected_before == protected_after},
        "professional_music_or_video_effectiveness": "not_claimed", "REAPER_executed": False, "G4_passed": False, "P7": False, "shutdown": False}
    (ROOT / "outputs/p4/media-contract-probe-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": evidence["passed"], "actual_audio_decode_exit": decoded.returncode, "core_processes": len(receipts),
                      "state": prepared["state"], "G4_passed": False}))
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
