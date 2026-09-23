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
     · 文件版本证据有**两处**，且默认链路上就有：
       (a) **读时哈希** `observed_hash = content_hash(最后一次精确 Read 的回执)`
           —— 由 `synaptic/filestate.py:171` 从转录算，**不依赖 ActionJournal，一直在**；
           同一模块还维护 `read_ranges`（覆盖面）、`stale/stale_at`（写后过期时钟）、
           `related_errors`、`diff_summary`，以及 `working_set(limit=12, pin, recent)` 选边。
       (b) **写后哈希** 才只在 `memory/journal.py:38 ChangeRecord.file_hash_after`，
           而 ActionJournal 默认关 ⇒ "我这次写之后文件是什么内容"事后不可恢复。
       ⇒ v0 的 `hash_verified=False` 只对 (b) 成立；**先前写"文件哈希只在默认关闭的
       ActionJournal 里"是错的**（顾问抓到，已按源码改）。
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


---

## 11. Phase 1.5（顾问评审后的语义收口，零 API，仍 shadow-only）

评审给的 4 问，逐问的结果——**其中一问把 Phase 1 自己的结论改掉了**。

### 11.1 先接受三条纠正（都是我说过头）

| 我说过的 | 状态 | 改成 |
|---|---|---|
| "尺寸只有 V1 的 1/14" | **不作结论** | 只说"同尾部 **0.28**"（536 是纯状态段、7,530 是整份投影，不同口径） |
| "reducer 7.8ms vs V1 187ms" | **不作结论** | 只说"reducer 自身增量成本 µs 级不随历史升"；**Full Projection vs Full Projection 未测**，那是 Phase 2 |
| "126/126 状态哈希都变" 记在 Regressions | **移出** | Current State 本就该可重写 ⇒ 它是 Transport 的输入项，不是退化 |
| "判死：尾部 token 上限 / 工作集原地刷新" | **改词** | 尾部 token 上限 = **DEFER**（Phase 1.5 没产生反对它的证据；`_tail_cap_scan` 只证明"当时没收益"）；"工作集原地刷新"要说清是哪一层：**V2 对 `files[path]` 的 supersede 是正在做的、不判死**；判死的只是"V1 那种在 prompt 段里原地改写文本" |

### 11.2 第 1 问：file stale=0.75 的真面目 —— ~~不是 auditor 太严，是 V2 几乎不去噪~~ **【本节归因已被 §14 重测取代：V2 的绝对路径归一化与 V1 不同源，导致按完整路径 join 时 1,125 条进 FP 桶；改为 basename join + V1 同源键后真实分布是 0.8% 真过期】**

按类别 pooled（126 点，`gold ∩ active / active` 当 Active Precision）：

| fact class | Recall | **Precision** | active | gold |
|---|---:|---:|---:|---:|
| failure（未解决错误） | 1.000 | **1.000** | 643 | 643 |
| todo（未闭合项） | 1.000 | **1.000** | 308 | 308 |
| current request | 0.936 | **0.929** | 126 | 125 |
| file | 1.000 | **0.243** | 1,767 | 430 |

⇒ 结论明确：**failure / todo 两类"高 Recall + 高 Precision"同时成立；file 类只成立一半——什么都没丢，但基本没去噪**。顾问的 P0.5 判断是对的，`536 tok` 短 ≠ 干净。
`request` 的 0.936/0.929 与 Phase 1 的 1.000（逐点中位）差在 pooled vs median，且 **8/126 点当前请求判错，未定位**，列开放项。

6 类归因**未收口**，原因查清了是我审计台自己的两个缺陷，不是 V2 的问题：

1. V1 的 `FileState` 键是**原始路径串**、V2 是归一化串 ⇒ join 对绝对路径系统性失配；改成两边同归一化后 **仍 1,183/1,337 落 FP 桶**；
2. 剩下的主因是**建事实的时机不同**：V2 在 `tool_use` 建行，V1 在 `tool_result` 建表，而我的状态点恰好取在"刚发出一次工具调用之后一行" ⇒ 边界系统性地对不齐。
   ⇒ 归因桶要先修这两处才有意义；**在此之前不要引用 6 类分布的任何一个数**（含 140 条 TRUE_STALE）。

### 11.3 第 3 问：V2 的 file 事实比 V1 的 FileState **少三样语义**（本轮最该记住的负结果）

> 结论方向成立，**分母作废**：下表 227 是"键域失配下侥幸 join 上的条数"，键域与 V1 同源后
> 真实覆盖率是 **1,714 / 1,717**（见 §14 表二），缺口比这里写的更大、更普遍。

在 227 条 V1 有 `FileState` 的 ACTIVE 文件事实上：

| V1 有 | V2 v0 有 |
|---|---|
| `observed_hash`（读时哈希） | 无 —— **218/227** |
| `read_ranges`（读过哪些区间，防"读一半当读全"） | 无 —— **218/227** |
| `diff_summary`（写后变更摘要） | 无 —— 28/227 |
| `related_errors` | 无 —— 0/227（V1 也没挂上） |

⇒ 直接推翻"V2 的文件状态更自然"：**在文件这一类上 V2 v0 是 V1 的降级版**，它只是"路径 + 版本号 + 事件号"。
⇒ 也给出下一步的正确答案：V2 该**复用 `synaptic/filestate.build_file_states` 的语义**（覆盖面/写后过期/错误关联），而不是重造一个更薄的文件事实。

### 11.4 第 2+4 问：StateSourceAdapter 与"派生事实"的可行性（源码已定位）

顾问说的对：**不该把所有事实都先降级成转录事件**。仓库里确实有权威件可直接读：

- `engine/goal_state.py:274 GoalStore`（+ `:70 Goal`）
- `tools/todo_write_tool/todo_write_tool.py:128 set_todo_store` / `TodoStore`（server 侧按会话注入：`server/session_pool.py:597`）
- 工具注册表上的 `read_state`（`tools/catalog.shared_read_state`，经 `engine/query_engine.py:1685` 传入 scheduler）
- `memory/journal.py:417` 的 ChangeRecord（ActionJournal 开时才有）

⇒ Phase 1.5 的接线做法：`StateSourceAdapter` 输出带 `authority ∈ AUTHORITATIVE / DERIVED / LITERAL / UNKNOWN` 的信号，
`Constraint/Decision` 走 `DERIVED`（V1 分类器 verdict + 原话 + provenance + 生命周期 UNKNOWN/ACTIVE_BY_DEFAULT，只有明确证据才 SUPERSEDE/RESOLVE/CANCEL）。

**但这一条被实测卡住了一半**：~~在 dev 语料的 126 个状态点上，V1 投影的 `[CONSTRAINTS] + [DECISIONS]` 行数 = **0**~~
**这句作废**——它是 §12 开头那个段解析器 bug 的产物（行内段头没认出来，整份头灌进 `_TOP`）。
修好后同一批语料有 **1,110 行**约束/决定，事后复用金标 = **36 行（3.2%）**，详见 §14 表三。

### 11.5 Phase 1.5 判定

`REWORK`，不是 `KEEP`，也不是 `REVERT`：

- 已经拿到顾问要的 Active Precision（分 4 类），且**它改变了结论**（file 类只成立一半、V2 文件事实是 V1 的降级版）；
- 归因桶与约束类金标各有一处未收口的度量缺陷 ⇒ **先修审计台，再谈 Phase 2 的 A/B**，否则 Phase 2 会把这两个缺陷带进 V1-vs-V2 的对比里。


---

## 12. Phase 2 —— V1 Full Projection vs V2 Full Projection（同点、同尾部、同尺，112 点）

前置：本轮第一版把 V1 臂算成 0，原因是**审计库的解析 bug**——生产热层段头是行内的
（`[CONSTRAINTS] 目标: …`），`v1_sections` 原先只认整行段头 ⇒ 整份头被灌进 `_TOP`。
已修 `memory/wsc2/audit.py` 并加回归（`test_v1_section_parser_handles_inline_headers`）。
**因此 §6 里所有 V1 侧数字（`v1_duplicate_ratio 0`、`v1_file_recall 1.0`、`v1_multi_section_paths 0`）一律作废。**

| 逐点中位 | V1（生产整条链） | V2（每枪从头重放 + 渲染，不给增量便宜） |
|---|---:|---:|
| 状态段 token | **10,085** | **485** ｜比值 **0.0694** |
| 整份（状态段 + 尾部）token | 10,683 | 4,516 ｜比值 **0.5405** |
| 尾部 token | ~600（V1 把 4,092 的尾**骨架化**了） | 4,092（原样保留） |
| 原始全文 | 99,956 | 99,956 |
| Full projection 延迟 | 40.4 ms（p95 **172**） | 1.74 ms（p95 **6.6**） |
| 句柄 / 被剪行数 | **44** / 151.5 | **0** / 151.5 |
| 状态段内重复行 | 6.57% | 同 key 多 ACTIVE **0** |

同金标下的质量对照：

| 类别 | V1 Recall | V2 Recall | V2 Precision | V1 侧同判据 |
|---|---:|---:|---:|---|
| file | **0.751** | **1.000** | 0.353 | 头内行被金标支撑占比 **0.329**（宽口径，只作下限） |
| current request | 0.902 | 0.920 | 0.920 | — |
| failure / todo | 不可测（无事实概念） | 1.000 | **1.000** | — |

### 三件被这轮改掉的事

1. **"V2 更小"是真的，但比 0.28 更复杂**：状态段确实只有 V1 的 6.9%；可 V1 同时还把尾部骨架化（4,092→~600 tok），而 V2 现在**没有冷层/句柄那一半机制** ⇒ 整份只降到 54%。**拿"小"当卖点必须先补齐可找回性，否则是拿我们的半成品比人家的成品。**
2. **去噪不是换核心白送的**：V2 的 file precision 0.353，V1 头被支撑占比 0.329——**两臂同量级地脏**。顾问担心的"Recall 高 Precision 低"成立，但它是 V1/V2 **共同**的缺口，需要一个独立的 relevance 策略（#31），不是 V2 独有的病。
3. **V2 的实质增量在 recall 与结构不变量上**：V1 会把 24.9% 的事后仍要用的路径挤出上下文（working_set limit=12 + budget 挤掉），V2 全留；wrong-version 0、同 key 双 ACTIVE 0、协议配对 0 leak/lost。

### Phase 2 判定：**REWORK，V2 不可上线，V1 一个机制都不删**

按 Gate 逐条：

| Gate | 结果 |
|---|---|
| wrong-version = 0 / tool corruption = 0 | ✅ |
| history discoverability / Read correctness = 100% | ❌ **V2 句柄数 0，被剪 151.5 行无处可寻** ⇒ 硬不变量不过 |
| 三项里赢两项（Precision↑ / Stale·Dup↓ / Tokens↓） | Tokens ✅；Stale·Dup ✅（V2 0 同key双 ACTIVE，V1 行重复 6.6%）；Precision ➖ 平手 ⇒ **2/3 勉强达成，但输在硬闸** |
| recall 不实质下降 | ✅（file 1.000 > V1 0.751） |
| cost / latency | ✅ 方向性成立（Full projection p95 6.6ms vs 172ms） |

⇒ 下一步按依赖顺序只能是 **Phase 3（History Index：让被剪内容重新可寻）**，不是 Phase 4/5 的 transport 或成本优化。
⇒ 顺带一句口径：`126/126 状态哈希变化` 在整份比 0.54 面前不是问题——真正贵的是 V1 那套"为了稳而保 10k tok 头"的机制；等 Phase 3 补齐后再算重填成本才有意义。


---

## 13. Phase 3 —— History Index（shadow-only，零 API，60 点）

先撤回一句：**§12 表里"V1 句柄中位 44"是假的**——我那条正则把 `#` 也算成句柄了。
按 `handles.py` 的真实形态（生产档 = `Read(file_path=…, offset, limit)`，回落档 = `expand(node://…)`)
重测，数字在下面。

设计只有两条决定性的：**① 定位符一律普通 `Read(路径, offset, limit)`，不新增 parser（D1）；
② 页文件 append-only ⇒ 行号永不漂移（事件流 append-only，生命周期变化另起一行，不原地改写）。**
namespace 只 4 个：requests / files / errors / tools。**不做 timeline 页**——Event Store 本身就是
timeline 且每行可直接 `Read(session, offset=行号)`，再抄一份就是把 V1 的胖子重造（第一版就踩了，
索引 10,627 tok ≈ V1 整份头，删掉 timeline 后降到 4,780）。

| 指标 | V2 Phase 3 | V1 同 corpus 同尺 |
|---|---:|---:|
| **常驻** metadata | root 中位 **54 tok** | 头中位 **9,855 tok** |
| 索引 on-disk（中位/点） | 4,780 tok / 143 条记录 | — |
| 页 locator 真回读 | **1,981 / 1,981 = 100%** | — |
| 原文行 locator 真回读 | **814 / 814 = 100%** | — |
| 卡片行里带**完整可执行句柄** | 不适用 | **3,724 / 23,822 = 15.6%** |
| 卡片行含句柄形状但不完整 | 不适用 | **208 行** ⚠️ 需逐条人判：PRUNED 卡正文里本来就带被裁断的 `Read(...)` 入参，不能直接算坏引用 |
| 索引 on-disk 字节 | 1.61 MB | V1 冷层目录 0.43 MB ⇒ **V2 索引比 V1 冷层大 ~3.8×（磁盘，不是 token）** |

### 止损判定：**不 STOP，KEEP**

- §二十三 的止损条件是"为 recoverability 重造一份和 V1 一样大的 metadata"。常驻口径下 V2 是
  **54 tok vs 9,855 tok**，没触发；可发现性从 Phase 2 的"无处可寻"变成**逐行可寻且 100% 回读成功**。
- 记一笔真实代价：磁盘 3.8×。可收（摘要 110→40 字，或只给被剪区开记录），**但先不为省磁盘加机制**（§十五）。
- V1 侧那条 15.6% 是本轮最值钱的观察：**热层里绝大多数卡片行并不带可执行取回口**，
  "被剪节点必可拉回"这句话在实际渲染里主要由冷层+视图保证，不靠卡面句柄。要引用"V1 有 44 个句柄"这种说法一律作废。
- 下一步（Phase 4 才有意义）：把 root 计入 V2 的 full projection 重跑 §12 —— 预期整份比从 0.5405
  变成 ~0.543，因为 root 只有 54 tok；真正会动数字的是"V2 也开始骨架化尾部"，那是 V1 机制的迁移，属 Phase 5。


---

## 14. #32 收口：键域统一之后，归因桶和约束类金标才第一次能引用

§11.2 当年留下一句"归因桶要先修两处才有意义，在此之前不要引用 6 类分布的任何一个数"。本轮把两处都修了，
**并且查出真正的病因不是审计台，是 V2 自己**——所以"修审计台"这个任务名本身就是错的。

### 14.1 1,125 条 FALSE_POSITIVE 的根因：V2 的绝对路径归一化与 V1 不同源

`synaptic.textutil.tool_input_paths` 会**抹掉盘符**：`D:\lea\a.py` → `/lea/a.py`（实测：
`Read → ['/lea/XenYon code/python/tests/a.py']`、`Edit → ['/lea/a.py']`）。
而 `memory/wsc2/events.py` 早期自造了一套归一化 ⇒ 同一个文件在 V1 的 `FileState` 里是 `/lea/a.py`、
在 V2 的事实键里是 `d:/lea/a.py`。**两臂各自内部都自洽，只有跨臂 join 时全线失配**——
于是"这条 ACTIVE 文件事实 V1 根本没跟踪"被判成假阳性，绝对路径越多越严重（1,279 条里 87.9%）。

修法是删掉 V2 的自造轮子、直接让 V1 的归一化做权威（`_norm_path` 内部调 `tool_input_paths`，
只在 V1 不可用时退回本地归一化）。同时修审计台的两处真缺陷：状态点改取在 `tool_result` **之后**
（对齐 V1 建表的时机）、V1 侧键也过同一个归一化，工作集在场判定改用 basename
（V1 的卡面对长绝对路径会做中段裁断，整串比对必然漏）。

### 14.2 修完之后：file 类"没去噪"这句要换成三个更准的事实

同一 126 点、同一把严格事后复用尺（pooled）：

**表一 · Active Recall / Precision**

| fact class | Recall | Precision | active | gold | vs §11.2 |
|---|---:|---:|---:|---:|---|
| failure | 1.000 | 1.000 | 619 | 619 | 不变 |
| todo | 1.000 | 1.000 | 302 | 302 | 不变 |
| request | 0.9365 | 0.9365 | 126 | 126 | 不变（8/126 判错仍未定位） |
| file | 1.000 | **0.2551** | 1,717 | 438 | 0.243 → 0.2551（分母换血） |

**表二 · 1,279 条"事后没再被引用"的 ACTIVE 文件事实，6 类归因**

| 归因 | 条数 | 占比 | 这条说的是什么 |
|---|---:|---:|---|
| `HISTORICAL_BUT_RESIDENT` | 1,024 | 80.1% | V1 在同一状态点上**也把它留在热层** ⇒ 两臂共同缺"相关性寿命"，不是 V2 独有缺陷 |
| `VERSION_STALE` | 244 | 19.1% | 文件后来又被改写，V1 会打 `STALE`+`stale_at`，**V2 v0 没有这个字段** |
| `TRUE_STALE` | 10 | **0.8%** | 真·过期后不再相关 |
| `RELEVANCE_UNKNOWN` | 1 | 0.1% | — |
| `AUDITOR_FALSE_POSITIVE` | **0** | 0% | §11.2 的 1,125 条 ⇒ 全是键域失配 |
| `STILL_RELEVANT` | 0 | 0% | 定义上被 `HISTORICAL_BUT_RESIDENT` 吃掉 |

⇒ 三句话：**① V2 自己的真过期只有 0.8%，"V2 几乎不去噪"这个说法作废；② 剩下 80% 是 V1 也一样驻留的，
所以 0.2551 这个 precision 衡量的是"这套状态有没有相关性生命周期"，两臂共同的答案是**没有**（V1 侧同轴的字面正当率也只有 0.329，见 §12）；
③ V2 唯一比 V1 差的那 19.1% 有明确落点——缺 `stale` / `stale_at`，正好是 #31 要复用的字段。**

**表三 · V2 的 file 事实相对 V1 `FileState` 的语义缺口（键域统一后第一次有真分母）**

| V1 有 | V2 v0 | 覆盖 |
|---|---|---|
| `observed_hash` | 无 | **1,558 / 1,714** |
| `read_ranges` | 无 | **1,558 / 1,714** |
| `diff_summary` | 部分（写事件摘要，不含读后变更） | 518 / 1,714 |
| `related_errors` | 无 | 0 / 1,714（V1 侧也基本没挂上） |
| `stale` / `stale_at` | 无 | 见 14.2 表二 244 条 |

**表四 · 约束 / 决定类：终于有分母**

| 指标 | 值 |
|---|---|
| V1 `[CONSTRAINTS] + [DECISIONS]` 行数（126 点） | **1,110**（§11.4 的 "0 行" 作废） |
| 事后被字面再引用的行 | **36 = 3.2%** |
| 卡面被中段裁断、无法判定的行 | **45** ⚠️ 需人判 |

⇒ 3.2% 只能读成**字面复用的下限**：这把尺不认改写与语义复用，所以**不能反读出"96.8% 是噪音"**。
它能撑住的结论只有一条：想给约束类做 Recall/Precision，必须先把"改写也算复用"的判定做出来
（零成本的词面/子集匹配做不到，这条属于 #31 的派生事实通道，不是新机制）。

### 14.3 本轮改了什么、还没动什么

改动只有两处，都不碰主链路：`memory/wsc2/events.py`（键域交给 V1 权威）+ `_wsc_out/_wsc2_phase15.py`（时机/键/join）。
回归：`tests/wsc2` 与 `tests/wsc + tests/wsc2` 全绿（数字见提交说明）。**零 API。**

欠账（不要引用旧值，但也不要以为已经刷新）：§6（Phase 1）与 §12（Phase 2）里 V2 侧的**文件类**行数/键统计
是在旧键域上算的，会把同一文件拆成两个键 ⇒ 那些数会动。修完键域后重跑这两台属新范围，未跑。

