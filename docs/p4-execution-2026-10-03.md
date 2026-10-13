# P4 工具适配与重点工作流执行报告

日期：2026-10-03。按顺序优先检查 ComfyUI/通用研发；不安装、不联网变更、不修改用户设备或 Codex 配置。

## 已完成

- 新建 `catalog/p4/tool-manifests.json`，为 ComfyUI、OfficeCLI、视频、音频和本地软件研发适配器记录 owner、版本/来源、权限、失败、恢复和运行准入。
- 新建 `adapters/p4/software_repair_adapter.py`，在项目测试工作区内调用固定 DAG validator，输出绑定 artifact hash、validator hash、运行时与逐项结果的证据报告。
- 对 P2/u 的真实 native engineering 产物执行一次本地有界验证，报告为 11/11 tests passed；这证明本地适配器链，不证明 ComfyUI 或专业模型有效性。
- `tools/test_p4_adapters.py` 的 2 项测试通过。
- 已发现并只读使用本机已运行的 ComfyUI `0.37.0` 服务；真实执行 `LoadImage -> ImageScale -> SaveImage`，生成并独立校验 `64x64` PNG，证据为 `outputs/p4/comfyui-probe-evidence.json`。这只是有界节点链证据，不是专业效果或完整 G4 通过。
- 已使用本机 ComfyUI 环境内已有的 ffmpeg `7.1` 二进制生成 1 秒 H.264 MP4，并用 ffmpeg 解码到 null 独立复核，证据为 `outputs/p4/ffmpeg-probe-evidence.json`。这是技术探针，不是专业剪辑/音频效果或完整 G4 通过。

## 阻断

当前 ComfyUI 与 ffmpeg 有界技术链已可用；OfficeCLI、REAPER 和批准的音频入口仍不可用，没有安装授权。已安装 Microsoft Office 不能冒充 OfficeCLI。音频、专业剪辑和质量 holdout 未完成，不能宣称 G4 通过。

证据：`outputs/p4/software-repair-u-evidence.json`、`outputs/p4/comfyui-probe-evidence.json`、`outputs/p4/ffmpeg-probe-evidence.json`；清单：`catalog/p4/tool-manifests.json`。
