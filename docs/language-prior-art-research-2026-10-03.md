# 语言与融合兼容性：已有实践优先的全网研究

日期：2026-10-03。用户要求：先检索已有想法、工程实践及验证结果；找不到足够适用依据时才自行验证。该原则也用于今后4.0的问题处理。

## 结论

“强类型小核心＋多语言专业层/工具协议”不是未经验证的新想法。Temporal Core、Codex、Goose、Restate提供不同形态的公开实现先例；Go服务与Python编排也存在成熟路线，不能把语言偏好变成语言优劣的绝对排名。

这些证据足够支持把Rust小核心与多语言融合选为4.0的推荐技术路线，不必先自己写Go/Rust两套原型，重新证明该类架构是否可行。本次取消前一报告建议的默认本地语言/兼容性/性能验证工作包。

推荐仍然是：一个Rust确定性小核心＋SQLite事务状态＋专业项目保留原生态，优先通过已有MCP/CLI/API接入；仅在确有必要时用小范围FFI。历史待批状态已于2026-10-03被用户“先修订1.5再执行”替代；当前执行基线v1.6已采用该路线，原v1.5只读保留。没有新增依赖安装、执行实验或生成核心代码。

不能从这些先例推出“Rust一定比Go快多少”“4.0一定获得同样速度”“本机适配器已经成功”。本轮找到的是同类架构的公开实现和作者经验，未找到本项目同输入同边界的比较数据；这种数据不是当前架构选型必须重造的前置工作。

## 1. 与想法高度匹配的先例

### Temporal Core：共享Rust内核与不同语言层

作者文章元数据发布日期是2021-04-20。它解释采用Rust共享核心的考虑：跨语言接入、内存/线程安全及SDK维护成本。历史文章里的计划与当前实现需分开。

当前sdk-rust README明确列出Core被TypeScript、Python、.NET、Ruby SDK采用。架构正文说明Core与语言层分开，TS/JS用Neon，Python用PyO3，其它语言可通过C绑定。这直接回应“核心写Rust会不会妨碍融合其它语言”。历史文中关于Go接入的规划不能当成当前Go SDK已迁移的事实。

可借鉴：共用确定性语义，专业层保持语言生态，接口与取消/回执边界清楚。不能据此把Temporal服务或它的完整FFI架构搬进军团。

来源：
- https://temporal.io/blog/why-rust-powers-core-sdk
- https://raw.githubusercontent.com/temporalio/sdk-rust/main/README.md
- https://raw.githubusercontent.com/temporalio/sdk-rust/main/ARCHITECTURE.md

### Codex：近似本地代理工具已有Rust核心与SQLite声明

官方codex-rs Cargo workspace中包含CLI、core、MCP等组件，并声明启用SQLite的SQLx依赖。这是与本地AI执行工具相近的公开源码先例，足以支持Rust与SQLite组合可采用，不需另写小实验才承认可行。

不能由依赖声明推导全部组件运行效果、具体吞吐或同本项目的性能收益；也不复制Codex实现或照搬它的全部依赖。SQLite库仍按短进程、同步事务和最小依赖需求选，不因Codex用SQLx就自动替换原候选。

来源：https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml

### Goose：Rust代理应用通过MCP扩展

当前项目README声明它以Rust构建，提供桌面/CLI/API形态并通过MCP连接扩展。该案例支持“执行核心不必与每个工具相同语言，扩展可以沿标准接口组织”。

可借鉴MCP扩展边界，不采用第二代理宿主、模型路由或常驻运行规则。它的扩展数量、供应商范围和平台声明不转化为4.0自身支持清单。

来源：https://raw.githubusercontent.com/aaif-goose/goose/main/README.md

### Restate：Rust运行层与多语言服务

其Cargo workspace声明Rust工程；官方服务文档给出TypeScript、Java、Python、Go的处理器与工作流示例。这是另一个“运行层与应用语言分开”的先例。

其运行形态与军团的短进程/无常驻约束不同，不导入完整平台。Cargo声明BUSL-1.1，不能当作已准入运行依赖或默认可复制资产；本次只引用设计与公开案例，许可采用另处理。

来源：
- https://raw.githubusercontent.com/restatedev/restate/main/Cargo.toml
- https://docs.restate.dev/concepts/services/

## 2. 相反路线：Go/Python并非低质量选项

Temporal服务当前go.mod表明服务端仍是Go工程。LangGraph官方Python文档提供持久执行、状态与人工介入等编排能力。这些先例反对“代理/调度程序只有Rust能高质量实现”的泛化。

4.0偏向Rust的理由应限定为：当前从零重写、用户倾向强质量/效率、核心需要严格身份/状态/资源约束，同时外部工具保持多语言。Go是可行方案；Python生态适配也不该被语言偏好牺牲。不能把Rust选择当作3.0问题的自动修复。

来源：
- https://raw.githubusercontent.com/temporalio/temporal/main/go.mod
- https://docs.langchain.com/oss/python/langgraph/overview

## 3. 对前一方案的修正

- 删除“先写跨语言协议探针或Go/Rust性能对照才能选型”的默认要求；已有高匹配工程先例足以结束架构可行性研究分支。
- 先复用现有标准和工具接口，不为每个外部项目发明新的总线，不强制统一改写语言，也不默认安装完整框架。
- 外部采用证明与性能测量证明分开；不写速度倍数，不声称所有融合都零成本。
- 精确版本、必要依赖和许可通过资料与上游信息核查；只对真的影响决定而仍无外部依据的缺口考虑最小验证。
- 本地最终成果与宿主执行状态仍如实记账，不将他人测试登记成4.0已运行；这不是要求重新验证公开架构结论。

## 4. 今后4.0统一处理顺序

问题/想法 → 查单一来源账内有效结论 → 全网找同类成功与失败案例 → 原始依据及当前实现 → 约束匹配 → 直接复用或有理由调整 → 只有决定性缺口才做最小验证。

有用已有结论按出处、适用环境、版本、反例、scope和消费者进入来源/进化链。不是另建一个研究数据库，不把每轮研究做成常驻模型或多评委会议。简单任务直接完成，已有有效结论不重复搜索。

已写入AGENTS及docs/adr/001-research-before-experiment.md。它现在是建设约束与待实现的运行设计，不是4.0核心已具备该行为的证明。

## 5. 搜索范围与限制

使用公开网络搜索定位同类项目，并读取作者文章、官方文档及当前公开源码。部分搜索接口返回空内容，Bing RSS若干结果与问题不相关，均未作为结论证据。没有宣称遍历整个互联网或完整审计这些项目；达到本次问题的证据覆盖后停止扩展。

采用结论的证据类型是原始设计说明、公开实现及作者列明的实际使用范围，不是独立复现的性能评测。README里的广泛采用或平台支持只能支持其声明范围，不能证明本机授权、免费额度或具体工具交付。

公开检索没有上传用户源码、原始资料、私有URL或凭据。本轮没有运行本地验证、安装、付费或修改旧项目。
