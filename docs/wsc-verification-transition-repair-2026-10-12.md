# 交接验收绑定保全修复（批次164）

## 根因与正确性边界

163真实源强压中，模型将当前checkpoint的7个验收调用身份替换为一个旧交接提交身份；旧校验只证明新身份可定位、有完整回执，未验证当前任务的验收绑定能否在交接重建时退休。引擎接受错误新声明，主模型按新快照回答，原文存档无损不能弥补当前状态变迁的缺口。

规则：已有明确阶段、仍有未完成事项的同阶段任务，交接声明移除既有验收绑定，需要该新声明选中的实际新回执作为变迁来源；回执新鲜度以有效结果到达位置判断，不以调用开始时间判断。只有旧来源、未选中的新结果、取消/不完整/含糊/损坏元数据，以及交接提交本身，均不能充当新验收来源。

明确阶段切换和终态沿用既有阶段/进度合同先校验。legacy、未观察到提交的状态保留原兼容。未退休原绑定的新增声明仍由既有身份/完整回执合同验证；新来源语义相关性由模型判断，此修复不宣称能证明模型全部语义正确。

## 默认源码变更

- 新模块 `python/memory/wsc_handoff_verification.py`：复用已有 `latest_todo_snapshot`、有效回执 `collect` 与 `observed_source`，不创建第二状态库或新字段。
- `python/memory/wsc_handoff_validation.py`：在已有事实/阶段/进度校验后执行新变迁校验；错误提交前拒绝。
- `python/memory/wsc_handoff_generation.py`：将中性 `handoff_verification_transition_source_missing` 纳入已有有界拒绝反馈。反馈仅包含已提交来源、缺失身份和声明身份等事实，不添加导演说明，不偷偷替模型修字段。
- `python/tests/wsc/test_handoff_verification.py`：17项变迁覆盖，包括晚到结果、错误/取消/不完整/损坏元数据、未选中结果、legacy、完整阶段/终态见证。

已接默认交接主链，无新旁路开关。是当前工作区源码实现，不声称线上旧进程已加载或安装器已部署。既有头和冷对象不回写。

## 验证

六相关模块 **91 passed**，源码差异空白检查通过。测试范围：verification、validation、progress、omission、task_phase、failure_continuity；不是仓库全量绿。

保存的163真实错误声明不改字段重放：仅绕过本批新规则的旧合同接受；新合同拒绝 `handoff_verification_transition_source_missing`，报告7个被移除身份及旧单ID。原149来源字节保持。证据 `_wsc_out/wsc-verification-transition-164/replay-report.json`。

同完整真实303来源、同239352声明小窗口、同查询的实际query_loop重跑：

1. 官方Flash再次先声明旧交接单ID；提交前中性拒绝，未污染主转录。
2. 第二次独立模型声明保留原7个验收ID，实际TodoWrite提交。
3. 当前完整请求参考211201 tokens（约88.24%）触发一次强压，游标300；压后17049，正式模型回答保留8项待办及原7个ID集合。

原源字节和新转录既有前缀保持。新增3次API费用估算 **0.07391736元**，5元总预算累计 **2.316518元**、剩余 **2.683482元**；没有HTTP重试。第二次交接调用是模型收到一次拒绝结果后的新声明请求，不是网络重发。

初验收按数组顺序误报ID失败：模型只是将原7个ID排序，而用户要求的是原集合。独立离线审计检查唯一性、数量与集合，全部正确；保存 `report.adapter-before.json`，不改模型输出/冻结头/原转录、不增加API复测。损坏元数据拒绝的补充边界在付费跑后添加并回归，不重复不相关API。

回执 `_wsc_out/wsc-verification-transition-164/report.json`、`audit.json`、`above85/transcript.jsonl`。这闭合163的具体交接退休反例；不是1M现场、多次复杂任务失败修订、更多媒体、多会话净收益或线上新代迁移证明。原三组最终验收及总账完整范围仍开放，Goal active。
