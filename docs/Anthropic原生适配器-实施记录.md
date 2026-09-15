# Anthropic 原生适配器 — 实施记录（方案 B）

> 2026-09-10。承接 `docs/Anthropic-Gemini支持方案与reasoning压缩域决策.md` 的
> 方案 B 决议：Claude 不做 OpenAI 兼容层，直接讲 Messages API。
> 本文只记录**已落地**的内容与它的边界，不重复决策论证。

## 1. 做了什么

新增 `python/model/anthropic.py`（761 行），实现 `ModelClient.stream()` 契约
（`model/client.py` 的 Protocol：`messages, tools, abort → AsyncIterator[ModelChunk]`）。

零改动已有推理路径：DeepSeek / OpenAI / local / fake 四个后端代码路径
逐字节未变，只有 `PROVIDER_PRESETS` 多了一行登记。

### 接线点

| 位置 | 改动 | 作用 |
| --- | --- | --- |
| `model/anthropic.py` | 新文件 | 适配器本体 |
| `model/openai_compat.py` | `PROVIDER_PRESETS` +1 条 | 进「支持的 provider 名单」，并登记 base_url |
| `cli/config_store.py` | `VALID_PROVIDERS` +1 | CLI `xeyo config set provider anthropic` |
| `engine/query_engine.py` | `backend == "anthropic"` 分支 | CLI/测试直连路径 |
| `server/session_pool.py` | `cfg.provider == "anthropic"` 分支 | GUI HTTP 路径 |
| `gui/src/stores/settingsStore.ts` | type/URL/LABEL/isProviderId | 前端识别与展示 |
| `gui/src/components/SettingsModal.tsx` | `inferProviderFromBaseUrl` | 按地址推断协议 |
| `tests/test_anthropic_adapter_contract.py` | 新文件，36 例 | 契约守卫 |

## 2. 六条协议差异（本模块存在的全部理由）

Messages API 与 Chat Completions 不是同一套，转码规则全部收敛在
`normalize_messages_for_anthropic()` 这一个序列化入口：

1. **system 提顶层** —— Anthropic 的 system 不在 messages 里。多条 system
   按序 `\n\n` 拼接。
2. **tool_use 是 content block** —— 不是 `tool_calls` 字段。
3. **tool_result 是 user 消息里的 block** —— 内部 `role=tool` 的独立行必须
   折进 user 消息；且紧跟其后的 `image_url` block 也要折进该 tool_result 的
   `content` 数组（Anthropic 没有并列图片槽）。
4. **严格 user/assistant 交替** —— 多个工具结果（内部每工具一条 `role=tool`）
   必须合并成**一条** user 消息的多个 block，否则连续两条 user 被 400 拒。
5. **thinking block 带 signature** —— 逐块原样回传。
6. **thinking 用 `adaptive`** —— `{type:"enabled"}` 在 Claude 4.7+ 返回 400。

### 思考态的两个安全默认

- **无签名的 thinking 块不发**：签名缺失时静默丢弃该块，不伪造签名。
- **跨厂商 reasoning 块不发**：DeepSeek 的 `reasoning` 明文块没有签名，
  Anthropic 承载不了 → 静默丢弃（不编造内容）。

这是「无路可走时沉默」而非「想办法让它能过」——符合引擎铁律。

## 3. 已实现 / 未实现（边界必须清楚）

### 已实现

- 流式（httpx 优先，urllib 线程回退，与 DeepSeek 客户端同构）
- thinking 增量 → `reasoning_delta` chunk（GUI 可实时渲染）
- signature 累积 → `state["thinking_bufs"][idx]["signature"]`，供回放落档
- tool_use 经 `input_json_delta` 累积 → `content_block_stop` 时闭合发 chunk
- usage 转换：Anthropic `input_tokens` **不含**缓存部分，故
  `prompt_tokens = input + cache_read + cache_creation`，否则面板输入恒偏低
- usage 账本落档（provider=`anthropic`，`vendor` 自动识别为 anthropic）
- 错误路径：HTTP ≥400 → `ProviderError` + `sanitize_http_body`；
  `error` 事件 → `ProviderError`

### 未实现（有意为之，非遗漏）

- **`thinking.block_binding` 冲突未处理**。2026-08 beta 起，重放 thinking 块
  要求其前的 system/tools/messages **全未变**，否则 400
  `Invalid signature...bound to a different conversation`。XEYO 的 compact
  压缩 / rewind / T_now 注入**都会改历史前缀** → 会撞上。新账号默认
  `error`，可设 `drop_block` 放宽。
  **当前行为**：不改，让厂商按默认口径裁决。若实测撞 400，处置方案是
  ① 请求头/参数设 `drop_block`，或 ② 仅在 append-only 窗口内回放 thinking。
  **这一项需要真实 key 实测才能定，未做。**
- **Gemini 适配器未做**。`thought_signature` 是硬门槛，且 OpenAI 报文没有
  承载字段 → 需侧信道缓存，是另一套设计。
- **thinking 的非流式回放路径未接**。`assistant_text_message(reasoning=...)`
  只在有 `tool_uses` 时把 reasoning 挂进 block 数组；纯文本轮的 reasoning
  无处承载。Anthropic 侧同理：非工具轮的 thinking 块目前不会落档。
  这与既有 DeepSeek 路径的约束一致（同一处代码决定），不是本模块新增限制。
- **`_stream_stdlib` 未做集成测试**（只测了 `_consume_sse_event` 纯函数）。
  正常环境 httpx 必定可用，该路径是兜底。

## 4. 测试

`python/tests/test_anthropic_adapter_contract.py` — 36 例，全绿，纯离线。

- 形状护栏（7）：方法齐全、无 key 拒绝、header 用 `x-api-key` 非 Bearer
- 请求体构造（19）：六条协议差异逐条锁定 + thinking off/adaptive + effort +
  max_tokens + temperature 抑制 + 工具 schema + tool_result 带图 + is_error
- SSE 解析（14）：thinking/text/tool_use 增量、签名累积、空 input 落 `{}`、
  usage 合并、error 事件、畸形 JSON 容错
- 端到端往返（2）：完整流 thinking(带签名)→tool_use；捕获的签名重建请求体后
  仍是原块（回放闭环）

期间测试抓到 **2 个真实 bug**（已修）：
1. `_tool_result_content` 读 `block["images"]`，但内部表示是**兄弟 block** →
   改为在 `_blocks_to_anthropic` 里折进前一个 tool_result。
2. `message_start` 的 usage 未存入 `state["input_usage"]` → `message_delta`
   合并失败，输入 token 恒为 0。

## 5. 回归验证（2026-09-10）

| 检查 | 结果 |
| --- | --- |
| `pytest tests/test_anthropic_adapter_contract.py` | 36 passed |
| `pytest` 模型/回放层 6 个文件 | 93 passed |
| `pytest -k "extension or session or message or compact or cache_prefix or hydrate or transcript"` | 360 passed / 11 failed |
| `pytest -k "provider or session_pool or attribution or pricing"` | 70 passed |
| `npx tsc --noEmit` | 0 error |
| `npx vitest run` | 743 passed / 5 failed |

**关于 11 + 5 个失败**：全部为既有失败或**其他会话在途改动**所致，与本改动无关，
已逐条求证：

- 11 个 pytest 失败：`test_worker_session_*` / `test_ilink_channel_*` /
  `test_sessions_delete_archive_gate` / `test_rewind_discard_rotated` /
  `test_cross_session_memory` 等属其他会话在途（memory index 退役、bash win_job、
  t_now 改造）；`test_simple_functionality::test_user_message_creation` 在
  **HEAD 版本**里就写着 `msg["role"]` 去下标 `Message` dataclass → 本就是陈旧测试；
  `test_compact::test_should_force_compact_on_pressure_threshold` 断言的阈值行为
  与当前 `compact.py` 不符（该文件我零改动）。
- 5 个 vitest 失败：`ModelPicker.tsx:122` 读 `s.profiles.find(...)` 得到
  `undefined`。**已用 `git show HEAD:` 还原我改的两个前端文件后重跑，
  同样是这 5 个失败** → 确证既有，非本改动引入。根因在
  `ChatHeader.tsx`/`UsagePanel.tsx`/`api.ts` 等其他会话在途的 usage 改造。

## 6. 未决事项（需真实 key 才能推进）

1. **`block_binding` 实测**：需 Anthropic 真 key，验证跨轮重放 thinking 是否
   撞 400；若撞，确定 `drop_block` 是请求级还是账号级设置。
2. **`thinking` 必须回传的范围**：官方口径「工具轮内必需 / 跨轮推荐 / 工具之外
   可省」。当前实现是「有签名就回放」，可能比必需更宽——但更宽是安全方向
   （留着只花 token 不触 400，删了可能触 400）。可实测后收紧。
3. **Gemini 适配器**：独立议题，需要侧信道缓存设计。
