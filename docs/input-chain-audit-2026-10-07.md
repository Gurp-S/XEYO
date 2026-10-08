# Agent 输入链审计（2026-10-07）

基线：`e091434`。范围：GUI 输入框 → HTTP/SSE → inbox/steer → 自动投递 → 转录/本地持久化，以及 Goal、Ink TUI、进程内 Python CLI。下文保留基线事故证据，末尾记录已实施修复和当前验证；基线位置不是修改后行号。已修改产品代码，未 commit/push，未调用付费模型。直接完成，未使用子代理。

## 结论与用户报告的症状

已复现消息乱序和重复；排队卡不消失找到独立的边界投递回执缺陷。常规“排队成功、最终收到回复”的测试全绿，无法证明完整交接正确。

| 编号 | 优先级 | 确认问题 | 证据 |
| --- | --- | --- | --- |
| F01 | P1 | 单条排队改引导，会删除其他 queued 项 | 后端探针 + 真实浏览器/后端 |
| F02 | P1 | 自动投递后用户气泡跑到上一轮回复前；刷新再乱序 | 默认合并与关闭合并两组 E2E |
| F03 | P1 | 队列转录回填与原流收尾交错，前端重复上一轮回复 | 普通逐条队列、改引导兜底两组真实 E2E |
| F04 | P1 | 排队改引导在采样边界送达后，回执永久 delivering | 真实路由、边界投递与 settlement 组件探针 |
| F05 | P1 | GUI 自动投递轮已执行，前端却空闲，无回复流和停止按钮 | 真实浏览器/后端对照 |
| F06 | P1 | TUI 排队受理后不订阅投递轮，也不同步回复 | 实际 Ink App + 离线 HTTP 替身 |
| F07 | P1 | 未成功发送就清掉待回答 Ask/Plan | 实际 GUI store 探针 |
| F08 | P1 | TUI 排队发送失败，把新草稿覆盖成旧消息 | 实际 Ink App + 延迟失败 |
| F09 | P1 | 刷新后 Goal 后端仍在，前端无卡片、无读取请求 | 真实浏览器/后端 |
| F10 | P2 | 迟到的 Goal 轮询覆盖更新的暂停/编辑结果 | 实际 React hook + 请求时序探针 |
| F11 | P1 | 旧目标编辑请求可以修改已替换的新目标 | 真实 ASGI HTTP PATCH |
| F12 | P2 | 回溯分支 Goal 使用 GUI id，请求错后端会话 | 实际 React hook + 分支状态探针 |
| F13 | P2 | SSE 重连路径丢弃 goal/jobs 事件 | 实际 SSE 解析入口探针 |
| F14 | P2 | 非空、格式错误的 Goal 200 响应被当成无目标 | 实际 API 解码探针 |
| F15 | P2 | 归档只读只在 GUI 限制，Goal HTTP 写入仍成功 | 真实 ASGI HTTP PATCH |
| F16 | P1 | CLI `/approval` 下一轮恢复为启动时模式 | 实际 CLI 编排 + 引擎替身 |
| F17 | P2 | CLI `/model` 意外新建会话，原历史不沿用 | 实际 CLI 编排 + 引擎替身 |
| F18 | P1 | CLI/TUI 清空会话后 `/retry` 重发旧会话任务 | 两个入口均复现 |

还有两项已确认行为、需明确产品契约：D01 停止后的队列会被 GET 快照重新启动；D02 排队消息采用最近请求的模型/审批环境，而非入队时环境。它们不混入上述 18 项缺陷计数。

## 排队、消息与流：根因和回归规则

### F01 单条取件破坏整个队列

位置：`python/server/inbox_registry.py:438`、`:463`；调用点 `python/server/routers/sessions.py:1912`。

`consume_for_boundary(queue_id=B)` 先把 active 筛成 B，重建剩余队列却只保留 `state != queued`。A/C 虽未选中仍被删掉，持久化也写入这个结果。引导拒绝后恢复 B 同样救不回 A/C。真实浏览器现场：后端仅剩 B；前端 A/C 气泡仍留着，看起来像已经送出，服务端转录却没有它们。

结构规则：仅从原队列减去真正取出的 queue_id；未选中消息的内容、状态、顺序和落盘结果保持一致。回归：A/B/C 选择 B，分别覆盖引导成功、队列满拒绝、落盘失败和重启；A/C 均存在。

### F02 接收回执后仍保留错误落位，刷新使用另一套顺序

位置：`gui/src/stores/chat/inboxSlice.ts:77`、`:294`、`:306`，`gui/src/stores/chat/streamDrain.ts:130`、`gui/src/stores/chat/streamSendSlice.ts:1378`，`gui/src/lib/db.ts:512`，`gui/src/stores/chat/streamHelpers.ts:317`。

真实输入时先形成 `[原问题, 排队气泡, 原回复]`。投递回执到来，按 id 替换锚点保持原位置，同时清掉 queueState；后续“释放排队气泡”逻辑无法再识别这个锚点，中间出现 `[原问题, 排队问题, 原回复, 排队回复]`。流收尾仍按当前数组末尾追加原回合正文，最终稳定状态还能变成 `[原问题, 排队问题, 排队回复, 原回复]`。既有 `inboxDeliveryOrder.test.ts:138` 从已经正确的 `[原问题, 原回复, 排队问题]` 开始，遗漏关键交接和慢收尾。

刷新又从 IDB 按 createdAt 排序，本地回复时间与服务端转录时间混用；同长度且工具数相同的转录不触发服务端回填，不能修正顺序。在流收尾前刷新曾观察到两条回复换位；最终版本探针等待收尾结束，再刷新，默认合并的 `[原问题, 合并排队问题, 排队回复, 原回复]` 仍保留。关闭合并后也乱序。

结构规则：排队只是待执行信息，执行后的转录位置来自权威 turn/转录顺序；显示、存盘、回读使用同一顺序依据。回归必须从真实的入队位置开始，并比较回执后、流收尾后、刷新后的完整 role/text 序列；不能只检查 marker 出现或卡片数量归零。

### F03 本地流收尾与服务端回填生成多份同一回复

位置：`gui/src/stores/chat/inboxSlice.ts:277`、`:298`，`gui/src/stores/chat/streamDrain.ts:130`，`gui/src/stores/chat/streamSendSlice.ts:1378`，`gui/src/stores/chat/streamHelpers.ts:353`。

排队 B 改引导，WAL 先把 B 写入转录；当前回合没有下一采样边界时走 settle 兜底。同步 B 的服务端尾部因此包含原回合回复。服务端回复 id 与本地 prose id 不同；按 id 合并不能认出同一回合的同一输出。原流的打字机收尾又追加本地回复，只比较末行同文也识别不了中间的服务端回复。最终探针等待原流和排水完全结束，记录服务端原回复 1 条，前端 3 条；刷新后仍为 3 条（最终前端 8 行、服务端 4 行，前端额外保留被 F01 丢失的 A/C）。

普通逐条队列（关闭合并）也复现了两条原回合回复：服务端共 8 行，前端 9 行，刷新后仍 9 行。此路径不需要“改引导”；队列回复插到末尾后，原流 drain 的正文预落行和最终 commit 的末行同文检查同样失去对应关系。因此既要协调服务端/本地身份，也要固定同一原流在 drain 与 commit 的输出身份。

结构规则：使用 turn/输出身份协调回填与流收尾，同一输出只对应一条正文；不能用全文相同去全局去重，因为用户可以合法重复提问。回归：队列改引导、settle 兜底、慢打字机收尾三者交错，比较服务端与前端并刷新回读。

### F04 边界引导成功却没有完成 inbox 回执

位置：`python/server/routers/sessions.py:1912`、`python/engine/query_loop.py:1023`、`python/server/inbox_registry.py:537`、`:553`，前端 `gui/src/stores/chat/streamSendSlice.ts:1652`。

单条 steer 路由把 inbox 项变为 inflight 后交给 t_now_steer。普通 inbox 边界投递会调用 `_finish_delivering`；单条 steer 路由没有对应接线。直接引导已在边界进入模型输入，但原回合 settlement 的 user_message_id 是原问题 id，匹配不到这个引导 id。结果仍为 delivering，ack 接口只接受 completed 项，删除数为 0。前端 SSE 临时撤卡后又立即轮询，后端 delivering 快照会把卡加回来。

结构规则：消息成功落到边界与其 inbox 所有权释放必须成对；无论来自普通 inbox 还是“改引导”，回执生命周期一致。回归：单条改引导 → 真边界 deliver → 原回合 settle → 两次轮询，卡片不再出现且不重复投递。本次复现覆盖实际组件调用，未使用付费模型制造工具多轮。

### F05/F06 自动投递没有客户端交接订阅

GUI 位置：`gui/src/stores/chat/inboxSlice.ts:250`、`gui/src/components/Composer.tsx:476`、`gui/src/pages/ChatPage.tsx:157`；TUI：`tui/src/app/App.tsx:479`、`:749`。

GUI 轮询 inbox，但只在 delivered/syncing 时同步转录，收到 delivering 时没有转交到新 turn 的 SSE。原流结束就清掉本地忙碌状态，新轮已在后端 detached 执行；E2E 现场 task.busy=true，而前端 live=false、停止按钮不可见、排队回复尚未出现。TUI 202 后更没有 inbox/turn/message 读取，等过健康轮询周期仍没有后续回复。

结构规则：被接受的任务由服务端 turn 身份驱动客户端忙碌、订阅和完成状态，覆盖自动投递与其他入口启动。回归：原 turn 结束、新 turn 仍运行时断言实时正文、忙碌、停止动作和最终转录；同时覆盖页面保持前台、切会话、断线重连和 TUI。

## 输入框与确认面板

### F07 发送校验前就销毁 Ask/Plan

位置：`gui/src/stores/chat/streamSendSlice.ts:163`。

清 pendingAsk/pendingPlan 发生在 Key、会话、归档校验之前，也在繁忙排队分支之前。空 Key 拒绝发送、没有任何网络请求，两个待回答面板仍变成 null；后端待回答请求没有同时解决。既有测试还把这一现象当成期望。

结构规则：被拒绝的发送不改变未完成确认；入队不等于解决当前待回答请求。回归：校验拒绝、归档拒绝、网络失败、忙时排队，以及后端仍等待回复的场景。

### F08 失败回填没有保护新草稿

位置：`tui/src/app/App.tsx:509`。

busy 提交先清输入框，失败后直接 `setInput(text)`。用户在请求期间输入的新草稿被旧提交覆盖。实际 Ink 键盘探针：延迟 HTTP 500，`new unsent draft` 丢失，旧排队消息回填。

结构规则：恢复草稿只允许针对发起提交时的草稿版本；新输入必须保留，失败原文另有可恢复位置。回归：提交旧草稿 → 用户输入新草稿 → 旧请求失败，验证两份文本均可恢复。

### F18 Retry 状态没有跟随会话身份

位置：`tui/src/app/App.tsx:124`、`:531`、`:550`、`:602`，`python/cli/chat_cmd.py:181`、`:243`、`:260`。

CLI 的 last_prompt 和 TUI 的 lastUserRef 跨清空/加载保留。旧任务 → `/clear` → `/retry`，两个入口都把旧任务发送到新会话。加载会话也缺少重置或按目标历史重建，但本次动态证据针对 clear。

结构规则：重试来源与会话绑定，切会话必须清空或根据目标转录恢复。回归：A 发任务 → clear/load B → retry，不得把 A 的输入发给 B。

## Goal 全链路

### F09 数据存在才挂载读取器，刷新无法发现已有目标

位置：`gui/src/components/Composer.tsx:1928`，`gui/src/components/SessionGoalDock.tsx:52`、`:137`。

轮询只在 SessionGoalDock 内部运行；Dock 又只有 sessionGoalById 中已有活目标才挂载。刷新后 store 没有目标，于是读取器也没有。E2E `/goal` 创建后卡片可见，刷新后服务端仍 active，前端 goals={}，3.5 秒内没有任何浏览器 GET /goal。

结构规则：发现/读取目标的生命周期由当前会话驱动，与目标卡片是否可见无关。回归：创建 → 刷新、选择已有目标会话、其他客户端创建，均能发现目标；不可恢复已结束目标为活目标。

### F10/F12 Goal 更新缺少版本和会话映射

位置：`gui/src/components/SessionGoalDock.tsx:63`、`:70`、`:192`，`gui/src/lib/goalSync.ts:13`。

迟到 GET rev1 active 可以覆盖 mutation rev2 paused；inflight 只挡轮询互相重叠，没有协调轮询、SSE、命令和 PATCH。另一个问题是 Dock GET/PATCH 使用 GUI activeId，而聊天和 /goal 命令在回溯后使用 activeBranch.backendSessionId。探针确认聊天定位 branch-backend，目标读取却请求 s1。

结构规则：使用后端会话身份请求、GUI 身份存投影，并以目标身份、revision 和请求世代处理全部更新源。回归：延迟旧 GET、暂停/编辑成功后释放旧响应；切换分支期间释放旧请求；请求地址与聊天实际 backend id 一致。

### F11 CAS 只校验 revision，未校验目标身份

位置：`python/server/routers/goals.py:94`、`:132`，`gui/src/components/SessionGoalDock.tsx:95`。

PATCH 不带 goal_id，而是读会话当时绑定的目标。旧目标与替换目标都可能 revision=1；持有旧目标 revision 的编辑请求返回 200，并改写新目标。GUI 本地关闭旧编辑器不能防止另一客户端或在途请求。409 自动重试也必须受目标身份限制。

结构规则：修改条件同时包含 backend session、goal_id、revision；身份变化不能自动把旧编辑意图转嫁给新目标。回归：旧目标 rev1 → 替换目标 rev1 → 旧 PATCH，应冲突且新目标不变。

### F13/F14 重连与解码掩盖目标状态

位置：`gui/src/lib/api/chatStream.ts:508` 对照首次连接 `:382`/`:392`，`gui/src/stores/chat/streamRecoverySlice.ts:653`；`gui/src/lib/api/goals.ts:113`。

streamTurnEvents 未处理 goal/jobs，重连消费者也未接这两个回调。有效事件流包含二者和 DONE，完成回调触发但两个状态回调从未触发。Goal GET 200 `{unexpected:"schema"}` 则返回 ok=true、goal=null；上层会清掉现有卡片，并失去读取器。

结构规则：首次 SSE 与重连采用相同事件契约；仅符合“明确无目标”契约的空响应可以清状态，非空坏数据属于读取失败。回归：同一事件序列分别首连和重连，状态相同；坏响应保留最近有效目标。

### F15 后端没有执行归档只读

位置：`python/server/routers/goals.py:109`；前端防线在 `gui/src/components/SessionGoalDock.tsx`。

实际归档后 PATCH edit 仍 200 且文字持久化。此项不是既有“归档时一帧交接差异”，而是明确写入成功。

结构规则：归档写入限制在后端执行层统一检查，不依赖单个客户端隐藏按钮。回归：归档后所有 Goal 修改入口拒绝，恢复后正常；本次动态验证仅覆盖 Goal edit，不声称已动态验证所有写接口。

## Python CLI

F16：`python/cli/slash.py:115` 更新 permission 上下文，`python/cli/chat_cmd.py:89` 每轮又用启动参数设置，外层 permission_mode 未更新。`/approval always` 后普通任务实际仍 risk。规则：只有一个会话级当前模式来源；回归跨至少两轮、模式切换与异常清理。

F17：`python/cli/chat_cmd.py:243` 把 model_override 和 clear/load 混到同一个重建分支；没有 load_session 就给新 UUID。规则：换模型沿用会话身份与历史，只有显式新会话动作改变身份。回归：已有历史 → `/model` → 下一任务，session_id 相同且历史保留。

## 已确认行为，需定清契约

D01：`python/server/inbox_registry.py:737` 声明 stopped/cancelled 保持 hold，`:370` 的 GET snapshot 却自动 schedule。探针：停止后没有投递，读取快照后启动 held 任务。原有部分 E2E 又期待停止后队列自动跑，显示契约和测试不一致。若 stop 只停当前轮，应统一说明与测试；若 stop 还暂停队列，必须有持久的 hold 状态，GET 不得解除。无需新增模型可见提示。

D02：`python/server/routers/chat.py:810` 在忙碌处理前记录最近请求环境；`python/server/synthetic_round.py:158` 在投递时读该全局会话环境。入队 A 使用 model-A/always，后续请求 B 使用 model-B/never，A 的投递请求载荷变为 model-B/never；最终有效审批还可能受会话覆盖设置影响，本次没有真实模型执行证据。agent_mode/multi_agent/max_tokens 也不在该保存环境中。采用最近模型可以是明确产品选择，但审批权限变化和模式遗漏必须有一致规则。可以选择每消息冻结执行环境，或定义队列跟随会话设置；不能把这项观察误报成付费实跑的效果证明。

## 验证与复现入口

| 基线检查 | 结果 |
| --- | --- |
| Python inbox/steer/goal/CLI/slash 12 个相关测试文件 | 102 passed |
| GUI Composer/Goal/发送/回执/顺序/API/goalSync 7 个测试文件 | 96 passed |
| TUI 既有测试 | 80 passed |
| GUI、TUI 类型检查 | 均通过 |
| 既有真实 Chromium + FastAPI 输入、slash、queue/steer E2E | 12 passed |

共 278 个相关单元/集成测试与 12 个既有 E2E 通过。未宣称运行全仓库 pytest P0 或已满足提交门；本次没有提交。

审计产物在 `docs/input-chain-audit-2026-10-07/`：

- `backend-observations.json`：9 个离线后端/CLI 观察项。
- `frontend-observations.json`：5 个 GUI 组件/状态观察项。
- `tui-observations.json`：3 个实际 Ink App 观察项。
- `queue-order-1.json`、`queue-order-0.json`：前端序列、服务端序列、刷新序列和采样；相应 PNG。
- `queue-live-browser.json`、`goal-reload-browser.json`、`selected-steer-browser.json`：真实浏览器/后端证据；相应 PNG。

观察探针断言的是当前缺陷，所以“passed”表示复现成功，不表示产品行为正确。队列完整顺序测试断言期望不变量，在合并开/关两种模式均失败；归属为本报告 F02，未隐藏或标成 xfail。审计测试独立配置，未接入正常回归目录。

复现命令（先进入对应目录）：

```powershell
# 仓库根：真实路由/组件，所有运行数据在临时目录
py -3.11 docs/input-chain-audit-2026-10-07/reproduce.py

# gui：离线组件观察
npx vitest run --config audit/input-chain.config.ts

# gui：真实 Chromium + 隔离 FastAPI + fake provider
npx playwright test --config audit/input-chain.browser.config.ts

# gui：逐条投递的顺序不变量；预期暴露 F02
$env:XEYO_INBOX_COALESCE='0'
npx playwright test --config audit/input-chain.browser.config.ts --grep 'compare final browser'
Remove-Item Env:XEYO_INBOX_COALESCE

# tui：实际 Ink App，HTTP 用确定性替身，不连接用户现场
npx tsx audit/input-chain-observe.tsx
```

边界：本次没有操作用户生产会话。浏览器覆盖普通发送、繁忙排队、自动投递、回执、刷新、改引导兜底和 Goal；长工具多轮的边界回执使用实际组件探针，未以付费模型跑。未把“所有可能的输入组合均无其他 bug”作为结论。

## 修复顺序与现有裁定

优先处理 F01/F04 的消息所有权与回执完成，再处理 F02/F03 的转录身份和持久顺序，随后补 F05/F06 的自动投递订阅。对输入保护处理 F07/F08/F18；Goal 先补 F09/F11，再统一 F10/F12/F13/F14。CLI 模式和会话问题以及归档执行层检查独立修复。

修复逻辑进入独立模块，Composer/chat/query_loop 留必要接线点；没有加入模型可见的编排、警告或劝导文本。前文规则和回归条件是事故修复前的结构依据；实施状态见下表。

已读 `docs/input-chain-维持项裁定-2026-10-07.md`，保留其中 submission_unknown 分流、归档一帧过渡、CLI Ask 空回车、后台化键位及不实现回合 pause 的裁定。GUI 自动 Goal 续跑等功能的 2026-10-03 主动移除不登记为 bug。

开工工作树干净；过程中另有 `docs/cache-hit-root-cause-2026-10-07.md` 出现，用户确认保留并排除，未读取、修改或纳入本次产物。其余在途文件属于本次审计、修复或验证。

## 已实施修复（工作区，未提交）

用户已确认两条执行规则：停止保留未执行队列，等待手动继续；队列执行使用当时最新设置。D01/D02 的基线描述保留为事故证据，不再是待定产品选择。

| 问题 | 结构性修复 / 不变量 | 回归证据 |
| --- | --- | --- |
| F01/F04 | 单条边界取件只改变所选消息；模型边界送达后服务端独立结束 inbox 所有权 | `test_inbox_selected_delivery.py`；真实选中引导 E2E |
| F02/F03/F05 | 每次模型调用有稳定 assistant message id；回填、流收尾以同一身份更新；服务端转录顺序持久化；自动投递轮独立订阅 | `assistantOutput.test.ts`、`streamPersistence.test.ts`；队列合并/实时回复/刷新 E2E |
| F06 | TUI 从持久队列恢复、跟随投递轮、处理 Ask/审批/工具和回填；断流按当前轮事件游标续接并去重 | `queuedTurn.test.ts` 实际 Ink 键盘场景；`queuedTimeline.test.ts` |
| F07/F08 | 仅成功受理新轮后清对应 Ask/Plan；延迟失败只恢复仍为空的输入框 | `mainPaths.workflow.test.tsx`、`sendPendingClear.test.ts`、`inputLifecycle.test.ts` |
| F09/F10/F12/F13/F14 | 无已知 Goal 也读取；请求代际和后端分支身份防止旧读覆盖；重连消费 goal/jobs；错误回执不解释为空 Goal | `goalConcurrency.test.tsx`、`goals.test.ts`、`sessionProjectionHandlers.test.ts`；Goal 真实 E2E |
| F11/F15 | Goal 编辑同时校验 goal_id 和 revision；归档执行层拒绝写入 | `test_goal_new_session_pin.py`；替换目标后旧编辑器 E2E |
| F16/F17/F18 | CLI 当前审批模式只有一个来源；换模型保留 session_id；CLI/TUI clear/load 清除旧 retry 任务 | `test_cli_session_input.py`、`inputLifecycle.test.ts` |
| D01 | 队列 hold 原子持久化，GET、后续成功轮和重启均不解除；仅手动 resume 解除 | `test_inbox_stop_hold.py`；GUI 停止/刷新/继续 E2E；TUI Esc/换模型/Ctrl+R |
| D02 | 独立 request-environment 更新；GUI/TUI 串行提交最新设置，继续前等待完成；合成请求完整转发字段；后台会话保留自己的审批模式 | `test_request_environment.py`、`useQueuedRequestSettings.test.tsx`；GUI/TUI 手动继续验证 |

修复过程中继续确认并处理的缺陷：

| 编号 | 根因 | 修复与回归 |
| --- | --- | --- |
| F19 | SSE 游标按 session 保存，但每 turn 从头编号，新轮误跳过帧 | 游标绑定 turn_id；`turnCursor.test.ts` |
| F20 | TUI 一轮多次模型调用仍追加到同一 assistant 气泡，穿过工具行 | SSE 传递稳定输出身份，按调用更新；`queuedTimeline.test.ts` |
| F21 | 所选排队引导未遇到下个采样边界，兜底重新 enqueue，产生双重所有权和残留卡 | 兜底恢复原 queue_id、sequence；选中引导回归和真实 E2E |
| F22 | 待投递引导直接写 transcript，既是恢复记录又是已送达历史，造成前后端乱序、刷新不一致 | HTTP 直接引导和 inbox 引导均先持久化 inbox，真正边界送达才写历史；`test_direct_steer_ownership.py`、Ctrl+Enter 真实 E2E |
| F23 | 旧流的延迟 IDB 写入覆盖刚完成的权威回填 | 写入读取当前快照，打开 DB 后再次校验会话/分支/快照所有权；`streamPersistence.test.ts` 两个竞争场景 |
| F24 | TUI 仅跟踪本进程受理的队列，并把断流轮当成已跟踪，不再重连 | 启动/load 从服务端恢复队列；同轮 EOF 不标完成，续接游标避免重复文本和弹窗；实际 Ink 恢复/断流测试 |
| F25 | 同一显式输入 ID 重试可创建两份待投递记录，同批边界投递也没有更新已见 ID 集合 | 普通队列和直接引导复用相同待投递所有权，冲突内容返回 409；边界追加后更新身份集合；重复 HTTP、重复模型历史和不同 ID 同文回归 |
| F26 | HTTP 观察 busy 后，最后一次 settle 可能先于工作线程 push，回调错过新引导，导致消息滞留 | 入队后检查执行状态，已空闲则用原所有权兜底入队；`test_direct_steer_ownership.py` 交接窗口测试 |

直接引导仍保留其已有文本额度；未送达时恢复原持久队列位置，不经过普通 enqueue 的 2000 字限制。提交持久化失败时不入模型边界队列，也不回 202。旧非 HTTP 内部 `t_now_steer.push` 的默认 WAL 兼容路径保留；生产 HTTP、所选 inbox 和自动 inbox 边界均显式使用已有持久所有权。

新增模块的复杂度是局部身份、请求代际、每轮游标和队列暂停状态；不包含模型规划、模型提示护栏或全局评分。主要回归风险为流切换/异步写入竞争、旧转录兼容和多端设置更新。保留理由是已复验的输入丢失、重复、乱序和状态丢失；未做无关重构或恢复已被产品移除的行为。

## 当前验证状态

- GUI 最近全量：225 个文件，1789 passed、5 个既有 skipped；类型检查通过。包含另一批在途滚动工作的测试，其文件未由本代理修改。
- TUI 全量：89 passed，无 skip；类型检查通过。包含真实 Ink 自动接管、停止后换模型并继续、启动恢复与同轮断线续接。
- 最新真实 Chromium + 隔离 FastAPI：整组 9 passed，2.8 分钟；包含 Goal、直接 Ctrl+Enter、普通队列顺序/刷新、实时回复、所选引导、停止后换模型继续，以及旧历史恢复/备份失败/排队持久身份场景。取消恢复回执修复后另行真实按钮链路 1 passed，1.7 分钟。最终整组启动预算 180 秒（各队列用例保留自己的 90 秒）；使用受门禁 fake provider，无付费调用。
- Python 最新全量：5692 passed、1 failed、3 skipped、29 个既有 xfailed，769.55 秒。失败仅为 `tests/test_data_root_overrides.py::test_every_hardcoded_data_root_honours_its_override`，定位到不属于本次输入链修复的在途 `evals/wsc_unresolved_gap.py` 没有使用 `XEYO_SESSIONS_DIR` 覆盖数据目录；按用户“保留/不要管”保持未修改。不能声称 Python 全量全绿，也未静默 xfail。该轮包含 F25/F26 最终实现。
- `fixed/` 保存修改后的前端/服务端/刷新对照；原探针和基线证据保留，用于说明原事故。原观察探针中的“缺陷存在”断言不作为修复验收。

任务仍在进行：输入加载/停止/恢复的组合仍需审查。旧版不同 ID 的额外回复按下文用户选择的权威历史规则恢复。当前结果证明列出的回归场景，不宣称所有输入组合都已无缺陷。未提交或 push。

其他在途改动保留并排除。本次用户已明确“不要管，继续 goal”，不再等待归属确认；未修改 AGENTS.md、滚动交互和独立 WSC 在途文件。

## 后续竞态修复（2026-10-07）

F27/F28 的最初只读探针实际调用 `createStreamRecoverySlice` / `recoverAfterDisconnect`，控制请求返回时序，确认旧分支回复进入新分支、旧历史替换新任务、旧恢复清掉新 controller。原观察探针仅证明缺陷，验收使用正常回归目录中的相反不变量。

| 编号 | 根因 | 修复规则及回归 |
| --- | --- | --- |
| F27 / P1 | 恢复入口和收尾只检查 session 存在，未绑定后端分支 | 独立 `streamOwnership` 模块同时检查会话、后端分支、连接和轮次；跨 await、订阅回调及 IDB 写入失效即退出；`recoveryOwnership.test.ts`、实际 chatStore 晚到正文/工具/Ask/收尾测试 |
| F28 / P1 | 同分支旧恢复可清掉新轮的 controller/loading；旧请求挡住新分支重连 | 在飞恢复仅复用仍有效的所有权；新分支可立即启动探测；普通发送与忙时直接开跑也绑定所有权。忙时断线清除已失效连接后再恢复；合法同轮迟到工具结果继续更新原卡 |
| F29 / P1 | 历史回填只以 GUI 会话去重；行数相等且工具数相同时保留本地错序 | 独立 `sessionHistoryLoader` 只共享同后端传输；每个调用保留自己的本地快照、回溯模式和失效检查；匹配转录身份时采用服务端顺序，保留排队输入。7 项回归覆盖错序、新分支不等待旧请求、迟到旧落盘、延迟 DB 写入、排队卡、本地尾部和显式回溯截断 |
| F30 / P1 | 打字机收尾登记按会话 ID 判断，旧动画可以推进新回复或删除新登记 | 动画逐帧同时检查自身登记和流所有权；只能释放自身登记。先复现 3 项失败，修复后 4 项回归通过，包含当前动画正常收尾 |
| F31 / P1 | 旧停止失败回执可覆盖新任务状态；旧工具超时按整张列表处理 | 回执和停止落盘绑定停止后的所有权；工具对账绑定后端分支；独立 `stoppedTools` 只结算该次停止观察到的工具 ID，保留新工具和晚到成功结果。跨分支/跨轮回执与工具范围回归 |
| F32 / P1 | 冷会话加载分支消息，却未恢复内存中的后端分支 ID，下一次输入可能发往主线 | 独立 `sessionHistoryHydration` 在消息回填前恢复身份，正在加载时的输入等待身份恢复再发送；并发共享加载，旧分支/旧轮迟到不得覆盖。实际 store 验证保存分支恢复及加载期间发送；3 项模块回归 |

上述机制不增加模型可见编排文本。新增状态局限于正在执行的恢复请求、回填代际与动画登记；回填等待受保护的 DB 写入完成，再删除自身代际登记，避免已删除会话留下无限累计的登记。回溯强制服务端快照仍删除旧后缀；服务端仅返回本地前缀时普通回填仍保留本地尾部。未按文本相似度猜测并删除旧版不同 ID 的重复回复，避免误删合法同文输出。

验证已更新为上述最新结果。早期浏览器第一组为 3 passed / 3 failed（启动超时、页面状态丢失、设置回执超时），运行期间发生源码热更新；代码冻结后的第二组为 5 passed / 1 failed（首次页面启动超时）。Goal 单独复跑通过，最终整组在更长冷启动预算下 6 passed；原失败记录不当作产品通过。测试期间后端、浏览器和工作区隔离，未影响实际运行会话。输入链自身 diff 检查通过；整个工作树的 diff 检查另有用户在途 AGENTS.md 文件末尾空行，不代为修改。

边界：同 ID 的已保存错序会从服务端修复；旧版不同 ID 的额外回复不按文本相似度猜测，采用下文完整、稳定的服务端历史和原子备份规则恢复。

## 旧历史恢复与本地输入保留（2026-10-07）

用户明确选择：以完整服务端历史为准；备份原本地历史，保留未送达输入。该规则授权清除服务端没有的旧回复，也包括未保存的回复片段；原始内容留在备份中。

| 编号 | 结构性根因 | 不变量、修复和回归 |
| --- | --- | --- |
| F33 / P1 | 前端把转录消息数组当成完整快照；后端跳过损坏 JSON 行却未将转录标为 degraded | 非完整快照只能合并，不能删本地内容。独立 `transcriptSnapshot` 保留同一返回数组的完整性事实；服务端损坏 JSON、非对象行、读取错误均阻止完整判定。真实 HTTP 6 项、API 和回填回归 |
| F34 / P1 | 旧版不同 ID 的本地回复无法仅凭行数或文本判定；直接替换没有恢复原文的保证 | 独立 `canonicalSessionHistory` 在前后同一已结束轮次中读取完整历史，校验后端身份、轮次、revision、事件游标和状态。`historyBackup` 在同一 IDB 事务内保存原历史并替换；备份失败保留原文并显示提示。首次备份按 GUI 会话/后端分支保留，重复恢复不覆盖；删除会话仅清理自己的备份。真实浏览器覆盖成功、刷新幂等、备份失败和删除范围 |
| F35 / P1 | 工具宽限定时器处理当时整张消息列表，并可能删除新的定时器登记 | 只结算登记时观察到的 waiting 工具；校验原流所有权和精确计时器登记，旧回调不得改新工具或新登记。`streamToolSettle.test.ts` 3 项竞争回归 |
| F36 / P1 | 启动恢复无变化仍创建新数组，导致服务端回填误判内存被修改；等待期间本地 UI 更新也会令回填全部跳过 | 无变化恢复保持原引用。独立 `historyBackfillProjection` 合并本次回填和等待期间新增行，只移除原快照中已经确认删除的行；所有权继续保护新分支/新轮。真实浏览器先确认数据库已修复而页面仍旧，修复后通过；实际 store 验证无变化和异步新增 UI 行 |
| F37 / P1 | 后续更长历史把未送达输入当成旧尾部删除；再次投影混合历史无条件清除投递标记 | `localUndelivered` 在后续回填和混合投影中保留，只由实际已送达行清除。未送达和排队行不进入模型请求历史；实际消息组件显示“未送达 · 本地保留”，不作为服务端可回溯轮次。增加历史增长和重复合并回归 |

恢复过程没有自动发送未送达输入，也没有增加模型可见编排文本。完整性元数据使用弱引用，加载登记结束后释放；备份每个 GUI 会话/后端分支保留一份原始快照。增加的复杂度是局部读写证明和一项原子备份，不引入文本相似评分或全局索引。主要风险是旧转录兼容、持久化容量和异步竞争，分别用实际 HTTP、IDB 故障注入、store 延迟回填及浏览器刷新验证。保留这些修复的依据是已经复现的内容删除、重复回复和页面/数据库不一致。

本轮后端相关回归 35 passed，包含完整性、停止保留、最新设置、引导所有权、投递回执和 Goal。此前 Python 全量的跨功能失败仍保持显式记录，不以这组通过代替全量通过。GUI 最新全量和类型检查见上方。首次两项旧历史浏览器测试失败揭示 F36；修复后两项单独复跑通过。随后整组 8 项验证全部通过，耗时 2.0 分钟；排队实时场景直接验证排队回复已开始、后端 busy、页面运行状态和停止按钮，不把瞬时 delivering 卡是否被轮询采到当作运行状态证据。

继续检查键盘和停止链路，补充两项已复现修复：

| 编号 | 根因 | 规则及验证 |
| --- | --- | --- |
| F38 / P1 | 全局 Esc 捕获仅检查 isComposing，输入法 keyCode=229 事件会触发停止/关闭编辑 | 复用现有 `isImeComposing` 判定，输入法取消事件不进入 Esc 层；先复现失败，再验证 isComposing、229 和普通 Esc 三项 |
| F39 / P2 | 停止专用工具宽限定时器按会话 ID 删除登记，旧超时可删除后续任务的新登记 | 回调首先校验精确 timer 身份；实际停止 slice 测试先复现新登记被删除，修复后要求新登记保留 |

F38/F39 后相关交互回归 60 passed、2 个既有 skipped；GUI 全量更新至 1768 passed，类型检查通过。停止/刷新/换设置/继续的真实浏览器场景再次通过（1 passed，1.1 分钟），其余浏览器场景采用此前冻结版本的整组 8 passed 结果。输入链文件 diff 检查通过。

上述两个待验证点均已复现并修复，继续记录如下。

## 排队持久身份与恢复取消（2026-10-07）

| 编号 | 结构性根因 | 修复规则和证据 |
| --- | --- | --- |
| F40 / P1 | DB 和流式写入快照都会删除暂态 queueState，却没有保存输入尚未送达这一事实；冷读时它会进入请求历史 | 独立 `messageDeliveryPersistence` 将排队用户行转为持久 localUndelivered；DB 所有写入口和 writer 快照共用规则。只由实际已送达行清除此事实；暂态 queued/delivering/syncing 变化不反复写库。浏览器先复现三种 DB 写入均丢身份，修复后真实 IDB 冷读不进入模型历史；writer 测试另外复现提前去标记的问题，验证投递状态变化及最终确认 |
| F41 / P1 | 恢复继续/取消按 GUI 会话清空恢复提示，取消失败也清空；迟到回执能清掉后续恢复任务。后端取消无目标身份、直接 hydrate/flush，可把新运行轮写成 stopped，落盘失败仍回成功 | 独立 `recoveryActions` 捕获后端分支和原恢复对象，仅清原提示；失败保留并提示。继续操作的在飞键含分支和轮次。取消必须传 turn_id；独立服务端 `recovery_abandon` 校验目标、执行状态和归档权限，读取/比较/持久替换共用 turn_snapshot 现有短时锁，失败返回 503。前端四项失败已复现后通过；后端 7 项真实 HTTP 覆盖旧轮次、缺身份、幂等、忙、只读、磁盘失败和与新轮并发写入 |

新取消请求体是 `{turn_id}`；旧客户端不带身份时返回 422，避免无目标取消改变任意当前轮。当前 GUI 调用已同步，仓库 TUI/CLI 无该入口。取消信息仅用于执行层校验，不进入模型上下文。并发测试证明新轮落盘在取消比较/替换窗口等待同一把锁，随后新轮状态仍为 running。

本轮真实浏览器的历史恢复/冷读/备份故障/停止继续 4 项通过（1.1 分钟）；随后 writer 快照修复后的整组 9 项全部通过（2.8 分钟）。相关后端增至 49 passed，包含新增归档和并发用例。GUI 此阶段全量 1773 passed、5 个既有 skipped；类型检查通过。

F42 / P1：恢复取消客户端只看 HTTP 200，空体、`ok:false`、错误状态或其他轮次回执也视为成功。先复现 4 项失败，抽出 `api/recovery` 校验 `ok:true`、`status:stopped` 和请求的 `turn_id`；5 项回执测试覆盖有效和无效响应。原写侧棘轮基线 `api.ts` 的状态独断写法从 12 处收紧到 11 处，不放松门禁；全量初次因此报基线减少漂移，更新计数后重跑通过。恢复取消真实浏览器按钮场景通过（1 passed，1.7 分钟），使用本轮隔离数据中的恢复快照，不触碰实际会话；验证旧目标被拒时提示保留，以及正确取消后页面提示和服务端状态同步。

本轮冻结实现最终验证：GUI 223 文件、1778 passed、5 个既有 skipped，类型检查通过；后端上述相关 49 passed；浏览器整组 9 项通过，回执校验修复后的恢复取消另行 1 项通过。输入链 diff 检查通过。此前跨功能 Python 全量失败仍保留记录，没有静默挂账或修改无关文件。Goal 继续，待查队列编辑/取消的跨分支迟到回执，以及其持久写入边界。未提交、未 push、未付费调用模型。

任务保持进行中；未提交、未 push、未付费调用模型。后续继续审查输入加载/停止/恢复的组合及未覆盖边界。

## 当前修复批次收尾（2026-10-08）

用户要求先完成当前修复，再判断整个 Goal 是否应结束。本批 F40/F41/F42 实现、回归和事故记录已经完成。按当前工作树重新运行，GUI 相关 46 passed、后端相关 49 passed，类型检查通过；此前冻结版本 GUI 全量 1778 passed、5 个既有 skipped，浏览器整组 9 passed 加恢复取消单项 1 passed。本批没有尚未完成的已确认缺陷修复，未提交或 push。

整个 Goal 的完成仍未得到充分证明：队列编辑/取消在切换分支时的迟到回执与持久写入边界尚未验证。建议将该场景作为最后一轮明确范围的收口验收，验证发现的问题修复并通过相关回归后再结束 Goal；不能将待验证点写成已确认缺陷，也不能仅凭本批测试通过宣称整个输入链已完成。

## 用户授权的收口验收（2026-10-08）

用户同意完成上述最后一轮明确范围的检查及修复，再决定结束 Goal。

| 编号 | 根因 | 修复及回归 |
| --- | --- | --- |
| F43 / P1 | 队列编辑/取消回执及后续 DB 写只绑定 GUI 会话 ID；分支切换后，相同消息 ID 的新分支行被旧编辑覆盖或被旧取消删除。轮询写入同样跨越 DB 等待 | 独立 `inboxMutationOwnership` 捕获后端身份和分支；失效回执不改页面、不推进新分支轮询代际。编辑/取消写入分别检查当前文本/消息缺席状态，防延迟写入覆盖后续更新；DB 打开与单行读取后再次校验。轮询增量写入/别名删除传同一代际 guard，等待落盘失效后不启动新分支流。增量 patch 在读取原行后及事务提交前再次校验，失效则原子取消。4 项 slice 失败先复现再通过；真实浏览器编辑/取消分别阻塞实际 HTTP 回执、创建真实后端 fork，并检查新分支内存和 IDB；另在实际 IDB get 成功时使所有权失效，覆盖 update/delete/patch 三个写入口 |
| F44 / P1 | 队列编辑/取消只看 HTTP 200，空体、拒绝体、其他会话/队列或错误文本仍当成功 | 抽出 `api/inboxWrites` 校验确认身份和回显文本；6 项失败先复现，7 项有效/无效回执回归。状态独断写法基线从 11 收紧为 9，未放松守卫；服务端既有回执已经携带所需字段，无新行为 |

首轮整组浏览器 9 passed、3 failed。两项新分支用例错误调用不存在的 saveChatHistoryState，改用已有 setKv 历史键；恢复用例复用了注入恢复快照前的 idle 查询，改为轮询真实重连并验证目标恢复身份。这些是测试准备错误，保留失败记录，不能当作产品验收成功。修正后冻结代码重跑整组 12 项。

本轮 GUI 全量 1789 passed、5 个既有 skipped，类型检查通过；TUI 全量 89 passed、无 skip，类型检查通过。后端本次扩大到输入链相关 CLI、模型边界、引导、队列、设置、Goal、历史完整性和恢复测试，65 passed；整组真实 Chromium + 隔离 FastAPI 12 passed，2.2 分钟。未提交、未 push、未付费调用模型，其他在途工作保持排除。

## 最终完成核对（2026-10-08）

本节为当前结论，前文进行中状态与待检查点保留为过程记录。

| 用户要求或确认规则 | 完成依据 |
| --- | --- |
| 输入框、普通发送、引导、排队交接、消息顺序/重复和卡片消失 | F01–F08、F19–F26 及相关后续修复；GUI/TUI 实际入口回归，浏览器普通队列、实时回复、直接引导、所选引导、刷新前后服务端转录对照通过 |
| Goal 刷新、修改、暂停、切换分支和旧编辑请求 | F09–F15，实际 hook/store、HTTP 身份/代际测试及浏览器 Goal 整条操作通过；未恢复产品已删除的自动行为 |
| 排队统一使用执行时最新设置；停止保留队列，手动继续 | D01/D02 的持久暂停、串行环境更新和执行层转发；浏览器停止/刷新/换设置/继续及实际 Ink 测试通过 |
| 恢复时以完整服务端历史为准，备份原本地历史，保留未送达输入 | F33/F34/F36/F37/F40；完整性实际 HTTP、真实 IDB 原子备份、备份故障、冷读输入排除、启动回填、重复刷新通过 |
| 异步流、恢复、停止及旧回执不得改新任务/分支或新持久记录 | F27–F32、F35/F38/F39/F41/F42；作用域、动画、工具、输入法、恢复回执/并发落盘及真实恢复取消操作验证通过 |
| 最后一轮队列编辑/取消跨分支与落盘验收 | F43/F44；4 项实际 slice 回归、7 项回执校验，真实 HTTP 延迟 + 后端 fork + 三个实际 IDB 写入口失效测试均通过 |

本次输入链审计已确认的 F01–F44 与两项用户产品规则完成修复及回归，用户授权的最后收口验收通过，没有留下已确认而未处理的本范围缺陷。建议结束本次 Goal。该结论证明已列范围和回归，不宣称所有未来状态组合永远无缺陷。

验证边界：GUI/TUI 全量通过；最新 Python 是输入链相关 65 项而非再次运行全部后端测试。此前 Python 全量有一项其他在途 WSC 目录覆盖失败，已明确记录并排除，不声称仓库整体全绿。本次不改其他在途文件，未提交、未 push；交付为当前工作树修复、正常回归用例和本审计证据。
