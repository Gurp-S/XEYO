# XEYO QA 题库 · 第 9 批（B09）

> 题号范围：**XEYO-QA-0401 – XEYO-QA-0450**
> 主题：memory 记忆基础层（runtime C0/C1/C2 投影与索引块 · memindex sqlite 派生索引 · memdir 长期记忆目录 · journal 行为日志 · search 词法检索 · instruction 嵌套指令 · governance schema 与晋升闸 · working 工作快照 · session_md 任务语义笔记 · write_policy 写入门禁 · memory_switches 开关权威 · observe/offload/citation/agent_scope · token/cache_profile 占位）
> 难度配比：简单 14 / 中等 18 / 困难 13 / 超压 5
> 事实基线（本批实际打开读过的文件与实测行数）：
> `memory_switches.py`(252, 全文) · `write_policy.py`(59, 全文) · `l5_flag.py`(47, 全文) · `cache_profile.py`(30, 全文) · `token.py`(21, 全文) · `governance.py`(264, 全文) · `session_md.py`(537, 全文) · `working.py`(641, 全文) · `observe.py`(115, 全文) · `offload.py`(52, 全文) · `memindex.py`(409, 全文) · `memdir.py`(482, 全文) · `search.py`(528, 定义面全量 + 正文精读) · `instruction.py`(382, 定义面全量) · `journal.py`(440, 定义面全量) · `runtime.py`(1926, 常量段 + 老化边界段 + Memory 索引块段精读) · `engine/aging.py`(96, 前 55 行精读)
> **边界声明**：C2 压缩的**执行算法**（`deterministic_c2_summary` / `apply_c2_messages` / `try_extend_c2` / `project_for_model` 的逐行行为）归 **B10**；NightShift / summarize / simulator / L5 公式细节归 **B10**；`codeindex.symbols` 符号抽取归 **B15**；`memory_tool`（工具入口层）归 **B06**；`permissions`/`extensions` 对记忆的权限与开关约束归 **B07/B12**——本批只从「开关权威与注册表」角度涉及 `memory_switches`，不裁决权限三态。
> **行号口径**：`runtime.py`(1926) / `search.py`(528) / `instruction.py`(382) / `journal.py`(440) 四个大文件采用「先 Grep 抽定义行号 → 再按 offset/limit 精读」的方式核对，题面行号以本批实测为准。

---

## 本批题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0401 | 简单 | 概念确认 | 记忆开关注册表的六列结构 | `memory_switches.py:41-68` |
| 0402 | 简单 | 概念确认 | 唯一 GUI 暴露项与默认值 | `memory_switches.py:43` |
| 0403 | 简单 | 概念确认 | L5 默认模式与快路径回退 | `l5_flag.py:14-32` |
| 0404 | 简单 | 概念确认 | `c2_gate` 恒真的边界 | `l5_flag.py:40-47` |
| 0405 | 简单 | 概念确认 | `get_value` 的权威来源 | `memory_switches.py:157-174` |
| 0406 | 简单 | 机制解释 | 工作快照 sidecar 的文件名与目录 | `working.py:114-138` |
| 0407 | 简单 | 机制解释 | `session.md` 的七段模板与磁盘位置 | `session_md.py:19-34,140-142` |
| 0408 | 简单 | 概念确认 | `session.md` 的禁止写入集 | `session_md.py:36-42` |
| 0409 | 简单 | 概念确认 | `MemoryNote` 必填字段面 | `governance.py:26-44,88-104` |
| 0410 | 简单 | 概念确认 | 四个枚举词表 | `governance.py:10-13` |
| 0411 | 简单 | 概念确认 | memdir 的目录布局 | `memdir.py:1-5,122-140` |
| 0412 | 简单 | 概念确认 | `MEMORY.md` 索引的两条硬限 | `memdir.py:28-29,299-318` |
| 0413 | 简单 | 机制解释 | 写入门禁的四条启发式 | `write_policy.py:32-59` |
| 0414 | 简单 | 概念确认 | 冲突裁决的三种返回值 | `governance.py:213-233` |
| 0415 | 中等 | 机制解释 | 记忆搜索的召回门槛：`require_all` / `min_or_hits` | `search.py:135-190` |
| 0416 | 中等 | 机制解释 | 语料平面与三类分词 | `search.py:32-38,116-133` |
| 0417 | 中等 | 机制解释 | 近因加权与重排封顶 | `search.py:41-49,60,107-113` |
| 0418 | 中等 | 机制解释 | `instruction.load_instruction_text` 的缓存键与签名 | `instruction.py:28-62,288-323` |
| 0419 | 中等 | 机制解释 | `@include` 的三道闸 | `instruction.py:21-25,194-224` |
| 0420 | 中等 | 机制解释 | `paths` frontmatter 的作用域匹配 | `instruction.py:64-134` |
| 0421 | 中等 | 机制解释 | journal 的序号、锁与索引分层 | `journal.py:32-44,50-62,140-238` |
| 0422 | 中等 | 机制解释 | memindex 的三张表与六条要点 | `memindex.py:31-80` |
| 0423 | 中等 | 机制解释 | 签名缓存与 write-through | `memindex.py:144-192,258-271` |
| 0424 | 中等 | 机制解释 | fragment + retrieve 的能力边界 | `memindex.py:32-34,293-346` |
| 0425 | 中等 | 机制解释 | citation 锚点的行号来源 | `memdir.py:259-296` + `search.py:192-210` |
| 0426 | 中等 | 机制解释 | 晋升闸的完整证据集 | `governance.py:146-180` |
| 0427 | 中等 | 机制解释 | 晋升置信度的三档 | `governance.py:183-199` |
| 0428 | 中等 | 机制解释 | workspace 隔离与 user 域合并 | `memdir.py:80-119,403-415` |
| 0429 | 中等 | 机制解释 | 三处保留期/上限的常量与语义 | `memdir.py:33-44` + `spill.py:24-26` + `session_md.py:48-52` |
| 0430 | 中等 | 机制解释 | C2 确定性摘要的 8 个配额 | `runtime.py:52-60` |
| 0431 | 中等 | 机制解释 | L3 原子化分段的落点 | `working.py:105-112` |
| 0432 | 中等 | 机制解释 | 可重入计量的重启契约 | `working.py:45-59` |
| 0433 | 困难 | 场景设计 | 老化推进与 v61/C2 的四路互斥 | `runtime.py:215-236` + `l5_flag.py:35-37` |
| 0434 | 困难 | 场景设计 | 首压锚点与 resume 的字节稳定闭环 | `working.py:27-42,164-187,324-347` |
| 0435 | 困难 | 场景设计 | sidecar 与 `session.md` 的双持久化一致面 | `working.py:459-488` + `session_md.py:160-188` |
| 0436 | 困难 | 代码阅读 | 转录行数计数的 None 语义 | `session_md.py:365-389` |
| 0437 | 困难 | 场景设计 | sidecar 落盘失败静默的四类风险 | `working.py:431-456` |
| 0438 | 困难 | 场景设计 | sqlite 索引的缓存双刃 | `memindex.py:214-239,274-286` |
| 0439 | 困难 | 场景设计 | 检索重排为什么必须不改召回集 | `search.py:52-113,246-268` |
| 0440 | 困难 | 代码阅读 | Memory 索引块的一行化 | `runtime.py:1201-1263` |
| 0441 | 困难 | 场景设计 | 索引注入改挂 T_now 的 KV 理由 | `runtime.py:1266-1282` |
| 0442 | 困难 | 代码阅读 | 工具结果事实抽取的四个限额 | `session_md.py:403-444` |
| 0443 | 困难 | 场景设计 | A5 差分重写的原子性 | `session_md.py:204-327,485-537` |
| 0444 | 困难 | 场景设计 | 老化边界推进的最小滞后 | `runtime.py:48-50,222-236` |
| 0445 | 困难 | 场景设计 | 投影计量与 legacy 字段的双轨 | `working.py:45-59,75-77` + `observe.py:55-115` |
| 0446 | 超压 | 故障排查 | 已删开关的静默继承 | `memory_switches.py:112-155,229-252` |
| 0447 | 超压 | 场景设计 | offload 的写入点与权限面 | `offload.py:17-52` + `offload_read_tool.py:46-62` |
| 0448 | 超压 | 场景设计 | 老化默认关：删除已实现、恢复未实现 | `engine/aging.py:1-13,40-52` |
| 0449 | 超压 | 安全拷问 | 记忆读路径的注入面与工作区隔离 | `l5_flag.py:19-33` + `runtime.py:1201-1263` |
| 0450 | 超压 | 故障排查 | 回滚后双 sidecar 的残留与重注入 | `working.py:459-488` + `session_md.py:160-188` |

---

### XEYO-QA-0401 记忆开关注册表的六列结构

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memory_switches 注册表 | 六元组字段语义 | 简单 | 概念确认 | `python/memory/memory_switches.py:33-68` |

**面试官提问**
`MEMORY_SWITCHES` 的每一项是一个六元组。这六个位置分别是什么？请完整列举。

**参考答案要点**
**A、B**。

`memory_switches.py:33-41`（原文，注释即字段契约）：

```python
# (key, 中文说明, 合法取值, 未设默认, GUI 暴露, 运行时读该键)
#
# ``GUI 暴露``：仅产品设置面板可见的开关为 True。测试 / 评测便捷开关置 False——
#   仍可经 ``save`` / settings.json 切换，只是不出现在产品 GUI（它们是测试方便用的，
#   不是产品功能）。
# ``运行时读该键``：该键是否真被运行时读取。False = 已下线 / 恒关占位（authority 面
#   仍保留注册，以免"已裁决键"凭空消失）。GUI 若展示这类键必须按 ``effective`` 显示
#   并标注已忽略，禁止出现「显示开、实际关」。
MEMORY_SWITCHES: tuple[tuple[str, str, tuple[str, ...], str, bool, bool], ...] = (
```

六个位置：`key` / 中文说明 / 合法取值 / 未设默认 / **GUI 暴露** / **运行时读该键**——后两项都是布尔。

注册表内容被拆成五个派生字典（`:70-74`）：

```python
_ALLOWED = {k: v for (k, _, v, *_) in MEMORY_SWITCHES}
_LABELS = {k: v for (k, v, *_) in MEMORY_SWITCHES}
_DEFAULTS = {k: v for (k, _, _, v, *_) in MEMORY_SWITCHES}
_EXPOSED = {k: e for (k, _, _, _, e, _) in MEMORY_SWITCHES}
_RUNTIME_READS = {k: r for (k, _, _, _, _, r) in MEMORY_SWITCHES}
```

注意后两个用的是「精确解包」（`e`/`r` 在固定位置），前三个用 `*_` 吞掉尾部——即**位置顺序是硬契约**，调整元组顺序会静默改变语义。

**深化讲解**（面试官参考，不要求候选人全说）
「运行时是否读该键」这一列的用途是给**已下线键留位**：`XEYO_MEMORY_INDEX_LIVE`（`:67`）的 `runtime_reads=False`，于是 `current()` 里它的 `effective` 恒为默认、`source` 报 `"ignored"`（`:191-197`）。注释解释了动机：「authority 面不因下线而少一个已裁决键」——也就是**注册表同时承担「当前生效开关」与「历史上做过裁决的键」两重职责**，后者只为防止「已裁决键凭空消失」导致后人重新讨论同一个问题。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「该键的持久化文件路径 / 上次修改时间」——说明没抓住本题的分界（C）。
- 答成「该键的历史取值列表 / 回滚点」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0402 唯一 GUI 暴露项与默认值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memory_switches 注册表 | GUI 暴露面与默认 | 简单 | 概念确认 | `python/memory/memory_switches.py:43-46` |

**面试官提问**
`MEMORY_SWITCHES` 里 `GUI 暴露=True` 的项有几个？是哪个？它的合法取值与默认值是什么？

**参考答案要点**
**正解：B（1 个：`XEYO_C2_LLM_SUMMARY`，取值 `("0","1")`，默认 `0`）**
`memory_switches.py:42-46`（原文）：

```python
	# ---- GUI 暴露（当前唯一一项）----
	("XEYO_C2_LLM_SUMMARY", "C2 摘要 LLM 旁路：压缩摘要改由模型生成（强保真要点列表，多一次模型调用；实测吸收潜力高但输出不稳定，默认关=确定性摘要）", ("0", "1"), "0", True, True),
	# ---- 非 GUI 暴露（测试 / 评测便捷开关）----
	("XEYO_L5", "L5 模式：project=默认链(不跑每轮 decide)；v61=实验通道(每轮 decide)", ("project", "v61"), "project", False, True),
	("XEYO_TOOL_AGING", "工具结果老化：压缩后冻结区仍可按窗口紧追推进（默认关）", ("0", "1"), "0", False, True),
```

三项的暴露面：

| key | 合法值 | 未设默认 | GUI 暴露 | 运行时读 |
|---|---|---|---|---|
| `XEYO_C2_LLM_SUMMARY` | `("0","1")` | `"0"` | **True** | True |
| `XEYO_L5` | `("project","v61")` | `"project"` | False | True |
| `XEYO_TOOL_AGING` | `("0","1")` | `"0"` | False | True |
| `XEYO_MEMORY_INDEX_LIVE` | `("0","1")` | `"0"` | False | **False** |

注释把非暴露项的理由写明了：它们是「测试 / 评测便捷开关……仍可经 `save` / settings.json 切换，只是不出现在产品 GUI（它们是测试方便用的，不是产品功能）」。

**一个必须注意的口径分歧**：注册表里 `XEYO_L5` 的未设默认是 **`"project"`**，但 `l5_flag.py:16` 的 `DEFAULT_MODE = "v61"` 并注明「上线默认 v61（2026-09-06 用户决策）；project 作快路径回退」。两者**不矛盾**，因为它们是两个不同层的默认：注册表默认只在「settings 未指定」时被 `get_value` 返回；而 `l5_flag.l5_mode()` 拿到 `"project"` 时返回 `"project"`，只有拿到**既非 project 也非 v61** 的值（例如空串）才落到 `DEFAULT_MODE`。

即：**`XEYO_L5` 的实际生效默认是 `project`（注册表权威），`DEFAULT_MODE="v61"` 只在「注册表返回无法识别的值」这条兜底路径上生效**。这是一个真实的「两处默认值」现象，读代码时极易误判。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「1 个：`XEYO_L5`，取值 `("project","v61")`，默认 `project`」——说明没抓住本题的分界（A）。
- 答成「2 个：`XEYO_C2_LLM_SUMMARY` 与 `XEYO_TOOL_AGING`」——说明没抓住本题的分界（C）。
- 答成「3 个：`XEYO_C2_LLM_SUMMARY` / `XEYO_TOOL_AGING` / `XEYO_L5`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0403 L5 模式的解析与快路径回退

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | l5_flag 热路径开关 | 模式归一化 | 简单 | 概念确认 | `python/memory/l5_flag.py:12-37` |

**面试官提问**
`l5_mode()` 把哪些取值判定为 `project` 模式？

**参考答案要点**
**正解：B（`"project"` / `"off"` / `"0"` / `"false"` / `"c0c1"` 五个取值）**
`l5_flag.py:19-37`（原文）：

```python
def l5_mode() -> str:
	"""返回当前 L5 模式：v61 或 project。

	以 ``memory_switches.get_value`` 解析（GUI settings.memory 权威；空/非法残留
	环境变量一律忽略落默认），不再直接读 os.environ，避免忘删的残留变量误切 v61。
	"""
	from memory.memory_switches import get_value

	raw = get_value(ENV_KEY).strip().lower()
	if raw in ("project", "off", "0", "false", "c0c1"):
		return "project"
	if raw == "v61":
		return "v61"
	return DEFAULT_MODE


def use_v61() -> bool:
	"""是否在热路径每轮调用 v6.1 decide。"""
	return l5_mode() == "v61"
```

五个 `project` 取值：`"project"`、`"off"`、`"0"`、`"false"`、`"c0c1"`——即**「关掉 v61」的多种自然表达都被收编为快路径**。这是「方向安全」的写法：任何表示「不要 v61」的输入都落到已固化的稳定模式，而不是落到 `DEFAULT_MODE`（`v61`）去。

`"v61"` 是唯一进入 v61 的取值。其余（含空串）→ `DEFAULT_MODE`（`"v61"`，`:16`）。

**深化讲解**（面试官参考，不要求候选人全说）
注意一个与 0402 呼应的细节：`l5_mode()` 的入参来自 `get_value(ENV_KEY)`，而 `get_value` 对**未注册键**返回空串（`memory_switches.py:166-167`），对**已注册但未设置**的键返回注册表默认。所以：

- `XEYO_L5` 已注册，未设置 → `get_value` 返回 `"project"` → `l5_mode()` 命中第一分支 → `project`；
- 若有人误把键名写错（例如 `XEYO_L5_MODE`）→ `get_value` 返回 `""` → `l5_mode()` 落到 `DEFAULT_MODE = "v61"` → **意外启用 v61**。

也就是说：**「键名写错」会把模式从默认的 project 悄悄切到 v61**（`"project"` → `""` → `v61`）。这与 0402 的「双默认」是同一条边界的两个方向。写测试或写配置时必须核对键名。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「只认字面量 `"project"`」——说明没抓住本题的分界（A）。
- 答成「除 `"v61"` 之外的任何值」——说明没抓住本题的分界（C）。
- 答成「只认 `"project"` 与 `"c0c1"`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0404 `c2_gate` 恒真的边界

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | l5_flag 固化函数 | 恒真函数的历史与边界 | 简单 | 概念确认 | `python/memory/l5_flag.py:40-47` |

**面试官提问**
`c2_gate()` 的实现是 `return True`。关于这个函数？
**参考答案要点**
**正解：B（它**恒为 True**；原注册表开关 `XEYO_C2_GATE` 已在 2026-09-06 固化删除，函数只为兼容旧调用点而保留）**
`l5_flag.py:40-47`（原文）：

```python
def c2_gate() -> bool:
	"""project 模式超长会话 C2 是否允许：**恒 True**（2026-09-06 固化）。

	原为注册表开关（XEYO_C2_GATE，默认开）；v61 默认开启后冗余删除。
	project 回退下 Path A 公式（_c2_formula_enabled 恒 True）裁决 C2，
	无需总闸。读点仅兼容旧调用；恒 True。
	"""
	return True
```

配套证据在 `memory_switches.py:47-51` 的固化注释里：

```python
	# ---- 固化（2026-09-06 用户决策 "v61 默认开启"）→ 删除的 7 个开关 ----
	# XEYO_C2_GATE（project 专用闸；v61 下 decide 自主，无读取意义）
	# XEYO_V61_PARETO / XEYO_V61_SI / XEYO_V61_DYNAMIC_R（B1/B2/B3 证据门未过，恒关）
	# XEYO_C2_PRESSURE_FORMULA / XEYO_C2_GAIN_FORMULA / XEYO_C2_EXTEND_FORMULA
	# （Path A 公式只服务 project 模式；v61 下 decide 接管 C2 触发。改为 _c2_formula_enabled 恒 True）
```

`l5_flag.py:8-9` 的模块 docstring 也写了：「`XEYO_C2_GATE`：**已固化删除**（2026-09-06）……旧 settings 残留值被忽略。」

**深化讲解**（面试官参考，不要求候选人全说）
这是一道「**恒真函数是不是死代码**」的辨析题。答案：**不是死代码，但它已经不是开关**。两条判据：

1. **有调用点**（「读点仅兼容旧调用」）——删函数会破坏调用方；
2. **不是可配置项**——键已从注册表移除，`get_value("XEYO_C2_GATE")` 现在返回 `""`（未注册键），所以即使有人手工把 `XEYO_C2_GATE` 写进 settings.json，也不会有任何行为变化（并且它会被 `stale_keys` 报为残留、被 `prune_stale` 清掉，见 0446）。

「固化」（不再做成开关、回退只能改源码）与「删除」（连函数一起去掉）是两种不同的收敛动作，这个文件里两者都被用到了：`c2_gate` 是**保留函数、固化返回**；`XEYO_V61_*` 三个键是**连注册带实现一起删**。区分标准是「是否还有调用点需要兼容」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「它是一个可配置的总闸，读设置项决定返回值」——说明没抓住本题的分界（A）。
- 答成「它在 v61 模式下返回 True、在 project 模式下读设置」——说明没抓住本题的分界（C）。
- 答成「它的返回值取决于 `compact_cursor` 是否大于 0」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0405 `get_value` 的权威来源

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memory_switches 取值 | 单一权威源 | 简单 | 概念确认 | `python/memory/memory_switches.py:77-83,157-174` |

**面试官提问**
`get_value(key)` 从哪些来源求值？环境变量 `XEYO_L5=...` 会影响它吗？

**参考答案要点**
**正解：B（**只读** settings.json 的 `memory` 段（home 与 workspace 合并、workspace 优先），环境变量**一律不参与**）**
`memory_switches.py:157-174`（原文）：

```python
def get_value(key: str, cwd: str | None = None) -> str:
	"""记忆开关生效值：**settings.memory（GUI 设置）为唯一权威** > 默认。

	- **环境变量一律不再参与**（包括合法非空值）——彻底杜绝「忘删 / 不知名位置
	  残留的环境变量」影响运行时开关。
	- 离线 gate-test / eval 如需切换模式，改为写入 settings.json memory 段
	  （``memory_switches.save``），运行时经 ``XEYO_HOME``/``XEYO_CWD`` 解析同一处。
	- 与 :func:`current` 口径一致，避免「运行时读 env、显示读 settings」不一致。
	"""
	if key not in _DEFAULTS:
		return ""
	store = _memory_store(_resolve_cwd(cwd))
	if key in store:
		coerced = _coerce(key, store[key])
		if coerced is not None:
			return coerced
		return _DEFAULTS[key]
	return _DEFAULTS[key]
```

来源合并规则（`:77-83`）：

```python
def _memory_store(cwd: str | None) -> dict[str, Any]:
	"""合并 home + workspace（更具体优先）两处 settings.json 的 memory 段。"""
	home = _cfg._read_json(_cfg.home_settings_path())
	ws = _cfg._read_json(_cfg.workspace_settings_path(cwd)) if cwd else {}
	merged = dict(home.get("memory") or {})
	merged.update(ws.get("memory") or {})
	return merged
```

三条求值路径：键未注册 → `""`；键在 store 里且值合法 → 归一化值；值非法 → **注册表默认**（不是空串）。键不在 store → 注册表默认。

**cwd 的解析有个兜底**（`:105-109`）：

```python
def _resolve_cwd(cwd: str | None) -> str | None:
	"""运行时无显式 cwd 时，用服务器管理的 XEYO_CWD（非记忆开关）解析工作区设置。"""
	if cwd:
		return cwd
	return os.environ.get("XEYO_CWD", "").strip() or None
```

★ 注意这里**仍然读环境变量**——读的是 `XEYO_CWD`（工作区路径，不是记忆开关）。所以「环境变量一律不参与」这条纪律的准确表述是：**记忆开关的取值不来自环境变量；但定位哪一份 settings.json 仍可能依赖 `XEYO_CWD`**。这是一个措辞与实现的精确差别。

**深化讲解**（面试官参考，不要求候选人全说）
「单一权威源」的收益在 docstring 里点明：「避免『运行时读 env、显示读 settings』不一致」——也就是 0401 里那条「禁止出现『显示开、实际关』」的同类问题。

代价在 `apply_to_environ`（`:212-226`）里被补偿：它把 settings 中**明确指定**的键写进 `os.environ`，让仍读环境变量的旧代码看到新值。但它只写 settings 里实际出现的键（「未出现的键保留用户手动 env / 默认，避免覆盖用户在 .bat / shell 里显式设置的值」）——这一条与 `get_value` 的「env 不参与」形成了**局部不一致**：通过 `apply_to_environ` 写进 env 的值会被旧代码读到，但 `get_value` 不读。两条路径的读者不同，所以当前无害；但若将来有人把某处旧代码改成 `get_value`，值会变。这是本批的待确认项之一。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「环境变量优先，settings.json 次之」——说明没抓住本题的分界（A）。
- 答成「命令行参数 → 环境变量 → settings.json」——说明没抓住本题的分界（C）。
- 答成「只读 home 级 settings.json，忽略 workspace 级」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0406 工作快照 sidecar 的文件名与目录

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | working 快照 | sidecar 路径 | 简单 | 机制解释 | `python/memory/working.py:114-138` |

**面试官提问**
`WorkingSnapshot` 落盘在哪个目录、文件名是什么形态？会话 id 里的特殊字符怎么处理？目录可以被覆盖吗？

**参考答案要点**
目录 `~/.xeyo/sessions/`（可用 `XEYO_SESSIONS_DIR` 覆盖），文件名是 `<safe_name>.working.json`。

`working.py:114-138`（原文）：

```python
def _sessions_dir() -> Path:
    """会话 sidecar 目录（与 JSONL 相同，可用 XEYO_SESSIONS_DIR 覆盖）。"""
    override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xeyo" / "sessions"


def _safe_name(session_id: str) -> str:
    """会话键 → 稳定文件名。"""
    raw = session_id or "session"
    parts: list[str] = []
    for ch in raw:
        if ch == ":":
            parts.append("__")
        elif ch.isalnum() or ch in "._-":
            parts.append(ch)
        else:
            parts.append("_")
    return "".join(parts).strip("._") or "session"


def path_for(session_id: str) -> Path:
    """返回会话快照的文件路径（~/.xeyo/sessions/{id}.working.json）"""
    return _sessions_dir() / f"{_safe_name(session_id)}.working.json"
```

三条规则：

| 情形 | 处理 | 理由 |
|---|---|---|
| `:` | 换成 `__` | 冒号在 Windows 文件名里非法；用双下划线是**可识别**的替换（不是丢弃） |
| 字母数字与 `._-` | 保留 | 常见 id 形态（含子 agent 的 `__agent__` 分隔符）无需转义 |
| 其他字符 | 换成 `_` | 兜底 |
| 首尾 `._` | `strip("._")` | 避免生成 `.working.json` 这类隐藏/畸形名 |

`safe_name` 的**幂等性**值得注意：它的输出只含 `[A-Za-z0-9._-]` 与 `__`，再次调用不会再变化——所以「记录在 sidecar 内的 `session_id`」与「派生出的文件名」不会互相污染。注意 `_to_dict` 存的是**原始 session_id**（`:228`），而文件名是 `_safe_name` 的产物；`hydrate` 读回后又用**入参 sid 覆盖**（`:427`），所以文件名是权威，内部字段只是记录。

`session_md.path_for` 用同一个 `_sessions_dir()` 与 `_safe_name`（`session_md.py:140-142`），落成 `~/.xeyo/sessions/{safe}/session.md`——**同一会话的两个 sidecar 在同一目录下**（一个以 `<safe>.working.json` 结尾，一个在 `<safe>/` 子目录里）。

**深化讲解**（面试官参考，不要求候选人全说）
两个 sidecar 的布局差异（**同目录不同形态**）是有意的：`.working.json` 是**机器状态**（`working.py:3`：「本文件只做机器状态，不写给模型看的叙事」），`session.md` 是**给模型看的任务笔记**（`session_md.py:1-6`）。用 `.working.json` 后缀而不是子目录，让「一句话列出所有会话的状态文件」成为可能（`glob("*.working.json")`），而 `session.md` 需要按会话分目录存放（因为可能还有 `session_deltas.jsonl`，见 `session_md.py:230-232`）。

**边界**：`_sessions_dir()` 与 `spill.spill_root()`（`spill.py:40-44`）是**两个不同的**环境变量（`XEYO_SESSIONS_DIR` vs `XEYO_SPILL_DIR`），默认目录也不同（`~/.xeyo/sessions` vs `~/.xeyo/spill`）。写测试时要分别覆盖。



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

### XEYO-QA-0407 `session.md` 的七段模板

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | session_md 任务语义笔记 | 七段结构与定位 | 简单 | 机制解释 | `python/memory/session_md.py:1-34,140-142` |

**面试官提问**
`session.md` 的模板有哪七段？它的权威边界是什么？谁在什么时候写它？

**参考答案要点**
七段（`session_md.py:19-34` 的 `TEMPLATE`，原文）：

```python
TEMPLATE = """# Session
## Goal
{goal}
## Current state
{current}
## Completed
{completed}
## Important discoveries
{discoveries}
## Key facts
{facts}
## Open questions
{open_questions}
## Next action
{next_action}
"""
```

依次为：`## Goal` / `## Current state` / `## Completed` / `## Important discoveries` / `## Key facts` / `## Open questions` / `## Next action`（外加 `# Session` 标题行）。

**权威边界**（`:1-6` docstring 原文）：

```
"""L5b 会话任务语义笔记（给模型看，不是机器状态）。

磁盘：~/.xeyo/sessions/{id}/session.md
权威边界：只写 Goal / Current / Completed / discoveries / Open / Next + Facts。
禁止写入 todos、cwd、cursor、hit_tokens。
"""
```

**写入时机与节流**（`maybe_update`，`:485-537`）：

```python
def maybe_update(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    min_tool_calls: int = MIN_TOOL_CALLS,
    working: WorkingSnapshot | None = None,
) -> None:
```

两道节流门：`n_tools < min_tool_calls` 直接返回（`MIN_TOOL_CALLS = 8`，`:44`）；文件已存在且 `n_tools - epoch < REWRITE_GAP` 也返回（`REWRITE_GAP = 8`，`:45`）。另有第三道**内容相等**门（`:510-514`）：`old.strip() == text.strip()` 时只推进 `session_md_tool_epoch`、**不写盘**（注释：「内容无变化：只推进节流纪元，不写盘（写放大为零）」）。

**内容怎么来**（`_extract`，`:447-477`）：**纯确定性抽取，不 fork 摘要模型**（`:448` docstring「从消息确定性抽取七段；不 fork 摘要模型」）。例如 `goal` 取第一条 user 文本截 300 字、`current` 取最后一条 user 截 400 字、`completed` 是 `f"{tools} tool results in this session"`、`discoveries` 取最后一条 assistant 截 400 字、`open_questions` 取最后一条**含问号**（`?` 或 `？`）的 assistant 文本截 300 字、`next_action` 取最后一条 user 截 300 字。

**深化讲解**（面试官参考，不要求候选人全说）
「给模型看」这个定位决定了三处设计：①七段全是**叙事**（Goal/Next action 等），没有机器字段；②明确禁止写入 `compact_cursor` / `prompt_cache` / `hit_tokens` 与 todo 复选框（见 0408）；③抽取用**规则**而非模型——因为它的读者是模型（下游 C2 左段），如果生成也要调模型，就会引入「压缩器自身耗令牌 + 输出不稳定」的复合问题（对照 B10 的 `XEYO_C2_LLM_SUMMARY` 旁路：那条路正是因为这个代价才默认关，`runtime.py:75-85`）。



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

### XEYO-QA-0408 `session.md` 的禁止写入集

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | session_md 内容净化 | 禁止 token | 简单 | 概念确认 | `python/memory/session_md.py:36-42,235-238,392-400` |

**面试官提问**
`_FORBIDDEN` 里列了哪些 token？它们被用在哪些地方？

**参考答案要点**
**正解：B（五个：`compact_cursor`、`prompt_cache`、`hit_tokens`、`- [ ]`、`- [x]`）**
`session_md.py:36-42`（原文）：

```python
_FORBIDDEN = (
    "compact_cursor",
    "prompt_cache",
    "hit_tokens",
    "- [ ]",
    "- [x]",
)
```

用途在**两处净化函数**里：

`_strip_forbidden`（`:235-238`）——整篇净化：

```python
def _strip_forbidden(text: str) -> str:
    for token in _FORBIDDEN:
        text = text.replace(token, "")
    return re.sub(r"- \[[ xX]\]", "", text)
```

`_clip`（`:392-400`）——单行截断时净化：

```python
def _clip(text: str, n: int = 400) -> str:
    """截断并去掉会污染 session.md 的机器字段。"""
    cleaned = " ".join((text or "").split())
    for token in _FORBIDDEN:
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"- \[[ xX]\]", "", cleaned)
    if len(cleaned) > n:
        return cleaned[: n - 1] + "…"
    return cleaned
```

两处都是**先按字面量替换 `_FORBIDDEN`，再补一条正则** `- \[[ xX]\]`——正则比 `"- [ ]"` / `"- [x]"` 两个字面量多了 `- [X]`（大写 X）这一档，是对字面量集的**超集补丁**。

`maybe_update` 里的调用顺序（`:508`）：`text = _strip_forbidden(render(messages))`——**先净化后比较/写盘**，所以物化文件里不会出现这些 token。

**深化讲解**（面试官参考，不要求候选人全说）
五类禁止项分两组：

| 组 | token | 为什么禁 |
|---|---|---|
| 机器状态 | `compact_cursor`、`prompt_cache`、`hit_tokens` | 它们属于 **L3/L5 机器状态**（`working.py` 的地盘）。写进给模型看的笔记会造成「同一事实两个来源」，且这些值**每轮变化**——一旦进入 `session.md`，它的字节就不再稳定，下游 C2 左段的 KV 前缀会持续 miss |
| 执行清单 | `- [ ]`、`- [x]` | todo 复选框属于 `TodoWrite` 工具（`working.py` 的 `todos` 字段）。写进叙事会诱导模型把这份笔记当成待办清单去执行 |

第二组与 `runtime.py:1209-1210` 记录的那次事故**同源**：索引条目被弱模型当成任务对象（会话 `sess_mtiche8l`）。所以「禁止在给模型看的文本里混入可被误当任务的东西」是一条贯穿记忆层的纪律。

**边界**：净化是**字面量替换**，所以它只挡完全匹配。`compact cursor`（带空格）、`compactCursor`、`hit token` 等变体不会被挡——防线是「规则 + 上游抽取本来就不产生这些词」，而不是「穷举所有变体」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「只有 `todo` 相关的两个复选框标记」——说明没抓住本题的分界（A）。
- 答成「`password`、`token`、`secret` 三个敏感词」——说明没抓住本题的分界（C）。
- 答成「无固定集合，按正则在抽取时动态判断」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。
### XEYO-QA-0409 `MemoryNote` 的必填字段面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | governance schema | 必填字段与拒绝条件 | 简单 | 概念确认 | `python/memory/governance.py:26-44,88-104` |

**面试官提问**
`parse_and_validate(frontmatter, body)` 在什么情况下抛 `MemorySchemaError`？请说明它明确要求哪些字段。

**参考答案要点**
**正解：B（要求 `source` 是含非空 `kind` 的 mapping、`confidence` 存在、`status` 存在且属于三值枚举、`scope`（缺省 `workspace`）属于四值枚举、`applies_to` 是 list、正文（或 `content`）非空）**
`governance.py:88-113`（原文关键段）：

```python
def parse_and_validate(frontmatter: dict, body: str) -> MemoryNote:
    """把 frontmatter+正文校验成 MemoryNote；缺 source/confidence/status 则拒绝"""
    if not isinstance(frontmatter, dict):
        raise MemorySchemaError("frontmatter must be a mapping")
    note_type_raw = _as_str(frontmatter.get("type"))
    indexable = note_type_raw in ALLOWED_TYPES
    note_type = note_type_raw if indexable else "untyped"
    source = frontmatter.get("source")
    if not isinstance(source, dict) or not _as_str(source.get("kind")):
        raise MemorySchemaError("source.kind is required")
    if "confidence" not in frontmatter:
        raise MemorySchemaError("confidence is required")
    if "status" not in frontmatter:
        raise MemorySchemaError("status is required")
    status = _as_str(frontmatter.get("status"))
    if status not in ALLOWED_STATUS:
        raise MemorySchemaError("status must be active|superseded|deleted")
    scope = _as_str(frontmatter.get("scope") or "workspace")
    if scope not in ALLOWED_SCOPE:
        raise MemorySchemaError("scope must be user|workspace|project|task")
    applies = frontmatter.get("applies_to") or []
    if not isinstance(applies, list):
        raise MemorySchemaError("applies_to must be a list")
    content = (body or "").strip() or _as_str(frontmatter.get("content"))
    if not content:
        raise MemorySchemaError("content is required")
```

**六类拒绝 + 一处「不拒绝」**：

| 检查 | 拒绝条件 | 缺省行为 |
|---|---|---|
| frontmatter 类型 | 不是 mapping | — |
| `source.kind` | 不是 dict 或 kind 为空 | 无缺省，**硬要求** |
| `confidence` | 键不存在（值由 `_as_float` 校验可转 float） | 无缺省 |
| `status` | 键不存在，或值不在 `{active, superseded, deleted}` | 无缺省 |
| `scope` | 值不在 `{user, workspace, project, task}` | **缺省 `workspace`** |
| `applies_to` | 存在但不是 list | **缺省 `[]`**（`or []` 兜住空值） |
| `content` | 正文与 `frontmatter.content` 都为空 | 正文优先，frontmatter 兜底 |

**唯一的「不拒绝」是 `type`**（`:92-94`）：类型不在 `ALLOWED_TYPES` 时不抛错，而是**降级**——`note_type = "untyped"` 且 `indexable = False`。这个字段的设计意图写在 `MemoryNote` 的注释里：`indexable: bool = True  # 四类之外降级后不得进 MEMORY.md`（`:44`）。

其余字段的缺省（`:114-121`）：`title` 缺省取正文首行前 80 字；`id` 缺省 `new_note_id()`（`"mem_" + uuid4().hex[:16]`，`:65-67`）；`created_at`/`updated_at`/`last_confirmed_at` 缺省 `today_iso()`（后两者都以 `created` 为兜底）。

**深化讲解**（面试官参考，不要求候选人全说）
「哪些字段必填、哪些可降级」反映的是**可信度模型**：`source`/`confidence`/`status` 三条必填，正好是判定「这条记忆可不可信、还算不算数」的三要素——缺了它们，note 就无法参与冲突裁决（`resolve_conflict` 要看 `source.kind` 与 `confidence`）与晋升闸（`can_promote` 看 `source.kind` 与 `evidence`）。而 `type` 只是**分类标签**，分类不认识的笔记仍有价值（只是不进索引），所以降级而非拒绝。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「只要求 `content` 非空」——说明没抓住本题的分界（A）。
- 答成「要求 `id`、`created_at`、`updated_at`、`last_confirmed_at` 全部显式给出」——说明没抓住本题的分界（C）。
- 答成「只要求 `type` 属于四值枚举」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0410 治理层的四个枚举词表

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | governance 枚举 | 四张词表 | 简单 | 概念确认 | `python/memory/governance.py:10-13` |

**面试官提问**
`governance.py` 顶部定义了四张枚举词表。请给出这四张词表的成员。

A. `ALLOWED_TYPES = {"user", "feedback", "project", "reference"}`
B. `ALLOWED_STATUS = {"active", "superseded", "deleted"}`
C. `ALLOWED_SCOPE = {"user", "workspace", "project", "task"}`
D. `ALLOWED_SOURCE_KIND = {"user", "agent", "inference", "nightshift"}`

**参考答案要点**
**A、B、C、D 全对**。

`governance.py:10-13`（原文）：

```python
ALLOWED_TYPES = {"user", "feedback", "project", "reference"}
ALLOWED_STATUS = {"active", "superseded", "deleted"}
ALLOWED_SCOPE = {"user", "workspace", "project", "task"}
ALLOWED_SOURCE_KIND = {"user", "agent", "inference", "nightshift"}
```

四张表的**约束力不同**，这是本题真正要考的点：

| 表 | 被谁强制 | 不满足时 |
|---|---|---|
| `ALLOWED_TYPES` | `parse_and_validate`（`:93`） | **降级** `untyped` + `indexable=False`，不抛错 |
| `ALLOWED_STATUS` | `parse_and_validate`（`:103`） | **抛** `MemorySchemaError` |
| `ALLOWED_SCOPE` | `parse_and_validate`（`:106`） | **抛** `MemorySchemaError` |
| `ALLOWED_SOURCE_KIND` | **`parse_and_validate` 不检查** | 见下 |

★ `ALLOWED_SOURCE_KIND` 只要求 `source.kind` **非空**（`:96-97`），**并不校验是否属于这四值**。它的实际消费方是别的模块：

- `governance.can_promote`（`:159,170`）：`kind == "user"` 直接放行；`kind == "agent"` 配合收割证据放行；
- `governance.promotion_confidence`（`:189-198`）：`kind == "user"` → `1.0`；`kind in {"agent","inference","nightshift"}` → `AGENT_PROMOTE_CONFIDENCE`；
- `resolve_conflict`（`:222-223`）：`old.source.get("kind") == "user"` 才算用户确认；`new.source.get("kind") in {"inference","nightshift","agent"}` 算推断。

所以 `ALLOWED_SOURCE_KIND` 更接近**文档性常量**（说明 kind 的取值域），而不是执行闸。一个 `kind = "whatever"` 的 note **能通过 `parse_and_validate`**，但它既不匹配 `"user"` 也不匹配推断三值 → `promotion_confidence` 落到最后的兜底 `return AGENT_PROMOTE_CONFIDENCE`（`:199`）。

**深化讲解**（面试官参考，不要求候选人全说）
「同一文件里的四张表，只有三张在同一个函数里被强制」这件事很容易被读成 bug，但从消费面看是自洽的：`ALLOWED_SOURCE_KIND` 的取值差异只影响**置信度与冲突裁决**，不影响**能否成为一条 note**——而这两件事的正确性有别的兜底（置信度封顶 0.6、推断永不覆盖用户确认）。把它做成硬枚举会带来一个副作用：将来新增一种 source（例如 `"harvest"`）就必须同时改 `parse_and_validate`，否则**存量的合法笔记会变成非法**。



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

### XEYO-QA-0411 memdir 的目录布局

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memdir 长期记忆目录 | 布局与根路径 | 简单 | 概念确认 | `python/memory/memdir.py:1-5,112-140` |

**面试官提问**
一个工作区的长期记忆目录（memdir）里有哪些文件/子目录？根路径怎么确定？

**参考答案要点**
**正解：B（`workspace.json`、`MEMORY.md`、`topics/*.md`、`tombstones.jsonl`（另有 `rollout_summaries/` 由 `session_md` 归档时创建）；根路径 `~/.xeyo/memory/{workspace_id}/`，可用 `XEYO_MEMORY_DIR` 覆盖）**
`memdir.py:1-5`（原文模块 docstring）：

```python
"""L4 长期记忆：workspace memdir（MEMORY.md + topics）。

~/.xeyo/memory/{workspace_id}/
  workspace.json  MEMORY.md  topics/*.md  tombstones.jsonl
"""
```

`memdir.py:112-140`（根路径与骨架创建，原文）：

```python
def memdir_root(wsid: str) -> Path:
    """返回该记忆域根目录（~/.xeyo/memory/{workspace_id|user}/）"""
    override = os.environ.get("XEYO_MEMORY_DIR", "").strip()
    if override:
        base = Path(override).expanduser()
    else:
        base = xeyo_home() / "memory"
    return base / wsid


def ensure_layout(wsid: str, *, canonical_path: str = "") -> Path:
    """创建 memdir 骨架（topics / tombstones / workspace.json）。"""
    root = memdir_root(wsid)
    (root / "topics").mkdir(parents=True, exist_ok=True)
    ws = root / "workspace.json"
    if not ws.is_file():
        payload = {
            "workspace_id": wsid,
            "canonical_path": canonical_path,
            "created_at": today_iso(),
        }
        ws.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    idx = root / "MEMORY.md"
    if not idx.is_file():
        idx.write_text("# Memory index\n", encoding="utf-8")
    ts = root / "tombstones.jsonl"
    if not ts.is_file():
        ts.write_text("", encoding="utf-8")
    return root
```

四件套的职责：

| 路径 | 形态 | 职责 |
|---|---|---|
| `workspace.json` | JSON 单对象 | 记录 `workspace_id` / `canonical_path` / `created_at`；`workspace_path()` 反查用（`:93-102`） |
| `MEMORY.md` | Markdown | **导航索引**，每行 `[type] 标题 → topics/xxx.md`（`index_line`，`:292-296`） |
| `topics/*.md` | 每 note 一文件 | 长期记忆正文（frontmatter + body），文件名由 `topic_filename` 生成（`:248-251`） |
| `tombstones.jsonl` | JSONL 追加 | 遗忘墓碑（`append_tombstone`，`:442-451`） |
| `index.sqlite3` | SQLite | **派生索引**（`memindex.db_path`，`memindex.py:98-102`）——可随时删库重建 |
| `candidates.jsonl` | JSONL | 候选队列（`candidates_path`，`:480-482`） |
| `rollout_summaries/*.md` | 每会话一文件 | 任务级归档（`session_md.rollout_dir`，`session_md.py:55-59`） |

★ 注意 **docstring 只列了四件**，而实际布局有七件（`index.sqlite3`、`candidates.jsonl`、`rollout_summaries/` 是后加的）。这是「模块 docstring 未随功能增长同步更新」的典型现象——读代码时**以 `memdir_root`/`ensure_layout`/各 `_path` 函数的实际引用为准**。

**深化讲解**（面试官参考，不要求候选人全说）
「文件是 source of truth，sqlite 只是派生索引」这条铁律写在 `memindex.py:3-4`：「**定位铁律：sqlite 只是派生索引/缓存；文件（memdir topics/*.md、rollout_summaries/*.md、session.md、转录 JSONL）永远是 source of truth。** 库可随时删除并全量重建，零数据丢失风险。」所以布局里出现了**同一份数据的两种形态**（`topics/*.md` 与 `index.sqlite3` 的 notes 表），而它们的权威关系是单向的。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「只有 `MEMORY.md` 一个文件」——说明没抓住本题的分界（A）。
- 答成「`notes/`、`index/`、`cache/` 三个子目录」——说明没抓住本题的分界（C）。
- 答成「每个 note 独立存成 JSON 文件」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0412 `MEMORY.md` 索引的两条硬限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memdir 索引重写 | 行数/字节双上限 | 简单 | 概念确认 | `python/memory/memdir.py:28-29,299-318` |

**面试官提问**
`rewrite_index` 对 `MEMORY.md` 施加了哪两条限制？超限时分别怎么处置？

**参考答案要点**
**正解：B（行数 200（`INDEX_MAX_LINES`）/ 字节 25,000（`INDEX_MAX_BYTES`）；行数超限**截断条目循环**，字节超限**按 UTF-8 截字节后再补换行**）**
`memdir.py:28-29`：

```python
INDEX_MAX_LINES = 200
INDEX_MAX_BYTES = 25_000
```

`memdir.py:299-318`（原文）：

```python
def rewrite_index(notes: list[MemoryNote], *, wsid: str) -> None:
    """只写导航行 [type] 标题 → topics/xxx.md；禁止叙事；仅 mutation 成功或 NightShift 时调用"""
    root = ensure_layout(wsid)
    lines = ["# Memory index"]
    for note in notes:
        if note.status != "active" or not note.indexable or note.type not in ALLOWED_TYPES:
            continue
        lines.append(index_line(note))
        if len(lines) - 1 >= INDEX_MAX_LINES:
            break
    text = "\n".join(lines) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > INDEX_MAX_BYTES:
        text = encoded[:INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
        if not text.endswith("\n"):
            text += "\n"
    path = root / "MEMORY.md"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
```

两条限制的处置方式**不同**：

| 限制 | 判据 | 处置 |
|---|---|---|
| `INDEX_MAX_LINES = 200` | `len(lines) - 1 >= 200`（`-1` 扣掉标题行） | **循环 `break`**——只写入前 200 条，后面的条目完全不进索引 |
| `INDEX_MAX_BYTES = 25_000` | `len(text.encode("utf-8")) > 25000` | **按字节切片**后 `decode(errors="ignore")`，末尾补 `\n` |

两者叠加时**先按行截断、再按字节截断**——所以最终文件可能既不满 200 行、也不到 25,000 字节。

**三道过滤**（`:304`）：`note.status != "active"` 跳过（`superseded`/`deleted` 不进索引）；`not note.indexable` 跳过（未知 type 降级后的 note）；`note.type not in ALLOWED_TYPES` 再查一次（与 `indexable` 冗余，属防御性重复）。

**深化讲解**（面试官参考，不要求候选人全说）
两条限制的**方向差别**是关键：行数超限是「丢弃尾部条目」（信息缺失，但每行完整）；字节超限是「切断内容」（可能把某一行的路径切一半）。后者的 `errors="ignore"` 会让**截断点落在多字节字符中间时静默丢字符**——即字节截断倾向于产生「一行残句」。对一个**导航索引**而言这是可接受的（读者仍能拿到大部分路径），但如果把它当数据读就会出错。

★ 与 `runtime._memory_index_digest` 的配合（见 0440）：索引块最终只输出**计数摘要**，所以 200 行的具体条目**不进模型投影**——它们只服务于「人肉查看 + 计数」两个用途。

**写入用原子替换**：`tmp = path.with_suffix(".md.tmp")` + `os.replace`（`:316-318`）——注意 `with_suffix` 会把 `.md` 换成 `.md.tmp`，所以临时文件名是 `MEMORY.md.tmp`。同一手法在 `write_note`（`:369-371`）与 `session_md._atomic_write_text`（`:197-201`）里复用。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「文件数 1000 / 单行 200 字符」——说明没抓住本题的分界（A）。
- 答成「无限制」——说明没抓住本题的分界（C）。
- 答成「只在 NightShift 时检查，热路径不检查」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0413 写入门禁的四条启发式

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | write_policy 内容门禁 | 四条拒绝规则 | 简单 | 机制解释 | `python/memory/write_policy.py:10-59` |

**面试官提问**
`write_policy.refuse_reason(title, content)` 在哪些情况下拒绝写入长期记忆？请给出四条规则及其阈值。

**参考答案要点**
四条规则（`write_policy.py:32-59`，按代码顺序）：

**① 显式意图词**（`:40-44`）：`_EPHEMERAL` 正则在 `title + content` 上匹配即拒绝。

```python
	if _EPHEMERAL.search(blob):
		return (
			"refused: do not store directory trees or one-off/temporary plans; "
			"write only durable facts the user confirmed"
		)
```

`_EPHEMERAL` 的中英词表（`:21-29`）：`one-off plan` / `temporary plan` / `today's plan` / `directory tree` / `folder tree` / `repo tree` / `project tree` / `临时计划` / `今日计划` / `今天的临时` / `目录树` / `文件夹树` / `当前目录树` / `tree /f` / `` `tree` `` / `tree…/F`。

**② tree 风格内容**（`:46-53`）：先按「非空行数 ≥ 6」设门，再统计 `_TREE_LINE` 或 `_PATHISH_LINES` 命中的行数，满足 `treeish >= 4` **或** `treeish >= 3 且 占比 >= 0.4` 即拒绝。

```python
	lines = [ln for ln in content.splitlines() if ln.strip()]
	if len(lines) >= 6:
		treeish = sum(1 for ln in lines if _TREE_LINE.search(ln) or _PATHISH_LINES.match(ln))
		if treeish >= 4 or (treeish >= 3 and treeish / len(lines) >= 0.4):
```

**③ 纯路径堆砌**（`:55-57`）：`len(content) >= 800` **且** `/` 与 `\` 合计 `>= 40` 即拒绝。

```python
	if len(content) >= 800 and content.count("/") + content.count("\\") >= 40:
		return "refused: content looks like a bulk path dump, not a durable fact"
```

**④ 空内容放行**（`:37-38`）：`if not content: return None` —— 空正文**不拒绝**（由上游决定是否算作无内容）。

**一个顺序细节**：`blob = f"{title}\n{content}".strip()`（`:36`）把标题与正文拼成一个 blob 供 ① 匹配，但 ②③ 只看 `content`（不含标题）。所以「标题写『目录树』而正文是正常事实」会被 ① 拒绝；「标题正常而正文是路径堆砌」由 ②③ 兜住。

**深化讲解**（面试官参考，不要求候选人全说）
门禁的定位在模块 docstring 里写明（`:1-4`）：

```
"""Memory 写入内容门禁：模型不遵守时的工具层兜底。

禁止把目录树 / 一次性临时计划写成长期笔记。纯启发式，无 I/O、不调模型。
"""
```

三个特征：「**工具层兜底**」（不是模型可见的指令——遵守 AGENTS.md 铁律「限制只在执行层」）、「**纯启发式**」（无 I/O、不调模型，所以是零成本的同步函数）、「**针对两类具体污染**」（目录树/临时计划）。

为什么这两类要被挡：①目录树是**可再生成**的（一条 `Glob`/`tree` 命令就能重得），把它写成长记忆等于用永久存储存临时视图，且它会随仓库变化**立刻过期**；②一次性计划是**任务态**而非**事实态**，属于 TodoWrite/session.md 的地盘（对照 0408 的禁止写入集）。

**边界**：正则 `_PATHISH_LINES`（`:16-19`）要求行内有 `/` 且整行只由路径片段构成（`^[\t ]{0,4}(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\s*$`）——所以**Windows 反斜杠路径的行、以及带缩进的深路径**不会被它命中（反斜杠只出现在 `_TREE_LINE` 的盘符分支 `[A-Za-z]:\\`）；`_TREE_LINE` 的字符类 `[├└│\-+`]` 则负责 box-drawing 风格。这两条正则的组合覆盖「`tree`/`ls -R` 输出」的常见形态，但**不覆盖**纯 `dir` 的长列表（无树字符、无行首路径）。



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

### XEYO-QA-0414 冲突裁决的三种返回值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | governance 冲突分流 | `coexist`/`keep_old`/`supersede` | 简单 | 概念确认 | `python/memory/governance.py:202-233` |

**面试官提问**
`resolve_conflict(old, new)` 可能返回哪三个值？在什么条件下返回 `supersede`？

**参考答案要点**
**正解：B（`coexist` / `keep_old` / `supersede`；**同 type 同 title** 或 **new 显式 `supersedes == old.id`** 才 `supersede`）**
`governance.py:213-233`（原文，含设计理由）：

```python
def resolve_conflict(old: MemoryNote, new: MemoryNote) -> str:
    """先比 scope/applies_to；不冲突返回 coexist。

    只把「同一主题（type+title 相同）或新笔记显式 supersedes 旧 id」当作替换：
    若只看 scope/applies_to，任何同 scope 新笔记都会吞掉其它类型/标题的旧笔记，
    导致已记住的事实从索引/搜索里静默消失。推断仍不得覆盖用户确认（keep_old）。
    """
    if _applies_key(old) != _applies_key(new):
        return "coexist"
    old_user = old.source.get("kind") == "user" and old.confidence >= 1.0
    new_infer = new.source.get("kind") in {"inference", "nightshift", "agent"} and new.confidence < 1.0
    if old_user and new_infer:
        return "keep_old"
    same_topic = (old.type, (old.title or "").strip()) == (
        new.type,
        (new.title or "").strip(),
    )
    explicit = str(new.supersedes or "") == old.id
    if same_topic or explicit:
        return "supersede"
    return "coexist"
```

判定**有严格顺序**，四步：

| 步 | 条件 | 返回 |
|---|---|---|
| 1 | `_applies_key(old) != _applies_key(new)` | `coexist`（`_applies_key = (note.scope, tuple(applies_to 归一化))`，`:202-210`） |
| 2 | 旧是用户确认（`kind=="user"` 且 `confidence>=1.0`）**且** 新是推断（kind ∈ {inference, nightshift, agent} 且 `confidence<1.0`） | `keep_old` |
| 3 | `(type, title)` 完全相同 **或** `new.supersedes == old.id` | `supersede` |
| 4 | 其余 | `coexist` |

**第 2 步先于第 3 步**是本题的关键：即使同一主题、同一 scope，只要「旧=用户确认、新=推断」，就走 `keep_old` 而不是 `supersede`——**推断永不覆盖用户确认**。

**深化讲解**（面试官参考，不要求候选人全说）
注释里那句「若只看 scope/applies_to，任何同 scope 新笔记都会吞掉其它类型/标题的旧笔记，导致已记住的事实从索引/搜索里静默消失」记录了**一次真实的收缩决策**：`supersede` 的判据从「scope 相同」收紧到「主题相同或显式声明」。这个改动的性质是「**把范围过宽的替换条件收窄**」，因为过宽的替换会造成**静默删除**——而静默删除在记忆系统里是最难排查的故障（用户只会发现「它忘了」）。

`supersede` 的两个触发条件是**互补**的：`same_topic` 覆盖「模型重复记录了同一主题的更新版」（不需要显式声明）；`explicit` 覆盖「主题名不同但确实是替换」（由模型显式给出 `supersedes` id）。

注意 `_applies_key` 的归一化（`:202-210`）：对 dict 元素用 `repr(sorted(item.items()))`，所以**字典键序不影响比较**；`scope` 也进键，因此「同 applies_to 但 scope 不同」会判 `coexist`。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「只有 `replace` 与 `keep` 两种；同 scope 即替换」——说明没抓住本题的分界（A）。
- 答成「`merge` / `split` / `drop`；按 confidence 大小决定」——说明没抓住本题的分界（C）。
- 答成「`coexist` / `supersede`；按 `applies_to` 长度决定」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0415 记忆搜索的召回门槛

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | search 查询拆词 | 召回模式与门槛 | 中等 | 机制解释 | `python/memory/search.py:135-189` |

**面试官提问**
`_query_terms(q)` 返回 `(terms, require_all, min_or_hits)` 三元组。请说明它在**多词查询**与**单词查询**两种情况下分别怎么决定 `require_all`，以及 `min_or_hits` 的实际取值。

**参考答案要点**
**多词查询**（`search.py:140-153`）：

```python
	spaced = [w for w in q.split() if w]
	if len(spaced) > 1:
		# 多词：若几乎全是拉丁 → AND；含 CJK 块则拆开后 OR+门槛
		cjk_chunks = []
		latin_parts = []
		for w in spaced:
			cjk_chunks.extend(_cjk_ngrams(w))
			latin_parts.extend(_LATIN_TOKEN.findall(w))
			latin_parts.extend(_HANGUL_SYL.findall(w))
		if cjk_chunks or any(_HANGUL_SYL.search(w) for w in spaced):
			terms = list(dict.fromkeys(spaced + cjk_chunks + latin_parts))
			# 小库词法召回：OR 命中 1 个有信息 ngram 即可；排序靠 lexical 分
			return terms, False, 1
		return spaced, True, 1
```

| 情形 | terms | require_all |
|---|---|---|
| 多词 + 含 CJK 或 Hangul | 原词 + CJK 2/3-gram + 拉丁 token + Hangul 音节（去重、保持插入序） | **False**（OR） |
| 多词 + 纯拉丁 | 原词 | **True**（AND） |

**单词查询**（`:155-167`）：

```python
	blob = spaced[0] if spaced else q
	latin = _LATIN_TOKEN.findall(blob)
	hangul = _HANGUL_SYL.findall(blob)
	cjk = _cjk_ngrams(blob)
	compact = re.sub(r"\s+", "", blob)
	if latin and "".join(latin) == compact and not cjk and not hangul:
		return latin, True, 1

	terms: list[str] = [blob]
	for tok in cjk + hangul + latin:
		if tok not in terms:
			terms.append(tok)
	return terms, False, 1
```

单词又分两种：**纯拉丁且可完整切分**（`"".join(latin) == compact`，即该词全由字母数字下划线构成）→ `([latin], True, 1)`；否则（含 CJK/Hangul/其他字符）→ `([blob] + tokens, False, 1)`。

**`min_or_hits` 恒为 1**——四条返回路径全部是 `1`。它是一个**参数化的预留位**，注释解释了它的用途：「min_or_hits：OR 模式下至少命中几个 term（降低单 bigram 误召）」，但当前没有调用方传入别的值。

门槛的最终裁决在 `_matches`（`:174-189`）：

```python
	if q and (q in hay or q in index):
		return True
	if not terms:
		return False
	if require_all:
		return all(t in hay or t in index for t in terms)
	hits = sum(1 for t in terms if _term_hit(t, hay, index))
	return hits >= max(1, min_or_hits)
```

**三条优先规则**：①整个查询串 `q` 命中 → **直接 True**（绕过所有 term 逻辑）；②无 term → False；③`require_all` 用 `all`，否则计数与 `max(1, min_or_hits)` 比。

而 `_term_hit`（`:170-171`）有一条**长度闸**：

```python
def _term_hit(term: str, hay: str, index: str) -> bool:
	return len(term) >= 2 and (term in hay or term in index)
```

即**单字符 term 一律不算命中**——这是 OR 模式（门槛=1）不误召的关键防线；否则查询词里任何一个单字母都会让 OR 条件成立。

★ 还有一处**双平面匹配**：所有匹配都在 `hay`（note 打分平面，`_note_hay` 归一化 type/title/content/id，`:63-65`）**或** `index`（`MEMORY.md` 归一化文本，`:235-244`）上做。索引被纳入匹配面意味着：**索引里出现过的路径/标题也会被召回**——这是「note 本体丢了但索引还在」时的兜底召回能力。

**深化讲解**（面试官参考，不要求候选人全说）
「多词纯拉丁用 AND、含 CJK 用 OR+门槛」的取舍来自**分词可靠性差异**：

- 拉丁词天然有空格分隔，`all` 是合理的严格匹配；
- CJK 没有词边界，只能取 2/3-gram，而 n-gram 的**假阳性率高**（一个 bigram 可能出现在无关文本里），所以用 OR + 门槛 1 保证召回（宽进），把精度交给**排序**（`score_note`/`query_reweight_score`，见 0417）。

注释把这条思路写明了：「小库词法召回：OR 命中 1 个有信息 ngram 即可；排序靠 lexical 分」。



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

### XEYO-QA-0416 语料平面与三类分词

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | search 归一化与分词 | NFKC + 三类正则 | 中等 | 机制解释 | `python/memory/search.py:20,32-38,63-65,116-133` |

**面试官提问**
记忆检索的文本归一化怎么做？三类分词正则分别覆盖什么字符区间？CJK 的 n-gram 取了哪些 n？

**参考答案要点**
**归一化**（`search.py:116-117`）：

```python
def _normalize_query(q: str) -> str:
	return unicodedata.normalize("NFKC", (q or "").strip()).lower()
```

三步：`strip()` → **NFKC 归一化** → `lower()`。NFKC 会把兼容字符（全角字母数字、连字、罗马数字等）折成基本形式，这样「全角 `Ｍap`」与「半角 `map`」能被同一套 term 匹配到。

**三类分词正则**（`:32-38`）：

```python
_LATIN_TOKEN = re.compile(r"[a-z0-9_]+", re.I)
# CJK 统一表意 + 扩展 A + 平假名/片假名
_CJK_CHAR = re.compile(
	r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
	r"\u3040-\u309f\u30a0-\u30ff]"
)
_HANGUL_SYL = re.compile(r"[\uac00-\ud7a3]+")
```

| 正则 | 覆盖区间 | 说明 |
|---|---|---|
| `_LATIN_TOKEN` | `[a-z0-9_]`（`re.I`） | 拉丁字母、数字、下划线；**不含连字符/点**（所以 `my-file` 会切成 `my` 与 `file`） |
| `_CJK_CHAR` | `U+3400–4DBF`（扩展 A）、`U+4E00–9FFF`（基本区）、`U+F900–FAFF`（兼容表意）、`U+3040–309F`（平假名）、`U+30A0–30FF`（片假名） | 只**匹配单字符**（用 `findall` 抽成字符列表） |
| `_HANGUL_SYL` | `U+AC00–D7A3`（谚文音节） | 连续音节作为**一整块**取出 |

**CJK n-gram**（`:120-133`）：

```python
def _cjk_ngrams(text: str) -> list[str]:
	chars = _CJK_CHAR.findall(text)
	if not chars:
		return []
	out: list[str] = []
	for n in (2, 3):
		if len(chars) < n:
			continue
		for i in range(len(chars) - n + 1):
			gram = "".join(chars[i : i + n])
			if gram not in out:
				out.append(gram)
	return out
```

**取 n = 2 与 3 两档**，按 `(2, 3)` 顺序生成，用 `if gram not in out` 去重（保持插入序）。

★ 注意一个**跨标点拼接**的边界：`_CJK_CHAR.findall` 只抽 CJK 字符、**丢弃中间的标点与空格**，所以「中文，测试」会得到连续字符序列 `['中','文','测','试']` → n-gram 里会出现 `"文测"` 这个**跨越标点的假 bigram**。这是纯字符级分词的固有代价（换来的是不必引入分词器）。

**打分平面**（`_note_hay`，`:63-65`）：

```python
def _note_hay(note: MemoryNote) -> str:
	"""检索打分平面：type/title/content/id 归一化拼接。"""
	return _normalize_query(f"{note.type} {note.title} {note.content} {note.id}")
```

四个字段拼接后整体归一化——所以**note 的 `id` 也参与词法打分**（`mem_01J…` 这类 id 里的十六进制串理论上可能与查询词撞上，实际概率极低，但它确实是平面的一部分）。

**深化讲解**（面试官参考，不要求候选人全说）
本模块首行有一条**禁令**（`:1` 附近注释「禁止调模型」，并在 `:53-57` 重申「纯词法、无模型调用（满足本文件首行『禁止调模型』）」）。这决定了三处设计：①不用 embedding/rerank 模型；②分词只能靠正则；③排序只能靠词频与规则加权。

NFKC + lower 的组合是**双向一致**的：note 平面与查询词都过 `_normalize_query`（`_note_hay` 与 `_query_terms` 的调用方），所以比较是对称的。若只归一化一侧，全角/大小写差异会造成单向漏召。



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

### XEYO-QA-0417 近因加权与重排封顶

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | search 打分 | recency bonus 与 term cap | 中等 | 机制解释 | `python/memory/search.py:41-49,60,68-113` |

**面试官提问**
`_recency_bonus` 的两个档位是多少？`query_reweight_score` 的 `_QUERY_TERM_CAP` 解决什么问题？旧口径（`reweight=False`）有什么缺陷、是否已修？

**参考答案要点**
**近因加权两档**（`search.py:41-49`）：

```python
def _recency_bonus(note: MemoryNote) -> float:
	"""最近使用 / 确认的笔记略加权（同一天 +2，否则 0）。"""
	stamp = note.last_used_at or note.last_confirmed_at or note.updated_at
	if not stamp:
		return 0.0
	try:
		return 2.0 if str(stamp)[:10] == today_iso() else 0.5
	except Exception:
		return 0.0
```

时间戳取 `last_used_at or last_confirmed_at or updated_at`（三级回退）；**同一天 +2.0，其他情况 +0.5**，无时间戳 0.0。（docstring 写「否则 0」，实际是 `0.5`——**注释与实现不一致**，以代码为准。）

**重排封顶**（`:60,107-113`）：

```python
_QUERY_TERM_CAP = 3

def query_reweight_score(hay: str, terms: list[str]) -> float:
	"""F4 重排分：每个区分查询词的命中数封顶到 _QUERY_TERM_CAP，广度主导深度。
	返回封顶后的覆盖分；作者拿它替换 raw lexical（同 置信度 + 近因 组合）。"""
	distinct = {t for t in terms if len(t) >= 2}
	if not distinct:
		return 0.0
	return float(sum(min(hay.count(t), _QUERY_TERM_CAP) for t in distinct))
```

两点：①`distinct` 是**集合**（去重）且**过滤掉长度 < 2 的 term**（与 `_term_hit` 的长度闸呼应）；②每个 term 的命中数 `min(count, 3)` **封顶**，然后求和。

**它解决的问题**（`:52-57` 原文注释）：

```
# F4（v61采纳说明-V2）：查询感知重排（只为「排序」服务，绝不改召回集）。
# 现有词法分把「重复命中单一词」无限加分（depth），导致高频窄语义笔记压过
# 覆盖整条查询的笔记。重排把词频封顶，改为奖励「覆盖不同查询词」（breadth）。
# 纯词法、无模型调用（满足本文件首行「禁止调模型」）。**已固化开启**
# （原 XEYO_MEMORY_QUERY_REWEIGHT 键已删；召回集仍绝不改动）。
```

即：旧口径 `hay.count(q) + sum(hay.count(t) for t in terms)` 是 **depth 主导**——一篇反复出现同一个词的长笔记能压过一篇恰好覆盖全部查询词的短笔记。封顶后变成 **breadth 主导**。

**旧口径的缺陷是否已修**：旧口径仍在代码里（`reweight=False` 分支），但**已加固**（`:76-94`）：

```python
	"""单条 note 的词法分（与 ``search()`` 同口径；rerank_preference_shadow 叠加偏好分用）。

	双重计数修复：``terms`` 在单 blob 查询下首项就是 ``q`` 本身，旧实现
	``hay.count(q) + sum(hay.count(t) for t in terms)`` 把 q 计了两遍，
	高频查询词权重被放大——terms 求和时剔除与 q 相同的项。
	"""
	if hay is None:
		hay = _note_hay(note)
	if reweight is None:
		reweight = query_reweight_enabled()
	if reweight:
		return (
			query_reweight_score(hay, terms)
			+ float(note.confidence or 0.0)
			+ _recency_bonus(note)
		)
	lexical = float(hay.count(q)) if q else 0.0
	lexical += float(sum(hay.count(t) for t in terms if t != q))
	return lexical + float(note.confidence or 0.0) + _recency_bonus(note)
```

**双重计数修复**在旧分支的最后一行：`for t in terms if t != q`——剔除了与 `q` 相同的项（单 blob 查询下 `terms[0]` 就是 `q`）。

两条分支的**共同项**：`+ confidence + _recency_bonus`。

**`query_reweight_enabled` 恒真**（`:97-104`）：原键 `XEYO_MEMORY_QUERY_REWEIGHT` 已删，「回退只能改本函数源码」。

**深化讲解**（面试官参考，不要求候选人全说）
「把词频封顶」这个改动看似微小，但它改变的是**排序语义**：从「谁提这个关键词最多」变成「谁覆盖的查询词最多」。前者会让**长文档**系统性占优（长文自然词频高），后者才对应「这篇笔记是不是在讲我这次问的事」。

★ 一处必须注意的**内部矛盾**：注释说 F4「只为**排序**服务，**绝不改召回集**」，但 `query_reweight_score` 的结果在 `search()` 里被同时用于**打分**与**筛选**。具体见 0439（困难题），那里会论证为什么「不改召回集」靠的是排序前的一次筛选而不是打分函数本身。而在 `search_session_notes` / `search_rollout_summaries` 里，`score` 的用途更直接（`:408-411,513-515`）。



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

### XEYO-QA-0418 指令加载的缓存键与签名

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | instruction 嵌套指令 | 缓存键与双签名 | 中等 | 机制解释 | `python/memory/instruction.py:28-62,288-323` |

**面试官提问**
`load_instruction_text(cwd, workspace_root)` 的缓存键是什么？为什么要维护**两个**签名（top 与 full）？预算怎么定？

**参考答案要点**
**缓存键**（`:339`）：

```python
	key = (str(cwd), str(workspace_root), budget)
```

三元组：`cwd`、`workspace_root`、`budget`（`:334-343`）。缓存结构声明在 `:39-42`：

```python
	# 入参 (cwd, workspace_root, budget)，返回 (top_sig, full_sig, text)
_CACHE: dict[
	tuple[str, str, int],
	tuple[tuple[tuple[str, int, int], ...], tuple[tuple[str, int, int], ...], str],
] = {}
```

**两个签名**：`top_sig` 覆盖 `_discover_paths` 顶层发现的文件，`full_sig` 覆盖**含 `@include` 展开后**的全部文件（`:335-353`）：

```python
	home = xeyo_home()
	discovered = _discover_paths(cwd, workspace_root)
	top_sig = _signature(discovered)
	budget = instruction_char_budget()
	key = (str(cwd), str(workspace_root), budget)
	cached = _CACHE.get(key)
	...
		full_paths = {Path(p) for p, _m, _s in cached_full}
```

`_signature` 的形态（`:288-300`）是 `tuple[(path, mtime, size), ...]`——即**用 (mtime, size) 作为内容指纹**，而不是读全文算哈希。

「top 用于**快速判定是否要重建**（一次 `listdir`+`stat` 就够），full 用于**判断缓存内容是否仍然完整**（因为 `@include` 展开的文件可能变，而顶层文件没变）」。这是一处典型的**两级失效**设计：廉价签名做门，昂贵签名做校验。

**预算**（`:23-36`）：

```python
MAX_CHARS = 40_000  # 硬顶安全阀
MAX_INCLUDE_DEPTH = 5
_DEFAULT_SOFT_CHARS = 8_000

def instruction_char_budget() -> int:
	"""常驻左段实际拼接预算（默认软上限 8k，省钱）；硬顶仍为 MAX_CHARS。"""
	raw = os.environ.get("XEYO_INSTRUCTION_BUDGET", "").strip()
	if raw:
		try:
			return max(256, min(MAX_CHARS, int(raw)))
		except ValueError:
			pass
	return min(MAX_CHARS, _DEFAULT_SOFT_CHARS)
```

三级：环境变量 `XEYO_INSTRUCTION_BUDGET` → **夹到 `[256, 40_000]`**；未设或非法 → `min(40_000, 8_000) = 8_000`。

**拼接与截断顺序**（`:360-380`）：先拼 `core`（常驻），再用 `scoped`（作用域匹配的）填剩余预算，最后整体 `text[:budget]` 兜底截断。

**深化讲解**（面试官参考，不要求候选人全说）
★ 注意这里**读了环境变量**（`XEYO_INSTRUCTION_BUDGET`），与 `memory_switches` 的「env 不参与」纪律形成对比。理由：这是 **L1 指令装配层**的预算（对应 Prompt 装配），不是「记忆系统开关」——`memory_switches` 只管注册表里的四个键。两者是不同治理面，不要相互套用口径。`xeyo_home()` 同样读 `XEYO_HOME`（`:56-61`），供测试隔离。

**为什么 L1 指令必须缓存**：指令文本会被嵌进 **system 左段**（最贵的 KV 前缀区）。若每轮重新读文件并拼接，①产生大量 `stat`/读盘；②更严重的是**只要拼接结果有一个字节不同，整段 system 前缀就 miss**。所以缓存 + 签名门是「成本」与「字节稳定」的双重要求。

`clear_instruction_cache()`（`:45-47`）的注释给出了清理时机：「compact 后、或指令文件被显式修改后调用」——即两个**已知会改变内容**的事件。



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

### XEYO-QA-0419 `@include` 的三道闸

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | instruction include 展开 | 深度/环/路径三道闸 | 中等 | 机制解释 | `python/memory/instruction.py:21-25,194-224` |

**面试官提问**
`@include` 指令在展开时受哪些限制？循环引用怎么处理？

**参考答案要点**
三道闸 + 一条容错，全部在 `_expand_includes`（`instruction.py:194-224`）：

```python
	rel = match.group(1).strip().strip("\"'")
	target = (base / rel).resolve()
	key = str(target)
	...
	try:
		body = target.read_text(encoding="utf-8")
```

| 闸 | 常量/机制 | 位置 |
|---|---|---|
| 深度 | `MAX_INCLUDE_DEPTH = 5`（`:24`），`depth` 参数递增 | `:195-199` 签名带 `depth` |
| 环 | `seen: set[str]`——**解析后的绝对路径字符串**作键 | `:198,208` |
| 存在性/可读性 | `read_text` 的 `OSError` 被 `try/except` 吞掉（静默跳过） | `:216-217` |
| 字符总量 | 展开后的文本仍受 `join_with_caps` 与最终 `text[:budget]` 约束 | `:175-182,380` |

`INCLUDE_RE = re.compile(r"^@include\s+(\S+)\s*$", re.MULTILINE)`（`:21`）——匹配**整行**的 `@include <path>`；`match.group(1).strip().strip("\"'")` 允许路径带引号（`:206`）。

**环检测的关键是先 resolve 再作键**（`:207-208`）：`target = (base / rel).resolve()` 然后 `key = str(target)`。这保证 `./a.md`、`a.md`、`../dir/a.md` 三种写法指向同一文件时被识别为同一个 key——若用原始相对路径作键，**同一个文件通过不同相对路径即可绕过环检测**。

**相对基准是「当前文件所在目录」**（`base`），不是 cwd——`target = (base / rel)`。所以 `@include` 是**相对当前被包含文件**解析的，这让指令文件可以自包含成一个小树。

**深化讲解**（面试官参考，不要求候选人全说）
三个常量放在文件顶部（`:21-25`）构成一套**嵌套指令的安全参数**：

```python
INCLUDE_RE = re.compile(r"^@include\s+(\S+)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
MAX_CHARS = 40_000  # 硬顶安全阀
MAX_INCLUDE_DEPTH = 5
_DEFAULT_SOFT_CHARS = 8_000
```

`MAX_CHARS` 的注释写的是「**硬顶安全阀**」——即它主要防的是**恶意/失控的指令文件把 system 左段撑爆**。深度 5 + 环检测 + 硬顶 40k 三者是**互补的**：深度防「链式展开过深」，环防「A→B→A」，硬顶防「宽扇出」（一个文件 include 20 个文件，每个都不深、也不成环）。

★ 另有一个**未在本文件加固的边界**：`_expand_includes` 没有**工作区边界检查**——`@include ../../../../etc/passwd` 会解析到工作区外的路径并读取（只要进程有读权限）。这是本批的**待确认项之一**：需确认上层（Prompt 装配或权限层）是否有拦截，或这是否属于「指令文件本身就是受信任输入」的既定前提。



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

### XEYO-QA-0420 `paths` frontmatter 的作用域匹配

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | instruction 作用域指令 | 三态 paths 与匹配规则 | 中等 | 机制解释 | `python/memory/instruction.py:64-134` |

**面试官提问**
指令文件的 frontmatter 里可以写 `paths`。它有三种形态，分别是什么语义？匹配怎么做的？

**参考答案要点**
**三态语义**（`instruction.py:64-71` docstring 原文）：

```python
def split_paths_frontmatter(text: str) -> tuple[list[str] | None, str]:
    """解析可选 YAML-ish frontmatter 的 paths。

    返回 ``(paths, body)``：
    - paths is None：无 frontmatter，body 为原文；
    - paths == []：有 frontmatter 但无 paths 键 → 视为常驻；
    - paths 非空：仅匹配时注入 body。
    """
```

| 返回 | 含义 |
|---|---|
| `None` | 无 frontmatter → 整篇是正文（常驻） |
| `[]` | **有** frontmatter 但没写 `paths` 键 → 视为**常驻** |
| 非空 list | 仅当 cwd 命中某个 glob 时才注入 |

★ `None` 与 `[]` 的区别只在**解析来源**上，效果相同（都常驻）——这是「显式空 = 常驻」的约定，避免「写了 frontmatter 就默认不注入」的意外。

**匹配规则**（`paths_match_cwd`，`:105-134`）：

```python
        focus = Path(cwd).expanduser().resolve()
        root = Path(workspace_root).expanduser().resolve()
        try:
            rel = focus.relative_to(root).as_posix()
        except ValueError:
            rel = focus.name
        focus_posix = focus.as_posix()
        for g in paths:
            pat = (g or "").strip().replace("\\", "/")
            ...
            prefix = pat[:-3].rstrip("/")     # 去掉 "/**"
            ...
            prefix = pat[:-5].rstrip("/")     # 去掉 "/**/*"
```

三点：①cwd 被**转成相对 workspace root 的 POSIX 形式**（`rel`），跨盘/越界时退化用 `focus.name`；②每个 glob 的**反斜杠统一成 `/`**；③对 `/**` 与 `/**/*` 两种后缀做**前缀剥除**（`pat[:-3]` / `pat[:-5]`），所以 `docs/**` 与 `docs/**/*` 都退化成前缀 `docs` 再比较——这是**前缀匹配而非完整 glob 匹配**的实现方式。

**拼接顺序**（`:360-380`）：`core`（常驻类，含无 paths 与空 paths）先、`scoped`（命中 paths 的）后，core 用满预算后 scoped 拿剩余预算。

**深化讲解**（面试官参考，不要求候选人全说）
★ 与 0418 的双签名直接呼应：**scoped 指令会随 cwd 变化**（同一会话内 cwd 可能变，或不同会话 cwd 不同），所以 `_discover_paths` 的结果必须按 `(cwd, workspace_root, budget)` 三元组缓存，而不能只按 workspace 缓存。

`rel` 的退化分支（`except ValueError: rel = focus.name`）是一个**方向安全**选择：当 cwd 不在 workspace root 下时，用目录名（而不是绝对路径）去匹配，这样 `paths: ["docs/**"]` 仍可能命中一个位于工作区外的 `docs` 目录——**可能是过度包含**，但不会漏掉用户以为该生效的规则。这是「宁可多加、不可漏加」的取舍（对指令而言，多注入一段规则比少注入安全）。

**边界**：前缀剥除意味着**不支持任意 glob**。例如 `paths: ["src/*/test/**"]` 会被 `pat[:-3]` 处理成 `src/*/test` 前缀——中间的 `*` 不会被展开，所以匹配退化为「相对路径是否以字符串 `src/*/test` 开头」，几乎不可能命中。也就是说 `paths` 的**实际能力面是「目录前缀」**，不是通用 glob。



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

### XEYO-QA-0421 journal 的序号、锁与索引分层

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | journal 行为日志 | seq 分配与两级存储 | 中等 | 机制解释 | `python/memory/journal.py:32-44,50-62,140-238` |

**面试官提问**
`journal.record_change` 怎么分配 `seq`？并发怎么保证？为什么同时写 journal 与 index 两个文件？

**参考答案要点**
**seq 分配**（`journal.py:164-169`）：

```python
def _record_change_locked(workspace_id: str, rec: ChangeRecord, path: Path) -> int:
    rec.seq = _tail_seq(path)
    row = _to_dict(rec)
    _append_row(path, row)
    _append_row(_index_path(workspace_id), _index_marker(row))
    return rec.seq
```

`_tail_seq(path)`（`:120-138` 附近）读文件**最后一行**并从中取 seq——所以新 seq 是「尾部 seq」而非「尾部 seq + 1」（注释说明「全局单调序号（journal 内部分配，供审计/追溯）」，`:34`）。`_append_row` 用 `json.dumps(..., separators=(",", ":"))` 写单行 JSONL（`:64-73`）。

**并发保护的**两级（`record_change`，`:140-161`）：

```python
    if workspace_lock is not None:
        with workspace_lock:  # type: ignore[attr-defined]
            return _record_change_locked(workspace_id, rec, path)

    # 跨进程依赖 O_APPEND 单次追加的原子性；同进程内仍加锁。
    with _lock_for(path):
        return _record_change_locked(workspace_id, rec, path)
```

| 层 | 机制 | 覆盖面 |
|---|---|---|
| 进程内 | `_lock_for(path)` —— 每文件一个 `threading.RLock`（`:50-62` 的 `_LOCKS` + `_LOCKS_GUARD`） | 同进程多线程 |
| 跨进程 | 传入 `workspace_lock`（如 `engine.workspace_lock.WorkspaceLock` 的 `hold` 上下文管理器） | 多进程强互斥 |
| 缺省（无 `workspace_lock`） | **只依赖 `O_APPEND` 单次追加的原子性** | 尽力而为 |

**为什么要写两个文件**（`:168-174`）：

```python
    _append_row(_index_path(workspace_id), _index_marker(row))
...
def _index_marker(row: dict[str, Any]) -> dict[str, Any]:
    """索引行 = journal 行的紧凑副本（保留全部字段以便脱离 journal 物化）。"""
    return dict(row)
```

索引行是 journal 行的**完整副本**（`dict(row)`），注释写明理由「保留全部字段以便**脱离 journal 物化**」——即 index 必须**自足**。配套的 `rebuild_index`（`:212-238`）能在 index 损坏/落后时从 journal 重建，而 `_journal_fresh`（`:202-210`）用 watermark 判断 index 是否跟上（`_index_watermark` 取 index 里最大 seq，`:180-187`）。

**深化讲解**（面试官参考，不要求候选人全说）
「journal 为权威、index 为派生」与 `memindex` 的「文件为权威、sqlite 为派生」（见 0422）是**同一个模式**在两条链上的复用：追加写的日志永不重写（便宜、可追溯），而查询用的结构单独维护并可从日志重建（贵、可丢）。

★ 跨进程那条路的诚实之处在于**把依赖写在注释里**：「跨进程依赖 `O_APPEND` 单次追加的原子性」——`O_APPEND` 保证「写指针定位 + 写」是原子的（POSIX），所以小行的追加不会互相覆盖；但**它不保证 seq 唯一**（两个进程可能同时读到同一个尾部 seq）。传 `workspace_lock` 才能得到「真正单调不重复的 seq」（注释：「写者在多进程竞争下得到绝对单调 seq」）。这是一条**显式声明的降级**，不是隐性缺陷。



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

### XEYO-QA-0422 `memindex` 的三张表与六条要点

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memindex sqlite 派生索引 | 表结构与 schema | 中等 | 机制解释 | `python/memory/memindex.py:1-19,31-80` |

**面试官提问**
`memindex` 的 sqlite 库里有哪几张表？各自的用途与主键是什么？库文件放在哪里？

**参考答案要点**
**四张表 + 一条索引**（`memindex.py:38-80` 的 `_SCHEMA_SQL`）：

| 表 | 主键 | 列 | 职责 |
|---|---|---|---|
| `meta` | `k` | `k`, `v` | 存 `schema_version` |
| `notes` | `(domain, path)` | `mtime`, `size`, `sha`, `fm_json`, `body` | 签名缓存（A4 第一步） |
| `rollouts` | `(domain, path)` | `mtime`, `size`, `raw` | rollout 原文缓存 |
| `fragments` | `(session_id, msg_index, kind, seq)` | `text`, `sha`, `created_at` | C2 压缩碎片还原（A2） |
| `edges` | `(session_id, from_msg, to_msg, kind)` | `created_at` | 因果边（C1 地基） |
| `idx_fragments_session` | — | `(session_id, msg_index)` | fragment 查询索引 |

**库文件路径**（`:98-102`）：

```python
def db_path(domain: str) -> Path:
    """库文件：``<memdir 根>/<domain>/index.sqlite3``（与 memdir 同域隔离）。"""
    from memory.memdir import memdir_root

    return memdir_root(domain) / "index.sqlite3"
```

即 `~/.xeyo/memory/{domain}/index.sqlite3`——**每个域一个库**，`domain` 就是 workspace_id（或 `user`，见 0428）。

**连接设置**（`:105-112`）：

```python
def _connect(domain: str) -> sqlite3.Connection:
    path = db_path(domain)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=2.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=2000")
    conn.executescript(_SCHEMA_SQL)
    return conn
```

三处：`timeout=2.0`、**WAL 日志模式**、`busy_timeout=2000`——都是为「多读少写、偶发并发」调优的；`executescript(_SCHEMA_SQL)` 用的是 `CREATE TABLE IF NOT EXISTS`（`:39,43,53,61,71`）与 `CREATE INDEX IF NOT EXISTS`（`:79`），所以每次连接都会**幂等地**建表。

**六条设计要点**（模块 docstring，`:1-19`）——这是本题最该记住的部分：

1. **定位铁律**：sqlite 只是派生索引/缓存；**文件永远是 source of truth**；「库可随时删除并全量重建，零数据丢失风险」；
2. notes/rollouts 走**按 `(mtime, size)` 签名的懒同步**，「查询不再每次全量读+解析所有 md 文件」；任何 sqlite 异常由调用方 **fail-open 回退文件扫描**（「P0 词法召回永不回归」）；
3. **评分逻辑不变**：仍用 `memory/search.py` 的 Python 词法评分（sqlite 只负责「拿到 note 列表」，不负责排序）；
4. fragments 存的是「C2 压缩时把左区被折叠的**结构化原子**（stack/kv/path/json/tree/table）」按 `notes:msg:<绝对下标>` 存全文；
5. **「转录是最终真相，fragments 只是压缩时点的抓拍」**；
6. edges 是「C1 地基」，本轮「**只建表+写入**」（不做钻取）。

**深化讲解**（面试官参考，不要求候选人全说）
「库只是派生」这条铁律决定了三处实现细节：①失败一律不抛（`upsert_note_file` / `store_fragments` / `add_edges` 全部 `try/except` 静默）；②`rebuild(domain)` 存在且是**一等操作**（`:274-286`，先 `DELETE` 再懒同步）；③调用方（`memdir.load_notes`）用 `try/except` 包住整条 sqlite 路径并**回退到纯文件扫描**（`memdir.py:339-356`）。

这样设计的结果是：**sqlite 坏了 → 性能退化，功能不退化**。对一个「记忆检索」这种 P0 能力来说，这是正确的失效方向。



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

### XEYO-QA-0423 签名缓存与 write-through

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memindex 同步策略 | (mtime,size) 懒同步 | 中等 | 机制解释 | `python/memory/memindex.py:127-192,214-271` |

**面试官提问**
`_sync_table` 怎么判断一个文件要不要重读？「坏文件」怎么处理？`upsert_note_file` 是什么策略、失败会怎样？

**参考答案要点**
**判据是 `(mtime, size)` 签名**（`memindex.py:151-160`）：

```python
    """按 (mtime, size) 签名把目录同步进 db：只重新读取变化的文件。"""
    entries = _dir_entries(directory)
    with _connect(domain) as conn:
        cur = conn.execute(
            f"SELECT path, mtime, size FROM {table} WHERE domain = ?", (domain,)
        )
        known = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        for name, (mtime, size) in entries.items():
            if known.get(name) == (mtime, size):
                continue
            full = directory / name
            loaded = loader(full)
```

`known.get(name) == (mtime, size)` 相等即跳过——**签名相同就不重读**。`_dir_entries`（`:127-141`）用 `os.scandir` + `ent.stat()` 拿 `(st_mtime, st_size)`。

**坏文件处理**（`:162-168`）：

```python
            if loaded is None:
                # 解析失败（如坏 frontmatter）→ 与文件扫描语义一致：不入库（跳过）
                conn.execute(
                    f"DELETE FROM {table} WHERE domain = ? AND path = ?", (domain, name)
                )
                continue
```

`loader` 返回 `None` 时**主动 DELETE 该行**——这保证「文件坏掉后，缓存里不会留旧的好版本」；语义与文件扫描（跳过坏文件）一致。

**双向同步**（`:184-188`）：

```python
        for name in known:
            if name not in entries:
                conn.execute(
                    f"DELETE FROM {table} WHERE domain = ? AND path = ?", (domain, name)
                )
```

**文件被删 → 行被删**。所以三件事都做了：新增/变化 → 重读入库；解析失败 → 删行；文件消失 → 删行。

**write-through**（`:258-271`）：

```python
def upsert_note_file(domain: str, path: Path) -> None:
    """write-through：write_note 落盘后立即同步单文件（尽力而为，失败静默）。"""
    try:
        _sync_table(domain, "notes", path.parent, loader=_load_note_file)
    except Exception:  # noqa: BLE001 — write-through 不阻塞写路径
        pass
```

调用点在 `memdir.write_note`（`memdir.py:372-378`）与 `session_md.archive_session_rollout`（`session_md.py:125-131`）。**失败静默**——注释写明「write-through 不阻塞写路径」。

★ 注意 `upsert_note_file` 传的是 `path.parent`，即**它同步的是整个目录**（虽然名义上是「单文件」）。所以一次写入会触发该目录内所有文件的签名比对——成本是 O(目录内文件数) 次 `stat`，而不是 O(1)。对 `topics/` 这种可能上百文件的目录，这是**每次 write_note 都要付的固定开销**。

**深化讲解**（面试官参考，不要求候选人全说）
「签名 = (mtime, size)」是一个刻意的**廉价近似**：它不做内容哈希（省一次全文读），代价是「同秒内被改成同样大小的文件」不会被发现。对这个用途（缓存 note 列表）是可接受的——因为：

1. 数据源是 `topics/*.md`，**只由本系统写入**（`write_note` 是唯一写点），而 `write_note` 会立刻 write-through；
2. `sqlite` 只是派生层，最坏情况是「返回旧版 note」——而 `load_notes_cached` 之后还会跑 `parse_and_validate`（`:236`），坏 frontmatter 仍会被跳过。

与 B04 里 `ReadFileState` 的 mtime 判据（`fileio/text.py:17-19`）是**同一类近似**，但风险面小得多：那里的判据会决定是否拦截/放行写入，这里只决定是否重读缓存。



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

### XEYO-QA-0424 fragment 与 retrieve 的能力边界

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memindex 压缩碎片 | 两条上限与容量语义 | 中等 | 机制解释 | `python/memory/memindex.py:31-34,293-346` |

**面试官提问**
`store_fragments` 的两条上限是什么？为什么说「fragments 只是压缩时点的抓拍」？超过上限时会发生什么？

**参考答案要点**
**两条上限**（`memindex.py:31-34`）：

```python
#: 每次压缩最多入库的结构化原子条数（防天量 tool_result 撑爆库）。
FRAGMENT_ROW_CAP = 400
#: 单条 fragment 正文上限（字节级还原的截断线，超出说明不该靠 retrieve 而该靠工具重跑）。
FRAGMENT_TEXT_CAP = 4096
```

| 常量 | 值 | 语义 | 超限处置 |
|---|---|---|---|
| `FRAGMENT_ROW_CAP` | 400 | 每次压缩最多入库条数 | **切片丢弃**：`for row in rows[:FRAGMENT_ROW_CAP]`（`:305`） |
| `FRAGMENT_TEXT_CAP` | 4096 | 单条正文上限 | **静默截断**：`text = str(row.get("text") or "")[:FRAGMENT_TEXT_CAP]`（`:310`） |

**「抓拍」的含义**（模块 docstring `:8-13`，原文）：

```
2. fragments（A2 retrieve 还原）：C2 压缩时把左区被折叠的**结构化原子**（stack/kv/path/
   json/tree/table）按 ``notes:msg:<绝对下标>`` 存全文；Memory(action=retrieve) 按锚点 id
   字节级找回。转录是最终真相，fragments 只是压缩时点的抓拍。
```

「抓拍」有两层意思：①**时点**——它记录的是「压缩那一刻」的文本，此后转录可能被追加/回滚，而 fragment 不会跟着变；②**内容**——存的是**已经过截断（4096）**的文本，所以「字节级找回」只在 `≤ 4096` 的前提下成立。

**其余入库规则**（`:302-323`）：`session_id` 为空或 `rows` 为空 → 返回 0；逐行 `int()` 解析失败 → `continue`；`text.strip()` 为空 → `continue`；写入用 `INSERT OR REPLACE`（同 `(session_id, msg_index, kind, seq)` 重复时覆盖）；`sha` 是 `_sha(text)`（sha256 前 32 位，`:119-120`）；`created_at` 是 UTC ISO（`_now_iso`，`:115-116`，`timespec="seconds"`）。

**整段被 `try/except` 包住**（`:303-323`）：异常时返回**已入库条数**（不是 0，也不是抛错）——注释：「失败静默（还原是增强项，绝不阻塞压缩热路径）」。

**取回**（`get_fragments`，`:326-346`）：按 `session_id + msg_index`（可选 `kind`）查询，`ORDER BY kind, seq`，返回 `[{"kind","seq","text"}]`；**任何异常返回 `[]`**。

**fragment 存在哪个库**：`_domain_for_sessions()`（`:349-357`）——「跟随当前工作区 memdir（与 L4 同域）」，即 `workspace_id(get_cwd())`；离线/测试环境回退固定域 `"offline"`。

**深化讲解**（面试官参考，不要求候选人全说）
「抓拍而非真相」这个定位决定了**两条上限的合理性**：既然它只是压缩点的快照，那么①条数不必无限（真的需要全文，就应该**重跑工具**——`FRAGMENT_TEXT_CAP` 的注释把这条思路直接写出来了：「超出说明不该靠 retrieve 而该靠工具重跑」）；②截断造成的失真可接受（快照本来就不是权威）。

★ 与 B04 的 spill（`tools/spill.py`）对比可以看出**两种「落盘」的不同定位**：

| | fragment（memindex） | spill（tools） |
|---|---|---|
| 落盘时机 | C2 压缩时 | 工具结果超预算时 |
| 权威性 | 抓拍（转录才是真相） | 证据（「宁可超预算，不可假证据」，`spill.py:11-12`） |
| 上限 | 400 条 / 4096 字符（**截断**） | 无条数上限；保留 7 天 |
| 取回工具 | `Memory(action=retrieve)` | `Read` / `offload_read` |
| 失败取向 | 静默（增强项） | 落盘失败则**原样返回不截断**（`tool_registry.py:208-209`） |



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
### XEYO-QA-0425 citation 锚点的行号来源

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memdir/citation 引用锚点 | 正文行区间 | 中等 | 机制解释 | `python/memory/memdir.py:259-296` + `python/memory/search.py:192-204` |

**面试官提问**
`note_location(note, wsid)` 返回什么？行号具体怎么算出来？什么情况下行号是 `None`？

**参考答案要点**
返回 `(相对路径, 起始行, 结束行)`（**1-based 闭区间**）。实现（`memdir.py:259-289`，原文）：

```python
def note_location(note: MemoryNote, wsid: str) -> tuple[str, int | None, int | None]:
    """note 正文的引用定位：返回 (相对路径, 起始行, 结束行)（1-based 闭区间）。

    行号取 frontmatter 结束后的正文首/末非空行；文件缺失或 frontmatter 不规整
    时行号返回 None（只给路径）。供 citation 检索锚点使用，纯读无副作用。
    """
    rel = f"notes/topics/{topic_filename(note)}"
    path = note_topics_path(note, wsid)
    if not path.is_file():
        return rel, None, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rel, None, None
    close = None
    if lines and lines[0].lstrip().startswith("---"):
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                close = idx
                break
    if close is None:
        return rel, None, None
    start = close + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines):
        return rel, None, None
    end = len(lines) - 1
    while end > start and not lines[end].strip():
        end -= 1
    return rel, start + 1, end + 1
```

**算法四步**：

1. **找 frontmatter 结束行**：首行 `lstrip().startswith("---")` 才认；从第 1 行起找第一个 `strip() == "---"` 的行，记为 `close`（0-based 索引）。找不到 → `(rel, None, None)`。
2. **正文起点**：`start = close + 1`，然后**跳过空行**（`while not lines[start].strip(): start += 1`）。
3. **正文终点**：从最后一行（`len(lines) - 1`）往回**跳过空行**。
4. **转 1-based**：返回 `start + 1, end + 1`。

**五种返回 `None` 行号的情形**：文件不存在；读失败（`OSError`）；首行不是 `---`；找不到第二个 `---`；正文起点超过文件长度。

**路径用的是相对形式**（`:265`）：`f"notes/topics/{topic_filename(note)}"`——注意前缀是 **`notes/topics/`**，而磁盘路径是 **`{memdir_root}/topics/`**（`note_topics_path`，`:254-256`）。也就是说**引用里的 `notes/` 是一个纯粹的逻辑前缀**，磁盘上并没有 `notes/` 这一层。这一层别名由 `citation` 模块统一处理（`search.py:198-203` import 的 `note_file_citation` / `render_block` / `block_for_entries` / `rollout_id_from_source`）。

**消费方**（`search.py:192-204`，`note_citation_text`）：

```python
	"""检索命中的引用块（``<citation_entries>``+``<rollout_ids>``）或空串。

	条目：notes/topics/<slug>.md:行区间|note=[title]；rollout_ids 取 source.session_id。
	供 Memory(action=search) 展示时把命中锚定到 memdir note 文件与来源会话。
	"""
```

**深化讲解**（面试官参考，不要求候选人全说）
这件事的用途是**把「模型看到的检索片段」锚定回磁盘上的确切位置**，让模型（或用户）能 `Read` 到原文核对。行号取「正文首/末非空行」而不是「整个文件的行区间」，是因为：**frontmatter 是机器元数据**（`note_to_frontmatter` 的十几个字段，`governance.py:247-264`），把它算进引用区间只会让锚点变模糊。用户/模型关心的是**正文那几行事实**。

★ 一个实现细节：行区间是**首尾非空行**，所以正文中间的空行**在区间内**，而首尾的空行**不在**。这意味着 `Read` 出来的片段可能首尾都有富余（因为 `Read` 按行读，不会自动剥空行）——但区间本身是精确的。

**边界**：`note_location` 是**纯读**（docstring 明确「纯读无副作用」）——与 `search()` 里的 `touch_last_used`（会写回 `last_used_at`，`memdir.py:394-400`）形成对照。检索会把命中锚点渲染出来，但**只有 `search()` 的 `touch=True` 才会写盘**（`search.py:220` 的 `touch: bool = True`）。



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

### XEYO-QA-0426 晋升闸的完整证据集

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | governance 晋升闸 | `can_promote` 六条通道 | 中等 | 机制解释 | `python/memory/governance.py:14-18,146-180` |

**面试官提问**
`can_promote(candidate)` 允许晋升的完整条件是什么？哪一条被**明确禁止**？

**参考答案要点**
六条放行通道 + 一条明确禁止（`governance.py:146-180`）：

```python
def can_promote(candidate: MemoryCandidate) -> bool:
	"""是否允许晋升为 active。

	闸门：用户确认 / 可核对事实 / 多 session 无冲突 / 控制面 /
	agent|主会话收割标记（置信度封顶，见 ``promotion_confidence``）/
	工作区改动 diff 佐证（``verified_by_diff``：仅 NightShift 对照真实 git 改动
	打标后生效，见 memory.workspace_diff —— P3，纯证据通道不放开既有门禁）。
	禁止仅因 repeat* 重复出现。
	"""
	kind = ""
	if isinstance(candidate.source, dict):
		kind = str(candidate.source.get("kind") or "")
	evidence = list(candidate.evidence or [])
	if kind == "user":
		return True
	if "user_confirm" in evidence or "control_plane" in evidence:
		return True
	if "verified_fact" in evidence:
		return True
	# P3：改动 diff 佐证 —— 先由 NightShift 对照真实工作区改动打标，这里才放行。
	if "verified_by_diff" in evidence:
		return True
	if any(e in AGENT_HARVEST_EVIDENCE for e in evidence):
		return True
	if kind == "agent" and any(
		e in AGENT_HARVEST_EVIDENCE or e.startswith("session:") for e in evidence
	):
		return True
	sessions = {e for e in evidence if e.startswith("session:")}
	if len(sessions) >= 2 and "no_conflict" in evidence:
		return True
	# 仅重复出现不得晋升
	if evidence and all(e.startswith("repeat") for e in evidence):
		return False
	return False
```

| # | 通道 | 判据 |
|---|---|---|
| 1 | 用户确认（source） | `source.kind == "user"` |
| 2 | 用户确认 / 控制面（证据） | `evidence` 含 `"user_confirm"` 或 `"control_plane"` |
| 3 | 可核对事实 | `evidence` 含 `"verified_fact"` |
| 4 | 改动 diff 佐证（P3） | `evidence` 含 `"verified_by_diff"` |
| 5 | 收割标记 | `evidence` 含任一 `AGENT_HARVEST_EVIDENCE` 成员 |
| 6 | agent 收割 + 会话证据 | `kind == "agent"` 且 evidence 含收割标记**或** `session:` 前缀项 |
| 7 | 多会话无冲突 | evidence 里 `session:` 前缀的**去重集合 ≥ 2** 且含 `"no_conflict"` |

`AGENT_HARVEST_EVIDENCE`（`:14-18`）：

```python
# Agent / 主会话收割证据：允许晋升，但置信度封顶（见 promotion_confidence）
AGENT_HARVEST_EVIDENCE = frozenset(
	{"subagent_marker", "main_harvest", "agent_harvest"}
)
```

**明确禁止**（`:177-179`）：

```python
	# 仅重复出现不得晋升
	if evidence and all(e.startswith("repeat") for e in evidence):
		return False
```

即：**「出现过很多次」本身不构成晋升理由**（`repeat*` 前缀的 evidence 全部被排除）。注意这条判据在**所有放行通道之后**——但因为它只在「全部 evidence 都是 repeat」时才生效，而前面的通道要求存在特定 evidence，所以实际上「全是 repeat」的候选必然没命中任何通道 → 无论有没有这一行都会返回最后的 `False`。这一行是**把结论显式化**（防未来有人在前面加通道时破坏这条纪律）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于理解「**晋升 = 从候选变成模型可见的长期事实**」这个动作需要什么级别的证据。七条通道的共同点是**都指向外部权威**：

| 权威 | 通道 |
|---|---|
| 用户 | 1、2 |
| 可核对的客观事实 | 3、4（diff 对照真实 git 改动） |
| 受控流程（子 agent / 主会话收割） | 5、6 |
| 跨会话一致性 | 7 |

而**没有**一条通道是「模型自己觉得重要」。`repeat*` 被点名禁止，正是这条原则的反面：重复出现只是**统计特征**，不构成事实依据。

★ `verified_by_diff` 的注释特别值得记：「仅 NightShift 对照真实 git 改动打标后生效，见 `memory.workspace_diff` —— **P3，纯证据通道不放开既有门禁**」——即新增一条证据通道时**只加证据，不动既有闸门条件**，这是「新功能先旁路验证」规矩在治理层的体现。



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

### XEYO-QA-0427 晋升置信度的三档

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | governance 置信度 | 三档封顶 | 中等 | 机制解释 | `python/memory/governance.py:14-18,183-199` |

**面试官提问**
`promotion_confidence(candidate)` 的三个档位各是多少？分别对应什么证据？为什么要有封顶？

**参考答案要点**
`governance.py:183-199`（原文）：

```python
def promotion_confidence(candidate: MemoryCandidate) -> float:
	"""晋升写入时的置信度：用户/确认=1.0；agent 收割封顶 0.6；diff 佐证 0.85。"""
	kind = ""
	if isinstance(candidate.source, dict):
		kind = str(candidate.source.get("kind") or "")
	evidence = list(candidate.evidence or [])
	if kind == "user" or "user_confirm" in evidence or "control_plane" in evidence:
		return 1.0
	if "verified_fact" in evidence or "verified_by_diff" in evidence:
		return 0.85
	if any(e in AGENT_HARVEST_EVIDENCE for e in evidence) or kind in {
		"agent",
		"inference",
		"nightshift",
	}:
		return AGENT_PROMOTE_CONFIDENCE
	return AGENT_PROMOTE_CONFIDENCE
```

| 档 | 值 | 判据 |
|---|---|---|
| 1.0 | **1.0** | `kind == "user"` 或 evidence 含 `user_confirm` / `control_plane` |
| 0.85 | **0.85** | evidence 含 `verified_fact` 或 `verified_by_diff` |
| 0.6 | `AGENT_PROMOTE_CONFIDENCE` | evidence 含收割标记，或 `kind ∈ {agent, inference, nightshift}` |
| 兜底 | `AGENT_PROMOTE_CONFIDENCE`（= **0.6**） | 其余（含空 evidence、未知 kind） |

`AGENT_PROMOTE_CONFIDENCE = 0.6`（`:18`）。

**判定的顺序很重要**：先查 1.0 档（用户权威）→ 再 0.85 档（客观事实）→ 再 0.6 档。所以「既是用户确认又带 `verified_fact`」会得 1.0。

**为什么要有封顶**（`:14-18` 注释）：

```python
# Agent / 主会话收割证据：允许晋升，但置信度封顶（见 promotion_confidence）
```

三个理由：

1. **`confidence` 是下游判据**——`resolve_conflict`（`:222-224`）用它区分「用户确认」与「推断」：`old_user = old.source.get("kind") == "user" and old.confidence >= 1.0`；`new_infer = new.source.get("kind") in {...} and new.confidence < 1.0`。**封顶在 0.6 保证了「推断永不覆盖用户确认」这条规则在数值上成立**——如果收割也能给出 1.0，`new_infer` 就是 False，用户确认就可能被覆盖；
2. **`confidence` 还是检索打分项**——`score_note`（`search.py:87-94`）把 `note.confidence` 直接加进分数。封顶防止「收割来的笔记」靠虚高置信度爬到检索首位；
3. **单调性**：兜底也返回 0.6 而不是 0.0，意味着**任何能通过 `can_promote` 的候选都至少拿到 0.6**——即「闸门负责准入，置信度负责分级」，两者不重叠。

**深化讲解**（面试官参考，不要求候选人全说）
三档数值的选取逻辑：`1.0` 表示「用户说的」（最高权威，且被 `resolve_conflict` 当作硬边界）；`0.85` 表示「有客观证据」（可信但非用户断言，留出 0.15 的差距，避免与用户确认混淆）；`0.6` 表示「流程/模型推断」（可入库但**不可覆盖**前两类）。

★ 一处**冗余但无害**的写法：`any(e in AGENT_HARVEST_EVIDENCE ...) or kind in {...}` 与最后的 `return AGENT_PROMOTE_CONFIDENCE` 返回同一个值，所以那个 `if` 分支**不影响结果**（只影响可读性）。读代码时不必把它当成一条独立规则。



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

### XEYO-QA-0428 workspace 隔离与 user 域合并

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memdir 域隔离 | workspace_id 与 user 域 | 中等 | 机制解释 | `python/memory/memdir.py:30-31,80-119,403-415` |

**面试官提问**
`workspace_id` 怎么生成？为什么说「复制目录必须得到新 id」？`user` 域是什么、检索时怎么合并？

**参考答案要点**
**`workspace_id` 生成**（`memdir.py:80-88`）：

```python
def workspace_id(canonical_path: str) -> str:
    """由规范化工作区路径生成稳定 workspace_id；复制目录必须得到新 id"""
    try:
        p = str(Path(canonical_path).expanduser().resolve())
    except OSError:
        p = os.path.abspath(os.path.expanduser(canonical_path or "."))
    digest = hashlib.sha256(p.encode("utf-8")).hexdigest()[:16]
    slug = _SLUG_RE.sub("_", Path(p).name.lower()).strip("_")[:40] or "ws"
    return f"{slug}_{digest}"
```

形态是 `<目录名 slug>_<路径 sha256 前 16 位>`：**可读前缀 + 路径指纹**。

「复制目录必须得到新 id」的原因在 `p` 的取法：`resolve()` 得到的是**绝对规范化路径**（解析 symlink、折叠 `..`、统一分隔符）。所以：

| 场景 | 结果 |
|---|---|
| 同一目录两条路径写法（`D:\a\.\b` vs `D:\a\b`） | `resolve()` 后相同 → **同一 id**（正确） |
| symlink 指向同一目录 | `resolve()` 后相同 → **同一 id**（正确） |
| `copy -r` 到另一个路径 | 路径不同 → **不同 id**（这正是注释要表达的：副本是另一个工作区，不该共享记忆） |

`_SLUG_RE = re.compile(r"[^a-z0-9]+")`（`:30`）把目录名里非字母数字的字符折成 `_`，所以 `XenYon code` → `xenyon_code`。

**user 域**（`:31,105-109`）：

```python
USER_MEMDIR_ID = "user"
...
def resolve_memdir_id(wsid: str, *, scope: str = "workspace") -> str:
    """按 scope 选择落盘域：user → 全局 user；其余 → 工作区 wsid。"""
    if (scope or "").strip() == "user":
        return USER_MEMDIR_ID
    return wsid
```

`user` 域就是 `memdir_root("user")` = `~/.xeyo/memory/user/`——**一个不随工作区变的固定域**，用来放跨工作区通用的用户偏好（对应 `MemoryNote.scope == "user"`，`governance.py:12`）。`write_note` 按 `note.scope` 路由（`:364`）。

**检索时的合并**（`load_notes_for_search`，`:403-415`）：

```python
def load_notes_for_search(wsid: str, *, scope: str = "") -> list[MemoryNote]:
    """搜索用：默认合并工作区 + user；scope=user 只读用户域。"""
    if scope == "user":
        return load_notes(USER_MEMDIR_ID)
    notes = list(load_notes(wsid))
    if wsid != USER_MEMDIR_ID:
        seen = {n.id for n in notes}
        for n in load_notes(USER_MEMDIR_ID):
            if n.id not in seen:
                notes.append(n)
    if scope and scope != "all":
        notes = [n for n in notes if n.scope == scope]
    return notes
```

四条规则：`scope="user"` → 只读用户域；否则工作区 + 用户域**合并**；合并用 **id 去重**（工作区优先，`seen` 里已有的同 id 用户域笔记不追加）；`scope` 为其他非空值（且非 `"all"`）时按 `note.scope` **过滤**。

另一处合并是索引文本（`search.py:235-244`）：`index = index_ws + "\n" + index_user`——索引平面也把两个域拼起来。

**深化讲解**（面试官参考，不要求候选人全说）
「id 去重、工作区优先」这个顺序解决了一个真实问题：**同一个 `id` 可能在两个域里都有文件**（例如一条笔记先写在工作区、后来被改成 `scope=user` 或手工复制过去）。若不做去重，检索结果里会出现两条完全相同的笔记（同 id、同标题），让模型困惑。

★ 注意 `seen` 是用**工作区**侧建的，所以工作区版本胜出。这个方向的取舍是合理的：**工作区更具体**（与 0405 的 settings 合并规则「workspace 更具体者优先」同向）。

**边界**：`find_note(wsid, note_id)`（`:382-391`）用的是「先工作区、再 user」的**逐个域查找**，而不是合并列表——因为它的语义是「按 id 找唯一一条」，先命中的优先。这与 `load_notes_for_search` 的「合并去重」在结果上一致（都让工作区胜出），但实现路径不同。



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

### XEYO-QA-0429 三处保留期/上限的常量对照

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | 保留期与上限族 | 三处常量的语义差别 | 中等 | 机制解释 | `python/memory/memdir.py:33-44` + `python/tools/spill.py:24-26` + `python/memory/session_md.py:48-52` |

**面试官提问**
记忆层里有三处「保留期/上限」配置，它们的默认值、环境变量与语义分别是什么？`<= 0` 在各自的语义下意味着什么？

**参考答案要点**
| 处 | 环境变量 | 默认 | 语义 | `<= 0` |
|---|---|---|---|---|
| `memdir.prune_dead_notes` | `XEYO_MEMORY_RETENTION_DAYS` | `7.0`（天） | 删除「非 active 且超期」的 `topics/*.md` | **不剪枝** |
| `spill._prune_old` | `XEYO_SPILL_RETENTION_DAYS` | `7`（天） | 删除超期的 spill 文件 | **不清理** |
| `session_md._prune_rollouts` | `XEYO_MEMORY_ROLLOUT_MAX` | `20`（**份数**） | 按 mtime 保留最新 N 份 rollout 归档 | 经 `max(1, ...)` 夹到 1 |

**`memdir.py:33-44`**（原文）：

```python
# P1-2 保留期剪枝（prune_stage1_outputs_for_retention）：
# 只剪掉「非 active + 超保留期」的死 note 文件，绝不触碰 active 事实。
ENV_RETENTION_DAYS = "XEYO_MEMORY_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 7.0


def retention_days() -> float:
	"""记忆保留期（天）；默认 7（同 spill.py）。<=0 表示不剪枝。"""
	try:
		return float(os.environ.get(ENV_RETENTION_DAYS, "").strip() or DEFAULT_RETENTION_DAYS)
	except (TypeError, ValueError):
		return DEFAULT_RETENTION_DAYS
```

`prune_dead_notes`（`:47-77`）的**只删两类**：「`status in {superseded, deleted}`、且 mtime 超保留期」；`status == "active"` 一律 `continue`（`:68-70`）。docstring 强调「保留期内或 active 的绝不动（天量死文件也不冒进）」。

**`session_md.py:48-52`**（原文）：

```python
# P2-2 任务级 rollout 归档（归档到 rollout_summaries/<slug>.md）：
# 会话/任务结束时把 session.md 归档一份到 memdir/rollout_summaries/，喂 L4 检索；
# 只保留最新 N 份（按归档时间），绝不做每轮全量重建（红线②）。
ENV_ROLLOUT_MAX = "XEYO_MEMORY_ROLLOUT_MAX"
DEFAULT_ROLLOUT_MAX = 20
```

`_rollout_max_keep()`（`:67-73`）用 `max(1, int(...))` 夹取下限；`_prune_rollouts`（`:76-93`）按 `st_mtime` **倒序**排序后删 `files[max_keep:]`。

**三处的共性**：都用 `os.environ.get(...)` + `try/except` 解析失败回退默认；都「尽力而为、不抛」（`OSError` 时 `continue`/`return removed`）；都有「保留期内绝不删」或「只删最新 N 之外的」这类**保守边界**。

**三处的差异**：

| 维度 | memdir prune | spill prune | rollout prune |
|---|---|---|---|
| 判据 | `status != active` **且** mtime 超期 | 只看 mtime 超期 | 只看份数（mtime 排序） |
| 单位 | 天（float） | 天（float） | 份（int，下限 1） |
| 触发时机 | NightShift 后台路径 | 每次 `save_text` | 每次归档 |
| 关停方式 | `days <= 0` | `days <= 0` | **无法关停**（`max(1, ...)`） |

**深化讲解**（面试官参考，不要求候选人全说）
三处**都没有 TTL 式的自动过期**，而是「**由事件触发的机会式清理**」：memdir 靠 NightShift、spill 靠下一次保存、rollout 靠下一次归档。这与 B04-0163 的结论一致——机会式清理避免引入后台定时器，代价是「长期不产生事件则旧数据不清」。

★ 一个**设计上的不一致**：`rollout` 的 `max(1, ...)` 让「设为 0 表示不剪枝」这条惯例**失效**——传 `XEYO_MEMORY_ROLLOUT_MAX=0` 会被夹成 1（只留最新 1 份），而不是「不剪」。要与另外两处对齐，应该改成 `if keep <= 0: return 0`（不剪）。这是本批的一处可改进项。



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

### XEYO-QA-0430 C2 确定性摘要的配额表

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | runtime C2 摘要预算 | 全局预算与类型配额 | 中等 | 机制解释 | `python/memory/runtime.py:52-60` + `python/memory/runtime.py:75-85` |

**面试官提问**
C2 确定性摘要的全局字符预算与各类型配额分别是多少？`XEYO_C2_LLM_SUMMARY` 旁路的实测表现如何、为什么默认关？

**参考答案要点**
**全局预算与七档配额**（`runtime.py:52-60`，原文）：

```python
# C2 确定性摘要：全局字符预算 + 类型配额（优先错误/取值，再 grep/assistant 结论，再普通）
C2_SUMMARY_BUDGET = 12_000
C2_QUOTA_ERROR = 400
C2_QUOTA_VALUE = 320
C2_QUOTA_ASSISTANT = 260  # 叙述性结论（git 提交号/文件结论/计数等）——事实常在此层，勿被低配额挤掉（B2）
C2_QUOTA_GREP = 220
C2_QUOTA_USER = 200
C2_QUOTA_DEFAULT = 120
C2_QUOTA_TOOL_USE = 80
```

| 项 | 值 | 说明 |
|---|---|---|
| 全局预算 | `12_000` 字符 | 整份摘要的字符上限 |
| 错误 | 400 | 最高配额 |
| 取值 | 320 | 次高 |
| assistant 结论 | 260 | 注释特别说明：**事实常在此层，勿被低配额挤掉** |
| grep | 220 | |
| user | 200 | |
| 默认 | 120 | 未归类内容 |
| tool_use | 80 | 最低（工具调用参数通常最不重要） |

配额**降序**排列：错误 > 取值 > assistant 结论 > grep > user > 默认 > tool_use——这个顺序就是「压缩时哪些信息更该保真」的排序。

**LLM 摘要旁路**（`:62-85`，原文）：

```python
# T8：C2 LLM 摘要旁路（默认关）。开关由环境变量 XEYO_C2_LLM_SUMMARY=1 显式开启；
# 关闭时 project_for_model/apply_c2_messages/force_compact 走纯确定性摘要（行为不劣化）。
C2_LLM_SUMMARY_ENV = "XEYO_C2_LLM_SUMMARY"
```

```python
def c2_llm_summary_enabled() -> bool:
	"""C2 LLM 摘要旁路（默认关）：**settings.memory 权威（GUI「记忆系统开关」面板可切换）**。

	eval / 脚本可写 ``memory_switches.save({"XEYO_C2_LLM_SUMMARY": "1"})``。
	与其它注册键一致（test_memory_switch_authority 契约）：运行时只读 get_value，
	env 不参与。多一次模型调用，成本权衡；实测吸收潜力高（96% 单次）但输出不稳定
	（同配置三次 62/92/83%），故默认关=确定性摘要。
	"""
```

**实测表现**：**单次 96%，同配置三次 62 / 92 / 83%** —— 潜力高但**方差极大**。这就是默认关的直接理由：「输出不稳定」意味着同一段历史可能被压成质量差异巨大的摘要，而摘要会**进入 KV 前缀**（一旦生成就倾向于冻结复用），一次坏摘要会污染后续很多轮。

★ 注意注释里的一处**口径冲突**：`C2_LLM_SUMMARY_ENV` 上方注释写「开关由环境变量 `XEYO_C2_LLM_SUMMARY=1` 显式开启」，但 `c2_llm_summary_enabled()` 的 docstring 明确「运行时只读 `get_value`，**env 不参与**」。以函数实现为准——**环境变量不生效，必须走 settings.memory 或 `memory_switches.save`**。这是 0405「单一权威源」改造留下的注释残留。

**深化讲解**（面试官参考，不要求候选人全说）
「确定性摘要」与「LLM 摘要」的取舍是**可复现性 vs 保真度**：

- 确定性摘要：纯规则、零额外模型调用、**字节稳定**（同输入必同输出），代价是保真度有限（只能按配额截取各类内容）；
- LLM 摘要：保真潜力高（单次 96%），但**不稳定**（62–92–83 的高方差）且多一次调用。

对一个要进 KV 前缀、且要在 `force_compact` 里被反复使用的东西，**稳定性压倒保真度**——所以默认关。而旁路保留在 GUI（唯一暴露项，见 0402），让用户可自行开启。



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
### XEYO-QA-0431 L3 原子化分段的落点

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | working 信息原子 | `current_atoms` 的形态 | 中等 | 机制解释 | `python/memory/working.py:105-112,254,400-402` |

**面试官提问**
`current_atoms` 存的是什么？为什么它是「可重入计量」而不是全文？

**参考答案要点**
`working.py:105-112`（原文，含 P1 缺失1 的标注）：

```python
    # P1 缺失1：当前 M 段的信息原子分段（可重入计量，不存全文）。
    # 序列化为 [{kind, weight, text}]，供 Q 按原子计权与审计观察。
    current_atoms: list[dict[str, Any]] = field(default_factory=list)
```

形态是 `[{kind, weight, text}]` 的列表——**每个「信息原子」一条**，带类型（`kind`）与权重（`weight`）。

**落盘与恢复**：

- 序列化：`"current_atoms": list(getattr(snap, "current_atoms", []) or [])`（`_to_dict`，`:254`）—— 直接浅拷贝列表；
- 反序列化：`_from_dict` 里做**逐项类型过滤**（`:400-402`）：

```python
        current_atoms=[x for x in raw.get("current_atoms") if isinstance(x, dict)]
        if isinstance(raw.get("current_atoms"), list)
        else [],
```

即**只保留 dict 项**，非 dict 的元素被丢掉（而不是让整份快照回退空）。

**为什么是「计量」而不是全文**：对照 `Current_atoms` 的**同族字段** `ProjectionDigest`（`:45-59`）——它同样自述「**不存全文**，P1 缺失2」：

```python
@dataclass
class ProjectionDigest:
    """投影 X 的可重入计量信息（**不存全文**，P1 缺失2）。

    只持久化重建 Ĥ/LCP 所需的最小计量：冻结前缀的哈希 + 各段 token 长度。
    这样杀进程重启后，``decide`` 仍能算出 ``lcp_keep``（= 冻结前缀长度），而无需
    重放整段投影或把全文写进 sidecar。``tail_len = total_len - frozen_len``。

    若上次投影从未建立（如首轮冷启动），``frozen_len=0``，调用方保守取 0。
    """
```

两者共同的设计动机（`ProjectionDigest` 的 docstring 说得最清楚）：**sidecar 的体积与「重启后还能算出决策参数」这两个要求之间存在矛盾**——把投影全文写进 sidecar 会让文件巨大（且投影本身就在转录里，重复存储），但不存原文就无法重放。解法是**只存「重建所需的最小计量」**：`prefix_hash`（冻结前缀的哈希，用于比对）+ `total_len` / `frozen_len` / `tail_len`（各段 token 长度）。于是重启后 `decide` 仍能算 `lcp_keep`（= 冻结前缀长度）而无需重放。

**深化讲解**（面试官参考，不要求候选人全说）
「可重入」（re-entrant / 可重放）在这个项目里的含义是：**同一个决策在重启前后、以及在同一会话的多次调用之间，能基于持久化的计量得到一致结果**。它需要满足两个条件：

1. **计量是幂等的**（同样输入算同样输出）；
2. **计量足够还原决策所需的量**（不需要全文）。

`current_atoms` 的 `weight` 字段正是为此服务——「供 Q 按原子计权」意味着后续决策（Q 函数）只用**权重**，不用正文。而 `text` 字段的存在说明它**不是纯粹的计量**（保留了正文片段），这是它与 `ProjectionDigest` 的差别：前者服务「按原子分配预算」，后者服务「LCP 预测」。

★ 一处**未在本文件闭环的疑问**（本批待确认项）：`current_atoms` 的 `text` 字段是否也会随会话增长而无限膨胀？代码里只看到序列化/反序列化与过滤，**没有看到上限或裁剪逻辑**（`ProjectionDigest` 有明确的「不存全文」约束，而 `current_atoms` 带 `text`）。需确认写入方（M 段分段器）是否有 cap。



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

### XEYO-QA-0432 可重入计量的重启契约

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | working 投影计量 | 三个长度字段 | 中等 | 机制解释 | `python/memory/working.py:45-59,75-77,259-292` |

**面试官提问**
`ProjectionDigest` 的四个字段分别是什么？`tail_len` 与另外两个长度字段的关系是什么？字段拿不到时的取值策略是什么？

**参考答案要点**
`working.py:45-59`（原文）：

```python
@dataclass
class ProjectionDigest:
    """投影 X 的可重入计量信息（**不存全文**，P1 缺失2）。

    只持久化重建 Ĥ/LCP 所需的最小计量：冻结前缀的哈希 + 各段 token 长度。
    这样杀进程重启后，``decide`` 仍能算出 ``lcp_keep``（= 冻结前缀长度），而无需
    重放整段投影或把全文写进 sidecar。``tail_len = total_len - frozen_len``。

    若上次投影从未建立（如首轮冷启动），``frozen_len=0``，调用方保守取 0。
    """

    prefix_hash: str = ""  # 冻结前缀（P = p_s + p_c）文本的 sha256
    total_len: int = 0  # 完整投影 X 的 token 长度
    frozen_len: int = 0  # 冻结前缀 P 的 token 长度（= Projected.p_end）
    tail_len: int = 0  # total_len - frozen_len（M+Tk+Tnow 段）
```

| 字段 | 含义 |
|---|---|
| `prefix_hash` | 冻结前缀 `P = p_s + p_c` 文本的 **sha256** |
| `total_len` | 完整投影 `X` 的 token 长度 |
| `frozen_len` | 冻结前缀 `P` 的 token 长度（= `Projected.p_end`） |
| `tail_len` | `total_len - frozen_len`（即 `M + Tk + Tnow` 段） |

**关系**：`tail_len = total_len - frozen_len`——docstring 里写明了这条不变量。但**存储时三者各自独立落盘**（`_projection_to_dict`，`:259-268`），并不在读取时重算 `tail_len`：

```python
def _projection_to_dict(digest: ProjectionDigest | None) -> dict[str, Any] | None:
    """把 ProjectionDigest 编成可 JSON 化的字典；None 时输出 None。"""
    if digest is None:
        return None
    return {
        "prefix_hash": str(digest.prefix_hash or ""),
        "total_len": int(digest.total_len or 0),
        "frozen_len": int(digest.frozen_len or 0),
        "tail_len": int(digest.tail_len or 0),
    }
```

**读取时的三处保守策略**（`_parse_projection`，`:271-292`）：

```python
    if not isinstance(raw, dict):
        return None
    try:
        total = max(0, int(raw.get("total_len") or 0))
    except (TypeError, ValueError):
        total = 0
    ...
```

①非 dict → 返回 `None`（调用方按「从未建立投影」处理）；②每个数值字段 `max(0, int(...))` 夹到非负；③解析失败（`TypeError`/`ValueError`）→ 该字段取 0。docstring 给出的语义是「若上次投影从未建立（如首轮冷启动），`frozen_len=0`，调用方保守取 0」——即**缺失一律按最保守值处理**。

**深化讲解**（面试官参考，不要求候选人全说）
「重启后仍能算出 `lcp_keep`」这条能力解决的是一个具体问题：**LCP（最长公共前缀）预测必须知道「上次发出去的投影有多长、冻结部分到哪」**——而这些信息在内存里（`last_x_sim` / `last_x_sent` 是全文），杀进程就没了。若重启后无法预测 LCP，`decide` 就会做出与实际缓存状态不符的决策（例如以为没有缓存命中而重新发送全量）。

解法有两层：

| 层 | 字段 | 用途 |
|---|---|---|
| 全文（易失） | `last_x_sim` / `last_x_sent`（`working.py:75-77`） | 热路径的邻居比对（`observe.py:85` 的 `lcp_tokens(x_sent, snap.last_x_sent)`） |
| 计量（持久） | `ProjectionDigest` | 重启后的 Ĥ/LCP 近似 |

`prefix_hash` 的存在让「冻结前缀是否变过」可以被**比哈希**判定，而不必比全文——这是「字节稳定」这件事的可验证化：哈希一致 ⇒ 前缀逐字节一致 ⇒ KV 前缀可复用。

★ 与 0445 呼应：`last_x_sent` 由 `observe_shot` 在**每个请求**里更新（`observe.py:115`），而 `last_projection` 是随 `flush`/`hydrate` 走的持久计量。两条轨道服务不同时效的需求——这是「**热路径用全文、冷路径用计量**」的分工。



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

### XEYO-QA-0433 老化推进与 v61/C2 的四路互斥

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | runtime 老化边界推进 | 四重前置条件 | 困难 | 场景设计 | `python/memory/runtime.py:48-50,215-236` + `python/memory/l5_flag.py:35-37` |

**面试官提问**
`maybe_advance_aging_boundary(messages, working)` 有**四重**前置条件。请逐条说明，并解释第 3、4 条各自防的是什么问题。

```python
def maybe_advance_aging_boundary(messages: list[dict], working: WorkingSnapshot) -> bool:
	"""非 v61 路径的老化边界推进：把 frozen_until 前移到尾部保护区之前。

	仅在开启 XEYO_TOOL_AGING 时生效；带滞后门（≥MIN_ADVANCE）与 pair-safe
	切点。**已压缩态（compact_cursor>0）跳过**：避免与 C2 同轮抢推边界、
	制造双 miss。v61 模式不介入（其 C1 由公式决策）。
	"""
	if not aging_enabled() or use_v61():
		return False
	if int(working.compact_cursor or 0) > 0:
		return False
	candidate = pair_safe_cut(messages, keep_tail_cut(messages))
	if candidate - int(working.c1_frozen_until) < _aging_min_advance():
		return False
	note_c1(working, candidate)
```

**参考答案要点**
四重前置（代码顺序）：

| # | 条件 | 位置 |
|---|---|---|
| 1 | `aging_enabled()`（`XEYO_TOOL_AGING` 开启；**默认关**）**且** `not use_v61()` | `:229` |
| 2 | `int(working.compact_cursor or 0) > 0` 时**跳过** | `:231-232` |
| 3 | 推进量 `candidate - c1_frozen_until >= _aging_min_advance()` | `:234-235` |
| 4 | `candidate = pair_safe_cut(messages, keep_tail_cut(messages))`——切点必须**工具对安全** | `:233` |

滞后常量（`:48-50`）：

```python
#: 老化边界推进的最小滞后（消息数）：两次推进之间至少积累这么多新消息，
#: 保证推进是稀发事件、推进后投影字节稳定（设计 N≈8 的落地映射）。
AGING_MIN_ADVANCE_DEFAULT = 8
```

可由 `XEYO_TOOL_AGING_MIN_ADVANCE` 覆盖，下限 1（`_aging_min_advance`，`:215-219`）。

**第 3 条（滞后门）防的是「频繁推进导致的持续 miss」**：每次推进 `frozen_until` 都会改变投影——被判为「冻结」的 tool_result 会被替换成存根（见 0448），从而**改变已发送前缀的字节**。若每轮都推进，KV 前缀**每轮都 miss**，缓存收益直接归零。要求「至少积累 8 条新消息才推一次」，把推进变成**稀发事件**：两次推进之间的投影字节保持稳定，缓存前缀可复用。

**第 4 条（pair-safe 切点）防的是「切断工具调用对」**：`pair_safe_cut`（`:320-327`）与 `_pair_ranges`（`:302-318`）保证切点落在 assistant 的 `tool_use` 与其 `tool_result` **之间之外**——即不把一个工具调用对切到两半。若切在中间，投影里会出现「有 tool_use 没有 result」或反之，这既违反消息协议（部分 provider 会直接报错），也会让存根替换逻辑找不到配对。

**第 2 条（已压缩态跳过）** 的理由注释写得很直接：「**避免与 C2 同轮抢推边界、制造双 miss**」。C2 压缩也会推进 `c1_frozen_until`（`working.note_c2` 里 `c1_frozen_until = max(c1_frozen_until, new_cursor)`，`working.py:496-499`）。若老化也同时推，**同一轮里投影被改两次**，每次改动都会破坏前缀——一轮双 miss 是最坏情况。

**第 1 条里的 `use_v61()`** 防的是「两套 C1 决策打架」：注释说「v61 模式不介入（其 C1 由公式决策）」——在 v61 下，C1 冻结边界由 `decide` 的公式管理（`_c2_formula_enabled` 恒真，见 0404），老化这条**独立的推进路径**必须让位，否则两个决策者会互相覆盖对方的边界。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于「**每一条前置条件都对应一类具体故障**」这个结构性事实：

| 条件 | 缺了会怎样 |
|---|---|
| 开关 + 非 v61 | 关着的功能偷偷生效 / 与公式决策打架 |
| 已压缩跳过 | 一轮双 miss（最贵的故障） |
| 滞后 ≥ 8 | 每轮 miss，缓存收益归零 |
| pair-safe | 消息协议破损 / 存根找不到配对 |

即这不是「层层保险」，而是**四个不同的失败模式各自的对策**。读这类守卫代码时，正确的读法是「把每条 `return False` 翻译成一句『否则会坏在哪』」，而不是把它们当成一串同质的检查。

★ 与 B03 已确立的结论证呼应：`aging` 默认关是**临时态**（恢复机制未落地），所以这条推进路径在当前默认配置下**根本不会执行**——但代码必须保持正确，因为一旦老化开启（GUI 或 NightShift 路径），这四条就是唯一的保护。



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

### XEYO-QA-0434 首压锚点与 resume 的字节稳定闭环

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | working checkpoint | 锚点对齐与摘要回填 | 困难 | 场景设计 | `python/memory/working.py:27-42,164-211,324-347` |

**面试官提问**
`CompactCheckpoint` 的三个锚点字段是什么？`_from_dict` 在恢复时做了哪两件事来保证「set checkpoint → flush → hydrate → projection 一致」？为什么要专门回填 `c2_summary_text`？

**参考答案要点**
**三个锚点 + 一个窗口链**（`working.py:27-42`）：

```python
@dataclass
class CompactCheckpoint:
    """C2 compact checkpoint（落盘在 ``<id>.working.json``）。

    投影锚点（anchor_*）+ 窗口链（window_chain）+ 首压摘要（anchor_summary）。
    resume 时由 ``_from_dict`` 用它重建投影：把 cursor/frozen 对齐到锚点、
    并回填冻结的 ``c2_summary_text``，保证「set checkpoint → flush → hydrate →
    projection 一致」。
    """

    version: int = 1  # checkpoint 格式版本，缺省 1
    anchor_cursor: int = 0  # 投影锚点：首压时冻结的 compact_cursor
    anchor_frozen_until: int = 0  # 投影锚点：首压时的 c1_frozen_until
    anchor_summary: str = ""  # 首压摘要文本（KV 前缀冻结，必为 c2_summary_text 的副本）
    # 窗口链：每次 C2/append-only 扩展追加一条 {cursor, frozen_until, summary_fp}
    window_chain: list[dict[str, Any]] = field(default_factory=list)
```

**恢复时做的两件事**（`_from_dict`，`:324-347`）：

```python
def _from_dict(raw: dict[str, Any], session_id: str) -> WorkingSnapshot:
    """从字典恢复快照；缺字段用默认。

    T8：读回 compact_checkpoint 后做**投影锚点对齐**——resume 时 cursor/frozen
    对齐到锚点、并回填冻结的 c2_summary_text，保证「set checkpoint → flush →
    hydrate → projection 一致」。
    """
    cursor = raw.get("compact_cursor", 0)
    try:
        cursor_i = max(0, int(cursor))
    except (TypeError, ValueError):
        cursor_i = 0
    try:
        frozen = max(0, int(raw.get("c1_frozen_until") or 0))
    except (TypeError, ValueError):
        frozen = 0
    c2_summary_text = str(raw.get("c2_summary_text") or "")
    cp = _parse_checkpoint(raw.get("compact_checkpoint"))
    if cp is not None:
        cursor_i = max(cursor_i, int(cp.anchor_cursor or 0))
        frozen = max(frozen, int(cp.anchor_frozen_until or 0))
        if not (c2_summary_text or "").strip():
            # resume：摘要文本由锚点回填，保证 KV 前缀字节稳定
            c2_summary_text = str(cp.anchor_summary or "")
```

| 动作 | 实现 | 方向 |
|---|---|---|
| ① 锚点对齐 | `cursor_i = max(cursor_i, cp.anchor_cursor)`；`frozen = max(frozen, cp.anchor_frozen_until)` | **只前进**（`max`） |
| ② 摘要回填 | 仅当 `c2_summary_text` 为空时，用 `cp.anchor_summary` 填充 | 单向兜底 |

**为什么要专门回填 `c2_summary_text`**：因为它是**冻结进 KV 前缀的文本**。注释（`:346`）说「保证 KV 前缀**字节稳定**」。字段注释也写了它的定位（`:70`）：「C2 摘要文本（首次压缩时冻结，保证后续请求字节稳定）」，而 `anchor_summary` 的注释进一步说明「**必为 `c2_summary_text` 的副本**」（`:40`）。

即：`c2_summary_text` 一旦生成就被**冻结复用**（每次 C2 投影都注入同一份文本），所以它的字节必须跨重启保持不变。若重启后它丢了（例如只落了 checkpoint 而主字段为空），重新生成一份**内容不同**的摘要 → 前缀从摘要处开始全部 miss，且模型看到的摘要内容也会变（同一会话的历史被「换了种说法」）。

**两件事的方向差别是关键**：锚点是 `max`（只允许前进，不允许回退——因为 `compact_cursor` 的语义是「已压实的历史索引（**只增不减**）」，`:68 注释），而摘要是「空则填」（不允许用锚点覆盖已有的非空摘要，避免用旧副本盖掉更新的版本）。

**`_parse_checkpoint` 的保守读取**（`:295-321`）：非 dict → `None`；`anchor_cursor`/`anchor_frozen` 夹非负；`window_chain` 非 list → `[]`，并过滤出 dict 项；`version` 夹到 ≥ 1。所以**坏 checkpoint 不会让整份快照失效**——它只是让 `cp` 为 `None`，此时两个 `max` 与回填都不执行，快照按主字段恢复。

**深化讲解**（面试官参考，不要求候选人全说）
这套机制解决的是一个**重启一致性**问题：压缩状态在内存里有多个相关变量（`compact_cursor` / `c1_frozen_until` / `c2_summary_text` / `window_chain`），它们**必须同时正确**才能重建等价的投影。单靠逐一落盘这些字段是不够的——落盘时刻与读取时刻之间可能有部分写入/旧版本数据，所以额外存一份**锚点三元组**作为「上一次确认过的自洽状态」，恢复时以「锚点与主字段取更前进者」的方式收敛。

`version` 字段（`int(cp.version or 1)`，夹到 ≥ 1）是**格式演进的预留位**——当前只用默认值 1，读取时容错（`max(1, ...)`）。这符合「先留版本号再加字段」的稳妥做法。

★ 配套的还有两个写入函数：`note_compact_checkpoint`（首压，`:164-187`）与 `append_compact_window`（已压缩态的 append-only 扩展，`:190-211`）。前者在 `cp` 为 `None` 时用传入值**建立**锚点、在已存在时**只前进**；后者在 `cp` 为 `None` 时也会建立。两者都会 `cp.window_chain.append(_cp_window(...))`，而 `_cp_window`（`:155-161`）只记 `{cursor, frozen_until, summary_fp}`——**`summary_fp` 是摘要的长度（`len(summary_text or "")`）而不是哈希**。这是一个**弱指纹**（不同摘要可能同长度），但对「窗口链」这个只用于审计/追溯的用途足够。



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
### XEYO-QA-0435 sidecar 与 `session.md` 的双持久化一致面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | working/session_md 回滚清理 | 双持久化面 | 困难 | 场景设计 | `python/memory/working.py:459-488` + `python/memory/session_md.py:160-188` |

**面试官提问**
回滚（transcript rewind）发生时，`working.reset_after_rollback` 与 `session_md.clear_after_rollback` 各自负责清理什么？它们清理的**粒度**有什么本质不同？为什么必须**两个都清理**？

**参考答案要点**
**两个清理函数**（原文）：

`working.reset_after_rollback`（`working.py:459-488`）：

```python
def reset_after_rollback(session_id: str) -> None:
    """Drop compression / projection sidecar state after transcript rewind.

    Chat-only rewinds truncate JSONL but leave ``.working.json`` untouched unless
    we reset it here.  Stale ``c2_summary_text`` would otherwise re-inject
    truncated conversation back into the model via C2 projection.
    """
    sid = (session_id or "").strip()
    if not sid:
        return
    snap = hydrate(sid)
    snap.session_id = sid
    snap.compact_cursor = 0
    snap.c1_frozen_until = 0
    snap.c2_summary_text = ""
    snap.turns_since_c2 = 0
    snap.last_x_sim = ""
    snap.last_x_sent = ""
    snap.last_action = ""
    snap.speculation = []
    snap.todos = []
    snap.tasks = []
    snap.read_file_state = {}
    snap.session_md_tool_epoch = 0
    snap.proj_cache = None
    snap.compact_checkpoint = None
    snap._pending_c2_summary = None
    snap.last_projection = None
    snap.current_atoms = []
    flush(sid, snap)
```

`session_md.clear_after_rollback`（`session_md.py:160-188`）：

```python
def clear_after_rollback(session_id: str, *, keep_tool_calls: int | None = None) -> None:
    """回滚后的 session.md 处理（A5 差分重写）。

    - ``keep_tool_calls=None``（缺省/无法计量）：旧行为——整文件删除（fail-closed）；
    - ``keep_tool_calls=N``：**精确截断**——只保留 turn ≤ N 的 delta 并重放重建
      物化文件（回滚不再失忆）；无 delta 可存（或从未 delta 化）→ 退回整删。
    """
    sid = (session_id or "").strip()
    if not sid:
        return
    path = path_for(sid)
    if keep_tool_calls is None:
        _unlink_quiet(path)
        _unlink_quiet(path_deltas(sid))
        return
    try:
        text = rebuild_from_deltas(sid, upto_turn=int(keep_tool_calls))
    except Exception:  # noqa: BLE001 — 回滚路径绝不因增强项失败
        text = None
    if not text or not text.strip():
        # 无可存叙事（delta 全在截断点之后 / 从未 delta 化）→ 旧行为整删
        _unlink_quiet(path)
        _unlink_quiet(path_deltas(sid))
        return
    try:
        _atomic_write_text(path, text)
    except OSError:
        pass
```

**粒度差异**（本题的核心）：

| | `working.reset_after_rollback` | `session_md.clear_after_rollback` |
|---|---|---|
| 目标 | `<id>.working.json` 一个文件 | `session.md` **与** `session_deltas.jsonl` 两个文件 |
| 方式 | **全量归零**（17 个字段逐个重置）+ `flush` | **两档**：全删 / 按 turn 精确重建 |
| 判据 | 无（回滚即全清） | `keep_tool_calls` 是否给得出（`None` = 无法计量） |
| 残留能力 | **零**（清完就没了） | **有**（`rebuild_from_deltas` 从 delta 日志重放） |

即：**machine state 是全清，narrative 是可截断重建**。

**为什么必须两个都清理**：`working.py:462-465` 的英文 docstring 把理由写死了：

> Chat-only rewinds truncate JSONL but leave `.working.json` untouched unless we reset it here. Stale `c2_summary_text` would otherwise re-inject truncated conversation back into the model via C2 projection.

即：回滚只截断 JSONL（转录），而 sidecar 是**独立文件**——若不显式清，**旧的 `c2_summary_text` 会在下一次 C2 投影里把「已被回滚掉的历史」重新注入模型**。这是「**已删除的内容通过缓存复活**」这一类故障，属于最隐蔽的一类（用户看到的是「我回滚了但它还记得」）。

`session.md` 一侧同样是「已删内容复活」的通道：它是模型可见文本（`session_md.py:1`「给模型看」），会被 C2 左段使用（`session_md.load` 的 docstring：`session_md.py:145-146`「读取 session.md 正文；不存在则返回 None，供 C2 左段使用」）。若不清理，回滚后模型仍能在笔记里看到被回滚的话题。

★ 还有**第三处**必须同步：`working.reset_after_rollback` 里清了 `snap.read_file_state = {}`——对应 B04 的 `ReadFileState`（`fileio/read_state.py`）经 `apply_to_tools`/`collect_from_tools` 与 sidecar 双向同步（`working.py:522-566`）。所以回滚后的「先读校验」状态也被重置——这与 B03 的 rewind 语义一致（回滚后应重新 Read）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的通用教训是「**一份逻辑状态有多个物理载体时，清理必须覆盖全部载体**」。这里的载体有三个：转录 JSONL（rewind 自己管）、`.working.json`（`reset_after_rollback`）、`session.md` + `session_deltas.jsonl`（`clear_after_rollback`）。三者的清理**入口完全不同**（rewind 服务 / memory.working / memory.session_md），靠**调用方把它们串起来**——也就是说，这个不变量**没有单一owner**，是目前架构里的一处结构风险（本批待确认项：需确认 rewind 路径是否**必定**调用这两个函数，以及是否有测试守住）。

`session_md` 侧的**两档设计**值得单独记：`keep_tool_calls=None` 时「整删」是 fail-closed（`docstring` 明写「旧行为——整文件删除（fail-closed）」），给出 N 时才走精确重建。而重建失败（`rebuild_from_deltas` 抛异常或无内容）**也退回整删**——即**降级方向是「多删」而非「少删」**。对「已删内容不得复活」这条不变量而言，多删是安全侧。



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

### XEYO-QA-0436 转录行数计数的 None 语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | session_md 回滚计量 | `count_tool_results_rows` | 困难 | 代码阅读 | `python/memory/session_md.py:360-389` |

**面试官提问**
`count_tool_results_rows(rows)` 在什么情况下返回 `None`？为什么返回 `None` 而不是 0？它与 `count_tool_calls(messages)` 的区别是什么？

**参考答案要点**
`session_md.py:365-389`（原文）：

```python
def count_tool_results_rows(rows: list[Any]) -> int | None:
    """对转录行（形状不保证）尽力统计工具结果条数；无法判定返回 None。

    供回滚路径把「delta 截断点」对齐到保留转录：形如 role=tool / content 含
    tool_result / type==tool_result 的行都计一次；解析失败整体返回 None
    （调用方退回旧行为整删）。
    """
    if not isinstance(rows, list):
        return None
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            return None
        if row.get("role") == "tool" or row.get("type") == "tool_result":
            n += 1
            continue
        content = row.get("content") or row.get("message")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            n += 1
            continue
        if isinstance(content, dict) and content.get("type") == "tool_result":
            n += 1
    return n
```

**返回 `None` 的两种情形**：①`rows` 不是 `list`；②遍历中遇到**任何非 dict 的行**（`if not isinstance(row, dict): return None`）——注意是**立刻整体返回 None**，不做「跳过这一行继续统计」。

**为什么返回 `None` 而不是 0**：因为 `None` 与 `0` 在下游的语义**完全不同**（见 0435）：

| 返回值 | `clear_after_rollback(keep_tool_calls=...)` 的行为 |
|---|---|
| `None` | `keep_tool_calls is None` → **整文件删除**（fail-closed，旧行为） |
| `0` | `keep_tool_calls = 0` → 走精确重建路径，`upto_turn=0` → 只保留 `turn <= 0` 的 delta |

若把「无法判定」映射成 0，就会把**一次解析失败误当成「保留 0 轮」**——虽然最终也可能落到「无内容 → 整删」，但**路径不同**（走了重建分支），而且一旦将来 `turn=0` 有特殊含义就会出错。`None` 保留了「**我不知道**」这个第三态，让调用方显式选择保守行为。

**与 `count_tool_calls` 的区别**（`:360-362` vs `:365-389`）：

| | `count_tool_calls(messages)` | `count_tool_results_rows(rows)` |
|---|---|---|
| 输入 | 消息列表（**形状已知**，就是投影用的 dict） | 转录行（**形状不保证**，`list[Any]`） |
| 判据 | `_is_tool_msg`：`role == "tool"` 或 content 里有 `tool_result` 块 | 三种形态都认：`role=="tool"` / `type=="tool_result"` / content(list/dict) 含 `tool_result` |
| 失败取向 | 无失败态（形状已知，最多数 0） | **遇到坏行 → `None`** |
| 用途 | session.md 重写的节流计数（`:501`） | 回滚时把 delta 截断点**对齐到保留转录** |

`count_tool_results_rows` 多认了 **`type == "tool_result"`** 这一形态（`:378`）以及 `content` 是单 dict 的形态（`:387`）——因为转录 JSONL 里工具结果可能有多种表示（取决于写入方），而投影里的消息形态是受控的。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的关键是把「**尽力而为 + 显式失败**」这个模式读透：

- 「尽力而为」体现在**多形态识别**（三种行形态、list/dict 两种 content）；
- 「显式失败」体现在**遇坏行整体放弃**（不是跳过坏行）——因为这是**回滚路径**，一段坏行意味着「无法确定保留到哪」，此时**猜一个数比放弃更危险**：猜少了会丢用户想保留的历史，猜多了会把回滚掉的内容带回（对照 0435 的「已删内容复活」故障）。

所以「遇坏行整体 `None`」不是偷懒，而是**在不确定时把决策权交回给 fail-closed 分支**（整删）。

★ 注意 docstring 最后一句「解析失败整体返回 None（**调用方退回旧行为整删**）」——它把调用方的降级行为也写在被调用方的文档里了。这是一个小但值得称赞的习惯：**失败语义的终点被写在了失败的产生点**，读者不必跳到调用方才能知道 `None` 意味着什么。



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

### XEYO-QA-0437 sidecar 落盘失败静默的四类风险

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | working flush 容错 | 静默失败的理由与代价 | 困难 | 场景设计 | `python/memory/working.py:431-456` |

**面试官提问**
`flush` 在落盘失败时**只记日志、不抛异常**。代码里给出的理由是什么？这个选择会带来哪些风险？

**参考答案要点**
`working.py:431-456`（原文，理由就在 docstring 里）：

```python
def flush(session_id: str, snap: WorkingSnapshot) -> None:
    """把 WorkingSnapshot 原子写回 sidecar，供重启后续聊。

    落盘失败只记日志不抛：调用方多在 finally 收尾链上，抛出会吞掉
    后续的 journal 终态 / task_state 复位（曾致重启误报 recovery_required）。
    """
    sid = (session_id or snap.session_id or "").strip()
    if not sid:
        return
    snap.session_id = sid
    path = path_for(sid)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_to_dict(snap), ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logging.getLogger(__name__).warning(
            "working snapshot flush failed session=%s", sid, exc_info=True
        )
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
```

**理由（docstring 原文）**：「落盘失败只记日志不抛：**调用方多在 finally 收尾链上**，抛出会吞掉后续的 journal 终态 / task_state 复位（**曾致重启误报 `recovery_required`**）。」

即这是一条**有事故背书**的决定：在 `finally` 里 `flush`，若它抛异常，会中断 `finally` 块的后续语句（journal 终态写入、`task_state` 复位），其后果是**重启后被误判为「需要恢复」**（假阳性的 recovery 提示）。

**清理动作**：失败时尝试删掉可能残留的 `.tmp` 文件（`tmp.unlink()`），且这一步自身也包在 `try/except OSError` 里。

**四类风险**：

| 风险 | 机制 | 后果 |
|---|---|---|
| ① **静默状态回退** | sidecar 保留上一次成功写入的内容 → 下次 `hydrate` 得到**旧快照** | 压缩游标/冻结边界落后于实际，可能出现「重复压缩」或「缓存前缀失配」 |
| ② **临时文件残留** | `tmp.write_text` 成功但 `os.replace` 失败（如目标被占用）时，`.tmp` 已写入 | 该函数会尝试删；若删除也失败（`OSError` 被吞），残留 `<id>.working.json.tmp`。**注意 `path_for` 只拼 `.working.json`，所以 `.tmp` 不会被误读为快照**（安全性可接受） |
| ③ **只记 warning，无审计事件** | 用的是 `logging`（`logger.warning`）而非 `audit.log` | 与 `_record_change_locked` 里的 `default_audit_log().record("memory.aging.advance", ...)` 相比，这条失败**不进审计链**——排障时只能在日志里找 |
| ④ **与 `reset_after_rollback` 的组合** | 那个函数自己也是「先 `hydrate` → 改动 → `flush`」 | 若最后的 `flush` 静默失败，**回滚清理没落盘**，sidecar 里仍是回滚前的状态 → 下次启动会把被回滚的历史重新投影（与 0435 的复活故障同源） |

**深化讲解**（面试官参考，不要求候选人全说）
这是一个教科书式的**容错取舍**：两个错误方向各有代价——

- **抛异常**：保护了「状态一致性」（调用方会知道失败），但破坏了「收尾链完整性」（事故已证）；
- **静默**：保住收尾链，代价是**状态可能落后，且失败不易被发现**。

代码选择了后者，并把理由写在 docstring 里（连事故现象「重启误报 `recovery_required`」都写明了）。判断这个选择是否正确的关键是：**这份 sidecar 是「权威状态」还是「可重建的优化状态」？**

- 若是权威状态 → 静默失败不可接受（应改成审计 + 让上层决定）；
- 若是可重建的优化状态 → 静默可接受（最坏是性能退化）。

从 0422 的「文件是 source of truth，sqlite 只是派生」以及 `working.py:3`「本文件只做机器状态」的定位看，`.working.json` 属于**后者**（衍生状态，可从转录重建）——所以静默是**方向上正确**的。但风险 ④ 是一个例外：`reset_after_rollback` 的清理**不是优化而是正确性要求**（防已删内容复活），它的 `flush` 静默失败会让这条要求失效。这是本批指出的**一处需要加固的点**（例如让回滚路径的 flush 走一条会报错的变体）。



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

### XEYO-QA-0438 sqlite 索引的缓存双刃

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memindex 缓存一致性 | 读写两侧的时效性 | 困难 | 场景设计 | `python/memory/memindex.py:144-192,214-239,274-286` |

**面试官提问**
`load_notes_cached` 是「与文件扫描逐字节等价」的缓存版。请说明它**可能返回与文件不一致**的两条路径，以及代码用什么手段缓解。`rebuild()` 为什么先 `DELETE` 再懒同步？

**参考答案要点**
**两条不一致路径**：

**① 签名碰撞**（`(mtime, size)` 相同但内容变了）：`_sync_table` 的跳过条件是（`memindex.py:158-160`）：

```python
        for name, (mtime, size) in entries.items():
            if known.get(name) == (mtime, size):
                continue
```

`(mtime, size)` 完全相同的两次写入（同秒内改成同样长度）→ **不重读，返回旧 body**。

**② 库里已有行但前端绕过（或写穿透失败）**：write-through（`upsert_note_file`）**吞掉所有异常**（`:258-263`）：

```python
def upsert_note_file(domain: str, path: Path) -> None:
    """write-through：write_note 落盘后立即同步单文件（尽力而为，失败静默）。"""
    try:
        _sync_table(domain, "notes", path.parent, loader=_load_note_file)
    except Exception:  # noqa: BLE001 — write-through 不阻塞写路径
        pass
```

若这次同步失败（例如 sqlite 被锁、磁盘满），**文件已更新而库仍是旧行**。下一次 `load_notes_cached` 会跑 `_sync_table`——所以只要签名变了就会被修正；但如果**签名的 mtime 恰好没变**（同秒写入），就落到路径 ①。

**缓解手段有三层**：

| 层 | 手段 | 位置 |
|---|---|---|
| 1 | 调用方 **fail-open 回退文件扫描** | `memdir.load_notes` 的 `try/except`（`memdir.py:339-346`） |
| 2 | 读出后仍跑 **`parse_and_validate`**（坏行跳过） | `load_notes_cached`（`:230-238`） |
| 3 | **`rebuild(domain)`** 作为一等的修复操作 | `:274-286` |

**`rebuild` 为什么先 `DELETE` 再懒同步**（`:274-286`）：

```python
def rebuild(domain: str) -> int:
    """全量重建（丢弃签名，强制重读全部文件）；返回重建的 note 条数。"""
    try:
        with _connect(domain) as conn:
            conn.execute("DELETE FROM notes WHERE domain = ?", (domain,))
            conn.execute("DELETE FROM rollouts WHERE domain = ?", (domain,))
    except Exception:  # noqa: BLE001
        return 0
    try:
        load_notes_cached(domain)
        return 1
    except Exception:  # noqa: BLE001
        return 0
```

因为 `_sync_table` 的跳过判据是「**库里签名 == 磁盘签名**」。若只调 `load_notes_cached` 而不先 `DELETE`，那些**签名恰好相同但内容已变**的行会继续被跳过——**重建就重建不了它们**。所以必须先清空，让所有行都变成「库里没有 → 必须重读」。

★ 注意 `rebuild` 的注释写「返回**重建的 note 条数**」，但实现返回的是 **`1` 或 `0`**（成功/失败的布尔）——**注释与实现不一致**，以返回值为准。这是一个小但会影响调用方的偏差（若调用方按条数展示「重建了 N 条」会永远显示 1）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于把「缓存等价性」拆成两个独立问题：

| 问题 | 本模块的答案 |
|---|---|
| **写后多久可见？** | 立即可见（write-through），失败则退化为「下次签名变化时可见」 |
| **读到的可能是旧的吗？** | 可能（签名碰撞、写穿透失败），所以设计上把它当**优化**而非真相 |

两条问题的答案共同定义了这份缓存的**定位**：它是一个「**通常正确、偶尔滞后、坏了就退化为全量扫描**」的加速层。判断这个定位是否可接受，取决于它的消费者承受能力——而检索链路的承受能力较高（`load_notes_for_search` 之后还有打分与 `top_k` 截断，多一条旧 note 不会导致事实错误），所以当前设计合理。

★ 对照 B04 的 `content_index`（`fileio/content_index.py`）：那里为了「不漏文件」选择了**全或无**（任一次读失败就 `return None` 放弃整个索引）。两者是**同一个问题在两种容忍度下的不同答案**：content_index 的「漏」会导致 `Grep` 报零命中（事实错误），而 memindex 的「旧」只导致检索结果略旧——所以前者必须放弃，后者可以退化。这个对比是本题最值得带走的心智模型。



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
### XEYO-QA-0439 检索重排「不改召回集」的实际边界

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | search 召回与排序分离 | 重排的作用面 | 困难 | 场景设计 | `python/memory/search.py:52-57,97-113,174-189,222-262` |

**面试官提问**
`search.py:52-57` 的注释声称 F4 查询感知重排「**只为「排序」服务，绝不改召回集**」。请读 `search()` 的主循环，判断这个声称**是否严格成立**；若不成立，指出它实际影响召回的具体条件。

```python
	terms, require_all, min_or_hits = _query_terms(q)
	want_type = (note_type or "").strip().lower()
	notes = [
		n
		for n in load_notes_for_search(ident, scope=scope or "")
		if n.status == "active"
		and (not want_type or (n.type or "").strip().lower() == want_type)
	]
	index_ws = _normalize_query(load_index_text(ident))
	...
	index = index_ws + "\n" + index_user
	reweight = query_reweight_enabled(cwd)
	scored: list[tuple[float, MemoryNote]] = []
	for note in notes:
		hay = _note_hay(note)
		if not _matches(hay, index, q, terms, require_all, min_or_hits):
			continue
		scored.append((score_note(note, q, terms, hay=hay, reweight=reweight), note))
	scored.sort(key=lambda x: x[0], reverse=True)
	hits = [n for _s, n in scored[: max(1, int(top_k))]]
```

**参考答案要点**
**注释声称不严格成立。** 重排在**大多数情况下**只影响排序，但在**两条具体路径**上会直接改变召回集。

**关键代码**（`search.py:247-251`）：

```python
	for note in notes:
		hay = _note_hay(note)
		if not _matches(hay, index, q, terms, require_all, min_or_hits):
			continue
		scored.append((score_note(note, q, terms, hay=hay, reweight=reweight), note))
```

注意：**`_matches` 的第三个实参是 `hay`，而 `q`/`terms` 都源自 `_normalize_query` 后的查询**。而 `_matches`（`:174-189`）的第一步是：

```python
	if q and (q in hay or q in index):
		return True
```

**① 路径一（真正的召回影响）：`_term_hit` 的长度闸与 `min_or_hits` 组合**

`_matches` 的 OR 分支（`:186-189`）：

```python
	if require_all:
		return all(t in hay or t in index for t in terms)
	hits = sum(1 for t in terms if _term_hit(t, hay, index))
	return hits >= max(1, min_or_hits)
```

而 `_term_hit`（`:170-171`）要求 `len(term) >= 2`。**`terms` 里长度 < 2 的项被静默丢弃**，于是：

- 若某个查询的所有 term 都长度 < 2（例如查询是单个 CJK 字符「改」→ n-gram 生成器 `_cjk_ngrams` 在 `len(chars) < n` 时返回 `[]`，`_query_terms` 兜底给 `terms = [blob]` 即 `["改"]`）→ `hits = 0` → `0 >= 1` 为假 → **零召回**；
- 此时只有 `q in hay or q in index` 那条快路径能救（`"改" in hay`），所以「单字查询能召回**正文含该字**的笔记」但**召回不到「只有 bigram 匹配」的笔记**。

这条路径与 F4 无关（是 `min_or_hits` 的既有设计），但它证伪了「召回集完全由重排之外的逻辑决定」——**门槛本身就是召回决策**。

**② 路径二（重排间接影响召回）：`score_note` 的返回值同时参与「过滤」判断**——**此说法需修正**

严格读代码后可以确认：`reweight` 只传入 `score_note`（`:251`），而 `score_note` 的结果**只进 `scored` 列表、不进 `_matches`**。所以 F4 的封顶公式（`min(count, 3)`）**确实只影响排序**。

但**同文件另外两个检索函数把 score 用作了筛选门槛**——`search_session_notes`（`:373-423`）与 `search_rollout_summaries`（`:480-528`）：

```python
		if not _matches(hay, "", q, terms, require_all, min_or_hits):
			continue
```

它们的 `index` 实参是**空串** `""`。也就是说：**在这两个函数里，「索引平面」这一路匹配完全失效**——`q in index` 与 `t in index` 永远为假，`_matches` 退化为**只能在 `hay` 上匹配**。而 `hay` 在 `search_session_notes` 里是：

```python
		hay = _normalize_query(f"{title} {text}")
```

这一点与 `search()` 不同（后者 `hay` 含 `type/title/content/id` 四段）。**结论**：`search_session_notes` / `search_rollout_summaries` 的召回集**更窄**（没有索引平面兜底），且与 `search()` 的口径不一致。

**所以对注释的正确表述是**：

| 声称 | 实际 |
|---|---|
| 「F4 重排只为排序服务，绝不改召回集」 | 对 `search()` 成立（`score_note` 结果不进 `_matches`） |
| | 对**同文件另两个检索函数**，由于 `index=""`，其召回机制**与 `search()` 不等价**——这不是 F4 造成的，但是「召回集由谁决定」这一问题的真实分歧点 |
| | 注释写在 F4 段落，但 F4 的 `query_reweight_score` 也被 `search_session_notes`（`:410`）与 `search_rollout_summaries`（`:515`）调用，所以 F4 的作用面**跨三个函数**，而注释只在 `search()` 的语境里成立 |

**另有一条**真正会影响召回的**排序侧**机制：`hits = [n for _s, n in scored[: max(1, int(top_k))]]`（`:253`）——`top_k` 的截断**发生在排序之后**，所以**排序顺序直接决定哪些笔记进入最终结果**。若把 `top_k` 视为「召回集」（它确实是调用方拿到的东西），那么 F4 的封顶公式**必然改变最终结果**：一篇「重复单一词」的笔记排序下降后可能掉出 `top_k`。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于区分三个层次：

| 层次 | 由谁决定 | 是否受 F4 影响 |
|---|---|---|
| 候选池 | `load_notes_for_search`（域合并 + scope 过滤）+ `status == "active"` + `note_type` 过滤 | 否 |
| 通过门槛者（`scored`） | `_matches`（`q` 快路径 / `require_all` / `min_or_hits` + `_term_hit` 长度闸） | **否**（F4 不参与） |
| 最终返回（`hits`） | 排序后 `[:top_k]` | **是**（排序变了，谁进 `top_k` 就变了） |

所以「F4 不改召回集」这句话，取决于把「召回集」定义在第二层还是第三层：

- 定义在第二层 → **成立**（F4 确实不参与 `_matches`）；
- 定义在第三层（调用方实际拿到的）→ **不成立**（`top_k` 截断让排序成为结果的决定因素）。

**工程上更准确的表述**应该是「F4 只改排序；但由于结果按 `top_k` 截断，排序变化会改变最终交付的条目」。这是一个**措辞精度**问题，不是实现缺陷——但它值得记，因为读代码的人若照注释相信「召回不受影响」，就会在排查「为什么这条笔记检不到了」时找错方向。

★ 顺带指出 `search_session_notes` / `search_rollout_summaries` 的 `index=""`（`:406,511`）：这是一个**真实的口径不一致**（`search()` 有索引平面兜底，这两个函数没有）。它不属 F4，但属同一类「注释与实现的作用面对不上」的问题，本批列为待确认项（需确认这是有意为之——session 笔记确实不该用 memdir 索引匹配——还是遗漏）。



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

### XEYO-QA-0440 Memory 索引块的一行化

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | runtime Memory 索引块 | 摘要一行 + 围栏 | 困难 | 代码阅读 | `python/memory/runtime.py:1201-1263` |

**面试官提问**
`_memory_index_block` 生成的块长什么样？它为什么只输出**计数摘要**而不列条目标题？块头的措辞承担什么职责？

```python
MEMORY_INDEX_HEADER = "# Memory index (background only — NOT the user request)"
```

**参考答案要点**
`runtime.py:1229-1251`（原文，注释即设计说明）：

```python
def _memory_index_block(index_text: str | None) -> str:
	"""组装 Memory index T_now 块（P0：B1 一行化 + C1 围栏 + C2 去条件化）。

	- C1 围栏：摘要数据包在 ``<memory_index readonly>`` 内，与 tool_output /
	  user_message 围栏同一房风（prompt/fence.py）——弱模型对「标签内=引用数据」
	  有训练级先验，比文字声明可靠。
	- C2 退役（2026-09-09 用户裁决维持下线）：本块不再常驻注入（生产恒关），
	  也不再携带「禁止/仅当/否则忽略」条件式指令文本——引擎文本不承载行为护栏
	  （铁律 5）。围栏 + 块头即身份来源；若将来源码级重开，正文保持纯信息。
	- 块头保留 ``# Memory index`` 前缀：query_loop._content_parts 的用量统计
	  与既有测试断言依赖该前缀。
	"""
	digest = _memory_index_digest(index_text)
	if not digest:
		return ""
	# 正文止于摘要行：来源由块头「background only — NOT the user request」与
	# readonly 围栏承担；不带任何行为指令（2026-09-09 铁律 5，恒关）。
	return (
		f"{MEMORY_INDEX_HEADER}\n"
		'<memory_index readonly="true">\n'
		f"{digest}\n"
		"</memory_index>"
	)
```

**块的最终形态**（三行）：

```
# Memory index (background only — NOT the user request)
<memory_index readonly="true">
Memory index: 12 entries (user 4, project 5, feedback 2, reference 1) · 检索: Memory(action=search)
</memory_index>
```

**摘要行的生成**（`_memory_index_digest`，`:1204-1226`）：

```python
	"""把 MEMORY.md 原文压成一行计数摘要；无条目返回空串。

	P0（B1 一行化）：索引块只回答「有什么类型、各多少条、怎么取」，
	条目标题 / 路径一律不进投影——条目正文属于 topics/*.md，检索走 Memory 工具。
	背景：整份索引尾插在用户文本后、贴近生成点，弱模型会把条目当成任务对象
	（实测 glm-4.5-air 把「帮我修改」绑定到记忆条目上，见会话 sess_mtiche8l）。
	"""
```

实现（`:1212-1226`）：逐行跳过空行与 `#` 开头行；用 `re.match(r"\[([A-Za-z_]+)\]", s)` 抽类型名（**抽不到则归 `"other"`**）；统计计数；无计数返回 `""`；输出格式：

```python
	return f"Memory index: {total} entries ({parts}) · 检索: Memory(action=search)"
```

其中 `parts` 按「计数降序、类型名字典序」排列（`sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))`）。

**为什么只给计数**：注释里的实测事故——**`glm-4.5-air` 把「帮我修改」这个请求绑定到了记忆条目上**（会话 `sess_mtiche8l`）。原因是整份索引**尾插在用户文本之后、贴近生成点**，条目标题（形如 `[project] 帮我修改 xxx → topics/...`）在位置上非常像用户指令的一部分。改成「只剩计数 + 一句检索指引」后，条目标题不再进入模型可见面，事故的触发面消失。

**块头的职责**：`MEMORY_INDEX_HEADER = "# Memory index (background only — NOT the user request)"`（`:1201`）——用**英文括注**声明「这是背景，不是用户请求」。这是「**只给信息、不给指令**」的措辞：它不是「忽略这条」的命令，而是对**这条数据是什么**的描述。

**两侧的兼容约束**（注释里两条 must）：

1. **块头必须保留 `# Memory index` 前缀**：「`query_loop._content_parts` 的用量统计与既有测试断言依赖该前缀」——即有个下游在处理「这是记忆索引块」时靠前缀识别；
2. **正文止于摘要行**：不带任何「禁止/仅当/否则忽略」的条件式指令（铁律 5：引擎文本不承载行为护栏）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题最值得带走的是「**同一个信息放在不同位置，风险完全不同**」这个观察。条目标题本身没有错，问题出在**它的位置**：尾插在用户文本之后、紧邻生成点，于弱模型的位置先验里就变成了「用户刚说的东西」。解法有三条可选：

| 解法 | 代价 |
|---|---|
| 换位置（放到历史里） | 索引每变一次就 miss 一大段 KV 前缀（见 0441） |
| 换措辞（加「忽略」指令） | 违反铁律 5（引擎文本不承载护栏） |
| **删内容（一行化）** | 失去「让模型看到有哪些记忆」的提示 |

代码选了第三条——即「**能不给模型看就不给**」（AGENTS.md 铁律 4「能静默就不说话」）。代价是模型不知道有哪些记忆条目，需要它主动调 `Memory(action=search)`——而这恰好也是摘要行末尾那句 `· 检索: Memory(action=search)` 的作用（**信息性指引**：告诉模型「要拿条目就用这个」，不是命令）。

★ 注意 `readonly="true"` 围栏的机制说明：「弱模型对『标签内=引用数据』有**训练级先验**，比文字声明可靠」——即围栏的作用不是给模型下指令，而是**利用训练分布**让模型把内容当引用数据。这与铁律 5 并不冲突（它不是引擎文本里的护栏，是数据结构上的身份标记）。



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

### XEYO-QA-0441 索引注入改挂 T_now 的 KV 理由

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | runtime 索引注入位置 | system 左段 vs T_now | 困难 | 场景设计 | `python/memory/runtime.py:1266-1282` |

**面试官提问**
`_append_memory_index(messages)` 把索引块**投影尾插**到消息里，而不是放进 system 左段。请说明代码给出的理由，以及这条选择的代价。

```python
def _append_memory_index(messages: list[dict]) -> list[dict]:
	"""把易变的 MEMORY.md 导航索引放到投影 T_now。

	system 左段不再嵌索引：任何 MemoryWrite/Forget 改索引都会让后续整个请求
	（system+对话）从改点起 miss。挂到 T_now 后索引变化只影响本轮尾部。

	末条是 tool 时由 ``append_text_blocks_to_last_user`` 投影尾插一条 user，
	不修改入参列表与既有消息对象（避免污染 query_loop 投影缓存 / JSONL）。
	"""
```

**参考答案要点**
**理由（KV 缓存前缀）**：`MEMORY.md` 是**易变内容**——任何一次 `MemoryWrite` / `Forget` 都会改它。若把索引嵌在 **system 左段**（最靠前的部分），那么每次索引变化都会让**从改点起的整个请求**（system + 全部对话）缓存失效。挂到 **T_now**（投影尾部）后，索引变化只影响**本轮尾部那一小段**，前面的历史仍能命中缓存。

**KV 前缀机制的具体含义**：LLM 的 prompt cache 按**最长公共前缀**命中——前缀一致的部分可以复用，从第一个不同字节起全部 miss。所以「变化的字节位置越靠前，代价越大」：

| 放置位置 | 索引变化时 miss 的范围 |
|---|---|
| system 左段 | system 剩余部分 + **全部对话历史** |
| 对话历史中间 | 该位置之后的全部历史 |
| **T_now（投影尾部）** | 仅尾部这一点 |

**为什么必须挂在投影而不是"到别处"**：`T_now` 是本项目为「每轮可能变 / 随时可开关」的模型可见内容设计的注入管线（AGENTS.md：`python/prompt/pre_llm_inject.py`）。索引正是这类内容（每轮可能变），所以规则要求它走 T_now，而不是写进 system prompt 或拼进历史。

**不污染入参的细节**（`:1275-1282`）：

```python
	if not messages:
		return messages
	block = memory_index_context_block()
	if not block:
		return messages
	from prompt.turn_context import append_text_blocks_to_last_user

	return append_text_blocks_to_last_user(messages, [block])
```

`append_text_blocks_to_last_user` 做**投影尾插**：注释说明「不修改入参列表与既有消息对象（避免污染 `query_loop` 投影缓存 / JSONL）」——即它返回的是一份**新的投影**，原 `messages` 与其中的消息对象都保持不变。这一点很关键：如果原地 `append`，会污染投影缓存（见 `Snapshot.proj_cache`）和待落盘的 JSONL。

**代价三条**：

| 代价 | 说明 |
|---|---|
| ① **可见性弱** | 尾插意味着它**靠近生成点**（这正是 0440 那起事故的成因）——所以必须一行化（0440）来补偿 |
| ② **每轮多一条消息** | `append_text_blocks_to_last_user` 在末条是 tool 时会**额外投影一条 user**——所以投影的消息条数可能多于历史条数（投影 ≠ 历史） |
| ③ **不落盘** | 因为它不进 JSONL，所以「模型看过索引」这件事**不在转录里**——事后回看会话记录时，看不到当时注入的索引内容（可复现性下降） |

**深化讲解**（面试官参考，不要求候选人全说）
这道题是「**KV 前缀优化如何反向约束信息架构**」的典型案例。三条相互牵制的设计：

```
易变内容 → 必须走 T_now（管线纪律）
T_now → 尾插（缓存纪律）
尾插 → 贴近生成点（位置风险）
位置风险 → 一行化（0440 的补偿）
```

也就是说，0440 的「一行化」**不是独立的优化**，而是 0441 这条位置选择的**必要补偿**。读这两段代码时若只看一段，会分别得出错误的结论（以为一行化是省 token；以为尾插只是实现细节）。

★ 还要注意一个**语义上的边界**：注释说「索引变化只影响本轮尾部」——但**索引不变化时**，T_now 也是逐轮重放的（每轮都尾插同样的内容）。也就是说，**稳定的 T_now 内容不会破坏前缀**（因为它每次都在同一位置、同样的字节），变化的 T_now 才会。这解释了为什么 T_now 块被设计成「每轮都重新装配」而不是「只在变化时装配」——**前缀稳定靠的是字节一致，不是靠跳过装配**。



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

### XEYO-QA-0442 工具结果事实抽取的四个限额

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | session_md Key facts 抽取 | 逐层限额 | 困难 | 代码阅读 | `python/memory/session_md.py:403-444` |

**面试官提问**
`_tool_paths_and_facts(messages)` 从工具结果里抽取「Key facts」。它有哪些限额？为什么每个工具结果只取**前 4 个路径**与**前 4 组取值**？最后的 `[:12]` 与循环内的两次 `>= 12` 判断是什么关系？

**参考答案要点**
`session_md.py:403-444`（原文）：

```python
def _tool_paths_and_facts(messages: list[dict[str, Any]]) -> list[str]:
    """从工具结果确定性抽取路径 / 取值事实（供 Key facts）。"""
    from memory.summarize import extract_tool_summary, extract_value_facts

    facts: list[str] = []
    seen: set[str] = set()
    path_re = re.compile(r"[\\/][\w.\-\\/]+?\.\w{1,8}")
    for msg in messages:
        if not _is_tool_msg(msg):
            continue
        content = msg.get("content")
        chunks: list[str] = []
        name = str(msg.get("name") or "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    chunks.append(str(block.get("content") or ""))
        for raw in chunks:
            for path in path_re.findall(raw)[:4]:
                key = path.strip()
                if key and key not in seen:
                    seen.add(key)
                    facts.append(f"path {key}")
            for k, v in extract_value_facts(raw, limit=4):
                line = f"{k}={v}"
                if line not in seen:
                    seen.add(line)
                    facts.append(line)
            if len(facts) >= 12:
                return facts
            # 短摘要一行（错误优先）
            brief = extract_tool_summary(raw, name, max_text=120)
            if brief and brief not in seen and len(brief) > 16:
                seen.add(brief)
                facts.append(brief)
                if len(facts) >= 12:
                    return facts
    return facts[:12]
```

**四个限额**：

| 限额 | 值 | 位置 | 作用 |
|---|---|---|---|
| 路径抽取上限 | `[:4]` | `:425` | **每个 chunk** 最多取 4 个路径 |
| 取值抽取上限 | `limit=4` | `:430` | **每个 chunk** 最多取 4 组 `k=v`（由 `extract_value_facts` 实现） |
| 短摘要文本上限 | `max_text=120` | `:438` | 摘要本身截 120 字符 |
| 短摘要**入列**门槛 | `len(brief) > 16` | `:439` | 太短的摘要不入列（防「ok」「done」这类噪音） |
| 总量上限 | **12**（三处：`:435`、`:442`、末行 `[:12]`） | `:435,442,444` | Key facts 最多 12 条 |

**为什么每个工具结果只取 4 + 4**：因为抽的是**「事实样本」而不是全部事实**。Key facts 是给模型看的七段之一（总长受 `_clip` 与模板约束），若把一个大 `Grep` 结果里的几百个路径全抽出来，这一段会变成**第二个 tool_result**——那就失去了「压缩成会话要点」的意义。取 4 个路径 + 4 组取值 + 1 条摘要，是「**每个工具结果贡献约 9 条候选**」，再由 12 条总量闸截断。

**三处 `12` 的关系（本题最容易读错的地方）**：

| 位置 | 形式 | 触发时机 |
|---|---|---|
| `:435` | `if len(facts) >= 12: return facts` | 每个 chunk 处理完**路径 + 取值**后 |
| `:442` | `if len(facts) >= 12: return facts` | 追加**短摘要**之后 |
| `:444` | `return facts[:12]` | 遍历结束后的**最终兜底截断** |

前两处是**提前退出**（早停，省后续解析），第三处是**最终保证**。为什么需要第三处？因为前两处的检查都发生在「追加动作之后」，而单次追加**最多只能让总数从 11 涨到 12**（每次 `append` 一个），所以前两处其实已经能保证不超 12……**除非** `facts` 在某次迭代里被追加了多于一个元素——而路径循环与取值循环各自可能追加多个：

```python
            for path in path_re.findall(raw)[:4]:       # 最多 4 次 append
                ...
            for k, v in extract_value_facts(raw, limit=4):   # 最多 4 次 append
                ...
```

在**路径循环**里没有 `len(facts) >= 12` 检查——所以一轮循环可以从 10 直接涨到 14。**因此末行的 `[:12]` 是必需的**（前两处检查不足以约束路径循环内部的增长）。这是一个真实的「检查位置与增长点不匹配」的细节。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的技术要点是**确定性抽取**（`:448`：「从消息确定性抽取七段；不 fork 摘要模型」）——它依赖两个外部函数：

- `memory.summarize.extract_value_facts(raw, limit=4)`：抽 `k=v` 形式的取值事实；
- `memory.summarize.extract_tool_summary(raw, name, max_text=120)`：生成短摘要（注释说「**错误优先**」）。

所以「抽什么事实」这一层的智能在 `summarize.py`（属 B10 范围），而本函数只负责**编排与限额**。

★ 还有一个**顺序偏置**值得注意：遍历顺序是**消息的时间顺序**（从最早到最晚），而 12 条上限会在中途 `return`。所以**早期工具结果里的事实优先入列，晚期的可能完全进不去**。对「Key facts」这个用途来说，这可能不是最优（晚期的工具结果往往更接近当前状态），但它与 `_extract` 里其他字段的选择是一致的——`goal` 取**第一条** user、`discoveries` 取**最后一条** assistant。也就是说本模块对「早 vs 晚」没有统一取向，逐字段不同。



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
### XEYO-QA-0443 A5 差分重写的原子性

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | session_md A5 差分重写 | delta 日志与物化 | 困难 | 场景设计 | `python/memory/session_md.py:204-232,270-327,485-537` |

**面试官提问**
A5 差分重写把「全量重写」改成「diff → 追加 delta → 工程侧合并」。请说明 delta 行（`session_deltas.jsonl`）的字段、物化文件的生成方式，以及「单条 delta 有误只废一条」这一说法为什么成立、边界在哪。

**参考答案要点**
**delta 行的字段**（`session_md.py:204-211` 的设计注释 + `append_delta` 的调用点）：

```
# - ``session_deltas.jsonl`` 每行 = {ts, turn, author, sections:{节头: 新节全文}}，
#   只记 **Changed 节**；物化 session.md = fold(deltas)（读者继续读物化文件，零改动）。
# - 单条 delta 有误只废一条：日志可回放/可截断（rewind 精确到 turn），不会一错到底。
# - Stage 2（模型 delta）预留：author 字段区分 det/model；本阶段只有 det。
```

写入（`:525-533`）：

```python
        append_delta(
            sid,
            {
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "turn": int(n_tools),
                "author": "det",
                "sections": changed,
            },
        )
```

| 字段 | 值 | 用途 |
|---|---|---|
| `ts` | 本地时区 ISO（秒精度） | 审计/追溯 |
| `turn` | `int(n_tools)`——**工具结果条数**，不是对话轮次 | 回滚截断的锚点（配合 0436 的 `count_tool_results_rows`） |
| `author` | `"det"`（确定性）；预留 `"model"` | Stage 2 模型 delta 的区分位 |
| `sections` | `{节头: 该节全文}`，**只含变化的节** | 合并的最小单位 |

**物化方式**（两步）：

① **只记 Changed 节**（`:517-523`）：

```python
        new_sections = _split_sections(text)
        old_sections = _split_sections(old)
        changed = {
            h: body
            for h, body in new_sections.items()
            if old_sections.get(h) != body
        }
```

② **工程侧合并 → 原子写物化文件**（`:534-535`）：

```python
    # ③ 工程侧合并：物化文件照常原子写（读者/C2 左段/peer 检索继续读它）
    _atomic_write_text(path, text)
```

注意这里的 `text` 是**全量 render 的结果**（`:508` 的 `text = _strip_forbidden(render(messages))`），而不是「旧文 + 合并 delta」的结果。也就是说：**物化文件写的是全量重写的结果，delta 日志只是并行记录的审计/回滚依据**。这一点与设计注释「物化 session.md = fold(deltas)」在**路径上不同**——只有当 `rebuild_from_deltas` 被显式调用（回滚路径）时，物化文件才是由 delta 折出来的（`:322-327`）。

**「单条 delta 有误只废一条」为什么成立**：因为每条 delta 是**独立一行 JSONL**，且合并单位是「节」：

- 坏行：`read_deltas` 用 `json.loads` 逐行解析，**坏行 `continue`**（`:293-296`）；
- 缺字段：`fold_deltas` 只接受 `isinstance(sections, dict)` 的行（`:314-318`）；
- 单节错：`fold_deltas` 按 `state[header] = body` 逐节覆盖，所以一条 delta 里某个节写坏，只影响那一个节的最终状态（其他节由更晚的 delta 或更早的值决定）。

**边界（三个）**：

1. **回放顺序**：`fold_deltas` 按**日志顺序**覆盖（后写胜），所以「错的 delta 之后没有更新的同名节 delta」时，错误会保留到最终状态——「只废一条」是指**不影响其他节**，不是「自动纠正」；
2. **不可回退的节**：若某节在 `old` 里**不存在**、在新的 `new_sections` 里存在，那它会被记为 changed 并成为该节的唯一来源——若这条 delta 丢了，该节在重建时**完全消失**（而不是回退到更早版本）；
3. **物化文件不依赖 delta**：正常路径下物化文件来自全量 render，所以「delta 日志损坏」**不影响正常读取**（读者读物化文件）——损害只在**回滚重建**时才显现。这是一条**很好的隔离**：日志损坏的可爆炸半径被限制在回滚路径。

**深化讲解**（面试官参考，不要求候选人全说）
A5 的动机是「**回滚不再失忆**」（`:164-166` docstring：「`keep_tool_calls=N`：**精确截断**——只保留 turn ≤ N 的 delta 并重放重建物化文件（回滚不再失忆）」）。旧行为是整删 `session.md`——一旦回滚，模型就丢掉了整段任务叙事。有了 delta 日志，回滚可以**重放到保留点**。

★ 这解释了为什么 `turn` 用**工具结果条数**而不是对话轮次：回滚的截断点来自转录（`count_tool_results_rows` 数的是转录里的工具结果行数），所以 delta 的 `turn` 必须用**同一把尺子**才能对齐。这是一个**跨模块的度量约定**——若将来转录侧的计数口径改了（例如改数 assistant 轮次），delta 的 `turn` 语义就必须同步改。

**Stage 2 预留**：`author` 字段当前只有 `"det"`，注释写「Stage 2（模型 delta）预留：`author` 字段区分 `det`/`model`；本阶段只有 `det`」——即设计上允许**模型自己产出 delta**（更高质量的叙事更新），而合并点（`fold_deltas`）不需要改。这是「合并点与生产者解耦」的设计收益。



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

### XEYO-QA-0444 老化推进的最小滞后

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | runtime 老化滞后门 | 缓存 vs 清理的取舍 | 困难 | 场景设计 | `python/memory/runtime.py:48-50,215-219,229-236` + `python/engine/aging.py:19-27` |

**面试官提问**
老化边界推进要求「距上次推进至少 8 条新消息」（`AGING_MIN_ADVANCE_DEFAULT = 8`）。请论证这个门槛为什么存在、为什么不能更小，以及它与「老化本意（清掉旧工具结果以省上下文）」的张力在哪里。

**参考答案要点**
**常量与覆盖**（`runtime.py:48-50`）：

```python
#: 老化边界推进的最小滞后（消息数）：两次推进之间至少积累这么多新消息，
#: 保证推进是稀发事件、推进后投影字节稳定（设计 N≈8 的落地映射）。
AGING_MIN_ADVANCE_DEFAULT = 8
```

```python
def _aging_min_advance() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_TOOL_AGING_MIN_ADVANCE", "") or AGING_MIN_ADVANCE_DEFAULT))
	except (TypeError, ValueError):
		return AGING_MIN_ADVANCE_DEFAULT
```

门槛判定（`:234-235`）：

```python
	candidate = pair_safe_cut(messages, keep_tail_cut(messages))
	if candidate - int(working.c1_frozen_until) < _aging_min_advance():
		return False
```

**为什么存在（缓存论证）**：老化的实现方式是把冻结区之前的 `tool_result` **替换成存根**（`engine/aging.py:6`：「存根两档：近档富信息（工具名+id尾8位+净化摘要+中立指引），远档折叠短存根」）。替换意味着**已发送出去的投影字节发生变化**。而 KV 缓存按最长公共前缀命中——**推进边界越频繁，前缀变得越频繁，缓存命中率越低**。

注释把结论写死了：「保证推进是**稀发事件**、推进后**投影字节稳定**」。即门槛的作用是**把「需要改前缀」这件事摊薄**：每 8 条消息才付一次「前缀失效」的代价，中间 7 条消息的前缀保持稳定、可持续命中。

**为什么不能更小**：

| 值 | 后果 |
|---|---|
| `1` | 每轮都推 → 每轮前缀都变 → **缓存几乎永不命中**（等于关掉 KV 优化） |
| `2–3` | 命中窗口极短，收益被频繁失效抵掉 |
| `8` | 与「设计 N≈8」的映射一致（注释原文），是经验平衡点 |
| 过大（如 100） | 老化几乎不推进 → 旧 `tool_result` 长期占用上下文，**老化的省上下文收益消失** |

★ 注意 `max(1, ...)` 的下限：环境变量可以把它设成 1（**故意允许**「每轮推进」用于实验），但不能设成 0 或负数——设 0 会让 `candidate - c1_frozen_until < 0` 永远为假（即**永不推进**）？不——若阈值为 0，则任何 `candidate >= c1_frozen_until` 都通过，**每轮都推**。`max(1, ...)` 的作用是防止「传 0 表达不了『关闭推进』」这类歧义：想关闭应由 `XEYO_TOOL_AGING=0` 关掉整个老化，而不是把门槛设成 0。

**与老化本意的张力（本题的核心）**：

| 目标 | 要求 |
|---|---|
| 省上下文（老化本意） | **尽快**把旧 `tool_result` 换成短存根 |
| 保缓存（前缀稳定） | **尽量少**改已发送前缀 |

两者**直接冲突**。8 这个值就是这个冲突的平衡点：老化**滞后于**上下文压力 8 条消息——也就是说，**在这 8 条消息的窗口内，宁可继续让旧工具结果占着上下文，也不动前缀**。

而 `engine/aging.py` 的**两档存根**设计进一步细化了这个取舍：**近档**（富信息：工具名 + id 尾 8 位 + 净化摘要 + 中立指引）与**远档**（超过 `FOLD_AFTER = 64` 消息后退化为短存根）——即「越旧越短」，把省上下文的效果做在**空间维度**（同一位置放多少信息）而不是**时间维度**（多快替换）：

```python
#: 远档折叠：距冻结边界超过该消息数的存根退化为短形式（确定性，增量投影一致）
FOLD_AFTER = 64
#: 富存根摘要上限字符数（净化后）
STUB_SUMMARY_MAX = 60
```

**深化讲解**（面试官参考，不要求候选人全说）
这道题把「**缓存友好性是一种全局约束**」这件事讲清楚了：任何会修改「已经发出去的内容」的功能（老化、压缩、索引变化、指令变化）都必须回答同一个问题——**改了以后前缀还能命中吗？** 本项目的三处回答互不相同：

| 功能 | 修改的内容 | 对策 |
|---|---|---|
| 老化（本模块） | 已发送投影里的旧 tool_result | **滞后门 8**（稀发） |
| C2 压缩（B10） | 左区折叠成摘要 | **已压缩态跳过老化**（0433 第 2 条，避免一轮双改） |
| Memory 索引（0441） | 每轮注入的导航块 | **改挂 T_now 尾部**（把变化挪到最末） |

三者是**同一约束的三个解**——分别用「稀发」「互斥」「移位」三种手段。把它们放在一起看，就能理解为什么记忆层的很多「奇怪」设计（滞后门、跳过条件、尾插）其实都是**KV 前缀纪律**的产物。



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

### XEYO-QA-0445 投影计量与 legacy 字段的双轨

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | working/observe 投影双轨 | 全文 vs 计量 | 困难 | 场景设计 | `python/memory/working.py:45-59,75-77` + `python/memory/observe.py:55-115` |

**面试官提问**
`WorkingSnapshot` 里既有 `last_x_sim` / `last_x_sent`（**全文**），又有 `last_projection`（**计量**）。请说明两条轨道各自的消费者、更新时机与持久化面，以及为什么不能只留一条。

**参考答案要点**
**两条轨道的字段**（`working.py:75-77` 与 `:110-112`）：

```python
    last_x_sim: str = ""  # 上一轮送模型的 simulator 格式投影 X，用于热路径 Ĥ 预测
    last_action: str = ""  # 上一枪实际发送的动作：project / keep / C1 / C2
    last_x_sent: str = ""  # 上一枪实际发送投影的规范化 JSON，供下一枪 LCP / Ĥ 预测
```

```python
    # P1 缺失2：上一枪发送投影 X 的可重入计量（不存全文）。重启后 decide 用它算
    # lcp_keep，避免依赖易失的 last_x_sim 全文。随 flush/hydrate 持久化。
    last_projection: ProjectionDigest | None = field(
        default=None, repr=False, compare=False
    )
```

| 轨道 | 字段 | 形态 | 持久化 | 消费者 |
|---|---|---|---|---|
| **全文** | `last_x_sim` / `last_x_sent` | 规范化 JSON 字符串（整份投影） | 序列化进 `.working.json`（`_to_dict`，`:238,240`） | 热路径 LCP / Ĥ 预测（`observe.py:85-93`） |
| **计量** | `last_projection` | `ProjectionDigest`（哈希 + 3 个长度） | 序列化进 `.working.json`（`:255`） | **重启后** `decide` 算 `lcp_keep` |

**全文轨道的更新时机**（`observe.py:74,115`）：

```python
	x_sent = _canon(projected)
	...
	snap.last_x_sent = x_sent
```

`observe_shot` 在**每个模型请求**（与 `note_shot` 同一处）调用，用 `_canon`（`:31-36`）把投影规范化：

```python
def _canon(messages: list[dict[str, Any]]) -> str:
	"""实际发送投影的规范化字节序列（与 probe._canon 对齐，保证 LCP 可比）。"""
	try:
		return json.dumps(messages, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
	except (TypeError, ValueError):
		return ""
```

**关键点**：`sort_keys=True` + `separators=(",", ":")` —— 保证**同一投影每次得到同一字节序列**，这样 `lcp_tokens(x_sent, snap.last_x_sent)`（`observe.py:85`）的 LCP 长度才有意义。注释还说明它与 `probe._canon` **对齐**（跨模块的规范化契约）。

**为什么不能只留一条**：

| 只留 | 后果 |
|---|---|
| 只留**全文** | `.working.json` 体积随会话线性增长（每份投影可能是几十 KB～几百 KB 的 JSON）；且这些全文**在转录里已有**（重复存储） |
| 只留**计量** | 热路径无法算 LCP——因为 LCP 需要**逐字节比对两份文本**，而计量只有长度与哈希，无法定位「从哪里开始不同」 |

所以两条轨道是**互补而非冗余**：

- 热路径要**精确**（LCP 是「最长公共前缀」的长度，必须逐字节比）→ 用全文；
- 冷路径（重启后）要**可用**（不能被易失状态卡住）→ 用计量 + `prefix_hash` 判「前缀是否变过」。

**`observe_shot` 的双模式**（`:67-71,76`）：

```python
	enabled: bool = True,
) -> None:
	"""记录一枪校准观测并更新 snap.last_x_sent（供下一枪 LCP）。

	enabled=False 时只更新 last_x_sent（供 Ĥ 预热），不落盘。
	"""
```

`enabled=False` 时**跳过校准落盘但仍更新 `last_x_sent`**——即全文轨道照常维护，只关掉「写 `calibration_events.jsonl`」。这进一步印证两条轨道的独立性。

**失败取向**（`:112-114`）：

```python
		except Exception:
			# 校准观测失败不阻塞热路径
			pass
	snap.last_x_sent = x_sent
```

注意 `snap.last_x_sent = x_sent` **在 `try` 块之外**——所以即使校准落盘抛错，全文轨道仍被更新。这是一个**有意的顺序**：把「必须发生的状态更新」放在异常处理之外，把「可选增强」放在里面。

**深化讲解**（面试官参考，不要求候选人全说）
这道题体现的是一条通用工程原则：**同一种信息可以有不同保真度的表示，用于不同时效的场景**。

| 维度 | 全文轨道 | 计量轨道 |
|---|---|---|
| 保真度 | 完整 | 近似（长度 + 哈希） |
| 时效 | 进程内（重启即失） | 跨重启 |
| 成本 | 大（写入 sidecar） | 小 |
| 能否回答「前缀变了吗」 | 能（逐字节） | 能（比 `prefix_hash`） |
| 能否回答「LCP 有多长」 | 能 | **不能** |

★ 注意 `last_projection` 的字段声明带了 `repr=False, compare=False`（`:110-112`）——与 `proj_cache` / `compact_checkpoint` / `_pending_c2_summary` 相同。这三处都用 `compare=False` 排除在 `dataclass` 相等比较之外，说明它们是**缓存/派生状态**，不参与「快照是否相等」的语义。这是一个小但一致的约定：**dataclass 的 `compare=False` 用来标记「不算状态的状态」**。



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
### XEYO-QA-0446 【超压】已删开关的残留与静默继承

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | memory_switches 残留键 | 三处防线与一条真实风险 | 超压 | 故障排查 | `python/memory/memory_switches.py:112-155,157-174,229-252` |

**面试官提问**
**故障背景**：项目在 2026-09-06 固化删除了 7 个记忆开关（`XEYO_C2_GATE` / `XEYO_V61_PARETO` / `XEYO_V61_SI` / `XEYO_V61_DYNAMIC_R` / `XEYO_C2_PRESSURE_FORMULA` / `XEYO_C2_GAIN_FORMULA` / `XEYO_C2_EXTEND_FORMULA`），另有一批「已固化开启」的键（`XEYO_MEMORY_SQLITE_INDEX` 等）也从注册表移除。请回答：①这些键**留在**用户的 `settings.json` 里现在会不会生效？②代码用什么机制防它们将来「复活」？③如果没有任何清理机制，具体会出什么事故？④`stale_keys` / `prune_stale` 在什么时候被调用？

**参考答案要点**
**① 现在不会生效（三处防线）**：

防线 1 —— **`get_value` 对未注册键返回空串**（`:166-167`）：

```python
	if key not in _DEFAULTS:
		return ""
```

防线 2 —— **`current()` 对 `runtime_reads=False` 的键强制报 ignored**（`:191-197`）：

```python
		if runtime_reads:
			effective = coerced
			source = "settings" if (key in store) else "default"
		else:
			# 已下线 / 恒关占位键：运行时恒为默认，settings 里的值一律被忽略。
			effective = default
			source = "ignored"
```

防线 3 —— **`save()` 显式拒绝未知键**（`:238-246`）：

```python
	for key, val in updates.items():
		if key not in _DEFAULTS:
			# 未知/已删键（如已固化开启的 A4/ω/⑮）一律拒绝，防 GUI/脚本误写回惰性残留。
			raise ValueError(f"未知记忆开关 {key!r}（已删除或不存在）")
		raw = str(val).strip().lower() if not isinstance(val, bool) else ("1" if val else "0")
		coerced = _coerce(key, raw)
		if coerced is None:
			raise ValueError(f"memory switch {key} 非法取值 {val!r}，允许 {_ALLOWED.get(key)}")
		mem[key] = coerced
```

**② 防复活的机制（两处）**：

机制 A —— **`save()` 的清理**（`:236-237`）：

```python
	# 顺带清掉已删/未知残留键：运行时本就不读，留着会被同名键将来复活时静默继承旧值。
	mem = {k: v for k, v in (data.get("memory") or {}).items() if k in _DEFAULTS}
```

机制 B —— **`prune_stale` 的显式清理**（`:118-154`），docstring 把风险写全了：

```python
	"""清理 home + workspace settings.json ``memory`` 段里的残留键，返回被删清单。

	为什么删：这些键**运行时本就不读**（``get_value`` 对未注册键返回空串），留着
	不生效、不报错、无清理入口；一旦同名键将来重新注册，历史残留值会被**静默继承**。
	删除因此是纯收益——不改变任何运行时行为。

	边界：
	- 只在确有残留时写盘（无残留 → 零写入，避免每次启动重写 settings.json）。
	- 只动 ``memory`` 段；``plugins`` / ``skills`` / ``mcp_servers`` / ``hooks`` 不碰。
	- best-effort：写盘失败只跳过该文件，不影响调用方（server 启动不应被阻断）。
	"""
```

**③ 若不清理会出的事故（「静默继承」的具体形态）**：

设想场景：某键 `XEYO_V61_SI` 在 2026-09-06 被删（该实验的 B1/B2/B3 证据门未过，恒关）。用户的 `settings.json` 里留着 `{"memory": {"XEYO_V61_SI": "1"}}`。

三个月后，团队决定重新引入一个**同名**开关（例如又做了一版 SI 实验，注册表里加回这个 key）。此时：

1. `get_value("XEYO_V61_SI")` 现在**返回 `"1"`**——因为这个键**又回到了 `_DEFAULTS`**；
2. 用户从未做过任何操作，但**旧值被静默继承**；
3. 表现是「**实验特性在部分用户机器上莫名其妙开启**」，且**没有任何提示**（无日志、无 UI 标记，因为 `source` 会报 `"settings"` —— 它确实是 settings 里的值）；
4. 排查成本极高：复现依赖「这个用户三个月前设过这个键」，而设置面板里当前没有任何地方显示它（若新版本把它标为 GUI 暴露项，用户会看到「开」但**想不起自己开过**）。

这正是 docstring 里那句「**静默继承旧值**（无提示、无清理入口）」的完整展开。注意它**不是**「旧值一直生效」——而是「**在键复活的那一刻起生效**」，所以事故的时间点与原因**相隔很远**，这是它难以排查的根本原因。

**④ `stale_keys` / `prune_stale` 的调用时机**：

- `stale_keys(cwd)`（`:112-115`）：**只读查询**，返回残留键名列表。docstring：「只读：`settings.memory` 中不属于注册表（已删 / 未知）的残留键。**不写盘**。」——它的用途是给调用方（server 启动流程 / GUI / 测试）**先看一眼**。
- `prune_stale(cwd)`（`:118-154`）：**清理**。目标文件两个：`home_settings_path()` 与（当能解析出 workspace 时）`workspace_settings_path(ws)`。三条边界：只在确有残留时才写盘；只动 `memory` 段；best-effort（`except Exception: continue`）。
- 另一个**隐式**时机：任何一次 `save(updates)` 都会顺带清理（机制 A）——所以「用户改任何记忆开关」都会顺手清掉残留。

★ 注意 `_resolve_cwd` 里的兜底（`:105-109`）：无显式 `cwd` 时用 `os.environ["XEYO_CWD"]` 解析工作区设置——所以 `prune_stale()` 不带参数时**未必**能清到工作区那份。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的核心是「**删除一个功能时，删除动作不止一处**」。一个开关的完整生命周期涉及**四个载体**：

| 载体 | 删除动作 | 现状 |
|---|---|---|
| 代码里的判断点 | 改/删函数体 | ✅（如 `c2_gate` 恒真） |
| 注册表条目 | 从 `MEMORY_SWITCHES` 移除 | ✅ |
| 用户 `settings.json` 里的值 | **`prune_stale` / `save`** | ✅（尽力而为） |
| GUI 面板里的显示项 | 按 `exposed` 过滤 | ✅（`exposed=False` 即不显示） |

本模块把**第三个**载体显式处理了——这在实践中非常罕见（多数项目只管前两个，任用户的配置里留垃圾）。而它给出的理由不是「整洁」，而是**一个具体的、延迟发生的故障**（同名键复活时静默继承）。

★ 还有一层**更细的防线**值得注意：`current()` 的 `source` 字段区分了 `"settings"` / `"default"` / **`"ignored"`** 三态，注释说「恒关键（`runtime_reads=False`）的 `effective` 恒为默认、`source` 报 `"ignored"`——**不再出现「显示开、实际关」**」。即：即使某个残留键**恰好在注册表里还留着占位**（如 `XEYO_MEMORY_INDEX_LIVE`，`:67`，`runtime_reads=False`），消费者（GUI）也能通过 `source == "ignored"` 知道「这个键的值不算数」。这是「**用状态字段表达『此值无效』**」的写法，比让 GUI 自己去判断 `runtime_reads` 更不易出错。



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

### XEYO-QA-0447 【超压】offload 的写入点与权限面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | offload 外部化与读回 | 阈值/路径/权限对照 | 超压 | 场景设计 | `python/memory/offload.py:17-52` + `python/tools/offload_read_tool.py:46-62` |

**面试官提问**
`memory/offload.py` 把超长工具结果卸载到文件，模型通过 `offload_read` 读回。请说明：①阈值与预览长度常量；②落盘目录与文件名；③`offload_enabled` 的**默认值是什么、判定方式与 `memory_switches` 的纪律是否一致**；④从「写侧」与「读侧」两侧审视这条链路，指出权限面的不对称。

**参考答案要点**
**① 三个常量**（`offload.py:17-19`）：

```python
OFFLOAD_THRESHOLD = int(os.environ.get("XEYO_TOOL_OFFLOAD_CHARS", "128"))
_PREVIEW = int(os.environ.get("XEYO_TOOL_OFFLOAD_PREVIEW", "128"))
_ENV = "XEYO_TOOL_OFFLOAD"
```

`OFFLOAD_THRESHOLD` 默认 **128 字符**（可由 `XEYO_TOOL_OFFLOAD_CHARS` 覆盖）；预览长度默认 **128**（`XEYO_TOOL_OFFLOAD_PREVIEW`）。★ 两者都在**模块导入时**求值（模块级 `int(...)`），所以运行期改环境变量**不生效**——与 `tools/spill.py` 的 `spill_root()`（函数内读 env）形成对比。

**② 落盘目录与文件名**（`:31-35,42-44`）：

```python
def _offload_root() -> Path:
	base = os.environ.get("XEYO_OFFLOAD_DIR", "").strip()
	if base:
		return Path(base)
	return Path(os.getcwd()) / ".xeyo_offload"
```

```python
	p = _offload_root() / f"{msg_idx}_{_safe(uid)}.tool.txt"
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(raw, encoding="utf-8")
```

默认目录是 **`<当前工作目录>/.xeyo_offload`**（不是 `~/.xeyo/...`！）；文件名 `{msg_idx}_{safe(uid)}.tool.txt`，其中 `_safe` 是 `re.sub(r"[^A-Za-z0-9_.-]", "_", s or "x")[:40]`（`:27-28`）。

**③ `offload_enabled` 的默认值与判定方式**（`:22-24`）：

```python
def offload_enabled() -> bool:
	"""L3 offload 是否开启（旁路默认关，字节稳定不因未读工具破坏）。"""
	return os.environ.get(_ENV, "").strip().lower() in ("1", "true", "yes", "on")
```

**默认关**（旁路），判定方式是**直接读 `os.environ`**。

★ 与 `memory_switches` 的纪律**不一致**：`memory_switches` 明确规定「**环境变量一律不再参与**（包括合法非空值）——彻底杜绝『忘删 / 不知名位置残留的环境变量』影响运行时开关」（`memory_switches.py:160-162`），且 `l5_flag` / `aging` 都已改成走 `get_value`。而 `offload.py` **仍直接读 env**，并且这个键**不在 `MEMORY_SWITCHES` 注册表里**（注册表只有四个键，见 0401）。所以：

- `XEYO_TOOL_OFFLOAD` 属于「**未经注册表治理的环变开关**」；
- 它不会被 `stale_keys` 发现（因为 `stale_keys` 只扫 settings.json 的 `memory` 段），也不会被 `prune_stale` 清理；
- 它受 0446 所述同一类风险影响（忘删的 env 会让某台机器长期开着 offload），只是载体从 settings.json 换成了环境变量。

**④ 权限面的不对称（两侧对照）**：

| 侧 | 组件 | 校验面 |
|---|---|---|
| 写 | `maybe_offload`（本模块） | **无任何权限检查**——直接 `mkdir` + `write_text` |
| 读 | `offload_read.execute`（`offload_read_tool.py:46-62`） | 只有 `is_file()` 与 `read_text` 的 `OSError`；**无 `check_permissions`、无路径狱、无尺寸/令牌闸门** |

即这条链路的**两侧都没有走 `permissions.filesystem`**：

- 写侧落在 `.xeyo_offload/`（工作区内）——但**路径由 `_offload_root()` 决定**，而它可被 `XEYO_OFFLOAD_DIR` 指向**任意目录**（包括工作区外），且**没有任何路径校验**；
- 读侧的路径来自模型传入的 `input["path"]`（`offload_read_tool.py:48`：`Path(str((input or {}).get("path") or "")).expanduser()`），`expanduser` 允许 `~` 展开——所以**可读任意绝对路径**（含工作区外与密钥文件）。

**事故链（组合起来看）**：

1. 若某台机器的环境里残留 `XEYO_TOOL_OFFLOAD=1` 与 `XEYO_OFFLOAD_DIR=D:\shared`，则**超 128 字符的工具结果被写进工作区外的共享目录**——内容是模型的工具输出（可能含源代码、路径、错误信息）；
2. 读侧不需要知道 offload 是否开启——`offload_read` 是**注册但隐藏**的工具（`exposure=hidden`），模型的幻觉调用或注入诱导都能触发它，读取任意路径；
3. 且由于 `is_error` 结果的措辞是 `(offload 文件不存在: {p})`（`offload_read_tool.py:50`）——**这个错误信息会回显路径**，可以当作一个**存在性探测 oracle**（试探某路径是否存在）。

**修复方向（只描述方向）**：①给 `maybe_offload` 加工作区边界约束（或至少在 `XEYO_OFFLOAD_DIR` 越界时拒绝并静默降级为不 offload）；②给 `offload_read.execute` 加与 `Read` 同一套 `filesystem.check_read_permission_for_tool`（B04-0200 已给出同一修复方向）；③把 `XEYO_TOOL_OFFLOAD` 纳入 `MEMORY_SWITCHES` 注册表（或至少改成 `get_value` 口径），让它可以被 GUI 治理与残留清理；④错误信息不回显完整路径（或只在权限通过后回显）。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的价值在于**把两个各自看起来"小事"的问题串成一条链**：

- 单看 `offload.py`：「一个旁路开关直接读 env」——像是个小的一致性问题；
- 单看 `offload_read_tool.py`：「一个 hidden 工具少了几行校验」——像是个小疏漏；
- **合起来看**：一个是**可把内容写出工作区**的通道，另一个是**可把任意文件读进来**的通道，两者共享同一个文件命名约定与目录结构——于是形成一条**双向的、绕过 `permissions.filesystem` 的数据通道**。

这正是安全审计里最典型的「**单点合规、组合越界**」形态。它也解释了为什么 `docs/全项目BUG排查-20260910.md` 把 `TOOL-01` 标为「P1 high（已复核）」——单看那个工具确实只是「与 `Read` 不对等」，但放在本模块的写侧一起看，威胁模型就完整了。

★ 与 B04-0200 的关系：那一题从「同能力域对称性」角度论 `offload_read` 缺权限；本题从「**链路组合**」角度补上写侧。两题共同构成这条链路的完整审计，且**答案不重复**（一个讲对称性方法，一个讲组合越界）。



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

### XEYO-QA-0448 【超压】老化默认关：删除已实现、恢复未实现

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | engine/aging 开关与取舍 | 默认关的根因 | 超压 | 场景设计 | `python/engine/aging.py:1-52` + `python/memory/memory_switches.py:46` |

**面试官提问**
`aging_enabled()` 的默认是**关**，且注释给出的理由是「toolout 占位的恢复机制落地前保持关闭，避免原文不可找回」。请说明：①判定方式；②「删除能力已实现、恢复能力未实现」具体指什么；③如果**强行打开**（`XEYO_TOOL_AGING=1`）会出现什么具体后果；④代码里还有一处会**加剧**这个后果的豁免规则，是哪一处。

**参考答案要点**
**① 判定方式**（`engine/aging.py:40-52`）：

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

`ENV_KEY = "XEYO_TOOL_AGING"`（`:19`）。判定走 `memory_switches.get_value`（注册表里的键，`:46`：「工具结果老化：压缩后冻结区仍可**按窗口紧追推进**（默认关）」），默认 `"0"` → `raw = "0"` → 非空 → `"0" in (...)` 为假 → **返回 False**。`ENV_KEY` 常量名虽叫 ENV，但取值**不读 `os.environ`**（遵守 0405 的纪律）。

**②「删除已实现、恢复未实现」**：

- **删除（替换）已实现**：`engine/aging.py` 有完整的两档存根规格（`:6`「存根两档：近档富信息（工具名+id尾8位+净化摘要+中立指引），远档折叠短存根」）与配套常量（`FOLD_AFTER = 64`、`STUB_SUMMARY_MAX = 60`、`EXEMPT_TOOLS`，`:22-27`），以及摘要净化正则（`_TAG_RE` / `_WS_RE`，`:29-30`）与统计计数器（`_stats`，`:32-37`）。也就是说「把旧 `tool_result` 换成存根」这件事**能跑**。
- **恢复未实现**：docstring 明确写「`logs/toolout` **文件级恢复为后续增强**（见设计文档前置依赖①）」（`:12`）。而「原文从投影消失」之后，模型要拿回原文必须**重跑工具**——`:10-11` 说：「恢复语义（v1）：所有被老化工具均可重跑再生；但存根本身保持中性措辞（"answer from remaining context"），不主动劝导重跑，避免 harness 诱发重复检索。」

即：**恢复的唯一途径是「重新执行工具」**，而这在没有文件级恢复的情况下意味着：对于一个**非幂等或成本高**的工具（例如跑了一次构建、查了一次变动的状态），原文**永久不可找回**。

**③ 强行打开的具体后果**：

| 后果 | 机制 |
|---|---|
| **原文不可找回** | 冻结区之前的 `tool_result` 被换成存根；旧内容只剩摘要（近档 60 字符上限、远档更短）。若模型后续需要细节，只能重跑工具 |
| **重跑可能得到不同结果** | 工具输出本身带时间性（`git status`、目录列表、时间戳、随机 id），重跑 ≠ 原值。所以这不是「恢复」而是「重新观测」 |
| **KV 前缀反复变动** | 老化推进改已发送前缀（见 0444）；强行开启且门槛设小会让缓存几乎不命中 |
| **证据链断裂** | 与 spill 的纪律直接冲突（`spill.py:11-12`「宁可超预算，不可假证据」）——老化把**投影里**的证据换成摘要，而 spill 拼命把证据**留下来**（默认保留 7 天）。两者方向相反 |

**④ 会加剧后果的那条豁免规则**：`engine/aging.py:7` 与 `:26-27`：

```python
- 豁免：is_error 结果、TodoWrite/AskUserQuestion 等结构化结果不老化
```

```python
#: 结构化结果豁免集（UI dock / 挂起语义依赖其原文）
EXEMPT_TOOLS = frozenset({"TodoWrite", "AskUserQuestion"})
```

**为什么它「加剧」**：豁免 `is_error` 结果意味着**错误原文保留、正常输出被删**——即老化后的上下文里，**失败信息的占比被系统性放大**。这是「反向保真」：最该被压缩的（冗长成功的输出）被压缩了，最需要上下文（错误详情）的没压；同时模型看到的历史变成「错误密集」的，可能**高估失败率**。注释对 `EXEMPT_TOOLS` 的豁免理由给了正当解释（「UI dock / 挂起语义依赖其原文」——那是引擎自己的 UI 需要），但 `is_error` 的豁免理由在 `:7` 只列了事实，未给论证。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的核心是「**一个功能的能力边界不完整时，默认关是正确取向**」。老化的**收益**是省上下文；**代价**是原文不可找回。当「找回」这条配套能力缺失时：

```
净收益 = 省下的 token − （不可找回造成的重跑成本 + 信息失真风险）
```

而在**没有恢复机制**的前提下，第二项**无法估算上界**（取决于模型后续要不要细节、工具是否可重跑、重跑是否幂等）。所以「默认关」不是保守，而是**在收益/代价不对称时选择可逆方向**。

★ 这与 AGENTS.md 的新功能准入规则（「新行为先以旁路形态上线验证收益，有数据证明收益后才并入主链路」）完全一致——老化是**已实现但未并入**的旁路，缺的正是「恢复机制」这块前置依赖。

★ 另一个值得记的点：**默认关的键仍然留在注册表里**（`memory_switches.py:46`，`runtime_reads=True`、`exposed=False`），所以它**可以被 `save` 打开**（测试/评测用），只是不出现在 GUI。也就是说「默认关」是**产品默认**，不是**能力禁用**——这解释了为什么 0433/0444 那些守卫代码必须保持正确（它们随时可能被打开）。



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

### XEYO-QA-0449 【超压】记忆读路径的注入面与工作区隔离

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | 记忆内容的注入面 | 写入源与围栏 | 超压 | 安全拷问 | `python/memory/runtime.py:1201-1263` + `python/memory/session_md.py:36-42` + `python/memory/memdir.py:454-477` |

**面试官提问**
记忆内容（`MEMORY.md` 索引摘要、`session.md` 七段、`topics/*.md` 笔记）会被注入模型上下文。请回答：①这些内容**可能来自哪里**（写入源）；②索引块靠什么机制防止被误当作用户请求；`session.md` 靠什么？③`is_under_memdir` 提供什么保证、它**不能**保证什么？④如果一条记忆笔记里被写入了针对模型的指令文本，防线的现状如何。

**参考答案要点**
**① 写入源**（至少六条）：

| 源 | 入口 | 是否经模型 |
|---|---|---|
| 模型自己的工具调用 | `memory_tool` → `memdir.write_note` | ✅ 模型内容 |
| 用户显式指令 | 用户在对话里要求记住某事 | ✅ 经模型转写 |
| 子 agent 收割 | `AGENT_HARVEST_EVIDENCE`（`governance.py:14-17`） | ✅ 模型内容 |
| NightShift 离线重塑 | `source.kind == "nightshift"` | ✅ 模型内容 |
| 工具结果抽取 | `session_md._tool_paths_and_facts` 从 tool_result 抽路径/取值 | ⚠️ **间接**——工具结果本身可能包含外部内容 |
| 会话归档 | `archive_session_rollout`（`session_md.py:96-137`） | ✅ 转写自 session.md |
| diff 佐证打标 | `verified_by_diff`（P3，对照真实 git 改动） | ⚠️ 半自动 |

★ 关键点：**几乎每一条写入源最终都经过模型**。所以「记忆内容」在注入时是**模型自己（或同类模型）产出的文本**——这与「用户输入」的信任级别**不同也不同**：它更可能是**指令形态**（因为是模型写的），但来源上又是「内部」的。

**② 索引块的防误当机制**（`runtime.py:1246-1251`）：

```python
	return (
		f"{MEMORY_INDEX_HEADER}\n"
		'<memory_index readonly="true">\n'
		f"{digest}\n"
		"</memory_index>"
	)
```

两道：**块头文字**（`HEADER = "# Memory index (background only — NOT the user request)"`，`:1201`）与 **`<memory_index readonly="true">` 围栏**。注释解释围栏的机制（`:1232-1234`）：「弱模型对「标签内=引用数据」有**训练级先验**，比文字声明可靠」。加上**一行化**（0440）：条目标题不进投影——即**最容易被误当任务的内容被直接删掉**。

**`session.md` 的防误当机制**（`session_md.py:36-42`）：

```python
_FORBIDDEN = (
    "compact_cursor",
    "prompt_cache",
    "hit_tokens",
    "- [ ]",
    "- [x]",
)
```

靠**内容净化**：禁止写入机器字段与 todo 复选框（其中 `- [ ]` / `- [x]` 正是**任务形态**的标记）。也就是说 `session.md` 防的是「**像任务的东西**」，而不是「像指令的东西」——两者的威胁模型不同。

**③ `is_under_memdir` 提供什么、不能提供什么**（`memdir.py:454-477`）：

```python
def is_under_memdir(path: str, *, wsid: str | None = None, cwd: str | None = None) -> bool:
    """路径是否落在（本工作区的）memdir 内。"""
    ...
    for root in roots:
        try:
            base = str(root.resolve())
        except OSError:
            base = str(root)
        prefix = os.path.join(base, "")
        if abs_path == base or abs_path.startswith(prefix):
            return True
    return False
```

**提供**：一个「路径是否在 memdir 内」的判定（用 `resolve()` 后的字符串前缀比较；`prefix` 用 `os.path.join(base, "")` 保证末尾分隔符）。

**不能提供**：

1. **它只判「在不在」，不判「能不能」**——它是**分类函数**而不是**权限闸**（返回 bool，不产生 `PermissionDecision`）；
2. **它不检查调用者身份**——任何持有 workspace id/cwd 的代码都能得到 True；
3. **`resolve()` 异常时退化**：`except OSError: base = str(root)`——此时比较的是未解析路径，**symlink 场景可能误判**（若 memdir 本身是 symlink）；
4. **它不管写**——本批未见它在写路径上被用作闸门（需确认，列为待确认项）。

**④ 如果笔记里被写入指令文本，防线现状**：

| 可能的防线 | 现状 |
|---|---|
| 写入时净化 | `write_policy.refuse_reason`（0413）只挡**目录树/临时计划**，**不挡指令文本** |
| 围栏 | `topics/*.md` 的正文注入**是否带围栏**，取决于装配方（`note_citation_text` 产出 `<citation_entries>` 块，`search.py:192-197`；而 `session.md` 走 C2 左段）。**未在本批读到的路径上看到统一的围栏要求** |
| 块头声明 | 只有 Memory 索引块有 `(background only — NOT the user request)`；`session.md` 与 note 正文无同类块头 |
| 提示词层 | `system_prompt` / `pre_llm_inject` 是否有「记忆内容不是指令」的声明 —— **属 prompt 层（B13）**，本批未核 |

所以**诚实的结论是**：记忆内容的「防指令注入」防线**目前不完整**。已知的三层是：写入侧的内容门禁（不针对指令）、索引块的双重标记（仅覆盖索引块）、以及可能的提示词声明（未核）。而**最容易被利用的路径**是：外部内容（网页/文件/工具结果）→ 模型转写为 note → note 进投影 → 后续轮次的模型把 note 里的句子当指令执行。这条路径上的**唯一强制点**是写入侧的 `write_policy`（一个纯启发式，且只挡两类内容）。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题要求把「记忆系统」放进**注入威胁模型**里看。三个层次必须分开：

| 层次 | 问题 | 现状 |
|---|---|---|
| **来源可信度** | 内容是谁写的？ | 六条源，**多数经模型**——所以内容天然可能是**指令形态**（模型爱写祈使句） |
| **载体隔离** | 注入时是否被标记为「引用数据」？ | 索引块 ✅（块头 + 围栏 + 一行化）；`session.md` / note 正文 ⚠️ 不统一 |
| **写入净化** | 写入时是否过滤危险内容？ | `write_policy` 只挡目录树/临时计划；`_FORBIDDEN` 只挡机器字段与 todo 复选框 |

即：**这套系统的防注入重心在「载体隔离」而不是「内容过滤」**——这是正确的取向（内容过滤永远可以绕过，而结构隔离是强制的），但**载体隔离目前只做了一半**（只有索引块完整）。

★ 与本项目既有理念的呼应：AGENTS.md 铁律 4 是「能静默就不说话——引擎自己能完成的事一律静默完成，不给模型看」，第一问永远是「**能不能不进上下文**」。按这条理念，最彻底的防注入是**把记忆内容从常驻上下文里拿掉**——索引块的一行化（0440）与常驻索引的下线（`XEYO_MEMORY_INDEX_LIVE` 恒关，`memory_switches.py:61-67`）正是这个方向。即：**这个项目对记忆注入的最终答案倾向于「少注入」而非「注入得更安全」**。



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

### XEYO-QA-0450 【超压】回滚后双 sidecar 的残留与重注入

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| memory 记忆 | 回滚一致性 | 三载体的清理责任 | 超压 | 故障排查 | `python/memory/working.py:431-488` + `python/memory/session_md.py:160-188` |

**面试官提问**
**故障报告**：用户对一个会话执行了「聊天回滚」（回滚到第 3 轮，删掉后面的对话）。回滚后：
① 转录 JSONL 里后面的对话确实没了；
② 但模型在下一次对话里**主动提到了被回滚掉的话题**；
③ 并且 `session.md` 里仍能看到被删掉的内容。

请给出**根因**（指出具体函数与字段）、**完整复现步骤**、**三条独立缺陷**、以及为什么这三个缺陷**必须同时修**才能消除故障。

**参考答案要点**
**根因**：回滚只截断了**转录 JSONL**，而「逻辑会话状态」还有**三个独立载体**没有被迫同步清理：`.working.json`（机器状态）、`session.md`（模型可见叙事）、`session_deltas.jsonl`（差分日志）。

**②的根因（模型提到被删话题）**——`working.py:459-465` 的英文 docstring 把机制写死了：

```python
def reset_after_rollback(session_id: str) -> None:
    """Drop compression / projection sidecar state after transcript rewind.

    Chat-only rewinds truncate JSONL but leave ``.working.json`` untouched unless
    we reset it here.  Stale ``c2_summary_text`` would otherwise re-inject
    truncated conversation back into the model via C2 projection.
    """
```

即：**旧的 `c2_summary_text`（C2 摘要）会在下一次 C2 投影里把「已被回滚掉的历史」重新注入模型**。摘要文本本身是「被压缩过的历史」——所以模型「记得」被删掉的话题。

**③的根因（`session.md` 仍有内容）**——`session_md.clear_after_rollback`（`session_md.py:160-188`）的 docstring 说明它有两个分支：

```python
    - ``keep_tool_calls=None``（缺省/无法计量）：旧行为——整文件删除（fail-closed）；
    - ``keep_tool_calls=N``：**精确截断**——只保留 turn ≤ N 的 delta 并重放重建
      物化文件（回滚不再失忆）；无 delta 可存（或从未 delta 化）→ 退回整删。
```

**如果这个函数根本没被调用**，`session.md` 原样保留 → ③成立。而 `session.md` 是**模型可见文本**（`session_md.py:1`「给模型看」），并由 C2 左段消费（`load` 的 docstring `:145-146`）——所以它同样构成一条「已删内容复活」的通道。

**完整复现步骤**：

1. 开一个会话，做 8 轮以上（越过 `MIN_TOOL_CALLS = 8` 的 session.md 重写门槛，`session_md.py:44`），其中包含至少 4 轮工具调用（让 `n_tools >= 8`）；
2. 继续聊到触发一次 **C2 压缩**（让 `working.compact_cursor > 0` 且 `c2_summary_text` 非空）——此时 `.working.json` 里有非空摘要，`trimmed` 的历史已被折叠进摘要；
3. 在后续轮次里引入一个**可识别的话题 X**（例如「XXYZ 方案」），让 X 进入 C2 摘要与 `session.md` 的 `## Important discoveries`；
4. 执行**聊天回滚**到第 3 轮（`POST /v1/sessions/{id}/rewind` 一类入口），确认 JSONL 里 X 之后的对话已消失；
5. 不要重启进程，直接发一条新消息（或重启后再发）；
6. **观测**：新消息得到的回复里出现「XXYZ 方案」等内容；同时 `cat ~/.xeyo/sessions/<id>/session.md` 仍能看到 X 的内容；`cat ~/.xeyo/sessions/<id>.working.json` 里 `c2_summary_text` 非空且含 X。
7. **反证**：手工把 `c2_summary_text` 置空并删 `session.md` 后重复第 5 步，X 不再出现。

**三条独立缺陷**：

| # | 缺陷 | 证据 | 后果 |
|---|---|---|---|
| 1 | **回滚入口未（或未总是）调用 `working.reset_after_rollback`** | 该函数 17 个字段归零（`:471-487`）是**正确的**，但它是**被调用才生效**；docstring 用英文写「unless we reset it here」暗示调用方可能漏 | ② 复活（经 C2 投影） |
| 2 | **回滚入口未（或未总是）调用 `session_md.clear_after_rollback`** | 同上；且该函数**两档**（整删 / 精确重建）都需要被显式调用 | ③ 复活（经 C2 左段 + 模型可见） |
| 3 | **`flush` 静默失败会让清理不落盘** | `working.py:431-456`：`except OSError` 只记 `logging.warning`（事故背书见 0437） | 即使调用了缺陷 1 的函数，**改动也可能没落盘**——下次启动回到旧状态 |

**为什么必须同时修**：

因为这三条是**并列的通道**，不是同一个 bug 的三种表现：

```
被回滚的内容 ──┬─→ 转录 JSONL（rewind 自己截断）✅
               ├─→ .working.json c2_summary_text ──→ C2 投影 ──→ 模型  ❌ 通道 1
               ├─→ session.md ────────────────────→ C2 左段 ──→ 模型  ❌ 通道 2
               └─→ session_deltas.jsonl ──────────→ 回滚重建时重放 ❌ 通道 3
```

- 只修通道 1 → 模型仍能从 `session.md` 里读到被删内容；
- 只修通道 2 → 模型仍能从 C2 摘要里看到；
- 只修通道 3 → `clear_after_rollback(keep_tool_calls=N)` 会**从 delta 重放出已被回滚的叙事**（`rebuild_from_deltas(sid, upto_turn=N)`，`:322-327`）——注意这一条尤其隐蔽：**delta 日志的 turn 语义必须与转录截断点一致**（见 0443/0436），若 `keep_tool_calls` 传错（例如传了 `None` 之外的错值），重建出的 `session.md` 会包含「本次应删掉」的节。

**修复方向（只描述方向）**：

1. **把「回滚」定义为一个跨载体的原子操作**：在回滚入口显式串联三个清理（`rewind` service 里），而不是靠各模块自觉；
2. **给清理加可验证的后置条件**：回滚后断言 `c2_summary_text == ""`、`compact_cursor == 0`、`session.md` 不存在或不含被删话题（这可以写成回归测试）；
3. **让回滚路径的 flush 可失败上报**：`reset_after_rollback` 里的 `flush` 应走一条会报错的变体（见 0437 的风险④），至少写入一条 `audit` 事件；
4. **考虑给 sidecar 加「回滚世代号」**：`compact_cursor` 与 `session_md_tool_epoch` 都基于「工具调用计数」这一个单调量，若在回滚时**不重置**而只是前进，就会出现「计数器比历史还大」的状态——用一个显式的 `rewind_epoch` 让所有基于计数的缓存知道自己已过期，比逐字段归零更不易漏。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的核心是「**删除一个东西，要删掉它的全部副本**」。回滚看起来是「删掉一些消息」，但被删消息的**派生表示**散落在至少四个载体里：

| 载体 | 派生自 | 谁负责清 |
|---|---|---|
| 转录 JSONL | 原始 | rewind 服务 |
| `.working.json` | 压缩/投影状态 | `reset_after_rollback` |
| `session.md` + `session_deltas.jsonl` | 叙事抽取 | `clear_after_rollback` |
| `read_file_state`（在 `.working.json` 内） | 工具先读状态 | `reset_after_rollback`（`snap.read_file_state = {}`，`:481`） |

**没有任何单一 owner 知道这四个载体**——清理责任分散在 rewind 服务与 memory 层的两个模块里，靠调用关系串联。这就是缺陷产生的结构原因（AGENTS.md 事故模板的第一问：「**结构性根因是什么？哪条规则能让它结构上不再发生？**」）。

结构性答案应该是：**为「会话状态」定义单一的回滚协议**（一个接口 / 一个世代号 / 一个注册表），让每个持有派生状态的模块**注册自己的回滚钩子**——这样新增一个 sidecar 时，「必须能被回滚」这件事成为**接口要求**而不是「记得去改另一个模块」。

★ 顺带一个观察：`reset_after_rollback` 归零的 17 个字段里包含 `speculation`（本回合假说）、`todos`、`tasks`、`read_file_state`、`compact_checkpoint`、`last_projection` 等——**这个清单的完备性本身就是维护负担**（每加一个字段就要记得加一行）。而它**没有**归零 `session_md_tool_epoch`？实际上归零了（`:482`）。但**没有**归零 `last_cache_hit_tokens` / `last_prompt_tokens` / `last_model_call_at`（这三个与压缩无关，合理）。也就是说这份 17 行清单是**手工维护的白名单**——这本身就是「结构性根因」的一部分。



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

## 批次自检表（B09）

| 项 | 结果 |
|---|---|
| 题号连续性 | XEYO-QA-0401 – XEYO-QA-0450，**无跳号无重号**（脚本比对 401..450 无缺口） |
| 难度配比实测 | 简单 **14** / 中等 **18** / 困难 **13** / 超压 **5** = **50** |
| 问法分布 | 机制解释 21 / 场景设计 12 / 概念确认 11 / 代码阅读 3 / 故障排查 2 / 安全拷问 1 = **50** |
| 覆盖子模块 | `runtime`（常量与老化边界段、Memory 索引块段）· `memory_switches` · `l5_flag` · `governance` · `session_md` · `working` · `memindex` · `memdir` · `search` · `instruction` · `journal` · `write_policy` · `observe` · `offload` · `cache_profile` · `engine/aging`（前 55 行）—— 共 **16 个文件** |
| 待确认条目 | **7 处**：① `@include` 与 `paths` 的**工作区边界检查**是否由上层承担；② `MEMORY.md` 字节截断在其它读者侧是否有额外校验；③ `memindex.edges` 表的钻取消费者是否存在；④ `XEYO_MEMORY_ROLLOUT_MAX=0` 被 `max(1,...)` 夹成 1 是否有意；⑤ `current_atoms.text` 是否有限幅；⑥ rewind 路径是否**必定**调用两个清理函数、是否有测试守住；⑦ `search_session_notes`/`search_rollout_summaries` 传 `index=""` 是否有意 |
| 边界遵守 | 未涉及 B10（C2 压缩执行、NightShift、summarize、simulator、L5 公式细节）、B06（`memory_tool` 工具入口层）、B07/B16（记忆开关的权限与扩展治理）、B14（`/v1/memory/*` 与 `/v1/settings/memory` 路由） |
| 未覆盖但已计划 | `citation.py`(209) 引用块渲染、`agent_scope.py`(349) / `subagent_memory.py`(312) 的子 agent 记忆域、`workspace_diff.py`(241) 的 diff 佐证通道、`instruction_maintain.py`(586) 嵌套指令维护、`token.py`(21) 与 `cache_profile.py`(30) 的占位语义、`pair_safe_cut`/`keep_tail_cut` 内部算法 → 归 B10 或补批 || 重复性检查 | 本卷题目考查点互不重复；与同能力域相邻卷的边界见上方「边界声明」 |
| 来源可追溯性 | 全部 50 题来源指向本批实际读过的 `文件:行号`；未出现推测性行号 |
