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

## 就绪能力映射

| P3专家职责 | 直接加载的Skill | 可派发任务 | 不自动获得的能力 |
|---|---|---|---|
| `p3/workflow/research` | 本包 `references/multi-source-research.md` | 研究问题拆分、来源范围分支、原始依据/反证、决策建议 | 浏览器/GitHub/MCP是否可用须按当前会话确认 |
| `p3/method/knowledge-base-qa` | 本包任务契约 | 基于已授权文档回答并逐项绑定来源、标明缺口 | 私有知识库访问权、云盘/文档授权 |
| `p3/workflow/code-repair`、`p3/leaf/code-review`、`p3/leaf/software-architecture`及语言专家 | 本包任务契约，必要时才加载对应语言/框架现有Skill | 缺陷定位、限定范围修改、代码审阅、架构或语言实现 | 仓库写权限、运行环境、测试工具不由角色声明赋予 |
| `p3/workflow/document-deck` | 可用时加载`documents:documents`或`presentations:Presentations` | Word/PDF/演示文件的解析、创建、编辑与必要的视觉检查 | 文件写权限、编译/渲染成功不由派发本身保证 |
| `p3/leaf/data-analysis`、`p3/workflow/dashboard-review` | 可用时加载`spreadsheets:Spreadsheets`；在线Excel会话才用`spreadsheets:excel-live-control` | 表格分析、公式/图表操作、数据口径与不确定性 | 云端数据授权及实时工作簿连接 |
| `p3/workflow/business-library`、`p3/workflow/workbench-builder` | 按实际文件选`documents:documents`、`spreadsheets:Spreadsheets`、`presentations:Presentations`或`pdf:pdf` | 办公交付、多格式结构保全、可编辑文件生成 | 实际渲染/解析能力以当前工具回执为准 |
| `p3/workflow/automation-design` | 若任务涉及Codex自动化，按需读`openai-docs`；飞书任务/日历自动化分别读`lark-task`/`lark-calendar` | 设计并操作用户明确要求的宿主原生自动化 | 创建/修改定时任务、飞书对象仍受用户授权和工具可用性约束 |
| `p3/leaf/skill-packager` | `skill-creator`；飞书CLI自定义Skill才用`lark-skill-maker` | 创建/更新Codex Skill或lark-cli Skill | 不自动修改全局技能或凭据 |
| `p3/workflow/publication-delivery`、`p3/workflow/content-operations` | 发布目标明确后再读对应平台Skill；飞书渠道按需使用`lark-im`、`lark-doc`或`lark-drive` | 准备平台交付、获准后操作发布/消息/文件 | 外发、发布、发送、删除需权限；拟稿不等于发出 |
| `p3/workflow/image-creation` | 有图像生成/编辑任务时用`imagegen` | 生成/编辑图像资产 | 生成权限/成本/来源权利以工具及授权为准 |
| `p3/leaf/motion-graphics` | `dashi-ppt`只在演示/动效交付符合该Skill范围时使用；其他视频/音频按当前可用专业Skill | 在已授权brief下输出动效/可编辑工程 | 不推断不存在的视频/音频Skill，不生成虚构媒体或外部接口 |

## 飞书能力按意图加载

不要把全部飞书Skills塞给一个常驻专家。由阿极按对象路由单个窄Skill：文档`lark-doc`；云盘`lark-drive`；表格`lark-sheets`；Base`lark-base`；幻灯片`lark-slides`；即时消息`lark-im`；邮件`lark-mail`；日历`lark-calendar`；任务`lark-task`；审批`lark-approval`；知识库结构`lark-wiki`；认证/权限`lark-shared`。这些是现成Skill引用，不保证本次会话的账户授权或对应底层API已连接。

## 执行桥与边界

Codex当前会话实际提供的原生子代理能力是首选执行桥；阿极直接派发任务范围明确的专家分身并管理并发与局部阻塞。专家定义/能力映射不代表分身已经启动。仓库中的Python执行器、`tools/legion_pipeline.py`及app-server适配仅作为辅助/诊断，不能替代当前会话原生委派；本地路由不调用真实模型。历史staff/leader实现仅留档，不得由当前运行时路由或启动。

## 后续补全规则

实际任务首次触发未覆盖职责时，补该专家卡：职责边界、既有P3角色ID、最窄的已安装Skill/MCP/CLI/API引用、输入与产物、真实并发/依赖关系、权限和失败降级。需要外部新能力时先查官方文档及成熟实现，并且仅在采用结论确有影响时安装/绑定。没有消费者的空专家维持冷态，不为了目录覆盖率批量填充。




## 压缩/交接恢复

复杂或长任务触发上下文压缩、角色交接或会话切换时，按需读取 [上下文连续性协议](context-continuity.md)。保留最小续接包与真实产物/回执引用；简单任务不增加记忆写入。该方法复用现有宿主handoff，不要求每位专家各自建立记忆库。
