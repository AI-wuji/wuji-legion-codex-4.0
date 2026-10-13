import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / ".dev/runtime-target/debug/wuji4.exe"
EXPORTED = ROOT / ".dev/native-protocol-schema-0.160.0"


class NativePreparationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = ROOT / ".dev/core-test-workspaces" / f"native-cli-{os.getpid()}-{time.time_ns()}"
        self.workspace.mkdir(parents=True)
        (self.workspace / "source.txt").write_text("G2准备测试，不调用模型。", encoding="utf-8")
        self.roles = self.call("prepared-roles", self.workspace)
        scope = self.roles["scope"]
        release = self.roles["release"]
        input_ref = {
            "id": "user/source", "type": "file", "scope": scope, "revision": 1,
            "sha256": hashlib.sha256((self.workspace / "source.txt").read_bytes()).hexdigest(),
            "release": release, "schema_version": 1,
        }
        nodes = [{
            "id": entry["kind"], "role_ref": entry["reference"], "owner": "p2-" + entry["kind"],
            "revision": 1, "inputs": [input_ref], "read_roots": ["source.txt"],
            "write_roots": [entry["kind"] + "-result.txt"],
            "acceptance_ids": entry["candidate"]["required_checks"], "status": "planned", "execution_form": "model",
        } for entry in self.roles["roles"]]
        self.plan = {
            "schema_version": 1, "contract_type": "WorkflowPlan",
            "payload": {
                "workflow_id": "native-cli", "version": "1", "catalog_version": release, "nodes": nodes,
                "edges": [{"from": "engineering", "to": "validation", "predicate": "depends-on"}],
                "budget": {
                    "max_candidates": 8, "max_query_objects": 20, "max_hops": 3,
                    "target_contract_bytes": 1024, "target_evidence_bytes": 1024,
                    "hard_bytes_limit": None, "measured_tokens": None, "effective_token_limit": None,
                    "wall_ms": 60000, "max_parallel_workers": 2, "max_extra_retries": 6,
                    "max_point_revisions": 2, "max_no_progress": 2,
                },
            },
            "metadata": {
                "id": "native-cli", "type": "WorkflowPlan", "scope": scope, "schema_version": 1,
                "revision": 1, "owner": "aji-local", "authority": "review_proposal", "status": "proposal",
                "source_refs": [], "evidence_refs": [], "created_at_utc_ms": 1, "updated_at_utc_ms": 1,
                "valid_until_utc_ms": None, "classification": "project_private", "content_hash": "0" * 64, "parent_refs": [],
            },
        }

    def call(self, *arguments, error=None):
        completed = subprocess.run(
            [str(EXECUTABLE), *map(str, arguments)], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if error:
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            result = json.loads(completed.stderr)
            self.assertEqual(result["error"], error, result)
            return result
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def seal(self):
        path = self.workspace / "proposal.json"
        path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
        self.plan["metadata"]["content_hash"] = self.call("object-hash", path)["sha256"]
        path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
        return path

    def test_only_two_prepared_roles_and_exact_source_links(self):
        self.assertEqual(len(self.roles["roles"]), 2)
        self.assertFalse(self.roles["runtime_admission"])
        self.assertEqual(self.roles["formal_model_experts"], 0)
        for entry in self.roles["roles"]:
            role = entry["candidate"]
            role_path = ROOT / "catalog/p2" / (entry["kind"] + ".json")
            self.assertEqual(hashlib.sha256(role_path.read_bytes()).hexdigest(), entry["reference"]["sha256"])
            self.assertEqual(json.loads(role_path.read_text(encoding="utf-8")), role)
            self.assertEqual(set(role["five_elements"]), {"goal", "inputs", "process", "output", "acceptance"})
            self.assertFalse(role["runtime_admission"])
            for origin in [role["baseline"], role["field_origins"]["five_elements"], role["field_origins"]["G2_minimum"], *role["field_origins"]["methods"]]:
                content = (ROOT / origin["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), origin["sha256"])
                if "pointer" in origin:
                    value = json.loads(content)
                    for part in origin["pointer"].split("/")[1:]:
                        value = value[int(part)] if isinstance(value, list) else value[part]
                    self.assertTrue(value)
            self.assertEqual({origin["candidate_id"] for origin in role["field_origins"]["methods"]}, set(role["atom_refs"]))

    def test_messages_match_exported_selected_schema_fields_and_remain_unbound(self):
        path = self.seal()
        for kind, effort in [("code", "high"), ("repair", "xhigh"), ("planning", "xhigh")]:
            prepared = self.call("prepare-native", self.workspace, path, "engineering", kind)
            for key, schema_name in [("thread_start", "ThreadStartParams.json"), ("turn_start_unbound", "TurnStartParams.json")]:
                message = prepared["candidate_messages"][key]
                params = message["params"]
                schema = json.loads((EXPORTED / "v2" / schema_name).read_text(encoding="utf-8"))
                self.assertTrue(set(params) <= set(schema["properties"]))
                self.assertTrue(set(schema.get("required", [])) <= set(params))
                for field, value in params.items():
                    field_types = schema["properties"][field].get("type")
                    if isinstance(field_types, str):
                        field_types = [field_types]
                    if field_types and value is not None:
                        type_name = "boolean" if isinstance(value, bool) else "string" if isinstance(value, str) else "array" if isinstance(value, list) else "object"
                        self.assertIn(type_name, field_types)
                self.assertEqual(params["model"], "gpt-6.1-sol")
            thread = prepared["candidate_messages"]["thread_start"]["params"]
            turn = prepared["candidate_messages"]["turn_start_unbound"]["params"]
            turn_schema = json.loads((EXPORTED / "v2/TurnStartParams.json").read_text(encoding="utf-8"))
            effort_shape = turn_schema["definitions"]["ReasoningEffort"]
            self.assertEqual(effort_shape["type"], "string")
            self.assertGreaterEqual(len(effort), effort_shape["minLength"])
            self.assertEqual(turn["effort"], effort)
            self.assertEqual(thread["sandbox"], "read-only")
            read_only = next(branch for branch in turn_schema["definitions"]["SandboxPolicy"]["oneOf"] if branch["title"] == "ReadOnlySandboxPolicy")
            self.assertEqual(turn["sandboxPolicy"]["type"], read_only["properties"]["type"]["enum"][0])
            self.assertFalse(turn["sandboxPolicy"]["networkAccess"])
            self.assertEqual(turn["input"][0]["type"], "text")
            self.assertIn("not-yet-bound", turn["threadId"])
            self.assertFalse(prepared["dispatchable"])
            self.assertFalse(prepared["generation_submitted"])
            self.assertEqual(prepared["effective"]["model"], "unknown")
        self.assertFalse((self.workspace / ".wuji4").exists())
        self.assertFalse((self.workspace / "engineering-result.txt").exists())

    def test_external_success_model_and_fee_claims_cannot_grant_admission(self):
        self.plan["payload"]["effective_model"] = "gpt-6.1-sol"
        self.call("prepare-native", self.workspace, self.seal(), "engineering", "code", error="Shape")
        del self.plan["payload"]["effective_model"]
        self.plan["payload"]["host_receipt"] = {"no_fee": True, "closed": True}
        self.call("prepare-native", self.workspace, self.seal(), "engineering", "code", error="Shape")
        del self.plan["payload"]["host_receipt"]
        self.call("prepare-native", self.workspace, self.seal(), "engineering", "auto", error="Shape")
        self.plan["metadata"]["authority"] = "user_explicit"
        self.call("prepare-native", self.workspace, self.seal(), "engineering", "code", error="AuthorityDenied")
        self.assertFalse((self.workspace / ".wuji4").exists())

    def test_deterministic_preparation_is_not_running_product_or_self_review(self):
        path = self.seal()
        prepared = self.call("prepare-native", self.workspace, path, "engineering", "code")
        repeated = self.call("prepare-native", self.workspace, path, "engineering", "code")
        self.assertEqual(prepared, repeated)
        self.call("prepare-native", self.workspace, path, "engineering", "text", error="Reference")
        self.plan["payload"]["nodes"][1]["owner"] = self.plan["payload"]["nodes"][0]["owner"]
        self.call("prepare-native", self.workspace, self.seal(), "validation", "code", error="SelfReview")
        self.assertFalse(self.call("host-status")["native_host_verified"])
        self.assertFalse((self.workspace / ".wuji4").exists())


if __name__ == "__main__":
    unittest.main()
