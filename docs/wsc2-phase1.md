# WSC V2 · Phase 1 —— Canonical Working State 是否值得成为新核心

日期：2026-09-23 ｜ 形态：**完全 shadow-only**（生产一行没动）｜ 成本：**零 API**
判据来源优先级：源码 > 本次固定实验 > 现有文档。文档里与源码冲突的地方写在 §10。

证据等级标记：【源码】= 文件:行；【账本】= 引擎自己写的 jsonl；【评测-离线】= 本次 126 个状态点、14 段会话、零 API；【建模】= 尺寸/比值口径；【待复核】= 分母或口径还没立住。

---

## 1. Hypothesis（为什么做这一步）

设想（用户原话压缩）：把 `History → DAG/Closure/Prune → Hot Prompt` 换成
`History → CanonicalWorkingState → Minimal Hot Prompt + History Index`，并取消"全局 append-only"，
只保 Event Store 与 History Index 只追加，Current State 允许原地重写。

Phase 1 只验证一件事：**能不能用 deterministic reducer 从事件流维护出一份可靠的"当前状态"。**
可靠 = Active Recall 高、错版本 0、协议不烂、生命周期不乱删。做不到就 STOP。

---

## 2. Source Findings（真实数据流，全部对齐到行号）

```
运行时事件
 └─ session 消息流  ~/.xeyo/sessions/<sid>.jsonl（行序 = stable event_id，append-only）
     · user 文本行 / assistant 行内 tool_use 块(或 OpenAI tool_calls) / role=tool 行 / user 行内 tool_result 块
     · ToolUse.id ↔ tool_call_id ↔ tool_use_id 是同一枚硬配对键         【源码】engine/query_loop.py, session/tool_sequence.py
     · 工具是否失败：tool_result 块的 is_error                          【源码】model/_openai_common.py
     · 文件版本：ApplyResult.version(=sha256) 只落到 journal.ChangeRecord.file_hash_after
       —— ActionJournal 默认关 ⇒ 事后从 jsonl 恢复不出文件哈希           【源码】memory/journal.py
     · error_kind 只在 SSE 事件里，未进 jsonl ⇒ 事后不可恢复             【源码】server/*, engine/*
        │
        ├─(V1 现状) engine/compact.keep_tail_cut / pair_safe_cut ──► C2 游标
        │        └─ memory/runtime.try_extend_c2：收益闸→稀发闸→θ=1 经济闸→冷却→硬顶
        │              └─► memory/wsc_projection.project_c2_messages(messages, working, cwd=)
        │                     └─ synaptic/project → graph(DAG) → closure → prune(cards)
        │                            → assemble(段: CONSTRAINTS/UNRESOLVED/TODO/WORKING SET/MAIN/
        │                              DECISIONS/PRUNED/NEXT/REQUESTS/REHYDRATED/PATHS/HEAD)
        │                            → budget(fixed 1800 / main 1200 / index 1600，index 只报账不裁)
        │                            → ColdStore(gzip+JSON 权威 + 文本视图) → Read 可回拉
        │
        └─(V2 旁路，本次新增) memory/wsc2/events → reducer → WorkingState → projector/audit
               完全独立于上面那条链；wsc_projection.py 里 0 处 wsc2 引用（有测试守着）
```

一句话：**C2 拥有触发权，WSC 决定"压成什么"，DAG/closure 只在 V1 这条链上选历史节点。**

---

## 3. Changes（本次实际落的文件）

| 文件 | 作用 | 是否被生产读 |
|---|---|---|
| `python/memory/wsc2/__init__.py` | 唯一开关 `XEYO_WSC_IMPL=v1\|v2\|shadow`，脏值落回 `v1` | 否（无调用方） |
| `python/memory/wsc2/events.py` | 事件视图：行序即 event_id，双形状归一（Anthropic 块 / OpenAI tool_calls） | 否 |
| `python/memory/wsc2/state.py` | **schema v0**：`Fact{fact_id,kind,key,value,status,created_by,last_event,superseded_by,resolved_by,version,provenance,evidence}` + 保守状态机 | 否 |
| `python/memory/wsc2/reducer.py` | **deterministic reducer v0**（§5 的 7 条规则） | 否 |
| `python/memory/wsc2/projector.py` | 最小状态渲染 + `state_hash`（只用于量尺寸） | 否 |
| `python/memory/wsc2/audit.py` | 事后金标（retrospective activeness）+ V1 文本指标 | 否 |
| `python/tests/wsc2/test_state_reducer_v0.py` | 24 条回归（含分层守卫、影子守卫、循环性自检） | 提交门 |
| `_wsc_out/_wsc2_phase1.py`（不入库） | 离线审计台 | — |

**没有**改：`synaptic/*`、`engine/compact.py`、`memory/runtime.py`、`memory/wsc_projection.py`、任何默认投影。

---

## 4. Schema v0（只收"有可靠事件来源"的）

五类事实：`request` / `file` / `tool_call` / `failure` / `todo`。
状态：`ACTIVE / SUPERSEDED / RESOLVED / CANCELLED / HISTORICAL`。每条带 `evidence`（哪条规则动的它）+ `provenance`（事件号）。

**故意不收**（这是设计，不是偷懒）：

- `goal`：runtime 里没有"目标完成/失败已解决"事件【源码】只有 todo 列表持久化；
- `constraint` / `decision`：**没有任何 deterministic 来源**。收进来就无法回答"谁 supersede 了它"，
  于是 Canonical State 退化成第二种有损摘要——正是 §六禁止的事。
  审计台对它们的唯一诚实产出是"字面量 + provenance"，而 V1 的 CONSTRAINTS/DECISIONS 段
  已经在做同一件事（靠分类器），所以 V2 在这一层**没有能力优势**（见 §9）。

---

## 5. Reducer v0 的 7 条规则（不明确 ⇒ KEEP）

| # | 触发 | 动作 | evidence 标签 |
|---|---|---|---|
| 1 | user 文本 | 建 `request`；同文重发只并 provenance 与 `repeat` | `user_text` |
| 2 | tool_use(有 call_id) | 建 `tool_call`；记下 `signature=hash(工具名+入参)` | `tool_use` |
| 3 | tool_result 配对 | 对应 `tool_call` → RESOLVED | `tool_result_paired` |
| 4 | tool_use(Write/Edit/…) 路径 p | p 的旧 ACTIVE 事实 → SUPERSEDED，新事实 ACTIVE、version+1 | `write_after_write` |
| 5 | tool_use(Read) 路径 p | 只 `mark_used`，**不**加版本 | `first_read`/touch |
| 6 | tool_result(is_error) | 建 `failure`（key=call_id，带 signature） | `is_error` |
| 7 | 同 signature 的成功回执 | 旧 `failure` → RESOLVED | `identical_retry_succeeded` |
| 8 | TodoWrite 快照 | 同 item 状态变 ⇒ 旧行 SUPERSEDED；`completed/cancelled` 直接落状态 | `todo_snapshot` / `todo_status_literal` |

零正则读用户语义、零读工具输出文本。新请求**不**盖旧请求。

---

## 6. Evaluation（126 个状态点 × 14 段会话，全离线）

金标 = **事后视角**（retrospective activeness）：某事实在 t 之后仍被事件引用 ⇒ 它在 t 是"当前事实"。
金标完全由原始事件流算出，不读 reducer 的记账（否则召回率恒等于 1，这条自检已进测试）。

| 指标 | 值 | 分母 |
|---|---|---|
| Active Recall · file | **1.000** | 430 条金标 |
| Active Recall · failure(未解决错误) | **1.000** | 643 |
| Active Recall · current request | **1.000** | 125 |
| Active Recall · todo(未闭合项) | **1.000** | 308 |
| Wrong-version（当前版本指错事件） | **0** | 184 次校验 |
| 同 key 多条 ACTIVE（"旧值+新值同时在场"） | **0** | 126 点 |
| 工具配对：leak / lost | **0 / 0** | 165 |
| Stale 污染 · file（按事后判据） | 中位 **0.75** | — |
| Stale 污染 · failure / request / todo | **0.00** | — |
| 代表点覆盖 | multi-turn 12/14、多文件 10、失败 13、重试 13、todo 8、长会话 14、旧版本被替 12、多未解决 13；**中断恢复 0/14（未采到）** | — |

尺寸与延迟（【建模】/【评测-离线】，同一把 token 尺）：

| | 中位 token | p95 时间 |
|---|---:|---:|
| 完整历史原文 | 23,292 | — |
| V1 整份投影（状态段 + 原始尾） | 7,530 | 187 ms |
| V2 状态段 alone | **536** | reduce 7.8 ms（含全量重放）+ render 0.21 ms |
| V2 状态段 + 同一条原始尾 | 1,102 | — |

⇒ **V2/V1 同尾部尺寸比 0.28**；V1 相对原文压缩 78.7%。
⇒ 增量性验证成立：单事件成本前半段 6.1µs / 后半段 6.4µs（**比值 1.06，不随历史长度上升**），
而"每轮从头推断"的形状是 5.5 ms 起步、p95 187 ms。
⇒ 缓存代价（对 §十七很重要）：**126 个相邻状态点里 0 个状态哈希不变** ⇒ Current State 每枪都要重写。
536 token × 每枪重填 ≈ 未命中面 536 token，θ=1 下折算 ¥0.0002/枪量级【建模】，可接受但必须实测。

---

## 7. Regressions / 未达成的部分（不粉饰）

1. **CONSTRAINTS / DECISIONS 没有被 V2 接管**：无 deterministic 来源（§4）。设想里"只放 ACTIVE 的约束/决定"这一条，Phase 1 **证不出来**。
2. **旧请求不能退役**：532 条历史请求事实存在，但"这条已完成"没有事件证据 ⇒ V2 只能把它们标成"生命周期未定"的归档段，不能删。设想 §十一 的收益（REQUESTS 变 Active Requests）只兑现了"能识别当前那条"，没兑现"其余可丢弃"。
3. **file 层 stale 0.75**：按事后判据，状态里 3/4 的路径之后再没被碰。这是"保守 KEEP"的代价，不是 bug；但也说明**"状态干净"这件事光靠 reducer 到不了底**，要么引入老化策略（那是 policy 不是证据），要么接受。
4. **每枪重写 Current State** ⇒ 冻结头/稳定追加这些 V1 机制在 V2 里不是白长的，删之前要先有实测成本。
5. 中断恢复类别 0 样本；V1 段内重复率这次没测（`v1_duplicate_ratio` 是在"状态段+原始尾"整份文本上算的，中位 0，与既有【账本】"头内行重复 32.4%"**不是同一口径**，不可混用）。

---

## 8. Complexity Ledger（§二十二）

| | V1 | V2 Phase 1 |
|---|---|---|
| 新增核心模块 | graph/closure/prune/rehydrate/seeds/freshness/governance… | 5 个文件（events/state/reducer/projector/audit）|
| 新机制数 | 十余个互相补偿 | **1**（事件→状态） |
| 配置项 | 多个 env + params | **1** 个 `XEYO_WSC_IMPL`，且生产无人读 |
| 持久状态 | ColdStore + working.json + 5 本账 | **0**（只产 shadow 日志） |
| LOC | — | 约 860（含注释/测试另计 24 条）|

---

## 9. Migration Matrix（B：旧机制 → V2 对应能力 → 证据 → 判定）

| 旧机制 | 现在解决什么 | V2 对应能力 | 证据 | 判定 |
|---|---|---|---|---|
| Event Store(消息流)/append-only | 原文耐久、可精确回拉 | 直接复用，作为 v2 的 Event Store | 【源码】 | **KEEP** |
| ColdStore + `Read(file,offset,limit)` | 剪掉的内容可恢复 | 完全保留（不重写第二套） | 【源码】+ 既有折叠账 | **KEEP** |
| DAG(graph) | 供 closure 选历史节点 | 状态层不需要；但**取回路径**仍需 | 【评测-离线】状态召回 1.0 与图无关 | **MIGRATE→DEFER**（Phase 3 前不删） |
| closure(hops=2) | 选"当前该看哪些历史" | WorkingState 取代其**语义**角色 | §6 四路 1.0 | **MIGRATE**（Phase 2 A/B 后定） |
| MAIN 段 | 承担 current state | 由状态段承担（file/failure/todo/request） | §6 | **MIGRATE 候选**，但 MAIN 也承载"历史预览"，那部分 V2 无对应 |
| PATHS | 历史路径索引 | `WorkingSet.files`（中位 25 条 ACTIVE 事实） | 【评测-离线】 | **MIGRATE**：热层只留工作集，全量进 History Index |
| REQUESTS 归档 | 留住用户说过什么 | current + archive 两段，archive 不可删 | §7.2 | **KEEP（降级）** |
| CONSTRAINTS/DECISIONS 卡片 | 留住硬约束/决定 | **无对应能力** | §4、§7.1 | **KEEP V1**（V2 不接管） |
| PRUNED cards + 句柄 | 可恢复性 | 不属状态层 | 既有【账本】句柄面占头 ~40% | **KEEP**，Phase 3 处理 |
| budget(fixed/main/index) | 尺寸闸 | 状态层天然小 | §6 尺寸 | **DEFER**（index 不裁的缺陷与 V2 无关，另案） |
| journal_layout / stable append | 缓存稳定 | 与状态层正交（Transport 私有） | §6 哈希 0/126 不变 | **KEEP**，但只在 Transport 里生效 |
| frozen head / cadence | 同上 | 同上 | 【账单】已有实测收益 | **KEEP** |
| C2 触发 + θ=1 + 三闸 | 便宜安全地发 | 完全不动 | 【账单】¥0.0284→0.0104 | **KEEP** |
| pair_safe / keep_tail_cut | 协议安全 | 状态层不碰；Raw Tail 策略留原样 | 【源码】+ 回归 | **KEEP** |
| hardtop(force) | 超窗兜底 | 不动 | 【账本】真流量观察到 2 次 | **KEEP** |
| fallback→expand(D1) | 视图丢失时恢复 | V2 不新增；仍要在 V1 修 | 既有【评测-离线】：生产 0 次触发，真问题在超大 Read 区间 | **KEEP 为独立 correctness 案** |

---

## 10. Decision 与 Next（I：阶段结论）

**Decision：KEEP（继续做 shadow），设想"部分成立"。**

- 成立且比预期强：**结构层**（文件版本 / 工具配对 / 未解决错误 / 未闭合 todo / 当前请求）
  可以用纯 deterministic、增量、零语义猜测的方式 100% 维护，且**尺寸只有 V1 的 1/14**。
  这一层确实比"每轮从历史里选节点"更适合当核心 —— 因为它有证据、可审计、复杂度是 1 个机制。
- 不成立：**"当前状态 = 语义摘要"那一半**。约束/决定/请求完成度没有事件证据，
  V2 在这一层没有任何优势，硬做就是第二个有损摘要。设想 §8/§9/§11 里"段全砍掉、只放 ACTIVE"
  必须以"这些段先有生命周期证据来源"为前提，而那个来源目前不存在（除非引入 LLM/语义，
  与 §十五 冲突）。
- 因此下一步不是删 MAIN，而是 **Phase 2：V2 projector 的离线 A/B**——
  同尾部下比 Active Recall / Stale / 尺寸 / 事后取回次数，验证"状态段替换 MAIN+PATHS"不掉信息。

**Next highest-leverage problem**：给 CONSTRAINTS/DECISIONS 找一条**事件级**证据来源
（例：把 V1 分类器的 verdict 当作"带 provenance 的字面事实"入账，生命周期仍按 KEEP 保守），
否则 V2 永远只能接管会话状态的四分之一，"新核心"名不副实。

Stop Condition（§二十三）：**未触发** —— deterministic reducer 下 Active State 是可靠的。
