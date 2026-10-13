import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from adapters.p4 import ffmpeg_workflow as video


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class P4ToolBindingTests(unittest.TestCase):
    @contextmanager
    def video_binding_fixture(self):
        with tempfile.TemporaryDirectory(
                prefix="t85-binding-", dir=ROOT / ".dev/core-test-workspaces") as temporary:
            fixture_root = Path(temporary)
            implementation_hashes = {}
            for relative in ("adapters/p4/ffmpeg_workflow.py", "adapters/p4/media_workflow.py", "tools/wuji4.py"):
                source = fixture_root / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes((ROOT / relative).read_bytes())
                implementation_hashes[relative] = digest(source)
            manifest = {
                "schema_version": 1,
                "tools": [{
                    "id": video.VIDEO_TOOL_ID,
                    "status": "available-local-bounded",
                    "runtime_admission": True,
                    "version": video.VIDEO_TOOL_VERSION,
                    "adapter": "adapters/p4/ffmpeg_workflow.py",
                    "workflow_entrypoint": "tools/wuji4.py run-video",
                    "reviewed_binding": {
                        "revision": 1,
                        "identity": {
                            "server": video.VIDEO_TOOL_SERVER,
                            "tool": video.VIDEO_TOOL_NAME,
                            "entrypoint": video.media.DEFAULT_FFMPEG.as_posix(),
                            "binary_sha256": video.media.PINNED_FFMPEG_SHA256,
                            "version_prefix": "ffmpeg version 7.1-essentials_build-",
                        },
                        "interface": copy.deepcopy(video.VIDEO_INTERFACE),
                        "implementation_hashes": implementation_hashes,
                    },
                }],
            }
            binding = fixture_root / "tool-manifest.json"
            binding.write_text(json.dumps(manifest), encoding="utf-8")
            with mock.patch.object(video, "ROOT", fixture_root), mock.patch.object(video, "BINDING_MANIFEST", binding):
                yield fixture_root, manifest

    def test_video_binding_includes_exact_version_schema_and_identity(self):
        with self.video_binding_fixture():
            binding = video.reviewed_binding()
        self.assertEqual(binding["tool_id"], "video-render")
        self.assertEqual(binding["version"], "ffmpeg-7.1-observed")
        self.assertEqual(binding["identity"]["server"], "local-process")
        self.assertEqual(binding["identity"]["tool"], "video-render/png-to-mp4")
        self.assertEqual(binding["interface"], video.VIDEO_INTERFACE)
        self.assertEqual(binding["implementation_hashes"], {
            relative: digest(ROOT / relative) for relative in binding["implementation_hashes"]
        })

    def test_video_binding_rejects_same_name_alias_and_directory_fallback(self):
        for mutation in ("same-name", "missing-target"):
            with self.subTest(mutation=mutation), self.video_binding_fixture() as (_, manifest):
                video.reviewed_binding()
                if mutation == "same-name":
                    alias = copy.deepcopy(next(tool for tool in manifest["tools"] if tool["id"] == "video-render"))
                    alias["id"] = "video-render-alias"
                    manifest["tools"].append(alias)
                else:
                    manifest["tools"] = [tool for tool in manifest["tools"] if tool["id"] != "video-render"]
                video.BINDING_MANIFEST.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "ambiguous|Exact unique"):
                    video.reviewed_binding()

    def test_video_dispatch_rejects_binding_drift_before_process_start(self):
        with self.video_binding_fixture() as (fixture_root, _):
            workspace = fixture_root / ".dev/core-test-workspaces/dispatch"
            workspace.mkdir(parents=True)
            source = workspace / "source.png"
            source.write_bytes((ROOT / "outputs/p4/comfyui-probe-output.png").read_bytes())
            binding = video.BINDING_MANIFEST
            expected_binding = video.reviewed_binding()
            video.require_current_binding(expected_binding)
            original_append = video.media.append_process_command
            process_calls = []

            def mutate_before_dispatch(receipt, phase, argv, cwd, timeout, parse_json=False, before_dispatch=None):
                if phase == "ffmpeg-version":
                    binding.write_text(binding.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                return original_append(receipt, phase, argv, cwd, timeout, parse_json, before_dispatch)

            with mock.patch.object(
                    video.media, "append_process_command", side_effect=mutate_before_dispatch), mock.patch.object(
                    video.media.subprocess, "run", side_effect=lambda *args, **kwargs: process_calls.append(args) or None):
                result = video.run(workspace, input_path=source)

            self.assertFalse(result["passed"])
            self.assertIn("drifted before dispatch", result["failure"]["message"])
            self.assertEqual(process_calls, [])
            self.assertEqual(result["commands"][0]["phase"], "ffmpeg-version")
            self.assertEqual(result["commands"][0]["dispatch_guard"], "rejected")
            self.assertFalse(result["commands"][0]["owned_process_exit_observed"])

    def test_video_binding_rejects_schema_identity_version_duplicate_and_source_drift(self):
        mutations = {
            "manifest-schema": "schema is unsupported",
            "interface-schema": "identity or interface schema drift",
            "typed-interface": "identity or interface schema drift",
            "identity": "identity or interface schema drift",
            "version": "version or reviewed binding is not admitted",
            "duplicate-id": "Exact unique",
            "source-hash": "implementation drift",
            "source-bytes": "implementation drift",
        }
        for mutation, message in mutations.items():
            with self.subTest(mutation=mutation), self.video_binding_fixture() as (fixture_root, manifest):
                video.reviewed_binding()
                tool = manifest["tools"][0]
                if mutation == "manifest-schema":
                    manifest["schema_version"] = 2
                elif mutation == "interface-schema":
                    tool["reviewed_binding"]["interface"]["duration_us"] = 2000000
                elif mutation == "typed-interface":
                    tool["reviewed_binding"]["interface"]["input_direct_child"] = 1
                elif mutation == "identity":
                    tool["reviewed_binding"]["identity"]["server"] = "different-remote-server"
                elif mutation == "version":
                    tool["version"] = "unverified-version"
                elif mutation == "duplicate-id":
                    manifest["tools"].append(copy.deepcopy(tool))
                elif mutation == "source-hash":
                    tool["reviewed_binding"]["implementation_hashes"]["tools/wuji4.py"] = "changed"
                else:
                    (fixture_root / "tools/wuji4.py").write_bytes(b"changed isolated source")
                video.BINDING_MANIFEST.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    video.reviewed_binding()

    def test_video_historical_binding_and_execution_evidence_are_rejected_as_stale(self):
        manifest_path = video.BINDING_MANIFEST
        evidence_path = ROOT / "outputs/p4/video-framework-workflow-evidence.json"
        manifest_before = manifest_path.read_bytes()
        evidence_before = evidence_path.read_bytes()
        with self.video_binding_fixture() as (_, manifest):
            video.reviewed_binding()
            manifest["tools"][0]["reviewed_binding"]["implementation_hashes"]["tools/wuji4.py"] = "0" * 64
            video.BINDING_MANIFEST.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "implementation drift"):
                video.reviewed_binding()
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(evidence_path.read_bytes(), evidence_before)

    def test_framework_video_evidence_binds_current_sources_artifact_and_real_decode(self):
        evidence = load_json("outputs/p4/video-framework-workflow-evidence.json")
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["result_state"], "completed_bounded_task")
        self.assertEqual(evidence["framework_execution"]["exit_code"], 0)
        self.assertEqual(evidence["framework_execution"]["source_sha256"], digest(ROOT / "tools/wuji4.py"),
                         "stale video execution evidence: framework source changed; no video rerun is claimed")
        for relative, expected in evidence["implementation_hashes"].items():
            self.assertEqual(expected, digest(ROOT / relative))
        artifact = evidence["retained_artifact"]
        self.assertEqual(artifact["sha256"], digest(ROOT / artifact["path"]))
        self.assertEqual(artifact["sha256"], evidence["artifacts"]["mp4"]["sha256"])
        self.assertTrue(all(evidence["checks"].values()))
        binding = evidence["reviewed_binding"]
        self.assertEqual(binding["manifest_sha256"], digest(ROOT / "catalog/p4/tool-manifests.json"))
        self.assertEqual(binding["identity"]["server"], "local-process")
        self.assertEqual(binding["identity"]["tool"], "video-render/png-to-mp4")
        self.assertTrue(evidence["checks"]["reviewed_binding_current"])
        decode = next(command for command in evidence["commands"] if command["phase"] == "ffmpeg-independent-decode")
        self.assertEqual(decode["exit_code"], 0)
        self.assertTrue(decode["owned_process_exit_observed"])
        self.assertEqual(evidence["validation"]["progress"]["frame"], "8")
        self.assertEqual(evidence["validation"]["progress"]["out_time_us"], "1000000")
        self.assertFalse(evidence["comfyui_submitted"])
        self.assertFalse(evidence["audio_device_opened"])
        self.assertFalse(evidence["P7"])

    def test_comfyui_historical_probe_is_not_reported_as_current_health(self):
        tool = next(tool for tool in load_json("catalog/p4/tool-manifests.json")["tools"] if tool["id"] == "comfyui")
        self.assertEqual(tool["status"], "blocked")
        self.assertFalse(tool["runtime_admission"])
        self.assertEqual(tool["current_health_evidence"], "outputs/p4/media-framework-failure-evidence.json")
        self.assertNotEqual(tool["bounded_evidence"], tool["current_health_evidence"])

    def test_office_document_binding_has_bounded_word_and_sheet_contract(self):
        manifest = load_json("catalog/p4/tool-manifests.json")
        tool = next(tool for tool in manifest["tools"] if tool["id"] == "officecli-documents")
        self.assertEqual(tool["status"], "available-local-bounded")
        self.assertTrue(tool["runtime_admission"])
        self.assertEqual(tool["adapter"], "adapters/p4/office_document_workflow.py")
        self.assertIn("word", tool["action_contract"]["input"])
        self.assertIn("sheet", tool["action_contract"]["input"])
        self.assertFalse(tool["action_contract"]["permissions"].find("global") == -1)

    def test_office_document_evidence_preserves_xlsx_success_and_word_render_block(self):
        evidence = load_json("outputs/p4/office-document-workflow-evidence.json")
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["status"], "partial_evidence_retained")
        self.assertTrue(evidence["formats"]["sheet"]["passed"])
        self.assertEqual(evidence["formats"]["sheet"]["build"]["grand_total"], "481.00")
        self.assertFalse(evidence["formats"]["word"]["passed"])
        self.assertEqual(evidence["formats"]["word"]["failure"]["type"], "render_unavailable")
        self.assertTrue(evidence["summary"]["word_structure_and_officecli_readback"])
        self.assertFalse(evidence["summary"]["word_required_render"])
        self.assertTrue(evidence["summary"]["word_render_blocked_external"])
        self.assertTrue(evidence["summary"]["configuration_unchanged"])
        for relative, expected in evidence["implementation_hashes"].items():
            self.assertEqual(expected, digest(ROOT / relative))
        for result in evidence["formats"].values():
            for artifact in (result["receipt"], result["framework_output"], result["artifact"]):
                path = ROOT / artifact["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(artifact["sha256"], digest(path))

    def test_manifest_binds_current_tool_versions_contracts_and_evidence(self):
        manifest = load_json("catalog/p4/tool-manifests.json")
        tools = manifest["tools"]
        self.assertEqual(len({tool["id"] for tool in tools}), len(tools))
        by_id = {tool["id"]: tool for tool in tools}
        for tool in tools:
            self.assertTrue(tool["owner"])
            self.assertIn(tool["status"], {"available-local", "available-local-bounded", "blocked"})
            if tool["status"] == "blocked":
                self.assertTrue(tool.get("reason"))
            else:
                self.assertTrue(tool["version"])
                self.assertIn("action_contract", tool)
                self.assertIsInstance(tool["action_contract"], dict)
                self.assertIn("failure", tool["action_contract"])
            self.assertIsInstance(tool["runtime_admission"], bool)

        comfy = load_json("outputs/p4/comfyui-probe-evidence.json")
        self.assertTrue(by_id["comfyui"]["version"].startswith(comfy["version_observed"]))
        self.assertEqual(by_id["comfyui"]["endpoint"], comfy["endpoint"])
        self.assertEqual([node["class_type"] for node in comfy["workflow"]],
                         ["LoadImage", "ImageScale", "SaveImage"])
        comfy_artifact = ROOT / comfy["artifact"]["path"]
        self.assertEqual(comfy["artifact"]["sha256"], digest(comfy_artifact))

        video = load_json("outputs/p4/ffmpeg-probe-evidence.json")
        ffmpeg = Path(video["binary_path"])
        self.assertIn("7.1", by_id["video-render"]["version"])
        self.assertTrue(ffmpeg.is_file())
        self.assertEqual(video["version_observed"], "ffmpeg version 7.1")
        video_artifact = ROOT / video["artifact"]["path"]
        self.assertEqual(video["artifact"]["sha256"], digest(video_artifact))
        self.assertEqual(video["validation"]["decode_to_null_exit_code"], 0)

        office = load_json("outputs/p4/officecli-probe-evidence.json")
        office_binary = Path(office["binary_path"])
        self.assertEqual(by_id["officecli"]["version"], "1.0.152-exact-original-release-observed")
        self.assertTrue(office["passed"])
        self.assertEqual(office["binary_sha256"], digest(office_binary))
        self.assertEqual(office["adapter_sha256"], digest(ROOT / "adapters/p4/officecli_adapter.py"))
        office_artifact = ROOT / office["artifact"]["path"]
        self.assertEqual(office["artifact"]["sha256"], digest(office_artifact))

        framework_office = load_json("outputs/p4/officecli-framework-workflow-evidence.json")
        self.assertEqual(framework_office["state"], "completed_bounded_task")
        self.assertTrue(framework_office["passed"])
        self.assertEqual(framework_office["artifact"]["sha256"], digest(Path(framework_office["artifact"]["path"])))
        self.assertEqual(framework_office["protected_configurations_before"],
                         framework_office["protected_configurations_after"])

    def test_changed_binding_evidence_is_not_accepted_as_current(self):
        manifest = load_json("catalog/p4/tool-manifests.json")
        evidence = load_json("outputs/p4/officecli-probe-evidence.json")
        office_tool = next(tool for tool in manifest["tools"] if tool["id"] == "officecli")
        original_version = office_tool["version"]
        self.assertTrue(original_version.startswith(evidence["version"]))
        office_tool["version"] = "unverified-version"
        self.assertFalse(office_tool["version"].startswith(evidence["version"]))
        office_tool["version"] = original_version
        original_adapter_hash = evidence["adapter_sha256"]
        evidence["adapter_sha256"] = "tampered"
        self.assertNotEqual(evidence["adapter_sha256"], digest(ROOT / "adapters/p4/officecli_adapter.py"))
        evidence["adapter_sha256"] = original_adapter_hash

        media_failure = load_json("outputs/p4/media-framework-failure-evidence.json")
        self.assertEqual(media_failure["status"], "failed_real_error")
        self.assertEqual(media_failure["failure"]["code"], "comfyui_unavailable")
        self.assertTrue(media_failure["configuration_protection"]["unchanged"])
        self.assertFalse(media_failure["P7"])


if __name__ == "__main__":
    unittest.main()
