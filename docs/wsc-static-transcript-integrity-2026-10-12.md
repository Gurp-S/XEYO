# 批次97：完整损坏行不静默改变恢复坐标（仅静态）

结构性根因：load_transcript替换坏UTF-8字节并跳过JSON坏行，messages_from_transcript与Todo来源恢复直接消费结果。完整中间事件损坏时，执行恢复可能缩短消息历史，导致位置游标/来源索引与实际已提交状态不一致；坏rollback marker也可能被忽略而暴露旧目标。容错展示不能代表完整执行来源。

不变量：无法读取完整来源不等于该事件不存在。复用既有load_transcript增加strict参数，展示默认保持宽容；主历史和Todo来源恢复统一strict=True。完整换行终止的坏UTF-8/坏JSON报中性transcript_corrupt_row，合法JSON却非对象报transcript_invalid_row，不记录正文。错误沿已有恢复失败路径传播，不创建空engine或替换旧历史。

未换行且无法解析的最后一行保留“未完成append”处理，不修改源，后续原重试机制可修尾。合法字典且缺终止换行仍可读取，与原重试补换行合同一致。空行及旧合法marker/UI行不因新参数被当损坏。本批不解决整个归档文件缺失、合法但语义坏的行或所有恢复游标失配；不宣称完整崩溃恢复通过。

修改python/session/record_transcript.py、hydrate.py。静态阅读load→合并surface→正文严格恢复→engine发布/replace顺序，未运行测试/编译/API/重放，各项0、费用0，无部署/冻结源修改。四块最终效果验收仍未完成。
