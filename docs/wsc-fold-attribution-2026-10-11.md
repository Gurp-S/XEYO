# 批次75：历史提前压缩归因与离线账本隔离

范围是批次62保存的六场真实会话、20次折叠，不扩成当前全局账本统计。离线产物：`_wsc_out/fold-attribution-2026-10-11/report.json`；无API调用。

|历史原因|次数|能确认的结论|
|---|---:|---|
|size_gate_fold|5|旧尺寸自动折叠|
|worth_fold|12|旧费用收益自动折叠|
|forced|3|强制折叠，入口来源与当时版本缺证，暂不归因|

GUI滚动会话尺寸折叠的region估参22362；前0.619秒厂商输入25813，后2.031秒输入14253。这支持用户指出低占用时提前折叠的问题。相邻请求仅提供时间对照，不证明精确请求关联，也不等于模型容量证据。

12次worth日志中3次prompt_basis=last_prompt_tokens，9次region_raw。后者661751至1184044等值来自历史原文估算，不能声称实发上下文超过1M。5次尺寸与3次强制未记prompt_basis。region/head/tail不能加总冒充完整请求。

3次forced发生在同一真实会话约11秒内；相邻厂商输入分别80984→27048、28857→29879、29879→26493。附近真实原文只有Bash/Edit/Read/Glob/Diagnostics等调用，不能证明由模型Compact触发；也不能据此认定85%触发或离线测试。保持未归因，未来需要入口、容量、完整请求身份与代码版本证据。

发现另一结构性缺口：共享离线environment设置了HOME/session/spill，却遗漏独立的XEYO_USAGE_DIR。usage ledger不随HOME迁移，因此既往离线force可能向真实全局账本追加事件。私有会话与冻结头隔离通过不等于全局账本隔离通过；不能继续声称离线测试完全不写全局用量。

规则修复：离线环境统一设置私有usage目录，进入/退出时恢复原环境。原有账行不删除、不改写；六场选定会话统计与全局统计必须区分，无法证明来源的forced保留未知。

实际回归在假共享账本预置原字节后执行真实force，确认游标推进、私有c2账行生成、共享三类账本逐字不变、退出恢复路径。与实际Read域回归联合3通过。审计读前后snapshot及原events.jsonl SHA256一致。

本批文件：`python/evals/wsc_unfolded_source_ab.py`、`python/evals/wsc_fold_event_audit.py`、`python/tests/wsc/test_offline_usage_isolation.py`及本文/总账/逐批账本。未修改生产压缩触发或冷卡默认。17/20已有原因标签，3/20缺来源；T14d仍开放。T16复杂实际续接、无声明与真超容量，T13/H22任意位置召回也仍开放。
