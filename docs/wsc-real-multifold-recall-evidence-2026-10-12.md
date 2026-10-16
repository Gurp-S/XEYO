# WSC 真实会话多次折叠/恢复与冷召回（批次129）

本批回到T16/T13真实来源验收，不扩大到外围bug。来源仍为_wsc_out/report-state-cycle-2026-10-11-a/transcript.jsonl，293行；只在新目录重建。新增wsc_real_report_continuation的cycle_recovery选项：先在前一个成功检查点后force、追加已有新事件、再force、flush/hydrate后核对完整发射相同。receipt_binding显式启用既有候选，其他默认不变。

两组native均游标283→287、追加时旧冻结头相同、第二次折叠后完整重启投影相同、来源字节不变。头19531字符，不是token。不是在真实1M窗口等到85%才触发，也不是继续执行原会话的代码修改或gate。

## 新反例与对照

第一组普通核对问题包含当前phase、待办状态及最后A/B回执两条原文。模型正确回答phase-bc-receipt和6completed/1pending，却未Read，原文字段null；它已指出正确不可变来源和offset1095/limit60，随后以“不在WORKING SET”推断需授权。

本地真实Read同一来源2/2精确返回，源/输入/冷对象保持。因此不是存档缺失或该Read被工具拒绝；本样本不足以证明所有生产权限。没有为诱导弱模型而增加引擎导演文本、放宽权限、重新热化原文或改变工作集。

第二组仅在评测用户问题增加“用Read读取所需历史存档已授权”，其余同源/开关/两次折叠与恢复不变。模型先误读两份旧工作区产物，隔离评测正确拒绝path outside archive；再读正确冷源，2/2逐字原文和调用身份准确。此组是显式用户请求对照，不能把额外请求措辞作为引擎修复或自然召回闭环。

两组都没有重做已完成步骤，pending gate保留。按原始291行TodoWrite输入及292成功回执独立核对，phase与7个待办状态完全一致；显式checkpoint.verification_call_ids是5项，模型两组均额外列出当前TodoWrite提交ID call_00_JJ0H8MO8jAUL7lcigSjk2757，严格身份集合检查失败。此项说明验收绑定集合与状态提交回执的角色区分尚未证明；不把所有已展示执行回执自动当验收成功。

## 文件与数字

仅修改python/evals/wsc_real_report_continuation.py，新增离线双fold/恢复及回执绑定参数/报告；未改生产逻辑。本轮没有新增代码回归测试。

证据：_wsc_out/real-multifold-2026-10-12-129、同名129-review与129-explicit-read。phase/input.json、report.json、answer.md、cold-receipt-audit.json、state-acceptance.json分别保存实际请求、回执、回答及独立核对。局部真实FileReadTool能取回并不等于模型主动取回。

第一组1次API、0Read，input14883/output697、hit1920/miss12963，现有计价口径费用估算0.0315788元。第二组3次API、3Read（2拒绝1成功），费用估算0.01280088元。合计4API、0.04437968元，非扣款账单；每组≤0.4元、每调用≤0.5元、无重试，官方DeepSeek，用户已有同范围派生请求授权。原源/所选旧产物不变，无部署/默认启用。

## 固定下一步及完成边界

T16新增真实多次折叠/重启后的阶段与待办保持证据；T13自然冷召回失败，T16复杂执行及精确验收角色尚未闭合。下一步核对状态投影中“显式绑定验收”与“检查点提交/其他执行”是否有充分结构区分；保持原身份/来源，并从声明及成功回执推出角色，不能靠工具名关键词或模型导演提示。冷召回继续区分当前文件入口与不可变历史证据，不能据一次显式Read成功推广默认。Goal仍开放。
