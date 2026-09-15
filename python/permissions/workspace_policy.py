"""仓库级策略文件 ``.xeyo-policy.json``。

缺省文件 = 对外安装默认：``bash=ask`` / ``write=ask`` / ``remote_bash=ask``。
本机自用可在仓库写 ``"bash":"default"`` 恢复只读白名单自动放行。
Agent 对策略文件本身不可写（由 policy 硬拒绝）。

权限单向性（T26）：``write`` 的 ``ask``/``always`` 只会**收紧**（强制每写确认）；
``risk``/``never``/``allow`` 不得把用户更严的审批模式放宽为自动放行——
放宽只能走用户侧（env / grant store / preset），仓库策略不再反客为主。
坏文件（解析失败）一律回退收紧默认并记审计（T25 fail-closed）。
"""

from __future__ import annotations
import logging

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

POLICY_FILENAME = ".xeyo-policy.json"
_BASH_MODES = frozenset({"default", "ask", "allow", "deny"})
_REMOTE_BASH_MODES = frozenset({"ask", "deny"})
_WRITE_MODES = frozenset({"ask", "always", "allow", "never", "risk"})
_BASH_ROUTING_MODES = frozenset({"auto", "off"})
#: Phase 2 渐进强制：同会话同命令形状重复命中次数上限（UI 推荐值/上限）。
BASH_ESCALATE_RECOMMENDED = 3
BASH_ESCALATE_MAX = 5


@dataclass(frozen=True)
class WorkspacePolicy:
	"""解析后的仓库策略（不可变）。"""

	allowed_roots: tuple[str, ...] = ()
	bash: str = "default"
	write: str | None = "risk"
	deny_tools: tuple[str, ...] = ()
	deny_commands: tuple[str, ...] = ()
	remote_bash: str = "ask"
	bash_job_memory_mb: int | None = None
	#: 43 号：Bash→专用工具 透明路由开关（"auto"=启用；"off"=关，保留 L2 错误重定向）。
	bash_routing: str = "off"
	#: 43 号 Phase 2：同会话同命令形状重复命中 ≥ 该次数后放行 bash（0=关闭，默认）。
	#: 上限 BASH_ESCALATE_MAX；推荐 BASH_ESCALATE_RECOMMENDED。
	bash_escalate: int = 0
	source_path: str | None = None
	#: 非 None 表示文件存在但解析失败（T25 fail-closed：策略不生效，默认收紧）。
	parse_error: str | None = None

	@property
	def exists(self) -> bool:
		"""策略文件存在**且解析成功**；坏文件不算生效策略（T25）。"""
		return bool(self.source_path) and self.parse_error is None


def _as_str_tuple(value: Any) -> tuple[str, ...]:
	if not isinstance(value, list):
		return ()
	out: list[str] = []
	for item in value:
		s = str(item).strip()
		if s:
			out.append(s)
	return tuple(out)


def _normalize(raw: dict[str, Any], *, source: str | None) -> WorkspacePolicy:
	bash = str(raw.get("bash") or "default").strip().lower()
	if bash not in _BASH_MODES:
		bash = "default"
	remote_bash = str(raw.get("remote_bash") or "ask").strip().lower()
	if remote_bash not in _REMOTE_BASH_MODES:
		remote_bash = "ask"
	write_raw = raw.get("write")
	if write_raw is None:
		write: str | None = "risk"
	else:
		write = str(write_raw).strip().lower()
		if write not in _WRITE_MODES:
			write = "risk"
	mem = raw.get("bash_job_memory_mb")
	mem_i: int | None
	try:
		mem_i = int(mem) if mem is not None and str(mem).strip() != "" else None
	except (TypeError, ValueError):
		mem_i = None
	if mem_i is not None and mem_i < 64:
		mem_i = 64
	bash_routing = str(raw.get("bash_routing") or "off").strip().lower()
	if bash_routing not in _BASH_ROUTING_MODES:
		bash_routing = "off"
	esc_raw = raw.get("bash_escalate")
	try:
		esc = int(esc_raw) if esc_raw is not None and str(esc_raw).strip() != "" else 0
	except (TypeError, ValueError):
		esc = 0
	esc = max(0, min(BASH_ESCALATE_MAX, esc))
	return WorkspacePolicy(
		allowed_roots=_as_str_tuple(raw.get("allowed_roots")),
		bash=bash,
		write=write,
		deny_tools=_as_str_tuple(raw.get("deny_tools")),
		deny_commands=_as_str_tuple(raw.get("deny_commands")),
		remote_bash=remote_bash,
		bash_job_memory_mb=mem_i,
		bash_routing=bash_routing,
		bash_escalate=esc,
		source_path=source,
	)


def _invalid_policy(path: Path, why: str) -> WorkspacePolicy:
	"""坏策略文件（T25 fail-closed）。

	回退收紧默认（bash/write/remote_bash 全 ask）——宁可多问，不静默丢 deny。
	不缓存旧值复活（与 settings 的 keep-last-good 相反：policy 失效方向必须收紧），
	但必须可见：error 日志 + 审计事件（policy.invalid）。
	"""
	import logging

	logging.getLogger(__name__).error(
		"invalid %s at %s: %s; falling back to ask-tight defaults",
		POLICY_FILENAME,
		path,
		why,
	)
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			"policy.invalid",
			path=str(path),
			error=why,
			action="defaults_applied_bash_ask_write_ask",
		)
	except Exception:  # 审计故障不得影响策略回退
		logging.getLogger(__name__).debug("policy.invalid audit failed", exc_info=True)
	# 坏文件 = 比「无文件缺省」更严：显式 ask/ask（T25 fail-closed，宁可多问）。
	# 缺省 bash=default / write=risk 只适用于「无策略文件」；坏文件不得落在宽松档。
	return WorkspacePolicy(
		source_path=str(path),
		parse_error=why,
		bash="ask",
		write="ask",
		remote_bash="ask",
	)


@lru_cache(maxsize=64)
def _load_cached(cwd_key: str, mtime_ns: int) -> WorkspacePolicy:
	_ = mtime_ns
	path = Path(cwd_key) / POLICY_FILENAME
	if not path.is_file():
		return WorkspacePolicy()
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, UnicodeError, json.JSONDecodeError) as e:
		return _invalid_policy(path, f"unreadable: {e}")
	if not isinstance(raw, dict):
		return _invalid_policy(path, "not a JSON object")
	return _normalize(raw, source=str(path))


def load_workspace_policy(cwd: str | None) -> WorkspacePolicy:
	"""从工作区根加载策略；文件缺失返回默认。"""
	root = os.path.abspath(os.path.expanduser(cwd or "."))
	path = Path(root) / POLICY_FILENAME
	try:
		mtime_ns = path.stat().st_mtime_ns if path.is_file() else 0
	except OSError:
		mtime_ns = 0
	return _load_cached(root, mtime_ns)


def clear_policy_cache() -> None:
	"""测试用：清空策略缓存。"""
	_load_cached.cache_clear()


def write_bash_policy(
	cwd: str | None,
	*,
	bash_routing: str | None = None,
	bash_escalate: int | None = None,
) -> WorkspacePolicy:
	"""写回 ``.xeyo-policy.json`` 的 bash 相关字段（保留其它字段），返回新策略。

	- bash_routing: 仅接受 "auto"/"off"，非法忽略；
	- bash_escalate: 夹到 [0, BASH_ESCALATE_MAX]。
	仅改传入字段；其余字段原样保留。
	"""
	root = os.path.abspath(os.path.expanduser(cwd or "."))
	path = Path(root) / POLICY_FILENAME
	data: dict[str, Any] = {}
	if path.is_file():
		try:
			raw = json.loads(path.read_text(encoding="utf-8"))
			if isinstance(raw, dict):
				data = raw
		except (OSError, UnicodeError, json.JSONDecodeError):
			data = {}
	if bash_routing is not None:
		br = str(bash_routing).strip().lower()
		if br in _BASH_ROUTING_MODES:
			data["bash_routing"] = br
	if bash_escalate is not None:
		try:
			esc = int(bash_escalate)
		except (TypeError, ValueError):
			esc = 0
		data["bash_escalate"] = max(0, min(BASH_ESCALATE_MAX, esc))
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
	)
	clear_policy_cache()
	return load_workspace_policy(cwd)


def resolve_allowed_roots(
	cwd: str,
	policy: WorkspacePolicy | None = None,
	*,
	extra: list[str] | None = None,
) -> list[str]:
	"""合并 cwd、策略 allowed_roots、会话 extra。"""
	root = os.path.abspath(os.path.expanduser(cwd or "."))
	pol = policy or load_workspace_policy(root)
	out: list[str] = [root]
	for item in pol.allowed_roots:
		p = item.strip()
		if not p or p == ".":
			continue
		abs_p = (
			os.path.abspath(os.path.expanduser(p))
			if os.path.isabs(p)
			else os.path.abspath(os.path.join(root, p))
		)
		if abs_p not in out:
			out.append(abs_p)
	for item in extra or []:
		abs_p = os.path.abspath(os.path.expanduser(item))
		if abs_p not in out:
			out.append(abs_p)
	return out


def is_policy_file(path: str, *, cwd: str | None = None) -> bool:
	"""路径是否为仓库策略文件（禁止 Agent 写入）。"""
	base = os.path.basename(os.path.abspath(os.path.expanduser(path))).lower()
	if base == POLICY_FILENAME.lower():
		return True
	# 相对 cwd 的同名也拦
	_ = cwd
	return False
