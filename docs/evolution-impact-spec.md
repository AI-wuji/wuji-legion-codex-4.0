# 双通道进化与完整影响

P1 baseline-1设计已冻结。文件完整性和G1审查见docs/design-baseline-1.json及outputs/p1/g1-review-2026-10-03.json；设计冻结不代表运行实现、专业效果或宿主验证已通过。

新技术与真实经验同链：observation→scoped candidate→来源/隐私/反例/专业重叠→delta提案→完整影响→独立固定验收→授权发布/晋升→按当前scope复用；不每任务增三代理反思。

ResourceDelta携带expected_revision/idempotency_key/operation/evidence/reason/revalidation refs。同key同payload重放、不同时拒绝；源变动仅使相关知识/经验/契约待复核，不能当新的用户决定或热改在途任务。用户私有偏好默认限用户/项目，不泛成全球规则。

发布影响从变更source/knowledge/experience/atom开始，完整遍历source→atom→bundle→assembly→专业/负责人/流程/图→schema/program/model/native实现→全部相关测试；visited按精确ref去重，页数预算分批但最终必须穷尽。每消费者记录保留专业差异、permission/context/schema migration diff；未知边或损坏索引必须修复/重建后再发布。

领域扩大需要新域输入/输出/反例/专业验收；全局扩大需跨对话、代码、非代码证据。性能/低上下文收益也需实际工作负载/单位/范围，不引用上游宣传当4.0测量。无益拆分/专家合并或退役必须保持需求覆盖和恢复版本。

共享晋升按architecture中的transfer_pending→target stable event/ack→source readonly ref协议；中断查询目标，不两库双写可改事实。撤销/过期过滤在每次查询/编译/领取重新检查，缓存含scope/release/input hash，失败/unknown不命中成功。已锁在途release不被悄改；有安全撤销时阻断受影响新动作并给检查点。

恢复target须完整验证、未被安全撤销、schema迁移兼容；不回退用户最新决定或自动降级新DB。P7部署的before/installed hash、三方比对和inverse_patch是另一个授权动作，恢复包不是第二套活动路由。
