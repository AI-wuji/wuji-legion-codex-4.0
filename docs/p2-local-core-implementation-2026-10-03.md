# P2 本地核心实现与重验报告

日期：2026-10-03。执行基线：v1.6，hash与批准范围见docs/execution-baseline.json。本文是建设中期产品报告，不是P0—P6全部完成、G2通过或生产发布。

## 1. 当前阶段与实际结果

G0已通过；G1设计审查通过并冻结baseline-1.1。P2核心实现进行中，G2未通过；P3—P6未启动，P7未授权。正式模型专家0，原生子代理0，新产品运行的额外模型/第三方生成探针0，生产安装0；当前阿极建设对话不冒充4.0原生专家执行。

- 最新70项Rust测试通过：69个行为测试入口和1个供子进程调用的测试fixture入口；此前61项结果另保留。新增9项是原生请求准备/拒绝测试，不是模型调用，不将fixture入口解释成独立业务能力。
- 最新13项实际CLI集成测试通过：9项覆盖真实UTF-8文件闭环、回放、权限/输入拒绝、图CAS、CAS取消、当前任务状态及检查点；另4项只测试G2准备接口及选定协议字段，不派发。
- 9项P1开发期审计测试及1001项结构检查通过；不是运行或专业效果验证。
- 原47项P0辅助测试是历史结果，本次未重跑。
- 完整95项验收未全部执行或通过。分项证据见outputs/p2/acceptance-component-evidence.json；所有完整场景仍保持not_run，不用局部断言替代原生/专业结果。

最新日志：outputs/p2/core-tests.log、core-cli-tests.log、native-preparation-cli-tests.log及native-preparation-build.log。最初40项和此前61项日志分别保留；准备接口首轮schema假设错误见native-preparation-cli-tests-attempt-1.log，已修正并重验，未隐藏失败记录。最新hash以core-build-review.json为准。

## 2. 本次实际实现

### 输入与证据

本地用户入口按真实工作区身份注册UTF-8文件；每次采用保存精确id/revision/scope/release/schema/hash、真实路径和大小。此状态是adopted_user_input，不是专业产物验收、宿主回执或全局知识准入。重复采用同一路径/内容回原引用；内容或路径改变生成新版本。

计划、领取、写入、验证时校验实际当前文件、精确引用、声明read_roots及发布绑定。不接受未注册、跨scope、过期或未分配的输入。CLI的run-local仅复制声明且已采用的UTF-8输入，生成新本地文件，再调用独立程序验证职责；不生成模型内容，不冒充工程专家。

输入/产物变化在单独短事务中持久标记完整下游失效；当前acceptance_links移除，历史validation/event保留，旧产物只读保留不删除。slot不会因失效释放。单纯检查当前hash与全链持久失效不再混为一谈。

### 图修订与预算

受信本地入口接收WorkflowPlan提案，CAS预期图版本。保存不可变计划历史；依据旧/新依赖并集计算影响闭包。被影响节点和仍在途/待恢复节点须显式增版，旧回执不能复活；已完成且无影响的产物与验收保持。

预算、catalog锁和全任务重试账不能通过图修订重置；同事件同payload返回原结果，不同payload冲突，无语义进展不消耗一个新图版本。当前P2不支持删除历史节点，必须保留身份；新增节点受256上限及点修订预算限制。

每个attempt保存原始spec_json；旧slot在关闭前仍按旧读写集合占位，不能通过改写新图路径偷放旧锁。

### 写入、验证、关闭

文件使用create_new、write、sync和实际回读，大小上限1 MiB、UTF-8检查、保留目录/越界检查。只准入program/local-file-writer及local.file-readable/local.hash-current/local.utf8三项验证；路径不可覆盖，返工应使用新版本输出路径。

重复写入同attempt、同路径及同bytes只回放原produced事件，并再次校验当前绑定与真实文件；不同payload冲突，不再次执行效果。CLI重复已完成本地复制也复用当前真实attempt/validation，不增加写入。

producer和程序validator职责身份不同；这不是独立模型评委。业务完成不释放slot；受信本地effect已观察或从未dispatch时才能关闭。本地最后slot关闭后对账succeeded/cancelled。unknown不靠超时、内容匹配或任务作废释放。

### unknown、检查点与真实进程测试

recover将dispatching转unknown，保留占槽、预期路径/hash/大小和查询引用，不重新提交动作；已因输入/图失效的superseded attempt不被恢复为可执行状态。

attempt查询仅返回真实DB状态和当前文件观测。匹配intent的文件内容不能证明producer身份、动作结束或原生关闭。此情况明确保持unknown。

检查点是有scope/hash的持久上下文快照。重新读取会核当前DB图/节点/attempt/产物及实际证据；旧快照变更后不可当当前上下文。检查点不导入用户自报状态，不延期lease，不释放slot，不解决unknown，也不是外部动作已恢复成功。

已实际启动并回收本测试自建OS子进程：两进程竞争同节点只有一个赢家；两个独立文件handler在两进程中并行完成并验证；强中断发生于dispatch提交后、文件sync后但producer事务前、SQLite事务尚未提交时。前两种保留unknown/slot，后一种回滚未提交图变更。未结束任何用户原有进程。

### 冷候选检索与分层投影

PreparedIndex按typed domain/kind/intents/anti_intents查metadata分组，返回selected/none/ambiguous，不假装理解自然语言，不造置信分数，不先加载所有专业正文。leaf/method/style/recipe只是索引类别，不是已生成专家。

brief来自已锁index；overview/source只按所请求的精确引用回读当前文件、核hash与scope。source可直接读取，不强制先走brief和overview。当前byte读取量有实际长度，tokens、缓存收益和模型开销保持未知；硬预算不足报错，不静默截正文。

所有候选、组装和投影结果runtime_admission=false；没有正式catalog活动发布、没有角色数量等于运行人数的声明。

## 3. 哈希、版本与构建

- 文件hash：实际原始bytes的SHA-256。
- hash命令：完整JSON的wuji-canonical-json-v1编码摘要；不是对象content_hash。
- object-hash命令：对象域前缀wuji4-object和codec后编码对象，排除且仅排除metadata.content_hash；不赋权限。
- 本地program exact ref锁定相关Rust源、状态schema、公共契约schema、Cargo manifest/lock；不是仅store.rs文件摘要。
- 公共契约schema_version仍为1；SQLite内部user_version为2。旧/未知版本明确拒绝，不静默迁移、降级或覆盖；尚无通用迁移/恢复工具，不宣称已有。
- 官方Cargo独立生成根锁；29个registry包，其中Windows可达28，与既有审计包版本/归档checksum一致，不复制审计锁。
- Rust/Cargo/std1.99.0、MSVC14.44.35207、SDK10.0.28000.0在既有隔离环境构建；Process环境结束恢复，不改全局安装。
- 实际静态链接SQLite3.53.4；启动前校验版本和精确source_id。Rust核心禁止自己的unsafe代码，但SQLite仍是C依赖，不称纯Rust全栈或依赖全部无unsafe。

构建/测试命令见tools/build-core.ps1。已有公开Rust小核心与多语言接口实践继续作为方案依据，本次测试新产品，不重新做语言选型、性能竞赛或兼容性实验。

## 4. 仍未闭合的门

本次后续新写了两个G2最小工程/独立验证职责候选及不派发请求编译器，记录见docs/p2-native-preparation-2026-10-03.md。所有候选仍prepared/runtime_admission=false，未形成正式catalog。官方协议和CLI0.160.0纯schema导出已核，仅证明选定字段；没有可信原生adapter、未启动app-server或额外生成，不以非空effort字段证明三档实际可用。

G2需要原生工程职责、独立验证职责及两独立文件任务的匹配真实宿主证据，尤其T68/T69/T72/T73的实际请求、有效模型/三档、原生配额、关闭释放与费用前置。

目前只知道请求策略gpt-6.1-sol，文字medium、代码high、修复/规划xhigh；有效模型/档位/配额/关闭/免费前置仍unknown。本地程序测试、配置、网页、CLI帮助、目录和自写host-status均不能补成真实观察。未证明免费前置，不提交嵌套Codex或第三方生成；没有明确子代理开发授权，不启动模型代理；不自动换模。

冷index不是已发布活动专家目录；当前验证不覆盖ComfyUI、OfficeCLI、图像、视频、剪映/REAPER、进化发布、P6全量复查或P7安装。P3—P6必须等对应前置门，不擅自改变已批准1.6的顺序来制造完成声明。

后续所需是合法、可信、费用明确且匹配所请求模型/档位的宿主执行条件及必要委派授权，不是再重复读资料或查同一语言选型。条件具备后接续真实G2任务及关闭证据，再推进P3—P6。所有产物与待办保留，未修改当前Codex、插件或音频链，不付费、不发布、不清理用户文件、不关机。
