"""Bash 命令黑名单 + 前缀规则引擎（只读白名单/收紧规则）+ 密钥读探测（L1：不做完整 AST）。

T7：内置只读白名单迁移为默认前缀规则；工作区可加 `.xeyo/bash_rules.(json|toml)`
规则（allow 追加只读放行面、ask/deny 全模式收紧），多规则命中最严胜出；
示例自校验矛盾规则拒载并报错。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# (pattern, reason) — 命中即 deny。保持短、可讲、可测。
_DENY_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
	# rm -rf / 与变体（含 --no-preserve-root、多余空白、Windows \）
	(
		re.compile(
			r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|--recursive.*--force|--force.*--recursive)"
			r".*(?:[/\\](?:\s|$)|--no-preserve-root)",
			re.I | re.S,
		),
		"destructive_root_delete",
	),
	(
		re.compile(
			r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*).*(?:[/\\](?:\s|$)|--no-preserve-root)",
			re.I | re.S,
		),
		"destructive_root_delete",
	),
	(re.compile(r"\bformat\s+[a-z]:", re.I), "disk_format"),
	(re.compile(r"\bmkfs(\.\w+)?\b", re.I), "disk_format"),
	(re.compile(r"\bcipher\s+/w", re.I), "disk_wipe"),
	(re.compile(r"\b(shutdown|reboot|poweroff)\b", re.I), "system_power"),
	(re.compile(r"\breg\s+delete\s+hklm\b", re.I), "registry_system"),
	# 远程执行：curl|sh / wget|sh / iwr|iex（含空白与换行）
	(
		re.compile(r"(invoke-webrequest|iwr)\b.*\|\s*iex\b", re.I | re.S),
		"remote_exec",
	),
	(
		re.compile(r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", re.I | re.S),
		"remote_exec",
	),
	(
		re.compile(
			r"\b(ba)?sh\b[^|;]*(-c|--command)\b[^|;]*(\$\(|`)\s*(curl|wget)\b",
			re.I | re.S,
		),
		"remote_exec",
	),
	(re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;", re.I), "fork_bomb"),
	(
		re.compile(r"\bdd\b.*\bof\s*=\s*[/\\](?:\s|$)", re.I | re.S),
		"disk_wipe",
	),
	# Windows：del /s、rd /s、Remove-Item -Recurse 打根盘
	(
		re.compile(
			r"\b(del|erase)\b\s+/[a-z]*s[a-z]*.*(?:[a-z]:\\?|(?:[/\\])\s*$)",
			re.I | re.M,
		),
		"destructive_root_delete",
	),
	(
		re.compile(
			r"\b(rd|rmdir)\b\s+/[a-z]*s[a-z]*.*(?:[a-z]:\\?|(?:[/\\])\s*$)",
			re.I | re.M,
		),
		"destructive_root_delete",
	),
	(
		re.compile(
			r"\bremove-item\b.*-(?:recurse|r)\b.*(?:[a-z]:\\|/|\\\\)",
			re.I | re.S,
		),
		"destructive_root_delete",
	),
	# PowerShell 编码绕过 / 下载执行
	(
		re.compile(
			r"\b(powershell|pwsh)\b.*\s-([Ee]nc|[Ee]ncoded[Cc]ommand)\b",
			re.I,
		),
		"encoded_powershell",
	),
	(
		re.compile(r"\bcertutil\b.*\s-decode\b", re.I),
		"certutil_decode",
	),
	(
		re.compile(r"\b(invoke-expression|iex)\b", re.I),
		"remote_exec",
	),
	# UNC 路径上的破坏性操作
	(
		re.compile(r"\b(rm|del|rd|rmdir|remove-item)\b.*\\\\[^\\\s]", re.I),
		"unc_destructive",
	),
)

# T7 种子数据：内置只读白名单，仅用于生成默认前缀规则（匹配统一走前缀规则引擎）。
_READONLY_BASES = frozenset(
	{
		"echo",
		"pwd",
		"cd",
		"dir",
		"ls",
		"ll",
		"la",
		"cat",
		"type",
		"head",
		"tail",
		"wc",
		"whoami",
		"hostname",
		"uname",
		"date",
		"time",
		"which",
		"where",
		"where.exe",
		"rg",
		"ripgrep",
		"grep",
		"findstr",
		"git",
		"npm",
		"pnpm",
		"yarn",
		"pip",
		"pip3",
		"python",
		"python3",
		"py",
		"node",
		"cargo",
		"go",
		"dotnet",
		"pytest",
		"tsc",
		"eslint",
	}
)

# 这些基命令只有带「只读」子命令才放行；裸跑或写操作不进白名单。
_READONLY_SUBCOMMANDS: dict[str, frozenset[str]] = {
	"git": frozenset(
		{
			"status",
			"log",
			"diff",
			"show",
			"branch",
			"tag",
			"remote",
			"rev-parse",
			"describe",
			"ls-files",
			"ls-tree",
			"blame",
			"shortlog",
			"version",
			"help",
		}
	),
	"npm": frozenset({"ls", "list", "view", "info", "outdated", "-v", "--version"}),
	"pnpm": frozenset({"ls", "list", "view", "info", "outdated", "why", "-v", "--version"}),
	"yarn": frozenset({"list", "info", "why", "version", "-v", "--version"}),
	"pip": frozenset({"list", "show", "freeze", "check", "--version", "-V"}),
	"pip3": frozenset({"list", "show", "freeze", "check", "--version", "-V"}),
	"python": frozenset({"-V", "--version"}),
	"python3": frozenset({"-V", "--version"}),
	"py": frozenset({"-V", "--version"}),
	"node": frozenset({"-v", "--version"}),
	"cargo": frozenset({"tree", "metadata", "version", "--version"}),
	"go": frozenset({"version", "env", "list", "doc"}),
	"dotnet": frozenset({"--info", "--list-sdks", "--list-runtimes"}),
}

# ---------------------------------------------------------------------------
# T7 bash 前缀规则引擎
# ---------------------------------------------------------------------------
# 规则条目：{program(basename), prefix: [tokens], decision: allow|ask|deny,
#            match_examples?, not_match_examples?}
# - 按 program(basename) 索引，prefix 逐 token 匹配（大小写不敏感）；
#   token 支持 `a|b` 备选与 `*` 单 token 通配。
# - match/not_match 示例加载期自校验：与规则矛盾 → 拒载该规则并报错。
# - 多条规则命中 → 最严胜出（allow < ask < deny）。
# - allow 只在 bash_mode=default / worker 只读沙箱生效（T26 决策，见 policy.py）；
#   ask/deny 在所有模式收紧。
# - 命令首 token 为绝对/相对路径时按 basename 归一（host_executable 白名单语义：
#   `C:\...\git.exe status` 与 `git status` 同判）。

BASH_RULES_DIRNAME = ".xeyo"
BASH_RULES_JSON = "bash_rules.json"
BASH_RULES_TOML = "bash_rules.toml"
_SEVERITY: dict[str, int] = {"allow": 0, "ask": 1, "deny": 2}


@dataclass(frozen=True)
class BashRule:
	"""单条 bash 前缀规则（已校验）。"""

	name: str
	program: str
	prefix: tuple[str, ...]
	decision: str
	source: str


class BashRuleset:
	"""默认 + 工作区规则集，附带加载期自校验错误。"""

	def __init__(self, rules: list[BashRule], errors: list[str]) -> None:
		self.rules = tuple(rules)
		self.errors = tuple(errors)
		index: dict[str, tuple[BashRule, ...]] = {}
		for r in self.rules:
			index[r.program] = index.get(r.program, ()) + (r,)
		self._index = index

	def rules_for(self, program: str) -> tuple[BashRule, ...]:
		return self._index.get(program, ())


def _build_default_rule_dicts() -> tuple[dict, ...]:
	"""内置只读白名单 → 默认规则（全部 allow）。"""
	rules: list[dict] = []
	for base in sorted(_READONLY_BASES):
		subs = _READONLY_SUBCOMMANDS.get(base)
		if subs is None:
			rules.append(
				{"name": f"builtin-{base}", "program": base, "prefix": [], "decision": "allow"}
			)
		elif base in {"python", "python3", "py", "node"}:
			# 解释器仅版本探测；-c/-e 任意代码不自动放行。
			rules.append(
				{
					"name": f"builtin-{base}-version",
					"program": base,
					"prefix": ["-V|--version"],
					"decision": "allow",
				}
			)
		else:
			for sub in sorted(subs):
				rules.append(
					{
						"name": f"builtin-{base}-{sub}",
						"program": base,
						"prefix": [sub],
						"decision": "allow",
					}
				)
				if base == "git":
					# 形如 git -C <path> <sub> / git -c <k=v> <sub>
					rules.append(
						{
							"name": f"builtin-git-opt-{sub}",
							"program": "git",
							"prefix": ["-c", "*", sub],
							"decision": "allow",
						}
					)
	return tuple(rules)


def _program_of_token(tok: str) -> str:
	"""命令首 token → 程序 basename（去引号/路径/.exe，小写）。"""
	t = (tok or "").strip().strip("\"'")
	t = t.lower()
	if t.endswith(".exe"):
		t = t[:-4]
	if "/" in t or "\\" in t:
		t = re.split(r"[\\/]+", t)[-1]
	return t


def _token_matches(rule_tok: str, cmd_tok: str) -> bool:
	for alt in rule_tok.split("|"):
		alt = alt.strip()
		if not alt:
			continue
		if alt == "*":
			return True
		if alt.lower() == cmd_tok.lower():
			return True
	return False


def _rule_matches_tokens(rule: BashRule, toks: list[str]) -> bool:
	if not toks or _program_of_token(toks[0]) != rule.program:
		return False
	rest = toks[1:]
	if len(rest) < len(rule.prefix):
		return False
	for i, rule_tok in enumerate(rule.prefix):
		if not _token_matches(rule_tok, rest[i]):
			return False
	return True


def _tokenize(command: str | None) -> list[str]:
	if not isinstance(command, str):
		return []
	text = _normalize_command(command)
	if not text:
		return []
	return text.split(" ")


def _as_str_list(value: object) -> list[str]:
	if isinstance(value, str):
		return [value] if value.strip() else []
	if isinstance(value, list):
		return [v for v in value if isinstance(v, str) and v.strip()]
	return []


def _validate_rule(raw: object, source: str, errors: list[str]) -> BashRule | None:
	"""校验单条规则；match/not_match 示例与规则矛盾 → 拒载该规则并报错。"""
	if not isinstance(raw, dict):
		errors.append(f"{source}: rule entry is not an object: {raw!r}")
		return None
	name = str(raw.get("name") or "").strip()
	program = str(raw.get("program") or "").strip()
	decision = str(raw.get("decision") or "").strip().lower()
	prefix_raw: object = raw.get("prefix") or []
	label = name or program or "?"
	if not program or _program_of_token(program) != program.lower():
		errors.append(
			f"{source}[{label}]: program must be a bare basename, got {program!r}"
		)
		return None
	if decision not in _SEVERITY:
		errors.append(
			f"{source}[{label}]: decision must be allow|ask|deny, got {decision!r}"
		)
		return None
	if isinstance(prefix_raw, str):
		prefix_raw = [prefix_raw]
	if not isinstance(prefix_raw, list) or not all(
		isinstance(t, str) and t.strip() for t in prefix_raw
	):
		errors.append(f"{source}[{label}]: prefix must be a list of non-empty tokens")
		return None
	for t in prefix_raw:
		if any(not alt.strip() for alt in t.split("|")):
			errors.append(f"{source}[{label}]: empty alternative in prefix token {t!r}")
			return None
	rule = BashRule(
		name=label,
		program=program.lower(),
		prefix=tuple(t.strip() for t in prefix_raw),
		decision=decision,
		source=source,
	)
	bad = False
	for ex in _as_str_list(raw.get("match_examples")):
		if not _rule_matches_tokens(rule, _tokenize(ex)):
			errors.append(
				f"{source}[{label}]: match_example does not match this rule: {ex!r}"
			)
			bad = True
	for ex in _as_str_list(raw.get("not_match_examples")):
		if _rule_matches_tokens(rule, _tokenize(ex)):
			errors.append(
				f"{source}[{label}]: not_match_example matches this rule: {ex!r}"
			)
			bad = True
	if bad:
		return None
	return rule


_DEFAULT_RULESET: BashRuleset | None = None


def _default_ruleset() -> BashRuleset:
	global _DEFAULT_RULESET
	if _DEFAULT_RULESET is None:
		errors: list[str] = []
		rules = [
			r
			for r in (
				_validate_rule(item, "builtin", errors)
				for item in _build_default_rule_dicts()
			)
			if r is not None
		]
		_DEFAULT_RULESET = BashRuleset(rules, errors)
	return _DEFAULT_RULESET


def _report_invalid_rules(source: str, why: str) -> BashRuleset:
	"""坏规则文件：报错 + 审计，回退内置默认规则（不静默丢白名单）。"""
	logging.getLogger(__name__).error(
		"invalid bash rules file %s: %s; falling back to builtin rules", source, why
	)
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			"bash_rules.invalid",
			path=source,
			error=why,
			action="builtin_rules_only",
		)
	except Exception:  # 审计故障不影响回退
		logging.getLogger(__name__).debug("bash_rules.invalid audit failed", exc_info=True)
	base = _default_ruleset()
	return BashRuleset(list(base.rules), list(base.errors) + [f"{source}: {why}"])


@lru_cache(maxsize=32)
def _load_rules_file_cached(path_key: str, mtime_ns: int) -> BashRuleset:
	_ = mtime_ns
	path = Path(path_key)
	source = str(path)
	try:
		text = path.read_text(encoding="utf-8")
	except (OSError, UnicodeError) as e:
		return _report_invalid_rules(source, f"unreadable: {e}")
	try:
		if path.suffix.lower() == ".toml":
			raw: object = tomllib.loads(text)
		else:
			raw = json.loads(text)
	except ValueError as e:  # JSONDecodeError / TOMLDecodeError 均为 ValueError
		return _report_invalid_rules(source, f"parse error: {e}")
	if isinstance(raw, list):
		raw_rules: object = raw
	elif isinstance(raw, dict):
		raw_rules = raw.get("rules")
	else:
		raw_rules = None
	if not isinstance(raw_rules, list):
		return _report_invalid_rules(source, "no 'rules' array found")
	errors: list[str] = []
	rules: list[BashRule] = []
	# T7：工作区规则与内置默认规则**合并**（不是替换）——追加 allow 放行面、
	# 叠加 ask/deny 收紧；冲突由最严胜出聚合裁决。
	for item in _build_default_rule_dicts():
		rule = _validate_rule(item, "builtin", errors)
		if rule is not None:
			rules.append(rule)
	for item in raw_rules:
		rule = _validate_rule(item, source, errors)
		if rule is not None:
			rules.append(rule)
	return BashRuleset(rules, errors)


def _rules_file(cwd: str | None) -> Path | None:
	if not cwd:
		return None
	try:
		root = Path(os.path.abspath(os.path.expanduser(cwd)))
	except (OSError, ValueError):
		return None
	base = root / BASH_RULES_DIRNAME
	for name in (BASH_RULES_JSON, BASH_RULES_TOML):
		path = base / name
		try:
			if path.is_file():
				return path
		except OSError:
			continue
	return None


def _effective_cwd(cwd: str | None) -> str | None:
	if cwd:
		return cwd
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		if ctx is not None and ctx.cwd:
			return ctx.cwd
	except Exception:
		pass
	return None


def load_bash_rules(cwd: str | None = None) -> BashRuleset:
	"""加载规则：内置默认 + `<cwd>/.xeyo/bash_rules.(json|toml)`（mtime 缓存）。"""
	path = _rules_file(cwd)
	if path is None:
		return _default_ruleset()
	try:
		mtime_ns = path.stat().st_mtime_ns
	except OSError:
		return _default_ruleset()
	return _load_rules_file_cached(str(path), mtime_ns)


def clear_bash_rules_cache() -> None:
	"""测试用：清空规则文件缓存。"""
	_load_rules_file_cached.cache_clear()


def bash_rule_decision(command: str | None, *, cwd: str | None = None) -> str | None:
	"""前缀规则判定：命中多条取最严（allow<ask<deny）；未命中/空命令返回 None。

	多行命令按物理行逐条判定并取最严结果——防止「首行蹭 allow、
	次行跑任意脚本」的换行绕过（`ls -la\\npython -c ...` 之类）。
	"""
	if not isinstance(command, str):
		return None
	lines = [ln for ln in re.split(r"[\r\n]+", command) if ln.strip()]
	if not lines:
		return None
	ruleset = load_bash_rules(_effective_cwd(cwd))
	best: str | None = None
	for ln in lines:
		toks = _tokenize(ln)
		if not toks:
			continue
		for rule in ruleset.rules_for(_program_of_token(toks[0])):
			if not _rule_matches_tokens(rule, toks):
				continue
			if best is None or _SEVERITY[rule.decision] > _SEVERITY[best]:
				best = rule.decision
	return best


def bash_rule_ask_deny(command: str | None, *, cwd: str | None = None) -> str | None:
	"""规则收紧判定：'ask' | 'deny' | None（allow 不在此，走只读白名单门禁）。"""
	decision = bash_rule_decision(command, cwd=cwd)
	return decision if decision in ("ask", "deny") else None

_COMPOSITE_RX = re.compile(r"[|;&`\n\r]|\$\(|&&|\|\|")
_SECRET_TOKEN_RX = re.compile(
	r"(?:^|[\\/\s\"'=])("
	r"\.env(?:\.[A-Za-z0-9_-]+)?|"
	r"\.gitconfig|"
	r"id_rsa|id_ed25519|id_ecdsa|"
	r"credentials\.json|credentials|"
	r"\.npmrc|\.pypirc|"
	r"[^\s\"']+\.(?:pem|key|p12|pfx)|"
	r"\.ssh(?:[/\\][^\s\"']*)?"
	r")(?:$|[\s\"'])",
	re.I,
)
_SECRET_READ_CMD_RX = re.compile(
	r"\b(?:type|cat|more|less|Get-Content|gc|Get-Item|gi)\b",
	re.I,
)


def _normalize_command(command: str) -> str:
	"""压空白 / 统一换行，降低简单空格绕过。"""
	t = command.replace("\r\n", "\n").replace("\r", "\n")
	t = re.sub(r"[ \t\f\v]+", " ", t)
	return t.strip()


def bash_deny_reason(command: str | None) -> str | None:
	"""返回拒绝原因；允许则 None。空命令交给工具自己报错。"""
	if not isinstance(command, str):
		return None
	text = _normalize_command(command)
	if not text:
		return None
	for pattern, reason in _DENY_RULES:
		if pattern.search(text):
			return reason
	return None


def bash_deny_extra(command: str, patterns: list[str] | None) -> str | None:
	"""仓库策略 deny_commands：子串/简单正则命中即 deny。"""
	if not patterns:
		return None
	text = _normalize_command(command).lower()
	for raw in patterns:
		pat = (raw or "").strip()
		if not pat:
			continue
		try:
			if re.search(pat, text, re.I | re.S):
				return "policy_deny_command"
		except re.error:
			if pat.lower() in text:
				return "policy_deny_command"
	return None


def bash_secret_read_reason(command: str | None) -> str | None:
	"""命令提及密钥/凭据路径时返回原因（读或任意引用均需确认）。"""
	if not isinstance(command, str):
		return None
	text = _normalize_command(command)
	if not text:
		return None
	if _SECRET_TOKEN_RX.search(text):
		return "bash_secret_read"
	_ = _SECRET_READ_CMD_RX  # 保留：后续可收紧为「仅读命令」
	return None


def bash_command_is_composite(command: str | None) -> bool:
	"""命令是否含组合/多语句/写重定向结构。

	G29: 组合命令(``&&``/``;``/``|``/换行/``$(``/反引号等)不得用「前缀 token」
	的 always-allow grant 静默放行——``git status && curl x|sh`` 不能蹭
	``git status`` 的授权;此类命令每次仍需确认。
	"""
	if not isinstance(command, str):
		return True
	text = _normalize_command(command)
	if not text:
		return True
	if _COMPOSITE_RX.search(text):
		return True
	if re.search(r"(?:>>?|2>>?|&>>)", text):
		return True
	return False


def bash_readonly_allow(command: str | None, *, cwd: str | None = None) -> bool:
	"""短只读命令才自动放行；管道/复合/解释器任意脚本一律 False。

	T7：放行面由前缀规则驱动（默认规则=原只读白名单迁移），工作区
	`.xeyo/bash_rules.(json|toml)` 可追加 allow 规则；生效范围不变
	（仅 bash_mode=default / worker 只读沙箱，T26）。
	"""
	if not isinstance(command, str):
		return False
	text = _normalize_command(command)
	if not text or _COMPOSITE_RX.search(text):
		return False
	# 重定向写出 → 非只读
	if re.search(r"(?:>>?|2>>?|&>>)", text):
		return False
	if bash_secret_read_reason(text):
		return False
	return bash_rule_decision(text, cwd=cwd) == "allow"


def is_remote_session(session_id: str | None) -> bool:
	"""微信 / 文件助手等远程会话：Bash 策略更严。"""
	sid = (session_id or "").strip().lower()
	return sid.startswith("ilink:") or sid.startswith("filehelper:")
