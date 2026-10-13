# 逻辑图谱、typed store与写权

P1 baseline-1设计已冻结。文件完整性和G1审查见docs/design-baseline-1.json及outputs/p1/g1-review-2026-10-03.json；设计冻结不代表运行实现、专业效果或宿主验证已通过。

## 类型与事务边界

| 表组 | 权威字段/唯一性 | 提交边界 |
|---|---|---|
| scopes/grants | scope_id、kind、parent、classification；actor用途权限 | 每次读和间接引用核ACL，private不得自动变shared |
| decisions/requirements | scope,id,revision；authority_proof_ref；expected_revision | 用户决定与需求投影同事务；模型只能提案 |
| tasks/role_graphs/task_nodes | task/graph revision；实例parent；node owner、状态、release、input refs | 图改版与受影响后继失效同事务；角色图短寿命 |
| node_dependencies | task,from,to；两端修订、scope | 缺端点/自环/有向环拒绝；不把原子谱系边当调度边 |
| attempts/leases | attempt_id唯一；node revision、owner、expires_at、state | 同节点当前领取唯一；CAS核lease与可信时间 |
| host_slots | invocation/slot_id唯一；reserved/open/closing/release_unverified/closed；evidence_ref | 与领取原子预留；只真实关闭确认释放，lease结束不覆盖slot |
| invocations/execution_events | invocation/event key唯一；payload hash；intent/dispatched/observed/unknown；trusted host ref | intent先持久化，外部执行后单独提交观察，重复payload同/不同分开 |
| artifacts | scope,id,revision,path,bytes,content_hash,producer/attempt,adoption | 不覆盖版本；producer不能自报verified/adopted |
| validations/acceptance_links | validation_id；validator/role；artifact revision/hash；requirement revision；verdict | 当前验证与要求投影同事务；self-review和过期验证拒绝 |
| source_registry/catalog_versions | source locator/hash/read scope/license/version；release manifest/hash/state | 来源观察不覆盖用户决定；active release唯一事务指针 |
| experiences/experience_evidence | scope,type,key,revision,status,applicability,counterexample,knowledge refs | proposal→review→验证→准入；TTL/撤销实时过滤，晋升用ack协议 |
| risks/review_findings/audit_events | finding scope、owner、object exact ref、evidence、verdict | 最小追加审计；不存原始会话/秘密 |
| derived_indexes/metrics | source_release/hash、complete flag；统计单位/范围/时间 | 可重建，不提供第二active事实来源 |

专业payload可以JSON/Markdown引用，但状态/主键/owner/scope/修订/lease/slot/验收写权必须是typed字段与数据库约束，不是万能graph_nodes任意JSON。

## 16视图

G-REQ→requirements；G-DEC→decisions；G-LEAD→发布版负责人配方；G-EXP→发布版专家定义与专业边界；G-TOOL→工具action/profile/健康/证据；G-ROLE→role_graphs/task_nodes；G-EXEC→tasks/attempts/leases/slots/events；G-ACCEPT→requirements/artifacts/validations/acceptance_links；G-CODE→派生符号/依赖/测试索引；G-RESEARCH→source refs/claim evidence；G-INCIDENT→symptom/hypothesis/diagnosis evidence；G-EXPERIENCE→typed经验；G-LINEAGE→source/atom/composition/consumer/test refs；G-RISK→risks；G-REVIEW→review_findings；G-PERF→metrics。目录类别、上下文投影及source_registry/catalog_versions是对应typed数据/派生读法，不另起第17图。

## 有限关系

depends-on/produces/validates/derives-from/uses-tool/uses-expert/implements/affects/supersedes/governed-by/uses-atom/composes/specializes。每个predicate有from/to类型白名单，修订和scope读取权双向校验；跨scope只能经过授权引用，不因边是派生就绕ACL。

## ACL与RACI

| 角色 | 可提出 | 可提交 | 明确禁止 |
|---|---|---|---|
| 阿极 | 用户需求/决定提案、路由、对账 | 受信用户事件绑定后的requirement、当前验收对账、用户答复 | 假造宿主/模型/产物证据 |
| 参谋部 | 调度合法性/预算状态 | store中的CAS领取、事件、依赖、失效、租约 | 写专业产物/验收专业质量/替用户决定 |
| 负责人 | 配方/DAG/合入范围 | 经授权自己的合入产物；图提案交store校验 | 霸占专家、扩大范围、直接spawn自由团队 |
| 专家/执行节点 | 自己node的专业候选/缺料 | 允许输出目录产物与自检；真实动作须host | 改上游决定、跨scope、批准自己验收 |
| 复合审查/验证者 | hash当前的质量/安全/合规/性能发现 | 自己职权的验证记录；不得与producer身份相同 | 篡改被审产物、用分数覆盖硬失败 |
| 女娲 | 去重/新来源/经验delta/发布候选 | 准入与完整回归闭合后的发布事务 | 常驻改生产/另起调度或收费优化 |
| 宿主适配 | 受信schema/事件/真实观察 | 有调用身份的invocation、close/释放观察 | 接受模型JSON自报身份、工具注释当授权 |

owner是业务责任，不赋任意DB写权。库内写入口只接由受信适配建立的ActorContext；任何业务JSON中的actor/authority字段只作数据，不构造该上下文。

## 无环、失效、分页与恢复

任务依赖同图内typed DAG；用有界邻接遍历检测环并返回具体路径。变更闭包用visited精确引用去重，普通查询可truncate/回读；发布影响必须分页穷尽并保存完整性证明，不能拿20条当全量。

图变更CAS(expected_revision)，更新任务revision，标记所有引用改变输入/要求的后继superseded/invalidated；已有host slot不释放。在途外部动作另记录query/cancel/unknown；不能据“旧任务作废”盲重发或强杀。旧产物可只读保留，但不是当前采用输入。

持久时钟记录UTC毫秒与最近可信观测；本进程可用单调时间辅助，重启不假装单调锚继续有效。回拨/超出锁定deadline的事件clock_untrusted/lease_expired。DB busy只做有界数据库锁等待，不重跑外部动作。
