# D：声明、Guard、持久状态的合同矩阵

此表覆盖 source_schema → inline scope 编译 → 原生 validate 的传递依赖 → commit 的职责边界。它不是“schema 与 Guard 接受集完全相等”的承诺：专用生成协议有意比通用 TodoWrite 窄；字节、来源、时序、事务不能用局部 JSON 形状替代。源码优先，语义支持始终不由本表证明。

| 合同 | schema 能表达的部分 | 执行权威与范围 | 语义仍未验证 |
|---|---|---|---|
| 完整声明 | 根对象、todos/checkpoint 必需、merge=false、已知字段 | wsc_handoff_validation、parse_input；48KB总输入、checkpoint16KB预算 | 全量声明是否遗漏真实工作 |
| 步骤形状 | id/content/activeForm必需且非空白、status枚举 | todo_item_from_raw 校验内容/状态并去周边空白 | 步骤是否适合目标 |
| 步骤持久身份 | id字符串；JSON uniqueItems不能表达跨不同对象的同ID | **303修复：parsed.todos最终ID唯一**，保留原始类型/非空检查；通用工具不改 | 是否把两个不同工作错误地认成同一步 |
| 活跃上下文 | 含pending/in_progress时objective、context必需且非空；相应通道phase_state必需 | validate活跃检查；终态/空清单仍允许空目标 | 目标是不是当前用户任务，是否误报完成 |
| context来源身份 | 小目录已知ID枚举、数组大小；大目录不塞完整枚举 | validate上下文在原消息中唯一，不把调用ID当消息ID | 这条来源是否适用于当前目标 |
| 精确引用事实 | source_message_id/quote/同项scope形状、数目；可引用源ID枚举 | validate_facts：唯一且绑定context、原文子串或同字段完整已提交值；generate要求引用对象 | 引用是否支持结论、约束是否已过期 |
| 同项scope编码 | 每事实附scope，phase/task类型 | to_native无损转旧持久格式，拒绝混用/缺scope，不自动补猜 | scope归属是否正确 |
| phase内部身份 | current、phases、来源数组及fact_scopes形状 | task_phase.validate：当前ID存在、阶段ID不重复、来源已绑定、scope阶段存在 | 候选自报的phase不是独立runtime registry；分配语义未知 |
| phase来源/转移时序 | 非空来源形状 | handoff_phase：原始文本或有效回执资格；变化有晚于旧checkpoint的事件 | 事件是否真的改变阶段 |
| 已绑定context遗漏 | context_disposition对象/字段 | handoff_bindings：最新base、遗漏集合相等、引用祖先仍算绑定 | 退休是否符合用户意图 |
| task-wide事实退休 | fact_disposition完整记录形状 | handoff_fact_disposition：base唯一/匹配、遗漏集合、事件唯一且在后、角色与原始文本 | 后续事件存在不等于语义支持退休 |
| 进度/未完成步骤遗漏 | 步骤状态枚举 | handoff_progress：变化或遗漏有新文本/有效迟到回执 | 完成、取消或重开是否真实 |
| 验收调用身份 | tool_call_ids独立命名空间/枚举 | validate：调用和有效结果各唯一、调用在结果前、未完成/取消回执不合格；恢复结果按原typed链解析 | 工具调用成功不等于任务验收成功 |
| 同阶段验收连续性 | 引用数组形状 | handoff_verification：活跃同阶段不能静默丢旧验收绑定 | 旧验收当前是否仍能证明目标 |
| execution observations | observation对象/字段、枚举/容量 | task_observations：来源绑定、当前阶段观察不遗漏；不把AVAILABLE冒充CONSUMED | 模型是否理解并正确利用回执 |
| 批次与调用身份 | 工具单次输入schema不表达批次互斥 | handoff_batch/generate：声明独占、非法批次0执行；原调用ID唯一；原帧不改 | 模型选择工具/提交时机是否合适 |
| 生成资源 | 单个声明可表达局部数组上界 | generate：原6请求、累计读/字节、全请求容量/输出预留/费用准入、取消；明确输出截断才增长额度，无HTTP重试 | 更长生成不保证更好语义 |
| 引用呈现与恢复 | ID/count仅是事实 | coverage/anchors/delta：只记录实际发送材料；quote祖先精确追溯、预算整条准入 | 看过不等于理解，存档不等于有效恢复 |
| 提交与持久化 | schema不表达事务 | transaction：源fingerprint不变、真实工具执行/回执、失败不伪造完成；新声明再次全Guard；commit返回mechanical VALIDATED、semantic UNVERIFIED | 已存状态不成为语义真值 |
| 发射、冷层、冻结恢复 | 声明schema不表达完整发射 | projection/head_store/publication：seal/cwd/cursor/layout/交界/冷产物校验；普通请求不能授权新代 | 当前生产热层是否过重、冷材料是否被正确用仍须行为验收 |

## 303 实施与证据

三轮实质评审见 `wsc-D-shape-contract-three-reviews-2026-10-15.md`。只修改上述持久ID和已有活跃形状，并为相应机械拒绝接既有有界纠正；未新增语义规则、状态存储、flag、自动目标、预算或HTTP重试。

独立证据库303安装隔离的jsonschema4.23.0，仅用于免费Draft2020-12验证，不增加产品或测试环境依赖。新旧schema均格式合法；同15输入比较中，缺目标、空白目标、空context、空白ID/content/activeForm六类原schema接受、现schema拒绝。不同对象的同ID和未知phase仍可能通过schema但由Guard拒绝，明确展示跨字段职责；任意无关自然语言objective仍可通过机械Guard，不能叫语义正确。见 `_wsc_out/wsc-shape-contracts-303/comparison.json`。

归一化碰撞原Guard接受、两个持久ID均report；现Guard以原错误码拒绝并给出重复持久ID。单个周边空白ID继续按原规则解析。非法输入不会被修改，生成器实际原始帧照原字节回传；只有模型下一份有效状态可提交、恢复和折叠。

## 自己发现的问题不遗漏

303扩展15个文件定向检查得到**226通过、1失败**。失败是既有 `test_recovered_result_can_commit_after_fold_without_changing_frozen_head`；单独重跑及替换成封存302旧validator均相同失败。不能声称全套通过，亦未降低原断言。

免费运行追踪已定位路径：首次显式fold的WSC收益门拒绝，`project_c2_messages`330行返回None，runtime安装了C2 fallback摘要；随后普通请求没有可验证WSC缓存，248行返回原始messages，先前fallback头不再被发射。原有working fallback摘要缺少与WSC头相同的完整seal/publication校验，不能简单信任summary非空或绕过Guard恢复。证据303/frozen-trace.json、frozen-before-change.xml与final.xml；旧冻结文件未修改。本项单列待修，后续必须在发布/复用生命周期上闭环，不能用更宽松的头复用掩盖。

## 不得被本次矩阵替代的固定 TODO

- [x] 机械合同按形状/来源时序/事务/语义未知分责；最终持久ID碰撞修复、活跃形状和中性错误续接。
- [ ] fallback生成已经安装后，普通发射及重启能验证并复用同一代；收益门/冷产物失效均不得静默重建或回用未验证头。
- [ ] U2 epistemic独立维度；U3显式transition、fact版本/关系；U4重要转移强制原始anchor；U5来源与语义支持完整边界；U6权威runtime phase registry。
- [ ] 控制用途污染旧任务目标，候选split未准入；不靠词表删objective，不以接口schema当语义评审器。
- [ ] 生产薄renderer、精确Read/媒体完整恢复链、安全去噪/UsefulLoss；本轮未跑付费API。
- [ ] 真实1/3/5/10代及重启/迟到/未消费/过期/范围/取消/重开/失败、独立留出任务、原228底线和最终同条件A1；最后经济性。Goal保持active。


## 2026-10-15: 303–304 持久身份与fallback发布闭环

结果、文件及固定TODO：docs/wsc-D-shape-and-fallback-results-2026-10-15.md。默认已修：最终持久ID归一化碰撞；已有活跃声明必需形状与Guard对齐/有界中性恢复；收益门fallback代复用同一head_store发布验证与_emit，显式无收益沿用原头时持久化本代身份。旧冻结头字节和旧冷对象不改；无新flag/状态存储/迁移/模型调用，未重启现场XEYO。

最终20文件定向277/277，隔离Draft2020-12同15输入对照；API0/费用0。原失败回归在旧302validator下仍失败，新实现原断言通过。304本地真实工具提交/落盘/fold/hydrate重建：cursor18→20、region_end保持18、头和旧冷对象SHA不变。来源是构造fixture，不伪称真实长会话/模型续接；第二次没有多吸收历史。

303中226通过1失败及实施首次重启失败均保留；11项新夹具错误是隔离后忘开WSC，另有1项旧默认OFF断言与现有恒True主路政策矛盾，保存旧测试后校正测试，不改生产开关。最终完整277通过，旧失败不抹、不重复累计。303合同矩阵中fallback未完成行按本追加闭环，本地范围已完成，不升级成现场/六轴通过。

固定未完成方向不变：控制用途污染/split仍候选；U2–U6完整状态协议；生产薄投影/模型按需精确Read与媒体/UsefulLoss；实际1/3/5/10代与异常/独立留出/现场重建；228底线和同条件A1；最后经济性。仍不能宣称超过A1或全面治本，完整Goal active。
