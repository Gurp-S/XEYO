"""Maintain provider-valid ordering for assistant tool calls and tool results."""

from __future__ import annotations

from msgtypes.message import Message


def _has_tool_use(message: Message) -> bool:
	if message.role != "assistant" or not isinstance(message.content, list):
		return False
	return any(
		isinstance(block, dict) and block.get("type") == "tool_use"
		for block in message.content
	)


def _tool_use_ids(message: Message) -> set[str]:
	if message.role != "assistant" or not isinstance(message.content, list):
		return set()
	return {
		str(block.get("id"))
		for block in message.content
		if isinstance(block, dict)
		and block.get("type") == "tool_use"
		and block.get("id")
	}


def _tool_result_id(message: Message) -> str:
	if message.tool_call_id:
		return str(message.tool_call_id)
	if isinstance(message.content, list):
		for block in message.content:
			if isinstance(block, dict) and block.get("type") == "tool_result":
				uid = block.get("tool_use_id")
				if uid:
					return str(uid)
	return ""


def discard_unpaired_tool_results(messages: list[Message]) -> list[Message]:
	"""Drop tool rows that have no matching preceding assistant tool call.

	Such a row cannot be represented on the provider wire without inventing a
	model action. It is retained in the raw transcript/UI, but omitted from the
	engine history so one malformed row cannot brick the next request.
	"""
	out: list[Message] = []
	pending: set[str] = set()
	changed = False
	for message in messages:
		if message.role == "assistant":
			pending = _tool_use_ids(message)
			out.append(message)
			continue
		if message.role == "tool":
			uid = _tool_result_id(message)
			if uid and uid in pending:
				out.append(message)
				pending.remove(uid)
			else:
				changed = True
			continue
		pending = set()
		out.append(message)
	return out if changed else messages


def reorder_system_messages_around_tool_results(
	messages: list[Message],
) -> list[Message]:
	"""Move system rows out of an assistant tool-result batch.

	A transcript writer race can persist a system row between results belonging to
	the same assistant tool call. Providers then reject the later ``role=tool``
	row because it no longer follows the assistant ``tool_calls`` row. System
	rows are retained and moved after the complete batch; no message content is
	changed.
	"""
	out: list[Message] = []
	changed = False
	i = 0
	while i < len(messages):
		message = messages[i]
		out.append(message)
		if not _has_tool_use(message):
			i += 1
			continue

		j = i + 1
		tool_rows: list[Message] = []
		system_rows: list[Message] = []
		while j < len(messages):
			next_message = messages[j]
			if next_message.role == "tool":
				tool_rows.append(next_message)
				j += 1
				continue
			if next_message.role == "system":
				system_rows.append(next_message)
				j += 1
				continue
			break

		if system_rows:
			changed = True
		out.extend(tool_rows)
		out.extend(system_rows)
		i = j

	return out if changed else messages
