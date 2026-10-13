# P2原生请求准备与G2最小职责报告

日期：2026-10-03。执行v1.6，设计baseline-1.1不变。本次是P2允许的最小准备，不是P3批量建设、正式专家发布、原生运行或P0—P6完工。

## 本次实际推进

- 新写catalog/p2/engineering.json与validation.json两个职责候选；目标、输入、过程、输出、验收、反触发、失败/取消与字段出处完整。工程按WF-SOFTWARE/WF-BUGFIX限定变化，评审按software.quality/code-review独立检查具体改动。只提炼已审方法，没有复制3.0或WorkBuddy实现/模板。
- 工程方法绑定P01/P03/P04/P08；独立验证绑定G01/G03/J06/J07。每个链接锁定批准计划、冻结职责映射、唯一原子来源账的hash及精确pointer；没有重读已有效总结、课件或原文。
- 新写src/native_protocol.rs与两个CLI入口prepared-roles、prepare-native。固定请求gpt-6.1-sol：文字medium、代码high、修复/规划xhigh；简单文字仍由阿极完成，不为它展开G2专家。
- prepare-native核冻结WorkflowPlan包络/hash、工作区scope、精确职责bytes/release/revision、DAG、有限文件范围、必需检查、producer/reviewer不同及硬字节预算。返回确定性thread/start与未绑定turn/start模板，绝不启动宿主或写用户产物。
- PreparedNativeRequest没有Deserialize入口，字段私有；ensure_dispatchable始终返回HostUnknown。没有从业务JSON导入成功回执/有效模型/费用/关闭的后门。现阶段也没有能创建运行准入的可信原生adapter；这项缺口明确保留。

## 研究与协议依据

先搜索官方资料，再实际HTTP取得官方app-server正文；developers.openai.com入口重定向到learn.chatgpt.com/docs/app-server。只阅读模型请求、schema导出、关闭及usage相关选定段落，不登记整页已读。原始网页、摘要和hash登记outputs/p2/native-protocol-source-evidence.json，承接现有统一上游来源账。

本机只读核CLI0.160.0帮助后，以Process级独立CODEX_HOME导出该版本schema到.dev/native-protocol-schema-0.160.0；没有启动app-server，没有复制配置/凭据，没有读取model/list，没有生成或修改Codex。导出警告说明隔离HOME不存在、没有创建PATH别名，已保留这一边界。

本机TurnStart字段是effort；ReasoningEffort定义只要求非空字符串，不枚举支持档位。首次CLI测试错误假设enum，已修正为检查真实schema形状，失败日志保留。官方示例、model/list形状及网页上的6.1-sol不能证明用户第三方当前可用性、实际请求接受或免费范围，不据此换模或填effective。

thread/unsubscribe回复只描述订阅状态；不能把它、turn/completed或业务产物完成当原生槽已释放。真正关闭/库存观察要绑定原thread/invocation，由未来受信transport取得。本次原生调用与close观察均为0。

## 当前准备的限制

候选的runtime_admission=false、effectiveness=not_run。请求模板包含未绑定threadId，不是可直接发送的请求。拟定文件范围不是授权；声明InputRef没有被prepare-native核成当前采用输入，输出明确保留其状态。目标写路径限定新文件且拒绝覆盖，但模型候选通道本身使用read-only且禁network；将来真实写文件仍须单独授权的materializer，不把只读响应说成文件落地。

同任务相互引用只能作为提案上下文，不视为上游专业产物已被接受。独立actor字符串只证明提案身份不同，不证明两个真实模型执行者独立。模型、费用、scope、quota、实际关闭及委派证据未具备前，候选不能进入Store.plan模型运行；原本的本地程序准入不放宽。

## 实际重验

- 70项Rust测试通过：69行为入口及1个OS子进程fixture入口；本轮新增9项纯准备/拒绝分支，不是9次模型调用。
- 9项原本实际CLI集成与4项新增准备CLI测试通过。新增项核两职责及精确来源、所使用协议选定字段/类型、固定请求/未绑定状态、self-asserted成功/费用拒绝、独立评审与零副作用。只验证用到的字段，不冒称完整JSON Schema通用验证器。
- 9项设计审计工具测试、1001项结构检查通过；G1冻结文件不改。历史47项P0辅助测试本轮未重跑。
- 95项冻结完整场景执行/通过仍0；局部组件证据单独登记。T68/T69/T72/T73真实模型/档位/并发/关闭/费用门均未过。

日志与hash见outputs/p2/core-build-review.json、native-preparation-review.json；首轮schema假设错误日志保留，重验成功没有覆盖失败历史。

## 真正剩余条件

G2仍需要匹配gpt-6.1-sol及三档实际请求的可信观察、免费前置、原生容量及真实退出释放，以及需要时的明确模型委派授权。公开资料和本地schema能解决协议字段问题，不能解决这些账号/运行/授权事实。没有合法安全的正向宿主证据，不发起额外生成，不绕门推进P3—P6，不宣称完工。

用户的持续目标仍为P0—P6。本次有实质准备进展，不擅自改目标或提前标complete/blocked；后续仅在有合法推进条件时继续，不用反复扩文件复制测试、重复资料阅读或无限检索相同结论充当进展。当前Codex、插件、音频链、3.0及用户原资料未修改，不付费、不发布、不清理、不关机。
