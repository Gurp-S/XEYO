# 厂商明确输出截断后的交接恢复：三轮复审

285保留四分支原失败：22次API/22usage、旧费率估算0.15587816元，交接0/4；回退后的实际文件4/4且正常结束。六次handoff响应中四次finish_reason=length、completion_tokens=2048，三次全部2048为reasoning；另一次reasoning1960。原anchor与对照都失败，不能给anchor宣称语义或任务收益。

## 一：根因、层边界与最小规则

语义模型还没有完整提交声明，不能归为Guard语义错或anchor误删。原wsc_handoff_output_retry只处理生成工具参数的invalid_json+实际耗尽，而model.stream_end在length/max_tokens处提前抛ModelProtocolError，导致这个恢复分支不可达。静态DTO大小估额也不能保证思考后还有正文额度。

通用provider结束边界新增一个保持原父类/原错误文本的明确类型，只有厂商length/max_tokens使用；handoff只处理此类型。绝不解析自然语言错误、网络响应正文或普通ValueError来猜截断；refusal/content_filter/断流/HTTP/取消仍原样失败。

## 二：失败时间轴与状态所有权

这是独立只生成声明的请求，尚未执行任务工具或提交TodoWrite。完整厂商截断事实允许在相同有效请求上增加输出额度生成新声明，不回放不完整助手帧、不制造缺工具结果。每次输出倍增至既有8192上限，仍共用MAX_REQUESTS、caller admit_next、免费预计数/完整容量和费用限制，usage先记账；下一额度放不下时不发送。

没有HTTP传输重试：每次新模型调用有不同max_tokens并记账；HTTP/未知断流不得触发恢复。所有原调用/费用/失败保留；到上限或调用上限仍失败时沿用原状态与原文回退。上一代或冻结头不改。

沿用既有XEYO_WSC_HANDOFF_OUTPUT_RETRY默认开启及显式0禁用的配置边界；不是新增旁路开关。新恢复默认接生产，也不能绕过用户已有的显式禁用。

## 三：替代方案、审查与前后验证

否决关闭thinking来让测试过、一次把所有请求改为巨大额度、按测试目标拼接正确checkpoint、把截断片段写入历史。已有invalid_json恢复保留原行为，统一上界但不重新定义它。新策略模块只返回机械上可用的下一额度，生成器是唯一循环/预算所有者；事务所有权不变。

需要正例：真实finish_reason=length/max_tokens，在完整请求不变且额度增加后接受有效声明；引用/phase拒绝合同仍保持。反例：非截断、取消、未知usage/有限总预算、8192仍截断、MAX_REQUESTS到界、下一额度容量超限、半个工具帧不得提交或回放。生产normal-stream父异常类型兼容。复用285原响应离线重放；再使用同协议、原始失败保留的独立小额行为对照，交接与回退、产物与静态状态分别记账。

正确有收益即接入真实交接，不作为永久旁路；这不关闭U2–U6、长任务、原228及生产薄投影TODO。
