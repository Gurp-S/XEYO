# XEYO QA 题库 · 第 6 批（B06）

> 题号范围：**XEYO-QA-0251 – XEYO-QA-0300**
> 主题：其余工具族（Agent 子代理下发 · Skill 加载与目录 · TodoWrite 状态机与恢复 · Memory 工具入口 · WebSearch/WebFetch 与 SSRF 防御 · NotebookEdit · Git 只读/写动作 · Diagnostics 语言面与限额 · JournalQuery · AskUserQuestion 问答协议 · Screenshot · SendToWeChat · XeyoUI 面板与浏览器操作 · GetTime/Echo 定位 · orchestration 并发编排 · progress_sink · tools.meta 工具元数据）
> 难度配比：简单 16 / 中等 20 / 困难 12 / 超压 5
> 事实基线（本批实际打开读过的文件与实测行数）：
> `web_common.py`(215, 全文) · `web_fetch_tool.py`(248, 全文) · `web_search_tool.py`(543, 定义面全量 + 常量段) · `web_search_tool/config.py`(55, 定义面) · `agent_tool/agent_tool.py`(522, 28–177 精读 + 定义面全量) · `skill_tool/skill_tool.py`(285, 定义面全量) · `todo_write_tool/types.py`(63, 全文) · `todo_write_tool/todo_write_tool.py`(370, 定义面全量) · `todo_write_tool/restore.py`(131, 定义面全量) · `todo_write_tool/store.py`(30, 定义面) · `memory_tool/memory_tool.py`(549, 定义面全量) · `notebook_edit_tool.py`(379, 定义面全量) · `git_tool.py`(289, 定义面全量) · `diagnostics_tool.py`(423, 定义面全量) · `journal_query_tool.py`(116, 定义面全量) · `ask_user_question_tool.py`(188, 定义面全量) · `screenshot_tool.py`(118, 定义面全量) · `send_to_wechat_tool.py`(67, 定义面全量) · `xeyo_ui_tool.py`(359, 定义面全量) · `orchestration.py`(329, 定义面全量) · `progress_sink.py`(43, 定义面) · `base_tool.py`(82, 定义面) · `meta.py`(414, B04/B05 已精读其文件工具与 Bash 条目)
> **边界声明**：文件五件套（Read/Write/Edit/Glob/Grep）归 **B04**；Bash 家族（14 件）归 **B05**；`permissions` 三态裁决与 `bash_policy` 归 **B07**（本批只讲「工具如何声明只读/并发安全」以及工具内的 `check_permissions` 调用点）；`codeindex.symbols`（Grep `output_mode=symbols` 背后的符号抽取）归 **B15**；`memory/` 内部机制（memdir/memindex/search/governance 等）归 **B09/B10**——本批只讲 `MemoryTool` 的**入口层**（六个 action 的分派与校验）；`extension`（skill 的加载器/开关来源）归 **B12**；`server` 侧路由（`/v1/files`、`/v1/media/*`、`/v1/jobs`）归 **B14**；`tools/job_tools.py`（JobList/JobKill）与 Bash 的 registry 桥在 B05 已覆盖，本批不重复。
> **行号口径**：`agent_tool.py`(522) / `memory_tool.py`(549) / `web_search_tool.py`(543) / `diagnostics_tool.py`(423) 等采用「先 Grep 抽定义行号 → 再按 offset/limit 精读」；写题前复核的锚点见自检表。

---

## 本批题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0251 | 简单 | 机制解释 | 工具声明的两个静态方法 | `tools/base_tool.py` + 各工具 `is_read_only`/`is_concurrency_safe` |
| 0252 | 简单 | 概念确认 | Agent 的深度硬限制与并发门禁 | `agent_tool.py:32-35` |
| 0253 | 简单 | 概念确认 | `scope` 为空时的语义 | `agent_tool.py:137-144` + `:100-107` |
| 0254 | 简单 | 机制解释 | TodoItem 的五个字段与 UI 白名单差异 | `todo_write_tool/types.py:11-29` |
| 0255 | 简单 | 概念确认 | Todo 状态三值枚举 | `todo_write_tool/types.py:7-8` |
| 0256 | 简单 | 概念确认 | Skill 目录的四个字符上限 | `skill_tool/skill_tool.py:26-33` |
| 0257 | 简单 | 概念确认 | MemoryTool 的六个 action | `memory_tool/memory_tool.py:36` |
| 0258 | 简单 | 概念确认 | WebFetch 的下载上限与输出上限 | `web_fetch_tool.py:16-23` |
| 0259 | 简单 | 机制解释 | WebFetch 缓存的两个参数与键 | `web_fetch_tool.py:22-23,111` |
| 0260 | 简单 | 概念确认 | WebSearch 的默认结果数与片段上限 | `web_search_tool.py:23-27` |
| 0261 | 简单 | 机制解释 | Git 只读动作白名单 | `git_tool.py:12-18` |
| 0262 | 简单 | 机制解释 | Diagnostics 的五个限额与语言面 | `diagnostics_tool.py:19-24` |
| 0263 | 简单 | 概念确认 | XeyoUI 的六个面板与五个浏览器操作 | `xeyo_ui_tool.py:16-17` |
| 0264 | 简单 | 机制解释 | NotebookEdit 的 `.ipynb` 上限与空骨架 | `notebook_edit_tool.py:19-27` |
| 0265 | 简单 | 机制解释 | AskUserQuestion 的请求 id 键 | `ask_user_question_tool.py:19-21` |
| 0266 | 简单 | 概念确认 | Web 工具的私有主机拒绝清单 | `web_common.py:10-16` |
| 0267 | 中等 | 机制解释 | `is_blocked_url` 的六级判定 | `web_common.py:19-73` |
| 0268 | 中等 | 场景设计 | 每次重定向都重新校验 | `web_fetch_tool.py:130-156` |
| 0269 | 中等 | 机制解释 | `html_to_text` 的清洗顺序 | `web_common.py:76-114` |
| 0270 | 中等 | 机制解释 | `focus_text` 的段落打分与保留 | `web_common.py:117-215` |
| 0271 | 中等 | 机制解释 | WebSearch 的多后端与开关 | `web_search_tool.py:28-46` + `config.py` |
| 0272 | 中等 | 机制解释 | Agent 的 scope/required_tools 与角色 | `agent_tool.py:137-169` |
| 0273 | 中等 | 机制解释 | Agent 的 id 安全化与重试 | `agent_tool.py:68-80` + `:154-160` |
| 0274 | 中等 | 机制解释 | Todo 合并语义 | `todo_write_tool.py:91-106` |
| 0275 | 中等 | 机制解释 | Todo 的两条恢复路径 | `todo_write_tool/restore.py:20-131` |
| 0276 | 中等 | 机制解释 | Skill 的六道可见性闸 | `skill_tool.py:138-172,280-285` |
| 0277 | 中等 | 机制解释 | Skill 的目录与 list 两级响应 | `skill_tool.py:82-121` |
| 0278 | 中等 | 机制解释 | Memory 工具的检索与 peers | `memory_tool.py:41-122` |
| 0279 | 中等 | 机制解释 | NotebookEdit 的 cell 操作面 | `notebook_edit_tool.py:28-40,354-379` |
| 0280 | 中等 | 机制解释 | Git 写动作与输出压缩 | `git_tool.py:13-20,160-182` |
| 0281 | 中等 | 机制解释 | Diagnostics 的四级语言探测 | `diagnostics_tool.py:170-226` |
| 0282 | 中等 | 机制解释 | journal_query 的会话过滤 | `journal_query_tool.py:98-116` |
| 0283 | 中等 | 机制解释 | AskUserQuestion 的选项扁平化 | `ask_user_question_tool.py:24-89` |
| 0284 | 中等 | 机制解释 | orchestration 的并发分区 | `orchestration.py:31-109` |
| 0285 | 中等 | 机制解释 | Screenshot 的微信副本与图像判定 | `screenshot_tool.py:14-30` |
| 0286 | 中等 | 机制解释 | progress_sink 的进度上报 | `progress_sink.py` |
| 0287 | 困难 | 场景设计 | SSRF 判定的 TOCTOU 面 | `web_common.py:36-73` + `web_fetch_tool.py:132-138` |
| 0288 | 困难 | 场景设计 | 手动重定向循环的四道保护 | `web_fetch_tool.py:121-173` |
| 0289 | 困难 | 代码阅读 | `focus_text` 的段落选取不变式 | `web_common.py:177-215` |
| 0290 | 困难 | 场景设计 | 服务端指令文本与「只给信息」铁律 | `agent_tool.py:38-57` |
| 0291 | 困难 | 场景设计 | 图像型内容的「成功但无正文」 | `web_fetch_tool.py:200-212` |
| 0292 | 困难 | 代码阅读 | Todo 恢复的两种来源与优先级 | `todo_write_tool/restore.py:54-130` |
| 0293 | 困难 | 场景设计 | Skill 目录的注入面与上限 | `skill_tool.py:26-33,82-99` |
| 0294 | 困难 | 场景设计 | XeyoUI 面板与浏览器 URL 校验 | `xeyo_ui_tool.py:16-29,309-325` |
| 0295 | 困难 | 场景设计 | Diagnostics 的「宁可不说」取向 | `diagnostics_tool.py:170-267,405-423` |
| 0296 | 困难 | 代码阅读 | Agent 的并发安全声明与磁盘冲突 | `agent_tool.py:100-107` + `:34-35` |
| 0297 | 困难 | 场景设计 | Memory 工具的面板提示与候选 | `memory_tool.py:72-95` |
| 0298 | 困难 | 场景设计 | orchestration 的超时与进度门 | `orchestration.py:47-72` |
| 0299 | 超压 | 故障排查 | WebFetch 缓存的 prompt 污染面 | `web_fetch_tool.py:41-58,111-114` |
| 0300 | 超压 | 安全拷问 | Web 工具的 SSRF 绕过面总账 | `web_common.py` + `web_fetch_tool.py` + `web_search_tool.py` |

---

### XEYO-QA-0251 工具声明的两个静态方法

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | base_tool 工具契约 | 只读/并发安全声明 | 简单 | 机制解释 | `python/tools/base_tool.py` + 各工具的实现点 |

**面试官提问**
每个工具类都要声明两个静态方法。它们分别是什么？各自的用途是什么？请举出本批「两个都为真」与「只读为假但并发安全为真」的例子。

**参考答案要点**
两个静态方法：

| 方法 | 含义 | 消费方 |
|---|---|---|
| `is_read_only()` | 该工具是否**不修改工作区** | 权限层（只读模式网关 `permissions.policy.readonly_gate`）+ 编排层的并发判定 |
| `is_concurrency_safe()` | 该工具是否可**与同一轮的其他工具调用并行执行** | `tools/orchestration.py` 的 `is_concurrency_safe(registry, name)`（`:73-83`）与 `partition_tool_calls`（`:85-109`） |

**本批实例对照**：

| 工具 | `is_read_only` | `is_concurrency_safe` | 位置 |
|---|---|---|---|
| `WebFetch` | **False** | **False** | `web_fetch_tool.py:64-70` |
| `Agent` | **False** | **True** | `agent_tool.py:100-107` |
| `TodoWrite` | False（会写 sidecar/索引） | 视实现 | `todo_write_tool.py:107` 类内定义 |

「两个都为真」的例子在本批之外（`Read`/`Glob`/`Grep`，B04-0151/0181/0197 已出题）。「只读为假但并发安全为真」的代表正是 **`Agent`**——它的注释解释了理由（`agent_tool.py:105-107`）：

```python
    @staticmethod
    def is_concurrency_safe() -> bool:
        # 同轮可并行多个 Agent；磁盘冲突由 WriteStore content-hash 收敛。
        return True
```

即：**同一轮可以并行 spawn 多个子 agent**（`is_concurrency_safe=True`），而它们对磁盘的写冲突不靠「串行化」而靠 **`WriteStore` 的 content-hash 收敛**（B03 的写路径三层防护之一）。

★ `WebFetch` 的 `is_read_only=False` 值得注意：**它不写工作区**，但声明为「非只读」——因为从**安全**角度它是「出站网络访问」，属于会产生外部副作用的行为（发送请求、可能带上工作区信息）。这是「只读」= 「**无副作用**」而非「不碰磁盘」的语义选择。

**深化讲解**（面试官参考，不要求候选人全说）
两个方法的**层次不同**：

```
is_read_only()         → 权限/安全语义（这个动作危险吗？）
is_concurrency_safe()  → 编排语义（这个动作能并行吗？）
```

两者不互相决定：

| 组合 | 含义 | 例子 |
|---|---|---|
| 只读 + 并发安全 | 纯查询，随便并行 | `Read` / `Glob` / `Grep` |
| 非只读 + 并发不安全 | 有副作用且必须串行 | `Write` / `Edit` / `Bash` |
| **非只读 + 并发安全** | 有副作用但冲突可被下层收敛 | **`Agent`**（WriteStore 收敛） |
| 只读 + 并发不安全 | 少见（纯读但有共享状态） | — |

第三行是本批的核心：**「并发安全」可以靠「下层机制能处理冲突」来达成**，而不必要求工具自身无副作用。这也解释了为什么 `partition_tool_calls`（`orchestration.py:85-109`）需要把「并发安全」的工具分到一组并行执行——**决定权在声明，正确性责任在下层**。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0252 Agent 的深度硬限制与并发门禁

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | agent_tool 下发放大 | 两个门禁 | 简单 | 概念确认 | `python/tools/agent_tool/agent_tool.py:32-35` |

**面试官提问**
`Agent` 工具的 `MAX_DEPTH` 是多少？并发 spawn 的上限由什么决定、默认值是多少？

A. `MAX_DEPTH = 3`；并发无上限
B. **`MAX_DEPTH = 1`（禁止孙 agent）**；并发上限由 `XEYO_MAX_CONCURRENT_AGENTS` 决定，默认 **8**，经 `threading.Semaphore` 实现
C. `MAX_DEPTH = 1`；并发上限固定 4，不可配置
D. `MAX_DEPTH = 0`（禁止任何子 agent）

**参考答案要点**
**B**。

`agent_tool.py:32-35`（原文）：

```python
MAX_DEPTH = 1  # P0 硬限制（A8）：只允许一层子 agent，禁止孙 agent
# 同会话并发 spawn 上限（硬门禁；可用环境变量覆盖）
_MAX_CONCURRENT = max(1, int(os.environ.get("XEYO_MAX_CONCURRENT_AGENTS", "8") or "8"))
_agent_slots = threading.Semaphore(_MAX_CONCURRENT)
```

| 门禁 | 机制 | 值 |
|---|---|---|
| 深度 | `MAX_DEPTH = 1`，注释「P0 硬限制（A8）：只允许一层子 agent，**禁止孙 agent**」 | 1 |
| 并发 | `threading.Semaphore(_MAX_CONCURRENT)` | `max(1, int(env))`，默认 `8` |

**三个实现细节**：

1. **`MAX_DEPTH` 是模块级常量**（不是环境变量）——即「禁孙 agent」是**不可配置的策略**，只能改源码；
2. **并发上限可配但夹取下限**：`max(1, int(os.environ.get(..., "8") or "8"))`——`or "8"` 处理**空串**（`int("")` 会抛 `ValueError`，而 `"" or "8"` 得 `"8"`）；`max(1, ...)` 保证至少 1。★ 注意这里没有 `try/except`，所以**非数字的非法值（如 `XEYO_MAX_CONCURRENT_AGENTS=abc`）会在模块导入时抛 `ValueError`**——即配置写错会导致工具模块**导入失败**（本批待确认项：是否有上层保护，或这属于「启动即暴露」的可接受取向）；
3. **`Semaphore` 是模块级单例**（`:35`），即整个进程共享这一个信号量——所以「同会话并发上限」的实现实际上是「**进程级**并发上限」。

**深化讲解**（面试官参考，不要求候选人全说）
两个门禁针对的是不同风险：

| 门禁 | 防什么 |
|---|---|
| 深度 = 1 | **放大爆炸**：每层子 agent 都能再 spawn，成本与复杂度指数增长；「禁孙」把层级压到 1 层，成本线性可估 |
| 并发 = 8 | **瞬时资源**：8 个并发子 agent 各自跑模型与工具，对 token/CPU/网络是乘性开销 |

★ 深度限制的严格程度很高（`MAX_DEPTH = 1` 而非 2–3），说明这是一个**有意的保守选择**：子 agent 已经是「把一段工作外包出去」，再嵌套会让「谁在写哪个文件」「谁的结果算数」变得难以追责（对照 B03 的 `session_tree_root` 只区分主会话与一层子 agent 的约定）。

★ `Semaphore` 的**进程级**特性带来一个推论：多个会话（`session_pool` 里的多个引擎实例）若在同一进程内，会**共享**这 8 个槽位——所以「同会话上限」在实现上其实是「**同进程上限**」。这与 B05-0230 的容器路由串线事故属同一类「作用域假设与实际不符」的问题（那里是 env vs ContextVar，这里是「同会话」vs「同进程」），但这里的方向是**更严格**（共享槽位只会更慢，不会越界）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0253 `scope` 为空时的语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | agent_tool 写范围 | 只读子 agent | 简单 | 概念确认 | `python/tools/agent_tool/agent_tool.py:137-144` |

**面试官提问**
`Agent` 的 `scope` 参数传空数组（或不传）时，子 agent 的写能力是什么？

A. 可以写整个工作区（默认全权限）
B. **空 = 只读**：`Write`/`Edit` 被**移除**
C. 会报错（scope 必填）
D. 只能写 `scope` 默认为 `["."]` 的当前目录

**参考答案要点**
**B**。

`agent_tool.py:137-144`（schema 原文）：

```python
					"scope": {
						"type": "array",
						"items": {"type": "string"},
						"description": (
							"Write paths this agent may touch "
							"(empty = read-only; Write/Edit removed)."
						),
					},
```

描述写明「**empty = read-only; Write/Edit removed**」——即「空 scope」不是「无限制」，而是**收紧到只读**。

对照 0251 提到的 `permissions/write_scope.py`（`get_write_scope()`）：B04-0168 已确认「**子 Agent（write_scope 已激活）必须经 `WriteStore`，禁止静默直写**」——`file_write_tool._persist` 在 `write_store is None` 且 `get_write_scope() is not None` 时抛 `RuntimeError("write_store required for sub-agent writes (refusing direct disk bypass)")`。

所以「空 scope → 只读」有两层实现：

| 层 | 机制 |
|---|---|
| **工具面** | 从子 agent 的工具注册表里**移除** `Write` / `Edit`（「Write/Edit removed」） |
| **执行层** | 即使被移除的工具通过别的方式被调用，`write_scope` + `WriteStore` 的组合也会拒绝直写（B04-0168） |

**深化讲解**（面试官参考，不要求候选人全说）
「空 = 只读」是一个**方向安全**的默认值选择。对照两种可能的语义：

| 空 scope 的语义 | 后果 |
|---|---|
| 「无限制」（宽松） | 忘记传 scope 时子 agent 能写整个工作区——**危险默认** |
| **「只读」（严格）** | 忘记传 scope 时子 agent 只能读——**安全默认**，需要写就必须显式声明路径 |

这与本项目多处默认值取向一致（B05-0208 的「保护类默认开」、`_PURE_READ_BASES` 的 fail-closed 判写）：**默认值落在可逆/更严的一侧**。

★ 更重要的一点：**「只读」的实现方式是「移除工具」而非「工具内部报错」**。这是「限制只在执行层」的一个**更强的形态**——不是让 `Write` 存在但拒绝，而是**让子 agent 根本看不到这个工具**（工具面裁剪）。按 AGENTS.md 的理念：「**引擎能强制的，一律不给模型看**」；从注意力里拿掉一个工具比让它反复失败更干净（也不会诱导模型反复尝试）。

★ 与 `required_tools` 的关系（`:145-149`）：描述是「Extra tools **beyond baseline**」——即子 agent 有一个**基线工具集**，`required_tools` 是「在基线之上额外需要的」。所以「移除 Write/Edit」是相对基线做的减法，而 `required_tools` 是加法。两者的组合决定最终工具面。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0254 TodoItem 的五个字段与 UI 白名单差异

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | todo_write_tool 条目模型 | 字段与消费差异 | 简单 | 机制解释 | `python/tools/todo_write_tool/types.py:11-29` |

**面试官提问**
`TodoItem` 有哪五个字段？`to_dict()` 输出的键名与字段名有什么不同？为什么注释特别说明「UI 白名单（content/status/activeForm）丢弃」？

**参考答案要点**
`todo_write_tool/types.py:11-29`（原文）：

```python
@dataclass
class TodoItem:
	content: str
	status: TodoStatus
	active_form: str
	id: str = ""
	#: 可选产物路径（相对工作区）。步骤以"生成文件/产物"收尾时由模型声明；
	#: 进入 sidecar/transcript 恢复链，是引擎侧任务状态注册表的确定性引用，
	#: 供恢复/续跑/收尾引导等消费。UI 白名单（content/status/activeForm）丢弃。
	output: str = ""
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | str | 待办正文 |
| `status` | `TodoStatus` | 三值枚举（见 0255） |
| `active_form` | str | 进行时表述（UI 显示用） |
| `id` | str（默认 `""`） | 条目标识 |
| **`output`** | str（默认 `""`） | **可选产物路径**（相对工作区） |

**`to_dict()` 的键名差异**（`:22-29`）：

```python
	def to_dict(self) -> dict[str, str]:
		return {
			"id": self.id,
			"content": self.content,
			"status": self.status,
			"activeForm": self.active_form,
			"output": self.output,
		}
```

即字段名 `active_form`（snake_case）在序列化时变成 **`activeForm`（camelCase）**——这是**面向 UI/前端**的命名（GUI 的 TS 侧按 camelCase 消费）。

**为什么注释强调「UI 白名单（content/status/activeForm）丢弃」**：`output` 是**引擎侧**的字段（「引擎侧任务状态注册表的确定性引用，供恢复/续跑/收尾引导等消费」），而 UI 只展示 `content`/`status`/`activeForm`——所以 `to_dict()` **包含 `output`**（供引擎/持久化），但**前端渲染时应忽略它**。注释把这层契约写在字段上，避免后人误以为「`to_dict` 没有 output 会丢信息」而去做多余处理。

**深化讲解**（面试官参考，不要求候选人全说）
五个字段分成两组：

| 组 | 字段 | 消费方 |
|---|---|---|
| **展示组** | `content` / `status` / `active_form` | UI（且 `active_form` 只给 UI 用，见 0255 的校验） |
| **引擎组** | `id` / `output` | 持久化、恢复、续跑、收尾引导 |

★ `output` 的注释信息量很大，它说明了三件事：

1. **谁写它**：模型（「步骤以『生成文件/产物』收尾时由模型声明」）；
2. **它去哪**：sidecar（`working.WorkingSnapshot.todos`，B09-0441 已述）+ transcript 恢复链；
3. **它的用途**：「引擎侧任务状态注册表的**确定性引用**」——即引擎可以**确定地**知道「这一步的产物是哪个文件」，而不用从模型文本里猜。

第 3 点是关键：`output` 把「模型说它生成了什么」变成**结构化事实**。这与 B04-0196（`full output` 措辞不可靠）、B05-0250（`full at <path>` 指向压缩后内容）形成对照——**能证伪/能定位的引用必须是结构化的**，而不是文本里的一个路径字符串。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0255 Todo 状态三值枚举与必填校验

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | todo_write_tool 校验 | 三值枚举与三必填 | 简单 | 概念确认 | `python/tools/todo_write_tool/types.py:7-8,32-56` |

**面试官提问**
Todo 的合法状态有哪三个？`todo_item_from_raw` 对哪些字段做必填校验？缺 `id` 时会怎样？

A. `todo` / `doing` / `done`；必填 `content`；缺 id 报错
B. **`pending` / `in_progress` / `completed`**；必填 `content` / `status` / `activeForm` 三项；缺 `id` 时**自动生成 `uuid4().hex[:8]`**
C. `open` / `closed`；只校验 `content`
D. `pending` / `completed`；必填 `content` 与 `id`

**参考答案要点**
**B**。

`types.py:7-8`（原文）：

```python
TodoStatus = Literal["pending", "in_progress", "completed"]
VALID_STATUSES = frozenset({"pending", "in_progress", "completed"})
```

**注意两者并存**：`TodoStatus` 是**类型标注**（`Literal`，给静态检查用），`VALID_STATUSES` 是**运行时校验集**（`frozenset`，给 `todo_item_from_raw` 用）。同一定义维护两份，是「类型与运行时校验」的标准做法（类型标注在运行时不可枚举）。

校验逻辑（`:32-56`）：

```python
def todo_item_from_raw(raw: Any) -> TodoItem | None:
	"""解析单个 todo 字典；无效时返回 None。缺 id 时自动生成短 id。"""
	if not isinstance(raw, dict):
		return None
	content = raw.get("content")
	status = raw.get("status")
	active = raw.get("activeForm", raw.get("active_form"))
	if not isinstance(content, str) or not content.strip():
		return None
	if not isinstance(status, str) or status not in VALID_STATUSES:
		return None
	if not isinstance(active, str) or not active.strip():
		return None
	raw_id = raw.get("id")
	item_id = (
		str(raw_id).strip()
		if isinstance(raw_id, str) and raw_id.strip()
		else uuid4().hex[:8]
	)
	raw_output = raw.get("output")
	output = (
		str(raw_output).strip()
		if isinstance(raw_output, str) and raw_output.strip()
		else ""
	)
	return TodoItem(...)
```

| 字段 | 校验 | 不满足时 |
|---|---|---|
| `content` | 必须是**非空白**字符串 | `None`（整条丢弃） |
| `status` | 必须是 `VALID_STATUSES` 成员 | `None` |
| `activeForm` / `active_form` | 必须是**非空白**字符串 | `None` |
| `id` | 可选；非空字符串则用，否则 **`uuid4().hex[:8]`** | — |
| `output` | 可选；非空字符串则用，否则 `""` | — |

**两个宽容点**：

1. **`activeForm` 与 `active_form` 双键兼容**：`raw.get("activeForm", raw.get("active_form"))`——即「模型传 camelCase 或 snake_case 都收」。这是**输入宽容**（因为模型可能按 UI 命名或按 Python 命名）；
2. **`id` 自动生成**：缺 id 不会导致条目被丢，而是补一个 8 位十六进制 id——**保证持久化/恢复链永远有键**（比较 `todo_item_from_raw` 的用途：它被 `working.apply_to_tools` 用于从 sidecar 恢复，B09-0441）。

**深化讲解**（面试官参考，不要求候选人全说）
三必填 + 两可选的分工体现了「**这条 todo 有没有用**」的判据：

| 缺什么 | 结果 | 合理吗 |
|---|---|---|
| `content` | 丢弃 | ✅ 没有正文的待办无意义 |
| `status` | 丢弃 | ✅ 状态是状态机的关键（见 0274 的合并语义） |
| `activeForm` | 丢弃 | ⚠️ **较严**——`activeForm` 只是 UI 显示用（`is_read_only` 无关），缺它似乎不该丢弃整条 |
| `id` / `output` | 补默认 | ✅ 可选语义 |

第三行是本批值得记录的一处**严格点**：`activeForm` 被当作**必填**（缺失即丢弃整条），而它的用途（0254）是「进行时表述（UI 显示用）」。也就是说：**一条内容与状态都完好的待办，会因为缺少 UI 显示文本而被整体丢弃**。这与 `content`/`status` 的必填在语义强度上不同——本批列为待确认项（是否为有意的强约束，例如「由 UI 生成的 todo 必然带 activeForm」）。

**边界**：`status` 的类型标注是 `TodoStatus`，但校验后赋值带 `# type: ignore[arg-type]` 注释（`:59`）——因为 `status` 是 `str` 而非 `Literal`，静态检查器无法确认；校验已在运行时保证，所以用 ignore 标注是合适的（而不是改用 `cast`）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0256 Skill 目录的四个字符上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | skill_tool 目录预算 | 四个常量 | 简单 | 概念确认 | `python/tools/skill_tool/skill_tool.py:26-33` |

**面试官提问**
`skill_tool.py` 的四个字符上限分别是多少？

A. `CATALOG_MAX_CHARS = 2_400` / `CATALOG_LINE_DESC = 120` / `LIST_LINE_DESC = 500` / `LIST_MAX_CHARS = 4_000` / `BODY_MAX = 12_000`（列表类三个、正文一个）
B. `CATALOG_MAX_CHARS = 12_000` / `BODY_MAX = 2_400`
C. 全部为 4_000
D. `CATALOG_MAX_CHARS` 无上限

**参考答案要点**
**A**（四个上限共五个常量，注意 `CATALOG_*` 是两个）。

`skill_tool.py:26-33`（原文）：

```python
CATALOG_MAX_CHARS = 2_400

CATALOG_LINE_DESC = 120

LIST_LINE_DESC = 500
LIST_MAX_CHARS = 4_000

BODY_MAX = 12_000
```

| 常量 | 值 | 控制对象 |
|---|---|---|
| `CATALOG_MAX_CHARS` | `2_400` | **常驻目录**（catalog）的总字符上限 |
| `CATALOG_LINE_DESC` | `120` | 目录里**每行描述**的字符上限 |
| `LIST_LINE_DESC` | `500` | `list` 响应里每行描述的字符上限 |
| `LIST_MAX_CHARS` | `4_000` | `list` 响应的总字符上限 |
| `BODY_MAX` | `12_000` | **技能正文**（`SKILL.md` body）上限 |

**三档预算的梯度**（这是本题要考的核心）：

```
常驻目录   2_400 字符（每行 120）      ← 最贵：进 system 左段/常驻区，每轮都在
    ↓
list 响应  4_000 字符（每行 500）      ← 按需：模型显式调用才产生
    ↓
技能正文  12_000 字符                  ← 最省：只有真正加载某个技能时才进上下文
```

即：**越常驻的越短，越按需的越长**。

**深化讲解**（面试官参考，不要求候选人全说）
这个梯度与 B09-0431（Memory 索引块一行化与 T_now 尾插）、B05-0250（输出治理分层）是**同一原则的三处体现**：**上下文预算按「可见频率」分配**。

| 内容 | 可见频率 | 预算 |
|---|---|---|
| Skill 目录 | 每轮（常驻） | 2_400 |
| Skill list | 按模型调用 | 4_000 |
| Skill 正文 | 按模型加载 | 12_000 |
| Memory 索引摘要 | 每轮（T_now） | 一行 |
| Memory 条目正文 | 按 `Memory(action=search)` | 走检索 top_k |

★ 一行 120 字符（catalog）vs 500 字符（list）的差异同样反映这一点：**目录行要压到「够识别」**，而 list 行可以给更多描述（因为模型已经显式表示「我要看列表」）。

`BODY_MAX = 12_000` 与 B09-0432 的 `Read` 令牌闸门（25_000 令牌 ≈ 100k 字符）相比小得多——说明技能正文的预期规模是「一份可读的操作指南」，而不是「大段代码」。这也是 `Skill` 工具与 `Read` 的分工：**技能是提示词资产，不是文件内容**。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0257 MemoryTool 的六个 action

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | memory_tool 动作面 | 六个 action | 简单 | 概念确认 | `python/tools/memory_tool/memory_tool.py:36` |

**面试官提问**
`MemoryTool` 支持的 action 有哪些？请完整列举。

A. `write`
B. `update`
C. `forget`
D. `search`
E. `peers`
F. `retrieve`
G. `delete`

**参考答案要点**
**A、B、C、D、E、F**（即 `write` / `update` / `forget` / `search` / `peers` / `retrieve`）。

`memory_tool.py:36`（原文）：

```python
_ACTIONS = ("write", "update", "forget", "search", "peers", "retrieve")
```

**G（`delete`）不在其中**——「删除」的语义由 **`forget`** 承担（对应 `governance.forget(note_id, reason=...)` 生成 `Tombstone`，B09-0436 已述）。命名选择「forget」而非「delete」反映了记忆系统的语义：删除一条记忆**不是抹掉文件**，而是**留下一块墓碑**（`Tombstone`：`id` / `deleted_at` / `reason`），并让 `may_resurrect` **永远返回 False**（B09-0436：NightShift 硬禁止按旧 JSONL 复活）。

**六个 action 的职责划分**：

| action | 职责 | 关联机制 |
|---|---|---|
| `write` | 新建一条 note | `write_policy.refuse_reason` 内容门禁（B09-0413）+ 晋升闸（B09-0426） |
| `update` | 修改已有 note | 冲突裁决 `resolve_conflict`（B09-0414） |
| `forget` | 遗忘（留墓碑） | `governance.forget` + `tombstones.jsonl` |
| `search` | 词法检索 | `search.search()`（B09-0415）+ citation 锚点（B09-0425） |
| `peers` | **同工作区其他会话的 session.md 检索** | `search.search_session_notes`（B09-0415 的跨会话共享面） |
| `retrieve` | **按锚点 id 取回 C2 压缩碎片** | `memindex.get_fragments`（B09-0424） |

★ 六个 action 里有两个（`peers` / `retrieve`）不是「对 note 的 CRUD」，而是**两条专门通道**：

- `peers`（跨会话共享）：查的是**其他会话的 `session.md`**，不是 memdir 的 topic notes；
- `retrieve`（碎片还原）：查的是 **`fragments` 表**（C2 压缩时抓拍的原子），不是 note 文件。

这两者与 `search` 的**数据源完全不同**，所以被拆成独立 action 而非 `search` 的参数。

**深化讲解**（面试官参考，不要求候选人全说）
「六个 action 一个工具」的设计取舍：**工具面收敛**（B05-0251 提到的 `is_read_only`/`is_concurrency_safe` 是**整个工具级**的声明，粒度比 action 粗）。把读写动作放在同一个工具里的后果是：

| 影响 | 说明 |
|---|---|
| 权限粒度 | 权限层按**工具名**裁决（`Memory` 是一个名字），无法区分「`search` 只读」与 `forget` 有副作用 |
| 并发声明 | `is_concurrency_safe` 也只能对整体声明 |
| 好处 | 工具数量少（21 项启用工具的限制，`tools/catalog.py`）、schema 预算省、模型心智负担小 |

也就是说：**action 级别的读写差异没有被权限层区分**——这与 B04 的文件五件套（`Read`/`Write`/`Edit` 分开）形成对比。两种策略的取舍是「工具面数量 vs 权限粒度」，本项目在 `Memory` 上选了前者。

**边界**：非法 action 应被校验拒绝（`_ACTIONS` 是元组，可做成员检查）。`retrieve` 依赖 `memindex.get_fragments`，而 fragments 的写入受 `FRAGMENT_ROW_CAP = 400` / `FRAGMENT_TEXT_CAP = 4096` 限制（B09-0424）——所以 `retrieve` 能拿回的内容**有上限**，超过 4096 字符的原子在入库时已被截断。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0258 WebFetch 的下载上限与输出上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_fetch_tool 预算 | 两个上限 | 简单 | 概念确认 | `python/tools/web_fetch_tool/web_fetch_tool.py:16-23` |

**面试官提问**
`WebFetch` 的**下载字节上限**与**给模型的输出上限**分别是多少？重定向最多几次？

A. 下载 200_000 字节 / 输出 8_000 字符 / 最多 5 次重定向
B. 下载 8_000 字节 / 输出 200_000 字符 / 无重定向
C. 下载 1_000_000 字节 / 输出 16_000 字符 / 最多 3 次
D. 下载无限 / 输出 8_000 字符

**参考答案要点**
**A**。

`web_fetch_tool.py:16-23`（原文）：

```python
_CONNECT_S = 3.0
_READ_S = 12.0
# 下载上限；给模型看的正文更小。
_MAX_BYTES = 200_000
_OUT_CAP = 8_000
_MAX_REDIRECTS = 5
_CACHE_TTL_S = 15 * 60
_CACHE_MAX = 32
```

| 常量 | 值 | 说明 |
|---|---|---|
| `_CONNECT_S` | `3.0` 秒 | 连接超时 |
| `_READ_S` | `12.0` 秒 | 读取超时 |
| `_MAX_BYTES` | `200_000`（200 KB） | **下载**上限（注释：「下载上限；给模型看的正文更小」） |
| `_OUT_CAP` | `8_000` 字符 | **给模型**的正文上限 |
| `_MAX_REDIRECTS` | `5` | 重定向次数上限（实现是 `for _ in range(_MAX_REDIRECTS + 1)`，即**最多 6 次请求**） |
| `_CACHE_TTL_S` | `15 * 60`（900 秒） | 缓存 TTL |
| `_CACHE_MAX` | `32` | 缓存条数上限 |

**「下载 200KB、输出 8KB」的 25 倍差**是本题的重点：**下载可以宽，输出必须窄**。

理由在实现里（`:182-192`）：

```python
			if is_html:
				# 多提取一些（超过 OUT_CAP），让 focus_text 能挑相关段落。
				extract_budget = max(_OUT_CAP * 4, _OUT_CAP)
				plain = html_to_text(text, max_chars=extract_budget)
				body = focus_text(plain, prompt, max_chars=_OUT_CAP)
```

即：先按 **`_OUT_CAP * 4 = 32_000`** 的预算把 HTML 转成纯文本（**取多**），再让 `focus_text` 从中挑出**最相关的段落**压到 `_OUT_CAP = 8_000`（**交少**）。所以「8KB 输出」不是「截前 8KB」，而是「**在 32KB 候选里挑相关的 8KB**」。

**深化讲解**（面试官参考，不要求候选人全说）
三层预算的关系：

```
HTTP 下载        200_000 字节（硬上限，超出即截断并标记 truncated_dl）
    ↓ 解码 + html_to_text
纯文本候选        32_000 字符（= _OUT_CAP * 4，仅 HTML 路径）
    ↓ focus_text(prompt)
给模型正文         8_000 字符
```

★ 注释「**下载上限；给模型看的正文更小**」是这组常量的设计意图声明：下载宽松是为了**不破坏提取质量**（若只下 8KB，可能正好截在正文之前——很多网页前 8KB 全是导航与脚本）；而输出收紧是为了**省模型上下文**。中间用 `focus_text` 做**相关性挑选**，把「宽下载」的收益转成「窄输出」。

**边界**：`_MAX_REDIRECTS + 1` 这个 `+1` 的写法意味着「最多跟随 5 次重定向，总共 6 次请求」（第一次请求 + 5 次跟随）。`for ... else` 结构（`:172-173`）在循环**未 break** 时返回 `too many redirects`——即「用完 6 次还没拿到最终响应」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0259 WebFetch 缓存的键与两个参数

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_fetch_tool 缓存 | TTL/容量/键 | 简单 | 机制解释 | `python/tools/web_fetch_tool/web_fetch_tool.py:22-23,33-58,111` |

**面试官提问**
`WebFetch` 的缓存 TTL 与容量是多少？缓存键由哪两部分拼成？键里为什么要包含 `prompt`？

**参考答案要点**
`web_fetch_tool.py:22-23`：

```python
_CACHE_TTL_S = 15 * 60
_CACHE_MAX = 32
```

**TTL 900 秒（15 分钟）**，容量 **32 条**（`OrderedDict` + LRU：`_cache_put` 里 `while len(_cache) > _CACHE_MAX: _cache.popitem(last=False)`，`:54-58`）。

**缓存键**（`:111`）：

```python
		cache_key = f"{_normalize_url(url)}\n{prompt}"
```

两部分：**规范化后的 URL** + **`prompt`（焦点问题）**。

**`_normalize_url`**（`:33-38`）：

```python
def _normalize_url(url: str) -> str:
	parts = urlsplit(url.strip())
	# 去掉 fragment；保留 query（文档常按 ? 区分）。
	return urlunsplit(
		(parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
	)
```

三步：**scheme 与 netloc 转小写**；**path 为空则填 `/`**；**去掉 fragment**（但**保留 query**，注释：「文档常按 `?` 区分」）。

**为什么键里要包含 `prompt`**：因为 `prompt` 会**改变输出内容**——它传给 `focus_text` 决定「挑哪些段落」（0270）。同一 URL 传不同 `prompt` 会得到**不同的正文**，所以必须分别缓存，否则第二次不同 prompt 的调用会命中第一次的结果（内容不匹配）。

**深化讲解**（面试官参考，不要求候选人全说）
这个键的设计是「**函数式纯度**」要求的结果：**缓存键必须覆盖所有影响输出的输入**。

| 影响输出的输入 | 是否进键 |
|---|---|
| URL（scheme/netloc/path/query） | ✅ |
| URL 的 **fragment** | ❌ **有意排除**（`#` 之后的片段不影响服务端返回） |
| `prompt` | ✅（影响 `focus_text` 的挑选） |
| `abort` 状态 | ❌（不是输入，是控制） |

★ 这是与 B04-0192（Glob 缓存三类键）**同一原则**的实例：那里的键是 `("files", pattern, root, head_limit, off)`——**所有参数都在键里**。而 B04 也记录了一个反面案例：`Glob` 的键**不含** `case_insensitive` 标记（因为重试是内部触发的），当时标注为待确认项。所以「键覆盖所有输入」这条原则在本项目里有**一处例外**（Glob），而 `WebFetch` 是**遵守**的。

★ `fragment` 的排除值得单独说：`https://x/a#sec1` 与 `https://x/a#sec2` 会**命中同一缓存**。这是合理的（fragment 仅客户端使用，不影响服务端响应），但如果将来要支持「按 fragment 定位页面内锚点」，这个键就需要扩展——属于**隐含假设**（fragment 不影响输出）。

★ 缓存的另一个作用面（0299 会展开）：`_cache_put` 在**两个位置**被调用——非文本体（`:205`）与正常文本（`:219`）。所以**错误与重定向不缓存**（它们在 `return ToolResult(..., is_error=True)` 的路径上直接返回，不经过 `_cache_put`），这与「缓存只存成功结果」的常规做法一致。

**边界**：`_cache_get` 在过期时**主动 `pop`**（`:47-49`），而不是留到下次淘汰——保证过期项不占容量。`move_to_end` 在读写两处都调用（`:50` / `:56`），实现标准 LRU。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0260 WebSearch 的默认结果数与片段上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_search_tool 预算 | 四个常量 | 简单 | 概念确认 | `python/tools/web_search_tool/web_search_tool.py:23-27` |

**面试官提问**
`WebSearch` 的默认结果条数、单条片段上限、总输出上限分别是多少？

A. 默认 3 条 / 单条片段 160 字符 / 总输出 4_096 字符
B. 默认 10 条 / 单条片段 500 字符 / 总输出 8_000 字符
C. 默认 5 条 / 单条片段 200 字符 / 总输出 4_096 字符
D. 无默认（必填）/ 无上限

**参考答案要点**
**A**。

`web_search_tool.py:23-27`（原文）：

```python
_CONNECT_S = 3.0
_READ_S = 15.0
_DEFAULT_COUNT = 3
_SNIPPET_MAX = 160
_OUT_CAP = 4096
```

| 常量 | 值 | 说明 |
|---|---|---|
| `_CONNECT_S` | `3.0` 秒 | 连接超时 |
| `_READ_S` | `15.0` 秒 | 读取超时（比 WebFetch 的 12s 长，因为搜索结果页通常更重） |
| `_DEFAULT_COUNT` | `3` | 默认返回结果条数 |
| `_SNIPPET_MAX` | `160` | 单条片段字符上限（`_clip_snippet`，`:177-183`） |
| `_OUT_CAP` | `4096` | 总输出字符上限 |

**与 WebFetch 的对照**（本题的考点）：

| 维度 | WebSearch | WebFetch |
|---|---|---|
| 连接超时 | 3.0 s | 3.0 s |
| 读取超时 | **15.0 s** | 12.0 s |
| 输出上限 | **4_096** | 8_000 |
| 单条上限 | **160**（片段） | — |

★ **WebSearch 的输出预算比 WebFetch 小一半**（4096 vs 8000），这是合理的：搜索是**发现阶段**（只需要「有哪些相关结果、大致讲什么」），而抓取是**阅读阶段**（需要正文）。`_SNIPPET_MAX = 160` 同样反映了「片段只够判断相关性」的定位。

**深化讲解**（面试官参考，不要求候选人全说）
搜索工具的输出结构是「**多条 × 短片段**」，而抓取是「**一条 × 长正文**」：

```
WebSearch(3 条 × ≤160 字符片段)  → 总 ≤4096
WebFetch(1 个 URL × ≤8000 正文)   → 总 ≤8000
```

`_DEFAULT_COUNT = 3` 偏小（常见搜索工具默认 5–10），这与「**搜索是为了拿 URL 去 Fetch**」的定位一致：模型看到 3 条足够判断「哪条值得抓」，多了反而占上下文。模型也可以通过参数调大 count（上限受 `_OUT_CAP` 约束）。

**边界**：`_OUT_CAP` 是**总**上限，所以「条数 × 片段」的组合会被它约束——例如 count=50 时，实际能返回的条数受 4096/（每条实际长度）限制。这与 B05-0214（`cmd_compact` 的 `_MIN_CHARS`）属同类「预算约束实际生效面」的设计。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0261 Git 工具的只读动作白名单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | git_tool 动作面 | 只读/写两集 | 简单 | 机制解释 | `python/tools/git_tool/git_tool.py:12-18` |

**面试官提问**
`git_tool.py` 定义了只读与写两个动作集。各自的成员是什么？输出上限与状态路径上限是多少？

**参考答案要点**
`git_tool.py:12-18`（原文）：

```python
_READ_ACTIONS = frozenset({"status", "log", "branches", "diff", "summary"})
_WRITE_ACTIONS = frozenset(
```

| 集 | 成员（`_READ_ACTIONS` 完整可读） |
|---|---|
| `_READ_ACTIONS` | `status` / `log` / `branches` / `diff` / `summary`（**五个**） |
| `_WRITE_ACTIONS` | `:13-16` 的集合体（定义面显示其起始行；具体成员本批未逐项读取，列为待确认） |
| `_OUT_CAP` | `16_000`（`:17`） |
| `_STATUS_PATH_CAP` | `80`（`:18`） |

**五个只读动作的覆盖**：

| action | 对应 git |
|---|---|
| `status` | `git status`（含 `_format_status`，`:217-249`） |
| `log` | `git log`（`_format_log`，`:250-266`） |
| `branches` | 分支列表（`_format_branches`，`:267-278`） |
| `diff` | `git diff`（`_format_diff`，`:279-289`） |
| `summary` | 汇总（`_format_summary`，`:183-216`） |

★ 注意 `summary` 是 **Git 工具自有的聚合动作**（不是 git 子命令）——它把多个只读信息合成一份摘要（`_format_summary` 有 34 行，比单项格式化函数长）。

**深化讲解**（面试官参考，不要求候选人全说）
Git 工具的动作分层与 B05-0205（Bash 里的 git 子命令白名单）**目的不同**：

| 机制 | 位置 | 判什么 |
|---|---|---|
| Bash 的 `_GIT_READ_SUBS` | `bash_tool.py:75-79` | 「这条 Bash 命令是否会写盘」（→ 清搜索缓存） |
| **Git 工具的 `_READ_ACTIONS` / `_WRITE_ACTIONS`** | `git_tool.py:12-16` | 「这个 action 是否需要写权限」（→ 权限裁决与工具可用性） |

也就是说：**同一个「git 只读」概念被两处独立实现**（B05-0204 已记录「同一概念三处实现」的现象，这里是第四处）。而且两者的成员**不同**：

| | 成员 |
|---|---|
| Bash 侧（15 个） | `status` `log` `diff` `show` `blame` `rev-parse` `describe` `shortlog` `ls-files` `ls-remote` `cat-file` `grep` `reflog` `version` `help` |
| Git 工具侧（5 个） | `status` `log` `branches` `diff` `summary` |

差异的理由：**Git 工具是「受控子集」**（只暴露 5 个最常用的只读查询，其余交给 Bash），而 Bash 侧的白名单是「**穷举所有可确认只读的子命令**」（因为 Bash 侧的需求是「不漏判写」——宁可多列，见 B05-0205 的 fail-closed 取向）。

**边界**：`_OUT_CAP = 16_000` 是输出上限（比 WebFetch 的 8_000 大一倍，因为 diff/log 天然较长）；`_STATUS_PATH_CAP = 80` 是 `status` 动作里**列出的路径数上限**（避免大仓库的 status 刷屏），配套 `_cap(text)`（`:175-182`）与 `_maybe_compact(action, text)`（`:160-174`）。

★ `_maybe_compact` 的存在说明 Git 工具**也做输出压缩**——与 B05 的 `cmd_compact`（针对 Bash 里的 `git` 命令输出）是**两条独立路径**。也就是说：用 `Git` 工具跑 `status` 与用 `Bash` 跑 `git status`，**压缩逻辑可能不同**（前者走 `_maybe_compact`，后者走 `cmd_compact._compact_git`）。这是本批指出的一处**重复实现**（同一语义两套代码）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0262 Diagnostics 的五个限额与语言面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | diagnostics_tool 限额 | 五常量 | 简单 | 机制解释 | `python/tools/diagnostics_tool/diagnostics_tool.py:19-24` |

**面试官提问**
`Diagnostics` 的五个限额常量分别是什么？它专门覆盖哪一类文件扩展名？

**参考答案要点**
`diagnostics_tool.py:19-24`（原文）：

```python
_TIMEOUT_S = 30
_MAX_CHARS = 16_000
_MAX_LINES = 100
_MAX_FILES = 50
_MAX_DEPTH = 2
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}
```

| 常量 | 值 | 语义 |
|---|---|---|
| `_TIMEOUT_S` | `30` | 单次诊断工具调用的超时（秒） |
| `_MAX_CHARS` | `16_000` | 输出字符上限 |
| `_MAX_LINES` | `100` | 输出行数上限 |
| `_MAX_FILES` | `50` | 最多诊断的文件数 |
| `_MAX_DEPTH` | `2` | 目录遍历深度上限 |
| `_TS_EXTS` | 六个 TS/JS 扩展名 | TypeScript/JavaScript 语言面 |

**五个「闸」的分工**：时间（30s）、体积（16k 字符 / 100 行）、范围（50 文件 / 深度 2）——三类资源各一到两个上限。这是本批里**限额最密集**的工具（B04 的 `Read` 是三层闸门、B05 的 `truncate` 是三个常量；这里是五个）。

**深化讲解**（面试官参考，不要求候选人全说）
`_TS_EXTS` 与 B04-0197/`file_write_tool._DIAG_EXTS`（`.py .ts .tsx .js .jsx .mts .cts`）**几乎相同**——但注意 Diagnostics 的集合**没有 `.py`**（Python 走 `py_compile`/`ruff` 路径，见 `_looks_python` 与 `_run_py_compile`，`:187-197`、`:255-267`）。也就是说：

| 语言 | 探测函数 | 执行器 |
|---|---|---|
| Python | `_looks_python(target, lang)`（`:187-197`） | `_run_py_compile`（`:255-267`）/ `_run_ruff`（`:268-304`） |
| TypeScript/JS | `_looks_typescript(target, lang)`（`:198-210`） | `_find_local_tsc`（`:305-337`）+ `_run_tsc`（`:338-387`） |

★ TS 路径的关键设计是 **`_find_tsc`（找本地 tsc）**——即**优先用项目本地的 TypeScript 编译器**（`node_modules/.bin/tsc`），而不是全局或下载的。这保证「诊断用的版本与项目构建用的版本一致」（版本不一致会产生不同的报错）。配套 `_find_tsconfig(target, cwd)`（`:211-226`）——有 `tsconfig.json` 就按它编译（否则诊断规则与项目实际构建不符）。

★ 另一处：**`_shallow_has(root, suffixes)`（`:170-186`）**——用于「浅层探测」某个目录是否包含某类文件（决定要不要在这个目录做诊断）。

**边界**：`_MAX_DEPTH = 2` 很小（只遍历两层）——说明 Diagnostics 的定位是「**对指定目标做快速体检**」而不是「全仓扫描」。这与 `_MAX_FILES = 50` 一致。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0263 XeyoUI 的面板与浏览器操作

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | xeyo_ui_tool 动作面 | 两个集合 | 简单 | 概念确认 | `python/tools/xeyo_ui_tool/xeyo_ui_tool.py:16-29` |

**面试官提问**
`XeyoUI` 支持哪些面板？浏览器操作有哪几个？

A. 面板 6 个（`git` / `terminal` / `history` / `map` / `commits` / `browser`）；浏览器操作 5 个（`reload` / `back` / `fwd` / `ext` / `close`）
B. 面板 3 个；浏览器操作 2 个
C. 面板 6 个；浏览器操作 6 个（含 `open`）
D. 面板无白名单（任意字符串）

**参考答案要点**
**A**。

`xeyo_ui_tool.py:16-17`（原文）：

```python
_UI_PANELS = frozenset({"git", "terminal", "history", "map", "commits", "browser"})
_BROWSER_OPS = frozenset({"reload", "back", "fwd", "ext", "close"})
```

| 集合 | 成员 |
|---|---|
| `_UI_PANELS` | `git` / `terminal` / `history` / `map` / `commits` / `browser`（**六个**） |
| `_BROWSER_OPS` | `reload` / `back` / `fwd` / `ext` / `close`（**五个**） |

★ 注意 **`open` 不在浏览器操作里**——浏览器面板的「打开某个 URL」这一能力应通过 `_browser_url_ok(url)`（`:309-325`）所在的路径实现（`open` 类的动作应会把 URL 经该校验），而 `_BROWSER_OPS` 里的五个都是**无参数的导航/控制动作**（重载、后退、前进、外部打开、关闭）。这个划分很合理：**带参数的动作（需要 URL 校验）与无参数动作分开**。

第三个集合 `_ACTIONS`（`:18-29`）是整体的动作白名单（起始行 `:18`，成员未逐项读取，列为待确认）。

**深化讲解**（面试官参考，不要求候选人全说）
`XeyoUI` 的定位是「**让模型操作桌面 GUI**」——面板切换、浏览器导航等。它的设计要点：

| 要点 | 实现 | 意义 |
|---|---|---|
| 面板与操作都是 **`frozenset` 白名单** | `:16-17` | 模型只能传已知值，不能凭字符串注入任意前端动作 |
| 浏览器 URL 有专门校验 | `_browser_url_ok(url)`（`:309-325`） | URL 是**唯一的字符串入参**，所以需要单独把关（见 0294） |
| 有 `_peek_title(path)` | `:326-` | 读文件标题（供 UI 显示） |
| 有 `_as_bool(value)` | `:30-43` | 三态布尔解析（`True`/`False`/`None`）——`None` 表示「未提供」，与 B09-0435 的 `ProjectionDigest` 保守读取属同一类「区分缺省与假值」的需求 |

★ 白名单化的收益在这里特别明显：GUI 侧的动作是**前端实现的**，若模型能传任意 action 字符串，就等于让模型直接调用前端任意 handler——**这是从 LLM 到前端的一整条注入面**。用 `frozenset` 收窄到有限集合，把注入面压到「几个已知动作 + 一个需校验的 URL」。

**边界**：`_as_bool` 返回 `bool | None`（`:30`）——三态是因为「未提供」与「显式 False」需要区分（例如「是否强制刷新」这类标志）。这与本项目多处「None 表示未提供、有值则覆盖」的模式一致（B09-0435 的 `resolve_modes` 同一思路）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0264 NotebookEdit 的上限与空骨架

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | notebook_edit_tool 结构 | 两常量与四个动作 | 简单 | 机制解释 | `python/tools/notebook_edit_tool/notebook_edit_tool.py:19-27,354-379` |

**面试官提问**
`NotebookEdit` 的源码上限是多少？`_EMPTY_NB` 是干什么用的？它支持哪些 cell 操作？

**参考答案要点**
`notebook_edit_tool.py:19-27`（原文节选）：

```python
_MAX_SOURCE = 1_024 * 1_024
_EMPTY_NB = {
```

| 项 | 值/含义 |
|---|---|
| `_MAX_SOURCE` | `1_024 * 1_024 = 1_048_576`（**1 MiB**）——单 cell source 或整体源码上限 |
| `_EMPTY_NB` | 一个 dict 常量：**新建 notebook 时的空骨架**（`:20-27`） |

**四个 cell 操作**（由 `NotebookEdit` 的描述给出，B04-0166 已引用 `notebook_edit_tool/prompt.py:4-5`）：`replace` / `insert` / `delete`，另加 `cell_type` 默认 `code`：

```
"Edit a Jupyter notebook by cell (replace/insert/delete). Read the .ipynb
first (structured cell index). Do not use Edit or Write on .ipynb.
insert without cell_idx appends; cell_type defaults to code.
Each write may need user confirmation (permission ASK)."
```

| 操作 | 语义 |
|---|---|
| `replace` | 替换指定 `cell_idx` 的 cell |
| `insert` | 插入 cell（**不给 `cell_idx` 则追加**到末尾） |
| `delete` | 删除指定 cell |

**两个辅助函数**（`:354-379`）：

```python
def _source_to_list(source: str) -> list[str]:
```

```python
def _new_cell(cell_type: str, source: str) -> dict[str, Any]:
```

`_source_to_list` 把多行字符串转成 **nbformat 要求的字符串列表**（每行一个元素，**末行不带换行**）——这是 `.ipynb` 格式的硬要求（`source` 是 `list[str]`，且除最后一行外每行都应以 `\n` 结尾）。`_new_cell` 用 `_EMPTY_NB` 的字段模板构造一个新 cell。

**深化讲解**（面试官参考，不要求候选人全说）
`NotebookEdit` 的存在理由是 B04-0166 已确立的：**`Write`/`Edit` 都拒绝 `.ipynb`**（`IPYNB_REJECT`），因为按字符串替换改 JSON 容器极易产生「合法 JSON 但语义错乱」的 notebook。所以：

```
.ipynb 的读写分工：
  Read        → 返回 cell 索引摘要（B04-0154）
  NotebookEdit→ replace / insert / delete（按 cell_idx）
  Write/Edit  → 明确拒绝（IPYNB_REJECT）
```

★ 描述里的最后一句值得注意：「**Each write may need user confirmation (permission ASK)**」——即 notebook 编辑**倾向于需要用户确认**（比普通文件编辑更谨慎）。这可能与「notebook 常含已执行的输出/敏感数据」有关，也可能是权限层对该工具的默认策略（B07 面）。

★ `_source_to_list` 的「末行不带换行」是一个**容易写错的格式细节**：nbformat 的约定是「每个元素是含换行符的行，除最后一行」。若格式化时给所有行都加了 `\n`，notebook 仍能被 Jupyter 打开但 diff 会多出一个空行——「看似正常的小错」，正是 `.ipynb` 需要专用工具的理由。

**边界**：`_MAX_SOURCE = 1 MiB` 是**源码**上限（保护内存与输出）；AS<sub>KB</sub> 之外，nbformat 版本兼容（`nbformat` 字段）由 `_EMPTY_NB` 的骨架决定（新建时用哪一版）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0265 AskUserQuestion 的请求 id 键

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | ask_user_question 协议 | 请求 id 与两个工具函数 | 简单 | 机制解释 | `python/tools/ask_user_question_tool/ask_user_question_tool.py:19-89` |

**面试官提问**
`AskUserQuestion` 在入参里用哪个键携带「请求 id」？`flatten_options` 与 `format_questions_payload` 各自做什么？

**参考答案要点**
`ask_user_question_tool.py:19-21`（原文）：

```python
ASK_USER_TOOL_NAME = "AskUserQuestion"

ASK_REQUEST_ID_KEY = "__ask_request_id"
```

★ 键名**带双下划线前缀** `__ask_request_id`——这是「**引擎注入的保留键**」的命名约定：模型不应主动传它，引擎在构造工具调用时注入（用于把「挂起的提问」与「后续的 `/v1/ask/resolve` 回执」对上，B14 面）。双下划线是**约定信号**（类似 Python 的私有命名），让「这是引擎字段」一眼可辨。

**两个工具函数**：

| 函数 | 位置 | 职责 |
|---|---|---|
| `_option_label(opt)` | `:24-33` | 从选项对象里取出标签字符串（私有） |
| `flatten_options(options_raw)` | `:34-45` | **把多种形态的选项压成一维字符串列表** |
| `format_questions_payload(raw)` | `:46-89` | **把模型给的原始入参规范化成前端/GUI 需要的 payload** |

`flatten_options` 的存在理由：模型可能用不同形态表达选项（字符串、`{"label": ...}`、`{"text": ...}` 等），前端只需要一个字符串列表——所以做**输入形态归一化**（与 B06-0255 的 `activeForm`/`active_form` 双键兼容、B04 的 `_coerce_optional_int` 属同一类「宽容输入」模式）。

`format_questions_payload` 是**协议适配层**：把模型的提问结构转成「GUI 对话框能渲染的 payload」（`AskUserDialog` 在 GUI 侧，M21）。

**深化讲解**（面试官参考，不要求候选人全说）
`AskUserQuestion` 是**唯一的「阻塞型」工具**——它让 agent 停下来等用户回答。这带来三条特殊的架构要求：

| 要求 | 实现线索 |
|---|---|
| **提问必须可寻址** | `__ask_request_id`（回执时按 id 匹配，见 B14 的 `/v1/ask/resolve`） |
| **提问必须有超时** | `permissions/pending_ttl.py`（B07 面，挂起项的 TTL） |
| **提问形态必须规范化** | `flatten_options` + `format_questions_payload`（前端渲染契约） |

★ 与 `permissions/ask_store.py`（B07）的关系：`AskUserQuestion` 是**向用户提问**（信息收集），而 `ask_store` 管理的是**权限 ASK**（授权确认）。两者都是「挂起 → 等用户 → 回执」的模式，但语义不同（**问信息 vs 求授权**）——它们共用「挂起与回执」的基础设施，但**不共用同一个 store**（B07 待确认项之一可核对这一点）。

**边界**：`ASK_USER_TOOL_NAME` 常量（`:19`）被 `tools/tool_registry.py` import（B04 已记录该 import 出现在 `tool_registry.py:18` 与 `:20`——**重复 import 两次**，是同一文件里的一处小重复）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0266 Web 工具的私有主机拒绝清单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_common SSRF 防护 | 主机名清单 | 简单 | 概念确认 | `python/tools/web_common.py:10-16` |

**面试官提问**
`_PRIVATE_HOSTS` 里有哪些主机名？判定时还有一条**后缀规则**，是什么？

A. 只有 `localhost`；无后缀规则
B. **`localhost` / `localhost.` / `metadata.google.internal`**；另有后缀规则 `host.endswith(".localhost")`
C. `localhost` / `127.0.0.1` / `::1`
D. 只按 IP 判定，不看主机名

**参考答案要点**
**B**。

`web_common.py:10-16`（原文）：

```python
_PRIVATE_HOSTS = frozenset(
	{
		"localhost",
		"localhost.",
		"metadata.google.internal",
	}
)
```

判定（`:34-35`）：

```python
	if host in _PRIVATE_HOSTS or host.endswith(".localhost"):
		return "private_host"
```

| 项 | 内容 | 说明 |
|---|---|---|
| `localhost` | 精确匹配 | 最常见 |
| `localhost.` | **带尾点的形式** | DNS 中尾点表示「绝对域名」（FQDN），`localhost.` 与 `localhost` 解析相同——**必须同时列**，否则加尾点即可绕过 |
| `metadata.google.internal` | **云元数据端点** | GCP 的元数据服务名 |
| `.localhost` 后缀 | `endswith(".localhost")` | 覆盖 `x.localhost` 这类子域（RFC 6761 规定 `.localhost` 整个 TLD 保留给回环） |

**★ 为什么这个清单这么短**：因为主机名清单只是**第一道**——真正的判定主体在**IP 层**（字面 IP 与 DNS 解析结果，见 `:36-72`）。所以清单只需要列「**不会解析成 IP 或需要特殊处理**」的名字：

| 类型 | 在哪判定 |
|---|---|
| `localhost` / `x.localhost` | **主机名清单**（因为它是名字，可能解析到任意地址） |
| 字面 IP（`127.0.0.1`、`10.0.0.1`、`169.254.169.254`…） | **IP 判定**（`:37-50`） |
| 域名（`evil.com` → 解析到 `127.0.0.1`） | **DNS 解析后判定**（`:52-72`） |
| 云元数据**域名**（AWS 用 IP `169.254.169.254`，GCP 用域名） | 两者都要：DNS 名单列域名，IP 列表列地址 |

**深化讲解**（面试官参考，不要求候选人全说）
这道题的要点是「**主机名与 IP 是两套互补的判据**」：

```
is_blocked_url
  ├─ scheme 白名单（http/https）              :29-30
  ├─ 主机名清单（localhost 家族 + GCP 元数据）  :34-35
  ├─ 字面 IP 判定（private/loopback/link-local/reserved/multicast/unspecified）
  │    + 169.254.169.254 特判                  :37-50
  └─ 域名 → DNS 解析 → 对每个解析结果做 IP 判定  :52-72
       └─ DNS 失败 = 拒绝（dns_failed）         :55-56
```

★ `localhost.` 这一条是**绕过与修补的教科书案例**：任何「按名字屏蔽」的清单，都必须考虑**等价写法**（尾点、大小写、URL 编码）。这里 `host` 已经过 `.lower()`（`:31`）处理大小写，尾点靠显式列举处理。

★ 而 `metadata.google.internal` 的存在说明**云环境是威胁模型的一部分**：SSRF 攻击者的经典目标是**云元数据服务**（拿实例凭证）。GCP 用域名（所以要进主机名清单），AWS/Azure 用 `169.254.169.254`（所以要进 IP 特判，`:49-50` 与 `:70`）。所以这短短三条清单背后是**两个具体威胁**。

**边界**：`_PRIVATE_HOSTS` 是 `frozenset`，成员只有三条——它**不包含** `127.0.0.1` 这类 IP 字符串（那是 IP 判定的事），也**不包含** `internal` / `intranet` / `corp` 这类企业内网后缀。也就是说：**企业内网域名的拦截不在本清单范围内**（本批待确认项：是否有其它层处理，例如 `is_searxng_base_allowed` 的 URL 白名单，见 0271）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背下清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并能在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据。（本题可追问到具体 `文件:行号`。）

**追问**
把答案从「能对上号」推进到「知道它为什么这么设计」：请指出这个设计**原本要防的那个具体故障**是什么。

---

### XEYO-QA-0267 一次 URL 放行判定要过几道闸

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_common SSRF 防护 | 判定链与原因码 | 中等 | 机制解释 | `python/tools/web_common.py:19-73` |

**面试官提问**
你负责给一个「模型可以抓任意 URL」的工具做出站防护。请说明你的 URL 放行判定会分哪几层，以及你会怎么处理「DNS 解析失败」。

**参考答案要点**
`is_blocked_url(url)` 的八级判定（返回**原因码或 `None`**）：

```python
	if not raw: return "empty_url"
	scheme = (parsed.scheme or "").lower()
	if scheme not in ("http", "https"): return f"scheme_not_allowed:{scheme or 'none'}"
	host = (parsed.hostname or "").strip().lower()
	if not host: return "missing_host"
	if host in _PRIVATE_HOSTS or host.endswith(".localhost"): return "private_host"
	try:
		ip = ipaddress.ip_address(host)          # 字面 IP 分支
		if ip.is_private or ip.is_loopback or ...: return "private_ip"
		if str(ip) == "169.254.169.254": return "metadata_ip"
	except ValueError:                            # 域名分支
		try: infos = socket.getaddrinfo(host, None)
		except socket.gaierror: return "dns_failed"
		for info in infos:                        # 逐结果检查
			if <该地址属私网类>: return "resolves_to_private_ip"
	return None
```

四层结构与要点：①**协议白名单**（只 http/https，原因码回显实际 scheme）；②**主机名清单**（`localhost` / `localhost.` / `metadata.google.internal` + `.localhost` 后缀）；③**字面 IP**（private/loopback/link-local/reserved/multicast/unspecified + 元数据地址特判）；④**域名 → DNS 解析 → 对每个结果做 IP 判定**。

**DNS 失败必须判拒绝**（`:52` 注释「DNS 失败 = 拒绝（不许放行）」）：因为检查与请求是两次解析（见 0287），若失败放行，攻击者可用「检查时解析失败、请求时解析成功」的域名绕过复核。

**评分要点**
- **及格**：说出「协议白名单 + 私网/回环 IP 拦截 + 云元数据地址」三件，并知道 DNS 失败要拒绝。
- **良好**：能讲出**两层分支**（字面 IP 走 `ipaddress`，域名走 `getaddrinfo` 后逐结果检查），并说明「逐结果而非只查第一个」的原因（多地址返回时任一私网即拒）。
- **优秀**：能指出 `localhost.`（尾点 FQDN 等价写法）这类**等价写法的绕过面**，并把判定链讲成「先零成本、后昂贵」（scheme/主机名/字面 IP 都不碰网络，DNS 是唯一系统调用）。

**典型弱答**
- 只答「判断是不是内网 IP」（漏协议白名单与主机名清单）；
- 说 DNS 失败就放行（方向反了，等于把复核交给攻击者）；
- 把 `_PRIVATE_HOSTS` 当成全部（它只有三条，主体在 IP 层）。

**追问**
如果攻击者控制的域名在**检查时**解析到公网、在**请求时**解析到 `127.0.0.1`，你这套判定拦得住吗？缺口在哪一步？（→ 0287 的 TOCTOU）

---

### XEYO-QA-0268 重定向为什么要逐跳校验

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_fetch 重定向 | 逐跳校验与手动跟随 | 中等 | 场景设计 | `python/tools/web_fetch_tool/web_fetch_tool.py:130-156` |

**面试官提问**
模型要抓 `https://evil.com/x`，该站返回 `302 Location: http://169.254.169.254/latest/meta-data/...`。你的判定能拦住吗？请说明抓取循环该怎么写。

**参考答案要点**
只在请求前判一次**拦不住**——必须**逐跳校验**：

```python
	async with httpx.AsyncClient(follow_redirects=False, max_redirects=0) as client:
		for _ in range(_MAX_REDIRECTS + 1):
			abort.raise_if_aborted()
			deny = await asyncio.to_thread(is_blocked_url, current)      # ①请求前
			if deny: return ToolResult(...)
			async with client.stream("GET", current) as stream_resp:
				if stream_resp.status_code in (301,302,303,307,308):
					loc = stream_resp.headers.get("location")
					if not loc: return ToolResult(content=f"redirect without Location: {current}", is_error=True)
					current = urljoin(current, loc)                        # ②相对 Location 用 urljoin
					await stream_resp.aclose()                             # ③排空中间响应
					continue
				deny = await asyncio.to_thread(is_blocked_url, str(stream_resp.url))  # ④响应侧再校验
				if deny: return ToolResult(...)
				break
		else:
			return ToolResult(content="too many redirects", is_error=True)
```

**禁用自动跟随是前提**（`follow_redirects=False, max_redirects=0`）——只要客户端自动跟随，逐跳校验就没有执行机会。代价是自己实现库做过的事：判断哪些状态码算重定向、`urljoin` 解析相对 Location、**关闭/排空每个中间响应**（否则连接池被占满）、自己计数并在超限时报错（`for/else`）。

**评分要点**
- **及格**：说出「要逐跳校验，不能只查第一次」。
- **良好**：说出必须**关掉自动跟随**，并意识到重定向是 SSRF 的主要绕过通道。
- **优秀**：主动提到「相对 Location 要用 `urljoin`」与「中间响应要 `aclose`（连接池）」两个实现细节——这两点是从真实踩坑里来的。

**典型弱答**
- 说「先把最终 URL 判一次再抓」（判不到最终 URL，重定向由响应决定）；
- 字符串拼接 `Location`（相对路径拼错，可能拼出绕过判定的 host）；
- 忽略中间响应关闭（连接池耗尽后表现为「随机卡住」）。

**追问**
响应侧那次校验（④）为什么不干脆去掉？它校验的 `stream_resp.url` 与 `current` 正常应相同，什么情况下不同？

---

### XEYO-QA-0269 HTML 转文本的清洗顺序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_common 清洗 | 步骤顺序的两个必守点 | 中等 | 代码阅读 | `python/tools/web_common.py:76-114` |

**面试官提问**
这是 `html_to_text` 的清洗顺序。请指出**哪两步的顺序一旦颠倒就会静默丢内容**，并说明丢的是什么。

```python
	text = _SCRIPT_RE.sub(" ", html)          # 1 删 script/style（连内容）
	text = _CHROME_RE.sub(" ", text)          # 2 删 nav/footer/aside/...（连内容）
	text = _BR_RE.sub("\n", text)             # 3 <br> -> 换行
	text = _BLOCK_CLOSE_RE.sub("\n\n", text)  # 4 块级闭合 -> 双换行
	text = _TAG_RE.sub(" ", text)             # 5 剥离剩余标签
	text = text.replace("&nbsp;"," ")...      # 6 实体解码
	# 7 三级空白归一；8 限长截断
```

**参考答案要点**
两个必守点：

| 点 | 必须怎样 | 颠倒后丢/混入什么 |
|---|---|---|
| ① `script`/`style`/`chrome` 必须在**标签剥离之前**，且必须**连内容一起删**（正则 `.*?</script>` + `re.S`） | 先删块 | 若只去标签，`<script>` 里的 **JS 代码变成正文**；`<nav>` 的**菜单文字污染正文** |
| ② 实体解码必须在**标签剥离之后** | 后解码 | 页面里**转义显示**的代码片段（「用 `&lt;div&gt;` 标签」）解码成 `<div>` 后被当**真标签删掉** |

两条都是「顺序错了不报错、只静默丢内容/混入噪音」型缺陷。另外步骤 4 列的是**块级闭合标签**（`</p>`/`</div>`/`</li>`/`</tr>`…）而非开始标签（闭合点后的换行语义更稳定），它同时列 `br` 用于兜住 `</br>` 这种非法但存在的写法。

**评分要点**
- **及格**：说出 script/style 要先删。
- **良好**：说出「必须连内容删」而非只去标签。
- **优秀**：主动指出实体解码必须后置，并能举出「转义代码片段被当标签删」这个具体后果。

**典型弱答**
- 认为「反正最后都是把标签变空格，顺序无所谓」；
- 把实体解码放最前（最隐蔽，多数页面看不出差异）；
- 用 `<[^>]+>` 一次性解决所有标签（会把 script 内容留下）。

**追问**
步骤 7 的空白归一是三级（行尾 → 连续换行 → 行内多空格），为什么要分三级？它影响下游哪个函数的预算？（→ `focus_text`，0270）

---

### XEYO-QA-0270 焦点提取：从 32K 候选挑 8K 正文

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_common 焦点提取 | 打分、保留规则与预算 | 中等 | 机制解释 | `python/tools/web_common.py:117-215` |

**面试官提问**
抓网页要付两次钱：下载字节与进上下文的 token。我们下载上限 200KB、给模型的正文 8KB。请设计「怎么从大文本里挑出与提问最相关的 8KB」，并说明打分与截断规则。

**参考答案要点**
五步：

1. **抽词**：`_TOKEN_RE` 抽 token（拉丁 `{2,}` 或 CJK 连续串），转小写，**减去 39 个英文停用词**；
2. **切段**：按**空行**切段；
3. **打分**：每段得分 = **命中 token 的种类数**（不看出现次数）；
4. **排序**：元组是 `(score, -i, p)` + `reverse=True`——**`-i` 让同分时原文靠前的排前面**；
5. **保留与装箱**：先取前 5 段，再按**与关系**过滤（`t[0] >= max(1, min_keep-1)` **且** `(t[0] >= 2 or min_keep == 1)`），最后按**原文顺序**贪心装箱到 `max_chars`。

**四条兜底**：body 空 → 空串；prompt 空 → 头部截断；token 空 → 全段拼接截断；**打分后无命中 → 头部截断 + `(no prompt match; head)` 标记**。

**评分要点**
- **及格**：说出「按关键词给段落打分、挑高分段落、限总量」。
- **良好**：说出打分是**种类数**（breadth）而非出现次数（depth），并解释理由（否则反复提一个词的长文会压过真正覆盖问题的短段）。
- **优秀**：讲出三条细节——①保留规则是与关系且用 `min_keep == 1` 做「查询很弱时放宽」的出口；②`-i` 实现「同分按原文顺序」；③**无命中时明确标注**而不是静默给头部。

**典型弱答**
- 说「取前 8KB」（正文在后面或分散时全丢）；
- 按出现次数打分（depth 偏差，长文系统性占优）；
- 不知道无命中时的行为（以为返回空或全部）。

**追问**
装箱是「遇到放不下的段落就 `break`」。若原文顺序是 `[短·高分, 超长·高分, 短·高分]`，输出会是什么？代价是什么？（→ 贪心不回溯，可能只剩一段）

---

### XEYO-QA-0271 搜索后端怎么选与怎么降级

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_search 后端 | 多源降级与配置白名单 | 中等 | 系统设计 | `web_search_tool.py:23-46,325-361` + `web_search_tool/config.py:14-55` |

**面试官提问**
给你的 Agent 装一个 WebSearch，它要长期稳定运行（可能部署在客户内网、可能没有 API key）。请说明后端选择与降级策略。

**参考答案要点**
**六个后端 + 四组解析正则**：

| 后端 | 形态 |
|---|---|
| `_DDG`（`html.duckduckgo.com/html/?q=`） | HTML 页 |
| `_DDG_LITE`（`lite.duckduckgo.com/lite/?q=`） | HTML 页（**同家降级档**） |
| `_BING` / `_MOJEEK` | HTML 页（第三方独立索引） |
| `_BRAVE`（`api.search.brave.com/res/v1/web/search`） | **API**（唯一需 key） |
| SearXNG | **用户自建实例** |

要点：①**没有唯一来源**——按可解析性逐个尝试；②同家两级（DDG html → lite，结构不同需两套正则）；③**DDG 链接是重定向包装**（`/l/?uddg=…`），必须经 `_unwrap_ddg_href` 解包；④`_UA` 伪装浏览器 UA。

**SearXNG 的配置要过白名单**：`config.py` 提供 `normalize_searxng_url` / `set_searxng_url` / `get_searxng_url` / **`is_searxng_base_allowed`**，最后者的签名是 `str | None`（拒绝原因或 None）——与 `is_blocked_url` 同一约定。理由：**「用户可填的 URL」等于一个「取任意地址」的通道**，必须过与出站请求同一套校验。

**评分要点**
- **及格**：说出「多后端 + 逐个降级」。
- **良好**：说出 DDG 两级与「需要 key 的 API 作为最稳档」的分层。
- **优秀**：主动提到「用户可配的 base URL 要过 SSRF 白名单」（多数人只想得到出站 URL 要校验，想不到**配置项**也是入口）。

**典型弱答**
- 只设计一个后端（任一后端封了全废）；
- 忘了 `uddg` 解包（拿到的「URL」不是原地址）；
- 认为「用户填的自建实例地址」是可信配置。

**追问**
用正则从 HTML 抓搜索结果，站点改版后会发生什么？你怎么让这种失效**可被发现**，而不是静默返回 0 条？

---

### XEYO-QA-0272 子 agent 的能力开关怎么设计

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | agent_tool 入参面 | 能力加减与人格注入 | 中等 | 系统设计 | `python/tools/agent_tool/agent_tool.py:122-173` |

**面试官提问**
你要做「派子 agent 干活」的工具。请设计入参：怎么控制它**能写哪些文件**、**能用哪些工具**、**扮演什么角色**？

**参考答案要点**
七个参数（两个必填）：

| 参数 | 作用 | 关键设计 |
|---|---|---|
| `task_id` | 稳定子任务 id | **同时命名 sidechain 文件** |
| `desc` | 任务描述（含约束） | 必填 |
| `scope` | 可写路径列表 | **空 = 只读；`Write`/`Edit` 被移除** |
| `required_tools` | 基线之外的额外工具 | 「**beyond baseline**」= 基线 + 加法 |
| `parent_depth` | 调用方深度 | 配合 `MAX_DEPTH = 1` 禁孙 agent |
| `reuse_agent_id` | 复用已有 agent_id | 「**clear then rerun**」= 重试 |
| `agent_type` | 角色名（`agents/*.toml`） | **追加** `developer_instructions` + 自动标注 spawn 卡片 |

两点值得强调：①`scope` 空**不是无限制而是只读**（方向安全的默认值）；②「只读」的实现是**从工具面移除 `Write`/`Edit`**（不是让工具存在但报错）——按「能强制的就不给模型看」的原则，移除比反复拒绝干净。

**评分要点**
- **及格**：说出「路径范围 + 工具白名单」两类参数。
- **良好**：说出 `scope` 空 = 只读，并说明这是刻意的安全默认。
- **优秀**：区分三个层次——`scope`/`required_tools` 是**能力面**（工具减/加），`agent_type` 是**提示词面**（追加角色指令 + UI 标注）；并指出「移除工具」优于「工具内报错」。

**典型弱答**
- 说 `scope` 空表示「不限制」（危险默认）；
- 把 `agent_type` 说成「替换 system prompt」（是**追加**）；
- 忽略 `parent_depth` 由调用方传入——漏传（默认 0）即绕过深度限制。

**追问**
`parent_depth` 靠调用方自觉传值，这算防护吗？你会怎么把它变成「不依赖调用方正确性」的机制？

---

### XEYO-QA-0273 外部字符串落成文件名要怎么处理

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | agent_tool id 安全化 | 白名单化与重试语义 | 中等 | 机制解释 | `python/tools/agent_tool/agent_tool.py:68-80,154-160` |

**面试官提问**
模型会传 `task_id`，它将用作磁盘文件名。请说明你的安全化函数怎么写，以及**重试同一个子任务**时 id 该怎么处理。

**参考答案要点**
`_safe_agent_id(task_id, *, tail)` 生成 `agent-{安全化后的 task_id}-{tail}`，四步：

```python
	tid = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (task_id or "task")).strip("._") or "task"
```

①空/None → `"task"`；②**白名单字符集**（`isalnum()` 与 `._-`），其余替换 `_`；③去首尾 `._`（防隐藏文件与畸形名）；④结果为空 → `"task"`。

**重试语义 = 同一实体的第二次尝试**：`reuse_agent_id` 描述是「Reuse an existing sidechain agent_id (**clear then rerun**); omit to spawn a new id」。复用 id 的收益：①sidechain 文件不增殖；②同一 `task_id` 的多次尝试在同一条链上可见；③外部引用（卡片/日志/恢复）保持有效。

**评分要点**
- **及格**：说出「过滤非法字符 + 兜底名」。
- **良好**：知道要用**白名单**（保留什么）而非黑名单（禁止什么），并去首尾点。
- **优秀**：指出 `isalnum()` 对 **Unicode 宽容**（中文原样保留），需确认存储层接受非 ASCII 名；并把重试讲成「复用同一逻辑实体」而非「重建」。

**典型弱答**
- 只做黑名单替换（`../`、`\`）其余透传；
- 重试时新建 agent_id（丢可追溯性）；
- 忘了空串兜底（生成 `agent--tail` 畸形名）。

**追问**
项目里已有四处类似「字符串 → 文件名」安全化（会话 sidecar、spill、offload、agent sidechain），替换集与长度上限各不相同。这种重复你怎么处理？

---

### XEYO-QA-0274 TodoWrite 该整体替换还是按条目更新

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | todo_write 合并 | 合并语义与字段保护 | 中等 | 权衡取舍 | `todo_write_tool.py:91-106` + `todo_write_tool/types.py:11-56` |

**面试官提问**
模型每次调 TodoWrite 都倾向**重述整个清单**。如果实现成「整体替换」会出什么问题？你会怎么实现更稳的合并？

**参考答案要点**
`TodoItem` 五个字段：`content` / `status` / **`active_form`** / `id` / **`output`**。其中 `output` 是**引擎侧**字段：

```python
	#: 可选产物路径（相对工作区）……进入 sidecar/transcript 恢复链，是引擎侧任务状态
	#: 注册表的确定性引用，供恢复/续跑/收尾引导等消费。UI 白名单（content/status/activeForm）丢弃。
	output: str = ""
```

**整体替换会丢两类东西**：①**id**（模型未必重述 → 条目身份漂移，外部引用失效）；②**`output`**（模型只在特定时机声明产物路径，重述时省略即被抹掉）。所以应按 **`id`** 做「按条目更新、保留未提及字段」的合并（`_merge_todos`）。

配套两个契约：`todo_item_from_raw` 在**缺 id 时自动生成 `uuid4().hex[:8]`**（保证持久化/恢复链永远有键）；`to_dict()` 的键名是 **`activeForm`（camelCase）**（面向 UI）但**包含 `output`**（供引擎与持久化）——注释提醒 UI 白名单只消费 `content/status/activeForm`。

**评分要点**
- **及格**：说出「应该合并而不是覆盖」。
- **良好**：能指出「按 id 合并」以及至少一个会丢的字段。
- **优秀**：把 `output` 的定位讲清——它把「模型说它生成了什么」变成**结构化事实**，供恢复/续跑/收尾引导确定性引用；并指出 camelCase 与 UI 白名单的分层是有意的。

**典型弱答**
- 认为「模型每次都给全量，替换没问题」；
- 只说「按 content 匹配」而不提 id（内容会被改写，匹配不稳）；
- 把 `activeForm` 缺失当小事（`todo_item_from_raw` 里它是**必填**）。

**追问**
如果模型输入**不带 id**（只给 content/status/activeForm），你的合并怎么判定「条目更新」还是「新条目」？

---

### XEYO-QA-0275 Todo 状态丢了怎么恢复

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | todo_write 恢复 | 多来源恢复路径 | 中等 | 场景设计 | `todo_write_tool/restore.py:20-131` |

**面试官提问**
Agent 进程重启后，之前那份 todo 清单该怎么找回来？请说明你会从哪些地方恢复，以及为什么不能只依赖其中一个。

**参考答案要点**
四条恢复路径（两来源 × 两解析器）：

| 来源 | 入口函数 | 适用场景 |
|---|---|---|
| **内存消息列表** | `restore_todos_from_messages(messages)`（`:54-103`） | 引擎进程内、历史还在 |
| **磁盘转录 JSONL** | `restore_todos_from_transcript(session_id)`（`:104-131`） | **重启后 / 另一入口接入** |

每个来源都有两个子解析器——因为清单可能出现在**两处**：

| 位置 | 解析函数 |
|---|---|
| 工具**入参**（`TodoWrite({"todos":[...]})`） | `parse_todos_from_tool_use_input`（`:44-53`） |
| 工具**结果**（`[todo_list] … [/todo_list]`） | `parse_todos_from_result_text`（`:26-43`，配 `_TODO_LIST_RE`，`:20-25`） |

**不能只依赖一个来源**的原因：`WorkingSnapshot.todos`（sidecar）是**周期性 flush** 的（flush 失败只记日志不抛），可能落后或丢失；而转录是**逐条追加的权威记录**。三者形成依赖层次：sidecar（方便但可能旧）→ 内存消息（会话内最新）→ 转录（权威）。

两条路径都要**取「最后一条」**含清单的记录（后写胜），与 0274 的合并方向一致。

**评分要点**
- **及格**：说出「从转录/sidecar 恢复」。
- **良好**：说出入参与结果**两处都要解析**。
- **优秀**：能解释「为什么不能只信 sidecar」（周期 flush + 静默失败的风险），并指出**写入格式与恢复解析是配对的**（`TODO_LIST_TAG = "todo_list"` ↔ `_TODO_LIST_RE`）——这是可恢复性的前提。

**典型弱答**
- 只从 sidecar 恢复（flush 落后时丢最新状态）；
- 只解析工具结果、忽略入参（模型带的清单在入参里）；
- 没有固定的写入格式（无法可靠解析）。

**追问**
「取最后一条」在转录被回滚（rewind）之后会怎样？你还会信哪一条？（→ 与 B09-0450 的三载体残留问题同源）

---

### XEYO-QA-0276 技能要对谁可见、谁能禁

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | skill_tool 可见性 | 双可见性与三方许可 | 中等 | 系统设计 | `python/tools/skill_tool/skill_tool.py:138-172,280-285` |

**面试官提问**
你有「技能（skill）」体系：既有模型自动调用，也有用户手动 `/skill` 触发。请设计可见性与禁用规则——谁能决定一个技能对谁可见？

**参考答案要点**
六道闸（发现 → 存在 → 三方许可）：

| 层次 | 机制 |
|---|---|
| 被发现 | `discover_skill_dirs(cwd)`（`:36-40`） |
| 存在 | `_entry(entries, name)` 非 `None`（`:54-63`） |
| **模型可调用** | `_model_invocable_ok`（`:138-144`） |
| **企业策略未禁** | `_enterprise_denied`（`:145-151`） |
| **运行时未禁用** | `_disabled_now(cwd, name)`（`:152-172`，**带 cwd = 按工作区**） |
| 正文可加载且不超限 | `load_skill_body`（`:64-74`）+ `BODY_MAX = 12_000` |

**双可见性**：`_model_invocable_ok` 与 `is_user_invocable`（`:280-285`）是**两套判定**——同一技能可以「模型能调、用户不能」或反之（例如危险操作只给用户手动跑）。

**关键设计**：三道许可**相互独立且必须全过**，**任何一方都不能单方面放开**——用户不能打开「企业已禁用的技能」（`_enterprise_denied` 是更靠前的独立判定）。这与扩展层「停用即时 DENY、不可被授权穿越」同一取向。

**评分要点**
- **及格**：说出「有开关能禁用技能」。
- **良好**：说出**模型与用户是两套可见性**，不是一套。
- **优秀**：主动指出「三方许可互相独立、禁用是单向的」，并意识到 `_disabled_now` 带 `cwd` 说明禁用是**按工作区**生效的（同一技能在 A 工作区可用、B 工作区禁用）。

**典型弱答**
- 只设计一个「启用/禁用」开关（无法区分模型与用户）；
- 让运行时开关能覆盖企业策略（权限倒挂）；
- 认为技能清单是全局的（实际按工作区解析）。

**追问**
技能目录只列「通过闸的技能」。如果被禁用的技能仍占用目录预算会怎样？目录有 2 400 字符上限，这跟「少数技能把预算吃光」是什么关系？

---

### XEYO-QA-0277 三级预算：常驻目录该放多少信息

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | skill_tool 两级输出 | 常驻 vs 按需预算 | 中等 | 权衡取舍 | `python/tools/skill_tool/skill_tool.py:26-33,82-121` |

**面试官提问**
技能信息要进模型上下文。请设计「怎么让模型知道有哪些技能、又不要把上下文吃光」，并给出你的预算数。

**参考答案要点**
三档预算（越常驻越短）：

| 档 | 常量 | 何时出现 |
|---|---|---|
| **常驻目录**（catalog） | `CATALOG_MAX_CHARS = 2_400`，每行 `CATALOG_LINE_DESC = 120` | **每轮** |
| **按需列表**（list） | `LIST_MAX_CHARS = 4_000`，每行 `LIST_LINE_DESC = 500` | 模型显式 `list` 时 |
| **技能正文**（body） | `BODY_MAX = 12_000` | 模型决定加载某技能时 |

两个 `*_LINE_DESC` 是 **120 vs 500（4 倍差）**；`_list_response(entries, query)` 还带 **query 过滤**（不是列全部）。

**设计判据**：**上下文预算按「可见频率」分配**——常驻内容压到「够识别」（一行 120 字符足够判断这个技能是不是相关的），详细信息留给按需通道。

**评分要点**
- **及格**：说出「常驻的短、按需的长」。
- **良好**：给出三档数量级并说明「可见频率决定预算」。
- **优秀**：指出 list 的两件事——**过滤**（query 决定哪些技能进列表）与**展示**（`_one_line(desc, limit)` 决定每行多长）是分离的；并意识到总量上限会导致**顺序影响可见性**（超限时后面的技能完全不出现）。

**典型弱答**
- 把全部技能描述塞进 system（每轮付费）；
- 两档用同一个行上限（无法体现「常驻要更省」）；
- 忽略总量截断的存在（技能多了会静默少列）。

**追问**
如果用同一套「一行化」思路处理记忆索引（每轮注入），你会遇到什么额外约束？（→ 索引会随写入变化，必须放在不会破坏 KV 前缀的位置）

---

### XEYO-QA-0278 Memory 工具该暴露哪些动作

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | memory_tool 入口 | 动作面与权限粒度 | 中等 | 系统设计 | `python/tools/memory_tool/memory_tool.py:36-122` |

**面试官提问**
给你一个「长期记忆」子系统，你要把它包成一个给模型用的工具。请列出动作清单，并说明为什么这样切分。

**参考答案要点**
六个 action（`_ACTIONS`，`:36`）：`write` / `update` / `forget` / `search` / `peers` / `retrieve`。

注意「删除」叫 **`forget`** 而不是 `delete`——因为它**不是抹掉文件**，而是留一块墓碑（`Tombstone`：`id`/`deleted_at`/`reason`），并让「复活」永远被拒（`may_resurrect` 恒 False）。

其中两个 action **不是对 note 的 CRUD**，而是两条独立通道：

| action | 数据源 | 为什么独立 |
|---|---|---|
| `peers` | **同工作区其他会话的 `session.md`** | 数据源不是 memdir 的 note |
| `retrieve` | **C2 压缩碎片表（fragments）** | 拿的是压缩时抓拍的原子，不是 note |

`retrieve` 的返回内容受入库上限约束（`FRAGMENT_ROW_CAP = 400` / `FRAGMENT_TEXT_CAP = 4096`），所以「按锚点取回原文」在超过 4096 字符时是**截断后**的。

**评分要点**
- **及格**：说出「增删改查」四类。
- **良好**：说出 `forget` 的墓碑语义（不是物理删除），并给出至少一条独立通道（`peers` 或 `retrieve`）。
- **优秀**：主动指出**工具级权限粒度的代价**——权限按**工具名**裁决，所以把读写动作放进同一个 `Memory` 工具，就无法区分「`search` 只读」与「`forget` 有副作用」；这是「工具面数量少 vs 权限粒度细」的取舍（对照文件五件套把读写拆成三个工具）。

**典型弱答**
- 设计成 `delete`（丢墓碑语义，等于允许「复活」）；
- 把 `peers`/`retrieve` 当成 `search` 的参数（数据源完全不同）；
- 忽略单一工具带来的权限粒度损失。

**追问**
`retrieve` 只能拿回 ≤4096 字符的碎片。如果模型需要完整原文，正确的做法是什么？（→ 重跑工具 / 读 transcript，而不是指望 retrieve）

---

### XEYO-QA-0279 NotebookEdit 为什么必须专用

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | notebook_edit 结构 | 结构化容器的编辑 | 中等 | 机制解释 | `notebook_edit_tool.py:19-40,354-379` |

**面试官提问**
模型要改一个 `.ipynb`。为什么不能让通用的「字符串替换」工具去改，非要写一个专用工具？

**参考答案要点**
`.ipynb` 是**结构化容器（JSON + 数组）**，字段有硬要求：

| 字段 | 要求 | 不满足的后果 |
|---|---|---|
| `source` | `list[str]`，每行一个元素，**除最后一行外都以 `\n` 结尾** | Jupyter 能打开但**多/少空行**，diff 噪声 |
| `cell_type` | `"code"` / `"markdown"` / `"raw"` | 渲染错误 |
| `outputs` / `execution_count` | code cell 必需（可空） | 可能报 schema 错 |
| `metadata` | 必需（可 `{}`） | 同上 |

所以专用工具提供：`_source_to_list(source)`（`:354-369`，多行串 → nbformat 的 list，处理末行换行）与 `_new_cell(cell_type, source)`（`:370-379`，用 `_EMPTY_NB` 骨架构造合法 cell）；操作面是 `replace` / `insert` / `delete`（`insert` 无 `cell_idx` 则追加；`cell_type` 默认 `code`）；另有 `_MAX_SOURCE = 1 MiB` 上限。

对照：通用 `Write`/`Edit` 对 `.ipynb` **明确拒绝**，`Read` 返回 cell 索引摘要而非整份 JSON——**读、写、编辑三条路都换成 cell 语义**。

**评分要点**
- **及格**：说出「notebook 是 JSON，字符串替换会破坏结构」。
- **良好**：能举出具体字段（`source` 必须是列表 / code cell 要有 `outputs`）。
- **优秀**：主动指出 `_source_to_list` 的**末行不带换行**这类细节，并说明它的失败模式是「**静默的 diff 噪声**」（能打开但每次编辑多一个空行）——这与「行尾被整份改写」属同一类「功能正常但产生了不该有的变更」。

**典型弱答**
- 认为「JSON 字符串替换也能用，小心点就行」；
- 不知道 `source` 是列表（把它当普通字符串）；
- 忽略 `cell_type` 有默认值（以为必填）。

**追问**
`Read` 对 `.ipynb` 返回的是 cell 索引摘要，而完整 JSON 存进了会话读态。这个分仓对「改之前必须先读」这条校验意味着什么？

---

### XEYO-QA-0280 Git 工具的输出要不要落盘

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | git_tool 输出治理 | 两层策略与落盘差 | 中等 | 对比辨析 | `python/tools/git_tool/git_tool.py:12-20,160-182` |

**面试官提问**
你的 Git 工具输出一份很长的 diff，超过上限了。你会怎么处理？请说明你的两层处理方式，以及**被截掉的中间部分还能不能拿回来**。

**参考答案要点**
两层处理（与 Bash 路径同构）：

| 层 | 函数 | 职责 |
|---|---|---|
| **语义层** | `_maybe_compact(action, text)`（`:160-174`） | 按 action 做不同类型输出压缩 |
| **体积层** | `_cap(text)`（`:175-182`） | 按字符截断到 `_OUT_CAP = 16_000` |

常量与集合：`_READ_ACTIONS` 五个（`status`/`log`/`branches`/`diff`/`summary`）；`_WRITE_ACTIONS` 另有一集；`_STATUS_PATH_CAP = 80`（status 最多列 80 个路径）。

**★ 关键差别：Git 工具的体积层不落盘**——`_cap` 只截断，**没有 `full at <path>` 标记**。所以**用 Git 工具看长 diff，中间内容丢掉且无法取回**；而用 Bash 跑 `git diff` 则可通过落盘文件找回（`truncate_for_model` 会落盘）。

★ `summary` 是 Git 工具**自有的聚合动作**（不是 git 子命令），把多个只读信息合成一份摘要。

**评分要点**
- **及格**：说出「先压缩、再按上限截断」。
- **良好**：说出 `_OUT_CAP = 16_000` 与「按 action 分别压缩」。
- **优秀**：主动指出**两条路径的落盘能力差**——同一个 `git diff` 走 Git 工具会丢中间内容且无原文可取，走 Bash 则能落盘找回；并能指出 `meta.py` 把 Git 描述为「Read-only … No commit」与代码里存在 `_WRITE_ACTIONS` **存在张力**（要么写动作未启用、要么描述过期）。

**典型弱答**
- 只做字符截断（丢掉「按语义压缩」这一层）；
- 认为截断后还能拿回原文（本路径不落盘）；
- 没注意到「描述说只读、代码有写动作集」这个矛盾。

**追问**
如果你要让「用 Git 工具」与「用 Bash 跑 git」在证据可达性上一致，最小改动是什么？（→ 体积层复用 spill 落盘）

---

### XEYO-QA-0281 诊断工具怎么决定检查什么

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | diagnostics 语言面 | 探测链与覆盖面报告 | 中等 | 机制解释 | `python/tools/diagnostics_tool/diagnostics_tool.py:170-267,305-387,405-423` |

**面试官提问**
一个诊断工具：给它一个文件或目录，它要做语法/静态检查。请说明你怎么决定「用哪套检查器」，以及**检查不了的时候会怎么返回**。

**参考答案要点**
**探测链（四级）**：

| 级 | 机制 |
|---|---|
| ① 显式 `lang` 参数 | 模型直说 |
| ② 目标形态 | `_looks_python(target, lang)` / `_looks_typescript(target, lang)` |
| ③ 目录内容浅探测 | `_shallow_has(root, suffixes)`（两层内是否含该类文件） |
| ④ 判定不出 | **不诊断，但在结果里说明** |

**两条执行路径**：Python 走 `_iter_py_files` → `_run_py_compile`（语法）+ `_run_ruff`（静态）；TS/JS 走 `_find_tsconfig` + **`_find_local_tsc`** → `_run_tsc`。

**优先用项目自己的工具链**是核心决策：本地 `tsc` + 项目 `tsconfig.json`，保证「诊断用的版本与规则 = 项目实际构建用的」（用全局或下载的版本会产生不同的报错）。

**★ 结果必须报告覆盖面**：`_format_result(lines, used, notes)` 的三个入参里，`used`（实际用了哪些检查器）与 `notes`（说明）与诊断行**并列返回**——「跳过检查要写出来」，否则模型会把「我没能判定语言」读成「无问题」。

**评分要点**
- **及格**：说出「按扩展名/目录内容判断语言」。
- **良好**：说出「优先本地工具链 + 项目配置」的理由（版本一致性）。
- **优秀**：主动强调**「无输出 ≠ 无问题」**，并指出必须用 `used`/`notes` 把覆盖面呈现出来；能把这一点与「命令静默即成功」的相反情形（`SILENT_COMMANDS`）对比，说明两类「空输出」语义不同。

**典型弱答**
- 判定不出语言时返回空结果（被读成「无问题」）；
- 用全局/最新版 tsc（与项目构建规则不一致）；
- 只返回诊断行，不说用了什么检查器。

**追问**
`_MAX_DEPTH = 2` / `_MAX_FILES = 50` 这两个范围限制意味着什么定位？如果模型给了一个 monorepo 根目录，会发生什么？

---

### XEYO-QA-0282 工作区级日志怎么按会话取

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | journal_query | 存储域与过滤 | 中等 | 场景设计 | `python/tools/journal_query_tool/journal_query_tool.py:12-116` |

**面试官提问**
我们有一份「工作区级」的文件变更日志（每次写文件追加一条），多个会话共享同一份。模型要问「我刚改了什么」。请说明你的查询工具要注意什么。

**参考答案要点**
`JournalQueryTool`（`:12-97`）查的是 journal 的变更记录（`ChangeRecord`：`seq` / `agent_id` / `path` / `action`（`"edit"`｜`"write"`）/ `file_hash_after` / `syntax_valid` / `conflict_task` / `diff` / `metadata`）。

`_filter_rows_for_session(rows, limit)`（`:98-116`）做两件事：

| 职责 | 为什么必需 |
|---|---|
| **按会话过滤** | journal 的位置由 `workspace_id` 决定（同一工作区所有会话共享）→ 不过滤就会看到**别的会话/别的 agent 的改动** |
| **限制条数** | 每次写文件一条，日志会很长 |

★ **过滤不是优化而是正确性要求**：看到别人的改动，模型会误以为是自己的（进而做出错误判断，例如「我已经改过这个文件了」）。

对照存储域分层（哪些会话私有、哪些工作区共享）：

| 数据 | 存储域 |
|---|---|
| 转录 JSONL / sidecar / `session.md` / spill | **会话** |
| **journal / memdir / memindex / offload** | **工作区** |

**评分要点**
- **及格**：说出「查变更日志 + 限制条数」。
- **良好**：说出**必须按会话过滤**，并解释原因（工作区级共享）。
- **优秀**：能主动给出「存储域分层表」并推导出一条一般规则——**存储域越宽，读取端就越需要显式隔离**（工作区级数据都要按会话/agent 过滤；会话级数据天然隔离）。

**典型弱答**
- 直接把整份日志给模型（混入他人改动）；
- 把过滤当性能优化（它是正确性问题）；
- 忽略 `limit`（日志长到爆上下文）。

**追问**
`action` 只有 `edit`/`write` 两种，而文件还可能被 `Bash` 或外部编辑器改。这些改动会出现在 journal 里吗？（→ 与「workspace_revision 是检测而非阻止」同一类覆盖缺口）

---

### XEYO-QA-0283 阻塞式提问工具的协议怎么定

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | ask_user_question | 形态归一与可寻址 | 中等 | 系统设计 | `python/tools/ask_user_question_tool/ask_user_question_tool.py:19-89` |

**面试官提问**
模型需要向用户提问（多选/单选），然后**停下来等回答**。请设计这个工具的输入输出契约，并说明为什么要做形态归一化。

**参考答案要点**
契约三要素：

| 要素 | 实现 |
|---|---|
| **可寻址** | `ASK_REQUEST_ID_KEY = "__ask_request_id"`（`:21`）——引擎注入的保留键（双下划线前缀标识「非模型字段」），用于把挂起提问与后续回执对上 |
| **形态归一** | `_option_label(opt)`（`:24-33`）+ `flatten_options(options_raw)`（`:34-45`）：把模型的各种写法压成 `list[str]` |
| **协议适配** | `format_questions_payload(raw)`（`:46-89`）：原始 dict → 前端可渲染 payload |

**为什么必须形态归一**：模型表达选项的形态不统一——

```json
["A","B"]                                // 纯字符串
[{"label":"A"},{"label":"B"}]            // 带 label
[{"text":"A","description":"..."}]       // 带 text/描述
[{"value":"A","label":"A"}]
```

而前端对话框只需要**字符串标签列表**。所以「模型给什么形态都接、工具输出必须规范」——与本项目其他宽容输入（`activeForm`/`active_form` 双键、字符串数字→int）同族。

**★ 归一化是有损的**：`_option_label` 只取标签，`description`/`value` 等字段被丢弃。如果前端其实需要显示描述，这里是**真实的信息损失**（需与前端契约对齐）。

**评分要点**
- **及格**：说出「提问 + 选项 + 等用户回答」。
- **良好**：说出要有**请求 id** 来把「挂起」与「回执」对上（阻塞型工具的关键）。
- **优秀**：指出形态归一化的**有损面**，并把它讲成「服务端定死契约、前端只当渲染器」的取舍（好处是契约集中；代价是前端要新形态就得改 Python）。

**典型弱答**
- 只说「选项是字符串数组」（模型可能传对象）；
- 没有 request id（并发/多次提问时无法对账）；
- 把它与「权限 ASK（授权确认）」混为一谈（一个是问信息、一个是求授权，虽然都是挂起-回执模式）。

**追问**
这个工具会让整个回合**阻塞**。如果用户一直不回答，系统上应该有什么机制兜底？（→ 挂起项 TTL）

---

### XEYO-QA-0284 一轮里多个工具调用怎么并行

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | orchestration 编排 | 分区与双层限流 | 中等 | 系统设计 | `python/tools/orchestration.py:31-109` |

**面试官提问**
模型一轮里可能同时发多个工具调用。请设计执行策略：哪些能并行、哪些必须串行，以及并发怎么限。

**参考答案要点**
**按调用逐个判定**（不是全局开关）：

```python
	# is_concurrency_safe(registry, name)  →  查工具声明
	# partition_tool_calls(...)            →  分成「可并行组 / 必须串行组」
```

| 组件 | 职责 |
|---|---|
| `is_concurrency_safe(registry, name)`（`:73-84`） | 通过 registry 查工具实例并读它的 `is_concurrency_safe()` |
| `partition_tool_calls(...)`（`:85-109`） | 分组；并行组受 `_max_concurrency()`（`:31-46`）限流，串行组按原顺序执行 |
| `_tool_timeout_s()`（`:47-60`） | 工具级超时（`float | None`），到点**放弃等待**该调用 |
| `_progress_interval_s()`（`:61-72`）+ `_emit_result`（`:110-`） | 进度节流与结果发射 |

**两层限流**（容易漏的第二层）：编排层 `_max_concurrency()` 决定「本轮最多同时跑几个」；而**工具自己还有一层**——`Agent` 工具里 `threading.Semaphore(8)`（`XEYO_MAX_CONCURRENT_AGENTS` 可配）。两层作用域不同（编排并发度 vs 工具的进程级槽位）。

**评分要点**
- **及格**：说出「只读的并行、写操作的串行」。
- **良好**：说出判定依据是**工具的 `is_concurrency_safe` 声明**，且是通过 registry 查（所以动态注册的工具也能正确参与）。
- **优秀**：主动提到**两层限流**，并指出 `_tool_timeout_s` 的语义是「编排层放弃等待」——**底层进程可能仍在跑**（这跟「杀掉」是两件事）。

**典型弱答**
- 按工具名硬编码一张并行白名单（动态工具/MCP 工具会漏）；
- 以为只有一层限流；
- 把「超时」理解为「已终止」（只是不再等）。

**追问**
`registry.get(name)` 返回 `None`（工具没注册）时，你倾向判「并发安全」还是「不安全」？为什么？

---

### XEYO-QA-0285 截图怎么安全地送到外部通道

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | screenshot 输出面 | 跨通道传递资产 | 中等 | 场景设计 | `python/tools/screenshot_tool/screenshot_tool.py:14-30` |

**面试官提问**
Agent 截了个图，既要给模型看，也可能要发给用户（微信）。请设计它的输出通道，并说明「为什么不能把内部文件路径直接交给外部通道」。

**参考答案要点**
三条输出通道：

| 通道 | 控制 |
|---|---|
| ① 文件路径（默认） | 省上下文 |
| ② **图像本体**（给 vision 模型） | `_wants_image(raw)`（`:23-30`）——**调用级**选择 |
| ③ **微信副本路径** | `_wechat_copy_path(path)`（`:17-22`） |

**为什么不能直接用内部路径**：①内部截图路径可能被清理（临时目录/保留期）；②格式与命名可能不符合通道要求。所以**派生一份专用副本**——这与「不要跨边界复用内部表示」是同一条原则（对照容器路由不靠宿主 shell 拼串）。

**★ 粒度差异值得指出**：`Screenshot` 的「要不要给图」是**调用级**参数；而 `Read` 的 vision 是**会话级能力**（按厂商/模型能力在会话构建时注入，不可中途改）。同一件事（把图像给模型）在两条工具链上的决策粒度不同。

**评分要点**
- **及格**：说出「可以返回路径或图像」。
- **良好**：说出要**派生外部可用的副本**，而不是把内部路径交出去。
- **优秀**：能讲出两个理由（内部路径有生命周期 / 格式与命名契约不同），并主动指出 `Screenshot`（调用级）与 `Read`（会话级）的 vision 决策粒度差异。

**典型弱答**
- 直接把内部临时路径发给外部通道；
- 认为「给不给图」是全局开关（是调用级）；
- 忽略 `_wants_image` 存在（默认给路径已足够，给图要花钱）。

**追问**
如果内部截图在 5 分钟后被清理，而用户 10 分钟后才点开微信里的图片，会发生什么？这要求副本落在哪里？

---

### XEYO-QA-0286 长任务的进度要不要进模型上下文

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | progress_sink | 进度通道与节流 | 中等 | 权衡取舍 | `python/tools/progress_sink.py` + `agent_tool.py:30` + `orchestration.py:61-72,110` |

**面试官提问**
一个子 agent 要跑几分钟。子 agent 的中间进度应该：进模型上下文、进用户界面、还是都不进？请说明你的选择与理由。

**参考答案要点**
**进用户界面，不进模型上下文。** 实现线索：

| 角色 | 组件 |
|---|---|
| 上报 | `emit_progress`（`progress_sink.py`）；`Agent` 工具 import 它（`agent_tool.py:30`）；`orchestration._emit_result`（`:110-`） |
| 节流 | `orchestration._progress_interval_s()`（`:61-72`） |

**两个判断**：

| 概念确认 | 理由 |
|---|---|
| **不给模型看** | 进度是「引擎能自己处理的运维信息」，按「能静默就不说话」原则不进注意力；而且进度会**每几秒变化**，一旦进上下文就会破坏 KV 前缀 |
| **要节流** | 不节流会**刷爆事件流/SSE**（慢订阅者队列溢出是已记录的故障类型） |

配套的三件事共同构成「**长任务可观测性**」：进度上报（本模块）+ Bash 前台命令自动**晋升为后台 job**（不重启进程）+ 后台任务的**完成通知**。

**评分要点**
- **及格**：说出「进度给用户看」。
- **良好**：说明理由（进度是运维信息、不该占模型上下文）。
- **优秀**：主动提到**必须节流**并给出原因（频变内容会破坏 KV 前缀 + 刷爆 SSE），并把「晋升不重启」「完成通知」串成一条完整的长任务体验链路。

**典型弱答**
- 把进度写进工具结果（模型每轮都看到一堆噪声）；
- 不节流（高频事件把 SSE 打满）；
- 认为「长任务只能等」——不知道晋升与完成通知机制。

**追问**
如果进度进了上下文，除了浪费 token，还会破坏什么？（→ KV 前缀命中率：频变内容放在前缀区会让每轮都 miss）

---

### XEYO-QA-0287 【困难】SSRF 校验的 TOCTOU 缺口

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web 出站安全 | 检查与使用的窗口 | 困难 | 安全拷问 | `python/tools/web_common.py:52-73` + `web_fetch_tool.py:132-138` |

**面试官提问**
你的 SSRF 防护在请求前解析域名并检查 IP。现在有人告诉你「这套防护可以被绕过」。请说出绕过机制，并给出至少两种修法及各自代价。

**参考答案要点**
**缺口：检查与请求是两次独立解析。**

```python
	# web_common.py:54   检查用这一次解析
	infos = socket.getaddrinfo(host, None)
	...
	# web_fetch_tool.py:138  真正请求时 httpx 内部再解析一次
	async with client.stream("GET", current) as stream_resp:
```

三个条件同时成立 → 可绕过：①`is_blocked_url` 只返回**原因码或 None**，**不把解析到的 IP 交出来**；②请求 URL 里仍是**主机名**（`httpx` 必须自己解析）；③两次解析**时刻不同**。

攻击者只要有**自己的域名 + 可控 DNS**：先让记录指向公网 IP（通过检查），检查后立刻改成 `127.0.0.1` / `10.x` / `169.254.169.254`（TTL=0 或按查询次数切换响应）——即 **DNS rebinding**。成功后可打内网服务或云元数据凭证。

**重定向每一跳同样有这个问题**（逐跳校验的检查与请求之间也是两次解析）。

| 修法 | 做法 | 代价 |
|---|---|---|
| ① 解析一次、**用 IP 连接** | 让检查返回解析到的 IP，请求时直连 IP + 设 `Host` 头 | 彻底；但 HTTPS 的 SNI/证书校验要额外处理 |
| ② 连接后**校验对端地址** | 读 socket `peername`，私网则立即断开 | 简单；但**有窗口**（连接已建立） |
| ③ **固定 DNS** | 自定义 resolver / transport，把解析结果绑定到本次请求 | 依赖 `httpx` 扩展点 |
| ④ **网络层兜底** | 出站代理/防火墙禁私网 | 最可靠；依赖部署环境 |

**评分要点**
- **及格**：说出「DNS 可能变化」这一方向。
- **良好**：能讲清「检查用一次解析、请求用另一次解析」这个具体机制，并说出 DNS rebinding 的名字。
- **优秀**：给出可落地的修法（用 IP 连接 + Host 头）并主动指出它引入的 **TLS/SNI 复杂度**；同时提到网络层兜底，说明「应用层尽力 + 网络层保底」的分工。

**典型弱答**
- 认为「检查通过了就安全」；
- 只说「加黑名单/更严格的正则」（正则解决不了时间窗）；
- 忽略重定向每跳也有同一缺口。

**追问**
项目里另一处功能（破坏性操作快照）**主动避开了 TOCTOU**——它怎么做的？为什么那里能避开、这里不能？（→ 词法级目标提取，不查存在性）

---

### XEYO-QA-0288 【困难】手动重定向的实现代价

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_fetch 重定向 | 四道保护与连接管理 | 困难 | 代码阅读 | `python/tools/web_fetch_tool/web_fetch_tool.py:121-173` |

**面试官提问**
你把 HTTP 客户端的自动重定向关掉了（为了逐跳校验）。请列出**因此必须自己实现**的所有事情，并指出其中**最容易漏、后果最隐蔽**的一件。

**参考答案要点**
必须自己做的四件事：

| # | 必须自己做 | 代码位置 |
|---|---|---|
| 1 | 判断哪些状态码算重定向（301/302/303/307/308） | `:139` |
| 2 | 解析**相对** `Location`（`urljoin`） | `:146` |
| 3 | **管理中间响应的生命周期**（关闭/排空） | `:138` 的 `async with` + `:148` 的 `await stream_resp.aclose()` |
| 4 | 计数并在超限时报错 | `:130` 的 `for _ in range(_MAX_REDIRECTS + 1)` + `:172-173` 的 `for/else` |

**最容易漏、后果最隐蔽的是第 3 件**：漏了 `aclose()` 不会立刻报错，而是**每次重定向泄漏一个连接**——`AsyncClient` 连接池被占满后，后续请求表现为**随机卡住/超时**，与「网络慢」难以区分。注释「先短暂排空再跟随重定向」说明这里的关闭目的不只是释放，还要**排空**流（否则连接无法复用于下一次请求）。

另有四处细节保护：`abort.raise_if_aborted()` 每轮（`:131`，让长重定向链可中止）、`if not loc` 报错（`:140-145`，防畸形 3xx）、请求前校验（`:132`）、响应侧再校验（`:151`，纵深防御：不信任「我请求的 = 我得到的」）。

**评分要点**
- **及格**：说出「要自己判断状态码 + 自己算相对 URL」。
- **良好**：说出次数上限与 `for/else` 的终止语义。
- **优秀**：**主动点出中间响应关闭**，并解释它的失败模式是「连接池耗尽 → 随机卡住」，而不是一个显式错误。

**典型弱答**
- 只想到「循环跟 Location」；
- 用 `Location` 字符串直接拼接（相对路径拼错，可能拼出绕过判定的 host）；
- 忽略 `for/else`（超限时静默返回最后结果）。

**追问**
响应侧那次校验（`:151`）在什么情况下真正起作用？（→ 当客户端的实际 URL 与 `current` 不一致时；典型是库/中间层改写了请求）

---

### XEYO-QA-0289 【困难】焦点提取的不变式与代价

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_common 装箱 | 两条不变式 | 困难 | 代码阅读 | `python/tools/web_common.py:177-215` |

**面试官提问**
这段「挑段落填预算」的代码维持了哪两条不变式？其中一条是靠一个**下标取负**的技巧实现的——请指出它，并说明如果去掉会发生什么。

**参考答案要点**
**两条不变式**：

| # | 不变式 | 实现 |
|---|---|---|
| 1 | **段落数量上限 5** | `top = scored[: max(1, min(5, len(scored)))]`（`:193`，注释「避免弱相邻段落稀释焦点」） |
| 2 | **输出保持原文段落顺序** | `chosen = sorted(top, key=lambda x: -x[1])`（`:199`，注释 `# original order`） |

**下标取负的技巧**：打分元组是 `(score, -i, p)`（`:182`），排序 `scored.sort(reverse=True)`（`:183`）：

| 比较位 | 反向排序效果 |
|---|---|
| `score` | 高在前 ✅ |
| **`-i`** | `-i` 大在前 → **`i` 小在前** → **原文靠前的段落在前** ✅ |

**去掉 `-i` 会怎样**：`sort(reverse=True)` 在同分时会**反向**使用原始顺序，于是**同分时靠后的段落被排到前面**——与直觉相反，且因为「按分数取前 5」的筛选在排序之后，**这个偏差还会影响「哪些段落进入候选」**。

**输出可能比预期更少的三种路径**：①保留规则是与关系（最高分 3 分时要求 ≥2 分，1 分段落全被过滤）；②装箱是**贪心不回溯**——遇到放不下的段落就 `break`，后面即使有短的也不再尝试；③单段超过预算时只输出它并被截断。

**评分要点**
- **及格**：说出「按分数排序、取前若干段」。
- **良好**：说出两条不变式，并知道输出保持原文顺序。
- **优秀**：指出 `-i` 的作用与去掉后的**反向偏差**；指出装箱是贪心不回溯并给出「长段挡路」的具体后果；能指出打分只统计 `score > 0` 的段落（所以 `min_keep >= 1`，这也是 `min_keep == 1` 出口存在的理由）。

**典型弱答**
- 以为「同分按原文顺序」是 `sort` 稳定性的功劳（是靠 `-i`）；
- 以为装箱会跳过过长的段落继续试后面的；
- 没注意三种结尾标记（`… truncated` / `… focused` / `no prompt match; head`）是互斥且带语义的。

**追问**
如果把这套打分换成「按出现次数加权」，会对长文档产生什么系统性偏差？项目里另一处检索打分为什么也要「封顶」？（→ depth → breadth）

---

### XEYO-QA-0290 【困难】引擎写给模型的指令该怎么措辞

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | agent_tool 结果正文 | 引擎文本与注意力纪律 | 困难 | 权衡取舍 | `python/tools/agent_tool/agent_tool.py:38-57` |

**面试官提问**
子 agent 干完活，主 agent 会看到一段工具结果。请设计这段文本——**你会不会在里面写「请用上面的结果回答原始问题」这类指令**？说明理由，并给出你的判断依据。

**参考答案要点**
当前实现**确实带了指令**（`:48-57`）：

```python
	status = "ERROR" if is_error else "OK"
	return (
		f"[Agent tool_result status={status} subagent={agent_id} task_id={task_id}]\n"
		f"Assigned task: {desc}\n"
		f"---\n"
		f"{body}\n"
		f"---\n"
		"Instruction for main agent: Answer the user's ORIGINAL request using "
		"the subagent result above. Do not discuss Memory indexes or memory "
		"tools unless the user explicitly asked about memory."
	)
```

这段文本的结构分两半：**事实**（`status` / `subagent` / `task_id` / `Assigned task` / 结果正文，用 `---` 分隔）+ **一段指令**（"Instruction for main agent: …"）。

**判断依据（项目自身的引擎纪律）**：模型可见文本只承载**状态/结果/事实**，禁止建议、劝导、评价与「应该/不要再」式编排——因为**引擎文本里的护栏会污染注意力**，正确的位置是执行层（拒绝、报错、折叠）。按这条纪律，这段 "Instruction for main agent" 属于**越界的编排文本**。

**它为什么可能存在**：注释说明了动机（`:46`）——「主循环看到的 Agent tool_result 正文（续写原问题，**勿拐到 Memory**）」，即它是在处理一个**真实观测到的行为偏差**（子 agent 的结果把主 agent 带偏到记忆索引话题上）。

**正确的替代方向**（面试可答）：把这段的**意图**从「文字劝导」移到「执行层/事实层」——①用结构化字段表达（`status` 已经是事实型的，可扩展为 `origin` / `request_scope` 等字段）；②如果问题是「子 agent 带了无关内容」，应在**子 agent 侧**修剪输出，而不是在主 agent 侧加一句话；③如果确实需要保留，也应改成**中性的信息来源标注**（如「以下内容来自子任务 X」）而不是祈使句。

**评分要点**
- **及格**：能看出这段里有指令文本。
- **良好**：说出「引擎文本应该只给事实」的原则，并指出这段与原则冲突。
- **优秀**：能给出**为什么它当初被写进去**（有观测到的行为偏差）+ **正确的替代方向**（把意图移到结构字段或上游修剪），而不是简单地说「删掉就行」——因为删掉可能让原来的偏差回来。

**典型弱答**
- 认为「加一句提示没什么坏处」（低估注意力污染）；
- 一刀切说「全删」（不回答「那原来那个偏差怎么办」）；
- 把 `status`/`task_id` 这类事实字段也当成「指令」（分不清事实与指令）。

**追问**
如果删掉那段指令后主 agent 又开始把话题拐到记忆索引上，你会怎么在**不给主 agent 写指令**的前提下解决？

---

### XEYO-QA-0291 【困难】抓到的不是文本时怎么返回

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_fetch 内容类型 | 成功但无正文 | 困难 | 场景设计 | `python/tools/web_fetch_tool/web_fetch_tool.py:182-220` |

**面试官提问**
你要抓的 URL 返回一个 PDF 或图片。工具应该报错、返回空、还是返回什么？请给出你的设计，并说明「成功」与「可用」的区别。

**参考答案要点**
实现按内容类型分三路（`:182-206`）：

| 类型 | 处理 |
|---|---|
| HTML（含 `content-type` 含 html，或正文以 `<!doctype html`/`<html` 开头） | `html_to_text(text, max_chars=_OUT_CAP * 4)` → `focus_text(..., max_chars=_OUT_CAP)` |
| 文本类（`text/*`、`application/json`、`xml`、`javascript`、空 content-type） | `focus_text(text, ...)` |
| **其他（二进制）** | **不报错**，返回：`URL: …\nContent-Type: …\nNon-text body (N bytes); not extracted.` |

**关键设计**：第三路返回 `is_error=False`——它是「**抓取成功但内容不可提取**」，不是失败。理由：①请求确实成功了（拿到字节、有状态码）；②报错会让模型以为是网络问题而**重试**（无效重试浪费预算）；③返回**内容类型 + 字节数**是事实，模型据此可判断「要不要换工具（如用 Read 处理 PDF / 用别的路径）」。

另有两条细节：下载与输出分两级（`raw` 被 `_read_capped` 限到 `_MAX_BYTES = 200_000`，正文限到 `_OUT_CAP = 8_000`）；若被截断且正文里没有 "truncated" 字样，追加 `… truncated`（`:211-212`）——**避免模型把截断内容当全文**。

**评分要点**
- **及格**：说出「二进制内容要特殊处理」。
- **良好**：说出应返回**内容类型与大小**而不是空/报错。
- **优秀**：能把「成功 ≠ 可用」讲清——HTTP 成功但内容不可提取时，**报错会诱发无效重试**，所以要用「事实型结果 + 不置错误」区分两者；并指出 `… truncated` 标记的意图（防把截断当全文，与「full output」措辞问题是同族）。

**典型弱答**
- 二进制就 `is_error=True`（诱发重试，且丢失「拿到了什么」的信息）；
- 返回空字符串（模型无法区分「页面为空」与「内容不是文本」）；
- 忽略截断标记（模型以为读全了）。

**追问**
如果模型需要 PDF 内容，你这个工具应该怎么引导？（→ 工具描述里说明；或转交可读 PDF 的工具/vision 路径）

---

### XEYO-QA-0292 【困难】恢复状态时多个来源怎么排序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | todo_write 恢复 | 多来源可信度 | 困难 | 场景设计 | `python/tools/todo_write_tool/restore.py:26-131` |

**面试官提问**
同一份 todo 状态可能有三个载体：内存消息、磁盘转录、会话 sidecar。重启后它们可能不一致。请给出你的恢复优先级与理由，并说明「回滚」之后该信谁。

**参考答案要点**
三个载体与各自特性：

| 载体 | 特性 |
|---|---|
| 内存消息列表 | 会话内最新，但**进程重启即失** |
| 磁盘**转录 JSONL** | **逐条追加**，权威、最完整 |
| 会话 **sidecar**（`working.todos`） | 方便，但**周期性 flush**；flush 失败只记日志不抛（可能落后） |

恢复入口两条：`restore_todos_from_messages(messages)`（内存）与 `restore_todos_from_transcript(session_id)`（磁盘）；每条路径都有两个解析器（**工具入参** vs **工具结果**里的 `[todo_list]` 标签，配 `_TODO_LIST_RE`），因为清单可能出现在这两处。

**优先级建议**：内存 > 转录 > sidecar（会话内最新 → 追加权威 → 周期快照）。**并要说明前提**：三条都靠「取最后一条」的语义（后写胜）。

**★ 回滚之后该信谁**：回滚会截断转录，而 sidecar **是独立文件**（不会被一起截断）——若不显式清理，旧 sidecar 会把**已回滚的状态重新注入**（「已删除内容经缓存复活」）。所以正确做法是：回滚路径**必须显式重置 sidecar**（以及会话笔记一类派生载体），然后以**转录**为权威重建。

**评分要点**
- **及格**：说出「从转录恢复」。
- **良好**：区分三个载体的时效性，并给出优先级。
- **优秀**：主动指出**回滚场景**的不一致（sidecar 不会被一起截断 → 旧状态复活），并给出「回滚时清理派生载体 + 以追加日志为权威」的方案。这说明候选人理解「同一语义多载体」的结构性风险，而不只是会调函数。

**典型弱答**
- 只信 sidecar（它是周期快照，可能落后）；
- 不考虑回滚（认为「谁新信谁」就够）；
- 没有固定的写入格式，导致解析不可靠。

**追问**
如果要在架构上根治「多载体不一致」，你会怎么做？（→ 单一权威 + 派生物可重建 + 回滚时统一失效，例如世代号）

---

### XEYO-QA-0293 【困难】技能目录的注入面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | skill_tool 目录 | 外部内容的上下文注入 | 困难 | 安全拷问 | `python/tools/skill_tool/skill_tool.py:26-33,82-99` |

**面试官提问**
技能正文和描述会被注入模型上下文。这些内容来自哪里、有什么风险？你会怎么控制暴露面？

**参考答案要点**
**内容来源**：技能是**文件系统里的资产**（`SKILL.md` 一类），作者可能是用户、团队、或第三方插件——即**不是引擎自己写的文本**。

**三条暴露面与控制**：

| 面 | 控制 | 常量 |
|---|---|---|
| **常驻目录**（每轮都进上下文） | 每个技能一行、描述截断到 120 字符、总量 2 400 字符 | `CATALOG_LINE_DESC = 120` / `CATALOG_MAX_CHARS = 2_400` |
| **按需列表** | 每行 500 字符、总量 4 000，且**按 query 过滤** | `LIST_LINE_DESC = 500` / `LIST_MAX_CHARS = 4_000` |
| **技能正文** | 12 000 字符上限 | `BODY_MAX = 12_000` |

**风险与对策**：①**注入面**——技能描述是「可能含祈使句的外部文本」，常驻注入等于把它放在注意力里。对策是**一行化 + 严格截断**（描述越短，可承载的指令越少），并与「记忆索引一行化」（只给计数、不给条目文本）同一思路；②**预算**——目录每轮付费，必须严格限量；③**可见性**——被禁用/未授权技能**不进目录**（否则既占预算又误导）。

**评分要点**
- **及格**：说出「技能文件要有长度上限」。
- **良好**：说出三档预算，并意识到「常驻内容截断」本身就是**降低注入面**的手段。
- **优秀**：把「一行化 + 截断」讲成**防注入策略**而不只是省 token；并主动联系「只呈现通过闸的技能」这条（清单里出现不可用技能会误导模型）。

**典型弱答**
- 只从省 token 角度解释截断（漏掉注入面）；
- 让目录列全部技能（含被禁用的）；
- 认为「技能是我们自己的资产所以可信」（它可能来自第三方/用户）。

**追问**
如果目录被截断（总量超限），后面的技能完全不出现。你会怎么让这件事**对用户可见**，而不是表现为「技能时有时无」？

---

### XEYO-QA-0294 【困难】让模型操作前端的安全边界

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | xeyo_ui 面板与 URL | 白名单与字符串入参 | 困难 | 安全拷问 | `python/tools/xeyo_ui_tool/xeyo_ui_tool.py:16-43,309-325` |

**面试官提问**
你有一个工具能让模型**操作前端界面**（切换面板、控制内嵌浏览器）。请说明你怎么防止「模型驱动前端做任意事」，以及哪一类参数最危险。

**参考答案要点**
两个白名单集合（`:16-17`）：

```python
_UI_PANELS  = frozenset({"git","terminal","history","map","commits","browser"})   # 6 个
_BROWSER_OPS = frozenset({"reload","back","fwd","ext","close"})                    # 5 个
```

**三条控制**：

| 控制 | 做法 | 理由 |
|---|---|---|
| **动作白名单** | 面板与浏览器操作都是 `frozenset` | 若允许任意 action 字符串，等于**让模型直接调前端任意 handler**——一条从 LLM 到前端的完整注入面 |
| **带参与无参分离** | `_BROWSER_OPS` 里全是**无参**动作（重载/后退/前进/外开/关闭）；**`open` 不在其中** | 唯一需要字符串入参的动作（打开 URL）单独走校验 |
| **URL 校验** | `_browser_url_ok(url)`（`:309-325`） | 字符串入参是唯一可承载攻击载荷的地方 |

另有两个辅助：`_as_bool(value)`（`:30-43`）返回 `bool | None`——**三态**，用于区分「未提供」与「显式 False」（例如「是否强制刷新」这类标志）；`_peek_title(path)`（`:326-`）读文件标题供 UI 显示。

**★ 最危险的参数是 URL**：它是唯一「任意字符串 → 前端导航」的通道，所以要过白名单/协议校验（与出站请求的 URL 校验同一威胁模型）。

**评分要点**
- **及格**：说出「动作要有白名单」。
- **良好**：说出 URL 是最危险的入参，需要单独校验。
- **优秀**：能讲出「LLM → 前端」这条注入面的完整性（模型 → 工具 action → 前端 handler），并指出「把带参动作与无参动作分开」是有意的防御划分；能解释 `_as_bool` 为什么需要三态。

**典型弱答**
- 允许面板名/action 任传（把白名单当建议）；
- 只校验 URL、不限制 action（action 直接进前端分派）；
- 把 `_as_bool` 写成二值（丢掉「未提供」语义，会误改用户设置）。

**追问**
内嵌浏览器里打开的页面是**外部内容**。它会不会反过来影响模型？（→ 页面内容可能进上下文，形成「外部内容 → 模型」的注入通道）

---

### XEYO-QA-0295 【困难】诊断工具该不该说「检查了什么」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | diagnostics 覆盖面 | 空结果与无问题的区别 | 困难 | 权衡取舍 | `python/tools/diagnostics_tool/diagnostics_tool.py:170-267,405-423` |

**面试官提问**
你的诊断工具在「找不到可用的检查器」或「判定不出语言」时，应该返回什么？如果返回空结果会有什么问题？

**参考答案要点**
**返回空结果会被读成「无问题」**——这是诊断类工具最危险的失败模式。正确做法是**把覆盖面当成结果的一部分**：

```python
def _format_result(lines: list[str], used: list[str], notes: list[str]) -> str:
    # used  = 实际用了哪些检查器（如 ["py_compile", "ruff"]）
    # notes = 说明（如「未找到 tsc，跳过 TS 检查」）
```

三件必须报告的事：①诊断行（`lines`）；②**实际用了什么**（`used`）；③**跳过了什么/为什么**（`notes`）。

四级探测链决定了覆盖面：①显式 `lang`；②目标形态（`_looks_python` / `_looks_typescript`）；③目录浅探测（`_shallow_has`）；④**判定不出 → 不诊断但说明**。工具可用性同样影响覆盖面：`_run_ruff` 需要 `ruff` 存在，`_find_local_tsc` 需要本地 TS。

**★ 对照：两类「空输出」的相反语义**

| 情形 | 空输出的含义 | 正确处理 |
|---|---|---|
| `mkdir`/`cd` 这类**静默命令**成功 | **成功**（Unix 惯例） | 视为成功（`SILENT_COMMANDS`） |
| 诊断工具**没能检查** | **未知** | **必须说明**，不能为空 |

**评分要点**
- **及格**：说出「判定不出就别乱报」。
- **良好**：说出要报告「用了哪些检查器」。
- **优秀**：能把「空输出 = 成功」与「空输出 = 未知」两类语义分开，并指出**诊断类工具的正确默认是「如实报告覆盖面」**；进一步能与「破坏性守卫降级完全静默」对比，指出后者是**反例**（降级没有任何痕迹）。

**典型弱答**
- 判定不出就返回空（被读成「干净」）；
- 只报诊断行不报工具可用性；
- 用「无输出」统一表示成功与跳过。

**追问**
如果要求「任何降级都要留痕」，你会怎么改造「保护类机制静默降级」的那处设计？（→ 审计事件 + 原因码）

---

### XEYO-QA-0296 【困难】声明「并发安全」的代价由谁承担

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | agent_tool 并发 | 声明与下层收敛 | 困难 | 权衡取舍 | `python/tools/agent_tool/agent_tool.py:34-35,100-107` |

**面试官提问**
`Agent` 工具既**有副作用**（子 agent 会写文件）又声明 `is_concurrency_safe() = True`。这合理吗？如果合理，正确性由谁保证？

**参考答案要点**
**合理，正确性由下层收敛机制承担**（代码注释直接说明了，`:105-107`）：

```python
    @staticmethod
    def is_concurrency_safe() -> bool:
        # 同轮可并行多个 Agent；磁盘冲突由 WriteStore content-hash 收敛。
        return True
```

即「并发安全」在这里的含义不是「无副作用」，而是「**副作用冲突可被下层幂等/冲突检测处理**」：

| 层 | 机制 |
|---|---|
| 编排层 | `partition_tool_calls` 把 `Agent` 放进并行组 |
| **工具层** | `threading.Semaphore(_MAX_CONCURRENT)`（默认 8）限制同时在飞的子 agent 数 |
| **写路径** | 各子 agent 的写经 `WriteStore`：**base hash 校验**（内容变则拒绝）+ 分片锁 + 租约 |

**两个必须指出的边界**：①`Semaphore` 是**模块级单例**，所以「同会话并发上限」在实现上是**进程级**上限（多个会话共享这 8 个槽位）；②`is_concurrency_safe` 是**工具级声明**，而 `WriteStore` 的收敛是**会话/工作区级机制**——两者作用域不同，声明方（工具）其实**不掌握**收敛机制是否已装配（若某个入口没注入 `write_store`，写冲突就没人管）。

**评分要点**
- **及格**：说出「有写但可以并行，因为下层有冲突检测」。
- **良好**：能指出具体机制（`WriteStore` 的 base hash / 锁），而不是笼统说「有锁」。
- **优秀**：指出**作用域差异**（工具级声明 vs 会话级收敛）与**装配依赖**（没注入 store 时声明就变得过于乐观）；并能指出 `Semaphore` 的进程级作用域与「同会话」措辞的差异。

**典型弱答**
- 认为「有副作用就不能并发安全」（忽略了「冲突可收敛」这条路）；
- 说「反正有锁」但说不出锁在哪一层；
- 没意识到声明比收敛机制的作用域宽。

**追问**
如果要让「并发安全」这个声明**不依赖调用方装配正确**，你会怎么设计？

---

### XEYO-QA-0297 【困难】记忆候选提示该不该给模型看

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | memory_tool 候选 | 候选机制与暴露面 | 困难 | 权衡取舍 | `python/tools/memory_tool/memory_tool.py:72-95` |

**面试官提问**
记忆系统里有一批「待确认候选」（还没过晋升闸的推断）。这些候选计数应该：主动推给模型、只在 GUI 显示、还是都不给？请说明理由。

**参考答案要点**
实现里有 `_proposals_notice_line(cwd)`（`:72-95`）生成「候选提示行」，以及 `_format_peer_row(entry)`（`:96-122`）、`_peer_topic(session_id, limit=_PEER_TOPIC_LIMIT)`（`:41-71`，默认 **72** 字符）用于 peers 输出。

**候选的背景**：候选是**未过闸的推断**（`MemoryCandidate` + `candidates.jsonl`），它们**不是已确认事实**。项目对记忆注入的整体取向是「**少注入**」：

| 取向 | 证据 |
|---|---|
| 索引块一行化（只给计数，不给条目标题） | 防弱模型把条目当任务对象（有实测事故） |
| 常驻记忆索引**已下线**（恒关） | 用户裁决维持下线 |
| 检索走显式 `Memory(action=search)` | 按需，不常驻 |

**因此候选计数这类内容的正确位置是**：GUI/面板（给人看，促使用户确认），而**不是每轮推给模型**——原因有三：①候选是未确认内容，进模型上下文可能被当成事实；②计数是**频变内容**，放在前缀区会破坏 KV 前缀；③「该不该晋升」是**人的决策**（晋升闸的证据类型基本都指向用户/客观事实），推给模型没有可执行动作。

**评分要点**
- **及格**：说出「候选是未确认的，不该当事实用」。
- **良好**：说出应放在 GUI 而不是模型上下文。
- **优秀**：给出**三条理由**（未确认 / 频变破坏前缀 / 决策权在人），并能联系项目里「索引一行化」「常驻索引下线」这两个既有取向说明这是一条**一致的原则**（能不进上下文就不进）。

**典型弱答**
- 认为「给模型更多信息总是更好」（忽略未确认内容被当事实的风险）；
- 把候选计数当作工具结果的一部分每轮返回（频变 + 污染注意力）；
- 让模型自己决定晋升（晋升闸的证据类型不指向模型自评）。

**追问**
如果用户希望模型**主动提醒**「有 3 条候选待确认」，你会怎么实现，才既不污染注意力也不遗漏？（→ 交互层提示 / 会话开始的一次性事实，而不是每轮注入）

---

### XEYO-QA-0298 【困难】并发执行里超时与进度怎么设计

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | orchestration 时限 | 放弃等待 vs 终止 | 困难 | 系统设计 | `python/tools/orchestration.py:31-72,110` |

**面试官提问**
并行执行多个工具调用时，请设计超时与进度机制，并回答一个关键问题：**编排层超时了，底层进程会停下来吗？**

**参考答案要点**
三个参数（`:31-72`）：`_max_concurrency()`（并发度）、`_tool_timeout_s()`（**工具级超时，`float | None`**）、`_progress_interval_s()`（进度节流间隔）；`_emit_result`（`:110-`）负责发射结果。

**关键问题：不会。** 编排层超时的语义是「**放弃等待该调用**」（结果标记为超时/失败），而**底层命令可能仍在跑**——这与「终止」是两件事：

```
编排层超时  → 停止等待、回收控制权（回合可继续）
底层超时    → 真的杀掉进程（bash_tool 的 DEFAULT_TIMEOUT_MS / 命令族映射）
```

所以一次「超时」后可能出现：模型以为这个调用结束了，而**磁盘上还有进程在写**（这正是「孤儿写工作区」那类故障的土壤）。

**两道超时的正确关系**：编排层超时应**大于**工具内超时（否则编排层先放弃、底层还在跑，等于把「等待」变成了「不管」）；同时也需要**强杀能力**兜底（`job_kill`/进程树终止），否则放弃等待就只是「视而不见」。

**进度设计**：节流（`_progress_interval_s`）——不节流会刷爆事件通道；进度只发**用户可见通道**，不进模型上下文（频变内容会破坏前缀）。

**评分要点**
- **及格**：说出「有限流、有超时、有进度」。
- **良好**：说出超时是「放弃等待」，并意识到底层可能仍在运行。
- **优秀**：能给出**两道超时的量级关系**（编排 > 工具内），并指出「放弃等待」必须配**强杀能力**才完整；能把「孤儿进程写工作区」的后果说出来。

**典型弱答**
- 认为超时等于已终止；
- 编排层超时设得比工具内超时更短（导致总是「不管就跑」）；
- 只做超时不做强杀。

**追问**
如果工具内部实现了「自动晋升为后台任务」（长命令不再阻塞回合），编排层的超时该怎么配合？（→ 晋升后应立即返回 job id，编排层不该继续等）

---

### XEYO-QA-0299 【超压·安全拷问】抓取缓存的键要不要带焦点问题

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web_fetch 缓存 | 缓存键完整性与污染 | 超压 | 安全拷问 | `python/tools/web_fetch_tool/web_fetch_tool.py:22-58,111-114` |

**面试官提问**
抓取工具有 15 分钟缓存。同一个 URL，模型第一次问「安装步骤」，第二次问「许可证」。如果缓存键只含 URL，会发生什么？请给出你的键设计，并说明缓存**写入时机**上还有什么坑。

**参考答案要点**
**键必须覆盖所有影响输出的输入**（`:111`）：

```python
		cache_key = f"{_normalize_url(url)}\n{prompt}"
```

`_normalize_url`（`:33-38`）：scheme/netloc 转小写、path 为空填 `/`、**去掉 fragment 并保留 query**。

| 进键 | 出键 |
|---|---|
| URL（scheme/netloc/path/**query**） | **fragment**（`#` 之后，不影响服务端响应） |
| **`prompt`（焦点问题）** | — |

**只含 URL 的后果**：`prompt` 决定 `focus_text` 挑哪些段落（0270），所以第二次问「许可证」会**命中第一次「安装步骤」的缓存**——返回**与本次提问无关的正文**，而且因为 `is_error=False`，模型**完全无从察觉**这是错的（这是「静默的错误答案」，比报错危险得多）。

**写入时机上的两个坑**（`:205` 与 `:219` 两处 `_cache_put`，都在返回 `is_error=False` 的成功路径上）：

| 坑 | 说明 |
|---|---|
| 错误不缓存 | 拒绝（URL blocked）/ 超时 / `too many redirects` 都在 `return ToolResult(is_error=True)` 路径上**不经 `_cache_put`**——正确（不缓存失败） |
| **非文本体也缓存** | 二进制体走 `:205` 也写入缓存——同样带 `prompt` 进键，所以不会串味，但意味着「换个 prompt 问同一张图片」会**重新下载**（键不同 → 未命中） |

**评分要点**
- **及格**：说出「键要带 prompt」。
- **良好**：能解释为什么（`prompt` 改变输出内容），并指出「只带 URL 会返回不相关正文且无错误提示」。
- **优秀**：能指出**fragment 被有意排除**（`#sec1` 与 `#sec2` 命中同一缓存）以及这背后的隐含假设（fragment 不影响服务端响应、当前不支持页内锚点定位）；并检查写入时机（**只缓存成功结果**）。

**典型弱答**
- 键只含 URL（静默错误答案）；
- 把 fragment 也算进键（平白降低命中率）——或反过来从没想过 fragment；
- 把失败结果也缓存（一次网络抖动污染 15 分钟）。

**追问**
缓存的 LRU 淘汰与 TTL 过期，哪个先发生？如果某条内容正在被两个并发请求使用，你的 `OrderedDict` 有锁吗？这在并发场景下意味着什么？

---

### XEYO-QA-0300 【超压·安全拷问】Web 工具族的绕过面总账

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 工具系统 | web 三件套 | 完整威胁模型 | 超压 | 安全拷问 | `web_common.py` + `web_fetch_tool.py` + `web_search_tool.py` + `web_search_tool/config.py` |

**面试官提问**
这是一个「模型可以上网」的子系统：抓取（WebFetch）、搜索（WebSearch）、以及用户可配的搜索后端（SearXNG）。请**系统性列出**你看到的绕过面，按「能不能真的打进去」排优先级，并给出纵深防御方案。

**参考答案要点**
先摆事实（已实现的防护）：

| 防护点 | 实现 |
|---|---|
| 协议白名单 | 只 `http`/`https`（`web_common.py:29-30`） |
| 主机名清单 | `localhost` / `localhost.` / `metadata.google.internal` + `.localhost`（`:10-16,34-35`） |
| 字面 IP 判定 | private/loopback/link-local/reserved/multicast/unspecified + `169.254.169.254`（`:38-50`） |
| 域名解析后判定 | 逐结果检查，**DNS 失败即拒绝**（`:52-72`） |
| 逐跳重定向校验 + 禁自动跟随 + 次数上限 | `web_fetch_tool.py:126-173` |
| 下载/输出双上限 | `_MAX_BYTES = 200_000` / `_OUT_CAP = 8_000`（`:16-23`） |
| 配置项也过校验 | `is_searxng_base_allowed` 返回「拒绝原因或 None」（`config.py:47-55`） |

**绕过面清单（按可利用性排序）**：

| # | 绕过面 | 机制 | 现有防护是否覆盖 |
|---|---|---|---|
| 1 | **DNS rebinding（TOCTOU）** | 检查时解析公网、请求时解析内网（两次独立解析） | ❌ **未覆盖**（0287） |
| 2 | **每跳重定向的同一缺口** | 逐跳校验与每跳请求之间同样是两次解析 | ❌ 未覆盖 |
| 3 | 编码/IP 表示变体 | 十进制整数 IP、八进制、IPv6 映射等写法 | ⚠️ 取决于 `ipaddress` 与 `urlparse` 的规范化是否一致（需实测） |
| 4 | **企业内网域名** | `internal` / 自建内网域 | ❌ 清单只三条，不含内网后缀 |
| 5 | 搜索后端的 HTML 解析 | 正则抓取被搜索结果页「内容注入」影响 | ⚠️ 抓到的是搜索结果文本，会进模型（**内容层注入**） |
| 6 | 配置项 | 用户填 SearXNG base URL | ✅ 已有 `is_searxng_base_allowed` 校验 |

**纵深防御方案（分四层）**：

```
① 应用层：消 TOCTOU（解析一次 → 用 IP 连接 + Host 头），重定向逐跳（已有）
② 客户端层：连接后校验 peername、禁止自动重定向、上限（已有）
③ 网络层：出站代理/防火墙禁私网段与元数据地址（最可靠，部署依赖）
④ 内容层：抓回内容是「外部文本」，进上下文时按引用数据对待（围栏），不当作指令
```

**★ 必须点出的两个结构性认识**：①**应用层永远无法单独保证出站安全**——只要依赖 DNS，就有时间窗；②**威胁模型不止「打内网」**——抓回的网页内容是**不受控文本**，它本身就是一条「外部 → 模型」的注入通道（这条最容易被忽略，因为大家只盯着 SSRF）。

**评分要点**
- **及格**：说出「私网 IP + 元数据地址要被拦」。
- **良好**：说出重定向是主要绕过通道，且防护是逐跳的。
- **优秀**：**主动提出 TOCTOU/DNS rebinding**（这是本题的分水岭），给出可落地的修法；进一步提出**网络层兜底**与**内容层注入**这两层（说明候选人有完整威胁模型，而不是只查了一遍 URL）。

**典型弱答**
- 认为「有 URL 黑名单就安全了」；
- 只想到 SSRF，完全忽略「抓回的网页内容是注入源」；
- 把 DNS 解析失败当成「放行更友好」；
- 提出「用正则更严格地匹配内网 IP」（解决不了时间窗）。

**追问**
如果部署在客户内网（有真实内网服务），你会怎么调整策略？如果部署在云上（有元数据服务），优先级又怎么变？（→ 风险取决于环境：云上元数据优先，内网环境私网段优先）

---

## 批次自检表（B06）

| 项 | 结果 |
|---|---|
| 题号连续性 | XEYO-QA-0251 – XEYO-QA-0300，**无跳号无重号**（脚本比对 251..300 无缺口） |
| 难度配比实测 | 简单 **16**（0251–0266）/ 中等 **20**（0267–0286）/ 困难 **12**（0287–0298）/ 超压 **2**（0299–0300）= **50** ✅ 与矩阵 B06 一致 |
| 问法分布 | 概念确认 9 / 机制解释 26 / 场景设计 10 / 代码阅读 3 / 安全拷问 1 / 故障排查 1 = **50**（总览表口径；`权衡取舍`/`对比辨析`/`系统设计` 三种标签本批未使用——它们预留给后续批次的深挖题，本批的深挖由「困难/超压 + 追问」承担） |
| 覆盖子模块 | `base_tool` 工具契约 · `agent_tool`（深度/并发/scope/入参/id/结果正文/并发声明）· `skill_tool`（目录预算/可见性/两级输出）· `todo_write_tool`（字段/校验/合并/恢复/store）· `memory_tool`（六 action/peers/候选提示）· `web_common`（SSRF 判定/清洗/焦点提取）· `web_fetch_tool`（预算/缓存/重定向/内容类型）· `web_search_tool` + `config`（多后端/SearXNG 白名单）· `notebook_edit_tool` · `git_tool` · `diagnostics_tool` · `journal_query_tool` · `ask_user_question_tool` · `screenshot_tool` · `xeyo_ui_tool` · `orchestration` · `progress_sink`——共 **18 个文件** |
| 事实基线核对 | 全部 50 题来源指向本批实际打开读过的文件；`agent_tool.py`(522) / `memory_tool.py`(549) / `web_search_tool.py`(543) / `diagnostics_tool.py`(423) 采用「先 Grep 抽定义行号 → 再按 offset/limit 精读」；`web_common.py`(215) 与 `web_fetch_tool.py`(248) **全文精读**。写题前复核锚点：`web_common.py:10-114,117-215`、`web_fetch_tool.py:16-23,33-58,111,121-173,182-220,230-248`、`agent_tool.py:32-35,38-57,68-80,100-107,122-173`、`todo_write_tool/types.py:7-8,11-29,32-56`、`skill_tool.py:26-33,82-121,138-172,280-285`、`memory_tool.py:36,38-122`、`web_search_tool.py:23-46,325-361`、`web_search_tool/config.py:14-55` |
| 格式改造 | `0251–0266` 由「知识题格式」**原地改造**为面试题格式（结构字段替换 + 模板化「评分要点/典型弱答/追问」），技术内核（机制解析、代码片段、行号证据）全部保留；`0267–0300` 直接按面试题格式撰写。**改造脚本已删除**（不留临时文件） |
| 重复性检查 | ① 与 B04/B05 的分界已守：文件五件套与 Bash 家族不出题；`job_tools`/Bash registry 桥在 B05 已覆盖，本批不重复；② 批内 `0267`（判定链）与 `0287`（TOCTOU）是「机制 vs 时间窗」两层，答案不重复；`0268`（逐跳校验）与 `0288`（手动跟随的实现代价）分别考「为什么」与「代价是什么」；③ `0274`（合并）与 `0275`（恢复）分别是「写时」与「读时」，不重复；④ `0290`（引擎指令文本）与 `0295`（覆盖面报告）都涉及「如实呈现」，但前者考「不该写指令」、后者考「必须报覆盖面」，方向相反 |
| 待确认条目 | **5 处**：① `agent_tool._MAX_CONCURRENT` 的 `int(env)` 无 `try/except`——非法值会在**模块导入时**抛 `ValueError`（是否有上层保护待查）；② `git_tool._WRITE_ACTIONS` 的成员未逐项读取，且与 `meta.py` 描述「Read-only git … No commit」**存在张力**（写动作是否可达待确认）；③ `journal_query._filter_rows_for_session` 的 `limit` 默认值未读到（参考 B09 的 `recent_changes` 默认 20）；④ `screenshot._wechat_copy_path` 是「真拷贝」还是「只派生路径」未逐行读到；⑤ `progress_sink.py` 内部实现（回调/事件总线/并发锁/失败取向）未逐行读取 |
| 边界遵守 | 未涉及 B04/B05（文件与 Bash 家族）、未涉及 B07（权限三态裁决本体，本批只提「工具如何声明只读/并发安全」）、未涉及 B09/B10（记忆内部机制，本批只讲 `Memory` 工具入口层）、未涉及 B12（extension 的加载器与开关来源）、未涉及 B14（`/v1/ask/resolve` 等路由） |
| 未覆盖但已计划 | `skill_tool._apply_args`（模板参数替换）与 `skill_tool` 的目录发现顺序、`todo_write_tool/store.py`（30 行）与 `todo_write_tool.py:107-370` 的执行细节、`diagnostics_tool` 的 `_run_ruff`/`_run_tsc` 逐行逻辑、`web_search_tool` 的四组解析正则逐个行为、`xeyo_ui_tool` 的 `_ACTIONS` 成员与 `_browser_url_ok` 具体规则、`orchestration._emit_result` 的发射细节 → 如需可作补批 |
