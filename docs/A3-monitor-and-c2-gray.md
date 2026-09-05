# A3 日常监控 + C2 灰度启用

> 目标：把「超长会话 C2」用**灰度 + 监控**的方式安全落地，并补齐 docs/12 表C / TODO 完工门的 A3 证据。
> 依据：`docs/实施计划/12-压缩质量验证计划书.md`（表C C4/C5）、`docs/总纲与路线/TODO.md`（A3）、`docs/落地前事件.md`（推荐口径：扩展机制逐个 evidence-gated 开启）。

---

## 0. 一句话结论

**当前默认形态本身就是"灰度"**：`DEFAULT_MODE="project"`（默认不跑每轮 decide）+ `DEFAULT_C2_GATE=False`（不设 `XEYO_C2_GATE` 时 C2 关）。你只需要：

1. 真遇到**超长会话（接近模型窗口）**想省钱时，才开 `XEYO_C2_GATE=1`；
2. **每天**跑一次 A3 日常监控，攒 3–7 天证据。

本处 C2 灰度开关**已接入 GUI 设置面板**：`设置 → 记忆系统开关`（持久化到 `.xeyo/settings.json` 的 `memory` 段，切换后运行时立即生效），涵盖 `XEYO_C2_GATE`、`XEYO_L5`、`XEYO_TOOL_AGING`、`XEYO_C2_LLM_SUMMARY`、`XEYO_C2_CITATION`。后端端点 `GET/POST /v1/settings/memory`（loopback 门禁）。

> 注：`C2_gray_on.bat`/`C2_gray_off.bat` 走 `setx` 用户级环境变量；GUI 开关走 settings.json（优先级更高、对运行时更权威）。二者可并存，GUI 开关会覆盖同名 env。

---

## 1. C2 灰度启用（XEYO_C2_GATE=1）

**语义**：允许压缩公式对「**会话逼近窗口**」的超长会话（公式 HardTop/软顶 且 `Q≥θ*=0.5`）触发 C2。普通会话**永不触发**（公式门控）。运行时默认关。

**开关脚本（用户级，`setx` 写入注册表，新开进程生效）**：

| 动作 | 脚本 | 说明 |
|---|---|---|
| 开灰度 | `C2_gray_on.bat` | `setx XEYO_C2_GATE 1` |
| 关灰度 | `C2_gray_off.bat` | `setx XEYO_C2_GATE 0`（恢复默认关） |

或**只对单个会话**：启动 XEYO 前 `set XEYO_C2_GATE=1`（同一 cmd 窗口，不持久）。

**必须知道的风险（重要）**：

- **质量退化**：在超长会话压缩态，**早期具体事实保真弱于 project**（本会话 A/B 实测：v61 66.7% vs 原样 91.7%，Δ=-25pp，事实层 6 题 0/3）。缓解：右尾保留最近 3 个工具轮（近期上下文完整）；只对真逼近窗口的会话开。
- **命中率口径**：A1/A2 达标值（尾窗≥99%、输入更低）是**合成循环会话**测得；真实会话（含文件重写尖峰）收敛更慢，省幅可能低于合成口径。
- **必须配套 A3 监控**：开了 C2 若没有每日监控，命中率塌 / C2 滥用无人发现。

---

## 2. A3 日常监控（自动）

**脚本**：`A3_daily_monitor.bat`（仓库根目录）

**做什么**：
1. 读生产 ledger `~/.xeyo/usage/events.jsonl` + `c2_events.jsonl`（**不设 `XEYO_USAGE_DIR`，必须读真实 ledger**）；
2. 写一行快照 `deploy_project_mode_<day>` 到 `docs/12` 表D（列：命中率/C2次数/req/输出/成本）；
3. 末尾离线跑 `--gate-verdict`（免费）打印当前各门判定。

**日志**：每次输出写入 `.diag_memory_cost\a3\a3_YYYYMMDD.log`。

**手动跑**：双击，或
```
A3_daily_monitor.bat
```

**或从设置面板手动触发**：`设置 → 记忆系统开关 → A3 日常监控快照 →「立即快照」`（调用 `POST /v1/settings/memory/snapshot`，与上面脚本走同一条 `--monitor-daily`，写同一处证据）。

**按天去重**：快照写入 `deploy_project_mode_<day>`，以「天」为行主键 upsert——同一天无论自动任务跑多少次、手动点多少次，**只覆盖该行、不新增**。`--gate-verdict` 的 `A3-日常监控` 行统计的是"已采集 N 个不同日"。

**每天定时（自动）** —— 注册为 Windows 计划任务（当前用户，无需管理员）：

```
schtasks /create /tn "XEYO_A3_DailyMonitor" ^
  /tr "\"D:\lea\XenYon code\A3_daily_monitor.bat\"" ^
  /sc daily /st 09:30 /f
```

- 想改时间：把 `/st 09:30` 换成你想要的 HH:mm。
- 想看已注册/取消：`schtasks /query /tn XEYO_A3_DailyMonitor` / `schtasks /delete /tn XEYO_A3_DailyMonitor /f`
- 备注：若路径含空格（本项目如此），`/tr` 里要用 `\"...\"` 包裹，如上已处理。

---

## 3. 判定标准（A3 怎么算过）

| 项 | 达标 |
|---|---|
| 日命中率 | ≥ 95%（`deploy_project_mode_<day>` 行 `hit_rate`） |
| C2 次数 | 默认关 = 0；灰度开 = 受控（不大幅增长） |
| 天数 | **连续 3–7 天达标** |

- 看结果：`A3_daily_monitor.bat` 末尾的 `--gate-verdict` 的 `A3-日常监控` 一行，显示"已采集 N 天、达标 M 天"。
- 证据落点：docs/12 表D `deploy_project_mode_*` 行，可用 `--accept <row_id>` 人工打勾。

**数据闭环**：A3 连续达标 + 表A/B2 质量门过（真实源）+ A1 真实 200+ 轮 → 才考虑把 `l5_flag.DEFAULT_C2_GATE` 改 `True`（生产默认允许超长会话 C2）。在那之前保持"灰度"，`C2_gray_on.bat` 只对超长会话临时开。

---

## 4. 注意事项 / 边界

1. `A3_daily_monitor.bat` 与 `v61_gate_test.bat`**互不影响**：前者读真实 ledger，后者用隔离目录（`apply_sandbox` 覆盖）+ 测试会话。
2. `--monitor-daily` 没有模型调用、不花钱，只是读 ledger + 写 docs/12。
3. `setx` 只对新进程生效；当前已开的 XEYO 不会立即改变。
4. 若每天都有新的生产数据（events.jsonl 有增量），`deploy_project_mode_<day>` 才会新增；无数据当天脚本会打印 SKIP 并 rc=1，不影响前几天的行。
5. 灰度开启期间的 C2 事件会进 `c2_events.jsonl`，`--monitor-daily` 的 C2 次数列会相应反映，便于观测是否受控。

---

## 附：相关文件

| 文件 | 作用 |
|---|---|
| `A3_daily_monitor.bat` | 每日 A3 监控（建议计划任务） |
| `C2_gray_on.bat` / `C2_gray_off.bat` | 用户级 C2 灰度开关 |
| `python/scripts/memory_stack_eval.py` | `--monitor-daily`（C4）/ `--gate-verdict`（汇总判定） |
| `docs/实施计划/12-压缩质量验证计划书.md` | 表D 证据落点 |
