# 38 · Goal 一等状态实体设计（工作区注册表 / 混合完成语义）

> 目标：把 goal 从「附属于 turn 的文本」升格为有身份（goal_id）、有 lifecycle（显式转换表）、
> 有权威（GoalStore）、有并发控制（revision CAS + WorkspaceLock）的一等状态实体。
> 作用域为**工作区级注册表**（goal 可跨 turn / 跨会话被引用），完成语义为**混合：
> 派生触发候选 + 用户隐式/显式确认**。goal 层只做 lifecycle 记账与提示投影，
> **不做任何执行控制**（不杀 turn、不挡工具、不改调用循环）。

## 0. 冻结口径

| # | 决策 | 口径 |
|---|------|------|
| 1 | 实体化 | goal 是一等实体：goal_id 稳定身份 + 显式转换表，取代「文本随 turn 走」 |
| 2 | 作用域 | **工作区级注册表**（`<workspace>/.xeyo/goals/`），跨 turn / 跨会话；不跨 workspace |
| 3 | 完成语义 | **混合**：确定性派生触发候选（pending_complete），用户隐式确认（下一条实质消息）或显式确认（GUI / 斜杠）后落 completed；**模型 P0 无权宣布完成** |
| 4 | 状态集 | 落盘仅 4 态：`active / blocked / completed / abandoned`；`awaiting_input` 是投影派生态（见 §3），不落盘 |
| 5 | 权威边界 | GoalStore 只权威 goal lifecycle；turn 执行权威仍在 SessionTaskState / TurnRunner，多 Agent 批次权威仍在 scheduler checkpoint |

## 1. 背景与现状缺失

现状（见 31-断点续跑与GUI-reattach 实施计划书落地的三层机制）：

- 进程内权威 `engine/task_state.py`（SessionTaskState，7 态，纯内存）；
- 落盘恢复 `engine/turn_snapshot.py`（TurnSnapshot，sidecar JSON，`goal_text` 宿主）；
- 事件驱动转移 `engine/turn_runner.py`（detached turn，permission/stop/error 分支）；
- 多 Agent 批次 `engine/scheduler.py`（checkpoint v2，`user_goal` + `.goal.txt` sidecar）；
- resume 重建 `server/routers/chat.py`（`_previous_user_goal` 历史反向扫描 → snapshot 兜底）。

对照「一等实体」的四块缺失：

| 缺失 | 现状 |
|------|------|
| 身份 | goal 无稳定 id，只有文本；续跑靠消息历史反向扫描（compact/删改后只剩 snapshot 兜底） |
| lifecycle | 无状态集；turn 终态后 goal 状态未知；blocked / awaiting_input 语义不存在 |
| 权威 | goal 真相散落四处（turn snapshot / checkpoint / 消息历史 / goal.txt），无 single source of truth |
| 并发 | 无 revision 校验；任意路径可覆写；工作区级共享时 last-writer-wins |

## 2. 实体模型

```python
# engine/goal_state.py
GoalStatus = Literal["active", "blocked", "completed", "abandoned"]

@dataclass
class Goal:
    goal_id: str            # uuid4().hex[:12]，稳定身份
    title: str              # 短标签（首条消息截 60 字符；仅供 GUI/列表）
    text: str               # 目标全文，≤4000（与现 goal_text 上限一致）
    status: GoalStatus = "active"
    origin_session_id: str  # 创建者会话
    origin_message_id: str  # 溯源发起消息
    owner_session_id: str   # 当前驱动会话（可被 resume 重新绑定）
    task_batch_id: str = "" # 多 Agent 批次回链（可空）
    blocked_reason: str = ""            # blocked 必填
    pending_complete: bool = False      # 候选完成标记（派生触发）
    pending_complete_reason: str = ""   # todos_all_done / batch_awaiting_synthesis / synthesis_done
    revision: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    reopened_at: float = 0.0
```

约束：**每个会话同时至多绑定一个非终态 goal**（binding 指针）；工作区注册表里可并存多个
goal（不同会话各驱各的，或历史终态归档），但单 goal 单 owner。

## 3. 状态机与转换表（落盘态）

```
create:  无 binding 且非续跑实质消息 ──→ active（owner=发起会话）

active    → blocked      turn 终态 failed；进程重启 recovery_required；reason 必填
active    → completed    候选 + 显式确认（GUI 按钮 / /goal done）
                         或候选 + 隐式确认（owner 会话下一条非续跑实质消息）
active    → abandoned    显式 /goal drop；显式 /goal new 时旧 goal 归档（reason=superseded）
blocked   → active       resume cue / 重试（re-arm，清 blocked_reason）
blocked   → abandoned    显式 drop
completed → active       reopen（显式；记 reopened_at）
abandoned → active       reopen（显式）
其余一切转换 ──✗ 拒绝并记日志（不影响 turn 主路径）
```

**投影派生态（不落盘）**：`awaiting_input` = 绑定 goal 为 active 且该会话 live turn
`waiting_permission == True`（或 Ask 模式）。秒级权限等待只在读投影（API / T_now 块 /
GUI）时组合，不产生落盘写抖动。

**候选完成不是终态**：`pending_complete=True` 时 goal 仍是 active；清除条件：
同 goal 又发起 turn 且派生条件不再成立（如出现新 pending todo），或 resume cue。

## 4. 工作区注册表：存储与并发

### 4.1 存储布局

```
<workspace>/.xeyo/goals/
  goals/<goal_id>.json               # 实体；tmp + os.replace 原子写；坏文件跳过并记录
  bindings/<safe_session_id>.json    # {goal_id, bound_at, last_turn_id}
```

- workspace 由请求入口 cwd 解析（`engine.config.cwd` / `_pool.session_cwd`），
  同 scheduler checkpoint 范式；cwd 不同即不同注册表（goal 不跨 workspace）。
- TurnSnapshot 在 `~/.xeyo/sessions/`（home），注册表在 workspace —— 两者按现有
  分层各归各位：跨进程恢复快照归 home，工作区共享的 goal 归 workspace。

### 4.2 并发控制

| 场景 | 机制 |
|------|------|
| 同进程并发 | 模块级 per-workspace asyncio 锁，包住「读-转-写」 |
| 跨进程（GUI / 通道服务 / 脚本） | 每次转换持 `engine/workspace_lock.WorkspaceLock(owner=f"goal:{session_id}", ttl=10)` 短租约（复用回溯 v3 已有租约管理器） |
| 客户端 API 写 | PATCH 带 `revision` 做 CAS，过期拒绝让客户端重读 |
| 执行串行化 | 不新增：TurnRunner 每会话至多一个活跃 turn 天然串行化单会话执行 |

goal 层任何文件/锁异常**只降级不阻断**：钩子全部 try/except + log，
坏 goal 文件跳过并记录（与扩展层坏 manifest 同纪律）。

## 5. 完成语义（混合，冻结口径 #3）

**派生触发**（turn 终态钩子计算，只写 pending_complete 字段）：

| 触发点 | 条件 | reason |
|--------|------|--------|
| 主循环 turn 终态 | succeeded 且 working.todos 非空且全 done | `todos_all_done` |
| 多 Agent 批次 | checkpoint all_succeeded | `batch_awaiting_synthesis` |
| synthesis turn | 终态 succeeded 且批次已 awaiting_synthesis | `synthesis_done` |

**确认路径**：

- 显式：GUI「标记完成」按钮、`/goal done` → `completed(confirmed=explicit)`。
- 隐式（默认）：候选存在时，owner 会话**下一条非续跑实质消息** → 先
  `completed(confirmed=implicit)`，再立即用该消息 create 新 goal（一气呵成，一个事务）。
- 反悔通道：候选存在但用户要继续 → GUI「继续此目标」按钮 / `/goal continue` /
  resume 口令 → 清候选，消息并入当前 goal（继续干活，不新开）。

**边界声明**：隐式确认是默认值不是真理——「还差 X，继续」这类实质消息会被判成
新 goal，此时旧 goal 已被派生判候选（todos 全 done），误伤面小；reopen 是一等
转换（§3），纠错便宜。远程通道（iLink / 文件传输助手）无 GUI 按钮，靠
`/goal continue`（P2 进远程白名单）或接受隐式默认。

**模型权限**：P0 模型**无权**触发任何 goal 转换；P2 再评估在 wrap-up 轮给模型
「建议完成」的软信号位（仍需用户确认）。

## 6. 触发点接线（只注册，不改调用循环）

| # | 触发点 | 位置 | 动作 |
|---|--------|------|------|
| 1 | 创建 / 维持 binding | `chat.py` submit 入口（非续跑分支） | 无 binding → create + bind；候选 + 实质消息 → 隐式确认 + create（§5） |
| 2 | blocked | `turn_runner._run_producer` finally（failed）；`turn_snapshot.mark_crashed_as_recovery` | active → blocked(reason=…) |
| 3 | 候选派生 | 同 #2 的 succeeded 分支；`scheduler.all_succeeded` / synthesis 收尾 | 置 pending_complete |
| 4 | re-arm | `chat.py` resume_cue 分支 | blocked → active；清候选；owner 重绑为当前会话 |
| 5 | 归档 / drop | slash `/goal`（P2）、PATCH API | 显式转换 |

所有钩子仅调用 `goal_state` 模块函数，不在调用循环内展开逻辑（AGENTS.md「只注册」范式）。

## 7. resume 链路反转

```text
goal = GoalStore.current(cwd, session_id)          # binding → hydrate 实体
     →（P1 懒采纳）binding 缺失但 prev_snap.goal_text 非空 → 采纳为实体（origin=adopted）
     → _previous_user_goal(messages)               # 历史反向扫描，终兜底
     → prev_snap.goal_text → user_text             # 现有最后兜底不变
```

- 富化续跑前缀（`_build_enriched_resume_prompt`）**保持 submit 文本注入方式不变**
  （它是一次性的，不属易变投影）；GoalStore 就绪后其 goal 来源改为实体。
- scheduler 的 `<sid>.goal.txt` / `last_multi_agent_goal.txt` 保留为兜底，不删。

## 8. T_now 注入（Goal 块）

- 构造：`prompt/pre_llm_inject.py` 新增 `build_goal_block(goal, live)`，
  块头 `# Goal（background only）`（归属声明防弱模型当新提问）。
- **注入条件（全部满足）**：非 after_tools；`inject_instructions` 开（工人短上下文不挂）；
  存在绑定 goal 且（`status=blocked` 或 `pending_complete`）。
  **active 常态不注入**——避免每轮噪音，这是它与 Mode / Nested 块的关键差异。
- 内容：goal_id / 标题 / 状态 / blocked_reason 或候选提示 / owner 会话 +
  live 派生态（「等待权限放行」）。截 1200 字符。
- 预算：参与 `T_NOW_EXTRA_BUDGET` 正常裁剪；**不是**「开了必须生效」的开关类，
  不学 wrap-up 后置强挂。
- 红线：不进 system 左段；不回写 MessageStore / JSONL（copy-on-write 只改投影）。

## 9. API 与 GUI

**API（additive）**：

- `GET /v1/sessions/{sid}/turns/current`：响应加 `goal: {goal_id, title, status,
  pending_complete, blocked_reason} | null`（现 `goal_text` 字段保留不动）。
- `GET /v1/sessions/{sid}/goal`；`PATCH /v1/sessions/{sid}/goal`
  （`action: confirm_complete | continue | drop | reopen | new`，带 revision CAS）。
- `GET /v1/goals?status=…`（P2，注册表列表）。

**GUI**（前端只消费投影，不做权威）：

- `api.ts` 类型 + chatStore goal slice（复用 turns/current 轮询/SSE 通道）。
- 状态 chip：active 灰 / 候选绿描边 / blocked 琥珀 / awaiting_input 青色（派生态）。
- 候选条：「标记完成 / 继续此目标」双按钮 → PATCH。
- 恢复横幅（ChatPage 现有 goal_text）改读 goal 实体，fallback goal_text。

## 10. 兼容与迁移

- `goal_id` additive：TurnSnapshot / TurnPublic / sessions API 加字段缺省 `""`，
  全部现有消费者与测试不变（`""` = legacy 行为）。
- 懒采纳（P1）：老会话首次 resume 时把 snapshot `goal_text` 采纳为实体，此后以注册表为准。
- 坏 goal 文件 / 坏 binding：跳过并记录，resume 自动落到历史扫描兜底——功能不缺失，只降级。

## 11. 切片

| 切片 | 内容 |
|------|------|
| P0 | `engine/goal_state.py`（实体 + 转换表 + 存储 + asyncio 锁/WorkspaceLock/CAS）；触发点 #1/#2/#4；`TurnSnapshot.goal_id` additive；`GET/PATCH …/goal`；测试 |
| P1 | 候选派生（触发点 #3：todos + scheduler）；T_now Goal 块；GUI chip + 候选条；懒采纳 |
| P2 | `/goal` 斜杠族（入 37 号 manifest，远程白名单评估）；跨会话 peer goal hint（background only，复用 session_presence 范式）；`GET /v1/goals` 列表；wrap-up 软信号评估 |

## 12. 测试清单（范式：test_task_state / test_multi_agent_p1 / test_turn_detach_reattach / test_pre_llm_inject）

- 转换表：合法链全通过；非法转换拒绝（blocked→completed 等）并记日志；
  revision CAS 冲突重试与过期拒绝。
- 崩溃链：running → 进程重启 recovery_required → goal blocked → resume → active。
- 隐式确认：候选 + 实质消息 → completed + 新 goal 原子创建；候选 + resume cue → 清候选继续。
- 派生：todos 全 done → candidate；出现新 pending → 清除；scheduler 批次两触发点。
- 兼容：无 goal 文件时 resume 走 fallback 链；goal_id="" 全投影不变。
- 注入：工人不挂 / after_tools 不挂 / active 常态不挂 / blocked 与候选才挂；预算裁剪。
- 并发：同进程 asyncio 锁互斥；跨进程 WorkspaceLock 租约互斥（复用 test_workspace_lock 手法）。

## 13. 明确不做

- **goal 树 / 层级 / 单会话多活跃 goal**——binding 单指针，需要时再扩。
- **跨 workspace goal**——注册表严格跟随 cwd 所在工作区。
- **模型直宣布 completed**（P0）——防弱模型乱宣布；P2 只做软信号。
- **goal 进 system 左段 / 会话历史**——易变内容走 T_now，红线同 32 号冻结口径。
- **goal 层做执行控制**——不杀 turn、不挡工具、不阻塞续跑；它只是 lifecycle 记账 + 提示投影。
- **新调度 / 后台线程**——全部复用现有钩子位置。
- **非候选期的 goal 漂移治理**（用户连发多个不同目标但从未触发候选）——P0 接受漂移，
  靠显式 `/goal new` 兜底；模型分类新/续目标是独立方向，不入本设计。

## 14. 开放问题

1. 隐式确认在远程通道的误判率——iLink / 文件传输助手灰度后回看。
2. goal text 修订（amendment 列表）是否需要——候选继续路径暂只清标记不改写 text。
3. WorkspaceLock 每次转换短租约在多通道高并发下的开销——P0 先冻结此粒度，跑一段再看。
4. P2 wrap-up 软信号的注入位与文案——等 P1 候选条上线后按真实误判数据定。
