# 更新日志

## 2026-10-14 — 大工具结果外置与按需回读

- Codex 核心 Skill 增加可运行的 Node `capture/summarize/select/read` 入口：保存命令输出原文，回传 hash、大小、必要状态/错误/权限，按字段或字节回读。
- 对关键字段超预算、陈旧引用、越界/junction、非 UTF-8/BOM、命令失败与重复执行提供明确处理；先预留制品，重复路径不重放副作用。
- 已同步本机安装 Skill 和默认全局入口；详细证据与局限见 `docs/tool-output-adoption-2026-10-14.md`。
- 七项定向测试通过；真实 3,616,323 字节来源锁回执 2,604 字节，完整 442 页重建一致。没有测得整体 token/费用下降。
- 不安装 Context Mode 运行时，不新增 MCP/hooks、记忆库或调度器。既有 Rust 证据权限校验继续保留。
- DSH 同步接入宿主原生 `tools/post-execute` 大文本外置与 `wuji_output_read` 分页回读，staff 升至 0.1.2、bundle 升至 4.3.1；15 项原生定向测试及源/刷新依赖加载校验通过。
