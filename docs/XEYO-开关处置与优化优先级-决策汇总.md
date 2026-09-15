# XEYO 开关处置与优化优先级 · 决策汇总

> **本文是两份文档的汇总与裁决**：`XEYO-高杠杆优化点-收益评估.md`（10 个优化点，按收益/适配双榜打分）
> + `XEYO-未开启功能全清单-与原因.md`（关闭态功能，A–G 七类）。
>
> **只回答四件事**：**哪些直接开 · 哪些改后开 · 哪些不能开 · 哪些可以删**，外加**优先级**与**怎么改**。
>
> **口径**：全部结论来自源码直读（带 `文件:行号`）。本文同时记录本轮**已落地的两处缺陷修复**（§1）——
> 修复改变了前两份文档的部分结论，凡冲突**以本文为准**。
>
> **状态基准**：代码默认值 = 新装机器开箱状态；本工作区实际值 = `<repo>/.xeyo/settings.json`（本文成稿时为
> `{"memory": {"XEYO_L5": "v61"}}`，残留键已清空）。

---

## §0 一页结论

### 0.1 四类处置

| 处置 | 数量 | 条目 | 一句话理由 |
|---|---|---|---|
| **① 直接开启** | **3** | `XEYO_TOOL_OFFLOAD`、`XEYO_BLOB_GC_ENABLED`（两段式）、GUI `thinking` / `showExperimental`（用户自选） | 设计已完整 / 有 dry-run 缓冲 / 纯用户偏好 |
| **② 修改后开启** | **4** | `XEYO_C2_LLM_SUMMARY`（**唯一留在 GUI 的**）、`XEYO_TOOL_AGING`、`XEYO_WALL_HARD_STOP`、`XEYO_MCP_NAME_MANIFEST` | 各缺一个**前置机制**（可回滚 / 可观测 / 恢复 / 产品入口） |
| **③ 不可开启** | **1 + 10** | `XEYO_MEMORY_INDEX_LIVE`（用户已裁决下线）；已固化的 10 个（**不是"关"，是"已删且恒开"**） | 带事故编号的证据门禁 / 固化决策 |
| **④ 可删除** | **4 类** | 见 §5：`cli/feature_registry.py`（★真发现）、恒真门函数与未消费常量、`XEYO_LEGACY_THING` 占位、残留键（已由 prune 接管） | 零消费方 / 死分支 / 双注册表冲突 |

### 0.2 优先级总表（三轨并行，不互相阻塞）

```
轨 A · 立刻可做（不依赖任何改动）
  A1  XEYO_TOOL_OFFLOAD            直接开 → 观察一轮
  A2  XEYO_BLOB_GC_ENABLED         先 dry_run=1 观察一轮 → 再关 dry_run
  A3  GUI thinking / showExperimental   用户自选（成本/半成品，非默认改）

轨 B · 主线（按依赖，不按分数）
  B0  ⑥ JSONL 撕裂尾修复 + 跨进程租约         S 级 · 零风险 · 建立"构造性测试"节奏
  B1  ① 命名事件瀑布（只命名 + 观测）          ← 杠杆满分，后续一切的入口
      ② 投影层通用 replace 算子 + sourceEventSeqs
      ④ hooks 事件面扩展（兑现预留的 3 个事件）
  B2  ⑤ C2 压缩事务化                         依赖 ①②④；同时是 ② 项开关的解锁条件
  B3  ③ 沙箱 confine + Windows restricted-token  ← 唯一换地基，必须最后

轨 C · 清理（随时，不阻塞）
  C1  cli/feature_registry.py                  零生产消费方 + 与权威注册表冲突
  C2  恒真门函数 / 未消费常量                   死分支（保留或降级，见 §5.2）
  C3  XEYO_LEGACY_THING                        纯占位示例
```

### 0.3 一句话

> **能立刻开的只有 3 项，且都不是"大功能"；真正的大收益全部卡在同一类前置——可回滚 + 可观测。**
> 所以正确的顺序是：**先用轨 A 拿即时收益 → 用轨 B 的 B0/B1 把"可回滚 + 可观测"铺出来 → 再回来开 ② 类的 4 个开关，最后动沙箱。**

---

## §1 本轮已落地的修复（改动清单 · 证据 · 边界）

三件事：**修两处真缺陷** + **GUI 只留 C2**。全部有测试钉住。

### 1.1 缺陷① GUI 死开关 —— 结构性修法（不是打补丁）

**原缺陷**：`XEYO_MEMORY_INDEX_LIVE` 因"authority 面不因下线而少一个已裁决键"被**保留在注册表**
（`memory/memory_switches.py`），于是 `get_value()` 返回 settings 里的 `"1"`、`current()` 报 `source="settings"`、
GUI 渲染成"开"、还能来回切、`save()` 也接受——但 `engine/query_loop.py:355-363` 的
`_memory_index_live_enabled()` **恒 `False` 且根本不读这个键**。**「显示开、实际关」**，且无测试覆盖。

**修法：给注册表加两个维度，让"能不能显示"与"运行时读不读"在数据层分开。**

| 维度 | 语义 | 消费方 |
|---|---|---|
| `exposed` | 是否在产品 GUI 暴露 | 前端 `filter(sw => sw.exposed === true)` |
| `runtime_reads` | 运行时是否**真的**读该键 | `current()` 据此产出 `effective` / `ignored` / `source` |

`current()` 现在的输出契约（`python/memory/memory_switches.py:178-210`）：

```
runtime_reads=True   → effective = settings 值, source = "settings" | "default"
runtime_reads=False  → effective = 默认值,   source = "ignored"   ← 恒关占位键
```

前端按 `effective`（**运行时真值**）显示开关态，`ignored` 项**置灰 + 标注"已下线，不生效"**。
**⇒ 「显示开、实际关」在结构上不可能再发生**——不是靠约定，是靠两个维度不可能同时为真。

**另一个镜像问题也一并封死**：`save()` 对未注册键**直接抛错**（`:239-242`），未知键写不回去。

### 1.2 缺陷② settings 残留键 —— 加了清理机制，并清了现场

**原缺陷**：本工作区 `.xeyo/settings.json` 的 `memory` 段有 4 个**已从注册表删除**的键
（`XEYO_MEMORY_RERANK_PREFERENCE` / `XEYO_MEMORY_SQLITE_INDEX` / `XEYO_CACHE_COOLDOWN_OMEGA` / `XEYO_C2_GATE`）。
不生效、不报错、**无清理入口**；同名键将来复活会**静默继承旧值**。

**修法：新增 `stale_keys()` / `prune_stale()`（`memory_switches.py:113-155`）**，三条边界写进实现：

| 边界 | 实现 |
|---|---|
| 只在**确有残留**时写盘 | 无残留 → 零写入（避免每次启动重写 settings.json） |
| 只动 `memory` 段 | `plugins` / `skills` / `mcp_servers` / `hooks` **不碰** |
| best-effort | 写盘失败只跳过该文件；**不阻断 server 启动 / 保存** |

**接入三个点**（缺一处就会漏）：

| 接入点 | 行为 |
|---|---|
| `server/__main__.py` 启动期 | 静默清理 home + workspace 两侧 |
| `server/routers/control.py` GET | 只读报告 `stale`（**不写盘**） |
| `server/routers/control.py` POST | **先 `prune_stale` 后 `save`**，回执 `pruned` 供审计（顺序不能反，否则回执恒空） |

**现场已清**：本工作区 4 个残留键 + 误导性的 `XEYO_MEMORY_INDEX_LIVE: "1"` 全部移除；
`memory` 段现在只剩 `XEYO_L5: "v61"`（有效键、运行时真读、`exposed=False`）。

### 1.3 GUI 只留 C2（按你的口径：其余是测试便捷开关）

`MEMORY_SWITCHES` 四项的最终归位：

| 键 | `exposed` | `runtime_reads` | 说明 |
|---|---|---|---|
| `XEYO_C2_LLM_SUMMARY` | **True** | True | **唯一产品开关**，GUI 可见可切 |
| `XEYO_L5` | False | True | 测试/评测便捷（v61 ↔ project 实验通道），运行时可切，**不在 GUI** |
| `XEYO_TOOL_AGING` | False | True | 同上（等恢复机制） |
| `XEYO_MEMORY_INDEX_LIVE` | False | **False** | 已下线占位；GUI 不显示、运行时恒关 |

**注意保留的两个非开关行**（它们不是"开启关闭的 GUI 功能"，故未删，**如需一并移除请说一声**）：

- **「已失效的残留开关 + 立即清理」行**——只在确有残留时出现；现场清空后**已经不再渲染**。
- **「A3 日常监控快照 · 立即快照」行**——运维动作（读生产 ledger 写 `docs/12` 表D，无模型调用），非开关。

### 1.4 改动文件清单

| 文件 | 改动 |
|---|---|
| `python/memory/memory_switches.py` | 注册表 4→**6 元组**（+`exposed`/`runtime_reads`）；`current()` 加 `exposed/ignored/effective`；新增 `stale_keys`/`prune_stale`；`save()` 过滤未知键 |
| `python/server/routers/control.py` | GET 回 `stale`；POST 先 `prune_stale` 再 `save`、回执 `pruned` |
| `python/server/__main__.py` | 启动期静默清理两侧残留 |
| `gui/src/lib/api.ts` | `MemorySwitch` 加 `exposed?`/`ignored?`/`effective?`，`source` 加 `'ignored'`；响应加 `stale?`/`pruned?` |
| `gui/src/components/MemorySwitchesSetting.tsx` | 按 `exposed` 过滤、按 `effective` 显示；`ignored` 置灰 + 标注；残留清理行 |
| `gui/src/components/SettingsModal.tsx` | 段说明改为"其余记忆开关仅供测试/评测，不在本面板暴露" |
| `python/tests/test_memory_switches.py`、`test_memory_switch_authority.py` | 钉死新契约（`exposed`/`ignored`/`effective`/prune/未知键拒绝） |

**元组扩容的兼容性已核实**（这是扩容唯一风险点）：全部消费点都是 `for key, *_` 或 `{k for (k, *_rest) in ...}`
形式——`server/routers/control.py:76`、`tests/test_memory_switches.py:47,59`、
`tests/test_memory_switch_authority.py:85,132`。**无一处按固定 4 元组解包。**

### 1.5 验证回执

| 门 | 结果 |
|---|---|
| `python/.venv/Scripts/python.exe -m pytest tests/test_memory_switches.py tests/test_memory_switch_authority.py` | **22 passed** |
| 相邻套件（`test_c2_llm_summary_t8` / `test_memory_aging` / `test_aging_default` / `test_runtime_c2` / `test_extensions_api` / `test_c2_escape_hatch` / `test_citation` / `test_rerank_preference`） | 通过 |
| `gui`: `npx tsc --noEmit` | 通过 |
| `gui`: `npx vitest run` | 2 个套件 5 个用例失败——**用 `git show HEAD:<file>` 临时还原后对照跑，失败完全相同 ⇒ 既有失败，与本次改动无关**（`MessageList.chat.test.tsx` / `mainPaths.workflow.test.tsx`）。已恢复改动并核对关键新增仍在 |
| `py_compile`（5 个改动文件） | 通过 |

**环境缺口（既有，非本次引入，但会影响你跑门）**：
`python/.venv` **缺 `typer`** ⇒ `tests/test_config_profiles_t16.py` 有 2 个用例 `ModuleNotFoundError: No module named 'typer'`；
`py -3.11` 里有 typer 0.27.2。**⇒ CLI 相关测试要用 `py -3.11` 跑，`.venv` 只覆盖引擎/server 侧。**

---

## §2 处置一：直接开启（3 项）

判据是**「设计已完整 + 开启成本为零 + 关掉能逐字节回退」**三者同时成立。

### 2.1 `XEYO_TOOL_OFFLOAD` —— L3 超长工具结果外部化 · **唯一无前置**

| 项 | 内容 |
|---|---|
| 落点 | `memory/offload.py`（`_ENV="XEYO_TOOL_OFFLOAD"`；阈值 `XEYO_TOOL_OFFLOAD_CHARS` 默认 128；预览 `XEYO_TOOL_OFFLOAD_PREVIEW` 默认 128） |
| 现状 | **旁路阶段**：超长结果仍走 C0 截断（8192） |
| 开启后 | `> OFFLOAD_THRESHOLD` 的工具结果**直接 offload**（写文件 + 固定预览引用），**不再走 C0 截断**——源码明写动机：「避免"先截断又 offload"的双重处理」 |
| 收益 | 超长结果不再全量进上下文；**引用文本与文件内容都确定性 ⇒ 同消息同 uid 每次生成相同引用 ⇒ KV 前缀稳定**（这条是源码明写的红线保证） |
| **为什么可以直接开** | ① 设计已完整（含字节稳定红线）；② 它是**旁路模块**，关掉即回原路径；③ 与已就位的三层截断链（`cmd_compact` 语义压缩 → `truncate.py` 硬截断 → `tool_registry._apply_output_budget` spill seam）**职责不重叠**：前两层对 Bash/Read 生效（`output_budget=0` 豁免），offload 针对其余工具的超长结果 |
| 开法 | `<repo>/.xeyo/settings.json` 写 `{"memory": ...}` 之外的环境键，或直接 `set XEYO_TOOL_OFFLOAD=1`（注意：它**不在 `MEMORY_SWITCHES` 注册表**里，是普通环境开关） |
| 判据 | 构造一个 > 阈值的结果 → 上下文里出现**引用**而非全文；同一消息在一次会话内重复投影，引用**逐字节相同**；`XEYO_TOOL_OFFLOAD=0` 时输出与改动前**逐字节一致** |

> ⚠️ **一个必须核实的边界**：`tools/exec_channel.py:11` 记录了「容器路由下 `first_sniff` 把宿主空 scratch 当成工作区，
> 注入 `(空目录)`」——说明**执行通道差异会污染观测**。开启 offload 时，**offload 的落盘目录必须在容器内外都可读**，
> 否则模型拿到一个它自己读不到的引用路径。这是落地前唯一需要实测的点（**不是**评测分支，是路径可达性）。

### 2.2 `XEYO_BLOB_GC_ENABLED` —— rewind 快照 blob 回收 · **两段式开**

| 项 | 内容 |
|---|---|
| 落点 | `rewind/blob_gc.py:16`、`:430`；启动接线 `server/app.py:170` |
| 现状 | **三重默认安全**：`enabled=False` + `dry_run=True`（默认 1）+ 未超预算不动手。注释记录**曾漏判 `dry_run` 导致真删**（已被测试钉死） |
| 不做的代价 | 快照目录**无限增长**——每个检查点的 blob 永久保留 |
| **开法（两段，不能一步到底）** | **第 1 段**：`XEYO_BLOB_GC_ENABLED=1` **保持 `dry_run=1`**，跑一轮真实使用，读报告确认「将删的都是不可达 blob」；**第 2 段**：确认无一误删后，`XEYO_BLOB_GC_DRY_RUN=0` |
| 为什么算"直接开启" | 有 dry-run 缓冲 ⇒ 第一段**零破坏性**，本质是"先看一份报告"；两段都无前置机制依赖 |
| 判据 | dry-run 报告里每个待删 blob 都**不可达**（不被任何 checkpoint / `agent_file_index` / `rewind_events` / `orphans` 引用）；真开后 `rewind` 的恢复动作全部成功（blob GC 的三重默认安全里，「永远全量保留」的是 `agent_file_index`/`rewind_events`/`orphans`） |

### 2.3 GUI `thinking` / `showExperimental` —— 用户自选，非默认改

| 项 | 内容 |
|---|---|
| `thinking` | `gui/src/stores/settingsStore.ts:266`，默认 `'disabled'`。**关的动机是成本**（输出占成本 83%），不是风险 |
| `showExperimental` | `:304`，默认 `false`。「半成品（AgentMap 代码/架构地图）移出主界面 chrome」 |
| 处置 | **不改默认值**——两者都是用户偏好/半成品隔离，已可由用户在设置里打开。**"打开"这件事本身已经完成**，本文只是确认它们不属于"没开的缺陷" |
| 若想扩大使用 | 只建议改**文案**（例如在设置里注明"推理/调试类任务建议开启"），不建议改默认——默认开会直接推高全部用户的成本 |

---

## §3 处置二：修改后开启（4 项）

判据：**功能本身已实现且安全，但它依赖的前置机制还没落地**。四项的前置条件**高度同构**——
三项要"可回滚"，两项要"可观测"，一项要"恢复"，一项要"产品入口"。

### 3.1 `XEYO_C2_LLM_SUMMARY` —— C2 摘要 LLM 旁路 ★ 唯一留在 GUI 的开关

| 项 | 内容 |
|---|---|
| 落点 | `memory/runtime.py:62-85`；注册 `memory/memory_switches.py:44` |
| 默认 | `"0"`（**确定性摘要**） |
| **为什么现在是关的（源码原话）** | 「实测**吸收潜力高但输出不稳定**，默认关=确定性摘要」 |
| 开启收益 | 超长会话的压缩摘要由**模型生成强保真要点列表**，替代确定性截断 ⇒ 压缩后**不丢关键细节**。这是**唯一直接影响长会话质量**的开关 |
| 代价 | 多一次模型调用（成本可归因，见下） |
| **前置 ①：可回滚** | 依赖 **B1-②「投影层通用 `replace` 算子 + `sourceEventSeqs`」**。压缩结果的最自然表达就是一次 `replace`（把 `[msg_5 … msg_120]` 换成一条摘要）；没有通用算子就只能再造一个 `_OP_COMPACT` 单用途 op，**复制 `rewind` 的老路**（单用途算子堆叠 = 今天多个机制难统一的根因） |
| **前置 ②：可归因** | 依赖 **B1-①「命名事件瀑布」**。压缩前后各落一条可配对事件（同一 `compact_id`），才满足 XEYO 自己在 `usage/ledger.py:66-76` 引用过的记账纪律：「压缩走模型的调用**必须可归因**」 |
| 怎么改 | ① 先落 B1-①②；② 在 `engine/compact.py` 的 C2 分支加"压缩前 emit → 调模型 → 压缩后 emit（同一 `compact_id`）"，压缩结果以 `replace` marker 追加（**不改 MessageStore / JSONL**，保持它现有的投影层定位）；③ 把 `_C2_LLM_PREFETCH_MIN_MESSAGES = 24` 的旁路门槛保留（它已是事实上的流量闸） |
| 判据 | **可回滚**：压缩后追加 undo marker，可见面精确回到压缩前（构造用例）；**配对平衡**：让 cut 点落在 `tool_use`/`tool_result` 中间，断言投影侧无孤儿；**可归因**：C2 那次模型调用在账本里可查且标注"压缩归因"；**回退**：开关置 `"0"` 后摘要输出与改动前**逐字节一致** |
| 风险 | 中（R=3）。压缩直接改变模型可见历史长度 ⇒ 必须先用例钉住"压缩后模型仍能看到最近 3 轮工具配对"（`KEEP_TAIL_TOOL_ROUNDS = 3` 已有此语义） |
| **为什么它是唯一留在 GUI 的** | 其余三个（`XEYO_L5` / `XEYO_TOOL_AGING` / `XEYO_MEMORY_INDEX_LIVE`）是**测试与运维便捷**；只有 C2 是**产品开关**——它决定"压缩后上下文质量"，用户能感知 |

### 3.2 `XEYO_TOOL_AGING` —— 工具结果老化

| 项 | 内容 |
|---|---|
| 落点 | `engine/aging.py:4`、`:43`；注册 `memory/memory_switches.py:47`（`exposed=False`） |
| **为什么现在是关的（源码原话）** | 「**toolout 占位的恢复机制未落地前保持关闭，避免原文不可找回**」 |
| 开启收益 | 压缩后冻结区仍可按窗口紧追推进；近档留富信息、远档折叠为短存根 ⇒ **长会话上下文预算显著改善** |
| **前置：恢复机制** | 原文被折叠后必须**找得回**。工程上就是"折叠时必须留一个可定位的句柄" |
| 怎么改 | ① 先落 `logs/toolout` 的**文件级恢复**；② 与**已升格开**的 `prompt/transcript_pointer_shadow.py`（⑬ C2 原始历史指针）组合——指针已能指向原始 transcript，老化只需在折叠处**复用同一指针形态**，不必另造一套；③ 老化的窗口推进逻辑已在 `engine/aging.py`，**不改算法，只补"可找回"这一环** |
| 判据 | **可找回**：对任一被折叠的远端结果，凭句柄能还原原文（构造用例：折叠 → 取回 → 逐字节等于原文）；**回退**：`"0"` 时输出与改动前逐字节一致；**预算改善可测**：同一长会话下投影字节数下降 |
| 依赖 | 与 3.1 共享同一套"可回滚 + 可观测"基建 ⇒ **B1 做完后两项可同批开** |

### 3.3 `XEYO_WALL_HARD_STOP` —— 死线硬停

| 项 | 内容 |
|---|---|
| 落点 | `engine/budget.py:38-43`、`:163` |
| **为什么现在是关的（源码原话）** | 「**默认关（产品会话无墙钟武装 → 行为零变化）**」；`:163`：「产品会话即使设了死线（仅时间感播报）也不会被引擎自动武装」 |
| 开启收益 | 到点**强制收尾**，防长任务失控烧钱（配合已有的 grace-cliff：`MAX_TOOL_CAP_STREAK = 2`，单轮爆发不算失控，连续两轮顶满才进收尾窗） |
| **前置：产品入口** | 没有"这次会话的死线"入口 ⇒ **没有触发源**，开了也无行为变化。所以它的前置不是机制，是**产品路径** |
| 怎么改 | ① GUI 会话级设置加"本次会话死线"（或在 Composer 侧加一次性入口）；② 把它写进 settings 并让 `budget.py` 武装；③ **不要改默认值**——默认武装会让所有用户的会话行为突变 |
| 判据 | 设死线 → 到点触发收尾且**不硬杀**（grace 内让模型自然收尾）；未设死线 → 行为**逐字节不变**；收尾窗内不产生孤儿工具调用 |
| 风险 | 低-中。收尾逻辑已存在（budget 的收尾窗），新加的是"武装开关"这一层 |

### 3.4 `XEYO_MCP_NAME_MANIFEST` —— MCP 工具 name-manifest 暴露档

| 项 | 内容 |
|---|---|
| 落点 | `extension/mcp_name_manifest_shadow.py:13,31,37-42`；红线登记在 `sidecar/upgrade.py:23-24` |
| **为什么现在是关的（源码原话）** | 「**需改会话起点冻结快照**」，标记「**实测 token 收益后接入**」 |
| 开启收益 | 把一个工具的 schema 收缩为 `name + 一句短描述`（丢弃 `inputSchema` 全文）⇒ **省 token** |
| **前置：① 先证明收益 ② 再动红线** | 它**不是**"改个函数就能开"的普通项：动它会触碰三条红线——`tools 数组会话内绝对冻结` / `_schemas_cache 永不失效` / `零前缀重缓存`。收窄 schema 会改变**会话起点快照**，而快照一变，整个会话的 KV 前缀缓存失效 |
| 怎么改（唯一安全路径） | ① **先离线量 token 收益**（拿真实 MCP 配置对比 `inputSchema` 全文 vs name+短描述的 token 差）；② 若收益不显著 ⇒ **直接放弃，不开**；③ 若显著 ⇒ 收益必须体现为"**会话起点就收缩**"（在建立 `_schemas_cache` 之前决定），**绝不允许多会话中途变 schema**；④ 走 `sidecar/` 形态先旁路验证（它已是 shadow 模块，形态天然合规） |
| 判据 | 会话内 schema **零变化**（构造：中途启停 MCP server，断言 tools 数组逐字节不变）；token 收益**可复现测量**；关掉后会话起点快照**逐字节一致** |
| 结论 | **本文把它列为"修改后开启"里最靠后的一项**：它的前置是"先做出收益证明"，而不是"先写一段代码" |

---

## §4 处置三：不可开启 / 明确不动

### 4.1 `XEYO_MEMORY_INDEX_LIVE` —— 用户已裁决下线（带事故编号）

| 项 | 内容 |
|---|---|
| 读点 | `engine/query_loop.py:355-363` `def _memory_index_live_enabled() -> bool:` **恒 `return False`** |
| 原因 | **事故 `sess_mtiche8l`**：弱模型（glm-4.5-air）**把索引条目当任务对象**。2026-09-09 **用户裁决维持下线**，`AGENTS.md`「已下线」与此对齐 |
| 重开条件（源码原文） | 「须源码级改此函数 + **A1（200+ 轮 live）/ A3 过门证据**」 |
| 本次处置 | ① 运行时/配置面**维持恒关**；② 注册表条目**保留**（authority 面不因下线而少一个已裁决键）；③ 但**已从 GUI 面移除**（`exposed=False`）并标 `ignored` ⇒ 不再出现"显示开、实际关"；④ 本工作区 settings 里的误导性 `"1"` **已删除** |
| **不要做的事** | ❌ 不要把它列进优化清单——**这不是待办，是带门禁的已裁决决策**（列进去等于不了解项目史） |

### 4.2 已固化的 10 个开关 —— **不是"关"，是"已删且恒开"**

`memory/memory_switches.py:48-61` 记录了 2026-09-06 用户决策「v61 默认开启」后**删除**的开关。
它们**已固化开启**，回退只能改源码：

| 原开关 | 现状 | 固化点 |
|---|---|---|
| `XEYO_C2_GATE` | 已删，恒 `True` | `memory/l5_flag.py:43-50` `c2_gate()` |
| `XEYO_C2_PRESSURE_FORMULA` / `_GAIN_` / `_EXTEND_` | 已删 → `_c2_formula_enabled` 按模式恒真/恒假 | `memory/runtime.py:1319` |
| `XEYO_MEMORY_SQLITE_INDEX`（A4） | 已删，恒开 | `memory/memindex.py:86` |
| `XEYO_CACHE_COOLDOWN_OMEGA`（A1 ω） | 已删，恒开 | `memory/memindex.py:16` |
| `XEYO_MEMORY_RERANK_PREFERENCE`（⑮） | 已删，`enabled()` **恒 True** | `memory/rerank_preference_shadow.py:47-53` |
| `XEYO_MEMORY_QUERY_REWEIGHT`（F4） | 已删，恒开 | `memory/search.py:97-104` |
| `XEYO_C2_CITATION` | 已删，恒开 | `memory/runtime.py:481-483` |
| `XEYO_C2_ESCAPE_HATCH` | 已删，恒开 | `memory/runtime.py:804-806` |
| `XEYO_MEMORY_RESTORE`（A2） | 已删，恒开 | `memory/runtime.py:809-811` |
| `XEYO_SESSION_MD_DELTA`（A5） | 已删，恒开 | `memory/session_md.py:225-227` |

**处置：知道就好，别去"复活开关"。** 它们若出现在任何文档里被当成"未开启功能"，那是误读——
**"已删且生效"与"存在但关闭"是相反的状态**。本工作区 settings 里的 4 个同名残留值（含 `XEYO_C2_GATE: "1"`）
**已由 prune 清掉**。

> **注意一处口径差异**：`memory/runtime.py:1319` 的 `_c2_formula_enabled` 是 **project 恒 True / v61 恒 False**
> （另有 `XEYO_C2_FORMULA_OVERRIDE` 一次性注入通道供 A/B 定参脚本用）——它**不是**恒真，
> 但**对当前 v61 模式是恒假**。看这部分代码时不要按"已固化恒 True"理解（`memory_switches.py:52` 的注释
> 写"改为 `_c2_formula_enabled` 恒 True"是**按 project 语境**说的，字面读会误解）。

### 4.3 反面清单（不改，且理由重要）

来自收益评估 §7，逐条保留：

| ❌ 不做 | 一句话理由 |
|---|---|
| 记忆召回重开 | **用户已裁决恒关**（事故编号 + A1/A3 门禁），不是待办 |
| 照 dsh 补 spill / 补工具配对平衡 | **都已实现**，且 XEYO 还多一层 dsh 没有的**族语义压缩**（`cmd_compact.py` 6 个压缩器） |
| 前端插槽化（对齐 dsh 45 个 ui 包） | dsh 插槽化是为**多形态复用**；XEYO 只有一个桌面形态 ⇒ 成本巨大、收益是"结构好看" |
| Typert RPC / Cordis 式 255 包重组 | SSE 事件流 + 生成式 manifest 已在解决同一问题；**换协议风格不产生能力增益** |
| per-file 100% 覆盖率门 | 应做 **ratchet（只升不降）**；100% 会逼出为覆盖而写的空测试，反而丢信号 |
| 把沙箱排第一 | **收益第一 ≠ 顺序第一**（唯一改变行为边界、唯一无法旁路验证、会让权限链部分作废） |
| 重写 `query_loop.py` | `AGENTS.md` 的处方是"**只留接线点**"，不是重写；重写会撕掉 `_EARLY_BLOCKLIST`、`_cancel_early_tasks` 4 个取消点、投机提前执行等已踩坑细节 |
| 忽略 XEYO 已比 dsh 强的地方 | `rewind/`（12 文件 5,343 行）、T_now 管线、投机提前执行、族语义压缩、记忆子系统、成本治理、Tauri 壳 —— **"完美优化"的第一条纪律是不破坏这些** |

---

## §5 处置四：可删除（4 类）

判据：**零消费方 / 死分支 / 纯占位 / 已被机制接管**。每项都给"删的收益"与"删的风险"。

### 5.1 ★ `cli/feature_registry.py` —— **零生产消费方，且与权威注册表冲突**（本轮真发现）

**先说结论**：这是一份**写了但从未接线**的注册表，而且它登记的内容与**真正在用的**注册表**互相矛盾**。
处置是**二选一：删掉，或真正收编**——**放着不动，它就是下一个"写了无消费方"。**

**证据一：生产侧零消费点。** 全仓 grep `feature_registry` / `FEATURE_SPECS` / `parse_features`（排除 `.venv`）：

```
./tests/test_config_profiles_t16.py:22   from cli.feature_registry import FEATURE_SPECS, parse_features   ← 唯一消费者
./memory/memory_switches.py:8             "取值域对齐 cli.feature_registry 的口径"                          ← 只是文档引用
```

**唯一消费者是一个测试文件**。生产代码**一处都没用**。

**证据二：它自己也承认没接线。** 文件 docstring（`cli/feature_registry.py:17-19`）：

> *Fail-closed and non-breaking: this is the declarative source of truth; the parser is something callers **may** use.
> **No existing call site is rewritten here**.*

**证据三：覆盖面只有 7%。** 它登记 **17 个** `XEYO_*` 键；全仓实测 **238 个**。若真接上，
其余 221 个会被 `parse_features` 全部报成 `"unknown switch ... is ignored"` ⇒ **噪音大于价值**。

**证据四（最关键）：与权威注册表三处冲突。**

| 键 | `cli/feature_registry.py` 说 | 真实状态（`memory/memory_switches.py` + 读点） | 判定 |
|---|---|---|---|
| `XEYO_C2_GATE` | `stage=internal, default="1"` —— **当成存活开关**（`:55`） | **已固化删除**（2026-09-06）；`l5_flag.py:8`「已固化删除」、`:43-50` `c2_gate()` 恒 `True` | ❌ **直接矛盾**：一个说它在且默认开，一个说它已删 |
| `XEYO_TOOL_AGING` | `stage=_STAGE_STABLE`（稳定功能，`:59-61`） | `memory_switches.py:47` 归为 **`exposed=False` 的测试/评测便捷开关** | ⚠️ 分类冲突 |
| `XEYO_LEGACY_THING` | `stage=removed, removed=True`（`:79-81`） | **纯占位示例**，唯一的"消费者"是它自己的测试 | ⚠️ 只为演示 removed 分支存在 |

**这就是本项目反复出现的"双轨并行"缺陷模式的又一例**（`AGENTS.md` 审计已记录：rewind v2/v3、MCP 直挂/网关、
AskUserQuestion/权限 ASK、GUI/TUI 两套 SSE）。**两份注册表描述同一批键，一份是权威、一份是幽灵。**

| 项 | 内容 |
|---|---|
| **删的收益** | ① 消除双注册表歧义（尤其 `XEYO_C2_GATE` 的真假矛盾）；② 消除"17 vs 238"的覆盖面错觉；③ 符合 `AGENTS.md` 反巨石（幽灵模块会诱使后来者往里加键） |
| **删的风险** | 低。`tests/test_config_profiles_t16.py` 里 5 个用例需改写——**改法是把断言指向真实注册表**（`memory_switches.MEMORY_SWITCHES` + `MEMORY_SWITCHES` 的 `exposed`/`runtime_reads`），语义等价甚至更强 |
| **若选择"收编"而不是删** | 需要：① 补齐 238 个键（或明确只登记"产品面开关"子集）；② 与 `memory_switches` 合并为单一 SSOT（否则双轨依旧）；③ 至少一个**生产**消费点（boot 时 `parse_features` 报警未知键）。**成本远高于删。** |
| **建议** | **删**（推荐）；若你对"声明式注册表"这个方向有产品意图，那就必须按上一条收编，**不要维持现状** |

### 5.2 恒真门函数与未消费常量 —— **函数留着，分支删掉**

这一类要分清楚，**不能一刀切删**。

**（a）真正未消费的常量 → 建议直接删**（实测：除定义处外全仓零引用）：

| 常量 | 位置 | 证据 |
|---|---|---|
| `DEFAULT_C2_GATE = True` | `memory/l5_flag.py:19` | 全仓唯一出现处 |
| `C2_GATE_ENV = "XEYO_C2_GATE"` | `memory/l5_flag.py:17` | 全仓唯一出现处（`XEYO_C2_GATE` 的另外两处出现是注释与 `feature_registry`） |

**（b）恒真的门函数 → 建议保留，但要认清它们是什么：**

| 函数 | 值 | 调用点数 | 位置 |
|---|---|---|---|
| `l5_flag.c2_gate()` | 恒 `True` | 2（`engine/query_loop.py:869`、`server/routers/sessions.py:831`） | `memory/l5_flag.py:43-50` |
| `runtime._c2_citation_enabled()` | 恒 `True` | 1（`runtime.py:576`） | `memory/runtime.py:481-483` |
| `runtime._c2_escape_hatch_enabled()` | 恒 `True` | 1（`runtime.py:1053`） | `memory/runtime.py:804-806` |
| `runtime._restore_enabled()` | 恒 `True` | 1 | `memory/runtime.py:809-811` |
| `session_md.deltas_enabled()` | 恒 `True` | 1 | `memory/session_md.py:225-227` |
| `search.query_reweight_enabled()` | 恒 `True` | 4 | `memory/search.py:97-104` |

**为什么建议保留**：每个 docstring 都写着「**回退只能改本函数源码**」——**它们就是为"单点回退"而刻意留的句柄**。
删掉函数，回退就要改到更深的地方，**违反"回退要容易"这条工程原则**。

**真正该删的是"恒假前置"分支**，也就是**函数有价值、分支没价值**：

```
engine/query_loop.py:869
  改前：(not c2_gate()) or int(snap.compact_cursor or 0) > 0     ← not c2_gate() 恒 False
  改后：int(snap.compact_cursor or 0) > 0                        ← 消一个死分支
```

`sessions.py:831` 的 `"c2_gate": bool(c2_gate())` 是 **API 回执字段**，属对外契约 ⇒ **保留**。

| 项 | 内容 |
|---|---|
| 删的收益 | 少 2 个死常量 + 1 个死分支；消除"这里似乎还能关点什么"的错觉 |
| 删的风险 | 低。但注意 `memory/runtime.py` 是 **1926 行巨石** ⇒ 改动遵守 `AGENTS.md` 第 7 条：**只抽本次触碰的函数，禁止顺手重构** |
| 判据 | 改后 `tests/test_c2_path_a.py` / `test_runtime_c2.py` / `test_citation.py` / `test_rerank_preference.py` / `test_memory_aging.py` 全绿 |

### 5.3 `XEYO_LEGACY_THING` —— 纯占位

`cli/feature_registry.py:79-81`，名字字面就是"遗留物体"。它存在的唯一目的是演示 `removed=True` 的解析路径
（被 `tests/test_config_profiles_t16.py:112,122` 使用）。**采纳 §5.1 的删除即一并消失**；
若保留 `feature_registry`，则它是一个"永久示例数据"——建议换成真实已删键（如 `XEYO_C2_GATE`），别留假名字。

### 5.4 settings 残留键 —— **已由机制接管，无需再删任何东西**

| 项 | 状态 |
|---|---|
| 4 个残留键（`XEYO_MEMORY_RERANK_PREFERENCE` / `SQLITE_INDEX` / `CACHE_COOLDOWN_OMEGA` / `C2_GATE`） | **已从本工作区清掉**（§1.2） |
| 误导性 `XEYO_MEMORY_INDEX_LIVE: "1"` | **已删除** |
| 未来的残留 | 启动期静默清理 + GET 报告 + POST 清理，**三道接管** |
| 残余风险 | 直接手改 `settings.json` 仍可写入未注册键（`save()` 会拒，但手改绕过它）⇒ **由启动期 prune 兜住**，风险可接受 |

---

## §6 优先级与实施顺序

### 6.1 为什么"收益最大"不等于"先做"

收益评估把两个榜拆开后有决定性的结论：

```
「收益量级榜」（B+L，满分 10）        「完美适配榜」（F，满分 5）
沙箱            10  ← 收益最大         命名事件瀑布     5  ← 最完美
命名事件瀑布      9                    投影层算子       5
投影层算子        8                    撕裂尾+租约      5
hooks 扩展        7                    hooks 扩展       5
C2 压缩事务       7                    沙箱            3  ← 失分点
```

**沙箱在收益榜第一，在适配榜只有 3。** 它要在 `tools/bash_tool/runner.py`（`:160`、`:345` 两个 spawn 点）
**新建一层 `confine()` 抽象**，且 confine 生效后"原本能跑的命令会失败"——**全表唯一改变现有行为边界**。
更关键的是：**它会连带让现有的权限链与黑名单部分作废**。

所以正确的顺序不是"先做收益最大的"，而是：

> **先做让最大收益变得可安全落地的。**

### 6.2 三轨并行

```
┌──────────────────────────────────────────────────────────────────────┐
│ 轨 A · 立刻可做（不依赖任何改动，可与轨 B 并行）                      │
│   A1  XEYO_TOOL_OFFLOAD             直接开（唯一无前置）              │
│   A2  XEYO_BLOB_GC_ENABLED          两段式：dry_run 观察 → 再真开     │
│   A3  GUI thinking / showExperimental  用户自选（不改默认）           │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ 轨 B · 主线（按依赖，不按分数）                                       │
│                                                                      │
│   B0  ⑥ JSONL 撕裂尾修复 + 跨进程租约      ← 全表唯一三项满分          │
│                                             S 级成本 · 零风险 · 完美适配 │
│                                             附带收益：建立"构造性测试"节奏│
│                                                                      │
│   B1  ① 命名事件瀑布（只命名 + 观测）       ← 杠杆满分 5/5              │
│       ② 投影层通用 replace + sourceEventSeqs                          │
│       ④ hooks 事件面扩展（5 → 8 事件）                                │
│         ↑ 三者互相成全，建议同批                                       │
│                                                                      │
│   B2  ⑤ C2 压缩事务化                       ← 依赖 ①②；解锁 3.1       │
│                                                                      │
│   B3  ③ 沙箱 confine + Windows restricted-token  ← 唯一换地基，必须最后 │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ 轨 C · 清理（随时，不阻塞）                                           │
│   C1  cli/feature_registry.py              零消费方 + 双注册表冲突     │
│   C2  未消费常量 2 个 / 死分支 1 个          S 级                       │
│   C3  XEYO_LEGACY_THING（随 C1 消失）                                 │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.3 三组真实依赖（决定顺序，不是偏好）

| 依赖 | 内容 |
|---|---|
| **A：① → ⑤ 与 ④** | 压缩事务化要在"压缩前"发射事件，hooks 要挂 `PreCompact`——**没有命名事件，这两件事都得再改一次 `query_loop.py`**（2000 行巨石） |
| **B：② → ⑤** | 压缩结果需要通用 `replace` 表达；否则只能再造一个 `_OP_COMPACT` 单用途 op，**复制 `rewind` 的老路** |
| **C：① 与 ④ → ③** | 沙箱需要"失败时优雅降级"的通道（否则 confine 拒绝命令后模型无从得知该换路）与"拦截点可观测"的能力（否则无法调试为什么某条命令被拒） |

### 6.4 三轨与本文件 §2–§5 的映射

| 轨 | 对应处置 | 为什么这个顺序 |
|---|---|---|
| A | §2 直接开启（3 项） | 收益即时、零前置 ⇒ **先拿**，且 `XEYO_TOOL_OFFLOAD` 与 offload 相关机制能给 B1 提供真实观测数据 |
| B | §3 修改后开启（4 项的前置） | B0/B1 做完 ⇒ §3 的 3.1/3.2 解锁；B3 做完 ⇒ 权限链有资格收粗 |
| C | §5 可删除（4 类） | 与 A/B 无耦合；先清 C1 可避免后来者往幽灵注册表里加键 |

### 6.5 "开了就是巨大收益"的 8 项在本框架里的最终归位

收益评估 §8 那张表是本文件的源头之一，此处做**最终裁决**：

| 收益评估表内的项 | 本文归位 | 理由 |
|---|---|---|
| ① `XEYO_TOOL_OFFLOAD` | **轨 A · 直接开** | 唯一无前置 |
| ② `XEYO_C2_LLM_SUMMARY` | **轨 B2 后开**（§3.1） | 前置 = 可回滚 + 可归因；**唯一留在 GUI 的开关** |
| ③ `XEYO_TOOL_AGING` | **轨 B2 后开**（§3.2） | 前置 = 恢复机制 |
| ④ GUI `thinking` | **轨 A · 用户自选**（§2.3） | 已可达，只是默认关 |
| ⑤ `XEYO_BLOB_GC_ENABLED` | **轨 A · 两段式开**（§2.2） | dry-run 缓冲 |
| ⑥ `XEYO_WALL_HARD_STOP` | **轨 B2 后开**（§3.3） | 前置 = 产品入口（不是机制） |
| ⑦ GUI `showExperimental` | **轨 A · 用户自选**（§2.3） | 半成品隔离 |
| ⑧ `XEYO_MCP_NAME_MANIFEST` | **轨 B3 之后 / 或永不开**（§3.4） | 前置 = 先证明 token 收益，再动三条红线 |

**⇒ 8 项里真正"立刻能开"的只有 3 项（①②⑤ 中的 ① 与 ⑤，加上 ④⑦ 这类用户自选项）；
其余 4 项全部卡在"可回滚 + 可观测 + 恢复 + 产品入口"这四类前置上——正好就是轨 B 的 B1/B2 要建的东西。**

---

## §7 如何修改：逐项落点与判据速查

| # | 项 | 落点（文件:行号） | 改什么 | 判据（构造性） |
|---|---|---|---|---|
| B0-1 | 撕裂尾隔离 | `session/record_transcript.py:247-250` | `except json.JSONDecodeError: continue` → 坏行**旁置到 `<name>.jsonl.torn`** + 审计一条可见记录 | 注入半行 JSON ⇒ 不抛错、坏行出现在旁置文件、审计有记录 |
| B0-2 | 跨进程租约 | `session/record_transcript.py:39`（`_disk_lock`）、临界区 `:150-156` | 一个租约文件（PID + 心跳 + 过期）**包住同一临界区**（`_maybe_rotate` 已在其中） | 两进程同时 append ⇒ 无交错损坏；租约过期自动可获取；**单进程字节完全相同** |
| B1-1 | 命名事件瀑布 | 新增 `engine/events.py`（新模块，符合反巨石）；`engine/query_loop.py` 7 个内联点 | 定义事件常量（`turn/start`·`turn/end`·`llm/before-request`·`llm/after-response`·`tool/pre-execute`·`tool/post-execute`·`compact/before`·`compact/after`·`budget/warn`·`guard/triggered`·`permission/decided`）；`emit()` 写 audit（复用 `default_audit_log()`）+ 可选 telemetry；内联点旁**各加一行 `emit(...)`** | 关掉后模型可见请求体与审计输出**逐字节相同**；跑一个含工具调用的回合，审计出现 `turn/start → llm/before-request → tool/pre-execute → tool/post-execute → turn/end` **有序**序列 |
| B1-1 内联点 | ↑ | `query_loop.py:175`（权限）`:1069`（repeat guard）`:800`（budget）`:850`（compact）`:645-686`（T_now 注入）`:179`（取消，4 个调用点 `:1164/:1364/:1416/:1440`）`:93/:112/:155`（投机资格） | **只加发射，不改语义**。特别地 `:1072 _ = guard_action` 把 guard 返回值丢弃了——命名事件正是让这个丢弃**可见**的手段 | — |
| B1-2 | 投影层算子 | `session/surface.py:36-38`（`_OP_REWIND`/`_OP_REWIND_UNDO`）、fold 循环 `:77-115`、辅助 `:117-150` | 加 `_OP_REPLACE`，marker 带 `{from_id, to_id}`；`active_markers`/`has_undo_marker` 各加一分支；事件带 `sourceEventSeqs` | **G1** 旧数据输出逐元素相同；**G2** 同 marker 重复 fold 稳定；**G3** replace 后 undo ⇒ 精确回到替换前；**G4** `sourceEventSeqs` 指向的原事件在合并日志中存在 |
| B1-4 | hooks 事件面 | `extension/hooks.py:24` `EVENTS`（现 5 个）+ 各发射点 | 补 `UserPromptSubmit` / `Stop` / `SubagentStop` / `PreCompact` / `PostCompact`；**每个新事件必须有真实发射点** | 关掉后零执行零注入；`fail_policy=abort` 与超时都归 `FailedAbort` 的行为不变；`PermissionRequest` **fail-closed DENY 不放松** |
| B2 | C2 压缩事务化 | `engine/compact.py`（C2 分支）、`memory/runtime.py`（`_C2_LLM_PREFETCH_MIN_MESSAGES = 24`） | 压缩前/后各 emit 一条（同 `compact_id`）；压缩结果以 `replace` marker 表达；**不改 MessageStore/JSONL** | 两条事件可配对；cut 点落在 `tool_use`/`tool_result` 中间时**投影侧无孤儿**；C2 那次模型调用在账本可查且标"压缩归因"；`KEEP_TAIL_TOOL_ROUNDS = 3` 语义保持 |
| B3 | 沙箱 confine | `tools/bash_tool/runner.py:160`、`:345`（两个 spawn 点） | 新建 `confine(argv, policy)` 抽象 + Windows `CreateRestrictedToken`（`WRITE_RESTRICTED`+`DISABLE_MAX_PRIVILEGE`+`LUA_TOKEN`）；per-workspace SID = `sha256(规范路径)` → `S-1-4-x-y`；per-session 随机 temp + 独立 SID；probe 真跑；**fail-closed** | read-only 下**写失败、读成功**；越界写被拒且**理由来自 OS 层**而非正则；沙箱不可用时**不静默降级**（`PLATFORM_CHAINS.win32` 曾为空 → 降级 `danger-full-access`，是已修复事故，必须有回归）；`enforcement:'partial'` 的已知缺口（Everyone 授权对象、硬链接别名）**用测试钉死** |
| C1 | 删幽灵注册表 | `python/cli/feature_registry.py`（133 行） | 删除；`tests/test_config_profiles_t16.py` 的 5 个用例改为断言 `memory_switches.MEMORY_SWITCHES` | 改后该测试文件**全绿**（注意需用 `py -3.11` 跑，见 §1.5） |
| C2 | 删死常量/死分支 | `memory/l5_flag.py:17,19`；`engine/query_loop.py:869` | 删 `C2_GATE_ENV`/`DEFAULT_C2_GATE`；`(not c2_gate()) or X` → `X`（保留 `c2_gate()` 供 `sessions.py:831` 回执） | `test_c2_path_a` / `test_runtime_c2` / `test_citation` / `test_rerank_preference` / `test_memory_aging` 全绿 |

**统一门**（每项完成都要过）：`python/.venv/Scripts/python.exe -m pytest python -m "not live"` 全绿 +
`npx tsc --noEmit` + `npx vitest run`；**CLI 相关测试用 `py -3.11`**（`.venv` 缺 typer）。

---

## §8 红线（改动前必须确认）

1. **沙箱不得按执行通道分叉。** 出现"容器路由就跳过"这类条件分支即属**应试修改**，`AGENTS.md` 明文禁止。
2. **会话自查询工具必须无条件注册。** 出现 `XEYO_BENCH_MINIMAL` 分支即应试。
3. **`XEYO_BENCH_MINIMAL` 只允许影响工具集，不得影响信息正确性。**
4. **tools 数组会话内绝对冻结 / `_schemas_cache` 永不失效 / 零前缀重缓存** —— 这三条是冻结红线，
   §3.4（`XEYO_MCP_NAME_MANIFEST`）是唯一会触碰它们的点，因此它排在最后。
5. **不破坏 XEYO 已有的 7 项独有机制**：`rewind/`（12 文件 5,343 行）、T_now 管线、投机提前执行、
   族语义压缩、记忆子系统、成本治理、Tauri 壳。**尤其 `rewind`**——任何改动投影层或 transcript 的点，
   都必须先确认 `session/surface.py` 文件头「兼容性」一节的契约仍然成立。
6. **反巨石**：新逻辑进新模块，既有巨石（`chat.py` / `query_loop.py` / `Composer.tsx` / `memory/runtime.py`）
   只留接线点；因功能触碰巨石时**允许顺手抽离本次触碰的函数，禁止顺手做无关重构**。

---

## §9 取证边界与文档状态

### 9.1 本文件的方法

| 项 | 说明 |
|---|---|
| 复核方式 | 直接读源码（`Read` + Python 脚本切片），**不依赖子代理转述** |
| 本轮实测的改动面 | `memory/memory_switches.py`、`server/routers/control.py`、`server/__main__.py`、`gui/src/lib/api.ts`、`gui/src/components/MemorySwitchesSetting.tsx`、`SettingsModal.tsx`、两个测试文件 |
| 本轮实测的死代码面 | `cli/feature_registry.py`（消费点穷举）、`memory/l5_flag.py`（全文）、`memory/runtime.py` 6 个门函数、`memory/session_md.py`、`memory/search.py`、`engine/first_sniff.py`、`engine/query_loop.py:869` |
| 复核环境 | `python/.venv/Scripts/python.exe`（22 passed）；`py -3.11`（typer 0.27.2） |

### 9.2 与前序文档的关系（**冲突以本文为准**）

| 文档 | 状态 |
|---|---|
| `docs/XEYO-未开启功能全清单-与原因.md` | §8 的两处缺陷**已修复**（本文 §1）；该文档已加修订标注 |
| `docs/XEYO-高杠杆优化点-收益评估.md` | §8 的缺陷注解与"开了就是巨大收益"表**已按本文归位**；两处已加修订标注 |
| `docs/XEYO-开源优化路线-五轮总结.md` | 其 P0 清单已被收益评估推翻（P0-3 等三项早已实现）；**以本文 §6 的顺序为准** |
| 五轮对比（R1–R5 合集） | 事实层未变；本文不动它们 |

### 9.3 未复核 / 待你裁决

| 项 | 说明 |
|---|---|
| `memory/runtime.py` 的 C2 公式族（约 600 行） | 只读了开关闸门，未逐行读公式（承接前轮） |
| `rewind/*` 细节 | 第五轮已全文精读；本文只引用结论 |
| **`A3 日常监控快照` 行与「残留清理」行是否也移出产品面板** | 它们**不是开启关闭的开关**，故按你的口径**保留**；若你要"面板只留 C2"，说一声即可一并移除 |
| **`cli/feature_registry.py` 是删还是收编** | 本文建议**删**（证据见 §5.1）；收编成本显著更高 |
| **恒真门函数是否连函数一起删** | 本文建议**保留函数、删死分支**（它们是刻意的单点回退句柄） |

