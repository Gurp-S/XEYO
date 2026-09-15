# XEYO ⟷ DeepSeek Harness 全量对比 · 第三轮：实现级

> 第一轮 `XEYO-vs-DeepSeekHarness-全量对比.md`（605 行 / 功能面）
> 第二轮 `XEYO-vs-DeepSeekHarness-设计级对比-第二轮.md`（1307 行 / 设计面 32 系统）
> **本轮（第三轮）只写实现细节**：函数签名、数据结构逐字段、算法步骤、常量默认值、错误分支、边界条件、并发/中断代码路径。设计动机与功能清单不重复，需要时回了指前两轮。

**取证基线**

| | dsh | XEYO |
|---|---|---|
| 版本 | `d347e70` / `0.1.3-alpha.1` / master | 工作树（2026-09-10） |
| 代码量 | 1611 个 `src/**.ts`（packages+apps） | python 1141 文件 / 160,772 行 |
| 测试 | 863 个 `.spec/.test.ts` | python 307 个 `test_*.py`；gui 102 个 |
| 其他规模 | 255 个包 | gui 391 文件 / 81,484 行；tui 29 文件 / 3,544 行；rust 3 文件 / 1,162 行 |

**本轮取证方式（与前两轮不同）**：子代理被限流（23:47 才恢复），因此本轮**由主代理直接逐文件读**——用 `Read` 精读关键实现文件、用 `sed/grep` 精确切片，所有计数（会话事件 48、工具目录 62 行、XEYO 工具 26、路由 101、T_now 登记 20）均为当场实测，不采信任何转述。**凡未读到的一律写「未见」。**

---

## 1. Agent 主循环：实现级

### 1.1 dsh `ReactLoopAgent`：显式状态机 + 双层循环

**文件**：`packages/core/agent-loop/src/agent.ts`（589 行）

不同于设计文档里的抽象描述，实现是一个**显式相位状态机**：

```ts
// agent.ts:39-47
type Phase =
  | { kind: 'idle'; lastTurn: number }
  | { kind: 'maintenance'; abort: AbortController; lastTurn: number; wakeRequested: boolean }
  | { kind: 'running'; abort: AbortController; turn: number; step: number; wakeRequested: boolean }
```

**相位迁移**由唯一入口 `setPhase()`（`:116-123`）负责，并顺带发布 `agent/status` 事件——状态可见性不靠散落的 emit。

**外层 `turn()`（`:258-342`）逐语句**：

| 行 | 动作 |
|---|---|
| `:265` | `const turn = phase.turn + 1` |
| `:267` | `session.append('turn/start', { turn })` |
| `:278` | `await this.preStep(target, { turn, step })` —— 一次 pre-step 提议 |
| `:279-282` | `decision.kind === 'reject'` → `turnEnds = { kind: 'blocked' }`，`return false` |
| `:283` | `if (turnEnds && decision.messages.length === 0) break` —— 已定局且无新输入即终结 |
| `:286-289` | `phase.step === 0 && messages.length === 0` → `{ kind: 'completed' }`，**不烧模型调用** |
| `:291` | `session.append('step/start', { turn, step })` |
| `:294-296` | 把 `decision.messages` 逐条 `session.append('user/message', …)` |
| `:299` | `const stepEnd = await this.step(...)` |
| `:302` | **max-tokens 粘滞**：`if (turnEnds === null \|\| turnEnds.kind !== 'max-tokens') turnEnds = stepEnd` |
| `:304` | `finally { session.append('step/end', …) }` |
| `:307-310` | `turnEnds && inbox.nextStep.length === 0` → `await dispatch.serial('agent/turn-stopping', …)` |
| `:311` | 再判一次 `turnEnds && nextStep.length === 0` → `break` |
| `:312` | `target = 'next-step'`（第二轮起从 next-step 取件） |
| `:331` | `finally { session.append('turn/end', { turn, reason: turnEnds }) }` |
| `:336-341` | `if (!inbox.hasPending) return false`；否则**换新 AbortController**、清 `wakeRequested`、`step = 0`、`return true` |

关键实现选择：
- **turn 未真正结束时不会 append `turn/end`**——`turnEnds` 由所有退出路径赋值，`finally` 里用 `turnEnds!` 断言（`oxlint-disable` 注释说明了有界性）。
- **error 的结构化**（`:314-327`）：`signal.aborted` → `{kind:'aborted', reason}`；否则 `error instanceof LlmError` → 保留 `error.failure` 事实，其他一律 `{ message: errorChain(error), code: 'UNKNOWN' }`。
- 每轮 turn 结束后**换新 AbortController**（`:337`），使旧 controller 上的 latch 失效。

**内层 `step()`（`:344-482`）是一个 `while(true)` 重试环**——同一 step 内可因 `agent/request-error` 瀑布返回 `retry` 而重新发起模型调用：

```ts
// agent.ts:425-448（缩略）
const finish = live.finish
if (finish.kind === 'error' || finish.kind === 'aborted') {
  live.settle('assistant/attempt', () => session.append('assistant/attempt', { turn, step, stream: live.stream }).seq)
  const action = await this.dispatch.waterfall('agent/request-error', {
    turn, step, provider: request.provider, failure: finish.failure,
    retryPolicy: preparedCall?.retryPolicy, signal,
  }, () => Promise.resolve<RequestErrorAction>(undefined))
  if (action?.kind !== 'retry') throw new LlmError(finish.failure.message, finish.failure.code, finish.failure)
  continue                            // ← 同 step 重试
}
```

**终止条件全集**（`step()` 返回值）：`{kind:'max-tokens'}`（`:468`）、`{kind:'completed'}`（无 tool call，`:471`）、`null`（有 tool call 且未 conclude，继续同 turn 下一 step，`:476`）。`concluded` 来自工具的 `concludesTurn` 标记（`tool-calls.ts:158`）。

**pre-step 提议链（`:237-255`）**——注意这里有一个**顺序陷阱**，实现是有意为之：

```ts
const claimed = this.inbox.claim(target, position.turn)
const assembly = await this.loopCtx.systemPrompt.assemble(assembleContextFor(this, signal))
signal.throwIfAborted()
const sections = renderContextSections(assembly)
const context = this.runtimeContext.project(joinContextSections(sections), sections)
const decision = await this.dispatch.waterfall('agent/pre-step', { messages: claimed, ...position, signal },
  () => Promise.resolve<PreStepDecision>({
    kind: 'enter',
    messages: context === undefined ? claimed : [...claimed, context],
  }))
```

即：**先 claim（取件）→ 再 assemble（组装 prompt）→ 再投影出 runtime context → 最后走 waterfall**。runtime context 作为**一条追加的 user 消息**进入 `messages`（不是 system）。

### 1.2 dsh 工具调用并发调度器：有界滚动池 + 顺序提交

**文件**：`packages/core/agent-loop/src/tool-calls.ts`（290 行）+ `constants.ts`

```ts
// constants.ts:6
export const DEFAULT_MAX_PARALLEL_TOOL_CALLS = 10
```

`executeToolCalls(ctx, turn, step, toolCalls, signal, acceptContext)`（`:60-102`）的算法：

1. **先全量计划**：把每个 `ToolCallBlock` 转成 `PlannedCall { block, exec }`，其中 `arguments: parseArguments(block.arguments)`；
2. `parseArguments`（`:105-111`）**不抛错**——`raw ? JSON.parse(raw) : {}`，解析失败**原样保留字符串**（`catch { return raw }`），把问题留给工具自身的 schema 校验；
3. `while (next < planned.length)`：**每次重新分类**——`const mode = ctx.tools.executionMode(first.exec).kind`（`:89`）。若是 `parallel`，把**剩余全部**纳入同一 group；若是 `exclusive`，group 只含这一个（barrier）。
4. `runGroup(...)` 返回 `{consumed, aborted, concluded}`；`aborted` 时把**剩余未启动的调用**逐条 `appendSkippedToolCall`，然后 `return`。

**`runGroup`（`:122-247`）的三段式**：

| 段 | 机制 |
|---|---|
| `commitReady()` `:147-161` | 只沿**连续**的模型序槽位推进（`committed` 指针），槽位就绪则 `finalize`（需 post）或 `finish`，`session.append('tool/result', …, { surfaceOp:'append', sourceEventSeqs:[callSeq] })`，并把 `result.additionalContexts` 交给 `acceptContext` |
| `startCall(i)` `:165-197` | 先 `appendToolCall`（拿到 seq 供结果引用）→ `await scheduler.prepare(exec)` → 按 `prepared.kind` 三态：`dispatch`（进 `inFlight`）、`post-result`（直接占槽，仍需 post）、`final-result`（直接占槽，跳过 post） |
| `fillPool()` `:199-214` | `while (!aborted && nextToStart < group.length && inFlight.size < maxParallelToolCalls)`——**启动前重读后续 mode**：`if (nextToStart > 0 && mode === 'parallel' && ctx.tools.executionMode(nextCall.exec).kind !== 'parallel') break`，即**运行期注册表变化可以随时插入 barrier** |

**主等待环（`:219-236`）**用 `Promise.race(inFlight.values())` 收割，每收一个就 `delete` → `commitReady()` → `fillPool()`：

```ts
await fillPool()
while (inFlight.size > 0) {
  const settledIndex = await Promise.race(inFlight.values())
  inFlight.delete(settledIndex)
  throwSchedulerFailure()
  await commitReady()
  throwSchedulerFailure()
  if (signal.aborted) aborted = true
  await fillPool()
}
```

**abort 语义（`:238-243`）**：

```ts
if (aborted) {
  for (const call of group.slice(started)) appendSkippedToolCall(session, turn, step, call.block)
  return { consumed: group.length, aborted: true, concluded }
}
```

`splice` 掉的调用拿到**合成错误结果**（`:250-260`）：

```ts
content: [{ type: 'text', text: 'Error: tool call aborted before dispatch' }],
isError: true,
error: { message: 'tool call aborted before dispatch', info: { name: 'AbortError', code: TOOL_ABORTED_BEFORE_DISPATCH } },
```

注释（`:7-11`）说明了这个设计的复现动机：**「Abort records synthetic error results for skipped calls so replay stays valid.」** 而**调度器自身失败**（非 abort）刻意不合成结果：`await Promise.allSettled(inFlight.values()); throw schedulerFailure.error`（`:232-236`）——`tool/call` 已落盘就保留，不编造结果。

### 1.3 dsh 流式累积：一次快照三处消费

**文件**：`packages/core/agent-loop/src/assistant-stream.ts`（140 行）

`AssistantStreamAttempt` 同时持有两个累积器，`push()`（`:60-71`）对每个 chunk **只取一次时间戳**，然后喂三处：

```ts
push(chunk: StreamChunk): void {
  const timed = this.accumulator.push({ time: Date.now(), chunk })   // ① durable 压缩流
  this.assembler.push(timed.chunk)                                    // ② 组装成 blocks
  this.emit({ type: 'chunk', attemptId, revision: this.nextRevision(), index: this.index++, time: timed.time, chunk: timed.chunk })  // ③ 实时帧
}
```

- **durable**：`accumulator.snapshot()`（`:112-114`）就是最终写入 `assistant/message.stream` 的「紧凑原始流」——`agent.ts:465` 把 `stream: live.stream` 一起落事件，**模型输出与其原始流一同持久化**（这是「每字重建模型当时看到什么」的实现基础）。
- **组装**：`assembler.blocks()`（正常）、`interruptedBlocks()`（中断时的可见前缀，`:122-124`）、`usage`、`finish`、`replayState` 全部从 assembler 取。
- **实时**：帧带 `revision` 自增计数（由 agent 的 `assistantStreamRevision` 提供，`agent.ts:367`），`settle()` 在**durable append 成功之后**才发 `end` 帧（`:78-97`），append 抛错则 `abandon()`（发 `{kind:'abandoned'}`）再抛。

**中断时的持久化分叉（`agent.ts:383-424`）**：

```ts
if (signal.aborted) {
  const content = live.interruptedBlocks()
  if (content.length > 0) live.settle('assistant/message', () => session.append('assistant/message', { … content, interrupted: true, usage, stream }, …).seq)
  else                   live.settle('assistant/attempt', () => session.append('assistant/attempt', { turn, step, stream: live.stream }).seq)
}
```

即有可见内容 → `assistant/message` + `interrupted: true`；零内容 → `assistant/attempt`（log-only，不进投影）。二次失败包成 `AggregateError`（`:416-422`），不吞。

### 1.4 XEYO `query_loop`：单 generator + 循环内联阶段

**文件**：`python/engine/query_loop.py`（2000 行）

```python
async def query_loop(*, store: MessageStore, model: ModelClient, tools: ToolRegistry,
                     prompt: PromptAssembler, system_prompt: str, abort: AbortController,
                     budget: BudgetTracker, working: WorkingSnapshot | None = None,
                     coordinator: PermissionCoordinator | None = None,
                     system_breakdown: list[dict] | None = None, agent_mode: str = "agent",
                     multi_agent: bool = False, include_memory_index: bool = True,
                     ensure_before: Any | None = None) -> AsyncIterator[EngineEvent]:
```

**无状态机、无相位枚举**——状态是函数体内的局部变量。主 `while True:` 在 `:796`，循环头部两个门：

```python
while True:
    if abort.aborted:
        yield StoppedEvent(reason="aborted"); return
    if not budget.prepare_next_turn():
        ...   # 预算门 → StoppedEvent(reason="budget"/"budget_usd")
```

**循环内建的守卫对象（每个 submit 新建 = 用户输入级重置）**：

| 对象 | 行 | 作用 |
|---|---|---|
| `RepeatCallGuard()` | `:766` | 同签名重复调用，阈值 `[3,5,8]` 递进提醒，**只提醒不拒执行** |
| `IdenticalResultFold()` | `:769` | 同签名·同输出**字节级折叠**为一行 `[fold]` 事实写回 store |
| `LoopLedger(exempt_tools=EXEMPT_TOOLS)` | `:772` | 行为账本：s1 结果等价 / s2 内容已见 / s3 首句重复 |
| `ZeroHitTracker()` | `:774` | 不同查询累计空结果 ≥2 → 追加中立提示 |
| `forced_wrap_up` / `wrap_quota_left` | `:783-784` | 硬停前一次性收尾放行；配额默认 3（`XEYO_WRAP_QUOTA` 覆盖，`0` = 全禁） |

**终止/中断实现**：
- 中断靠 `abort.aborted` 轮首+轮中检查，产出 `StoppedEvent(reason="aborted")`；`StoppedEvent.interrupted: bool`（`events.py:104`）用于标注「已有部分输出」；
- `_persist_interrupted_anchor(...)`（`:311`）在中断时把已有输出锚进 transcript；
- 配对修复 `_repair_unpaired_tool_calls(store, "aborted")`（`:218-243`）**只在 submit 入口做一次**，注释明确「不在每轮模型请求前全量扫 store」；
- `_fill_missing_tool_results(store, tool_uses, reason)`（`:244-247`）为缺失结果补占位。

**重试实现（与 dsh 的 waterfall 完全不同形态）**：`_llm_max_attempts()`（`:263`）`max(1, min(n, 5))`，`_llm_retry_delay_ms(attempt, retry_after_ms)`（`:273-281`）计算退避，`_audit_llm_failure(...)`（`:292`）落审计；事件 `llm_retry` / `llm_retry_started`（`events.py:287-310`）明确标注**「非 surface 事件 / 不进 transcript」**。

**并发**：多个 tool_use 的调度在 `:1743-1798` 一段。XEYO **没有 dsh 式的并发池抽象**——是内联的 `while pending:` 循环 + `_eligible_for_early()`（`:155`）判断只读工具可否提前执行，配 `_cancel_early_tasks()`（`:179`）。`early_readonly_tools_enabled()`（`:112`）读环境开关。

### 1.5 主循环实现级对照

| 实现维度 | dsh | XEYO |
|---|---|---|
| 结构 | `Phase` 显式状态机 + `turn()`/`step()` 双方法 | 单 `query_loop` generator + 局部变量 |
| 状态存放 | 类字段（`phase`、`requestHeaderLogged`、`requestSurfaceGeneration`、`assistantStreamRevision`） | 函数局部（每 submit 重建） |
| step 重试 | `step()` 内 `while(true)` + `agent/request-error` waterfall 决定 `retry` | 内联退避 `_llm_retry_delay_ms` + 事件外发 |
| 并发调度 | `executeToolCalls` 有界池（10）+ `exclusive` barrier + `Promise.race` 顺序提交 | 内联 `while pending`；只读工具可早跑 |
| 注册表变更能否插 barrier | **能**（`fillPool` 每次重读 `executionMode`） | 无此概念 |
| 中断的落盘 | 已启动 → 提交；未启动 → **合成错误结果**（保 replay 有效） | 补占位 + `interrupted` 锚 |
| max-tokens | `TurnEndReason['max-tokens']` **粘滞**（后续 step 不降级） | `StoppedEvent(reason=...)` 单值 |
| 模型原始流 | **完整持久化**（`assistant/message.stream`） | 不落原始流（落组装后 transcript） |

---

## 2. 会话数据模型：实现级

### 2.1 dsh：48 个会话事件（实测）

**基线**：`packages/core/session/src/types.ts` 的 `SessionEventMap` 是 12 个核心事件；全仓另有 **26 个插件通过 `declare module` 合并**补入 36 个事件。实测**去重后 48 个**（`grep` 全量枚举，非估计）：

```
agent-preset/selected  approval/asked  approval/decided  approval/policy
assistant/attempt  assistant/message  command/done  command/run
compaction/end  compaction/prune  compaction/start  compaction/summary
feedback/record  goal/change  hook/invoked  hook/result
llm/retry  llm/retry-started  model/selection  permission/preset
plan/mode  request/context  request/header  sandbox/mode
schedule/change  session-log-deepseek/delivery-accepted  session/end-seed
session/title  session/title-llm-request  step/end  step/start
subagent/descriptor  subagent/model-selection-policy  team/member  team/task
todo/write  tool-workflow/agent-end  tool-workflow/agent-start
tool-workflow/run-end  tool-workflow/run-start  tool/call
tool/code-dispatch  tool/code-dispatch-start  tool/result
turn/end  turn/start  user/message  web/deepseek-search-llm-request
```

**核心 12 事件的 payload 逐字段**（`types.ts:260-376`）与 model-visible 判定：

| 事件 | payload 字段 | 何时发 | 进投影 | 可跳过 |
|---|---|---|---|---|
| `turn/start` | `turn` | `agent.ts:267` | ✗ | — |
| `turn/end` | `turn`, `reason: TurnEndReason` | `:331`（finally） | ✗ | — |
| `step/start` | `turn`, `step` | `:291` | ✗ | — |
| `step/end` | `turn`, `step` | `:304`（finally） | ✗ | — |
| `user/message` | `UserMessage`（含 `source`） | `:295` | **✓** | — |
| `assistant/message` | `turn, step, message, stream, usage?, interrupted?` | `:460`/`:389` | **✓** | — |
| `assistant/attempt` | `turn, step, stream` | `:407/413/430` | ✗（log-only） | — |
| `tool/call` | `turn, step, callId, name, arguments`（**原始未解析 JSON 串**） | `tool-calls.ts:264` | ✗ | — |
| `tool/result` | `turn, step, message, error?, meta?` | `tool-calls.ts:282` | **✓** | — |
| `request/header` | `header: EpochHeader`, `reason`, `startsSeries?` | `agent.ts:552/555/561` | ✗ | — |
| `request/context` | `provider, model, contextWindow?` | `:575` | ✗ | — |
| `session/end-seed` | `inherited?: true` | 仅 `Session` 构造器 | ✗ | — |

**四个机制细节**（都是实现级的、设计文档看不到的）：

1. **`ignorable` 保守默认**（`:456-465`）：事件信封有一个可选 `ignorable?: true`；**缺省意味着必需**——读到不认识的 `type` 且无此标记时，**读者必须拒绝重建**而不是静默跳过。注释："defaulting to required means a forgotten marker over-refuses (an inconvenience) rather than silently resuming a gutted session."

2. **`SessionSeq` 是 brand + 运行期校验**（`:36-41`）：非安全非负整数或 `-0` 一律 `TypeError`。

3. **`surfaceOp` 由类型系统强制**（`:466-475`）：只有 `user/message` / `assistant/message` / `tool/result`（`SurfaceEventType`）能带 `surfaceOp` 与 `sourceEventSeqs`；且 **v2 的 `assistant/message` 用 `sourceEventSeqs?: never` 硬禁**（`:426-432`）——因为它内嵌 provider stream，引用来源在语义上冲突。

4. **`SurfaceOp.replace`**（`:416-418`）：`{op:'replace', start, end}`，两端**必须都是既有 surface 节点**，且新节点的 `sourceEventSeqs` **必须包含被遮蔽的每一个节点**——这是压缩能安全改写的全部约束。

**`SESSION_FORMAT_VERSION = 2`**（`:86`）的升级判据写在注释里（`:64-85`），是一段罕见的、可直接执行的工程规则：

> bump 的判据是 **WRITER 发出什么**，不是新读者能接受什么。「parses without error」不算正确性——静默跳过影响重建的内容就是错误读。只有**结构变更**够格：header 形状、`SessionEvent` 信封、核心事件语义、或 surface 机制（`SurfaceEventType` 集合与 `SurfaceOp` 变体）。**新增普通事件类型不 bump**，由每事件的 `ignorable` 守卫覆盖词汇增长。拿不准就 bump。

**Header 中的持久化状态**（`:91-128`）：`version, id, createdAt, cwd?, parentSession?, isSeeded, origin?: 'subagent', delegationDepth?, agentPreset?`。其中 `delegationDepth` 与 `agentPreset` 的注释都给出了「为什么必须持久化」——**递归预算要跨重启存活**、**preset 决定工具与提示，恢复错组合会让模型面对已无法作用的历史**。

### 2.2 XEYO：19 个引擎事件（实测）+ 20 个 dataclass

**文件**：`python/msgtypes/events.py`（333 行）

**实测**：文件里定义 **20 个 dataclass**，但 `EngineEvent` 联合只列 **19 个**——`PermissionExpiringEvent`（`:195-202`，`type="permission_expiring"`，默认提前 30s）**定义了但未进联合**（这是本轮实测到的实现级事实；第二轮写「20 个 dataclass / 19 个联合成员」与此一致）。

| 事件 | 关键字段 | 是否进 transcript |
|---|---|---|
| `AssistantDelta` | `text` | ✗（流式） |
| `ReasoningDelta` | `text` | ✗（流式） |
| `ToolCallEvent` | `name, input, tool_use_id, input_summary, parallel` | ✓ |
| `ToolProgressEvent` | `name, tool_use_id, message, elapsed_ms, xy?` | ✗（明示「不写 transcript」） |
| `ToolResultEvent` | `name, output, is_error, tool_use_id, todos?, operation_id?, ui?, duration_ms, spilled` | ✓ |
| `FinalEvent` | `text, prompt_tokens, completion_tokens, cache_hit/miss_tokens, usd, used_usd, usd_limit` | ✓ |
| `StoppedEvent` | `reason: max_turns\|max_tool_calling\|aborted\|budget\|budget_usd\|wall`, `budget_used_usd?`, `budget_limit_usd?`, `interrupted` | ✓ |
| `UsageEvent` | 12 个计数字段 + `cost_source` + `context_tokens/limit` + `context_breakdown` + `compact_cursor` + `c2_summary_chars` | ✗ |
| `ContextCompressionEvent` | `phase: start\|complete`, `source: automatic\|manual`, `context_tokens/limit` | ✗ |
| `ResultEvent` | `subtype`（7 值）, `result`, `is_error`, `duration_ms`, `num_turns`, `session_id`, `stop_reason`, budget 字段 | ✗ |
| `PermissionPendingEvent` | `request_id, tool_name, tool_input, reason, prompt, path?, expires_at?, choices, peer_summary, intent` | ✗（挂起信号） |
| `PermissionResolvedEvent` | `request_id, approved, actor, reason, resolved_at?, choice` | ✗ |
| `AskUserPendingEvent` | `request_id, session_id, turn_id, question, options, default?, expires_at?` | ✗ |
| `AskUserResolvedEvent` | `request_id, answer, actor, timeout, resolved_at?` | ✗ |
| `PlanPendingEvent` | `request_id, session_id, turn_id, plan, expires_at?` | ✗ |
| `PlanResolvedEvent` | `request_id, approved, actor, reason, resolved_at?` | ✗ |
| `TaskStateEvent` | `session_id, turn_id, task_status, current_tool?, interruptible, error?` | ✗ |
| `LlmRetryEvent` | `attempt, next_retry_ms, code, message, provider, model` | ✗（注释：非 surface） |
| `LlmRetryStartedEvent` | `attempt, provider, model` | ✗ |

**实现级对照**：

| 维度 | dsh | XEYO |
|---|---|---|
| 事件数 | **48**（12 核心 + 36 插件合并） | **19**（联合成员）/ 20 dataclass |
| 扩展机制 | `declare module` 类型合并（编译期，可被第三方包扩展） | 无（单一文件里的 `Union`，加事件要改这个文件） |
| 事件信封 | 统一 `{type, seq, time, data, ignorable?, surfaceOp?, sourceEventSeqs?}` | **无信封**：dataclass 各自为政，流式事件与落盘事件混在一个联合里 |
| 序号 | `seq` 单调、连续（注释明确要求） | 无 |
| 未知事件处理 | `ignorable` 保守拒绝 | 无概念（Python 反序列化即忽略未知字段） |
| 模型原始流 | 每 step 落 `assistant/message.stream` | 不落 |
| 版本化 | `SESSION_FORMAT_VERSION=2` + `ignorable` 双保险 | 无日志格式版本号 |

---

## 3. 上下文投影与 KV 前缀保护：实现级

### 3.1 dsh：请求从日志整体重建，header 快照化

dsh 的投影不是一个「transform 函数」，而是**每 step 从头重建整个请求**（`agent.ts:353-362`）：

```ts
const { request, preparedCall } = await this.buildRequest(
  turn, step, assembly.tools, system, this.session.deriveMessages(),
  startsRequestSeries, surfaceGeneration, signal,
)
```

`buildRequest`（`:488-588`）的实现顺序值得逐步列出：

| 行 | 动作 |
|---|---|
| `:502-510` | 读 `session.requestHeader()` 得到**上次持久化的完整 header**；只恢复「本 loop 实例声明的 route」且未被 adapter 标记为默认的 `reasoningEffort` |
| `:512-521` | `seedConfig = deepFreeze(structuredClone(requestHeaderLogged ? requestProposal(persistedHeader) : {...route, reasoningEffort?, maxTokens?}))` —— **首次用 route，之后用「上一次 proposal」**（`requestProposal()` `:61-67` 先剥掉 adapter 派生字段） |
| `:522-526` | `dispatch.waterfall('agent/request', …, () => seedConfig)` —— 插件可在此改配置 |
| `:533-539` | `llm.prepareCall(proposedConfig, signal)`；`NO_ADAPTER` 时**容忍**（middleware 可能服务未注册路由），其余错误抛出 |
| `:542-547` | `canonicalHeader({ config, adapterDefaults?, system?, tools? })` —— **header = 配置 + 系统提示 + 工具 schema** |
| `:551-562` | 落 `request/header` 的四种 reason |
| `:565-576` | route/capacity 变化才落 `request/context` |
| `:579-586` | `markAgentLoopRequest(deepFreeze({...header.config, messages: boundaryMessages, system?, tools?, sessionId, signal}))` |

**「模型当时看到什么」的完整重建链**：`request/header`（system + tools + config）+ `deriveMessages()`（消息）+ `request/context`（窗口容量）。这就是为什么 `request/header` 的注释说它是 **log-only，最新快照即可重建**（`types.ts:338-347`）。

**四种 reason 的精确判据**（`agent.ts:549-562`）：

```ts
const startsSeries = startsRequestSeries || this.requestSurfaceGeneration !== surfaceGeneration
if (!this.requestHeaderLogged)                                        → reason: baseline === undefined ? 'initial' : 'resume'
else if (baseline === undefined || !headerEquals(baseline, header))   → reason: 'change'（且 startsSeries 时带 startsSeries:true）
else if (startsSeries)                                                → reason: 'series'
```

`requestSurfaceGeneration` 是 `session.surface.replaceGeneration`——**surface 被替换（压缩）会强制开新 series**，这是压缩后 KV 前缀必然失效的显式承认。

**KV 缓存的实际保障方式（与第二轮更正一致，此处给实现证据）**：
- dsh **没有**「工具面会话内冻结」的 memo。`systemPrompt.assemble()` 每次 `pre-step` 调一次（`agent.ts:242`），工具 provider 每次被重新求值（`system-prompt/src/index.ts:562-572`），`orderTools` 每次重排（`:598`）。工具面变化 → `header` 不等 → 落 `request/header reason:'change'` **并开新 series**——即**用日志如实记录前缀断裂，而不是阻止断裂**。
- 真正的缓存声明在 provider 层：`llm-pi-ai/catalog.ts:233` 的 `cacheControlFormat:'offer'`（第二轮已核实）。

### 3.2 XEYO：显式 transform + 尾部追加

XEYO 的投影是「把 store 里的消息转成模型可发格式」的**显式函数**（`project_for_model` 一族，在 `prompt/` 与 `engine/` 内），与 dsh 的区别在于：

- **消息为单位**，不是事件为单位；
- **T_now 块一律尾插**，且 env_channel 档用「**仅存在于投影**」的伪造 tool 对（见 §6），保证**前缀逐字节不动**；
- **MEMORY.md 索引不在左段**（`system_prompt.py:6` 注释：「mutation 会弄废整段 KV 前缀」），改由 runtime 追加到投影 T_now 尾部；
- 左段刻意**不含 Date / Model / 工具名清单**（`system_prompt.py:46-49`）：「Date / Model 都不进左段：避免换日/换模型打爆 KV」。

**实现级对照**：

| 维度 | dsh | XEYO |
|---|---|---|
| 投影输入 | **事件序列**（48 类） | **消息序列** |
| 投影位置 | `Session.deriveMessages()`（每 step 调一次） | `project_for_model`（显式调用点） |
| 系统提示/工具变化 | 接受断裂 → 落 `request/header reason:'change'` + 新 series | 左段锁死三件套，**只 append 不替换** |
| 易变内容 | 走 `systemPrompt.context()` 动态 context，渲染成**一条 user 消息**尾插（`renderContextSections`/`joinContextSections`，`system-prompt/src/index.ts:287-306`） | 走 T_now 管线，env_channel 伪造 tool 对尾插 |
| 前缀断裂 | 有日志证据（header 事件） | 设计上避免；引擎自己保证尾部追加 |
| 压缩 | `surfaceOp:'replace'` 显式改 surface + `sourceEventSeqs` 举证 | C0/C1/C2 三档 + `compact_cursor` |

**一个有意思的实现级巧合**：dsh 的动态 context 也是「渲染成一条 user 消息」（`renderContextSnapshot` 产出 `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.` 的正文，`system-prompt/src/index.ts:290`），也是尾插——但它**不伪装成工具结果**，而是真的 user 角色；XEYO 的 env_channel 恰恰是为了**脱离 user 角色**才发明伪造 tool 对（`t_now_strategy.py:5-12` 的 L2 事故注记）。

---

## 4. 压缩与预算：实现级

### 4.1 dsh：compaction 是 seam，触发是纯算术

**文件**：`packages/compaction/compaction-basic/src/config.ts`

```ts
// config.ts:144-152
const thresholdTokens = Math.floor(contextWindow * policy.thresholdRatio)
const retainTokens = policy.retainRatio !== undefined ? Math.floor(contextWindow * policy.retainRatio) : …
if (retainTokens >= thresholdTokens) {
  throw new Error(`… retain tokens (${retainTokens}) must be less than threshold tokens ${thresholdTokens}`)
}
```

- 触发阈值 = `contextWindow × thresholdRatio`（floor），保留目标 = `contextWindow × retainRatio`（floor），**保留必须小于阈值**（否则配置直接抛错）。
- `contextWindow <= 0` 或非整数 → 抛错（`:138-141`）。
- 配置键校验白名单 `'thresholdRatio'`（`config.ts:27`）——`KNOWN_KEYS` 之外的键会被诊断（`UnknownConfig` warning 可抑制）。
- 压缩产物是 `compaction/start` … `compaction/summary` … `compaction/end` 三段事件 + `compaction/prune`（4 个事件名，实测），UI 可据此渲染折叠卡片；surface 改写走 `SurfaceOp.replace`。
- 另有 `command-compact` 提供手动触发命令，`active` 集合防重入（`command-compact/src/index.ts:87-93`）。

### 4.2 XEYO：C0/C1/C2 三档 + 预算门 + 收尾窗

**实测结构**：`engine/compact.py` 实现三档；`engine/budget.py` 的 `BudgetTracker` 提供 `prepare_next_turn()` 门（`query_loop.py:800` 处），返回 `False` 即产 `StoppedEvent(reason="budget"|"budget_usd")`。

`UsageEvent` 里的 `compact_cursor: int` 与 `c2_summary_chars: int`（`events.py:132-134`）是**压缩状态随用量事件外发**的实现证据——前端据此画压缩后的用量条。`ContextCompressionEvent(phase, source, context_tokens, context_limit)`（`events.py:139-146`）是**压缩生命周期事件**，`source` 区分 `automatic`/`manual`——即 XEYO 把「压缩开始/结束」做成了对外可见事件，dsh 则做成三类日志事件。

**预算相关常量（实测，来自 `query_loop.py`）**：

| 名称 | 值 | 位置 |
|---|---|---|
| 收尾配额默认 | 3（`XEYO_WRAP_QUOTA` 覆盖，`0` = 维持全禁语义） | `wrap_quota_from_env()` `:118-129` |
| `_LLM_MAX_ATTEMPTS` 上限 | `max(1, min(n, 5))` | `_llm_max_attempts()` `:263` |
| 重复提醒阈值 | `[3, 5, 8]` | `:765` 注释 |
| 零命中提示门槛 | 累计空结果 ≥2 | `:773` 注释 |

**实现级对照**：

| 维度 | dsh | XEYO |
|---|---|---|
| 触发判据 | `floor(contextWindow × thresholdRatio)` 纯算术，可配 | 三档 C0/C1/C2（确定性规则），见 `engine/compact.py` |
| 配置校验 | `retain < threshold` 否则抛错；未知键诊断 | 档位为代码常量 |
| 压缩对历史的作用 | 显式 `SurfaceOp.replace` + `sourceEventSeqs` 举证 | 游标（`compact_cursor`）推进 |
| 对外可见性 | `compaction/start|summary|prune|end` 四事件 | `ContextCompressionEvent(start|complete)` + UsageEvent 里的 `compact_cursor`/`c2_summary_chars` |
| 预算 | 无「预算」概念（只有 contextWindow） | `BudgetTracker` 门 + `budget_mirror` / `runtime_budget` T_now 块 + 收尾窗配额 |

---

## 5. System Prompt 组装：实现级

### 5.1 dsh：段注册表 + 中央序号表 + 严格插值

**文件**：`packages/core/system-prompt/src/index.ts`（614 行）

**段位置由一张中央常量表独占**（`:121-152`），实测 **33 个具名槽位**：

```ts
const SECTION_ORDERS = {
  HARNESS_IDENTITY: -1000, HARNESS_SOURCE: -900, WEB_SURFACE: -800,
  DEPLOYMENT_PERSONA: 0, PLAN_POLICY: 500, TEAM_POLICY: 600, PTC_ONLY: 800,
  FILE_REFERENCE: 900,
  TOOL_BASH: 1000, TOOL_PWSH: 1010, TOOL_READ: 1100, TOOL_WRITE: 1200,
  TOOL_EDIT: 1300, TOOL_GLOB: 1400, TOOL_GREP: 1500, TOOL_JOBS: 1600,
  TOOL_PTY: 1700, TOOL_WEB_SEARCH: 2000, TOOL_WEB_FETCH: 2100, TOOL_LSP: 2200,
  TOOL_SESSION_QUERY: 2300, TOOL_GOAL: 2400, TOOL_CORDIS: 2500,
  TOOL_WORKFLOW: 2600, TOOL_RALPH: 2700, TOOL_SUBAGENT: 2800,
  TOOL_REPORT: 2900, TOOLS_SDK: 5000, DELIVERABLE_FILE_REFERENCES: 9000,
  STRUCTURED_OUTPUT: 9900,
} as const
const CONTEXT_ORDERS = { SANDBOX_POLICY: 110, APPROVAL_POLICY: 115, SUBAGENT_DELEGATION: 120 } as const
```

**排序规则**（`:227-229`）：`a.order - b.order || compareNames(a.name, b.name)`——**同序号按名字（code-unit 序，locale 无关）**，保证跨机器一致。

**变量插值是严格的、会抛错的**（`interpolate()` `:309-346`）：
- 名字必须匹配 `/^[a-z][a-z0-9_]*$/`（`:175`），否则**抛错**；
- 未注册的名字抛错，且**用 `Object.hasOwn` 防 `Object.prototype` 穿透**（`:334` 注释「Do not resolve unregistered names through Object.prototype」）；
- 已注册但值为 `undefined` → **抛错**（不是空串）；
- 单个 `{{` 后面没有 `}}` → 当**字面散文**保留（`:320-326`）；
- 替换进去的值**不再二次扫描**（`:258`）。

**`complete` 段机制**（`:67-73`, `:574-586`）：标了 `complete: true` 的段会**作为唯一 system 段生效**，但 assembly 仍跑完 waterfall（让工具/上下文/变量能解析）；**两个 complete 段同时生效 → assembly 失败并列出名字**。

**工具排序**（`orderTools()` `:205-219`）：
- 工具名 `'<unlisted-tools>'`（`TOOL_ORDER_REST` `:181`）是保留字，工具 provider 返回它就抛错（`:206-209`）；
- 未配置 `toolOrder` → 按名字字典序（`:210`）；
- 配置了 → **未知名字抛错并列出全部已知名**（`:211-214`），未列出的按序插到 rest 位置；
- validation 用**限制前的名字全集**（`knownNames`，`:569-572`），因为 provider 可能报出在本 scope 被隐藏的工具名。

**动态 context 渲染**（`:287-306`）：

```ts
export function joinContextSections(sections: readonly ContextSnapshotSection[]): string {
  const body = sections.map(section => section.text).join('\n\n')
  if (body.length === 0) return ''
  return `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n${body}`
}
```

**「supersedes」是关键词**——每次全量重发一份快照，靠这句话声明旧快照作废。`renderContextSections` 同时保留**具名分片**供 UI 归因（`:293-301`）。

**分层与作用域**：`ScopedLayers`（`:398-401`）——global 层 + 按 scope 链；**离得最近的 scope 覆盖同名**（变量 `:546-551`，段与 context 走 `this.layers.merge(scope, …)` `:553-554`）。每次注册/注销发 `system-prompt/change`（`:400`）。

**默认装配**（构造器 `:404-422`）：`harness:identity` 段（`includeHarnessIdentity` 默认 true，文本 `"You are an AI agent powered by DeepSeek Harness."`）+ `PERSONA_SECTION = 'deployment:persona'`（order 0，可由 preset 同名覆盖）。`includeRuntimeContext` 默认 true，关闭走 `suppressRuntimeContext()`。

### 5.2 XEYO：左段锁死三件套

**文件**：`python/prompt/system_prompt.py`（217 行）

```python
IDENTITY = "你是 XEYO，桌面与微信场景下的编程助手。"

def get_default_system_prompt_parts(*, cwd, model, tool_names, date_iso=None) -> list[str]:
    if side_mode():
        return [IDENTITY, FENCE_POLICY]
    return [IDENTITY, f"CWD: {cwd}", FENCE_POLICY]
```

- **左段就这三段**；`model` / `date_iso` / `tool_names` 收了参数但**显式 `_ = tool_names, model, date_iso` 丢弃**（`:55`），注释给出原因：避免换日/换模型打爆 KV；工具名以 API `tools` schemas 为准。
- `custom_system_prompt` / `append_system_prompt` **只允许 append**；合并时**先剥掉可能误拼的重复身份句**（`:182-183`），且相同内容只留一次（`:184-185`）。
- 组装时把段分类成 `identity_env = defaults[:2]` + `rest`（`:146-147`），**XEYO.md instructions 插在两者之间**（`:163-164`），并给 breakdown 打 `soft_over` 标记（`:166-173`）。
- `assemble_system_prompt_parts` 返回 `(text, breakdown)`，breakdown 里每段带 `{category, label, chars}`——**为用量条的分类统计服务**（`:155`）。

**实现级对照表**：

| 实现维度 | dsh | XEYO |
|---|---|---|
| 段注册 | `systemPrompt.section({name, order, text, complete?})`，注册即发 change 事件 | 硬编码三段，无注册 API |
| 顺序 | 中央 33 槽位表 + 同序按名 | 数组字面顺序 |
| 段内容 | `string \| (ctx) => string`（每次 assembly 求值） | `string`（部分段是常量） |
| 变量 | `{{name}}` 严格插值，未注册即抛错 | 无变量系统 |
| 用户规则文件 | 无等价物（靠 `user/message` 注入 + skill） | **XEYO.md 进左段**（`# Instructions (XEYO.md)`），带软预算标记 |
| 动态上下文 | `systemPrompt.context()` 注册，渲染成**一条 user 消息**（带「supersedes」声明） | 走 T_now 管线（见 §6） |
| 工具排序 | 可配置 `toolOrder` + rest 占位，未知名抛错 | 按 schema 数组顺序，无排序配置 |
| 身份句 | `harness:identity` 段，可关 | `IDENTITY` 常量；`Agent` 前缀共用的单一入口 |

---

## 6. T_now 注入管线：实现级（XEYO 独有）

这是 XEYO 最独特的机制，本节写到字节级。

### 6.1 四种策略与优先级

**文件**：`python/prompt/t_now_strategy.py`（133 行）

```python
STRATEGY_ENV_CHANNEL = "env_channel"   # 默认
STRATEGY_LEGACY = "legacy"             # 仅审计对照/显式评测档，不再自动回退
STRATEGY_SKIP = "skip"                 # 内部档：本轮不注入任何块
STRATEGY_PREFILL = "prefill"           # 预留，解析为 env_channel

def t_now_strategy() -> str:            # 显式 ContextVar > 环境变量 XEYO_T_NOW_STRATEGY > env_channel
def resolve_t_now_strategy(provider="", model="") -> str:
    s = t_now_strategy()
    if s == STRATEGY_PREFILL: s = STRATEGY_ENV_CHANNEL
    if s == STRATEGY_ENV_CHANNEL and env_channel_unsupported(env_unsupported_key(provider, model)):
        return STRATEGY_SKIP
    return s
```

**回落判定集合**（`:87`）：

```python
ENV_FALLBACK_STATUS = frozenset({400, 404, 405, 413, 415, 422})
```

注释明确排除 402（欠费）/429（限流）/5xx（瞬时）——「这些与消息结构无关，回退只会掩盖真实原因」。回落目标是 **skip 而不是 legacy**：`skip` 的 docstring 写「宁缺毋滥，不把引擎文本伪装成用户消息」，并声明「执行层硬约束（预算/回合/wrap 门）不依赖提示文本」。

**备忘是进程级的**（`:83` `_env_unsupported: set[str]`）：重启即重新尝试（`:82` 注释）。

### 6.2 伪造 tool 对的字节级构造

**文件**：`python/prompt/turn_context.py:115-155`

```python
def append_env_notice_pair(messages: list[dict], text: str) -> list[dict]:
    t = (text or "").strip()
    if not messages or not t:
        return messages
    from prompt.t_now_strategy import ENV_TOOL_NAME, new_env_tool_call_id
    call_id = new_env_tool_call_id()
    pair = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": ENV_TOOL_NAME, "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": t, "is_error": False}]},
    ]
    return [*messages, *pair]
```

**四个实现级要点**：
1. **内部格式是 Anthropic 形状**（`tool_use` / `tool_result` 块），经 `normalize_messages_for_openai` 转成 OpenAI 的 `assistant(tool_calls)` → `tool` 消息（docstring `:127-129` 明示）；
2. **copy-on-write**：`return [*messages, *pair]`，绝不改入参列表或既有消息对象（`:139` 注释）；
3. **绝不进 MessageStore / JSONL**（`:139`）；
4. 工具名 `xeyo_env_notice`（`t_now_strategy.py:110`）**不注册进 tools 数组**——docstring 解释「OpenAI 兼容厂商不校验历史 tool 名归属」，故 schemas 冻结红线不受影响。

**环境通知头（`:122-125`）**：

```python
ENV_NOTICE_HEADER = (
    "[system-environment]（XEYO 运行环境注入 — background only，非用户消息）\n"
    "以下是引擎注入的状态通知与背景信息。"
)
```

注释（`:118-121`）声明这是理念裁决的产物：**只做定义式来源声明，不写「按其中约束处理」类抬格指令**，且**契约测试断言不含「继续/按其中约束」等行为引导词**。拼装函数 `format_env_notice(blocks)` 用 `\n\n---\n\n` 分隔（`:128-133`）。

### 6.3 20 块登记表 + 三层预算 + 机器执法

**文件**：`python/prompt/pre_llm_inject.py`（1387 行）

**登记表 20 条（实测）**，每条带 `klass` 与 `why`：

| # | 块名 | klass | 登记的「为什么必须在上下文」 |
|---|---|---|---|
| 1 | `continue` | directive | 工具续写轮无此块模型把 tool_result 当终点，不回用户问题 |
| 2 | `mode_instructions` | directive | Ask/Plan/批准计划是本轮行为模式合同，决定能否写盘 |
| 3 | `wrap_up` | directive | 收尾窗引导：配额内可落盘/验证但不得开新探索；缺口清单来自引擎 stat |
| 4 | `runtime_budget` | directive | 预算透明：模型需知剩余额度以决定收敛节奏 |
| 5 | `budget_mirror` | directive | 死线会话每轮稳态预算/时间镜像；正常会话零注入 |
| 6 | `multi_agent_hint` | directive | 多代理分解/汇总的协作合同，缺了会单干或重复汇总 |
| 7 | `repeat_guard` | directive | 轮内防复读提醒（引擎 clear_advice 逐轮重置） |
| 8 | `nested_instructions` | inventory | 子目录规则按需加载；限窗注入，滚出尾窗静默 |
| 9 | `compact` | directive | 输出/写码压缩开关生效的统一行为规则 |
| 10 | `mcp_required_warn` | event | required MCP server 启动失败的可见警告（fail-visible） |
| 11 | `reconcile_events` | event | 工具面/技能目录变更，consume 语义——静默即永久丢失 |
| 12 | `peer_presence` | event | 多会话交叉活动提醒，冲突预防（drain 队列） |
| 13 | `file_conflict` | event | 触碰文件被其他会话写入——静默即丢，覆盖风险 |
| 14 | `browser_preview` | inventory | 用户预览页 URL：读页面正文的必要指针 |
| 15 | `runtime_mode_snapshot` | directive | 审批模式活状态（supersedes）；真门禁在 permissions 层 |
| 16 | `agent_settlement` | event | 子代理结算通知，drain 语义——静默即永久丢失 |
| 17 | `goal` | directive | 仅 blocked/pending_complete 注入：恢复执行/完成确认的锚 |
| 18 | `resume_directive` | event | 续跑富化指令投影-only 送达；落库只存用户真实文本 |
| 19 | `pending_jobs` | directive | job 完成补投：一次性待领信息，模型不读则任务结果不可见 |
| 20 | `skill_preinvoke` | directive | 用户 /name 直呼技能的宿主确定性加载 |

**三层预算常量（实测）**：

```python
T_NOW_TOTAL_BUDGET    = 6_000   # :812  总量（字符）
T_NOW_INVENTORY_MAX   = 2_500   # :813  inventory 类配额
T_NOW_BLOCK_HARD_CAP  = 21      # :826  登记数硬顶（注释：23→21，裁决 5 删两块）
NESTED_MAX_CHARS      = 4_000   # :390  单块上限（nested）
_VAGUE_MAX_CHARS      = 24      # :946  模糊指代判定阈值
```

**20 条登记 vs 硬顶 21** —— 留了 1 格余量；注释要求「加一必须删一；显式调高需在 commit message 给出预算不破的理由」。

**装配点全部经 `_tag_block()`**（`:922-928`）：

```python
def _tag_block(tagged, name, block) -> None:
    """装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。"""
    if name in _skipped_blocks():
        return
    tagged.append(block)
```

`_skipped_blocks()`（`:917-919`）读 `XEYO_T_NOW_SKIP="a,b"` 做**块级消融**，注释警告「event 类（drain 语义）被跳过即永久丢失，消融跑分可接受，生产应急慎用」。

**类感知裁剪算法（完整实现，`:990-1026`）**：

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
    room = max(0, min(inventory_max, total - used))  # inventory 拿剩余额度
    for k, b in inv:
        if room <= 0: break
        if len(b) <= room:
            kept.append((k, b)); room -= len(b)
        elif room >= 64:
            kept.append((k, b[:room].rstrip() + "…")); room = 0
        else:
            break
    return kept
```

三个实现级细节：**directive/event 不裁剪**（构造处各自有界）；**inventory 拿 `min(2500, 总量-已用)`**；**剩余不足 64 字符就整块丢弃**（不做无意义截断）。

**装配顺序（`run_pre_llm_inject` `:1030-1310`，实测 `_tag_block` 调用 20 处）**：continue → mode_instructions → wrap_up → (multi_agent_hint) → repeat_guard → nested_instructions → compact → mcp_required_warn → reconcile_events → peer_presence → file_conflict → browser_preview → runtime_mode_snapshot → agent_settlement → goal → (runtime_budget/budget_mirror) → pending_jobs → skill_preinvoke。

**执法测试（`tests/test_t_now_block_registry.py`）**第一问是「**能不能不进上下文**」，机器执法四件事：登记表与 `# block: <名>` 标记一一对应；**未登记即红**；**登记但不用也红**；**重复标记也红**。

### 6.4 dsh 的对应物：没有 T_now，但有动态 context

dsh **没有**等价于 T_now 的机制——实测 48 个事件里没有「逐轮易变块」这一类。它最接近的东西是 `systemPrompt.context()` 注册的动态 context（§5.1），差异在实现层是三条：

1. **粒度**：dsh 是「每次 assembly 全量重渲染一份快照，正文声明 supersedes」；XEYO 是「20 个独立块，各自有 klass/预算/旁路开关」。
2. **预算**：dsh 无字符预算（靠 section 作者自控）；XEYO 有总 6000 / inventory 2500 / 单块 4000 三层。
3. **准入治理**：dsh 只要注册就能进；XEYO 有登记表 + 硬顶 + 机器执法 + 逐条理由。
4. **声道**：dsh 动态 context 就是真 user 消息；XEYO env_channel 用伪造 tool 对把引擎文本与用户意图在**消息结构上隔离**。

**判断**：这不是「dsh 缺一个功能」，而是**两端对「易变内容该不该进注意力」的答案不同**——dsh 把易变内容当 prompt 的一部分（有注册 API、无准入）；XEYO 把它当**治理对象**（登记、预算、理由、执法、旁路开关）。

---

## 7. 工具系统：实现级

### 7.1 dsh `ToolDefinition`：逐字段

**文件**：`packages/core/tools/src/index.ts`（1937 行）+ `types.ts`

`ToolDefinition` 的字段（从 `:200-280` 与 `schema.ts` 交叉读取，逐项列出）：

| 字段 | 类型 | 语义 |
|---|---|---|
| `name` | string | 模型可见名 |
| `description` | string | 模型可见描述 |
| `parameters` | JSON Schema | **入参 schema（原始 JSON Schema，非 zod 推导）** |
| `execute` | `(args, ctx: ToolRunContext) => Promise<ToolExecutionResult>` | 工具体 |
| `timeoutMs` | number? | per-tool 超时（`guard/timeout-policy` 读它） |
| `isConcurrencySafe` | `(args) => boolean`? | 可否加入并行组（调度器 `executionMode` 用） |
| `presentCall` | `(args) => ToolCallView \| undefined`? | **PENDING 态 UI 呈现**（纯函数，可回放） |
| `presentResult` | `(args, result: ToolResult) => ToolResultView \| undefined`? | **完成态 UI 呈现**（纯函数，可回放） |
| 输出投影 | 由 output 声明 | 产出 `ToolResult.meta`（durable，UI 回放用） |

**`presentCall` / `presentResult` 的注释是实现级金句**（`:262-279`）：

> Pure and side-effect-free: a UI may call it during live streaming AND a session-log replay, so it must depend only on `args`.

——即 dsh 要求 UI 呈现是**历史的纯函数**，这是「日志回放能复原卡片」的实现前提。

**`ToolExecutionResult` 家族**（从 `tool-calls.ts:153-158` 与 `:424-436` 反推 + `types.ts`）：成功态带 `content: ContentBlock[]`、`isError`、可选 `error: {message, info}`、可选 `meta`、可选 `additionalContexts: UserMessage[]`、**`concludesTurn?: boolean`**（唯一能终止 turn 的标记）。

**`ToolImplementation` 的入参跨一个「无损 JSON 物化边界」**（`:365-371` 注释）：parsed arguments 在进 policy 前**物化一次并无损化**，然后 **deep-frozen**；`callId` / caller signal / registry 分配的 `token` 全部 readonly；registry 在 `tools/result` observer 跑之前**冻结整个对象**。

### 7.2 dsh `ToolRuntime`：四阶段可调度接口

```ts
// index.ts:444-453
export interface ToolRuntimeScheduler {
  prepare(exec: ToolExecutionInput): Promise<ScheduledToolPreparation>   // 物化 + 有序 pre-execute/guard 门
  dispatch(exec: ToolRunContext): Promise<ScheduledToolDispatch>          // 仅 around-dispatch/body
  finalize(exec: ToolRunContext, result: ToolExecutionResult): Promise<ToolExecutionResult>  // post-execute + 内容定稿 + 通知
  finish(exec: ToolRunContext, result: ToolExecutionResult): ToolExecutionResult              // 跳过 post-execute
}
```

**`prepare` 的三态返回**（`:424-427`）：

```ts
| { kind: 'dispatch'; exec: ToolRunContext }                                // 正常进 body
| { kind: 'post-result'; exec; result }                                     // 已判结果，但仍要走 post-execute
| { kind: 'final-result'; exec; result }                                    // 已终局，跳过 post-execute
```

**这条三分支是实现级的关键**：**`post-result` vs `final-result` 的区别就是「post-execute 瀑布还能不能改写」**——调度器据此避免无谓的异步等待（`tool-calls.ts:187-192` 直接占槽）。

**扩展点（waterfall）实测**：
- `'tools/pre-execute'`（`:144`）：`(exec, next) => Promise<PreToolDecision>`，**scope-filtered**（带 `this: Scoped<ToolRuntime>`）。
- `'tools/post-execute'`（`:167`）：`(exec, result, next) => Promise<PostToolDecision>`。
- `register(definition)`（`:1028`）：返回 disposer。
- **单调 guard**（`:697`, `:1092` 注释）：在**每次 `tools/pre-execute` 之后**求值——这是「守卫」与「拦截器」的分层实现。
- `executionMode(exec)`（`:1267`）：返回 `{kind:'parallel'|'exclusive'}`。
- `post-execute` 的两个显式不变量（`:1749`, `:1757`）：**「accept 决策不能同时替换 value 与 content」**、**「不能替换已失败结果的值」**——都是 `TypeError` 而非静默。

### 7.3 dsh schema 生成：多语言类型桥

`packages/core/tools/src/` 里有一组**按语言分文件的类型桥**，实测：

| 文件 | 行数 | 作用 |
|---|---|---|
| `json-schema.ts` | 656 | JSON Schema 定义/工具 |
| `schema.ts` | 617 | schema 装配 |
| `py-types.ts` | 818 | **Python 类型桥** |
| `ts-types.ts` | 317 | TS 类型桥 |
| `ptc.ts` | 678 | PTC（程序化工具调用）模式 |
| `presentation.ts` | 389 | 呈现层 |
| `testing.ts` | 42 | 测试辅助 |

`py-types.ts`（818 行）与 `ts-types.ts` 的存在说明：dsh 的 schema 是**给多语言运行时用的类型描述**（PTC 模式下模型写代码调工具，需要在目标语言里有类型声明）。而发给 LLM 的 wire 形状在 `llm/src/types.ts:399-403`：

```ts
export interface ToolSchema { name: string; description: string; parameters: Record<string, unknown> }
```

**接口注释说明了归属**（`:392-397`）：ToolSchema 声明在 `dsh-llm` 而不是 `dsh-tools`，因为它属于 `GenerateOptions`；`ToolDefinition` 与 `PromptAssembly` 都从这里 import。

### 7.4 dsh 工具目录：62 行 / 66 个工具名（实测）

`docs/tool-catalog.md` 是**生成物**（`scripts/gen-tool-catalog.ts`），生成方式本身是实现级细节：

> Unlike the cordis catalog (a pure source-AST pass), this generator **BOOTS each tool plugin on a real context and reads `ctx.tools.schemas()`**, because a tool schema is not statically knowable (runtime-spread enums, concatenated descriptions, config-driven names, raw-JSON-Schema MCP tools). A completeness guard globs `packages/*/tool-*` and **fails if any package is missing** from the generator's boot manifest.

**实测 62 行 / 66 个工具名**（含重名与别名）：

| 分组 | 工具名 |
|---|---|
| 交互 | `ask_user_question`, `exit_plan_mode` |
| 代码运行时 | `run_code` |
| Shell | `bash`, `pwsh`（一次性）+ `bash`/`pwsh`（persistent PTY 版同形） |
| 自修改 | `cordis_define`, `cordis_inspect_list`, `cordis_inspect_query`, `cordis_inspect_self`, `cordis_run`, `cordis_stop`, `cordis_undefine`（**7 个**） |
| 文件 | `edit`, `read`, `read_image`, `write`, `str_replace_editor` |
| 检索 | `glob`, `grep` |
| 终端 | `terminal_close`, `terminal_list`, `terminal_open`, `terminal_read`, `terminal_send`, `terminal_signal`（6 个） |
| 目标 | `create_goal`, `get_goal`, `update_goal` |
| 调度 | `schedule_create`, `schedule_delete`, `schedule_list` |
| LSP | `lsp` |
| 工作流 | `ralph`, `workflow` |
| 技能 | `skill` |
| 会话自查询 | `session_event_read`, `session_event_search`, `session_event_trace`, `session_search`, `session_trace`（**5 个**） |
| 子代理 | `subagent`, `subagent_fork`, `list_subagent_models`, `interrupt_agent`, `list_agents`, `send_message` |
| 作业 | `job_kill`, `job_list`, `job_output` |
| Agent Teams（experimental） | `spawn_teammate`, `team_task_create`, `team_task_get`, `team_task_list`, `team_task_update`, `wait_agent` |
| 待办 | `todo_write` |
| Web | `web_fetch`, `web_search` |

### 7.5 XEYO `ToolMeta`：单表 26 项

**文件**：`python/tools/meta.py`（414 行）。模块 docstring 直接写定位（`:1-4`）：

> 工具元数据单表 — policy / catalog / subagent / schema 短描述的唯一来源。新增工具：在此登记一行，再在 catalog 挂工厂；**勿再手抄 READONLY / 白名单**。

`ToolMeta` 是 frozen dataclass，**14 个字段**：

```python
@dataclass(frozen=True)
class ToolMeta:
    name: str
    read_only: bool
    concurrency_safe: bool
    policy: PolicyKind                                  # 8 值
    subagent_ok: bool = False                           # 可否出现在子 agent 注册表
    subagent_baseline: bool = False                     # 子 agent 默认基线白名单
    needs_write_store: bool = False
    needs_read_state: bool = False
    needs_runtime_provider: bool = False
    repeat_exempt: bool = False
    short_description: str = ""                         # 发给模型的短描述（省 schema token）
    enabled: bool = True                                # False = 仅策略/测试用（如 echo）
    output_budget: int | None = None                    # T1 per-tool 输出预算（字符）
    exposure: Literal["normal", "hidden"] = "normal"     # F2：hidden 不进 schemas 但保留注册
```

`PolicyKind = Literal["always_allow","outbound_ask","ui_ask","read_path","write_path","agent_allow","bash","interactive"]`（`:14-22`）——**8 种策略类型**，是 policy 层分流的唯一键。

**三个实现级注释值得记**：
- `output_budget`：`None` = 默认 16000 字符；`0` = 豁免（自带截断或防读回环，如 Bash 自带 spill、Read 防 read→spill→read）；
- `exposure`：`hidden` = 不进 schemas 但**保留注册**，「模型幻觉调用仍走权限三态，fail-safe」；
- `short_description`：空则保留工具自带全文。

**实测 26 个工具条目**：

| 工具 | policy | 备注 |
|---|---|---|
| `echo` | always_allow | `enabled=False`（仅测试） |
| `getTime` | always_allow | read_only |
| `offload_read` | read_path | **`exposure="hidden"`**（hidden-but-registered） |
| `Glob` / `Grep` / `Read` | read_path | read_only |
| `Write` / `Edit` | write_path | |
| `Bash` | bash | |
| `TodoWrite` | always_allow | |
| `Screenshot` / `SendToWeChat` / `XeyoUI` | ui_ask / outbound_ask | |
| `Memory` | write_path | policy 里特判为 `memory_tool_confined` → ALLOW |
| `AskUserQuestion` | interactive | |
| `JournalQuery` / `Diagnostics` / `Git` / `NotebookEdit` | 读或写 | |
| `Skill` / `Agent` | agent_allow | |
| `WebFetch` / `WebSearch` | outbound_ask | |
| `job_output` / `job_list` / `job_kill` | — | 作业控制三件套（与 dsh 同名） |

### 7.6 加一个工具的 SOP（两端对照）

| 步骤 | dsh | XEYO |
|---|---|---|
| 1 | 新建 `packages/*/tool-<name>/src/index.ts`，`defineTool({name, description, parameters, execute, presentCall?, presentResult?})` | 在 `python/tools/meta.py` 登记一行 `ToolMeta(...)` |
| 2 | 在插件 `apply()` 里 `ctx.tools.register(def)`，用 `ctx.effect` 管 disposer | 在 `python/tools/catalog.py` 挂工厂 |
| 3 | 在 profile 的 `cordis.patch.yml` 或 preset 里挂上插件 | 工具进 `ENABLED_TOOLS`（`enabled=True`/`exposure="normal"`） |
| 4 | 跑 `pnpm run gen-tool-catalog` 重生成文档；**completeness guard 会因缺文档失败** | 跑 `tests/test_t_now_block_registry.py` 无关；但 **`catalog.py` 的 schema 与 `meta.py` 单表一致**由测试保证 |
| 5 | 写 spec；**per-file 100% 覆盖率门** | 写 pytest |
| 守卫 | 完成时 `verify-tool-catalog` 会检查新增 `packages/*/tool-*` 是否都进文档 | 无「新工具必须文档化」的机器门（靠 AGENTS.md 约定） |

---

## 8. 工具执行管线：实现级

### 8.1 dsh：一个 tool call 的完整阶段表

对照 `docs/tool-execution-pipeline.md` 与源码，**逐阶段**：

| # | 阶段 | 实现位置 | 可拦截点 | 失败行为 |
|---|---|---|---|---|
| 1 | 模型输出 → tool_call 解析 | `agent.ts:470`（filter `type==='tool-call'`） | — | 无 tool call → `{kind:'completed'}` |
| 2 | 参数解析 | `tool-calls.ts:105-111` | — | **JSON 失败保原串**，空串 → `{}` |
| 3 | 计划与分组 | `tool-calls.ts:72-100` | — | — |
| 4 | 分类 mode | `ctx.tools.executionMode(exec)` `:89`, `:205` | — | 运行期可变，可插入 barrier |
| 5 | 落 `tool/call` | `:264` | — | — |
| 6 | **prepare**（物化 + pre-execute + guard） | `TOOL_RUNTIME_SCHEDULER.prepare` `:170` | **`tools/pre-execute` waterfall**（并发 `waterfalls`）+ 单调 guard | 返回三分支；抛错 → schedulerFailure |
| 7 | **dispatch**（around-dispatch + body） | `:174` | **`tools/execute` wrapper**（可替换 signal） | 抛错 → `schedulerFailure`，**不合成结果** |
| 8 | **finalize / finish**（post-execute + 内容定稿） | `:153-154` | **`tools/post-execute` waterfall** | `TypeError` on illegal accept |
| 9 | 落 `tool/result` | `:282-289` | — | — |
| 10 | 附加上下文入下一 step | `:157` `acceptContext` → `inbox.splice('next-step', …)` `agent.ts:474` | — | — |

**四个实现级不变量**（都在代码注释里写死）：

1. **「Dispatch may overlap, while policy, results, and result context remain model-ordered」**（`tool-calls.ts:4-5`）——**并发只发生在 body，policy 与结果顺序严格按模型序**。
2. **prepare 是有序的**（`:216-218` 注释）：「Ordered pre-execute may await; only dispatch/body overlaps.」
3. **abort 时 started 的先结算、unstarted 的补合成结果**，且「returns with the signal still aborted」（`:44-49`）。
4. **调度器失败绝不编造结果**（`:8-10`）：「A terminal scheduler failure preserves already-recorded `tool/call` events without fabricating results.」

**`finalize` 与 `finish` 的分工**在 `:1723-1757` 的实现里可见：`finalize` 跑 `tools/post-execute` 瀑布后做 `finalizeContent`；`finish` 只做后者。

### 8.2 dsh 结果截断：spill 的头尾预算

**文件**：`packages/spill/spill-policy/src/index.ts`

```ts
// :94-98
function headTailPreview(text: string, budget: number): string {
  const headBytes = Math.ceil(budget / 2)
  const tailBytes = Math.floor(budget / 2)
  const retainer = new TextRetainer({ kind: 'headTail', headBytes, tailBytes })
  …
}
```

即：**预算对半分头尾**（head 向上取整、tail 向下取整，奇数预算时头多 1 字节），而不是常见的「保头丢尾」。`spill-local` 提供 `store.ts` / `cleanup.ts`（实际落盘与清理），`spill` 定义 seam（`index.ts` / `types.ts`）。policy 注释（`:6`）说明产出是「bounded head/tail preview plus the backend's …」。

**`fs-tool` 的 `spillStore`**（tool-catalog 里 glob/grep 一行）：**「Capped results save the complete formatted list through the optional `ctx.spillStore` backend; returned locators are follow-up-readable/searchable」**——即截断后给模型的是**可追查的定位符**，不是死文本。

### 8.3 XEYO：内联链 + 路由标记 + 三条旁路

XEYO 的管线是**函数内联链**（第二轮已定性），本轮补实现级细节：

- **结果截断**：`ToolMeta.output_budget` 是 per-tool 字符预算（默认 16000），`0` = 豁免；`ToolResultEvent.spilled: bool` 与 `duration_ms: int`（`events.py:78-79`）是截断与耗时的**对外可见证据**，注释标注为「T13：tool_call.end 元数据」。
- **外部化（L3 offload）**：`offload_read` 工具（`exposure="hidden"`）用于**按行区间读取被外部化的工具结果文件**——与 dsh 的 spill 是同一问题的两种解法：dsh 给「头尾预览 + 定位符」，XEYO 给「截断 + 一个专门的按需读取工具」。
- **Bash 路由标记**：`[routed: Bash …→…]`（AGENTS.md 契约）——纯文件读命令且目标在工作区内时改走专用工具，结果头带一行标记。这是**观测域一致性**的实现：路由本身是执行层动作，标记是给模型的信息。
- **三条旁路**（第二轮已定位，本轮补「绕过什么」）：

| 旁路 | 实现文件 | 绕过 |
|---|---|---|
| `server/workspace_fs.py` 直写 | `python/server/workspace_fs.py` | 权限 / rewind / 审计（默认只读开关关） |
| 后台 bash job | `python/tools/job_tools.py` + 24h 超时 | 主链超时与权限（事实无超时） |
| WriteStore 写路径 | `python/engine/write_store.py` | 统一写通道（`needs_write_store` 是 `ToolMeta` 字段，说明这是**注册时选择**而非统一强制） |

### 8.4 管线实现级对照

| 维度 | dsh | XEYO |
|---|---|---|
| 形态 | **命名事件瀑布**，4 个可拦截点（pre-execute / execute / post-execute / ptc-dispatch-log） | 函数内联链 + **单钩子接缝**（`extension/hooks.py` 的 `PreToolUse`/`PostToolUse`） |
| 第三方拦截 | 是（waterfall 可改 decision/result/content） | 是（hook 可 abort；`PermissionRequest` 非 Success → fail-closed DENY） |
| 并发边界 | **policy 与结果严格模型序，仅 body 重叠**（有上限 10 + barrier） | 内联 `while pending`，只读工具可早跑 |
| 结果顺序 | `commitReady()` 连续指针，**只沿连续槽位推进** | store 追加序 |
| 参数解析失败 | 保原串交给工具 schema | 同（Python dict 解析后交工具） |
| 截断 | head/tail 各半 + spillStore + 可追查定位符 | per-tool `output_budget`（默认 16000）+ spill + `offload_read` 专用工具 |
| 失败语义 | 显式 `isError` + 结构化 `error.info`；abort 合成结果保 replay | `is_error` + 占位补全 |
| 旁路 | 一切经 `ctx.fs` / `ctx.shell` / `ctx.tools`（seam 强制） | **三条旁路各有绕过面** |
| 自我修改工具 | 有（7 个 `cordis_*`） | 无 |

---

## 9. 权限与审批：实现级

### 9.1 dsh：审批是一个 capability seam，不是工具门

**文件**：`packages/interaction/user-approval/src/`（`index.ts` 301 + `invariant.ts` 111 + `types.ts` 91）

**审批策略是二值**（`index.ts:60-63`）：

```ts
export type ApprovalPolicy = 'ask' | 'never'
export const APPROVAL_POLICIES: readonly ApprovalPolicy[] = ['ask', 'never']
```

docstring 把两条语义写得很清楚（`:51-58`）：
- `'ask'`（**默认**）——委托给已组合的 answerer；**没有 answerer 就 fail closed**；
- `'never'`——**不向任何人提问**，每个 ask 直接 `'rejected'`。这是「不用问就能知道结果的策略」。

**结果词汇是封闭的、且只有一个授予值**（`request()` docstring `:191-206`）：

| 情形 | 结果 |
|---|---|
| 正常同意 | `'allowed-once'`（**唯一授予**） |
| signal 被 abort | `'cancelled'` |
| answerer 缺失或抛错 | `'unavailable'`（**fail closed**） |
| answerer 返回词汇外值 | **归一为 `'unavailable'`** |

**审计对必须被 turn 包住**（`:210-216`）：

```ts
if (!hasOpenTurn(session)) {
  throw new Error('approval.request() outside an open turn: the approval/asked + approval/decided audit pair '
    + 'must be turn-enclosed (a bare event between turns is crash-tail garbage on reload). …')
}
```

——`approval/asked` + `approval/decided` 是**成对持久化**的；注释进一步声明「返回未记日志的决定会破坏成对性，所以审计 append 失败也必须 reject」。

**策略可见性的双轨实现（这是本轮最有意思的实现细节之一）**：

1. **`approval/policy` 事件是 log-only**（`:26-33` 注释）：

> The session's approval policy was switched — log-only, durable, replayable, **never in the model transcript** (the model learns the policy …

2. **但策略确实会告诉模型**——通过一条**动态 context**（`:153-167`）：

```ts
// The complete current value travels after retained history, so switching
// policy does not rewrite the stable system-prompt cache prefix.
ctx.inject(['systemPrompt'], (scope) => {
  scope.systemPrompt.context({
    name: 'approval:policy',
    order: scope.systemPrompt.getContextOrder('APPROVAL_POLICY'),   // = 115
    text: (context) => {
      const agent = context.agent
      if (agent === undefined) return ''
      const policy = effective(agent)
      return policy === 'never' ? NEVER_SENTENCE : ASK_SENTENCE
    },
  })
})
```

注释写明了动机：**「完整当前值走在保留历史之后，所以切换策略不会重写稳定的 system-prompt 缓存前缀。」** 即：换策略 → 尾部动态 context 变化，前缀不动。

3. **切换动作本身**通过 `agent.inject()` 发一条 user 消息（`:180-190`）：`'The approval policy changed from "X" to "Y" (changed by the user).'`。

**沙箱升级与审批的耦合**（`packages/sandbox/sandbox/src/escalation.ts:146-175`）——`approveEscalation()` 是一个**严格有序的 fail-closed 序列**：

```ts
// ① 严格放宽检查（执行期检查，非 schema 约束）
if (!(WIDER_MODES[effectiveMode] ?? []).includes(mode)) {
  throw new Error(`sandbox escalation to "${mode}" is not strictly wider than this call's current "${effectiveMode}" mode`)
}
if (approval.approver === undefined) throw new Error(`… requires approval, but no approval service is composed`)
if (approval.agent === undefined)   throw new Error(`… requires approval, but the call has no agent to route it through`)
const outcome = await approval.approver.request({ … })
```

注释明确：**非放宽的请求永远不打扰人类**（"A non-widening request never prompts a human"），而**授权只作用于提出申请的那一次调用**（"the granted mode … consumed by the one call that asked"）。

**权限档位的三旋钮结构**（`packages/interaction/permission-presets/src/index.ts`）：一个 preset 同时写 `sandbox` 与 `approval` 两个值（`PresetSpec { sandbox: SandboxMode; approval: ... }` `:58-61`），当前值由**三个整值 knob 事件**（`permission/preset`、`sandbox/mode`、`approval/policy`）折出 `permissions` 投影（`types.ts:34-43`）；匹配不上任何表项时派生 `custom`（`:321-334`）。

**一个防误配的启动期断言**（`:195-197`）：

```ts
if (ctx.shell.sandboxMode === undefined) {
  throw new Error('permission: the mounted bash executor does not confine (no sandboxMode) — presets bundle a sandbox mode, so composing this plugin over an unconfined executor is a misconfiguration')
}
```

——即**权限预设不允许装在不会沙箱的执行器上**，这是编译期思维搬到运行期。

### 9.2 XEYO：判定函数 + 挂起存储 + grant 指纹

**判定入口两层**（`python/permissions/policy.py`）：

```python
def evaluate_policy(name, tool_input, *, cwd, allowed_paths=None, tool=None) -> PolicyDecision:
    """T10：外层叠加 grant store。ASK 先查 always-allow 授权；DENY 不可被 grant 触碰。"""
    decision = evaluate_policy_impl(name, tool_input, cwd=cwd, allowed_paths=allowed_paths, tool=tool)
    if decision.decision != PermissionDecision.ASK:
        return decision                      # ← DENY/ALLOW 在此终止，grant 永远碰不到
    try:
        from permissions.store import default_grant_store, grant_fingerprint
        from permissions.write_scope import get_write_scope
        if get_write_scope() is not None:  return decision   # worker 沙箱：grant 不得放宽
        if is_remote_session(_session_id()): return decision  # 远程会话不得静默放行（§34 不变量）
        if permission_mode() == "always": return decision     # 用户显式要求逐条确认
        if name.lower() == "bash":
            if bash_command_is_composite(cmd): return decision  # G29：组合命令不得吃前缀 token grant
        fp = grant_fingerprint(name, tool_input, matched_rule=…, mcp_target=…)
        if not fp: return decision
        identity_name = decision.mcp_target.strip() or name
        grant = default_grant_store().match(tool_name=identity_name, fingerprint=fp, scope=cwd or "")
        if grant is None: return decision
        return PolicyDecision(decision=ALLOW, reason="always_allow_grant", matched_rule="grant_store", …)
    except Exception:
        return decision                      # 任何异常 → 回到原 ASK（fail-safe）
```

**四条 grant 豁免**（worker / remote / always / 组合 bash）与**一个异常兜底**，全部有注释锚定事故编号（G29、§34、T10）。

**`evaluate_policy_impl` 的分支顺序（逐分支实测，`:1391-1700`）**：

| 顺序 | 分支 | 结果 |
|---|---|---|
| 1 | `raw_name in pol.deny_tools`（workspace policy 显式禁） | DENY / `policy_deny_tool` |
| 2 | `raw_name.startswith("mcp__")` | → `_evaluate_mcp(...)`（企业 deny 最严胜出 → tool_policies → 未知兜底） |
| 3 | `raw_name == "Mcp"`（网关工具） | → `_evaluate_mcp_gateway(...)`（list/describe 放行；call 解析目标身份后三态） |
| 4 | `in _ALWAYS_ALLOW` | ALLOW / `tool_unrestricted_p0` |
| 5 | `in _OUTBOUND_ASK_TOOLS` | 工作区路径校验（SendToWeChat 缺 path → DENY；路径外 → DENY）→ max 档 ALLOW，否则 ASK |
| 6 | `in _UI_ASK_TOOLS` | → `_evaluate_ui_ask(...)`（`list` 放行；其余按 action 分流） |
| 7 | `== "Agent"` | 默认 ALLOW；`permission_mode()=="always"` → ASK |
| 8 | `== "Bash"` | → `_evaluate_bash(...)` |
| 9 | `in _READ_PATH_TOOLS` | `check_read_permission_for_path` → ALLOW/ASK/DENY（DENY 再细分为 path_outside / secret_path / dangerous_path） |
| 10 | `in _WRITE_PATH_TOOLS` | 依次：Memory 特判 ALLOW → 缺 path DENY → **policy 文件 DENY** → **密钥路径 DENY** → **子 agent write scope DENY** → memdir（Write 还查 schema）→ **受保护元数据 DENY** → 工作区外 DENY（max 档除外）→ 模式合成 → worker scope（无 ASK）→ peer 热文件冲突 → auto_approve / ASK / ALLOW |
| 11 | 未知工具 | **ASK**（`unknown_tool_default_ask`，注释「不再宽松透传」） |

**写路径的「单向性」实现**（`:1628-1644`）值得单独引：

```python
mode = permission_mode()
if mode in _AUTO_WRITE_MODES:            # never/allow = 最高权限，跳过仓库收紧
    pass
elif pol.write in ("ask", "always"):
    mode = "always"                       # 收紧：非最高权限下强制每写确认
elif pol.write in ("never", "allow", "risk"):
    pass                                  # 单向性：不得把用户更严的选择放宽
```

注释点明事故来源：「仓库默认 write=ask 收紧若在此处反向 override 成 always（每写必问），会让最高权限仍弹『允许写入』确认（smoke-test #1）」。

**挂起存储 `PendingPermissionStore`**（`python/permissions/store.py`，508 行）：

- `create(...)` 14 个关键字参数（`session_id, turn_id, tool_name, tool_input, reason, prompt, request_id?, matched_rule, command_summary, choices?, peer_summary, mcp_target`）；
- **风险分级 TTL**（`:94-104`）：`danger/secret/protected` → **60s**；普通 → **180s**；`ttl<=0`（交互式）→ **不超时**；
- `resolve(request_id, approved, actor, outcome, *, choice)` → `bool`；`choice ∈ _VALID_USER_CHOICES` 时以 choice 为准，否则用 bool；**`resolve` 顺带写审计日志**（`audit.log.default_audit_log`）；
- `wait(...)`（`:208`）是 async 等待原语，`cancel_pending_for_session`（`:185`）按会话取消。

**grant 指纹（v2）逐字符实现**（`:444-456`）：

```python
def mcp_grant_fingerprint(registered_tool_name: str) -> str:
    tool = (registered_tool_name or "").strip()
    if not tool.startswith("mcp__") or len(tool) <= len("mcp__"):
        return ""                                # 身份不可用 → 空串，不可落 grant（fail-safe）
    canon = json.dumps(["mcp-tool", tool], ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]
    return f"{_MCP_FP_VERSION}:{digest}"
```

即：**`"v2:" + sha256(JSON(["mcp-tool", 注册名]))` 的前 32 位十六进制**，**参数不进指纹**（防注入）。

**HTTP 接口（实测路由）**：`POST /v1/permission/resolve`（`control.py:145`）、`GET /v1/permissions/grants`（`:179`）、`DELETE /v1/permissions/grants/{grant_id}`（`:200`）、`POST /v1/ask/resolve`（`:216`）、`POST /v1/plan/{turn_id}/approve`（`:278`）。

### 9.3 权限实现级对照

| 实现维度 | dsh | XEYO |
|---|---|---|
| 形态 | **独立 capability seam**（`ctx.approval`），另有 permission-presets 组合层 | **纯函数判定**（`evaluate_policy`）+ 挂起存储 + HTTP |
| 策略取值 | `ask` \| `never`（二值） | `always` \| `risk` \| `never` \| `allow`（四值）+ `agent`/`ask`/`plan` 模式 |
| 结果词汇 | `allowed-once` / `rejected` / `cancelled` / `unavailable`（封闭，唯一授予值） | `allow` / `ask` / `deny`（三态）+ `choice` 子词汇 |
| 无 answerer 时 | **fail closed**（`unavailable`） | 无 resolver 时 DENY（写路径注释明示） |
| 审计 | `approval/asked` + `approval/decided` 成对，**必须 turn 内**，否则抛错 | 挂起项内存 + `audit.log` 落盘；不强制 turn 包络 |
| 策略对模型的可见性 | 事件 log-only；**但**注册 `approval:policy` 动态 context 渲染句子（尾插，不破前缀） | `runtime_mode_snapshot` T_now 块（directive 类） |
| 授权粒度 | `allowed-once`（单次） | grant store 按 `(tool_name, fingerprint, scope)` 持久命中 |
| 指纹 | 未见（`approval/asked` 用 request id + toolName） | **v2 = sha256(JSON(["mcp-tool", 名字]))[:32]**，参数不进指纹 |
| 沙箱耦合 | **强**：preset 同时写 sandbox+approval；升级走 `approveEscalation` 严格放宽检查 | 弱：sandbox 只有 Windows Job Object / 容器路由，与审批无映射 |
| 防误配 | 启动期断言：装在不 confine 的执行器上直接抛错 | 无 |
| 远程/多会话 | 未见对应约束 | 显式：远程会话不得静默放行；peer 热文件冲突强制三选 ASK |
| 黑名单 | 未见 workspace 级 deny 列表 | `.xeyo-policy.json` 的 `deny_tools` 在最前判定 |

---

## 10. 沙箱与执行隔离：实现级

### 10.1 dsh：单函数抽象 + 四平台链 + 功能探针

**`confine()` 签名与返回**（`packages/sandbox/sandbox-local/src/index.ts:316-336`）：

```ts
confine(argv: readonly string[], policy: SandboxPolicy): ConfinedArgv {
  if (this.runnerCommand !== undefined) {          // 运维显式断言：不探测，直接信任
    return { argv: [...this.runnerCommand, ...bwrapProfileArgs(policy), '--', ...argv],
             enforcement: 'full', denialSignatures: DENIAL_SIGNATURES.runnerCommand,
             runnerFailureRules: [{ fatalSignatures: this.configuredRunnerFailureSignatures }] }
  }
  const selected = this.selectRunner(policy.mode)
  const runnerArgv = this.runnerArgv(selected.runner, policy)
  return { argv: [...runnerArgv, '--', ...argv], enforcement: selected.enforcement,
           denialSignatures: DENIAL_SIGNATURES[selected.runner],
           runnerFailureRules: RUNNER_FAILURE_RULES[selected.runner] }
}
```

**返回四个东西**——不只是 argv：**执行强度（`enforcement`）、拒绝签名、runner 失败规则**。这是「执行层不仅隔离，还要能把隔离失败翻译成模型可理解的拒绝」的实现。

**三种沙箱模式**（`packages/sandbox/sandbox-policy/src/session-mode.ts:42`）：

```ts
export const SANDBOX_MODES = ['read-only', 'workspace-write', 'danger-full-access']
// 默认 read-only（sandbox-policy/src/index.ts:112 的 schema default）
```

**模式→模型可见文本**（`sandbox-policy/src/index.ts:43-48`）——`read-only` 的措辞值得逐字读：

> Current DSH file policy: read-only. Any available operation enforced by the DSH file sandbox cannot modify files in the standing mode. **Do not refuse a required modification from this policy alone: try an available tool normally and follow any denial and escalation guidance it returns.**

即：**策略声明是信息，不是禁止令**——明确要求模型「别因为这个策略就不动手，照常试，跟随拒绝/升级指引」。这是引擎铁律在 dsh 侧的对应实现（虽然 dsh 没有成文铁律）。

**runner 选择算法**（`selectRunner` `:493-508` + `chainVerdict` `:511-524`）：

```
selectRunner(mode):
  selectedRunner ??= chainVerdict()            # 每个 provider 生命周期只解析一次（缓存）
  if selectedRunner === 'unavailable' → throw SandboxUnavailableError(mode)

chainVerdict():
  chain = internals.chain ?? PLATFORM_CHAINS[platform] ?? []
  if chain 空 → 'unavailable'
  if 只有一个候选 → 直接用（不探测；执行期拒绝仍然 fail closed）
  else 按链序逐个 probeRunner()，第一个非 'unusable' 胜出
```

**探针按后端区分强度语义**（`probeRunner` `:527-556` 注释）：

| 后端 | 探针通过含义 |
|---|---|
| `bwrap` | `'full'`（mount profile 由构造保证覆盖所有承诺的文件效果） |
| `landlock` | 探针报告区分 `full` 与 per-ABI `'partial'` |
| `seatbelt` | `'full'`（deny-file-write* profile 由构造保证） |
| `windows-acl` | **永远 `'partial'`**（文档化的 Everyone 与硬链接边界） |

**拒绝签名表**（`:205-213`）——把内核级错误翻译成结构化信号：

```ts
const DENIAL_SIGNATURES = {
  bwrap:         ['read-only file system'],
  landlock:      ['permission denied'],
  seatbelt:      ['operation not permitted'],
  'windows-acl': ['access is denied', 'access to the path', 'permission denied'],
  runnerCommand: ['read-only file system', 'permission denied'],
}
```

**runner 自身失败的识别**（`:215-226`）比「看退出码」讲究得多：`windows-acl` 打印 `windows-acl-run: <detail>` 且退出 **127**，规则**以退出码门控签名匹配**——注释明确理由：「a confined command that merely PRINTS the signature (or a runner …)」不应被误判为 runner 失败。`Landlock` 是版本化的 exit-125 契约；`bwrap` 与 `sandbox-exec` 只做签名匹配（因为它们的公开契约没有保留失败状态码）。`RunnerFailureRule` 的应用顺序（`sandbox/src/index.ts:74-86`）：**先 `allowedExitCodes` 门控 → 再按整行精确相等剔除 `informationalLines` → 再在剩余 stderr 行内大小写不敏感匹配 `fatalSignatures`**。

**Windows ACL 后端的实现细节**（`packages/sandbox/sandbox-windows-acl/`）：
- 授予是**按 provider 生命周期物化的**：workspace-root 常驻授权 + 每个 live session/workspace 对的**可撤销、随机的私有 temp 能力**（`sandbox-local/src/index.ts:352-360` 注释）；
- runner 收 `--write-sid` / `--temp-write-sid`，**自己不做任何授权**；
- 无 agent 的 workspace-write 调用传 ambient temp ROOT、不带 SID flag，runner 为那一次调用创建并删除一个随机私有子目录；
- `token.ts:179` 注释提到「每个 confined 模式」与「**C:\-root 建树的逃逸**（标准 …）」——说明 ACL 设计考虑过绝对路径逃逸；
- `win32-abi.ts:25`：`WRITE_DAC` 与 `WRITE_OWNER` **刻意排除**，让被限子进程无法改写 ACL 自解锁。

**升级通道**：模型可以申请放宽（`ESCALATION_TARGETS`），走 §9.1 的 `approveEscalation` 严格放宽 + 审批；**gated by 退出码 127 / 版本化 125** 的失败识别让「隔离失败」与「命令自己失败」不混淆。

### 10.2 XEYO：没有 OS 级沙箱

**实测否定结论**（排除 `.venv`/`__pycache__` 的全仓 grep，第二轮已做、本轮沿用）：`landlock|seatbelt|bubblewrap|bwrap|sandbox-exec` **零命中**。XEYO 的隔离手段只有两样：

1. **Windows Job Object**——第二轮核实为**资源限额**（进程数/内存），不是文件系统隔离；
2. **docker 容器路由**——仅评测链路（`TerminalBench/xeyo_harbor_agent.py`），**不是产品路径**，且已知属于「宿主空 scratch + 容器内执行」的旁径（C2 口径）。

**XEYO 真正等价于「沙箱」的东西是权限层**：写作用域（`write_scope`）、受保护元数据（`.git/.xeyo/.agents` 工作区内默认只读）、密钥路径硬拦、工作区外默认拒绝、`deny_tools`。这是**路径级策略**，不是**内核级隔离**。

### 10.3 实现级对照

| 维度 | dsh | XEYO |
|---|---|---|
| 抽象 | `confine(argv, policy) -> {argv, enforcement, denialSignatures, runnerFailureRules}` | 无（无此抽象） |
| 隔离层级 | 内核级（bwrap mount namespace / Landlock LSM / Seatbelt profile / Windows ACL） | 路径级策略（权限函数）+ 资源限额（Job Object） |
| 平台链 | Linux 双后端（bwrap→landlock）、macOS、Windows，按链序探测 | 仅 Windows Job Object（非隔离） |
| 探测 | 启动期功能探针，结果缓存；无可用 runner → 抛 `SANDBOX_UNAVAILABLE` | 无 |
| 失败姿态 | **fail-closed**（链空/探测失败/执行期拒绝都封死） | 权限函数 fail-safe（异常回 ASK） |
| 拒绝识别 | 签名表 + 退出码门控（125/127）+ 整行剔除 benign | 无（无 runner 概念） |
| 升级 | 严格放宽 + 审批，授权仅单次 | 无（改为改 `permission_mode`） |
| 默认档 | `read-only` | 写默认 ask（工作区内） |
| 云沙箱 | E2B POC（独立包） | 无 |
| 容器 | 未见产品路径 | docker 仅评测旁径 |

**判断**：这是本轮差距最大的一处，且是**「缺一整层」**——XEYO 的策略能拦住「模型通过工具写敏感路径」，拦不住「模型让 bash 起一个子进程自己绕过一切」。

---

## 11. 文件系统能力：实现级

### 11.1 dsh：一切经 `ctx.fs`，容器判定有真实现

**seam 结构**：`packages/fs/fs`（Service Definition + `types.ts` + `invariant.ts`）、`fs-local`（Provider：`fsio.ts` / `win32.ts`）、`fs-sandbox`（`containment.ts` / `index.ts`）、`fs-observation-policy`（读前写前观察策略）、`tool-fs`（消费者：`read.ts` / `edit.ts` / `write` / `diff.ts` / `read-image.ts` / `read-render.ts` / `read-target.ts` / `sandbox.ts` / `session-cwd.ts` / `error.ts`）。

**路径包含判定的实现（`fs-sandbox/src/containment.ts`）**——这是本轮读到的最讲究的一段工程代码：

```ts
/** 第一段：词法快速路径 */
function isLexicallyUnder(path, root, caseSensitive): boolean {
  const comparableTarget = comparablePath(path, caseSensitive)
  const comparableRoot = comparablePath(root, caseSensitive)
  if (comparableTarget === comparableRoot) return true
  const prefix = comparableRoot.endsWith(sep) ? comparableRoot : comparableRoot + sep
  return comparableTarget.startsWith(prefix)
}

/** 第二段：文件系统身份回退（dev + ino） */
function sameIdentity(left: BigIntStats, right: BigIntStats): boolean {
  return left.dev === right.dev && left.ino === right.ino
}

/** 第三段：走 target 已有祖先，逐级比对文件系统身份 */
export async function isPathUnder(path: string, root: string, …): Promise<boolean> { … }
```

模块 docstring 说明了为什么要三段：

> Canonical spellings take the fast lexical path; **filesystem identity supplies the conservative fallback for alias-equivalent roots such as Windows 8.3 names and casing.**

即：**不把包含性判定弱化成文本近似**——遇到拼写不一致时，走 `stat(bigint)` 逐级祖先比对 `dev/ino`，因此 Windows 8.3 别名与大小写差异不会造成误判。`MISSING_CODES = {ENOENT, ENOTDIR}` 表示「目标可以有一段尚不存在」，只对**已存在的祖先**做身份比对（`:28-38`, `:53-60`）。

**观察策略**（`fs-observation-policy`）作为一个**独立 gate 包**存在，且**不改 schema**（tool-catalog 明说「an `fs/*` event-gate plugin, no schema change」）：读前/写前状态观察 → 产生 `fs/write-intent` / `fs/edit-intent` / `fs/observed` 事件。**「读前必须先读」这条规则是事件门，不是工具参数。**

**工具面**：`edit`, `read`, `read_image`, `write`（`tool-fs`）+ `str_replace_editor`（独立包，view/create/唯一字面替换/按行插入）+ `glob`/`grep`（`tool-fs-search`，**spawn 打包的 ripgrep 二进制，走 `ctx.subprocess`，从不作为后台 job**——tool-catalog 明确：「no host `rg` install and no shell layer」，且文档配置选了 `sampleOverCapGlobResults: true`）。

### 11.2 XEYO：三条写通道，覆盖不均

| 通道 | 实现 | 覆盖 |
|---|---|---|
| 专用工具 | `tools/file_read_tool/`、`file_write_tool/`、`file_edit_tool/`、`fileio/` | **全**：过 `evaluate_policy`（§9.2 第 9/10 分支的全部硬拦） |
| `server/workspace_fs.py` 直写 | 服务端 workspace 文件接口 | **绕过**权限/rewind/审计（默认只读开关关） |
| WriteStore | `engine/write_store.py`；`ToolMeta.needs_write_store` | 由注册标记决定是否走统一写通道——**是选择项而非强制** |

**读路径的实现级细节**（`policy.py:1502-1543`）：`in _READ_PATH_TOOLS` 分支先 `_pick_path(tool_input, "file_path", "path", "filePath", "notebook_path")`（4 个键名依次尝试），无 path 时**回退到 `os.path.abspath(cwd)`**（即「不填路径 = 读工作区根」）；然后 `check_read_permission_for_path(path, context=ctx)`；DENY 再细分三类原因（`path_outside_working_directory` / `secret_path` / `dangerous_path`），与旧 gate 契约保持一致（注释语）。

**保护元数据的实现位置很讲究**（`:1605-1607` 注释）：

> T12：受保护元数据（.git/.xeyo/.agents）——workspace 内默认只读。**放在 memdir 分支之前会导致 Memory 工具误伤，故置于 memdir allow 之后。**

——即分支顺序是被一次误伤事故调整过的。

### 11.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 单一入口 | **是**：一切经 `ctx.fs` seam，工具无法绕过 | **否**：三条通道，两条有覆盖缺口 |
| 包含判定 | 词法快速路径 + `dev/ino` 身份回退（防 Windows 8.3/大小写） | `path_in_allowed_working_path`（词法为主） |
| 读前写前规则 | 独立 gate 包，**不改 schema** | 无「读前必须先读」的等价门（有 `needs_read_state` 标记 + `missing_read:` 报错） |
| 默认只读 | 沙箱模式 `read-only` 是默认档 | 写默认 ask；受保护元数据默认只读 |
| 写入意图事件 | `fs/write-intent` / `fs/edit-intent` / `fs/observed` | 无（有 `operation_id` 关联 rewind） |
| 检索工具 | `glob`/`grep` spawn 打包 ripgrep，**从不后台** | `glob_tool`/`grep_tool`（Python 实现）+ `bash_tool` 路由 `rg` |
| 路径键名 | JSON Schema 显式定义 | `_pick_path` 容错 4 个键名（file_path/path/filePath/notebook_path） |

---

## 12. Shell / 终端 / 子进程：实现级

### 12.1 dsh

- **`packages/shell`**（61 文件 / 14,758 行）：能力缝 + 本地 provider + pwsh provider。工具面两个名（`bash` / `pwsh`）**各有两个实现包**：一次性（`tool-bash` / `tool-pwsh`）与持久 PTY（`tool-bash-persistent` / `tool-pwsh-persistent`）——**同名不同实现，由组合决定**。
- **一次性 pwsh 的实现在 tool-catalog 里写得很具体**：「Each call runs in a fresh process (no persistent PTY session), with native `C:\...` paths and `$env:NAME` variables.」**且「mirrors the bash tool call-for-call minus sandbox controls」**。
- **`packages/terminal`**（17 文件 / 6,582 行）+ `tool-terminal` 六件套：`terminal_open/close/list/read/send/signal`。`terminal_send(run_in_background: true)` 注册到 `ctx.jobs`；tool-catalog 明确 **「TUI, named key sequences, BEL, resize, auto-start, and cross-agent sharing are absent from the schema」**——即持久终端的能力边界是显式收敛的。
- **`packages/subprocess`**（27 文件 / 7,440 行）：含 Win32 细节与进程树 kill（`subprocess-win32` 之类的库在包内）。
- **后台作业统一收口**：`tool-jobs` 的 `job_kill/job_list/job_output` 是**kind-agnostic** 的——「background bash commands, PTY sends, and subagents are read, listed, and killed through the same three tools」。加载该插件会「arms producers' `ctx.jobs.start()`」。
- **超时**：`guard/timeout-policy`（`packages/guard/timeout-policy/src/index.ts`）——读 `ctx.tools.get(exec.name, exec.agent)?.timeoutMs`，超时产 `ToolExecutionResult`，消息 `tool call timed out after ${timeoutMs}ms`，错误码常量 `TOOL_TIMEOUT`。

### 12.2 XEYO

- **`python/tools/bash_tool/`**：命令路由 + 超时 + 截断 + 后台。与 dsh 的一处**明确的产品级优势**（第二轮已认定，本轮补实现证据）：**45s 未完自动 promote 到后台且进程不重启**——dsh 要模型自己预判 `run_in_background`。
- **危险命令拦截**：`permissions/policy.py` 的 `_evaluate_bash`（`:822-1015`，约 193 行）是一整套 bash 语义分析，实测的正则常量：

| 常量 | 行 | 作用 |
|---|---|---|
| `_BASH_REDIRECT_RX` | `:742` | 写重定向识别 |
| `_BASH_WRITE_CMD_RX` | `:745` | 写命令识别 |
| `_BASH_INTERP_RX` | `:751` | 解释器内联执行识别 |
| `_BASH_WRITE_MARK_RX` | `:754` | 写标记 |
| `_BASH_PY_OPEN_RX` | `:760` | Python `open()` 写文件识别 |

配套函数 `_bash_write_target(command)`（`:765`）→ `bash_write_target(command)`（`:798`）、`_bash_writes_file`（`:785`）→ `bash_writes_file`（`:803`）、`_peer_bash_conflict`（`:1016`）、`_bash_touches_policy_file`（`:1092`）、`_bash_write_path_block`（`:1109`）——**从 bash 命令行反推它想写哪个文件，再走写路径策略**。这是「观测域一致性」的一个实现级范例：bash 与 Write 走同一套写策略。
- **G29 组合命令豁免**（`:1348-1362`）：`bash_command_is_composite(cmd)` 为真 → 不吃前缀 token grant。
- **持久终端**：**无**（实测穷举未见 PTY/terminal 会话抽象）。
- **超时/后台**：后台 job 的 24h 超时 = 事实无超时（第二轮已认定），实现位于 `tools/job_tools.py`。

### 12.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| shell 一次性与持久 | **两种都有**，同名工具由组合切换 | 只有一次性 |
| PTY | 有（6 个终端工具，能力边界显式收敛） | 无 |
| pwsh | 有专门 provider + 专属工具名 + 专属持久版 | Bash 工具内处理（无独立 pwsh 工具面） |
| 后台作业 | `job_kill/list/output` kind-agnostic 收口 | `job_output/list/kill` 三件套（同名同构） |
| 后台启动方式 | 模型显式 `run_in_background` | **Bash 45s 自动 promote**（无需预判） |
| 超时 | per-tool `timeoutMs` + guard 包统一执行 | 工具内自管 + 后台 job 24h（事实无超时） |
| 危险命令分析 | 未见（靠沙箱兜底） | **~193 行 bash 语义分析 + 5 条正则 + 写目标反推** |
| 进程树 kill | 有（subprocess 包） | 有（Windows Job Object / taskkill） |

---

## 13. 模型层与流式协议：实现级

### 13.1 dsh：7 种 chunk 的封闭联合

**文件**：`packages/llm/llm/src/types.ts`（`llm` 包 115 文件 / 32,560 行，另有 `llm-deepseek` / `llm-pi-ai` / `llm-retry` / `token-meter` / `deepseek-llm-api-extensions` 五个子包）

```ts
// types.ts:378-390
export type StreamChunk =
  | { type: 'block-start';     index: number; blockType: ContentBlockType }
  | { type: 'text-delta';      index: number; text: string }
  | { type: 'reasoning-delta'; index: number; text: string }
  | { type: 'tool-call-delta'; index: number; id: ToolCallId; name?: string; argumentsDelta: string }
  | { type: 'block-end';       index: number; block: ContentBlock }
  | { type: 'usage';           usage: TokenUsage }
  | { type: 'finish';          reason: FinishReason; replayState?: ReplayEnvelope }
```

**实现级要点有三个**：
1. **`reasoning-delta` 与 `text-delta` 平级**——thinking 不是特殊路径，是同级的块增量；
2. **`tool-call-delta` 带 `index` + `id` + 可选 `name` + `argumentsDelta: string`**——即**工具参数是增量字符串拼接**，最终解析在 agent 侧（`tool-calls.ts:parseArguments`）；`name` 可选是因为它可能只在第一片出现；
3. **`finish` 携带 `replayState?: ReplayEnvelope`**——**重放元数据随流结束回传**，`AssistantStreamAttempt.replayState`（`assistant-stream.ts:136-139`）转发它，最终写进 `assistant/message.source.replayState`（`agent.ts:455`）。这是「录制/回放」能力的实现接口：**回放不靠重新请求，靠当时记录的 envelope**。

**`ToolSchema` 的归属**（`llm/src/types.ts:392-403`）：声明在 `dsh-llm` 而不是 `dsh-tools`，注释给出理由「it is part of `GenerateOptions`」。

**重试**：独立包 `llm-retry`，有 `llm/retry` + `llm/retry-started` 两个事件（实测）；agent 侧的消费点是 `agent/request-error` waterfall 返回 `{kind:'retry'}` → `continue`（`agent.ts:432-447`）——**重试决策是插件给的，不是硬编码的退避**。

**token 计量**：独立包 `token-meter`。

**KV 缓存 wire 扩展**：`deepseek-llm-api-extensions` 包 + `llm-pi-ai/catalog.ts` 的 `cacheControlFormat: 'offer'`。

### 13.2 XEYO：provider 适配 + reasoning 裁剪 + 事件化重试

- **provider 抽象**：三家各自实现（OpenAI 兼容 / Anthropic / DeepSeek），thinking 处理链路跨厂商**有损**（第二轮已认定）。
- **流式解析**：SSE chunk → `AssistantDelta` / `ReasoningDelta` 两类事件（`events.py:27-35`）——**XEYO 把 text 与 reasoning 拆成两个平级 dataclass**，与 dsh 的 `StreamChunk` 联合里的 `text-delta`/`reasoning-delta` 是同一个观察，两种表达。
- **重试的事件化**（`events.py:287-310`）：`LlmRetryEvent` 带 `attempt, next_retry_ms, code, message, provider, model`，**UI 依据 `next_retry_ms` 渲染倒计时**（docstring 原文）；`LlmRetryStartedEvent` 带 `attempt`。两者都**明确非 surface、不进 transcript**。`code` 来自 `classify_llm_failure`（docstring 原文）——即**错误分类是显式函数**。
- **`UsageEvent` 的上下文构成**（`events.py:128-130`）：`context_breakdown: list[{category,label,tokens}]`，注释「供前端画分段用量条」，且 **`sum(tokens) ≈ context_tokens`**——这是 `_compute_category_chars`（`query_loop.py:427`）+ `_scale_breakdown`（`:468`）两函数协作的产物：**按字符分类统计 → 按真实 token 总量等比缩放**（`_scale_breakdown` 的存在说明 XEYO 明确接受「字符比例近似 token 比例」这一近似）。
- **`reasoning` 裁剪**：第二轮已核实为跨厂商有损；本轮未见独立的 reasoning 存储事件（`ReasoningDelta` 不进 transcript）。

### 13.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 流式类型 | 7 种 chunk 的封闭联合（含 block-start/end、usage、finish） | 2 种 delta 事件 + usage/final 独立事件 |
| 块增量 | 有 `index`/`block-start`/`block-end` 显式块边界 | 无块边界事件（按 delta 流） |
| 工具参数 | `tool-call-delta.argumentsDelta` 增量串，agent 侧解析 | 同上（provider 侧累积后给 `ToolCallEvent.input`） |
| 重放元数据 | **有**（`ReplayEnvelope` 随 finish 回传并持久化） | 无 |
| 重试决策 | 插件 waterfall（`agent/request-error` → `retry`） | 内置退避 + `llm_retry` 事件外发 |
| 错误分类 | `LlmError`（保留 facts）+ `errorChain` 兜底 `UNKNOWN` | `classify_llm_failure` 稳定错误码 |
| token 计量 | 独立包 `token-meter` | `usage/` 模块（ledger/attribution/vendor/pricing） |
| 上下文构成 | 无分类明细 | `context_breakdown` 分段用量（字符→token 等比缩放） |
| KV 缓存声明 | provider 库 `cacheControlFormat` | 靠「左段锁死 + 尾部追加」+ T_now 声道 |

---

## 14. 成本与用量：实现级

### 14.1 XEYO：价格表 + 峰谷 + 账本文件

**价格表实现（`python/usage/pricing.py`，652 行）**——实测字面值：

```python
# (cache_hit, cache_miss, output) 元 / 百万 token；外层 tuple = (空闲档, 高峰档)
_DEEPSEEK: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "flash": ((0.05, 1.5, 4.5), (0.10, 3.0, 9.0)),
    "pro":   ((0.15, 4.5, 13.5), (0.30, 9.0, 27.0)),
}
# OpenAI：(input, cached_input, output) USD / 百万
_OPENAI_USD: dict[str, tuple[float, float, float]] = {
    "gpt-4o-mini": (0.15, 0.075, 0.60), "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60), "gpt-4.1": (2.00, 0.50, 8.00),
}
```

**峰谷时段是数据驱动的**（`:52-58`）：

```python
_DEFAULT_TIME_TIERS = {
    "deepseek": {
        "windows": {"peak": (("09:00", "12:00"), ("14:00", "18:00"))},
        "multipliers": {"peak": 2.0, "offpeak": 1.0},
    },
    # 时段 / 倍率可用 XEYO_TIME_TIERS_JSON 整体覆盖，厂商改窗口或折扣不用发版
}
```

即：**DeepSeek 官方高峰 09:00–12:00、14:00–18:00（北京时区），低峰 = 高峰 × 1/2**；本地表与上游实时价都对齐「低峰」档，故 `peak` 倍率 2.0（`:48-50` 注释）。

**一次 P1-2 修复的实现级痕迹**（`:207-215`）：

> 2026-09-09 修复（P1-2）：旧实现把高峰硬编码为「空闲 × 2」（`_DEEPSEEK` 字面 peak 档），忽略配置里的自定义窗口 / 倍率；此处统一为 `基价(空闲档) × 当前档倍率`，与 `effective_prices`（USD 预算链）的时段语义一致。**未覆盖档一律 ×1.0**。

**token 拆分算法 `split_usage` 的容错顺序**（`:150-162`）：

```python
hit  = _as_int(usage.get("prompt_cache_hit_tokens"))
miss = _as_int(usage.get("prompt_cache_miss_tokens"))
out  = ...                                      # completion / output
if isinstance(details, dict) and hit == 0:
    hit = _as_int(details.get("cached_tokens"))  # ① 回退到 details.cached_tokens
if hit + miss == 0 and prompt > 0:
    miss = max(0, prompt - hit)                  # ② 全 miss
    if miss == 0: miss = prompt
elif hit + miss < prompt:
    miss += prompt - hit - miss                  # ③ 差额并入 miss
```

注释（`:146-147`）解释为什么这样能对齐厂商口径：「无独立 write 档的厂商（DeepSeek）由 `miss = prompt − hit` 把 uncached+cacheWrite 合并为 miss，故 `hit/(hit+miss)` 与该公式等价」。

**账本实现（`python/usage/ledger.py`）**：

| 项 | 实现 |
|---|---|
| 单文件上限 | `_MAX_LINES = 80_000`（`:16`）——**账本文件有行数上限**，防无限增长 |
| 路径 | `usage_dir()` / `events_path()`（`:20-29`） |
| key 指纹 | `key_fingerprint(api_key)`（`:31`）——**API key 不明文入账本** |
| 记录入账 | `record_from_openai_usage(...)`（`:45`）适配 OpenAI usage 形状 |
| 追加 | `_append(event)`（`:133`）+ `_read_events()`（`:142`） |
| 查询 | `query_usage(...)`（`:250`），带 `_day_list` / `_hit_rate` / `_bucket_view` / `_series_from` |
| 专用账本 | `c2_events_path()` / `record_c2_event` / `read_c2_events`（压缩事件账本）；`calibration_events_path()` / `record_calibration_shot`（**校准快照**，`:379-388`） |

`usage/` 目录共 7 文件：`attribution.py`（归因）、`combine.py`、`ledger.py`、`multi_agent_metrics.py`（多代理指标）、`pricing.py`、`vendor.py`。

### 14.2 dsh：只有 token，没有钱

实测：`packages/llm/token-meter`（独立包）+ `TokenUsage` 类型，随 `assistant/message.usage` 一起持久化（`types.ts:305` 注释：「so the model output and its accounting travel together (**there is no separate usage record**)」）。**没有任何货币、价格表、账本**——grep 全仓未见 cost/pricing 相关模块。

### 14.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 计费 | **无**（只有 token 计数） | 完整（表 + 峰谷 + 折算 + 限额） |
| usage 与消息的关系 | **内嵌**在 `assistant/message.usage`（无独立记录） | 独立 `UsageEvent` + `FinalEvent` 快照 |
| 价格来源 | — | 本地表 + 上游实时价 + `XEYO_TIME_TIERS_JSON` 覆盖 |
| 峰谷 | — | 数据驱动窗口 + 倍率，可覆盖 |
| 记账持久化 | — | JSONL 账本（80000 行上限）+ key 指纹 + C2 专账 + 校准账 |
| 归因 | — | `attribution.py` + `multi_agent_metrics.py` |
| 前端呈现 | 无 | `context_breakdown` 分段用量条 + `usd_limit` 倒计时字段 |

**判断**：这一项是**单向**的——XEYO 的运营性资产，dsh 完全没有，且不是「缺一层」而是「不在同一问题域」（dsh 是 harness 给下游产品，钱由下游算）。

---

## 15. 记忆子系统：实现级

### 15.1 XEYO：30 个文件的完整子系统

**实测**：`python/memory/` 有 **30 个条目**。本轮读到实现细节的模块：

| 模块 | 实现级事实 |
|---|---|
| `runtime.py` | C2 摘要与老化：`c2_llm_summary_enabled()`、`_append_c2_instruction(messages)`、`_resolve_c2_summary(...)`、`maybe_advance_aging_boundary(messages, working) -> bool`、`idle_seconds(working)` |
| `runtime.py` 的**配对安全切点** | `_assistant_tool_ids(msg)` / `_tool_result_ids(msg)` → `_pair_ranges(messages)` → **`pair_safe_cut(messages, cut)`** → `c2_cut_index(messages, s0)`。**即压缩切点必须落在 tool_use/tool_result 配对边界之外**，不能把一对拆散 |
| `memdir.py` | 记忆目录模型：`workspace_id(canonical_path)`、`workspace_path(wsid)`、`resolve_memdir_id(wsid, scope)`、`memdir_root(wsid)`、`ensure_layout(wsid, canonical_path)` |
| `memdir.py` 的 frontmatter | `split_frontmatter(text)` / `_parse_fm(text)` / `dump_frontmatter(data)`——**记忆条目是带 YAML frontmatter 的 markdown** |
| `memdir.py` 的保留策略 | `retention_days()`（`:39`）+ **`prune_dead_notes(wsid, now)`（`:47`）**——记忆有 TTL 与清理 |
| `memdir.py` 的索引 | `topic_filename(note)`、`note_topics_path(note, wsid)`、`note_location(note, wsid)`、`index_line(note)`——索引行由笔记生成 |
| `write_policy.py` | `refuse_reason(title, content) -> str \| None`——**写入前先问「为什么拒绝」**，返回原因串 |
| 其他 | `governance.py`、`journal.py`、`nightshift.py`（夜间整理）、`observe.py`、`search.py`、`summarize.py`、`rerank_preference_shadow.py`、`citation.py`、`l5_flag.py`、`simulator/` 等 |

**自动召回恒关的实现（`engine/query_loop.py:355-363`，逐字）**：

```python
def _memory_index_live_enabled() -> bool:
    """Memory 索引常驻注入开关：**恒关**（2026-09-09 用户裁决维持下线）。

    事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役，AGENTS「已下线」
    与此对齐。注入走 project_for_model 的 _append_memory_index 仍供脚本/评测用，
    生产投影层不推送；settings/env 残留一律忽略（同其他固化恒关项）。受控重开
    须源码级改此函数 + A1（200+ 轮 live）/ A3 过门证据。
    """
    return False
```

**实现级要点**：这是**代码常量**开关（不是配置项）——「settings/env 残留一律忽略」明示了配置无法改变行为；重开必须改源码 + 过两道路径证据。

### 15.2 dsh：无跨会话记忆（穷举核实）

实测在整个 `packages/*/*/src/` 内：
- `MEMORY.md` / `memory.md` / `longTermMemory` / `persistentMemory` → **零命中**；
- `memory` 一词的命中全部是**技术同义词**（`attachment-local/store.ts` 的内存缓存、`core/session/src/index.ts` 的 in-memory、`seq-ranges.ts` 的 memo 等），**没有一个是「跨会话长期记忆」语义**。

**dsh 的替代物**：`context/session-reference`（会话引用）+ `tool-session-query` 五件套（`session_event_read/search/trace`、`session_search/trace`）——**dsh 让模型自己查历史，而不是给它一份自动召回的摘要**。这是与 XEYO 记忆子系统根本不同的取向。

### 15.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 跨会话记忆 | **无**（穷举零命中） | 有（30 文件子系统） |
| 替代物 | 会话自查询工具（5 个，只读，按不可变 caller session 鉴权） | 记忆工具 + memdir 文件 + 索引 |
| 存储形态 | — | memdir（workspace_id 目录）+ YAML frontmatter + 索引行 + TTL 清理 |
| 写入准入 | — | `write_policy.refuse_reason(title, content)` |
| 召回 | — | **恒关**（`_memory_index_live_enabled()` 硬 return False） |
| 整理 | — | `nightshift.py` / `summarize.py` / `governance.py` |
| 与压缩的关系 | — | `pair_safe_cut` 保证 c2 切点不拆 tool 对 |

---

## 16. 子代理与多代理：实现级

### 16.1 dsh：seam + 7 种 provider + 持久化深度

**provider 包（实测 10 个）**：`subagent`（seam + `child-agent.ts` + `depth.ts` + `descriptor.ts`）、`subagent-in-process-driver`、`subagent-spawn-in-process`、`subagent-fork-in-process`、`subagent-acp`、`subagent-claude-code`、`subagent-codex`、`subagent-dsh-sdk`、`tool-subagent`、`tool-subagent-control`。共 **102 文件 / 33,523 行**——是 dsh 最大的能力域之一。

**深度控制是持久化的**（`packages/subagent/subagent/src/child-agent.ts:44-56`）：

```ts
export function resolveChildDepth(parent: Agent, maxDepth: number | undefined): number {
  const childDepth = delegationDepthOf(parent) + 1
  …
  if (maxDepth !== undefined && childDepth > maxDepth) {
    throw new SubagentDepthError(childDepth, maxDepth)     // 消息：`subagent depth X exceeds maxDepth Y`
  }
}
```

深度来源是 **session header 的 `delegationDepth`**（§2.1）——头注释解释了为什么必须落盘：「recursion budget survives restart and resume — a runtime-only depth would reset a resumed child to top-level」。

**能力收窄是强制的**：`subagent-acp` 的注释（`:143`）列出子代理**无法兑现**的请求项：`agentOptions` / `outputSchema` / `maxDepth` / `toolFilter`——即**委托边界按 provider 能力显式收窄，不假装支持**。

**工具面**（tool-catalog）：`subagent`（名字可配，默认 `subagent`）、`subagent_fork`（固定路由）、`list_subagent_models`；控制面 `send_message` / `interrupt_agent` / `list_agents`（**全局唯一注册**，且 `list_agents` 来自单独加载的 `/list-agents` 插件）。**向后连续性**：`tool-subagent-control` 的 docstring 说这些是「control tools over continuable background subagents」——子代理可续跑。

**实验性多代理**：`experimental/agent-team`（9 个工具）——`spawn_teammate` / `wait_agent` / `team_task_create|get|list|update` / `interrupt_agent` / `list_agents` / `send_message`；事件 `team/member` / `team/task` / `team/message/queued|delivered`。**shipped base bundle 默认禁用**（tool-catalog 原文）。

### 16.2 XEYO：单实现复用主循环 + 侧链 + 结算

- **`engine/subagent_runner.py`**：`SubagentRuntime` / `SubagentRunResult` 数据类；`run_subagent(...)` → `_run_subagent_body(...)`；`subagent_budgets_for_scope(scope_paths) -> tuple[int,int]` 按写入 scope 给预算；
- **侧链存储**：`_sidechain_dir(main_session_id)` / `_flush_subagent_snapshot(...)` / `_meta_path(main, agent_id)` / `upsert_subagent_meta(...)` / `list_subagent_metas(main)` / `load_sidechain_messages(main, agent_id)` / `clear_sidechain(...)`；
- **续跑**：`_followup_max_turns()` / `_followup_max_tool_calling()` / `_followup_limit()` / `_followup_user_text(text)`——**续跑有独立配额与文本包装**；
- **流式**：`_StreamingTeeClient`（`:76`）——把子代理的流**旁路转发**给父；
- **写陈旧检测**：`_detect_write_stale(messages)`（`:610`）；
- **结论可用性**：`_usable_conclusion(messages, conclusion)`（`:567`）——**结算前校验结论是否可用**；
- **结算**：`engine/agent_settlement.py` + T_now 的 `agent_settlement` 块（event 类，drain 语义）；
- **角色**：`engine/agent_roles.py`（TOML 角色定义）；
- **DAG 调度**：`engine/scheduler.py`（§17）。

### 16.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| provider 数 | **7 种**（in-process / spawn / fork / acp / claude-code / codex / dsh-sdk） | 1 种（复用主循环） |
| 深度控制 | `delegationDepth` **持久化在 session header**；`SubagentDepthError` | 有（`agent_roles` + write scope），未见持久化深度字段 |
| 能力收窄 | 显式（provider 不支持的请求项被点名） | 隐式（子 agent 注册表来自静态工厂 + `subagent_ok` 标记） |
| 工具面 | `subagent` / `subagent_fork` / `list_subagent_models` / `send_message` / `interrupt_agent` / `list_agents` | 单 `Agent` 工具（+ `agent_tool/` 包） |
| 后台续跑 | 有（continuable background subagents） | 有（`_followup_*` 配额） |
| 结算 | 子会话事件自然回流 | `agent_settlement` T_now 块 + `_usable_conclusion` 校验 |
| 多代理团队 | **experimental agent-team（9 工具 + 3 类事件）**，默认禁用 | 无团队概念（`multi_agent_hint` 块 + DAG 调度） |
| 写冲突 | 未见（沙箱层兜底） | `write_scope` 硬门禁 + `_detect_write_stale` |

---

## 17. 调度 / 后台 / 工作流 / Webhook：实现级

### 17.1 dsh

**① Schedule（持久化提醒，实测三种记录类型）**（`packages/schedule/schedule/src/types.ts`）：

```ts
export type ScheduleId = Branded<'ScheduleId'>     // 一个会话内唯一且永不复用

interface AfterScheduleRecord  { id; kind:'after'; prompt; afterSeconds: number; scheduledAt: string }
interface AtScheduleRecord     { id; kind:'at';    prompt; scheduledAt: string }   // RFC 3339 UTC（四位年）
interface EveryScheduleRecord  { id; kind:'every'; … }   // 固定频率，下一目标保持与创建锚点对齐
```

- **三条创建路径**：`after_seconds`（正延迟）、显式绝对 `at`、有界固定频率 `every_seconds`（tool-catalog 原文）；
- **交付是会话本地的**（session-local delivery），且「management reads and mutations require the shared Session persistence barrier」；
- 只注册在**插件加载后创建的 live root Agent scope** 内（即老会话没有这个工具）；
- 事件 `schedule/change`。

**② Jobs**：`jobs`（seam）+ `jobs-local`（实现）+ `tool-jobs`；后台产者三类（bash / PTY send / subagent）统一收口到三个工具。

**③ Webhook**（17 文件 / 2,059 行）：入站入口，`webhook` 包。

**④ Workflow**：`workflow`（能力）+ `workflow-worker-thread`（provider）+ `tool-workflow` + **`tool-ralph`**。`ralph` 的实现证据（`tool-ralph/src/index.ts`）：

```ts
name: 'ralph-loop',                                        // :79
'You are one fresh worker in a foreground Ralph loop. You receive no parent conversation and no prior child session. Do not call the ralph tool: this round already is its worker.'   // :154
```

即 **Ralph 循环 = 每一轮起一个全新结构化子代理（无父会话、无先验子会话）**，模型只能选**不可变目标 + 可选轮数上限**（tool-catalog 原文），且**worker 被明确告知不要再调 ralph 工具**（防递归）。事件 `tool-workflow/run-start|run-end|agent-start|agent-end`（实测 4 个）。

### 17.2 XEYO

**`engine/scheduler.py`（1110 行）——本轮实测其真实能力**：

| 符号 | 行 | 作用 |
|---|---|---|
| `Task` / `TaskRunResult` | `:37` / `:29` | 任务与结果数据类 |
| `toposort(tasks)` | `:109` | **拓扑排序**（真 DAG） |
| `scope_conflicts(...)` | `:134` | 写 scope 冲突检测 |
| `_break_cycles(tasks)` | `:154` | **环检测与打破** |
| `build_tool_whitelist(task)` / `batch_tool_whitelist(tasks)` | `:191` / `:202` | 按任务构建工具白名单（并集） |
| `repair_task_graph(...)` | `:215` | 任务图修复 |
| `turns_for_timeout(timeout_s)` | `:243` | 超时→轮数换算 |
| `Scheduler` | `:249` | 调度器主体 |
| `scheduler_state_path` / `read_scheduler_checkpoint` / `checkpoint_is_incomplete` / `checkpoint_awaiting_synthesis` / `clear_scheduler_checkpoint` | `:905-1000` | **checkpoint 持久化**（崩溃恢复） |
| `last_user_goal_path` / `write_last_user_goal` / `checkpoint_summary` | `:1003-1029` | 目标与摘要 |
| `run_task_batch(...)` | `:1054` | 批量执行 |

**关键实测结论（修正第二轮的定性）**：这是**多代理任务 DAG 调度器**，被 `subagent_runner.py`（5 处导入）、`server/session_pool.py:887 scheduler_for`、`chat.py` checkpoint、`coord/store.py` 与多个 test 消费。**XEYO 真缺的是「时间触发型定时任务」**（用户说「明天 9 点」→ 无人接），而不是这个模块。

**后台作业**：`tools/job_tools.py` 三件套 + 24h 超时（事实无超时）+ 完成补投走 `pending_jobs` T_now 块（directive，一次性待领信息）。

**Webhook / 定时 / 工作流**：**未见**（`workflow` 全仓零命中）。

### 17.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 时间触发定时 | **有**（after / at / every 三种，持久化 + RFC3339 UTC + 锚点对齐） | **无** |
| 任务 DAG | 无（`team/task` 是实验性团队任务） | **有**（toposort + 环打破 + scope 冲突 + checkpoint） |
| 后台作业 | 有（kind-agnostic 三工具） | 有（三工具，24h 事实无超时） |
| Webhook | 有（独立包） | 无 |
| 工作流引擎 | 有（worker-thread provider + `ralph` 循环） | 无（`workflow` 零命中） |
| Ralph 循环 | 有（每轮全新子代理 + 明确禁止递归） | 无 |
| 崩溃恢复 | checkpoint 由 `dsh-session-checkpoint-policy` 拥有（每请求持久化检查点） | `scheduler.py` 自带 checkpoint + `checkpoint_is_incomplete` / `awaiting_synthesis` |

**结论**：两端在「编排」上**互补而非对齐**——dsh 有时间轴（schedule/workflow/webhook/ralph），XEYO 有关系图（DAG + scope 冲突 + 写锁）。两者各自都有对方完全没有的那一半。

---

## 18. Skill 系统：实现级

### 18.1 dsh：frontmatter 逐字段

**包结构**：`skill`（seam）+ `skill-filesystem`（本地 provider，§`ParsedSkill`）+ `skill-badge` + `tool-skill`。共 9 文件 / 6,162 行（`skill-filesystem` 是主体）。

**`ParsedSkill` 逐字段**（`skill-filesystem/src/index.ts:104-112`）：

```ts
interface ParsedSkill {
  name: string
  description: string
  whenToUse?: string
  invocation: SkillInvocationPolicy
  metadata?: Record<string, unknown>
  content: string
}
```

**SKILL.md 的实际格式**（实测内置 10 个技能，如 `.agents/skills/dsh-code-review/SKILL.md`）：YAML frontmatter 只有 `name` + `description`：

```yaml
---
name: dsh-code-review
description: Use when reviewing a pull request in the deepseek-harness repo — orients the reviewer to …
---
```

`whenToUse` 与 `metadata` 是**可选**字段（`ParsedSkill` 里带 `?`），`invocation` 是策略对象（决定技能如何被调用）。

**发现与加载实现**：
- 分区根：`Config` 有 `skipSystem?` / `projectRoot?` / `trustedHost?`（`:95-99`），发现时 `if (root.skipSystem && entry.name === '.system') continue`（`:723`），文件级只认 `entry.name.endsWith('.md')`（`:726`）；
- **条目按 `localeCompare` 排序**（`:722`）——确定的发现顺序；
- 条目解析 `parseFrontmatter(raw)`（`:801` / `:909`）→ 注册到 `ctx.skills`，带 `provider: this.name`（`:216`）；
- **监听配置**（`ResolvedWatchConfig`）：`enabled / usePolling / stabilityThresholdMs / pollIntervalMs / maxProjects / followSymlinks`——**技能目录是热监听的**（含稳定性阈值与轮询间隔，说明考虑过写文件的竞态）。

**注入方式**：工具面是 `skill` 工具；调用后**通过 `agent.inject()` 以 user/message 替换目录**（tool-catalog 原文：`user/message replacement catalogs via agent.inject()`）——即**技能正文以 user 消息注入**，不是系统提示。

### 18.2 XEYO

- 目录：`.xeyo/skills/`；
- 暴露：`Skill` 工具（`tools/skill_tool/`）+ `skill_preinvoke` T_now 块（**用户 `/name` 直呼时的宿主确定性加载**，登记理由：「不注入则直呼依赖模型自觉调 Skill 工具，user 只见技能的直呼即失效」）；
- 开关：`enabled_extensions`（默认关）+ `set_skill_enabled` → push reconcile → T_now 的 `reconcile_events` 块（event 类，静默即永久丢失）；
- 契约测试：`tests/extension/*`。

### 18.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| frontmatter 字段 | `name`（必）+ `description`（必）+ `whenToUse?` + `invocation`（策略）+ `metadata?` | 未见统一 frontmatter 契约（`.xeyo/skills` 目录） |
| 发现根 | 多根 + `skipSystem` / `projectRoot` / `trustedHost` | 单目录 |
| 热更新 | **有**（监听 + 稳定性阈值 + 轮询间隔 + maxProjects + symlink 策略） | 无监听（靠 reconcile 推送） |
| 注入形式 | `skill` 工具 → `agent.inject()` 替换 user 消息目录 | `Skill` 工具 + `/name` 直呼时 T_now `skill_preinvoke` |
| 目录校验 | **完整性 guard**（新 `packages/*/tool-*` 未文档化即失败） | 无 |
| 内置技能 | **10 个**（code-review / doc / translate-docs / pre-push-checks / ci-test-reliability / merging-stacked-prs / archive-agent-notes / find-simplifications / prose-standard / trim-cot-leakage） | `.xeyo/skills` 用户侧 |

---

## 19. MCP 集成：实现级

### 19.1 dsh：直注工具面，无网关

**包**：`packages/mcp/mcp-client/`（`index.ts` / `connection.ts` / `tools.ts` / `transport.ts`）——仅 12 文件 / 4,101 行。

**工具命名与命名空间保留**（`index.ts:4-10, 37-58`）：

```ts
/** Valid `serverName`, kept below the public tool-name budget. */
// 工具名形如 `mcp__<serverName>__<rawName>`
// serverName 必须匹配 [A-Za-z0-9_-]{1,32}
```

- **每个插件实例连接一个 MCP server**，并**保留 `serverName` 命名空间**；重复 serverName 会让**新实例**失败（`:152` 注释：「Reserve the namespace next: a duplicate `serverName` fails THIS instance」）；
- **HMR 热替换**：dispose 旧实例 → 建新实例（`:9-10`）；
- 有 `resolveReconnectPolicy(config.reconnect, …)` —— **重连策略是配置项**；
- 工具是**直注** `ctx.tools`（工具名在全局命名空间里），**没有网关工具、没有会话内启停**。因此**工具面变化 = 新 `request/header`**（tool-catalog 对 `cordis_*` 的说明也印证：「a full changed request header logs those tool-set changes」）。

### 19.2 XEYO：网关工具 + push reconcile + 指纹 v2

第三轮无需重复第二轮结论，仅补实现级细节：

- **`Mcp` 网关工具的 action 集**：`list | describe | call | resources | read_resource`（第二轮核实 `mcp_gateway.py`）；策略层 `_evaluate_mcp_gateway`（`policy.py:1217-1318`，**102 行**）把 `list`/`describe` 视为元动作放行、`call` 解析目标身份后走目标工具策略；
- **指纹 v2 的落库链路**：`PolicyDecision.mcp_target`（`policy.py:64-66`）→ 挂起项 `PendingPermission.mcp_target`（`store.create` 参数）→ `grant_fingerprint(..., mcp_target=...)` → `mcp_grant_fingerprint(identity_name)`；
- **remove 即 DENY**：`permissions/policy.py` 在 grant 两分支**之前**判停用（第二轮的「不可被 grant 穿越」）；
- **tools 数组冻结**：`_schemas_cache` 会话内不复算；新增工具唯一通道 = 网关工具。

### 19.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 工具暴露 | **直注** `ctx.tools`，名 `mcp__server__tool` | 不进 tools 数组，**只出 `Mcp` 网关工具** |
| serverName 约束 | 正则 `[A-Za-z0-9_-]{1,32}` + 命名空间保留（重复即失败） | 未见同形约束 |
| 会话内启停 | **不支持**（靠 HMR dispose/重建 + header change 记录） | **支持**（push reconcile + T_now 活页块） |
| 重连 | 有（`reconnect` 配置 + 策略解析） | 有（`mcp_client.py`） |
| 鉴权/权限 | 未见 MCP 专属权限模型（走工具通用路径） | **指纹 v2 + 停用即 DENY + 目标身份解析** |
| 命名空间冲突 | 显式失败 | 未见 |

---

## 20. Hooks：实现级

### 20.1 dsh：双桥 + 封闭 codec + 事件成对

**包**：`hooks/hook-protocol`（`codec.ts` / `detached.ts` / `events.ts` / `matcher.ts` / `merge.ts` / `runner.ts` / `types.ts` / `invariant.ts`）+ `hooks-claude-code` + `hooks-codex`。33 文件 / 4,873 行。

**事件全集（实测）**：`SessionStart` / `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` / `SubagentStart` / `SubagentStop`（`hooks-claude-code/src/index.ts` 的 runPoint 调用点覆盖）。**matcher 语义有例外**：`UserPromptSubmit` 与 `Stop` 的 matcher 字段被丢弃（`matcher.ts:68` 注释：「because those events have no …」）。

**codec 的优先级规则（实现级，容易搞错的一处）**（`codec.ts:33-130`）：

| 通道 | 合法取值 | 说明 |
|---|---|---|
| 顶层 `decision` | **只有 `approve` / `block`** | `allow`/`deny`/`ask` 写在这里**是无效的、被忽略**（注释：「So an out-of-band `{"decision":"deny"}` is invalid and ignored here (it must not become a real blocking decision)」） |
| `hookSpecificOutput.permissionDecision` | **只有 `allow` / `deny` / `ask`** | **覆盖**顶层 legacy decision（`:125-126`） |
| `hookSpecificOutput.hookEventName` | 必须匹配当前触发事件 | 缺失或不匹配 → **丢弃该 hookSpecificOutput 的 per-event 部分** |
| `additionalContext` | string | 与 `updatedInput` 一起住在 hookSpecificOutput 里 |
| `continue` | bool | 顶层 |

**stderr 摘要上限**（`events.ts:52-54`）：`DEFAULT_STDERR_SUMMARY_MAX_CHARS = 500`，注释说明「它住在截断规则旁边，一次定义，**两个桥不能各写一份漂移**」；截断规则是「trim 后空 → `undefined`；超限按 `maxChars` 切断并加省略号」。

**审计事件成对且必须 turn 内**（`events.ts:1-8`）：

> They carry no surface intent and must remain **turn-enclosed and invoked/result paired**. Mid-turn hook points satisfy that boundary; **SessionStart records injected context instead and does not append `hook/*` outside a turn.**

`HookInvocation` 字段：`turn`, `point`, `dialect`, `handlerId`, `matcher?`；`HookResultRecord` 再加 `output`, `stderrSummaryMaxChars`, `durationMs`（durable 计时）。

**各事件的行为**（`hooks-claude-code/src/index.ts`）：
- `SessionStart`：**detached** 运行（`detached.track(...)`），慢 hook 不阻塞；失败只 `logger.warn`；
- `UserPromptSubmit` → `PreStepDecision`（可改进入 step 的消息）；
- `PreToolUse` → `PreToolDecision`，`deny` 时 `{ kind:'deny', reason: merged.reason ?? 'blocked by PreToolUse hook' }`；
- `PostToolUse` → `PostToolDecision`，`block` 时注入 feedback 文本 + 可选 `additionalContexts`；
- `Stop` → **block 强制续跑**（`:271-274`，reason 默认 `'continue: blocked by Stop hook'`）；
- `SubagentStart` 可注入子上下文；`SubagentStop` **只观察**。

### 20.2 XEYO

第二轮已给设计面，此处补实现级事实：

- **事件全集**：`EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "SessionEnd")`（`extension/hooks.py:38`）——**比 dsh 少 `UserPromptSubmit` / `Stop` / `SubagentStart` / `SubagentStop`，多 `PermissionRequest` / `SessionEnd`**；
- **超时默认 600s**（`_DEFAULT_TIMEOUT_S = 600.0`，`:41`）；
- **三分结果**（`_outcome_for` `:109-116`）：`timeout` → **`abort`**（fail-closed）；`returncode == 0` → `success`；非零 → `abort` if `fail_policy=="abort"` else `continue`；**OSError → `error`**；
- **PermissionRequest 任一非 Success → fail-closed DENY**（模块 docstring `:11`）；
- **执行环境**：`env = scrub_git_env()`（剥离仓库级 `GIT_*`，复用 `plugin_fetcher.scrub_git_env`）+ 注入 `XEYO_HOOK_CONTEXT`（JSON）；`cwd = hook.command.parent`；`command` 相对插件根且**已校验禁越界**（`_resolve_command` `:100-106` 用 `relative_to` 校验）；
- **afdout 注入**：`stdout` 非空且 status ≠ abort 时 `_format_block(...)` → `publish_reconcile_block(blk)`（**走 T_now 管线**）；**正文截断 800 字符**（`:199`）；
- **默认关**：`ExtensionConfig.hooks_enabled()` = 扩展主开关 && hooks 主开关（默认 false）；关闭时「本模块零执行、零注入（旁路形态，逐位 = 停产）」（docstring `:6-7`）；
- **async 接缝**：`run_event_hooks_async` 用 `asyncio.to_thread` 包装（`:210-217`），避免阻塞事件循环。

### 20.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 事件数 | 7（SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / Stop / SubagentStart / SubagentStop） | 5（PreToolUse / PostToolUse / **PermissionRequest** / SessionStart / **SessionEnd**） |
| 协议 | **双桥**（Claude Code + Codex），各有独立 wire 形态 | 自有协议（`XEYO_HOOK_CONTEXT` 环境变量 + stdout） |
| 决策通道 | 顶层 `decision`(approve/block) + `hookSpecificOutput.permissionDecision`(allow/deny/ask)，后者覆盖前者 | 三分结果（success/continue/abort），无「ask」通道 |
| 阻断能力 | 能（PreToolUse deny / PostToolUse block / Stop 强制续跑） | 能（abort；PermissionRequest 非 Success → DENY） |
| matcher | 有（按工具名；两类事件无 matcher） | 未见（无 matcher 概念） |
| 审计 | `hook/invoked` + `hook/result` 成对，**turn 内强制**，带 durationMs | 审计日志，无成对与 turn 包络约束 |
| stderr 上限 | 500 字符（常量集中定义，防两桥漂移） | stdout 截断 800 字符；stderr 只记错误 |
| 超时 | runner 的 `defaultTimeoutMs`（每桥自持配置默认） | 600s（常量） |
| 默认开关 | 由组合决定 | **默认关**（扩展主开关 && hooks 开关） |
| stdout 去向 | 未见过滤后注入模型上下文 | 经 reconcile 注入 T_now 块（`# 插件钩子·<事件>（background only …）`） |

---

## 21. 扩展组合机制：实现级

### 21.1 dsh：Profile 是一个目录，组合是一条 patch 链

**实现**（`packages/boot/app-boot/src/profile.ts:3-23`）：

> A profile is a directory under `$DSH_HOME/profiles/<name>` holding:
> - a `package.json` (**out-of-tree plugin dependencies** plus the profile manifest `dsh.profile` with its ordered `bundles` list)
> - a `cordis.patch.yml`

**组合顺序（逐字）**：「composed by applying each bundle's patch list in `dsh.profile.bundles` order over an empty entry list, then the profile's own patches, then any launcher patches.」

**CLI 入口（实测）**（`apps/cli/src/args.ts`）：

| 参数/子命令 | 作用 |
|---|---|
| `--profile <name>` | boot `$DSH_HOME/profiles` 下的 profile（`:131`） |
| `--patch <path>` | 在 profile 层之后叠加额外 patch-list（**repeatable**，`:132`） |
| `--dump-config` | 打印组合后的 profile 树并退出（`:133`） |
| `--dump-default-config` | 打印**不含用户层与 patch** 的树（`:134`） |
| `web` | boot web profile（`--profile web` 的别名，`:156`） |
| `plugin` | **把剩余参数转发给 profile 目录里的 pnpm**（`:171`） |

**四层结构**（第二轮结论 + 本轮实现证据）：Bundle（可安装的 patch 层）→ Profile（`dsh.profile.bundles` 有序列表 + 自己的 patch）→ Launcher patch（CLI `--patch`，repeatable）→ 用户 patch 文件 `cordis.patch.yml`（**长驻界面热重载**，`profile.ts` 注释：「The user patch layer inside a profile directory (hot-reloaded on long-lived surfaces)」）。

**`--dump-config` / `--dump-default-config` 的互斥校验**（`args.ts:90`）与「config dump 不接受 app 参数」（`:96`）都是 `program.error(...)` 硬退出。

### 21.2 XEYO

- **配置单一来源**：`<root>/.xeyo/settings.json`；home 级与 workspace 级合并，**workspace 更具体者优先**；坏 JSON → keep-last-good + `config.invalid` 审计（方向安全）。
- **扩展点 = `enabled_extensions` 总开关 + per-item `{enabled: bool}`**（plugins / skills / mcp_servers）。
- **会话内启停** = push reconcile → T_now 活页块（`# 工具面变更` / `# 技能目录变更`），digest 幂等（同值零块），pull 兜底 = `enabled_probe`。
- **加一个扩展**：写插件目录（manifest 声明 hooks 等）→ 在 settings.json 打开 → 引擎 reconcile。**无「组合层」概念**（没有 bundle/profile/patch 链）。

### 21.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 组合单位 | Bundle → Profile → Launcher patch → 用户 patch（**四层链式覆盖**） | settings.json 合并（home + workspace，更具体优先） |
| 组合可导出 | **有**：`--dump-config` / `--dump-default-config` 打印组合树 | 无 |
| 组合可复现 | 有（profile 目录 + package.json 依赖 + patch 链） | 部分（settings.json 快照，无依赖清单） |
| 热重载 | 用户 patch 层**热重载** | 扩展热 reconcile |
| 装插件 | `dsh plugin add <pkg>`（转发 pnpm 到 profile 目录） | 插件目录 + settings 开关 |
| 坏配置 | 未见 keep-last-good（profile 装载失败即失败） | **keep-last-good + `config.invalid` 审计**（方向安全） |
| 扩展点数量 | **层数 × 每层 patch 面**（可插入任意插件） | 固定枚举（3 类：plugins/skills/mcp_servers） |

---

## 22. 服务端与协议：实现级

### 22.1 dsh：类型化 RPC + 单一 mux

- **`packages/api`**（118 文件 / 38,948 行）——dsh 最大的包。Remote BFF 组装 + Typert RPC 网关。
- **`packages/typert`**（39 文件 / 14,988 行）——实测四个子包：`generator` / `loader` / `protocol` / `registry`，即**类型图的生成器、加载器、协议、运行时注册表**。类型图的作用是让「服务端方法与客户端调用」共享同一份类型定义，因此 `RemoteErrorDetailsMap` 可以用 `declare module` 扩展（实测 `core/session/src/types.ts:478-483` 就合并了 `'session/not-found': { sessionId: SessionId }`）——**错误详情也是类型化契约的一部分**。
- **`packages/sdk`**（20 文件 / 5,395 行）+ `packages/acp`（19 文件 / 4,885 行）+ `python/sdk` + `python/sdk-runtime`。
- **profile 五形态**（第二轮结论）：`web` / `headless` / `sdk` / `sdk-minimal` / `acp`。

**实现级要点**：dsh 的「协议」不是一组 HTTP 端点，而是**一个类型化 RPC 面 + 单一 WebSocket mux**（第二轮认定）；`session/not-found` 这类错误在类型层面被登记，客户端能静态知道有哪些失败形态。

### 22.2 XEYO：REST 101 条路由 + SSE 双通道

**实测路由总数 101**，分布：

| 文件 | 路由数 | 文件 | 路由数 |
|---|---|---|---|
| `sessions.py` | **32** | `goals.py` / `media.py` / `memory.py` / `usage.py` | 各 3 |
| `workspace.py` | **20** | `chat.py` / `commands.py` / `extensions.py` / `mcp.py` | 各 2 |
| `control.py` | **13** | `audit.py` / `jobs.py` / `references.py` / `skills.py` | 各 1 |
| `rewind.py` | 7 | | |
| `plugins.py` | 5 | | |

**SSE 面是双通道的（本轮最重要的实现发现之一）**。序列化在 `server/routers/chat.py:1088-1125+`：

```python
async for ev in engine.submit(submit_text, options=submit_options):
    frames: list[tuple[int, bytes, str]] = []
    if isinstance(ev, AssistantDelta):
        full += ev.text
        eid = envelope_gen.next()
        frames.append((eid, _openai_chunk(ev.text, model=body.model).encode("utf-8"), "delta"))
    elif isinstance(ev, ReasoningDelta):
        if ev.text:
            xy = _id({"type": "reasoning_delta", "text": ev.text})
            frames.append((int(xy["event_id"]), _xy_chunk(xy, model=body.model).encode("utf-8"), "reasoning_delta"))
    elif isinstance(ev, ToolCallEvent):
        xy_call = {"type": "tool_call", "name": ev.name, "input": _sanitize_tool_input_for_ui(ev.input)}
        …
```

**两个关键实现事实**：

1. **`AssistantDelta` 不发成 XEYO 自己的事件类型**，而是编码成 **OpenAI 兼容的 chat completion chunk**（`_openai_chunk`），帧类别标 `"delta"`——目的是让前端能直接消费 OpenAI 形的流。实测 `assistant_delta` 这个字符串**在 `server/` 目录里零出现**。
2. **其余一切走「xy 旁路帧」**（`_xy_chunk` + `_id()` 分配 `event_id`），带自己的 `type` 名。实测 `chat.py` 里出现的 SSE type 字面量共 **23 个**：`ask_user_pending` / `ask_user_resolved` / `context_compression` / `done` / `error` / `final` / `goal` / `jobs` / `llm_retry` / `llm_retry_started` / `permission_pending` / `permission_resolved` / `plan_pending` / `plan_resolved` / `reasoning_delta` / `stopped` / `system` / `task_state_changed` / `title` / `tool_call` / `tool_progress` / `tool_result` / `usage`。

即 **19 个 EngineEvent 联合成员 → 23 个 SSE 帧类型**（因为 `title` / `jobs` / `goal` / `system` / `done` / `error` 是服务端自造的，不对应引擎事件）。

**旁路实现**：`server/workspace_fs.py`、`workspace_git.py`、`workspace_terminal.py` 三个直通服务端模块（不经引擎权限/rewind），`local_gate.py` 是 loopback 门禁，`session_pool.py` 管会话池，`turn_settlement_hub.py` 管回合结算，`synthetic_round.py` / `goal_round_driver.py` 造合成回合。

### 22.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 协议风格 | 类型化 RPC + 单一 WebSocket mux | REST 101 路由 + SSE 流 |
| 类型安全 | **端到端类型图**（typert generator/loader/protocol/registry） | 无（手写 Pydantic 模型 + 手写前端类型） |
| 错误契约 | 类型化（`RemoteErrorDetailsMap` 可合并） | HTTP 状态码 + 错误体 |
| 流式面 | 一种（RPC 事件流） | **双通道**（OpenAI 兼容 delta + 原生 xy 旁路帧） |
| 事件类型数 | 48 个会话事件（模型可见与否有结构保证） | 23 个 SSE 帧类型（19 引擎事件 + 6 服务端自造） |
| 门禁 | 未见 loopback 门禁（本地部署） | `require_loopback` 依赖注入到每个 router |
| 旁路 | 无（seam 强制） | 3 个服务端直通模块（workspace_fs / git / terminal） |

---

## 23. 前端架构：实现级

### 23.1 dsh：50 个插槽化包

`packages/client/` 下实测 **47 个以上子包**（第一轮数到 47，加 `web` 等）——从 `ui-chat` / `ui-conversation` / `ui-trajectory` 到 `ui-settings-plugin-inventory` / `ui-directory-picker-native`。设计要点（第二轮）：**React-free 对象层 + 插槽化 UI 注册**（`ui-slots`）。

**Trajectory 的实现**（`packages/client/ui-trajectory/src/client/trajectory-record.ts`）：数据来自 session log 投影（`session-projection`），因此**天然可回放到任意历史点**——这正是 `presentCall`/`presentResult` 必须是纯函数的原因（§7.1）。

**其他实测前端相关包**：`ui-conversation/src/client/contract/records.ts`（会话记录契约）、`ui-settings-plugins/src/client/agent-loop-card-controller.ts`（**agent-loop 的 UI 卡片控制器**——说明 dsh 把 loop 配置也做成可插拔 UI）。

### 23.2 XEYO：单包 React 应用

`gui/src/` 实测 15 个一级子目录：`assets` / `bench` / `components` / `generated` / `hooks` / `lib` / `pages` / `pasture` / `paths` / `pet` / `stores` / `styles` / `test` / `theme` + 入口 `App.tsx` / `main.tsx`。

值得点名的三个**业务独有**目录：
- `pet/`（桌宠）——dsh 完全没有的产品形态；
- `pasture/`（牧场？UI 概念）；
- `bench/`（评测面板）——**把评测口径做进了产品 UI**。

`generated/` 是**生成物目录**（斜杠命令 manifest 的落点，`*/generated/slashManifest.ts`，由 `py -3.11 -m slash.export_manifest` 重导）。

### 23.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 包结构 | 50 个独立包（可插槽注册） | 单包，15 个一级目录 |
| UI 注册 | slots 机制（插件式） | 无（静态导入） |
| 事件消费 | 全部 48 类事件有类型化契约 | 消费 SSE 23 类帧中的一部分（TUI 只处理 17 类，第二轮已认定） |
| 轨迹回看 | **Trajectory 面板**（数据来自 session log 投影，可回放） | 有历史面板（IndexedDB + 后端 transcript） |
| 呈现契约 | `presentCall`/`presentResult` 纯函数，日志回放可复原 | 前端按工具名特判渲染 |
| 生成物 | cordis catalog / tool catalog（生成 + 校验） | slash manifest（生成） |
| 桌宠 / 评测面板 | 无 | **有**（`pet/`、`bench/`） |
| 状态存储 | store 包 + connection 层 | IndexedDB（origin 隔离）+ zustand |

---

## 24. 桌面壳与进程管理：实现级

### 24.1 XEYO

**Rust 侧实测只有 3 个文件**：`main.rs`（104 字节，仅入口）、`pet.rs`（4,832 字节，桌宠）、`lib.rs`（**31,110 字节，壳的全部逻辑**）。

`lib.rs` 里的关键机制（第二轮的实现级细化，均已在 09-10 事故中落地）：
- `python_exe_usable()`：**真实探测**（挡「文件存在但不可用」）；
- `resolve_python_exe` 返回 `Result` 且**不静默换解释器**；
- `BACKEND_SPAWN_ERROR` 静态槽 + `get_backend_error` command：GUI 连接失败时**优先显示真实原因**；
- 后端进程守护 + sidecar 打包 + 自包含 slim venv。

**配套脚本**：`scripts/build_slim_venv.py`（自包含断言：缺 DLL / site-packages 不在 `sys.path` / `pyvenv.cfg` 指向外部 → 构建失败）、`build_slim_python.py`、`build_installer.ps1|sh`、`check.ps1|sh`、`smoke_p0p1`。

### 24.2 dsh

**无桌面壳**（第二轮已穷举确认）。分发形态是 npm 包 + `dsh` CLI + profile 目录；长驻界面是 web profile（浏览器）。

### 24.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 桌面壳 | **无** | Tauri（Rust `lib.rs` 31KB 承担全部壳逻辑） |
| 进程管理 | 无（CLI 即进程） | 拉起 + 守护 + 真探测 + 错误回传 |
| 解释器/运行时 | Node（同语言，无跨语言启动问题） | **Python sidecar**（跨语言，需自包含 venv + 可用性探测） |
| 打包 | npm / 无安装包 | MSI + 自包含 slim venv（~85M/105M） |
| 桌宠 / 托盘 / 快捷键 | 无 | 有（`pet.rs` + 窗口/托盘） |
| 分发一致性风险 | 低 | **高**（薄壳 venv 事故已发生一次） |

---

## 25. 对外集成（CLI / SDK / ACP）：实现级

### 25.1 dsh

- **CLI**（`apps/cli/src/args.ts`）：`--profile` / `--patch`（repeatable）/ `--dump-config` / `--dump-default-config` + 子命令 `web` / `plugin`（详见 §21.1）。配套模块：`args.ts` / `bin.ts` / `plugin.ts` / `profile-boot.ts` / `process-shutdown.ts` / `dump-config.ts` / `sdk-source.cordis.patch.yml`。
- **SDK**：`packages/sdk`（TS）+ `python/sdk` + `python/sdk-runtime`（打包运行时，**Python wheel**）；`subagent-dsh-sdk` 说明 SDK 也被用作子代理 provider。
- **ACP**（Agent Client Protocol）：`packages/acp`（19 文件 / 4,885 行）+ `subagent-acp`——**双向**：既能作 ACP server 被别的客户端接，也能作客户端去驱动 ACP 兼容的子代理。

### 25.2 XEYO

**CLI 子命令实测**（`python/cli/main.py`）：

| 组 | 命令 |
|---|---|
| 顶层 | `version` / `setup` / `chat` / `attach` / `serve` |
| `sessions` | `list` / `show` / `rm` |
| `config` | `path` / `show` / `set` |
| `coord` | `run` / `status` |

**对外能力**：Typer CLI + HTTP attach + TUI + 微信通道（`SendToWeChat` 工具 + outbound ASK）。**无 SDK、无 ACP**。

### 25.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| CLI 形态 | profile 启动器（配置组合为中心） | 功能命令族（chat/attach/serve + 3 组管理） |
| CLI 命令数 | 2 子命令 + 4 选项 | **12 命令 / 4 组** |
| SDK | TS + Python（含打包运行时 wheel） | 无 |
| ACP | 有（server + client 双向） | 无 |
| 对外通道 | RPC / SDK / ACP | HTTP + CLI + TUI + 微信 |
| 配置导出 | `--dump-config` | `config show` |

---

## 26. 配置 / 凭据 / 身份 / 遥测：实现级

| 项 | dsh | XEYO |
|---|---|---|
| 配置 | profile 目录（`package.json` + `cordis.patch.yml`）+ `$DSH_HOME` | `.xeyo/settings.json`（home + workspace 合并，workspace 优先） |
| 坏配置 | profile 装载失败即失败 | **keep-last-good + `config.invalid` 审计**（方向安全） |
| 凭据 | `packages/credentials`（19 文件 / 4,305 行）+ `credentials-local` | 未见独立凭据模块（API key 经 `key_fingerprint` 进账本但不落明文） |
| 身份 | `packages/identity`（**2 文件 / 205 行**，极小） | 无等价物（身份即 `IDENTITY` 提示句） |
| 遥测 | `runtime-diagnostics` 包 | **无**（`opentelemetry` 全仓零命中，第二轮已穷举） |
| 审计 | 事件即审计（`hook/invoked`+`hook/result`、`approval/asked`+`approval/decided`） | `audit.log`（`audit/log.py`）+ `server/routers/audit.py`（1 路由） |
| 日志 | `session-log-deepseek` 包（含 `session-log-deepseek/delivery-accepted` 事件） | JSONL session + `logs/` 目录 |

**一个值得注意的规模反差**：dsh 的 `identity` 只有 205 行——说明它把「身份」当极小的事；XEYO 没有独立身份模块，但 `IDENTITY` 常量是**跨入口共用的单一入口**（`system_prompt.py:21-25` 注释：「GUI / CLI / side-chat / 子 agent 前缀共用」）。

---

## 27. 质量门与测试：实现级

### 27.1 dsh：per-file 100% 覆盖率门 + 完整性 guard

**`docs/testing.md` 实测原文**：

> **Coverage gate** (`pnpm run test:coverage`): the gating run, **per-file 100% on `packages/*/*/src`**. An uncovered line is often dead code the gate flags for deletion, not a missing test to bolt on. Line coverage is necessary, never sufficient — it proves lines ran, not that the feature works as shipped. Per-file 100% on `packages/shell/pwsh-local/src` needs a real `pwsh`: without one its executor suites self-skip and `vitest.config.ts` exempts the file so pwsh-less hosts stay green, while CI runners ship pwsh and enforce the full bar.

**三条实现级要点**：
1. **未覆盖行 = 删代码的信号**（不是补测试的信号）——这条把覆盖率门从「补测试指标」改造成「死代码发现器」；
2. **明确承认行覆盖率的局限**（"necessary, never sufficient"）；
3. **有平台条件的豁免机制**：`vitest.config.ts` 对 `pwsh-local` 豁免，无 pwsh 的机器保持绿，CI 有 pwsh 则执行完整门——**豁免点在配置里显式声明，不是静默跳过**。

**录制会话快照回放**（`docs/testing.md:16` 原文）：

> Session fixtures retain headers and payloads but **omit body sequence/time envelopes; replay synthesizes them**. Replay, record, and refresh select each **parent/child role's highest generation**. Current v2 uses `.v2`, one row per event, and embedded compact Assistant streams; retained v0 (suffixless) and v1 (`.v1`) may keep canonical packed rows for migration coverage. [The migrator](../scripts/migrate-packed-session-fixtures.ts) rewrites older historical layouts.

——即：**fixture 不存 `seq`/`time`（回放时合成）**，且历史三代布局（v0 / v1 / v2）共存并有迁移脚本。

**其他机器门（实测）**：
- `verify-tool-catalog`（doc-sync 的一部分）：**新 `packages/*/tool-*` 未进文档即失败**；
- cordis catalog 的生成/校验；
- 863 个测试文件；CI 有覆盖率分区并行 + self-hosted runner 共享主机与卷（`docs/testing.md:20` 明确「Only the process is isolated: ports, predictable paths, external namespaces, and inherited children are not」）。

### 27.2 XEYO：三道本地门 + 无覆盖率门

- **`scripts/check.ps1` / `check.sh`**：pytest（not live）+ typecheck + vitest；
- **无 pre-commit / husky**——「全绿才 commit」纯靠人跑（第二轮已认定）；
- **无 per-file 覆盖率门**；
- **CI**（`.github/workflows/ci.yml`）：`push` 到 `main`/`master` + `pull_request` 触发；`concurrency` 分 `ci-${{ github.ref }}` 且 `cancel-in-progress: true`；python job 在 `ubuntu-latest` 用 Python 3.11，依赖缓存指 `python/requirements.txt` + `python/pyproject.toml`；
- **`.github/workflows/ci.yml` 只在 push 后生效**（第二轮）——这是「本地门 vs CI 门」的实现级缺口；
- **测试规模**：python 307 个 `test_*.py`；gui 102 个测试文件；
- **沙箱内全量 pytest 不可靠**（basetemp 竞争假失败），须单跑 + `--basetemp` 全新路径（第二轮已记入项目记忆）。

### 27.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 覆盖率门 | **per-file 100%**（`packages/*/*/src`），未覆盖行视为死代码 | 无 |
| 平台豁免 | 配置里显式声明（`vitest.config.ts` 豁免 pwsh-local） | 无 |
| 文档完整性门 | **有**（tool-catalog / cordis catalog 生成 + 校验，新工具未文档化即失败） | 部分（slash manifest 生成，但无「未文档化即失败」） |
| 快照回放 | **有**（fixture 省略 seq/time，回放合成；v0/v1/v2 三代 + 迁移脚本） | 无 |
| 本地门 | 见 testing.md 的多门清单 | `check.ps1`（3 门） |
| pre-commit | 未见 | **无**（纯靠人） |
| 测试数 | 863 文件 | 307 + 102 文件 |
| CI 触发 | （未读 CI 配置，`docs/testing.md` 只提门） | push/PR；**仅在 push 后生效** |

---

## 28. 构建 / 打包 / 分发：实现级

| 项 | dsh | XEYO |
|---|---|---|
| 构建器 | `tsdown`（每包一个 `tsdown.config.ts`）+ monorepo 工具链 | Vite + tsc；`cargo` 打 Tauri；PyInstaller 之类不用于后端（用 slim venv） |
| 分发物 | npm 包 + `dsh` CLI | MSI（Tauri）+ 内嵌自包含 Python 运行时 |
| 运行时自包含 | N/A（Node 同语言） | **必须自包含**（`build_slim_venv.py` 用 python-build-standalone + 三条断言） |
| 体积 | N/A | 52M/77M → **~85M/~105M**（裁 pytest/ray/sqlalchemy、保留 pip） |
| 依赖隔离 | pnpm workspace | pip（产品可装可选依赖） |
| 模板/生成 | cordis catalog / tool catalog | slash manifest |
| 关键坑 | 未见记录 | **`pyvenv.cfg` 必须写 `home=.`（无空格）**；替换 venv 前必须停后端（WinError 5）；构建脚本禁递归删大目录（改名旁置） |

---

## 29. 实现级差异总表

### 29.1 「缺一层」级（不是缺功能）

| 层 | dsh | XEYO | 影响 |
|---|---|---|---|
| **OS 级沙箱** | `confine(argv, policy)` 四后端 + 探针 + fail-closed + 拒绝签名 | 无（仅路径级策略 + Job Object 资源限额） | 模型可让 bash 起子进程绕过一切策略 |
| **事件溯源会话日志** | 48 事件 + `seq` 连续 + `ignorable` 保守默认 + `surfaceOp` 强制 + 版本化 + 每 step 原始流 | 19 事件 + 消息级 transcript，无信封/序号/版本 | 无法逐字重建「模型当时看到什么」；压缩/改写无举证机制 |
| **端到端类型化协议** | typert 类型图 + RPC + 类型化错误详情 | 手写 Pydantic + 手写前端类型 | 前后端契约靠人工同步 |
| **组合层** | Bundle → Profile → Launcher patch → 用户 patch，可 dump 可复现 | settings.json 合并 | 扩展组合不可导出、不可复现 |
| **质量门** | per-file 100% + 文档完整性 + 快照回放 | 无覆盖率门、无 pre-commit、CI 仅 push 后生效 | 死代码与文档漂移无人拦 |
| **持久终端 + LSP + 工作流 + 定时 + Webhook** | 均有 | 均无 | 能力面缺口（非机制缺口） |

### 29.2 「XEYO 独有且更深」级

| 项 | 实现深度 | dsh 状态 |
|---|---|---|
| T_now 注入管线 | 4 策略 + 20 块登记 + 硬顶 21 + 三层预算 + 类感知裁剪 + 机器执法 + 块级消融开关 + 逐条理由 | 无（只有动态 context 快照） |
| env_channel 声道 | 字节级伪造 tool 对 + copy-on-write + 结构类 4xx 回落 skip + 进程级备忘 + 契约测试禁行为引导词 | 无 |
| 成本治理 | 价格表 + 数据驱动峰谷 + split_usage 三重容错 + 80000 行账本 + key 指纹 + 归因 + C2 专账 + 校准账 | 无货币概念 |
| 权限策略实现 | 11 级分支顺序 + 写路径单向性 + bash 语义分析（193 行 / 5 正则 / 写目标反推）+ 指纹 v2 + 4 条 grant 豁免 + 风险分级 TTL | 二值策略 + fail-closed 四值结果（更简洁，但无路径级策略） |
| 记忆子系统 | 30 文件 + frontmatter + TTL 清理 + 写准入 + 配对安全切点；召回恒关（源码级开关） | 无（改为会话自查询工具） |
| 桌面壳 | Tauri + 真探测 + 错误回传 + 自包含 venv 断言 | 无 |
| 多会话协同 | peer presence / file conflict 块 + write scope + peer 热文件三选 ASK | 未见（沙箱兜底） |
| 任务 DAG 调度 | toposort + 环打破 + scope 冲突 + checkpoint + 合成 | 无（schedule 是时间轴不是关系图） |
| 观测域一致性 | bash 写目标反推 → 与 Write 同策略；路由标记 `[routed: …]`；T_now 与工具同通道 | 无此概念的显式实现 |

### 29.3 同一问题的两种实现（逐项）

| 问题 | dsh 的实现 | XEYO 的实现 |
|---|---|---|
| 工具并发 | 有界池(10) + exclusive barrier + 顺序提交 + 运行期可插 barrier | 内联 `while pending` + 只读早跑 |
| 中断的 replay 有效性 | 未启动调用**合成错误结果** | 占位补全 + `interrupted` 锚 |
| 结果截断 | head/tail 各半 + spillStore + 定位符 | per-tool 16000 字符预算 + spill + `offload_read` 工具 |
| 审批无 answerer | `unavailable` → fail closed | DENY（写路径） |
| 审批身份 | request id + toolName | 指纹 v2（sha256 前 32 位，参数不入指纹） |
| 策略可见性 | 事件 log-only **+** 动态 context 渲染句子（尾插保前缀） | `runtime_mode_snapshot` T_now 块（directive 类） |
| 前缀断裂 | 如实记录 header change + 开新 series | 设计上避免（左段锁死 + 尾部追加） |
| 记忆 | 让模型自查询历史（5 个只读工具） | 自动记忆子系统（召回恒关） |
| 动态内容注入 | `systemPrompt.context()` → 真 user 消息 | env_channel 伪造 tool 对（脱离 user 角色） |
| 定时 vs 关系图 | 时间轴（after/at/every + workflow + ralph） | 关系图（DAG + scope 冲突 + 写锁） |
| 加工具的门 | 文档完整性 guard 强制 | 单表登记 + AGENTS 约定 |
| 自我修改 | **7 个 `cordis_*` 工具**（模型定义并挂载插件） | 无 |

---

## 30. 结论与取证边界

### 30.1 三句话结论

1. **实现级的差距主要体现在「有没有那一层」**：沙箱、事件溯源日志、类型化协议、组合层、质量门——dsh 这五处是**层**，XEYO 对应位置是**函数或约定**。补功能容易，补层难。
2. **XEYO 的实现深度集中在「引擎对模型注意力的治理」**：T_now 管线（字节级声道 + 三层预算 + 机器执法）、权限策略（11 级分支 + 单向性 + bash 语义分析）、成本治理（峰谷 + 账本 + 归因）——这三项的实现复杂度**不低于** dsh 任何一层，且 dsh 完全没有对应物。
3. **两端在编排上是互补而非对齐**：dsh 有时间轴（schedule/workflow/ralph/webhook），XEYO 有任务图（DAG + scope 冲突 + checkpoint）。谁都不是「更完整」的那一个。

### 30.2 前两轮的更正是否还被维持

- 第二轮更正一（dsh **没有** `Mcp` 网关工具、工具面**不冻结**）：**本轮维持并加固**——`mcp-client` 直注 `ctx.tools`（`mcp__<server>__<tool>`，实测无网关工具），`systemPrompt.assemble()` 每 step 重算、`orderTools` 每次重排（§3.1、§19.1）。
- 第二轮更正二（`engine/scheduler.py` 不是死代码）：**本轮维持并细化**——它是一个真 DAG 调度器（toposort + 环打破 + scope 冲突 + checkpoint + `run_task_batch`），消费方含 `subagent_runner.py`、`server/session_pool.py:887`、`chat.py`、`coord/store.py`（§17.2）。XEYO 真缺的是**时间触发型定时任务**。
- 计数更正：XEYO SSE 实测 **19 个 EngineEvent + 20 个 dataclass（`PermissionExpiringEvent` 未进联合）+ 23 个 SSE 帧类型**（§2.2、§22.2）；dsh 会话事件实测 **48 个**（§2.1）；dsh 工具目录实测 **62 行 / 66 个工具名**（§7.4）；XEYO 工具实测 **26 个**（§7.5）；XEYO 路由实测 **101 条**（§22.2）。

### 30.3 本轮新发现的、前两轮没有的实现事实（挑 8 条）

1. **dsh 的 `ToolRuntimeScheduler.prepare` 返回三态**（`dispatch` / `post-result` / `final-result`），其中后两者的差别就是「post-execute 瀑布还能不能改写」——这是并发优化与可拦截性的分界（§7.2）。
2. **dsh 的 `spill` 是头尾各半**（`ceil/floor`），不是「保头丢尾」（§8.2）。
3. **dsh 的审批结果词汇是封闭四值且只有 `allowed-once` 一个授予值**，无 answerer → `unavailable`（fail closed）（§9.1）。
4. **dsh 把「模型可见的策略句子」做成动态 context 而非事件**，理由写在注释里：**切换策略不重写稳定前缀**（§9.1）。
5. **dsh 的 `fs-sandbox` 包含性判定有词法快速路径 + `dev/ino` 身份回退**，专门处理 Windows 8.3 与大小写（§11.1）。
6. **dsh 的 hook codec 顶层 `decision` 只认 `approve`/`block`**，`allow`/`deny`/`ask` 必须写在 `hookSpecificOutput.permissionDecision` 里且**覆盖**顶层值（§20.1）。
7. **XEYO 的 SSE 是双通道**：`AssistantDelta` 编码成 OpenAI 兼容 chunk（`server/` 里 `assistant_delta` 零出现），其余走 `_xy_chunk` 旁路帧（§22.2）。
8. **XEYO 的 `_trim_tagged_blocks` 有「剩余不足 64 字符就整块丢弃」的实现细节**，且 directive/event 永不裁剪（§6.3）。

### 30.4 取证边界（必读）

**本轮实际做的**：
- dsh：精读 20 个实现文件全文或大段（`agent.ts` 589 行、`tool-calls.ts` 290、`assistant-stream.ts` 140、`session/types.ts` 483、`system-prompt/index.ts` 614、`tools/index.ts` 关键段 255-455、`sandbox-local/index.ts` 300-560、`permission-presets/index.ts`、`user-approval/index.ts` 148-215、`escalation.ts` 130-175、`fs-sandbox/containment.ts` 1-60、`spill-policy/index.ts`、`hooks codec/events`、`skill-filesystem` 类型段、`mcp-client/index.ts` 头部、`args.ts`、`profile.ts`、`child-agent.ts`、`tool-ralph/index.ts` 关键段、`testing.md`、`tool-catalog.md` 全文）。
- 计数全部当场实测（会话事件 48、工具目录 62、包规模按目录聚合、测试 863）。
- XEYO：精读 `msgtypes/events.py` 全文 333 行、`prompt/system_prompt.py` 全文 217 行、`permissions/policy.py` 1319-1700 全文、`permission/store.py` 关键段、`prompt/t_now_strategy.py` 全文 133 行、`prompt/turn_context.py` 100-175、`extension/hooks.py` 全文 217 行、`pre_llm_inject.py` 登记表 + 裁剪算法 + `_tag_block`、`usage/pricing.py` 表与峰谷段、`engine/query_loop.py` 结构与守卫段、`server/routers/chat.py` 1080-1125、CLI 命令、路由计数、规模计数。

**本轮未逐行读的**：
- dsh：`typert` 四个子包内部实现（只读了包结构与用途）、`api` 118 文件的 RPC 装配细节、`client/*` 50 个包内部（只读了 Trajectory 的记录文件与几个入口）、`llm-deepseek` / `llm-pi-ai` 的 provider 实现细节（只读了 `catalog.ts` 一行证据）、`subagent` 各 provider 的完整实现（读了 seam 与深度控制）、`storage` 的 SQLite schema 机制、`compaction-basic` 的压缩算法本体（只读了阈值计算）、`workflow` / `webhook` / `jobs` 的内部实现、`acp` 协议细节。
- XEYO：`engine/query_loop.py` 2000 行中的主体执行段（读了循环头、守卫构造、并发段行号，未逐行读 800-2000 的每个分支）、`permissions/policy.py` 的 `_evaluate_bash` 193 行内部（读了常量与函数名，未逐行）、`memory/` 30 个模块（读了 `runtime.py` / `memdir.py` / `write_policy.py` 的符号，未读实现体）、`gui/src` 15 个目录（读了目录结构与规模，未读组件实现）、`engine/scheduler.py` 1110 行（读了符号表，未读 `Scheduler` 类实现体）、`rewind` 的 `execute`/`reconcile`（读到函数名与 WAL/原子写原语，未读完整流程）。

**任何「未见」断言的检索面**：全部做过排除 `.venv` / `__pycache__` / `node_modules` 的全仓 grep（dsh 的跨会话记忆、XEYO 的 landlock/seatbelt/bwrap/opentelemetry/workflow/PTY 等）。

**判据提醒**：本轮所有引用都带 `文件:行号`；若某条结论与第一、二轮冲突，**以本轮实测为准**（本轮是直接读源码，前两轮部分依赖子代理转述）。

