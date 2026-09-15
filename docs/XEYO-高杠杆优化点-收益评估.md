# XEYO 高杠杆优化点评估（五轮总结 · 收益视角）

> **这份文档不回答"按什么顺序做"**（那是 `XEYO-开源优化路线-五轮总结.md` 的职责），
> **只回答一个问题**：五轮 7,680 行对比里，哪几个点既**完美适配 XEYO 已有架构肌理**、
> 又**收益巨大**。
>
> 口径：所有"已存在 / 不存在"的断言都由本轮**直接读源码复核**，带 `文件:行号`。
> 与前面任何一轮冲突时，**以本文为准**——因为本文是本轮为做收益判断而重跑的证据。

---

## §0 一句话结论

**收益量级最大的是沙箱，但最优选择不是它。**

本轮把"收益巨大"和"完美适配"拆成两个独立维度打分后发现：**沙箱同时在两个榜上都靠前，却在"适配度"上失分**——它要新建一层、会改变现有行为边界、且做完之后现有的 11 级权限链与 18 条 bash 黑名单**大概率要重写**。先做它，等于在还没铺地的地基上盖楼。

真正**两个维度同时登顶**的是另外两个点：

| 排名 | 点 | 为什么 |
|---|---|---|
| **①** | **命名事件瀑布**（第一步只做"命名 + 观测"，不要求可替换） | 收益量级高（9/10）+ 杠杆满分（5/5）+ 适配满分（5/5），综合 **30.0** |
| **②** | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 收益 8/10 + 适配满分（层已存在，只扩算子）+ 综合 **27.5** |
| ③ | 沙箱 confine + Windows restricted-token 后端 | **收益满分（10/10）**，但适配 3/5、成本 2/5 → 综合 26.5 |

**并且本轮推翻了上一份收官报告的 P0 清单**：它列的 P0-3（工具结果头尾预算 + spill 可取回）**早已完整实现**，P1-5 里的"工具配对平衡"**也早已实现**。剔除假差距后，P0 只剩一项。

---

## §1 先更正：三项被误判为"待做"的其实早已存在

这是本文最重要的部分之一。**如果按上一份文档开工，第一件事就是重写已经写好的代码。**

### 更正 A：P0-3「工具结果头尾预算 + spill 到文件可取回」—— 已完整实现

上一份文档 `:167` 把它列为 P0，落点写的是 `tools/bash_tool/truncate.py`。实测这条链**有三层，且每层都已就位**：

| 层 | 实现 | 常量 / 行为 |
|---|---|---|
| ① **语义压缩**（XEYO 独有） | `tools/bash_tool/cmd_compact.py`（12 KB，**6 个族压缩器**） | `_compact_pytest` / `_compact_test_runner` / `_compact_tsc` / `_compact_lint` / `_compact_git` / `_compact_build`；门槛 `_MIN_CHARS = 4_000`，`_MAX_GROUPED_FILES = 40`。在硬截断**之前**压掉 test/build/git 噪声，失败与 traceback 保留 |
| ② **硬截断 + 原始落盘** | `tools/bash_tool/truncate.py`（96 行） | `DEFAULT_LIMIT = 30_000`、`HEAD_CHARS = 20_000`、`TAIL_CHARS = 8_000`；**中段错误行抢救** `MAX_ERROR_EXCERPT_LINES = 8` / `MAX_ERROR_EXCERPT_CHARS = 800`，`_ERR_LINE_RE` 匹配 22 类错误标记；全文落 `persist_dir`，模板尾部给 `[output truncated, full at {path} ({n} chars)]` |
| ③ **registry 级 spill seam** | `tools/tool_registry.py:179-234` `_apply_output_budget` | `DEFAULT_OUTPUT_BUDGET = 16_000`、`PREVIEW_HEAD = 6_000`、`PREVIEW_TAIL = 2_000`；走 `tools/spill.py::save_text` 落盘 + 审计事件 `tool.spill`（记 `path`/`original_chars`/`spill_bytes`）+ 元数据 `spilled/spill_path/truncation="output_budget"` |

`tools/spill.py`（117 行）本身也已超出"最小可用"：`O_EXCL` 独占创建绝不覆盖、POSIX `0600`、按会话命名空间 `~/.xeyo/spill/<safe_session>/`、保留期清理 `XEYO_SPILL_RETENTION_DAYS`（默认 7 天）、**spill 失败绝不抛给调用方**（"宁可超预算，不可假证据"）。

**而且"双重截断"这个坑早被显式规避**——`tools/meta.py`：

```
:111-112   # T1：Read 豁免 spill——防 read→spill→read 循环。
           output_budget=0,
:146-148   # T1：Bash 自带 raw→落盘→截断 seam（truncate_for_model），豁免
           # registry 级预算，避免双重截断/双重落盘。
           output_budget=0,
```

我在本轮一度假设"bash 的 20k/8k 承诺会被 registry 的 6k/2k 覆盖"，**这个假设是错的**——Bash 与 Read 都被 `output_budget=0` 豁免，registry 预算只作用于其余工具。这是一个**已完成的设计决策**，不是待办。

### 更正 B：P1-5 里的「工具配对平衡」—— 已实现

上一份文档 `:169` 把"压缩事务化：括号事务 + 工具配对平衡"列为 P1，理由是"XEYO 的 C0/C1/C2 是截断不是事务"。**"配对"这一半不成立**：

```
engine/compact.py:69    def tool_pair_ranges(...)      # 识别 assistant(tool_calls)+连续 tool 的成对区间
engine/compact.py:87    def _keep_tail_rounds(...)     # KEEP_TAIL_TOOL_ROUNDS = 3
engine/compact.py:95    def keep_tail_cut(...)         # cut 点吸附到配对完整处
engine/compact.py:116   def split_at_cursor(...)
engine/compact.py:24-27 MAX_TOOL_RESULT_CHARS = 8_192  # 与 dsh pruner 的 8192 同值
                       KEEP_TAIL_MESSAGES = 6
```

`engine/compact.py` 的文件头也写明了它是**投影层压缩**，不是主链改动：

```
"""L5 摘要记忆：送模型投影（不改 MessageStore / JSONL）。
C0 截断始终做；C1 占位按 frozen_until 应用（runtime 按公式推进冻结边界），
本函数不自行决定窗口，保证两次 C1/C2 之间投影字节稳定。C2 由 runtime 处理。"""
```

**真实差距收窄为**：cut 点已配对安全，但（a）压缩**不是事务**——没有"压缩前落一条事件、可回滚"的语义；（b）XEYO 靠 **事后修补**（`_repair_unpaired_tool_calls`）兜底，dsh 靠**事前原子**。这是一条**降级后的中等项**，不是"新模块 + 配对算法"。

### 更正 C（承接前几轮）：投影层、写后缓冲、fsync 也都已存在

| 曾以为缺 | 实际 | 证据 |
|---|---|---|
| 投影层 | **已存在** | `session/surface.py`（150 行）`fold_surface_rows`；`session/hydrate.py` 组装 `messages_from_rows(resolve_transcript_rows(fold_surface_rows(rows), path))` |
| JSONL 写后缓冲 | **已存在** | `session/record_transcript.py:122 _writer_loop`、`:143 _write_batch`、`:183 flush_pending_sync`、`:194` atexit 排空 |
| fsync | **已存在** | `:156 os.fsync(f.fileno())  # 崩溃窗口不丢会话尾部(G107)`——**有事故编号** |
| 轮转 | **已存在** | `:50-65` `_max_transcript_bytes()` 默认 32 MB、保留 2 代归档 |
| 写路径互斥 | **部分存在** | `:39 _disk_lock = threading.Lock()` + `_disk_lock` 覆盖 rotate+append（`:150-156`） |

### 更正小结：P0 重新定义后只剩一项

| 上一份文档 | 本文判定 |
|---|---|
| P0-3 工具结果头尾预算 + spill | **删除**（已实现，见更正 A） |
| P0-4 JSONL 撕裂尾修复 + 跨进程租约 | **保留**（唯一真 P0，见 §5.5） |
| P1-5 的工具配对平衡部分 | **删除**（已实现，见更正 B）；只留"事务化" |
| P1-3 投影层泛化 | **保留但降级为"扩算子"**（层已存在） |
| P1-6 命名事件瀑布 | **保留，且本轮升级为第 ① 优先** |
| P2-1 沙箱 | **保留，收益量级第一但顺序不动** |

---

## §2 剔除假差距后的真实候选池

**入选条件**：本轮源码复核确认为真差距，且在五轮报告里出现过。

| # | 候选 | 类型 | 现状证据（查过才有资格入池） | XEYO 现有对应物 |
|---|---|---|---|---|
| 1 | **沙箱 confine + Windows restricted-token** | 能力·信任 | 全仓排除 `.venv` 后 `landlock\|seatbelt\|bwrap\|sandbox-exec` **零命中**；`tools/bash_tool/win_job.py` 是**资源限额**（Job Object）非隔离 | 权限链 11 级 + `bash_policy.py` 18 条黑名单（**文本分析**） |
| 2 | **命名事件瀑布** | 结构·杠杆 | `engine/query_loop.py`（2,000 行）内联点：`evaluate_policy` `:175`、`repeat_guard.observe` `:1069`、`budget.prepare_next_turn` `:800`、`maybe_force_compact_on_pressure` `:850`、`run_pre_llm_inject` 包装 `:645`；`extension/hooks.py` 只在工具门禁/会话边界接缝被调用 | `audit.record`（只记不派发） |
| 3 | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 结构·能力 | `session/surface.py:36-38` 只有 `_OP_REWIND` / `_OP_REWIND_UNDO` 两个**单用途** op；无来源追踪字段 | `fold_surface_rows` + `active_markers` + `has_undo_marker` |
| 4 | **C2 压缩事务化（可归因 + 可回滚）** | 能力·成本 | `engine/compact.py` 是投影截断；`_repair_unpaired_tool_calls` 为事后修补 | `tool_pair_ranges` / `frozen_until` / `_C2_LLM_PREFETCH_MIN_MESSAGES = 24` |
| 5 | **hooks 事件面扩展** | 生态·扩展 | `extension/hooks.py:24` `EVENTS = ("PreToolUse","PostToolUse","PermissionRequest","SessionStart","SessionEnd")` —— **5 个**；docstring 自陈"`Subagent*` / `UserPromptSubmit` / `PrePostCompact` **预留**" | hooks 执行器已完整（子进程 / 三分结果 / PermissionRequest fail-closed / stdout 经 reconcile 进 T_now） |
| 6 | **JSONL 撕裂尾修复 + 跨进程租约** | 可靠性 | `:249-250 except json.JSONDecodeError: continue`（静默跳过、不可观测）；`:39 _disk_lock = threading.Lock()`（**进程内**） | 写后缓冲 + fsync + 32 MB 轮转 + 按 id 去重 |
| 7 | **会话事件自查询工具** | 能力·可观测 | 工具表 `tools/meta.py` 无 session-query 类；`tools/journal_query_tool` 是**多代理工作区变更**查询（`memory.journal`），非会话事件查询 | `rewind`/`journal` 读侧 API 已存在，但未做成工具 |
| 8 | **覆盖率 ratchet** | 质量 | 无覆盖率门；`scripts/check.ps1` 为 pytest + typecheck + vitest | pytest 307 文件 / vitest 102 文件 |
| 9 | **时间触发型定时任务** | 能力 | `engine/scheduler.py`（1,110 行）是**任务 DAG**（toposort/环打破/scope 冲突），被 `subagent_runner.py` 等 5 处消费——**不是**时间触发 | 后台 bash job（24 h 超时） |
| 10 | 前端插槽化 | 结构 | `gui/src` **134 个 `.tsx` 单体**；`grep registerSlot\|slots\|pluginRegistry` **零命中** | 无 |

**同时明确剔除（不入池，理由见 §7）**：跨会话记忆召回重开、Typert RPC、Cordis 式 255 包重组、per-file 100% 覆盖率门、双 SDK / ACP、i18n、E2B / PTY / LSP、workflow + ralph。

---

## §3 评分口径：为什么要把"收益"和"适配"拆开

"完美优化 XEYO"这句话里其实塞了**两个独立诉求**，混在一起必然选错：

- **"收益巨大"** = 做完之后产品能力强多少 → 这是**收益**维度
- **"最适合/完美"** = 是否顺着 XEYO 已有的架构肌理走、做完不欠新债 → 这是**适配**维度

一个点的收益可以巨大，但如果它要新建一层、改变现有行为边界、让已有的十几处机制作废，那它就**不完美**。反之亦然。

### 五维打分（1–5，两个反向维度已翻正）

| 维度 | 含义 | 高分的表现 |
|---|---|---|
| **B** 收益量级 | 直接影响多少产品能力 | 5 = 改变产品边界；1 = 只影响边角场景 |
| **L** 杠杆 | 是否让**其他优化**变便宜 | 5 = 成为后续一切的扩展点；1 = 孤立 |
| **F** 适配度 | 是否顺着已有肌理走 | 5 = 扩已有机制 / 有明文约定的落点；1 = 需新建架构层 |
| **C** 成本（翻正） | 工程量反向 | 5 = S 级（单文件小改）；1 = 大型新建 |
| **R** 风险（翻正） | 行为变化/回归风险反向 | 5 = 关掉逐字节一致；1 = 改变现有行为边界 |

**综合 = (B + L) × 2 + F × 1.5 + (C + R) / 2**（满分 37.5）

- 前两项 `(B+L)×2` 是"**收益巨大**"的量化：收益量级 + 杠杆，权重最高。
- 中间 `F×1.5` 是"**完美适配**"的量化。
- 末项 `(C+R)/2` 是**可行性**，权重最低——因为这份文档的立场是**先看收益与适配，再看好不好做**；一个点哪怕便宜，收益小就不该进榜。

### "完美适配"的三条硬判据

一个点要拿到 F ≥ 4，必须至少满足两条：

1. **有明文约定的落点**——`AGENTS.md` 的硬规矩（反巨石 / 新功能先旁路）已经为它指定了位置；
2. **扩已有机制，而非新建层**——代码里已有承担同一语义的结构；
3. **可旁路验证**——能做成 `sidecar/` 形态或 feature flag，关掉即逐字节恢复。

> **`sidecar/` 是 XEYO 最被低估的资产。** `sidecar/policy.py`（58 行）+ `sidecar/upgrade.py`（75 行）构成一套完整的"侧挂→升格"基建：`XEYO_SIDEMOD_PROMOTE`（默认 1）一键开合，已挂 6 个挂钩型模块（`memory.memindex_sig_shadow` / `tools.fileio.content_index_cache_shadow` / `memory.eval_cold_memory_shadow` / `tools.spill_shadow` / `prompt.transcript_pointer_shadow` / `memory.rerank_preference_shadow`）+ 4 个纯函数型（pollution / reporting / strict_env / blind_audit）。**`AGENTS.md` 硬规矩第 4 条「新功能先以旁路形态上线验证收益」在这里被代码化了**——任何新优化都能以此形态进场，且 `upgrade.py` 的 fail-open 语义（单模块失败不挡引擎构建）保证零风险。

---

## §4 全候选评分表

| # | 点 | B | L | F | C | R | **综合** | 榜位 |
|---|---|---|---|---|---|---|---|---|
| 2 | **命名事件瀑布**（第一步只命名+观测） | 4 | **5** | **5** | 4 | **5** | **30.0** | ① 最优选择 |
| 3 | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 4 | 4 | **5** | 4 | 4 | **27.5** | ② |
| 1 | **沙箱 confine + Windows restricted-token 后端** | **5** | **5** | 3 | 2 | 2 | **26.5** | ③ 收益第一 |
| 5 | **hooks 事件面扩展**（5 → 9 事件） | 3 | 4 | **5** | 4 | 4 | **25.5** | ④ |
| 4 | **C2 压缩事务化**（可归因 + 可回滚） | 4 | 3 | 4 | 3 | 3 | **23.0** | ⑤ |
| 6 | JSONL 撕裂尾修复 + 跨进程租约 | 2 | 2 | **5** | **5** | **5** | **20.5** | ⑥ 真 P0 |
| 7 | 会话事件自查询工具 | 3 | 2 | 4 | 4 | 4 | **20.0** | ⑦ |
| 8 | 覆盖率 ratchet（不做 per-file 100%） | 2 | 3 | 4 | 4 | 4 | **20.0** | ⑦ |
| 9 | 时间触发型定时任务 | 3 | 2 | 3 | 3 | 4 | **18.0** | ⑨ |
| 10 | 前端插槽化 | 3 | 3 | 2 | 2 | 2 | **17.0** | 不入榜 |

### 拆两个榜看，结论更有意思

**「收益量级榜」（B + L，满分 10）**：

```
沙箱            ██████████ 10   ← 收益最大
命名事件瀑布     █████████   9
投影层算子       ████████    8
hooks 扩展       ███████     7
C2 压缩事务      ███████     7
```

**「完美适配榜」（F，满分 5）**：

```
命名事件瀑布     █████ 5   ← 最完美
投影层算子       █████ 5
撕裂尾+租约      █████ 5
hooks 扩展       █████ 5
沙箱            ███   3   ← 失分点
```

**两个榜的交集就是本文推荐的前两名。** 沙箱在两个榜上都靠前，但适配度掉到 3——它要在 `tools/bash_tool/runner.py`（`:160`、`:345` 两个 spawn 点）**新建一层 `confine()` 抽象**，且 confine 生效后"原本能跑的命令会失败"，是**唯一改变现有行为边界**的改动。

### 关于"杠杆"这一维的具体解释（它决定了排名）

杠杆不是抽象概念，本轮把它落成可核验的提问：**做完这个点之后，原本需要"改引擎"的事，能不能变成"挂插件"？**

| 点 | 做完之后，什么变便宜了 |
|---|---|
| 命名事件瀑布 | 后续**每个** guard / 拦截 / 观测都从"改 `query_loop.py`"变成"挂一个命名事件"。今天 `repeat_guard`、`budget`、`compact`、`evaluate_policy` 都是**内联调用点**，加第五个就得再改一次巨石 |
| 投影层算子 | C2 压缩事务化、任意"改写过去"的能力、来源追踪审计——全部统一到一条 fold 路径 |
| hooks 事件面扩展 | 外部插件（用户侧）能拦到 `Stop` / `SubagentStop` / `UserPromptSubmit` / `PreCompact`——**这是产品生态面，dsh 已有而 XEYO 缺** |
| 沙箱 | 权限链可从 11 级收粗、bash 黑名单可从 18 条收窄、`XEYO_BASH_UNSAFE_ALLOW` 这条"没有 jail 就不给全权"的补丁可以退役。**但它让这些变便宜的前提是权限链已经在别处被命名事件/审计铺好** |

---

## §5 收益巨大的点，逐个论证

### §5.1 ① 命名事件瀑布 —— 综合最优（30.0）

#### 它现在长什么样（本轮实测的内联点全集）

`engine/query_loop.py` 是 2,000 行巨石。引擎级的可插拔语义点**全部是内联函数调用**，没有一个是命名事件：

| 语义点 | 行号 | 形态 |
|---|---|---|
| 权限判定 | `:175` `decision = evaluate_policy(name, raw_input, cwd=registry.cwd, tool=tool)` | 直接函数调用（在 `_eligible_for_early` 内） |
| 重复调用守卫 | `:1069` `guard_action = repeat_guard.observe(tu.name, tu.input)` | 直接方法调用，返回值 `:1072 _ = guard_action` **被丢弃** |
| 预算推进 | `:800` `if not budget.prepare_next_turn():` | 直接方法调用 |
| 强制压缩 | `:850` `if maybe_force_compact_on_pressure(...)` | 直接函数调用 |
| 上下文注入 | `:645-686` 薄封装委托 `prompt.pre_llm_inject.run_pre_llm_inject` | 包装函数 |
| 投机任务取消 | `:179` `_cancel_early_tasks`，调用点 `:1164` `:1364` `:1416` `:1440` | 直接函数调用 ×4 |
| 投机资格判定 | `:93` `_EARLY_BLOCKLIST`、`:112` `early_readonly_tools_enabled()`、`:155` `_eligible_for_early` | 模块级私有 |

**对比：XEYO 只有一处在"接缝"上**——`extension/hooks.py` 自陈"本模块不自含调度/主循环；只在工具门禁 / 会话边界的**接缝**被调用（AGENTS.md 反巨石：新逻辑进新模块，巨石仅留调点）"。**接缝这个概念已经存在，只是只被用在了工具门禁一处。**

#### 为什么收益巨大（B=4、L=5）

杠杆满分不是修辞。今天要在"模型请求发出前"插一个新机制，唯一路径是**再改一次 `query_loop.py`**；有了命名事件，路径变成**挂一个监听器**。而 `AGENTS.md` 硬规矩第 7 条「反巨石」已经把"新逻辑一律进新模块，既有巨石只留接线点"写成机器执法级约束——**这个点在偿还一笔已经存在的技术债**。

同时它带来一个立竿见影的真实收益：**可观测**。今天回答"这一回合引擎做了什么决策"只能读代码；命名事件 + 现有 `audit.record` 直接给出时序。注意 XEYO 已经有 `tool_call.begin` 参数摘要（`query_loop.py:100-105`，压成单行 JSON 截 200 字符）这类为审计做的准备，说明审计通道是现成的。

#### 为什么适配完美（F=5）

三条硬判据全中：

1. **有明文约定的落点**——`AGENTS.md` 第 7 条就是为它写的；
2. **扩已有机制**——`extension/hooks.py` 已经定义了"接缝 + 命名事件 + 三分结果 + 超时 + fail-policy"这套完整语义，只是场景限制在工具边界；引擎级命名事件是同一套语义的推广，不是新发明；
3. **可旁路验证**——`sidecar/policy.py::side_enabled()` 现成可用。

#### 关键：第一步只做"命名 + 观测"

这是它风险 R=5 的原因。**第一步不改任何语义**：

```
新增 engine/events.py（新模块，符合反巨石）：
  - 定义命名事件常量：turn/start · turn/end · llm/before-request · llm/after-response
    · tool/pre-execute · tool/post-execute · compact/before · compact/after
    · budget/warn · guard/triggered · permission/decided
  - emit(name, **fields) → 写 audit（复用 default_audit_log()）+ 可选 telemetry
query_loop.py 只做一件事：在上述 7 个内联点旁边各加一行 emit(...)
```

**"可替换"留到第二步，且不承诺。** 这样做的收益是：即使第二步永不做，第一步也已经拿到观测与审计；而第二步（允许 sidecar 挂到事件上）的成本因为第一步的命名而大幅下降。

#### 判据（构造性，不依赖任何外部判分）

- **关掉后逐字节一致**：`XEYO_SIDEMOD_PROMOTE=0`（或专用 flag）下，模型可见请求体与审计输出与改动前**逐字节相同**；
- **事件完整**：跑一个含工具调用的回合，审计里出现 `turn/start → llm/before-request → tool/pre-execute → tool/post-execute → turn/end` 的**有序**序列；
- **零回归**：`python/.venv/Scripts/python.exe -m pytest python -m "not live"` 全绿 + `npx tsc --noEmit`。

#### 风险

R=5——**前提是坚持"第一步只命名"**。一旦在第一步就引入"事件可改写行为"，风险立刻从 5 掉到 3（因为改的是 2,000 行巨石里的执行顺序）。**这条边界必须在实施时写死。**

---

### §5.2 ② 投影层通用 `replace` 算子 + `sourceEventSeqs` —— 适配最完美（27.5）

#### 它现在长什么样

`session/surface.py` 已经完整实现了"append-only 是唯一真相，模型可见面 = fold"这套语义，文件头写得比很多设计文档还清楚：

```
surface/generation 模型：
- append-only JSONL 是唯一真相，回溯不再重写文件，而是追加一条 surface_op marker 行，
  把「当时可见面」从 shadow_from 起的区间影子化（shadow）——原始行永不改写、永不移动。
- 模型可见历史 = 对合并日志（含轮转归档 .old2→.old1→当前）做一次 fold_surface_rows
```

**但它只有两个单用途算子**（`:36-38`）：

```python
_OP_REWIND = "rewind"           # 影子化 shadow_from 起至可见面末尾
_OP_REWIND_UNDO = "rewind_undo" # 恢复该 rewind_id 影子化的全部行
```

#### 为什么这是差距（而不是"设计如此"）

dsh 对应实现的算子集是 `append | {op: 'replace'}`——**一个通用替换算子**，外加每条事件带 `sourceEventSeqs` 来源追踪（第三/四轮实测）。差别不是"多一个 op"，而是：

| | XEYO | dsh |
|---|---|---|
| 算子语义 | `rewind` = 影子化**到末尾** | `replace` = 替换**任意区间** |
| 能表达的 | "退回某一轮" | "把这一段换成那一段" |
| 来源追踪 | 无 | `sourceEventSeqs` 指向被替换的原事件 |
| 可承载 | 回溯 | 回溯 **+** 压缩结果 **+** 注入覆盖 **+** 审计溯源 |

**`rewind` 是 `replace` 的一个特例**（`to = null` 且区间到尾）。XEYO 把特例做成了唯一实现，于是**压缩、覆盖、注入这三类需求都无法用同一条路径表达**——这是多个机制难以统一的**根因**（第五轮 Part C 的 C-3 已指出同一现象）。

#### 为什么适配完美（F=5）

这是全表**成本最低的"结构性"改动**：

1. **层已存在**（150 行），`fold_surface_rows` 的 fold 循环结构（`:77-115`）天然支持追加分支：
   ```
   for row in rows:
       if is_surface_marker(row):
           op = str(row.get("op") or "")
           → 加一个 elif op == _OP_REPLACE: 分支，用 {from_id, to_id} 替换区间
   ```
2. **兼容性契约已经写好**——文件头已声明"旧 transcript 无 marker → fold 恒等"，新 op 对旧数据天然无影响；
3. **`active_markers` / `has_undo_marker` 两个辅助函数（`:117-150`）只需各加一个分支**，v2 物理重写路径的"回填 active marker 永远方向安全"这条既有论证依然成立。

#### 收益（B=4、L=4）

- **直接收益**：人类侧永远能看到完整 append-origin 历史，模型侧看到折叠后的可见面——**审计与上下文彻底解耦**，而这正是 XEYO 已有架构的**既定分工**（文件头原文："与「模型看 surface、人看 append-origin」的分工一致"）；
- **杠杆收益**：§5.6 的 C2 压缩事务化**直接依赖它**（压缩结果就是一次 `replace`）；`sourceEventSeqs` 让"这条上下文是哪来的"可回答——这是可审计性的地基。

#### 判据

- **G1 旧数据不变**：对不带 `replace` marker 的既有 transcript，`fold_surface_rows` 输出与改动前**逐元素相同**；
- **G2 新算子幂等**：同一 `replace` marker 重复 fold 结果稳定；
- **G3 可逆**：`replace` 后追加 undo marker，可见面精确回到替换前（用 20 行 → 替换为 3 行 → undo → 恢复 20 行 的构造用例）；
- **G4 来源可查**：`sourceEventSeqs` 指向的原事件 id 在合并日志中确实存在。

---

### §5.3 ③ 沙箱 confine + Windows restricted-token —— 收益量级第一（26.5）

#### 为什么收益巨大（B=5、L=5）

这是**唯一一个改变产品能力边界**的点。今天的 XEYO 在 Windows 上：

- 用 `tools/bash_tool/win_job.py` 做 **Job Object 资源限额**——那是"别把机器跑死"，**不是隔离**；
- 全仓（排除 `.venv`）搜 `landlock|seatbelt|bwrap|sandbox-exec` **零命中**；
- 于是安全只能靠**文本分析**：`permissions/policy.py` 的 11 级分支 + `permissions/bash_policy.py` 的 `_DENY_RULES` + 193 行 bash 语义分析反推写目标；
- 并且必须给自己上一道"没有 jail 就不给全权"的补丁：`bash_mode=="allow"` 时若无 `XEYO_BASH_UNSAFE_ALLOW=1` 且非 `full` profile → **自动降回 `default`**。

**沙箱把这些全部重构**：可信边界从"我们正则匹配到了危险命令"换成"内核不允许写"。直接后果：

1. **误拒变少**——现在被 18 条黑名单挡掉的合法命令可以放行；
2. **模型少绕路**——今天模型撞上 DENY 后往往换写法重试（白烧 token）；
3. **`bash_mode=allow` 可以真正安全**，不用再靠环境变量兜底；
4. **权限链有资格收粗**——11 级分支里相当一部分是为"补隔离的缺失"而存在的。

#### 为什么适配度只有 3

三条硬判据它只中一条半：

| 判据 | 判定 |
|---|---|
| 有明文约定的落点 | ❌ 无。要在 `tools/bash_tool/runner.py`（`:160`、`:345` 两个 spawn 点）**新建 `confine()` 抽象层** |
| 扩已有机制 | ⚠️ 半中。`win_job.py` 是同一个执行层，但语义不同（资源限额 vs 隔离），不能复用 |
| 可旁路验证 | ⚠️ 半中。可旁路，但**关掉它 ≠ 逐字节一致**——confine 生效后"原本能跑的命令会失败"，这是行为变化 |

#### 但它有一个被低估的适配优势：dsh 有 Windows 后端可直接对照

前几轮曾把沙箱判为"XEYO 是 Windows 产品所以用不了"——**这个判断是错的**（第五轮已更正）。dsh 有 `packages/sandbox/sandbox-windows-acl`，且有 43 行设计决策记录。它的路线：

- `CreateRestrictedToken`，标志 `WRITE_RESTRICTED` + `DISABLE_MAX_PRIVILEGE` + `LUA_TOKEN`；
- **核心洞察：只交写访问，读沿用调用者权限 → 不需要改宿主 DACL**（AppContainer / restricted-user 方案需要大改 DACL，因此被否决）；
- per-workspace SID = `sha256(规范路径)` → `S-1-4-x-y`；per-session 随机 temp + **独立 SID**（所以 fork 不能写兄弟的 temp）；
- probe 真跑一次；**fail-closed**；自发标 `enforcement:'partial'` 并用测试钉死已知缺口（Everyone 授权对象、硬链接别名）。

对一个 **Windows 优先**的 XEYO，这是**可直接对照移植**的设计，且它自带一份"为什么这么做"的论证。

#### 为什么它排第三而不是第一

三个理由，缺一不可：

1. **它是唯一改变现有行为边界的改动**（做完后原本能跑的命令会失败）；
2. **它是唯一无法旁路验证的**——不能靠"关掉后逐字节一致"证明安全，只能靠"read-only 下写失败、读成功"这类构造性用例；
3. **它会连带让现有的权限链与黑名单部分作废**——先做它，那 11 级链 + 18 条规则可能白改。

**它必须等 §5.1（命名事件）铺好"拦截点在哪观测"、§5.4（hooks 事件面）铺好"失败时怎么优雅降级"之后再动。**

#### 判据

- **read-only 下写失败、读成功**（构造性，不依赖外部判分）；
- **越界写被拒**：写工作区外路径 → 拒绝，且拒绝原因来自 OS 层而非正则；
- **fail-closed**：沙箱不可用时不静默降级为无沙箱（今天 `PLATFORM_CHAINS.win32` 曾为空 → 降级 `danger-full-access`，那是一次已修复的事故，回归测试必须覆盖）；
- **`enforcement` 自陈诚实**：已知缺口（Everyone、硬链接别名）必须有测试钉死，不允许写在注释里。

#### 红线

沙箱**不得按执行通道分叉**。`AGENTS.md` 明文禁止"容器路由就跳过"这类评测条件分支——那属于应试修改。

---

### §5.4 ④ hooks 事件面扩展 —— 兑现自己预留的欠条（25.5）

#### 它现在长什么样

`extension/hooks.py:24`：

```python
EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "SessionEnd")
```

文件头 docstring 紧接着写着：**"事件（`Subagent*` / `UserPromptSubmit` / `PrePostCompact` 预留）"**。

**"预留"两个字就是本文给它 F=5 的理由**——这不是"照 dsh 抄"，这是**兑现 XEYO 自己开的欠条**。

#### 两端事件对照（本轮实测）

| 事件 | XEYO | dsh（Claude Code 桥） |
|---|---|---|
| `PreToolUse` | ✅ | ✅ |
| `PostToolUse` | ✅ | ✅ |
| `SessionStart` | ✅ | ✅ |
| `SessionEnd` | ✅ | — |
| `PermissionRequest` | ✅（**fail-closed DENY**） | — |
| `UserPromptSubmit` | ⏳ 预留 | ✅ |
| `Stop` | — | ✅ |
| `SubagentStop` | ⏳ 预留（`Subagent*`） | ✅ |
| `PreCompact` / `PostCompact` | ⏳ 预留 | — |

**两端各有所长**：XEYO 独有 `PermissionRequest`（且做成了 fail-closed）与 `SessionEnd`；dsh 独有 `Stop` / `SubagentStop` / `UserPromptSubmit`。

#### 为什么收益巨大（B=3、L=4）

这不是内部机制，是**产品生态面**。hooks 是用户与第三方插件接入 XEYO 生命周期的**唯一外部通道**：

- `UserPromptSubmit` 让插件能在用户提交时注入/拦截；
- `Stop` / `SubagentStop` 让插件能感知"回合结束"（今天做不到——这是最常见的告警/通知挂点）；
- `PreCompact` / `PostCompact` 让插件能在压缩前后介入（长会话治理的关键挂点）。

而且执行器**已经完整**：子进程执行、超时 `_DEFAULT_TIMEOUT_S = 600.0`、三分结果（`Success` / `FailedContinue` / `FailedAbort`）、`fail_policy` 可配、环境剥离仓库级 `GIT_*`、注入 `XEYO_HOOK_CONTEXT`、`command` 相对插件根且 manifest 已校验禁越界、stdout 经 `extension.reconcile.publish_reconcile_block` 进 T_now 管线（事件类静默即失、绝不门控）。**加事件几乎只是扩 `EVENTS` 元组 + 补发射点。**

#### 一个必须注意的设计细节（两端一致，值得保留）

`PermissionRequest` 任一非 `Success` → **fail-closed DENY**（短路工具调用，绝不静默放行）。这条不能因为扩展事件面而放松。

#### 判据

- **每个新事件都有真实发射点**（不能只有常量没有 emit——这会变成下一个"写了无消费方"）；
- **关掉后零执行、零注入**（docstring 已承诺"逐位 = 停产"，回归测试守住）；
- **`fail_policy=abort` 与超时都归入 `FailedAbort`** 的行为不变。

#### 风险

R=4。唯一的坑是：新事件如果**在错误的位置**发射（例如 `Stop` 在真正停止前发），会让插件做出错误判断。发射点必须与 §5.1 的命名事件**一起定义**，不要分两次做。

---

### §5.5 ⑥ JSONL 撕裂尾修复 + 跨进程租约 —— 两个真 P0（20.5）

#### 它现在长什么样（两处，都已实测）

**撕裂尾**：`session/record_transcript.py:247-250` 读侧

```python
try:
    obj = json.loads(line)
except json.JSONDecodeError:
    continue
```

崩溃导致半行 JSON 时，**静默跳过**。方向是安全的（不崩），但**不可观测**——用户永远不知道自己少了哪条，引擎也不会留下任何记录。

**跨进程**：`session/record_transcript.py:39`

```python
_disk_lock = threading.Lock()
```

**纯进程内锁**。写侧已有的保护是完整的（`_writer_loop` 后台线程 `:122`、批量 `_write_batch` `:143`、`os.fsync` `:156` 带事故编号 G107、32 MB 轮转 `:50-65`、按 id 去重 `:251-253`、atexit 排空 `:194`），**唯独没有跨进程互斥**。

#### 为什么它是"真 P0"（C=5、R=5、F=5）

这是全表**唯一一个三项满分**的点：

| 维度 | 理由 |
|---|---|
| 成本 5 | 两处都是 S 级。撕裂尾 = 把坏行**旁置到 `<name>.jsonl.torn`** 而不是丢弃 + 审计一条可见记录；跨进程 = 一个租约文件（PID + 心跳 + 过期）包住 `_disk_lock` 覆盖的 `:150-156` 临界区 |
| 风险 5 | **关掉后逐字节一致**。撕裂尾修复只改"坏行去哪"；租约只在多进程竞争时生效，单进程路径不变 |
| 适配 5 | 完全顺着已有实现：`_disk_lock` 的位置已经标好了临界区边界；`_maybe_rotate` 已经在同一临界区内（`:150-156`），租约不需要新临界区 |

#### 为什么收益只是"中"（B=2、L=2）

诚实说：**触发频率低**。撕裂尾需要恰好崩溃在半行写入；跨进程需要同一会话被两个进程同时写。所以它**不是"收益巨大"**——它进榜的原因是**"性价比最高"**：几乎零成本、零风险、修掉一类"静默数据损坏 + 不可观测"的隐患。

这与上一份收官文档的判断一致（它在 P0 里也是性价比最高的一条），**本文维持**。

#### 判据

- **撕裂尾**：往 transcript 注入半行 JSON（构造），读侧不抛错、坏行出现在旁置文件、审计里有记录；
- **租约**：两个进程同时 append（构造），无交错损坏；租约过期后自动可获取；
- **单进程零变化**：单进程路径下，写出的字节与改动前**完全相同**。

---

### §5.6 ⑤ C2 压缩事务化 —— 依赖 ②，收益实在（23.0）

#### 它现在长什么样

`engine/compact.py` 是**投影层截断**（文件头："送模型投影（不改 MessageStore / JSONL）"）。它做对了很多事：`tool_pair_ranges`（`:69`）保证 cut 点落在配对完整的边界上、`KEEP_TAIL_TOOL_ROUNDS = 3`、`MAX_TOOL_RESULT_CHARS = 8_192`（与 dsh pruner 同值）、`frozen_until` 保证"两次 C1/C2 之间投影字节稳定"。

**剩下的真差距是"事务性"**：

1. **不可回滚**——压缩结果一旦进入投影就是既成事实；dsh 的压缩产生一条**会话事件 + checkpoint**，可以指回"压缩前的状态"；
2. **不可归因**——dsh 的记录纪律（XEYO 自己在 `usage/ledger.py:66-76` 引用过）："压缩走模型的调用必须可归因"。XEYO 有 `_C2_LLM_PREFETCH_MIN_MESSAGES = 24` 的旁路门槛与 `c2_gate()`，但压缩**本身**没有落一条可追溯的事件；
3. **靠事后修补**——`_repair_unpaired_tool_calls` 在 submit 入口做一次性修补，而不是让压缩**事前**不产生孤儿。

#### 为什么依赖 ②

**压缩结果的最自然表达就是一次 `replace`**：把 `[msg_5 … msg_120]` 换成一条摘要事件。所以 §5.2 的通用算子是它的前置。**先做 ②，④（=本文 §5.6）从"新建压缩事务模块"降级为"用已有算子表达压缩结果 + 落一条事件"。**

#### 判据

- **压缩前落一条事件、压缩后落一条事件，两条可配对**（同一 `compact_id`）；
- **压缩前后工具配对平衡**（构造：让 cut 点落在 `tool_use`/`tool_result` 中间，断言投影侧无孤儿）；
- **可归因**：C2 走的那次模型调用在账本里能查到，且标注为"压缩归因"。

#### 风险

R=3。压缩直接改变模型可见历史长度，做错会影响长会话行为。**必须有用例先钉住"压缩后模型仍能看到最近 3 轮工具配对"**。

---

## §6 组合：为什么这几个点的收益是**乘法**而不是加法

单看每个点，收益是线性的；但**这四个点之间存在真实的依赖与放大关系**，这才是"完美优化"的完整图景。

```
        ┌──────────────────────────────────────────────┐
        │ ① 命名事件瀑布（只命名 + 观测）              │
        │    提供：拦截点在哪 · 引擎做了什么可观测      │  ← 杠杆核心
        └───────────────┬──────────────────────────────┘
                        │ 让下面两件事从"改巨石"变成"挂监听"
          ┌─────────────┴─────────────┐
          ▼                           ▼
┌──────────────────────┐   ┌──────────────────────────┐
│ ④ hooks 事件面扩展    │   │ ⑤ C2 压缩事务化          │
│  产品生态面可拦截      │   │  压缩可归因 + 可回滚      │
└──────────┬───────────┘   └──────────┬───────────────┘
           │  铺好"失败时怎么优雅降级"  │  依赖通用算子
           ▼                          ▼
        ┌──────────────────────────────────────────────┐
        │ ③ 沙箱 confine + Windows restricted-token    │
        │    唯一改变行为边界 · 唯一无法旁路验证        │
        └──────────────────────────────────────────────┘

        ┌──────────────────────────────────────────────┐
        │ ② 投影层通用 replace 算子 + sourceEventSeqs   │
        │    提供：统一的"改写过去"通道 → ⑤ 的前置      │
        └──────────────────────────────────────────────┘

        （⑥ 撕裂尾 + 租约：独立，任何时候都能做，但不影响其他点）
```

### 三组真实的依赖关系

**依赖 A：① → ⑤ 与 ④。** 压缩事务化要在"压缩前"发射一条事件，hooks 要挂 `PreCompact`——**没有命名事件，这两件事都得再改一次 `query_loop.py`**。

**依赖 B：② → ⑤。** 压缩结果的表达需要通用 `replace`；否则只能再造一个 `_OP_COMPACT` 单用途 op，**复制 `rewind` 的老路**（单用途算子堆叠 = 今天多个机制无法统一的根因）。

**依赖 C：① 与 ④ → ③。** 沙箱是唯一改变行为边界的改动。它需要一个"失败时优雅降级"的通道（否则 confine 拒绝命令后模型无从得知该换路），以及一个"拦截点在哪可观测"的能力（否则无法调试为什么某条命令被拒）。**这两条正是 ① 与 ④ 提供的。**

### 反过来的乘法：③ 一旦落地，会**让已有的复杂机制变简单**

这是 ③ 虽排第三、却值得做的最重要理由——它**减少**复杂度而非增加：

| 现有机制 | 沙箱落地后的处境 |
|---|---|
| `permissions/policy.py` 11 级判定分支 | 相当一部分是为"补隔离缺失"而存在 → 有资格收粗 |
| `permissions/bash_policy.py` 的 `_DENY_RULES` | 从"安全边界"降级为"防误操作" → 可以收窄 |
| 193 行 bash 语义分析反推写目标 | 不再需要承担安全职责 |
| `bash_mode=="allow"` 时的 `XEYO_BASH_UNSAFE_ALLOW` 兜底 | 补丁可以退役 |
| `win_job.py`（Job Object） | 保留（资源限额仍有价值），但不再被误当作隔离 |

**所以正确的顺序恰好不是"先做收益最大的"，而是"先做让最大收益变得可安全落地的"。**

### 实施顺序（按依赖，不按分数）

```
第 0 步（独立，可立刻并行）
  ⑥ 撕裂尾修复 + 跨进程租约          ← S 级、零风险、建立"构造性测试"节奏

第 1 步（三者互相成全，建议同批）
  ① 命名事件瀑布（只命名 + 观测）
  ② 投影层通用 replace 算子 + sourceEventSeqs
  ④ hooks 事件面扩展（兑现预留的 3 个事件）

第 2 步（依赖第 1 步）
  ⑤ C2 压缩事务化

第 3 步（唯一"换地基"，必须最后）
  ③ 沙箱 confine + Windows restricted-token 后端

随时可做（不阻塞）
  ⑦ 会话事件自查询工具 · ⑧ 覆盖率 ratchet · ⑨ 时间触发型定时任务
```

---

## §7 反面清单：看起来收益大，其实不是

这一节和"该做什么"同等重要——**五轮里最容易犯的错是照着 dsh 补一个 XEYO 已经有的东西，或者补一个不该补的东西。**

### 7.1 ❌ 记忆召回重开 —— 最大的"沉睡收益"陷阱

XEYO 有 `python/memory/`（48 文件）的完整记忆子系统，而实时召回是**恒关**的。乍看这是"巨大沉睡收益"——把开关打开就白赚一个 dsh 完全没有的能力。

**但这不是优化机会，是用户已经裁决过的下线项。** `engine/query_loop.py:355-363` 原文：

```python
def _memory_index_live_enabled() -> bool:
    """Memory 索引常驻注入开关：**恒关**（2026-09-09 用户裁决维持下线）。

    事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役，AGENTS「已下线」
    与此对齐。注入走 project_for_model 的 _append_memory_index 仍供脚本/评测用，
    生产投影层不推送；settings/env 残留一律忽略（同其他固化恒关项）。受控重开
    须源码级改此函数 + A1（200+ 轮 live）/ A3 过门证据。
    """
    return False
```

**"恒关" + 事故编号 + 需 A1/A3 过门证据** ——三项都在说同一件事：这不是一个待办，是一个**带门禁的已裁决决策**。`memory/memory_switches.py:48` 还专门注明"`engine/query_loop._memory_index_live_enabled` 恒 False（**不看本键**）"，即 settings/env 都穿不过去。把它列进优化清单是**不了解项目史**。

### 7.2 ❌ 照 dsh 补 spill / 补工具配对平衡

本文 §1 已详述：这两项**都已实现**，且实现质量不低于 dsh（XEYO 还多了一层 dsh 没有的**族语义压缩** `cmd_compact.py`）。照着补 = 重写已有代码。

**这条的教训值得单独记**：清单式读法（读对面有什么 → 看自己缺什么）在**否定判断**上极不可靠。写优化建议前必须先在被建议方全仓搜同义词，而不是只读被点名的那几个文件。

### 7.3 ❌ 前端插槽化（对齐 dsh 的 45 个 ui 包）

`gui/src` 是 **134 个 `.tsx` 的单体**，`registerSlot|slots|pluginRegistry` **零命中**。差距真实存在。

**但不该做**：dsh 是 5 个应用形态共享一套 UI（`packages/client` **45 个子包**），插槽化是为**多形态复用**服务的；XEYO 只有一个桌面形态。把 134 个组件拆成 45 个包，收益是"结构好看"，成本是巨大重构 + 构建复杂度上升。**这是"对面有所以我该有"的典型误判。**

### 7.4 ❌ Typert RPC / Cordis 式 255 包重组

dsh 的 `packages/typert` 类型图 RPC 是为"多语言 SDK + 多形态客户端"服务的。XEYO 的 SSE 事件流 + 生成式 manifest 已经在解决同一问题（`slash/registry.py` 35 条命令的 SSOT + 生成式 manifest 门禁）。**换协议风格不产生能力增益。**

### 7.5 ❌ per-file 100% 覆盖率门

dsh 的门是 per-file 100%。XEYO 应做的是 **ratchet**（只升不降），不是 100%。100% 会逼出大量为覆盖而写的空测试，反而使测试失去信号。**上一份收官文档已把它降级为"覆盖率 ratchet"，本文维持。**

### 7.6 ❌ 把沙箱排第一

§5.3 已论证：它是唯一改变行为边界、唯一无法旁路验证、且会让权限链部分作废的改动。**收益第一 ≠ 顺序第一。**

### 7.7 ❌ 重写 `query_loop.py`

2,000 行巨石，但 `AGENTS.md` 的处方是"**只留接线点**"，不是"重写"。§5.1 的命名事件正是这个处方的执行方式。重写会撕掉大量已踩过坑的细节（`_EARLY_BLOCKLIST`、`_cancel_early_tasks` 的 4 个取消点、投机提前执行、`rejected_early` 的 `:1560-1565` 处理）。

### 7.8 ❌ 忽略 XEYO 已经比 dsh 强的地方

对照时容易产生"对面更完整"的错觉。实测 XEYO **独有且成熟**的机制至少包括：

| XEYO 独有 | 规模/证据 | dsh 对应物 |
|---|---|---|
| **工作区回滚 rewind** | `python/rewind/` **12 文件 5,343 行**（三把锁 / 两张终态转移表 / 内容寻址 blob / 影子 git / 前置校验状态机） | **无**（dsh 只做对话侧 surface 投影） |
| **T_now 注入管线** | 20 块登记 + 硬顶 21 + `6000/2500/6000/4000` 三层预算 + 机器执法测试 | **无** |
| **投机提前执行** | `early_readonly_tools_enabled()` `:112`、`_eligible_for_early` `:155`、`_cancel_early_tasks` `:179` | **无** |
| **族语义压缩** | `cmd_compact.py` 6 个压缩器 | 通用 head/tail |
| **跨会话记忆子系统** | `python/memory/` 48 文件（召回恒关但子系统在） | **无** |
| **成本治理** | 账本 + 峰谷 + 归因 + 数据驱动定价 | **无** |
| **Tauri 原生壳** | 进程守护 + `python_exe_usable()` 真探测 + 自包含 slim venv 断言 | **无** |

**"完美优化 XEYO"的第一条纪律是不要破坏这些。** 尤其 rewind（5,343 行）——任何改动投影层或 transcript 的点，都必须先确认 rewind 的兼容性契约仍然成立（`surface.py` 文件头专门有一节 `兼容性` 讲这件事）。

---

## §8 一页结论

### 该做的（按依赖排序，不按分数排序）

| 序 | 点 | 综合分 | 为什么是它 |
|---|---|---|---|
| 0 | **JSONL 撕裂尾修复 + 跨进程租约** | 20.5 | 全表唯一三项满分：S 级成本、零风险、完美适配。不是收益最大，是**性价比最高**，且建立"构造性测试"节奏 |
| 1 | **命名事件瀑布**（只命名 + 观测） | **30.0** | 综合第一。杠杆满分——把后续一切的入口从"改 2,000 行巨石"变成"挂命名事件"，且是 `AGENTS.md` 反巨石条文的直接执行 |
| 1 | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 27.5 | 适配满分。层已存在（150 行），只扩算子；是"压缩/覆盖/注入统一走一条路"的地基 |
| 1 | **hooks 事件面扩展**（兑现预留的 3 个事件） | 25.5 | 兑现自己开的欠条，扩的是产品生态面；执行器已完整，成本近零 |
| 2 | **C2 压缩事务化** | 23.0 | 依赖上面两个，做完后从"新建模块"降级为"用已有算子表达 + 落一条事件" |
| 3 | **沙箱 confine + Windows restricted-token 后端** | 26.5 | **收益量级第一**（10/10），必须最后：唯一改变行为边界、唯一无法旁路验证，且会让权限链部分作废。dsh 有 Windows 后端可直接对照移植 |
| 随时 | 会话事件自查询工具 / 覆盖率 ratchet / 时间触发型定时任务 | 20.0 / 20.0 / 18.0 | 不阻塞、不依赖前面任何点 |

### 已经写好、只差打开的（**开了就是巨大收益**）

> 这一类不是"新增功能"，是**已实现但默认关**的开关。全部来自全仓 `XEYO_*` 穷举（238 个去重）+ `gui/src` 设置全表，逐条带 `文件:行号`。完整清单见 `docs/XEYO-未开启功能全清单-与原因.md`。
> **读法**：最后一列是**为什么不能无脑开**——八个点里有六个卡在同一类前置（**可回滚 + 可观测**）。

| 序 | 功能（已实现 · 默认关） | 开关 / 位置 | 为什么现在是关的（源码原话） | 打开后的收益 | 前置条件 |
|---|---|---|---|---|---|
| 1 | **L3 工具结果外部化** | `XEYO_TOOL_OFFLOAD`<br/>`memory/offload.py:8,23` | 旁路阶段：「统一 C0/L3 截断…**不再走 C0 截断**（8192）——避免"先截断又 offload"的双重处理」 | 超长工具结果不再全量进上下文；**引用文本与文件内容都确定性 → 同 uid 每次同引用 → KV 前缀稳定** | **无**（设计已完整，含字节稳定红线保证） |
| 2 | **C2 摘要 LLM 旁路** | `XEYO_C2_LLM_SUMMARY`<br/>`memory/runtime.py:62-85` | 「实测**吸收潜力高但输出不稳定**，默认关=确定性摘要」（`memory_switches.py:30`） | 超长会话压缩从**确定性截断**升级为模型生成的**强保真要点列表** → 压缩后不丢关键细节 | 先解决"输出不稳定"：用投影层算子约束 + 落一条事件使其**可回滚** |
| 3 | **工具结果老化** | `XEYO_TOOL_AGING`<br/>`engine/aging.py:4,43` | 「**toolout 占位的恢复机制未落地前保持关闭，避免原文不可找回**」 | 压缩后冻结区仍可按窗口紧追推进（近档富信息 / 远档折叠短存根）→ **长会话上下文预算** | 先落"恢复机制"（设计文档前置依赖①；可与 ⑬ transcript 指针组合） |
| 4 | **思考态** | GUI `thinking:'disabled'`<br/>`settingsStore.ts:266` | 产品默认省成本（**输出占成本 83%**） | 推理 / 调试类任务**质量显著提升** | 无（用户可自行开；成本上升——属"提质量"非"省成本"） |
| 5 | **rewind blob GC** | `XEYO_BLOB_GC_ENABLED`<br/>`rewind/blob_gc.py:16,430` | **三重默认安全**：`enabled=False` + `dry_run=True` + 未超预算不动手（注释记录**曾漏判 dry_run 导致真删**） | 快照目录不再无限增长（否则每个检查点的 blob 永久保留） | 先看一轮 `dry_run` 报告，确认无误删再真开 |
| 6 | **死线硬停** | `XEYO_WALL_HARD_STOP`<br/>`engine/budget.py:38-43` | 「**默认关（产品会话无墙钟武装 → 行为零变化）**」；`:163` 产品会话即使设死线也不会自动武装 | 到点**强制收尾**，防长任务失控烧钱 | 需产品路径（GUI 加"本次会话死线"入口），否则无触发源 |
| 7 | **实验功能入口** | GUI `showExperimental:false`<br/>`settingsStore.ts:304` | 「半成品移出主界面 chrome，需在设置里显式开启」 | **AgentMap 代码/架构地图**等能力变为可达 | 无（半成品质量，属"能用"非"好用"） |
| 8 | **MCP name-manifest** | `XEYO_MCP_NAME_MANIFEST`<br/>`extension/mcp_name_manifest_shadow.py:13,37` | 「**需改会话起点冻结快照**；标记「**实测 token 收益后接入**」」（`sidecar/upgrade.py:23-24` 明文红线） | 工具 schema 收缩为 `name + 一句短描述` → **省 token** | ⛔ **不可先开**：会触碰 `tools 数组会话内绝对冻结 / _schemas_cache 永不失效` 三条红线 |

**明确不在此列（看起来诱人，实则已裁决下线）**：

- ❌ `XEYO_MEMORY_INDEX_LIVE`（Memory 索引常驻注入）——**事故 `sess_mtiche8l`**（弱模型把索引条目当任务对象）+ **2026-09-09 用户裁决维持下线**，读点 `engine/query_loop.py:355-363` **恒 `False`**。重开须源码级 + A1/A2 证据门。**注意**：本工作区 settings 里写了 `"1"`，GUI 面板会**显示为"开"但功能永久关**（见下条注解）。

**本轮顺带发现的两处缺陷**（完整论证见配套文档 §8）：

1. **`XEYO_MEMORY_INDEX_LIVE` 的 GUI 开关是死的**——它**保留在注册表**（`memory/memory_switches.py:51`），于是 `get_value()` 返回 settings 里的 `"1"`、`current()` 报 `source="settings"`、`MemorySwitchesSetting.tsx:64` 渲染成"开"，用户可来回切；但运行时恒 `False`。**「显示开、实际关」**，与 `memory_switches.py:98` 想避免的「显示关、实际开」互为镜像，且**无测试覆盖**。
2. **本工作区 settings 有 4 个已删除的残留键**（`XEYO_MEMORY_RERANK_PREFERENCE` / `XEYO_MEMORY_SQLITE_INDEX` / `XEYO_CACHE_COOLDOWN_OMEGA` / `XEYO_C2_GATE`）——不生效也不报错，**且无清理入口**；同名键若未来复活会**静默继承旧值**。

### 不该做的

- ❌ 记忆召回重开（**用户已裁决恒关**，带事故编号与 A1/A3 门禁）
- ❌ 照 dsh 补 spill / 补工具配对平衡（**都已实现**）
- ❌ 前端插槽化、Typert RPC、Cordis 式 255 包重组、per-file 100% 覆盖率门
- ❌ 把沙箱排第一
- ❌ 重写 `query_loop.py`

### 两条必须守住的红线

1. **沙箱不得按执行通道分叉**——出现"容器路由就跳过"这类条件分支即属应试修改，`AGENTS.md` 明文禁止；
2. **会话自查询工具必须无条件注册**——出现 `XEYO_BENCH_MINIMAL` 分支即应试。

### 一句话

> **XEYO 的问题从来不是"缺功能"，是"缺一层"——而最好的补法不是照着对面重建那一层，是先把已有的肌理（投影层 / 接缝 / 侧挂）扩成通用形态，再用命名事件把它们串起来。收益量级最大的是沙箱，但最优的第一笔投入是"命名事件瀑布 + 投影层算子"这两个低成本、零风险、杠杆满分的点。**

---

## 附：本文的取证边界

| 项 | 说明 |
|---|---|
| 复核方式 | 本轮直接读源码（`Read` + Python 脚本切片），**不依赖任何子代理转述** |
| 已复核的实现文件 | `tools/spill.py`、`tools/spill_shadow.py`、`tools/bash_tool/truncate.py`、`tools/tool_registry.py`、`tools/meta.py`、`engine/compact.py`、`engine/query_loop.py`、`session/surface.py`、`session/record_transcript.py`、`sidecar/policy.py`、`sidecar/upgrade.py`、`extension/hooks.py`、`extension/config.py`、`permissions/*`（承接前轮） |
| dsh 侧复核 | `packages/hooks/hooks-claude-code/src/*.ts`（6 个 hook 点）、`packages/core/session/src/surface.ts`、`packages/sandbox/sandbox-windows-acl` |
| 未复核（承接前轮结论） | `rewind/*` 细节（第五轮已全文精读）、`cmd_compact.py` 内部压缩算法、`gui/src` 组件内部 |
| 与前轮的冲突处理 | **以本文为准**。本文为做收益判断重跑了关键证据，已推翻第一/三/六轮在 spill、配对平衡、投影层上的"缺失"判定 |




