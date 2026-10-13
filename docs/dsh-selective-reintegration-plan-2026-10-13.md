# DSH 选择性回补 4.0 实施方案

日期：2026-10-13

## 目标

从 `E:/wuji-projects/dsh-wuji-legion-mode` 中提取已经真实验证、能补回 4.0 当前缺口的机制，保持 4.0 作为现有 AI 宿主上的任务优先工作体系，不搬入 DSH 的完整运行壳、插件集合、第二调度器或第二事实库。

本方案只规划 DSH 回补，不代表 DSH 已经合入 4.0，也不把目录、生成文件或历史报告当成专业效果证明。

## 当前只读结论

- 4.0 源账当前有 57 个专家职责、17 个主帅族、26 条配方。
- DSH 的 `packages/wuji-staff/data/recipes.json` 已与 4.0 `catalog/p3/delegation-manifest.json` 的 17 族、26 配方投影同步；`node scripts/build-staff-recipes.mjs --check` 已通过。
- DSH 当前根目录和 bundle 各有 17 个主帅目录、66 个专家目录。66 不是“4.0 已验证 66 个专家”：它包含 4.0 目录投影、14 个 FOREIGN 角色，并排除了 5 个 RETIRED 角色。
- 当前 manifest 的专家引用集合中，有 25 个 role id 不在 4.0 `experts.json`，另有 5 个 4.0 专家未被当前配方引用。这个差异需要解释和建账，不能直接复制文件消除。
- DSH 的 `preset/agent.cordis.yml` 和当前桌面 profile 的普通 `tool-subagent` 都已经配置 `maxDepth: 3`。`.tmp/e2e/layercheck/四层验证报告.md` 中的 `maxDepth=1` 是历史失败记录，后续验证必须标注当时的配置时间，不能当作当前状态。
- 当前 profile 已将 REA 放进独立 `preset-rea`，普通无极军团会话不加载 REA 的 139 个工具。DSH 仓库中的 `scripts/build-wuji-preset.mjs`、bundle patch 和 `software-reverse` Skill 仍描述 profile 顶层 `mcp-rea`，下一次生成可能覆盖当前结构，这是最高优先级漂移。
- REA 的 schema 压缩代理能减少 schema 体积，但现有证据只能支持“按 preset/session 隔离”和“schema 压缩”；不能把它称为按单工具真正 lazy discovery。
- 现有报告证明过参谋部工具注册、配方选择、排程和主帅 Skill 加载，也记录过专家层被当时的深度上限阻断。后续需要用当前 `maxDepth: 3` 做一次新的有界验证，不能用历史报告倒填当前成功。

## 回补边界

### 回补到 4.0 的内容

1. 主帅池和专家池的**来源账、派生投影和一致性检查**。
2. DSH 已经真实用过的主帅/专家实例的**证据分层记录**，包括任务、会话、产物、hash、revision 和独立验证。
3. REA 的**条件能力绑定**：只有 `software-reverse` 子任务和明确的逆向模式才允许挂载。
4. REA 的**独立 preset/session 隔离**与 schema 压缩方法。
5. 4.0 的**上下文预算分层**：模型规格、宿主窗口、工具 schema、压缩阈值、输出预算分别记录。
6. DSH 中已经证明有效的“生成源 → 投影 → runtime check”检查链。

### 不回补的内容

- DSH 的完整插件和 bundle。
- profile 级常驻 REA。
- 另造一个 4.0 调度服务或角色运行平台。
- 把 66 个 DSH 角色统一登记为 4.0 已验收专家。
- 把历史报告里的计划、生成文件或 README 说明写成真实专业效果。
- 把 schema 压缩写成单工具级 lazy discovery。
- 未核实宿主生效值前，机械把 240K、272K 或其他旧预算乘倍数。

## 实施阶段

### P0：冻结当前证据和写集

建立一份 DSH 对照表，字段至少包括：

- `role_id`、`family_id`、`recipe_id`
- 来源：4.0 catalog、DSH FOREIGN、历史/退役
- 当前文件路径和生成来源
- 是否被当前配方引用
- 是否有真实运行证据
- 证据等级：注册、选择、加载、执行、产物、独立验证
- `effectiveness`: `passed`、`partial` 或 `not_claimed`
- 许可证/来源 commit

P0 只读 DSH，写入 4.0 的审计/方案文档；不触碰 DSH 未提交文件。

验收：源账、manifest、recipes 投影和角色目录可以互相解释；所有差异都有明确状态。

### P1：修复主帅/专家池的源账和派生链

优先调整 4.0 的源账表达，而不是复制 DSH Skill 文件：

1. 为 25 个 manifest 外部引用逐项标记 `foreign`、补来源或修正 role id。
2. 为 5 个未被配方引用的 4.0 专家标记“冷态未配方引用”，不要自动删除。
3. 把 DSH 的 FOREIGN/RETIRED 集合从生成器隐含常量变成可核对的来源声明；如果暂时不迁移，至少生成检查报告。
4. 让 `recipes.json` 和角色生成物继续作为派生结果，不把它们升格为第二真源。
5. 将 DSH 的“66 个目录”拆为 57 个 4.0 专家 + FOREIGN + 其他状态，动态生成数量说明。

验收：重新生成或检查后，4.0 源账、DSH 投影、角色目录和文档的数量口径一致；不改变当前专家专业效果状态。

### P2：修复 REA 生成漂移

目标是让 DSH 仓库的可复现生成结果与当前本机 profile 的独立 `preset-rea` 一致：

1. 以当前已经验证的 `preset-rea` 结构为目标。
2. 将 `scripts/build-wuji-preset.mjs` 中“REA 必须在 profile 顶层”的历史逻辑标成旧路径并移除生成责任，或改成生成独立 preset 的来源。
3. 同步更新 `packages/wuji-bundle/cordis.patch.yml`。
4. 更新 `skills/wuji-expert-software-reverse/SKILL.md`，把“profile 顶层常驻”改成“逆向模式按需挂载”。
5. 保留 `failOnStartupError: false`、长任务超时和 schema 压缩，但分别记录为启动容错、任务超时和 schema 体积优化，不混称为 lazy discovery。
6. 增加静态检查：普通军团配置不得出现 REA 工具；REA preset 才能出现 `mcp-rea`。

验收：生成器、bundle、Skill、当前 profile 对 REA 的位置、加载条件和失败语义一致；普通会话不承担 139 工具 schema。

### P3：用当前配置复验真实委派

选择一个有实际消费者的研究或软件逆向任务，做一次有界复验：

- 顶层任务身份；
- 参谋部选择的主帅和配方；
- 主帅 Skill 实际加载；
- 专家 Skill 实际加载和委派；
- `maxDepth: 3` 的当前配置观察；
- REA preset 是否按条件启用；
- 工具调用或明确失败回执；
- 产物路径、hash、revision 和 scope；
- 独立验证；
- 专业效果单独记为 `passed`、`partial` 或 `not_claimed`。

只验证一个消费者，不批量启动 57 个专家，也不把一次成功扩展成全部专家通过。

### P4：上下文预算 A/B

先区分四种值：

- `requested`：用户或任务请求的窗口；
- `configured`：宿主/路由登记的窗口；
- `observed`：实际请求或失败回执中看到的窗口；
- `effective`：有可信回执证明当前生效的窗口。

测试至少覆盖：

1. 普通军团模式，无 REA；
2. 逆向模式，REA schema 压缩前后；
3. 主帅/专家链路，分别测工具 schema、历史消息、工具结果和输出预算；
4. 大输出分页回读、压缩后重建、旧证据回读；
5. 预算接近上限和超过上限的失败边界。

当前不把“500K”写入 4.0 生效配置。模型规格、官方计费分界、Codex 桌面宿主和当前代理路由的窗口不能互相替代；本项目已有预算语义修订也明确要求把 `configured`、`observed`、`effective` 和 `unknown` 分开。下一步必须取得当前宿主的 `observed/effective` 证据，再决定 4.0 是否把 240K/272K 等阈值调整为分层预算。

验收：预算策略能说明为什么压缩、为什么保留、为什么分页，并能区分模型窗口、宿主限制和计费分界。

## 建议的最小实施顺序

1. P0 对照表和差异状态。
2. P2 REA 生成漂移修复。
3. P3 当前 `maxDepth: 3` 的单消费者真实复验。
4. P1 主帅/专家源账闭合。
5. P4 上下文预算 A/B。
6. 只有 P3/P4 形成证据后，才决定是否把任何 DSH 机制回写为 4.0 的正式运行能力。

## 2026-10-14 当前实施状态

- 已落地到4.0：17个主帅族/26条配方的动态计数、4.0目录与外部引用的显式覆盖账、最短最小路由、主帅候选池、主帅 plan→专家 execute→主帅 aggregate 的一次性执行接口、真实文件/hash/scope/revision/acceptance 输入门、受影响上游的有限重做、unknown 不盲重试，以及跨主帅/专家共享并发槽。
- 已完成有界检查：`test_legion_task`、`test_legion_pipeline`、`test_p3_catalog`、`test_whitehat_entry`、`test_wuji4_framework` 共85项通过；DSH `build-staff-recipes.mjs --check` 通过。
- 仍未宣称：原生模型主帅/专家专业效果、当前宿主的有效上下文窗口、REA 生成漂移修复、DSH 当前会话的 `maxDepth: 3` 真实专业复验。Python fixture 只证明执行契约和本地回执门。
- 当前4.0 manifest 明确登记5个未被配方引用的冷角色和25个未纳入4.0正文的外部引用；外部引用被需要时必须进入 `selection_gap`，不能用DSH目录或README替代4.0专家正文。

## 当前暂停点

本方案完成的是只读研究和实施边界。下一次真正改动前，需要先确定 P0 的对照表写入位置，以及是否允许在 DSH 的大量未提交修改上只改 REA 生成相关文件。未获得这一步的具体范围前，不改 DSH 工作树。



## 用户确认的运行原则

## 团内流水线执行契约

主帅收到参谋部的一个子任务后，可把它拆成多个专家任务；每个专家任务只携带自己的目标、上游已验收输入、输出契约、验收标准和写范围。专家不需要知道团队其他成员的任务。专家任务按显式依赖和写集分组并发；无依赖的成员可并行，有依赖的成员等待上游回执。

上游回执必须通过输入门：缺少生产者身份、产物、范围或验收通过标记时，当前任务拒收，返回 `rework_upstream`，由上游重做；下游不能用不完整输入继续生产。主帅只在所有必需成员的产物通过验收后汇总回参谋部。


后续实施必须遵守三条硬规则：最短最小任务链覆盖路由、工具、输出和内部推理；小任务由阿极直办，复杂任务由参谋部激活主帅分身，再由主帅按难度激活必要专家分身；白帽与阿极绑定，保持第三方客观，不迎合也不只反驳。P3 真实复验需分别验证小任务直办、单专家短链和主帅→专家组团链路。
