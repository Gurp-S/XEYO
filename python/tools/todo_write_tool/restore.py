"""从 transcript 恢复最近一次 TodoWrite 快照。

权威顺序：sidecar ``.working.json`` 优先；本模块仅在 sidecar 为空时作冷启动回填。
扫描策略与前端 ``parseTodosFromResult`` 对齐：倒序找最后一次 TodoWrite tool_result
里的 ``<todo_list>…</todo_list>``；再回退 assistant tool_use.input.todos。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from session.hydrate import messages_from_transcript
from session.persistence import transcript_path
from session.record_transcript import transcript_read_paths
from tools.todo_write_tool.constants import TODO_WRITE_TOOL_NAME
from tools.todo_write_tool.types import TodoItem, todo_item_from_raw

_TODO_LIST_RE = re.compile(
	r"<todo_list>\s*([\s\S]*?)\s*</todo_list>",
	re.IGNORECASE,
)


def parse_todos_from_result_text(text: str) -> list[TodoItem] | None:
	"""解析 tool_result 正文；无标签返回 None；空标签返回 []。"""
	m = _TODO_LIST_RE.search(text or "")
	if not m:
		return None
	inner = (m.group(1) or "").strip()
	if not inner:
		return []
	try:
		raw = json.loads(inner)
	except json.JSONDecodeError:
		return None
	if not isinstance(raw, list):
		return None
	items = [todo_item_from_raw(x) for x in raw]
	return [t for t in items if t is not None]


def parse_todos_from_tool_use_input(inp: Any) -> list[TodoItem] | None:
	if not isinstance(inp, dict):
		return None
	raw = inp.get("todos")
	if not isinstance(raw, list):
		return None
	items = [todo_item_from_raw(x) for x in raw]
	return [t for t in items if t is not None]


def restore_todos_from_messages(messages: list[Any]) -> list[TodoItem]:
	"""倒序扫描消息列表，返回最后一次 TodoWrite 权威快照（可能为空列表）。"""
	last_from_result: list[TodoItem] | None = None
	last_from_input: list[TodoItem] | None = None

	for msg in reversed(list(messages)):
		role = getattr(msg, "role", None)
		name = getattr(msg, "name", None) or ""
		content = getattr(msg, "content", None)

		if role == "tool" and name == TODO_WRITE_TOOL_NAME:
			text = content if isinstance(content, str) else ""
			if isinstance(content, list):
				parts: list[str] = []
				for block in content:
					if isinstance(block, dict) and block.get("type") == "tool_result":
						c = block.get("content")
						if isinstance(c, str):
							parts.append(c)
					elif isinstance(block, str):
						parts.append(block)
				text = "\n".join(parts)
			parsed = parse_todos_from_result_text(text)
			if parsed is not None:
				last_from_result = parsed
				break

		if role == "assistant" and isinstance(content, list):
			for block in content:
				if not isinstance(block, dict):
					continue
				if block.get("type") != "tool_use":
					continue
				if (block.get("name") or "") != TODO_WRITE_TOOL_NAME:
					continue
				parsed = parse_todos_from_tool_use_input(block.get("input"))
				if parsed is not None:
					last_from_input = parsed
					# 继续向前找更新的 tool_result；若没有则用 input
					break
			if last_from_result is not None:
				break

	if last_from_result is not None:
		return last_from_result
	if last_from_input is not None:
		return last_from_input
	return []


def restore_todos_from_transcript(session_id: str) -> list[TodoItem]:
	"""从会话 JSONL（含旋转归档）恢复；文件缺失返回 []。

	replace 事件化回溯：用合并日志的 surface fold 视图（与 hydrate 同源），
	被回溯轮写的 todo 不再复活。此前 per-file 分别 hydrate 会漏掉
	「marker 在当前文件、被影子行在归档」的跨文件影子。
	"""
	sid = (session_id or "").strip()
	if not sid:
		return []
	try:
		from session.hydrate import messages_from_rows, surface_rows_for_session

		return restore_todos_from_messages(messages_from_rows(surface_rows_for_session(sid)))
	except Exception:
		# fold 管线不可用（如 transcript_blobs 异常）→ 退回旧行为，至少不丢 todo。
		try:
			primary = transcript_path(sid)
			paths = [p for p in transcript_read_paths(primary) if p.is_file()]
		except Exception:
			return []
		merged: list[Any] = []
		for p in paths:
			try:
				merged.extend(messages_from_transcript(p))
			except Exception:
				continue
		return restore_todos_from_messages(merged)
