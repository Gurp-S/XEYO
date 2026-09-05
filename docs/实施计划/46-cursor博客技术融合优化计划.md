# 46-cursor 博客技术融合优化计划（独立侧挂 + 收益门槛制）

> 依据：`docs/设计/cursor博客的技术融合到XEYO.md`（方案稿，24 项 ①–㉔）。
> 交付模型（用户三项硬约束）：
> 1. **只有明确收益，才落地到当前代码**——任何项先在「独立侧挂模块」里跑通 + 门槛测试绿 + 实际复现收益，才升格为主路径/默认开；否则保持默认关、随时可卸载。
> 2. **侧面修改，不影响当前代码**——主文件既有函数逻辑不改；侧挂模块以包装方式包裹，与主函数同签名，仅在开关开启时接管。
> 3. **随时卸载加载**——每模块自带 `enabled()` 开关；开=走侧挂逻辑（失败自动回退原函数，fail-open），关=直连原函数逐位不变。
> 本次范围：**优先批** ①②③④⑤⑦⑧⑧.5⑫⑬⑭⑮。**⑥⑨⑩⑪⑯⑰⑱⑲–㉔ 暂缓**；**⑲ 写路径/WAL、embedding/语义层不纳入**（见 §8）。

> **执行状态（本会话）**：
> - **已落地（侧挂模块 + 门槛/证明性测试全绿，默认关、可卸载）**：① ② ③ ④ ⑤ ⑧ ⑧.5 ⑫ ⑬ ⑭ ⑮。
> - **留设计注记、不实现（经实际代码分析，诚实结论）**：⑦（Merkle 目录指纹，见 §B3）。
> - **未做（范围外/依赖 ⑲ 或语义层）**：⑥ ⑨ ⑩ ⑪ ⑯ ⑰ ⑱ ⑲–㉔。
> - **验收**：`py -3.11 -m pytest` 通过（所有侧挂模块 + 各自基础套件 + extension 契约套件 = 114 例全绿）。
> - **侧挂模块清单**：`memory/memindex_sig_shadow`、`tools/fileio/content_index_cache_shadow`、
>   `memory/eval_cold_memory_shadow`、`evals/pollution_gate_shadow`、`evals/blind_audit_shadow`、
>   `evals/reporting_shadow`、`evals/strict_env_shadow`、`tools/spill_shadow`、
>   `prompt/transcript_pointer_shadow`、`extension/mcp_name_manifest_shadow`、
>   `memory/rerank_preference_shadow`。
> - **注意**：所有项均「默认关、随时可卸载」，尚未「升格为主路径/默认开」。升格前提 = 门槛测试已在本地复现 +
>   真实场景复现收益（见各节「升格」）。本次未将任一项目默认开——遵守「只有明确收益才落地」。

> **离线验收（本会话，`py -3.11 -m pytest`，无 API key / 模型 / 网络）**：
> - **守卫**（`tests/test_side_modules_offline_guard.py`，3 例）：6 个挂钩型侧挂模块默认关时
>   `enabled()==False`、`install()` 返回 False、主模块函数未被替换；设开关后 install→uninstall
>   恢复原函数（可随时卸载）。5 个纯函数型模块无 install/uninstall 挂钩面（天然零副作用）。
> - **证明性测试**（11 个侧挂模块 = 62 例）全绿。
> - **基础套件回归**（memindex / content_index / spill / search 邻域 = 32 例）全绿。
> - **extension 契约套件**（freeze / exposure / gateway / reconcile / fingerprint v2 / name-manifest）全绿。
> - **合并全套 117 例全绿**——确认各侧挂模块相互无干扰、未破坏既有冻结/暴露/指纹契约。

> **升格（本会话，全部默认开，⑫ 例外；总开关 `XEYO_SIDEMOD_PROMOTE`=1 默认，=0 一键回退）**：
> - **挂钩型 6 个**（⑧.5 memindex_sig、⑧ content_index_cache、① eval_cold_memory、⑭ spill、
>   ⑬ transcript_pointer、⑮ rerank_preference）：新增 `python/sidecar/upgrade.py`（`apply()/unapply()`）
>   + `python/sidecar/policy.py`（`sidemod_promote()/side_enabled()`）；在 `build_default_engine`
>   （`engine/query_engine.py`，MCP attach 之后）接入 `upgrade.apply()`，沿用 fail-open（单模块失败
>   不挡引擎构建）。
> - **纯函数型 4 个**（④ pollution、⑤ reporting、② strict_env、③ blind_audit）：`enabled()` 改为
>   回退 `side_enabled()`（默认升格；专用 env 显式则优先）。
> - **⑫ mcp_name_manifest 维持旁路**：需实测 token 收益后才接入会话起点冻结快照（红线：不改 `_schemas_cache`）。
> - **验收**：升格后全套 124 例全绿（含新 `test_sidecar_upgrade` 5 例 + 适配 `test_side_modules_offline_guard`）；
>   `build_default_engine(model_backend="fake")` 引擎构建通过；`bench_cursor_benefit.py` 复现升格生效
>   （④ 污染门默认拦、⑧.5 同秒检错、⑧ 零 trigram 重算）。
> - **回退**：`XEYO_SIDEMOD_PROMOTE=0` → 引擎不 install + 各 `enabled()` 回 False，逐位 = 升格前。

> **离线收益对比（本会话，`python scripts/bench_cursor_benefit.py`，无 API key/模型/网络）**：
> 「前」= 基线（默认关/原逻辑）vs「后」= 侧挂开启。
>
> | 项 | 之前(基线) | 之后(侧挂开启) | 量化收益 |
> |---|---|---|---|
> | ⑧.5 memindex 签名 | 同秒编辑**漏检**(True) | 同秒编辑**命中**(漏检 False) | 正确性：同秒编辑不漏检（`XEYO_MEMINDEX_SIG_HASH`） |
> | ⑧ content_index 缓存 | 二建重算 300 次 / 369ms | 二建重算 **0 次** / 53.8ms | 省 CPU：内容未变二建**零 trigram 重算**（`XEYO_CONTENT_INDEX_CACHE`） |
> | ⑮ 重排偏好 | 词法分主导 | 被采用者优先（召回集不变 P0） | 排序收益（`XEYO_MEMORY_RERANK_PREFERENCE`） |
> | ④ 环境污染门 | 门关(skip)、污染不拦 | 污染**拦**、干净放行 | 诚实度：评测前拦污染（`XEYO_EVAL_POLLUTION_GATE`） |
> | ⑤ 报告口径 | 只报 accuracy | 恒含 standard/strict/Δ/leakage | 诚实度：禁止单一 accuracy（`XEYO_EVAL_REPORTING`） |
> | ① 冷记忆 | 常忆召回面=list | 冷忆召回面=[] | 诚实度：评测测「解」非「记」（`XEYO_EVAL_COLD_MEMORY`） |
>
> - **离线不可量化**（依赖真实模型/agent 回路）：②严格档、③盲审。范围外：⑥⑨⑩⑪⑯⑰⑱⑲–㉔。
> - **诚实注记**：⑧ 的收益是**省 CPU**（未变文件不重算 trigram），非省 IO（仍会重读以算哈希）；真正省 IO
>   的路径（持久化 per-root 内容哈希索引）属更大改动，本波不做（见 §B3）。

---

## 0. 通用侧挂契约

```
# <name>_shadow.py  —— 独立侧挂模块（新文件，不改主文件）
def enabled() -> bool: ...            # 开关（env / settings / memory_switches）；默认 False
def wrap_<name>(original): ...        # 返回一个「同签名」的包装函数：
    def _wrapped(*a, **k):
        if not enabled():
            return original(*a, **k)             # 直连原函数（默认路径）
        try:
            return _shadow(*a, **k)              # 走侧挂逻辑
        except Exception:
            return original(*a, **k)             # fail-open 回退
    return _wrapped
```

- **门槛测试（proof test）**：量化收益，或证明诚实性/正确性/契约；绿了才允许升格。
- **升格判定**：门槛测试绿 + 实际运行复现收益 → 把 `enabled()` 默认改为 True（或合并进主路径）；否则保持旁路、默认关。
- **红线**：侧挂逻辑必须 fail-open（异常/超限→回退原函数）；⑦⑧⑧.5 绝不假阴、绝不泄密；⑫ 守扩展层 freeze 契约；⑮ 词法召回集不变（P0）。

---

## 1. 波次与收益门槛总览

| 项 | 侧挂模块 | 包装点 | 收益门槛测试 | 默认 |
|---|---|---|---|---|
| ① 冷记忆+召回归因 | `memory/eval_cold_memory_shadow.py` | `search.search()` 候选装载 | 证明：开=零召回 / 关=逐位一致 / 非评测永不触发 | 关 |
| ② 严格环境档 | `evals/strict_env_shadow.py` | `evals/*` 仓库准备+出口+summary | 证明：git 剥/恢复、断网白名单、summary 含 4 字段 | 关 |
| ③ 盲审反作弊 | `evals/blind_audit_shadow.py` | 独立审计入口 | 证明：合成泄漏轨迹分类正确 + leakage_rate | 关 |
| ④ 环境污染门 | `evals/pollution_gate_shadow.py` | 评测入口 | 证明：拒污染 fixture / 接干净 / 不误伤 | 关 |
| ⑤ 报告口径 | `evals/reporting_shadow.py` | harness summary/print | 证明：恒含 4 字段，无单一 accuracy | 关 |
| ⑦ Merkle 目录指纹 | —（不实现，见 §B3 诚实分析） | — | — | 关 |
| ⑧ per-file 内容哈希缓存 | `tools/fileio/content_index_cache_shadow.py` | `content_index._build_index` | 性能（省 CPU）：未变文件二建零 trigram 重算 / 变更正确失效 / 回退 | 关 |
| ⑧.5 memindex 签名→内容哈希 | `memory/memindex_sig_shadow.py` | `memindex._sync_table` | 正确性：同 mtime 异内容重读 / 同内容零重读 | 关 |
| ⑫ MCP name-manifest | `extension/mcp_name_manifest_shadow.py` | 会话起点 tools 快照组装 | 性能+契约：token 下降 + freeze 逐字节不变 + 暴露层守 | 关 |
| ⑬ C2 原始历史指针 | `prompt/transcript_pointer_shadow.py` | `pre_llm_inject` inventory 块 | 证明：仅 C2 轮注入一次 / 无 KV 前缀破坏 / 未压缩不注入 | 关 |
| ⑭ spill tail 建议行 | `tools/spill_shadow.py` | `spill.save_text` hint | 行为：溢出后含「Read 该路径」，无溢出不变 | 关 |
| ⑮ 检索重排偏好 | `memory/rerank_preference_shadow.py` | `search.search` 打分 | 性能+召回：排序改善 + 召回集逐位不变（P0） | 关 |

---

## 2. Wave A — 评测可信度（收益=诚实度；门槛=证明性测试）

### A1 / ① 冷记忆评测 + 召回归因（S）
- 侧挂 `python/memory/eval_cold_memory_shadow.py`：`enabled()` 读 `XEYO_EVAL_COLD_MEMORY`（默 0）。包装 `search.search()` 候选装载：开启时候选集置空返回 `[]`；开启但非评测上下文→视为关。`citation.py` 加纯函数 `mark_retrieval_assisted(block)`（引用 note 加 `[retrieval-assisted]` 前缀，不写盘、不改结构）。
- 门槛：`test_eval_cold_memory`——开=`[]`；关=`search` 结果逐位=原函数；评测白名单上下文外永不触发。
- 升格：跑「冷记忆 vs 常忆」XEYO 自评，确认分数测「解」不测「记」且无明显削峰，再默认开。

### A2 / ② 严格环境档（M）
- 侧挂 `python/evals/strict_env_shadow.py`：`enabled()` 读 `XEYO_EVAL_STRICT`（默 0）。包装评测仓库准备：剥 `.git`→`git init` 单 commit→评完恢复；出口默认禁网、仅白名单包解析（复用 `permissions/policy.py` 面，评测期收紧为「基准 profile」）；`client.py`/`evals/*` 传入 `strict_tier`。
- 门槛：`test_strict_env`——仓库无历史 git、断网仅白名单可解析、评完原历史恢复、summary 恒含 `standard/strict/Δ/leakage_rate`。
- 升格：真跑一遍 SWE/XEYO 自评，对比 standard vs strict Δ，确认 strict 档有效再默认开。

### A3 / ⑤ 报告口径（S）
- 侧挂 `python/evals/reporting_shadow.py`：包装 harness summary/print——恒输出 `standard/strict/Δ/leakage_rate` + 注明「编码能力」还是「编码+检索能力」；禁止只写单一 `accuracy`。
- 门槛：summary 恒含 4 字段；无单一 accuracy 残留 print。同步 `docs/设计/XEYO评估.md`/`docs/起步阶段评测结果.md` 口径。

### A4 / ④ 环境污染门（S）
- 侧挂 `python/evals/pollution_gate_shadow.py`：包装评测入口——跑 SWE/长任务前校验：任务镜像为**修复前**快照；无镜像页/无隐藏测试与标准补丁暴露/无 `check(...)` 断言串暴露通道；违例即拒（对齐 v61 源健康门先例）。
- 门槛：`test_pollution_gate`——拒污染 fixture、接干净、不误伤既有入口。

### A5 / ③ 盲审反作弊审计（M）
- 侧挂 `python/evals/blind_audit_shadow.py`：独立离线审计（读 session JSONL + 记忆引用）——只看「问题+完整轨迹」不经模型看是否通过；分类 `upstream lookup/git history mining/hidden-test exposure/environment clue inferral/memory recall` + 输出 `leakage_rate`（复用 `evals/client.py` 非流式）。天然不改主路径。
- 门槛：`test_blind_audit`——合成泄漏轨迹分类正确、leakage_rate 合理；无 `DEEPSEEK_API_KEY` 时明确报错。

---

## 3. Wave B — 安全索引省 IO（收益=IO 减少；门槛=性能探针；fail-open 红线）

### B1 / ⑧.5 memindex 签名→内容哈希（S，最低风险）
- 侧挂 `python/memory/memindex_sig_shadow.py`：包装 `memindex._sync_table` 签名比较——`(mtime, size)`→`(size, sha256)`（notes 表已有 `sha` 列，`_sha` 复用）。未变文件零重读、同秒编辑正确触发。
- 门槛（正确性）：`test_memindex_sync_signature`——同 mtime 异内容重读、同内容零重读；邻域回归绿。
- 升格：无性能风险即默认开（纯口径一致修复）。

### B2 / ⑧ per-file 内容哈希缓存层（S/M）→ **已落地为「省 CPU」**
- 侧挂 `python/tools/fileio/content_index_cache_shadow.py`：包装 `content_index._build_index`——trigram 贡献按 `(file, content_hash)` 缓存（blake2b 同 `codeindex.symbols`），未变文件不再**重算 trigram**（省 CPU）。
- **诚实口径**：要算内容哈希必须先读文件，故本层只省 **CPU**（未变文件不重跑 `_trigrams`），**不省 IO**。真正省 IO 需持久化 per-root 内容哈希索引（跨进程），超出本波范围。
- 门槛（性能，证 CPU）：`test_content_index_cache`——未变文件二建 `READ_COUNT=0`；内容变更正确失效；异常→`None` 回退全量 `rg`（fail-open 不变）。
- 升格：探针证明 trigram 重算次数下降、无假阴，再默认开。

### B3 / ⑦ Merkle/目录聚合指纹（M，最大项）→ **留设计注记，不实现（经实际代码分析）**
- 依据：方案稿 `docs/设计/cursor博客的技术融合到XEYO.md` §⑦。
- **为何不做（诚实发现）**：在「不假阴、fail-open、不改正确性」红线下，无法净省 IO：
  1. `rewind/index.py` 的 `capture_turn_baseline`/`diff_turn_changes` 已只 `lstat`（`(size, mtime_ns)`），
     无内容读；Merkle 聚合签名成本 = 现两次整树 lstat 的成本，无净收益，且该路径**无持久树**可跳过
     子分支（每 turn 基线即弃）。改成内容哈希只会让热路径**更贵**；若用签名捷径则有边界漏检
     （假阴）风险，违反红线。
  2. `content_index._get_or_build` 想「跳过整目录重建」需先判定未变；便宜信号只有**目录 mtime**，
     但改动既有文件内容时 Linux 父目录 mtime**未必**变 → 可能假阴（漏检变更）。想不假阴就得
     全量内容读，那就没省 IO。
- **结论**：Cursor 的 Merkle 解决「跨客户端/团队同步」（其架构=服务端+团队索引共享）；XEYO 是
  单机本地、零持久、按需解析，无此问题。只吸收思想：**判定不可用时无条件回退既有全量**
  （`content_index` 顶部已有「要么覆盖全部、要么完全不加速」超集保证）。留作后续波次设计注记，不落地。

---

## 4. Wave C — 动态上下文

### C1 / ⑭ spill 预览补 tail 建议（S，文案级）
- 侧挂 `python/tools/spill_shadow.py`：包装 `spill.save_text` 返回的 `SpillRef.hint`——`full output: <path> (N bytes)` 追加「若需中段，Read 该路径」（对齐 `glob_tool` 同款文案）。
- 门槛：溢出后预览含此提示；无溢出路径行为不变。

### C2 / ⑬ C2 压缩后注入原始历史文件指针（M，治压缩后失忆）
- 侧挂 `python/prompt/transcript_pointer_shadow.py`：包装 `pre_llm_inject`——C2 前进 cursor 时注入一条 **inventory 类** T_now 块，指向 `transcript_path(session_id)`（`~/.xeyo/sessions/{id}.jsonl`，权限已放行）。**仅 C2 那轮加一次、字节稳定**，不破坏 KV 前缀。
- 门槛（证明性）：`test_c2_transcript_pointer`——仅 C2 轮注入一次、未压缩轮不注入、无 KV 前缀破坏、`transcript_path` 复用现成函数。
- 升格：确认压缩后任务可 grep 回原文（恢复率改善）、零回归，再默认开。

### C3 / ⑫ MCP name-manifest 暴露档（M，牵扩展层契约，独立严格验收）
- 侧挂 `python/extension/mcp_name_manifest_shadow.py`：`enabled()` 读 `XEYO_MCP_NAME_MANIFEST`（默 0）。包装「会话起点 tools 快照组装」——开启时只放 `name + 一句短描述`，**完整 `inputSchema` 全部移到 `Mcp describe` 背后**（`mcp_gateway` 已支持）。先读 `docs/设计/40-MCP与SKILL企业级融合设计.md`。
- 门槛（性能+契约，双闸）：①prompt token 下降（A/B 实测）；②`tests/extension/test_freeze_invariants.py` `schemas()` 逐字节不变（会话内冻结/零前缀重缓存红线）、`test_mcp_fingerprint_v2.py`、`test_mcp_exposure.py`（三层 + cap/尺寸/名长截断）全绿；③无网关路径零回归（P0a 出口）。
- 升格：token 下降实测确认 + 契约全绿 + P0a 零回归，再默认开。

---

## 5. Wave D — 检索重排偏好信号

### D1 / ⑮ 轨迹驱动检索重排（M；P0 召回集不变）
- 侧挂 `python/memory/rerank_preference_shadow.py`：`enabled()` 读 `XEYO_MEMORY_RERANK_PREFERENCE`（默 0，注册进 memory_switches）。包装 `search.search` 打分——从 `observe.py`/`session_md`/`rollout_summaries` 提取「被采用/被打开」note 标记，给被采用者加偏好分。**词法召回集不变（P0）**：绝不改 `load_notes_for_search` 候选集；只调排序。
- 门槛（性能+召回）：`test_rerank_preference`——采用 note 高权重排序；开关关时与 `query_reweight` 关时逐位一致；召回集逐位不变；fail-open。

---

## 6. 暂缓项（仅设计注记，不实现）
- **⑥** 评测感知 Agent 检测：探索性，优先级低。
- **⑨** 跨工作区作用域守卫：XEYO 已按 `workspace_id` 隔离，单用户本地无跨客户端泄漏面；仅吸收「先证明所有权再暴露」原则映射到扩展层「DENY 优先于 grant」。
- **⑩⑪⑯⑰⑱** 语义/embedding：本次不做，留 40 号设计侧扩「chunk 级 embedding 缓存」注记；⑰ 检索基准、⑱ 在线 A/B 观测口径留语义层立项。
- **⑲–㉔**：见 §8。

## 7. 禁区 / 硬约定
- 不动 `python/memory/` 会话内冻结的召回面来「讨好」评测——召回/检索必须先归因再谈分。
- SWE 系与 XEYO 自我评测结果**禁止只报单一 accuracy**（Wave A 落实）。
- ⑦⑧⑧.5 索引改动必须 **fail-open**：异常/超限→无条件回退现有全量 `rg`/整树 lstat；绝不假阴、绝不泄密。
- ⑫（Wave C3）必须守扩展层契约：freeze 不变量、指纹 v2、暴露层三层、P0a 零回归。
- ⑮ 词法召回集不变（P0），只调排序/增量扩充召回。
- **所有侧挂模块默认关、可随时卸载**；只有门槛测试绿 + 实际复现收益，才升格为主路径。

## 8. ⑲ 推迟说明（用户点选「推迟」）
- ⑲ 主张「journal 为写路径线性化点、工作区降级为可重建缓存」。现状 `python/engine/write_store.py` 已接近该哲学（`_atomic_write` temp+`os.replace` + `content_hash` 校验 + `journal.record_change`）——但**真相仍偏「工作区」（写真文件），journal 只是审计**（`journal_warning` 仅标记失败不阻断）；`python/rewind/journal.py` 无「先落 WAL 再视为已提交」的严格线性化点。
- 此改动触碰核心不变量（「每文件单写者+content-hash 校验+原子写」、journal 必须先于「视为已提交」落盘），侵入深、风险高，且当前无暴露 bug 逼着我们改（正确性由既有原子写保证）。故放到独立后续波次，先立设计（对照 `design/28 多Agent协同` 确定性共享原语 + `rewind/` 骨架）再动。⑳–㉔ 依赖 ⑲，一并推迟。

## 9. 验收 / 回归汇总
- 每项先「侧挂 + 门槛测试绿」，再「实际复现收益」，才允许升格；每 Wave 结束跑对应邻域回归 + `run-pytest-p0b.bat`。
- 关键针对：`test_eval_cold_memory`、`test_strict_env`、`test_pollution_gate`、`test_blind_audit`、`test_reporting`、`test_memindex_sync_signature`、`test_content_index_cache`、`test_merkle_dir_fingerprint`、`test_c2_transcript_pointer`、`test_rerank_preference`；⑫ 扩 `test_mcp_exposure`。
- 无嵌入层路径零回归（P0a 出口）。

## 10. 假设与依赖
- `evals/` harness 现为 DeepSeek 客户端（无工具回路），Wave A/②「严格环境档」作用于被测仓库历史/网络面；若后续 XEYO 自身 agent 回路参与评测，另立 harness 扩展，不在本次。
- ⑧ 复用 `codeindex.symbols._file_hash`（blake2b）；若签名不适配则在其上包一层，不改其语义。
- ⑫ name-manifest 以「不改 `_schemas_cache` 会话内冻结」为前提。
- 所有侧挂模块默认关，分波次落地；每波先证明收益再升格。
