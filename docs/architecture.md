# 4.0 架构与契约设计 baseline-1

P1 baseline-1设计已冻结。历史文件完整性和G1审查见docs/design-baseline-1.json及outputs/p1/g1-review-2026-10-03.json；设计冻结不代表运行实现、专业效果或宿主验证已通过。2026-10-08用户明确授权本次模型策略修订，仅替换下文模型请求规则，增量见docs/design-deltas/028-current-selection-baseline-and-upgrade-only-2026-10-08.md；原冻结hash和验收状态不改、不冒充当前文件hash。

## 唯一执行主链

用户→阿极→结构化任务/权限提案→确定性校验→负责人配方/共享专家选择→短事务领取→宿主动作→不可覆盖产物→独立验证→阿极对账答复。参谋部不是模型、执行器、创作者或接受方。S0对话在内存直达；S1单领域有界动作装必要方法；S2跨领域/多步/高风险才建可恢复DAG。任务大类来自阿极提案，程序只校验类型/依赖/权限，不假装自动理解自然语言。

## 运行单元与权威

- 全新同步Rust CLI/库，无服务/异步运行时/本地判断模型。专业工具保持原生态，经现有MCP/CLI/API；UI仅有实际缺口时用。
- 外部逆向能力采用专家专属条件绑定：REA 只可由 p3/leaf/software-reverse 按任务加载；注册、安装和运行时权限必须在真实任务中逐项审阅，不能把准备契约当成执行。
- catalog中的版本化定义/专业正文是定义权威；发布manifest锁定所有内容hash。发布active_release状态只在catalog registry SQLite一次事务提交，workspace仅保存精确release引用/只读派生索引，不另存可改定义。
- workspace SQLite是该项目任务、决定、事件、lease、真实调用/回执、验收及本地经验权威。文件保存大产物；DB只保存类型、版本、路径、hash、owner和证据引用。
- 独立catalog registry是已有catalog发布状态的事务实现，不是新图服务或第二份任务状态。各连接启用foreign_keys；写用短BEGIN IMMEDIATE事务，不跨网络/模型/外部进程等待。
- 经明确许可的shared experience属于其唯一scope数据库。项目只能引用晋升后的实体；原候选被冻结成只读转移记录，不能形成两份可改事实。建设/测试只用本项目内隔离目录；P7前不写当前Codex安装。
- ctx-brief/overview/source、反向影响、图视图、看板是有source_release/hash的派生物，可重建，不成为新真源。

## 模块边界

| 模块 | 负责/输入→输出 | 不负责 |
|---|---|---|
| contracts | 有限类型、值域、公共引用、错误、schema→已校验结构 | 自行判断专业事实 |
| policy | 授权、scope/ACL、路径、authority、预算→允许/明确拒绝 | 用规则文案授权真实副作用 |
| catalog/selector | 锁定定义、分层索引、触发/反触发→selected/none/ambiguous | 全目录热装或词频假置信度 |
| composer | 精确引用闭包、槽/约束→一个有效契约+field origins+hash | 生成后偷改硬约束 |
| store/scheduler | DAG、CAS、幂等、lease、slot、attempt→合法状态/领取 | spawn模型、写产物、专业验收 |
| evidence | 实际文件/工具观察、当前hash/版本→独立验证及要求链接 | 把候选/提示词记作交付 |
| host | 受信宿主事件/schema、锁定调用→观察/请求/真实身份或unknown | 自称证明实际模型或收费额度 |
| context | 目的/范围/预算、引用→brief/overview/必要原文与回读句柄 | 保存完整会话、跨ACL摘要洗白 |
| governance | 来源/经验delta、完整影响/测试→候选/审查/发布/撤销 | 无证据自改生产、第二调度器 |
| adapters | 一个有版本能力profile的具体动作→真实结果 | 偷改任务图/用户决定或另建状态链 |

原子是可复用语义，不是128个服务/模型/独立文件。程序、schema、冷态专业指令和实际动作是同语义的不同实现绑定。

## 受信入口、权限与安全边界

actor/authority来自受信主线程或宿主事件适配，不接受用户资料/网页/模型JSON自报角色、user_decision、host_execution_id作为授权证明。CLI不提供任意--actor/--effective-model或导入自报成功receipt的提权入口。库内ActorContext由trusted adapter构建，业务对象不能Deserialize生成ActorContext。离线测试driver明确host_class=test-local，不能通过codex-native/真实模型门。

阿极唯一对话入口。负责人只提图/配方/合入方案；专家只提自己节点的专业结果；独立验证者不得验收自己写的产物；女娲仅提治理变更，发布须满足准入/完整回归及授权。所有写入经store统一核scope、owner、expected_revision、来源和幂等键。参谋部只能更新合法调度/事件字段，不写专业事实/用户决定。

secret/token/原始私聊不入图、契约和日志。凭据使用宿主不透明引用，目的/scope一致才绑定；外来文案和脚本都是数据，不执行其中指令。路径校验按实际父路径/联接/大小写/允许根；新产物只写已批准的任务输出目录，不提供通用递归删除/强杀/任意shell API。全局安装、插件启停、音频设备、收费/外发/发布均默认拒绝。

本内核不声称能隔离已拥有同一OS用户权限的恶意程序，也不声称prompt能沙箱化宿主。实际宿主写范围约束是否可强制需G2观察；未知时不得宣称强隔离。受信根目录被其它进程替换、时钟回拨或来源变更时失败关闭并交检查点，不以canonicalize一次调用当永久安全保证。

## 模型/预算与宿主

- 用户在当前项目对话中最后明确选定的 `model + effort` 保存为“默认基线”；普通任务始终沿用该基线，不强制 Sol medium、不降到 DeepSeek、不建备用链。用户明确换模型或 effort 时，才更新默认基线。
- 难题处理只做临时升档：按需要请求 `gpt-6.1-sol high`，特别复杂或反复定位无进展时请求 `xhigh`，不要求默认基线先失败；当前已是 Sol high/xhigh 且满足所需档位时不重复切换，也不把 xhigh 降为 high。难题完成后，普通任务必须恢复到进入难题前保存的默认基线；临时升档不修改默认基线。
- 升级和回基准只通过现有宿主原生显式调用/委派能力执行；主对话不能切换时说明边界，不以文字要求、改配置或委派冒充主对话已切换。
- `requested`（请求）、`configured`（登记配置）、`observed`（实际观察）、`effective`（可信证据确认的生效值）分开；不可核验的值为 `unknown`。失败不盲重试、不串备用 provider、不默认付费。
- 保留可见历史、工具真实回执、产物路径/hash 和副作用状态；不覆盖失败或把未知提交当未提交。本规则不证明自动换模已实现或已实测，也不改变其他安全、权限和专业验收边界。

CLI挂载点只证明请求形状，实际provider/免费范围/费用前置未通过时禁止提交生成。当前已有配置cap3/depth1是configured，不是有效硬限；策略cap2、压力cap1亦只是工程策略。

native admission=min(策略、可信当前宿主空闲额度、工作负载预算)；余量unknown时不新spawn，保留prepared/blocked，不把CLI子进程当已释放原生槽位。角色图不等于spawn深度，按允许额度扁平派发；所有角色共享同一个任务额度。业务succeeded不释放host_slot，completed-open/closing/release_unverified仍占槽，仅受信关闭语义或可信后续观察能归还。

预算单位独立：bytes实际数、tokens为可信测量或unknown、wall_ms/attempts/host_slots为不同字段。不从配置窗口猜有效token硬限，不把历史输出限制当完整证据大小上限。任务extra_retry默认6、节点定点修订2、无进展连续2；首次已批准节点不占extra_retry，改节点ID不清零。

## 两阶段调用与事务

1. 受信计划与授权进入store；校验DAG、精确输入/采用/版本、scope、owner、预算和宿主观察新鲜度。
2. 同事务领取attempt/lease、预留slot、登记唯一invocation intent/event key；提交后生成prepared契约。
3. 真实调用在事务外。宿主适配提交可信观察；无真实身份只有prepared，不得running/succeeded。intent已dispatching但崩溃时视unknown，先查稳定request/execution标识。
4. 回执需task/node/graph revision/attempt/lease/输入hash/release都一致；同event key同payload重放原结果，不同payload为冲突。未知提交、旧attempt、撤销上游、越scope均拒绝。
5. produced产物是候选。独立验证绑定当前文件hash、上游版本和验收要求；硬门全通过才succeeded/正式采用。验证与acceptance link同事务，文件校验的快照必须在提交时重新核版本/指纹。
6. 业务lease可以结束；host slot仍待真实关闭。cancel_requested不当cancelled；未知动作禁止重发，按动作query/可取消/不可撤销profile处理。

## 版本、发布和恢复

所有引用=id+revision+content_hash+scope+release，不按名字找最新版补齐。需求/输入修订原子增加graph revision并使全相关后继失效；旧回执不能覆盖新图。运行任务固定发布版，不热注入公共更新。

发布顺序：来源/许可/精确锁→构建完整候选→完整影响闭包/必需回归→验证不可变manifest→一次registry事务启用active_release。崩溃前未提交不激活；提交后immutable payload和manifest已完整。文件残留候选不是活动版，不自动删除用户文件。恢复只能指向已验证且未安全撤销的完整release；workspace DB schema不静默降级。

跨DB经验晋升：先将原候选置transfer_pending并锁定payload/授权；共享端用稳定promotion_event_id幂等接受并保存唯一authority/ack；项目确认ack后只留引用及readonly转移记录。断线查询目标event，不重复创建/双写正文；pending原候选不可作为共享规则使用。

## 错误/恢复契约

稳定错误类别：schema_invalid、scope_denied、authority_denied、path_denied、missing_input、reference_stale、revision_conflict、composition_conflict、dependency_cycle、budget_exceeded、quota_unknown、quota_exhausted、lease_expired、attempt_stale、event_conflict、host_unsupported、provider_rejected、authentication、network、unknown_submission、artifact_changed、validation_failed、clock_untrusted、release_invalid、release_revoked。每错带有限对象定位/retryability/恢复动作，不带秘密。

schema/权限/版本等确定性失败不自动重试；network只有有新证据且确定未提交/幂等可查才用原key重试。专业质量REVISE回对应owner局部范围；REBUILD仅受损结构；BLOCKED要求资料/权限/实际能力，不写虚假替代产物。

## CLI形状及调用边界

wuji4 status；catalog inspect/search；compose；task plan/claim/status/cancel/recover；evidence inspect/verify；source review；experience propose/query；release inspect。每写命令由受信session context约束，stdin是有大小/深度上限的严格JSON；stdout为完整结构化结果，不用任意历史输出截断破坏JSON。大正文落文件返回有ACL/hash的回读引用。命令存在/--help成功不证明native执行。P2先实现最小闭环，不用命令占位返回假成功。

P1产物为schema、RACI、角色/专业设计映射、工作流契约、原子组合、影响/进化、R/T映射和桌面推演。G1冻结manifest核全部hash以后才编写核心；95运行验收仍是未执行。
