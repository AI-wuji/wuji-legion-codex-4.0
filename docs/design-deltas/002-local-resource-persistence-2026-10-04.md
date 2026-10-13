# 002：项目内知识/经验持久化与已知版本迁移

日期：2026-10-04。依据冻结 architecture、evolution-impact-spec、ADR002及v1.6；不改原20个冻结文件、不改变批准范围，不批准P7。

## 实现范围

- 知识与经验使用同一工作区SQLite中不同类型表、版本与生命周期；resource_events只记录对应变更事件，不建立第二任务事实库。
- resource-propose记录project_private、review_proposal候选；不会因JSON的authority字段自动成为用户授权或全局事实。
- resource-review-local只在本项目.dev下独立工作区、显式确认后得到active_local；始终runtime_admission=false，不宣称正式专家有效性、公共发布或专业效果。
- resource-query每次重核当前文件hash、ExactRef的scope/release/revision、经验依赖的知识版本、撤销与过期。源变化/知识退役后经验不再命中，不依据缓存复活。
- 幂等结果是历史事务结果，不代表现在仍符合复用条件；当前资格必须查询。新候选不热覆盖旧采用版本；本地审查通过后同事务切换同ID的局部状态。

## 数据库边界

工作区schema从2增加至3。只对已确认application_id、原工作区身份的已知schema2进行加法事务迁移；只读观察型open_existing拒绝迁移，明确init才允许迁移。未知/更新/身份不符数据库不覆写。失败需全部回滚，包括user_version。

## 未实现项

公共catalog registry完整发布、跨scope移交/ack、独立专业holdout和模型正式准入仍需后续建设。当前局部持久化不能替代这些门，也不宣称G5整体专业效果已通过。

新测试为tests/p6_resource_acceptance.rs、tests/p6_schema_migration.rs和tools/test_resource_cli.py；结果使用outputs/p6/test-execution.json绑定实际源码与日志，不通过更新冻结acceptance-map来宣布通过。
