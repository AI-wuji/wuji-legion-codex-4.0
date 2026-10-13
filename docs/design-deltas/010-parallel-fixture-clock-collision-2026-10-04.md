# 并行回归工作区同钟碰撞

日期：2026-10-04。统一重验Python191项通过，Rust在received-delta套件初始化失败（Windows os error 183）；失败执行账与原始Rust日志完整保留于outputs/p6/continuation-2026-10-04，不删除或改写成通过。

## 具体证据与研究

该套件有七次Fixture::new，但失败进程37748在.dev/received-delta-acceptance下仅有六个新根目录。旧目录名只有进程ID和SystemTime.as_nanos；两个并行用例复用了同一根目录，Store::open创建.wuji4时发生已存在错误。其余业务负例没有执行完，不能先将其计通过。

复用既有研究先行与Rust标准库来源方法，核对原始文档：

- https://doc.rust-lang.org/std/time/struct.SystemTime.html ：时间精度依赖底层系统，纳秒表示不是唯一ID保证。
- https://doc.rust-lang.org/std/sync/atomic/index.html ：原始示例使用Relaxed原子递增计数；本次只取进程内唯一序号，不用它同步业务内存。

观察日期均为2026-10-04。公开资料指导修复方法，不冒充本机业务测试；失败日志、七调用六目录与后续回归才是本次产品证据。未加入或晋升新的专业专家原子，不修改现有知识/经验权限或冻结资料。

## 最小修复与范围

只修改tests/p6_received_delta.rs测试夹具：目录名增加进程内原子序号，并独占创建根目录，碰撞时不得默默复用。新增相同固定时间戳下32个真实线程的目录创建负例，确保问题不再依赖偶然时钟粒度才触发。

这不改Store运行实现、业务拒绝语义、默认并发或当前Codex配置，也不通过串行化全部测试掩盖碰撞。所有目录留在项目.dev，既有失败产物保留，不清理用户文件。完整业务场景仍需后续统一重验通过才能入账，P7与关机均不执行。
