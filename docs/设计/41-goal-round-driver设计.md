# 41 · Goal Round Driver 设计（跨轮自动续跑 / armed 进程内 / GUI 对齐 DSH）

> 目标：在 38 号 Goal 一等状态实体之上补上「驱动」——turn 结束后若 goal 为 active 且用户
> 显式 armed，则自动预约并执行下一轮（复用 chat submit 管线），直到候选确认、blocked、
> 达 cap 或用户停止。语义对齐 `dsh-goal` + `dsh-goal-round-driver`（对照报告 §4），
> GUI 功能对齐 `dsh-client-ui-goal`（GoalBar），样式融入 XEYO 主题。
> **铁律不变**（38 号 §13）：armed 只在内存、进程重启必静止；driver 不杀 turn、不挡工具、
> 不阻塞续跑；全部钩子只注册、不改调用循环。

## 0. 冻结口径

| # | 决策 | 口径 |
|---|------|------|
| 1 | 轮次上限 | 默认沿用 `GOAL_ROUND_CAP=32`；全局默认可在 `~/.xeyo/config.toml`（`[goal] round_cap`）调；**arm 时可按 goal 覆写**（实体新增 `max_rounds`，对齐 DSH「maxGoalRounds 属于目标定义」） |
| 2 | 激活权 | **显式 arm**（GUI 按钮 / API），绝不随 goal 创建自动 armed；普通对话自动建 binding 不会引发自动续跑 |
| 3 | 失败策略 | turn 终态 failed / 用户 stop → **补 blocked 记账（failed）或 disarm（user_stop）**，不自动重试；解除后由用户显式恢复 |
| 4 | 人类消息 | 让位优先级最高：轮间已预约 → 取消预约放行人类消息；轮中 → 现有 409 busy 语义不变；**人类轮不消耗 cap**（修正 T9 现状，见 §3.2） |
| 5 | GUI | 功能对齐 DSH GoalBar（四动词面 + whole-value 投影），样式用 XEYO dock 卡片体系；**比 DSH 多暴露 armed 态**（DSH 已知限制，XEYO 单权威 server 可做对，见 §9.4） |
| 6 | 同会话 | driver 只驱动绑定会话自身（DSH 同款：不 spawn、不 fork、不建第二状态机） |

## 1. 背景与现状缺失

38 号已落地 T9：`engine/goal_state.py`（4 态转换表 + `pending_complete` 派生候选 +
`rounds` + revision CAS）+ `server/routers/goals.py`（GET / PATCH + 409）+
`query_engine._maybe_advance_goal_round`（turn 结束 flush→复检→记账）+
T_now Goal 块（blocked / pending_complete 才注入）。

缺的不是状态，是把状态喂回输入队列的驱动：

| 缺失 | 现状证据 |
|------|----------|
| 无跨轮预约 | `_maybe_advance_goal_round`（query_engine.py L392）只记账，不调度 |
| blocked 钩子未接线 | 38 号 §6 触发点 #2（turn_runner failed → blocked）**设计有、实现无**：全库无 `transition(..., "blocked")` 调用，goal 失败后永远停在 active |
| resume 恢复未接线 | 38 号 §6 触发点 #4（resume cue → blocked→active）同样未实现 |
| rounds 语义偏差 | 现状任何人机成功轮都 +1（`_note_round_async`），与 DSH「人类消息不消耗上限」冲突 |
| GUI 零展示 | `gui/src` 无任何 goal 消费；38 号 §9 的 chip/候选条未落地 |

## 2. DSH 语义对照与取舍

| DSH（dsh-goal / goal-round-driver / client-ui-goal） | 本设计 |
|------|------|
| phase 四态 `active/paused/blocked/complete` | 沿用 XEYO 四态 `active/blocked/completed/abandoned`（38 号冻结口径），**不新增 paused**：durable 的「用户主动停」由 disarm（进程内）+ blocked_reason 表达，重启后本就静止 |
| `GoalRef{id,revision}` CAS，mutation 回 `{ref}` ack | 复用 GoalStore revision CAS 与 PATCH 409 语义 |
| armed/disarmed 进程内、绝不持久化、加载不继承 | 完全同款；driver 状态纯内存 dict |
| idle 检查点：flush（失败即 disarm）→ 复检 revision 与竞争输入 → 预约 `roundsStarted+1` → 排队 prompt | settlement 检查点（turn_runner finally 之后）：持久化已由引擎收尾保证（等价 flush）→ CAS 复检 → `create_task` 预约 |
| 只有进入 step 的 `user/message` 才 +roundsStarted；陈旧预约不消耗编号 | 只有 **driver 发起的 turn 真正 start 成功** 才 CAS `rounds+1`；预约被让位/409 作废不消耗 |
| `<goal_round>` 保留 prompt：JSON 引用 goal + round/maxGoalRounds + 权威声明 + 完成需证据 | 复用「继续」resume-cue 管线（`_build_enriched_resume_prompt` 扩展 `round_info`），指令含义等价（§6） |
| 人类消息不占 cap；人类工作让位到 idle 后重新预约 | 同款（§0 口径 4） |
| 取消：有预约/已准入尝试的 goal 下一检查点 pause，失败兜底 disarm | 简化：用户 Stop → settlement 见 `stopped/user_stop` → 直接 disarm（不 pause goal） |
| GUI：GoalBar 挂 composer dock（Todo 后），投影 whole-value，动词 edit/pause/resume/clear，single-flight | SessionGoalDock 挂 Composer 统一外框（SessionTodoDock 旁），SSE xy `goal` 帧 whole-value + GET 播种，动词面 §9.2 |
| maxGoalRounds 属目标定义，可 edit | `max_rounds` 落实体，PATCH `action=edit` 可改，arm 时可带 |

## 3. 实体扩展与 rounds 语义修正

### 3.1 Goal additive 字段

```python
# engine/goal_state.py
@dataclass
class Goal:
    ...
    rounds: int = 1          # 语义变更：只计 driver 准入的 goal 轮（见 3.2）
    max_rounds: int = 32     # per-goal cap（arm 时可覆写；0/缺省 = 用全局默认）
```

- `max_rounds` additive：旧文件无此字段 → `from_dict` 缺省 0 → 运行时解析为全局默认
  （`config.toml [goal] round_cap`，经 `cli.config_store.load_config`，服务端启动读一次）。
- `rounds` 不迁移：历史值是旧语义（含人工轮）的计数，接受偏高，从此按新语义累加。

### 3.2 rounds 只由 goal 轮推进（修正）

| 动作 | 现状 | 本设计 |
|------|------|--------|
| 人工 turn 成功 | `rounds+1` | **不动 rounds**；只做候选派生（`_maybe_advance_goal_round` 保留 flush→derive→置候选，删去轮次推进） |
| driver 轮真正 start | — | `admit_round`：CAS（revision）+ `rounds+1` + 达 cap 置候选；miss → 放弃本轮预约（不消耗编号） |

`_note_round_async` 拆为 `admit_round`（driver 用）与纯候选派生两路径；cap 安全阀
（达 cap 未确认 → `pending_complete`）移入 `admit_round`，用 `goal.max_rounds`。

## 4. RoundDriver 状态机与生命周期

新文件 `python/server/goal_round_driver.py`（模块级单例，照 `get_turn_runner` 范式）。
状态纯内存：`{session_id: DriverState(armed: bool, pending: asyncio.Task | None, round_no: int)}`。

```
disarmed（默认/重启后唯一初始态）
   │  POST …/goal/round-driver {action:"arm", max_rounds?}
   ▼
armed-idle ──settlement(final="succeeded")──▶ 复检①②③④ ──▶ 预约 create_task ─▶ queued
   ▲                                                                        │
   │                                                              start 成功：admit_round CAS
   │                                                              失败(409/miss)：预约作废
   │                                                                        ▼
   └──disarm / app shutdown──◀────────────────────────────────── running（普通 detached turn）
                                                                            │
                                                       settlement：succeeded → 回 armed-idle 复检
                                                                   failed → goal blocked + disarm
                                                                   stopped(user_stop) → disarm
```

复检条件（全满足才预约）：① armed；② goal active 且非 pending_complete；
③ `rounds < max_rounds`；④ 会话无活 turn（`TurnRunner.is_running`）且无在途预约。
预约与 start 之间加固定短防抖（默认 2s，让 GUI 渲染终态、给人类消息留让位窗口）。

- **让位**：chat.py 主端点在 busy 闸（is_running / `pool.try_begin`）**之前**调
  `driver.yield_to_human(sid)`——取消在途预约任务再放行；人类 turn 结束后的
  settlement 自然重新预约（对齐 DSH「让位直到 idle 后重排」）。
- **flush 义务**：settlement 运行在 producer finally（终态写入 + `pool.end`）之后，
  引擎侧转录落盘与 turn snapshot 持久化均已完成——XEYO 无需额外 flush 步骤，顺序即保证。
- **teardown**：app lifespan shutdown → 全量 cancel 预约任务 + 清 armed（不写 goal）。

## 5. 触发点接线（只注册，不改调用循环）

| # | 触发点 | 位置 | 动作 |
|---|--------|------|------|
| 1 | settlement | `turn_runner._run_producer` finally 末尾新增**可空回调槽**（engine 不 import server，server 启动时注册 driver.on_turn_settled） | driver 检查点：复检→预约；failed → blocked 补记账；user_stop → disarm |
| 2 | blocked 补记账 | 同 #1 failed 分支 | `transition(goal_id, "blocked", revision)`，补上 38 号触发点 #2 欠账 |
| 3 | 让位 | `chat.py` POST /chat busy 闸前 | `driver.yield_to_human(sid)` |
| 4 | arm/disarm | `server/routers/goals.py` 新端点 | 内存态切换；arm 可带 `max_rounds`（对 goal 做 CAS edit） |
| 5 | blocked 恢复 | `chat.py` resume-cue 分支 | blocked → active（补上 38 号触发点 #4 欠账）；是否顺手 re-arm **不自动**，由用户显式操作 |
| 6 | driver 轮发起 | driver → ASGI 自调用 POST /chat | 复用整条 submit 管线（config 解析 / T_now contextvar / 权限 ASK / 持久化 / SSE），带标记头 `X-Xeyo-Goal-Round: <goal_id>@<round_no>` |

全路径 try/except 降级：driver 任何异常只记日志，绝不影响 turn 与人类请求。

## 6. Round prompt 形态

- 合成消息文本为「继续」——命中现有 `_is_multi_agent_resume_cue` → 走结构化续跑分支，
  GUI 气泡显示「继续」（与现 resume cue 行为一致）。
- `_build_enriched_resume_prompt` 增加 `round_info: tuple[int, int] | None` 参数，输出行：
  `Goal round: N/max (auto-continuation)`，并追加两行指令：完成判断须以工作区/工具结果
  为证据；未完成保持目标 active（对齐 DSH `<goal_round>` 的权威声明与证据要求）。
- **不新增 T_now 块**：round 信息是每轮一次性内容（随 submit 注入），不属易变投影；
  blocked / pending_complete 的 T_now Goal 块继续按 38 号 §8 工作，两者正交。
- 用户可发的普通「继续」与 driver 的「继续」在引擎侧不可区分——**无需区分**：
  driver 的权威性来自预约与 admit_round 的 CAS，而非消息文本。

## 7. 并发与崩溃恢复

| 场景 | 机制 |
|------|------|
| 同会话串行 | TurnRunner 每会话至多一 turn + driver 每会话至多一个预约任务，天然串行 |
| 预约→start 竞争 | start 走 POST /chat 全闸（is_running / lease / 409）；409 或 `admit_round` CAS miss → 预约作废，编号不消耗 |
| 人类让位 | §5 #3；人类 turn 结束后重新预约 |
| 进程重启 | armed 与预约皆内存态 → 自动静止；goal（含 rounds/revision/max_rounds）落盘保留；用户显式恢复（§5 #5 + 重新 arm）——与 DSH「重启只恢复目标、不恢复自动续跑」一致，**零额外成本** |
| 跨进程 | GoalStore 既有 asyncio 锁 + WorkspaceLock + CAS 已覆盖；XEYO 部署形态单 server，多进程共写同一 goal 时 CAS miss 方放弃即可 |
| 崩溃残留 | 崩溃发生在任意时刻：磁盘上只有 goal 实体，无 driver 残留状态可清理（内存态方案在恢复语义上反而优于事件溯源预约日志） |

## 8. API（additive）

- `POST /v1/sessions/{sid}/goal/round-driver`，body `{action: "arm"|"disarm", max_rounds?: int}`：
  - arm：可选 `max_rounds` 先对 goal 做 CAS edit（miss → 409 附当前 goal），再置内存 armed。
  - disarm：清内存 armed + 取消在途预约；不改 goal 落盘状态。
  - 挂 `require_loopback`（同 goals router 现有门禁）。
- `GET /v1/sessions/{sid}/goal` 响应 additive：
  `max_rounds` + `driver: {activation: "armed"|"disarmed", pending: bool, round: int} | null`。
- `PATCH …/goal` 增加 `action: "edit"`（objective / max_rounds，带 revision CAS）——DSH edit 动词对齐。
- SSE 新 xy 帧 `{type: "goal", goal: {...}, driver: {...}}`：**whole-value 快照**（DSH 投影纪律），
  发射点：PATCH 各动作、arm/disarm、admit_round、settlement blocked 化、round 起止。
  前端以此为准，GET 只做会话切换/断线重连播种。

## 9. GUI（对齐 dsh-client-ui-goal，融入 XEYO 主题）

### 9.1 位置与渲染规则

- 新组件 `gui/src/components/SessionGoalDock.tsx`，置于 Composer 统一外框内
  `SessionTodoDock` 之后（对齐 DSH dock order：Todo 后），复用 `DockPresence` + 卡片样式
  （与 TodoList 同体系：圆角面板、主题 token、smoothness 动画）。
- 渲染规则照抄 DSH：加载中 / 无 goal / completed / abandoned **不渲染**；
  active / blocked / pending_complete 渲染。提供 `useSessionGoalDockLive()` 供外框统一收口。

### 9.2 功能清单（DSH 四动词面 + XEYO 补充）

| 状态 | 展示 | 动作 |
|------|------|------|
| active + disarmed | 圆点灰色 + 阶段标签「进行中」+ 截断 objective | 「自动续跑」(arm)；P1：edit（行内表单改 objective / 轮次上限）、drop |
| active + armed（idle） | 圆点蓝色呼吸 | 「停止续跑」(disarm)；P1：edit / drop |
| active + armed + 轮中 | 圆点绿色 + 「自动续跑 · 第 N/M 轮」 | 「停止」= 现有 Stop（interrupt）→ settlement 自动 disarm |
| pending_complete | 绿描边 + 「待确认完成」 | 「标记完成」(confirm_complete) / 「继续此目标」(continue) ——38 号 §9 候选条并入本 dock |
| blocked | 琥珀 + 「已阻塞」+ reason（截断，title 悬浮全文） | 「恢复」(reopen)；恢复后仍需显式 arm |

动词调用纪律（对齐 DSH）：每次调用从 store 读 `{goal_id, revision}` 作 CAS ref；
409 时用响应附带的当前 goal 刷新重试一次；**single-flight 防护**（React pending 挡不住
同帧双击）；clear/drop 成功后乐观抑制显示直至权威投影到达。

### 9.3 数据通道

- `chatStore` 增 `sessionGoalById: Record<sid, GoalProjection>` 切片（照 `sessionTodosById` 范式）。
- 播种：会话切换 / 断线重连时 `GET /v1/sessions/{sid}/goal`；live：SSE xy `goal` 帧
  whole-value 直写 store（streamDrain 处新增分支）。
- `lib/api/` 新增 `goals.ts`：getGoal / patchGoal / roundDriverAction，错误处理照 `permissions.ts`。

### 9.4 对 DSH 的一处有意偏离

DSH GoalBar 的已知限制：投影只含 durable phase，**条带无法区分 armed 与 disarmed**
（activation 是 agent 进程本地，无实时通道）。XEYO 的 server 是唯一权威、SSE 通道现成，
故投影直接携带 `driver.activation` 与轮中态——这是 §0 口径 5 的「运行中/停止态」来源，
也是本设计相对 DSH 的净改进，非语义漂移。

### 9.5 全局设置（P1）

SettingsModal 增「目标自动续跑」区：全局默认轮次上限（写 `~/.xeyo/config.toml [goal] round_cap`，
照 outputCompact 链路的 server 侧等价物——服务端启动读取，不在请求体传）。

## 10. 兼容与迁移

- 全部字段/端点/帧 additive；`max_rounds` 缺省解析、`driver` 字段可缺省，旧消费者无感。
- 不经 server 的进程内入口（python/cli REPL 直连 `QueryEngine`）没有 TurnRunner settlement，
  **P0 无 driver**——放养式任务是 GUI / server 形态场景，可接受；文档明示。
- 远程通道（iLink 等）：P0 只享有 blocked / 候选的 T_now 投影，arm 需 loopback GUI；
  远程白名单评估延后（与 38 号 §5 远程边界同口径）。

## 11. 切片

| 切片 | 内容 |
|------|------|
| P0 后端 | `server/goal_round_driver.py`（状态机 + settlement 回调 + 让位 + ASGI 自调用）；turn_runner 回调槽；chat.py 让位 + resume-cue blocked→active；goal_state `max_rounds`/`admit_round` + rounds 语义修正；goals.py arm/disarm 端点 + GET 扩展 + PATCH edit；SSE goal 帧；failed→blocked 补记账；测试 |
| P0 GUI | `SessionGoalDock`（显示 + arm/停 + 确认完成/继续）+ chatStore goal 切片 + api/goals.ts + SSE 分支 + 播种；单测 |
| P1 | 行内 edit / drop；SettingsModal 全局 cap；崩溃恢复（turn_snapshot recovery → blocked）接线；GUI 轮次 chip（「第 N/M 轮」）与自动轮气泡来源标识；远程通道边界评估 |
| P2 | goal 轮聚合 USD 预算（driver 预约前查累计）；settlement 通知 / continuable 子代理（对照报告 §10 对齐）；`GET /v1/goals` 注册表列表；mid-turn steering 评估 |

## 12. 测试清单（范式：test_goal_state_t9 / test_goal_api_t9 / test_goal_turn_hook_t9 / test_turn_detach_reattach）

- 状态机：arm→settlement 预约→start→admit_round CAS→轮后复检循环；达 cap → 置候选 → 停；
  disarm 后 settlement 不预约；pending_complete / blocked / abandoned 均不预约。
- 让位：预约后人类消息到达 → 预约任务被取消、人类请求放行；人类轮结束 → 重新预约；
  **人类轮后 rounds 不变**；409 竞争 / CAS miss → 预约作废且编号不消耗。
- 失败链：failed → goal blocked（reason 带 stop_reason）+ disarm；user_stop → disarm 且 goal 仍 active；
  blocked 后 resume cue → active（38 号触发点 #4）。
- 持久化纪律：armed 不落盘——重启后 driver 全静止、goal 实体完好；arm 时 max_rounds CAS 落盘正确。
- API：arm/disarm loopback 门禁；GET additive 字段；PATCH edit / 409 附当前 goal。
- SSE：goal 帧 whole-value、发射点齐全、无 goal 不发帧。
- 降级：driver 异常不影响 turn；无 goal / 无 binding / 坏 goal 文件全 no-op。
- GUI：四状态渲染矩阵；无 goal / completed 不渲染；动词 CAS 与 single-flight；SSE 更新 store。

## 13. 明确不做

- **新调度器 / 后台线程**——driver 只是 settlement 钩子上的内存态回调 + create_task（38 号「复用现有钩子位置」延续）。
- **durable armed / 落盘预约**——内存态是特性不是缺陷：重启必静止，恢复语义零成本。
- **跨会话 / 跨实例驱动**——同会话（DSH 同款）；多实例共写靠 CAS miss 方放弃。
- **轮中抢占人类消息**——让位只发生在轮间；轮中 busy 语义与任何 turn 一致，steering 属 P2 评估。
- **资源预算**——cap 只是轮数；token / USD 预算维持 per-turn 现状（DSH 同口径），聚合预算 P2。
- **瞬时失败自动重试**——失败即 blocked + 等人（冻结口径 3）。
- **模型自主完成判定**——沿用 38 号：模型 P0 无权宣布完成，候选仍需用户确认；
  driver 的 round 指令只要求「完成须给证据」，不授予转换权。
- **goal 进 system / 历史**——round 指令随 submit 注入一次（38 号 §7 口径），T_now 红线不变。

## 14. 开放问题

1. 合成「继续」在时间线上的呈现：P0 与普通用户气泡一致（现 resume cue 行为）；
   是否需要 DSH 式独立来源样式（右对齐等宽 command-input 节点）——P1 按真实使用观感定。
2. `blocked_reason` 结构化（DSH `GoalBlockReason{code,message}`）：P0 直填 stop_reason，
   P1 归一 code 表（budget / permission_denied / provider_error / …）。
3. ASGI 自调用的实现细节：`httpx.AsyncClient(transport=ASGITransport(app))` 复用同一 app 实例，
   需实现时确认不触发 lifespan 二次启动、鉴权头如何内联（loopback 请求头直带）。
4. 防抖窗口（2s）与「连发多轮间的 GUI 呼吸感」是否需要按轮指数退避——先固定值上线，看体验。
