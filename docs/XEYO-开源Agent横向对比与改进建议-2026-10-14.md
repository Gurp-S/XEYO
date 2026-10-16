# XEYO 是否需要改变：开源 Agent 横向对比（2026-10-14）

> **本文回答一个问题**：把 XEYO 放到 2026 年开源 coding agent 的版图里，**它需不需要改变？改哪里？**
>
> **与前五轮的关系**：`docs/XEYO-vs-DeepSeekHarness-*`（累计 7680 行）+ `XEYO-开源优化路线-五轮总结.md` 已经做过 XEYO vs **dsh 单一对象**的深度对比。本文是**第六轮**：把对象扩到 **codex / dsh / zcode + 主流开源 agent**，并且**沿用五轮总结的筛选准则 S1–S5**，保证结论与既有决策不打架。
>
> **取证口径**：dsh 部分为**本地源码实证**（`D:\lea\dsh-src`）；codex / zcode / 其他项目为**公开检索**，已标注来源与不确定项（见 §8）。

---

## §0 结论速览（先读这一段）

**需要改变，但只需要动 4 处；其余是"别人在补课，XEYO 已经做完了"。**

| 判定 | 项 | 一句话 |
|---|---|---|
| 🔴 **必须补** | **OS 级沙箱** | codex / dsh / OpenHands / Gemini CLI 全有；XEYO 只有策略层，**这是唯一的结构性代差** |
| 🟠 **强烈建议** | **模型自写编排脚本**（workflow-as-code） | dsh 已落地；这是唯一能「既补上编排能力、又不违反 XEYO 铁律 2」的路 |
| 🟡 **建议补** | **子代理 worktree 隔离** | 已成事实标准（codex / Qwen Code）；XEYO 的 `coord/worktree.py` 已有，只是没接 |
| 🟡 **建议补** | **LSP 接入** | dsh 有 `lsp/` + `tool-lsp`；XEYO 零 LSP，读码质量上限被压住 |
| 🟢 **不要改** | 多 Agent DAG 执行器 | **不要为了"别人有"去接线**——dsh 自己的 agent-team 也是 experimental，明说「无稳定性承诺」 |
| 🟢 **不要改** | WriteStore 写冲突模型 | **XEYO 比 dsh 强**（dsh 明说写范围只是 advisory，Bash/formatter 可绕过版本检查） |
| 🟢 **不要改** | rewind / T_now / 成本治理 / 本地优先 | 差异化护城河；zcode 的"静默上传工作区"争议正好反证本地优先的价值 |

**最反直觉的一条**：XEYO 在**多 Agent 并发写同一个代码库**这件事上，目前**比 dsh 做得更硬**（见 §5.2）。这一轮真正要补的是**沙箱**和**编排表达力**，不是"多 Agent"。

---

## §1 调研范围与取证方式

| 对象 | 取证方式 | 可靠性 |
|---|---|---|
| **dsh**（DeepSeek Harness，`deepseek-ai/deepseek-harness`，MIT） | 本地源码 `D:\lea\dsh-src`（50 个包组） | ✅ 实证 |
| **codex**（`openai/codex`，Apache-2.0，Rust） | 公开检索（官方 README + 多篇 2026 年分析） | ⚠️ 二手 |
| **zcode**（智谱 Z.ai ZCode，ADE） | 公开检索（智谱官网 + 百科 + 媒体报道） | ⚠️ 二手，身份已确认 |
| 其他（opencode / Aider / Cline / Roo / OpenHands / SWE-agent / Gemini CLI / Qwen Code / Goose / Crush / Continue / Amp / Trae Agent） | 公开检索 | ⚠️ 二手，仅作趋势参考 |

> **纪律**：凡二手来源，本文只用于「有没有这类能力」的判断，**不用于具体实现细节的断言**。凡不确定，写「未证实」。

---

## §2 三个重点对象的现状

### 2.1 dsh（本地源码实证 —— 最可靠的对照）

**定位**：DeepSeek 官方开源 harness，**everything-is-a-plugin**，构建在 Cordis（spatiotemporal composability）之上；MIT；developer preview，官方明说「**会有破坏性变更**」。

**与 XEYO 直接相关的四块能力（本地实证）**：

| 能力 | dsh 的实现 | XEYO 的现状 | 差距 |
|---|---|---|---|
| **沙箱** | `packages/sandbox/` 四包：`sandbox`（契约）/ `sandbox-local`（**Linux bwrap→Landlock、macOS Seatbelt、Windows restricted token**）/ `sandbox-policy`（共享策略）/ `sandbox-windows-acl`（**Windows ACL restricted token**，官方记录里明说"为何选它而不是 mxc/AppContainer"）。三档模式：`read-only` / `workspace-write` / `danger-full-access`；**fail-closed**；被拒可经用户批准做**一次性升级** | ❌ **零 OS 级沙箱**（`grep -ril "landlock\|seatbelt" python/` → 0）。只有 `permissions/` 策略链，且 `XEYO_BASH_UNSAFE_ALLOW` 的注释自陈「**没有 OS jail 就不给全权**」 | **结构性** |
| **编排表达力** | `packages/workflow/`：**模型写一段 JS 编排脚本**（`agent()` / `parallel()` / `pipeline()` / `phase()` / `log()`），引擎在 `node:worker_threads` 里跑；脚本的 `meta` 是**纯 JSON 数据**、**跑之前先校验 schema、绝不 eval 脚本文本取 meta**；结构化输出限定在 JSON Schema 子集；`agent()` 可按调用覆盖 `provider`/`model`。`isolation`/`effort`/`agentType` 是 **`DEFERRED_AGENT_OPTIONS`，显式报错拒绝** | 只有「模型同轮发 N 个 `Agent` 工具调用」；确定性 DAG 调度器（`engine/scheduler.py::run_task_batch`）**未接线** | **表达力** |
| **子代理后端** | `packages/subagent/`：**一个契约 `ctx.subagents` + 多个 provider**——进程内（全新 / **从父的已完成历史 fork**）、进程外（**ACP**、**真 Codex**（走官方 app-server 协议）、**真 Claude Code**（官方 Agent SDK）、Harness over SDK）。另有「**可续期的后台子代理**」（durable，接受后续轮次） | 子代理是本进程 `query_loop` 递归；`MAX_DEPTH=1`；子代理**短命** | 异构 + 可续期 |
| **多 Agent 协作** | `packages/experimental/agent-team/`：Lead + 命名队友、durable mailbox（崩溃/重启后仍送达）、共享 task board（**CAS revision**，过期写入被拒）。**但限制写得很直白**：「**一个进程、一个共享 checkout——本包不提供 worktree、不做 merge、不做文件系统锁**」「**写范围只是 advisory，Bash/formatter/代码生成器/外部写入者可绕过版本检查**」「无自动所有权释放」「mailbox 不是跨进程 exactly-once」 | WriteStore **每文件锁 + content-hash 前置条件**（不一致直接 `stale` 拒绝）+ 原子写 + `write_scope` 硬门禁 | **XEYO 更强** |

**dsh 还有 XEYO 没有的**（本地实证，`ls packages/`）：`lsp`（含 `tool-lsp`）、`schedule`（时间轴）、`e2b`（云端沙箱）、`webhook`、`jobs`、`acp`、`api`、`terminal`、`spill`、`hooks-claude-code`、`preset`/`bundle`/`profile` 组合层、`credentials`、`identity`。

> 注意：`workflow` 里那句 `isolation: 'worktree'` 出现在**测试断言里**，断的是**「`isolation` 是 deferred」**（`DEFERRED_AGENT_OPTIONS`）——**dsh 目前并不支持 worktree 隔离**。不要误读。

### 2.2 codex（二手，但多个来源一致）

- Rust 核心（`codex-rs`），Apache-2.0，规模约 12.9 万 star 量级（未精确核）。
- **多 Agent**：官方把 Codex 描述为 **agentic coding 的 Command Center**，用 **worktree + 云端环境**让多个 Agent 并行；2026-09 发布 Agents API（Context / Tool / **Subagent** + 执行环境）。
- **沙箱**：**平台自适应**——macOS Seatbelt / Linux Landlock / Windows sandbox；`approval_policy` 审批体系。
- **扩展**：`AGENTS.md` 项目指令（全局→项目逐级）+ **MCP + Skills**。
- ⚠️ 未证实：上下文压缩实现、resume 语义细节。

### 2.3 zcode（二手，身份已确认）

- **身份**：智谱 Z.ai 的 **Agentic 开发环境（ADE）**，2026-07 发布、2026-09 开源；**GLM-5.3 官方 Agent Harness**，1M 上下文，四档执行模式。
- **形态**：**「三端一核」**——Electron 桌面 + React Web + CLI TUI，**共享同一套 Agent 运行时**。
- **⚠️ 关键事件（对 XEYO 有战略意义）**：曾被曝**静默上传工作区快照**到云 OSS，引发信任危机，随后开源并公布补偿方案。
- 未证实：License、沙箱后端、子代理细节。

> **这条对 XEYO 的意义**：zcode 的争议恰好证明 **「本地优先」是可被用户验证的信任资产**。XEYO 的 `README` 首句就是「本地优先的代码工作台」，这不是口号，是**可对标的差异化定位**——不要为了对齐"云端多 Agent"而稀释它。

---

## §3 横向对照表（趋势参考，二手）

| 项目 | 语言/许可 | 多 agent | 并发/隔离 | 沙箱 | 上下文 | 扩展 | 形态 |
|---|---|---|---|---|---|---|---|
| **codex** | Rust / Apache-2.0 | ✅ 主+子代理 | **worktree + 云环境** | **Seatbelt/landlock/Windows** | AGENTS.md | MCP+Skills | CLI+IDE+App |
| **dsh** | TS / MIT | ✅ 可插拔异构 | ⚠️ 共享 checkout（**无 worktree**，isolation deferred） | **bwrap/landlock/Seatbelt/Windows ACL** | compaction 多档 + spill | MCP+Skills+插件 | CLI+Web |
| **zcode** | — | 未证实 | 未证实 | 未证实 | 1M 上下文 | — | 桌面+Web+TUI |
| **opencode** | TS+Bun / MIT | ✅ 主+子代理 | 事件流 | 权限门 | AGENTS.md+压缩 | 插件+MCP | TUI+桌面+IDE |
| **Gemini CLI** | TS / Apache-2.0 | ✅ Agent Skills | — | **Docker** | 自动记忆 | Extensions+MCP | CLI+IDE |
| **Qwen Code** | TS / Apache-2.0 | ✅ SubAgent | **worktree** | — | — | MCP | CLI+IDE |
| **OpenHands** | Python / MIT | ✅ 可委派 | — | **Docker/VM** | 事件流 | MCP | Web+CLI |
| **Roo Code** | TS / Apache-2.0 | ✅ Orchestrator | — | 审批 | — | MCP | IDE |
| **Aider** | Python / Apache-2.0 | ❌ 单 | **每步进 git** | ❌ | repo map | 少 | CLI |
| **SWE-agent** | Python / MIT | ❌ 单 | — | 沙箱 | ACI | 有限 | CLI |
| **Goose / Crush / Cline / Kilo / Continue / Amp / Trae** | 各异 | 部分 | 各异 | 各异 | 各异 | MCP 为主 | 各异 |

---

## §4 2026 开源 Agent 的共性趋势（本节最重要）

1. **多 Agent 已成主流，但形态收敛于「主从 + 上下文隔离」，不是自由并行。** 共识是「子代理独立上下文窗口、防污染、不无限嵌套」。真正大规模 DAG 并行仍是少数派。
2. **沙箱从"加分项"变成"入场券"。** Seatbelt / Landlock / bwrap / Docker 四足鼎立，**「按 OS 自适应选后端」**是共同做法。**这一条是 XEYO 最需要正视的**。
3. **worktree 隔离是"并行改同一代码库"的事实标准**（codex、Qwen Code）。但注意：**dsh 没做**（agent-team 明确不提供，workflow 的 isolation 是 deferred）——说明这条路**还没定论**，但方向清楚。
4. **编排正在从"模型发 N 个工具调用"走向"模型写编排脚本"**（dsh 的 workflow；其 `meta` 字段自陈「字段词汇对齐 **Claude Code dynamic-workflows** 的 meta 块」）。这是**本轮最有价值的新发现**。
5. **MCP 已是标准工具协议；Skills 正在成为第二层共识。**
6. **`AGENTS.md` 成为跨项目约定的项目级指令文件**（codex / opencode / Qwen 都支持）——XEYO 已有，✅ 不落后。
7. **「一核多端」**：CLI/TUI/GUI/IDE 共享同一 Agent 运行时——**XEYO 已是这个形态**（Python 引擎 + Tauri + Ink TUI + Typer CLI），✅ 不落后。
8. **Plan/Build 双模式 + 审批策略**成为通用抽象——XEYO 的 agent/plan/ask 三模式 ✅ 对齐。

---

## §5 逐维度判定：XEYO 需不需要改

### 5.1 沙箱 —— 🔴 必须补（唯一的结构性代差）

- **事实**：XEYO `grep -ril "landlock\|seatbelt" python/` → **0**；dsh 有完整四包 + 三档模式 + 一次性升级；codex 有平台自适应沙箱。
- **XEYO 现状的自陈风险**：`XEYO_BASH_UNSAFE_ALLOW` 的注释写着「**没有 OS jail 就不给全权**」（`permissions/policy.py:878`）——即 XEYO **自己承认**缺 jail 导致权限被迫收窄。
- **为什么必须补**：这不只是"功能对齐"。**沙箱是"权限策略可以变粗"的前提**——五轮总结 §0.2 已经点破：「dsh 的权限策略可以粗，因为下面有内核兜底；XEYO 必须细，因为正则就是最后一道防线」。**补上沙箱 = 权限链有机会从 11 级降到 3 级**（对应五轮总结的 W1 加权项）。
- **落地形态（受 S5「Windows 可用」约束）**：直接照抄 dsh 的**平台分流**思路——Linux `bwrap→landlock`、macOS `Seatbelt`、**Windows ACL restricted token**（dsh 官方记录里专门论证过"为何选 ACL restricted token 而不是 mxc/AppContainer"，这是可复用的先例）。**旁路优先**（S2）：先做成一个 `sandbox` 模块 + feature flag，不动权限链；验证收益后再考虑简化权限链。
- **优先级**：**P0**。

### 5.2 并发写冲突 —— 🟢 不要改，XEYO 更强

- **XEYO 的 WriteStore**：每文件分片锁 + **content-hash 前置条件**（base vs 磁盘，不一致 → `stale` 拒绝）+ `missing_read` 拒绝盲写 + 原子写（`os.replace` + Windows 占用回落）+ `write_scope` 硬门禁。
- **dsh 的 agent-team**：官方自陈「**写范围只是 advisory**，Bash/formatter/代码生成器/外部写入者可绕过版本检查」+「无 worktree、无 merge、无文件系统锁」。
- **结论**：在"多 Agent 写同一代码库"这件事上 **XEYO 的机制比 dsh 硬**。这是 XEYO 的**优势**，应保留，并可在开源叙事里作为卖点。**不要因为"别人有多 Agent"就去改这里。**

### 5.3 编排表达力 —— 🟠 强烈建议补，且这是唯一不破铁律的路

- **差距**：XEYO 的编排上限是「同轮 N 个 `Agent` 调用」（彼此独立、无数据流、无循环、无 pipeline）。dsh 的模型可以写一段脚本，里面有 `parallel()` / `pipeline()` / 循环 / 结构化输出 / 每调用换模型。
- **为什么这不是"违反铁律 2"**：XEYO 铁律 2 是「**引擎**不规划路线」。dsh 的 workflow 里，**脚本是模型写的**——规划权仍在模型，引擎只提供执行器。五轮总结 §3.2 推论 1 说得很清楚：Workflow「只能以**模型可主动调用的工具**形态存在」——**模型自写编排脚本正是这个形态**。
- **必须先回答的设计问题（不要跳过）**：
  1. **执行边界**：脚本能调哪些工具？必须复用现有 `write_scope` / 权限三态，不能开旁路（否则违反铁律 3「限制只在执行层」的反面——变成"脚本层绕过执行层"）。
  2. **铁律 1 风险**：`phase()` / `log()` 会产出叙述文本。dsh 的处理是「`phase` 只是给观察者的进度分组，**无执行语义**」——XEYO 若要采纳，必须确保这些文本**不进模型注意力**（或只作为事实）。
  3. **安全**：dsh 自己在源码注释里写明「**vm 不是安全边界**」。所以这条**依赖 §5.1 的沙箱先落地**。
- **优先级**：**P1**（且排在沙箱之后）。

### 5.4 子代理 worktree 隔离 —— 🟡 建议补（小工程量）

- **事实**：XEYO 的 `coord/worktree.py` + `reconciler.py`（唯一 reconciler + `git rebase` 三路合并 + `REOPEN_LIMIT=3` 熔断）**已经实现且测试完整**，但 `coord.backend` **默认 `memory`**，产线子代理不隔离（同 cwd，靠 WriteStore 收敛）。
- **趋势**：worktree 隔离是事实标准（codex / Qwen Code）；但 dsh **没做**（agent-team 明确不提供）——说明它还没到"不做就出局"的程度。
- **建议形态**：**不要**去启用整条 coord 链（那是重型跨进程编排）。而是把 `WorktreeManager` 抽成**子代理的一个可选项**（`Agent` 工具加 `isolation: "worktree"`），只解决"两个子代理并行改同一批文件"这一件事，合并仍走 reconciler 的三路合并。这是**小一个数量级**的工程。
- **优先级**：**P1**。

### 5.5 LSP 接入 —— 🟡 建议补

- **事实**：XEYO `grep -ril "language server"` → **0**；只有符号级浏览（类/函数/模块结构）。dsh 有 `packages/lsp/`（`lsp` + `lsp-stdio` + `tool-lsp`）。
- **为什么值得**：XEYO 的差异化是"读代码质量"，而 LSP 提供的**定义跳转 / 引用查找 / 类型诊断**是文本搜索（rg）给不了的。这直接抬升 agent 读码与改码的准确率。
- **落地形态**：新增 `lsp` 模块 + `Lsp` 工具（旁路，S2），stdio 传输（与 XEYO 现有 MCP stdio 同构，可复用传输层思路）。
- **优先级**：**P2**。

### 5.6 异构子代理 / 可续期子代理 —— 🟡 可选（生态位选择）

- dsh 能**把真实 Codex / Claude Code 当子代理**（走 ACP / 官方 app-server / 官方 Agent SDK），并且子代理**可续期**（durable，接受后续轮次）。
- 对 XEYO：这是**战略选择题**，不是必答题。若 XEYO 想定位成"编排层/中枢"，异构子代理是加分项；若定位成"本地一体化工作台"，自研子代理更自洽。**建议先不做，记为储备**。
- **优先级**：**P3**。

### 5.7 定时任务 / MCP HTTP-SSE —— 🟢 低优先

- XEYO 的 `XEYO-未开启功能全清单` §7 已明确：**G-1 无时间轴**（`crontab|schedule_at|cron` 零命中）、**G-3 MCP 仅 stdio**。dsh 有 `schedule/`。
- 但对"编程 agent"而言，**定时任务的价值远低于沙箱和编排**；MCP HTTP/SSE 只影响远程 server 场景（XEYO 定位本地优先，收益更小）。
- **优先级**：**P3 / 不做**。

---

## §6 建议改动清单（按 XEYO 自己的 S1–S5 准则筛过）

筛选准则沿用 `XEYO-开源优化路线-五轮总结.md` §1：S1 不破铁律 / S2 可旁路独立落地 / S3 收益可证伪 / S4 不引入巨石 / S5 Windows 可用。

| 优先级 | 改动 | 落地形态 | 为什么过 S1–S5 | 判据（S3） |
|---|---|---|---|---|
| **P0** | **OS 级沙箱**（平台分流：Linux bwrap→landlock / macOS Seatbelt / **Windows ACL restricted token**） | 新模块 `sandbox/` + flag，**不动权限链** | S1✅限制在执行层 S2✅旁路 S3✅越权写能被拦 S4✅新模块 S5✅有 Windows 后端先例 | 构造"写工作区外文件"的用例，沙箱开/关 A/B：开关下被拒且 fail-closed |
| **P1** | **子代理 worktree 隔离** | `Agent` 工具加 `isolation:"worktree"`，复用 `coord/worktree.py` + `reconciler.py` | S1✅ S2✅ S3✅ S4✅ S5✅ | 两个子代理并行改同一文件 → 隔离下各自 worktree，合并走三路合并；不隔离下第二个 `stale` |
| **P1** | **模型自写编排脚本**（workflow-as-code） | 新工具 `Workflow`，worker 线程执行，脚本只能调**已过权限三态**的工具 | S1✅（脚本由模型写，引擎不规划）S2✅ S3✅ S4✅ S5✅ | 同一任务用"N 个 Agent 调用" vs "一段编排脚本"跑 A/B，比 token 与完成率 |
| **P2** | **LSP 接入** | 新模块 `lsp/` + `Lsp` 工具，stdio | S1✅ S2✅ S3✅ S4✅ S5✅ | 同一改码任务，开/关 LSP 比"改错文件/改错符号"次数 |
| **P3** | 异构子代理（ACP / 真 Codex / Claude Code 作子代理） | 储备，不落地 | — | 先做生态位决策 |
| **P3** | 定时任务 / MCP HTTP-SSE | 不做或储备 | 收益低 | — |
| **不做** | 接上 `run_task_batch` DAG 执行器 | — | **为对齐而接线 = 违背 XEYO 自己的"模型自决"决策** | — |
| **不做** | 改 WriteStore 写冲突模型 | — | XEYO 已强于 dsh | — |
| **不做** | 拆 rewind / T_now / 成本治理去"对齐" | — | 差异化护城河 | — |

---

## §7 明确不做的事（避免跟风）

1. **不要为了"别人有多 Agent"去启用 DAG 执行器。** XEYO 的决策（分解权归模型）是对的；dsh 自己也没把 agent-team 当稳定能力——它是 **experimental、私有包、明确排除在官方发布之外、无稳定性承诺**。两边**独立收敛到同一个判断**，这本身就是证据。
2. **不要把"云端并行"当目标。** codex 的 worktree+云环境是它的产品形态（云优先）；XEYO 是本地优先。**照着抄会稀释自己的定位。**
3. **不要为了"沙箱"而破坏 Windows 可用性。** 五轮总结 S5 已经钉死这条——**Linux-only 方案对 XEYO 的主战场零收益**。要抄就抄 dsh 的 Windows ACL 先例。
4. **不要把 `AGENTS.md` / 三模式 / 一核多端当成待补项**——XEYO 已经全部具备（§4 趋势 6/7/8）。
5. **不要在编排脚本里塞"导演文本"。** 铁律 1 是 XEYO 最贵的资产（有 `test_loop_ledger.py` 逐词断言在执法）。`phase()` / `log()` 这类叙述必须不进模型注意力。

---

## §8 不确定项与取证边界

| 项 | 状态 |
|---|---|
| codex 的多 Agent / worktree / 沙箱细节 | **二手来源**（官方 README + 2026 年分析文）。方向可信，**具体实现未实证** |
| codex 的上下文压缩、resume 语义 | **未证实**，本文未据此下结论 |
| zcode 的 License / 沙箱后端 / 子代理细节 | **未证实**；本文只用其"身份 + 三端一核 + 上传争议"三点，均为公开报道 |
| dsh 的 `isolation: 'worktree'` | **已实证为 deferred**（`DEFERRED_AGENT_OPTIONS`，测试断言其报错）——**dsh 目前不支持 worktree 隔离** |
| dsh 的沙箱"实际生效程度" | 本地有四个包与官方设计记录；**未实机验证其拦截效果** |
| 其他项目（opencode/Gemini CLI/Qwen Code 等） | **仅作趋势参考**，未逐项核实 |
| XEYO 侧 | 均为**本地源码实证**（`python/`，已排除 `.venv`/`__pycache__`/`node_modules`） |

**一句话边界**：本文对 **dsh** 的结论可直接采信；对 **codex / zcode / 其他** 的结论是"趋势级"判断，落地前需再做一次一手核实。

---

## 附：本轮引用

**XEYO 侧**：`AGENTS.md` · `docs/XEYO-架构范式定位与证据-2026-10-13.md` · `docs/XEYO-开源优化路线-五轮总结.md` · `docs/XEYO-未开启功能全清单-与原因.md` · `docs/面试知识书/07-第六册-扩展与多智能体.md` · `python/engine/write_store.py` · `python/engine/write_transaction.py` · `python/coord/{worktree,reconciler,store}.py` · `python/permissions/{policy,write_scope}.py`

**dsh 侧（本地 `D:\lea\dsh-src`）**：`README.md` · `packages/sandbox/README.md` · `packages/sandbox/sandbox-local/` · `packages/subagent/README.md` · `packages/experimental/agent-team/README.md` · `packages/workflow/tool-workflow/src/index.ts` · `packages/workflow/workflow-worker-thread/src/runtime.ts` · `docs/subsystems/workflow.md`

**公开来源**：`github.com/openai/codex`（README）· 智谱官网 `zhipuai.cn` · 百度百科「Zcode」· 多篇 2026 年 codex/ZCode 分析报道（见正文标注）
