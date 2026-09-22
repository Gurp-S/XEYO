# XEYO 完整项目说明与 Terminal-Bench 2.1 低分根因

> 文档目的：让没有读过 XEYO 源码的人，能够先理解 XEYO 是什么、一次请求怎样流过系统、Terminal-Bench（TB2.1）到底测到了什么，以及为什么 XEYO 的分数看起来很低。
>
> 文档状态：基于 2026-09-18 工作树和已完成的零费用验证。本文不把未跑出的 89 题成绩写成事实，也不把官方自报分数当成 XEYO 当前可达分数。
>
> 重要范围：这是设计与根因说明，不是提交记录。工作树中仍有其他在途改动；本文不要求提交代码、不重生成 golden、不触发付费评测。

---

## 0. 结论先行：为什么看起来只有五十多分，清洗后为什么仍然七十多分

这个问题不能用一句“模型不行”或者“XEYO 不行”解释。当前证据显示，低分由四层因素叠加而成，而且它们被原始评测分数混在了一起：

1. **比较基准不是同一个口径。** 表里写的 DeepSeek V4.1-Flash `90.6` 是厂商自报结果；公开受控评测和厂商口径之间已经被同模型配对实验观察到约 `12.6` 个百分点的差距。因此，`90.6` 不能直接当作 XEYO 在同样 89 题、同样 harness、同样重试策略下应该拿到的目标。

2. **原始表观分数被判分基础设施失败污染。** 9 月 14 日那批 37 题中，20 题 green，5 题是真答错，11 题是 `verifier_invalid`，1 题 agent timeout。原始 `20/37 = 54.1%` 把 11 个“判分没有正常完成”的题当成了模型没做对。

3. **把判分无效题剔除后，仍然有真实错误。** 同一批数据中，有效分是 `20 / (20 + 5 + 1) = 76.9%`。这是 [`zero/verdict.py`](TerminalBench/zero/verdict.py) 的已确立裁决口径。清洗只能去掉基础设施噪声，不能把 5 个真答错自动变成 green。

4. **XEYO 之前确实存在会影响 agent 行为的引擎和 harness bug。** 已确认的重要问题包括：错误的 65536 上下文硬编码、推理 token 没进入压力水位、容器内外文件系统不一致、专用文件工具被错误路由、后台 job 管理带来额外轮次、旧的 `xeyo_env_notice` 伪工具形态诱发自调用循环。这些问题会让“同一个模型”在 XEYO 里比在干净 harness 里更容易浪费轮次、丢失证据、过早压缩或无法读取自己刚写的文件。

5. **当前仍不能宣称 89 题分数已经是多少。** 已修复的是一批结构性问题，已完成的是零费用测试和局部容器端到端验证；尚未完成的是“修复前后、同一题集、同一模型、同一成本口径”的受控 89 题复测。因此当前任何 `72/89`、`77%` 或其他数字，若不是某一次完整实测的 verdict 输出，都只能叫预测，不能叫成绩。

最简因果链：

```text
官方自报 90.6
      │ 不是同一评测协议，不能直接比较
      ▼
公开受控基线本来就会低一截
      │
      ├── XEYO 原始执行层 / 容器 / 上下文 bug
      │       ├── verifier_invalid 增多
      │       ├── 轮次浪费、证据取不回
      │       └── 错误压缩或上下文压力误判
      │
      ├── 模型和题目本身的真实错误
      │       └── 5 题 wrong_answer + 1 题 timeout（37 题样本）
      │
      └── 混合结果
              ├── 表观分：54.1%
              └── 清洗判分基础设施后：76.9%
```

**完整答案是：原始低分有很大一部分不是答题能力；但剔除基础设施故障后，剩余的真实答题能力也还不是 90%，而且官方 90.6 本身不是可比目标。**

---

## 1. XEYO 是什么

### 1.1 一句话定义

XEYO 是一个 **local-first 的代码工作台和 agent 引擎**：模型负责理解任务、制定行动、调用工具和验证结果；XEYO 负责把模型请求接到本地工作区、容器、文件系统、权限系统、会话存储、上下文投影和事件流上。

它不是一个单独的模型，也不是一个只有 prompt 的聊天机器人。它是三层组合：

```text
┌─────────────────────────────────────────────────────────────┐
│ 产品层：GUI / TUI / CLI                                    │
│ 用户输入、界面展示、权限交互、会话管理                       │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / SSE 或进程内调用
┌──────────────────────────────▼──────────────────────────────┐
│ 引擎层：QueryEngine + query_loop                           │
│ 模型请求、上下文投影、T_now、工具解析、权限、循环、预算、事件 │
└──────────────────────────────┬──────────────────────────────┘
                               │ ToolRegistry / ModelClient
┌──────────────────────────────▼──────────────────────────────┐
│ 执行层：Bash、Read、Write、Edit、Glob、Grep、job、容器、MCP  │
│ 真正读写文件、运行命令、管理后台进程、返回事实结果             │
└─────────────────────────────────────────────────────────────┘
```

Terminal-Bench 不是从 GUI 启动 XEYO，而是直接使用引擎层外面的一层 Harbor adapter，把每道题放入独立 Docker trial container，接入 DeepSeek 模型，再把最终轨迹交给 verifier。理解 TB 分数时，必须同时看产品层、引擎层和 benchmark adapter，不能只看某一个 prompt 文件。

### 1.2 模型和引擎各自负责什么

| 责任 | 模型负责 | XEYO 引擎负责 |
|---|---|---|
| 理解任务 | 读取题目、分析目标、判断下一步 | 把题目送入正确会话和模型上下文 |
| 选择行动 | 决定调用 Bash、Read、Grep 等工具 | 注册工具、生成 schema、执行权限判断 |
| 文件操作 | 选择路径、写出代码、验证结果 | 把路径映射到正确的宿主/容器工作面 |
| 上下文管理 | 利用历史和工具返回结果 | 压缩、投影、预算、上下文窗口水位 |
| 安全限制 | 无法越过执行层 DENY | 允许、询问、拒绝，并对受保护路径硬限制 |
| 交互输出 | 产生文本、推理、tool call | 流式解析、持久化、重放、事件转发 |
| 评测收尾 | 决定何时认为任务完成 | 强制 max turns、max tool calls、超时和结果收集 |

最关键的一点是：**模型可见的文本不应该承担调度器的职责。** XEYO 当前的设计原则是，模型看到的是状态、事实、工具结果和当前环境信息；真正的权限、上限、拒绝、折叠和停止在执行层完成。

---

## 2. 仓库结构：从哪里读懂 XEYO

根目录位于 `D:\lea\XenYon code`。项目同时包含产品端、服务端、引擎、工具和评测适配器。

### 2.1 顶层目录

| 路径 | 作用 | 初学者应该先看什么 |
|---|---|---|
| [`python/`](python/) | 核心 Python 引擎、FastAPI、CLI、工具和测试 | [`python/ARCHITECTURE.md`](python/ARCHITECTURE.md)、`engine/query_engine.py`、`engine/query_loop.py` |
| [`python/engine/`](python/engine/) | 请求循环、模型调用、预算、上下文、事件、终止 | `query_engine.py`、`query_loop.py`、`write_store.py` |
| [`python/prompt/`](python/prompt/) | system prompt、模型投影前注入、T_now 策略 | `pre_llm_inject.py`、`t_now_strategy.py`、`system_prompt.py` |
| [`python/memory/`](python/memory/) | 历史投影、记忆、压缩、上下文压力 | `runtime.py`、`compact.py` |
| [`python/tools/`](python/tools/) | Bash、文件、Grep、Glob、Web、Memory、job 等工具 | `catalog.py`、`tool_registry.py`、文件工具目录 |
| [`python/permissions/`](python/permissions/) | allow/ask/deny、模式、路径和 MCP 权限 | `policy.py`、`store.py` |
| [`python/server/`](python/server/) | FastAPI 路由、会话池、SSE、控制接口 | `routers/chat.py`、`session_pool.py` |
| [`python/session/`](python/session/) | 会话、JSONL、消息存储、恢复和重放 | MessageStore 相关文件 |
| [`python/msgtypes/`](python/msgtypes/) | 消息和事件的数据结构 | `events.py` |
| [`python/extension/`](python/extension/) | MCP、Skill、插件配置和网关 | `mcp_gateway.py`、`reconcile.py` |
| [`gui/`](gui/) | React + TypeScript 前端，Tauri 壳 | API 客户端和组件 |
| [`tui/`](tui/) | Ink 终端 UI | TUI 入口和服务连接 |
| [`TerminalBench/`](TerminalBench/) | TB 运行器、诊断、oracle 预检和本地证据 | `xeyo_harbor_agent.py`、`zero/` |
| [`docs/`](docs/) | 设计说明、事故归因和实验记录 | TB 归因文档 |

### 2.2 推荐阅读顺序

如果读者从未看过源码，建议按这条顺序理解：

1. 先读 [`python/ARCHITECTURE.md`](python/ARCHITECTURE.md)，获得模块地图。
2. 再读 [`python/engine/query_engine.py`](python/engine/query_engine.py)，理解一次会话由谁持有状态。
3. 然后读 [`python/engine/query_loop.py`](python/engine/query_loop.py)，理解每一个模型轮次怎样发生。
4. 接着读 [`python/permissions/policy.py`](python/permissions/policy.py)，理解为什么工具不一定能执行。
5. 再读 [`python/prompt/pre_llm_inject.py`](python/prompt/pre_llm_inject.py) 和 [`python/prompt/t_now_strategy.py`](python/prompt/t_now_strategy.py)，理解动态状态怎样进入模型。
6. 最后读 [`python/tools/catalog.py`](python/tools/catalog.py)、[`python/tools/tool_registry.py`](python/tools/tool_registry.py) 和 [`TerminalBench/xeyo_harbor_agent.py`](TerminalBench/xeyo_harbor_agent.py)，把产品引擎和 TB 适配器连起来。

不要从 GUI 组件、某个工具的 UI 包装或 TB 的 verifier 开始。它们都可能是局部视角，容易让人误以为 XEYO 只是“一个聊天窗口”或“一个 Bash wrapper”。

---

## 3. 一次请求的完整生命周期

下面用一次“用户让 XEYO 修改代码并运行测试”的请求说明实际链路。

### 3.1 请求进入系统

```text
用户输入
  │
  ├─ GUI：React/Tauri 通过 HTTP/SSE
  ├─ TUI：Ink 连接 FastAPI
  └─ CLI：直接进程内调用或 attach 到服务
  │
  ▼
server/routers/chat.py
  │  找到或创建 session
  ▼
session_pool.py
  │  取出该会话的 QueryEngine
  ▼
QueryEngine.submit_message()
  │
  ▼
engine/query_loop.py
```

`QueryEngine` 是会话的总拥有者。它保存消息状态、会话状态、工具注册表、预算追踪、模型客户端、终止信号、回溯状态和 prompt assembler。HTTP 层主要负责传输，不应该自己复制一套 agent 循环。

### 3.2 每个模型轮次发生什么

一个轮次大致如下：

```text
1. 读取当前会话的 canonical message store
2. 根据压缩游标和上下文预算生成 model projection
3. 在下一次采样前装配当前 T_now 状态
4. 生成 system prompt、工具 schema 和历史消息
5. 调用模型的 streaming API
6. 解析文本 delta、reasoning delta 和 tool call
7. 对每个 tool call 先过 permission policy
8. 允许的调用进入工具执行器；需要确认的调用进入 ask；拒绝的调用得到中性错误
9. 工具结果写入消息存储并产生 ToolResultEvent
10. 继续下一轮，直到模型结束、达到上限、超时、取消或发生不可恢复错误
11. 生成最终 result、usage、cost 和 trajectory
```

模型请求不是简单的“把全部历史拼在一起”。引擎会先建立面向模型的投影：历史记录是事实存档，投影是本轮模型实际能看到的有限上下文。压缩、折叠、工具结果截断、T_now 和 system channel 都发生在这层边界附近。

### 3.3 工具调用的真实链路

```text
模型输出 tool call
       │
       ▼
native/XML parser
       │  验证工具名和参数
       ▼
ToolRegistry
       │  找到 ToolMeta、schema、执行函数、路由信息
       ▼
permissions/policy.py
       │
       ├─ allow → 执行
       ├─ ask   → 生成等待权限事件
       └─ deny  → 返回 Permission denied / 事实型错误
       │
       ▼
具体工具
       │
       ├─ Bash：宿主或 Docker container
       ├─ Read/Write/Edit：容器文件系统层或本地文件系统
       ├─ Glob/Grep：路由到正确的文件系统
       └─ job：启动、查询、终止后台进程
       │
       ▼
ToolResultEvent + MessageStore + 下一次模型上下文
```

工具调用有三个经常被混淆的概念：

- **工具存在**：schema 是否出现在模型的工具数组中。
- **工具能被调度**：ToolRegistry 是否找到它，路由是否正确。
- **工具能否执行**：权限策略和路径/容器状态是否允许。

其中任何一层出问题，模型看到的结果都可能只是一个错误文本。对 TB 来说，这种错误既可能导致真实答错，也可能导致 verifier 根本没拿到可判定的产物。

---

## 4. XEYO 的状态模型：存档、投影、事件不是一回事

### 4.1 Canonical history：系统真正保存的事实

MessageStore / transcript 是会话的 canonical 记录，包含用户消息、模型消息、tool call、tool result、system note 和相关元数据。它用于：

- 恢复会话；
- 重放和调试；
- 生成轨迹；
- 支持 rewind / checkpoint；
- 在上下文压缩后重新生成模型投影。

canonical history 不等于模型每次看到的内容。历史可以比当前上下文长得多。

### 4.2 Model projection：本轮真正送给模型的内容

model projection 是对 canonical history 的一次视图：

```text
canonical history（完整）
        │
        ├─ 取当前窗口范围
        ├─ 应用压缩和折叠
        ├─ 处理工具结果溢出 / spill
        ├─ 合并可持久记忆和 system prompt
        ├─ 装配 T_now
        └─ 加入工具 schema
        ▼
本轮 api_messages + tools
```

模型只对 projection 负责。调试 TB 低分时，必须分别回答：

1. 文件最终是否写对了？这是 canonical / container 状态问题。
2. 模型有没有看到正确的工具结果？这是 projection / spill 问题。
3. verifier 有没有运行？这是评测基础设施问题。

如果只看最后的 agent 文本，三类问题会被混成“模型没做对”。

### 4.3 Event stream：面向 UI 和观测的事实流

事件流包含 `AssistantDelta`、`ReasoningDelta`、`ToolCallEvent`、`ToolResultEvent`、`UsageEvent`、压缩事件、权限事件和最终结果。事件流适合实时显示和生成 trajectory，但不是唯一的事实来源：

- 事件可以被前端丢弃或延迟；
- 消息存储需要支持恢复；
- 评测 adapter 会额外记录容器、模型、成本和环境 metadata。

因此，分析分数时要同时看 verdict、trajectory、metadata 和容器状态，不能只看 UI 里的最后一条文字。

---

## 5. Prompt、system prompt 和 T_now

### 5.1 稳定信息与易变信息

XEYO 将 prompt 内容分成两类：

| 类别 | 例子 | 处理方式 |
|---|---|---|
| 稳定信息 | 工具的基本语义、产品身份、长期不变的使用事实 | system prompt / tool schema |
| 易变信息 | 当前 job、权限状态、待处理事件、压缩状态、运行时变化 | T_now 注入管线 |

易变内容不应被不断拼进历史用户消息，也不应散落在多个巨型模块里。当前权威装配面是 [`python/prompt/pre_llm_inject.py`](python/prompt/pre_llm_inject.py) 和 [`python/prompt/t_now_strategy.py`](python/prompt/t_now_strategy.py)。

### 5.2 T_now 的三条管道

T_now 的边界是：**一批工具执行完成、下一次模型采样开始之前**。在这个边界，三类东西被分别处理：

1. **用户输入管道**：运行中输入先排队，在安全边界进入真正的 `role=user` 历史消息；不打断当前工具批次。
2. **引擎当前状态管道**：值发生变化时，以 system note / system channel 形式进入投影；值不变时可以去重。
3. **引擎事件管道**：工具或系统事件按 drain 语义投递；事件不可随意去重，否则会静默丢信息。

每一个 T_now 块都必须在登记表中有明确身份、预算、去重属性和存在原因。登记表是 [`python/prompt/pre_llm_inject.py`](python/prompt/pre_llm_inject.py) 中的 `T_NOW_BLOCK_REGISTRY`，目前有数量上限，防止“每遇到一个边角需求就往模型上下文增加一块”。

### 5.3 当前默认 system channel

当前默认策略是 `system_channel`：把动态状态作为原生 system 消息追加到模型投影尾部。它的优势是：

- 状态是引擎注入的，不冒充用户或模型；
- 不进入 MessageStore 的普通对话消息；
- 不进入 tools 数组；
- 模型有机会读取状态，但不能把状态块当成自己刚刚调用的工具。

不同 provider 的协议转换由 adapter 处理。对于 Anthropic 风格请求，system 消息需要被提升到顶层 system 字段；对于 OpenAI 系列，保留 `role=system`。

### 5.4 旧的 `xeyo_env_notice` 为什么会伤害 TB

旧方案把环境状态伪装成类似：

```text
assistant(tool_use: xeyo_env_notice)
tool_result(...)
```

这种形态和模型自己调用工具的轨迹完全相似。模型可能推断“这是我拥有的工具”，随后真的调用 `xeyo_env_notice`，引擎再把结果作为一轮工具结果回灌，形成自催化循环。

已观测事实是：旧 `env_channel` 有 216 次提及、65 次幻觉式自省和 1 次真实调用；`X/50` 之类运行时文本也曾大量进入轨迹。2026-09-15 后默认改为原生 system channel，并增加机器执行层守卫。这个修复解决的是“模型被错误 affordance 诱导”的结构性问题，不是给模型增加一段更强的劝告。

这体现了 XEYO 的一条设计原则：**模型可见文本应当提供信息；引擎的限制应在执行层实现。**

---

## 6. 上下文、记忆与压缩

### 6.1 为什么不能只看 `prompt_tokens`

推理模型的响应通常同时包含：

- 可见回答 token；
- reasoning token；
- 工具调用和工具结果；
- 历史消息和 system prompt。

部分厂商 usage 字段会把 reasoning token 计入成本，却不把它们完整反映在 `prompt_tokens` 或下一次请求的上下文水位里。如果引擎只相信 `prompt_tokens`，它可能误以为还有很多空间，或者在另一个地方错误触发压力压缩。

当前 runtime 增加了 `reasoning_tokens_in_context()` 和压力水位补齐，以便上下文判断更接近模型真实占用。

### 6.2 C0 / C1 / C2 的概念

XEYO 的记忆与压缩可以理解为三层：

- **C0：原始近期上下文**。保留最近的用户、模型和工具交互，适合模型直接继续工作。
- **C1：结构化或摘要化的历史**。当旧内容不适合继续完整放入窗口时，保留任务状态、重要事实和关键结果。
- **C2：更高阶的长期压缩/摘要**。按开关和预算使用，目标是减少长期会话体积，但需要防止摘要改变事实。

`compact.py` 和 `memory/runtime.py` 负责在 canonical history 和 model projection 之间做这层转换。压缩不应该破坏 canonical transcript；它改变的是本轮模型看到的投影。

### 6.3 已确立的上下文硬编码问题

旧逻辑把上下文窗口按 `65536` 处理。对 DeepSeek flash 的真实配置，当前验证结果是 `context_limit=1000000`。旧硬编码导致压力阈值：

```text
压力阈值 = 窗口大小 − 54,199
```

在 582 个回合中：

| 窗口假设 | 触发压缩的回合 |
|---|---:|
| 错误的 65,536 | 376 / 582 = 65% |
| 真实的 1,000,000 | 0 / 582 |

错误窗口下实际大约在 11,337 token 就触发压力逻辑；真实窗口下对应触发点是 945,801 token。压缩痕迹和裁决结果存在强相关：5 个 wrong_answer 中 4 个有压缩痕迹，green 中 20 个有 8 个痕迹。但这还不是因果证明，因为难题本来就可能产生更长轨迹。

正确的表述是：**这是一个高优先级结构性 bug，证据足以修复和做 A/B，不足以单凭相关性声称它造成了全部 wrong_answer。**

### 6.4 当前窗口配置

当前引擎包含已知模型窗口表：DeepSeek flash 走 1M；未知模型走更保守的 128K，并允许请求配置覆盖。真实引擎验证已经确认：

- provider 是 DeepSeek；
- `context_limit=1000000`；
- 请求体包含 `thinking: {type: enabled}`；
- 请求体包含 `reasoning_effort: high`。

这说明推理档位不是只写在本地配置里，而是确实被发送到 provider。

---

## 7. 工具系统：从 schema 到真实文件

### 7.1 工具目录和最小工具面

完整工具目录包含 Bash、Read、Write、Edit、Glob、Grep、TodoWrite、job 管理、Memory、Web 工具、Git、NotebookEdit、Agent、MCP 等。为了 benchmark 的稳定性，TB 适配器当前使用最小工具面：

```text
Bash
Read
Write
Edit
Glob
Grep
Agent
job_output
job_list
job_kill
```

由 `XEYO_TOOL_SURFACE=minimal` 选择最小面；`XEYO_BENCH_MINIMAL=1` 还会排除需要人机交互的 AskUserQuestion、Screenshot、SendToWeChat、XeyoUI。两者是不同层次的开关：前者选择 benchmark 的工具集合，后者避免人类交互工具干扰无人值守评测。

最小工具面的设计目标不是让模型能力变弱，而是降低 schema 噪声、交互歧义和不可复现的外部依赖。代价是：如果某个核心工具没有正确接通，模型可能退回 Bash，轨迹会变长，工具统计会失真。

### 7.2 Bash 与专用文件工具

理论上，模型可以用 Bash 完成所有事情，但专用工具有几个优势：

- 返回结构更稳定；
- 更容易做路径权限检查；
- 更容易知道文件是否被读取过；
- 不需要模型自己拼接不同 shell 的命令；
- 可以把宿主文件系统和容器文件系统路由到同一抽象层。

因此当前最小面保留 Bash，同时保留 Read/Write/Edit/Glob/Grep。正确的运行状态应该是：模型可以根据任务自主选择 Bash 或专用工具，而不是因为专用工具被错误路由而只能使用 Bash。

### 7.3 容器文件系统层

TB 的任务在 Docker container 中执行。XEYO 同时有宿主 Python 进程和容器工作面：

```text
宿主机 Python 进程
  │
  ├─ 管理模型请求、会话、事件和权限
  ├─ 通过 Docker SDK 执行容器命令
  └─ 需要把路径转换为 container path
           │
           ▼
Docker trial container
  ├─ 题目仓库
  ├─ /root 或题目指定工作目录
  ├─ python、git、编译器、题目依赖
  └─ verifier 最后真正检查的文件系统
```

当前 [`python/tools/container_fs.py`](python/tools/container_fs.py) 提供容器文件系统抽象；`fileio`、`Grep`、`Glob`、Read/Write/Edit 通过它判断 exists、isdir、getsize、listdir 和文件内容。`working_directory` 会传到容器执行，而不是被 Python 进程静默忽略。

### 7.4 旧的容器错位为什么会直接影响答题

旧实现中曾有这些错位：

1. system prompt 显示宿主 scratch 路径，但 Bash 实际在 container 中执行；
2. Bash 的 `working_directory` 在容器分支被静默忽略；
3. Read/Write/Edit/Glob/Grep 某些请求被当成 L2 路由错误返回，模型只好退回 Bash；
4. 工具输出过长时 spill 文件落在宿主 cwd，再把宿主路径告诉模型；模型在容器中无法读取它；
5. `job_kill` 只查宿主 registry，模型能看到容器后台 job，却杀不掉；
6. 容器 prompt 曾经说“POSIX 工具通常不存在”，和真实镜像相反。

这些问题不是 prompt 小瑕疵，而是“模型认为自己拥有一个工作面、执行器却在另一个工作面”的协议错误。典型后果是：

- 模型读不到刚刚生成的证据；
- verifier 看的是 container 文件，而模型误以为写到了宿主文件；
- 工具错误诱发多轮重试；
- 任务最终可能是 `verifier_invalid`，而不是正常的 wrong answer。

当前修复把路径、cwd、溢出文件、job kill 和目录建议统一到容器路由；但目前只在 `alexgshaw/regex-log:20251031` 这一镜像上做过完整端到端验证，不能把它自动外推为所有 TB 镜像都已证明无问题。

### 7.5 Bash 提升和后台 job

长时间 Bash 命令可以变成后台 job：

```text
模型发 Bash
  │
  ├─ 短命令：等待并直接返回结果
  └─ 长命令：进入 job registry，返回 job id
               │
               ├─ job_list：查看状态
               ├─ job_output：取结果
               └─ job_kill：终止进程
```

旧逻辑用 45 秒一刀切的 promote threshold，截断了题目自己的 300/420 秒 timeout 分级。当前 `promote_threshold_for()` 使用 `min(300s, timeout × 0.8)`，并把容器后台 job 纳入 kill 路径。

然而 job 机制本身也有成本。9 月 14 日轨迹中 job 管理调用约 198 次，占 assistant 轮次约 12%；其中 job_output 160 次、job_list 22 次、job_kill 16 次。它未必是根因，但会消耗上下文、增加等待状态和出错机会，所以必须和真实答错分开统计。

当前针对这条成本链的修复是事件驱动的：后台 job 结束时，registry 的完成事件和人类下一轮的 pending 补投都会附带有界的输出尾部（单 job 8,000 字符、批次 24,000 字符），不再在模型可见文本中要求“再调用 `job_output`”。`job_output` 仍保留为显式补读工具，用于读取完整 ring 的增量内容，但它不再是完成通知后的默认 polling 步骤。Docker headless 回退路径也把完成输出直接放进完成事件，并在投递后标记 delivered；若模型显式使用 `wait=true`，Docker 后台表现在也由完成/取消事件唤醒，不再固定每 250ms 轮询。

因此，理想路径从：

```text
启动 job → job_output → 仍运行 → job_output → … → job_output
```

变成：

```text
启动 job → runtime 等待完成 → JobCompleted 事实 + 有界输出尾部
```

---

## 8. 权限系统：限制发生在执行层

XEYO 的权限决策是三态：

```text
allow  → 工具可以执行
ask    → 需要用户或外部控制面确认
deny   → 工具不执行，返回事实型拒绝结果
```

权限模式包括 `always`、`risk`、`never` 等，benchmark 适配器设置为无人值守的 `never` 语义，以便已允许的 benchmark 工具不因人类确认而停住。这里的 `never` 不是“允许一切”，而是“不要进入人类问答式确认流程”；路径保护和硬 deny 仍然存在。

权限系统还包含：

- 当前轮次的权限快照；
- live mode 收紧立即生效，放宽延后生效；
- 受保护路径禁止写入；
- MCP 停用后先 DENY，再看 grant，grant 不能绕过停用门；
- 子代理和 side mode 的权限上下文隔离。

这套设计故意不靠模型可见的“警告文本”来保证安全。模型可能忽略一句“请不要这样做”，执行层不能忽略一次 DENY。

---

## 9. 模型协议和 DeepSeek 路径

XEYO 通过 provider/model adapter 调用模型，常见形式是 OpenAI-compatible streaming 请求。一次请求包含：

- system 和历史消息；
- 当前可用工具 schema；
- 模型名、provider、API base；
- 上下文窗口和 reasoning 配置；
- streaming / abort 控制。

一次响应可能交错返回 reasoning delta、可见文本 delta、tool call name/arguments、usage 和 finish reason。因此 query loop 不能只等待一个最终字符串；它需要增量解析、把 tool call 与后续 tool result 配对、在 abort 时修复未配对调用，并把事件写入 session。

已验证的 TB DeepSeek 路径包括：

```json
{
  "context_limit": 1000000,
  "thinking": {"type": "enabled"},
  "reasoning_effort": "high"
}
```

这回答了一个常见疑问：**当前 XEYO 不是把 reasoning 配置写在本地却没发给模型；该配置确实出网。**但“reasoning 开启”不等于一定拿到官方表的分数，因为工具面、容器、判分协议、重试策略和题目环境仍然不同。

---

## 10. 会话、回溯、写入和恢复

XEYO 不把一次请求当成不可恢复的临时脚本。它维护 session id、JSONL 或等价的持久化消息、event stream、checkpoint/rewind、文件写入记录、usage、成本元数据、子代理和后台 job 状态。

### 10.1 写文件的安全路径

```text
模型参数
  → 路径解析 / cwd 归一化
  → workspace / container 路由
  → 权限检查
  → 临时文件或原子写入
  → 目标文件替换
  → 事件与会话记录
```

`engine/write_store._atomic_write` 和文件工具共享路径与路由逻辑，目标是避免模型在拿到半写文件时继续执行，也避免宿主和容器看到不同版本。

### 10.2 Rewind 和压缩的关系

rewind 可以改变历史投影和文件状态；历史被改写后，T_now 的去重台账必须失效，否则引擎可能认为某个状态已经发送过而不再发送。正确顺序是：

```text
先完成历史改写 / 压缩 / 回溯
       │
       ▼
清理受影响的 T_now note 台账
       │
       ▼
下一轮按当前事实重新注入
```

这也是为什么“把动态提醒简单追加到历史”会产生长期脏状态：它无法区分当前事实和过去某一轮事实。

---

## 11. MCP、Skill、Agent 和扩展层

扩展层不是 TB 低分的主要根因，但它是 XEYO 的完整设计的一部分。

### 11.1 配置和工具快照

扩展配置以 `.xeyo/settings.json` 为主，工作区级覆盖 home 级。默认 `enabled_extensions` 关闭；MCP server、plugin、skill 各自有 enabled 状态。

原生 MCP 工具面在会话 attach 时形成快照，之后 tools 数组冻结，避免会话中途变化造成 provider 缓存和模型 schema 不一致。会话内启停通过 `Mcp` 网关和 reconcile 推送状态，而不是偷偷改原生 tools 数组。

### 11.2 MCP 网关

扩展开启后，`Mcp` 网关支持 list、describe、call、resources、read_resource。call 的身份从已知工具集解析，不从不可信参数外通道猜身份。停用工具先经过 DENY；grant 不得绕过停用状态。

### 11.3 Skill 和 Agent

Skill 影响能力说明和可调用方式；Agent 影响子会话/子任务的执行上下文。TB 当前设置 `XEYO_MULTI_AGENT=0`，因为多 agent 会改变成本、工具竞争、上下文和 verdict 归因；这不是 XEYO 产品层永久禁止多 agent，而是 benchmark 为可控性选择单 agent。

---

## 12. Terminal-Bench 2.1 是怎样接入 XEYO 的

### 12.1 Harbor adapter 的职责

[`TerminalBench/xeyo_harbor_agent.py`](TerminalBench/xeyo_harbor_agent.py) 是把 XEYO 引擎接到 TB/Harbor 的适配器。它负责：

1. 为每道题创建 trial workspace 和 Docker container；
2. 在 `run()` 阶段把 container id 作为显式 runtime fact 和 ContextVar 传给 XEYO 工具；不再在并发 `setup()` 阶段写进程级 `XEYO_DOCKER_CONTAINER`；
3. 设置 benchmark 环境变量；
4. 创建 XEYO engine 和 DeepSeek model client；
5. 执行事件循环，收集最终结果、trajectory、usage、cost 和 metadata；
6. 让 Harbor/verifier 在同一题目的容器状态上判分。

这个 adapter 不是 verifier，也不是题目本身。它是“XEYO 怎样参加 TB”的边界层。

### 12.2 当前 benchmark 环境变量

```text
XEYO_BENCH_MINIMAL=1
XEYO_PERMISSION_MODE=never
XEYO_BASH_PROMOTE_MS=300000
XEYO_MULTI_AGENT=0
XEYO_TOOL_SURFACE=minimal
XEYO_DOCKER_CONTAINER=<本题 trial container>
```

adapter 使用 DeepSeek provider、thinking enabled、high reasoning，并以单次尝试为主。单次尝试意味着没有官方某些自报协议里可能存在的多次采样、重试、筛选或人工调优收益。

### 12.3 题目工作区和实际判分对象

一题的关键对象不是宿主上的 scratch 文件夹，而是 verifier 最终读取的 trial container 文件系统：

```text
题目镜像
  + 任务初始化文件
  + XEYO 在容器中运行的命令 / 文件操作
  + 任务完成后的 container 状态
  → verifier
  → green / wrong_answer / verifier_invalid / timeout
```

因此，任何只在宿主落盘、容器看不到的“成功”都不算任务成功；任何模型看不到但容器已经存在的文件，也可能造成模型继续重复工作。早期 XEYO 的宿主/容器错位正是这个边界上最危险的 bug 类型。

---

## 13. 9 月 14 日 37 题数据：应当怎样读

这是目前最重要的一批已确立事实。裁决来自 [`TerminalBench/zero/verdict.py`](TerminalBench/zero/verdict.py) 的分类口径。

| 裁决 | 题数 | 含义 |
|---|---:|---|
| `green` | 20 | agent 产物存在，verifier 正常运行且通过 |
| `wrong_answer` | 5 | verifier 正常运行，但答案/产物确实错误 |
| `verifier_invalid` | 11 | verifier 没有在有效条件下完成，不能归因于 agent 答错 |
| `agent_timeout` | 1 | agent 在允许时间内没有完成 |
| 合计 | 37 |  |

真答错题名是：

```text
gpt2-codegolf
make-doom-for-mips
model-extraction-relu-logits
pytorch-model-cli
rstan-to-pystan
```

```text
表观分 = green / 全部题数 = 20 / 37 = 54.1%
有效分 = green / (green + wrong_answer + agent_timeout)
       = 20 / (20 + 5 + 1) = 76.9%
```

如果把 timeout 也从能力分母中剔除，只计算 verifier 正常完成的题，则是 `20 / 25 = 80%`；但正式报告应保留 timeout，因为 timeout 也是一次运行没有完成，不能随意删除。

另一个极端样本 `p6-tail23-b10` 的表观分是 75%，但清洗后有效分是 100%，真答错为 0。这说明“表面 75%”不能自动解释成模型能力只有 75%。

### 13.1 11 个 verifier_invalid 的具体性质

已归因的基础设施异常包括：`uv` 不存在或未被判分脚本找到、CPython/uv 安装受 32 MB 限制、NVIDIA 轮子或其他依赖下载超时、apt/dpkg 锁争用、判分脚本缺少 uv，以及并发太高导致带宽互抢和安装互相阻塞。

这类题的正确结论不是“XEYO 答错”，而是“这次实验不能用来评价 XEYO 的答题能力”。如果把它们直接算作 0，会把评测环境的失败混入模型能力。

### 13.2 缺失命令不能误判成 XEYO bug

抽样轨迹中 `command not found` 共 59 次、涉及 29 题，主要是题目镜像真实缺少 `python3`、`git`、`ps`、`xxd` 等命令。5/5 抽样镜像没有 `rg`，但存在 `grep`/`find`。

所以：镜像没有某个命令是题目环境事实；XEYO 没有提供可用替代路径才可能是 prompt/工具问题；XEYO 把真实存在的工具路由成错误才是引擎 bug。不能把每个 `command not found` 都归到 XEYO。

### 13.3 历史 89 题汇总不能直接当作当前单次成绩

工作树里还存在旧的 head/tail 汇总记录，例如某份历史汇总曾显示最新 green 为 `61/89 = 68.5%`，另有“ever green”统计为 69。它们来自不同批次、不同部分或不同尝试的聚合，不能等价于“当前修复后的 XEYO 在完整 89 题上跑了一次得到 61 题”。

报告 89 题时，必须注明：题集、运行批次、模型、工具面、并发、重试次数、verifier 版本和是否清洗 `verifier_invalid`。缺少这些字段的“89 题分数”只能作为历史线索，不能作为当前基线。

---

## 14. 低分根因分层归因

下面把原因按“已证实、强线索、正常题目事实、尚未证明”分开。

### 14.1 官方 90.6 与当前实验不是同一口径

这是比较问题，不是 XEYO 代码 bug。已知对照是：同模型配对的 `gpt-5.6-sol`，厂商官方口径为 `88.8`，公开受控榜对应约 `76.18`，差约 `12.6` 个百分点。这不是在声称 DeepSeek V4.1-Flash 的公开可比成绩正好也是 76.18%，而是证明“厂商分数和公开受控分数可能不是同一协议”。官方数字可能包含不同的 harness、prompt、工具面、重试或采样次数、timeout/verifier 处理、环境准备方式，以及统计和缺失题处理。

因此，XEYO 清洗后约 77% 并不等于“比官方低 13 个百分点就全部是 XEYO bug”。至少有一部分差距在协议层，不能从单次分数反推代码原因。

### 14.2 verifier 基础设施失败把表观分压低

37 题中 11/17 个非 green 结果属于 verifier_invalid，约占非绿题的 65%。这些题不能直接成为模型能力的失败样本。它们让表观分从有效的约 77% 看起来降到 54.1%。这一层的解决方式是 preflight、低并发、依赖准备和 verdict 分类，不是给模型再写一段 prompt。

### 14.3 上下文窗口硬编码造成错误压缩

旧硬编码把 1M 模型当成 65536 窗口，导致 65% 的采样回合进入错误的压力判断。压缩会改变模型能看到的历史、工具结果和任务证据，因此有理由怀疑它影响了部分真实错误。

但目前只能说：触发差异已实测；wrong_answer 和压缩痕迹有相关性；bug 已修复并有单测；尚未完成同题 A/B 证明每个错误都由压缩导致。严谨报告不能把相关性改写成因果率。

### 14.4 宿主/容器工作面不一致

这是最直接的工程结构性风险之一。TB verifier 看的是容器，旧版部分工具和提示却把宿主 scratch 当成工作面。对于代码题、文件转换题、模型下载题和需要读取大型输出的题，工作面错位会导致结果写错地方、证据读不回来、模型重复执行、verifier 看到的内容与 agent 认为的内容不同，以及判分失败或答案错误。

当前已经把容器路径抽象扩展到 Read/Write/Edit/Glob/Grep、spill、working_directory、job kill 和目录建议，并完成一个镜像的端到端验证。剩余风险是其他镜像的工具和权限差异。

### 14.5 旧 `xeyo_env_notice` 伪工具诱发自循环

这是一类 prompt/协议形态 bug，而不是模型“太笨”。它把引擎注入伪装成模型自己的工具调用，造成模型反复调用、host 继续回灌工具结果、注意力被环境状态占用、轮次和上下文快速膨胀。

它已于 9 月 15 日通过 system channel 和执行层守卫修复。修复后需要用轨迹指标验证：`xeyo_env_notice`、`X/50`、伪工具轮次是否归零或显著下降。

### 14.6 专用工具路由失败造成 Bash 过度使用

已知工具分布是 1378 个 assistant 轮中：

```text
Bash        1405
job_output   160
job_list      22
job_kill      16
TodoWrite     14
Read           6
其他 13 个工具全部为 0
```

这不是“模型喜欢 Bash”这么简单。抽样已发现专用工具曾经被错误返回 L2 路由错误，模型于是退回唯一可用的 Bash。当前最小工具面保留专用文件工具并修正容器路由；是否最终改善答案，需要受控复测。

### 14.7 job 管理开销和轮次浪费

job 管理约占 12% 轮次，更像放大器而不是单独根因：等待会消耗 token 和 wall time，轮询会使上下文变长，kill 不到容器 job 会让无效任务持续，过早后台化会把简单命令变成多步骤协议。

当前通过按 timeout 计算 promote threshold、修复容器 kill 和保留最小 job 工具面处理。应在复测中单独统计 job 等待时间、job 轮询次数和最终任务成功率。

### 14.8 5 个真实 wrong_answer 和 1 个 timeout

这部分不能通过 verdict 清洗删除。它代表至少有一部分问题仍然来自模型对具体题目的理解或实现错误、工具返回不足、上下文压缩或工作面错位、时间预算、依赖下载或测试执行过慢。

在没有逐题重跑前，不能把 5 题全部归到模型，也不能把 5 题全部归到引擎。正确做法是逐题看 trajectory、container diff、verifier log 和压缩记录。

---

## 15. 为什么“清洗以后”不是 90%，而是约 77%

```text
37 题 = 20 green + 5 wrong_answer + 11 verifier_invalid + 1 timeout
清洗后的有效集合 = 20 green + 5 wrong_answer + 1 timeout = 26 题
有效分 = 20 / 26 = 76.9%
```

清洗不会重新让 5 个 wrong_answer 通过 verifier，不会把 timeout 变成完成，不会抹掉工具路由、压缩、容器错位造成的真实损失，不会把 single-trial 协议变成官方多试次协议，也不会让 37 题自动等于 89 题总体。

所以“清洗后只有 77”并不矛盾：在这批能够正常判分的题中，XEYO 当时确实还有大约四分之一没有拿到 green；基础设施失败只是额外把表观分再压低了一层。

---

## 16. 已完成的修复和它们解决的问题

### 16.1 TB 评测侧的零费用保护

[`TerminalBench/zero/`](TerminalBench/zero/) 是评测辅助层，且被 gitignore，不污染主仓库。已完成：

| 文件/模块 | 作用 |
|---|---|
| `zero/verdict.py` | 将 green、wrong_answer、verifier_invalid、agent_timeout 分列，输出表观分和有效分 |
| `zero/preflight.py` | 用 oracle/reference solution 先检查判分装置，不调用模型；非 0 退出码阻止付费评测 |
| `zero/diag_set.py` / `diag_set.json` | 成本感知诊断子集，9 题约 ¥2.37；也可压到 4 题做最小 A/B |
| `zero/make_budget_yaml.py` | 生成低并发预算配置 |
| `zero/*.yaml` | 默认并发压到 2，避免 dpkg 锁、下载带宽和安装过程互相争用 |
| `xeyo_harbor_agent.py` | 写入 benchmark 环境 metadata，以显式 runtime/ContextVar 绑定容器，并设置最小工具面 |

这些改动的核心意义是：**先证明评测装置能判，再花模型钱。**

### 16.2 容器和文件工具侧

已新增或接通：

- [`python/tools/container_fs.py`](python/tools/container_fs.py)：容器文件系统层；
- `tools/fileio/fsprobe.py`：按路由判断 exists、isdir、getsize；
- `tools/grep_tool/rg_fallback.py`：没有 `rg` 时映射到 `grep` 和 `find`；
- `fileio/text.py`：Read/Edit/Write/NotebookEdit 汇聚到统一路由；
- `fileio/rg_subprocess.py`、`glob_tool`、`grep_tool`：Glob/Grep 使用正确工作面；
- `engine/write_store._atomic_write`：原子写入遵循容器路由；
- spill / truncate：溢出文件落在容器内，模型拿到的是容器可读取的路径；
- `job_tools.py`：job kill 覆盖容器后台 job；
- `job_tools.py`：`job_output(wait=true)` 只依据当前 `ExecutionContext` 判断容器路由；显式 local context 会屏蔽遗留 `XEYO_DOCKER_CONTAINER`，避免上一题的环境变量把本地等待错误降级成额外轮询；
- `system_prompt.py`：CWD 显示容器 pwd；
- `bash_tool.py`：容器 working directory、生效的 timeout promote、容器后台取消；
- `bash_tool/prompt.py`：容器描述与真实环境一致。

### 16.3 上下文与 T_now 侧

- DeepSeek flash 识别为 1M，上下文未知时使用 128K 保守值；
- reasoning token 进入 runtime 压力水位；
- `system_channel` 成为默认 T_now 声道；
- 旧 `xeyo_env_notice` 伪工具形态不再作为默认注入；
- wrap_up/runtime_budget 等误导性模型可见预算文本撤销，收尾由执行层强制；
- 机器守卫防止旧的 `X/50` 运行时文本重新进入模型。

### 16.4 工具面侧

- 增加 `MINIMAL_SURFACE_TOOLS`；
- benchmark 默认启用 Bash、Read、Write、Edit、Glob、Grep、Agent 和 job 三件套；
- 容器路由下不再把能执行的专用调用返回成 L2 路由错误；
- 保持多 agent 关闭，避免评测归因和成本失控。

### 16.5 本轮执行层收敛（不涉及 WSC/压缩策略）

说明文档指出的几个高风险事实现在有了机器侧结构，而不是只靠模块约定：

- `engine/execution_context.py`：定义一次 submit 的 session、cwd、runtime、container、workspace、权限范围、trace 和 deadline；`workspace_context.py` 保留旧 API 作为兼容入口。显式 `runtime=local` 会屏蔽残留的进程级 Docker 环境，且 `container_fs`、`exec_channel`、Bash、job 工具不再在下游把该 env 重新恢复，避免跨 trial 串容器。
- `tools/base_tool.py`：`ToolResult` 增加 `status`、`error_kind`、`retryable`、`side_effect`、`action_id`；旧工具即使只返回 `is_error + content`，也会得到稳定的 `INTERNAL` 分类。
- `tools/error_taxonomy.py`：统一未知工具、参数错误、权限错误、超时、临时基础设施错误、取消和动作结果未知等类别。
- `engine/action_journal.py`：副作用工具在执行前记录 `executing`，完成后记录 `completed`；断流/取消落 `unknown`，恢复时同一 action 不会被盲目重复执行。动作账本的读取和写入在同一 session 锁内完成，避免并发恢复重复启动副作用。
- `engine/abort.py` / `engine/cancellation.py`：取消从孤立 boolean 升级为可组合的父子 scope。`batch → task → tool/job → process` 可以传播取消原因；子节点本地超时不会反向取消父节点。detached job 没有显式父 scope 时保持独立，避免普通 turn 收尾误杀已经交还后台的进程。
- `engine/cancellation.py` 与 session pool：detached job 现在挂在 session 生命周期根上；普通 turn interrupt 不会杀它，删除 session 时统一向 job/process 传播 `session_deleted`，同一 session id 重用时创建全新的根。
- `server/job_registry.py`：每个后台 job 都有自己的 cancellation scope；`job_kill` 通过该 scope 收口，显式传入 `parent_abort` 时才继承父 scope。这样 job 的“归属 session”和“取消父节点”不再靠隐式共享一个 controller 推断。
- job 终态 detail 保留真实取消原因：`job_kill` 仍报告 `killed by job_kill`，session 删除则报告 `killed by session_deleted`，避免恢复与 verdict 诊断把生命周期收口误归因成模型主动 kill。
- `engine/scheduler.py`：多 Agent batch 创建的 task abort 改为 batch 的子节点；batch 取消会传播到正在运行的 task，task 自己失败或超时只收口本 task。
- `tools/tool_registry.py` / `engine/execution_context.py`：当前模型可见工具面同时记录稳定的策略身份（如 `minimal@1`）和具体 schema `sha256` 指纹，并写入每轮执行上下文；隐藏工具不计入，既能区分“选了哪种工具面”，也能确定识别该工具面是否发生协议漂移。
- `engine/runtime_capabilities.py`：每轮对执行面做无副作用能力预检（可写性、Git/Python/Node/编译器/包管理器、磁盘余量）。local 才读取宿主能力；Docker/SSH 不冒用宿主 `PATH`，未知能力明确记为 `None`，并生成稳定 capability id。
- `engine/runtime_profile.py`：把 `product-local`、`terminal-bench-2.1`、CI、SSH 等执行档案规范成显式对象和稳定 `profile_id`。TB adapter 现在明确传 `terminal-bench-2.1`，环境变量仍只作为兼容回退，不再是唯一的模式身份。
- `build_default_engine()` 现在正式接收 Harbor adapter 已使用的 `runtime`、`container_id`、`workspace_id` 参数；显式执行面事实会进入 `QueryEngineConfig`，不再因适配器传参而在构建阶段报 `TypeError`。
- `QueryEngine.runtime_snapshot()`：提供统一只读聚合面，包含 execution context、task/lifecycle、budget、abort 原因和当前 session 的 job 视图。它不夺取各组件的写权限，后续 resume/trace 从这里读取，避免重新从环境变量和多个对象拼猜运行态。
- `engine/state_authority.py`：登记 conversation、workspace、process、permission、projection、lifecycle 的唯一事实拥有者；event、trajectory、UI 只标记为派生/通知面，不能反向成为状态写入源。
- `engine/tool_call_state.py` 与 `tools/orchestration.py`：工具执行采用有限状态迁移 `validated → running → pending/completed/failed/cancelled/unknown`，状态历史只写入机器元数据；终态重入会被执行层拒绝，工具失败不再只靠自然语言判断。
- `engine/tool_coordinator.py`：`query_loop` 的单工具、批量工具和权限批准后重跑统一经过窄门面；并发、超时和权限策略仍由原组件持有，后续可以逐步拆出主循环而不一次性重写。
- `engine/turn_runtime.py`：把一次 submit 的回合预算闸、收尾窗口、收尾工具配额和生命周期准入集中成显式状态机；`query_loop` 只消费 `continue/wrap_up/stop` 决策，不再保存第二套隐式收尾状态。
- `tools/tool_registry.py`：`tool.started/finished` 审计事件附带当前 turn trace、runtime/container、tool schema hash 和 capability id；这些字段只进机器审计，不进入工具结果正文。
- `engine/execution_context.py` / `query_loop.py`：追踪 `model_request_id`、`projection_id`、permission snapshot 和 workspace revision 的机器字段，把一次模型请求、投影和工具执行串在同一个 turn trace 下；`engine/trace_graph.py` 将这些审计事实归并为脱敏证据链，可由 `runtime_snapshot(include_trace=True)` 或 `/v1/audit/trace` 读取，不复制 prompt、参数或结果正文。
- `permissions/trace.py` / `permissions/runtime_mode.py`：权限模式、workspace、runtime profile 和 live-mode revision 生成稳定 `permission_snapshot_id`；deny、ask、pending 和 tool audit 都能回溯到同一裁决快照。
- `permissions/trace.py` / `tools/tool_registry.py`：deny/ask 结果附带机器裁决字段 `permission_action`、`permission_rule_id`、`permission_reason_code`、`permission_snapshot_id` 和资源身份；这些字段用于审计与恢复归因，不扩展模型可见指令，也不改变成功工具原有的 `tool.started/finished` 审计契约。
- `engine/runtime_checkpoint.py`：提供 `runtime.json` 原子 checkpoint 旁路，记录最后已知运行态而不重放副作用；默认关闭，`XEYO_RUNTIME_CHECKPOINT=1` 后用于恢复实验，未知中的 job/action 仍必须走 unknown 结算。
- `engine/runtime_recovery.py`：恢复时比较 checkpoint 与当前 runtime 的 container、profile、能力、工具面和活跃 job；漂移只产出 `fresh/compatible/drifted` 报告，绝不自动重放副作用，也不把旧 job 假装成仍在运行。启用 `runtime_checkpoint` 时，turn-start 会在覆盖旧 `runtime.json` 前先执行一次只读漂移核验。
- `engine/runtime_verification.py`：可选的完成前 `VERIFYING` 阶段，检查工作目录、tool call 配对、未知/未结算 action 和活跃后台 job。它只产生机器报告，不判断代码答案，也不把提示塞回模型。
- `engine/lifecycle.py` 与 `engine/budget.py`：把预算 grace、verifying、finalizing 和终态变成执行层状态；墙钟默认仍不自动武装。进入 finalizing 后禁止新建 Agent 子任务，但仍允许既有权限闸控制的读写收尾动作。
- `tools/orchestration.py` 与 `tools/job_tools.py`：超时、取消、异常、未知 job 等路径都保留结构化结果，编排层不再要求下游从自然语言错误猜测是否可重试。

这部分没有继续扩展 WSC、压缩算法或上下文记忆内容；已有投影观测旁路只作为当前工作树中的既有诊断改动，不应被解读为已经证明压缩收益。

---

## 17. 当前验证状态：哪些已证明，哪些还不能说

### 17.1 已完成的零费用验证

已做过真 Docker container 端到端验证：Read、Glob、Grep、Write、Edit；好路径/坏路径权限预检；container `working_directory`；job kill；40000 字符溢出取回；图片字节传输；fake model 付费配置 smoke；真实 DeepSeek 请求路径；1M context、thinking、reasoning effort。当前本轮不含 WSC/压缩/上下文记忆用例的重点回归为 `468 passed, 2471 deselected, 1 warning`；job、Bash promote、编排、执行上下文、动作账本、权限快照、RuntimeProfile、runtime verification/recovery、模型事件协议、TurnRuntime、TraceGraph 和生命周期专项回归通过。另有一个已归属的 `test_reserved_tool_prefix.py::test_engine_env_projection_still_constructs` 旧失败，来自此前 T_now 撤销伪对后的 golden/测试契约漂移，未重新生成 golden。

这些结果证明的是“代码路径和测试契约可工作”，不是“89 题最终得分一定提高了多少”。

### 17.2 Oracle 预检状态

本地 oracle 预检已经完整跑完 10/10，但门禁明确未通过：6 题 green、2 题 oracle wrong_answer、2 题 verifier_invalid（其中 `pytorch-model-recovery` 是 900 秒 verifier 超时）。失败日志显示 `caffe-cifar-10`、`merge-diff-arc-agi-task`、`mteb-leaderboard` 受容器内 uv/CPython/GitHub 网络依赖影响；这仍是 ¥0 的判分装置问题，不是模型成绩，因此没有启动付费评测。

在这些 oracle 题没有全部完成前，不应启动需要支付模型调用的诊断或 89 题全量。

### 17.3 仍未证明的内容

- 修复后完整 89 题分数；
- 5 个历史 wrong_answer 是否全部被修复；
- 其他所有 TB 镜像是否都具备和 regex-log 一样的容器行为；
- 官方 90.6 的准确 prompt、重试、verifier 和统计协议；
- `arm_wall_stop(None)` 是否应该默认启用；
- 最小工具面和完整工具面的受控收益差异；
- 清除压缩痕迹后每个题目的因果改善幅度。

---

## 18. 设计讨论：优点、代价和可争论点

### 18.1 优点：状态和执行分层

XEYO 把模型注意力、执行限制和持久化状态分开：模型看到事实，不依赖控制性提示；权限在工具执行前判断；历史可以完整保存而模型上下文可以压缩；工具可以替换宿主/容器路由而不改变模型接口；provider 差异由 adapter 吸收。

这比不断往 prompt 里添加更强的提醒更容易测试，也更不容易形成模型自我说教和伪工具循环。

### 18.2 代价：中间层多，边界必须一致

```text
用户界面 ↔ API
API ↔ session
session ↔ query loop
query loop ↔ model projection
model ↔ tool parser
tool registry ↔ permissions
host ↔ container
canonical history ↔ compact projection
engine ↔ verifier
```

任何一个边界“看起来成功、实际上对象不同”，都会产生隐蔽故障。宿主 cwd/container cwd、canonical history/model projection、tool exists/tool executable、verifier invalid/wrong answer 都属于同一类问题：**边界两侧对同一个事实的命名或状态不一致。**

### 18.3 最小工具面和模型能力的取舍

工具越多，模型有更多路径，但 schema 和选择成本也增加；工具越少，轨迹更可控，但一个核心工具失效就会把所有工作压到 Bash。当前选择“最小但不只 Bash”的方案，是在可控性和能力之间的折中。

以后讨论工具面时，要区分：工具是否存在、工具是否正确执行、模型是否偏好该工具。不能用“模型没调用 Read”证明 Read 没有价值，也不能用“Read 存在”证明它在容器里工作正常。

### 18.4 是否默认武装墙钟停止

当前 `arm_wall_stop(None)` 不默认武装，原因是 TB 主要判文件系统状态而不只看最终文本；贸然启用可能在模型即将写完时静默拒绝工具，增加新的失败类型。

这有真实权衡：默认不武装，少一个静默拒绝但坏任务可能长时间耗钱；默认武装，成本和尾部时间可控但可能杀掉最后一个必要命令。应该用专门的 4 题诊断测量，不能凭直觉切换。

### 18.5 评测模式和产品模式是否应该分开

| 维度 | 产品模式 | TB 模式 |
|---|---|---|
| 权限 | 可能 ask 用户 | 无人值守、预设决策 |
| 工具面 | 可以包含扩展 | 最小稳定工具面 |
| agent | 可启用多 agent | 当前关闭 |
| cwd | 工作区/用户目录 | trial container |
| 预算 | 用户交互控制 | 题目 timeout 和成本上限 |
| 动态注入 | 产品状态 | benchmark metadata 也必须可追踪 |

两个模式可以共享引擎核心，但不应把 TB 的 hack 写成产品默认行为，也不应把产品交互假设带进无人值守 verifier。

---

## 19. 如何继续确认低分根因，而不是继续猜

### 19.1 第一阶段：零费用门禁

```powershell
cd "D:\lea\XenYon code"
git status --short

cd python
py -3.11 -m pytest tests/ -q -k "bash or grep or glob or catalog or compact or context_limit or reasoning or bench_tool or spill or truncate or read_tool or edit_tool or write_tool or job or notebook or prompt" --ignore=tests/extension

cd ..\TerminalBench
& ".venv-harbor313\Scripts\python.exe" zero\preflight.py --from-evidence evidence\p6-rest66-o18 --from-evidence evidence\p6-tail23-b10 --concurrent 2
```

门禁判据是装置能否正常完成 oracle/reference verifier，不是“模型看起来可能会得多少分”。

### 19.2 第二阶段：先跑小诊断，不跑 89 题

全量 89 题预计约 ¥16–25；诊断子集约 ¥2.37，压缩到 4 题约 ¥0.3 左右。第一笔钱只应该回答一个二元问题：**修复是否改变了行为。**

跑前写死判据，三条中至少两条成立才认为修复有效：

1. `verifier_invalid` 从约 65% 降到最多 1 题；
2. `xeyo_env_notice`、`X/50`、job 轮询在轨迹中归零或显著下降；
3. 有效分不低于已确立的 76.9%。

这个判据不保证 89 题高分，但可以防止花钱后只得到“感觉好像不同”的结果。

### 19.3 第三阶段：受控 A/B

```text
A：修复前 / 原上下文逻辑
B：修复后 / 真实 1M + 容器路由
```

必须固定同一题集、同一模型和 reasoning 档位、同一并发、同一 timeout、同一 verifier、同一重试次数和同一成本上限，否则分数变化无法归因。

### 19.4 verdict 报告必须同时给四个数字

每次报告都应输出：全量表观分、verifier_invalid 数量与比例、有效分、wrong_answer 数量和题名。如果只报一个总百分比，读者无法判断是模型答错、判分失败、超时，还是题目镜像本身缺依赖。

---

## 20. 常见误解和正确说法

| 误解 | 正确说法 |
|---|---|
| 官方 90.6，所以 XEYO 77 一定差 13 个点 | 官方数字与公开受控协议不等价；同模型配对已有约 12.6pp 口径差。 |
| 37 题只绿 20，所以模型只有 54% | 11 题 verifier_invalid；表观分 54.1%，清洗有效分 76.9%。 |
| 清洗后应该 100% | 清洗删除判分无效题，不会修复 5 个 wrong_answer 和 1 个 timeout。 |
| 所有 command not found 都是 XEYO bug | 很多是镜像真实缺命令；要区分镜像事实和工具路由。 |
| 压缩痕迹证明压缩造成答错 | 目前是强相关和修复理由，不是完整因果证明。 |
| Bash 很多说明模型不需要专用工具 | 旧版专用工具曾被错误路由，Bash 过多可能是执行层推过去的。 |
| 预测的 72/89 就是当前分数 | 没有当前 89 题 verdict 文件，只能称预测。 |

---

## 21. 一页版给讨论者的模型

```text
                    ┌──────────────────────┐
                    │  DeepSeek 模型        │
                    │  理解任务 / 选择行动   │
                    └──────────┬───────────┘
                               │ messages + tools
                               ▼
┌──────────────────────────────────────────────────┐
│ XEYO QueryEngine / query_loop                    │
│ 1. 保存会话                                       │
│ 2. 生成模型上下文投影                             │
│ 3. 注入当前状态                                   │
│ 4. 解析 tool call                                 │
│ 5. 执行权限和预算                                 │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│ 工具执行面                                        │
│ Bash / Read / Write / Edit / Glob / Grep / job   │
└──────────────┬───────────────────────────────────┘
               │ container filesystem
               ▼
┌──────────────────────────────────────────────────┐
│ TB trial container                                │
│ verifier 最终读取的真实文件和程序状态             │
└──────────────┬───────────────────────────────────┘
               │
               ▼
       green / wrong_answer / invalid / timeout
```

低分时按箭头逐层问：模型有没有收到正确题目和上下文；引擎有没有给出正确工具 schema；tool call 有没有被正确解析和授权；工具有没有在正确的 container cwd 执行；文件和依赖是否真的让 verifier 可用；verifier 是否正常运行；如果 verifier 正常，产物是否真的错误。

只有最后一步是纯粹的“答案能力”问题。前面任何一步失败，都会让总分下降，但不应该都归到模型。

---

## 22. 关键源码和证据索引

### 核心引擎

- [`python/engine/query_engine.py`](python/engine/query_engine.py)：引擎对象、配置、会话提交、上下文窗口默认值。
- [`python/engine/query_loop.py`](python/engine/query_loop.py)：轮次循环、模型流、工具解析、权限、终止和事件。
- [`python/engine/compact.py`](python/engine/compact.py)：压缩和模型投影相关逻辑。
- [`python/memory/runtime.py`](python/memory/runtime.py)：运行时记忆、压力水位、reasoning token 计数。

### Prompt 和动态状态

- [`python/prompt/system_prompt.py`](python/prompt/system_prompt.py)：稳定 system prompt 和当前 cwd 事实。
- [`python/prompt/pre_llm_inject.py`](python/prompt/pre_llm_inject.py)：T_now 块登记和装配。
- [`python/prompt/t_now_strategy.py`](python/prompt/t_now_strategy.py)：system/env/legacy/skip 策略和回退。

### 工具和容器

- [`python/tools/catalog.py`](python/tools/catalog.py)：完整工具目录和最小工具面。
- [`python/tools/tool_registry.py`](python/tools/tool_registry.py)：工具注册、schema 和路由。
- [`python/tools/container_fs.py`](python/tools/container_fs.py)：容器文件系统层。
- [`python/tools/bash_tool/bash_tool.py`](python/tools/bash_tool/bash_tool.py)：Bash、容器 cwd、后台和 timeout promote。
- [`python/tools/fileio/`](python/tools/fileio/)：文件读写和路由汇聚点。
- [`python/tools/grep_tool/`](python/tools/grep_tool/)：Grep 和无 `rg` fallback。
- [`python/tools/glob_tool/`](python/tools/glob_tool/)：Glob 和近似路径建议。

### 权限、服务和扩展

- [`python/permissions/policy.py`](python/permissions/policy.py)：allow/ask/deny 和模式。
- [`python/server/routers/chat.py`](python/server/routers/chat.py)：聊天入口。
- [`python/server/session_pool.py`](python/server/session_pool.py)：会话池。
- [`python/extension/mcp_gateway.py`](python/extension/mcp_gateway.py)：MCP 网关。
- [`python/extension/reconcile.py`](python/extension/reconcile.py)：扩展状态变更。

### TB 和判分

- [`TerminalBench/xeyo_harbor_agent.py`](TerminalBench/xeyo_harbor_agent.py)：Harbor/TB 适配器。
- [`TerminalBench/zero/verdict.py`](TerminalBench/zero/verdict.py)：裁决分类器。
- [`TerminalBench/zero/preflight.py`](TerminalBench/zero/preflight.py)：零费用 oracle 门禁。
- [`TerminalBench/zero/diag_set.py`](TerminalBench/zero/diag_set.py)：诊断题集。
- [`docs/归因-XEYO在TB2.1分数偏低与官方口径-20260910.md`](docs/归因-XEYO在TB2.1分数偏低与官方口径-20260910.md)：较早的 TB 归因记录；阅读时以本文的当前修复状态为准。

---

## 23. 最终判断

当前最稳妥、可以和别人讨论的结论是：

XEYO 的低分不是一个单一 bug，也不是官方 90.6 与 XEYO 结果之间的简单差值。原始 54.1% 被 11 个 verifier_invalid 严重压低；清洗后约 76.9% 反映了当时可判题中的真实表现，但其中还包含 5 个真实 wrong_answer、1 个 timeout，以及旧上下文、容器路由、伪工具注入和 job 开销等结构性问题。官方 90.6 又不是当前单次 XEYO 评测可直接达到的同协议基线。

已完成的修复主要消除了“评测装置不可靠”和“引擎把模型置于错误工作面”的问题。下一步只有在 oracle 预检全部通过后，做小规模受控 A/B，再决定是否值得花钱跑全量 89 题。没有那次受控 verdict 之前，任何全量分数都只能标成预测。

因此，讨论 XEYO 设计时应把问题拆成三个独立问题：

1. **评测装置是否有效？** 看 `verifier_invalid` 和 preflight。
2. **引擎是否把模型正确接到工具和容器？** 看轨迹、工具路由、cwd、spill、T_now 和上下文水位。
3. **在装置和引擎都正常时，模型对题目本身答得怎样？** 看 `wrong_answer`，而不是把所有非 green 都算进去。

只有这样，XEYO 的分数才有可解释性，也才知道下一次修复究竟是在提高模型能力、提高 harness 可靠性，还是只是在减少判分噪声。
