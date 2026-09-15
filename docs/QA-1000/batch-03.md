# XEYO QA 题库 · 第 3 批（B03）

> 题号范围：**XEYO-QA-0101 – XEYO-QA-0150**
> 主题：engine 容错与状态账本（abort / 预算阶梯 / 上下文压缩 / 重复折叠 / 输出老化 / 收尾窗广播 / 阶段计时 / 行为账本 / 进程账本 / 工作区锁与修订 / 写路径 / 影子 git / 工作区恢复）
> 难度配比：简单 16 / 中等 18 / 困难 14 / 超压 2
> 事实基线（本批实际打开读过的文件与实测行数）：
> `abort.py`(42, 全文) · `aging.py`(96, 全文) · `wrap_window.py`(63, 全文) · `stage_clock.py`(91, 全文) · `repeat_fold.py`(140, 全文) · `workspace_revision.py`(109, 全文) · `budget.py`(492) · `compact.py`(352) · `loop_ledger.py`(247) · `process_ledger.py`(423) · `workspace_lock.py`(325) · `write_store.py`(449) · `shadow_git.py`(210) · `prof_stats.py`(91) · `workspace_restore.py`(645)
> **边界声明**：`query_loop` / `query_engine` / `turn_runner` / `subagent_runner` / `scheduler` 属 **B02**；permissions 归 **B07**；rewind 快照服务归 **B11**（本批只从「工作区恢复事务」角度涉及 `workspace_restore.py`）。

---

## 本批题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0101 | 简单 | 概念确认 | AbortController 成员 | `abort.py:9-30` |
| 0102 | 简单 | 概念确认 | LinkedAbortController 语义 | `abort.py:33-42` |
| 0103 | 简单 | 概念确认 | 输出老化默认开关 | `aging.py:19,40-52` |
| 0104 | 简单 | 机制解释 | 老化两档常量 | `aging.py:22-25` |
| 0105 | 简单 | 概念确认 | 老化豁免集 | `aging.py:26-27,75-77` |
| 0106 | 简单 | 概念确认 | 收尾窗的传播载体 | `wrap_window.py:42` |
| 0107 | 简单 | 机制解释 | WrapWindow 字段与未知值 | `wrap_window.py:33-38` |
| 0108 | 简单 | 机制解释 | StageClock 常规用法 | `stage_clock.py:14-59` |
| 0109 | 简单 | 概念确认 | compact 四常量 | `compact.py:24-27` |
| 0110 | 简单 | 概念确认 | 截断后缀字面量 | `compact.py:27` |
| 0111 | 简单 | 概念确认 | 行为账本默认阈值 | `loop_ledger.py:52` |
| 0112 | 简单 | 概念确认 | 折叠默认触发次数 | `repeat_fold.py:32` |
| 0113 | 简单 | 机制解释 | 折叠行前缀与三种文案 | `repeat_fold.py:42-54` |
| 0114 | 简单 | 概念确认 | WriteStore 分片数 | `write_store.py:170` |
| 0115 | 简单 | 概念确认 | 工作区修订号格式 | `workspace_revision.py:76,109` |
| 0116 | 简单 | 机制解释 | 进程账本的类型与条目 | `process_ledger.py:28,35` |
| 0117 | 中等 | 机制解释 | prepare_next_turn 不增加 Turn | `budget.py:251-256` |
| 0118 | 中等 | 代码阅读 | grace 启动与耗尽 | `budget.py:267-279` |
| 0119 | 中等 | 场景设计 | grace-cliff 修复 | `budget.py:285-320` |
| 0120 | 中等 | 机制解释 | 运行时提醒的去重与排序 | `budget.py:330-346` |
| 0121 | 中等 | 机制解释 | 提醒的一次性消费 | `budget.py:322-328` |
| 0122 | 中等 | 机制解释 | 工具配对区间与尾部保护 | `compact.py:69,87,95` |
| 0123 | 中等 | 机制解释 | project 与 project_incremental | `compact.py:125,286` |
| 0124 | 中等 | 代码阅读 | 工具结果截断 | `compact.py:24,167` |
| 0125 | 中等 | 机制解释 | 折叠双档判定 | `repeat_fold.py:97-135` |
| 0126 | 中等 | 机制解释 | 等价档的总开关 | `repeat_fold.py:68-70` |
| 0127 | 中等 | 机制解释 | 行为账本三信号 | `loop_ledger.py:52,142-156` |
| 0128 | 中等 | 场景设计 | paths=() vs paths=None | `workspace_revision.py:76-100` |
| 0129 | 中等 | 机制解释 | 只读元数据指纹 | `workspace_revision.py:47-74` |
| 0130 | 中等 | 机制解释 | 分片锁与提交形态 | `write_store.py:170-194` |
| 0131 | 中等 | 机制解释 | base hash 校验 | `write_store.py:389` |
| 0132 | 中等 | 机制解释 | ShadowGit 的定位与调用面 | `shadow_git.py:54-81` |
| 0133 | 中等 | 机制解释 | 进程账本 reap/sweep | `process_ledger.py:200,237,276` |
| 0134 | 中等 | 机制解释 | StageClock sink 幂等 | `stage_clock.py:61-74` |
| 0135 | 困难 | 场景设计 | 老化默认关的取舍 | `aging.py:1-13,40-52` |
| 0136 | 困难 | 场景设计 | 存根措辞的中立性 | `aging.py:80-90` |
| 0137 | 困难 | 场景设计 | 收尾窗广播只改「怎么做」 | `wrap_window.py:1-15` |
| 0138 | 困难 | 代码阅读 | 增量投影的一致性 | `compact.py:286-330` |
| 0139 | 困难 | 场景设计 | 租约 stale 判定与回收 | `workspace_lock.py:75-141` |
| 0140 | 困难 | 机制解释 | 租约生命周期四方法 | `workspace_lock.py:217,265,286,320` |
| 0141 | 困难 | 场景设计 | 原子写与语法前置校验 | `write_store.py:93-125,400` |
| 0142 | 困难 | 场景设计 | 多文件事务 | `write_store.py:364` |
| 0143 | 困难 | 场景设计 | WAL 与安全回滚 | `workspace_restore.py:60-96,369` |
| 0144 | 困难 | 代码阅读 | 路径校验与 symlink 处理 | `workspace_restore.py:97,180,217` |
| 0145 | 困难 | 代码阅读 | 修订号的三类 fail-safe 分支 | `workspace_revision.py:50-59` |
| 0146 | 困难 | 机制解释 | git 字节解码的编码回退 | `shadow_git.py:12-52` |
| 0147 | 困难 | 机制解释 | 墙钟阈值与 USD 水位 | `budget.py:257-266,231` |
| 0148 | 困难 | 代码阅读 | 百分位与分组统计 | `prof_stats.py:13,25,52,87` |
| 0149 | 超压 | 故障排查 | 三锁并发写竞态 | `write_store.py` + `workspace_lock.py` + `workspace_revision.py` |
| 0150 | 超压 | 场景设计 | 崩溃恢复的四源一致性 | `workspace_restore.py` + `process_ledger.py` + `shadow_git.py` |

---

### XEYO-QA-0101 AbortController 的成员面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | abort | 中断控制器 | 简单 | 概念确认 | `python/engine/abort.py:5-30` |

**面试官提问**
`python/engine/abort.py` 里 `AbortController` 提供了哪些成员？请说明它的成员面。

**参考答案要点**
**正解：A（`aborted`（属性）、`abort()`、`reset()`、`raise_if_aborted()`，另有异常类 `Aborted`）**
`abort.py:5-30`（原文）：

```python
class Aborted(Exception):
    """循环内检测到中断时抛出，由 query_loop 转成 StoppedEvent。"""


class AbortController:
    def __init__(self) -> None:
        """中断控制器。"""
        self._aborted = False

    @property
    def aborted(self) -> bool:
        """是否已中断。"""
        return self._aborted

    def abort(self) -> None:
        """中断循环。"""
        self._aborted = True

    def reset(self) -> None:
        """重置中断状态。"""
        self._aborted = False

    def raise_if_aborted(self) -> None:
        """如果已中断，则抛出 Aborted 异常。"""
        if self.aborted:
            raise Aborted()
```

四个成员：`aborted`（**property** 而非方法）、`abort()`（无返回值，只置位）、`reset()`、`raise_if_aborted()`。异常类是 `Aborted`，docstring 点明它的去向：「**由 query_loop 转成 StoppedEvent**」——即异常只是循环内的**控制流手段**，最终对外的表达是事件（不是异常）。

**深化讲解**（面试官参考，不要求候选人全说）
细节容易错的两处：① `aborted` 是 **property**（B 选项写成方法）；② `abort()` 返回值是 `None`（D 选项编了 bool）。`reset()` 的存在说明控制器是**可复用**的——一个回合结束后重置，供下一回合使用（而不是每回合新建对象）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`aborted`（方法）、`cancel()`、`clear()`，异常类为 `Cancelled`」——说明没抓住本题的分界（B）。
- 答成「只有 `abort()` 与 `aborted`，无重置能力」——说明没抓住本题的分界（C）。
- 答成「`abort()` 返回 `bool` 表示是否成功中断」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0102 LinkedAbortController 的继承方向

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | abort | 单工具超时的局部中止 | 简单 | 概念确认 | `python/engine/abort.py:33-42` |

**面试官提问**
`LinkedAbortController(parent)` 的语义是：

**参考答案要点**
**正解：B（**自身 `abort()` 不污染父控制器，但自身 `aborted` 会继承父级的 `aborted`**）**
`abort.py:33-42`（原文）：

```python
class LinkedAbortController(AbortController):
    """单工具超时用的局部 abort：自身 abort 不污染父控制器，但继承父级 aborted。"""

    def __init__(self, parent: AbortController) -> None:
        super().__init__()
        self._parent = parent

    @property
    def aborted(self) -> bool:
        return self._aborted or self._parent.aborted
```

两个方向的语义**刻意不对称**：

| 方向 | 结果 | 含义 |
|---|---|---|
| 父 → 子 | **传播**（父 abort 后子的 `aborted` 立即为真） | 「整个回合被中止」必须让所有局部任务感知 |
| 子 → 父 | **不传播**（子的 `_aborted` 是独立字段） | 「这一个工具超时/被取消」不应该把整个回合干掉 |

**用途**：docstring 明确——「**单工具超时用的局部 abort**」。某个工具（例如一次长 Bash）超时，只需要中止它自己；回合必须继续（模型需要看到「这个工具超时了」的结果并决定下一步）。反过来，用户点停止时必须能立刻终止所有在飞的局部任务。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的考点是**方向性**：继承 `AbortController` 但把 `aborted` 改成 `property` 做「或」运算，就得到了一个「**单向只增**」的中止视图。C 选项说共享同一字段——那样子的 abort 会污染父（就变成双向了）；D 选项把方向说反了。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「自身 `abort()` 会同时中止父控制器」——说明没抓住本题的分界（A）。
- 答成「与父控制器完全等价（共享同一个 `_aborted` 字段）」——说明没抓住本题的分界（C）。
- 答成「只能中止父控制器，自身不可被中止」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0103 工具输出老化的默认开关

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | aging | T27 默认关 | 简单 | 概念确认 | `python/engine/aging.py:19,40-52` |

**面试官提问**
`XEYO_TOOL_AGING`（工具输出老化）默认是开还是关？开启/关闭的判定走哪条通道？docstring 给出的默认关闭理由是什么？

**参考答案要点**
**正解：B（**默认关**；走 `memory.memory_switches.get_value`（以 GUI settings.memory 为准）；理由是「**toolout 占位的恢复机制落地前保持关闭，避免原文不可找回**」）**
`aging.py:40-52`（原文）：

```python
def aging_enabled() -> bool:
    """T27：默认**关**；显式 ``1/true/on/yes`` 开启。

    toolout 占位的恢复机制未落地前保持默认关——老化即「原文从投影消失
    且无处找回」，与证据先行（T1/T27 spill）方向冲突。
    以 GUI settings.memory 为准（memory_switches.get_value），空/非法残留环境变量忽略。
    """
    from memory.memory_switches import get_value

    raw = get_value(ENV_KEY).strip().lower()
    if not raw:
        return False
    return raw in ("1", "true", "on", "yes")
```

三个要点：
1. `ENV_KEY = "XEYO_TOOL_AGING"`（`aging.py:19`），判定真值集合是 `("1","true","on","yes")`；
2. **读取通道不是 `os.environ`**，而是 `memory.memory_switches.get_value(ENV_KEY)`——注释明说「以 **GUI settings.memory 为准**」，「空/非法残留环境变量忽略」；
3. **默认关**，理由是设计冲突（见下）。

**默认关闭的理由（`aging.py:1-13` 的模块 docstring）**：

> 开关 ``XEYO_TOOL_AGING``（**T27：默认关**；设 ``1/true/on`` 显式开启——toolout 占位的恢复机制落地前保持关闭，避免原文不可找回）

以及 `aging_enabled` 的 docstring：

> 老化即「**原文从投影消失且无处找回**」，与**证据先行（T1/T27 spill）**方向冲突。

即：老化会从投影里删掉工具输出原文，而「找回原文」的机制（spill / toolout 占位恢复）**还没落地**。在「删得掉、找不回」的状态下默认开启，会造成不可逆的信息丢失——所以宁可保留冗余也不默认开。

**深化讲解**（面试官参考，不要求候选人全说）
这题的完整答案需要串起三处：**默认关 + 通道是 GUI 设置 + 理由是恢复机制缺失**。只答「省 token」是把它理解反了——老化是**省上下文预算**的手段，但项目因为**证据完整性**优先级更高而默认关闭。

`get_value` 而非 `os.environ` 也值得注意：这说明 XEYO 的开关有**分级配置通道**（GUI 设置 > 残留环境变量），与 `AGENTS.md` 里「以 GUI settings.memory 为准」的口径一致。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「默认开；读环境变量；理由是省 token」——说明没抓住本题的分界（A）。
- 答成「默认关；读 `~/.xeyo/settings.json`；理由是性能」——说明没抓住本题的分界（C）。
- 答成「默认开；读 `.xeyo-policy.json`；理由是上下文预算」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0104 老化的两档常量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | aging | 富存根与远档折叠 | 简单 | 机制解释 | `python/engine/aging.py:20-27,80-90` |

**面试官提问**
`aging.py` 中 `AGING_VERSION`、`FOLD_AFTER`、`STUB_SUMMARY_MAX` 的值各是多少、作用是什么？`build_stub(...)` 在 `folded=True` 与 `folded=False` 时分别产出什么文本？

**参考答案要点**
`aging.py:20-27`：

```python
AGING_VERSION = 1

#: 远档折叠：距冻结边界超过该消息数的存根退化为短形式（确定性，增量投影一致）
FOLD_AFTER = 64
#: 富存根摘要上限字符数（净化后）
STUB_SUMMARY_MAX = 60
#: 结构化结果豁免集（UI dock / 挂起语义依赖其原文）
EXEMPT_TOOLS = frozenset({"TodoWrite", "AskUserQuestion"})
```

| 常量 | 值 | 作用 |
|---|---|---|
| `AGING_VERSION` | `1` | 老化策略版本号（语义变更时递增，便于识别历史批次） |
| `FOLD_AFTER` | `64` | 距冻结边界的**消息数**超过 64 时，存根退化为短形式 |
| `STUB_SUMMARY_MAX` | `60` | 富存根的**摘要**净化后上限（字符） |

`build_stub`（`aging.py:80-90`）：

```python
def build_stub(tool_name: str, use_id: str, summary: str, *, folded: bool) -> str:
    """生成存根文本。folded=True 为远档短形式；两档均确定性、单行。

    总长约 ≤120 字符（≈30 token）：头部13 + id尾8 + 摘要≤60 + 尾部提示。
    """
    if folded:
        _stats["folds"] += 1
        return f"[elided earlier {tool_name}]"
    uid8 = (use_id or "")[-8:]
    s = sanitize_summary(summary)
    return f"[elided {tool_name} {uid8}: {s}] (archived; answer from remaining context)"
```

- `folded=True`（远档）→ `[elided earlier <tool>]`，并 `_stats["folds"] += 1`；
- `folded=False`（近档）→ `[elided <tool> <id尾8位>: <净化摘要≤60>] (archived; answer from remaining context)`。

注释还给了字节预算拆解：「总长约 ≤120 字符（≈30 token）：头部13 + id尾8 + 摘要≤60 + 尾部提示」。

**深化讲解**（面试官参考，不要求候选人全说）
两档的区别是**信息量分级**：近档保留「工具名 + id 尾 8 位 + 摘要」，足以让模型知道「这里曾有一次 Grep，关于 XXX」；远档只保留「这里曾有 <tool> 的调用」。id 取**尾 8 位**（`use_id[-8:]`）而不是全长，因为 id 通常是 uuid——尾 8 位已足够在局部区分，且固定 8 字符便于长度可预测。

「**两档均确定性、单行**」是硬约束：docstring 的「确定性，增量投影一致」与 `sanitize_summary` 的「对任意输入确定性输出（R26）」都指向同一个要求——**投影必须可重复计算**，否则增量投影会因为两次计算结果不同而产生抖动。



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

### XEYO-QA-0105 老化的豁免规则

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | aging | 错误保真与结构化豁免 | 简单 | 概念确认 | `python/engine/aging.py:26-27,75-77` |

**面试官提问**
`should_exempt(is_error, tool_name)` 在什么情况下返回 `True`（即**不老化**）？请完整列举。

**参考答案要点**
**A、B、C**。

`aging.py:26-27,75-77`：

```python
#: 结构化结果豁免集（UI dock / 挂起语义依赖其原文）
EXEMPT_TOOLS = frozenset({"TodoWrite", "AskUserQuestion"})

def should_exempt(is_error: bool, tool_name: str) -> bool:
    """错误结果保真、结构化结果豁免（设计规则表）。"""
    return bool(is_error) or tool_name in EXEMPT_TOOLS
```

即两类豁免：

1. **错误结果保真**：`is_error=True` 一律豁免。错误信息是排查的唯一线索，被折叠/缩短会直接损害后续决策；
2. **结构化结果豁免**：`TodoWrite` 与 `AskUserQuestion` 在 `EXEMPT_TOOLS` 里。注释给了理由——「**UI dock / 挂起语义依赖其原文**」：
   - `TodoWrite` 的清单是 UI 侧边栏的数据源，也是 `wrap_gap` 计算缺口的输入（见 B02 的 0076），原文被改写会破坏这两个消费方；
   - `AskUserQuestion` 的问题/选项文本是挂起语义的载体（用户看到的就是原文，不能变成存根）。

`Bash` / `Read` **不在**豁免集——它们正是老化要处理的主要对象（工具输出的大头）。

**深化讲解**（面试官参考，不要求候选人全说）
这题的关键是理解**豁免的判据不是「重要性」而是「有没有别的消费方依赖原文」**。`Read` 的结果当然也重要，但它只有「模型」一个消费者，所以可以被安全地折叠（且折叠后模型还能通过重跑拿回）。而 `TodoWrite`/`AskUserQuestion` 有**模型之外的第二消费者**（UI dock、挂起面板），改原文会同时破坏两侧。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「工具是 `Bash`」——说明没抓住本题的分界（D）。
- 答成「工具是 `Read`」——说明没抓住本题的分界（E）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0106 收尾窗状态的传播载体

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | wrap_window | ContextVar 广播 | 简单 | 概念确认 | `python/engine/wrap_window.py:20,42` |

**面试官提问**
`wrap_window.py` 用什么机制把「是否在收尾窗、剩余墙钟秒数」传给工具层？

**参考答案要点**
**正解：C（**通过 `contextvars.ContextVar` 广播**（`_SLOT`，默认值 `_INACTIVE`））**
`wrap_window.py:20,41-42`：

```python
from contextvars import ContextVar
...
_INACTIVE = WrapWindow()
_SLOT: ContextVar[WrapWindow] = ContextVar("xeyo_wrap_window", default=_INACTIVE)
```

`ContextVar` 的意义在于**隔离**：每个任务/协程有自己的上下文视图，`set_wrap_window` 只影响当前上下文分支。对并发工具任务来说，这保证了「收尾窗状态」不会像全局变量那样跨任务串台。

docstring 还明确了「**不设置在权限或策略层**——它不改变『能不能做』，只改变『怎么做』」。

**深化讲解**（面试官参考，不要求候选人全说）
为什么不用 A（消息）？因为这是**引擎内部信号**，不该出现在模型可见的对话历史里——docstring 里「不产生给模型的劝告文本」就说明了这一点。注意区分：`wrap_gap` 的缺口清单**会**进 T_now（模型可见，见 B02 的 0076），而 `wrap_window` 是**工具层内部**信号（模型不可见）——两者是同一次收尾的两个不同信道。

为什么不用 B（环境变量）？环境变量是进程级的，无法在并发任务间区分；且修改 `os.environ` 影响全局，与「每个回合自己的收尾状态」不匹配。

为什么不用 D？权限/策略层管「能不能做」，而收尾窗只改「怎么做」（例如长命令是否后台化）——**混进策略层会把一个执行优化错误地升格成权限约束**。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「通过 `MessageStore` 追加一条系统消息」——说明没抓住本题的分界（A）。
- 答成「通过 `os.environ` 设置进程级环境变量」——说明没抓住本题的分界（B）。
- 答成「通过 `permissions/policy.py` 的策略对象」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0107 WrapWindow 的字段与未知值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | wrap_window | 数据类定义与访问器 | 简单 | 机制解释 | `python/engine/wrap_window.py:33-63` |

**面试官提问**
`WrapWindow` 是什么类型的对象、有哪些字段？`remaining_s` 用什么表示「未知」？五个访问函数（`set_wrap_window` / `clear_wrap_window` / `wrap_state` / `in_wrap_window` / `wrap_remaining_s`）各自做什么？未武装时 `in_wrap_window()` 返回什么？

**参考答案要点**
`wrap_window.py:23-63`：

```python
__all__ = ["WrapWindow", "clear_wrap_window", "in_wrap_window",
           "set_wrap_window", "wrap_remaining_s", "wrap_state"]

@dataclass(frozen=True)
class WrapWindow:
    """收尾窗口状态：是否在窗口内 + 距墙钟死线的剩余秒数（未知为 None）。"""
    active: bool = False
    remaining_s: float | None = None

_INACTIVE = WrapWindow()
_SLOT: ContextVar[WrapWindow] = ContextVar("xeyo_wrap_window", default=_INACTIVE)

def set_wrap_window(active: bool, remaining_s: float | None = None) -> None:
    _SLOT.set(WrapWindow(active=bool(active), remaining_s=remaining_s))

def clear_wrap_window() -> None:
    _SLOT.set(_INACTIVE)

def wrap_state() -> WrapWindow:
    return _SLOT.get()

def in_wrap_window() -> bool:
    return _SLOT.get().active

def wrap_remaining_s() -> float | None:
    state = _SLOT.get()
    return state.remaining_s if state.active else None
```

- **类型**：`@dataclass(frozen=True)` ——**不可变**（赋值会抛 `FrozenInstanceError`）。不可变很重要：ContextVar 里的值被多个读取方共享，若可变则一处修改会影响所有读取方的视图。
- **字段**：`active: bool = False`、`remaining_s: float | None = None`。「未知」用 **`None`** 表示（不是 `-1`、不是 `inf`）。
- **五个访问器**：
  - `set_wrap_window(active, remaining_s=None)`：写入新状态（`bool(active)` 强制布尔化）；
  - `clear_wrap_window()`：复位为 `_INACTIVE`（模块级单例）；
  - `wrap_state()`：取整个 `WrapWindow` 对象；
  - `in_wrap_window()`：只取 `active`；
  - `wrap_remaining_s()`：**仅当 `active` 为真**才返回 `remaining_s`，否则返回 `None`（见下）。
- **未武装/未进窗时**：`in_wrap_window()` 恒 `False`（docstring `:15` 明确：「未武装墙钟 / 未进入收尾窗时 `in_wrap_window()` 恒 False」）。

**深化讲解**（面试官参考，不要求候选人全说）
`wrap_remaining_s()` 的实现细节值得注意：

```python
state = _SLOT.get()
return state.remaining_s if state.active else None
```

它**不看 `remaining_s` 是否为空，只看 `active`**。含义是：**不在窗口内就不该关心剩余秒数**——即使某个残留对象里 `remaining_s` 有值，不在窗口时也一律返回 `None`。这是一个「**用状态门控数据**」的写法，避免调用方误用「不在收尾窗但有个剩余秒数」这种矛盾组合。

对照 `_INACTIVE = WrapWindow()` 复用同一个实例：因为 dataclass 不可变，共享单例是安全的，且省掉了每次 clear 的对象分配。



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

### XEYO-QA-0108 StageClock 的用法与 sink

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | stage_clock | 阶段计时纯件 | 简单 | 机制解释 | `python/engine/stage_clock.py:1-91` |

**面试官提问**
`StageClock` 的三种计时入口分别是什么？`result()` 与 `finish()` 有什么区别？`finish()` 的幂等性体现在哪里、为什么要保证幂等？这个模块「不负责落审计」意味着什么？

**参考答案要点**
`stage_clock.py:14-81`：

```python
class StageClock:
    """命名阶段计时(ms)。支持嵌套 contextmanager 与显式 add/lap。

    - ``with clock.stage("assemble"): ...`` — 常规用法,段耗时自动累计;
    - ``clock.lap("first_byte")`` — 打点:距 __init__/reset 的累计耗时;
    - ``clock.sink`` — finish() 时收到完整 {name: ms} 报告(接审计)。
    """
```

**三种入口**：

| 入口 | 形态 | 语义 |
|---|---|---|
| `stage(name)` | `@contextmanager` | 命名阶段计时，**同名多次进入则累计**；**异常也记录耗时**（`finally` 里 `_add`） |
| `lap(name)` | 普通方法 | 打点：记录**自 `_t0`（`__init__`/`reset`）到此刻**的累计 ms，返回该值 |
| `add(name, ms)` | 普通方法 | 外部提供耗时（如子进程返回的墙钟）直接累计，`max(0.0, ...)` 防负 |

**`result()` vs `finish()`**：

```python
def result(self) -> dict[str, float]:
    """按首次进入顺序返回 {name: 累计 ms}。"""
    return {n: round(self._stages.get(n, 0.0), 3) for n in self._order}

def finish(self) -> dict[str, float]:
    """取结果;若配了 sink 则回调一次(幂等)。"""
    out = self.result()
    if self.sink is not None and not self._finished:
        self._finished = True
        try:
            self.sink(dict(out))
        except Exception:  # noqa: BLE001 — 审计侧失败不阻塞主路径
            pass
    return out
```

- `result()` **纯读取**：按**首次进入顺序**（`_order`）返回 `{name: 毫秒}`，值保留 3 位小数；
- `finish()` = `result()` + **触发 sink 一次**。

**幂等的实现**：`self._finished` 标志位。第一次 `finish()` 时置位并回调；后续调用直接跳过回调（但仍返回结果）。幂等的必要性：`finish()` 可能被多条路径调用（例如正常收口、异常收口、诊断钩子），若不幂等会导致**同一次回合上报多条审计记录**（重复计数）。

另外 sink 回调包在 `try/except: pass` 里，注释给出理由：「审计侧失败不阻塞主路径」——与 B03 里反复出现的「附加能力故障隔离」同一取向。

**「不负责落审计」的含义**（模块 docstring `stage_clock.py:1-5`）：

> stage_clock — 旁路(P0):回合内阶段计时纯件(**无引擎依赖**)。
> query_loop 逐段计时钩子(收口后接入)与本地诊断共用。只做时间采集,
> **不负责落审计**(调用方在 `finish()` 时拿到 dict 自行 emit/写日志)。

即这是个**纯函数式组件**：它不认识 audit 模块，只把数据交出去。好处是**零耦合**——`to_summary_report(report)`（`:84-91`，输出 `name→ms` 对齐文本 + `TOTAL` 行）同样是「不依赖 prof_stats，保持零耦合」的独立实现。

**深化讲解**（面试官参考，不要求候选人全说）
这题的两个考点：① **幂等**（`_finished` 标志 + sink 一次）；② **职责边界**（采集 vs 落盘分离）。`reset()` 会重置 `_finished`，说明「一轮结束 → reset → 下一轮复用」是预期用法；而 `_t0` 也在 `reset()` 中更新，保证 `lap()` 的基准正确。



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

### XEYO-QA-0109 上下文压缩的四个常量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | compact | 截断与尾部保护参数 | 简单 | 概念确认 | `python/engine/compact.py:24-27` |

**面试官提问**
请说出 `compact.py` 的模块级常量及其取值。

**参考答案要点**
**A、B、C、D**。

`compact.py:24-27`：

```python
MAX_TOOL_RESULT_CHARS = 8_192
KEEP_TAIL_MESSAGES = 6              # 兼容旧名：等价于保留约 N 条消息的尾部保护区
KEEP_TAIL_TOOL_ROUNDS = 3           # 按「assistant(tool_calls)+连续 tool」成对区间保留的轮数
TRUNCATE_SUFFIX = "\n…[truncated]"  # 截断时追加的后缀
```

**E 不存在**：`compact.py` 中没有 `MAX_CONTEXT_TOKENS` 这样的常量（上下文窗口相关的默认值在 `query_engine.py:1164` 的 `_default_context_limit(provider, model)` 里按 provider/model 推导，不在本模块）。

三个值得记的细节：
1. `KEEP_TAIL_MESSAGES = 6` 的注释写着「**兼容旧名**」——说明尾部保护的口径已经从「按消息条数」迁移到「按工具轮数」（即 `KEEP_TAIL_TOOL_ROUNDS = 3`），旧常量保留是为了兼容；
2. `TRUNCATE_SUFFIX` 的内容是 `"\n…[truncated]"`：**换行开头 + 一个 U+2026 省略号**（不是三个 ASCII 点）；
3. 数字下划线 `8_192` 是 Python 字面量写法，值即 8192。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在「`KEEP_TAIL_MESSAGES` 与 `KEEP_TAIL_TOOL_ROUNDS` 的**口径差异**，以及注释里那个「兼容旧名」的提示。按消息条数保护尾部是**脆弱的**——一条消息可能是一条文本，也可能包含 20 个 tool_result；而按「assistant(tool_calls) + 连续 tool」的**成对区间**保护（`tool_pair_ranges`，`compact.py:69`）才能保证「工具调用与其结果不被切开」。

E 选项是典型的「听起来合理但不存在」——识别方法是确认常量的**归属模块**（上下文窗口推导在 `query_engine`，不在 `compact`）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`MAX_CONTEXT_TOKENS = 128_000`」——说明没抓住本题的分界（E）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0110 截断后缀的精确字面量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | compact | 截断标记 | 简单 | 概念确认 | `python/engine/compact.py:27` |

**面试官提问**
`compact.py` 中被截断的工具结果会追加什么后缀？

**参考答案要点**
**正解：C（`"
…[truncated]"`（**换行 + 单个 U+2026 省略号**））**
`compact.py:27`：

```python
TRUNCATE_SUFFIX = "\n…[truncated]"  # 截断时追加的后缀
```

构成是：`\n`（换行，让标记单独成行）+ `…`（**U+2026 HORIZONTAL ELLIPSIS**，单字符）+ `[truncated]`（ASCII 方括号包围的英文单词）。

**深化讲解**（面试官参考，不要求候选人全说）
这类「字面量精确性」题看似琐碎，但在两种场景下是硬要求：

1. **测试可精确匹配**：XEYO 的测试大量使用「精确文案匹配」作为契约执法（对照 `repeat_fold.py:21` 的注释：「折叠行含 `[fold]` 前缀……**测试可精确匹配**」）。如果实现与测试不一致，测试会红；
2. **增量投影的一致性**：截断结果会被反复重算（见 0138），后缀必须**逐字节稳定**，否则同一条内容在两次投影里字节不同，会被判为「变化」。

同理，B03 里其他后缀也值得对照记忆：`aging.py` 的 `…`（`t[:limit].rstrip() + "…"`）、`query_loop.py:109` 的 `raw[:200] + "…"`——**都是单个 U+2026 而不是三个点**，这是 XEYO 代码的一致约定。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`"...[truncated]"`」——说明没抓住本题的分界（A）。
- 答成「`"
...[truncated]"`（换行 + 三个 ASCII 点）」——说明没抓住本题的分界（B）。
- 答成「`" [TRUNCATED]"`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0111 行为账本的默认阈值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | loop_ledger | 三信号默认阈值 | 简单 | 概念确认 | `python/engine/loop_ledger.py:52` |

**面试官提问**
`loop_ledger.py` 中 `DEFAULT_LEDGER_AT = (3, 4, 3)` 对应哪三个信号？它们的含义是什么？

**参考答案要点**
**正解：B（**s1 结果等价 / s2 内容已见 / s3 首句重复 三个信号的触发次数**）**
`loop_ledger.py:52`：`DEFAULT_LEDGER_AT = (3, 4, 3)`

对应的三个信号（属性见 `loop_ledger.py:142-156`）：

| 属性 | 信号 | 默认阈值 |
|---|---|---|
| `s1` | 结果等价 | 3 |
| `s2` | 内容已见 | 4 |
| `s3` | 首句重复 | 3 |

这三个计数器由 `observe_tool(...)`（`:157`）与 `observe_assistant(text)`（`:193`）更新，由 `render()`（`:207`）渲染成文本，`reset()`（`:239`）清零。

**深化讲解**（面试官参考，不要求候选人全说）
本批 B02-0100 的上下文里已出现过这个模块的定位（`query_loop.py:779-781` 的注释）：

```python
# 行为账本（循环信号计数器：s1 结果等价 / s2 内容已见 / s3 首句重复）；
# 豁免集与 RepeatCallGuard 同源；经 InjectContext 供 pre_llm_inject 直读。
loop_ledger = LoopLedger(exempt_tools=frozenset(EXEMPT_TOOLS))
```

三个信号的设计意图是**从不同粒度检测「空转」**：

- **s1 结果等价**：这次的输出与之前某次相同（**结果维度**）；
- **s2 内容已见**：这次要看的**内容**在历史里已经出现过（输入维度 / 信息增量维度）；
- **s3 首句重复**：assistant 回复的**开头 30 字符**（`_HEAD_LEN = 30`，`:55`）重复（**表述维度**）。

注意 s2 的阈值（4）比 s1/s3（3）高：因为「内容已见」的误报代价更大（模型可能确实需要再看一次同一片内容来确认），所以容忍度更高。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「三个工具的超时秒数」——说明没抓住本题的分界（A）。
- 答成「三轮重试次数」——说明没抓住本题的分界（C）。
- 答成「(最小、默认、最大) token 阈值」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0112 折叠的默认触发次数

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_fold | 逐字节档与等价档的触发点 | 简单 | 概念确认 | `python/engine/repeat_fold.py:32-39,88-89` |

**面试官提问**
`DEFAULT_FOLD_AFTER` 与 `DEFAULT_FOLD_EQUIV_AT` 都是 3。它们控制的分别是什么？`IdenticalResultFold.__init__` 对 `fold_after` 做了什么钳制？

**参考答案要点**
**正解：B（**`DEFAULT_FOLD_AFTER` 控「同签名相邻输出逐字节相同」；`DEFAULT_FOLD_EQUIV_AT` 控「同工具跨签名但输出内容相同」；`fold_after` 被钳制为 `max(2, int(...))`**）**
`repeat_fold.py:32-39`：

```python
DEFAULT_FOLD_AFTER = 3

#: 结果等价档默认触发次数：同工具第 N 次出现相同内容（N=1 首次完整，
#: N≥2 为等价重复）。默认 3——与逐字节档同底线（R2' 契约：前两次原文
#: 保留，给足模型看清的机会）；``XEYO_FOLD_EQUIV_AT`` 可调激进档。
#: 属行为账本方案（engine/loop_ledger.py）的消费端之一，受总开关
#: XEYO_LOOP_LEDGER 管控。
DEFAULT_FOLD_EQUIV_AT = 3
```

以及 `repeat_fold.py:88-89`：

```python
def __init__(self, *, fold_after: int = DEFAULT_FOLD_AFTER) -> None:
    self.fold_after = max(2, int(fold_after))
```

**两个阈值分属两档**：

| 常量 | 档位 | 判据 |
|---|---|---|
| `DEFAULT_FOLD_AFTER` | 逐字节档 | **同签名**（`semantic_key` 归一后相同）**且**与上一次输出**逐字节相同** |
| `DEFAULT_FOLD_EQUIV_AT` | 等价档 | **同工具、不同参数**（跨签名）但输出内容**相同**（靠 sha256 摘要判定） |

**钳制**：`max(2, int(fold_after))` —— 下限是 2。为什么不是 1？因为「首次输出必须完整保留」：`N=1` 是第一次出现（原文必须给出），折叠从第 2 次起才有意义。注释里也写了「**前两次原文保留，给足模型看清的机会**」——这里说的「前两次」对应 `seq=1`（首次）与 `seq=2`（第一次重复仍给原文），第 3 次才折叠。

**深化讲解**（面试官参考，不要求候选人全说）
两档共存的意义：逐字节档抓的是「**完全没变**」（典型死循环）；等价档抓的是「**换了参数但结果一样**」（例如反复用不同的 grep 模式搜同一个不存在的字符串，每次结果都是空）。后者更隐蔽——签名不同，朴素实现抓不到。

「属行为账本方案的消费端之一」这句说明**等价档的生命周期受 `XEYO_LOOP_LEDGER` 总开关约束**（见 0126）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「两者都是「连续 3 次后折叠」；`fold_after` 无钳制」——说明没抓住本题的分界（A）。
- 答成「前者控字符数、后者控 token 数」——说明没抓住本题的分界（C）。
- 答成「两者合并为一个阈值，3 是缓存大小」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0113 折叠行的三种文案

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_fold | `[fold]` 前缀与三种措辞 | 简单 | 机制解释 | `python/engine/repeat_fold.py:41-54` |

**面试官提问**
`repeat_fold.py` 里定义了三条文案常量。请说出各自的变量名、触发场景，以及它们**共同的前缀**是什么、为什么这个前缀重要。

**参考答案要点**
`repeat_fold.py:41-54`（原文）：

```python
#: 超短占位（seq > fold_after 时使用）：既保持配对又几乎零 token。
_REPEAT_SHORT = "[fold] 与上一条输出相同（第 {n} 次连续）——详情见首次输出。"
#: 触发档的解释行：出现一次，点明引擎在做什么（C1 同精神：纯事实，
#: 不带"请继续/请换参数"类劝导）。
_FOLD_EXPLAIN = (
    "[fold] 这是同一签名的第 {n} 次调用，输出与首次逐字节相同——"
    "引擎已折叠后续重复内容以节省上下文。"
)
#: 结果等价档（loop_ledger 方案）：同工具、**不同参数**但输出内容完全相同
#: ——"换着花样调但结果全是旧的"的瘦身档；纯事实措辞，同受措辞测试执法。
_FOLD_EQUIV = (
    "[fold] 本次输出与该工具既往某次输出完全相同（第 {n} 次等价结果）——"
    "引擎已折叠重复内容以节省上下文。"
)
```

| 常量 | 触发场景 |
|---|---|
| `_FOLD_EXPLAIN` | 逐字节档**恰好达到** `fold_after`（`seq == self.fold_after`）——**只出现一次** |
| `_REPEAT_SHORT` | 逐字节档**超过** `fold_after`（`seq > fold_after`）——超短占位，几乎零 token |
| `_FOLD_EQUIV` | 等价档命中（`equi_n >= _fold_equiv_at()`） |

**共同前缀**：`[fold]`。

**为什么前缀重要**（`repeat_fold.py:21` 的 docstring）：

> 折叠行含 ``[fold]`` 前缀，与既有 **[repeat]** 提醒文案互不冲突（**测试可精确匹配**）。

三重意义：① 与 `RepeatCallGuard` 的 `[repeat]` 提醒**区分开**（两条通道语义不同：`[repeat]` 是"你在重复"的提示，`[fold]` 是"输出被折叠"的事实）；② 让模型能识别这是引擎的折叠动作而不是工具的原输出；③ 让测试可以**精确匹配**前缀做契约执法。

**深化讲解**（面试官参考，不要求候选人全说）
三条文案的分工体现了一个细节设计：**逐字节档只在首次触发时给解释行**（`_FOLD_EXPLAIN`），之后转为极短占位（`_REPEAT_SHORT`）。理由是「解释只需说一次」——第 4 次、第 5 次重复时继续给完整解释只是浪费 token。

措辞纪律也值得注意：两条解释行都以「**引擎已折叠重复内容以节省上下文**」结尾——陈述**引擎做了什么**（事实），而不是「**请停止重复**」（劝导）。注释明确写成「C1 同精神：纯事实，不带『请继续/请换参数』类劝导」。



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

### XEYO-QA-0114 WriteStore 的分片锁

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | write_store | 分片并发控制 | 简单 | 概念确认 | `python/engine/write_store.py:170-182` |

**面试官提问**
`WriteStore.__init__(root, *, shards=64)` 中的 `shards` 用来做什么？`_lock_for(path)` 与 `submit(intent)` 的关系是：

**参考答案要点**
**正解：B（**`shards` 是内部锁的分片数；`_lock_for(path)` 按路径取分片锁，`submit(intent)` 返回 Awaitable（异步提交）**）**
`write_store.py:167-194`：

```python
class WriteStore:
    def __init__(self, root: str | Path, *, shards: int = 64) -> None:
        ...
    def _lock_for(self, path: str) -> threading.Lock:
        ...
    def submit(self, intent: ChangeIntent) -> Awaitable[ApplyResult]:
        ...
    async def close(self) -> None:
        ...
    def submit_sync(self, intent: ChangeIntent) -> ApplyResult:
        ...
```

- `shards = 64`：**内部锁的分片数**。用固定数量的锁对象按路径哈希分片，使「不同文件的写」可以并行、而「同一文件的写」串行——避免一把全局锁把全部写操作串行化；
- `_lock_for(path)`：按路径返回对应的分片锁（`threading.Lock`，**线程锁**，说明写路径可能从 threadpool 进入）；
- `submit(intent) -> Awaitable[ApplyResult]`：**异步**提交（可 await），返回应用结果；
- `submit_sync(intent) -> ApplyResult`：**同步**版本，供非异步调用方使用；
- `async def close()`：关闭（清理资源）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的要点是「**64 是一个工程折中**」：
- 分片太少（例如 1）→ 退化为全局锁，所有写串行；
- 分片太多（例如按路径数动态）→ 锁对象本身占内存，且并发度提升的边际收益递减（磁盘 IO 是真正的瓶颈）；
- 64 是一个固定的、内存开销可控（几十个 `Lock` 对象）且并发度足够的取值。

**注意**：分片锁**只解决进程内并发**。跨进程/跨会话的一致性靠另外两层：`workspace_lock.py` 的租约（见 0139/0140）与 `write_store.py:389` 的 `_lookup_base_hash`（见 0131）。这三者构成 B03 超压题 0149 的分析对象。

`submit` 返回 `Awaitable` 而非协程本身的写法也值得注意：调用方可以 `await store.submit(intent)`，也便于在非 await 场景下把返回对象交给事件循环——这是「提交即可异步等待」的常见形态。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`shards` 是分片上传的块数；`submit` 同步执行」——说明没抓住本题的分界（A）。
- 答成「`shards` 是文件备份份数；`submit` 返回 `None`」——说明没抓住本题的分界（C）。
- 答成「`shards` 是无意义的兼容参数」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0115 工作区修订号的格式与算法

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_revision | 保守指纹 | 简单 | 概念确认 | `python/engine/workspace_revision.py:76-109` |

**面试官提问**
`WorkspaceRevision.calculate(paths)` 返回的修订号形如：

**参考答案要点**
**正解：C（**`rev_<sha256 前 16 位十六进制>`**）**
`workspace_revision.py:103-109`：

```python
hasher = hashlib.sha256()
hasher.update(head.encode("utf-8"))
hasher.update(b"\0")
for token in metadata:
    hasher.update(token.encode("utf-8", errors="surrogateescape"))
    hasher.update(b"\0")
return f"rev_{hasher.hexdigest()[:16]}"
```

构成：**前缀 `rev_` + sha256 的十六进制前 16 字符**。

哈希的输入按顺序是：① shadow git 的 HEAD 提交号（或字面量 `"empty"`）；② `b"\0"` 分隔符；③ 逐个 `metadata` token（每个后跟 `b"\0"`）。`metadata` 在哈希前 `metadata.sort()`（`:101`）——**排序保证顺序无关**（同样的路径集合，无论从 git status 里以什么顺序枚举，都得到同一个修订号）。

**深化讲解**（面试官参考，不要求候选人全说）
几个容易漏的细节：

1. **`errors="surrogateescape"`**：编码 token 时用这个错误处理器。它是处理「**文件名含非法 UTF-8 字节**」的关键——Windows 上文件名可能是非 Unicode 的有效字节序列，用默认 `strict` 会抛 `UnicodeEncodeError`；`surrogateescape` 保证任意字节都能被编码且可逆解码，使指纹**永不因文件名异常而失败**；
2. **`head or "empty"`**：仓库还没有任何提交时用字面量 `"empty"` 参与哈希（避免 `None` 无法编码）；
3. **前缀 `rev_`**：让修订号自解释（与 git commit 哈希区分开）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「单调递增整数（如 `42`）」——说明没抓住本题的分界（A）。
- 答成「UUID（如 `3f2b...`）」——说明没抓住本题的分界（B）。
- 答成「git commit 的完整 40 位哈希」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0116 进程账本的类型与条目

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | process_ledger | 后台进程登记 | 简单 | 机制解释 | `python/engine/process_ledger.py:28-70,301-357` |

**面试官提问**
`process_ledger.py` 用哪些类型描述登记的进程？模块级便利函数（`register_process` / `unregister_process` / `leftovers` / `get_ledger` / `ledger_enabled`）分别做什么？`Kind` 是枚举还是自由字符串？

**参考答案要点**
`process_ledger.py` 的类型与接口：

```python
class Kind(str, Enum):        # :28  —— 字符串枚举（进程类别）
class Entry:                  # :35  —— 单条登记
    def age(self, now: float | None = None) -> float:      # :45
class ReapReport:             # :50
    def __str__(self) -> str:                              # :57
def _pid_alive(pid: int) -> bool:                          # :70
def default_probe(entry: Entry) -> bool:                   # :82
def _terminate_pid(pid: int) -> bool:                      # :94
def default_cleanup(entry: Entry) -> bool:                 # :116
class ProcessLedger:                                       # :134
    def register(...) -> ...                               # :148
    def unregister(self, kind: Kind, key: str) -> bool:    # :175
    def list(self, *, owner=None, kind=None) -> list[Entry] # :179
    def reap(...)                                          # :200
    def sweep(...)                                         # :237
    def count(self) -> int                                 # :276
    def snapshot(self) -> list[dict]                       # :280
_DEFAULT: "ProcessLedger | None" = None                    # :301
def get_ledger() -> "ProcessLedger":                       # :304
def ledger_enabled() -> bool:                              # :312
def _auto_owner() -> str                                   # :318
def register_process(...)                                  # :330
def unregister_process(pid: int) -> bool                   # :350
def leftovers(*, owner=None) -> list[Entry]                # :357
```

- **`Kind(str, Enum)`**：是**枚举**，且继承 `str` —— 所以它既是枚举成员也可当字符串用（便于写 JSON/日志）。**不是自由字符串**。
- **`Entry`**：单条登记；`age(now=None)` 返回该条目的年龄（距登记/更新过了多久）。
- **`ReapReport`**：回收报告；`__str__` 提供可读输出。
- **进程存活判定**：`_pid_alive(pid)`（探测）、`default_probe(entry)`（默认存活探针）、`_terminate_pid(pid)`（终止）、`default_cleanup(entry)`（默认清理动作）。
- **`ProcessLedger`**：注册 `register` / 注销 `unregister(kind, key)` / 列举 `list(owner=, kind=)` / 回收 `reap` / 清扫 `sweep` / 计数 `count` / 快照 `snapshot`。
- **模块级便利函数**：`get_ledger()`（取默认单例，`_DEFAULT`）、`ledger_enabled()`（总开关）、`_auto_owner()`（自动推断 owner）、`register_process(...)` / `unregister_process(pid)` / `leftovers(owner=)`（**残留进程**查询——与「崩溃恢复」直接相关，见 0150）。

**深化讲解**（面试官参考，不要求候选人全说）
这题的关键是「**枚举 + 继承 str**」这个细节。它带来两个好处：类型安全（IDE/静态检查能查成员）与序列化便利（`str(枚举成员)` 就是它继承来的字符串值）。同时 `unregister(kind, key)` 用**二元组**作键，说明同一 `kind` 下可以有多个实例（例如多个后台 bash job）。

`snapshot() -> list[dict]` 说明账本可以被外部读取成可序列化形态（用于诊断/上报），而 `leftovers()` 这个**语义化查询**的存在，正说明「**残留进程**」是这套机制最关心的输出——进程账本的核心价值就是**让残留可见并可清理**。



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

### XEYO-QA-0117 prepare_next_turn 为什么不增加 Turn

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | 判定与计数分离 | 中等 | 机制解释 | `python/engine/budget.py:251-256` |

**面试官提问**
`prepare_next_turn()` 的 docstring 里有一句关键约束：「**该方法不增加 Turn**」。请解释这句话解决了什么具体问题——为什么「Tool Call 达到上限」不应该消耗或制造一个 Turn？

**参考答案要点**
`budget.py:251-256`（原文）：

```python
def prepare_next_turn(self) -> bool:
    """判断下一次模型 API 请求是否允许，并在边界排队软提醒。

    该方法不增加 Turn。只有真正调用 ``begin_turn`` 时才会计入下一次
    模型响应，因此 Tool Call 达到上限不会凭空制造或消耗一个 Turn。
    """
```

**解决的问题**：**判定（问）与计数（做）必须分开**。

调用方在主循环里是这么用的（B02 的 `query_loop.py:800`）：

```python
if not budget.prepare_next_turn():
    ...
```

注意它是在**每轮循环开头**调用，而且**返回值有可能是 False**（不允许）——此时这一轮**不会发生**。假如 `prepare_next_turn` 内部就把 `turn_count += 1`：

- **情况 A：不允许但已计数** → 「被拒绝的那一轮」也消耗了预算。结果是：达到上限时，一次被拒的判定会额外吃掉 1 个额度，实际可用轮次比配置少（**凭空消耗**）；
- **情况 B：Tool Call 触顶时也要判定** → 工具配额是**每轮内**的计数（`current_turn_tool_calls`），而 `prepare_next_turn` 还会检查 `turn_count`。如果判定动作会改轮次计数，那么「工具打满」这个**轮内事件**就凭空改变了**轮级计数**（**凭空制造**）。

把计数移动到 `begin_turn()`（`budget.py:285-300`，其中 `self.turn_count += 1`）之后，「**问**」变成了纯查询，「**做**」才计数。这样 `turn_count` 的语义严格是「**真实发生过的模型请求数**」。

**深化讲解**（面试官参考，不要求候选人全说）
这是一道「**幂等查询 vs 有副作用动作**」的经典设计题。同类对照：

- `allow_next_turn()`（`:281-283`）直接 `return self.prepare_next_turn()` —— 说明 `prepare_next_turn` 已经被设计成可以安全重复调用（无副作用），旧名字只是兼容；
- `over_budget()`（`:446`）/ `over_token_budget()`（`:450`）也是纯判定属性；
- 反面对照：`begin_turn()`（计数）、`begin_tool_call()`（占配额）、`consume_runtime_notice()`（消费即清）——这三个是**动作**。

还有一个细节：`prepare_next_turn` 会在**边界**排队软提醒（`_queue_notice("max_turns")`，`:269`）。这个副作用是**提醒**而非**计数**——重复排队会被 `queue_runtime_notice` 的去重挡掉（见 0120），所以不破坏「可重复调用」的性质。



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

### XEYO-QA-0118 grace 阶梯的四条返回路径

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | 宽限期状态机 | 中等 | 代码阅读 | `python/engine/budget.py:267-279` |

**面试官提问**
阅读下面代码，指出四条可能的返回路径（含触发条件与返回值），并说明「一旦进入 grace 就再也回不到 `turn_count < max_turns` 的普通路径」这一性质会带来什么行为。

```python
if self.grace_started:
    if self.turn_count >= self.max_turns:
        self._queue_notice("max_turns")
    if self.grace_turns_used < MAX_GRACE_TURNS:
        return True
    self._hard_stop_reason = self.grace_reason or "max_turns"
    return False

if self.turn_count < self.max_turns:
    return True

self._start_grace("max_turns")
return True
```

**参考答案要点**
**四条路径**：

| # | 条件 | 动作 | 返回 |
|---|---|---|---|
| 1 | 已进 grace 且 `grace_turns_used < 3` | 若 `turn_count >= max_turns` 则排队 `max_turns` 提醒 | **True**（宽限内放行） |
| 2 | 已进 grace 且 `grace_turns_used >= 3` | 设置 `_hard_stop_reason = grace_reason or "max_turns"` | **False**（硬停） |
| 3 | 未进 grace 且 `turn_count < max_turns` | — | **True**（正常放行） |
| 4 | 未进 grace 且 `turn_count >= max_turns` | `self._start_grace("max_turns")` | **True**（本次放行，同时开启宽限） |

`MAX_GRACE_TURNS = 3`（`budget.py:25`，见 B02-0060）。

**「回不去」的性质与影响**：

`grace_started` 一旦为真就**永远不会被重置为 False**（`_start_grace` 只置位；`reset_for_new_submit` 才会重置整个 tracker）。所以路径 3 只在**第一次**触顶之前可能走到；触顶之后，判定永远在路径 1/2 之间摇摆：

- 路径 1 的条件下 `turn_count >= max_turns` 恒为真 → **每一轮都排队一次 `max_turns` 提醒**。由于 `queue_runtime_notice` 按文本去重（见 0120），实际只会注入一次——**去重机制在这里承担了「只提醒一次」的职责**；
- `grace_turns_used` 只在 `begin_turn()` 里递增（`:287-288`），所以「宽限 3 轮」计的是**真实发生的模型请求数**，与 0117 的「判定不计数」保持一致。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的关键是**看清 grace 是一个「单向闩锁」**。这带来两个可验证推论：

1. **提醒的去重是必需的**（否则会每轮重复排队）——两处机制耦合，缺一不可；
2. **`_start_grace` 只在路径 4 调用一次**——所以「进入 grace 的原因」（`grace_reason`）在整段时间里固定。这也是 `_hard_stop_reason = self.grace_reason or "max_turns"` 里能直接用 `grace_reason` 的前提。

`or "max_turns"` 的兜底含义：如果 `grace_reason` 为空（理论上不该发生），仍给出一个确定的原因字符串，保证 `StoppedEvent(reason=...)` 不为空（对照 B02-0075 的 `budget.hard_stop_reason or "max_turns"`，那是第二层兜底）。



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

### XEYO-QA-0119 grace-cliff：单轮爆发不能烧掉整段预算

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | 工具配额触顶的分级处理 | 中等 | 场景设计 | `python/engine/budget.py:285-320` |

**面试官提问**
场景：模型在**一轮**里并发发起了 200 个工具调用，而 `max_tool_calling = 64`。

（1）`begin_tool_call()` 对这 200 次调用分别返回什么？
（2）这一轮结束后，`tool_cap_streak` 是多少？什么条件下才会真正开启工具收尾窗？
（3）注释里说的「**grace-cliff**」指什么？为什么单轮大并行「只能靠提醒让模型收敛」？

**参考答案要点**
`budget.py:285-320`（原文）：

```python
def begin_turn(self) -> None:
    """进入一次真实模型 API 请求，并重置该 Turn 的 Tool Call 计数。"""
    if self.grace_started:
        self.grace_turns_used += 1
    # 工具态收尾(grace-cliff 修复)：只有"连续 MAX_TOOL_CAP_STREAK 轮持续
    # 顶满/超出单轮工具配额"才启动工具收尾窗口；单轮爆发仅拒绝溢出调用，
    # 不开启整轮倒计时。上一轮未满配额则清零连续计数。
    if self._turn_hit_tool_cap:
        self.tool_cap_streak += 1
    else:
        self.tool_cap_streak = 0
    self._turn_hit_tool_cap = False
    self.turn_count += 1
    self.current_turn_tool_calls = 0
    if not self.grace_started and self.tool_cap_streak >= MAX_TOOL_CAP_STREAK:
        self._start_grace("max_tool_calling")


def begin_tool_call(self) -> bool:
    """在实际进入 Agent tool interface 前尝试占用一个 Tool Call 配额。

    返回 False 表示本次请求被预算层跳过，调用方必须生成确定性的错误
    ToolResult，且不能进入工具实现。该方法无 await，在并发任务间保持
    单次事件循环内的原子计数。

    这里只排队一次性"工具使用过多"提醒并标记本轮顶满配额，**不**立即
    开启共享收尾窗口——单轮大并行批次只能靠提醒让模型收敛，不能把整个
    submit 的剩余轮次烧光(grace-cliff)。
    """
    if self.current_turn_tool_calls >= self.max_tool_calling:
        self._queue_notice("max_tool_calling")
        return False
    self.current_turn_tool_calls += 1
    if self.current_turn_tool_calls >= self.max_tool_calling:
        self._turn_hit_tool_cap = True
        self._queue_notice("max_tool_calling")
    return True
```

**（1）前 64 次与后 136 次的返回不同**：

- 第 1~63 次：`current_turn_tool_calls` 从 0 增到 63，**返回 True**（允许）；
- **第 64 次**：`current` 增到 64，因为 `64 >= 64` → 置 `_turn_hit_tool_cap = True`，排队一次提醒，**返回 True**；
- **第 65~200 次**：`current_turn_tool_calls(64) >= max_tool_calling(64)` → 排队提醒，**返回 False**。

对返回 False 的调用，调用方**必须生成确定性的错误 ToolResult 且不进入工具实现**（docstring 明确）——即「拒绝」是通过**返回一个错误结果**表达的，不是静默丢弃（模型必须能看到「这次被预算拒绝了」，否则 tool_use ↔ tool_result 配对会断，`query_loop` 的配对修复机制会被卷进来）。

**（2）`tool_cap_streak` 的值**：
本轮置了 `_turn_hit_tool_cap = True`，所以下一次 `begin_turn()` 时 `tool_cap_streak += 1` → **1**。

**只有连续 `MAX_TOOL_CAP_STREAK = 2` 轮**都顶满配额，才 `_start_grace("max_tool_calling")`。若下一轮没有顶满（`_turn_hit_tool_cap` 仍为 False），`tool_cap_streak` 会被**清零**，计数从头开始。

**（3）grace-cliff 指什么**：
「grace 悬崖」——如果**单轮**顶满工具配额就立刻开启共享收尾窗，那么这一轮里**剩下的所有轮次**（`max_turns` 还有几百轮）都会被判为「收尾中」。后果是：

- 整个 submit 的后续预算被**一次性烧光**；
- 一个「模型一次并发发起太多调用」的**局部行为**被放大成「整个回合进入收尾」的**全局后果**；
- 而且这个决定是**不可逆的**（grace 是单向闩锁，见 0118）。

**为什么单轮只能靠提醒**：因为「一次并发 200 个调用」既可能是**模型犯错**（该分轮做），也可能是**合理的大批量操作**（例如批量重命名 200 个文件）。引擎无法区分，而它的取向是不导演——所以选择：

- **执行层做确定的限制**（超出配额的调用一律返回 False + 错误结果）；
- **注意力层只给一次事实提醒**（`max_tool_calling` 文案）；
- **把「是否进入收尾」的判定推迟到「连续 2 轮都顶满」**，让「持续行为」而不是「单次爆发」决定全局状态。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的三个层次：① **配额占用的返回约定**（False + 确定性错误结果，保持配对完整）；② **连续计数 vs 累计计数**（`tool_cap_streak` 要求连续，`_turn_hit_tool_cap` 是每轮标记）；③ **局部行为不应触发全局不可逆状态**。

`begin_tool_call` 的 docstring 还点明了一个并发细节：「该方法**无 await**，在并发任务间保持单次事件循环内的原子计数」——因为 200 个工具调用可能在同一个事件循环里并发进入，若函数内有 `await`，`current_turn_tool_calls` 的检查与自增之间就可能被其他任务插入（超发）。**无 await = 单线程内的原子性**，这是 Python asyncio 下最轻量的「锁」。



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

### XEYO-QA-0120 运行时提醒的去重与排序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | `queue_runtime_notice` 的规则 | 中等 | 机制解释 | `python/engine/budget.py:330-346` |

**面试官提问**
`queue_runtime_notice(text)` 在什么情况下**不**入队？它用哪个集合做「一次性」保证？入队后为什么还要 `sort`，排序键是什么？返回值表示什么？

**参考答案要点**
`budget.py:330-346`（原文）：

```python
def queue_runtime_notice(self, text: str) -> bool:
    """排队一条一次性运行时提醒（按文本去重），返回是否新增。

    供引擎层（如重复调用守卫）注入"停止重复"类提示；与软上限提醒共用
    同一下一轮消费通道。空文本与完全相同的文本会被忽略。
    """
    clean = str(text or "").strip()
    if not clean or clean in self._pending_notices:
        return False
    if clean in self._notified_reasons:
        return False
    self._notified_reasons.add(clean)
    self._pending_notices.append(clean)
    self._pending_notices.sort(
        key=lambda value: 0 if value == MAX_TURN_WARNING else 1
    )
    return True
```

**三项过滤（任一命中即不入队并返回 False）**：
1. **空文本**（`clean` 为空，`strip()` 后）；
2. **已在待发队列**（`clean in self._pending_notices`）；
3. **历史上已发过**（`clean in self._notified_reasons`）。

**「一次性」的保证靠 `_notified_reasons`**：这个集合记录**曾经排队过的全部文本**，且只增不减（直到 `reset_for_new_submit`）。所以同一条提醒在**整个 submit 内只会被注入一次**——即使调用方（例如循环里每轮都排队 `max_turns` 提醒的 `prepare_next_turn`，见 0118）反复调用。

**排序的意义**：

```python
self._pending_notices.sort(key=lambda value: 0 if value == MAX_TURN_WARNING else 1)
```

`MAX_TURN_WARNING`（「回合数已接近上限。」）被排到**最前**，其余排后。这是一个**稳定优先级**：`list.sort` 是稳定排序，所以同类项保持插入顺序。

为什么「回合数接近上限」优先？因为它是**最接近硬停**的信号——`MAX_GRACE_TURNS` 用尽后回合就结束了。把最紧迫的事实放前面，让模型在同一段文本里先看到它。

**返回值**：`True` = **本次新增了一条**；`False` = 被过滤（空/重复）。调用方可以据此判断「是否真的产生了新信息」。

**深化讲解**（面试官参考，不要求候选人全说）
这题有两个容易漏的点：

1. **去重是「永久」而非「队列内」**——`_notified_reasons` 与 `_pending_notices` 是两个容器：前者是「历史全集」（只增），后者是「待发队列」（消费时清空）。只检查后者的话，同一条提醒在消费后可以再次入队（变成多次注入）。两个都检查才实现「一次性」。
2. **排序发生在每次追加后**，而不是消费时。这样消费时只需 `"\n".join(...)`（见 0121），逻辑简单且顺序确定。

注意 docstring 的定位：「供**引擎层**（如重复调用守卫）注入『停止重复』类提示」——说明这个通道是**引擎机制之间**共享的注入口，`RepeatCallGuard` 的多档提示也走它（对照 B02 的 `repeat_guard.py`）。



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

### XEYO-QA-0121 提醒的一次性消费

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | `consume_runtime_notice` 的边界 | 中等 | 机制解释 | `python/engine/budget.py:322-328` |

**面试官提问**
`consume_runtime_notice()` 在没有待发提醒时返回什么？多条提醒如何合并？它的 docstring 明确说明了「**不写入历史或 SSE**」——请解释这句话的工程含义，以及它与 `queue_runtime_notice` 的配对关系。

**参考答案要点**
`budget.py:322-328`（原文）：

```python
def consume_runtime_notice(self) -> str | None:
    """取出仅用于下一次模型请求的临时提醒，不写入历史或 SSE。"""
    if not self._pending_notices:
        return None
    notice = "\n".join(self._pending_notices)
    self._pending_notices.clear()
    return notice
```

- **无待发时返回 `None`**（不是空字符串）——调用方可以用 `if notice:` 判断；
- **多条合并且用 `"\n"` 连接**（换行分隔，每条独占一行，便于阅读）；
- **取走即清空**（`clear()`），是一次性的。

**「不写入历史或 SSE」的工程含义**：

| 载体 | 是否写入 | 后果 |
|---|---|---|
| `MessageStore` / transcript 历史 | **不写** | 提醒不会成为持久化对话记录的一部分 |
| SSE 事件流 | **不推** | 前端不会看到这条系统提醒（它只是给模型的） |
| 下一次模型请求的 T_now 投影 | **写** | 提醒出现在下一轮的模型上下文里 |

也就是说：这条提醒是**「只给模型看一轮」的临时注入**。调用点见 B02 的 `query_loop.py:813`：

```python
runtime_notice = budget.consume_runtime_notice()
```

紧接着它会经 T_now 装配进下一轮（`query_loop.py:813-816` 的注释说明「每轮刷新 → 剩余墙钟变化可被工具层看到」）。

**与 `queue_runtime_notice` 的配对关系**：

| 方向 | 方法 | 容器 | 性质 |
|---|---|---|---|
| 入队 | `queue_runtime_notice(text)` | `_pending_notices`（+`_notified_reasons`） | 写入、去重、排序 |
| 出队 | `consume_runtime_notice()` | `_pending_notices` | 读取、合并、清空 |

**关键推论**：既然消费即清空，那么「一次性」实际上由**两层**共同保证：
- 队列层：消费后队列空 → 不会再被重复消费；
- 历史层：`_notified_reasons` 阻止同一文本再次入队（见 0120）。

**只有两层都在**，才能保证「同一条事实提醒在整个 submit 内只注入一次」；去掉任一层都会退化（去掉队列清空 → 每轮重复注入；去掉历史集合 → 消费后可再次入队）。

**深化讲解**（面试官参考，不要求候选人全说）
这题适合训练「**注入通道的生命周期**」这一思维。XEYO 里有多个类似的「投影-only」通道——最典型的是 `engine/resume_directive.py`（续跑指令，对照 B02-0052 的 `finally` 清理），它们共同的特征是：**只影响下一轮模型上下文，不污染权威记录**。

这样设计的好处：① transcript 保持「只有真实对话与工具结果」，回溯/审计读取时不会被引擎临时提醒干扰；② 提醒的**失效是自动的**（消费即清），不需要「到期清理」逻辑。



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

### XEYO-QA-0122 尾部保护为什么按「工具轮」而不是「消息条数」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | compact | 工具配对区间与尾部保护区 | 中等 | 机制解释 | `python/engine/compact.py:25-27,30-51,69,87-115` |

**面试官提问**
`compact.py` 里 `KEEP_TAIL_MESSAGES = 6` 的注释说它是「**兼容旧名**」，新的口径是 `KEEP_TAIL_TOOL_ROUNDS = 3`（「按『assistant(tool_calls)+连续 tool』成对区间保留的轮数」）。

（1）为什么「按消息条数」是不安全的？
（2）`tool_pair_ranges(messages)` 提供什么数据？`_assistant_tool_ids(msg)` 与 `_tool_result_ids(msg)` 各自提取什么？
（3）`keep_tail_cut(...)` 与 `split_at_cursor(...)` 在投影流程里扮演什么角色？

**参考答案要点**
`compact.py` 相关定义：

```python
KEEP_TAIL_MESSAGES = 6              # 兼容旧名：等价于保留约 N 条消息的尾部保护区
KEEP_TAIL_TOOL_ROUNDS = 3           # 按「assistant(tool_calls)+连续 tool」成对区间保留的轮数
def _assistant_tool_ids(msg: dict[str, Any]) -> list[str]:      # :30
def _tool_result_ids(msg: dict[str, Any]) -> list[str]:         # :51
def tool_pair_ranges(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:   # :69
def _keep_tail_rounds() -> int:                                  # :87
def keep_tail_cut(...)                                           # :95
def split_at_cursor(...)                                         # :116
```

**（1）按消息条数为什么不安全**：
在 XEYO 的消息模型里，**一条 assistant 消息可能携带 N 个 `tool_use` 块**（一轮并发发起 N 个工具），而工具结果可能分布在**后续多条**消息里（多模态/分组情况下更碎）。所以「保留最后 6 条消息」可能：

- **切断工具调用与结果的配对**——保留了一个 `assistant(tool_use)` 但它对应的 `tool_result` 落在地平线之外（或反之）。这种「悬空 tool_use」会被下游的配对修复机制（`query_loop._repair_unpaired_tool_calls`，见 B02-0079 相关）当成「aborted」处理，注入虚假的失败结果；
- **保护力度随内容形态剧烈波动**——6 条消息可能包含 3 条纯文本（信息极少），也可能包含 6 条各带 20 个工具结果（信息极多）。预算不可预测。

**（2）三个函数的职责**：

| 函数 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `_assistant_tool_ids(msg)` | 一条消息 | 该消息里所有 `tool_use` 的 id 列表 | 识别「调用侧」 |
| `_tool_result_ids(msg)` | 一条消息 | 该消息里所有 `tool_result` 的 id 列表 | 识别「结果侧」 |
| `tool_pair_ranges(messages)` | 全部消息 | `[(start, end), ...]` 索引区间列表 | 给出**成对区间**，使裁剪可以按「整段工具往返」为单位 |

`tool_pair_ranges` 是这套设计的核心产物：它把消息序列切成若干个**自洽的区间**（一个 assistant 的多个 tool_use + 对应的全部 tool_result）。有了它，裁剪就能**以区间为单位取舍**，而不会切在配对中间。

**（3）两个函数在投影流程中的角色**：
- `keep_tail_cut(...)`：根据 `_keep_tail_rounds()`（即 `KEEP_TAIL_TOOL_ROUNDS`）计算出**尾部保护区**的起点——保护区内的内容**不参与压缩/截断**；
- `split_at_cursor(...)`：在给定游标处把历史**切分**（通常是「待压缩的前段」与「保留的后段」）。

二者一个定边界、一个做切分，配合 `project(...)`（`:125`）完成「保留尾部 + 投影前段」的整体流程，而 `project_incremental(...)`（`:286`）是同族的**增量版本**。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于「**数据结构决定裁剪安全性**」。如果消息是「一条消息 = 一个工具往返」的简化模型，按条数切就够用；但 XEYO 的消息是**多块（blocks）结构**（一条 assistant 可含多个 tool_use），所以必须显式恢复配对关系（`tool_pair_ranges`）。这也是为什么 `KEEP_TAIL_MESSAGES` 被标注为「兼容旧名」——旧口径在新数据形态下不可靠，保留它只是为了让还没迁移的调用点继续工作。



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

### XEYO-QA-0123 project 与 project_incremental 的一致性要求

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | compact | 全量投影与增量投影 | 中等 | 机制解释 | `python/engine/compact.py:125,143,221,286` |

**面试官提问**
`compact.py` 里同时存在 `project(...)`（`:125`）与 `project_incremental(...)`（`:286`）。请说明：① 两者的定位差异；② `_process_message(...)`（`:221`）与 `build_tool_use_names(...)`（`:143`）在其中的作用；③ 两条路径必须满足什么一致性约束，否则会出现什么现象？

**参考答案要点**
实测函数面：

```python
def project(...)                                    # :125 —— 全量投影入口
def build_tool_use_names(history) -> dict[str, str] # :143 —— tool_use_id → 工具名
def _collect_tool_use_names(...)                    # :148
def _project_tool_result_content(...)               # :167 —— 单块结果内容投影
def _process_message(...)                           # :221 —— 单条消息投影
def project_incremental(...)                        # :286 —— 增量投影
def _iter_tool_result_blocks(msg)                   # :314
def _block_text_len(block)                          # :331
def _message_chars(history)                         # :344
```

**① 定位差异**：
- `project(...)` 是**全量**入口：给定完整历史，算出投影后（压缩/截断/折叠后）的历史；
- `project_incremental(...)` 是**增量**入口：历史只增不改，因此可以复用上一次的结果，只处理**新增的消息**（避免每轮都对全量历史重算）。

**② 两个函数的作用**：
- `_process_message(...)`：**单条消息的投影逻辑**（提取文本块、处理 tool_result 内容等）。它是两条路径的**共享单元**——全量遍历每条消息，增量只处理新增的那些，但「怎么处理一条」必须一致；
- `build_tool_use_names(history)`：构建 **`tool_use_id` → 工具名** 的映射（内部由 `_collect_tool_use_names` 收集）。作用：处理 `tool_result` 时，结果块通常只带 `tool_use_id` 不带工具名，需要回查名字才能标注「这是哪个工具的输出」（老化存根、截断标记都要用工具名，见 0104）。

**③ 一致性约束**：**对同一份输入，两条路径必须产出逐字节相同的结果**（增量结果 == 全量重算结果）。

违反时的现象：**投影抖动**。增量路径复用了上一轮的缓存，而全量路径重算——如果两者的判定细节有差异（例如增量路径没有重新评估「尾部保护区」的边界，或者缓存里保留了已被折叠的旧内容），则：

- 同一份历史在不同调用点/不同轮次得到**不同投影**；
- 依赖「投影稳定」的下游全部受影响：缓存命中（前缀逐字节相同才命中 KV 缓存）、内容的哈希比较（`repeat_fold._digest` 用的就是内容摘要）、UI 展示的一致性；
- 而且故障表现是**间歇性的**（只在缓存与重算不一致时出现），极难定位。

这也是 `aging.py` 强调「**确定性，增量投影一致**」、`sanitize_summary` 强调「对任意输入**确定性**输出（R26）」的统一动机。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的核心是「**同一语义的多条实现路径必须可证等价**」。工程上常见的做法是让增量路径**复用**全量路径的单单元（这里就是 `_process_message`），差别只在「遍历哪些消息」。注释里的 `KEEP_TAIL_*` 口径演进（见 0122）也是同一问题的另一面——保护区边界必须是**确定性函数**，否则增量复用的边界会漂移。

配合 `_message_chars(history)`（`:344`，统计字符数）与 `_block_text_len(block)`（`:331`，单块文本长度），可以看出投影还需要**计量**能力（决定能保留多少、压掉多少）。



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

### XEYO-QA-0124 工具结果的截断阈值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | compact | 结果内容截断 | 中等 | 代码阅读 | `python/engine/compact.py:24,27,167,314,331` |

**面试官提问**
`compact.py` 对单个工具结果的默认截断阈值是多少？截断标记的精确字面量是什么？`_iter_tool_result_blocks(msg)`（`:314`）与 `_block_text_len(block)`（`:331`）为什么必须存在——直接用「整条消息的字符串长度」不行吗？

**参考答案要点**
`compact.py:24,27`：

```python
MAX_TOOL_RESULT_CHARS = 8_192
TRUNCATE_SUFFIX = "\n…[truncated]"  # 截断时追加的后缀
```

**阈值 8192 字符**；标记为 `"\n…[truncated]"`（换行 + U+2026 + ASCII `[truncated]`）。执行截断的逻辑在 `_project_tool_result_content(...)`（`:167`）——即**逐块投影**时对内容块做长度控制。

**为什么需要 `_iter_tool_result_blocks` 与 `_block_text_len`**：

因为 XEYO 的消息内容不是「一个字符串」，而是**块列表**（`list[block]`；assistant 消息含 `tool_use` 块，tool 消息含 `tool_result` 块，可能还混有文本/图像块）。所以：

- **`_iter_tool_result_blocks(msg)`**：从一条消息里**筛出**所有 `tool_result` 块。一条消息可能包含多个结果块（一轮并发 N 个工具的结果可以放在同一条 tool 消息里），必须逐个处理——否则只能做「整条消息一刀切」，无法对单个结果独立设限；
- **`_block_text_len(block)`**：计算**单个块**的文本长度。块的形态不同（文本块、结构化块、含附件引用的块），长度口径需要统一，才能让「8192 字符」这个阈值有确定含义。

**直接用整条消息的字符串长度的问题**：
1. **口径错误**：`str(msg)` 包含键名、JSON 结构、转义符——与「内容长度」无关。8192 这个数字将失去意义；
2. **粒度错误**：一条消息里有 5 个工具结果时，只能对整条设限——可能 1 个超长把其余 4 个也带上截断，或反之全部放过；
3. **结构破坏**：对 JSON 序列化结果直接切片，容易产生**非法结构**（半个引号、半个括号），下游解析会炸。

**深化讲解**（面试官参考，不要求候选人全说）
这题的关键是「**预算的单位必须与内容的自然边界对齐**」。XEYO 的块结构决定了「一刀切字符串」不可行，所以库里有成对的「枚举块 / 量块」小函数。

`8_192`（= 8192 = 8 KiB）这个数字本身也值得注意：它与 `query_loop._tool_input_summary` 的 **200 字符**（B02-0056）、`aging` 的 **60 字符摘要**（0104）形成一组「**不同层的预算梯度**」：

| 层 | 预算 | 目的 |
|---|---|---|
| 事件摘要（`tool_call.begin`） | 200 字符 | 让前端/日志能显示参数 |
| 老化存根摘要 | 60 字符 | 让模型知道「这是什么工具做过什么」 |
| 工具结果内容 | 8192 字符 | 投影时的单块上限 |



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

### XEYO-QA-0125 折叠的两档判定顺序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_fold | `process()` 的判定流程 | 中等 | 机制解释 | `python/engine/repeat_fold.py:97-135` |

**面试官提问**
`IdenticalResultFold.process(tool_name, input_data, content)` 返回 `(text, folded)`。请按源码顺序说明：① 等价档状态在什么时候推进、为什么要在逐字节档之前；② `key` 是怎么构造的；③ `seq` 何时递增、何时重置；④ 两档都命中时哪个优先、为什么。

**参考答案要点**
`repeat_fold.py:97-135`（原文）：

```python
def process(self, tool_name, input_data, content) -> tuple[str, bool]:
    d = _digest(content)
    text = str(content or "")

    # 等价档状态推进（先于逐字节档：seen 集合需登记本次摘要）。
    equi_n = 0
    if _equiv_enabled() and d:
        seen = self._equi_seen.setdefault(tool_name, set())
        if d in seen:
            self._equi_seq[tool_name] = self._equi_seq.get(tool_name, 0) + 1
        else:
            self._equi_seq[tool_name] = 0
            seen.add(d)
        equi_n = self._equi_seq[tool_name] + 1

    key = f"{tool_name}\x00{semantic_key(tool_name, input_data)}"
    last_digest, seq = self._state.get(key, ("", 0))
    if d and d == last_digest:
        seq += 1
    else:
        seq = 1
    self._state[key] = (d, seq)
    if seq >= self.fold_after:
        if seq == self.fold_after:
            return _FOLD_EXPLAIN.format(n=seq), True
        return _REPEAT_SHORT.format(n=seq), True
    if _equiv_enabled() and equi_n >= _fold_equiv_at():
        return _FOLD_EQUIV.format(n=equi_n), True
    return text, False
```

**① 等价档状态先推进的原因**：源码注释写明「**先于逐字节档：seen 集合需登记本次摘要**」。

细看逻辑：等价档用 `_equi_seen[tool_name]` 记录该工具**历史上出现过的全部结果摘要**。它必须在本次判定中**先把当前摘要登记进去**，然后才能用「`d in seen`」判断「这次是不是重复」。同时 `_equi_seq` 是「等价重复的**连续**计数」（新内容出现即清零）。

**② `key` 的构造**：`f"{tool_name}\x00{semantic_key(tool_name, input_data)}"` —— 工具名 + **NUL 分隔符**（`\x00`）+ 入参的**语义归一化签名**（`semantic_key`，来自 `repeat_guard`，见 B02-0064）。用 NUL 而不是冒号/下划线，是为了避免「工具名里含分隔符」造成歧义。

注意 `key` 里**不含输出内容**——它标识「同一签名」，输出是否相同由 `_state[key]` 里存的 `last_digest` 判断（这正是「同签名 + 相邻输出逐字节相同」的实现）。

**③ `seq` 的增减**：

```python
if d and d == last_digest:
    seq += 1     # 与上一次该签名的输出相同 → 连续计数 +1
else:
    seq = 1      # 输出变了（或空摘要）→ 重置为 1
```

「输出一变即重置」对应 docstring 的「**合法轮询豁免**」：合法的轮询（后台 job 状态、长任务进度）输出里通常含时间戳/进度，逐字节比对几乎必然不同 → `seq` 一直停在 1 → 永不折叠。

**④ 两档都命中时的优先级**：**逐字节档优先**（代码顺序：`if seq >= self.fold_after` 分支在前，落在前面就 `return` 了）。理由写在 docstring 里：

> 两档判定独立计数，逐字节档（同签名相邻相同）优先于等价档（同工具跨签名同内容）——**前者文案更具体**。

`_FOLD_EXPLAIN` 说的是「同一签名的第 N 次调用，输出与首次逐字节相同」——比 `_FOLD_EQUIV` 的「与该工具既往某次输出完全相同」更精确。给模型更具体的信息，是优先级的方向。

**深化讲解**（面试官参考，不要求候选人全说）
还有一个不在题干里但必须注意的细节：`if _equiv_enabled() and d:` —— 等价档还有两个前置条件：**总开关开启**（见 0126）且**摘要非空**（`_digest` 在异常时返回 `""`，空摘要不参与等价判定，避免把「无法计算摘要」误判为「内容相同」）。

另外 `_state` 存的是 `(last_digest, seq)`，等价档用另外两个字典（`_equi_seen` / `_equi_seq`）——**两档状态完全独立**，因为它们的判据与生命周期都不同（前者是「相邻」，后者是「历史集合」）。



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

### XEYO-QA-0126 等价档的总开关语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_fold | `XEYO_LOOP_LEDGER` 与 `XEYO_FOLD_EQUIV_AT` | 中等 | 机制解释 | `python/engine/repeat_fold.py:57-70` |

**面试官提问**
`_equiv_enabled()` 读 `XEYO_LOOP_LEDGER`，`_fold_equiv_at()` 读 `XEYO_FOLD_EQUIV_AT`。两者的默认行为分别是什么？为什么 `_equiv_enabled` 写成「`!= "0"`」而不是「`in ("1","true",...)`」？`_fold_equiv_at` 对取值有什么额外要求？

**参考答案要点**
`repeat_fold.py:57-70`（原文）：

```python
def _fold_equiv_at() -> int:
    raw = os.environ.get("XEYO_FOLD_EQUIV_AT", "").strip()
    if raw:
        try:
            v = int(raw)
            if v >= 2:
                return v
        except ValueError:
            pass
    return DEFAULT_FOLD_EQUIV_AT


def _equiv_enabled() -> bool:
    """等价档随行为账本总开关（XEYO_LOOP_LEDGER=0 → 只保留原逐字节档）。"""
    return os.environ.get("XEYO_LOOP_LEDGER", "").strip() != "0"
```

**① 默认行为**：
- `_equiv_enabled()`：**默认开启**。环境变量未设置时 `""`（空串）`!= "0"` 为真 → 启用；
- `_fold_equiv_at()`：**默认 3**（`DEFAULT_FOLD_EQUIV_AT = 3`）。

**② 为什么写成 `!= "0"`**：这是一个**「默认开、显式关」**的开关（opt-out），而不是 opt-in。原因与 0103（老化默认关）形成鲜明对照：

| 机制 | 默认 | 开关形式 | 理由 |
|---|---|---|---|
| 输出老化（`aging`） | **关** | opt-in（`in ("1","true","on","yes")`） | 删除内容（原文从投影消失）且恢复机制未落地 → 证据完整性优先 |
| 结果折叠等价档（`repeat_fold`） | **开** | opt-out（`!= "0"`） | 折叠**不删原文**（首次完整输出仍在历史前部）→ 省上下文优先 |

`repeat_fold.py:11-12` 的 docstring 印证了这个「不删」的性质：

> 连续第 ``fold_after`` 次（默认 3）相同输出：把**该次**将写入 store / 送给模型的内容替换为一行解释性折叠行（**首次完整输出仍在历史前部，信息无损**）

所以「信息无损」→ 可以默认开；「信息有损」→ 默认关。**默认值的方向由可逆性决定**。

顺便：`XEYO_LOOP_LEDGER` 这个名字说明等价档**归属行为账本方案**（`loop_ledger.py`），关掉账本总开关，等价档也随之关闭，只保留原有的逐字节档（docstring 原话：「`XEYO_LOOP_LEDGER=0` → **只保留原逐字节档**」）。

**③ `_fold_equiv_at` 的额外要求**：`int(raw)` 成功后还要求 **`v >= 2`** 才采用。这与 `IdenticalResultFold.__init__` 的 `max(2, int(fold_after))`（见 0112）是**同一条约束的两次表达**：折叠必须从第 2 次起才可能发生（首次输出必须完整给出）。

不满足时的行为差异值得注意：
- `IdenticalResultFold.__init__` 传了 `fold_after=1` → **钳制到 2**（有效值）；
- `_fold_equiv_at()` 读到 `"1"` → **回落默认 3**（不采用 1，也不钳到 2）。

两者都是安全的（都不会让折叠在第 1 次就触发），但实现手法不同：一个是钳制，一个是回落。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的三层考点：① **默认值的方向由可逆性决定**（可逆→默认开，不可逆→默认关）；② **两个环境变量的解析风格不同**（opt-out vs 带下限的数值）；③ **同一约束在两层重复表达**（构造函数钳制 + 环境解析下限）。

顺带一个实用结论：要「只保留逐字节档」，设 `XEYO_LOOP_LEDGER=0`；要「让等价档更激进」，设 `XEYO_FOLD_EQUIV_AT=2`（最小值）。



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

### XEYO-QA-0127 行为账本的三个信号与渲染

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | loop_ledger | 计数器、入口与渲染 | 中等 | 机制解释 | `python/engine/loop_ledger.py:52-58,106-156,193,207,239` |

**面试官提问**
`LoopLedger` 通过什么入口更新三个信号？`render()` 产出什么、`reset()` 何时用？`ledger_enabled()` 与 `ledger_thresholds_from_env()` 分别做什么？`content_digest` / `params_digest` / `assistant_head` 三个工具函数各服务哪个信号？

**参考答案要点**
`loop_ledger.py` 的接口面（实测）：

```python
DEFAULT_LEDGER_AT = (3, 4, 3)          # :52
_HEAD_LEN = 30                          # :55
def ledger_enabled() -> bool            # :58
def ledger_thresholds_from_env() -> tuple[int, int, int]   # :63
def content_digest(content: Any) -> str # :75
def params_digest(params: Any) -> str   # :86
def assistant_head(text: Any) -> str    # :98
class LoopLedger:                       # :106
    def __init__(...)                   # :114
    @property s1 / s2 / s3 / tool_calls # :142,146,150,154
    def observe_tool(...)               # :157
    def observe_assistant(self, text)   # :193
    def render(self) -> str             # :207
    def reset(self) -> None             # :239
```

**更新入口（两个）**：
- `observe_tool(...)`（`:157`）——每次工具调用/结果时观测（服务 **s1 结果等价**、**s2 内容已见**）；
- `observe_assistant(text)`（`:193`）——每次 assistant 文本产出时观测（服务 **s3 首句重复**）。

**三个信号与三个工具函数的对应**：

| 信号 | 判据 | 依赖的工具函数 |
|---|---|---|
| **s1 结果等价** | 本次结果内容与既往某次相同 | `content_digest(content)`（内容摘要） |
| **s2 内容已见** | 本次要看的**入参**在历史里出现过 | `params_digest(params)`（参数摘要） |
| **s3 首句重复** | assistant 回复**开头**重复 | `assistant_head(text)` + `_HEAD_LEN = 30`（取开头 30 字符） |

**`render()` 与 `reset()`**：
- `render()`（`:207`）：把当前计数器渲染成给模型看的文本（**经 InjectContext 供 `pre_llm_inject` 直读**，见 B02-0100 引用的 `query_loop.py:779-781` 注释）；
- `reset()`（`:239`）：清零全部计数。生命周期是**每 submit 新建**（与 `RepeatCallGuard` / `IdenticalResultFold` 同步的用户输入级重置）。

**`ledger_enabled()` 与 `ledger_thresholds_from_env()`**：
- `ledger_enabled()`（`:58`）：账本总开关（与 0126 的 `_equiv_enabled` 同源——`repeat_fold` 的等价档就受它管）；
- `ledger_thresholds_from_env()`（`:63`）：从环境变量读三个阈值，返回 `tuple[int,int,int]`，默认即 `DEFAULT_LEDGER_AT = (3,4,3)`（见 0111）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题最有价值的是**s2 的存在**——它与其他两个信号正交：

- s1 看**输出**是否重复（结果维度）；
- s2 看**输入**是否已被覆盖（信息增量维度）；
- s3 看**表述**是否重复（assistant 文本维度）。

三个信号合起来能识别一类很难捕获的空转：**「模型反复要看已经看过的内容」**——例如它一次次 `Read` 同一个文件的同一段（s2 命中），虽然每次可能因上下文变化而「看起来合理」，但事实上**信息增量为零**。单纯看输出（s1）或表述（s3）都抓不到这种模式。

`_HEAD_LEN = 30` 也值得记：s3 只取 assistant 文本的**前 30 字符**做比较。理由是「首句重复」是个强信号且极小成本——不需要对全文做摘要。



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

### XEYO-QA-0128 paths 的三态语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_revision | `calculate(paths)` 的三种入参 | 中等 | 场景设计 | `python/engine/workspace_revision.py:76-100` |

**面试官提问**
`WorkspaceRevision.calculate(paths=None)` 的 docstring 说明：`paths=()`（空可迭代）与 `paths=None` 行为**不同**。请说明三种入参（`None` / `()` / 非空列表）各自指纹什么、适用什么场景，以及为什么需要区分。

**参考答案要点**
`workspace_revision.py:76-100`（原文）：

```python
def calculate(self, paths: Iterable[str] | None = None) -> str:
    """Calculate the current workspace revision without a content scan.

    ``paths=()`` (empty iterable) fingerprints shadow HEAD only — suitable
    for chat-only rollback where unrelated worktree noise must not block.
    ``paths=None`` keeps the legacy full porcelain fingerprint.
    """
    self.shadow_git.init_if_needed()
    head = self.shadow_git.head_commit() or "empty"
    metadata: list[str] = []
    if paths is not None:
        for relative_path in self.normalize_paths(paths):
            metadata.append(self._metadata_token("SC", relative_path))
    else:
        status_result = self.shadow_git._run(
            ["status", "--porcelain=v1", "--untracked-files=normal"], check=False,
        )
        status_text = status_result.stdout if status_result.returncode == 0 else "<status-error>"
        for line in status_text.splitlines():
            parsed = self._status_path(line)
            if parsed is not None:
                metadata.append(self._metadata_token(*parsed))
    metadata.sort()
```

**三态对照**：

| 入参 | 走哪个分支 | 指纹内容 | 适用场景 |
|---|---|---|---|
| `paths=None` | `else` 分支 | shadow git 的 **HEAD** + `git status --porcelain=v1 --untracked-files=normal` 列出的**全部变更路径**（含未跟踪）的元数据 | **legacy 全量指纹**（兼容旧调用） |
| `paths=()`（空） | `if paths is not None` 分支 | **只有 shadow HEAD**（`normalize_paths(())` 返回空 → `metadata` 为空 → 哈希只喂 head） | **纯聊天回滚**：工作区噪声不应阻断 |
| `paths=["a.py", ...]` | 同上 | shadow HEAD + **这些指定路径**的元数据（状态标记硬编码为 `"SC"`） | 「只关心我计划的这几个文件」 |

**为什么需要区分**：这是**「指纹稳定性」与「指纹覆盖面」的权衡**。

`WorkspaceRevision` 的类 docstring（`:12-20`）解释了动机：

> When ``paths`` is provided, only those relative paths are fingerprinted (plus shadow HEAD). That keeps **Vite/test churn outside the rollback plan from invalidating `expected_workspace_revision`**.

即：一个回滚计划在开始时会记下 `expected_workspace_revision`，执行前要校验「工作区还是原来那个」。如果用**全量**指纹，那么期间 Vite 的构建产物、测试缓存、临时文件的变化都会改变指纹 → **校验失败、回滚被误阻断**。而「纯聊天」场景根本不产生文件变更，此时用 `paths=()`（只认 HEAD）即可——**噪声再大也不影响**。

`paths=["a.py"]` 则是「我确实要动这几个文件，只关心它们有没有被别的东西改过」。

**深化讲解**（面试官参考，不要求候选人全说）
三个细节值得指出：

1. **`if paths is not None` 是判据，不是 `if paths:`** —— 否则空元组会掉进 legacy 分支（这正是「`()` 与 `None` 行为不同」的实现根因）；
2. **指定路径的 status 标记硬编码为 `"SC"`**（`_metadata_token("SC", relative_path)`）——因为没有走 `git status`，无法知道真实状态（M/A/D），只能用固定标记表示「指定路径扫描」；
3. **`normalize_paths` 会去重与归一化**（`workspace_revision.py:36-45`：反斜杠转正斜杠、去 `./` 前缀、去重）——保证「同一个文件的两种写法」不会让指纹变化。

`metadata.sort()`（`:101`）在**所有分支之后**统一执行——保证路径枚举顺序不影响结果（见 0115）。



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

### XEYO-QA-0129 元数据指纹为什么读 lstat 而不读内容

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_revision | `_metadata_token` 的字段构成 | 中等 | 机制解释 | `python/engine/workspace_revision.py:47-74` |

**面试官提问**
`_metadata_token(status, relative_path)` 生成一个 token 参与指纹哈希。请说明：① 它用了哪些 stat 字段、为什么用 `st_mtime_ns` 而不是秒级；② 它在三种异常/特殊情况下返回什么；③ 为什么「不读文件内容」是一个有意选择，代价是什么？

**参考答案要点**
`workspace_revision.py:47-74`（原文）：

```python
def _metadata_token(self, status: str, relative_path: str) -> str:
    candidate = (self.workspace_root / relative_path).resolve(strict=False)
    try:
        relative = candidate.relative_to(self.workspace_root)
    except ValueError:
        return f"{status}\0{relative_path}\0outside-workspace"

    try:
        stat = os.lstat(candidate)
    except FileNotFoundError:
        return f"{status}\0{relative.as_posix()}\0missing"
    except OSError as exc:
        return f"{status}\0{relative.as_posix()}\0error:{type(exc).__name__}"

    if os.path.islink(candidate):
        try:
            link_target = os.readlink(candidate)
        except OSError:
            link_target = "<unreadable>"
        kind = f"symlink:{link_target}"
    elif os.path.isdir(candidate):
        kind = "directory"
    else:
        kind = "file"
    return (
        f"{status}\0{relative.as_posix()}\0{kind}\0{stat.st_size}"
        f"\0{stat.st_mtime_ns}\0{stat.st_ctime_ns}\0{stat.st_mode}"
    )
```

**① 字段构成**：`status`、相对路径、`kind`（file/directory/symlink:target）、`st_size`、`st_mtime_ns`、`st_ctime_ns`、`st_mode`。

**为什么用 `st_mtime_ns`（纳秒）而不是秒级**：秒级精度**不足以区分同一秒内的两次修改**。在自动化场景（构建/测试/格式化工具连续改写同一文件）里，两次写入可能落在同一秒——用秒级时间戳，指纹**不会变化**，于是「工作区已变」被漏判，乐观校验失效。纳秒精度把碰撞概率降到可忽略。

（同类：`st_ctime_ns` 也取纳秒；`st_mode` 参与是为了捕捉**权限/类型变化**——例如 `chmod +x` 不改内容但确实改变了工作区语义。）

**② 三类异常/特殊返回**：

| 情况 | 判定 | 返回值中的标记 |
|---|---|---|
| 路径解析后**在工作区外** | `relative_to` 抛 `ValueError` | `outside-workspace` |
| 文件**不存在** | `lstat` 抛 `FileNotFoundError` | `missing` |
| 其它 IO 错误 | `lstat` 抛 `OSError` | `error:<异常类型名>` |
| 符号链接 | `os.path.islink` 为真 | `symlink:<target>`（读不出目标时为 `symlink:<unreadable>`） |
| 目录 / 普通文件 | `isdir` 判定 | `directory` / `file` |

**「不读内容」的代价**：token 里**没有内容哈希**，所以「**内容变了但 size/mtime/ctime 全都不变**」的修改**检测不到**。这在理论上可能（例如原地覆写相同长度内容并手动把时间戳改回去），但现实中：

- 正常编辑一定会改变 `mtime_ns`；
- 该指纹服务的场景是「**乐观校验**」（判断「我准备回滚的东西还是不是我记下的那个」），**不是**安全校验（防篡改）。防篡改需要内容哈希，成本是**全量读盘**。

**收益**：`calculate()` 的 docstring 明确写着「**without a content scan**」（不做内容扫描）。对一个可能包含几十万文件的工作区，逐文件读内容会带来秒级甚至更长的延迟；而 `lstat` 是元数据操作，快几个数量级。在「回滚执行前校验」这个高频、时间敏感的位置，这个取舍是合理的。

**深化讲解**（面试官参考，不要求候选人全说）
这题是「**指纹的精度与成本**」的典型权衡题。三个观察点：

1. `resolve(strict=False)` + `relative_to` 的组合处理了**路径穿越**（`../` 逃出工作区）——返回 `outside-workspace` 而不是报错；
2. `os.lstat` 而非 `os.stat`：**lstat 不跟随符号链接**——所以能识别「这是个链接」并记录链接目标。若用 `stat`，链接会被解析成目标文件，链接本身的变化（改指向）就检测不到；
3. NUL（`\0`）作字段分隔符——与 0125 的 `key` 构造同理，避免字段内容含分隔符导致歧义。



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

### XEYO-QA-0130 WriteStore 的三个数据类型

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | write_store | `EditOp` / `ChangeIntent` / `ApplyResult` | 中等 | 机制解释 | `python/engine/write_store.py:31-70` |

**面试官提问**
`write_store.py` 开头定义了三个数据类型。请说出它们的名字与大致职责，并解释为什么写路径要用「意图（intent）」而不是「直接写」。

**参考答案要点**
`write_store.py:31-70`（实测）：

```python
class EditOp:            # :31
    def kind(self) -> str: ...        # :40
class ChangeIntent:      # :47
class ApplyResult:       # :58
```

**三个类型的职责**：

| 类型 | 职责 | 关键成员 |
|---|---|---|
| `EditOp` | **单次编辑操作**的描述（要做什么改动）；`kind()` 返回操作种类（如 create/modify/delete 之类） | `kind()` 属性 |
| `ChangeIntent` | **变更意图**：把一个或多个 `EditOp` 与上下文（工作区、会话、基准哈希等）打包成一次提交 | 供 `submit(intent)` 消费 |
| `ApplyResult` | **应用结果**：提交被应用后的结果（成功/失败、影响路径、哈希等） | 由 `submit` / `submit_sync` 返回 |

**为什么用「意图」而不是「直接写」**：

1. **可校验**：意图是一个**数据对象**，可以在真正落盘前做一系列检查——语法检查（`_syntax_ok`，见 0134）、基准哈希校验（`_lookup_base_hash`，见 0131）、路径归一化（`_canon`，`:198`）。直接写就没有这个中间阶段；
2. **可并发调度**：`submit(intent) -> Awaitable[ApplyResult]` 意味着意图可以**排队**，由分片锁（见 0114）决定串行或并行——调用方不需要自己管理锁；
3. **可记录/可审计**：意图是结构化数据，可以写日志、算 diff（`_make_unified_diff`，`:140`）、上报；而「直接 `open().write()`」不留痕迹；
4. **可多文件事务**：一个 `ChangeIntent` 可以包含多个 `EditOp`（`_apply_multi`，`:364`），从而支持「要么都成功、要么都不做」的语义（见 0142）；
5. **可回滚**：有了「意图 + 结果」，就能在失败时知道**已经改了什么**，从而回退（`_apply_core` 里的失败处理）。

**深化讲解**（面试官参考，不要求候选人全说）
这题的落点是「**把副作用推迟到数据校验之后**」这个通用模式。XEYO 里同一模式的其它实例：

- `permissions` 的裁决结果（决策对象先产生，再执行）；
- `aging` 的「纯函数与开关，**不碰存储**」（`aging.py:3`：「本模块只提供纯函数与开关，不碰存储」）；
- `compact` 的「**只在结果写入前决定替换文本**，不触碰 MessageStore 的历史条目」（`repeat_fold.py:20`）。

共同特征：**计算决策 与 施加副作用 分离**。这让校验、并发、审计、回滚都有插入点。

`_MAX_DIFF_LINES = 400`（`:137`）也属于同一簇设计——diff 用于展示，需要有长度上限（与 0124 的 8192 字符上限是不同用途的两个预算）。



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

### XEYO-QA-0131 写入前的基准哈希校验

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | write_store | 乐观并发控制 | 中等 | 机制解释 | `python/engine/write_store.py:71,88,389` |

**面试官提问**
`write_store.py` 里有 `_content_hash(path)`（`:71`）、`_content_hash_text(content)`（`:88`）与 `_lookup_base_hash(intent, path)`（`:389`）。请说明「基准哈希（base hash）」的作用——它防的是什么？为什么这个防护在「多个会话/多个代理并行改同一工作区」时是必需的？

**参考答案要点**
三个函数（实测签名）：

```python
def _content_hash(path: Path) -> str          # :71 —— 读文件算内容哈希
def _content_hash_text(content: str) -> str   # :88 —— 对给定文本算哈希
def _lookup_base_hash(intent, path) -> str    # :389 —— 取该次意图的基准哈希
```

**base hash 的作用**：它是**乐观并发控制（optimistic concurrency control）**的比对依据。

机制是：调用方在**读取文件准备编辑时**，记下当时内容的哈希（base hash）；提交 `ChangeIntent` 时把它一并带上。写入前，`_apply_core`（`:234`）会调 `_lookup_base_hash` 取回基准值，并与**磁盘当前的** `_content_hash(path)` 比对：

- **一致** → 说明「我读到的东西到现在没被别人改过」→ 允许写入；
- **不一致** → 说明**在我读完之后、写之前，有人改了它** → 拒绝写入（或走冲突处理），避免**静默覆盖他人的修改**。

**为什么在并行场景必需**：XEYO 支持多会话/多代理（多 surface 会话、子代理、多代理 DAG）。若没有 base hash 校验，典型事故是：

1. 会话 A 读 `config.py`，看到 `x = 1`；
2. 会话 B 把 `x = 1` 改成 `x = 2` 并写入；
3. 会话 A 基于「`x = 1`」的位置信息构造编辑（例如「把第 3 行的 `1` 换成 `9`」），写入成功；
4. 结果：**B 的修改被无声吞掉**（如果 A 写的是整文件内容），或**语义错乱**（A 的补丁应用在 B 的内容上）。

base hash 把这类事故从「**静默数据丢失**」变成「**显式的冲突拒绝**」——后者可恢复（重读再改），前者不可恢复。

**深化讲解**（面试官参考，不要求候选人全说）
注意 `_content_hash` 与 `_content_hash_text` 的**成对**设计：前者对**磁盘文件**算哈希（用于校验现状），后者对**字符串**算哈希（用于描述「我要写成什么」或计算「新内容哈希」）。两者必须是**同一算法**，否则比对无意义（对照 0130 提到的「同一语义多条路径必须等价」）。

还要看清 base hash 与 `workspace_revision`（0129）的**层级差异**：

| 机制 | 粒度 | 作用 |
|---|---|---|
| `workspace_revision` | **整个工作区**（或指定路径集） | 判断「环境是否还是我记下的那个」，用于回滚计划的前置校验 |
| base hash（write_store） | **单个文件** | 判断「这个文件是否还是我读到的那份」，用于单次写前的防覆盖 |

一个是环境级，一个是文件级——超压题 0149 会把两者与分片锁放在一起做完整分析。



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

### XEYO-QA-0132 ShadowGit 的定位与调用面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | shadow_git | 影子仓库封装 | 中等 | 机制解释 | `python/engine/shadow_git.py:8-94,133,143,166` |

**面试官提问**
`ShadowGit` 是什么？它封装了哪些方法？`init_if_needed()`、`head_commit()`、`diff_paths(old, new)`、`snapshot(...)` 各自做什么？为什么需要「影子」而不是直接用用户的工作区仓库？

**参考答案要点**
`shadow_git.py` 的接口面（实测）：

```python
class ShadowGitError(RuntimeError):        # :8
def decode_git_bytes(data: bytes) -> str     # :12
def _git_text_encodings() -> list[str]       # :29
class ShadowGit:                             # :54
    def __init__(self, workspace_root)       # :57
    def _run(self, args, check=True) -> CompletedProcess[str]        # :63
    def _run_bytes(self, args, check=True) -> CompletedProcess[bytes] # :81
    def init_if_needed(self) -> None          # :94
    def head_commit(self) -> Optional[str]    # :133
    def diff_paths(self, old_commit, new_commit) -> list[str]   # :143
    def snapshot(...)                         # :166
```

**方法职责**：

| 方法 | 职责 |
|---|---|
| `_run(args, check=True)` | 执行 git 命令，返回**文本**结果（`CompletedProcess[str]`）；`check` 控制非零返回是否抛错 |
| `_run_bytes(args, check=True)` | 同上但返回**字节**结果——用于路径名可能非法 UTF-8 的场景（对照 0115 的 `surrogateescape`） |
| `init_if_needed()` | **幂等**初始化影子仓库（已存在则跳过） |
| `head_commit()` | 取当前 HEAD 提交号，无提交时返回 `Optional` 的 `None` |
| `diff_paths(old, new)` | 给定两个提交，返回**变更路径列表** |
| `snapshot(...)` | 记录一次快照（产生新提交） |

`ShadowGitError(RuntimeError)` 是它的错误类型；`decode_git_bytes` / `_git_text_encodings()` 说明**输出解码是显式处理的**（git 输出的编码不一定是 UTF-8，尤其在 Windows 上）。

**为什么需要「影子」**：

1. **不污染用户仓库**：用户的工作区可能**本来就是 git 仓库**（甚至是一个大型 monorepo）。若直接用 `git add -A && git commit` 来记录快照，会：
   - 修改用户的 **HEAD/索引/分支**（改变用户的 git 状态）；
   - 把不该提交的文件（密钥、构建产物）卷进提交；
   - 与用户自己的 git 操作（rebase/checkout）冲突；
   - 违反「工作区只应有本功能在途改动」这条工程硬规矩。
   影子仓库是一个**独立的 git 目录**（通常在工作区之外或隐藏位置），对用户仓库**只读**（`status`/`diff`），写入只发生在影子库里；
2. **可丢弃**：影子库坏了可以直接删掉重建（`init_if_needed` 幂等），不影响用户数据；
3. **提供独立的对比基线**：`diff_paths(old, new)` 让引擎能算出「这两次快照之间哪些路径变了」——这是 rewind/回滚（B11 主题）与 `workspace_revision`（0129，用 `head_commit` 参与指纹）的共同基础。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的考点是「**为记录而记录的仓库必须与用户仓库解耦**」。注意 `WorkspaceRevision` 里同时用了 `ShadowGit` 的两个面（`workspace_revision.py:83-92`）：

```python
self.shadow_git.init_if_needed()
head = self.shadow_git.head_commit() or "empty"
...
status_result = self.shadow_git._run(["status", "--porcelain=v1", "--untracked-files=normal"], check=False)
```

即：`head_commit()` 提供「基线版本」，`_run(["status", ...])` 提供「当前变更集」——**读**影子库，**改**只发生在需要快照时。

`check=False` 与 `status_result.returncode == 0 else "<status-error>"` 的兜底（`workspace_revision.py:90-96`）也值得一提：git 命令失败（例如目录不是仓库、git 不可用）时，指纹**不抛异常**，而是把失败状态编码进 metadata（`<status-error>`）——保证「指纹永远能算出来」，因为调用方（回滚前置校验）需要的是一个**确定的字符串**，不是异常。



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

### XEYO-QA-0133 进程账本的回收与清扫

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | process_ledger | `reap` / `sweep` / 探针 | 中等 | 机制解释 | `python/engine/process_ledger.py:70-134,200,237,276-280` |

**面试官提问**
`ProcessLedger` 的 `reap(...)` 与 `sweep(...)` 有什么区别？`default_probe(entry)` 与 `default_cleanup(entry)` 的默认行为是什么？`count()` 与 `snapshot()` 分别给谁用？

**参考答案要点**
`process_ledger.py` 的相关面：

```python
def _pid_alive(pid: int) -> bool          # :70  —— PID 存活探测
def default_probe(entry: Entry) -> bool   # :82  —— 默认探针
def _terminate_pid(pid: int) -> bool      # :94  —— 终止进程
def default_cleanup(entry: Entry) -> bool # :116 —— 默认清理
class ProcessLedger:
    def reap(...)                          # :200
    def sweep(...)                         # :237
    def count(self) -> int                 # :276
    def snapshot(self) -> list[dict]       # :280
```

**`reap` 与 `sweep` 的区分**（二者名字都取自「收割/清扫」的隐喻）：

| 方法 | 语义（按命名与配套函数推断） | 作用对象 |
|---|---|---|
| `reap(...)` | **针对性回收**：对满足条件的条目做「探测 → 判定 → 终止/清理」，产出 `ReapReport`（`:50`，有 `__str__` 便于日志） | 通常是**指定 owner 或指定条件**的条目 |
| `sweep(...)` | **批量清扫**：遍历账本做一轮清理，处理「已死但仍在册」的残留 | 账本中**所有**符合过期/死亡条件的条目 |

两者都依赖底层的三个动作：`default_probe`（问「还活着吗」）、`_terminate_pid`（杀）、`default_cleanup`（收尾——例如删临时文件、注销登记）。

**`default_probe` 与 `default_cleanup` 的定位**：它们被命名为 `default_*`，说明**可被替换/注入**——`ProcessLedger` 的构造函数（`:137`）接受自定义探测与清理实现（测试里可以注入假的探针，不真的杀进程；不同 `Kind` 也可能需要不同探针）。默认实现在「探针」侧基于 `_pid_alive`（PID 存活），在「清理」侧基于 `_terminate_pid`。

**`count()` 与 `snapshot()`**：
- `count() -> int`：**数量**，用于快速判断「有没有残留」——例如状态上报、决定要不要触发 `sweep`；
- `snapshot() -> list[dict]`：**结构化快照**（可序列化），用于诊断/展示/上报。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于「**后台进程是资源泄漏的高发区**」。XEYO 里有大量长生命周期子进程（后台 bash job、sidecar llama、终端执行等——见 B05 主题），它们的共同风险是：

- 进程崩溃/被强杀时，**登记还在，进程已死**（幽灵条目）；
- 父进程退出时，**子进程还在跑**（孤儿进程继续占端口/文件/CPU）。

`ProcessLedger` 的定位就是给「引擎启动过哪些进程」留一份**可查、可清**的台账，而 `leftovers(owner=)`（`:357`，见 0116）正是「孤儿/残留」的一等查询入口。

`ReapReport` 有 `__str__`（`:57`）说明它会被**打进日志或回给用户**——「回收了 N 个，其中 M 个成功、K 个失败」这类结构化信息对排障很重要。



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

### XEYO-QA-0134 写入前的语法门禁

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | write_store | 语法检查与安全读取 | 中等 | 机制解释 | `python/engine/write_store.py:93-125,433` |

**面试官提问**
`_syntax_error_count(suffix, text)`、`_syntax_ok(path, new_content)`、`_read_text_safe(path)` 三个函数各自解决什么问题？`_compute_new_content(op, path)`（`:433`）在流程中处于什么位置？为什么语法检查是「门禁」而不是「自动修复」？

**参考答案要点**
`write_store.py` 的四个相关函数：

```python
def _syntax_error_count(suffix: str, text: str) -> int:   # :93
def _syntax_ok(path: Path, new_content: str) -> bool:     # :111
def _read_text_safe(path: Path) -> str:                   # :125
def _compute_new_content(op: EditOp, path: Path) -> str | None:   # :433
```

**三者解决的问题**：

| 函数 | 问题 |
|---|---|
| `_syntax_error_count(suffix, text)` | 按文件扩展名（`suffix`）选择解析器，**统计**文本里的语法错误数 |
| `_syntax_ok(path, new_content)` | 组合封装：判定「这个新内容对该路径是否语法合法」（返回布尔） |
| `_read_text_safe(path)` | **安全读文本**（处理编码/不存在/二进制等异常，保证读取不抛） |
| `_compute_new_content(op, path)` | 根据 `EditOp`（编辑操作）与当前文件内容，**算出新内容**；返回 `None` 表示「无法计算」（例如旧文本没匹配到、文件不可读） |

**`_compute_new_content` 的位置**：它在**流程的前段**——`_apply_core`（`:234`）先用它算出「打算写成什么」，然后再做语法检查（`_syntax_ok`）与基准哈希校验（`_lookup_base_hash`，见 0131），最后才走 `_atomic_write`（`:400`）。所以流程是：

```
EditOp + 磁盘当前内容
  → _read_text_safe / _compute_new_content   （算出新内容）
  → _syntax_ok                              （语法门禁）
  → _lookup_base_hash vs _content_hash(path)（并发门禁）
  → _atomic_write                            （落盘）
```

**为什么语法检查是「门禁」而不是「自动修复」**：

1. **修复需要语义判断**——引擎不知道用户想要什么，自动「修好」语法可能改变语义（例如把不完整的表达式补成合法的另一种含义）。这违反引擎铁律的「不做导演」；
2. **门禁保持可诊断**——拒绝写入时，模型的编辑**没有生效**，它拿到「语法不通过」的事实结果，可以自己重试。若引擎自动修复，模型会以为自己的编辑成功了（**事实被污染**）；
3. **只对可解析的语言生效**——`_syntax_error_count(suffix, ...)` 按**扩展名**分派，说明检查是「对已知语言用对应解析器」；未知扩展名（纯文本、配置、markdown）无法做语法判定，此时门禁自然不适用（不能因为「检查不了」就拒绝一切写入）；
4. **它是「执行层限制」的正确形态**——按 XEYO 的理念，引擎的限制只在**执行层**表达（拒绝 + 中性结果措辞），而不是往注意力里写「你写的代码有语法错误，请修复」。

**深化讲解**（面试官参考，不要求候选人全说）
这道题把「写路径的完整防线」串了起来：

| 防线 | 机制 | 防什么 |
|---|---|---|
| 内容计算 | `_read_text_safe` + `_compute_new_content` | 编码异常、旧文本不匹配 |
| 语法 | `_syntax_ok` | 写出语法非法的文件（对已知语言） |
| 并发 | `_lookup_base_hash` | 覆盖他人并发修改（见 0131） |
| 原子性 | `_atomic_write`（`:400`） | 写到一半进程死 → 半个文件 |
| 展示预算 | `_make_unified_diff` + `_MAX_DIFF_LINES = 400`（`:137,140`） | diff 过大撑爆上下文 |

再加 `_note_presence_write(path, session_id)`（`:352`）——写操作会**登记到会话存在感**（用于「其他会话活动/文件冲突」类 T_now 通知，见 B02 的 `_notify_peers_after_allow` 一族）。也就是说：一次写入不只是改文件，还会**产生可被其他会话观察到的事实**。



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

### XEYO-QA-0135 为什么「能删但找不回」就必须默认关

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | aging × repeat_fold | 默认值方向由可逆性决定 | 困难 | 场景设计 | `python/engine/aging.py:1-13,40-52`；`python/engine/repeat_fold.py:11-12,68-70` |

**面试官提问**
（1）`aging`（输出老化）默认**关**，`repeat_fold`（结果折叠）默认**开**。请从「可逆性」角度解释这个差异。
（2）如果为了让长会话「更省 token」而把 `XEYO_TOOL_AGING` 默认打开，会出现什么具体问题？
（3）模块 docstring 提到「与**证据先行（T1/T27 spill）**方向冲突」——请说明这里的冲突是什么。

**参考答案要点**
**（1）可逆性决定默认值方向**

| 机制 | 默认 | 内容是否可找回 | 依据 |
|---|---|---|---|
| `repeat_fold` 折叠 | **开** | **可找回**：docstring 原文「首次完整输出**仍在历史前部，信息无损**」（`repeat_fold.py:11-12`） | 折叠只裁「与上次完全相同、无新增信息」的那一份，原文仍有一条在历史里 |
| `aging` 老化 | **关** | **找不回**：docstring 原文「toolout 占位的恢复机制落地前保持关闭，**避免原文不可找回**」（`aging.py:4-5`）；`aging_enabled` 又写「老化即『**原文从投影消失且无处找回**』」（`aging.py:43-44`） | 老化把内容**从投影里去掉**，且没有落地文件级恢复机制 |

规则可以概括为：**「信息无损」→ 默认开（省预算是纯收益）；「信息有损」→ 默认关（省预算的收益不足以抵消不可逆风险）**。

注意这两者的开关形式也与此一致：折叠是 opt-out（`!= "0"`，见 0126），老化是 opt-in（`in ("1","true","on","yes")`，见 0103）。**默认值与开关形式是同一决策的两面**。

**（2）默认打开老化会出现的具体问题**：

1. **不可逆的信息丢失**：表现为把工具输出替换为 `[elided <tool> <id8>: <摘要≤60>] (archived; answer from remaining context)`。摘要只有 60 字符（`STUB_SUMMARY_MAX`），一个 200 行的文件内容、一段完整报错堆栈、一份 JSON 结构**都只剩一行描述**；
2. **无法恢复**：没有「按 id 取回原文」的通道（spill/toolout 恢复机制未落地）。被老化的内容在后续所有投影里都是存根——即使回滚到更早的消息也不行（投影重算仍会老化）；
3. **错误被保留、上下文被删——保真方向反而搞反**：`should_exempt(is_error=True, ...)` 会豁免错误结果（见 0105），所以「错误原文留着、正常输出被删」——这在排查型任务里是最坏的组合（需要看的是正常输出里的细节）；
4. **与 `Screenshot`/图像类结果冲突**：这类结果的结构性内容（如 `XeyoUI` dock、图像引用）一旦被摘要化，UI 侧渲染会失去数据源。

**（3）与「证据先行（T1/T27 spill）」的冲突**：

「证据先行」的口径是：**先把原始证据完整保存下来（spill 落盘），再讨论要不要把它显示给模型**。它承认「上下文有限」这个约束，但解法是**把原文存到别处**，而不是**丢掉**。

老化的做法正相反：**直接从投影里删除**。在没有「spill 落盘 + 按 id 取回」这条路径之前，老化等于「**只有删除、没有归档**」。两者对同一个约束（上下文预算）给出了方向相反的解法：

| | 证据先行 / spill | 老化（恢复机制缺失时） |
|---|---|---|
| 手段 | 原文落盘，投影里放引用/占位 | 原文从投影消失 |
| 可恢复 | ✅ 按 id/digest 取回 | ❌ 无处可取 |
| 代价 | 磁盘占用 | 信息永久丢失 |

所以「等恢复机制落地再默认开」是一个**顺序约束**：**先具备恢复能力，再启用删除能力**。

**深化讲解**（面试官参考，不要求候选人全说）
这题把「默认值」从一个配置问题提升成**架构顺序问题**。三处源码口径完全一致（模块 docstring、函数 docstring、默认值字面量），说明这不是随手设的默认，而是经过审查的决定。

顺带一个验证方式：如果想确认「老化真的不可逆」，可以查两个地方——① 是否有「按 digest 从磁盘取回原始工具输出」的接口；② `logs/toolout` 文件级恢复是否已实现。模块 docstring 明确写「**logs/toolout 文件级恢复为后续增强（见设计文档前置依赖①）**」——即尚未实现。



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

### XEYO-QA-0136 存根为什么不能写「请重跑这个工具」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | aging | 恢复语义与措辞纪律 | 困难 | 场景设计 | `python/engine/aging.py:10-12,80-90` |

**面试官提问**
`aging.py` 的 docstring 写：

> 恢复语义（v1）：所有被老化工具均可重跑再生；但存根本身保持**中性措辞**（"answer from remaining context"），**不主动劝导重跑**，避免 harness **诱发重复检索**。

（1）存根的措辞是什么？为什么「不主动劝导重跑」是必要的——如果写成「该内容已老化，请重新运行此工具获取」，会发生什么？
（2）这里提到的「harness 诱发重复检索」在 XEYO 里与哪些既有机制相互放大？（提示：结合 B02 的重复守卫与 B03 的折叠）
（3）这个决定体现了哪条引擎铁律？

**参考答案要点**
**（1）措辞与风险**

存根文本（`aging.py:88-90`）：

```python
uid8 = (use_id or "")[-8:]
s = sanitize_summary(summary)
return f"[elided {tool_name} {uid8}: {s}] (archived; answer from remaining context)"
```

尾部的 `(archived; answer from remaining context)` 是**中性陈述**：告知「内容已归档」并指出「（请）从剩余上下文作答」——注意它说的是**从已有上下文回答**，而不是「去重新获取」。

**如果写成「请重新运行此工具获取」会发生什么**：

1. **模型可见文本变成了指令**——它不再是「事实」，而是**行为指引**。这直接违反引擎铁律第 1 条（模型可见文本只承载状态/结果/事实，禁止建议与编排）；
2. **循环放大**：老化本身是「为了控上下文而删内容」的动作。如果存根**要求**模型重跑，那么模型重跑 → 新输出又占上下文 → 再次触发老化 → 又要求重跑。**删与取形成闭环**，上下文预算不但没省，反而因为每次重跑都产生新输出+新存根而**增加**；
3. **与重复守卫冲突**：重跑同一工具会命中 `RepeatCallGuard`（阈值 3/5/8，见 B02-0061），引擎随后注入「你在重复」的提示。于是模型同时收到「请重跑」（存根）与「你在重复」（守卫）——**两条互相矛盾的注意力输入**，模型无从判断该听谁的；
4. **与折叠叠加**：若重跑的输出与既往某次**逐字节相同**，`IdenticalResultFold` 会把它折叠成 `[fold] ...`（见 0113）。模型**既拿不到原文**（老化删了）、**也拿不到重跑结果**（折叠了）——它被彻底剥夺了获取信息的路径，只能空转。

（2）**放大链条**总结：

```
老化存根（若含"请重跑"指令）
  → 模型重跑
    → 命中 RepeatCallGuard → 注入"重复"提示（与存根矛盾）
    → 输出与既往相同 → 命中 IdenticalResultFold → 折叠（拿不到内容）
    → 输出占上下文 → 触发新一轮 aging（再次老化）
```

三套「省上下文」机制（老化 / 重复守卫 / 折叠）各自都是合理的，但**一旦存根变成指令，它们就从「各自省预算」变成「互相锁死」**。

（3）**体现的铁律**：第 1 条「**注意力里只出现信息，不出现导演**」。

具体到这条措辞：引擎可以做的是**把事实说清楚**（「已归档」+「从剩余上下文作答」）；引擎**不能**做的是**指挥模型的行为**（「去重跑吧」）。注意二者差别看似细微，但后果是结构性的——前者把选择权留给模型（它可以重跑、可以换个工具、可以基于摘要作答、也可以直接说「我不知道」），后者把选择权拿走了。

**深化讲解**（面试官参考，不要求候选人全说）
这题的价值在于「**一个字面差异带来的系统性后果**」。实现者显然意识到了这点——docstring 特意用「**避免 harness 诱发重复检索**」点出动机，用词是「**harness**」（脚手架/测试装置），说明这个风险在自动化评测场景下尤其明显（评测里模型会反复尝试，很容易陷入重跑循环，导致 token 爆掉、超时失败）。

这也给出一条判据：**当一段模型可见文本描述了一个「可以采取的动作」时，要问「这是陈述事实，还是在暗示行动？」**——如果是后者，就要重新设计措辞。



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

### XEYO-QA-0137 收尾窗广播只改变「怎么做」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | wrap_window × tools | 执行层路由信号 | 困难 | 场景设计 | `python/engine/wrap_window.py:1-15,45-63` |

**面试官提问**
（1）`wrap_window.py` 的 docstring 明确「**不设置在权限或策略层——它不改变『能不能做』，只改变『怎么做』**」。请解释这两个层次的区别，并说明如果把收尾窗状态塞进权限层会发生什么。
（2）docstring 说「工具层据此做的也只是**路由决策**（立即后台化），不产生给模型的劝告文本」。请说明「立即后台化」为什么是一个合适的执行层动作。
（3）「未武装墙钟 / 未进入收尾窗时 `in_wrap_window()` 恒 False」这条性质有什么工程价值？

**参考答案要点**
**（1）「能不能做」vs「怎么做」**

| 层次 | 问题 | 对应机制 | 例子 |
|---|---|---|---|
| 能力/权限层 | **能不能做**（是否允许） | `permissions/policy.py` 的 allow/ask/deny | 「读工作区外的文件」被 DENY |
| 执行层 | **怎么做**（用什么方式做） | `wrap_window`、`tools/container_routing`、`permissions/write_scope`（docstring 明确把三者并列） | 「这条长命令**立即后台化**」 |

**如果把收尾窗塞进权限层会怎样**：

1. **语义升格错误**：一个「预算快用完了」的**时间约束**会变成「这个工具被禁止」的**权限约束**。后果是：收尾窗内某些工具直接 DENY，模型收到的 `Permission denied: ...` 与权限系统的其它 DENY **无法区分**——模型（和用户）会以为是自己没被授权，而不是「时间不够了」；
2. **审计污染**：权限 DENY 会被审计记录，混进「越权尝试」的统计里，让安全审计产生**假阳性**；
3. **不可逆的观感**：权限类是「配置/预设」决定的，用户看到 DENY 会去改权限设置——但问题根源在预算，改权限也没用；
4. **违反「限制只在执行层表达」**：铁律第 3 条要求限制**以中性结果措辞在执行层表达**，而不是通过改变权限模型来达成。

**（2）为什么「立即后台化」是合适的执行层动作**

背景：收尾窗的稀缺资源是**剩余墙钟**（`remaining_s`）。一条长命令（构建、测试、长 bash）如果**前台同步等待**，会吃掉整个收尾窗，导致「本来该用来落盘的时间被一条命令占完」。

「立即后台化」的语义是：**不改这条命令能否执行（仍然执行），只改它的等待方式（不再阻塞收尾窗）**。这样：

- **模型仍能发起这条命令**（能力不变）；
- **收尾窗的时间不被独占**（约束被遵守）；
- **模型可见文本没有任何新增**（没有「由于时间不够，我已改为后台执行」这类劝告）——docstring 原文「工具层据此做的也只是**路由决策**，不产生给模型的劝告文本」；
- 模型的后续行为由**工具结果本身**（后台 job 的 id/状态）驱动，而不是被引擎的话术推动。

这正是铁律第 3 条的范本：**限制存在（时间紧），但只在执行层表达（改成后台），且措辞中性（只有工具结果）**。

**（3）「恒 False」的工程价值**

docstring 原文：「**与 `tools/container_routing`、`permissions.write_scope` 同构：不设置时一切路径与旧行为字节级等价**」。

价值有三：

1. **零回归**：未启用该机制的代码路径与改之前**逐字节相同**——这样引入这个机制不会给现有测试/现有行为带来任何变化，可以安全合入；
2. **可观测的开关边界**：`in_wrap_window()` 恒 False 意味着「工具层走原路径」，出问题时可以立刻判断「是不是收尾窗机制引起的」；
3. **不依赖初始化**：`_SLOT` 的 `default` 是 `_INACTIVE`——**即使完全没人调用 `set_wrap_window`，读取也永远安全**（不会抛 KeyError / 不会得到 None）。这是 ContextVar 相对「显式传参」的优势：**默认值让「没设置」成为一个合法状态**。

**深化讲解**（面试官参考，不要求候选人全说）
这题把三个看似不同的机制（`wrap_window` / `container_routing` / `write_scope`）串在一条线上——docstring 明确说它们「**同构**」。共同特征：

| 特征 | 说明 |
|---|---|
| 传播手段 | `ContextVar`（异步任务隔离） |
| 语义定位 | **执行层**路由，不涉能力/权限 |
| 默认值 | 未设置 = 旧行为（字节级等价） |
| 模型可见性 | 不产生劝告文本 |

这实际上定义了一个**「执行层信号」的设计模式**：用它承载「环境状态」，让工具层在自己的实现里做适配，而不是把状态变成对模型的指令。



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

### XEYO-QA-0138 修订号计算的确定性设计

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_revision | 哈希输入的构造 | 困难 | 代码阅读 | `python/engine/workspace_revision.py:36-45,76-109` |

**面试官提问**
阅读下面代码，回答四个问题：① 为什么 `metadata.sort()` 必须在哈希之前？② 为什么要对每个 token 都追加 `b"\0"` 分隔符？③ `normalize_paths` 做了哪些归一化、为什么每一处都必要？④ 如果一个路径在 `paths` 参数里出现两次，指纹会变吗？

```python
@staticmethod
def normalize_paths(paths: Iterable[str] | None) -> tuple[str, ...]:
    if paths is None:
        return ()
    seen: list[str] = []
    for raw in paths:
        text = str(raw or "").replace("\\", "/").strip().lstrip("./")
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)

# ...（calculate 中）
    metadata.sort()

    hasher = hashlib.sha256()
    hasher.update(head.encode("utf-8"))
    hasher.update(b"\0")
    for token in metadata:
        hasher.update(token.encode("utf-8", errors="surrogateescape"))
        hasher.update(b"\0")
    return f"rev_{hasher.hexdigest()[:16]}"
```

**参考答案要点**
**① 为什么必须 `metadata.sort()`**：
因为 `metadata` 的**产生顺序不确定**。在 `paths=None` 分支里，它来自 `git status --porcelain` 的输出——git 的输出顺序**不是契约**（受目录遍历顺序、文件系统实现、索引状态影响）；在 `paths=[...]` 分支里，它来自调用方给的列表顺序。

哈希是**顺序敏感**的：同样的文件集合，若枚举顺序不同，`sha256` 结果完全不同。排序把「集合」规范化成「唯一确定的序列」，**保证指纹只反映内容而不反映枚举顺序**。没有这一步，同一工作区在不同机器/不同时刻可能算出不同修订号 → 乐观校验随机失败。

**② 为什么每个 token 后都要 `b"\0"`**：
防**哈希拼接歧义（length-extension / boundary ambiguity）**。分段哈希时，如果不加分隔符，`["ab", "c"]` 与 `["a", "bc"]` 会喂入完全相同的字节流 `abc`——**两种不同的状态得到同一个指纹**，导致真实的差异被漏判。

用 NUL 分隔后，前者是 `ab\0c\0`，后者是 `a\0bc\0`，可区分。选 `\0` 而不是换行/逗号，是因为 **NUL 不可能出现在路径与 stat 字段里**（它是字符串终止符），所以不会与内容本身产生歧义。

同样的手法在 `head` 与第一个 token 之间也用了（`hasher.update(head.encode())` 后紧跟 `b"\0"`）——保证「HEAD 值的尾部」与「第一个 token 的开头」不会粘连。

**③ `normalize_paths` 的四处归一化及其必要性**：

```python
text = str(raw or "").replace("\\", "/").strip().lstrip("./")
if text and text not in seen:
    seen.append(text)
```

| 操作 | 必要性 |
|---|---|
| `str(raw or "")` | 容忍 `None` 元素（`raw or ""` → 空串，随后被 `if text` 过滤） |
| `.replace("\\", "/")` | **Windows 路径分隔符统一**：`src\a.py` 与 `src/a.py` 是同一个文件，不统一会算出两个指纹 |
| `.strip()` | 去首尾空白（防止从配置文件/命令行读入时带空格） |
| `.lstrip("./")` | 去前导 `./`（`./a.py` 与 `a.py` 同义） |
| `if text` | 过滤归一化后变空的项（`""`、`"."`、`"./"`） |
| `text not in seen` | **去重** |

**④ 重复路径会不会改变指纹**：**不会**。因为 `if text not in seen` 做了去重——`["a.py", "a.py"]` 与 `["a.py"]` 得到同一个 `metadata` 列表。

这个性质很重要：调用方（例如从模型的编辑列表、从 git 变更集）很容易产生重复路径，如果去重缺失，**同一份工作状态会因调用方传入的冗余而算出不同指纹**。

**深化讲解**（面试官参考，不要求候选人全说）
这题集中训练「**哈希输入必须规范化**」这个通用技能。三道防线缺一不可：

| 防线 | 防的问题 |
|---|---|
| 排序 | 顺序无关性（枚举顺序不可控） |
| 分隔符 | 边界歧义（不同集合 → 同样字节流） |
| 去重 + 路径归一化 | 输入表示差异（同一路径的多种写法） |

顺带注意 `errors="surrogateescape"`（在 hash 循环里）：与 0115 的解释一致——**文件名可能是任意字节序列**（只在 Windows 上存在，但必须要处理），用 `surrogateescape` 保证编码**永不失败**且**可逆**。若用默认的 `strict`，一个非法 UTF-8 的文件名会让整个 `calculate()` 抛 `UnicodeEncodeError`——而它的调用方（回滚前置校验）需要一个确定的结果。



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

### XEYO-QA-0139 工作区租约的 stale 判定与回收

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_lock | 租约文件 + 心跳文件 | 困难 | 场景设计 | `python/engine/workspace_lock.py:14-38,72-141,192-217` |

**面试官提问**
`WorkspaceLock` 通过「租约文件 + 心跳文件」实现跨进程的工作区互斥。请回答：

（1）从源码的函数面看，`_read_lease()`、`_heartbeat_path()`、`_lock_file_is_stale()`、`_reclaim_stale()`、`_create_lease()` 大致构成一条什么链？
（2）`_start_heartbeat()` / `_heartbeat_loop(stop)` 说明心跳是**独立线程/定时循环**实现的。这与 B02-0099 里 `turn_runner` 的「消费帧时顺带续期」有什么本质差异？
（3）`LeaseBusyError` 与 `LeaseError` 的继承关系说明什么？`reclaim_stale_if_expired()` 对外暴露的意义是什么？
（4）请指出本批**未逐行核对**的部分（需标注待确认）。

**参考答案要点**
**（1）从函数面推断的链路**（`workspace_lock.py`，实测行号）：

```
acquire(blocking=False, timeout=0.0)          # :217
  ├─ _read_lease()                            # :75   读现有租约
  │    └─ _lock_file_is_stale()               # :109  判断「这个租约是不是过期了」
  │         └─ _heartbeat_path(lease_id)      # :72   心跳文件（按 lease_id 定位）
  │         └─ _reclaim_stale(lease)          # :117  回收过期租约
  └─ _create_lease(lease)                     # :141  创建新租约
       └─ _start_heartbeat()                  # :192  启动心跳
            └─ _heartbeat_loop(stop: Event)   # :200  心跳循环
```

即：**获取时先读现有租约 → 用心跳文件的时效判断它是否已死 → 死则回收 → 创建自己的租约 → 启动心跳维持它**。

`reclaim_stale_if_expired()`（`:209`）是一个**对外暴露的显式回收入口**（不只是 acquire 内部调用），说明「主动清理过期租约」可以独立触发。

**（2）与 `turn_runner` 心跳的本质差异**

| | `turn_runner.touch_busy`（B02-0099） | `WorkspaceLock._heartbeat_loop` |
|---|---|---|
| 实现 | 在**消费事件帧的循环里**顺带判断 `now - last_touch >= 30.0` | **独立的循环**（参数是 `stop: Event`，即有自己的停止信号） |
| 心跳源 | **数据流**（有帧才检查） | **时间**（与数据流无关） |
| 隐含前提 | 「长回合必然持续产帧」——静默期会停 | 无此前提 |
| 风险 | 长时间无帧 → 心跳停 → 被误判 stale（这是 B02-0099 的根因） | 无（只要线程/循环活着就续期） |

**本质差异**：`WorkspaceLock` 的心跳是**条件无关的时间驱动**，而 `turn_runner` 的心跳是**数据驱动的副产品**。前者不会因为业务静默而停，后者会。这也从侧面印证 B02-0099 给出的加固方案（改成独立时间驱动）是**本仓库已有的成熟范式**——同一个仓库里两种心跳实现并存，`WorkspaceLock` 那种才是正确的。

（注意：`_heartbeat_loop` 的具体节拍是**待确认**——本批未逐行读该函数体，因此跳过了「心跳快多少倍于 stale 阈值」这类细节。）

**（3）异常继承与显式回收**

```python
class LeaseError(RuntimeError):        # :14
class LeaseBusyError(LeaseError):      # :18
```

`LeaseBusyError` 继承 `LeaseError`，语义分层清晰：
- **`LeaseError`** = 「租约操作出了问题」的**总类**（捕获它可兜住所有租约异常）；
- **`LeaseBusyError`** = 「**已被占用**」这个**特定原因**。调用方可以精确捕获它，走「等待/提示用户/放弃」的分支，而不是把「忙」与「IO 错误/路径错误」混在一起处理。

这与 B02-0052 的 `RuntimeError("engine is busy: ...")` 是同一思路的不同实现（那里靠**消息文案**里的 `busy` 让上层的 `friendly_error` 翻译；这里靠**类型**区分）——都为了让上层能区分「忙」与其他失败。

`reclaim_stale_if_expired()` 对外暴露的意义：**「回收」是一个可能需要主动触发的动作**。例如：上一个进程崩溃时留下了租约文件，新进程启动后应该主动清理（而不是等下一次 `acquire` 碰巧触发）；或者提供诊断/运维入口（「工作区被锁住了，帮我看看是谁」）。

**（4）待确认项**（必须显式说明）：
- `_heartbeat_loop` 的**节拍值**与 `_lock_file_is_stale` 的**过期阈值**（本批未逐行读）；
- 租约文件与心跳文件的**具体路径与格式**（`_lease_path`/`_heartbeat_path` 的落点）；
- 是否使用**文件锁**（`fcntl`/`msvcrt`）还是纯「文件存在 + 时间戳」判定——这决定了「两个进程同时 acquire」的竞态处理方式。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的关键是**从「函数名 + 参数类型」恢复设计意图**，并**明确区分「已核对」与「未核对」**。这种能力在审计里非常重要：不能因为「看起来合理」就把推断当事实（B02-0099 也做了同样的标注）。

一个值得注意的设计信号：`_heartbeat_path(lease_id)` 是**按 lease_id 定位**的——说明心跳文件与租约一一对应。这是实现「谁能回收谁」的关键：回收时要知道「这个租约的心跳文件在哪儿、多久没更新了」。



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

### XEYO-QA-0140 租约的四阶段生命周期

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_lock | acquire / renew / release / hold | 困难 | 机制解释 | `python/engine/workspace_lock.py:217,265,286,320` |

**面试官提问**
`WorkspaceLock` 提供 `acquire(*, blocking=False, timeout=0.0)`、`renew()`、`release()`、`hold(*, blocking=False, timeout=0.0)`（后者是 `@contextmanager`）。请说明：① 四个方法在生命周期中的位置与返回值；② `blocking`/`timeout` 两个参数的组合语义；③ 为什么还要提供 `hold()`——它与手写 `acquire` + `try/finally: release` 相比的价值是什么？

**参考答案要点**
**① 生命周期位置**

| 阶段 | 方法 | 返回 |
|---|---|---|
| 获取 | `acquire(*, blocking=False, timeout=0.0)`（`:217`） | `Lease` 对象（`:23`，含 `lease_id` 等信息） |
| 维持 | `renew()`（`:265`） | 新的/更新后的 `Lease` |
| 释放 | `release()`（`:286`） | 无返回值（清理租约文件与心跳） |
| 组合 | `hold(...)`（`:320`，`Iterator[Lease]` 的 contextmanager） | 进入时 `acquire`，退出时 `release` |

`WorkspaceLock.__init__`（`:38`）接受工作区参数；`_heartbeat_path(lease_id)`（`:72`）说明每次持有租约都有心跳文件。

**② `blocking` 与 `timeout` 的组合语义**（按签名 `blocking: bool = False, timeout: float = 0.0` 与 `LeaseBusyError` 的存在推断）：

| `blocking` | `timeout` | 预期行为 |
|---|---|---|
| `False`（默认） | 忽略（0.0） | **不等待**：若已被占用，**立即**抛 `LeaseBusyError` |
| `True` | `0.0` | **无限等待**直到拿到（或调用方取消）——`timeout=0.0` 在此语境下表示「不限时」，而不是「零超时」 |
| `True` | `> 0` | **最多等 `timeout` 秒**，超时抛 `LeaseBusyError` |

关键点是**默认不等待**（`blocking=False`）：这是一个**fail-fast** 的默认值——调用方如果没想清楚要不要等，宁可立刻得到「忙」的错误，也不要静默挂住。这与 B02 里 `TurnRunner.start` 遇到已有 turn 就抛 `RuntimeError` 是同一取向。

（**待确认**：`timeout=0.0` 在 `blocking=True` 时究竟解释为「无限」还是「立即超时」，本批未逐行核对 `acquire` 函数体，故上述组合语义中该格标注为**推断**。）

**③ `hold()` 的价值**

手写版本是：

```python
lease = lock.acquire()
try:
    ...
finally:
    lock.release()
```

`hold()` 把这个模式封装成 contextmanager，带来三点：

1. **异常安全不会漏**：`finally: release()` 是最容易被漏写的一行（尤其在异常路径、提前 `return`、`continue` 的地方）。用 `with` 语法，Python 保证退出时执行 `__exit__`；
2. **参数透传一致**：`hold(blocking=..., timeout=...)` 与 `acquire` 参数一致，调用方不必写两套参数处理；
3. **语义自解释**：`with lock.hold():` 直接表达「这一段处于租约保护下」，比「acquire 之后若干行之后 release」更易读——尤其当中间有几百行代码时。

反面风险（用 `hold` 的代价）：**作用域变长**。租约持有时间等于 `with` 块的执行时间，若块内有耗时操作（等网络、等用户输入），租约会被长期占用——而租约的意义是「保护工作区」，长时间持有会阻塞其他会话。所以 `hold()` 的正确用法是**尽量小的临界区**，而不是「把整个回合包起来」。

**深化讲解**（面试官参考，不要求候选人全说）
这题的三层考点：① **四阶段生命周期**（获取/维持/释放/组合）；② **默认 fail-fast**（`blocking=False`）这一保守方向；③ **contextmanager 的价值与风险**（异常安全 vs 作用域膨胀）。

一个容易忽略的细节：`renew()` **有返回值**（`Lease`）。这与 `turn_runner` 的 `touch_busy`（无返回）不同——说明 `renew` 可能更新租约的**版本/代数**（例如每次续期递增一个计数），返回值让调用方拿到最新状态。是否会因为「长时间不续期」而失效，取决于 `renew` 与心跳的配合（`_heartbeat_loop` 自动续期，见 0139），因此 `renew()` 的**显式调用场景**是「心跳不可用/需要立即确认仍持有」的情况。



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

### XEYO-QA-0141 原子写与「先校验后落盘」的顺序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | write_store | `_atomic_write` 与前置校验 | 困难 | 场景设计 | `python/engine/write_store.py:93-125,234-337,400` |

**面试官提问**
（1）`_atomic_write(path, content, encoding="utf-8")`（`:400`）为什么必须是「原子」的？非原子写会带来什么具体故障？
（2）为什么语法检查（`_syntax_ok`）要在**写入之前**做，而不是写完之后检查、发现错误再回滚？
（3）请说明 `_apply_core`（`:234`）的整体顺序：从拿到 `ChangeIntent` 到落盘，中间经过哪些门禁、为什么是这个顺序。

**参考答案要点**
**（1）为什么必须原子写**

`_atomic_write` 的命名表明它采用**「写临时文件 + rename」**类实现（rename 在同文件系统内是原子操作）。非原子写（直接 `open(path, "w")` 然后 `write`）的危险在于**写入过程是可见的中间态**：

| 故障 | 具体表现 |
|---|---|
| **进程在写一半时死掉** | 磁盘上是**半个文件**——语法不完整、内容截断。用户拿到一个坏文件，且原内容已被 `"w"` 模式**截断**（不可恢复） |
| **并发读者看到中间态** | 另一个会话/监视工具（Vite、tsc、格式化器）在写入过程中读文件，会读到不完整内容并据此产生**错误的派生结果**（例如编译报错、把坏内容再次写回） |
| **磁盘满/IO 错误** | `write` 中途失败，文件已被截断——**原始内容丢失且新内容不完整**（双重损失） |

原子写把「内容替换」变成**一次性的目录项替换**：要么新内容完整可见，要么完全看不到（读到的仍是旧内容）。中间态在文件系统层面不存在。

**（2）为什么语法检查必须在写入之前**

如果改成「先写、后检查、错了再回滚」：

1. **回滚本身可能失败**：回滚要恢复旧内容，需要先把旧内容**保存下来**（额外的备份机制）；若回滚时进程崩溃或磁盘满，工作区就停在**坏状态**——比「根本没写」严重得多；
2. **中间态会被外部观察到**：即使最终回滚成功，在「写坏」到「回滚」的时间窗内，Vite/tsc/其它会话可能已经读了坏文件并产生了派生效果（缓存、报错、甚至写回）；
3. **「先检查」是零成本的**：`_syntax_error_count` 只用解析器分析字符串，**不触碰磁盘**——没有理由把它放到有副作用的动作之后。工程上的通则是：**能在纯计算阶段否决的，就不要走到 IO 阶段**；
4. **错误语义不同**：写前拒绝 → 模型收到「编辑未生效」的确定结果，可以重试；写后回滚 → 模型可能已经收到「成功」的中间信号（若事件流在写与检查之间推送了结果），造成**事实污染**。

**（3）`_apply_core` 的门禁顺序**（按 0134 已梳理的链条）：

```
ChangeIntent
  ├─ _canon(path)                                    # :198  路径规范化（工作区边界）
  ├─ _read_text_safe(path)                           # :125  安全读当前内容
  ├─ _compute_new_content(op, path)                  # :433  算出新内容（None = 无法计算）
  ├─ _syntax_ok(path, new_content)                   # :111  语法门禁（纯计算）
  ├─ _lookup_base_hash(intent, path)                 # :389  基准哈希
  │    vs _content_hash(path)                        # :71   与磁盘现状比对（并发门禁）
  ├─ _atomic_write(path, content, encoding)          # :400  原子落盘
  ├─ _note_presence_write(path, session_id)          # :352  登记「本次写」到会话存在感
  └─ _make_unified_diff(path, before, after)         # :140  生成 diff（≤400 行）
```

**为什么是这个顺序**：**代价递增 + 副作用递增**。

| 阶段 | 成本 | 副作用 |
|---|---|---|
| 路径规范化 / 读内容 / 算新内容 | 极低（内存） | 无（读盘无副作用） |
| 语法检查 | 低（解析） | 无 |
| 基准哈希比对 | 低（读盘 + 哈希） | 无 |
| 原子写 | 中（磁盘写） | **有**（改工作区） |
| 存在感登记 / diff | 低 | 有（改状态、占上下文） |

把「无副作用且便宜」的检查全部前置，让**副作用发生在所有否决点之后**——这样任何失败都发生在「工作区未被改动」的状态下，不需要回滚。这也解释了为什么 `_note_presence_write`（登记存在感）在写**之后**：只有真的改了文件，才应该通知其他会话「这里有变更」。

**深化讲解**（面试官参考，不要求候选人全说）
这题可以概括成一句话：**「原子性 + 前置校验」的组合，让失败模式从『可能留下坏状态，需要回滚』变成『什么都没发生，直接重试』**。前者需要补偿逻辑（复杂、易错、可能二次失败），后者不需要。

对照 `workspace_restore.py`（0143）——那里的操作**无法原子完成**（要跨多个文件恢复），所以它**必须**有 WAL + trash + 回滚机制。两个模块的复杂度差异，正来自「能否把操作做成只有一个提交点」：

| 模块 | 操作 | 能否单一提交点 | 需要的补偿机制 |
|---|---|---|---|
| `write_store` | 单文件替换 | ✅ 能（rename） | 无（前置校验即可） |
| `workspace_restore` | 跨多文件恢复 | ❌ 不能 | WAL + trash + `_rollback_to_safety` |



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

### XEYO-QA-0142 多文件变更的一致性问题

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | write_store | `_apply_multi` | 困难 | 场景设计 | `python/engine/write_store.py:31-70,234,364` |

**面试官提问**
一个 `ChangeIntent` 可以包含多个 `EditOp`，由 `_apply_multi(intent)`（`:364`）处理，而单文件路径走 `_apply_core(intent, path)`（`:234`）。

（1）多文件变更引入的核心风险是什么？请举一个具体的 XEYO 场景。
（2）从 `_apply_multi` 的命名与 `_apply_core` 的存在，能推断出它的实现形态有哪几种可能？各自的代价是什么？
（3）`workspace_restore.py` 用了 WAL（`:60-89`）来解决同类问题，`write_store` 为什么**没有**引入 WAL？（提示：结合 0141 与 0143）

**参考答案要点**
**（1）多文件变更的核心风险：部分成功（partial failure）**

单文件写是「一个提交点」；多文件写是「N 个提交点」——进程可能在**第 k 个写完、第 k+1 个没写**的时刻死掉，留下**自相矛盾的工作区**。

**具体 XEYO 场景**：模型重构把一个函数从 `utils.py` 移到 `helpers.py`，这是一次语义上的原子变更，但物理上涉及两个文件：

```python
ChangeIntent(ops=[
    EditOp(创建 helpers.py，含新函数),
    EditOp(从 utils.py 删除该函数),
    EditOp(在 main.py 改 import),
])
```

若在「已创建 helpers.py、还没改 main.py」时中断：

- 工作区里 `main.py` 仍 `from utils import f`（但 `utils.f` 已删除）→ **import 报错，项目跑不起来**；
- 更隐蔽的情况：`utils.py` 里删了、`helpers.py` 里也还没写 → **函数彻底消失**（连回退都不容易）。

**（2）`_apply_multi` 的三种可能实现形态与代价**

| 形态 | 做法 | 一致性 | 代价 |
|---|---|---|---|
| **顺序应用 + 失败即停** | 逐个 `_apply_core`；某个失败 → 停止，报告已完成的部分 | **弱**（可能部分成功） | 低（无额外机制）；调用方需自行处理不一致 |
| **先全量校验，再逐个应用** | 先对**所有** op 做「语法 + base hash」预检（都是无副作用阶段，见 0141）；全部通过才开始写 | **中**（消除了"因校验失败而中断"这一类；但进程崩溃仍可能留下一半） | 低-中（一轮额外校验）；这是**最可能的实现**，因为校验阶段本来就无副作用，可以自然前置 |
| **预写 + 原子提交 / 事务** | 把新内容写临时文件，全部就绪后一次性 rename；或写 WAL 支持回滚 | **强** | 高（跨目录 rename 不原子、需 WAL/恢复逻辑） |

从 `_apply_multi` 只是 `WriteStore` 的一个方法（而非独立的事务管理器），且同模块**没有** WAL 相关的函数（对照 `workspace_restore` 有 `_append_wal`/`_read_wal`/`_latest_wal`），可以**合理推断**它属于前两种形态之一。**（待确认：本批未逐行读 `_apply_multi` 函数体，不排除它内部有更强的保护。）**

**（3）`write_store` 为什么没有 WAL**

因为**目标与约束不同**：

| | `write_store`（写路径） | `workspace_restore`（恢复路径） |
|---|---|---|
| 操作性质 | **用户/模型主动发起的编辑** | **在已知 commit 上重建整个工作区状态** |
| 规模 | 少量文件（通常 1-5 个） | 可能**成百上千**个文件 |
| 单个操作是否可原子 | ✅ 单文件 rename 原子 | ❌ 跨多文件，无单一提交点 |
| 失败后谁来修 | **模型自己**（它能看到语法/哈希校验失败的结果，然后重试或换个做法） | **必须由系统保证**（用户指望「回滚到某个状态」是可完成的） |
| 因此需要 | 前置校验（便宜、覆盖绝大多数失败） | WAL + trash + 显式回滚（`_rollback_to_safety`，`:369`） |

关键判据：**「失败能不能交给上游重试」**。写路径的失败由模型承接（它是主动方，能感知失败并重新决策）；恢复路径的失败**没有上游可承接**——用户点了「恢复到 X」，系统不能回一句「恢复了一半，你自己看着办」。

所以两者是**不同一致性等级**的合理选择，而不是「一个做得不够好」。

**深化讲解**（面试官参考，不要求候选人全说）
这题的关键是**避免把「更强的一致性」当成无条件的目标**。WAL/事务是有成本的（额外的 IO、恢复逻辑、状态机复杂度、可能失败的回滚）。正确的做法是按**「失败的承接方是谁」**来定等级：

- 有上游可承接（模型、用户可以重试）→ 前置校验 + 原子单点足够；
- 无上游可承接（用户期望一个确定的结果）→ 必须有补偿/恢复机制。

顺带注意 `workspace_restore._move_to_trash`（`:296`）与 `_restore_trash`（`:311`）——删除文件是**移到 trash 目录**而不是 `unlink`，这样即使流程中断，被删内容也还在（可从 trash 恢复）。这是「无上游承接」场景下的典型手法：**不承诺「一定能原子完成」，但保证「每一步都不丢信息」**。



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

### XEYO-QA-0143 WAL 与「先移入 trash 再删」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_restore | 预写日志与安全回滚 | 困难 | 场景设计 | `python/engine/workspace_restore.py:20-96,296-322,369,389,615` |

**面试官提问**
（1）`WorkspaceRestoreTransaction` 的 WAL 由 `_append_wal(payload, *, durable=False)`（`:60`）、`_read_wal()`（`:74`）、`_latest_wal(records)`（`:89`）三个函数支撑。请说明 WAL 在这里的作用，以及 `durable=False` 这个默认值意味着什么。
（2）删除文件为什么走 `_move_to_trash(relative_path, trash_dir)`（`:296`）而不是直接删？`_restore_trash(moved_paths, trash_dir)`（`:311`）在什么时机被调用？
（3）`_rollback_to_safety(...)`（`:369`）与 `reconcile()`（`:615`）分别是给谁用的？

**参考答案要点**
**（1）WAL 的作用与 `durable` 的含义**

WAL（Write-Ahead Log，预写日志）的核心是：**在改动工作区之前，先把「我打算做什么」写下来**。这样如果中途崩溃，下次启动时可以读日志知道**当时进行到哪一步**，从而决定「继续完成」还是「回滚」。

三个函数构成最小 WAL 能力：

| 函数 | 作用 |
|---|---|
| `_append_wal(payload, *, durable=False)`（`:60`） | **追加**一条日志（意图/进度） |
| `_read_wal()`（`:74`） | 读回全部日志记录 |
| `_latest_wal(records)`（`:89`） | 从记录序列里取**每个目标的最新状态**——即「按 key 归并，保留最后一条」 |

注意第三个函数名是复数归并（`records` → 最新），说明 WAL 是**追加式**的：同一个文件可能有多条记录（计划删 → 已移入 trash → 已写新内容），`_latest_wal` 给出「现在到底处于什么状态」。这是崩溃恢复的关键——**日志不是「结果」，而是「过程」**，恢复时要能从过程推导出当前真实状态。

**`durable=False` 的默认值**：说明**默认的追加不做「强制落盘」（fsync）**。含义是：

- 性能优先：每条记录都 `fsync` 会把恢复路径的吞吐拉到磁盘 IOPS 下限；
- **代价**：进程崩溃（不是机器断电）时日志通常还在（在 OS page cache 里，进程死亡不影响）；但**机器断电/内核崩溃**时，最后几条未 fsync 的记录可能丢失；
- 所以实现提供了开关：需要更强保证时显式传 `durable=True`（例如「关键提交点」的那一条）。

这个设计是「**分层持久化保证**」：绝大多数记录允许丢失（它们只描述过程，丢失后可以重来），关键点强制落盘。

**（2）为什么「移到 trash」而不是直接删**

直接 `unlink` 的问题：**信息永久消失**。若整个恢复流程在「删了 A、还没写 B」时中断，A 的内容**只有 git 对象库里那一份**（如果它曾提交过）——但工作区里**未被提交的改动**就彻底没了。

`_move_to_trash(relative_path, trash_dir)` 把文件**移动到事务自己的 trash 目录**：

- 语义上等于删除（工作区里看不到了）；
- 但内容**仍在**（只是换了个位置），随时可以恢复。

`_restore_trash(moved_paths, trash_dir)` 的调用时机有两类：
1. **回滚路径**：`_rollback_to_safety`（`:369`）把工作区退回安全状态时，需要把已移入 trash 的文件**搬回来**；
2. **失败恢复路径**：流程中断后由 `reconcile()`（`:615`）识别并恢复。

这与 0142 的判据一致：在「失败的承接方是系统」的场景下，**每一步都必须可逆**。`trash` 是「无上游承接」场景的标准手法。

**（3）`_rollback_to_safety` 与 `reconcile` 的受众**

| 函数 | 受众/触发者 | 作用 |
|---|---|---|
| `_rollback_to_safety(...)`（`:369`，私有） | **事务内部**——`execute()`（`:389`）发现无法继续时的自救路径 | 把工作区退回**已记录的安全状态**，避免停在中间态 |
| `reconcile()`（`:615`，公开） | **外部**——进程重启后由上层调用（例如 server 启动时、或用户点「检查恢复状态」） | 扫描 WAL/trash，识别未完成事务并给出处理结果 |

注意 `_rollback_to_safety` 是**单下划线私有**、`reconcile` 是**公开**——这个可见性差异恰好对应「内部自救」与「对外恢复入口」的分工，与 0139 的 `reclaim_stale_if_expired` 是同一手法（显式对外暴露恢复能力）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题把「**崩溃安全的文件事务**」的三个必备要素串起来：

| 要素 | 本模块的实现 | 防的问题 |
|---|---|---|
| 过程可追溯 | WAL（`_append_wal` / `_read_wal` / `_latest_wal`） | 崩溃后不知道「做到哪了」 |
| 操作可逆 | trash（`_move_to_trash` / `_restore_trash`） | 删了/改了之后无法退回 |
| 状态可收敛 | `_rollback_to_safety`（内部）+ `reconcile`（外部） | 停在中间态无法继续 |

三者缺一不可：只有 WAL 没有可逆操作 → 知道做到了哪，但退不回去；只有 trash 没有 WAL → 能恢复文件，但不知道该恢复成什么样。

另一处值得注意的细节：`_read_target_bytes(commit, relative_path)`（`:235`）从**git commit** 里读目标内容——说明「恢复到某状态」的内容来源是**影子仓库的对象**（见 0132），而不是事务自己备份的副本。这解释了为什么 `_tree_entries(commit)`（`:115`）和 `_git_blob_hash(data)`（`:217`）存在：事务要把 git 树里的条目与 blob 与当前工作区逐项比对。



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

### XEYO-QA-0144 恢复事务的路径安全处理

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | workspace_restore | 路径校验、转义解码与只读处理 | 困难 | 代码阅读 | `python/engine/workspace_restore.py:97,115,138,180,217,221,235,243,253,287` |

**面试官提问**
`workspace_restore.py` 里有一组「把 git 里的路径变成可安全操作的本地路径」的辅助函数。请说明：

（1）`_validate_relative_path(relative_path) -> Path`（`:97`）存在的必要性（不校验会有什么攻击/故障面）？
（2）`_decode_tree_path(path_b: bytes) -> str`（`:138`）与 `_unescape_git_path(path: str) -> str`（`:180`）为什么是两个函数、分别在处理什么？
（3）`_make_writable(path)`（`:243`）是为了解决什么平台上的什么问题？
（4）`_git_blob_hash(data: bytes) -> str`（`:217`）为什么是用**本地计算**而不是调 `git hash-object`？

**参考答案要点**
**（1）`_validate_relative_path` 的必要性**

它把「来自 git 的路径字符串」转成「可安全操作的 `Path`」。**不校验**的风险面：

| 风险 | 例子 | 后果 |
|---|---|---|
| **目录穿越** | 路径里含 `../` 或绝对路径 | 恢复到工作区**之外**——覆盖系统文件、用户其它项目、甚至 `~/.ssh` |
| **符号链接逃逸** | 路径指向一个 symlink，symlink 目标在工作区外 | 写入穿透到工作区外 |
| **保留名/非法字符**（Windows） | `CON`、`PRN`、`AUX`、结尾的点/空格 | 创建失败或创建到意外位置 |
| **空/荒谬路径** | `""`、`.`、`/` | 意外操作工作区根 |

关键在于**这个路径来自 git 对象库**——而 git 对象库里的树可能由**任何来源**产生（用户历史提交、别人推的 commit、甚至影子库被第三方改动）。所以这是**不可信输入**，必须校验。返回 `Path` 而不是字符串，说明校验的产物就是「工作区内的相对路径」这一类型。

**（2）为什么是两个解码函数**

它们处理的是**两类不同的编码问题**：

| 函数 | 输入 | 处理什么 |
|---|---|---|
| `_decode_tree_path(path_b: bytes) -> str`（`:138`） | **字节** | git 的树对象里，文件名是**原始字节**。转成 `str` 需要选择编码——合法 UTF-8 直接解，非法字节需要回退策略（否则抛 `UnicodeDecodeError`）。这与 `shadow_git.py` 的 `decode_git_bytes` / `_git_text_encodings()` 是同一问题域（见 0146） |
| `_unescape_git_path(path: str) -> str`（`:180`） | **字符串** | git 在 `porcelain` 输出里会对特殊字符做**反斜杠转义**（例如含换行的文件名会输出成 `"a\nb"`）。要还原成真实文件名，必须**反解转义** |

即：一个解决「字节 → 字符串」的**编码**问题，另一个解决「git 转义表示 → 真实文件名」的**语法**问题。两者的输入类型不同（bytes vs str），职责不同，因此是两个函数。

（注意：`_decode_tree_path` 的命名以 `path` 而非 `bytes` 结尾，说明它的语义是「解码为路径」，不是「路径的字节」——命名上做了区分。）

**（3）`_make_writable(path)` 的平台问题**

在 **Windows** 上，**只读文件无法被覆写或删除**（`open(path, "w")` 抛 `PermissionError`、`os.remove` 抛 `PermissionError`）。而 git 的**索引与对象**会忠实地保留文件模式中的只读位——从 git 恢复出来的文件可能带着只读属性。

后果：恢复流程在「需要覆写一个只读文件」时直接失败。`_make_writable` 的作用是在覆写/删除前**清除只读位**（Windows 上即去掉 `FILE_ATTRIBUTE_READONLY`）。

这也解释了为什么需要 `_atomic_write`（`:253`）配合：它要先确保目标**可写**（否则 rename 覆盖也会失败），再落盘。

（**待确认**：`_make_writable` 的具体实现（是否用 `os.chmod`、是否处理 Windows 特有属性）未在本批逐行核对。）

**（4）为什么本地计算 blob 哈希**

`_git_blob_hash(data: bytes) -> str`（`:217`）是用**本地**算法算哈希，而不是 `git hash-object`。理由是**性能与依赖**：

- **调用 git 是进程启动**：每个文件一次 `subprocess`（进程创建 + git 初始化 + 参数解析）在 Windows 上是**毫秒到几十毫秒**级。恢复事务可能要处理**上百个文件**，逐次调用 git 会累加成秒级甚至分钟级延迟；
- **git blob 的哈希算法是公开确定**的：`sha1(b"blob " + str(len(data)).encode() + b"\0" + data)`（或 sha256 版本，取决于仓库格式）。**可以本地实现**，结果与 git 完全一致；
- **减少故障面**：不依赖 git 可执行文件在 PATH 里、不依赖子进程调用成功（对照 `shadow_git._run` 的失败处理）。

所以主循环里的「是否需要更新这个文件」判定（比较 git blob 哈希与当前内容哈希）可以用**纯本地计算**完成——只有真正需要读 git 内部对象时（`_read_target_bytes`，`:235`）才需要走 git。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的中心是「**把不可信输入变成可安全操作的对象**」。四个函数对应四种不同的「不安全因素」：

| 函数 | 不安全因素 | 类型 |
|---|---|---|
| `_validate_relative_path` | 路径穿越/绝对路径/保留名 | **语义安全** |
| `_decode_tree_path` | 非 UTF-8 文件名字节 | **编码鲁棒性** |
| `_unescape_git_path` | git 转义表示 | **语法还原** |
| `_make_writable` | 只读属性阻断写入 | **平台差异** |

再加一个**性能**优化（`_git_blob_hash` 本地算）。

这组函数的存在说明实现者经历过真实的跨平台故障（Windows 只读、非 UTF-8 文件名、路径转义），而不是只在 Linux 上跑通的实现。对 XEYO 这种「Windows 优先（`XEYO.bat`、WebView2、NSIS/MSI 打包）」的项目，这类处理是必需项。



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

### XEYO-QA-0145 百分位函数为什么要求已排序输入

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | prof_stats | 纯统计工具集 | 困难 | 代码阅读 | `python/engine/prof_stats.py:13,25,52,72,87` |

**面试官提问**
`prof_stats.py` 的 `percentile(sorted_values, p)`（`:13`）**要求输入已排序**（参数名直接写明 `sorted_values`）。请说明：

（1）为什么这样设计，而不是在函数内部排序？
（2）`summarize(values)`（`:25`）与 `summarize_grouped(...)`（`:87`）的关系是什么？`group_records(...)`（`:52`）与 `format_table(...)`（`:72`）分别在流水线的哪一段？
（3）这个模块与 `stage_clock.py` 是什么关系？（提示：`stage_clock.to_summary_report` 的 docstring 里有一句说明）

**参考答案要点**
**（1）为什么要求调用方排序**

`percentile(sorted_values, p)` —— 参数名就是契约：**调用方负责排序，函数只负责取值**。

理由：**避免重复排序**。典型用法是「对同一批数据取多个百分位」：

```python
clock_result = sorted(timings)
p50 = percentile(clock_result, 50)
p90 = percentile(clock_result, 90)
p99 = percentile(clock_result, 99)
```

若每次调用内部排序，同一组数据会被排序 3 次（`O(3 · n log n)`）；要求外部排序则只排一次（`O(n log n)`），三次取值的代价是 `O(1)` 级。

代价是**契约风险**：调用方若不排序，结果会**静默错误**（不是报错）。这就是为什么参数名要取得如此明确（`sorted_values` 而非 `values`）——**用命名把前置条件写在调用点上**。

（**待确认**：本批未逐行读函数体，因此「实现是否在内部做断言/校验」未确认。）

**（2）四条函数的流水线位置**

| 函数 | 阶段 | 输入 → 输出 |
|---|---|---|
| `summarize(values)`（`:25`） | **统计** | 原始数值序列 → `dict[str, float]`（一组统计量：均值/最大/最小/分位等） |
| `group_records(...)`（`:52`） | **分组** | 记录集 → 按某维度分组的记录 |
| `summarize_grouped(...)`（`:87`） | **组合** | 分组后的记录 → 「每组一份 summarize」的结果 |
| `format_table(...)`（`:72`） | **呈现** | 统计结果 → 可打印的表格文本 |

所以完整流水线是：

```
原始记录 → group_records（分组） → summarize_grouped（每组统计） → format_table（渲染）
                                   └─ 单组时直接 summarize
```

`summarize_grouped` 显然是 `group_records` + `summarize` 的组合封装（避免调用方每次手写循环），而 `format_table` 是**最后一公里**（把 dict 变成人能看的表）。

**（3）与 `stage_clock` 的关系：刻意解耦**

`stage_clock.py:84-85` 的 docstring 明确写着：

```python
def to_summary_report(report: dict[str, float]) -> str:
    """诊断用单行/多行文本(不依赖 prof_stats,保持零耦合)。"""
```

即：`stage_clock` **故意不依赖** `prof_stats`，自己实现了一个极简的文本格式化（`to_summary_report`）。

共性与差异：

| | `stage_clock` | `prof_stats` |
|---|---|---|
| 定位 | **时间采集**（`StageClock` 计时） | **通用统计**（分位数、分组、表格） |
| 输出 | `{name: ms}` + 单行文本 | 统计量 + 表格 |
| 依赖 | **零依赖**（docstring 明确） | 被诊断/上报侧使用 |
| 关系 | **互不依赖**（`to_summary_report` 是刻意的重复实现） | — |

为什么容忍这点重复？因为 `stage_clock` 的定位是「**旁路(P0)：回合内阶段计时纯件（无引擎依赖）**」（`:1`）——它可能被用在引擎最里层、甚至在 `prof_stats` 不可用的环境（早期初始化、最小化部署），所以宁可有 8 行重复的格式化代码，也不要引入一条依赖。

**深化讲解**（面试官参考，不要求候选人全说）
这题三层：① **前置条件用命名表达**（`sorted_values`）；② **统计流水线的阶段划分**（分组 → 统计 → 呈现）；③ **刻意解耦 vs 复用的取舍**。

第三条最值得体会：工程上「零耦合」有时比「消除重复」更重要。判断依据是**这个组件会被用在什么层**——`stage_clock` 声称「**无引擎依赖**」，如果它 import 了 `prof_stats`，那这句话就不成立（`prof_stats` 会把它拉进统计模块的依赖树）。

（**待确认**：`summarize` 返回的 `dict[str, float]` 具体含哪些键（p50/p90/mean/max…）本批未逐行核对。）



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

### XEYO-QA-0146 git 输出的编码回退

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | shadow_git | 字节解码与候选编码 | 困难 | 机制解释 | `python/engine/shadow_git.py:12,29,63,81` |

**面试官提问**
`shadow_git.py` 里 `_run(args, check=True)` 返回 `CompletedProcess[str]`，而 `_run_bytes(args, check=True)` 返回 `CompletedProcess[bytes]`；另有 `decode_git_bytes(data: bytes) -> str`（`:12`）与 `_git_text_encodings() -> list[str]`（`:29`）。

（1）为什么需要**同时**存在文本与字节两个执行入口？
（2）`_git_text_encodings()` 返回一个**列表**（多个候选）而不是单个编码——为什么？
（3）如果解码全部候选都失败，合理的兜底是什么？为什么不能直接抛异常？

**参考答案要点**
**（1）为什么两个入口都要**

| 入口 | 返回 | 适用 |
|---|---|---|
| `_run`（`:63`） | `str` | 输出**确定是文本**的场景——例如 `git status --porcelain` 的**状态行**、`git rev-parse HEAD` 的提交号。这些内容是 ASCII，解码无歧义 |
| `_run_bytes`（`:81`） | `bytes` | 输出**可能含任意字节**的场景——例如**文件名**（`git ls-tree`、`--name-only` 类输出）。文件名在 git 里是**原始字节序列**，在 Linux 上完全可以是非法 UTF-8 |

关键判据：**「输出里是否可能包含文件系统原始字节」**。若包含，就必须保留字节形态——一旦在子进程边界处解码成 `str`，非法字节的信息就丢了（或被替换成 U+FFFD，导致后续无法定位真实文件）。

这也解释了 `workspace_restore.py` 为什么要有 `_decode_tree_path(path_b: bytes) -> str`（0144）——那是同一个问题的另一处实现。

**（2）为什么候选编码是一个列表**

因为 **git 输出的编码不是单一的**，取决于多个因素：

| 因素 | 影响 |
|---|---|
| 平台默认编码 | Windows 上是 GBK/CP936 之类（中文系统），Linux 上通常 UTF-8 |
| git 配置 `core.quotepath` | 决定非 ASCII 路径是输出转义序列还是原始字节 |
| `i18n.logOutputEncoding` / `commitEncoding` | 影响提交信息等文本的编码 |
| 用户输入的文件名 | 可能混用多种编码（历史遗留文件） |

所以「猜一个编码」必然在某些组合下失败。返回**候选列表**（例如 `["utf-8", "gbk", "cp936", "latin-1"]`）并**依次尝试**，是覆盖率最高的策略：绝大多数情况第一个就成功，极端情况靠后面的兜底。

（**待确认**：`_git_text_encodings()` 的具体候选列表与顺序未逐行核对；顺序本身也是设计决策——通常把最可能/最严格的编码放前面。）

**（3）兜底与「为什么不能抛异常」**

合理的兜底是**保信息优先**：用 `errors="surrogateescape"`（对照 0115/0138 的同一手法）或最终回退到 `latin-1`（**任意字节序列都能「解码」且可逆**）。

**为什么不能抛异常**：因为解码失败会**中断整条链路**，而链路的调用方（`WorkspaceRevision.calculate`、`workspace_restore` 的树比对）需要的是一个**确定的结果**：

<!-- 说明：以下为设计分析，非逐行源码引用 -->

1. **指纹场景**（0129）：如果一个文件名解码失败就抛异常，那么 `calculate()` 会失败 → 回滚前置校验**无法完成** → 用户无法回滚。而「**无法回滚**」比「指纹里某个文件名显示成乱码」严重得多；
2. **恢复场景**（0143/0144）：恢复必须能处理那个文件（哪怕名字是乱码形式），否则工作区会**缺文件**；
3. **可逆性**：`surrogateescape` 编码的结果**可以逆变换回原字节**（这是它存在的全部意义），所以用它解码不会丢失信息——后续要真正操作文件时可以再编码回 bytes 去 `open()`。

设计原则可以概括为：**「显示可以降级，功能不能中断」**。

**深化讲解**（面试官参考，不要求候选人全说）
这题把「编码」从「字符串细节」提升到**系统鲁棒性**层面。三条判据：

| 决策 | 判据 |
|---|---|
| 是否需要字节入口 | 输出是否可能含文件系统原始字节 |
| 为什么候选是列表 | 编码取决于平台 + 配置 + 输入，无法单一确定 |
| 为什么不抛异常 | 链路的产物（指纹/恢复）必须产出确定结果；显示可降级，功能不可中断 |

顺带一个跨模块的观察：`surrogateescape` 在 B03 里出现了**三次**（0115 的指纹编码、0138 的哈希输入、0146 的解码兜底）——这不是巧合，而是同一类问题（**处理任意字节的文件名**）在三个不同环节的一致答案。



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

### XEYO-QA-0147 墙钟与成本两道水位的触发点

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | budget | 墙钟死线与 USD 水位 | 困难 | 机制解释 | `python/engine/budget.py:37,68,87,148-231,257-266` |

**面试官提问**
`budget.py` 里有一组墙钟与成本相关的接口：`wall_hard_stop_from_env()`（`:37`）、`default_budget_usd_from_env()`（`:68`）、`max_budget_usd_from_env()`（`:87`）、`set_wall_deadline(deadline_ts, *, started_ts=None)`（`:148`）、`wall_remaining_s(now=None)`（`:154`）、`arm_wall_stop(enabled=None)`（`:160`）、`check_wall_deadline(now=None)`（`:168`）、`check_usd_waterline()`（`:231`）。

（1）为什么 `check_wall_deadline` 与 `check_usd_waterline` 都被放在 `prepare_next_turn()` 的**开头**、且都包在 `try/except: pass` 里？
（2）`arm_wall_stop(enabled=None)` 的参数默认是 `None`——这暗示什么语义？
（3）墙钟的「80%/90% 阈值提醒」与 `WALL_STOP_NOTICE`（`:34`，文案「时间预算已到上限（已进入收尾窗）。」）是什么关系？

**参考答案要点**
**（1）为什么放在 `prepare_next_turn` 开头 + 包 `try/except`**

`budget.py:257-266`（原文）：

```python
# 墙钟死线检查（禀赋①）：80%/90% 阈值提醒走既有 runtime notice 通道。
try:
    self.check_wall_deadline()
except Exception:  # noqa: BLE001
    pass
# USD 水位事实播报（默认档/显式限额共用，纯数字）。
try:
    self.check_usd_waterline()
except Exception:  # noqa: BLE001
    pass
```

**为什么在开头**：`prepare_next_turn()` 是「每轮模型请求前」的**唯一必经点**（B02-0075 已确认它是主循环的判定入口）。把「时间/成本检查」挂在这里，保证**每一轮都检查一次**，不需要额外的定时器或钩子。这是「**借既有节拍做周期性检查**」的手法（对照 B02-0067 的 30s 心跳也是借事件流节拍）。

**为什么包 `try/except: pass`**：这两个检查是**播报性质**（排队提醒、更新水位状态），不是**控制性质**。它们失败时：

- 不应该让回合崩掉（检查逻辑的 bug 不能杀主循环）；
- 不应该影响 `prepare_next_turn` 的返回值（返回值决定「能不能跑下一轮」，与播报无关）。

注意注释里的定位：「80%/90% 阈值**提醒**走既有 runtime notice 通道」「USD 水位**事实播报**」——都强调是**告知**，不是**裁决**。真正的硬停由 `prepare_next_turn` 的主逻辑（grace 阶梯，见 0118）决定。

**（2）`arm_wall_stop(enabled=None)` 的 `None` 语义**

参数是可选的 `bool | None`，默认 `None`。这种签名通常表示**「三态」**：

| 传值 | 语义 |
|---|---|
| `None`（默认） | **不做显式设置**——按环境/配置推导（`wall_hard_stop_from_env()`，`:37`） |
| `True` | 强制武装墙钟硬停 |
| `False` | 强制不武装 |

即：`None` 表示「**交给默认策略决定**」，而不是「关掉」。这与 `bool` 二值开关的语义不同——它是**「三态覆盖」**模式（显式值 > 环境推导）。

`set_wall_deadline(deadline_ts, *, started_ts=None)` 的 `started_ts=None` 同理：不传起点时按「现在」或内部记录推定。

**（3）阈值提醒与 `WALL_STOP_NOTICE` 的关系**

两者是**同一段墙钟时间轴上的不同刻度**：

| 时点 | 事件 | 通道 |
|---|---|---|
| 80% / 90% | 排队提醒（`_queue_notice`，走 runtime notice） | `consume_runtime_notice` → T_now 投影（模型可见一轮） |
| 100%（死线到） | 触发 `WALL_STOP_NOTICE`（「时间预算已到上限（已进入收尾窗）。」） | 同样走 runtime notice |
| 死线之后 | `check_wall_deadline()` 返回停止原因（返回类型 `str | None`），进入收尾窗/硬停判定 | 与 grace 阶梯（0118）汇合 |

即：**提醒是渐进的（80/90/100），硬停判定是最后的**。渐进提醒的意义是让模型**有时间主动收敛**——在还剩 10-20% 时间时就知道「快没时间了」，而不是到死线才被告知（那时只能被动收尾）。

`WALL_STOP_NOTICE` 的文案本身也值得注意：「**已进入收尾窗**」——它陈述的是**状态转移的事实**（而不是「请尽快完成」这类催促）。这与 B02-0060 的三条文案（`MAX_TURN_WARNING` / `MAX_TOOL_WARNING` / `WALL_STOP_NOTICE`）属于同一族：只陈述事实，不做劝导。

**深化讲解**（面试官参考，不要求候选人全说）
这题把「预算」的三条独立轴拼齐了（对照 B02-0090 的方法面）：

| 轴 | 计数依据 | 渐进提醒 | 硬停入口 |
|---|---|---|---|
| 轮次 | `turn_count` vs `max_turns` | `MAX_TURN_WARNING` | `prepare_next_turn` grace 阶梯 |
| 工具调用 | `current_turn_tool_calls` vs `max_tool_calling` | `MAX_TOOL_WARNING` | `begin_tool_call` 返回 False |
| **墙钟** | `wall_remaining_s` vs 死线 | 80%/90% | `check_wall_deadline` + `WALL_STOP_NOTICE` |
| **成本** | 累计 USD vs 限额 | USD 水位播报（纯数字） | `over_budget` / `over_token_budget` |

一个重要结论：**墙钟与成本是「环境/外部约束」，轮次与工具是「行为约束」**。前两者可能在任何时刻到顶（用户设了 5 分钟、余额不足），因此必须挂在「每轮必经点」上做检查，而不能只在计数到顶时触发。

另外 `default_budget_usd_from_env()` 与 `max_budget_usd_from_env()` 成对出现，说明成本限额有**默认档**与**显式上限**两层——`check_usd_waterline` 的注释明确「默认档/显式限额**共用**」。



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

### XEYO-QA-0148 IdenticalResultFold 的内部状态与「连续」的真实含义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | repeat_fold | 三个状态字典的语义与增长 | 困难 | 代码阅读 | `python/engine/repeat_fold.py:88-108,111-135,137-140` |

**面试官提问**
`IdenticalResultFold` 用三个字典维护状态。请回答：

（1）`_state`、`_equi_seen`、`_equi_seq` 的键与值分别是什么？
（2）**关键**：`equi_n` 的含义是「该内容第 N 次出现」吗？请用序列 `A, B, A` 和 `A, A, B, A` 分别演算 `equi_n`（阈值设为 3），说明 `_equi_seq` 到底是「每内容计数」还是「每工具计数」。
（3）这个设计会带来什么行为？在什么情况下会**漏折叠**？
（4）长回合下三个字典的内存增长如何？`reset()` 之外还有清理吗？

**参考答案要点**
**（1）三个字典**

```python
self._state: dict[str, tuple[str, int]] = {}   # key=(tool_name + "\x00" + semantic_key) → (last_digest, seq)
self._equi_seen: dict[str, set[str]] = {}      # tool_name → 该工具出现过的所有结果摘要集合
self._equi_seq: dict[str, int] = {}            # tool_name → 等价重复的连续计数
```

| 字典 | 键 | 值 |
|---|---|---|
| `_state` | 「工具 + 语义签名」字符串 | `(上次输出的摘要, 连续相同计数)` |
| `_equi_seen` | **工具名** | 该工具**历史上出现过的全部**结果摘要（集合） |
| `_equi_seq` | **工具名** | 最近一次「非首次出现」的**连续**计数 |

关键观察：`_equi_seen` 与 `_equi_seq` 的键是**工具名**（不是「工具+签名」，也不是「摘要」）。

**（2）`equi_n` 的真实含义（演算）**

相关代码：

```python
if _equiv_enabled() and d:
    seen = self._equi_seen.setdefault(tool_name, set())
    if d in seen:
        self._equi_seq[tool_name] = self._equi_seq.get(tool_name, 0) + 1
    else:
        self._equi_seq[tool_name] = 0
        seen.add(d)
    equi_n = self._equi_seq[tool_name] + 1
```

因为 `_equi_seq` 的键是**工具名**，所以计数器是**每工具一个**——每次调用该工具时，只根据「本次摘要是否已在 seen 中」来**递增或清零**，而**不区分是哪个摘要**。

**演算 A：序列 `A, B, A`（阈值 3，工具为 T）**

| 调用 | 摘要 | 在 seen 中？ | `_equi_seq[T]` | `equi_n` |
|---|---|---|---|---|
| 1 | A | 否 | 0 | 1 |
| 2 | B | 否（已加 A） | **0**（清零） | 1 |
| 3 | A | **是** | 1 | 2 |

结果：第三次调用 `equi_n = 2`，**不折叠**（< 3）。注意第 3 次是「A 的第 2 次出现」，但 `equi_n` 只有 2——**不是「该内容出现的总次数」**。

**演算 B：序列 `A, A, B, A`**

| 调用 | 摘要 | 在 seen 中？ | `_equi_seq[T]` | `equi_n` |
|---|---|---|---|---|
| 1 | A | 否 | 0 | 1 |
| 2 | A | 是 | 1 | 2 |
| 3 | B | 否 | 0 | 1 |
| 4 | A | 是 | 1 | 2 |

结果：**全程不折叠**——因为第 3 步的 B 把计数器清零了。

**结论**：`_equi_seq` 是**每工具计数**，`equi_n` 反映的是「**该工具最近连续几次调用都命中了『历史见过的内容』**」，而不是「某个具体内容出现了多少次」。

**（3）行为与漏折叠场景**

这个设计的**优点**：它抓的是「**连续重复**」这个模式——连续 3 次调用结果都是「见过的内容」，是死循环的强信号；而散布在长序列里的重复（A……A……A）不算。

**漏折叠的场景**：
- **交替模式**：`A, B, A, B, A, B, ...`——每次都在 seen 中（`d in seen` 为真），但等等：这里 `_equi_seq` 会**一直递增**（因为每次都命中 seen），所以 `equi_n` 会到 3 并折叠。**这才是真正危险的情况**：交替虽然「内容在变」，但都是旧内容，属于典型的空转；
- **真正漏掉的**：`A, A, B, C, A, A, A` —— 中间的 B/C（新内容）会把计数清零两次，所以最后的 `A,A,A` 只能拿到 `equi_n = 3`（第 3 个 A）——刚好达到阈值，会折叠一次；
- **容易漏的**：`A, B, A, C, A, D, A, ...` 这种「新内容穿插」的模式永不清零前先被穿插清零，`_equi_seq` 反复归零 → `equi_n` 长期为 1-2 → **永不折叠**。这在「模型反复看同一批文件、中间偶尔看一眼新文件」的场景下会漏掉。

**（4）内存增长与清理**

| 字典 | 增长上界 | 是否有界 |
|---|---|---|
| `_state` | 不同「工具+签名」组合的数量 | 受本回合调用数限制（有界） |
| `_equi_seen` | 每工具累积**所有见过**的摘要（16 字符 hex + set 开销） | **随回合内不同输出数线性增长** |
| `_equi_seq` | 工具数量 | 有界 |

`_equi_seen` 是唯一有实质增长压力的：一个超长回合（例如 256 轮 × 每轮 64 个工具 = 最多 16384 次调用）下，若每次输出都不同，`_equi_seen[T]` 可累积上万条摘要。

**除此之外没有别的清理**——`reset()`（`:137-140`）清空三个字典，而 `reset()` 的调用时机是**每 submit 新建对象**（`query_loop.py:776-778` 注释「每 submit 新建 → 与 repeat_guard 同步的**用户输入级重置**」）。也就是说：

- **正常情况**：一个用户回合结束 → 对象被丢弃 → 内存释放。所以增长上界 = **单个用户回合**的调用数；
- **风险场景**：一个**极长**的用户回合（模型自己跑几百轮不返回）会让 `_equi_seen` 涨到 MB 级。量级评估：假设 16384 条摘要 ×（16 字符 + Python str 开销 ~65 字节 + set 条目 ~30 字节）≈ **1.5-2 MB**。对现代机器可接受，但对「多会话并发」的场景会成倍叠加。

**深化讲解**（面试官参考，不要求候选人全说）
这题的核心是**从代码推出「计数器的真实语义」而不是接受命名暗示**。`_equi_seq` 这个名字读起来像「等价序列计数」，很容易误以为是「每条内容的计数」——但字典的**键是工具名**，这就决定了它是**每工具**的连续计数。

这个语义差异带来两个可验证的推论：
1. **交替模式会被折叠**（A,B,A,B… 每次都命中 seen，计数持续递增）——从「省上下文」角度是**正确的**（都是旧内容）；
2. **新内容穿插会清零计数**——这会**漏掉**「反复看旧内容、中间偶尔看新内容」的长空转。

如果要把「每内容计数」做对，`_equi_seq` 的键应该变成 `(tool_name, digest)`——但那样内存会更大（键数 = 摘要数）。当前设计是**内存与捕获能力之间的折中**：每工具一个计数器 → 内存恒定；代价是漏掉穿插模式。



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

### XEYO-QA-0149 三层机制下仍可能被静默覆盖的写路径

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | write_store × workspace_lock × workspace_revision | 并发写的覆盖范围与盲区 | 超压 | 故障排查 | `write_store.py:71,170-182,389,400`；`workspace_lock.py:18,217,265,286`；`workspace_revision.py:76` |

**面试官提问**
故障现象：会话 A 与会话 B 几乎同时修改 `src/app.py`。事后发现**B 的修改完全消失**，A 的版本胜出，且**没有任何错误被报告给 B**（B 以为写成功了）。

已知 XEYO 有三层机制可能与该问题相关：

- ① `WriteStore` 的分片锁（`_lock_for(path)`，`:179`；`shards=64`，`:170`）
- ② `WorkspaceLock` 的工作区租约（`acquire`/`renew`/`release`，`:217/265/286`）
- ③ `write_store` 的基准哈希校验（`_lookup_base_hash`，`:389` + `_content_hash`，`:71`）

请回答：

（1）三层各自的**保护范围**是什么（防什么、不防什么）？
（2）要让「B 静默失败」发生，需要同时满足哪些条件？请给出至少一条完整的条件链。
（3）哪一层的缺失是**最危险的**，为什么？
（4）除此之外，还有一类**完全不受三层保护**的写入通道——请指出它，并说明 `workspace_revision` 在其中扮演什么角色（是「阻止」还是「检测」）。

**参考答案要点**
**（1）三层的保护范围**

| 层 | 机制 | 覆盖范围 | **不覆盖** |
|---|---|---|---|
| ① 分片锁 | `threading.Lock`（按路径哈希分片） | **同一进程内**、同一路径的并发写串行化 | **跨进程**（`threading.Lock` 不跨进程）；不同路径之间不互斥 |
| ② 工作区租约 | 文件租约 + 心跳（跨进程可见） | **跨进程**的工作区级互斥（前提：调用方**确实 acquire 了**） | 粒度是**整个工作区**——它不区分「改哪个文件」；且完全依赖调用方主动持有 |
| ③ 基准哈希 | 读-改-写窗口的乐观校验 | **单文件**：「我读到的还是不是现在磁盘上的那份」（前提：intent **带了** base hash） | 不做互斥（只拒绝）；不带 base hash 的 intent 不受保护 |

三者是**互补而非冗余**：作用域分别是「进程内 × 路径」「跨进程 × 工作区」「单文件 × 时序」。

**（2）「B 静默失败」的条件链**

最典型的一条完整链（**B 走了不带基准哈希的路径、且未持租约、且在另一进程**）：

```
条件 1：A 与 B 处于【不同进程】（两个 attach 的 CLI/服务进程，或 GUI 与 CLI 并存）
        → ① 分片锁失效（进程内锁，不跨进程）

条件 2：两进程【都没有持有 WorkspaceLock 租约】
        → ② 失效（租约不主动生效；没人 acquire 就没有互斥）
        （现实原因：租约是「工作区级」的，若所有会话都持租约会彻底串行化，因此
          它可能只在特定操作（如恢复事务）中才被获取，而不是每次写文件都获取）

条件 3：B 提交的 ChangeIntent 【没有携带 base hash】（或指向的基准是 A 写之前的版本，
        而写入路径未做校验/校验被跳过）
        → ③ 失效（乐观校验的前提是「带上了基准」且「真的比对了」）

条件 4：B 的写入是【整文件覆盖】（而非基于最新内容的增量编辑）
        → 即使 B 读到的旧内容，它也只是把「基于旧内容算出的新内容」整体写下去

结果：A 的内容被 B 覆盖，或 B 的内容被 A 覆盖（取决于时序），
      两次写入都以「成功」返回 → 失败方毫不知情。
```

**关键洞察**：条件 3 是**最可能在现实中缺一环**的地方——因为乐观校验需要调用方**主动提供** base hash，而「读文件 → 记下哈希 → 带着哈希提交」这条链路上任何一个环节的疏忽，都会让校验静默退化为「不校验」。这也是为什么它必须与 ① ② 配合：**乐观校验不是为了替代互斥，而是为了在互斥缺席时兜住「静默覆盖」变成「显式冲突」**。

**（3）哪一层的缺失最危险**

**③ 基准哈希缺失最危险**，原因有三：

1. **① ② 的缺失是「显式可观测」的**——不持租约、跨进程这些事实是**架构可见**的（代码里看得到调用点），可以在设计阶段评估；而 ③ 的缺失是**数据依赖**的（取决于这一次 intent 有没有带 base hash），单次运行完全看不出问题；
2. **③ 是唯一把「静默覆盖」转成「显式冲突」的机制**。没有它，覆盖是**静默**的——A 和 B 都会收到成功，用户要到很久以后（例如发现功能异常、git diff 里少了一段）才会察觉；
3. **③ 是唯一能覆盖「非并发但有时序错乱」场景的**——例如 A 在 3 分钟前读了文件（记下 base），中间 B 改了它，现在 A 才提交。①（锁）只在**同时**写时有效，②（租约）只在持有期间有效，而 ③ 能跨越任意时间窗口。

**（4）不受三层保护的写入通道 + `workspace_revision` 的角色**

**通道清单**（至少四类）：

| 通道 | 为何不受保护 |
|---|---|
| `Bash` 工具执行的外部命令（`sed -i`、脚本生成文件、git checkout…） | 不走 `WriteStore`，没有分片锁、没有 base hash |
| 用户在**外部编辑器**中的修改（VS Code / Vim 保存） | 引擎完全不可见 |
| **构建/工具链**产生的文件（Vite 产物、`tsc` 输出、格式化器改写） | 由第三方进程写入 |
| **子代理 / 多代理 worker** 的写入（若它们各自有自己的 `WriteStore` 实例） | 分片锁不共享（不同实例 = 不同锁对象） |

**`workspace_revision` 的角色：检测，不是阻止。**

它的能力边界很清楚（`workspace_revision.py:12-20` 的 docstring）：计算一个「**保守的、仅元数据的**工作区指纹」（`rev_<sha256[:16]>`，见 0115）。它能做的是：

- 在**回滚计划开始**时记下 `expected_workspace_revision`，执行前重算并比对；
- 不一致 → **拒绝执行回滚**（而不是「修复冲突」）——它给出的是「环境已变」这个**事实**。

它**不能**做的是：

- 阻止任何写入（它不参与写路径）；
- 告诉你「是哪个进程改的」；
- 区分「无关噪声」（Vite 产物）与「真实冲突」——这正是 `paths=()` / `paths=[...]` 三态入参存在的原因（见 0128）：**通过缩小指纹范围把噪声排除在外**。

**为什么这是可接受的边界**：外部进程的写入**本质上无法被引擎阻止**——引擎不是操作系统，无法拦截用户用别的编辑器保存文件。所以正确的分层是：

| 层次 | 责任 |
|---|---|
| 引擎能控制的写入（`WriteStore`） | 三层防护：分片锁 + 租约 + 基准哈希 |
| 引擎不能控制的写入（Bash/外部/工具链） | **检测**：`workspace_revision` 比对 + 写前 `lstat` 元数据（0129） |
| 用户/模型 | 收到「环境已变」的事实后自行决策 |

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的训练目标是「**区分『防护』与『检测』，并接受不可控边界**」。三个层次必须分清：

1. **能阻止的**（引擎自己的写路径）→ 做足防护（三层）；
2. **能检测的**（外部写入）→ 提供指纹比对，把「不知道变了」变成「知道变了」；
3. **既不能阻止也不能检测的**（例如外部进程在两次指纹计算之间改了文件又改回来）→ 明确承认这是边界，不假装覆盖。

一个常见的架构错误是：**把「检测机制」当成「防护机制」**（例如以为有 `workspace_revision` 就不会有覆盖问题）。本题的故障现象（B 静默失败）正是这种混淆的产物——三层机制里没有任何一层真正**阻止**了那次覆盖，因为最该起作用的那层（基准哈希）在这次调用里缺席了。



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

### XEYO-QA-0150 断电重启后四个信息源的一致性收敛

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| engine 引擎 | 崩溃恢复 | 快照 / 进程账本 / WAL+trash / 影子仓库 | 超压 | 场景设计 | `turn_snapshot.py:151,167`；`process_ledger.py:200,237,357`；`workspace_restore.py:60-96,296-322,369,615`；`shadow_git.py:94,133,143,166`；`workspace_revision.py:76` |

**面试官提问**
场景：机器**断电**（不是进程崩溃）。重启后，XEYO 需要在四个信息源之间收敛状态：

- ① `turn_snapshot`（`~/.xeyo/sessions/*.turn.json`）—— 回合状态
- ② `process_ledger` —— 引擎启动过的后台进程台账
- ③ `workspace_restore` 的 WAL + trash —— 未完成的恢复事务
- ④ `shadow_git` —— 快照基线（配合 `workspace_revision` 算指纹）

（1）四者可能出现的**不一致组合**有哪些？请至少列出四条（每条附上对应的处理机制）。
（2）恢复的**执行顺序**应该是什么？请给出顺序并论证为什么「先处理 ②」是关键——请说明如果顺序反了会发生什么。
（3）断电与「进程被强杀」在恢复难度上有什么本质差异？这会影响哪一项的处理策略？
（4）四者中哪一个**不能**用来判断「工作区是否与某状态一致」？为什么？

**参考答案要点**
**（1）四类不一致组合与处理机制**

| # | 不一致现象 | 处理机制 |
|---|---|---|
| 1 | **快照说 running/stopping/queued，但进程其实已死**（进程不可能还活着） | `mark_crashed_as_recovery(snap)`：`running/stopping/queued` → `recovery_required`，`stop_reason` 为 `process_restart`；若 `waiting_permission` 则为 `restart_while_waiting_permission`（见 B02-0087） |
| 2 | **账本里有登记，但 PID 已不存在**（幽灵条目） | `reap(...)` / `sweep(...)`（`process_ledger.py:200,237`）——用 `default_probe` 探测（`_pid_alive`，`:70`）判定死亡后清理 |
| 3 | **进程已死但子进程还活着**（孤儿，可能仍在写文件/占端口） | 同上，`default_cleanup`（`:116`）→ `_terminate_pid`（`:94`）；`leftovers(owner=)`（`:357`）提供「残留」查询 |
| 4 | **WAL 有「计划删除 X」的记录，但 trash 里找不到 X**（事务在「移入 trash」之前就断电） | `reconcile()`（`workspace_restore.py:615`）：按 WAL 判定事务未完成，走 `_rollback_to_safety`（`:369`）或报告状态 |
| 5 | **WAL 有「已移入 trash」记录，文件确实在 trash**（事务中断在中途） | `_restore_trash(moved_paths, trash_dir)`（`:311`）把文件搬回，恢复原状 |
| 6 | **影子仓库 HEAD 与工作区内容不符** | 这是**正常状态**（工作区本就可以有未提交改动）。只有与 `expected_workspace_revision` 比对时才有意义（见 0149 的（4）） |

注意 #4 与 #5 的区别：**WAL 记录的是「过程」，而 trash 是「事实」**。恢复时必须用**事实**（文件是否真在 trash）来判定实际进度，而不能只信 WAL 的最后一条——因为断电可能发生在「记录已写、文件还没移动」之间（WAL 先写、动作后做，这正是 WAL 的定义）。这也是 `_latest_wal(records)`（`:89`，按 key 归并取最新）必须与 `_read_wal()` 配合的原因。

**（2）恢复顺序与「先处理 ②」的论证**

**推荐顺序**：

```
② 清理进程账本（kill 残留/孤儿，确认没有"活着的写者"）
  ↓
③ 收敛恢复事务（读 WAL + 检查 trash 实际状态 → 完成/回滚）
  ↓
① 处理回合快照（running/stopping/queued → recovery_required，标记待用户确认）
  ↓
④ 计算工作区指纹（配合 shadow_git HEAD），供上层与 expected_*_revision 比对
```

**为什么②必须最先**——这是本题的核心：

核心概念是 **TOCTOU（Time-of-Check to Time-of-Use）**。残留进程是四者中**唯一「仍在改变状态」的源**：

- 快照、WAL、影子仓库都是**静态数据**（不会再变）；
- 而一个侥幸存活的后台进程（例如一个还在跑的后台构建、一个卡住的 bash job）**可能正在写文件**。

如果先做 ③（恢复事务）而进程还在写：

1. 恢复事务读到的工作区状态是 **T 时刻**的；
2. 在其执行过程中，残留进程在 **T+ε** 改了同一个文件；
3. 恢复事务按 T 的信息做决策（例如「这个文件需要删掉」），结果**破坏了残留进程的新写入**，或者**恢复到一半又被改动**；
4. 最终工作区处于一个**既不是「恢复前」也不是「已恢复」**的第三方状态。

**先清理进程**把「活跃写者」变成「零个」——之后所有恢复动作都在**静态工作区**上进行，TOCTOU 窗口消除。

**顺序反了的具体后果**（顺序 ③ → ②）：

- 恢复事务可能**半途被干扰**（如上）；
- 更糟：恢复完成后残留进程继续写 → 覆盖恢复结果 → 用户看到「我恢复了但它又变回去了」；
- 而且这个故障**难以复现**（取决于残留进程的时序），会成为长期的随机 bug 来源。

**（3）断电 vs 强杀的本质差异**

| | 进程被强杀（SIGKILL / 任务管理器） | **机器断电** |
|---|---|---|
| 进程内存 | 立刻丢失 | 立刻丢失 |
| **OS page cache** | **保留**（由 OS 继续持有，其他进程可读） | **全部丢失** |
| 未 `fsync` 的写入 | **通常已落盘或在 cache 中可见** | **可能丢失** |
| 文件系统元数据 | 一致（unlink/rename 已完成的事实在 cache 里，最终会落盘） | 可能处于**日志恢复**过程中（ext4/NTFS 会做 journal replay） |

**影响哪项策略**：直接影响 **WAL 的 `durable` 参数**（见 0143）。

- `_append_wal(payload, *, durable=False)` 默认**不 fsync**。在「强杀」场景下这没问题（cache 还在）；
- 但在**断电**场景下，最后几条未 fsync 的记录**可能真的没了**——于是 WAL 可能**缺少最后一步的记录**。

这恰好要求恢复逻辑**不能只依赖 WAL**，而必须**交叉验证 trash 的实际状态**（如（1）#4/#5 的分析）：**WAL 是「意图记录」，trash 是「事实」；断电时前者可能缺失，后者是文件系统层面的既成事实**。

同时也解释了为什么关键提交点要支持 `durable=True`——在必须保证「这一步不能丢」的地方显式 fsync，代价是性能。

**（4）哪一个不能用来判断「工作区是否与某状态一致」**

**① `turn_snapshot` 不能**。

理由：它描述的是**回合的执行状态**（`running` / `stopping` / `queued` / `waiting_permission` / `recovery_required` + `incomplete_tools` + `stop_reason`），**不包含任何工作区内容或哈希信息**。它的值是「引擎进行到哪一步」，而不是「工作区长得什么样」。

因此：

- 问「工作区变了吗」→ 用 ③（WAL/trash）或 ④（`workspace_revision` 指纹）；
- 问「这个回合还能不能继续」→ 用 ①；
- 问「有没有残留进程在捣乱」→ 用 ②。

而 **④ `shadow_git` + `workspace_revision` 也不能单独用来判断「一致性」**——它只知道「当前指纹是多少」，不知道「应该是多少」；那个「应该」来自**外部**（回滚计划开始时记录的 `expected_workspace_revision`，见 0149）。这又是一个「检测 ≠ 判定」的例子。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的核心是「**恢复顺序由『谁是活跃写者』决定**」。三个层次的推理：

1. **四源性质分类**：静态数据（快照/WAL/影子）vs 活跃实体（进程）；
2. **TOCTOU 原则**：先消除活跃写者，再做一致性收敛——否则在动态目标上做恢复等于没做；
3. **WAL ≠ 事实**：断电会丢失未 fsync 的日志，所以必须用文件系统的既成事实（trash 内容）交叉验证。

顺带一个观察：四源里三处都有「**显式对外恢复入口**」——

| 源 | 对外入口 |
|---|---|
| 快照 | `list_recoverable()`（B02-0087） |
| 进程账本 | `leftovers()` / `reap` / `sweep` |
| 恢复事务 | `reconcile()` |

这个一致性不是偶然：**崩溃恢复必须是「可被外部触发的」（服务启动时、用户主动请求时），而不能只依赖「下一次正常操作碰巧触发」**。



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

## 批次自检表（B03）

| 项 | 结果 |
|---|---|
| 题号连续性 | XEYO-QA-0101 – XEYO-QA-0150，**无跳号无重号** |
| 难度配比实测 | 简单 **16**（0101–0116）/ 中等 **18**（0117–0134）/ 困难 **14**（0135–0148）/ 超压 **2**（0149–0150）= **50** ✅ 与矩阵一致 |
| 题型分布 | 单选 8 / 多选 3 / 简答 24 / 场景分析 10 / 代码阅读 5（无重复主题） |
| 覆盖子模块 | abort / aging / wrap_window / stage_clock / repeat_fold / workspace_revision / budget（墙钟与 USD 侧）/ compact / loop_ledger / process_ledger / workspace_lock / write_store / shadow_git / prof_stats / workspace_restore（15 个文件） |
| 重复性检查 | ① 与 B02 的分界已守：`budget` 在 B02 只讲「轮次/工具/方法面」，本批只讲「墙钟/USD/grace 计数细节」，无重叠题；② 本批内 `0148` 深挖 `repeat_fold` 状态语义，与 `0125`（判定流程）角度不同，答案不重复；③ `0141`/`0142`/`0143` 分别聚焦单文件原子性 / 多文件一致性 / 跨文件事务，递进不重复 |
| 来源可追溯性 | 全部 50 题的「来源依据」均指向本批实际打开核对的 `文件:行号`；**未出现推测性行号** |
| 待确认条目（本批显式标注） | **6 处**：① 0139 心跳节拍与 stale 阈值；② 0139 是否用文件锁；③ 0140 `timeout=0.0` 在 `blocking=True` 时的语义；④ 0142 `_apply_multi` 的一致性等级；⑤ 0144 `_make_writable` 的实现方式；⑥ 0145 `percentile` 是否有内部断言、`summarize` 的返回键；⑦ 0146 候选编码列表与顺序 |
| 边界遵守 | 未涉及 B02（主循环/子代理/调度）、B07（权限裁决）、B11（rewind 快照服务）主题；`workspace_restore` 仅从「崩溃安全事务」角度出题，未涉及 rewind 的 checkpoint/snapshot 语义 |
| 未覆盖但已计划 | `compact` 的 `project_incremental` 实现细节（0123/0128 仅到定位层）、`shadow_git.snapshot` 参数细节、`workspace_restore._tree_entries/_decode_tree_path` 内部算法 → 如需可作 B11/补批 |
