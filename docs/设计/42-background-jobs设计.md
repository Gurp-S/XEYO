# 42 · Background Jobs 设计（后台任务 / 完成通知 / 复用 41 号 settlement 机器）

> 目标：借 DSH `dsh-jobs / jobs-local / tool-jobs / client-ui-jobs` 四件套的语义
> （对照报告 §10、§14），让长命令可以 `run_in_background`——工具立即返回 job id，
> turn 不被阻塞；任务结算后**完成通知作为 LLM 的输入**送达（忙→挂起待领，闲→唤醒新轮），
> 模型凭通知调 `job_output` 收结果继续收尾。GUI 侧 header 角标 + 只读弹层对齐 DSH。
> **与 41 号的关系是本设计的骨架**：settlement 回调槽、idle 唤醒、人类消息让位三件
> 基础设施全部由 41 号铺设，42 号是它的第二个租户（§3）。

## 0. 冻结口径

| # | 决策 | 口径 |
|---|------|------|
| 1 | 生命周期 | job 是**进程内、内存态、per-session（owner）**记录；进程重启即清空（与 41 号 armed 同纪律：重启只留 transcript 卡片，不留可运行状态） |
| 2 | 通知即输入 | 完成通知不是 UI 事件：唯一主动投递通道 = **唤醒轮**（合成 submit，受唤醒预算约束）；被动通道 = 人类下一轮开工时的 T_now 补投（§6） |
| 3 | 唤醒有界 | `maxConsecutiveWakes=3`（per-session）；**goal 轮与 job 唤醒共享同一预算**（防双自激，§3.4）；只有人类撰写输入恢复预算 |
| 4 | 生产方 | P0 只接 `BashTool`（`python/tools/bash_tool/`）的 `run_in_background` 参数；Agent / scheduler workflow 后台化 P1/P2 |
| 5 | 工具目录 | `job_output / job_list / job_kill` 三工具**恒注册**（无任务时空转），schema 不随状态抖动（对照报告 §8 对动态追加目录的 KV 批评，DSH「schema 恒注册」纪律同源） |
| 6 | GUI 只读 | 列表行不做流输出直读、不做人类中断（DSH 同款暂缓）；数据走 SSE xy `jobs` 帧 whole-value 镜像，UI 零 RPC |
| 7 | 权限 | `run_in_background` 不绕过 Bash 既有权限三态（先过判定再入注册表）；`job_output/job_list` 只读、`job_kill` 仅限本会话任务，默认 allow + 日志（开放问题 #1 留 ASK 评估） |

## 1. 背景与现状缺失

- XEYO 工具执行是 **turn 内同步**：一条长回归（分钟级）占住整个 turn，用户只能干等或
  打断；模型也没有「先干别的、回头收结果」的表达能力。
- 会话内没有任何「待领投递」概念：子 agent（`agent_tool/`，one-shot）结果随 turn 返回，
  scheduler 批次在同一 turn 内收口——跨轮的「完成→告知→继续」不存在。
- 对照报告 §10 建议的 settlement 通知、§14 jobs 通知经济学，均落在 41 号铺设的
  settlement 机器上；41 号只服务 goal 轮，本设计把它泛化。

## 2. DSH 语义对照与取舍

| DSH | 本设计 |
|-----|--------|
| `dsh-jobs` 约定：start/get/list/read/kill/wait/onJobDone/onJobsChanged + attachController + scope 分层 | `server/job_registry.py` 简化版：单 server 单组合，**无 scope 分层**（owner 即 session_id，比较即安全边界）；其余语义照抄 |
| `dsh-jobs-local`：`<kind>-N` id、只交快照不交实时状态、首次结果优先结算、`maxConcurrentJobsPerOwner=10`、容量满 start 前失败并教模型 kill | 同款全抄 |
| `dsh-tool-jobs`：三工具 + 完成通知 + 忙注入/闲唤醒 + maxConsecutiveWakes + kill/read 标记已报告 | 忙注入改形（§6：XEYO 无 mid-turn inbox，busy 结算挂 pending 队列、turn settlement 时合并唤醒）；其余同款 |
| 通知文本 `background job <id> (<kind>: <label>) finished [status: ...]. Read its output with job_output.` | 原样 |
| `dsh-tool-bash`：`run_in_background` spawn 前预检 `ctx.jobs.start()`，ShellProcess 句柄适配取消/完成/增量输出三钩子，立即返回不适用超时 | `BashTool` 同构改造（§5）；无 pwsh 工具，单生产方 |
| `dsh-client-ui-jobs`：header 触发器+角标（零隐藏）、确定性排序、detail 取代状态词、耗时每秒/冻结、终态弱化保留 | `ChatHeader` + 弹层同款；数据通道换 XEYO SSE xy 帧（§8） |
| 系统提示词「后台任务指引」固定区段 | `prompt/system_prompt.py` 左段固定区段（工具策略类指令，非易变投影，不走 T_now） |

## 3. 与 41 号的依赖关系（本设计的骨架）

### 3.1 复用件一：settlement 回调槽 → TurnSettlementHub

41 号在 `turn_runner._run_producer` finally 末尾加的是**单个可空回调槽**（engine 不 import
server）。42 号需要同一位置做 job 结算投递——**槽升级为 hub**：

```
turn_runner finally ──单回调──▶ server/turn_settlement_hub.py（启动时注册进槽）
                                    ├─→ GoalRoundDriver.on_turn_settled   （41 号检查点）
                                    └─→ JobRegistry.drain_settled(sid)    （42 号投递决策）
```

turn_runner 仍只认识一个回调；41/42 各自独立注册进 hub，互不感知。**排序依赖：
hub 由 41 号 P0 建立，42 号只加第二个分发目标，不改 engine。**

### 3.2 复用件二：idle 唤醒机器 → 通用合成轮通道

41 号的「armed-idle → 复检 → ASGI 自调用 POST /chat」是一条**通用合成轮通道**，
42 号直接复用，只换载荷：

| | goal 轮（41） | job 唤醒轮（42） |
|---|---|---|
| 触发 | settlement 复检 goal | settlement 发现未领取完成通知 |
| 载荷 | 「继续」+ enriched resume（round N/max） | 通知短文本（§6 文案） |
| 记账 | `admit_round` CAS、消耗 goal cap | 无 goal 记账；消耗**共享唤醒预算** |
| 让位/409/防抖 | 同一套：人类消息取消 pending、竞争作废不消耗、2s 防抖 | 同左 |

### 3.3 复用件三：让位语义

41 号 chat.py 入口的 `yield_to_human(sid)`（取消在途 goal 预约）泛化为**取消全部
pending 合成轮**（goal 预约 + job 唤醒）。人类消息优先级在两个租户之上，一处实现。

### 3.4 互激防护（两租户共享一个预算）

存在合法链：goal 轮里启动后台 job → job 完成唤醒新轮 → 该轮 settlement 又触发 goal
复检 → 再开 goal 轮……每条边都各自「合理」，合起来是自激。约束：**goal 复检唤醒与
job 唤醒共享 per-session `wakes_remaining=3`**，任何一方的自产出都不恢复预算，只有
人类输入恢复。超界后一切降级为「pending 待领 + T_now 补投」，等待人类。goal 自身的
`max_rounds` cap 独立生效（轮数上限 ≠ 唤醒上限，两道闸）。

## 4. 注册表（`server/job_registry.py`）

```python
@dataclass
class JobRecord:
    job_id: str            # "<kind>-N"，如 bash-3
    kind: str              # "bash" / "agent" / …（生产方自报）
    label: str             # 短描述（命令首行截断等）
    status: str            # running / stopping / succeeded / failed / killed
    detail: str = ""       # 失败原因 / 终态摘要；GUI 有 detail 则取代状态词
    owner_session_id: str  # owner 隔离：list/read/kill 比对 caller
    reported: bool = False # 通知已投递位（kill / 终态 read / 唤醒消费 均置位）
    output_ring: ...       # 环缓冲（cap bytes，保尾）；job_output 单游标消费
    started_at / finished_at: float
```

- `start(spec)`：先过 owner 容量（running+stopping ≤ 10，满则在**生产方执行前**失败，
  错误文案教模型 `job_kill` 腾位）→ 签发 id → 注册 running。不排队、不抢占。
- `read(id, caller)`：流任务消费唯一游标（增量），终态任务幂等读终止输出；读已终止
  任务置 `reported`。
- `kill(id, caller, reason)`：先请求生产方取消（取消抛异常则任务保持 running）→
  置 stopping + 标记已报告；终止快照非消费式。
- 结算**首次结果优先**：生产方 done / 取消异常隔离为 failed / 服务销毁强制失败，
  只记一次；监听器逐个隔离异常。结算顺序：记录提交 → 可见集变更广播 → 通知投递
  （投递方可能同步开轮，其他观察者必须已看到终态）。
- `on_done` / `on_changed` 监听：hub 与 SSE 广播各挂一个；异常隔离、不等待。

## 5. 生产方接线（P0：BashTool）

- schema additive：`run_in_background: bool`（**恒注册**，冻结口径 5）；执行路径：
  先走 Bash 既有权限判定 → 再 `registry.start()` 预检（满则本调用失败，权限已花不退）
  → spawn，句柄适配三钩子：取消（terminate 进程树）、完成（退出码/信号 → status/detail）、
  增量输出（stdout/stderr → ring，cap 保尾，UTF-8 边界）。
- 返回：`started background job <id> (<kind>: <label>)` + 提示「完成会自动通知，
  可用 job_output 读取」；**不适用超时**（后台语义）。
- 前台行为与现有完全一致（未带参数零差异）。
- 输出经济：P0 ring cap 保尾（借 12 号 spill 的常数纪律）；P1 超限完整文本落
  `tools/spill.py` 已有 saveText，ring 里留 `full output: <path>` 指针。

## 6. 通知管线（核心）

结算后 `hub → JobRegistry.drain_settled(sid)` 对每个 `reported=False` 的完成任务：

1. **owner turn 活着**（`TurnRunner.is_running`）→ 挂 per-session pending 队列；
   turn settlement 时 hub 把 pending 并入决策（多 job 同 settle **只花一个唤醒轮**）。
2. **owner 空闲**且 `wakes_remaining > 0` → 唤醒轮：合成 submit，user_text = 通知文本
   （多条合并为一个 digest 块）：
   `background job bash-3 (bash: 全量回归) finished [status: succeeded]. Read its output with job_output.`
   消费即置 `reported`；`wakes_remaining -= 1`。
3. **预算耗尽 / `completionDelivery: quiet`** → 通知留在 pending，等人类下一轮：
   submit 入口把 pending 摘要 set 进 contextvar，`pre_llm_inject` 输出
   `# Background jobs（background only）` 补投块（列 id/kind/status/detail + job_output
   指引），**注入后立即出队**（一次性消费，照 agent_mode contextvar 进出范式）。
   该块挂在 `_trim_blocks_to_budget` **之后**：被预算挤掉 = 通知永久丢失，语义与
   「开了必须生效」强挂类同构（T_now 红线三条均满足：一次性、非 system 权威、不入历史）。
4. 抑制重复：kill / 终态 read / 唤醒消费，任何一条路径置 `reported` 后不再投递。

唤醒轮自身是普通 turn：有 goal binding 且 armed → settlement 照常复检 goal（合法链，
§3.4 双闸管住）；无 goal → 纯收尾轮。

## 7. 模型工具面（三工具恒注册）

| 工具 | 行为 | 渲染 |
|------|------|------|
| `job_output(job_id, wait?, timeout_ms?)` | 默认非阻塞读增量；`wait:true` 上限 30s 默认 / 600s 硬顶，超时任务保持存活；响应尾标 `[status: ...]` | read 卡 |
| `job_list()` | `<id> [<kind>] <status> — <label>` 快照列表；空回 `(no background jobs)` | read 卡 |
| `job_kill(job_id, reason?)` | 立即请求取消并转发 reason；返回 `requested cancellation of job <id>` 或既有终态 | execute 卡 |

三工具仅作用 caller 自会话任务；schema 恒在（无任务空转），保 KV 前缀稳定。
系统提示词左段固定区段（原文对齐 DSH：不 busy-poll、不重复别人的活、终答前
`job_output` 收仍然相关的任务、kill 掉不再重要的）。

## 8. GUI（对齐 dsh-client-ui-jobs，XEYO 主题）

- 数据：SSE xy 帧 `{type:"jobs", jobs:[JobSnapshot...]}` whole-value per session；
  发射点 = start / stopping / settle / owner 清空。chatStore 增
  `sessionJobsById: Record<sid, JobSnapshot[]>`，**last-wins，空集 = 删除键**
  （缺失与 `[]` 同一表示，消费方永不测哨兵）；会话切换/重连时 GET 播种
  （`GET /v1/sessions/{sid}/jobs` additive）。
- 入口：`ChatHeader` 触发器 + 角标（running+stopping 计数，**为零整个隐藏**）；
  会话无任务不长控件。
- 弹层：活跃行前（startedAt 升序）、终态行后（finishedAt 降序）、并列按启动序
  （渲染确定性，map 序永不参与）；行 = kind / label / detail（有则取代状态词）/
  状态标记 / 耗时（活跃每秒推进、finishedAt 冻结，时钟只在有活物时运行）；
  终态行弱化保留至被清。样式走 XEYO dock 卡片 token（与 41 号 GoalDock 同体系）。
- 会话流：`run_in_background` ack 渲染 generic 卡（对齐 DSH 后台呈现）；
  job_output/job_list/job_kill 走 read/execute 卡。

## 9. 并发与恢复

| 场景 | 机制 |
|------|------|
| job 与 turn 并行 | 这就是特性；互斥只发生在合成轮之间（同一通道天然串行 + 409 作废） |
| 唤醒 vs 人类 | 让位（§3.3）；人类 turn 结束后 hub 重新决策唤醒 |
| 唤醒 vs goal 轮 | 共享唤醒预算（§3.4）；goal cap 独立 |
| 进程重启 | 内存记录清空；transcript 里 run_in_background 卡仍在而列表空（DSH 同款限制，接受）；armed/唤醒预算均不持久 → 重启静止 |
| 崩溃残留 | 无（内存态；子进程随 server 死亡由 OS 收割，P1 可加 job 树孤儿检测日志） |

## 10. 兼容与迁移

- 全部 additive：Bash schema、xy 帧类型、GET jobs、三工具。未带 `run_in_background`
  的调用行为逐字节不变。
- 三工具恒注册的代价是每次请求固定少量 schema token（DSH 同款并自知）——换取
  KV 前缀稳定，避免「有 job 才出现」的目录抖动。
- T_now 候选清单追加 `Background jobs（background only）`（查重：与 peer presence /
  proposals digest 同族但语义为一次性待领投递，注入即出队，非每轮常驻）。

## 11. 切片

| 切片 | 内容 |
|------|------|
| P0 后端 | `server/job_registry.py`；hub 落地（41 号槽升级双分发）；BashTool `run_in_background` + ring 输出；三工具恒注册 + 左段指引区段；唤醒轮（复用 41 通道）+ 共享唤醒预算 + T_now 补投块；SSE jobs 帧 + GET jobs；测试 |
| P0 GUI | ChatHeader 触发器/角标/弹层；chatStore jobs 镜像 + SSE 分支 + 播种；generic/read/execute 卡渲染；单测 |
| P1 | job 输出超限落 spill（§5）；AgentTool 后台化（one-shot 返回 jobId，复用同一注册表与通知）；cli-ts 只读展示；kill 是否 ASK 回看 |
| P2 | scheduler workflow 后台批次（与既有 resume cue 关系评估，可能免做）；continuable 子代理（对照报告 §10 对齐）；跨进程持久后端；输出直读第二通道 |

## 12. 测试清单（范式：test_goal_turn_hook_t9 / test_turn_detach_reattach / test_concurrency_gates）

- 注册表：owner 隔离（跨会话 list/read/kill 拒）；容量 10 满 → start 前失败且文案带
  job_kill；首次结算优先（done 与取消竞态只记一次）；快照非实时（读到的是拷贝）。
- 生产方：run_in_background 立即返回、不适用超时；权限拒绝不产生 job；后台完成
  status/detail 正确；ring cap 保尾 + UTF-8 边界；kill 停进程树。
- 通知：忙结算 → pending 合并 → 单唤醒轮（两 job 一次投递）；唤醒轮消费置 reported；
  kill / 终态 read 抑制；预算 3 耗尽 → 降级 pending + 人类下一轮 T_now 补投且注入即出队。
- 互激（§3.4）：goal 轮→job→唤醒→goal 复检链，共享预算 3 次后全降级；人类消息
  恢复预算；唤醒轮不消耗 goal rounds；goal cap 独立生效。
- 让位：pending 唤醒遇人类消息被取消且不消耗预算；409 竞争作废。
- 恒注册：无任务时三工具 schema 在、job_list 空句；T_now 补投块仅在有 pending 时出现。
- GUI：角标零隐藏、排序确定性、detail 取代状态词、耗时冻结、空集缺键、SSE whole-value。
- 降级：registry/hub 任意异常不影响 turn 与人类请求（全 try/except + log）。

## 13. 明确不做

- **跨重启 / 跨进程 job**——内存态是纪律不是缺陷（与 41 号 armed 同哲学）；持久后端需先重塑身份/所有权语义，P2 评估。
- **GUI 直读流输出 / 人类中断行**——单游标限制对齐 DSH；中断牵涉 `reported` 位语义（模型会以为任务还在跑），DSH 也暂缓。
- **前台转后台**——启动时定死。
- **job 独立 token/USD 预算**——唤醒轮本身是普通 turn，走既有 per-turn 预算；轮数上限与唤醒上限两道闸已够。
- **强通知/抢占**——通知永不打断人类消息、永不杀 turn；inbox 非空不许关 turn 的 DSH 语义在 XEYO 无对应物，等价约束由「人类优先 + 预算」承担。
- **per-kind 定制卡**——三工具共用通用卡（DSH 同款）。

## 14. 开放问题

1. `job_kill` 是否走 ASK：默认 allow 的理由是作用面仅限本会话自建任务；若 P1 AgentTool
   后台化引入更强副作用面，回看。
2. T_now 补投块的强挂位（`_trim` 之后）是对「一次性待领信息」的破例——上线后验证
   与开关类强挂的共存次序。
3. ring cap 常数与 `job_output` 分页（对照 12 号 spill 纪律定）。
4. scheduler workflow 是否需要后台化：DAG 批次已有 checkpoint + resume cue「继续」，
   可能与后台 job 语义重复——P2 先评估再决定，避免两套跨轮续跑。
5. 唤醒轮提示词是否需要区分「这是通知轮，不是新任务」（防弱模型把通知当新指令发挥）——
   参照 41 号 round prompt 的权威声明行，倾向加一行归属声明。
