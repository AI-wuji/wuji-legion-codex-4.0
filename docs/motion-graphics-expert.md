# 动效制作专家

职责 ID：`p3/leaf/motion-graphics`。该职责负责产品动画、UI 动效、动态图表、文字动画和代码动画解说，交付可编辑工程、成片和真实检查结果。单个明确动效由阿极直接调用；需要组织的任务由现有 `lead.video` 使用 `motion-graphics-delivery` 配方调用，不新增主帅或常驻调度器。

## 实际入口

核心 Skill 的 [专业指引](../legion/skills/wuji-legion-4-0/references/motion-graphics.md) 同时包含职责、输入输出、原生命令、项目隔离和验收约束。仓库入口和安装版核心 Skill 都使用同一个薄 launcher，逐次验证固定 npm 归档及全部安装文件，参数和失败码交给原生 CLI。

```powershell
# 第一次准备项目私有运行环境；仅此步骤按需下载固定发布包。
python tools/setup_motion_graphics.py

# 后续可直接通过军团入口使用原生命令。
python tools/wuji4.py run-motion doctor
python tools/wuji4.py run-motion new outputs/my-motion
python tools/wuji4.py run-motion studio outputs/my-motion --no-open
python tools/wuji4.py run-motion check outputs/my-motion
python tools/wuji4.py run-motion render outputs/my-motion --fps 24

# 安装后的核心 Skill 也可从其他 cwd 调用；显式 ROOT 绑定实际项目。
node C:/Users/Administrator/.agents/skills/wuji-legion-codex-4-0/scripts/motion-graphics.mjs --root E:/wuji-projects/wuji-legion-codex-4.0 doctor
```

普通用户只需说“给我的产品制作一支动画介绍片”或“把这组数据做成动画解说”。阿极确定本次输入、风格、时长、画幅和声音后，按需进入此职责；无需用户记住底层包名。

依赖固定为作者发布的 `huashu-motion@0.1.1`，不是未成功下载的 Git checkout。npm archive 的 SHA512 和 253 个安装文件逐项校验；保留原有 GSAP、字体和其他组件许可，不默认采用仅演示授权的作者人物形象。Node、Chrome、FFmpeg、FFprobe 使用项目绑定，PATH/HOME/经验目录仅对子进程和当前项目生效。首次声音模型或采样下载、付费和外部发布不从工具安装授权中推导。

## 已执行的本机验收

2026-10-19 在 Windows 上使用现有原生子代理完成了 `lead.video plan → 动效制作专家 execute → 真实产物/hash 输入门 → lead.video aggregate`。一次性角色桥调用现有 `execute_delegation`，不是 fixture 或另一个模型宿主。明确的后续局部修改复用同一专家，按最短链执行。

实际作品为 `outputs/motion-graphics/wuji-intro`：18 秒、1280×720、24fps，保留本地可编辑 HTML/GSAP、合成配乐和音效，导出 H.264/AAC MP4。首版与修改版分开保存。Tabbit 在真实编辑器 16.5 秒处点中 `end-title` 提交评论，专家经 inbox/look/set/done 处理后导出第二版；独立探测、完整解码和关键帧检查分别记录。

当前角色与工具的有界证据入口是 `outputs/motion-graphics/integration-evidence.json`，详细作品检查是工程内 `delivery.json` 与 `revision.json`。这些是本机实际执行记录，按仓库规则不提交生成的媒体、本机配置或审计日志。迁移机器后重新执行 setup/doctor 和实际消费者验收，不能复制本机准入结论。

修复前独立复核发现过 undo 命令遗漏和 Python option-first 参数转发问题，修复后的真实 undo 逐字节恢复、原生失败码保留、前置 --project 扫描及安装文件一致性均已核对。原失败记录保留，未用新结论改写。旧 P3 冻结生成器会拒绝覆盖新增消费者角色，避免重新生成时悄悄丢失本专家；它不具备扩展角色的重建能力。

## 边界

本次只证明当前 Windows 运行环境、代码动效制作和一次真实评论修改。自动检查的容器级警告和低运动提示留在作品记录中；关键帧可读、源结构检查与解码通过不能代替人工试听或完整正常速度观片。生成口播/TTS/ASR、透明 MOV/WebM 和其他平台未做本次实测，使用时另核依赖与产物。不扩大为全部 58 项职责、所有视频任务或商业级效果保证。
