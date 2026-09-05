# XEYO 转化为 harness —— 总纲 v5（现状盘点 + 执行路线）

> 目标：XEYO(agent) → XEYO(harness)。判据来源：`docs/DSH-可借鉴机制对照报告.md`（§0 四大工程重心 + 16 节机制清单）、
> `docs/XEYO-融合改造计划.md`（v1–v4 执行档案）、40–43 号最近波次设计。
> 视点：不是「再借机制」，而是**把 DSH 报告 §0 的四大支柱逐根补完**——它们是"harness"区别于"传统 agent"的判据。
> 盘点基准：2026-09-01 晚（git HEAD `1762f13`，工作区含 T36 未提交删除）。

---

## 0. 判据：传统 agent vs harness

| | 传统 agent | harness（DSH 式） |
|---|---|---|
| 状态与恢复 | 状态在内存/边上，崩溃靠猜 | **日志唯一真相**：append-only 事件流，恢复=重放，投影是派生 |
| 失败语义 | 异常 + 截断凑合 | **协议化**：结构化错误码 + 内嵌恢复指令，模型/UI 不猜 |
| 输出 | 一截就丢、截断=失败 | **输出经济学**：pruner → retention → spill 三层，截断带元数据 |
| 能力边界 | 估计值当决策依据 | **诚实**：partial/近似/声明如实标注 |

## 1. 四大支柱完成度（本盘点结论）

| 支柱 | 状态 | 已落地证据 | 剩余缺口 |
|---|---|---|---|
| ① 日志唯一真相/恢复 | ✅ 大部 | JSONL+COW 投影+sidecar；T4 崩溃尾合成；T8 compact checkpoint；T31 模式/会话 durable；rewind；41 号 goal 事件化 | request/header 请求快照（P2，请求可重建） |
| ② 失败语义协议化 | 🔶 **唯一剩余核心缺口** | 审批四值+intent+成对审计（T3）；友好错误（T34）；begin/end+correlation（T13）；goal blocked 结构化（T9）；Job 结构化（42 号） | **LLM 适配层**：错误码未归一、无 retry 事件帧、无 interrupted anchor（报告 §7 P1） |
| ③ 输出经济学 | ✅ | T1 spill+locator+截断元数据+per-tool 预算；T8 LLM 摘要前缀重放；T27 raw→spill→compact 顺序 | （观察项：bash 30k/Read 豁免已覆盖） |
| ④ 能力边界诚实 | ✅ | T35 成熟度诚实口径+surface 门；34 号冻结明确「不做 OS 沙箱」并如实约束 | 随 43 号 Phase 1 观测数据更新 |

## 2. 机制吸收核对（40–43 波次 + T 系列）

- **40 号 MCP×SKILL 企业级融合**：P0a（F1/F3/F4/F6a）+ P0b（网关/对账/冻结/指纹/注入）✅ 已提交，含契约测试 6 件套；T15（skill_loader 四件套）已并入此波 ✅。
- **41 号 goal-round-driver**（DSH `dsh-goal-round-driver`）：✅ `server/goal_round_driver.py` + `docs/设计/41-goal-round-e2e手工验证.md`；goal 轮次驱动、让位、预算独立已接线。
- **42 号 background jobs**（DSH `dsh-jobs`）：✅ `server/job_registry.py` + `tools/job_tools.py`（job_output/job_list/job_kill）+ bash 桥 + GUI 角标；验收清单 `docs/设计/42-background-jobs验收清单.md`。
- **43 号 bash 专用工具路由**：Phase 0（观测）✅ `plan_bash_route` + `tool.routed_observed` + `scripts/analyze_bash_routing.py`；**Phase 1（透明路由 auto|off）未做**。
- **T 系列（融合计划 v1–v4）**：P0 全批收官（T1–T7/T12/T25–T29/T33/T34/T39）；P1 收官（T8–T14/T16/T17/T30–T32/T35–T38）。

## 3. 剩余缺口清单（v5 视点，按支柱归类）

| # | 机制 | 来源 | 优先级 | 落点（草案） | 验收要点 |
|---|---|---|---|---|---|
| A | **LLM 失败语义协议化**：错误码集（NO_ADAPTER/AUTH/RATE_LIMIT/CONTEXT_WINDOW_EXCEEDED/EMPTY_RESPONSE…）、重试=新 turn 重建请求（不包 stream）、SSE `llm/retry`+`llm/retry-started` 帧、中断流非空前缀补 `interrupted` anchor、deepseek wire 细则（usage 先于 finish / reasoning passback / 5min idle watchdog） | 报告 §7 P1 | **P1·本轮开工** | `model/client.py`、`model/deepseek.py`、`model/openai_compat.py`、`engine/query_loop.py`、`server/routers/chat.py`、msgtypes 事件 | 失败统一 `finish{kind,failure}`；重试不产生两次计费请求退避 500ms→10s+jitter；客户端可渲染倒计时 |
| B | **hook 系统**（Codex 模型，非 DSH）| 融合计划 T22 | P1 | 新增 `engine/hooks.py` + `.xeyo/hooks/` | PermissionRequest fail-closed+短超时+Success/FailedContinue/FailedAbort |
| C | **网络域名白名单**：WebFetch 出站集中管控 | 融合计划 T20 | P1 | `tools/` 出站工具 + `.xeyo/settings.json` | deny 覆盖 allow + 每请求审计 |
| D | **GUI 投影推拉**：历史尾页 projections 水印 + 广播帧 higher-seq-wins；GUI 只渲染投影、动作只发命令 | 报告 §12 P1 | P1 | server SSE + gui store（todos/标题/goal/usage） | 消除前端折算漂移；重连从最低水位增量 |
| E | **Windows ACL 沙箱 PoC**（CreateRestrictedToken 轻版） | 报告 §13 P1 / T18 | **待拍板**：与 34 号冻结「明确不做 OS 沙箱」冲突 | `permissions/`+工具执行 | 需用户解冻；仅「工作区内可写+会话私有 temp」两档、partial 如实报 |
| F | request/header 事件快照（请求可重建） | 报告 §1 P1 | P2 | `session/persistence.py` | 逐字节重建请求 |
| G | SQLite 会话索引（T21）/ worktree 子代理隔离（T24）/ code-mode 档案（T23） | 融合计划 P2 | P2 立项 | — | 会话>几百个再做；best-of-N 场景 |
| H | 43 号 **Phase 1 透明路由**（`bash_routing: auto\|off` 默认 off，T1+T2 路由、L2 上移 registry、DENY 回退、worker 开） | 43 号 §4 | P1·在途收尾 | `tools/tool_registry.py`、`permissions/workspace_policy.py` | 路由命中返回内容+note；DENY 回退原 Bash；read_state 一致性 |
| I | 记忆机制 evidence-gated 开启（TOOL_AGING 等） | `docs/落地前事件.md` | 独立线 | — | 开一个验一个（p0b bat + 真实日志对账） |

## 4. v5 执行顺序

```
W1: A（LLM 协议化，核心 loop 最后一块拼图）→ H（43° Phase 1 收尾）
W2: C（网络白名单，小）→ B（hook 系统）
W3: D（投影推拉，GUI 架构）→ F（请求快照）
待拍板: E（沙箱，34 号冻结需解冻）; G（P2 立项按需）
独立线: I（记忆 evidence-gated，按真实运行数据开）
```

## 5. 红线（不得触碰）

- T_now 投影哲学（`docs/设计/32`）：运行时上下文不落史，「关闭后历史干净」；
- KV 前缀稳定（system 左段锁序、tool catalog 会话内冻结）；
- 权限三态 + 单向性（T26：policy 只能收紧）；`permissions/store.py` 指纹 v2；
- copy-on-write 投影；34 号冻结未解冻项（OS 沙箱、完整 Bash AST、Agent 写 `.xeyo-policy.json`）。

---
