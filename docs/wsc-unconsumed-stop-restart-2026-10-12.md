# 批次170：成功交接后容量停止的未消费结果续接

验收边界：隔离交接成功不代表主任务模型已消费工具结果。若完整请求在一次折叠后仍超容量，必须停止主调用；后续落盘恢复并以可容纳请求继续时，未消费结果的调用身份与完整正文仍进入主模型请求，不重复交接、不改已有转录前缀。

本批复用正式 query_loop、TodoWrite、转录持久化、WorkingSnapshot flush/hydrate 和投影缓存清空路径。模型为确定性测试替身；恢复为同进程从磁盘加载，不能写成独立进程或真实模型采用证明。

- 两条 WSC 通道分别增加一例：约14KB多行未消费回执 → 成功结构化交接 → 一次折叠 → 超容量停止 → 保存并恢复 → 工具定义缩小 → 主调用获得完整正文与原调用身份。
- 断言原转录前缀、原消息、预算记账、一次交接、停止原因及恢复后转录不再追加交接；折叠游标不越过未消费边界。
- 首次结果26通过/2失败：测试错误地在列表字符串表示中查找带真实换行的原文。改用一致JSON编码比较，不改变正文或生产行为。随后三个相关模块37通过。
- 生产代码修改0，付费API0。没有扩大工具输出热保留预算，也没有新增模型提示或开关。

改动文件：`python/tests/wsc/test_handoff_capacity_loop.py`。

验证命令：Python 3.11，`-B -m pytest python/tests/wsc/test_handoff_capacity_loop.py python/tests/wsc/test_handoff_failure_continuity.py python/tests/wsc/test_late_receipt_boundary.py -q -p no:cacheprovider --tb=short`。结果：`37 passed in 6.36s`。

此结果补齐成功交接后硬容量停止与磁盘恢复的执行层组合，不能替代复杂真实长任务、多次折叠后迟到媒体的模型采用、线上1M容量或迁移证明。接下来仍按169顺序先做功能效果，费用与缓存收益最后。
