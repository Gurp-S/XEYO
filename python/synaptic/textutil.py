"""WSC 文本层工具：消息扁平化、文件路径/符号抽取、错误签名、工具分类。

只依赖标准库；不 import 生产链模块。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

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
	# 去掉 heredoc / 重定向右值等易误伤片段
	cmd = re.sub(r"<<\s*['\"]?\w+['\"]?", " ", cmd)
	return extract_paths(cmd, limit=12)


# ---------------------------------------------------------------------------
# 错误签名
# ---------------------------------------------------------------------------

_SIG_PATTERNS = (
	re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning|Failure|Timeout))\b\s*:?\s*([^\n]{0,120})"),
	re.compile(r"\berror\[([A-Za-z0-9_]+)\]"),  # Rust 风格
	re.compile(r"\b(E\d{3,5})\b"),  # Python/TS 编译码
	re.compile(r"\b(TS\d{4})\b"),
	re.compile(r"\bexit(?:ed)?\s+(?:with\s+)?(?:code\s+)?([1-9]\d*)\b", re.IGNORECASE),
	re.compile(r"\bFAILED\b\s*([^\n]{0,120})"),
	re.compile(r"(?:^|\n)\s*(\d+\s+failed[^\n]{0,80})"),
)


def extract_error_sig(text: str, *, limit: int = 120) -> str:
	"""抽取错误签名：异常类 + 关键片段；无则回退首行实质内容。

裸数字（``255`` / ``1``）是退出码而非签名，补上语义前缀再用——否则 PIN 里
会出现「未解决: 255」这种读者无法判读的条目。
	"""
	if not text:
		return ""
	head = text[:4000]
	for pat in _SIG_PATTERNS:
		m = pat.search(head)
		if not m:
			continue
		groups = [g for g in m.groups() if g]
		sig = ": ".join(groups) if len(groups) > 1 else groups[0]
		sig = re.sub(r"\s+", " ", sig).strip()
		if not sig:
			continue
		if sig.isdigit():
			sig = f"退出码 {sig}"
		return sig[:limit]
	# 回退：首个非空且形似错误说明的行
	for line in head.splitlines():
		s = line.strip()
		if not s:
			continue
		if any(k in s.lower() for k in ("error", "failed", "cannot", "unable", "denied", "not found")):
			return re.sub(r"\s+", " ", s)[:limit]
	return ""


# ---------------------------------------------------------------------------
# 工具分类
# ---------------------------------------------------------------------------

WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "str_replace_editor"})
READ_TOOLS = frozenset({"Read", "Grep", "Glob", "NotebookRead", "LS", "View"})

# Bash 只读白名单（与仓库 bash 路由白名单同向；此处是宽松启发式，仅用于重放成本估计）
_BASH_READ_VERBS = (
	"cat ", "ls ", "dir ", "grep ", "rg ", "findstr ", "head ", "tail ", "wc ",
	"sed -n", "awk ", "git status", "git diff", "git log", "git show", "type ",
	"Get-Content", "Select-String", "python -c", "py -c", "node -e", "echo ",
)
_SHELL_META = re.compile(r"[|;&><`$]|\|\||&&")


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
	if n == "Bash":
		cmd = ""
		if isinstance(inp, dict):
			c = inp.get("command")
			cmd = c if isinstance(c, str) else ""
		if not cmd:
			return False, False, ""
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
