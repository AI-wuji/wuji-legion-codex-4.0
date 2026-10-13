import copy
import hashlib
import json
import sqlite3
import unittest
from unittest import mock

import run_legion_task as legion
import test_core_cli
import test_resource_cli


REVIEW_PERMIT = "confirm-isolated-project-resource-review"
TRIGGER = "legion-route-manifest"
METHOD = json.dumps({
    "consumer": "isolated-manifest-regression",
    "route": "engineering",
    "reject_activation": ["installed", "automatic_discovery_enabled", "P7"],
    "reject_duplicate_keys": ["authority", "installed", "automatic_discovery_enabled", "P7"],
}, sort_keys=True)
COUNTEREXAMPLES = [
    "Repeated prose is not a duplicate JSON key.",
    "This test consumer does not authorize installation, discovery, P7 or current Codex configuration changes.",
    "A local review is not automatic model learning, universal truth or all-professional effectiveness.",
]


class ExperienceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.resources = test_resource_cli.ResourceCliTests("test_review_requires_explicit_isolated_permit")
        self.resources.setUp()
        self.fixture = self.resources.fixture
        self.workspace = self.fixture.workspace
        self.scope = self.fixture.initial["scope"]
        self.failures = []

    @staticmethod
    def database_snapshot(fixture):
        database = fixture.workspace / ".wuji4/state.sqlite"
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            return tuple(connection.iterdump())

    def rejected_without_writes(self, fixture, *arguments, error):
        before = self.database_snapshot(fixture)
        result = fixture.call(*arguments, expected_error=error)
        after = self.database_snapshot(fixture)
        self.assertEqual(after, before, arguments)
        event = arguments[5] if arguments[0] == "resource-propose" else arguments[4]
        self.failures.append({"command": arguments[0], "case": event, "resource_kind": arguments[2], "error": result["error"],
                              "failed_database_writes": int(after != before)})
        return result

    def query(self, kind, trigger="", fixture=None):
        fixture = fixture or self.fixture
        return fixture.call("resource-query", fixture.workspace, kind, trigger, 8)

    def propose(self, kind, envelope, event, expected_revision=0):
        path = self.fixture.seal(envelope, event + ".json")
        checked = self.fixture.call("check", path)
        self.assertEqual(checked["shape_and_object_hash"], "pass")
        result = self.fixture.call("resource-propose", self.workspace, kind, path, expected_revision, event)
        self.assertEqual(result["state"], "candidate")
        self.assertFalse(result["runtime_admission"])
        self.assertFalse(result["production_or_global_admission"])
        return result["reference"]

    def review(self, kind, reference, event):
        path = self.fixture.write_json(event + "-reference.json", reference)
        result = self.fixture.call("resource-review-local", self.workspace, kind, path, event, REVIEW_PERMIT)
        self.assertEqual(result["reference"], reference)
        self.assertEqual(result["state"], "active_local")
        self.assertFalse(result["runtime_admission"])
        self.assertFalse(result["global_admission"])
        self.assertEqual(result["professional_effectiveness"], "not_claimed")

    def experience(self, knowledge_ref, method=METHOD, trigger=TRIGGER, kind="failure_condition"):
        metadata = self.fixture.plan()["metadata"]
        metadata.update(id="experience/manifest-regression", type="ExperienceCandidate")
        return {"schema_version": 1, "contract_type": "ExperienceCandidate", "metadata": metadata,
                "payload": {"scope": self.scope, "trigger": trigger, "method": method,
                            "evidence": [self.resources.source], "counterexamples": list(COUNTEREXAMPLES),
                            "expiry_utc_ms": None, "type": kind, "knowledge_refs": [knowledge_ref]}}

    def observe_manifest_guards(self, method, label):
        parameters = json.loads(method)
        self.assertEqual(parameters["consumer"], "isolated-manifest-regression")
        manifest = json.loads((test_core_cli.ROOT / "legion/task-entry.json").read_text(encoding="utf-8"))
        pack = self.workspace / label
        pack.mkdir()
        for relative in (manifest["entry"], manifest["routes"][parameters["route"]]):
            path = pack / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Independent 4.0 test guidance; no execution authority.", encoding="utf-8")
        entry = pack / "task-entry.json"
        observations = []
        with mock.patch.object(legion, "PACK", pack):
            entry.write_text(json.dumps(manifest), encoding="utf-8")
            valid = legion.route(parameters["route"])
            self.assertEqual(valid["state"], "guidance_loaded_not_executed")
            self.assertEqual(len(valid["context"]), 2)
            self.assertEqual(valid["actual_agents_started"], 0)
            self.assertFalse(valid["model_generation_submitted"])
            self.assertFalse(valid["execution_authority"])
            for field in parameters["reject_activation"]:
                with self.subTest(consumer=label, activation=field):
                    entry.write_text(json.dumps(dict(manifest, **{field: True})), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "isolated uninstalled") as rejected:
                        legion.route(parameters["route"])
                    observations.append({"case": field + "=true", "error": str(rejected.exception)})
            for field in parameters["reject_duplicate_keys"]:
                with self.subTest(consumer=label, duplicate=field):
                    serialized = json.dumps(manifest)
                    entry.write_text(serialized[:-1] + "," + json.dumps(field) + ":false}", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Duplicate") as rejected:
                        legion.route(parameters["route"])
                    observations.append({"case": "duplicate:" + field, "error": str(rejected.exception)})
            benign = dict(manifest, authority="Repeated prose. Repeated prose.")
            entry.write_text(json.dumps(benign), encoding="utf-8")
            self.assertEqual(legion.route(parameters["route"])["state"], "guidance_loaded_not_executed")
        return {"rejections": observations, "repeated_prose_accepted": True}

    def consume_manifest_experience(self, trigger, label):
        selected = self.query("experience", trigger)
        if not trigger or len(selected["entries"]) != 1:
            raise ValueError("No exact reviewed experience for this task")
        entry = selected["entries"][0]
        payload = entry["envelope"]["payload"]
        if payload["trigger"] != trigger:
            raise ValueError("No exact reviewed experience for this task")
        self.assertEqual(entry["reference"]["scope"], self.scope)
        self.assertEqual(entry["envelope"]["metadata"]["classification"], "project_private")
        self.assertEqual(entry["envelope"]["metadata"]["owner"], "aji-local")
        knowledge = self.query("knowledge")["entries"]
        linked = [record for record in knowledge if record["reference"] in payload["knowledge_refs"]]
        self.assertEqual([record["reference"] for record in linked], payload["knowledge_refs"])
        self.assertEqual(len(linked), 1)
        source = linked[0]["envelope"]["payload"]
        self.assertEqual(source["source_refs"], payload["evidence"])
        evidence_path = (self.workspace / source["location"].rsplit(":", 1)[0]).resolve()
        self.assertTrue(evidence_path.is_relative_to(self.workspace.resolve()))
        evidence_bytes = evidence_path.read_bytes()
        self.assertEqual(hashlib.sha256(evidence_bytes).hexdigest(), payload["evidence"][0]["sha256"])
        prior = json.loads(evidence_bytes)
        self.assertEqual(prior["method"], payload["method"])
        actual = self.observe_manifest_guards(payload["method"], label + "-pack")
        self.assertEqual(actual, prior["observations"])
        return self.fixture.write_json(label + ".json", {
            "consumer": "bounded_test_consumer_not_runtime_learning",
            "trigger": trigger, "experience_ref": entry["reference"],
            "knowledge_refs": payload["knowledge_refs"], "exact_method": payload["method"],
            "evidence_refs_used": payload["evidence"], "counterexamples": payload["counterexamples"],
            "actual_followup": actual, "automatic_model_learning": False,
            "all_professional_effectiveness": "not_claimed", "full_user_acl": "not_implemented",
            "requested_model": "gpt-6.1-sol", "effective_model": "unknown",
            "requested_reasoning": "high", "effective_reasoning": "unknown",
            "P7": False,
        })

    def assert_self_grants_and_stale_queries_rejected(self, knowledge, knowledge_ref, experience, experience_ref, evidence):
        pending = []
        for kind, envelope in (("knowledge", knowledge), ("experience", experience)):
            mutations = [("public", "metadata", "classification", "public", "AuthorityDenied"),
                         ("user-authority", "metadata", "authority", "user_explicit", "AuthorityDenied"),
                         ("universal-authority", "metadata", "authority", "universal", "Shape"),
                         ("universal-scope", "metadata", "scope", "universal", "ScopeDenied")]
            if kind == "knowledge":
                mutations.append(("fact-authority", "payload", "authority", "user_explicit", "AuthorityDenied"))
            else:
                mutations.append(("no-counterexample", "payload", "counterexamples", [], "Shape"))
            for label, section, field, value, error in mutations:
                with self.subTest(kind=kind, self_grant=label):
                    forged = copy.deepcopy(envelope)
                    forged[section][field] = value
                    if label == "universal-scope":
                        forged["payload"]["scope"] = value
                    path = self.fixture.seal(forged, kind + "-" + label + ".json")
                    self.rejected_without_writes(self.fixture, "resource-propose", self.workspace, kind, path, 0,
                                                 kind + "-" + label, error=error)
            revised = copy.deepcopy(envelope)
            revised["metadata"]["revision"] = 2
            pending.append((kind, revised, self.propose(kind, revised, kind + "-pending", expected_revision=1)))
        evidence.write_text("Changed after local reviews; old ExactRefs must not be reused.", encoding="utf-8")
        self.assertNotEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(), self.resources.source["sha256"])
        before = self.database_snapshot(self.fixture)
        stale_queries = {}
        for kind, reference in (("knowledge", knowledge_ref), ("experience", experience_ref)):
            result = self.query(kind, TRIGGER if kind == "experience" else "")
            self.assertEqual(result["entries"], [])
            self.assertEqual(result["rejected"], [{"reference": reference, "reason": "ValidationStale"}])
            stale_queries[kind] = result
        self.assertEqual(self.database_snapshot(self.fixture), before)
        with self.assertRaisesRegex(ValueError, "No exact reviewed"):
            self.consume_manifest_experience(TRIGGER, "stale-followup")
        self.assertFalse((self.workspace / "stale-followup.json").exists())
        self.assertFalse((self.workspace / "stale-followup-pack").exists())
        for kind, envelope, reference in pending:
            path = self.fixture.write_json(kind + "-stale-ref.json", reference)
            self.rejected_without_writes(self.fixture, "resource-review-local", self.workspace, kind, path,
                                         kind + "-stale-review", REVIEW_PERMIT, error="ValidationStale")
            revised = copy.deepcopy(envelope)
            revised["metadata"]["revision"] = 3
            path = self.fixture.seal(revised, kind + "-stale-proposal.json")
            self.rejected_without_writes(self.fixture, "resource-propose", self.workspace, kind, path, 2,
                                         kind + "-stale-proposal", error="ValidationStale")
        self.fixture.write_json("rejection-and-staleness-result.json", {"failures": self.failures, "new_cli_queries": stale_queries,
                                                                       "write_measurement": "read_only_logical_database_snapshot_diff",
                                                                       "mode": "project_private/aji-local", "P7": False})

    def test_t21_reviewed_exact_experience_drives_related_task_and_rejects_stale_or_universal(self):
        observations = self.observe_manifest_guards(METHOD, "first-task-pack")
        evidence = self.fixture.write_json("manifest-evidence.json", {"method": METHOD, "observations": observations})
        self.resources.source = self.fixture.call("register-input", self.workspace, "user/manifest-evidence", evidence.name)
        knowledge = self.resources.knowledge()
        knowledge["payload"].update(location=evidence.name + ":1", method=METHOD,
                                    claim="Actual isolated manifest rejections and accepted repeated prose")
        knowledge_ref = self.propose("knowledge", knowledge, "knowledge-propose")
        self.assertEqual(self.query("knowledge")["entries"], [])
        self.review("knowledge", knowledge_ref, "knowledge-review")
        experience = self.experience(knowledge_ref)
        experience_ref = self.propose("experience", experience, "experience-propose")
        self.assertEqual(self.query("experience", TRIGGER)["entries"], [])
        with self.assertRaisesRegex(ValueError, "No exact reviewed"):
            self.consume_manifest_experience(TRIGGER, "unreviewed-followup")
        self.assertFalse((self.workspace / "unreviewed-followup.json").exists())
        self.review("experience", experience_ref, "experience-review")
        for unrelated in ("unrelated-task", TRIGGER[:-1], TRIGGER + "-suffix", TRIGGER.upper()):
            with self.subTest(trigger=unrelated):
                self.assertEqual(self.query("experience", unrelated)["entries"], [])
                with self.assertRaisesRegex(ValueError, "No exact reviewed"):
                    self.consume_manifest_experience(unrelated, "unrelated-followup")
        self.assertFalse((self.workspace / "unrelated-followup.json").exists())
        self.assertEqual(len(self.query("experience", "")["entries"]), 1)
        with self.assertRaisesRegex(ValueError, "No exact reviewed"):
            self.consume_manifest_experience("", "untriggered-followup")
        self.assertFalse((self.workspace / "untriggered-followup.json").exists())
        receipt = json.loads(self.consume_manifest_experience(TRIGGER, "related-followup").read_text(encoding="utf-8"))
        self.assertEqual(receipt["experience_ref"], experience_ref)
        self.assertEqual(receipt["exact_method"], METHOD)
        self.assertEqual(receipt["evidence_refs_used"], [self.resources.source])
        self.assertEqual(receipt["counterexamples"], COUNTEREXAMPLES)
        self.assertEqual(len(receipt["actual_followup"]["rejections"]), 7)
        self.assertTrue(receipt["actual_followup"]["repeated_prose_accepted"])
        self.assert_self_grants_and_stale_queries_rejected(knowledge, knowledge_ref, experience, experience_ref, evidence)

    def test_t22_scope_and_review_permit_are_rechecked_before_private_reuse(self):
        private = {"preference": "project-A prefers local review only", "fact": "project-A fixture tag is private-417"}
        path = self.fixture.write_json("private-evidence.json", private)
        self.resources.source = self.fixture.call("register-input", self.workspace, "user/private-evidence", path.name)
        knowledge = self.resources.knowledge()
        knowledge["payload"].update(location=path.name + ":1", claim=json.dumps(private))
        knowledge_ref = self.propose("knowledge", knowledge, "private-knowledge-propose")
        path = self.fixture.write_json("private-knowledge-reference.json", knowledge_ref)
        self.rejected_without_writes(self.fixture, "resource-review-local", self.workspace, "knowledge", path,
                                     "invalid-knowledge-review", "pretend-user-approved", error="AuthorityDenied")
        self.assertEqual(self.query("knowledge")["entries"], [])
        self.review("knowledge", knowledge_ref, "private-knowledge-review")
        experience = self.experience(knowledge_ref, method=private["preference"], trigger="private-review", kind="user_preference")
        experience_ref = self.propose("experience", experience, "private-experience-propose")
        path = self.fixture.write_json("private-experience-reference.json", experience_ref)
        self.rejected_without_writes(self.fixture, "resource-review-local", self.workspace, "experience", path,
                                     "invalid-experience-review", "pretend-user-approved", error="AuthorityDenied")
        self.assertEqual(self.query("experience", "private-review")["entries"], [])
        self.review("experience", experience_ref, "private-experience-review")
        self.assertEqual(self.query("knowledge")["entries"][0]["envelope"]["payload"]["claim"], json.dumps(private))
        self.assertEqual(self.query("experience", "private-review")["entries"][0]["envelope"]["payload"]["method"], private["preference"])
        other = test_core_cli.CoreCliTests("test_complete_copy_repeat_and_current_file")
        other.setUp()
        other_scope = other.initial["scope"]
        self.assertNotEqual(self.scope, other_scope)
        source_before = self.database_snapshot(self.fixture)
        for kind, envelope, reference in (("knowledge", knowledge, knowledge_ref), ("experience", experience, experience_ref)):
            for trigger in ("", "private-review"):
                result = self.query(kind, trigger, other)
                self.assertEqual(result["entries"], [])
                self.assertEqual(result["rejected"], [])
                for secret in private.values():
                    self.assertNotIn(secret, json.dumps(result))
            for alteration in ("original", "envelope-scope", "all-reference-scopes"):
                with self.subTest(kind=kind, proposal=alteration):
                    forged = copy.deepcopy(envelope)
                    if alteration != "original":
                        forged["metadata"]["scope"] = forged["payload"]["scope"] = other_scope
                    if alteration == "all-reference-scopes":
                        fields = ("source_refs",) if kind == "knowledge" else ("evidence", "knowledge_refs")
                        for field in fields:
                            for dependency in forged["payload"][field]:
                                dependency["scope"] = other_scope
                    path = other.seal(forged, kind + "-" + alteration + ".json")
                    error = "Reference" if alteration == "all-reference-scopes" else "ScopeDenied"
                    self.rejected_without_writes(other, "resource-propose", other.workspace, kind, path, 0,
                                                 kind + "-" + alteration, error=error)
            for alteration in ("original", "reference-scope"):
                with self.subTest(kind=kind, review=alteration):
                    forged = dict(reference)
                    if alteration == "reference-scope":
                        forged["scope"] = other_scope
                    path = other.write_json(kind + "-" + alteration + "-ref.json", forged)
                    self.rejected_without_writes(other, "resource-review-local", other.workspace, kind, path,
                                                 kind + "-review-" + alteration, REVIEW_PERMIT,
                                                 error="Reference" if alteration == "reference-scope" else "ScopeDenied")
            self.assertEqual(self.query(kind, "", other)["entries"], [])
        self.assertEqual(self.database_snapshot(self.fixture), source_before)
        self.fixture.write_json("private-isolation-result.json", {"source_scope": self.scope, "other_scope": other_scope,
                                                                 "mode": "project_private/aji-local", "failures": self.failures,
                                                                 "write_measurement": "read_only_logical_database_snapshot_diff",
                                                                 "T22": "partial", "full_user_acl": "not_implemented", "P7": False})


if __name__ == "__main__":
    unittest.main()
