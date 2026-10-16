# 批次136：模型选取的执行观察与逐字来源合同

## 实施及边界

新增leaf模块synaptic/task_observations.py。checkpoint可选observations数组，每项call_id、phase_id、quote；最多16项、总编码8192字节，仍受整个声明16000字节上限。调用须属于声明verification_call_ids，阶段须已存在。引用来自唯一绑定的真实结果正文，保存原文SHA256及来源，不将工具正文作为用户约束/决定来源。

交接提交验证每项原文确实出现于唯一完整结果，拒绝错文、重复身份、调用前结果、不完整/取消结果；失败但完整的结果仍是可核验观察，保留is_error。当前阶段的观察进入新投影，历史阶段只保留来源；同阶段未结束任务的更新不能静默遗漏已有观察。换阶段仍须经过原有phase provenance/transition验证，未放宽。

候选`XEYO_WSC_EXECUTION_OBSERVATIONS`默认关闭；开启时TodoWrite schema提供observations及phase_state，新投影追加原文片段与精确Read来源。旧格式无新字段时不增加来源扫描，不改旧冻结头/冷对象。兼容解码允许已有候选声明恢复；此候选未并入默认。普通压缩、水位和存档机制不改。

工具字段描述原文：`Exact result quotes selected by the model, bound to declared verification calls and phases. Total encoded observation size is at most 8192 bytes.` 仅陈述字段/限制，不给模型执行路线建议。

## 本地与API证据

新test_task_observations及task_continuity、terminal_verification、handoff_validation共56项通过，包含结构预算、阶段切换、遗漏拒绝、错文/重复/次序/不完整/取消来源拒绝、候选schema与大结果不全文回热。

用户本轮新增1元API授权后仅调用一次官方Flash，输入仅真实A/B回执286及调用/阶段身份，用户评测请求要求记录后续核对Read描述和cleanup需要的观察。模型自行给出原文片段，未由脚本预填答案；2/2逐字覆盖，结构及真实来源验证通过，共624编码字节，费用现有口径估算0.003656元。完整捕获见`_wsc_out/observation-selection-2026-10-12-136/{input,capture,report}.json`。初始辅助脚本名select.py遮蔽标准库，尚未调用API即失败；改名run_quote_probe.py后仅实际调用一次，无模型重试。

此调用是片段选择，未让模型重新生成全部任务交接，也不是压后续接查询。下一步必须验收压后模型是否采用观察并保持目标/步骤/证据，以及输入与信息净收益，不能据2/2本地可见直接推广。

## 真实提交、折叠与恢复

随后用真实293行源与既有已提交目标/待办声明，附加模型选出的observations，经实际TodoWrite事务提交；其余声明直接复制，不冒充模型重新规划。隔离副本first_cursor287，提交后追加旧头保持，下一fold游标288，新头15509字包含已核验观察，flush/hydrate后请求完全一致，原来源hash保持03073e90…578c0。证据`committed/{transcript,input,report}.json[l]`。全程不执行原任务、不改原会话，不将新头按阶段facts混为当前已发头。

API新增预算记录`_wsc_out/api-budget-one-yuan-2026-10-12.json`，本轮估算余量0.996344元；这是本地现有费率口径，不是官方实时余额。后续不得绕过该新增总预算，若官方再报余额不足立即通知用户。

## 未完成

候选尚缺压后模型续接、真实信息/输入净收益及更多阶段实轨迹，仍默认关；未知/不支持的媒体结果不提供文字观察，原来源仍可精确召回。Goal保持active，不声称全部治本、安装发布或现场冷召回已闭环。
