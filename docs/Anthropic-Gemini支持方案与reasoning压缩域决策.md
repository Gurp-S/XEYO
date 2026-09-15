# Anthropic / Gemini 支持方案 + reasoning 压缩域决策

> 状态：**待用户决策**（本文件是决策书，不是实施记录）
> 依据：本机实测 + 官方文档核实（2026-09-10）+ 项目源码清点
>
> ⚠️ **2026-09-10 后续实测推翻了本文 §二 的成本模型**：S1 实验证明 **DeepSeek 把回传的
> `reasoning_content` 排除在 `prompt_tokens` 计费基数之外**（塞入 5.9 万 token 的
> reasoning，`prompt_tokens` 只涨 3,589）。故「全量 ¥76 / 命中 ¥1.53」的推算**整体作废**，
> 裁剪的**成本动机消失**，只剩**窗口管理**动机。详见 `docs/S1-取证报告-reasoning裁剪与计费.md`。

---

## 零、先说结论（TL;DR）

| 问题 | 结论 |
|---|---|
| **支持 Anthropic/Gemini** | **用户已定：走方案 B（原生适配器）**，Claude 当一级公民。业界四个生产实现（Roo/Cline/gptme/Helix）**无一例外都在存原生格式**，印证此路线。 |
| **reasoning 是否进压缩域** | **实测后重定：成本动机不存在（不计费），只需按「窗口管理」裁。近档保留 2 轮 = Anthropic 官方示例值。** |

---

## 一、Anthropic / Gemini 支持：三条路线

### 事实底座（本机 + 官方文档核实）

**① 本机现状：零原生适配**
- `python/model/` 下只有 `deepseek.py` + `openai_compat.py` 两个客户端，共用 `_openai_common.py` 序列化。
- `engine/query_engine.py:1260-1310` 的 backend 分派只有 `deepseek` / `openai` / `local` / `fake`。
- `openai_compat.py:357 PROVIDER_PRESETS` 仅 4 项；`_build_body:184` 的 `provider == "deepseek"` 是唯一的厂商分支。
- GUI `settingsStore.ts:16`：`type ProviderId = 'deepseek' | 'openai' | 'local' | 'fake'`。
- 全仓 grep `v1/messages` / `generateContent` / `thoughtSignature` → **0 命中**。

**② 官方都提供 OpenAI 兼容端点**（关键事实）
- Anthropic：`base_url=https://api.anthropic.com/v1/` + `/chat/completions`，改 3 样（base_url / key / model 名）即可用。
  - ⚠️ 官方原话：兼容层「**主要供测试与对比**，不是长期/生产级方案」。
  - ⚠️ **不支持 prompt caching**（走兼容层）；**思考态不返回给 OpenAI SDK**（拿不到 Claude 的 reasoning 明文）。
  - temperature 被夹到 [0,1]；`strict` 参数被忽略（工具 JSON 不保证符合 schema）。
- Gemini：`base_url=https://generativelanguage.googleapis.com/v1beta/openai`。
  - ⚠️ **thought_signature 是硬门槛**：Gemini 3 的 functionCall 必须回传签名，缺了直接 **400**（不是降质，是报错）。Gemini 2.5 缺签名只降质不报错。
  - 签名是**不透明字节**，OpenAI 报文的 tool_call 里没有字段承载它 → 必须做**独立缓存**（业界标准做法：按 tool_call_id 缓存签名，组装下一请求时回贴）。
  - ⚠️ Gemini 要求 user/model 角色交替，需合并连续同角色消息；system 走 SystemInstruction。

### 方案 A：OpenAI 兼容端点（推荐）

思路：把 `anthropic` / `gemini` 加进 `PROVIDER_PRESETS`，复用现有 `OpenAICompatClient`。

改动面（估算）：
1. `openai_compat.py::PROVIDER_PRESETS` 加 2 项（各 3 行）。
2. `engine/query_engine.py:1260` 的 backend 白名单加 2 个 id（2 行）。
3. **Gemini thought_signature 缓存**（唯一有分量的部分）：新增 `model/thought_signature_cache.py`
   - 流式响应里抓 `tool_calls[].thought_signature`（Gemini 兼容层会放在额外字段里，需实测确认字段名）→ 按 tool_call id 存。
   - `normalize_messages_for_openai` 组装 tool_call 时回贴签名。
   - 无签名时对 Gemini 2.5 静默放行，对 Gemini 3 fail-closed 报中性错误。
4. GUI：`ProviderId` 加 2 项 + `PROVIDER_DEFAULT_URL` / `PROVIDER_LABEL` / `MODEL_OPTIONS` + `isProviderId`（约 30 行，散在 5 个文件）。
5. 测试：扩 `test_model_client_contract.py` 的形状护栏 + 新增签名缓存契约测试。

**收益**：半天工作量换 2 家厂商可用；不新增协议分支（守住「反巨石」）。
**代价（必须诚实标注）**：
- **Claude 拿不到思考态明文** → 我们刚做的 S1/S2/S3 思考态回放在 Claude 上**收益为 0**（兼容层不吐 reasoning）。
- **Gemini 必须做签名缓存**，否则多轮工具调用直接 400 —— 这是「不做也得上」的硬成本。
- prompt caching 不可用 → Claude 输入成本无法享受缓存折扣（对照 XEYO 主业 DeepSeek 命中率 93.9%，差距巨大）。

### 方案 B：原生适配器（Anthropic Messages API / Gemini generateContent）

思路：新增 `model/anthropic.py` + `model/gemini.py`，各自实现 `ModelClient.stream()` Protocol。

**收益**：
- Claude 拿到**完整思考态**（含 `thinking` block + `signature`）→ 我们的回放机制在 Claude 上是真收益。
- prompt caching 可用（Claude 的 cache_control 显式标记），输入成本大幅下降。
- Gemini 签名天然在 parts 里，不需要侧信道缓存。

**代价**：
- Anthropic 的 wire 格式差异**很大**：`system` 提为顶层字段、`tool_use`/`tool_result` 是 content block（不是 `tool_calls`/`role:"tool"`）、**tool_result 必须与 tool_use 在同一用户消息里**、messages 必须 user/assistant 严格交替。
- Gemini 更远：`contents[].parts[]`、`functionCall`/`functionResponse`、`role: "model"` 不是 `assistant`、system 走 `systemInstruction`。
- 这意味着 **`normalize_messages_for_openai` 那套「唯一序列化入口」的设计前提被打破** —— 需要引入「wire 适配器」抽象层，把 `Message` 按目标协议转码。这是**结构性改动**，不是加个文件。
- 每家的流式事件格式也不同（Anthropic 是 `content_block_delta`，Gemini 是 `parts` 增量），要各自写 SSE 消费者 + 各自写契约测试。
- 两个厂商 × (回放 + 缓存 + 签名 + 工具配对) ≈ **数天工作量 + 长期维护面翻倍**。

### 方案 C：先做 A，把 B 留作条件触发

思路：A 上线后，**只在「有真实用户/评测需求 + 能证明收益」时**才升 B（符合 AGENTS.md 第 4 条「新功能准入：旁路验证收益后才并入主链路」）。

---

### 我的建议

**选 A，但 Gemini 的签名缓存必须做扎实**（这是 A 里唯一的真风险点）。

理由：
1. **AGENTS.md 第 4 条**（新功能准入：有数据证明收益后才并入主链路）直接指向 A —— 我们现在**没有任何证据**表明有人要用 Claude/Gemini，先上最薄的形态验证需求。
2. XEYO 是**本地编码 Agent**，主业是 DeepSeek（家底：93.9% 缓存命中、成本结构 83% 在输出）。Claude 走兼容层拿不到缓存折扣、拿不到思考态，**性价比远低于 DeepSeek**，B 的收益在当前产品定位下兑现不了。
3. **反巨石**：B 需要引入 wire 适配器抽象层，触碰 `_openai_common.py` 这个「唯一序列化入口」，扩散面大。

**但有一个前置问题必须先定**：如果长远一定要 Claude 的**原生思考态 + 缓存**（比如为了评测对标），那 A 就是死路（兼容层不吐 reasoning），应该直接上 B。**这个取决于你——是否把 Claude 当「一级公民」还是「兼容性兜底」？**

---

## 二、reasoning 是否进压缩域

### ★ 实测体量数据（59 份 A 族轨迹复算，2026-09-10）

用 `TerminalBench/zero/_stats_reasoning_volume.py` 对既有 59 份含 `reasoning_content` 的轨迹复算：

| 指标 | 数值 |
|---|---|
| 会话数 | 59 |
| reasoning 总条数 | 1,138 |
| reason 总字符 | 8,866,042 → **≈ 521 万 token** |
| **平均每会话** | **150,271 字符 ≈ 88,395 token / 19 条思考** |
| 最长单会话 | 980,537 字符 ≈ **576,786 token**（40 条思考） |
| 单条思考均长（中位） | **6,330 字符**（不是几百字符！） |

**关键推算**：厂商要求「带 tools 时历史全量回传」，即第 N 轮上下文里躺着前 N−1 条思考。按此累积：

```
59 会话累计输入 reasoning ≈ 76,295,520 token ≈ ¥76.30（未命中 1.0 元/M）
平均每会话 ≈ ¥1.29
```

**对照基准**：我记忆里的 P2 全量基准总花费是 **¥26.49**。
→ **reasoning 全量回放的成本（¥76.30）是整个基准预算的 2.9 倍。**

若**只保留最近 2 轮**（更早的丢弃）：

```
累计 ≈ 10,138,527 token ≈ ¥10.14（降 86.7%）
```

**但必须诚实标注两个不确定性**：
1. 这 ¥76.30 是**未命中价**。DeepSeek 有 KV 前缀缓存（XEYO 实测命中率 93.9%），而**reasoning 回放是「逐字不动地贴回」→ 正好落在 KV 前缀上**，实际大概率按命中价 0.02 元/M 计 → **¥76.30 → ¥1.53**。
2. 所以「贵不贵」完全取决于**厂商是否对 reasoning_content 段计命中**。这**必须实测**（一次多轮调用，看 `usage.prompt_cache_hit_tokens` 有没有把 reasoning 算进去）。

**这就是为什么必须先做实验**：同样一份数据，按未命中算是 ¥76（不可接受），按命中算是 ¥1.5（可接受）——**差 50 倍**。

### 现状实测

| 环节 | 行为 | 位置 |
|---|---|---|
| 落盘 | reasoning block 进 content 数组，原样 JSON 序列化 | `transcript_blobs.py:105` |
| hydrate | 原样还原，无过滤 | `hydrate.py:28-33` |
| 压缩投影 | **只重写 `tool_result` block，reasoning 在「未 aging」与「aging」两分支都原样透传** | `compact.py:244-283` |
| 送模型 | 还原为 `reasoning_content` 字段 | `_openai_common.py:278-280` |

**结论：当前 reasoning 完整进入压缩域，且不会被裁剪。**

### 这意味着什么（信息价值账）

- **必要**：厂商协议要求回传「与本轮工具调用配对的历史 assistant 消息」的思考。旧的能否裁 —— **协议灰区，未实测**。
- **不必要**：单条思考中位 **6,330 字符**（约 3.7k token）属于「中等长度」——比预期长得多。第 3 轮的「我要先读 a.py」这种思考对第 8 轮几乎没有信息增量，反而可能构成**「旧结论锚定」**（`policy.py:375` 的注释正是这个顾虑：「弱模型存在旧结论指令化锚定/续写压力」）。

### 三个子方案

**方案 1：保持现状（全量保留）**
- 优点：零风险、零改动、协议最安全。
- 缺点：若不计命中，成本是基准预算的 3 倍；长任务上下文膨胀（最长单会话 57 万 token，直接逼近窗口）。

**方案 2：压缩时丢弃旧轮 reasoning**
- 优点：省 token（若只留近 2 轮降 86.7%）、去锚定。
- 缺点：**未实测**。不知 DeepSeek 是否容忍历史 assistant 缺 `reasoning_content`。**违反「信息纪律」的风险**：若厂商因此降质，我们无从察觉。
- **必须先花 ¥0.01 实测**（复用 `step0_probe.py`，加一臂「裁掉中间轮 reasoning」）。

**方案 3：压缩域内按「近档保留、远档丢弃」分级（推荐）**
- 与现有 `aging` 机制**天然同构** —— `compact.py` 已有 `frozen` / `aging` 远近分档，reasoning 只是多挂一条「远档丢思考」规则。
- 具体：保留最近 N 轮（如 2~3 轮）reasoning 明文；更早轮次进入 `frozen` 区时丢弃 reasoning block（保留 text + tool_use，配对完整）。
- 优点：风险限制在「远的、价值低的」思考上。
- 前置：**同样需要实测**（方案 2 那一臂）。

### 我的建议

**先做两个 ¥0.01 实验，拿到数据再决定——不要现在拍脑袋。**

**实验 1：裁剪容忍度**
- 复用 `step0_probe.py`，加一臂：多轮 tool 循环里，**中间轮 assistant 剥掉 `reasoning_content`**，看是否 200。
- 200 → 方案 2/3 可行，按方案 3 实现（与 aging 同构，最省）。
- 400 → 方案 1 是唯一选项，退一步「只在压缩触发时丢」。

**实验 2：reasoning 是否计命中（决定成本结论）**
- 一次 3~4 轮调用，第 2 轮起回头读 `usage`，看 `prompt_cache_hit_tokens` 是否覆盖 reasoning 段。
- 命中 → 全量保留只要 ¥1.5，方案 1 完全可接受，**不动**。
- 未命中 → 按未命中 ¥76 计，必须做裁剪（方案 2/3）。

**必须澄清一点**：这件事和第 4 条 `reasoning_tail_enabled`（往 T_now 注入上一轮思考尾段）是**两件不同的事**：
- 那个是**注入**（主动往注意力塞），默认关，有锚定顾虑。
- 这个是**回放**（协议要求的历史回传），是厂商硬要求，不是我们主动塞。
- 「回放要不要裁」和「注入要不要开」是两个独立决策，别混。

---

## 三、待你拍板的三个问题

1. **Claude 的定位**：是「兼容性兜底」（→ 选 A）还是「一级公民，要原生思考态+缓存」（→ 直接上 B）？
2. **是否先做两个 ¥0.01 实测**（裁剪容忍度 + 命中计费）？我可以复用现有 `step0_probe.py`，不改源文件。
3. 若实测结论是「不计命中」，**近档保留几轮**？我建议 2~3 轮（对齐现有 `reasoning_tail` 的 600 字符尾段思路，但按轮数而非字符数）。
