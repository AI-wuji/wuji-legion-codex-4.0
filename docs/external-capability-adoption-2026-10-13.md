# 外部能力选择性融合记录：2026-10-13

## 结论

本轮将用户提供的 GitHub 项目、补充项目和文章中的能力统一作为候选输入，采用“方法提炼优先、运行时按需、许可证与宿主分开”的方式处理。

本轮不把任何外部仓库的完整 Agent、插件、运行壳或第二状态库搬入 4.0。实际融合分为四层：

1. **已纳入 4.0 共用行为契约**：`i-have-adhd` 的先结论/下一步输出纪律；PonyTail 的最小正确路径继续保留。
2. **纳入设计方法，但不安装运行时**：ECC 的工程闭环、Context Mode 的数据先在代码侧处理、HumanLayer 的展示/复核方法、文章中的 Any Search 与仓颉式内容蒸馏。
3. **登记为按需能力候选**：Archify、Agent-Reach、Taste Skill、HyperFrames、文章中的 chatcut。
4. **当前拒绝进入 4.0 核心**：God's Eye View、OpenAI Skills 全量目录、OpenAI Plugins 全量插件、文章中的 Computer Use 运行壳。

来源热度、周涨星和文章排名只作为发现线索，不作为本项目的专业效果、稳定性、免费性或安全性证据。

## 项目和能力处置

| 候选 | 当前处置 | 4.0 落点 | 主要边界 |
|---|---|---|---|
| `ayghri/i-have-adhd` | `distill-to-atom` | 阿极输出契约：先结论、编号步骤、给出下一步 | 不能压缩研究报告、验收报告或用户明确要求的长文 |
| `bilawalsidhu/gods-eye-view` | `reject` | 暂无当前消费者；保留为可视化参考 | 独立浏览器应用，不是 4.0 Skill；许可证信息未形成准入依据 |
| `tt-a1i/archify` | `candidate-skill` | `software-architecture` 的架构图和源码回指产物 | DSH 社区适配器绑定特定宿主版本，必须单独做隔离 profile 验证 |
| `DietrichGebert/ponytail` | `already-adopted` | 4.0 最小正确路径、复用优先、按需升级 | 不重复安装、不创建第二份全局规则 |
| `affaan-m/ECC` | `distill-to-atom` | 计划→测试→实现→复核→验证→记忆的工程闭环 | 不导入 71 Agent、311 Skill 或付费 ECC Pro |
| `heygen-com/hyperframes` | `candidate-skill` | 视频领域的 HTML composition、渲染和回执 | Chrome、FFmpeg、Git LFS 和渲染链需真实任务触发后再验收 |
| `mksglu/context-mode` | `benchmark-first` | 大输出、索引、代码侧聚合和上下文预算方法 | 与 DSH 原生压缩/T20 有重叠；ELv2 许可证与 MCP/hooks 需单独审查 |
| `openai/skills` | `historical-reference` | 只参考 Skill 组织方式 | 官方仓库已标记 deprecated，不能作为当前准入目录 |
| `humanlayer/skills` | `distill-to-atom` | `show-me`、视觉复核、RPI 的局部方法 | RPI 不能取代阿极→参谋部→主帅→专家链路 |
| `openai/plugins` | `format-reference` | 只参考 plugin manifest、Skill、MCP、command 的组合 | Codex 插件宿主格式，不能直接挂入 DSH |
| `Panniantong/Agent-Reach` | `candidate-adapter` | `research` 的按需外部来源入口 | Python、外部后端、Cookie、平台限制；默认不启用登录态 |
| `Leonxlnx/taste-skill` | `candidate-profile` | `web`、`image`、`presentation` 的视觉 Profile | 默认 v2 为 experimental，固定 commit；不做全局视觉硬律 |
| 文章：Computer Use | `boundary-only` | 复用已有浏览器、文件和宿主授权边界 | 不新增任意桌面控制运行壳，不把能操作电脑写成当前 4.0 已具备 |
| 文章：chatcut | `distill-to-atom` | 视频粗剪、去停顿、字幕、包装、导出验收方法 | 不接入商业剪辑插件，不承诺自动一键成片 |
| 文章：Any Search | `distill-to-atom` | 研究任务的来源分层、定向检索、原文回读 | 与现有 web 能力及 Agent-Reach 重叠，不新增第二搜索宿主 |
| 文章：仓颉 Skill | `distill-to-atom` | 资料蒸馏：核心逻辑、方法、判断标准、适用边界、底层依据 | 不建立第二记忆库，不把摘要当原文，不把文章宣传当蒸馏效果证明 |

## 已融合的行为变化

### 输出纪律

阿极在简单任务中应遵循：

1. 先说结论或当前状态；
2. 再列已经完成的动作；
3. 需要用户操作时只给下一步；
4. 复杂任务再展开证据、假设、风险和未完成项；
5. 不用没有信息量的礼貌性收尾。

该规则不覆盖长文、研究报告、验收报告或用户明确要求的完整解释。输出长度服从用户决策负担和交付证据，而不是固定追求短。

### 工程闭环

复杂软件任务按需要采用以下闭环：

```text
目标与边界
  → 最小方案
  → 实现或委派
  → 独立复核
  → 定向测试/验证
  → 交付与路径回执
  → 只记录真实有效的可复用经验
```

“独立复核”不能由执行者自己的总结单独证明；“记录经验”不自动等于把经验晋升成全局规则。

### 研究来源回执

由 Any Search、Agent-Reach 或现有 web 能力取得的外部资料，进入 4.0 研究产物时至少保留：

```text
source_url
source_platform
retrieved_at
backend_or_tool
authentication_state
source_version_or_commit
quoted_or_extracted_range
facts
inferences
unknowns
```

抓取成功不等于原文已读，搜索摘要不等于全文证据，渠道可访问不等于长期稳定。

### 资料蒸馏

仓颉式蒸馏只作为研究和学习任务的输出结构：

```text
内容主题
核心逻辑
可执行方法
判断标准
适用条件
失败条件/反例
与当前任务的关系
待回读原文
```

必须保留原始资料路径或 URL。摘要不能替代下游需要直接读取的原文，也不能把来源作者的宣传结论升级成 4.0 的经验。

## 按需候选的接入条件

候选能力必须同时满足以下条件，才可以从“登记”进入“本机采用”：

- 有明确的当前任务消费者；
- 能说明输入、输出、权限、失败和回滚边界；
- 记录来源仓库、版本/commit 和许可证；
- 不重复已有宿主能力或第二状态权威；
- 有静态加载检查和一次真实任务验证；
- 有独立复核或真实产物回读证据；
- 未验证部分保留为 `unknown`，不写成已生效。

本文件只记录候选和方法融合，不声明 Archify、Agent-Reach、Taste Skill、HyperFrames 或文章插件已经安装或在当前宿主中可运行。

## 来源锁与文章身份边界

12 个 GitHub 项目的仓库身份、锁定 commit、已读文件、许可证、网络失败和 `runtime_verification=not_run` 统一记录在 [外部能力来源锁](external-capability-sources-2026-10-13.json)。该 JSON 是来源证据账，不是运行时配置，也不代表这些仓库已安装。

文章正文实际出现四个名称：`Computer Use`、`chatcut`、`Any Search`、`仓颉 Skill`。目前只有 `chatcut` 能在锁定的 `openai/plugins` 树中确认到明确目录；其余三个保留为文章中的能力名，未确认到唯一官方仓库身份。因此文章部分只融合方法和权限边界，不做安装或运行时绑定。
## 外部来源

- `ayghri/i-have-adhd`：MIT，输出纪律 Skill。
- `bilawalsidhu/gods-eye-view`：真实公开数据的浏览器态势可视化应用；许可证未形成当前准入依据。
- `tt-a1i/archify`：MIT，交互式架构图和源码回指；其 DSH 适配器有独立宿主版本契约。
- `DietrichGebert/ponytail`：MIT，已在 4.0 规则和 DSH persona 中采用。
- `affaan-m/ECC`：MIT，工程闭环和多宿主技能集合；付费托管能力不采用。
- `heygen-com/hyperframes`：Apache-2.0，HTML 原生视频渲染路线。
- `mksglu/context-mode`：README 标注 ELv2，MCP/hooks/SQLite 索引和上下文削减路线。
- `openai/skills`：官方 README 已标记 deprecated，并指向 `openai/plugins`。
- `humanlayer/skills`：MIT，RPI、show-me、visual-pr 等技能。
- `openai/plugins`：Codex 插件示例集合，不是 DSH 插件。
- `Panniantong/Agent-Reach`：MIT，Python 3.10+，多平台来源接入和诊断。
- `Leonxlnx/taste-skill`：MIT，默认 `design-taste-frontend` v2 为 experimental。
- 今日头条文章：`Codex真正实力曝光！4大核心插件，解锁AI全能生产力`，2026-09-30。正文实际列出 Computer Use、chatcut、Any Search、仓颉 Skill。文章是候选发现来源，未作为这些能力的专业效果证明。



## 本轮进一步固化的全局行为

## 从方法融合到执行契约

本轮融合的最短路径、输出纪律、工程闭环和资料蒸馏已经接入 4.0 核心 Skill 与任务路由；它们不再只保留为来源笔记。复杂任务的专家团现在生成局部任务、上游输入门、输出契约和依赖并发计划；输入不合格返回上游重做，团队成员只看到自己的任务和已验收的上游产物。


用户明确要求将最短最小任务链落实到所有角色、工具、输出和内部推理：无 Skill/MCP/专家需求，或只需一个专家且不要求组团时由阿极直办；复杂任务才经过参谋部→主帅分身→必要专家分身。白帽与阿极绑定，负责第三方客观判断，既不迎合也不只反驳。
