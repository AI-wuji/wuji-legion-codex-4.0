# ComfyUI/ffmpeg 有界媒体任务链

日期：2026-10-04。该增量把现有 Rust/SQLite 媒体契约、ComfyUI 节点链和 ffmpeg 技术链收敛为一次性有界任务，不建设常驻媒体服务。

## 任务边界

- `tools/wuji4.py run-media` 只接受独立 `.dev` 工作区、同名声明输入和显式确认词。
- 声明输入先与现有 ComfyUI input 中的同名文件做 hash 对账；不上传、覆盖或猜测外部输入。
- 真实链为 Rust/SQLite 二进制输入注册 → ComfyUI `LoadImage -> ImageScale -> SaveImage` → ffmpeg H.264 MP4 → 独立解码检查。
- 回执绑定命令/HTTP观察、版本、输入/产物 hash、失败原因、配置保护和音频设备未打开事实。

## 当前结果

- 定向单元与实时失败处置测试通过：`tools/test_media_workflow.py`。
- 框架端到端已执行到 Rust/SQLite 输入注册；本机当前 `http://127.0.0.1:8898` 连接被拒绝，回执为 `failed_real_error/comfyui_unavailable`，进程返回非零，不冒充成功。
- 既有 `outputs/p4/comfyui-probe-evidence.json` 与 `outputs/p4/ffmpeg-probe-evidence.json` 仍只证明此前各自有界技术探针，不替代本链当前成功或专业质量 holdout。

## 失败处置

无效输入、工作区、版本、节点、HTTP、ffmpeg 或解码失败都保留 JSON 回执；不会自动启动、安装、切换工具、改 Codex 配置或打开音频设备。
