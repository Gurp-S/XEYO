# WSC官方Flash缺省输出预留A/B与默认并入（批次195）

承接194默认关闭的候选，先受控A/B，再更改默认值。没有发送超窗请求或调用生成API。

## 正常真实请求对照

复用194核对过的34份真实官方请求，逐份校验原请求SHA，再按原显式max_tokens与同一输入计量，在开/关两组执行现有finish准入。34/34发送体未变，准入结果及完整facts相同；原回执和输入文件SHA保持。它们均设置了显式额度，因此证明的是已有显式行为不被默认值覆盖，不是假称已观察34次缺省额度生成。

## 缺省输出边界

按194官方/models返回的1048576上下文和[官方Chat Completions默认额度](https://api-docs.deepseek.com/api/create-chat-completion/)，构造三种相同输入：

- 非思考8192预留，输入1040385，总量比窗口多1。
- 思考65536预留，输入983041，总量比窗口多1。
- max effort131072预留，输入917505，总量比窗口多1。

开关关闭时，输出仍未知，三个总量越界都未被该总量检查拒绝；候选开启时，全部发送前拒绝。前后请求体、输入占用、80%/85%判定及冻结状态没有改动。这是算术边界模拟，不能称为实际向厂商提交超窗后的报错复现。

证据：`_wsc_out/wsc-default-output-ab-195/audit.py`、`report.json`。

## 默认并入

已有旁路A/B证明正常路径等价、缺省总量检查补齐，`python/model/deepseek_output_defaults.py`默认开启，显式`XEYO_DEEPSEEK_DEFAULT_OUTPUT_RESERVE=0`保留对照行为。范围只覆盖已核实的官方HTTPS原点/标准路径/精确deepseek-flash ID，未知别名、自定义代理和其他模型不推断。发送的max_tokens和其它body字段都不更改。

记录依据仍区分provider_request_output_limit与provider_documented_default_output_limit；后者来自已核实的服务文档，不是用户配置或生成usage。最大输出393216没有拿来替代默认值。参考输入仍标为估算，总量错误也明确estimated_input。

新增默认开启／显式关闭检查，native_output_default_reserve、handoff_capacity_loop、main_timing三模块49项通过（6.38秒），覆盖默认三种模式、显式优先、未知边界和既有压缩/恢复主链。记录`pytest.txt`。

本轮无生成API、新费用或部署；原线上头和冷文件未动。预算估算累计3.87601816元、剩余1.12398184元不变。其他厂商预计数/默认值、媒体/大窗口和长任务完整范围仍保持验收边界；Goal继续active，成本净收益仍最后。
