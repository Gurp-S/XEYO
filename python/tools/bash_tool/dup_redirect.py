"""Bash → 专用工具的「重复能力」重定向与路由规划（非权限、非审计）。

现象：模型常拿 Bash cat/find/ls/rg 干本应由 Read/Glob/Grep 干的活——这些读命令
零摩擦（只读白名单自动放行）、shell 本身通用、模型对 shell 最熟，于是描述层
（「Prefer Glob/Grep…」）压不住。本模块只做「解析」这一件纯函数的事：

- ``plan_bash_route``：把「意图毫无歧义」的纯文件读命令解析成等价专用工具计划
  （BashRoutePlan：tier 分级 / tool_name / tool_input / 审计摘要），供 Phase 0
  观测审计与 Phase 1 透明路由共用（见 bash 专用工具路由设计 #43）；
- ``redirect_hint``：现有 L2 的调用点错误提示（与 plan 同源，文案逐字节不变）。

判据原则（宁放勿拦——无法精确映射到专用工具语义的一律放行执行）：
- 必须是无元字符的单命令：| < > & ; ` ^ % $( 换行等出现即放行；
- 目标命令只在白名单内，且参数形状完全匹配；
- 文件路径参数不得含通配符（* ?），设备名（nul/con/...）放行；
- 带未知标志/多文件/复合查找选项（ls -lt、rg -l、find -exec）放行。

分级（决策 1 + 实测修正）：
- T1（语义铁证）：cat/type/Get-Content/gc [-n] <单文件> → Read
- T2（需显式保语义）：rg/ripgrep/grep/findstr [-rinIsEe...] <pattern> [<path>]
  → Grep（output_mode="content"：rg 默认打印命中行，Grep 默认只列文件名）

**明确不路由**：
- ls/dir/ll/la（裸列目录）：Glob 是"按名搜索"工具，对宽匹配 ``*`` 只回「目录摘要
  （文件数）」而不列文件名，无法满足"列出目录内容"→ 交给 bash 真实列目录
  （实测 `dir "docs\设计"` → Glob 只回 `./ (30 files)`，见 bash 路由设计 #43 §3.1）。
- find：**不在 bash 只读白名单**，`bash=default` 下先 ASK 用户，ALLOW 分支到不了、
  路由不触发，故不纳入解析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: 命令链/管道/重定向/换行等元字符：出现即视为复合命令，不重定向。
_METACHARS = re.compile(r"[|<>;&`^%]|\$\(|\n")

#: Windows 设备名（cat nul / type nul 常见于占位操作，非文件读）。
_DEVICE_NAMES = re.compile(r"^(nul|null|con|prn|aux|lpt[1-9]|com[1-9])$", re.I)

#: 文件名/路径里的通配符——出现即放行（shell 展开多文件，不可映射为单次工具调用）。
_WILDCARD = re.compile(r"[*?]")

#: grep 家族允许的短标志（组合如 -rn 逐字符校验）；不在此列的选项放行执行。
_GREP_FLAG_CHARS = frozenset("rRinIEs")

#: cmd 风格 /i /n /s（findstr 等）。
_CMD_FLAGS = re.compile(r"^/[ins]$", re.I)

#: 组合短标志，如 -rn / -iE；逐字符必须在 _GREP_FLAG_CHARS 内。
_GREP_COMBO = re.compile(r"^-([rRinIEs]+)$")

#: 语义保真分级（审计/开关按此区分）。
TIER_T1 = "T1"
TIER_T2 = "T2"


@dataclass(frozen=True)
class BashRoutePlan:
	"""一次 Bash→专用工具 的解析结果（Phase 0 观测 / Phase 1 路由共用）。

	- tier: 语义保真分级（T1/T2/T3）；
	- tool_name / tool_input: 等价专用工具调用（Phase 1 由 registry 执行，走完整
	  三态权限 + 审计 + 共享 read_state）；
	- brief: 审计/元数据用的命令摘要（去空白、截断）；
	- hint: 现有 L2 提示文案（与 redirect_hint 同源）；
	- note: 透明路由时结果头部的一行 [routed] 纠正提示。
	"""

	tier: str
	tool_name: str
	tool_input: dict[str, Any]
	brief: str
	hint: str
	note: str


@dataclass(frozen=True)
class _Hit:
	"""内部命中：tier / 目标工具输入 / L2 提示。"""

	tier: str
	tool_name: str
	tool_input: dict[str, Any]
	hint: str


def _tokens(command: str) -> list[str]:
	"""按空白切词：保留引号内空格，不做 shell 转义解释（Windows 反斜杠路径安全）。"""
	out: list[str] = []
	cur: list[str] = []
	quote: str | None = None
	for ch in command:
		if quote:
			if ch == quote:
				quote = None
			else:
				cur.append(ch)
		elif ch in "\"'":
			quote = ch
		elif ch.isspace():
			if cur:
				out.append("".join(cur))
				cur = []
		else:
			cur.append(ch)
	if cur:
		out.append("".join(cur))
	return out


def _short(text: str, limit: int = 80) -> str:
	text = (text or "").strip()
	return text if len(text) <= limit else text[: limit - 1] + "…"


def _read_positional(tokens: list[str], start: int) -> str | None:
	"""取唯一的位置参数（文件路径）；多参数/含通配符/设备名/未知标志 → None。"""
	path: str | None = None
	for tok in tokens[start:]:
		if tok in ("-n", "--number"):
			continue
		if tok.startswith("-"):
			return None
		if path is not None:
			return None
		if _WILDCARD.search(tok) or _DEVICE_NAMES.match(tok):
			return None
		path = tok
	return path


def _hit_read(tokens: list[str]) -> _Hit | None:
	path = _read_positional(tokens, 1)
	if not path:
		return None
	return _Hit(
		tier=TIER_T1,
		tool_name="Read",
		tool_input={"file_path": path},
		hint=(
			f'Use Read instead of Bash {tokens[0]}: file_path="{path}" '
			"(offset/limit for long files)."
		),
	)


def _hit_search(tokens: list[str]) -> _Hit | None:
	case_insensitive = False
	pattern: str | None = None
	path: str | None = None
	i = 1
	while i < len(tokens):
		tok = tokens[i]
		if tok in ("-e", "--regexp"):
			if pattern is not None:
				return None
			i += 1
			if i >= len(tokens):
				return None
			pattern = tokens[i]
		elif _GREP_COMBO.match(tok):
			if "i" in tok.lower():
				case_insensitive = True
		elif _CMD_FLAGS.match(tok):
			if tok.lower() == "/i":
				case_insensitive = True
		elif tok.startswith("-") or tok.startswith("/"):
			return None
		elif pattern is None:
			pattern = tok
		elif path is None:
			path = tok
		else:
			return None
		i += 1
	if pattern is None:
		return None
	if path and (_WILDCARD.search(path) or path.startswith("-") or path.startswith("/")):
		return None
	inp: dict[str, Any] = {
		"pattern": pattern,
		# rg 默认打印命中行；Grep 默认 files_with_matches——必须显式 content 保语义。
		"output_mode": "content",
	}
	if path:
		inp["path"] = path
	if case_insensitive:
		inp["case_insensitive"] = True
	extra = ", case_insensitive=true" if case_insensitive else ""
	tail = f', path="{path}"' if path else ""
	return _Hit(
		tier=TIER_T2,
		tool_name="Grep",
		tool_input=inp,
		hint=(
			f'Use Grep instead of Bash {tokens[0]}: pattern="{pattern}"{tail}'
			f"{extra}."
		),
	)


def _routed_note(command: str, hit: _Hit) -> str:
	"""透明路由结果头部的一行 [routed] 纠正提示。"""
	base = _short(command.strip().split()[0]) if command.strip() else "?"
	arg = hit.tool_input.get("file_path") or hit.tool_input.get("path")
	arg = arg if isinstance(arg, str) and arg.strip() else hit.tool_input.get("pattern")
	frag = f" {_short(str(arg))}" if isinstance(arg, str) and arg.strip() else ""
	return (
		f"[routed: Bash {base} → {hit.tool_name}{frag}] "
		f"Use {hit.tool_name} directly — "
		"Bash is only for commands without a dedicated tool."
	)


def plan_bash_route(command: str | None) -> BashRoutePlan | None:
	"""识别纯文件读的 Bash 命令，返回分级路由计划；None = 照常执行 Bash。"""
	hit = _classify(command)
	if hit is None:
		return None
	return BashRoutePlan(
		tier=hit.tier,
		tool_name=hit.tool_name,
		tool_input=dict(hit.tool_input),
		brief=_short(command),
		hint=hit.hint,
		note=_routed_note(command, hit),
	)


def redirect_hint(command: str | None) -> str | None:
	"""L2：识别纯文件读命令并返回替代工具提示（None = 不拦截，照常执行）。"""
	hit = _classify(command)
	return hit.hint if hit is not None else None


def _classify(command: str | None) -> _Hit | None:
	if not isinstance(command, str) or not command.strip():
		return None
	if _METACHARS.search(command):
		return None
	tokens = _tokens(command.strip())
	if not tokens:
		return None
	base = tokens[0].lower()
	if base in ("cat", "type", "gc", "get-content"):
		return _hit_read(tokens)
	if base in ("rg", "ripgrep", "grep", "findstr"):
		return _hit_search(tokens)
	return None
