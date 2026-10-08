# WSC 主流程压缩时机交付（批次34，2026-10-08）

范围是用户最后明确要求的四项；直接进入主流程，无新旁路开关。此前批次的“默认关”是历史结算，不代表本批运行行为。

## 结构性规则

根因：费用、轮数、绝对水位和容量保护分别推进历史边界，模型执行任务时可能在低占用下失去上下文；任务状态又不能仅靠历史请求恢复。

统一规则：普通折叠只消费成功配对的 Compact 调用回执；强压在最终完整请求发送前按当前模型登记/元数据容量的85%判定。80%事实通知按折叠代和容量去重，只有成功送达才记已通知。确定性投影、旧头及冷对象的字节保护不变。

回归：默认工具目录、旧开关设0仍生效、1M下20K不折、80/85精确比例边界、schema/通知导致跨线、工具结果越线后的下一次准备、400/500重试、模型请求、native与旧回退的任务交接、未消费结果、冻结头、重启和实际Read。

## 已并入

- [x] Compact 恒注册，普通费用/轮数/老化/旧水位自动分支不再进入模型发送主链。旧 MODEL_TIMING/TASK_CONTINUITY 两个开关已从环境登记表退休，设0也不能关闭；冻结头/成本吸收旧开关同步从记忆登记表退休，避免账面与实际行为不一致。
- [x] 80%事实通知追加到当前请求，不回写冻结头；失败请求不消费通知，重启可恢复去重。
- [x] 最终完整请求包括 system、T_now、工具schema、当前消息和通知本身。OpenAI兼容入口按实际编码归一化后的输入结构计量；容量来自登记或元数据，去除型号名猜128K。输出预算和累计用量不充当输入占用。
- [x] TodoWrite检查点进入主流程，保留声明目标、稳定步骤身份/状态、决定、约束、绑定的验收回执和明确来源。短验收正文有界内联，长正文保留精确Read引用；未消费工具批次留在尾部。native和旧确定性回退均覆盖，旧回退新头不再加载session.md中的历史Goal。
- [x] 未冻结工具回执不再被历史C0/offload/尺寸投影二次缩短，已有冻结表示不重置。执行层预算/spill仍保留。

## 模型实际可见工具描述

工具名 `Compact`，参数 `{}`，无字段。原schema和最终schema预算后的描述共用同一个常量：

> Requests deterministic compaction before next call; keeps goal, steps, decisions, evidence and unread results with exact Read archive references. Acceptance is pending execution. No arguments.

工具回执 `compaction_request=accepted; execution=pending` 只证明请求接受；真正折叠结果由下一次请求边界记录，不伪称工具调用时已完成。任务结构继续使用TodoWrite.checkpoint；Compact没有混入Memory的持久知识操作。

## 验证数字

最终一次合并集合：**176 passed，8.16s**。集合包括17个相关测试文件；前面69、166、167及分组数字有重叠，不累加。不声称全仓测试通过。

真实保存源2339行，SHA256 `5c4baa86ab9056db08868d5f183ffe61a6c4c93d58a10269085b071053810734`。使用私有目录、登记1M容量、完整默认工具schema及OpenAI输入编码重建；没有访问模型API，没有改线上会话。

| 指标 | 完整请求强压前 | 强压后 / 重启下一枪 |
| --- | ---: | ---: |
| 完整输入估算 | 1,499,722 | 17,633 |
| 折叠游标 | 0 | 2332 |
| 自动折叠尝试 | 1（85%容量） | 0 |
| 实际Read | — | 5/5 |

头241行；旧冷对象字节、冷视图完整内容、原始捕获源字节、重启头一致均通过，9/9接受项。源末端无未消费批次，这个源不能证明未消费保护；另有native/回退均包含真实未消费结果的非空回归，不能把0条结果当保护闭环。

编码时捕获源已有9条未配对历史工具结果，归一化会剔除其wire行；原记录和冷原文未删除。这不是历史线上wire重现。原始现场请求/模型行为不能由此反推。

证据：`_wsc_out/main-timing-2026-10-08/report.json`、`rebuilt-head.txt`、`rebuilt-request.json`。复现入口 `python/evals/wsc_main_timing_replay.py`。

## 边界与剩余验证

容量分母是真实登记/元数据值，输入分子仍明确是UTF8字节/4估算，不等于厂商精确tokenizer，媒体占用也不能由文本字节等价证明。未知容量不猜1M、不伪造百分比。固定schema或不可折叠的当前结果自身过大时，只尝试一次并记录no_eligible_history，不无限折叠或伪报成功。

检查点保存模型实际提交的状态，不凭关键词补造未声明目标、决定或验收。原有会话缺检查点时可召回原文，不能声称引擎已经理解并补齐全部任务过程。真实模型长期漂移、实际召回效用、线上迁移和更广去噪审计仍在总TODO中，整体目标不结案。

代码已并入当前工作区；本批未停止/重启用户正在运行的XEYO服务。已有进程需加载新代码后才使用此主流程。

## 本批改动文件

入口及规则：`python/engine/query_engine.py`、`python/engine/env_switches.py`、`python/memory/runtime.py`、`python/memory/wsc_timing.py`、`python/memory/wsc_projection.py`、`python/memory/memory_switches.py`。

任务连续性：`python/synaptic/task_checkpoint.py`、`python/synaptic/project.py`、新增 `python/memory/wsc_fallback_handoff.py`。

工具：`python/tools/catalog.py`、`python/tools/meta.py`、`python/tools/compact_tool.py`、新增 `python/tools/compact_description.py`。

证据与回归：新增 `python/evals/wsc_main_timing_replay.py`、`python/tests/wsc/test_main_timing.py`；更新 `tests/test_catalog.py`、`tests/test_context_limit_declared.py`、`tests/test_memory_switch_authority.py` 和WSC测试 `test_full_request_timing.py`、`test_model_timing_requests.py`、`test_unfolded_results.py`、`test_task_continuity.py`、`test_restart_continuation.py`、`test_live_head_freeze.py`、`test_chunked_recovery.py`、`test_state_contracts.py`、`test_continuation_repairs.py`（路径均在python/）。旧开关、旧活跃历史提升、可修改冷文件等断言改成主流程契约；保留来源完整性和身份分组检查，没有跳过失败用例。

文档：本文件、`docs/wsc-two-conversations-todo-2026-10-08.md`、追加 `docs/wsc-loop-notes-2026-10-07.md`。
