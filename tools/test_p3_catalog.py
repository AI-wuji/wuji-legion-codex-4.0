import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from build_p3_catalog import QUALITY_SOURCE_PATHS, quality_current
import build_p3_catalog

ROOT = Path(__file__).resolve().parents[1]


class P3CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "catalog/p3/experts.json").read_text(encoding="utf-8"))
        cls.assemblies = json.loads((ROOT / "catalog/p3/atom-assemblies.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((ROOT / "catalog/p3/composition-manifest.json").read_text(encoding="utf-8"))
        cls.report = json.loads((ROOT / "outputs/p3/p3-quality-report.json").read_text(encoding="utf-8"))

    def test_catalog_covers_all_responsibilities_and_stays_cold(self):
        frozen = json.loads((ROOT / "docs/expert-design-map.json").read_text(encoding="utf-8"))
        frozen_ids = {item["baseline_id"] for item in frozen["responsibilities"]}
        roles = {role["baseline_id"]: role for role in self.catalog["roles"]}
        self.assertEqual(57, len(frozen_ids))
        self.assertEqual(frozen_ids | {"motion-graphics"}, set(roles))
        self.assertEqual(58, self.catalog["role_count"])
        self.assertEqual(self.catalog["role_count"], len(self.catalog["roles"]))
        self.assertEqual(self.catalog["role_count"], len({role["id"] for role in self.catalog["roles"]}))
        self.assertFalse(self.catalog["runtime_admission"])
        self.assertEqual(0, self.catalog["formal_model_experts"])
        # The original 57 stay cold; any later motion admission is its own bounded result.
        self.assertTrue(all(not roles[key]["active_release"] and not roles[key]["runtime_admission"]
                            for key in frozen_ids))

    def test_each_role_has_contract_sources_and_boundaries(self):
        fields = {"goal", "inputs", "process", "output", "acceptance"}
        for role in self.catalog["roles"]:
            with self.subTest(role=role["id"]):
                self.assertEqual(fields, set(role["five_elements"]))
                self.assertTrue(role["source_refs"])
                if role["id"] == "p3/leaf/motion-graphics":
                    self.assertEqual([], role["atom_refs"])
                    self.assertEqual("task_scoped_consumer_extension", role["catalog_extension"]["kind"])
                    self.assertFalse(role["catalog_extension"]["frozen_design_membership"])
                else:
                    self.assertTrue(role["atom_refs"])
                self.assertTrue(role["composition_dependencies"])
                self.assertTrue(role["scope_rule"])
                self.assertTrue(role["cancellation"])

    def test_composition_references_shared_components_without_duplicate_public_bodies(self):
        self.assertEqual(self.catalog["role_count"], len(self.manifest["roles"]))
        self.assertEqual({role["id"] for role in self.catalog["roles"]},
                         {entry["role_id"] for entry in self.manifest["roles"]})
        self.assertTrue(self.manifest["rules"]["duplicate_public_bodies"])
        self.assertEqual(69, len(self.assemblies["assemblies"]))
        self.assertTrue(all(entry["shared_components"] for entry in self.manifest["roles"]))

    def test_historical_quality_report_does_not_admit_task_extension(self):
        self.assertTrue(self.report["passed"])
        # This bounded extension cannot reuse the old 57-role report as current admission.
        self.assertFalse(quality_current(ROOT, self.report))
        stale = {path for path, digest in self.report["source_hashes"].items()
                 if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest}
        self.assertEqual({"catalog/p3/experts.json", "catalog/p3/composition-manifest.json",
                          "tools/build_p3_catalog.py"}, stale)
        self.assertEqual("not_run", self.catalog["effectiveness"])
        self.assertTrue(any("effectiveness" in text for text in self.report["limitations"]))

    def test_motion_role_composes_one_skill_reference_and_actual_launcher_contract(self):
        role = next(role for role in self.catalog["roles"] if role["id"] == "p3/leaf/motion-graphics")
        entry = next(item for item in self.manifest["roles"] if item["role_id"] == role["id"])
        self.assertEqual("动效制作专家", role["title"])
        self.assertEqual(1, len(role["source_refs"]))
        source = role["source_refs"][0]
        self.assertEqual("alchaincyf/huashu-motion", source["repository"])
        self.assertEqual("5f2608c2e12abcf518f74dde86093b19f7f88603", source["commit"])
        self.assertEqual("skills/huashu-motion/SKILL.md", source["path"])
        self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(["legion/skills/wuji-legion-4-0/references/motion-graphics.md"], role["reference_bindings"])
        self.assertEqual(role["call_binding"], entry["call_binding"])
        binding = role["call_binding"]
        self.assertEqual("legion/skills/wuji-legion-4-0/scripts/motion-graphics.mjs", binding["launcher"])
        self.assertEqual("tools/wuji4.py run-motion", binding["thin_entry"])
        for required in (binding["launcher"], binding["reference"], binding["thin_entry"], source["path"]):
            self.assertIn(required, role["five_elements"]["process"])
        for field in ("process", "inputs", "output"):
            for required in (binding["reference"], binding["launcher"]):
                self.assertIn(required, role["five_elements"][field])
        self.assertEqual(role["five_elements"]["output"], entry["professional_difference"]["outputs"])
        self.assertEqual(role["five_elements"]["acceptance"], entry["professional_difference"]["acceptance"])

    def test_frozen_rebuild_cannot_silently_remove_the_new_expert(self):
        paths = [ROOT / p for p in ("catalog/p3/experts.json", "catalog/p3/composition-manifest.json",
                                    "catalog/p3/atom-assemblies.json", "outputs/p3/p3-quality-report.json")]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        with self.assertRaisesRegex(ValueError, "would discard task-scoped roles"):
            build_p3_catalog.main()
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_all_catalog_source_links_match_current_file_bytes(self):
        for field in ("baseline","design_source","atom_ledger","requirement_map"):
            reference = self.catalog[field]
            self.assertEqual(reference["sha256"],hashlib.sha256((ROOT / reference["path"]).read_bytes()).hexdigest())

    def test_old_quality_flag_cannot_override_changed_missing_or_forged_source_lock(self):
        with tempfile.TemporaryDirectory(prefix="p3-quality-",dir=ROOT / ".dev") as temporary:
            root = Path(temporary)
            hashes = {}
            for name in QUALITY_SOURCE_PATHS:
                path = root / name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b"bounded test fixture")
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            report = {"passed":True,"source_hashes":hashes}
            self.assertTrue(quality_current(root,report))
            path = root / QUALITY_SOURCE_PATHS[0]
            path.write_bytes(b"changed")
            self.assertFalse(quality_current(root,report))
            path.unlink()
            self.assertFalse(quality_current(root,report))
            hashes["../outside.json"] = "0" * 64
            self.assertFalse(quality_current(root,report))


if __name__ == "__main__":
    unittest.main()
