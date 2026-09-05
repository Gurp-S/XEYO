# 45-主会话与子Agent消息inbox设计

mid-turn inbox 对齐 DSH（``send_message``/``interrupt_agent``/``list_agents`` 三分工具
提炼出的语义基线）。**硬约束**：KV 前缀零破坏 + 最大省钱 + 最优性能。

## 1. 语义基线（从 DSH 提炼的四条）

1. **消息只在回合边界投递**——不能改道已在进行的回合（硬约束，非实现细节）。
2. **inbox 是对话的一部分**——停靠消息属于该 agent 的持久对话，打断回合也不丢。
3. **agent 是持久会话**——侧链 JSONL 存在即 ``ready`` 态（XEYO 不建长驻 idle agent）。
4. **投递与结果分离**——post 即确认，结果待回合 settle 后另行排水。

## 2. KV 前缀契约（零破坏）

请求形状恒为三段拼接，任何改动不得改变顺序：

```
[system 左段(字节稳定)] + [history(只 append, 绝不插入中部)] + [T_now(仅锚最新 user 消息)]
```

- 实现保证（已在代码）：``prompt/pre_llm_inject.run_pre_llm_inject`` 只经
  ``turn_context.append/prepend_text_blocks_to_last_user``（copy-on-write）把易变块锚到
  **末条 user**，**永不触碰 system 段**（模块 docstring 明示「禁止插入 system 左段（保 KV 前缀）」）。
- 排队投递（P1）＝「用户此刻手发一条消息」的**逐字节等价**：``submit_synthetic`` 只回传一条
  user 消息，engine warm 时 ``get_or_create`` 复用 ``mutable_messages``；cold 时
  ``messages_from_transcript`` **无截断**。
- 铁律：
  1. 排队文本/易变块**绝不进 system/前缀**；**绝不在历史中部插入消息**；
  2. follow-up 轮的系统前缀与首轮**逐字节一致**（同实例生成，见 §4.2）；
  3. 已知边界：子 agent 跨午夜（``date_iso`` 变）→ 一次性前缀 miss（接受）。
- 回归测试：``tests/test_cache_prefix_invariant.py``（system 不污染 / 易变块只锚最新 user /
  正常轮 vs inbox 轮除最新 user 外逐字节一致 / 工具续写轮投影-only user 追加）。

## 3. 主会话 inbox（P1）

### 3.1 数据结构（``python/server/inbox_registry.py`` 单例）

```python
@dataclass
class InboxItem:
    queue_id: str; text: str; media_refs: list[str]; message_id: str | None
    queued_at: float; attempts: int; state: str  # queued | delivering | stuck
```

per-session FIFO（``deque``）+ 线程锁（同 ``session_pool`` 锁纪律）。队列**仅内存**（与
``_pending_interrupt`` 同口径，进程重启即丢）。

### 3.2 投递接线图（复用 41/42 已验证通道）

```
用户 post（回合忙，queue_if_busy）
   └─ chat.py 202；enqueue FIFO
settlement（turn_runner finally 后）
   └─ turn_settlement_hub.on_turn_settled
        ├─ 租户1 InboxRegistry.on_turn_settled   ← 排第一
        │    ├─ succeeded/failed & 且空闲 → create_task(_drain)
        │    │    ├─ COALESCE=1 → pop_all → submit_synthetic(join "\n\n", surface="inbox")
        │    │    └─ COALESCE=0 → peek → submit_synthetic(单条)
        │    └─ stopped/cancelled → hold（下一条由再次人类 settle 或 resume）
        ├─ 租户2 GoalRoundDriver   （_precheck 见 _turn_running=True → 自动跳过 = 用户优先）
        └─ 租户3 JobRegistry
```

- **优先级**：inbox 租户排第一；inbox 提交后 goal ``_precheck`` 的 ``_turn_running`` 判活为真
  → 跳过 goal 续跑（**不改 goal driver**）。
- **省钱的优先级**：goal 续跑的共享唤醒预算由 inbox 轮的 ``_human_surface`` 恢复——
  ``surface="inbox"`` 视为人类面（``yield_to_human`` + ``restore_wake`` 均为有意行为），但
  跳过 ``set_pending_jobs_digest``（省 input token）与 resume 富化 / goal 自动创建 /
  checkpoint 清理。

### 3.3 批投（省钱主杠杆）

``XEYO_INBOX_COALESCE``（默认 1）：settle 时把队列里**此刻全部**消息合并为一个合成轮
（``\n\n`` 分隔）。收益：N→1 轮 = 省 N-1 个「满上下文输入 + 输出」；且 N-1 个回合不计入
``turns_since_c2``，**降低提前触发 C2 压缩**（压缩=全前缀重建=成本尖峰+KV 破坏）。
代价：转录并成一条（GUI 保留独立气泡，仅线上合并）；``=0`` 退回逐条（DSH 语义）。

### 3.4 HTTP / SSE 协议表

| 方法 | 路径 | 作用 | 返回 |
| --- | --- | --- | --- |
| POST | /v1/chat/completions | 常规流式；忙时 `queue_if_busy=True` → 排队 | 202 `{queued, queue_id, position}`；否则 409 |
| GET | /v1/sessions/{sid}/inbox | 队列快照（GUI 轮询驱动 chip） | `{autorun, coalesce, items[]}` |
| DELETE | /v1/sessions/{sid}/inbox/{queue_id} | 取消单条 | 200；delivering → 409 `inbox_delivering` |
| POST | /v1/sessions/{sid}/inbox/resume | 清 stuck/重新 arm | snapshot |

GUI 以 2s 轮询（busy 时）驱动 chip；不新增 SSE 帧（与 jobs 轮询同范式）。

## 4. 子 Agent follow-up inbox（P2）

### 4.1 运行时收件箱（``python/engine/live_agents.py``）

``_INBOX[key="{sid}::{aid}"] = list[{text, message_id, queued_at, state}]``，同锁。
``post_to_agent``（仅入队，park 不注入）/``drain_agent_inbox``（原子取空）/
``inbox_count``/``remove_agent_inbox_item``/``clear_agent_inbox``。

### 4.2 同实例续跑循环（``engine/subagent_runner._run_subagent_body``）

复用同一 ``sub_store``/``reg``/system parts/``BudgetTracker``（**零重建**，系统前缀同实例生成）
首轮 settle 后：

```
while not abort.aborted and cycle_no < XEYO_SUB_FOLLOWUP_LIMIT(3):
    followups = drain_agent_inbox(sid, aid)
    if not followups: break
    sub_store.append(user_message(f"[Resume] Continue.\n\nUser follow-up:\n{first}"))
    以 followup 小预算(12轮/24工具) 再跑一次 query_loop
    # 其余 followups 放回队列（保 FIFO），下次循环再取
```

- 侧链自然延续（``record_transcript`` 增量续写），GUI 卡片无感知中途拆分；``register_live_agent``
  覆盖全程（卡片持续「运行中」）。
- 事件：follow-up 交付走 ``ToolProgressEvent.xy`` 直通（``multi_agent_followup``），无需新 SSE 管道。

### 4.3 已结束 agent 的迟到消息

- 存 meta ``pending_followups``（``upsert_subagent_meta`` merge-keep）；``inbox_count`` 为派生值
  （读取时 = ``len(meta.pending_followups) + live.inbox_count``）。
- retry：``clear_sidechain`` 后把 ``pending_followups`` 置入运行时 inbox，follow-up 循环同实例消费
  （重跑清侧链但消息不丢）。

| 方法 | 路径 | 作用 | 返回 |
| --- | --- | --- | --- |
| POST | /v1/sessions/{sid}/agents/{aid}/inbox | 投递 follow-up | `{ok, deliver: running\|pending, inboxCount}` |
| DELETE | /v1/sessions/{sid}/agents/{aid}/inbox/{item_id} | 取消 follow-up | `{ok, deliver, removed}` |
| GET | /v1/sessions/{sid}/agents | 列表（含 `inboxCount`） | agents[] |

## 5. 观测（P3）

``/health`` 聚合：
- ``inbox``：``pending``/``stuck``/``sessions``/``batches_delivered``/``items_delivered``/
  ``tokens_est``（合并轮 chars/4，估算）。
- ``prefix_cache_hit_ratio`` / ``last_cache_hit_tokens`` / ``last_cache_miss_tokens``：由
  ``query_engine.budget_snapshot`` 透出最近一轮 usage 的 cache 拆分裂（``pricing_mod.split_usage``），
  ``session_pool.usage_snapshot`` 聚合；无数据为 ``None``。

GUI 卡片角标：``AgentDoneBars`` 经 ``loadAgentsFor`` 合并 ``listSessionAgents`` 返回的
``inboxCount``，>0 渲染 ``+N`` 角标（follow-up 已排队）。

## 6. 边界与失败模式

见计划书 §六（权限等待不排水 / stop→hold / 队列满载 429 / 批投窗口 / 服务重启队列丢失+
进 LLM 前拒绝 / resume / follow-up 限次 / 迟到消息不复活 / date_iso 跨午夜 / side- 与 CLI 保持 409）。

## 7. 验收要点

- ``test_cache_prefix_invariant`` 绿（KV 零破坏被证明）；
- busy 中发送 → 202 + chip；settle 后自动下一轮；``COALESCE=1`` 批投 N→1；
- 子 agent 运行中 follow-up → 卡片 +1，同实例续跑，侧链含原文；已结束 → meta pending，retry 附带；
- CLI/side 行为不变；``run-pytest-p0b.bat`` 通过。
