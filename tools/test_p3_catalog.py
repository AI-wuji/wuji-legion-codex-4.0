import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from build_p3_catalog import QUALITY_SOURCE_PATHS, quality_current

ROOT = Path(__file__).resolve().parents[1]


class P3CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "catalog/p3/experts.json").read_text(encoding="utf-8"))
        cls.assemblies = json.loads((ROOT / "catalog/p3/atom-assemblies.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((ROOT / "catalog/p3/composition-manifest.json").read_text(encoding="utf-8"))
        cls.report = json.loads((ROOT / "outputs/p3/p3-quality-report.json").read_text(encoding="utf-8"))

    def test_catalog_covers_all_responsibilities_and_stays_cold(self):
        self.assertEqual(57, self.catalog["role_count"])
        self.assertEqual(57, len(self.catalog["roles"]))
        self.assertEqual(57, len({role["id"] for role in self.catalog["roles"]}))
        self.assertFalse(self.catalog["runtime_admission"])
        self.assertEqual(0, self.catalog["formal_model_experts"])
        self.assertTrue(all(not role["active_release"] for role in self.catalog["roles"]))

    def test_each_role_has_contract_sources_and_boundaries(self):
        fields = {"goal", "inputs", "process", "output", "acceptance"}
        for role in self.catalog["roles"]:
            with self.subTest(role=role["id"]):
                self.assertEqual(fields, set(role["five_elements"]))
                self.assertTrue(role["source_refs"])
                self.assertTrue(role["atom_refs"])
                self.assertTrue(role["composition_dependencies"])
                self.assertTrue(role["scope_rule"])
                self.assertTrue(role["cancellation"])

    def test_composition_references_shared_components_without_duplicate_public_bodies(self):
        self.assertEqual(57, len(self.manifest["roles"]))
        self.assertTrue(self.manifest["rules"]["duplicate_public_bodies"])
        self.assertEqual(69, len(self.assemblies["assemblies"]))
        self.assertTrue(all(entry["shared_components"] for entry in self.manifest["roles"]))

    def test_quality_report_passes_without_claiming_effectiveness(self):
        self.assertTrue(self.report["passed"])
        self.assertTrue(quality_current(ROOT,self.report))
        self.assertEqual("not_run", self.catalog["effectiveness"])
        self.assertTrue(any("effectiveness" in text for text in self.report["limitations"]))

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
