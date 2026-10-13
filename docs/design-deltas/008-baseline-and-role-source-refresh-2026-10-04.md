# 活动基线测试与P2来源修复

日期：2026-10-04。活动方案v1.7，完整v1.6需求及P7保护不变。

## 实际问题与最小修复

统一回归发现两个旧测试仍替换preflight.PLAN/BASELINE_MANIFEST，而实际入口已改为ROOT下的execution_baseline.load_active。测试因此没有操作自己的临时基线。现改为真正的临时项目：保留P7另批与shutdown=false，核正确hash、计划字节变化、未授权版本、项目外路径和缺失文件；不修改真实活动基线或放宽拒绝条件。

另外，原子来源账追加原始Rust依据后，P2两个准备角色仍登记旧整文件hash。核对八个精确pointer与candidate_id后，只更新派生来源hash并将角色revision从2递增到3。完整旧角色字节保存在outputs/p2/catalog-history，来源刷新回执见outputs/p2/prepared-role-source-refresh.json。

这不是新架构、语言选型或通用机制实验，而是本次实际产物的版本完整性修复。已有研究先行方法及精确引用规则直接复用，不重读课程资料或重复全网论证。

## 实测与限制

已隔离重新构建Rust CLI；P2准备角色四项真实CLI测试通过。baseline定向五项通过。修复后的首次统一回归为Rust169项、Python186项全部通过，源码与配置前后稳定；后续新增任务测试以新的统一执行账为准。

准备角色仍是prepared、runtime_admission=false、effectiveness=not_run。旧原生模型回执继续绑定旧字节，不能冒充revision3实测；当前原生专业复验仍有已记录的429限制，不换模或改配置绕过。现用Codex配置、安装、全局Skill、凭据和音频设备不变，不执行P7或关机。
