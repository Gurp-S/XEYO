"""按内容类型动态抽取工具输出的短摘要（C2 摘要的“语义片段”）。

把“无脑取正文前 160 字符”升级成：
- 错误 / 栈回溯：保留首尾（头部栈帧 + 尾部异常/错误）。
- grep / rg：只保留“匹配行统计 + 命中的 文件:行号 + 几个真实匹配行”。
- read / 大文件：内容自适应——取值行多则保留“N params :: key=value”，否则“行数+结构签名+头部”。
- bash / 其它长文本：含参数表则抽取值，否则 head + tail。
- 短内容（<= max_text）原样返回，不误伤。

纯函数、确定性、无 I/O、不碰存储。可在热路径直接调用。
"""

from __future__ import annotations

import re

# 结构分支各保留的“首/尾”行数
HEAD_LINES = 8
TAIL_LINES = 6
# 报错/栈回溯的窗口更小：首 4 行（外层调用）+ 尾 3 行（内层调用 + 异常），
# 否则短回溯会把整段都当“尾部”、压平后截掉真正的 Error。
ERROR_HEAD_LINES = 4
ERROR_TAIL_LINES = 3
DEFAULT_MAX_TEXT = 160

# 错误/栈回溯标记（内容形态，不依赖工具名）
_TRACEBACK_MARKER = "traceback (most recent call last)"
_STACK_FILE_RE = re.compile(r'(^|\n)\s+File "[^"]+", line \d+')
_STACK_AT_RE = re.compile(r"(^|\n)\s+at\s+[\w.$<>]+\(.*?\)")
_STACK_NATIVE_RE = re.compile(r"(^|\n)\s*#\d+\s+0x[0-9a-f]+")
_ERROR_TYPE_RE = re.compile(
    r"\b(exception|assertionerror|valueerror|keyerror|typeerror|runtimeerror|"
    r"importerror|oserror|filenotfounderror|filenotfound|notimplementederror|"
    r"indexerror|attributingerror|zerodivisionerror|modulenotfounderror|"
    r"syntaxerror|permissionerror|timeouterror|timeout)\b",
    re.IGNORECASE,
)
_ERROR_HEAD_RE = re.compile(r"(^|\n)\s*[\w.$<>]*error\s*:", re.IGNORECASE)

_GREP_TOOLS = frozenset({"grep", "rg", "ripgrep", "search", "find"})
_READ_TOOLS = frozenset(
    {"read", "readfile", "cat", "head", "tail", "ls", "glob", "list", "tree"}
)


def is_error_like(text: str) -> bool:
    """按内容形态判断是否像错误/栈回溯；纯内容判断，不依赖工具名。"""
    t = (text or "").strip()
    if not t:
        return False
    if _TRACEBACK_MARKER in t.lower():
        return True
    if _STACK_FILE_RE.search(t) or _STACK_AT_RE.search(t) or _STACK_NATIVE_RE.search(t):
        return True
    if _ERROR_TYPE_RE.search(t) or _ERROR_HEAD_RE.search(t):
        return True
    return False


def _flatten(text: str) -> str:
    """多行 / 多余空白压成单行，避免摘要行被换行撑破。"""
    return re.sub(r"\s+", " ", (text or "").strip())


def _clip(text: str, limit: int) -> str:
    """单行化后按 limit 截断，保留尾部省略号。"""
    t = _flatten(text)
    if len(t) <= limit:
        return t
    return t[: max(1, limit - 1)].rstrip() + "…"


def _join_ht(head: str, tail: str, *, max_text: int) -> str:
    """把首部与尾部拼成一条摘要；空间不足时**尾部优先**（报错/结尾最重要）。"""
    sep = " … "
    if not tail:
        return _clip(head, max_text)
    head = _flatten(head)
    tail = _flatten(tail)
    if len(tail) > max_text:
        tail = tail[: max(1, max_text - 1)].rstrip() + "…"
    budget_head = max_text - len(tail) - len(sep)
    if budget_head < 8:
        # 空间只够给尾部（报错 / 结尾结果最重要），优先保留尾部
        return tail[:max_text]
    if len(head) > budget_head:
        head = head[: max(1, budget_head - 1)].rstrip() + "…"
    return head + sep + tail


def _head_tail(raw: str, *, max_text: int, head_lines: int, tail_lines: int) -> str:
    """保留前 head_lines 行 + 后 tail_lines 行，中间省略。

    head / tail 不重叠（行数不足以分开时减少 head 行数）；字符串超长时由
    _join_ht 尾部优先截断，确保报错/结尾出现在摘要里。
    """
    lines = (raw or "").splitlines()
    if not lines:
        return ""
    n = len(lines)
    tail_lines = max(0, min(tail_lines, n))
    head_lines = max(0, min(head_lines, n - tail_lines))
    head = "\n".join(lines[:head_lines])
    tail = "\n".join(lines[n - tail_lines:]) if tail_lines else ""
    return _join_ht(head, tail, max_text=max_text)


def _looks_like_path(p: str) -> bool:
    p = (p or "").strip()
    if not p or len(p) > 80:
        return False
    if "/" in p or "\\" in p:
        return True
    return bool(re.search(r"\.(py|ts|tsx|js|jsx|go|rs|java|c|cpp|h|hpp|md|json|toml|yaml|yml|txt|sh|css|html|xml)$", p))


# ---- Read / 大文件：结构签名行规则 ----
_SIG_START_RE = re.compile(
    r"^(?:def |async def |class |import |from .+ import |#{1,6} |\[[^\]]+\]|@\w+|https?://|[A-Za-z_][\w.]*\s*=|```)"
)


def _is_signature(line: str) -> bool:
    """是否像"结构签名"行：函数/类/导入/标题/节头/装饰器/URL/顶层赋值。"""
    s = _LINENO_PREFIX_RE.sub("", line).strip()
    return bool(s) and bool(_SIG_START_RE.match(s))


def _signature_lines(lines, *, limit: int = 5) -> list[str]:
    """抽结构签名行（文件"目录/骨架"）；过多时首尾散布以传达"从哪到哪"的范围。"""
    sigs: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        s = _LINENO_PREFIX_RE.sub("", ln).strip()
        if not _is_signature(s):
            continue
        key = s[:60]
        if key in seen:
            continue
        seen.add(key)
        sigs.append(s)
    if len(sigs) <= limit:
        return sigs
    # 保留首 limit-1 条 + 最后 1 条，中间省略
    return sigs[: limit - 1] + ["…"] + sigs[-1:]


# ---- 取值/定义抽取：key=value / markdown 表 / 默认值 ----
_SKIP_NAME_RE = re.compile(r"^(self\.|tmp|temp|[a-z])$", re.IGNORECASE)
_VALUE_ASSIGN_RE = re.compile(r"^([A-Za-z_][\w.]{0,40})\s*=\s*(.+?)\s*$")
_VALUE_COLON_RE = re.compile(r"^([A-Za-z_][\w.]{0,40})\s*:\s*(.+?)\s*$")
_VALUE_DEFAULT_RE = re.compile(r"^(?:默认|default)\s*[:=]?\s*(.+?)\s*$", re.IGNORECASE)
# 某些 Read 输出每行带 "NNN→" 行号前缀，先剥掉再解析取值/结构
_LINENO_PREFIX_RE = re.compile(r"^\d{1,5}\s*→\s*")
_VALUE_KEYWORDS = frozenset({"none", "true", "false", "null", "nan", "yes", "no"})
# 列头/非取值词：markdown 表首行等，避免被当成取值
_HEADER_WORDS = frozenset({
    "记号", "人话", "默认", "值", "名称", "名字", "含义", "说明", "描述", "符号",
    "注释", "备注", "参数", "字段", "类型", "value", "default", "name", "desc",
    "description", "type", "key", "note", "含义", "意义",
})
# 表头里表示"取值列"的词：命中则该列为 value
_VALUE_TABLE_HEADERS = frozenset({"默认", "default", "值", "value", "取值", "default_value"})
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _is_good_value(v: str) -> bool:
    """取值是否"高价值"：数字 / 含数字的短值 / 纯 ASCII 短 token；拒绝中文描述句、代码表达式、列头词。"""
    v = (v or "").strip().strip("`\"'").strip().rstrip(",").strip()
    if not v:
        return False
    low = v.lower().strip()
    if low in _VALUE_KEYWORDS or low in _HEADER_WORDS:
        return False
    if len(v) > 30:
        return False
    if re.search(r"[()=]", v):  # 代码表达式/函数调用/赋值
        return False
    if v.startswith(("http://", "https://")):
        return False
    if re.fullmatch(r"-?\d+(\.\d+)?%?", v):  # 纯数字
        return True
    # 含数字的短值（如 DeepSeek 64）——但中文描述句（≥3 汉字）不算
    if re.search(r"\d", v) and len(v) <= 25 and len(_CJK_RE.findall(v)) < 3:
        return True
    # 纯 ASCII 短 token / 符号（无汉字）
    if not re.search(_CJK_RE, v) and re.fullmatch(r"[A-Za-z0-9_\-\.]+(?: [A-Za-z0-9_\-\.]+)?", v):
        return True
    return False


def _value_from_cell(cell: str) -> str | None:
    """取值单元格 → 高价值取值；前导/独立数字回退（如「0.85；按层…」取 0.85、「默认 8。…」取 8）。

    只取「独立数字」（前面不是字母，避免把 P0/alpha_win 里的数字当取值），
    且数字前只能有 默认/约/:= 或 ≤2 字符标签（如「检索 0.8」取 0.8）。
    """
    c = (cell or "").strip()
    if _is_good_value(c):
        return c
    m = re.search(r"(?<![\w])(-?\d+(?:\.\d+)?)", c)
    if m:
        prefix = c[: m.start()].strip()
        rest = re.sub(r"[默认约:=\s]", "", prefix)
        if not rest or len(rest) <= 2:
            return m.group(1)
    return None


def _table_cells(s: str) -> list[str] | None:
    """解析一行 markdown 表格单元格（剥行号前缀、去首尾管道）。"""
    s = _LINENO_PREFIX_RE.sub("", (s or "").strip())
    if "|" not in s:
        return None
    body = s
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells = [c.strip() for c in body.split("|")]
    return cells if any(cells) else None


def _match_value_line(s: str) -> tuple[str, str] | None:
    """把非表格行的 (name, value) 抽出来；非取值行返回 None。"""
    s = (s or "").strip()
    if not s or s.startswith(("#", "//", "<!--", "```")):
        return None
    s = _LINENO_PREFIX_RE.sub("", s)
    m = _VALUE_ASSIGN_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _VALUE_COLON_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _VALUE_DEFAULT_RE.match(s)
    if m and m.group(1).strip():
        return "default", m.group(1).strip()
    return None


# #2 补强：数字+单位（measured value）与 路径 也作为高价值事实。
# 数字必须带单位（128k/605token/0.05元/99.4%），避免抓到海量裸数字噪音；
# 路径认文件扩展名与 Windows 路径。
_NUM_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,8}(?:\.\d+)?)\s*(k|K|KB|MB|GB|tokens?|token|chars?|字符|%|ms|元)\b"
)
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])((?:[A-Za-z]:\\[\w\\ .:+-]+|[\w./-]+\.(?:md|py|ts|tsx|js|jsx|json|css|txt|toml|yml|yaml|html|log|sql|bat|sh)))(?![A-Za-z0-9])"
)
# #2 补强：上下文置信度 / 噪音 / 路径防噪 / 类目上限
_NUM_CAP = 12
_PATH_CAP = 8
_CTX_HIGH_RE = re.compile(r"配置|阈值|大小|数量|路径|版本|容量|长度|默认|单位|次数|行数|字符|字节|token|字符数", re.I)
_TS_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{2}:\d{2}:\d{2}|1[6-9]\d{9}|^\d{9,}$")


def _is_noise_num(s: str) -> bool:
	"""数字+单位 里的噪音：时间戳/日期/超长ID。"""
	return bool(_TS_RE.search(s or ""))


def _valid_path(s: str) -> bool:
	"""路径防误伤：排除 URL(http/https) 与纯数字。"""
	if not s or "://" in s:
		return False
	if re.search(r"^\d+$", s):
		return False
	return True


def _ctx_boost(raw: str, s: str, pos: int) -> int:
	"""上下文置信度：数字/路径紧邻关键词 → +1 权重。"""
	ctx = raw[max(0, pos - 20):pos + len(s) + 20]
	return 1 if _CTX_HIGH_RE.search(ctx) else 0


def extract_value_facts(text: str, *, limit: int = 8) -> list[tuple[str, str]]:
    """抽内容里的高价值"取值/定义"事实（参数表、常量、默认值）。

    - markdown 表：只认含"默认/值/value"表头的表，抽对应列为 value，避免把动作表/现状表误抽。
    - 非表格行：识别 `key=value` / `key: value` / `默认 X`。
    - 只保留数字/含数字短值/ASCII 短 token；过滤代码局部变量、代码表达式、中文描述句。
    确定性、无 I/O；供 Read 大文件摘要优先保留"取值"这一层事实。
    """
    facts: list[tuple[str, str]] = []
    seen: set[str] = set()
    lines = (text or "").splitlines()
    n = len(lines)
    i = 0
    reserved = min(4, max(0, limit))  # 为 num/path 高价值事实保留份额，避免被 key=value 挤光
    while i < n and len(facts) < limit - reserved:
        s = _LINENO_PREFIX_RE.sub("", lines[i]).strip()
        cells = _table_cells(s) if "|" in s else None
        # ---- 取值表：表头含"默认/值"，抽该列为 value ----
        if cells and any(c.lower() in _VALUE_TABLE_HEADERS for c in cells):
            value_col = next(
                (j for j, c in enumerate(cells) if c.lower() in _VALUE_TABLE_HEADERS),
                len(cells) - 1,
            )
            j = i + 1
            while j < n and len(facts) < limit - reserved:
                rs = _LINENO_PREFIX_RE.sub("", lines[j]).strip()
                rc = _table_cells(rs) if "|" in rs else None
                if rc is None:
                    break
                if all((c.strip().startswith("-") or not c.strip()) for c in rc):
                    j += 1  # 分隔行 | --- |
                    continue
                if len(rc) > value_col:
                    name = rc[0].strip()
                    val = _value_from_cell(rc[value_col])
                    if val and name and not _SKIP_NAME_RE.match(name):
                        key = f"{name}:{val}"
                        if key not in seen:
                            seen.add(key)
                            facts.append((name, val))
                j += 1
            i = j
            continue
        # ---- 非表格行 ----
        row = _match_value_line(s)
        if row is not None:
            name, value = row
            if not _SKIP_NAME_RE.match(name) and _is_good_value(value):
                key = f"{name}:{value}"
                if key not in seen:
                    seen.add(key)
                    facts.append((name, value))
        i += 1
    # #2 补强：数字+单位 / 路径，dict 去重 + 上下文置信度 + 类目均衡（填剩余 reserved）。
    whole = text or ""
    num_cands: dict[str, tuple[int, str]] = {}
    path_cands: dict[str, tuple[int, str]] = {}
    for m in _NUM_UNIT_RE.finditer(whole):
        s = f"{m.group(1)}{m.group(2)}"
        if s.lower() in seen or _is_noise_num(s):
            continue
        sc = _ctx_boost(whole, s, m.start())
        prev = num_cands.get(s.lower())
        if prev is None or sc > prev[0]:
            num_cands[s.lower()] = (sc, s)
    for m in _PATH_RE.finditer(whole):
        s = m.group(1).strip()
        if s.lower() in seen or _SKIP_NAME_RE.match(s) or not _valid_path(s):
            continue
        sc = _ctx_boost(whole, s, m.start())
        prev = path_cands.get(s)
        if prev is None or sc > prev[0]:
            path_cands[s] = (sc, s)
    room = max(0, limit - len(facts))
    num_list = sorted(num_cands.values(), key=lambda x: -x[0])
    path_list = sorted(path_cands.values(), key=lambda x: -x[0])
    # 均衡：数字优先，但给路径保底 1 条（若有）；各自按置信度取 top。
    num_take = min(_NUM_CAP, len(num_list), max(0, room - 1))
    num_take = max(0, num_take)
    if num_take > 0:
        for _sc, s in num_list[:num_take]:
            if s.lower() in seen:
                continue
            facts.append(("num", s))
            seen.add(s.lower())
    path_take = min(_PATH_CAP, len(path_list), max(0, room - num_take))
    if path_take > 0:
        for _sc, s in path_list[:path_take]:
            if s.lower() in seen:
                continue
            facts.append(("path", s))
            seen.add(s.lower())
    return facts


def extract_semantic_facts(text: str, *, num_cap: int = 20, path_cap: int = 10) -> dict:
	"""结构化事实抽取（供抽取式摘要 Phase1 用）：返回 {numeric_facts, path_facts}。

	与 extract_value_facts（(name,value) 兼容旧调用）不同，本函数返回结构化 JSON，
	生成式 Phase2 可按需引用；含 context 置信度 + 类目上限。
	"""
	whole = text or ""
	seen: set[str] = set()
	numeric: list[dict] = []
	path: list[dict] = []
	for m in _NUM_UNIT_RE.finditer(whole):
		v, u = m.group(1), m.group(2)
		s = f"{v}{u}"
		if s.lower() in seen or _is_noise_num(s):
			continue
		seen.add(s.lower())
		numeric.append({"value": v, "unit": u, "raw": s, "ctx": _ctx_boost(whole, s, m.start())})
	for m in _PATH_RE.finditer(whole):
		s = m.group(1).strip()
		if s.lower() in seen or not _valid_path(s):
			continue
		seen.add(s.lower())
		path.append({"path": s, "raw": s, "ctx": _ctx_boost(whole, s, m.start())})
	numeric.sort(key=lambda x: -x["ctx"])
	path.sort(key=lambda x: -x["ctx"])
	return {"numeric_facts": numeric[:num_cap], "path_facts": path[:path_cap]}


def _compact_symbol(name: str) -> str:
    """把 LaTeX 记号压成可读短名：\\(\\theta\\)→theta、\\tau_{switch}→tau_switch。"""
    n = name.replace("\\(", "").replace("\\)", "").replace("\\", "")
    n = re.sub(r"\{(\w+)\}", r"\1", n)  # _{x} -> _x
    return n.strip() or name


def _compact_value(v: str) -> str:
    """把"短字母标签+数字"的值压成数字（如 DeepSeek 64 -> 64），日期/版本不压。"""
    v = str(v or "").strip()
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*$", v)
    if m:
        label = v[: m.start()].strip()
        if re.fullmatch(r"[A-Za-z]{1,8}", label):
            return m.group(1)
    return v


def _read_summary(raw: str, *, max_text: int) -> str:
    """大文件/Read 摘要：内容自适应。

    - 取值行足够多（≥3）→ 优先保留"取值"：`{n} lines, {m} params :: name=value, …`。
    - 否则 → 结构分支：`{n} lines :: 结构签名行 :: 头部`。
    相比"只保前 8 行"，能保住"文件里有什么/关键取值"这一层事实。
    """
    lines = (raw or "").splitlines()
    if not lines:
        return ""
    n = len(lines)
    vals = extract_value_facts(raw, limit=8)
    # ---- 取值优先：优先列"数字取值"，压缩符号名，尽量塞进 max_text ----
    if len(vals) >= 3:
        nums = re.compile(r"-?\d+(?:\.\d+)?")
        facts = sorted(
            vals,
            key=lambda kv: (
                0 if nums.fullmatch(str(_compact_value(kv[1])).strip()) else 1,
                nums.fullmatch(str(_compact_value(kv[1])).strip()) is None,
            ),
        )
        pairs = ", ".join(f"{_compact_symbol(name)}={_compact_value(value)}" for name, value in facts)
        return _clip(f"{n} lines, {len(facts)} params :: {pairs}", max_text)
    # ---- 结构分支 ----
    sigs = _signature_lines(lines, limit=5)
    out = f"{n} lines"
    if sigs:
        out += " :: " + " | ".join(sigs)
    out = _flatten(out)
    if len(out) >= max_text - 4:
        return _clip(out, max_text)
    head = _flatten("\n".join(lines[:3]))
    budget = max_text - len(out) - 4
    if budget >= 10:
        out += " :: " + head[:budget]
    return _clip(out, max_text)


def _grep_summary(lines, *, max_text: int, total: int) -> str:
    """grep 输出：给“文件:行号 统计 + 真实匹配行样本”，而不是任意开头。"""
    files: list[str] = []
    samples: list[str] = []
    line_nos: list[int] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if len(samples) < 3:
            samples.append(s)
        m = re.match(r"^([^:]{1,80}):(\d+):(.*)$", s)
        if not m:
            m2 = re.match(r"^([^:\s]{1,80}):(.+)$", s)
            if m2 and _looks_like_path(m2.group(1)):
                path = m2.group(1).strip()
                if path and path not in files and len(files) < 8:
                    files.append(path)
            continue
        path = m.group(1).strip()
        if path and path not in files and len(files) < 8:
            files.append(path)
        n = int(m.group(2))
        if n not in line_nos and len(line_nos) < 8:
            line_nos.append(n)

    head = f"{total} matches"
    if files:
        head += f" in {len(files)} file(s): " + ", ".join(files[:4])
        if len(files) > 4:
            head += f", +{len(files) - 4}"
    if line_nos:
        head += f" @line {line_nos[0]}"
    head = _flatten(head)
    if samples:
        budget = max_text - len(head) - 4
        if budget >= 8:
            head += " :: " + _flatten(" | ".join(samples[:3]))[:budget]
    return _clip(head, max_text)


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")  # CSI/OSC 转义序列


def _clean_tool_output(raw: str, name: str = "") -> str:
	"""L1 智能过滤：去 ANSI 转义 +（噪音源）连续重复行去重，零成本。

	- ANSI 转义总是剥（着色/进度条）。
	- 连续重复行去重**仅对噪音源**（Bash/通用长文本，如循环输出、进度副本）；
	  文件读（Read）与 grep 的行数/匹配是信息，不去重（避免把 N 行内容折叠成 3 行、
	  破坏"N lines::…"结构检测）。
	"""
	if not raw:
		return raw
	t = _ANSI_RE.sub("", raw)
	if (name or "").strip().lower() in _READ_TOOLS or (name or "").strip().lower() in _GREP_TOOLS:
		return t
	lines = t.splitlines()
	out: list[str] = []
	prev = None
	for ln in lines:
		s = ln.strip()
		if s and s == prev:  # 连续完全相同行（循环/进度/重复样板）→ 去噪
			continue
		prev = s
		out.append(ln)
	return "\n".join(out)


def extract_tool_summary(
    content: str, tool_name: str = "", *, max_text: int = DEFAULT_MAX_TEXT
) -> str:
    """按工具类型 + 内容形态动态抽取短摘要；<=max_text 时原样返回。"""
    raw = _clean_tool_output(content or "", name=tool_name).strip()
    if not raw:
        return ""
    if len(raw) <= max_text:
        return raw
    name = (tool_name or "").strip().lower()
    lines = raw.splitlines()
    nonempty = sum(1 for ln in lines if ln.strip())
    if is_error_like(raw):
        return _head_tail(raw, max_text=max_text, head_lines=ERROR_HEAD_LINES, tail_lines=ERROR_TAIL_LINES)
    if name in _GREP_TOOLS or nonempty and _looks_like_grep(lines):
        return _grep_summary(lines, max_text=max_text, total=nonempty)
    if name in _READ_TOOLS:
        return _read_summary(raw, max_text=max_text)
    # 默认长文本：若含参数/定义表则抽取值，否则 head+tail
    if len(extract_value_facts(raw, limit=8)) >= 3:
        return _read_summary(raw, max_text=max_text)
    return _head_tail(raw, max_text=max_text, head_lines=HEAD_LINES, tail_lines=TAIL_LINES)


def _looks_like_grep(lines) -> bool:
    """无工具名时按内容形态兜底：多数行像 路径:行号:内容。"""
    hit = 0
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^[^:]{1,80}:\d+:", s):
            hit += 1
    return hit >= 2
