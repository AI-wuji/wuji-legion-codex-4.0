# P2真实隔离执行与G2重验报告

日期：2026-10-03。执行基线：v1.6。本文只记录P2/G2真实隔离执行，不宣称G2通过、P3—P6完成或P7安装。

## 1. 结果摘要

- Q与R两个全新隔离工作区各完成一组engineering与validation原生调用；每个调用均观察到匹配的`thread/start`、`turn/start`、`turn/started`、`turn/completed`、`thread/closed`及owned process exit。
- Q/R的producer与reviewer分别使用不同真实thread，产物实际存在，SQLite中的artifact hash、revision、attempt和关闭证据一致。
- R的独立review返回`verdict=fail`：`engineering.scope-preserved`与`validation.artifact-current`、`validation.independent`为true，但行为与回归证据项为false；`accept-native`返回`ValidationStale`，事务没有把失败产物adopted。
- 真实生命周期已验证，但effective backend model/effort、native quota、费用或计费证明仍为unknown；`native_verified`与G2均保持未通过。
- L/M/N/P的早期unknown attempt保留原状态，不重派；没有用新任务覆盖旧attempt的未知语义。

## 2. 期间修复

1. Rust导入驱动回执时严格校验并剥离驱动添加的`transport_provenance`，另存为metadata-only证据，不让它参与RPC匹配或权限判断。
2. 删除bootstrap对`NativeSession.start()`的重复调用，使`run_task`成为唯一生命周期所有者。
3. 接受真实事件中出现的`emittedAtMs`传输时间戳，要求无符号整数并不授予任何业务、关闭或模型权限。
4. 准备validation节点时，仅当前选中节点要求新写路径；已完成的上游engineering输出保留并继续由artifact/hash/revision校验。
5. 驱动按agent message ID去重`item/completed`与`turn/completed.items`，避免同一模型消息被拼接两次，新增回归测试覆盖该场景。

## 3. 真实执行证据

- Q工作区：`.dev/native-p2-workspace-20261003-q`；engineering与validation artifact均为`produced`，两slot均为`closed`。旧validation JSON因去重修复前的重复消息而不可作为通过证据，已在R重跑。
- R工作区：`.dev/native-p2-workspace-20261003-r`；engineering artifact hash为`a3434a21f4ed65e71a0c72c0713e8cf11815985fa95cda72126fad4941fc1c4e`，validation artifact hash为`c3a577ddebf545b03cebe7c9cb927fcbca3e69e6e02d0e90bb81722c5a6fdfdd`。
- R reviewer结果：`engineering.scope-preserved=true`、`engineering.behavior-current=false`、`engineering.regression-current=false`、`validation.artifact-current=true`、`validation.behavior-current=false`、`validation.regression-evidence=false`、`validation.independent=true`。
- `outputs/p2/native-real-execution-report-2026-10-03.json`保存Q/R的SQLite状态、事件、artifact/hash、slot close evidence、未知尝试和配置hash。
- 具体运行日志：`outputs/p2/native-real-engineering-run-q.log`、`outputs/p2/native-real-validation-run-q.log`、`outputs/p2/native-real-engineering-run-r.log`、`outputs/p2/native-real-validation-run-r.log`、`outputs/p2/native-accept-run-r.log`。

## 4. 门状态

G2仍为in_progress，且native acceptance子门未通过。失败不是代码异常：独立validator按约束拒绝了缺少真实行为/回归证据的artifact；不能通过手工改JSON、模型自报、总分或关闭消息覆盖。P3批量专家正文、正式运行目录和Codex接入继续禁止。

当前Codex配置`C:/Users/Administrator/.codex/config.toml`的SHA-256仍为`f37efee8358d33ff6b848a6c207b974c501dde0d548a7cfe4d4b052cd1d6e4fc`，未修改。所有原生会话均由隔离工作区创建并观察退出，不修改用户原有进程、插件、音频链或P7安装状态。

## 5. 后续合法路径

补齐与当前artifact/hash/revision绑定的真实行为和回归证据，重新走独立validation与`accept-native`；在G2闭合前不进入P3。effective model、effort、quota和费用事实仍需可信宿主/账单证据，不由本报告推断。
