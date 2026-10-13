"""Materialize reviewed P0 decisions; never admit runtime capabilities."""

import csv
from collections import Counter
import hashlib
import json
from pathlib import Path

from preflight import PLAN, ROOT, active_baseline, digest, stamp, write_json

TREATMENTS = {"distill-to-atom", "native-tool", "dependency", "asset-reference", "reject"}
FAMILY_TARGETS = {
    "A": "requirement-intake", "B": "scope-authorization", "C": "evidence",
    "D": "minimal-correct-path", "E": "composition", "F": "selection",
    "G": "exact-reference-lineage", "H": "scheduling", "I": "action-lifecycle",
    "J": "artifact-acceptance", "K": "context-projection", "L": "experience",
    "M": "source-admission-release", "N": "content-intent", "O": "media-time",
    "P": "engineering-behavior",
}
DISTINCTIONS = [
    ("A01", "A02", "结果目标不等于文件列表；要求Excel不能替代要解决的问题"),
    ("A03", "J07", "满意标准提案与硬检查放行不同，主观高分不能消除必需失败"),
    ("B01", "B02", "数据scope与actor读取权分别检查；同项目不等于每个actor都可读"),
    ("B03", "B07", "当前动作许可与动作升级重新授权不同；阅读许可不含发布"),
    ("B05", "B06", "产物写owner与用户决定权不同；可写不能替用户确认"),
    ("C02", "C04", "来源等级与范围适用性不同；官方旧版本也可能不适用"),
    ("C07", "I05", "执行来源可信与请求参数绑定不同；宿主回执还须对应锁定动作"),
    ("C08", "J05", "完成声明资格与交付物覆盖不同；覆盖齐全仍可能未验收"),
    ("D04", "J07", "按风险选择检查与已有硬检查放行不同；不能为省事略过失败"),
    ("D05", "H06", "并行收益与写冲突不同；省时也不能同路径并发写"),
    ("D08", "H05", "无进展停止与次数额度不同；额度未尽也应停重复无证据重试"),
    ("E01", "J02", "定义schema形状与交付文件可解析性不同；JSON契约正确不证明PPT可打开"),
    ("E05", "E07", "必需不变量与互斥槽冲突不同；加载顺序不能解决授权削弱"),
    ("E06", "G05", "菱形去重与无环检查不同；重复依赖可去重，真环必须拒绝"),
    ("F03", "F06", "能力匹配与健康状态不同；擅长声明不能绕过未验证或过期"),
    ("G01", "G02", "精确修订解析与内容hash不同；hash正确不能指向另一个版本"),
    ("G02", "G03", "内容完整性与当前采用有效性不同；被撤销文件hash仍正确"),
    ("G06", "M06", "全影响消费者闭包与各表现回归集合不同；20条第一页不能证明完整"),
    ("G07", "J06", "attempt回执时效与报告产物版本绑定不同；两者都须通过"),
    ("H03", "H04", "领取资格与租约存续不同；曾领取不能授权过期提交"),
    ("I02", "I03", "可提交意图与重复事件判定不同；登记不是执行也不是付费成功"),
    ("I06", "H05", "unknown查询恢复与重试额度不同；不能换幂等键再次付费"),
    ("I07", "I08", "资源归属与释放证明不同；任务完成不等于宿主已退出"),
    ("J01", "J02", "文件可读与格式可解析不同；伪扩展名可读但格式不合格"),
    ("J03", "M03", "素材用途权利与源代码许可适配不同；可下载不等于可商用"),
    ("J04", "G03", "某产物正式采用与上游当前有效不同；已采用也可能后来撤销"),
    ("J08", "P08", "返工写owner与回归影响用例不同；不能让验证者修改他人产物"),
    ("K03", "K04", "主输入原文与必需指令投影不同；摘要不能替代原台词或源码"),
    ("K07", "G08", "缓存查询身份与派生索引发布新鲜度不同；scope变更必须失效"),
    ("L04", "L06", "范围内复用与全局泛化不同；一次成功不能升级全球规则"),
    ("L07", "M08", "经验撤销过滤与恢复发布资格不同；回滚不得恢复已撤销经验"),
    ("M02", "M04", "当前稳定版观察与采用例外不同；最新不自动可用"),
    ("M05", "J05", "运行资产完备与用户交付齐全不同；规则摘要不等于脚本和字体"),
    ("N03", "N04", "事实保持与实体身份连续不同；同名角色不自动是同一人"),
    ("N06", "O05", "情绪曲线意图与声轨路由不同；一首BGM不能替代分轨工程"),
    ("O01", "O03", "精确时间单位转换与片段时长合成不同；转场重叠不重复相加"),
    ("O02", "O08", "事件窗口约束与真实输出测量不同；字数估计不是音频时长"),
    ("O04", "O07", "时间线锚点与工程素材引用不同；工程打开仍可能声音锚点已过期"),
    ("P03", "P04", "可复现症状与根因区分实验不同；复现不自动证实某个猜测"),
    ("P06", "P07", "接口兼容与宿主真实注册不同；import成功不证明节点可见"),
]


def load(name):
    return json.loads((ROOT / "outputs/p0" / name).read_text(encoding="utf-8"))


def reviewed_decisions(rows, sources):
    ids = [row["id"] for row in rows]
    expected = {source["baseline_fields"][0] for source in sources}
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("Source decisions must cover every baseline id exactly once")
    result = []
    for row in rows:
        if row["treatment"] not in TREATMENTS or not row["reason"].strip() or not row["target"].strip():
            raise ValueError("Invalid reviewed source treatment")
        result.append(row)
    return result


def unique_anchor(lines, cells):
    expected = "| " + " | ".join(cells) + " |"
    matches = [number for number, line in enumerate(lines, 1) if line.strip() == expected]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous exact baseline anchor: " + cells[0])
    return matches[0]


def preserve_method_bindings(current, previous):
    semantic_fields = ("candidate_id", "name", "input", "output", "consumer_and_counterexample",
                       "target_module_proposal", "professional_difference", "approved_source")
    if previous is None or any(current.get(key) != previous.get(key) for key in semantic_fields):
        return current
    for key in ("method_source_bindings", "primary_method_attribution", "method_binding_reviewed_at"):
        if key in previous:
            current[key] = previous[key]
    return current


def primary_review_state(source, decision):
    unchanged = all(source.get(key) == decision.get(key) for key in ("treatment", "target", "reason"))
    if decision["treatment"] == "reject":
        return "not_required_for_rejected_runtime"
    return source.get("primary_review", "pending_before_admission") if unchanged else "pending_before_admission"


def materialize():
    baseline_ref = active_baseline()
    plan_hash = baseline_ref["sha256"]
    plan_lines = PLAN.read_text(encoding="utf-8-sig").splitlines()
    baseline = load("source-baseline.json")
    decision_path = ROOT / "docs/source-dispositions.tsv"
    with decision_path.open(encoding="utf-8", newline="") as stream:
        rows = reviewed_decisions(list(csv.DictReader(stream, delimiter="\t")), baseline["sources"])
    decisions = {row["id"]: row for row in rows}
    review = load("upstream-version-review.json")
    by_id = {row["baseline_id"]: row for row in review["sources"]}
    for source in baseline["sources"]:
        source_id, name, old_state, old_target = source["baseline_fields"]
        decision = decisions[source_id]
        primary_review = primary_review_state(source, decision)
        provenance = {"path": str(PLAN), "sha256": plan_hash,
                      "line": unique_anchor(plan_lines, source["baseline_fields"]),
                      "kind": "approved_requirement_not_upstream_read"}
        source.update(review="disposition_reviewed", adopted=False,
                      treatment=decision["treatment"], target=decision["target"],
                      reason=decision["reason"], baseline_provenance=provenance,
                      decision_sha256=digest(decision_path),
                      primary_review=primary_review)
        source["historical_state_not_inherited"] = {"state": old_state, "target": old_target}
        upstream = by_id[source_id]
        upstream.update(treatment=decision["treatment"], target=decision["target"],
                        reason=decision["reason"], adopted=False)
        if decision["primary_locator"] != "unknown":
            if upstream.get("origin_locator") != decision["primary_locator"]:
                upstream["locator_status"] = "discovered_not_current_primary_review"
            upstream["origin_locator"] = decision["primary_locator"]
        if decision["treatment"] == "reject":
            upstream.update(freshness="not_required_for_rejected_runtime", license="not_imported",
                            required_assets="none_imported", verification="no_runtime_admission")
    baseline.update(baseline=baseline_ref, reviewed_at=stamp(), G0="not_passed")
    review["baseline"] = baseline_ref
    review["observed_at"] = stamp()
    write_json(ROOT / "outputs/p0/source-baseline.json", baseline)
    write_json(ROOT / "outputs/p0/upstream-version-review.json", review)
    candidates = load("atom-candidates.json")
    ledger_path = ROOT / "outputs/p0/atom-evidence-ledger.json"
    previous_atoms = load("atom-evidence-ledger.json")["atoms"] if ledger_path.is_file() else []
    previous_by_id = {row["candidate_id"]: row for row in previous_atoms}
    if len(previous_by_id) != len(previous_atoms):
        raise ValueError("Duplicate candidate evidence ids")
    ledger = []
    for candidate in candidates["candidates"]:
        atom_id = candidate["id"]
        fields = candidate["baseline_fields"]
        if "→" not in fields[1]:
            raise ValueError("Baseline candidate has no input/output boundary: " + atom_id)
        input_spec, output_spec = fields[1].split("→", 1)
        anchor = unique_anchor(plan_lines, [atom_id, *fields])
        row = {"candidate_id": atom_id, "name": fields[0], "layer_proposal": "L1",
                       "input": input_spec, "output": output_spec,
                       "consumer_and_counterexample": fields[2],
                       "target_module_proposal": FAMILY_TARGETS[atom_id[0]],
                       "approved_source": {"path": str(PLAN), "sha256": plan_hash, "line": anchor,
                                           "kind": "approved_semantic_proposal"},
                       "admission": "not_admitted", "runtime": "not_implemented",
                       "single_responsibility_review": "boundary_recorded_final_review_at_G1",
                       "primary_method_attribution": "pending_field_level_source_binding",
                       "implementation_bindings": [], "effectiveness_tests": [],
                       "professional_difference": fields[2]}
        ledger.append(preserve_method_bindings(row, previous_by_id.get(atom_id)))
    if len(ledger) != 128 or len({row["candidate_id"] for row in ledger}) != 128:
        raise ValueError("Candidate baseline coverage mismatch")
    bound_count = sum(bool(row.get("method_source_bindings")) for row in ledger)
    write_json(ROOT / "outputs/p0/atom-evidence-ledger.json",
               {"schema_version": 1, "baseline": baseline_ref, "observed_at": stamp(), "G0": "not_passed", "atoms": ledger,
                "method_binding_summary": {"bound_candidates": bound_count, "total_candidates": len(ledger),
                                           "formal_admission": False, "runtime_implementation": False},
                "boundary": "Approved plan anchors prove required semantics, not upstream reading or implementation."})
    write_json(ROOT / "outputs/p0/semantic-overlap-map.json",
               {"schema_version": 1, "baseline": baseline_ref, "observed_at": stamp(), "G0": "not_passed",
                "covered_candidate_ids": [row["candidate_id"] for row in ledger],
                "pairs": [{"left": left, "right": right, "decision": "keep_distinct",
                           "reason_and_counterexample": reason} for left, right, reason in DISTINCTIONS],
                "rule": "未列的组合不宣称穷尽；共享结果类型或同类消费者不构成合并证据。",
                "formal_admission": False})
    responsibilities = load("responsibility-map.json")
    for row in responsibilities["responsibilities"]:
        fields = row["baseline_fields"]
        row.update(review="approved_destination_anchored", adopted=False,
                   proposed_target=fields[1], professional_difference=fields[2],
                   provenance={"path": str(PLAN), "sha256": plan_hash,
                               "line": unique_anchor(plan_lines, fields)},
                   runtime="not_implemented", expert_contract="not_frozen")
    responsibilities["baseline"] = baseline_ref
    write_json(ROOT / "outputs/p0/responsibility-map.json", responsibilities)
    return {"sources_with_decisions": len(rows), "treatments": dict(Counter(row["treatment"] for row in rows)),
            "candidate_boundaries": len(ledger), "reviewed_distinct_pairs": len(DISTINCTIONS),
            "candidate_method_bindings": bound_count,
            "responsibility_destinations": len(responsibilities["responsibilities"]),
            "admitted_experts": 0, "G0": "not_passed"}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(materialize(), ensure_ascii=False))
