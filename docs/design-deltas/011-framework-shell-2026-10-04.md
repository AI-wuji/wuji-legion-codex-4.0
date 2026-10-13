# 4.0项目内框架外壳

日期：2026-10-04。按任务优先的v1.7继续执行。

## 目标

用户需要先得到一个可运行的4.0军团框架，再在使用中扩建专业内容。本次不增加常驻服务、第二任务数据库、通用调度器或模型宿主；把已有入口和既有Rust/SQLite任务链收敛为一个稳定的项目内命令。

## 最小实现

`tools/wuji4.py`提供六个命令：

- `status`：返回阿极入口、活动基线、按需能力、现有Rust/SQLite权威、安装/P7/常驻状态和受保护配置摘要。
- `doctor`：只读检查活动基线、入口包路径、Rust CLI、配置可读性和未安装/未常驻/P7边界。
- `capabilities`：只读展示现有专业工具的真实边界、入口、当前证据和效果声明；不提供任意工具派发或通用fallback。
- `route`：委托已有薄入口，只加载当前任务对应的Skill指引。
- `run-copy`：委托已有真实隔离文件任务，不改变动作授权和工作区边界。
- `summary`：委托现有Rust/SQLite执行摘要。

这层是框架入口，不是新的事实权威。专业判断仍由现有宿主和专业工具承担；模型请求、工具权限和Codex配置不由命令自行扩大。

## Skill要求的落地

本外壳直接落实4.0 Skill与3.0方法要求：阿极唯一沟通入口、简单任务直达、专业指引按需加载、现有工具优先、独立写集、未知不冒充完成、P7另批和不改现用配置。目录不是模型，doctor/status不是模型效果证据。

## 使用方式

```powershell
$python = 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $python tools/wuji4.py doctor
& $python tools/wuji4.py status
& $python tools/wuji4.py route engineering
```

框架自检通过后，再使用已有`run-copy`或项目内相应专业适配器；扩建其他能力时继续从真实任务、既有工具和最小缺口开始。

## 限制

此框架当前只在项目内可用，未安装到Codex自动发现目录；原生模型调度、完整专业效果、完整用户ACL和P7接入仍未完成。任何后续扩建必须保留这些未完成状态，不以框架自检通过替代全量验收。
