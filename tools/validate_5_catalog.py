import hashlib
import json
import sys
from pathlib import Path

from execution_baseline import ROOT
from p6_package_validation import strict_json


RELEASE_PATH = ROOT / "catalog/p3/catalog-release-5.0.json"


def _read_bound_file(record, label):
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ValueError(f"{label} path record is malformed")
    path = (ROOT / record["path"]).resolve(strict=True)
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError(f"{label} must resolve to a project file")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if record.get("sha256") != digest:
        raise ValueError(f"{label} SHA-256 does not match the release record")
    return path


def validate_catalog():
    release = strict_json(RELEASE_PATH.read_text(encoding="utf-8"))
    if (release.get("schema_version") != 1
            or release.get("state") != "one_bounded_role_admitted_57_design_roles_cold"):
        raise ValueError("Unsupported or overstated 5.0 catalog release")
    catalog_path = _read_bound_file(release.get("catalog"), "role catalog")
    direct_path = _read_bound_file(release.get("direct_expert_manifest"), "direct expert manifest")
    catalog = strict_json(catalog_path.read_text(encoding="utf-8"))
    direct = strict_json(direct_path.read_text(encoding="utf-8"))
    provenance = release.get("provenance")
    rights = release.get("rights")
    if (not isinstance(provenance, dict) or provenance.get("source_use") != "read_only_semantic_lineage; not a 5.0 runtime baseline"
            or not isinstance(rights, dict) or rights.get("external_source_license_clearance") != "not_claimed_for_historical_source_refs"):
        raise ValueError("5.0 provenance or rights boundary is missing")
    roles = catalog.get("roles")
    catalog_record = release["catalog"]
    expected_count = catalog_record.get("role_count")
    if (not isinstance(roles, list) or type(expected_count) is not int
            or len(roles) != expected_count or catalog.get("role_count") != expected_count
            or direct.get("role_count") != expected_count
            or catalog_record.get("baseline_design_role_count") != 57
            or catalog_record.get("bounded_consumer_extension_count") != 1):
        raise ValueError("5.0 role counts disagree across release records")
    admitted_records = release.get("admitted_roles")
    if not isinstance(admitted_records, list) or len(admitted_records) != 1:
        raise ValueError("5.0 release must enumerate its single bounded role admission")
    admitted = {item.get("role_id"): item for item in admitted_records if isinstance(item, dict)}
    if set(admitted) != {"p3/leaf/motion-graphics"}:
        raise ValueError("5.0 admitted role set does not match the bounded consumer evidence")
    required_elements = {"goal", "inputs", "process", "output", "acceptance"}
    ids = set()
    for role in roles:
        if not isinstance(role, dict) or not isinstance(role.get("id"), str) or role["id"] in ids:
            raise ValueError("5.0 role ids must be present and unique")
        ids.add(role["id"])
        elements = role.get("five_elements")
        if not isinstance(elements, dict) or not required_elements.issubset(elements):
            raise ValueError(f"Role {role['id']} is missing a five-element contract")
        if not isinstance(role.get("anti_trigger"), str) or not role["anti_trigger"].strip():
            raise ValueError(f"Role {role['id']} is missing an anti-trigger")
        if role["id"] == "p3/leaf/motion-graphics":
            if (role.get("runtime_admission") is not True or role.get("active_release") is not True
                    or role.get("effectiveness") != "bounded_actual_task_verified"):
                raise ValueError("Bounded motion role status disagrees with its catalog record")
            if role.get("runtime_admission_basis", {}).get("evidence") != admitted[role["id"]].get("evidence", {}).get("path"):
                raise ValueError("Bounded motion role evidence path drifted")
        elif (role.get("runtime_admission") is not False or role.get("active_release") is not False
              or role.get("effectiveness") != "not_run"):
            raise ValueError(f"Cold design role {role['id']} overstates runtime admission")
    if len(roles) - len(admitted) != 57:
        raise ValueError("The catalog must retain exactly 57 cold design roles")
    for record in admitted_records:
        for field in ("brief", "launcher"):
            path = (ROOT / record[field]).resolve(strict=True)
            if not path.is_relative_to((ROOT / "legion/skills/wuji-legion-5-0").resolve()) or not path.is_file():
                raise ValueError(f"Admitted role {field} must resolve inside the 5.0 Skill")
            expected_hash = record.get(f"{field}_sha256")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise ValueError(f"Admitted role {field} hash drifted")
        evidence = record.get("evidence", {})
        evidence_path = ROOT / evidence.get("path", "")
        evidence_present = evidence_path.is_file()
        if evidence_present:
            digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            if digest != evidence.get("sha256"):
                raise ValueError("Available historical motion evidence has drifted")
    contract = release.get("role_contract")
    if (not isinstance(contract, dict) or contract.get("return_path") != "expert -> aji"
            or contract.get("missing_trigger_behavior") != "selection_gap"):
        raise ValueError("5.0 direct expert role contract is incomplete")
    if (direct.get("state") != "cold_catalog_with_one_bounded_consumer_extension"
            or direct.get("execution", {}).get("return_path") != ["expert", "aji"]):
        raise ValueError("Direct expert manifest return path drifted")
    if direct.get("catalog") != "catalog/p3/experts.json":
        raise ValueError("Direct expert manifest points to a different role catalog")
    extension = direct.get("bounded_extensions")
    if (not isinstance(extension, list) or len(extension) != 1 or not isinstance(extension[0], dict)
            or extension[0].get("role_id") != "p3/leaf/motion-graphics"
            or extension[0].get("legacy_call_binding_is_authoritative") is not False
            or extension[0].get("brief") != admitted["p3/leaf/motion-graphics"]["brief"]
            or extension[0].get("launcher") != admitted["p3/leaf/motion-graphics"]["launcher"]):
        raise ValueError("The bounded motion role must resolve through its 5.0 entry")
    return {
        "state": "catalog_contract_valid_with_one_bounded_role",
        "release": release["release"],
        "role_count": len(roles),
        "catalog_sha256": release["catalog"]["sha256"],
        "direct_manifest_sha256": release["direct_expert_manifest"]["sha256"],
        "runtime_admission_claim": "one_bounded_role_only; current invocation must still observe host and local tools",
        "admitted_role_ids": sorted(admitted),
        "cold_design_role_count": 57,
        "historical_local_evidence_present": evidence_present,
        "effectiveness": "one_bounded_role_only",
    }


if __name__ == "__main__":
    try:
        print(json.dumps(validate_catalog(), ensure_ascii=False))
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"state": "invalid", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
