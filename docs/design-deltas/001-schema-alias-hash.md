# 设计增量001：schema版本与哈希域歧义修正

日期2026-10-03；P2字段一致性审查触发，不增用户功能/权限，不改批准v1.6。原baseline-1清单作为历史保存在outputs/p1/design-baseline-1.json。

- CompositionManifest.schema_version原字符串与公共头整数重复语义不一致；统一为整数1，避免两个可改schema版本事实。
- ObjectMeta与payload重复权威字段校验明确包含schema_version；专业子类型type及资产sha256不强等于公共type/对象content_hash。
- 对象hash排除仅metadata.content_hash；文件digest和complete-json digest分别有命名域，不能混用。
- 影响闭包：contracts.schema.json→30包络形状/引用→Rust冻结schema解析与包络一致性→所有公共schema正常/缺字段反例。原子语义schema引用同公共ExactRef，需一并重审$refs；领域IO/授权/专业正文未变。
- 此次尚无生产release或运行专家，不发生P7安装/数据迁移；已锁旧任务不会自动切新定义。
- 复审：P1结构1001检查/9开发期测试；P2字段一致性回归执行后记录。原设计错误不掩盖为先前运行成功。
