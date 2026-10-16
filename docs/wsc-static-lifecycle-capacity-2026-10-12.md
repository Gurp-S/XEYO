# 批次87：原引用范围与输出空间静态修正

验收方式沿用用户10-12指示：只做静态代码问题审查；未运行代码测试、编译、模型评测或API。以下“修正”表示代码已改并核对调用关系，不表示运行效果通过。

## 生命周期边界

结构缺口：批次86适用范围扩大只按quote相等关联旧事实，原文引用缩短或扩大后仍是真实来源，但可避开旧阶段事实匹配。

修复复用 synaptic/task_fact_sources.resolve 和 source_text，将有来源对象的引用解析到原始消息及全部精确匹配区间。相同原消息且引用范围重叠的事实，适用范围扩大/阶段重绑定仍需要后续事件。不添加关键词、自然语言过期分类或历史原文回热。不同原始来源的相同文字不单凭文字相同判成同一事实；旧无范围声明保留原值匹配边界。

静态路径：handoff_generation → handoff_validation → handoff_phase → handoff_applicability；事务commit再次经过相同校验。expanded_facts唯一调用已更新sources参数，现有中性拒绝反馈保持。该逻辑只读来源，不改既有回执/状态结构。

边界：多次出现同段文字时现有schema没有指定唯一出现位置，所以重叠判据保守；旧无来源字符串、首次无阶段声明和完全不同表述不由此证明生命周期已解决。事件是否在语义上授权变化仍由模型声明，引擎只证明结构/新来源。这些不是可以用静态阅读勾选的任务漂移验收。

## 容量边界

结构缺口：主请求最终准入只检查 input>=capacity，已配置max_tokens没有参与总容量校核；专用handoff已有输入加2048检查，两条路径不一致。

修复在三种现有provider客户端增加只读context_output_limit接口，返回其_build_body实际使用的同一个_max_tokens字段，经共享output_limit_from_body验证正整数（不接受bool）。不重复编码输入/媒体，不把生成选项计入输入token。

最终prepare保持80/85输入占用判定，折叠和通知处理后再读输出上限。已知输入估参+已配置输出上限超过已声明容量时中性停止；未配置输出上限为unknown，不猜默认值。仅因输出上限而超容量、输入尚不足85%时不会新增自动折叠。调用方已有ValueError处理及两声道回退继续复用，无新调度状态机。

新增output_reserve_tokens/output_reserve_basis只写WorkingSnapshot准入事实，不进入冻结头或模型提示。实际发送仍由原encoder生成max_tokens；此处不降低用户配置或伪报已发送。

静态覆盖：DeepSeek、Anthropic、OpenAI兼容的接口字段与_build_body赋值一致；最终准入仍属于memory/wsc_request_timing.prepare，主query_loop首次及协议回退均使用它。

边界：输入仍是估参而非厂商精确token；缺失配置的默认输出余量、媒体/回传思考计量、模型容量语义及实际厂商准入未证明。T14d不勾。

## 文件与状态

修改：memory/wsc_handoff_applicability.py、memory/wsc_request_timing.py、model/context_input.py、model/deepseek.py、model/anthropic.py、model/openai_compat.py，加本证据和总账。共享工作树其他改动不归本批。

- [x] 静态代码修正：引用范围参与旧事实关联；接口和唯一调用一致。
- [x] 静态代码修正：已配置输出空间进入最终硬准入，输入80/85触发不变。
- [ ] 运行效果：用户已停止代码测试，本批未验证；不能继承旧测试数字覆盖本批。
- [ ] 四块最终验收：T16/T18/T14d/T13/H22/T11仍按正确性边界文件执行，不缩减goal。

测试运行0、API0、费用0；未部署重启，未改真实会话或既有冻结前缀。候选迟到投影仍默认关闭。
