# WSC Goal 完成后处理的 bug 队列

用户最新顺序：优先完成Goal，过程中收集其他bug，Goal完成后再修。仅直接阻碍Goal或破坏冻结/来源/任务连续性的缺陷在当前解决。用户10-12已解除测试/编译/API限制，并授权同范围后续真实派生请求至官方DeepSeek；单调用费用上限仍有效。

本文件仅记录此前已经定位的项目，不为收集bug扩大扫描。

- [ ] UI-only转录写入没有接入普通正文身份核对。证据：`python/session/record_transcript.py::record_ui_thoughts` 按known ID跳过，不核对正文；需要先明确前端thought快照是否允许更新，不能直接套消息不可变契约。
- [ ] 明确删除会话后的转录缓存生命周期未清理。证据：删除入口清理磁盘及pool，但当前record的路径known缓存和transcript_identity索引没有对应清除入口。并发删除/队列所有权需统一核实，现不扩展删除流程。
- [ ] 无ID旧转录行恢复采用随机默认Message.id，跨恢复身份兼容未闭合。证据：`python/session/hydrate.py::message_from_row` 缺ID时未传id；不擅自重写旧行。
- [ ] 旧恢复测试合同：批次125运行test_hydrate_outcome_facts确认三项失败，两项期待旧进程台账措辞、一项期待无结果即TOOL_NOT_STARTED。先核对台账启用状态与实际事实合同再改断言；不能恢复没有结果即未执行的错误推断。不是本批90项针对性通过范围。
- [ ] Read旧测试与现有结构事实合同不一致：140五模块36通过2失败；旧schema独立恢复也复现test_read_line_semantics的结构视图旧措辞、显式范围不含总行数断言失败。先核对已有structure_hint的默认及事实文本合同，不因本批工具说明变化改执行或弱化断言刷绿。证据 `_wsc_out/read-contract-2026-10-12-140/baseline.json`。

四块核心Goal缺口（默认迟到续接、准确容量、信息收益/召回/迁移、真实长任务连续性）仍在主总账，不移入这个事后队列，也不因记录本文件视为完成。
