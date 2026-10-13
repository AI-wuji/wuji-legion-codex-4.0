# 无极军团4.0语言与融合兼容性方案

日期：2026-10-03。性质：对3.0当前工作区的只读、关键路径分析及技术选型建议；2026-10-03已纳入批准的v1.6，正文中的v1.5待批描述为历史提案语境。

用户同日追加“先全网检索已有实践，有足够匹配结论时不重复自行验证”的统一要求。本报告第6节已按该要求修订；原始案例与当前研究结论见 docs/language-prior-art-research-2026-10-03.md，长期规则见 docs/adr/001-research-before-experiment.md。

## 1. 结论与决定边界

主推荐：把Rust列为4.0确定性小核心的优先选型，采用SQLite事务状态，Python/TypeScript/现有Go及C++项目通过有版本的协议适配。不是整套系统全部Rust化，也不是继承或翻译3.0源码。

这是一项有工程先例支撑的架构修订建议，不是“已测出Rust比Go快”的结论。批准v1.5目前指定Go核心及纯Go SQLite驱动；本报告不修改批准方案，不安装Rust/MSVC，不写核心，不修改3.0或Codex安装。Rust选型以公开实践作为可行性依据，不先自行重做语言/性能对照；正式改变基线仍须明确批准、记录必要依赖与许可并完成G1设计冻结。

3.0主要问题是业务语义、状态提交、宿主接线、资料与工具的证据强度以及规则组织方式。多数问题Go也能修正；重写理由不是Go本身不合格。Rust的潜在增量是更严格的有限状态、关联数据、错误处理和资源所有权表达，适合持续演化但不能替代事务、授权或真实验收。

## 2. 本次实际分析范围

- 读取根AGENTS、go.mod、README相关部分及构建/工具链定位脚本。
- 定点检查路由、专家目录读取、来源执行契约、参谋部状态、知识存储锁、JSON写入、需求/执行图、调度类型、验收、宿主dispatch/orchestration以及ComfyUI准入探针。
- 对旧审查报告读取相关范围后与当前源码交叉核对；不把2026-10-01报告全部判断直接视为当前事实。
- 统计项目内指定源码扩展名，排除.git/.wuji/.workbuddy/node_modules/bin/upstream-snapshots等目录。统计不是全量源码阅读证明；行数包括空行，末尾换行分割可能计入一行。
- 未执行旧项目测试、路由或外部工具。未形成当前测试通过率、宿主执行成功率或Go/Rust性能对照；旧报告的26个失败不是本次复测结果。
- 官方资料采用只读HTTP，核查与本议题相关段落，不宣称整份文档阅读。出处、HTTP状态和内容hash见配套证据JSON。

### 2.1 当前规模，而非旧报告口径

| 范围 | 本次统计 |
|---|---|
| 非测试Go源码 | 49文件，18,654行 |
| Go测试源码 | 41文件，8,090行 |
| internal/core非测试Go | 41文件，17,041行，集中在一个core包 |
| PowerShell | 32文件，3,016行 |
| 其它已统计脚本 | JS 1、TS 2、CJS 1、MJS 1；不是独立专业能力数量 |
| 专家目录当前数组 | 57个专家条目、9个commanders条目；目录条目不证明真实执行 |
| 最大文件 | route.go 1,927行；expert_bridge.go 1,200行；cmd/wuji/main.go 1,121行 |

关键结构出处：3.0的go.mod声明Go1.25；没有声明SQLite模块依赖。general_staff_store.go采用JSON快照；多个图与验收状态采用自己的JSON文件/锁，不能把3.0描述为现有SQLite核心。

## 3. 从3.0问题推导选型，而非从语言排行榜推导

### 3.1 状态存储与提交边界：先改架构，再谈语言

当前知识锁使用进程内Mutex及O_EXCL锁文件。knowledgeLockWait为2秒；锁文件超过其4倍时间会被删除，而该分支没有先证明创建锁的进程已退出。长操作可能被判断为陈旧锁：这是源码可定位的风险路径，本次没有故障注入证明其已经发生。

知识存储的writeKnowledgeFile写临时文件并关闭后Rename；Rename失败时会先Remove旧目标再重试Rename，没有文件Sync。若后续失败，存在旧目标已移除的窗口；不能把这种路径当作数据库事务或已验证的崩溃持久性。须与evolve.go中的atomicWriteFile区分：后者已有temp.Sync，Rename失败直接返回错误，没有先删除旧目标。不能把知识写入风险扩写成所有文件写入都一样。

需求写入后另记审计事件；验收先读取需求/执行状态、校验文件，再在验收自己的锁内写入。这些是分开的提交与观察边界，需验证跨状态变更、进程中断和检查后变更情形。Rust的所有权不会使多个JSON文件自动成为原子事务；Go改成正确SQLite事务也能解决这一类问题。

4.0必须采用：短事务、expected_revision/CAS、幂等事件、领取/预算/授权同事务提交、意图与真实外部副作用分离、unknown先查询以及崩溃恢复。不在等待模型或工具时持有数据库写事务。SQLite仍只有一个同时进行的写事务，不因换Rust获得无限并行写入。

源码定位：internal/core/knowledge_store.go:142；internal/core/knowledge.go:38及:706；internal/core/evolve.go:212；internal/core/requirement_graph.go:118；internal/core/acceptance.go:57。

### 3.2 规则重复与耦合：换语言不能自动减上下文

当前专家目录的字符串统计：PonyTail规则130项/83种，白帽检查99项/62种，failure_states249项/77种。这是字面重复线索，不等于每条语义可合并，也不等于已测得token节省。

core包集中了路由、上下文、任务、来源、经验、验收和宿主准备等机制；大文件与跨模块调整增加维护面。LoadManifests每次加载目录清单，loadExpertCatalog读取并校验整个专家目录，后者还有不同形式的解析。这些是索引/发布快照/调用组织的优化候选，不是已证明的性能热点。

4.0应通过原子引用、唯一语义ID、单一发布目录、反向影响闭包、层级索引和按需正文投影解决。无论Go还是Rust，都不能只把重复字符串换成另一语言里的字符串。

源码定位：internal/core/registry.go:445；internal/core/expert_bridge.go:731；capabilities/experts/manifest.json:1。

### 3.3 质量与强类型：Rust有增量，但不要夸大

3.0已有Go命名类型，例如TaskStatus、TaskFailureKind、GeneralStaffLifecycle；因此“Go完全没有类型保护”不成立。不过部分状态和身份字段仍以普通string表示，语义需要散落的运行时校验和调用顺序共同维护。

Rust候选设计采用有限enum、带关联数据的结果类型、不同身份的newtype、私有构造入口及必须处理的Result。新增状态时，对该状态做穷尽匹配且未写兜底分支的代码可以受到编译检查；它不能自动发现所有漏接线，也不能保证所有错误Result都被业务正确处理。

尤其不能让所有对象共用一个万能状态enum。任务执行、工具健康、经验晋级、来源准入和发布分别建状态类型；Missing/Unknown/Failed/Verified不得混用。NativeExecutionId、PreparedContractId、ArtifactRef、VerificationRef、OwnerId等不以一串普通字符串任意互换。

Go也能用私有类型、构造函数、静态分析和测试实现相当部分约束。推荐Rust不是否定Go，而是在核心尚未开写时，把更严格的编译期约束作为长期质量候选。

源码定位：internal/core/task_scheduler.go:9；internal/core/general_staff.go:9；internal/core/types.go:1。

### 3.4 宿主与成果真实性：语言解决不了宿主权限

当前dispatch明确默认返回native-host-dispatch-required；orchestrate声明它只是准备契约，真实子代理由Desktop宿主创建。外部codex exec只是受限兼容诊断，不能冒充宿主原生身份。

ComfyUI现有probe检查manifest/Skill存在及相关字段，属于契约smoke，不是实际节点注册与工作流输出测试。更换核心语言不会让该probe突然变成真实ComfyUI执行。

4.0要分别证明请求模型/档位、真实调用、宿主身份、产物格式/内容、专业验收和关闭释放；宿主缺能力时明确未通过门，不填假回执。

源码定位：internal/core/dispatch.go:180；internal/core/orchestrate.go:52；scripts/verify-comfyui.ps1:1。

### 3.5 已修补的旧问题不要再当当前未修Bug

本次确认当前源码已出现三项修正：路由默认aji/direct而非虚拟core/primary；角色图组装后执行最终replay预算门并在阻断后重建图；验收证据已要求普通文件和实际SHA256。

但“验收报告文件存在且hash正确”仍不等于验证程序真实运行或报告来源可信。4.0需把验证结果绑定到受控验证动作、对应产物修订、工具/宿主身份和scope。不能为求方便允许报告自己证明自己。

源码定位：internal/core/route.go:254及:606；internal/core/acceptance.go:301。

## 4. 候选比较与推荐

| 方向 | 优势与适用点 | 代价与本项目限制 | 决策 |
|---|---|---|---|
| Go小核心 | 既有经验和工具链；足以实现确定性事务/调度；建设与维护路径较熟悉 | 仍须人工建立严格有限状态、身份区分和终检；GC真实开销需测，不凭印象定为瓶颈 | 保守基线，完全可行；不是低质量方案 |
| Rust小核心 | 有限状态/关联数据/身份与资源所有权表达更严格；核心可不引入GC | 构建与借用检查增加开发成本；FFI及依赖边界仍需审查；当前PATH未发现rustc/cargo/MSVC，不能宣称已具备构建条件 | 优先审计候选；通过可行性门并获批准后采用 |
| Python主核心 | 适合资料、ComfyUI等生态接入，能管理子进程 | 本轮没有证据证明它适合替换当前强约束核心；将生态便利作为适配器收益，而非替换所有核心的理由 | 保留适配器，不建议作为4.0唯一核心 |
| TypeScript主核心 | 可承接界面、Node工具和前端项目 | 编译类型不代替外部JSON运行时验证；不为界面或SDK便利把单一任务权威交给Node平台 | 按需用于界面/适配器，不推荐替代确定性核心 |
| C++主核心 | 有需要时保留既有原生/GPU库 | 本轮未发现必须把调度治理核心写成C++的行为需求；不会为理论极限新增手工内存/ABI维护面 | 仅明确专业内核需求时接入 |

不写“Rust必然更快”或“Rust一定提高多少质量”。没有同条件测试，也没有端到端等待/返工/内存基线。取消GC并不等于减少模型等待、网络等待、工具耗时或SQLite写竞争。

## 5. 经常融合其它项目：协议边界才是兼容性基础

建议分四种融合类型，每个来源按具体用途选一种，不把“融合”理解为源码必须编入核心：

1. 方法/知识融合：蒸馏成有来源、scope和有效期的原子/专业方法；不增加运行依赖，不重新编译核心。仍查版权与专业效果。
2. 声明/资源融合：契约、配方、工作流和素材引用通过单一catalog发布；所用资产独立许可/hash/版本锁，不复制3.0资产。
3. 工具行为融合：优先对已有CLI用stdio请求/回执，已有MCP/API用对应标准适配器；第三方Python/Node/Go工具保持自己的生态和独立依赖，不重写整项目。
4. 内核融合：只有明确缺乏协议入口、数据复制/调用开销已实测为热点、且有稳定可审查边界时，才采用原生库或C ABI；unsafe/FFI集中到小边界，不暴露到业务核心。不得用内存对象、跨语言异常或Rust内部类型当稳定外部协议。

示意：

用户 → 阿极 → Rust确定性小核心（候选） → 工作区SQLite
                     │
                     ├─ 来源/原子/专家/工具：一个发布catalog
                     ├─ Python适配器：ComfyUI、资料及相应专业SDK
                     ├─ Node/TypeScript适配器：界面及相应SDK/浏览器工具
                     ├─ Go工具：保持可执行程序或公开协议边界
                     └─ C/C++/Rust库：必要且实测值得时，单独审查FFI

Python/Node运行时优先使用已存在且版本合适的环境；没有就明确依赖缺口，不把“单exe核心”误写成“所有专业工具零依赖”。不能在一个环境里无边界安装所有项目依赖。

默认不采用进程内动态插件作为融合总线，不强制新增HTTP服务或WASM沙箱，不为每个原子创建进程。Go官方plugin当前支持Linux/FreeBSD/macOS而非Windows，且有构建兼容和race detector限制；Rust也不以语言内部ABI作为任意第三方插件接口。优先选择实际已有协议，避免为统一而包出第二层工具宿主。

### 5.1 统一但不过度的适配契约

固定共同字段：protocol_version、action_id、request_id、task/attempt、scope、exact_input_refs、expected_revision、capability_profile、effect_class、authorization_ref、deadline、idempotency_key、artifact_refs、verification_refs及release_state。

共同字段只覆盖身份、权限、状态和证据；专业参数和结果保留领域schema。例如视频时间量、Comfy节点注册、Word可编辑性不能统一成success=true。

stdout只输出有界协议数据，日志分stderr；输出字节、分页、超时和路径均有边界。生产环境禁止泛化shell字符串拼接，以固定命令及参数列表调用已准入工具。版本不支持/字段不兼容时显式拒绝，不猜、不静默降级。

输入、工具能力、环境和来源锁变更触发相应缓存失效。新工具升级仅影响其消费者；在途任务继续锁定旧修订，不自动吃最新依赖。适配器不能直接写核心SQLite或把第三方数据库变成第二任务权威。

“不常驻”约束不变：只在任务需要时启动有归属的进程，真实退出前占槽，空闲不保留军团后台模型/服务。stdio短进程接口能覆盖的场景，不为了看起来高级引入常驻RPC层。

## 6. 先复用已有验证，不把自做实验作为选型前置

用户要求研究先行。现已找到Temporal Core多语言接入、Codex Rust工作区与SQLite声明、Goose Rust/MCP扩展、Restate多语言服务等公开实践；另以Temporal Go服务与LangGraph Python编排校正语言优越性的泛化。详细出处、支持范围及未支持的断言见本次研究报告。

这些匹配案例足以支持Rust小核心＋多语言融合路线的可行性，不再默认安排自行编写Go/Rust原型、协议探针或性能竞赛。本轮未执行这些实验，不安装开发环境，不调用付费服务。

- Windows工具链、SQLite候选及跨语言接口先使用上游公开说明和已有实现依据；按实际采用项登记版本/许可，不为了证明一般可行性重造测试。
- 依赖选择仍遵循小核心：rusqlite与SQLx等候选按短进程/事务需求取舍，不因某大项目采用某库就复制其全部构建链。
- 当前没有4.0 Go/Rust性能对照数据，因此不写速度倍数；缺少该数据不作为架构研究无法结束的理由。
- 只有仍影响决定且已有实践未覆盖的具体缺口，才考虑最小必要验证；非决定性缺口明确局限后继续。
- 外部实践是方案依据，不冒称本机执行；正式实现与专业交付的实际状态仍按已有门准确记账。

Rust仍是推荐选型，Go仍是未修改的批准基线；语言变更需要明确决定，但不需要先让用户等待重复的可行性实验。

## 7. 对P0—P6的最小调整

- P0：记录已有实践与本选型建议；保持资料范围和来源账口径；公开研究优先，不默认增设语言/兼容性实验，不重新通读课程。
- P1：若用户批准Rust，更新语言ADR及其影响的依赖、打包、实现绑定与验收映射，保留既有72需求/95验收/57职责，冻结baseline-1；未批准前Go仍是执行基线。
- P2：只实现一个确定性核心与最小工程/验证闭环；先核心正确性及真实宿主门，不批量造专家。
- P3—P5：专业专家和领域适配不因Rust改成单语言；进化沿单一来源/经验链，经全影响回归与一次发布，不允许第三方项目任意自改核心。
- P6：加Windows可安装包、隔离依赖、跨语言故障恢复与来源/许可一致性；真实重点工作流门保持不变。
- P7：仍须单独批准。不改Codex安装、插件启停或音频设备。

## 8. 官方依据与阅读边界

仅核查下列与选型直接相关的官方/上游段落，内容hash/响应状态见outputs/p0/language-analysis-2026-10-03.json。未锁定任何新生产依赖。

- Rust Book ownership：编译检查的所有权规则与内存管理；https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html
- Rust Book match：穷尽模式匹配；https://doc.rust-lang.org/book/ch06-02-match.html
- Rust Nomicon FFI：C ABI及unsafe边界；https://doc.rust-lang.org/nomicon/ffi.html
- Rust Reference functions：extern ABI与跨语言调用边界；https://doc.rust-lang.org/reference/items/functions.html
- Go GC Guide：GC CPU/内存成本需要根据程序行为测量；https://go.dev/doc/gc-guide
- Go plugin文档：平台与构建限制，IPC替代边界；https://pkg.go.dev/plugin
- SQLite transactions：写事务与busy/事务模式；https://www.sqlite.org/lang_transaction.html
- rusqlite上游README：bundled编译链接SQLite；https://raw.githubusercontent.com/rusqlite/rusqlite/master/README.md
- Python asyncio subprocess：子进程接口与Windows事件循环条件；https://docs.python.org/3/library/asyncio-subprocess.html

最终建议：依据已找到的同类实践，推荐Rust小核心与有边界的跨语言融合，不先自行重做一般可行性证明。不要把“更优质”定义成换个语言名，也不要因为3.0用了Go就未经分析沿用。将每一类3.0问题绑定到4.0修复机制及真实验收；不承诺一种语言会消灭所有未来问题。
