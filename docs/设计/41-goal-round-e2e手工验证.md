# 41/42 号 —— 手工 E2E 验证步骤（Goal Round Driver + Background Jobs）

> 目的：在真实运行的应用里验证 41 号全链（armed → 合成轮 → admit 计轮 → cap 软锁 →
> failed→blocked → 让位/停止 → 重启静止）与 42 号后台任务链（后台启动 → 角标/弹层 →
> 完成唤醒 → job_output 收结果）。单测已覆盖各环节，本步骤验证**真实管线串联**。
>
> 准备：双击 `XEYO.bat` 启动（FastAPI + GUI）。后端控制台确认出现：
> `settlement hub registered (goal + jobs tenants)`（app.py lifespan 注册成功）。

## 观察点速查（后端日志关键行）

| 日志行 | 含义 |
|---|---|
| `goal round submit session=… goal=… round=N/M` | 合成轮已提交（N=即将开的轮次） |
| `goal blocked session=… goal=… reason=…` | 失败轮补记账 blocked |
| `goal round yield_to_human session=…` | 人类消息让位成功 |
| `goal admit CAS miss (round uncounted) goal=…` | 竞争作废，轮号未消耗（保守方向） |
| `goal round skipped session=… wake budget exhausted` | 共享唤醒预算耗尽，不开轮（42 号 §3.4） |
| `job started bash-N (bash: …) owner=…` | 后台 job 登记 |
| `job settled bash-N [succeeded|failed|killed] …` | job 结算 |

GUI 观察：输入框上方 GoalDock 的五态流转（进行中 / 已开启自动续跑 / 自动续跑·第 N 轮 / 待确认完成 / 已阻塞）。

## A. 主链：armed → 自动续跑 → 轮次递增

> **42 号落地后的口径变化**：goal 复检唤醒与 job 唤醒共享 per-session 唤醒预算
> `wakes_remaining=3`（防双自激）；任何一方的自产出都不恢复预算，只有**人类消息**
> 恢复。即 armed 连续自动轮数最多 3 轮（未到 goal cap 就停），此后 dock 保持
> 「已开启自动续跑 · 第 N 轮」不动——发任意一条人类消息即恢复，续跑继续。
> 41 号单测在 42 号前验证时无此限制。

1. GUI 新会话，发一条**会做多轮**的真实任务（例：「在 workspace 里写一个 fizzbuzz.py，跑通后再造三个变体文件」，保证模型干一轮干不完）。
2. 发出后 GoalDock 出现：「目标进行中 (1)」+「自动续跑」按钮。
3. 点「自动续跑」→ 变「已开启自动续跑 · 第 1 轮」（呼吸点 = 预约在途）。
4. 等本轮结束：约 2 秒防抖后后端日志出现 `goal round submit … round=1/32`；GUI dock 变「自动续跑 · 第 1 轮」（旋转图标 = 轮中）。**模型收到的用户消息是 enriched resume prompt**（气泡仍显示「继续」，属预期）。
5. 该轮结束后 dock 回「已开启自动续跑 · 第 2 轮」并自动继续——轮次逐轮递增。

## B. 待确认完成（候选 → 收敛）

1. 给模型一个 1-2 轮能做完的小任务并 armed。
2. 某轮结束时 todo 全 done → settlement 置候选 → dock 变「**待确认完成**」+ [标记完成] [继续此目标]。
3. 点「标记完成」→ dock 消失（goal → completed）。
4. 重做一次，这次点「继续此目标」→ 回「目标进行中/续跑」（候选清除，armed 保持则继续跑）。

## C. cap 软锁（可选：需要改 cap）

默认 cap=32 手工等不起。用 PATCH 把当前会话 goal 的 max_rounds 设为 2（PowerShell）：

```powershell
$sid = "<会话id>"   # GUI 会话 id（URL / 日志里可见）
Invoke-RestMethod -Method Patch "http://127.0.0.1:8000/v1/sessions/$sid/goal" -ContentType "application/json" -Body '{"action":"edit","max_rounds":2}'
```

armed 跑满 2 轮后，第 3 次准入会把 goal 软置候选（pending_complete）→ dock 变「待确认完成」——**不是**硬停、不是自动 completed。恢复：GUI 点「继续此目标」或 PATCH `{"action":"continue"}`。

## D. 失败 → blocked + 自动 disarm（冻结口径 3：不自动重试）

1. armed 且空闲时，把 GUI 设置里的**模型名改成不存在的值**（或改错 API Key）。
2. 等下一次合成轮：后端对该请求失败 → turn failed → 日志 `goal blocked … reason=…` → dock 变「**已阻塞**」+ 原因 + [恢复]。
3. 确认**没有**自动重试（dock 停在阻塞态）。
4. 把模型名改回 → 点「恢复」→ 回「目标进行中」（disarmed；blocked_reason 清空）。要续跑需再点「自动续跑」。

## E. 停止 / 让位

- 轮中点 dock「**停止**」→ 中断当前轮 → settlement stopped → 自动 disarm → dock 回「目标进行中」。
- armed 空闲点「**停止续跑**」→ 预约作废，不开新轮。
- （可选，2 秒窗口）armed 刚结束的 2s 内立刻发人类消息：日志出现 `goal round yield_to_human`，人类消息正常执行。错过窗口合成轮已开跑则得到 409 session_busy——属现有租约语义（mid-turn 让位是 43 号范围）。

## F. 重启静止（armed 不落盘）

armed 状态下重启 `XEYO.bat` → dock 回「目标进行中」（需要重新 arm）。

## G. 42 号：后台任务 → 完成通知 → job_output（后台链）

1. GUI 会话里对模型说：「用 Bash 工具 run_in_background 跑 `sleep 25`（或 ping -n 25 127.0.0.1），跑完告诉我」。
2. 模型调用 Bash(run_in_background) → 工具卡立即返回 `Started background job bash-1…`，turn 正常结束（不等命令跑完）。
3. ChatHeader 出现角标「后台 1/1」（旋转图标）；点开弹层：行 = `bash-1` + label + 耗时每秒推进。
4. 约 25s 后：后端日志 `job settled bash-1 [succeeded]` → 防抖 2s → 自动出现**唤醒轮**（一条「后台任务完成通知」的用户消息，模型凭通知调 job_output 收结果并答复你）。角标变「后台 1/1」无旋转，行状态「已完成」耗时冻结。
5. 预算观察：连续三次「后台跑 + 等完成」后，第四次 job 完成不再自动唤醒（预算 3 耗尽）——你随便发一条人类消息，消息开头会收到 `# Background jobs` 补投块（模型可见），它应调 job_output 收掉。
6. job_kill：让模型再起一个长后台任务，然后对它说「用 job_kill 停掉 bash-N」→ 弹层行变「停止中」→「已终止」，日志 `job settled bash-N [killed]`。

## 通过标准

A1-A5 全程轮次递增且每轮都走真实 chat 管线；B 两个动词都能收敛；C 软锁出现且可恢复；
D blocked 有原因、无自动重试、可恢复；E 停止即停；F 重启后静止（A-F=41 号）；
G 后台启动即回、角标/弹层实时、完成自动唤醒并 job_output 收结果、预算 3 后降级待领、
kill 即停（G=42 号）。全程无未捕获异常刷屏。
