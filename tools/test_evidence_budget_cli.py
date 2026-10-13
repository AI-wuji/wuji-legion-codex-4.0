import hashlib
import json
import unittest

import test_core_cli


class EvidenceBudgetCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core_cli.CoreCliTests("test_complete_copy_repeat_and_current_file")
        self.fixture.setUp()
        self.root = self.fixture.workspace

    def configuration(self, name, threshold):
        value = {"schema_version": 1, "host_class": "local_codex", "model": "gpt-6.1-sol", "config_revision": 1,
                 "values": {"tool_output_token_limit": 4096, "model_auto_compact_token_limit": threshold,
                            "auto_compact_scope": "body_after_prefix", "configured_context_window": None,
                            "skills_max_context_tokens": None, "max_threads": 3}}
        path = self.fixture.write_json(name, value)
        reference = self.fixture.call("register-input", self.root, f"user/{name}", path.name)
        ref_path = self.fixture.write_json(f"{name}-ref.json", reference)
        return self.fixture.call("budget-configuration", self.root, ref_path), ref_path

    def test_t70_actual_large_json_copy_and_paged_readback_preserve_errors_and_not_fee_limits(self):
        payload = {"state": "failed", "content": "完整资料与权限🧭" * 1300,
                   "errors": [{"kind": "AuthorityDenied", "detail": "Original failure remains readable"}],
                   "permissions": {"allowed": ["read"], "denied": ["charge", "publish", "modify_config"]},
                   "safety": {"white_hat": True, "native_authority": False}}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.assertGreater(len(raw), 4096)
        (self.root / "source.txt").write_bytes(raw)
        source = self.fixture.call("register-input", self.root, "user/source", "source.txt")
        plan = self.fixture.plan(source)
        path = self.fixture.seal(plan)
        self.fixture.call("plan", self.root, path)
        result = self.fixture.call("run-local", self.root, "cli-task", "copy", "source.txt", "result.txt")
        self.assertFalse(result["professional_or_native_verified"])
        self.assertEqual((self.root / "result.txt").read_bytes(), raw)
        reference = self.fixture.call("register-input", self.root, "user/full-evidence", "result.txt")
        ref_path = self.fixture.write_json("evidence-ref.json", reference)
        offset = 0
        rebuilt = bytearray()
        pages = 0
        while True:
            page = self.fixture.call("read-evidence", self.root, ref_path, offset, 4096)
            pages += 1
            self.assertEqual(page["reference"], reference)
            self.assertEqual(page["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(page["total_bytes"], len(raw))
            self.assertFalse(page["evidence_truncated"])
            self.assertFalse(page["failure_fields_filtered"])
            self.assertFalse(page["safety_fields_filtered"])
            self.assertFalse(page["fee_hard_limit"])
            self.assertFalse(page["execution_authority"])
            rebuilt.extend(bytes.fromhex(page["page_hex"]))
            self.assertEqual(page["next_offset"], len(rebuilt))
            if page["complete"]:
                break
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertGreater(pages, 1)
        self.assertEqual(bytes(rebuilt), raw)
        self.assertEqual(json.loads(rebuilt), payload)
        for threshold in (240000, 90000):
            declaration, _ = self.configuration(f"budget-{threshold}.json", threshold)
            self.assertEqual(declaration["configured"]["values"]["model_auto_compact_token_limit"], threshold)
            self.assertEqual(declaration["effective"]["context_window"], "unknown")
            self.assertEqual(declaration["effective"]["directory_budget"], "unknown")
            self.assertFalse(declaration["fee_hard_limit"])
            self.assertFalse(declaration["budget_semantics"]["directory_budget_calculated"])
        self.fixture.call("read-evidence", self.root, ref_path, len(raw) + 1, 4096, expected_error="Shape")
        self.fixture.call("read-evidence", self.root, ref_path, 0, 0, expected_error="BudgetExhausted")
        self.fixture.call("read-evidence", self.root, ref_path, 0, 16385, expected_error="BudgetExhausted")
        (self.root / "result.txt").write_bytes(b"changed after last page")
        self.fixture.call("read-evidence", self.root, ref_path, 0, 4096, expected_error="ValidationStale")

    def test_configuration_cli_rejects_effective_fields_and_update_replay(self):
        observation, ref_path = self.configuration("budget.json", 90000)
        self.assertEqual(observation["configured_state"], "configured_only")
        self.assertFalse(observation["observed"]["active_config_observed"])
        self.assertFalse(observation["native_host_verified"])
        configured = observation["configured"]
        configured["effective"] = {"context_window": 272000}
        file_path = self.fixture.write_json("forged.json", configured)
        forged = self.fixture.call("register-input", self.root, "user/forged", file_path.name)
        forged_ref = self.fixture.write_json("forged-ref.json", forged)
        self.fixture.call("budget-configuration", self.root, forged_ref, expected_error="Shape")
        (self.root / "budget.json").write_text("changed declaration", encoding="utf-8")
        self.fixture.call("budget-configuration", self.root, ref_path, expected_error="ValidationStale")


if __name__ == "__main__":
    unittest.main()
