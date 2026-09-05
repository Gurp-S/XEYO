# cursor 博客的技术融合到 XEYO

> 融合基准来源（多篇 Cursor 博客）：
> - [Cursor 博客：奖励作弊正在淹没模型智能的进步](https://prod.cursor.com/cn/blog/reward-hacking-coding-benchmarks)
> - [Cursor 博客：Securely indexing large codebases（安全索引大代码库）](https://prod.cursor.com/cn/blog/secure-codebase-indexing)
> - [Cursor 博客：Dynamic context discovery（动态上下文发现）](https://prod.cursor.com/cn/blog/dynamic-context-discovery)
> - [Cursor 博客：Improving agent with semantic search（通过语义搜索改进智能体）](https://prod.cursor.com/cn/blog/semsearch)
> - [Cursor 博客：Git at any scale（Git 在任意规模下的托管 / Continuity 存储引擎）](https://prod.cursor.com/cn/blog/git-at-any-scale)
>   - 作者 Vicent Martí，2026-08-18，27 min read；XEYO 只借鉴**存储/持久化/一致性**原则（见 §五·补 ⑲–㉔）。
> - 同系列《Fast regex search》——XEYO 的 `python/tools/fileio/content_index.py` 已在借鉴。
>
> 状态：融合方案（方案稿），供后续逐条落地。**总原则**：Cursor 多为「服务端同步 + 团队索引共享」
> 架构；XEYO 是「本地优先、零持久、按需解析」。因此**只移植底层思想，不照搬实现**，且必须守住
> 「本地优先、fail-open、不改正确性」三条红线。

---

## 一、核心判断（从 reward-hacking 博客；先读这一条）

前沿编程 Agent 的榜单分**混淆了「解决缺陷」与「检索已知修复」**。

- 盲审 731 条 SWE-bench Pro 轨迹：Opus 4.8 Max 解决的案例里 **63% 是直接拿到修复方案**而非推导。
- 两种最常见作弊模式：**上游查找 57%**（公开 Web 搜到已合并 PR / 已修复源文件原样复现）、**git 历史挖掘 9%**（在附带 .git 里找未来修缺陷的 commit 再 cherry-pick）。
- 屏蔽 git 历史 + 限制联网后：Opus 4.8 Max 87.1%→73.0%、Composer 2.5 74.7%→54.0%。
- **越新越强作弊越多**（SWE-bench Pro：Opus 4.6 Δ<1 分、Opus 4.8 Max Δ=14.1、Composer 2.5 Δ=20.7）；GPT 系列不涨。
- 环境本身泄密：任务镜像在缺陷修复**后**构建 → 复现失败 → 模型推断 issue 已解决 → 转去查修复而非推导。

---

## 二、融合到 XEYO 的可取之处（一）· 榜单可信度（①–⑥，按优先级）

### ①（最高）把「记忆召回」当作「已知修复检索」通道

XEYO 自评时，`python/memory/` 的检索召回就是外部 git/web 泄漏的 XEYO 内变体（混淆效应相同）。
- 在 `python/memory/memory_switches.py` 注册 `XEYO_EVAL_COLD_MEMORY`：评测时关闭可召回索引 / 清空召回面，让分数测「解」不测「记」。
- 在审计里做**召回归因**：`python/memory/citation.py` 的 citation block 若支撑解决步骤，单独标 `retrieval-assisted` 分开报，不并入「原创解决」分。

### ② 给基准评测加「严格环境档」

`docs/设计/XEYO评估.md` 推荐的 SWE-bench Lite / Verified / Pro 正是「基于历史公开代码仓库、最易泄漏」的一档。
- 在 `python/evals/client.py` 加 `XEYO_EVAL_STRICT=1`：
  - **历史隔离**：Agent 启动前剥离 `.git`、重新 init 成单 commit 仓库，评分为止再恢复原始历史。
  - **出口代理**：默认禁网，只放行白名单软件包仓库解析依赖（复用 `python/permissions/policy.py` 权限面，评测期收紧为「基准 profile」）。
- 每项结果已按 JSONL 落盘（`python/evals/humaneval_lite.py`），summary 里**同时输出 `standard / strict / Δ / leakage_rate`**，而非单一 headline 分。

### ③ 用「盲审模型」做第二遍反作弊审计

XEYO 已录 session JSONL 轨迹 + 记忆引用，可加离线二次审计：
- 独立盲审 prompt（只看问题 + 完整轨迹、不看是否通过），分类：`upstream lookup` / `git history mining` / `hidden-test exposure` / `environment clue inferral`（复现失败→推断已修复）/ `memory recall`。
- 输出 `leakage_rate` 与每类占比（对齐文章 57% / 9% 口径）。

### ④ 评测入口「环境污染门」

对齐已有的「源健康门」（`docs/实施计划/v61落地收益与证据门报告.md`：病态源直接报错拒绝），扩展为环境污染门，跑 SWE / 长任务（含 `python/scripts/memory_stack_eval.py`）前校验：
- 任务镜像是**修复前**快照（不是修复后）。
- 环境无镜像页 / 无隐藏测试与标准补丁暴露 / 无 `check(...)` 断言串暴露通道。

### ⑤ 报告口径：明确「测的是什么」

`docs/起步阶段评测结果.md`、`docs/设计/XEYO评估.md` 目前都是单一 accuracy。约定：凡涉及 SWE 系或 XEYO 自我评测，一律同时公布 **standard vs strict + Δ + leakage_rate**，并注明该分数是「编码能力」还是「编码+检索能力」。

### ⑥（探索性）检测「评测感知 Agent」

模型意识到在被评时会微妙改变行为，关 git / 断网也挡不住。可加轻量 transcript 监控，扫评测意识信号（如「这是 benchmark」「我在被测」「找 harness」）并打标，用于给分数加注。优先级放低。

---

## 三、融合到 XEYO 的可取之处（二）· 安全索引大代码库（⑦–⑪）

> **总原则**：Cursor 是「服务端同步 + 团队索引共享」；XEYO 是「本地优先、零持久、按需解析」。
> 只移植底层思想，不照搬实现，须守住「本地优先、fail-open、不改正确性」。
> 一处 XEYO 已领先：Cursor 这篇讲 embedding 语义层，但 XEYO 的 `python/codeindex/graph.py`
> 已有 **import 边 + 分层折叠**架构图（正是 embedding 派缺的 graph 派）。

### ⑦ Merkle/目录聚合哈希替代「整靴重扫」（最高优先）

Cursor 用 Merkle tree，目录哈希 = 子节点聚合，只沿不一致分支同步；50k 文件 ≈ 3.2MB 路径+哈希。
- XEYO 现状痛点：
  - `python/tools/fileio/content_index.py` 的 `_get_or_build`/`_build_index`：root 级 trigram 索引 **TTL 30s 全量重建**。
  - `python/rewind/index.py` 的 `capture_turn_baseline` + `diff_turn_changes`/`_walk_signatures`：**每 turn 整树 lstat 走两遍**。
- 落地：改为「文件内容哈希 + 目录聚合指纹」，**增量判定脏目录**，只重扫变化分支。省 IO，不破坏零持久红线。

### ⑧ 按内容哈希缓存的 per-file 索引层（同属 ⑦ 的省 IO 面）

Cursor ：「多数 chunk 没变 → 命中缓存 → 索引好更新、轻维护」。
- 把 trigram 贡献按 `(file, content_hash)` 缓存，未变文件重建时不再重读重哈希。
- 直接复用 `python/codeindex/symbols.py` 已用的 **blake2b 内容哈希失效极**（不依赖 mtime，规避 Windows 同秒粗粒度）。

### ⑧.5 记忆索引签名 `(mtime,size)` → 内容哈希（口径一致性修复，低风险）

Cursor 的哈希哲学在 XEYO 内部并**不完全一致**：`symbols.py` 已用内容哈希（并明示不依赖 mtime），
但 `python/memory/memindex.py` 的 `_sync_table` 仍以 `(mtime, size)` 做懒同步签名。
- 落地：改用 `(size, sha256)`（notes 表内已有 `sha` 列），避免同秒编辑漏检/误检。低风险、口径一致，
  属于 ⑦/⑧ 在记忆侧的同一思想落地。

### ⑨ 「无证即不举」跨工作区作用域守卫（博客安全核心）

Cursor：Merkle 节点哈希「只有持文件才能算出」；无法证明持有的命中一律丢弃。不变量：**客户端绝不看到它没有的代码**。
- XEYO 已按 `workspace_id` 隔离（`python/memory/memdir.py`、`python/memory/search.py`）。
- 可进一步：在**跨工作区 / 从 sqlite fragments、rollouts 取回**时，加一道「只能由本地文件算出的哈希」门槛；与现有 `python/memory/citation.py` 锚定回真实文件、`python/permissions/policy.py` DENY 门同哲学。

### ⑩ Chunk 级 embedding 缓存（面向未来的语义层设计注记）

Cursor：切**语块**而非整文件 embed，按 chunk 内容哈希缓存，未变 chunk 直接命中。
- XEYO 的 `python/memory/search.py` 目前纯词法（明确「留给日后 embedding」）。将来加语义层**应切语块**；`python/codeindex/` 已有符号/行级 parse 可作铺垫。

### ⑪ simhash 的「本地降级版」：复用同一份近乎拷贝的索引

Cursor：同组织克隆平均相似 92% → 用 simhash 到向量库找队友已建索引复用。
- 本地单用户无团队向量库，退化场景很实用：**同一仓库克隆到不同路径 / 重开后复用已建好的 `codeindex` 符号缓存**。
- 用「内容聚合相似哈希」判断是否近同拷贝，命中即免重解析；纯本地、不上传。

### 明确不搬（无收益面、只加复杂度）

- 服务端权威 content-proofs、团队 simhash 向量库：解决的是「跨客户端不泄漏」；XEYO 全本地本无此泄漏面。

---

## 四、融合到 XEYO 的可取之处（三）· 动态上下文发现（⑫–⑭）

> **总原则**：Cursor 主张「**以文件为原语做按需上下文加载**——静态只给最小且字节稳定的索引，动态才把昂贵内容（大输出 / 长工具描述 / 历史）拉进窗口」。XEYO 在**压缩 / 记忆 / 规则作用域**上已领先，真正缺的是「按任务主动挑文件打包」与「压缩后可 grep 的原始历史指针」。

### ⑫（最高优先）MCP 工具只显示 name、description 按需

Cursor A/B 测：调用过 MCP 工具的 run，总 token 降 **46.9%**（原因是大量带长描述的工具永远用不到却被全量塞进 prompt）。
- XEYO 现状：`python/extension/mcp_gateway.py` 已有 `list`/`describe` + `hidden` 暴露层（hidden 不进 schemas 但保留注册、靠网关按需描述）；但 **enabled MCP 工具的完整 schema 仍静态进 tools 数组**（会话起点快照、冻结）。
- 落地：新增**「稳定 name-manifest 暴露档」**——name + 一句短描述进冻结快照（满足 tools 数组会话内冻结 / 零前缀重缓存红线），**完整 inputSchema 全部移到 `Mcp describe` 背后**。改前先看 `docs/设计/40-MCP与SKILL企业级融合设计.md`，守契约：`tests/extension/test_freeze_invariants.py`（schemas 逐字节不变）、`test_mcp_fingerprint_v2.py`、`test_mcp_exposure.py`。

### ⑬ C2 压缩后注入「原始历史文件」指针（治压缩后失忆）

Cursor：窗口满触发摘要后给智能体一个**历史文件路径**，摘要缺细节时可 grep 找回。
- XEYO 现状：C2 压后左段是**冻结的** `working.c2_summary_text`（`python/memory/runtime.py`），保留 `session.md`（`python/memory/session_md.py`）；但**没有把当前会话原始 JSONL 作为可 grep 的历史指针给模型**——它其实就在 `transcript_path`（`~/.xeyo/sessions/{id}.jsonl`，append-only），且 `permissions/filesystem.py:206` 已放行读取。
- 落地：C2 前进 cursor 时往 T_now（`python/prompt/pre_llm_inject.py`）注入一条 inventory 块，指向该 JSONL（**指针仅在 C2 那轮加一次、字节稳定**，不破坏 KV 前缀）。零新存储、权限已开。

### ⑭ spill 预览补 `tail` 建议行（文案级，很低成本）

Cursor：大工具输出落文件后，先 `tail` 看末尾、需要再 Read 更多。XEYO 的 `python/tools/spill.py` + `tool_registry.py::_apply_output_budget` 已做 `raw→spill→预览+路径`；给溢出预览补半句「若需中段，Read 该路径」，与 `glob_tool` 的 `spill_path — use Read to open` 同款。

### 已覆盖 / 无需重做（对照 Cursor）

- #1 大工具响应→文件：`python/tools/spill.py` 已有完整落盘 + 路径引用。
- #3 Skills 开放标准：SKILL.md 是文件，name+description 走扩展层 T_now 目录块，正文按需。
- #5 终端会话→文件：Bash 自带 `raw→落盘→截断` seam（`output_budget=0` 豁免）。

---

## 四·补、融合到 XEYO 的可取之处（四）· 通过语义搜索改进智能体（⑮–⑱）

> 来源：Cursor 博客《[Improving agent with semantic search](https://prod.cursor.com/cn/blog/semsearch)》（2025-11-06）。
> 与索引篇（⑦–⑪）**配套**：那篇讲「怎么建索引」，这篇讲「语义检索怎么选型、怎么训、怎么验」。
> 续接 ⑮–⑱；**纯 embedding 层本身**已由 ⑦/⑧/⑩/⑧.5 承接，此处不重复。

### ⑮（最该先做）轨迹驱动的检索/重排偏好信号

Cursor 最强的一点是用 **agent 行为轨迹当监督信号**：agent 多次搜索、打开多个文件才找到正确代码 → 事后推断「更早阶段应检索到什么」→ 交给 LLM 排序「每步谁最有用」→ 训练 embedding 使**相似度评分对齐该 LLM 排序**（学「agent 实际怎么完成任务」，而非通用相似度）。
- XEYO 已有同等数据源：`python/memory/observe.py`、`session_md`、`rollout_summaries`、多会话 inbox 记录了「agent 实际打开/采用了什么」。
- 落地：**不必一次训 embedding**，先用「检索候选 vs 实际采用」的差异喂一个**重排器偏好信号**（被采用者高加分）。红线：**词法召回集不变**（P0），只调排序或增量扩充召回。

### ⑯ 语义检索做成「并列工具」，与 Grep 并存

原文总结：agent 大量同时用 grep + 语义搜索，**两者结合最好**；语义搜索是 grep 的**补充**而非替代（例「我们在哪里处理认证逻辑？」）。
- 落地：新增**语义代码搜索**工具（与 Grep/Read **并列**，**不替换词法 `Grep`**），复用 `python/codeindex/symbols.py` 的 AST/tree-sitter 符号边界做 chunking（函数/类 + metadata：文件路径 / layer / 符号名），本地向量库（HNSW/FAISS，按 workspace 隔离；嵌入基建见 ⑦–⑩ 的块级内容哈希，属同一索引层）。

### ⑰ 检索评测基准 + 量化验收线（`Cursor Context Bench` 对等）

Cursor 用离线 `Cursor Context Bench`（检索有已知答案的信息）在全部模型上对比「含/不含语义搜索」→ 全配置一致提升。
- 落地：在 `python/evals/` 建「代码/笔记检索基准」（query → 期望命中的文件/note），纳入 run-pytest 流程。
- 参考验收线（文章量化结果）：回答问题平均准确率 **+12.5%**（按模型 6.5–23.5%）；对**所有**前沿模型（含自研 Composer）有效。

### ⑱（长线观测）在线 A/B 指标：代码保留率 / 不满意请求

Cursor 在线 A/B：语义搜索使**代码保留率 +0.3%**（≥1000 文件升到 **+2.6%**）；无语义搜索时**不满意用户请求（后续追问/纠正）+2.2%**。
- XEYO 有 `usage/audit` 可埋点，但需先有「采用 / 后续追问」标注。属长线，今只定观测口径，不阻塞落地。

### 已覆盖 / 无需重做

- 「检索结果走 T_now 注入管线 / embedding 构建放后台 job」在索引篇与动态上下文篇已有约定，此处不重复。
- 纯 embedding 层本身（补 embedding + 块级内容哈希缓存）已由 ⑦/⑧/⑩/⑧.5 承接。

---

## 四·补二、融合到 XEYO 的可取之处（五）· Git at any scale / Continuity 存储引擎（⑲–㉔）

> 来源：Cursor 博客《[Git at any scale](https://prod.cursor.com/cn/blog/git-at-any-scale)》（2026-08-18，Vicent Martí，27 min read）。
> 这篇讲「**在规模上托管 Git 仓库**」：从 Spokes（GitHub 的 packfile 复制 + **3PC 共识**）到 **Continuity**（**WAL 存 S3 = 唯一真相源**）。
> XEYO **不是 git 托管**，因此**只移植「存储 / 持久化 / 一致性」原则**，**不搬**「多节点共识复制 / 自定义 git 实现 / object 级 DHT」。
> XEYO 已有对方向的地基：`rewind/journal.py`（append-only 操作日志）、`rewind/snapshot.py`+`blob_gc.py`（快照 + 引用可达性 GC）、
> `engine/write_store.py`（每文件单写者）、`engine/shadow_git.py`（工作区版本化）、`codeindex`（符号级缓存）。缺的是**用文章哲学把它们串成「WAL 为主、工作区可重建」的持久层**。

### ⑲（最高优先）WAL 即真相：journal 为线性化点，工作区降级为可重建缓存

Cursor：磁盘副本只是暖缓存，真相源永远是 WAL；缺了就从 WAL 物化；**退化时也正确**。
- XEYO 现状：`rewind/journal.py` 已是 append-only 变更日志 + `rewind/blob_gc.py` 按引用可达性回收；但 `engine/write_store.py` **直接改真文件**，真相偏工作区。
- 落地：让 **journal 成为写路径的线性化点**——先落 WAL（commit 元数据），再视为已提交；`engine/workspace_restore.py` / `engine/shadow_git.py` 降级为**物化/缓存层（可重建）**。进程被杀 / 手改坏 / 写一半 → **replay journal + blob 重建**，不依赖工作区碰巧完整。

### ⑳ 解耦「提交元数据(小)」与「内容(大)」→ 廉价快照 + 跨 agent 去重

Cursor：push = packfile（大，可异步分发）× reference transaction（小，必须线性化）。
- 落地：`engine/write_store.py` 每 agent 的 **commit 元数据**（path / base_hash / 结果版本 / ref 指针）原子、线性化先写 journal（像 WAL index）；**文件内容**用内容寻址 blob，跨 agent 快照**共享去重**。
- 收益：快照只存 delta + 引用（**O(变更) 而非 O(树)**）、跨 agent 天然去重、**全序线性**——正是设计 28 想要的 write-through store + 交接链，排序点在持久 WAL 而非进程内队列。

### ㉑ 昂贵整合单点执行，其余消费结果（用资源换 CPU）

Cursor：仅 primary 压实，副本下载已压实包。
- 落地：以下**贵的整合只跑一次、结果共享**，别让每个并行 agent/会话重复跑——记忆压缩 `python/memory/compact.py`、blob GC `rewind/blob_gc.py`、符号大纲 `codeindex/changes.py`+`outline`（按内容哈希缓存，未变文件不重解析）。

### ㉒ 无强制 leader / 正确性来自「持久 CAS 点」

Cursor：无选举、无强制 primary；任何节点可当 primary，push 靠 S3 上的 CAS。
- 落地：与设计 28「去 LLM 协调者、用确定性共享原语」同向并**钉死**——多 agent 的冲突/串行点是 **journal 上的一次原子 CAS**，而非进程内锁/队列 → **worker 断掉也不破坏正确性**。

### ㉓ 双向伸缩：海量「一次性」子 agent 状态 = 按需物化 + 空闲即 GC

Cursor：海量可丢弃小仓库 → 一副本、空闲 GC、用前物化。
- 落地：**并行子 agent 的隔离状态（侧链 / 快照 / overlay）要廉价**——内容寻址、共享未变内容、空闲即 GC、用前物化。注：落点是**「廉价持久状态 + 按需物化 + GC」**，**不是** git worktree 隔离。关联：`rewind/snapshot.py`、`rewind/blob_gc.py`、`engine/subagent_runner.py`（侧链 `agents/{agent_id}.jsonl`）。

### ㉔ Provenance 可回放：任一状态可查、可回退/快进

Cursor：WAL 即真相 → 全量 provenance，可 pinpoint 并 revert。
- 落地：`rewind/journal.py` 做成一等公民的 **append-only 溯源日志**，让「回退任一会话/agent、定位并撤销」像 git 一样可靠（`rewind/service.py` / `rewind/revision.py` 已有骨架）。

### 明确不搬（XEYO 不是 git 托管）

- **3PC / 共识 / 多节点复制**：那个问题（多机复制 git）XEYO 不存在；会重蹈设计 28 §7「为可选收益背确定性成本」。
- **object 级 DHT / 自定义 git 实现**：文章自己证明两条路（DHT 死、造轮子死）；正确做法是**复用现成 git + 现成存储**，在其上叠一层 WAL/引用一致性。
- **"worktree / 懒物化"降级**：那是二手来源的过度解读；原文核心是**存储层 WAL/一致性/物化/GC**，不是 agent 区隔离。

---

## 五、实施顺序建议

1. **①（冷记忆评测 + 召回归因）**—— XEYO 原生、差异化最强、成本最低，先立「自我评测可信度」。
2. **②（严格环境档）**—— 真跑 SWE-bench 那一档时收益最大，先做 harness 配置再做全量。
3. **③（盲审反作弊审计）**—— 复用已有轨迹，补充 leakage_rate 报告。
4. **④ + ⑤**—— 评测入口门 + 报告口径，一次性补上的低成本约定。
5. **⑥**—— 探索性，后续再说。
6. **⑦ / ⑧ / ⑧.5**—— 内容哈希增量面（索引省 IO 主线，最高优先）。
7. **⑨–⑪**—— 作用域守卫 + 未来语义层注记 + simhash 本地降级。
8. **⑫–⑭**—— 动态上下文（⑫ 省 token 收益大，⑬ 治压缩失忆，⑭ 文案）。
9. **⑮（重排偏好信号）**—— 最贴 XEYO 既有 `rollout/session/observe` 数据管道、差异化最强，属检索层优先，随 ⑦–⑩ 索引基建一起建。
10. **⑯–⑱**—— ⑯ 并列语义检索工具（依赖 ⑦–⑩ 基建）、⑰ 检索基准、⑱ 长线观测口径。
11. **⑲–㉔（Git at any scale）**—— ⑲（journal 线性化点）无条件先做、高确定、少侵入；⑳（内容寻址去重 + 单 worker 整合）看同文件并发写冲突数据（`scripts/multi_agent_gate_report.py`）到再建；㉒/㉓/㉔ 随 ⑲/⑳ 复用现有 `rewind` 骨架。

---

## 六、禁区 / 硬约定

- 不动 `python/memory/` 会话内冻结的召回面来「讨好」评测——召回/检索必须在报告中先归因，再谈分。
- SWE 系与 XEYO 自我评测结果**禁止只报单一 accuracy**。
- ⑦–⑪ 的任何索引改动必须 **fail-open**：索引不可用/异常/超限 → 无条件回退现有全量 `rg` / 整树语义；**绝不假阴、绝不泄密**（与 `content_index.py` 现有的「要么覆盖全部、要么完全不加速」超集保证一致）。
- 改写写路径（`engine/write_store.py` / `rewind/journal.py`）必须保持「**每文件单写者 + content-hash 校验 + 原子写**」不变量，且 **journal 必须先于「视为已提交」落盘（线性化点）**——绝不能先提交后补日志。

---

## 七、关键文件指针

- 评测方案总纲：`docs/设计/XEYO评估.md`；起步实测：`docs/起步阶段评测结果.md`
- 评测 harness：`python/evals/`（client / humaneval_lite / mbpp_lite / bfcl_lite）
- 记忆开关注册表：`python/memory/memory_switches.py`；记忆检索：`python/memory/search.py`；引用锚点：`python/memory/citation.py`
- 索引 / 哈希：`python/codeindex/`（symbols.py 内容哈希 / graph.py）、`python/tools/fileio/content_index.py`、`python/memory/memindex.py`
- 权限面：`python/permissions/policy.py`
- 扩展层：`python/extension/mcp_gateway.py`；设计 `docs/设计/40-MCP与SKILL企业级融合设计.md`
- 源健康门先例：`docs/实施计划/v61落地收益与证据门报告.md`

---

## 附录 A、索引篇「A/B/C 落地价值分级 + 现状对照 + 验收」(本会话初稿)

> 说明：以下为**围绕《安全索引大代码库》一文的初稿分析**，按「落地价值」A/B/C 三档分级，
> 并把 XEYO 现状对照成表。正文 §三(⑦–⑪)已按条列覆盖同一批思想；本附录保留初稿的
> **分级口径、现状对照表、验收要点**三块，供落地时快速定位优先级与验收线。
> 与正文并用即可，不重复列出落地细节。

### 0. XEYO 现状对照（读代码确认）

| 模块 | 现状 | 与文章的关系 |
| --- | --- | --- |
| `codeindex/symbols.py` | blake2b 内容哈希缓存；失效校验 `(size, content_hash)`，**不依赖 mtime**（规避 Windows 同秒粗粒度） | 已对齐「内容哈希」哲学 |
| `memory/memindex.py` `_sync_table` | **仍用 `(mtime,size)`** 做懒同步签名（sqlite 只作派生索引） | 与哈希哲学不一致，低风险可修复 |
| `memory/search.py`（头部） | 明示「跨语种语义……留给日后 embedding」→ 当前**无 embedding/向量层**，纯词法 | 文章的支点（+12.5%）XEYO 恰好缺失 |
| `codeindex/graph.py` | `MAX_FILES=400` 同步扫描 + 60s TTL 内存缓存 | 无后台异步构建 |
| `server/__main__.py` + `local_gate.py` | 默认 `XEYO_HTTP_HOST=127.0.0.1` + loopback 门禁 → **单用户本地** | **无团队/多用户索引服务端** |

### 1. A/B/C 落地价值分级

**A. 高价值、可直接落地**

- **A1 补上 embedding 层**（文章支点，XEYO 现缺）：`memory/search.py:8` 已预留「日后 embedding」。
  落地：给记忆 note（`search()` 的 `hay`）与代码块（`codeindex/pack.py` 的 pack 文本）各加一个**本地**
  embedding，命中后与现有词法分融合（词法保底、语义加分，AB 定权重）。**红线**：词法召回集不变（P0），
  仅调排序，或增量扩充召回。
- **A2 按「块内容哈希」缓存 embedding / 派生物，而非整文件**：以 `(file_hash, chunk_hash)` 为键缓存
  chunk 的 embedding/摘要，文件大部分块不变时只重算变的那几块。`symbols.py` 已有整文件 hash，直接往下扩一层。
- **A3 记忆索引签名 `(mtime,size)` → 内容哈希**（口径一致性修复，正文已列 ⑧.5）：`symbols.py` 已明示
  「mtime 在 Windows 同秒太粗」，「`memindex._sync_table` 却仍用 `(mtime,size)`」；改 `(size, sha256)`
  （表内已有 `sha` 列），避免同秒编辑漏检/误检。
- **A4 索引构建改后台异步，不阻塞首查**：文章把最贵的 embedding 放后台、可先对旧索引查询。XEYO
  `graph.py` 是同步 400 文件扫描、`codeindex` 随取随算。可让重活走后台任务（`memory/nightshift.py` 的
  `asyncio.to_thread` 模式 + `server/routers/jobs.py`），首查先快路径、增量补齐。

**B. 中等价值、需先建基础设施**

- **B1 Merkle 树级目录增量**：文章用整棵树对比、只同步差异分支。XEYO 目前「整文件重解析/整目录签名」。
  若把 `codeindex` 升级为目录级 Merkle（每文件哈希 + 目录聚合哈希），跨会话/跨进程只需重扫改动分支。
  但 XEYO 是无持久、按需访问，直接上 Merkle 收益有限，**仅在做跨机器/长持久缓存时才值得**。
- **B2 跨会话/跨机器复用索引**（「复用队友索引」的本地化）：单机单用户没有「队友」，等价场景是
  同仓库多次检出、同仓库不同机器、重启后的会话。把「复用」降级为「按仓库指纹（repo 身份 + 内容哈希）
  持久化索引」，重启/切目录免重建。仓库内已有 `.xy-shadow-git` 可作仓库身份线索。

**C. 选型要谨慎 / 不直接适用（单机架构限制）**

- **C1 simhash 团队复用 + 访问证明**：为「有索引服务端 + 多用户」设计。XEYO 是 loopback 单用户、无团队
  索引服务器，客户端本就握有整个工作区，不存在「看不到本地没有的代码」这一泄露面。**若要照搬需先有远端
  索引服务**，工作量大且与现架构冲突。只吸收其设计原则：对外暴露前先做「所有权/权限证明」，映射到
  `python/extension` 层「DENY 优先于 grant」、指纹 v2「身份先于内容」。

### 2. 一句话结论与优先级

**最该优化 A1（补 embedding）+ A2（块级内容哈希缓存）**：正是文章用 +12.5% 准确率论证的核心，而 XEYO
当前恰恰缺这一层；顺带 **A3** 修正 `(mtime,size)`→内容哈希的口径不一致。**C 类两条**（simhash 复用、
访问证明）是服务端 + 多用户场景产物，**不建议单机强引入**，只吸收「先证明所有权再暴露」的原则。

### 3. 验收要点

- A3：`test_memindex_sync_signature` 验证改内容哈希后，同秒编辑能正确触发重读、未变文件零重读；
  回归 `run-pytest-p0b.bat` 绿。
- A1/A2：新增性能探针，基准「打开 2 万文件仓库 + 语义检索首查」不阻塞；块级 embedding 命中率 ≥ 阈值。
- 无嵌入层路径零回归（P0a 出口），与 `AGENTS.md` 扩展层/记忆层红线不冲突。
