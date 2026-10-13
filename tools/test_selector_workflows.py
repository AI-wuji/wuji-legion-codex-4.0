import hashlib
import json
import time
import unittest

import test_core_cli

ROOT = test_core_cli.ROOT


class SelectorWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core_cli.CoreCliTests("test_complete_copy_repeat_and_current_file")
        self.fixture.setUp()
        self.root = self.fixture.workspace
        self.scope = self.fixture.initial["scope"]
        self.entries = []
        self.references = {}
        self.source_text = "Exact original professional input: preserve identity; do not publish.\n" * 16
        for identifier, domain, anti in [("retouch", "image", ["illustration"]),
                                          ("illustrate", "image", ["retouch"])]:
            source_path = self.root / f"{identifier}.txt"
            source_path.write_bytes(self.source_text.encode("utf-8"))
            overview_path = self.root / f"{identifier}-overview.txt"
            overview_path.write_text(f"Overview of {identifier}", encoding="utf-8")
            source = self.exact(identifier, source_path.read_bytes())
            overview = self.exact(f"{identifier}-overview", overview_path.read_bytes())
            self.references[identifier] = source
            self.entries.append(self.entry(source, overview, domain, ["image"], anti,
                                           source_path.name, overview_path.name))
        for index in range(80):
            source = self.exact(f"unrelated-{index}", b"unrelated cold content")
            overview = self.exact(f"unrelated-overview-{index}", b"unrelated overview")
            self.entries.append(self.entry(source, overview, "unrelated", ["audio"], [],
                                           f"missing-unrelated-{index}.txt", f"missing-overview-{index}.txt"))
        self.index_path = self.fixture.write_json("cold-index.json", {
            "schema_version": 1, "scope": self.scope, "release": "selector-test-1",
            "state": "prepared", "entries": self.entries})
        self.index = self.exact("cold-index", self.index_path.read_bytes())
        self.index_ref_path = self.fixture.write_json("cold-index-ref.json", self.index)

    def exact(self, identifier, data):
        return {"id": identifier, "type": "file", "scope": self.scope, "revision": 1,
                "sha256": hashlib.sha256(data).hexdigest(), "release": "selector-test-1", "schema_version": 1}

    @staticmethod
    def entry(source, overview, domain, intents, anti, source_path, overview_path):
        return {"reference": source, "kind": "leaf", "domain": domain, "all_intents": intents,
                "anti_intents": anti, "brief": f"Bounded contract for {source['id']}",
                "source": {"path": source_path, "reference": source},
                "overview": {"path": overview_path, "reference": overview}}

    def select(self, intents, cap=8, domain="image", kind="leaf", expected_error=None):
        request = self.fixture.write_json("selection.json", {"domain": domain, "kind": kind,
                                                                "intents": intents, "max_candidates": cap})
        return self.fixture.call("select", self.root, "cold-index.json", self.index_ref_path, request,
                                 expected_error=expected_error)

    def project(self, reference, tier, cap=16384, expected_error=None):
        path = self.fixture.write_json("projection-ref.json", reference)
        return self.fixture.call("project", self.root, "cold-index.json", self.index_ref_path,
                                 path, tier, cap, expected_error=expected_error)

    def test_t05_actual_subset_selection_provides_needed_source_and_excludes_unrelated_bodies(self):
        selected = self.select(["image", "retouch"])
        self.assertEqual(selected["state"], "selected")
        self.assertEqual(selected["candidates"], [self.references["retouch"]])
        self.assertEqual(selected["examined_metadata_entries"], 2)
        self.assertEqual(selected["professional_body_bytes_read"], 0)
        self.assertFalse(selected["runtime_admission"])
        needed = self.project(selected["candidates"][0], "source")
        self.assertEqual(needed["content"], self.source_text)
        self.assertFalse(needed["execution_authority"])
        self.assertEqual(self.select(["image", "retouch", "illustration"])["state"], "none")
        self.assertEqual(self.select(["image"], domain="absent")["examined_metadata_entries"], 0)
        self.assertEqual(self.select(["image"], kind="method")["state"], "none")
        self.assertEqual(self.fixture.call("status", self.root)["open_slots"], 0)
        self.assertFalse((self.root / "missing-unrelated-0.txt").exists())

    def test_t06_actual_ambiguity_requires_narrowing_not_fake_confidence_or_truncation(self):
        broad = self.select(["image"])
        self.assertEqual(broad["state"], "ambiguous")
        self.assertEqual(len(broad["candidates"]), 2)
        self.assertIsNone(broad["confidence"])
        self.assertEqual(broad["professional_body_bytes_read"], 0)
        self.assertFalse(broad["native_execution"])
        self.select(["image"], cap=1, expected_error="BudgetExhausted")
        narrow = self.select(["image", "illustration"])
        self.assertEqual(narrow["state"], "selected")
        self.assertEqual(narrow["candidates"], [self.references["illustrate"]])
        self.assertIsNone(narrow["confidence"])
        self.assertEqual(self.fixture.call("status", self.root)["open_slots"], 0)

    def test_t83_actual_direct_tiers_have_measured_roundtrips_full_sources_and_stale_rejection(self):
        reference = self.references["retouch"]
        started = time.perf_counter_ns()
        direct = self.project(reference, "source")
        elapsed = time.perf_counter_ns() - started
        self.assertEqual(direct["content"], self.source_text)
        self.assertEqual(direct["content_bytes_read"], len(self.source_text.encode("utf-8")))
        self.assertEqual(direct["file_bytes_read_this_call"],
                         self.index_path.stat().st_size + len(self.source_text.encode("utf-8")))
        brief = self.project(reference, "brief")
        self.assertEqual(brief["content_bytes_read"], 0)
        self.assertEqual(brief["source_validation_bytes_read"], len(self.source_text.encode("utf-8")))
        overview = self.project(reference, "overview")
        self.assertEqual(overview["content"], "Overview of retouch")
        self.project(reference, "source", cap=4096 // 4, expected_error="BudgetExhausted")
        self.project(dict(reference, revision=2), "source", expected_error="Reference")
        (self.root / "retouch.txt").write_text("changed source", encoding="utf-8")
        for tier in ("brief", "overview", "source"):
            self.project(reference, tier, expected_error="HashMismatch")
        self.index_path.write_text("changed index", encoding="utf-8")
        self.select(["image", "retouch"], expected_error="HashMismatch")
        self.assertGreater(elapsed, 0)
        evidence = {"kind": "actual_isolated_selector_cli", "direct_projection_process_roundtrips": 1,
                    "direct_projection_elapsed_ns": elapsed, "index_entries": len(self.entries),
                    "direct_projection": direct, "brief_projection": brief, "overview_projection": overview,
                    "freshness_negative_tiers": ["brief", "overview", "source"],
                    "measurement_scope": "single_call_no_cross_model_or_latency_superiority_claim",
                    "source_test_sha256": hashlib.sha256((ROOT / "tools/test_selector_workflows.py").read_bytes()).hexdigest(),
                    "runtime_admission": False}
        (ROOT / "outputs/p6/selector-workflow-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
