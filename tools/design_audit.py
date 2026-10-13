from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA_KEYS = {"$schema", "$id", "$ref", "title", "description", "$defs", "type", "const", "enum", "properties", "required", "additionalProperties", "items", "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "pattern", "oneOf", "anyOf", "allOf"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def pointer(document, fragment):
    if not fragment.startswith("/"):
        raise ValueError("only explicit JSON pointers are allowed")
    current = document
    for segment in fragment[1:].split("/"):
        current = current[segment.replace("~1", "/").replace("~0", "~")]
    return current


def schema_errors(schema, schemas, document_name, location=""):
    errors = []
    if not isinstance(schema, dict):
        return [f"{document_name}{location}: expected schema object"]
    unsupported = set(schema) - SCHEMA_KEYS
    if unsupported:
        errors.append(f"{document_name}{location}: unsupported schema keywords {sorted(unsupported)}")
    if "$ref" in schema:
        target_name, fragment = schema["$ref"].split("#", 1)
        target_name = target_name or document_name
        if target_name not in schemas:
            errors.append(f"{document_name}{location}: external/unlocked reference {target_name}")
        else:
            try:
                pointer(schemas[target_name], fragment)
            except (KeyError, ValueError, TypeError):
                errors.append(f"{document_name}{location}: unresolved reference {schema['$ref']}")
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            errors.append(f"{document_name}{location}: object not closed")
        if not set(schema.get("required", [])) <= set(properties):
            errors.append(f"{document_name}{location}: required property has no definition")
        if len(set(schema.get("required", []))) != len(schema.get("required", [])):
            errors.append(f"{document_name}{location}: repeated required property")
    for map_key in ("$defs", "properties"):
        for child_name, child in schema.get(map_key, {}).items():
            errors.extend(schema_errors(child, schemas, document_name, f"{location}/{map_key}/{child_name}"))
    for array_key in ("oneOf", "anyOf", "allOf"):
        for index, child in enumerate(schema.get(array_key, [])):
            errors.extend(schema_errors(child, schemas, document_name, f"{location}/{array_key}/{index}"))
    if "items" in schema:
        errors.extend(schema_errors(schema["items"], schemas, document_name, f"{location}/items"))
    for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength"), ("minItems", "maxItems")):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            errors.append(f"{document_name}{location}: reversed bounds")
    return errors


def audit(root):
    errors = []
    checks = []

    def require(condition, label):
        checks.append({"check": label, "passed": bool(condition)})
        if not condition:
            errors.append(label)

    baseline = load_json(root / "docs/execution-baseline.json")
    from execution_baseline import load_active
    require(load_active(root) == baseline, "approved active revision and retained original hashes current")
    requirements = load_json(root / "docs/requirement-design-map.json")["requirements"]
    tests = load_json(root / "docs/acceptance-map.json")["tests"]
    experts = load_json(root / "docs/expert-design-map.json")["responsibilities"]
    atoms = load_json(root / "docs/atom-design-map.json")
    walkthroughs = load_json(root / "docs/design-walkthroughs.json")["design_results"]
    schemas = {name: load_json(root / "schemas" / name) for name in ("contracts.schema.json", "atom-semantics.schema.json")}
    for name, schema in schemas.items():
        errors.extend(schema_errors(schema, schemas, name))
    require(len(requirements) == 72 and len({row["id"] for row in requirements}) == 72, "72 distinct requirements")
    require(len(tests) == 95 and len({row["id"] for row in tests}) == 95, "95 distinct acceptance designs")
    require({row["id"] for row in requirements} == {f"R{index:02d}" for index in range(1, 73)}, "requirement identifiers exact")
    require({row["id"] for row in tests} == {f"T{index:02d}" for index in range(1, 96)}, "test identifiers exact")
    test_map = {row["id"]: row for row in tests}
    for row in requirements:
        require(bool(row["module"] and row["data_invariant"] and row["test_ids"] and row["design_refs"]), f"{row['id']} module/data/test design")
        try:
            pointer(schemas["contracts.schema.json"], row["contract_schema"].split("#", 1)[1])
        except (KeyError, ValueError):
            errors.append(f"{row['id']} schema missing")
        require(all(Path(root / ref).is_file() for ref in row["design_refs"]), f"{row['id']} design refs exist")
        require(all(test_id in test_map and row["id"] in test_map[test_id]["requirement_ids"] for test_id in row["test_ids"]), f"{row['id']} reciprocal tests")
    require(all(row["requirement_ids"] and row["normal_spec"] and row["negative_spec"] for row in tests), "all tests have requirement/normal/negative specs")
    require(all(row["runtime_execution"] == "not_run" and not row["protocol_mock_is_native_proof"] for row in tests), "no design mock promoted to native test")
    original_roles = load_json(root / "outputs/p0/responsibility-map.json")["responsibilities"]
    require(len(experts) == 57 and {row["baseline_id"] for row in experts} == {row["baseline_fields"][0] for row in original_roles}, "57 baseline responsibilities no omissions")
    require(all(row["inputs"] and row["outputs"] and row["anti_trigger"] and row["professional_acceptance"] and len(row["five_elements"]) == 5 for row in experts), "all responsibility boundaries and five elements")
    require(all(not row["runtime_admission"] and row["expert_body"] == "not_written" for row in experts), "no premature expert creation")
    expected_atoms = {f"{group}{index:02d}" for group in "ABCDEFGHIJKLMNOP" for index in range(1, 9)}
    require(len(atoms["atoms"]) == 128 and {row["id"] for row in atoms["atoms"]} == expected_atoms, "128 candidates receive semantic decision")
    atom_defs = schemas["atom-semantics.schema.json"]["$defs"]
    ledger = load_json(root / "outputs/p0/atom-evidence-ledger.json")
    ledger_ids = {row["candidate_id"]: row for row in ledger["atoms"]}
    for row in atoms["atoms"]:
        require(all(row["id"] + suffix in atom_defs for suffix in ("Input", "Value", "Result")), f"{row['id']} typed input/single-result schema")
        require(bool(row["single_responsibility"] and row["failure_kind"] and row["negative_spec"] and row["normal_spec"] and row["preconditions"] and row["rollback"]), f"{row['id']} responsibility/failure/positive/negative/recovery")
        require(bool(row["l2_consumers"] or row["l3_consumers"]), f"{row['id']} composition consumer")
        require(bool(ledger_ids[row["id"]]["method_source_bindings"]), f"{row['id']} original method evidence")
        require(all(binding["form"] in {"schema", "program", "model", "native_action"} for binding in row["implementation_bindings"]), f"{row['id']} finite implementation binding")
        require(not row["runtime_admission"], f"{row['id']} semantic design is not runtime admission")
    required_l0 = {"ExactRef", "EvidenceRef", "InputBinding", "DecisionRecord", "EffectSpec", "TimeQuantity", "Finding", "MethodApplicability"}
    require(required_l0 <= schemas["contracts.schema.json"]["$defs"].keys(), "all approved L0 values explicitly defined")
    meta_fields = schemas["contracts.schema.json"]["$defs"]["ObjectMeta"]["required"]
    require(len(meta_fields) == 16, "16 common authority fields")
    require(len(schemas["contracts.schema.json"]["oneOf"]) == 30, "30 baseline public contract envelopes")
    require(len(walkthroughs) >= 11 and all(row["normal_path"] and row["abnormal_path"] and row["runtime_verification"] == "not_run" for row in walkthroughs), "normal/abnormal tabletop coverage with honest boundary")
    graph_doc = (root / "docs/graph-data-model.md").read_text(encoding="utf-8")
    graphs = {"G-REQ", "G-DEC", "G-LEAD", "G-EXP", "G-TOOL", "G-ROLE", "G-EXEC", "G-ACCEPT", "G-CODE", "G-RESEARCH", "G-INCIDENT", "G-EXPERIENCE", "G-LINEAGE", "G-RISK", "G-REVIEW", "G-PERF"}
    require(all(graph in graph_doc for graph in graphs), "16 approved logical graphs retained")
    architecture = (root / "docs/architecture.md").read_text(encoding="utf-8")
    require(all(marker in architecture for marker in ("ActorContext", "unknown", "release_unverified", "transfer_pending", "ack", "BEGIN IMMEDIATE", "G2")), "trusted entry/transactions/unknown/slot/ack interfaces")
    return {"schema_version": 1, "phase_id": "P1", "kind": "development_design_audit_not_runtime_test", "checks": checks, "errors": errors, "passed": not errors, "runtime_acceptance_executed": 0, "P7_authorized": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    report = audit(options.root.resolve())
    if options.output:
        output = options.output.resolve()
        if not output.is_relative_to(options.root.resolve() / "outputs"):
            raise ValueError("audit output must remain in project outputs")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]), "errors": report["errors"]}, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
