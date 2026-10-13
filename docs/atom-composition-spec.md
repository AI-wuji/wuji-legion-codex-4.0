# 原子、包与组装接口

P1 baseline-1设计已冻结。文件完整性和G1审查见docs/design-baseline-1.json及outputs/p1/g1-review-2026-10-03.json；设计冻结不代表运行实现、专业效果或宿主验证已通过。

## 四层与最小实现

L0为ExactRef、Scope、TypedValue、TimeQuantity/Rate、Budget等数据值，不是专家。L1为一输入责任→单类结果/可定位失败的语义；L2为条件组合包；L3为负责人/专家/审查/工作流配方及有出处的专业差异。同代码可实现多个具名契约，复用稳定内聚代码，不按每条规则建函数文件/服务。

公开语义设计接受不等于执行资产准入。program/schema绑定在P2实际实现和测试；model指令在P3由课程与专业来源全新编写；native_action在P4真实profile/资产/授权/结果后才可用。所有candidate正常/反例和拟定实现位置进入设计映射，运行admission继续false。

## 构建输入输出

Input=release manifest精确锁＋AssemblyDefinition＋具名task slot bindings＋授权scope/用途＋当前typed inputs。Output=一份五要素齐全的有效契约、源字段映射、闭包锁、哈希、预算、required checks与未解决缺口。一个热契约携带必要实际指令，不假定模型知道原子ID。

固定操作顺序：核release/schema/hash→有限条件选择→构造精确依赖DAG→环/悬空/同ID不同版本冲突→按稳定拓扑顺序去重→具名槽类型/范围绑定→约束合一→必需引用/权限上限保护→五要素与专业输入验收完整性→字段出处/闭包→预算→不可变构建产物。未知条件不默认为true；歧义回阿极。

冲突无最后覆盖获胜：同槽相同值可以合一并记录全部来源路径，不同值明确COMPOSITION_CONFLICT；不同版本即使文字相同不合并。专业差异只能填授权槽/细化兼容范围，不能删用户约束、白帽、权限、来源、验收。菱形同精确ref只装一次，所有出处路径保留。数组含叙事/用户顺序时不排序；具名引用集合以明确typed集合语义排序。

## 规范化与类型

命名codec=wuji-canonical-json-v1，不宣称完整RFC8785实现。关键契约使用严格JSON：递归拒绝重复key；对象key按UTF-8字节序排序；数组保留顺序；字符串按JSON转义、不做隐式Unicode归一；关键数值仅整数/具名有理数，不把f64作时间权威。外部工具原始请求/结果可作为hash锁定文件，不混入可编辑关键值。相同codec/schema/release/slot输入产生相同字节及SHA256；更换codec就是release变更。

ObjectMeta为公共权威头；payload同名id/scope/revision/owner/hash存在时必须与头一致，不能作为第二份可改事实。type与contract_type一致；创建/更新时间、valid_until及单位合法。JSONschema只能检形状；跨字段、ACL、DAG、当前采用、真实宿主与独立验证必须独立程序检查。不能从反序列化的authority/host_execution_ref赋受信权限。

TimeQuantity含有理数、unit、basis_ref、rounding；Rate明确frame/sample/tick per second及profile；换算用有检查的整数运算，溢出/未知时基/要求exact但不可整除分别拒绝。REAPER浮点秒的测量误差由适配profile明确，不声称pan即3D或字数即对白时长。

## 包与消费

最低共同包：course-five-elements、minimum-correct、white-hat、versioned-handoff。负责人/专家按适用任务引用同版本共享包，再加领域IO/工具/验收/反触发。无关风格、方法和专家保持冷态；固定2方法只是默认目标，可因自包含性调整，不为了预算删除必需正文。

专业示例：Comfy节点=五要素＋Python环境方法＋已核节点schema＋输入张量/注册/错误验收；Office=文档结构方法＋非目标保全＋真实解析/编辑/渲染；视频=Story→实际MusicCue预剪→Shot→生成→Timeline→Sound→export，不拿视频钩子当代码/办公共同硬门。

## 构建失败与完整影响

原子单失败可定位，但检查领取/预留/意图须同事务提交，不能把原子化拆成竞态。必需检查全是AND，不让主观分盖失败。完整反向影响索引锁source_release/hash；损坏/未穷尽分页返回IMPACT_INCOMPLETE，禁止发布。所有schema/program/model/native绑定及专家/负责人/流程/图/测试都是消费者，不能只更新几份提示词。

## 哈希域、unknown与实现分型冻结

原始文件digest=SHA256实际文件bytes。定义对象content_hash=SHA256(UTF-8域前缀`wuji4-object\0wuji-canonical-json-v1\0` + canonical envelope)，计算时仅移除metadata.content_hash这一自哈希字段；payload里的sha256若表示资产完整性则仍参与哈希，不能强制它等于对象content_hash。通用JSON哈希命令对完整输入canonical bytes哈希，不冒充对象hash。所有ExactRef.sha256指所引用对象声明的明确hash域；解析器按object/file类型和发布锁核同一域，不能混域。

metadata与payload重复的id/scope/revision/owner/schema_version必须一致；payload.type若是ExperienceCandidate等专业子类型，不等于contract_type，不能盲强制覆盖。metadata.type才与contract_type一致。proposal/null观察不能冒充host证据；缺观察用显式缺口记录而非伪造ExactRef。状态result pass/proposal需要非null typed value与null failure_code；fail/unknown必须定位atom_id前缀failure_code，unknown绝不放行。

method/profile原生观测与有限程序证据检查不是同一种实现。AtomImplementation.execution_form仅schema/program/model/native_action；P1 primary_form是语义分类并明确转换，非新运行枚举。原子ID虽共用，native_action只在实际profile/授权/结果后准入，模型不能构造trusted observation。
