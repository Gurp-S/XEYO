# XEYO × DeepSeek Harness（dsh）全量对比

> 只读源码考古，2026-09-10。**所有结论均来自实际读到的源码/生成文档，附 `文件:行号`；凡"未见"= 通读范围内未找到实现，不等于绝对不存在，但已按可检索面穷举。**

---

## 0. 取证口径（先说清楚我读了什么）

| | **XEYO** | **DeepSeek Harness（dsh）** |
|---|---|---|
| 仓库 | `D:\lea\XenYon code`（本机工作区） | `github.com/deepseek-ai/deepseek-harness` |
| 本地副本 | — | `D:\lea\dsh-src`（原为 sparse checkout，本次**已关闭 sparse 并补齐全部源码**） |
| 版本/提交 | 工作树 HEAD | `d347e70`，`version 0.1.3-alpha.1`，默认分支 `master` |
| 许可 | MIT（`LICENSE:1`） | MIT（`LICENSE`，仓库根） |
| 读取方式 | `find`/`grep` 全量 + Read 关键文件 | 同上；`git ls-tree -r HEAD` 枚举 9080 个受控文件 |

**规模（本机实测，非引用）**

| 维度 | XEYO | dsh |
|---|---|---|
| 源文件 | Python 1141 个 `.py`；GUI 391 个 `.ts/.tsx`；Rust 3 个 `.rs`；TUI 16 个 `.tsx` | 3226 个 `.ts/.tsx`（含测试），255 个包 |
| 代码行 | Python **160,772**；`gui/src` **81,484**；`tui` **3,544**；Rust **1,162** ≈ **246,962** | **767,579**（含测试）；**308,675**（仅 `*/src/`） |
| 测试文件 | pytest **307**；GUI **102** | vitest **863** |
| 包/模块数 | `python/` 约 16 个顶层子包 | `packages/<组>/<包>/` **255** 个 |
| 文档 | `docs/*.md` **21** 篇 | `docs/` **363** 个文件（含双语文档 + 生成目录 + 子系统页） |

> 一句话：**dsh 的源码量约为 XEYO 的 1.2～3 倍（按口径），但包粒度细 16 倍**——XEYO 是「一大坨 Python 引擎 + 一个 GUI」，dsh 是「255 个小包的插件树」。

---

## 1. 定位

| | XEYO | dsh |
|---|---|---|
| 自称 | 本地编码 Agent（`AGENTS.md:1`「XEYO 项目级说明」） | 开源 agent harness，`README.md:3`「an open-source agent harness developed by DeepSeek AI」 |
| 核心主张 | **注意力纪律**：*"注意力里只出现信息，不出现导演"*（`AGENTS.md` 设计理念节） | **一切皆插件**：*"There is no privileged core to patch"*（`docs/architecture.md:13`） |
| 架构基座 | 自研单体引擎（Python）+ FastAPI + React/Tauri 壳 | [Cordis](https://github.com/cordiverse/cordis) 元框架（插件/服务/可回滚副作用），形式化论文 arXiv:2608.25512 |
| 成熟度 | 内测/自用（有镜像容灾、事故复盘文化） | **developer preview**（`README.md:11` 明写 *THERE WILL BE COMPATIBILITY-BREAKING CHANGES*） |

**这是最根本的分歧**：XEYO 把「怎么让模型看到正确的信息」当作第一性问题并在引擎文本层面立法；dsh 把「怎么让任何一块能力都能被换掉」当作第一性问题并在**组合结构**层面立法。两者甚至不冲突——但取向完全不同。

---

## 2. 顶层架构范式

### 2.1 dsh：255 个包的 Cordis 插件树

- `docs/architecture.md:11`：*"Every part of the product is a plugin, including the model adapter, the tool registry, the session log, and the agent loop itself"*。
- **注册即 effect**：`AGENTS.md:105`「every contribution goes through `ctx.effect()` / `ctx.on()`; a registry's `register()` returns the disposer」——插件卸载时注册项自动解绑。
- **68 个服务缝**（`docs/capability-seams.md` 生成图，实测提取）：
  `ctx.sessions`、`ctx.tools`、`ctx.systemPrompt`、`ctx.agents`、`ctx.agentLoop`、`ctx.llm`、`ctx.fs`、`ctx.shell`、`ctx.subprocess`、`ctx.terminals`、`ctx.sandbox`、`ctx.sandboxPolicy`、`ctx.approval`、`ctx.userQuestions`、`ctx.permissionPresets`、`ctx.subagents`、`ctx.skills`、`ctx.compaction`、`ctx.spillStore`、`ctx.codeRuntime`、`ctx.workflowEngine`、`ctx.goals`、`ctx.jobs`、`ctx.schedule`（工具）、`ctx.webhookRuntime`、`ctx.web`、`ctx.lsp`、`ctx.attachments`、`ctx.credentials`、`ctx.authorization`、`ctx.settings`、`ctx.storage`、`ctx.storageDomain`、`ctx.sessionPersistence`、`ctx.sessionProjections`、`ctx.sessionProjectionCache`、`ctx.sessionQuery`、`ctx.sessionTitle`、`ctx.sessionTelemetry`、`ctx.workspaceRegistry`、`ctx.commands`、`ctx.agentPresets`、`ctx.clientModules`、`ctx.typert`、`ctx.typertGateway`、`ctx.webServer`、`ctx.dynamicCordisRunner`、`ctx.cordisInspect`、`ctx.inspector`、`ctx.invariants`、`ctx.tokenMeter`、`ctx.toolResultPruner`、`ctx.spillStore`、`ctx.fileReferences`、`ctx.fileUploads`、`ctx.sessionFileReferences`、`ctx.sessionSkillCatalog`、`ctx.messageFeedback`、`ctx.sessionReferenceResolver`、`ctx.planMode`、`ctx.directoryPicker`、`ctx.agentTeams`、`ctx.agentDefaultModel`、`ctx.subagentModelSelection`、`ctx.shellEnv`、`ctx.deepseekLlmApiExtensions`、`ctx.agentToolPresentation` 等。
- **能力缝三角色**（`docs/architecture.md:117`）：Service Definition（抽象类）/ Service Provider（唯一实现）/ Consumer（通常是模型可见工具）。例：`packages/shell/shell/src/index.ts:64` `abstract class ShellExecutor extends Service`，实现 `bash-local`/`pwsh-local`，消费方 `tool-bash`。
- **组合层**：Profile（5 档：`web`/`headless`/`sdk`/`sdk-minimal`/`acp`，`packages/boot/app-boot/src/profile.ts:137-158`）→ Bundle（`base`/`web-app`/`headless`/`sdk-app`/`sdk-minimal`/`acp-app`）→ 用户 `cordis.patch.yml` → `--patch` 覆盖层（`docs/architecture.md:27`）。

### 2.2 XEYO：单体引擎 + 注入管线

- `python/AGENTS.md` 的「入口与运行模型」给出四入口（GUI/TUI/CLI/attach）。
- 没有插件容器；扩展面是**固定枚举**的三条：`extension/`（MCP + 插件 + hooks）、`slash/`（斜杠命令）、`skills/`（技能目录）。
- 架构约束反向：`AGENTS.md` 反巨石规则「新逻辑一律进新模块，既有巨石（`chat.py`/`query_loop.py`/`Composer.tsx`）只留接线点」——即用**文件级模块隔离**替代运行期插件隔离。

### 2.3 对照结论

| 维度 | XEYO | dsh |
|---|---|---|
| 扩展机制 | 编译期枚举 + 配置开关 | 运行期挂载/卸载插件，effect 自动回收 |
| 可替换粒度 | 整包替换（改代码） | 单个 seam 的 provider 替换（改配置） |
| 配置载体 | `~/.xeyo/settings.json` + `<ws>/.xeyo/settings.json` | `cordis.yml` + `cordis.patch.yml`（YAML + `!!js` 表达式） |
| 失败姿态 | 坏 JSON → keep-last-good | 配置错误 → **fail loud**（`AGENTS.md:116`） |

---

## 3. 运行入口与产品形态

| | XEYO | dsh |
|---|---|---|
| 入口 | `XEYO.bat`（Tauri dev）、`XEYO-TUI.bat`（Ink）、`python -m cli`（Typer）、attach HTTP | `dsh` CLI 单一入口：`dsh web` / `--profile headless` / `--profile sdk` / `--profile sdk-minimal` / `--profile acp`（`docs/architecture.md:43`） |
| 应用数 | 3 端（GUI/TUI/CLI） | 5 profile（+Python SDK 运行时） |
| 启动约束 | 无特殊约束 | **应用只能由 `dsh` profile 启动**；`verify-application-entrypoints` 机器执法（`AGENTS.md:9`） |
| 协议 | FastAPI + SSE（`/v1/chat/completions`） | Typert RPC 网关（WebSocket mux）+ HTTP `/api`；ACP（JSON-RPC stdio）；SDK（newline-delimited JSON-RPC） |

---

## 4. Agent 主循环

### dsh

- **turn/step 两级**（`docs/architecture.md:76-95`）：一个 *step* = 一次模型请求 + 它调用的工具；一个 *turn* = 0..n 个 step。
- 序列：`turn/start` → claim input → 装配 prompt sections + tool schemas → `agent/pre-step`（waterfall，可改写/拒绝）→ `step/start` → 写 `user/message` → `deriveMessages()` → `agent/request`→`llm/stream`→assistant stream → `tool/call*` → `tools/pre-execute`→`tools/execute`→`tools/post-execute`→`tool/result*` → `step/end` → 若欠一个请求或来了新输入则继续 → `agent/turn-stopping` → `turn/end`。实现：`packages/core/agent-loop/src/agent.ts:258-342`（turn）、`:344-482`（step）。
- **瀑布式拦截**：`agent/pre-step`、`agent/request`、`llm/stream`、`tools/*` 三个都是 waterfall，**listener 必须调 `next()`** 才委派（`AGENTS.md:109`）；`agent/turn-stopping` 是串行无 next。
- 终止原因：无 tool-call、`concludesTurn`、max-tokens（粘性）、reject→blocked、error、aborted（`agent.ts:279-282,471-476`）。
- 取消：每阶段一个 `AbortController`，`cancel()` 带 `{kind:'user'|'parent'|'hook'|'disposed'}` 归因（`agent.ts:146-152`）。

### XEYO

- **单层 turn 循环**：`python/engine/query_loop.py:726` 起，`while True` 在 `:796`。
- 序列：abort 检查 → `budget.prepare_next_turn()`（失败进收尾窗 `:800-812`）→ 投影 `project_for_model`（C0/C1/C2，`:924`）→ `first_sniff` 首轮嗅探 → `_attach_turn_context` 注入 T_now → `prompt.build` + `tools.schemas()`（缓存冻结）→ `model.stream` → `_admit_tool_use` 配额/并发 → `run_tools_partitioned` → `store.append(tool_result_message)` → 下一轮。
- 终止：aborted / budget_usd / max_turns / token budget / 无 tool_uses→`FinalEvent`（`:1540`）/ Plan 模式审批（`:1437-1538`）。
- 恢复：`engine/resume_directive.py` 用 contextvar + 投影-only 送达，**不落库**。
- 粘性 vs 重置：`schemas_json_cache` 跨 turn 冻结（`:1012-1018`）；`repeat_guard`/`zero_hit_tracker`/`result_fold` **每次 submit 重建**（`:774-785`）。

### 差异

| 维度 | XEYO | dsh |
|---|---|---|
| 循环抽象 | 硬编码在 `query_loop.py` | `ctx.agentLoop` 本身是可替换的 seam |
| 拦截点 | 代码内联的 guard/flag | 命名 waterfall 事件，插件可挂 |
| 步/轮区分 | 无独立 step 概念 | turn/step 两级，且 step 是**持久事件** |
| 工具并发 | `_admit_tool_use` 只读早并发 | `isConcurrencySafe` → parallel/exclusive，`DEFAULT_MAX_PARALLEL_TOOL_CALLS=10`（`agent-loop/constants.ts:6`） |

---

## 5. 会话数据模型（**最大的结构差异**）

### dsh：事件溯源日志

- **append-only `SessionEvent` log 是唯一真相源**；`deriveMessages()` 从日志投影出模型历史（`docs/architecture.md:107`）。
- 事件类型（`packages/core/session/src/types.ts:260-376`）：
  `turn/start`、`turn/end`、`step/start`、`step/end`、`user/message`、`assistant/message`、`assistant/attempt`、`tool/call`、`tool/result`、`request/header`、`request/context`、`session/end-seed`；插件扩展类型 70+ 种（`known-event-types.ts:22-74`）。
- **Surface 概念**：`SurfaceEventType = user/message | assistant/message | tool/result`（`types.ts:387-391`）——只有这三类进模型历史；`surfaceOp: 'append' | {op:'replace',start,end}`（`surface.ts:416-418`）。
- 版本：`SESSION_FORMAT_VERSION = 2`（`types.ts:86`），header 校验（`index.ts:101-103`）；`seq = log.length` 连续契约（`index.ts:659-661`）；append 前 `snapshotJsonValue` 强制 lossless JSON（`index.ts:709-716`）。
- **代际迁移**：v0 `session.jsonl[.zstd]`，v1+ `session.vN.jsonl[.zstd]`；**已提交代际永不重命名/覆盖/删除**，打开旧版时在内存里链式迁移并**并排发布**新代（`docs/architecture.md:109`）。
- `assistant/message` 内嵌**该步精确的压缩流**（`stream: AssistantStreamRecord[]`），失败的尝试进 `assistant/attempt`——不伪造模型历史。
- 派生能力：fork / resume / transcript / telemetry / persistence 全部从日志派生。
- `session/end-seed` 标记 seed 边界（resume/fork/replay 继承前缀）。

### XEYO：消息级 transcript + 三层存储

- 三层：前端 IndexedDB（`gui/src/lib/db.ts:17-37`，库 `xeyo-web` v4）→ 后端 `~/.xeyo/sessions/<id>.jsonl`（`python/session/persistence.py:39,62`）→ `_workspace_index.jsonl`（`session/ws_index.py:38`）。
- 记录格式（`session/record_transcript.py:205`）：`{id,role,content,tool_call_id,name,narration?,interrupted?,ts}`——**消息级、非事件级**。
- 写入：后台线程批量 + fsync（`:143-156`），轮转保留 2 代（`:65,81`）。
- 生命周期接口（`server/routers/sessions.py`）：archive `:558`、restore `:575`、DELETE `:191`（常态 409 `archived_required`）、fork `:483`、rename `:464`。
- rewind：v3 热路径 `rewind/hotpath.py`（默认）、v2 `rewind/service.py` 兼容；接口 `server/routers/rewind.py:168 /rewind`、`:192 /undo`、`:210 /recover`。

### 对照

| 维度 | XEYO | dsh |
|---|---|---|
| 真相源粒度 | 消息（message-level） | 事件（event-sourced） |
| 能否重建"模型当时看到什么" | 靠投影函数重算，日志不含请求头 | `request/header` 入日志，**可逐字重建**；runtime invariant 强制校验 |
| 失败的模型尝试 | 无独立记录 | `assistant/attempt` 保留 |
| 版本迁移 | 轮转 2 代 | vN 代际 + 内存迁移 + 并排发布，永不改写旧代 |
| fork | `POST /v1/sessions/{id}/fork` | `SessionStore.fork()`，seed 前缀 + `inheritedEventCount`，禁止跨 open turn（`session/src/index.ts:1176-1234`） |
| 模型能否查询自己的历史 | 有 `JournalQuery`（查 rewind 日志） | **5 个只读工具**：`session_event_read`/`session_event_search`/`session_event_trace`/`session_search`/`session_trace`（`docs/tool-catalog.md:1304-1536`） |

> dsh 的「模型可查询自己的会话历史」是 XEYO 完全没有的能力面；XEYO 的 `rewind`（工作区回滚 + 崩溃恢复）是 dsh 完全没有的能力面（dsh 无 workspace rewind，只有 session fork）。

---

## 6. 上下文投影与压缩

| | XEYO | dsh |
|---|---|---|
| 投影 | `project_for_model` 分 C0/C1/C2 三档 + 增量缓存 `proj_cache`（`query_loop.py:882-946`） | `ctx.sessionProjections` 注册式投影单元，增量 fold + `snapshot()` 裁剪批（`architecture.md:113`） |
| 压缩 | `compact.py` + `memory/compact`，预算 `budget.py`、`aging.py`、`result_fold`（重复结果折叠） | `ctx.compaction` seam（`compaction/src/index.ts:96-170`），provider `compaction-basic`，触发 `pressure`/`context-overflow`；区间替换为单个 summary 节点，`compaction/start..end` 锁定 |
| 工具结果瘦身 | `offload_read` 工具 + 结果折叠 | `compaction-tool-result-pruner`（`thresholdChars: 8192, headChars: 4096, tailChars: 1024`，standard preset）+ `ctx.spillStore` 超长文本落盘返回 locator |
| token 计量 | `usage/pricing.py` + 厂商权威 usage | `ctx.tokenMeter`（`token-meter/src/estimate.ts:43` 用 `CHARS_PER_TOKEN` 启发式）——**仅用于重放测量，不参与预算决策** |

**注意**：dsh **未见**显式的 token 预算/死线机制（预算类能力集中在 XEYO：`budget.py`、`runtime_budget`、`wrap_up` 收尾窗）。这是 XEYO 明显更强的一面。

---

## 7. System Prompt 与「模型可见文本」策略

### dsh
- 段注册表：`ctx.systemPrompt.section()` 按 `order` 排序（`core/system-prompt/src/index.ts:432-441`）；内置 `harness:identity`(−1000)、`deployment:persona`(0)、工具段 `TOOL_READ 1100`…`TOOL_SUBAGENT 2800`（`index.ts:121-152`）。
- 动态上下文单独序列（`context()`，`index.ts:77-84`）；`{{variable}}` **严格插值**，未定义即抛（`index.ts:309-346`）。
- **铁律**：*"Model-visible means logged"*（`architecture.md:111`）——任何进入请求的内容必须能从日志重建，runtime invariant 强制（`agent-loop/src/invariant.ts:21-54`）。
- **未见** KV 前缀缓存的显式断点（无 `cache_control`），也未做「静态段/动态段」显式切分——dsh 靠"把易变内容变成 session 事件"而不是靠 prompt 分区来保缓存。

### XEYO
- 左段极简：`[IDENTITY, CWD, FENCE_POLICY]`（`prompt/system_prompt.py:65-69`）；Date/Model 刻意不进左段**保 KV 前缀**。
- `XEYO.md` 经 instructions 注入（`:119`）；身份句不含行为要求（`:23-25`）。
- **T_now 注入管线**（`prompt/pre_llm_inject.py`）：全部易变内容走此管线，默认声道 `env_channel`（伪造 `assistant(xeyo_env_notice) → tool_result` 对尾插，`t_now_strategy.py:4-8,29`）。
- **硬准入**：`T_NOW_BLOCK_HARD_CAP = 21`（`pre_llm_inject.py:826`）；预算 6000 / inventory 2500（`:812-813`）；每个 `tagged.append` 必须带 `# block: <名>` 且与登记表一一对应，`tests/test_t_now_block_registry.py` 机器执法。
- 现有 **20 块**（`pre_llm_inject.py:828-909`）：`continue`、`mode_instructions`、`wrap_up`、`runtime_budget`、`budget_mirror`、`multi_agent_hint`、`repeat_guard`、`nested_instructions`、`compact`、`mcp_required_warn`、`reconcile_events`、`peer_presence`、`file_conflict`、`browser_preview`、`runtime_mode_snapshot`、`agent_settlement`、`goal`、`resume_directive`、`pending_jobs`、`skill_preinvoke`。每块登记「为什么必须在上下文」+ 类别（directive/event/inventory）。

**对照**：dsh 用「日志可重建性」保证不偷偷给模型看东西；XEYO 用「白名单 + 预算硬顶 + 逐条理由」保证**不给模型看导演**。前者约束"可审计"，后者约束"内容性质"。**两者互补，不重叠。**

---

## 8. 工具系统：逐工具对照

### 8.1 dsh 全量工具清单（`docs/tool-catalog.md`，生成物，`verify-tool-catalog` 执法）

| 工具 | 包 | 用途 |
|---|---|---|
| `bash` | `tool-bash` | POSIX shell 执行，支持 `run_in_background`、沙箱升级审批 |
| `pwsh` | `tool-pwsh` | PowerShell 方言（Windows 组合） |
| `bash` / `pwsh`（持久） | `tool-bash-persistent` / `tool-pwsh-persistent` | **PTY 持久会话**，状态跨调用保留 |
| `read` / `write` / `edit` / `read_image` | `tool-fs` | 文件读写 + 图片（需 `ctx.attachments` + 图像路由） |
| `glob` / `grep` | `tool-fs-search` | 直调打包的 ripgrep 二进制（经 `ctx.subprocess`，**不经 shell**） |
| `str_replace_editor` | `tool-str-replace-editor` | view/create/唯一字面替换/行插入（Anthropic 风格编辑器） |
| `terminal_open/close/read/send/signal/list` | `tool-terminal` | 6 个 PTY 终端工具（可选） |
| `todo_write` | `tool-todo` | 会话级清单，`todo/write` 事件，整体替换 |
| `exit_plan_mode` | `plan-mode` | 计划提交审批；**跨模式常驻**以保工具目录不变 |
| `ask_user_question` | `tool-ask-user` | 挂起等待人类回答 |
| `run_code` | `tools`（保留名） | **PTC 模式**：模型写程序编排多次工具调用，一次往返 |
| `skill` | `tool-skill` | 技能目录 + 加载 |
| `subagent` / `subagent_fork` | `tool-subagent` | 派生子代理（spawn / fork provider，可续聊） |
| `interrupt_agent`/`list_agents`/`send_message` | `tool-subagent-control` | 控制后台可续子代理 |
| `job_output`/`job_list`/`job_kill` | `tool-jobs` | 通用后台任务控制（bash 后台/PTY/子代理同一套） |
| `create_goal`/`get_goal`/`update_goal` | `tool-goal` | 同会话目标状态机 |
| `schedule_create`/`schedule_delete`/`schedule_list` | `schedule` | 定时（after_seconds / at / every_seconds） |
| `lsp` | `tool-lsp` | 语言服务器导航（provider 在 `ctx.lsp` 后） |
| `web_search` / `web_fetch` | `tool-web` | 检索/抓取（provider 在 `ctx.web` 后） |
| `workflow` | `tool-workflow` | 模型写 workflow 脚本，worker-thread 执行，含 agent/parallel/pipeline/phase/log |
| `ralph` | `tool-ralph` | 固定前台工作流，每轮一个结构化子代理，可选轮数上限 |
| `session_event_read`/`_search`/`_trace`、`session_search`/`session_trace` | `tool-session-query` | 读自己的会话历史（可选包） |
| `list_subagent_models` | `tool-subagent` | 子代理模型发现 |
| `cordis_define`/`_inspect_list`/`_inspect_query`/`_inspect_self`/`_run`/`_stop`/`_undefine` | `tool-cordis` | **自修改：模型定义并挂载自己的插件** |
| `interrupt_agent`/`list_agents`/`send_message`/`spawn_teammate`/`team_task_*`/`wait_agent` | `experimental-tool-agent-team` | Agent Teams（实验，默认禁用） |

**计：稳定产品工具 ≈ 45 个（含 7 个 cordis 自修改工具、6 个终端工具），实验组另 9 个。**

### 8.2 XEYO 全量工具清单（`python/tools/meta.py:53-311` `TOOL_META`，实测 26 个）

`echo`、`getTime`、`offload_read`、`Glob`、`Grep`、`Read`、`Write`、`Edit`、`Bash`、`TodoWrite`、`Screenshot`、`SendToWeChat`、`Memory`、`AskUserQuestion`、`JournalQuery`、`Skill`、`Agent`、`Diagnostics`、`Git`、`NotebookEdit`、`WebFetch`、`WebSearch`、`XeyoUI`、`job_output`、`job_list`、`job_kill`。

### 8.3 逐项映射

| 能力 | XEYO | dsh | 结论 |
|---|---|---|---|
| 读/写/编辑 | `Read`/`Write`/`Edit` | `read`/`write`/`edit` + `str_replace_editor` + `read_image` | dsh 多 2 个（图片读、Anthropic 风格编辑器） |
| 检索 | `Glob`/`Grep` | `glob`/`grep` | 对等（dsh 直调 ripgrep，XEYO 走 rg） |
| Shell | `Bash` | `bash` + `pwsh` + **持久 bash/pwsh** | dsh 多 pwsh 原生 + PTY 持久 |
| 终端 | **未见** | 6 个 terminal 工具 + `ctx.terminals` | **dsh 独有** |
| 后台任务 | `job_output/list/kill` | `job_output/list/kill` | 对等 |
| 任务清单 | `TodoWrite` | `todo_write` | 对等 |
| 提问 | `AskUserQuestion` | `ask_user_question` | 对等 |
| 计划模式 | `/plan` 斜杠命令 + `mode` + Plan 审批接口 | `exit_plan_mode` 工具 + `plan/mode` 事件 | 实现路径不同，能力对等 |
| 技能 | `Skill` | `skill` | 对等；dsh 分层注册表，XEYO 单目录 |
| 子代理 | `Agent` | `subagent` + `subagent_fork` + 3 个控制工具 | dsh 多控制面 + 多 provider（codex/claude-code/acp） |
| 目标 | 斜杠 `/goal` + `server/routers/goals.py` | `create_goal`/`get_goal`/`update_goal` 工具 + `goal/change` 事件 | dsh 模型可直接改目标；XEYO 偏人机命令 |
| 定时 | **未见**（有 `scheduler` DAG 但未接线） | `schedule_create/list/delete` | **dsh 独有（可用）** |
| 工作流脚本 | **未见** | `workflow` + `ralph` | **dsh 独有** |
| 代码执行（PTC） | **未见** | `run_code` + `ctx.codeRuntime` | **dsh 独有** |
| LSP | `Diagnostics`，源码注释明写 *"not a full LSP/IDE"*（`diagnostics_tool.py:1`） | `lsp` + `ctx.lsp` seam + `lsp-stdio` provider | **dsh 显著更强** |
| 网络 | `WebSearch`/`WebFetch` | `web_search`/`web_fetch` | 对等 |
| 会话历史查询 | `JournalQuery`（查 rewind 日志） | 5 个 session query 工具 | dsh 面更宽 |
| 记忆 | `Memory` + `memory/` 48 文件 | **未见**独立记忆工具（无 memory seam） | **XEYO 独有** |
| 桌面/UI 控制 | `XeyoUI` | 未见（`directoryPicker` 仅选目录） | **XEYO 独有** |
| 截图 | `Screenshot` | 未见 | **XEYO 独有** |
| 微信外发 | `SendToWeChat`（+ `channels/` 33 文件） | 未见 | **XEYO 独有** |
| Git 只读 | `Git` | 未见专用工具（走 bash） | **XEYO 独有（工具化）** |
| Notebook | `NotebookEdit` | 未见 | **XEYO 独有** |
| 自修改插件 | **未见** | 7 个 `cordis_*` 工具 | **dsh 独有** |
| Agent Teams | 有 `coord/` 工作池（feature-flag）+ 多会话 peer | experimental agent-team（默认禁） | 各有实现 |

### 8.4 工具接口形状

| | XEYO | dsh |
|---|---|---|
| 定义 | `Tool` Protocol：`name/schema/execute/is_read_only/is_concurrency_safe`（`tools/base_tool.py:23-43`）+ `ToolMeta` 静态登记（`meta.py:25-28`） | `ToolDefinition extends ToolSchema`：`output{schema,render,presentationMeta?}`、`execute(args,exec)`、`finalizeContent?`、`timeoutMs?`、`isConcurrencySafe?`、`presentCall/presentResult`（`core/tools/src/index.ts:214-270`） |
| 参数 schema | dict 直写 JSON Schema | `defineTool` + 自研 DSL 编译为 JSON Schema（`schema.ts:545-617`） |
| 注册 | `registry.register()` 清 `_schemas_cache` | `ToolRuntime.register(definition)` 经 `layers.effect`（`index.ts:1028-1053`） |
| 超时 | **未见 per-tool 超时**；只有 `AbortController` | `timeoutMs` + `timeout-policy` 包装 `tools/execute`，超时替换为 `{code:'TOOL_TIMEOUT'}`（`guard/timeout-policy/src/index.ts:55-81`） |
| UI 呈现 | GUI 侧按 toolActivity 动态生成 | `presentCall`/`presentResult` + `meta` 持久化（host presenter 保持纯函数，Web 卡由原始事件派生） |

---

## 9. 工具执行管线

### dsh（`docs/tool-execution-pipeline.md` + `core/tools/src/index.ts`）
`tool/call` → **`tools/pre-execute`**（hooks + permission + sandbox 判定，waterfall）→ 单调 guards → **`tools/execute`**（超时/重试/指标，可包装）→ tool body → `fs/write-intent`/`fs/edit-intent` → **`tools/post-execute`** → `finalizeContent` → **`tools/result`**（观察者）→ `tool/result` 事件。
- 事件定义：`index.ts:144/155/167/189`。
- 不变量：`tools/result` 发布前 exec 与 outcome 必须 **frozen**（`invariant.ts:23-28`）。

### XEYO
`_admit_tool_use`（配额 + 只读早并发）→ `run_tools_partitioned` → `tool.execute(input, abort)`（`tool_registry.py:149`）→ `store.append(tool_result_message)` + SSE。
- 权限判定在 `permissions/policy.py:evaluate_policy`（`:1319`），工具侧只看到 `Permission denied: {reason}`（中性结果型，`tool_registry.py:453-459`）。
- 插件 hooks（`extension/hooks.py`）挂在工具门禁接缝，默认关。

**差异**：dsh 的管线是**命名事件瀑布**（任何插件可插在 4 个点位）；XEYO 是**函数内联 + 一个 hook 接缝**。dsh 的可拦截性高一个量级。

---

## 10. 权限与审批

| 维度 | XEYO | dsh |
|---|---|---|
| 决策词表 | **ASK / ALLOW / DENY**（`PolicyDecision`，`policy.py:54-68`） | **ask / never** 策略 + 结果 `allowed-once`/`rejected`/`cancelled`/`unavailable`（`user-approval/src/types.ts:32`）——**无 DENY/ALLOW 词** |
| 判定顺序 | `deny_tools`→DENY → `mcp__*` → Mcp 网关 → `ALWAYS_ALLOW`→ALLOW → `OUTBOUND_ASK`→ASK → ASK 时查 grant（`policy.py:1404-1429`, `:1375-1386`） | aborted→cancelled → 策略 `never`→**确定性 rejected（先于 waterfall）** → `approval/request` waterfall → 无 answerer → `unavailable`（fail closed） |
| grant 指纹 | `v2:` + sha256(["mcp-tool", 注册名])[:32]；**参数不进指纹**（注入免疫，`store.py:444-456`）；v1 不兼容 | **未见**等价 grant 指纹概念；审批为一次性 |
| DENY 可否被 grant 穿透 | **不可**（`policy.py:1331`） | 不适用 |
| 挂起/恢复 | HTTP：`POST /v1/permission/resolve`、`/v1/ask/resolve`、`/v1/plan/{turn_id}/approve`（`server/routers/control.py:145,216,278`）；TTL 风险分级（`store.py:91-99`） | `ctx.approval` 一次性决策；`approval/asked`+`approval/decided` **入 session log**（`user-approval/src/index.ts:217,224`）且要求 open turn（`:77-84`） |
| 预设 | `readonly`/`workspace-write`/`full`（默认 workspace-write，`permissions/presets.py:11-12`） | `workspace-write`+ask / `danger-full-access`+never（两旋钮 = sandbox mode × approval policy，`permission-presets/src/index.ts:170-179`） |
| 模式 | `always`/`risk`/`never`/`allow`（`policy.py:75`） | 无对应四模式；只有 sandbox 三档 |
| 审计 | `approval/*` 事件 + `audit/` 模块 | 审批审计对入 log，可回放（turn 包裹） |

> **重要差异**：dsh 把「沙箱模式」当作权限的**主要旋钮**——权限≈隔离强度。XEYO 没有沙箱，权限=**工具级 grant + 危险名单**。两者的安全模型不是同一个东西。

---

## 11. 沙箱与隔离

| | XEYO | dsh |
|---|---|---|
| OS 级沙箱 | **完全没有**（全仓 grep `landlock`/`seatbelt`/`bwrap` 零命中，排除 venv 后） | **四平台后端**：Linux `bwrap` + `landlock`、macOS `seatbelt`、Windows `windows-acl`（`sandbox-local/src/index.ts:159` `PLATFORM_CHAINS`） |
| 原生实现 | — | `native/landlock-run`：`@deepseek-ai/node-addon-landlock-run`，`LAUNCHER_FAILURE_EXIT=125` |
| 云端沙箱 | — | `packages/e2b/`（E2B POC：`fs-e2b` + `subprocess-e2b`） |
| 降级 | — | **fail-closed**：请求受限模式但无可用后端 → 拒绝（`sandbox/src/index.ts:131-143`）；强制等级 `bwrap/landlock/seatbelt=full`、`windows-acl=partial`（`sandbox-local:177-187`） |
| 与文件系统的关系 | 权限层拦工具调用 | `fs-sandbox` 提供者：`read-only` 全拒 / `workspace-write` 限 `writableRoots` / `danger-full-access` 不围栏（`fs-sandbox/src/index.ts:122-134`） |
| 与 shell 的关系 | — | `bash-sandbox` 在 spawn 前 `ctx.sandbox.confine(argv, policy)`（`sandbox/src/index.ts:175`） |

> 这是 **dsh 领先最大的一项**。XEYO 的安全完全依赖「工具调用前判定」，一旦工具本身被绕过（例如 Bash 里 `rm -rf`），没有第二道防线。XEYO 侧对应物是 `bash_tool/destructive_guard.py`（关键词/模式级），属于**启发式**而非内核隔离。

---

## 12. 文件系统

| | XEYO | dsh |
|---|---|---|
| 统一通道 | `tools/*` 多数走 python 文件 API；`server/workspace_fs.py` 是**旁路**（默认拒直写，需 `XEYO_WORKSPACE_FS_WRITABLE=1`，`workspace_fs.py:39-41`，不穿权限/rewind） | 一律经 `ctx.fs`（`fs/src/index.ts` 注释：*tool-fs executes through ctx.fs*） |
| 默认只读 | 默认关闭（`fs-local` 的 `sandboxMode` 返回 `undefined`，只有挂载 `fs-sandbox` 才生效） | 由 `sandbox-policy` 部署默认 `read-only`（`sandbox-policy:112`） |
| 陈旧写守卫 | **未见** | `writeText` 带陈旧版本守卫（`fs-local:182-191`） |
| 读前写策略 | **未见**强制的 read-before-write | `fs-observation-policy`（`fs/*` 事件门，无 schema 变更）：未先读则拒绝写/编辑（`docs/tool-catalog.md:27`） |
| 事件 | — | `fs/write-intent`、`fs/edit-intent`、`fs/observed`（`fs/src/index.ts:58`） |

---

## 13. 子代理与多代理

| | XEYO | dsh |
|---|---|---|
| 实现 | `engine/subagent_runner.py`，**复用 `query_loop`**（不重建 QueryEngine），独立 MessageStore/BudgetTracker/WorkingSnapshot | `ctx.subagents` seam：`SubagentRuntime.start(name, request)`（`subagent/src/index.ts:554`） |
| Provider | 单一进程内实现 | `subagent-spawn-in-process`、`subagent-fork`、`subagent-acp`、**`subagent-claude-code`、`subagent-codex`**（后两者可选，`standard` preset 里 `disabled: true`） |
| 上下文继承 | `subagent_context.py`；侧链 `agents/{agent_id}.jsonl` 不污染主 JSONL | `child-agent.ts:68 parentAgentOptionsForDelegation`（继承 provider/model/effort/maxTokens）；`childSessionMeta`（继承 cwd/preset/parentSession/delegationDepth/origin） |
| 深/宽限制 | `_depth`/`max_depth`；`DEFAULT_SUB_MAX_TURNS=32` | `assertSubagentMaxDepth`（深度）；**未见全局 fan-out 上限**；冷列举并发 4 |
| 权限继承 | 未显式收窄 | **委托边界强制 `approvalPolicy:'never'`**（`child-agent.ts:245-246`），以 `source:'delegation'` 写入子日志 |
| 结果回流 | 结算事件 + `agent_settlement` T_now 块 | 一次性 `SubagentRun.result: Promise`；可续子代理经 `SubagentContinuationManager` 的 inbox（`sendMessage`/`steerPrompt`/`queuePrompt`） |
| 多代理团队 | `coord/` 工作池（feature flag）+ 多会话 peer 活动提醒 | `experimental/agent-team`：名册 + 共享任务 DAG + 邮箱（默认禁） |

---

## 14. 调度 / 后台任务 / Webhook / 工作流

| 能力 | XEYO | dsh |
|---|---|---|
| 定时任务 | `engine/scheduler.py`（**1110 行 DAG，审计确认为"写了无消费方"未接线**） | `ctx.schedule` 运行时（每 root agent 进程内定时器）+ `schedule_*` 三工具；`schedule/change` 事件持久化（`schedule/runtime.ts:77,268-294`） |
| 后台任务 | `job_*` 三工具 + `server/job_registry.py` | `ctx.jobs` seam + `jobs-local`；`job_*` 三工具；**kind-agnostic**（bash 后台/PTY send/子代理同一套控制器） |
| Webhook | **未见** | `ctx.webhookRuntime` + 规则注册 + `createWebhookSession`（`webhook/src/index.ts:58,89,126,142`）；示例 `webhook-github`（HMAC 校验、路由、`maxBodyBytes`） |
| 工作流脚本 | **未见** | `ctx.workflowEngine` + worker-thread 执行（`vm.Script`，`workflow-worker-thread/src/runtime.ts:91-115`），hooks `agent/parallel/pipeline/phase/log`，并发槽 `maxConcurrentAgents`/`maxTotalAgents`/`maxItemsPerCall` |

---

## 15. Skill 系统

| | XEYO | dsh |
|---|---|---|
| 目录/格式 | `.xeyo/skills/<name>/SKILL.md`（`extension/skill_loader.py`、`skill_store.py`）；本机实际只有 2 个：`awwwards-ui-design`、`map` | `SKILL.md` + YAML frontmatter（`name`/`description`），（`skill-filesystem/src/index.ts:672,725`） |
| 发现 | 单根目录 | **分层合并**：项目/用户/bundled 三源，`SkillRegistry` 分层覆盖（`skill/src/index.ts:358`） |
| 注入形态 | 经 T_now `skill_preinvoke` 块（用户 `/name` 直呼）+ `Skill` 工具按需加载 | 包成 `<skill_content name=…><skill_instructions>…</skill_instructions></skill_content>`（`skill/src/index.ts:172-185`）；用户直呼走 `skill-invocation` context 消息（`:148-161`） |
| 自带技能 | 2 个（用户级 `~/.workbuddy/skills` 另有） | **11 个**（`.agents/skills/`：`dsh-code-review`、`dsh-doc`、`dsh-prose-standard`、`dsh-ci-test-reliability`、`dsh-trim-cot-leakage`、`record-browser-gif` 等） |

---

## 16. MCP 与扩展层

| | XEYO | dsh |
|---|---|---|
| 配置 | `<root>/.xeyo/settings.json`（home + workspace 合并，**workspace 更具体者优先**；坏 JSON keep-last-good） | 插件即配置；MCP 由 `mcp-client` 单实例连单 server |
| 传输 | MCP client（`extension/mcp_client.py`） | `stdio`（command/args/env/cwd）或 `streamable-http`（url/headers）（`mcp-client/src/index.ts:50-98`） |
| 工具暴露 | `Mcp` **网关工具**：`action=list|describe|call|resources|read_resource`（`mcp_gateway.py`） | 直接注册进 `ctx.tools`，公共名 `mcp__<server>__<tool>`（`mcp-client/src/index.ts:3-5`） |
| tools 数组冻结 | **绝对红线**：`_schemas_cache` 会话内冻结、零前缀重缓存；会话内启停只发 T_now 活页块（`extension/reconcile.py:9-12`） | 同样冻结：attach 时快照决定哪些工具进 `schemas()`，会话内**永不触碰 `_schemas_cache`**（`AGENTS.md` 扩展层契约）；会话内新增工具的唯一通道是 `Mcp` 网关（**dsh 也有同名网关工具！**） |
| 权限 | 停用即 DENY，不可被 grant 穿越（`policy.py` 先于 grant 判定） | 走与原生工具相同的 `tools` 管线，无独立权限 |
| 其他扩展 | `plugins/`（manifest + hooks + 子进程执行） | 255 个包本身就是扩展；`ctx.dynamicCordisRunner` 运行期加载 |

> **意外的高度相似**：两边都独立演化出了「工具面会话内冻结 + 网关工具做会话内新增」的设计，连网关工具命名（`Mcp`）都一致。

---

## 17. Hooks

| | XEYO | dsh |
|---|---|---|
| 事件 | `PreToolUse`、`PostToolUse`、`PermissionRequest`、`SessionStart`、`SessionEnd`（`extension/hooks.py:36`） | `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`、`SubagentStop`（+`SubagentStart` 注入子上下文）（`hooks-claude-code/src/index.ts:207,222,240,249,271,294`） |
| 方言 | 自有 JSON（`XEYO_HOOK_CONTEXT`） | **双方言**：`HookDialect='claude-code'|'codex'`（`hook-protocol/src/types.ts:48,79`） |
| 决策 | 三分：Success / FailedContinue / FailedAbort；`PermissionRequest` 非 Success → **fail-closed DENY** | `allow/ask/deny/none` → 归一 `allow/deny/block`（`merge.ts:12`） |
| 执行 | 子进程，短超时（默认 600s），剥离 `GIT_*`，结果 stdout 作为 T_now 上下文块注入 | 经 `ctx.shell` 写 JSON payload 到 stdin；结果记 `hook/invoked`+`hook/result` 事件（`events.ts:75,92,99`） |
| 默认 | **关**（`hooks_enabled` 默认关，`extension/hooks.py` 文档头） | 由组合决定 |

---

## 18. 模型层与 provider

| | XEYO | dsh |
|---|---|---|
| 适配 | `python/model/` 10 文件：deepseek / openai / anthropic / fake（`docs/Anthropic原生适配器-实施记录.md`） | `ctx.llm` + `abstract class LlmAdapter`（唯一必需方法 `stream(options): AsyncIterable<StreamChunk>`，`llm/src/index.ts:197,278`）；`registerAdapter(providers, adapter)` 按 provider 路由，重复抛 `DUPLICATE_ADAPTER`（`:384`） |
| Provider | 3 家（+fake） | `llm-deepseek`（官方）、**`llm-pi-ai`**（库驱动，多厂商）、`llm-replay`（测试） |
| 思考态 | `docs/最终方案-思考态回放.md` + `docs/deepseek-harness-思考态实现考据.md`（**已专门考据过 dsh 的 `ReasoningBlock` 做法**） | `ReasoningBlock {type:'reasoning', text}` 明文字块（`llm/src/types.ts:59-63`）；`reasoning_effort` ∈ `off/low/high/max`（默认 high，`llm-deepseek/src/adapter.ts:165-186`）；`reasoning_content` delta → reasoning block（`translate.ts:155-164`） |
| 重试 | `LlmRetry`/`RetryStarted` 事件 | `llm-retry`：`normal`（maxRetries=5）/`always`；可重试码 `EMPTY_RESPONSE|RATE_LIMIT|SERVER|TIMEOUT|TRANSPORT`（`retry-policy.ts:18-24`） |
| 流 | SSE（OpenAI 兼容帧 + `xy.*` 扩展帧） | SSE 解析 `llm-deepseek/src/sse.ts` + `translate.ts`；`llm/stream` waterfall 可拦截 |
| KV 缓存 | **主动保前缀**（Date/Model 不进左段）+ 命中/未命中计费 | 只读回 `prompt_cache_hit_tokens`/`miss`（`translate.ts:56`、`types.ts:174-175`）；**请求侧无 `cache_control`/`prompt_cache` 参数** |
| wire 扩展 | — | `docs/deepseek-llm-api-wire-extensions.md`：顶层 `dsh_plugin_packages`（默认开）、`dsh_session_log`（默认关）+ 归因头 `x-deepseek-harness-user-id`/`session-id`/`compact` |

---

## 19. 成本与用量

| | XEYO | dsh |
|---|---|---|
| 价格表 | `usage/pricing.py`：DeepSeek flash/pro，**高峰(0.10/3.0/9.0)空闲减半**，`USD_CNY=7.2`（`:22-37`）；分时段 `time_tier`（北京 09-12/14-18 倍率 2.0，`:51-112`） | `route-pricing.ts` + 图像定价（`adapter.ts:369`） |
| 计量 | `split_usage` 拆 hit/miss/out（`query_loop.py:1271`）；以厂商权威 `prompt_tokens` 为准，投影估算兜底（`:1276-1284`）；`usage/ledger.py` / `attribution.py` / `combine.py` / `vendor.py` / `multi_agent_metrics.py` | `ctx.tokenMeter`（启发式估算，仅重放测量）；usage 随 `assistant/message` 事件一起落库（无独立 usage 记录） |
| 预算/死线 | **有**：`budget.py` + `runtime_budget`/`budget_mirror`/`wrap_up` T_now 块 + `forced_wrap_up` 收尾窗 | **未见** token 预算/死线机制 |

---

## 20. 记忆

| | XEYO | dsh |
|---|---|---|
| 实现 | `python/memory/` **48 文件**：投影、journal、compact、summarize、search、`simulator/`（离线标定） | **未见**独立记忆子系统 |
| 自动召回 | 存在但**恒关**（`python/engine/query_loop.py:356` `_memory_index_live_enabled` return False，09-09 事故后退役） | 不适用 |
| 工具面 | `Memory` 工具 | 不适用 |
| 替代方案 | — | 靠 `session-query`（查历史）+ `agent-instructions`（AGENTS.md）+ 项目文档；**没有跨会话长期记忆** |

---

## 21. 前端

| | XEYO（`gui/`） | dsh（`packages/client/` + `apps/web`） |
|---|---|---|
| 框架 | React **19.1.0** + Vite 6.3.5 | React（`platform.ts:8-13`） |
| 构建 | Vite + `tsc -b` | `tsdown`（CJS closure-factory bundle，`window.__ModuleLoader__.load`）+ lightningcss；`apps/web` 用 Vite |
| 状态 | zustand 5.0.5 + `@preact/signals-react` | `zustand/vanilla` + `immer` + `subscribeWithSelector`，**React-free 对象层**（`store/src/index.ts:14-23`） |
| 样式 | **Tailwind 4.1.7** | **CSS Modules + clsx + lightningcss**，明令禁 Tailwind/组件库（`docs/web-styling.md:15`），`--dsw-*` token |
| 组件合成 | 直接 import | **插槽系统**：`ctx.slots.register(...)`，4 种基数 `single/list/keyed/chain`，3 种作用域（`ui-slots/src/index.ts:772,90-93`）——**UI 也是插件** |
| 包数 | `gui/src` 单包（components 131 / lib 165 / stores 41 / hooks 10 …） | **50 个 client 子包**（38 个 `ui-*` + connection/file-upload/hmr/locale/modules/store/web） |
| 虚拟滚动 | `@tanstack/react-virtual`，>40 轮才窗口化（`VirtualRoundList.tsx:40`） | `@tanstack/react-virtual`（ui-trajectory）；`ui-conversation` 用 **lexical** |
| Markdown | `streamdown` + `react-syntax-highlighter` | `ui-primitives`（Markdown/shiki/katex） |
| 布局 | 固定（Sidebar + MessageList + Composer） | `ui-layout` + slots（`single|list|keyed|chain`） |
| 轨迹回看 | **未见**独立轨迹面板 | **`ui-trajectory`（40 文件/13,488 行）**：turn 感知事件账本、搜索索引、折叠、时间线区间选中、`loadOlder` 分页、来源标签（`TrajectoryView.tsx:147,210-310,380-383,500-504`） |
| HMR | Vite HMR | `client-hmr`：SSE `/plugins/events` → 热换 cordis fiber（`hmr/client/index.ts:104-140`） |
| i18n | **未见**（中文为主） | `locale` 包：命名空间字典 + `declare module` 合并，内置 `zh`/`en`（可加语言包，回退链必须终于 `en`，`locale/client/index.ts:447-455,315-334`） |
| 主题 | 存在（`stores`/主题目录） | `ui-theme`：`light|dark|system`（默认 system），boot 内联脚本防闪烁（`boot-theme.ts:12-23`） |
| 工具卡片 | 动态 verb 生成（`toolActivity.ts:13`）+ 文件变更 unified diff（`FilesChanged.tsx:3,8`） | keyed 插槽 `tool.call.toolview` + 原子视图 `bash/read/read-image/file-mutation/search/web/todo/ask-question`（`ui-tool/src/client/apply.ts:34-57`） |
| 审批/提问 | `PermissionDialog`/`AskUserDialog`/`PlanDialog` | `ui-approval`（chain 接管 composer，`ApprovalPanel.tsx:26-29`）+ `ui-user-questions`（`QuestionComposer` + `PlanReviewPanel`） |
| 设置 | `SettingsModal`（profiles/模型/权限/推理等级） | `ui-settings` + `ui-settings-general/models/plugins/plugin-inventory`；**每个 section 由注册它的 Host 插件拥有** |
| 桌面壳 | **Tauri 2（Rust 1,162 行）**：后端进程守护（10s 探活/30s 重启）、`python_exe_usable` 探测、`BACKEND_SPAWN_ERROR` 静态槽、透明无边框窗、桌宠独立窗（`pet.rs`） | **无桌面壳**（宿主只是 Node 进程 + 本地 HTTP） |

**XEYO 独有**：Tauri 原生壳、桌宠、桌面岛（pasture）、WebView2 数据隔离方案、`XeyoUI` 工具、Screenshot、Screenshot 驱动的 GUI 验证链路。
**dsh 独有**：插槽化插件 UI、Trajectory 面板、i18n 双语、HMR 热换、浏览器快照 e2e。

---

## 22. 服务端与协议

| | XEYO | dsh |
|---|---|---|
| 服务 | FastAPI（`python/server/app.py:292-364` 注册路由）+ SSE | Node HTTP/WS（`ctx.webServer`）；Typert RPC 网关（WebSocket mux） |
| 路由 | `server/routers/`：audit / chat / commands / control / extensions / goals / jobs / mcp / media / memory / plugins / references / rewind / sessions / skills / usage / workspace（18 个） | `packages/api/`（118 文件/38,948 行）：gateway / remotes / session-controller / settings-controller / workspace-controller |
| SSE 事件 | 25 类：`AssistantDelta`、`ReasoningDelta`、`ToolCallEvent`、`ToolProgressEvent`、`ToolResultEvent`、`FinalEvent`、`StoppedEvent`、`UsageEvent`、`ContextCompressionEvent`、`ResultEvent`、`PermissionPending/Resolved`、`AskUserPending/Resolved`、`PlanPending/Resolved`、`TaskStateEvent`、`LlmRetry/RetryStarted`（`msgtypes/events.py:7-22`） | `session/event`（durable）+ `agent/*`（live）+ `agent/assistant-stream`（process-local start/chunk/end）+ capability 事件（`fs/*`、`tools/*`、`telemetry/*`） |
| 类型化 RPC | **未见** | **Typert**：类型图生成器 + 运行时类型注册表 + 跨线 RPC（`typert/protocol/src/index.ts`、`registry/src/index.ts:17-27`）——**XEYO 没有对应物** |
| 断线恢复 | 前端直播流不自动重连；刷新后按 `cursor`（sessionStorage `turnCursor`）从 `/v1/sessions/{id}/turns/current/events?cursor=` 重放（`chatStream.ts:434-639`） | 日志即真相源，客户端按 seq 重连；`session/event` 广播 |

---

## 23. 对外集成（SDK / ACP / CLI）

| | XEYO | dsh |
|---|---|---|
| SDK | **未见**官方 SDK | **TS SDK**（`packages/sdk/`：protocol/client/server，newline-delimited JSON-RPC over stdio）+ **Python SDK**（`python/sdk/`：`HarnessClient`，`client.py:39-130`） |
| Python 运行时分发 | — | `python/sdk-runtime`：wheel 内打包 `deepseek-harness-sdk-runtime-<platform>-<arch>` **单文件 Node 可执行** + ripgrep 旁路 + macOS spawn-helper（`__init__.py:55-90`） |
| ACP | **未见** | `packages/acp/`：Agent Client Protocol server（`@agentclientprotocol/sdk`），暴露 initialize/new-session/resume/list/prompt/request-permission/cancel（`acp/src/index.ts:20-47`）；亦可作为子代理 provider |
| CLI | Typer：`version/setup/chat/attach/serve`、`coord run|status`、`sessions list|show|rm`、`config path|show|set`（`cli/main.py:123-321`） | `dsh`：`--profile`、`web`、`plugin --profile <n> <pnpm args>`、`--dump-config`、`--dump-default-config`、`--patch`、`-V`（`apps/cli/src/args.ts:117-191`） |
| 斜杠命令 | **35 条**（`slash/registry.py`：help/version/docs/clear/load/export/retry/goal/exit/mode/output/code/model/theme/approval/status/usage/context/cwd/ls/stop/allow/deny/compact/transcript/rule/doctor/proposals/run/git/diff/revert/skills/mcp/plugins），SSOT → 导出 TS manifest（`slash.export_manifest --check` 进门禁） | `ctx.commands`：`CommandDefinition`（name 必须 `^[a-z][a-z0-9_-]*$`），handler 返回 `CommandResult`（`commands/src/index.ts:60-75`）；`command/run`/`command/done` 事件 |

---

## 24. 凭据 / 设置 / 身份 / 遥测

| | XEYO | dsh |
|---|---|---|
| 凭据 | 未见独立 seam（配置 + 环境变量） | `ctx.credentials` seam：两层——`CredentialRef`（环境变量名，按 env/file/project-env/user-env 分层，每次操作重解，`credentials/src/index.ts:183`）+ `CredentialKey`（授权记录，`modifyRecord` 唯一写路径）；**值永不明文暴露** |
| 设置 | `settings.json` home + workspace 合并 | `ctx.settings` seam：`schema 默认 → composition base → 用户文档`（用户层覆盖 base，`settings/src/index.ts:740-753`）；**wire 前必 `redactSecrets`**（`:105-108,529`） |
| 身份 | 未见 | `ctx.identity`：随机 UUID v4 存 `$DSH_HOME/.anonymous-user-id`，**绝不取主机名/网络**（`anonymous-user-id/src/index.ts:26-29,54`） |
| 遥测 | `usage/` + `audit/` 模块（本地账本） | `ctx.sessionTelemetry` seam + `session-telemetry-otel`（OpenTelemetry）；XEYO 侧 grep `opentelemetry` 零命中 |

---

## 25. 测试与质量门

| | XEYO | dsh |
|---|---|---|
| 单测 | pytest `-q --timeout=60 -m "not live"`（`scripts/check.ps1:11`）；307 个文件 | vitest；863 个 spec；`resilience/edge case/event ordering/concurrency race` 为明确偏好 |
| 覆盖率门 | **未见** | **per-file 100% on `packages/*/*/src`**（`docs/testing.md:10`），"未覆盖的行往往是死代码" |
| 类型门 | `tsc -b`（gui）+ tui typecheck | `strict: true` + `noImplicitAny` + 每个 `any` 需解释；`verify-export-jsdoc` 强制 JSDoc |
| 契约门 | `slash.export_manifest --check`；`tests/test_t_now_block_registry.py`（块登记表一一对应执法）；`test_freeze_invariants.py` | **40+ 个 `verify-*` 脚本**：`verify-application-entrypoints`、`verify-cordis-config`、`verify-tool-catalog`、`verify-package-invariants`、`verify-md-links`、`verify-agent-note-classification`、`verify-skill-invocation-metadata`、`verify-translation-pairing`… |
| 快照 | 未见 | **录制会话回放**：`test:snapshot`（keyless 回放录制的 session 走真实 profile）、`test:expected`、`test:web`（Chromium 对比） |
| 真 API e2e | `-m "not live"` 排除，即**平时不跑** | `test:e2e` 显式跑真 API，**"We are DeepSeek — do not ration real-API tests"**（`testing.md:23`）；无 key 自跳过 |
| 不变式 | 分散在各 guard | `ctx.invariants` 注册表 + `packages/*/invariant` companion，违反抛 `InvariantError`（`runtime-diagnostics/invariants/src/index.ts:50-66`） |
| 已知失败 | 显式 `xfail` 并注明归属（实测仅 2 处，均在 `test_bash_isolated.py:25`） | 无 xfail 文化；改行为改测试并说明理由 |
| 提交门 | `scripts/check.ps1`（pytest + manifest + gui typecheck/vitest + tui typecheck），**无 hook 强制** | `lefthook.yml` + `pnpm run check:all` + CI 多平台矩阵（含 win-wine 观测道） |

---

## 26. 构建 / 打包 / 分发

| | XEYO | dsh |
|---|---|---|
| 产物 | **Tauri 应用**：NSIS + MSI（`gui/src-tauri/tauri.conf.json:37`），`resources/python/` 映射进安装目录（`:46-48`） | **npm 包**：`npx @deepseek-ai/dsh web`；profile 即分发单位 |
| Python 运行时 | `scripts/build_slim_venv.py`：用 `astral-sh/python-build-standalone` 造**自包含可重定位** venv（自带 DLL/标准库/VC 运行时），带**自包含性断言**；`pyvenv.cfg` 必须写 `home=.` | `python/sdk-runtime`：单文件 Node exe + ripgrep |
| 构建编排 | `scripts/build_installer.ps1`（3 步：精简 Python → slim venv → `tauri:build`） | `pnpm run build`（tsc → `lib/`，tsdown 打包） |
| 开发启动 | `XEYO.bat`（校验 node/py3.11 → 起后端 → 等 `/health` → `npm run tauri:dev`） | `pnpm dsh web`（源码启动走 `node --import tsx/esm`） |
| CI | `.github/workflows/ci.yml`：python(pytest) / gui(typecheck+test) / tui(typecheck) | `.gitlab-ci.yml` + `.github/`：多平台矩阵（linux-primary、static、coverage、snapshot、artifacts、consumers、windows-blocking/complete/observational、wine） |
| 容灾 | bare mirror（`D:/lea/XenYon-git-mirror-*.git`）+ 封存 `.git.broken-*`；**无 remote** | 标准 GitHub 仓库 + PR 栈工作流 |

---

## 27. 文档与协作规范

| | XEYO | dsh |
|---|---|---|
| 仓库级规范 | `AGENTS.md`（设计理念五条 + 工程硬规矩七条） | `AGENTS.md`（155 行）+ `packages/AGENTS.md` + `docs/AGENTS.md` + `vendor/AGENTS.md` + `snapshots/AGENTS.md` |
| 文档量 | 21 篇（含 3 篇审计、1 篇 BENCH 口径、1 篇 dsh 考据） | 363 个文件，含**生成式目录**（tool-catalog / config-catalog / capability-seams / module-graph / persistence-catalog / event-producer-consumer / graph-atlas）+ 40+ 子系统页 + postmortem |
| 双语 | 中文为主 | **强制双语**（`*.md` + `*.zh.md` + `*.i18n.yaml`），`verify-translation-pairing` 执法 |
| 变更伴随文档 | 未强制 | **非平凡改动必须同 PR 附 Agent Note**（`AGENTS.md:125`），归档笔记冻结不可改 |
| 散文规范 | 引擎文本铁律 | `dsh-prose-standard` 技能 + 禁用隐喻、禁用 `contract/boundary/shape` 滥用（`AGENTS.md:144`） |

---

## 28. 差异总表

### 28.1 dsh 有、XEYO 完全没有

1. **OS 级沙箱**（bwrap/Landlock/Seatbelt/Windows-ACL + E2B），fail-closed
2. **PTY 持久终端**（`ctx.terminals` + 6 个 terminal 工具 + 持久 bash/pwsh）
3. **代码执行 seam**（`ctx.codeRuntime`：worker-thread/process/container）+ **PTC 模式**（`run_code`）
4. **工作流脚本引擎**（`workflow` 工具 + worker-thread）与 `ralph`
5. **Webhook 入口**（`ctx.webhookRuntime` + GitHub 适配器）
6. **定时任务可用**（`schedule_*` 三工具）
7. **自修改**（7 个 `cordis_*` 工具，模型定义/挂载/停用自己的插件）
8. **会话历史自查询工具**（5 个 session-query 工具）
9. **LSP 能力缝**（`ctx.lsp` + `lsp-stdio` + `lsp` 工具）
10. **事件溯源会话日志**（`SessionEventMap` + `deriveMessages` + surface + 代际迁移）
11. **录制会话快照测试** + **浏览器快照 e2e**
12. **per-file 100% 覆盖率门**
13. **Typert 类型化 RPC**
14. **TS/Python 双 SDK** + **ACP 服务器**
15. **多 provider 子代理**（fork/codex/claude-code/acp）
16. **多厂商 LLM 适配器**（`llm-pi-ai`）
17. **插槽化插件 UI** + Trajectory 面板 + HMR + i18n
18. **Anonymous identity 与 OTel 遥测**
19. **双语言（中/英）文档体系 + Agent Note 制度**
20. **Profile/Bundle/Patch 三层组合**与 5 个应用形态
21. **`ctx.invariants` 包级不变式注册表**
22. **`fs-observation-policy`（读前写强制）**
23. **spill store**（超长文本落盘 + locator）
24. **`deepseek-llm-api-wire-extensions`**（请求侧扩展字段与归因头）

### 28.2 XEYO 有、dsh 完全没有

1. **工作区 rewind**（v2/v3，崩溃恢复顺序 orphan→fsync→原子替换 transcript→恢复工作区）
2. **跨会话长期记忆子系统**（`memory/` 48 文件 + `Memory` 工具 + 离线 simulator）
3. **预算/死线机制**（`budget.py`、`runtime_budget`/`budget_mirror`/`wrap_up`、forced wrap-up 收窗）
4. **T_now 注入管线 + 块登记表硬顶**（21 上限 + 逐条理由 + 机器执法）
5. **`env_channel` 伪造 tool 对声道**（说话人混淆根治）
6. **桌面原生壳**（Tauri：进程守护、`python_exe_usable` 真探测、`BACKEND_SPAWN_ERROR` 真实原因回显、自包含 slim venv 构建与断言）
7. **桌面 UI 控制工具**（`XeyoUI`）、**Screenshot**、**桌宠/桌面岛**
8. **微信通道**（`channels/` 33 文件：filehelper/ilink）
9. **`SendToWeChat`**、**`NotebookEdit`**、**`Git`（只读工具化）**、**`Diagnostics`**
10. **成本口径治理**（分时段峰谷价、`USD_CNY`、ledger/attribution/vendor/combine、多代理成本度量）
11. **斜杠命令 SSOT + 生成式 manifest 进门禁**（35 条命令）
12. **TUI（Ink）第二客户端**
13. **中文优先文档与应试性审查尺子**（R1–R4 四条的自我约束框架）
14. **`bash_routing` 透明路由**（纯读命令自动改用专用工具，带 `[routed: …]` 信号）
15. **多会话 peer 活动感知**（`peer_presence`/`file_conflict` 块 + 工作区索引）
16. **`workspace_fs` 只读旁路**与 `XEYO_WORKSPACE_FS_WRITABLE` 开关

### 28.3 同名不同实现（易混淆）

| 能力 | XEYO 做法 | dsh 做法 |
|---|---|---|
| 权限 | 工具级 ASK/ALLOW/DENY + grant 指纹 | 沙箱模式 × 审批策略两旋钮，无 DENY 词 |
| 计划模式 | 斜杠 `/plan` + 服务端审批接口 | `exit_plan_mode` 工具 + `plan/mode` 持久事件 |
| 子代理 | 单实现复用 query_loop，侧链 JSONL | seam + 5 种 provider，委托边界强制 `never` 审批 |
| 技能 | 单目录 + T_now 预注入 | 分层注册表 + `<skill_content>` 包装 |
| MCP | `Mcp` 网关工具 | 同名 `Mcp` 网关工具（独立演化出同一设计） |
| 后台任务 | `job_*` 三工具 | `job_*` 三工具（kind-agnostic 统一控制器） |
| 会话删除 | 归档门槛 409 `archived_required` | 代际不可删（提交代际永不删除） |
| 工具面冻结 | `_schemas_cache` 冻结 | 会话起点快照冻结 |
| 断线恢复 | cursor 重放 current turn events | 日志 seq 重放 |

---

## 29. 结论

**1. 两者是不同物种。** XEYO 是「一个引擎 + 一套注意力纪律 + 一个桌面产品」；dsh 是「一个运行时 + 一套组合理论 + 五个应用形态」。XEYO 把复杂度压在**信息正确性**上（模型看到什么、看不到什么、为什么）；dsh 把复杂度压在**结构可替换性**上（任何一块能不能被换掉）。

**2. dsh 在"工程完备度"上全面领先。** 沙箱、PTY、LSP、工作流、webhook、定时、事件溯源日志、快照测试、100% 覆盖门、双 SDK、ACP、i18n 双语、生成式文档——这些都是 XEYO 没有的**基础设施级**能力。差距不是"差几个功能"，而是"缺的是同一层东西"。

**3. XEYO 在"注意力治理"与"成本治理"上领先。** T_now 管线 + 21 硬顶 + 逐块理由 + 机器执法，dsh 没有等价物（dsh 只有"model-visible ⟺ logged"这一条**可审计性**约束，不约束内容性质）。预算/死线机制、峰谷定价口径、rewind 工作区回滚、跨会话记忆，dsh 也都没有。

**4. 最值得 XEYO 借鉴的三件事**（按性价比排序）：
- **事件溯源会话日志**：把 transcript 从"消息级"升到"事件级"，并把 `request/header` 入日志——这是"模型到底看到过什么"唯一可逐字重建的方案，也是 fork/resume/telemetry/迁移的公共底座。XEYO 现在靠投影函数重算，无法证明。
- **沙箱执行层**：`ctx.sandbox.confine(argv, policy)` + fail-closed。XEYO 目前只有"工具调用前判定 + destructive_guard 关键词"，一旦落到 Bash 就没有第二道防线。
- **能力缝三角色 + 命名事件瀑布**：不需要照搬 Cordis，但把 `query_loop` 里的 4 个点位（pre-step / request / llm stream / 工具三段）改成命名事件，就能让今天的 guard 从"改引擎"变成"挂插件"。

**5. 最值得 dsh 借鉴的一件事**：**T_now 式的注入治理**（白名单 + 硬顶 + 逐条存在理由 + 机器执法）。dsh 的插件自由是双刃剑——谁的插件都能往上下文塞东西，而它只有"可重建"这一条底线，没有"这条内容该不该出现在注意力里"的门。

**6. 一个共同的收敛点。** 两边独立演化出了相同的两条结论：**①工具面会话内冻结（保 KV 前缀缓存）；②会话内新增工具只能走网关工具。** 这说明这两条不是实现选择，而是长会话 Agent 的结构性必然。

---

*取证边界：本文覆盖 `D:\lea\dsh-src` 全部 9080 个受控文件的模块级通读（其中核心包逐文件读；前端 38 个 `ui-*` 包按入口/slot/contract 读，组件内部实现未逐行读）与 XEYO `python/`(1141 文件) + `gui/src`(391 文件) + `tui/`(16 文件) + `gui/src-tauri`(3 文件) 的模块级通读。凡标"未见"处均为可检索面穷举后未命中。*
