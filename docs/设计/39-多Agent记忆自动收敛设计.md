# XEYO 多 Agent 记忆自动收敛线设计

> 仓库：`D:\lea\XenYon code`
> 版本：2026-08-29
> 定位：把对比文档 `XEYO-三方设计对比-DSH×Codex×XEYO.md` §10.4 第 3/4/5 条（「抄 Codex 异步收敛 job + 模型检索/citation，但落 XEYO 门禁」）落成可实施设计。是 **T14** 的先行件。
> 依赖既有能力：`python/memory/agent_scope.py`、`subagent_memory.py`、`governance.py`、`write_policy.py`、`memdir.py`、`journal.py`、`nightshift.py`。本设计**不改**这些文件的既有语义，只在其上**补一条"自动收敛线"**。
> 一句话：**子代理结束 → `SubagentHandoff.memories` → 主会话确认门禁 → 后台收敛 job → memdir 写入 + 索引原子重写；全程单写者、过 `write_policy` 门禁、可幂等、可 tombstone。**

---

## 0. 现状盘点：XEYO 已有 80%，缺的正是"自动"二字

已有（本设计复用，不重造）：

| 已有能力 | 文件:行 | 拿来做什么 |
|---|---|---|
| AgentScope 隔离 + 子代理剔除 Memory 工具 | `agent_scope.py:27-99` | 子代理**不能**直接写 memdir（保持，别放宽） |
| 子代理候选采集（`MEMORY_CANDIDATE` 标记） | `subagent_memory.py:17-21,143-151` | 已能从侧链 + 结论提取 `MemoryCandidate` 载荷 |
| 候选数据结构 | `governance.py:56-62`（`MemoryCandidate{content,source,evidence}`） | 收敛线的"原料" |
| 内容写门禁 | `write_policy.py:32-59`（`refuse_reason`） | 拒目录树/一次性计划/路径堆 |
| 笔记写入 + 索引原子重写 | `memdir.py:253`（`write_note`）、`memdir.py:205-224`（`rewrite_index`，tmp+os.replace） | 落盘 + 导航索引 |
| 单写者/一致性 | `journal.py:53-160`（per-path RLock + 可选 WorkspaceLock）、`nightshift.py:56-57`（`.nightshift.lock`） | 收敛 job 的并发护栏 |

**缺的**：子代理产出的 `MemoryCandidate` 目前只做**采集**（`harvest_subagent_memories` 返回 `memories_as_dicts`），**没有一条"确认→落库（含自动升级）→索引更新"的收敛线**，也没有像 Codex `memory_stage1/consolidate_global` 那样的**异步收敛 job**（`codex-rs/state/runtime/memories.rs:19,45`）。

> 对照 Codex 的"糟"：其自动收敛**治理弱**（靠模型 + 摘要，缺写门禁；全局单一 memory_root 易跨任务污染）。**XEYO 抄它的异步 job 思想，但必须带上门禁 + 仅主会话确认 + 分层作用域**——这正是本设计的缝合点。

---

## 1. 目标与非目标

**目标**
1. 子代理发现的可留档事实，能**自动、确定性**沉淀进 L4 memdir，且**过主会话确认 + `write_policy` 门禁**。
2. 收敛**异步不阻塞主循环**（复用 NightShift/job 思路），失败可重试、**幂等**、**不重复写**、**可 tombstone**。
3. **KV 不被动**：收敛只改 memdir/topics + 索引，不改主 JSONL / session.md / compact_cursor（保持 `agent_scope.py:28` 的"仅主会话"铁律）。
4. 需要时能**补一条 citation 溯源**（`path:lines|note`，仿 Codex `read_path.md:22-37`、`citations.rs`），让主会话下次可"回指来源"。

**非目标（明确不做）**
- 不把子代理全文/侧链 JSONL 打进主 store（保持 §10.4 第 2 条；只回传摘要 + 候选）。
- 不引入分布式锁（沿用 §28 §2.5.2「每文件单写者事务 store 无锁化」思路）。
- 不自动改 XEYO.md / session.md / 主 JSONL（铁律）。
- 不替代 NightShift 的离线重塑；二者是**两条互补的收敛线**（§6）。

---

## 2. 数据流（一条"确认→收敛"线）

```
子代理结束
  └─ run 结束回调：subagent_memory.harvest_subagent_memories(侧链, ..., main_session_id, agent_id, conclusion)
        → (memories_as_dicts, cleaned_conclusion)          # subagent_memory.py:143-151
  └─ 组装 SubagentHandoff(memories=[MemoryCandidate...])     # agent_scope.py:33-37
  └─ 主会话 tool_result 只追加"一条摘要 + 候选指针"           # §10.4 第 2 条，主历史只加一条
        │
        ▼
  ┌────────────────────────── 主会话确认门禁（必须过，才入队）─────────────────────────┐
  │ ① MemoryCandidate -> 主会话在"回传可见区"显式确认(如 /接受 该候选)？                │
  │ ② write_policy.refuse_reason(title, content) 是否为 None？（拒目录树/临时计划）       │
  │ ③ AgentScope.may_write_memdir(main) == True        （agent_scope.py:81-83）          │
  │ 通过 => 生成 MemoryNote(type,title,content,source,confidence,status='candidate')      │
  │ 拒绝 => 丢弃 + 记 journal（reason）——不写 topics、不进 MEMORY.md                      │
  └─────────────────────────────────────────────────────────────────────────────────────┘
        │ (通过)
        ▼
  ┌────────────────────────── 后台收敛 job（异步，可重试，幂等）──────────────────────┐
  │  复用归属：nightshift.py 的"空闲期"容器 或 独立 job 队列（见 §4 分期）                │
  │  步骤：                                                                             │
  │   ① acquire memdir 写锁（nightshift.py:56-57 同款锁；单写者）                        │
  │   ② content-hash 去重（同 workspace + 同 content 归一）——防子代理重复收敛            │
  │   ③ 再跑一次 write_policy.refuse_reason（双保险：确认后内容不可被绕过）              │
  │   ④ write_note(note, wsid)          → topics/<type>-<slug>.md（memdir.py:253）       │
  │   ⑤ journal.record_change(..., workspace_lock=锁)  → 同一事务（journal.py:143-160）   │
  │   ⑥ rewrite_index(notes, wsid)       → MEMORY.md 原子重写（memdir.py:205-224）        │
  │   ⑦ 状态转移 candidate -> active；写 tombstone（若有 supersedes/被拒）              │
  │  失败 => status 保持 candidate / job 标记 retryable（不污染 topics）                 │
  └─────────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
  主会话下次：MEMORY.md 索引注入（runtime.py:472-508）读到新条目 + 可选 citation 溯源。
```

**关键不变量**：
- 收敛线**只在主会话确认触发**，子代理自体永不触发写入（`agent_scope.py:95-99` 已剔除 Memory 工具，这里再补"候选未确认不写"）。
- 任何写都在**同一把 memdir 单写者锁 + journal 同事务**内完成，`write_note` + `rewrite_index` 原子（tmp+rename），**并发收敛/与主会话写不撕裂**。
- 收敛**不改**主 JSONL / KV / session.md；只增 topics + 索引 + journal。

---

## 3. 内容模型与状态机

复用 `governance.py:MemoryNote`，候选到落库加一个**最小状态机**：

| 状态 | 含义 | 何时进 | 可否进 MEMORY.md |
|---|---|---|---|
| `candidate` | 子代理发现，未确认 | `harvest` 产出 | 否 |
| `confirmed` | 主会话确认 + 过 `write_policy` | 主会话确认门禁 | 否（等落库） |
| `active` | 已 `write_note` + `rewrite_index` | 收敛 job 成功 | **是**（`indexable` 且 type∈ALLOWED_TYPES） |
| `dropped` | 被拒/重复/过期 | 门禁或幂等失败 | 否（记 journal；tombstone 若曾被 active） |

- 只让 **`active`** 且 `indexable`（`governance.py:44`）进 `MEMORY.md`（保持 §3.4.7「MEMORY.md 只做导航」与 `memdir.py:210` 的过滤）。
- 复用一个 `MemoryCandidate` 到 `MemoryNote` 的转换函数：**确定性、纯函数**（不进模型），字段映射 `content→content`、`source→source`、`type` 由 `parse_and_validate`/`ALLOWED_TYPES` 派生（`governance.py:88-99`），`confidence` 默认下限（候选→0.6，仅限事实类）。

---

## 4. 分期

**P0（最小闭环，先跑通）——T14 先行**
- 只做 **同步收敛**：子代理结束 → 主会话确认一次 → 复用一个轻量 `consolidate_subagent_memories(...)` 同步落库（走 §2 的①-⑦，但无独立 job 队列）。
- 交付：候选→确认→`write_note`+`rewrite_index`→`active`；`write_policy` 门禁 + 单写者锁 + content-hash 去重；`tombstone` 不复活。
- 验收：确定性单测 + 并发（两子代理同候选不重复写）+ 门禁（临时计划/目录树被拒）。

**P1（异步收敛 job）**——对齐 Codex `memory_stage1/consolidate_global`
- 加**后台 job**（复用 `nightshift.py` 空闲期容器或独立队列：`kind='memory_consolidate'`，形如 `state/runtime/memories.rs:19,45` 的 job 表），候选确认后**入队**，空闲期批量收敛。
- 支持 `retry`/`cancelled`（参考 `dsh-workflow`/`dsh-jobs` 的 job 结果语义）；失败不污染 topics，状态回 `candidate` 或 `retryable`。

**P2（检索 + citation）**
- 模型侧加 `memory_search`/`memory_read`（复用 `search.py`、`JournalQuery` 读端），返回 `path:lines|note` 溯源（仿 Codex `read_path.md`、`citations.rs`）；主会话引用时回写 `last_used_at`（`governance.py:40`）。

---

## 5. 测试点（确定性、可单测）

| # | 用例 | 断言 |
|---|---|---|
| 1 | 候选未确认 → 不写 | `memdir` 无新 `topics/*`，无新 `MEMORY.md` 行 |
| 2 | 确认 + 过 `write_policy` → 落库 | `MEMORY.md` 增 `[type] title → topics/...`；note `status='active'` |
| 3 | 内容含目录树/一次性计划 → 拒 | `write_policy.refuse_reason` 非 None；状态 `dropped`；journal 记 reason；topics 无新增 |
| 4 | 两子代理同候选 | content-hash 去重 → 只写一次；无重复索引行 |
| 5 | 收敛与主会话写并发 | 单写者锁 + journal 同事务 → 索引字节稳定，无撕裂（参照 `loader` 的"两次非 mutation 间字节不变" `memdir.py:227`） |
| 6 | KV 不动 | 收敛前后主 JSONL / session.md / compact_cursor 字节不变 |
| 7 | tombstone | 被 Forget 的 id 不会被收敛线复活（`governance.py:48-53`、`agent_scope` 铁律 §5.6/§5.5） |
| 8 | 幂等重试 | job 失败后重跑 → 不重复写；同 note 再跑 → idempotent（content-hash + status 检查） |
| 9 | 检索/citation | `memory_search` 返回 `path:lines|note`；命中回写 `last_used_at` |

---

## 6. 与 NightShift / 现有 L4 的关系

- **两条互补收敛线**：
  - **任务收敛线（本设计）**：子代理/任务结束，**即时、可确认、异步**沉淀"任务内新事实"。
  - **离线重塑线（NightShift）**：`nightshift.py` 周期性对 **已有 topics** 做**治理/合并/重索引**（L6 休眠），不改来源、不新增候选。
- **不重叠**：本设计只处理"**子代理新候选 → active**"；NightShift 处理"**active 集合的再治理**"。二者共用同一把 memdir 写锁（`nightshift.py:56-57`）保证互斥；本设计 P1 的 job **可挂在 NightShift 空闲期容器**里（低耦合，避免再开一套调度）。
- **本次不碰**：NightShift 的治理策略、`aging` 回收（P2 再议）。

---

## 7. 边界与"不要去"清单（对齐红线）

1. 收敛线**只在主会话确认触发**，子代理永不直接写（`agent_scope.py:91-99` 再加一道"未确认不写"）。
2. 只写 `memdir/topics` + `MEMORY.md` 索引 + `journal`；**绝不写**主 JSONL / `session.md` / `compact_cursor` / `XEYO.md`（`agent_scope.py:28`）。
3. **不带模型进写路径**：候选→note 转换、门禁、去重全是确定性纯函数（沿用 §28 §2.2「质量评判不进 store 写路径」）。
4. **无 LLM 协调者**：主会话"确认"是用户/主会话显式动作，不是模型自由发挥（防 Codex 式"自动写"污染）。
5. **不引入分布式锁**：每文件单写者 + 一把 memdir 写锁（`nightshift.py:56-57` 同款）即可（§28 §2.5.2）。

---

## 8. 验收口径（设计级）

- **自动**：子代理产生候选 → 主会话确认 → 后台收敛 → `MEMORY.md` 可读，无需手工拷贝。
- **安全**：未确认候选不写；`write_policy` 拒绝内容不写；收敛不改主 KV/session.md；失败幂等不污染。
- **收敛**：`MEMORY.md` 只做导航、只列 `active`+`indexable`；索引原子重写；tombstone 不复活。
- **对齐**：与 `10-完整记忆体系.md §5.5 写信冲突 / §3.4.7`、`§28 §2.5.2 单写者无锁` 语义一致；是 §10.4 的落地。

---

## 9. 证据引用（本设计涉及的现状接口）

- XEYO：`python/memory/agent_scope.py:27-99`、`subagent_memory.py:17-21,143-151`、`governance.py:44,56-62,88-99`、`write_policy.py:32-59`、`memdir.py:192-224,253,227`、`journal.py:53-60,143-160`、`nightshift.py:56-57`、`runtime.py:472-508`；`python/tests/test_agent_scope.py:24-31`。
- 用户设计：`docs/设计/10-完整记忆体系.md §5(1130-1216)/§3.4.7(480)/§5.5`、`docs/设计/28-多Agent协同设计.md §2.5.2(180-208)`。
- 对标：Codex `codex-rs/state/runtime/memories.rs:19,45`（异步 job）、`codex-rs/memories/write/src/workspace.rs:58`、`codex-rs/ext/memories/templates/memories/read_path.md:22-37`、`codex-rs/ext/memories/src/tools/{list,read,search}.rs`、`codex-rs/memories/read/src/citations.rs`、`codex-rs/core/src/agent/role_tests.rs:419`。
