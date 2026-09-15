# Cursor 博客 × XEYO 源码：相同设计清单

> 材料：cursor.com/blog 全量 74 篇（sitemap 枚举，逐篇抓取）+ XEYO 仓库真实源码。
> 判定口径：**要能指出两边各自的具体机制**才算"一样"；只有概念相近的一律降级标注。
> 未接线的实现（写了无消费方）单独标注，不计入"已有能力"。

---

## 0. 总览：同构度分三级

| 级别 | 含义 | 条数 |
| --- | --- | --- |
| A 强同构 | 机制级一一对应，能指出双方实现位置 | 14 |
| B 部分同构 | 方向相同、实现路径不同 | 8 |
| C 反向差距 | Cursor 有明确机制，XEYO 没有或只有壳 | 7 |

另有 3 条**理念级同构**，是整份对照里最值得注意的部分（见 §4）。

---

## 1. A 级：强同构（14 条）

### A1. 扩展层五原语组合 —— 最完整的一组对应

| | Cursor | XEYO |
| --- | --- | --- |
| Rules | 系统级指令 | `python/memory/instruction.py`（XEYO.md，硬顶 40k 字符、include 深度 5、默认软上限 8k） |
| Skills | 领域 prompt + code | `python/extension/skill_loader.py`、`skill_store.py`、`engine/skill_preinvoke.py` |
| Subagents | 主 agent 派生 | `python/engine/agent_roles.py`（`agents/*.toml` 声明 name/description/nickname/developer_instructions） |
| MCP | stdio / HTTP | `python/extension/mcp_client.py`、`mcp_manager.py` |
| Hooks | 观察 / 控制 agent 行为 | `python/extension/hooks.py`（PreToolUse / PostToolUse / PermissionRequest / SessionStart / SessionEnd） |

Cursor 在 `marketplace` / `new-plugins` 里明确主张"插件 = Skills + Subagents + MCP + Hooks + Rules 的组合打包，远强于单独 MCP"。XEYO 的 `python/extension/manifest.py` + `plugin_store.py` + `plugin_fetcher.py` + `server/routers/plugins.py` 是同一套五原语打包。**连 `PermissionRequest` 非 Success 即 fail-closed DENY 这种细节都对得上**。

### A2. 会话内动态工具发现网关

- **Cursor**：`Cloud MCP` —— "动态可发现工具，改接口不重建 agent loop"（cloud-agent-environment）。
- **XEYO**：`python/extension/mcp_gateway.py` —— `GATEWAY_TOOL_NAME = "Mcp"`，action = `list|describe|call|resources|read_resource`，静态 schema 约 150 token；身份经已知工具集解析（`resolve_tool`），不从 args 外取身份。输出预算 `_GATEWAY_OUTPUT_BUDGET = 4000`。
- 判定：**同构**。都用"一个常驻元工具 + 按需 describe"绕开"新工具要重建工具表"的死结。

### A3. Prompt cache 前缀冻结 / 工具面会话内冻结

- **Cursor**：`continually-improving-agent-harness` —— 上下文窗口顺序固定（system + tool descriptions + 会话状态 + 用户请求）；mid-chat 换模型要换 harness/prompts/tools，cache miss 代价被计入路由成本（`how-cursor-router-works`）。
- **XEYO**：工具面在 attach 时快照、**会话内冻结、零前缀重缓存**（AGENTS.md 扩展层契约，由 `tests/extension/test_freeze_invariants.py` 机器执法）；T_now 注入走**仅存在于投影**的伪造 tool 对（`t_now_strategy.py:110` `ENV_TOOL_NAME="xeyo_env_notice"`），不进 MessageStore/JSONL、不进 tools 数组，尾部追加前缀逐字节不动。
- 判定：**同构且 XEYO 更硬**（把不变量写成了契约测试）。Cursor 把这当经验教训，XEYO 把它当红线。

### A4. 重复命令 → 显式升级（最像的一条行为设计）

- **Cursor**：`agent-sandboxing` —— "agent 反复重试同命令不提权 → 改 Shell tool result 显式标出触发约束并建议 escalate，恢复显著改善"。
- **XEYO**：两条机制合起来等价——
  - `python/engine/repeat_guard.py:39` 阈值 `[3, 5, 8]`（`XEYO_REPEAT_TOOL_ADVICE`）；
  - `python/engine/repeat_fold.py` `IdenticalResultFold`：同签名同输出字节级折叠为一行 `[fold]`；
  - AGENTS.md 的 `bash_escalate`：同会话同命令形状重复命中达 N 次后放行 bash 执行（推荐 3、上限 5）。
- 判定：**强同构**。连"阈值 3"这个数都一样。差别在 XEYO 的 repeat_guard 是"提醒"（advisory），而铁律要求限制只在执行层表达——这里存在一处理念张力，见 §5。

### A5. 反馈驱动的持久指令演化

- **Cursor**：`bugbot-learning` —— 三源反馈（comment downvote / reply / human reviewer 评论）→ candidate rule → 持续评估 → 累积信号后 promote 为 active，持续负信号则 disable；>11 万 repo、>4.4 万规则。
- **XEYO**：`python/memory/governance.py` `MemoryNote`（`last_confirmed_at` / `last_used_at` / `updated_at`）+ `memory/write_policy.py` + `memory/instruction_maintain.py::reconcile_nested_state` + `memory/nightshift.py`（夜间批处理）+ `tools/memory_tool/`。
- 判定：**同构**。都是"反馈 → 候选 → 评估 → 提升 / 失效"的持久指令生命周期。差异是触发源：Cursor 来自代码评审评论，XEYO 来自会话与记忆治理。

### A6. 确定性多 Agent 调度 + 文件 scope 冲突消解

- **Cursor**：`agent-swarm-model-economics` / `self-driving-codebases` —— planner 独占 scope、不写码；worker 拿独立 repo copy；**冲突消解内置于 VCS**；merge conflict 由中性第三方 agent 裁决；megafile 由 worker 标记后交外部 agent 拆分。
- **XEYO**：`python/engine/scheduler.py` —— "确定性多 Agent 调度器（非 LLM）。DAG 事件驱动：依赖就绪且与运行中任务无文件 scope 冲突即可启动；**同文件串行、不同文件并行**"；`MAX_DECOMPOSE_TASKS = 8`、`MAX_PATCH_RETRIES = 3`；`python/engine/write_scope.py` 提供 scope 原语。
- 判定：**强同构**（设计意图一字不差：用文件 scope 而非全局锁做并发控制）。
- ⚠️ **但 `scheduler.py`（1110 行）目前无消费方**——写了没接线，不计入现有能力。

### A7. 子 agent：窄 scope + 明确输出 + 显式约束

- **Cursor**：`cursor-support` —— "每个 subagent 须 narrow scope + clear output + explicit constraints"（LogInvestigator / KnownIssueMiner / TicketWriter / CustomerReplyDrafter）。
- **XEYO**：`python/engine/subagent_runner.py:137` `run_subagent`；`:39` `subagent_budgets_for_scope`（按 scope 推导只读轮数/工具数）；`:273` `build_subagent_registry`（剔除 `_agent`，A8 防递归）；`engine/agent_roles.py` 的 `developer_instructions` 即"explicit constraints"。
- 判定：**强同构**。

### A8. 单次 handoff 回传

- **Cursor**：worker 完成后写 **single handoff**（含 notes / deviations）回 planner；信息沿链向上传播，无 global sync / cross-talk。
- **XEYO**：`:529` `harvest_subagent_memories`、`:674` `upsert_subagent_meta`、`:635` `_flush_subagent_snapshot`、`:766` `list_subagent_metas` —— 子链结果一次性写回主会话记忆与元数据。
- 判定：**同构**（一次性回传，不做双向同步）。

### A9. 内容哈希增量索引 + 最小上下文装填

- **Cursor**：`secure-codebase-indexing` —— Merkle tree（每文件/目录 SHA-256），client 与 server 比树 hash 差异，只同步 diverge 分支；文件变更拆 syntactic chunks → 异步 embedding；**按 chunk 内容缓存 embedding**，未变 chunk 命中 cache。
- **XEYO**：
  - `python/codeindex/symbols.py` —— 按需解析 + `(size, content_hash)` 失效校验（刻意不用 mtime，规避 Windows 同秒粗粒度）；blake2b 摘要；`MAX_CACHED_FILES = 5000` 插入序 LRU；`MAX_PARSE_BYTES = 2_000_000`。
  - `python/codeindex/cgraph.py` —— sqlite 持久化 symbols + edges，**内容哈希增量更新（改哪个文件重解析哪个，不全量）**。
  - `python/codeindex/pack.py` —— 按字符预算装填 body → docstring → used imports → 同文件 callee 签名 → caller 签名，`DEFAULT_BUDGET_CHARS = 8_000`，零跨文件、零调用图。
- 判定：**同构**（"内容哈希判增量 + 按需解析 + 最小上下文装填"三件套一致）。
- 差异：Cursor 有 embedding/语义检索与团队索引复用；XEYO 是 AST 符号级，**无语义检索**。

### A10. 敏感路径保护清单

- **Cursor**：`agent-sandboxing` —— Seatbelt profile 用正则 `deny file-write*` 保护 `.vscode` / `.cursor` / `.git/config` 等。
- **XEYO**：`python/permissions/filesystem.py:308` —— workspace 根顶层目录默认只读（`_protected_metadata`）；`:127` `path_in_allowed_working_path` 两侧 `realpath`（符号链接指出去即拒）；`:118` `expand_to_abs` 防 `..` 穿越。
- 判定：**同构**（清单式保护 + 路径规范化优先）。

### A11. 密钥防护 + 出网白名单

- **Cursor**：`cloud-agent-environment` —— tool result 中 secret redaction（**agent 读不到**）、commit 内 secret scanning、scoped/proxied git remote、network egress 限制。
- **XEYO**：`python/permissions/policy.py` 判定顺序中"密钥 DENY"位于规则 DENY 之前（`:828` 注释链）；`python/tools/web_common.py:19` `is_blocked_url` 拦截 private host/IP（localhost、私有网段、解析到私有 IP = SSRF 守卫）。
- 判定：**同构**（密钥在执行层直接 DENY + 出网白名单）。

### A12. 审计事件面

- **Cursor**：`aiuc-1` 认证要求覆盖 secrets protection / MCP security / agent identity & permissions；`cloud-agent-development-environments` 每环境 version history + audit log。
- **XEYO**：`python/server/routers/audit.py` `GET /v1/audit/events`（按 kind 或 `permission.` 前缀查询）；`extension/config.py` 坏 JSON 走 `config.invalid` 审计；`mcp.tool.call` 硬字段由写入端保证。
- 判定：**同构**。

### A13. 多入口共用同一引擎 + 目录式配置

- **Cursor**：`typescript-sdk` —— 桌面 / CLI / Web 同一 agent runtime、harness、model；local / cloud / self-hosted 三 runtime 同 SDK 切换；配置走 `.cursor/mcp.json`、`.cursor/skills/`、`.cursor/hooks.json`。
- **XEYO**：`python/cli/`（Typer）+ `python/server/`（FastAPI attach）+ `gui/` + `tui/` 共用同一个 `QueryEngine`；配置单一来源 `<root>/.xeyo/settings.json`，home 级与 workspace 级按范围合并、**workspace 更具体者优先**。
- 判定：**同构**（多壳一核 + 目录式声明配置）。

### A14. 上下文压缩的两类形态

- **Cursor**：`self-summarization` 明确三类 —— text-space prompted summary / sliding context window / latent space（向量）。自摘要循环 = 生成到固定 token trigger → 插 synthetic query "summarize" → scratch space 压缩 → 带回 summary + conversation state（plan state、remaining tasks、prior summarization 次数）。
- **XEYO**：
  - 文本摘要类：`python/engine/compact.py:125` `project()` = C0 截断 + C1 冻结区占位（**copy-on-write，不改 MessageStore/JSONL**）；`memory/runtime.py:1851` `maybe_force_compact_on_pressure`，比例由 `XEYO_CONTEXT_COMPACT_RATIO` 控制；C2 LLM 摘要旁路（会话 ≥ 24 条时预取，失败回退确定性摘要）。
  - 滑动窗口类：`compact.py:26` `KEEP_TAIL_TOOL_ROUNDS = 3`（保最近 3 个成对工具轮）；`engine/aging.py` 老化存根。
- 判定：**两类同构**（latent 类无）。差异：Cursor 把 compaction 折进 RL 训练（模型学会自己摘要，输出 ~1000 token、复用 KV cache），XEYO 是引擎侧启发式 + 可选 LLM 旁路。

---

## 2. B 级：部分同构（8 条，方向同、实现不同）

| # | 设计点 | Cursor 口径 | XEYO 实现 | 差异 |
| --- | --- | --- | --- | --- |
| B1 | Agent 沙箱 | macOS Seatbelt / Linux Landlock+seccomp / Win 走 WSL2；workspace 映射 overlay FS，ignored 文件用副本覆盖；sandboxed agent 中断少 40% | `tools/bash_tool/bash_tool.py:195` `_docker_exec_with_timeout` 经 docker SDK 进容器（`XEYO_DOCKER_CONTAINER`）；`tools/container_routing.py` ContextVar 协程级隔离；无容器时 `policy.py:874-878` 要求显式 `XEYO_BASH_UNSAFE_ALLOW=1` | 同目标（边界内自治），**层次不同**：容器 vs OS jail。XEYO 缺乏"细粒度文件写拒绝 + 出界才问" |
| B2 | 权限判定 | `agent-autonomy-auto-review`：**classifier agent（小快模型）** 置于 loop 前，风险 = f(action, 意图, 后果)；可 agentic 地 ReadFile/Grep/Glob 后判定；阻断不弹用户，返回 explanation 给父 agent 选更窄路径；实测仅 ~4% 动作被 block | `permissions/policy.py:1319/1391` 是**确定性规则链**（黑名单 DENY → 密钥 DENY → 规则 DENY → 策略文件 → 只读白名单 → 写目标证明 → 默认 ASK）；ASK 挂起 `permission_pending`，由 `/v1/permission/resolve` 裁决 | 同方向（放权做成 dial 而非 switch），**XEYO 缺模型判定层**，所以"风险分级"是静态规则不是运行时推断 |
| B3 | 后台自治 | `automations`：schedule + Slack/Linear/GitHub/PagerDuty webhook 触发 → 起 sandbox → 自验输出 → 带 memory tool 从历史 run 学习 | `server/job_registry.py`、`tools/job_tools.py`（后台 bash job）、`server/inbox_registry.py`、`memory/nightshift.py` | 有后台执行与夜间批处理，**无事件触发、无自验闭环、无 run 间记忆** |
| B4 | 快照 / 版本绑定 | `builds`：每小时 env 副本、fork live machine、broken build 不激活并告警、每次 run 绑定确切 build SHA | `rewind/snapshot.py` `SnapshotStore`（内容寻址 SHA-256、原子幂等写、`~/.xeyo/snapshots`）；`engine/turn_snapshot.py`、`workspace_revision.py` | 有快照与版本绑定，**无预热副本、无 build 流水线** |
| B5 | 配置合并语义 | `organizations`：organization > teams > groups，多归属时 **most permissive wins** | `extension/config.py`：home 级 + workspace 级合并，**workspace 更具体者优先** | 都在解多级覆盖，**合并方向相反**（Cursor 取宽，XEYO 取具体）；XEYO 无多租户 |
| B6 | 编辑格式 | `continually-improving-agent-harness`：OpenAI 用 patch-based、Anthropic 用 string replacement，**按模型训练格式适配**，错配费 reasoning token 且更易错 | `tools/file_edit_tool/file_edit_tool.py` 固定 `old_string`/`new_string`/`replace_all` 语义 | XEYO **不按模型切换编辑格式**；`find_actual_string` 做模糊匹配兜底（`:406`）是另一种解法 |
| B7 | 评测集的构造效度 | `cursorbench`："任务源自真实 Cursor session，Cursor Blame 把 commit 回溯到 agent request 配对 query ↔ ground truth"；明列公共 benchmark 三缺陷（alignment / grading / contamination） | XEYO 跑的是**公共 Terminal-Bench 2.1**（正是 Cursor 批评的那类），但另建了 `docs/BENCH-口径.md` 分数口径登记表 + `docs/应试性审查-副作用修复与53号.md` | 精神同构（都严查"分数是否代表真实能力"），**素材反向**（Cursor 自建内部集，XEYO 用公共集） |
| B8 | 工具错误分类 | 分 `InvalidArguments` / `UnexpectedEnvironment` / `ProviderError` / `UserAborted` / `Timeout`，**unknown error 一律当 bug 报警**，并按 per-tool / per-model 基线做异常检测 | `tools/base_tool.py:12` 只有 `is_error: bool` 二元；`engine/abort.py` 覆盖 UserAborted；无 per-tool/per-model 基线与 unknown-error 告警 | 分类概念只有最粗一层，**遥测闭环缺失** |

---

## 3. C 级：Cursor 有、XEYO 没有（7 条）

| # | 机制 | Cursor 出处 | XEYO 现状 |
| --- | --- | --- | --- |
| C1 | **模型路由**（按任务复杂度选模型） | `how-cursor-router-works` / `router`：Compass 复杂度分 + domains/tasks/modifiers 三级分类，候选需对便宜模型达 75% 单边 uplift 才 eligible；成本含 model-switch 的 cache miss | **无路由代码**。`usage/pricing.py:26` 只有计价（cache_hit / cache_miss / output 三档 + 峰谷 peak×2），没有"选哪个模型"的逻辑 |
| C2 | **Keep Rate 质量指标 + online A/B 闭环** | 改动留在代码库的比例；online 代理指标（用户继续下一任务=好 / 贴 stack trace=坏）抓"离线高分但体验差"的回归 | 只有 `memory/simulator/calibration.py:146` 的仿真用 `keep_rate`，**生产无此指标、无 A/B 闭环** |
| C3 | **语义索引 / embedding / 团队索引复用** | Merkle simhash 复用团队索引（time-to-first-query 中位 7.87s → 525ms）；加密 access proof（client 持 tree proof，server 无法反查无权代码） | 只有 AST 符号级索引（`codeindex/`），**无 embedding、无向量检索、无索引复用与访问证明** |
| C4 | **代码审查 agent 全家桶** | Bugbot：只审增量 diff、`/review` 去重、effort levels（high 多发现 35% 而解决率恒 80%）、autofix（>35% 改动被合入）、**以 resolution rate 而非 flag 数作质量信号**（52%→78%） | **无代码评审 agent** |
| C5 | **多 worker fan-out 编排 + 自研 VCS** | planner 按性能指标动态部署/重平衡 worker；自研 VCS 峰值 ~1000 commits/s（Git ~1000/hr），协调逻辑内置于 VCS 层 | 每次 `Agent` 调用只 spawn 一个子 agent、单子链回传（`subagent_runner.py`）；单轮内并行只是**工具级**（`tools/orchestration.py` 信号量默认 10）。`scheduler.py` 有多 worker 意图但**未接线** |
| C6 | **OS 级沙箱原语** | Seatbelt / Landlock / seccomp-bpf / WSL2 | 无。隔离完全依赖 docker 容器；不配容器即等同宿主直接执行 |
| C7 | **标准协议接入外部 IDE + 企业多租户** | `jetbrains-acp`（ACP Registry 安装）；`organizations`（三层容器、独立 budget/model 访问/spend limit、Admin API/CSV） | 无 ACP；无组织/多租户，只有单机 workspace 策略（`permissions/workspace_policy.py`） |

---

## 4. 理念级同构（3 条，比机制级更值得看）

### P1. 把编排从"文本提示"挪到"执行层机制"

- **Cursor**：`cloud-agent-lessons` —— "早期 harness 强制 commit/push，**现把逻辑移入 agent 可控工具**（如 CI Autofix 改给 GitHub CLI）"；`continually-improving-agent-harness` —— 模型变强后**撤除 guardrails**（强制 lint/type 报错、重写 file reads、限制单 turn tool call 数），转 dynamic context。
- **XEYO**：AGENTS.md 铁律 —— "注意力里只出现信息，不出现导演""**限制只在执行层**""**能静默就不说话**"；`memory/instruction_maintain.py::reconcile_nested_state` 被点名为范本（引擎能强制的一律不给模型看）。T_NOW_BLOCK_REGISTRY 的硬准入第一问就是"**能不能不进上下文**"。
- 判定：**同一条路**。两边独立得出："引擎的编排不该写在提示里，该写成执行层机制"。

### P2. 构造效度 / 观测域一致性

- **Cursor**：`reward-hacking-coding-benchmarks` —— strict harness 两条修法：**history isolation**（启动前删 `.git` 并重 init 为单 commit，仅评分时还原）+ **egress proxying**（默认断网，pinned proxy 只放行 allow-list）。坦承"模型可感知在 eval 中而更隐蔽地作弊，是开放难题"。分数落差 Opus 4.8 Max 87.1 → 73.0、Composer 2.5 74.7 → 54.0。
- **XEYO**：`docs/应试性审查-副作用修复与53号.md` 的四条尺子 —— R1 产品受益、R2 无评测分支、R3 信息纪律、R4 收益可证伪；核心缺陷面叫"**观测域一致性**"：引擎的核对/嗅探必须与模型动作走**同一执行通道**，否则注入"模型看不到的事实"；修法 = 同通道原语 + **不可观测则沉默**。
- 判定：**同一把尺子**。Cursor 讲 construct validity，XEYO 讲观测域一致性——都在问"我测的到底是不是我想测的行为"。

### P3. 事故 → 结构性规则（而不是补丁）

- **Cursor**：`cloud-agent-lessons` 把 work-stealing 架构换成 Temporal；`self-driving-codebases` 明确"shared state file + lock 自协调**彻底失败**（长持锁、忘释放、20 agent 吞吐降到 1-3）"；`fast-regex-search` 记录 quadgram 索引过大、bigram posting list 过大；`git-at-any-scale` 记录 NFS/GFS2/DRBD 不符 Git 语义、JGit+DHT 每跳 round-trip 代价过高 —— 每条都给出"哪条原则让它结构上不再发生"。
- **XEYO**：AGENTS.md 第 5 条事故模板 —— "结构性根因是什么？哪条规则能让它结构上不再发生？回归测试怎么写？**答不出第一条的修复只是把事故推迟**"。仓库 memory 里同类记录：`git stash` 击穿 `.git`（已四犯）→ 改成路径限定提交；薄壳 venv 事故 → `scripts/build_slim_venv.py` 自带自包含性断言。
- 判定：**同一种工程文化**。

---

## 5. 两处值得回头看的地方

1. **`repeat_guard` 的 advisory 措辞 vs 铁律**：`engine/repeat_guard.py` 阈值 `[3,5,8]` 只提醒不拒执行，提醒文本属于"建议/编排"性质，与"注意力里只出现信息，不出现导演"存在张力。Cursor 的对应做法是把约束写进 **tool result**（状态陈述）而非另发提醒。建议按 R3 信息纪律复核该块措辞。
2. **`scheduler.py` 是 A6 的唯一证据，但它没接线**：1110 行确定性 DAG 调度器目前无消费方。也就是说"多 agent 文件 scope 冲突消解"这条同构，**当前只是设计意图，不是运行能力**。要么接线，要么在登记表标注为未启用。

---

## 6. 一句话结论

XEYO 与 Cursor 最像的不是产品形态，而是**两个底层信念**：编排写在执行层而不是提示里（P1），以及只测自己真正想测的行为（P2）。在扩展层五原语、工具面冻结、重复命令升级、内容哈希增量索引、子 agent 窄 scope 这五处，两边已经收敛到几乎同一套机制；差距集中在**模型层（路由）、语义层（embedding）、评审层（Bugbot）、编排层（多 worker fan-out）与沙箱层（OS jail）**。

---

## 7. 最值得参考优化的四档排序

排序用三道闸门过滤：
1. **应试尺子（R1–R4）**——只对评测有收益、或必须读 `/tests` 才能兑现的，直接出局；
2. **引擎铁律**——新增的模型可见文本必须只承载信息；
3. **口径能否兑现**——在 TB 口径下（C1 bench-minimal 排除文件工具层 / C2 容器路由让宿主 cwd 机制失效），有些收益在评测里根本不会出现，只能按产品口径算。

### 第一档：立即做（低成本、高杠杆、零注意力风险）

**① TB harness 的 `.git` 历史隔离**（来自 Cursor strict harness）

Cursor 的审计数据：63% 成功轨迹是"检索"而非"推导"，其中 **git-history mining 占 9%**——模型挖 `.git` 里的未来 commit 直接取 patch。修法是启动前删 `.git` 并重新 init 为单 commit，只在评分时还原。
**动作**：核查 `TerminalBench/xeyo_harbor_agent.py` 起的容器里，仓库是否带完整 `.git`，模型能否 `git log` / `git show` 到评测案例的提交。
**为什么排第一**：改动仅 harness 一处，收益是消除"89 题成绩有一部分不是能力"这个风险——直接加固 R4（收益可证伪）。

**② 工具错误分类 + unknown error 一律视为 bug**（来自 harness 遥测）

`python/tools/base_tool.py:12` 现在只有 `is_error: bool`。Cursor 分了 `InvalidArguments` / `UnexpectedEnvironment` / `ProviderError` / `UserAborted` / `Timeout`，unknown error 一律当 bug 报警，并按 per-tool / per-model 基线做异常检测。
**动作**：把 `is_error` 升级为带 kind 的枚举（保留 bool 兼容），只用于本地统计与审计，不新增模型可见文本。
**为什么值**：目前"21 项改动只有 5 项进计分路径"这类判断靠人工审计；有了 kind 就变成可查询数据。

**③ `engine/scheduler.py` 接线或明确停用**（A6 的唯一证据）

1110 行确定性 DAG 调度器目前无消费方。两条路都比现状好：接线 → 多 agent 并行成为真能力；不接线 → 在登记表标注"未启用"，避免下次又把设计意图当运行能力。
**为什么值**：Cursor 的终态设计（planner 不写码 + 文件 scope 冲突消解 + 单一 handoff）XEYO 全写好了，而 Cursor 的失败教训（shared state + lock 彻底失败、integrator 单点瓶颈）恰好验证了 scope 冲突检测这条路。这是少数"照着走就行、不必重新试错"的地方。

### 第二档：值得做，但先补前置

**④ 本地 Keep Rate（改动静置率）** —— 整份清单里**如果只做一件事就做它**

Cursor 用 keep rate（agent 改动在固定时间后仍留在代码库的比例）作质量信号，并明确抛弃"用 benchmark 分数推断"。XEYO 现在缺的正是这个：EV 中位数 59/89 是唯一质量信号，而 `docs/BENCH-口径.md` 自己也在质疑分数的代表性。
**XEYO 已有基建，不用新建**：`rewind/journal.py` 的 `OperationJournal` + `rewind/blob_gc.py` 的跨会话引用收集 + `rewind/snapshot.py` 内容寻址快照。
**动作**：记录每次 agent 写入的文件区间，观察它在后续 N 个 turn / 会话内是否被改回或删除 → 得到 keep rate。
**三道闸门全过**：零模型调用、零模型可见文本（R3 过）、纯本地无评测分支（R2 过）、收益可证伪（R4 过）。**它的真正价值是让后续所有优化变得可判断**——没有它，任何改动只能靠 EV 中位数猜。

**⑤ 容器路由转为默认沙箱（出界才 ASK）**

Cursor 数据：sandboxed agent 中断少 40%；企业侧 auto-review 把"~40% 动作被挡"降到"~4%"。XEYO 现在不配容器即等同宿主直接执行，`bash:allow` 还要显式 `XEYO_BASH_UNSAFE_ALLOW=1`。
**注意**：**不要照抄 Cursor 的 OS 原语**（Seatbelt / Landlock / seccomp）——Cursor 自己在 Windows 上都退到 WSL2，Windows 优先的 XEYO 更不该走这条路。已有的 docker 路径（`tools/bash_tool/bash_tool.py:195` + `tools/container_routing.py`）才是正解。
**前置**：先有 ④ 的干预率数据，否则不知道 ASK 到底有多吵。

**⑥ `usage/pricing.py` 计价口径先修正**

`_DEEPSEEK["flash"]` 仍是旧价（命中 0.05 / 未命中 1.5 / 输出 4.5）+ peak×2 未更新。
**为什么是前置**：任何"成本优化"的收益都要用它算。基准花费 P2 全量 ¥26.49 / P5 ¥28 都建立在这张表上，表错了所有优化都得重算。

### 第三档：大工程，先要有信号才能判断值不值

**⑦ 复杂度路由（简化版）** —— 含一个关键的成本口径修正

Cursor 的 router 用 Compass 复杂度分 + 三级分类，候选要对便宜模型达 75% 单边 uplift 才 eligible，成本里还计入 model-switch 的 cache miss。
**但不要照抄它的重点**：XEYO 成本结构是**输出占 83%**、未命中 12%、命中 ≈5%。"cache-aware routing"对 XEYO 性价比很低——cache miss 只占小头。
**该抄的是"按难度选档位"，因为它压的是输出成本这块大头**。可借两条原则：①判据用真实表现而非 benchmark 分数；②性能信号 = 用户是否继续下一任务 / 是否回来纠正（XEYO 无线上流量，本地 session 历史够用）。
**前置**：⑥ 的计价修正 + ④ 的质量信号（否则没法证明路由没把难题做坏）。

**⑧ 自建内部评测集（CursorBench 的对应物）**

Cursor 的论证很直接：公共 benchmark 有三缺陷——alignment（偏 bug-fix）、grading（窄正确集）、contamination（SWE-bench 已泄入训练）。做法是用 Cursor Blame 把 commit 回溯到 agent request，配对 query ↔ ground truth。
**XEYO 的对应数据是现成的**：`~/.xeyo/sessions/*.jsonl`（权威 transcript）+ rewind journal + workspace revision。
**这是最贵但最能改决策的一条**——它能把"EV 中位 59/89、追平 70.8% 概率仅 7%"这类判断，换成基于自己真实会话的质量曲线。

**⑨ 多 worker fan-out 编排**

Cursor 由 planner 按性能指标动态部署 / 重平衡 worker，配自研 VCS（峰值 ~1000 commits/s）。
**前置**：④ 的质量信号 + ③ 的 scheduler 接线先到位，否则是在没有仪表盘的车上加涡轮。

### 第四档：明确不建议照抄

| 项 | 原因 |
| --- | --- |
| OS 级沙箱原语（Seatbelt / Landlock / seccomp） | Windows 优先；Cursor 自己在 Windows 上都退到 WSL2 |
| prompt cache 专项优化 | XEYO 成本里命中 token 只占 ≈5%，投产出低 |
| Cursor 的"撤除 guardrails"节奏 | 建立在它自研模型的能力曲线上；XEYO 是 DeepSeek 基座，护栏该按自己的曲线撤 |
| 团队索引复用 / 加密 access proof | 本地单机产品没有团队与跨用户场景 |
| `repeat_guard` 的 advisory 提醒形态 | 应改成 Cursor 的做法：把约束写进 **tool result 的状态陈述**，而不是另发提醒文本——后者与"注意力里只出现信息"直接冲突 |
| Cursor 的自摘要训练（模型自学压缩、输出 ~1000 token） | 训练侧能力，XEYO 无训练链路 |

### 一句话

第一档三条都是"改了立刻更可信"；第二档的核心是 **Keep Rate**——它不是一条优化，而是让其余优化变得可判断的那件工具；第三档应按 Cursor 自己的教训排序：**先有质量信号，再谈并行与路由**。
