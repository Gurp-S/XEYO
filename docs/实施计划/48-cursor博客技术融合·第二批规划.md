# 48-cursor 博客技术融合·第二批优化计划（规划稿）

> 状态：**档 A 已实施；档 C/D 待用户拍板**（本文件为规划 + 实施记录）。
> 依据：`docs/设计/cursor博客的技术融合到XEYO.md`（§三 ⑨⑪、§四 ⑮–⑱、§四·补二 ⑲–㉔）。
> 前提：第一批（`docs/实施计划/46-cursor博客技术融合优化计划.md`）已升格全部优化（⑫ 例外），
> 11 个侧挂模块默认开/可卸载，全套 124 例绿，引擎构建通过。
> 纪律沿用：**每项 = 独立侧挂模块 + 门槛/证明性测试 + 默认关可卸载；只有明确收益才升格主路径；先计划后执行。**

---

## 0. 第二批剩余项总览（按可行性/风险 3 档）

| 档 | 项 | 一句话 | 需要的新设施 | 风险 | 建议阶段 |
|---|---|---|---|---|---|
| **A 无新设施** | ⑰ 检索评测基准 | 在 `evals/` 建 query→期望命中基准，纳入 run-pytest | 无 | 低 | **先做** |
| A | ⑱ 在线 A/B 观测口径 | 只定「采用/追问」埋点口径进 `docs/设计/XEYO评估.md` | 无 | 低 | 顺带 |
| **C 新设施** | ⑯ 语义代码搜索工具 | embedding + 向量库（按 workspace 隔离），复用 codeindex 符号 chunking | **embedding/向量库** | 中高 | **需拍板** |
| C | ⑰ 配语义版 | 若上 ⑯ 需配合建 embedding 基准 | 同上 | 中高 | 跟 ⑯ |
| **D 写路径核心** | ⑲–㉔ Git at any scale | WAL 即真相 / 内容寻址去重 / CAS / provenance | 无（重写核心） | **最高** | **维持推迟** |

已做/无需重复：⑤（报告口径，第一批）、⑮（轨迹重排，第一批已做）。

> **档 A 实施记录（本会话）**：
> - **⑰ 检索评测基准**：新增 `python/evals/retrieval_bench.py`（离线、纯词法、不引 embedding），
>   内置 notes + controlled-code 数据集，跑 `memory.search`（词法）与 `content_index.lookup`（trigram
>   候选超集）的 `hit@k`；新增 `tests/test_retrieval_bench.py`（5 例）。**基线结果**：notes `hit@k=0.4`
>   （自然语言 query 常常不字面命中）、code `hit@k=1.0`（干净字面量文件名可靠命中）。
> - **⑱ 观测口径**：`docs/设计/XEYO评估.md` 新增「五、检索观测口径（⑱）」节（指标/埋点/分档约定），
>   **不改代码**。
> - **验收**：`tests/test_retrieval_bench.py` 5 例 + `test_reporting`/`test_strict_env` 邻域全绿。
>
> **后续（待拍板）**：⑯ 语义搜索（embedding/向量库，档 C）——在本基准上叠加，用于对比 +12.5% 口径。

---

## 1. 档 A — ⑰ 检索评测基准（推荐先做，零新设施、离线）

### 目标
建一个**离线检索基准**（对齐 Cursor `Context Bench`）：一组 `(query, 期望命中的文件/note)` ，评测
当前 XEYO 检索（`memory/search.py` 词法召回 + `codeindex`）的命中率。**不引 embedding**，纯词法口径，
先给出「当前词法召回率」基线——这是整个评估链的地基。

### 落地形态
- `python/evals/retrieval_bench.py`：内置小数据集（query → expected hit），跑 `memory.search` /
  `codeindex` 召回，算 `hit@k`。
- `python/evals/retrieval_data/*.json`：数据集（可先内置少量，后续扩充）。
- 纳入 run-pytest 流程（或作为 `bench_cursor_benefit` 的一个子命令）。
- **先不引 embedding**；只在词法召回上打基线。

### 门槛
- 词法 `hit@k` 可重复、离线、无 API 调用；数据集 query 有唯一预期命中。

### 决策点
- 只覆盖**代码检索**（代码库 query→文件），还是也覆盖**笔记检索**（note query→文件）？
  建议先做代码检索（`codeindex` 符号面）简单、且与 ⑯ 衔接。

---

## 2. 档 C — ⑯ 语义代码搜索工具（唯一彻底新增设施，需先选型）

### 目标
新增**语义代码搜索**（与 Grep/Read 并列、**不替换**词法 Grep），回答「我们在哪里处理 X 逻辑？」
这类问题。复用 `python/codeindex/symbols.py` 的 AST/tree-sitter 符号边界 chunking（函数/类 + metadata：
文件路径/layer/符号名），本地向量库（按 workspace 隔离）。

### 关键选型（需用户拍板）
1. **embedding 来源**：
   - 本地小模型（bge/onnx 等）：离线、零成本、慢、冷启动加载。
   - API（DeepSeek/OpenAI 等）：快、准、要 key、有成本。
2. **向量库**：
   - 内置 numpy/LSH（零依赖、够用、按 workspace 隔离、易于 fail-open）。
   - FAISS（快、重依赖、引入二进制依赖）。

### 纪律（不变）
- **不替换词法 Grep**：新工具与 Grep 并存（P0 词法召回集不变）。
- **fail-open**：向量库/embedding 异常/超限 → 回退词法 `rg` 全量。
- **按 workspace 隔离**：向量索引与 workspace_id 绑定，绝不跨 workspace 泄漏（承接 ⑨ 思想）。
- 默认关、可卸载（`XEYO_SEMANTIC_SEARCH`）。

### 建议
先跑 **⑰ 词法基准**拿到当前词法召回率，再据此评估「值不值得上 embedding」——避免为未量化的收益
背一个重设施。

---

## 3. 档 D — ⑲–㉔ Git at any scale / Continuity（维持推迟）

### 结论（沿用第一批 §B3/§8 诚实分析）
- ⑲ WAL 即真相：触碰 `engine/write_store.py` + `rewind/journal.py` 核心不变量（「每文件单写者 +
  content-hash 校验 + 原子写」、journal 必须先于「视为已提交」落盘）。当前无暴露 bug 逼改（正确性由
  既有原子写保证），侵入深、风险高 → 维持「独立后续波次，先立设计再动」。
- ⑳–㉔ 依赖 ⑲ 的 WAL/内容寻址骨架，一并推迟。
- **只吸收思想**：判定不可用时无条件回退既有全量路径（fail-open），绝不假阴；多 agent 串行点用
  「journal 上的一次原子 CAS」而非进程内锁（设计 28 同向）。

---

## 4. ⑨⑪（小项，收益窄）
- **⑨ 跨工作区作用域守卫**：XEYO 已按 `workspace_id` 隔离（`memdir`/`search`），单用户本地无「跨
  客户端泄漏」面。只吸收「先证明所有权再暴露」原则，映射到扩展层「DENY 优先于 grant」（已由既有
  指纹 v2 + 单向性落实）。**无新增**。
- **⑪ simhash 本地降级**：只对「同仓克隆多份 / 重开后复用索引」有效；单用户本地收益窄。可并入
  ⑧ 的 per-file 缓存已有收益，**暂不单独立项**。

---

## 5. 需要用户拍板（3 件）
1. **第二批启动范围**：(a) 只做 ⑰ 词法检索基准 + ⑱ 口径（无新设施，推荐）；(b) ⑯ 语义搜索一起上
   （引入 embedding/向量库，需先选型）；(c) 维持暂停只留注记。
2. **embedding 选型**（若选 b）：本地小模型（离线零成本慢） vs API（快准需 key 有成本）。
3. **⑰ 基准范围**：只代码检索，还是含笔记检索。

---

## 6. 执行纪律（确认后）
每项按「独立侧挂模块 + 门槛/证明性测试 + 默认关可卸载 + 先计划后执行 + 只有明确收益才升格」。
- ⑰：纯基准模块 + 词法 hit@k 测试；纳入 run-pytest。
- ⑯（若做）：`XEYO_SEMANTIC_SEARCH` 默认关；`semantic_search_shadow.py` + 向量库 + 索引构建后台 job；
  连同 `XEYO_SIDEMOD_PROMOTE` 体系一致（默认关，升格选项）。
- ⑱：仅 `docs/设计/XEYO评估.md` 加观测口径节，不改代码。
