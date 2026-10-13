import json
from pathlib import Path
import tempfile
import unittest

from design_audit import audit, load_json, pointer, schema_errors, unique_object


class DesignAuditTests(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"id":1,"id":2}', object_pairs_hook=unique_object)

    def test_trailing_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "input.json"
            target.write_text('{}{}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json(target)

    def test_escaped_pointer(self):
        self.assertEqual(pointer({"a/b": {"~": 3}}, "/a~1b/~0"), 3)

    def test_unresolved_reference(self):
        schema = {"$ref": "#/$defs/Missing"}
        self.assertTrue(schema_errors(schema, {"local": schema}, "local"))

    def test_remote_reference_rejected(self):
        schema = {"$ref": "https://remote.invalid/schema#/$defs/Input"}
        self.assertTrue(schema_errors(schema, {"local": schema}, "local"))

    def test_unknown_keyword_rejected(self):
        schema = {"type": "string", "unreviewed": True}
        self.assertTrue(schema_errors(schema, {"local": schema}, "local"))

    def test_missing_required_property(self):
        schema = {"type": "object", "properties": {}, "required": ["not_defined"], "additionalProperties": False}
        self.assertTrue(schema_errors(schema, {"local": schema}, "local"))

    def test_cross_file_reference(self):
        schema = {"$ref": "other#/$defs/Value"}
        target = {"$defs": {"Value": {"type": "string"}}}
        self.assertEqual(schema_errors(schema, {"local": schema, "other": target}, "local"), [])

    def test_current_design_map(self):
        report = audit(Path(__file__).resolve().parent.parent)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["runtime_acceptance_executed"], 0)
        self.assertFalse(report["P7_authorized"])


if __name__ == "__main__":
    unittest.main()
