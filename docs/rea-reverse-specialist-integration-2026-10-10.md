# REA 逆向能力接入说明

日期：2026-10-10。状态：已登记为设计级按需能力，尚未安装、注册或完成本机验证。

## 归属与路由

REA（Reverse Engineer Anything）只绑定到现有逆向工程专家 `p3/leaf/software-reverse`（`baseline_id=software-reverse`）。阿极识别出需要闭源程序、原生二进制、Electron、.NET、Android APK、固件、字节码、崩溃记录或进程行为分析时，才可以把该能力作为这个专家的条件工具加载。

REA 不属于公共工具层，不向普通代码修复、文档、测试、项目管理或其他专家开放，也不承担模型选择、任务调度、军团路由或用户交付。`comfyui-reverse` 仍按自己的 ComfyUI 逆向职责处理；本绑定不把两个专家合并。

## 专家调用契约

- 输入：已授权的目标、分析范围、允许的文件/进程/网络权限和验收目标。
- 处理：逆向工程专家选择必要的 REA MCP 工具，核对目标、版本、依赖和权限，保留工具取消、进度和失败状态。
- 输出：行为重建结论、证据引用、适用范围、未决缺口和安全限制，交回阿极统一解释和交付。
- 权限：默认只读已声明目标；运行时分析涉及本机进程、文件系统、浏览器或网络时，必须按具体任务重新授权。
- 边界：不复制 REA 的专家目录或工作流，不建立常驻 REA 服务，不把工具目录或准备契约当成真实执行结果。

## 首次真实任务的接入顺序

1. 先确认 Node.js/npm 和任务所需逆向工具的当前状态。
2. 用只读诊断确认环境；`rea doctor --json` 的结果只说明诊断观察。
3. 如确有需要，再执行 `rea setup --client codex --dry-run --json`，先审阅配置、安装和技能变更。
4. 经任务授权后才注册必要的 MCP 能力；保留实际配置变更和工具回执。
5. 用一个范围明确、优先读取型的真实目标验收，再决定是否扩大工具范围。

本文件不授权安装、全局配置修改、网络访问、进程运行或对外发布。当前未执行上述接入动作。

## 来源

- 项目：<https://github.com/morluto/rea>
- MCP 合约：<https://github.com/morluto/rea/blob/main/docs/mcp-contracts.md>
- 安装说明：<https://github.com/morluto/rea/blob/main/docs/installation.md>