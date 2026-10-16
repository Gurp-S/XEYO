# 批次80：大未消费结果与迟到回执的完整主链边界

## 合法配对的大结果

新回归经过真实query_loop、MessageStore、工具声明提交与transcript落盘，模型流受控，API0。原生/回退 × 260000/420000 ASCII正文共4臂：

- 260000正文引发容量准备，交接和后续主请求均完整观察到原始结果（按tool_result_text比对完整正文，包含首尾及换行，不按几个标记计成功）；源对象与已持久前缀不变，fold不越过保护调用帧。
- 420000正文使专门交接请求本身超过100000容量，任何模型流开始前停止，原因handoff_request_exceeds_capacity；游标0、原文与磁盘逐字不变。不能把这一停止称为任务续接成功。

该覆盖为合法相邻工具帧，不证明所有迟到/非相邻结果恢复。

## 发现绕过WSC的迟到结果丢失

最初将调用与结果之间放入后续assistant消息，完整主链四臂都没有观察到原结果：进入query_loop时的配对修复先用discard_unpaired_tool_results清掉迟到结果，再给原调用补[tool aborted]。此前直接force/重建保护边界测试没有经过这层；不能用它们声称端到端晚到回执已保全。

本批增加独立session/late_result_guard.py，识别唯一已知调用、唯一实际回执却非当前邻接帧的序列冲突。配对修复不再把该真实回执当“缺失”；主循环在任何模型调用/折叠前返回中性tool_result_sequence_conflict，原store对象保持。新实际主循环回归确认原对象/正文不变、模型0调用、游标0。

**当前是防丢失的保护性停止，尚不是迟到结果的可用续接方案。** 完整方向固定为原时间线/来源身份不改，合法provider表示另做只读投影；hydration也必须沿用同一无损边界。不能移动原历史行冒称结果早已消费，不删除源，不伪造中止结果，不能无限停住会话便称治本。未知/重复身份尚未由此唯一身份规则解决。

## 测试结果及限制

相关未消费容量、晚到force/恢复、容量交接及请求时机：39通过。扩大检查配对修复/中断/hydrate旧契约后：**44 passed、3 failed、1 xfailed**。未引入skip/xfail。

3失败均来自本批未改动的test_hydrate_outcome_facts：期望进程台账两类旧附注及只读工具TOOL_NOT_STARTED，现实现返回TOOL_OUTCOME_UNKNOWN。单独该文件复现2通过/3失败；没有修原测试掩盖，也不宣称扩大检查全绿。原有xfailed来自未配对调用套件。

本批改动：python/session/late_result_guard.py、python/engine/query_loop.py配对修复/入口、python/tests/wsc/test_unread_result_capacity.py及文档总账。未改真实会话文件、既有冻结头或hydrate实现，未上线/重启。API费用0。

T18新增迟到序列源保全/恢复与合法请求续接（含旧恢复契约核对）；T16复杂实际执行/未声明规范/超容量连续性，T14d精确计量，T13/H22跨任务召回继续开放。goal active。
