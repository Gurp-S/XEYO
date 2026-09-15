# XEYO QA 题库 · 第 2 批（B02）

> 题号范围：**XEYO-QA-0051 – XEYO-QA-0100**
> 主题：engine 主循环（query_loop / query_engine / turn_runner / subagent_runner / scheduler / plan / goal_state / 轮次记账）
> 难度配比：简单 22 / 中等 18 / 困难 8 / 超压 2
> 事实基线（本批实际逐一读过的文件与实测行数）：
> `python/engine/query_loop.py`(2000) · `query_engine.py`(1430) · `turn_runner.py`(493) · `subagent_runner.py`(1411) · `scheduler.py`(1110) · `goal_state.py`(705) · `plan.py`(125) · `budget.py`(492) · `repeat_guard.py`(315) · `wrap_gap.py`(108) · `turn_snapshot.py`(181) · `title.py`(331) · `task_state.py`(85)
> **边界声明**：容错与工作区账本（compact / abort / aging / repeat_fold / wrap_window / stage_clock / loop_ledger / process_ledger / workspace_lock / workspace_restore / workspace_revision / write_store / shadow_git）归 **B03**；permissions 裁决归 **B07**；rewind 归 **B11**；本批一律不重复出题。

---

## 本批题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0051 | 简单 | 概念确认 | QueryEngine 的配置类型 | `query_engine.py:85,145,154` |
| 0052 | 简单 | 机制解释 | submit_message 进程内互斥 | `query_engine.py:489,500` |
| 0053 | 简单 | 概念确认 | query_loop 的参数面 | `query_loop.py:726-742` |
| 0054 | 简单 | 概念确认 | 早读工具开关默认值 | `query_loop.py:112-115` |
| 0055 | 简单 | 概念确认 | 收尾窗配额默认值 | `query_loop.py:118-129` |
| 0056 | 简单 | 机制解释 | tool_call.begin 参数摘要 | `query_loop.py:100-109` |
| 0057 | 简单 | 概念确认 | 早读黑名单 | `query_loop.py:93` |
| 0058 | 简单 | 机制解释 | 早读的三个前置条件 | `query_loop.py:155-176` |
| 0059 | 简单 | 概念确认 | budget 默认轮次/工具上限 | `budget.py:19,24` |
| 0060 | 简单 | 机制解释 | grace turns 与 cap streak | `budget.py:25,30` |
| 0061 | 简单 | 概念确认 | 重复调用建议阈值 | `repeat_guard.py:39` |
| 0062 | 简单 | 概念确认 | 守卫是否真的拦截 | `repeat_guard.py:41-45` |
| 0063 | 简单 | 概念确认 | 零命中提示触发点 | `repeat_guard.py:288` |
| 0064 | 简单 | 机制解释 | 搜索工具的折叠默认口径 | `repeat_guard.py:109-110` |
| 0065 | 简单 | 概念确认 | 终态 turn 保留数 | `turn_runner.py:27` |
| 0066 | 简单 | 机制解释 | 帧缓冲双上限 | `turn_runner.py:21,24` |
| 0067 | 简单 | 概念确认 | busy 租约心跳间隔 | `turn_runner.py:221-229` |
| 0068 | 简单 | 机制解释 | TurnSnapshot 三函数 | `turn_snapshot.py:78,122,142` |
| 0069 | 简单 | 概念确认 | 标题字节上限 | `title.py:25,27` |
| 0070 | 简单 | 概念确认 | 子代理四档默认预算 | `subagent_runner.py:23-26` |
| 0071 | 简单 | 机制解释 | follow-up 短预算 | `subagent_runner.py:54,58,63` |
| 0072 | 简单 | 概念确认 | goal 轮次硬顶 | `goal_state.py:66` |
| 0073 | 中等 | 机制解释 | multi_agent 软提示语义 | `query_loop.py:748` |
| 0074 | 中等 | 机制解释 | include_memory_index 为何传 False | `query_loop.py:751` |
| 0075 | 中等 | 概念确认 | 主循环两个退出条件 | `query_loop.py:796-804` |
| 0076 | 中等 | 场景设计 | 收尾窗与配额消费 | `query_loop.py:786-791,805` |
| 0077 | 中等 | 机制解释 | ensure_before 的时序契约 | `query_loop.py:744-746` |
| 0078 | 中等 | 机制解释 | LLM 重试上限与退避 | `query_loop.py:263-281` |
| 0079 | 中等 | 场景设计 | interrupt 为何取消三类面板 | `query_engine.py:401-434` |
| 0080 | 中等 | 机制解释 | goal 候选派生只记账 | `query_engine.py:436-483` |
| 0081 | 中等 | 代码阅读 | 帧裁剪的丢弃方向 | `turn_runner.py:211-220` |
| 0082 | 中等 | 机制解释 | incomplete_tools 与截断 | `turn_runner.py:237-259` |
| 0083 | 中等 | 机制解释 | subscribe/wait_done/断连 | `turn_runner.py:386-398,413,462` |
| 0084 | 中等 | 代码阅读 | 终态驱逐排序依据 | `turn_runner.py:186-198` |
| 0085 | 中等 | 机制解释 | 拓扑排序与环打断 | `scheduler.py:109,154` |
| 0086 | 中等 | 机制解释 | 任务工具白名单 | `scheduler.py:191,202` |
| 0087 | 中等 | 场景设计 | 崩溃恢复标记 | `turn_snapshot.py:151,167` |
| 0088 | 中等 | 机制解释 | 标题双阶段生成 | `title.py:62,162,280,311` |
| 0089 | 中等 | 机制解释 | Plan 面板 TTL 与 resolve | `plan.py:30,38,64,90` |
| 0090 | 中等 | 概念确认 | BudgetTracker 三闸方法 | `budget.py:251,281,302` |
| 0091 | 困难 | 场景设计 | 早读为何只放 ALLOW | `query_loop.py:155-176` |
| 0092 | 困难 | 场景设计 | R3' 收尾窗不再全禁 | `query_loop.py:786-791` |
| 0093 | 困难 | 场景设计 | 三重互斥闸防御纵深 | `query_engine.py:489` + `turn_runner.py:143` |
| 0094 | 困难 | 场景设计 | 帧缓冲上限 vs reattach | `turn_runner.py:186-220` |
| 0095 | 困难 | 场景设计 | goal 轮次推进权迁移 | `query_engine.py:442-451` |
| 0096 | 困难 | 代码阅读 | 子代理预算按 scope 推导 | `subagent_runner.py:39-49` |
| 0097 | 困难 | 代码阅读 | 结论可用性与写后失效 | `subagent_runner.py:567,610` |
| 0098 | 困难 | 场景设计 | wrap guide 的 fail-open | `query_loop.py:132-152` |
| 0099 | 超压 | 故障排查 | 长回合+重连+租约竞态 | `turn_runner.py:200-260` |
| 0100 | 超压 | 场景设计 | 四机制叠加的注意力污染 | `query_loop.py:774-791` + `repeat_guard.py` |

---

### XEYO-QA-0051 QueryEngine 的配置载体

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_engine | 引擎实例的配置结构 | 简单 | 概念确认 | `python/engine/query_engine.py:85,145,154` |

**面试官提问**
`python/engine/query_engine.py` 中，`QueryEngine` 的构造配置用什么方式承载？请说明这个承载方式的好处。

**参考答案要点**
**正解：B（用 `TypedDict`（`QueryEngineConfig`）承载，属于**静态类型提示**，运行时不校验）**
`query_engine.py:85` 定义 `class QueryEngineConfig(TypedDict):`；`query_engine.py:145` 定义 `class QueryEngine:`；`query_engine.py:154` 是 `def __init__(self, config: QueryEngineConfig) -> None:`。

`TypedDict` 是 **typing 层面的静态结构声明**，不是运行时校验器——传入的仍是普通 `dict`，缺键/多键/类型不符在运行时**不会**被 Python 自动拦截（只有 mypy/pyright 类静态检查会报）。这说明引擎对配置的健壮性依赖的是调用方（`build_default_engine`，`query_engine.py:1194`）而不是类型系统。

**深化讲解**（面试官参考，不要求候选人全说）
本题考「源码细节中的类型机制语义」。A 是常见误判——XEYO 的 server 层（FastAPI）大量用 Pydantic，但**引擎内部配置不走 Pydantic**；C 漏掉了 `TypedDict` 这层声明；D 把配置对象与数据模型混淆，`QueryEngineConfig` 是给 `dict` 用的键结构，不是数据类。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「用 Pydantic `BaseModel` 子类承载，构造时会做字段类型强校验」——说明没抓住本题的分界（A）。
- 答成「用一个普通 `dict` 直接传入 `__init__`，没有任何类型声明」——说明没抓住本题的分界（C）。
- 答成「用 `dataclass(frozen=True)` 承载，构造后不可变」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0052 submit_message 的进程内互斥

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_engine | 单引擎实例同时只跑一轮（T39） | 简单 | 机制解释 | `python/engine/query_engine.py:489,500` |

**面试官提问**
`QueryEngine.submit_message` 开头为什么要有 `if self._turn_active: raise RuntimeError(...)` 这段判断？它的原文中文注释说明了什么？抛出的消息里刻意包含哪个英文词，为什么？

**参考答案要点**
代码位置 `python/engine/query_engine.py:489-514`：

```python
async def submit_message(self, prompt, options=None) -> AsyncIterator[EngineEvent]:
    """引擎内互斥入口（T39 防御纵深）。
    正常路径外层已有 SessionPool busy 表 + TurnRunner 双闸；这里挡住
    进程内 CLI REPL、旁路脚本等漏检入口，保证单引擎实例同时只跑一轮。
    消息文案含 ``busy``，经 friendly_error 会翻译为「会话正忙」。
    """
    if self._turn_active:
        raise RuntimeError(
            f"engine is busy: session {self._session.session_id} "
            "already running a turn"
        )
    self._turn_active = True
    try:
        async for event in self._submit_message_inner(prompt, options):
            yield event
    finally:
        self._turn_active = False
        from engine.resume_directive import clear_resume_directive
        clear_resume_directive()
```

要点三条：

1. **定位是第三道闸（防御纵深）**：外层已有 ① `SessionPool` 的 busy 租约表、② `TurnRunner` 的 per-session 单 turn 锁；`_turn_active` 挡的是**绕过前两者**的进程内入口——CLI REPL、旁路脚本直接拿引擎实例调用的情况。
2. **消息里刻意保留 `busy`**：因为错误统一经 `friendly_error` 翻译，含 `busy` 才能被识别并翻译成用户可读的「会话正忙」，而不是抛出一个原始英文栈。
3. **`finally` 里清 resume directive**：轮结束即清 contextvar，防止「续跑指令」泄漏到后续轮次（注释标注为「修订2（设计32）」）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的核心不是「有没有锁」，而是**为什么要三道**。单看 `submit_message` 会以为多余（外层不是有锁吗），注释把「漏检入口」说清楚了：锁的作用域不同——租约表与 TurnRunner 都在 HTTP 层之上，而进程内调用不经过 HTTP。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0053 query_loop 的参数面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | 主循环的函数契约 | 简单 | 概念确认 | `python/engine/query_loop.py:726-742` |

**面试官提问**
`python/engine/query_loop.py:726` 的函数签名中，**没有默认值、必须由调用方传入**的参数有哪些？请完整列举。

**参考答案要点**
**A、B、C、D、E、F、G**。

`query_loop.py:726-742` 的完整签名：

```python
async def query_loop(
    *,
    store: MessageStore,
    model: ModelClient,
    tools: ToolRegistry,
    prompt: PromptAssembler,
    system_prompt: str,
    abort: AbortController,
    budget: BudgetTracker,
    working: WorkingSnapshot | None = None,
    coordinator: PermissionCoordinator | None = None,
    system_breakdown: list[dict] | None = None,
    agent_mode: str = "agent",
    multi_agent: bool = False,
    include_memory_index: bool = True,
    ensure_before: Any | None = None,
) -> AsyncIterator[EngineEvent]:
```

- 必填 7 个：`store` / `model` / `tools` / `prompt` / `system_prompt` / `abort` / `budget`。
- 有默认值的 7 个：`working`（None）、`coordinator`（None）、`system_breakdown`（None）、`agent_mode`（`"agent"`）、`multi_agent`（False）、`include_memory_index`（True）、`ensure_before`（None）。
- 全部是 **keyword-only**（`*` 之后），调用方必须写参数名。

**深化讲解**（面试官参考，不要求候选人全说）
H 是干扰项：`coordinator` 默认 `None`，而 `query_loop.py:756-765` 明确写了「仅当会话有 coordinator（真实会话）时执行；本地/无会话路径跳过」——说明无 coordinator 是被支持的一等路径（CLI / 测试 / 本地）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0054 早读工具的开关与默认值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | 只读工具提前执行（early readonly） | 简单 | 概念确认 | `python/engine/query_loop.py:112-115` |

**面试官提问**
`early_readonly_tools_enabled()` 的默认行为与环境变量覆盖方式是：

**参考答案要点**
**正解：B（**默认开**；`XEYO_EARLY_READONLY_TOOLS=0` 关闭；真值集合为 `("1","true","yes","on")`）**
`query_loop.py:112-115`：

```python
def early_readonly_tools_enabled() -> bool:
    """默认开；``XEYO_EARLY_READONLY_TOOLS=0`` 关闭。"""
    raw = os.environ.get("XEYO_EARLY_READONLY_TOOLS", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")
```

默认值字面量是 `"1"`，即**缺省开启**；判定用 `.strip().lower()` 后再做集合匹配，所以 `" TRUE "` 这类写法也能识别。

**深化讲解**（面试官参考，不要求候选人全说）
注意「默认开」这一选择与 XEYO 的整体取向一致：只读工具（Glob / Grep / Read 等）提前并发执行可以显著缩短首字延迟，而它们不改变工作区状态，风险低。风险控制不放在开关上，而放在 `_eligible_for_early` 的逐条准入（见 0058）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「默认关；`XEYO_EARLY_READONLY_TOOLS=1` 开启」——说明没抓住本题的分界（A）。
- 答成「默认开；`XEYO_EARLY_READONLY_TOOLS=off` 关闭；真值只认 `"on"`」——说明没抓住本题的分界（C）。
- 答成「只能由配置文件控制，不受环境变量影响」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0055 收尾窗剩余配额

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | forced_wrap_up 期的工具配额 | 简单 | 概念确认 | `python/engine/query_loop.py:118-129` |

**面试官提问**
`wrap_quota_from_env()` 决定进入收尾窗后**还能调用几次工具**。它的默认值、环境变量名，以及取值为 `0` 时的语义是：

**参考答案要点**
**正解：B（默认 3；`XEYO_WRAP_QUOTA`；0 = 维持旧的「一开闸全禁」语义）**
`query_loop.py:118-129`：

```python
def wrap_quota_from_env(default: int = 3) -> int:
    """收尾窗（forced_wrap_up）的剩余工具配额默认值。

    ``XEYO_WRAP_QUOTA`` 逗号无关整数覆盖；0 = 维持旧"一开闸全禁"语义。
    """
    raw = os.environ.get("XEYO_WRAP_QUOTA", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return default
    return default
```

三个细节：① 默认 `3`；② 环境变量是 `XEYO_WRAP_QUOTA`（不是 `_MAX`）；③ 解析失败（非整数）**回落到 default**，不是回落 0；④ `max(0, int(raw))` 保证非负。

**深化讲解**（面试官参考，不要求候选人全说）
「0 = 维持旧的全禁语义」是本题关键。注释里写的旧语义是「一开闸全禁」——即早期实现在进收尾窗时把工具**全部禁掉**；现在改为「配额内仍可用」，因为「收尾恰好最需要落盘」（这条动机在 `query_loop.py:786-789` 的注释里写得很直白）。把配额设为 0 就是退回到旧行为，而不是「无限」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「默认 0；`XEYO_WRAP_QUOTA`；0 = 不限制」——说明没抓住本题的分界（A）。
- 答成「默认 5；`XEYO_WRAP_QUOTA`；0 = 立即中止回合」——说明没抓住本题的分界（C）。
- 答成「默认 3；`XEYO_WRAP_QUOTA_MAX`；0 = 维持旧的「全禁」语义」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0056 tool_call.begin 的参数摘要

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | 事件流里的参数摘要（T13） | 简单 | 机制解释 | `python/engine/query_loop.py:100-109` |

**面试官提问**
`_tool_input_summary()` 对工具入参做了哪些处理？为什么它不直接 `str(input)`？截断长度是多少、截断后加什么后缀？

**参考答案要点**
`query_loop.py:100-109`：

```python
def _tool_input_summary(input: dict[str, Any]) -> str:
    """tool_call.begin 参数摘要：压成单行 json，截断到 200 字符（T13）。"""
    try:
        raw = json.dumps(input, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raw = str(input)
    raw = raw.replace("\n", " ")
    if len(raw) <= 200:
        return raw
    return raw[:200] + "…"
```

处理链三步：
1. **优先 JSON 化**：`json.dumps(..., ensure_ascii=False, separators=(",", ":"))` —— 不转义非 ASCII（中文原样保留，便于阅读），`separators` 去掉了默认的空格，压到最紧凑；
2. **降级**：JSON 化失败（不可序列化对象）时退回 `str(input)`，保证函数**永不抛异常**；
3. **单行化 + 截断**：把换行替换成空格（事件帧是单行 JSON，内嵌换行会破坏可读性），超过 200 字符截断并追加 `…`（U+2026，非三个点）。

**深化讲解**（面试官参考，不要求候选人全说）
为什么不能只写 `str(input)`：① 事件流（SSE）里的 `tool_call.begin` 帧携带这个摘要，前端/日志都要消费，必须是**稳定的单行文本**；② `ensure_ascii=False` 让中文参数不变成 `\uXXXX`，用户能看懂「读的是哪个文件」；③ 「永不抛异常」是事件生产的硬约束——参数摘要失败不能导致整个事件流断掉。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0057 早读黑名单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | `_EARLY_BLOCKLIST` | 简单 | 概念确认 | `python/engine/query_loop.py:93` |

**面试官提问**
即使某工具本身是只读的，`_EARLY_BLOCKLIST` 中的工具也**永不提前执行**。请写出这份黑名单的完整成员。

**参考答案要点**
**A、B、C、D**。

`query_loop.py:93`：

```python
_EARLY_BLOCKLIST = frozenset({"ExitPlanMode", "AskUserQuestion", "AskUser", "Agent"})
```

**深化讲解**（面试官参考，不要求候选人全说）
为什么这四类被单独拎出来：

- `ExitPlanMode` / `AskUserQuestion` / `AskUser` 三者都是**交互型工具**——它们会阻塞等待人类输入，提前执行等于在用户还没看到上下文时就弹窗，且 `_eligible_for_early` 里本来就要求 `decision == ALLOW`（交互工具通常走 ASK，见 0058），黑名单是**第二道冗余保险**；
- `Agent` 是**子代理派发**——提前执行会让子代理在「首轮文本还没产出」时就并行开跑，既不可控也放大成本，且它与 `_EARLY_BLOCKLIST` 的「并发安全」判定在语义上冲突（子代理自身内部又是一个主循环）。

`Bash` 与 `TodoWrite` 不在黑名单，但它们会因为「非只读」「非并发安全」在 `_eligible_for_early` 被否掉——**黑名单与准入条件是两条独立的防线**。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`Bash`」——说明没抓住本题的分界（E）。
- 答成「`TodoWrite`」——说明没抓住本题的分界（F）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0058 早读的准入条件

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | `_eligible_for_early` 判定链 | 简单 | 机制解释 | `python/engine/query_loop.py:155-176` |

**面试官提问**
一个工具调用要被提前（early）执行，必须同时满足哪些条件？请按源码顺序列出，并说明为什么最后一条要用 `evaluate_policy(...) == ALLOW` 而**不是** `!= DENY`。

**参考答案要点**
`query_loop.py:155-176`：

```python
def _eligible_for_early(registry, tu, *, forced_wrap_up) -> bool:
    """只读 + 并发安全 + policy ALLOW；ASK/写/外发/交互一律不提前。"""
    if forced_wrap_up:
        return False
    name = (tu.name or "").strip()
    if not name or name in _EARLY_BLOCKLIST:
        return False
    tool = registry.get(name)
    if tool is None:
        return False
    if not tool_flag(tool, "is_concurrency_safe", default=False):
        return False
    if not tool_flag(tool, "is_read_only", default=False):
        return False
    raw_input = tu.input if isinstance(tu.input, dict) else {}
    decision = evaluate_policy(name, raw_input, cwd=registry.cwd, tool=tool)
    return decision.decision == PermissionDecision.ALLOW
```

条件链（全部满足才为真）：
1. **不在收尾窗**：`forced_wrap_up` 为真 → 直接 False；
2. **工具名有效**：非空 `strip()` 后且不在 `_EARLY_BLOCKLIST`；
3. **工具已注册**：`registry.get(name)` 非 None；
4. **并发安全**：`is_concurrency_safe`（`default=False` —— 属性缺失即视为不安全）；
5. **只读**：`is_read_only`（同样 `default=False`）；
6. **策略判定为 ALLOW**：`evaluate_policy(...)` 的 `decision` **严格等于** `PermissionDecision.ALLOW`。

**为什么要严格等于 ALLOW**：三种决策是 `ALLOW / ASK / DENY`。若写成 `!= DENY`，那么 `ASK` 的工具就会被提前执行——而 `ASK` 的本质是「**必须等人类点头**」。提前执行一个 `ASK` 工具意味着：模型和用户在对话框弹出之前就看到了它的结果，用户实际上被剥夺了否决权。所以注释写「ASK/写/外发/交互一律不提前」。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的关键在最后一条的不等式方向。「只读」是**工具自身的属性**，而「ASK」是**这次调用的策略裁决结果**——同一个只读工具，不同入参可能触发不同裁决（例如读工作区外的文件被要求确认）。准入必须同时看属性与本次裁决。

`default=False` 的两处也值得注意：这是**fail-closed** 的默认——没声明就是不安全。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0059 引擎默认轮次与工具预算

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | 默认硬上限常量 | 简单 | 概念确认 | `python/engine/budget.py:19,24` |

**面试官提问**
`python/engine/budget.py` 中，一个回合默认的最大轮次数与最大工具调用数分别是：

**参考答案要点**
**正解：B（`DEFAULT_MAX_TURNS = 256` / `DEFAULT_MAX_TOOL_CALLING = 64`）**
`budget.py:19`：`DEFAULT_MAX_TURNS = 256`
`budget.py:24`：`DEFAULT_MAX_TOOL_CALLING = 64`

即「轮次宽松（256）、工具调用严格（64）」——一个回合允许很多次模型往返，但工具调用总次数收紧。这两个数字可通过 `max_turns_from_env`（`budget.py:58`）与 `max_tool_calling_from_env`（`budget.py:63`）覆盖。

**深化讲解**（面试官参考，不要求候选人全说）
容易混的对照表（别混）：

| 常量 | 值 | 位置 | 作用域 |
|---|---|---|---|
| `DEFAULT_MAX_TURNS` | 256 | `budget.py:19` | 主回合轮次 |
| `DEFAULT_MAX_TOOL_CALLING` | 64 | `budget.py:24` | 主回合工具调用 |
| `DEFAULT_SUB_MAX_TURNS` | 32 | `subagent_runner.py:23` | 子代理（可写）轮次 |
| `DEFAULT_SUB_MAX_TOOL_CALLING` | 64 | `subagent_runner.py:24` | 子代理（可写）工具调用 |
| `DEFAULT_SUB_RO_MAX_TURNS` | 16 | `subagent_runner.py:25` | 子代理（只读）轮次 |
| `DEFAULT_SUB_RO_MAX_TOOL_CALLING` | 32 | `subagent_runner.py:26` | 子代理（只读）工具调用 |

D 选项正是把「子代理可写档」的 32/64 错当成主回合。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`DEFAULT_MAX_TURNS = 64` / `DEFAULT_MAX_TOOL_CALLING = 256`」——说明没抓住本题的分界（A）。
- 答成「`DEFAULT_MAX_TURNS = 100` / `DEFAULT_MAX_TOOL_CALLING = 100`」——说明没抓住本题的分界（C）。
- 答成「`DEFAULT_MAX_TURNS = 32` / `DEFAULT_MAX_TOOL_CALLING = 64`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0060 grace turns 与工具封顶连续计数

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | 软上限到硬停之间的缓冲 | 简单 | 机制解释 | `python/engine/budget.py:25,30-34` |

**面试官提问**
解释 `budget.py` 里 `MAX_GRACE_TURNS = 3` 和 `MAX_TOOL_CAP_STREAK = 2` 各自控制什么，并说明 `MAX_TURN_WARNING` / `MAX_TOOL_WARNING` / `WALL_STOP_NOTICE` 三条文案分别对应哪个触发条件。

**参考答案要点**
`budget.py:25,30-34`：

```python
MAX_GRACE_TURNS = 3
MAX_TOOL_CAP_STREAK = 2
MAX_TURN_WARNING = "回合数已接近上限。"
MAX_TOOL_WARNING = "工具调用数已接近上限。"
WALL_STOP_NOTICE = "时间预算已到上限（已进入收尾窗）。"
```

- **`MAX_GRACE_TURNS = 3`**：轮次达到软上限后，仍允许的**宽限轮数**。宽限不是「免费」——它对应 `_start_grace(reason)`（`budget.py:204`）与 `grace_turns_remaining`（`budget.py:354`），耗尽后才进入硬停（`hard_stop_reason`，`budget.py:349`）。
- **`MAX_TOOL_CAP_STREAK = 2`**：工具调用触顶后允许的**连续触顶次数**，用于区分「偶发触顶」与「持续触顶」，避免一次越界就直接硬停。
- 文案对应关系：
  - `MAX_TURN_WARNING` → 轮次接近上限；
  - `MAX_TOOL_WARNING` → 工具调用数接近上限；
  - `WALL_STOP_NOTICE` → **墙钟**时间预算到顶且已进入收尾窗（注意它说的是「已进入收尾窗」，对应 `set_wall_deadline` / `arm_wall_stop` / `check_wall_deadline`，`budget.py:148,160,168`）。

**深化讲解**（面试官参考，不要求候选人全说）
这三条文案的存在本身就是设计约束的体现：XEYO 的理念要求模型可见文本**只承载状态/事实**。这三句都是**纯事实陈述**——「回合数已接近上限」，没有「请尽快收尾」「你应该……」的劝告成分。对照 0092 讨论的收尾窗机制，可以看清「预算耗尽」这件事的表达方式是「告知事实 + 收尾窗配额 + 缺口清单」，而不是「催促」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0061 重复调用守卫的递进阈值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_guard | 重复调用提示的档位 | 简单 | 概念确认 | `python/engine/repeat_guard.py:39` |

**面试官提问**
`RepeatCallGuard` 采用「递进建议制」。它的默认档位阈值 `DEFAULT_ADVICE_LEVELS` 是：

**参考答案要点**
**正解：C（`(3, 5, 8)`）**
`repeat_guard.py:39`：`DEFAULT_ADVICE_LEVELS = (3, 5, 8)`。

含义：同一个「调用签名」被重复发起达到 3、5、8 次时，分别跨过一档，触发对应强度的提示文本。注意 `query_loop.py:772-774` 的注释解释了生命周期：

```python
# 重复调用守卫（T6 递进建议制：阈值 [3,5,8]，只提醒不拒执行；
# 每次 submit 新建即用户输入级重置）。
repeat_guard = RepeatCallGuard()
```

**关键点两条**：
1. **「只提醒不拒执行」**——这是「建议制」的定义；
2. **每次 `submit` 新建**——计数器在**用户输入级**重置。也就是说，跨用户轮次不会累积（同一用户回合内才累积），避免把「用户让我再查一次」误判成模型的重复行为。

**深化讲解**（面试官参考，不要求候选人全说）
阈值设计成「3 → 5 → 8」而不是「3 → 4 → 5」，是刻意的**递增间隔**：如果模型是在做有意义的迭代，重复次数通常不会持续线性增长；间隔拉大可以降低对「正在正常工作」的打扰。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`(1, 2, 3)`」——说明没抓住本题的分界（A）。
- 答成「`(2, 4, 6)`」——说明没抓住本题的分界（B）。
- 答成「`(5, 10, 20)`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0062 守卫是否真的会拦截

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_guard | 动作常量与真实语义 | 简单 | 概念确认 | `python/engine/repeat_guard.py:41-45` |

**面试官提问**
判断：「当重复调用次数达到最高档阈值时，`RepeatCallGuard` 会返回 BLOCK 动作，引擎据此拒绝执行该次工具调用。」

这句话是否正确？请给出源码依据。

**参考答案要点**
**错误**。

`repeat_guard.py:41-45`：

```python
ACTION_RUN = "run"
ACTION_ADVICE = "advice"
ACTION_HINT = ACTION_ADVICE
ACTION_BLOCK = ACTION_ADVICE
```

`ACTION_BLOCK` 被**直接别名到 `ACTION_ADVICE`**——也就是说，即使代码里某处返回了「BLOCK」，它的字符串值仍是 `"advice"`。**守卫在实现上不存在独立的拦截动作**，所谓最高档也只是提示强度更高。这与 `query_loop.py:772-773` 注释的「只提醒不拒执行」完全一致。

需要注意的边界：**「不拦截」不等于「没有后果」**——提示文本会经 T_now 块进入模型上下文（影响后续决策），但引擎不会因为重复而拒绝执行工具。真正会「拒绝执行」的是权限层（ASK/DENY）与预算层（配额尽）。

**深化讲解**（面试官参考，不要求候选人全说）
这是一道典型的「命名误导」题。`ACTION_BLOCK` 这个名字会让人以为存在硬拦截，但别名赋值把语义钉死成 advice。识别这类陷阱要**看赋值而不是看名字**——这也是 XEYO 代码里 `ACTION_HINT = ACTION_ADVICE` 同样手法的原因（历史动作名保留，语义统一到一处）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0063 零命中提示的触发次数

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_guard | `ZERO_HIT_ADVICE_AT` | 简单 | 概念确认 | `python/engine/repeat_guard.py:288` |

**面试官提问**
`ZERO_HIT_ADVICE_AT = 2` 在 `zero_hit` 机制里的含义是：

**参考答案要点**
**正解：B（**不同查询累计空结果达到 2 起后**追加中立提示）**
`repeat_guard.py:288`：`ZERO_HIT_ADVICE_AT = 2`。

对应的装配点在 `query_loop.py:782-785`：

```python
# 零命中前提复核：不同查询累计空结果 ≥2 起追加中立提示。
zero_hit_tracker = ZeroHitTracker()
# tu.id → 该调用结果上要追加的零命中提示文本。
zero_hit_advice: dict[str, str] = {}
```

三个限定词必须答对：**不同查询**（不是同一查询重复）、**累计**（不是连续）、**≥2 起**（达到 2 触发）。

**深化讲解**（面试官参考，不要求候选人全说）
为什么是「不同查询」：单次空结果很正常（文件确实不存在、模式确实没匹配）。但**多个不同的查询都空**，才构成「我假设的前提可能整体不成立」的信号——这时追加一条**中立提示**（不是「你应该换个思路」，而是类似「多次查询均为空」的事实陈述）。

「中立」二字很关键：按 XEYO 的信息纪律，这条提示也不能写成建议。它属于「以事实形式呈现」的那类注入。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「单次搜索返回 0 条结果时立即提示」——说明没抓住本题的分界（A）。
- 答成「连续 2 轮没有任何工具调用时提示」——说明没抓住本题的分界（C）。
- 答成「同一查询重复 2 次后提示」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0064 搜索工具的折叠默认口径

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_guard | 搜索类工具的等价判定默认值 | 简单 | 机制解释 | `python/engine/repeat_guard.py:109-124` |

**面试官提问**
`repeat_guard.py` 里 `SEARCH_TOOLS` 包含哪些工具？`_GREP_DEFAULT_OUTPUT_MODE` 的值是什么、它在等价判定中起什么作用？`_SEARCH_SEMANTIC_FIELDS` 与 `_PATTERN_WRAP_QUOTES` 各自解决什么问题？

**参考答案要点**
`repeat_guard.py:109-124`：

```python
SEARCH_TOOLS = frozenset({"Grep", "Glob"})
_GREP_DEFAULT_OUTPUT_MODE = "files_with_matches"
_SEARCH_SEMANTIC_FIELDS = (...)
_PATTERN_WRAP_QUOTES = "\"'`“”‘’"
```

- **`SEARCH_TOOLS = {"Grep","Glob"}`**：这两个是「搜索类」工具，走**语义等价**判定，而不是字节等价。
- **`_GREP_DEFAULT_OUTPUT_MODE = "files_with_matches"`**：Grep 在**未显式指定** `output_mode` 时，引擎按 `files_with_matches` 处理。作用：让「`Grep(pattern=X)`」与「`Grep(pattern=X, output_mode="files_with_matches")`」被判为**同一个调用签名**——否则模型换个写法就能绕过重复计数。
- **`_SEARCH_SEMANTIC_FIELDS`**：搜索类工具里**参与语义等价的字段白名单**。含义是「只有这些字段的取值差异才算不同查询」，其余字段（如行号、上下文行数等展示参数）不参与判等，避免把「同一搜索的两种展示形态」算成两次。
- **`_PATTERN_WRAP_QUOTES`**（含 `"` `'` `` ` `` 以及中英文弯引号 `“”‘’`）：判定前**剥掉模式外层的包裹引号**。解决的是「`Grep(pattern="foo")` 与 `Grep(pattern='"foo"')`」在语义上是同一搜索、但在字符串上不同的问题——尤其常见于 Windows/PowerShell 语境下模型习惯性给参数加引号。

**深化讲解**（面试官参考，不要求候选人全说）
这四项合起来说明一件事：XEYO 的重复判定不是 `hash(json.dumps(input))` 这种朴素做法，而是**先做语义归一化再比对**。这是一个「判定口径」类机制，它的反面教材是「模型换个等价写法就把计数器清空」——那会让守卫形同虚设。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0065 终态 turn 的保留数量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | 内存中保留的终态 turn | 简单 | 概念确认 | `python/engine/turn_runner.py:27,186-198` |

**面试官提问**
`TurnRunner` 会把已终结（terminal）的 turn 保留在内存中供客户端 reattach 重放。保留上限 `_MAX_TERMINAL_TURNS` 是多少？为什么「丢弃旧终态不影响恢复」？

**参考答案要点**
**正解：B（**32**；因为**快照已落盘**，frames 只用于重放）**
`turn_runner.py:27`：`_MAX_TERMINAL_TURNS = 32`
`turn_runner.py:186-198`：

```python
def _evict_terminal_turns_locked(self) -> None:
    """调用方必须持有 _tlock。终态 turn 只保留最近 N 个会话的，控内存。

    frames 只用于 reattach 重放；快照已落盘，丢弃旧终态不影响恢复。
    """
    terminal = [(sid, t) for sid, t in self._turns.items() if t.done.is_set()]
    if len(terminal) <= _MAX_TERMINAL_TURNS:
        return
    terminal.sort(key=lambda st: st[1].started_at)
    for sid, _t in terminal[: len(terminal) - _MAX_TERMINAL_TURNS]:
        self._turns.pop(sid, None)
```

**为什么安全**：`frames`（事件帧列表）的唯一用途是**客户端 reattach 时重放**；而「这一轮发生了什么」的权威记录已经**落盘**（`_persist`，`turn_runner.py:369`；快照层见 `turn_snapshot.py`）。所以驱逐只影响「能不能重放最近的历史帧」，不影响「能不能恢复状态」。

**深化讲解**（面试官参考，不要求候选人全说）
注意驱逐的两个细节：① 只统计 `done.is_set()` 的 turn（运行中的永不驱逐）；② 排序键是 `started_at`（**开始时间**，不是结束时间），按开始时间从旧到新丢弃。用开始时间而非结束时间是个保守选择——长回合不会被误认为「刚结束所以还新鲜」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「8；因为丢弃的帧会从磁盘重新生成」——说明没抓住本题的分界（A）。
- 答成「64；因为超过 64 个会话的 turn 一定已经过期」——说明没抓住本题的分界（C）。
- 答成「没有上限，靠 GC 回收」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0066 帧缓冲的双上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | `_MAX_BUFFERED_FRAMES` / `_MAX_BUFFERED_BYTES` | 简单 | 机制解释 | `python/engine/turn_runner.py:21,24` |

**面试官提问**
`TurnRunner` 对单个 turn 的事件帧缓冲设了**两个**上限，分别是什么值？为什么要同时设「帧数」和「字节数」两个维度？

**参考答案要点**
`turn_runner.py:21,24`：

```python
_MAX_BUFFERED_FRAMES = 4000
_MAX_BUFFERED_BYTES = 8 * 1024 * 1024
```

即 **4000 帧** 与 **8 MiB**。

**为什么两个维度都要**：
- 只限帧数：一帧可以是一句 delta 文本（几十字节），也可以是一次工具结果的全量内容（可能几百 KB 甚至更大）。4000 帧在「小帧」场景下只有几十 KB（浪费额度），在「大帧」场景下可能是 GB 级（内存炸掉）。
- 只限字节：如果帧极小（例如每帧几十字节的心跳/进度），字节上限很晚才触发，但**帧对象本身有开销**（元组 + 字符串对象头 + 列表节点），4000 → 数十万帧时 Python 对象开销本身就不可忽略。
- 两个维度取**先到者**：`turn_runner.py:211-218` 用 `or` 连接，任一超限就进入裁剪循环。

**深化讲解**（面试官参考，不要求候选人全说）
这是一道「为什么两个常量而不是一个」的设计题。答案要落到「帧大小分布不确定」这个现实上——事件流里的帧尺寸方差极大（delta 文本 vs 工具结果），单一维度必然在某一段分布上失效。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0067 busy 租约心跳的间隔

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | 长回合的租约续期 | 简单 | 概念确认 | `python/engine/turn_runner.py:221-229` |

**面试官提问**
`_run_producer` 中向 `SessionPool` 续期 busy 租约（`touch_busy`）的节流间隔是多少？为什么是「逐帧比较」而不是「启动一个定时器」？

**参考答案要点**
**正解：B（**每 ≥30 秒续期一次**，逐帧比较；避免每个 delta 帧都去抢 pool 锁）**
`turn_runner.py:221-229`：

```python
# busy 租约心跳：每 ≥30s 刷一次，防止长回合被 stale 回收。
# 逐帧节流，避免每 delta 都抢 pool 锁。
now = time.monotonic()
if now - last_touch >= 30.0:
    last_touch = now
    try:
        self._pool.touch_busy(det.session_id)
    except Exception:
        pass
```

三个要点：
1. 阈值 **30.0 秒**，用 `time.monotonic()`（单调时钟，不受系统时间调整影响）；
2. **逐帧节流**：在已有的「消费事件帧」循环里顺带判断，不需要额外协程/定时器；
3. 外层 `try/except: pass` —— 续期失败**不中断回合**（租约回收是外层池的职责，turn 本体不该因为续期失败而崩）。

**深化讲解**（面试官参考，不要求候选人全说）
为什么不用定时器：`asyncio` 定时器需要额外 task 生命周期管理（创建、取消、异常吞掉），而事件流本身就是高频的「心跳源」。用「自然节拍」做节流是更省的实现——代价是**如果事件流长时间无帧，心跳也会停**。这是这道题最值得注意的隐含约束：该实现的正确性依赖「长回合必然持续产帧」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「每帧都续期」——说明没抓住本题的分界（A）。
- 答成「每 5 分钟续期一次，由 `asyncio.create_task` 定时唤醒」——说明没抓住本题的分界（C）。
- 答成「只在 `permission_pending` 时续期」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0068 TurnSnapshot 的三个入口函数

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_snapshot | 回合快照的水化/落盘/清除 | 简单 | 机制解释 | `python/turn_snapshot.py:78,122,142`（实际路径 `python/engine/turn_snapshot.py`） |

**面试官提问**
`python/engine/turn_snapshot.py` 暴露了 `hydrate(session_id)` / `flush(snap)` / `clear(session_id)` 三个函数。分别说出它们的签名与职责。另外，`list_recoverable()` 与 `mark_crashed_as_recovery(snap)` 是给谁用的？

**参考答案要点**
实测签名（`python/engine/turn_snapshot.py`）：

```python
def hydrate(session_id: str) -> TurnSnapshot | None:      # :78
def flush(snap: TurnSnapshot) -> None:                     # :122
def clear(session_id: str) -> None:                        # :142
def list_recoverable() -> list[TurnSnapshot]:              # :151
def mark_crashed_as_recovery(snap: TurnSnapshot) -> TurnSnapshot:  # :167
```

- `hydrate(session_id) -> TurnSnapshot | None`：按会话 id 从磁盘读回落盘快照；不存在时返回 `None`（用 Optional 表达「没有」而不是抛异常）。
- `flush(snap) -> None`：把当前快照写盘。
- `clear(session_id) -> None`：清除该会话的快照（回合正常结束时）。
- `list_recoverable()` / `mark_crashed_as_recovery(snap)`：**恢复路径专用**——前者枚举「可恢复」的快照（正常结束时会 `clear`，所以留下的就暗示未正常结束）；后者把快照标记为「崩溃待恢复」形态再交给上层。

路径助手 `path_for(session_id)`（`:74`）与 `_sessions_dir()`（`:54`）说明快照落在会话目录下，`_safe_name(session_id)`（`:61`）负责把 session id 转成安全文件名。

**深化讲解**（面试官参考，不要求候选人全说）
`hydrate` 返回 `None` 而非抛异常，是引擎这类代码的通用约定：**「不存在」是正常状态**（首次会话、已清理的回合），只有真正的 IO 错误才该是异常。对照 `turn_runner.py:369` 的 `_persist`——落盘与内存状态是两套，`clear` 与 `flush` 的配对使用保证了「正常运行不留恢复垃圾」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0069 会话标题的字节上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | title | 标题长度与默认值 | 简单 | 概念确认 | `python/engine/title.py:25,27,46` |

**面试官提问**
`title.py` 中标题的默认值与长度限制是：

**参考答案要点**
**正解：B（**`DEFAULT_TITLE = "新会话"`，上限 `MAX_TITLE_BYTES = 96`（字节，非字符）**）**
`title.py:25,27`：

```python
MAX_TITLE_BYTES = 96
DEFAULT_TITLE = "新会话"
```

并且 `title.py:46` 有专门的截断函数：

```python
def _byte_safe_truncate(text: str, limit: int = MAX_TITLE_BYTES) -> str:
```

**「byte-safe」是本题的关键**：上限单位是**字节**，而标题通常是「中英混排」。一个中文字符在 UTF-8 下占 3 字节，所以 96 字节 ≈ 32 个纯中文字符，但如果按「字符数 ≤ 96」来切，一个含 96 个汉字的标题会是 **288 字节**，直接超限 3 倍。

`_byte_safe_truncate` 的存在说明实现者踩过这个坑：不能简单 `text[:96]`（按字符切），否则既可能超字节预算，也可能把多字节字符**切成半个**（产生乱码）；正确做法是按字节裁剪并保证不切断码点。

**深化讲解**（面试官参考，不要求候选人全说）
D 选项是最常见的误读（把 `_BYTES` 当字符数）。凡是常量名以 `_BYTES` 结尾，一律按 UTF-8 字节理解——这在 XEYO 里不是孤例（`_MAX_BUFFERED_BYTES`、`MAX_TITLE_BYTES`）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`DEFAULT_TITLE = "Untitled"`，上限 64 字符」——说明没抓住本题的分界（A）。
- 答成「`DEFAULT_TITLE = "New Chat"`，上限 128 字节」——说明没抓住本题的分界（C）。
- 答成「`DEFAULT_TITLE = "新会话"`，上限 96 个字符」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0070 子代理的默认预算常量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | subagent_runner | 子代理四档默认预算 | 简单 | 概念确认 | `python/engine/subagent_runner.py:23-26` |

**面试官提问**
请说出 `subagent_runner.py` 的模块级常量及其取值。

**参考答案要点**
**A、B、C、D**。

`subagent_runner.py:23-26`：

```python
DEFAULT_SUB_MAX_TURNS = 32
DEFAULT_SUB_MAX_TOOL_CALLING = 64
DEFAULT_SUB_RO_MAX_TURNS = 16
DEFAULT_SUB_RO_MAX_TOOL_CALLING = 32
```

**E 是错的**：follow-up 的 12 这个数字**不是模块级常量**，而是 `_followup_max_turns()`（`subagent_runner.py:52-54`）的**函数内默认参数值**：

```python
def _followup_max_turns() -> int:
    """follow-up 续跑轮次上限（省钱：短预算，不复用首轮大预算）。"""
    return _env_int("XEYO_SUB_FOLLOWUP_MAX_TURNS", 12)
```

命名规律也值得记：`SUB_RO_*` 里的 **RO = Read-Only**，只读工人拿到更低的上限（16/32 vs 32/64），直接对应注释里的「省钱」。判据是 `scope_paths` 是否为空（见 `subagent_budgets_for_scope`，`:39-49`）。

**深化讲解**（面试官参考，不要求候选人全说）
这题考「常量 vs 函数默认值」的区分，以及 `RO` 缩写的展开。E 的数值 12 是真的、环境变量名也是真的——但它不是常量，这种「数值真、载体假」的选项是最容易误选的。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`DEFAULT_SUB_FOLLOWUP_MAX_TURNS = 12`」——说明没抓住本题的分界（E）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0071 follow-up 的短预算与次数上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | subagent_runner | follow-up 续跑预算 | 简单 | 机制解释 | `python/engine/subagent_runner.py:52-68` |

**面试官提问**
子代理的 follow-up（追加追问）为什么**不复用首轮的预算**？它的三个上限分别是什么（含环境变量名与默认值）？`_followup_user_text()` 拼出的触发消息长什么样、为什么要复用 `[Resume]` 契约？

**参考答案要点**
`subagent_runner.py:52-68`：

```python
def _followup_max_turns() -> int:
    """follow-up 续跑轮次上限（省钱：短预算，不复用首轮大预算）。"""
    return _env_int("XEYO_SUB_FOLLOWUP_MAX_TURNS", 12)

def _followup_max_tool_calling() -> int:
    return _env_int("XEYO_SUB_FOLLOWUP_MAX_TOOL_CALLING", 24)

def _followup_limit() -> int:
    """每 agent 的 follow-up 循环次数上限（防刷）。"""
    return _env_int("XEYO_SUB_FOLLOWUP_LIMIT", 3)

def _followup_user_text(text: str) -> str:
    """follow-up 在侧链里的触发消息：复用 [Resume] 契约 + 真实 follow-up 文本。"""
    return f"[Resume] Continue.\n\nUser follow-up:\n{(text or '').strip()}"
```

三个上限：

| 项 | 环境变量 | 默认值 | 语义 |
|---|---|---|---|
| 轮次 | `XEYO_SUB_FOLLOWUP_MAX_TURNS` | 12 | 单次 follow-up 的模型往返上限 |
| 工具调用 | `XEYO_SUB_FOLLOWUP_MAX_TOOL_CALLING` | 24 | 单次 follow-up 的工具调用上限 |
| 次数 | `XEYO_SUB_FOLLOWUP_LIMIT` | 3 | **每个 agent** 能接受几次 follow-up（防刷） |

**为什么短预算**：注释写得很直接——「省钱：短预算，不复用首轮大预算」。follow-up 的语义是「补充追问」，正常情况只需几轮就能答完；沿用首轮的 32/64 会让「反复追问」的成本线性放大。加上 `_followup_limit` 的次数上限，形成「每次短 + 总次数少」的双重约束。

**复用 `[Resume]` 契约的原因**：`[Resume]` 是引擎已有的「续跑」信号标识（与 `engine/resume_directive.py` 同一契约）。侧链里的 follow-up 本质上就是「让这个已经停下的子代理继续跑」，走同一个可识别的标记，可以让引擎的续跑逻辑（含 T_now 的 resume 块）统一处理，不必为 follow-up 再开一条平行通道。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0072 goal 的轮次硬顶

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | goal_state | `GOAL_ROUND_CAP` | 简单 | 概念确认 | `python/engine/goal_state.py:66,172` |

**面试官提问**
`goal_state.py` 里 `GOAL_ROUND_CAP = 32` 的含义，以及 `resolved_max_rounds(goal, default_cap=GOAL_ROUND_CAP)` 的作用是：

**参考答案要点**
**正解：B（**一个 goal 的默认轮次上限是 32；`resolved_max_rounds` 用 goal 自身的设置覆盖这个默认值**）**
`goal_state.py:66`：`GOAL_ROUND_CAP = 32`
`goal_state.py:172`：`def resolved_max_rounds(goal: Goal, default_cap: int = GOAL_ROUND_CAP) -> int:`

即：**32 是默认值（default_cap），不是硬编码的全部**——`resolved_max_rounds` 的存在说明存在「每个 goal 自己的 max rounds 设置」，取值的优先级是「goal 自身设置 > 默认 32」。

对照常量：goal 的**状态**枚举在 `goal_state.py:38-43`（`STATUS_ACTIVE / PAUSED / BLOCKED / COMPLETED / ABANDONED`），状态转换合法性由 `can_transition(current, target)`（`:133`）判定——这与「轮次上限」是两件不同的事，C 选项把它们混了。

**深化讲解**（面试官参考，不要求候选人全说）
本题的考点是「默认值 vs 覆盖机制」：看到 `X_CAP = 32` 就答「硬顶 32」是常见误判。有 `resolved_*(..., default_cap=X)` 这种形态的模块，几乎必然支持 per-instance 覆盖。

要区分三个容易混的量：
- **轮次**上限 → `GOAL_ROUND_CAP` / `resolved_max_rounds`；
- **状态**集合与转换 → `STATUSES` / `can_transition`；
- **完成候选** → `CANDIDATE_ACTIVE` / `CANDIDATE_TODOS_DONE` / `CANDIDATE_BATCH_AWAITING_SYNTHESIS` / `CANDIDATE_SYNTHESIS_DONE`（`:141-144`）与 `derive_candidate`（`:147`）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「一个 goal 最多允许 32 次**工具调用**」——说明没抓住本题的分界（A）。
- 答成「goal 状态最多只能转换 32 次」——说明没抓住本题的分界（C）。
- 答成「一个 goal 最多派生 32 个候选完成信号」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0073 multi_agent 开关到底改变了什么

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | `multi_agent` 参数语义 | 中等 | 机制解释 | `python/engine/query_loop.py:748-749` |

**面试官提问**
`query_loop(..., multi_agent: bool = False)` 打开时具体做了什么？请把「做了」和「**没做**」都说清楚。关闭时 `Agent` 工具还能用吗？

**参考答案要点**
`query_loop.py:748-749`（参数文档字符串原文）：

```
``multi_agent``：Composer chip。True 时在 T_now 追加软提示，偏向使用 Agent；
不裁剪工具表、不拦截收尾。关闭时 Agent 工具仍可用，模型可主动 spawn。
```

拆成四条：

| 维度 | `multi_agent=True` | `multi_agent=False` |
|---|---|---|
| T_now 注入 | 追加一条**软提示**，内容偏向让模型使用 `Agent` | 不追加 |
| 工具表 | **不裁剪**（`Agent` 本来就在表里） | 不裁剪 |
| 收尾行为 | **不拦截**（不会因为「多代理」而改变 wrap 语义） | 不拦截 |
| `Agent` 可用性 | 可用 | **仍可用**，模型可主动 spawn |

**关键结论**：这个开关**只影响提示，不影响能力**。它是一个「注意力倾向」旋钮，不是「功能开关」。这一点与 XEYO 的引擎铁律一致——引擎不通过裁剪工具来「引导」模型，倾向性表达只以**软提示**（事实/倾向陈述）的形式出现在 T_now 通道里。

**深化讲解**（面试官参考，不要求候选人全说）
最容易答错的是「关闭时 Agent 不可用」。源码写得很清楚：关闭只是不追加软提示，`Agent` 工具全程在工具表里。所以「我不想用它」和「它不存在」是两件事——前者靠注意力，后者靠工具表，XEYO 选择了前者。

另一处易错：以为 `multi_agent=True` 会「裁剪掉其他工具，只留 Agent」——注释明确写了不裁剪。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0074 include_memory_index 为什么子代理要传 False

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | Memory 索引注入的控制 | 中等 | 机制解释 | `python/engine/query_loop.py:751-752` |

**面试官提问**
`include_memory_index` 的默认值是 `True`，但源码注释明确说「子 Agent 应传 False」。请给出**两个**理由，并说明这个参数控制的具体是哪一块注入。

**参考答案要点**
`query_loop.py:751-752`（原文）：

```
``include_memory_index``：是否在 T_now 挂 Memory 索引。子 Agent 应传 False，
避免工人提示词被索引撑大、也避免误答 Memory。
```

**控制对象**：T_now 注入管线里是否挂载 **Memory 索引块**（`python/prompt/pre_llm_inject.py` 装配的那一类块）。

**两条理由**：

1. **撑大工人提示词**：子代理（worker）的提示词本应聚焦在「分配给你的这个子任务」上。Memory 索引是很长的一串条目（笔记标题/摘要），挂上去会让每个子代理的开场上下文显著膨胀——而子代理是**并发派发**的，膨胀成本按工人数量倍增。
2. **避免误答 Memory**：子代理不应该回答关于「长期记忆里有什么」的问题——那是主代理与 Memory 工具的职责。如果索引进上下文，工人可能把记忆条目当作任务上下文直接答复（错位回答）。

**深化讲解**（面试官参考，不要求候选人全说）
默认值选 `True` 而子代理显式传 `False`，这个「默认值 + 显式例外」的模式说明：主路径（人类会话）需要索引；派发路径不需要。值得注意的是这两个理由的性质不同——① 是**成本**（可量化），② 是**职责边界**（正确性）。后者更重要：成本可以通过截断缓解，职责错位不能。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0075 主循环的两个终止出口

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | `while True` 的退出条件 | 中等 | 概念确认 | `python/engine/query_loop.py:796-804` |

**面试官提问**
`query_loop` 的主循环是 `while True:`。请列出所有会**真正结束循环并 return**（而不是继续下一轮）的情形。

**参考答案要点**
**A、B**。

`query_loop.py:796-812`：

```python
while True:
    if abort.aborted:
        yield StoppedEvent(reason="aborted")
        return
    if not budget.prepare_next_turn():
        if forced_wrap_up:
            # 收尾调用也已消耗，仍无文本可交付 → 维持原硬停语义。
            yield StoppedEvent(reason=budget.hard_stop_reason or "max_turns")
            return
        forced_wrap_up = True
        try:
            _publish_wrap_guide(tools, _workspace_cwd_for_turn(tools), wrap_quota_left)
        except Exception:
            pass
    runtime_notice = budget.consume_runtime_notice()
```

逐项分析：

- **A 正确**：中止优先于一切。
- **B 正确**：预算耗尽的**第二次**触发才是硬停。`reason` 取 `budget.hard_stop_reason`，回落到字符串 `"max_turns"`。
- **C 错误**：这正是**收尾窗的入口**。`prepare_next_turn()` 第一次返回 False 时不退出，而是把 `forced_wrap_up` 置 True、发布收尾引导（缺口清单 + 配额），然后**继续循环**——给模型一次带配额的收尾机会。
- **D 错误**：模型无工具调用时是否结束由后续循环体逻辑决定（是否会再请求一次），本题选项中描述为「自然结束」过于笼统，且**它不在 return 点的代码位置**；本批只对 `796-804` 的两个 return 负责。真正的无工具调用收尾发生在循环体后段（`726-2000` 区间的其他分支），不属于这两个出口。
- **E 错误**：`consume_runtime_notice()` 只是**取走**一条待注入的运行时通知文本（消费即清），它的返回值进入下一轮的 T_now 装配，**与循环终止无关**。

**深化讲解**（面试官参考，不要求候选人全说）
本题的核心是「`prepare_next_turn()` 返回 False」这个**同一个条件在不同状态下语义不同**：第一次 = 进入收尾窗；第二次 = 硬停。这种「同一函数返回值 + 状态变量」决定分支的设计，是 `forced_wrap_up` 这个标志存在的全部理由。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`budget.prepare_next_turn()` 返回 False，但 `forced_wrap_up` 还是 」——说明没抓住本题的分界（C）。
- 答成「模型输出中没有工具调用 → 自然结束」——说明没抓住本题的分界（D）。
- 答成「`budget.consume_runtime_notice()` 返回了非空文本 → 结束」——说明没抓住本题的分界（E）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0076 收尾窗的进入与配额消费

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | forced_wrap_up 生命周期 | 中等 | 场景设计 | `python/engine/query_loop.py:786-791,805-812` |

**面试官提问**
场景：一次回合中，模型已经跑满了轮次预算，但还有文件没落盘。请描述从「预算耗尽」到「回合真正结束」之间，`query_loop` 做了哪些动作。`wrap_quota_left` 在哪里初始化、默认值是多少？缺口清单是谁生成的、生成失败怎么办？

**参考答案要点**
时序（`query_loop.py:786-811`）：

**① 初始化（进入主循环之前）**

```python
# max_turns / max_tool_calling 硬停前的一次性收尾放行：配额内工具仍可用
# （R3'：不再"一开闸全禁"——收尾恰好最需要落盘；配额尽才禁，文本引导收敛）。
forced_wrap_up = False
wrap_quota_left = wrap_quota_from_env()
```

`wrap_quota_left` 在**主循环外**初始化一次（`wrap_quota_from_env()` 默认返回 3，见 0055），意味着它是**整个回合共用的一份配额**，不是每轮重置。

**② 首次预算耗尽 → 进入收尾窗**

```python
if not budget.prepare_next_turn():
    if forced_wrap_up:
        yield StoppedEvent(reason=budget.hard_stop_reason or "max_turns")
        return
    forced_wrap_up = True
    try:
        _publish_wrap_guide(tools, _workspace_cwd_for_turn(tools), wrap_quota_left)
    except Exception:
        pass
```

`forced_wrap_up = True`；然后调用 `_publish_wrap_guide`。

**③ 缺口清单的生成**

`_publish_wrap_guide`（`query_loop.py:132-152`）内部：

```python
from engine.wrap_gap import build_gap_lines, compose_guide_text, publish_gap
todo_tool = tools.get("TodoWrite") if tools is not None else None
todos = todo_tool.current_todos() if todo_tool is not None else None
lines = build_gap_lines(todos, cwd)
text = compose_guide_text(quota, lines)
publish_gap(text if text.strip() else "")
```

- 数据源是 **`TodoWrite` 工具的当前清单**（`current_todos()`），不是模型的自述；
- `build_gap_lines(todos, cwd)` **stat 磁盘**核对每个声明产物的真实存在性 → 算出「缺口」；
- `compose_guide_text(quota, lines)` 把配额与缺口合并成给模型看的文本；
- 走 `publish_gap(...)` 发布到模块级槽位，由 `pre_llm_inject` 在下一轮装配成 **T_now 的 wrap_up 块**。

**④ 失败处理：fail-open**

```python
except Exception:  # noqa: BLE001 — 缺口清单只是引导增强，失败静默
    try:
        from engine.wrap_gap import publish_gap
        publish_gap("")
    except Exception:
        pass
```

两层降级：① 整个生成流程异常 → 静默；② 连「清空槽位」都失败 → 仍然静默。**设计取向明确写在注释里**：「缺口清单只是引导增强」，绝不因为它失败而挡住 wrap 主路径。

**⑤ 仍在配额内**

后续轮次里 `_eligible_for_early` 的第一条就是 `if forced_wrap_up: return False`（`query_loop.py:162-163`）——**收尾窗内不再提前执行只读工具**，把窗口完整留给落盘这类写操作。

**⑥ 二次耗尽 → 硬停**

下一轮 `prepare_next_turn()` 再返回 False 且 `forced_wrap_up` 已 True → `StoppedEvent` 并 return。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于看清「收尾」不是一刀切，而是一段**有配额、有事实清单、有降级路径**的过渡期。它直接回应了一个真实痛点：早期实现在进入收尾时把工具全禁，「收尾恰好最需要落盘」——于是模型有话说不出，回合以「文本没落盘」告终（R3' 的修正动机，见 `query_loop.py:786-788` 注释）。

另外注意**信息纪律**：`_publish_wrap_guide` 的 docstring 明确写「纯事实呈现，不裁决不拦截」——缺口清单是「Todo 声明了 X，磁盘上没有 X」这类事实，不是「你应该先去写 X」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0077 ensure_before 的时序契约

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | 首写前的 Before 快照等待 | 中等 | 机制解释 | `python/engine/query_loop.py:744-746` |

**面试官提问**
`query_loop(..., ensure_before=None)` 这个参数解决什么问题？它被 await 的时机是什么？「写工具不得越过未就绪的 Before」具体在防什么？

**参考答案要点**
`query_loop.py:744-746`（原文）：

```
``ensure_before``：可选 awaitable/callable。首个非只读工具执行前会 await，
用于让 rewind Before 快照与首轮 stream 重叠，写工具仍不得越过未就绪的 Before。
```

**解决的问题**：**延迟与正确性的冲突**。

- 如果「先建快照、再发第一次模型请求」，那么快照 IO（可能涉及遍历/哈希工作区）会**串行阻塞**首字延迟；
- 如果「先发请求、快照后台做」，那么模型的第一批工具调用可能在快照完成前就落地——此时 rewind 的 Before 基线**不完整**，回溯会失真。

`ensure_before` 是这个矛盾的折中载体：把「建快照」做成交给主循环的 awaitable，**把 await 的点推迟到「首个非只读工具执行之前」**。

**await 时机**：不是循环开头，而是**首个非只读工具即将执行**的那个点。注释里的措辞是「首个非只读工具执行前会 await」。

**防的具体问题**：**写工具穿越未就绪的 Before**。只读工具可以自由地与快照并行（读不改状态，晚一点一致性也无损）；但一旦有写（Write/Edit/Bash 写命令等），必须保证「Before 已经就绪」——否则 rewind 拿不到变更前的内容，用户就无法把文件恢复到这一步之前。

**深化讲解**（面试官参考，不要求候选人全说）
这是一道**经典的「快照与流并行」设计题**。核心洞察有两条：

1. `ensure_before` 接受 **awaitable 或 callable**（注释写「可选 awaitable/callable」），意味着调用方可以传协程，也可以传一个「被调用时才启动」的工厂——后者让「启动快照」这件事本身也可以懒到真正需要时；
2. 与 `_eligible_for_early` 的关系是**互补的**：早读工具提前执行时，`ensure_before` 还没 await（因为还没有非只读工具）——所以「只读可以早」与「写不能早」这两条，在实现层是同一个原则的两个投影。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0078 LLM 请求的重试上限与退避算法

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | 模型请求重试（44 号） | 中等 | 机制解释 | `python/engine/query_loop.py:261-281` |

**面试官提问**
请写出 `_llm_max_attempts()` 的取值规则（含环境变量名、默认值、钳制区间）。`_llm_retry_delay_ms(attempt, retry_after_ms)` 的退避公式是什么？厂商 `Retry-After` 与本地退避如何取舍？为什么加 jitter？

**参考答案要点**
`query_loop.py:261-281`：

```python
# --- 44 号：LLM 重试策略（错误码分类见 common.errors.classify_llm_failure） ---

def _llm_max_attempts() -> int:
    """单次模型请求（流）的最大尝试次数；``XEYO_LLM_MAX_ATTEMPTS`` 可覆盖，钳制 [1,5]。"""
    raw = os.environ.get("XEYO_LLM_MAX_ATTEMPTS", "3").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(1, min(n, 5))

def _llm_retry_delay_ms(attempt: int, retry_after_ms: int | None) -> int:
    """本地退避 500ms→10s（10% jitter）；厂商 Retry-After 有效时取其较大者。"""
    import random

    base = min(0.5 * (2 ** max(0, attempt - 1)), 10.0)
    delay_ms = int(round((base + base * random.uniform(0, 0.1)) * 1000))
    if retry_after_ms and retry_after_ms > 0:
        delay_ms = max(delay_ms, int(retry_after_ms))
    return delay_ms
```

**① `_llm_max_attempts()`**：

| 项 | 值 |
|---|---|
| 环境变量 | `XEYO_LLM_MAX_ATTEMPTS` |
| 默认 | `"3"` |
| 解析失败 | 回落 3（不是 1，也不是异常） |
| 钳制 | `max(1, min(n, 5))` → **[1, 5]** |

钳制区间上限是 5：无论用户配多大的值，都不会变成「无限重试」。下限 1 保证至少有 1 次尝试。

**② 退避公式**：

```
base = min(0.5 * 2^(attempt-1), 10.0)      # 单位秒，指数退避，封顶 10s
delay = round((base + base * U(0, 0.1)) * 1000)   # 加 0~10% 抖动，转毫秒
if retry_after_ms > 0:
    delay = max(delay, retry_after_ms)      # 与厂商建议取较大者
```

序列（不含抖动）：attempt=1 → 0.5s；=2 → 1.0s；=3 → 2.0s；=4 → 4.0s；=5 → 8.0s；再往上封顶 10.0s。

`max(0, attempt - 1)` 里的 `max(0, ...)` 是为了防御 `attempt=0` 这类非法入参（避免 `2**-1` 产生 0.25 的意外值）。

**③ Retry-After 的取舍**：**取较大者**（`max`）。这是唯一安全的方向——如果厂商明确说了「X 秒后再来」，比它更早重试只会再次失败。反之如果厂商没给（`None` 或 ≤0），就用本地退避。

**④ 为什么加 jitter**：`random.uniform(0, 0.1)` 是 0~10% 的正向抖动。防的是**惊群/重试同步**——多个客户端在同一个失败点同时开始退避，如果不加抖动会整批同时重试，把瞬时压力再次打满。注意这里是**正向**抖动（只加不减），所以实际延迟落在 `[base, 1.1*base]`，不会比基础退避更短。

**深化讲解**（面试官参考，不要求候选人全说）
这个函数是「44 号」修复的产物，注释里同时指向了错误分类器 `common.errors.classify_llm_failure`——说明**并非所有错误都重试**，重试与否由分类器决定，本函数只管「重试时的等待时长」。这一点在答案里必须点出，否则会把「重试策略」误答成「无条件重试 3 次」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0079 interrupt 为什么必须取消三类未决面板

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_engine | 中止时的面板清理 | 中等 | 场景设计 | `python/engine/query_engine.py:401-434` |

**面试官提问**
用户点击「停止」时，`QueryEngine.interrupt()` 除了 abort 控制器之外还额外做了三件事。它们分别是什么？如果不做会有什么后果？源码里对这个后果的原文描述是什么？

**参考答案要点**
`query_engine.py:401-434`：

```python
def interrupt(self) -> None:
    """中止当前正在执行的查询（若存在）。"""
    self._abort_controller.abort()
    # 若 session 内部控制器与外部不一致，也一并中止
    if self._session.abort is not self._abort_controller:
        self._session.abort.abort()
    # 等待审批 / 提问的协程挂在 store.wait 的 Event 上，abort 无法唤醒；
    # 把未决面板按取消处理，等待者即刻返回（按拒绝 / 未回答处理），
    # 否则回合（及其 busy 租约）要等面板 TTL 到期才结束。
    sid = self._session.session_id
    try:
        from permissions.store import default_permission_store
        default_permission_store().cancel_pending_for_session(sid)
    except Exception: ...
    try:
        from permissions.ask_store import default_ask_store
        default_ask_store().cancel_pending_for_session(sid)
    except Exception: ...
    try:
        from engine.plan import default_plan_engine
        default_plan_engine().cancel_pending_for_session(sid)
    except Exception: ...
```

**四件事（含第一件的两个分支）**：

1. `self._abort_controller.abort()`；
2. 若 `self._session.abort` 不是同一个控制器，**也一并 abort**（防御「内外控制器不一致」的情况）；
3. `permissions.store.default_permission_store().cancel_pending_for_session(sid)` —— 取消未决**权限审批**面板；
4. `permissions.ask_store.default_ask_store().cancel_pending_for_session(sid)` —— 取消未决**提问**（AskUser）面板；
5. `engine.plan.default_plan_engine().cancel_pending_for_session(sid)` —— 取消未决**计划审批**面板。

**不做的后果（源码原文）**：

> 等待审批 / 提问的协程挂在 store.wait 的 Event 上，abort 无法唤醒；把未决面板按取消处理，等待者即刻返回（按拒绝 / 未回答处理），**否则回合（及其 busy 租约）要等面板 TTL 到期才结束**。

三层含义：

- **abort 传播不到等待者**：这些协程等的不是 `abort` 对象，而是 `store.wait` 上挂的一个 `Event`。`abort.abort()` 把标志位置了，但 Event 不会因此被 set；
- **取消即「拒绝/未回答」**：等待者按拒绝处理返回到主循环，主循环随即看到 `abort.aborted` 并产出 `StoppedEvent`；
- **不取消的真实代价是「挂住」**：面板 TTL（`plan.py` 的 `PENDING_PANEL_TTL_SECONDS`）到期前，回合不会结束 → **busy 租约也不释放** → 用户「点了停止但会话还是忙的」。

三处 `try/except` 各自独立且**静默**（只有 `logger.debug`）：任一 store 不可用不该阻断其余两处的清理，也不该把异常抛给 UI。

**深化讲解**（面试官参考，不要求候选人全说）
这是一道「看似冗余、实则关键」的题。三个 `cancel_pending_for_session` 的目标对象分属三个不同模块（permissions / permissions.ask / engine.plan），说明引擎把「等待人类输入」这件事拆成了三条独立的挂起通道——而**每新增一条挂起通道，就必须在 interrupt 里加一行清理**，否则就会出现「停止不彻底」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0080 goal 候选派生为什么只记账不调度

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_engine | `_maybe_advance_goal_round` 的边界 | 中等 | 机制解释 | `python/engine/query_engine.py:436-483` |

**面试官提问**
`_maybe_advance_goal_round` 在 turn 结束时被调用。请说明：① 它在什么条件下才真的做事；② 它「只记账不调度」的具体含义；③ 为什么轮次**不在**这里推进（41 号语义修正）；④ 出错时的降级策略是什么。

**参考答案要点**
`query_engine.py:436-483`（docstring 原文关键句）：

```
"""T9/41 号：turn 结束钩子——flush→候选派生（只记账，不调度）。

只在成功 turn 且会话绑定了 active goal 时做候选派生；全程 try/except
降级，goal 层绝不杀 turn / 挡工具 / 阻塞续跑（38 号 §「刻意不做」）。
- flush：收集本轮信号（turn_succeeded、当前 todo 清单是否全 done）。
- 复检：``derive_candidate`` 判断是否应置候选。
- 记账：``mark_candidate_async`` 只写 pending_complete（无变化不写、不
  bump revision）。**轮次不再在此推进**——41 号语义修正：round 数只由
  round driver 的 ``admit_round_async`` 推进，人类轮不消耗 cap。
"""
```

**① 做事条件**（三道早退，任一不满足即 return）：

```python
if not turn_succeeded: return                        # 只在成功 turn
root = str(self._session.cwd or "").strip()
if not root or not session_id: return                 # 必须有工作区根与会话 id
goal = gstore.current(session_id)
if goal is None or goal.status != STATUS_ACTIVE: return   # 必须绑定 active goal
```

**② 「只记账」的含义**：产出的是「候选完成」这个**记录**，不是「开始下一轮」这个**动作**。

```python
todos_all_done = False
todo_tool = self._tools.get("TodoWrite")
if todo_tool is not None:
    todos = todo_tool.current_todos()
    todos_all_done = bool(todos) and all(
        getattr(t, "status", "") == "completed" for t in todos
    )
candidate = derive_candidate(turn_succeeded=True, todos_all_done=todos_all_done)
await gstore.mark_candidate_async(
    goal.goal_id, revision=goal.revision,
    pending_complete=candidate_is_pending(candidate),
)
```

注意 `todos_all_done` 的口径：`bool(todos)` 要求**清单非空**——空清单不算「全 done」（避免「什么都没做」被误判为完成）。

**③ 轮次为什么不在这里推进**：docstring 说得很直白——**「round 数只由 round driver 的 `admit_round_async` 推进，人类轮不消耗 cap」**。含义是：如果 turn 结束就 bump 轮次，那么**用户在会话里随口问一句**也会消耗 goal 的轮次预算（人类轮被当成 goal 推进轮）。41 号修正把推进权**收敛到单一入口**（round driver），人类轮因此不消耗 cap。这是「单一写者」原则在状态机上的应用。

**④ 降级策略**：

```python
except Exception:  # noqa: BLE001
    logging.getLogger(__name__).debug(
        "goal round advance skipped session=%s", session_id, exc_info=True
    )
```

**全量吞异常 + debug 日志**。注释给出了理由：「goal 层绝不杀 turn / 挡工具 / 阻塞续跑（38 号 §「刻意不做」）」——goal 是一个**附加能力**，它的任何故障都不能影响主循环这个核心。

**深化讲解**（面试官参考，不要求候选人全说）
这题的三层考点：① **条件收敛**（只成功 turn、只 active goal）；② **职责收敛**（只记账、不调度、不推进轮次）；③ **失败隔离**（goal 挂掉不影响主链路）。

「无变化不写、不 bump revision」也值得注意：`mark_candidate_async` 在状态未变时不写盘、不递增修订号——避免每轮 turn 结束都产生一次无意义的磁盘写与协商版本号膨胀。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0081 帧缓冲溢出时裁掉哪一端

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | 溢出裁剪的方向 | 中等 | 代码阅读 | `python/engine/turn_runner.py:207-220` |

**面试官提问**
阅读下面这段代码，回答：溢出时被裁掉的是**最早**的帧还是**最新**的帧？`det.last_event_id` 在裁剪过程中会回退吗？这种「丢早期帧」的做法带来什么可观测后果，为什么项目接受它？

```python
async for event_id, frame, kind in producer():
    det.last_event_id = max(det.last_event_id, int(event_id))
    det.frames.append((int(event_id), frame, kind))
    det.frames_bytes += len(frame)
    if (len(det.frames) > _MAX_BUFFERED_FRAMES
            or det.frames_bytes > _MAX_BUFFERED_BYTES):
        while det.frames and (
            len(det.frames) > _MAX_BUFFERED_FRAMES
            or det.frames_bytes > _MAX_BUFFERED_BYTES
        ):
            _ev_id, ev_frame, _k = det.frames.pop(0)
            det.frames_bytes -= len(ev_frame)
```

**参考答案要点**
**裁掉的是最早的帧**，`det.last_event_id` **不会回退**。

逐点分析：

1. **方向**：`det.frames.pop(0)` —— `list.pop(0)` 弹出**头部**元素，即最早入队的帧。所以裁剪后保留的是**尾部（最新）**窗口（FIFO 队列的滑动窗口语义）。
2. **`last_event_id` 不回退**：它在 append **之前**用 `max(...)` 更新，且裁剪循环**不修改**它。所以即使事件帧被丢弃，「已产出到哪个事件号」这个水位仍单调递增。
3. **可观测后果**：如果某客户端从未收到过被丢弃的那些早期帧（例如它从回合开始就连着但因为某种原因没消费），重连后拿到的历史帧会**缺开场部分**——它看到的「回合」从中间开始。
4. **为什么接受**：
   - `_evict_terminal_turns_locked` 的 docstring（`:187-190`）给出理由：「**frames 只用于 reattach 重放；快照已落盘，丢弃旧终态不影响恢复**」；
   - 内存是无上限增长的唯一受害者，而帧缓冲的用途只有「重放最近的过程」这一项；
   - 加上 `_MAX_BUFFERED_FRAMES = 4000` / `_MAX_BUFFERED_BYTES = 8 MiB` 的双上限（见 0066），溢出本身只有在**极端大帧或超长回合**才发生。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的关键是分清两个**方向相反**的语义：「丢弃方向 = 从旧到新」与「水位方向 = 单调递增」。二者不矛盾：水位表达的是「生产者进度」，缓冲区表达的是「可重放窗口」。

容易错的推论是「丢帧了所以 last_event_id 也该退」——那样会导致客户端重连时被要求重放一个已经不存在的区间。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0082 incomplete_tools 的用途与截断

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | 已发起未返回的工具记录 | 中等 | 机制解释 | `python/engine/turn_runner.py:237-259` |

**面试官提问**
`_run_producer` 如何维护 `det.incomplete_tools`？它记录什么、在什么事件上增、在什么事件上删？超过 64 个时如何截断，为什么用「删前 32」而不是「删到 64」？这份数据的用途是什么？

**参考答案要点**
`turn_runner.py:237-259`：

```python
elif kind == "tool_call":
    # 恢复数据：记录已发起未返回的工具（崩溃后续跑提示用）
    try:
        import json as _json
        xy = _json.loads(frame).get("xy") or {}
        tuid = str(xy.get("tool_use_id") or "")
        if tuid and tuid not in det.incomplete_tools:
            det.incomplete_tools.append(tuid)
            if len(det.incomplete_tools) > 64:
                del det.incomplete_tools[:32]
    except Exception:
        pass
elif kind == "tool_result":
    try:
        import json as _json
        xy = _json.loads(frame).get("xy") or {}
        tuid = str(xy.get("tool_use_id") or "")
        if tuid and tuid in det.incomplete_tools:
            det.incomplete_tools.remove(tuid)
    except Exception:
        pass
```

**语义**：`incomplete_tools` = 「**已发起、尚未返回**」的工具调用 id 列表。用途写在注释里：「**恢复数据：记录已发起未返回的工具（崩溃后续跑提示用）**」。

**增删规则**：
- `tool_call` 帧 → 解析 `xy.tool_use_id`，去重后 append（`not in` 判重防重复帧）；
- `tool_result` 帧 → 若 id 在列表中则 `remove`；
- 都会在外层 `try/except: pass` 里，**解析失败静默跳过**（帧结构异常不该让 turn 崩）。

**截断策略**：`if len(...) > 64: del det.incomplete_tools[:32]`
- 阈值 64；
- 超限时**一次删掉最旧的 32 个**（`del list[:32]` 删头部）。

**为什么「删 32」而不是「删到 64」**：如果只删掉最少必要的量（即 `del [:(len-64)]`，通常只删 1 个），那么在一个**持续溢出**的长回合里，**每一帧**都要触发一次 `del` 与列表搬移（O(n) 每次），累计成 O(n²) 的开销。一次清掉一半（32 个）把「何时再触发下一次清理」的时间**翻倍**，摊薄了管理成本——这是典型的**摊还（amortized）**策略。

**深化讲解**（面试官参考，不要求候选人全说）
注意一个隐含事实：`tool_call` 与 `tool_result` 的增减使得这个列表的大小近似等于「**当前并发在飞的工具数**」，正常情况是个位数。要它涨到 64，必须是「大量工具发起后长期不返回」——这恰好就是「崩溃/挂起」的特征场景，也正是这份数据要服务的目标。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0083 subscribe 的节拍常量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | 事件订阅的唤醒节拍 | 中等 | 机制解释 | `python/engine/turn_runner.py:81-84,413,462` |

**面试官提问**
`turn_runner.py` 里 `_SUBSCRIBE_TICK_S = 12.0` 与 `_END = object()` 分别是什么？`subscribe(...)` 与 `wait_done(session_id, timeout=None) -> bool` 在接口形态上有什么不同（生成器 vs 单次返回）？

**参考答案要点**
实测事实：

```python
_END = object()                    # :81  —— 模块级哨兵对象
_SUBSCRIBE_TICK_S = 12.0           # :84  —— 订阅唤醒节拍（秒）
async def subscribe(...)           # :413 —— async 生成器形态的订阅接口
async def wait_done(self, session_id: str, timeout: float | None = None) -> bool:   # :462
```

- **`_END = object()`**：典型的**哨兵对象**用法。用模块级唯一实例（不是 `None`、不是字符串）作为「流结束」标记，好处是与任何正常载荷都不相等——即使载荷本身是 `None` 或 `"END"` 也不会与哨兵混淆。
- **`_SUBSCRIBE_TICK_S = 12.0`**：订阅循环的**唤醒节拍**，12 秒。它的存在说明订阅不是纯粹的「有帧就推」推送——还存在一个定时唤醒（用于在没有新帧时也能察觉「turn 已结束/已无订阅者」这类状态变化，避免订阅者永久挂住）。
- **两种接口形态的差异**：
  - `subscribe(...)` 是 `async def` 生成器（`async for` 消费），面向「**持续拉取一段事件流**」；
  - `wait_done(session_id, timeout=None) -> bool` 是**单次 await 得到布尔结果**，面向「**只关心跑完没有**」——`timeout` 为 `None` 表示一直等；传了超时则以布尔值表达「是否在超时前完成」。

**深化讲解**（面试官参考，不要求候选人全说）
这题的设计要点是「**推送 + 定时唤醒**」的混合模型。纯事件驱动在「生产者已死但没有显式终结事件」时会挂住；纯轮询又浪费。12 秒的节拍是在这两种失败模式之间取的折中——它对应的正是「客户端断开/回合终结」这类**不产生帧的状态变化**。

（说明：`subscribe` 的内部实现细节（`:413-460`）不在本批逐一展开，上面对节拍作用的说明基于常量语义与接口形态；如需精确的行级行为，请直读该函数体。）



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0084 断连与停止是两件事

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | 客户端断连 vs 主动停止 | 中等 | 机制解释 | `python/engine/turn_runner.py:386-398` |

**面试官提问**
`note_client_disconnect(session_id, turn_id="")` 与 `mark_stopping(session_id, reason="user_stop")` 是两个不同方法。请说明它们的语义差异，以及为什么「客户端断开」不能直接等价于「停止回合」。

**参考答案要点**
两个方法（`turn_runner.py:386,398`）：

```python
def note_client_disconnect(self, session_id: str, turn_id: str = "") -> None: ...
def mark_stopping(self, session_id: str, reason: str = "user_stop") -> None: ...
```

**语义差异**：

| | `note_client_disconnect` | `mark_stopping` |
|---|---|---|
| 触发者 | 客户端（HTTP/SSE 连接断开、窗口关闭、网络抖动） | 引擎侧（收到停止指令） |
| 含义 | 「**观察者走了**」 | 「**工作要停**」 |
| `reason` 参数 | 无（只带 `turn_id` 用于校验） | 有，默认 `"user_stop"` |
| 对回合的影响 | 不终止回合 | 标记回合进入停止流程 |

**为什么断连 ≠ 停止**：这正是「detached turn」这个设计的全部意义（`_DetachedTurn`，`turn_runner.py:59`；`TurnRunner` 的 docstring 语境见 `:87`）。回合作为 `asyncio.Task` 独立运行（`turn_runner.py:180-183` 的 `asyncio.create_task(..., name=f"xeyo-turn-{session_id}-{tid}")`），**不绑定任何一条 HTTP 连接**。用户关掉窗口/断网时：

1. 回合继续跑（文件还在写、工具还在执行）；
2. 帧继续进缓冲区（这样客户端重连后能 reattach 重放，见 0081）；
3. busy 租约继续靠 30s 心跳续期（见 0067）——**假设回合还在产帧**。

所以 `note_client_disconnect` 的职责是「记账/告知」，不是「终止」。如果断连即终止，那么任何一次网络抖动都会让长任务白跑，且用户重连后看到的是一个半途而废的工作区。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于把「连接生命周期」与「任务生命周期」解耦这件事说清楚。它也顺带解释了一个容易困惑的现象：为什么 XEYO 里「关掉窗口再打开，任务还在跑」——因为停止必须显式（`mark_stopping` / interrupt 链路，见 0079）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0085 任务图的拓扑排序与环打断

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | scheduler | DAG 校验与修复 | 中等 | 机制解释 | `python/engine/scheduler.py:23-24,109,154,215` |

**面试官提问**
`scheduler.py` 提供了 `toposort(tasks)`、`_break_cycles(tasks)`、`repair_task_graph(...)`。它们各自解决多代理任务图的什么问题？`MAX_DECOMPOSE_TASKS = 8` 与 `MAX_PATCH_RETRIES = 3` 分别约束什么？

**参考答案要点**
实测函数与常量：

```python
MAX_PATCH_RETRIES = 3                               # :23
MAX_DECOMPOSE_TASKS = 8                             # :24
def _norm_scope_path(path, root=None) -> str        # :95
def toposort(tasks: list[Task]) -> list[Task]       # :109
def scope_conflicts(...)                            # :134
def _break_cycles(tasks: list[Task]) -> None        # :154
    def dfs(u: str) -> bool                         # :163（嵌套 DFS）
def build_tool_whitelist(task: Task) -> list[str]   # :191
def batch_tool_whitelist(tasks: list[Task]) -> list[str]   # :202
def repair_task_graph(...)                          # :215
def turns_for_timeout(timeout_s: float) -> tuple[int, int]  # :243
```

**各自解决的问题**：

| 函数 | 问题 | 说明 |
|---|---|---|
| `toposort(tasks)` | **执行顺序** | 按依赖关系给出拓扑序，保证「依赖的先跑」 |
| `scope_conflicts(...)` | **写冲突识别** | 判断多个任务的 `scope`（`_norm_scope_path` 归一化后的路径集）是否重叠 |
| `_break_cycles(tasks)` | **环检测与打断** | 用嵌套 `dfs(u)` 找环并打断，使图重新成为 DAG |
| `repair_task_graph(...)` | **整体修复** | 把上面几步串起来，对模型给出的任务图做「可执行化」修补 |

**两个常量的约束**：
- **`MAX_DECOMPOSE_TASKS = 8`**：一次**分解**（decompose）最多产出 8 个任务。约束的是「模型拆得太碎」——任务数爆炸会让调度、冲突检测、上下文传递的成本非线性上升。
- **`MAX_PATCH_RETRIES = 3`**：任务图的**修补重试**上限 3 次（对应 `repair_task_graph`）。约束的是「反复修补不收敛」——修 3 次仍有环/冲突就不再回炉，避免无限循环。

**深化讲解**（面试官参考，不要求候选人全说）
这题的重点是理解「**模型给的任务图不能直接信**」。模型产出的依赖关系可能成环（A 依赖 B、B 依赖 A）、可能写同一批文件（scope 冲突）、可能拆得过细。scheduler 这一组的定位就是把「模型意图」翻译成「可安全并发执行的 DAG」——**排序、冲突、环**三件事各自有独立函数，最后用 `repair_task_graph` 收口。

`_norm_scope_path(path, root)` 的存在说明 scope 比较之前必须**归一化**（相对/绝对、`..`、分隔符大小写等），否则「同一目录」会被判成不冲突而并发写入。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0086 子代理工具白名单：并集还是交集

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | scheduler | 任务级与批级工具白名单 | 中等 | 机制解释 | `python/engine/scheduler.py:191-212` |

**面试官提问**
请说清 `build_tool_whitelist(task)` 的三步构造，以及 `batch_tool_whitelist(tasks)` 为什么要取**交集**而不是并集。为什么「空 scope 任务与可写任务混批」时，交集里**不能**有写工具？

**参考答案要点**
`scheduler.py:191-212`（原文）：

```python
def build_tool_whitelist(task: Task) -> list[str]:
    """按任务构建子 agent 工具白名单：基线 + required_tools，剔除禁止项。

    空 scope → 剔除全部 write_path 工具（Write/Edit/NotebookEdit…），只读工人硬门禁。
    """
    allow = set(SUBSET_TOOL_BASELINE) | set(task.required_tools)
    if not (task.scope or []):
        allow -= WRITE_PATH_TOOLS
    return sorted(n for n in allow if n not in FORBIDDEN_SUB_TOOLS)


def batch_tool_whitelist(tasks: list[Task]) -> list[str]:
    """批次共用白名单候选（A3 缓存提示）：取各任务 whitelist 的交集。

    空 scope 任务不含写工具；与可写任务混批时交集亦无写工具，避免只读工人看见 Write。
    无任务时回退基线（仍剔禁止项）。
    """
    if not tasks:
        return sorted(n for n in SUBSET_TOOL_BASELINE if n not in FORBIDDEN_SUB_TOOLS)
    sets = [set(build_tool_whitelist(t)) for t in tasks]
    shared = sets[0].intersection(*sets[1:]) if len(sets) > 1 else sets[0]
    return sorted(shared)
```

**单任务三步**：
1. `allow = SUBSET_TOOL_BASELINE ∪ task.required_tools` —— 「基线工具」并上「该任务声明必需的工具」；
2. 若 `task.scope` 为空（`not (task.scope or [])`）→ `allow -= WRITE_PATH_TOOLS` —— **空 scope 硬门禁**：没有声明作用域的任务视为只读工人，剔除 Write/Edit/NotebookEdit 等全部写路径工具；
3. 过滤 `FORBIDDEN_SUB_TOOLS` 后排序返回。

**批级为什么取交集**：注释已经给了答案——「**避免只读工人看见 Write**」。批级的工具表是**整批共用的**（A3 缓存提示的意图是让缓存命中）。如果取并集，那么「一个可写任务 + 一个只读任务」混批后，共用工具表里会出现 Write——**只读工人就拿到了写工具**。取交集是唯一安全的合并方向：**收紧才安全，放宽即越权**。

代价也要说清：交集会让「可写任务的写工具」在混批时也不可用——这是用**能力换安全**，方向与 XEYO 整体的 fail-closed 取向一致。

无任务时回退 `SUBSET_TOOL_BASELINE`（仍剔除禁止项），而不是返回空表——空表会让子代理连读都做不了。

**深化讲解**（面试官参考，不要求候选人全说）
这题的核心是**方向性**：安全属性的合并（`∩`）与能力属性的合并（`∪`）是相反的。`build_tool_whitelist` 里 `|` 与 `-` 的用法同样体现了这一点：基线用并（放宽能力），空 scope 用差（收紧能力）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0087 崩溃恢复标记的判定与话术

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_snapshot | 进程重启后的快照状态迁移 | 中等 | 场景设计 | `python/engine/turn_snapshot.py:151-181` |

**面试官提问**
进程被强杀（未走正常清理）后重启，哪些快照会被 `list_recoverable()` 认为是「可恢复/需确认」的？`mark_crashed_as_recovery(snap)` 会在什么状态下改写快照，改写成什么，`stop_reason` 有哪两个可能取值、分别对应什么情形？

**参考答案要点**
`turn_snapshot.py:151-181`（原文）：

```python
def list_recoverable() -> list[TurnSnapshot]:
    """扫描 sessions 目录中可恢复 / 需确认的 turn。"""
    root = _sessions_dir()
    if not root.is_dir():
        return []
    out: list[TurnSnapshot] = []
    for path in root.glob("*.turn.json"):
        sid = path.name[: -len(".turn.json")]
        snap = hydrate(sid)
        if snap is None:
            continue
        if snap.is_active() or snap.status == "recovery_required":
            out.append(snap)
    return out


def mark_crashed_as_recovery(snap: TurnSnapshot) -> TurnSnapshot:
    """进程重启后：原 running/stopping → recovery_required。"""
    if snap.status in {"running", "stopping", "queued"}:
        if snap.waiting_permission:
            snap.status = "recovery_required"
            snap.stop_reason = snap.stop_reason or "restart_while_waiting_permission"
        else:
            snap.status = "recovery_required"
            snap.stop_reason = snap.stop_reason or "process_restart"
        flush(snap)
    elif snap.status == "waiting_permission":
        snap.status = "recovery_required"
        snap.stop_reason = snap.stop_reason or "restart_while_waiting_permission"
        flush(snap)
    return snap
```

**① 谁被认为可恢复**：扫描 `*.turn.json`（**文件名去掉后缀即 session id**），逐个 `hydrate`；满足二者之一即纳入：
- `snap.is_active()`（`turn_snapshot.py:47`）—— 仍处活跃态；
- `snap.status == "recovery_required"`。

注意 `root.is_dir()` 为假时直接返回 `[]`（首次运行、目录被清理时正常运行）。

**② 改写条件与结果**：

| 原 `status` | 额外条件 | 新 `status` | `stop_reason` |
|---|---|---|---|
| `running` / `stopping` / `queued` | `waiting_permission` 为真 | `recovery_required` | `restart_while_waiting_permission` |
| `running` / `stopping` / `queued` | `waiting_permission` 为假 | `recovery_required` | `process_restart` |
| `waiting_permission`（自身状态） | — | `recovery_required` | `restart_while_waiting_permission` |
| 其它（如已终结态） | — | **不改写** | — |

**③ 两个 `stop_reason` 的语义差别**：`restart_while_waiting_permission` 表示「**重启时正在等人类审批**」——这是一个**可解释**的中断（用户当时可能正看着弹窗）；`process_restart` 表示「**纯粹被重启打断**」。区分二者的价值在于后续给用户的话术不同：前者可以提示「当时有一个待审批的请求」，后者只能说「会话被中断」。

**④ `snap.stop_reason or "..."` 的写法**：只在 `stop_reason` 为空时写入，**不覆盖已有值**——保留更原始的失败原因（避免二次改写抹掉第一次的原因）。

**深化讲解**（面试官参考，不要求候选人全说）
这题有个容易忽略的细节：`queued` 状态也被纳入「崩溃」集合。它说明 `queued` 是一个**尚未开始但已登记**的状态——重启后不会自动继续跑，必须走恢复确认。

另一处：改写后立刻 `flush(snap)` 落盘——**内存改了不落盘等于没改**，重启的判定依赖磁盘上的 `status`。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0088 标题的两条生成路径

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | title | 即时标题与模型增强 | 中等 | 机制解释 | `python/engine/title.py:46-78,162,280,311` |

**面试官提问**
`instant_title(first_user_text)` 对首条用户消息做了哪几步清洗？为什么要有 `_byte_safe_truncate` 而不是直接切片？`ensure_instant_title`（`:162`）、`enhance_with_model`（`:280`）、`fire_and_forget_enhance`（`:311`）三者的关系是什么？

**参考答案要点**
`title.py:46-78`（原文）：

```python
def _byte_safe_truncate(text: str, limit: int = MAX_TITLE_BYTES) -> str:
    """按 UTF-8 字节预算截断；绝不切坏多字节字符。"""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    out: list[str] = []
    used = 0
    for ch in text:
        w = len(ch.encode("utf-8"))
        if used + w > limit:
            break
        out.append(ch)
        used += w
    return "".join(out).rstrip()


def instant_title(first_user_text: str) -> str:
    """从首条用户消息推导确定性标题：去 markdown 噪声、折叠空白、安全截断。"""
    raw = str(first_user_text or "")
    for line in raw.splitlines():
        line = line.strip()
        if line:
            raw = line
            break
    else:
        return DEFAULT_TITLE
    line = _MD_NOISE_RE.sub("", raw.strip()).strip()
    line = _LEADING_MARKER_RE.sub("", line).strip()
    line = re.sub(r"\s+", " ", line)
    if not line:
        return DEFAULT_TITLE
    title = _byte_safe_truncate(line)
    return title or DEFAULT_TITLE
```

**`instant_title` 的五步**：
1. **取第一条非空行**（`for ... break` + `else: return DEFAULT_TITLE`）—— 全空白输入直接回默认标题「新会话」；
2. `_MD_NOISE_RE.sub("", ...)` 去 markdown 噪声（如 `#`、代码围栏等标记）；
3. `_LEADING_MARKER_RE.sub("", ...)` 去前导标记；
4. `re.sub(r"\s+", " ", line)` 折叠所有连续空白为单个空格（含换行/制表符）；
5. `_byte_safe_truncate(line)` 截断，空结果回默认标题。

**为什么必须 `_byte_safe_truncate`**：`MAX_TITLE_BYTES = 96` 是**字节**预算。直接 `text[:96]` 是**按字符**切——中英混排时会超字节预算（一个汉字 3 字节），而且如果按字节切（`raw[:96].decode()`），会在多字节字符中间断开，产生 `UnicodeDecodeError` 或替换字符。`_byte_safe_truncate` 的做法是**逐字符累加字节数、超限即停**，天然不会切坏码点；结尾再 `.rstrip()` 去掉截断后残留的空白。

**三条路径的关系**：

| 函数 | 定位 |
|---|---|
| `instant_title(...)` | **确定性、纯本地**：从首条用户文本直接算，零延迟零成本 |
| `ensure_instant_title(session_id, first_user_text)`（`:162`） | **落地封装**：算即时标题并**写入 sidecar**（含 `read_title`/`write_title` 的持久化链路，`:104`/`:126`） |
| `enhance_with_model(...)`（`:280`） | **异步增强**：调模型生成更好的标题 |
| `fire_and_forget_enhance(...)`（`:311`，内部 `async def _run()`） | **触发方式**：把增强做成**不等待**的后台任务 |

即：`ensure_instant_title` 保证「会话一建立就有标题」（不会出现空白标题）；`enhance_with_model` 随后在后台把它替换成更好的；`fire_and_forget_enhance` 让调用方**不必等待**模型返回——用户看到标题立刻出现，几秒后可能悄悄变好。内部还有 `_stream_text(client, prompt)`（`:239`）与 `_audit(kind, **fields)`（`:271`）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的工程价值在「**先给确定性结果，再异步优化**」这个模式。它避免了两个坏情况：① 首字前等待模型生成标题（延迟）；② 标题栏长期空白（体验）。同时 `archive_sidecar_path`/`read_archive`/`write_archive`/`clear_archive`（`:173-222`）说明业务上还有一套「归档标题」的持久化——与普通标题分开存储。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0089 Plan 面板的 TTL、幂等与唤醒

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | plan | 计划确认面板的生命周期 | 中等 | 机制解释 | `python/engine/plan.py:18-104` |

**面试官提问**
`PlanEngine` 的定位是什么？`create()` 里 `request_id` 的默认生成顺序是什么？`resolve()` 在什么情况下返回 `False`（为什么这个保护是必要的）？`wait()` 的超时默认值是什么、超时后是抛异常还是返回？

**参考答案要点**
`plan.py:30-104`（原文节选）：

```python
class PlanEngine:
    """进程内、按 turn_id 索引的 Plan 确认存储。"""

    def __init__(self, ttl_seconds: float = PENDING_PANEL_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, PendingPlan] = {}
        self._events: dict[str, asyncio.Event] = {}

    def create(self, *, session_id, turn_id, plan, request_id=None) -> PendingPlan:
        self._prune()
        rid = request_id or turn_id or uuid.uuid4().hex
        now = time.time()
        item = PendingPlan(request_id=rid, session_id=session_id, turn_id=turn_id,
                           plan=plan, expires_at=now + self._ttl, created_at=now)
        self._items[rid] = item
        self._events[rid] = asyncio.Event()
        return item

    def resolve(self, request_id: str, approved: bool, actor: str = "") -> bool:
        item = self._items.get(request_id)
        if item is None or item.resolved:
            return False
        item.resolved = True
        item.approved = approved
        item.actor = actor
        ev = self._events.get(request_id)
        if ev is not None:
            ev.set()
        return True

    async def wait(self, request_id: str, timeout: float | None = None) -> PendingPlan | None:
        item = self._items.get(request_id)
        if item is None:
            return None
        if timeout is None:
            timeout = max(0.0, item.expires_at - time.time())
        ev = self._events.get(request_id)
        if ev is not None and not ev.is_set():
            try:
                await asyncio.wait_for(ev.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        return self._items.get(request_id)
```

**① 定位**：docstring 明确——「**进程内、按 turn_id 索引的 Plan 确认存储**」。三个限定词都要答对：进程内（不跨进程/不持久化）、按 `turn_id` 索引（`create` 的 `rid` 默认就取 `turn_id`）、存储（不负责展示）。

**② `request_id` 生成顺序**：`rid = request_id or turn_id or uuid.uuid4().hex` —— **显式传入 > `turn_id` > 随机 uuid**。用 `turn_id` 作为默认值使得「一个 turn 一次计划确认」成为天然约束，也让前端能用已知的 `turn_id` 直接寻址。

**③ `resolve()` 返回 `False` 的两种情况**：`item is None`（未知请求）或 **`item.resolved` 已为真**。第二个是关键——**幂等保护**：同一个计划被「批准 + 拒绝」两次（例如用户在两个界面上都点了，或网络重试导致重复提交）时，第二次不再改写状态。没有这层保护，后到的裁决会覆盖先到的（`approved` 被翻转），而等待者可能已经按先到的裁决继续执行了——**状态与行为不一致**。

**④ `wait()` 的超时默认值与行为**：
- `timeout is None` → `timeout = max(0.0, item.expires_at - time.time())`，即**默认等到 `expires_at`（TTL 到期）**；`max(0.0, ...)` 防御「已过期」导致的负超时；
- 超时**不抛异常**：`except asyncio.TimeoutError: pass`，随后**照常 `return self._items.get(request_id)`** ——把「未裁决」这件事通过**返回未 resolved 的 item** 表达，而不是异常。这样调用方能统一用「返回值的 `approved`/`resolved` 字段」判断结果。

**深化讲解**（面试官参考，不要求候选人全说）
三个机制串起来就是完整的生命周期：`create` 时 `expires_at = now + ttl`（`PENDING_PANEL_TTL_SECONDS`）→ `wait` 最多等到 TTL → 人类裁决经 `resolve` 置位并 `ev.set()` 唤醒 → 若被 `interrupt` 打断，`cancel_pending_for_session`（`:76-88`）会以 `approved=False, actor="abort"` 批量处理并唤醒（注释点明「与 permission/ask 同源：wait 挂在 asyncio.Event 上，abort 无法唤醒，不取消则回合挂死到面板 TTL」——与 0079 完全对应）。

`create` 开头的 `self._prune()`（`:106`）说明每次新建都会顺带清理过期项——**惰性 GC**，不依赖后台定时器。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0090 BudgetTracker 的闸门方法面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | 轮次/工具/美元三套闸门 | 中等 | 概念确认 | `python/engine/budget.py:251,281,302,322,349,354,446,450,454` |

**面试官提问**
请列出 `BudgetTracker` 的实例方法。

A. `prepare_next_turn()` —— 申请下一轮
B. `allow_next_turn()` —— 判定是否允许下一轮
C. `begin_turn()` / `begin_tool_call()` —— 轮次与工具调用的计数起点
D. `consume_runtime_notice()` / `queue_runtime_notice(text)` —— 运行时通知的消费与入队
E. `hard_stop_reason()` / `grace_turns_remaining()` —— 硬停原因与宽限余量
F. `over_budget()` / `over_token_budget()` —— 美元与 token 两道水位
G. `reset_for_new_submit(...)` —— 新一轮提交时的重置
H. `toposort(tasks)` —— 任务拓扑排序

**参考答案要点**
**A、B、C、D、E、F、G 都是**；H 不是（`toposort` 是 `scheduler.py:109` 的模块级函数，与预算无关）。

实测行号对照：

| 方法 | 行号 |
|---|---|
| `prepare_next_turn()` | `budget.py:251` |
| `allow_next_turn()` | `budget.py:281` |
| `begin_turn()` | `budget.py:285` |
| `begin_tool_call()` | `budget.py:302` |
| `consume_runtime_notice()` | `budget.py:322` |
| `queue_runtime_notice(text)` | `budget.py:330` |
| `hard_stop_reason()` | `budget.py:349` |
| `grace_turns_remaining()` | `budget.py:354` |
| `tool_call_count()` | `budget.py:359` |
| `consume_tokens(n)` | `budget.py:362` |
| `add_usage(usage, ts=None)` | `budget.py:423` |
| `over_budget()` | `budget.py:446` |
| `over_token_budget()` | `budget.py:450` |
| `reset_for_new_submit(...)` | `budget.py:454` |

另有墙钟一组：`set_wall_deadline(deadline_ts, *, started_ts=None)`（`:148`）、`wall_remaining_s(now=None)`（`:154`）、`arm_wall_stop(enabled=None)`（`:160`）、`check_wall_deadline(now=None)`（`:168`）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的真正考点是**「预算」在 XEYO 里不是一个数，而是多条独立的闸门**：

1. **轮次闸**（`DEFAULT_MAX_TURNS = 256`）—— 由 `prepare_next_turn` / `begin_turn` 管理；
2. **工具闸**（`DEFAULT_MAX_TOOL_CALLING = 64`）—— 由 `begin_tool_call` 管理；
3. **墙钟闸** —— 由 `set_wall_deadline` / `check_wall_deadline` / `arm_wall_stop` 管理，对应 `WALL_STOP_NOTICE`；
4. **成本闸**（美元 + token）—— `over_budget` / `over_token_budget` 两道水位，由 `add_usage` / `consume_tokens` 喂养。

`prepare_next_turn` 与 `allow_next_turn` 的**并存**也值得注意：名字都在问「能不能下一轮」，但一个是**申请动作**（可能带副作用，如触发宽限、排队通知），一个是**纯判定**。这类「动作 vs 判定」的方法对在 XEYO 里反复出现（对照 `_should_persist` 与 `_persist_transcript_delta`，`query_engine.py:380,387`）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0091 为什么早读准入不能放宽到「非 DENY」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop × permissions | 早读与策略裁决的耦合 | 困难 | 场景设计 | `python/engine/query_loop.py:155-176`；`python/permissions/policy.py`（`evaluate_policy`） |

**面试官提问**
场景：某只读工具（例如 `Grep`）在一次具体调用中，因为目标路径在工作区外，被策略裁决为 `ASK` 而不是 `ALLOW`。

（1）它会被提前执行吗？为什么？
（2）假设有人为了「提升并行度」把 `_eligible_for_early` 的最后一行的判定从 `== ALLOW` 改成 `!= DENY`，请分析这个改动会造成什么后果——请从**用户否决权**、**审计真实性**、**注意力顺序**三个角度说明。
（3）这个改动是否属于「应试性修改」？为什么？

**参考答案要点**
**（1）不会。** `query_loop.py:174-176`：

```python
raw_input = tu.input if isinstance(tu.input, dict) else {}
decision = evaluate_policy(name, raw_input, cwd=registry.cwd, tool=tool)
return decision.decision == PermissionDecision.ALLOW
```

严格等于 `ALLOW`。`ASK` 不满足，因此该调用进入正常的「等待裁决」路径，不提前执行。注释给的定位是「只读 + 并发安全 + policy ALLOW；**ASK/写/外发/交互一律不提前**」。

**（2）改成 `!= DENY` 的三重后果**：

**① 用户否决权被剥夺（最严重）**
`ASK` 的语义是「**必须由人类点头才能执行**」。提前执行的本质是「**在用户看到弹窗之前就已经跑完**」。放宽后，模型和用户都会先看到结果——此时用户即使点「拒绝」，事实已经发生（文件被读、内容进了上下文）。**裁决从「事前」变成了「事后」**，`ASK` 这一档在只读工具上实质失效。

**② 审计记录与真实执行顺序失真**
执行发生在裁决之前，审计里会出现「**未获批准却已执行**」的记录。更糟的是，若用户的拒绝导致引擎产出「被拒绝」的事件，而工具结果早已进入对话历史，就会形成**互相矛盾的持久化记录**——与 `session/record_transcript.py` 的权威 transcript 口径冲突（该文件本身就是已知缺陷高发区，见 B08）。

**③ 注意力顺序破坏**
`ASK` 场景下用户看到的顺序应当是「请求 → 裁决 → 结果」。提前执行后变成「结果 → 请求 → 裁决」，用户失去对自己工作区被读取的知情顺序感。这与引擎铁律的「注意力里只出现信息」并不冲突——**问题不在信息本身，而在信息来源通过了未经授权的通道**。

**（3）属于应试性修改。** 按 XEYO 的四条应试性审查准则（R1 产品受益 / R2 无评测分支 / R3 信息纪律 / R4 收益可证伪）：

- **R1**：这个改动只提升「并行度」这个指标，而牺牲的是权限语义——收益只在评测的耗时维度体现，产品上是有害的（用户失去否决权）；
- **R2**：它等于给评测场景开了一条特权路径（评测里 ASK 少、耗时敏感），是为跑分而改行为；
- **R4**：收益可证伪的方式只能是「读评测判分器/看计时」，属于应试。

**正确方向**：如果要提升并行度，应该改的是「哪些工具被裁决为 `ALLOW`」（策略侧），或让早读并发度更高（调度侧）——**不能改准入的语义边界**。

**深化讲解**（面试官参考，不要求候选人全说）
这道题把「一行判定」放大成三类后果，考的是能否分辨「能力放宽」与「权限语义改变」。核心判据只有一句：

> `ASK` 是**事前**约束；任何让执行早于裁决的优化，都在把它变成事后约束。

顺带注意 `evaluate_policy(name, raw_input, cwd=registry.cwd, tool=tool)` 里传的是 `raw_input`（**本次调用的真实入参**）——说明裁决是**逐调用**的，同一个只读工具的不同入参可以有不同裁决。这也解释了为什么「工具属性是只读」不足以作为准入依据。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0092 收尾窗从「全禁」改为「配额」的权衡

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop | R3' 收尾窗语义修正 | 困难 | 场景设计 | `python/engine/query_loop.py:786-791,805-812`；`python/engine/wrap_gap.py:26` |

**面试官提问**
场景：一个回合因为 `max_tool_calling` 到顶而进入收尾窗，此时**有 3 个文件被 TodoWrite 声明过但磁盘上不存在**（模型承诺要写但没写）。

（1）R3' 之前的「一开闸全禁」会怎样？R3' 之后呢？
（2）为什么「收尾恰好最需要落盘」这句话在工程上是成立的？
（3）配额默认只有 3，如果模型把这 3 次配额用来**继续探索**（例如再 Grep 几次）而不是落盘，系统会阻止吗？为什么这样设计是可接受的？
（4）`MAX_GAP_ITEMS = 5` 起到什么作用？

**参考答案要点**
**（1）行为对比**

| | R3' 之前（一开闸全禁） | R3' 之后（配额制） |
|---|---|---|
| 进收尾窗的动作 | 把所有工具禁掉 | `forced_wrap_up = True`，发布缺口清单 + 配额 |
| 模型能做什么 | 只能输出文本 | **配额内仍可调用工具**（默认 3 次），配额尽才禁 |
| 3 个未落盘文件的结局 | 只能「口头承诺」或留下半成品 | 有机会真正写下去 |

源码依据 `query_loop.py:786-789` 的注释：

```python
# max_turns / max_tool_calling 硬停前的一次性收尾放行：配额内工具仍可用
# （R3'：不再"一开闸全禁"——收尾恰好最需要落盘；配额尽才禁，文本引导收敛）。
```

以及 `:790-791`：

```python
forced_wrap_up = False
wrap_quota_left = wrap_quota_from_env()
```

**（2）为什么这句话成立**
因为「回合被中断」的真实痛点不是「模型想继续聊天」，而是「**工作区处于不一致状态**」：TodoWrite 里声明了产物、磁盘上没有。这类不一致的修复**只能通过工具落地**（Write/Edit/Bash），文本输出无法改变磁盘。所以一个「全禁工具」的收尾窗恰好把唯一能修问题的通道关掉了——它把「工具预算耗尽」这个本来只是**资源约束**的事件，升级成了**数据完整性事故**（用户得到一份声称完成、实际缺失的工作区）。

**（3）不会阻止。** 配额是**工具调用次数**，不区分调用的是「探索型」还是「落盘型」。设计上接受这一点，理由有三：

1. **引擎不导演（铁律）**：如果系统规定「收尾窗只准调用写工具」，那就是引擎在替模型规划路线——违反「注意力里只出现信息，不出现导演」。配额是资源事实，不是路由指令。
2. **有事实可依**：缺口清单（`build_gap_lines(todos, cwd)` 通过 **stat 磁盘**核对 TodoWrite 的声明）已经把「哪些声明了但不存在」作为**事实**呈现给模型。模型若仍选择探索，那是它的决策——引擎不纠正。
3. **代价有界**：默认配额 3 意味着最坏情况只是多 3 次调用，不改变「回合即将结束」这个事实；超压场景（0099/0100）才会把这件事放大成问题。

**（4）`MAX_GAP_ITEMS = 5`**（`wrap_gap.py:26`）：缺口清单**最多列 5 条**。作用有二：① **上下文预算**——缺口可能有几十条，全列会挤爆 wrap_up 块；② **可操作性**——剩下 3 次配额时，一份 30 条的清单没有行动价值，5 条是「能在配额内处理完」的量级。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的核心是理解「**配额是资源表达，不是行为约束**」。R3' 的修正把「收尾」从一个**禁止性状态**改成了一个**有限资源状态**，这个改动的深层依据正是引擎铁律——引擎可以做「限制」（配额 0 次 = 不许调），但不能做「指挥」（只许调写工具）。而限制只在**执行层**表达：`_eligible_for_early` 的第一条 `if forced_wrap_up: return False`（`:162-163`）是执行层动作，不是提示文本。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0093 三重互斥闸的分工

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | 并发控制 | SessionPool / TurnRunner / engine 三层 | 困难 | 场景设计 | `python/engine/query_engine.py:489-514`；`python/engine/turn_runner.py:143-161`；`python/server/session_pool.py` |

**面试官提问**
XEYO 至少有三层「单会话同时只跑一轮」的保证。请指出三层各自的**位置**、**作用域**、**已知失败模式**，并说明为什么三层都需要（而不是只保留最外层）。

**参考答案要点**
**三层对照**：

| 层 | 位置 | 载体 | 作用域 | 挡的是什么 |
|---|---|---|---|---|
| ① `SessionPool` busy 租约 | `python/server/session_pool.py`（租约续期见 `turn_runner.py:221-229` 的 `touch_busy`） | 池级 busy 表 + 30s 心跳 | HTTP/服务进程 | 同一会话被两个 HTTP 请求同时驱动 |
| ② `TurnRunner` per-session 单 turn | `turn_runner.py:143-161` | `self._turns[session_id]` + `self._lock` + `self._tlock` | 服务进程内 | 同一会话已有一个 detached turn 在跑时的二次 `start` |
| ③ `QueryEngine._turn_active` | `query_engine.py:489-514` | 实例布尔标志 | **单个引擎实例** | 绕过前两层的进程内调用（CLI REPL、旁路脚本） |

`turn_runner.py:155-161` 的原文：

```python
async with self._lock:
    # 临界区（含 threading 锁）内无 await——start 的成员操作对
    # threadpool 读侧原子可见。
    with self._tlock:
        existing = self._turn_locked(session_id)
        if existing is not None and not existing.done.is_set():
            raise RuntimeError(f"turn already running for session {session_id}")
```

**各自的失败模式（为什么不能只留一层）**：

- **只有 ①**：`SessionPool` 在 HTTP 层之上；进程内直接拿引擎（CLI、测试、旁路脚本）不经过它 → 漏检。而且租约是**外部资源**：心跳依赖事件流持续产帧（见 0067），**长静默回合可能被误回收**，此时必须靠更内层的标志兜住。
- **只有 ②**：`TurnRunner` 是「生产者的管理」，它挡的是「第二次 start」；但如果持有引擎实例的代码**自己**发起第二轮（不经 TurnRunner），它管不到。
- **只有 ③**：`_turn_active` 是**实例级**标志，粒度最细也最脆——它只防「同一实例重入」，多实例（多进程 attach 同一会话）它完全看不见。

**为什么三层都需要**：三个作用域**不互相覆盖**——池管「外部并发」、runner 管「进程内 turn 生命周期」、engine 管「实例重入」。去掉任一层都会出现明确的漏检入口。这不是冗余，而是**纵深防御**（注释里管它叫「防御纵深（T39）」）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的陷阱是「看着冗余就想删」。判据是：**逐层问「如果只有这一层，谁能绕过它」**——如果存在这样的调用者，这层就不够。答案里三层都各有绕过的调用者，所以三层都必要。

另一个细节：`turn_runner.py:156-157` 注释强调「临界区（含 threading 锁）内 **无 await**」——`start` 的成员操作要对 threadpool 读侧「原子可见」。这说明 ② 这一层不只要防协程重入，还要防**线程**读侧的观测撕裂。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0094 帧缓冲上限与 reattach 重放的冲突

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner | 可重放窗口 vs 内存上限 | 困难 | 场景设计 | `python/engine/turn_runner.py:21-27,186-220` |

**面试官提问**
场景：一个超长回合产出了 12000 个事件帧（其中若干帧是几百 KB 的工具结果）。客户端在此期间断网 3 分钟，之后重连并请求 reattach 重放。

（1）溢出时缓冲里还剩什么？客户端重连后会看到什么？
（2）`det.last_event_id` 在溢出时是「被丢弃帧中最大的」还是「所有已产出帧中最大的」？
（3）为什么项目接受「重放内容不完整」？如果不接受，可行的替代设计是什么（说清代价）？

**参考答案要点**
**（1）还剩尾部窗口。** 因为裁剪是 `det.frames.pop(0)`（`turn_runner.py:219`），从头弹出 → **保留最新**的帧，直到同时满足 `len ≤ _MAX_BUFFERED_FRAMES(4000)` 且 `bytes ≤ _MAX_BUFFERED_BYTES(8 MiB)`。

客户端重连后：**只能重放缓冲区里剩下的尾部帧**——它会看到「回合的中后段」，**缺失开场部分**。缺失多少取决于帧大小分布：如果都是小 delta 帧，4000 帧可能覆盖大部分过程；如果夹杂几百 KB 的工具结果（如题目所述），8 MiB 会先触发，可能只剩很少几十帧。

**（2）是「所有已产出帧中最大的」。** `turn_runner.py:208`：

```python
det.last_event_id = max(det.last_event_id, int(event_id))
```

它在 `append` **之前**用 `max` 单调更新，且裁剪循环**不碰它**。所以水位表达的是**生产者进度**，与被丢弃的缓冲内容无关。

**（3）为什么接受**：`_evict_terminal_turns_locked` 的 docstring（`:187-190`）给出口径——

> frames 只用于 reattach 重放；**快照已落盘，丢弃旧终态不影响恢复**。

关键在于**恢复不等于重放**：
- 「恢复」需要的是**状态**（这一轮跑到哪、哪些工具在飞、工作区什么样）→ 由快照承载（`turn_snapshot.py`，见 0087）；
- 「重放」需要的是**过程**（逐帧还原用户看到的流式输出）→ 由 frames 承载。

用户断网 3 分钟后重连，最重要的是**知道现在什么状态、接下来会怎样**，而不是逐帧补齐过去 3 分钟已经发生的视觉动画。缺失开场会有一点体验损失（对话流看起来从中途开始），但没有正确性损失。

**可行的替代设计与代价**：

| 替代方案 | 做法 | 代价 |
|---|---|---|
| 全量不裁剪 | 去掉上限 | 长回合内存无界增长 → OOM，且 8 MiB×N 会话会直接压垮服务进程 |
| 落盘帧日志 | 把帧也持久化，重放时读盘 | 每个 delta 都写盘 → IO 放大（对比：`session/record_transcript.py` 已有 transcript 落盘，但那不是逐帧） |
| 在重放前发一个「已截断」标记 | 客户端知道自己缺开场 | 只是**知情**，不解决缺失；属于最小的改进项 |
| 增量快照 + 关键帧 | 定期把「重放到此处的完整状态」快照化 | 复杂度显著上升（等于实现两套快照语义）；与已有 `turn_snapshot` 职责重叠 |

**深化讲解**（面试官参考，不要求候选人全说）
这题的落点是「**重放 ≠ 恢复**」这个区分。很多系统在这上面犯错，是因为把「客户端看到的流」当成了「系统状态」——前者是**表现层缓存**（可以有损），后者是**状态**（必须完整）。XEYO 把两者分开放在 `frames`（有损）与 `turn_snapshot`/`_persist`（无损）两个载体上，所以可以放心裁剪。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0095 goal 轮次推进权的迁移

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | goal_state × query_engine | 41 号语义修正 | 困难 | 场景设计 | `python/engine/query_engine.py:442-451`；`python/engine/goal_state.py:66,172` |

**面试官提问**
场景：用户为一个 goal 设了轮次上限。在会话进行中，用户又**手动追加了 5 条消息**（人类轮，每条都触发了完整的 turn）。

（1）41 号修正之前，这 5 条人类轮会不会消耗 goal 的轮次配额？修正之后呢？
（2）`_maybe_advance_goal_round` 为什么必须在 `turn_succeeded` 为真时才做事？
（3）docstring 里「只记账，不调度」与「goal 层绝不杀 turn / 挡工具 / 阻塞续跑」两句话分别约束了什么？

**参考答案要点**
**（1）修正前会消耗，修正后不会。** 依据 `query_engine.py:449-451`（docstring 原文）：

> **轮次不再在此推进**——41 号语义修正：round 数只由 round driver 的 `admit_round_async` 推进，**人类轮不消耗 cap**。

修正前：`_maybe_advance_goal_round` 是**每个成功 turn 结束**都会走的钩子。如果在这里 bump 轮次，那么用户随口问一句也 +1。结果是：**人类交互越频繁，goal 的自动推进预算越快耗尽**——一个「多说几句话」的用户会发现 goal 提前停摆，而且原因极难归因（用户不会想到「聊天也算轮次」）。

修正后：推进权**收敛到单一入口**（round driver 的 `admit_round_async`），只有「由 driver 主动发起的推进轮」才计数。人类轮只走 `_maybe_advance_goal_round` 的**记账**路径（派生候选），不动 cap。

**（2）为什么必须 `turn_succeeded`**：`query_engine.py:452-454`：

```python
try:
    if not turn_succeeded:
        return
```

理由：「候选完成」这个信号只有在**本轮真的成功了**才有意义。一个被中止、被预算截断、或因 LLM 报错结束的 turn，其 TodoWrite 状态可能是**中途的**（例如已把某个 todo 标 completed，但产物没落盘）。用它去派生「全 done → 候选完成」，会把失败误报成成功——这正是 `derive_candidate(turn_succeeded=True, todos_all_done=...)` 显式要求传入 `turn_succeeded` 的原因（`goal_state.py:147`）。

**（3）两句约束的分工**：

- **「只记账，不调度」**约束的是**这个钩子自己的权力**：它可以更新状态记录，但不能触发新的执行。对应实现就是 `mark_candidate_async(... pending_complete=candidate_is_pending(candidate))`（`:479-483`）——**只写一个布尔字段**。
- **「绝不杀 turn / 挡工具 / 阻塞续跑」**约束的是**故障隔离方向**：goal 是**附加层**，它的任何行为都不能反向影响主循环。对应实现是整个函数体被 `try/except Exception` 包住（`:484-487`），异常只写 debug 日志（`"goal round advance skipped session=%s"`）。

再叠加 `mark_candidate_async` 的「**无变化不写、不 bump revision**」语义（docstring `:447-449`），可以看出一个完整的设计意图：**goal 状态推进必须是低频、幂等、可丢弃的**——频率高会污染修订号，不幂等会重复触发，不可丢弃会拖累主线。

**深化讲解**（面试官参考，不要求候选人全说）
这道题最适合训练「**状态推进权归属**」这个架构判据。经验规则：**如果一个状态推进点有多个入口，迟早会出现「谁在推、推了几次」无法回答的问题**。41 号修正的做法正是把多入口收敛为单入口（round driver），其余入口降级为「只记账」。这与 0093 的「三重闸」看似矛盾（那里是加层，这里是去重），其实同源——**都是让每个机制的作用域唯一且可回答**。

另外注意 `resolved_max_rounds(goal, default_cap=GOAL_ROUND_CAP)`（`goal_state.py:172`）说明 cap 本身可被 goal 覆盖（见 0072），所以「人类轮不消耗 cap」这条规则的实际效果是「**只有 driver 推进的轮才受 cap 约束**」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0096 子代理预算的判据是 scope 还是权限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | subagent_runner | 预算按 scope 推导 | 困难 | 代码阅读 | `python/engine/subagent_runner.py:29-49` |

**面试官提问**
阅读下面代码，回答：决定一个子代理用「可写档」还是「只读档」预算的**判据**是什么？这个判据与 `scheduler.build_tool_whitelist` 的判据是否一致？`_env_int` 对非法输入的行为是什么？

```python
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def subagent_budgets_for_scope(scope_paths: list[str]) -> tuple[int, int]:
    """只读工人更低轮次上限（省钱）；可写保持默认。可用环境变量覆盖。"""
    if scope_paths:
        return (
            _env_int("XEYO_SUB_MAX_TURNS", DEFAULT_SUB_MAX_TURNS),
            _env_int("XEYO_SUB_MAX_TOOL_CALLING", DEFAULT_SUB_MAX_TOOL_CALLING),
        )
    return (
        _env_int("XEYO_SUB_RO_MAX_TURNS", DEFAULT_SUB_RO_MAX_TURNS),
        _env_int("XEYO_SUB_RO_MAX_TOOL_CALLING", DEFAULT_SUB_RO_MAX_TOOL_CALLING),
    )
```

**参考答案要点**
**判据是「`scope_paths` 是否为空」（即子任务有没有声明作用域路径）**，不是「有没有被授予写权限」。取值：

| `scope_paths` | 档位 | 轮次 | 工具调用 |
|---|---|---|---|
| 非空 | 可写档 | `DEFAULT_SUB_MAX_TURNS = 32`（`XEYO_SUB_MAX_TURNS`） | `DEFAULT_SUB_MAX_TOOL_CALLING = 64`（`XEYO_SUB_MAX_TOOL_CALLING`） |
| 空 | 只读档 | `DEFAULT_SUB_RO_MAX_TURNS = 16`（`XEYO_SUB_RO_MAX_TURNS`） | `DEFAULT_SUB_RO_MAX_TOOL_CALLING = 32`（`XEYO_SUB_RO_MAX_TOOL_CALLING`） |

注意 `if scope_paths:` 是 **truthiness 判断**，所以 `None`、`[]`、`[""]`… 唯一区分点是「是否为空列表」。`None` 与 `[]` 同档（都走只读档），因为空列表为假。

**与 `build_tool_whitelist` 是否一致：一致。** `scheduler.py:197-198`：

```python
if not (task.scope or []):
    allow -= WRITE_PATH_TOOLS
```

两处用的是**同一个判据**：`scope` 为空 → 只读。这不是巧合，而是必要的**一致性**——如果预算判据与工具判据不一致，就会出现「按可写档给预算、但工具表里没有写工具」这种自相矛盾的工人（预算白给）或反过来（有写工具但预算按只读档，写到一半被截断）。

**`_env_int` 的边界行为**：
- 空字符串（`""` 或不设）→ 返回 `default`；
- 能转 int → `max(1, int(raw))`，**下限钳制为 1**（配 0 或负数会被抬到 1——不允许「零预算工人」）；
- **非数字字符串** → `except ValueError` → 返回 `default`（不是抛异常，也不是 0）。

`.strip()` 在解析前先做，所以 `" 24 "` 可正常解析。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的隐藏考点是**判据的语义选择**。为什么不用「是否授予了写权限」作判据？因为**授权是运行时可能变化的**（权限裁决逐调用），而预算是**派发前一次性确定**的。用「有没有声明 scope」这个**任务固有属性**作判据是稳定的：任务声明了它要动哪些路径，就按可写给预算；没声明，就当只读工人。

顺带一个工程细节：`max(1, ...)` 与「解析失败回落 default」是两个不同的保守方向——前者保证「配了 0 也要给 1 次」，后者保证「配错了不炸」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0097 子代理侧链的流式旁路与落盘节拍

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | subagent_runner | `_StreamingTeeClient` 与增量落盘 | 困难 | 代码阅读 | `python/engine/subagent_runner.py:71-106` |

**面试官提问**
阅读下列结构定义，回答：`_StreamingTeeClient` 的代理形态是什么？`__getattr__` 的作用是什么？为什么类名里是「**Tee**」？侧链增量落盘的最小间隔被设成了多少、依据是什么（请引用注释原文）？

```python
# 运行中侧链增量落盘的最小间隔（秒）：GUI 每 2s 轮询一次，
# 1s 的落盘节拍足够跟上轮询且几乎不增加 IO 压力。
# ...

class _StreamingTeeClient:
    def __init__(self, inner: Any, on_text_delta: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
    async def stream(self, messages: Any, tools: Any, abort: Any): ...
```

**参考答案要点**
**① 代理形态**：`_StreamingTeeClient` 是一个**透明包装器**——持有 `inner`（真实模型客户端）与 `on_text_delta`（回调）。它只覆写 `stream(...)`，其余所有属性访问经 `__getattr__` **委派给 `inner`**。

`__getattr__` 的意义：Python 的属性查找只在常规路径失败时才调用 `__getattr__`，因此这个类可以「**只实现我要拦的那一个方法，其余全部穿透**」——不用继承、不用手写几十个转发方法。这是装饰器模式在 Python 里的惯用写法（代理/Decorator）。

**② 为什么叫 Tee**：借自 Unix 的 `tee` 命令——数据流「**一份继续往下走，一份复制到旁路**」。这里的旁路是 `on_text_delta` 回调：模型流式输出的每个文本增量，一边照常交给上层（不改变原有行为），一边复制给回调（供实时展示/增量落盘）。

必须强调的一个性质：**tee 不改变主数据流**。子代理拿到的 chunk 序列与不包装时完全一致（否则会改变模型行为）。这也解释了为什么不直接把落盘逻辑写进子代理主循环——**保持主路径纯净，旁路挂在包装层**。

**③ 落盘节拍 = 1 秒**（注释原文，`subagent_runner.py:71-73`）：

> 运行中侧链增量落盘的最小间隔（秒）：**GUI 每 2s 轮询一次**，**1s 的落盘节拍足够跟上轮询且几乎不增加 IO 压力**。

依据是**消费者节拍**：GUI 2s 轮询一次，生产者只要比它快就够（1s < 2s）。再快没有收益——用户看不到更细的更新，只会增加 IO；再慢则会看到明显滞后（最坏 2s 轮询 + 2s 落盘 = 4s 延迟）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在「**生产节拍由消费节拍决定**」这个判据。很多系统在类似地方凭直觉调参数（例如设成 100ms「更实时」），结果是 IO 压力上去了、用户感知不变。第 71-73 行注释难得地把推理写出来了：**消费端 2s ⇒ 生产端 1s 足够**。

另一处值得记的设计：增量落盘的存在意味着子代理的输出**有两份持久化路径**——侧链增量（高频、可能部分）与回合结束时的完整落盘（`_flush_live_transcript`，`subagent_runner.py:370`）。高频那份的价值是「进程崩溃时也有东西可看」，而不是「替代最终落盘」。

（说明：`stream` 内部的具体 tee 实现（`:92-106`）不在本批逐行展开；上面关于「不改变主流」的结论由类名、构造签名与 `__getattr__` 委派形态可确定，如需逐行核对请直读该方法。）



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0098 引导机制的 fail-open 方向

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop × wrap_gap | 缺口清单的失败降级 | 困难 | 场景设计 | `python/engine/query_loop.py:132-152`；`python/engine/wrap_gap.py:26,31` |

**面试官提问**
`_publish_wrap_guide` 在异常时做了**两层**降级，都选择「静默」。请说明：

（1）为什么这里必须是 **fail-open**（失败即空）而不是 fail-closed（失败则阻止进入收尾窗）？
（2）第二层 `except` 里还要再 `publish_gap("")` 的意义是什么？
（3）这个机制的 docstring 写着「纯事实呈现，不裁决不拦截」——请说明「不裁决」与「不拦截」分别对应代码里的哪个事实。

**参考答案要点**
`query_loop.py:132-152`（原文）：

```python
def _publish_wrap_guide(tools: Any, cwd: str, quota: int) -> None:
    """进入收尾窗时发布缺口清单 + 配额（wrap_gap 模块级，pre_llm_inject 消费）。

    从 TodoWrite 工具的当前清单读 output 声明,stat 磁盘缺口;失败 fail-open
    为空(不挡 wrap 主路径)。纯事实呈现,不裁决不拦截。
    """
    try:
        from engine.wrap_gap import build_gap_lines, compose_guide_text, publish_gap

        todo_tool = tools.get("TodoWrite") if tools is not None else None
        todos = todo_tool.current_todos() if todo_tool is not None else None
        lines = build_gap_lines(todos, cwd)
        text = compose_guide_text(quota, lines)
        publish_gap(text if text.strip() else "")
    except Exception:  # noqa: BLE001 — 缺口清单只是引导增强，失败静默
        try:
            from engine.wrap_gap import publish_gap

            publish_gap("")
        except Exception:  # noqa: BLE001
            pass
```

**（1）为什么必须 fail-open**：docstring 里给的判据是「**不挡 wrap 主路径**」。

关键在**依赖倒置**：`_publish_wrap_guide` 是**收尾窗**的**附加增强**——真正决定「进不进收尾窗」的是 `budget.prepare_next_turn()` 返回 False 这个**预算事实**（`:800-805`）。如果这里 fail-closed（异常 → 阻止进入收尾窗），那就变成了「**清单生成失败 ⇒ 回合不能收尾**」——一个**表现层**组件的故障反过来阻断了**资源层**的状态转移。后果是回合可能进入既不能继续跑（预算已尽）、又不能结束（收尾被阻断）的死状态。

保守方向在这里是**反过来**的：越是「增强/引导/展示」类组件，失败越应该静默降级；越是「资源/安全」类组件，失败才应该 fail-closed。判断依据是**它在链路中的位置**，不是「保守总是安全」。

**（2）第二层 `publish_gap("")` 的意义**：`wrap_gap.py:31` 有一个**模块级槽位** `_CURRENT_GAP`。`pre_llm_inject` 按该槽位的内容装配 T_now 的 wrap_up 块。

- 第一层降级：生成失败 → 直接调 `publish_gap("")` 清空；
- 第二层降级：**连清空都失败**（例如 import 失败）→ 但此时槽位里可能残留**上一轮**的内容。

所以第二层 `except: pass` 接受的风险是「**可能残留上一次的缺口清单**」。为什么接受：① 残留内容是**同类信息**（上一次的缺口），不会误导到别的语义；② 清空操作本身已经是最底层的动作，它失败意味着环境严重异常，此时不该再往上抛；③ `wrap_gap.py` 的 `_CURRENT_GAP` 会在下一次成功调用时被覆盖，残留不是永久污染。

**（3）「不裁决」与「不拦截」对应的事实**：

| 措辞 | 代码事实 |
|---|---|
| **不裁决** | 只 `publish_gap(text)` 到槽位——**没有任何 `if` 去判断模型该不该收尾**，也没有改任何预算/权限状态。它写的是「Todo 声明了 X，磁盘上没有 X」这类**存在性事实**，判断题留给模型。 |
| **不拦截** | 全程没有 `return False` / 没有修改 `forced_wrap_up` / 没有改 `wrap_quota_left`。窗口的开关与配额**完全不受本函数影响**——它只是一个「公告板」。 |

数据来源也印证「事实」定位：`build_gap_lines(todos, cwd)` 的 todo 来自 **`TodoWrite.current_todos()`**（工具的真实状态），缺口靠 **stat 磁盘**核对（不是模型自述、不是推断）。这是「**只给信息**」的直接落地。

**深化讲解**（面试官参考，不要求候选人全说）
这题把三个层次串起来：① **失败方向的判据**（增强层 fail-open、资源层 fail-closed）；② **模块级槽位的生命周期**（残留与覆盖）；③ **信息纪律的代码投影**（不裁决 = 无分支判断，不拦截 = 无状态修改）。

一个容易误答的点：以为「不裁决」是指「不调用权限系统」。它真正的意思是「**不对模型的完成状态下判断**」——只把事实摆出来。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
给出一个**最小修改方向**，并说明改完之后哪些既有行为会跟着变。

---

### XEYO-QA-0099 长静默回合下的租约竞态

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | turn_runner × session_pool | 心跳依赖产帧的隐含前提 | 超压 | 故障排查 | `python/engine/turn_runner.py:221-229`；`python/engine/query_engine.py:489-510` |

**面试官提问**
故障现象：一个回合里模型发起了一次**长时间无输出的外部命令**（例如某个网络工具挂住 20 分钟），期间事件流几乎无帧。与此同时客户端断连 5 分钟后重连。

（1）请指出「busy 租约可能被 stale 回收」这条推断链的每一环，并给出源码依据。
（2）回收真的发生后，会不会有两个 turn 同时驱动同一会话？请逐层分析（三层闸，见 0093）。
（3）这个缺口是「设计错误」还是「已知边界」？如果你要加固，最小改动是什么？请说明为什么这**不是**应试性修改。

**参考答案要点**
**（1）推断链逐环**

| 环节 | 事实 | 依据 |
|---|---|---|
| ① 心跳只在「消费到帧」时检查 | `now = time.monotonic(); if now - last_touch >= 30.0: ... touch_busy(...)` 位于 `async for ... producer()` 的循环体内 | `turn_runner.py:207,221-229` |
| ② 长静默 ⇒ 循环体不执行 | 事件流无帧时，列表推导式的迭代体会被挂起（`async for` 等不到下一个元素） | 同上（结构推得） |
| ③ 心跳停 ⇒ 已过期的租约无人续期 | `touch_busy` 不再被调用 | `turn_runner.py:227` |
| ④ 池侧将过期租约判为 stale 并回收 | 池的 stale 回收是**池的职责**（`turn_runner.py:221` 注释原文即为「防止长回合被 stale 回收」，说明池确有该机制） | `python/server/session_pool.py`（**该处回收阈值未在本批逐行核对，标注「待确认」**） |
| ⑤ 客户端重连可能触发新的请求路径 | 重连后客户端可能重新发消息（而非仅 reattach） | 客户端行为，非本批源码事实 |

**必须显式指出的问题**：环节 ① 的注释承认了这套心跳的**隐含前提**——「**长回合必然持续产帧**」。而本题场景恰好是「长回合 + 长静默」，前提不成立。所以这条链的**根因不是回收阈值太小，而是心跳源的语义选错了**：用一个「可能有静默期的数据流」当心跳源。

**（2）会不会出现双驱动？逐层看**

| 层 | 能否挡住 | 依据 |
|---|---|---|
| ① `SessionPool` busy 租约 | **可能挡不住**——如果租约刚被回收，池认为「无人在跑」，新请求可以正常获取租约 | 环节 ④ |
| ② `TurnRunner._turns[session_id]` | **能挡住**：`start` 在临界区内检查 `existing is not None and not existing.done.is_set()` → 抛 `RuntimeError(f"turn already running for session {session_id}")` | `turn_runner.py:158-161` |
| ③ `QueryEngine._turn_active` | **能挡住同一实例的重入**（`RuntimeError`，消息含 `busy`） | `query_engine.py:500-504` |

**结论（单进程内）**：即使租约被误回收，② ③ 两层仍会挡住第二次驱动——第二层是**决定性**的，因为 detached turn 的存在与池的租约状态无关，只要 task 还没结束（`done` 未 set），`start` 就拒绝。

**结论（跨进程）**：如果第二个驱动来自**另一个进程**（例如第二个 attach 到同一会话的 CLI/服务进程），则 ② ③ 都在各自进程的内存里，**互相看不见**——这是真正的缺口。这一点属于推断，**标注为待确认**（需要核对 `session_pool.py` 是否使用跨进程文件锁或 `.xeyo` 下的租约文件）。

**（3）性质判断与最小加固**

**性质**：属于「**已知边界 + 语义选取不当**」的混合，不是纯粹的设计错误。理由：② ③ 两层已经把单进程内的后果限制到「拒绝第二次驱动」（用户会看到 `busy` 错误而不是数据损坏），这本身是**可接受的降级**。真正的缺陷是「心跳源的语义不匹配」，它导致「**误报 stale**」这一**假信号**，进而可能触发不必要的回收动作。

**最小加固（单点、不改语义）**：把心跳从「消费帧时顺带续期」改为「**独立的时间驱动续期**」——即用 `asyncio` 周期任务（或已有的 `_SUBSCRIBE_TICK_S = 12.0` 那类节拍，见 0083）每 <30s 无条件 `touch_busy` 一次，其余逻辑不变。

**为什么不是应试性修改**：
- **R1 产品受益**：真实产品里长静默工具（网络请求、长构建）非常常见，误回收会让长任务表现为「莫名被抢占」；修复直接受益于真实使用；
- **R2 无评测分支**：改动是通用的（对所有回合生效），没有针对评测场景的特判；
- **R3 信息纪律**：不新增任何模型可见文本；
- **R4 收益可证伪**：可以用「长静默回合 + 并发请求」的复现用例验证「不再出现 stale 误报」，判据是运行时状态而非评测分数。

**深化讲解**（面试官参考，不要求候选人全说）
这道题要求的能力是**区分「根因」与「阈值调参」**。把 30s 调大（例如 300s）能缓解本例，但静默 6 分钟的场景又会复现——**阈值永远追不上静默时长**。根因是**心跳源的选取**：应该用「时间」（无条件的时钟驱动）而不是「数据」（可能有静默期的事件流）。

这类「用数据流当心跳源」的缺陷在分布式系统里非常典型（Kafka consumer heartbeat 独立于 poll 就是这个道理）。把它放进题库，是因为**推理链清晰、源码依据完整、加固方案单点**——非常适合考察排查能力。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请给出真实故障的**复现步骤**，并说明为什么它在常规测试里抓不到。

---

### XEYO-QA-0100 四机制叠加时的注意力与信息丢失

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | query_loop 装配 | 重复提示 / 结果折叠 / 零命中 / 收尾清单 | 超压 | 场景设计 | `python/engine/query_loop.py:772-791`；`python/engine/repeat_guard.py:37-45,288`；`python/engine/wrap_gap.py:26` |

**面试官提问**
在一次超长回合的收尾阶段，下列四个机制**可能同时生效**：

1. `RepeatCallGuard` 的递进提示（阈值 3/5/8）；
2. `IdenticalResultFold` 的同签名同输出字节级折叠；
3. `ZeroHitTracker` 的零命中提示（不同查询累计 ≥2）；
4. `_publish_wrap_guide` 的缺口清单（≤5 条）+ 配额。

（1）四个机制各自把什么写进模型可见上下文？它们是否都会「改变模型看到的事实」？
（2）四者叠加时**最大的风险**是什么？请至少写出两条具体的失败形态。
（3）XEYO 用了哪些手段控制这个风险？请引用源码中的具体机制（含「每 submit 新建」与「轮首清残留」两处）。
（4）按引擎铁律检验：这四个机制中，哪个**最容易**被质疑「在导演模型」？为什么它仍然不算违反？

**参考答案要点**
**（1）四机制写入内容与「是否改变事实」**

| # | 机制 | 写入什么 | 是否改变事实 |
|---|---|---|---|
| 1 | `RepeatCallGuard` | 重复调用达到 3/5/8 档时的**提示文本** | 不改变工具结果；**新增**一条状态描述 |
| 2 | `IdenticalResultFold` | 把重复的相同结果**替换为一行 `[fold]` 事实**写入 store | **改变**（这是唯一真正改内容的机制——原文被折叠） |
| 3 | `ZeroHitTracker` | 多次空结果后**追加中立提示** | 不改变已有结果；**追加**一条事实 |
| 4 | wrap guide | 缺口清单（Todo 声明 vs 磁盘 stat）+ 剩余配额 | 不改变任何结果；只有**新增**（且是纯事实） |

源码依据：`query_loop.py:774-785`（四者的构造与注释）、`:790-791`（配额）、`repeat_guard.py:39`（阈值）、`repeat_guard.py:288`（零命中触发）、`wrap_gap.py:26`（5 条上限）。

**（2）最大的风险：信息被「折叠掉」或「淹没掉」——即上下文里的事实与真实执行痕迹之间出现不可解释的差异。**

**失败形态 A —— 折叠导致模型失去唯一的差异信号。**
`IdenticalResultFold` 是**字节级**判等（注释原文「同签名·同输出字节级折叠」）。设想：模型连续两次运行同一条命令，第二次输出**恰好逐字节相同**——但这一次的语义完全不同（例如第一次是「本来就该没输出」，第二次是「本该有输出但没输出」）。折叠后模型看到一行 `[fold]`，**无法区分这两次**。若此时零命中提示或重复提示同时出现，模型手上只剩「提示」没有「原始证据」，可能得出错误结论。

**失败形态 B —— 多源提示争夺注意力，把「收尾」变成「回应提示」。**
收尾阶段本应聚焦落盘，此时却同时收到：重复提示（第 5 档）、零命中提示、缺口清单 5 条 + 配额 3 次。四条信息都「值得回应」，但配额只够 3 次工具调用。模型很可能把配额**花在回应提示上**（例如为了消除重复提示而改变调用形态），而不是落盘——**提示本来是要改善行为，结果挤掉了真正该做的事**。

副形态：`RepeatCallGuard` 的提示是**递进**的（3→5→8），在长回合里会**反复出现同一主题**的多条提示，占用上下文预算的同时降低每条信息的边际价值。

**（3）控制手段（源码机制）**

| 手段 | 依据 | 作用 |
|---|---|---|
| **每次 submit 新建** | `query_loop.py:772-774`：「每次 submit 新建即用户输入级重置」；`IdenticalResultFold` 同样「每 submit 新建 → 与 repeat_guard 同步的用户输入级重置」（`:776-778`） | 计数器/折叠状态**不跨用户输入累积**，避免长会话里阈值被历史撑爆 |
| **轮首清残留提醒** | `query_loop.py:775`：`clear_advice()  # 轮首清残留提醒，T_now 块只反映本轮状态` | 防止上一轮的提示文本残留到本轮（`repeat_guard.py:83` 的 `_CURRENT_ADVICE` 是模块级槽位，必须显式清） |
| **缺口清单上限 5** | `wrap_gap.py:26` `MAX_GAP_ITEMS = 5` | 控制 wrap_up 块的上下文预算与可操作性（见 0092） |
| **零命中阈值 ≥2 且要求「不同查询」** | `repeat_guard.py:288`；`query_loop.py:782` 注释 | 避免单次空结果就插话 |
| **折叠只针对「字节级相同」** | `query_loop.py:776-777` 注释 | 把误折叠面压到最小（只折叠完全一致的结果） |
| **守卫不拦截** | `repeat_guard.py:41-45`（`ACTION_BLOCK = ACTION_ADVICE`） | 提示不会改变执行路径，模型仍有完整行动自由（见 0062） |

**（4）最容易被质疑「导演」的是 `RepeatCallGuard`。**

理由：它直接对「模型反复做同一件事」施加**注意力压力**，措辞上最接近「你在重复，别这样」。**但它仍不违反铁律**，判据有三条：

1. **产物是信息而非指令**：它输出的是一句状态描述（次数事实），不是「不要再调用 X」；
2. **执行层不配合**：`ACTION_BLOCK = ACTION_ADVICE` 说明**没有任何执行层拦截**与它联动——提示不改变工具是否执行；
3. **引擎不裁决路径**：它不禁止、不替换、不重排工具，模型完全可以选择继续重复 100 次（直到预算耗尽）。

换言之，XEYO 承认「**信息可以影响决策**」，这正是它追求的效果；它禁止的是「**用指令代替信息**」。区别在于：前者把选择权留在模型手里，后者把选择权拿走了。

**深化讲解**（面试官参考，不要求候选人全说）
这道题是整批的收束题，考的是**在多个「看起来都合理」的机制同时生效时，能否识别它们的相互作用**。三个要点：

1. **区分「新增信息」与「修改信息」**——四个机制里只有 `IdenticalResultFold` 改写了已有内容，因此它的风险性质与其他三个不同（其余是「多说一句」，它是「少给一段」）；
2. **提示会竞争资源**——收尾窗的配额是稀缺资源，任何消耗注意力的提示都可能间接挤占它；
3. **铁律的判据是「选择权归属」**——不是「有没有影响」，而是「有没有剥夺选择」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请给出真实故障的**复现步骤**，并说明为什么它在常规测试里抓不到。

---

## 批次自检表（B02）

| 项 | 结果 |
|---|---|
| 题号连续性 | XEYO-QA-0051 – XEYO-QA-0100，**无跳号无重号** |
| 难度配比实测 | 简单 **22**（0051–0072）/ 中等 **18**（0073–0090）/ 困难 **8**（0091–0098）/ 超压 **2**（0099–0100）= **50** ✅ 与矩阵一致 |
| 题型分布 | 单选 12 / 多选 5 / 判断 1 / 简答 21 / 场景分析 8 / 代码阅读 3 / 故障排查 1（无重复主题） |
| 覆盖子模块 | query_loop / query_engine / turn_runner / budget / repeat_guard / wrap_gap / subagent_runner / scheduler / plan / goal_state / turn_snapshot / title / task_state（engine 包 13 个文件） |
| 重复性检查 | 已合并潜在重复：「终态 turn 上限」与「驱逐排序」原为两题，合并入 0065；「早读准入」在 0058（事实）与 0091（分析）分角度，答案不重叠 |
| 来源可追溯性 | 全部 50 题的「来源依据」均指向本批实际打开核对的 `文件:行号`；**未出现推测性行号** |
| 待确认条目 | **2 处**：① 0099 中 `session_pool.py` 的 stale 回收阈值未逐行核对；② 0099 中「跨进程是否使用文件锁」未核对。二者均在题内显式标注 |
| 边界遵守 | 未涉及 B03（容错/工作区账本）、B07（权限裁决）、B11（rewind）主题 |
| 未覆盖但已计划 | `task_state.SessionTaskState.set_status/snapshot`（仅作 0072 侧证）、`aging.py`、`prof_stats.py`、`first_sniff.py`、`todo_hint.py`、`skill_preinvoke.py`、`workspace_context.py`、`session_presence.py`（1110 行级）、`process_narration.py`、`live_agents.py` → 归 B03/B16 或后续补批 |
