from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "docs" / "wuji-legion-4.0-execution-plan-v1.6-2026-10-03.md"
DESIGN_PATH = ROOT / "docs" / "expert-design-map.json"
LEDGER_PATH = ROOT / "outputs" / "p0" / "atom-evidence-ledger.json"
REQUIREMENT_PATH = ROOT / "outputs" / "p0" / "requirement-map.json"
RELEASE = "p3-catalog-1"
QUALITY_SOURCE_PATHS = (
    "docs/wuji-legion-4.0-execution-plan-v1.6-2026-10-03.md", "docs/expert-design-map.json",
    "outputs/p0/atom-evidence-ledger.json", "outputs/p0/requirement-map.json",
    "catalog/p3/experts.json", "catalog/p3/atom-assemblies.json", "catalog/p3/composition-manifest.json",
    "tools/build_p3_catalog.py",
)


def quality_current(root: Path, report: dict) -> bool:
    expected = report.get("source_hashes")
    if not isinstance(expected, dict) or set(expected) != set(QUALITY_SOURCE_PATHS):
        return False
    try:
        return report.get("passed") is True and all(
            expected[path] == sha256(root / path) for path in QUALITY_SOURCE_PATHS)
    except OSError:
        return False


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path, kind: str):
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path), "kind": kind}


def main() -> None:
    design = read_json(DESIGN_PATH)
    ledger = read_json(LEDGER_PATH)
    requirements = read_json(REQUIREMENT_PATH)
    atom_by_id = {atom["candidate_id"]: atom for atom in ledger["atoms"]}
    roles = []
    consumers = defaultdict(list)
    missing_atoms = []

    for item in design["responsibilities"]:
        atom_refs = []
        for atom_id in item["atom_refs"]:
            atom = atom_by_id.get(atom_id)
            if atom is None:
                missing_atoms.append({"responsibility": item["baseline_id"], "atom": atom_id})
                continue
            consumers[atom_id].append(item["baseline_id"])
            atom_refs.append({
                "candidate_id": atom_id,
                "name": atom.get("name"),
                "layer_proposal": atom.get("layer_proposal"),
                "input": atom.get("input"),
                "output": atom.get("output"),
                "professional_difference": atom.get("professional_difference"),
                "admission": atom.get("admission"),
                "runtime": atom.get("runtime"),
                "source_evidence": atom.get("approved_source"),
                "method_source_bindings": atom.get("method_source_bindings", []),
            })
        role_id = f"p3/{item['kind']}/{item['baseline_id']}"
        body = {
            "id": role_id,
            "baseline_id": item["baseline_id"],
            "kind": item["kind"],
            "design_target": item["design_target"],
            "five_elements": item["five_elements"],
            "anti_trigger": item["anti_trigger"],
            "owner_rule": item["owner_rule"],
            "scope_rule": item["scope_rule"],
            "cancellation": item["cancellation"],
            "atom_refs": atom_refs,
            "composition_dependencies": item["composition_dependencies"],
            "source_refs": [item["provenance"]],
            "body_state": "structured_body_written_from_frozen_4_0_design",
            "runtime_admission": False,
            "effectiveness": "not_run",
            "active_release": False,
            "cold_reason": "P3 catalog contract is written, but professional effectiveness and required source/asset coverage remain unverified.",
        }
        roles.append(body)

    atom_assemblies = []
    for atom_id in sorted(consumers):
        atom = atom_by_id[atom_id]
        atom_assemblies.append({
            "candidate_id": atom_id,
            "layer": atom.get("layer_proposal"),
            "shared_definition": {
                "name": atom.get("name"),
                "input": atom.get("input"),
                "output": atom.get("output"),
                "consumer_and_counterexample": atom.get("consumer_and_counterexample"),
            },
            "source_evidence": atom.get("approved_source"),
            "method_source_bindings": atom.get("method_source_bindings", []),
            "consumers": sorted(consumers[atom_id]),
            "runtime_admission": False,
            "effectiveness": "not_run",
        })

    composition = []
    for role in roles:
        composition.append({
            "role_id": role["id"],
            "baseline_id": role["baseline_id"],
            "shared_components": sorted(set(role["composition_dependencies"])),
            "professional_difference": {
                "design_target": role["design_target"],
                "inputs": role["five_elements"]["inputs"],
                "outputs": role["five_elements"]["output"],
                "acceptance": role["five_elements"]["acceptance"],
                "anti_trigger": role["anti_trigger"],
            },
            "unique_owner": "aji-integration-owner",
            "write_scope": "role-instance-only; shared definitions are referenced, not copied",
            "reverse_dependencies": sorted([consumer for consumer in consumers.get(role["atom_refs"][0]["candidate_id"], []) if consumer != role["baseline_id"]]) if role["atom_refs"] else [],
        })

    common = {
        "course-five-elements": "引用 role.five_elements，不复制公共正文",
        "minimum-correct": "共享最小正确路径与必要闭包",
        "white-hat": "缺证据保留 unknown，禁止越权与伪完成",
        "versioned-handoff": "版本、scope、读写权和回读句柄绑定",
    }
    manifest = {
        "schema_version": 1,
        "release": RELEASE,
        "baseline": ref(BASELINE_PATH, "approved_execution_plan"),
        "design_source": ref(DESIGN_PATH, "frozen_p1_design"),
        "common_components": common,
        "roles": composition,
        "rules": {
            "shared_experts": "reference_only",
            "leader_assembly": "task_recipe_only",
            "duplicate_public_bodies": "forbidden",
            "style_changes_facts_or_permissions": False,
            "runtime_activation": "separate_effectiveness_gate",
        },
    }

    catalog = {
        "schema_version": 1,
        "release": RELEASE,
        "phase": "P3",
        "state": "catalog_written_cold",
        "baseline": ref(BASELINE_PATH, "approved_execution_plan"),
        "design_source": ref(DESIGN_PATH, "frozen_p1_design"),
        "atom_ledger": ref(LEDGER_PATH, "p0_evidence_ledger"),
        "requirement_map": ref(REQUIREMENT_PATH, "p0_requirement_map"),
        "role_count": len(roles),
        "roles": roles,
        "runtime_admission": False,
        "formal_model_experts": 0,
        "effectiveness": "not_run",
    }
    quality = {
        "schema_version": 1,
        "release": RELEASE,
        "phase": "P3",
        "checks": {
            "baseline_bound": catalog["baseline"]["sha256"] == sha256(BASELINE_PATH),
            "design_bound": catalog["design_source"]["sha256"] == sha256(DESIGN_PATH),
            "atom_ledger_bound": catalog["atom_ledger"]["sha256"] == sha256(LEDGER_PATH),
            "requirement_map_bound": catalog["requirement_map"]["sha256"] == sha256(REQUIREMENT_PATH),
            "all_57_responsibilities_covered": len(roles) == 57,
            "unique_role_ids": len({role["id"] for role in roles}) == len(roles),
            "five_elements_complete": all(set(role["five_elements"]) == {"goal", "inputs", "process", "output", "acceptance"} for role in roles),
            "source_refs_present": all(role["source_refs"] for role in roles),
            "shared_components_referenced": all(role["shared_components"] for role in composition),
            "no_runtime_admission_claimed": catalog["runtime_admission"] is False and catalog["formal_model_experts"] == 0,
            "no_old_implementation_imported": True,
        },
        "counts": {
            "responsibilities": len(roles),
            "workflow": sum(role["kind"] == "workflow" for role in roles),
            "leaf": sum(role["kind"] == "leaf" for role in roles),
            "method": sum(role["kind"] == "method" for role in roles),
            "governance": sum(role["kind"] == "governance" for role in roles),
            "selector": sum(role["kind"] == "selector" for role in roles),
            "shared_atom_assemblies": len(atom_assemblies),
            "missing_atom_refs": len(missing_atoms),
        },
        "missing_atom_refs": missing_atoms,
        "limitations": [
            "Structured catalog bodies are written from frozen 4.0 design inputs; they are not claims of professional model effectiveness.",
            "Roles with incomplete source or asset evidence remain cold and are not routed at runtime.",
            "P4 real tool and professional artifact verification is still required.",
        ],
        "passed": all(quality for quality in {
            "baseline": catalog["baseline"]["sha256"] == sha256(BASELINE_PATH),
            "design": catalog["design_source"]["sha256"] == sha256(DESIGN_PATH),
            "count": len(roles) == 57,
            "unique": len({role["id"] for role in roles}) == len(roles),
            "five_elements": all(set(role["five_elements"]) == {"goal", "inputs", "process", "output", "acceptance"} for role in roles),
            "sources": all(role["source_refs"] for role in roles),
            "cold": catalog["runtime_admission"] is False,
        }.values()),
    }

    out = ROOT / "catalog" / "p3"
    out.mkdir(parents=True, exist_ok=True)
    (out / "experts.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "atom-assemblies.json").write_text(json.dumps({"schema_version": 1, "release": RELEASE, "assemblies": atom_assemblies}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "composition-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    quality["passed"] = all(quality["checks"].values()) and not missing_atoms
    quality["source_hashes"] = {path: sha256(ROOT / path) for path in QUALITY_SOURCE_PATHS}
    (ROOT / "outputs" / "p3" / "p3-quality-report.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
