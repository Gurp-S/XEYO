# 用户授权：有证实进展的修复直接接主路；首项交接原帧修复

本记录追加取代此前“新机制只旁路/长期不并入”的准入方式：用户明确要求之前与之后有进展的修改直接成为真实实现。正确性、质量不退化、三轮复审、冻结头、完整Goal与失败记录要求继续。测试驱动不接入产品，未证明收益或失败候选不机械启用。无需再次确认接入。

## 第一轮：修复根因与实现选择

生产 `wsc_handoff_prepare` 调用 `wsc_handoff_generation.generate`，后者读取模型正文/思考却只把tool-only assistant帧加到专用续接，实际读取/拒绝路径丢信息。267、273及280的真实续接已证明保留原帧的必要性和可运行性。

否决直接在主路包ReplayModel：它在stream阶段恢复帧，而context_input委托底层，容量预计数可能只看到tool-only帧，发射却更大。也否决将eval ProviderFrameModel和预算脚本导入生产。v1：原生generate本身在请求数组里放完整assistant帧；计数、准入、发送天然使用同一数组。复用现有assistant_text_message和reasoning block校验，新增模块只收集本次完成帧的内容。

## 第二轮：失败、签名与时序

每次只在stream正常完整结束后构造帧；读取与拒绝反馈都使用同一原帧，ToolUse ID/参数不改。截断、中断、无效签名或取消不构造可续接成功帧、不提交声明；usage仍由原finally记账。新模块不缓存跨请求状态，不触碰事务、frozen head、源行、schema、REQUEST或生产模型配置。

复用主模型已有消息构造语义，保留原native签名/redacted blocks及正文/思考增量；不声称修复底层parser既有的原JSON argument字符串格式问题。正反例需要覆盖display增量不重复、子额度、token计数含原帧、预算与失败结果。

## 第三轮：主链准入与验证

原267的旧结果必须保留；新回归直接调用改后的production generate，不再通过旁路包装取得通过。对比保存的旧typed原帧与新帧：读取、拒绝两条路径均证明保留；签名/中断/usage独立。再运行真实query_loop容量交接、未消费结果和失败恢复的定向既有测试，不跑无关全库、不增加付费API。

同时复用280已付费provider帧离线重放到生产generate实际读取路径，证明新原生请求正常序列化且无新增导演文本。符合对应合同后此修复在主路默认生效，不增加flag。机械22/22的AD原型、ArtifactSink、actor trace等仍必须按实际用途区分，不当作生产修复全部导入。

完成边界：主路专用帧丢失修复，非全部D优化完成；U2/U3/U4/U5/U6、长期/冷/媒体/原228与A1质量目标仍按完整Goal推进。
