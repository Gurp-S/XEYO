"""XeyoUI — 桌面端 UI 控制（列对话 / 打开预览 / 打开面板 / 工具流程 / 跨对话后台发送）。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from engine.abort import AbortController
from permissions.filesystem import expand_to_abs, path_in_allowed_working_path
from permissions.policy import current_surface, is_gui_surface
from tools.base_tool import ToolResult
from tools.xeyo_ui_tool.prompt import DESCRIPTION, XEYO_UI_TOOL_NAME

_UI_PANELS = frozenset({"git", "terminal", "history", "map", "commits", "browser"})
_BROWSER_OPS = frozenset({"reload", "back", "fwd", "ext", "close"})
_ACTIONS = frozenset(
	{
		"list_sessions",
		"open_preview",
		"open_panel",
		"browser",
		"show_tool_flow",
		"send_to_session",
	}
)


def _as_bool(value: Any) -> bool | None:
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)) and value in (0, 1):
		return bool(value)
	if isinstance(value, str):
		s = value.strip().lower()
		if s in ("true", "1", "yes", "on"):
			return True
		if s in ("false", "0", "no", "off"):
			return False
	return None


class XeyoUITool:
	name = XEYO_UI_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		# 有界面副作用；ask/plan/侧聊不应放行。
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def __init__(self, cwd: str = ".") -> None:
		self._cwd = cwd
		self._session_id = ""

	def set_session_id(self, session_id: str) -> None:
		self._session_id = str(session_id or "").strip()

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"properties": {
					"action": {
						"type": "string",
						"enum": sorted(_ACTIONS),
						"description": "see tool description",
					},
					"path": {
						"type": "string",
						"description": "open_preview path",
					},
					"panel": {
						"type": "string",
						"enum": sorted(_UI_PANELS),
						"description": "open_panel target",
					},
					"url": {
						"type": "string",
						"description": "browser navigate (http/https)",
					},
					"op": {
						"type": "string",
						"enum": sorted(_BROWSER_OPS),
						"description": "browser op",
					},
					"show": {
						"type": "boolean",
						"description": "show_tool_flow",
					},
					"session_id": {
						"type": "string",
						"description": "send_to_session id",
					},
					"text": {
						"type": "string",
						"description": "send_to_session text",
					},
				},
				"required": ["action"],
				"additionalProperties": False,
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = input if isinstance(input, dict) else {}
		action = str(raw.get("action") or "").strip()
		if action == "list_sessions":
			return self._list_sessions()
		# T35：XeyoUI 仅 GUI 面可用。非 GUI 面（cli/cli_ts/remote）明确返回
		# 「需要 GUI」，不再假成功（避免脚本/终端误以为预览/面板已打开）。
		if not is_gui_surface():
			return ToolResult(
				content=(
					"XeyoUI 需要 GUI：桌面窗口或浏览器（npm run dev）才能执行 "
					f"{action or '(empty)'}。当前入口面为 {current_surface()}。"
				),
				is_error=True,
			)
		if action == "open_preview":
			return self._open_preview(raw)
		if action == "open_panel":
			return self._open_panel(raw)
		if action == "browser":
			return self._browser(raw)
		if action == "show_tool_flow":
			return self._show_tool_flow(raw)
		if action == "send_to_session":
			return self._send_to_session(raw)
		return ToolResult(
			content=f"Unknown action: {action or '(empty)'}",
			is_error=True,
		)

	def _list_sessions(self) -> ToolResult:
		from session.persistence import default_sessions_dir

		root = default_sessions_dir()
		rows: list[dict[str, Any]] = []
		busy_fn = None
		try:
			from server.deps import _pool

			busy_fn = _pool.is_busy
		except Exception:
			busy_fn = None
		if root.exists():
			entries: list[tuple[Path, os.stat_result]] = []
			for p in root.glob("*.jsonl"):
				try:
					st = p.stat()
				except OSError:
					continue
				entries.append((p, st))
			entries.sort(key=lambda t: t[1].st_mtime, reverse=True)
			for p, st in entries:
				sid = p.stem
				if sid.startswith("side-"):
					continue
				title = _peek_title(p) or sid
				busy = bool(busy_fn(sid)) if busy_fn else False
				rows.append(
					{
						"id": sid,
						"title": title,
						"updatedAt": int(st.st_mtime * 1000),
						"busy": busy,
						"current": bool(self._session_id and sid == self._session_id),
					}
				)
		if not rows:
			return ToolResult(content="No sessions found.")
		lines = ["Sessions:"]
		for r in rows:
			flags: list[str] = []
			if r["current"]:
				flags.append("current")
			if r["busy"]:
				flags.append("busy")
			flag_s = f" [{', '.join(flags)}]" if flags else ""
			lines.append(f"- {r['id']}: {r['title']}{flag_s}")
		lines.append("")
		lines.append(json.dumps(rows, ensure_ascii=False))
		return ToolResult(content="\n".join(lines))

	def _open_preview(self, raw: dict[str, Any]) -> ToolResult:
		path_raw = str(raw.get("path") or "").strip()
		if not path_raw:
			return ToolResult(content="path is required", is_error=True)
		path = expand_to_abs(path_raw, cwd=self._cwd)
		if not path_in_allowed_working_path(path, cwd=self._cwd):
			return ToolResult(
				content=f"path outside working directory: {path}",
				is_error=True,
			)
		if not os.path.isfile(path):
			return ToolResult(content=f"file not found: {path}", is_error=True)
		return ToolResult(
			content=f"Opening preview: {path}",
			ui={"action": "open_preview", "path": path},
		)

	def _open_panel(self, raw: dict[str, Any]) -> ToolResult:
		panel = str(raw.get("panel") or "").strip()
		if panel not in _UI_PANELS:
			return ToolResult(
				content=(
					"panel must be one of: git, terminal, history, map, commits, browser"
				),
				is_error=True,
			)
		return ToolResult(
			content=f"panel {panel}",
			ui={"action": "open_panel", "panel": panel},
		)

	def _browser(self, raw: dict[str, Any]) -> ToolResult:
		"""Preview browser: url → open+nav; op → control; bare → open."""
		url = str(raw.get("url") or "").strip()
		op = str(raw.get("op") or "").strip()
		if url:
			ok, err = _browser_url_ok(url)
			if not ok:
				return ToolResult(content=err or "bad url", is_error=True)
			return ToolResult(
				content=f"browser {url}",
				ui={"action": "browser", "url": url},
			)
		if op:
			if op not in _BROWSER_OPS:
				return ToolResult(
					content="op must be reload|back|fwd|ext|close",
					is_error=True,
				)
			return ToolResult(
				content=f"browser {op}",
				ui={"action": "browser", "op": op},
			)
		return ToolResult(
			content="browser open",
			ui={"action": "browser"},
		)

	def _show_tool_flow(self, raw: dict[str, Any]) -> ToolResult:
		if "show" not in raw:
			return ToolResult(
				content="show is required (true to open, false to close)",
				is_error=True,
			)
		show = _as_bool(raw.get("show"))
		if show is None:
			return ToolResult(
				content="show must be a boolean",
				is_error=True,
			)
		verb = "Showing" if show else "Hiding"
		return ToolResult(
			content=f"{verb} tool-flow map",
			ui={"action": "show_tool_flow", "show": show},
		)

	def _send_to_session(self, raw: dict[str, Any]) -> ToolResult:
		target = str(raw.get("session_id") or "").strip()
		text = str(raw.get("text") or "").strip()
		if not target or not text:
			return ToolResult(
				content="session_id and text are required",
				is_error=True,
			)
		if target.startswith("side-"):
			return ToolResult(
				content="cannot send to side-chat sessions",
				is_error=True,
			)
		if self._session_id and target == self._session_id:
			return ToolResult(
				content="cannot send_to_session to the current session",
				is_error=True,
			)
		try:
			from server.deps import _pool

			if _pool.is_busy(target):
				return ToolResult(
					content=f"target session is busy: {target}",
					is_error=True,
				)
		except Exception:
			pass
		return ToolResult(
			content=f"Queued background send to {target}",
			ui={
				"action": "send_to_session",
				"session_id": target,
				"text": text,
			},
		)


def _browser_url_ok(url: str) -> tuple[bool, str]:
	"""Allow http(s) or bare host; reject other schemes. Returns (ok, err)."""
	u = url.strip()
	if not u:
		return False, "url required"
	if len(u) > 2048:
		return False, "url too long"
	lower = u.lower()
	if "://" in lower:
		if not (lower.startswith("http://") or lower.startswith("https://")):
			return False, "url must be http/https"
		return True, ""
	if lower.startswith(("javascript:", "data:", "file:", "vbscript:")):
		return False, "url must be http/https"
	return True, ""


def _peek_title(path: Path) -> str:
	"""从 transcript 头几行猜标题（失败则空）。"""
	try:
		with path.open("r", encoding="utf-8") as fh:
			for i, line in enumerate(fh):
				if i > 40:
					break
				line = line.strip()
				if not line:
					continue
				try:
					row = json.loads(line)
				except Exception:
					continue
				if not isinstance(row, dict):
					continue
				# 常见：user 首条 text
				role = row.get("role") or row.get("type")
				if role in ("user", "human"):
					content = row.get("content") or row.get("text") or ""
					if isinstance(content, list):
						parts = []
						for b in content:
							if isinstance(b, dict) and b.get("type") == "text":
								parts.append(str(b.get("text") or ""))
							elif isinstance(b, str):
								parts.append(b)
						content = "\n".join(parts)
					text = str(content).strip().replace("\n", " ")
					if text:
						return text[:48] + ("…" if len(text) > 48 else "")
	except Exception:
		return ""
	return ""
