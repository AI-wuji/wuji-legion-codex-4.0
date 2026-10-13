# 003：隔离发布、单写移交与有界专业契约

日期：2026-10-04。实现依据仍为v1.6、冻结architecture、evolution-impact-spec、ADR002与已有SQLite事务/PROV来源账，不改20份冻结设计文件，不新增服务、FFI或生产安装。002是schema3建设时的历史记录，本次明确init将已知schema2/3事务迁移至4；未知/更新库及观察型打开不迁移。

## 本地catalog registry

新建src/registry.rs和registry_schema.sql。定义与manifest只在不可变文件中，SQLite仅拥有一个active_release、指针revision、准入状态、事件与可重建消费者索引；workspace不另存活动指针。

文件使用create_new并sync_all，已有文件只接受完全相同字节。manifest完整锁定同scope/release、唯一文件/ID、全部引用与必需根；所有适用消费者的组合先校验，再短BEGIN IMMEDIATE事务CAS发布指针。不会因候选目录存在而激活，也不自动恢复已撤销版。当前任务可保留ReleaseLock，后续精确读取重查manifest及全部文件hash；撤销拒绝新组合，不热改旧锁。

消费者索引与定义文件推导的完整边集严格比对；缺失/伪造边必须显式重建。分页声明total、next_offset和all_pages_required，不能把一页当完整闭包。T52检验36项影响闭包、分页穷尽、缺失/新增伪边及修复。

publish_local只在本项目.dev独立目录显式确认后可用，仍runtime_or_global_admission=false；当前只是完整确定性组合校验，不是公共专业发布。Windows目录条目的掉电持久性或跨文件/SQLite原子性不作保证；打开时缺失/变化均fail closed。本轮还没有把通用任务领取/原生派发接到registry撤销检查，因此T51/T53仍不得仅凭注册表组件测试升级为正式通过。

## 单写移交

resource_transfers冻结源ID的全部本地写权和检索复用；目标received_resources按稳定transfer_id幂等接收，持有唯一生命周期写权。源只通过实际查询目标ACK完成shared_ref，不接受业务JSON自报ACK。中断停在transfer_pending也不会有两个可写事实；目标已提交时先查再收口。

原envelope与来源ExactRef保留为不可变出处快照，不伪装成目标scope的事实或全局知识。授权限定两个不重叠.dev工作区，目标复用必须重查原文件、知识依赖和过期；源不可读/知识已移交的依赖未接通时保留拒绝，不复制出第二份可改知识。目标可以CAS退役，幂等接收不会复活已退役资源。源无自动解冻/重新写回路径。一般跨scope内容修订、依赖重新定位、领域/全局晋升及专业有效性仍未完成。

## 时间与专业准备

TimeQuantity→TimeBase.rate ExactRef→当前Rate→profile/origin ExactRef分开重查，所有单位/正比率/舍入按冻结schema。转换先用checked i128有理数，交叉约分；再显式exact/floor/ceil/nearest_even，拒绝帧率冒充采样率、不同origin隐式重基和溢出。不把用户采用的profile声明说成实际媒体已测量。

新增Story→真实PCM-WAV MusicCue→Shot有界准备链：实际音频长度/采样块/格式、精确Story/Music引用、权利证据文件、时基与跨度均检查。情绪描述不替代音频，不隐含循环，不强制每拍切镜。输出prepared、runtime_admission=false；权利文件被观察不等于其法律/发布权限已独立验证。时间线/retiming/stem/REAPER和专业成片holdout仍未接通，不能宣称G4已过。

register-input保留UTF-8边界。register-binary-input仅以显式确认在独立.dev登记<=1MiB不透明媒体；登记不是执行授权。文本复制器在领取槽前拒绝非UTF-8，避免失败留下不必要的占槽。

有界prepare-recipe引用共享窄专家的精确组合与五要素/IO/工具/验收契约，分配独立实例/owner、依赖与canonical写集。不克隆专家定义，不隐含启动模型；max_parallel_instances<=3是建设保守上限而非已测原生quota。请求仍固定gpt-6.1-sol及medium/high/xhigh，实际模型/档位unknown，正式专家数0。

execution-summary只依据当前工作区任务、产物、要求链接与调用/关闭状态汇总，不把prepared/目录数量/unknown说成完成；实际模型线程数未取证仍unknown。只证明对应有界任务，不证明全G4/G6或P7。

## 复查根因与证据

Windows verbatim路径的PathBuf.join会规范化父组件，原先只检查joined.components漏掉内部“..”。现在先检查原始target.components再拼接，保留canonical/保留控制目录/写冲突检查。Rust原始文档快照与hash已追加到现有outputs/p0/atom-evidence-ledger.json，不另建来源账；这是公开既有行为，当前产品回归用于检验实际修复，不重复做语言选型实验。

追加复查修复：读集原先以字符串starts_with判定，使data/one可能误准data/one-other.txt。改为重新canonicalize登记路径、按Path组件及Windows大小写检查单向包含；不使用双向写冲突谓词来授权读取。输入hash完整性与UTF-8处理器兼容性分开；二进制不再被误报为“文件变化”，但文本复制仍在领取前明确拒绝。

正式结果由outputs/p6/test-execution.json和acceptance-execution.json当前hash重新计算；局部实现和专业/原生完整验收分开。本次不修改现用Codex配置，不付费，不安装、推送、发布、执行P7或关机。
