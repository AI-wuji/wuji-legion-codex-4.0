# OfficeCLI 有界任务链

日期：2026-10-04。该增量把已有 OfficeCLI 适配器接到项目内框架，但不把文档探针扩大为通用办公或设计能力。

## 任务边界

- `tools/wuji4.py run-office` 只接受独立 `.dev` 工作区和显式确认词。
- 适配器只创建新的文本 PPTX，执行 `create/add/get/set/view/close`，禁止外部资产、全局配置、安装、自更新和常驻。
- 回执绑定命令退出、产物 hash、受保护配置前后 hash、独立 OOXML 检查和失败/不重试状态。
- 成功只表示有界原生可编辑文本 PPTX 链通过；专业设计质量、Word/Excel 公式、视觉 holdout 与 P7 仍未声明。

## 证据

- 实现：`adapters/p4/officecli_workflow.py`
- 定向测试：`tools/test_officecli_workflow.py`
- 框架入口测试：`tools/test_wuji4_framework.py`
- 真实回执留在对应 `.dev` 隔离工作区；成功任务不覆盖既有文件。

## 失败处置

原生动作失败保留已观察命令和当前产物，不盲重试、不覆盖原文件；路径、版本、receipt 和保护配置不满足时在执行前拒绝。
