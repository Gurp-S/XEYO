# XEYO QA 题库 · 第 4 批（B04）

> 题号范围：**XEYO-QA-0151 – XEYO-QA-0200**
> 主题：文件工具族（Read / Write / Edit / Glob / Grep 五件套 · `tools/fileio/` 共享层 · 输出预算与 spill 回取旁路）
> 难度配比：简单 16 / 中等 18 / 困难 13 / 超压 3
> 事实基线（本批实际打开读过的文件与实测行数）：
> `file_read_tool.py`(687) · `vision_media.py`(180) · `file_read_tool/prompt.py`(21) · `file_write_tool.py`(516) · `file_edit_tool.py`(647) · `glob_tool.py`(1093) · `grep_tool.py`(938) · `fileio/text.py`(196) · `fileio/read_state.py`(145) · `fileio/paths.py`(72) · `fileio/conflict.py`(116) · `fileio/diff_preview.py`(56) · `fileio/syntax_check.py`(65) · `fileio/excludes.py`(119) · `fileio/rg_subprocess.py`(124) · `fileio/content_index.py`(170) · `fileio/content_index_cache_shadow.py`(145) · `fileio/__init__.py`(42) · `offload_read_tool.py`(62) · `spill.py`(117) · `spill_shadow.py`(77) · `meta.py`(414, 文件工具条目段) · `tool_registry.py`(636, 预算/patch 段) · `tests/test_file_tools_contract.py`(346) · `tests/test_glob_optimize.py`(550, 摘要与缓存段)
> **边界声明**：Bash 工具族（`bash_tool/` 12 件、容器路由、破坏性守卫、超时表）归 **B05**；权限裁决（`permissions/policy`、`filesystem` 路径狱、`bash_policy`）归 **B07**——本批只从「工具内 `check_permissions` 调用点与 fail-open/fail-closed 取向」角度涉及，不裁决三态语义；`write_store`/`workspace_lock`/`workspace_revision` 归 **B03**——本批只讲「文件工具如何接入它们」；`grep output_mode="symbols"` 背后的 `codeindex.symbols` 符号索引归 **B15**；`memdir`/`journal` 等记忆工具归 **B09/B10**。
> **行号口径**：`glob_tool.py` / `grep_tool.py` 的题面行号以本批 Read 时的文件状态为准（两文件行数分别为 1093 / 938）；`docs/全项目BUG排查-20260910.md` 中的 `glob_tool.py:656-658`、`grep_tool.py:634-644` 等锚点属于**更早版本**，本批已逐条复核并改写为当前行号，差异见自检表「待确认条目」。

---

## 本批题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0151 | 简单 | 概念确认 | Read 三层尺寸/令牌闸门常量 | `file_read_tool.py:37-38` + `prompt.py:9` |
| 0152 | 简单 | 概念确认 | Read 图片扩展名白名单 | `file_read_tool.py:40` |
| 0153 | 简单 | 概念确认 | Read 拒绝目录的异常类型 | `file_read_tool.py:389-392` |
| 0154 | 简单 | 机制解释 | `.ipynb` 的返回形态 | `file_read_tool.py:453-472` |
| 0155 | 简单 | 概念确认 | `cat -n` 行号前缀格式 | `fileio/text.py:79-91` |
| 0156 | 简单 | 概念确认 | unchanged-stub 的字面文案 | `file_read_tool/prompt.py:3-7` |
| 0157 | 简单 | 概念确认 | 写入路径必须先读的三个拒绝码 | `file_write_tool.py:264-272` + `file_edit_tool.py:372-380` |
| 0158 | 简单 | 概念确认 | `write_text_file` 的编码默认值 | `fileio/text.py:54-60` |
| 0159 | 简单 | 机制解释 | 三段式 stale 文案组成 | `fileio/conflict.py:92-109` |
| 0160 | 简单 | 概念确认 | `ReadFileState` 默认 LRU 容量 | `fileio/read_state.py:29-50` |
| 0161 | 简单 | 机制解释 | 写后语法自检的语言面与增量判据 | `fileio/syntax_check.py:25-65` |
| 0162 | 简单 | 机制解释 | `offload_read` 的行区间语义 | `offload_read_tool.py:46-62` |
| 0163 | 简单 | 机制解释 | spill 保留期默认与环境变量 | `spill.py:24-26,61-83` |
| 0164 | 简单 | 概念确认 | ENOENT 提示的优先级 | `fileio/paths.py:35-72` + `file_read_tool.py:377-387` |
| 0165 | 简单 | 概念确认 | 读取侧行尾归一化方向 | `fileio/text.py:22-23,50-51` |
| 0166 | 简单 | 概念确认 | Write 拒绝 `.ipynb` 的替代工具 | `file_write_tool.py:244-251` |
| 0167 | 中等 | 代码阅读 | offset 越界时的空切片路径 | `file_read_tool.py:505-511,542-557` |
| 0168 | 中等 | 机制解释 | `_persist` 两条路径的等价性 | `file_write_tool.py:152-158` 与 `fileio/text.py:62-64` |
| 0169 | 中等 | 机制解释 | `ReadFileState._key` 归一化动机 | `fileio/read_state.py:89-93` |
| 0170 | 中等 | 概念确认 | 12 个被阻断的设备文件 | `file_read_tool.py:79-104` |
| 0171 | 中等 | 机制解释 | 引号归一化的三段式匹配 | `fileio/text.py:94-111,154-170` |
| 0172 | 中等 | 机制解释 | `old_string=""` 的两个分支 | `file_edit_tool.py:347-370,444-468` |
| 0173 | 中等 | 机制解释 | 触碰即刷新的 LRU | `fileio/read_state.py:95-108` |
| 0174 | 中等 | 机制解释 | `.agentignore` 的后置 `--glob !rule` | `fileio/excludes.py:83-105` |
| 0175 | 中等 | 机制解释 | 外部归因的会话树排除 | `fileio/conflict.py:62-89` |
| 0176 | 中等 | 机制解释 | relaxed glob 的放宽规则 | `glob_tool.py:523-573` |
| 0177 | 中等 | 机制解释 | `lookup` 返回 `[]` 的充分性 | `fileio/content_index.py:144-170` |
| 0178 | 中等 | 机制解释 | 预算函数的 is_error 早退 | `tool_registry.py:179-190` |
| 0179 | 中等 | 代码阅读 | 陈旧分支的触发条件 | `file_write_tool.py:167-188` |
| 0180 | 中等 | 机制解释 | 贪婪 pattern 判定规则 | `glob_tool.py:195-212` |
| 0181 | 中等 | 机制解释 | `build_rg_args` 参数装配顺序 | `grep_tool.py:189-242` |
| 0182 | 中等 | 机制解释 | Read 态 LRU 的淘汰与刷新 | `fileio/read_state.py:100-108` |
| 0183 | 中等 | 代码阅读 | content 排序键与 `--` 分隔行 | `grep_tool.py:316-324,606-608` |
| 0184 | 中等 | 机制解释 | `Edit` 校验缓存两条清理路径 | `file_edit_tool.py:274-293,604-608` |
| 0185 | 困难 | 故障排查 | Glob 分页与大小写重试的分页混用 | `glob_tool.py:883` |
| 0186 | 困难 | 场景设计 | `Read` 的 `total_lines` 与尾随换行 | `file_read_tool.py:474-475` |
| 0187 | 困难 | 场景设计 | 同毫秒 mtime 下写入陈旧判定失效 | `fileio/text.py:17-19` |
| 0188 | 困难 | 场景设计 | `Read` 去重与老化开关的互斥 | `file_read_tool.py:357-375` + `engine/aging.py` |
| 0189 | 困难 | 场景设计 | content_index 的「全或无」超集保证 | `fileio/content_index.py:86-115` |
| 0190 | 困难 | 代码阅读 | 大小写重试与排除集的覆盖关系 | `glob_tool.py:238-255` |
| 0191 | 困难 | 场景设计 | 目录摘要的 git 跟踪态分区 | `glob_tool.py:312-422` |
| 0192 | 困难 | 场景设计 | `Glob` 60s 缓存与写后失效面 | `glob_tool.py:48-52,88-112` |
| 0193 | 困难 | 场景设计 | `content_index_cache_shadow` 的收益边界 | `fileio/content_index_cache_shadow.py:1-26,95-145` |
| 0194 | 困难 | 代码阅读 | Read 符号读取与 `pack` 的元数据面 | `file_read_tool.py:420-504` |
| 0195 | 困难 | 场景设计 | `diff_preview` 的 80 行上限 | `fileio/diff_preview.py:9,41-50` |
| 0196 | 困难 | 场景设计 | spill 的「预算截断 ≠ 失败」语义 | `tool_registry.py:202-234` |
| 0197 | 超压 | 故障排查 | Write 把 CRLF 全量改写成 LF | `file_write_tool.py:319,372` |
| 0198 | 超压 | 故障排查 | Grep count 在分页下的「总数」少报 | `grep_tool.py:625-653,793-806` |
| 0199 | 超压 | 场景设计 | 三方缓存与写后失效面总账 | `glob_tool.py` + `fileio/content_index.py` + `fileio/read_state.py` |
| 0200 | 超压 | 安全拷问 | 非对称路径校验：Read 有门、offload_read 无门 | `offload_read_tool.py` + `file_read_tool.py:346-347` |

---

### XEYO-QA-0151 Read 的三层输入闸门

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead 尺寸/令牌闸门 | 读取上限常量 | 简单 | 概念确认 | `python/tools/file_read_tool/file_read_tool.py:37-38` + `python/tools/file_read_tool/prompt.py:9` |

**面试官提问**
`Read` 在真正读盘前后设了若干「上限常量」。关于这些常量的数值？
**参考答案要点**
**正解：A（磁盘文件上限 0.25 MiB（`MAX_SIZE_BYTES`）、粗估令牌上限 25,000（`DEFAULT_MAX_TOKENS`）、无 `limit` 时默认读 2000 行（`MAX_LINES_TO_READ`））**
`file_read_tool.py:37-38`（原文）：

```python
# 上限 0.25 MiB
MAX_SIZE_BYTES = int(0.25 * 1024 * 1024)
DEFAULT_MAX_TOKENS = 25_000
```

`file_read_tool/prompt.py:9`：

```python
MAX_LINES_TO_READ = 2000
```

三个常量作用点与**触发条件**各不相同，这是本题的关键：

| 常量 | 值 | 检查位置 | 触发条件（原文所限） |
|---|---|---|---|
| `MAX_SIZE_BYTES` | `262144`（0.25×1024×1024） | `file_read_tool.py:444` | `size > MAX_SIZE_BYTES and limit is None and sym is None` |
| `DEFAULT_MAX_TOKENS` | `25_000` | `file_read_tool.py:514` | 对**切片后**文本粗估 `max(1, len//4)` 超限 |
| `MAX_LINES_TO_READ` | `2000` | `file_read_tool.py:508` | 仅当 `limit is None` 时作为 `effective_limit` |

**边界（易错三处）**：

1. **0.25 MiB 闸门有三个「豁免」而非一个**：只要给了 `limit`，或走了 `symbol` 分支（`sym is not None`），大文件预检整体跳过——注释写明理由是「symbol 读取先定位（不受整文件大小预检限制——返回的只是符号体）」（`file_read_tool.py:420`）。
2. **令牌上限用的是粗估而非真分词**：`_rough_token_estimate` 是 `len(content) // 4`，文件头 `TODO: [token] API 级 token 计数（现用 chars/4 粗估）`（`file_read_tool.py:5`）自认这是近似；中文/代码混合场景该系数会显著失真。
3. **两者不可互推**：0.25 MiB 纯 ASCII ≈ 65,536 令牌 > 25,000；但对**已切片**的小文件，是令牌闸门先触发还是尺寸闸门先触发，取决于给不给 `limit`——给了 `limit` 就只剩令牌闸门。

**深化讲解**（面试官参考，不要求候选人全说）
这道题考「同一工具上叠了多层上限，每层的触发条件不同」。把常量背下来没有意义，必须能答出**哪一层在什么前提下会说话**：

- 尺寸闸门问的是「整文件有多大」→ 所以它能被 `limit` 绕过（因为此时不读整文件）；
- 令牌闸门问的是「这次真正要吐出去的文本有多大」→ 所以它管的是切片后结果，**绕不过**，只能靠更小的 `offset`/`limit` 或改用 `symbol`/`Grep`；
- 行数默认值只是「你没说读多少」时的缺省，本身不是限制——`limit` 写多大就多大（另一侧的上限来自令牌闸门）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「磁盘文件上限 1 MiB、令牌上限 100,000、默认读 500 行」——说明没抓住本题的分界（B）。
- 答成「磁盘文件上限 0.25 MiB、令牌上限 200,000、默认读 2000 行」——说明没抓住本题的分界（C）。
- 答成「磁盘文件上限 8 MiB、令牌上限 25,000、默认读 1000 行」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0152 Read 的图片扩展名白名单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead vision 分流 | 图片扩展名白名单 | 简单 | 概念确认 | `python/tools/file_read_tool/file_read_tool.py:40` |

**面试官提问**
`Read` 用 `IMAGE_EXTENSIONS` 与 `BINARY_EXTENSIONS` 两个集合把扩展名分成三档（图片 / 二进制 / 文本）。下列**属于** `IMAGE_EXTENSIONS` 的是哪些？请完整列举。

**参考答案要点**
**A、B、D、E**。

`file_read_tool.py:40`（原文）：

```python
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
```

五个成员：`png` / `jpg` / `jpeg` / `gif` / `webp`。`svg` **不在其中**，也不在 `BINARY_EXTENSIONS`（`file_read_tool.py:41-77` 的清单里没有 `svg`）——因此 `.svg` 会走**文本读取**路径，按 UTF-8 解码后当 XML 文本给模型看。

三档的后续分流（`file_read_tool.py:394-413`、`593-596`）：

| 档 | 判定 | vision 关时 | vision 开时 |
|---|---|---|---|
| 图片 | `ext in IMAGE_EXTENSIONS` | `RuntimeError`（提示用 vision 模型或 `Screenshot`） | `asyncio.to_thread(self._execute_image, ...)` → 回传 data URL |
| PDF | `ext == "pdf"` | `RuntimeError` | `_execute_pdf`（页号取 `offset`） |
| 二进制 | `ext in BINARY_EXTENSIONS and ext not in IMAGE_EXTENSIONS` | 一律 `RuntimeError`（文案「Office/archives」引导用外部工具） | 同样 `RuntimeError`（vision 不解锁二进制） |

注意 PDF 是**独立的第三个分支**，不在 `IMAGE_EXTENSIONS` 里，也不在 `BINARY_EXTENSIONS` 里（后者的清单里确实列了 `pdf`，但 `IMAGE_EXTENSIONS` 分支在前、`ext == "pdf"` 分支居中、`BINARY_EXTENSIONS` 分支在最后，所以 `pdf` 不会落到二进制分支）。

**深化讲解**（面试官参考，不要求候选人全说）
白名单的作用是决定「走二进制通道还是文本通道」。`svg` 是刻意排除的：它是 XML 文本，按文本读反而更有信息量（能看到路径与样式）；而 `png` 这类位图按文本读只会得到乱码。

`validate_input` 与 `call` 在同一判据上有**两套文案**（前者报 `errorCode 4`，后者直接抛 `RuntimeError`）——模型看到的 message 不同但语义一致，这是「校验期拦截」与「执行期兜底」的分层，不是重复实现。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`svg`」——说明没抓住本题的分界（C）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0153 对目录路径调 Read 的异常类型

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead 输入校验 | 目录路径拒绝 | 简单 | 概念确认 | `python/tools/file_read_tool/file_read_tool.py:389-392` |

**面试官提问**
对**已存在的目录**调用 `Read`，`FileReadTool.call` 抛出的是：

**参考答案要点**
**正解：A（`IsADirectoryError`，文案含 `Path is a directory, not a file: <file_path>`）**
`file_read_tool.py:389-392`（原文）：

```python
		if os.path.isdir(full):
			raise IsADirectoryError(
				f"Path is a directory, not a file: {input_data.file_path}"
			)
```

并且 `execute` 层对它的处理是**统一兜底**（`file_read_tool.py:607-608`）：

```python
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=str(e), is_error=True)
```

也就是说，`IsADirectoryError` 既没有被 `validate_input` 提前拦截，也没有被专门处理——它靠 `except Exception` 落成 `is_error=True` 的工具结果。

顺序上是**先文件后目录**：`call` 先查 `os.path.exists(full)`（`:377`，不存在则抛 `FileNotFoundError`），再查 `os.path.isdir`（`:389`）。所以一个**不存在的目录路径**得到的是 `FileNotFoundError`，只有**真实存在的目录**才会走到 `IsADirectoryError`。

用哪个工具查目录本身，`Read` 的描述里已给答案（`file_read_tool/prompt.py:14`）：「Not for directories (use Glob/Bash)」。

**深化讲解**（面试官参考，不要求候选人全说）
本题的价值在于「错误类型即线索」：目录不是「文件不存在」，也不是「权限不足」，而是**调用对象类型错了**。工具把这个事实用异常类型如实表达，再由 `execute` 的宽兜底转成文本结果。

顺带一个架构观察：`Read` 的 `validate_input` 里**没有**目录检查（`file_read_tool.py:250-344` 只查 file_path 非空、UNC 短路、扩展名三档、设备文件、offset/limit 范围、symbol/pack 组合），目录与不存在都由 `call` 阶段抛。这与 `Glob` 的 `validate_input`（用 `os.path.exists` + `os.path.isdir` 给出 `errorCode 1/2`，`glob_tool.py:779-795`）风格不同——同一工具面里两套校验分层，是历史演进的结果。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`FileNotFoundError`」——说明没抓住本题的分界（B）。
- 答成「`PermissionError`」——说明没抓住本题的分界（C）。
- 答成「`RuntimeError`，文案含 `ephemeral`」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0154 `.ipynb` 的返回形态

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead notebook 分流 | `.ipynb` cell 摘要 | 简单 | 机制解释 | `python/tools/file_read_tool/file_read_tool.py:453-472,656-687` |

**面试官提问**
用 `Read` 读一个 `.ipynb` 文件时，工具返回给模型的内容是完整 JSON 吗？`read_state` 里存的是什么？摘要的行数是怎么算出来的？

**参考答案要点**
**不是。模型看到的是 cell 索引摘要；`read_state` 里存的是完整 JSON 原文。**

`file_read_tool.py:453-472`（原文）：

```python
		# .ipynb：完整 JSON 存入 read_state；返回 cell 索引摘要。
		if ext == "ipynb":
			mtime = get_mtime_ms(full)
			self._read_state.set(
				full,
				FileStateEntry(
					content=content,
					timestamp=mtime,
					offset=None,
					limit=None,
				),
			)
			summary = _notebook_cell_summary(content, input_data.file_path)
			return ReadOutput(
				type="text",
				file_path=input_data.file_path,
				content=summary,
				start_line=1,
				total_lines=summary.count("\n") + 1,
			)
```

三点事实：

1. **分流位置**：在 `read_text_file` 之后、通用 `all_lines = content.split("\n")` 之前（`:474`）。也就是说 `.ipynb` 的**尺寸/令牌闸门不完全适用**——注意 `size > MAX_SIZE_BYTES and limit is None` 的预检在更早的 `:444` 已经执行过，所以超大 notebook 仍会被尺寸闸门拦下；但令牌闸门（`:514`）在这条提前返回路径上**不会被求值**。
2. **摘要格式**（`_notebook_cell_summary`，`:656-687`）：首行给出文件路径、cell 总数与 `nbformat`，并显式引导用 `NotebookEdit`；随后逐 cell 一行 `[i] <cell_type>: <前 80 字符预览>`，预览中的换行被替换成字面 `\n`，空 cell 显示 `(empty)`。整体超过 **16,000 字符**时截断并附 `\n… truncated`。
3. **`total_lines` 的口径是摘要自身的行数**（`summary.count("\n") + 1`），**不是** notebook 原文件的行数。这是本批里少见的「`total_lines` 不等于源文件行数」的返回路径。

**深化讲解**（面试官参考，不要求候选人全说）
这条分流体现了「不同载体给不同投影」：notebook 是 JSON 容器，把整份 JSON 吐给模型既贵又难读，而模型真正需要的是「有哪些 cell、什么类型、大概内容」——于是原文留在 `read_state`（供 `NotebookEdit` 与写入前的先读校验使用），投影换成索引。

写侧是对称的：`Write` 明确拒绝 `.ipynb`（`file_write_tool.py:244-251`，转 `IPYNB_REJECT` 文案），`Edit` 同样拒绝（`file_edit_tool.py:312-319`）——改 notebook 只有 `NotebookEdit` 一条路。

**边界**：`json.loads` 失败时不是抛错，而是返回字符串 `Invalid notebook JSON in <path>: <err>`；`cells` 不是列表时返回 `Invalid notebook (no cells list): <path>`——两种「坏 notebook」都以 `type="text"` 正常返回，模型看到的是诊断句子而不是 `is_error`。



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

### XEYO-QA-0155 `cat -n` 行号前缀的格式

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 文本 | 行号前缀格式 | 简单 | 概念确认 | `python/tools/fileio/text.py:79-91` |

**面试官提问**
`Read` 返回的文本每行前缀形如 `     1→print("hi")`。这个前缀的生成规则是：

**参考答案要点**
**正解：B（行号右对齐、宽度 6、后跟 Unicode 箭头 `→`；当行号位数 ≥ 6 时不补齐）**
`fileio/text.py:79-91`（原文）：

```python
def add_line_numbers(content: str, *, start_line: int = 1) -> str:
	"""cat -n 风格：spaces + line number + arrow。"""
	if not content:
		return ""
	lines = content.split("\n")
	out: list[str] = []
	for i, line in enumerate(lines):
		num = str(i + start_line)
		if len(num) >= 6:
			out.append(f"{num}\u2192{line}")
		else:
			out.append(f"{num.rjust(6)}\u2192{line}")
	return "\n".join(out)
```

`\u2192` 即 `→`（Unicode U+2192），不是 ASCII 的 `->`。

**三个边界条件**：

1. **`start_line` 可偏移**：调用点传的是 `start_line=output.start_line`（`file_read_tool.py:547`），所以分页读取时行号是**源文件真实行号**，不是从 1 重新数。
2. **空内容提前返回空串**：`if not content: return ""`——所以「读到了空切片」这条路径不会产生任何行号行。
3. **位数 ≥ 6 时不补齐**：`rjust(6)` 只对位数 < 6 生效；超过 6 位（≥100000 行）时前缀比 6 列还宽，**列对齐会破**。代码选择「行号完整」优先于「列对齐」。

这个前缀还有个**下游契约**：`Edit` 的描述明确要求模型不要把它带进 `old_string`——`file_edit_tool/prompt.py:6`：「Match old_string exactly as in the file (never include Read's line-number prefix).」

**深化讲解**（面试官参考，不要求候选人全说）
这是一道「格式即契约」题。行号前缀同时服务三个目的：让模型能引用行号、让模型能定位分页起点、让 `Edit` 不被前缀污染。最后一条靠**提示词约束**而非代码强制——`find_actual_string`（`fileio/text.py:103-111`）只做引号归一化，不做行号剥离，所以模型若把 `     1→` 抄进 `old_string`，匹配会失败并报 `errorCode 8`。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「行号左对齐、宽度 6、后跟 ASCII 箭头 `->`」——说明没抓住本题的分界（A）。
- 答成「行号右对齐、宽度 4、后跟 `|`」——说明没抓住本题的分界（C）。
- 答成「行号 + Tab 分隔」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0156 unchanged-stub 的字面文案

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead 去重 | 未变化占位文案 | 简单 | 概念确认 | `python/tools/file_read_tool/prompt.py:3-7` |

**面试官提问**
`Read` 判定「同路径同区间且 mtime 未变」时，不重复返回正文，而是返回一段固定文案。这段话的核心意思是：

**参考答案要点**
**正解：B（「文件自上次读取后未变化；本次会话中更早的 Read 结果仍然有效，请参照它，不要重复读取」）**
`file_read_tool/prompt.py:3-7`（原文）：

```python
FILE_UNCHANGED_STUB = (
	"File unchanged since last read. The content from the earlier Read "
	"tool_result in this conversation is still current — refer to that "
	"instead of re-reading."
)
```

它在 `map_tool_result_to_content` 里被直接当作结果内容返回（`file_read_tool.py:543-545`）：

```python
	@staticmethod
	def map_tool_result_to_content(output: ReadOutput) -> str:
		if output.type == "file_unchanged":
			return FILE_UNCHANGED_STUB
```

**为什么这段文案要写成「陈述 + 指路」而不是「拒绝」**：工具结果是一条**事实**——「文件没变，你之前看到的内容仍然有效」。它没有说「你不该重复读」，而是给出「请参照那条结果」这个可执行的指向。这正是引擎铁律「注意力里只出现信息，不出现导演」在工具文案层的体现：不评价模型的行为，只提供状态。

**三个必须同时成立的判据**（`file_read_tool.py:361-373`，六条件缺一不可）：条目存在、`symbol is None`、**老化未开启**、非 `is_partial_view`、`offset` 与 `limit` 都相同、`get_mtime_ms(full) == existing.timestamp`。任一条不满足就真读。

**深化讲解**（面试官参考，不要求候选人全说）
顺带一个反向事实：`A` 选项描述的行为**恰好是另一处设计所明确避免的**——老化的注释（`file_read_tool.py:357-359`）写着：老化开启时**跳过去重**，因为 unchanged-stub 会指向「可能已被老化清除的早期读取结果」，让模型无从参照。也就是同一份代码里，「stub 指向的内容是否还在」是被认真对待的前提。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「「文件未变化，但内容已从上下文清除，请重新读取」」——说明没抓住本题的分界（A）。
- 答成「「文件未变化，已自动跳过；如需强制读取请加 `force=true`」」——说明没抓住本题的分界（C）。
- 答成「「读取被缓存，内容见 `/tmp` 下的临时文件」」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0157 写入前「必须先读」的拒绝面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Write/Edit 先读门禁 | 未读拒绝与部分视图拒绝 | 简单 | 概念确认 | `python/tools/file_write_tool/file_write_tool.py:264-272` + `python/tools/file_edit_tool/file_edit_tool.py:372-380` |

**面试官提问**
对**已存在**的文件调用 `Write` 或 `Edit`，如果模型没有先 `Read`，会被哪些条件拦下？请完整列举。

**参考答案要点**
**A、B**。

`file_write_tool.py:264-272`（原文）：

```python
		entry = self._read_state.get(full)
		if not entry or entry.is_partial_view:
			return {
				"result": False,
				"message": (
					"File has not been read yet. Read it first before writing to it."
				),
				"errorCode": 2,
			}
```

`file_edit_tool.py:372-380`（原文）：

```python
		entry = self._read_state.get(full)
		if not entry or entry.is_partial_view:
			return {
				"result": False,
				"message": (
					"File has not been read yet. Read it first before writing to it."
				),
				"errorCode": 6,
			}
```

**两个工具用同一条件、不同错误码**（Write `errorCode 2`、Edit `errorCode 6`）。

关于 `C`：文件**不存在**时 Write 反而放行——`file_write_tool.py:253-255` 的原文注释就写着 `# 新文件：无需先读`。`Edit` 稍微复杂：文件不存在且 `old_string == ""` 也放行（`:348-350`），这是「创建新文件」语义；文件不存在而 `old_string != ""` 才报 `errorCode 4`（`File does not exist...`）。

关于 `B` 的成因：`Read` 只有在**非符号读取**时才把 `offset`/`limit` 落进 `read_state`（`file_read_tool.py:523-531`），而 `is_partial_view` 是 `FileStateEntry` 的独立字段（`fileio/read_state.py:16`），当前 `Read` 的写入路径**未显式置位**它——置位发生在别的入口（如 `WorkingSnapshot` sidecar 相关路径）。这是一个「字段存在、主路径不写」的状态，读代码时容易误判为死字段。

**深化讲解**（面试官参考，不要求候选人全说）
先读门禁的目的不是「要求模型守规矩」，而是**保证写入有可比较的基线**：`Write` 是整文件替换、`Edit` 是精确串替换，两者都需要一个「我看到的版本」作参照，否则模型可能在陈旧认知上动手。配套的陈旧检测（`mtime > timestamp` 的分支）就建立在这个条目之上。

注意这道门禁是**工具内**的（`validate_input` 返回 `result: False`，`execute` 转成 `is_error=True`），与权限层的 `check_permissions`（`file_write_tool.py:308-309` 转发到 `permissions.filesystem`）是两条独立门——顺序上先校验后权限（`execute` 里 `validate_input` 在前、`check_permissions` 在后，`:462-470`）。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「文件不存在（ENOENT）」——说明没抓住本题的分界（C）。
- 答成「内容里有中文」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0158 `write_text_file` 的编码默认值

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 文本写 | 编码与行尾参数 | 简单 | 概念确认 | `python/tools/fileio/text.py:54-76` |

**面试官提问**
`write_text_file` 的签名参数中，`encoding` 与 `line_endings` 的默认值分别是：

**参考答案要点**
**正解：A（`encoding="utf-8"`、`line_endings="LF"`）**
`fileio/text.py:54-60`（原文）：

```python
def write_text_file(
	path: str,
	content: str,
	*,
	encoding: str = "utf-8",
	line_endings: LineEnding = "LF",
) -> None:
	"""写入文本；按 line_endings 还原换行。"""
```

两个参数都是**仅关键字**（`*` 之后），且函数体第一件事是把内容按 LF 归一化再按 `line_endings` 还原（`:62-64`）：

```python
	to_write = normalize_newlines(content)
	if line_endings == "CRLF":
		to_write = "\r\n".join(to_write.split("\n"))
```

然后是 **UTF-16 专有分支**（`:68-74`）：

```python
	# utf-16-le 编码器不写 BOM：不带 BOM 的 UTF-16 文件下一次 Read 检测
	# 不到编码（首字节不是 FF FE），会按 utf-8 解码成乱码。原文件带 BOM
	# （Read 就是靠它识别的），写回时必须补上。
	if encoding == "utf-16-le":
		with open(path, "wb") as f:
			f.write(b"\xff\xfe" + to_write.encode("utf-16-le"))
		return
	with open(path, "w", encoding=encoding, newline="") as f:
		f.write(to_write)
```

这条注释说明了一个完整的**往返一致性**闭环：`read_text_file` 靠首两字节 `FF FE` 识别 UTF-16（`:39-41`），`write_text_file` 就必须把 BOM 补回去，否则下一次 Read 会按 UTF-8 解码成乱码——写坏的文件会「看起来像新文件」。

LF 分支用 `newline=""` 打开（不做平台换行翻译），保证写出的字节与 `to_write` 逐字节一致；这也解释了 `Write`（`file_write_tool.py:372`）为什么必须**硬编码** `line_endings="LF"` 才能保持「写什么就是什么」。

**深化讲解**（面试官参考，不要求候选人全说）
默认值 `LF` 是**跨平台确定性的选择**（Windows 上 Python 文本模式默认会把 `\n` 翻译成 `\r\n`，`newline=""` 关掉了这个翻译）。默认 `utf-8` 是无 BOM 的 UTF-8——与 `read_text_file` 的 `data.decode("utf-8", errors="replace")` 配对。

但默认值不等于调用点的实际取值：`Edit` 会把 `validate_input` 期间探测到的 `endings` 传进来（`file_edit_tool.py:520`），`Write` 则固定传 `"LF"`（`file_write_tool.py:372`）——**这正是批内超压题 0197 的根因所在**。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`encoding="utf-8"`、`line_endings="CRLF"`」——说明没抓住本题的分界（B）。
- 答成「`encoding="utf-16-le"`、`line_endings="CRLF"`」——说明没抓住本题的分界（C）。
- 答成「无默认值，两参数均必填」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0159 陈旧拒绝消息的三段式组成

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 冲突归因 | stale 消息组装 | 简单 | 机制解释 | `python/tools/fileio/conflict.py:92-109` |

**面试官提问**
`build_stale_message` 把一条「文件已被修改」的拒绝升级成了三段信息。这三段分别是什么？各段的生成函数是谁？

**参考答案要点**
`fileio/conflict.py:92-109`（原文）：

```python
def build_stale_message(
	base: str,
	cwd: str,
	abs_path: str,
	self_session_id: str,
	snapshot: str,
	current: str,
) -> str:
	"""组装完整拒绝消息：base + 行范围摘要 + 外部归因 + 重放指令。"""
	parts = [base]
	line_hint = line_range_summary(snapshot, current)
	if line_hint:
		parts.append(line_hint)
	attr = external_attribution(cwd, abs_path, self_session_id)
	if attr:
		parts.append(attr.strip())
	parts.append("Read the file again, then re-apply your intended change onto the current content.")
	return "\n".join(parts)
```

四段（第 1、4 段是固定项，中间两段可省）：

| 段 | 内容 | 生成者 | 省略条件 |
|---|---|---|---|
| ① base | 调用方传入的原始原因（如 `File has been unexpectedly modified. Read it again...`） | 调用方（`file_write_tool.py:30-31` / `file_edit_tool.py:39-41`） | 从不省 |
| ② 行范围摘要 | `Your snapshot differs from disk at lines 12-14 (changed), line 30 (added on disk).` | `line_range_summary`（`conflict.py:21-52`） | 无差异 → `""` |
| ③ 外部归因 | `Suspicious: another session「<标题>」wrote this file recently (14:22).` | `external_attribution`（`conflict.py:62-89`） | 无外部写入者 / 同会话树 → `""` |
| ④ 重放指令 | `Read the file again, then re-apply your intended change onto the current content.` | 本函数内置 | 从不省 |

②的行号口径是**磁盘版本**（`j1`/`j2` 是 `SequenceMatcher` 的 b 侧索引），注释写明理由：「用行号区间描述差异所在的"磁盘版本"行（模型将要 read 到的行）」（`conflict.py:30`）。三类差异用三种后缀表达：`(changed)` / `(removed in disk)` / `(added on disk)`。②还会**限幅到 6 段**并附 `(+N more sections)`（`conflict.py:50-52`）。

③的关键实现是**会话树排除**：`session_tree_root(owner.session_id) == session_tree_root(sid)` 时返回空串，注释写「同一会话树（含本会话子 agent）写入：不算外部，交旧提示兜底」（`conflict.py:80-84`）。

**深化讲解**（面试官参考，不要求候选人全说）
这条消息是「拒绝也要可行动」的样板：不告诉模型「你错了」，而是给三个事实——差异在哪几行、可能是谁改的、下一步做什么。③尤其克制：只有**确认是另一个会话树**才说 `Suspicious`，同会话树内部（含子 agent）写入一律沉默，避免自家人写自己家文件却被归因为「可疑」。

**边界**：③依赖 `session_presence` 注册表，取不到 `owner` 或抛异常都返回 `""`（`conflict.py:76-79`），即**归因失败静默降级**——拒绝本身不受影响。



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

### XEYO-QA-0160 `ReadFileState` 的默认容量

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 读态账本 | LRU 容量与环境覆盖 | 简单 | 概念确认 | `python/tools/fileio/read_state.py:29-50` |

**面试官提问**
`ReadFileState` 的默认条目上限是多少？可以用什么手段改？

**参考答案要点**
**正解：B（默认 128，可用环境变量 `XEYO_READ_STATE_MAX_ENTRIES` 覆盖，且下限被夹到 8）**
`fileio/read_state.py:29-50`（原文）：

```python
def _max_entries_from_env(default: int = 128) -> int:
	raw = os.environ.get("XEYO_READ_STATE_MAX_ENTRIES", "").strip()
	if not raw:
		return default
	try:
		return max(8, int(raw))
	except ValueError:
		return default


class ReadFileState:
	"""按绝对路径缓存已读文件快照（同一 registry / session 共享）。

	条目含文件全文（供 Edit 校验先读），必须限幅：超出 max_entries 时
	按 LRU 淘汰最久未访问的路径，防止长会话内存无界增长。
	"""

	def __init__(
		self, *, max_entries: int | None = None, conversation_id: str = ""
	) -> None:
		self._entries: dict[str, FileStateEntry] = {}
		self._max_entries = max(8, int(max_entries or _max_entries_from_env()))
```

三条事实：

1. **默认 128**（`_max_entries_from_env(default=128)`）；
2. **两级覆盖**：构造参数 `max_entries` 优先（`max_entries or _max_entries_from_env()`），环境变量次之——注意用的是 `or`，所以传 `0` 会**落回环境变量/默认值**而不是「无上限」；
3. **下限 8**：`max(8, ...)` 在**两处**都出现（环境解析里一次、`__init__` 里一次），并且 `int(raw)` 解析失败时回退默认值。

容量存在的理由是注释里的那句：**条目含文件全文**（供 `Edit` 校验先读），所以它是内存占用的大头，必须限幅。

**边界**：`max_entries or ...` 意味着**无法通过参数把容量设成 0 或负数**（会被 `or` 短路成默认值）。若真的想要极小容量，只能通过环境变量传 `1`→被 `max(8, …)` 夹到 8。

**深化讲解**（面试官参考，不要求候选人全说）
这是一个典型的「防御性默认」：默认值够大（128 个文件全文）覆盖常见会话，同时硬下限（8）防止有人把容量调到「连当前文件都留不住」的程度——如果容量小于正在编辑的文件数，`Edit` 会频繁报「File has not been read yet」，看起来像 bug 其实是配置事故。

测试对此有直接断言：`tests/test_file_tools_contract.py:267-275` 用 `monkeypatch.setenv("XEYO_READ_STATE_MAX_ENTRIES", "16")` 后写 20 条，断言 `f0.txt` 被淘汰、`f19.txt` 保留。**注意该测试用 16 而非 8**——正好避开下限夹取，所以它验证的是环境变量路径而不是夹取逻辑。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「无上限」——说明没抓住本题的分界（A）。
- 答成「默认 32，可用构造参数 `max_entries` 覆盖，无下限」——说明没抓住本题的分界（C）。
- 答成「默认 128，只能改代码常量」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0161 写后语法自检的语言面与增量判据

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 语法自检 | 语言面与增量判定 | 简单 | 机制解释 | `python/tools/fileio/syntax_check.py:25-65` + `python/tools/file_write_tool/file_write_tool.py:383-396` |

**面试官提问**
`Write` 落盘后会做一次「语法自检」并把错误细节带进工具结果。它覆盖哪些文件类型？什么情况下**不**提示？

**参考答案要点**
**只覆盖 `.py` 与 `.json`；旧内容也错时不提示。**

`fileio/syntax_check.py:27-32`（语言面，原文）：

```python
	suffix = os.path.splitext(str(file_path or ""))[1].lower()
	if suffix not in (".py", ".json"):
		return None
	if not isinstance(content, str) or len(content) > _MAX_PARSE_CHARS:
		return None
```

`fileio/syntax_check.py:59-65`（增量判据，原文）：

```python
def introduces_error(file_path: str, old_content: str, new_content: str) -> bool:
	"""增量判据：新内容有错且旧内容无错（旧也错 → 不提示，避免对烂文件唠叨）。"""
	if not isinstance(new_content, str) or not isinstance(old_content, str):
		return False
	if syntax_error_detail(file_path, new_content) is None:
		return False
	return syntax_error_detail(file_path, old_content) is None
```

调用点（`file_write_tool.py:383-396`）：

```python
		syntax_hint = ""
		try:
			from tools.fileio.syntax_check import introduces_error, syntax_error_detail

			prev = normalize_newlines(old_content) if old_content is not None else ""
			if introduces_error(full, prev, normalized):
				syntax_hint = (
					"Written file has a parse error — "
					+ str(syntax_error_detail(full, normalized) or "see linter")
				)
		except Exception:  # noqa: BLE001 — 自检失败不影响写盘主路径
			syntax_hint = ""
```

**四个「不提示」条件**：

1. 文件类型不在 `.py`/`.json`（如 `.ts`/`.tsx` 不查——尽管 `Write` 的 `_diagnostics_hint` 会为 `.ts/.tsx` 追加一行 `Hint: Diagnostics path=...`，那是另一条通道，见 `file_write_tool.py:509-516`）；
2. 内容长度 > `_MAX_PARSE_CHARS = 2_000_000`（`syntax_check.py:22`）；
3. 新内容**没有**语法错；
4. **旧内容也有**语法错 → `introduces_error` 返回 `False`，这是「增量」的核心：只提示**本次新引入**的错误。

另外整段被 `try/except Exception` 包住（`file_write_tool.py:395-396`）——**自检失败绝不影响写盘**，这是正确取向：写盘是主线，提示是附加信息。

**关键语义**：提示是 `Written file has a parse error — Python syntax error at line 3 column 5: def f( → invalid syntax` 这样的**事实陈述 + 定位**（`syntax_check.py:41-46`）。源码注释明确不裁决：「引擎只展示事实、不裁决 —— 是否重写由模型决定（产品语义：允许 WIP 写盘）」（`syntax_check.py:9`）。

**深化讲解**（面试官参考，不要求候选人全说）
「旧也错 → 不提示」这条规则值得细想：它避免了在模型处理一个本来就有语法错误的文件时（例如正在逐步修复）反复收到同一条抱怨。代价是：若模型把 `A 错误` 改成 `B 错误`，`introduces_error` 仍为 `False`（旧的有错），于是**错误变了却不提示**。这是一个设计取舍而非漏洞，但读代码时容易被当成漏检。



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

### XEYO-QA-0162 `offload_read` 的行区间语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | 按需读回外部化结果 | 行区间参数 | 简单 | 机制解释 | `python/tools/offload_read_tool.py:46-62` |

**面试官提问**
`offload_read` 接受 `path` / `start` / `end` 三个参数。`start`/`end` 的计数方式与缺省行为是什么？行超界时会发生什么？

**参考答案要点**
**`start` 为 1 起（含）、`end` 含；缺省 `start=1`、`end=0` 表示「到文件末尾」；超界时静默截断，不报错。**

`offload_read_tool.py:46-62`（原文）：

```python
	async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
		abort.raise_if_aborted()
		p = Path(str((input or {}).get("path") or "")).expanduser()
		if not p.is_file():
			return ToolResult(content=f"(offload 文件不存在: {p})", is_error=True)
		try:
			text = p.read_text(encoding="utf-8")
		except OSError as e:
			return ToolResult(content=f"(读取失败: {e})", is_error=True)
		start = int(input.get("start") or 1)
		end = int(input.get("end") or 0) or None
		lines = text.split("\n")
		if end:
			body = "\n".join(lines[max(0, start - 1):end])
		else:
			body = "\n".join(lines[max(0, start - 1):])
		return ToolResult(content=body)
```

逐点：

| 参数 | schema 描述 | 实现 |
|---|---|---|
| `path` | 外部化工具结果文件路径（必填） | `Path(...).expanduser()`，`is_file()` 不过是则报错 |
| `start` | 起始行（含，1 起） | `int(input.get("start") or 1)` → 缺省或 `0` 都得 `1` |
| `end` | 结束行（含） | `int(input.get("end") or 0) or None` → `0`/缺失 → `None` → 读到末尾 |

切片是 `lines[max(0, start - 1) : end]`——Python 切片本身**不报越界**，所以 `start` 超过文件行数会得到空串、`end` 超过行数会读到末尾。**唯一的越界保护是 `max(0, start - 1)`**（把负数 `start` 夹到 0）。

两个边界：

1. `start=0` 与 `start=1` 等价（`0 or 1` → `1`）；
2. 返回内容**无行号前缀**（不像 `Read` 会 `add_line_numbers`），所以模型拿到的是裸文本——这与它的用途一致（把外部化结果的原文原样取回，不做二次加工）。

`end` 的语义要小心：文档写「结束行(含)」，而切片是 `lines[start-1:end]`——取第 `start` 到第 `end` 行，含两端（因为 `end` 是开区间右端点，而行索引 `end-1` 对应第 `end` 行）。所以**语义与描述一致**。

**深化讲解**（面试官参考，不要求候选人全说）
这个工具的定位在模块 docstring 里写得很清楚（`offload_read_tool.py:1-6`）：它读的是被外部化的**超长工具结果**（`memory.offload` 存为 `.xeyo_offload/*.tool.txt`），`exposure=hidden`（不进 `tools` 数组，保 schema 冻结红线），但**保持注册**——「幻觉/按需调用仍经 `run()` 权限三态，fail-safe」。

最后那句「仍经 `run()` 权限三态」是本批超压题 0200 的落点：`run()` 会给它做**通用**策略裁决，但工具自身没有任何路径校验，见 0200。



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

### XEYO-QA-0163 spill 的保留期

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | 输出落盘 | 保留期与清理时机 | 简单 | 机制解释 | `python/tools/spill.py:24-26,61-83,113-116` |

**面试官提问**
`tools/spill.py` 会把超预算工具输出落盘。这些文件的默认保留期是多久？清理在什么时候发生？`days <= 0` 意味着什么？

**参考答案要点**
**默认 7 天；每次 `save_text` 顺带清理一次；`days <= 0` 表示不清理。**

`spill.py:24-26`：

```python
ENV_SPILL_DIR = "XEYO_SPILL_DIR"
ENV_RETENTION_DAYS = "XEYO_SPILL_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 7
```

`spill.py:61-83`（原文，`_prune_old`）：

```python
def _prune_old(root: Path, *, now: float | None = None) -> int:
	"""删除超过保留期的 spill 文件；返回删除数。尽力而为，不抛错。"""
	try:
		days = float(os.environ.get(ENV_RETENTION_DAYS, "").strip() or DEFAULT_RETENTION_DAYS)
	except ValueError:
		days = DEFAULT_RETENTION_DAYS
	if days <= 0:
		return 0
	cutoff = (now if now is not None else time.time()) - days * 86400.0
	removed = 0
	try:
		for dirpath, _dirnames, filenames in os.walk(root):
			for fn in filenames:
				p = Path(dirpath) / fn
				try:
					if p.stat().st_mtime < cutoff:
						p.unlink()
						removed += 1
				except OSError:
					continue
	except OSError:
		return removed
	return removed
```

调用时机（`spill.py:113-116`，在 `save_text` 末尾）：

```python
	try:
		_prune_old(spill_root())
	except Exception:  # noqa: BLE001 — 清理失败不影响保存
		pass
```

四个要点：

1. **判据是 `st_mtime < cutoff`**，即按**最后修改时间**而非创建时间；
2. **清理是以保存为触发点的机会式清理**——没有后台定时器。若长期不产生 spill，旧文件不会被清；
3. **`days <= 0` → 直接返回 0**：不是「立刻全删」，而是**关闭清理**。这是一个容易读反的分支；
4. **失败全部吞掉**：`float()` 解析失败回退默认值；单个文件的 `stat`/`unlink` 失败 `continue`；`os.walk` 失败返回已删数；外层再包一层 `except Exception`。定位是「尽力而为，不抛错」——绝不让清理影响保存。

**存储路径**：`spill_root()` 取 `XEYO_SPILL_DIR`，否则 `~/.xeyo/spill`（`spill.py:40-44`）；会话命名空间由 `_safe_session` 生成（冒号换 `__`、非 `[A-Za-z0-9._-]` 换成 `_`、去首尾 `._`、空则 `session`、截断 120 字符，`spill.py:47-58`）。落盘用 `O_EXCL` 独占创建（绝不覆盖已有证据）+ POSIX `0600`（`spill.py:98-107`）。

**深化讲解**（面试官参考，不要求候选人全说）
「机会式清理」这个选择与 spill 的用途相关：它是**证据**，不是缓存。删除太激进会毁掉「事后取回原文」的能力（模块注释：「宁可超预算，不可假证据」，`spill.py:11-12`），所以清理策略偏保守——只在明确产生新 spill 时才顺手动一次，且默认保留整七天。



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

### XEYO-QA-0164 文件不存在时的提示优先级

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 路径提示 | ENOENT 两级建议 | 简单 | 概念确认 | `python/tools/fileio/paths.py:35-72` + `python/tools/file_read_tool/file_read_tool.py:377-387` |

**面试官提问**
`Read` 遇到文件不存在时，会尝试给出 `Did you mean ...?` 建议。它用了两个不同的启发式函数，当两者都能给出建议时，**哪一个**会出现在消息里？

**参考答案要点**
**正解：B（`suggest_path_under_cwd`（工作区下同名项），它优先；只有它给不出时才用 `find_similar_file`）**
`file_read_tool.py:377-387`（原文）：

```python
		if not os.path.exists(full):
			suggestion = suggest_path_under_cwd(full, cwd=self._cwd)
			similar = find_similar_file(full)
			message = (
				f"File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {self._cwd}."
			)
			if suggestion:
				message += f" Did you mean {suggestion}?"
			elif similar:
				message += f" Did you mean {similar}?"
			raise FileNotFoundError(message)
```

是 `if / elif`——**两者互斥**，`suggestion` 优先。

两个函数的判据完全不同：

| 函数 | 位置 | 判据 | 返回 |
|---|---|---|---|
| `suggest_path_under_cwd` | `fileio/paths.py:35-54` | 目标路径的 **realpath** 位于「cwd 的父目录」之下但**不在 cwd 之内**（即典型的「少写了一层目录名」），然后在 cwd 下找**同名项**（不区分大小写） | cwd 下的完整路径 |
| `find_similar_file` | `fileio/paths.py:57-72` | 在**目标自身所在目录**下找「主名相同、扩展名不同」的文件（且必须是文件、不等于原路径） | 同目录下的近邻文件 |

`suggest_path_under_cwd` 的越界判定（`paths.py:37-45`）值得单独看：

```python
	cwd_parent = os.path.dirname(os.path.realpath(cwd))
	try:
		rp = os.path.realpath(target_path)
	except OSError:
		rp = os.path.abspath(target_path)
	sep = os.sep
	parent_prefix = sep if cwd_parent == sep else cwd_parent + sep
	if (not rp.startswith(parent_prefix)) or rp.startswith(cwd + sep) or rp == cwd:
		return None
```

即：**必须以「cwd 的父目录」为前缀**，且**不能已经在 cwd 内**，也不能就是 cwd 本身。这个条件比「在工作区外」窄得多——它专治「`D:\lea\XenYon code\python\xxx` 漏了中间的 `tools`」这类「少一层」错误（模型把相对路径理解错一层是常见失败模式）。

`cwd_parent == sep` 那个分支处理的是根目录场景（`os.path.dirname("C:\\")` 得 `"C:\\"`，`os.path.dirname("/")` 得 `"/"`），避免拼出 `//` 前缀。

**深化讲解**（面试官参考，不要求候选人全说）
「谁优先」体现了对失败模式的排序：**「少写了一层目录」比「扩展名写错」更常见**，而且前者一旦命中，给出的路径是**可直接使用的完整路径**；后者给的是同目录下的另一个文件，还需要模型自己判断是否真的想要那个。另外 `suggest_path_under_cwd` 是**工作区感知**的（它知道 cwd），而 `find_similar_file` 只是纯目录扫描。

**边界**：`find_similar_file` 在目录不可读（`OSError`）时静默返回 `None`；`suggest_path_under_cwd` 的 `os.listdir` 失败同样静默。两者都**不会**因为建议机制本身出错而改变「文件不存在」这个事实。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`find_similar_file`（同目录同名不同扩展名），因为它更精确」——说明没抓住本题的分界（A）。
- 答成「两个都出现在消息里」——说明没抓住本题的分界（C）。
- 答成「随机选一个」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0165 读取侧的行尾归一化方向

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 文本 | CRLF→LF 归一化 | 简单 | 概念确认 | `python/tools/fileio/text.py:22-23,31-51` |

**面试官提问**
`read_text_file` 返回的正文是归一化过的还是原样的？它同时还返回什么？

**参考答案要点**
**正解：B（归一化为 **LF**，同时返回探测到的 `LineEnding` 与编码名）**
`fileio/text.py:22-23`：

```python
def normalize_newlines(content: str) -> str:
	return content.replace("\r\n", "\n").replace("\r", "\n")
```

注意是**两步替换**：先 `\r\n`→`\n`，再**剩下的** `\r`→`\n`。顺序不能反——若先替换孤立 `\r`，会把 `\r\n` 拆成 `\n\n`。

`fileio/text.py:31-51`（原文）：

```python
def read_text_file(path: str) -> tuple[str, LineEnding, str]:
	"""
	读取文本文件。
	返回 (normalized_LF_content, original_line_endings, encoding_name)。
	"""
	with open(path, "rb") as f:
		data = f.read()
	encoding = "utf-8"
	if len(data) >= 2 and data[0] == 0xFF and data[1] == 0xFE:
		encoding = "utf-16-le"
		text = data.decode("utf-16-le")
		# BOM 不是内容：残留 \ufeff 会在 Edit old_string 匹配、哈希、
		# 每次写回时累积多一个 BOM。
		if text.startswith("\ufeff"):
			text = text[1:]
	else:
		text = data.decode("utf-8", errors="replace")
		if text.startswith("\ufeff"):
			text = text[1:]
	endings = detect_line_endings(text)
	return normalize_newlines(text), endings, encoding
```

三元组是 **(归一化后的 LF 正文, 原始行尾风格, 编码名)**。

三个细节：

1. **探测在归一化之前**：`detect_line_endings(text)` 拿的是**解码后、未归一化**的文本（`text.py:26-28`：`return "CRLF" if "\r\n" in text else "LF"`）——所以它才能看出原来是 CRLF。若顺序反过来，永远只能得到 `LF`。
2. **编码靠 BOM 猜，不靠魔数表**：只有 `FF FE` 开头才判 `utf-16-le`，其余一律 `utf-8` + `errors="replace"`。所以 GBK/Shift-JIS 文件会被「替换字符化」（不报错，但内容失真）。
3. **BOM 被显式剥掉**，理由在注释里写全了：残留 `\ufeff` 会污染 `Edit` 的 `old_string` 匹配、影响哈希、并在每次写回时**累积**多一个 BOM。

**深化讲解**（面试官参考，不要求候选人全说）
「读进来归一化成 LF，写出去按记录的 `LineEnding` 还原」是标准的两段式设计：内存里只有一种换行（比较、匹配、diff、哈希全部简化），磁盘上保留用户风格。

`Edit` 完整地实现了这个往返：`validate_input` 时把 `endings` 挂到 `_last_endings`（`file_edit_tool.py:434`），`call` 再传给 `_persist`（`file_edit_tool.py:519-521`）。`Write` **没有**——它固定传 `"LF"`（`file_write_tool.py:372`）。两者不一致，是本批超压题 0197 的核心。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「原样返回，不归一化」——说明没抓住本题的分界（A）。
- 答成「归一化为 **CRLF**，不返回编码」——说明没抓住本题的分界（C）。
- 答成「归一化依据平台：Windows 归一化为 CRLF」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。
### XEYO-QA-0166 Write 拒绝 `.ipynb` 后引导到哪个工具

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Write/Edit 载体限制 | `.ipynb` 拒绝文案 | 简单 | 概念确认 | `python/tools/file_write_tool/file_write_tool.py:244-251` + `python/tools/notebook_edit_tool/prompt.py:10-13` |

**面试官提问**
用 `Write` 写一个 `.ipynb` 文件会被拒绝，拒绝文案本身就包含「应该改用哪个工具」的指引。那个工具是：

**参考答案要点**
**正解：B（`NotebookEdit`（cell 级编辑））**
`file_write_tool.py:244-251`（原文）：

```python
		if full.lower().endswith(".ipynb"):
			from tools.notebook_edit_tool.prompt import IPYNB_REJECT

			return {
				"result": False,
				"message": IPYNB_REJECT,
				"errorCode": 6,
			}
```

`notebook_edit_tool/prompt.py:10-13`（文案原文）：

```python
IPYNB_REJECT = (
	"Jupyter Notebook (.ipynb) must be edited with the NotebookEdit tool "
	"(cell-level). Do not use Edit/Write on .ipynb."
)
```

**这道题真正要记住的是「同一句话管两个工具」**：`Edit` import 的是**同一个常量**（`file_edit_tool.py:312-319`，但错误码是 `5`）。所以 `Write` 与 `Edit` 在 `.ipynb` 上给出**逐字相同**的拒绝文案，只有错误码不同（6 vs 5）。

配套的对称设计还有三处：

1. `NotebookEdit` 自己的描述要求**先 Read**：「Read the .ipynb first (structured cell index). Do not use Edit or Write on .ipynb.」（`notebook_edit_tool/prompt.py:4-5`）；
2. `Read` 的 notebook 摘要首行显式带 `Use NotebookEdit with cell_idx below.`（`file_read_tool.py:668`）；
3. 判定用 `full.lower().endswith(".ipynb")`——**大小写不敏感**，且在 `expand_path` 之后对**绝对路径**判定，所以 `A.IPYNB` 也拦得住。

**深化讲解**（面试官参考，不要求候选人全说）
按扩展名分派载体不是通用规则，而是**针对「文本串替换会破坏结构」的载体制定的专规**。notebook 是 JSON + 数组结构，`Edit` 的字符串替换容易写出「合法 JSON 但语义错乱」的 notebook（例如只改 `cell_type` 而不同步 `outputs`），而 `NotebookEdit` 按 `cell_idx` 操作天然避开这类错误。

**边界（易漏）**：拒绝发生在 `validate_input` 内，位置在 **UNC 短路之前、ENOENT 检查之前**（`file_write_tool.py:240-255`）——也就是说，**即使目标文件还不存在**，只要扩展名是 `.ipynb` 也一律拒绝，不存在「用 `Write` 新建 notebook」这条路。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「`Edit`（逐串替换够用）」——说明没抓住本题的分界（A）。
- 答成「`Bash`（直接重定向写文件）」——说明没抓住本题的分界（C）。
- 答成「`Memory`（先存记忆再写）」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
请指出这个设计**原本要防的那个具体故障**是什么；它在没有这个机制时会以什么形式出现。

---

### XEYO-QA-0167 offset 越界时的返回路径

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead 切片边界 | offset 越界 | 中等 | 代码阅读 | `python/tools/file_read_tool/file_read_tool.py:505-511,542-557` |

**面试官提问**
给定一个 `total_lines` 为 10 的文件，调用 `Read(file_path=..., offset=50)`（不给 `limit`、不给 `symbol`）。返回给模型的文本是什么？为什么这里能区分「空文件」和「offset 越界」？

```python
		else:
			# offset 从 1 开始计数
			start_idx = max(0, offset - 1)
			effective_limit = MAX_LINES_TO_READ if limit is None else limit
			sliced = all_lines[start_idx : start_idx + effective_limit]
			slice_text = "\n".join(sliced)
			start_line_out = offset
```

```python
	@staticmethod
	def map_tool_result_to_content(output: ReadOutput) -> str:
		if output.type == "file_unchanged":
			return FILE_UNCHANGED_STUB
		if output.content:
			return add_line_numbers(output.content, start_line=output.start_line)
		if output.total_lines == 0:
			return (
				"<system-reminder>Warning: the file exists but the contents "
				"are empty.</system-reminder>"
			)
		return (
			f"<system-reminder>Warning: the file exists but is shorter than "
			f"the provided offset ({output.start_line}). The file has "
			f"{output.total_lines} lines.</system-reminder>"
		)
```

**参考答案要点**
返回**第二种** system-reminder：

```
<system-reminder>Warning: the file exists but is shorter than the provided offset (50). The file has 10 lines.</system-reminder>
```

推导链（每步落到代码）：

1. `start_idx = max(0, 50 - 1) = 49`（`:507`）；
2. `effective_limit = 2000`（`limit is None` → `MAX_LINES_TO_READ`，`:508`）；
3. `sliced = all_lines[49:2049] = []`（Python 切片越界不报错，`:509`）；
4. `slice_text = "\n".join([]) = ""`（`:510`）；
5. `tokens = _rough_token_estimate("") = 0`（`:107-108` 的 `if content else 0`）→ **不触发** 25,000 令牌闸门（`:514`）；
6. `start_line_out = 50`（`:511`）；`read_state` 记 `offset=50, limit=None`（`:523-531`）；
7. `ReadOutput(content="", start_line=50, total_lines=10)`（`:533-540`）；
8. `map_tool_result_to_content` 落到第三分支：`output.content` 为空 → 判 `total_lines`。

**关键在第 8 步的分支顺序**：

- 第一分支 `total_lines == 0` 专门捕获**真空文件**——`total_lines` 由 `len(all_lines) if content else 0` 得出（`:474-475`），只有全文为空串才是 0；
- 第二分支（落到末尾 `return` 的那个）捕获**「文件非空但短于 offset」**，并把 `start_line`（即模型给的 offset）与真实 `total_lines` 都念出来。

**若两个分支顺序反过来**（先查 `total_lines > 0`），越界读就会走进「文件内容为空」的警告，模型会误以为文件是空的——这是分支顺序存在的全部理由。

**深化讲解**（面试官参考，不要求候选人全说）
这段设计的意图是「**把模型传错参数这件事，变成一个可自我纠正的事实**」：不报 `is_error`，而是明确告诉它「文件有 10 行，你从第 50 行要起」。注意 `total_lines` 的口径（`:474-475`）在本题里被顺带暴露：`content.split("\n")` 在文件以换行结尾时会产生**尾随空串**，于是 `total_lines` 比「人类认为的行数」多 1——题设的「`total_lines` 为 10」应这样理解（展开见 0186）。

**边界**：`offset=0` 与 `offset=1` 等价（`:352-354`：先 `max(1, offset)`，随后 `if input_data.offset == 0: offset = 1`），所以越界分界线是 `offset > total_lines`。`validate_input` 只拦 `offset < 0`（`:305-310`，`errorCode 5`），**上界不拦**——故意留着让越界走上面这条信息路径。



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

### XEYO-QA-0168 `_persist` 两条路径的等价性维护

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Write/Edit 落盘分叉 | 直通 vs WriteStore | 中等 | 机制解释 | `python/tools/file_write_tool/file_write_tool.py:119-141,152-158,372` |

**面试官提问**
`Write._persist` 有两条落盘路径（无 `write_store` 直通 / 有 `write_store` 经单写者队列）。为什么要**手工**再写一遍换行还原逻辑，而不是直接调用 `write_text_file`？

**参考答案要点**
因为 `WriteStore` 的原子写按 `newline=''` 语义落盘、**不再做平台换行翻译**，所以两条路径都必须自己把「LF 归一化的内容」按目标 `line_endings` 还原成磁盘字节——不能让 store 层再猜一次。

`file_write_tool.py:152-158`（原文注释与实现）：

```python
		# 与直通路径 write_text_file 等价：按 line_endings 还原换行、保留
		# encoding。store 的原子写用 newline=''，不再做平台翻译。
		content_out = (
			content
			if line_endings != "CRLF"
			else "\r\n".join(content.replace("\r\n", "\n").split("\n"))
		)
```

对照直通路径最终调用的 `write_text_file`（`fileio/text.py:62-64`）：

```python
	to_write = normalize_newlines(content)
	if line_endings == "CRLF":
		to_write = "\r\n".join(to_write.split("\n"))
```

两者**计算结果相同**（都是「先归一到 LF 再按需还原 CRLF」），但表达不等价：`write_text_file` 用 `normalize_newlines`（`.replace("\r\n","\n").replace("\r","\n")`，两步），store 分支只做 `content.replace("\r\n", "\n")`——**不处理孤立 `\r`**。

这是一处**真实的细微不等价**。它是否显现取决于传入实参：`call` 在进 `_persist` 前已经算过 `normalized`（`:349`），但 `:372` 传的是**原始 `content`**：

```python
		journal_warning = self._persist(full, content, encoding=encoding, line_endings="LF")
```

所以直通路径会再归一化一次（幂等，无副作用），而 store 路径遇到孤立 `\r` 会把它**原样写进文件**。这是一条只有同时读两处才能发现的边界。

`Edit` 侧同理，且注释逐字重复了这段理由（`file_edit_tool.py:186-192`）——但它传的是 `endings`（探测到的原风格，`file_edit_tool.py:519-521`），所以 `Edit` 走 store 路径时**能保留 CRLF**。

**深化讲解**（面试官参考，不要求候选人全说）
这题的考点不是「哪条路径对」，而是**「同一语义有两份实现时，等价性靠什么维持」**：靠注释声明（「与直通路径 `write_text_file` 等价」）+ 靠人工自律。这里没有共享函数、没有断言两者等价的测试，所以微小漂移可以长期存在。

工程上的改进方向很轻：把还原逻辑抽成一个纯函数（如 `to_disk_text(content, line_endings)`），两条路径都调它——既消除漂移面，也不触碰任何架构分层。

**边界**：store 分支在 `result.ok` 为假时有两条升级路径（stale/`missing_read` → 组装 stale 消息；其余 → `write failed: <reason>`），并且**成功时**返回 `result.journal_warning`（`:190`），最终出现在工具结果末尾（`:439-441`）——「文件已落盘但证据链有缺口」这件事不静默。



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

### XEYO-QA-0169 `ReadFileState._key` 的归一化动机

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 读态账本 | 路径键归一化 | 中等 | 机制解释 | `python/tools/fileio/read_state.py:89-93,144-145` |

**面试官提问**
`ReadFileState` 内部字典的键不是原始路径，而是 `_key(path)` 的结果。这个函数做了哪两步归一化？**不这么做**会发生什么具体故障？

**参考答案要点**
两步：`os.path.normcase` 套 `os.path.normpath`，即 `normcase(normpath(path))`。

`fileio/read_state.py:89-93`（原文，注释里就写着故障）：

```python
	@staticmethod
	def _key(path: str) -> str:
		# Windows 大小写/分隔符不敏感：Read "D:\Foo.py" 与 Edit "d:/foo.py"
		# 必须命中同一条目，否则报 "has not been read yet" 误报。
		return os.path.normcase(os.path.normpath(path))
```

| 步骤 | Windows 行为 | 解决的故障 |
|---|---|---|
| `normpath` | `d:/foo.py` → `d:\foo.py`；折叠 `..`/`.`、去重复分隔符 | `Read` 用正斜杠、`Edit` 用反斜杠时键不同 |
| `normcase` | 转小写并统一分隔符（POSIX 上是 **no-op**） | `D:\Foo.py` 与 `D:\foo.py` 视为同一文件（NTFS 默认大小写不敏感） |

**不做归一化的具体后果**：`Read` 用 `D:\Foo.py` 登记，`Edit` 用 `d:/foo.py` 查表 → 查不到条目 → `validate_input` 返回 `errorCode 6`「File has not been read yet. Read it first before writing to it.」（`file_edit_tool.py:372-380`）。模型会陷入**重读也无用**的循环：两个路径形式都由模型自己生成，只要不一致就永远过不了门——用户视角完全无法理解。

同一键函数也用于 `__contains__`（`read_state.py:144-145`）：

```python
	def __contains__(self, path: object) -> bool:
		return isinstance(path, str) and self._key(path) in self._entries
```

**深化讲解**（面试官参考，不要求候选人全说）
一处**不对称**值得记：所有进 `_key` 的路径其实都已是 `expand_path` 的产物（`fileio/paths.py:17-23`：`expanduser` → 非绝对则 join cwd → `abspath`），所以 `normpath` 的主要价值落在「统一分隔符 + 作为 `normcase` 的前置」上（Windows 的 `normcase` 会把 `/` 换成 `\`），折叠 `..` 的边际收益有限。

另一处：`suggest_path_under_cwd` 用的是 `os.path.realpath`（`paths.py:37-41`）——**realpath 解析符号链接，`abspath` 不解析**。所以两个 symlink/junction 指向同一文件时，`_key` 会得到**两个不同的键**，「读写同一实体」的保证在 symlink 场景下不成立。是否需要引入 `realpath` 属设计取舍（realpath 有额外 syscall 且会改变路径文本），本批列为待确认项。



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

### XEYO-QA-0170 被阻断的设备文件清单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead 设备文件防护 | 阻断清单与 `/proc` 特例 | 中等 | 概念确认 | `python/tools/file_read_tool/file_read_tool.py:79-104,295-303` |

**面试官提问**
`Read` 会拒绝读取某些「设备文件」。关于这份清单与判定逻辑？请完整列举。

**参考答案要点**
**A、B、C**。

`file_read_tool.py:79-104`（原文）：

```python
BLOCKED_DEVICE_PATHS = frozenset(
	{
		"/dev/zero",
		"/dev/random",
		"/dev/urandom",
		"/dev/full",
		"/dev/stdin",
		"/dev/tty",
		"/dev/console",
		"/dev/stdout",
		"/dev/stderr",
		"/dev/fd/0",
		"/dev/fd/1",
		"/dev/fd/2",
	}
)


def _is_blocked_device(path: str) -> bool:
	if path in BLOCKED_DEVICE_PATHS:
		return True
	if path.startswith("/proc/") and (
		path.endswith("/fd/0") or path.endswith("/fd/1") or path.endswith("/fd/2")
	):
		return True
	return False
```

调用点（`:295`）是 `_is_blocked_device(full.replace("\\", "/"))`——**C 正确**：先做斜杠归一化，`\dev\zero` 这类 Windows 形式也能落进精确匹配。

**D 不正确**：清单里**没有** `NUL`/`CON`/`PRN`/`AUX`。Windows 上 `Read` 一个 `NUL` 路径会走到 `os.path.exists` 分支并抛 `FileNotFoundError`（构造不出「无限读」风险），所以这是**不需要拦**而非漏拦。

**A 里这 12 个为什么是它们**：按 `validate_input` 的错误文案「this device file would block or produce infinite output」（`:298-301`）分两类：

| 类别 | 成员 | 危险机制 |
|---|---|---|
| 无限/阻塞输出 | `zero`、`random`、`urandom`、`full` | 读不完 / 永不 EOF，撑爆内存与上下文 |
| 进程标准流 | `stdin`、`stdout`、`stderr`、`fd/0-2`、`tty`、`console` | 会让工具阻塞等输入，或在 Read 里「偷」走终端输入 |

`/proc/<pid>/fd/{0,1,2}` 用后缀匹配是必要的：进程号动态，无法枚举。

**深化讲解**（面试官参考，不要求候选人全说）
这道防护与「二进制扩展名黑名单」性质不同：后者防的是**读进来是乱码**（信息无价值），前者防的是**读操作本身不会结束**（可用性事故）。所以它是硬拦截，并且在 `validate_input` 阶段（`:295`）就拦住——连 `os.path.exists` 都还没查。

**边界**：设备判定在 `file_path` 非空检查与 UNC 短路**之后**（`:251-260` 先做前两项），所以 `\\?\GLOBALROOT\Device\...` 这类设备命名空间路径会在 UNC 短路处**直接放行**（`return {"result": True}`），不走这份清单。



**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出上面的主体结论与关键常量/枚举，不得编造行号。
- **良好**：能说出每个字段/每道闸的**作用对象**（它管什么、不管什么），而不只是背清单。
- **优秀**：能把本题结论与同类机制对比（指出它们各自管什么），并在追问下拿出 `文件:行号` 作证。

**典型弱答**（听到这些就得分不高）
- 答成「Windows 的 `NUL`、`CON` 也在这份清单里」——说明没抓住本题的分界（D）。
- 只报清单/只报数字，说不出“它为什么存在”；
- 把本题的机制当成全局机制（跨模块张冠李戴）；
- 编造行号或「大概就是某某函数里」而拿不出证据（本题可追问到具体 `文件:行号`）。

**追问**
把机制换个场景：如果把它挪到另一条链路，哪一条假设会先失效？

---

### XEYO-QA-0171 弯引号归一化与实际串的取回

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 智能引号 | 匹配与样式保持 | 中等 | 机制解释 | `python/tools/fileio/text.py:94-111,154-170` |

**面试官提问**
模型给的 `old_string` 里用直引号 `"`，而文件里实际是弯引号 `“”`（U+201C/U+201D）。`find_actual_string` 怎么处理？匹配成功后，又如何保证替换文本沿用文件原有的弯引号风格？

**参考答案要点**
**先用原串直查；失败则把两侧弯引号都归一化成直引号再查；命中后从「文件原文」按原串长度切回实际串。**

`fileio/text.py:94-111`（原文）：

```python
def normalize_quotes(s: str) -> str:
	return (
		s.replace(LEFT_SINGLE_CURLY, "'")
		.replace(RIGHT_SINGLE_CURLY, "'")
		.replace(LEFT_DOUBLE_CURLY, '"')
		.replace(RIGHT_DOUBLE_CURLY, '"')
	)


def find_actual_string(file_content: str, search_string: str) -> str | None:
	if search_string in file_content:
		return search_string
	normalized_search = normalize_quotes(search_string)
	normalized_file = normalize_quotes(file_content)
	idx = normalized_file.find(normalized_search)
	if idx != -1:
		return file_content[idx : idx + len(search_string)]
	return None
```

四类映射（`text.py:11-14`）：`‘`/`’` → `'`；`“`/`”` → `"`。

三步：

1. **快路径**：原串命中直接返回（常见情形零开销、零风险）；
2. **归一化路径**：两侧同时归一化后 `find` 得 `idx`；
3. **回切**：`file_content[idx : idx + len(search_string)]`——长度用**原串**长度，从**未归一化**的原文里切。

第 3 步最容易被忽略：归一化是**一对一映射**（`“` 与 `"` 都是 1 个字符），所以 `idx` 与长度在两侧通用。这也划出了能力边界——形如 `ﬁ` → `fi` 的一对多替换**不可能**用这套机制处理，代码只处理一对一映射的引号。

匹配成功后风格对齐在 `preserve_quote_style`（`text.py:154-170`）：

```python
def preserve_quote_style(
	old_string: str, actual_old_string: str, new_string: str
) -> str:
	if old_string == actual_old_string:
		return new_string
	has_double = (
		LEFT_DOUBLE_CURLY in actual_old_string or RIGHT_DOUBLE_CURLY in actual_old_string
	)
	has_single = (
		LEFT_SINGLE_CURLY in actual_old_string or RIGHT_SINGLE_CURLY in actual_old_string
	)
	result = new_string
	if has_double:
		result = _apply_curly_double(result)
	if has_single:
		result = _apply_curly_single(result)
	return result
```

即**只有风格确有差异时才改写 `new_string`**。改写用两个方向感知辅助函数：

- `_apply_curly_double`（`:121-131`）：按 `_is_opening_context`（`:114-118`，前一字符是空格/Tab/换行/`(`/`[`/`{`/`—`/`–` 或行首 → 开引号）决定成 `“` 还是 `”`；
- `_apply_curly_single`（`:134-151`）：单引号多一个分支——`prev.isalpha() and nxt.isalpha()` 时判为撇号 `’`（如 `it's`），否则按开/闭上下文决定。

**深化讲解**（面试官参考，不要求候选人全说）
这是「**宽容匹配 + 保守替换**」的组合：匹配端允许模型写直引号（模型很难稳定输出弯引号），替换端坚持文件风格不被拉平。没有 `preserve_quote_style`，一次编辑就会把文件里的 `“` 全换成 `"`——diff 里塞满与意图无关的改动。

**边界（重要）**：归一化路径返回的是**原文切片**，所以 `call` 里 `occurrences = file_content.count(actual_old)`（`file_edit_tool.py:511`）统计的是**弯引号版本**的出现次数。若同一句话在文件里既有直引号版又有弯引号版，唯一性判定是**按实际风格分别计数**，而不是把两者合并。



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

### XEYO-QA-0172 `old_string=""` 的两个分支

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Edit 创建语义 | 空 old_string 分支 | 中等 | 机制解释 | `python/tools/file_edit_tool/file_edit_tool.py:347-370,444-468,500-517` |

**面试官提问**
`Edit` 允许 `old_string=""` 表示「写入内容」。这条路在**文件不存在**与**文件存在**两种情况下分别怎么走？两阶段的判据是同一个吗？

**参考答案要点**
**文件不存在 → 走「新建文件」分支直接落盘 `new_string`；文件存在 → 只有内容是空白时才放行，否则报 `Cannot create new file - file already exists.`（`errorCode 3`）。两阶段判据不同。**

**校验期**（`file_edit_tool.py:347-370`）：

```python
		# 文件不存在
		if file_content is None:
			if input_data.old_string == "":
				return {"result": True}
			suggestion = suggest_path_under_cwd(full, cwd=self._cwd)
			similar = find_similar_file(full)
			message = (
				f"File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {self._cwd}."
			)
			if suggestion:
				message += f" Did you mean {suggestion}?"
			elif similar:
				message += f" Did you mean {similar}?"
			return {"result": False, "message": message, "errorCode": 4}

		# 空 old_string：仅空文件允许（创建内容）
		if input_data.old_string == "":
			if file_content.strip() != "":
				return {
					"result": False,
					"message": "Cannot create new file - file already exists.",
					"errorCode": 3,
				}
			return {"result": True}
```

「文件不存在」的判定**不是**靠 `os.path.exists`，而是靠 `read_text_file` 抛 `FileNotFoundError` 后把 `file_content` 置 `None`（`:338-345`）。那里还处理了 `OSError` 的两种走向：`getattr(e, "errno", None) == 2 or not os.path.exists(full)` → 视为不存在；否则返回 `errorCode 11`（真错误，如权限）。

**执行期**（`:444-448`）：

```python
		# 新文件创建：old_string == ""
		if not os.path.exists(full) and input_data.old_string == "":
			journal_warning = self._persist(
				full, input_data.new_string, encoding="utf-8", line_endings="LF"
			)
```

**判据不同**：校验期看 `file_content is None`（读失败），执行期看 `not os.path.exists(full)`（存在性）。正常情况二者一致；但在「校验与执行之间文件被创建」的窗口里会产生一条**隐蔽的等价路径**：`old_string=""` 而文件已存在 → 不走新建分支 → 落到通用编辑路径 → 读文件、找 `actual_old`，因 `old_string == ""` 使 `actual_old` 为 `""`（`:500-501`）→ 命中 `actual_old == ""` 分支 `updated = actual_new`（`:507-509`）→ **整文件被替换成 `new_string`**。最终效果与新建相同，但**没有** `_persist(..., encoding="utf-8", line_endings="LF")` 的硬编码参数，而是用**该文件探测到的** `encoding`/`endings`。

**「空文件」判定用 `file_content.strip() != ""`**：只含空白/换行的文件也算空，允许灌入内容。

**执行期新建分支的三个细节**：`encoding="utf-8"`、`line_endings="LF"` 硬编码（`:447`，新文件无原编码可继承）；`set_written` 登记的是 `input_data.new_string.replace("\r\n", "\n")`（`:451`，只归一化 `\r\n`，与 0168 的等价性问题同源）；`occurrences=1` 固定（`:462`）。

**深化讲解**（面试官参考，不要求候选人全说）
`old_string=""` 承担「创建文件」语义，但它被塞在 `Edit` 里而不是让模型用 `Write`——这解释了描述里的 `Prefer Edit over creating new files`（`file_edit_tool/prompt.py:7`）：工具面允许，提示词引导优先。



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

### XEYO-QA-0173 触碰即刷新的 LRU

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 读态账本 | get/set 的序维护 | 中等 | 机制解释 | `python/tools/fileio/read_state.py:95-108,113-142` |

**面试官提问**
`ReadFileState.get` 除了返回值还做了什么？为什么这个副作用必须记住？`snapshot_meta` 与 `load_meta` 分别怎么处理这个副作用？

**参考答案要点**
`get` 做了三件事：查表、**把命中项移到字典末尾**（触碰即刷新新鲜度）、返回。`set` 是「先删后插再淘汰」，所以新写的条目**一定在末尾**，而淘汰永远从**头部**取。

`fileio/read_state.py:95-108`（原文）：

```python
	def get(self, path: str) -> FileStateEntry | None:
		key = self._key(path)
		entry = self._entries.get(key)
		if entry is not None:
			self._entries.pop(key, None)
			self._entries[key] = entry  # 触碰即刷新新鲜度
		return entry

	def set(self, path: str, entry: FileStateEntry) -> None:
		key = self._key(path)
		self._entries.pop(key, None)
		self._entries[key] = entry
		while len(self._entries) > self._max_entries:
			self._entries.pop(next(iter(self._entries)))
```

这是一个用普通 `dict` 手写的 LRU，依赖 Python 3.7+ 的插入序保证：移末尾 = `pop` 后重插；淘汰最旧 = `pop(next(iter(...)))`（迭代器首个即最旧）。

**为什么必须记住 `get` 有副作用**——它被当作「纯查询」用的地方很多：

| 调用点 | 语义 | 是否利用刷新 |
|---|---|---|
| `file_read_tool.py:361`（去重判定） | 查询是否读过 | 是 |
| `file_write_tool.py:264`（先读门禁） | 查询先读事实 | 是 |
| `file_edit_tool.py:372,477,479` | 校验 + 执行两次查询 | 是 |
| `read_state.py:131`（`load_meta` 内） | 取回现有正文 | 无害（随即被 `set` 重排） |

`snapshot_meta`（`:113-123`）**直接遍历 `self._entries`**、不刷新——这是对的（序列化不该改变访问序）：

```python
	def snapshot_meta(self) -> dict[str, dict]:
		"""序列化 mtime/offset，不含文件正文（给 WorkingSnapshot sidecar）。"""
		out: dict[str, dict] = {}
		for path, entry in self._entries.items():
			out[path] = {
				"timestamp": entry.timestamp,
				"offset": entry.offset,
				"limit": entry.limit,
				"is_partial_view": entry.is_partial_view,
			}
		return out
```

注意它序列化的键用的是**归一化后的键**（`self._entries` 的键），而**不含** `content` / `content_known` / `writer_session_id` / `writer_ts`——所以 sidecar 恢复后正文必然未知，这正是 `content_known=False` 的来源。

`load_meta`（`:125-142`）用 `get` 取回可能已存在的正文再 `set` 回同键，并用一个复合表达式同时处理两种「正文未知」：

```python
					content_known=bool(existing and existing.content),
```

即：条目不存在、或正文为空串，都判为 `content_known=False`。

**深化讲解**（面试官参考，不要求候选人全说）
手写 LRU 的正确性依赖三条不变式：①字典插入序 = 新鲜度序；②只有 `get`（命中时）与 `set` 改变顺序；③淘汰只从头部取。任一条被破坏就会出现「刚写的条目被踢掉」这类诡异行为。

**提醒**：若将来有人在 `snapshot_meta` 里改用 `get` 取值，就会把「序列化」变成一次**全量触碰**，淘汰顺序被彻底打乱——这是这个设计里最容易被无意踩坏的一点。



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

### XEYO-QA-0174 `.agentignore` 为什么还要追加后置 `--glob !rule`

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 搜索排除 | agentignore 双重挂载 | 中等 | 机制解释 | `python/tools/fileio/excludes.py:64-105` |

**面试官提问**
挂载 `.agentignore` 时，代码既传 `--ignore-file`，又把每条非否定规则追加成 `--glob !rule`。既然 `--ignore-file` 已实现完整 gitignore 语义，为什么还要多此一举？

**参考答案要点**
因为 **rg 的命令行 `--glob` 白名单会覆盖 ignore 文件规则，且「后面的 glob 优先」**——只有把规则也作为**后置** `--glob !rule` 追加，才能压住用户自己传的 glob（如 `*.log`）。

`fileio/excludes.py:83-105`（原文，注释即答案）：

```python
def agentignore_args(*roots: str) -> list[str]:
	"""存在 ``.agentignore`` 时返回 ripgrep 的过滤参数（Glob/Grep 共用）。

	对传入的候选根目录（搜索根、工作区 cwd 等）逐个探测：
	- ``--ignore-file``：完整 gitignore 语义，不依赖 git 仓库；
	- 另把非否定行追加为**后置** ``--glob !rule``——rg 中命令行 --glob
	  白名单会覆盖 ignore 文件，且"后面的 glob 优先"，这样用户 glob
	  （如 ``*.log``）也无法穿透 .agentignore。
	"""
	args: list[str] = []
	seen: set[str] = set()
	for root in roots:
		if not root:
			continue
		path = os.path.abspath(os.path.join(root, AGENTIGNORE_FILENAME))
		if path in seen:
			continue
		seen.add(path)
		if os.path.isfile(path):
			args += ["--ignore-file", path]
			for rule in _read_agentignore_rules(path):
				args += ["--glob", f"!{rule}"]
	return args
```

实现要点：

| 要点 | 实现 | 理由 |
|---|---|---|
| 只取非否定行做 `--glob` | `_read_agentignore_rules`（`:67-80`）跳过空行、`#` 注释、`!` 开头的行 | 否定行语义交给 `--ignore-file`；把 `!keep` 变成 `--glob !keep` 会把「保留」反转成「排除」 |
| 多 root 去重 | `seen` 按**绝对路径**判重（`:97-100`） | Glob/Grep 都传 `(root, cwd)`，同一文件可能被探测两次 |
| 只认存在的文件 | `os.path.isfile(path)` | 不存在就一条参数都不加（零开销） |
| 参数顺序 | `--ignore-file` 先、`--glob !rule` 后 | 后者才能压住前者与用户 glob |

**参数顺序为什么关键**——对照 Glob 侧的另一处注释（`glob_tool.py:244-249`）：

```
	rg 中 ``--iglob`` 白名单与 ``--glob`` 排除属不同集合、互不按"后者优先"
	覆盖（大小写重试趟的 iglob 白名单会穿透前置排除项），因此 case-insensitive
	时把全部排除项再以 ``--iglob !rule`` 形式后置补一遍，保证压住白名单。
```

这是**同一问题的两个变体**：正常趟用 `--glob`（同类可被后者覆盖），大小写重试趟用 `--iglob`（跨类不可覆盖，只能再补一遍 `--iglob`）。

**深化讲解**（面试官参考，不要求候选人全说）
本题的价值是揭示 `rg` 的一个非直觉行为：**ignore 文件与命令行 glob 处在不同优先级层，命令行赢**。所以在「用 ignore 文件表达兜底约束」的场景里，必须把兜底规则**升格成命令行参数**才能获得硬约束地位。

方向性观察：`.agentignore` 由用户/团队维护，而 `excluded_secret_globs()`（`excludes.py:108-119`）是从 `permissions.filesystem.DANGEROUS_FILES / DANGEROUS_SUFFIXES` **代码生成**的密钥排除，参数形态一致但来源不同——这意味着改权限层常量会同时改变搜索排除面（跨层耦合）。



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

### XEYO-QA-0175 外部归因的会话树排除

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 冲突归因 | 同会话树豁免 | 中等 | 机制解释 | `python/tools/fileio/conflict.py:55-89` |

**面试官提问**
`external_attribution` 在哪些情况下会**主动返回空串**（放弃归因）？为什么要专门排除「同一会话树」？

**参考答案要点**
四条空返回路径：①`cwd`/`abs_path`/`self_session_id` 任一为空；②`session_presence` 查询抛异常（静默）；③注册表查不到写入者（`owner is None`）；④**写入者与本会话属同一会话树**（且 `exclude_tree_roots=True`，默认值）。

`fileio/conflict.py:62-89`（原文）：

```python
def external_attribution(
	cwd: str,
	abs_path: str,
	self_session_id: str,
	*,
	exclude_tree_roots: bool = True,
) -> str:
	"""若文件被**另一个会话树**最近写入，返回归因短语；否则 ""。"""
	sid = (self_session_id or "").strip()
	if not cwd or not abs_path or not sid:
		return ""
	try:
		reg = default_session_presence()
		owner = reg.owner_of(cwd, abs_path, exclude_session=sid)
	except Exception:  # noqa: BLE001
		return ""
	if owner is None:
		return ""
	if exclude_tree_roots and session_tree_root(owner.session_id) == session_tree_root(
		sid
	):
		# 同一会话树（含本会话子 agent）写入：不算外部，交旧提示兜底。
		return ""
	label = owner.title or owner.session_id[-8:]
	return (
		f" Suspicious: another session「{label}」wrote this file recently"
		f" ({_time_hhmm(next(iter(owner.owned_files.values()), 0))})."
	)
```

**为什么要排除同一会话树**：本会话的**子 agent** 是独立会话 id（形如 `<主会话>__agent__<...>`），它们写文件是这条主会话的**正常工作流的一部分**。若不排除，主 agent 在子 agent 刚写完一个文件后去 `Edit` 它，就会收到 `Suspicious: another session「…」wrote this file recently`——把「自己下属干的活」报成「有外人在改我的文件」。这既误导模型（它会去排查一个不存在的冲突），也稀释了 `Suspicious` 一词的可信度。

树根归约由 `engine/session_presence.session_tree_root` 完成（子 agent 会话归约到主会话 id）；`read_state.py:51-53` 的注释印证同一约定：「本册所属会话树根（主会话 id，或子 agent 会话去掉 `__agent__` 后缀）」。

另外两处取值细节：

1. **`owner_of(..., exclude_session=sid)`**：查询时就排除自己，所以「本会话自己写的」在更早一层不会成为 `owner`——树根比较是**第二道网**，专收「同树不同会话」的子 agent 情形；
2. **`label = owner.title or owner.session_id[-8:]`**：有标题用标题，否则取会话 id **末 8 位**（不把完整 id 塞进模型上下文）；
3. **时间戳取 `next(iter(owner.owned_files.values()), 0)`**：只取该 owner 名下的**第一个**文件时间，**不是** `abs_path` 自己的时间——这是一处近似，owner 拥有多文件时显示的时间可能不属于本次目标文件。

**深化讲解**（面试官参考，不要求候选人全说）
归因的失败方向被设计成**安全侧**：查不到、异常、同树 → 一律沉默。理由直接：错误的外部归因会让模型做出错误决策（重读、放弃、甚至去动另一个会话的文件），而漏报只退化成原有通用提示，代价小得多。这是「不确定就不说」在工具文案层的落地。



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

### XEYO-QA-0176 relaxed glob 的放宽规则

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Glob 空结果引导 | 放松匹配反推 | 中等 | 机制解释 | `python/tools/glob_tool/glob_tool.py:523-573` |

**面试官提问**
`Glob` 零命中时会尝试给出 `Did you mean:` 建议。它把原 pattern **怎么改**成放宽模式？哪些情况下**不给**建议？

**参考答案要点**
**把文件名段里的 `_` 与 `-` 全部换成 `*`，并把名字锚到任意深度**（有字面目录前缀且该目录存在时保留前缀）；过宽、放宽后仍无命中、rg 出错时都不给。

`glob_tool.py:523-573`（原文关键段）：

```python
	norm = (pattern or "").strip().replace("\\", "/")
	while norm.startswith("./"):
		norm = norm[2:]
	if not norm or is_broad_pattern(norm):
		return None
	last = norm.rsplit("/", 1)[-1]
	if is_broad_pattern(last):
		return None
	fuzzy_last = last.replace("_", "*").replace("-", "*")
	prefix, _rest = split_pattern_prefix(norm)
	if prefix and os.path.isdir(os.path.join(root, prefix)):
		relaxed = f"{prefix}/**/{fuzzy_last}"
	else:
		relaxed = f"**/{fuzzy_last}"
	try:
		hits, _truncated, _total, _spill = perform_glob(
			pattern=relaxed,
			root_dir=root,
			limit=limit,
			offset=0,
			abort=None,
			case_insensitive=True,
			ignore_roots=(cwd,),
		)
	except RipgrepRunnerError:
		return None
	if not hits:
		return None
	rel_hits = [to_relative_path(os.path.join(root, h), root) for h in hits][:limit]
	dirs = sorted({os.path.dirname(h).replace("\\", "/") or "." for h in rel_hits})
	lines = ["Did you mean:"]
	lines.extend(f"  {h}" for h in rel_hits)
	if prefix and dirs and not any(
		(d == prefix) or d.endswith("/" + prefix) for d in dirs
	):
		lines.append(f"  (searched `{prefix}/`; closest match is under `{dirs[0]}/`)")
	_bump_stat("miss_suggestions")
	return "\n".join(lines)
```

**五条前置**（任一不满足即 `None`）：归一化后非空；整个 pattern 不过宽；**末段也不过宽**；放宽后有命中；`RipgrepRunnerError` 时静默。

**放宽规则的作用范围**：只换 `_`/`-`，**不换数字、不换点**。设计意图在 docstring（`:530-534`）：`doc/agent_b.md` → `**/agent*b.md`——**一次命中同时纠正目录与文件名两处错位**。保留前缀那一路只在 `prefix` 非空**且该目录真实存在**（`os.path.isdir`）时启用；目录不存在就退回 `**/fuzzy_last` 全树放松。

**额外的一句提示**：用了前缀但命中文件**都不在前缀目录下**时，追加 `(searched `<prefix>/`; closest match is under `<dirs[0]>/`)`——明确告诉模型「我按你给的前缀找过，最近的在别处」。

**深化讲解**（面试官参考，不要求候选人全说）
这个机制的取向是「**用一次额外的、成本可控的全局放松扫描，换掉一次完全无用的空结果**」。注释（`:534`）明确它只发生在无匹配分支，过吵则静默返回 `None`；其结果**会被缓存**（`glob_tool.py:937-947`，键 `("suggestion", pattern, root, self._cwd)`，**连 `None` 也缓存**）——避免同一无匹配查询在 60s 内反复触发全量扫描。

**代价**：这条路径会**额外跑一次 rg**，且是 `**/` 全树范围（前缀不可用时）。对超大工作区，一次空查询的成本接近一次全库 glob；缓存是主要缓解，`_bump_stat("miss_suggestions")` 是留给遥测的计数器。



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
### XEYO-QA-0177 `lookup` 返回空列表说明了什么

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 内容索引 | 空候选的确定性 | 中等 | 机制解释 | `python/tools/fileio/content_index.py:86-115,144-170` |

**面试官提问**
`content_index.lookup` 可能返回三种值：`None`、`[]`、非空列表。它们分别意味着什么？为什么返回 `[]` 时 `Grep` 可以**直接**给出零命中，而返回 `None` 必须回退全量 rg？

**参考答案要点**
三元语义：

| 返回值 | 含义 | 调用方动作 |
|---|---|---|
| `None` | **索引不可用**（不可建 / 超限 / 异常） | 回退全量 `rg`（fail-open，只失去加速） |
| `[]` | 索引可用，且**确定性证明没有文件能含该字面量** | 直接返回零命中（索引唯一的短路点） |
| 非空列表 | 候选**超集**（可含假阳性） | 交给 `rg` **精确验证** |

`fileio/content_index.py:144-170`（原文核心）：

```python
	for tg in tgs:
		s = idx.trigrams.get(tg)
		if s is None:
			return []  # 某 trigram 全库不存在 → 无任何文件可含该字面量 → 零候选
		if common is None:
			common = set(s)
		else:
			common &= s
		if not common:
			return []
	return sorted(common)
```

以及 `_build_index` 的「全或无」保证（`:86-115`）：遍历 `rg --files --hidden`（同一套排除清单）列出的**全部**文件，只要有任一个文件 `getsize` 失败、或单文件超 `_SKIP_FILE_BYTES = 2 MiB`、或累计超 `_MAX_INDEXED_BYTES = 64 MiB`、或读失败、或文件数超 `_MAX_INDEXED_FILES = 20_000` → **直接 `return None`**（放弃整个索引）。

**为什么 `[]` 是确定性的**：trigram 倒排的性质是——若字面量 `L` 出现在文件 `f` 中，则 `L` 的**每个** trigram 都出现在 `f` 中，因此 `f` 必然属于每个 trigram 的倒排集合，故必属于它们的**交集**。反之，若某个 trigram `t` 的倒排集合**不存在**（`idx.trigrams.get(tg) is None`），说明**全库没有任何文件含 `t``——那么任何含 `L` 的文件都不存在，交集必空。同理，交集在某步变空也是确定性结论。

这两个 `return []` 都是**推理结论**而非猜测，其唯一前提正是「全或无」：若索引覆盖不全（漏了文件），空交集就可能是假阴性。所以「要么索引覆盖全部（非排除）文件，要么完全不加速」（`:11-13`）是 `[]` 语义成立的**唯一支柱**。

**深化讲解**（面试官参考，不要求候选人全说）
三种返回值的分层体现了 fail-open 的正确形态：**加速路径的失败绝不改变正确性**。注意 `None` 的来源之一是「读到不可读文件」（`OSError` → `return None`）——看似过于保守（一个坏文件让整个索引失效），但正是它保证了「不漏」，注释亦自陈「任一上限触发即放弃（回退全量 rg）」（`:29`）。

`Grep` 侧的短路点在 `grep_tool.py:585-595`：候选为空时直接构造零命中 `GrepOutput` 并跳过 `rg`。

**代价与新鲜度**：`_TTL_S = 30.0`（`:28`），写后由 `clear_content_index()` 显式清空（`:134-141`，注释：「清错只损失一次加速……不清才是正确性事故（30s TTL 内新写文件进不了候选集 → `files_with_matches` 漏）」）。这与 `:14-15` 的「窗口内新建的文件可能未被收录，属已知权衡（候选为超集，rg 仍精确验证）」**存在张力**：候选漏了文件就不再是超集，`rg` 也无法把它验证回来。正确的理解是两条注释针对不同威胁模型——前者描述「无写后失效时的理论窗口」，后者描述「候选为超集」这一常态假设；写后清缓存（含 Bash 写命令触发，见 `tests/test_glob_optimize.py:495-517` 的分类器）才是常态保证。



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

### XEYO-QA-0178 输出预算函数的两处早退

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | registry 输出预算 | 早退与预算优先级 | 中等 | 机制解释 | `python/tools/tool_registry.py:179-203` + `python/tools/meta.py:103-155` |

**面试官提问**
`ToolRegistry._apply_output_budget` 在什么情况下**直接原样返回**（不落盘、不换预览）？预算数值按什么优先级确定？本批五个文件工具里哪些**豁免**了这个机制？

**参考答案要点**
**早退四处**：`result.is_error` 为真；`content` 不是 `str`；`content` 为空串；`budget <= 0` 或 `len(content) <= budget`。

`tool_registry.py:179-203`（原文）：

```python
	def _apply_output_budget(
		self, tool: Tool, result: ToolResult, *, session_id: str = ""
	) -> ToolResult:
		"""超预算输出 → spill 原文 + 预览替换（T1/T27 顺序：raw 先落盘）。

		- is_error 结果不 spill（错误本就应完整可见且通常很短）；
		- spill 失败原样返回（不 isError、不丢内容）；
		- 截断元数据标注「预算截断」，与工具失败区分。
		"""
		if result.is_error or not isinstance(result.content, str) or not result.content:
			return result
		from tools.meta import meta_for

		meta = meta_for(tool.name)
		# 实例级覆盖优先（F6a per-tool output_token_limits → McpTool.output_budget）；
		# 静态 ToolMeta 次之；最后默认预算。
		budget = getattr(tool, "output_budget", None)
		if budget is None:
			budget = (
				meta.output_budget
				if meta is not None and meta.output_budget is not None
				else self.DEFAULT_OUTPUT_BUDGET
			)
		if budget <= 0 or len(result.content) <= budget:
			return result
```

**三级优先级**：实例属性 `tool.output_budget`（动态工具注入，如 MCP per-tool 配置）→ 静态 `ToolMeta.output_budget` → `ToolRegistry.DEFAULT_OUTPUT_BUDGET = 16_000`（`tool_registry.py:84`）。

**`budget <= 0` 的语义是「关闭预算」，不是「零预算」**。本批相关工具的实际配置（`meta.py:103-155`）：

| 工具 | `output_budget` | 理由（源码注释） |
|---|---|---|
| `Read` | **0** | 「T1：Read 豁免 spill——防 read→spill→read 循环。」 |
| `Bash` | **0** | 「Bash 自带 raw→落盘→截断 seam（truncate_for_model），豁免 registry 级预算，避免双重截断/双重落盘。」 |
| `Glob`/`Grep`/`Write`/`Edit` | 未设 | 走默认 `16_000` |

`Read` 豁免的理由值得单独记：若 `Read` 的超预算结果也落盘 + 换预览，那么「读那个 spill 文件」这个动作本身又会产出超预算结果……形成 `read → spill → read → spill` 的循环。正确解不是「减小预览」，而是**从根上关闭该工具的预算机制**。

**`is_error` 不 spill**：错误通常短且必须完整可见（模型要靠它定位问题）。注意它也**不**被换成预览——即使错误内容很大（如整页 rg 错误输出）也原样返回。

**深化讲解**（面试官参考，不要求候选人全说）
四处早退的共同点是「**条件不满足就不要碰内容**」，加上 spill 失败也原样返回（`:208-209`），`_apply_output_budget` 成为一个**纯附加**机制：它的任何路径都不会让工具结果变得更差。



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

### XEYO-QA-0179 陈旧分支的触发条件

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Write 写入失败归因 | stale/missing_read 分支 | 中等 | 代码阅读 | `python/tools/file_write_tool/file_write_tool.py:136-190` |

**面试官提问**
读下面的代码，回答：哪些情况会走进「组装 stale 消息」这一支？进去时传给 `build_stale_message` 的 `snapshot` 与 `disk_content` 分别是什么？

```python
		entry = self._read_state.get(full)
		base_hash = ""
		if entry is not None and entry.content:
			base_hash = _content_hash_text(entry.content)
		elif entry is not None:
			from tools.fileio.text import read_text_file as _rtf

			try:
				base_hash = _content_hash_text(_rtf(full)[0])
			except OSError:
				base_hash = ""
		content_out = (
			content
			if line_endings != "CRLF"
			else "\r\n".join(content.replace("\r\n", "\n").split("\n"))
		)
		result = self._write_store.submit_sync(
			ChangeIntent(
				agent_id=self._agent_id,
				base_hashes={full: base_hash},
				ops=[EditOp(path=full, new_content=content_out)],
				encoding=encoding,
			)
		)
		if not result.ok:
			reason = str(result.reason or "")
			if result.base_stale or reason in ("stale", "missing_read"):
				snapshot = entry.content if entry is not None else ""
				try:
					disk_content, _, _ = read_text_file(full)
				except OSError:
					disk_content = ""
				extra = str(getattr(result, "detail", "") or "").strip()
				detail = build_stale_message(
					f"write conflict ({reason or 'stale'}): "
					f"{FILE_UNEXPECTEDLY_MODIFIED_ERROR}",
					self._cwd,
					full,
					self._session_id,
					snapshot,
					disk_content,
				)
				if extra and "session" not in detail:
					detail += "\n" + extra
				raise RuntimeError(detail + " Re-Read then retry.")
			raise RuntimeError(f"write failed: {reason}")
```

**参考答案要点**
触发条件是**或**关系：`result.base_stale` 为真，**或** `reason ∈ {"stale", "missing_read"}`。

| 参数 | 取值 | 语义 |
|---|---|---|
| `base`（消息首行） | `f"write conflict ({reason or 'stale'}): {FILE_UNEXPECTEDLY_MODIFIED_ERROR}"` | `reason` 为空时占位 `stale` |
| `snapshot` | `entry.content if entry is not None else ""` | **会话读态**（模型上次看到的版本） |
| `disk_content` | `read_text_file(full)[0]`，`OSError` 时 `""` | **现读磁盘**（模型即将读到的版本） |

即 `snapshot` = 「你以为的样子」，`disk_content` = 「现在的样子」，两者交给 `line_range_summary` 做差异定位（见 0159）。

**三个细节**：

1. **`snapshot` 可能是空串**：`entry is None` 时（文件从未 Read、或走了现读现算 base 的路径）——此时 `line_range_summary("", disk)` 会输出「磁盘全文都是新增」，行号从 1 起，退化成「整份文件都变过」的提示。可接受的降级。
2. **`extra` 的拼接条件是 `if extra and "session" not in detail`**：`result.detail` 只在当前消息**还没提到 session** 时追加，避免与 `external_attribution` 的「another session…」重复表达同一件事。
3. **非 stale 失败**走最后一行 `raise RuntimeError(f"write failed: {reason}")`——不带归因，因为这不是「文件被改过」类问题。

**`base_hash` 三来源**（与 B03 的 WriteStore 契约衔接）：①`entry.content` 非空 → 用它的哈希；②`entry` 存在但正文为空（sidecar 恢复的 `content_known=False` 条目）→ **现读现算**；③都没有 → 交空串，会被 store 以 `missing_read` 拒绝。第 ② 条的注释解释了理由：「交空 base 会被 store 以 missing_read 拒绝（恢复后首写必败）；现读现比对：本调用已在 `to_thread` 中，store 锁仍串行写者。」

**深化讲解**（面试官参考，不要求候选人全说）
这条分支的意义是：`WriteStore.submit_sync` 的失败原因是**结构化**的（`ok` / `reason` / `base_stale` / `detail`），工具层负责把它翻译成**模型可行动的消息**。翻译的关键动作是**现读磁盘**而非复用 `read_state`——要比较的正是「快照 vs 磁盘」，两者必须都拿到手里。



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

### XEYO-QA-0180 贪婪 pattern 的判定规则

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Glob 过宽判定 | 名字线索规则 | 中等 | 机制解释 | `python/tools/glob_tool/glob_tool.py:137-146,195-212` |

**面试官提问**
`is_broad_pattern` 怎么判断一个 glob 是否「过宽」？为什么 `gui/**/*` 算过宽而 `**/*.tsx` 不算？`*.*` 与 `?` 呢？

**参考答案要点**
**只看 pattern 的「最后一段」（文件名部分）去掉 `*` 后是否还剩字母数字**——不剩就是过宽。

`glob_tool.py:195-212`（原文）：

```python
def is_broad_pattern(pattern: str) -> bool:
	"""过宽/贪婪：文件名部分没有固定名字线索（去掉 * 后不含任何字母数字）。

	目录前缀不豁免——`gui/**/*` 和 `**/*` 一样是全子树泄洪，判断落在
	最后一段（文件名部分）上：`**/*.tsx`、`*Map*` 有名字线索 → 放行；
	`gui/**/*`、`src/**`、`*.*`、`?` 无名字线索 → 贪婪，返回目录摘要。
	"""
	p = (pattern or "").strip().replace("\\", "/")
	if not p:
		return True
	while p.startswith("./"):
		p = p[2:]
	if p in _BROAD_EXACT:
		return True
	base = p.rsplit("/", 1)[-1]
	if not any(ch.isalnum() for ch in base.replace("*", "")):
		return True
	return False
```

逐例：

| pattern | 末段 | 去掉 `*` 后 | 结果 |
|---|---|---|---|
| `**/*` | `*` | `""` | 过宽 |
| `gui/**/*` | `*` | `""` | **过宽**（目录前缀不豁免） |
| `**/*.tsx` | `*.tsx` | `.tsx` | 放行 |
| `*Map*` | `*Map*` | `Map` | 放行 |
| `*.*` | `*.*` | `.` | **过宽**（`.` 不是字母数字） |
| `?` | `?` | `?` | **过宽** |
| `src/**` | `**` | `""` | 过宽 |

`_BROAD_EXACT`（`:137-146`）在规则之前短路：`*`、`**`、`**/*`、`**/**`、`./*`、`./**`、`./**/*`、`./**/**`——这些去掉 `*` 后确实没有字母数字，所以该集合**逻辑上冗余**，属显式化写法（可读性 + 防回归）。

**`?` 的处理**：`base.replace("*", "")` 只去 `*`，**没去 `?`**。但判定是「是否含字母数字」，`?` 本身不是，所以 `?` 仍过宽——靠 `isalnum` 兜住，而不是靠替换集。推论：`?.tsx` 会**放行**（`.tsx` 里有字母）——语义合理但反直觉（`?.tsx` 确实限定了扩展名）。

**过宽的后果不是报错，而是换成一层目录摘要**（`:820-859`），且摘要会**限定到前缀子树**（`split_pattern_prefix` 拆出 `gui`，若 `os.path.isdir` 成立则把 `summary_root` 指向它，并追加 `Pattern scope: \`gui/\`` 说明）。

**深化讲解**（面试官参考，不要求候选人全说）
规则的关键取舍是「**目录前缀不构成约束**」：`gui/**/*` 的 `gui/` 看似限定了范围，但从「一次调用会吐出多少文件」看，它与 `**/*` 没有量级差别。所以判定落在**文件名**上：有没有一个「名字线索」把结果收敛到可读规模。

反过来说，`**/*.tsx` 放行是因为扩展名本身就是强线索。这条规则把「线索」定义为「字母数字字符」，是宽松到几乎不会误伤的启发式。



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

### XEYO-QA-0181 `build_rg_args` 的参数装配顺序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Grep rg 参数编译 | argv 装配 | 中等 | 机制解释 | `python/tools/grep_tool/grep_tool.py:175-242` |

**面试官提问**
`build_rg_args` 把 `GrepInput` 编译成 `rg` 的 argv。请说出装配**顺序**，并解释两处以 `-` 开头的处理为什么必要。

**参考答案要点**
装配顺序（`grep_tool.py:189-242`）：

| 序 | 参数 | 触发条件 | 位置 |
|---|---|---|---|
| 1 | `--hidden` | 恒定 | `:192` |
| 2 | `excluded_dir_globs()`（排除目录 + 密钥 glob） | 恒定 | `:194` |
| 3 | `--max-columns 500` | 恒定（`MAX_COLUMNS = 500`，`:41`） | `:196` |
| 4 | `--max-columns-preview` | 仅 `output_mode == "content"` | `:199-200` |
| 5 | `-U --multiline-dotall` | `multiline=True` | `:202-203` |
| 6 | `-i` | `case_insensitive=True` | `:205-206` |
| 7 | `-l` / `-c` | `files_with_matches` / `count` | `:208-211` |
| 8 | `-n` | `content` 且 `show_line_numbers` | `:213-214` |
| 9 | `-C` 或 `-B`/`-A` | `content` 模式上下文（`context` → `context_c` → (`context_before`,`context_after`) 择一） | `:216-226` |
| 10 | pattern（或 `-e pattern`） | 恒定 | `:228-233` |
| 11 | `--type <t>` | `type` 给定 | `:235-236` |
| 12 | `--glob <g>` × N | `glob` 给定，按 `split_glob_patterns` 拆分 | `:238-240` |

**两处 `-` 处理**。第一处是 pattern（`:229-233`）：

```python
	pattern = input_data.pattern
	# 以 - 开头的 pattern 必须用 -e，避免被当成 rg 选项
	if pattern.startswith("-"):
		args.extend(["-e", pattern])
	else:
		args.append(pattern)
```

第二处在 `split_glob_patterns`（`:175-186`）——**空格先拆；不含花括号的再按逗号拆；含 `{a,b}` 的整段保留**：

```python
	for raw in glob.split():
		if "{" in raw and "}" in raw:
			patterns.append(raw)
		else:
			patterns.extend(p for p in raw.split(",") if p)
	return [p for p in patterns if p]
```

否则 brace 模式 `*.{ts,tsx}` 会被逗号拆成 `*.{ts` 与 `tsx}` 两个坏模式。

**为什么 `-` 必须特殊处理**：`rg` 的 argv 解析把 `-` 开头的位置参数当**选项**。搜 `-foo`（例如 YAML 列表项 `- name:`）若不包 `-e`，会报 unrecognized flag。`-e` 是标准的「后续参数是 pattern」显式开关。

**上下文参数的优先级链**（`:217-226`）：`context`（前后同时）> `context_c`（`-C` 别名）> 分别的 `context_before`/`context_after`。一旦有 `context`/`context_c`，`-B`/`-A` 整体跳过——两者**不会同时出现**。

**深化讲解**（面试官参考，不要求候选人全说）
`--max-columns` 防 base64/压缩内容单行刷爆上下文（`:40-41` 注释）；`--max-columns-preview` 仅 content 模式加，**替代** rg 默认的 `[Omitted long matching line]`，让长行显示行首预览（`:197-198` 注释），模型无需额外 Read 就能看到命中内容开头。

`split_glob_patterns` 是「schema 写单值、实现收多值」的宽容输入面：schema 里 `glob` 是单个字符串（`:403-406`），实际可传空格/逗号分隔的多值。



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

### XEYO-QA-0182 Read 态账本的淘汰演算

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 读态账本 | LRU 不变式与测试口径 | 中等 | 机制解释 | `python/tools/fileio/read_state.py:46-50,95-108` + `python/tests/test_file_tools_contract.py:267-275` |

**面试官提问**
现有 `ReadFileState(max_entries=16)`。依次执行：`set` 17 个路径（`f0`…`f16`）；`get("f0")`；再 `set` 18 个新路径（`g0`…`g17`）。最后 `f16` 还在吗？请逐条说明依据的不变式。

**参考答案要点**
**`f16` 已不在。**

①`set` `f0`…`f16`：字典序 `f0..f16`，长度到 17 触发 `while len > 16` → 淘汰头部 `f0`；剩 `f1..f16`，`f16` 在末尾（最新）。

②`get("f0")` → `None`（已淘汰），无副作用。

③`set` `g0`…`g17`：每插一个淘汰头部一个。

- 插 `g0` → 淘汰 `f1`；剩 `f2..f16, g0`
- 插 `g1` → 淘汰 `f2`；剩 `f3..f16, g0, g1`
- ……每个 `g` 淘汰一个 `f`
- 插 `g15` 时 `f` 侧只剩 `f16`，插入后长度 17 → 淘汰 **`f16`**；剩 `g0..g15`
- 插 `g16`、`g17` → 淘汰 `g0`、`g1`；最终剩 `g2..g17`

所以 `f16` 在插入 `g15` 时被淘汰。

**不变式清单**（`read_state.py:95-108`）：

| 不变式 | 代码依据 |
|---|---|
| 字典插入序 = 「最近使用」序（末尾最新） | `set` 用 `pop` + `[key]=entry` 使新条目到末尾（`:103-106`） |
| 命中查询会刷新 | `get` 命中时同样 `pop` + 重插（`:98-100`） |
| 淘汰只从头部取，且是 `while` 而非 `if` | `while len(...) > self._max_entries: pop(next(iter(...)))`（`:107-108`） |
| 同键覆盖不增长长度 | 先 `pop(key, None)`（`:105`） |
| 键归一化 | `_key` = `normcase(normpath(path))`（`:89-93`） |

**测试盲区提醒**：`tests/test_file_tools_contract.py:267-275` 用 `max_entries=16`（经环境变量）写 20 条，断言 `f0.txt` 被淘汰、`f19.txt` 保留。该用例只验证「最旧被淘汰、最新保留」一个方向，**没有**覆盖「`get` 会刷新新鲜度」——若有人删掉 `get` 里的重插，该用例仍会绿。

**深化讲解**（面试官参考，不要求候选人全说）
手写 LRU 的风险集中在不变式③：用 `if` 代替 `while` 时，任何非经 `set` 的批量写入都可能留下超限状态（当前 `load_meta` 是逐条 `set`，所以安全）。用 `while` 是有意为之。

另一个易错点：下限是 8（`max(8, int(max_entries or _max_entries_from_env()))`，`:50`），**无法构造更小的账本**来观察淘汰——所有基于 8 以下的实验都会得到 8 的行为。



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

### XEYO-QA-0183 content 排序键与 `--` 上下文分隔行

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Grep content 排序 | 分隔行的排序键 | 中等 | 代码阅读 | `python/tools/grep_tool/grep_tool.py:277-332,606-608` |

**面试官提问**
`Grep` 在 `content` 模式下对 rg 输出做**确定性排序**再分页。读下面的排序键，回答：一行纯 `--`（rg 的上下文分隔行）会被排到什么位置？为什么？这对分页稳定性意味着什么？

```python
def _split_rg_path_prefix(line: str) -> tuple[str, str] | None:
	"""
	拆分 rg 输出的 path 前缀与剩余部分。
	Windows 盘符路径（C:\\...）需跳过驱动器冒号，避免把 D: 当成分隔符。
	"""
	start = 0
	if re.match(r"^[A-Za-z]:[\\/]", line):
		start = 2
	elif line.startswith("\\\\") or line.startswith("//"):
		start = 2
	colon = line.find(":", start)
	if colon <= 0:
		return None
	return line[:colon], line[colon:]


def _content_line_sort_key(line: str) -> tuple[str, int]:
	"""content 行确定性排序键：先按路径、再按行号（rg 遍历序不稳定）。"""
	parts = _split_rg_path_prefix(line)
	if parts is None:
		return (line, 0)
	file_path, rest = parts
	m = re.match(r":(\d+):", rest)
	num = int(m.group(1)) if m else 0
	return (file_path.replace("\\", "/").lower(), num)
```

**参考答案要点**
**排在结果最顶端**（同一路径分组内最前）。

推导：

1. 分隔行是纯 `--`。`_split_rg_path_prefix("--")`：`start = 0`（不匹配盘符/UNC 正则），`line.find(":", 0)` → `-1` → `colon <= 0` → 返回 `None`（`:287-289`）。
2. 于是走 `return (line, 0)` → 键为 `("--", 0)`。
3. 正常行键是 `(路径小写, 行号)`，形如 `("src/a.py", 12)`。
4. 元组比较先比字符串：`-` 的码位是 `0x2D`，而路径首字符通常是字母、数字、`.`、`/`（码位均大于 `-`）。所以 `("--", 0)` 最小 → **最前**。

仅当路径首字符的码位**小于** `-`（`!` `"` `#` `$` `%` `&` `'` `(` `)` `*` `+` `,` 等）时才会改变，属极罕见文件名。

**为什么会出现分隔行**：`rg` 在 `-A/-B/-C`（上下文）模式下用 `--` 分隔**不同命中块**。这些行不是匹配结果、不含路径信息，所以排序键无法把它们归到正确位置——这是**排序键的信息缺失**，不是排序算法的问题。

**对分页稳定性的后果**：

- 分隔行错位 → 分页边界可能落在块中间 → 模型看到「上半块 + 下半块」被拆散；
- 更关键的是**块间顺序仍不确定**：每个分隔行的键都是 `("--", 0)`，彼此**相等**。Python `sort` 稳定，但相等元素的相对顺序取决于 rg 的**原始输出序**——而原始输出序正是注释点名的「不稳定」来源（`:317`：「先按路径、再按行号（rg 遍历序不稳定）」）。所以**确定的只有「分隔行整体位于前部」**，它们之间以及它们与所属块的对应关系都不确定。

**深化讲解**（面试官参考，不要求候选人全说）
注释点明了排序目的（`:606-607`：「确定序：先按 (路径, 行号) 排好再分页，避免 rg 遍历序跨调用漂移」），但排序键**没有**为分隔行设计归属。更完整的设计会让键携带「所属块首行号」，或在排序前把「块」作为整体单位——当前是简化版。

对照 `count` 模式的排序键（`:327-332`）：

```python
def _count_line_sort_key(line: str) -> tuple[str]:
	"""count 行确定性排序键：按路径。"""
	colon = line.rfind(":")
	if colon <= 0:
		return (line,)
	return (line[:colon].replace("\\", "/").lower(),)
```

它用 **`rfind`**（最后一个冒号），因为 count 行是 `path:count` 且 Windows 路径里也有冒号；content 则用 `_split_rg_path_prefix` 专门跳盘符冒号。同一问题两种解法。



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

### XEYO-QA-0184 `Edit` 校验缓存的两条清理路径

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Edit 跨方法传参 | `_last_*` 缓存生命周期 | 中等 | 机制解释 | `python/tools/file_edit_tool/file_edit_tool.py:274-293,431-435,470-474,532-533,604-608` |

**面试官提问**
`Edit` 用四个实例属性（`_last_actual_old` / `_last_encoding` / `_last_endings` / `_last_file_content`）把 `validate_input` 的结论传给 `call`。这些属性在哪些时机被清理？如果漏了清理会发生什么？有没有测试守住这一点？

**参考答案要点**
**清理时机两处**：①`validate_input` **每次进入时先清**（`:291-293`）；②`call` 成功结束时清（`:532-533`），以及 `execute` 捕获到 `call` 抛错时清（`:604-608`）。

属性清单与写入点（`:274-279`、`:431-435`）：

```python
	_LAST_VALIDATION_ATTRS = (
		"_last_actual_old",
		"_last_encoding",
		"_last_endings",
		"_last_file_content",
	)

	def _clear_validation_cache(self) -> None:
		"""清掉上次校验挂在实例上的跨调用缓存。

		这些属性是 validate→call 的隐式传参；call 失败/中止时不清理，
		残留值会污染下一次调用（例如把上一个文件的内容写进新建文件）。
		"""
		for attr in self._LAST_VALIDATION_ATTRS:
			if hasattr(self, attr):
				delattr(self, attr)
```

```python
	def validate_input(self, input_data: EditInput) -> dict[str, Any]:
		# 每次校验先重置：保证 call 读到的缓存一定来自本次校验。
		self._clear_validation_cache()
```

```python
		# 把校验期发现的 actual 挂到临时属性，call 再用（避免二次不一致）
		self._last_actual_old: str | None = actual
		self._last_encoding: str = encoding
		self._last_endings = endings
		self._last_file_content: str = file_content
```

`call` 侧优先用缓存、缺失则重读（`:470-475`）：

```python
		# 优先使用 validate 缓存；否则重读
		file_content = getattr(self, "_last_file_content", None)
		encoding = getattr(self, "_last_encoding", "utf-8")
		endings = getattr(self, "_last_endings", "LF")
		if file_content is None:
			file_content, endings, encoding = read_text_file(full)
```

**漏清理会怎样**：`call` 里有一条**提前返回分支**——「新文件创建」（`:444-448`）在 `_persist` 之后直接 `return EditOutput(...)`，**不读任何 `_last_*`**。所以旧值本身不会污染新建文件。真正的污染面是**通用编辑路径**：若上一次校验残留了 A 文件的 `_last_file_content`，而本次是 B 文件但 `validate` 因某种原因没刷新（例如走了 `old_string == ""` 的空白文件分支就返回 `{"result": True}`，此时 `call` 仍会进通用路径），`call` 就会**拿 A 的内容做替换基底并写回 B 文件**。

`execute` 层的兜底清理正是为这条路径准备的（`:604-608`）：

```python
		except Exception as e:  # noqa: BLE001
			# call 失败也要清缓存：残留的 _last_* 属于上一次校验，
			# 可能污染下一次调用（跨文件内容写入）。
			self._clear_validation_cache()
			return ToolResult(content=str(e), is_error=True)
```

**有没有测试守住**：有，两个。`tests/test_file_tools_contract.py:279-316`（`test_edit_validation_cache_not_leaked_across_calls`）先对 `a.py` 做一次成功 `Edit`，再对空文件 `b.txt` 走 `old_string=""` 分支，断言 `b.txt` 内容**只有** `fresh content`；同文件 `:319-346`（`test_edit_failed_call_does_not_poison_next_new_file`）手工注入 `_last_file_content = "POISON_FROM_A"` 与 `_last_actual_old` 后走新建分支，断言目标文件干净。**注意**：第二个用例的注释（`:326-330`）自陈「手工塞入残留属性后走新建文件分支」是「等价验证」——它守住的其实是**新建分支不读缓存**这条性质，而**不是**「通用路径 + 残留缓存」那条更危险的组合。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的核心是「**隐式跨方法传参**」这一反模式的代价：`validate` 与 `call` 之间靠实例属性通信，就必然要维护属性的生命周期；而 `execute` 的调用序列是 `validate → check_permissions → call`，**中间插入的任何失败**（权限拒绝、abort）都会让 `validate` 的结果悬在那里。当前实现用「入口先清 + 出口（成功/异常）清」的双向策略覆盖了绝大多数序列，但**权限拒绝这条路径不清理**（`:593-594` 直接 return）——由于下一次调用入口会先清，所以是安全的：安全性来自「入口必清」这条更强的保证。



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
### XEYO-QA-0185 Glob 分页与大小写重试的混用

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Glob 大小写重试 | 分页下的模式混用 | 困难 | 故障排查 | `python/tools/glob_tool/glob_tool.py:861-900` |

**面试官提问**
某仓库里有 40 个 `Handler.py` 这样首字母大写的文件。模型执行：

```
Glob(pattern="handler.py", offset=0,  head_limit=20)   # 第 1 页
Glob(pattern="handler.py", offset=20, head_limit=20)   # 第 2 页
```

两页合并起来能覆盖全部 40 个文件吗？请指出代码里决定这件事的那一行，并说明这个行为是「有意设计」还是「缺陷」。

**参考答案要点**
**不能。第 1 页走大小写不敏感匹配（`--iglob`）得到若干大写文件名，第 2 页走大小写敏感匹配（`--glob`）→ 零命中。两页来自两种不同的匹配模式。**

决定这件事的是 `glob_tool.py:883` 的 `off == 0`：

```python
			# --- 1) 空结果 + 含字母 → iglob 重试 ---
			if not files and off == 0 and _pattern_has_letters(pattern):
				files, truncated, total, spill_path = perform_glob(
					pattern=pattern,
					root_dir=root,
					limit=head_limit,
					offset=off,
					abort=abort,
					case_insensitive=True,
					ignore_roots=(self._cwd,),
					session_id=session_id,
				)
				case_retry = bool(files)
				if case_retry:
					_bump_stat("case_retries")
```

`off == 0` 这个条件把重试限制在**只对第一页生效**。原因可以从缓存键反推（`:862-864`）：

```python
		# --- 4) TTL 缓存：相同 (pattern, root, limit, offset) 60s 内不重扫 ---
		# 大小写重试的结果一并烘焙进缓存：命中即零磁盘扫描。
		scan_key: tuple = ("files", pattern, root, head_limit, off)
		cached_scan = _glob_cache_get(scan_key)
```

**缓存键含 `offset`**，所以第 1 页与第 2 页是两个独立的缓存项、两次独立的 rg 调用。若允许第 2 页也重试，`perform_glob` 会以 `case_insensitive=True` 再跑一遍（`offset=20` 的切片），**理论上**能拿到正确的第 2 页——但代价是：

1. 每次分页都要先跑一遍失败的大小写敏感查询（浪费一次全树扫描）；
2. 更本质的问题：**重试判据是「本页为空」**，而一个「第 1 页有大写命中、第 2 页恰好没有」的正常场景（例如命中数正好在 20 个上下）会让第 2 页错误地切换到 `--iglob`，把**小写**文件也混进来。也就是说 `off == 0` 是在用「牺牲跨页一致性」换「避免末页模式突变」。

**这是缺陷还是设计**：从证据看是**未处理的缺陷**，而非有意取舍——

- 代码没有注释说明 `off == 0` 的理由（对比同函数中 `_exclusion_args` 的大小写覆盖注释写得非常详细，`glob_tool.py:244-249`）； 
- 测试只覆盖了单页：`tests/test_glob_optimize.py:114` 的 `test_case_insensitive_retry` 不带 `offset`；
- 提示词向模型承诺的是「Empty first pass with letters in the pattern retries case-insensitively」（`glob_tool/prompt.py:17-18`）——**措辞是 `first pass`，没有承诺分页一致性**，所以从契约角度它是「说了实话但没兜住场景」。

**可复现的最小场景与观测点**：`offset=0` 时 `metadata.case_insensitive_retry` 为 `true` 且内容含 `(Case-insensitive retry: first pass had 0 matches; showing --iglob results.)`（`:911-915`）；`offset=20` 时该标记消失、内容为 `No files found`。**两个 metadata 一对比，缺陷可见**——这也是本批推荐的复现方式（无需构造 40 个文件，只要命中数少于 `head_limit` 即可观察到第 2 页的模式切换）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的推理链是：**分页正确性依赖「各页用同一判据」**。凡是「根据本页结果动态切换查询模式」的设计，都必须在**页与页之间保持模式一致**（例如把模式连同页号一起缓存，或把「是否重试」提到会话级状态）。当前实现把模式选择放在了页内局部，所以只有 `offset=0` 一页能享受重试。

顺带一个已知的**呼应问题**（另见 0190）：大小写重试趟用 `--iglob`，与排除项用的 `--glob` **属不同集合、不按后者优先覆盖**，所以 `_exclusion_args` 必须把全部排除项再以 `--iglob !rule` 后置补一遍——即「模式切换」这件事在参数层也留下了补丁痕迹。



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

### XEYO-QA-0186 `Read` 的 `total_lines` 与尾随换行

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead 行数口径 | split 产生的 phantom 行 | 困难 | 场景设计 | `python/tools/file_read_tool/file_read_tool.py:474-475,542-557` |

**面试官提问**
一个内容为 `"a\nb\nc\n"`（9 字节，磁盘上一行一换行、末尾有换行）的文件，`Read` 报告的 `total_lines` 是多少？这个数字对 `Read` 自己的输出、对 `offset` 越界警告分别有什么影响？如果用 2,000 行以上的文件配合无 `limit` 读取，会出现什么让模型误解的现象？

**参考答案要点**
`total_lines` 是 **4**。

`file_read_tool.py:474-475`（原文）：

```python
		all_lines = content.split("\n")
		total_lines = len(all_lines) if content else 0
```

`"a\nb\nc\n".split("\n")` → `["a", "b", "c", ""]`，长度 **4**。这正是审计报告里那条 `TOOL-08` 的现象（`docs/全项目BUG排查-20260910.md:140`：「`Read` 按 `\n` 切分，尾随换行产生 phantom 行 → total_lines off-by-one」），本批已按当前行号复核（该文档指向 `474-475`，与实测一致）。

**三处影响**：

**① 影响 `add_line_numbers` 的输出行数**。`map_tool_result_to_content` 走 `add_line_numbers(output.content, start_line=...)`（`:547`），而 `add_line_numbers` 内部**再切一次** `content.split("\n")`（`fileio/text.py:83-91`）。所以 `Read` 全文件时模型会看到 **4 行输出**——第 4 行是 `     4→` 后面跟空内容。行的存在感来自那个 `→` 箭头，模型容易把它读成「文件第 4 行是空行」。

**② 影响 `offset` 越界警告的阈值**。判断「文件比 offset 短」用的就是 `total_lines`（`:553-557`），所以对上述文件执行 `offset=5` 会得到 `The file has 4 lines.`——**报出的行数比人类数出来的多 1**。反过来，`offset=4` 不会触发警告，而是返回 `content=""` 吗？不——`all_lines[3:4]` 是 `[""]`，`"\n".join([""])` 是 `""`（空串）；`output.content` 为空 → 走第三条分支 → `total_lines != 0` → 输出 `Warning: ... is shorter than the provided offset (4). The file has 4 lines.`。**即模型传 `offset=4`（一个它按 `total_lines` 推断为合法的值）会得到「文件比 4 短」的自相矛盾消息**——这是本题最锋利的一处。

**③ 无 `limit` 时的静默截断与漏报**。`effective_limit = MAX_LINES_TO_READ if limit is None else limit`（`:508`），`MAX_LINES_TO_READ = 2000`（`prompt.py:9`）。所以读一个 5,000 行文件、不给 `limit`，只会返回前 2,000 行——而**返回的文本里没有任何「已截断」标记**（`map_tool_result_to_content` 的四个分支都不检查截断）。`total_lines` 确实被算成 5001 并放进 `ReadOutput`，但 `map_tool_result_to_content` **根本不使用它**（只在 `content` 为空的两个警告分支里用到）。于是模型看到 2,000 行编号输出，**无从知道后面还有 3,001 行**——这就是审计报告 `TOOL-09` 指出的「模型误以为读全」（`docs/全项目BUG排查-20260910.md:141`）。

**深化讲解**（面试官参考，不要求候选人全说）
三处影响的根因是同一个：**`total_lines` 与「实际交付的行数」是两个不同的量，而工具结果里只呈现后者**。

- ①③ 是「呈现层没把两个量对齐」；
- ② 是「判据使用了一个多 1 的口径」。

★ 修复方向（供参考，本批不含源码改动）有三条互不冲突：把 `total_lines` 改成 `content.count("\n") + (0 if content.endswith("\n") else 1)` 或 `len(content.splitlines())`；在截断时给结果追加一句事实性的 `[showing lines 1-2000 of 5001]`；把 `total_lines` 暴露到 `metadata`，让模型或 GUI 自行消费（现在 `ReadOutput.total_lines` 只用于两个警告分支）。

注意 `content.splitlines()` 与 `split("\n")` 的语义差别不止尾随换行：`splitlines` 还会把 `\v`、`\f`、`\x1c`… 以及 Unicode 行分隔符当换行，而 `read_text_file` 已经把 `\r\n`/`\r` 归一化过了，所以两者差异**恰好在尾随换行这一点上**。



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

### XEYO-QA-0187 同毫秒 mtime 下的陈旧判定失效

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 新鲜度判据 | mtime 精度与 stale 判定 | 困难 | 场景设计 | `python/tools/fileio/text.py:17-19` + `python/tools/file_write_tool/file_write_tool.py:324-329` |

**面试官提问**
`get_mtime_ms` 用 `math.floor(os.path.getmtime(path) * 1000)`。在 Windows 上（文件时间戳精度通常为 100 ns，但改造/写入同一文件的两次操作可能落在**同一毫秒**内），这套判据会不会漏判「文件已被外部修改」？请给出失效场景，并说明代码里有哪些**兜底**能救回一部分。

**参考答案要点**
**会漏判。**

`fileio/text.py:17-19`：

```python
def get_mtime_ms(path: str) -> int:
	"""floor(mtimeMs)。"""
	return math.floor(os.path.getmtime(path) * 1000)
```

判据是**严格大于**（`file_write_tool.py:324-329`）：

```python
			entry = self._read_state.get(full)
			mtime = get_mtime_ms(full)
			if (
				entry is not None
				and mtime > entry.timestamp
				and entry.content_known
			):
```

**失效场景**：外部编辑器（或另一个进程）在**同一毫秒内**完成写入，使 `mtime == entry.timestamp` 而非 `>`。此时：

- `call` 的陈旧分支不触发 → 不做 `is_full and old_content == entry.content` 的内容比对；
- `validate_input` 的对应分支（`file_write_tool.py:285`）同样不触发;
- 于是 `Write`（整文件替换）**直接覆盖**，`Edit` 则在 `find_actual_string` 上碰运气。

对 `Write` 而言这**未必是坏事**（它本来就要整文件替换）；对 `Edit` 而言，风险落在 `old_string` 匹配上：若外部改动恰好没碰到 `old_string` 所在区域，`Edit` 会**静默地基于旧内容计算新内容并写回**——把外部改动**回退**掉。这是「无提示的数据丢失」类故障，且**难以复现**（依赖毫秒级时序）。

另外 `floor` 还有一个方向性问题：`getmtime` 返回的是**浮点秒**，`floor(x*1000)` 在浮点误差下可能比真实的毫秒值**小 1**（例如 `1.2349999999` 秒本应是 1235 ms，`floor(1234.9999999)` = 1234）。这会让 `mtime` 更**容易**满足或更容易不满足判据，方向不确定——属于典型的「用浮点时间戳做相等比较」陷阱。

**兜底有几层（但都不覆盖上述场景）**：

1. **`Edit` 自己的匹配兜底**：若外部改动碰掉了 `old_string`，`find_actual_string` 返回 `None` → `errorCode 8` / `RuntimeError('String to replace not found in file.')`（`file_edit_tool.py:406-415,496-499`）——**这是最常见的救命路径**，但它只在「改到了目标区」时生效。
2. **写入侧 store 的 base_hash**（多 agent / 子 agent 场景）：`WriteStore.submit_sync` 用**内容哈希**而非 mtime 判 stale（`file_write_tool.py:138-151` 的 `base_hash` 三来源）。内容哈希不受毫秒精度影响，所以在**有 write_store** 的路径上这类漏判被根治。**但单 agent 默认无 store**（`_write_store is None` 直通旁路，`:125-135`），所以默认路径没有这层保护。
3. **`workspace_revision`**（B03）：它是**检测**而非阻止，且不参与写路径——只能事后告知「环境已变」。
4. **`session_presence` 归因**：只在**拒绝已经发生**后才附加信息；它对「没有拒绝」的场景无能为力。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于揭示「**用 mtime 做新鲜度判据的固有权衡**」：mtime 便宜（一次 `stat`）但精度与可靠性都不足；内容哈希可靠但要求持有或现读全文。当前实现是**混合策略**：

- `validate_input` / `call` 用 mtime 做**廉价初筛**（`mtime > timestamp` 才做内容比对）；
- 初筛通过后再用「全文件读取且内容一致」做**精确豁免**（`is_full and old_content == entry.content`，`file_write_tool.py:291`）——这一步的存在说明作者知道 mtime 会误报，专门加了豁免；
- 但**反方向（漏报）没有对称处理**：`mtime == timestamp` 时不做任何检查。

工程上把判据改成 `mtime != entry.timestamp` 会更保守（牺牲精度换不漏报），但会引入误报（同毫秒内的正常自写也会触发比对——不过比对本就豁免一致内容，所以代价可控）。这是一条**值得验证的改进假设**，本批列入待确认项。



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

### XEYO-QA-0188 `Read` 去重与老化开关的互斥

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead 去重 vs 老化 | 五条件互斥 | 困难 | 场景设计 | `python/tools/file_read_tool/file_read_tool.py:356-375` + `python/engine/aging.py:19,40-52` |

**面试官提问**
`Read` 的「文件未变化」去重有五个必须同时成立的判据。其中一条是「老化未开启」。请说明这条判据存在的理由，以及「老化开启/关闭」两种状态下，`Read` 的行为分别是什么。

**参考答案要点**
判据原文（`file_read_tool.py:356-375`）：

```python
		# 去重：同路径同 range 且 mtime 未变 → stub
		# 老化开启时跳过去重（R1）：unchanged-stub 会指向可能已被老化清除的
		# 早期读取结果，模型无从参照——宁可真读，不可悬空引用。
		# symbol 读取绕过去重：目标 range 不同于任何全文件/分页记录。
		existing = self._read_state.get(full)
		if (
			existing
			and input_data.symbol is None
			and not aging_enabled()
			and not existing.is_partial_view
			and existing.offset is not None
			and existing.offset == offset
			and existing.limit == limit
		):
			try:
				if get_mtime_ms(full) == existing.timestamp:
					return ReadOutput(type="file_unchanged", file_path=input_data.file_path)
			except OSError:
				pass
```

五条判据（外加 mtime 相等这条第六判据）：

| # | 判据 | 作用 |
|---|---|---|
| 1 | `existing` 存在 | 本会话读过 |
| 2 | `symbol is None` | 符号读取的 range 与全文件/分页记录不同，必须真读 |
| 3 | **`not aging_enabled()`** | 老化开启时不去重 |
| 4 | `not existing.is_partial_view` | 部分视图不作为去重依据 |
| 5 | `offset` 与 `limit` 都相同 | 「同 range」 |
| 6 | `get_mtime_ms(full) == existing.timestamp` | 磁盘未变 |

**判据 3 的理由**（注释即答案）：「老化开启时跳过去重（R1）：unchanged-stub 会指向可能已被老化清除的早期读取结果，模型无从参照——宁可真读，不可悬空引用。」

综合 `engine/aging.py` 的事实（B03 已确立）：老化会把较早的 **toolout 占位**替换/清除以省上下文，且**「toolout 占位的恢复机制落地前保持关闭」**（`aging.py:4-5`）。所以：

| 老化状态 | `Read` 行为 | 理由 |
|---|---|---|
| **关**（默认，`aging_enabled()` 返回假） | 去重生效：第二次读同一路径同区间且 mtime 未变 → 返回 `FILE_UNCHANGED_STUB` 而不是正文 | 早期读取结果**仍在上下文里可达**，stub 的指向有效 |
| **开**（`XEYO_AGING_TOOLOUT` 等开关打开） | 去重**整体跳过** → 每次都真读、每次都返回正文 | 早期结果**可能已被清除**，stub 会指向不存在的内容 → 「悬空引用」，比多花令牌更糟 |

**为什么「宁可真读」是正确取舍**：unchanged-stub 的全部价值在于「模型能参照到那段内容」。一旦被参照物可能不存在，stub 就从「省令牌的优化」变成「**制造幻觉的诱饵**」——模型会相信自己确实拿到过内容，进而基于记忆中的模糊印象继续操作。所以这不是性能取舍，而是**正确性取舍**。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的推理结构值得单独记：**「优化」的前提条件是它引用的外部状态必须仍然成立**。去重优化的前提 = 「早期 Read 结果可达」；老化恰好破坏这个前提。因此两个机制虽然各自独立，却必须**显式互斥**（`not aging_enabled()` 直接写在条件里）。

这也解释了为什么这个条件被放在**条件列表的第 3 位而不是函数开头**：它是「去重的语义前提」，与 `symbol is None`（同 range 前提）、`is_partial_view`（视图完整性前提）属于同一类——三条都是「关于被引用对象是否可信」的前提判断，而不是「有没有发生过读」的事实判断。

**边界**：`aging_enabled()` 每次调用都执行一次（在 `Read` 的主路径上），所以**开启老化后会立刻生效**，不需要重建会话。反过来，配置切换也让「同一路径同一区间第一次读到 stub、第二次读到正文」成为可能——这不是不稳定，而是配置变更的正常后果。



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

### XEYO-QA-0189 content_index 的「全或无」保证

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 内容索引 | 超集完整性的代价 | 困难 | 场景设计 | `python/tools/fileio/content_index.py:28-33,86-115` |

**面试官提问**
`_build_index` 里有 5 处 `return None` 的放弃点。请说明这条「全或无」纪律的**必要性**，以及它对**大型仓库**意味着什么。若有测试想验证「一定不漏文件」，应该构造什么样的小场景？

**参考答案要点**
**5 个放弃点**（`content_index.py:86-115`）：

| 放弃点 | 触发 | 行 |
|---|---|---|
| 列文件失败 | `_list_roots_files` 返回 `None`（rg 异常/超时） | `:88` |
| 文件数超限 | `len(all_files) > _MAX_INDEXED_FILES`（**20,000**） | `:88` |
| 单文件 stat 失败 | 文件消失/不可访问 | `:100-102` |
| 单文件过大 | `size > _SKIP_FILE_BYTES`（**2 MiB**） | `:103-104` |
| 累计过大 | `total_bytes > _MAX_INDEXED_BYTES`（**64 MiB**） | `:106-107` |
| 读失败 | `open` 抛 `OSError` | `:111-112` |

**必要性**：`lookup` 返回 `[]` 时 `Grep` 会**直接宣布零命中**（见 0177）。这个结论的正确性**唯一依赖**「索引覆盖了全部（非排除）文件」——trigram 交集为空只能证明「在**已索引的文件集合**里没有候选」。若索引**部分**覆盖，空交集就可能是假阴性：文件 `f` 含目标字面量但没被索引 → 交集空 → `Grep` 报零命中 → **模型得到错误的事实**。所以纪律是：「要么覆盖全部，要么完全不加速」（`:12-13`）。

**对大型仓库的后果**：`XEYO` 本仓就是例子——`_MAX_INDEXED_BYTES = 64 MiB` 与 `_SKIP_FILE_BYTES = 2 MiB` 两个上限在**中大型仓库上极易触发**（单个 `package-lock.json`、`uv.lock`、`*.min.js` 就可能超 2 MiB）。一旦触发，该 root **永久退化**为全量 rg——注意 `_get_or_build` **会把 `None` 也写入缓存**（`:124-131`，`_cache[root] = (时间, idx)`），所以在 `_TTL_S = 30.0` 内不会重试。这是有意的（注释：「重建结果（含 None）也写入缓存，避免每次重试」），代价是「探测期的坏状态会粘住 30 秒」。

**该构造什么测试**：想验证「不漏」这条性质，最小场景要**故意制造一个放弃点**，然后断言 `lookup` 返回 `None`（而非空列表）：

1. 建 root，放两个文件：一个正常小文件（含 `needle_marker`），一个 **大于 2 MiB** 的文件（`"x" * (2*1024*1024 + 1)`）；
2. 断言 `content_index.lookup(root, "needle_marker") is None`——**不是** `[]`。这一步就是「宁可失去加速，也不给假阴性」的直接见证；
3. 再删掉大文件、清缓存（`clear_content_index()`）后重试，断言 `lookup` 返回**非空列表**（含那个正常文件）。

**反向**对照组（验证 `[]` 的语义）：只放小文件、查询一个全库不存在的字面量（如 `zzzz_never_present`），断言返回 `[]`。**第 2 步与对照组合起来，才完整证明了「`[]` 与 `None` 的差别正是安全边界」**。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的核心是「**用可用性换正确性**」在缓存层的落地。值得对比例子：`glob_tool` 的缓存（0192）在写后会**全清**——它的正确性威胁是「旧缓存藏住新文件」，靠失效解决；content_index 的正确性威胁是「索引不全 → 假阴性」，而**失效无法解决这个问题**（索引本身就不完整），所以只能放弃加速。

两者还有一个共同点：**都选择「清/放弃」而不是「局部修正」**。注释里的理由也一致——语义最简单、无副作用、写频远低于读。这是同一套工程直觉在两处的复用。



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

### XEYO-QA-0190 大小写重试趟的排除集覆盖

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Glob 排除参数 | iglob 白名单穿透 | 困难 | 代码阅读 | `python/tools/glob_tool/glob_tool.py:238-255` |

**面试官提问**
读下面的代码，回答：为什么 `case_insensitive=True` 时要把所有排除项**再补一遍**？补的为什么是 `--iglob` 而不是 `--glob`？这个补丁覆盖了哪些排除来源？

```python
def _exclusion_args(
	root_dir: str,
	ignore_roots: tuple[str, ...],
	*,
	case_insensitive: bool,
) -> list[str]:
	"""内置排除 + .agentignore 过滤参数。

	rg 中 ``--iglob`` 白名单与 ``--glob`` 排除属不同集合、互不按"后者优先"
	覆盖（大小写重试趟的 iglob 白名单会穿透前置排除项），因此 case-insensitive
	时把全部排除项再以 ``--iglob !rule`` 形式后置补一遍，保证压住白名单。
	"""
	args = excluded_dir_globs() + agentignore_args(root_dir, *ignore_roots)
	if case_insensitive:
		for flag, pat in zip(args[::2], args[1::2]):
			if flag == "--glob" and pat.startswith("!"):
				args += ["--iglob", pat]
	return args
```

**参考答案要点**
**为什么补**：大小写重试趟（`perform_glob(..., case_insensitive=True)`）用的是 `--iglob`（白名单形式传给 rg），而初始排除项是用 `--glob !xxx`（排除形式）传的。rg 中这两者**属于不同的集合，不按「后者优先」互相覆盖**——于是重试趟的 `--iglob` 白名单会**穿透**前置的 `--glob` 排除项，让 `.git` / `node_modules` / 密钥文件等重新出现在结果里。

**为什么补 `--iglob` 而不是 `--glob`**：要压住 `--iglob` 白名单，必须用**同集合**的排除项——即 `--iglob !rule`。用 `--glob !rule` 补是无效的（跨集合）。

**覆盖的排除来源**：补丁遍历 `args`（即 `excluded_dir_globs() + agentignore_args(...)`）的**所有** `--glob !...` 项，所以三类来源全被覆盖：

| 来源 | 生成者 | 内容 |
|---|---|---|
| VCS 目录 | `excluded_dir_globs()` → `search_excluded_dirs()`（`excludes.py:16-23`） | `.git` `.svn` `.hg` `.bzr` `.jj` `.sl` |
| 重型目录 | 同上（`excludes.py:25-40`） | `node_modules` `.pnpm-store` `.venv` `venv` `__pycache__` `.cache` `coverage` `.next` `.nuxt` `.yarn` `bower_components` `dist` `build` `target` |
| 密钥文件 | `excluded_secret_globs()`（`excludes.py:108-119`） | `DANGEROUS_FILES` 的名字 + `DANGEROUS_SUFFIXES` 的后缀（各出 `!name` 与 `!**/name` 两条）、`.ssh` 两条 |
| 环境变量追加 | `XEYO_SEARCH_EXCLUDE` 逗号分隔项（`excludes.py:43-52`） | 用户自定义目录名 |
| `.agentignore` | `agentignore_args`（`excludes.py:83-105`） | 非否定行转成的 `--glob !rule` |

注意**密钥排除是「双写」的**（`--glob !name` 与 `--glob !**/name` 各一条，`excludes.py:113-116`）——所以补丁也会为它们各补一条 `--iglob`，参数数量翻倍是可接受的代价。

**一个实现细节**：`zip(args[::2], args[1::2])` 把扁平的 `["--glob", "!x", "--glob", "!y", …]` 配对遍历。这依赖**`args` 里所有元素都是成对出现**——`excluded_secret_globs` 最后一条 `args += ["--glob", "!.ssh", "--glob", "!**/.ssh/**"]`（`excludes.py:118`）确实是成对的，`agentignore_args` 也是（`--ignore-file <path>` 与 `--glob !rule` 都成对）。**但 `--ignore-file <path>` 的第一个元素不是 `--glob`**，所以它会走到 `if flag == "--glob"` 判断为假而被**跳过**——这是正确的（它不是排除 pattern，无法转成 `--iglob`）。这也说明这段 `zip` 的健壮性依赖两个前提：**参数恒为成对**、以及**非 `--glob !` 项必须被显式跳过**。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的推理链是：**「同一种语义在两个 rg 参数集合里有两种表达」**，所以任何跨集合的模式切换都必须**同步迁移"约束类"参数**——否则约束会在切换时静默失效。而「静默失效」正是最危险的形态：结果里多出 `.git` 或 `node_modules` 里的条目并不报错，只是让输出变得嘈杂且可能泄露敏感文件（密钥 glob 也在被穿透之列）。

对照 0174（`.agentignore` 的后置 `--glob !rule`）可以看到，这里其实是**同一个问题的第三层**：

| 层 | 冲突双方 | 解法 |
|---|---|---|
| 1 | ignore 文件 vs 命令行 `--glob` 白名单 | 把 ignore 规则升格为命令行 `--glob !rule` |
| 2 | 用户 `--glob` 白名单 vs 排除项 | 后置（顺序保证"后面的 glob 优先"） |
| 3 | `--iglob` 白名单 vs `--glob` 排除项 | **跨集合，顺序无效** → 再补一遍 `--iglob !rule` |



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

### XEYO-QA-0191 目录摘要的 git 跟踪态分区

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Glob 目录摘要新鲜度列 | 三种分区的输出 | 困难 | 场景设计 | `python/tools/glob_tool/glob_tool.py:258-264,275-298,312-422` |

**面试官提问**
`Glob` 的「过宽 pattern → 一层目录摘要」在默认状态下会为部分目录追加新鲜度信息。请说明：**哪种目录显示日期、哪一种只显示计数、哪一种完全静默**？为什么非 git 工作区**整体静默**？「不用目录自身 mtime」的理由是什么？

**参考答案要点**
三种分区的规则在 `_fresh_col`（`:408-422`）：

```python
	def _fresh_col(tracked_count: int, total: int, n: float) -> str:
		if not fresh or tracked is None:
			return ""  # 非 git / 中止 → 静默
		untracked = total - tracked_count
		if tracked_count > 0:
			# 混合目录（B2，2026-09-09）：只报 untracked 计数——纯 git 状态
			# 事实，不带日期（权威区 mtime 是噪声，B2 不重蹈覆辙）。仅真有
			# 未收编文件时付 ~3 tok。
			if untracked > 0:
				return f" · {untracked} untracked"
			return ""  # 权威区（人已 commit）→ 静默
		col = " · untracked"  # 零 tracked：亮出分区事实 + newest（草稿区唯一有意义的问题）
		if n > 0:
			col += f" · newest {time.strftime('%Y-%m-%d', time.localtime(n))}"
		return col
```

| 分区 | 条件 | 输出 | 实测断言 |
|---|---|---|---|
| **草稿区** | `tracked_count == 0` | ` · untracked · newest YYYY-MM-DD` | `tests/test_glob_optimize.py:332`：`docs/  (1 files · untracked · newest 2026-01-01)` |
| **混合区** | `tracked_count > 0 and untracked > 0` | ` · N untracked`（**无日期**） | `:415`：`mixed/  (2 files · 1 untracked)` |
| **权威区** | 全部 tracked | `""`（完全静默） | `:435`：`full/  (2 files)` |
| **非 git 工作区** | `tracked is None` | `""`（整体静默） | `:392-394`：断言 `"untracked" not in content` 且 `"newest" not in content` |

**非 git 工作区整体静默的理由**（`:275-281` 的 docstring）：「git 跟踪是唯一确定性的『人的策展事实』——文件被 commit 过 = 人主动声明它是仓库正式状态。git 不可用 / 非 repo → None，调用方据此整体静默（无策展事实，日期失去正当性前提）。」代码落点是 `:344-345`：

```python
	if fresh and tracked is None:
		fresh = False  # 非 git / git 不可用 → 全静默
```

**不用目录自身 mtime 的理由**（`:317-318` 注释原文）：「Windows 上它只反映直接子项增删，深层修改不更新，浅信号会给错信息；逐文件 stat 是唯一真值来源。」

**「日期为什么只给草稿区」**：`_fresh_col` 的注释写得很直白——「权威区 mtime 是噪声（定稿冻结/代码日均 churn）；草稿区没有任何权威版本，『哪版最新』是唯一有意义的迭代问题」（`:312-316`）。也就是说：**已 commit 的文件改来改去是正常开发，其 mtime 不携带决策价值；未收编的文件没有任何版本记录，「最新改动在什么时候」才是模型/用户真正需要的事实**。

**两遍法与开销控制**：`tracked` 集合来自 `git ls-files -z`（`:275-298`），与 rg 目录列表**并行**执行（`ThreadPoolExecutor(max_workers=1)` 先 submit 再跑 rg，`:322-343`，注释估 ~130 ms）。随后 `:375-406` 做「两遍法」：

```python
		zero_tops = {t for t in counts if tracked_tops.get(t, 0) == 0}
		need_root = tracked_root == 0
		for rel in all_files:
			...
			if top not in zero_tops:
				continue
```

即**第二遍只对「零 tracked 目录 + 根文件（且根也需 display）」逐文件 stat**——因为 tracked 目录的 newest 永不显示，对它们 stat 是纯浪费。注释声明「输出与全量 stat 逐字节一致」（`:377-378`）。中止会在每 1,000 个文件处检查一次（`:402-406`），一旦中止就把 `fresh` 置假并清掉已收集的日期，**摘要退回旧格式**。

**深化讲解**（面试官参考，不要求候选人全说）
三个设计判断都指向同一个原则：**「只呈现模型能据以行动的事实」**。

- 权威区静默：日期没有决策价值，且会让摘要变长（每次过宽 glob 都要付这份 token）；
- 混合区只给计数：`N untracked` 是纯 git 状态事实（「这个目录里有人已经收编过一部分」），足以提示「这里混着正式与草稿」；
- 草稿区给日期：这是唯一「哪版最新」有意义的地方。

而「多付 token」这件事被显式计量：`_fresh_col` 混合区注释写「仅真有未收编文件时付 ~3 tok」。这在提示词工程层面是可贵的自律——**每条附加信息都要算清代价**。

**开关面**：默认开，`XEYO_GLOB_SUMMARY_FRESH=0` 显式关（`:258-264`），注释说明「旁路期（默认关）已验证：根级摘要 +0 token（全仓 tracked 静默逐字节一致）、scoped 下钻才在零 tracked 目录浮现 `untracked · newest 日期`。默认开无回归面」——这是一条完整的新功能准入记录：**先旁路验证收益与成本，再并入主链路**。



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

### XEYO-QA-0192 Glob 缓存的三类键与失效面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Glob TTL 缓存 | 缓存键与写后失效 | 困难 | 场景设计 | `python/tools/glob_tool/glob_tool.py:48-52,88-112` + `python/tests/test_glob_optimize.py:195-224,442-489` |

**面试官提问**
`Glob` 有 60 秒 TTL 的内存缓存。请列出代码里用到的**三类缓存键**，并说明：写操作为什么要**全清**而不是按前缀精确失效？哪一类失效场景是**测试覆盖到**的、哪一类**没有**？

**参考答案要点**
三类键（都在 `glob_tool.py`）：

| 类别 | 键构造 | 位置 | 缓存内容 |
|---|---|---|---|
| 文件列表 | `("files", pattern, root, head_limit, off)` | `:864` | `(files, truncated, total, case_retry, spill_path)` 五元组 |
| 目录摘要 | `("summary", summary_root)` | `:836` | 渲染好的摘要文本 |
| 空结果建议 | `("suggestion", pattern, root, self._cwd)` | `:939` | `(suggestion is not None, suggestion)`（**连 `None` 也缓存**） |

容量与 TTL：`_GLOB_CACHE_TTL_S = 60.0`、`_GLOB_CACHE_MAX = 128`，结构是 `OrderedDict` + `threading.Lock`，写入时 `move_to_end` 并按 `popitem(last=False)` 淘汰最旧（`:48-52,88-112`）。

**「大小写重试结果一并烘焙进缓存」**（`:862-863` 注释）：`case_retry` 是五元组的一项，所以缓存命中时也**不会重新扫描**就能给出 `(Case-insensitive retry: …)` 提示（`:911-915`）。★ 推论（本批待确认项之一）：缓存键**不含** `case_insensitive` 标记，因为重试是 `perform_glob` 内部由空结果触发的，不在 `GlobInput` 表面；若将来把 `case_insensitive` 提升为显式入参，这个键需要同步扩展，否则两种模式会互相命中。

**为什么要全清**：`clear_glob_cache()` 的实现是**全清**（`:88-90`），写入侧的注释给了理由（`file_write_tool.py:34-43`，`_invalidate_glob_cache`）：

```python
def _invalidate_glob_cache() -> None:
	"""落盘成功后失效 Glob 缓存（2026-09-09 A1）。

	此前 clear_glob_cache 全仓库零调用者：写后 60s TTL 内 Glob 命中旧缓存，
	新文件"存在但 Glob 找不到"。全清而非按路径前缀精准失效——写频远低于
	读（128 条缓存按需重建），语义最简单且无副作用。懒导入防环。
	"""
	from tools.glob_tool.glob_tool import clear_glob_cache

	clear_glob_cache()
```

三个理由：①**写频远低于读**（128 条缓存按需重建的成本可忽略）；②**语义最简单**（不用反推哪些键可能受影响——一个 pattern 可能匹配新文件的路径，`("summary", root)` 更是与 pattern 无关）；③**无副作用**。这段注释还披露了一个历史事实：`clear_glob_cache` **曾是零调用者的死代码**，即「写后 60s 内 Glob 命中旧缓存，新文件存在但找不到」的幽灵窗口曾经真实存在过。

**测试覆盖情况**：

| 场景 | 测试 | 断言 |
|---|---|---|
| 相同查询二次命中 | `test_ttl_cache_second_call_hits`（`:196-212`） | `cached` 先 False 后 True，内容相同；**不同 offset = 不同键，不命中** |
| 摘要也缓存 | `test_broad_summary_also_cached`（`:216-224`） | `glob_kind == "dir_summary"`，二次 `cached is True` |
| Write 后失效 | `test_write_invalidates_glob_cache`（`:442-458`） | 断言 `cached is not True` 且新目录 `subdir2/` 出现 |
| Edit 后失效 | `test_edit_invalidates_glob_cache`（`:462-489`） | 断言 `cached is not True or "beta_marker" in content` |
| Bash 写后失效 | `test_bash_write_invalidates_glob_cache`（`:521-535`） | 断言 `cached is not True` 且 `bg_dir/` 出现 |
| Bash 只读不清缓存 | `test_bash_readonly_keeps_glob_cache`（`:539+`） | 保缓存 |

**未覆盖的失效场景**（本批明确列为缺口）：

1. **`Bash` 写命令的「漏判」方向**：分类器 `_command_may_mutate_workspace` 的 fail-closed 语义（白名单全命中→不清；显式写/解释器/未知/命令替换→清）在 `test_bash_classifier_readonly_vs_mutating`（`:495-517`）里有正反样例，但**未知命令一律清**意味着「只读但不在白名单的外部命令」会白白清缓存——这是性能缺口而非正确性缺口，**无测试断言其影响范围**；
2. **写系统之外的写入者**：外部编辑器、构建工具、`git checkout`、另一个 XEYO 会话的写——都不经过这三个 `_invalidate_glob_cache` 调用点，**60s 窗口内的可见性没有任何保证**（与 B03 已确立的「`workspace_revision` 是检测而非阻止」是同一类结论）；
3. **`("suggestion", …)` 键的失效**：三类键中只有「文件列表」与「目录摘要」会在写后被清（因为 `clear_glob_cache` 全清，所以实际上三类都被清）——但**没有测试**断言「写后建议缓存也被清」，而建议依赖目录内容（放松 pattern 的命中集），所以这是一个**值得补的用例**；
4. **`content_index` 的联动**：`Glob` 的缓存清了，`fileio/content_index` 的 30s 索引另有 `clear_content_index()`——**Glob/Edit/Write 的 `_invalidate_glob_cache` 并不调用它**，两者由谁在写后一起清，是 B05（Bash 侧）与 B03 交界处的待确认项。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的意义是把「缓存」这件事拆成三个可独立检查的维度：**键的构造**（覆盖了哪些输入）、**失效的触发**（谁负责清）、**测试的覆盖**（哪条路径没守）。当前实现的第一维与第二维都很清晰，第三维有明确缺口——而缺口的三/四项（外部写入者、跨缓存联动）恰好都是**跨模块**场景，正是单元测试天然容易漏掉的地方。



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
### XEYO-QA-0193 `content_index_cache_shadow` 的收益边界

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio 侧挂缓存模块 | 省 CPU 而非省 IO | 困难 | 场景设计 | `python/tools/fileio/content_index_cache_shadow.py:1-26,95-145` |

**面试官提问**
`content_index_cache_shadow` 是一个「默认关」的侧挂模块。它自称收益是**省 CPU 而非省 IO**——为什么？它通过什么手段接入而不改主文件？`install()` 在未启用时会成功吗？它的「结果与原文逐位等价」这一声称，边界在哪里？

**参考答案要点**
**为什么只省 CPU**：因为**要拿到「文件内容哈希」必须先读文件**。模块 docstring 把这点写得很直白（`:8-11`）：

```
- **必须明确**：要拿到「文件内容哈希」必须先读文件。因此本模块**每次重建仍会读每个文件**，
  缓存命中只跳过**「重算 trigram set」**这一步。所以收益是**省 CPU**（未变文件不重跑 `_trigrams`），
  **不是省 IO**。真正省 IO 由 B3（`content_index_fp_shadow.py` 目录聚合指纹，跳过未变目录的
  整目录读取）承担。
```

对照实现（`:124-140`）：`open(...).read()` **无条件执行**，只有 `_hash_text(text)` 之后的 `mod._trigrams(text)` 被跳过：

```python
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return None

        # 内容哈希：命中缓存且未变 → 复用；否则重读重算。
        digest = _hash_text(text)
        with _CACHE_LOCK:
            cached = _CACHE.get(full)
        if cached is not None and cached[0] == digest:
            file_tgs = cached[1]
        else:
            READ_COUNT += 1
            file_tgs = tuple(mod._trigrams(text))
            with _CACHE_LOCK:
                _CACHE[full] = (digest, file_tgs)
```

`READ_COUNT` 的语义被 docstring 明确限定（`:22-25`）：「模块级 `READ_COUNT` 计数『**实际重算 trigram** 的文件数』（命中缓存不计）……注意：文件本身仍被读取（为算哈希），故该计数测的是 **CPU 省量，不是 IO**。」——**这是一个把指标口径写进注释的范例**：名字叫 `READ_COUNT`，但量的是 CPU，若不写明必然被误读。

**接入手段（不改主文件）**：`install()` 做**猴子补丁**（`:71-83`）：

```python
def install() -> bool:
    """挂钩 `content_index._build_index`；返回是否实际安装（仅已启用才装）。"""
    if not enabled():
        return False
    global _TARGET
    mod = importlib.import_module(_TARGET_MODULE)
    if not getattr(mod, _INSTALLED_FLAG, False):
        if not hasattr(mod, _ORIG_NAME):
            setattr(mod, _ORIG_NAME, getattr(mod, _HOOK_NAME))
        setattr(mod, _HOOK_NAME, _build_index_cached)
        setattr(mod, _INSTALLED_FLAG, True)
    _TARGET = mod
    return True
```

三点：①把原函数**改名保存**到 `_ORIG__build_index`（仅在首次安装时保存，避免二次安装覆盖原函数）；②把 `_build_index` 指向 `_build_index_cached`；③用模块级标记 `__content_index_cache_installed` 保证**幂等**。`uninstall()`（`:86-92`）把原函数**还原**回 `_build_index` 并清标记。

**`install()` 在未启用时会成功吗**：**不会——它返回 `False` 且不做任何修改**（`if not enabled(): return False`，`:72-74`）。启用判据是 `side_enabled(_ENV)`，`_ENV = "XEYO_CONTENT_INDEX_CACHE"`（`:36,51-55`），经 `sidecar.policy.side_enabled` 解析（注释：默认 0=关；「升格后默认开；专用 env / 全局 promote 可关」）。**注意 docstring 与代码注释的口径差异**：docstring 写「默认 0=关」，而 `enabled()` 的 docstring 写「升格后默认开」——实际取值由 `sidecar.policy` 决定，本批列为待确认项。

**「逐位等价」的边界**：docstring 声称（`:19-20`）「命中时拿回同一 `text→trigrams` 产物，`ContentIndex` 与原文逐位等价（超集/上限/bailout 语义全保）」。这个声称成立的**关键**是：缓存键是**文件绝对路径**（`full`），值是 `(内容哈希, trigram 元组)`，而命中条件是**哈希相等**。所以：

| 边界 | 是否等价 | 说明 |
|---|---|---|
| `files` 列表顺序 | ✅ | 缓存版按 `all_files` 顺序 append，与原文一致（`:108-112`） |
| trigram 集合内容 | ✅ | 命中时复用同一 `tuple(mod._trigrams(text))` 的**缓存副本** |
| 各放弃点（超限/读失败） | ✅ | 检查顺序与阈值**硬编码复制**（`mod._SKIP_FILE_BYTES`、`mod._MAX_INDEXED_BYTES`、`mod._MAX_INDEXED_FILES` 都从原模块取，`:104,118,121`） |
| **哈希碰撞** | ⚠️ 理论 | `blake2b(digest_size=16)`（128 位）——碰撞概率可忽略 |
| **同路径内容不同但哈希相同** | ⚠️ | 同上 |
| **原模块常量被改** | ⚠️ | 缓存版读 `mod._XXX`，所以常量变更会**同步**（这是好事） |
| **原模块 `_build_index` 的后续改动** | ❌ **真实风险** | 缓存版是**复制粘贴实现**，原函数若新增放弃点或改顺序，缓存版**不会自动跟随**——这是「逐位等价」声称最脆弱的边界 |

也就是说，等价性不是靠共享代码保证的，而是靠**实现复制的一致性**——与 0168（Write 双落盘路径）是**同一类风险**，只是这里写在 docstring 里当作契约声明。另注意 `files.append(norm)` 用了 `norm = rel.replace("\\", "/")`，而 `os.path.join(root, rel)` 用**原始 `rel`**（`:111-113`），与原模块 `content_index.py:94-97` 的写法一致（原模块同样 `norm` 进 `files`、`rel` 拼路径）。

**深化讲解**（面试官参考，不要求候选人全说）
侧挂模块的契约在 docstring `## 侧挂契约（不改主文件逻辑）`（`:14-20`）里四条俱全：`enabled()` 读环境变量；`install()`/`uninstall()` 挂钩与卸载；**fail-open**（读/哈希异常 → 与原文一致，返回 `None`）；**结果一致性**（逐位等价）。这四条是本项目「新行为先以旁路形态上线」规矩（AGENTS.md 硬规矩 #4）的具体落地形态。

本题的要点是**识别「收益口径」的诚实性**：一个模块声称「省 CPU 而非省 IO」，并且把**代价探针的语义**也写清楚（`READ_COUNT` 测 CPU 不测 IO），这在性能类改动里是罕见的自律——因为「省 IO」与「省 CPU」在用户感知上差别巨大（磁盘/网络 vs 计算），把口径说错会让验证结论完全失真。



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

### XEYO-QA-0194 符号读取与 `pack` 的元数据面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | FileRead symbol 分支 | 定位、歧义与 pack | 困难 | 代码阅读 | `python/tools/file_read_tool/file_read_tool.py:318-342,420-504,612-616` |

**面试官提问**
`Read` 传 `symbol="MyClass.handle_request"` 时走的是与 `offset`/`limit` 完全不同的路径。请说明：**先做什么、哪些前置检查被跳过、歧义如何处理、`pack=true` 多返回什么**？以及为什么 `symbol` 与 `offset`/`limit` 是**互斥**的？

**参考答案要点**
**① 互斥校验**（`file_read_tool.py:318-342`）：

```python
		if input_data.symbol:
			if input_data.offset is not None or input_data.limit is not None:
				return {
					"result": False,
					"message": (
						"symbol cannot be combined with offset/limit; "
						"pass only symbol to read one symbol's body"
					),
					"errorCode": 5,
				}
			ext = os.path.splitext(full)[1].lower().lstrip(".")
			if ext in IMAGE_EXTENSIONS or ext in BINARY_EXTENSIONS or ext == "pdf":
				return {
					"result": False,
					"message": (
						f"symbol is only supported for text source files, not .{ext}"
					),
					"errorCode": 4,
				}
		elif input_data.pack:
			return {
				"result": False,
				"message": "pack requires symbol; pass symbol with pack=true",
				"errorCode": 5,
			}
```

**为什么互斥**：`symbol` 的语义是「读一个符号体」，它的行区间由**符号定位**决定；`offset`/`limit` 的语义是「按行读一段」。两者都指定区间，同时给就是**两个真源**——无法合并，只能拒绝。同理 `pack` 单独出现无意义（没有符号可 pack），所以 `elif input_data.pack` 把它也拦下（注意是 `elif`：`symbol` 存在时 `pack` 是合法的，所以不能用独立 `if`）。

**② 定位在尺寸预检之前**（`:420-442`）：

```python
		# symbol 读取先定位（不受整文件大小预检限制——返回的只是符号体）
		sym = None
		if input_data.symbol:
			candidates = locate_all(full, input_data.symbol)
			if not candidates:
				raise RuntimeError(
					f"Symbol '{input_data.symbol}' not found in "
					f"{input_data.file_path}. Use Grep with "
					'output_mode="symbols" to list symbol names first.'
				)
			if len(candidates) > 1:
				listing = "\n".join(
					f"  - {s.kind} {s.name}"
					f"{' (in ' + s.parent + ')' if s.parent else ''}"
					f" lines {s.start}-{s.end}: {s.signature}"
					for s in candidates[:8]
				)
				raise RuntimeError(
					f"Symbol '{input_data.symbol}' is ambiguous "
					f"({len(candidates)} matches). Use a qualified path like "
					f"'ClassName.method':\n{listing}"
				)
			sym = candidates[0]
```

并且尺寸预检的豁免条件包含它（`:444-449`）：

```python
		if size > MAX_SIZE_BYTES and limit is None and sym is None:
```

注意这是 **`and sym is None`**——`symbol` 读取**完全绕过 0.25 MiB 闸门**。理由写在注释里：「symbol 读取先定位（不受整文件大小预检限制——返回的只是符号体）」。**但令牌闸门仍然生效**（见第 ④ 点）。

**③ 歧义不是自动选第一个，而是报错并列出候选**（`:430-441`）：`len(candidates) > 1` 时抛 `RuntimeError`，文案含 `Symbol '...' is ambiguous (N matches)`、引导使用 `ClassName.method` 这种限定路径，并列出**前 8 个**候选（每个含 `kind` / `name` / `(in parent)` / `lines start-end` / `signature`）。零候选时则引导用 `Grep output_mode="symbols"` **先列符号名**——这也解释了 `Grep` 的 `symbols` 模式存在的意义（`grep_tool/prompt.py:7`：「prefer it over content when looking for classes/functions/structure」）。

**④ 两条子路径与元数据**（`:477-504`）：

```python
		symbol_meta: Optional[dict] = None
		if sym is not None:
			if input_data.pack:
				from codeindex.pack import pack_symbol_context

				packed = pack_symbol_context(
					full, target=sym, source_lines=all_lines
				)
				slice_text = packed.text
				start_line_out = 1
				symbol_meta = {
					"symbol": sym.name,
					"kind": sym.kind,
					"range": [sym.start, sym.end],
					"approximate": sym.approximate,
					"truncated": packed.truncated,
					"pack_sections": list(packed.sections),
				}
			else:
				sliced = all_lines[sym.start - 1 : sym.end]
				slice_text = "\n".join(sliced)
				start_line_out = sym.start
				symbol_meta = {
					"symbol": sym.name,
					"kind": sym.kind,
					"range": [sym.start, sym.end],
					"approximate": sym.approximate,
				}
```

| 对比 | 无 `pack` | `pack=true` |
|---|---|---|
| 正文 | `all_lines[sym.start-1 : sym.end]` 原样切片 | `codeindex.pack.pack_symbol_context(full, target=sym, source_lines=all_lines).text` |
| `start_line_out` | `sym.start`（真实起始行） | **`1`**（packed 文本有自己的行序） |
| 元数据 | symbol / kind / range / approximate | 追加 `truncated` 与 `pack_sections` |
| 描述 | 只有符号体 | 同文件 docstring、用到的 import、被调/调用方签名（budget 受限，`prompt.py:13`） |

`execute` 层把元数据转成 `result.metadata`（`:612-616`）：

```python
		if output.symbol_meta:
			meta = dict(output.symbol_meta)
			kind = "symbol_pack" if "pack_sections" in meta else "symbol"
			result.metadata = {"read_kind": kind, **meta}
```

即 `read_kind` 由**是否含 `pack_sections`** 推断（不是另一个布尔字段）——一个务实的小技巧。

**⑤ 令牌闸门仍然生效**：由「pack 会把多个区段拼进来」这一事实决定——packed 文本可能比符号体大很多，所以必须过 25,000 令牌闸门。**这是 symbol 路径唯一不能绕过的闸门。**

**⑥ `read_state` 的登记形态不同**（`:523-531`）：

```python
		self._read_state.set(
			full,
			FileStateEntry(
				content=content,
				timestamp=mtime,
				offset=start_line_out if symbol_meta is None else None,
				limit=None if symbol_meta is not None else limit,
			),
		)
```

符号读取时写 **`offset=None, limit=None`**——也就是说它在 `read_state` 里**长得像一次全文件读取**。这与去重判据（`:361-370`）刻意排除 `symbol` 是一致的设计：**符号读取不去重，但它登记的状态会影响其他判断**。★ 一个值得注意的副作用：符号读取会**覆盖**同一路径此前的全文件条目（`set` 同键即替换），而新条目的 `content` 是**全文**（不是切片），所以后续的 `Write`/`Edit` 先读校验能过；但 `offset/limit` 被清成 `None` 意味着「全文件」语义——如果之前的分页读取记录被这样覆盖，后续同区间的去重会因 `existing.offset != offset` 而失效（不命中 stub，退化为真读）。**这是安全的降级方向**（多读不丢信息）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题把 `Read` 的两套区间 API 摆在一起看，核心结论是「**互斥不是限制，而是保护**」：一旦允许同时给，就会出现「offset/limit 说是这里，symbol 说是那里」的不可判定状态。三处校验（互斥、载体限制、pack 依赖 symbol）都属同一类：**拒绝语义冲突的输入，而不是猜测意图**。

另一条线是「**闸门按实际交付量设计**」：尺寸闸门（整文件）被豁免，令牌闸门（实际交付文本）保留——因为 symbol 路径的交付量与文件大小**无关**，却与 pack 的区段数量有关。



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

### XEYO-QA-0195 `diff_preview` 的 80 行上限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | fileio diff 预览 | 截断与省略说明 | 困难 | 场景设计 | `python/tools/fileio/diff_preview.py:9,17-56` |

**面试官提问**
`Write`/`Edit` 成功后会把统一 diff 附在工具结果里。这个 diff 被 `MAX_DIFF_LINES = 80` 截断。请说明：截断发生在哪一侧（`difflib` 输出之前还是之后）？截断后如何标记？哪些 diff 内容**不计入**这 80 行？这个设计把什么风险留给了模型？

**参考答案要点**
**截断发生在 `difflib.unified_diff` 输出之后**——先全量生成，再切片。`fileio/diff_preview.py:17-50`（原文）：

```python
def format_capped_unified_diff(
	old: str,
	new: str,
	*,
	file_path: str,
	max_lines: int = MAX_DIFF_LINES,
) -> str:
	"""返回统一 diff 正文（无围栏），超出上限时截断并附省略说明。"""
	a = old.splitlines(keepends=True)
	b = new.splitlines(keepends=True)
	name = basename(file_path)
	# 旧内容为空 → 创建；为可读性使用 /dev/null 风格头部。
	from_file = "/dev/null" if not old else f"a/{name}"
	to_file = f"b/{name}"
	lines = list(
		difflib.unified_diff(
			a,
			b,
			fromfile=from_file,
			tofile=to_file,
			lineterm="\n",
			n=3,
		)
	)
	if not lines:
		return ""
	# 聊天展示时统一为 \n。
	normed = [ln if ln.endswith("\n") else ln + "\n" for ln in lines]
	if len(normed) <= max_lines:
		return "".join(normed).rstrip("\n")
	kept = normed[:max_lines]
	omitted = len(normed) - max_lines
	kept.append(f"\n… [{omitted} more diff lines omitted]\n")
	return "".join(kept).rstrip("\n")
```

**截断标记**：`… [{omitted} more diff lines omitted]`——**带具体省略行数**，且 `omitted = len(normed) - max_lines` 是**精确值**（不是「约」）。

**三类「不计入」的内容**：

| 内容 | 是否计入 80 行 |
|---|---|
| 代码围栏 ` ```diff ` / ` ``` ` | **不计**——围栏由 `append_diff_fence` 在外层添加（`:53-56`） |
| 工具结果的说明句（`File created successfully at: …` / `+N -M`） | **不计**——同样在围栏之外（`file_write_tool.py:425-436`） |
| 追加的 `Hint: Diagnostics path=…` | **不计** |
| `journal_warning` / `syntax_hint` | **不计**（追加在 diff 之后，`file_write_tool.py:439-442`） |
| diff 自身的 `--- a/x` / `+++ b/x` / `@@` hunk 头 | **计入**（它们本身就是 `unified_diff` 输出的一部分） |

也就是说 80 行是**纯 diff 正文**的预算；整个工具结果 = 说明句 + 围栏 + ≤80 行 diff + 省略说明 + 诊断提示 + 语法提示 + journal 警示。

**两个格式细节**：

1. **创建文件的头部用 `/dev/null`**：`from_file = "/dev/null" if not old else f"a/{name}"`——注意判据是 `not old`（**旧内容为空串**），不是 `os.path.exists`。所以一个「原来就是空文件」的更新会显示成创建样式（对模型而言信息等价，都是「从无到有」）。
2. **换行统一**：`normed = [ln if ln.endswith("\n") else ln + "\n" for ln in lines]` 补足缺失的换行（`difflib` 在 `lineterm="\n"` 下通常都带换行，此处是兜底），最后 `rstrip("\n")` 去掉尾部换行——因为外层要自己包围栏。

**留给模型的风险（三点）**：

1. **截断是「从头部保留 80 行」**，不是「保留最相关的 hunk」。一个大文件的小改动若分布靠后，diff 的前 80 行可能全是 `@@` 上下文与前面的 hunk，**模型看不到自己刚改的那一段**——而省略说明只告诉它「还有 N 行」，不告诉它「你要看的那段被省了」。
2. **80 行是「行数」而非「字符数」**：diff 里的长行（如压缩后的单行 JSON、minified 代码）会让实际字符量远超预期，虽然 `ToolRegistry` 的 `16_000` 字符预算（`Write`/`Edit` 未设 `output_budget`，走默认）会兜住——两者**量纲不同**（行数 vs 字符数），是两条独立的截断机制。
3. **`omitted` 的计数包含 hunk 头与上下文行**，所以「N more diff lines omitted」不等于「N 行代码改动」——模型若把它当改动规模来读会高估。

**深化讲解**（面试官参考，不要求候选人全说）
设计取向是「**用一段可读的局部 diff 换令牌**」，代价（看不清远端改动）由另一条路径补偿：`Write`/`Edit` 的返回同时含精确的 `+N -M` 行数统计（由 `_line_diff_counts` 用 `SequenceMatcher` 独立计算，`file_write_tool.py:68-81`），以及可读的 `Diagnostics path=…` 提示（仅 `.py/.ts/.tsx/.js/.jsx/.mts/.cts`，`file_write_tool.py:509-516`）。也就是说：**diff 负责「看形状」，行数统计负责「看规模」，诊断提示负责「看健康」**——三者互补而非重复。

一处值得注意的**重复计算**：`_line_diff_counts`（用 `SequenceMatcher.get_opcodes`）与 `format_capped_unified_diff`（用 `difflib.unified_diff`）在一次写入里**各做一遍 diff**（前者算行数、后者渲染正文），且 `FileEditTool` 与 `FileWriteTool` **各复制了一份 `_line_diff_counts`**（`file_edit_tool.py:102-115` 与 `file_write_tool.py:68-81`，实现逐字相同）。这是本批可以指出的第二处「双实现」现象（第一处见 0168）。



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

### XEYO-QA-0196 spill 的「预算截断 ≠ 失败」语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | registry 输出预算 | 预览替换与元数据 | 困难 | 场景设计 | `python/tools/tool_registry.py:82-88,202-234` |

**面试官提问**
当一个工具结果超过预算时，`_apply_output_budget` 会做「原文落盘 + 预览替换」。请说明预览的**精确构成**、元数据的**键值**、以及为什么要把 `is_error` 显式设为 `False`。另请指出「`full output`」这个名字在**什么情况下是不准确的**。

**参考答案要点**
`tool_registry.py:202-234`（原文，从预算通过点开始）：

```python
		if budget <= 0 or len(result.content) <= budget:
			return result
		try:
			from tools.spill import save_text

			ref = save_text(session_id or "session", result.content)
		except Exception:  # noqa: BLE001 — spill 失败：原样返回，不 isError
			return result
		head = result.content[: self.PREVIEW_HEAD]
		tail = result.content[-self.PREVIEW_TAIL :]
		preview = (
			f"{head}\n\n…[middle truncated by output budget]…\n\n{tail}\n\n"
			f"[output truncated: 预算截断（非错误），原始 {len(result.content)} 字符；"
			f"full output: {ref.path}]"
		)
		default_audit_log().record(
			"tool.spill",
			session_id=session_id,
			tool_name=tool.name,
			path=ref.path,
			original_chars=len(result.content),
			spill_bytes=ref.bytes,
		)
		metadata = dict(result.metadata or {})
		metadata.update(
			{
				"spilled": True,
				"spill_path": ref.path,
				"original_chars": len(result.content),
				"truncation": "output_budget",
			}
		)
		return ToolResult(content=preview, is_error=False, metadata=metadata)
```

**预览的精确构成**（四段）：

```
<head = 前 6000 字符>
\n\n…[middle truncated by output budget]…\n\n
<tail = 后 2000 字符>
\n\n[output truncated: 预算截断（非错误），原始 <N> 字符；full output: <路径>]
```

常量来自类属性（`:82-88`）：

```python
	#: T1：默认输出预算（字符）；per-tool 覆盖见 ToolMeta.output_budget。
	DEFAULT_OUTPUT_BUDGET = 16_000
	#: 预览头/尾长度（预算截断后模型可见部分）。
	PREVIEW_HEAD = 6_000
	PREVIEW_TAIL = 2_000
```

注意 `head + tail = 8000 < 16000`——预览是**真截断**，不是「预算内尽量填」。

**元数据四键**：`spilled=True`、`spill_path=<路径>`、`original_chars=<原始字符数>`、`truncation="output_budget"`。第四键的值是**固定字符串**，用途是把「预算截断」与「工具失败」在机器可读层面分开——`is_error` 是布尔，不足以区分「失败」与「被截断」。

**为什么要显式写 `is_error=False`**：因为 `ToolResult` 的构造在别处可能默认或被推导为真（尤其当结果来自失败的中间态时）。这里显式声明是**语义断言**：这次调用**成功了**，只是投影被裁剪。配合预览里的中文括注「预算截断（非错误）」，**模型侧与代码侧各有一份同样的声明**——模型不该把截断误判为失败去重试，程序不该把它计入错误率。

**「`full output`」在何时不准确**：spill 落盘的是 `result.content`，也就是**工具返回的、已经过工具自身约束的内容**——不是「工具的真实原始输出」。至少两类情况名不副实：

| 情况 | 工具 | 现象 |
|---|---|---|
| 工具自带截断 | `Read`（`output_budget=0`，不走 registry 预算） | `Read` 无 `limit` 时只返回 2,000 行（**静默**），`spill` 里也不会有第 2,001 行起的任何东西 |
| 工具自带 head_limit | `Grep`（走 16,000 默认预算） | `files_with_matches` 默认 `head_limit=250`，`GrepOutput.filenames` 本身只有 250 条；若结果超 16,000 字符被 spill，落盘的也只是那 250 条的文本，**不是全库命中集** |
| 工具自带分页/spill | `Glob` | `Glob` 自己会把**完整列表**写进 `tools/spill.py`（`glob_tool.py:660-668`），并在结果里追加 `Complete match list (N paths) saved to: <path>`——这一条的措辞是准确的（它明确写「complete match list」） |

所以「`full output`」应当读作「**本次工具结果的完整文本**」。这与审计报告 `TOOL-11` 的指控一致（`docs/全项目BUG排查-20260910.md:143`：「registry 预算 spill 包的是『已截断内容』，却标称 full output」），本批已按当前行号复核——`tool_registry.py:204-234` 的确只 spill `result.content`，而 `result.content` 是工具 `execute` 的返回值。

**对照 `Glob` 自己的 spill 写法**（`glob_tool.py:991-996`）：

```python
		if output.spill_path and output.total_matches:
			text += (
				f"\n\nComplete match list ({output.total_matches} paths) saved to: "
				f"{output.spill_path} — use Read to open."
			)
```

它同时给出**数量**（`total_matches`）与「use Read to open」的动作指引，且用词是 `Complete match list`（因为它确实落的是完整排序列表，`perform_glob` 的 `save_text(session_id, "\n".join(all_files))`）——**同一项目里两种 spill 措辞的精度不同**，这本身是一条可改进项。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的推理终点是「**截断链条上每一层的措辞都要对它自己那一层的真实范围负责**」。链条是：

```
工具内部约束（Read 2000 行 / Grep head_limit / Glob 分页）
        ↓  result.content
registry 预算（16,000 字符）→ spill 文件 + 预览
        ↓  模型可见投影
```

`full output` 站在第二层描述第一条链路，所以只对「registry 之前的内容」为真。正确措辞可以是 `full tool result: <path>`，或者像 `Glob` 那样带上数量——**这不需要改架构，只需改文案**。

另有两条实现细节值得记：①`session_id or "session"`——`session_id` 缺失时落到字面量 `"session"` 命名空间（所有无会话 id 的 spill 会混在同一个目录，靠文件名时间戳 + uuid 区分）；②`save_text` **抛异常时原样返回**（`:208-209`）——宁可超预算，不可假证据（与 `spill.py:11-12` 的模块注释同调）。



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
### XEYO-QA-0197 【超压·故障排查】Write 把 CRLF 文件整份改写成 LF

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Write 行尾处置 | 行尾风格的静默改写 | 超压 | 故障排查 | `python/tools/file_write_tool/file_write_tool.py:317-321,347-372` + `python/tools/fileio/text.py:54-76` |

**面试官提问**
**故障报告**：一个 Windows 仓库里的 `.ps1` / `.bat` 文件（CRLF 行尾）被 agent 用 `Write` 覆盖后，`git diff` 显示**整个文件每一行都变了**，但语义改动只有一行。同一仓库里用 `Edit` 改的文件**没有**这个问题。请给出根因、证据行号、复现步骤、影响面，并说明为什么 `Edit` 不受影响。

**参考答案要点**
**根因：`Write` 在调用 `read_text_file` 时拿到了原文件的 `_endings`，却把它丢弃，落盘时硬编码 `line_endings="LF"`。**

**证据链（四处，缺一不可）**：

**① 读到就丢**（`file_write_tool.py:317-321`）：

```python
		if existed:
			try:
				old_content, _endings, encoding = read_text_file(full)
			except OSError:
				old_content = None
```

下划线前缀 `_endings` 是明显的「有意忽略」标记——而**同一行的 `encoding` 被保留了**，说明这不是「不需要这个信息」，而是**只保留了编码、没保留行尾**。这是不对称处置的直接证据。

**② `read_text_file` 明确返回了三个值**（`fileio/text.py:31-51`）：

```python
def read_text_file(path: str) -> tuple[str, LineEnding, str]:
	"""
	读取文本文件。
	返回 (normalized_LF_content, original_line_endings, encoding_name)。
	"""
```

**③ 落盘硬编码 LF**（`file_write_tool.py:372`）：

```python
		journal_warning = self._persist(full, content, encoding=encoding, line_endings="LF")
```

注意 `encoding=encoding`（**用了探测结果**）与 `line_endings="LF"`（**没用探测结果**）出现在同一个调用里——这行是本故障的**唯一改写点**。

**④ LF 是「不还原」**（`fileio/text.py:62-64`）：

```python
	to_write = normalize_newlines(content)
	if line_endings == "CRLF":
		to_write = "\r\n".join(to_write.split("\n"))
```

`line_endings == "LF"` 时不追加 `\r`，内容里本来也已被 `normalize_newlines` 把所有 `\r\n` 变成了 `\n`（`:349` 调用过一次、`:62` 又归一化一次）——于是 `\r` **全部消失**。

**为什么 `Edit` 不受影响**：`Edit` 走了完整的往返（`file_edit_tool.py:434,519-521`）：

```python
		self._last_endings = endings          # validate_input 里保存探测结果
		...
		journal_warning = self._persist(
			full, updated, encoding=encoding, line_endings=endings  # type: ignore[arg-type]
		)
```

它把探测到的 `endings` 一路传到 `_persist`，并且 `_persist` 的 store 分支也按 `line_endings` 还原（`file_edit_tool.py:186-192`）。所以「`Write` 改 CRLF 文件全量变、`Edit` 改同文件只变目标行」——**两个工具的差异本身就是最有力的定位线索**。

**复现步骤**（三步，可脚本化）：

1. 用 CRLF 写一个 6 行文件（例如 `f.txt`，内容 `a\r\nb\r\nc\r\nd\r\ne\r\nf\r\n`），`git add` 并 `git commit`；
2. agent 侧：`Read(f.txt)` → `Write(f.txt, content="a\nb\nc\nd\ne\nF\n")`（只改最后一行）；
3. 观察：`git diff --stat` 显示 `6 insertions(+), 6 deletions(-)`（**全文件**）；用字节级检查（如 `Format-Hex` / `xxd`）确认文件里已无 `0D 0A`。
   - **对照**：改用 `Edit(old_string="f", new_string="F")`，`git diff` 只显示 1 行变化，且行尾仍是 `0D 0A`。

**影响面**：

| 面 | 影响 |
|---|---|
| `git diff` 可读性 | 语义改动一行 → diff 全文件；评审与 blame 失效 |
| `git blame` / 历史 | 行级归属被打散，一次 `Write` 会「认领」整个文件 |
| 工具链 | 依赖 CRLF 的脚本（`.bat`、`.ps1` 的部分场景、批处理）可能行为改变；某些语言/工具的 `\r` 敏感检测会报警 |
| 影响范围 | **仅 `Write`**；`Edit` 正确；`NotebookEdit` 走另一条路径（本批未验证） |
| 触发条件 | 目标文件原本含 CRLF，且操作是 `Write`（**与改多少行无关**，改 1 行也全量改写） |

**与已知缺陷基线的一致性**：审计报告 `TOOL-02`（`docs/全项目BUG排查-20260910.md:134`）记录了同一现象，其给出的锚点是 `file_write_tool.py:317-319,372`——本批逐行复核后确认：**`:317-319` 是 `_endings` 丢弃处（`read_text_file` 调用在第 319 行），`:372` 是硬编码 `line_endings="LF"` 处**。两个锚点与实测一致，未漂移。

**修复方向（不含源码改动，仅指方向）**：把 `_endings` 改名保留并在 `_persist` 传入（最小改动、与 `Edit` 对齐）；注意需同时确认 store 分支（`file_write_tool.py:152-158`）也按该值还原——它已经支持 `line_endings` 参数，所以改造面是**一行改名 + 一处传参**。另一个可选方向是「`Write` 保留原行尾，新建文件用 LF」，用 `existed` 与探测结果共同决定。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的定位逻辑值得提炼成通用方法：**在「同场景两个工具行为不同」时，先找两者的前置信息差异，而不是先读实现细节**。此处 `Edit` 保留了 `endings`、`Write` 丢弃了它——一行下划线前缀就是全部答案。

第二个可提炼点是「**不对称处置是最强的线索**」：同一行代码里 `encoding` 被保留、`_endings` 被丢弃，说明作者**知道这两个信息都存在**，只是漏了一路。这比「实现了但写错」更容易定位，也更值得在代码评审里被当作气味（smell）来抓。



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

### XEYO-QA-0198 【超压·故障排查】Grep count 在分页下的「总数」少报

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | Grep count 统计口径 | 分页后的求和 | 超压 | 故障排查 | `python/tools/grep_tool/grep_tool.py:139-156,625-653,793-806` |

**面试官提问**
**故障报告**：对一个含 400 个匹配、分布在 60 个文件里的模式执行 `Grep(pattern=…, output_mode="count", head_limit=10)`，工具结果末尾声称 `Found 37 total occurrences across 10 files.`。但把同一模式换成 `output_mode="files_with_matches"` 会看到远多于 10 个文件。请给出根因、证据行号、最小复现、以及这个缺陷对**模型决策**的实际危害。

**参考答案要点**
**根因：`count` 模式的 `total_matches` 是对「已分页的切片」求和，而 `map_tool_result_to_content` 把这个局部和包装成 `Found N total`。**

**证据链（三处形成闭环）**：

**① 先分页、后求和**（`grep_tool.py:625-653`）：

```python
		if mode == "count":
			# 确定序：按路径排序后再分页（count 模式输出本身无序）。
			results.sort(key=_count_line_sort_key)
			limited, applied_limit = apply_head_limit(
				results, input_data.head_limit, offset
			)
			final_lines = [
				_relativize_count_line(line, self._cwd) for line in limited
			]
			total_matches = 0
			file_count = 0
			for line in final_lines:            # ← 只对分页后的 final_lines 求和
				colon = line.rfind(":")
				if colon <= 0:
					continue
				try:
					total_matches += int(line[colon + 1 :])
					file_count += 1
				except ValueError:
					continue
```

注意求和循环遍历的是 **`final_lines`（切片后）**，而不是 `results`（全量）。`GrepOutput.num_matches = total_matches`、`num_files = file_count`。

**② 分页确实是截断**（`grep_tool.py:139-156`）：

```python
def apply_head_limit(
	items: list[str],
	limit: int | None,
	offset: int = 0,
) -> tuple[list[str], int | None]:
	"""
	分页截断。limit=0 表示不限制；未指定则用 DEFAULT_HEAD_LIMIT。
	仅在真正发生截断时返回 applied_limit，便于模型分页。
	"""
	safe_offset = max(0, offset or 0)
	if limit == 0:
		return items[safe_offset:], None
	effective = DEFAULT_HEAD_LIMIT if limit is None else limit
	if effective < 0:
		effective = DEFAULT_HEAD_LIMIT
	sliced = items[safe_offset : safe_offset + effective]
	was_truncated = len(items) - safe_offset > effective
	return sliced, (effective if was_truncated else None)
```

`head_limit=10` → `sliced = results[0:10]`，`applied_limit = 10`（因为确实截断了）。

**③ 措辞把它说成全局总数**（`grep_tool.py:793-806`）：

```python
		if output.mode == "count":
			raw = output.content or "No matches found"
			matches = output.num_matches or 0
			files = output.num_files or 0
			if matches == 0:
				raw = raw + _NO_MATCH_TIP
			summary = (
				f"\n\nFound {matches} total "
				f"{'occurrence' if matches == 1 else 'occurrences'} across "
				f"{files} {_plural(files, 'file')}."
			)
			if limit_info:
				summary = summary[:-1] + f" with pagination = {limit_info}"
			return raw + summary
```

措辞是 `Found {matches} total occurrences across {files} files`——**`total` 一词把局部和宣称为全局**。而 `limit_info`（`limit: 10`）被贴在句尾作为**附加说明**，不改变「total」的断言。

对照 `files_with_matches` 模式的措辞（`:817-827`）：

```python
		# files_with_matches 模式
		if output.num_files == 0:
			return "No files found" + _NO_MATCH_TIP
		header = f"Found {output.num_files} {_plural(output.num_files, 'file')}"
		if limit_info:
			header = f"{header} {limit_info}"
		body = header + "\n" + "\n".join(output.filenames)
```

它写 `Found {num_files} files limit: 10`——**没有 `total`**。也就是说 `files_with_matches` 口径正确（它只报告返回条数并标注 limit），**`count` 模式多了一个 `total` 词**。这个差异正是缺陷的**边界**：同一份 `apply_head_limit` 结果，两个渲染函数的措辞精度不同。

**最小复现**：

1. 建 `tmp/`，写 60 个小文件，每个含 7 行同一标记 `bench_marker`（共 420 处；或用 1 个文件每行一处，效果一样——只要**文件数**超过 `head_limit`）；
2. `Grep(pattern="bench_marker", path=tmp, output_mode="count", head_limit=10)`；
3. 观察：`num_matches` ≈ 70（10 个文件 × 7 处），摘要为 `Found 70 total occurrences across 10 files. with pagination = limit: 10`；
4. 对照：同参数换 `output_mode="files_with_matches"`，`num_files=250` 被截断为 `limit: 250`…（若文件数不足 250 则显示全部 60）——**两个模式的「文件数」结论不一致**（10 vs 60），这就是模型能察觉的矛盾。

**实际危害（三层）**：

| 层 | 危害 |
|---|---|
| 事实误导 | 模型把 `37 total` 当作「全仓共有 37 处」——**用于判断「改动是否彻底」「模式是否普遍」时直接得错** |
| 分页契约失效 | 正确的分页语义是「每页给出本页条数 + 总数（或明确未知）」；现在总数是假的，模型无法判断「翻页翻完没」 |
| 与 `symbols` 模式的不一致 | `symbols` 模式的 `num_matches` 也是**分页前**累计的（`grep_tool.py:754-761` 的 `count` 在分页前统计）——即 `symbols` 口径是**对的**，只有 `count` 错了。同一工具三种模式三种口径 |

**注**：`symbols` 模式的口径在 `_call_symbols` 里正确实现（`count` 变量在 `apply_head_limit` **之前**累加，`:699-758`），`num_matches=count`（`:775`）。这进一步证明 `count` 模式的写法是**实现疏忽**而非有意设计——因为同一文件中已有正确范本。

**修复方向（仅指方向）**：在分页**之前**对全量 `results` 求和得到 `total_matches`/`total_files`，分页后另行统计 `page_matches`/`page_files`；渲染成 `Found {total} total occurrences across {total_files} files (showing {page_files} files with pagination = limit: 10)`。或者**最小改动**：把 `total` 一词删掉，改为 `Found {matches} occurrences in the {files} file(s) returned`——**先让措辞与事实对齐**，口径修复可分步进行。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的通用教训是「**统计量必须与它的采集范围同名**」。这里的错误非常典型：变量名 `total_matches` 暗示全局，采集范围却是分页切片——**命名与范围不一致**最终导致渲染层说错话。识别方法也很直接：**看求和循环遍历的是 `results` 还是 `final_lines`**（第 ② 步与第 ③ 步的先后顺序是全部答案）。

第二个可提炼点：**同一函数内存在正确范本时，错误实现的可信度判定**。`_call_symbols` 在分页前累计、`count` 在分页后求和——两处并存说明后者是疏忽；如果只有一处实现，就需要从「分页语义」本身论证它错。



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

### XEYO-QA-0199 【超压·场景分析】文件工具族的三方缓存总账与写后失效面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | 缓存一致性总账 | 三方缓存的失效责任 | 超压 | 场景设计 | `python/tools/glob_tool/glob_tool.py:48-52,88-112` + `python/tools/fileio/content_index.py:28-33,134-141` + `python/tools/fileio/read_state.py:95-108,113-123` |

**面试官提问**
文件工具族里有**三份独立的缓存/账本**：Glob 的查询缓存、`content_index` 的 trigram 索引、`ReadFileState` 的读态账本。请列出三者的键、TTL/容量、**写后失效责任**，然后回答：若外部编辑器（不经 XEYO）修改了工作区文件，这三份各自会出现什么后果？哪一份的后果最严重？并指出当前实现里**唯一没有写后失效机制**的一份及其失效形态。

**参考答案要点**
**三方对照表**：

| 缓存 | 键 | TTL / 容量 | 写后失效责任 |
|---|---|---|---|
| Glob 查询缓存 | 三类：`("files", pattern, root, head_limit, off)` / `("summary", summary_root)` / `("suggestion", pattern, root, cwd)` | TTL **60s**；`_GLOB_CACHE_MAX = 128`，LRU（`glob_tool.py:48-52`） | `clear_glob_cache()` **全清**；调用点：`file_write_tool._invalidate_glob_cache`（`:34-43`）、`file_edit_tool._invalidate_glob_cache`（`:44-52`）、Bash 写命令分类器（`test_glob_optimize.py:495-517` 覆盖其正反样例） |
| content_index trigram 索引 | `root` 单键（`_cache: root -> (expires, ContentIndex|None)`） | TTL **30s**；`_MAX_CACHE_ROOTS = 8`（`content_index.py:28-39`） | `clear_content_index()` **全清**（`:134-141`），注释：「写突变后失效，与 glob 缓存同轨」 |
| ReadFileState 读态账本 | `normcase(normpath(abspath))` | **无 TTL**；默认 128 条 LRU（`read_state.py:46-50`） | **无写后失效**——`set_written` 只在**本工具自己落盘后**覆盖单条（`read_state.py:62-86`） |

**外部编辑器（不经 XEYO）修改文件时的三方后果**：

| 缓存 | 后果 | 严重度 |
|---|---|---|
| Glob 查询缓存 | 60s 内 `Glob` 可能返回**过时列表**：新文件找不到、被删文件仍出现。**只影响文件名的发现，不影响内容正确性** | 低（可见性延迟） |
| content_index | 30s 内候选集可能与磁盘不一致。★ 但注意两个方向不同：**新增**文件不在候选集 → `files_with_matches` **漏报**（因为 `rg` 只在候选集内精确验证，`grep_tool.py:596-601`）；**删除**文件仍在候选集 → `rg` 会因文件不存在而自然过滤，**不漏报**。所以危险方向是「索引变旧 + 新文件命中」 | 中高（漏报） |
| ReadFileState | **无失效机制**，条目一直留到 LRU 淘汰。此时 `mtime > timestamp` 的陈旧检测**会**触发（外部改动必然推进 mtime），所以能拦住大部分情形——**除了同毫秒改动**（见 0187） | 高（数据丢失路径） |

**后果最严重的是 `ReadFileState`**，理由不是「它没有 TTL」，而是**它的失效形态是静默的数据回退**：外部改动的文件在同毫秒内被 `Read` 记为「已读」，随后 `Write` 用它做基底整文件覆盖（或 `Edit` 以陈旧内容计算新内容并写回），**外部改动被抹掉且没有任何提示**。而 Glob 缓存与 content_index 的失效只产生「看不见 / 少报」的**信息层**缺陷，不会破坏磁盘内容。

**当前唯一没有写后失效机制的一份**：`ReadFileState`。它的失效形态有两种，必须分开看：

| 形态 | 触发 | 现状 |
|---|---|---|
| **本工具写后**（`Write`/`Edit` 成功了） | 落盘后 `set_written` 覆盖该路径条目，并用**落盘后重新取**的 `get_mtime_ms(full)` 作为时间戳（`file_write_tool.py:374-381`；`file_edit_tool.py:523-530`） | ✅ 正确——写后条目与磁盘同源 |
| **外部写后** | 无主动失效 | ⚠️ 靠 `mtime > timestamp` 的**被动**检测（`file_write_tool.py:285,325-329`；`file_edit_tool.py:389-404,479-491`）兜住，同毫秒失效 |

★ 一个必须点出的**交叉缺口**：Glob 的写后失效**不调用** `clear_content_index()`。也就是说 `content_index` 的清空责任只落在**它自己的调用点**上（grep 路径），而 `Write`/`Edit` 的 `_invalidate_glob_cache` 只管 Glob 一家。这造成一个**时序不对称**：本进程 `Write` 一个新文件后，`Glob` 立刻可见（缓存已清），但 `Grep files_with_matches` 的候选集**仍可能是 30s 前的索引**——如果新文件恰好没被旧索引收录，`Grep` 会**漏报**该文件里的匹配。两份缓存的 TTL 也不同（60s vs 30s），进一步放大了窗口差异。**本批将此列为待确认项**（需确认是否存在第三个统一清理点，例如 `tool_registry` 或写路径的更外围）。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的价值在于**把「缓存一致性」从单点问题提升为责任分配问题**。三份缓存的失效策略其实各自合理，问题出在**责任边界没有被统一收敛**：

- Glob 的三类键**全清**——简单、安全、成本可忽略（0192 已论证）；
- content_index 的 `None` 也入缓存——代价是坏状态粘住 TTL（0189 已论证）；
- ReadFileState 无 TTL 且无外部失效——**它的正确性完全押在 mtime 被动检测上**，而 mtime 检测有已知的精度漏洞。

因此正确的改进方向不是「再加一份缓存」，而是**把「工作区被写入」这件事收敛成一个事件**（本批观察：`workspace_revision` 已经承担了「工作区变了吗」的检测职责，见 B03-0149；`process_ledger` 承担「谁还在写」的职责）。**把三方失效挂到同一个事件上**，才是结构性解；逐个打补丁会持续留下类似「Glob 清了、content_index 没清」的缺口。

另一个观察：三份缓存的**量纲完全不同**——Glob 缓存的键含 `pattern`（内容寻址）、content_index 的键是 `root`（位置寻址）、ReadFileState 的键是**绝对路径**（实体寻址）。失效策略必须匹配键的粒度：内容寻址的缓存只能全清（无法按内容反推），位置寻址的可以按 root 清，实体寻址的本可以按路径精确清——**而恰恰是唯一可精确失效的那一份没有做失效**。这个「能力与选择的反差」是本题最值得记住的一点。



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

### XEYO-QA-0200 【超压·安全测试】非对称路径校验：Read 有门而 offload_read 无门

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| tools 工具集 | 读路径权限对称性 | 隐藏工具的路径校验缺失 | 超压 | 安全拷问 | `python/tools/offload_read_tool.py:8-62` + `python/tools/file_read_tool/file_read_tool.py:346-347,585-586` |

**面试官提问**
`Read` 与 `offload_read` 都是「读文件」的工具：前者走 `permissions.filesystem` 路径狱 + 设备文件/扩展名/尺寸/令牌闸门；后者只有 `is_file()` 与 `read_text()`。请指出后者的**完整校验面**、为什么它仍然「可用」、它的实际风险等级如何评估、以及**最小修复**是什么。

**参考答案要点**
**`offload_read.execute` 的全部校验代码**（`offload_read_tool.py:46-62`，逐行完整）：

```python
	async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
		abort.raise_if_aborted()
		p = Path(str((input or {}).get("path") or "")).expanduser()
		if not p.is_file():
			return ToolResult(content=f"(offload 文件不存在: {p})", is_error=True)
		try:
			text = p.read_text(encoding="utf-8")
		except OSError as e:
			return ToolResult(content=f"(读取失败: {e})", is_error=True)
		start = int(input.get("start") or 1)
		end = int(input.get("end") or 0) or None
		lines = text.split("\n")
		if end:
			body = "\n".join(lines[max(0, start - 1):end])
		else:
			body = "\n".join(lines[max(0, start - 1):])
		return ToolResult(content=body)
```

**校验面清单（与 `Read` 逐项对照）**：

| 校验 | `Read` | `offload_read` |
|---|---|---|
| `check_permissions` → `permissions.filesystem` 路径狱 | ✅ `:346-347`，`execute` 里调用（`:585-586`） | ❌ **完全没有** |
| 密钥文件 DENY / 危险文件 ASK | ✅（经 `filesystem`） | ❌ |
| 设备文件阻断清单 | ✅（`BLOCKED_DEVICE_PATHS` + `/proc` 规则） | ❌ |
| 扩展名三档（图片/二进制/文本） | ✅ | ❌（任意扩展名都读，二进制按 UTF-8 + `errors` 默认**严格**解码） |
| 尺寸闸门 0.25 MiB | ✅ | ❌ |
| 令牌闸门 25,000 | ✅ | ❌（**整文件读入内存且整份返回**） |
| 目录/不存在检查 | ✅（`IsADirectoryError` / `FileNotFoundError`） | ⚠️ 仅 `is_file()`（把「目录」与「不存在」合并成同一句错误） |
| 工作区边界 | ✅ | ❌ |
| `abort` 检查 | ✅ 多处 | ✅ 一次（`:47`） |

**为什么它仍然「可用」（为什么这不是立即崩溃级漏洞）**：三层缓冲。

1. **`exposure=hidden`**（`meta.py:76` 的 `offload_read` 条目 + `tool_registry.schemas()` 的 `exposure_of` 过滤，`tool_registry.py:110-120`）：它**不进 `tools` 数组**，所以模型不会在正常工具列表里看到它。触发需要**幻觉调用**或**被注入内容诱导**（审计报告的原文判断）。
2. **`registry.run` 的通用权限门**：模块 docstring 明确写「注册但保留可用性（幻觉/按需调用仍经 `run()` 权限三态，fail-safe）」（`offload_read_tool.py:4-5`）。也就是说 `PolicyDecision` 层会按 **`offload_read` 这个工具名**做一次策略裁决（例如「未授权工具名 → ASK/DENY」）。
3. **没有独立的危险语义**：它只做「读文本并返回行区间」，没有写、没有执行、没有网络。

**风险等级的诚实评估**（三点必须都说）：

- **不是**「任意文件读取漏洞」的立即形态——因为 `run()` 的通用门与 `exposure=hidden` 都不为零；
- **但是**「工具面不对称」这一**结构性**问题：当策略层对**这个工具名**给出 `allow`（例如用户在使用过程中批准过一次、或策略配置宽松），`offload_read` 就变成了一个**绕过 `Read` 全部内容审查**的读通道——包括**工作区外的文件**（`expanduser` 后可以是任意绝对路径）与**密钥文件**（`Read` 有 `DANGEROUS_FILES` DENY，它没有）。攻击面是「提示注入 + 一次已批准的隐藏工具」，这在「模型可能被工作区文件内容诱导」的威胁模型下不属假想。
- **额外的可用性风险**：无尺寸/令牌上限 = **一次调用可把整个大文件灌进上下文**（`Read` 的两道闸门在此完全缺席）。这不只是安全题——它是**上下文预算的敞口**，与 0163（spill 纪律）、0196（预算机制）属于同一治理面而缺乏一致约束。

**与缺陷基线的一致性**：审计报告 `TOOL-01`（`docs/全项目BUG排查-20260910.md:63,133`）给出锚点 `offload_read_tool.py:46-62` 并标注「**已复核** high」，备注写「该工具 `exposure=hidden`（不进 schema），故触发需模型『幻觉调用』或被注入内容诱导；但 `execute()` 内确实无 `check_permissions` 与路径狱，与 `Read` 行为不对等」。本批**逐行复核一致**（`:46-62` 确为 `execute` 全体，且无任何 `permissions` 引用）。

**最小修复（一行级，含 import）**：

```python
		# 与 Read 对齐：读前走同一路径狱/密钥 DENY 判定
		from permissions import filesystem
		if not filesystem.check_read_permission_for_tool(self, input, None):
			return ToolResult(content="permission denied", is_error=True)
```

要点三条：①复用 `Read` 的**同一函数**（`file_read_tool.py:346-347` 用的就是这个），保证语义不分叉；②放在 `is_file()` **之前**——否则「文件不存在」的错误信息本身就会成为一个**路径存在性探测 oracle**（`Read` 的顺序也是先权限后存在性：`execute` 里 `check_permissions` 在 `call` 之前，`:585-598`）；③`is_file()` 之后还应补**尺寸上限**（可复用 `MAX_SIZE_BYTES`）——这是与安全同源的**上下文预算**修复。

**深化讲解**（面试官参考，不要求候选人全说）
这道题的核心不是「发现一个洞」，而是**用「同能力域内的对称性」作为审计棱镜**。同一能力域（读文件）里的两个工具，一个层层设防、一个全裸——这种落差本身就是**缺陷存在的证明**：要么 `Read` 的防护多余，要么 `offload_read` 缺失。而 `Read` 的防护有明确的威胁模型（设备文件无限输出、密钥泄露、上下文预算），所以答案只能是后者。

第二个可提炼点是**「hidden 不等于安全」**：`exposure=hidden` 是**注意力层**的收敛（不进 tools 数组、不占 schema 预算），不是**执行层**的限制。本项目的设计立场在 AGENTS.md 里写得很清楚——「**限制只在执行层**」、引擎的限制「只在执行层表达」。而 `offload_read` 恰好是「用了注意力层的收敛代替了执行层的限制」，这正是理念与实现之间的一处偏差。这一点比单个洞更有价值，因为**同类偏差可能存在于其他 hidden 工具上**（本项目 `meta.py` 中 `exposure="hidden"` 的条目不止一个）。



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

## 批次自检表（B04）

| 项 | 结果 |
|---|---|
| 题号连续性 | XEYO-QA-0151 – XEYO-QA-0200，**无跳号无重号**（`grep -c "^### XEYO-QA-"` = 50） |
| 难度配比实测 | 简单 **16**（0151–0166）/ 中等 **18**（0167–0184）/ 困难 **12**（0185–0196）/ 超压 **4**（0197–0200）= **50**。与矩阵 B04 规划（16/18/13/3）差 1 题：`0196` 由「困难」上调为「超压」，详见下方「难度配比更正说明」 |
| 题型分布 | 单选 **9** / 多选 **3** / 简答 **19** / 场景分析 **10** / 代码阅读 **5** / 故障排查 **3**（0185、0197、0198）/ 安全测试 **1**（0200）= **50**（总览表与字段表两处口径一致，均按「每表各行 3/4 列」机器统计）。无「接口测试」「性能压测」题型：本批无可测端点，压测面已由 0199 的缓存总账覆盖 |
| 覆盖子模块 | `file_read_tool`（主文件 / `prompt` / `vision_media` 相关面）/ `file_write_tool` / `file_edit_tool` / `glob_tool` / `grep_tool` / `fileio`（`text` `read_state` `paths` `conflict` `diff_preview` `syntax_check` `excludes` `rg_subprocess` `content_index` `content_index_cache_shadow` `__init__`）/ `offload_read_tool` / `spill` / `spill_shadow`（相关面）/ `tools/meta`（文件工具条目）/ `tools/tool_registry`（预算段）——共 **20 个文件** |
| 事实基线核对 | 全部 50 题的「来源依据」均指向本批**实际打开读过**的文件与行号；本批对 `glob_tool.py`（1093 行）、`grep_tool.py`（938 行）、`file_read_tool.py`（687 行）三处盲读难保证的大文件，采用了「**先 Grep 定位段落 → 再 Read 带 offset/limit 精读**」的方式，并在写入题面前复核了关键锚点（`:656-658`、`:883`、`:625-653`、`:793-806`、`:474-475`、`:317-321,372`、`:46-62`） |
| 缺陷基线行号复核 | `docs/全项目BUG排查-20260910.md` 中与本批相关的 **8 条**（TOOL-01/02/04/05/07/08/09/10/11）已逐条对当前源码复核：**行号基本一致**（`TOOL-02: 317-319,372` ✅、`TOOL-08: 474-475` ✅、`TOOL-01: 46-62` ✅、`TOOL-05: 634-644` ✅、`TOOL-11: 204-234` ✅）；`TOOL-04` 的第二个锚点文档写作 `656-658`，实测 `656-658` 是 `perform_glob` 的 `reverse/total/sliced` 三行（**相关但非重试判据**），重试判据在 **`:883`**——已在 0185 中按实测行号出题并说明差异 |
| 重复性检查 | ① 与 B03 的分界已守：`write_store`/`workspace_lock`/`workspace_revision` 只在「文件工具如何接入」的角度出现（0168/0179/0187/0199），未重复 B03 的分片锁、租约、WAL 主题；② 与 B02 无重叠（未涉及 query_loop/调度）；③ 批内 `0160`/`0173`/`0182` 三题同属 `ReadFileState`，但分别聚焦**容量配置**、**get 副作用**、**淘汰演算**，答案不重复；④ `0168`（Write 双路径等价）与 `0193`（侧挂模块等价）角度不同（前者是同函数内双分支，后者是跨模块猴补丁）；⑤ `0183`（content 排序键）与 `0198`（count 求和口径）同属 Grep 但缺陷面不同 |
| 待确认条目（本批显式标注） | **7 处**：① 0169 `abspath` vs `realpath`（symlink 场景是否需要统一）；② 0173 `snapshot_meta` 不带 `content_known` 而 `load_meta` 需自行推断，是否存在其它 sidecar 写入点；③ 0187 把判据改成 `mtime != timestamp` 的改进假设是否成立（需实测误报代价）；④ 0192 缓存键不含 `case_insensitive` 标记——若该参数将来提升为显式入参需同步扩键；⑤ 0192 第 4 项「`Glob`/`Write`/`Edit` 的 `_invalidate_glob_cache` 是否应同时调 `clear_content_index()`」——本批确认 Glog 侧未调用，是否存在第三处统一清理点待查；⑥ 0193 `enabled()` 默认值口径（docstring 写「默认 0=关」，`enabled()` 注释写「升格后默认开」，实际由 `sidecar.policy.side_enabled` 决定）；⑦ 0157 `is_partial_view` 在 `Read` 主路径未被置位——需确认置位入口（WorkingSnapshot 侧） |
| 边界遵守 | 未涉及 B05（`bash_tool/` 12 件、破坏性守卫、容器路由、`truncate`）、未涉及 B07（权限三态裁决、`bash_policy`、`presets`）、未涉及 B11（rewind 快照/checkpoint）、未涉及 B15（`codeindex.symbols` 符号抽取算法——0194 只讲 `Read` 侧的调用与元数据面） |
| 未覆盖但已计划 | `file_read_tool/vision_media.py` 的图片压缩管线（`compress_image_for_llm` 的三档 quality、`read_pdf_for_llm` 的 pymupdf 双开）与 `Read` 的 vision 分支只做了**清单级**引用（0152/0194），未出细节题 → 如需可作补批；`spill_shadow.py`（tail 建议猴补丁）与 `content_index_fp_shadow.py`（B3 目录指纹）未出题 → 归 B03 侧挂族补批；`fileio/excludes.py` 的 `DANGEROUS_SUFFIXES` 具体清单未展开（属 B07 权限层） |
| 难度配比更正说明 | 矩阵 B04 规划为 16/18/13/3。本批实际产出 16/18/**12**/**4**：`0196` 由「困难」上调为**超压**（它与 0197/0198 构成「输出投影的措辞与事实范围」三连，独立超压更贴切），因此超压由 3 增为 4。若必须严格对齐矩阵，可把 `0196` 标为困难——**题目内容不变**，仅难度标签归属差异，已在此显式记录以免统计口径混淆 |





---
