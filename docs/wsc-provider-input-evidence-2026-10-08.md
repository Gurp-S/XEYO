# 批次38：原生厂商请求计量对象对齐

## 根因与规则

最终完整请求的计量入口支持`model.context_input`，但独立DeepSeek和原生Anthropic客户端未实现该接口。此前实际发送采用各自编码器，容量检查却按通用消息量字节；system抽离、工具结果转换、签名思考回放和图片转换等形状可能不同。OpenAI兼容客户端已有接口。

规则：容量计量的输入对象由实际发送编码器生成，读取其messages/system/tools输入字段；密钥、认证头、输出预算、温度、流式选项不属于输入占用。不在引擎中另抄一套厂商转换规则。

新独立`python/model/context_input.py::from_body`只提取上述输入字段。`python/model/deepseek.py`、`python/model/anthropic.py`新增接口并调用各自真实`_build_body(..., stream=False)`。无网络、无厂商计数调用、无新开关；发送编码本身没有改变。纯转换中的现有媒体物化机制仍按原客户端处理。

## 验收

新`python/tests/wsc/test_provider_context_input.py`六条：两厂商分别检查系统、真实工具配对、回执、有效图片、各自可回传思考内容；计量对象等于实际编码输入字段，消息/工具原对象不改，空tools/system不伪计，输出预算/温度/思考生成设置不改输入占用。签名thinking用内部text/signature格式，无签名reasoning按各厂商既有转换，不编造签名。

联合完整请求时机、重试、原生Anthropic运行/适配、DeepSeek账本：69 passed（7.01s）。API支出0；不修改原XEYO会话、冻结头、运行服务或生产80%/85%水位。

## 未完成边界

对齐的是请求对象，不是精确tokenizer。`provider_normalized_input_utf8_quarters_estimate`仍明确标为估参，3272估算/4771厂商实际差异未由此消除。图片base64字节不能等同视觉token，也不能拿累计usage替代下一次请求。T14d保持未勾：还需精确厂商计数能力/真实容量来源/媒体与输出余量验收；未登记容量时不能凭型号字样猜窗口。模型长期漂移及线上证据仍按总账继续。
