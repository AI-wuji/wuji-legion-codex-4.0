# 016：Office 文档有界工作流

日期：2026-10-04。该增量补充项目内 DOCX/XLSX 的任务入口，但不把 OfficeCLI 探针扩大为通用 Office 编辑器，也不把结构通过误写成专业效果通过。

## 具体任务阻塞与最小改动

已有 `run-office` 只覆盖文本 PPTX，不能承接当前需要的新建 Word/Excel 文件任务。现有实现增加了项目内 `tools/wuji4.py run-office-doc` 入口，复用隔离工作区、显式确认、OfficeCLI 观察和配置保护边界；不新增常驻服务、第二份任务数据库、全局安装或 Codex 配置写入。

请求 schema 只允许两类有界任务：

- `word`：标题加 1–12 段纯文本正文。
- `sheet`：标题加 1–20 行，每行包含标签、整数数量和两位小数单价。

请求拒绝未声明字段、路径、宏、用户提供的公式、控制字符、越界值和会覆盖既有产物的写集。DOCX/XLSX 输出与 JSON 回执必须是独立工作区内全新的直接子文件。

## 当前结果

- **XLSX 有界成功。** 当前实现可新建受限范围的工作簿，写入受控公式及缓存值，并完成独立 OOXML 结构检查以及 OfficeCLI `validate`、`view outline`、`get` 读取回查。该结论只覆盖这条受限的生成—读取链。
- **DOCX 结构通过但整体不完成。** 当前实现生成的 DOCX 通过文本/结构检查，OfficeCLI `validate`、`view outline` 和 `get /body` 读取也通过；批准的 DOCX 渲染器无法找到允许使用的 LibreOffice 可执行文件，因此结果为 `render_unavailable`，渲染状态为 `blocked_external`，整体保留为 `failed_evidence_retained`。
- **专业效果不声明。** DOCX 的批准渲染门未通过，不能声称视觉渲染、版式质量或专业办公效果完成；XLSX 的有界成功也不能扩展为通用 Excel 编辑或专业财务验收。

## 证据口径

`render_unavailable` 是批准渲染环境缺失造成的真实证据缺口，不是把结构检查失败改写成成功，也不是允许自动切换到未批准的桌面 LibreOffice。失败回执保留已创建文件、OfficeCLI 观察和配置保护结果，调用方收到非零失败，不覆盖历史文件。

本次文档支线只更新说明文件：不改当前 Codex 配置、凭据、全局 Skill/插件挂载、代码、工具 manifest 或已有证据，不生成虚假证据。实现与测试锚点仍分别位于 `adapters/p4/office_document_workflow.py`、`adapters/p4/officecli_adapter.py`、`tools/wuji4.py` 和 `tools/test_office_document_workflow.py`。

## 不属于本增量

- 不处理既有 Word/Excel 文件的任意编辑、外部资产导入、宏执行、用户任意公式或通用排版。
- 不替代专业模板、视觉 holdout、财务正确性验收或全部 G6/G7 场景。
- 不通过修改现用 Codex 配置、安装软件、启动服务或关闭渲染门来解除阻断。
