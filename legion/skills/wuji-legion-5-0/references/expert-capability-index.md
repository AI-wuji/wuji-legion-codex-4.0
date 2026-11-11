# 5.0专家能力索引（按需解析）

本索引把现有P3专家职责接到当前可发现的Skills。首选专家执行桥是当前 Codex 会话实际提供的原生子代理能力；专家按需MoE冷态，启动状态以真实工具回执为准。Skill目标文件按实际安装路径解析，调用前遵循该Skill自身说明。MCP/CLI/API不在本索引中猜测：只有当前会话明确提供并授权时才绑定。项目目录中的角色定义不等于全局已安装或当前分身已启动。

## MoE角色生命周期（所有角色统一）

阿极本身是轻量常驻协调入口；其余角色定义均冷态保存，只有匹配当前子任务时才启动对应的一次性分身；任务需要单一专家时可直接启用一个，不必先扩成复杂团队。这里的MoE是运行路由/激活策略，不代表特定神经网络模型内部的MoE结构。

生命周期：`cold → active(task_instance) → suspended(checkpoint, if host supports) → active(resume)`；任务完成、取消或不可继续时转`closed`并释放会话/并发槽。角色定义和能力引用可以保留，模型上下文与活跃实例不常驻。无原生暂停时以最小checkpoint结束旧实例，后续新实例按宿主机制恢复，不假称原进程仍挂起。

该规则适用于工作流/主帅角色、参谋职责、专家和方法角色；配方只是检索知识，不能因命中配方而自动调用主帅代理。未使用角色保持冷态，不读取其完整指令、不给它们传任务、不占调用与宿主槽位。

## 通用派发约定

本索引按5.0直派专家解释能力映射。历史4.0及更早Skill不作为可加载运行能力。专业知识如有必要，由阿极在任务契约中提炼，不调用其旧路由、角色链或流程。

- 角色身份取自P3专家ID；以下映射提供专业边界，目标Skill提供方法和工具流程。两者互补，不将Skill名称当作执行结果。
- 一个专家角色可为互斥来源/对象范围开多个分身并行；分身共享角色能力，各自限定读写范围并简短回执。只有独立方法边界明显不同时才选不同角色。
- 对用户或专家只传当前任务、必须上下文、范围/权限、产物与阻塞；不传冗长思考过程。
- 没有对应Skill时先用P3职责和当前宿主原生工具；不因此阻塞不依赖它的分支，也不自动安装。

## 26个按需专家

正式专家集以 `catalog/p3/expert-roster-5.0.json` 为准；每位专家的用户可见中文功能名见 `display_name_zh`，角色定义和可用范围见本目录 `experts/`。面向用户展示或介绍专家时必须使用中文功能名，内部英文 ID 只用于路由和代码引用，不能单独作为展示名称。表内 P3 ID 是被合并的设计来源，不是额外可派发的角色。阿极按任务启用一个或多个互不冲突的专家实例，并把完整角色卡、当前目标、范围和验收条件放入原生子代理任务。

| 中文功能名（内部ID） | 合并职责来源 | 可派发能力 |
|---|---|---|
| 软件架构设计专家 (`wuji-architect`) | `software-architecture`、`ai-workflow-engineer` | 只读架构、边界与接口方案 |
| 自动化与工作台专家 (`wuji-automation`) | `automation-design`、`workbench-builder` | 本地自动化与工作台实现 |
| 音视频制作专家 (`wuji-av-producer`) | `image-creation`、`video-production`、`post-production`、`voice-audio` | 图像与视听制作；按媒介任务限定范围 |
| 商务方案与资料专家 (`wuji-business`) | `requirement-decomposition`、`studio-owner`、`business-library`、`client-proposal`、`delivery-acceptance` | 商务需求、定位、方案、资料和交付接收 |
| 代码审查专家 (`wuji-code-reviewer`) | `code-review`、`evolution-review` | 独立代码审阅与能力演进审查 |
| ComfyUI 工作流与节点专家 (`wuji-comfyui`) | 全部 `comfyui-*` 职责 | ComfyUI 分析、工作流、节点、性能、打包和验证；原生扩展须另证接口与实现能力 |
| 合同风险审查专家 (`wuji-contract-reviewer`) | `contract-risk` | 合同条款风险审查 |
| 课程与学习设计专家 (`wuji-course`) | `course-design`、`learning-coach`、`template-curator` | 课程、陪练与学习模板 |
| 数据分析专家 (`wuji-data-analyst`) | `data-analysis`、`dashboard-review` | 数据分析与看板审查 |
| 故障诊断专家 (`wuji-diagnostician`) | `incident-diagnosis`、`comfyui-debug-performance` | 只读故障诊断与性能证据分析 |
| 文档与办公文件处理专家 (`wuji-document`) | `document-deck`、商务资料中的文件制作 | Word/PDF/表格/演示文档处理 |
| 软件工程实现专家 (`wuji-engineer`) | `code-repair`、`code-implementation`、Python/Rust/Go/C++工程叶子、`ai-workflow-engineer`、`workbench-builder` | 软件实现、缺陷修复与语言/API专项 |
| 代码与系统探查专家 (`wuji-explorer`) | `software-architecture`、`software-reverse` 的只读探查面 | 入口、调用链、数据流和副作用取证 |
| 文件整理专家 (`wuji-file-operator`) | `file-operations` | 有界文件归类、映射与可恢复操作 |
| 影视策划与分镜专家 (`wuji-film-planner`) | `screenwriter`、`visual-storyboard`、`art-director`、`comic-storyboard`、`video-copywriter`、`studio-producer` | 剧本、分镜、美术和影视生产计划 |
| 影视拉片与二创专家 (`wuji-film-analysis-adaptation`) | `screenwriter`、`visual-storyboard`、`video-copywriter` | 影片拉片与证据化逐镜分析；基于影片改编/二创；也可独立原创；按需调用 `directors-eye` 和 `omni-script-director` |
| 前端界面与视觉设计专家 (`wuji-frontend-visual`) | `frontend-visual`、工作台界面部分 | 前端实现、视觉与可用性审查 |
| 音视频与媒体质量审查专家 (`wuji-media-reviewer`) | `media-quality-review` | 独立媒体质量与集成审查 |
| 动效制作专家 (`wuji-motion-graphics`) | `motion-graphics` | 当前仅限已记录的动效工具链和格式范围 |
| 内容发布与渠道交付专家 (`wuji-publisher`) | `publication-delivery`、`content-operations` 的发布动作 | 精确授权下发布并回读状态 |
| 调研与资料核查专家 (`wuji-researcher`) | `research`、`knowledge-base-qa` | 有来源边界的调研与资料问答 |
| 软件逆向分析专家 (`wuji-reverse`) | `software-reverse`、授权静态分析 | 授权目标的只读行为重建 |
| Skill 设计与打包专家 (`wuji-skill-packager`) | `skill-packager`、演进审查中的打包面 | 项目内Skill与插件整理、许可和验证 |
| 软件测试与交付验证专家 (`wuji-tester`) | 修复/ComfyUI/交付验收中的独立验证面 | 测试编写与独立验收，不实现被测源码 |
| 安全威胁建模专家 (`wuji-threat-modeler`) | 架构/审阅/API集成中的威胁建模面 | 授权系统的只读 STRIDE 威胁建模 |
| 内容写作与平台改写专家 (`wuji-writer`) | `writing`、`multi-platform-distribution`、`topic-selection`、`screenwriter`、`video-copywriter`、内容运营建议 | 内容写作、选题与渠道改写；不代发布 |

同一P3来源可为不同消费者提供互补能力；它不会因此恢复成旧的独立派发角色。实际任务选择只使用26个 `p5/expert/*` 身份。没有列出的工具、格式、平台权限或专业验收均不由角色名称推定。

### 影视拉片与二创路由

- 用户要求拉片、镜头分析、导演手法或影片二创时，启用「影视拉片与二创专家」并按任务加载 `directors-eye`；用户要求基于影片二创时，先产出有来源、时间码和复核状态的拉片分析，再加载 `omni-script-director` 改写剧本。
- 用户要求分镜时，待剧本定稿后再按 `omni-script-director` 的分镜契约处理；普通拉片不强制产生剧本或分镜。
- 从零原创或只改写文字剧本，默认路由现有「影视策划与分镜专家」；用户明确指定影视拉片与二创专家时例外。
- 两个 Skill 已在当前 Codex 环境提供时按需调用；当前会话仍须确认实际发现及依赖。没有真实观片/听音证据时保留 `unknown`，不把自动切点、帧差、字幕或 ASR 当成人工复核。

`wuji-reverse` 的中文功能名为**软件逆向分析专家**。需要专用分析能力时，按需加载仓库级 `.agents/skills/software-reverse-analysis/SKILL.md`；附带工具只归该专家按任务使用，不作为全局常驻能力。该 Skill 当前包含离线 v8asm `.jsc` 分析器，版本 profile 和解析门槛以 Skill 文档为准；其他格式使用当前会话已有的本地工具，不自动下载或安装依赖。

## 飞书能力按意图加载

不要把全部飞书Skills塞给一个常驻专家。由阿极按对象路由单个窄Skill：文档`lark-doc`；云盘`lark-drive`；表格`lark-sheets`；Base`lark-base`；幻灯片`lark-slides`；即时消息`lark-im`；邮件`lark-mail`；日历`lark-calendar`；任务`lark-task`；审批`lark-approval`；知识库结构`lark-wiki`；认证/权限`lark-shared`。这些是现成Skill引用，不保证本次会话的账户授权或对应底层API已连接。

## 执行桥与边界

Codex当前会话实际提供的原生子代理能力是首选执行桥；阿极直接派发任务范围明确的专家分身并管理并发与局部阻塞。专家定义/能力映射不代表分身已经启动。仓库中的Python执行器、`tools/legion_pipeline.py`及app-server适配仅作为辅助/诊断，不能替代当前会话原生委派；本地路由不调用真实模型。历史staff/leader实现仅留档，不得由当前运行时路由或启动。

## 后续补全规则

实际任务首次触发未覆盖职责时，补该专家卡：职责边界、既有P3角色ID、最窄的已安装Skill/MCP/CLI/API引用、输入与产物、真实并发/依赖关系、权限和失败降级。需要外部新能力时先查官方文档及成熟实现，并且仅在采用结论确有影响时安装/绑定。没有消费者的空专家维持冷态，不为了目录覆盖率批量填充。




## 压缩/交接恢复

复杂或长任务触发上下文压缩、角色交接或会话切换时，按需读取 [上下文连续性协议](context-continuity.md)。保留最小续接包与真实产物/回执引用；简单任务不增加记忆写入。该方法复用现有宿主handoff，不要求每位专家各自建立记忆库。
