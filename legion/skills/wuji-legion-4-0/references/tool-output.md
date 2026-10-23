# 大工具结果与原文回读

仅在日志、浏览器快照、JSON、批量文件结果等会挤占上下文时使用；小结果直接读。批量统计优先在工具侧写一次脚本、查询或聚合，只打印本次决定所需字段，保留真实失败和权限状态。

## 已有入口优先

- MCP/浏览器返回 resourceId、分页或制品路径时，沿原入口按需读取，不重复复制同一资料。
- 已登记证据需要 owner/revision/scope 校验时，继续使用现有 `wuji4 read-evidence`，不以普通文件摘要绕过它。
- 无可用资源接口的命令，用本 Skill 的 `scripts/tool-output.mjs` 捕获 stdout/stderr 到任务授权工作区，返回短回执。脚本是本地 Node 辅助，不是 Hook；它不拦截其他 Codex 工具或授予执行权限。

## 文件摘要、捕获与读取

从已安装 Skill 使用脚本的绝对路径；源码脚本位于 `legion/skills/wuji-legion-4-0/scripts/tool-output.mjs`。示例：

```powershell
node <skill>/scripts/tool-output.mjs summarize --workspace <本次授权工作区> --file logs/result.json
node <skill>/scripts/tool-output.mjs capture --workspace <本次授权工作区> --file logs/run-唯一名称.json -- node analyze.mjs
node <skill>/scripts/tool-output.mjs select --workspace <相同工作区> --file logs/result.json --sha256 <回执sha256> --pointer /errors/0/kind
node <skill>/scripts/tool-output.mjs read --workspace <相同工作区> --file logs/result.json --sha256 <回执sha256> --offset 0 --bytes 4096
```

`capture` 的 `--` 后是明确程序与参数，不通过 shell 解释；PowerShell/cmd 只有本次任务确需时显式调用。目标使用工作区相对路径，执行原命令前用独占创建预留回执，不覆盖已有文件，也不因名称重复重放有副作用命令，不写出授权根目录。原命令需要什么授权依然需要什么授权，不能通过脚本执行原本禁止的操作。

回执包含完整文件路径、SHA-256、总字节、关键 JSON 字段的 pointer/value 和下一步读取参数。识别的约定 JSON 状态、错误、stderr、退出码、权限、安全和 unknown 字段优先保留；任意业务 schema 的关键字段仍须按本次验收指定 pointer，不把字段识别当语义完备判断。过大的关键字段或非 JSON 内容使 `critical_fields_complete=false`、`read_required=true`，禁止把短回执当完整验收。摘要不重写原文件；中间原文被省略这一事实始终显式保留。

JSON 优先用 `select` 读取确切 pointer，字段超过 4096 字节时拒绝塞回上下文，提示选更窄字段或分页。按需回读以 `next_offset` 续页，1..8192 字节；sha256 改变拒绝旧引用。单页 UTF-8 不完整或为二进制时返回 `page_base64`，按字节重建，不用替换字符猜原文。捕获制品使用 base64 保留原 stdout/stderr 字节，命令失败或超时也保存 `error`/退出状态并返回失败；`output_complete=false` 表示原进程结果不完整。

## 团队和恢复

上游传给主帅/专家：本次目标、产物路径、hash、必需字段/定位、错误与权限状态、已做/剩余/下一步；避免复制整份日志或父会话历史。成员验收版本和所需原文，引用陈旧或关键字段未读时拒收，局部重做。

Codex 会话交接继续用宿主现有摘要；DSH 任务状态继续用原生 Session/Goal。制品只是本次工具输出，不是新的经验库、任务数据库或跨项目共享权限。普通问答不生成制品，不承诺压缩后自动恢复所有历史。

## 实际开销

只比较本次工具输出原始字节和实际回执字节，并检查同一产物能完整回读、错误/权限不丢、陈旧引用拒绝。字节下降不等于 token/费用下降，更不等于扩大模型上下文容量；不可观测的 token 和费用保持 unknown。
