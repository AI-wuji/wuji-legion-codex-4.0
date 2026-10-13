# 2026-10-06：有证返工、单用户权限与真实收口

活动方案仍为v1.7，原稿与95项验收定义不变。用户要求排除25项未运行场景，其余继续；不能把一轮检查或报告生成当任务完成。本次只修现有消费者路径，不新增模型宿主、调度器、专业应用或常驻服务。

## 已有任务的有证返工

`src/revisions.rs::repair_local_plan`复用既有任务、失效记录、事件及独立验证表。调用方只提交局部修订提案；缺陷资格来自实际文件/输入核对触发的未解决invalidations，不来自JSON自称的Finding。

- `revise`保留显式用户计划CAS；`repair`单独处理有证返工，不把正常计划编辑误作连续无进展。
- 只返工本次有证节点及其后继；两个独立缺陷可以分别修复，不把无关blocked节点拉入重做。
- 同一缺陷节点最多使用固定预算中的定点修订数；各节点独立计数。验证进展只重置连续无进展判断，不重置节点返工总数或全任务重试预算。换event-id不会复活额度。
- 丢失产物允许保持原规格、原路径重新生成，不要求制造无关行为变更；存在的旧产物不自动删除或覆盖。
- 原`artifacts.path`全局唯一导致历史失效行卡住再生成，已经改为只约束活动产物的部分唯一索引；原行、原hash、验证外键与事件保留。数据库升为7，只允许现有可信owner的版本6经显式初始化事务升级；观察不迁移，无owner/撤销/未知扩展/碰撞/坏引用拒绝或回滚，原字节不变。旧程序引用不改绑为当前源码。
- 重放返回历史事务结果，不多占修订次数；实际写入、当前独立验证和关闭之后才显示完成。无缺陷不制造三个问题。

## 当前Windows本地资源授权

`src/local_identity.rs`使用受保护系统路径的`whoami.exe /user /fo csv /nh`输出SID，并严格检查单行结构和SID。外部用户名、JSON token、`owner=aji-local`不授予本机用户身份。

新工作区以当前SID绑定单一owner、scope、root hash及enable状态。资源提议/复核/查询/退役，以及transfer/received双方使用，在当前事务及历史重放前复核；已经打开Store也不能沿用撤销前权限。复制数据库、变更scope或伪造另一SID拒绝，不返回私有内容。

没有可信绑定的历史数据库只读检查后拒绝，不静默认领、补owner、迁移或改原字节。该边界依赖操作系统文件权限保护；不声称DACL检查、防管理员/同SID进程直接改SQLite、多租户服务、跨用户公共晋升或非Windows身份支持。系统身份入口不可用时拒绝。

## 部署状态和停止条件

`tools/wuji4.py::status`区分冻结源码包策略与当前本机观察。只有声明的7个核心Skill文件集合和字节hash匹配才显示installed；缺失、额外文件、内容陈旧、链接路径或无法观察都不冒充已装备。全局AGENTS只报告已见默认入口/白帽规则，不读配置秘密，不冒充独立新对话模型行为。

`tools/refresh_continuation_report.py::core_closeout_state`移除无条件`core_closeout_complete=true`：当前T19/T22语义证据、核心源/安装一致及全局规则观察缺一则保留具体next_local_work。当前核心收尾与全部专业能力验收始终分开；所有95项通过才是完整能力完成，历史22项不能倒填当前结果。

后续复查修复了补充证据仍回指旧全量执行的缺口：`tools/p6_acceptance.py::evaluate`接收受项目路径边界约束的`receipt_path`，输出明确的`execution_receipt`并让场景引用实际本轮回执；默认旧路径保留历史调用兼容性。`current_core_projection`重新检查当前源码、日志、配置保护与安装观察，不信任缓存的完成布尔值；`--current-core`仅生成派生的当前剩余视图，不覆盖正式历史验收。包外审计同时列当前有界核心与历史完整能力状态，不把一次补充回归换算成完整95项通过数。

## 已有语义的实际消费者绑定

这些是当前有界实现的可查绑定，不是128个候选全部准入；P0历史候选账保持原状，程序效果不替代模型或专业效果。

| 既有语义 | 当前消费实现 | 对应实际检查 |
|---|---|---|
| D08 无进展停止、J08 局部返工归属 | `src/revisions.rs::repair_local_plan`，原生CLI `repair` | T19有证返工、无缺陷拒绝、独立缺陷分修、节点额度、丢失产物重做；真实CLI修复回归 |
| B01 scope、B02 读取权、B03 动作授权 | `src/local_identity.rs::require`、`src/resources.rs`、`src/transfers.rs`、`src/received.rs` | T22当前owner合法消费、撤销/另一SID/变更scope/JSON自授/重放/跨Store拒绝 |
| B04 路径边界 | 既有`src/policy.rs::Workspace`和Store输出保留 | Windows Junction逃逸、路径重定向和大小写重复写权实测；真实symlink创建因当前token权限缺失未测 |
| C08 完成声明资格 | `tools/refresh_continuation_report.py::core_closeout_state`、既有执行摘要 | 证据陈旧、partial、安装源不一致都不能宣称收口；报告生成不是完成条件 |
| G02 当前字节完整性、M07 包一致性 | `tools/wuji4.py`核心副本观察、既有包构建/验证器 | 当前源/安装7文件比对；本地包→外部审计→包测试按依赖顺序执行 |

当前执行日志和回执见`outputs/p6/continuation-2026-10-06/core-completion-execution.json`；是否有效以该回执与当前源码、日志的实际匹配为准。首次原路径修复失败的回执和日志保留在`outputs/p6/continuation-2026-10-06/failed-missing-artifact-repair/`，不把后来修复倒填成首次成功。原正式账保留历史；补充场景通过只依据此次源码快照、实际日志及完整正负用例，不刷新旧执行hash冒充重跑。
