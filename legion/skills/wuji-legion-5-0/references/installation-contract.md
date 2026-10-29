# 5.0安装与状态契约

本文件定义项目源与 Codex 全局安装之间的边界。它是部署前检查清单，不是权限授予，也不要求当前任务立即修改用户目录。

## 状态含义

- `project_entry_active=true`：本仓库中的 5.0 项目入口可作为当前项目的活动规则。
- `installed=true` 且 `automatic_discovery_enabled=true`：只有在目标 Codex 全局目录完成安装并回读确认后才可使用。
- `global_installation_status=external_per_codex_home_verification`：全局安装状态不写入共享项目源；针对某个 Codex 用户目录的部署结果需独立回读记录。
- Skill 目录存在、manifest 可解析或本地 CLI 路由成功，都不能单独证明新 Codex 对话已经加载全局规则。

## 部署目标

部署时只处理以下两类目标：

1. 全局 `AGENTS.md`：使用本包的 `global-agents.template.md` 作为稳定行为基线；若目标文件已存在，先合并并保留用户已有的非军团规则。
2. 用户 Skill 目录中的 `wuji-legion-5-0/SKILL.md` 及其 references：按完整目录复制，保留标准 frontmatter 和相对引用。

不得覆盖无关的 `config.toml`、模型/provider、凭据、插件、MCP、设备设置或其他用户 Skill。4.0目录不作为5.0部署源，也不作为兼容运行入口。

## 最低部署验收

部署完成后必须逐项回读：

1. 目标 `AGENTS.md` 存在，并且 5.0 规则已合并而不是整文件替换。
2. 目标 `wuji-legion-5-0/SKILL.md` 存在，frontmatter 的 `name` 与 `description` 可解析。
3. Skill references 全部存在，路径未越界，内容为 UTF-8。
4. 项目源与目标 Skill 文件的相对路径、字节长度和 SHA-256 一致。
5. 新建或刷新一个 Codex 会话后，只观察 5.0 规则是否被遵循；不把文件存在、提示词回显或本地 fixture 当作运行验收。

任何一步失败都保留失败状态，不把 `pending` 改写为 `installed`，也不自动重试可能产生副作用的安装动作。
