# P0 安装态差异与P7精确恢复清单

日期：2026-10-03。本文件承接v1.6第19.1.1节，只有只读观察与后续动作边界，未执行切换、卸载、配置写入或恢复。机器证据见 `outputs/p0/host-capabilities.json` 的 `installation_observation`。

| 对象 | 本轮观察 / 有效层 | Owner与语义处置 | P7恢复要求 |
|---|---|---|---|
| C:/Users/Administrator/.codex/config.toml | 本机文件存在；白名单字段与整文件hash已记录；有效生成配置未证实 | 用户配置；provider、认证与无关字段禁止改动；不得整文件覆盖 | 获批后仅拟改字段保存无秘密快照及before/installed hash；用户并行改动触发三方比对 |
| config中的developer_instructions | 临时脱敏阅读完成；11语义组覆盖43非空行hash；未保存原正文/秘密 | 保留兼容白帽/唯一入口/预算；重写3.0身份、静默降档、默认staff及媒体偏好证据边界；不整段删除 | 语义diff已保存，patch/inverse_patch仍待P7精确版本与授权，不凭本清单实施 |
| C:/Users/Administrator/.codex/AGENTS.md、AGENTS.override.md | 本轮明确检查均不存在 | 不自行创建全局覆盖 | 若部署前新出现，重新核所有权、hash和作用范围 |
| C:/Users/Administrator/.agents/skills/wuji-legion-codex-3-0 | Junction，实际指向E:/wuji-projects/wuji-legion-codex-3.0 | 当前3.0登记，P7前保留；不能把链接目录当4.0已安装 | 获批后记录链接类型、精确目标、入口hash及逆向切换；不递归删除目标项目 |
| C:/Users/Administrator/.codex/skills/wuji-legion-codex-3-0 | 本轮该精确路径不存在 | 不推断其它别名一定不存在；已检相关目录名 | 若P7发现别名必须先识别，不能批量清理Skills |
| 3.0/AGENTS.md、3.0/.codex/config.toml | 原项目只读保留；项目配置存在 | 历史项目所有者；不通过修改旧配置证明4.0隔离 | 不纳入4.0逆向覆盖 |
| 4.0/AGENTS.md及v1.6 baseline manifest | 全新项目规则，当前目录执行约束 | 4.0建设文件；原实现/配置/数据库/测试未移植 | 发布后按精确版本/hash对账 |
| C:/Users/Administrator/.codex/plugins | 仅目录级和配置白名单观察；军团专属注册ID未证实 | 共享插件cache、启停、市场引用本轮均不动 | P7先定位注册ID/owner/目标；无法确认就停止该项，不删除共享cache |
| model_catalog_json、profiles、agents.*及预算 | 配置观察不等于真实请求；不依赖历史profiles有效性 | 请求模型固定6.1-sol；逐调用medium/high/xhigh挂载点已核，实际有效值仍unknown | 保留目录/provider及无关预算；实际请求后才允许校准必要字段 |
| Codex/3.0数据库、缓存、在途任务 | 本轮未打开数据库或接管任务 | 不复制、不清空、不迁移；4.0后续独立SQLite状态 | 无权强杀用户进程；真实关闭/未知动作分别处理 |
| provider凭据、认证、素材、音频设备、无关Skills/plugins | 不读取输出凭据，不变更音频/设备/启停 | 用户所有；本轮不涉及发布、外发或付费 | 恢复快照也不得复制秘密或扩大授权 |

## 当前接线决定

采用官方CLI支持的逐调用`--model gpt-6.1-sol`与`--config model_reasoning_effort=...`作为设计挂载点，不为证明profile层改写全局配置。外部文档与本机帮助只证明接口形状，不证明本用户第三方请求生效、并发释放或实际模型身份。

## 未闭合项

- developer_instructions条款级语义diff已保存到统一来源账和host-capabilities的installation_observation；不是实际有效层或安装/恢复完成证据。
- 插件/快捷入口的军团专属注册与实际有效指令层仍需准确定位，目录存在不等于启用或真实调用。
- 快照、installed hash、逆向patch与恢复演练只能在P7授权和实际拟安装版本确定后形成；当前未创建含秘密的配置副本。
- 当前G0通过依据完整来源/设计输入审查，不由本清单自动放行；P7/G7仍未授权。部署失败或用户并行修改时停止冲突项，保留用户新变更，不整文件覆盖。
