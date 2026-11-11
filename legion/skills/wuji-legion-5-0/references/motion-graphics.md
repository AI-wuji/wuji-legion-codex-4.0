# 动效制作专家（5.0有界消费者）

职责 ID：`p3/leaf/motion-graphics`。阿极在当前会话直接启用一个必要的动效专家分身；工具入口只负责调用已固定来源的 `huashu-motion@0.3.1`，不创建角色链、常驻调度器或模型宿主。

## 触发与边界

仅在用户已授权的代码动效、产品动画、UI 动效、动态图表、文字动画、动画解说或既有动效工程评论修改中使用。真人实拍、通用视频生成、纯提示词、普通剪辑不触发此职责。缺少事实/素材权利、目标规格、工程授权、工具或可写范围时，返回具体缺口，不推断授权、不激活其他专家。

当前证据只覆盖本机 Windows 上的代码动画创建及一次真实浏览器评论修改。它不代表配音/TTS/ASR、透明 MOV/WebM/GIF、其他平台、无人值守发布或全部视频专业效果已验收。详细本地证据在 `outputs/motion-graphics/integration-evidence.json`；该文件不入库，迁移机器或更换来源/运行时后重新观察。

## 输入与交付

输入包括任务目标、已授权的事实/品牌/素材及其权利、画幅/时长/帧率/字幕/声音要求、隔离项目目录；修改任务还需要工程版本、评论或帧位置，以及必须保留的内容。

交付可编辑 HTML/GSAP 工程、获准的导出文件、局部评论修改记录、实际检查结果、路径与 SHA-256。真实执行后核对源工程、导出、帧/时序和适用音轨；未执行的项目写 `unknown` 或 `not_run`。自动检查不能替代完整人工观片或试听。

## 本地工具入口

运行前必须有项目私有 `.dev/motion-graphics/runtime.json`，其中固定 Node、Chrome、FFmpeg、FFprobe 路径，并有 `.dev/tools/huashu-motion-0.3.1.tgz` 和对应解包目录。当前锁定 GitHub 正式标签 `v0.3.1`（commit `52467f99c602b76ba86d511d37acdfe93fa1e16e`），再由本地 npm pack 生成固定 SHA-512 归档；npm registry 的 `latest` 仍是 `0.1.1`，所以不把旧 npm 发布版误作 GitHub 最新版。旧 `0.1.1` 归档与解包目录保留作本机回退。launcher 会核验归档完整性、已安装文件与私有运行时路径；它不安装系统依赖、不改全局 PATH、不启动常驻服务。

项目级配套 Skill `huashu-art-motion@1.2.0` 安装于 `.agents/skills/huashu-art-motion/`。两者配合使用但没有硬依赖：Motion 负责可编辑项目、预览、评论和渲染，包内自带一部分 Art Motion 内容；独立 Art Motion 是更完整的风格与镜头语法素材库。按任务只读一张相关风格卡或语法卡，不整本加载。制作常规产品开场/代码动效默认走 Motion；整片需要艺术风格、口播驱动的多镜头画面或特定动画语法时，再按需让 Art Motion 提供画面方案与场景素材。Windows Codex Desktop 是否会自动发现仓库级 `.agents/skills` 尚未实测；有公开的同类发现问题报告，不把文件已安装等同于已自动激活。

本机 Art Motion 1.2.0 含有针对上游 issue #11 的项目本地兼容补丁：`P.film`、`P.lensFlare`、`P.vignette`、`P.kirbyShade` 改用实际画布中心。2026-11-04 在 Windows 上对 `33_rubberhose` 和 `35_shinkai` 做了 1080×1920 单帧渲染；引擎和效果路径出图成功，但 `35_shinkai` 样例仍是横屏构图、下半屏留空，因此不算竖屏画质验收。上游 issue 仍开放，今后更新 Skill 时需保留或复核此补丁；WSL 不需要用于当前已通过的 Windows 核心链路。

## 当前版本实测边界

2026-11-04 在 Windows 上以单浏览器完成 `doctor → new → look --at → render --workers 1 → qa`。隔离工程成功导出 1920×1080、24fps、8 秒 MP4，`look` 真实生成了 PNG，渲染通过；示范工程的 `qa` 对停帧和硬切有提示，该示范只用于验证工具链，不作为成片质量验收。上游全量测试 154 项：139 通过、6 失败、9 跳过；失败包括 Windows 专用路径/命令假设、性能阈值、示例音乐语法和较慢的素材抽取/MOV/WebM/GIF 渲染超时。因此本次只确认 Windows 单工 MP4 核心链路；并行渲染、这些导出格式及新版本评论修改尚未重新准入。旧版本的一次真实浏览器评论记录不能自动证明新版本同样通过。

首次安装时，如果 `.dev/tools/huashu-motion-0.3.1.tgz` 尚未缓存，先通过本机 FluxDown 下载锁定提交的源码 ZIP：向 `http://127.0.0.1:17800/download` 发送带 `X-FluxDown-Client: codex` 的 POST JSON，`url` 为 `https://codeload.github.com/alchaincyf/huashu-motion/zip/52467f99c602b76ba86d511d37acdfe93fa1e16e`。等待 FluxDown 任务完成后，将实际保存路径传给安装器；安装器会核对归档目录、包名、版本和最终 npm 包 SHA-512，不自行联网下载。已缓存归档时无需再提供 ZIP。

```powershell
# First-time project-local setup; never installs global tools.
python legion/skills/wuji-legion-5-0/scripts/setup_motion_graphics.py --root E:/wuji-projects/wuji-legion-codex-4.0 --ffmpeg E:/path/to/ffmpeg.exe --motion-source-zip E:/path/to/completed-fluxdown-archive.zip

node legion/skills/wuji-legion-5-0/scripts/motion-graphics.mjs --root E:/wuji-projects/wuji-legion-codex-4.0 doctor
node legion/skills/wuji-legion-5-0/scripts/motion-graphics.mjs --root E:/wuji-projects/wuji-legion-codex-4.0 help
```

需要用户输入或真实交互的命令继承当前终端；launcher 会转发退出码。只在当前任务授权的工程和输出范围内写入。首次下载、付费服务或对外发布均需单独授权。
