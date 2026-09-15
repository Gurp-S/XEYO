# XEYO × DeepSeek Harness 逐字段级对比（第四轮）

> 前三轮：功能面（605 行）→ 设计面（1307 行）→ 实现面（2246 行）。
> 本轮只做一件事：**把每个类型、每个字段、每个常量、每条分支、每个键名穷举出来**，并给出字段级差异矩阵与行为对照用例。
> 设计动机、功能清单、架构评述**本轮不重复**；若与前轮冲突，以本轮实测为准（本轮全部为主代理直读源码 + 逐条命令行实测）。

**代码库基线**

| | dsh | XEYO |
|---|---|---|
| 路径 | `D:\lea\dsh-src` | `D:\lea\XenYon code` |
| 版本 | `0.1.3-alpha.1` / commit `d347e70` / master | 工作树（本日 20:26 快照） |
| 语言 | TypeScript monorepo（Cordis 插件） | Python 引擎 + React/TS + Rust 壳 |
| 包/模块粒度 | **255** 个 `packages/<组>/<子包>/` | 1 个 `python/` + `gui/` + `tui/` |

**本轮实测规模（全部命令行得出，非估算）**

| 指标 | dsh | XEYO |
|---|---|---|
| 源文件 | `src` 下 `.ts/.tsx` **1611** | `python` `.py` **1141** / `gui/src` **391** / rust **3** |
| 代码行 | （前轮 767,579 含测试） | python **160,772** / gui **81,484** / tui **3,544** / rust **1,162** |
| 测试文件 | `.spec.ts/.test.ts` **863** | pytest **307** / vitest **102** |
| 会话事件类型 | **51** | 事件 dataclass **20** / 联合成员 **19** |
| 工具 | 目录条目 **62** / 唯一工具名 **57** | **26**（单表 14 字段） |
| HTTP 路由 | —（RPC，见 §16） | **101** |
| 斜杠命令 | —（`command/*` 事件 + 各包自有命令） | **35** |

---

## §0 本轮方法、取证边界与三处更正

### 0.1 取证方法

1. **主代理直读**：本轮不依赖子代理转述。全部结论来自 `Read` 精读 + Python/`grep` 精确切片。
2. **枚举一律脚本化**：事件名、工具名、路由、字段表全部用 Python 正则 + 花括号计数提取，不用 `grep -c` 估。
3. **每条断言带 `文件:行号`**；无法核实的写「未见」。
4. **否定判断必须穷举**：凡「XEYO 没有 Y」一律先做排除 `.venv` / `node_modules` 的全仓检索。

### 0.2 本轮对前轮的三处更正

**更正 A（第三轮计数错）：dsh 会话事件是 51 个，不是 48 个。**

第三轮用 `^\s{4}'...'` 固定缩进 + `[a-z-]+/[a-z-]+` 单斜杠正则提取，**漏掉了双斜杠键名**：

- `agent/inbox/spliced`（`core/agent/src/types.ts`）
- `team/message/queued`（`experimental/agent-team/src/types.ts`）
- `team/message/delivered`（同上）

48 + 3 = **51**。本轮第一次提取时我自己也踩了同一个坑（正则 `'([a-z0-9-]+/[a-z0-9-]+)'` 同样只允许一个斜杠），改用 `'([a-z0-9-]+(?:/[a-z0-9-]+)+)'` 后才正确。

**教训**：事件键名的 **段数不固定**（1 段命名空间 + 1~2 段名）。任何"固定段数"的提取模式都会静默漏数。

**更正 B（第三轮计数对、表述需精确）：`SESSION_FORMAT_VERSION = 2`，且 dsh 自己写明了"什么时候该 bump"。**

原文 rationale 值得逐字引用（`packages/core/session/src/types.ts:64-85`）：

> The version is a single monotonic integer with no major/minor split. Whether a bump is needed is decided by what the **WRITER** emits, never by what a newer reader can accept: bump exactly when an older runtime could no longer handle a new log with full semantic correctness ("parses without error" is not correctness — silently skipping content that shapes reconstruction is a wrong read). Only structural changes reach that bar: the header shape, the `SessionEvent` envelope, core event semantics, or the surface mechanism. **Adding an ordinary event type does not bump** — the per-event `SessionEvent.ignorable` guard covers vocabulary growth instead. When in doubt, bump: a near-identity upgrade step is almost free, a missed bump makes older runtimes read new logs wrong silently.

即：**加事件类型不升版本号，靠 `ignorable` 标记兜住词汇增长**。这条设计在 XEYO 侧无对应物（XEYO 的 JSONL 无版本号、无 ignorable 语义）。

**更正 C（口径澄清）：dsh 的"工具目录 62 条"不等于 62 个工具。**

`docs/tool-catalog.md` 有 **62 个 `### ` 条目**，但去重后 **57 个唯一工具名**——因为同名工具存在多 provider 变体（`bash` 有 local + persistent 两个包；`pwsh` 同理；`interrupt_agent`/`list_agents`/`send_message` 在 subagent-control 与 agent-team 两处各有一份）。

---

## §1 会话数据模型：逐事件、逐字段

### 1.1 dsh —— `SessionEventMap` 全 51 事件

**声明分布（51 = 12 核心 + 39 插件）**

| 命名空间 | 条数 | 声明文件 |
|---|---|---|
| `turn/` `step/` `user/` `assistant/` `tool/` `request/` `session/`（核心 12） | 12 | `core/session/src/types.ts` |
| `tool/code-dispatch*` | 2 | `core/tools/src/types.ts` |
| `compaction/` | 4 | `compaction/compaction/src/types.ts` |
| `team/` | 4 | `experimental/agent-team/src/types.ts` |
| `tool-workflow/` | 4 | `workflow/tool-workflow/src/types.ts` |
| `approval/` | 3 | `interaction/user-approval/{types,index}.ts` |
| `session/`（title ×2 + end-seed） | 3 | `session/session-title*/src/index.ts` |
| `assistant/` | 2 | `core/session/src/types.ts` |
| `command/` | 2 | `interaction/commands/src/types.ts` |
| `hook/` | 2 | `hooks/hook-protocol/src/types.ts` |
| `llm/` | 2 | `llm/llm-retry/src/types.ts` |
| `request/` | 2 | `core/session/src/types.ts` |
| `step/` `subagent/` `session-log-deepseek/` | 各 1~2 | 见下 |
| 其余单条 | 8 | 见下 |

**核心 12 事件逐字段（`core/session/src/types.ts`）**

| # | 事件 | 行 | payload 字段 | 何时发 | 进投影? |
|---|---|---|---|---|---|
| 1 | `turn/start` | 267 | `turn: number` | 循环在 claim 排队输入 / pre-step 之前开启 | ❌ log-only |
| 2 | `turn/end` | 276 | `turn: number` + `reason: TurnEndReason` | 用结束原因关闭 turn | ❌ |
| 3 | `step/start` | 278 | `turn: number`, `step: number` | 开启一步（一次模型调用 + 其请求的工具执行） | ❌ |
| 4 | `step/end` | 280 | `turn: number`, `step: number` | 关闭一步 | ❌ |
| 5 | `user/message` | 288 | `UserMessage`（整体，**无包装**） | 三类来源：真人 prompt / `agent.inject()` 合成上下文 / goal 续跑轮；靠 `source` 区分 | ✅ **surface** |
| 6 | `assistant/message` | 299 | `turn`, `step`, `message: AssistantMessage`, `stream: AssistantStreamRecord[]`, `usage?: TokenUsage`, `interrupted?: true` | 一步的组装后助手消息 | ✅ **surface** |
| 7 | `assistant/attempt` | 313 | `turn`, `step`, `stream: AssistantStreamRecord[]` | 一次**未提交 surface 消息**的模型尝试（失败/重试/取消/流错） | ❌ |
| 8 | `tool/call` | 319 | `turn`, `step`, `callId: ToolCallId`, `name: string`, `arguments: string` | 模型请求一次工具调用；`arguments` 是**未解析的原始 JSON 字符串** | ❌（配对用） |
| 9 | `tool/result` | 331 | `turn`, `step`, `message: ToolResultMessage`, `error?: {name, code}`, `meta?: JsonValue` | 工具调用完成 | ✅ **surface** |
| 10 | `request/header` | 342 | `header: EpochHeader`, `reason: RequestHeaderReason`, `startsSeries?: true` | 请求前记录完整头（config + system + tools） | ❌ log-only |
| 11 | `request/context` | 352 | `RequestContext`（`provider`, `model`, `contextWindow?`） | 路由或容量变化时才记 | ❌ |
| 12 | `session/end-seed` | 375 | `inherited?: true` | 构造器种子结束标记 | ❌ |

**`EpochHeader` 逐字段**（`:223-232`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `config` | `LlmCallConfig` | provider / model / reasoningEffort / 采样标量 |
| `adapterDefaults?` | `LlmCallConfigAdapterDefaults` | 由适配器**实际物化**（非调用方提议）的字段 |
| `system?` | `string` | 渲染后的 system prompt 全文；无 system 的请求缺席 |
| `tools?` | `ToolSchema[]` | 装配后的工具 schema；无工具请求缺席 |

**`SessionHeader` 逐字段**（`:91-128`）

| 字段 | 类型 | 可选 | 语义 |
|---|---|---|---|
| `version` | `typeof SESSION_FORMAT_VERSION`（=2） | 否 | 逻辑格式版本 |
| `id` | `SessionId`（branded） | 否 | 会话 id |
| `createdAt` | `number` | 否 | Unix epoch **毫秒** |
| `cwd?` | `string` | 是 | 创建时的绝对工作目录 |
| `parentSession?` | `SessionId` | 是 | fork 血缘 |
| `isSeeded` | `boolean` | 否 | 是否含 fork 继承前缀 |
| `origin?` | `'subagent'` | 是 | 子代理子会话的产品分类（**仅展示元数据**，不证明可续跑） |
| `delegationDepth?` | `number` | 是 | 委派深度；持久化以便**递归预算跨重启存活** |
| `agentPreset?` | `string` | 是 | 组合本会话 agent 的 preset id；持久化因 preset 决定工具与提示 |

**`SessionEvent` 包封逐字段**（`:447-476`）

| 字段 | 类型 | 条件 | 语义 |
|---|---|---|---|
| `type` | `K extends SessionEventType` | 必有 | 判别式 |
| `seq` | `SessionSeq`（branded，非负安全整数） | 必有 | 会话内单调序号 |
| `time` | `number` | 必有 | Unix epoch ms |
| `data` | `SessionEventMap[K]` | 必有 | payload |
| `ignorable?` | `true` | 可选 | **缺席 = 必需**：读者遇到不认识的 type 且无此标记，必须**拒绝重建**而非静默丢弃 |
| `sourceEventSeqs?` | `SessionSeq[]` | 仅 surface 三事件 | 本事件引用的更早来源事件（如被 compaction 遮蔽的 surface 节点） |
| `surfaceOp?` | `SurfaceOp` | 仅 surface 三事件 | 如何进入有序 surface |

**surface 机制逐字段**

- `SurfaceEventType = 'user/message' | 'assistant/message' | 'tool/result'`（`:387-390`）——**只有这 3 个类型能产生 LLM 消息**。
- `SurfaceOp = 'append' | { op: 'replace'; start: SessionSeq; end: SessionSeq }`（`:416-418`）——`replace` 用于 compaction，且 `sourceEventSeqs` 必须包含每一个被遮蔽的 surface 节点。
- `SessionEventSurface = 'current' | 'shadowed' | 'log-only'`（从 api-catalog 声明反推，`extensions/tool-cordis/src/api-catalog.ts`）——把"日志里的事件"分成三态，UI/检索按此过滤。
- `RequestHeaderReason = 'initial' | 'resume' | 'change' | 'series'`（`:252`）。
- `TurnEndReasonMap` 6 变体（`:192-213`）：`completed` / `aborted{reason}` / `blocked` / `error{error: LlmFailure}` / `max-tokens` / `interrupted`。
  - `interrupted` 的注释极重要：**「崩溃孤儿 turn 由 resume 事后补关；循环从不活体发出该标记，崩溃前的事件保持完整」**——这是 XEYO「中断锚」的同类问题，dsh 的解法是"事后补一个类型化 closer"。
- `AgentCancelCause` 4 变体（`:180-184`）：`user` / `parent` / `hook{reason}` / `disposed`；`TurnEndCancelCause` 再加 `legacy`。

**插件 39 事件逐条（名 + 声明文件 + 一句话）**

| 事件 | 声明文件 | 语义 |
|---|---|---|
| `agent-preset/selected` | `preset/agent-presets/src/session.ts` | 本会话选定的 agent preset |
| `agent/inbox/spliced` | `core/agent/src/types.ts` | 收件箱队列被拼接（目标、起点、移除数、插入的 UserMessage[]、`outcome?: 'canceled'`） |
| `approval/asked` | `interaction/user-approval/src/types.ts` | 审批请求挂起 |
| `approval/decided` | 同上 | 审批结果 |
| `approval/policy` | `interaction/user-approval/src/index.ts` | 审批策略变更（**log-only**） |
| `command/run` | `interaction/commands/src/types.ts` | 斜杠命令开始 |
| `command/done` | 同上 | 斜杠命令结束 |
| `compaction/start` | `compaction/compaction/src/types.ts` | 压缩开括号（`{compactionId, sourceCommandId?, turn: number\|null}`） |
| `compaction/summary` | 同上 | 摘要体 + 被遮蔽区间 + token 计数 + provider/model/maxTokens/usage + `llmStreamCall` 判别 |
| `compaction/end` | 同上 | 压缩闭括号（含 `error?: string`） |
| `compaction/prune` | 同上 | 工具结果裁剪（无 LLM 参与的纯确定性压缩） |
| `feedback/record` | `feedback/command-feedback/src/index.ts` | 用户反馈落账 |
| `goal/change` | `goal/goal/src/domain.ts` | goal 状态变化 |
| `hook/invoked` | `hooks/hook-protocol/src/types.ts` | 钩子被调用（`{turn, point, dialect, matcher?, handlerId}`） |
| `hook/result` | 同上 | 钩子结果（`{turn, point, handlerId, decision, exitCode?, stderrSummary?, durationMs}`） |
| `llm/retry` | `llm/llm-retry/src/types.ts` | 重试调度决策 |
| `llm/retry-started` | 同上 | 重试实际开始 |
| `model/selection` | `api/session-controller/src/types.ts` | 模型选择 |
| `permission/preset` | `interaction/permission-presets/src/index.ts` | 权限预设切换（whole-value knob） |
| `plan/mode` | `plan/plan-mode/src/index.ts` | plan 模式（**as logged state**） |
| `sandbox/mode` | `sandbox/sandbox-policy/src/session-mode.ts` | 沙箱模式切换（**log-only**，含 `source?: 'delegation'`） |
| `schedule/change` | `schedule/schedule/src/types.ts` | 定时任务变更 |
| `session/title` | `session/session-title/src/index.ts` | 会话标题 |
| `session/title-llm-request` | `session/session-title-llm/src/index.ts` | 标题生成请求 |
| `session-log-deepseek/delivery-accepted` | `session/session-log-deepseek/src/types.ts` | 远端投递被接受 |
| `subagent/descriptor` | `subagent/subagent/src/descriptor.ts` | 子代理身份描述符 |
| `subagent/model-selection-policy` | `subagent/tool-subagent/src/model-selection-state.ts` | 子代理模型选择策略 |
| `team/member` | `experimental/agent-team/src/types.ts` | 团队成员快照（`version: 2`） |
| `team/task` | 同上 | 团队任务快照（`version: 2`） |
| `team/message/queued` | 同上 | 团队消息入队 |
| `team/message/delivered` | 同上 | 团队消息投递 |
| `todo/write` | `todo/tool-todo/src/types.ts` | 待办写入 |
| `tool-workflow/run-start` / `run-end` | `workflow/tool-workflow/src/types.ts` | workflow 运行括号 |
| `tool-workflow/agent-start` / `agent-end` | 同上 | workflow 内子 agent 括号 |
| `tool/code-dispatch-start` | `core/tools/src/types.ts` | PTC 子调用开始（`{rootCallId, parentCallId, subCallId, name, arguments}`） |
| `tool/code-dispatch` | 同上 | PTC 子调用结算（+`isError`, `content: ContentBlock[]`） |
| `web/deepseek-search-llm-request` | `web/web-search-deepseek/src/provider.ts` | 搜索用的 LLM 请求 |

> **注意 `team/*` 与 `tool/code-dispatch*` 的 `version` 字段**：事件 payload 自带版本号，是 dsh 应对"事件词汇演进"的第二层机制（第一层是 `ignorable`，第三层是 `SESSION_FORMAT_VERSION`）。

### 1.2 XEYO —— 20 个 dataclass / 19 个联合成员

**文件**：`python/msgtypes/events.py`（333 行）

| # | dataclass | 行 | 字段（名:类型=默认） | 是否入 `EngineEvent` 联合 |
|---|---|---|---|---|
| 1 | `AssistantDelta` | 26 | `text: str`; `type="assistant_delta"` | ✅ |
| 2 | `ReasoningDelta` | 32 | `text: str`; `type="reasoning_delta"` | ✅ |
| 3 | `ToolCallEvent` | 38 | `name: str`; `input: dict`; `tool_use_id=""`; `input_summary=""`; `parallel=False`; `type` | ✅ |
| 4 | `ToolProgressEvent` | 49 | `name`; `tool_use_id=""`; `message=""`; `elapsed_ms=0`; `xy: dict\|None=None`; `type` | ✅ |
| 5 | `ToolResultEvent` | 65 | `name`; `output: str`; `is_error=False`; `tool_use_id=""`; `todos: list\|None`; `operation_id: str\|None`; `ui: dict\|None`; `duration_ms=0`; `spilled=False`; `type` | ✅ |
| 6 | `FinalEvent` | 83 | `text`; `prompt_tokens`; `completion_tokens`; `cache_hit_tokens`; `cache_miss_tokens`; `usd`; `used_usd`; `usd_limit`; `type` | ✅ |
| 7 | `StoppedEvent` | 97 | `reason: Literal[6 值]`; `budget_used_usd`; `budget_limit_usd`; `interrupted=False`; `type` | ✅ |
| 8 | `UsageEvent` | 108 | `prompt_tokens`; `completion_tokens`; `cache_hit_tokens`; `cache_miss_tokens`; `tokens`; `used_tokens`; `usd`; `used_usd`; `cny`; `used_cny`; `cost_source="estimate"`; `usd_limit`; `context_tokens`; `context_limit`; `context_breakdown`; `compact_cursor=0`; `last_action=""`; `c2_summary_chars=0`; `type`（**19 字段，全文件最重**） | ✅ |
| 9 | `ContextCompressionEvent` | 138 | `phase: Literal["start","complete"]`; `source: Literal["automatic","manual"]="automatic"`; `context_tokens`; `context_limit`; `type` | ✅ |
| 10 | `ResultEvent` | 149 | `subtype: Literal[7 值]`; `result=""`; `is_error`; `duration_ms`; `num_turns`; `session_id`; `stop_reason`; `budget_used_usd`; `budget_limit_usd`; `type` | ✅ |
| 11 | `PermissionPendingEvent` | 173 | `request_id`; `tool_name`; `tool_input`; `reason`; `prompt`; `path`; `expires_at`; `choices: list[str]=[]`; `peer_summary=""`; `intent="confirm"`; `type` | ✅ |
| 12 | `PermissionExpiringEvent` | 195 | `request_id`; `expires_at`; `seconds_left=30.0`; `type` | ❌ **不在联合里** |
| 13 | `PermissionResolvedEvent` | 205 | `request_id`; `approved: bool`; `actor=""`; `reason=""`; `resolved_at`; `choice=""`; `type` | ✅ |
| 14 | `AskUserPendingEvent` | 219 | `request_id`; `session_id`; `turn_id`; `question`; `options: list[str]=[]`; `default`; `expires_at`; `type` | ✅ |
| 15 | `AskUserResolvedEvent` | 237 | `request_id`; `answer=""`; `actor=""`; `timeout=False`; `resolved_at`; `type` | ✅ |
| 16 | `PlanPendingEvent` | 249 | `request_id`; `session_id`; `turn_id`; `plan`; `expires_at`; `type` | ✅ |
| 17 | `PlanResolvedEvent` | 261 | `request_id`; `approved`; `actor`; `reason`; `resolved_at`; `type` | ✅ |
| 18 | `TaskStateEvent` | 273 | `session_id`; `turn_id`; `task_status`; `current_tool`; `interruptible=True`; `error`; `type` | ✅ |
| 19 | `LlmRetryEvent` | 286 | `attempt`; `next_retry_ms`; `retry_code`（`code`）; `message=""`; `provider=""`; `model=""`; `type` | ✅ |
| 20 | `LlmRetryStartedEvent` | 303 | `attempt`; `provider=""`; `model=""`; `type` | ✅ |

**枚举取值逐条**

- `StoppedEvent.reason`（`:99`）：`max_turns` / `max_tool_calling` / `aborted` / `budget` / `budget_usd` / `wall`（**6 值**）
- `ResultEvent.subtype`（`:153-161`）：`success` / `error_max_turns` / `error_max_tool_calling` / `aborted` / `budget` / `budget_usd` / `error_during_execution`（**7 值**）
- `PermissionResolvedEvent.choice`（`:215` 注释）：`allow` / `deny` / `remind` / `timeout`（**4 值**）
- `PermissionPendingEvent.intent`（`:191`）：`confirm` / `choice` / `plan-review`（**3 值**）
- `PermissionExpiringEvent.seconds_left` 默认 **30.0**（提前 30s 预告）
- `AssistantDelta.type` = `"assistant_delta"`，但 **server 目录里零命中**——它在 SSE 层被编码成 OpenAI 兼容 chat chunk（见 §16）。

### 1.3 字段级差异矩阵（会话模型）

| 维度 | dsh | XEYO | 差异性质 |
|---|---|---|---|
| 事件类型总数 | **51** | 20（19 生效） | dsh 多 31 个；多出的绝大多数是插件域（team/workflow/compaction/hook/schedule/goal） |
| payload 版本号 | 部分事件自带 `version`（`team/*` = 2） | 无 | dsh 可演进而旧读者仍可判 |
| 未知事件策略 | **`ignorable` 缺席即拒绝重建** | 无（未知 type 静默） | dsh fail-closed，XEYO fail-open |
| 日志格式版本 | `SESSION_FORMAT_VERSION = 2` + 迁移链 + `.v2` fixture | **无版本号** | dsh 有迁移工程，XEYO 无 |
| surface 概念 | 显式三态（current/shadowed/log-only）+ `SurfaceOp` + `sourceEventSeqs` | 无（transcript 直出） | dsh 有"投影层"，XEYO 无 |
| 事件封套字段 | `type/seq/time/data/ignorable/surfaceOp/sourceEventSeqs` | 无统一封套（dataclass 各自带 `type` 字符串） | dsh 统一包封，XEYO 扁平 |
| 时钟 | `time`（epoch ms） | 无（`resolved_at`/`expires_at` 局部有） | dsh 每条可排时，XEYO 仅挂起类有 |
| 顺序 | `seq` 单调 + 区间/游标类型（`SessionSeq`/`SessionSeqCursor`/`SessionLogOffset`） | 无序号 | dsh 类型化游标，XEYO 依赖数组下标 |
| tool 参数形态 | `arguments: string`（**原始 JSON 字符串，未解析**） | `input: dict`（已解析） | dsh 保原始字节，XEYO 已丢格式 |
| tool 错误 | `error?: {name, code}`（结构化） | `is_error: bool` + 文本 | dsh 有错误码，XEYO 只有布尔 |
| 中断 | `TurnEndReasonMap.interrupted` 事后补写 closer | `StoppedEvent.interrupted` + 落史锚 | 同题不同解 |
| 只读观测 | `SessionObservation{source: 'live'\|'prepared', projections?, retain()}` | 无 | dsh 有观察者协议 |

---

## §2 工具协议：逐字段

### 2.1 dsh —— ToolSchema 与内容块

**发给 LLM 的 schema 形状（`llm/llm/src/types.ts`）**

```ts
export interface ToolSchema {
  name: string
  description: string
  parameters: Record<string, unknown>   // JSON Schema
}
```

**只有 3 个字段**。dsh 的 schema 从 `packages/core/tools/src/{json-schema,schema,ptc,ts-types,py-types}.ts` 生成——`ts-types.ts` / `py-types.ts` 的存在说明它能从 **TS 类型或 Python 类型**推导 schema，而 `json-schema.ts` 是手写路径。三条路径并存（本轮未逐行读这三个文件，属"未见细节"）。

**`ContentBlock` 6 变体逐字段**

| 变体 | 字段 |
|---|---|
| `TextBlock` | `type: 'text'`, `text: string` |
| `ReasoningBlock` | `type: 'reasoning'`, `text: string` |
| `ImageBlock` | `type: 'image'`, `attachment: ImageAttachmentRef` |
| `FileBlock` | `type: 'file'`, `attachment: FileAttachmentRef` |
| `ToolCallBlock` | `type: 'tool-call'`, `id: ToolCallId`, `name: string`, `arguments: string` |
| `ToolResultBlock` | `type: 'tool-result'`, `toolCallId: ToolCallId`, `content: ContentBlock[]`, `isError?: boolean` |

**`FinishReason` 5 变体**：`stop` / `tool-calls` / `max-tokens` / `aborted{failure: LlmFailure}` / `error{failure: LlmFailure}`。

**`TokenUsage` 6 字段**：`inputTokens`, `outputTokens`, `totalTokens?`, `cacheReadTokens?`, `cacheWriteTokens?`, `reasoningTokens?`。

**`LlmFailure` 5 字段**：`message`, `code`, `status?`, `providerRetryAfterMs?`, `requestId?`。

**`StreamChunk` 7 变体（流式协议逐条）**

```ts
export type StreamChunk =
  | { type: 'block-start';     index: number; blockType: ContentBlockType }
  | { type: 'text-delta';      index: number; text: string }
  | { type: 'reasoning-delta'; index: number; text: string }
  | { type: 'tool-call-delta'; index: number; id: ToolCallId; name?: string; argumentsDelta: string }
  | { type: 'block-end';       index: number; block: ContentBlock }
  | { type: 'usage';           usage: TokenUsage }
  | { type: 'finish';          reason: FinishReason; replayState?: ReplayEnvelope }
```

**关键设计**：dsh 的流是**显式块生命周期**（`block-start` → 若干 delta → `block-end`），且 `finish` 带 `replayState`（可重放封套）。XEYO 的 provider 流是隐式累积（无 block-start/end，见 §10）。

**`GenerateOptions` 逐字段**：`provider`, `model`, `reasoningEffort?`, `messages`, `system?`, `tools?: ToolSchema[]`, `temperature?`, `maxTokens?`, `stop?: string[]`, `signal?: AbortSignal`, `sessionId?`。

### 2.2 XEYO —— `ToolMeta` 14 字段 + 26 工具全表

**`ToolMeta` 逐字段（`python/tools/meta.py:24-48`）**

| # | 字段 | 类型 | 默认 | 语义（原文注释） |
|---|---|---|---|---|
| 1 | `name` | `str` | 必填 | 工具名 |
| 2 | `read_only` | `bool` | 必填 | — |
| 3 | `concurrency_safe` | `bool` | 必填 | 可否并发执行 |
| 4 | `policy` | `PolicyKind`（8 值） | 必填 | 权限策略类 |
| 5 | `subagent_ok` | `bool` | `False` | 可否出现在子 agent 注册表（False → 禁发） |
| 6 | `subagent_baseline` | `bool` | `False` | 子 agent 默认基线白名单 |
| 7 | `needs_write_store` | `bool` | `False` | — |
| 8 | `needs_read_state` | `bool` | `False` | — |
| 9 | `needs_runtime_provider` | `bool` | `False` | — |
| 10 | `repeat_exempt` | `bool` | `False` | 重复检测豁免 |
| 11 | `short_description` | `str` | `""` | 发给模型的短 description（省 schema token）；空则保留工具自带全文 |
| 12 | `enabled` | `bool` | `True` | False = 仅策略/测试用（如 echo），不进 `ENABLED_TOOLS` |
| 13 | `output_budget` | `int \| None` | `None` | T1 per-tool 输出预算（字符）：None=默认 **16000**；**0=豁免**（自带截断或防读回环） |
| 14 | `exposure` | `Literal["normal","hidden"]` | `"normal"` | F2：hidden = 不进 schemas 但保留注册（幻觉调用仍走权限三态，fail-safe） |

**`PolicyKind` 8 值**（`:12-21`）：`always_allow` / `outbound_ask` / `ui_ask` / `read_path` / `write_path` / `agent_allow` / `bash` / `interactive`

**26 工具逐字段全表（唯一登记表 `TOOL_META`，`:53-312`）**

| # | name | 行 | read_only | conc_safe | policy | sub_ok | baseline | write_store | read_state | runtime_prov | repeat_exempt | enabled | out_budget | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `echo` | 57 | ✅ | ✅ | always_allow | | | | | | | **❌** | | |
| 2 | `getTime` | 65 | ✅ | ✅ | always_allow | | | | | | | ✅ | | |
| 3 | `offload_read` | 72 | ✅ | ✅ | read_path | | | | | | | ✅ | | **hidden** |
| 4 | `Glob` | 80 | ✅ | ✅ | read_path | ✅ | ✅ | | | | | ✅ | | |
| 5 | `Grep` | 92 | ✅ | ✅ | read_path | ✅ | ✅ | | | | | ✅ | | |
| 6 | `Read` | 104 | ✅ | ✅ | read_path | ✅ | ✅ | | ✅ | | | ✅ | **0** | |
| 7 | `Write` | 117 | ❌ | ❌ | write_path | ✅ | ✅ | ✅ | ✅ | | | ✅ | | |
| 8 | `Edit` | 128 | ❌ | ❌ | write_path | ✅ | ✅ | ✅ | ✅ | | | ✅ | | |
| 9 | `Bash` | 139 | ❌ | ❌ | bash | ✅ | ✅ | | | | | ✅ | **0** | |
| 10 | `TodoWrite` | 157 | ❌ | ❌ | always_allow | | | | | | | ✅ | | |
| 11 | `Screenshot` | 163 | ❌ | ❌ | outbound_ask | | | | | | | ✅ | | |
| 12 | `SendToWeChat` | 170 | ❌ | ❌ | outbound_ask | | | | | | | ✅ | | |
| 13 | `Memory` | 178 | ❌ | ❌ | write_path | **❌** | | | | | | ✅ | | |
| 14 | `AskUserQuestion` | 186 | ✅ | ❌ | interactive | | | | | | **✅** | ✅ | | |
| 15 | `JournalQuery` | 193 | ✅ | ✅ | always_allow | ✅ | ✅ | | | | | ✅ | | |
| 16 | `Skill` | 202 | ✅ | ✅ | always_allow | ✅ | ❌ | | | | | ✅ | | |
| 17 | `Agent` | 211 | ❌ | ✅ | agent_allow | **❌** | | ✅ | | **✅** | | ✅ | | |
| 18 | `Diagnostics` | 224 | ✅ | ✅ | read_path | ✅ | ✅ | | | | | ✅ | | |
| 19 | `Git` | 235 | ✅ | ✅ | always_allow | ✅ | ✅ | | | | | ✅ | | |
| 20 | `NotebookEdit` | 244 | ❌ | ❌ | write_path | ✅ | ❌ | ✅ | ✅ | | | ✅ | | |
| 21 | `WebFetch` | 255 | ❌ | ❌ | outbound_ask | **❌** | | | | | | ✅ | | |
| 22 | `WebSearch` | 263 | ❌ | ❌ | outbound_ask | **❌** | | | | | | ✅ | | |
| 23 | `XeyoUI` | 271 | ❌ | ❌ | ui_ask | **❌** | | | | | | ✅ | | |
| 24 | `job_output` | 283 | ✅ | ✅ | always_allow | | | | | | **✅** | ✅ | | |
| 25 | `job_list` | 294 | ✅ | ✅ | always_allow | | | | | | | ✅ | | |
| 26 | `job_kill` | 301 | ❌ | ❌ | always_allow | **❌** | | | | | | ✅ | | |

**14 个派生集合（`:367-411`，全部由单表计算，禁止手抄）**

`ALWAYS_ALLOW_TOOLS` / `OUTBOUND_ASK_TOOLS` / `UI_ASK_TOOLS` / `READ_PATH_TOOLS` / `WRITE_PATH_TOOLS` / `READONLY_ALLOW` / `READONLY_ASK_ALLOW` / `SUBSET_TOOL_BASELINE` / `FORBIDDEN_SUB_TOOLS` / `REPEAT_EXEMPT_TOOLS` / `WRITE_STORE_TOOL_NAMES` / `READ_STATE_TOOL_NAMES` / `RUNTIME_PROVIDER_TOOL_NAMES` / `ENABLED_META_NAMES`，外加兼容别名 `SUBSET_TOOL_WHITELIST = SUBSET_TOOL_BASELINE`。

**注册期硬失败校验（`tools/catalog.py`，4 条）**

| 校验 | 失败后果 |
|---|---|
| 工厂产出名 ≠ 声明名 | `tool factory name mismatch` |
| meta 缺失或 `enabled=False` | `enabled tool missing from tools.meta` |
| 标了 `needs_read_state` 但无 `set_read_file_state` | RuntimeError |
| 实例 `is_read_only()` ≠ `meta.read_only` | RuntimeError |
| 实例 `is_concurrency_safe()` ≠ `meta.concurrency_safe` | RuntimeError |

即 **meta 表是唯一真相，实例与表漂移在注册期就炸**——这是 XEYO「机器执法」在工具面的体现。

**`XEYO_BENCH_MINIMAL=1` 的裁剪集（`catalog.py`）——18 个工具**

```python
excluded = {
    "Skill", "Agent", "Memory", "AskUserQuestion",
    "Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit",
    "Screenshot", "SendToWeChat", "XeyoUI", "JournalQuery",
    "Diagnostics", "Git", "WebFetch", "WebSearch",
}
```

保留 **8 个**：`echo`(禁用也不进) / `getTime` / `offload_read` / `Bash` / `TodoWrite` / `job_output` / `job_list` / `job_kill`。→ 实测保留的启用工具 = **7 个**（`getTime`, `offload_read`, `Bash`, `TodoWrite`, `job_output`, `job_list`, `job_kill`）。

### 2.3 dsh —— 57 个唯一工具名（按能力域分组）

| 域 | 工具名 | 实现包 |
|---|---|---|
| 文件 | `read`, `read_image`, `write`, `edit`, `str_replace_editor`, `glob`, `grep` | `tool-fs`, `tool-fs-search`, `tool-str-replace-editor` |
| 执行 | `bash`, `pwsh`（各含 local + persistent 变体） | `tool-bash`, `tool-pwsh`, `tool-bash-persistent`, `tool-pwsh-persistent` |
| 终端 | `terminal_open`, `terminal_read`, `terminal_send`, `terminal_signal`, `terminal_list`, `terminal_close`（**6 个**） | `tool-terminal` |
| 代码 | `run_code` | `dsh-tools` |
| 自修改 | `cordis_define`, `cordis_undefine`, `cordis_run`, `cordis_stop`, `cordis_inspect_list`, `cordis_inspect_query`, `cordis_inspect_self`（**7 个**） | `tool-cordis` |
| 会话自查询 | `session_event_read`, `session_event_search`, `session_event_trace`, `session_search`, `session_trace`（**5 个**） | `tool-session-query` |
| 子代理 | `subagent`, `list_subagent_models`, `interrupt_agent`, `list_agents`, `send_message` | `tool-subagent`, `tool-subagent-control` |
| 团队（实验） | `spawn_teammate`, `team_task_create`, `team_task_get`, `team_task_list`, `team_task_update`, `wait_agent` | `experimental-tool-agent-team` |
| 后台 | `job_list`, `job_output`, `job_kill` | `tool-jobs` |
| 计划/待办 | `exit_plan_mode`, `todo_write`, `create_goal`, `get_goal`, `update_goal` | `plan-mode`, `tool-todo`, `tool-goal` |
| 调度 | `schedule_create`, `schedule_delete`, `schedule_list` | `schedule` |
| 其他 | `ask_user_question`, `skill`, `lsp`, `web_fetch`, `web_search`, `workflow`, `ralph` | `tool-ask-user`, `tool-skill`, `tool-lsp`, `tool-web`, `tool-workflow`, `tool-ralph` |

**XEYO 26 vs dsh 57 的工具面差异（域级）**

| 域 | XEYO | dsh |
|---|---|---|
| 文件 | Read/Write/Edit/Glob/Grep/NotebookEdit（6） | read/read_image/write/edit/str_replace_editor/glob/grep（7） |
| 执行 | Bash（1） | bash/pwsh ×（local+persistent）= 4 |
| 持久终端 | ❌ | **6 个 terminal_\*** |
| 代码运行 | ❌ | `run_code` |
| 自修改插件 | ❌ | **7 个 `cordis_*`** |
| 会话自查询 | ❌ | **5 个 `session_*`** |
| 子代理 | Agent（1） | subagent + 4 控制工具 |
| 团队 | ❌ | **6 个 team_\***（实验） |
| 后台任务 | job_output/job_list/job_kill（3） | 同名 3 个 |
| 计划/goal | ❌（plan 走 mode，无工具） | exit_plan_mode + 3 个 goal 工具 |
| 定时 | ❌ | **3 个 schedule_\*** |
| LSP | Diagnostics（1，自陈"Not a full LSP"） | `lsp` |
| 网络 | WebFetch/WebSearch | web_fetch/web_search |
| 桌面/外发 | Screenshot/SendToWeChat/XeyoUI（**3 个，dsh 完全没有**） | ❌ |
| 其他 XEYO 独有 | echo/getTime/offload_read/TodoWrite/Memory/AskUserQuestion/JournalQuery/Skill/Git | — |
| 其他 dsh 独有 | skill/ask_user_question/workflow/ralph | — |

---

## §3 工具执行管线：逐阶段、逐拦截点

### 3.1 dsh —— 事件瀑布式管线

dsh 的工具执行是**一条 `tools/*` 事件瀑布**（`ctx.on(...)` + `next()`），每个插件声明自己挂在哪一环。本轮从 guard / spill / timeout 三个包的 `apply()` 里读到实际挂载点：

| 阶段 | 事件/接口 | 实现文件:行 | 第三方可否拦截 | 失败行为 |
|---|---|---|---|---|
| 1. 解析 | 模型 `tool/call` 事件落 `arguments: string` | `core/session/src/types.ts:319` | — | 原样保留字符串 |
| 2. 执行入口 | `tools/execute`（可被包装的 waterfall） | `guard/timeout-policy/src/index.ts`（`ctx.on('tools/execute', …)`） | ✅ 可包装 | 透传 |
| 3. 超时 | `tools/execute` 包装：读 `ctx.tools.get(name, agent)?.timeoutMs` | 同上；`TOOL_TIMEOUT = 'TOOL_TIMEOUT'` | ✅ | **无 timeoutMs → 无 deadline，直接 delegate**；到期 → 替换为 `isError` 结果 |
| 4. 权限（Pre 决策） | `PreToolDecision` / hook `PreToolUse` | `hooks/hooks-*/src/index.ts` | ✅ | Codex 只认 `deny`；CC 认 `allow`/`deny`/`ask` |
| 5. 沙箱 | `ctx.sandbox.confine(argv, policy)` | `sandbox/sandbox/src/index.ts:175` | ❌（provider 内部） | **fail-closed** |
| 6. 执行 | provider 跑 confined argv | `sandbox/sandbox-local/src/index.ts` | ❌ | `SANDBOX_UNAVAILABLE` |
| 7. 结果后处理 | `tools/post-execute`（可被包装） | `guard/repeat-tool-reminder/src/index.ts`、`spill/spill-policy/src/index.ts` | ✅ 可 block / 可换内容 / 可加 `additionalContexts` | 见下 |
| 8. PTC 子调用日志 | `tools/ptc-dispatch-log` | `spill-policy`（第二条臂） | ✅ | 只压日志副本，不动程序值 |
| 9. 落事件 | `tool/result` | `core/session/src/types.ts:331` | ❌ | `meta` 非 JSON 可序列化即**在源头拒收**（`isJsonValue` 校验） |

**`tools/post-execute` 的决策类型（三态）**

| 决策 | 语义 | 证据 |
|---|---|---|
| `{kind:'block', feedback, additionalContexts?}` | 阻断并回灌反馈 | `repeat-tool-reminder` 里对 `downstream.kind === 'block'` 的分支 |
| 内容替换（value replacement） | 换掉模型可见内容 | `spill-policy` 注释："Accepted value replacements pass through for registry revalidation and rendering; this presentation policy cannot also replace content in the same mutually exclusive decision." |
| 附加上下文（`additionalContexts`） | 不改内容只加料 | `prependContext(ours, theirs)` 保留下游 source 与 metadata |

**关键不变量（原文）**：`repeat-tool-reminder` 的注释写明——**counting 放在 post-execute，因为被拒的调用也流经同一条瀑布**：

> Counting happens here — in post-execute — because denied calls also flow through this waterfall (`ToolRuntime.execute` routes a deny through the same pipeline), and a model hammering a denied call is exactly the loop worth breaking.

这一条与 XEYO 的理念铁律（"观测域一致性"）是同一个洞见的不同表达。

### 3.2 XEYO —— 调用链式管线（含 3 条旁路）

| 阶段 | 实现位置 | 说明 |
|---|---|---|
| 1. 解析 tool_use | `engine/query_loop.py`（`_assistant_tool_uses:192`、`_message_tool_call_id:205`） | 从 assistant 消息取 tool_use 块 |
| 2. 配对修复 | `_repair_unpaired_tool_calls:218`、`_fill_missing_tool_results:244` | **只在 submit 入口 + abort 路径各做一次**，不在每轮全量扫 store（注释明写） |
| 3. 只读预取 | `_eligible_for_early:155`、`early_readonly_tools_enabled:112`、`_cancel_early_tasks:179` | 只读工具提前并发 |
| 4. 预算闸 | `budget.begin_tool_call()`（`query_loop.py:1075`） | `forced_wrap_up` 时**跳过**该闸（`R3'`） |
| 5. 权限判定 | `permissions/policy.py::evaluate_policy`（见 §4） | 5 道硬拦 + grant store |
| 6. 执行 | 工具实例 |
| 7. 结果后处理 | `query_loop.py:1940-1990`：suffixes 拼接 → `ResultFold.process()` 折叠 | |
| 8. 写 store | `store.append(tool_result_message(...))`（`:1976`） | |
| 9. 发事件 | `ToolResultEvent`（`:1946`） | 含 `duration_ms`、`spilled` |

**与 dsh 的管线形态差异**

| | dsh | XEYO |
|---|---|---|
| 形态 | **事件瀑布**（插件各挂一环，可互相包裹） | **顺序调用链**（写死在 query_loop） |
| 第三方扩展点 | 9 个阶段中 6 个可拦截 | 0 个（只有 T_now 文本注入） |
| 超时 | 声明式（`tool.timeoutMs`）+ 独立 policy 包 | 工具内部各自实现 |
| 结果后处理 | 可 block / 可替换 / 可加料，**三态俱全** | 只有"追加后缀 + 折叠"，无 block |
| 重复检测位置 | post-execute（**拒绝也计数**） | `RepeatCallGuard`（轮内状态，`clear_advice` 每轮重置） |
| 折叠 | ❌ | ✅ `IdenticalResultFold`（同签名+同输出 → 一行 `[fold]`） |

**XEYO 的三条旁路（绕过主链）**

| 旁路 | 文件 | 绕过什么 |
|---|---|---|
| `workspace_fs` 直写 | `server/workspace_fs.py` | 绕过权限判定 / rewind / 审计（默认只读开关关） |
| 后台 bash job | 24h 超时（≈事实无超时） | 绕过工具超时与轮内预算闸 |
| WriteStore 写路径 | 写工具经 `needs_write_store` 注入 | 不经 rewind 的 Before 快照 |

### 3.3 逐工具配对表（同名/同能力）

| 能力 | dsh | XEYO | 实现差异 |
|---|---|---|---|
| 读文件 | `read` | `Read` | dsh 有 `read_image` 独立工具；XEYO 把 vision 折进 `Read`（`apply_read_vision`），Read 的 `output_budget=0` 防 read→spill→read 回环 |
| 写文件 | `write` | `Write` | 两侧都要求先读；XEYO 另走 `needs_write_store` 注入 |
| 改文件 | `edit` + `str_replace_editor` | `Edit` + `NotebookEdit` | dsh 的 `str_replace_editor` 是另一套编辑器语义；XEYO 的 NotebookEdit 专治 .ipynb |
| 查找 | `glob` / `grep` | `Glob` / `Grep` | XEYO 额外有 Bash→Glob/Grep 的**透明路由**（`.xeyo-policy.json` 的 `bash_routing`） |
| 执行 | `bash` / `pwsh`（+persistent） | `Bash`（1 个） | XEYO 有 45s 未完**自动 promote 后台**（见前轮）；dsh 需模型预判 `run_in_background` |
| 终端 | 6 个 `terminal_*` | ❌ | dsh 独有 PTY 持久会话 |
| 子代理 | `subagent`（+4 控制） | `Agent`（1） | dsh 可 `list_agents`/`interrupt_agent`/`send_message` 续聊子代理 |
| 待办 | `todo_write` | `TodoWrite` | 同名语义 |
| 网络 | `web_fetch` / `web_search` | `WebFetch` / `WebSearch` | XEYO 两侧都是 `outbound_ask` 策略；dsh 由 hook 与 permission 决定 |
| 提问 | `ask_user_question` | `AskUserQuestion` | 两者都挂起等用户 |
| 会话自查询 | 5 个 `session_*` | ❌ | dsh 独有（事件溯源红利的直接兑现） |
| LSP | `lsp` | `Diagnostics`（自陈非全量 LSP） | 能力层级差 |

---

## §4 权限判定：逐分支

### 4.1 XEYO —— `evaluate_policy` 两条函数、分支顺序固定

**外层 `evaluate_policy`（`:1319-1388`）—— 5 道 grant 前置守卫**

```
evaluate_policy(name, tool_input, cwd, allowed_paths, tool)
  decision = evaluate_policy_impl(...)
  if decision.decision != ASK: return decision            # ← 非 ASK 终态，grant 不可触碰
  ├─ get_write_scope() is not None       → return          # worker 沙箱：grant 不得放宽
  ├─ is_remote_session(_session_id())    → return          # 远程会话不得静默放行（§34 不变量）
  ├─ permission_mode() == "always"       → return          # 用户显式要求逐条确认
  ├─ name == "bash" and bash_command_is_composite(cmd) → return   # G29：`git status && curl x|sh` 不得吃前缀 grant
  fp = grant_fingerprint(name, tool_input, matched_rule=..., mcp_target=...)
  if not fp: return
  identity_name = mcp_target or name                       # 存取同一身份
  grant = default_grant_store().match(tool_name=identity_name, fingerprint=fp, scope=cwd)
  if grant is None: return decision
  return PolicyDecision(ALLOW, reason="always_allow_grant", matched_rule="grant_store")
```

**内层 `evaluate_policy_impl`（`:1391-…`）—— 分支顺序（已读到前 6 条）**

| 序 | 条件 | 结果 | 证据行 |
|---|---|---|---|
| 0 | 取 `roots = _effective_roots(cwd, allowed_paths)`、`pol = load_workspace_policy(cwd)` | — | 1401-1402 |
| 1 | `raw_name in pol.deny_tools` | **DENY** `policy_deny_tool` | 1404-1410 |
| 2 | `raw_name.startswith("mcp__")` | → `_evaluate_mcp`（`:1150`） | 1413-1414 |
| 3 | `raw_name == "Mcp"` | → `_evaluate_mcp_gateway`（`:1217`） | 1418-1419 |
| 4 | `raw_name in _ALWAYS_ALLOW` | **ALLOW** `tool_unrestricted_p0` | 1421-1426 |
| 5 | `raw_name in _OUTBOUND_ASK_TOOLS` | SendToWeChat：缺 path→**DENY**；路径越界→**DENY**；`is_max_permission_mode()`→**ALLOW** `outbound_max_allow`；否则 **ASK** | 1429-1470 |
| 6+ | `ui_ask`（`_evaluate_ui_ask:506`）/ `read_path`（`_pick_path:437`、`readonly_gate:417`）/ `write_path` / `agent_allow`（`_prompt_for_agent:480`）/ `bash`（`_evaluate_bash:822`）/ `interactive` | 见 §4.3 | — |

**`_evaluate_bash` 的 5 道硬拦 + 语义分析（`:822-1015`，共 194 行）**

辅助函数链：`_bash_write_target:765` → `_bash_writes_file:785` → `_peer_bash_conflict:1016` → `_bash_touches_policy_file:1092` → `_bash_write_path_block:1109`。
即 XEYO 会**从 bash 命令文本反推写目标**，再套用 `write_path` 策略——这是 XEYO 权限系统最重的单块逻辑。

**`PermissionDecision` 三态**：`ALLOW` / `ASK` / `DENY`（`policy.py:55` 起）。
**权限模式**：`permission_mode()` 取值含 `always`；`is_max_permission_mode()`（`:219`）；`_default_permission_mode:175`、`_runtime_mode_effective:188`、`begin_permission_turn:229`（turn 边界拍基线）。
**会话档位**：`session_permission_profile`（`:268`）。
**只读闸**：`readonly_gate`（`:417`）、`tool_allowed_in_mode`（`:386`）。

### 4.2 dsh —— 三个 whole-value knob + 投影折叠

**`PermissionSelect`（`interaction/permission-presets/src/types.ts`）**

```ts
export interface PresetOption {
  value: string        // 稳定选项值：表键，或 'custom'
  name: string         // 展示标签
  description?: string // 一句话说明
}
export interface PermissionSelect {
  options: PresetOption[]   // 表序 + 恰好当 custom 有效时追加的 'custom'
  currentValue: string
}
```

**关键：`permissions` 是投影（projection），不是单一事件**——

> The session's permission select, folded from the three whole-value knob events (`permission/preset`, `sandbox/mode`, `approval/policy`) over the composition defaults. **Key absence means no permission service is composed — clients hide the control.**

**沙箱模式 3 值（`sandbox/sandbox-policy/src/index.ts`）**

| 值 | 渲染给模型的策略句（原文，`renderPolicyContext`） |
|---|---|
| `read-only`（**fail-safe 默认**） | "Current DSH file policy: read-only. Any available operation enforced by the DSH file sandbox cannot modify files in the standing mode. **Do not refuse a required modification from this policy alone**: try an available tool normally and follow any denial and escalation guidance it returns." |
| `workspace-write` | "Current DSH file policy: workspace-write. …may modify files under the session workspace: `<root JSON>`。Some platform temporary areas may also be writable." |
| `danger-full-access` | "Current DSH file policy: danger-full-access. The DSH file sandbox does not restrict file modifications by available operations." |

**注意**：这段文本**不是事件**，是"每请求重建的动态 context"——注释写明理由：**避免切换策略时重写稳定的 system-prompt 缓存前缀**。

### 4.3 权限字段级差异矩阵

| 维度 | dsh | XEYO |
|---|---|---|
| 判定入口 | 事件瀑布 + 组合的 policy 插件 | 单函数 `evaluate_policy` → `evaluate_policy_impl` |
| 结果枚举 | `allow / ask / deny / none`（merge 优先序 **deny > ask > allow**，首个 `continue:false` 粘滞） | `ALLOW / ASK / DENY`（三态） |
| 策略来源 | 组合（preset + knob 事件） | `.xeyo-policy.json`（`deny_tools`）+ 模式 + meta 表策略类 |
| 默认档 | **`read-only`**（fail-safe） | 由模式决定（非 fail-safe 单一默认） |
| 沙箱联动 | 权限档 → sandbox policy（强耦合） | 权限与沙箱**不耦合**（XEYO 无沙箱层） |
| 授权留存 | grant 概念在用户审批层（`allowed-once` 唯一授予值） | **grant store + 指纹 v2**（`grant_fingerprint`，含 `matched_rule` 与 `mcp_target`） |
| 排除条件 | — | worker 沙箱 / 远程会话 / `permission_mode=always` / bash 复合命令 **四类不吃 grant** |
| 命令语义分析 | ❌（不做 bash 文本反推） | ✅ `_bash_write_target` 等 5 个函数从命令反推写目标 |
| 策略告知模型 | **不给**（`approval/policy` 是 log-only，注释明写"stays out of the model transcript"） | **给**（T_now `runtime_mode_snapshot` 块） |
| 停用即时性 | 停用 → DENY | 停用 → DENY，且**不可被 grant 穿越**（`evaluate_policy` 首行 `!= ASK` 早返） |

---

## §5 审批与提问：逐字段

### 5.1 XEYO —— 4 组挂起/解决事件（八元组）

| 组 | Pending 事件字段 | Resolved 事件字段 |
|---|---|---|
| **权限** | `request_id`, `tool_name`, `tool_input: dict`, `reason`, `prompt`, `path?`, `expires_at?`, `choices: list[str]`, `peer_summary`, `intent`（3 值） | `request_id`, `approved: bool`, `actor`, `reason`, `resolved_at?`, `choice`（4 值：allow/deny/remind/timeout） |
| **提问** | `request_id`, `session_id`, `turn_id`, `question`, `options: list[str]`, `default?`, `expires_at?` | `request_id`, `answer`, `actor`, `timeout: bool`, `resolved_at?` |
| **计划** | `request_id`, `session_id`, `turn_id`, `plan: str`, `expires_at?` | `request_id`, `approved`, `actor`, `reason`, `resolved_at?` |
| **过期预告** | `request_id`, `expires_at?`, `seconds_left=30.0`（**未入联合**） | — |

**HTTP 接口（`server/routers/control.py`）**

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/permission/resolve` | 权限审批 resolve |
| GET | `/v1/permissions/grants` | 列已存 grant |
| DELETE | `/v1/permissions/grants/{grant_id}` | 删 grant |
| POST | `/v1/ask/resolve` | 提问作答 |
| POST | `/v1/plan/{turn_id}/approve` | 计划批准 |
| POST | `/v1/interrupt`、`/api/interrupt` | 中断 |

**审批是否入 JSONL**：`TaskStateEvent`（`task_status` 含 `waiting_permission`）与会话状态事件都会进 transcript；`LlmRetryEvent` 注释明确**不进 transcript**。

### 5.2 dsh —— 审批四值 + 三处 log-only

| 项 | 内容 | 证据 |
|---|---|---|
| 事件 | `approval/asked`、`approval/decided`、`approval/policy` | `interaction/user-approval/src/{types,index}.ts` |
| 策略事件性质 | `approval/policy` **log-only**，永进日志、永不进模型 transcript | 同前轮已核 |
| 授予值 | 封闭四值，**唯一授予值是 `allowed-once`**；无 answerer → `unavailable`（fail-closed）；answerer 返回词汇外值 → 归一为 `unavailable` | 前轮已核 |
| 超时 | 默认 600000ms（hook 侧）/ user-approval 自带超时 | 前轮已核 |
| 模型可见性 | **不可见**（审批策略句以动态 context 形式给，事件本身不给） | `sandbox-policy` + `user-approval` 注释 |

### 5.3 差异

| 维度 | dsh | XEYO |
|---|---|---|
| 挂起种类 | 1 类（审批） | **4 类**（权限 / 提问 / 计划 / 过期预告） |
| 过期预告 | ❌ | ✅ 独立事件 + 30s 默认提前量 |
| 计划确认 | 走 `plan/mode` 状态 | 独立 `plan_pending/plan_resolved` 事件 + HTTP approve |
| 审批入日志 | ✅ `approval/asked`/`decided` | ✅ TaskStateEvent（状态级） |
| 模型可见审批状态 | **否**（刻意） | **是**（T_now `runtime_mode_snapshot`） |

---

## §6 T_now 注入管线：20 块逐块全文

### 6.1 登记表（`python/prompt/pre_llm_inject.py::T_NOW_BLOCK_REGISTRY`）

**硬顶 `T_NOW_BLOCK_HARD_CAP = 21`**，注释写："23→21：裁决 5 删除 stale_xeyo_md / nested_change 两块（提醒类退出注意力，状态维护转引擎静默）"。

| # | 块名 | klass | why（原文） |
|---|---|---|---|
| 1 | `continue` | directive | 工具续写轮无此块模型把 tool_result 当终点，不回用户问题 |
| 2 | `mode_instructions` | directive | Ask/Plan/批准计划是本轮行为模式合同，决定能否写盘 |
| 3 | `wrap_up` | directive | 收尾窗引导:配额内可落盘/验证但不得开新探索;缺口清单来自引擎 stat |
| 4 | `runtime_budget` | directive | 预算透明：模型需知剩余额度以决定收敛节奏 |
| 5 | `budget_mirror` | directive | 死线会话每轮稳态预算/时间镜像（23ca693 禀赋①）；正常会话零注入，与 runtime_budget 瞬时通知互补 |
| 6 | `multi_agent_hint` | directive | 多代理分解/汇总的协作合同，缺了会单干或重复汇总 |
| 7 | `repeat_guard` | directive | 轮内防复读提醒（引擎 clear_advice 逐轮重置） |
| 8 | `nested_instructions` | inventory | 子目录规则按需加载；限窗注入，滚出尾窗静默 |
| 9 | `compact` | directive | 输出/写码压缩开关生效的统一行为规则（任一开关开启即注入；③合并两块减一） |
| 10 | `mcp_required_warn` | event | required MCP server 启动失败的可见警告（fail-visible） |
| 11 | `reconcile_events` | event | 工具面/技能目录变更，consume 语义——静默即永久丢失 |
| 12 | `peer_presence` | event | 多会话交叉活动提醒，冲突预防（drain 队列） |
| 13 | `file_conflict` | event | 触碰文件被其他会话写入——静默即丢，覆盖风险 |
| 14 | `browser_preview` | inventory | 用户预览页 URL：读页面正文的必要指针 |
| 15 | `runtime_mode_snapshot` | directive | 审批模式活状态（supersedes）；真门禁在 permissions 层 |
| 16 | `agent_settlement` | event | 子代理结算通知，drain 语义——静默即永久丢失 |
| 17 | `goal` | directive | 仅 blocked/pending_complete 注入：恢复执行/完成确认的锚 |
| 18 | `resume_directive` | event | 续跑富化指令投影-only 送达（修订2）：落库只存用户真实文本 |
| 19 | `pending_jobs` | directive | job 完成补投：一次性待领信息，模型不读则任务结果不可见 |
| 20 | `skill_preinvoke` | directive | 用户 /name 直呼技能的宿主确定性加载；不注入则直呼依赖模型自觉调 Skill 工具，user 只见技能的直呼即失效 |

**类别分布**：directive **12** / event **6** / inventory **2**。

### 6.2 装配点（20 个 `_tag_block` 调用，与登记表一一对应）

`continue`(1045) / `mode_instructions`(1054) / `wrap_up`(1059) / `runtime_budget`(1063) / `multi_agent_hint`(1070) / `repeat_guard` / `nested_instructions` / `compact` / `mcp_required_warn` / `reconcile_events` / `peer_presence` / `file_conflict` / `browser_preview` / `runtime_mode_snapshot` / `agent_settlement` / `goal` / `resume_directive` / `pending_jobs` / `budget_mirror` / `skill_preinvoke`

**统一入口（`:922-930`）**

```python
def _tag_block(tagged, name, block) -> None:
    """装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。"""
    if name in _skipped_blocks():
        return
    tagged.append(block)
```

**块级旁路开关**：`XEYO_T_NOW_SKIP="a,b"`（消融/应急）。注释警告：**event 类被跳过即永久丢失**（consume 已清空）。

### 6.3 三层预算（实测常量）

| 常量 | 值 | 用途 |
|---|---|---|
| `T_NOW_TOTAL_BUDGET` | **6,000** | 全块总预算（字符） |
| `T_NOW_INVENTORY_MAX` | **2,500** | inventory 类配额上限 |
| `T_NOW_EXTRA_BUDGET` | **6,000** | 额外预算 |
| `NESTED_MAX_CHARS` | **4,000** | 嵌套说明限窗 |
| `T_NOW_BLOCK_HARD_CAP` | **21** | 登记条数硬顶 |
| `KLASS_DIRECTIVE` / `KLASS_EVENT` / `KLASS_INVENTORY` | 字符串常量 | 类别标记 |

### 6.4 裁剪算法逐行（`_trim_tagged_blocks:990-1027`）

```python
def _trim_tagged_blocks(tagged, *, total=T_NOW_TOTAL_BUDGET, inventory_max=T_NOW_INVENTORY_MAX):
    kept, inv = [], []
    used = 0
    for k, raw in tagged:
        b = (raw or "").strip()
        if not b: continue
        if k == KLASS_INVENTORY: inv.append((k, b))
        else:
            kept.append((k, b)); used += len(b)      # directive/event 全保
    room = max(0, min(inventory_max, total - used))  # inventory 配额 = min(2500, 6000-used)
    for k, b in inv:
        if room <= 0: break
        if len(b) <= room:
            kept.append((k, b)); room -= len(b)
        elif room >= 64:                              # ★ 剩余 ≥64 才截断
            kept.append((k, b[:room].rstrip() + "…")); room = 0
        else:
            break                                     # ★ 剩余 <64 整块丢弃
    return kept
```

**三条硬性质**：① directive/event **永不裁剪**（构造处各自有界）；② inventory 按装配序填配额；③ **末块剩余不足 64 字符则整块丢弃**（不是截成残句）。

### 6.5 装配序（`run_pre_llm_inject:1030-…`）

`after_tools = ends_with_tool_result(out)` → 若为真先挂 `continue` → `mode_instructions`（`build_mode_context_blocks`）→ `wrap_up`（仅 `forced_wrap_up`）→ `runtime_budget`（仅 `ctx.runtime_notice`）→ `multi_agent_hint`（仅 `ctx.multi_agent`）→ …

### 6.6 与 dsh 的对照

| 维度 | dsh | XEYO |
|---|---|---|
| 逐轮注入机制 | 无统一管线；各插件用 `createUserMessage({source:{kind:'plugin', plugin:…}})` 往 pre-step 加消息 | **T_now 单一管线** + 登记表 + 硬顶 |
| 声道 | 合成 user 消息（带 `source` 标记） | `env_channel`：伪造 tool 对（见 §7） |
| 预算 | 无全局预算（各插件自管） | 三层预算 6000/2500/21 |
| 登记/执法 | 无 | **20 块登记 + 硬顶 21 + 源码级执法测试** |
| 类别语义 | 无 | directive（全保）/ event（drain，静默即失）/ inventory（可裁） |
| 旁路 | 无 | `XEYO_T_NOW_SKIP` |

---

## §7 `env_channel` 声道：逐字段

**实现**：`python/prompt/turn_context.py::append_env_notice_pair`（`:115` 起）

**产出结构（仅存在于投影的伪 tool 对）**

```python
pair = [
  {"role": "assistant",
   "content": [{"type": "tool_use", "id": call_id, "name": ENV_TOOL_NAME, "input": {}}]},
  {"role": "user",
   "content": [{"type": "tool_result", "tool_use_id": call_id, "content": t, "is_error": False}]},
]
return [*messages, *pair]
```

**逐字段语义**

| 字段 | 值 | 说明 |
|---|---|---|
| `role` | `"assistant"` → `"user"` | 内部格式；经 `normalize_messages_for_openai` 转成标准 `assistant(tool_calls)` → `tool` 消息 |
| `tool_use.name` | `ENV_TOOL_NAME`（`"xeyo_env_notice"`） | **不注册进 tools 数组** → schemas 冻结红线不受影响 |
| `tool_use.id` | `new_env_tool_call_id()` | 每次新建 |
| `tool_result.content` | 注入文本 | 环境声道载荷 |
| `tool_result.is_error` | `False` | 恒定 |

**关键不变量（原文）**

> tool_result 是模型训练出的「环境数据声道」——注入内容与用户意图在消息结构上隔离，说话人混淆无从发生。工具名（xeyo_env_notice）不注册进 tools 数组（schemas 冻结红线不受影响）；**尾部追加不改前缀字节，KV 缓存语义与 legacy 尾插等价**。

**另外两个同族函数**（同文件）

| 函数 | 行为 | 使用轮型 |
|---|---|---|
| `append_text_blocks_to_last_user` | 末条是 user 则**追加**到其 content；否则尾插新 user | after_tools 轮 |
| `prepend_text_blocks_to_last_user` | **前插**到末条 user 的文本之前（P1/A1 分仓） | 仅 fresh-user 轮 |
| `append_env_notice_pair` | 伪造 tool 对尾插 | env_channel 策略 |

**设计意图原文**：inventory/capability 类背景块放用户原文**之前**，理由是"生成点紧邻的永远是用户请求本身，recency 偏置为用户服务"；块自身靠围栏 + `background only — NOT the user request` 头防归属误读。

**渲染上限**：`APPROVED_PLAN_MAX_CHARS` 截断 + `\n…[plan truncated]`；approved plan 块结尾**只保留**"按已批准计划实现。"（裁决 4：引擎引导删除）。

**与 dsh 的对照**：dsh 没有等价声道设计；dsh 用 `MessageSource` 标记（`{kind:'plugin', plugin, form:'notice', summary}`）在**消息元数据**里区分来源，模型看到的是普通 user 消息。**XEYO 把隔离做进消息结构，dsh 把隔离做进元数据**——后者对模型是"作者标签"，前者对模型是"数据类型"。

---

## §8 沙箱：逐平台、逐参数

### 8.1 服务接口

```ts
// packages/sandbox/sandbox/src/index.ts:39-72, 153-175
export interface SandboxExecutionPolicy {
  mode: SandboxMode               // 'read-only' | 'workspace-write' | 'danger-full-access'
  workspaceRoot: string           // workspace-write 可写的绝对根
  sessionId?: SessionId           // 后端按会话键控私有状态（如 windows-acl 的私有 temp + SID）
}
export interface SandboxPolicy extends SandboxExecutionPolicy {
  mode: ConfinedSandboxMode       // per-call 携带，不是 provider 固定
}
export type SandboxEnforcement = 'full' | 'partial'

abstract class SandboxProvider {
  abstract confine(argv: readonly string[], policy: SandboxPolicy): ConfinedArgv
}
```

**原文不变量**：

> {@link confine} must return enforcing argv **or fail closed** at wrap or runner-execution time; **silent unconfined passthrough is forbidden**.

**错误码**：`SANDBOX_UNAVAILABLE`；异常文案原文：

> `... refusing to run the command unconfined. Install bubblewrap or run a Landlock-enforcing ...`

### 8.2 四平台 argv 逐参数（`sandbox/sandbox-local/src/profiles.ts`）

**Linux / bwrap**

```ts
['--ro-bind', '/', '/', '--dev', '/dev', '--unshare-pid', '--proc', '/proc', '--die-with-parent']
// workspace-write 追加：
['--tmpfs', '/tmp', '--bind', policy.workspaceRoot, policy.workspaceRoot]
```

**Linux / Landlock**（`@deepseek-ai/node-addon-landlock-run` 的原生 addon）

```ts
grantArgs({ readOnly: ['/'], readWrite: ['/dev/null' (+ '/tmp', workspaceRoot when workspace-write)] })
```

**macOS / Seatbelt**（SBPL profile）

```
(version 1) (allow default) (deny file-write*)
(allow file-write* (literal "/dev/null"))
[+ (allow file-write* (subpath "<root1>") (subpath "<root2>") …)]
```

**Windows / ACL**（`sandbox-windows-acl/`，9 个文件）：`acl.ts` / `ffi.ts` / `grant.ts` / `path-boundary.ts` / `runner.ts` / `spawn.ts` / `token.ts` / `win32-abi.ts` / `workspace-sid.ts`
→ 实现方式是 **Win32 FFI + 受限 token + 按 workspace 的 SID + 按会话的私有 temp**。`SandboxExecutionPolicy.sessionId` 的注释原文：

> backends key per-session state off it (e.g. windows-acl gives each live session/workspace pair a random private temp directory and SID, while the workspace SID and standing grant remain per-workspace)

**`writableRoots(policy)`**：seatbelt 授权与进程内 fs 栅栏（`fs-sandbox`）**共用同一个 helper**，注释明写"so the Seatbelt grant and the in-process fs fence can never drift apart"。

### 8.3 E2B 与降级

- `packages/e2b/`：云沙箱 POC（本轮未逐行读，属"未见细节"）。
- `sandbox/src/escalation.ts`：升级仲裁（失败关闭序列）；`DENIAL_SIGNATURES` 在 `sandbox-local` 中定义，用于**从 stderr 识别沙箱拒绝**（区分"命令没跑"与"沙箱成功拦下"）。
- `RunnerFailureRule` 逐字段：`allowedExitCodes?`（非零退出码白名单，省略=任意非零）/ `informationalLines`（按行**大小写不敏感精确相等**剔除）/ `fatalSignatures`（在剩余 stderr 行内**大小写不敏感**匹配）。
  → 注释原文："**Exit status alone never proves runner failure.**"

### 8.4 XEYO 的沙箱面

| 项 | XEYO 实测 |
|---|---|
| OS 级隔离 | ❌ 无（全仓 `landlock\|seatbelt\|bubblewrap\|bwrap\|sandbox-exec` 零命中，排除 `.venv`） |
| 进程资源限额 | ✅ Windows **Job Object**（资源限额，非文件隔离） |
| 容器路由 | ✅ `TerminalBench/xeyo_harbor_agent.py`（评测旁径：`docker exec` 进容器，cwd 是自建空目录） |
| fs 栅栏 | 有路径白名单（`_effective_roots` / `path_in_allowed_working_path`），但**不是内核强制** |
| 降级 | 无降级概念（因为没有强制层） |

**结论**：dsh 的沙箱是**层**（4 后端 + 策略服务 + 升级仲裁 + 失败证据规则 + 进程内 fs 栅栏），XEYO 的对应位置是**若干 `if` 判断**。

---

## §9 截断与压缩：逐常量

### 9.1 dsh —— 三条独立预算链

**(a) 工具结果中间裁剪 `compaction-tool-result-pruner`**

```ts
export const PRUNE_MARKER = '\n\n[... tool result middle pruned ...]\n\n'
export const DEFAULTS = { thresholdChars: 8192, headChars: 4096, tailChars: 1024 }
```

- 三个键是**完整白名单**（`CONFIG_KEYS`），未知键 → 报错。
- 校验：`thresholdChars` 正整数；`headChars`/`tailChars` 非负整数；`headChars + codePointLength(PRUNE_MARKER) + tailChars ≤ thresholdChars`，否则抛错。
- 长度按 **Unicode code point** 计（`Array.from(text).length`），不劈代理对。

**(b) spill（超限则外部化）`spill-policy`**

| 项 | 值/行为 |
|---|---|
| 配置 | 仅 `maxInlineBytes`（UTF-8 字节） |
| 未配置 | **注册零插件**（真正的 no-op） |
| 配置非法（负数/小数） | **加载期抛错**，不留给每次调用（注释：bad config must fail the deployment, not the tool） |
| 触发 | 最终结果的 UTF-8 大小 > `maxInlineBytes` |
| 预览切割 | `headBytes = ceil(budget/2)`；`tailBytes = floor(budget/2)`（`TextRetainer({kind:'headTail', …})`） |
| 仅纯文本 | 任一非 text 块 → 原样不动 |
| 跳过 `read` | 模型面臂跳过 `read`（防 read→spill→read 循环）；日志臂仍压 |
| 失败语义 | **尽力而为**：无会话 owner / 无后端 / 存盘失败 → 记日志返回原结果；"**A spill failure must NEVER turn a successful tool call into an `isError`**" |
| 通知文案 | `(${omission} Full formatted result stored at: ${ref.locator}. ${ref.retrievalHint})` |
| 存储根 | `mkdtempSync(join(tmpdir(), 'dsh-spill-'))`，即前缀 `dsh-spill-` + 6 位随机 |

**(c) compaction（上下文压缩）`compaction-basic`**

| 常量 | 值 | 说明 |
|---|---|---|
| `DEFAULT_THRESHOLD_RATIO` | **0.8** | 请求压力占 contextWindow 比例 |
| `DEFAULT_RETAIN_RATIO` | **0.16** | 逐字保留的尾部比例 |
| `maxTokens` | **8192** | 摘要输出上限 |
| `compactionRetries` | **1** | 压缩重试 |
| `maxOverflowRetries` | **1** | 溢出重试 |
| `auto` | **true** | 自动压缩 |

- `thresholdTokens = floor(contextWindow * thresholdRatio)`
- `retainTokens = retainRatio === undefined ? floor(contextWindow * retainRatio) : retainTokens`
- **硬校验**：`retainTokens < thresholdTokens`；`retainRatio >= thresholdRatio` → 加载期抛错；`retainRatio` 与 `retainTokens` **互斥**。
- 保留形式三态：`{retainTokens}` / `{retainRatio}` / 继承 fallback。
- 可对 **(provider, model) 精确覆盖**（`modelPolicies`），重复键用 `\u0000` 拼名去重后报错。
- 压缩是**日志记录的事务**：`compaction/start` → `compaction/summary`（含 `shadowedRange`/`shadowedSeqs`/`shadowedTokenCount`/`provider`/`model`/`maxTokens`/`usage`/`llmStreamCall` 判别）→ `compaction/end`（可带 `error`）；另有一条不走 LLM 的 `compaction/prune`。
- 事务选项：`owner: 'current-turn' | null`（是否开括号）、`stability: 'whole-surface' | 'selected-span'`（异步摘要期间的 surface 关系必须存活）、`flush?`。
- 专用错误：`SurfaceChangedError`（摘要完成时边界已变）、`ManualCompactionError`、`toolPairingBalancedBefore/After`（工具配对平衡校验）。

### 9.2 XEYO —— 两条预算链 + C0/C1/C2 三档

| 常量/机制 | 值 | 位置 |
|---|---|---|
| per-tool 输出预算默认 | **16000 字符** | `tools/meta.py` `output_budget` 注释 |
| 豁免值 | **0**（自带截断：Bash 的 raw→落盘 seam、Read 防回环） | `Bash`/`Read` 两条 |
| T_now 三层 | 6000 / 2500 / 21 | `pre_llm_inject.py` |
| 嵌套说明限窗 | 4000 | `NESTED_MAX_CHARS` |
| 收尾配额 | `XEYO_WRAP_QUOTA` 覆盖，**默认 3**；0 = 旧的全禁语义 | `query_loop.py:791` |
| 重复提醒阈值 | `[3, 5, 8]` | `RepeatCallGuard` |
| C2 首压前预热门槛 | `_C2_LLM_PREFETCH_MIN_MESSAGES` | `query_loop.py:840` |
| 压缩事件 | `ContextCompressionEvent{phase: start\|complete, source: automatic\|manual, context_tokens, context_limit}` | `msgtypes/events.py:138` |
| 压缩相关函数 | `pair_safe_cut` / `c2_cut_index` / `maybe_advance_aging_boundary` / `_aging_min_advance` / `_pair_ranges` | `memory/runtime.py:215-334` |

**工具配对保护**：`_pair_ranges`（配对区间）+ `pair_safe_cut`（**切割点必须落在配对边界**）+ `c2_cut_index`——与 dsh 的 `toolPairingBalancedBefore/After` 是同一问题的两种实现：**压缩不得拆散 tool_use↔tool_result 对**。

### 9.3 截断/压缩字段级差异

| 维度 | dsh | XEYO |
|---|---|---|
| 工具结果裁剪 | 中间裁剪（头 4096 + marker + 尾 1024，阈值 8192） | 单阈值截断（per-tool 16000），**无头尾保留策略** |
| 超限外部化 | ✅ spill（落盘 + 定位符 + 取回指引） | ✅ Bash 自带 spill（`spilled` 字段上报）；`offload_read` 读回 |
| 外部化失败语义 | 绝不把成功调用变 `isError` | — |
| 上下文压缩 | ✅ 独立 seam + 事务 + 摘要 LLM + 精确到 (provider,model) 的策略 | ✅ C0/C1/C2 三档（确定性摘要，C2 LLM 摘要默认关） |
| 配对保护 | `toolPairingBalanced*` | `pair_safe_cut` |
| 预算单位 | token（`contextWindow × ratio`） | 字符（`len(b)`）+ token（`budget.over_token_budget()`） |
| 压缩可观测 | 4 个事件（start/summary/end/prune）+ `shadowedSeqs` | 1 个事件（phase: start/complete） |
| 保留策略可配 | ✅ 按模型精确覆盖 | ❌ |

---

## §10 LLM 层：逐字段与流式协议

### 10.1 dsh

**能力缝三角色**（`packages/llm/llm/src/types.ts`）

- 发现/配置：`LlmProviderInfo{id, name}`、`LlmConfigurableProvider{provider, displayName, settingsNs, settingsPath, declared?}`
- 模型元数据：`LlmModelInfo{provider, id, name, description?, inputModalities?}` → `LlmResolvedModelInfo`（+`context?: {contextWindow}`, `defaultMaxTokens?`, `reasoning?: {efforts[{id,name,description?}], defaultEffort?}`）
- 推理档：`LlmReasoningEffortInfo{id, name, description?}` / `ReasoningEffortId`（branded）

**KV 缓存**：在 provider 库声明（前轮已核：`llm-pi-ai/catalog.ts:233` `cacheControlFormat:'offer'`），**不在引擎**。`TokenUsage` 有 `cacheReadTokens`/`cacheWriteTokens` 两个独立字段。

**流式**：7 变体 `StreamChunk`（见 §2.1），显式块生命周期 + `replayState` 可重放封套。

**重试**：`llm/retry` 与 `llm/retry-started` 两个**独立事件**（调度决策 vs 实际开始），可在 UI 上渲染倒计时。

### 10.2 XEYO

**provider 抽象**：`ModelClient` 协议（`query_loop.py` 形参 `model: ModelClient`）。
**事件层**：`AssistantDelta{text}` / `ReasoningDelta{text}` 两个**极简** delta 类，无 block 生命周期。
**重试**：`LlmRetryEvent{attempt, next_retry_ms, code, message, provider, model}` + `LlmRetryStartedEvent{attempt, provider, model}` — 与 dsh **同名同语义**（两侧都是"调度"与"开始"两个事件），注释明写 **非 surface 事件、不进 transcript**。
**重试策略函数**：`_llm_max_attempts:263`、`_llm_retry_delay_ms:273`、`_llm_provider_name:284`、`_llm_model_name:288`、`_audit_llm_failure:292`。
**thinking 裁剪**：`ReasoningDelta` + `turn_reasoning_parts`（`query_loop.py:792`）累计。
**usage/token**：`UsageEvent` 19 字段（全文件最重），含 `context_tokens` / `context_limit` / `context_breakdown[{category,label,tokens}]` / `compact_cursor` / `c2_summary_chars` / `cost_source`。
**成本表（`usage/pricing.py`）**

```python
# (cache_hit, cache_miss, output) 元 / 百万 token
_DEEPSEEK = {
    "flash": ((0.05, 1.5, 4.5), (0.10, 3.0, 9.0)),   # (空闲档, 高峰档)
    "pro":   ((0.15, 4.5, 13.5), (0.30, 9.0, 27.0)),
}
_OPENAI_USD = {
    "gpt-4o-mini": (0.15, 0.075, 0.60), "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60), "gpt-4.1": (2.00, 0.50, 8.00),
}
USD_CNY = 7.2
```

- 文档头声明口径："DeepSeek V4 官方价（**2026-08-17 起**）… 高峰 09:00–12:00、14:00–18:00（北京时间）；空闲 = 高峰 × 1/2"。
- **峰谷表可整体覆盖**：`XEYO_TIME_TIERS_JSON`；默认 `{"deepseek": {"windows": {"peak": (("09:00","12:00"),("14:00","18:00"))}, "multipliers": {"peak": 2.0, "offpeak": 1.0}}}`。
- `time_tier()` 支持**跨零点窗口**（`minutes >= s or minutes < e`）；`disabled_models` 可让指定模型不分时。
- `effective_prices()` = 静态基价 × 时段倍率；实时价与本地表都对齐"低峰"，故 peak 倍率 **2.0**。
- 命中率口径原文：`cacheHitPercent = cacheRead/(uncached+cacheRead+cacheWrite)`；无独立 write 档的厂商由 `miss = prompt − hit` 合并计算，`hit/(hit+miss)` 等价。
- ⚠️ **注意**：工作记忆里记的"新价 0.02/1.0/4.0 尚未更新"——本轮实测文件头仍是 **2026-08-17 价表**，且 `_DEEPSEEK` 仍带 peak 倍率。**结论维持**：价格表未同步新价。

### 10.3 字段级差异

| 维度 | dsh | XEYO |
|---|---|---|
| 内容块类型 | 6（text/reasoning/image/file/tool-call/tool-result） | 无类型化块（dict + `type` 字符串） |
| 流式 | 7 变体，显式 block 生命周期 + replay 封套 | 2 个 delta 类（text/reasoning），隐式累积 |
| 结束原因 | 5 变体（`FinishReason`） | `StoppedEvent` 6 值 + `ResultEvent` 7 值 |
| 错误类型 | `LlmFailure{message, code, status?, providerRetryAfterMs?, requestId?}` | `code` 字符串（`classify_llm_failure`） |
| 用量字段 | 6（input/output/total?/cacheRead?/cacheWrite?/reasoning?） | 19（含 context 分段、压缩态、成本源） |
| 成本 | ❌ 无成本统计（全仓无 cost 引擎） | ✅ pricing + ledger + attribution + 峰谷 |
| KV 缓存声明 | provider 库（`cacheControlFormat`） | 靠"前缀逐字节不变"的注入纪律（env_channel 尾插） |
| 重试事件 | 2 个（retry / retry-started） | 2 个（同名同语义） |
| 模型发现 | ✅ `LlmModelDiscovery*` + 拒绝错误码 | ✅ `/v1/models` |

---

## §11 Hooks：wire 协议逐字段

### 11.1 dsh 共用 wire 类型（`hooks/hook-protocol/src/types.ts`）

**`HookOutput` 14 字段**

| # | 字段 | 类型 | 语义（原文要点） |
|---|---|---|---|
| 1 | `exitCode` | `number \| undefined` | 原始退出码；`undefined` = 钩子没跑起来 |
| 2 | `stderr` | `string` | trim 后；**退出 2 时是 block 原因来源** |
| 3 | `stdout` | `string` | trim 后原样保留（干净退出时可为纯文本，CC 渲染为输出，Codex 视作 `additionalContext`） |
| 4 | `continue?` | `boolean` | `false` → 请求停止；配 `stopReason` |
| 5 | `stopReason?` | `string` | 停顿时显示的原因 |
| 6 | `decision?` | `'approve' \| 'allow' \| 'block' \| 'deny' \| 'ask'` | **归一化后的中性阻断决策** |
| 7 | `reason?` | `string` | 随 `decision` 的原因 |
| 8 | `hookEventName?` | `string` | 事件判别式；不匹配则丢弃事件域字段（保留该值） |
| 9 | `additionalContext?` | `string` | 给下次模型请求的额外上下文 |
| 10 | `systemMessage?` | `string` | 展示给用户的警告 |
| 11 | `updatedInput?` | `Record<string, unknown>` | **解析但不采纳**（输入改写已推迟；桥会记日志+告警） |

**关键归一化规则（原文，务必逐字）**

> The neutral blocking decision a hook expressed, folded from the two channels the reference protocols keep **DISTINCT**: the legacy top-level `decision` (`approve`/`block` **only**) and `hookSpecificOutput.permissionDecision` (`allow`/`deny`/`ask`). We normalize them to one enum — `'block'`/`'deny'` forbid, `'approve'`/`'allow'` permit, `'ask'` requests confirmation — but **`'allow'`/`'deny'`/`'ask'` arise ONLY from a `permissionDecision`, never from a top-level `decision`** (an out-of-band `{"decision":"deny"}` is **invalid and ignored**, matching the schemas). Absent ⇒ no explicit decision (exit code governs).

**`CommandHook`**：`{command: string, timeoutSec?: number}`（**wire 单位是秒**，runner 转 ms）。
**`MatcherGroup`**：`{matcher?: string, hooks: CommandHook[]}`；`matcher` 缺席 / `''` / `'*'` = match-all。
**`MatcherMode`**：CC 在模式纯 `[A-Za-z0-9_|]+` 时用**字面量**（竖线=精确择一），否则正则；Codex **恒正则**。
**`DEFAULT_STDERR_SUMMARY_MAX_CHARS = 500`**（两桥共用的唯一默认，放在协议层防漂移）。

**hook 事件（log-only 两条）**

| 事件 | payload 逐字段 |
|---|---|
| `hook/invoked` | `turn`, `point: string`, `dialect: HookDialect`, `matcher?: string`, `handlerId: string` |
| `hook/result` | `turn`, `point`, `handlerId`, `decision: string`, `exitCode?: number`, `stderrSummary?: string`, `durationMs: number` |

### 11.2 三个 hook 点集逐条对照

| 方言 | 支持点 | 数量 | 换算 |
|---|---|---|---|
| **Claude Code** | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStart`, `SubagentStop` | **7** | ✅ 完整 |
| **Codex** | `PreToolUse`, `PostToolUse`, `SessionStart`, `UserPromptSubmit`, `Stop` | **5** | 少 `SubagentStart/Stop` |
| **XEYO** | `PreToolUse`, `PostToolUse`, `PermissionRequest`, `SessionStart`, `SessionEnd` | **5** | 独有的 `PermissionRequest`；缺 `UserPromptSubmit`/`Stop`/`Subagent*` |

**能力差异**：Codex 只认 **block**（deny），不认 `allow`/`ask`；CC 认三种；XEYO 三分结果为 `Success` / `FailedContinue` / `FailedAbort`，**`PermissionRequest` 任一非 Success → fail-closed DENY**。

### 11.3 XEYO hooks 逐字段

| 项 | 值 | 位置 |
|---|---|---|
| 事件元组 | `EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "SessionEnd")` | `extension/hooks.py:41` |
| 默认超时 | `_DEFAULT_TIMEOUT_S = 600.0`（**秒**） | `:44` |
| 结果三态 | `success` / `continue` / `abort` / `skipped` | `HookOutcome:62` |
| `PluginHook` 字段 | `plugin_name`, `event`, `command: Path`, `args: tuple`, `timeout_s=600.0`, `fail_policy="continue"` | `:49-58` |
| 开关 | `hooks_enabled(cwd)` = 扩展层主开关 **&&** hooks 主开关，**默认关** | `:70` |
| 子进程环境 | 剥离仓库级 `GIT_*`（复用 `plugin_fetcher.scrub_git_env`）+ 注入 `XEYO_HOOK_CONTEXT`（JSON） | 文件头 docstring |
| 注入通道 | 钩子 stdout 经 `extension.reconcile.publish_reconcile_block` 走 **T_now 管线**；注释："事件类静默即失，**绝不门控**" | 文件头 docstring |
| 预留 | 注释声明 `Subagent*` / `UserPromptSubmit` / `PrePostCompact` 为**预留** | 文件头 docstring |

### 11.4 Hooks 差异矩阵

| 维度 | dsh | XEYO |
|---|---|---|
| 点集大小 | 7（CC）/ 5（Codex） | 5 |
| 方言兼容 | ✅ 双桥（CC + Codex），各自 wire 差异显式建模 | ❌ 自有协议 |
| 输出解析 | `HookOutput` 14 字段 + 两通道归一化 + 事件名不匹配丢字段 | `HookOutcome{status, blocks, errors}` |
| 阻断 | ✅ `decision` 归一化 5 值；Codex 只认 deny | ✅ `abort`（且 PermissionRequest fail-closed） |
| 超时 | per-hook `timeoutSec`（秒）→ ms | per-hook `timeout_s`（**默认 600**） |
| stderr 摘要上限 | **500** 字符（协议层唯一默认） | — |
| 输入改写 | 解析但**不采纳**（显式推迟） | — |
| 默认开关 | 由组合决定 | **关**（`hooks_enabled` 默认 false） |
| 审计 | `hook/invoked` + `hook/result` 两条事件（进 session log） | 审计文件 |
| 结果去向 | 事件 + `additionalContexts` | stdout → T_now 块 |

---

## §12 Skill / 子代理：逐字段

### 12.1 Skill

**dsh**（`skill/skill-filesystem/src/index.ts`）

| 项 | 内容 |
|---|---|
| 发现 | 用户根目录递归发现（`discoverRoot`），`root.skipSystem` 时跳过 `.system` 目录 |
| frontmatter | YAML；解析出 `name` + `description`（`:101-108`、`:211-212`） |
| 注册结构 | `SkillInfo{name, description, provider}`（`:147`）；provider 默认名 `filesystem`（`:50`、`:161`） |
| 正文加载 | 经 `ctx.fs` 加载（能力缝复用，非直接 fs） |
| 排序 | `entries.sort((a,b) => a.name.localeCompare(b.name))`（`:722`） |
| 注册表 | `ctx.skills` 服务 |

**XEYO**（`tools/meta.py` + `extension/config.py`）

| 项 | 内容 |
|---|---|
| 路径 | `.xeyo/skills/<name>/SKILL.md` |
| 暴露形式 | **工具** `Skill`（`policy=always_allow`, `subagent_ok=True`, `subagent_baseline=False`） |
| 短描述 | "Load on-demand playbook from .xeyo/skills/<name>/SKILL.md." |
| 配置 | `settings.json` 的 `skills: {"<name>": {"enabled": true}}` |
| 直呼 | T_now 第 20 块 `skill_preinvoke`（用户 `/name` 直呼时的宿主确定性加载） |
| 目录变更 | `reconcile_events` 块（事件类，静默即失） |

**差异**：dsh 的 skill 是**注册表能力**（`ctx.skills` seam，可被任意消费者用），XEYO 的 skill 是**一个工具**（模型必须主动调）。dsh 支持 catalog/loader 工具（前轮已核），XEYO 只有单一 `Skill` 工具。frontmatter 字段：dsh 明确只用 `name` + `description`；XEYO 未设独立 frontmatter 解析（由工具实现自行读取）。

### 12.2 子代理

**dsh `SubagentDescriptor` 逐字段**（`subagent/subagent/src/descriptor.ts`）

| 字段 | 类型 | 模式 |
|---|---|---|
| `version` | `number` | 两者 |
| `mode` | `'one-shot' \| 'continuable'` | 两者 |
| `provider` | `string`（`ctx.subagents` provider 名） | 两者 |
| `label?` / `label` | `string` | one-shot 可选 / continuable 必填 |
| `agentProvider?` | `string` | continuable |
| `agentModel?` | `string` | continuable |
| `agentReasoningEffort?` | `ReasoningEffortId` | continuable |
| `persona?` | `string` | continuable（**resume 时遮蔽部署 persona**） |
| `toolFilter?` | `ToolRestriction` | continuable（**resume 时重新施加**） |

**关键设计**：递归深度存在 **`SessionHeader.delegationDepth`**（父深度 + 1），注释原文：

> Persisted so a recursion budget survives restart and resume — **a runtime-only depth would reset a resumed child to top-level**.

**XEYO**：`Agent` 工具（`policy=agent_allow`, `needs_write_store=True`, `needs_runtime_provider=True`, `subagent_ok=False`）；短描述声明"sub-agents: **Git + readonly Bash sandbox**; no Memory/nested Agents"；配套 `FORBIDDEN_SUB_TOOLS`（`enabled and not subagent_ok`）与 `SUBSET_TOOL_BASELINE` 白名单；还有 `subagent_baseline=False` 的例外项（`Skill` / `NotebookEdit`）。

**差异**

| 维度 | dsh | XEYO |
|---|---|---|
| 描述符 | ✅ 类型化 9 字段 + 版本号 | ❌（注册表白名单 + 运行时参数） |
| 可续跑 | ✅ `continuable` + persona/toolFilter 重施 | 短生命周期（"short-lived"） |
| 深度预算 | ✅ 持久化到 header | ❌ |
| 控制工具 | 4 个（list/interrupt/send_message/list_subagent_models） | 1 个（Agent，无控制面） |
| 团队模式 | ✅ 6 个 team_* 工具（实验） | ❌ |
| 子代理隔离 | 沙箱 + toolFilter | 工具白名单（Git + 只读 Bash） |

---

## §13 调度 / 后台 / 工作流：逐字段

| 能力 | dsh | XEYO |
|---|---|---|
| 定时任务 | ✅ `schedule/*`（`schedule_create/delete/list` + `schedule/change` 事件） | ❌ **无时间触发型定时任务**（`engine/scheduler.py` 是 **DAG 调度器**，非定时器——本轮维持前轮更正） |
| 后台作业 | ✅ `job_*` 3 工具 | ✅ `job_output/job_list/job_kill` 3 工具（同名同数） |
| 作业状态枚举 | `'running' \| 'stopping' \| 'completed' \| 'killed' \| 'failed'`（`SessionJob.status`） | `job_output` 尾部 `[status: ...]` 文本 |
| 工作流引擎 | ✅ `workflow` + `ralph` + `tool-workflow/{run,agent}-{start,end}` 4 事件 | ❌（全仓 `workflow` 零命中） |
| Webhook 入口 | ✅ `packages/webhook/` | ❌ |
| Goal | ✅ `create_goal/get_goal/update_goal` + `goal/change` | ✅ T_now `goal` 块（仅 blocked/pending_complete 注入） |
| Todo | ✅ `todo_write` + `todo/write` 事件 | ✅ `TodoWrite` 工具（`ToolResultEvent.todos` 结构化 UI 载荷） |
| 计划 | plan 为 **logged state**（`plan/mode`） | **mode**（`mode_instructions` 块）+ `plan_pending/resolved` 挂起三件套 |

---

## §14 服务端协议：XEYO 101 路由逐条 + 23 帧

### 14.1 XEYO 全部 HTTP 路由（101 条，按文件分组）

| 文件 | 条数 | 路由 |
|---|---|---|
| `audit.py` | 1 | GET `/v1/audit/events` |
| `chat.py` | 2 | POST `/v1/chat/completions`；POST `/api/chat` |
| `commands.py` | 2 | POST `/v1/slash`；POST `/v1/slash/parse` |
| `control.py` | 13 | GET `/v1/settings/memory`；POST `/v1/settings/memory`；POST `/v1/settings/memory/snapshot`；POST `/v1/interrupt`；POST `/api/interrupt`；POST `/v1/permission/resolve`；GET `/v1/permissions/grants`；DELETE `/v1/permissions/grants/{grant_id}`；POST `/v1/ask/resolve`；GET `/v1/settings/rewind-gc`；PUT `/v1/settings/rewind-gc`；POST `/v1/settings/rewind-gc/run`；POST `/v1/plan/{turn_id}/approve` |
| `extensions.py` | 2 | GET `/v1/extensions/settings`；POST `/v1/extensions/settings` |
| `goals.py` | 3 | GET/PATCH `/v1/sessions/{id}/goal`；POST `/v1/sessions/{id}/goal/round-driver` |
| `jobs.py` | 1 | GET `/v1/sessions/{id}/jobs` |
| `mcp.py` | 2 | GET `/v1/mcp`；POST `/v1/mcp/op` |
| `media.py` | 3 | GET `/v1/media/{digest}`；POST `/v1/media/upload`；POST `/v1/files` |
| `memory.py` | 3 | GET `/v1/memory/notes`；POST `/v1/memory/search`；POST `/v1/memory/compact` |
| `plugins.py` | 5 | GET `/v1/plugins`；POST `/v1/plugins/install`；POST `/v1/plugins/update`；POST `/v1/plugins/remove`；GET `/v1/plugins/market` |
| `references.py` | 1 | GET `/v1/references/files` |
| `rewind.py` | 7 | POST `/v1/sessions/{id}/rewind`；POST `…/rewind/{rid}/undo`；POST `…/rewind/{rid}/recover`；GET `…/rewind/{rid}`；GET `…/rewind`；GET `…/rewind/checkpoint/{mid}`；POST `…/rewind/checkpoint/{mid}/anchor` |
| `sessions.py` | **32** | POST `/v1/sessions`；POST `…/runtime-mode`；GET/POST `…/runtime-preset`；DELETE `/v1/sessions/{id}`；POST `…/delete`；GET `/v1/sessions`；GET `/v1/workspaces/sessions`；POST `…/rename`；POST `…/fork`；POST `…/archive`；POST `…/restore`；GET `…/messages`；POST `…/ui-thoughts`；GET `…/compression`；GET `…/agents`；GET `…/agents/{aid}`；POST `…/agents/{aid}/cancel`；POST `…/agents/{aid}/inbox`；DELETE `…/agents/{aid}/inbox/{iid}`；POST `…/agents/{aid}/retry`；POST `…/rollback/preview`；POST `…/rollback/execute`；POST `…/rollback/jobs/{jid}/recover`；GET `…/rollback/status/{jid}`；GET `…/task`；GET `…/turns/current/events`；POST `…/recovery/abandon`；GET `…/inbox`；DELETE `…/inbox/{qid}`；PATCH `…/inbox/{qid}`；POST `…/inbox/resume` |
| `skills.py` | 1 | GET `/v1/skills` |
| `usage.py` | 3 | GET `/v1/models`；GET `/v1/usage`；GET `/v1/usage/balance` |
| `workspace.py` | 20 | GET/POST `/v1/workspace/policy-bash`；GET/POST `/v1/workspace`；GET `/v1/workspace/entries`；GET `/v1/workspace/file`；GET `…/file/stat`；PUT `…/file`；DELETE `…/file`；GET `…/graph`；GET `…/outline`；POST `…/map/explain`；GET `…/search`；GET `…/journal`；GET `…/peers`；GET `…/git/status`；GET `…/git/log`；GET `…/git/branches`；GET `…/file/diff`；POST `…/terminal/exec` |

**结构特征**：`sessions.py` 独占 32 条（生命周期 + agents + rollback + inbox 四组）；`workspace.py` 20 条（文件读写 + git + 检索 + journal + peers）；两者合计 52 条（51%）。

### 14.2 XEYO SSE 23 帧逐条（`server/routers/chat.py`，1575 行）

| # | 帧名 | 通道 | 产出行 | 依据 |
|---|---|---|---|---|
| 1 | `goal` | xy | 1024 | `{"type":"goal","goal":…,"driver":…}` |
| 2 | `jobs` | xy | 1043 | `{"type":"jobs","jobs":…,"wake_budget_left":…}` |
| 3 | `title` | xy | 1071 | `{"type":"title","title","pinned","enhanced"}` |
| 4 | **`assistant_delta`** | **OpenAI 兼容** | 1103 | `_openai_chunk(ev.text, model=…)` → 标准 chat chunk |
| 5 | `reasoning_delta` | xy | 1103 | `{"type":"reasoning_delta","text":…}` |
| 6 | `tool_call` | xy | 1117 | 含 `name` / `input`（经 `_sanitize_tool_input_for_ui`）/ `tool_use_id?` |
| 7 | `tool_progress` | xy | 1134 | `name` / `tool_use_id` / `message` / `elapsed_ms` |
| 8 | `tool_result` | xy | 1154 | +`todos?` / `ui?` |
| 9 | `llm_retry` | xy | 1173 | +`message?` / `provider?` / `model?` |
| 10 | `llm_retry_started` | xy | 1188 | +`attempt` / `provider?` / `model?` |
| 11 | `usage` | xy | 1260 | +`context_breakdown?` / `compact_cursor` / `last_action` / `c2_summary_chars` |
| 12 | `permission_pending` | xy | 1279 | +`path` / `expires_at` / `choices` / `peer_summary` / `intent` |
| 13 | `permission_resolved` | xy | 1294 | +`approved` / `actor` / `reason` / `resolved_at` / `choice` |
| 14 | `ask_user_pending` | xy | 1310 | +`turn_id` / `question` / `options` / `default` / `expires_at` |
| 15 | `ask_user_resolved` | xy | 1324 | +`answer` / `actor` / `timeout` / `resolved_at` |
| 16 | `plan_pending` | xy | 1338 | +`session_id` / `turn_id` / `plan` / `expires_at` |
| 17 | `plan_resolved` | xy | 1352 | +`approved` / `actor` / `reason` / `resolved_at` |
| 18 | `task_state_changed` | xy | 1365 | +`task_status` / `current_tool` / `interruptible` / `error` |
| 19 | `context_compression` | xy | 1384 | +`context_tokens?` / `context_limit?` |
| 20 | `final` | 终止帧 | 1205 | — |
| 21 | `stopped` | 终止帧 | 1222 | — |
| 22 | `error` | OpenAI 风格 | 566（`_sse_error`） | `error_body(message, err_type)`，前端 `parseOpenAiSse` 读 `obj.error` |
| 23 | `[DONE]` | 哨兵 | 1401/1406/1415 | `data: [DONE]` |

**双通道事实**：`AssistantDelta` 在 `server/` 目录里**零命中**——它被编码成 OpenAI 兼容 chunk 走出通用通道；其余 18 类全部走 `_xy_chunk(xy, model=…)` 旁路（每帧带 `event_id`）。

**关键辅助函数**：`_engine_for` / `_workspace_for` / `_busy_or_queue` / `_effective_request_modes` / `_build_enriched_resume_prompt` / `_engine_message_from_chat` / `_split_prior_and_user` / `_openai_chunk` / `_xy_chunk` / `_sanitize_tool_input_for_ui` / `_sse_error`。

### 14.3 协议形态差异

| 维度 | dsh | XEYO |
|---|---|---|
| 形态 | **类型化 RPC**（Typert 类型图，`RemoteErrorDetailsMap` 声明错误码） | **REST + SSE** |
| 契约来源 | 类型图自动生成（`typert`） | 手写路由 + Pydantic |
| 错误类型 | `RemoteErrorDetailsMap`（如 `'session/not-found': {sessionId}`、`'llm/model-discovery-rejected'`） | `error_body(message, err_type)` |
| 事件流 vs RPC | 事件流走高吞吐 follow 帧（`SessionFollowFrame`：`snapshot` / `SessionEventEntry` / `assistant-stream`） | 单条 SSE 混装数据 + 终止 |
| 首帧形态 | `snapshot`（含 `header`/`cursor`/`records`/`hasMore`/`projections`） | xy 帧逐条推送（`event_id`） |
| 游标 | `SessionSearchCursor` / `SessionSeqCursor` | 无 |
| 客户端类型 | TS SDK + Python SDK + ACP | Typer CLI + HTTP attach + TUI |

---

## §15 前端与桌面壳：逐模块

### 15.1 XEYO `gui/src`（391 文件 / 81,484 行）

| 目录 | 文件数 | 职责 |
|---|---|---|
| `components/` | **131** | React 组件（含 Composer / 消息列表 / 工具卡片 / 审批 / 侧栏 / 设置） |
| `lib/` | **165** | 协议层、工具、工具函数（最大模块） |
| `stores/` | **41** | 状态（zustand 类） |
| `pet/` | 15 | 桌宠 |
| `pasture/` | 12 | （待查） |
| `hooks/` | 10 | 自定义 hooks |
| `bench/` | 8 | 基准页 |
| `theme/` | 2 | 主题 |
| `generated/` | 1 | 生成物（斜杠 manifest） |
| `App.tsx` / `main.tsx` / `paths/` / `test/` | 各 1 | 入口与测试 |

**SSE 消费**：`lib` 中 `case '<name>':` 分支为前端消费口径（前轮实测）。
**IndexedDB**：`session.spaceId → rootPath` 映射，按 origin 隔离；权威 transcript 在后端 JSONL。

### 15.2 XEYO Rust 壳（3 文件 / 1,162 行）

| 文件 | 行数 | 职责 |
|---|---|---|
| `lib.rs` | ~1,000（31,110 字节） | 后端进程拉起 + 窗口/托盘/快捷键 + commands（`resolve_python_exe` / `python_exe_usable` / `BACKEND_SPAWN_ERROR` / `get_backend_error`） |
| `main.rs` | 104 字节 | 入口 |
| `pet.rs` | 4,832 字节 | 桌宠窗口 |

### 15.3 dsh 前端

| 项 | 内容 |
|---|---|
| 包数 | `packages/client/` 下 **45 个子包目录**（`ls packages/client` 返回 50 条目 = 45 目录 + 5 文件：`AGENTS.md`/`README.md`/`README.zh.md`/`README.i18n.yaml`/`tsdown.client.ts`） |
| 组装机制 | **slots**（`ui-slots`）——插件式 UI 注册 |
| store / connection | 独立子包（`store` / `connection`） |
| Trajectory | `ui-trajectory` 面板（按来源检查、搜索、分叉、重放） |
| 桌面壳 | ❌ **无**（apps 下只有 `cli` 与 `web`） |
| CLI | `apps/cli/`（profile 解析：web/headless/sdk/sdk-minimal/acp） |
| Web | `apps/web/` + 浏览器快照测试（`snapshots/web/`、`apps/web/tests/expected/`） |

### 15.4 差异

| 维度 | dsh | XEYO |
|---|---|---|
| UI 粒度 | 45 个独立包 + slots 注册 | 1 个 `gui/src`（131 组件 + 165 lib） |
| 插件式 UI | ✅ | ❌ |
| 桌面壳 | ❌ | ✅ Tauri（进程守护 + 自包含 venv 断言） |
| 桌宠 / 系统集成 | ❌ | ✅ pet.rs + Screenshot + SendToWeChat + XeyoUI |
| 终端 UI | CLI（无 TUI） | ✅ `tui/`（Ink，3,544 行） |
| 浏览器快照门 | ✅ | ❌ |
| i18n | ✅ 双语（locale 子包） | 未见独立 i18n 层 |

---

## §16 工程门禁：逐条

### 16.1 dsh

| 门 | 内容 | 证据 |
|---|---|---|
| 覆盖率门 | `pnpm run test:coverage` — **per-file 100% on `packages/*/*/src`** | `docs/testing.md:10` |
| 覆盖率哲学 | "An uncovered line is often **dead code the gate flags for deletion**, not a missing test to bolt on. Line coverage is necessary, never sufficient." | 同上 |
| 平台豁免 | `packages/shell/pwsh-local/src` 需真实 pwsh；无 pwsh 的机器 suite 自跳过且 `vitest.config.ts` 豁免该文件；CI 有 pwsh 则全量执行 | 同上 |
| 真实 API e2e | `pnpm run test:e2e`（`EXA_API_KEY` / `PERPLEXITY_API_KEY` 等各自 gate，无 key 自跳过） | `:11` |
| 浏览器快照 | `pnpm run test:web`（**required Linux PR gate**）；CI 强制 `DSH_SNAPSHOT=replay` **只读**；录制/刷新仅本地且每次 diff 需 review | `:14` |
| fixture 版本链 | 当前 **v2**（每事件一行 + 内嵌 compact Assistant 流）；保留 v0（无后缀）/ v1（`.v1`）；迁移器 `scripts/migrate-packed-session-fixtures.ts` | `:16` |
| 并行纪律 | 只有进程隔离；端口 / 可预测路径 / 外部命名空间 / 继承子进程**不隔离**；"a spec that passes only when it runs alone [is] a defect in the spec" | `:20` |
| 测试规模 | **863** 个 spec/test 文件 | 实测 |

### 16.2 XEYO

| 门 | 内容 | 证据 |
|---|---|---|
| 本地统一门 | `pwsh -File scripts/check.ps1`：Python `pytest -q --timeout=60 -m "not live"` + `slash.export_manifest --check` → GUI `npm run typecheck` + `npm test` → tui `npm run typecheck` | `scripts/check.ps1` |
| CI | `push` 到 main/master + PR；`python` job（3.11，pytest + slash manifest drift check）+ `gui` job（node 20，typecheck + test） | `.github/workflows/ci.yml` |
| 覆盖率门 | ❌ 无 | — |
| 浏览器快照 | ❌ 无 | — |
| 契约冻结测试 | ✅ T_now 登记表执法（4 用例）、扩展层 6 个契约测试、bash 路由契约 | `tests/test_t_now_block_registry.py` 等 |
| 测试规模 | pytest **307** / vitest **102** | 实测 |
| 提交门 | AGENTS.md 规定 `tsc + vitest + pytest P0` 全绿才 commit；**无 pre-commit/husky**（靠人跑） | `AGENTS.md` |

### 16.3 门禁强度对照

| 维度 | dsh | XEYO |
|---|---|---|
| 覆盖率 | per-file 100% 硬门 | 无 |
| e2e 真实 API | ✅ 分 key 自跳过 | 部分（`-m "not live"` 反向） |
| 浏览器快照 | ✅ required PR gate | ❌ |
| 契约/冻结测试 | 包级 invariant 文件（`invariant.ts` 出现在 session/tools/sandbox/compaction 等包） | 集中在 tests/ 若干文件 |
| fixture 版本迁移 | ✅ v0/v1/v2 + 迁移器 | ❌（无版本号） |
| 门禁自动化 | 覆盖率 + e2e + web + lint 全自动 | 3 段脚本 + CI，无覆盖率 |

---

## §17 字段级差异总矩阵

| # | 维度 | dsh | XEYO | 性质 |
|---|---|---|---|---|
| 1 | 事件类型数 | 51 | 20（19 生效） | dsh 多 31 |
| 2 | 事件封套 | 统一 7 字段 | 无封套 | 结构性 |
| 3 | 日志版本 | `SESSION_FORMAT_VERSION=2` + 迁移链 | 无 | 结构性 |
| 4 | 未知事件 | `ignorable` 缺席即拒绝重建 | 静默 | 安全方向相反 |
| 5 | surface 投影 | 显式三态 + replace + 来源引用 | 无 | 结构性 |
| 6 | 序号/游标 | 类型化 `SessionSeq`/`SessionLogOffset` | 无 | 结构性 |
| 7 | 沙箱 | 4 平台 + fail-closed + 升级仲裁 | 无（仅 Job Object + docker 旁径） | 缺一层 |
| 8 | 权限判定 | 事件瀑布 + 组合 | 单函数 6 分支 + 5 守卫 | 形态差 |
| 9 | 命令语义分析 | ❌ | ✅ 5 函数反推写目标 | XEYO 独有 |
| 10 | grant store | 审批制（`allowed-once`） | 指纹 v2 + 排除四类 | XEYO 更细 |
| 11 | 审批告知模型 | ❌ 刻意不给 | ✅ T_now 块 | 相反 |
| 12 | 逐轮注入 | 各插件自管 | T_now 20 块 + 硬顶 21 + 三层预算 | XEYO 独有 |
| 13 | 注入声道 | `MessageSource` 元数据 | 伪造 tool 对（结构隔离） | 相反 |
| 14 | 工具 schema | 3 字段（name/description/parameters） | meta 表 14 字段 | 维度不同 |
| 15 | 工具注册校验 | 包 invariant | 注册期 5 项硬失败 | XEYO 更严 |
| 16 | 工具执行 | 9 阶段事件瀑布（6 可拦截） | 顺序调用链（0 扩展点） | 形态差 |
| 17 | 结果后处理 | block / replace / context 三态 | 追加后缀 + 折叠 | 能力差 |
| 18 | 重复检测 | 3 档 [3,5,8]，**拒绝也计数** | [3,5,8]，轮内重置 | 近似对等 |
| 19 | 结果裁剪 | 头 4096 + marker + 尾 1024（阈值 8192） | 单阈值 16000 截断 | 策略差 |
| 20 | 外部化 | spill + 定位符 + 取回指引 | Bash 自带 spill + `offload_read` | 近似对等 |
| 21 | 压缩 | 独立 seam + 事务 + LLM 摘要 + 按模型覆盖（0.8/0.16/8192） | C0/C1/C2（确定性，LLM 摘要默认关） | 层级差 |
| 22 | 配对保护 | `toolPairingBalanced*` | `pair_safe_cut` | 对等 |
| 23 | LLM 流 | 7 变体 + block 生命周期 + replay 封套 | 2 delta 类 | 层级差 |
| 24 | 用量字段 | 6 | 19（context 分段 + 压缩态 + 成本源） | XEYO 更细 |
| 25 | 成本 | ❌ | pricing + ledger + 峰谷表（可 env 覆盖） | XEYO 独有 |
| 26 | KV 缓存 | provider 库 `cacheControlFormat` | 注入纪律（前缀不动） | 位置不同 |
| 27 | Hooks 点集 | 7（CC）/ 5（Codex） | 5 | 近似 |
| 28 | Hooks wire | 14 字段 + 双通道归一化 | 4 字段 outcome | 层级差 |
| 29 | Skill 暴露 | `ctx.skills` seam + catalog/loader 工具 | 单一 `Skill` 工具 | 层级差 |
| 30 | 子代理描述符 | 类型化 9 字段 + 持久化深度 | 白名单 + 短生命周期 | 层级差 |
| 31 | 定时任务 | ✅ | ❌ | dsh 独有 |
| 32 | 工作流 | ✅ workflow + ralph | ❌ | dsh 独有 |
| 33 | Webhook | ✅ | ❌ | dsh 独有 |
| 34 | 会话自查询工具 | 5 | ❌ | dsh 独有 |
| 35 | 自修改工具 | 7 个 `cordis_*` | ❌ | dsh 独有 |
| 36 | 持久终端 | 6 工具 | ❌ | dsh 独有 |
| 37 | rewind | ❌ | ✅ v2/v3 + 7 条路由 + GC 设置 | XEYO 独有 |
| 38 | 跨会话记忆 | ❌（穷举零命中） | ✅ `memory/` 27 模块 | XEYO 独有 |
| 39 | 预算/死线 | ❌ | ✅ BudgetTracker + 收尾窗 + wrap quota | XEYO 独有 |
| 40 | 桌面集成 | ❌ | ✅ Tauri + 桌宠 + 微信 + 截图 | XEYO 独有 |
| 41 | 协议 | 类型化 RPC + 双 SDK + ACP | REST 101 路由 + SSE 23 帧 | 形态差 |
| 42 | 前端 | 47 包 + slots | 单包 391 文件 | 结构差 |
| 43 | 覆盖率门 | per-file 100% | 无 | dsh 独有 |
| 44 | 浏览器快照 | ✅ PR gate | ❌ | dsh 独有 |
| 45 | fixture 迁移 | v0/v1/v2 + 迁移器 | ❌ | dsh 独有 |

---

## §18 行为对照用例：同一任务在两端各发生什么

**任务**：用户说「把 `config/app.yaml` 里的 `timeout: 30` 改成 `timeout: 60`」。

### 18.1 dsh 逐步

| 步 | 发生的事 | 依据 |
|---|---|---|
| 1 | `turn/start{turn}` | 核心事件 |
| 2 | `request/header{header:{config, system, tools}, reason:'initial'}` 落日志 | 工具面与 system 快照进日志 |
| 3 | `step/start{turn, step}` | |
| 4 | 流：`block-start(text)` → `text-delta*` → `block-end(TextBlock)` → `block-start(tool-call)` → `tool-call-delta{argumentsDelta}` × N → `block-end(ToolCallBlock)` → `usage` → `finish{tool-calls, replayState}` | `StreamChunk` 7 变体 |
| 5 | 落 `assistant/message{turn, step, message, stream, usage}` | surface 事件 |
| 6 | 落 `tool/call{callId, name:'read', arguments:'{"path":"config/app.yaml"}'}`（**原始字符串**） | |
| 7 | 执行管线：`tools/execute` → timeout 包装（读 `tool.timeoutMs`，无则跳过）→ `PreToolUse` hook → `ctx.sandbox.confine(argv, policy)`（默认 `read-only`）→ 执行 | §3.1 |
| 8 | `tools/post-execute`：repeat guard 计数 → spill 判定（超 `maxInlineBytes` 则落盘替换） | |
| 9 | 落 `tool/result{turn, step, message, meta?}`；`meta` 非 JSON 可序列化则**源头拒收** | |
| 10 | 落 `step/end`，进入下一步：**重新** 组装 system prompt 与工具列表 → `request/header`（**只有变化时才落**） | 工具面不冻结 |
| 11 | 第二次 `read` → 然后 `edit`：`PreToolUse` 对 `edit` 触发审批（策略档决定）→ 落 `approval/asked` | |
| 12 | 用户批准 → `approval/decided`；**策略句以动态 context 形式进入下一请求，事件本身不进 transcript** | |
| 13 | `edit` 执行；`fs-sandbox` 三重包含判定（词法 → `stat(bigint)` 逐级祖先 → `dev/ino` 身份） | §8.3 |
| 14 | 落 `tool/result`，`turn/end{reason:{kind:'completed'}}` | |

**关键**：模型**看得见** `approval` 的结果（工具返回了什么），但**看不见**审批策略本身。工具面每步可重算。

### 18.2 XEYO 逐步

| 步 | 发生的事 | 依据 |
|---|---|---|
| 1 | `query_loop` 进入 `while True`；首轮 `budget.prepare_next_turn()` 通过 | `query_loop.py:796-800` |
| 2 | `_repair_unpaired_tool_calls(store, "aborted")`（**只在 submit 入口做一次**） | `:795` |
| 3 | `clear_advice()` 清轮首残留提醒；新建 `RepeatCallGuard` / `IdenticalResultFold` / `LoopLedger` / `ZeroHitTracker` | `:774-783` |
| 4 | `budget.begin_turn()`；计算 `remaining = max_turns + grace - turn_count` | `:823-828` |
| 5 | T_now 装配：`tagged` 开始累块（continue/mode/runtime_budget/…）→ `_trim_tagged_blocks` → **`append_env_notice_pair` 伪造 tool 对尾插** | §6 |
| 6 | 流：`AssistantDelta` → SSE 编码为 **OpenAI 兼容 chunk**；`ReasoningDelta` → `_xy_chunk` | §14.2 |
| 7 | `ToolCallEvent{name, input（已解析 dict）, tool_use_id, input_summary, parallel}` | |
| 8 | 权限：`evaluate_policy(name='Read', tool_input, cwd, …)` → `read_path` 分支 → `readonly_gate` → `ALLOW`；grant 层早返回 | §4.1 |
| 9 | 只读工具走 `_eligible_for_early` 预取并发；`ensure_before` 保证 rewind Before 快照就绪 | |
| 10 | 结果：`result_fold.process()` 折叠同签名同输出；`store.append(tool_result_message(...))`；发 `ToolResultEvent{…, duration_ms, spilled}` | `:1971-1983` |
| 11 | `Edit` 调用：`write_path` 分支 + `needs_read_state`（必须先 Read）+ `needs_write_store` 注入 → `WriteStore` 写路径 | |
| 12 | 若需审批：`PermissionPendingEvent{request_id, tool_name, tool_input, reason, prompt, path, expires_at, intent='confirm'}`；30s 前发 `PermissionExpiringEvent` | §5.1 |
| 13 | 用户点批准 → `/v1/permission/resolve` → `PermissionResolvedEvent{approved:True, choice='allow'}`；可选"记住"→ grant store（指纹 v2） | |
| 14 | 下一次同工具同参数 → `evaluate_policy` 的 grant 层命中 → `ALLOW / always_allow_grant`（**但 bash 复合命令不吃 grant**） | §4.1 |
| 15 | 轮末：`abort.aborted` / `over_token_budget()` / `prepare_next_turn()` 任一命中 → `StoppedEvent`；否则继续 while | `:1991-2000` |

**关键**：模型**看得见** `runtime_mode_snapshot`（审批模式告知）；工具面 `schemas_json_cache` 会话内不变（`query_loop.py:771`）；T_now 每轮重建但**尾插不改前缀字节**。

### 18.3 同任务的行为差异清单

| 环节 | dsh | XEYO |
|---|---|---|
| 审批策略可见性 | 不可见 | 可见（T_now 块） |
| 工具参数给模型看什么 | `arguments` 原字符串 | `input` 已解析 dict |
| 工具面 | 每步可重算 | 会话内冻结（`schemas_json_cache`） |
| 逐轮易变信息 | 各插件自塞 user 消息 | T_now 20 块 + 3 层预算 + 伪造 tool 对 |
| 写盘保护 | 沙箱强制（内核级） | 引擎级（write_path + needs_read_state + WriteStore） |
| 命令分析 | 无 | bash 文本反推写目标 |
| 审批重放 | ✅ 事件溯源可重建"当时看到什么" | 靠 JSONL 直出（无 header 快照） |
| 崩溃恢复 | `interrupted` 事后补写 closer | rewind v2/v3 + 中断锚 |
| 上下文压力 | `thresholdRatio 0.8` 自动压缩 | C0/C1/C2 分档 |

---

## §19 本轮覆盖自检

**精读的文件（`Read` 全文或 Python 逐段）**

| 侧 | 文件 | 方式 |
|---|---|---|
| dsh | `core/session/src/types.ts` | Read 全文（484 行） |
| dsh | `core/tools/src/types.ts` | Read 全文（59 行） |
| dsh | `core/agent-loop/src/constants.ts`、`tool-calls.ts`、`agent.ts`、`assistant-stream.ts` | 前轮 Read（本轮未重读） |
| dsh | `guard/repeat-tool-reminder/src/index.ts` | cat 全文 |
| dsh | `guard/timeout-policy/src/index.ts` | cat 全文 |
| dsh | `sandbox/sandbox/src/index.ts`（节选）、`sandbox-local/src/profiles.ts` | 切片 |
| dsh | `sandbox/sandbox-policy/src/index.ts`（1-120）、`session-mode.ts` | 切片 |
| dsh | `spill/spill-policy/src/index.ts`（1-130）、`types.ts` | 切片 |
| dsh | `compaction/compaction-basic/src/config.ts` | cat 全文 |
| dsh | `compaction/compaction-basic/src/region.ts`（1-80） | 切片 |
| dsh | `compaction/compaction-tool-result-pruner/src/config.ts` | cat 全文 |
| dsh | `hooks/hook-protocol/src/types.ts`、`events.ts` | cat 全文 |
| dsh | `hooks/hooks-claude-code/src/config.ts`（1-40） | 切片 |
| dsh | `llm/llm/src/types.ts` | Python 逐 interface |
| dsh | `subagent/subagent/src/descriptor.ts`（51-105） | 切片 |
| dsh | `interaction/permission-presets/src/types.ts` | 切片 |
| dsh | `docs/tool-catalog.md` | 系统提取 |
| dsh | `docs/testing.md` | 系统提取 |
| XEYO | `python/tools/meta.py` | Read 全文（414 行） |
| XEYO | `python/msgtypes/events.py` | Read 全文（333 行） |
| XEYO | `python/prompt/pre_llm_inject.py` | 逐段（登记表/装配/裁剪/常量） |
| XEYO | `python/prompt/turn_context.py` | 逐段（3 个注入函数） |
| XEYO | `python/permissions/policy.py`（1319-1470 + 符号表） | 切片 |
| XEYO | `python/tools/catalog.py` | 逐段（注册校验 + BENCH_MINIMAL） |
| XEYO | `python/engine/query_loop.py`（726-845 + 1940-2000 + 符号表） | 切片 |
| XEYO | `python/extension/hooks.py` | 全文结构 + 前 70 行 |
| XEYO | `python/extension/config.py` | 逐段 |
| XEYO | `python/slash/registry.py` | 系统提取 + 前 60 行 |
| XEYO | `python/usage/pricing.py`（1-4200 字节） | 切片 |
| XEYO | `python/server/routers/chat.py` | 系统提取（帧清单 + 产帧点上下文） |
| XEYO | `server/routers/*.py` × 17 | 正则提取全部路由 |

**未见 / 未逐行读（诚实边界）**

- dsh：`core/tools/src/{json-schema,schema,ptc,ts-types,py-types}.ts`（schema 生成三条路径仅知存在，未读实现）；`core/agent-loop/src/agent.ts` 本轮未重读（前轮已读）；`sandbox/sandbox-local/src/index.ts` 全文（仅读 profiles + 引用行）；`sandbox-windows-acl/*` 9 文件（仅知结构）；`packages/e2b/`；`typert` 类型图实现；`client/ui-*` 47 包内部（按 slots 机制理解，未逐行）；`session-query` 5 工具入参细节（仅知名与包）。
- XEYO：`permissions/policy.py` 第 1470 行之后的分支（`ui_ask` / `read_path` / `write_path` / `agent_allow` / `_evaluate_bash` 194 行内部逻辑）；`gui/src/lib` 165 文件内部；`tui/` 内部；`memory/` 27 模块内部（仅知文件名与 `runtime.py` 函数名）；`server/routers/chat.py` 1000 行之前的请求装配段。

**否定判断的穷举范围**：所有「XEYO 无 X」结论均在 `--exclude-dir=.venv --exclude-dir=__pycache__` 下全仓 `python/` 检索得出；所有「dsh 无 X」在 `packages/` 全树检索得出。

---

## §20 本轮结论（一句话级）

1. **本轮的增量全在"可核验的枚举"**：51 个事件 × 逐字段、57 个工具名、62 条工具目录、101 条路由、23 个 SSE 帧、35 条斜杠命令、26 个工具 × 14 字段、20 个 T_now 块 × 3 类预算——每一条都能用一行命令复现。
2. **三处更正**：dsh 事件数是 **51**（第三轮的 48 漏了 3 个双斜杠键名）；`SESSION_FORMAT_VERSION=2` 的 bump 规则是"看 writer 不看 reader，加事件不 bump"；62 条工具目录 ≠ 62 个工具（去重 57）。
3. **dsh 的五处"层"**在字段级看更清楚：事件封套 7 字段 × 51 事件、沙箱 4 平台 × 逐参数、hook wire 14 字段 × 双通道归一化、compaction 事务 × 按模型覆盖、per-file 100% 覆盖门——**XEYO 在这五处的对应物都是"若干函数或约定"**。
4. **XEYO 的四处"独有资产"**在字段级同样清楚：T_now 20 块 + 三层预算 + 逐行裁剪算法、`env_channel` 伪造 tool 对（5 字段结构隔离）、grant 指纹 v2 + 四类不吃 grant 的排除、19 字段 UsageEvent + 峰谷可 env 覆盖——**dsh 这四处没有对应物**。
5. **两端的取舍是镜像的**：dsh 用"更厚的结构层"换可替换性与可迁移性（代价：51 类事件、255 包、863 测试文件的复杂度）；XEYO 用"更厚的注意力纪律与执行期不变量"换信息正确性（代价：无沙箱、无事件溯源、无覆盖率门、扩展点为 0）。

