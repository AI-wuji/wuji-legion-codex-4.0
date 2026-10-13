import hashlib
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
ADAPTER = ROOT / "adapters/p4/software_repair_adapter.py"
SOURCE = ROOT / ".dev/native-p2-workspace-20261003-u/engineering-result.py"


class P4AdapterTests(unittest.TestCase):
    def test_comfyui_bounded_probe_artifact_is_hash_and_dimension_bound(self):
        evidence = json.loads((ROOT / "outputs/p4/comfyui-probe-evidence.json").read_text(encoding="utf-8"))
        artifact = ROOT / evidence["artifact"]["path"]
        content = artifact.read_bytes()
        self.assertEqual(evidence["status"], "bounded_real_probe_passed")
        self.assertEqual(evidence["version_observed"], "0.37.0")
        self.assertEqual(evidence["artifact"]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(evidence["artifact"]["bytes"], len(content))
        self.assertEqual(content[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", content[16:24]), (64, 64))

    def test_ffmpeg_bounded_probe_artifact_is_hash_bound(self):
        evidence = json.loads((ROOT / "outputs/p4/ffmpeg-probe-evidence.json").read_text(encoding="utf-8"))
        artifact = ROOT / evidence["artifact"]["path"]
        content = artifact.read_bytes()
        self.assertEqual(evidence["status"], "bounded_real_probe_passed")
        self.assertEqual(evidence["version_observed"], "ffmpeg version 7.1")
        self.assertEqual(evidence["artifact"]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(evidence["artifact"]["bytes"], len(content))
        self.assertIn(b"ftyp", content[:64])
        self.assertEqual(evidence["validation"]["decode_to_null_exit_code"], 0)

    def test_available_adapter_emits_hash_bound_pass_report(self):
        report = ROOT / "outputs/p4/test-adapter-report.json"
        completed = subprocess.run([PYTHON, "-B", str(ADAPTER), str(SOURCE), str(report)], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual("passed", data["status"])
        self.assertEqual(data["result"]["passed"], True)
        self.assertEqual(len(data["result"]["tests"]), 11)
        self.assertFalse(data["native_or_professional_claim"])
        report.unlink()

    def test_adapter_rejects_path_outside_project(self):
        completed = subprocess.run([PYTHON, "-B", str(ADAPTER), str(Path("C:/Windows/win.ini")), str(ROOT / "outputs/p4/escape.json")], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(1, completed.returncode)
        self.assertIn("escapes project root", completed.stdout)


if __name__ == "__main__":
    unittest.main()
