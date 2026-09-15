# XEYO QA 题库 · 第 5 批（B05）

> 题号范围：**XEYO-QA-0201 – XEYO-QA-0250**
> 主题：Bash 工具族（命令语义归一化 · 破坏性命令快照守卫 · 只读白名单与写判定 · 超时分级映射 · 输出截断与错误抢救 · 命令压缩 · 预检查三道闸 · 后台作业与 registry 桥 · Windows Job Object · PowerShell 7 探测与安装 · 容器路由 · 执行器取消语义）
> 难度配比：简单 14 / 中等 18 / 困难 13 / 超压 5
> 事实基线（本批实际打开读过的文件与实测行数）：
> `bash_tool/bash_tool.py`(1059, 前 240 行 + 495–624 精读 + 定义面全量) · `runner.py`(426, 定义面全量 + 46–115 精读) · `destructive_guard.py`(374, 50–179 精读 + 定义面全量) · `semantics.py`(100, 全文) · `precheck.py`(122, 定义面全量) · `dup_redirect.py`(252, 定义面全量) · `timeout_map.py`(127, 全文) · `truncate.py`(96, 全文) · `background.py`(225, 定义面全量) · `win_job.py`(190, 定义面全量) · `pwsh7.py`(174, 定义面全量) · `jobs_bridge.py`(89, 定义面全量) · `cmd_compact.py`(370, 定义面全量) · `prompt.py`(23, 全文)
> **边界声明**：`permissions/policy.py::bash_writes_file`、`permissions/bash_policy.py`（Bash 规则引擎与三态裁决本体）归 **B07**——本批只讲「Bash 工具如何调用它们、如何在分类器不可用时 fail-closed」；`engine/wrap_window.py` 的收尾窗机制归 **B03**（本批只讲 `effective_promote_ms` 如何消费它）；`server/job_registry.py` 与 `/v1/jobs` 路由归 **B14**（本批只讲 `jobs_bridge` 的桥接契约）；`tools/job_tools.py` 的 `JobList`/`JobKill` 工具面归 **B06**；容器镜像与 `precheck` 的评测适配动机属评测体系，归 **B20**。
> **行号口径**：`bash_tool.py`(1059) 与 `runner.py`(426) 采用「先 Grep 抽定义行号 → 再按 offset/limit 精读」；写题前复核的锚点见自检表。
> **缺陷基线复核（本批重要发现）**：`docs/全项目BUG排查-20260910.md` 的 **`TOOL-03`「Bash docker 分支 `is_error` 恒 False 且丢退出码」（文档锚点 `bash_tool.py:569-573`）在本批实测中已不成立**——当前 `:569-573` 的 docker 分支是 `out_code, out_text = _docker_exec_with_timeout(...)` 后 `return BashOutput(code=out_code, stdout=out_text)`，**退出码被完整保留**。判定为**文档过期（该缺陷已修复）**，详见 0248 与自检表。

---

## 本批题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0201 | 简单 | 概念确认 | Bash 的四个尺寸/超时常量 | `bash_tool.py:124-127` |
| 0202 | 简单 | 概念确认 | 超时夹取区间 | `bash_tool.py:346` |
| 0203 | 简单 | 概念确认 | 静默命令集 | `bash_tool.py:180-192` |
| 0204 | 简单 | 机制解释 | `_segment_base` 的三步归一化 | `bash_tool.py:82-88` |
| 0205 | 简单 | 概念确认 | git 只读子命令白名单 | `bash_tool.py:75-79` |
| 0206 | 简单 | 概念确认 | 破坏性快照的两个默认上限 | `destructive_guard.py:73-74` |
| 0207 | 简单 | 概念确认 | 破坏性程序清单 | `destructive_guard.py:54-58` |
| 0208 | 简单 | 概念确认 | 快照守卫的默认开关 | `destructive_guard.py:52,103-105` |
| 0209 | 简单 | 机制解释 | 命令族超时的四个代表值 | `timeout_map.py:24-64` |
| 0210 | 简单 | 概念确认 | 输出截断的 head/tail 常量 | `truncate.py:7-9` |
| 0211 | 简单 | 概念确认 | PowerShell 7 的钉版版本号 | `pwsh7.py:26-29` |
| 0212 | 简单 | 机制解释 | Windows Job 的默认内存上限 | `win_job.py:22,94-105` |
| 0213 | 简单 | 机制解释 | 后台日志的 TTL | `background.py:209` |
| 0214 | 简单 | 概念确认 | 压缩器的最小生效长度 | `cmd_compact.py:13-15` |
| 0215 | 中等 | 机制解释 | 只读白名单的 fail-closed 判定 | `bash_tool.py:57-112` |
| 0216 | 中等 | 机制解释 | 晋升阈值与收尾窗路由 | `bash_tool.py:128-175` |
| 0217 | 中等 | 机制解释 | 目标 token 提取规则 | `destructive_guard.py:147-182` |
| 0218 | 中等 | 机制解释 | 快照前后尺寸闸 | `destructive_guard.py:184-226` |
| 0219 | 中等 | 机制解释 | `_kill_process` 的平台分叉 | `runner.py:62-88` |
| 0220 | 中等 | 机制解释 | shell 选择与 UTF-8 环境 | `runner.py:30-45,116-150` |
| 0221 | 中等 | 机制解释 | 输出的三级编码回退 | `runner.py:91-105` |
| 0222 | 中等 | 机制解释 | 流式句柄与收尾 | `runner.py:183-200,333-407` |
| 0223 | 中等 | 机制解释 | 预检查的三道闸 | `precheck.py:25-112` |
| 0224 | 中等 | 机制解释 | 重定向/命令替换的拦截 | `dup_redirect.py:38-58,218-252` |
| 0225 | 中等 | 机制解释 | 错误行抢救的契约 | `truncate.py:11-58` |
| 0226 | 中等 | 机制解释 | registry 桥的降级链 | `bash_tool.py:588-622` + `jobs_bridge.py:14-53` |
| 0227 | 中等 | 机制解释 | 命令压缩的四家族 | `cmd_compact.py:45-85` |
| 0228 | 中等 | 机制解释 | 语义层的结果解读 | `semantics.py:10-56` |
| 0229 | 中等 | 机制解释 | 净室执行的合成命令 | `bash_tool.py:541-559` |
| 0230 | 中等 | 机制解释 | 容器路由的并发防串线 | `bash_tool.py:561-573` |
| 0231 | 中等 | 机制解释 | 后台日志的接管与清理 | `background.py:130-225` |
| 0232 | 中等 | 机制解释 | pwsh7 的完整性校验 | `pwsh7.py:38-105` |
| 0233 | 困难 | 场景设计 | 白名单片段解析的绕过面 | `bash_tool.py:91-112` |
| 0234 | 困难 | 场景设计 | 破坏性守卫的黑名单边界 | `destructive_guard.py:54-71` |
| 0235 | 困难 | 场景设计 | 快照结算的两条结局 | `destructive_guard.py:346-366` |
| 0236 | 困难 | 代码阅读 | `_decode` 的三级回退代价 | `runner.py:91-105` |
| 0237 | 困难 | 场景设计 | 超时分级与 worker 护栏的互斥 | `timeout_map.py:1-15` + `bash_tool.py:176-178` |
| 0238 | 困难 | 场景设计 | 压缩与错误保真的张力 | `cmd_compact.py:13-15,86-171` |
| 0239 | 困难 | 场景设计 | 预检 fail-open 与执行层 fail-closed 的分工 | `bash_tool.py:575-586` + `precheck.py:113` |
| 0240 | 困难 | 场景设计 | Job Object 双保险为何不互相取代 | `runner.py:62-88` + `win_job.py:26-93` |
| 0241 | 困难 | 代码阅读 | `effective_promote_ms` 的四条早退 | `bash_tool.py:149-175` |
| 0242 | 困难 | 场景设计 | 截断落盘与 spill/预算的三层关系 | `truncate.py:61-96` + `tool_registry.py:204-234` |
| 0243 | 困难 | 场景设计 | 后台晋升的进程不重启保证 | `bash_tool.py:128-130` |
| 0244 | 困难 | 场景设计 | 命令压缩的家族识别边界 | `cmd_compact.py:45-54` |
| 0245 | 困难 | 场景设计 | `_load_overrides` 的缓存与坏值 | `timeout_map.py:72-93` |
| 0246 | 超压 | 故障排查 | POSIX 超时只杀 shell 不杀子进程树 | `runner.py:81-82` |
| 0247 | 超压 | 安全拷问 | 只读白名单被判「只读」的越界面 | `bash_tool.py:64-112` |
| 0248 | 超压 | 故障排查 | docker 分支的「失败报成功」是否仍成立 | `bash_tool.py:561-573` |
| 0249 | 超压 | 场景设计 | 破坏性守卫的「不知情」降级面 | `destructive_guard.py:213-226,346-366` |
| 0250 | 超压 | 场景设计 | 三层输出治理的顺序与证据链 | `truncate.py` + `cmd_compact.py` + `tool_registry.py` |

---

### XEYO-QA-0201 Bash 的尺寸与超时常量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 主常量 | 四个上限 | 简单 | 概念确认 | `python/tools/bash_tool/bash_tool.py:124-127` |

**面试官提问**
`bash_tool.py` 顶部定义的默认超时、最大超时、结果字符上限、命令字符上限分别是多少？

**参考答案要点**
**正解：B（**120_000 / 600_000 / 30_000 / 100_000**）**
`bash_tool.py:124-127`（原文）：

```python
DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 600_000
MAX_RESULT_CHARS = 30_000
MAX_COMMAND_CHARS = 100_000
```

| 常量 | 值 | 用途 |
|---|---|---|
| `DEFAULT_TIMEOUT_MS` | `120_000`（2 分钟） | 模型未传 `timeout` 时的默认；**可被命令族映射覆盖**（见 0209） |
| `MAX_TIMEOUT_MS` | `600_000`（10 分钟） | 夹取上界 |
| `MAX_RESULT_CHARS` | `30_000` | 工具结果的字符预算 |
| `MAX_COMMAND_CHARS` | `100_000` | 单条命令本身的长度上限 |

★ 三个容易混淆的「30k / 45s / 120s」要分清：

- **`MAX_RESULT_CHARS = 30_000`** 与 `truncate.DEFAULT_LIMIT = 30_000`（`truncate.py:7`）**同值但不同常量**——前者是 `max_result_size_chars`（工具类属性，见 `:496`），后者是截断函数的默认 `limit`。两者一致是有意的，但改一处不会自动改另一处；
- **`BASH_PROMOTE_DEFAULT_MS = 45_000`**（`:130`）不是超时，而是「前台命令跑多久后**自动晋升为后台 job**」的阈值（见 0216/0243）；
- **`DEFAULT_TIMEOUT_MS = 120_000`** 是「多久后**杀掉**命令」。

**深化讲解**（面试官参考，不要求候选人全说）
四个常量分属两个不同的治理面：

| 面 | 常量 | 违反了会怎样 |
|---|---|---|
| 时间 | `DEFAULT_TIMEOUT_MS` / `MAX_TIMEOUT_MS` | 命令在 120s 被掐断（长安装/编译常见痛点，正是 `timeout_map` 要修的） |
| 体积 | `MAX_RESULT_CHARS` / `MAX_COMMAND_CHARS` | 结果刷屏 / 命令本身超长被拒 |

`bash_tool/prompt.py:17` 把时间面写进了工具描述：「command required; timeout ms (default 120000, max 600000)」——**模型可见的这两个数字必须与代码常量一致**，否则模型按描述传值会与 clamp 结果不符。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「60_000 / 600_000 / 30_000 / 100_000」——说明没抓住本题的分界（A）。
- 答成「120_000 / 300_000 / 16_000 / 50_000」——说明没抓住本题的分界（C）。
- 答成「45_000 / 120_000 / 30_000 / 10_000」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0202 超时夹取

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 超时夹取 | `clamp_timeout_ms` | 简单 | 概念确认 | `python/tools/bash_tool/bash_tool.py:346-369` |

**面试官提问**
`clamp_timeout_ms(timeout)` 对输入做了什么？传 `0` 或负值会得到什么？

**参考答案要点**
**正解：B（非正数或缺失 → 默认 120_000；正数 → 夹到 `[?, 600_000]`）**
`bash_tool.py:346-369`（原文）：

```python
def clamp_timeout_ms(timeout: int | None) -> int:
```

具体行为（读取定义面）：**非正数 / `None` → `DEFAULT_TIMEOUT_MS`（120_000）**；正数 → 夹到 `MAX_TIMEOUT_MS = 600_000` 以内。

三个要点：

1. **`0` 不等于「不超时」**：它落到默认值 120s。这是「无超时」这个语义**在本工具里不存在**——命令永远有上界；
2. **负值也被归一到默认值**（不是夹到 0），所以畸形输入不会产生「立即超时」的行为；
3. **上界是硬顶**：传 `10_000_000` 会得到 600_000。

★ 与命令族映射的**顺序关系**（见 0216 与 0237）：`call` 里的流程是

```python
		timeout_ms = clamp_timeout_ms(inp.timeout_ms)
```

即 **先由 `parse_input` 决定基础值（可能来自命令族映射），再夹取**。所以「命令族映射给出的 420_000（cargo）」也会被 `MAX_TIMEOUT_MS` 夹到 600_000 以内——映射表里最大的是 `cargo: 420_000`，在界内。

**深化讲解**（面试官参考，不要求候选人全说）
「无超时」这个语义被**刻意排除**：对一个会执行任意命令的工具来说，允许「无限等待」等于把控制权交给命令——而引擎的整个交互模型建立在「回合能结束」之上（B02/B03 的 budget/abort 体系都依赖这一点）。所以这里的选择是「永远有上界，默认 2 分钟，最大 10 分钟」。

**边界**：`timeout_ms` 在 `BashInput` 里是 `int | None`（`:370-382` 的定义面），而 `parse_input`（`:401-448`）负责把它从原始 dict 里解析出来（含字符串数字等宽容形态）——所以「模型传字符串 `"60000"`」这类情形在 `parse_input` 就被归一化，`clamp_timeout_ms` 拿到的是 int 或 None。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「只做上界夹取，负值原样透传」——说明没抓住本题的分界（A）。
- 答成「强制为 `120_000`，忽略任何输入」——说明没抓住本题的分界（C）。
- 答成「传 `0` 表示「不超时」（无限等待）」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0203 静默命令集

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 期待输出判定 | `SILENT_COMMANDS` | 简单 | 概念确认 | `python/tools/bash_tool/bash_tool.py:180-192` |

**面试官提问**
`expect_no_output(command)` 依据什么判断「这条命令不该有输出」？请给出这个静默集的完整成员，并说明它为什么存在。

**参考答案要点**
**正解：B（`mv` / `cp` / `rm` / `mkdir` / `rmdir` / `chmod` / `chown` / `touch` / `ln` / `cd` / `export` / `unset` / `wait`）**
`bash_tool.py:180-183`（原文）：

```python
SILENT_COMMANDS = frozenset({
	"mv", "cp", "rm", "mkdir", "rmdir", "chmod", "chown",
	"touch", "ln", "cd", "export", "unset", "wait",
})
```

判定函数（`:190-192`）：

```python
def expect_no_output(command: str) -> bool:
	base = extract_base_command(command)
	return base in SILENT_COMMANDS
```

注意它依赖 `semantics.extract_base_command`（`semantics.py:15` 定义面）取出**基础命令名**，而不是直接比较整条命令——所以 `rm -rf dir`、`cp a b` 都能命中。

**深化讲解**（面试官参考，不要求候选人全说）
这个集合的用途是「**期望无输出**」这一判断，即区分两类正常结果：

| 情形 | 语义 |
|---|---|
| 命令有输出 | 输出即证据 |
| 命令**本应无输出**（如 `mkdir`、`cd`、`export`） | **空输出是成功**，不是「没跑到」 |

如果工具把「空输出」一律当成异常/无信息，模型就会对 `mkdir` 成功这类事实产生误判。所以这本质上是**结果语义归一化**：把「Unix 静默即成功」的惯例显式编码。

★ 注意 `echo` **不在**集合里——虽然它常被用来做「静默占位」，但 `echo` 的语义就是输出，所以它属于「有输出」类。同理 `printf` 不在集合里。

**边界**：集合的匹配是**精确的基础命令名**，所以：

- `mkdir` 命中，`mkdir.exe` 是否命中取决于 `extract_base_command` 是否去 `.exe`（`_segment_base` 会去，但 `extract_base_command` 是另一个函数，见 0204 的对照）；
- `Remove-Item`（PowerShell 的 `rm` 别名）**不在**集合里——它属于 `destructive_guard.DESTRUCTIVE_PROGRAMS`（见 0207）而不是静默集。也就是说「静默集」是 POSIX 取向的集合，PowerShell 原生别名未覆盖。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`ls` / `cat` / `echo`」——说明没抓住本题的分界（A）。
- 答成「`pytest` / `npm` / `git`」——说明没抓住本题的分界（C）。
- 答成「`rm` / `del` / `find` / `grep`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0204 基础命令的三步归一化

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 命令归一化 | `_segment_base` | 简单 | 机制解释 | `python/tools/bash_tool/bash_tool.py:82-88` |

**面试官提问**
`_segment_base(seg)` 对一个命令片段做了哪三步归一化？它为什么需要「取第一个词」而不是整段？

**参考答案要点**
`bash_tool.py:82-88`（原文）：

```python
def _segment_base(seg: str) -> str:
	token = seg.strip().split()[0] if seg.strip() else ""
	if "/" in token or "\\" in token:
		token = token.replace("\\", "/").rsplit("/", 1)[-1]
	if token.lower().endswith(".exe"):
		token = token[:-4]
	return token.lower()
```

**三步**：

| 步 | 动作 | 例 |
|---|---|---|
| 1 | **取第一个空白分隔的词**（空片段→空串） | `"rm -rf build"` → `"rm"` |
| 2 | **去路径前缀**（正反斜杠统一为 `/` 后取最后一段） | `"/usr/bin/rm"` / `"C:\\WINDOWS\\system32\\rm.exe"` → `"rm.exe"` |
| 3 | **去 `.exe` 后缀并转小写** | `"RM.EXE"` → `"rm"` |

**为什么取第一个词**：因为 `_command_may_mutate_workspace`（`:91-112`）需要判定「这个片段是哪个程序」，而判断依据是**程序名**（后续参数不影响「是不是纯读命令」这个结论，重定向/替换另行拦截）。整段比较会让 `rm -rf x` 与 `rm` 变成两个不同的 key，白名单就失效了。

★ 与 `semantics.extract_base_command`（`semantics.py:15`）和 `timeout_map.base_command_of`（`timeout_map.py:96-103`）是**三个功能相似但实现不同**的函数：

| 函数 | 位置 | 归一化步数 |
|---|---|---|
| `_segment_base` | `bash_tool.py:82-88` | 取首词 + 去路径 + 去 `.exe` + 小写 |
| `extract_base_command` | `semantics.py:15` | 先 `_split_segment` 再取（见 0228） |
| `base_command_of` | `timeout_map.py:96-103` | 取首词（`split(maxsplit=1)`）+ 去两种斜杠路径 + 小写（**不去 `.exe`**） |

★ `timeout_map.base_command_of` **不去 `.exe`**——这解释了 `timeout_map._FAMILY_TIMEOUTS_MS` 里为什么同时有 `"pytest": 300_000` 与 `"pytest.exe": 300_000` 两项（`:62-63`）：Windows 上 `pytest.exe` 会作为基础命令名出现，需要单独一条映射。而 `_segment_base` 去掉了 `.exe`，所以 `bash_tool` 的白名单不需要 `.exe` 变体。

**深化讲解**（面试官参考，不要求候选人全说）
「同一概念三处实现」是这批代码的显著特征（B04 里也有 `_line_diff_counts` 双份、`write_text_file` 等价逻辑双份）。这里的三份各有取舍：`_segment_base` 面向**程序身份识别**（要能对上白名单），`extract_base_command` 面向**语义解释**（要能对上 git 子命令），`base_command_of` 面向**超时映射**（要能对上映射表键）。三者对 `.exe` 的处理不同，正是各自映射表形态决定的。



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

### XEYO-QA-0205 git 只读子命令白名单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool git 特例 | `_GIT_READ_SUBS` | 简单 | 概念确认 | `python/tools/bash_tool/bash_tool.py:73,75-79,106-109` |

**面试官提问**
`git` 在 `_PURE_READ_BASES` 里，但要额外查一张子命令白名单。`git log`、`git commit`、`git push`、`git stash` 分别被判为「只读」还是「可能写盘」？

**参考答案要点**
**正解：B（`log` 只读；`commit` / `push` / `stash` 判**可能写盘**）**
`bash_tool.py:73` 与 `:75-79`（原文）：

```python
	"git",  # git 另查子命令白名单
})
_GIT_READ_SUBS = frozenset({
	"status", "log", "diff", "show", "blame", "rev-parse", "describe",
	"shortlog", "ls-files", "ls-remote", "cat-file", "grep", "reflog",
	"version", "help",
})
```

判定（`:106-109`）：

```python
		if base == "git":
			sub = _segment_base(" ".join(seg.strip().split()[1:]))
			if sub not in _GIT_READ_SUBS:
				return True
```

即：`git` 的**子命令不在白名单** → 返回 `True`（可能写盘 → 应清缓存）。所以 15 个子命令之外的**一切** git 子命令都按「可能写盘」处理，包括 `commit` / `push` / `stash` / `checkout` / `reset`（正确），也包括 `clean` / `fetch`（保守但安全）。

**一个实现细节**：取子命令用的是 `_segment_base(" ".join(seg.strip().split()[1:]))`——先把 `git` 之后的**全部词**重新拼成一个字符串，再对这个字符串调 `_segment_base`（它取首词）。所以：

- `git -c core.pager=cat log` → 拼出 `"-c core.pager=cat log"` → 首词是 `-c` → `"-c"` **不在白名单** → 判「可能写盘」（保守，正确方向）；
- `git --no-pager log` → 首词 `"--no-pager"` → 同上，保守处理。

也就是说**全局选项会让只读 git 命令被判为写盘**——这是 fail-closed 的**误判方向**（多清一次缓存，成本约 140ms，见 `bash_tool.py:57-61` 的注释「误清只损失一次缓存重建（~140ms），漏清是正确性事故——误差单向朝安全」）。

**深化讲解**（面试官参考，不要求候选人全说）
为什么 `git` 需要**特例**而不是拆成 `git-read` / `git-write` 两个程序名：因为命令行里程序名恒为 `git`，子命令是它的第一个非选项参数。于是「程序名 → 是否只读」这个映射必然是一对多的，只能加一层子命令判定。

★ 白名单的 15 项覆盖了日常查询（`status`/`log`/`diff`/`show`/`blame`/`rev-parse`/`describe`/`shortlog`/`ls-files`/`ls-remote`/`cat-file`/`grep`/`reflog`/`version`/`help`）。注意 `reflog` 在列（只读），而 `reset` / `checkout` / `switch` / `restore` 不在（都写工作区）——这个取舍是对的；但 `git fetch` / `git remote update` 也**不在**（它们写 `.git` 但不写工作区），被判「可能写盘」属保守。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「全部只读（`git` 在白名单里）」——说明没抓住本题的分界（A）。
- 答成「全部可能写盘（保守）」——说明没抓住本题的分界（C）。
- 答成「`log` / `commit` 只读；`push` / `stash` 可能写盘」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0206 破坏性快照的两个默认上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 上限 | 文件数与单文件字节 | 简单 | 概念确认 | `python/tools/bash_tool/destructive_guard.py:73-74,108-119` |

**面试官提问**
破坏性命令执行前会做 before 快照。`DEFAULT_MAX_FILES` 与 `DEFAULT_MAX_FILE_BYTES` 分别是多少？环境变量覆盖时有什么保护？

**参考答案要点**
**正解：B（**50 / 10_000_000**；环境变量经 `max(1, int(...))` 夹取下限）**
`destructive_guard.py:73-74`（原文）：

```python
DEFAULT_MAX_FILES = 50
DEFAULT_MAX_FILE_BYTES = 10_000_000
```

读取函数（`:108-119`）：

```python
def max_files() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_DESTRUCTIVE_SNAPSHOT_MAX_FILES", "")))
	except ValueError:
		return DEFAULT_MAX_FILES


def max_file_bytes() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_DESTRUCTIVE_SNAPSHOT_MAX_BYTES", "")))
	except ValueError:
		return DEFAULT_MAX_FILE_BYTES
```

| 项 | 默认 | 环境变量 | 保护 |
|---|---|---|---|
| 文件数 | `50` | `XEYO_DESTRUCTIVE_SNAPSHOT_MAX_FILES` | `max(1, ...)`（下限 1）；坏值回落默认 |
| 单文件字节 | `10_000_000`（约 10 MB） | `XEYO_DESTRUCTIVE_SNAPSHOT_MAX_BYTES` | 同上 |

**两处「最大」的语义不同**：`max_files` 是**参与快照的文件数上限**（超过部分不快照，计入 `skipped_count`，见 `DestructivePlan` 定义 `:87-100`）；`max_file_bytes` 是**单个文件超过此值就不快照**。

★ 注意环境变量为空串时 `int("")` 抛 `ValueError` → 回落默认值（这正是「未设置」的路径）；而传 `"0"` 会得到 `max(1, 0) = 1`——**不是「不限」**。也就是说这两个闸门**永远生效**，无法通过配置关成「全量快照」。这与 0202 的「`0` 不等于无限」是同一套设计取向。

**深化讲解**（面试官参考，不要求候选人全说）
快照守卫的定位是「**尽力而为的 before 保护**」而不是「完整备份」：它给 rewind（B03/B11 的文件级回溯）留下证据，但**有明确的成本上限**。两个闸门的组合意义是：

| 场景 | 结果 |
|---|---|
| 删 3 个小文件 | 全部快照 |
| 删 200 个小文件 | 前 50 个快照，其余 `skipped_count` 计数 |
| 删 1 个 50 MB 日志 | 不快照（超 `max_file_bytes`） |

所以「`rm -rf` 一个大目录」这类操作**必然有一部分不被快照**——这不是缺陷，而是「**快照成本必须可控**」的显式取舍（`settle_destructive_plan` 会在结局后结算，见 0235）。

**边界**：`guard_enabled()`（`:103-105`）用 `_DISABLE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})` 判定关闭——**默认开**（`os.environ.get("XEYO_DESTRUCTIVE_SNAPSHOT", "1")`）。所以整套守卫的开关是 `1/0`，而两个上限只能调不能关。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「100 / 1_000_000；无保护」——说明没抓住本题的分界（A）。
- 答成「200 / 50_000_000；坏值直接抛错」——说明没抓住本题的分界（C）。
- 答成「无上限（全量快照）」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0207 破坏性程序清单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 程序清单 | 两家族划分 | 简单 | 概念确认 | `python/tools/bash_tool/destructive_guard.py:54-66` |

**面试官提问**
`DESTRUCTIVE_PROGRAMS` 里包括哪些程序？`_POSIX_FAMILY` 与 `_WINDOWS_FAMILY` 的划分依据是什么？请完整列举。

**参考答案要点**
**A、B、C**。

`destructive_guard.py:54-66`（原文）：

```python
#: 破坏性程序名（小写、去 .exe、去路径前缀后匹配）。`ri` = Remove-Item 别名。
DESTRUCTIVE_PROGRAMS = frozenset({
	"rm", "unlink", "mv", "move", "del", "erase", "rd", "rmdir",
	"deltree", "remove-item", "ri",
})
#: POSIX 语义家族：`/x` 是路径不是旗标；`-x` 是旗标。
_POSIX_FAMILY = frozenset({"rm", "unlink", "mv"})
#: Windows/cmd/pwsh 语义家族：`-x` 与 `/x` 都按旗标跳过。
_WINDOWS_FAMILY = frozenset({
	"del", "erase", "rd", "rmdir", "deltree", "move", "remove-item", "ri",
})
#: 前缀程序（其后才是真命令）。
_PREFIX_PROGRAMS = frozenset({"sudo", "command", "env", "time", "nice", "nohup"})
```

**D 不正确**：家族划分**与运行平台无关**——它是**命令形态**的分类（依据命令本身属于哪一族方言），判定在 `_targets_in_segment` 里用 `windows = prog in _WINDOWS_FAMILY`（`:164`）。在 Windows 上照样可能是 `rm`（若装了 git-bash 或用了 `rm` 别名），此时应按 POSIX 语义解析参数。

**为什么会需要这个区分**（`_targets_in_segment`，`:174-179`）：

```python
		if tok.startswith("-"):
			# `-x` 旗标（两家族一致；`--` 也落在此处）。
			continue
		if windows and tok.startswith("/"):
			# cmd/pwsh 旗标（/q /s /y …）；POSIX 家族里 `/x` 是路径，不在此拦。
			continue
```

也就是说：**`/` 开头 token 的归属有歧义**。

| 程序 | `-x` | `/x` |
|---|---|---|
| `rm` / `unlink` / `mv` | 旗标（跳过） | **路径**（是删除目标！） |
| `del` / `rd` / `remove-item` … | 旗标 | 旗标（跳过） |

若把 `rm /tmp/x` 的 `/tmp/x` 当旗标跳过，就会**漏掉一个删除目标**（快照不到它）；若把 `del /q file` 的 `/q` 当路径，就会**试图快照一个不存在的 `/q`**（浪费或报错）。所以这个区分是**正确性必需**的。

★ `_PREFIX_PROGRAMS` 覆盖「其后的词才是真命令」的情形：`sudo rm x`、`env FOO=1 rm x`、`time rm x`。配套的 `_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")`（`:67`）跳过 `VAR=value` 形式的前缀赋值（`:153-158`）。

**深化讲解**（面试官参考，不要求候选人全说）
这份清单的**覆盖面取向是「宁多勿少」**：既有 POSIX（`rm`/`unlink`/`mv`），也有 cmd（`del`/`erase`/`rd`/`deltree`/`move`），还有 PowerShell（`remove-item` 与别名 `ri`；`rmdir`/`rd` 在 PowerShell 里也是 `Remove-Item` 的别名）。

★ 一个**可见的缺口**（本批待确认项）：清单**没有** `Remove-Item` 的其他常见别名 `rd`（有）、`rmdir`（有）、`ri`（有）之外的写入类命令，例如 `clear-content` / `set-content` / `out-file`（它们**截断**文件但不删除）。也就是说「破坏性=删除/移动」这个定义**不含截断**——`> file` 形式的截断由别的机制管（`_REDIR_TOKENS`，`:71`）。这是一致的定义边界，不是缺陷，但值得知道范围。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「划分依据是操作系统（在 Windows 上只启用 Windows 家族）」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0208 快照守卫的默认开关

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 开关 | 默认值与关闭词表 | 简单 | 概念确认 | `python/tools/bash_tool/destructive_guard.py:52,103-105` |

**面试官提问**
破坏性快照守卫默认是开还是关？哪些取值表示关闭？

**参考答案要点**
**正解：B（**默认开**；`0` / `false` / `no` / `off` / `disabled` 表示关闭（大小写不敏感、`strip` 后比较））**
`destructive_guard.py:52` 与 `:103-105`（原文）：

```python
_DISABLE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
```

```python
def guard_enabled() -> bool:
	value = os.environ.get("XEYO_DESTRUCTIVE_SNAPSHOT", "1").strip().lower()
	return value not in _DISABLE_VALUES
```

三条行为：

| 环境变量取值 | 结果 |
|---|---|
| 未设置 | `os.environ.get(..., "1")` → `"1"` → **开** |
| `"0"` / `"false"` / `"no"` / `"off"` / `"disabled"`（任意大小写、含前后空格） | **关** |
| 其他任意值（含 `"yes"`、`"true"`、`"banana"`、空串 `""`） | **开** |

★ 空串 `""`：`os.environ.get` 只有在变量**不存在**时才返回默认 `"1"`；若变量存在但为空串，返回 `""` → `"" not in _DISABLE_VALUES` → **开**。所以「设成空串」不等于关闭。

**这是「默认开 + 显式白名单关闭」的模式**——与 `aging_enabled`（`engine/aging.py:40-52`，**默认关**、需显式 `1/true/on/yes` 开启）**方向相反**。两者取向不同的理由是：

| 功能 | 默认 | 理由 |
|---|---|---|
| 破坏性快照（本模块） | **开** | 它是**保护**：关掉会让 `rm -rf` 无证据可回溯。误开的成本是快照开销（受 0206 两个上限约束） |
| 工具输出老化（`aging`） | **关** | 它是**删除**：开启会让原文从投影消失且不可找回（恢复机制未落地，见 B09-0448） |

即：**「保护类」默认开，「删除类」默认关**——这是本项目对待「默认值」的一条一致取向（方向安全 = 让默认值落在可逆那一侧）。

**深化讲解**（面试官参考，不要求候选人全说）
`_DISABLE_VALUES` 包含 `"disabled"` 这项值得注意：它多收了一个长词，使 `XEYO_DESTRUCTIVE_SNAPSHOT=disabled` 这种「自然写法」也能关。而**不包含** `"n"` / `"none"` / `"null"`——所以 `=none` 会被判为**开**（保守）。

**边界**：`guard_enabled()` 只在 `plan_destructive_snapshot`（`:213-226`）里被消费；关掉之后，`plan_destructive_snapshot` 应返回 `None`，于是工具的 `call` 路径里 `guard_plan` 为 `None`，`settle_destructive_plan(None, executed=...)` 也应是空操作（见 0235）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「默认关；`1`/`true` 表示开启」——说明没抓住本题的分界（A）。
- 答成「默认开；任何非空字符串都表示开启」——说明没抓住本题的分界（C）。
- 答成「默认关；只能通过代码常量开启」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0209 命令族超时的代表值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | timeout_map 分级表 | 家族与数值 | 简单 | 机制解释 | `python/tools/bash_tool/timeout_map.py:23-70` |

**面试官提问**
`_FAMILY_TIMEOUTS_MS` 按命令族给出的默认超时中，`cargo` / `mvn` / `npm` / `curl` / `pytest` 分别是多少？无命中时回落什么？

**参考答案要点**
`timeout_map.py:24-64`（原文节选与全表）：

| 命令族 | 默认超时 | 分组注释 |
|---|---|---|
| `pip` / `pip3` / `uv` / `pdm` / `poetry` / `conda` | `300_000` | 「网络安装常 3-5 分钟」 |
| `npm` / `npx` / `pnpm` / `yarn` / `bun` | `240_000` | 「npm ci / 原生编译常超」 |
| `apt` / `apt-get` / `apk` / `yum` / `dnf` / `brew` | `300_000` | 系统包管理 |
| `make` / `cmake` / `ninja` / `gcc` / `g++` / `clang` / `rustc` | `300_000` | 编译工具链 |
| **`cargo`** | **`420_000`** | 全表最大 |
| `go` | `240_000` | |
| `mvn` / `gradle` / `sbt` | `360_000` | 「JVM 构建」 |
| `wget` | `240_000` | |
| **`curl`** | **`180_000`** | 全表最小 |
| **`pytest`** / `pytest.exe` | **`300_000`** | |

**无命中回落**：`family_default_ms` 返回 `None`（`:106-127`），调用方回落**全局 120s**（`DEFAULT_TIMEOUT_MS`）。

**匹配优先级**（`:106-126`，注释原文「匹配优先级：env 覆盖 > 精确 base > 前缀家族」）：

1. env 覆盖（`XEYO_CMD_TIMEOUT_OVERRIDES`，JSON）；
2. 精确 base 名（`_FAMILY_TIMEOUTS_MS`）；
3. **前缀家族**（`_PREFIX_FAMILIES`，`:66-70`）：

```python
_PREFIX_FAMILIES: tuple[tuple[str, str], ...] = (
	("-m pip ", "pip"),
	("-m pytest ", "pytest"),
)
```

即 `python -m pip install ...` 与 `python -m pytest ...` 这类形态也能命中（判定用 `low.startswith(prefix) or (" " + prefix) in low`，`:121-123`）。

**深化讲解**（面试官参考，不要求候选人全说）
这张表解决的是一个具体的产品痛点（模块 docstring `:1-15` 原文）：

```
产品痛点：``bash_tool`` 默认超时对所有命令一刀切 120s（``DEFAULT_TIMEOUT_MS``），
``pip install`` / ``npm ci`` / 编译（make/gcc/cargo）等长命令经常在 120s 被掐断，
用户被迫手动加 timeout 或反复重试。
```

三条设计纪律（docstring）：

1. **纯规则、不碰 LLM 判断**（「符合『硬编码映射不要 LLM 判断』哲学」）；
2. **只影响「模型未显式传 timeout」时**——显式 timeout 仍由 `clamp_timeout_ms` 决定（见 0202）；
3. **worker（子 Agent）模式不生效**——「worker 30s/60s 上限是刻意的花钱护栏，不被命令族覆盖——`parse_input` 侧已排除」（见 0237）。

★ 还有一个**诚实的能力声明**（docstring `:13-14`）：「收益口径：这是产品体验修复（评测容器里 `docker exec` 另管超时、评测不疼），判定基线 = 单元测试锁映射正确性」——即它明确标注了「**这条改动不改善评测分数**」，只改善本机使用体验。这种标注在性能/体验类改动里很有价值（避免后人误以为它影响 benchmark）。



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

### XEYO-QA-0210 输出截断的 head/tail 常量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | truncate 双向保留 | 三个常量 | 简单 | 概念确认 | `python/tools/bash_tool/truncate.py:7-9` |

**面试官提问**
`truncate_for_model` 的三个长度常量是什么？当文本超过 `limit` 时保留哪些部分？

**参考答案要点**
**正解：A（`DEFAULT_LIMIT=30_000`、`HEAD_CHARS=20_000`、`TAIL_CHARS=8_000`；保留**头部 20k + 尾部 8k**，中间截断并落盘）**
`truncate.py:7-9`（原文）：

```python
DEFAULT_LIMIT = 30_000
HEAD_CHARS = 20_000
TAIL_CHARS = 8_000
```

截断逻辑（`:76-96`）：

```python
	if len(text) <= limit:
		return text, None

	ensure_dir(persist_dir)
	path = os.path.join(persist_dir, f"bash-{uuid.uuid4().hex}.txt")
	with open(path, "w", encoding="utf-8", errors="replace") as f:
		f.write(text)

	head = text[:HEAD_CHARS]
	tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
	middle = text[HEAD_CHARS : len(text) - TAIL_CHARS] if tail else ""
	body = head
	if tail:
		body = head + "\n\n...[middle truncated]...\n\n"
		if middle and not _has_signal_line(tail):
			excerpt = _error_excerpt(middle)
			if excerpt:
				body += excerpt + "\n\n"
		body += tail
	body = body + f"\n\n[output truncated, full at {path} ({len(text)} chars)]"
	return body, path
```

**四个关键行为**：

| 行为 | 实现 |
|---|---|
| 不超限直接返回 | `if len(text) <= limit: return text, None`（不落盘） |
| **超限先落盘** | 先写全文到 `persist_dir/bash-<uuid>.txt`，再裁剪（**顺序：raw 先落盘**） |
| 头尾区间 | `head = text[:20_000]`、`tail = text[-8_000:]`，中间为 `text[20000 : len-8000]` |
| **尾部不足时不留中间** | `tail` 的计算带条件 `if len(text) > HEAD_CHARS + TAIL_CHARS`——若文本长度在 20k–28k 之间，`tail` 为空串，此时 `body = head`（**只保留头部**，不拼接） |

★ 最后一条容易被忽略：`head + tail` 的上限是 28,000 字符，与 `DEFAULT_LIMIT = 30_000` 之间**留了 2,000 字符的余量**给截断标记与错误摘录。所以「超限后给模型的文本」通常略小于 30k，而不是正好 30k。

**深化讲解**（面试官参考，不要求候选人全说）
「**头 + 尾 + 落盘**」是输出治理的标准三件套，本项目的三个实现可以对照（见 0242 与 0250）：

| 实现 | 位置 | 头 | 尾 | 落盘 |
|---|---|---|---|---|
| Bash 自带 | `truncate.py:84-95` | 20,000 | 8,000 | `persist_dir/bash-<uuid>.txt` |
| registry 预算 | `tool_registry.py:210-216` | `PREVIEW_HEAD = 6_000` | `PREVIEW_TAIL = 2_000` | `spill.save_text` |
| Glob 完整列表 | `glob_tool.py:660-667` | — | — | `spill.save_text` |

Bash 之所以给得比 registry 更宽（20k+8k vs 6k+2k），是因为它在 `tools/meta.py` 里**豁免了 registry 预算**（`output_budget=0`，注释「Bash 自带 raw→落盘→截断 seam（truncate_for_model），豁免 registry 级预算，避免双重截断/双重落盘」，见 B04-0178）。所以两条链路**不会叠加**——Bash 的输出只被 `truncate_for_model` 处理一次。

**边界**：落盘路径由调用方传入（`persist_dir` 是必填关键字参数），文件名含 `uuid4().hex`，所以**不会覆盖**已有文件；`errors="replace"` 保证任意字节都能写出（不会因编码失败而丢落盘证据）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`DEFAULT_LIMIT=30_000`、`HEAD_CHARS=15_000`、`TAIL_CHARS=15_00」——说明没抓住本题的分界（B）。
- 答成「`DEFAULT_LIMIT=16_000`、`HEAD_CHARS=6_000`、`TAIL_CHARS=2_000`」——说明没抓住本题的分界（C）。
- 答成「`DEFAULT_LIMIT=30_000`；只保留头部」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0211 PowerShell 7 的钉版与校验

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | pwsh7 自动安装 | 钉版与哈希 | 简单 | 概念确认 | `python/tools/bash_tool/pwsh7.py:26-30,46-59` |

**面试官提问**
`pwsh7.py` 自动下载 PowerShell 时，怎么保证装到的是可信的官方版本？

**参考答案要点**
**正解：B（**钉死 `PINNED_VERSION = "7.4.6"`**、从 GitHub releases 下载固定的 zip 名，并**用官方 `hashes.sha256` 文件校验 SHA-256**）**
`pwsh7.py:26-30`（原文）：

```python
PINNED_VERSION = "7.4.6"
_GITHUB_RELEASE = f"https://github.com/PowerShell/PowerShell/releases/download/v{PINNED_VERSION}"
_ZIP_NAME = f"PowerShell-{PINNED_VERSION}-win-x64.zip"
_HASHES_NAME = "hashes.sha256"
_DOWNLOAD_TIMEOUT_S = 120
```

哈希解析（`:46-59`）：

```python
def _parse_hashes_txt(text: str, filename: str) -> str | None:
```

即从官方 `hashes.sha256` 文本里**按文件名**取出对应哈希（该文件是「多行、每行 `哈希 文件名`」的格式）。校验在 `install_from_zip(zip_path, expected_sha256=None)`（`:83`）里执行；`download_and_install()`（`:114`）负责取哈希 + 下载 + 校验 + 装。

**三条安全设计**：

| 项 | 实现 | 意义 |
|---|---|---|
| **钉版** | `PINNED_VERSION` 常量，URL/zip 名都由它派生 | 不受「最新版」漂移影响；行为可复现 |
| **哈希校验** | 与 zip 同目录的 `hashes.sha256`（官方发布物） | 防传输损坏 / 篡改 |
| **安全解压** | `_extract_zip_safe`（`:60-82`） | 防 zip-slip（路径逃逸） |

★ 注意哈希文件**与 zip 同源**（都从同一个 GitHub release 下载）——这意味着校验能防「传输错误/中间环节篡改 zip」，但**不能防「整个 release 被替换」**（那需要钉死哈希常量或签名校验）。这是一个诚实的边界：本模块的定位是**可复现 + 防损坏**，不是供应链签名验证。`expected_sha256` 参数允许调用方传入**外部钉死的哈希**来补上这一层。

**深化讲解**（面试官参考，不要求候选人全说）
「内置一个自包含的 PowerShell 7」这个需求来自 Bash 工具的 shell 策略：`runner.build_shell_argv`（`:136`）优先用 pwsh 7，退回 Windows PowerShell 5.1（见 0220）。5.1 的差异在 `bash_tool/prompt.py:16` 有直接体现：「`&&` and `||` work on PowerShell 7 only; on 5.1 split into separate calls」——也就是说 pwsh 7 的能力**直接影响模型能不能用复合命令**，所以值得为它做自动安装。

`locate()`（`:141-161`）与 `ensure()`（`:162-173`）构成查询/确保两级：`ensure()` 是「没有就装」。

**边界**：`_cache_root()`（`:33-37`）决定安装位置（缓存目录）；`_sha256_file`（`:38-45`）是分块读取的哈希计算（避免把整个 zip 读进内存）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「下载最新的 release，不校验」——说明没抓住本题的分界（A）。
- 答成「只校验文件大小」——说明没抓住本题的分界（C）。
- 答成「校验数字签名（Authenticode）」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0212 Windows Job 的默认内存上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | win_job Job Object | 内存限额 | 简单 | 机制解释 | `python/tools/bash_tool/win_job.py:22,94-105` |

**面试官提问**
`win_job.create_bash_job` 创建的 Job Object 默认内存上限是多少？这个值从哪里可以被覆盖？

**参考答案要点**
**默认 2048 MB（2 GB）**，可由工作区策略的 `bash_job_memory_mb` 覆盖。

`win_job.py:22`：

```python
DEFAULT_JOB_MEMORY_MB = 2048
```

`_memory_limit_bytes`（`:94-105`）把 MB 转成字节（并处理 `None` = 不限额）；`create_bash_job(*, memory_mb: int | None = None)`（`:106`）是入口。

**覆盖来源**在 `runner.py:53-59`：

```python
def _job_memory_mb(cwd: str) -> int | None:
	try:
		from permissions.workspace_policy import load_workspace_policy

		return load_workspace_policy(cwd).bash_job_memory_mb
	except Exception:
		return None
```

即：**工作区策略**（`.xeyo/settings` 一类的 `workspace_policy`，属 B07 面）提供 `bash_job_memory_mb`；取不到（异常/未配置）返回 `None`。

★ 注意 `None` 的语义：`create_bash_job` 的默认参数是 `memory_mb=None`，而 `_memory_limit_bytes(None)` 应当是「不设内存限额」——所以「策略里配了值」→ 用策略值；「策略取不到」→ **不限额**，而 `DEFAULT_JOB_MEMORY_MB = 2048` 是「显式要求限额但没给数」时的兜底。

**深化讲解**（面试官参考，不要求候选人全说）
Job Object 的**主要职责不是限额而是「进程树兜底清理」**——`runner._kill_process`（`:62-88`）的 docstring 写明了分工：

```
	优先 taskkill /T（可靠打断 shell 子进程）；Job Object 仅作限额与
	CloseHandle 时的 KillOnJobClose 兜底——勿在此调用 TerminateJobObject，
	在部分嵌套 Job 环境下会阻塞。
```

即：**杀进程树的主力是 `taskkill /T /F`**；Job Object 提供两件事：①内存限额；②句柄关闭时的 `KillOnJobClose`（进程句柄一关，Job 内所有进程被系统清理）。第 ② 条是「即使 XEYO 自己崩了也不留孤儿」的最后一层保险——这是 `taskkill` 做不到的（taskkill 需要 XEYO 活着去执行）。

**边界**：`TerminateJobObject` 被**显式警告不要用**——理由写在 docstring 里：「在部分嵌套 Job 环境下会阻塞」。这是一个有实测背书的约束（嵌套 Job 指进程本身已在某个 Job 里，Windows 8+ 支持嵌套 Job，但某些 API 在嵌套下行为异常）。



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

### XEYO-QA-0213 后台日志的 TTL

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | background 日志清理 | 清理周期 | 简单 | 机制解释 | `python/tools/bash_tool/background.py:209-225` |

**面试官提问**
旧式日志文件后台（`start_background` / `adopt_background` 那一套）的日志清理周期默认是多少？它在什么时候被触发？

**参考答案要点**
`background.py:209-225`（原文签名）：

```python
def _cleanup_old_logs(log_dir: str, *, ttl_s: float = 7 * 24 * 3600) -> None:
```

**默认 TTL = 7 天（`7 * 24 * 3600 = 604800` 秒）**。

触发时机是**在后台任务启动/接管时顺带清理**（与 `spill._prune_old`、`session_md._prune_rollouts` 的「机会式清理」模式一致，见 B09-0429）。

★ 这个默认值与另外两处一致：

| 处 | 默认 | 单位 |
|---|---|---|
| `background._cleanup_old_logs` | `7 * 24 * 3600` | 秒（硬编码默认参数） |
| `tools/spill._prune_old` | `7`（`DEFAULT_RETENTION_DAYS`） | 天（`XEYO_SPILL_RETENTION_DAYS`） |
| `memory/memdir.prune_dead_notes` | `7.0`（`DEFAULT_RETENTION_DAYS`） | 天（`XEYO_MEMORY_RETENTION_DAYS`） |
| `memory/journal.gc` | `7 * 24 * 3600`（`ttl_seconds` 默认） | 秒 |

**四处默认都是 7 天**——这是一个贯穿全项目的统一保留期约定。

**深化讲解**（面试官参考，不要求候选人全说）
后台作业在本模块里有**两套实现**，这是理解 `jobs_bridge`（0226）的前提：

| 实现 | 位置 | 通知机制 | 何时使用 |
|---|---|---|---|
| **registry job** | `jobs_bridge.start_registry_job`（`:14-52`） | 完成通知 / `job_output` / `job_kill` | **优先**（42 号改造后） |
| **旧式日志文件后台** | `background.start_background`（`:57-129`） | 只能读日志文件 | registry 不可用（CLI in-process）或登记失败 |

`bash_tool.call` 里的降级链（`:591-618`）先试 registry，失败则落回日志文件后台并**打一条 `_log.warning`**（`:603-607`：「registry job start failed (%s); falling back to log-file background」）。

`adopt_background`（`background.py:141-208`）用于「接管」——即进程重启后把已有的后台任务重新纳入管理（与 B03 的 `process_ledger` 的 `leftovers()` 属同一族能力）。`_cleanup_old_logs` 就是在这条路径与启动路径上被调用的。

**边界**：`ttl_s` 是**关键字参数带默认值**（不是环境变量），所以运维无法通过环境变量调整——要改只能改源码或走 `adopt_background` 的调用点传参。这是与 spill/memdir（都有环境变量）的一个差别（本批待确认项：是否需要为它补一个环境变量）。



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

### XEYO-QA-0214 压缩器的最小生效长度

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | cmd_compact 阈值 | 三个常量 | 简单 | 概念确认 | `python/tools/bash_tool/cmd_compact.py:13-15` |

**面试官提问**
`cmd_compact.py` 的三个常量 `_MIN_CHARS` / `_TAIL_BUILD_LINES` / `_MAX_GROUPED_FILES` 分别是多少？

**参考答案要点**
**正解：A（`4_000` / `12` / `40`）**
`cmd_compact.py:13-15`（原文）：

```python
_MIN_CHARS = 4_000
_TAIL_BUILD_LINES = 12
_MAX_GROUPED_FILES = 40
```

| 常量 | 值 | 语义 |
|---|---|---|
| `_MIN_CHARS` | `4_000` | **低于此长度不压缩**（压缩收益不值当） |
| `_TAIL_BUILD_LINES` | `12` | 构建类输出尾部保留的行数 |
| `_MAX_GROUPED_FILES` | `40` | 分组展示时最多列出的文件数 |

判定入口是 `compact_command_output(command, stdout)`（`:55-85`），家族识别是 `detect_family(command)`（`:45-54`）：

```python
_Family = str  # pytest | vitest | cargo_test | go_test | tsc | lint | git | build | unknown
```

**九个家族**，各有专门的压缩器：`_compact_pytest`（`:86-171`）、`_compact_test_runner`（`:172-225`，供 vitest/cargo_test/go_test 等）、`_compact_tsc`（`:226-259`）、`_compact_lint`（`:260-304`）、`_compact_git`（`:305-355`）、`_compact_build`（`:356-370`）。

**深化讲解**（面试官参考，不要求候选人全说）
「测试/构建输出压缩」的目的是**保信息不保全量**：`pytest -q` 的输出里 90% 是通过行，模型真正需要的是失败详情、traceback、统计行。而 `bash_tool/prompt.py:22` 把这件事写进了工具描述：「Noisy test/build/git stdout is compacted for the model; **failures are kept**」——即**承诺失败信息不被压掉**。

`_MIN_CHARS = 4_000` 的存在让「小输出」完全不受影响：一次 `git status` 的几十行不会被改写。这很重要——压缩器是**有损**的，所以必须有一个「不值得冒险」的下界。

**边界**：家族识别失败（`unknown`）时应有**原样返回**的兜底（不压缩比乱压缩安全）。九家族之外的一切命令（如 `ls`、`cat`）都在 `unknown` 里——这保证了压缩只作用于「输出可预测的成熟工具」。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`1_000` / `40` / `12`」——说明没抓住本题的分界（B）。
- 答成「`8_000` / `20` / `100`」——说明没抓住本题的分界（C）。
- 答成「`4_000` / `40` / `12`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。
### XEYO-QA-0215 只读白名单的 fail-closed 判定链

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 搜索缓存门控 | 写判定链路 | 中等 | 机制解释 | `python/tools/bash_tool/bash_tool.py:57-112` |

**面试官提问**
`_command_may_mutate_workspace(command)` 决定「是否要清掉 Glob / content_index 缓存」。它的判定链有几步？每一步的失败取向是什么？

**参考答案要点**
判定链共 **五道**（`bash_tool.py:91-112`，原文）：

```python
def _command_may_mutate_workspace(command: str) -> bool:
	"""Bash 命令是否可能写盘 → 是否应失效搜索缓存。"""
	if not command or not command.strip() or "\n" in command:
		return True  # 空/多行不可解析 → fail-closed
	try:
		from permissions.policy import bash_writes_file

		if bash_writes_file(command):
			return True  # 显式写特征（重定向/写命令/解释器带写标记）
	except Exception:
		return True  # 分类器不可用 → fail-closed
	if "$(" in command or "`" in command:
		return True  # 命令替换可藏任意写
	for seg in _split_segment(command):
		base = _segment_base(seg)
		if base == "git":
			sub = _segment_base(" ".join(seg.strip().split()[1:]))
			if sub not in _GIT_READ_SUBS:
				return True
		elif base not in _PURE_READ_BASES:
			return True
	return False
```

| 步 | 判据 | 命中时 | 失败取向 |
|---|---|---|---|
| 1 | 空 / 全空白 / **含换行** | `True`（判写） | fail-closed |
| 2 | `permissions.policy.bash_writes_file(command)` 抛异常 | `True` | fail-closed |
| 3 | `bash_writes_file` 返回真（显式写特征） | `True` | — |
| 4 | 含 `$(` 或反引号（命令替换） | `True` | fail-closed |
| 5 | 逐段查基础命令白名单（`git` 查子命令） | 非白名单 → `True` | fail-closed |
| 结果 | 全部通过 | `False`（保留缓存） | **只有全绿才不动缓存** |

**为什么每一步都 fail-closed**（`:57-61` 的设计注释原文）：

```
# fail-closed：只读白名单全命中才保留缓存；解释器/未知/解析失败一律判写。
# 误清只损失一次缓存重建（~140ms），漏清是正确性事故——误差单向朝安全。
```

即**成本不对称**：

| 误判方向 | 后果 | 量级 |
|---|---|---|
| 误判为「写」 | 白清一次缓存 | ~140ms 重建（注释给出的估值） |
| 误判为「只读」 | 写后 60s/30s 内 Glob/Grep 看到旧结果 | **正确性事故**（「存在但找不到」幽灵） |

所以整条链的默认答案是「写」，只有**明确的只读证据**才翻转它。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的关键是把「**fail-closed 的成本论证**」读出来。它不是「保守主义」的教条，而是**基于两个方向成本相差数量级的量化判断**：

- 「多清一次」是可忽略的一次性开销（且 60s TTL 本来就意味着缓存会自然过期）；
- 「漏清一次」会让模型在写文件后**看不见自己的改动**——而模型很可能据此做出错误决策（重试、怀疑写入失败、走别的路径）。

★ 第 1 步「含换行即判写」是这条链里**最粗的一刀**：多行命令（如 `ls\nrm x`）无法用单片段解析器可靠分析，所以直接放弃分析。这解释了 `tests/test_glob_optimize.py:517` 那条断言 `mutate("ls\nrm x") is True`——**即使第一行是只读命令，只要含换行就判写**。

★ 第 4 步（命令替换）是另一条「可藏任意写」的通道：`echo $(python write.py)` 的表面命令是 `echo`（在 `_PURE_READ_BASES` 里！），但替换里可以跑任意程序。`tests/test_glob_optimize.py:515` 正是这条的断言。



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

### XEYO-QA-0216 晋升阈值与收尾窗路由

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 前台晋升 | 两条时间线 | 中等 | 机制解释 | `python/tools/bash_tool/bash_tool.py:128-175` |

**面试官提问**
`BASH_PROMOTE_DEFAULT_MS` 与环境变量 `XEYO_BASH_PROMOTE_MS` 是什么关系？`effective_promote_ms` 在什么情况下会把阈值改成 `1`（立即后台化）？

**参考答案要点**
**关系**（`bash_tool.py:128-140`）：

```python
#: 前台命令运行超过该阈值仍未结束 → 自动晋升为后台 job（0=关闭）。
#: 进程不重启、已累积输出随晋升返回；env XEYO_BASH_PROMOTE_MS 可调。
BASH_PROMOTE_DEFAULT_MS = 45_000


def promote_threshold_ms() -> int:
	raw = os.environ.get("XEYO_BASH_PROMOTE_MS", "").strip()
	if not raw:
		return BASH_PROMOTE_DEFAULT_MS
	try:
		return max(0, int(raw))
	except ValueError:
		return BASH_PROMOTE_DEFAULT_MS
```

即：默认 **45_000 ms（45 秒）**；环境变量可覆盖；**解析失败回落默认**；**夹取下限 0**——而 `0` 的语义是「**关闭晋升**」（注释原文「0=关闭」）。

**`effective_promote_ms` 的立即后台化条件**（`:149-175`）：

```python
	if base_ms <= 0:
		return base_ms
	try:
		from engine.wrap_window import in_wrap_window, wrap_remaining_s
		from tools.bash_tool.timeout_map import family_default_ms

		if not in_wrap_window():
			return base_ms
		if family_default_ms(cmd) is None:
			return base_ms
		remaining = wrap_remaining_s()
		if remaining is not None and remaining >= WRAP_WINDOW_BG_MAX_REMAINING_S:
			return base_ms
		return 1
	except Exception:  # noqa: BLE001 — 信号/映射不可用即按原阈值
		return base_ms
```

**四条早退 + 一条命中**（见 0241 展开），核心是「**收尾窗 + 长命令族 + 窗口剩余时间短或未知**」→ 返回 `1`（立即晋升）。

`WRAP_WINDOW_BG_MAX_REMAINING_S = 120.0`（`:146`），理由（`:143-145` 注释）：

```
#: 收尾窗内"立即后台化长命令"的剩余时间闸门（秒）。窗口还剩很多时不动——让
#: 可能在窗口内跑完的命令照常前台等结果（保住"最后一步长命令出产物"的路径）；
#: 只在窗口已经很短（或剩余时间未知=配额型收尾窗）时才提前交还控制权。
```

**深化讲解**（面试官参考，不要求候选人全说）
两条时间线必须分清（本题的核心）：

| 时间线 | 阈值 | 到点后的行为 |
|---|---|---|
| **晋升** | 45s（`promote_threshold_ms`） | 命令**继续运行**（进程不重启），但控制权交还模型，结果改由 job 通知/`job_output` 领取 |
| **超时** | 120s（`DEFAULT_TIMEOUT_MS`，可被命令族映射放大到 180–420s） | 命令**被杀**，返回 `Command timed out after N ms and was killed.` + 部分输出（`runner.py:390-398`） |

所以一条 `npm ci` 的典型生命周期是：45s 时**晋升**为后台 job → 后台继续跑 → 可能在 240s（npm 族默认）内正常结束 → 完成通知。**若没有 45s 晋升**，模型会一直等到 120s/240s 才拿到任何东西，回合被长时间占住。

★ 「收尾窗内改成 1ms」这条路由的用意（`:152-155` 注释原文）：

```
	窗口（R1'/R3' 的 forced_wrap_up）只剩几十秒时，等 promote 阈值（默认 45s）
	等于把落盘时间吃掉；提前交还控制权，模型就能用余下时间落盘。这是**执行层
	路由决策**，不向模型输出任何劝告文本。
```

注意最后半句——**「不向模型输出任何劝告文本」**，这正是 AGENTS.md 铁律「限制只在执行层」的落地：引擎通过**改变调度行为**（立即后台化）来达成目的，而不是往模型注意力里塞一句「时间不多了，请尽快落盘」。

**边界**：`family_default_ms(cmd) is None` 时**不晋升**——即「非长命令族」即使收尾窗很紧也照常在窗口内等。这是「只对已知会久留的家族做提前交权」的精确限定。



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

### XEYO-QA-0217 破坏性目标 token 的提取规则

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 目标提取 | token 过滤 | 中等 | 机制解释 | `python/tools/bash_tool/destructive_guard.py:130-182` |

**面试官提问**
`_targets_in_segment(segment)` 从一段命令里提取「删除目标」。它会跳过哪些 token？为什么这些跳过是正确性必需的？

**参考答案要点**
`destructive_guard.py:147-182`（原文）：

```python
def _targets_in_segment(segment: str) -> list[str]:
	"""从单个命令段提取破坏性命令的目标 token（不解析路径、不查存在性）。"""
	tokens = _segment_tokens(segment)
	if not tokens:
		return []
	idx = 0
	while idx < len(tokens):  # 前缀：VAR=value / sudo / env / time …
		tok = tokens[idx]
		if _ENV_ASSIGN_RE.match(tok) or tok.lower() in _PREFIX_PROGRAMS:
			idx += 1
			continue
		break
	if idx >= len(tokens):
		return []
	prog = _program_name(tokens[idx])
	if prog not in DESTRUCTIVE_PROGRAMS:
		return []
	windows = prog in _WINDOWS_FAMILY
	targets: list[str] = []
	skip_next = False
	for tok in tokens[idx + 1:]:
		if skip_next:
			skip_next = False
			continue
		if tok in _REDIR_TOKENS:
			skip_next = True
			continue
		if tok.startswith("-"):
			# `-x` 旗标（两家族一致；`--` 也落在此处）。
			continue
		if windows and tok.startswith("/"):
			# cmd/pwsh 旗标（/q /s /y …）；POSIX 家族里 `/x` 是路径，不在此拦。
			continue
```

**跳过的五类 token**：

| # | 跳过对象 | 机制 | 为什么必需 |
|---|---|---|---|
| 1 | `VAR=value` 前缀赋值 | `_ENV_ASSIGN_RE`（`:67`） | `FOO=1 rm x` 里 `FOO=1` 是环境赋值，不是命令也不是目标 |
| 2 | 前缀程序 | `_PREFIX_PROGRAMS`（`:66`） | `sudo rm x` / `env rm x` / `time rm x` 里真正要解析的是 `rm` |
| 3 | 重定向 token **及其后的目标名** | `_REDIR_TOKENS` + `skip_next`（`:71,171-173`） | `echo x > out.txt` 里 `out.txt` 是**写目标**不是删除目标；把它当删除目标会去快照一个「将被创建的文件」 |
| 4 | `-x` 形式的旗标（含 `--`） | `tok.startswith("-")`（`:174-176`） | `rm -rf x` 里 `-rf` 是旗标 |
| 5 | Windows 家族下的 `/x` 形式旗标 | `windows and tok.startswith("/")`（`:177-179`） | `del /q /s x` 里 `/q`/`/s` 是旗标 |

★ **第 5 条是两家族差异的核心**（见 0207）：POSIX 家族下 `/tmp/x` **是路径**，不能被当旗标跳过——否则会漏掉一个删除目标。所以这条跳过**只在 `windows` 为真时生效**。

**token 切分的前置处理**（`_segment_tokens`，`:130-144`）：

```python
	try:
		raw = shlex.split(segment, posix=False)
	except ValueError:
		raw = segment.split()
	tokens: list[str] = []
	for tok in raw:
		if tok.startswith("#"):
			break
		if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
			tok = tok[1:-1]
		if tok:
			tokens.append(tok)
```

三处：①`shlex.split(..., posix=False)`——**非 POSIX 模式**保留引号（便于自己判断），失败则退化为 `split()`；②**遇 `#` 开头的 token 即停止**（当注释起点，`:131` 注释「raw token 判定，引号内不算」——但注意 `shlex` 非 POSIX 模式下引号是保留的，所以 `"#x"` 这种带引号的不会 startswith `#`）；③**剥掉成对的引号**。

**深化讲解**（面试官参考，不要求候选人全说）
这段代码的设计原则写在 docstring 里：「**不解析路径、不查存在性**」。也就是说 `_targets_in_segment` 只做**词法级的候选提取**——它的输出是「疑似目标」列表，后续 `_expand_targets`（`:184`）才做路径展开、`_contained`（`:206`）才判工作区包含关系。

这个分层是必要的：**在快照阶段查存在性会引入 TOCTOU**（检查与执行之间目标可能变化），而快照本来就是「尽力而为」（见 0206）。所以这里选择「词法提取 → 展开 → 包含判定」，**每一步都不依赖「目标当前是否存在」**。

**边界**：`prog not in DESTRUCTIVE_PROGRAMS` 时直接返回 `[]`（`:162-163`）——所以非破坏性命令段**不产生任何目标**。因此 `rm a && ls b` 只会得到 `["a"]`（第二段是 `ls`，不是破坏性程序）。



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

### XEYO-QA-0218 快照的路径展开与尺寸闸

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 展开与包含 | 两处判定 | 中等 | 机制解释 | `python/tools/bash_tool/destructive_guard.py:184-226` |

**面试官提问**
`_expand_targets` 与 `_contained` 各自做什么？`plan_destructive_snapshot` 把它们与两个上限常量怎么组合？

**参考答案要点**
**`_expand_targets(raw_targets, cwd)`**（`:184-205`）：把词法提取出的原始 token 展开成**真实路径**——包括 `~` 展开、相对路径按 `cwd` 拼接、通配符展开（`glob`）。docstring 未在本次读取范围内完整呈现，但从函数名、签名与调用位置（位于 `_targets_in_segment` 之后、`_contained` 之前）可确定其职责是「候选 → 绝对路径集合」。

**`_contained(path_real, root_real)`**（`:206-212`）：

```python
def _contained(path_real: str, root_real: str) -> bool:
```

判断一个已解析的路径是否落在工作区根之内。**入参名带 `_real` 后缀**说明调用方应传入 `realpath` 结果（解析过 symlink），这样包含判定不会被 symlink 绕过（对照 B04-0169 讨论的 `abspath` vs `realpath`）。

**`plan_destructive_snapshot(command, cwd)`**（`:213-226`）：编排入口——解析命令段 → 提取目标 → 展开 → 过滤（工作区内）→ 受两个上限约束 → 对每个通过的文件做 before 快照 → 组装 `DestructivePlan`。

`DestructivePlan` 的字段（`:87-100`）：

```python
@dataclass
class DestructivePlan:
	"""一次破坏性命令的快照计划；由执行路径持有并在结局后结算。"""

	command: str
	cwd: str
	ctx: Any  # RewindExecutionContext；rewind 导入失败时本模块整体降级
	entries: list[GuardEntry] = field(default_factory=list)
	operation_ids: list[str] = field(default_factory=list)
	skipped_count: int = 0
	settled: bool = False
	_settle_lock: threading.Lock = field(
		default_factory=threading.Lock, repr=False, compare=False
	)
```

| 字段 | 含义 |
|---|---|
| `command` / `cwd` | 原命令与运行目录（审计/重放） |
| `ctx` | **RewindExecutionContext**——注释直接说明「rewind 导入失败时**本模块整体降级**」 |
| `entries` | 已成功快照的文件（`GuardEntry`：`path` / `snapshot_id` / `content_hash` / `size_bytes`，`:77-85`） |
| `operation_ids` | 对应 rewind 侧的操作 id（供结算与回溯定位） |
| `skipped_count` | **因超限未快照的数量**（见 0206） |
| `settled` + `_settle_lock` | 结算标志与锁（防重复结算，见 0235） |

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于看清「**快照的依赖边界**」：`ctx` 的类型是 `Any`，注释写明「rewind 导入失败时本模块整体降级」。也就是说：

```
destroy_guard  →  依赖  →  rewind 的 RewindExecutionContext
                          （B11 的文件级回溯体系）
```

若 rewind 不可用（导入失败），整个守卫**降级**而不是报错——这与 `guard_enabled()` 默认为开形成对比：**开关默认开，但依赖缺失时静默降级**。这个取向合理（守卫是增强项，不该阻断 Bash 主路径），但代价是「**守卫可能在用户不知情的情况下不生效**」（见 0249 的超压题）。

★ `_contained` 的入参命名（`path_real` / `root_real`）是一条**代码级契约提示**：它要求调用方先 `realpath`。这与 `destructive_guard` 的「不查存在性」原则有一处张力——`realpath` 对不存在的路径会退化为 `abspath`（不解析 symlink），所以「目标尚不存在」时包含判定是**弱化版**的。这属于可接受的降级方向（宽松判定 → 可能多快照区外文件，但不会漏快照区内文件）。



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

### XEYO-QA-0219 `_kill_process` 的平台分叉

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | runner 进程终止 | 两平台不同实现 | 中等 | 机制解释 | `python/tools/bash_tool/runner.py:62-88` |

**面试官提问**
`_kill_process(proc, job)` 在 Windows 与 POSIX 上的实现有什么不同？为什么 Windows 分支要额外用 `taskkill`？`job` 参数为什么被显式忽略？

**参考答案要点**
`runner.py:62-88`（原文）：

```python
def _kill_process(proc: subprocess.Popen, job: JobHandle | None = None) -> None:
	"""终止仍在运行的进程树。

	优先 taskkill /T（可靠打断 shell 子进程）；Job Object 仅作限额与
	CloseHandle 时的 KillOnJobClose 兜底——勿在此调用 TerminateJobObject，
	在部分嵌套 Job 环境下会阻塞。
	"""
	_ = job
	if proc is None or proc.poll() is not None:
		return
	try:
		if os.name == "nt" and proc.pid:
			# shell=False 时杀的也是整棵树（taskkill /T）；proc.kill() 仅杀根。
			subprocess.run(
				["taskkill", "/PID", str(proc.pid), "/T", "/F"],
				capture_output=True,
				timeout=5,
				check=False,
			)
		else:
			proc.kill()
		try:
			proc.wait(timeout=2)
		except subprocess.TimeoutExpired:
			pass
	except OSError:
		pass
```

| 平台 | 实现 | 杀的范围 |
|---|---|---|
| Windows | `taskkill /PID <pid> /T /F` | **整棵树**（`/T` 递归） |
| POSIX | `proc.kill()` | **只有根进程**（注释自陈：「`proc.kill()` 仅杀根」） |

`job` 参数被 `_ = job` **显式忽略**，理由是 docstring 里那句：「Job Object 仅作限额与 CloseHandle 时的 KillOnJobClose 兜底——**勿在此调用 TerminateJobObject，在部分嵌套 Job 环境下会阻塞**」。即：Job Object 的清理**不通过主动调用**完成，而是靠**句柄关闭**时的系统行为（`KillOnJobClose`）。

**为什么 Windows 需要 `taskkill`**：`proc.kill()` 只终止 `Popen` 直接创建的那个进程——而这里是 `pwsh -Command <command>`，被杀的只是 **pwsh 外壳**，它启动的子进程（真正的 `npm`/`pytest`）会**变成孤儿继续跑**。`taskkill /T` 递归整棵树，正是为解决这个。

**深化讲解**（面试官参考，不要求候选人全说）
★ **这道题的 POSIX 分支正是审计报告 `TOOL-06` 的位置**（`docs/全项目BUG排查-20260910.md:138`：「POSIX 超时只 kill shell 不杀子进程树 → 孤儿进程」，文档锚点 `runner.py:81-82`）——本批实测**锚点完全一致**（`:81-82` 正是 `else: proc.kill()`），缺陷**仍然成立**（见 0246 超压题）。

也就是说 `_kill_process` 里存在**平台不对称**：

| 平台 | 树杀 | 孤儿风险 |
|---|---|---|
| Windows | ✅ `taskkill /T` + Job Object `KillOnJobClose` 双保险 | 低 |
| POSIX | ❌ 只杀根 + **没有 Job Object** | **高**：`sh -c "npm run build"` 超时后 `npm` 与其子进程继续跑 |

Posix 侧缺失的原因可能在于「Windows 上出现过孤儿问题所以专门修了」，而 POSIX 侧的等价方案（进程组 `setsid` + `killpg`、或 `start_new_session=True`）没有落地。

**边界**：函数开头的 `if proc is None or proc.poll() is not None: return` 保证幂等（已退出则不动作）；`taskkill` 的 `check=False` 意味着**失败不抛**（进程可能已自然退出）；`timeout=5` 防止 `taskkill` 自身挂住。



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

### XEYO-QA-0220 shell 选择与 UTF-8 环境

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | runner shell 解析 | 优先级与环境 | 中等 | 机制解释 | `python/tools/bash_tool/runner.py:30-45,116-177` |

**面试官提问**
`build_shell_argv` 在 Windows 上按什么优先级选 shell？argv 向量的固定参数是哪四个？`_resolve_pwsh_exe` 会下载 PowerShell 吗？

**参考答案要点**
**优先级**（`runner.py:136-147`）：

```python
def build_shell_argv(command: str) -> tuple[list[str], str]:
	"""构造 shell 调用向量。command 不参与解析器选择（仅占位签名）。

	返回 (argv 前缀, 显示名)。最终 Popen 为 ``[*argv, command]``、``shell=False``。
	"""
	_ = command
	if os.name != "nt":
		return ["/bin/sh", "-c"], "sh"
	exe, kind = _resolve_pwsh_exe()
	if kind == "pwsh" and exe:
		return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"], "pwsh"
	return [_ps51_exe(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"], "powershell"
```

| 条件 | shell | argv 前缀 |
|---|---|---|
| 非 Windows | `/bin/sh -c` | 显示名 `sh` |
| Windows + pwsh7 可用 | `<pwsh.exe>` | `-NoLogo -NoProfile -NonInteractive -Command` |
| Windows + pwsh7 不可用 | `WindowsPowerShell\v1.0\powershell.exe` | 同四参数 |

**四个固定参数**：`-NoLogo`（不显示启动横幅）、`-NoProfile`（不加载用户 profile，保证可复现）、`-NonInteractive`（不允许交互提示）、`-Command`（后随命令串）。

**`_resolve_pwsh_exe` 会下载吗**：**不会**。docstring 明确（`:121-122`）：

```python
	"""返回 (pwsh.exe 路径 | None, kind)。不下载、不阻塞；仅文件存在性判断。"""
```

它做两件事：①检查 `XEYO_DISABLE_PWSH7`（`1/true/yes` 时直接返回 `(None, "powershell")`）；②调用 `pwsh7.locate()`（`:141-161`，只查缓存目录里有没有已安装的）。**下载只发生在 `pwsh7.ensure()`**（`:162-173`），由别的入口（如启动引导）触发。

`_ps51_exe()`（`:116-118`）：

```python
def _ps51_exe() -> str:
	root = os.environ.get("SystemRoot", r"C:\Windows")
	return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
```

用 `SystemRoot` 环境变量定位（兜底 `C:\Windows`），而不是硬编码路径。

**深化讲解**（面试官参考，不要求候选人全说）
「不下载、不阻塞；仅文件存在性判断」这条约束很关键：`build_shell_argv` 在**每次执行命令**时都会被调用（`spawn_streaming` 里 `:342`），若这里触发下载（120s 超时，见 0211），一次命令执行就会被网络阻塞。所以**选择 shell 必须是纯本地判定**，下载必须发生在独立入口。

★ `_utf8_env()`（`:30-45`）与 `_decode`（`:91-105`）配对解决中文乱码问题：前者给子进程注入 UTF-8 相关环境变量（让 `python`/`rg`/`git` 输出 UTF-8），后者做多级解码回退（见 0221）。`shell_display_name()`（`:150-176`）把版本号探测结果**进程内缓存一次**（`_SHELL_META_CACHE` + `_SHELL_META_LOCK`），因为每次探测要起一个 pwsh 进程（8s 超时）——它只用于结果头元信息与诊断，不值得每命令一次。

**边界**：`shell_display_name` 的探测失败**不影响执行**（`except Exception: pass`，`:172-173`），显示名退化为 `f"{kind} (version unavailable)"`。



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

### XEYO-QA-0221 输出的三级编码回退

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | runner 输出解码 | `_decode` | 中等 | 机制解释 | `python/tools/bash_tool/runner.py:91-105` |

**面试官提问**
`_decode(data)` 按什么顺序尝试解码？为什么需要多级回退而不是直接用 UTF-8？

**参考答案要点**
`runner.py:91-105`（原文）：

```python
def _decode(data: bytes) -> str:
	"""按 UTF-8 优先、OEM/GBK 回退解码子进程输出，根治中文乱码。

	Windows PowerShell 5.1 的部分原生输出仍走 OEM/GBK 码页；python/rg/git 等
	已按 UTF-8（见 ``_utf8_env``）。纯 UTF-8 解码失败（如 GBK 汉字）→ 回退
	GBK/cp936，避免中文文件名输出 ``***********`` 乱码。可作任意字节块解码。
	"""
	if not data:
		return ""
	for codec in ("utf-8", "gbk", "cp1252"):
		try:
			return data.decode(codec)
		except UnicodeDecodeError:
			continue
	return data.decode("utf-8", errors="replace")
```

**三级顺序**：`utf-8` → `gbk`（cp936）→ `cp1252` → 最后 `utf-8` + `errors="replace"`（永不失败）。

**为什么需要回退**（docstring 给出两半原因）：

| 半 | 说明 |
|---|---|
| **输出源多样** | Windows PowerShell 5.1 的**部分原生命令**走 OEM/GBK 码页；而 `python`/`rg`/`git` 经 `_utf8_env` 注入后走 UTF-8 |
| **纯 UTF-8 解不开 GBK** | GBK 汉字字节序列通常不是合法 UTF-8 → 抛 `UnicodeDecodeError` → 需要回退 |

★ 这个设计还有一条**逐块解码**的前提：docstring 末尾写「**可作任意字节块解码**」——因为 `_pump`（`:224-239`）是**逐行**从 `proc.stdout` 读取并解码的（`for raw in self.proc.stdout: text = _decode(raw)`），所以 `_decode` 必须能处理「任意字节块」而不只是完整文件。这也意味着编码判定是**逐行**做的——同一份输出里理论上可能混用不同编码（例如 pwsh 5.1 的原生命令输出 GBK，而 `python` 输出 UTF-8），逐块解码恰好能分别处理。

**深化讲解**（面试官参考，不要求候选人全说）
「GBK 在 cp1252 之前」这个顺序体现了**语言环境假设**：这个项目的主要用户环境是中文 Windows，所以 GBK 比西欧的 cp1252 更可能是正确答案。若顺序反过来，一个 GBK 字节序列**很可能**能被 cp1252 解出来（cp1252 几乎把所有字节都映射到某个字符），从而产生**看似成功但完全错乱**的结果（乱码但不报错）——这是「多级回退」里最危险的失败模式：**错误的成功**。

| 顺序 | GBK 字节的结局 |
|---|---|
| utf-8 → **gbk** → cp1252 | 在 gbk 处正确解出 ✅ |
| utf-8 → **cp1252** → gbk | 被 cp1252「成功」解成西欧乱码 ❌（不会走到 gbk） |

所以这个顺序**必须**是「更可能正确的编码在前」，且 cp1252 放在**最后**（它几乎不会失败，放最后才有意义）。

**边界**：`if not data: return ""` 提前处理空块；最后的 `errors="replace"` 是**永不失败的兜底**（保证 `_decode` 的返回类型恒为 `str`）——但注意它**只有在三个 codec 全部失败后**才执行，而 cp1252 几乎不可能失败，所以这条兜底实际很少触发。



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

### XEYO-QA-0222 流式句柄与收尾

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | runner 流式底座 | 句柄与四类结局 | 中等 | 机制解释 | `python/tools/bash_tool/runner.py:197-245,332-405` |

**面试官提问**
`StreamHandle` 承担了什么架构角色？`finish_streaming` 会产出哪几类结局？

**参考答案要点**
**架构角色**（`runner.py:197-213`）：

```python
@dataclass
class StreamHandle:
	"""一次流式 spawn 的句柄：活进程 + 泵缓冲 + 可后挂的 sink。"""

	proc: subprocess.Popen | None
	job: JobHandle | None
	spawn_error: str | None = None
	buf: list[str] = field(default_factory=list)
	sinks: list[SinkFn] = field(default_factory=list)
	killed_by_abort: bool = False
	buf_lock: threading.Lock = field(default_factory=threading.Lock)
	_pump_done: threading.Event = field(default_factory=threading.Event)
	_release_lock: threading.Lock = field(default_factory=threading.Lock)
	_released: bool = False
	#: [AbortController | None] 可变槽：attach/detach 原语换内容，监视线程每轮读槽。
	_abort_box: list = field(default_factory=list)
	_watcher_started: bool = False
```

它是**前台与后台共用的底座**：`run_command`（`:408-426`）走 `spawn_streaming` + `finish_streaming`，而 `bash_tool` 的晋升（0216）也是**在这个句柄上**做交接——`spawn_streaming` 的注释（`:368`）写明了：

```python
	# 总是启动监视线程：晋升时 detach/attach 换槽即可，无需重启线程。
	h.watch_abort(abort)
```

**三个关键设计**：

| 设计 | 字段/机制 | 作用 |
|---|---|---|
| **泵线程 + 缓冲** | `_pump` / `buf` / `buf_lock` / `_pump_done` | 后台线程逐行读 stdout，写入内存缓冲并分发给 sinks；**不积压 PIPE**（`:421` 注释） |
| **可后挂 sink** | `sinks` + `add_sink`（`:242-244`） | 前台时无 sink，晋升为后台时挂一个「写日志」的 sink（见 0231） |
| **abort 可变槽** | `_abort_box` + `watch_abort` | 监视线程每轮读槽内容——所以 `attach/detach` 换的是**槽里的对象**，线程无需重启 |

**`finish_streaming` 的四类结局**（`:373-405`）：

```python
	if h.spawn_error is not None:
		return ExecResult(stdout=h.spawn_error, code=1)
	...
	if timed_out:
		return ExecResult(
			stdout=(
				f"Command timed out after {timeout_ms}ms and was killed.\n"
				f"Partial output:\n{stdout or ''}"
			),
			code=code or 1,
			timed_out=True,
		)
	if h.killed_by_abort:
		return ExecResult(
			stdout=(stdout or "").rstrip() + "\n",
			code=code or 1,
			interrupted=True,
		)
	return ExecResult(stdout=stdout or "", code=code)
```

| 结局 | `ExecResult` 标志 | 正文 |
|---|---|---|
| spawn 失败 | — | `spawn_error` 文本 |
| **超时** | `timed_out=True` | `Command timed out after N ms and was killed.` + 部分输出 |
| **中止** | `interrupted=True` | 仅部分输出（**不加任何提示文本**） |
| 正常 | — | 输出 + 真实退出码 |

★ 中止那条的**静默**很值得注意：它只 `rstrip()` 后加一个换行，**不拼「已取消」之类的说明**。理由与 AGENTS.md 铁律一致（中性结果型文案）；而 `interrupted` 标志由上层（`query_loop`）转成 `StoppedEvent`，**不需要工具文本去说这件事**。

**超时那条**则**必须**说话——因为「命令被杀了」是模型必须知道的事实（否则它会以为拿到了完整输出）。

**深化讲解**（面试官参考，不要求候选人全说）
`StreamHandle` 的存在解决了「晋升不重启进程」这个硬约束（`bash_tool.py:128-130` 注释：「进程不重启、已累积输出随晋升返回」）。若没有这个句柄，晋升就得「杀掉前台进程 → 后台重新启动命令」——那会**重跑副作用**（构建、安装、写盘），完全不可接受。

所以句柄的设计目标可以概括为：**让「等待」这个动作可以被解绑，而进程本身不受影响**。三个机制分别负责：泵缓冲（输出不丢）、sink 后挂（输出改道）、abort 槽（取消通道可换）。

**边界**：`_release()` 与 `_release_lock`/`_released`（`:209-210`）构成**幂等释放**（防重复释放 Job 句柄 / 台账登记）；`finish_streaming` 里 `h.release()` 在 `wait` 之后调用（`:387`）——即「先等完/杀完，再释放资源」。



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

### XEYO-QA-0223 预检查的三道闸

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | precheck 命令预检 | 三类拦截 | 中等 | 机制解释 | `python/tools/bash_tool/precheck.py:25-112` |

**面试官提问**
`precheck_command(command)` 拦哪三类命令？为什么只拦这三类，而不做更全面的校验？

**参考答案要点**
三道闸（`precheck.py` 的定义面）：

| 闸 | 函数 | 拦截对象 | 常量 |
|---|---|---|---|
| 1 | `_fullscreen_block`（`:43-53`） | **全屏/分页交互程序**（会占满 TTY、等按键） | `_FULLSCREEN`（`:25-30`） |
| 2 | `_tty_flag_block`（`:54-67`） | 带 **TTY 旗标**的容器/编排工具 | `_TTY_TOOLS = frozenset({"docker", "podman", "nerdctl", "kubectl", "docker-compose"})`（`:31`） |
| 3 | `_git_editor_block`（`:86-112`） | **git 会拉起编辑器/分页器**的形态 | `_COMMIT_MSG_RE = re.compile(r"^-[A-Za-z]*[mF]")`（`:34`） |

**闸 3 的两条判据**：

- `_has_commit_style_msg(toks)`（`:68-81`）：token 里出现「以 `-` 开头且含 `m` 或 `F`」的旗标（如 `-m` / `-am` / `-F file`）→ **有提交信息** → **放行**（不会开编辑器）；
- `_has_flag(toks, *flags)`（`:82-85`）：配合判定如 `--no-edit` 一类的「免交互」旗标。

即：`git commit`（无 `-m`）会被拦（会开编辑器），`git commit -m x` 放行。

**入口**（`:113`）：

```python
def precheck_command(command: str) -> tuple[bool, str | None]:
```

返回 `(can_execute, failure_reason)`；`bash_tool.call` 里消费它（`:577-586`）：

```python
		try:
			can_execute, failure_reason = precheck_command(inp.command)
		except Exception:  # noqa: BLE001
			can_execute, failure_reason = True, None
		if not can_execute:
			return BashOutput(
				stdout=fast_fail_message(failure_reason or ""),
				code=1,
				is_error=True,
			)
```

**为什么只拦这三类**（`bash_tool.py:575-576` 注释原文）：

```
		# 预检查：只拦「等 TTY/编辑器会挂」的形态；预检自身异常必须 fail-open，
		# 否则一次正则意外就把整个 Bash 工具打挂（call 是 Bash 唯一执行路径）。
```

即：预检的目标**不是安全**（安全由权限层负责，B07），而是**可用性**——拦「一定会挂住直到超时」的命令，避免把 120s 的预算浪费在一次注定失败的等待上。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的要点是理解**每一层的职责边界**：

| 层 | 负责 | 拦截方式 |
|---|---|---|
| **预检**（本模块） | 可用性：会挂住的形态 | 拒绝执行 + `fast_fail_message` |
| **权限**（B07） | 安全：越权/危险命令 | 三态 allow/ask/deny |
| **破坏性守卫**（0206+） | 可恢复性：删改前快照 | 不拒绝，只留证据 |
| **超时/晋升**（0216） | 资源：时间预算 | 晋升或杀 |

四层各管一件事，**互不越界**——预检不去判「这条命令危不危险」（那是权限层的事），权限层也不去判「这条命令会不会挂」（那是预检的事）。`fast_fail_message`（`bash_tool.py:115-122`）的措辞也体现了这一点：它给的是「**可行动的改法**」，并明确「不提不存在的『绕过旗标』，别诱导模型空转」：

```python
	return (
		"Command blocked by precheck (would hang waiting for a TTY/editor).\n"
		f"Reason: {failure_reason}\n"
		"Fix the command per the reason and retry; if it truly needs a human "
		"in a real terminal, tell the user to run it themselves."
	)
```

**边界**：预检**必须 fail-open**——`bash_tool.call` 里用 `try/except` 包住，异常时 `can_execute = True`。理由直白：「call 是 Bash 唯一执行路径」，预检出 bug 不能把整个工具打挂。这与 `_command_may_mutate_workspace` 的 **fail-closed**（0215）形成鲜明对照——同一文件里两种相反的失败取向，依据是「失败的代价在哪一侧」：

| 功能 | 失败取向 | 因为 |
|---|---|---|
| 缓存失效判定 | fail-**closed**（判写） | 漏清的代价是正确性事故 |
| 命令预检 | fail-**open**（放行） | 误拦的代价是工具整体不可用 |



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

### XEYO-QA-0224 重定向与命令替换的拦截

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | dup_redirect 路由判定 | 元字符拦截 | 中等 | 机制解释 | `python/tools/bash_tool/dup_redirect.py:38-58,218-252` |

**面试官提问**
`dup_redirect.py` 是什么用途？`_METACHARS` 拦截哪些字符？为什么含这些字符的命令不做路由？

**参考答案要点**
**用途**（`:61` 的 `BashRoutePlan` 与 `:218-239` 的入口）：

```python
def plan_bash_route(command: str | None) -> BashRoutePlan | None:
```

```python
def redirect_hint(command: str | None) -> str | None:
```

`plan_bash_route` 判定「一条 Bash 命令是否其实应该用专用工具执行」（对应 AGENTS.md 里的透明路由：`cat`→`Read`、`rg/grep/findstr`→`Grep`），返回一个 `BashRoutePlan`（含 `tier` / `tool_name` / `tool_input` / `brief`）。`redirect_hint` 生成给模型看的提示行。

**元字符拦截**（`:38`）：

```python
_METACHARS = re.compile(r"[|<>;&`^%]|\$\(|\n")
```

覆盖：`|`（管道）、`<` `>`（重定向）、`;`（顺序）、`&`（后台/逻辑）、`` ` ``（反引号命令替换）、`^`（cmd 转义）、`%`（cmd 变量）、`$(`（POSIX 命令替换）、`\n`（多行）。

**为什么含这些字符不路由**：因为路由的前提是「这条命令**语义等价于**一个专用工具调用」。一旦出现元字符，语义就不再是单一读操作：

| 元字符 | 语义变化 |
|---|---|
| `\|` | 输出经过另一个程序处理 → 结果 ≠ 原文 |
| `>` `<` | 有写入或输入重定向 → 不只是读 |
| `;` `&` `\n` | 多条命令 → 一次路由覆盖不了 |
| `` ` `` `$(` | 命令替换可藏任意程序 |
| `^` `%` | cmd.exe 特有的转义/变量语义 |

**另两个判据**：

```python
_DEVICE_NAMES = re.compile(r"^(nul|null|con|prn|aux|lpt[1-9]|com[1-9])$", re.I)
_WILDCARD = re.compile(r"[*?]")
```

- `_DEVICE_NAMES`：目标若是设备名（`nul`/`con` 等）→ 不路由（与 B04-0170 的设备文件防护同源）；
- `_WILDCARD`：含通配符 → **不路由 Glob/文件读类**（因为「通配符展开」的语义由 shell 决定，而路由后的工具会用**自己的**展开规则，结果可能不同）。`:44` 注释即此意。

**深化讲解**（面试官参考，不要求候选人全说）
透明路由的**判定哲学**是「**只路由语义确定无歧义的形态**」：

```
Bash 命令  ──┬─→ 含元字符 / 设备名 / 通配符  →  原样执行（不路由）
             └─→ 纯单一读命令            →  路由到 Read/Grep（并标注 [routed: …]）
```

AGENTS.md 对这条机制的描述与此完全对应：「**透明路由**：Bash 中纯文件读命令且目标在**工作区内**时，引擎直接改用专用工具执行并返回结果」、以及「**明确不路由**：`ls`/`dir`（Glob 对宽匹配 `*` 只回目录摘要、列不出文件名）、`find`（不在 bash 只读白名单，`bash=default` 下先 ASK）；以及目标路径在工作区外、或**带管道/重定向/链式的复合命令** → 原样执行 Bash」。

★ 注意 `_GREP_FLAG_CHARS = frozenset("rRinIEs")`（`:47`）、`_CMD_FLAGS = re.compile(r"^/[ins]$", re.I)`（`:50`）、`_GREP_COMBO = re.compile(r"^-([rRinIEs]+)$"`（`:53`）这三条——它们用于**识别 `grep`/`findstr` 的旗标组合**，判断哪些旗标不影响「输出是匹配行/文件名」这一语义，从而决定能否安全路由到 `Grep`。这属于路由白名单的细粒度部分（`bash=default` 策略下的行为，属 B07 的 Bash 策略面）。

**边界**：路由的**实际执行**（是否真的路由）由 `permissions/policy.py` 与工作区 `.xeyo-policy.json` 的 `bash_routing` 设置决定（AGENTS.md 说明：`"off"` 时回「报错提示」行为，`"auto"` 时透明路由）。本模块只**判定 + 生成计划/提示**，不决定是否执行路由。



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

### XEYO-QA-0225 错误行抢救的契约

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | truncate 中段抢救 | 三条规则 | 中等 | 机制解释 | `python/tools/bash_tool/truncate.py:11-58,90-94` |

**面试官提问**
截断时「从中段抢救错误行」的触发条件是什么？最多抢救多少？超长报错日志怎么处理？

**参考答案要点**
**触发条件**（`truncate.py:90-94`）：

```python
		if middle and not _has_signal_line(tail):
			excerpt = _error_excerpt(middle)
			if excerpt:
				body += excerpt + "\n\n"
```

**两个条件同时成立**：①中段非空；②**尾部没有**高信号错误行（`_has_signal_line(tail)` 为假）。

第二个条件的意思是「**尾部已经能看到错误了就不用再抢救**」——避免重复。

**高信号行的判定**（`:11-21`）：

```python
_ERR_LINE_RE = re.compile(
	r"(?:Traceback|SyntaxError|NameError|TypeError|ValueError|KeyError|"
	r"IndexError|ImportError|ModuleNotFoundError|AttributeError|OSError|"
	r"FileNotFoundError|PermissionError|RuntimeError|AssertionError|"
	r"RecursionError|IndentationError|CompileError|LinkerError|"
	r"undefined reference|No such file|fatal error|collect2:|"
	r"^.*\bE\s+.*|FAILED|failed to (?:build|install|compile)|"
	r"error:|Error:)",
	re.IGNORECASE,
)
```

覆盖三类：**Python 异常名**（19 个）、**编译/链接错误**（`undefined reference` / `fatal error` / `collect2:`）、**测试框架失败标记**（`FAILED` / `E ` 前缀 / `failed to build|install|compile`）、以及通用 `error:` / `Error:`。

**抢救上限**（`:24-25`）：

```python
MAX_ERROR_EXCERPT_LINES = 8
MAX_ERROR_EXCERPT_CHARS = 800
```

**去重与限长**（`_error_excerpt`，`:40-58`）：逐行匹配 → `key = line.strip()` 去重（`seen` 集合）→ 每行 `rstrip()[:200]` → 达到 8 行**或** 800 字符即 `break` → 前缀 `[error excerpt preserved from truncated middle]\n`。

**设计契约**（`:68-73` docstring 原文）：

```
	#13：头部+尾部双向保留（head 20k / tail 8k，中间截断有标记）之外，若**尾部
	没有高信号错误行**，则从中段抢救最多 8 行错误证据拼在截断标记之后——
	防「报错后面又跟了 >8k 成功输出、把关键报错挤出预览」的情况（编译/批量任务
	常见）。契约：模型永远能看到头部 20k、尾部 8k 与（有则）中段错误行。
```

★ 注意契约写的「**永远能看到**」有前提：尾部 8k 内**没有**错误行时才抢救中段。若尾部已有错误行，则「尾部有错误」这个事实已满足契约意图。

**深化讲解**（面试官参考，不要求候选人全说）
这条设计针对的是一个**非常具体的失败模式**：

```
编译输出：
  [错误]  ← 第 500 行
  ...然后 20k 行的成功编译产物...
  [最后的 8k 汇总]
```

此时 head 20k 可能包含错误（若错误在前 20k 内），但**更常见**的是：错误在**中段**（20k–len-8k 之间），而尾部 8k 是无关的汇总。若不抢救，模型会看到「一段成功的尾部输出」而**完全不知道编译失败了**——这是「**信息在截断中被吃掉**」的典型。

所以抢救机制是**针对截断这一有损操作的补偿**：既然必须截，就要保证「**最高价值的证据（错误）有优先通道**」。

**边界**：抢救的 800 字符来自**中段**，这意味着最终给模型的文本可能略超 `HEAD_CHARS + TAIL_CHARS`（20k + 8k + ≤800 + 标记）。这与 0210 提到的「head+tail ≤ 28k < 30k 留余量」正好呼应——**余量就是给这类补偿留的**。



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

### XEYO-QA-0226 registry 桥的三态返回与降级链

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | jobs_bridge 桥接 | 三态语义与依赖方向 | 中等 | 机制解释 | `python/tools/bash_tool/jobs_bridge.py:1-50` + `python/tools/bash_tool/bash_tool.py:588-622` |

**面试官提问**
`start_registry_job` 返回 `None` / `("", err)` / `(job_id, "")` 三态分别代表什么？桥为什么必须**惰性**导入 `server`？

**参考答案要点**
**三态语义**（`jobs_bridge.py:22-28` docstring 原文）：

```python
	"""尝试把命令登记为 42 号后台 job。

	返回：
	- ``None`` —— registry 不可用（无 server / 异常）→ 调用方走旧式后台；
	- ``("", error)`` —— registry 拒绝（容量满 / 无会话上下文）→ 教科书式错误；
	- ``(job_id, "")`` —— 成功。
	"""
```

| 返回 | 含义 | 调用方动作 |
|---|---|---|
| `None` | **registry 不可用**（无 server / 导入失败 / 异常） | 走**旧式日志文件后台**（`background.start_background`） |
| `("", err)` | **registry 拒绝**（容量满 / 无会话上下文） | 打 `warning`，**同样**回退旧式后台 |
| `(job_id, "")` | 成功 | 返回 `BashOutput(background_task_id=job_id, background_job=True)` |

**惰性导入的理由**（`:1-7` 模块 docstring 原文）：

```
"""Bash → JobRegistry 桥（42 号 P0）。

依赖方向约束：``tools/`` 不 import ``server/``（CLI in-process 运行时无 server）。
桥在**调用时**惰性尝试 server.registry；不可用返回 None，BashTool 落回旧式
日志文件后台——server 场景获得 42 号 job 语义（完成通知 / job_output / kill），
纯引擎场景行为逐字节不变。
"""
```

即：**`tools/` 的架构分层不允许依赖 `server/`**。而 `server/job_registry.py` 是 server 侧组件，所以唯一合规的接法是**运行时惰性 import**（`from server.job_registry import get_job_registry` 写在函数体内，`:33`），并在 `except Exception` 时返回 `None`。

**降级链的完整形态**（`bash_tool.py:588-622`）：

```python
		if inp.run_in_background:
			# 42 号：优先登记为 registry job（完成通知 / job_output / job_kill）；
			# registry 不可用（CLI in-process）落回旧式日志文件后台，行为不变。
			bridged = start_registry_job(...)
			if bridged is not None:
				job_id, err = bridged
				if job_id:
					return BashOutput(background_task_id=job_id, background_job=True)
				# registry 可达但登记失败（容量/会话等）：记录并回退旧式日志文件后台。
				_log.warning(
					"bash background: registry job start failed (%s); "
					"falling back to log-file background",
					err,
				)
			# registry 直通路径生产者线程无 rewind ctx（Phase A 已知缺口）；
			# 仅登记失败落回日志文件后台时做 before 快照保护。
			guard_plan = plan_destructive_snapshot(inp.command, run_cwd)
			h = start_background(...)
			return BashOutput(background_task_id=h.task_id, background_log_path=h.log_path)
```

**三条重点**：

1. **两种失败合并到同一条降级路径**（`None` 与 `("", err)` 都走 `start_background`），差别只在是否打 `warning`；
2. **返回值形态不同**：registry 路径返回 `background_job=True`（无 `background_log_path`），旧式路径返回 `background_log_path`（无 `background_job`）——模型/上层可据此区分；
3. ★ **注释里的已知缺口**（`:608-609`）：「registry 直通路径生产者线程无 rewind ctx（**Phase A 已知缺口**）；仅登记失败落回日志文件后台时做 before 快照保护」——即**走 registry 路径的后台命令不做破坏性快照守卫**，只有降级到旧式路径时才做。

**深化讲解**（面试官参考，不要求候选人全说）
第 3 条是本批一个**重要的诚实缺口**：破坏性守卫（0206）依赖 `rewind ctx`（`DestructivePlan.ctx`，见 0218），而 registry 直通路径的**生产者线程没有 rewind 上下文**——所以「后台跑一条 `rm -rf`」在 server 场景下**不会被快照**。这是代码注释主动声明的「Phase A 已知缺口」，不是隐藏缺陷。

对照一下路径矩阵：

| 执行形态 | 破坏性快照 | 理由 |
|---|---|---|
| 前台（`call` 主路径） | ✅ | 有 rewind ctx |
| 后台（registry 直通） | ❌ **已知缺口** | 生产者线程无 rewind ctx |
| 后台（降级为日志文件） | ✅ | 注释说明「仅登记失败落回日志文件后台时做 before 快照保护」 |

所以「后台命令的守卫覆盖面取决于是否走了 registry」——这是一个**运行环境决定的语义差异**（server 场景走 registry，CLI in-process 走日志文件），值得在设计文档里显式记录。



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

### XEYO-QA-0227 命令压缩的四类家族

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | cmd_compact 家族压缩 | 六个压缩器 | 中等 | 机制解释 | `python/tools/bash_tool/cmd_compact.py:17-85,86-370` |

**面试官提问**
`cmd_compact.py` 定义了哪九个家族？实际实现的专用压缩器有几个、分别针对什么？

**参考答案要点**
**九家族**（`:17`）：

```python
_Family = str  # pytest | vitest | cargo_test | go_test | tsc | lint | git | build | unknown
```

**六个专用压缩器**：

| 压缩器 | 位置 | 服务家族 |
|---|---|---|
| `_compact_pytest` | `:86-171` | `pytest` |
| `_compact_test_runner` | `:172-225` | `vitest` / `cargo_test` / `go_test`（**共用**） |
| `_compact_tsc` | `:226-259` | `tsc` |
| `_compact_lint` | `:260-304` | `lint` |
| `_compact_git` | `:305-355` | `git` |
| `_compact_build` | `:356-370` | `build` |

即：**九个家族 → 六个压缩器**（三个 test runner 家族共用 `_compact_test_runner`；`unknown` 无压缩器）。

**入口**（`:55-85`）：

```python
def compact_command_output(command: str, stdout: str) -> str:
```

`detect_family(command)`（`:45-54`）先识别家族，再分派到对应压缩器。

**辅助正则**（`:33-42`）：

```python
_PYTEST_FAIL_START = re.compile(...)      # pytest 失败块起点
_PYTEST_SUMMARY = re.compile(...)          # pytest 统计行
_PASSED_LINE = re.compile(r"(?i)^\s*(?:PASSED|PASS|ok)\b")
_FAILED_LINE = re.compile(r"(?i)^\s*(?:FAILED|FAIL|ERROR)\b")
_TRACE_HINT = re.compile(r"(?i)(traceback|exception|error:|FAILED|FAILURES)")
```

即压缩器靠**行分类正则**工作：把输出行分成「通过/失败/统计/traceback」几类，保留失败与统计、丢掉通过行明细。

**深化讲解**（面试官参考，不要求候选人全说）
「九个家族六个压缩器」这个数字关系说明了压缩策略的**粒度选择**：

- **测试框架**：pytest 有自己独特的输出格式（失败块 + 统计行），需要专用解析；而 vitest/cargo_test/go_test 的输出结构相近（都能用「通过/失败行 + 摘要」模式处理），所以共用一个「通用测试运行器压缩器」；
- **其余**：tsc（编译错误的 `file(line,col): error TSxxxx` 格式）、lint（规则名 + 位置）、git（status/log/diff 的固定格式）、build（编译输出）各成一类。

**边界**：`unknown`（九家族之外）**没有压缩器**，应原样返回——这保证了压缩只作用于「输出格式已知」的工具。加上 `_MIN_CHARS = 4_000`（0214）的下界，压缩的生效面被两重条件限定：**家族已知 + 输出够长**。

★ 一个设计上的一致点：`_compact_git`（`:305-355`）的存在对应 `bash_tool.py:75-79` 的 git 只读子命令白名单——但两者**独立**（一个用于缓存失效判定，一个用于输出压缩）。也就是说 `git` 既在「只读白名单」里（缓存不清），也在「有压缩器」里（输出压缩）——这两个集合的成员不完全重合（例如 `pytest` 有压缩器但不在只读白名单里，因为它会写 `.pytest_cache`）。



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

### XEYO-QA-0228 语义层的结果解读

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | semantics 命令语义 | 三个函数 | 中等 | 机制解释 | `python/tools/bash_tool/semantics.py:10-56` |

**面试官提问**
`semantics.py` 提供哪三个函数？`interpret_command_result` 的作用是什么？

**参考答案要点**
`semantics.py`（100 行）的三个函数：

| 函数 | 位置 | 作用 |
|---|---|---|
| `_split_segment(cmd)` | `:10-14` | 把复合命令切成片段（私有） |
| `extract_base_command(cmd)` | `:15-26` | 取基础命令名（供 `expect_no_output` 等消费） |
| `_git_subcommand(cmd)` | `:27-44` | 取 git 子命令（私有） |
| `interpret_command_result(...)` | `:45-56` | **把执行结果解释成语义**（公开） |

`interpret_command_result` 的签名（`:45`）在本次定义面抽取中可见，其职责是**结合命令与执行结果给出解释**——典型用途是判断「这个退出码 + 这段输出」意味着成功、失败、还是「无输出的成功」（与 `expect_no_output` 的静默集配套，见 0203）。

**深化讲解**（面试官参考，不要求候选人全说）
`semantics.py` 只有 100 行，但它是 Bash 工具的**语义归一化层**——把「shell 命令 + 退出码 + 输出文本」这堆原始事实翻译成「这次调用发生了什么」。这一层的存在意义在于：**shell 的成功/失败语义并不统一**（见 0203）：

| 情形 | 退出码 | 输出 | 正确解读 |
|---|---|---|---|
| `mkdir x` 成功 | 0 | 空 | **成功**（静默命令） |
| `pytest` 全部通过 | 0 | 大段输出 | 成功 |
| `pytest` 有失败 | 1 | 失败详情 | 失败 |
| `grep` 无匹配 | **1** | 空 | **不是失败**，是「无匹配」 |
| `rm -rf x` 成功 | 0 | 空 | 成功 |

最后一行 `grep` 是经典陷阱：`grep` 无匹配返回 **1**，若工具把「非 0 = 失败」一律当错误，模型会以为搜索出错。这正是为什么需要语义层——**退出码要与命令语义一起解读**。

★ 与 `_segment_base`（`bash_tool.py:82-88`）和 `base_command_of`（`timeout_map.py:96-103`）的对比见 0204：三者是「同一概念三种实现」，各自服务不同的映射表形态。

**边界**：`_split_segment` 与 `_git_subcommand` 是私有函数，说明 `semantics` 对外的契约只有 `extract_base_command` 与 `interpret_command_result` 两个——前者被 `expect_no_output` 与 `_command_may_mutate_workspace`（经 `_split_segment`）消费，后者被 Bash 工具的结果渲染消费。



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

### XEYO-QA-0229 净室执行的合成命令

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 净室执行 | `run_isolated` | 中等 | 机制解释 | `python/tools/bash_tool/bash_tool.py:541-559` |

**面试官提问**
`BashInput.run_isolated` 为真时，工具会把命令改写成什么形态？这个改写为什么**必须**用 POSIX 片段？

**参考答案要点**
`bash_tool.py:541-559`（原文）：

```python
		# 禀赋②：净室执行——在只含声明输入的临时目录里跑命令（信息给足，判断归模型）。
		# 组合为 POSIX 片段后随同路由（容器内 mktemp/cp 均可用），与容器路由正交。
		if inp.run_isolated:
			inputs = [p.strip().lstrip("/") for p in inp.isolation_inputs if p.strip()]
			cp_part = ("cp --parents " + " ".join(shlex.quote(p) for p in inputs) + " \"$__iso/\" 2>&1; ") if inputs else ""
			composed = (
				'__iso="$(mktemp -d)"; '
				+ cp_part
				+ 'cd "$__iso" || exit 95; '
				+ "{ " + inp.command + "; __rc=$?; } ; "
				+ 'echo "__ISO_DIR=$__iso"; '
				+ 'echo "__ISOLATED_NEW_FILES:"; find "$__iso" -type f | head -40; exit $__rc'
			)
			inp = BashInput(
				command=composed,
				timeout_ms=inp.timeout_ms,
				run_in_background=inp.run_in_background,
				description=inp.description,
			)
```

**改写后的命令结构**（五步）：

| 步 | 片段 | 作用 |
|---|---|---|
| 1 | `__iso="$(mktemp -d)"` | 建临时目录 |
| 2 | `cp --parents <inputs> "$__iso/" 2>&1;` | 把声明的输入文件按**原相对路径**拷进去（`--parents` 保留目录结构）；无输入则整段省略 |
| 3 | `cd "$__iso" \|\| exit 95` | 进净室；失败则退出码 95 |
| 4 | `{ <原命令>; __rc=$?; }` | 执行原命令并**保存退出码**（花括号保证 `$?` 取到的是原命令的） |
| 5 | `echo "__ISO_DIR=..."` + `echo "__ISOLATED_NEW_FILES:"` + `find "$__iso" -type f \| head -40` + `exit $__rc` | 回传净室路径、列出**产生的新文件**（最多 40 个），并以原命令退出码退出 |

**为什么必须用 POSIX 片段**：注释写明「组合为 POSIX 片段后**随同路由**（容器内 `mktemp`/`cp` 均可用），与容器路由正交」。三个理由：

1. **容器路由的目标环境是 Linux 容器**——宿主是 PowerShell（0220），但 `run_isolated` 的合成命令要能在**容器内的 `bash -lc`** 里跑（`bash_tool.py:220`：`client.containers.get(cid).exec_run(["bash", "-lc", command], ...)`），所以只能用 POSIX；
2. **`mktemp -d` / `cp --parents` / `find` 在容器里可用**（注释直接这么说）；
3. **正交性**：净室改写发生在容器路由**之前**（`:543` 早于 `:568` 的 `cid` 判定），所以两种路由可以叠加而互不干扰。

★ **模型可见的信息**（`:541` 注释「信息给足，判断归模型」）：回传的 `__ISO_DIR=` 让模型知道净室在哪、`__ISOLATED_NEW_FILES:` 列表让它知道产生了哪些文件——**都是事实，没有劝告**。这符合 AGENTS.md 铁律：净室这个限制不通过文本传达，而是通过**实际改变执行环境**达成；文本只报告环境状态。

**深化讲解**（面试官参考，不要求候选人全说）
「净室执行」解决的是**副作用隔离**问题：让一条命令在只含声明输入的临时目录里跑，从而：

- 原工作区**不被修改**；
- 命令能看到的输入是**显式声明的**（而不是整个工作区）；
- 产生的新文件可以被枚举（`find` + `head -40`）供模型判断。

`lstrip("/")` 那一步（`:544`）值得注意：输入路径**去掉前导斜杠**，使 `cp --parents /a/b` 变成 `cp --parents a/b`——因为 `cp --parents` 会把绝对路径的完整层级带到目标目录下（`$__iso/a/b`），去掉前导斜杠让「相对工作区的路径结构」被保留，这正是「按原相对路径拷进去」想要的效果。

**边界**：`2>&1` 挂在 `cp` 后面——拷贝失败的错误信息会进 stdout，与后续输出混在一起（不会静默失败）。`head -40` 限制新文件列表长度（防刷屏；与 `_MAX_GROUPED_FILES = 40` 是不同用途但同样的量级选择）。



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

### XEYO-QA-0230 容器路由的并发防串线

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 容器路由 | ContextVar 优先 | 中等 | 机制解释 | `python/tools/bash_tool/bash_tool.py:195-239,561-573` |

**面试官提问**
容器路由为什么用 **ContextVar** 而不直接用环境变量？不用宿主 shell 拼 `docker exec` 的原因是什么？

**参考答案要点**
**ContextVar 优先的理由**（`bash_tool.py:566-568` 注释原文）：

```python
		# 并发 trial 防串线：ContextVar（每 trial 协程上下文）优先于进程级 env——
		# harbor 多 trial 共进程时后者会被互相覆盖（p4 冒烟实测串线事故）。
		cid = _routed_container() or os.environ.get("XEYO_DOCKER_CONTAINER", "").strip()
```

即：`_routed_container()`（ContextVar 读取）**优先**，环境变量 `XEYO_DOCKER_CONTAINER` 是退路。理由是「harbor 多 trial 共进程时后者会被互相覆盖」——**有实测事故背书**（注释点名「p4 冒烟实测串线事故」）。

| 载体 | 作用域 | 多 trial 共进程时 |
|---|---|---|
| ContextVar | 每个协程上下文（trial）独立 | ✅ 各自看到自己的容器 |
| 进程级 env | 整个进程唯一 | ❌ 后设置的覆盖先设置的 → **串线**（trial A 的命令跑到 trial B 的容器里） |

**不用宿主 shell 拼 `docker exec` 的理由**（`:561-565` 注释原文）：

```python
		# 容器路由（评测适配）：XEYO_DOCKER_CONTAINER 设置时，所有命令经 docker SDK
		# exec_run 直连 named pipe 转发进容器（bash -lc）。之所以不走宿主 shell 拼串
		#（XEYO_BASH_EXEC_PREFIX 的 docker exec … 方案）：Windows 上 pwsh7 -Command
		# 下 docker exec 的 stdout 会静默丢失（实测 rc=0 空输出，模型全程盲打），
		# SDK 走 API 无 shell/TTY/wsl 依赖，输出与退出码可靠。cwd 语义由 WORKDIR 承担。
```

**三条**：①Windows 上 `pwsh7 -Command` 下 `docker exec` 的 stdout **静默丢失**（实测 `rc=0` 空输出，模型「全程盲打」）；②SDK 走 Docker API（named pipe），**无 shell/TTY/wsl 依赖**；③`cwd` 语义由容器 `WORKDIR` 承担（不靠宿主传 `-w`）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于**两条「实测事故 → 设计决策」的因果链**，两条都有具体的观测证据（不是推测）：

| 决策 | 事故证据 | 后果若不改 |
|---|---|---|
| ContextVar 优先于 env | 「harbor 多 trial 共进程时后者会被互相覆盖（p4 冒烟实测串线事故）」 | 并发评测时命令跑进错误的容器 → 结果不可信且难排查 |
| 用 docker SDK 而非 shell 拼串 | 「Windows 上 pwsh7 -Command 下 docker exec 的 stdout 会静默丢失（实测 rc=0 空输出，模型全程盲打）」 | 模型拿到空输出但退出码为 0 → **以为命令成功且无输出** |

第二条尤其严重：`rc=0` + 空输出会被 `semantics.interpret_command_result`（0228）解读为「静默命令成功」——模型会**在完全没看到输出的情况下继续**。这正是「**错误的成功**」这类最危险故障（对照 0221 的 cp1252 顺序问题，同一类型）。

★ `_docker_exec_with_timeout`（`:195-278`）里的 **promote 等价物**（`:202-207`）也值得一提：

```
	promote 等价物（评测路由分支）：promote 阈值（默认 45s，XEYO_BASH_PROMOTE_MS
	可覆盖）内完成 → 直接返回；超时 → 命令转「docker 后台 job」（worker 线程继续
	跑完写入 `_DOCKER_BG_JOBS`），立即把控制权还给模型并告知 job_id——长命令不再
	阻塞回合（复现：p90 间隔 77-407s 的长命令曾把 15 分钟预算吃光）。
```

即容器分支**自己实现了一套晋升机制**（`_DOCKER_BG_JOBS` + `docker_bg_snapshot` + `docker_bg_mark_delivered`，`:286-301`），动机同样有数据：「p90 间隔 77-407s 的长命令曾把 15 分钟预算吃光」。这与宿主侧的 `promote_threshold_ms`（0216）是**并行的两套**——因为容器分支走的是独立的 SDK 执行路径，用不上宿主侧的 `StreamHandle`。

**边界**：模块级 `_DOCKER_BG_LOCK` 与 `_DOCKER_BG_SEQ`（`:23-24`）保护容器后台 job 表；`_docker_promote_seconds()`（`:279-285`）把 promote 阈值换算成秒（并被 `max(1.0, min(promote_s, timeout_ms/1000))` 夹取，`:237-239`）。



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

### XEYO-QA-0231 后台日志的接管与清理

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | background 生命周期 | 三件事 | 中等 | 机制解释 | `python/tools/bash_tool/background.py:19-47,57-130,141-225` |

**面试官提问**
`background.py` 里的 `BackgroundHandle`、`_MergedAbort`、`adopt_background` 分别解决什么问题？

**参考答案要点**
三者的职责（`background.py` 定义面）：

| 组件 | 位置 | 解决的问题 |
|---|---|---|
| `BackgroundHandle`（dataclass） | `:23-27` | 描述一个后台任务的句柄（`task_id` / `log_path` 等）；`bash_tool` 用它返回 `background_task_id` 与 `background_log_path`（`bash_tool.py:619-622`） |
| `_MergedAbort(AbortController)` | `:28-46` | **把多个中止源合并成一个**：让后台任务同时响应「会话级 abort」与「命令级 abort」 |
| `start_background` | `:57-129` | 启动后台任务：spawn + 日志 sink + 超时杀 |
| `adopt_background` | `:141-208` | **接管**：进程重启后把仍在跑的后台任务重新纳入管理 |
| `_append_log` | `:130-140` | 追加写日志（sink 的实现） |
| `_cleanup_old_logs` | `:209-225` | 清理超过 7 天的旧日志（见 0213） |
| `cancel_background` | `:47-56` | 取消一个后台任务 |

**三者各自解决的问题**：

**① `_MergedAbort`（`:28`）**——一个后台任务可能在两种情形下需要停止：会话被中断（用户按了停止 / 回合结束）或显式 kill。它继承 `AbortController`（`engine/abort.py`，B03-0101）并合并多个源的「已中止」状态。这不是简单的 `or`：它要保证**任意一个源中止即整体中止**，且对外仍是一个 `AbortController` 接口（这样 `runner`/`bash_tool` 无需感知多源）。

**② `adopt_background`（`:141-208`）**——**接管**的场景是「XEYO 进程重启后，之前启动的后台任务还在跑」。此时内存里的句柄没了，但进程还在、日志文件还在。接管要做的是：根据日志文件/任务记录重建句柄，把一个新的 sink（继续往同一日志文件追加）挂上去，让任务重新可见、可 kill。

这与 B03 的 `process_ledger.leftovers()`/`reap`/`sweep`（进程账本）属同一族能力——都是「崩溃/重启后的状态收敛」。

**③ `_cleanup_old_logs`（`:209-225`）**——机会式清理（7 天 TTL，见 0213）。

**深化讲解**（面试官参考，不要求候选人全说）
把这四个组件放在一起看，可以看出旧式日志后台的**完整生命周期**：

```
start_background ──→ 运行中（sink 写日志 / _MergedAbort 监听中止）
     │                      │
     │                      ├─→ cancel_background（主动取消）
     │                      ├─→ 超时/中止 → 杀掉
     │                      └─→ 进程重启 → adopt_background（接管回来）
     └─→ 每次启动/接管顺带 _cleanup_old_logs（7 天）
```

★ 为什么需要 `_MergedAbort` 而不是「把两个 abort 传进一个列表」：因为 `runner.spawn_streaming` 的 `abort` 参数是**单个对象**（`:337`），且 `StreamHandle.watch_abort(abort)` 用 `_abort_box` 可变槽管理（0222）。所以「多源」必须在**进入 runner 之前**合并成一个对象——`_MergedAbort` 就是那个适配层。

**边界**：`background.py` 全部依赖 `start_background` 的 `guard_plan` 参数（`bash_tool.py:610-618` 传入 `plan_destructive_snapshot(inp.command, run_cwd)`）——所以**降级到日志后台的后台命令是有破坏性守卫的**（与 registry 直通路径的缺口形成对照，见 0226）。



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

### XEYO-QA-0232 pwsh7 的完整性与安全解压

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | pwsh7 安装 | 校验与解压 | 中等 | 机制解释 | `python/tools/bash_tool/pwsh7.py:33-174` |

**面试官提问**
`download_and_install` 的完整流程有几步？`_extract_zip_safe` 防的是什么？`locate` 与 `ensure` 的分工是什么？

**参考答案要点**
**`download_and_install`（`:114-140`）的流程**：

| 步 | 动作 | 依据 |
|---|---|---|
| 1 | 取哈希：下载官方 `hashes.sha256`（`_HASHES_NAME`） | `:29,46` |
| 2 | 解析哈希：`_parse_hashes_txt(text, _ZIP_NAME)` 按文件名取对应哈希 | `:46-59` |
| 3 | 下载 zip：`_fetch(url)`（`_DOWNLOAD_TIMEOUT_S = 120`） | `:30,106-113` |
| 4 | 校验 + 解压 + 安装：`install_from_zip(zip_path, expected_sha256=...)` | `:83-105` |
| 5 | 清理/落位到 `_cache_root()` | `:33-37` |

**`_extract_zip_safe`（`:60-82`）防的是「zip-slip」**：恶意或畸形的 zip 条目名里含 `../` 或绝对路径时，直接 `extractall` 会把文件写到目标目录**之外**（覆盖系统文件）。安全解压的做法是逐条目检查解析后的真实路径是否仍在目标目录内，否则跳过/拒绝，返回解出的文件名列表。

**`locate` 与 `ensure` 的分工**（`:141-173`）：

| 函数 | 职责 | 是否下载 |
|---|---|---|
| `locate()` | **只查**：在 `_cache_root()` 下找已安装的 `pwsh.exe`，返回 `Path \| None` | ❌ 不下载 |
| `ensure()` | **确保**：没有就装（调 `download_and_install`） | ✅ 会下载 |

这个分工与 0220 的结论直接对应：`runner._resolve_pwsh_exe` 只调 `locate`（每次执行命令时都会被调），`ensure` 由独立入口触发。

**深化讲解**（面试官参考，不要求候选人全说）
整条安装链的安全姿态可以概括为「**钉版 + 哈希 + 安全解压**」三层（见 0211）：

| 层 | 防什么 | 不防什么 |
|---|---|---|
| 钉版（`PINNED_VERSION`） | 版本漂移、行为不可复现 | — |
| 哈希（官方 `hashes.sha256`） | 传输损坏、传输链路篡改 | **整个 release 被替换**（哈希与 zip 同源） |
| 安全解压（`_extract_zip_safe`） | zip-slip 路径逃逸 | 解压后文件的进一步篡改 |

★ 第三层的必要性容易被低估：`zipfile.ZipFile.extractall()` 在 Python 里**确实**会受条目名中的 `..` 影响（历史上的 CVE 类问题），因此「下载并解压一个远程 zip」这个动作**必须**自己校验条目路径。这是「**从网络取可执行文件**」这类操作的必备环节——即使哈希校验通过（哈希只能证明「这个 zip 是我期待的那个」，而如果官方 zip 本身有恶意条目，哈希通过也无济于事；当然官方 zip 不会有，但防御性是针对「万一」）。

**边界**：`_sha256_file`（`:38-45`）分块计算哈希（不把整个 zip 读进内存）——因为 zip 有几十 MB。`expected_sha256` 参数允许调用方传入**外部钉死的哈希**（补上「release 被替换」这一层，见 0211）。



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
### XEYO-QA-0233 白名单片段解析的绕过面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 写判定绕过 | 可藏写的三类形态 | 困难 | 场景设计 | `python/tools/bash_tool/bash_tool.py:91-112` |

**面试官提问**
`_command_may_mutate_workspace` 只做**词法级**判定。请指出它能被「一条实际会写盘、却被判为只读」的命令绕过的**三种形态**，并说明为什么每种都（或都不）被现有防线覆盖。

**参考答案要点**
**三种可藏写的形态**：

**① 命令替换（已覆盖）**：`echo $(python write.py)`

```python
	if "$(" in command or "`" in command:
		return True  # 命令替换可藏任意写
```

`echo` 在 `_PURE_READ_BASES` 里（`:67`），但第 4 步在切片白名单**之前**拦住了 `$(`/反引号。**已覆盖**，且注释直接写明动机「命令替换可藏任意写」。

**② 多行命令（已覆盖，粗粒度）**：

```python
	if not command or not command.strip() or "\n" in command:
		return True  # 空/多行不可解析 → fail-closed
```

`ls\nrm x` 的第一段是只读命令，但**含换行即判写**。**已覆盖**（`tests/test_glob_optimize.py:517` 有对应断言）。

**③ 只读程序被用作写载体（未覆盖）**——这是本题真正要找的：

| 命令 | 表面 | 实际 |
|---|---|---|
| `find . -delete` | `find` 在 `_PURE_READ_BASES` 里（`:66`） | `-delete` 会**删除文件** |
| `find . -exec rm {} \;` | 同上 | `-exec` 跑任意程序 |
| `tee out.txt` | 不在白名单 → 已拦 | — |
| `sed -i s/a/b/ f.py` | `sed` **不在**白名单 → 已拦 | — |
| `git branch -D x` | `git` 子命令 `branch` 不在 `_GIT_READ_SUBS` → 已拦 | — |
| `sort -o out.txt in.txt` | `sort` 不在白名单 → 已拦 | — |

关键在于 `find` **在**白名单里，而 `find` 同时支持 `-delete`、`-exec`、`-fprint`（写文件）等**写操作**。所以 `find . -name '*.log' -delete` 会被判为「只读」→ **缓存不清**。

同类还有 `sort`（不在白名单，已拦）之外的两个白名单成员值得检查：

| 白名单成员 | 可写选项 | 是否被现有防线拦 |
|---|---|---|
| `find` | `-delete` / `-exec` / `-fprint` / `-fls` | ❌ 不拦 |
| `tree` | `-o file`（输出到文件） | ❌ 不拦 |
| `diff` | `--output=file` | ❌ 不拦 |
| `xxd` | `xxd in out`（第二位置参数是输出文件） | ❌ 不拦 |
| `od` | 无写选项 | — |
| `iconv` | `-o outfile` / 位置参数输出 | ❌ 不拦 |

也就是说：**白名单是「程序级」的，而这些程序里有「选项级」的写能力**——判定的粒度不匹配。

**为什么第 2 步拦不住它们**：第 2 步调 `permissions.policy.bash_writes_file(command)`（`:96-99`），它面向**显式写特征**（重定向/写命令/解释器带写标记）。`find . -delete` 既没有重定向、程序名也不在写命令表里——**特征不显式**，所以第 2 步返回假。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值是**精确定位防线的粒度错配**：判定在「基础命令名」这一层做（`_segment_base` → `_PURE_READ_BASES`），但这些程序**在同一条命令内部**有只读与可写两种模式。

受影响的范围有多大？需要同时满足：①基础命令在白名单；②带写选项；③该写会改变**搜索结果**（即 `.gitignore`/缓存真正关心的内容）。实际影响举例：

- `find . -name '*.tmp' -delete` 删掉一批文件 → Glob 在 60s 内仍列出它们（**这就是缓存失效要防的幽灵**）；
- `tree -o tree.txt` 写一个新文件 → Glob 看不到它（同上）。

**误判方向**：这里是「**判为只读但实际写**」——即 0215 注释里说的「**漏清是正确性事故**」。所以它不是「保守主义过头」，而是**保守主义不够**。

**修复方向（只描述方向）**：①在这份白名单上补一层「**危险选项表**」（`find -delete/-exec/-fprint/-fls`、`tree -o`、`diff --output`、`iconv -o` 等），命中即判写；②或把粒度从「基础命令」提升为「基础命令 + 选项集」（对白名单成员逐个定义「只读选项集」，未列出的选项一律判写）——后者更彻底但表更大；③最小改动是在 `_command_may_mutate_workspace` 里加一条「白名单成员 + 含任一危险 token → 判写」的检查，与现有的「命令替换」检查同级。**本批列为待确认项**（需确认是否有上层机制覆盖这些形态，例如权限层的 `bash_writes_file` 是否已含 `-delete` 特征）。



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

### XEYO-QA-0234 破坏性守卫的黑名单边界

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 覆盖边界 | 三个缺口 | 困难 | 场景设计 | `python/tools/bash_tool/destructive_guard.py:54-71,130-182` |

**面试官提问**
`DESTRUCTIVE_PROGRAMS` 是**黑名单**。请指出三个「会删除/破坏工作区文件、但不在清单里」的形态，并说明每个缺口的原因。

**参考答案要点**
**缺口一：解释器内删除**——`python -c "import shutil; shutil.rmtree('build')"`

- 程序名是 `python`，不在 `DESTRUCTIVE_PROGRAMS`；
- `_targets_in_segment` 只对 `DESTRUCTIVE_PROGRAMS` 里的程序提取目标（`:162-163`：`if prog not in DESTRUCTIVE_PROGRAMS: return []`），所以**返回空目标**；
- `_plan` 里 `if not raw_targets: return None`（`:242-243`）→ **整条命令不保护**。

注意这一条**同时**会让缓存失效判定失效吗？不会——`python` 不在 `_PURE_READ_BASES`，所以 0215 那条链**会判写并清缓存**。也就是说：**缓存清得对，但快照不做**。两个系统的覆盖面不同。

**缺口二：截断而非删除**——`Set-Content -Path f.txt -Value ""` / `> f.txt`（空重定向）

- 清单定义的是「删除/移动」（`:54` 注释：「破坏性程序名」），**不含截断**；
- `_REDIR_TOKENS`（`:71`）出现在 `_targets_in_segment` 里，但它只用于**跳过**重定向目标（`:171-173`），不是把它当破坏目标；
- 所以「把一个 500 行的文件清空」不被快照——而它**同样是不可逆的数据丢失**。

**缺口三：通过别名/包装程序删除**——`Remove-Item` 已被覆盖（清单含 `remove-item` 与 `ri`，见 0207），但：

| 形态 | 是否覆盖 | 原因 |
|---|---|---|
| `ri x` | ✅ | 在清单里 |
| `rmdir /s /q x` | ✅ | `rmdir` 在 Windows 家族 |
| `robocopy src dst /MIR` | ❌ | `robocopy` 不在清单；`/MIR` 会**镜像删除**目标目录里的多余文件 |
| `rsync -a --delete src/ dst/` | ❌ | `rsync` 不在清单；`--delete` 删除目标侧多余文件 |
| `git clean -fdx` | ❌ | 程序名是 `git`（不是破坏性程序），且它在 `_GIT_READ_SUBS` **之外** → 缓存会清（0215 判写），但**快照不做** |
| `git checkout .` / `git restore .` | ❌ | 同上——**丢弃未提交改动**，是极高风险的不可逆操作 |

★ `git clean -fdx` / `git checkout .` / `git restore .` 这三个是**最值得注意的缺口**：它们能一次性丢弃工作区里所有未提交改动，风险等级不低于 `rm -rf`，但因为「程序名是 `git`」而不进破坏性清单。而 `git` **在** `_PURE_READ_BASES` 里（`:73`），所以 0215 的判定会走子命令白名单：`clean`/`checkout`/`restore` **不在** `_GIT_READ_SUBS` → 判写 → **缓存会清**。所以系统知道「这条命令可能改工作区」，却**不做快照**。

**深化讲解**（面试官参考，不要求候选人全说）
三个缺口的**共同结构性原因**是：**破坏性清单以「程序名」为键**，而这些形态的破坏性**不在程序名上**：

| 破坏性载体 | 键所在层 |
|---|---|
| `rm` / `del` | 程序名 ✅ |
| `python -c ...` | **解释器内容**（字符串参数） |
| `> f` | **重定向**（`_REDIR_TOKENS` 只用于跳过） |
| `git clean` | **子命令**（0215 有子命令层，但因为只要判「是否写」而不判「是否破坏」，没有复用） |
| `robocopy /MIR` | **选项** |

对照看：0215 的缓存判定链已经**答对了「这条命令可能写」**（解释器/非白名单 git 子命令都判写）——它缺的只是「写得多严重」这个信息。所以**一个可能的改进方向**是把 0215 的分类结果**复用**到守卫上：`git clean` 已被判为「写」，如果守卫能按「写 + 危险子命令」做快照，缺口三就补上了。这是本批提出的**结构性方向**（而非逐条补黑名单）。

★ 但要注意 0215 的取向是 **fail-closed 判「可能写」**（任何非白名单命令都判写），所以直接复用它会导致「几乎所有命令都做快照」——开销不可接受（受 0206 两个上限保护，但仍会频繁触发）。所以更现实的方案是在两者之间加**第三级分类**（如「只读 / 写 / 破坏性」三档），而不是简单复用。



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

### XEYO-QA-0235 快照结算的两条结局

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 结算 | 幂等与状态选择 | 困难 | 场景设计 | `python/tools/bash_tool/destructive_guard.py:146-153` + `program/tools/bash_tool/destructive_guard.py:346-364` |

**面试官提问**
`settle_destructive_plan(plan, executed)` 做了什么？为什么「被中断/超时的命令」要按 `completed` 结算？幂等性怎么保证？

**参考答案要点**
`destructive_guard.py:346-364`（原文）：

```python
def settle_destructive_plan(plan: DestructivePlan | None, *, executed: bool) -> None:
	"""命令有结局后结算 started 操作。executed=False → cancelled。fail-open。

	被中断/超时的命令仍按 completed 结算：破坏可能已部分发生，
	「恢复到 before 快照」依旧是正确的逆操作。
	"""

	if plan is None or plan.settled:
		return
	with plan._settle_lock:
		if plan.settled:
			return
		plan.settled = True
	status = "completed" if executed else "cancelled"
	for op_id in plan.operation_ids:
		try:
			plan.ctx.journal.transition_operation(op_id, status)
		except Exception:  # noqa: BLE001 — 单条失败不影响其余结算
			_log.warning("destructive guard settle failed for %s", op_id, exc_info=True)
```

**做什么**：把 plan 里的每个 `operation_id` 通过 `plan.ctx.journal.transition_operation(op_id, status)` **从 `started` 迁移到终态**（`completed` 或 `cancelled`）。这是 rewind 日志（B11）的状态机推进——不结算的话，操作会永远停在 `started`。

**为什么中断/超时也按 `completed`**（docstring 原文）：「破坏可能已部分发生，『恢复到 before 快照』依旧是正确的逆操作」。

这一条是本题的核心：直觉上「命令被杀了 = 没执行成功 = cancelled」，但**破坏性操作的语义不是「成功/失败」而是「是否可能已发生」**：

| 情形 | 实际后果 |
|---|---|
| `rm -rf big_dir` 被 45s 超时杀掉 | 目录**已经删了一部分** |
| `rm -rf` 秒级完成但输出被中断 | 删除**已完成** |
| 命令因预检被拒（未执行） | 什么都没发生 → `executed=False` |

所以 `executed` 这个参数名的含义是「**命令是否真的被执行过**」（而不是「是否成功」）。被杀的命令**执行过**，所以按 `completed` 结算——而 `completed` 的语义是「这次操作有既成事实，回溯时应当恢复到 before 快照」。

★ 这与 B03 已确立的一条结论同源：**「恢复」的判据是「是否有既成事实」，不是「是否成功」**。

**幂等性三层**：

```python
	if plan is None or plan.settled:      # ① 快路径：已结算直接返回
		return
	with plan._settle_lock:                # ② 加锁
		if plan.settled:                   # ③ 双检：锁内再查一次
			return
		plan.settled = True
```

① 是**快路径**（无锁，避免已结算时也去抢锁）；②③ 是**双检锁**（double-checked locking）——`_settle_lock` 定义在 `DestructivePlan` 上（`:98-100`，`repr=False, compare=False` 标记为「不算状态的状态」）。

**逐条容错**：每个 `op_id` 的迁移**各自 `try/except`**，单条失败只打 warning 不中断——理由写明「单条失败不影响其余结算」。这是正确的：已 `settled = True` 已置位，若中断在中间，剩余 op 将**永远不会被结算**。

**深化讲解**（面试官参考，不要求候选人全说）
这道题体现的是**「结算」这个动作的两条硬要求**：

| 要求 | 实现 |
|---|---|
| **必须发生**（否则操作永远停在 `started`） | `plan is None or plan.settled` 之外无条件执行；逐条容错保证尽量多结算 |
| **只能发生一次**（重复迁移会破坏日志状态机） | `settled` 标志 + 双检锁 |

而 `executed` 的语义选择（「是否执行过」而非「是否成功」）决定了**恢复的正确性**：若被杀的命令按 `cancelled` 结算，回溯系统就会认为「这次删除没发生」→ **不提供恢复** → 用户丢了文件还找不到恢复点。所以这里的选择不是「保守」，而是**唯一正确的选择**。

**边界**：`plan.ctx` 可能为 `None`?——不会：`_plan` 里 `if ctx is None or not ctx.enabled: return None`（`:234-235`），所以有 plan 就有可用的 ctx。而 `plan.ctx.journal` 的 `transition_operation` 若不存在会抛 `AttributeError`，被 `except Exception` 吞掉并打 warning。



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

### XEYO-QA-0236 `_decode` 三级回退的代价

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | runner 解码 | 「错误的成功」与逐块代价 | 困难 | 代码阅读 | `python/tools/bash_tool/runner.py:91-105,224-239` |

**面试官提问**
`_decode` 被 `_pump` 逐行调用。请分析：①这套三级回退在什么情况下会给出**错误但不报错**的结果？②逐块解码相比整段解码有什么代价与收益？

**参考答案要点**
**①「错误的成功」**：

```python
	for codec in ("utf-8", "gbk", "cp1252"):
		try:
			return data.decode(codec)
		except UnicodeDecodeError:
			continue
```

回退链的每一步都是「**能解出就返回**」。问题在于 `cp1252` 的**覆盖率**：它把 `0x00–0xFF` 里绝大多数字节都映射到某个字符（只对 5 个字节未定义），所以**几乎任何字节序列都能被 cp1252 解开**。

由此产生两类「错误的成功」：

| 实际编码 | 字节特征 | utf-8 | gbk | cp1252 | 结果 |
|---|---|---|---|---|---|
| UTF-16LE 输出 | 含大量 `0x00` | ❌（`0x00` 合法但后续组合常失败） | 可能**成功**（把 `0x00` 映射到某字符） | — | **GBK 乱码但不报错** |
| Big5 / Shift-JIS | 非 GBK | ❌ | ❌（多数失败） | ✅ | **西欧乱码但不报错** |
| GBK | GBK 双字节 | ❌ | ✅ | — | 正确 |

第二类是设计上接受的（项目主要面向中文环境，cp1252 只是最后兜底）；**第一类才是真问题**：UTF-16 输出（某些 Windows 原生命令会输出 UTF-16LE）里的 `0x00` 字节会被 GBK **成功**解成字符，产生**看似正常的乱码**，而**没有任何错误信号**回传给模型。

★ 也就是说：回退链的**风险不在「解不开」而在「用错的编码解开」**——这与 0221 讨论 cp1252 顺序问题是同一类型，只是这里连 GBK 也会「错误地成功」。

**② 逐块解码的代价与收益**：

`_pump`（`:224-239`）：

```python
			for raw in self.proc.stdout:  # type: ignore[union-attr]
				text = _decode(raw)
```

是**按行**（`for raw in self.proc.stdout` 迭代文本行——注意 `Popen` 用了默认文本模式参数？实际上 `spawn_streaming` 未设 `text=True`，见 `:345-353`，所以 `proc.stdout` 是**二进制**流，按 `\n` 切分）解码。

| 维度 | 逐块（现状） | 整段（若改） |
|---|---|---|
| **收益**：多编码混用 | ✅ 同一份输出里 GBK 行与 UTF-8 行能各自正确解码 | ❌ 只能选一种编码，另一种全乱 |
| **收益**：流式输出** | ✅ 每行到手即可分发 sink（后台日志实时可见） | ❌ 必须等进程结束才能解码 |
| **代价**：跨块多字节字符 | ⚠️ 若一个字符的字节被切在两块之间则会解错 | ✅ 不会 |
| **代价**：开销 | ⚠️ 每行三次 `decode` 尝试（异常开销） | 一次 |
| **代价**：`errors` 粒度 | 每行独立判定 | 整体判定 |

★ 「跨块多字节字符」这一条在**按 `\n` 切分**的前提下**通常不成问题**：UTF-8 的多字节序列里不含 `0x0A`（续字节范围 `0x80–0xBF`，首字节 `0xC2–0xF4`），GBK 双字节的第二字节范围是 `0x40–0xFE`（**含 `0x0A`？**——GBK 第二字节范围是 `0x40–0x7E` 与 `0x80–0xFE`，**不含 `0x0A`**）。所以在「按 `\n` 切分」下，两种编码的字符都不会被切断。**这个前提容易被忽略**：若将来改成按固定字节块读，跨块切断就会成为真问题。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的通用教训是「**多级回退的每一步都必须问『它失败吗』和『它错得很像对吗』**」。一个几乎不会失败的兜底编码（cp1252）在链尾是安全的（只有前面的都失败才用它），但在链中/链首就会**吞掉**本该由后续编码正确处理的字节。

而「逐块解码」这个选择的**真正理由**其实是**流式性**（收益表第 2 行）：后台任务的日志要实时可见（`on_output` sink 逐行回调，`runner.py:420-421` 注释「on_output：提供时逐行回调输出（后台任务实时写 log），不积压 PIPE」），而整段解码就必须等到进程结束。所以「逐块」不是为多编码混用而选的（那是副产品），而是**为流式性**。

**边界**：`if not data: return ""` 处理空块（迭代二进制流时可能出现空行对应的 `b"\n"`，不会为空；空块来自 read 边界）；最终 `data.decode("utf-8", errors="replace")` 是**永不失败**的兜底，保证返回类型恒定——但如上所述，cp1252 几乎不会失败，所以它很少被执行到。



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

### XEYO-QA-0237 超时分级与 worker 护栏的互斥

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | timeout_map 与 worker | 两类超时的边界 | 困难 | 场景设计 | `python/tools/bash_tool/timeout_map.py:1-15` + `python/tools/bash_tool/bash_tool.py:176-178` |

**面试官提问**
命令族映射（180–420s）与 worker 上限（30s/60s）会同时生效吗？为什么 worker 必须**排除**命令族映射？

**参考答案要点**
**不会同时生效——worker 模式被显式排除**。

`timeout_map.py:8-10`（docstring 原文）：

```
- 只影响**模型未显式传 timeout** 时的默认值；显式 timeout 仍由 clamp 决定；
- worker（子 Agent）模式**不生效**（worker 30s/60s 上限是刻意的花钱护栏，
  不被命令族覆盖——``parse_input`` 侧已排除）；
```

worker 侧常量（`bash_tool.py:176-178`）：

```python
# Phase 2 工人 Bash：更短默认/上限，防测挂烧钱（可用 XEYO_WORKER_BASH_TIMEOUT_MS 覆盖默认）。
WORKER_BASH_DEFAULT_TIMEOUT_MS = 30_000
WORKER_BASH_MAX_TIMEOUT_MS = 60_000
```

| 模式 | 默认 | 上限 | 命令族映射 |
|---|---|---|---|
| 主 agent | 120_000 | 600_000 | ✅ 生效（180–420s） |
| **worker（子 Agent）** | **30_000** | **60_000** | ❌ **不生效**（`parse_input` 侧排除） |

**为什么 worker 必须排除**：docstring 说得直白——「worker 30s/60s 上限是**刻意的花钱护栏**」。子 Agent 是**并发**的（多个 worker 同时跑），所以：

1. **成本是乘性的**：一个主 agent 的一次命令最长 600s；若有 N 个 worker 各跑 600s，总成本是 N 倍。30/60s 把**单个 worker 的时间预算**压到很小，从而压住总体上限；
2. **worker 的可中断性更差**：worker 由父 agent 发起，父 agent 可能在等它——一个挂住的 worker 会连带拖住父 agent 的回合（这正是「防测挂烧钱」）；
3. **命令族映射的假设不成立**：映射假设「这条命令在**本机**值得等 300s」（如 `pip install`）。但在 worker 场景（常见于评测/批量任务），**宁可让 worker 超时失败**也不愿为一个子任务烧掉几分钟——因为父 agent 可以换策略（用别的命令、或上报失败）。

★ 排除位置在 **`parse_input`**（`bash_tool.py:401-448`）——也就是说，是**解析入参的阶段**就决定「不用映射」，而不是在 `call` 里再判断。这种「在入口处分流」的做法让后续代码无需关心模式差异。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的通用教训是「**同一个参数在不同执行上下文下应有不同的默认值与上限**」，而且**上下文的优先级高于命令特征**：

```
超时决定优先级（高 → 低）：
  显式 timeout（模型指定，仍受 clamp）
    ↓
  worker 护栏（30s/60s）        ← 上下文优先
    ↓
  命令族映射（180–420s）        ← 命令特征
    ↓
  全局默认（120s）
```

注意「**显式 timeout**」排在最上面：即使 worker 模式，模型显式传 `timeout=300000` 也会被 `clamp_timeout_ms` 夹到 60_000（worker 上限）——所以 worker 的上限是**硬护栏**，连显式指定也越不过。这与 0202 的「`MAX_TIMEOUT_MS` 是硬顶」是同一套「**上限不可协商**、只有默认值可调」的结构。

**边界**：`XEYO_WORKER_BASH_TIMEOUT_MS` 可覆盖**默认值**（30s），注释只说「覆盖默认」，而 `WORKER_BASH_MAX_TIMEOUT_MS = 60_000` 的**是否可覆盖未在注释中说明**——本批列为待确认项（需确认上限是否也是环境变量可调，这关系到「花钱护栏能否被绕过」）。



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

### XEYO-QA-0238 压缩与错误保真的张力

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | cmd_compact 保真 | 保真不变式与其盲区 | 困难 | 场景设计 | `python/tools/bash_tool/cmd_compact.py:13-15,55-83` + `bash_tool/prompt.py:22` |

**面试官提问**
输出压缩是**有损**的。代码里有一条「**保真不变式**」用来兜住「失败信息不被压掉」——它在哪、怎么实现的？这条不变式在什么情况下会失效？

**参考答案要点**
**承诺**（`bash_tool/prompt.py:22`）：「Noisy test/build/git stdout is compacted for the model; **failures are kept**.」

**保真不变式**在 `compact_command_output`（`cmd_compact.py:55-83`，原文）：

```python
def compact_command_output(command: str, stdout: str) -> str:
	"""返回给模型看的压缩文本；不改原命令、不落盘。"""
	text = stdout if stdout is not None else ""
	if len(text) < _MIN_CHARS:
		return text
	family = detect_family(command)
	if family == "unknown":
		return text

	handlers: dict[_Family, Callable[[str], str]] = {
		"pytest": _compact_pytest,
		"vitest": _compact_test_runner,
		"cargo_test": _compact_test_runner,
		"go_test": _compact_test_runner,
		"tsc": _compact_tsc,
		"lint": _compact_lint,
		"git": _compact_git,
		"build": _compact_build,
	}
	handler = handlers.get(family)
	if handler is None:
		return text
	compacted = handler(text)
	if compacted == text:
		return text
	# 失败夹具必须仍含错误信号
	if _TRACE_HINT.search(text) and not _TRACE_HINT.search(compacted):
		return text
	return compacted.rstrip() + f"\n\n[compacted {family}]"
```

**不变式就是最后那个 `if`**：

```python
	if _TRACE_HINT.search(text) and not _TRACE_HINT.search(compacted):
		return text
```

读法：**「原文含有错误信号，而压缩后没有了 → 放弃压缩，返回原文」**。这是一个**事后校验 + 回滚**的设计：先压缩，再检查「错误信号是否被压掉」，若是则**整段回到原文**。

`_TRACE_HINT`（`:42`）：

```python
_TRACE_HINT = re.compile(r"(?i)(traceback|exception|error:|FAILED|FAILURES)")
```

**五条前置早退**（任一成立即返回原文）：输出为空/短于 `_MIN_CHARS = 4_000`；家族为 `unknown`；家族在 dict 里但 `handlers.get` 为 `None`（防御性）；压缩结果与原文本相同；**不变式命中**。

**这条不变式的失效面**——它的强度取决于 `_TRACE_HINT` 的**召回**：

| 失败形态 | `_TRACE_HINT` 是否命中 | 后果 |
|---|---|---|
| Python traceback | ✅ `traceback` | 受保护 |
| pytest `FAILED` / `FAILURES` | ✅ | 受保护 |
| 通用 `error:` | ✅ | 受保护 |
| 自定义/框架专属 `ERROR: ...` | ✅（`error:` 大小写不敏感） | 受保护 |
| **`npm ERR! ...`** | ❌ **不匹配** | **不受保护**——若压缩器把它压掉，不变式不触发 |
| **`2 failed, 3 passed`（无 `FAILED` 大写）** | ⚠️ 取决于大小写（`re.I` 使它匹配 `failures` 但 `failed` 不在模式里） | 需实测 |
| **中文/符号失败（`✗ 检查失败`）** | ❌ | 不受保护 |
| **`cargo` 的 `error[E0308]`** | ✅ `error:`?（`error[` 不含冒号） | ⚠️ 需实测 |
| **非零退出码 + 无匹配行的静默失败** | ❌ | 不受保护 |

所以不变式的准确表述是「**已识别的错误信号不会被压掉**」——`_TRACE_HINT` 的**模式外的失败**没有这层保护。

**深化讲解**（面试官参考，不要求候选人全说）
★ 这个「事后校验 + 回滚」的设计比「靠保留规则尽量不丢」强得多：

| 策略 | 保证 |
|---|---|
| 只靠保留规则（pressure：保留 FAILED 行） | 规则漏了 → **静默丢失** |
| **事后校验**（本模块） | 只要 `_TRACE_HINT` 能看见错误，**要么错误留着、要么整段不压** |

它的代价是「压缩可能白做」（回滚到原文 = 全量输出），但这是**正确方向的代价**：宁可多给模型一段长输出，也不让它看不到错误。这与 0225 的**中段错误抢救**是同一理念的两种实现（一个在压缩层做校验回滚，一个在截断层做主动抢救）。

★ 还有一处**附注标记**：压缩成功时追加 `[compacted {family}]`（`:83`）——模型能知道「这段是压缩过的」。这是「事实型标注」（不说「已为你精简」之类的劝告语），符合 AGENTS.md 的文案纪律。

**边界**：`compacted.rstrip()` 去掉尾部空白后再加标记；`detect_family` 用 `_CMD_PATTERNS` 的**正则列表**逐个 `search`（`:45-52`），首个命中即返回家族名——所以家族的识别是**整条命令串的正则匹配**（不是只看首词），比 0204/0209 的「base command」粒度更宽（见 0244）。



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

### XEYO-QA-0239 预检 fail-open 与执行层 fail-closed 的分工

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 双取向 | 同一文件的两种失败取向 | 困难 | 场景设计 | `python/tools/bash_tool/bash_tool.py:575-586` + `:91-112` |

**面试官提问**
同一个 `bash_tool.py` 里有两处失败取向相反：`_command_may_mutate_workspace` 是 **fail-closed**（判写），`precheck_command` 的调用处是 **fail-open**（放行）。请论证两者为什么必须相反，以及「取向」在这里到底指什么。

**参考答案要点**
**两处代码**（对照）：

`bash_tool.py:91-101`（fail-closed）：

```python
	if not command or not command.strip() or "\n" in command:
		return True  # 空/多行不可解析 → fail-closed
	try:
		from permissions.policy import bash_writes_file

		if bash_writes_file(command):
			return True  # 显式写特征（重写/写命令/解释器带写标记）
	except Exception:
		return True  # 分类器不可用 → fail-closed
```

`bash_tool.py:575-586`（fail-open）：

```python
		# 预检查：只拦「等 TTY/编辑器会挂」的形态；预检自身异常必须 fail-open，
		# 否则一次正则意外就把整个 Bash 工具打挂（call 是 Bash 唯一执行路径）。
		try:
			can_execute, failure_reason = precheck_command(inp.command)
		except Exception:  # noqa: BLE001
			can_execute, failure_reason = True, None
		if not can_execute:
			return BashOutput(
				stdout=fast_fail_message(failure_reason or ""),
				code=1,
				is_error=True,
			)
```

**「取向」指的是什么**（本题的关键概念）：它指的是「**当判定机制本身失效时，默认落在哪一侧**」——不是「正常情况下更倾向哪个答案」。两者的正常判定都很精确（0215 的白名单链、0223 的三道闸）；差异只在**异常路径**。

**为什么必须相反**——比较两个方向的代价：

| 机制 | 失效方向 | 后果 | 可逆性 |
|---|---|---|---|
| 缓存失效判定 | 误判为「只读」（fail-open） | 写操作后 60s 内 Glob/Grep 看不到改动 → **模型基于错误事实继续工作** | ❌ 不可逆（错误事实已被消费） |
| 命令预检 | 误拦（fail-closed） | 命令被拒 → **整个 Bash 工具在特定命令上不可用** | ✅ 可逆（换写法/加 `-m` 重试） |

★ 判据可以概括为**「失败发生在事实层还是执行层」**：

- 缓存判定影响的是**事实的正确性**（模型看到的文件列表/搜索结果）——错误会被下游消费且无法追回，所以必须**宁可多清**；
- 预检影响的是**动作的可行性**（这条命令能不能跑）——错误只是让一条命令失败，模型可以改写法或换工具，所以必须**宁可放行**。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于**破除一个常见误读**：「保守」不是一种风格，而是**依代价方向逐个决定**的。同一个文件里出现相反的取向，恰恰说明作者是**按代价算的**而不是按口味选。

三处对照（本批已读到的）：

| 位置 | 取向 | 依据（代价不对称的方向） |
|---|---|---|
| `_command_may_mutate_workspace`（`:91-112`） | fail-closed | 漏清的代价是正确性事故，误清的代价是 ~140ms 重建 |
| `precheck_command` 调用处（`:575-580`） | fail-open | 误拦的代价是整个工具不可用，放行的代价是一次注定超时的等待 |
| `plan_destructive_snapshot`（`destructive_guard.py:220-224`） | **fail-open** | 「保护失效绝不能拖垮 Bash 工具」 |

第三处值得单独看（`:220-224`）：

```python
	try:
		return _plan(command, cwd, ctx)
	except Exception:  # noqa: BLE001 — fail-open：保护失效绝不能拖垮 Bash 工具
		_log.warning("destructive guard plan failed; fail-open", exc_info=True)
		return None
```

它的取向是 **fail-open**——理由是「保护失效不能拖垮工具」。注意这里的选择与「保护」这个词听起来相反（保护类机制似乎该 fail-closed），但代价计算支持它：**快照失败 → 失去恢复能力**（可逆性下降），**快照机制拖垮工具 → 完全不可用**（严重得多）。

所以**三处取向的依据统一为一条**：**「失效后果更接近『不可用』还是『不准确』」**——前者取 fail-open（保可用），后者取 fail-closed（保准确）。



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

### XEYO-QA-0240 Job Object 双保险为何不互相取代

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | win_job + runner 双机制 | 互补而非冗余 | 困难 | 场景设计 | `python/tools/bash_tool/runner.py:62-88` + `python/tools/bash_tool/win_job.py:25-93` |

**面试官提问**
Windows 上杀进程树有**两套**机制：`taskkill /T /F` 与 Job Object（`KillOnJobClose`）。它们是冗余还是互补？为什么 `_kill_process` 明确**不调用** `TerminateJobObject`？

**参考答案要点**
**是互补，不是冗余**——两套机制覆盖的是**不同触发时机**：

| 机制 | 触发条件 | 依赖 | 覆盖场景 |
|---|---|---|---|
| `taskkill /PID <pid> /T /F` | **XEYO 主动调用** | XEYO 进程活着、`taskkill.exe` 可用 | 正常超时/中止路径 |
| Job Object `KillOnJobClose` | **Job 句柄被关闭**（进程退出/句柄释放） | Windows 内核 | **XEYO 自己崩了/被杀** |

`runner.py:62-68` 的 docstring 写明了分工（原文）：

```
	优先 taskkill /T（可靠打断 shell 子进程）；Job Object 仅作限额与
	CloseHandle 时的 KillOnJobClose 兜底——勿在此调用 TerminateJobObject，
	在部分嵌套 Job 环境下会阻塞。
```

`win_job.py:25-27`（`JobHandle` 的 docstring）：「持有 Job Object 句柄；**close 时 KillOnJobClose 会杀仍在运行的成员**。」

**为什么 `TerminateJobObject` 被禁用**：docstring 给的理由是「**在部分嵌套 Job 环境下会阻塞**」。

「嵌套 Job」指：XEYO 自身进程**已经**处于某个 Job Object 中（Windows 8+ 支持 Job 嵌套；某些运行环境——CI、容器、任务计划、某些终端——会给进程套 Job）。在此情形下对**子 Job** 调 `TerminateJobObject` 可能阻塞（等一个不会到来的状态变化），于是：**一个用于「清理」的调用自己变成了挂起点**。

★ 这是一个**「机制本身比它要解决的问题更危险」**的判断，所以选择：

| 动作 | 是否调用 | 理由 |
|---|---|---|
| `AssignProcessToJobObject` | ✅ 调用（`win_job.py:45`） | 把子进程收进 Job（正常路径） |
| `taskkill /T /F` | ✅ 调用（`runner.py:75-80`） | 主动杀树 |
| `TerminateJobObject` | ❌ **不调用** | 嵌套 Job 下可能阻塞 |
| `CloseHandle` | ✅ 调用（句柄释放） | 触发 `KillOnJobClose`（**被动**清理） |

**深化讲解**（面试官参考，不要求候选人全说）
这道题的关键是识别「**主动 vs 被动**」这一划分：

```
主动清理（XEYO 决定杀）：taskkill /T /F        ← 需要 XEYO 活着
被动清理（系统决定杀）：KillOnJobClose          ← XEYO 死了也会执行
```

若只有主动清理，那么「XEYO 被强杀」时子进程全部变孤儿（并继续占 CPU/内存/文件锁）；若只有被动清理，那么「命令超时但 XEYO 继续运行」时无法及时杀掉（只能等 Job 句柄释放——而句柄在 `finish_streaming` 的 `h.release()` 才释放，还在等 `proc.wait(timeout=2)`）。

所以**两者缺一不可**，这也解释了为什么 `_kill_process` 会接收 `job` 参数却 `_ = job` 忽略它（`:69`）——参数保留是为了**接口完整性**（调用方有 job 就传），而实现上**刻意不通过 job 主动终止**。

★ 与 POSIX 侧的对照（0246）：POSIX 分支**只有** `proc.kill()`（主动，且只杀根），**没有**被动兜底（没有进程组/session）。所以 POSIX 侧的孤儿风险**同时来自**「杀不干净」与「没有被动兜底」两个缺陷——而 Windows 侧两个都有解。这是**平台成熟度不对称**的一个具体实例。



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

### XEYO-QA-0241 `effective_promote_ms` 的四条早退

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 收尾窗路由 | 早退顺序 | 困难 | 代码阅读 | `python/tools/bash_tool/bash_tool.py:146-175` |

**面试官提问**
`effective_promote_ms(cmd, base_ms)` 有四条早退（返回原阈值）。请逐条说明它们各自在防什么，并指出哪一条是「保住最后一步产物」的关键。

**参考答案要点**
`bash_tool.py:160-175`（原文）：

```python
	if base_ms <= 0:
		return base_ms
	try:
		from engine.wrap_window import in_wrap_window, wrap_remaining_s
		from tools.bash_tool.timeout_map import family_default_ms

		if not in_wrap_window():
			return base_ms
		if family_default_ms(cmd) is None:
			return base_ms
		remaining = wrap_remaining_s()
		if remaining is not None and remaining >= WRAP_WINDOW_BG_MAX_REMAINING_S:
			return base_ms
		return 1
	except Exception:  # noqa: BLE001 — 信号/映射不可用即按原阈值
		return base_ms
```

| # | 早退条件 | 防什么 |
|---|---|---|
| 1 | `base_ms <= 0` | **晋升已关闭**（0216：`0=关闭`）。若不早退，`0` 会被改成 `1` → **把用户关闭的功能偷偷打开** |
| 2 | `not in_wrap_window()` | 不在收尾窗内 → 完全不该介入（这是收尾窗专属路由） |
| 3 | `family_default_ms(cmd) is None` | **非长命令族** → 不提前交权（见下，这条是关键） |
| 4 | `remaining >= 120.0`（或 `remaining is None` 之外的充裕情形） | 窗口**剩余时间充裕** → 让能跑完的命令照常等 |

**第 3 条是关键**（`:143-145` 注释）：

```
#: 收尾窗内"立即后台化长命令"的剩余时间闸门（秒）。窗口还剩很多时不动——让
#: 可能在窗口内跑完的命令照常前台等结果（保住"最后一步长命令出产物"的路径）；
#: 只在窗口已经很短（或剩余时间未知=配额型收尾窗）时才提前交还控制权。
```

「保住**最后一步长命令出产物**的路径」——即：如果一条长命令**还有机会在窗口内跑完并产出结果**，就让它继续跑（模型能拿到真正的结果）；只有**注定跑不完**（窗口已很短）时，才提前交权让模型用余下时间去落盘。

★ 第 3 条用的是 `family_default_ms(cmd) is None` —— 注意它问的是「**是否有家族映射**」，而不是「是否真会跑很久」。也就是说判据是「**已知会久留的命令族**」（pip/npm/cargo 等，见 0209）。这比「估计时长」简单且可复现（符合 `timeout_map` 的「纯规则」纪律）。

**第 4 条的细节**：`remaining is not None and remaining >= 120.0` —— 注意 `None` 的语义：

| `wrap_remaining_s()` 返回 | 含义 | 本条是否早退 |
|---|---|---|
| 一个数值 `>= 120` | 窗口充裕 | ✅ 早退（原样） |
| 一个数值 `< 120` | 窗口很紧 | ❌ 不早退 → `return 1` |
| **`None`** | **剩余时间未知**（配额型收尾窗） | ❌ 不早退 → `return 1` |

即「**未知即按最紧处理**」——注释明确「（或剩余时间未知=配额型收尾窗）时提前交还控制权」。这是 fail-safe 方向的选择：预算型窗口无法预知还剩多久，所以一律提前交权。

**深化讲解**（面试官参考，不要求候选人全说）
这四条的**顺序有讲究**：

```
① 功能关闭？        → 不介入（最高优先，保护用户显式设置）
② 不在窗口？        → 不介入（缩小作用面）
③ 非长命令族？      → 不介入（保护「能跑完的」）
④ 窗口充裕？        → 不介入（同上，但按剩余时间判）
   ↓ 全不成立
   立即后台化（1ms）
```

①② 是**作用面收缩**（不该介入的场景）；③④ 是**效用判断**（介入反而有害的场景）。把它们分开的理由是：①② 是「这个机制管不着」，③④ 是「这个机制管得着但此刻不该动」。

**边界**：整个 `try` 包住 ②③④（含两个惰性 import），异常时 `return base_ms`——**fail-safe**：信号或映射不可用时退回原阈值（不介入），而不是错误地提前交权。这与 0239 的「三处取向」一致：**误提前交权**会让一条本来能跑完的命令被后台化（模型要多一次 `job_output` 交互），而**不介入**只是维持旧行为——所以异常时选后者。

另外注意 `return 1` 而不是 `return 0`：因为 `0` 在 0216 里是「关闭晋升」的语义。若返回 0，就会**关掉晋升**——与意图（让它立即后台化）完全相反。这个「1 vs 0」的差别是一处**极易写错**的地方。



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

### XEYO-QA-0242 截断落盘与 spill/预算的三层关系

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | 三层输出治理 | 为何不叠加 | 困难 | 场景设计 | `python/tools/bash_tool/truncate.py:61-96` + `python/tools/meta.py:138-155` + `python/tools/tool_registry.py:204-234` |

**面试官提问**
Bash 的输出可能经过三层治理：`truncate_for_model`（Bash 自带）、`cmd_compact`（压缩）、`_apply_output_budget`（registry 预算）。请说明哪几层**实际会作用**在同一次 Bash 调用上，以及 Bash 为什么豁免 registry 预算。

**参考答案要点**
**豁免**在 `tools/meta.py:138-155`（Bash 的 `ToolMeta` 节选）：

```python
		ToolMeta(
			name="Bash",
			read_only=False,
			concurrency_safe=False,
			policy="bash",
			subagent_ok=True,
			subagent_baseline=True,
			# T1：Bash 自带 raw→落盘→截断 seam（truncate_for_model），豁免
			# registry 级预算，避免双重截断/双重落盘。
			output_budget=0,
			short_description=(
				"Only for commands with no dedicated tool: "
				"build/test/install/process/network, git writes. "
				"NEVER for file ops — list→Glob, search→Grep, read→Read, "
				"edit→Edit, write→Write, git read→Git."
			),
		),
```

`output_budget=0` 在 registry 侧的含义是「**关闭预算**」（B04-0178：`budget <= 0` 直接返回，早退）。理由注释写明了：「Bash 自带 raw→落盘→截断 seam（`truncate_for_model`），豁免 registry 级预算，**避免双重截断/双重落盘**」。

**实际作用链**：

| 层 | 是否作用在 Bash 上 | 依据 |
|---|---|---|
| `cmd_compact`（压缩） | ✅ | 结果渲染阶段（`compact_command_output`） |
| `truncate_for_model`（截断 + 落盘） | ✅ | `bash_tool` 的结果处理（20k/8k + 落盘） |
| `_apply_output_budget`（registry 预算） | ❌ **豁免** | `meta.py` 的 `output_budget=0` |
| `_apply_output_budget` 的 spill 落盘 | ❌ 同上层 | 同上 |

**若不豁免会怎样**（双重处理的三个具体后果）：

| 后果 | 机制 |
|---|---|
| **双重截断** | `truncate_for_model` 已把 100k 输出裁成 28k+标记；若 registry 再按 `16_000` 字符裁一次 → 模型的可见面被裁两次，且第二次的「头 6k + 尾 2k」落在**第一次裁完的文本**上 → 中间段的**错误抢救内容**（0225 抢救的那 8 行）可能被第二次裁掉 |
| **双重落盘** | `truncate_for_model` 已落盘一份 `bash-<uuid>.txt`；registry 再 `spill.save_text` 落一份 → **同一份输出的两份证据文件**，模型看到两个路径（一个来自截断标记、一个来自预算标记），可能重复读取 |
| **标记冲突** | 文本里会同时出现 `[output truncated, full at <pathA>]` 与 `[output truncated: 预算截断（非错误）……full output: <pathB>]` 两类标记，含义重叠但路径不同 → 语义混乱 |

★ 注意第一行的**具体危害**：0225 的中段错误抢救是**针对第一次截断**设计的补偿；若第二次截断（registry 的 head 6k/tail 2k）作用其上，那 8 行抢救内容位于**第一次结果的中间偏后**位置——而 6k/2k 的窗口**很可能把它裁掉**。也就是说**双层截断会让「抢救」白做**。这是「豁免」这条设计的具体价值所在。

**深化讲解**（面试官参考，不要求候选人全说）
这道题体现的是一条清晰的架构原则：**同一治理职责只允许一层实现**。Bash 的定位是「自带完整 seam 的工具」（raw → 落盘 → 截断），所以它在 registry 层被标记为**已自治**。

对照其他工具（B04 已确立）：

| 工具 | `output_budget` | 谁负责截断/落盘 |
|---|---|---|
| `Read` | `0`（豁免） | Read 自带（`MAX_LINES_TO_READ` + 令牌闸门）——理由「防 read→spill→read 循环」 |
| `Bash` | `0`（豁免） | `truncate_for_model` |
| `Glob` / `Grep` / `Write` / `Edit` | 未设 → `16_000` | registry 预算 + spill |

即：**凡是自带截断/落盘能力的工具都设 `output_budget=0`**，避免双重处理；其余工具交给 registry 统一管。这是一个**按能力而非按重要性**划分的分工。

★ 而 `cmd_compact` 与 `truncate_for_model` 之间**不是重复**而是**串联**（压缩在前、截断在后，见 0238 的顺序问题）——它们是两个不同职责：压缩是**语义级**（把通过行去掉、保失败），截断是**体积级**（按字符裁 + 落盘）。所以 Bash 内部的「两层」是允许的（职责不同），但 registry 那层与 `truncate_for_model` 是**同一职责**（体积截断 + 落盘）→ 必须二选一。



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

### XEYO-QA-0243 后台晋升的「进程不重启」保证

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 晋升语义 | 三条保证 | 困难 | 场景设计 | `python/tools/bash_tool/bash_tool.py:128-130` + `python/tools/bash_tool/runner.py:333-370` + `python/tools/bash_tool/jobs_bridge.py:53-89` |

**面试官提问**
前台命令晋升为后台 job 时，代码如何保证「进程不重启、已累积输出随晋升返回」？三条保证各自依赖什么机制？

**参考答案要点**
**承诺**（`bash_tool.py:128-130` 注释原文）：

```python
#: 前台命令运行超过该阈值仍未结束 → 自动晋升为后台 job（0=关闭）。
#: 进程不重启、已累积输出随晋升返回；env XEYO_BASH_PROMOTE_MS 可调。
BASH_PROMOTE_DEFAULT_MS = 45_000
```

**三条保证及其机制**：

| 保证 | 机制 | 位置 |
|---|---|---|
| ① **进程不重启** | 晋升走 `adopt_registry_job`（**接管**一个运行中的句柄），而不是重新 `start_registry_job` | `jobs_bridge.py:53-89` |
| ② **已累积输出不丢** | `StreamHandle.buf` 在泵线程里持续累积（每行 append + sink 分发） | `runner.py:224-239` |
| ③ **输出改道可后挂** | `add_sink`（`:242-244`）+ `_abort_box` 可变槽（`:211-213`） | `runner.py:211-244` |

**① 的关键证据**是 `adopt`/`start` 两个函数名的对照（`jobs_bridge.py`）：

```python
def start_registry_job(...):
	"""尝试把命令登记为 42 号后台 job。"""

def adopt_registry_job(
	*,
	handle: Any,          # ← 接收「已存在的句柄」
	...
):
	"""前台超时晋升：把运行中的活进程收编为 42 号 job。"""
```

`adopt_registry_job` 的 docstring 明确「**把运行中的活进程收编**」，且它的第一个业务参数是 `handle`——即**传入正在运行的 `StreamHandle`**，由 registry 接管。若晋升是「杀掉重跑」，就绝不会需要 `handle` 参数。

**② 的关键**是泵线程**从未停止**：`spawn_streaming`（`:364-370`）里

```python
	h = StreamHandle(proc=proc, job=job)
	if on_output is not None:
		h.add_sink(on_output)
	h.start_pump()
	# 总是启动监视线程：晋升时 detach/attach 换槽即可，无需重启线程。
	h.watch_abort(abort)
	return h
```

`start_pump()` 立刻起泵线程；泵把每行写入 `self.buf`（`:228-230`）**无论有没有 sink**。所以「晋升前的输出」全在 `buf` 里；晋升后 registry 读 `h.buffered()` 就能拿到**从进程启动到晋升那一刻**的全部累积输出。

**③ 的关键**是两处「可变槽」设计：

- `sinks` 是普通 list + 锁，`add_sink` 可随时追加（前台时无 sink，晋升后挂「写日志/推事件」的 sink）；
- `_abort_box` 是**单元素 list**（注释：「可变槽：attach/detach 原语换内容，监视线程每轮读槽」）——所以换 abort 对象**不需要重启监视线程**。

注释那句「晋升时 detach/attach 换槽即可，**无需重启线程**」正是这两处设计的动机。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的核心是「**为什么必须不重启**」——因为命令**有副作用**：

| 命令 | 若晋升 = 杀 + 重跑，会怎样 |
|---|---|
| `npm install` | 重跑浪费网络与时间，且可能撞上「已部分安装」的中间态 |
| `cargo build` | 已编译的产物作废，重新编译 |
| `docker build` | 重新拉取/构建镜像 |
| `rm -rf big_dir` | **重跑会删掉新产生的文件**（第一次已删了一部分） |
| `git commit` | 可能产生两次提交 |

也就是说：**「重跑」在语义上不是「继续等」，而是「再做一遍」**——对长命令而言完全不可接受。

所以 `StreamHandle` 这个抽象的真正价值就在此（0222 已述）：**它把「等待」与「进程」解耦**——等待动作（前台阻塞）可以被放弃（交还控制权），而进程继续跑、输出继续被泵线程收集。这也是为什么它被设计成「前台/后台共用底座」而不是两套实现。

★ 对照容器分支（0230）：它**也**实现了晋升（`_DOCKER_BG_JOBS`），但**不通过 `StreamHandle`**——因为容器走 `docker SDK` 的 `exec_run`（一个阻塞调用），没有可解绑的本地进程。所以容器分支的晋升是「**worker 线程继续跑完 → 写入 job 表**」，语义等价但实现不同（那个线程本身就是「等待动作」，它继续存在即可）。



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
### XEYO-QA-0244 家族识别的粒度与误判面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | cmd_compact 家族识别 | 整串正则匹配 | 困难 | 场景设计 | `python/tools/bash_tool/cmd_compact.py:45-52` |

**面试官提问**
`detect_family(command)` 的识别粒度是什么？它与 `timeout_map.base_command_of`（0209）的粒度差异会导致什么具体误判？

**参考答案要点**
`cmd_compact.py:45-52`（原文）：

```python
def detect_family(command: str) -> _Family:
	cmd = (command or "").strip()
	if not cmd:
		return "unknown"
	for pat, fam in _CMD_PATTERNS:
		if pat.search(cmd):
			return fam
	return "unknown"
```

**粒度是「整条命令串的正则匹配」**——`pat.search(cmd)` 作用于**完整命令行**（不是只对首词），且**首个命中的模式即返回**（顺序敏感）。

对照 `timeout_map.base_command_of`（`timeout_map.py:96-103`）：

| 维度 | `detect_family` | `base_command_of` |
|---|---|---|
| 作用对象 | **整条命令串** | **首个词**（`split(maxsplit=1)[0]`） |
| 匹配方式 | 正则 `search`（子串匹配） | 字典精确查表（+ 前缀家族） |
| 顺序敏感 | **是**（首个命中即返回） | 否（精确键唯一） |
| 是否去 `.exe` | 不涉及 | **不去**（所以表里有 `pytest.exe` 单独一条，见 0204） |

**差异导致的三类具体后果**：

**① 复合命令的家族由「首个出现的关键词」决定**：`npm test && pytest -q` 这类命令，家族取决于 `_CMD_PATTERNS` 里 `npm`-系与 `pytest` 模式的先后顺序——而**压缩器只会按一个家族的规则处理**（另一个部分的输出格式不同）。这不会压错（压错也只是少压），但可能**压缩效果不如预期**。

**② 命令串里出现的「非程序名关键词」可能误命中**：因为用的是 `search`（子串）而非「首词匹配」，形如

```
echo "run pytest later" > note.txt
```

若 `_CMD_PATTERNS` 里有匹配 `pytest` 的模式，这条命令会被判为 `pytest` 家族 → 用 pytest 压缩器处理一段**与 pytest 无关**的输出。后果是**压缩可能生效但无意义**（大多数压缩器在「找不到匹配行」时会返回近似原文，所以危害有限）；若压缩器有激进分支，则可能丢信息。

**③ 与 0238 的不变式配合后风险受控**：即使家族误判、压缩器误压，`_TRACE_HINT` 的**事后校验**（`compact_command_output` 的最后一个 `if`）仍会在「错误信号被压掉」时回滚原文。所以误判的**主要代价是「压缩没压好」而不是「信息丢失」**——这个结论依赖于 0238 的不变式存在。

**深化讲解**（面试官参考，不要求候选人全说）
家族识别的粒度选择是**「整串正则」vs「首词查表」**之间的取舍：

| 方案 | 优点 | 缺点 |
|---|---|---|
| **整串正则**（本模块） | 能识别 `python -m pytest`、`npx vitest run`、`cargo test --all` 等「程序名不是家族名」的形态 | 顺序敏感；子串误命中；复合命令只认一族 |
| **首词查表**（`timeout_map`） | 精确、无顺序问题 | 必须为每个变体单列（所以表里有 `pytest.exe`）；识别不了 `python -m pytest`（因此另加 `_PREFIX_FAMILIES` 前缀兜底） |

两者各自补了自己的短板：`timeout_map` 加**前缀家族**（`:66-70`），`cmd_compact` 用**正则**（天然覆盖前缀形态）。所以**不是谁更好，而是两种短板的不同补偿方式**。

★ 一个值得记录的对照：`timeout_map` 的 `_PREFIX_FAMILIES` 只有两条（`-m pip`、`-m pytest`，`:67-70`）——**枚举式补偿**，需要逐个添加；而 `cmd_compact` 的正则天然覆盖任意位置的前缀——**模式式补偿**。前者可预测、后者更宽。这也是为什么 `timeout_map` 必须为 `pytest.exe` 单独列表（0204 已述），而 `cmd_compact` 不需要。

**边界（本批待确认项）**：`_CMD_PATTERNS` 的**具体正则与顺序**未在本次定义面抽取中列出（它未匹配 `^(def |class |[A-Z_]{3,} *=)` 模式，可能是带类型标注的赋值如 `_CMD_PATTERNS: tuple[...] = (`）。因此「顺序敏感」这一点的**实际影响**需读该常量才能确认。本批按「存在且被 `detect_family` 顺序遍历」出题，并显式标注这一待确认。



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

### XEYO-QA-0245 `_load_overrides` 的缓存与坏值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | timeout_map 环境覆盖 | 单次加载与坏值 | 困难 | 场景设计 | `python/tools/bash_tool/timeout_map.py:72-93,106-127` |

**面试官提问**
`_load_overrides` 用模块级全局变量缓存解析结果。这个缓存在什么粒度上生效？「坏值/坏 JSON」分别怎么处理？这个设计有什么运行期后果？

**参考答案要点**
`timeout_map.py:72-93`（原文）：

```python
_OVERRIDES: Optional[dict[str, int]] = None


def _load_overrides() -> dict[str, int]:
	"""env ``XEYO_CMD_TIMEOUT_OVERRIDES``（JSON 对象）→ 增量覆盖；坏 JSON 忽略。"""
	global _OVERRIDES
	if _OVERRIDES is None:
		raw = os.environ.get("XEYO_CMD_TIMEOUT_OVERRIDES", "").strip()
		parsed: dict[str, int] = {}
		if raw:
			try:
				data = json.loads(raw)
				if isinstance(data, dict):
					for k, v in data.items():
						try:
							parsed[str(k)] = max(1_000, int(v))
						except (TypeError, ValueError):
							continue
			except ValueError:
				parsed = {}
		_OVERRIDES = parsed
	return _OVERRIDES
```

**缓存粒度**：`if _OVERRIDES is None` —— 即**进程内一次性**（lazy singleton）。第一次调用解析，此后**永不重读环境变量**。

**坏值处理分两层**：

| 层级 | 坏形态 | 处置 |
|---|---|---|
| **整体** | `raw` 不是合法 JSON（`json.JSONDecodeError` ⊂ `ValueError`） | `parsed = {}`——**整份忽略** |
| **整体** | JSON 合法但不是 dict（如 `[1,2]`） | `isinstance(data, dict)` 为假 → 保持 `parsed = {}`（整份忽略） |
| **单项** | 某个 value 不能 `int()`（如 `"abc"`、`null`） | `continue`——**只跳过该项**，其余保留 |
| **单项** | 某个 value 小于 1000 | `max(1_000, int(v))` → **夹到 1000** |

★ 注意两层**取向不同**：整体坏 = 全丢；单项坏 = 只丢一项。这是合理分层（一个坏项不该毁掉整份配置），但也意味着「值写错（如把 `600000` 写成 `"600k"`）会**静默失效**」——没有 warning、没有日志，该命令族的超时**回落到表内默认值或全局 120s**。

**运行期后果（本题的重点）**：

| 后果 | 机制 |
|---|---|
| **改环境变量无效** | 一旦 `_load_overrides` 被调用过，后续 `os.environ["XEYO_CMD_TIMEOUT_OVERRIDES"] = ...` **不生效**（缓存不为 `None`） |
| **测试必须重置全局** | 任何测试想验证覆盖行为，必须手动把 `timeout_map._OVERRIDES` 置回 `None`（或 `importlib.reload`），否则测试间会互相污染 |
| **多进程场景无问题** | 每个进程各自解析一次环境变量，天然隔离 |
| **配置热更新的缺口** | 若产品希望「改环境变量即时生效」，此设计**不支持**（与 `memory_switches.apply_to_environ` 那种「每次切换都重新写入 env」的模式不同） |

**深化讲解**（面试官参考，不要求候选人全说）
「lazy singleton + 永不重读」是一个**常见的性能取向选择**（避免每次命令执行都解析 JSON 与 `int()` 转换），代价是**不可热更**。对这个用途来说代价可接受：超时映射是**启动期配置**，中途改环境变量的需求很弱。

但有一处**具体不一致**值得记录：同目录下的 `bash_tool.py:133-140`（`promote_threshold_ms`）**每次调用都读环境变量**：

```python
def promote_threshold_ms() -> int:
	raw = os.environ.get("XEYO_BASH_PROMOTE_MS", "").strip()
```

即：`XEYO_BASH_PROMOTE_MS` 可热更，而 `XEYO_CMD_TIMEOUT_OVERRIDES` 不可。同一个工具族的两个超时相关配置**热更能力不同**——这不是缺陷，但是**读代码时容易假设一致**的地方。

★ 另外注意覆盖的**优先级位置**（`family_default_ms`，`:106-127`）：「匹配优先级：env 覆盖 > 精确 base > 前缀家族」——即 env 覆盖**可以覆盖前缀家族的解析结果**（`:124-125`：前缀命中时先查 `if family in overrides`）。这是合理的设计（用户显式覆盖优先于内置表）。

**边界**：`max(1_000, int(v))` 的下限 1000ms 意味着**无法配置「0.5 秒超时」**；而**没有上界夹取**——但 `clamp_timeout_ms`（0202）会在最终应用时夹到 `MAX_TIMEOUT_MS = 600_000`，所以环境变量给的值仍受全局硬顶约束。



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

### XEYO-QA-0246 【超压·故障排查】POSIX 超时只杀 shell 不杀子进程树

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | runner 进程终止 | 孤儿进程 | 超压 | 故障排查 | `python/tools/bash_tool/runner.py:62-88,333-405` |

**面试官提问**
**故障报告**：在 Linux/macOS 上，一条超时被杀的 Bash 命令**仍在后台继续运行**——它继续占 CPU、继续写文件，甚至在被杀之后**产生了新的文件**。Windows 上同样的场景没有这个问题。请给出根因、证据行号、复现步骤、影响面与修复方向。

**参考答案要点**
**根因：`_kill_process` 的 POSIX 分支只调用 `proc.kill()`，终止的是 `Popen` 直接创建的进程（即 `/bin/sh -c <command>` 这一个进程），而它启动的子进程（真正的 `npm`/`pytest`/`make`）不在杀死范围内。**

**证据链（四处）**：

**① 平台分叉**（`runner.py:70-82`）：

```python
	if proc is None or proc.poll() is not None:
		return
	try:
		if os.name == "nt" and proc.pid:
			# shell=False 时杀的也是整棵树（taskkill /T）；proc.kill() 仅杀根。
			subprocess.run(
				["taskkill", "/PID", str(proc.pid), "/T", "/F"],
				capture_output=True,
				timeout=5,
				check=False,
			)
		else:
			proc.kill()
```

**注释自己写明了差异**：「shell=False 时杀的也是整棵树（`taskkill /T`）；**`proc.kill()` 仅杀根**」。即作者知道 `proc.kill()` 只杀根，但**只给 Windows 补了树杀**。

**② shell 是中间层**（`runner.py:136-147`）：命令的 argv 是 `[shell, "-c", command]`（POSIX）或 `[pwsh, "-Command", command]`（Windows），所以：

```
XEYO 进程
  └─ /bin/sh -c "npm run build"        ← proc.pid（被杀的就是它）
       └─ sh 解析后 spawn 的 npm        ← 孤儿
            └─ node ...                ← 孤儿
```

`sh -c "a && b"` 时 `sh` 会 `fork` 出子进程再等待——所以 `proc.kill()` 杀的是「等待者」，被等待的进程**不受影响**。

**③ 没有被动兜底**：Windows 侧还有 Job Object 的 `KillOnJobClose` 作为第二道（0240），而 POSIX 侧 `spawn_streaming`（`:333-370`）虽然**也调了** `create_bash_job`（`:343`），但 `win_job.JobHandle.assign` 在非 Windows 上直接返回 `False`（`win_job.py:32-33`：`if self.handle is None or os.name != "nt" or not pid: return False`）——即**没有任何生效的进程组/session 机制**。

**④ 超时路径确实会调它**（`runner.py:378-386`）：

```python
	try:
		h.proc.wait(timeout=max(0.001, timeout_ms / 1000.0))  # type: ignore[union-attr]
	except subprocess.TimeoutExpired:
		timed_out = True
		h.kill()
		try:
			h.proc.wait(timeout=2)  # type: ignore[union-attr]
		except subprocess.TimeoutExpired:
			pass
```

`h.kill()` 最终走 `_kill_process`。而 `h.proc.wait(timeout=2)` 等的是**根进程**——根被杀后立即返回，于是流程继续（`release()` → 返回 `ExecResult(timed_out=True, ...)`），**完全不会察觉子进程仍在跑**。

**复现步骤**：

1. 在 Linux 上准备一条「会产生长时间子进程」的命令，例如 `sh -c 'sleep 300 & echo started'`，或更真实地 `npm run build`（`npm` 会 spawn `node` 子进程）；
2. 用远小于实际运行时长的 `timeout_ms`（例如 `3000`）调用 `Bash`；
3. 工具返回 `Command timed out after 3000ms and was killed.`；
4. **观测**：`pgrep -f sleep`（或 `pgrep -f node`）仍能看到该进程；`ps -o ppid= -p <pid>` 显示其父进程已是 1（被 init 收养）——**孤儿**；
5. **反证**：同场景在 Windows 上执行等价命令，`tasklist` 查不到残留（`taskkill /T` 已递归杀掉）。

**影响面**：

| 面 | 影响 |
|---|---|
| 资源 | 孤儿持续占 CPU/内存（编译/测试类命令尤其重） |
| **正确性** | 孤儿仍在**写工作区**——用户在杀掉命令后手动改文件，孤儿可能**覆盖**它（最严重） |
| 可观测性 | `process_ledger` 登记的是 `proc.pid`（`runner.py:363`：`_ledger_register_process(proc.pid, cmdline=command)`），孤儿**不在账本里** → 重启后的 `leftovers()` 也发现不了它 |
| 平台差异 | Windows 无此问题，导致**同一 bug 只在 Linux/macOS 出现** |
| 影响范围 | 任何超时/中止的 Bash 命令；后台任务的取消路径同理 |

**与缺陷基线的一致性**：审计报告 `TOOL-06`（`docs/全项目BUG排查-20260910.md:138`）记录「POSIX 超时只 kill shell 不杀子进程树 → 孤儿进程」，锚点 `bash_tool/runner.py:81-82`。本批**逐行复核一致**：`:81-82` 正是 `else:` 与 `proc.kill()` 两行，缺陷**仍然成立**（与 0248 的 `TOOL-03` 形成对照——那条已修复）。

**修复方向（只描述方向）**：

1. **让子进程独立成组再整组杀**：`Popen(..., start_new_session=True)`（POSIX）使子进程成为新 session/进程组组长，再用 `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)`——这是 POSIX 上 `taskkill /T` 的等价物；
2. **或在杀根前先杀所有后代**：递归 `pgrep -P <pid>` / `/proc/<pid>/task/*/children`——可移植性较差，但不必改 `Popen` 调用；
3. **配套**：`process_ledger` 应登记**进程组 id** 而不只是 `pid`（否则重启后的孤儿依旧不可见）；
4. **回归测试**：起 `sh -c 'sleep 60 & wait'`，超时后断言 `pgrep -f sleep` 无输出。注意这条测试**只在 POSIX 有意义**——CI 的 gui/tui job 在 Windows 上会跳过（B01 已记录「Windows 平台不在 CI 内」，但这条恰好相反：**Linux 侧需要补测试**）。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的核心是「**平台不对称**」这一结构性根因，而不只是「少了一行」。三个观察：

**① 注释证明作者知道差异**——「`proc.kill()` 仅杀根」写得清清楚楚，却只在 Windows 分支处理。这类「**已知但只修了一侧**」的缺陷比「未知缺陷」更值得记录：它说明修复的触发条件是「**有人在实际使用的平台上遇到了**」，而不是「代码评审发现了不一致」。

**② 被动兜底也不对称**（与 0240 对照）：

| 平台 | 主动树杀 | 被动兜底 |
|---|---|---|
| Windows | ✅ `taskkill /T` | ✅ Job Object `KillOnJobClose` |
| POSIX | ❌ 只杀根 | ❌ **无**（`JobHandle.assign` 在非 Windows 直接返回 False，且无进程组） |

所以 POSIX 侧是**两道都缺**——这也解释了为什么修复方向第 1 条（`start_new_session` + `killpg`）是根因级修复，而第 3 条（账本登记进程组）补的是「被动可见性」。

**③ 最严重的后果是「孤儿写工作区」**：这把它从「资源泄漏」升级为「**数据正确性问题**」。用户在超时后以为命令已被终止，随后手动（或让 agent）修改文件——而孤儿可能在几秒后写入它自己的版本 → **改动被覆盖且现场无任何提示**。这与 B04-0197（`Write` 改行尾）、B09-0450（回滚残留）属同一类「**静默的既成事实**」故障。



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

### XEYO-QA-0247 【超压·安全测试】只读白名单被判「只读」的越界面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 白名单 | 判定与实际能力不符 | 超压 | 安全拷问 | `python/tools/bash_tool/bash_tool.py:63-79,91-112` |

**面试官提问**
`_PURE_READ_BASES` 的注释是「**纯读基础命令（任意参数都只读）**」（`bash_tool.py:63`）。请回答：①这份「只读」声明的**实际作用域**是什么？②把它当作安全白名单会有什么后果？③`find` 这个成员有哪三种写能力？④如果攻击者只能控制「让 agent 执行一条 Bash 命令」，这份清单能为攻击者提供什么便利？⑤正确的审计报告应该怎么写？

**参考答案要点**
**① 实际作用域：仅「是否清搜索缓存」**。

唯一消费面是 `_command_may_mutate_workspace`（`:91-112`），其返回值语义是「是否可能写盘 → 是否应失效 Glob/content_index 缓存」。它**不参与**：

| 机制 | 是否用这份清单 |
|---|---|
| 权限三态裁决（allow/ask/deny） | ❌（`permissions/policy.py` + `bash_policy.py`，B07） |
| 只读模式网关（readonly gate） | ❌（`permissions.policy.readonly_gate`） |
| 破坏性快照 | ❌（用**自己的** `DESTRUCTIVE_PROGRAMS` 黑名单，0207） |
| 命令预检 | ❌（自己的三道闸，0223） |
| **缓存失效** | ✅ **唯一消费面** |

所以「任意参数都只读」是**对缓存语义的陈述**（「这些命令不写工作区，所以不必清缓存」），**不是安全声明**。

**② 把它当安全白名单的后果**：会立刻放行大量可写命令。清单里至少这些成员**带写能力**：

| 成员 | 写能力 |
|---|---|
| `find` | `-delete`、`-exec`、`-fprint`/`-fls`（见 ③） |
| `tree` | `-o file` |
| `diff` | `--output=file` |
| `xxd` | `xxd in out`（第二位置参数是输出文件） |
| `iconv` | `-o outfile` |
| `cut`/`nl`/`tac`/`rev`/`fold`/`fmt`/`tr`/`uniq`/`join`/`comm`/`cmp` | 本身无 `-o`，但**重定向**可写（`cut ... > f`）——这一路已被 `bash_writes_file` 拦（0215 第 2 步） |
| `ps`/`tasklist`/`whoami`/`hostname`/`pwd`/`date`/`printenv`/`which`/`where` | 无写 |
| `echo`/`printf`/`test`/`true`/`false`/`sleep` | 无写（除非重定向） |

即：**清单是「程序级」的，而部分程序有「选项级」的写能力**（0233 已从缓存正确性角度讨论；这里是同一事实的安全视角）。

**③ `find` 的三种写能力**：

| 选项 | 行为 |
|---|---|
| `-delete` | 删除匹配的文件/目录 |
| `-exec <cmd> {} \;`（或 `+`） | 对每个匹配项执行任意命令（含写） |
| `-fprint <file>` / `-fls <file>` / `-fprintf <file> …` | 把结果**写入文件**（`-print` 的文件版） |

所以 `find . -name '*.py' -exec sh -c '…' \;` 是一条**完全可写**的命令，却被判为「只读」。

**④ 攻击者获得的便利**（在「只能让 agent 跑一条 Bash 命令」的假设下）：

| 便利 | 机制 |
|---|---|
| **对权限层：无** | 权限三态与这份清单**无关** → 该命令仍走 `evaluate_policy`（ASK/DENY） |
| **对缓存一致性：有** | 判「只读」→ **不清缓存** → 60s/30s 内 Glob/Grep 呈现**旧事实**；攻击者可用它制造「agent 以为自己看到了全部文件」的窗口 |
| **对快照：有（叠加缺口）** | `find` **不在** `DESTRUCTIVE_PROGRAMS`（0207）→ 不做破坏性快照（0234 缺口一：解释器/非清单程序的破坏性） |
| **最有价值的一条** | 组合「`find -delete`（无快照） + 缓存仍列出被删文件（不清缓存）」→ agent 基于**错误的文件列表**继续工作，且**没有恢复点** |

★ 结论：这份清单**不削弱权限**，但它的**误判与另一份黑名单的缺口叠加**，会产生「**破坏既成事实 + 不更新事实 + 无恢复点**」的三重组合——这是攻击者（或提示注入）最想要的组合之一。

**⑤ 正确的审计报告写法**：不应写「白名单有漏洞」（那会误导修复方向为「往白名单加选项检查」），而应写**叠加缺口**：

```
find . -name '*.log' -delete
  ├─ 缓存判定：白名单命中 → 判只读 → 不清缓存        ❌ 事实不更新
  ├─ 快照判定：find 不在 DESTRUCTIVE_PROGRAMS → 不守卫  ❌ 无恢复点
  ├─ 预检：不匹配三道闸 → 放行（正确，它不会挂）        ✅
  └─ 权限：走 evaluate_policy（ASK/DENY）              ✅ 唯一的真闸
```

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的要点是**「一份清单的语义被误读为另一份清单的职责」**。项目里同类的「清单/机制」至少有五份（本批已读到）：

| 机制 | 位置 | 判什么 | 拒绝还是观测 |
|---|---|---|---|
| `_PURE_READ_BASES` / `_GIT_READ_SUBS` | `bash_tool.py` | 是否可能写盘（→缓存） | 观测（决定清不清缓存） |
| `DESTRUCTIVE_PROGRAMS` | `destructive_guard.py` | 是否可能删改（→快照） | 观测（决定做不做快照） |
| `_FULLSCREEN` / `_TTY_TOOLS` / git editor | `precheck.py` | 是否会挂住（→拒绝） | **拒绝** |
| `SILENT_COMMANDS` | `bash_tool.py` | 空输出是否正常 | 观测（结果解读） |
| `evaluate_policy` / `bash_policy` | `permissions/`（B07） | 可否执行 | **裁决** |

**只有最后一份是权限**。前四份都是**观测分类器**——它们的输出不阻止执行，只改变引擎的辅助行为（清缓存 / 做快照 / 拒绝挂死 / 解读结果）。

★ 因此「把观测分类器当权限白名单」会立即产生越界；而它们在**正确作用域内**是有价值的（清缓存的成本论证见 0215）。

★ 另一个值得记的点：**「任意参数都只读」这句注释本身就是错的**——它的正确表述是「这些命令**在默认参数下**通常不写工作区」。注释的措辞把一个**启发式**说成了**不变量**，而这正是后人误用的根源。这类「注释把启发式写成不变量」的措辞问题，与 B09-0439（「不改召回集」）、B04-0196（「full output」）属同一族。



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

### XEYO-QA-0248 【超压·故障排查】docker 分支的「失败报成功」是否仍成立

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | bash_tool 容器分支 | 缺陷基线复核 | 超压 | 故障排查 | `python/tools/bash_tool/bash_tool.py:195-278,561-573` + `docs/全项目BUG排查-20260910.md:135` |

**面试官提问**
缺陷基线记录 `TOOL-03`：「Bash docker 分支 `is_error` 恒 False 且丢退出码 → 失败报成功」（文档锚点 `bash_tool.py:569-573`）。请**复核这条缺陷在当前源码上是否仍然成立**，并指出文档的哪一部分过期了。若已修复，说明现在 docker 分支的失败是怎样表达的。

**参考答案要点**
**结论：该缺陷在当前源码上已不成立——文档过期（缺陷已修复）。**

**复核证据**（`bash_tool.py:568-573`，原文）：

```python
		cid = _routed_container() or os.environ.get("XEYO_DOCKER_CONTAINER", "").strip()
		if cid:
			out_code, out_text = _docker_exec_with_timeout(
				cid, inp.command, timeout_ms
			)
			return BashOutput(code=out_code, stdout=out_text)
```

**逐项对照文档的两条指控**：

| 文档指控 | 当前实现 | 是否成立 |
|---|---|---|
| 「`is_error` 恒 False」 | `BashOutput(code=out_code, stdout=out_text)` —— **没有传 `is_error`**，取默认值 | ⚠️ **字面成立但不再是缺陷**（见下） |
| 「**丢退出码**」 | `code=out_code` 完整传回 | ❌ **不成立** |

**退出码的来源链**（`_docker_exec_with_timeout` 的 worker，`:214-227`）：

```python
	def _worker() -> None:
		try:
			import docker

			client = docker.from_env()
			res = client.containers.get(cid).exec_run(
				["bash", "-lc", command], demux=True
			)
			out_b, err_b = res.output
			text = ((out_b or b"") + (err_b or b"")).decode("utf-8", "replace")
			code = int(res.exit_code or 0)
		except Exception as exc:  # noqa: BLE001
			code, text = 95, f"docker exec failed: {exc}"
		q.put((code, text))
```

两处关键：**①** `code = int(res.exit_code or 0)`——SDK 的 `exec_run` 返回 `exit_code`，被取出；**②** 异常路径给出 **`code = 95`**（非零），而不是 0。

**失败现在怎样表达**：**非零退出码 + stdout 里的错误文本**。

| 情形 | `code` | `stdout` |
|---|---|---|
| 容器内命令失败（如 `exit 1`） | 容器真实退出码 | 命令输出 |
| docker SDK 调用异常 | **95** | `docker exec failed: <exc>` |
| 命令成功 | 0 | 输出 |

所以**失败不再被伪装成成功**。而 `is_error` 未显式置位属**另一层**的职责（结果封装层按 `code != 0` 决定是否 `is_error`），不是 docker 分支的缺陷。

**文档哪一部分过期**：`docs/全项目BUG排查-20260910.md:135` 整行——

```
| TOOL-03 | P1 | Bash docker 分支 `is_error` 恒 False 且丢退出码 → 失败报成功 | `bash_tool.py:569-573` | medium |
```

其中「**丢退出码 → 失败报成功**」这一**因果链**已断裂。锚点 `:569-573` **仍指向 docker 分支**（行号未漂移），但该分支行为已变 → 属**「锚点正确、结论过期」**型陈旧。

★ 这比「锚点漂移」更难发现：按锚点查会看到「确实有个 docker 分支」，容易误以为缺陷还在。**缺陷基线的两类失效**：

| 失效类型 | 特征 | 发现方式 |
|---|---|---|
| 锚点漂移 | 行号指向无关代码 | 按锚点读代码，发现内容不符（B04 对 `glob_tool.py:656-658` 的复核即此型） |
| **结论过期** | 锚点仍指向同一代码，但行为已变 | 必须**逐条复核行为**，不能只看锚点对不对 |

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的价值在于**演示「缺陷基线复核」的正确方法**：不能只核对行号是否指向同一处，必须**核对指控的行为是否仍在**。

对 `TOOL-03` 的复核步骤（可复用于其余条目）：

1. 读锚点行 → 确认是 docker 分支 ✅（锚点未漂移）；
2. 读该分支的**完整实现**（进入 `_docker_exec_with_timeout`）→ 发现 `exit_code` 被取出；
3. 检查**异常路径**的 code → 发现给的是 **95**（非零）；
4. 检查 `BashOutput` 的字段 → `code=out_code` 被传入；
5. 检查 `is_error` 去哪了 → 不在 docker 分支，属结果封装层；
6. 结论：**「丢退出码」不成立，「失败报成功」的因果链断裂**。

★ 一个**经验性观察**：文档的两条指控（`is_error` 恒 False + 丢退出码）在**旧实现**里是同一件事的两面——旧代码很可能只是 `return BashOutput(stdout=out_text)`（既无 code、也无 is_error）。现在的 `return BashOutput(code=out_code, stdout=out_text)` 恰好补上了「code」这一半。所以**修复方式是「传 code」而不是「传 is_error」**——这解释了为什么**只复核「`is_error` 有没有置位」会得出错误结论**（看起来还是没置位）。

因此：**复核缺陷必须理解它的「机制」而不只是「症状」**。症状是「失败被报成成功」，机制是「退出码丢失」；机制被修掉（code 传回），症状即消失，即使 `is_error` 仍未显式置位。



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

### XEYO-QA-0249 【超压·场景分析】破坏性守卫的「不知情」降级面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | destructive_guard 降级 | 六条不守卫路径 | 超压 | 场景设计 | `python/tools/bash_tool/destructive_guard.py:213-243,346-364` + `bash_tool.py:588-622` |

**面试官提问**
破坏性守卫的开关**默认开**（0208），但有**六条路径**会让「一条破坏性命令不被快照」。请列全这六条，论证为什么它们都是「**静默**降级」，并说明这对「恢复能力」这个承诺意味着什么。

**参考答案要点**
**六条不守卫路径**（`_plan` 的前置早退，`destructive_guard.py:227-243`）：

```python
def _plan(command: str, cwd: str, ctx: Any) -> DestructivePlan | None:
	if current_context is None or RewindExecutionContext is None:
		return None
	if not guard_enabled():
		return None
	if ctx is None:
		ctx = current_context()
	if ctx is None or not ctx.enabled:
		return None
	if not cwd:
		return None

	raw_targets: list[str] = []
	for segment in _SEG_SPLIT.split(command or ""):
		raw_targets.extend(_targets_in_segment(segment))
	if not raw_targets:
		return None
```

| # | 条件 | 位置 | 性质 |
|---|---|---|---|
| 1 | **rewind 模块导入失败**（`current_context is None or RewindExecutionContext is None`） | `:228-229` | **依赖缺失** |
| 2 | 开关关闭（`guard_enabled()` 假） | `:230-231` | 显式关闭（用户知情） |
| 3 | `current_context()` 返回 `None`（无 rewind 上下文） | `:232-235` | **环境缺失** |
| 4 | `ctx.enabled` 为假 | `:234-235` | 上下文未启用 |
| 5 | `cwd` 为空 | `:236-237` | 参数缺失 |
| 6 | **`raw_targets` 为空**（命令不含可识别的破坏性目标） | `:242-243` | **识别失败** |

另有**第 7 条来自上层**（`bash_tool.py:608-609` 注释原文）：

```python
			# registry 直通路径生产者线程无 rewind ctx（Phase A 已知缺口）；
			# 仅登记失败落回日志文件后台时做 before 快照保护。
```

即**后台命令走 registry 直通路径时不守卫**（见 0226）。再叠加 `plan_destructive_snapshot` 的 fail-open 包装（`:220-224`）：

```python
	try:
		return _plan(command, cwd, ctx)
	except Exception:  # noqa: BLE001 — fail-open：保护失效绝不能拖垮 Bash 工具
		_log.warning("destructive guard plan failed; fail-open", exc_info=True)
		return None
```

**任何内部异常也归入「不守卫」**（第 8 条，作为上面各条的兜底）。

**为什么都是「静默」降级**：

| 观察面 | 是否有信号 |
|---|---|
| 命令的执行结果 | **无差异**——照常执行、返回正常输出与退出码 |
| 工具结果文本 | **无差异**——不追加「未快照」之类说明 |
| 日志 | ⚠️ 只有**异常路径**打 `_log.warning`（`:223`）；**正常早退的六条一条日志都没有** |
| 审计 | ⚠️ 结算函数在 `plan is None` 时**直接返回**（`:353-354`：`if plan is None or plan.settled: return`）→ 没有 plan 就没有任何审计痕迹 |
| 模型可见面 | 无（符合「不向模型输出劝告文本」的铁律） |
| 用户可见面 | 无（除非用户事后发现「没有恢复点」） |

★ 也就是说：**「本次删除没有被快照」这件事，在任何地方都没有记录**。用户只会在需要恢复时（发现恢复点不存在）才知道——而那时**已经太晚**。

**对「恢复能力」承诺的影响**：

| 层面 | 实际 |
|---|---|
| 项目对外宣称：「破坏性命令有 before 快照，可回溯」 | ⚠️ **有条件**：需 rewind 可用 + 上下文启用 + 目标可识别 + 前台路径 + 未超文件/字节上限（0206） |
| 用户心智模型 | 「删了还能恢复」 |
| 实际保证 | 「**在多数常见情况下**能恢复；但系统不会告诉你这次是否被保护」 |

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题的核心是**「保护类机制的可用性必须可观测」**。当前降级设计遵循一条明确原则（fail-open + 不打扰），它对**执行**是正确的（0239 已论证：保护失效不能拖垮工具），但对**信任**有代价：

```
执行正确性  ← fail-open 是对的（工具必须能用）
恢复可信度  ← 需要「这次有没有保护」的可见事实
```

两者**不冲突**：可以既 fail-open（照常执行），又**留下一条审计事件**（例如 `bash.destructive.unguarded` + 原因码）。当前实现缺的正是后半句——那些精确的原因（「registry 直通路径生产者线程无 rewind ctx（Phase A 已知缺口）」）**只写在源码注释里**，没有变成运行时事实。

★ 与项目里**做对了的对照**：`ToolRegistry._apply_output_budget` 在 spill 时写审计（`default_audit_log().record("tool.spill", ...)`，B04-0196）；`runtime.maybe_advance_aging_boundary` 也写 `memory.aging.advance`（B09-0424）。也就是说**同项目里其他「增强型行为」都留了审计**，而破坏性守卫的降级没有——这是一个**可对照、可执行**的改进方向。

第二个值得记的点：**六条早退里有三条是「依赖/环境缺失」（1、3、5）**，而这三条在**评测容器 / CI / 纯引擎场景**下**极易同时成立**（无 rewind 上下文、无 cwd）。即：**在最需要保护的高危自动化场景里，守卫恰恰最可能不生效**。这与 `jobs_bridge` 注释里的「CLI in-process 无 server」是同一类环境差异——但那份注释至少显式说明了降级后的行为「逐字节不变」，这里没有说明。



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

### XEYO-QA-0250 【超压·场景分析】三层输出治理的顺序与证据链

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | 输出治理总账 | 顺序与证据可达性 | 超压 | 场景设计 | `cmd_compact.py:55-83` + `truncate.py:61-96` + `tools/meta.py:138-155` + `tool_registry.py:204-234` |

**面试官提问**
从「进程吐出字节」到「模型看到的文本」，Bash 的输出经历了几道处理？请给出**顺序**、每道的**证据可达性**（被丢弃的内容还能不能拿到原文），并回答一个关键问题：**当模型看到 `[output truncated, full at <path>]` 时，那个 `path` 里的内容是什么阶段的产物？**

**参考答案要点**
**四道处理（顺序）**：

```
① 逐块解码（_decode）                 runner.py:224-239（泵线程逐行）
        ↓  text（已解码的行序列）
② 语义压缩（compact_command_output）  cmd_compact.py:55-83
        ↓  compacted（可能回滚为原文）
③ 体积截断 + 落盘（truncate_for_model）truncate.py:61-96
        ↓  给模型的文本 + full_path
④ registry 预算                       ❌ 豁免（meta.py output_budget=0，见 0242）
        ↓
   模型看到的文本
```

**每道的证据可达性**：

| 道 | 有损？ | 被丢弃的内容还能拿到吗 | 依据 |
|---|---|---|---|
| ① `_decode` | 有损（编码回退可能出错） | **不能**——原始字节不再保留（且「错误的成功」无提示） | `runner.py:100-105` |
| ② `cmd_compact` | 有损（丢通过行） | ⚠️ **部分**：**压缩前的文本不落盘**。若不变式（0238）回滚则无损；若压缩生效，被丢掉的通过行**无处可取** | `cmd_compact.py:56` docstring：「**不改原命令、不落盘**」 |
| ③ `truncate_for_model` | 有损（裁中间） | ✅ **能**——全文落盘到 `persist_dir/bash-<uuid>.txt`，路径写进标记 | `truncate.py:79-95` |
| ④ registry | 豁免 | — | `meta.py:149`（`output_budget=0`） |

**关键问题的答案**：**`full at <path>` 里的 `path` 是「②压缩之后」的内容，不是进程的原始输出。**

推理链：

1. `truncate_for_model` 的入参是 `text`（`truncate.py:61-66`），它把 `text` 落盘（`:81-82`），再把 `text` 的头尾给模型；
2. 那么在调用它之前，`text` 是否已过 `cmd_compact`？——从职责看**是**：`cmd_compact.compact_command_output` 的 docstring 明确「返回给模型看的压缩文本」（`:56`），即它是**渲染给模型**的一环；`truncate_for_model` 也产出「给模型看的文本」；
3. 因此**落盘的是「压缩后」的文本**——被压缩器丢掉的通过行**不在这个文件里**。

★ 这一点极易误读：模型看到 `full at <path>` 的自然理解是「这里能拿到**完整**输出」，而实际拿到的是「**压缩后的完整**输出」。若一个测例有 5,000 行通过行 + 30 行失败，压缩可能把它压成 60 行；这 60 行若仍超 `DEFAULT_LIMIT = 30_000` 才触发落盘，落盘的是**那 60 行的完整版**——原来 5,000 行**永久不在任何文件里**。

**证据链的完整结论**（按「还能不能拿回原始字节」排序）：

| 阶段 | 原始字节是否可达 |
|---|---|
| 进程原始 stdout（未解码） | ❌ **任何情况下都不可达**（`_decode` 后即丢） |
| 解码后的完整文本（压缩前） | ❌ **不落盘**（除非压缩未生效，此时等于 ③ 的落盘内容） |
| **压缩后的文本（截断前）** | ✅ 当 ③ 触发落盘时可达（`full at <path>` 指向它） |
| 截断后的头+尾 | ✅ 就是模型看到的那份 |

即：**「全量原文」在 Bash 工具里其实不存在三个层次，只有一个「压缩后的完整文本」**——而它的**标记措辞是 `full`**（0242 已从 registry 侧指出 `full output` 措辞超范围，这里是同一问题在 Bash 内部的表现）。

**深化讲解**（面试官参考，不要求候选人全说）
这道超压题要把**「有损链条上每一道都损了什么、还能不能补救」**做完。三条结论：

**① 有损操作的顺序决定证据可达性。** 若把顺序反过来（先截断落盘、再压缩），落盘文件就**包含通过行**（证据更完整），代价是落盘体积大。

| 顺序 | 落盘内容 | 丢失内容 |
|---|---|---|
| **压缩 → 截断**（现状） | 压缩后文本 | 通过行（**不可达**） |
| 截断 → 压缩 | 原始文本 | 无（压缩只影响模型可见面） |

★ 这是一个**可被质疑的设计选择**：评测/调试场景往往需要「**看到全量**」（尤其「为什么这个测试没通过」需要看通过项与失败项的相对位置）。若改为「截断 → 压缩」（先落盘原文、再压缩给模型看），就能实现「模型看精简版、需要时读全量」，与 **spill 的纪律**（B04：「原始输出先落盘，截断只发生在模型可见投影」，`tools/spill.py:1-13`）**完全一致**。当前 Bash 内部的顺序与这条纪律**不一致**——这是本批提出的**最重要的一处结构性改进方向**。

**② `full at <path>` 的措辞需要在 Bash 内部也校准**（0242 已从 registry 侧提出同一问题）：

| 措辞 | 出现处 | 准确性 |
|---|---|---|
| `[output truncated, full at <path> (<n> chars)]` | `truncate.py:95` | ⚠️「full」= 压缩后的完整，非原始 |
| `Complete match list (N paths) saved to: <path>` | `glob_tool.py:993` | ✅ 准确（确实落的是完整列表） |
| `[output truncated: 预算截断（非错误），原始 N 字符；full output: <path>]` | `tool_registry.py:214-215` | ⚠️ 同 registry 侧问题 |

全项目里「full」这个词被用于**三种精度**——统一口径是低成本改进（改成 `full compacted output` / `full tool result`）。

**③ 逐块解码使「原始字节」在第一道就不可逆地丢失**，而它的失效（编码猜错）是**静默**的（0236）。这条链上唯一「有提示」的损失是 ③ 的截断标记；①与②的损失**都无提示**（②有 `[compacted <family>]` 标注，但那只说「压缩过」，不说「丢了什么」）。



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

## 批次自检表（B05）

| 项 | 结果 |
|---|---|
| 题号连续性 | XEYO-QA-0201 – XEYO-QA-0250，**无跳号无重号**（脚本比对 201..250 无缺口） |
| 难度配比实测 | 简单 **14** / 中等 **18** / 困难 **13** / 超压 **5** = **50** |
| 问法分布 | 机制解释 22 / 场景设计 13 / 概念确认 10 / 代码阅读 2 / 故障排查 2 / 安全拷问 1 = **50** |
| 覆盖子模块 | `bash_tool.py`（常量 / 只读白名单与写判定 / 晋升与收尾窗 / 容器路由 / 净室 / registry 降级链）· `runner.py`（终止 / shell 解析 / 解码 / 流式句柄）· `destructive_guard.py` · `semantics.py` · `precheck.py` · `dup_redirect.py` · `timeout_map.py` · `truncate.py` · `background.py` · `win_job.py` · `pwsh7.py` · `jobs_bridge.py` · `cmd_compact.py` · `prompt.py` + 跨批引用 `tools/meta.py`/`tool_registry.py` 预算段 —— 共 **14 个 bash_tool 文件 + 2 个跨批文件** |
| 缺陷基线复核 | 两条**一正一反**：① `TOOL-06`「POSIX 超时只杀 shell 不杀子进程树」**仍然成立**（锚点 `runner.py:81-82` 实测一致，见 0246）；② `TOOL-03`「docker 分支 `is_error` 恒 False 且丢退出码」**已不成立（文档过期）**——锚点仍指向 docker 分支，但该分支现为 `return BashOutput(code=out_code, ...)`，退出码完整保留、异常路径给 `code=95`（见 0248）。据此总结「锚点漂移 vs 结论过期」两类失效的区分方法 |
| 待确认条目 | **6 处**：① 0213 `_cleanup_old_logs` 的 `ttl_s` 是硬编码默认参数（非环境变量）；② 0233/0247 白名单成员的「危险选项」形态是否已被 `bash_writes_file` 或 B07 策略层覆盖；③ 0237 `WORKER_BASH_MAX_TIMEOUT_MS` 是否可被环境变量覆盖（若可则「花钱护栏」可绕过）；④ 0238 `_TRACE_HINT` 对 `npm ERR!` / `cargo error[E0308]` 的实测召回；⑤ 0244 `_CMD_PATTERNS` 的具体正则与顺序未实测；⑥ 0250 压缩与截断的**实际调用顺序**基于职责与 docstring 推断，未在结果渲染段逐行确认 |
| 边界遵守 | 未涉及 B07（`bash_policy` 规则引擎与三态裁决本体）、B14（`server/job_registry.py` 与 `/v1/jobs`）、B06（`job_tools` 工具面）、B11（rewind 快照本体）、B03（`wrap_window`/`process_ledger` 本体） |
| 未覆盖但已计划 | `precheck._FULLSCREEN` 成员清单、`dup_redirect.BashRoutePlan` 字段面与 `_routed_note` 文案、`cmd_compact` 六个压缩器的逐个行分类策略、`win_job.terminate/close` 完整实现、`pwsh7._parse_hashes_txt` 边界；容器后台三函数（`_docker_promote_seconds`/`docker_bg_snapshot`/`docker_bg_mark_delivered`）归 B19/B20 || 重复性检查 | 本卷题目考查点互不重复；与同能力域相邻卷的边界见上方「边界声明」 |
| 来源可追溯性 | 全部 50 题来源指向本批实际读过的 `文件:行号`；未出现推测性行号 |
