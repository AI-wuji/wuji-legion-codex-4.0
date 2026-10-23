# 工具大输出外置与回读：2026-10-14

## 实际交付范围

采用 Context Mode 的大输出外置、代码侧聚合、按需回读方法，自行实现本任务所需的原子适配；未复制其源码、安装 context-mode、注册其 MCP/hooks 或建立第二记忆库。方法采用与该外部运行时的 `runtime_verification=not_run` 分开。

Codex 核心 Skill 新增 `scripts/tool-output.mjs` 与 `references/tool-output.md`，已同步到当前安装位置 `C:/Users/Administrator/.agents/skills/wuji-legion-codex-4-0`。全局 `C:/Users/Administrator/.codex/AGENTS.md` 加入大输出的默认分流规则，原有入口、model/provider/凭据配置未改。修改前备份只保存在本机 `.codex/backups/wuji-tool-output-*`，不进入公开仓库。

脚本是一次性本地 Node 辅助，不是常驻服务或强制拦截全部 Codex 工具的 Hook。已有 MCP resource、分页和制品路径优先复用；普通文件及命令缺入口时才使用它。已登记证据继续由原有 Rust `read-evidence` 承担 owner/revision/scope 校验，普通文件回执不取代这层权限。

## 可运行入口

- `capture`：执行明确程序，将 stdout/stderr 字节及退出码、信号、错误、完整性保存到本次授权工作区；回传短回执。执行前用独占创建预留制品，重复路径拒绝且不重放原命令。
- `summarize`：摘要已有文件，返回路径、SHA-256、字节数、已识别关键状态/错误/权限字段和下一次读回参数；不改原文件。
- `select`：按当前 hash 和确切 JSON pointer 读取一个字段；超过 4096 字节提示进一步收窄或分页，缺字段/陈旧引用拒绝。
- `read`：按当前 hash 和 offset 读取 1..8192 字节；支持非 UTF-8、分片边界与 BOM 的精确重建，非法大小/越界/hash 改变拒绝。

路径必须在声明的本次工作区内，外部 junction/symlink 拒绝。回执 `execution_authority=false`，原文中的授权/指令字段只是资料；不会授予运行程序或读写其他文件的权限。

约定字段识别不等于任意业务 schema 的语义验证。关键字段超预算、未解析文本和未读取的捕获 stdout 必须回读。主帅/专家传局部目标、必要产物路径/hash、所需字段和失败/权限状态；不复制全量父上下文，也不为普通问答建立任务记忆。

## 真实基准与检查

真实消费者为本项目 `docs/external-capability-sources-2026-10-13.json`，不是虚构 payload：

| 检查 | 实际结果 |
|---|---|
| 原始文件 | 3,616,323 字节 |
| 摘要回执 | 2,604 字节 |
| 按 `/sources/6/reading_scope` 读取 | 420 字节 |
| 完整读回 | 442 页、3,616,323 字节，逐字节一致 |
| 原文 SHA-256 | `a4b9bbe86798eb44b11365a20e3de40bd88b90c98a6c2d16d1ecf654a304467f` |
| 错误明细超回执预算 | 正确标记 `critical_fields_complete=false`，要求回读 |
| token/费用 | `unknown` |

此比较是“当前一次摘要/字段回执”的字节开销。完整读回全部原文不节省总字节，分页还有回执开销；不能把短回执百分比当整体 token/费用下降，不能以摘要替代未读证据。

`node --test tools/test_tool_output.mjs` 七项通过：真实大 JSON/Unicode 重建、陈旧和越界拒绝、大关键字段/文本回读要求、真实失败子进程 stderr/退出码、禁止副作用重放、外部 junction 拒绝、字段选择预算与缺字段、BOM/二进制和进程启动失败保存。测试包含组合场景，数量不代表全领域验收。

安装文件与源码字节/hash 一致；本次实际执行了已安装脚本读取来源锁的 `reading_scope`。具体本机基准与安装回执位于 `.dev/context-output/benchmark.json`、`install-evidence.json`；本机目录为忽略制品，不提交用户配置快照。

## DSH 对应交付

DSH 已在 `E:/wuji-projects/dsh-wuji-legion-mode` 的 `@wuji/dsh-wuji-staff@0.1.2` 中接入宿主原生 `tools/post-execute` 内容层适配，并将 bundle 升至 `4.3.1`。符合条件的无极 scope 成功大纯文本会保存为本机会话制品，只替换模型可见的 `content` 为短回执；`value`、`meta`、`isError`、contexts 和下游 deny/finalizer 的权威结果保持原样。回读工具 `wuji_output_read` 仅接受当前会话 scope 与完整 hash，按字符分页，拒绝跨会话、陈旧 hash、越界和不完整关键字段。失败、拒绝、权限、富媒体、未能完整识别关键字段时保留完整原生结果。

已通过 DSH 的 15 项输出外置/回读定向测试（含真实 Cordis ToolRegistry、拒绝和错误传播、unicode、多块文本、hash/路径/硬链接/junction 边界），并分别验证源依赖和 bundle 刷新依赖。`verify-self-built-load.mjs` 已真实 import/apply 两个包并验证四个工具契约；`check-wuji-preset.mjs` 与配置 schema 校验通过。桌面插件管理器当前显示 bundle `v4.3.1` 且“启用”为 On。当前桌面已有会话未重启、未以旧会话冒充新代码已生效；上述结果证明安装解析、新会话可加载路径和原生插件集成，未证明用户当前旧会话的模型端到端行为。未进行付费 provider 长任务测试。

DSH 的回读制品位于系统临时目录并受 scope/hash 门禁约束，不建立第二记忆库、常驻调度器或 Context Mode 全量运行时。
