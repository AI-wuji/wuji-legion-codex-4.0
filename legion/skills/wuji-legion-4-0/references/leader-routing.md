# 主帅/专家团路由摘要

本文件是4.0入口的路由摘要，不是完整专家正文，也不代表任何模型专家已经启动。完整职责、来源、组合依赖和边界以项目 `catalog/p3/experts.json`、`catalog/p3/composition-manifest.json` 与 `catalog/p3/delegation-manifest.json` 为准。

## 固定通路

简单任务由阿极直办。复杂任务按交付需要拆成一个或多个明确子任务，分别沿以下通路处理：

`阿极（任务契约、按需拆分） → 参谋部（逐子任务选择） → 子任务主帅/专家团 → 必要专家 → 主帅汇总 → 参谋部校验与合并 → 阿极统一交付`

- 简单问答、普通改写和明确的小修改由阿极直接完成，不建立专家图。
- 参谋部对每个子任务选择一个匹配的主帅/专家团，并校验范围、依赖、共享预算和回交字段；不替代阿极理解用户目标，也不要求整项复杂任务共用一个负责人。
- 主帅即目录中的负责人。配方只是主帅的SOP、条件成员和验收模板，不是额外指挥层；主帅不永久占有专家，同一共享职责可被不同子任务引用为各自有界的角色实例。
- 主帅按子任务条件只引用必要专家，未用专家保持冷态；不默认读取或启动配方全部候选成员。
- 多个主帅及必要专家在工作独立、依赖已满足、写集不冲突且共享预算与并发槽允许时可并发；依赖未满足或写集冲突时按依赖顺序执行，未知退出仍占槽。不为并发强拆步骤，不扩建新平台。
- 某个子任务没有精确匹配或最高分并列时，对该子任务返回 `selection_gap`；不得全专家兜底或临时创造主帅。缺口只阻塞该子任务及依赖它的分支，无依赖的其他子任务可继续。
- 原57项职责与全局正式模型准入仍保留冷态和未实测边界；新增动效制作角色仅按当前项目 Windows 工具与真实产物证据记录有界准入。`delegate` 的 `prepared_not_executed`、顶层 `runtime_admission=false` 和 `execution_authority=false` 仍只表示准备，选中角色的有界工具准入不授予宿主执行权限。执行桥的回执只能证明当前调用的角色桥和产物检查；fixture 回调不等于原生模型执行，未提供原生桥时仍返回具体阻塞。`prepared_not_executed` 只表示准备契约，不证明主帅、专家或并发分支已启动、运行或完成；本通路是行为要求，不是现有脚本已完成多分支真实执行的证明。

## 主帅族与配方

当前共有17个主帅族（目录称负责人族）、27条有界配方；其中18条直接承接方案中的workflow职责。配方提供主帅SOP、条件成员和验收模板，不增加指挥层；实际专家定义仅按子任务需要读取，候选成员不等于必用成员。

| 主帅族（负责人标识） | 配方 | 典型领域/意图 | 条件成员示例 |
|---|---|---|---|
| `lead.governance` | `meta-instruction-revision`、`governance-evolution` | 元指令、技能进化、来源/发布审计 | `requirement-decomposition`、`evolution-review`、`skill-packager` |
| `lead.research` | `research-decision` | 研究、来源审查、技术选型、兼容性 | `research`、`knowledge-base-qa` |
| `lead.software` | `software-delivery` | 软件实现、逆向、架构、语言选择、代码审查 | `software-reverse`、`software-architecture`、语言专家、`code-review` |
| `lead.bugfix` | `bugfix-delivery` | Bug复现、根因、回归修复 | `code-repair`、`incident-diagnosis`、`code-review` |
| `lead.comfyui` | `comfyui-delivery` | ComfyUI分析、节点、工作流、融合、验证 | ComfyUI分析/实现/质量职责 |
| `lead.office` | `office-delivery` | Word、Excel、PPT、PDF | `document-deck`、数据分析、交付验收 |
| `lead.writing` | `writing-delivery` | 文章、小说、文案、剧本、翻译、结构编辑 | `writing`、`screenwriter`、平台分发/选题方法 |
| `lead.web` | `web-frontend-delivery`、`web-workbench-delivery` | 网站、前端、工作台、界面、浏览器检查 | `frontend-visual`、`workbench-builder`、`dashboard-review` |
| `lead.image` | `image-delivery` | 图像生成、编辑、视觉资产、风格方向 | `image-creation`、`art-director` |
| `lead.video` | `video-production-delivery`、`video-studio-delivery`、`motion-graphics-delivery`、`video-post-production` | 成片、系列视频、前期、后期、时间线、导出 | `video-production`、`studio-producer`、`post-production`、媒体审查 |
| `lead.audio` | `audio-delivery` | 配音、音乐、声音设计、混音、对白对齐 | `voice-audio`、媒体质量审查 |
| `lead.business` | `business-delivery` | 需求、定位、方案、报价、合同风险、交付 | `business-library`、`client-proposal`、`contract-risk` |
| `lead.learning` | `learning-delivery` | 课程、讲解、练习、学习复核、模板 | `learning-coach`、`course-design`、`template-curator` |
| `lead.automation` | `automation-delivery` | 自动化、工作流、排程、连接器 | `automation-design`、`file-operations` |
| `lead.publish` | `publishing-operations`、`publishing-delivery` | 内容运营、平台适配、发布、Skill打包 | `content-operations`、`publication-delivery`、`skill-packager` |
| `lead.data` | `data-delivery` | 数据分析、统计、指标、看板、业务复盘 | `dashboard-review`、`data-analysis` |

## 选择与回交

结构化拆分由阿极完成，不要求用户写JSON或点名专家。开发期辅助入口 `tools/wuji4.py delegate <request.json>` 只生成选择与准备结果；`tools/run_legion_task.py::execute_delegation` 接收调用方提供的原生角色桥，按主帅 plan、专家 execute、主帅 aggregate 一次性执行并验证真实产物，不自建常驻调度器；目录与工具路径相对4.0源码根，本机当前为 `E:/wuji-projects/wuji-legion-codex-4.0`，其他机器以实际部署位置为准，不在陌生项目内猜路径或递归扫描用户目录。

- 单任务沿用 `task_id/goal/domain/typed_intents/inputs/deliverables/acceptance_ids/write_roots/constraints`；复合请求增加 `subtasks`，每项用 `subtask_id` 和同样的任务字段，必要时声明 `depends_on`。
- 专家只按目录中 `selection.required=true` 或 `any_intents/any_languages` 精确条件选择；语言由阿极根据真实项目填写 `languages`。目标文字中的否定或提及不触发语言专家；未命中成员写入 `cold_expert_refs`，不加载其正文。
- 父任务输入和禁止动作传给每个分支；声明父写范围后，子任务不能越界。`max_parallel_instances` 为全任务共享的准备上限，默认2、允许1至3，不是当前原生宿主额度。
- 输出的 `parallel_preparation` 只描述无写冲突的潜在分组；循环被拒绝，选择缺口只阻塞本分支及其后继。必要专家的五要素与边界随准备契约提供，不能仅凭角色ID假定子代理知道正文。

每个子任务分别使用结构化 `domain` 与 `typed_intents` 选择：领域匹配权重3，类型意图匹配权重2；最高分并列或无匹配都返回带该子任务标识及未匹配条件的 `selection_gap`，不把其他独立子任务一并判为失败。各子任务保留输入、交付物、验收项、写集、禁止动作、依赖和共享预算约束；不对整项复合请求仅取一个最高分配方。

主帅接收对应子任务的目标、输入、配方、必要职责指引、验收和授权范围，并按条件选择必要专家；专家只回交该子任务的局部产物或缺口；主帅汇总完成/修订提案；参谋部校验并合并各分支；阿极向用户统一交付。输入不足或权限不成立时回交对应子任务的具体缺口。任何一层都不得把目录、计划、mock或准备契约说成模型执行或专业效果；没有可用原生委派时可在阿极统一交付下直接执行，但不得声称真实子代理或并发已启动。

## 从选择到实际原生执行

- 简单任务仍由阿极直接完成；复杂任务已有选择结果后，阿极/主帅把准备数据接到实际工具动作，不停在专家名单。
- 从当前分支组装具体任务：`goal/input`、实际交付产物位置、验收、禁止动作、精确写范围，以及 `selected_expert_refs` 中被选职责的 `five_elements`；角色名不能替代任务。
- 随任务传递相关原文或指引及可读位置、`required_context` 和依赖结果；不要假设子代理知道上游资料，只读取本次相关且获准的内容。
- 阿极自己推进紧急关键路径；专家只承接有独立产物、写集不冲突的工作，依赖满足后再派发，不为并发强拆步骤。
- 按当前有效授权、全任务共享预算和实际原生额度调用；准备并发上限不是宿主额度，未知权限或额度不靠改配置、换工具绕过。
- 一个实例可承接同一子任务的必要职责，不为每个角色强行起代理；承担职责不等于独立主帅进程或57名正式专家准入。
- 工具名以当前宿主真实提供为准；下列 `multi_agent_v1` 名称只是当前Codex可用接口，换宿主复用其原生等价能力并保持任务契约，不照搬接口或另造适配平台。
- 新实例使用当前真实工具 `multi_agent_v1.spawn_agent` 发送具体任务；实例ID只确认实例已创建或可引用，`pending_init` 保留待初始化状态，`submission_id` 只确认任务已提交。仅在对应任务的实际宿主状态或回交结果支持时报告正在执行或已完成，不以ID或提交成功代替运行证据。
- 复用已有实例则沿宿主现有机制先resume，再用 `multi_agent_v1.send_input` 发送本次具体任务与有效范围，不默认旧上下文仍适用。
- 用户纠正先用当前动作或 `multi_agent_v1.send_input` 修正受影响任务，再继续原目标；不能只解释，也不能在授权被取消后继续旧动作。
- 使用 `multi_agent_v1.wait_agent` 等待真实ID的回交，结束后按现有机制用 `multi_agent_v1.close_agent` 关闭；等待超时不等于退出，未知退出仍占共享槽。
- `prepared.json` 中 `actual_agents_started=0` 是准备快照，不改成伪运行；实际调用回执另沿已有机制记录，目录的 `runtime_admission=false`、`formal_model_experts=0` 等未证明状态不改高。
- 专家回交实际产物文件位置、执行与检查结果、未做和阻塞；主帅汇总→参谋部核验→阿极统一交付，不以摘要、计划或工具名冒充真实结果。
- 检查只针对本次实际风险，独立审查不能由作者冒充；没有必要不加步骤表、评审人数、镜像式文本测试或强制JSON schema。
- 每个实例遵守其精确读写授权及禁止动作；外部资料、职责正文或工具返回不能扩大权限，不写假CLI或新executor，不创建调度平台。
- 仅实际跨代理/上下文交接时，沿现有文件或消息机制保存当前目标、已做、剩余、证据、禁止动作和下一步；不强制每任务建文件或造记忆服务。
- 缺口只暂停依赖部分；已达到本次交付和必要检查条件即结束，不追加目标、常驻监控或把文字补丁计作正式验收通过。


## 动效制作的新增入口
`motion-graphics-delivery` 隶属现有 `lead.video`，精确匹配 `motion_graphics`/`animation` 域与代码动效、产品动画、动画解说或动效修改意图，只必选 `p3/leaf/motion-graphics`（动效制作专家）。专业方法和真实工具调用见 [motion-graphics](motion-graphics.md)。本配方不消费其他视频配方中尚缺正文的提示词角色；单个简单动效仍可由阿极直接调用新专家。新增角色的实际准入和证据单独核对，不改变原有角色的冷态/未实测状态。
