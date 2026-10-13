from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "adapters/p4/media_workflow.py"
INPUT = Path("E:/COMFYUI_dapao1/ComfyUI/input/example.png")
CONFIG = Path.home() / ".codex/config.toml"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.p4 import media_workflow as workflow


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MediaWorkflowTests(unittest.TestCase):
    def test_external_receipt_is_denied_before_writing_or_execution(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".dev/core-test-workspaces") as temporary:
            root = Path(temporary)
            workspace = root / "task"
            workspace.mkdir()
            outside = root / "outside.json"
            with mock.patch.object(workflow, "execute") as execute:
                with self.assertRaises(workflow.WorkflowFailure):
                    workflow.run(workspace, input_path=INPUT, receipt=outside)
            execute.assert_not_called()
            self.assertFalse(outside.exists())
            self.assertEqual(list(workspace.iterdir()), [])

    def test_oversized_process_output_is_retained_in_full_and_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".dev/core-test-workspaces") as temporary:
            workspace = Path(temporary)
            stdout = b"a" * (workflow.MAX_PROCESS_OUTPUT + 1)
            stderr = b"error details" * 1024
            completed = subprocess.CompletedProcess(["declared-tool"], 0, stdout, stderr)
            receipt = {"commands": []}
            with mock.patch.dict(os.environ, {"FFREPORT": "must-not-be-used"}), mock.patch.object(
                    workflow.subprocess, "run", return_value=completed) as process:
                with self.assertRaises(workflow.WorkflowFailure) as failure:
                    workflow.append_process_command(receipt, "bounded-test", ["declared-tool"], workspace, 1)
            self.assertEqual(failure.exception.code, "command_output_exceeded")
            self.assertNotIn("FFREPORT", process.call_args.kwargs["env"])
            record = receipt["commands"][0]
            self.assertTrue(record["owned_process_exit_observed"])
            for retained, content in zip(record["retained_output"], (stdout, stderr)):
                path = Path(retained["path"])
                self.assertEqual(path.parent, workspace)
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(retained["sha256"], digest(path))
                self.assertEqual(retained["bytes"], len(content))

    def test_unreadable_config_fails_closed_before_any_tool_call(self):
        with mock.patch.object(workflow, "sha256_file", side_effect=PermissionError("unreadable")):
            self.assertIsNone(workflow.sha256_or_missing(CONFIG))
        with tempfile.TemporaryDirectory(dir=ROOT / ".dev/core-test-workspaces") as temporary:
            workspace = Path(temporary)
            with mock.patch.object(workflow, "sha256_or_missing", return_value=None):
                result = workflow.run(workspace, input_path=INPUT)
            self.assertNotEqual(result["process_exit_code"], 0)
            self.assertEqual(result["result_state"], "failed_real_error")
            self.assertFalse(result["configuration_protection"]["unchanged"])
            self.assertEqual(result["commands"], [])
            self.assertTrue((workspace / "media-workflow-receipt.json").is_file())

    def test_declared_graph_is_exact_three_node_path(self):
        sys.path.insert(0, str(ROOT / "adapters/p4"))
        try:
            from media_workflow import build_workflow
        finally:
            sys.path.pop(0)
        graph = build_workflow("example.png", "test-prefix")
        self.assertEqual([graph[str(index)]["class_type"] for index in range(1, 4)], ["LoadImage", "ImageScale", "SaveImage"])
        self.assertEqual(graph["2"]["inputs"]["image"], ["1", 0])
        self.assertEqual(graph["3"]["inputs"]["images"], ["2", 0])

    def test_declared_non_png_fails_before_external_execution(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".dev/core-test-workspaces") as temporary:
            root = Path(temporary)
            invalid = root / "declared.png"
            invalid.write_bytes(b"not-a-png")
            receipt = root / "receipt.json"
            workspace = root
            completed = subprocess.run([
                sys.executable, "-B", str(MODULE),
                "--input", str(invalid),
                "--comfy-input-root", str(root),
                "--receipt", str(receipt),
                "--workspace", str(workspace),
            ], cwd=ROOT, capture_output=True, text=True, check=False)
            try:
                self.assertNotEqual(completed.returncode, 0)
                evidence = json.loads(receipt.read_text(encoding="utf-8"))
                self.assertEqual(evidence["failure"]["code"], "input_not_png")
                self.assertEqual(evidence["commands"], [])
                self.assertTrue(evidence["configuration_protection"]["unchanged"])
            finally:
                self.assertTrue(workspace.is_relative_to(ROOT / ".dev"))

    def test_live_environment_completes_or_records_real_comfyui_failure(self):
        self.assertTrue(INPUT.is_file(), f"declared probe input is missing: {INPUT}")
        with tempfile.TemporaryDirectory(dir=ROOT / ".dev/core-test-workspaces") as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            workspace = root
            before_config = digest(CONFIG)
            completed = subprocess.run([
                sys.executable, "-B", str(MODULE),
                "--input", str(INPUT),
                "--receipt", str(receipt),
                "--workspace", str(workspace),
            ], cwd=ROOT, capture_output=True, text=True, check=False)
            try:
                evidence = json.loads(receipt.read_text(encoding="utf-8"))
                self.assertIn(completed.returncode, (0, 1, 2), completed.stdout + completed.stderr)
                self.assertEqual(evidence["configuration_protection"]["before_sha256"], before_config)
                self.assertEqual(evidence["configuration_protection"]["after_sha256"], digest(CONFIG))
                self.assertTrue(evidence["configuration_protection"]["unchanged"])
                self.assertFalse(evidence["audio_protection"]["audio_device_opened"])
                self.assertFalse(evidence["P7"])
                self.assertEqual(evidence["professional_effectiveness"], "not_claimed")
                if completed.returncode == 0:
                    self.assertEqual(evidence["status"], "completed_bounded_media_task")
                    self.assertEqual(evidence["result_state"], "completed_bounded_task")
                    self.assertIn("comfy_output", evidence["artifacts"])
                    self.assertIn("mp4", evidence["artifacts"])
                    self.assertTrue(any(command["phase"] == "ffmpeg-independent-decode" and command["exit_code"] == 0
                                        for command in evidence["commands"]))
                else:
                    self.assertEqual(evidence["status"], "failed_real_error")
                    self.assertTrue(str(evidence["failure"]["code"]).startswith(("comfyui_", "ffmpeg_", "core_", "executable_")))
                    self.assertTrue(any(command["phase"] == "system_stats" for command in evidence["commands"]))
            finally:
                self.assertTrue(workspace.is_relative_to(ROOT / ".dev"))


if __name__ == "__main__":
    unittest.main()
