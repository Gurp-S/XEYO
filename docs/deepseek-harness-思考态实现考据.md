# deepseek-harness 源码考据 — 思考态（reasoning）的格式与实现

> 2026-09-10 只读考据。来源：`github.com/deepseek-ai/deepseek-harness`（master，`aa8262e` / 2026-09-10）。
> 本机无 clone 能力（GitHub 走代理不通），改用 raw + API 逐文件拉取。落地在 `.cache/dsharness/`。
> 目的：核对《最终方案-思考态回放》的 S1 数据模型设计，看官方 harness 怎么做。

---

## 一、结论速览

**harness 的做法与 S1 的 `provider_state` 设计思路一致，但更简单、更彻底：**

| 维度 | harness 实现 | S1 原设计 | 判定 |
|---|---|---|---|
| 数据模型 | `ReasoningBlock { type:'reasoning', text:string }` 进 `ContentBlock` 联合体 | `provider_state: dict\|None` **不透明容器** | **harness 更简单**：同一个 `content` 数组里，多一种 block 类型 |
| 是否不透明 | ❌ 不透明 —— `text` 是**明文**，引擎直接读 | ✅ 完全不透明，引擎从不解读 | **分歧点** |
| 位置 | 就是 assistant 消息的 `content` 里的一个 block | 独立字段贴在 assistant 消息上 | 等价 |
| 回放条件 | **有 reasoning 就回传**（不区分工具轮） | 按 per-provider 策略表 | harness 更宽 |
| 签名处理 | 不在 DeepSeek 侧；别的厂商「**hash 这段文本**恢复签名」 | 原样存字节 | 见 §四 |

**最重要的一条**：harness 把 reasoning 当**明文文本块**存，**不做任何不透明封装**。这直接质疑了 S1「不透明容器」的必要性。

---

## 二、数据模型：`ReasoningBlock`

`packages/llm/llm/src/types.ts:59-63`

```ts
/** Reasoning / thinking content, distinct from visible text. */
export interface ReasoningBlock {
  type: 'reasoning'
  text: string
}
```

并入 `ContentBlockMap`（`:110-118`）：

```ts
export interface ContentBlockMap {
  'text': TextBlock
  'reasoning': ReasoningBlock      // ← 就是多了一种 block
  'image': ImageBlock
  'file': FileBlock
  'tool-call': ToolCallBlock
  'tool-result': ToolResultBlock
}
```

**对比 XEYO**：`msgtypes/message.py` 的 `Message.content` 已经是 `str | list[dict]`，理论上加 `{"type":"reasoning","text":...}` 即可 —— **不需要新增顶层字段 `provider_state`**。

**注意**：harness 的 `ReasoningBlock` **只有 `text`，没有 signature / encrypted / provider 字段**。

---

## 三、回放：`serializeAssistant`

`packages/llm/llm-deepseek/src/serialize.ts:202-238`（核心逻辑）

```ts
/** Serialize one assistant message (text + reasoning + tool calls). */
function serializeAssistant(message: Message): WireMessage {
  const text = flattenText(message.content)
  const reasoning = message.content
    .filter(block => block.type === 'reasoning')
    .map(block => block.text)
    .join('')                                     // ← 多个 reasoning 块拼成一个字符串
  const toolCalls = message.content
    .filter(block => block.type === 'tool-call')
    .map(block => ({ id: block.id, type: 'function' as const,
                     function: { name: block.name, arguments: block.arguments } }))

  return {
    role: 'assistant',
    content: text,                                // ← 空串而非 null
    ...reasoning.length > 0 ? { reasoning_content: reasoning } : {},
    ...toolCalls.length > 0 ? { tool_calls: toolCalls } : {},
  }
}
```

### 三条可直接抄的经验

**① 回放条件比官方要求更宽 —— 不区分工具轮**

`serializeAssistant` 对**任何**带 reasoning 的 assistant 消息都回传，不做「是否工具轮」判断。
源码注释给了理由（`:228-232`）：

> CoT passback on every reasoning-carrying turn. The official rule (guides/thinking_mode.mdx) requires it on tool-call turns and **ignores it elsewhere**; a gateway re-encoding the conversation for another vendor recovers that turn's **upstream thinking signature by hashing this exact text**, which a tool-call-free turn carries nowhere else.

→ **这是《最终方案》S3 漏掉的一层**：文档只写「按官方要求，工具轮必须」。harness 多给了个理由 —— **非工具轮的 reasoning 是跨厂商转码时恢复签名的唯一载体**。

**② `content` 必须是 `""` 而**不是**`null`**

注释（`:215-226`）写得很重：

> Text-less turns send `""` — **NEVER null**. … Reasoning-ONLY turns (the model can answer entirely in the reasoning channel, e.g. a v4-flash greeting): the live API rejects null-content/no-tool_calls assistant messages with a **400** ("content or tool_calls must be set"), and **since the message sits durably in the session log, a null here bricks every later turn of that session**.

→ **★ 这才是真正会 400 的地方，不是 reasoning 不回传。**
→ 我 S0 实测的 A 臂（不回传 reasoning）不 400，与此完全吻合：harness 说的 400 条件是 **`content` 为 null 且无 tool_calls**，是另一件事。
→ **XEYO 实施 S1 时必须检查**：`assistant_text_message()` 在纯 tool_call 轮会不会产 `content: None`。

**③ reasoning 与 text 拆开再拼回**

`reasoning` 是 `filter(type==='reasoning')` 后 `join('')`；`text` 是 `flattenText` 只取 `text` 块。两者在 wire 上重新变成两个平行字段。**顺序由 block 在数组里的位置隐式承载**。

---

## 四、签名（signature）：harness 根本没存

`packages/llm/llm/src/message.ts:9-25`

```ts
/** Provider/model identity and adapter-private replay data for an assistant message. */
export interface AssistantProvenance {
  /** Provider route that produced the message. */
  provider: string
  /** Provider model id that produced the message. */
  model: string
  /**
   * Lossless-JSON adapter state needed to replay the provider response.
   * `LlmRuntime` exposes it to a target adapter only when that adapter instance
   * currently owns both this historical provider and the target provider.
   */
  replayState?: unknown
}
```

**关键设计**：跨厂商签名走 **`AssistantProvenance.replayState`**（一个 `unknown`，**lossless JSON**），而不是塞进 `ReasoningBlock`。

而且 `replayState` **有所有权门**：只有同一个 adapter 实例**同时持有历史 provider 与目标 provider** 时才交给它。这是比 S1「不透明容器」更强的隔离 —— **连适配器之间都默认不给**。

**DeepSeek 侧不用 replayState**（因为 DeepSeek 的 `reasoning_content` 是明文、无签名），所以 `serializeAssistant` 直接读 `text`。

→ **对 XEYO 的启示**：如果只做 DeepSeek，**`provider_state` 不透明容器是过度设计** —— 明文 `text` 就够（harness 就这么干）。
→ 但若要**同时支持 Anthropic/Gemini**（真有 signature），则 harness 的 `replayState` 才是正解：**签名与明文分开存**（明文进 content block 供回放，签名进 provenance 供转码）。

---

## 五、流式解析：空 delta 不开块

`packages/llm/llm-deepseek/src/types.ts` 的 `WireDelta` 注释：

> Thinking-mode CoT. The **FIRST chunk carries an empty string (must not open a reasoning block)**; absent entirely in non-thinking mode.

`packages/llm/llm-deepseek/src/translate.ts:155-164`

```ts
// Reasoning first: thinking mode interleaves it before text.
const reasoning = delta?.reasoning_content
if (typeof reasoning === 'string' && reasoning.length > 0) {   // ← 空串被丢弃
  if (!reasoningBlock) {
    reasoningBlock = open('reasoning')
    yield { type: 'block-start', index: reasoningBlock.index, blockType: 'reasoning' }
  }
  reasoningBlock.text += reasoning
  yield { type: 'reasoning-delta', index: reasoningBlock.index, text: reasoning }
}
```

→ **XEYO 的 `query_loop.py:1160-1163` 有一模一样的守卫**（`if chunk.text:`）✅ 这块没问题。

`packages/llm/llm/src/types.ts:393` 的流事件类型：

```ts
| { type: 'reasoning-delta'; index: number; text: string }
```

→ 与 XEYO 的 `ModelChunk(kind="reasoning_delta")` + `ReasoningDelta` 事件同构 ✅

---

## 六、思考档位：显式解析链

`serialize.ts:82-98`

```ts
function resolveThinking(options: GenerateOptions, defaults: RequestDefaults): ResolvedThinking {
  if (options.purpose === 'session-title') return { thinking: 'disabled' }   // ← 旁路请求强制关
  const effort = options.reasoningEffort === undefined
    ? defaults.reasoningEffort
    : reasoningEffort(options.reasoningEffort)
  if (defaults.thinking === 'disabled' && effort !== undefined && effort !== 'off') {
    throw new LlmError(`DeepSeek deployment does not support reasoning effort "${effort}"`,
                       'UNSUPPORTED_REASONING_EFFORT')
  }
  if (effort === 'off') return { thinking: 'disabled' }
  if (effort === 'low' || effort === 'high' || effort === 'max') {
    return { thinking: 'enabled', reasoningEffort: effort }
  }
  return defaults.thinking === undefined ? {} : { thinking: defaults.thinking }
}
```

**要点**：
- **effort 是事实上的主开关** —— 给 `low/high/max` 自动带 `thinking: enabled`；
- `off` **不上 wire**（转成 `thinking: disabled`），与官方「`off` 不是合法 wire effort」一致 ✅；
- `defaults.thinking === undefined` → **不发该字段**（落到厂商默认）；
- **能力声明**（`adapter.ts:420-434`）：模型元数据里带 `reasoning: { efforts, defaultEffort }`，**`defaultEffort` 默认是 `HIGH`**，与官方「默认 effort = high」对齐 ✅。

→ **这正是 XEYO `build_default_engine()` 缺的那一层**（问题 4）。harness 的解法是：**effort 是一等参数 + 模型元数据声明可选档位 + 默认值显式写死**。

---

## 七、对 XEYO 方案的修正建议

| S1/S2/S3 原设计 | harness 实践 | 建议 |
|---|---|---|
| `Message` 加 `provider_state: dict\|None` 不透明容器 | `ContentBlock` 加 `{type:'reasoning', text}` | **若只做 DeepSeek，改明文 block 更简单**；不透明容器是为多厂商签名预留 |
| S3 策略表「工具轮才回放」 | **有 reasoning 就回放** | **放宽**：非工具轮的 reasoning 是跨厂商恢复签名的唯一载体 |
| 「不回传 → 400」 | 真 400 是 **`content:null` 且无 tool_calls** | **纠正风险焦点**（与 S0 实测一致） |
| 未提 | `content` 必须 `""` 不能 `null` | **★ 新增必查项**：XEYO `assistant_text_message()` 纯 tool_call 轮产什么 |
| 未提 | reasoning 与签名**分开存**（block 明文 / provenance lossless） | **多厂商时必做**；且 provenance 有 adapter 所有权门 |

### 新增的必查项（下一步）

1. **`content: null` 风险** → ✅ **已查，XEYO 无此风险**（实测见 §九）。
2. **多厂商取舍**：先确认 XEYO 到底要不要支持 Anthropic/Gemini。要 → 抄 `replayState` 的所有权门；不要 → 抄 `ReasoningBlock` 明文，别做不透明容器。

---

## 九、★ XEYO `content: null` 风险实测：无此风险

harness 警告的 400（`content:null` 且无 tool_calls，且**会让整个会话后续轮全砖**）在 XEYO 不存在。实测：

```python
assistant_text_message('', [ToolUse(id='call_1', name='Bash', input={'cmd':'ls'})])
# 内部: [{'type':'tool_use','id':'call_1','name':'Bash','input':{'cmd':'ls'}}]
# wire: {'role':'assistant','content':'',            ← 空串 ✅
#        'tool_calls':[{'id':'call_1','type':'function','function':{'name':'Bash',
#                       'arguments':'{"cmd": "ls"}'}}]}

assistant_text_message('', None)
# 内部: ''（字符串）
# wire: {'role':'assistant','content':''}            ← 空串 ✅
```

`model/_openai_common.py:271` 的写法是**恒定空串**：

```python
msg: dict[str, Any] = {
    "role": "assistant",
    "content": "".join(text_parts),      # ← 永不为 None
}
if tool_calls:
    msg["tool_calls"] = tool_calls
```

→ **XEYO 这条天然安全**，无需改动。这也解释了 S0 实测 A 臂为何稳定 200。

---

## 十、最终对照表：三家实现同一件事

| | **DeepSeek harness** | **XEYO 现状** | **《最终方案》S1-S3** |
|---|---|---|---|
| reasoning 存储 | `{type:'reasoning',text}` 进 content 数组 | **无**（查过，无字段） | `provider_state` 不透明容器 |
| 流式解析 | `if length > 0` 开块 | ✅ `if chunk.text:` 已有 | — |
| 回放位置 | assistant 消息的 `reasoning_content` | 无 | 同 harness |
| 回放条件 | **有就回传**（不限工具轮） | 无 | 仅工具轮（**偏窄**） |
| `content` 空值 | `""`（注释警告 null 会 400 + 砖会话） | **`""`** ✅ 已安全 | 未提 |
| 签名 | `AssistantProvenance.replayState`（lossless，**有 adapter 所有权门**） | 无 | 塞进不透明容器（**混在一起**） |
| 思考档位 | effort 一等参数 + 模型元数据声明 + 默认 HIGH | 无（走厂商默认） | S5 补 |
| 跨厂商 | hash reasoning 文本恢复签名 | — | 未提 |

---

## 八、取证文件清单

`.cache/dsharness/`（本地缓存，非仓库交付物）：

| 文件 | 来源 |
|---|---|
| `ds_llmtypes.ts` | `packages/llm/llm/src/types.ts`（ReasoningBlock / ContentBlockMap） |
| `ds_message.ts` | `packages/llm/llm/src/message.ts`（AssistantProvenance.replayState） |
| `ds_content.ts` | `packages/llm/llm/src/content.ts` |
| `ds_serialize.ts` | `packages/llm/llm-deepseek/src/serialize.ts`（★ 回放核心） |
| `ds_translate.ts` | `packages/llm/llm-deepseek/src/translate.ts`（流式解析） |
| `ds_types.ts` | `packages/llm/llm-deepseek/src/types.ts`（WireRequest/WireAssistantMessage） |
| `ds_adapter.ts` | `packages/llm/llm-deepseek/src/adapter.ts`（能力声明） |
| `ds_sesslog.ts` | `packages/session/session-log-deepseek/src/types.ts` |

> 本机 git 无法访问 GitHub（代理 127.0.0.1:7897/2999 均不通），全部经 `raw.githubusercontent.com` + `api.github.com` 逐文件拉取。
