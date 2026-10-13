# 006：媒体校验纠错与选择、局部返工、预算证据闭环

日期：2026-10-04。执行v1.6及既有冻结设计；新增实现增量，不改冻结验收、不改现用Codex配置、不扩大P7授权。

## 媒体真实边界

已核对Rust整数原始依据并在统一来源账记录。时间比较/差值错误逐层返回；溢出不能被is_ok_and吞掉。正常首尾相接的retiming段允许，每一映射必须连续覆盖完整Shot源span与对应clip目标span；空段、倒序、间隙、重叠、不完整覆盖及越界均拒绝。改变clip时间必须提供映射，每个Shot最多一份完整映射。

ID/revision不能证明父内容。当前retiming以timeline_binding_sha256绑定：固定域前缀、当前scope及完整TimelineManifest payload，仅剔除retiming_map避免循环。所有Story/Shot/Music精确引用、timebase、rate、clip、owner与revision仍在指纹中；完成时间线登记后仍重查其完整ExactRef。这是无循环的父内容投影，不冒充完整父ExactRef。更新父内容不能沿用旧映射。

frame profile现在必须是严格的frame_rate_declaration及1—32个有理数supported_rates；只证明声明支持，不称真实素材帧率测量。frame型timebase Rate与inline frame_rate必须相同。SoundPackage的stem/render必须是当前登记的真实有界PCM-WAV，不接受占位字节；bus/automation/validation仅查引用完整性，输出明确标记语义未验、render未执行。删除虚假的minimal_downstream_revalidation=true，媒体最小依赖闭包仍是内部待实现项。

## 冷目录与实际任务返工

T05/T06/T83增加真实独立CLI调用场景：82条目录中只检查适用组，必要原文确实提供，歧义需缩小条件而非伪置信度/截断，直达source不强制brief→overview。逐次记录元数据与实际源读取字节，计量单次进程往返与耗时；不作跨模型速度优越声明。源或index更新撤销旧投影。冷态prepared不成为运行准入。

T11/T12/T13/T18补完整隔离本地工作流：全部完成后局部需求变更只重验受影响链、保留其他采用与旧产物；重复事件20次不产生第二次dispatch；真实OS中断后多次恢复/查询仍隔离unknown，匹配文件不制造producer receipt；文件变更后旧评审失效，新revision必须重新独立验证。这些确定性本地验收不替代真实模型或专业效果。

## 预算与完整证据

新增只读read-evidence页接口，每页明确工程字节大小、完整ExactRef/hash/长度、偏移及hex内容；跨UTF-8边界也能无损重组JSON，不裁掉失败/权限字段。单页1—16384字节是有界接口的工程限制，完整文件仍按原1MiB输入边界保存；不是历史4096 tokens、任务费用或上游模型额度。

预算配置声明只从隔离.dev工作区的登记文件读取，不读写活跃配置。configured、当前文件字节观察、effective及unknown分别返回；host/schema/source指纹只证明声明身份，不能当可信宿主遥测。窗口未知不推导5440，不把另一模型272000或240000/90000压缩阈值变成有效窗口、计费限额或免费承诺；配置更新拒绝旧精确引用。真实宿主观察和有效窗口计算仍未实现，不据该层将T71整项升级。

## 验收真实性与并行

缺少专业工作流/holdout实现的场景归not_run内部待建，不再整类冒称外部阻断。原生真实身份/档位/退出/额度无法取得仍保留明确缺口。验收证据闭包增加实际消费的来源、覆盖、版本和授权资料hash；旧组件证明只挂supporting，不凭数字调整宣称全量通过。

第一只读子代理观察到429且已关闭；第二只读审计完成后继续独立证据/预算模块写集。显式high/medium创建请求未被接口接受，成功继承通道不证明实际档位。固定请求模型、不换模、不改配置绕过限制；真实执行/退出及unknown分开记录。
