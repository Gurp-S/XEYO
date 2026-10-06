"""当前状态的唯一筛选口径；原文和历史位置仍由 MessageStore 保留。"""

from __future__ import annotations

from msgtypes.message import Message


def current_context_items(items: list[Message], *, include_system_notes: bool) -> list[Message]:
	latest: dict[str, Message] = {}
	for item in items:
		if item.note_key and not item.note_retracted and (include_system_notes or item.role != "system"):
			latest[item.note_key] = item
	return [item for item in items if not item.note_key or latest.get(item.note_key) is item]
