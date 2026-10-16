# 独立进程恢复、冷召回和报告执行（批次165–166）

## 165：真实落盘后在新进程续接

164的测试只持久化转录、没有在query_loop结束后flush工作快照。query_loop本身不是完整QueryEngine提交收尾入口，因此不能把164声称为完整进程重启证明。这是验收覆盖缺口，不是生产flush缺失。

165在新的隔离副本实际重新执行强压，原303行来源保持；收尾调用真实转录持久化和WorkingSnapshot.flush。强压仍保留8待办/7验收ID。bootstrap进程结束后，另一个Python进程通过hydrate/转录严格恢复，读取真实sidecar，恢复游标300和原7个ID。

新用户测试任务要求冷召回两条历史原文、写resume-review.json、保持gate待审批，然后调用Compact。正式query_loop中官方Flash实际Read两次→Write报告→Compact。落盘报告的8项待办、7个验收ID集合、Read描述和cleanup两条完整原文、来源调用身份全部正确，gate仍pending。旧冷对象SHA、旧转录字节前缀和冻结头前缀均保持。

第二次Compact尚未完成：生成模型先遗漏一项绑定上下文、又把context_disposition放进checkpoint，随后返回无效JSON。165评测适配器直接json.loads工具参数，提前异常；正式厂商客户端会保留 `_raw`，已有结构化错误反馈路径。不能把这次适配器异常归为生产解析缺陷，不能据error=null或落盘文件存在宣称整轮结束通过。实际StoppedEvent为 `Extra data...`，游标仍300。

165共10次生成调用：bootstrap3次估算0.07354784元、resume7次估算0.19058376元，合计0.2641316元。没有HTTP重试。

## 166：生产解析器下的模型协议失败

只复制165保存状态到新的隔离目录，保留165证据。新进程追加新测试用户消息：报告已生成，执行Compact并回报gate及验收身份。工具参数使用正式共享 `model._openai_common.finish_tool_bufs`，无效JSON保留为_raw，不悄悄修字段。Write范围仍仅隔离报告，原冷对象不可写。

首次启动复用了restart-review-user消息ID，正式转录身份校验在任何API前拒绝冲突。修验收器为新restart-compact-user，不改旧消息；0API准备失败回执保存在prepare-error.json。

修正后6次实际模型调用，估算0.14464088元。模型在有界交接请求中反复遗漏旧绑定 `18ff2975cbcc4918a9c642278d3bf3d2`，或将context_disposition放到checkpoint子对象。已提供的正式工具schema明确该字段在根对象；执行层如实拒绝，最后停止 `handoff_bound_context_disposition_missing`，游标仍300、未提交无效交接、没有第二折叠。

既有报告仍8待办/7ID/2原文正确，gate pending；源转录前缀、旧冷对象SHA和冻结前缀保持。这里是模型未能遵守可用schema、引擎安全拒绝，不是字段被WSC删掉。未自动搬字段、放宽合同、增加请求上限或添加导演提示来凑通过。

166的artifact_created布尔来自复用验收器，只表示旧报告仍存在，不代表本批再次Write。也不能将165和166各自部分成功拼成第二次压缩完成。

## 结论和下一步

- [x] 新修复后的真实源强压在完整收尾落盘后，由独立进程恢复当前绑定。
- [x] 恢复后真实工具冷召回、精确原文核对、实际报告Write；必要信息实际使用，旧目标未被执行，gate未运行。
- [x] 无效协议下旧状态/冻结前缀/冷对象安全保留，无错误提交或被迫继续。
- [ ] 模型生成合法第二交接并完成多折叠，尚未通过；不得以安全拒绝代替用户期望的顺畅续接。
- [ ] 复杂失败修订、多会话实际效用/净收益、实际新代上线迁移和真实1M现场范围保持。

固定方向是先核对实际 schema/错误反馈与模型协议能力边界，减少状态层假设；不存在真实引擎缺陷时不靠删绑定、扩大卡面或弱模型导演“修复”。当前没有新的生产源码修改。

两批总16次生成调用，新增费用估算0.40877248元。5元总预算累计2.72529048元、剩余估算2.27470952元，非官方余额，未遇402。回执：`_wsc_out/wsc-restart-continuation-165/report.json`、`resume-report.json`、`above85/resume-review.json`、`_wsc_out/wsc-restart-compact-166/resume-report.json`。Goal active，原完整范围未完成。
