# 循环熔断器（LoopBreaker）设计 · 实装记录 — 2026-09-14

> 缘起：`sess_mu0mkitk_5aehjt.jsonl` 里同一条 Bash 命令**连续重复 166 次**（第 261→432 次
> 工具调用），`repeat_guard` 越阈即静默（只在第 3/5/8 次报过），`repeat_fold` 又要求输出
> **逐字节相同**（该命令尾挂第二个 `rg`，166 次无一命中）⇒ 执行层与注意力层**同时归零**，
> 止损只剩 max_turns / 墙钟。
>
> 本模块（`python/engine/loop_breaker.py`）的答案：把判定搬到**工具准入层**，且**永不静默**。

## 0. 一句话

同一路径持续无进展 → **该路径持续报错且该次调用不执行**；不注入劝导、不停 run、不写历史。

这是工程铁律 #3 的原文形态（"让该路径的工具持续静默报错"）。

## 1. 参考实现对照（全部读源码实证）

| 实现 | 代码位置 | 判据 | 动作 | 默认 |
| --- | --- | --- | --- | --- |
| **DSH**（上游同源） | `packages/guard/repeat-tool-reminder/src/index.ts` | 同 tool + 规范化参数**连续** | 阈值处**注入提醒**（`additionalContexts`），不阻断 | 开（`[3,5,8]`） |
| cline | `sdk/packages/core/src/runtime/safety/loop-detection.ts` | 同 tool+args 签名连续 | soft=3 提示；**hard=5 停整个 run** | 开 |
| cline | `.../safety/mistake-tracker.ts` | 连续"错误类"事件 ×4 类 | 到 max → **问用户**：换方法（清计数 + recovery notice）或停 | max=3 |
| goose | `crates/goose/src/tool_monitor.rs`（`RepetitionInspector`） | 同 name+params 连续 | **Deny**；deny 分支**不更新 last_call** ⇒ 超限后每次都拒 | `new(None)` → 默认不拦 |
| gemini-cli | `packages/core/src/services/loopDetectionService.ts` | ①同 tool+args 连续 5 ②**周期 k=1..5 各 5 次** ③正文 chunk 重复 10 ④30 轮后每 10 轮 LLM 判官 | 第 1 次：注入 `System: Potential loop detected…` 劝导并重开一轮；第 2 次 abort | 开 |
| OpenHands v0.20 | `openhands/controller/stuck.py` | 4 场景：同 action+obs ×4 / 同 action+error ×4 / **monologue**（连续 3 条 agent 消息逐字相同且中间无 obs）/ 交替模式 ×3 | `AgentStuckInLoopError` → **STUCK 停**（交互模式问用户） | 开 |
| SWE-agent | `sweagent/agent/agents.py` | 连续同类错误计数（超时 / format / blocklist / syntax） | 超限 → 退 run | 配置项 |
| Codex CLI | `codex-rs/` 全树 | **无循环检测**（只有 guardian=风险审批） | 靠 token/turn 上限 + 用户 | — |

**DSH 的两个关键事实**（我们与它同源，判断必须对着它做）：

1. DSH 与 XEYO 的 `repeat_guard` 是同一套语义（阈值 `[3,5,8]`、canonical JSON key-sort、
   `argumentsPreviewChars=500`、用户消息清链）。
2. DSH 把两条局限**写进了 README 的 Known Limitations**：
   - **"Past the highest threshold a chain goes silent"** —— 第 8 次之后再无任何信号；
   - **"Escalating to a blocking form is not implemented"** —— 明确拒绝阻断，理由原文是
     "a blocked call punishes legitimate identical repeats (polling a long-running terminal,
     re-checking a file the agent expects to change)"。

⇒ 结论：**"越阈静默"不是 XEYO 的实现缺陷，是这条设计谱系的固有缺口**；而 DSH 拒绝阻断的
理由（合法轮询被误杀）**是对的**，所以阻断必须配"半开探针"才敢落地——这是本模块相对
上游的两点增量。

## 2. 该学的 / 不该学的

**该学**

1. 判据全是逐字节 / 集合运算（签名归一、周期匹配、digest 相等），没有一家用语义猜测当触发器。
2. **周期 k 检测**（gemini）比"同签名连续"强一档，代价只是几次后缀比较。
3. **计数含被拒的尝试**（goose）：拒绝不更新"上次签名" ⇒ 超限后每次都拒，天然永不静默。
4. **DSH 的取证细节**：参数预览截断（`argumentsPreviewChars`）、`include`/`exclude` 通配、
   误配置 fail-loud（空阈值 / <2 / 重复即抛）。

**不该学**

1. gemini 的 recovery 注入劝导文本（铁律 #1 禁止的导演文本）。
2. cline hard / OpenHands STUCK / SWE-agent exit —— 一次循环 = 该题 0 分；硬顶已有 max_turns/墙钟。
3. cline 的"问用户" —— 无人值守评测里没人回答。
4. gemini 的 LLM 判官 —— 多一次模型调用（钱 + 延迟 + 非确定性），且把"是否循环"交给另一个
   模型裁量，属铁律 #2 禁止的编排。

## 3. 实装：`python/engine/loop_breaker.py`

### 3.1 四档判据（全部逐字节可判定）

| 档 | 判据 | 默认阈值 | 抓什么 |
| --- | --- | --- | --- |
| L1 | 同签名**连续**（`semantic_key`，检索型语义折叠） | 6（`XEYO_LOOP_BREAK_AT`） | 166 次事故形态 |
| L2 | 尾部 `k·C` 个签名构成周期 k（k=2,3）的重复 | C=5（`..._CYCLE_AT`） | "换个近邻签名接着转" |
| L3 | 同签名**且结果摘要与上次相同**连续 | 3（`..._EQUIV_AT`） | 真正零进展 |
| L4 | 同工具连续 N 次结果都是**本回合已见过的摘要** | 4（`..._FAMILY_AT`） | 换参数同结果 |

**L1/L2 只由"换签名"重置**——这是从事故形态反推出来的硬约束：166 次事故的每次输出都不同
（尾挂第二个 rg），若把"有新结果即清零"用在 L1 上，该形态**直接逃逸**。（`repeat_fold` 当年
正是死在"要求输出逐字节相同"这一条上。）

### 3.2 动作

命中 ⇒ 该次调用**不执行**，回一条中性结果型 ToolResult（同形于既有 `[max_tool_calling reached;
tool call was not executed]`）：

```
[loop_break] identical call not executed (tool=Bash; 7 identical calls in a row; args={"command":"rg -n foo"})
```

- `is_error=True`，`metadata={"loop_refused":True,"loop_kind":"L1|L2|L3|L4","loop_count":N,"loop_sig":16hex}`；
- **措辞纯事实**（工具 / 次数 / 形态 / 参数预览 ≤300 字符），零劝导；受禁导演词执法；
- **永不静默**：拒绝不更新"上次签名"，同签名再来继续拒；
- **配对完整**：始终产出 tool_result，不留悬空 tool_use；
- **不占配额**：判定在 `budget.begin_tool_call()` 之前。

### 3.3 半开探针（合法长轮询的出口）

连续拒 R=3 次（`XEYO_LOOP_BREAK_PROBE_AFTER`）后**放行一次探针**；探针拿到新结果 → 该签名
熔断阀解除；结果仍相同 → 继续拒。净效果是合法轮询以 1/4 速率继续（**被限流，不是被判死**），
而 166 次形态被压到 1/4。这条正是对 DSH"拒绝阻断"理由的直接回答。

### 3.4 豁免（transparent：既不计数也不重置，同 DSH 的 `exclude`）

分页续读（`is_pagination_continuation`，offset 递增）· 交互工具（`tools.meta.REPEAT_EXEMPT_TOOLS`）。

### 3.5 开关

`XEYO_LOOP_BREAK=0` 全关（默认开）；四个阈值 + 探针档全部 env 可调，**误配置当场报错**
（fail-loud，对齐 DSH；只在显式设置该 env 时触发，默认路径不可能抛）。

### 3.6 与既有机制的分工

- `repeat_guard`：保留（注意力层的纯事实计数；**不再承担止损职责**）。
- `repeat_fold`：保留（展示瘦身）。两者不互斥：**折叠在前（第 3 次起），熔断在后（第 6 次起）**。
- `loop_ledger` / `ZeroHitTracker`：不动。

### 3.7 取证

每次拒绝追加一行 `usage_dir()/loop_break.jsonl`：
`{ts, kind, tool, sig, count, denied_n, tok_share}`。`tok_share` 来自 `note_turn_tokens`
（token 归属到"该轮前最后一次放行的签名"，近似）——**只记录，不驱动判据**：按签名归属的
占比会误伤"整回合 bash 密集但命令各不相同"的正常工作（AGENTS 硬规矩 4：有数据证明收益后
才并入主链路）。

## 4. 回归测试（`python/tests/test_loop_breaker.py`，23 例全绿）

1. L1：第 N 次起每次都拒，**第 N+50 次仍在拒**（永不静默）；
2. 输出每次微变（事故真实形态）→ **不逃逸**；
3. 换签名 → 链重置（不误杀"编辑-重跑-编辑"）；不同签名互不累积；
4. L2 `A→B→A→B` 命中；L3 同签名同结果命中、结果一变即解除；L4 换参数同结果命中、新内容清零；
5. 半开探针：L1 下 `allowed == [0,1,4,7]`（停流而非判死）；探针拿到新结果解除 L3；
6. 分页 / 交互工具 transparent（不计数也不重置）；
7. 四个档位的文案都过禁导演词 + `[loop_break]` 前缀 + `not executed` 契约；metadata 契约；
8. `XEYO_LOOP_BREAK=0` 零行为变化；阈值误配置 fail-loud；JSONL 取证行；`token_share` 计算；
9. **装配守卫**：`query_loop.py` 里三处接线同时在位。

既有测试联动：`python/tests/test_repeat_guard.py::test_fold_actually_fires_inside_query_loop`
原断言"折叠即终态"（`texts[-1]` 含 `[fold]`）已被准入层接管，改为**两层同时断言**
（折叠仍在 + 熔断在报）——语义变化已在该测试内写明。

## 5. 接线点（5 处，均在 `python/engine/query_loop.py`）

| 位置 | 作用 |
| --- | --- |
| import 区 | `from engine.loop_breaker import LoopBreaker` |
| submit 初始化 | `loop_breaker = LoopBreaker(exempt=frozenset(EXEMPT_TOOLS))`（每 submit 新建） |
| `_admit_tool_use` | `admit` → 命中即填 ToolResult 并 `return events`（在 budget 之前） |
| usage 尾帧处 | `note_turn_tokens`（取证，只记录） |
| 结果落 store 前 | `observe_result`（L3 / L4 / 探针自愈） |

三处调用都经 `safe_observe` 隔离：**判定失败 fail-open 放行**（工具照跑），但记 debug 日志
（不静默吞）。

## 6. 风险与边界（诚实项）

- 对评测臂预期收益 ≈ 0：109 条 trial 里最长"同签名连续"= 2，远低于 N=6；收益主要在 GUI 使用态。
- L1 阈值 6 = "连续 6 次同签名且中间**没有任何其它工具调用**"；除轮询外均为病态。轮询由探针限流。
- `tok_share` 归属是近似（一次模型调用可能产出多个工具调用），只作证据。
- 本模块**不写 MessageStore 历史**，只改准入处的 ToolResult → 投影字节稳定性不受影响。
- 待办（未做）：`p6_run.py` 的**单题成本上限**（评测层护栏，独立于引擎）。