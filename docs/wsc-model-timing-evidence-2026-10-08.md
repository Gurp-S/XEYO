# 批次31：模型请求压缩与80%事实通知

## 结构规则

模型选择普通压缩；引擎只执行请求与容量保护。模型文字、未返回调用、失败调用均不是压缩授权回执。请求接受与实际折叠分开记录。被压缩的历史仍按总账的绑定任务状态/可核验执行事实交接，不能从历史旧请求派生目标。

通知也有两阶段：构造不等于已投递。成功模型请求才消费通知身份；请求失败或声道回退删除该通知后，不假记已送达。身份按折叠cursor和声明容量区分，落工作快照，回滚清掉旧时间线状态。

## 修改

- 新 `python/tools/compact_tool.py`：无参数、返回 `compaction_request=accepted; execution=pending`，默认关闭拒绝，取消/非法参数不接受。
- `python/tools/meta.py` 静态登记权限与并发事实，enabled=False不进默认工厂矩阵；`query_loop`仅新时机旁路开启时注册会话工具。默认工具集合不变。
- `engine/execution_facts.py` 把实际成功结果的结构化请求写入持久工具回执，独立于旧执行事实旁路。
- `memory/wsc_timing.py` 从配对成功回执读取最新请求；最新请求已处理后不复活更早请求。`runtime`安全请求边界消费，区分compacted/no_eligible_history，不把接受当完成。
- `memory/working.py` 保存已处理请求及已投递通知身份；hydrate/rollback覆盖。
- `wsc_execution_boundary.py` 新时机旁路也启用尚未消费响应窗口保护，独立于任务续接旁路。
- 80%通知在system/T_now/工具schema装配后计算，正文“上下文已达80%（当前完整请求估算）”；经已有引擎事实载体投递，含估参口径，无建议或导演文本。完成注入后才生成本次manifest。回退丢掉通知则不消费其投递身份。

## 验证

新增3项回归（多断言）：实际工具成功/失败/取消/关闭/伪文字和不完整配对；通知schema占用/去重/未发送/重启/回滚；真实query_loop中约20K未提前折叠，模型工具请求后下一次模型请求发生真实fallback折叠，原工具结果仍可见，状态flush/hydrate一致。query_loop用确定性模型替身，不是实际模型的自主时机选择或漂移验收。

定向：`tests/wsc/test_model_timing_requests.py tests/wsc/test_timing.py tests/test_query_loop_plain.py tests/test_runtime_c2.py tests/test_env_switches.py tests/test_execution_fact_contracts.py tests/test_todo_restore.py`，73 passed（3.64s）。

扩展：`tests/wsc tests/test_runtime_c2.py tests/test_notice_channel.py tests/test_c2_escape_hatch.py tests/test_c2_llm_summary_t8.py tests/test_env_switches.py`，1017 passed（36.22s）。集合有重叠，不能把73和1017相加。随后修正两处声道回退消费身份，需新增开启旁路的回退覆盖；当前默认关闭声道回归不能证明新分支。

## 尚未结案

1. 最终请求notification已有schema/T_now估参，但85%强压仍在早期keep评估入口，未以最终完整请求统一执行；厂商编码/回传reasoning/多模态实际占用亦需纳入并辨别估参。T14不勾选。
2. 本次只通知构造及去重/成功路径引擎机制有证据；声道错误回退/模型错误重试需开启旁路实测。
3. 当前C0大结果截短及相关尺寸输出去噪仍待审计，不能宣称任务信息损失解决。
4. 尚无真实源新增时机策略A/B、实际模型自决与有用信息/费用结算，不冒充现场闭环。默认旁路关闭，旧会话与冻结头未改。
