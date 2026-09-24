> **交接文档**。截至 2026-09-23（HEAD = `c991be6`）。给"新开一个对话"用：先读 §0 与 §1，再按 §7 继续。
> 所有数字后面都标了它是哪一台台子量出来的、以及**不能**怎么读。

> **后续裁决（同日，覆盖下文 §0/§7 的「B4 待裁」状态）**：B4 在 V2 影子链验收为
> **48 条 / 384 token**，`[EXCLUDED BRANCHES]` 先于 `[PATHS]`。126 点逐点配对平均新增
> 186.52 tok、`path` 0.2719→0.5701、`path_recent` 0.4033→0.8565；@700 tok 的
> `error_sig` 与关闭路径段同为 0.3409。详见 `docs/wsc2-v2-parity.md §6.10` 与
> `_wsc_out/_wsc2_b4_paired.json`。WSC 准则已写入 `AGENTS.md`；几十 token 的边界差
> 按信息保留和回归综合验收，不再反复调参。V2 尚未接入生产，也没有任务成功 A/B。

---

## 0. 一分钟版

- WSC = 把会话前缀压成"给模型看的状态头"。有 **V1（已上线）** 与 **V2（影子，未接管生产）** 两套实现，一个旗标切：`XEYO_WSC_IMPL=v1|v2|shadow`。
- 今天做完的：`B1-a` 分支结论类接进 V2（体积压到 V1 同类的 **0.64×**）→ `B2` 尾部骨架化**判死** → `B3` `[PATHS]` 移植**做完即回溯** → `B4` 提及索引**实装在途、未提交**。
- 今天撤回的：「退场 26 条、误删 0」「整份比 0.6879」「B2 是整份差的主要来源」，以及两次错误归因。
- 当前**唯一待你裁的**：`B4` 要不要收下 —— 它把 V2 的 `path` 覆盖从 0.2719 抬到 **0.8109（超过 V1 头的 0.6613）**，代价是头 **+243 tok/点（超了我先声明的 ≤+200 判死线）**、且每事件成本约翻倍（8.7→16.5 µs，仍与历史长度无关）。三条路在 §7.3。
- 未提交的就是 B4 这一批（4 改 1 新测试，门禁 327 passed / 1 xfailed）；`git status` 里另有两个 `gui/` 文件是**别人的在途改动，别碰**。

---

## 1. 铁律与授权（改引擎前必读）

| 类别 | 内容 |
|---|---|
| 用户裁定（长期） | **「先 B 再 A」**；此后所有改动**可以自由牺牲"压缩那一枪"的前缀命中率**，但**两次折叠之间头必须逐字不变**是硬不变量（破坏它的实测代价 = 每请求贵 2.7 倍） |
| 禁止 | 禁止花钱调模型（除非他明确授权）；**禁止 push**；不许动外来注入路径 `D:\Users\lsn\business\continuous-eval\...`；不许提交别人的在途文件（当前是 `gui/src/components/ActivityLog.tsx`、`gui/src/styles/workflow-split.css`）；不打印 `DEEPAK_API_KEY` |
| V2 边界 | **只做影子**：不删 MAIN/DAG/closure、不改默认生产投影、不接管 model input；保守归约（不明确 ⇒ KEEP，绝不误判 SUPERSEDE/RESOLVE）；v0 不许上 LLM/语义猜测；每阶段带停止条件；"验证而非执行"——实验证伪就当面推翻 |
| 交付纪律 | 每项优化改完立刻测收益，**没收益就回溯不许留**；常数要用多语料最坏 regret 挑；归因前先证明标签没坏；汇报用「问题 → 解决 → 收益」并附"能说什么/不能说什么" |
| 工程门 | 提交前 `pytest tests/wsc tests/wsc2` 全绿（当前 327 passed / 1 xfailed）；tsc/vitest 与本批无关（没动前端） |
| 环境 | 本机时钟不可信；跑 harbour/探针要 `PYTHONUTF8=1`；Windows 下中文 print 走 GBK 会崩（写文件用 `encoding="utf-8"`） |

---

## 2. 架构：V1 链（生产在用）

**文件都在 `python/` 下。**

| 环节 | 文件 | 干什么 |
|---|---|---|
| 触发/尾部 | `engine/compact.py` | `keep_tail_cut()` 定尾部起点（轮原子，从不切半轮） |
| 折叠经济门 | `memory/runtime.py` | `try_extend_c2()`：θ=1 经济门 + 尺寸保底；`c2_cut_index()` pair-safe 切点 |
| 投影入口 | `memory/wsc_projection.py` | `project_c2_messages()`；`:65` `_STATE: dict[str,_Live]` **按 session_id 缓存冻结头**（跨点采样污染之源）；`production_params()` 是生产档唯一配置来源 |
| 装配 | `synaptic/project.py` `synaptic/assemble.py` | `Projection` / `state.frozen_cards`；段渲染 `[CONSTRAINTS]/[UNRESOLVED]/[TODO]/[WORKING SET]/[PATHS]/[REQUESTS]/[MAIN]/[REHYDRATED]/[DECISIONS]/[PRUNED]` |
| 图层 | `synaptic/graph.py` | `build_graph(messages)`：节点 `idx = enumerate(messages)`；refs 四条来源（`:412-422`）＋噪音过滤＋变体归并 |
| 闭包/背包 | `synaptic/closure.py` | 确定性密度贪心，`emitted_tokens()` 按发射成本记账 |
| 主链骨架 | `synaptic/assemble.py:153 _skeleton_of` | 大节点压一行（`inline_max_tokens=48` 是分界） |
| 路径索引 | `synaptic/paths.py` | `[PATHS]`：配额 `path_index_limit=96` / `path_index_budget_tokens=1024`（`synaptic/types.py:300`），形态 = 最短唯一后缀，发射按首次出现升序 |
| 剪枝卡 | `synaptic/prune.py` `synaptic/assemble.py:215 render_decisions` | `[DECISIONS]`（带 error_sig 的卡）/`[PRUNED]`（其余卡，同组合并）；V1 的卡**永不退场** |
| 文件状态 | `synaptic/filestate.py` `synaptic/handles.py` `synaptic/coldstore.py` `synaptic/rehydrate.py` | FileState、句柄表达式、冷层、回灌 |
| 判据原语 | `synaptic/textutil.py` | `tool_input_paths`（**抹盘符**，是键域权威）、`extract_paths`、`command_paths`、`is_noise_path`、`suffix_chain_canonical`、`shortest_unique_suffix`(在 `paths.py`)、`extract_error_sig` |
| 针 | `synaptic/seeds.py:383 harvest_needles` `synaptic/metrics.py:44 needle_survival` | 五类针：`user / error_sig / path / path_recent / failure_site`，**只从被折区收割** |

---

## 3. 架构：V2 链（影子）

`python/memory/wsc2/`：

| 文件 | 职责 | 关键点 |
|---|---|---|
| `events.py` | Event Store（会话 JSONL 行 = 事件） | `first_in_message`；`_norm_path` **委派 V1 的 `tool_input_paths`**（键域同源，#30 的修法） |
| `state.py` | `Fact` / `WorkingState` | `authority` 四档：`AUTHORITATIVE / DERIVED / LITERAL / UNKNOWN`；`obs`（路径级读观测侧账）；**新增 `paths` 触碰账 + `touch_path()`（B4，未提交）** |
| `reducer.py` | 确定性 8 条归约规则 | 保守 KEEP；`_resolve_retried_failure` 两道闸（同 call_id 自解、成功必须晚于失败）；`apply()` 里 FileObserver + `path_touches` 入账（B4） |
| `sources.py` | StateSourceAdapter | `FileObserver`（V1 五条对齐决定）、`v1_file_oracle`、`constraint_signals`、`error_sig`、`decision_signals`、`attach_decisions`、`retire_decisions`（含"同签名仍有未解决失败 ⇒ 不退场"闸）、`path_touches`（B4） |
| `projector.py` | 渲染 | `sections()/render()`；`_file_line`、`_decision_line`、**`_paths_lines`＋`_path_caps`（B4，未提交）** |
| `audit.py` | 离线审计台 | `gold()`、`v1_sections()`、`score()`、`category_flags()` |
| `history.py` | append-only 页 + 行号 locator | `Read(页, offset=行号, limit=1)`，第二级指 Event Store 行号；**1-based** |

**V2 与 V1 的键域/时机一致性**（#30/#32 修完）：路径键必须与 V1 同源且是其不动点；状态点时机（V1 在 tool_result 建表、V2 在 tool_use 建行）已对齐。

---

## 4. 度量基础设施

| 资产 | 地址 | 用途 |
|---|---|---|
| sid 守卫（已接进发车闸门） | `python/evals/wsc_sid_guard.py` | `SidLedger.claim()` 复用 sid 直接 `SystemExit`；`contamination()`、`order_is_stable()`、`require_independent()`；`_sha()` 会掩掉 `offload/wsc/…` 与 `<…>` |
| 守卫回归 | `python/tests/wsc/test_wsc_sid_guard.py`（5 条，变异验证过） | 同一输入在"共用 sid / 唯一 sid"下不等就拒跑 |
| 语料 | `_wsc_out/_ab3_corpus/*.jsonl`（gitignored） | 主用 `sess_real_200turn_c2.jsonl`；126 点＝14 会话 × ≤9 个 tool_result 边界 |
| 厂商账本 | `~/.xeyo/usage/events.jsonl` | `prompt_tokens/cache_hit/cache_miss/cost_cny/session_id/attempt/kind`；口径权威见 `usage/pricing.py:150` |
| 探针（全在 `_wsc_out/`，gitignored） | `_wsc2_b1_parity.py`（B1-a 对账+成本）、`_wsc2_b1_ablation.py`（files 形态消融）、`_wsc2_b1_perline.py`（逐行成分）、`_wsc2_b2_shape.py`（V1 头成分）、`_wsc2_b2_uniq.py`（V2 针域逐段消融）、`_wsc2_b2_qa.py`（**V1 针域逐段消融 + 同预算对照**，带 `X_NO_PATHS=1` 干净消融开关）、`_wsc2_b4_mention.py`（B4 判死量）、`_wsc2_b4_cost.py`（B4 增量代价，**还没跑**）、`_wsc2_v1_remeasure.py`（#43 共用/唯一 sid 双臂） | 复跑：`cd _wsc_out && PYTHONUTF8=1 py -3.11 <name>.py` |
| 文档 | `docs/wsc2-phase1.md`、`wsc2-phase4.md`、`wsc2-phase5.md`、`wsc2-summary-phase1-5.md`（总表，§0 有警告）、`wsc2-v2-parity.md`（**B 阶段主文档，§1–§6.9 最新**）、`synaptic-compression.md`（V1 史） | 数字以 `wsc2-v2-parity.md` §6 为准，旧的以 §0 更正为准 |

**证据等级**：【账单】厂商实付 > 【账本】`usage/events.jsonl` > 【源码】读码 > 【评测-离线】零成本台。
**口径陷阱（每条都踩过）**：发射量 ≠ 厂商请求（差 1.7×）；`fold_events.region_tokens` 是**压缩量**不是 `cache_miss`；比值必须声明聚合口径（逐点中位 / 逐点均值 / 总量比，**不许分量各自取中位再相除** —— 我犯过两次）；`gold["requests"]` 是指纹要还原成字面；比较头要用 `SidLedger` 且一臂一进程。

---

## 5. 已完成进度（带提交号）

| # | 内容 | 结论 | 提交 |
|---|---|---|---|
| Phase 1–3 | V2 事件层/状态层/投影层 + History Index | 召回 1.000；增量 7.9 µs/事件（与历史长度无关） | 见 `docs/wsc2-phase1.md` |
| #31 | V2 文件类复用 V1 `FileState` 语义 + authority 分级 | 4 个字段 **1,087 次比对 100% 对齐**；代价：状态段 +197.5 tok/点 | `wsc2-phase1.md §15` |
| Phase 4 | 传输层（段序稳定 + 差分台账） | **判死**：稳态命中 0.999、miss 中位 197 tok ⇒ 要省的 88 tok/枪是真实请求的 0.2%；T4-1 已回退 | `docs/wsc2-phase4.md §8` |
| Phase 5 | 去噪三臂 | 臂②（按保质期删）**判死**（闲 ≥32 枪仍有 12.8% 事后被再用）；P5-3b 同预算对照替代 | `docs/wsc2-phase5.md` |
| #43 | V1 臂全量重算（每点唯一 sid） | 推翻两条旧结论：**V1 file 召回其实 0.988–1.000**（不是 0.751）；"V2 省一半"实为 **24%** | `wsc2-phase5.md §8–9` |
| B1-a | V1 剪枝卡 → V2 `decision` 事实 + `[EXCLUDED BRANCHES]` | 见 §6.1 | `6367a4e` |
| B2 | 尾部骨架化 | **判死** | `11847d7` |
| B3 | `[PATHS]` 移植（照抄 V1 段） | 做完即**回溯** | `c991be6` |
| B4 | 提及索引（V2 自己的账本 + 配额段） | **实装在途、未提交** | — |

---

## 6. 实验结论（可以直接说的）

### 6.1 B1-a：分支结论类（`docs/wsc2-v2-parity.md §5`）

- 126 点：V1 `[DECISIONS]` 385 行 = **189.5 tok/点**；V2 接成 **377 条事实**，解析失败 0，同键合并 8。
- 体积：初版 237.7（1.25×，负结果）→ 行格式四改后 **121.0 tok/点 = V1 的 0.639×**。构成：结论本体 **91.8** ＋ 字段 26.2 ＋ 换行 2.8 ⇒ **这一段已到地板**（85% 是 V1 卡片结论原文）。
- 四改：删 V1 根本不发射的键前缀；`files`/`err` 按**字面包含**去重（两侧都 casefold）；`err` 截 40；`rows`→`lines=<1-based>`（与 `Read` 的 offset 同口径）。**明确不做**：`files` 只留 basename —— 消融证明只省 0.2 tok/点且行上可指路径 0.793→0.761；干脆不发 `files=` 省 30.2 tok/点（−25%）但覆盖掉到 0.377（那是 V1 记过的事故形状）。
- 逐行：V1 一行 72.2 tok、V2 45.2；V1 每行 **36.5 tok 是句柄表达式**。口径敏感性：本台 offload 路径比生产形状长 2 tok/行（33 vs 31）⇒ 换生产路径比值 0.639→约 0.66，结论不动。
- **B1-a 的收益数字（在 V1 自己的针域，V2 全量头，接前→接后）**：`error_sig` 0.3434→**0.851**、`failure_site` 0.5926→**0.8262**、`path_recent` 0.3721→0.4033。

### 6.2 退场：能力存在，真语料零触发（撤回清单）

- 旧"26 条退场、误删 0"**两半都坏**：误删判据拿"签名最早出现位 > t"，而分支的存在就证明它在 t 之前出现过 ⇒ 恒 0。换两条独立判据（归一化签名重现 / 错误原话字面重现）⇒ 26 次里 **8 次（30.8%）误删**，两判据同数。
- 加一致性闸（同签名仍有未解决失败 ⇒ 不许退场）⇒ **退场次数 26 → 0**。开工单时预告的"验收②误删必须为 0 ⇒ 否则判死"按原话兑现。
- 库里保留带闸版本 + 变异验证过的测试（`python/tests/wsc2/test_decisions_source.py`）。**"V2 会退场"不许写进任何对外材料。**

### 6.3 V1 的头由什么构成（`_wsc2_b2_shape.py`）

- 头中位 2,828.5 tok（均值 2,728.8）；尾部发射中位 3,295.5（原文 3,912）。
- 段 tok/点（中位/均值）：**`PRUNED` 1,494/1,210.1** ← 头的 44%；`MAIN` **0/313.8**；`WORKING SET` 242/294.2；`CONSTRAINTS` 77/202.5；`DECISIONS` 93.5/189.5；`PATHS` 157/167.4；`REQUESTS` 95/162.9；`UNRESOLVED` 43/49.8；`TODO` 0/42.3。
- **`MAIN` 在 85/126 点上是空的**；中间区中位 156 个节点 / 75,799 tok 原文，`MAIN` 只写了 **3.9%** 的节点 ⇒ V1 主链小是因为**丢得多**，不是骨架化得好。
- 比值（逐点中位/逐点均值/总量比）：头比 0.298/0.344/0.377；**整份比 0.742/0.727/0.8407**。补一份 V1 大小的主链只把整份比推到 0.8701（+0.03）。
- ⚠️ 撤回：**整份比 0.6879 作废**（分量各自取中位再相除的算法错误）。

### 6.4 逐段消融（两台台子，结论不同，都得说）

**V2 审计针域**（`_wsc2_b2_uniq.py`，563 根 file+request 针，两臂都算头+共用尾部）：V1 覆盖 542（96.3%）、**V2 563（100%）**。拆段掉针：CONSTRAINTS 36 / REQUESTS 28 / PRUNED 14 / WORKING SET 8 / PATHS 1 / **DECISIONS、TODO、UNRESOLVED、MAIN 全 0**。阳性对照：MAIN 行**单独**覆盖 62 根、27 个点非零 ⇒ "独有 0" 是没贡献不是量具坏。

**V1 自己的针域**（`_wsc2_b2_qa.py`，只评头）：针数 user 547 / error_sig 396 / path 10,505 / path_recent 3,980 / failure_site 702。

| 段 | 拆掉后掉的针 | 受影响点数 |
|---|---|---|
| `PATHS` | **2,609** | 100 |
| `PRUNED` | 2,204 | 89 |
| `REQUESTS` | 360 | 72 |
| `DECISIONS` | 203（error_sig 65＋failure_site 48＋path 90） | 27 |
| `CONSTRAINTS` | 126 | 118 |
| `UNRESOLVED` | 82 | 59 |
| `WORKING SET` | 48 | 22 |
| `TODO` | 1 | 1 |
| `MAIN` | **0** | 0 |

⇒ **每 100 tok 值多少根独有针**：`PATHS` **15.6** ≫ `REQUESTS` 2.2 > `PRUNED` 1.8 > `UNRESOLVED` 1.6 > `DECISIONS` 1.1 > `CONSTRAINTS` 0.6 > `WORKING SET` 0.16 > `TODO` 0.02 > `MAIN` 0。

### 6.5 同预算对照（V2 中位 722 tok ⇒ 只有 700 档真等尺）

@700 tok（V1 / V2，B4 之前）：`user` 0.4424/**0.9031**、`error_sig` 0.649/0.3434、`path_recent` 0.6302/0.1613、`failure_site` 0.4715/0.292。
⇒ 等尺下 V2 **不是"只是更小"**：赢 `user` 一类、输三类。

### 6.6 B3 为什么回溯（`c991be6`）

按 §6.4 把 V1 的 `[PATHS]` 原样移植进 V2，**只关这一段的干净 A/B**：`path`/`path_recent`/`failure_site`/`error_sig` 四项**一字不变**，头 722→750（+28 tok/点）⇒ 撤。
两条原因：① **V2 的 `WORKING SET` 没有条数上限**，PATHS 列的路径全在里面（V1 需要第四通道是因为它的工作集 ≤12 条）；② **池子不同**：V1 的 refs 有四条来源（工具输入、命令、**工具结果文本**、节点正文，`synaptic/graph.py:412-430`），V2 的 `FileObserver` 只记 read/write 工具输入里的路径。②才是 `path_recent` 卡 0.403 的真原因。
顺带纠正一次错误归因：`error_sig` 0.343→0.851 差点被记给 PATHS，两臂同为 0.851 ⇒ 全是 §6.2/§6.1 说的 B1-a 收益。

---

## 7. 在途（未提交）：B4 提及索引 —— 接手从这里开始

### 7.1 改了什么

| 文件 | 改动 |
|---|---|
| `python/memory/wsc2/state.py` | `WorkingState.paths: dict[path → {first,last,fail}]` + `touch_path()`。**不是事实、不需要退场证据**（配额就是它的生命周期） |
| `python/memory/wsc2/sources.py` | `path_touches(e)`：镜像 V1 建图四步（输入＋命令 → 结果文本 → 正文回退 → `is_noise_path` 过滤），归并留给渲染时 |
| `python/memory/wsc2/reducer.py` | `apply()` 里每条事件入账 |
| `python/memory/wsc2/projector.py` | `_paths_lines()` + `_path_caps()`，`[PATHS]` 排在 `WORKING SET` 之后；形态调 V1 的 `suffix_chain_canonical` + `shortest_unique_suffix`；配额读 V1 生产参数；优先级 recent → fail → 其余按最后触碰倒序；发射按首次出现升序 |
| `python/tests/wsc2/test_path_ledger.py`（新） | 5 条：三条来源入账、噪音过滤、**与 V1 `build_graph` 的 refs 池同域（金标）**、配额 + 确定性、失败现场抢位 |
| 门禁 | `327 passed / 1 xfailed` |

### 7.2 实测（`_wsc2_b2_qa.py` 两臂，`X_NO_PATHS=1` 只关渲染段）

| 臂 | V2 头 tok 中位 | `user` | `error_sig` | `path` | `path_recent` | `failure_site` |
|---|---|---|---|---|---|---|
| 关 | 722 | 1.0 | 0.851 | 0.2719 | 0.4033 | 0.8262 |
| 开 | **965** | 1.0 | 0.851 | **0.8109** | 0.9678 | 0.9701 |
| V1 头（对照 2,837 tok） | — | 0.9872 | 0.9823 | 0.6613 | 0.9302 | 0.9630 |

等尺 @700 tok：`path` 0.1029→0.2813、`path_recent` 0.1613→0.3256、`failure_site` 0.292→0.3519，但 **`error_sig` 0.3434→0.2449（被 PATHS 挤掉预算）**。

**读数纪律**：`path_recent`/`failure_site` 的涨幅**半同义反复** —— 这两类针就是 `recent_paths` / 错误节点 refs，而 `[PATHS]` 的 tier 0/1 正是从这两个集合选出来的（V1 自己在 `synaptic/paths.py` 注释里写了"= path_recent 针的集合本身"）。**唯一独立的读数是 `path`（全域 refs）：0.2719 → 0.8109，且已超过 V1 头的 0.6613，而 V2 头只有它的 0.34×。**

### 7.3 判死线兑现情况（不许漂）

开工前报的线：**`path_recent ≥ 0.75` 且 头增幅 ≤ +200 tok/点**。
实测：0.9678 ✓（但该维度同义反复，独立维度 `path` 也过）；头 **+243 tok/点 ✗ 超线 22%**。
⇒ 三条可选路（**这就是要你裁的那一句**）：
1. **收窄配额收下**：把段自身预算压到 ≤512 tok 或 `limit≤64`（V2 池子比 V1 大所以实付超估），复跑到 ≤+200 为止；
2. **按线回溯**（等价于 B3 的处置），把"V2 在同尺寸下 path 覆盖落后"写进对外短板，直接进 A；
3. **保留但改优先级**：让 `error_sig` 那批不被挤掉（把 PATHS 排在 UNRESOLVED/EXCLUDED BRANCHES 之后再吃预算）。

### 7.4 增量代价（`_wsc2_b4_cost.py`，已跑，本机 perf_counter）

| 前缀事件数 | 带路径账 µs/事件 | 关掉路径账 | 净增 | 倍数 |
|---|---|---|---|---|
| 120 | 21.28 | 9.18 | +12.1 | 2.32× |
| 365 | 18.56 | 8.77 | +9.8 | 2.12× |
| 2,466 | 16.47 | 8.67 | +7.8 | 1.90× |

⇒ **B4 把 V2 的每事件成本大约翻倍**（8.7 → 16.5 µs），但**仍然与历史长度无关**（越长的前缀单位成本反而略降），
所以"增量、不被历史拖住"这条 headline **形状不变、常数翻倍** —— 引用时要按这句改口。
绝对代价很小：生产是逐事件增量，一枪新增 ~10 个事件 ⇒ 约 +80 µs；上表是整段重放的口径。

仍欠：B4 提交前需按 §7.3 收窄后**再跑一次 `X_NO_PATHS` A/B** 确认实付 tok/点，并把数字写进
`docs/wsc2-v2-parity.md`（§6.9/§7）。


---

## 8. 不能说的（对外材料红线）

1. 不能说"V2 会退场" —— 真语料 0 触发（§6.2）。
2. 不能说"V2 省一半体积 / 整份 0.69" —— 现在是 **0.742（逐点中位）/ 0.8407（总量比）**（§6.3）。
3. 不能说"V2 召回不如 V1" —— V2 审计针域 V2 反而 100% vs V1 96.3%；只能说"**同尺寸下 V2 在路径/错误签名两类针上落后**"（§6.5）。
4. 不能说"针存活率 = 任务成功率" —— 它是代理指标，V1 文档自己也这么标；"缺这根针会不会做错"**离线测不到**，只有 A 的真负载能答。
5. 不能说 B1-a 的 `lines=a-b` 可取回 —— 本轮 rows 是"V1 行上有没有句柄"的**代理**，可取回性没被证明（任务 #46）。
6. `[DECISIONS]` 在 V2 针域独有贡献为 0、在 V1 针域为 203 —— **一台的"没用"不能替另一台说**，引用时必须带域。

---

## 9. 欠账清单（任务号 → 事）

| # | 事 | 状态 |
|---|---|---|
| #11 | 折叠当枪的厂商实测样本 ≥30 次（现在 12 行 / 1 会话） | pending，要花钱 |
| #17 | 头/尾预算重分配 | 等"帽子"语义修好 |
| #23 | 首压闸仍带 `remaining_turns` | 未裁 |
| #24 | `calibration_events.action` 折叠标签召回 ~2% | 实测缺陷未修 |
| #27 | D10：尾部可超窗口 → 按角色的发射量普查 | pending |
| #46 | A 阶段用真 `frozen_cards` 复测退场触发 + `lines=` 可取回性 | pending |
| #48 | B4 提及索引（本文 §7） | **在途** |
| A 阶段 | V2 状态层并进主链 + 真实负载冒烟 | **需单独付费授权**；停机类动作永不自动执行 |
