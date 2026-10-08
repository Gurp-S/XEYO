# 批次37：旧C2验收迁移至模型请求/容量/代际规则

唯一任务总账：`docs/wsc-two-conversations-todo-2026-10-08.md`。

## 根因与边界

批次36扩大检查的14条既有失败，并不全部代表新的代码缺陷：测试仍要求decide/HardTop、C1、剩余轮数与费用解耦自动推进压缩，或要求新代永远以旧交接为前缀；这些要求与用户最终明确的模型自主压缩和新代最新状态规则冲突。另两条KEEP投影断言把完整回执的身份事实头当成正文丢失。

修正的是验收契约，不是生产阈值；没有恢复旧自动压缩、关闭主时机、删测试、使用skip/xfail、为单测增加运行旁路或把旧头改写为模型指令。

## 逐项映射（14条失败全部保留对应验收）

| 旧失败用例 | 新验收 |
| --- | --- |
| l5_project_never_advances | KEEP游标不动、原文不改、回执正文逐字保持，身份头单独允许 |
| cooldown_blocks_non_hardtop_c2 | 没有模型请求时旧C2调度不可执行（调用立即使测试失败） |
| hardtop_advances_cursor_store_len_unchanged | 已声明实际容量触发强压、原始消息不改、未消费尾部回执保留 |
| c1_freezes_middle_and_records_boundary | 旧C1调度不可执行，未折叠回执不能截短/冻结，重复KEEP稳定 |
| c1_cooldown_blocks_and_records_keep_x | 冷却年龄0/2/100均不能改变KEEP投影或推进游标 |
| keep_records_last_x_sim_for_next_hit | 不运行旧费用预测器，不改已存观察 |
| every_fold_attempt_is_ledgered_with_the_arm_that_ran | 实际KEEP评估两臂记账，真实timing_action/input_tokens，费用参数不能调度 |
| c2_compact_state_never_rewrites_summary | 先真fold，追加消息但无新请求时代内头字节不变 |
| c2_compact_state_extension_appends | 第二次显式fold生成新代，旧冷文件字节不变、原消息不改 |
| c2_decoupled_extension_fires_when_decide_keeps | 旧解耦开启和低费用门也不能自动推进游标 |
| c2_projection_prefix_stable_across_rounds | 真fold后KEEP头稳定，不靠未发生压缩来假验证 |
| hardtop_forces_extension_despite_gates | 声明容量强压能绕过旧费用/冷却，产生新代、不累积旧头 |
| remaining_capped_by_r_cap | 剩余轮数0/1/4/99不参与压缩调度，投影一致 |
| c2_compressed_right_side_freezes_after_c1 | 已冻结代保持，未冻结工具回执正文完整；不能因旧C1再截短 |

另修正三条原本通过却未实际触发压缩的测试：工具配对、原消息ID不变改为真实force；无可折叠区改为真实force且游标/头/原消息保持。底层pair-safe、持久化、记忆索引与独立费用辅助函数的有效验收继续保留。整个文件仍33条测试。

## 结果

修改文件仅`python/tests/test_runtime_c2.py`：33 passed（最后单文件2.25s）。与多代生命周期、任务连续性、真实工具请求回执、完整请求强压、配对/冻结/重启相关集合146 passed（8.51s）；此集合包含33条，不能累加。联合运行后无可折叠区用例从伪造旧decide改为实际force，随后单文件33再验证。

测试私有HOME/CWD、回退档隔离明确；原生档及收益门回退档分别由批次36四组合覆盖，不声称本文件回退档覆盖所有原生行为。不修改现场会话、旧冻结文件或运行服务，不发API。

T15验收迁移完成；T14d精确厂商计量、T10/T13长期模型行为、T11线上迁移、H19/20/21/23/31/37等其他未勾项继续开放。目标没有结案。
