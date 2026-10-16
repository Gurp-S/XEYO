# 原始anchor重新呈现：三轮实现复审

本项对应U4和S5：重要状态更新不能只有上一代摘要；继续沿用完整Goal和“正确有收益即接生产”的最新授权。当前生产已能验证、归档quote ancestry，但生成工作集只展开bound_context_message_ids的source_text。这个ID若指向TodoWrite回执，source_text=None导致延期；模型可能只见committed_task_fields，不曾重新见原始文本。

## 第一轮：结构根因和职责

不新增一份状态、不做语义检索，不复制完整历史。复用synaptic.task_fact_sources.resolve，从最新已提交清单中仍适用的decision/constraint出发，沿精确同字段/全值引用回溯。只有链末确为唯一身份的普通用户/助手文本，才能形成original anchor。终态任务不主动重新加热；历史阶段事实不参与当前anchor。

直接已经呈现的同一原文不复制；只需要重新呈现当前绑定遗漏的祖先原文。继承链的中间回执只是出处链，不能冒充原始消息。legacy字符串在回执终止、坏引用、重名身份及机器note均不能猜测为原文。它们保留为未解析状态；不把source存在视为entailment。

## 第二轮：失败、容量、恢复

新代码独立模块，在generate实际request中物化，位于统一规范化计量之前；原数组/冻结前缀不动。完整记录16KB上限，容量不足整条defer；只剩元数据也放不下则省略可选面，既有目录/读取仍可恢复。只有实际发出的请求记presentation，延期/取消不能声称看过。

不会把工具数据当用户授权，不新增OBSERVED真值、不替换原Guard；不声称已完成epistemic/transition/registry。遗留事实没有原anchor时不能宣称U4全部通过。之后要在显式重要transition的机械协议中检查实际呈现，这一单位先修真实出处可见性缺口。

呈现账本复审：模型可能仍引用父声明，而原始anchor已真实重呈现。账本应同时保留本次anchor的完整/延期身份，不能只保留candidate.context_message_ids；否则存储出处又会被当前投影引用混淆。只增加有界anchor集合，不把全历史曝光记录无界塞进回执；metadata不代表semantic entailment。

## 第三轮：替代方案和验收

否决按关键词找旧消息、只重复前代摘要、直接打开全来源展开、削弱旧来源校验。已有精确resolver不另写平行解析器；新增入口只负责选择/完整呈现与容量，继承链合法性仍归resolver。

先用真实TodoWrite回执构造多代链，对照原workset确实缺原文、新生成请求确实包含原文；坏链、错误字段、终态、阶段过期、重复身份、超容量、取消、实际计数/coverage分别验证。再从原真实来源的已付费声明恢复引用链，确认原文逐字一致。行为/API只能用原始来源和相同任务，原gold不进输入；报告需要发生的API调用、请求及usage，不能用offline合同代替continuation quality。

先离线核验与最小接入，正确即成为生产逻辑；后续小额行为对照不允许重写旧成绩。Goal仍active。

## 准备层自查纠正（285/287之后、289之前）

发现chained使用通用task()夹具，默认content是旧WSC第二批任务、output=report.json，而objective和当前用户需求是支付验收/result.json。机械validate可以接受不一致自然语言，正说明SEMANTIC_UNVERIFIED边界必须保留。285/287原数据不改，降为“混合任务状态压力”，不冒充干净留出任务或方法胜负。

准备修改三轮核对：①语义所有权：fixture明确声明支付验收步骤，去掉与当前任务无关的旧待办；不改引擎来迁就fixture。②失败模型：规范源、quote ancestry、输出字段、oracle与API限额均保持，旧来源文件及response快照不覆盖。③公平性：独立289重做两臂、同状态/同请求/同工具/同额度，预登记检查todos/goal/输出文件一致；旧失败不能合并成新通过数。只修准备层，不降低Guard。
