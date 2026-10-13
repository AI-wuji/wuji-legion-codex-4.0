# 无极军团4.0：当前怎么用

日期：2026-10-05。活动方案v1.7。核心入口已接入Codex；下文区分当前可用入口与仍待按需扩展/验收的专业能力，不宣称全量4.0已完成。

## 先理解入口

全局入口是`C:/Users/Administrator/.codex/AGENTS.md`与用户已授权的4.0 developer入口，让每个新Codex对话默认按阿极与懒人行动规则工作，不需口令；已有新会话输入检查记录，不冒充模型行为测试。4.0核心Skill安装在`C:/Users/Administrator/.agents/skills/wuji-legion-codex-4-0`，3.0运行挂载已撤销，不共存。最新记录见`outputs/p7/global-4-only-cutover-2026-10-05.json`；复杂任务按需引用相关指引和现有工具。

入口可直接使用；无需运行本项目CLI来激活。全量95项仍是能力验收账，不是预先建设清单或开始使用的前置条件。当前全量P6审计尚未通过；没有证据的专业场景仍按未完成处理，后续遇到真实任务时再复用/适配。

## 项目内辅助工具（不是激活步骤）

普通使用直接向Codex提出需求，不必运行以下命令。MCP和专业应用不预先遍历或验证，用到时再按该任务范围复用和检查。 REA 只由 software-reverse 专家在真实逆向任务中按需接入，当前没有安装或注册。接入边界见 docs/rea-reverse-specialist-integration-2026-10-10.md。

项目内框架外壳见 `tools/wuji4.py`。它不是新调度器，而是把入口、自检、按需路由和已有Rust/SQLite任务链收敛到一个调用面：

```powershell
$python = 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $python tools/wuji4.py doctor
& $python tools/wuji4.py status
& $python tools/wuji4.py capabilities
& $python tools/wuji4.py route engineering
```

`doctor`只读检查当前项目；`status`不会启动模型或常驻服务；`route`只加载请求类别的指引。通过后再调用`run-copy`或既有专业工具。本轮已在 `.dev/legion-task-workspaces/framework-smoke` 实际完成一条文件任务。详细边界见 `docs/design-deltas/011-framework-shell-2026-10-04.md`。

### 当前本地缺陷返工

已有Rust/SQLite有界任务的`revise`用于明确用户计划变更，`repair`用于已有真实文件/输入失效证据的局部返工。`repair <workspace> <sealed-plan.json> <expected-revision> <event-id>`只接受当前未解决失效节点及其依赖后继，不接受JSON自称“发现问题”来授权返工，也不能借改节点ID、事件ID或预算绕过单节点修订与无进展上限。正常用户改版不会被无进展返工计数误伤。执行后仍须实际写入、独立验证和关闭；命令准备成功不表示任务完成。

丢失且已失效的产物可以在原路径重新生成，保留原产物和验证历史；活动产物路径仍唯一，磁盘上已有文件仍拒绝覆盖。工作区数据库当前版本为7：只有已有可信SID绑定的版本6，才能经显式初始化入口`init`（`Store::open`）在事务内升级产物历史索引；观察入口`Store::open_existing`不迁移。未绑定、撤销、未知列/索引或坏外键拒绝升级，不静默认领owner，不改旧库字节，也不重写旧任务的固定程序引用。

## 框架接入的专业有界任务

当前用户要求只修核心，不运行下面的专业软件命令；以下保留为按需接口文档，不是本轮执行清单。开发者运行 `python tools/run_audit_tests.py` 或 `python tools/run_p6_regressions.py` 时默认只加载显式核心测试；`--include-software-tests` 会扩大至软件测试，须有相应任务授权，本次不使用。

OfficeCLI 文本 PPTX 链已接入框架，可在新的独立工作区运行：

```powershell
New-Item -ItemType Directory '.dev/legion-task-workspaces/office-task' -ErrorAction Stop
& $python tools/wuji4.py run-office '.dev/legion-task-workspaces/office-task' `
  confirm-isolated-officecli-task --output office-receipt.json
```

该命令只创建新 PPTX，并把真实命令、OOXML 检查、hash 和配置保护写入回执；不代表专业设计效果。Office 文档链和媒体链分别使用下面的独立入口。

### Office 文档（DOCX/XLSX）有界链

`run-office-doc` 只接受新的 `.dev/legion-task-workspaces/<独立任务>` 工作区、严格的内联 JSON 请求和显式确认词。例如，下面的请求创建一个新的 XLSX：

```powershell
New-Item -ItemType Directory '.dev/legion-task-workspaces/office-document-task' -ErrorAction Stop
$request = '{"schema_version":1,"kind":"sheet","title":"Project Cost Summary","rows":[{"label":"Research design","quantity":2,"unit_price":"120.50"}]}'
& $python tools/wuji4.py run-office-doc '.dev/legion-task-workspaces/office-document-task' `
  $request confirm-isolated-office-document-task --receipt office-document-receipt.json
```

请求只支持 `word`（标题加 1–12 段正文）和 `sheet`（标题加 1–20 行标签、整数数量、两位小数单价）；不接受未声明字段、路径、宏或用户提供的公式。输出、回执都必须是该工作区的全新直接子文件，不覆盖既有产物，不改全局配置，不安装或启动常驻服务。

- **XLSX：有界成功。** 当前实现可以新建受限范围的工作簿，生成受控公式和缓存值，并通过独立结构检查以及 OfficeCLI 的 `validate`、`view outline`、`get` 读取回查。这个结果只证明该有界生成与读取链，不等于通用 Excel 编辑能力或专业财务效果。
- **DOCX：不宣称完成。** 当前实现可以生成 DOCX；结构检查和 OfficeCLI 的 `validate`、`view outline`、`get /body` 读取通过，但批准的 DOCX 渲染器找不到允许使用的 LibreOffice 可执行文件，回执为 `render_unavailable` / `blocked_external`，整体保留为 `failed_evidence_retained`。不会改用未批准的桌面程序绕过该门，也不能据此声称视觉渲染、版式质量或专业效果完成。

该 Office 文档增量的完整边界见 `docs/design-deltas/016-office-document-workflows.md`。媒体链使用同名声明输入，并要求它与现有 ComfyUI input 文件 hash 一致：

```powershell
New-Item -ItemType Directory '.dev/legion-task-workspaces/media-task' -ErrorAction Stop
Copy-Item 'E:/COMFYUI_dapao1/ComfyUI/input/example.png' `
  '.dev/legion-task-workspaces/media-task/example.png'
& $python tools/wuji4.py run-media '.dev/legion-task-workspaces/media-task' example.png `
  confirm-isolated-media-task --output media-receipt.json
```

媒体命令只在现有 ComfyUI 服务可用时继续到节点执行；服务不可用会保留 `failed_real_error` 回执并返回非零，不自动启动服务、不安装、不改 Codex 或音频设备。详细边界见 `docs/design-deltas/012-officecli-workflow-2026-10-04.md`、`docs/design-deltas/013-media-workflow-2026-10-04.md` 和 `docs/design-deltas/016-office-document-workflows.md`。

已有 PNG 只需要编码成短视频时，直接使用独立 `run-video`，不绕行 ComfyUI：

```powershell
New-Item -ItemType Directory '.dev/legion-task-workspaces/video-task' -ErrorAction Stop
Copy-Item 'outputs/p4/comfyui-probe-output.png' '.dev/legion-task-workspaces/video-task/source.png'
& $python tools/wuji4.py run-video '.dev/legion-task-workspaces/video-task' source.png `
  confirm-isolated-video-task --receipt video-receipt.json
```

这些工作区名称必须尚不存在；重复任务请使用新的独立名称，不覆盖历史回执或产物。视频链仅证明声明 PNG → 一秒、八帧、无音频 H.264 MP4 → 独立进程解码。输入最多 8 MiB、偶数宽高 2–2048，输出和回执必须是工作区直接子文件；不覆盖、不安装、不切换工具、不作为媒体失败的自动后备，不代表专业剪辑、声音或全视频验收。真实示例见 `outputs/p4/video-framework-workflow-evidence.json` 与 `outputs/p4/video-framework-output.mp4`。

## 查看任务所需指引

在本项目根目录使用已有Python：

```powershell
& 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' tools/run_legion_task.py route engineering
```

支持 `chat`、`rewrite`、`engineering`、`research`、`documents`、`media`、`evolution`。简单任务只返回入口，专业任务只增加一篇对应reference；结果含当前字节、hash和未做事项。`guidance_loaded_not_executed` 不代表模型已执行、工具已获权限或专业效果通过。

## 已能实际运行的有界文件任务

现有Rust CLI完成UTF-8文件复制、当前hash/内容核验、任务摘要和幂等重放。它不是任意shell、代码生成器或模型专业任务替身。只允许现存 `.dev/legion-task-workspaces/<独立任务>` 和 `.dev/core-test-workspaces/<独立测试>` 工作区；工具链、runtime目录、项目根目录和外部用户目录不能作为入口工作区。

已有本轮示例工作区 `.dev/legion-task-workspaces/first-usable-task`；输入是明确标记的本地测试材料：

```powershell
$python = 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $python tools/run_legion_task.py run-copy '.dev/legion-task-workspaces/first-usable-task' 'first-usable-task' 'source.txt' 'result.txt' 'confirm-isolated-legion-file-copy'
& $python tools/run_legion_task.py summary '.dev/legion-task-workspaces/first-usable-task' 'first-usable-task'
```

只有最后的明确范围确认才启动此本地动作，指引或业务JSON不能授权执行。Rust/SQLite仍是唯一任务状态权威，没有另建任务数据库。输入、任务ID和写集相同的重放不产生第二次实际调用；修改已验证输出后，当前摘要不再称完成。需要更改任务时应新建独立任务或使用已有明确版本机制，不靠改配置或覆盖历史解除冲突。

实际产物与回执见 `outputs/p2/legion-first-task-receipt.json`、`outputs/p2/legion-first-task-source.txt`、`outputs/p2/legion-first-task-result.txt`。工作区数据库保留在.dev，不打包进发布资料。回执只证明此本地UTF-8任务，不证明模型修复、Word/Excel/全媒体链或全量95项验收。

## 经验如何使用，什么不算自动学习

现有Rust资源入口将知识依据与经验候选分型，候选必须明确隔离复核后才可按精确trigger查询；候选文本或查询结果都不授予执行权限。后续相关任务仍需核对scope、精确版本、当前证据和反例，再实际采用方法。只保存候选、命中查询或写一句“已学习”不算任务采用，也不会自动变成通用规则或全球发布。

本轮实际方法是manifest护栏：在加载指引前拒绝重复权限键及installed、automatic_discovery_enabled、P7真值。它已用于本项目后续修复与回归，真实历史回执见 `outputs/p5/legion-experience-task-receipt.json`。

该示例的证据已刻意变更，用于证明新进程会拒绝旧经验；不要恢复旧证据来冒称它现在有效。查询可使用：

```powershell
& '.dev/runtime-target/debug/wuji4.exe' resource-query 'E:/wuji-projects/wuji-legion-codex-4.0/.dev/legion-task-workspaces/experience-first' experience 'legion-route-manifest' 8
```

期望当前entries为空并保留失效原因。完整用户身份/ACL、自动模型进化、公共晋升和跨域专业效果尚未完成，不以项目隔离或本地测试替代这些能力。

## 后续交付边界

研发、研究、办公、媒体及经验指引已新写，但真实工具执行、专业holdout和全范围验收分别记账。正式状态看 `outputs/p6/acceptance-execution.json` 与 `outputs/p6/remaining-work.json`；一条示例成功不能关闭所有门。

历史全局切换仅改动用户已授权的入口区块及Skill挂载，保护其他配置；本次核心收尾不再修改Codex配置、凭据、全局Skills、插件或音频设备。不自动付费、发布、推送、清理用户文件或关机。
