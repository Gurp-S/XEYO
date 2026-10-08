# WSC 根因契约修复与离线闭环（批次 20，2026-10-08）

> **批次 21 补正**：本批“剩余全部完成”不能覆盖未绑定会话中最早请求自动当目标的缺口；后续已以请求投影旁路修复，详见 `docs/wsc-request-projection-evidence-2026-10-08.md`。下文保留批次 20 的实际版本与数字，不把后续结果回填为本批结果。

本批完成剩余清单的旁路实现，并贯通五项根因机制。两个新开关均默认关闭：`XEYO_WSC_STATE_CONTRACTS`、`XEYO_EXECUTION_FACT_CONTRACTS`。没有设置生产环境开关，没有修改原会话、原冻结头或原冷区文件。既有 G1 开关保留；本批新契约独立运行，A/B 中将 G1 关掉以区分收益来源。

## 事故修复前三问

1. **结构性根因**：目标、约束和历史消息绑定为一个不可退休的载体；错误显示与错误解决判据各自记账；冷区路径没有约束对应内容；冻结头与冷区发布缺乏完整代次校验；环境宣告与实际权限各自维护，开始记录被误当作完成证据。
2. **结构性规则**：目标生命周期取现有 GoalStore 的 goal_id/revision/status；约束独立保存。错误只凭同调用范围的完整成功回执解决，所有显示面读取同一状态。冷对象按完整字节 SHA-256 命名、原子发布且禁止覆盖；头清单封印来源、正文、生命周期和引用对象。新头持久化成功后才替换内存头；正常发射直接复用冻结字节。环境事实来自执行权限判据；工具开始与工具返回分开留痕，未知不伪装成未执行。
3. **回归**：真实生产适配器覆盖尾部关闭声明、折叠、后续发射、重启、投影故障、持久化故障；真实 Read 覆盖篡改检测；混合目标/硬约束、五种 GoalStore 状态、空输出成功、后台未完成、重复错误、文件错误注释、Edit CAS 竞争、scratch 双通道和复合删除分别验证。

## 五项机制及清单对账

| 根因机制 | 对应问题 | 本批行为 |
| --- | --- | --- |
| 目标、约束分离 | G1 | 已绑定目标读取现有 GoalStore；显式关闭仅退休目标事实，原文与硬约束仍在。未绑定旧会话仍用保守派生规则，不把最新一句自动当目标。 |
| 冷区不可变 | #9/G3/C-1 | 完整内容寻址，先写齐后原子链接，重建不会覆盖旧对象；实际 Read 在缓存短路前校验摘要。GC 只接受显式完整引用根，默认 dry-run；没有自动 TTL 删除仍可回读的对象。 |
| 错误单一生命周期 | #16/G4 | 完整成功状态可解决空输出调用；未完成后台调用不算成功。错误从 DECISIONS/PRUNED 重复展示面移除，保留一个未解决事实通道与完整冷区原文；文件错误注释也使用同一状态。 |
| 代次发布、冻结发射 | #3、前缀稳定 | 头清单封印全部引用对象及生命周期；持久化失败不替换内存头；已有合格头在投影失败时继续复用。异常只留本地阶段/异常类，不把错误指导塞进注意力。 |
| 执行事实与权限同源 | #2/#7、G2、C-2–C-7 | scratch 精确子树许可、活权限事实、shell 语法事实、逐调用返回回执、Edit 验证内容 CAS 基线、差异位置、全部字面写目标证明、拒绝规则/证据类别、job 最后输出时间及输出量。 |

附带完成 #13：联合门与 changedetect 的 JSON 输出，任何非零或未完成阶段都不能冒充成功。#19：PATHS 仅去掉已由 PIN/工作集明确表达的完全相同路径，不按长度或通用词猜测噪声。A-⑧：补齐 XEYO.md 的测试、构建与架构入口空标题。#20 原前提不成立，冷层回读已存在，无需再造入口。

C-3 从真实原文 #1812 找到误判：拒绝规则把 Python 属性 `p.key` 当成凭据文件。新增有界 Python AST 识别，在单引号字面 here-string 中仅排除经语法证实的 `.key` 属性；真实 `open('secret.key')`、shell 文件 `p.key`、语法无法证明的载荷仍拒绝。原始命令的 secret 判据由拒绝 → 不命中，凭据反例仍拒绝；这只是权限判据重放，没有执行原始诊断脚本。回执 `_wsc_out/root-contracts-2026-10-08/secret-replay.json`。拒绝结果同时显示规则、类别和规范化区间，不输出命令或密钥。C-4 仅支持解析器可证明的字面命令；变量、通配符、解释器变换保持拒绝，避免最后一个 token 冒充写目标。

## 改动文件

新机制模块：

```
python/synaptic/contracts.py
python/synaptic/lifecycle.py
python/memory/wsc_diagnostics.py
python/memory/wsc_goal_source.py
python/memory/wsc_publication.py
python/memory/wsc_object_gc.py
python/engine/execution_facts.py
python/session/execution_receipt.py
python/permissions/bash_targets.py
python/permissions/bash_secret_evidence.py
python/tools/fileio/edit_contract.py
```

既有接线文件（均有此前在途改动，本批只负责上述接线）：

```
python/synaptic/project.py             python/synaptic/assemble.py
python/synaptic/types.py               python/synaptic/graph.py
python/synaptic/freshness.py           python/synaptic/metrics.py
python/memory/wsc_projection.py        python/memory/wsc_head_store.py
python/memory/wsc_continuation.py      python/engine/env_facts.py
python/engine/env_switches.py          python/engine/query_loop.py
python/permissions/filesystem.py       python/permissions/policy.py
python/permissions/bash_policy.py
python/session/call_trace.py           python/session/hydrate.py
python/msgtypes/message.py             python/tools/base_tool.py
python/tools/tool_registry.py          python/tools/bash_tool/bash_tool.py
python/tools/file_read_tool/file_read_tool.py
python/tools/file_edit_tool/file_edit_tool.py
python/tools/job_tools.py              python/server/job_registry.py
python/evals/changedetect/__main__.py   scripts/check.ps1
```

验证与文档：`python/tests/wsc/test_state_contracts.py`、`python/tests/test_execution_fact_contracts.py`、`python/evals/wsc_root_contracts.py`、`scripts/check_gate.py`、`XEYO.md`、本文、未修清单、交接提示词、账本批次 20、G1 方案 §11。没有提交或合并其他在途工作。

## 测试数字与可复验入口

- 本批新契约：**30 passed**；含既有 head-store 回归的复验：**34 passed**。
- 初轮全仓离线门：Python **5776 passed / 2 skipped / 1 deselected / 29 xfailed**；GUI **1789 passed / 5 skipped**；GUI/TUI 类型检查、slash manifest、changedetect 均通过。
- 全仓联合门 **6/6 阶段 passed**：Python **5789 passed / 2 skipped / 1 deselected / 29 xfailed**（1 条依赖弃用提示），GUI **1789 passed / 5 skipped**；GUI/TUI 类型、slash manifest 与 changedetect **5/5** 通过。报告 `_wsc_out/root-contracts-2026-10-08/gate-final/report.json`。该全仓检查启动于最后权限 AST/恢复回执元数据修补之前；最后修补另跑下述相关全集，不冒称同一次全仓覆盖最后所有字节。没有跑真实模型请求或 GUI/TUI live E2E。
- 最后权限与新契约子集：**99 passed / 1 skipped**；最后全部相关接线（WSC、权限、执行回执、工具、环境登记）**929 passed / 1 skipped**，32.85s；此前完整 WSC 与工具环境组合 **863 passed**。重复套件存在重叠，不累加成通过总数。

```powershell
py -3.11 scripts/check_gate.py --skip-install --output _wsc_out/root-contracts-2026-10-08/gate-final
py -3.11 -m pytest python/tests/wsc/test_state_contracts.py python/tests/test_execution_fact_contracts.py python/tests/wsc/test_head_store.py -q
py -3.11 python/evals/wsc_root_contracts.py C:/Users/48522/.xeyo/sessions/sess_mux0q86a_ea2kv9.jsonl --output _wsc_out/root-contracts-2026-10-08/replay-final
```

最后接线复验：

```powershell
py -3.11 -m pytest python/tests/wsc python/tests/test_execution_fact_contracts.py python/tests/test_env_facts.py python/tests/test_file_tools_contract.py python/tests/test_jobs_control_edges.py python/tests/test_env_switches.py python/tests/test_changedetect_env_baseline.py python/tests/test_bash_policy.py python/tests/test_permission_policy.py python/tests/test_permissions.py python/tests/test_write_policy.py -q
```

## 真实会话前后对照

原始会话 **1879 条**。SHA-256：`a63576fe9c8171d350f6efd10598b12045e26c4175ace6dfb2c03615fd2bb910`。在同一生产参数、相同原文、相同切点下独立重建；全部产物落在隔离目录。主报告 `_wsc_out/root-contracts-2026-10-08/replay-final/report.json`，完整差异为同目录 `head.diff`。

| 原文切点 | 关闭旁路头 tokens | 开启旁路头 tokens | 未解决错误（两组相同） |
| --- | ---: | ---: | ---: |
| 200 | 3455 | 3615 | 3 |
| 400 | 4242 | 3924 | 8 |
| 800 | 5559 | 4616 | 14 |
| 1200 | 6369 | 4847 | 19 |
| 1600 | 8761 | 6222 | 34 |
| 1809 | 11121 | 7618 | 50 |
| 1844 | 11840 | 7947 | 53 |
| 1845 | 12274 | 8401 | 53 |
| 1866 | 12295 | 8407 | 53 |
| 1879 | 12295 | 8414 | 53 |

末切点减少 **31.6%**；首切点增加 **160 tokens**，不声称所有长度均获益。与初跑不同的路径长度会影响 token 数，本表全部来自同一次 final 成对运行。

- 冷区文本与单节点/分组 expand **26,862 / 26,862** 一致；这些是两个实验臂、十个切点的累计引用次数，不是独立节点数。
- 实际 FileReadTool **120 / 120** 成功，每次核对目标位置的最多 10 行；不冒充所有全文均经工具读取。
- 原会话及原产物 **10 / 10** SHA-256 不变；除目标外的既有 PIN 事实丢失 **0**。
- 关闭声明之后旧 ChatGPT 目标 **3 / 3 → 0 / 3**；下一派生目标仍是 #66，不声称它等于用户最新任务。
- 验收 **6 / 6**。包括实际生产发射适配器对真实原文的冻结实验：#1844 声明仍在尾部时头相同；指定折叠吸收声明后换头一次；下一轮头相同；清空进程态后恢复的整个发射结果相同。选取折叠边界为实验控制，未测在线自动折叠时机。
- `freeze-replay/` 保存各阶段完整发射 JSON；原线上头未改写。回归另外模拟投影故障、持久化失败，验证继续发射旧头。
- 实际 scratch 执行 **4 / 4**：Write 创建、Bash 创建、无事先 Read 的 Edit、组合命令删除刚建文件；CAS 竞争另由回归验证。回执见 `_wsc_out/root-contracts-2026-10-08/execution现场/report.json`。

## 是否治本与剩余事实

**已从结构上约束住的根因**：新冷区路径绑定完整内容，旧对象无法被正常发布覆盖；目标关闭不再连带丢硬约束；完整成功证据与错误状态贯通；环境宣告与写权限同源；新头发布失败不能替换已持久化旧头；正常发射及重启复用已封印字节。这里的结论限定于已验证的旁路与离线场景。

**仍不能夸大的边界**：

1. 原文有 **53 条缺少可验证闭合证据的历史错误**，两组都保留。没有凭“后面测过别的测试”消掉这些账；结构上已支持今后的完整回执，历史缺失结果不能补造。
2. 未绑定 GoalStore 的历史会话没有可靠的“最新目标”结构，继续保守派生；绑定目标后才以现有目标 revision/status 为权威。不会凭最后一句猜测档 B。
3. 后台 `last_output_at/output_chars` 是活动观测，不证明程序正在取得进展；Docker 非流式 exec 的中途输出不可观测，显示 0 而非伪造心跳。
4. GC 尚未自动执行，完整引用根包含原会话/历史冻结产物，不能只用当前头清理。保留存储换取历史可回读。
5. 默认开关仍关，旧线上头未清账；启用后只有真实折叠才能迁移目标与指针。必要代次转换可能断一次前缀，日常发射不改既有行。未测厂商缓存命中率、在线 token 花费或模型是否少白跑。

## 参考实现的取舍

采用可验证原文恢复与确定性状态提取，参照 [pi-vcc](https://github.com/sting8k/pi-vcc)；它的 [索引范围问题 #28](https://github.com/sting8k/pi-vcc/issues/28)也说明索引窗口与会话身份需要同源。冷区完整内容身份参照 [Git 对象存储](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)。这些是架构参考，不作为本项目已治好的证据；结论来自上述回归与真实重建。
