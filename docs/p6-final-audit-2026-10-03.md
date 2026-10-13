# P6 全量复查与交付审计

日期：2026-10-03。本文是 P0—P6 当前实际证据的交付审计，不把局部机制测试或目录文件写成全部专业能力已通过。

## 已通过的局部门

- G2：全新 `u` 隔离任务完成 engineering→独立 validation→accept-native；产物、hash、revision、不同线程、thread/closed、owned process exit均对账一致。
- G3：57项冷态职责目录、69项原子组装、composition manifest及4项质量测试通过；runtime admission仍为 false。
- G5：Rust治理核心4项测试通过，覆盖delta幂等、冲突、CAS、scope/evidence、影响闭包、撤销和发布回滚。
- 本轮 Rust 全量测试：102 passed；Python 工具测试：115 passed；cargo build通过。
- baseline-1.1的20个冻结文件hash一致；当前Codex配置hash仍为 `f37efee8358d33ff6b848a6c207b974c501dde0d548a7cfe4d4b052cd1d6e4fc`。

## 未通过/阻断

- G4：ComfyUI、OfficeCLI、视频和音频入口在当前主机不可用，且没有安装授权；本地软件研发适配器仅证明确定性文件验证链。
- G6：95项验收矩阵的权威状态仍为 `not_run`，不能用102项Rust或115项Python辅助测试替代；专业holdout、真实媒体/软件产物、有效模型/额度/计费证明仍缺。
- 交付包复查发现并修复了包内清单自引用ZIP哈希的缺陷；当前采用包内不自引用、包外sidecar记录最终ZIP哈希的方式，并由 tools/test_p6_package.py 做哈希绑定、路径安全和包内文件一致性回归。
- 已生成 outputs/p6/evidence-crosswalk.json，将95项权威验收保持为 not_run，并把6类 supporting evidence 与6类外部阻断单独列账；不把机制测试提升成专业验收通过。
- P7：未执行，不修改Codex、插件、凭据、音频设备或用户资料。

权威报告：`outputs/p6/full-audit-report.json`。
