# 事故：无主 tool 结果 400（会话结构性卡死）— 诊断与修复

日期：2026-09-20 · 归属：本轮（wire 兜底 + manifest 补漏报）· 状态：已修（兜底+检测），生产者未定位

## 现象

会话说 `sess_mu9oqy8m_63ljiu`（WSC / Codex holdout 那轮）对**之后每一条**消息都以 400 失败：

```
请求参数有误（400），请检查输入后重试
(Messages with role 'tool' must be a response to a preceding message with 'tool_calls')
```

## 证据链

| 证据 | 位置 | 内容 |
| --- | --- | --- |
| transcript 尾部停在用户消息后无 assistant | `~/.xeyo/sessions/sess_mu9oqy8m_63ljiu.jsonl` | 末行 = 用户「继续」（19:34:02），无后续 assistant 行 ⇒ 回合在第一次模型调用即死 |
| 该次调用立即失败 | `~/.xeyo/audit/audit.jsonl` | turn `11024d16ba7d`：`model.started` 19:34:02.301 → `.971` `model.finished status=failed error_code=provider_error`，未吐任何 chunk |
| 引擎自评投影 | `.working.json::last_projection_manifest`（`proj_2b74c801d0463fb9eacf9a74`） | `tool_calls_seen=137`、**`tool_results_seen=138`**、`tool_pairs_preserved=137`、`unresolved_tool_calls=0`、**`invariant_errors=[]`** |
| 上一轮已被该厂商拒过一次 | 同上 audit | 19:30:12 `status=protocol_fallback error_code=HTTP_400` ⇒ system 声道被拒 → 进程内退回 env 伪对；该轮最后成功发出的请求体（`last_x_sent`）确实以 `assistant(tool_use xeyo_env_…) → user(tool_result xeyo_env_…)` 收尾 |
| 磁盘历史本身是干净的 | 离线 hydrate transcript | 140 calls / 140 results，全配对（`messages_from_transcript` + `as_api_messages`） |

## 结构性根因

1. **投影尾部无配对守卫**：`session.tool_sequence.discard_unpaired_tool_results` 只覆盖
   MessageStore 投影**之前**的内部形状；压缩 / T_now 注入 / 运行时改写之后（最后一公里）没有任何
   配对校验。一旦多出一条无主 `role="tool"` 行，厂商即 400。
2. **坏形状可复现 ⇒ 卡死**：投影每轮从同一状态重算同一个坏形状，所以「改消息内容」永远无效。
3. **自检漏报**：`engine/projection_manifest` 只查「调用无结果」（`unresolved_tool_calls`），
   不查「结果无调用」⇒ 坏投影被判合法，事故第一次发生时无任何信号。

## 本轮改动

| 文件 | 改动 |
| --- | --- |
| `python/model/_openai_common.py` | 新增 `prune_orphan_tool_rows()`，并在 `normalize_messages_for_openai` 出口调用：丢弃没有前置 assistant tool_calls 应答的 `role="tool"` 行（fail-open；只记 id 数量与前 5 个 id，不记内容）。合法配对（含 `xeyo_env_` 伪对）不受影响 |
| `python/engine/projection_manifest.py` | `invariant_errors` 增加 `orphan_tool_results:<n>`（`projected_results - projected_calls`） |
| `python/tests/test_wire_orphan_tool_guard.py`（新） | 5 例：配对不被误删、无主 tool 行被丢、user 行里的伪对残片被丢、env 伪对存活、干净时返回原对象并回 id |
| `python/tests/test_projection_manifest.py` | 新增 `test_projection_manifest_flags_orphan_tool_result` |
| `python/tests/test_reasoning_replay_contract.py` | 3 例 fixture 补前置 assistant tool_calls（原 fixture 是 wire 上非法的裸 tool 行，此前"通过"属侥幸；断言意图不变） |

## 验证

```
pytest tests/test_wire_orphan_tool_guard.py tests/test_projection_manifest.py \
       tests/test_message_store.py tests/test_reasoning_replay_contract.py        → 36 passed
pytest tests/test_media_store.py tests/test_model_client_contract.py \
       tests/test_reasoning_retention_contract.py tests/test_t_now_env_channel.py \
       tests/test_t_now_system_channel.py tests/test_wire_orphan_tool_guard.py \
       tests/test_projection_manifest.py                                          → 69 passed
pytest tests/test_unclosed_tool_use_t4.py tests/test_record_transcript.py \
       tests/test_t_now_block_registry.py tests/wsc                               → 196 passed
```

## 未解决 / 下一步

1. **生产者未定位**：磁盘历史干净、live 投影 137/138 ⇒ 漏出的那一半产生于最后一公里的改写
   链（最可疑：跨轮残留的 `xeyo_env_notice` 伪对——projection-only 状态本不该跨轮存活，
   上一轮 env_channel 的最后一次请求确实以伪对收尾）。下一步：把伪对从投影里剥掉（每轮注入前
   清理历史里遗留的 `xeyo_env_` 成对残片），或在 `_attach_turn_context` 前做一次
   internal 形状的 orphan 清理。
2. **Anthropic 路径未加同一守卫**（`normalize_messages_for_anthropic`）——同一类风险，未在本次范围。
3. **观测**：兜底命中只写 server 日志（warning，含 id）。若要进审计面，可在 query_loop 的
   `build_manifest` 处把 `invariant_errors` 也记一条 audit（manifest 目前仅落 `.working.json`）。
4. **恢复方式**：重启后端（重新 hydrate transcript，磁盘历史干净）后，卡死会话应可继续；
   兜底生效后即使投影再坏也不会再砖会话。
