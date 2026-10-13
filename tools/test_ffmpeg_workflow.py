import importlib.util
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from p6_acceptance import ROOT

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SPEC = importlib.util.spec_from_file_location("wuji4_video_tests", ROOT / "adapters/p4/ffmpeg_workflow.py")
video = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(video)


class FfmpegWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="video-policy-", dir=ROOT / ".dev/core-test-workspaces")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.source = self.workspace / "source.png"
        shutil.copyfile(ROOT / "outputs/p4/comfyui-probe-output.png", self.source)

    def test_actual_video_task_decodes_eight_frames_and_never_overwrites(self):
        result = video.run(self.workspace, input_path=self.source)
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["checks"]["decoded_eight_frames"])
        self.assertTrue(result["checks"]["decoded_one_second"])
        self.assertTrue(result["configuration_protection"]["unchanged"])
        self.assertFalse(result["comfyui_submitted"])
        before = (self.workspace / "video-output.mp4").read_bytes()
        repeated = video.run(self.workspace, Path("second-receipt.json"), input_path=self.source)
        self.assertFalse(repeated["passed"])
        self.assertEqual(repeated["commands"], [])
        self.assertEqual(before, (self.workspace / "video-output.mp4").read_bytes())

    def test_invalid_input_leaves_failed_receipt_before_any_tool_call(self):
        self.source.write_bytes(b"not PNG")
        result = video.run(self.workspace, input_path=self.source)
        self.assertFalse(result["passed"])
        self.assertEqual(result["commands"], [])
        self.assertEqual(result["failure"]["code"], "input_not_png")
        self.assertEqual(json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8")), result)

    def test_path_and_receipt_rejections_never_touch_preexisting_files(self):
        protected = self.workspace / "protected.json"
        protected.write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError):
            video.run(self.workspace, protected, input_path=self.source)
        with self.assertRaises(ValueError):
            video.run(self.workspace, self.workspace.parent / "escape.json", input_path=self.source)
        self.assertEqual(protected.read_bytes(), b"unchanged")
        self.assertFalse((self.workspace.parent / "escape.json").exists())

    def test_changed_binary_is_rejected_without_automatic_fallback(self):
        with mock.patch.object(video.media, "PINNED_FFMPEG_SHA256", "unverified"):
            result = video.run(self.workspace, input_path=self.source)
        self.assertFalse(result["passed"])
        self.assertEqual(result["commands"], [])
        self.assertIn("missing or changed", result["failure"]["message"])

    def test_configuration_change_revokes_completion(self):
        with mock.patch.object(video.media, "sha256_or_missing", side_effect=["before", "after"]):
            result = video.run(self.workspace, input_path=self.source)
        self.assertFalse(result["passed"])
        self.assertFalse(result["configuration_protection"]["unchanged"])
        self.assertEqual(result["result_state"], "failed_evidence_retained")
        self.assertTrue(result["checks"]["decode_completed"])

    def test_literal_pattern_characters_do_not_expand_the_declared_input(self):
        literal = self.workspace / "source-%03d.png"
        shutil.copyfile(self.source, literal)
        result = video.run(self.workspace, input_path=literal)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["input"]["path"], str(literal))
        encode = next(command for command in result["commands"] if command["phase"] == "ffmpeg-encode")
        pattern_index = encode["argv"].index("-pattern_type")
        self.assertEqual(encode["argv"][pattern_index + 1], "none")

    def test_unreadable_config_retains_failure_without_encoding(self):
        with mock.patch.object(video.media, "sha256_or_missing", return_value=None):
            result = video.run(self.workspace, input_path=self.source)
        self.assertFalse(result["passed"])
        self.assertEqual(result["commands"], [])
        self.assertFalse(result["configuration_protection"]["unchanged"])
        self.assertEqual(result["result_state"], "failed_evidence_retained")

    def test_schema_identity_duplicate_and_source_drift_are_denied_before_real_dispatch(self):
        original = json.loads(video.BINDING_MANIFEST.read_text(encoding="utf-8"))
        for drift in ("schema", "typed_schema", "identity", "duplicate", "source"):
            with self.subTest(drift=drift):
                manifest = copy.deepcopy(original)
                tool = next(tool for tool in manifest["tools"] if tool["id"] == "video-render")
                if drift == "schema":
                    tool["reviewed_binding"]["interface"]["duration_us"] = 2000000
                elif drift == "typed_schema":
                    tool["reviewed_binding"]["interface"]["input_direct_child"] = 1
                elif drift == "identity":
                    tool["reviewed_binding"]["identity"]["server"] = "different-remote-server"
                elif drift == "duplicate":
                    manifest["tools"].append(copy.deepcopy(tool))
                else:
                    tool["reviewed_binding"]["implementation_hashes"]["adapters/p4/ffmpeg_workflow.py"] = "changed"
                altered = self.workspace / f"{drift}-binding.json"
                altered.write_text(json.dumps(manifest), encoding="utf-8")
                with mock.patch.object(video, "BINDING_MANIFEST", altered):
                    result = video.run(self.workspace, Path(f"{drift}-receipt.json"), input_path=self.source)
                self.assertFalse(result["passed"])
                self.assertEqual(result["commands"], [])
                self.assertTrue(result["configuration_protection"]["unchanged"])
                self.assertFalse((self.workspace / "video-output.mp4").exists())

    def test_binding_changed_during_real_encoding_revokes_completion(self):
        binding = self.workspace / "binding.json"
        binding.write_bytes(video.BINDING_MANIFEST.read_bytes())
        original_append = video.media.append_process_command

        def append_with_change(receipt, phase, argv, cwd, timeout, parse_json=False, before_dispatch=None):
            result = original_append(receipt, phase, argv, cwd, timeout, parse_json, before_dispatch)
            if phase == "ffmpeg-encode":
                binding.write_text(binding.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return result

        with mock.patch.object(video, "BINDING_MANIFEST", binding), mock.patch.object(
                video.media, "append_process_command", side_effect=append_with_change):
            result = video.run(self.workspace, input_path=self.source)
        self.assertFalse(result["passed"])
        self.assertIn("drifted before dispatch", result["failure"]["message"])
        self.assertEqual(result["commands"][-1]["phase"], "ffmpeg-independent-decode")
        self.assertEqual(result["commands"][-1]["dispatch_guard"], "rejected")
        self.assertFalse(result["commands"][-1]["owned_process_exit_observed"])
        self.assertTrue((self.workspace / "video-output.mp4").is_file())


if __name__ == "__main__":
    unittest.main()
