# WSC近期输入计量与缺省输出预留（批次194）

## 真实输入用量核对

只读185–192的最近34次实际官方Flash请求/usage，排除191重放的前三次响应。使用当前固定参考编码重新计算完整messages/system/tools，不拟合倍率、不修改tokenizer或80%/85%阈值。

- 实际输入7020–80150 token。
- 最大绝对误差7 token；最大相对误差0.0671501%。
- 输出上限覆盖384、768、2048、3072、4096；5次厂商length停止保留在样本中。
- 请求/回执来源文件SHA保持；本轮生成API0。

证据`_wsc_out/wsc-recent-input-count-194/audit.py`、`report.json`。这仍是原生Flash指定文本格式的参考估算，不是厂商精确预计数、媒体计量或1M阈值实测。

## 官方容量与输出额度

另一次只读官方GET /models返回`deepseek-flash`：context_window=1048576，max_output_tokens=393216，保存于`current-model-metadata.json`。最大输出不是缺省输出。

[官方Chat Completions参数说明](https://api-docs.deepseek.com/api/create-chat-completion/)明确输入与输出共用模型上下文，未设置max_tokens时，非思考默认8K、思考默认64K、max effort默认128K。[官方模型列表字段定义](https://api-docs.deepseek.com/api/list-models/)区分上下文总量、最大输出和仅在服务定义时出现的缺省值。来源核对日期2026-10-13。

## 旁路修复与A/B

结构性根因：`DeepSeekModelClient.context_output_limit`只读取本地显式max_tokens；官方服务采用非零缺省值时，引擎记录未知并跳过输入＋输出总量检查。该路径没有伪称零预留，但不能证明请求能容纳实际缺省输出。

规则：使用当前真实配置或已核实的服务缺省值计算预留，最大输出不得冒充默认值；未核实端点/模型仍未知。计量来源必须区分显式请求值与官方文档缺省值，不能统一标为实际请求参数。

新增独立模块`python/model/deepseek_output_defaults.py`，开关`XEYO_DEEPSEEK_DEFAULT_OUTPUT_RESERVE=1`启用，默认关闭。仅核实的官方HTTPS原点、标准路径和精确deepseek-flash ID适用；实验别名和自定义端点不推断。显式值优先，非思考8192、思考65536、max effort131072。

`DeepSeekModelClient`增加带来源的额度计量；`wsc_request_timing.finish`消费该计量，并在已知额度下沿用现有输入＋输出总量检查。没有改实际发送body、模型输出配置、输入触发阈值或冻结前缀。记录依据为provider_documented_default_output_limit，不能冒称配置值或厂商usage。

10项新回归，包含三种模式开/关A/B发送体逐字相同、显式值优先、未知原点/模型不推断、已知默认下不足容量发送前拒绝。与capacity_loop、main_timing三模块48项通过（6.65秒），见`pytest.txt`。

候选尚未默认推广，未知其他厂商/模型、媒体计量及大窗口边界仍需沿完整TODO验收。没有新增生成请求或成本；预算估算累计3.87601816元、余额1.12398184元不变，收益验收最后，Goal保持active。
