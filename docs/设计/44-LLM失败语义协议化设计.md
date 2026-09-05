# 44 · LLM 失败语义协议化（harness 支柱②补完）设计

> 来源：`docs/DSH-可借鉴机制对照报告.md` §7（P1）+ §15.4（XEYO 简化版许可）。
> 目标：把 LLM 适配层的「异常 + 猜」升级为「结构化错误码 + 内嵌恢复指令 + 可渲染重试事件」，
> 补齐 harness 四大支柱中的第②根（失败语义协议化）在 **LLM 适配层** 的缺口。
> 红线：不动 T_now / KV 前缀 / 权限三态 / COW；失败 chunk 永不进史（现状已满足——见 §3）。

## 0. 现状事实（代码走读）

- 适配器已抛 `ProviderError(status_code)` / `NetworkError`（`common/errors.py`），有中文 friendly 链（T34）。
- **无**：稳定错误码集、重试机制、重试事件帧、`interrupted` anchor。
- 引擎流消费点：`engine/query_loop.py:883` `async for chunk in model.stream(...)`；
  唯一特殊性 catch：`except Aborted → StoppedEvent(reason="aborted")`；其余异常向上传播。
- **失败 chunk 永不进史（已天然满足）**：assistant 消息只在流**完整结束后**才
  `store.append`（`query_loop.py:1031`）；流中途异常→未 append→重试安全（无半条消息）。
- `model.stream` 调用点是纯函数式重建条件：`(api_messages, tool_schemas, abort)` 均可重取——
  满足「重试 = 重建同一请求」（DSH 语义的 XEYO 简化版：同 turn 内重建，不换 turn 号）。
- SSE 映射点：`server/routers/chat.py:1049` `async for ev in engine.submit(...)` 的 isinstance 分支链；
  新增事件类型 = events.py 类 + chat.py 分支 + `gui/src/lib/api/core.ts` 解析（additive）。

## 1. 设计

### 1.1 错误码集（分类器，纯函数）

`common/errors.py` 增加：

```
LlmFailureCode = Literal[
    "no_adapter" | "auth" | "invalid_credential" | "rate_limit"
  | "context_window_exceeded" | "empty_response" | "timeout"
  | "network" | "provider_error" | "unknown"
]
@dataclass(frozen=True)
class LlmFailure:
    code: LlmFailureCode
    retryable: bool
    retry_after_ms: int | None = None   # 厂商 Retry-After，未给则 None（走本地退避）

def classify_llm_failure(exc: BaseException) -> LlmFailure
```

- `NetworkError` / URLError / ConnectionError / OSError(connect/timeout/unreachable) → `network`（retryable）
- `ProviderError`：401→auth；403→invalid_credential；429→rate_limit（retryable，retry_after_ms = exc.retry_after_ms）；
  408→timeout（retryable）；5xx→provider_error（retryable）；400 且消息含 context/长度类词→context_window_exceeded（不重试）；
  其余→provider_error（不重试）
- `EMPTY_RESPONSE`：引擎层检测（流零 chunk 正常结束）→ `empty_response`（retryable），见 §1.3
- 其余→unknown（不重试）。**分类器是唯一权威**：下游（引擎重试决策 / SSE 帧 / 审计 / UI）不自行猜。

### 1.2 重试环（query_loop 流消费点）

- 包一层 `_stream_with_retry(model, api_messages, tool_schemas, abort, on_event)`：
  - `LLM_ATTEMPTS_MAX = 3`（可 `XEYO_LLM_MAX_ATTEMPTS` 覆盖，≥1）；退避 500ms→10s + 10% jitter；
    `retry_after_ms` 有效时替换本地退避（取 max）。
  - 重试前 yield `LlmRetryEvent{attempt, next_retry_ms, code, message, provider, model}`（= DSH `llm/retry`，调度决策）；
    实际重试开始前 yield `LlmRetryStartedEvent{attempt, provider, model}`（= DSH `llm/retry-started`，供 UI 倒计时）。
  - 非重试错误或耗尽 → 重新 raise（错误已带 code），由既有上层路径处理；**审计**记 `llm.failure`（code + attempt + 状态码）。
  - 仅对 `classify_llm_failure(...).retryable` 重试；abort 不重试（Aborted 优先）。
  - 不换 turn 号（简化版）；`llm/retry-started` 与 `llm/retry` 是**非 surface 事件**——不进 transcript、不进消息历史。

### 1.3 EMPTY_RESPONSE

- 流完整结束但零 chunk（无 text/reasoning/tool_use）→ 视为 `empty_response`，走重试环；
  重试耗尽后按失败收敛（对齐 DSH：EMPTY_RESPONSE 默认可重试）。
- 注意 forced_wrap_up 空响应已有硬停语义（query_loop.py:1045）——**仅普通路径**检测；wrap_up 路径不改。

### 1.4 interrupted anchor（「用户看到的必须入史」）

- `except Aborted` 时若本流已产出非空前缀（text/reasoning/tool_use 任一）：
  在 `_fill_missing_tool_results` 之前 `store.append(assistant_text_message(partial_text, partial_tool_uses or None, interrupted=True))`；
  `Message` 增 `interrupted: bool = False` 字段（transcript 留档，投影可按需忽略——默认不忽略，保持 raw 真相）。
- `StoppedEvent` 增 `interrupted: bool = False`；GUI `chatStore` 在 aborted 恢复时对中断消息加「（已中断）」标注（P0 可仅加字段）。
- 风险：partial XML 未闭合——as-is 存档（raw 真相），修复由既有 hydrate/next-turn 字典补偿处理。

### 1.5 wire 细则核对（deepseek 适配器）

- usage 先于 finish、reasoning passback：对照 `model/deepseek.py` 现实现逐条核对，缺则补（P1 本任务内）。
- 5min stream idle watchdog：P2（不做，记录）。
- `ProviderError` 增 `retry_after_ms`（429/503 从响应头解析，仅 deepseek/openai_compat 两适配器填）。

## 2. 事件形状（SSE）

```
{"type": "llm_retry",          "attempt": 1, "next_retry_ms": 1250, "code": "rate_limit",
 "message": "...", "provider": "deepseek", "model": "deepseek-chat"}          # 调度决策
{"type": "llm_retry_started",  "attempt": 2, "provider": "deepseek", "model": "deepseek-chat"}  # 实际开始
```

- chat.py：在 isinstance 链加两分支 → `_xy_chunk(_id({...}))`；GUI `core.ts` 解析进 `EventIdentity` 保留（P0 不渲染，P1 加倒计时徽章可选）。

## 3. 分步与验收

| 步 | 内容 | 验收 |
|---|---|---|
| A1 | 分类器 + `LlmFailure`（纯函数）+ 单测 | 状态码×类型矩阵全对；retry_after 透传；无状态码不崩 |
| A2 | 引擎重试环 + 两事件 + EMPTY_RESPONSE + 审计 | 429/网络 300 次模拟全部重试且退避符合；零 chunk 走 empty_response；非重试码立即失败；abort 不重试；失败轮无半条消息进史 |
| A3 | interrupted anchor + Message/StoppedEvent 字段 | 强杀/取消后 resume：部分文本可见且标中断；tool 配对完整 |
| A4 | chat.py 两分支 + GUI core.ts | 新帧不破坏既有解析（类型收窄安全）；GUI typecheck 过 |

测试落点：新 `tests/test_llm_failure_codes.py`（A1）；`tests/test_query_loop_retry_a2.py`（A2，fake 模型注入）；A3 并入既有崩溃恢复测试族。

## 4. 不采纳（记录）

- 重试=新 turn 重建（DSH 完整版）：依赖 request/header 快照（欠账 F）；XEYO 简化版 = 同 turn 重建，
  因 assistant 消息只在流结束后落盘（§0 事实），语义等价且无需快照。
- 重试事件进 transcript/log-only 投影：XEYO 非事件溯源（保 JSONL+sidecar 口径）；帧只走 SSE 通道。

---

## 5. 完成注记（A1–A4 已落地，验证全绿）

> 实施要点与计划差异：
> - **A1 分类器**：`common/errors.py` 增 `LlmFailureCode`（10 码）、`LlmFailure`、`classify_llm_failure`、
>   `empty_response_failure`、`parse_retry_after`（delta-seconds / RFC 7231 日期双格式，坏值→None 走本地退避）、
>   `EmptyResponseError`；完整矩阵 19 例单测。
> - **A2 重试环**：`query_loop.py` 流消费点改为 attempt 循环——仅「失败尝试零 chunk」原地重试
>   （已吐 chunk 的失败直接收敛，防 GUI 重复吐字）；`XEYO_LLM_MAX_ATTEMPTS` 钳制 [1,5] 默认 3；
>   退避 500ms→10s + 10% jitter，厂商 Retry-After 更大时取厂商值；`llm.failure` 审计（code/attempt/status/provider/model）。
> - **A3 中断锚**：`Message.interrupted` + transcript/row_from_message/hydrate 全链序列化；
>   abort 时 `_persist_interrupted_anchor` 写入「已吐但未落盘」的部分输出；`StoppedEvent.interrupted`；
>   chat.py stopped 帧文案 → `aborted (interrupted)`。工具阶段 abort 无需锚（assistant 消息已完整落盘）。
> - **A4 帧/解析**：`LlmRetryEvent`/`LlmRetryStartedEvent` → chat.py 两分支 → core.ts 类型+解析 → chatStream.ts 分发（双调用点）。
>   适配器 Retry-After 接线：deepseek.py（httpx/HTTPError/非流式三处）+ openai_compat.py（httpx/HTTPError 两处）。
> - **wire 细则核对结论**：usage 先于 finish——XEYO 无独立 finish 帧，usage 在流内 `include_usage` 读取（结构性满足）；
>   **reasoning passback 未做**——XEYO 刻意不持久化 reasoning（只留尾部注入下一轮 T_now），
>   与 DeepSeek「带 reasoning 的 assistant turn 回传 reasoning_content」要求存在已知差异，
>   属「reasoning 不入史」红线的既有张力，记录为 P2 选题而非本项补做。
> - **验证**：A 项全套（分类器 19 + 重试环/中断锚 8）+ 邻域（query_loop 26 + 信封 6 + 会话层 49 + server API 18 +
>   model 契约）**全部通过**；GUI `tsc --noEmit` 通过。
> - **已知边界**：已吐 chunk 的中途失败无自动恢复（设计取舍，见 §4 不采纳）。
