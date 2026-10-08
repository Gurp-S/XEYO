# 批次32：完整请求85%准入与通知重试

## 根因与规则

批次31的85%检查仍在KEEP投影早期，漏了工具schema/T_now；通知在最终请求出现，却没参与强压判断。另一处是协议回退重建了请求，manifest/通知身份可能仍描述失败尝试。

结构规则：模型时机旁路下，主query_loop只让完整请求组装器决定自动容量折叠；普通投影只接受明确模型工具回执。完整请求包含system、当前状态注入、工具定义和80%通知本身；协议回退后同入口重建、重测。每次发送尝试manifest描述实际该次API消息。输出预算不冒充输入。

## 修改

- 新独立模块 `python/memory/wsc_request_timing.py`，承担最终请求组装、通知、85%判定、折叠后重建及重新计量，保留前后事实和实际cursor推进结果。
- `wsc_timing.request_measure` 提供共同请求计量入口；OpenAI兼容客户端新增纯 `context_input`，采用与实际编码器相同的消息归一化/工具包装，不包含headers/凭证/输出预算。
- query_loop旁路下跳过旧早期pressure；`project_for_model(capacity_managed=True)`不再在不完整输入上自动强压，明确模型Compact请求仍执行。
- 新代折叠后重建fence/digest/T_now，按新cursor重新决定通知；通知本身令请求越85%也触发折叠。清旧注入账本发生在重建前。
- 400声道回退重建后再次走完整准入；500普通重试保持实际同一请求。通知只在成功响应后消费。每次尝试前重建manifest，避免把失败尝试的消息数/cursor当成成功请求。
- 回退中新出现的折叠发压缩事件并清结果证据缓存；不依赖进入retry前旧compression_started布尔值。

## 触发线不是目标大小

85%是强制执行一次折叠的触发线。固定schema或当前不能退休的消息本身可能超过85%；无可折叠历史会记录no_eligible_history，不无限循环、不谎报完成，也不为了达标删除当前任务。仍超线的请求并不证明容量问题已解决，后续需要真实容量/大结果验收。

## 验证

新增7条用例：schema占用独自越85%、无可折叠历史只尝试一次；通知本身越线后新cursor重测；失败尝试不消费通知；OpenAI归一化与实际body字段相等且输出预算不参与；真实query_loop在首次发送前因schema越线发生实际fallback折叠；400声道回退和500重试各实际发送两次通知，失败未消费，成功请求才消费。

扩展运行：`tests/wsc tests/test_runtime_c2.py tests/test_notice_channel.py tests/test_c2_escape_hatch.py tests/test_c2_llm_summary_t8.py tests/test_env_switches.py tests/test_context_limit_declared.py`，1031 passed（36.99s）。随后修正容量管理早期账本forced标记、折叠前注入清账和回退中新折叠事件，再运行本次时机四文件及query_loop_plain/execution_fact_contracts，32 passed（3.40s）。两集合有重叠，不能相加。

这些是引擎实际执行链路加确定性模型替身，不是现场历史wire，也不是实际模型的长任务漂移验收。默认关闭，原会话/旧冻结头未改。

## 未完成边界

- token计数仍UTF8字节/4估算，OpenAI输入结构一致不等于厂商tokenizer一致；非OpenAI编码、回传reasoning及媒体实际token归属仍需验证。大媒体JSON占用也不能直接等价视觉token。
- 未知/兜底容量须继续审查，不能把默认128K宣称真实1M。
- C0工具结果8192字符及其他输出尺寸路径尚待修；旧目标防复活/交接状态方案必须与时机旁路合并验收，不能仅启新时机旗标就宣称续接修好。
- 真实XEYO源的时机A/B、实际模型自决、冷召回、有用事实遗漏/关联与费用，T10/T13/T14尚未结案。
