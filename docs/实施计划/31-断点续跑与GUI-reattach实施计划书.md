# 31 — 断点续跑与 GUI reattach 实施计划书

> 状态：已落地（P0/P1 主路径）  
> 对应问题：刷新杀任务、重启不续跑、手动「继续」语义弱

## 根因（冻结）

| 现象 | 根因 |
|------|------|
| 刷新 GUI，AI 任务断掉 | SSE `is_disconnected` → `engine.interrupt()`；连接=租约 |
| 重启后 AGENT 不自动继续 | 只 hydrate 消息；无 TurnSnapshot / 无 startup recovery |
| Stop 后「继续」怪 | resume cue 未接入 live path；裸用户口令靠模型猜 |

产品路径是 **Agent-as-tool**，不复活旧 `run_task_batch`。

## 设计原则

1. **SSE 是订阅者，不是执行租约** — Turn 由 `TurnRunner` 拥有。
2. **消息恢复 ≠ 任务恢复** — JSONL / `.working.json` + `.turn.json`。
3. **显式 Stop 才 interrupt**；刷新只断投影流。
4. **「继续」注入结构化 `[Resume]` 前缀**（用户气泡仍显示「继续」）。
5. Tauri 关窗杀 Python → P2（本迭代不做 daemon）。

## 已实现

### Phase 0 — 观测

- `turn_start` / `client_disconnect` / `turn_end` / `turn_stopping` 结构化日志（`xeyo.turn_runner` / `xeyo.chat.stream`）
- 前端 `turnDetached` / `isTurnLikelyDetached`；`recoverStuckStream` 不再默认 `interruptChat`

### Phase 1 — 刷新不断 + reattach

- [`python/engine/turn_runner.py`](../../python/engine/turn_runner.py)：detached producer + 事件 ring + subscribe(cursor)
- [`python/server/routers/chat.py`](../../python/server/routers/chat.py)：disconnect **不** interrupt；HTTP CancelledError 只记 disconnect
- `GET /v1/sessions/{id}/task`
- `GET /v1/sessions/{id}/turns/current/events?cursor=`
- 前端 `streamTurnEvents` / `reattachStream` / hydrate+focus 后 `reattachActiveStreams`
- `sessionStorage` 保存 `turnCursor` 供刷新追赶

### Phase 2 — 「继续」语义

- `_is_multi_agent_resume_cue` 接入 live submit
- `_build_enriched_resume_prompt`：原目标 + incomplete todos + stop_reason
- 仅非 resume cue 时 clear legacy scheduler checkpoint
- Stop 后 Composer chip「继续未完成任务」

### Phase 3 — 重启 recovery

- [`python/engine/turn_snapshot.py`](../../python/engine/turn_snapshot.py)：`~/.xeyo/sessions/{id}.turn.json`（与进程内 `SessionTaskState` 分离）
- lifespan：`running` → `recovery_required`；子 agent `running` → `interrupted`
- GUI `RecoveryBanner`：继续 / 放弃（`POST .../recovery/abandon`）

## 验收清单

- [ ] 中途刷新：工具继续执行，刷新后 reattach 收到后续帧与 final
- [ ] 刷新中点 Stop：任务停止，UI 一致
- [ ] Stop →「继续」：模型引用原目标 / todos，而非空转追问
- [ ] 杀 Python 再起：出现 recovery 条；继续可走 enriched resume
- [ ] channel/微信路径不受影响

## 明确不做（P2）

- Tauri detach / 关窗仍跑 Agent
- Permission pending 落盘
- 复活 scheduler DAG 主路径

## 测试

- `python/tests/test_turn_detach_reattach.py`
- 既有 `test_multi_agent_p1.py` resume cue 单测仍有效
