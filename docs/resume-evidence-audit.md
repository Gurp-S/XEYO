# XEYO 简历证据审计（Phase 0 + XEYO 取证实验）

审计日期：2026-09-18  
审计基线：`HEAD=19f8205`  
审计范围：仅 XEYO；不纳入当前工作树的未提交改动，不修改现有源码或既有测试。  
新增文件约束：新增 benchmark、结果和测试文件只放在 `benchmarks/resume_evidence/`。

## 1. 结论摘要

- XEYO 的预算、循环检测、权限、MCP、会话隔离都有真实实现和较多契约测试；这些测试证明了局部行为，不等于简历中的大规模成功率或压力测试数字。
- 本轮已有测试实际运行：MCP/权限相关 `102 passed, 1 skipped`；并发/会话/usage/retrieval 相关 `44 passed`；长任务相关 `62 passed, 1 failed`。失败是现有 `test_max_turns` 对 warning 文本的断言，不隐藏、不修改。
- 新增长任务 benchmark：正常短任务和多工具任务均 `end_turn`；失控任务分别以 `max_turns`、`budget_usd` 停止；重复调用 53 次中 51 次被 L1 阻断，20 次不同参数正常调用无误杀。
- 新增 MCP adversarial matrix：`9/10`；参数变化后仍复用同一 MCP grant 是唯一失败项，说明当前 v2 指纹不做参数级重新授权判断。
- 新增 500 会话隔离 benchmark：`500/500` 会话、engine、budget、message container、tool instance 均独立，`0` owner/cwd mismatch；该结果基于干净 `HEAD` 快照运行，因为当前工作树的 `query_loop.py` 存在既有 `TabError`。
- `0.83s -> 0.02s` 在 `HEAD`、仓库内现有报告和 `TerminalBench` 顶层评测文件中均未找到可追溯来源。该数字当前不能进入简历。
- 当前代码的缓存命中率定义是 `cache_hit / (cache_hit + cache_miss)`，并且有 JSONL 用量账本和单测；但没有找到 `5.3 亿`、`99.41%` 的冻结筛选条件、原始结果和仓库内复现命令。
- 本机 XEYO 用量账本的只读聚合结果与简历数字不一致：截至 2026-09-18 记录了 14,055 条有效事件、`732,732,561` prompt tokens、命中率 `95.366531%`；按模型筛选仍没有得到简历中的 `99.41%`。这是带原始路径的审计结果，不替代简历原 claim。
- 现有记忆检索 benchmark 只有 5 条 notes case，结果为 `2/5 hit@k=0.4`；它不是 `95.3% memory hit` 的证据。代码与审计文档还显示自动记忆召回当前关闭，主要依靠显式 Memory 工具。
- MCP 代码和测试覆盖了默认 ASK、企业 deny、scope、grant/revoke、TTL、指纹防 spoof、网关身份和审计，但现有 MCP 默认策略是 `outbound_ask`，不是默认 DENY；尚无覆盖用户列举全部攻击面的统一 adversarial matrix。
- 并发证据包括同一引擎提交互斥、两会话 cwd 隔离、owner 隔离，以及 50 worker / 10 线程的文件协调测试；没有找到“500 个同时活跃会话、0 次跨会话状态冲突”的可复现脚本或原始结果。
- `TerminalBench/REPORT.md` 与完整 `run/` 结果在本机存在，但 `TerminalBench/` 被 `.gitignore` 排除；同时 `docs/BENCH-口径.md` 明确把 70.8% 定义为接力并集，不是单引擎全量成绩。简历当前写法需要重写，不能直接 KEEP。

## 2. 仓库中已找到的测试、benchmark、log、report

### 2.1 CI 与总体测试入口

- `.github/workflows/ci.yml`：Python `pytest -q --timeout=60 -m "not live"`、slash manifest check、GUI typecheck/vitest、TUI typecheck。
- `README.md` 和 `scripts/check.ps1`：提供接近 CI 的本地检查入口。
- `HEAD` 中统计到 364 个 `python/tests/*.py`、111 个 GUI 测试文件、91 个 `python/evals` 文件、15 个 `python/scripts` 文件。数量代表现有代码规模，不代表简历 claim 已验证。

### 2.2 长任务、预算和循环控制

实现与测试入口：

- `python/engine/budget.py`：记录 Turn、Tool Call、token、USD；包含 max-turn、tool-call cap、token/USD、wall-clock、共享 grace 和 hard-stop reason。
- `python/engine/loop_breaker.py`：L1 同签名、L2 周期、L3 同结果、L4 无新内容，带半开 probe 和 JSONL 取证。
- `python/engine/repeat_guard.py`：同参数调用计数和提醒；它本身是 advice，不是强制拒绝。
- `python/tests/test_loop_breaker.py`：覆盖 53 次同签名持续拒绝、周期重复、同结果、同工具无新内容、probe、自定义开关和 metadata。
- `python/tests/test_repeat_guard.py`：覆盖语义签名、分页豁免、同参数提醒、结果折叠和 query loop 集成。
- `python/tests/test_loop_ledger.py`：覆盖等价结果、跨工具已见内容、render gate 和 episode reset。
- `python/tests/test_budget.py`：包含 `test_submit_stops_on_budget_usd`、`test_phase2_tier_cuts_runaway_loop`、`test_phase2_normal_session_not_killed_by_tier`、显式预算优先级和 grace 相关测试。
- `python/tests/test_max_turns.py`：用持续输出 tool call 的 fake model 验证 max-turn 停止和 grace 期间正常收尾。
- `python/tests/test_abort.py`、`python/tests/test_query_loop_retry.py`：覆盖中止和重试相关路径。

证据判断：这些测试足以证明“有多层预算和循环保护实现”，但测试文件没有形成统一的 scenario matrix，也没有落盘每个异常 case 的 termination reason、consumed turns、tool calls、tokens、elapsed 和 false-positive 汇总。因此它们不能支持简历中的 runaway termination rate、bounded-exit rate 或 shutdown latency。

### 2.3 上下文、用量和记忆

- `python/usage/ledger.py:45-117`：把 provider/model/session/request usage 写入 JSONL，保存 `prompt_tokens`、`cache_hit`、`cache_miss`、`output` 等字段。
- `python/usage/ledger.py:189-217`：命中率定义为 `hit / (hit + miss)`，`input_total` 定义为 `hit + miss`。
- `python/tests/test_usage_ledger.py`、`python/tests/test_usage_attribution.py`、`python/tests/test_usage_combine.py`：验证字段拆分、聚合、窗口过滤、vendor 归属和无金额报表。
- `python/evals/retrieval_bench.py:50-70,221-225,240-315`：固定 5 条 notes case 和 5 条受控 code corpus case，测词法 `hit@k`，不测生成回答，也不测 RAG answerability。
- `python/tests/test_retrieval_bench.py`：明确允许 notes 低于 1.0，并将 notes 回归门设为 `>=0.2`。
- 本机忽略目录 `artifacts/benchmarks/retrieval/hitk.json` 当前记录 notes `2/5=0.4`、code `5/5=1.0`；该文件不在 Git 中。
- `benchmarks/resume_evidence/xeyo_usage_ledger_audit.py` 可从 `XEYO_USAGE_LOG` 或 `XEYO_USAGE_DIR/events.jsonl` 重算 usage 账本；原始快照写入 `results/xeyo_usage_ledger_audit.json`。
- `docs/面试知识书/01-代码地图与覆盖矩阵.md:663-685` 明确区分 retrieval 5-case 基线、BFCL/MBPP/HumanEval 缓存命中和生产样本，指出它们不能混算。
- `docs/全项目审计-20260910.md:83-84`、`docs/面试知识书/01-代码地图与覆盖矩阵.md:765` 记录自动记忆召回关闭的现状；不能把显式 Memory 工具能力表述成自动召回质量。

### 2.4 MCP、权限和安全正确性

实现与测试入口：

- `python/tests/extension/test_mcp_e2e.py`：主链 enable → ASK/DENY → grant → allow → audit；plugin scope；enterprise deny。
- `python/tests/extension/test_mcp_gateway.py`：list/describe/call/resources/read_resource、unknown tool fail-closed、bad action、gateway identity、enterprise deny、grant roundtrip。
- `python/tests/extension/test_mcp_scopes.py`：project/user/plugin 优先级、企业 deny、tool deny pattern、trust 和 declaration hash。
- `python/tests/extension/test_mcp_exposure.py`：hidden-but-registered、可见性、单工具/总 schema budget、hidden tool 仍走 ASK。
- `python/tests/test_mcp_fingerprint_v2.py`：参数 spoof 不改变授权身份、gateway/native identity 一致、deny beats grant、v1/v2 隔离、pending item 携带 mcp target。
- `python/tests/test_permission_grants.py`：grant match、revoke、TTL expiry、scope binding、ASK 后 grant、remote/worker/always 模式不继承 grant。
- `python/tests/test_permission_policy.py`、`python/tests/test_permissions.py`：工具策略、workspace/path boundary、`..` escape、symlink escape、secret path、destructive command 和 registry gate。
- `python/tests/test_permission_ask_resume.py`、`python/tests/test_permission_t3.py`：pending/resolve/timeout/cancel、审计配对和风险分级 TTL。
- `python/tests/extension/test_freeze_invariants.py`：tool schema session freeze、disabled server execution DENY、reconcile 幂等和 v2 fingerprint chain。
- `benchmarks/resume_evidence/xeyo_mcp_adversarial.py`：本轮新增 10 case matrix，原始结果为 `9/10`，包含失败 case，不将失败改写为通过。

现有测试是高价值 correctness evidence，但不是完整攻击面统计。另一个必须修正的语义是：`python/tests/test_mcp_client_t11.py` 明确验证 MCP 默认 policy 为 `outbound_ask`；因此“以默认拒绝作为 MCP 默认策略”不能按当前代码保留。`docs/全项目审计-20260910.md:24-26` 还指出 MCP 直挂与网关存在双轨，简历不应笼统宣称所有 MCP 调用已经收敛为单一执行路径。

### 2.5 并发与隔离

- `python/tests/test_concurrency_gates.py`：同一 `QueryEngine` 并发 submit 被拒、close 清理 busy flag；TurnRunner 双启动拒绝和终态可见。
- `python/tests/test_session_cwd_isolation.py`：两个 session 使用不同 cwd，ThreadPoolExecutor 2 个读任务不会跨 cwd；同 session 换 cwd 会冲突。
- `python/tests/test_agent_inbox.py`、`python/tests/test_agent_scope.py`：inbox/session/agent scope 隔离。
- `python/tests/test_job_registry_t42.py`：owner session 隔离、容量、终态和 first-settle-wins。
- `python/tests/coord/test_worker_pool.py:205-242`：`n=50` 个 worker，`ThreadPoolExecutor(max_workers=10)`，每个 worker 使用独立 store/pool，验证 50 个文件收敛、内容正确、无 `.git/index.lock`。

这组既有测试能支持“存在会话、owner、cwd、worker worktree 隔离机制”。本轮新增 `xeyo_session_isolation_500.py` 在干净 `HEAD` 快照上验证了 500 个同时到达 barrier 的 session：500/500 engine、budget、message、tool 实例独立，0 mismatch；它使用最小 fake model 和 probe tool，不等同于真实 LLM 压测。

### 2.6 已有外部评测与原始产物

- `python/evals/bfcl_lite.py`、`humaneval_lite.py`、`mbpp_lite.py`、`mmau_local.py` 与本机忽略目录 `artifacts/benchmarks/startup/` 存在完整 JSON/XML 结果；这些是函数调用、代码题和离线门测试，不是简历中 500 并发或 MCP adversarial 的证据。
- `TerminalBench/REPORT.md` 在本机存在，原始目录有 89 个 `result.json`，当前解析为 63 个 reward=1、25 个 reward=0、1 个缺失 reward；`TerminalBench/` 被 `.gitignore` 排除，未进入 `HEAD`。
- `docs/BENCH-口径.md:12-14,35-47` 将 70.8% 定义为 `terminus-2` 基线、XEYO 翻绿和基建补测的接力并集，并明确不是单引擎全量成绩。
- `TerminalBench/REPORT.md:3-6,21` 和 `TerminalBench/秋招项目说明.md:9-18` 则把 63/89 及长会话缓存指标写成单次全量 XEYO 结果。两者血缘冲突，必须先统一口径。

## 3. 简历 claim 逐条证据等级

证据等级：A = 可复现 benchmark 或 correctness test；B = 有测试/日志，但证据不完整；C = 代码实现存在但没有结果验证；D = claim 超过代码或现有证据。

### XEYO-1：长任务执行、状态机预算、异常循环熔断

- Claim：Turn / Tool Call / Token / USD budget 统一管理，并可对异常循环熔断。
  - 等级：A（机制与本轮 deterministic benchmark）；
  - 原因：`BudgetTracker`、`LoopBreaker`、`RepeatCallGuard`、query loop 接线和相关单测都存在；新增结果覆盖正常短任务、多工具任务、max-turn/USD runaway、L1/L2 loop 和正常不同参数调用。
  - 风险：`RepeatCallGuard` 是 advice；强制阻断来自 `LoopBreaker`、预算和 query loop hard stop，简历若把它们都叫“熔断”会混淆执行层语义。
- Claim：`0.83s -> 0.02s` 收尾控制权交还。
  - 等级：D。
  - 原因：在 `HEAD`、仓库报告和 `TerminalBench` 顶层文件中未找到该数字的原始测量、before/after 脚本、环境或计算方法。
- 建议：当前 bullet `[REWRITE]`。保留架构问题和机制，删除该数字；完成 P0 benchmark 后再加入 1–2 个最有解释力的指标。

### XEYO-2：上下文治理与记忆

- Claim：累计约 5.3 亿 prompt tokens。
  - 等级：D。
  - 原因：未找到该数字的冻结时间窗、model/provider/session 过滤、原始文件和仓库命令。当前本机账本快照聚合为 `732,732,561` prompt tokens，口径明显不同。
- Claim：缓存命中率 99.41%。
  - 等级：D。
  - 原因：代码定义是清楚的，但没有找到产生 `99.41%` 的可追溯聚合；本次审计快照为 `698,781,626 / (698,781,626 + 33,950,935) = 95.366531%`。
- Claim：记忆命中率 95.3%。
  - 等级：D。
  - 原因：没有命中定义、ground truth、样本集或原始结果；现有 retrieval benchmark 为 notes `2/5`，不能替代。
- 建议：当前 bullet `[REWRITE]`。保留“上下文投影/稳定前缀/分层记忆”的架构描述，删除三项未冻结数字；若要保留数字，先固定数据集、窗口、模型过滤和 ground truth。

### XEYO-3：工具系统与 MCP

- Claim：统一 Policy Gate、默认拒绝、scope/TTL/audit、权限与模型决策解耦。
  - 统一 Policy Gate：B。native tool、MCP gateway、permission store 和 registry gate 都有测试，但 `docs/全项目审计-20260910.md` 记录 MCP 直挂/网关双轨。
  - 默认拒绝：D。MCP 默认 policy 的现有测试期望是 `outbound_ask`；全局未知工具也有 ASK 路径，不能改写为默认 DENY。
  - scope/TTL/audit/revoke：A-（本轮矩阵 `9/10`，但参数变化 case 失败）。
  - 建议：当前 bullet `[REWRITE]`。改为“以 ASK/DENY/ALLOW Policy Gate 约束 native/MCP 工具，覆盖 workspace scope、授权 TTL、revoke 与 audit”；不要宣称参数级授权重判。

### XEYO-4：并发隔离与 500 并发 0 冲突

- Claim：多 Agent 并发时避免 Tool Call 状态和参数跨会话污染。
  - 等级：A（限定实验条件）。
  - 原因：已有 QueryEngine 互斥、cwd/session/owner/inbox/agent scope 和 worker worktree correctness tests；新增 500-session oracle 对每个 session 的 Tool probe 参数、runtime budget、message container、cwd 和 tool instance 做了归属核对，0 mismatch。实验使用 deterministic fake model/probe，不等同真实 LLM 压测。
- Claim：500 并发会话、0 次跨会话状态冲突。
  - 等级：A（限定实验条件）。
  - 原因：新增结果为 500 sessions / 500 worker threads / 500 barrier overlap，500/500 engine、budget、message、tool instance 独立，0 owner/cwd mismatch；结果基于干净 `HEAD` 快照，不能外推为真实模型吞吐或长时间压力稳定性。
- 建议：当前 bullet `[KEEP + ADD DATA]`，但必须注明“500 个 deterministic fake session、单次 barrier overlap、0 mismatch”，不要扩写成真实模型吞吐或长期压力稳定性。

### XEYO-5：Terminal-Bench 2.1

- Claim：全量 63/89、70.8%。
  - 等级：B（结果文件存在，但 provenance 冲突且文件被 ignore）。
  - 原因：本机有 89 个 result，解析分布为 63/25/1（pass/fail/missing）；但 tracked `docs/BENCH-口径.md` 将 70.8% 标为接力并集，并明确禁止把它当单引擎全量成绩。
  - 建议：当前 bullet `[REWRITE]`。在统一来源前，不写“XEYO 全量单引擎 63/89”；若采用接力口径，必须把“接力并集、k=1、各来源分解”写进 bullet 或面试解释。

## 4. 当前最小新增实验集合

本轮已执行，全部放在 `benchmarks/resume_evidence/`：

1. `xeyo_long_task_control.py`：保存正常任务、max-turn/USD runaway、L1/L2 loop 和 false-positive 原始结果。
2. `xeyo_mcp_adversarial.py`：保存 MCP 未知目标、spoof、enterprise deny、disabled、TTL、scope、revoke、参数变化和 retry 行为。
3. `xeyo_session_isolation_500.py`：保存 500 session 的 owner/cwd/tool/budget/message identity oracle。
4. `xeyo_usage_ledger_audit.py`：按代码既有公式重算本机 usage JSONL；不把本机快照冒充仓库固定数据集。
5. `xeyo_terminalbench_provenance.py`：读取本机 89 个结果并记录 tracked provenance；确认 70.8% 不能写成单引擎 XEYO 全量成绩。

## 5. Phase 0 后的简历动作建议

- 长任务：保留问题和架构方向；可使用本轮有界退出和循环阻断结果，但不要使用无来源的 `0.83s -> 0.02s`。
- 上下文治理：保留稳定前缀、T_now、分层记忆等设计；暂删 5.3 亿、99.41%、95.3%。
- MCP：保留 policy gate / scope / TTL / audit 方向，把“默认拒绝”改成代码真实的 ASK/DENY/ALLOW 语义，并披露 `9/10` 中参数重判失败。
- 并发：可以保留“500 个 deterministic fake session、0 mismatch”，同时注明不是真实模型吞吐压测。
- Terminal-Bench：保留为候选 benchmark，但当前 70.8% 只能按已登记的接力口径说明，不能写成无条件的单引擎全量成绩。

## 6. 本阶段未做的事

- 未修改生产代码、现有测试或 `.gitignore`；仅更新了本次新建的审计文档。
- 未移动或覆盖当前工作树中的任何在途文件。
- 未执行全套 pytest；已运行的测试命令和失败结果只按本轮实际输出记录。
