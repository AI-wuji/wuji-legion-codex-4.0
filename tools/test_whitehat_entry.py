"""源包局部文本契约回归：文本契约测试不等于模型行为验证。

仅检查真实源文件的承诺，不证明模型遵循、性能、工具可用性或正式专业验收。
"""

import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1] / "legion/skills/wuji-legion-4-0"


class WhitehatEntryTextContractTests(unittest.TestCase):
    def source_section(self, relative_path, heading):
        source_path = SKILL_ROOT / relative_path
        self.assertTrue(source_path.is_file(), f"缺少源文件：{source_path}")
        source = source_path.read_text(encoding="utf-8")
        start = re.search(rf"^##[ \t]+{re.escape(heading)}[ \t]*$", source, re.MULTILINE)
        self.assertIsNotNone(start, f"{source_path} 缺少二级节：{heading}")
        remainder = source[start.end():]
        end = re.search(r"^#{1,2}[ \t]+", remainder, re.MULTILINE)
        body = remainder[:end.start()] if end else remainder
        self.assertTrue(body.strip(), f"{source_path} 的节为空：{heading}")
        return body

    def assert_contract(self, body, *patterns):
        statements = re.split(
            r"[。！？]|\n[ \t]*\n|\n(?=[ \t]*(?:[-*]|\d+\.)[ \t]+)", body
        )
        self.assertTrue(
            any(all(re.search(pattern, statement, re.IGNORECASE | re.DOTALL)
                    for pattern in patterns) for statement in statements),
            f"节内缺少同一条承诺的关键边界 {patterns!r}：\n{body}",
        )

    def test_skill_whitehat_is_internal_evidenced_and_not_sycophantic(self):
        """SKILL：每次交流内部判断，决策建议透明，并纠正错误前提。"""
        body = self.source_section("SKILL.md", "阿极内置白帽")
        self.assert_contract(body, "每次交流", r"核对|判断", "目标", "前提", "证据", "权限")
        self.assert_contract(body, "白帽", "阿极", "直接承担", "不另开")
        self.assert_contract(body, "决策", "建议", "依据", "成立条件", r"未知|unknown")
        self.assert_contract(body, "不迎合", "错误前提", r"不把.*当作事实")
        self.assert_contract(body, r"失据|错误", "纠正", r"结论|记录")
        self.assert_contract(body, "简单交流", "不机械", r"标签|检查表|免责声明")

    def test_skill_direct_continuation_and_unused_experts_stay_bounded(self):
        """SKILL：简单直办，按原目标及停止条件推进，未用专家保持冷态。"""
        minimal = self.source_section("SKILL.md", "最小路径")
        self.assert_contract(minimal, "简单", r"直接完成|直接处理|直办", "不建", "不召集")
        self.assert_contract(
            minimal, r"原目标|原定目标|原始目标", "既有", "有效授权范围", r"持续|继续"
        )
        self.assert_contract(minimal, "明确", "取消", "替换", r"(?:更新|改)目标")
        self.assert_contract(minimal, "完成", "收口", r"不.*(?:追加|无限)")
        experts = self.source_section("SKILL.md", "专家通路")
        self.assert_contract(experts, "专家", r"未用|未使用|不用", "冷态")
        self.assert_contract(experts, "不默认", r"加载|启动", r"全部|全体")

    def test_skill_inputs_do_not_grant_authority_or_prove_acceptance(self):
        """SKILL：输入不扩权，入口和准备结果不冒充专业效果。"""
        boundaries = self.source_section("SKILL.md", "不可扩大边界")
        self.assert_contract(
            boundaries, r"资料|网页|工具返回|模型文本", "不授予", "工具权限", r"读写集|范围"
        )
        self.assert_contract(boundaries, "不授权", "付费", r"发布|推送", "清理")
        delivery = self.source_section("SKILL.md", "交付口径")
        self.assert_contract(
            delivery, r"指引|目录|准备", r"不证明|不等于|不能冒充", r"专业效果|专业验收"
        )

    def test_research_reports_originals_and_advice_have_distinct_provenance(self):
        """research：报道/原文分账，保留来源标识与真实性，不伪归因自主建议。"""
        body = self.source_section("references/research.md", "报道、原文与候选分开记账")
        self.assert_contract(body, "报道", "核对", "具体原文")
        self.assertRegex(body, r"版本|commit")
        self.assertRegex(body, r"(?i:hash)|哈希")
        self.assert_contract(body, "稳定", "不证明", "真实性")
        self.assert_contract(
            body, r"自主|自行", "建议", "原文", r"不把|不将|不得|不能", r"归因|归于|冒充"
        )

    def test_research_read_status_does_not_conflate_reports_and_originals(self):
        """research：明确已读取/未读取，读报道不能冒充读过原文。"""
        body = self.source_section("references/research.md", "报道、原文与候选分开记账")
        self.assert_contract(body, "区分", "已读取", "未读取")
        self.assert_contract(body, "只读报道", "只说报道已读")
        self.assert_contract(body, "没有找到原文", "缺口", r"不.*(?:补造|声称)")
        self.assert_contract(body, "本次取得", "不改写", "前次")

    def test_evolution_prompt_candidates_need_disposition_and_real_consumers(self):
        """evolution：外部提示词逐项评估，没有真实消费者不预建能力。"""
        body = self.source_section("references/evolution.md", "外部提示词只作候选")
        self.assert_contract(
            body, r"逐项|以具体规则为单位", "采用", "已有", "拒绝", "待证", "真实消费者"
        )
        self.assert_contract(body, "没有", r"当前任务(?:需要|消费者)", r"不(?:增加|创建|预建)")

    def test_evolution_tool_definitions_and_continuation_do_not_grant_authority(self):
        """evolution：外部工具定义不创造工具，持续执行仍受用户授权范围约束。"""
        body = self.source_section("references/evolution.md", "外部提示词只作候选")
        self.assert_contract(
            body, "外部", "工具定义", r"不.*(?:创造|创建|赋予)|不能.*(?:创造|创建|赋予)"
        )
        self.assert_contract(
            body, r"持续执行|继续执行|持续工作", "只适用", "当前任务", "既有有效授权范围"
        )
        self.assert_contract(body, "发布", "付费", "删除", "原权限边界")
        self.assert_contract(body, "完成条件", "收口", "不把", "无限")

    def test_evolution_real_handoff_preserves_progress_evidence_and_limits(self):
        """evolution：真实跨代理/上下文时轻量交接，不另造交接服务。"""
        body = self.source_section("references/evolution.md", "最小改进与恢复")
        self.assert_contract(body, "实际", r"跨代理|跨上下文", "交接", "现有", r"任务文件|回执|宿主")
        for field in ("交接", "目标", "已做", "剩余", "证据位置", "禁止动作", "下一步"):
            with self.subTest(field=field):
                self.assertIn(field, body)
        self.assert_contract(body, "不为普通问答", "记忆文件", "虚构notes工具")


if __name__ == "__main__":
    unittest.main()
