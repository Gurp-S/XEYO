# XEYO 交接文档：cursor 博客技术融合（46-48 号）· 本会话全量收益

> 用途：会话上下文即将切换，本文件是**交接提示词 + 全部收益清单**。后续接续时按本文件即可自主继续。
> 生成时间：本会话末。**所有数字、文件、结论均经本会话工具实测，非推测。**

---

## 0. 交接提示词（直接粘贴给下一个会话）

```
继续 XEYO 的「cursor 博客技术融合」工作。请先读：
- docs/实施计划/46-cursor博客技术融合优化计划.md（第一批：11 个侧挂模块 + 升格 + 收益表）
- docs/实施计划/48-cursor博客技术融合·第二批规划.md（⑰⑱⑯⑨⑪⑲ 分档 + ⑰⑱ 实施记录）
- docs/设计/XEYO评估.md 第五节「检索观测口径（⑱）」（我只定了口径，未实施埋点）
- 本文档（交接 + 收益清单）

已完成：11 个侧挂模块默认开/可卸载（⑫ 例外，总开关 XEYO_SIDEMOD_PROMOTE=1）；⑰ 检索基准已升格
（基线落盘 artifacts/benchmarks/retrieval/hitk.json + 回归门禁测试）；⑱ 只定口径未实施。

待办：
1. 【⑱】按「设计讨论」在下方第 5 节——需要拍板①做到哪步②代码保留率判定方式③埋点形态；我倾向
   "代码保留率 + 检索采用率"旁路埋点（默认关、离线可测基线），"不满意请求率"留人工金标阶段。
2. 【⑯】语义搜索（embedding + 向量库）——启动前需定 embedding 来源 + 向量库；可用 ⑰ 的笔记基线
   (hit@k=0.4) 做对比，验证能否达到 Cursor +12.5% 量级。
3. 【⑨⑪】小项，收益窄，多数可并入既有能力。
4. 【⑲–㉔】写路径/WAL，最高风险，维持推迟（需先立设计）。

纪律：每项 = 独立侧挂模块 + 门槛/证明性测试 + 默认关可卸载；只有明确收益才升格；先计划后执行。
红线：不改 write_store/rewind/journal 核心不变量、不改 _schemas_cache、不动 tools 会话内冻结快照。
```

---

## 1. 第一批：升格全部优化（11 个侧挂模块默认开，⑫ 例外）

**目标**：把 `docs/设计/cursor博客的技术融合到XEYO.md` 的优先批（①②③④⑤⑦⑧⑧.5⑫⑬⑭⑮）做成
「独立侧挂 + 收益门槛 + 默认关可卸载」，随后全部升格（⑫ 例外）。

**落地的侧挂模块（11 个）**：
| 模块文件 | 项 | 开关 | 收益/类型 |
|---|---|---|---|
| `python/memory/memindex_sig_shadow.py` | ⑧.5 | `XEYO_MEMINDEX_SIG_HASH` | 同秒编辑不漏检（正确性） |
| `python/tools/fileio/content_index_cache_shadow.py` | ⑧ | `XEYO_CONTENT_INDEX_CACHE` | 省 CPU（未变文件不重算 trigram） |
| `python/memory/eval_cold_memory_shadow.py` | ① | `XEYO_EVAL_COLD_MEMORY` | 评测冷记忆（召回面清空） |
| `python/evals/pollution_gate_shadow.py` | ④ | `XEYO_EVAL_POLLUTION_GATE` | 环境污染门 |
| `python/evals/blind_audit_shadow.py` | ③ | `XEYO_EVAL_BLIND_AUDIT` | 盲审反作弊审计 |
| `python/evals/reporting_shadow.py` | ⑤ | `XEYO_EVAL_REPORTING` | 报告口径（禁单 accuracy） |
| `python/evals/strict_env_shadow.py` | ② | `XEYO_EVAL_STRICT` | 严格环境档（git 隔离+断网白名单） |
| `python/tools/spill_shadow.py` | ⑭ | `XEYO_SPILL_TAIL_HINT` | spill tail 建议 |
| `python/prompt/transcript_pointer_shadow.py` | ⑬ | `XEYO_C2_TRANSCRIPT_POINTER` | C2 原始历史指针 |
| `python/extension/mcp_name_manifest_shadow.py` | ⑫ | `XEYO_MCP_NAME_MANIFEST` | name-manifest（**维持旁路**） |
| `python/memory/rerank_preference_shadow.py` | ⑮ | `XEYO_MEMORY_RERANK_PREFERENCE` | 检索重排偏好（召回集不变 P0） |

**升格基础设施**：
- `python/sidecar/policy.py`：`sidemod_promote()`（默认 True）+ `side_enabled()`（专用 env 优先，否则回退 promote）。
- `python/sidecar/upgrade.py`：`apply()`/`unapply()` 聚合器（`_HOOKED` 列表 = 6 个挂钩型模块）。
- `engine/query_engine.py::build_default_engine`：MCP attach 之后接入 `sidecar.upgrade.apply()`（fail-open）。

**⑦ Merkle 目录指纹 → 留设计注记不实现**（诚实分析）：rewind 已只 lstat、无持久树可跳；content_index
判定未变需 mtime（有假阴风险）或全读（不省 IO）。结论写入 `46` 计划 §B3。

**验证**：全套 **135 例全绿**（侧挂模块测试 + 基础套件 + extension 契约套件 + 引擎构建）；`bench_cursor_benefit.py` 复现升格生效。

---

## 2. 前/后收益对比（实测，`scripts/bench_cursor_benefit.py`）

| 项 | 之前(基线) | 之后(侧挂开启) | 量化收益 |
|---|---|---|---|
| ⑧.5 memindex 签名 | 同秒编辑**漏检** | 同秒编辑命中 | 正确性：不漏检 |
| ⑧ content_index 缓存 | 二建重算 **300 次 / ~370-505ms** | 二建重算 **0 次 / ~54-130ms** | 省 CPU ~86%（非省 IO，已诚实标注） |
| ④ 污染门 | 门关(skip)、污染不拦 | 污染**拦**、干净放行 | 诚实度 |
| ⑤ 报告口径 | 只报 accuracy | 恒含 standard/strict/Δ/leakage | 诚实度 |
| ① 冷记忆 | 常忆召回面=list | 冷忆召回面=[] | 诚实度（测"解"非"记"） |
| ⑮ 重排偏好 | 词法分主导 | 被采用者优先（召回集不变 P0） | 排序收益 |
| ② 严格档 / ③ 盲审 | — | — | 依赖真实模型/agent，离线不可量化 |

> 诚实注记：⑧ 省的是 CPU（未变文件不重算 trigram），**不是**省 IO——要算内容哈希必须先读文件。

---

## 3. ⑰ 检索基准（升格完成）

- `python/evals/retrieval_bench.py`：离线词法基准（不引 embedding），notes（`memory.search`）+ controlled code corpus（`content_index.lookup`）。
- `tests/test_retrieval_bench.py`：8 例（结构、回归门禁、落盘）。
- **基线落盘**：`artifacts/benchmarks/retrieval/hitk.json`。
- **实测基线**：
  - **notes hit@k = 0.4**（2/5）——自然语言中文 query 常不字面命中 → **这正是语义搜索(⑯)要补的缺口**。
  - **code hit@k = 1.0**（5/5）——干净字面量文件名可靠命中（词法已强）。
- **回归门禁**：notes hit@k ≥ 0.2、code hit@k == 1.0（防检索能力回退）。
- **结论**：若上 ⑯，**优先做笔记/语义侧**，而非代码侧（代码词法已 1.0）。

---

## 4. ⑱ 观测口径（已定口径，未实施）

`docs/设计/XEYO评估.md` 第五节：指标（代码保留率 / 不满意请求率 / 检索采用率）+ 埋点前提 +
分档约定（≥1000 文件 vs 小仓库）。**只定口径，不改代码**（⑯ 未启动前不埋在线 A/B）。

**设计讨论要点（见本文件 §0 待办）**：三指标定义；数据来源建议"先人工金标 50-100 条验证自动判定、
再扩全量"；代码保留率可用 `rewind` 现成 diff 自动判定；埋点形态建议独立观测侧挂模块（默认关）。
**待拍板**：①做到哪步 ②代码保留率判定方式 ③埋点形态。

---

## 5. 关键文件清单（改动的）

**新增**：
- `python/sidecar/policy.py`、`python/sidecar/upgrade.py`
- 11 个 `*_shadow.py`（见 §1 表）
- `python/evals/retrieval_bench.py`、`tests/test_retrieval_bench.py`
- `tests/test_sidecar_upgrade.py`、`tests/test_side_modules_offline_guard.py`、`tests/test_memindex_sig_shadow.py`、
  `tests/test_content_index_cache_shadow.py`、`tests/test_eval_cold_memory.py`、`tests/test_pollution_gate.py`、
  `tests/test_blind_audit.py`、`tests/test_reporting.py`、`tests/test_strict_env.py`、`tests/test_spill_shadow.py`、
  `tests/test_c2_transcript_pointer.py`、`tests/test_rerank_preference.py`
- `docs/实施计划/46-cursor博客技术融合优化计划.md`、`docs/实施计划/48-cursor博客技术融合·第二批规划.md`
- `artifacts/benchmarks/retrieval/hitk.json`（基线快照）

**修改**：
- `engine/query_engine.py`（build_default_engine 接线 upgrade.apply()）
- `python/memory/memindex.py`（仅经 side-module 包装，主函数未改）
- `python/memory/memory_switches.py`（注册 `XEYO_MEMORY_RERANK_PREFERENCE`）
- `docs/设计/XEYO评估.md`（新增⑤检索观测口径节）
- 6+4 个侧挂模块的 `enabled()` 回退 `side_enabled()`

---

## 6. 待办 / 下一步（按优先级）

1. **⑱** 拍板后实施旁路埋点（代码保留率 + 检索采用率），先取当前基线。
2. **⑯** 语义搜索（embedding/向量库）——先选型，用 ⑰ 笔记基线(0.4)做对照，验证 +12.5% 量级；红线：不替换词法 Grep、fail-open、按 workspace 隔离。
3. **⑨⑪** 小项（多为并入既有能力）。
4. **⑲–㉔** 写路径/WAL——维持推迟，需先立设计（对照 design/28 确定性共享原语 + rewind 骨架）。

---

## 7. 硬约束 / 红线（后续必须遵守）

- ① 只有明确收益才落地（升格前先「侧挂 + 门槛测试 + 实际复现收益」）；默认关、随时可卸载。
- ② 侧面修改不动主逻辑；侧挂模块同签名包装、fail-open（异常回退原函数）。
- ③ 不动 `python/memory/` 会话内冻结召回面来讨好评测；召回/检索先归因再谈分。
- ④ SWE 系与 XEYO 自我评测禁止只报单一 accuracy。
- ⑤ 索引改动必须 fail-open（异常→回退全量 rg/整树 lstat），绝不假阴、绝不泄密。
- ⑥ ⑫ 必须守扩展层契约：`schemas()` 逐字节不变、指纹 v2、暴露层三层、P0a 零回归。
- ⑦ ⑮ 词法召回集不变（P0），只调排序/增量扩充。
- ⑧ 不改 `write_store`/`rewind/journal` 核心不变量（每文件单写者 + content-hash 校验 + 原子写 + journal 先落盘）；⑲ 需先立设计再动。
