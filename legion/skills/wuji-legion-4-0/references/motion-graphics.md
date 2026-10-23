# 动效制作专家：项目内原生运行边界

职责 ID：`p3/leaf/motion-graphics`，显示名“动效制作专家”。用于代码动效、产品动画、动画解说、可编辑 HTML/GSAP 工程，以及画面、时序、字幕、适用声音、局部评论修改和导出验收。输入是任务目标、已授权品牌/素材、目标画幅与时长、声音选择、交付目录和本地 runtime。输出包括 `index.html`、必要 assets、方向/节奏说明、关键帧、评论处理记录、导出媒体与真实检查证据。视频实拍、人物身份复制和通用视频生成不在此职责内。

## 唯一上游与发现顺序

只引用一份上游 Skill：`<ROOT>/.dev/tools/huashu-motion-0.1.1/skills/huashu-motion/SKILL.md`，具体创作规则按需从该文件进入，不复制整套角色。当前绑定是 npm 正版 `huashu-motion@0.1.1` 发布包，而非因网络失败未取到的 Git checkout；发布包身份不能证明某个 Git commit 已本地验证。上游入口是安装目录的 `cli/om.js`，无需 npm 依赖、npx 或联网下载来启动。

先确认真实消费者项目，再读 `<ROOT>/.dev/motion-graphics/runtime.json`；通过 launcher `doctor` 检查运行环境。缺文件、源码绑定不符、Node 太旧、Chrome 或 FFmpeg 缺失时停在具体缺口，交阿极补运行环境。专家不安装系统依赖、不改全局 PATH、模型配置或凭据。launcher 不承担安装、发布、制作调度或角色管理。

从仓库使用：

```powershell
node E:/wuji-projects/wuji-legion-codex-4.0/legion/skills/wuji-legion-4-0/scripts/motion-graphics.mjs --root E:/wuji-projects/wuji-legion-codex-4.0 doctor
node E:/wuji-projects/wuji-legion-codex-4.0/legion/skills/wuji-legion-4-0/scripts/motion-graphics.mjs --root E:/wuji-projects/wuji-legion-codex-4.0 help
```

从安装后的核心 Skill 使用同一个 `scripts/motion-graphics.mjs`，仍传显式 `--root`。脚本位置和调用者 cwd 不用于寻找另一份包或 manifest；相对的原生命令路径以 ROOT 为基准。`tools/wuji4.py run-motion` 由阿极维护，向本 launcher 原样转发参数；本适配器不实现第二个入口系统。安装 inventory 必须包含本脚本与本 reference，实际发布包/私有 manifest 保留在项目 `.dev`，不要把本机工具、字体归档和私有配置提交到核心 Skill。


新机器或迁移后的初始化由阿极使用仓库安装器执行，不属于日常 launcher 的隐式行为：

```powershell
python <ROOT>/tools/setup_motion_graphics.py
# 需要复用已有本机依赖时，按实际路径可选传入：
python <ROOT>/tools/setup_motion_graphics.py --node <NODE> --chrome <CHROME> --ffmpeg <FFMPEG> --ffprobe <FFPROBE>
```

该安装器负责固定 npm archive/integrity、本地解包和私有依赖准备；保留不同的已有 manifest，不隐式覆盖，也不改全局配置。先完成 setup，再用 launcher doctor 留下本机实际回执。launcher 的普通调用仍只读现有 runtime，不自动安装、下载或修复运行环境；安装器的完整实现与迁移验收由阿极负责。
## Runtime manifest（schema_version 1）

必需字段如下；阿极负责写入与锁定运行环境。所有相对路径相对显式 ROOT，绝对 node/chrome 路径可直接使用。

```json
{
  "schema_version": 1,
  "node": "C:/Program Files/nodejs/node.exe",
  "chrome": "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "ffmpeg": ".dev/motion-graphics/bin/ffmpeg.exe",
  "ffprobe": ".dev/motion-graphics/bin/ffprobe.exe",
  "source": {
    "name": "huashu-motion",
    "version": "0.1.1",
    "install_dir": ".dev/tools/huashu-motion-0.1.1",
    "archive": ".dev/tools/huashu-motion-0.1.1.tgz",
    "integrity": "sha512-RJAUfR4/kP4FwE/41xwMMTx/Ua5KAGDqg6gwUFcg2DLsLvWaZCDtzL6DYD4FuCoPgCfd+Ek/EMB/xZrwq7QjUg=="
  }
}
```

`install_dir` 必须真实位于 ROOT 的上述固定目录，直接包含 package.json 和 cli/om.js，不能重定向到用户目录。archive 必须位于项目 `.dev`，其 SHA512 必须与代码内固定 integrity 一致。每次运行都将归档内全部文件与安装内容逐个 SHA256 比较，再核对 package name/version/bin；CLI 的实际 SHA256 可由导出的 `prepareLaunch(...).binding.cli_sha256` 获取。与上游不同的本地补丁会被拒绝，应先回交阿极决定，不能隐式改源码或绕过绑定。配置的 Node 可执行文件必须实际返回 >=22 的版本，不更改宿主 Node 或全局配置。依赖文件存在仅证明前置可用，doctor 的实际输出仍须留证。

Windows FFmpeg 原文件来自 `adapters/p4/media_workflow.py DEFAULT_FFMPEG`：`E:/COMFYUI_dapao1/python_dapao313/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`。它的文件名不是 ffmpeg.exe，不能仅把其父目录放入 PATH。安装方在 `.dev/motion-graphics/bin/ffmpeg.exe` 私有 copy/hardlink，并准备同目录 ffprobe.exe；launcher 检查真实路径，不自行复制。当前 ffprobe 安装来源由阿极记录为 `@ffprobe-installer/win32-x64@5.1.0`，integrity 见 `.dev/motion-adoption-20261019/ffprobe-pack.json`，保留 `.dev/tools/ffprobe-installer-win32-x64-5.1.0` 中版权文件；本 launcher 不冒称已独立核验 ffprobe 发布包。非 Windows 对应私有 bin/ffmpeg 和 bin/ffprobe。

子进程 PATH 前置配置的 Node 目录与私有媒体 bin，Chrome 通过 OM_CHROME 指定；父进程和系统环境不变。清除子进程 NODE_OPTIONS/NODE_PATH，防止隐式 loader 改变绑定。继承其他普通环境，不启动 shell 解释传入参数。

## 参数和项目隔离

正常入口为 `node SCRIPT --root ROOT <om-subcommand> <args...>`；需要省略原生项目参数时可用 `node SCRIPT --root ROOT --project FILM_DIR <om-subcommand> <args...>`。launcher 的 root/project 参数只能放在子命令前。子命令后的数组逐项原样传给原生 CLI，所有原生 flags，包括未知 flags 的接受/拒绝，保持上游行为；不重排、不重写、不将字符串重新交 shell 解析。子命令白名单来自固定发布包，含 help/version、doctor/new/templates/demo/studio/inbox/look/done/reopen/cancel/fonts/vars/set/scan/check/still/swatch/voice/sound/render/qa/learn/samples/export/fork/undo。白名单不代表用户授权下载、使用受限素材或对外发布；`export html` 仅本地导出。

按实际项目目录定位 `.om/huashu-motion` 作为 OM_HOME。目录别名通过 realpath 归一，新目录通过现存祖先定位，不用简单名称或请求标签产生交叉污染。new/studio/inbox/render/check/voice/sound/undo 等取项目 operand；look/done/reopen/cancel 跳过 comment id；set 跳过 key=value；fonts add 跳过 family；learn harvest、export html、fork 的项目位置各按上游处理。still HTML、swatch Markdown 和 qa 视频文件默认取其父目录；对工程子目录中的这些文件，可用显式 --project 指向其真实工程祖先。fork 使用新工程目录作为经验范围。显式 --project 与实际工程 operand 冲突会非零拒绝，避免把一个项目的经验写入另一个项目。

首次创建工程前，显式 --project 的 learn 可以使用 ROOT 作为进程 cwd、仍将经验范围绑定到尚未创建的工程；依赖现有工程的 render 等则明确拒绝不存在的目录。无 project 的 learn/topics/status/add、samples、doctor 等使用 ROOT 的 `.om/huashu-motion`，不是共享用户目录。原生 learn 的 --project 也参与范围定位并原样保留。若 learn add 的上游 --project 原本只是一个说明标签，此入口要求把它写为真实项目路径，或改用前置 launcher --project。OM_SAMPLES 指向范围内 samples；子进程 HOME/USERPROFILE 也指向范围内 home，使上游不遵守 OM_HOME 的可选 TTS/ASR 缓存不写进用户共享目录。这不自动创建或安装任何模型；已有用户目录 Kokoro 环境不会被自动借用。

studio 和 inbox --wait 保持前台附着，stdin/stdout/stderr 直接继承，launcher 等待原生子进程结束。终端 Ctrl-C 或 SIGTERM/SIGHUP 会传给该子进程，信号退出转换为非零（130/143/129）。Windows 使用正常进程句柄停止，不启 detached/unref，不创建常驻服务。启动错误返回 2；正常原生失败码保留，包括 inbox 超时 3。外层宿主强杀整个 launcher 而不投递可处理信号不在可保证的停止链内；保留宿主 session/PID，必要时用现有进程管理终止，不能假称已停止。

## 最短真实工作顺序

以下以 `$L` 表示本脚本绝对路径，`$R` 表示 runtime 所在 ROOT，`$P` 表示实际工程路径。路径和值在 PowerShell 中作为独立参数传入。

```powershell
node $L --root $R doctor
node $L --root $R --project $P learn launch rhythm sound
node $L --root $R new $P --template blank
node $L --root $R studio $P --no-open
# 保留 studio 的前台 session，在另一 session 继续：
node $L --root $R inbox $P --wait --timeout 120 --json
node $L --root $R look COMMENT_ID $P
# 查看真实帧，编辑 index.html 或按变量做局部修改
node $L --root $R set 'headline=已授权的新文案' $P
node $L --root $R done COMMENT_ID $P --note '具体修改及复核结果'
node $L --root $R check $P --samples 24 --json
node $L --root $R still $P --at 0,1.5,3
node $L --root $R sound $P
node $L --root $R render $P --format mp4
node $L --root $R qa $P --json
node $L --root $R learn harvest $P
# 必要时才使用 undo，避免覆盖其后已确认修改
```

创作前采用上游方向/节奏方法并按当前目标裁剪；保留工程可编辑性。先做最难关键帧，再做其余镜头。默认 blank 和已授权的产品素材；不默认选择 storytime/demo。`THIRD_PARTY.md` 明确 `runtime/clip/lib/toon.js` 的“豆子花叔”作者形象及 storytime/demo 中的该形象仅演示使用，不授权其他用途，不能把它当 MIT 可复用人物素材。包自身 MIT 不覆盖此形象；GSAP 保留其 Standard “no charge” License，fonts 保留各字体版权与 SIL OFL 文件，按分发范围保留项目 vendor 和字体许可。

评论必须来自真实 studio；读取 inbox 和 look 的真实帧，按 comment 对象/时间局部改源码，复看后 done --note。禁止自造“用户评论”来证明真实用户验收。纯脚本测试只证明适配器参数和隔离，不证明动效质量。

## 声音、口播和验收边界

音乐/音效走原生 sound，再由 render 刷新混音。原音频导入可用 `voice $P --audio RECORDING --asr off`；原音频来源、授权和同步应实际检查。`--text` 是合成语音，不等同原音频导入：macOS say 是 macOS 系统 TTS，Windows 没有本包支持的同等 say 后端；Kokoro 需要独立 Python/venv/模型。上游默认首次合成/识别可能下载 Kokoro/whisper 大模型，不能把 voice 当无需后端的通用 Windows TTS，也不能在 README/Skill 默认触发安装或调用来补验收。只有当前用户明确要求且允许相应下载/环境准备时，阿极才处理依赖；本封装不提供自动安装。原音频需 ASR 时同样先确认 whisper 后端和模型许可；没有真实逐词证据不能标“逐词精确”。子进程私有 home 内模型也不绕过下载授权。

交付前必须跑真实 check，回读错误和警告；`--source` 或少量 samples 只覆盖相应范围，不等同完整画面 QA。打开 still/look 产物核对字体、遮挡、时序与字幕，正常速度观看成片。原生 qa 检测硬切、单帧闪烁、静滞、节奏或 loop seam 等机器可见问题；命令退出 0 也要回读其报告，不能当审美/商业质量证明。使用真实 ffprobe 独立检查分辨率、fps、时长、视频与音频流，再做 FFmpeg 解码；有音轨并不证明可听，需检查实际响度/非静音并试听，核对口播与字幕同步。没有生成口播只记“音乐/音效或原音频已测”，不可写“系统 TTS 通过”。

保留命令、退出码、stdout/stderr、工程与导出路径/hash、帧查看结果、音频检查及评论前后差异。未实测的透明 MOV/WebM/GIF、Kokoro/whisper、其他平台和安装版调用明确记未知。doctor 可用、check 无发现和测试替身通过，均不能单独宣布动效专家专业效果通过。


