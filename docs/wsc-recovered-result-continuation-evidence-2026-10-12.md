# WSC 恢复观察后真实结果续接（批次125）

## 结构性根因与合同

恢复生成的“执行结果未知”观察和后来真实执行结果共用原调用ID。此前序列检查把它们都当作执行结果：停止请求虽避免发出非法重复原生结果，却使真实结果无法续接。不能用文字UNKNOWN、消息ID前缀或complete=false豁免重复；真实截断结果也可能complete=false。

新恢复观察记录耐久recovery_observation：kind=outcome_unknown、origin_message_id及原tool_use规范化正文SHA-256。只有唯一原调用、唯一绑定观察和唯一后来结果构成可核验链时，候选投影保留旧原生调用及观察，后来结果以事实追加。旧转录没有类型绑定、调用正文被改、两份真实结果或多个观察仍拒绝。哈希是结构归因证据，不是外部输入的认证签名。

来源层保留两条事件；验收收集排除被实际结果取代的未知观察，保留真实结果自身的完整/截断状态。原调用已进冷层时，从完整存档核验同一绑定，配对保护与尾部发射共用同一只读补充投影，不拉回旧调用，也不改冻结头。

## 改动文件

- 新叶模块：python/session/recovery_result_chain.py。
- 恢复及存储：python/session/recovery_event.py、hydrate.py、message_store.py；python/engine/query_loop.py。
- 请求表示：python/session/late_result_guard.py、late_result_projection.py。
- 冷层边界与验收：python/memory/runtime.py、wsc_execution_boundary.py；python/synaptic/task_verification.py。
- 审计与回归：python/evals/wsc_receipt_sequence_audit.py；新增python/tests/wsc/test_recovery_result_chain.py。

本批复用XEYO_LATE_RESULT_PROJECTION，仍默认关闭，未新增开关。新生成未知观察的类型持久化已接恢复路径；合法补到结果的请求投影须显式启用现有候选。没有工具描述变更、生产会话操作、部署或旧对象重写。

## 验收数字与证据边界

七模块90项针对性回归通过：test_recovery_result_chain、test_late_wire_prefix、test_late_result_projection、test_mixed_late_receipt、test_late_media_identity、test_task_continuity、test_task_phase。最新增加自包含观察类型和审计断言后，受影响的recovery_result_chain模块15项重新通过。不是全库测试通过声明。

覆盖两厂商真实请求编码、文字/图片、原请求前缀、六类非法绑定、候选关闭、真实转录保存/恢复、MessageStore及query_loop不吞结果、验收选择真实结果，以及两条WSC通道的折叠/冷层/重启。

离线冷层对照：_wsc_out/recovered-cold-boundary-2026-10-12-125/report.json记录中间反例，原调用已折叠后native通道改变旧头。修复后新目录_wsc_out/recovered-cold-boundary-2026-10-12-125-after/report.json两通道均cursor=21、head_unchanged=true、guard=null、actual_payload_retained=true、factual_supplement=true、restart_equal=true。before.json/after.json保留请求对照，旧证据不覆盖。

这组输入为合成工作轨迹，未知观察由真实恢复代码生成；实际走确定性fold及恢复路径。不是生产会话重建的模型效果证明。修复过程中另发现把转换仅放unfolded入口会遗漏两条主通道，已移至共同restore_tail并由两通道回归覆盖。最终元数据新增kind由受影响测试验收，早先独立输出保持原证据不重写。

扩展旧test_hydrate_outcome_facts时另有三个失败：两项旧进程台账措辞断言、一项无结果即TOOL_NOT_STARTED预期。它们未在本批修复，已入后置队列；不能恢复错误“未开始”推断来刷绿。最初新测试的is_error夹具遗漏已纠正。

API调用0，费用0。没有本批模型语义续接、真实厂商计数、一般净收益或默认推广证明。

## Goal状态与固定下一步

T18的恢复观察/真实结果身份混淆已在可核验新事件的候选中处理，局部冷层与重启合同闭合。旧无类型记录、其他不支持的归因序列仍保守停止。下一步证明模型确实采用折叠后补到的真实结果，并核对实际会话/媒体兼容及收益；取得依据后才能讨论默认启用。T16复杂长任务、T14d真实容量计量、T13/H22/T11收益与迁移仍开放，Goal不标完成。
