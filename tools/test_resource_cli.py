import json
import subprocess
import unittest

import test_core_cli


class ResourceCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core_cli.CoreCliTests("test_complete_copy_repeat_and_current_file")
        self.fixture.setUp()
        self.workspace = self.fixture.workspace
        (self.workspace / "evidence.txt").write_text("project evidence", encoding="utf-8")
        self.source = self.fixture.call("register-input", self.workspace, "user/evidence", "evidence.txt")

    def knowledge(self):
        metadata = self.fixture.plan()["metadata"]
        metadata.update(id="knowledge/cli", type="KnowledgeRecord")
        return {"schema_version": 1, "contract_type": "KnowledgeRecord", "metadata": metadata,
                "payload": {"knowledge_id": "knowledge/cli", "scope": self.fixture.initial["scope"],
                            "source_refs": [self.source], "location": "evidence.txt:1",
                            "sha256": self.source["sha256"], "authority": "review_proposal",
                            "claim": "Project-private reviewed candidate", "method": "Check source",
                            "derived_refs": [], "freshness": "current", "conflicts": []}}

    def test_propose_review_query_retire_with_the_documented_argument_counts(self):
        envelope = self.fixture.seal(self.knowledge(), "knowledge.json")
        proposed = self.fixture.call("resource-propose", self.workspace, "knowledge", envelope, 0, "propose-event")
        self.assertEqual(proposed["state"], "candidate")
        before = self.fixture.call("resource-query", self.workspace, "knowledge", "", 8)
        self.assertEqual(before["entries"], [])
        reference = self.fixture.write_json("reference.json", proposed["reference"])
        reviewed = self.fixture.call("resource-review-local", self.workspace, "knowledge", reference,
                                    "review-event", "confirm-isolated-project-resource-review")
        self.assertFalse(reviewed["runtime_admission"])
        result = self.fixture.call("resource-query", self.workspace, "knowledge", "", 8)
        self.assertEqual(len(result["entries"]), 1)
        self.fixture.call("resource-retire", self.workspace, "knowledge", reference, "retire-event")
        self.assertEqual(self.fixture.call("resource-query", self.workspace, "knowledge", "", 8)["entries"], [])

    def test_review_requires_explicit_isolated_permit(self):
        envelope = self.fixture.seal(self.knowledge(), "knowledge.json")
        proposed = self.fixture.call("resource-propose", self.workspace, "knowledge", envelope, 0, "propose-event")
        reference = self.fixture.write_json("reference.json", proposed["reference"])
        self.fixture.call("resource-review-local", self.workspace, "knowledge", reference,
                          "review-event", "pretend-user-approved", expected_error="AuthorityDenied")

    def test_two_actual_processes_have_one_resource_revision_winner(self):
        envelope = self.fixture.seal(self.knowledge(), "knowledge.json")
        processes = [subprocess.Popen([str(test_core_cli.EXECUTABLE), "resource-propose", str(self.workspace),
                                       "knowledge", str(envelope), "0", event],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8") for event in ("race-1", "race-2")]
        results = [(process.returncode, output, error) for process in processes
                   for output, error in [process.communicate(timeout=20)]]
        self.assertEqual(sum(code == 0 for code, _, _ in results), 1, results)
        self.assertEqual([json.loads(error)["error"] for code, _, error in results if code != 0], ["RevisionConflict"])


if __name__ == "__main__":
    unittest.main()
