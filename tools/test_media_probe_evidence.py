import hashlib
import json
from pathlib import Path
import unittest
import wave

from p6_package_validation import confined_path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MediaProbeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.proof = json.loads((ROOT / "outputs/p4/media-contract-probe-evidence.json").read_text(encoding="utf-8"))

    def test_real_artifacts_source_hashes_and_pcm_profile_are_current(self):
        self.assertTrue(self.proof["passed"])
        for relative, checksum in self.proof["sources"].items():
            self.assertEqual(digest(confined_path(ROOT, relative)), checksum)
        self.assertEqual(digest(ROOT / ".dev/runtime-target/debug/wuji4.exe"), self.proof["core_binary_sha256"])
        for artifact in self.proof["artifacts"]:
            path = confined_path(ROOT, artifact["path"])
            self.assertEqual(path.stat().st_size, artifact["bytes"])
            self.assertEqual(digest(path), artifact["sha256"])
            if path.suffix == ".wav":
                with wave.open(str(path), "rb") as source:
                    self.assertEqual(source.getframerate(), self.proof["actual_pcm_profile"]["sample_rate"])
                    self.assertEqual(source.getnframes(), self.proof["actual_pcm_profile"]["sample_frames"])

    def test_preparation_decode_and_expected_negative_are_not_professional_completion(self):
        receipts = self.proof["core_process_receipts"]
        self.assertTrue(all(row["matched"] and row["owned_process_exit_observed"] for row in receipts))
        self.assertTrue(any(row["expected_error"] == "Reference" and row["exit_code"] != 0 for row in receipts))
        self.assertEqual(self.proof["ffmpeg"]["decode_exit_code"], 0)
        self.assertEqual(digest(Path(self.proof["ffmpeg"]["binary_path"])), self.proof["ffmpeg"]["binary_sha256"])
        self.assertFalse(self.proof["ffmpeg"]["audio_device_opened"])
        self.assertEqual(self.proof["prepared"]["state"], "prepared")
        self.assertFalse(self.proof["prepared"]["runtime_admission"])
        self.assertFalse(self.proof["G4_passed"])
        self.assertFalse(self.proof["REAPER_executed"])
        self.assertFalse(self.proof["P7"])
        self.assertEqual(self.proof["protected_codex_configuration"]["before"], self.proof["protected_codex_configuration"]["after"])


if __name__ == "__main__":
    unittest.main()
