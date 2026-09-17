"""Git — read-only workspace git (reuses server.workspace_git)."""

from __future__ import annotations

import os
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.git_tool.prompt import DESCRIPTION, GIT_TOOL_NAME, WRITE_REJECT

_READ_ACTIONS = frozenset({"status", "log", "branches", "diff", "summary"})
_WRITE_ACTIONS = frozenset(
	{"commit", "push", "add", "reset", "checkout", "merge", "rebase", "pull"}
)
# 与 engine.compact.MAX_TOOL_RESULT_CHARS 对齐。
_OUT_CAP = 16_000
_STATUS_PATH_CAP = 80


class GitTool:
	name = GIT_TOOL_NAME
	max_result_size_chars = _OUT_CAP

	def __init__(self, *, cwd: str = ".") -> None:
		self._cwd = os.path.abspath(os.path.expanduser(cwd or "."))

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"required": ["action"],
				"properties": {
					"action": {
						"type": "string",
						"enum": ["summary", "status", "log", "branches", "diff"],
						"description": (
							"Read-only git action. summary returns a quick overview; "
							"dirty repositories also list symbols hit by changed lines. "
							"Write operations are unsupported."
						),
					},
					"path": {
						"type": "string",
						"description": "Relative file path. Required for action=diff.",
					},
					"limit": {
						"type": "integer",
						"description": "Max commits for action=log. Default 20, max 100.",
					},
				},
				"additionalProperties": False,
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = input or {}
		action = str(raw.get("action") or "").strip().lower()
		if not action:
			return ToolResult(content="action is required", is_error=True)
		if action in _WRITE_ACTIONS or action not in _READ_ACTIONS:
			return ToolResult(content=WRITE_REJECT, is_error=True)

		from server.workspace_git import (
			GitBinaryMissing,
			GitError,
			read_changed_hunks,
			read_file_diff,
			read_git_branches,
			read_git_log,
			read_git_status,
		)

		try:
			# workspace_git 的 read_* 都是同步 subprocess.run，大仓库 status/log
			# 可达秒级——必须挪线程，否则事件循环（所有会话）被冻结。
			import asyncio

			if action == "summary":
				# 三个只读 git 子进程相互独立，并行跑（原先串行叠加 ~120ms）；
				# 干净仓库多跑一次廉价 diff，换取恒定的一轮往返。
				st, log, ch = await asyncio.gather(
					asyncio.to_thread(read_git_status, self._cwd),
					asyncio.to_thread(read_git_log, self._cwd, limit=3),
					asyncio.to_thread(read_changed_hunks, self._cwd),
				)
				touched_section = ""
				if st.get("repo") and not st.get("clean"):
					try:
						from codeindex.changes import (
							format_touched_section,
							symbols_touched_by_hunks,
						)

						# 符号解析是文件 IO + AST，冷缓存 ~100ms——同样挪线程，
						# 否则冻结事件循环（所有会话）。
						touched = await asyncio.to_thread(
							symbols_touched_by_hunks,
							self._cwd,
							ch.get("hunks") or {},
						)
						touched_section = format_touched_section(
							touched, untracked=list(ch.get("untracked") or [])
						)
					except Exception:
						touched_section = ""
				return ToolResult(
					content=_cap(_format_summary(st, log, touched_section=touched_section))
				)
			if action == "status":
				payload = await asyncio.to_thread(read_git_status, self._cwd)
				return ToolResult(content=_cap(_format_status(payload)))
			if action == "log":
				try:
					limit = int(raw.get("limit") or 20)
				except (TypeError, ValueError):
					limit = 20
				limit = max(1, min(100, limit))
				payload = await asyncio.to_thread(read_git_log, self._cwd, limit=limit)
				return ToolResult(content=_cap(_format_log(payload)))
			if action == "branches":
				payload = await asyncio.to_thread(read_git_branches, self._cwd)
				return ToolResult(content=_cap(_format_branches(payload)))
			path = str(raw.get("path") or "").strip()
			if not path:
				return ToolResult(
					content="path is required for action=diff",
					is_error=True,
				)
			payload = await asyncio.to_thread(read_file_diff, self._cwd, path)
			return ToolResult(content=_cap(_maybe_compact("diff", _format_diff(payload))))
		except GitBinaryMissing as e:
			return ToolResult(content=str(e), is_error=True)
		except FileNotFoundError as e:
			return ToolResult(content=str(e), is_error=True)
		except PermissionError as e:
			return ToolResult(content=str(e), is_error=True)
		except GitError as e:
			return ToolResult(content=str(e)[:500], is_error=True)
		except Exception as e:  # noqa: BLE001
			return ToolResult(
				content=f"Git failed: {type(e).__name__}: {e}"[:500],
				is_error=True,
			)


def _maybe_compact(action: str, text: str) -> str:
	"""单文件 diff 复用 bash 的语义压缩（剥上下文行，保留全部 hunk/±行）。

	只用于 diff：`_compact_git` 对 status/log 另有 30 样本 / 40 commit 的硬上限，
	会覆盖本工具自己的 `_STATUS_PATH_CAP=80` 与 `limit<=100` 语义，造成信息回退。
	不足 4000 字符时原样返回，失败也不丢错误信号。
	"""
	try:
		from tools.bash_tool.cmd_compact import compact_command_output

		return compact_command_output(f"git {action}", text)
	except Exception:  # noqa: BLE001
		return text


def _cap(text: str) -> str:
	if len(text) <= _OUT_CAP:
		return text
	head = text[:10_000]
	tail = text[-4_000:]
	return head + "\n\n… [middle truncated] …\n\n" + tail


def _format_summary(
	status: dict[str, Any],
	log: dict[str, Any],
	*,
	touched_section: str = "",
) -> str:
	if not status.get("repo"):
		return "Not a git repository."
	counts = status.get("counts") or {}
	lines = [
		f"branch: {status.get('branch') or '?'}",
		(
			f"dirty: staged={counts.get('staged', 0)} "
			f"unstaged={counts.get('unstaged', 0)} "
			f"untracked={counts.get('untracked', 0)}"
		),
	]
	if status.get("clean"):
		lines.append("clean (no changes)")
	commits = log.get("commits") or []
	if commits:
		lines.append("recent:")
		for c in commits[:3]:
			if not isinstance(c, dict):
				continue
			lines.append(
				f"  {c.get('short') or '?'} {c.get('date') or ''} "
				f"{c.get('subject') or ''}".rstrip()
			)
	if touched_section:
		lines.append(touched_section)
	return "\n".join(lines)


def _format_status(payload: dict[str, Any]) -> str:
	if not payload.get("repo"):
		return "Not a git repository."
	lines = [
		f"branch: {payload.get('branch') or '?'}",
		f"cwd: {payload.get('cwd') or ''}",
	]
	for label, key in (
		("staged", "staged"),
		("unstaged", "unstaged"),
		("untracked", "untracked"),
	):
		items = payload.get(key) or []
		if not items:
			continue
		lines.append(f"{label}:")
		shown = 0
		for it in items:
			if shown >= _STATUS_PATH_CAP:
				lines.append(f"  … +{len(items) - shown} more")
				break
			if isinstance(it, dict):
				lines.append(
					f"  {it.get('status') or ''} {it.get('path') or ''}".rstrip()
				)
			else:
				lines.append(f"  {it}")
			shown += 1
	if len(lines) <= 2:
		lines.append("clean (no changes)")
	return "\n".join(lines)


def _format_log(payload: dict[str, Any]) -> str:
	if not payload.get("repo"):
		return "Not a git repository."
	commits = payload.get("commits") or []
	if not commits:
		return "No commits."
	lines = []
	for c in commits:
		if not isinstance(c, dict):
			continue
		lines.append(
			f"{c.get('short') or c.get('hash') or '?'} "
			f"{c.get('date') or ''} {c.get('subject') or ''}".rstrip()
		)
	return "\n".join(lines)


def _format_branches(payload: dict[str, Any]) -> str:
	if not payload.get("repo"):
		return "Not a git repository."
	cur = payload.get("current")
	branches = payload.get("branches") or []
	lines = [f"current: {cur or '?'}"]
	for b in branches:
		mark = "*" if b == cur else " "
		lines.append(f"{mark} {b}")
	return "\n".join(lines)


def _format_diff(payload: dict[str, Any]) -> str:
	if not payload.get("repo"):
		return "Not a git repository."
	kind = payload.get("kind") or "none"
	path = payload.get("path") or ""
	diff = payload.get("diff")
	if kind == "binary":
		return f"{path}: binary (no text diff)"
	if kind == "unchanged" or not diff:
		return f"{path}: unchanged"
	return f"{path} ({kind}):\n{diff}"
