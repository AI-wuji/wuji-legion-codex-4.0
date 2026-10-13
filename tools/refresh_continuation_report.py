from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import argparse
import hashlib

from p6_acceptance import ROOT, SEMANTIC_PYTHON_CASES, SUPPORTING_PYTHON_CASES, digest, evaluate
from p6_package_validation import confined_path, strict_json
from execution_baseline import load_active


def write_json(relative: str, value: dict) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def core_closeout_state(acceptance: dict, deployment: dict) -> dict:
    states = {row["id"]: row["status"] for row in acceptance.get("matrix", [])}
    remaining = [identifier for identifier in ("T19", "T22")
                 if acceptance.get("evidence_valid") is not True or states.get(identifier) != "passed"]
    entry = deployment.get("entry", {})
    skill = entry.get("core_skill_observation", {})
    agents = entry.get("global_agents_observation", {})
    if skill.get("installed") is not True or skill.get("state") != "source_match":
        remaining.append("current_core_skill_source_match")
    if agents.get("default_entry_rule_present") is not True or agents.get("white_hat_rule_present") is not True:
        remaining.append("current_global_entry_rule_observation")
    return {"core_closeout_complete": not remaining,
            "next_local_work": [{"id": identifier, "action": "resolve_current_core_gap_and_check_matched_evidence"}
                                for identifier in remaining],
            "basis": "current evidenced repair, local resource ACL and observed core deployment only; not full capability acceptance"}


def current_core_projection(root: Path = ROOT, *,
                            receipt_path: str = "outputs/p6/continuation-2026-10-06/core-completion-execution.json",
                            deployment: dict | None = None, config_path: Path | None = None) -> dict:
    path = confined_path(root, receipt_path)
    if not path.is_file():
        return {"scope": "current_scoped_core_not_full_acceptance", "receipt_path": receipt_path,
                "evidence_valid": False, "state": "receipt_missing",
                "closeout": {"core_closeout_complete": False,
                             "next_local_work": [{"id": "current_core_receipt", "action": "execute_current_core_checks"}]}}
    try:
        content = path.read_bytes()
        receipt = strict_json(content.decode("utf-8"))
        if any(not isinstance(receipt.get(section, {}), dict)
               for section in ("rust", "python", "configuration", "tool_evidence_hashes")):
            raise ValueError("Invalid execution receipt section")
        specs = strict_json((root / "docs/acceptance-map.json").read_text(encoding="utf-8"))
        evaluated = evaluate(root, specs, receipt, receipt_path=receipt_path)
    except (OSError, ValueError, TypeError, KeyError):
        return {"scope": "current_scoped_core_not_full_acceptance", "receipt_path": receipt_path,
                "evidence_valid": False, "state": "receipt_invalid",
                "full_spec_retested": False, "full_capability_acceptance_complete": False,
                "configuration_content_exported": False,
                "closeout": {"core_closeout_complete": False,
                             "next_local_work": [{"id": "current_core_receipt", "action": "replace_invalid_or_unreadable_execution_evidence"}]}}
    if deployment is None:
        from wuji4 import status
        deployment = status()
    closeout = core_closeout_state(evaluated, deployment)
    configuration = config_path if config_path is not None else Path.home() / ".codex/config.toml"
    try:
        current_hash = digest(configuration) if configuration.is_file() else None
    except OSError:
        current_hash = None
    protection = receipt.get("configuration", {})
    config_preserved = (current_hash is not None and protection.get("unchanged") is True
                        and protection.get("before_sha256") == current_hash == protection.get("after_sha256"))
    if not config_preserved:
        closeout["core_closeout_complete"] = False
        closeout["next_local_work"].append({"id": "current_configuration_evidence", "action": "observe_without_modifying_configuration"})
    return {"scope": "current_scoped_core_not_full_acceptance", "receipt_path": receipt_path,
            "receipt_sha256": hashlib.sha256(content).hexdigest(), "evidence_valid": evaluated["evidence_valid"],
            "state": "current" if evaluated["evidence_valid"] else "failed_or_stale",
            "configuration_preserved": config_preserved, "configuration_content_exported": False,
            "deployment_observation": deployment.get("entry", {}),
            "matched_current_scenarios": [row for row in evaluated["matrix"] if row["status"] == "passed"],
            "current_scoped_statuses": [{"id": row["id"], "status": row["status"]} for row in evaluated["matrix"]],
            "full_spec_retested": False, "full_capability_acceptance_complete": False,
            "closeout": closeout}


def refresh_current_remaining() -> dict:
    projection = current_core_projection()
    formal_path = ROOT / "outputs/p6/acceptance-execution.json"
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    remaining = [row for row in formal["matrix"] if row["status"] != "passed"]
    observed = datetime.now(timezone.utc).isoformat()
    report = {"schema_version": 1, "observed_at": observed, "goal_complete": False,
              "goal_complete_basis": "full frozen capability acceptance, not the current scoped chat goal",
              "core_closeout_complete": projection["closeout"]["core_closeout_complete"],
              "full_capability_acceptance_complete": False,
              "goal_boundaries": "docs/goal-execution-boundaries-2026-10-05.md",
              "p7_conditionally_authorized": True, "shutdown_conditionally_authorized": False,
              "authorization_is_not_execution_or_gate_completion": True,
              "no_user_continue_prompt_required": True,
              "next_local_work": projection["closeout"]["next_local_work"],
              "current_core": projection,
              "historical_formal_ledger": "outputs/p6/acceptance-execution.json",
              "historical_formal_ledger_sha256": digest(formal_path),
              "historical_status_counts": formal["summary"]["status_counts"],
              "remaining_scenarios_basis": "historical formal ledger retained unchanged; current scoped coverage is in current_core",
              "remaining_scenarios": remaining,
              "peripheral_validation": "deferred_until_a_real_task_requires_it",
              "acceptance_ledger_is_not_a_prebuild_backlog": True,
              "formal_acceptance_rewritten": False, "P7": False, "shutdown": False}
    write_json("outputs/p6/remaining-work.json", report)
    return report


def main() -> None:
    receipt = json.loads((ROOT / "outputs/p6/test-execution.json").read_text(encoding="utf-8"))
    acceptance = json.loads((ROOT / "outputs/p6/acceptance-execution.json").read_text(encoding="utf-8"))
    if not acceptance["evidence_valid"] or receipt["rust"]["exit_code"] != 0 or not receipt["python"]["passed"]:
        raise ValueError("Current failed or stale execution cannot generate a successful continuation report")
    summary = acceptance["summary"]
    from wuji4 import status
    closeout = core_closeout_state(acceptance, status())
    counts = summary["status_counts"]
    observed = datetime.now(timezone.utc).isoformat()
    date = str(datetime.now(timezone(timedelta(hours=8))).date())
    gates = json.loads((ROOT / "docs/phase-gates.json").read_text(encoding="utf-8"))
    active = load_active()
    gates.setdefault("requirements_origin", gates["baseline"])
    gates["baseline"] = {key: active[key] for key in ("version", "plan", "sha256")}
    gates["gates"]["G1"]["approved_revision_integrity_report"] = "outputs/p1/plan-1.7-review.json"
    gates["updated_at"] = observed
    prepared_revisions = sorted({json.loads((ROOT / f"catalog/p2/{kind}.json").read_text(encoding="utf-8"))["revision"]
                                 for kind in ("engineering", "validation")})
    gates["gates"]["G2"]["current_release_native_retest"] = f"not_retested_current_release; previous isolated workers observed 429, current rate availability unknown; legacy bounded acceptance preserved, not rerun for schema6 and prepared role revisions {prepared_revisions}"
    gates["gates"]["G2"]["prepared_source_refresh"] = "outputs/p2/prepared-role-source-refresh.json"
    gates["gates"]["G2"]["bounded_legion_task"] = "outputs/p2/legion-first-task-receipt.json"
    gates["gates"]["G2"]["bounded_legion_task_current_recheck"] = "outputs/p2/legion-first-task-current-recheck.json"
    gates["gates"]["G2"]["project_local_framework_smoke"] = "outputs/p2/framework-doctor-current.json"
    gates["gates"]["G2"]["project_local_capability_view"] = "outputs/p2/framework-capabilities-current.json"
    gates["gates"]["G4"].update(
        available_local_chain=["software-repair/local-dag-validator",
                               "video-render/ffmpeg-bounded", "officecli/native-text-pptx",
                               "officecli/native-word-xlsx-bounded"],
        historical_local_chain=["comfyui/bounded-load-scale-save"],
        blocked_chains=["comfyui/current-endpoint", "audio-render/REAPER", "professional-effectiveness-holdouts"],
        current_comfyui_failure="outputs/p4/media-framework-failure-evidence.json",
        independent_video_evidence="outputs/p4/video-framework-workflow-evidence.json",
        officecli_bounded_evidence="outputs/p4/officecli-probe-evidence.json",
        office_document_bounded_evidence="outputs/p4/office-document-workflow-evidence.json",
        reason="Existing OfficeCLI text-PPTX, bounded Word/XLSX document workflow and independent PNG-to-video workflow have current actual evidence; DOCX rendering, ComfyUI, audio/REAPER and professional holdouts remain incomplete.")
    gates["gates"]["G5"]["local_persistence_report"] = "outputs/p5/resource-persistence-report-2026-10-04.json"
    gates["gates"]["G5"]["status"] = "in_progress_full_scope"
    gates["gates"]["G5"]["deterministic_governance_core_passed"] = True
    gates["gates"]["G5"]["scope_note"] = "Isolated local persistence, task actions, transfers and exact dependencies are implemented. One exact local experience was reviewed, used in followup manifest regression and rejected after source change. Autonomous model evolution and public admission remain incomplete."
    gates["gates"]["G5"]["bounded_legion_experience"] = "outputs/p5/legion-experience-task-receipt.json"
    gates["gates"]["G5"]["experience_workflow_regressions"] = "outputs/p5/experience-workflow-evidence.json"
    gates["gates"]["G5"]["implementation_delta"] = "docs/design-deltas/005-received-content-delta-2026-10-04.md"
    gates["gates"]["G6"].update(
        status="in_progress_internal_work_and_explicit_external_limits",
        acceptance_execution="outputs/p6/acceptance-execution.json", acceptance_summary=summary,
        required_followups=["Use selected existing professional/native tools for real task artifacts; no new universal dispatch platform",
                            "Professional timeline/sound adapter execution and independent holdouts",
                            "92 G6-scoped scenarios; 3 G7 scenarios remain separately authorized",
                            "Actual model/effort/quota/fee and professional image/video/audio holdouts"])
    gates["gates"]["G6"].pop("checks", None)
    gates["gates"]["G6"]["checks_authority"] = "outputs/p6/full-audit-report.json evaluated against current source/receipt/package"
    write_json("docs/phase-gates.json", gates)
    resource_cases = {name: state for name, state in receipt["rust"]["cases"].items()
                      if name.startswith(("resource_", "t23_", "source_change_and_knowledge", "empty_evidence_", "schema2_", "schema3_", "schema4_", "failed_known_migration", "transfer_", "transferred_", "moved_knowledge", "two_receivers_", "t51_", "t53_", "task_catalog"))}
    write_json("outputs/p5/resource-persistence-report-2026-10-04.json", {
        "schema_version": 1, "observed_at": observed, "scope": "same-project isolated local persistence",
        "passed": acceptance["evidence_valid"] and bool(resource_cases) and all(state == "passed" for state in resource_cases.values()),
        "test_cases": resource_cases, "source": "src/resources.rs", "source_sha256": digest(ROOT / "src/resources.rs"),
        "schema": "src/resource_schema.sql", "schema_sha256": digest(ROOT / "src/resource_schema.sql"),
        "workspace_schema_version": 7, "second_task_fact_database": False,
        "knowledge_and_experience_types_separate": True, "runtime_or_global_admission": False,
        "isolated_single_owner_transfer": "implemented_with_queryable_ack_and_source_readonly",
        "isolated_catalog_publication": "immutable_files_one_pointer_full_deterministic_composition",
        "catalog_bound_local_task_actions": "exact_lock_rechecked_before_claim_revision_and_write; no_hot_pointer_fallback",
        "received_origin_knowledge_resolution": "explicit_two_workspace_grant_exact_origin_and_current_target_ack",
        "received_owner_content_delta": "immutable_origin_snapshot_plus_cas_candidate_reviewed_versions_and_exact_parent_bindings",
        "general_cross_scope_content_delta_and_public_professional_admission": "not_completed"})
    experience_cases = {case: receipt["python"]["cases"].get(case, "not_run")
                        for case in [*SEMANTIC_PYTHON_CASES["T21"], *SUPPORTING_PYTHON_CASES["T22"]]}
    write_json("outputs/p5/experience-workflow-evidence.json", {
        "schema_version": 1, "observed_at": observed, "kind": "actual_isolated_cli_related_task_regression",
        "passed": acceptance["evidence_valid"] and all(state == "passed" for state in experience_cases.values()),
        "source": "tools/test_experience_workflows.py", "source_sha256": digest(ROOT / "tools/test_experience_workflows.py"),
        "test_cases": experience_cases, "execution_receipt": "outputs/p6/test-execution.json",
        "execution_receipt_sha256": digest(ROOT / "outputs/p6/test-execution.json"),
        "T21_scope": "reviewed exact local experience used by a related deterministic task; stale and self-publication denied",
        "T22_scope": "Windows single-owner SID/ACL/scope with current semantic evidence required; no DACL changes or multi-tenant service claim",
        "consumer": "bounded regression task, not autonomous model learning",
        "runtime_or_global_admission": False, "P7": False, "shutdown": False})
    remaining = [row for row in acceptance["matrix"] if row["required_for_g6"] and row["status"] != "passed"]
    write_json("outputs/p6/remaining-work.json", {
        "schema_version": 1, "observed_at": observed, "goal_complete": False,
        "core_closeout_complete": closeout["core_closeout_complete"],
        "full_capability_acceptance_complete": False,
        "goal_boundaries": "docs/goal-execution-boundaries-2026-10-05.md",
        "p7_conditionally_authorized": True,
        "shutdown_conditionally_authorized": False,
        "authorization_is_not_execution_or_gate_completion": True,
        "no_user_continue_prompt_required": True,
        "next_local_work": closeout["next_local_work"],
        "core_closeout_basis": closeout["basis"],
        "peripheral_validation": "deferred_until_a_real_task_requires_it",
        "acceptance_ledger_is_not_a_prebuild_backlog": True,
        "remaining_scenarios": remaining, "P7": False, "shutdown": False})
    text = f"""# 4.0 连续建设复查：{date}

这是4.0核心收尾检查点，不是全量专业能力完工声明。活动执行基线为v1.7；v1.6原稿与历史基线原字节保留，其他P1冻结设计不覆盖，全部95项验收保留。核心入口已装备；外围能力按真实任务需要再接入，不另造Codex平台。

## 本轮新增及修复

- 全新交付一个阿极入口与五篇按需指引；chat/rewrite只加载入口，专业任务只增加对应reference。用户级AGENTS、4.0 developer入口和4.0 Skill已有当前装备记录；不把文字指引当模型效果通过。
- 薄入口实际调用既有Rust/SQLite完成一条独立UTF-8文件任务；独立内容/hash核对、当前摘要和重复调用只一次执行已通过，输出变动后撤销完成声明。产物/回执见outputs/p2/legion-first-task-*，使用说明见docs/legion-quickstart.md；这不是模型修复或全专业链。
- 真实完成一条本地经验小闭环：基线负例回归证据→知识/经验分型候选→明确隔离复核→精确版本用于后续manifest护栏/回归→来源变化后新进程查询拒绝旧经验。回执见outputs/p5/legion-experience-task-receipt.json；未宣称自动模型进化或全局晋升。
- 经验采用已固化为真实CLI任务回归：精确复核后用于相关manifest任务，未复核/无关trigger/来源失效/自授公共权威均拒绝；跨项目私有经验和错误review许可另验。T21按实际场景入账，T22仍partial并明确缺完整用户身份/ACL；不以项目隔离替代用户权限层。
- 修复源文件变化后brief/overview仍可返回旧内容的问题；现在每次投影重核精确源hash，并如实记录额外验证字节。
- 修复CLI过期P2阶段/缺漏命令，明确隔离建设不等于G4/G6通过或完整能力发布。
- 修复包内/包外清单身份不一致、重复ZIP项、Windows路径、缺失文件及解压预算问题；增加完整源码闭包，不夹带.dev、运行DB或凭据。
- 真实执行账同时核对Rust/Python实际逐项日志、退出码和源码hash；T52/T53/T64按完整确定性正反例入账，T53还要求真实进程中断、实际领取/写入及非撤回版恢复，不据组件mock通过。
- 修复新增来源记录后的P2/P3过时来源hash；P2准备角色当前revision为{prepared_revisions}，完整revision2字节与来源刷新回执保留，ExactRef不再固定revision1。历史原生证据不冒充新字节实测。
- 修复两项旧baseline测试替换失效接口的问题，真实临时ROOT继续检查计划变化、未授权版本、越界和缺失路径；没有放宽活动基线或P7保护。
- 修复薄入口动作成功后至摘要前的产物变化竞态：当前incomplete不再配固定“完成”文字，completed与当前摘要绑定；真实变动产物回归核对只一次invocation且不自动覆盖。原文件任务按当前入口重核通过，不重写历史回执。
- 4.0项目内框架外壳已可用：`tools/wuji4.py`提供status/doctor/route/run-copy/summary，真实doctor通过并以新隔离工作区完成一条文件任务；它是项目内辅助工具，不是常驻调度器，报告见outputs/p2/framework-doctor-current.json。
- 框架同时提供只读`capabilities`视图，显示现有专业适配器的真实入口、边界和效果声明；不提供任意工具派发，不把工具目录当成已验证专家。
- OfficeCLI文本PPTX链已接入`run-office`并在新隔离工作区真实完成create/add/get/set/view/close；回执绑定原生退出、OOXML、产物hash与配置保护，专业设计质量仍未声明。
- OfficeCLI文档链已接入`run-office-doc`并在新隔离工作区真实完成有界XLSX公式/缓存值/OfficeCLI回读；DOCX结构、文字和OfficeCLI回读通过，但批准渲染器缺失，保留`render_unavailable`失败证据，不冒充Word完成或专业效果。
- ComfyUI/ffmpeg链已接入`run-media`并真实执行到Rust/SQLite输入注册；本轮当前ComfyUI端口拒绝连接，回执为failed_real_error且入口返回非零，不自动启动服务或冒充专业媒体完成。
- 独立`run-video`在新工作区真实完成PNG→一秒八帧无音频MP4→另一进程解码，绑定现有工具、输入/输出、源码和配置hash；不调用ComfyUI、不自动fallback，不把编码任务扩称专业剪辑。证据见outputs/p4/video-framework-workflow-evidence.json和对应MP4。
- 修复Office失败回执只有state、框架却退出零的问题；失败现在保留JSON并退出非零。回执不得越界、预存文件不覆盖；完整大输出留存并失败，配置不可读/变动不成功。模拟配置失败没有写入真实配置。
- 按FFmpeg官方image2原始文档采用pattern_type=none，避免单文件名中的模式字符读成其他序列；原始快照与阅读范围登记在同一来源账，不把公开依据算成本机执行。
- 回归重写日志时错误核验旧归档源码闭包的循环已修复；回归核上一归档身份，正式本次闭包仍在封包后总审计严格重核，旧失败账保留。
- 纠正T24/T85只凭hash/报告断言即判完整通过的口径；T24现已由当前Rust正反例、来源哈希和隔离证据完成确定性本地场景，T85仍partial，缺全范围工具发现与当前schema实际派发漂移拒绝，不为提高通过数削弱场景。
- 用户明确撤销3.0运行挂载并要求4.0全局入口；当前切换记录见outputs/p7/global-4-only-cutover-2026-10-05.json。P7全量能力发布与关机均未执行，且本轮不把它们排为继续扩建理由。
- 独立短视频的实际派发前新增精确server/tool/本机二进制/接口schema/源码复核绑定，复用现有工具manifest而不建第二目录；身份、schema（含bool/int区别）、同名重复或源码变化均在工具执行前拒绝，执行期间manifest变化撤销完成。该有界工具缺口已补，不因此宣称全部MCP/API工具发现和T85全范围通过。
- 修复并行测试夹具仅用进程ID/纳秒时间导致的同钟目录复用；七次初始化只生成六个根目录并发生os error 183，失败账/日志保留。仅夹具增加原子序号与独占创建，相同固定时刻32线程回归核对，不改业务语义或串行化全套测试掩盖失败。
- P3冷目录质量报告补齐当前生成器/来源/产物8项hash，总审计不再只信旧通过布尔值；来源变更、缺失与越界路径回归均覆盖。
- 修复终审报告被旧manifest打进自身归档后再更新导致闭包过时的循环；终审作为真实包外attestation，保留项目报告并拒绝重新夹带，不通过反复重打包掩盖问题。
- 完成同一工作区SQLite内知识/经验分型持久化、CAS、幂等、撤销、当前来源复核、过期及scope检查；本地审查仍限独立.dev工作区，不能自升全局。
- 已知schema2/3/4明确init才事务迁移至5；观察型打开/未知库不自动迁移，故障连新增列/表全部回滚。
- 完成隔离catalog不可变文件/manifest、单活动指针CAS、精确release lock、安全撤销、完整消费者组合校验及36项影响闭包分页/损坏修复。
- 目录绑定接通实际本地program任务领取/写入/图修订；旧任务固定版本、撤回拒绝新动作、缺失绑定不能退回无锁；原生派发护栏未在当前真实模型条件下重验。
- 完成双隔离scope单写移交：源冻结→目标幂等写/可查询ACK→源shared_ref；目标退役不使源复活。原文快照仍保留origin_scope，不洗白成目标或全局事实。
- 补齐目标内容delta：schema6不可变版本链、expected_revision/CAS、候选到独立复核、精确父引用、受保护来源字段和merge边界；同一授权目标内的知识改版依赖不跟随latest，未ACK/错目标/目标退役/篡改/源变动均拒绝。跨域发布和全局晋升仍未完成。
- 接通有理数TimeQuantity→TimeBase→Rate精确引用与四种舍入、实际PCM音乐前置到Shot的有界准备链、共享窄专家/独立写集的任务配方和真实DB执行摘要；prepared始终不是已启动/已验收。
- 修复媒体比较溢出吞错、ID/revision不能绑定父内容、首尾相接retiming误拒与clip对应缺口；新增作用域/完整payload投影指纹和连续全span检查。frame profile仅是明确支持率声明，stem/render只证明真实PCM格式；媒体最小下游依赖闭包、bus/automation语义、专业编辑器与成片效果仍未实现，不再输出假重验布尔值。
- T05/T06/T83增加真实CLI冷目录选择/歧义缩小/分层或直达原文闭环与实际字节/往返计量；T11/T12/T13/T18补全局部返工、重复事件、真实OS中断查询隔离与新revision独立重验场景，不以组件名字代替完整场景。
- 增加完整证据分页回读与隔离预算配置声明分层：不截坏JSON，不删错误/权限，不把configured当effective，不推导未知窗口5440或费用限额；当前真实宿主预算观察仍unknown。专业流程未实现项改为内部not_run，不全部包装成外部阻断。
- 修正预算数字语义：4096是单项工具摘要预算，240000/90000是压缩与Skill投影策略值；gpt-6.1-sol官方规格为1050000上下文、128000最大输出，超过272K输入是计费分界，不是上下文上限。官方规格不替代当前Codex宿主的effective观察；T70/T71活动映射和生成器均已同步。
- 复查发现Windows verbatim拼接可消掉原始“..”，已按Rust原始说明在拼接前检查raw target并增加回归；本地产品验证不是重复语言选型实验。
- 找到已安装的OfficeCLI 1.0.152，与原始发布SHA256精确相符；禁用自安装、自更新、自动resident后，真实创建/编辑原生可编辑PPTX、get/HTML/OOXML及close通过。没有下载或安装，没有改PATH/全局Skill。
- 已启动两个固定gpt-6.1-sol/high的隔离CLI工作者；遇429后两个进程均退出，不换模，不在终止后盲重试。有效后台模型/档位仍unknown。
- 本轮两个独立写集开发子代理完成并已提交成功关闭请求；工具显式xhigh参数被拒后保留继承设置，不切模型或改配置，实际模型/档位及原生后台退出仍unknown，不据此宣称档位或G2准入已验证。记录见outputs/p6/continuation-2026-10-04/local-parallel-repair-report.json。

## 实际验收

Rust：{receipt['rust']['tests_passed']}项通过；Python：{receipt['python']['tests_run']}项，passed={receipt['python']['passed']}。

95项冻结场景全部保留：{json.dumps(counts, ensure_ascii=False)}。其中92项属于G6，T43/T44/T74属于需另批的新会话G7，不混作G6阻断，也不删除。当前G6正式通过{summary['passed_for_g6']}项，其余仍须建设/取证。

G4仍未通过：REAPER/音频专业链、专业图像/视频/音频holdout等未完成。Office证据仍是有界工作流，不证明所有Word/Excel/专业设计效果；这些不在本轮外围预检范围。

## 保护与后续

当前配置本轮前后hash相同；与10月3日历史hash不同的变化发生于本轮前，操作者unknown。本轮不还原、不写入现用配置；不付费、不发布。P7全量能力发布和关机均未执行，本轮也不安排关机；不提前挂载、不使用强制关闭或正数倒计时。

完整能力账仍有专业任务链、跨域发布/全局晋升、专业时间线/分轨适配器、独立holdout及部分G6场景未完成；这不改变4.0核心入口已可用。它们只在真实任务需要时按需复用现有工具并做必要检查，不预建适配器，不要求用户反复发“继续”。权威执行账是outputs/p6/acceptance-execution.json；总报告重新计算，不复用旧的全通过布尔值。
"""
    text = text.replace("OfficeCLI\u4ec5\u8bc1\u660e\u6709\u754c\u6587\u672cPPTX\u52a8\u4f5c\uff0c\u4e0d\u8bc1\u660e\u6240\u6709Word/Excel/\u4e13\u4e1a\u8bbe\u8ba1\u6548\u679c\u3002", "\u5f53\u524dOffice\u8bc1\u636e\u8986\u76d6\u6709\u754c\u6587\u672cPPTX\u3001XLSX\u516c\u5f0f/\u56de\u8bfb\u548cDOCX\u7ed3\u6784/\u56de\u8bfb\uff1bDOCX\u6279\u51c6\u6e32\u67d3\u53d7\u5916\u90e8\u73af\u5883\u963b\u65ad\uff0c\u4e13\u4e1a\u6587\u6863/\u8bbe\u8ba1\u6548\u679c\u4ecd\u672a\u58f0\u660e\u3002")
    (ROOT / "docs/continuation-report-2026-10-04.md").write_text(text, encoding="utf-8")
    readme = ROOT / "README.md"
    current = readme.read_text(encoding="utf-8")
    paragraphs = current.splitlines()
    core_summary = "本轮核心收尾条件已满足" if closeout["core_closeout_complete"] else "本轮核心收尾仍有具体缺口，继续执行"
    paragraphs = [f"当前阶段：4.0核心入口状态见当前部署观察；{core_summary}；Rust {receipt['rust']['tests_passed']}项、Python {receipt['python']['tests_run']}项回归通过（跳过{receipt['python'].get('skipped', 0)}项）。全量验收仍为{summary['passed_for_g6']}/92项G6通过，另3项G7保留；MCP及专业应用不预检，真实任务需要时再接入。最新复查见 docs/continuation-report-2026-10-04.md。" if line.startswith("当前阶段：") else line for line in paragraphs]
    paragraphs = [line.replace("OfficeCLI\u6587\u672cPPTX\u4e0e\u72ec\u7acbffmpeg\u77ed\u89c6\u9891\u5df2\u6709\u6709\u754c\u5b9e\u9645\u8bc1\u636e", "OfficeCLI\u6587\u672cPPTX\u3001XLSX\u6709\u754c\u94fe\u548c\u72ec\u7acbffmpeg\u77ed\u89c6\u9891\u5df2\u6709\u5b9e\u9645\u8bc1\u636e") for line in paragraphs]
    readme.write_text("\n".join(paragraphs) + "\n", encoding="utf-8")
    progress = ROOT / "docs/progress.md"
    note = f"\n## {date} 核心收尾检查点\n\n4.0核心入口已装备，3.0运行挂载已撤销；本轮Rust {receipt['rust']['tests_passed']}、Python {receipt['python']['tests_run']}（跳过{receipt['python'].get('skipped', 0)}）回归通过，G6 {summary['passed_for_g6']}/92，另3项G7保留。MCP和专业应用按真实任务延后，不预检、不扩建；本轮未修改Codex保护配置，不关机。\n"
    current_progress = progress.read_text(encoding="utf-8")
    heading = f"\n## {date} 连续建设检查点"
    if heading in current_progress:
        current_progress = current_progress[:current_progress.index(heading)]
    progress.write_text(current_progress.rstrip() + "\n" + note, encoding="utf-8")
    print(json.dumps({"summary": summary, "current_report": "docs/continuation-report-2026-10-04.md", **closeout, "full_capability_complete": False}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh current scoped status without rewriting the frozen acceptance ledger")
    parser.add_argument("--current-core", action="store_true")
    options = parser.parse_args()
    if options.current_core:
        report = refresh_current_remaining()
        print(json.dumps({"core_closeout_complete": report["core_closeout_complete"],
                          "next_local_work": report["next_local_work"],
                          "full_capability_acceptance_complete": False}, ensure_ascii=False))
    else:
        main()
