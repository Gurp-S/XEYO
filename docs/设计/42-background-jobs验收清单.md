# 42 · Background Jobs —— 完整验收清单

> 覆盖设计 §0 冻结口径 1-7、§3.4 互激、§4-§10 全部 P0 语义、§12 测试清单。
> 每条标注执行方式：**[自动]**=已由单测覆盖（给出证据），**[手工]**=必须真实管线人工验证，
> **[可选]**=自动化已盖、手工加验更稳。
> 验收范围 = P0 后端 + P0 GUI。P1 项（spill 指针 / AgentTool 后台化 / cli-ts / kill-ASK 复检）
> **不在本次验收**。

## 阶段 0 · 自动化门槛

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| A1 | [自动] | `py -3.11 -m pytest tests/test_job_registry_t42.py tests/test_goal_round_driver_t41.py tests/test_goal_api_t9.py tests/test_server_api.py tests/test_server_hardening.py tests/test_catalog.py -q --basetemp=.pytest-tmp`（workdir `python/`） | 全部 passed（当前基线 76/76） |
| A2 | [手工·bat] | 双击 `run-gui-check-jobs-p0.bat`（注意别跑成旧的 goal-dock bat） | typecheck 0 错；vitest 除 2 个在案失败（chatStore PR-R4、MessageList reasoning）外全绿，且**不出现新失败** |
| A3 | [手工] | 双击 `XEYO.bat` 启动 | 后端日志出现 `settlement hub registered (goal + jobs tenants)`；无未捕获异常刷屏 |

§12 单测证据对照（已自动化，不再手工重复）：owner 隔离 / 容量 10 start 前失败+文案教 job_kill /
首次结算优先 / 快照拷贝 / ring 保尾+UTF-8 / 权限拒绝不产生 job / 忙→pending 合并→单唤醒轮 /
唤醒消费置 reported / kill·终态 read 抑制 / 预算 3 耗尽→pending+T_now 补投且注入即出队 /
让位取消不耗预算 / 409 竞争作废 / 恒注册空转 / hub 异常隔离 / bash 桥×4（registry 文本、
legacy 回退、容量错误、permission-denied 无 job）。

## 阶段 1 · 工具面恒注册（冻结口径 5）

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| B1 | [手工] | 新会话问模型：「列出当前后台任务」 | `job_list` read 卡（Checking/Checked），结果 `(no background jobs)`；三工具 schema 恒在（24 工具目录不变） |
| B2 | [自动] | catalog 冻结断言 + meta 行 | test_catalog.py 内 job_output/job_list/job_kill 三行 + 24 工具 drift assert（A1 已盖） |

## 阶段 2 · 主链（§4/§5/§6 正路径）

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| C1 | [手工] | 普通前台 Bash 命令（不带 run_in_background） | 行为与改造前逐字节一致（冻结口径：additive） |
| C2 | [手工] | 对模型说：「用 Bash run_in_background 跑 `ping -n 25 127.0.0.1`，跑完告诉我」 | 工具卡**立即**返回 `Started background job bash-1…（完成会自动通知，凭通知 job_output 收结果）`；该 turn 正常结束不等命令（§5 不适用超时） |
| C3 | [手工] | 观察右上角 | 角标出现「后台 1/1」+ 旋转图标；点开弹层：行 = bash-1 + label + 耗时每秒推进 |
| C4 | [手工] | 等 ~25s | 日志 `job started bash-1 (bash: …) owner=…` → `job settled bash-1 [succeeded]`；2s 防抖后**自动出现唤醒轮**（一条后台任务完成通知的用户消息），模型调 job_output 收结果并答复；角标行变「已完成」耗时冻结 |
| C5 | [手工] | 唤醒轮后继续观察 | 不再二次通知（reported 抑制）；终态行弱化保留 |
| C6 | [手工] | 后台跑一个必败命令（如 `exit 3`） | 唤醒通知带 `[status: failed]`；弹层 detail `exit code 3` **取代状态词**「失败」 |
| C7 | [可选] | 两个后台任务几乎同时跑完 | 只花**一个**唤醒轮（通知为合并 digest）；日志一次唤醒 submit |

## 阶段 3 · GUI 细节矩阵（§8，冻结口径 6）

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| D1 | [手工] | 无任务会话 | 角标整个不渲染（不长控件） |
| D2 | [手工] | 1 running + 1 succeeded | 计数「后台 1/2」（running+stopping / 总数） |
| D3 | [手工] | 混合多任务开弹层 | 活跃行在前（startedAt 升序）、终态行后（finishedAt 降序），顺序确定 |
| D4 | [手工] | failed 行有 detail | detail 取代状态词；无 detail 才显示状态词 |
| D5 | [手工] | 活跃 + 终态并存 | 活跃行耗时每秒推进；终态行冻结在 finishedAt；关闭弹层时钟即停 |
| D6 | [手工] | 终态行 | 弱化（降透明度）但**保留**不清除 |
| D7 | [手工] | 重启 XEYO.bat（内存态清空）后回到该会话 | 角标消失（GET 播种空集 → 删除键）；transcript 里 run_in_background 卡片仍在（§9 接受项） |
| D8 | [手工] | 多会话切换 | 会话切换即 GET 播种，角标数据与后端一致 |
| D9 | [手工] | 检查弹层 | 只读：无 kill 按钮、无人类中断行、无流直读 |
| D10 | [手工] | 观察三类卡 | run_in_background ack = generic 卡；job_output/job_list = read 卡（Checking/Checked）；job_kill = execute 卡（Stopping/Stopped）；job_id 出现在 detail（`job bash-N`） |

已接受偏差（不算失败）：SSE `jobs` 帧只在 turn 起点播种（§8）；owner turn 存活期内的结算变化由
GUI 5s 轮询补齐（无 out-of-turn 推送通道，同 GoalDock 取舍，已文档化）。

## 阶段 4 · 唤醒预算与互激（§3.4，冻结口径 3）

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| E1 | [手工] | 连续做 3 次「后台跑 + 等自动唤醒」后，第 4 次跑完 | **不再自动唤醒**（预算 3 耗尽，任务留 pending）；角标行停在终态 |
| E2 | [手工] | 随便发一条人类消息 | 该轮请求模型可见 `# Background jobs（background only）` 补投块（id/kind/status/detail + job_output 指引）；模型应 job_output 收掉；注入即出队（下一轮无此块） |
| E3 | [手工] | 再发一条消息后重跑后台链 | 预算已恢复 → 自动唤醒重新工作 |
| E4 | [手工] | armed goal 会话里跑后台 job（或 job 唤醒轮触发 goal 复检） | goal 轮与 job 唤醒**共享**预算：连续自产出合计 ≤3 轮即降级；goal 自身 max_rounds cap 独立生效（两道闸）；唤醒轮不消耗 goal rounds |

## 阶段 5 · kill 与工具细节（§7）

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| F1 | [手工] | 起一个长后台任务，对模型说「用 job_kill 停掉 bash-N」 | execute 卡 Stopping/Stopped；返回 `requested cancellation of job bash-N`；日志 `job settled bash-N [killed]`；弹层行「已终止」 |
| F2 | [可选] | kill 不存在的 id / 已终态 id | `unknown job: X` / `job X already killed`（单测已盖） |
| F3 | [可选] | 长输出任务让模型分两次 job_output | 第二次只回增量，响应尾 `[status: running|succeeded]`（单测已盖游标与尾标） |

## 阶段 6 · 容量 / 权限 / 隔离 / 恢复（§0 口径 7、§4、§9）

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| G1 | [手工] | 起 10 个长后台任务后再让模型起第 11 个 | 第 11 个**生产前失败**，错误文案教模型先 job_kill 腾位；已有 10 个不受影响 |
| G2 | [手工] | ASK 权限 preset 下让模型后台跑命令 | 先弹 Bash 权限（后台不绕过三态）；拒绝则无 job 产生、角标不出现（单测已盖；手工验证 GUI 面） |
| G3 | [手工] | 后台任务运行中，中断该会话 turn（停止按钮） | turn 中断**不杀** job（job 有独立 AbortController）；job 完成仍正常唤醒 |
| G4 | [可选] | 两个会话各自后台跑 | owner 隔离：A 会话任务对 B 会话模型不可见、不可 kill（单测已盖） |
| G5 | [手工] | 重启 XEYO.bat | job 全清、角标消失、无崩溃；子进程由 OS 收割，无孤儿残留报错 |
| G6 | [可选] | `py -3.11 -m cli chat` 进程内（无 server）跑 run_in_background | 走旧式日志文件后台路径，不炸（单测已盖 fallback） |

## 阶段 7 · 让位与回归

| # | 方式 | 操作 | 通过标准 |
|---|------|------|----------|
| H1 | [手工] | job 完成唤醒在途（2s 防抖窗口内）立刻发人类消息 | 人类消息优先执行（让位）；唤醒预约取消且不耗预算 |
| H2 | [手工] | 按 41 号 E2E 文档抽验 A1-A3 + E + F | 41 号链在共享预算修正后仍全绿；armed 连续自动轮 ≤3（E4 可合并观察） |
| H3 | [手工] | 对照既有失败集合 | 仍只有：GUI 的 PR-R4 + MessageList reasoning；pytest 的 notebook policy。**不新增** |

## 验收判定

- 阶段 0-7 全部 P0 项通过 + 已知失败集合不变 → **42 号 P0 验收通过**。
- 任一 [手工] 项失败：记录现象 + `logs\` 对应日志段，回炉修复后重跑该阶段。
- P1 项（spill 指针、AgentTool 后台化、cli-ts 只读展示、kill-ASK 复检）明确不在本次范围。
