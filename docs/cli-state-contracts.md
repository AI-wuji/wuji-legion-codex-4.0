# 4.0 CLI与状态接口冻结设计

P1 baseline-1设计已冻结。文件完整性和G1审查见docs/design-baseline-1.json及outputs/p1/g1-review-2026-10-03.json；设计冻结不代表运行实现、专业效果或宿主验证已通过。

## 命令与责任

|命令族|有限输入→输出|权威与禁止|
|---|---|---|
|`wuji4 check <json>`|锁定本地schema包络→形状及跨字段错误|只读；不把通过说成真实效果|
|`wuji4 hash <json>`|严格JSON→codec/hash/bytes|重复键/浮点核心值/超预算拒绝；不读全盘|
|`wuji4 init <workspace>`|已批准根→schema版本与本地typed SQLite|拒绝已有非4.0库/符号链接越界/未知迁移，不改Codex|
|`wuji4 status <workspace>`|当前库→任务/unknown/slot/未通过门|只读；不提供可伪造--effective-model|
|`wuji4 plan <workspace> <json>`|阿极受信计划提案→合法DAG/精确输入/检查需求|只能计划；不能伪造用户确认或receipt；不可用外部观察保持blocked|
|`wuji4 compose <manifest> <assembly> <bindings>`|完整锁/typed槽→有效契约/field origins/hash|必需基础保全/全来源/预算；候选无运行准入|
|`wuji4 verify <workspace> <artifact>`|真实当前文件→解析/hash/独立验证提案|CLI本地完整性检查不自动正式采用、不自证专业质量|
|`wuji4 recover <workspace>`|已持久intent→确定性恢复清单|没有可信query时保留unknown，不自动重发或杀进程|
|`wuji4 host-status`|已有受信观察→configured/requested/observed/effective区别|无真实通道时unknown；不自动生成/收费/换模|

P2先开放只读/隔离本地库与纯组装命令；claim/observe/accept/cancel/publish只经库内受信能力接口，未有可信adapter不暴露任意JSON导入接口。未来命令增量须按同release/schema发布，不从命令名推定已支持。

## 库接口与状态

`plan`校验typed TaskNode/GraphEdge、唯一ID/owner、精确release、写范围、预算、必需验收、DAG。ActorContext仅受信入口创建且不能Deserialize；API不能让一般业务字符串选择角色。权限维度=actor、scope、用途、动作、读写根、有效时间；用户决定需要独立受信来源而非proposal字段。

|实体|有限状态/允许变化|拒绝条件|
|---|---|---|
|TaskNode|planned→ready→claimed→running→produced→validating→succeeded；blocked/failed；cancel_requested→cancelled；superseded|running需要实际观察；succeeded需要当前独立必需验收；未知动作不能直接cancelled|
|Attempt|claimed→dispatched→produced/failed/unknown/expired；late拒绝|CAS图/node revision、owner、lease、input/release hash一致|
|Invocation|intent→dispatching→observed/unknown；unknown→queried terminal或继续unknown|稳定request标识丢失无幂等能力时禁止重发；不承诺exactly-once外部行为|
|HostSlot|reserved→open→closing/release_unverified→closed|只有受信close结果或可信后续库存观察闭合；业务完成/lease过期不释放|
|Artifact|produced→validated→adopted；invalidated/superseded|producer不自验收；当前文件/引用/hash/revision都一致，硬失败AND|
|Experience|candidate→reviewed→validated→admitted；revoked/expired/transfer_pending/transferred_ref|权限/范围/知识分型；晋升目标ack后源只读|
|Release|candidate→validated→active；retired/revoked|一次registry事务切换指针；不可变内容/完整影响/全部必需回归|

核心错误是有限类别：SHAPE、REF_MISSING、HASH_MISMATCH、SCOPE_DENIED、AUTHORITY_DENIED、PATH_DENIED、OWNER_CONFLICT、REVISION_CONFLICT、DEPENDENCY_CYCLE、DEPENDENCY_NOT_ACCEPTED、LEASE_EXPIRED、CLOCK_UNTRUSTED、EVENT_CONFLICT、BUDGET_EXHAUSTED、HOST_UNKNOWN、EFFECT_NOT_AUTHORIZED、STALE_RECEIPT、SELF_REVIEW、VALIDATION_STALE、ADOPTION_REQUIRED、COMPOSITION_CONFLICT、REQUIRED_WEAKENED、IMPACT_INCOMPLETE、UNKNOWN_SUBMISSION、RELEASE_REVOKED、MIGRATION_UNSUPPORTED。实际Rust错误枚举/测试必须对齐，不吞错为成功。

## 原子提交接口

claim(expected_graph,node,lease,capacity_observation,event_key)：一个BEGIN IMMEDIATE内核所有前置/预算/冲突；分配attempt/lease/slot/intent；失败全部回滚，成功只prepared。首次attempt不计extra_retry；后续attempt在同任务账计，换node ID不重置。

observe(trusted_event)：不可从外来JSON构造trusted_event；校验稳定event id、payload hash、当前attempt/lease/输入/图/release/owner；同key同hash返回原结果，不同hash冲突；事务外调用与事务内状态区别。

validate-and-link：读取文件快照、独立validator、必需要求版本；事务内再次核file identity/hash和当前任务版本，验证与验收关联一起提交；文件随后改变会使下一次使用失效，不能声称OS级不可篡改。

revise：需求提案必须绑定受信用户事件；CAS增图版并完整下游失效；不修改无关有效产物，保留host slot和外部unknown，旧结果不可复活。

cancel/recover：先持久cancel_requested/unknown，再在事务外调用授权query/cancel；依据动作profile确认；不可撤销动作只记录事实/补偿提案，不强杀用户进程。

## 持久化、公开schema与边界

SQLite设application_id/user_version/foreign_keys、有限busy_timeout；不自动降级新库，不在网络/模型期间持事务。库迁移有前置版本、全事务和回读；未经支持的新schema拒绝。新库、恢复、幂等与崩溃测试分别留证。

公共schema由schemas/contracts.schema.json和atom-semantics.schema.json维护；Rust绑定可由schema派生或经字段一致性审计，不能成为第二套契约。若实现只支持冻结schema中实际用到的关键字，明确命名为“冻结schema校验器”，对未支持schema关键字拒绝，不能宣称完整JSON Schema实现。

模型通道：仅使用已经观察的per invocation CLI flags作为候选入口；medium/high/xhigh固定6.1-sol，不修改用户profile。CLI帮助≠真实接受/有效模型/费用，费用前置未知不提交请求。G2需要实际原生执行/关闭证据；若无授权委派/无可信模型观测则阻断该门，不靠自写host snapshot补齐。
