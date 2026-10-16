# WSC 折叠后补到结果的模型使用（批次126）

## 本批验收

上一批125完成耐久恢复观察/真实执行结果归因与冷层边界，本批证明模型是否真的取用后来结果。新增python/evals/wsc_recovered_result_behavior.py：同一合成来源、同一目标、同一后来Read结果，比较未折叠与fallback/native实际fold；所有请求使用现有默认关续接候选。未折叠组不是旧默认策略组，不声称候选对默认的完整A/B。

目标与基线100只在原始用户目标中，模型输出任务身份、实际ledger_total、差值、证据调用ID及观测状态。24条工作记录含sample_total=173干扰；后来真正结果ledger_total=137。最新用户句只说继续当前核对、输出约定JSON，没有再提供答案或重述目标字段。

三组均六项检查通过：任务reconciliation-125、实际137、差值37、证据pending、状态observed及合法JSON。两组fold均游标21，原调用/未知观察已折叠，真实结果此后追加；冻结头不变、重启投影相同、原来源不变，请求序列守卫通过。此处是合成轨迹的真实确定性压缩及实际模型调用，不是现场私有会话或85%水位运行。

原始证据目录：_wsc_out/recovered-semantic-2026-10-12-126。每组保存request.json、response.json、projection.json、report.json；两fold组另存before.json。预审离线目录为同名126-review，未调用API。接口固定官方api.deepseek.com、deepseek-flash、非思考、max_tokens384、无重试，共3次调用。

## 当前请求与成本

厂商prompt_tokens：未折叠5377、fallback2079、native3530。相对同源未折叠，输入减少61.34%和34.35%，本例目标/结果六项都保持。三组cache_hit均0，不能推导一般缓存收益或97%命中。输出分别39、39、30。

现有评测Budget峰时人民币计价口径合计估算0.022836元，每次估算0.011066/0.004470/0.007300元；发送前字节预算加双倍输出预留分别0.086272/0.044126/0.052254元，均低于用户单次0.5元和本轮0.4元。usage不是账单，不能从三次usage反推出厂商单价。当前官方英文价格页列美元，故以上保留为现有计价口径估算，不能称为实际扣款或已复核人民币价格：[官方定价](https://api-docs.deepseek.com/quick_start/pricing/)。

## 容量计量反证 T14d

不增加API，用同三次原始model-stage消息重建输入，逐一确认client.context_input等于已发送body的messages/system/tools，再运行生产request_measure。

完整请求UTF-8/4估参与厂商输入：7907/5377（+47.05%）、2661/2079（+27.99%）、3677/3530（+4.16%）。正确审计见measurement-audit-corrected.json。第一次辅助脚本错误地把已编码wire消息再交给模型编码，导致未折叠组丢掉一个孤立结果，所得measurement-audit.json不作为证据；原始API请求未受影响，已纠正为编码前消息并明确核对输入相等。评测模块现内置同口径核对和误差记录。

这说明即使完整请求范围正确，字节估参仍可能提前触发水位。不能用这三个样本拟合统一倍率、累计usage或已生成usage当下一次真实计数。T14d保持开放：已支持的官方免费预计数路径需真实兼容证明，其他厂商只能诚实标估算；需要匹配模型版本的官方计量依据才能进一步改善。

另一次免费GET官方/models取得Flash当前context_window=1048576、max_output_tokens=393216（official-models.json），现有vendor_models解析两字段正确。评测显式context_limit=1000000是夹具容量，且以force触发折叠，不可声称本批验收了现网80/85边界。厂商字段表明应区分产品“1M”称呼与实际整数容量；不以旧型号名前缀表覆盖会话明确容量或厂商声明，也不因旧usage达到某数字就猜最大窗口。官方资料说明实际输入数以usage为准，离线tokenizer及图像计量有估算边界：[Token用量](https://api-docs.deepseek.com/quick_start/token_usage/)。

## 完成边界

本批没有生产逻辑修改、默认候选推广、旧冻结/冷对象/会话改写或部署。新增可复用验收模块；未追加代码测试。125的90项针对性通过范围不变，三项旧恢复合同失败仍后置。

T18新增“真实fold后模型采用补到结果”有限证据。T16复杂真实长任务、T18真实媒体/主链默认可用性、T14d实际计量及T13/H22/T11一般收益与迁移仍不能勾完；Goal不完成。下一步固定围绕当前完整请求的计量来源及已验证续接的默认准入边界，禁止再以外围bug或样本倍率代替。
