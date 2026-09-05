"""子 Agent 写路径 scope 硬门禁（contextvars）。

- ``None``：主会话，不按 scope 限制（仍走工作区 / 策略门禁）。
- ``()``：子 Agent 未声明 scope → 禁止 Write/Edit。
- 非空：写路径必须落在任一 scope 前缀下（相对工作区根或绝对路径）。
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Iterator, Sequence

_write_scope_ctx: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
	"xeyo_write_scope", default=None
)


def get_write_scope() -> tuple[str, ...] | None:
	return _write_scope_ctx.get()


def set_write_scope(paths: Sequence[str] | None) -> None:
	if paths is None:
		_write_scope_ctx.set(None)
		return
	cleaned = tuple(str(p).strip() for p in paths if str(p).strip())
	_write_scope_ctx.set(cleaned)


@contextmanager
def write_scope(paths: Sequence[str] | None) -> Iterator[None]:
	"""进入子 Agent 写 scope；``None`` 清除限制，空序列表示只读工人。"""
	token = _write_scope_ctx.set(
		None
		if paths is None
		else tuple(str(p).strip() for p in paths if str(p).strip())
	)
	try:
		yield
	finally:
		_write_scope_ctx.reset(token)


def normalize_worker_scope(
	raw: Sequence[str] | None,
	*,
	cwd: str,
) -> tuple[list[str], bool, str]:
	"""规范化工人 scope。

	返回 ``(paths, read_only, reason)``：
	- 过宽（``.`` / 仓根 / 盘符根）→ 空 paths + read_only + ``scope_too_broad``
	- 绝对路径尽量收束为相对 cwd 的前缀
	"""
	from permissions.filesystem import expand_to_abs, normalize_case_for_comparison

	root = os.path.abspath(os.path.expanduser(cwd or "."))
	root_cmp = normalize_case_for_comparison(os.path.realpath(root))
	out: list[str] = []
	broad = False
	for item in raw or []:
		s = str(item).strip()
		if not s:
			continue
		norm = s.replace("\\", "/").rstrip("/")
		if norm in (".", "./", "") or norm == root.replace("\\", "/").rstrip("/"):
			broad = True
			continue
		# 盘符根：C: / C:/ / /
		if len(norm) <= 3 and (
			norm in ("/", "\\")
			or (len(norm) >= 2 and norm[1] == ":" and (len(norm) == 2 or norm[2:] in ("", "/")))
		):
			broad = True
			continue
		try:
			abs_p = os.path.realpath(expand_to_abs(s, cwd=root))
			abs_cmp = normalize_case_for_comparison(abs_p)
		except OSError:
			abs_p = expand_to_abs(s, cwd=root)
			abs_cmp = normalize_case_for_comparison(abs_p)
		if abs_cmp == root_cmp:
			broad = True
			continue
		# 收束到相对路径（仍在仓内）
		try:
			rel = os.path.relpath(abs_p, root)
		except ValueError:
			rel = s
		if rel.startswith("..") or os.path.isabs(rel):
			# 仓外：当作无效，不扩大权限
			broad = True
			continue
		cleaned = rel.replace("\\", "/").strip("/")
		if cleaned and cleaned not in out:
			out.append(cleaned)
	if broad and not out:
		return [], True, "scope_too_broad"
	if not out:
		return [], True, ""
	return out, False, ("scope_too_broad" if broad else "")


def path_in_write_scope(
	path: str,
	*,
	cwd: str,
	scope: Sequence[str] | None = None,
) -> bool:
	"""路径是否落在当前（或显式）写 scope 内。

	``scope is None`` 且 context 也为 None → True（主会话）。
	空 scope → False。
	"""
	active = list(scope) if scope is not None else get_write_scope()
	if active is None:
		return True
	if not active:
		return False
	from permissions.filesystem import expand_to_abs, normalize_case_for_comparison

	abs_path = normalize_case_for_comparison(
		os.path.realpath(expand_to_abs(path, cwd=cwd))
	)
	root = os.path.abspath(os.path.expanduser(cwd or "."))
	for raw in active:
		raw_s = str(raw).strip()
		if not raw_s:
			continue
		prefix = expand_to_abs(raw_s, cwd=root)
		# 目录前缀：文件或其子路径
		try:
			pref = normalize_case_for_comparison(os.path.realpath(prefix))
		except OSError:
			pref = normalize_case_for_comparison(prefix)
		if abs_path == pref or abs_path.startswith(pref + os.sep):
			return True
		# 也认未创建目录的逻辑前缀
		if abs_path.startswith(
			normalize_case_for_comparison(prefix).rstrip("\\/") + os.sep
		) or abs_path == normalize_case_for_comparison(prefix):
			return True
	return False


def write_scope_deny_reason(path: str, *, cwd: str) -> str | None:
	"""若当前写 scope 禁止该路径，返回原因码；否则 None。"""
	scope = get_write_scope()
	if scope is None:
		return None
	if not scope:
		return "write_scope_empty"
	if not path_in_write_scope(path, cwd=cwd, scope=scope):
		return "write_scope_denied"
	return None
