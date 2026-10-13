# 预置工作流与专业交接契约

P1 baseline-1设计已冻结。文件完整性和G1审查见docs/design-baseline-1.json及outputs/p1/g1-review-2026-10-03.json；设计冻结不代表运行实现、专业效果或宿主验证已通过。

| 工作流/交付owner | 入口/依赖 | 正常节点与输出 | 必需验收/失败与恢复 |
|---|---|---|---|
| S0/阿极 | 简单文字，无外部副作用 | 必要核查→直接短答；内存单节点，不拉staff/专家 | 不伪造事实；需要动作时显式转S1/S2 |
| WF-SOFTWARE/lead.software | 授权源码、目标行为、生态/依赖锁 | 行为/接口→模块设计→限定实现→独立回归→可运行包 | 真实环境/接口/测试，越范围拒绝；专业生态不强Rust化 |
| WF-BUGFIX/lead.bugfix | 症状、输入、当前环境 | 已有公开根因/反证→决定性缺口复现→最小修复→新回归 | 相关性不当根因；同输入无新证据熔断，局部返原owner |
| WF-COMFY/lead.comfyui | 授权插件、实际环境/工作流 | C0来源环境→C1注册/数据流→C2公开行为→C3重叠差异→C4统一设计→C5原生态实现→C6真实节点/图→C7包/回归 | import/smoke不代替注册与真实图；未知设备/数值/取消/许可阻断，不能用Office样例冒充 |
| WF-RESEARCH/lead.research | 问题/决定/约束/已有来源 | 有效已有结论→一手/同类实践/反证→范围匹配→ResearchDecision/来源缺口 | 外部验证与本机执行分开；仅决定性缺口最小实验，无额外搜索宿主 |
| WF-WRITING/lead.writing | 原文、平台/目的、事实/观点边界 | 选窄专业/风格→结构→新写→事实/表达复核→定稿 | 不虚构作者经历或改观点；发布另授权，无资料报告缺口 |
| WF-LEARNING/lead.learning | 目标学员/资料/掌握度 | 来源知识→可练习目标→讲解/练习→证据掌握度→课程产物 | 知识与个人掌握度分开；无固定互动次数/虚假效果 |
| WF-OFFICE/WF-DATA/lead.office | 文件类型、非目标保持项、公式/口径 | 结构/数据→原生态编辑→解析/公式/可编辑/渲染→交付 | OfficeCLI须实际入口准入；静态图片不当原生PPTX，示例数据明确标注 |
| WF-IMAGE/lead.image | brief、参考职责、权利、目标profile | 身份/保持项→provider编译→授权真实生成/编辑→实际文件回看→采用 | 提示词不当图；免费/接口/权利unknown不提交，备用key不默认激活 |
| WF-VIDEO/lead.video | 类型/情报/目标/风格、当前输入 | V0信息/视角→V1 Story→V2实际MusicCue/预剪→V3资产/Shot→V4生成→V5粗剪/精剪Timeline→V6全声音→V7合入/工程/导出 | 可省无关节点，不跳实际依赖；实际时长/音轨/字幕/工程，源变更局部失效 |
| WF-AUDIO/lead.audio | 已采用时间线/台词/SRT/music/stems | 对白/旁白、环境、拟音、音乐窄专家→唯一声音owner→bus/automation→离线导出→重开 | 混合不当分轨、pan不当全3D；不打开capture/改系统音频，隔离未知即停 |
| WF-BUSINESS/WF-PUBLISH/lead.business/lead.publish | 商务事实/当前平台/明示授权 | 需求范围→提案/报价依据/风险→定稿→授权动作→回读 | 建议不是合同法律意见；保存/云草稿/发送/发布/付款分开权限 |
| WF-AUTOMATION/lead.automation | 用户明确调度目标/时间 | 宿主原生排程→绑定scope/action→真实回执→变更/停用 | 不造watcher/常驻模型；排程对象存在不证明将来动作成功 |
| WF-GOVERNANCE/女娲 | 新来源或真实反馈/失败事件 | 限域delta→去重/专业差异→来源许可/完整影响→独立验收→单一发布→撤销/恢复 | 不自动跨scope/改生产/收费优化；候选不能先激活再补测试 |

## 视频与音乐正式交接

writing/fiction产StoryPlan和事实/台词保持项；audio/music-selection与beat-analysis基于Story段落选择有权利的真实音乐、phrase/beat锚和MusicCue；video/precut可回传预剪/难以匹配的段落，不直接改已确认事实。详细分镜消费adopted MusicCue而非BGM占位文字；必要改变返回Story owner和阿极确认影响，不单方面重写故事。

video/montage-board、camera-design使用同cue/timebase，visual资产专家负责身份/状态，provider专家仅编译当前接口，不代替真实调用。最终audio声音owner消费已采用Timeline、SRT/对白、music/stems；剪映同步/非同步两路选择以实际profile，模型自带声音不自动等于可分轨可替声。

换第3句对白→该voice/SRT/cue窗口/声音自动化/最终导出失效；未受影响图像/BGM不重做。换music phrase→对应预剪/Shot时点/转场/相关声音/导出失效；story事实保持。时间线变版→所有受影响anchor检查失效，不用旧音频验收新工程。

## 每接口必需责任

输入owner及exact ref、采用状态、schema/timebase、授权/权利、锁定版本、输出producer、独立validator、失败类别、局部rerun范围、取消和unknown恢复。失败返回负责人，不让专家自由互调形成循环。不存在工具/原文/免费范围时输出BLOCKED和可恢复引用，不编假音画文件。
