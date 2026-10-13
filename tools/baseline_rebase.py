"""Rebase P0 audit references without rescanning or resetting reading evidence."""

import json

from preflight import PLAN, ROOT, active_baseline, plan_rows, stamp, write_json


def merge_plan_rows(previous, current):
    previous_by_id = {row["id"]: row for row in previous}
    current_ids = {row["id"] for row in current}
    if len(previous_by_id) != len(previous) or len(current_ids) != len(current) or set(previous_by_id) != current_ids:
        raise ValueError("Plan rebase must not add, lose, or duplicate baseline ids")
    merged = []
    for row in current:
        preserved = dict(previous_by_id[row["id"]])
        if preserved["baseline_fields"] != row["baseline_fields"]:
            history = list(preserved.get("baseline_fields_history", []))
            history.append(preserved["baseline_fields"])
            preserved["baseline_fields_history"] = history
        preserved["baseline_fields"] = row["baseline_fields"]
        merged.append(preserved)
    return merged


def rebase():
    baseline = active_baseline()
    text = PLAN.read_text(encoding="utf-8-sig")
    requirements = plan_rows(text, "R", 72)
    tests = plan_rows(text, "T", 95)
    topics = plan_rows(text, "CHAT", 48)
    names = ["requirement-map.json", "conversation-requirement-map.json", "atom-candidates.json",
             "source-baseline.json", "responsibility-map.json", "source-summary.json",
             "upstream-version-review.json"]
    pending = {}
    for name in names:
        path = ROOT / "outputs/p0" / name
        value = json.loads(path.read_text(encoding="utf-8"))
        old = value.get("baseline")
        if old and old != baseline:
            history = list(value.get("baseline_history", []))
            if old not in history:
                history.append(old)
            value["baseline_history"] = history
        value["baseline"] = baseline
        value["rebased_at"] = stamp()
        if name == "requirement-map.json":
            value["requirements"] = merge_plan_rows(value["requirements"], requirements)
            value["tests"] = merge_plan_rows(value["tests"], tests)
        if name == "conversation-requirement-map.json":
            value["topics"] = merge_plan_rows(value["topics"], topics)
        pending[name] = value
    for name, value in pending.items():
        write_json(ROOT / "outputs/p0" / name, value)
    coverage_path = ROOT / "outputs/p0/source-coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    counts_before = dict(coverage["counts"])
    coverage["execution_baseline"] = baseline
    coverage["scope"] = "2026-10-03 authorized summaries/necessary originals; reading remains separate from runtime admission"
    write_json(coverage_path, coverage)
    report = {"observed_at": stamp(), "baseline": baseline, "artifacts_rebased": names,
              "requirements": len(requirements), "acceptance_scenarios": len(tests),
              "conversation_topics": len(topics), "source_reading_counts_preserved": counts_before,
              "reading_records_reset": False, "core_implementation_written": False,
              "G0": "not_passed", "G1": "not_passed"}
    write_json(ROOT / "outputs/p0/baseline-revision-audit.json", report)
    return report


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(rebase(), ensure_ascii=False))
