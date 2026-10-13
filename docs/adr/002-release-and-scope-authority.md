# ADR002：发布权威与跨scope移交

状态：P1冻结决策，2026-10-03；不代表代码已实现。依据批准v1.6第4.3/13.6/19节及已读SQLite事务/外部unknown/PROV方法。

1. catalog不可变定义文件和manifest是定义权威；catalog registry SQLite仅拥有active_release指针/准入状态/发布事件。workspace只引用release，不写第二活动指针。此为批准“全局发布目录与工作区任务状态不双写”的实现细化，不新增记忆系统/服务。
2. 文件先完整持久化并校验manifest，后短事务发布指针。仅候选文件存在不激活。读release先固定指针并校验全部必要hash；当前任务固定release。安全撤销拒绝新动作，不悄改任务。
3. 同scope经验只有一个可写事实。跨scope先冻结源transfer_pending，目标以稳定transfer_id幂等写入并ack，源收到并核ack转只读shared_ref。进程中断先query目标；暂时目标已写、源仍冻结不是双可写。未授权时不创建用户应用shared库，本阶段测试目录内隔离演示。
4. catalog registry与workspace及shared库不试图跨库BEGIN事务伪造原子性；必要移交用可查询ack协议。active版本恢复仍完整检查/兼容/未撤销，不回退用户决定。
5. 替代方案拒绝：工作区复制一套可改catalog；每经验双写两个库；把派生索引当活动权威；单schema通用graph_nodes任意JSON承载所有状态。
6. 运行验收留P2/P5，P1仅完成正常/中断/冲突推演。P7安装另授权且不在本次修改当前宿主。
