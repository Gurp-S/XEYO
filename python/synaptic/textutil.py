"""WSC 文本层工具：消息扁平化、文件路径/符号抽取、错误签名、工具分类。

只依赖标准库；不 import 生产链模块。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from synaptic.memo import Memo

#: ``extract_paths`` 的记忆表（进程内、有界、不落盘）。见 ``synaptic/memo.py``。
_PATH_MEMO = Memo()

# ---------------------------------------------------------------------------
# 消息扁平化
# ---------------------------------------------------------------------------

def message_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
	"""把消息 content 归一为 block 列表（字符串 content 视为单个 text block）。"""
	content = msg.get("content")
	if isinstance(content, str):
		return [{"type": "text", "text": content}]
	if isinstance(content, list):
		return [b for b in content if isinstance(b, dict)]
	return []


def message_text(msg: dict[str, Any]) -> str:
	"""消息的可读文本（用于 token 估算 / 摘要 / 哈希）。"""
	content = msg.get("content")
	if isinstance(content, str):
		return content
	if not isinstance(content, list):
		return ""
	parts: list[str] = []
	for b in content:
		if not isinstance(b, dict):
			continue
		t = b.get("type")
		if t == "text":
			parts.append(str(b.get("text") or ""))
		elif t == "thinking":
			parts.append(str(b.get("thinking") or ""))
		elif t == "tool_use":
			parts.append(f"{b.get('name')}({_compact_json(b.get('input'))})")
		elif t == "tool_result":
			inner = b.get("content")
			if isinstance(inner, list):
				for ib in inner:
					if isinstance(ib, dict) and ib.get("type") == "text":
						parts.append(str(ib.get("text") or ""))
					elif isinstance(ib, str):
						parts.append(ib)
			else:
				parts.append(str(inner or ""))
	return "\n".join(p for p in parts if p)


def _compact_json(obj: Any) -> str:
	import json

	try:
		return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	except (TypeError, ValueError):
		return str(obj)


def content_hash(text: str) -> str:
	"""内容短哈希（确定性，跨进程一致）。"""
	return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def node_token_len(text: str) -> int:
	"""与生产链同口径的 P0 估参：ceil(utf-8 bytes / 4)。

	刻意内联而不 import ``memory.token``——旁路包对生产链零依赖。
	与 ``memory/token.py::token_len`` 数值一致（有契约测试锁死）。
	"""
	if not text:
		return 0
	return (len(text.encode("utf-8")) + 3) // 4


# ---------------------------------------------------------------------------
# 块级抽取
# ---------------------------------------------------------------------------

def tool_use_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
	out = []
	for b in message_blocks(msg):
		if b.get("type") == "tool_use":
			out.append(b)
	calls = msg.get("tool_calls")
	if isinstance(calls, list):
		for c in calls:
			if not isinstance(c, dict):
				continue
			fn = c.get("function") if isinstance(c.get("function"), dict) else {}
			out.append(
				{
					"type": "tool_use",
					"id": c.get("id") or "",
					"name": fn.get("name") or c.get("name") or "",
					"input": _maybe_json(fn.get("arguments")),
				}
			)
	return out


def tool_result_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
	out = []
	for b in message_blocks(msg):
		if b.get("type") == "tool_result":
			out.append(b)
	if msg.get("role") == "tool" and msg.get("tool_call_id"):
		out.append(
			{
				"type": "tool_result",
				"tool_use_id": msg.get("tool_call_id"),
				"content": msg.get("content"),
				"is_error": bool(msg.get("is_error")),
			}
		)
	return out


def tool_result_text(block: dict[str, Any]) -> str:
	inner = block.get("content")
	if isinstance(inner, list):
		parts = []
		for ib in inner:
			if isinstance(ib, dict) and ib.get("type") == "text":
				parts.append(str(ib.get("text") or ""))
			elif isinstance(ib, str):
				parts.append(ib)
		return "\n".join(parts)
	return str(inner or "")


def _maybe_json(raw: Any) -> Any:
	if isinstance(raw, str):
		import json

		try:
			return json.loads(raw)
		except (json.JSONDecodeError, ValueError):
			return {"_raw": raw}
	return raw if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# 路径 / 符号抽取
# ---------------------------------------------------------------------------

# 保守的路径正则：带扩展名、可含目录分隔符；排除 URL 与纯数字版本号。
_PATH_RE = re.compile(r"(?<![\w/])(?:[A-Za-z0-9_.\-]+[/\\])*[A-Za-z0-9_.\-]+\.[A-Za-z][A-Za-z0-9]{0,5}\b")
_URL_RE = re.compile(r"https?://\S+")
_SYMBOL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,}(?:\.[a-zA-Z_][A-Za-z0-9_]*)*)\b")

# Windows 盘符前缀，用于归一化
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

# 目录/扩展名黑名单（降低噪音）
_EXT_DENY = {
	"png", "jpg", "jpeg", "gif", "webp", "ico", "woff", "woff2", "ttf", "otf",
	"mp3", "mp4", "mov", "avi", "mkv", "wav", "flac", "pdf", "zip", "gz", "tar",
	"bz2", "7z", "rar", "lock",
}

# 无目录分隔符时只承认真实文件扩展名。否则 ``block.get`` / ``os.path`` /
# ``torch.nn`` 这类点号链会被误当路径，推高 path 针的分母并污染文件状态。
_EXT_ALLOW = frozenset({
	"bash", "bat", "c", "cc", "cfg", "cjs", "cmd", "conf", "cpp", "cs", "css",
	"csv", "cxx", "dart", "env", "go", "gql", "graphql", "h", "hpp", "hxx",
	"htm", "html", "ini", "java", "js", "json", "json5", "jsonc", "jsonl", "jsx",
	"kt", "kts", "less", "lua", "md", "mdx", "mjs", "php", "pl", "proto", "ps1",
	"py", "pyi", "r", "rb", "rs", "rst", "sass", "scss", "sh", "sql", "svelte",
	"swift", "tex", "tf", "tfvars", "toml", "ts", "tsv", "tsx", "txt", "vue", "xml",
	"yaml", "yml", "zsh",
})

# 少数无目录分隔符、扩展名碰巧像真实后缀的点号链，显式拒绝。
_DOTTED_CHAIN_DENY = frozenset({"block.get", "mss.mss", "sct.grab", "img.rgb", "os.path", "torch.nn"})

# ---------------------------------------------------------------------------
# 来源 / 路径过滤（建图前剔除机器噪音路径）
# ---------------------------------------------------------------------------

#: 二进制 / 构建产物扩展名：不承载任务事实（「这个解释器在哪」不是会话事实）。
_NOISE_EXT = frozenset({
	"exe", "dll", "so", "dylib", "pyd", "pyc", "pyo", "class", "jar", "o", "obj",
	"a", "lib", "node", "wasm", "pdb", "bin", "dmg", "msi", "whl",
})

#: 依赖 / 解释器 / 系统目录片段。这些目录下的路径属于环境而非任务。
_NOISE_FRAGMENTS = (
	"node_modules/", "site-packages/", "dist-packages/", "__pycache__/",
	"/.venv/", "/venv/", "/env/", "/.tox/", "/.jdks/", "/windowsapps/",
	"/appdata/local/temp/", "/tmp/", "/temp/", "/target/release/", "/target/debug/",
	"/.codex/plugins/cache/", "/.codex/skills/", "/.git/objects/", "/mnt/c/temp/",
)

#: 一次性临时 / 预览产物（调试截图、临时 HTML）。判据 = 文件名自带临时语义。
_NOISE_NAME_MARKERS = ("preview", "_tree_", "scratch", "tmp_", "_tmp", "screenshot", "debug_")


def is_noise_path(path: str) -> bool:
	"""来源过滤：该路径是否属于「机器噪音」而非任务事实。

	判据只看**路径自身**（扩展名 / 目录片段 / 临时产物命名），不做任何语义推断，
	因此对**所有信息类**同口径生效——不是 error 专用补丁。
	"""
	p = str(path or "").strip().lower()
	if not p:
		return True
	base = p.rsplit("/", 1)[-1]
	if "." in base and base.rsplit(".", 1)[-1] in _NOISE_EXT:
		return True
	for frag in _NOISE_FRAGMENTS:
		if frag in p:
			return True
	if base.startswith("_") and any(m in base for m in _NOISE_NAME_MARKERS):
		return True
	return False


def suffix_chain_canonical(paths: Iterable[str]) -> dict[str, str]:
	"""路径变体归并：把同一文件的不同写法折叠成最短写法。

	只认一种结构信号：**组内每个写法都以同一个最短写法结尾**（``components/X.tsx``
	是 ``code/cli/src/components/X.tsx`` 的路径段后缀）。该信号蕴含「同一文件」，
	不含任何语义猜测。只要有一个成员不满足（例如 ``a/index.ts`` 与 ``b/index.ts``
	互相不是对方的后缀），整组原样保留——宁可多留一条路径，也不把两个不同文件
	并成一个。归并只改**索引键**：原始消息文本一字节不动，冷层 expand 仍是原文。
	"""
	items = list(dict.fromkeys(str(p) for p in paths if p))
	groups: dict[str, list[str]] = {}
	for p in items:
		groups.setdefault(p.rsplit("/", 1)[-1], []).append(p)
	out: dict[str, str] = {}
	for _base, members in groups.items():
		if len(members) < 2:
			out[members[0]] = members[0]
			continue
		target = min(members, key=lambda x: (len(x), x))
		# 判据：组内**每个**写法都以 target 结尾（且对齐在路径段边界上）。这覆盖
		# ``a/x/W.tsx`` / ``code/x/W.tsx`` / ``W.tsx`` 这类同文件多写法；而
		# ``a/index.ts`` 与 ``b/index.ts`` 这种「同 basename、不同文件」不满足（谁也
		# 不以对方结尾）⇒ 整组保留，绝不并成一个。
		if not all(m == target or ("/" + m).endswith("/" + target) for m in members):
			for m in members:
				out[m] = m
			continue
		for m in members:
			out[m] = target
	return out



def normalize_path(path: str) -> str:
	"""归一化路径：反斜杠转正斜杠、去 Windows 盘符、去前导 ./。"""
	p = str(path or "").strip().strip("'\"`")
	if not p:
		return ""
	p = p.replace("\\", "/")
	if _DRIVE_RE.match(p):
		p = p[2:]
	p = re.sub(r"^\./+", "", p)
	p = re.sub(r"/+", "/", p)
	return p


def extract_paths(text: str, *, limit: int = 24) -> tuple[str, ...]:
	"""从任意文本抽取文件路径（确定性顺序：首次出现顺序，去重）。

	记忆化：本函数对每条消息各跑一次正则（标准会话 profile 里 14k 次 / 0.45 s），
	而输入文本在相邻两轮之间基本不变。纯函数 ⇒ 只影响耗时，不影响结果。
	返回值是**不可变 tuple**，调用方不可能原地改坏缓存。
	"""
	if not text:
		return ()
	return _PATH_MEMO.get_or((text, limit), lambda: _extract_paths_uncached(text, limit=limit))


def _extract_paths_uncached(text: str, *, limit: int = 24) -> tuple[str, ...]:
	scrubbed = _URL_RE.sub(" ", text)
	out: list[str] = []
	seen: set[str] = set()
	for m in _PATH_RE.finditer(scrubbed):
		raw = m.group(0)
		if raw.lower() in _DOTTED_CHAIN_DENY:
			continue
		ext = raw.rsplit(".", 1)[-1].lower()
		if ext in _EXT_DENY:
			continue
		p = normalize_path(raw)
		# 带目录分隔符的真实路径允许项目私有扩展名；无分隔符时只接受白名单后缀。
		if "/" not in p and ext not in _EXT_ALLOW:
			continue
		if not p or len(p) > 200 or "/" not in p and len(p) < 4:
			continue
		if is_noise_path(p):
			continue
		if p in seen:
			continue
		seen.add(p)
		out.append(p)
		if len(out) >= limit:
			break
	return tuple(out)


def extract_symbols(text: str, *, limit: int = 16) -> tuple[str, ...]:
	"""抽取疑似符号名（CamelCase / 点分路径），用作语义邻接的弱启发式。"""
	if not text:
		return ()
	out: list[str] = []
	seen: set[str] = set()
	for m in _SYMBOL_RE.finditer(text):
		s = m.group(1)
		if s in seen or len(s) < 4:
			continue
		seen.add(s)
		out.append(s)
		if len(out) >= limit:
			break
	return tuple(out)


def tool_input_paths(inp: Any) -> tuple[str, ...]:
	"""从工具入参里取最权威的路径字段（优先于文本扫描）。"""
	if not isinstance(inp, dict):
		return ()
	out: list[str] = []
	for key in ("path", "file_path", "file", "notebook_path", "target_file"):
		v = inp.get(key)
		if isinstance(v, str) and v.strip():
			p = normalize_path(v)
			if p:
				out.append(p)
	if not out:
		for key in ("paths", "files"):
			v = inp.get(key)
			if isinstance(v, list):
				for item in v:
					if isinstance(item, str) and item.strip():
						p = normalize_path(item)
						if p:
							out.append(p)
	return tuple(dict.fromkeys(out))


def command_paths(inp: Any) -> tuple[str, ...]:
	"""从 Bash 命令串里抽取路径（次权威来源）。"""
	if not isinstance(inp, dict):
		return ()
	cmd = inp.get("command")
	if not isinstance(cmd, str):
		return ()
	# 写目标就是「现场」，必须进 refs（`_scan` 检测到重定向后只回收拒绝原因、
	# 丢弃 target，所以这份抽取在 WSC 侧；漏了它 filestate 就不知道该路径被写过）。
	# 用**原串**抽：heredoc 标记下一步要被抹掉，但 `> path` 的位置不该受影响。
	targets = bash_write_targets(cmd)
	# 去掉 heredoc / 重定向右值等易误伤片段
	cmd = re.sub(r"<<\s*['\"]?\w+['\"]?", " ", cmd)
	return tuple(dict.fromkeys(targets + tuple(extract_paths(cmd, limit=12))))


# ---------------------------------------------------------------------------
# 错误签名
# ---------------------------------------------------------------------------

_SIG_PATTERNS = (
	re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning|Failure|Timeout))\b\s*:?\s*([^\n]{0,120})"),
	re.compile(r"\berror\[([A-Za-z0-9_]+)\]"),  # Rust 风格
	re.compile(r"\b(E\d{3,5})\b"),  # Python/TS 编译码
	re.compile(r"\b(TS\d{4})\b"),
	re.compile(r"\bFAILED\b\s*([^\n]{0,120})"),
	re.compile(r"(?:^|\n)\s*(\d+\s+failed[^\n]{0,80})"),
)

#: 「退出码」只是兜底，不是签名。原先它排在别名模式之前，于是 PowerShell 的失败
#: 一律被压成「退出码 1」——实测活跃失败 16 条里 12 条（75%）签名零信息量。
#: 兜底用的退出码抽取。第二种形状是**宿主回执信封的 JSON 键**（``"exit_code":1``）：
#: Codex 形态的 ``Script completed`` 信封把真退出码放在正文里，只配字面量
#: ``exit code N`` 时那批失败会判成错误却**没有签名**，而无签名的错误进不了
#: ``[UNRESOLVED]``（``seeds._unresolved_error_nodes`` 要求 ``is_error and error_sig``）。
_EXIT_ONLY_RE = re.compile(
	r"\bexit(?:ed)?\s+(?:with\s+)?(?:code\s+)?([1-9]\d*)\b"
	r'|\bexit_?code"?\s*[:=]\s*([1-9]\d*)',
	re.IGNORECASE,
)

#: **结构化失败行**（优先级高于退出码）：PowerShell 错误记录正文、构建/启动失败行。
_FAILURE_LINE_RES = (
	# PowerShell 错误记录的正文行：`     | Access to the path '…' is denied.`
	# 注意**不加行尾锚点**：错误正文经常超过 160 字符，加了 `$` 就整条匹配不上（实测漏 4 例）；
	# 也不限定最小长度到 7：`| 拒绝访问` 这种短正文同样是有用信息。
	re.compile(r"(?m)^\s*\|\s*([A-Za-z\u4e00-\u9fff][^\n|]{2,160})"),
	re.compile(r"(?m)^\s*(Unable to create process using[^\n]{0,140})"),
	re.compile(r"(?m)^\s*(Program '[^']{1,80}' failed to run:[^\n]{0,120})"),
	re.compile(r"(?m)^\s*(failed to (?:build|bundle|remove|compile|link|run|start|write)[^\n]{0,140})"),
	re.compile(r"(?m)^\s*((?:error|fatal):\s*[^\n]{6,140})"),
	re.compile(r"(?m)^\s*(?:warning:\s*)?(Not a git repository[^\n]{0,100})"),
)

#: PowerShell 错误记录头（单独成行的 `Cmdlet:`）：与正文行拼起来才是完整签名
#: （`Get-CimInstance: 拒绝访问` 比光秃秃的 `拒绝访问` 有用）。
_PS_HEADER_RE = re.compile(r"(?m)^\s*([A-Z][A-Za-z0-9_.\-]{2,40}):\s*$")
_PS_BODY_RE = re.compile(r"(?m)^\s*\|\s*([A-Za-z\u4e00-\u9fff][^\n|]{2,160})")
_PS_HEADER_SKIP = frozenset({"Output", "Chunk ID", "Wall time", "Original token count"})

#: PowerShell 语法错误块里「出错的那一行源码」：`   8 |  'stage': (Select-String …`
_NUMBERED_LINE_RE = re.compile(r"(?m)^\s*\d+\s*\|\s*([^\n]{6,140})$")

#: 明显无信息量的签名（会被上面两层替换掉；实在没有别的才留）。
_USELESS_SIG_RE = re.compile(r"(?i)^(?:退出码 \d+|.*\bLine \|\s*|warning:?)$")


def extract_error_sig(text: str, *, limit: int = 120) -> str:
	"""抽取错误签名：异常类 + 关键片段；无则回退首行实质内容。

裸数字（``255`` / ``1``）是退出码而非签名，补上语义前缀再用——否则 PIN 里
会出现「未解决: 255」这种读者无法判读的条目。
	"""
	if not text:
		return ""
	# 扫描窗 = 头 + 尾。**必须是两端**：构建/测试日志的失败行在尾部（实测一条 7638 字符的
	# tauri 日志，真正的 `error: failed to read asset …` 在 4000 字符之后，只看头就漏成
	# 「退出码 1」）。
	head = text[:4000]
	if len(text) > 4600:
		head = head + "\n" + text[-2500:]
	# ① 异常类 / 编译码 / FAILED（原有别名模式，去掉「退出码」——它降级为兜底）
	for pat in _SIG_PATTERNS:
		m = pat.search(head)
		if not m:
			continue
		groups = [g for g in m.groups() if g]
		sig = ": ".join(groups) if len(groups) > 1 else groups[0]
		sig = re.sub(r"\s+", " ", sig).strip()
		if not sig:
			continue
		# 「信息量不足」的异常签名先尝试**补全**（如 ParserError: Line | → 出错的那行源码），
		# 补不出来才继续往下走——直接 continue 会掉到「退出码」，等于白丢根因。
		sig = _refine_sig(sig, head)
		if _USELESS_SIG_RE.match(sig):
			continue
		return sig[:limit]
	# ② 结构化失败行（PowerShell 错误记录正文 / 构建·启动失败行）
	m = _PS_BODY_RE.search(head)
	if m:
		body = re.sub(r"\s+", " ", m.group(1)).strip()
		if body and not _USELESS_SIG_RE.match(body):
			head_name = ""
			for hm in _PS_HEADER_RE.finditer(head[: m.start()]):
				if hm.group(1) not in _PS_HEADER_SKIP:
					head_name = hm.group(1)
			return (f"{head_name}: {body}" if head_name else body)[:limit]
	for pat in _FAILURE_LINE_RES:
		m = pat.search(head)
		if m:
			sig = re.sub(r"\s+", " ", m.group(1)).strip()
			if sig and not _USELESS_SIG_RE.match(sig):
				return sig[:limit]
	# ③ 退出码（兜底，且带语义前缀）
	m = _EXIT_ONLY_RE.search(head)
	if m:
		return f"退出码 {m.group(1) or m.group(2)}"
	# ④ 首个形似错误说明的行
	for line in head.splitlines():
		s = line.strip()
		if not s:
			continue
		if any(k in s.lower() for k in ("error", "failed", "cannot", "unable", "denied", "not found")):
			return re.sub(r"\s+", " ", s)[:limit]
	return ""


def is_useful_error_sig(sig: str) -> bool:
	"""签名是否携带信息（排除「退出码 N」/「Xxx: Line |」这类零信息量回落）。"""
	s = re.sub(r"\s+", " ", str(sig or "")).strip()
	return bool(s) and not _USELESS_SIG_RE.match(s)


def _refine_sig(sig: str, head: str) -> str:
	"""把「信息量不足的异常签名」补成可用签名。

	两个实测形状：
	* ``ParserError:`` —— PowerShell 语法错误，正文里真正有用的是**出错的那一行源码**
	  （``   8 |  'stage': (Select-String …``），而不是 ``Line |``；
	* ``XxxError:`` 后面空着 —— 退回结构化失败行或原文首行。
	"""
	low = sig.rstrip()
	if "Line |" in low or low.endswith(":"):
		name = low.split(":", 1)[0].strip() or sig
		m = _NUMBERED_LINE_RE.search(head)
		if m:
			body = re.sub(r"\s+", " ", m.group(1)).strip()
			return f"{name}: {body}"
	return sig


# ---------------------------------------------------------------------------
# 工具分类
# ---------------------------------------------------------------------------

#: 写工具（会改盘）。``apply_patch`` 是 Codex 形态轨迹里**实际在用的写工具**——
#: 原先漏登记，导致「成功改写同一文件」这条时效轴覆盖信号、以及 filestate 的 stale 标记
#: 在本语料里全程不触发（109 次 apply_patch 全被当成「既非写也非读」）。
WRITE_TOOLS = frozenset({
	"Write", "Edit", "MultiEdit", "NotebookEdit", "str_replace_editor", "apply_patch",
})
READ_TOOLS = frozenset({
	"Read", "Grep", "Glob", "NotebookRead", "LS", "View", "view_image",
})

# Bash 只读白名单（与仓库 bash 路由白名单同向；此处是宽松启发式，仅用于重放成本估计）
_BASH_READ_VERBS = (
	"cat ", "ls ", "dir ", "grep ", "rg ", "findstr ", "head ", "tail ", "wc ",
	"sed -n", "awk ", "git status", "git diff", "git log", "git show", "type ",
	"Get-Content", "Select-String", "python -c", "py -c", "node -e", "echo ",
)
_SHELL_META = re.compile(r"[|;&><`$]|\|\||&&")


_FULL_FILE_READ_VERBS = ("cat ", "type ", "Get-Content")


def is_full_file_read(replay_cmd: str) -> bool:
	"""这条只读命令是否**读了整个文件**。

	只有整文件读才有资格进文件状态表：``grep`` / ``rg`` / ``head`` / ``sed -n`` / ``ls``
	给的是片段或目录项，把它们当成「文件现状我看过」会让**写后过期（stale）时钟凭空归零**
	——正是 `filestate` 模块存在的理由要杜绝的「最后一次 read 只读了一半却当成完整文件」。
	带管道/重定向的命令在 ``classify_tool`` 里已经判不出 ``read_only``，故 ``cat x | head``
	这类被截断的形状不会误进来。
	"""
	s = str(replay_cmd or "").strip()
	return any(s.startswith(v) or s.startswith(v.strip()) for v in _FULL_FILE_READ_VERBS)


#: bash / shell **写操作**的外部判据槽（默认未注册）。
#:
#: 存在理由（问答集 A 组整列 N/A 的直接根因）：容器内任务的改盘动作几乎全走
#: bash heredoc / 重定向，而 ``WRITE_TOOLS`` 只认 Write/Edit/apply_patch ⇒ 图里
#: ``is_write`` 恒 False ⇒「末次写是否成功」「写之前的读」这类题**没有分母**，
#: 47 会话 / 29 个外部 verifier 真值一条都配对不上。
#:
#: 为什么走槽、不在算法层直接 import：``metrics.ALGORITHM_MODULES`` 执法
#: ``textutil`` / ``graph`` / ``filestate`` 对生产链零依赖，而 ``permissions`` 在
#: ``PRODUCTION_ROOTS`` 里；同时「这条命令是不是写」的判据已经有一份结构化的
#: （``permissions/bash_readonly.py`` 的 ``_scan`` + ``redirect_write``），在算法层
#: 再写一份正则就是本仓最忌讳的第二份口径。
#:
#: 默认 ``None`` ⇒ bash 写一律不识别 = **现行为逐字节不变**；由接线层注册后生效
#: （旁路上线，拿到收益数据再并入主链）。
_BASH_WRITE_PROBE: Any = None


def set_bash_write_probe(fn: Any) -> None:
	"""注册 / 清空 bash 写判据：``fn(command) -> 被写路径元组``（非写返回空）。"""
	global _BASH_WRITE_PROBE
	_BASH_WRITE_PROBE = fn


def bash_write_targets(command: Any) -> tuple[str, ...]:
	"""这条 shell 命令写了哪些路径；不是写、或判据未注册 ⇒ 空元组。"""
	probe = _BASH_WRITE_PROBE
	if probe is None or not isinstance(command, str) or not command.strip():
		return ()
	try:
		targets = probe(command)
	except Exception:  # noqa: BLE001 - 外部判据失灵不得影响建图（fail-open）
		return ()
	return tuple(t for t in (targets or ()) if isinstance(t, str) and t.strip())


def classify_tool(name: str, inp: Any) -> tuple[bool, bool, str]:
	"""返回 (is_write, read_only, replay_cmd)。

	``read_only`` 表示「可安全重放」——只读且命令无副作用。``replay_cmd``
	仅在 read_only 时非空（Write 类工具重放会改盘，不记）。
	"""
	n = str(name or "")
	if n in WRITE_TOOLS:
		return True, False, ""
	if n in READ_TOOLS:
		return False, True, ""
	if n in ("Bash", "exec_command", "exec"):
		cmd = ""
		if isinstance(inp, dict):
			c = inp.get("command") or inp.get("cmd")
			cmd = c if isinstance(c, str) else ""
		if not cmd:
			return False, False, ""
		# **写判定必须先于 `_SHELL_META` 早退**：重定向正是被它拦成「结构不可判」的，
		# 而那恰好就是 bash 改盘的主要形状。
		if bash_write_targets(cmd):
			return True, False, ""
		if _SHELL_META.search(cmd):
			return False, False, ""
		stripped = cmd.strip()
		if any(stripped.startswith(v) or stripped.startswith(v.strip()) for v in _BASH_READ_VERBS):
			return False, True, stripped[:240]
		return False, False, ""
	return False, False, ""


def read_range(inp: Any, content: str) -> tuple[int, int] | None:
	"""解析 Read 的已读区间（1-based 闭区间）；无法判定返回 None。"""
	if not isinstance(inp, dict):
		return None
	try:
		offset = int(inp.get("offset") or 1)
	except (TypeError, ValueError):
		offset = 1
	offset = max(1, offset)
	try:
		limit = int(inp.get("limit") or 0)
	except (TypeError, ValueError):
		limit = 0
	n_lines = content.count("\n") + (1 if content else 0)
	if limit > 0:
		return offset, offset + min(limit, max(1, n_lines)) - 1
	if n_lines <= 1:
		return offset, offset
	return offset, offset + n_lines - 1
