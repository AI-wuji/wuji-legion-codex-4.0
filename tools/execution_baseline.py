import hashlib
import json
from pathlib import Path

from p6_package_validation import strict_json


ROOT = Path(__file__).resolve().parents[1]

ACTIVE_SCENARIO_OVERRIDES = {
    "T70": {
        "normal_spec": "4096为单项工具/函数返回摘要预算，不截坏JSON；完整证据可回读；240000/90000为压缩与Skill投影策略值，不是上下文或计费硬限",
        "negative_spec": "以4096截断完整证据、删除证据、以240000/90000承诺费用或限制模型上下文",
    },
    "T71": {
        "normal_spec": "configured/observed/effective/unknown分开；记录gpt-6.1-sol官方1050000上下文与128000最大输出但不冒充当前宿主有效值；窗口不明不算5440；更新后观察失效",
        "negative_spec": "把272000当gpt-6.1-sol完整上下文或最大单次调用、套另一模型窗口、以磁盘值冒充有效值",
    },
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_path(root, value):
    if not isinstance(value, str) or not value:
        raise ValueError("Nonempty project path required")
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError("Baseline evidence must be a current project file")
    return resolved


def load_active(root=ROOT):
    baseline = strict_json((root / "docs/execution-baseline.json").read_text(encoding="utf-8"))
    if baseline.get("version") not in ("1.6", "1.7") or baseline.get("P7") != "separate_approval" or baseline.get("shutdown") is not False:
        raise ValueError("Unsupported or unauthorized execution baseline")
    plan = project_path(root, baseline["plan"])
    if digest(plan) != baseline["sha256"]:
        raise ValueError("Active execution plan differs from approved hash")
    if baseline["version"] == "1.7":
        prior = baseline["prior_baseline"]
        if prior["version"] != "1.6" or prior.get("retained_read_only") is not True:
            raise ValueError("Revision must retain the complete 1.6 requirements")
        if digest(project_path(root, prior["plan"])) != prior["sha256"] or digest(project_path(root, prior["manifest"])) != prior["manifest_sha256"]:
            raise ValueError("Historical 1.6 evidence changed")
        original = strict_json(project_path(root, prior["manifest"]).read_text(encoding="utf-8"))
        if original["version"] != "1.6" or original["sha256"] != prior["sha256"]:
            raise ValueError("Historical baseline identity differs")
        if baseline["preserved_baseline_counts"] != original["preserved_baseline_counts"]:
            raise ValueError("Revision cannot silently delete inherited coverage")
        exceptions = baseline.get("authorized_design_supersessions", {})
        if set(exceptions) != {"docs/execution-baseline.json"}:
            raise ValueError("Only the explicitly authorized active baseline may supersede frozen design")
        exception = exceptions["docs/execution-baseline.json"]
        if exception["historical_snapshot"] != prior["manifest"] or exception["historical_sha256"] != prior["manifest_sha256"] or not exception.get("reason"):
            raise ValueError("Invalid baseline history preservation exception")
    return baseline


def frozen_observation(root, entry, active):
    path = project_path(root, entry["path"])
    current = digest(path)
    result = {"path": entry["path"], "expected_sha256": entry["sha256"], "actual_sha256": current,
              "unchanged": current == entry["sha256"], "preserved": current == entry["sha256"], "authorized_supersession": False}
    exception = active.get("authorized_design_supersessions", {}).get(entry["path"])
    if not result["unchanged"] and exception:
        historical = project_path(root, exception["historical_snapshot"])
        preserved = digest(historical) == entry["sha256"] == exception["historical_sha256"]
        result.update(preserved=preserved, authorized_supersession=preserved,
                      historical_snapshot=exception["historical_snapshot"], reason=exception["reason"])
    return result


def build_execution_map(root=ROOT):
    active = load_active(root)
    specs = strict_json((root / "docs/acceptance-map.json").read_text(encoding="utf-8"))
    identifiers = [row["id"] for row in specs["tests"]]
    if len(identifiers) != 95 or set(identifiers) != {f"T{index:02}" for index in range(1, 96)}:
        raise ValueError("All 95 inherited scenarios must remain identifiable")
    p7 = {row["id"] for row in specs["tests"] if row["gate"] == "G7"}
    if p7 != {"T43", "T44", "T74"}:
        raise ValueError("P7 scope cannot be silently expanded or removed")
    first = {"T01", "T02", "T05", "T06", "T11", "T12", "T13", "T18", "T70", "T83", "T89"}
    tool = {"T25", "T26", "T27", "T28", "T29", "T30", "T85", "T95"}
    media = {f"T{index:02}" for index in range(31, 39)} | {"T78", "T79", "T80", "T81", "T87", "T88"}
    rows = []
    for spec in specs["tests"]:
        identifier = spec["id"]
        priority = "separately_authorized_p7" if identifier in p7 else "first_usable_entry_and_task" if identifier in first else "actual_professional_tools" if identifier in tool else "actual_content_and_media" if identifier in media else "task_driven_remaining_requirements"
        override = ACTIVE_SCENARIO_OVERRIDES.get(identifier, {})
        rows.append({"id": identifier, "name": spec["name"], "gate": spec["gate"], "priority": priority,
                     "normal_spec": override.get("normal_spec", spec["normal_spec"]),
                     "negative_spec": override.get("negative_spec", spec["negative_spec"]),
                     "required_for_g6": identifier not in p7, "requirement_changed": False, "execution_status": "see_current_acceptance_ledger"})
    return {"schema_version": 1, "active_plan": {key: active[key] for key in ("version", "plan", "sha256")},
            "requirements_origin": specs["baseline"], "acceptance_spec_sha256": digest(root / "docs/acceptance-map.json"),
            "total": 95, "required_for_g6": 92, "removed_scenarios": [], "rows": rows,
            "authority": "Execution order only; no completed scenario, runtime admission, deferred requirement or P7 permission implied."}


def main():
    mapping = build_execution_map()
    (ROOT / "docs/plan-execution-map-v1.7.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    active = load_active()
    frozen = strict_json((ROOT / "docs/design-baseline-1.json").read_text(encoding="utf-8"))
    history = [frozen_observation(ROOT, entry, active) for entry in frozen["files"]]
    report = {"schema_version": 1, "kind": "approved_revision_integrity_not_runtime_acceptance", "active_version": active["version"],
              "active_sha256": active["sha256"], "history": history, "inherited_scenarios": 95, "required_for_g6": 92,
              "passed": all(row["preserved"] for row in history), "P7": False, "shutdown": False}
    (ROOT / "outputs/p1/plan-1.7-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"active_version": active["version"], "revision_integrity_passed": report["passed"], "total": 95, "required_for_g6": 92}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
