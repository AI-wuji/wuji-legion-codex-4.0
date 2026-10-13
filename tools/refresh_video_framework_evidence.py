from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p4/comfyui-probe-output.png"
OUTPUT = ROOT / "outputs/p4/video-framework-output.mp4"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    workspace = ROOT / ".dev/legion-task-workspaces" / f"video-binding-{time.time_ns()}"
    workspace.mkdir(parents=True, exist_ok=False)
    source = workspace / "source.png"
    shutil.copyfile(SOURCE, source)
    command = [sys.executable, "-B", "tools/wuji4.py", "run-video", str(workspace), source.name,
               "confirm-isolated-video-task", "--receipt", "video-workflow-receipt-current.json"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0:
        raise RuntimeError((completed.stdout + completed.stderr).decode("utf-8", errors="replace"))
    result = json.loads(completed.stdout.decode("utf-8"))
    receipt = result["receipt"]
    if receipt.get("passed") is not True:
        raise RuntimeError("run-video did not produce a completed bounded task")
    artifact = workspace / "video-output.mp4"
    if not artifact.is_file():
        raise RuntimeError("run-video did not retain its MP4 artifact")
    shutil.copyfile(artifact, OUTPUT)
    evidence = dict(receipt)
    evidence["framework_execution"] = {
        "command": command,
        "source": "tools/wuji4.py",
        "exit_code": completed.returncode,
        "source_sha256": digest(ROOT / "tools/wuji4.py"),
    }
    evidence["implementation_hashes"] = {
        relative: digest(ROOT / relative)
        for relative in ("adapters/p4/ffmpeg_workflow.py", "adapters/p4/media_workflow.py", "tools/wuji4.py")
    }
    evidence["retained_artifact"] = {
        "path": OUTPUT.relative_to(ROOT).as_posix(),
        "sha256": digest(OUTPUT),
        "bytes": OUTPUT.stat().st_size,
    }
    evidence["original_receipt_sha256"] = digest(Path(receipt["receipt_path"]))
    (ROOT / "outputs/p4/video-framework-workflow-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": evidence["passed"], "artifact_sha256": evidence["retained_artifact"]["sha256"],
                      "manifest_sha256": evidence["reviewed_binding"]["manifest_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
