"""从 transcript 的已提交 TodoWrite 回执恢复状态，与 WSC 使用同一来源。"""

from __future__ import annotations

import json
import re
from typing import Any

from tools.todo_write_tool.constants import TODO_WRITE_TOOL_NAME
from tools.todo_write_tool.types import TodoItem, todo_item_from_raw

_TODO_LIST_RE = re.compile(
	r"<todo_list>\s*([\s\S]*?)\s*</todo_list>",
	re.IGNORECASE,
)


def parse_todos_from_result_text(text: str) -> list[TodoItem] | None:
	"""解析 tool_result 正文；无标签返回 None；空标签返回 []。"""
	from synaptic.todo_snapshot import _payload
	raw = _payload(text or "")
	if raw is None:
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
	"""Restore committed receipt state using the same provenance as WSC."""
	from tools.todo_write_tool.committed_restore import restore

	return restore(messages)


def restore_todos_from_transcript(session_id: str) -> list[TodoItem]:
	"""从会话 JSONL（含旋转归档）恢复；文件缺失返回 []。

	replace 事件化回溯：用合并日志的 surface fold 视图（与 hydrate 同源），
	被回溯轮写的 todo 不再复活。此前 per-file 分别 hydrate 会漏掉
	「marker 在当前文件、被影子行在归档」的跨文件影子。
	"""
	from session.persistence import is_session_persistence_disabled
	if is_session_persistence_disabled():
		return []
	sid = (session_id or "").strip()
	if not sid:
		return []
	from session.hydrate import surface_rows_for_session

	# API hydration handles provider sequencing separately. State authority
	# comes from the combined rollback-folded surface; recovery failures do
	# not establish an empty state or permit a per-file rollback bypass.
	return restore_todos_from_messages(surface_rows_for_session(sid))
