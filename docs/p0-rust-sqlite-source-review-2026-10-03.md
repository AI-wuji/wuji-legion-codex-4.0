# P0 Rust / SQLite 上游采用核查

日期：2026-10-03。执行基线v1.6。统一证据权威：`outputs/p0/upstream-version-review.json` 的 `primary_dependency_review`；本说明不是第二份锁文件。

## 已决定与未完成

用户的“先修订1.5，再执行”已承接Rust小核心路线。保留Python/TypeScript/Go/C++原生态，通过既有MCP/CLI/API融合；不重新做Go/Rust原型或性能竞赛，也不默认引入Tokio/FFI/常驻服务。

已完成的是上游发布、许可、必要Windows构建文件及逐调用宿主入口的核查，不是核心实现、Cargo.lock或本机编译成功。原v1.5和3.0实现未修改。

## 精确候选

| 对象 | 本轮一手观察 | 拟采用锁 | 边界 |
|---|---|---|---|
| Rust | 官方stable manifest日期2026-10-01，Rust1.99.0 | 1.99.0 / x86_64-pc-windows-msvc，官方tar.xz SHA256见来源账 | 早期仅观察；后续Cargo/rustc官方组件已隔离解包至.dev，不改全局PATH、Codex或宿主配置 |
| rusqlite | crates.io最新稳定0.40.2，发布2026-08-08；MIT；未撤回 | 0.40.2，crate SHA256及上游commit已登记 | 审计用Cargo.lock已生成；无军团根Cargo.lock。MSRV字段未声明，不自行猜版本 |
| libsqlite3-sys | 注册表0.38.2，上游Cargo同版本；MIT | 0.38.2，crate SHA256及commit已登记 | 是C SQLite绑定，不是纯Rust数据库 |
| SQLite | 官方发布历史最新可见3.53.4，2026-07-24发布 | 3.53.4，官方源码ZIP SHA256及发布源码身份已登记 | ZIP仅保存，不代表源码全文已读或数据库已运行 |

本轮查询时crates.io单版本API返回HTTP403空体；保留失败记录。随后使用正常返回的完整官方注册表获取对应版本，未把403内容当JSON，也未通过非官方镜像猜测校验和。

## 发现的包装器 / 引擎版本差异

最新rusqlite0.40.2的libsqlite3-sys内置头文件仍声明SQLite3.53.2；SQLite官方则已发布3.53.4并说明修复3.53.0至3.53.3的问题。因此“最新Rust包装器”不能被误写成“最新SQLite引擎”。

处理：保留同步rusqlite路线，但不盲目开启`bundled`冻结旧引擎。拟通过上游明确支持的`SQLITE3_LIB_DIR`、`SQLITE3_INCLUDE_DIR`、`SQLITE3_STATIC`接入项目隔离的3.53.4静态库；不开启动态扩展、SQLCipher、自动bindgen或全特性包。若后续上游正式包同步修复版，按同一来源账评估，而不偷偷修改crate源码或回退到系统SQLite。

这项结论来自上游发布与构建入口，不需要先自造语言实验。实际构建、引擎版本、SQLite设置和事务故障行为仍属于P2真实产品验收，不能用网上案例替代。后续已使用项目隔离的官方Cargo解析SQLite候选的8包依赖闭包，保存 `tools/dependency-audit/Cargo.lock`，核对包摘要并完整读取八份MIT许可。只运行版本、generate-lockfile与metadata；未编译、未执行外来build.rs或测试。该审计锁不是军团根Cargo.lock，G1后须按实际运行依赖重新锁定，不能宣称核心依赖准入全部通过。

## Windows现状

只读运行现有vswhere并定点检查文件，定位到已有`E:/VSBuildTools`、Visual Studio Build Tools17.14.37614.0、MSVC14.44.35207。x64编译器、链接器与libcmt文件存在；Windows SDK目录为10.0.28000.0。未安装或更新这些工具，未运行编译。

Rust不在已核PATH/常见cargo目录，不能据有限路径推断全机没有Rust。后续已按官方manifest精确摘要下载并隔离解包Cargo/rustc1.99.0，仅供依赖解析；缓存与子进程环境留在本项目.dev，未运行安装器或更改全局配置。Rust std目标库尚未准备，未编译核心；先闭合G0/G1再写运行实现。

## 宿主接线

官方Codex CLI reference列出`--model`和`--config key=value`；配置reference描述`model_reasoning_effort`取决于模型与客户端的支持。结合已观察到的本机帮助，可使用逐调用请求挂载点，而不依赖历史profiles表是否有效。

预期请求仍固定`gpt-6.1-sol`，文字medium、代码high、修复/规划xhigh。官方文档与CLI帮助不证明本用户第三方通道实际接受三档、实际返回模型或并发释放；这些保持unknown并留G2。未发起模型/付费请求，不通过ChatGPT目录判定第三方可用性，不自动换模。

## 下一门

G0仍未通过。剩余工作集中在历史方法的字段级出处与采用状态、专业资产必要许可/入口以及安装态字段恢复清单；不是重新读取已总结课件。G0闭合立即正式冻结P1，G1通过才开始Rust运行核心。

## 一手出处

- Rust stable manifest：https://static.rust-lang.org/dist/channel-rust-stable.toml
- Rust Windows要求：https://rust-lang.github.io/rustup/installation/windows-msvc.html
- Rust许可：https://raw.githubusercontent.com/rust-lang/rust/1.99.0/COPYRIGHT
- crates.io：https://crates.io/api/v1/crates/rusqlite 与 https://crates.io/api/v1/crates/libsqlite3-sys
- rusqlite发布commit：e88f112bef7899234a497baed5cc3c3d553deeb8；该发布的Cargo.toml、README、LICENSE及libsqlite3-sys/Cargo.toml、build.rs、LICENSE已定点核查；源码并非全文已读。
- SQLite发布：https://www.sqlite.org/changes.html 与 https://www.sqlite.org/releaselog/3_53_4.html
- SQLite许可：https://www.sqlite.org/copyright.html
- SQLite源码：https://www.sqlite.org/2026/sqlite-amalgamation-3530400.zip
- Codex入口：https://developers.openai.com/codex/cli/reference/ 与 https://developers.openai.com/codex/config-reference/
