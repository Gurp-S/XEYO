# 批次35：短任务真实 Flash 压缩与续接证据

生产容量仍为模型声明的1M，80%通知/85%强压阈值没有修改。普通压缩只由真实模型的Compact调用及成功执行回执触发；此次用户夹具明确请求先Compact再续接，并不证明模型在无人要求时能选好压缩时机。

## 两类验收分开

1. 静态投影后续接：离线显式调用确定性投影，再把压缩上下文发给真实deepseek-flash，不等待水位。`_wsc_out/flash-drift-2026-10-08-b/report.json`：完整历史8/8，刻意丢状态且无存档的反控0/8，现有投影7/8。后者读了验收回执但没读正确规范，source_value错误。独立`synaptic/source_description.py`为延后来源提供首行原文（160字符上限、截断标记），不推断语义、不推荐路线。修改后`flash-drift-2026-10-08-c/report.json`当前投影8/8，实际冷存档召回成功。这是单样本，不能宣称普遍不漂移；完整历史未重复付费重测。
2. 实际工具/引擎请求链：`_wsc_out/flash-compact-chain-2026-10-08-d/report.json`。实际query_loop、Compact注册、成功执行回执、确定性折叠、最终请求检查、厂商编码均保留。无模拟模型调用、无降低水位。第一请求估算3272，厂商prompt_tokens=4771；真实模型调用`call_00_czZ8FdE1pxZzD0Hwv5s67937`的Compact；第二请求估算2803、厂商prompt_tokens=4246，游标0→25。两次automatic_attempts均0。目标BILL-27、步骤verify、决策decimal_half_even、验收v-new、失败状态五项正确。6条链路检查与5条续接检查共11/11。

## 实际发现的问题和限定

- 稀疏工具历史的旧“保留三工具轮”边界让显式Compact/强压也折不了足够历史。新增明确折叠边界：近期消息下限、配对安全、未消费批次保护；扩展吸收遵循已请求游标，回退无Todo也提供完整历史冷存档。定向四组合回归。
- 只有冷材料编号不足以稳定选中来源；用限长原文首行表达来源，不加模型指令。单样本恢复召回，不作为T10/T13结案。
- 第一次工具链夹具误用了user角色工具回执，运行时修复生成中断回执，原失败答案保留在chain-b报告。实际引擎内部回执是tool角色，夹具已校正，并加离线回归。这个失败不归责生产压缩。
- chain-d原评分器只接受纯JSON，真实回答包含说明及JSON，且用failed而非未规定的error；离线提取唯一JSON、失败状态按两种同义结果计分。原始响应和original_scoring_checks保留；未为改评分再请求API。
- 3272估算对应厂商4771，表明当前估参不是厂商精确计量。这个差异在短任务不会碰水位，但85%附近的精确容量保证仍有风险，保持计量TODO开放。
- 模型回答仍引用Compact历史接受回执的execution=pending；报告只证明游标和实际投影完成，不把接受回执当完成回执。
- 不证明85%巨量请求的实际模型长期不漂移，也不证明模型自发压缩时机；测试没有恢复全部历史用户原文到热头，没有改旧冻结头/原会话。

## 成本与测试

官方人民币峰值价格作为上界：输入未命中2元/百万tokens、命中0.04、输出8，来源 https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ 。POST前保守预算拒绝、输出500或700封顶、无重试；每调用上限0.5元。三轮静态试验与两轮已发工具链试验共峰值上界0.24149064元，单次最高约0.046元；chain-d两次合计0.01885736元。预算拒绝/构造失败的两个目录未发API、费用0。不是账户账单数，真实离峰可能更低。

最终相关回归187 passed（13.40s），包括主时机、配对/冻结/重启、连续性、稀疏折叠、来源描述、预算、工具链夹具；集合覆盖前批176，不累加。此次代码已在当前工作区，未重启用户服务。

改动涉及：memory/wsc_execution_boundary.py、memory/runtime.py、memory/wsc_extension_economics.py、memory/wsc_fallback_handoff.py、synaptic/task_checkpoint.py、新synaptic/source_description.py，以及evals/wsc_drift_budget.py、evals/wsc_flash_drift.py、evals/wsc_flash_compact_chain.py和对应四个回归文件。具体请求、工具ID、响应、usage均在报告；不含密钥/认证头。
