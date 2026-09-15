# XEYO × DeepSeek Harness（dsh）设计级对比 · 第二轮

> 从**架构**走到**系统实现的设计**：每个系统都回答同一组问题——为什么这么设计、抽象与契约长什么样、一次操作的数据流怎么走、关键机制怎么实现、扩展点在哪、作者自己怎么解释这个取舍。
> 2026-09-10。结论均带 `文件:行号`。凡"未见"= 按可检索面穷举后未命中，不等于绝对不存在。

**与第一轮的关系**：第一轮（`docs/XEYO-vs-DeepSeekHarness-全量对比.md`）是**功能面清单**（有什么、没有什么）。本轮是**设计面解剖**（为什么这样、怎么接起来的），并**更正第一轮的两处硬错误**（见 §0.2）。两份文档互补，不重复。

**取证口径**

| | XEYO | dsh |
|---|---|---|
| 仓库 | `D:\lea\XenYon code` | `D:\lea\dsh-src` |
| 版本 | 工作树 HEAD | `d347e70` / `0.1.3-alpha.1` / `master` |
| 规模 | Python 1141 文件 / 160,772 行；gui 81,484 行；tui 3,544；rust 1,162 | 3226 个 `.ts/.tsx` / 767,579 行（含测试）；**255 个包** |
| 本轮方式 | 6 路分队按**能力域**跨两端并行通读 + 主代理复核加载性结论 | 同左 |

---

## 0. 先说两处更正（第一轮的错误）

第二轮的价值有一半在这里：两个第一轮的强结论经不起复核，错了，而且真相比原来那个说法更有意思。

### 0.1 更正一：dsh **没有** `Mcp` 网关工具——"两端独立演化出同一结论"是我编的

第一轮 §16 我写：「两边都独立演化出『工具面会话内冻结 + 会话内新增工具只能走网关工具』，连网关工具命名（`Mcp`）都一致」。

**这是错的**，错因很蠢：我把 **XEYO 自己 `AGENTS.md` 的扩展层契约文本**（里面写着 `_schemas_cache`、`Mcp` 网关）当成 dsh 的契约抄进了 dsh 那一列。`_schemas_cache` 是 XEYO 的变量名，dsh 根本没有这个概念。

复核证据：

```
# 1) dsh 全仓无名为 Mcp 的工具
$ grep -rn "name: *[\"']Mcp[\"']" packages/ --include=*.ts   →  空

# 2) dsh 的 MCP 工具是直接注册进工具面，公共名带命名空间
packages/mcp/mcp-client/src/index.ts:4
  * (`mcp__<serverName>__<rawName>`). Each plugin instance connects to one MCP
packages/mcp/mcp-client/src/tools.ts:113
  const joined = `mcp__${serverName}__${rawName}`

# 3) dsh 唯一的 MCP 包
$ ls -d packages/mcp/*/   →  packages/mcp/mcp-client/
```

那么 dsh 到底怎么保证工具面稳定？**它压根不冻结**：

```
packages/core/tools/src/index.ts:1144  private view(scope?: ScopeKey): ToolView {
packages/core/tools/src/index.ts:1152    const inherited = new Map(...this.layers.global.tools.entries())
packages/core/agent-loop/src/agent.ts:242
  const assembly = await this.loopCtx.systemPrompt.assemble(assembleContextFor(this, signal))
packages/core/agent-loop/src/agent.ts:356
  this.buildRequest(turn, step, assembly.tools, system, this.session.deriveMessages(), ...)
```

`ToolRuntime.view()` 是**按需派生**、无 memo 无缓存（全文件 grep `memo|cache` → 空）；`systemPrompt.assemble()` 与 `deriveMessages()` 一样**每 step 重算**。工具面随插件挂载/卸载**实时变化**，`cordis_define` 因此可以让模型在会话内直接给自�己加工具（`tool-cordis/src/index.ts:152`）——**不需要网关，因为没有冻结**。

dsh 真正在管 KV 缓存的地方是 **provider 库**，而且是声明式的：

```
packages/llm/llm-pi-ai/src/catalog.ts:129  export type PiAiCacheControlFormat = ...
packages/llm/llm-pi-ai/src/catalog.ts:233  cacheControlFormat: 'offer',
docs/config-catalog.md:1248  /** Whether the endpoint accepts `cache_control` on tool definitions; `anthropic-messages`. */
docs/config-catalog.md:1241  /** Whether the endpoint accepts long prompt-cache retention; ... */
```

**更正后的真实对照**（比原来有价值得多）：

| | dsh | XEYO |
|---|---|---|
| 工具面是否会话内冻结 | **否**——每步 `view()` 重新派生 | **是**——`_schemas_cache` 会话内冻结，绝对红线 |
| 会话内新增工具 | 直接 register，工具面自然变化 | **不可能**（冻结），故必须发明 `Mcp` 网关工具作为逃生口 |
| KV 前缀稳定性来源 | **结构副产品**：追加式事件日志使消息前缀天然 append-only；缓存策略下沉到 provider 库（`cacheControlFormat`/`supportsLongCacheRetention`/`supportsCacheControlOnTools`） | **显式政策**：左段刻意极简（Date/Model 不进）+ `frozen_until` 游标 + 工具面冻结 |
| 客户端一致性怎么保证 | 类型化 RPC（Typert）+ 事件溯源日志 | SSE 事件流 + 磁盘 transcript 权威 |

也就是说：**两端不是"独立收敛到同一结论"，而是"取向相反且各自自洽"**。XEYO 选择冻结，代价是必须造一个网关工具来绕过自己的冻结；dsh 选择不冻结，代价是必须用类型化 RPC + 事件溯源来保证"客户端看到的"和"日志记下的"一致。第一轮那句话请作废。

### 0.2 更正二：XEYO `engine/scheduler.py` **不是**"写了无消费方"

第一轮（及项目审计文档）称 `scheduler.py`（1110 行 DAG）"未接线"。复核后**不成立**：

```
$ grep -rn "scheduler" --include=*.py --exclude-dir=.venv --exclude-dir=__pycache__ .
engine/subagent_runner.py:924   from engine.scheduler import Task
engine/subagent_runner.py:978   from engine.scheduler import scope_conflicts
engine/subagent_runner.py:1030  from engine.scheduler import MAX_DECOMPOSE_TASKS, repair_task_graph
engine/subagent_runner.py:1104  from engine.scheduler import MAX_DECOMPOSE_TASKS, Task
engine/subagent_runner.py:1232  from engine.scheduler import MAX_DECOMPOSE_TASKS
server/session_pool.py:887      def scheduler_for(self, session_id, *, write_store=None)
server/session_pool.py:889          from engine.scheduler import Scheduler
server/routers/chat.py:961-974  read_scheduler_checkpoint / clear_scheduler_checkpoint
coord/store.py:10,68            复用 scheduler.scope_conflicts 语义
tests/test_agent_tool.py:15     from engine.scheduler import Task, scope_conflicts, toposort
tests/test_multiagent_hardening.py:15  from engine.scheduler import Task, run_task_batch
```

`Scheduler` / `run_task_batch` / `repair_task_graph` / `scope_conflicts` / `checkpoint` 被**子代理多代理编排主链路**实际消费。它**不是**时间触发型定时器（那才是 XEYO 真正缺的），而是**多代理任务 DAG 调度器**。第一轮把"缺 cron 式定时任务"和"scheduler.py 未接线"混为一谈了。

> 顺带：这条错误同时存在于项目记忆文件里，本轮一并修正。

---

## 1. 设计范式总纲：两个第一性问题

两个仓库规模相近，但对"什么是这个系统里最难的问题"给出了完全不同的答案。这决定了后面 29 个系统的每一个设计。

### 1.1 XEYO：第一性问题是「模型注意力里出现了什么」

`AGENTS.md` 设计理念节把这条写成了引擎铁律，五条：只给信息 / 模型自决 / 限制只在执行层 / 能静默就不说话 / 弱模型护栏不做在引擎文本里。落到代码上是三种机制：

1. **引擎文本立法**：`python/prompt/system_prompt.py:9-11` 注释「引擎不向模型注意力注入任何纪律/建议/劝导文本——行为约束一律由执行层静默强制」。
2. **注入管线收口**：所有易变内容必须走 `pre_llm_inject.py`，且受 `T_NOW_BLOCK_REGISTRY`（20 块）+ `T_NOW_BLOCK_HARD_CAP=21` + `tests/test_t_now_block_registry.py` 四条用例机器执法。
3. **执行层强制**：不让模型看到约束，而是让工具**静默报错**（如 `missing_read: no prior Read for this path in this session`）。

代价：引擎是**不可替换的单体**，任何行为变化都要改引擎代码。

### 1.2 dsh：第一性问题是「这一块能不能被换掉」

`docs/architecture.md:13`：「There is no privileged core to patch」——连 agent loop 本身都是插件。落到代码上：

1. **68→69 个服务缝**（本轮实测 `docs/capability-seams.md` 70 行、69 个唯一 `ctx.<name>`）：`ctx.tools`、`ctx.llm`、`ctx.fs`、`ctx.shell`、`ctx.sandbox`、`ctx.sessions`、`ctx.agentLoop`…
2. **注册即 effect**：`ToolRuntime.register()` 走 `this.layers.effect(...)`，返回 disposer，插件卸载自动解绑（`core/tools/src/index.ts:1028-1053`）。
3. **组合三层**：Profile（5 档）→ Bundle → 用户 `cordis.patch.yml` → `--patch`。

代价：任何"全局纪律"都无处安放——没有白名单，没有硬顶，谁都能往上下文塞东西；只有 `model-visible ⟺ logged` 一条可审计性底线（`architecture.md:111`）。

### 1.3 三分法对照

| 设计维度 | XEYO | dsh |
|---|---|---|
| **复杂度放在哪** | 信息是否应该进入注意力 | 结构是否可被替换 |
| **一致性靠什么** | 磁盘 transcript 权威 + 投影函数重算 | 事件日志即真相 + 运行时不变量校验 |
| **失败姿态** | keep-last-good（坏 JSON 保留上一份好配置）+ 静默降级 | fail-loud（配置错误直接炸）+ fail-closed（沙箱不可用即拒绝执行） |
| **扩展方式** | 编译期枚举 + 配置开关（三条固定扩展面） | 运行期挂载/卸载 + effect 回收 |
| **一句话** | 一个**策略引擎** | 一个**运行时内核** |

下面 29 个系统，都是这三分法在不同层面上的投影。

---

## 2. Agent 主循环

### 2.1 dsh：turn / step 双循环 + 可替换的 loop

**抽象**：`AgentLoop`（`core/agent-loop/src/index.ts:359`）→ `createAgent`/`resume` → `Agent.turn()`（`agent.ts:258`）。

**数据流**（精确到函数）：

```
turn(turn:number)                                   agent.ts:258
  ├ while true:
  │   ├ preStep(target, {turn, step})                agent.ts:237
  │   │   └ ctx.waterfall('agent/pre-step', {messages: claimed, ...})   agent.ts:247
  │   │        → decision: reject | {assembly, startsRequestSeries}     agent.ts:254
  │   │        assembly = await systemPrompt.assemble(...)              agent.ts:242
  │   ├ step(assembly, startsRequestSeries)          agent.ts:344
  │   │   ├ buildRequest(turn, step, assembly.tools, renderPrompt(assembly),
  │   │   │              session.deriveMessages(), ...)                 agent.ts:353
  │   │   ├ llm.stream(request) / preparedCall.stream(request)          agent.ts:374
  │   │   ├ session.append('assistant/message', {...})                  agent.ts:460
  │   │   ├ 无 tool-call → return {kind:'completed'}                    agent.ts:471
  │   │   └ executeToolCalls(...)                    agent.ts:472 → tool-calls.ts:60
  │   │        ├ runGroup(...) 有界并行池             tool-calls.ts:122,200
  │   │        ├ parallel 整组并行 / exclusive 成栅栏  tool-calls.ts:90
  │   │        ├ commitReady 按 model order 提交      tool-calls.ts:147
  │   │        └ session.append('tool/result')        tool-calls.ts:282
  │   └ inbox.splice('next-step', ...) → 继续         agent.ts:474
```

**终止条件**（三条，`agent.ts:279-282, 311, 316, 471`）：① 无 tool call；② `inbox.nextStep` 空且 `turnEnds` 已置；③ abort 抛错。

**中断**：`AbortSignal` 贯穿 + `raceAbort`（`agent-loop/index.ts:150`）；`cancel()` 带归因 `{kind:'user'|'parent'|'hook'|'disposed'}`（`agent.ts:146-152`）。**恢复**：`resume`（`index.ts:831`）读持久化后由 `interruptedTurnClosers` 补 closers（`index.ts:878`）——即"把上次没写完的收尾事件补齐"，而不是重放。

**设计要点**：`ctx.agentLoop` 本身是 seam；`step` 是**持久事件**（`step/start`/`step/end` 入日志）。这两条合起来意味着"换一个主循环实现"和"回放任何一步"都是被支持的。

### 2.2 XEYO：单 generator + 隐式阶段

**抽象**：一个 async generator `query_loop`（`engine/query_loop.py:726`），`while True`（`:796`）。没有 loop 抽象，没有 step 概念。

```
while True:                                                    query_loop.py:796
  ├ abort.aborted → StoppedEvent("aborted")                    :797
  ├ budget.prepare_next_turn() 失败 → forced_wrap_up + Stopped  :800
  ├ project_for_model (C0/C1/C2)                               :924
  ├ first_sniff 首轮嗅探 / _attach_turn_context 注入 T_now
  ├ prompt.build + tools.schemas()（_schemas_cache 冻结）      :1012-1018
  ├ model.stream → chunk.kind=="tool_use" → _admit_tool_use    :1141-1157
  ├ run_tools_partitioned / tools.run(...)                     :1893
  └ store.append(tool_result_message) → 下一轮
```

**终止**：aborted / budget_usd / max_turns / token budget / 无 tool_uses → `FinalEvent`（`:1540`）/ Plan 审批（`:1437-1538`）。

**并发**：`late_task`/`early_task` 两组 asyncio task + `result_q` 投递 + `wake` event（`:1737-1769`）；只读工具早并发（`_admit_tool_use`）；硬上限在编排层信号量（默认 10，`budget.py:21`）。

**中断恢复**：`except Aborted` → `_fill_missing_tool_results` + `StoppedEvent`（`:1801-1810, 1829-1838`）——**补齐缺失的 tool_result 以维持配对**；`_repair_unpaired_tool_calls`（`:795`）同源。`ensure_before` 让 rewind Before 快照与首轮 stream 重叠（`:744`）。

**粘性 vs 重置**：`schemas_json_cache` 跨 turn 冻结；`repeat_guard`/`zero_hit_tracker`/`result_fold` **每次 submit 重建**（`:774-785`）——这是"哪些状态属于会话、哪些属于这一轮"的显式划分。

### 2.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 循环本身 | seam（可换实现） | 硬编码在 `query_loop.py` |
| 阶段边界 | turn/step 两级且**入日志** | 隐式，靠函数调用顺序 |
| 拦截点 | 命名 waterfall（`agent/pre-step`/`agent/request`/`llm/stream`） | 代码内联 guard |
| 工具输出解析 | 结构化 `block.type==='tool-call'` | 结构化 `chunk.tool_use` + **XML 兜底**（`xml_tool_call.py:99`） |
| 并发语义 | 有界池 + exclusive 栅栏 + 按模型顺序提交 | asyncio 双队列 + 信号量 |
| 中断后 | 补 closers（保证日志闭合） | 补 tool_result（保证配对闭合） |

XEYO 的 XML 兜底是 dsh 没有的——这是为弱模型准备的执行层机制（模型把 tool call 写成 XML 文本时的抢救），符合"限制只在执行层"的定位。

---

## 3. 会话数据模型与持久化

这是两端**结构差异最大**的一处，也是第一轮已点出、本轮把设计机理讲透的一处。

### 3.1 dsh：事件溯源（event sourcing）

**真相源** = append-only `SessionEvent` 日志；模型历史是**投影**出来的。

- **事件词汇表**：`KNOWN_SESSION_EVENT_TYPES`（`core/session/src/known-event-types.ts:22-74`）共 73 个类型。
- **model-visible 只有 3 类**：`user/message`、`assistant/message`、`tool/result`，且必须带 `surfaceOp` 标记（`surface.ts:22-45`）。判定函数 `deriveEventMessage`（`surface.ts:90`）：非 surface 事件（turn/step 边界、`assistant/attempt`、`feedback/record`、`session/title`）返回 `null`（`surface.ts:117-119`）。
- **投影算法**：`foldSurface` 重放（`surface.ts:400`），`append` 推节点、`replace` 切片替换（`surface.ts:381-383`），增量由 `SurfaceManager._processDelta`（`surface.ts:417`）。
- **版本机制**：`SESSION_FORMAT_VERSION = 2`（`core/session/src/types.ts:86`，本轮已复核字面值）；header 校验在 `index.ts:101-103`；旧日志升级走**相邻迁移链** `createSessionFormatChain`（`session-format/src/chain.ts:38`）+ `defineSessionFormatMigration`（`chain.ts:21`）。
- **未知事件怎么办**：不按事件名注册，而是必须带 `ignorable` 标记，否则拒绝读整条日志——理由见 `known-event-types.ts:14-20`：「silently skipping … would reconstruct a wrong session」。
- **`assistant/message` 内嵌该步精确的压缩流** `AssistantStreamRecord[]`；失败的尝试进 `assistant/attempt`——**不伪造模型历史**。

**持久化**：

- append-only、**从不重写**（`session-persistence/src/index.ts:117-133`）。
- **崩溃安全**：torn physical tail 截断后不返回、append 前 truncate（`:117-119`）；`flush` 是持久性屏障（`:121-129`）。
- **resume 语义**：取 write 所有权 + 补 closers（`agent-loop/index.ts:878`）。
- **投影缓存**：`session-projection-cache` write-behind（计数/间隔触发 + 三个强制点 create/turn-end/dispose，`projection-cache/index.ts:301-352`），且**写前先 flush 日志**保证缓存不领先（`:256`）。

### 3.2 XEYO：消息级 transcript

- **格式**：`message_to_dict`（`session/record_transcript.py:205`）→ `{id, role, content, tool_call_id, name, narration?, interrupted?, ts}`。**消息级，非事件级**。
- **路径**：`~/.xeyo/sessions/<id>.jsonl`（`session/persistence.py:60`），按 `id` 去重（`record_transcript.py:266,312`）。
- **权威关系**：磁盘 transcript 权威；常驻引擎内存经 `QueryEngine.replace_history` 整表对齐（`server/session_pool.py:319`）。
- **写入**：后台线程批量追加（`record_transcript.py:122-167`）+ 每批 `os.fsync`（`:156`）+ 同步直写路径也 fsync（`:282`）；轮转保留 2 代、原子 `os.replace`（`:65,95`）。
- **特殊 role**：`role=ui_thought` 行**仅供 UI**，engine hydrate 时跳过（`:361-368`）——这是"同一份日志承载两种消费者"的一处显式处理。
- **rewind**：v3 热路径（默认）与 v2 兼容（`rewind/service.py` / `server/session_pool.py:312-327`）；v2 = 整引擎丢弃，v3 = 热路径精细对齐（复位 compact 游标 / C2 摘要 / 锚点）。`revision.py` 的 `_append_json` 同样 fsync（`rewind/revision.py:43`）。

### 3.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 真相源粒度 | 事件（73 类） | 消息 |
| 能否逐字重建"模型当时看到什么" | **能**——`request/header` 入日志 + runtime invariant 强制 | **不能**——靠投影函数重算，日志不含请求头 |
| 失败的模型尝试 | `assistant/attempt` 保留 | 无记录 |
| 版本迁移 | vN 代际 + 内存迁移 + 并排发布，**永不改写旧代** | 轮转 2 代 |
| fork | `SessionStore.fork()` + seed 前缀 + `inheritedEventCount`，禁止跨 open turn（`session/src/index.ts:1176-1234`） | `POST /v1/sessions/{id}/fork` |
| 投影一致性 | `replace` 可改写历史中间段（压缩用） | `compact.project` 在内存 history 上 transform |

**可借鉴性**：dsh 的"日志 = 唯一真相 + 请求头入日志"是**唯一能证明模型看到过什么**的方案。XEYO 的 rewind 与 dsh 的 fork 是两种不同的"回到过去"：rewind 回滚**工作区文件**（dsh 没有），fork 分叉**会话**（XEYO 有但轻）。

---

## 4. 上下文投影与 KV 前缀保护

### 4.1 dsh：投影是纯函数 fold，前缀天然不动

- 决定者：`session.deriveMessages()`（`agent.ts:358`）+ surface 层。
- **KV 保护是结构副产品**：surface `replace` 只改中间节点，头部前缀逐字节不动（`surface.ts:381-383`）；压缩 `summarize` **复用同一个 system prompt / tools / messages**（`compaction-basic/src/index.ts:229-231`）。
- 作者的显式约束（`compaction/README.md:160`）：compaction "shrinks derived history, never the system prompt, tools, or session prefix"。
- 其余不变量：`buildRequest` 用 frozen request（`agent.ts:485`）；`assistant/message` 不能带 `sourceEventSeqs`（`surface.ts:226-228`）；`tool/result` 替换仅改 content（`surface.ts:299-330`）。
- 投影自身的纪律（`surface.ts:96-102`）：「Do NOT re-add per-type framing … framing is caller-owned」——投影层**逐字透传**，不加装饰。

### 4.2 XEYO：投影是显式 transform，靠游标保稳定

- 决定者：`compact.project(history, frozen_until)`（`engine/compact.py:125`），作用在 `as_api_messages` 之上。
- 稳定机制：`boundary = max(0, min(frozen_until, len))`，**未冻结消息不改写**（`compact.py:135,238`）；保尾 K 默认 3 轮（`keep_tail_cut`，`compact.py:95-114`）；C0 单条 tool_result 截断 8192 字符（`MAX_TOOL_RESULT_CHARS`，`compact.py:24`）。
- 作者的设计意图（`compact.py:5-6`）：「本函数不自行决定窗口，保证两次 C1/C2 之间投影字节稳定」。
- 增量 `project_incremental` 与全量投影**逐字节一致**（`compact.py:286-310`）——这是可测试的设计目标，不是巧合。
- 左段极简（`query_loop.py:822`「system 左段保持稳定」）。

### 4.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 投影实现 | 事件 → surface → messages 纯函数 fold | 消息列表 → C0/C1 占位 transform |
| 前缀稳定靠 | 追加式结构（不动头） | `frozen_until` 游标 + 保尾区 + 左段极简 |
| 谁可以改写历史 | 只有压缩（在 lock bracket 内） | 只有 C1/C2 投影 |
| 是否显式关心 KV | 否（下沉到 provider 库的 cache 声明） | **是**（引擎层显式政策） |

> 注意：dsh 也**没有**在请求侧下发 `cache_control` 全局断点；它的 `cacheControlFormat`/`supportsLongCacheRetention` 是 `llm-pi-ai` 的**模型目录声明**，由第三方库（pi-ai）决定怎么用。XEYO 的 `system_prompt.py:46-48` 则是引擎作者手写的"Date/Model 刻意不进左段"。

---

## 5. 压缩与预算

### 5.1 dsh：压缩是 seam，双触发，可组合

- **触发**：自动注册于 `agent/pre-step` 的 pressure（`compaction-basic/src/index.ts:148`）+ `agent/request-error` 的 context-overflow（`CONTEXT_WINDOW_EXCEEDED_CODE`，`:180-184`）。阈值 `thresholdTokens = resolveCompactSpec(policy, contextWindow)`（`:304`），`totalTokens < threshold` 直接不压（`:305`）。
- **算法**：`selectCompactableRange` + `compactRegion` 把 surface 区间**替换为单个 summary 节点**（`compaction/src/index.ts:164`）；边缘必须 `toolPairingBalanced`（`:154`），否则不成对会破日志语义。
- **续接**：replace 落在 **lock bracket** 内，崩溃留孤儿锁**可检测**——`compaction/README.md:95` 的原话：「The replacement sits inside the lock bracket, so a crash … leaves a detectable orphaned lock rather than a `compaction/end` that falsely claims success.」`deriveMessages` 把 summary 渲染为 user 消息。
- **可组合性**（作者原话 `compaction-basic/index.ts:279-282`）：「Pruning is optional so compaction-basic remains independently composable.」
- **没有的东西**：**无 token 预算、无死线、无成本上限**。`ctx.tokenMeter` 是**启发式估算且仅用于重放测量**（`token-meter/src/estimate.ts:43` 用 `CHARS_PER_TOKEN`），`TokenUsage` 随 `assistant/message` 事件落库，无独立账本。

### 5.2 XEYO：C0/C1/C2 三档确定性压缩 + 多重预算护栏

- **压缩**：C0（单条 tool_result 截断 8192）→ C1（占位/折叠）→ C2（LLM 摘要，**默认关**，仅首压前预热，`query_loop.py:836-847`）。压力触发：厂商上下文达 95% 强制 C2（`maybe_force_compact_on_pressure`，`:848-850`）。
- **预算**：`BudgetTracker`（`budget.py:100`）——`max_turns` 默认 256、`max_tool_calling` 默认 64（`budget.py:19-24`）、grace 3 轮（`:25`）、墙钟硬停**默认关**（`:37-44`）。
- 作者对该字段的定位（`budget.py:20-24`）：「真正的并发上限由编排层信号量控制…这里只是总执行数的高护栏」。
- 收尾窗：预算耗尽 → `forced_wrap_up` + `wrap_up` T_now 块 + `runtime_budget` 块。

### 5.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 压缩触发 | pressure + context-overflow 双自动 | 压力阈值 + 显式 `/compact` |
| 压缩产物 | surface 区间 → 单个 summary 节点（可 replace） | 确定性占位（C0/C1）+ 可选 LLM 摘要（C2，默认关） |
| 崩溃语义 | lock bracket + 可检测孤儿锁 | 无锁；靠投影函数幂等 |
| 预算/死线 | **完全没有** | turn / tool / token / usd 四重 + 收尾窗 |
| token 计量 | 启发式，仅重放用 | 厂商权威 usage 为准，投影估算兜底（`query_loop.py:1276-1284`） |

**这是 XEYO 明显更强的一面**，且强在"可运营性"：一个要长期跑、要控成本的本地 Agent 必须有预算；dsh 作为 developer preview 的 harness 可以不关心钱。

---

## 6. System Prompt 组装

### 6.1 dsh：段注册表 + 严格插值 + 独立动态上下文序列

- **静态段**：`ctx.systemPrompt.section()` 按 `order` 升序拼接（`core/system-prompt/src/index.ts:121-152` `SECTION_ORDERS`；装配 `:432-441`）。内置：`harness:identity`(−1000)、`deployment:persona`(0)、工具段 `TOOL_READ 1100` … `TOOL_SUBAGENT 2800`。
- **身份句极简**：`You are an AI agent powered by DeepSeek Harness.`（`:409-413`）。
- **动态上下文序列**：独立的 `context()`（`:77-84`、`:467-476`），渲染成单独一段 `Current runtime context…supersedes earlier…`（`:275-306`），夹在静态段之后——**易变内容与静态段物理分离**。
- **严格插值**：`{{variable}}` 未定义即抛（`:263-346`），作者原话「Malformed, unknown, or undefined references throw」——把 prompt 变量当**强契约**而非模板。
- **环境信息不注入**：全仓 grep `git status|process.platform|os.platform` 命中项全在测试与平台分支，**无一处进 prompt**；cwd/OS/日期都不在 system 左段。时间由 `context/time-context` 插件以**插件身份的 user 消息快照**注入（`time-context/src/index.ts:180-220`），且 opt-in + 按 `refreshIntervalMs` 节流。
- **每个注册返回 disposer**：`section/context/tools/variable` 注册都返回 Cordis effect（`:432/467/499/515`），插件卸载自动解绑。

### 6.2 XEYO：左段锁死三件套 + 只 append 不替换

- 左段 `[IDENTITY, CWD, FENCE_POLICY]`（`prompt/system_prompt.py:23-25, 65-69`）；`XEYO.md` 经 instructions 注入（`:84-92, 119, 164`）。
- **显式保 KV 前缀**：注释明写 Date/Model **刻意不进左段**（`:46-48`，避免换日/换模型打爆前缀），需要时刻用 `getTime` 工具。`MEMORY.md` 索引也不进左段（模块 docstring `:6`）。
- `custom_system_prompt`/`append_system_prompt` **只 append 不可整段替换**（`:132-206`）。
- 装配 seam = `PromptAssembler` 的会话级 memo（`assembler.py:26-98`，键含 `instr_sig`）。
- **无 `{{var}}` 插值**——没有变量语法，也就没有"未定义即抛"这类契约。

### 6.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 分段机制 | 注册表 + order 排序，插件可增删 | 硬编码左段 + append 区 |
| 动态内容位置 | 独立 runtime-context 快照（`supersedes` 语义） | 全部走 T_now 注入管线（不进 system） |
| 变量插值 | 严格，未定义即抛 | 无 |
| cwd / OS / 日期 | **全部不注入**，交给工具 | cwd 进左段；OS/日期/git 不进 |
| 保前缀手段 | 静态段/动态段物理分离 | 刻意省略易变字段 |

两者都"保前缀"，但 dsh 是**分离**（把易变内容挪出 system），XEYO 是**省略 + 收口到 T_now 管线**。

---

## 6.5 逐轮注入管线：T_now vs「无治理」——两端差距最大的注意力机制

这是 XEYO 唯一**有完整治理层**、dsh **完全没有对应物**的一处。因为它在 XEYO 侧本身就是"引擎铁律"的落地机制，值得单独立节。

### 6.5.1 XEYO：双声道 + 硬准入 + 机器执法

**两条声道**（`prompt/t_now_strategy.py:1-21`）：

| 档 | 做法 | 语义 |
|---|---|---|
| `env_channel`（默认） | 全部易变块装进一对**仅存于投影**的 `assistant(tool_use xeyo_env_notice) → tool_result` 伪对，尾插 | 作者原话（`:4-8`）：「tool_result 是模型训练出来的『环境数据声道』……不再与用户意图同层（**根治说话人混淆**）」 |
| `legacy` | 块以文本尾插末条 user | 回退档 |
| `skip` | 厂商以结构类 4xx 拒绝伪对时**宁可本轮不注入也不回落 legacy** | 保声道纯度 |

优先级：会话/请求显式 > `XEYO_T_NOW_STRATEGY` 环境变量 > 默认（`t_now_strategy.py:19-21, 54-62`）。声道常量 `ENV_TOOL_NAME = "xeyo_env_notice"`（`:110`）。

**硬准入四件套**（`pre_llm_inject.py:815-830`）：

```
T_NOW_BLOCK_HARD_CAP = 21     # 23→21：裁决 5 删掉 stale_xeyo_md / nested_change
T_NOW_BLOCK_REGISTRY: dict[str, dict[str, str]]   # 实测 20 条
T_NOW_TOTAL_BUDGET = 6000     # 总预算
T_NOW_INVENTORY_MAX = 2500    # inventory 类预算
```

三条规则写在代码注释里（`:818-824`）：① 每个装配点必须带标记且已登记；② 登记数硬顶 = 存量（加一必须删一，调高需在 commit message 给预算不破的理由）；③ 每条登记必须回答「为什么必须在上下文」，答不出的先问「**能不能不进上下文**」。

**执法方式本轮复核（比注释更强）**：装配点统一走 `_tag_block(tagged, "名", ...)`，测试直接断言**源码里不存在裸 `tagged.append(`**（仅助手本体允许一次），再正则提取全部 `_tag_block` 名做**双向核对**（`tests/test_t_now_block_registry.py`）：

```
test_hard_cap_not_exceeded                    # 登记数 ≤ 21
test_every_append_site_is_marked_and_registered  # 装配点全登记、无未登记名、无重复标记
test_registry_has_no_dead_entries             # 登记表不腐烂（每个登记名都能找到装配点）
test_registry_entries_are_complete            # klass 合法 + why 非空
```

即"改名/漏登记/登记不用"三种腐烂都有测试兜底——**登记名是真实代码参数，不是注释**。

**20 个块全清单**（`pre_llm_inject.py` 登记表 + 装配点，本轮实测）：

| # | 块名 | 类别 | 触发条件 |
|---|---|---|---|
| 1 | `continue` | directive | 工具续写轮（`ends_with_tool_result`） |
| 2 | `mode_instructions` | directive | Ask/Plan/批准计划模式合同 |
| 3 | `wrap_up` | directive | 预算/回合耗尽收尾窗 |
| 4 | `runtime_budget` | directive | 预算瞬时通知 |
| 5 | `budget_mirror` | directive | 仅墙钟死线会话每轮稳态镜像 |
| 6 | `multi_agent_hint` | directive | 多代理分解/汇总 |
| 7 | `repeat_guard` | directive | 轮内防复读（逐 submit 重置） |
| 8 | `nested_instructions` | inventory | 子目录 XEYO.md 按需加载 |
| 9 | `compact` | directive | 输出/写码压缩开关生效 |
| 10 | `mcp_required_warn` | event | required MCP 启动失败 |
| 11 | `reconcile_events` | event | 工具面/技能目录变更（drain） |
| 12 | `peer_presence` | event | 多会话交叉活动（drain） |
| 13 | `file_conflict` | event | 触碰文件被他会话写入 |
| 14 | `browser_preview` | inventory | 预览页 URL |
| 15 | `runtime_mode_snapshot` | directive | 审批模式活状态（supersedes） |
| 16 | `agent_settlement` | event | 子代理结算（drain） |
| 17 | `goal` | directive | 仅 blocked / pending_complete |
| 18 | `resume_directive` | event | 续跑富化指令（投影-only） |
| 19 | `pending_jobs` | directive | 后台 job 完成补投 |
| 20 | `skill_preinvoke` | directive | 用户 `/name` 直呼技能 |

装配入口 `run_pre_llm_inject`（`:1030-1358`）：按序 `_tag_block` → **类感知预算截断**（`_trim_tagged_blocks`，`:990-1027`）→ 按声道分流。另有一条注意力保护：**模糊指代轮整类静默 INVENTORY**（`:1312-1315`）。

### 6.5.2 dsh：没有等价物

dsh 的易变内容只有两条去处：① `systemPrompt.context()` 的运行时快照（`SUPERSEDES` 语义，见 §6.1）；② `time-context` 插件 prepend 一条 user 消息（`time-context/src/index.ts:210-218`）。全仓 grep **无**块登记表、无硬顶、无白名单、无机器执法测试、无"伪造 tool 对"声道。

### 6.5.3 设计分歧与判断

| 维度 | dsh | XEYO |
|---|---|---|
| 有没有"什么可以进上下文"的门 | **没有** | 有：登记表 + 硬顶 21 + 逐条理由 |
| 谁决定易变内容的位置 | 插件自己（section / context / prepend user） | 引擎统一收口到 T_now 管线 |
| 防说话人混淆 | 无此概念 | `env_channel` 伪造 tool 对 |
| 执法 | 无 | 4 条测试 + 禁用裸 append + 双向核对 |
| 代价 | 插件自由，但上下文可能被任意污染 | 引擎僵化，加一个块要删一个块 |

这是两种自由观的正面冲突：dsh 把"能不能往上下文塞东西"的权力**下放给插件作者**，只保留"塞了必须能重建"的底线；XEYO 把这条权力**收归引擎**，用硬顶和测试把"注意力预算"当成稀缺资源管理。dsh 的做法在生态繁荣后必然出问题（谁都能塞），XEYO 的做法在需要快速扩展时必然难受（加块要审批）。**两边都对，取决于你赌哪个未来。**

---

## 7. 工具系统（抽象 · 注册 · 生命周期）★重点样例

用户点名要以工具系统为例，所以这一节写到接口级。

### 7.1 dsh：ToolDefinition = 行为 + 结构化输出 + UI 投影 + 超时

```ts
// packages/core/tools/src/index.ts:214-280
export interface ToolDefinition extends ToolSchema {
  readonly output: ToolOutputDefinition          // {schema, render, presentationMeta?}
  execute(args: unknown, exec: ToolRunContext): Promise<unknown>
  finalizeContent?(exec, result): ContentBlock[] | undefined
  timeoutMs?: number                              // 经 timeout-policy 包装，绝不下发模型
  isConcurrencySafe?(args): boolean
  presentCall?(args): ToolCallView | undefined
  presentResult?(args, result): ToolResultView | undefined
}
```

- **入参 schema**：自研 DSL `defineTool`（`schema.ts:545-617`）编译为 JSON Schema；execute 内 `validate` 失败抛 `ToolArgsError`。
- **结果类型**：`ToolResult {content, isError, meta?}`（`index.ts:283-295`）；**结构化输出**靠 `output.render(args, value)` 投影，`meta` 持久化进 `tool/result` 事件。
- **四条正交关注点被塞进了同一个接口**：模型可见 schema（`ToolSchema`）、执行（`execute`）、模型可见内容后处理（`finalizeContent`）、UI 呈现（`presentCall`/`presentResult`）。这是"一个工具 = 一个包"能成立的前提。
- 变体：PowerShell 走独立 `tool-pwsh`；PTY 持久会话 `tool-bash-persistent`/`tool-pwsh-persistent`；流式进度走事件，不另立 execute 变体。

### 7.2 XEYO：Tool Protocol + 单表元数据

```python
# python/tools/base_tool.py:23-43
@runtime_checkable
class Tool(Protocol):
    name: str
    def schema(self) -> dict: ...
    async def execute(self, input, abort) -> ToolResult: ...
    @staticmethod
    def is_read_only() -> bool: ...
    @staticmethod
    def is_concurrency_safe() -> bool: ...
```

- `ToolResult` dataclass（`base_tool.py:9-21`）= `content / is_error / todos / images / metadata / ui`。
- **元数据单表** `TOOL_META`（`tools/meta.py:24-48`）：`read_only / concurrency_safe / policy / subagent_ok / output_budget / exposure`。作者在表头的定位（`meta.py:1-4`）：「工具元数据单表 — policy / catalog / subagent / schema 短描述的唯一来源。新增工具：在此登记一行，再在 catalog 挂工厂；**勿再手抄 READONLY / 白名单**。」
- **schema 手写**：各工具 `schema()` 直接返回 dict（手写 JSON Schema），无 DSL、无编译期校验。
- **`exposure` 字段**是 dsh 没有的概念：`meta.py:76-78` 的 `hidden` 用于 L3 offload 工具——**注册进注册表但不进主 schemas**，模型只能通过 offload_read 回读。

### 7.3 注册与生命周期

| | dsh | XEYO |
|---|---|---|
| 注册 API | `ctx.tools.register(definition)`（`index.ts:1028-1053`） | `ToolRegistry.register`（`tool_registry.py:103-105`） |
| 生命周期 | 经 `this.layers.effect(...)`，**返回 disposer，卸载自动解绑** | 进程启动时一次性注册，无常驻增删 |
| 作用域 | scoped 工具 **shadow** globals（`view()` 逐层合并，`index.ts:1144-1186`）；`restrict()`/`guard()` 同机制（`:1062-1107`） | 全局单表 |
| 组合 | bundle/profile + `cordis.patch.yml` | `catalog.py` 的 `ENABLED_TOOL_ENTRIES`（`:261-287`）+ `XEYO_BENCH_MINIMAL` 裁剪（`:359-370`） |
| 缓存 | 无（`view()` 每次派生） | `_schemas_cache`，会话内冻结 |
| 启动自检 | `verify-tool-catalog` 机器执法 | `_register_factories` 硬失败（`catalog.py:308-352`）+ `_assert_names` 保证 ENABLED == meta.enabled（`:485-492`） |

**加一个工具的 SOP 对照**

dsh（5 步）：
1. 新建 `packages/<组>/<tool>/src/index.ts`，`defineTool({...})` 并实现 `output`；
2. 包内 `ctx.tools.register(...)`；
3. 需要系统提示段则写 `prompt.ts` 经 `ctx.systemPrompt` 注册；
4. 在目标 bundle 的 `cordis.patch.yml` 挂载该包；
5. 更新 `docs/tool-catalog.md`（`verify-tool-catalog` 执法）。

XEYO（4 步）：
1. `tools/<name>_tool/` 实现 `Tool` 协议（`schema()` + `execute()`）；
2. `meta.py` 的 `TOOL_META` 登记一行；
3. `catalog.py` 的 `ENABLED_TOOL_ENTRIES` 加 `(name, _factory)`；
4. 启动自检会强制"名 / flag / meta / enabled"四者对齐，不对齐**硬失败**。

**设计意味**：dsh 的第 4 步（bundle patch）是"可组合性"的体现——同一个工具包，不同 profile 可以选择装或不装；XEYO 的第 3 步是"枚举式启用"——所有可用工具写死在一个列表里，靠常量裁剪。

### 7.4 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 结果结构化 | `output.schema` 一等公民 + `render` 投影 | `metadata` 松散承载 |
| UI 呈现 | 工具自带 `presentCall/presentResult` | GUI 侧按 `toolActivity.ts` 动态生成 |
| 超时 | `timeoutMs` per-tool，`timeout-policy` 包装 | **无 per-tool 超时**，只有 AbortController |
| 缓存/冻结 | 无，实时派生 | `_schemas_cache` 会话内冻结（红线） |
| 隐藏工具 | 无等价概念 | `exposure="hidden"`（offload L3） |

---

## 8. 工具执行管线

### 8.1 dsh：命名事件瀑布，4 个可拦截点

`docs/tool-execution-pipeline.md` + `core/tools/src/index.ts`：

```
tool/call（事件） → presentCall（UI）
  → tools/pre-execute  (waterfall: hooks + permission + sandbox + ctx.approval 挂起)
  → 单调 guards        (tools.guard，deny/abstain，身份受保护)
  → tools/execute      (waterfall: timeout / retry / metrics 包装) → tool body
                                                → fs/write-intent | fs/edit-intent
  → tools/post-execute (waterfall: accept / block / replace / add context)
  → finalizeContent
  → tools/result       (观察者，frozen)
  → tool/result（事件）
```

- 事件定义：`index.ts:144 / 155 / 167 / 189`。
- **不变量**：`tools/result` 发布前 exec 与 outcome 必须 **frozen**（`invariant.ts:23-28`）。
- **可拦截点 = 4 个 waterfall + 单调 guards + `ctx.approval`**。任何第三方插件可以在不碰工具实现的前提下：改参数、拒执行、改结果、加补充上下文、加超时。
- 作者对权限归属的显式设计（`shell/tool-bash/src/index.ts:6-7`）：`TODO(permissions): deployment policy belongs in tools/pre-execute and sandboxing executors`——**权限属于管线，不属于工具**。

### 8.2 XEYO：函数内联链 + 单钩子接缝

```
_admit_tool_use（占配额 / early 只读并发 / flush transcript）      query_loop.py:1047
  ↓ chunk.kind=="tool_use"                                       query_loop.py:1155-1157
tool_registry.run                                                  tool_registry.py:296
  ├ readonly_gate
  ├ PreToolUse 钩子（extension/hooks.py，默认关）
  ├ evaluate_policy → ALLOW / Bash 路由 / DENY / ASK
  ├ _execute_audited（写 tool.started / tool.finished 审计）
  ├ _apply_output_budget（超 16000 落 spill）
  └ PostToolUse 钩子
  ↓
store.append(tool_result_message) → SSE
```

- 权限判定在 `permissions/policy.py:evaluate_policy`（`:1319`）；工具侧只看到中性结果型错误 `Permission denied: {reason}`（`tool_registry.py:453-459`）。
- 作者对"策略先于工具"的纪律（`tool_registry.py:148`）：「策略层已 ALLOW / skip_ask：工具内 check_permissions 不得再把 ASK 降成 DENY。」

**旁路清单**（这是 XEYO 结构上最需要警惕的一面）：

| 旁路 | 位置 | 绕过了什么 |
|---|---|---|
| `server/workspace_fs.py` 直写 | `workspace_fs.py:39-42`（需 `XEYO_WORKSPACE_FS_WRITABLE=1`） | 不穿权限、不穿 rewind，仅 `workspace_fs.{action}` 审计（`:44-56`） |
| 后台 bash job | `bash_tool.py:588-622` → `server/job_registry.py` | 拿到 job id 后脱离 tool-call 信号独立运行 |
| `offload_read` + `spill.py` 外部化 | `tools/spill.py`、`meta.py:76-78` | 结果不进主 schemas，走 L3 隐藏工具回读 |
| Bash 改文件 | `bash_tool.py:57-112` | 第二条写盘路径，靠 `_invalidate_search_caches` 补救 |

作者对旁路的态度是**明确的**（`workspace_fs.py:35-38`）：「默认拒绝写入…必须由用户显式开启才能承担写/删风险」——即：知情地承认旁路存在，用开关而不是用架构封死。

### 8.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 管线形态 | 命名 waterfall（可拦截、可观测、可测） | 函数内联 + 1 个钩子接缝 |
| 可拦截点 | 4 + guards + approval | 3（Pre/Post/PermissionRequest，默认关） |
| 结果冻结 | `tools/result` 前强制 deep-freeze（不变量） | 无 |
| 权限位置 | 管线（pre-execute），工具无关 | 注册表 run 内，但工具可重入 |
| 旁路 | 无（一切经 `ctx.fs`/`ctx.shell`） | 4 条（1 条默认关） |

---

## 9. 权限与审批

### 9.1 dsh：两个旋钮，权限 ≈ 隔离强度

- **两旋钮**：`sandbox-mode`（read-only / workspace-write / danger-full-access）× `approval-policy`（ask / never）。预设：`workspace-write(ask)`、`danger-full-access(never)`（`interaction/permission-presets/src/index.ts:170-179`）。
- **判定顺序**（`interaction/user-approval/src/index.ts:258-298`）：

```
signal.aborted                          → 'cancelled'
effectivePolicy == 'never'              → 'rejected'   （先于 waterfall，确定性）
approval/request waterfall              → 无 answerer → 'unavailable'（fail closed）
```

- **挂起即入日志**：`request()` 写 `approval/asked` + `approval/decided` 事件（`:217,224`），且**必须处于 open turn**（`:77-84`）——审批是可回放的历史事件，不是旁路状态。
- **没有 grant 指纹**：审批是**一次性**的。身份标识用 `agent.session`。
- 作者对预设的定位（`permission-presets/src/index.ts:48-54`）：「Records the selected preset as durable, **log-only** user intent… stays out of the model transcript」——即：记录用户意图但**不给模型看**。这一点与 XEYO 的 T_now `runtime_mode_snapshot` 块（把审批模式快照给模型）**取向相反**。

### 9.2 XEYO：工具级三值 + grant 指纹 + HTTP 挂起

- **词表**：`ASK / ALLOW / DENY`（`permissions/policy.py:54-68`）；模式 `always / risk / never / allow`（`:75`）。
- **判定顺序**（`evaluate_policy_impl`，`policy.py:1391-1429`）：

```
deny_tools 命中            → DENY
mcp__*                     → 走 Mcp 网关
_ALWAYS_ALLOW 命中         → ALLOW
_OUTBOUND_ASK 命中         → ASK
ASK 时查 grant 命中        → ALLOW（store.py:1336-1386）
```

- **grant 指纹 v2**：`"v2:" + sha256(["mcp-tool", 注册名])[:32]`，**参数不进指纹**（`store.py:444-456`）→ 对提示注入免疫；Bash 用命令前缀作指纹（`store.py:459-497`）。**DENY 不可被 grant 穿透**（`policy.py:1331` 守卫）。
- **挂起/恢复**：`PendingPermissionStore.create/resolve/wait`（`store.py:71/136/208`）+ HTTP `POST /v1/permission/resolve`（`server/routers/control.py:145`）；TTL 风险分级（`store.py:91-99`）。
- **审批记录**：`approval/*` 事件 + `audit/` 模块（JSONL，`audit/log.py:30-45`，经 `scrub_audit_fields` 脱敏）。

### 9.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 决策词表 | ask / never（策略）+ allowed-once / rejected / cancelled / unavailable（结果） | ASK / ALLOW / DENY |
| 主旋钮 | 沙箱模式（权限≈隔离强度） | 工具级授权（权限=谁能调什么） |
| 记忆性 | 一次性，无指纹 | grant 指纹（v2，参数免疫）+ TTL 分级 |
| 挂起记录 | `approval/asked`+`decided` 入 session log，**必须 open turn** | HTTP resolve + pending store |
| 模式是否告知模型 | **不告知**（log-only，明确不进 transcript） | 告知（T_now `runtime_mode_snapshot` 块） |
| DENY 语义 | 不适用（无 DENY 词） | 硬 DENY，grant 不可穿越 |

**安全模型不重叠**：dsh 关心"这行命令在什么隔离等级下跑"，XEYO 关心"这个工具这次调用被谁授权过"。两者可以叠加，但没有一方实现了另一方。

---

## 10. 沙箱与执行隔离

### 10.1 dsh：内核级四后端 + 云沙箱，fail-closed

**抽象**：`ctx.sandbox` 是一条能力缝，唯一接口是"约束 argv"：

```ts
// packages/sandbox/sandbox/src/index.ts:154-176
confine(argv, policy): ConfinedArgv
```

作者把语义写死了（`sandbox/src/index.ts:154-156`）：「**silent unconfined passthrough is forbidden**」；`sandbox-local/src/index.ts:5-6`：「Missing or unusable confinement **fails closed** rather than returning the original argv」。

- **策略词汇**：`SandboxMode = 'read-only' | 'workspace-write' | 'danger-full-access'`，per-call 承载（`SandboxPolicy` 带 `mode/workspaceRoot/sessionId`，`sandbox/src/index.ts:29-72`）。
- **平台矩阵**（`PLATFORM_CHAINS`，`sandbox-local/src/index.ts:159-187`）：Linux `[bwrap, landlock]` / macOS `[seatbelt]` / Windows `[windows-acl]`；强制等级 `bwrap/seatbelt/landlock = full`、`windows-acl = partial`（ACL 的 Everyone/硬链接边界）。
- **不可用即拒绝**：请求受限模式但无可用后端 → `SandboxUnavailableError`（`SANDBOX_UNAVAILABLE`，`sandbox/src/index.ts:124-144`）；`selectRunner` 无候选直接抛（`sandbox-local/src/index.ts:492-496`）。
- **消费侧**：`SandboxBashExecutor` 在 spawn 前 `confine(['bash','-c',cmd], policy)`，且有一条精细的优先级规则——「runner 启动失败（命令没跑）优先于 denial（约束生效并拦下）」（`shell/bash-sandbox/src/index.ts:88-114, 150-167`）。
- **策略默认值最保守**：`ctx.sandboxPolicy` 默认 `read-only`（`sandbox-policy/src/index.ts:111-117`），优先级 `显式 override > session 'sandbox/mode' 事件 > 部署默认`（`:163-170`）。
- **原生与云**：`native/landlock-run`（`@deepseek-ai/node-addon-landlock-run`，`LAUNCHER_FAILURE_EXIT=125`）；E2B 云沙箱（`packages/e2b/e2b/src/index.ts:77-81`，超时即删沙箱）。

### 10.2 XEYO：没有 OS 级沙箱，只有 Windows Job Object + 容器路由

- 全仓穷举 grep `landlock|seatbelt|bubblewrap|bwrap|sandbox-exec|Job Object|AppContainer`（排除 `.venv`）**只命中 Windows Job Object**，且作者明确拒绝 AppContainer：`bash_tool/win_job.py:1-4`「不做 AppContainer——会绊住本机 git/npm」。Job Object 提供的是**内存上限 + 超时整树杀**（资源限额），**不是隔离**。
- **TerminalBench 场景走 docker 容器路由**（这是评测旁径，不是产品通用能力）：
  - `XeyoHarborAgent.setup()` 从 trial 会话名推导容器名（`__env-main-1`），置 `XEYO_DOCKER_CONTAINER` 或 `set_container_override(cid)`（ContextVar 防共进程串线）——`TerminalBench/xeyo_harbor_agent.py:40-50, 100-115, 136-146`。
  - bash 工具读 `current_container()` → docker SDK `exec_run(["bash","-lc",cmd])`（named pipe 直连，零宿主 shell 依赖）——`tools/bash_tool/bash_tool.py:568-573` + `tools/container_routing.py`。
  - 容器路径下放开审批档 `XEYO_PERMISSION_MODE=never`，仅硬边界（密钥/策略/危险路径）仍由 policy 拦截（`xeyo_harbor_agent.py:127-130`）。

### 10.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| OS 级隔离 | 四后端 + 原生 addon | **无** |
| 云沙箱 | E2B | 无（容器仅评测路由） |
| 抽象 | `confine(argv, policy)` 单函数 | 无抽象 |
| 失败姿态 | fail-closed（宁可拒跑） | 不适用（无隔离层） |
| 第二道防线 | 有（内核） | 无；只有 `destructive_guard.py` 关键词级启发式 |
| 策略默认 | `read-only` | 权限模式默认 workspace-write（工具级） |

**这是 dsh 领先最大的一项**，且差距的性质是"缺一整层"：XEYO 的安全完全依赖"工具调用前判定"，一旦落到 Bash 内部（`rm -rf`、`curl | sh`），没有第二道防线。XEYO 自己也知道——`brainstorm` 级补救是关键词黑名单，属于启发式。

**注意一个反直觉点**：dsh 的 `fs-sandbox` 作者特意声明它**不是**安全边界（`fs-sandbox/src/index.ts:13-18`）：「This is containment, not a security boundary; kernel-grade isolation of untrusted CODE stays `ctx.shell`'s job」——即：文件围栏防误伤，内核沙箱防恶意，两者职责分明。这种"明确声明某一层不负责什么"的写法，正是 XEYO 的 `AGENTS.md` 铁律在做的事，只是 dsh 用在架构层、XEYO 用在注意力层。

---

## 11. 文件系统能力与策略

### 11.1 dsh：一切经 `ctx.fs`，三事件 + 两层守卫

**三角色**：

- Service Definition：`FileSystem` 抽象 + `fs/write-intent` / `fs/edit-intent` / `fs/observed` 三事件（`packages/fs/fs/src/index.ts:49-105`）。
- Provider `LocalFileSystem`：`writeText` 带**陈旧版本守卫**——`replaceIfVersion` 比对 observed version；`createIfAbsent` 落在已存在文件 → `FS_NOT_OBSERVED`（`fs-local/src/index.ts:182-191`）。
- 沙箱围栏 `SandboxedFileSystem`：继承 local，仅对两处变更加 per-call 策略栏——`read-only` 全拒 / `workspace-write` 仅限 `writableRoots` 内 fresh canonical 路径 / `danger-full-access` 解锁（`fs-sandbox/src/index.ts:122-144`）。
- **读前写强制**：`fs-observation-policy`——未先 read，则 write → `createIfAbsent`、edit → `FS_NOT_OBSERVED`；实现为**事件单槽决策**（`fs-observation-policy/src/index.ts:61-94`）。
- Consumer `tool-fs` **只持有 schema/呈现/观察事件，不持有 provider**（`tool-fs/src/index.ts:22`）——这是"换后端不改工具"的具体体现。

### 11.2 XEYO：三条写通道，覆盖不均

| 通道 | 实现 | 守卫 |
|---|---|---|
| `Write`/`Edit` 工具 | `engine/write_store.py:167-232, 234-275` | 每文件分片锁 + 路径硬门禁（`_canon` 拒工作区外 + `write_scope_deny_reason`）+ **陈旧哈希拒绝** + 原子写 + `journal.record_change` 审计 |
| `server/workspace_fs.py` | 旁路 | 默认拒绝写；开启后**不穿权限/rewind**，仅审计 |
| Bash 改文件 | `bash_tool.py:57-112` | 无写守卫；改后 `_invalidate_search_caches` 失效搜索缓存 |
| `Read` | `filesystem.check_read_permission_for_tool` | 读权限 |

### 11.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 统一通道 | **是**（一切经 `ctx.fs`） | **否**（三通道） |
| 默认只读 | 由 `sandbox-policy` 部署默认 `read-only` | 写通道默认可用（权限模式下） |
| 陈旧写守卫 | `replaceIfVersion`（provider 层） | 陈旧哈希拒绝（WriteStore 层） |
| 读前写强制 | **是**（`fs-observation-policy`） | 有 `missing_read` 类静默报错（同思路，落在执行层） |
| 写意图事件 | `fs/write-intent` / `fs/edit-intent` | 无（有审计事件 `tool.started/finished`） |

有趣的是两者**独立想到了同一件事**：dsh 用 `FS_NOT_OBSERVED`，XEYO 用 `missing_read: no prior Read for this path in this session`——都是"没读过就不许写"的**中性结果型报错**。这是本轮第二个"真·独立收敛"，与 §0.1 那个假的不同：两边的报错措辞、触发点（provider 策略 vs 工具层）都各自独立可证。

---

## 12. Shell / 终端 / 子进程

### 12.1 dsh

- **`ShellExecutor` 抽象**（`packages/shell/shell/src/index.ts:64-100`）：`run`（前台：非零退出/超时杀/abort 都 **resolve 为结果**，不抛）、`start`（后台，**无 timeout**）、`readOutput`（增量、不重复）。作者显式写死后台无超时（`:54-55`）。
- **Provider 矩阵**：`bash-local` / `pwsh-local` + 沙箱版 `bash-sandbox` / `pwsh-sandbox`；命令路由在 provider 内部。
- **持久 PTY**：`ctx.terminals` 是 owner-scoped 注册表，dispose 时 `disposeAll` 并等待清理（`'pty teardown'`，`terminal/src/index.ts:105-118`）；6 个 `tool-terminal` 工具（spawn/close/read/send/signal/list）+ `run_in_background`（`tool-terminal/src/index.ts:27, 43-46`）；`terminal-bash` 在沙箱模式变更时**拒绝开新 PTY**（`terminal-bash/src/index.ts:37-60`）。
- **子进程**：`win32-process` 用 `CreateProcessAsUserW` + Job Object 原语（`subprocess/win32-process/src/index.ts:1`）；`subprocess-local` 在组合拆卸时停并 await 后台进程。

### 12.2 XEYO

- `BashTool.call` 二路：容器（docker SDK）/ 宿主。超时：前台默认 `120_000`、上限 `600_000`，worker 模式 `30_000`/`60_000`（`bash_tool.py:124-125, 177-178, 346-366`）。
- 截断 `MAX_RESULT_CHARS = 30_000`（`bash_tool.py:126`）；**promote 机制**：`45_000ms` 内未完 → 自动晋后台 job（**进程不重启**）（`:130, 633-662`）。
- `run_in_background` → registry job（`job_output/list/kill` + 完成通知）（`:588-622`）。
- Windows 进程树：`win_job.py` 内存上限 + 超时整树杀；`runner.py` 优先 `taskkill /T`（`bash_tool/runner.py:65, 314, 418`）。
- **持久终端 / PTY：未见**（grep 无终端会话实现）。**后台 job 24h 超时：源码未见**（grep `86400|24h|MAX_IDLE` 无命中；后台 job 由 session abort 关 Job Object 回收，`server/job_registry.py:348`）。

### 12.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| Shell 抽象 | seam（`run`/`start`/`readOutput`） | 单工具内 if/else |
| 后台超时 | **无**（设计如此） | 前台 120s/600s，无后台死线 |
| 长命令处理 | 由模型显式 `run_in_background` | **自动 promote**（45s 未完转后台，进程不重启） |
| 持久终端 | PTY + 6 工具 + 沙箱联动 | 无 |
| 沙箱联动 | spawn 前 `confine` | 无（有 destructive_guard 启发式） |

XEYO 的**自动 promote** 是 dsh 没有的贴心设计：模型不必预判命令会不会久，引擎在执行层自动换轨，且进程状态不丢。

---

## 13. 模型层与 provider

### 13.1 dsh：LlmAdapter seam + 类型化流 + 可拦截

- **三角色**：Service Definition = `LlmRuntime extends TypertRemoteService`（`llm/src/index.ts:330`）；Provider = `LlmAdapter`（唯一必需方法 `stream()`，`:197-279`）；Consumer = agent loop 经 `llm/stream` waterfall（`:71, 1093-1107`）。`registerAdapter` 按 provider 路由，重名抛 `DUPLICATE_ADAPTER`（`:384-413`）。
- **Provider 全集**：`llm-deepseek`（官方直连）、**`llm-pi-ai`**（库驱动多厂商）、`llm-replay`（测试）。
- **请求组装**：`GenerateOptions`（`types.ts:407-443`，含 `provider/model/reasoningEffort/purpose`）；`adapterStream` 把文件投影成文本、图像按模态处理（`:998-1080`）。
- **流式协议**：`StreamChunk` 类型化联合（`types.ts:378-390`）：`block-start / text-delta / reasoning-delta / tool-call-delta / block-end / usage / finish`。
- **思考态**：`ReasoningBlock {type:'reasoning', text}`（`types.ts:59-63`）；`reasoning_effort ∈ off/low/high/max`（`adapter.ts:161-186`，默认 high）；`reasoning_content` delta → reasoning block（`translate.ts:155-164`）。
- **重试**：`ResolvedRetryPolicy` 分 `normal`（maxRetries=5）/`always`；可重试码 `EMPTY_RESPONSE | RATE_LIMIT | SERVER | TIMEOUT | TRANSPORT`（`llm-retry/retry-policy.ts:14-24`）。
- **错误分类**：`LlmError` + 机器码（`index.ts:90-124`）；HTTP 映射 401/403→AUTH、429→RATE_LIMIT、≥500→SERVER（`adapter.ts:332-344`）。
- **token**：`TokenUsage` 互斥计数含 `cacheReadTokens` / `reasoningTokens`（`types.ts:149-163`）；`mapUsage` 从 `prompt_tokens` 里减掉 cacheRead（`translate.ts:55-72`）。
- **KV wire**：请求侧**无** `cache_control` 全局参数；扩展字段 `dsh_plugin_packages`（默认开）、`dsh_session_log`（默认关）+ 归因头（`x-deepseek-harness-user-id` 等）**全在 messages 之外**（`docs/deepseek-llm-api-wire-extensions.md`；`adapter.ts:531-543`）。

### 13.2 XEYO：三家 provider 各自实现，reasoning 跨厂商有损

- **provider**：`openai_compat`（deepseek 路径，复用 `_openai_common.py`）、`anthropic.py` 原生适配器、`deepseek.py`、`fake`。**无统一基类**，各有 `stream()`。
- **思考态**：`anthropic.py:_blocks_to_anthropic` 处理 `thinking` + `signature` 回放（`:200-214`）；`thinking_delta` → `reasoning_delta` 实时渲染（`:385-399`）；`output_config.effort`（`:576-577`）。
- **跨厂商裁剪**：OpenAI 系纯文本 reasoning 转 Anthropic 时**静默丢弃**（无签名不伪造，`:207-210`）——这是一条明确的"宁可丢也不造假"纪律。
- 流式用 `ModelChunk(kind=...)`（`model/chunks.py:12`），弱类型。

### 13.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 适配抽象 | `LlmAdapter` seam + 路由 + 重复检测 | 无基类，各 provider 独立 |
| 可拦截 | `llm/stream` waterfall（可改写请求/拦截流） | 无 |
| 多厂商 | `llm-pi-ai` 库驱动（含 Anthropic `cache_control` 支持声明） | 三家手写适配器 |
| 流类型 | 强类型联合（7 种 chunk） | `ModelChunk(kind=...)` |
| reasoning | 明文 block + effort 四档 | anthropic 带签名回放；deepseek `reasoning_content`；跨厂商有损裁剪 |
| 请求侧缓存 | 扩展字段与归因头（全在 messages 外） | 无 |

---

## 14. 代码运行时与 LSP

### 14.1 dsh

- **`ctx.codeRuntime`**（`code-runtime/code-runtime/src/index.ts:95-120`）：`run` 跑模型写的程序，对接 host async bindings；`isolation ∈ worker-thread | process | container`；作者要求「treat programs as hostile peers, isolate runs from one another, and terminate and await in-flight runs during disposal」（`:99-101`）。消费端 = `run_code` 工具（PTC 模式）。
- **`ctx.lsp`**（`lsp/lsp/src/index.ts:82`）：注册 provider（按扩展名**独家保留**），只暴露四个操作 `goToDefinition / findReferences / goToImplementation / hover`，**无 JSON-RPC 逃逸口**（README:10-11）——把语言服务器的能力面**收窄到可审计的四件事**，而不是把 LSP 全量暴露给模型。

### 14.2 XEYO

- `DiagnosticsTool` 源码注释自陈 *"minimal language diagnostics (not a full LSP/IDE)"*（`tools/diagnostics_tool/diagnostics_tool.py:1`）；基于 AST 的静态诊断，`_TIMEOUT_S=30`、`_MAX_CHARS=16000`、`_MAX_FILES=50`，仅 Python/TS/JS（`:19-24`）。

### 14.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 代码执行 | `run_code` + 隔离三档 + PTC 模式 | 无（靠 Bash 跑脚本） |
| LSP | 真语言服务器（goto/refs/hover）+ seam | AST lint |
| 能力面收窄 | 显式四操作白名单 | 不适用 |

**PTC（Programmatic Tool Calling）值得单独说**：dsh 的 `run_code` 让模型写一段程序来编排多次工具调用，一次往返替代多轮。作者对其规则的说明（`core/tools/src/index.ts:49-51`）：「`run_code` is the only tool you can call directly — a tool call naming any other tool fails. Reach every tool the SDK declares below from inside the program.」这是"把工具调用循环下沉到代码里"的一种正交优化，XEYO 完全没有。

---

## 15. 成本与用量

### 15.1 XEYO：完整成本口径治理

- **价格表** `usage/pricing.py`：DeepSeek flash/pro 峰谷价（高峰 09–12 / 14–18 北京时 ×2.0，`:22-37, 40-112` `time_tier`；`USD_CNY=7.2`）；`LOCAL_PRICING_DB` 兜底 + `aipricing.guru` 实时价（TTL 24h + 磁盘缓存 + 后台线程刷新，`:337-556`）；`split_usage` 拆 hit/miss/out（`:142-162`）。
- **账本**：`ledger.py` / `attribution.py` / `vendor.py` / `combine.py` / `multi_agent_metrics.py`——厂商权威 usage 计账 + 归因 + 多代理成本度量。
- **计量纪律**：以厂商权威 `prompt_tokens` 为准，投影估算仅兜底（`query_loop.py:1276-1284`）。
- **预算死线**：`budget.py` + `runtime_budget` / `budget_mirror` / `wrap_up` 三个 T_now 块（见 §6.5）。
- 已知口径偏差（第一轮所述，仍在）：`pricing.py::_DEEPSEEK["flash"]` 尚未更新到新价，且仍带 peak×2。

### 15.2 dsh：只有 token 估算，没有钱

- `ctx.tokenMeter`：**启发式估算，且仅用于重放测量**（`token-meter/src/estimate.ts:43` 用 `CHARS_PER_TOKEN`）。
- `TokenUsage` 类型（含 cacheRead / reasoning，`llm/src/types.ts:149-163`）随 `assistant/message` 事件落库，**无独立账本**。
- `adapter.imageRequestPricing` 只做图像视觉 token 计价（`llm/src/types.ts:166-193`）。
- 全仓 grep `cost|budget|price|usd` 在 `packages/llm` 内命中全是测试与描述文本，**无预算/死线实现**。

### 15.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 计价 | 无（仅图像 route-pricing） | 峰谷价 + 实时价源 + 兜底表 |
| 计量用途 | 重放测量 | 决策（预算/收尾窗） |
| 账本 | 无 | ledger / attribution / vendor / combine |
| 死线 | 无 | turn/tool/token/usd + 收尾窗 |

**这是 XEYO 第二强的面**（仅次于注意力治理）。它的实际意义是：一个本地 Agent 要能被"运营"，必须能回答"这次会话花了多少钱、花在哪、还剩多少"。dsh 作为开源 harness 把这件事留给使用者。

---

## 16. 记忆子系统

### 16.1 XEYO：完整模型，但自动召回已退役

- **数据模型**（`memory/governance.py`）：`MemoryNote`（`:25-44`）——`id / type(user|feedback|project|reference) / content / source / confidence / status(active|superseded|deleted) / scope(user|workspace|project|task) / last_used_at / expires_at / supersedes`；`MemoryCandidate`（`:56-62`）为过闸前态；`Tombstone`（`:47-53`）防 NightShift 复活。
- **写入时机**：经 `Memory` 工具（模型/用户发起），落 `memindex.store_fragments`（`memory/memindex.py:293`）——**非每轮自动**。
- **召回**：`search.search()`（`memory/search.py:212`，`score_note` / `_recency_bonus` 重排）、`search_session_notes`（`:373`）、`search_rollout_summaries`（`:480`）。
- **自动召回恒关**：`engine/query_loop.py:355-363` 直接 `return False`，注释「事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役」；`memory/memory_switches.py:48-51` 同步「恒 False（不看本键），受控重开须源码级 + A1/A3 证据门」。
- 规模：`python/memory/` **48 文件**，含离线标定 `simulator/`。

### 16.2 dsh：没有独立记忆子系统

- grep `ctx.memory | memory seam | long-term` 在 `packages/` 无命中。
- 长期知识靠三样替代：`session-query` 工具（**查本会话**历史）+ `agent-instructions`（AGENTS.md）+ 项目文档。**无跨会话长期记忆**。

### 16.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 跨会话记忆 | 无 | 有完整模型（48 文件） |
| 自动召回 | 不适用 | **已退役**（恒关） |
| 当前实际形态 | 会话内查询 + 文档 | 显式 `Memory(action=search)` 才召回 |
| 事故教训 | 无 | 有：索引条目被弱模型当任务对象 |

**一个值得记的判断**：XEYO 建成了记忆子系统，又因事故把自动召回关掉——这个"建了又关"的过程本身就是结论：**记忆的难点不在存，在于"什么时候把什么塞回注意力"**。dsh 选择不建，反而绕过了这个坑。

---

## 17. 子代理与多代理

### 17.1 dsh：seam + 5 种 provider + 委托边界强制收窄

- **抽象**：`ctx.subagents`；`start(name, request): Promise<SubagentRun>`（`subagent/src/index.ts:554-566`）——provider 先建子再返回 run（fulfillment = 单一发布/所有权转移边界）。
- **Provider**：spawn-in-process / fork / acp / **claude-code** / **codex**（后两者在 `standard` preset 里 `disabled: true`）。
- **上下文继承**：`parentAgentOptionsForDelegation` / `childSessionMeta`（`index.ts:111-120`，`child-agent.ts`）——继承 provider/model/effort/maxTokens + cwd/preset/parentSession/delegationDepth/origin。深度 `assertSubagentMaxDepth`（`:557`）。
- **结果回流**：`SubagentRun.result: Promise`；可续子代理经 `SubagentContinuationManager` 的 inbox（`sendMessage` / `steerPrompt` / `queuePrompt`）（`:17-22`）。
- **权限收窄**：委托边界**强制 `approvalPolicy: 'never'`**（`child-agent.ts:245-246`），以 `source:'delegation'` 写入子日志——即"子代理不能被人类批准去做事"，防止审批链被用来放大权限。
- 注册表 = 命名 provider 注册（`registerProvider`，`:524`）；**未见全局 fan-out 上限**；冷列举并发 4。

### 17.2 XEYO：单实现复用主循环 + 侧链 + 角色 TOML + 结算归因

- `subagent_runner.py` **复用 `query_loop`**（不重建 god object），独立 `MessageStore` / `BudgetTracker` / `WorkingSnapshot`；侧链 `agents/{agent_id}.jsonl` **不污染主 JSONL**（`:1-14`）；预算 `DEFAULT_SUB_MAX_TURNS=32`（`:23`）。
- **角色**：`agent_roles.py` 读 `<workspace>/agents/*.toml`，**fail-closed**（`:1-14, 39-79`）。
- **结算**：`agent_settlement.py` 进程内 FIFO，每会话封顶 16，产出 `agent_settlement` T_now 块（`:7, 16, 32-78`）。
- **多代理编排**：由 `scheduler.py` 的任务 DAG 支撑（见 §18；第一轮"未接线"已更正）。

### 17.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 抽象 | seam + 5 provider | 单实现 |
| 复用 | provider 各自建子 | **复用主循环**（同一份 loop 代码） |
| 上下文隔离 | 子 session + `childSessionMeta` | 侧链 JSONL 不污染主日志 |
| 角色定义 | preset / provider | `<ws>/agents/*.toml`（fail-closed） |
| 权限 | 委托边界强制 `never` | 未显式收窄 |
| 结果回流 | Promise + 可续 inbox | 结算事件 + T_now 块 + 成本归因 |
| 成本 | 无 | `multi_agent_metrics.py` 归因 |

XEYO 的"复用主循环"是个反巨石的设计选择：不新建一套 sub-agent 引擎，而是给同一份 loop 换 store/budget/snapshot。代价是偶合，收益是行为一致性（子代理的每个 guard 与主代理同源）。

---

## 18. 调度 / 后台任务 / 工作流 / Webhook

### 18.1 dsh：四件套齐全

- **定时**：`ScheduleRuntime` 每 root agent 进程内定时器，持久化 `schedule/change` 事件（`schedule/schedule/src/runtime.ts:1-130, 77`）；工具 `schedule_create/list/delete`。
- **后台**：`ctx.jobs` **kind-agnostic** seam（bash 后台 / PTY send / 子代理共用同一控制器），`job_output/list/kill`（`jobs/jobs/src/index.ts:1-91`）。
- **Webhook**：`ctx.webhookRuntime` 规则注册 + `createWebhookSession`（`webhook/webhook/src/index.ts:1, 57-130`）；示例适配器 `webhook-github`（HMAC 校验、路由、`maxBodyBytes`）。
- **工作流**：`ctx.workflowEngine` worker-thread 执行（`vm.Script`，`workflow-worker-thread/src/runtime.ts:91-115`），hooks `agent/parallel/pipeline/phase/log`，并发槽 `maxConcurrentAgents` / `maxTotalAgents` / `maxItemsPerCall`；工具 `workflow` + `ralph`。

### 18.2 XEYO：后台对等，DAG 已接线，缺时间触发与工作流

- **后台**：`job_output/list/kill` 三工具（`tools/job_tools.py`）+ `server/job_registry.py`——与 dsh 对等。
- **任务 DAG**：`engine/scheduler.py`（1110 行）——`Task` / `toposort` / `scope_conflicts` / `build_tool_whitelist` / `repair_task_graph` / `run_task_batch` / checkpoint 系列。**已接线于多代理编排**（§0.2 已更正）。语义是**路径作用域互斥**（`scope_conflicts` 做路径归一后交集判定，`coord/store.py:10,68` 明确复用）。
- **时间触发型定时任务**：**未见**（这才是 XEYO 真缺的）。
- **工作流脚本 / Webhook**：**未见**（无 `workflow` 工具、无 webhook 入口）。
- **计划与待办**：`/goal` 斜杠 + `server/routers/goals.py`；`TodoWrite` 工具。

### 18.3 设计分歧

| 能力 | dsh | XEYO |
|---|---|---|
| 时间触发定时 | 有（进程内定时器 + 持久事件） | **无** |
| 后台任务 | seam，kind-agnostic | `job_*` + job_registry |
| 任务 DAG | `agent/pre-step` 内的分解 | `scheduler.py`（路径作用域互斥 + checkpoint） |
| 工作流脚本 | 有（worker-thread + 5 hook） | **无** |
| Webhook 入口 | 有（含 GitHub 适配） | **无** |
| 待办 | `todo_write`（`todo/write` 事件） | `TodoWrite` |

XEYO 的 `scheduler.py` 有一个 dsh 没有的设计点：**作用域互斥**（两个子任务若触碰同一路径则冲突，必须串行）——这是为"并行改同一个工作区"这一真实风险设计的，dsh 的分解没有等价约束。

---

## 19. Skill 系统

### 19.1 逐字段对照

| SKILL.md 字段 | dsh | XEYO |
|---|---|---|
| `name` / `description` | 必填（`skill-filesystem:810-815`） | 必填（`skill_loader.py:20-22, 50-59`） |
| 路由提示 | `whenToUse` | `model_hint` / `tags` |
| 模型可调用 | `disable-model-invocation`（bool） | `model_invocable` |
| 用户可调用 | `user-invocable`（bool） | `user_invocable` |
| 额外元数据 | `metadata`（对象） | `paths` / `mcp_dependencies` |
| 旧字段兼容 | `modelInvocable`/`userInvocable` **显式拒绝**（`:993-995`） | — |
| 坏 frontmatter | 忽略该 skill（记日志） | **fail-closed 丢弃**为 broken-but-listed（`skill_loader.py:24-25, 178-214`） |

### 19.2 发现与注入

| | dsh | XEYO |
|---|---|---|
| 发现分层 | 7 层带 rank：`project-dsh`(100) / `project-agents`(200) / `custom`(300) / `user-dsh`(400) / `user-agents`(500) / `bundled`(600) / `runtime`(250)（`skill-filesystem:36-40, 241-261`） | 三源：`workspace`(`.xeyo/skills`) > `home`(`~/.xeyo/skills`) > `plugin`（`skill_loader.py:271-277, 305-339`），casefold 去重，默认禁止覆盖，3s TTL 缓存 |
| 合并语义 | global+scope 链，最近层同名覆盖，层内按 rank（`skill/src/index.ts:553-567, 808-812`） | 优先级高者胜，默认禁止覆盖 |
| 目录注入 | `<system-reminder><available_skills>` 持久 `skill-catalog` 消息，经 `agent/pre-step` 瀑布**按 digest 幂等重发**（`tool-skill:213-251, 254-277`；digest 变化才重发 `:228, 361-377`） | 目录嵌进工具 schema，**会话起点快照，会话内不变**（`skill_tool.py:82-97, 178-180`，`CATALOG_MAX_CHARS=2400`） |
| 正文注入 | `<skill_content name=…><skill_instructions>…` （`skill/src/index.ts:172-185`） | `Skill` 工具按需加载 |
| 用户直呼 | `skill-invocation` 上下文消息（`:148-161`） | T_now `skill_preinvoke` 块 |
| 工具动作 | `skill`（可 describe） | `Skill`——仅 `action:'list'`，**无 describe**（`skill_tool.py:243-257`） |
| 内置技能 | **11 个**（`.agents/skills/`） | 本机 2 个 |

### 19.3 设计分歧

dsh 的目录是**每步校验 digest 的活页**（变了就重发，幂等）；XEYO 的目录是**会话起点冻结的快照**。这与 §0.1 的整体取向完全一致：dsh 允许会话内变化并保证幂等；XEYO 冻结一切以保前缀稳定。**同一个设计哲学在两个不相关的子系统上重复出现**，说明它不是局部选择而是全局纪律。

---

## 20. MCP 集成

### 20.1 dsh：直注工具面，无网关

- 一个 `mcp-client` 插件实例连一个 server，工具**直接注册进 `ctx.tools`**，公共名 `mcp__<serverName>__<rawName>`（`mcp-client/src/index.ts:4-5`；`tools.ts:113`）；多 server 多实例（`:4-11`）。
- 传输：`stdio`（command/args/env/cwd）或 `streamable-http`（url/headers）（`:50-95`）。
- 命名空间预留 + 冲突处理（`:154-168`）；`apply` **阻塞激活**直到首连 + 工具发现完成（`:184-187`）；重连策略（`:106-134, 173, 175-177`）；`failOnStartupError`（`:70, 122, 185`）。
- 权限：走与原生工具相同的 `ctx.tools` 管线，**无独立权限模型**。

### 20.2 XEYO：不出网关，走 `Mcp` 工具

- 配置三源合并（`settings.json` 的 `mcp_servers` + project mcp，按 id 合并，`mcp_manager.py:6, 113-131`）；`McpManager` 按 cwd 进程单例（`:5, 55-56, 89`）。
- 生命周期：stdio 子进程，skip-and-log，有界重连 500ms→30s 至多 10 次（`mcp_client.py:10-14`）；server 身份 = config sha256，attach 复用就绪 client（`:8-9`）；`required: true` 失败**不挡会话** + 挂 T_now 警告（`:10-11`，对应 `mcp_required_warn` 块）。
- **暴露方式**：经 `McpTool` 注册进 `ToolRegistry`，默认 `outbound_ask`（`:17-18`），不折叠同名（`:15-16`）；可见性预算 F2（`:77-85`）。授权：无 `${VAR}` 展开（`:14-15`）。
- **网关工具** `Mcp`：`action = list | describe | call | resources | read_resource`（`mcp_gateway.py:45-51`）。
- 作者对网关必要性的说明（`mcp_gateway.py:1-16`）：会话内新增工具的**唯一通道**（因为 tools 数组已冻结）；`reconcile.py:1-12` 补充「会话内启停**永不触碰**已冻结的 `schemas()`」。

### 20.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 工具暴露 | 直注 `ctx.tools`，命名空间名 | 注册 + **`Mcp` 网关工具** |
| 会话内新增 | 直接生效（工具面不冻结） | 只能经网关（工具面冻结） |
| 启停传播 | 插件激活期注册 | push reconcile → 单轮 T_now 活页块 |
| 权限 | 同原生管线 | `outbound_ask` 默认 + 停用即 DENY 不可被 grant 穿越 |
| 启动失败 | `failOnStartupError` 可选 | required 失败不挡会话 + T_now 警告 |

**这是本轮更正的核心结论**（§0.1）：第一轮把 XEYO 的网关设计误当成两端的共同点。真实情况是——**网关是 XEYO 为了绕过自己的冻结而发明的东西，dsh 因为不冻结所以不需要它**。

---

## 21. Hooks

| 维度 | dsh | XEYO |
|---|---|---|
| 事件 | `SessionStart` / `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` / `SubagentStop` / `SubagentStart`（`hooks-claude-code/src/index.ts:2-8, 207-294`） | `PreToolUse` / `PostToolUse` / `PermissionRequest` / `SessionStart` / `SessionEnd`（`extension/hooks.py:38`） |
| 方言 | **双方言** `HookDialect = 'claude-code' \| 'codex'`（`hook-protocol/src/types.ts:48`） | 自有 JSON |
| 配置 | `hooks.json`（`configPath`，`:45-53, 104`） | 插件 manifest 的 `hooks`（`hooks.py:82-96`） |
| wire | 经 `ctx.shell` 跑命令，JSON 写 stdin | 子进程，注入 `XEYO_HOOK_CONTEXT`，剥离 `GIT_*`（`:16, 123-124`） |
| 决策归一 | `allow / ask / deny / none`，优先序 **deny > ask > allow**，首个 `continue:false` **粘滞**（`merge.ts:3-21, 79-82`） | 三分 `Success` / `FailedContinue` / `FailedAbort`，超时 → FailedAbort（`:9-11, 111-113`） |
| 能否阻断 | 能（`abort`） | 能（`abort`，`:182-185`）；`PermissionRequest` 非 Success → **fail-closed DENY**（`:11`） |
| stdout 用途 | — | 经 reconcile 注入 T_now 块（`:13-14, 162, 179-181`） |
| 超时默认 | 600000ms（`:66-67`） | 600s（`:41`） |
| 日志 | `hook/invoked` + `hook/result` 事件（`events.ts:75, 92, 99`） | 审计 |
| 默认 | 由组合决定 | **关**（`hooks_enabled` 默认 false，`config.py:183-185`） |

**设计差异**：dsh 把 Hooks 当成**外部生态兼容层**（同时吃 Claude Code 与 Codex 的 hooks 协议），XEYO 把它当成**自有扩展点**且默认关闭。前者是"接入别人"，后者是"给别人接我"。

---

## 22. 扩展组合机制

### 22.1 dsh：四层组合

```
Profile（5 档：web / headless / sdk / sdk-minimal / acp）   boot/app-boot/src/profile.ts:137-158
  → Bundle（@deepseek-ai/dsh-base + 各 app bundle）          :142-157
  → 用户 cordis.patch.yml                                    :7-13, 44
  → --patch 覆盖层
Preset（agent-presets：standard / minimal / ptc / cordis）   以 scope 子树挂到 agent 之下
                                                             preset/agent-presets/src/mount.ts:1-14
```

- **改行为的两条路径**：① 在 `cordis.patch.yml` 加/改插件行（部署期）；② 会话内 `cordis_define`（运行期，模型自己挂）。
- **改提示**：patch `systemPrompt` section 或 agent preset 的 system 段。
- **扩展点规模**：`docs/capability-seams.md` 实测 70 行 / **69 个唯一 `ctx.<name>`**；包总数 **255**。

### 22.2 XEYO：固定枚举 + 配置开关

- `settings.json`（home + workspace 合并）+ `enabled_extensions` 总开关 + `plugins` / `skills` / `mcp_servers` / `hooks` 子开关（`extension/config.py:130-198`）。
- 扩展面**固定三条**：`extension/`（MCP + 插件 + hooks）、`slash/`、`skills/`。`AGENTS.md` 反巨石规则明确：新逻辑进新模块，**不在 `extension/` 之外新开扩展面**。
- 改行为：加 `mcp_servers` 条目、装插件、写 skill。**无运行期挂载。**

### 22.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 扩展点数量 | 69 seam / 255 包 | 3 个面 / 4 类开关 |
| 替换粒度 | 单 seam 的 provider（改配置） | 整包替换（改代码） |
| 运行期挂载 | 支持（`cordis_define`） | 不支持 |
| 配置载体 | `cordis.yml` + `cordis.patch.yml`（YAML + `!!js`） | `settings.json`（纯 JSON） |
| 失败姿态 | fail-loud（配置错误直接炸） | keep-last-good（坏 JSON 保留上一份） |
| 守卫 | `verify-cordis-config` 等 40+ verify | 启动自检硬失败 + 契约测试 |

**这是"可替换性"与"可预测性"的取舍**：dsh 换来的是"任何一块都能换"，代价是"没有任何一块的行为是确定的"；XEYO 换来的是"引擎行为完全可预期"，代价是"改任何行为都要发版"。

---

## 23. 服务端与协议

### 23.1 dsh：类型化 RPC + 单一 WebSocket mux

- `packages/api/gateway/src/index.ts`：`TypertGatewayService` 把 Cordis Service 暴露为强类型 Remote 调用，在 `/api` 上拦截 RPC（`:199-204`）；所有流式 Remote 走 `REMOTE_STREAM_MUX_PATH = '/api/remote.mux'`（`stream-protocol.ts:6`）。unary 走 `invoke`/`dispatchRpc`（`:590-600`），stream 走 `stream()`（`:321`）。
- **客户端可见的事件被白名单化**：Host 只转发 **18 个 allowlisted Cordis 事件**（2 个 waterfall：`approval/request`、`user-questions/request`；16 个 emit）——`api/remotes/src/index.ts` + `remote-events.ts:16-35`。这是客户端 `ctx.remote.$on` 的**合法键集**。
- **为什么要类型化 RPC**（`typert/README.md:12` 原话）：「Client environments can call Host capabilities as typed methods … **without hand-written wire code**」。构建期类型图生成器 → 运行时注册表 → Loader 自动注册；优先用生成的定义，否则回退源码反射（`gateway/index.ts:631-642`）。

### 23.2 XEYO：REST + SSE 事件流

- `server/app.py:296-364` 注册 **18 个 router**（workspace / media / usage / audit / control / commands / sessions / rewind / memory / chat / goals / jobs / skills / references / extensions / mcp / plugins）。
- SSE 在 `routers/chat.py`：OpenAI 兼容帧 + `xy.*` 旁路帧（`_xy_chunk`，`:517`）。
- **事件类型本轮实测**：`msgtypes/events.py` 里带 `type: str` 的 dataclass **共 20 个**；`EngineEvent` 联合列出 **19 个**（`permission_expiring` 未入联合，`:313-333`）：
  `assistant_delta / reasoning_delta / tool_call / tool_progress / tool_result / final / stopped / usage / context_compression / result / permission_pending / permission_expiring / permission_resolved / ask_user_pending / ask_user_resolved / plan_pending / plan_resolved / task_state_changed / llm_retry / llm_retry_started`

  > 第一轮写"25 类"是估的，本轮以源码为准更正为 **20 个 dataclass / 19 个联合成员**。
- **安全门禁**：`server/local_gate.py:20-32` 非 loopback 控制面一律 403（`_LOOPBACK` 含 `127.0.0.1/::1/localhost/testclient`），`XEYO_ALLOW_REMOTE_CONTROL=1` 才放开。作者对反向代理的态度（`local_gate.py:27`）：「部分反向代理会把真实 peer 放在 X-Forwarded-For；**默认仍拒**——本地桌面不该经公网代理。」CORS 也弃用 `*` 通配符（`app.py:217-237`：「通配符 + allow_credentials 等于对任意网页开放本地 API」）。
- **旁路**：`server/workspace_fs.py:39-41` 默认拒绝直写，需 `XEYO_WORKSPACE_FS_WRITABLE=1`；`write_file`/`delete_path`（`:207-212, 228-233`）绕过引擎权限与 rewind，仅打审计（`_audit_write`，`:44-62`）。

### 23.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 协议范式 | 调用式（typed method call + mux） | 推送式（REST + SSE 事件流） |
| 类型安全 | 端到端（类型图生成 + 运行时注册表） | 无（JSON 帧约定） |
| 事件面 | **18 个白名单**（窄） | **20 类**（宽），含审批/提问/计划的 pending+resolved 配对 |
| 细粒度数据 | 走类型化 session-controller 的持久 `session/event` 流 | 全走 SSE |
| 门禁 | — | loopback 强制 + CORS 收紧 + 直写默认关 |

**两种哲学**：dsh 是"少量事件 + 强类型拉取"，XEYO 是"大量事件 + 单向推送"。前者客户端更可预测（白名单 + 生成类型），后者实现更简单但**契约靠约定**（`EngineEvent` 联合是唯一的类型约束，且已有 1 个成员漏登记）。

---

## 24. 前端架构

### 24.1 dsh：React-free 对象层 + 插槽化 UI

- **状态**（`client/store/src/index.ts:1-9`）：快照 store 引擎 = **zustand/vanilla + immer + subscribeWithSelector + rafFlush**，明确写「**NO selector hook**」；React 绑定由 `ui-renderer` 合成（`:7-8`）。flush 分 `sync` / `raf`（`:103-104`）。
- **插槽系统**（`client/ui-slots/src/index.ts:89-93`）：4 种基数 `single | list | keyed | chain` × 3 种作用域 `root | session-maybe | session`——**UI 也是插件**。
- **包数**：`packages/client/` 下 50 个子包（38 个 `ui-*` + connection / file-upload / hmr / locale / modules / store / web）。
- **事件来源**：18 个转发事件 + `session/event` 持久流 + `agent/*` 直播。
- **Trajectory 面板**：独立 `ui-trajectory` 包（40 文件 / 13,488 行），turn 感知事件账本 + 搜索索引 + 折叠 + 时间线区间选中 + `loadOlder` 分页 + 来源标签。
- **HMR**：`client-hmr`：SSE `/plugins/events` → 热换 cordis fiber（`hmr/client/index.ts:104-140`）。

### 24.2 XEYO：业务驱动的单包 React 应用

- `gui/src`：React 19 + Vite；zustand 5 + `@preact/signals-react`。
- **IndexedDB**（`lib/db.ts:42`）：库 `xeyo-web`（由旧 `xenyon-web` 迁移，`:41-43`），对象仓库 `spaces / sessions / messages / kv`（`:17-37`）。
- **流式**：`lib/sessionStreams.ts:18-19` 用 `SessionStreamState.lastEventId` 作 reattach cursor，断线后按 cursor 重放（**非自动重连**，`:13-17`）。
- **关键 UI**：`Composer.tsx`、`FilesChanged.tsx`（unified diff）、`toolActivity.ts`（动态 verb）、`AskUserDialog` / `PermissionDialog` / `PlanDialog`、`VirtualRoundList.tsx`（>40 轮才窗口化，`:40`）。

### 24.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 组件合成 | 插槽（4 基数 × 3 作用域），UI 插件化 | 直接 import |
| 包数 | 50 个 client 子包 | `gui/src` 单包（components 131 / lib 165 / stores 41 / hooks 10） |
| 状态层 | React-free 对象层 + 渲染绑定分离 | zustand + signals，React 耦合 |
| 轨迹回看 | **Trajectory 面板**（13.5k 行） | **未见** |
| 国际化 | `locale` 包（zh/en，回退链终于 en） | **未见**（中文为主） |
| 热更新 | cordis fiber HMR | Vite HMR |
| 断线恢复 | 日志 seq 重连 | cursor 重放 current turn events |

---

## 25. 桌面壳与进程管理

### 25.1 XEYO：Rust 壳 + 真探测 + 守护（dsh 完全没有）

- `gui/src-tauri/src/lib.rs:285` `resolve_python_exe`：依次试 `XEYO_PYTHON` → 内嵌 `.venv` → `py -3.11` → `python3/python`。
- `:266` `python_exe_usable`：用一次**真实** `python -c "import sys"` 探测。注释记录了薄壳 venv 事故：「`is_file()` 挡不住启动即失败」。
- `:358` `BACKEND_SPAWN_ERROR`（`OnceLock` 静态槽）+ `:372` `get_backend_error` 把真实失败原因回显 GUI。注释 `:355`：「spawn 失败只 eprintln，用户完全不知道是内嵌 Python 坏了」。
- 守护 `:231-233`：`SUPERVISE_INTERVAL_S=10` / `STARTUP_GRACE_S=20` / `KILL_AFTER_UNHEALTHY_S=30`；`:925-979` 周期探测 + respawn。
- 窗口/桌宠：透明无边框窗 + 独立桌宠窗（`pet.rs`）；sidecar 映射 `resources/python`（`tauri.conf.json:46-48`）。

### 25.2 dsh：无桌面壳

穷举 `packages/`：**无 tauri / electron 子包**；宿主就是 Node 进程 + 本地 HTTP。`apps/cli/src/args.ts` 的子命令只有 `web`（`--profile web` 别名，`:156`）与 `plugin --profile <n> <pnpm args>`（`:171`），外加启动旗标 `--profile/--patch/--dump-config/--dump-default-config/-V`（`:131-134`）。

### 25.3 设计分歧

XEYO 的壳承担了一件 dsh 从不需要做的事：**把一个 Python 解释器 + 引擎作为 sidecar 可靠地拉起来**。dsh 是 Node 生态，`npx` 直接跑，没有"解释器不存在/不可用"这个问题类别。所以 XEYO 的壳里那些"真探测/失败原因回显/自包含断言"代码，本质是在补 Node 生态免费得到的东西——**这是选 Python 的代价，不是设计水平问题**。

---

## 26. 对外集成（CLI / SDK / ACP）

| | dsh | XEYO |
|---|---|---|
| **SDK** | **TS SDK**（`packages/sdk/`：protocol / client / server，newline-delimited JSON-RPC over stdio）+ **Python SDK**（`python/sdk/src/deepseek_harness/client.py:39` `HarnessClient`，同步客户端，`profile="sdk"`，`:24-36`） | **未见** |
| **运行时打包** | `python/sdk-runtime`：wheel 内打包 `deepseek-harness-sdk-runtime-<platform>-<arch>` **单文件 Node 可执行** + ripgrep sidecar + macOS spawn-helper（`__init__.py:6-9, 55-90`） | — |
| **ACP** | `packages/acp/`：Agent Client Protocol server（JSON-RPC stdio），暴露 `initialize / new-session / resume / list / prompt / request-permission / cancel`（`acp/src/index.ts:1-7, 20-47`），`inject:['agents','llm','sessionPersistence','sessions']`（`:62`）；**亦可作为子代理 provider** | **未见** |
| **CLI** | `dsh`：profile 启动器 + `plugin` 包管理（见 §25.2） | Typer：`version / setup / chat / attach / serve` + `coord run|status` + `sessions list|show|rm` + `config path|show|set`（`cli/main.py:123-301`） |
| **斜杠命令** | `ctx.commands`：`CommandDefinition`（name 必须 `^[a-z][a-z0-9_-]*$`），handler 返回 `CommandResult`；`command/run` / `command/done` 事件（`commands/src/index.ts:60-75`） | **35 条**（`slash/registry.py`），SSOT → 导出 TS manifest，`slash.export_manifest --check` 进门禁 |
| **第二客户端** | web / headless / sdk / sdk-minimal / acp 五 profile | TUI（Ink） |

**这是 XEYO 的第三大缺口**：它对外只能"人用"（GUI/TUI/CLI），没有"程序用"的接口。dsh 的 SDK + ACP 让它能被 IDE、其他 Agent、脚本当成一个**组件**接入——这是 `subagent-codex` / `subagent-claude-code` 能存在的前提（反过来，它也能当别人的子代理）。

---

## 27. 配置 / 凭据 / 身份 / 遥测

| 维度 | dsh | XEYO |
|---|---|---|
| 设置优先级 | `schema 默认 → composition base → 用户文档`（用户层覆盖 base，`settings/src/index.ts:740-753`） | `home + workspace` 深合并，**workspace 更具体者优先**（`extension/config.py:202-214`） |
| 脱敏 | wire 前必 `redactSecrets`（`:105-108, 529`） | `scrub_audit_fields` 只作用于审计日志（`audit/log.py:30-45`） |
| 凭据 | `ctx.credentials` seam：`CredentialRef`（环境变量名，按 env/file/project-env/user-env 分层，**每次操作重解**，`:183`）+ `CredentialKey`（授权记录，`modifyRecord` 唯一写路径）；「**值永不明文暴露**」（`:5-7`） | **未见独立 seam**（环境变量 + 配置） |
| 身份 | `anonymous-user-id`：随机 UUID v4 存 `$DSH_HOME/.anonymous-user-id`，**绝不取主机名/网络/git remote**（`:1-17, 68`） | **未见** |
| 遥测 | `ctx.sessionTelemetry` seam + `session-telemetry-otel`（OpenTelemetry） | grep `opentelemetry` **0 命中**；只有本地 `usage/` + `audit/` 账本 |
| 不变式 | `ctx.invariants` 注册表 + 各包 `invariant` companion，违反抛 `InvariantError`（`runtime-diagnostics/invariants/src/index.ts:50-66`） | 分散在各 guard |

作者对凭据设计的一句话（`credentials/src/index.ts:5-7`）：「providers own the actual values … Consumers resolve a reference once per operation, so **a changed credential reaches the next operation without any plugin restart**」——引用/值分离，换来"换钥匙不用重启"。

---

## 28. 测试与质量门

| 维度 | dsh | XEYO |
|---|---|---|
| 单测规模 | vitest **863** spec | pytest **307** 文件；GUI vitest ~102 |
| **覆盖率门** | **per-file 100% on `packages/*/*/src`**（`docs/testing.md:10`）：「未覆盖的行往往是死代码」 | **未见** |
| 类型门 | `strict: true` + `noImplicitAny` + 每个 `any` 需解释；`verify-export-jsdoc` 强制 JSDoc | `tsc -b`（gui）+ tui typecheck |
| **快照回放** | `test:snapshot`（录制的 session 走真实 profile 回放）+ `test:expected` + `test:web`（Chromium 比对，**required Linux PR gate**）（`testing.md:13-14, 54`） | **未见** |
| 真 API e2e | `test:e2e` 显式跑真 API，作者原话「**We are DeepSeek — do not ration real-API tests**」（`:23-24`） | `-m "not live"` **平时不跑**（`scripts/check.ps1:11`） |
| 契约/生成物门 | **40+ `verify-*`**（application-entrypoints / cordis-config / tool-catalog / package-invariants / md-links / agent-note-classification / skill-invocation-metadata / translation-pairing…） | `slash.export_manifest --check`；`test_t_now_block_registry.py`（4 用例）；`test_freeze_invariants.py` |
| 不变式 | `ctx.invariants` 注册表 | 分散 |
| 已知失败 | 无 xfail 文化；改行为改测试并说明理由 | 显式 `xfail` + 注明归属（实测 2 处，`test_bash_isolated.py:25`） |
| 提交门 | `lefthook.yml` + `pnpm run check:all` + CI 多平台矩阵（含 win-wine 观测道） | `scripts/check.ps1`，**无 hook 强制**（靠人跑） |

**门禁强度差距是本轮最一致的一处**：dsh 是"五重门"（覆盖 + 快照回放 + 浏览器 + 真 API + 40 verify），XEYO 是"四件事"（pytest 非 live + manifest + typecheck + vitest）。而且 XEYO 的 pytest **平时不跑真 API**，dsh 明确要求不省真 API 测试——这直接影响"改动是否有真实收益"的可证性。

---

## 29. 构建 / 打包 / 分发

| 维度 | dsh | XEYO |
|---|---|---|
| 产物 | **npm 包**：`npx @deepseek-ai/dsh web`；**profile 即分发单位** | **Tauri 应用**：NSIS + MSI（`tauri.conf.json:37`），`resources/python/` 映射进安装目录（`:46-48`） |
| 构建编排 | `pnpm run build`（tsc → `lib/`，tsdown 打包） | `scripts/build_installer.ps1` 三步：精简 Python → slim venv → `tauri:build` |
| Python 运行时 | `python/sdk-runtime`：单文件 Node exe + ripgrep | `scripts/build_slim_venv.py`：用 `astral-sh/python-build-standalone` 造**自包含可重定位** venv（自带 DLL / 标准库 / VC 运行时），**带自包含性断言**；`pyvenv.cfg` 必须写 `home=.` |
| 开发启动 | `pnpm dsh web`（源码走 `node --import tsx/esm`） | `XEYO.bat`（校验 node/py3.11 → 起后端 → 等 `/health` → `npm run tauri:dev`） |
| CI | `.gitlab-ci.yml` + `.github/`：多平台矩阵（linux-primary / static / coverage / snapshot / artifacts / consumers / **windows-blocking / complete / observational** / wine）；`sdk-wheel` + 5 个 runtime 平台 | `.github/workflows/ci.yml`：python(pytest) / gui(typecheck+test) / tui(typecheck) |
| 容灾 | 标准 GitHub + PR 栈 | bare mirror（`D:/lea/XenYon-git-mirror-*.git`）+ 封存 `.git.broken-*`；**无 remote** |

XEYO 在这条链上有一个 dsh 没有的**硬约束**：安装包必须自带 Python 运行时，于是"自包含性断言"成为构建门的一部分（缺 DLL / site-packages 不在 sys.path / `pyvenv.cfg` 指向外部 → 构建失败）。这是被事故逼出来的工程纪律（薄壳 venv 事故），价值高于 dsh 的 `npx` 一键分发。

---

## 30. 文档与协作规范

| 维度 | dsh | XEYO |
|---|---|---|
| 仓库级规范 | `AGENTS.md`（155 行）+ `packages/AGENTS.md` + `docs/AGENTS.md` + `vendor/AGENTS.md` + `snapshots/AGENTS.md` | `AGENTS.md`（设计理念五条 + 工程硬规矩七条） |
| 文档量 | **363 个文件**，含生成式目录（tool-catalog / config-catalog / capability-seams / module-graph / persistence-catalog / event-producer-consumer / graph-atlas）+ 40+ 子系统页 + postmortem | 21+ 篇（含 3 篇审计、BENCH 口径、dsh 考据、应试性审查） |
| 双语 | **强制**（`*.md` + `*.zh.md` + `*.i18n.yaml`），`verify-translation-pairing` 执法 | 中文优先 |
| 变更伴随文档 | **非平凡改动必须同 PR 附 Agent Note**（`AGENTS.md:125`），归档笔记冻结不可改 | 未强制 |
| 散文规范 | `dsh-prose-standard` 技能 + 禁用隐喻 + 禁用 `contract/boundary/shape` 滥用（`AGENTS.md:144`） | 引擎文本铁律（只给信息不给导演） |
| 自我约束框架 | — | **应试性审查四尺子**（R1 产品受益 / R2 无评测分支 / R3 信息纪律 / R4 收益可证伪）+ BENCH 口径登记表 |

**一个对称的发现**：dsh 有一份 `dsh-prose-standard` 技能，规定**写给模型看的技术文档**该用什么语气（禁隐喻、禁术语滥用）；XEYO 的 `AGENTS.md` 铁律规定**写给模型看的运行时文本**只许是信息。两者都在管"语言"，但一个管**人类文档**，一个管**模型注意力**。这恰好是两端第一性问题的又一次投影。

---

## 31. 设计层差异总表

### 31.1 同一问题、两种解法（设计取向对照）

| 问题 | dsh 的解法 | XEYO 的解法 | 谁赢 |
|---|---|---|---|
| 长会话工具面变化 | 不冻结，每步派生；一致性交给类型化 RPC + 事件日志 | **冻结** `_schemas_cache`；新增只能经 `Mcp` 网关 | 平（代价各异） |
| KV 前缀稳定 | 结构副产品（追加式日志）+ provider 库声明 cache 能力 | 显式政策（左段极简 + `frozen_until` 游标） | XEYO 更自觉 |
| 上下文里能放什么 | 无门（插件自由），只要求"可见即可重建" | **登记表 + 硬顶 21 + 逐条理由 + 4 条测试** | XEYO 更严 |
| 权限的本质 | 沙箱模式 × 审批策略（≈隔离强度） | 工具级 ASK/ALLOW/DENY + grant 指纹 | 不可比（正交） |
| 隔离 | 内核级四后端 + 云沙箱，fail-closed | 无（仅 Job Object 资源限额 + 关键词启发式） | **dsh 完胜** |
| 模型历史真相 | 事件溯源，`request/header` 入日志，可逐字重建 | 消息级 transcript，靠投影函数重算 | **dsh 完胜** |
| 成本可控 | 无 | 峰谷价 + 账本 + 归因 + 四重预算 + 收尾窗 | **XEYO 完胜** |
| 失败姿态 | fail-loud（配置错就炸）+ fail-closed（沙箱不可用即拒跑） | keep-last-good + 静默降级 + 执行层静默报错 | 取向不同 |
| 扩展能力 | 69 seam / 255 包 / 运行期挂载 | 3 个固定扩展面 / 编译期枚举 | **dsh 完胜** |
| 对外可编程 | TS/Py 双 SDK + ACP + 5 profile | 只有 CLI/TUI/HTTP attach | **dsh 完胜** |
| 质量门 | 覆盖率 100% + 快照回放 + 真 API + 40 verify | pytest(非 live) + manifest + typecheck + vitest | **dsh 完胜** |
| 桌面交付 | 无壳（npx） | Tauri 壳 + 自包含 venv 断言 + 进程守护 | **XEYO 完胜** |

### 31.2 dsh 有、XEYO 完全没有（设计层，去重后 14 项）

1. **能力缝三角色 + 69 个 seam**（Service Definition / Provider / Consumer）
2. **注册即 effect**（disposer 自动回收）
3. **命名事件瀑布**（4 个工具管线拦截点 + 3 个 agent 阶段 waterfall）
4. **OS 级沙箱四后端 + E2B**，`confine(argv, policy)` 抽象，fail-closed
5. **事件溯源会话日志 + `request/header` 入日志 + 代际迁移链**（`SESSION_FORMAT_VERSION=2`）
6. **PTY 持久终端**（6 工具）+ Shell seam（`run`/`start`/`readOutput` 语义分离）
7. **代码运行时 seam + PTC（`run_code`）**
8. **LSP seam（四操作收窄）**
9. **工作流脚本引擎 + `ralph`**、**Webhook 入口**、**时间触发定时任务**
10. **自修改工具**（7 个 `cordis_*`）
11. **类型化 RPC（Typert）+ 18 事件白名单**
12. **SDK / ACP / profile 组合（Profile→Bundle→Patch→Preset 四层）**
13. **per-file 100% 覆盖率门 + 快照回放 + 浏览器 PR 门 + 40 verify**
14. **凭据 / 身份 / OTel 遥测三个 seam + `ctx.invariants` 注册表 + 强制双语 + Agent Note**

### 31.3 XEYO 有、dsh 完全没有（设计层，去重后 12 项）

1. **注意力硬准入**（20 块登记表 + 硬顶 21 + 逐条理由 + 4 条执法测试 + 禁止裸 append）
2. **`env_channel` 伪造 tool 对声道**（根治说话人混淆）
3. **预算 / 死线四重护栏 + 收尾窗 + 预算类 T_now 块**
4. **成本口径治理**（峰谷价 + 实时价源 + 账本 + 归因 + 多代理成本）
5. **工作区 rewind**（v2/v3，崩溃恢复顺序 + 热路径精细对齐）
6. **跨会话记忆模型**（48 文件 + Tombstone + scope + 离线 simulator）
7. **Tauri 原生壳**（进程守护 + 解释器真探测 + 失败原因回显 + 自包含 venv 断言）
8. **桌面 UI 控制 / Screenshot / 桌宠**
9. **微信通道**（`channels/`）
10. **透明 Bash 路由**（`[routed: …]`，纯读命令换专用工具）
11. **斜杠命令 SSOT + 生成式 manifest 门禁**（35 条）
12. **多代理任务 DAG 的作用域互斥**（`scope_conflicts`）+ 成本归因结算

### 31.4 第一轮结论的修正影响

| 第一轮结论 | 状态 |
|---|---|
| 「两端独立演化出『工具面冻结 + 网关新增』同一设计」 | **作废**（§0.1）。真相：取向相反，各自自洽 |
| 「`engine/scheduler.py` 写了无消费方」 | **作废**（§0.2）。真相：多代理 DAG 已接线；XEYO 缺的是**时间触发**定时 |
| 「XEYO SSE 25 类事件」 | **更正**为 20 个 dataclass / 19 个联合成员 |
| 「dsh 68 个服务缝」 | **更正**为 69 个唯一 `ctx.<name>`（70 行表） |
| 其余（沙箱/PTY/LSP/事件溯源/成本/记忆/壳/门禁等） | 本轮均获源码级支撑并细化 |

---

## 32. 结论

**1. 第一轮说"两者是不同物种"，第二轮可以给出更硬的判据：它们把"最难的问题"定在了不同的层。**
XEYO 认定最难的是**模型注意力里出现了什么**，于是用"引擎文本立法 + 注入管线硬准入 + 执行层静默强制"三件事去解决；dsh 认定最难的是**任何一块能不能被换掉**，于是用"能力缝 + effect 回收 + 组合四层"去解决。这不是风格差异，是**问题定义的分歧**——它们甚至不冲突，但同一段代码不会同时服务两个目标。

**2. 上一轮那句"共同收敛"是我的错误，但它错得有价值。**
真相是：XEYO 冻结工具面 → 必须发明网关工具绕过自己；dsh 不冻结 → 不需要网关，但必须用类型化 RPC + 事件溯源保证客户端与日志一致。**互为镜像，而不是趋同。** 我原来看到的"趋同"，其实是我把 XEYO 的契约抄到了 dsh 那一列。

**3. 设计层的最大差距不是"功能缺",而是"缺一层"。**
沙箱、事件溯源、类型化 RPC、seam 机制——这四件事都不是"再加个功能"能补上的，它们是**别的东西成立的前提**。比如：没有事件溯源，"模型当时看到什么"永远无法证明；没有沙箱，Bash 内部永远没有第二道防线；没有 seam，任何行为变更都得改引擎。

**4. XEYO 的两项领先同样不是功能性的，而是"运营性"的。**
注意力硬准入（20 块 + 硬顶 + 4 条测试）与成本口径治理（峰谷价 + 账本 + 四重预算）解决的都不是"能不能跑"，而是"能不能长期跑并且说得清"。dsh 作为 developer preview 不需要这个；XEYO 作为要在用户机器上常驻的产品必须要有。

**5. 最值得 XEYO 借鉴的三件事（按性价比重排）**

| 序 | 借鉴项 | 为什么值 | 落点 |
|---|---|---|---|
| 1 | **事件溯源会话日志**（含 `request/header` 入日志） | 它是 fork / resume / telemetry / 迁移 / 快照回放 / 成本归因的**公共底座**。XEYO 现在的 transcript 是"结果"，不是"过程"，导致所有派生能力都要各写一遍 | `session/record_transcript.py` 改为事件追加；请求头单独落一类事件 |
| 2 | **沙箱执行层 `confine(argv, policy)`** | XEYO 现在 Bash 一落地就没有第二道防线；且 fail-closed 语义可以直接复用 XEYO 已有的"执行层静默报错"纪律 | `tools/bash_tool/` spawn 前统一过一道 confine，Windows 走 ACL 或降级为显式拒绝 |
| 3 | **能力缝 + 命名事件**（不必照搬 Cordis） | 把 `query_loop` 里 4 个内联点位（pre-step / request / llm stream / 工具三段）改成命名事件，今天的 guard 就能从"改引擎"变成"挂插件" | 第一步只做**命名**（事件 + 观测），不要求可替换 |

**6. 最值得 dsh 借鉴的一件事：T_now 式的注入治理。**
dsh 的插件自由是双刃剑——69 个 seam、255 个包，任何插件都能往上下文塞东西，而它只有"可重建"一条底线，**没有"这条内容该不该出现在注意力里"的门**。XEYO 的"登记表 + 硬顶 + 逐条存在理由 + 机器执法"是这套治理的完整范本，且已被证明可实施（20 块 + 4 条测试）。

**7. 一个更冷静的收尾。**
XEYO 的注意力铁律能让它产出**更干净**的模型轨迹——这是它的差异化资产，值得继续守。但"干净"不产生分叉能力、不产生隔离、不产生可编程接口。第二轮的全部结论可以压成一句：**XEYO 的问题是"缺一层"，不是"缺几个功能"；它现有的一切纪律，都应该被搬到那层地基之上，而不是用来替代那层地基。**

---

*取证边界：本轮由 6 路分队按能力域（循环/会话、工具/管线/权限、执行隔离/IO、prompt/模型/成本/记忆、扩展生态/编排、协议/前端/壳/工程）跨两端并行通读源码；主代理独立复核了全部加载性结论（dsh 无 `Mcp` 工具、`ToolRuntime.view()` 无缓存、`SESSION_FORMAT_VERSION=2`、XEYO 事件数、T_now 登记 20 块 + cap 21 + 4 条执法用例、scheduler 消费方、dsh seam 69 个）。dsh 侧核心包逐文件读，38 个 `ui-*` 包按入口/slot/contract 读、组件内部未逐行读，`native/landlock-run`、`code-runtime-worker-thread`、部分 tool provider 的 execute 实现未逐行读。XEYO 侧 `python/` 关键链逐段读，`memory/simulator`（11 文件）、`usage/ledger|attribution` 内部、`server/routers/*` 各路由实现体、`tui/src` 未逐行读。凡"未见"均为排除 `.venv` / `__pycache__` / `node_modules` 后穷举未命中。*


