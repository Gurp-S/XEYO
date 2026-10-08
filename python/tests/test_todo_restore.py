"""TodoWrite：transcript 恢复 + agent key 隔离。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import Message
from tools.todo_write_tool.restore import (
	parse_todos_from_result_text,
	restore_todos_from_messages,
	restore_todos_from_transcript,
)
from tools.todo_write_tool.store import TodoStore
from tools.todo_write_tool.todo_write_tool import TodoWriteTool
from tools.todo_write_tool.types import TodoItem


def test_parse_todos_from_result_text() -> None:
	blob = json.dumps(
		[{"content": "A", "status": "pending", "activeForm": "Doing A"}]
	)
	text = f"ok\n<todo_list>\n{blob}\n</todo_list>"
	items = parse_todos_from_result_text(text)
	assert items is not None
	assert len(items) == 1
	assert items[0].content == "A"


def test_output_field_survives_transcript_restore() -> None:
	"""R4 注册表：output 必须穿透 tool_result → 解析 → 恢复全链路。"""
	blob = json.dumps(
		[
			{
				"content": "A",
				"status": "completed",
				"activeForm": "Doing A",
				"output": "out/a.json",
			}
		]
	)
	text = f"ok\n<todo_list>\n{blob}\n</todo_list>"
	items = parse_todos_from_result_text(text)
	assert items is not None
	assert items[0].output == "out/a.json"

	msg = Message(
		role="tool",
		name="TodoWrite",
		content=text,
		tool_call_id="1",
	)
	got = restore_todos_from_messages([msg])
	assert len(got) == 1
	assert got[0].output == "out/a.json"


def test_restore_from_messages_prefers_last_tool_result() -> None:
	first = Message(
		role="tool",
		name="TodoWrite",
		content='x\n<todo_list>\n[{"content":"old","status":"pending","activeForm":"o"}]\n</todo_list>',
		tool_call_id="1",
	)
	second = Message(
		role="tool",
		name="TodoWrite",
		content='y\n<todo_list>\n[{"content":"new","status":"in_progress","activeForm":"n"}]\n</todo_list>',
		tool_call_id="2",
	)
	got = restore_todos_from_messages([first, second])
	assert len(got) == 1
	assert got[0].content == "new"


def test_restore_from_transcript_file(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	sid = "sess-todo-restore"
	from session.persistence import transcript_path

	path = transcript_path(sid)
	row = {
		"id": "m1",
		"role": "tool",
		"name": "TodoWrite",
		"tool_call_id": "c1",
		"content": (
			'ok\n<todo_list>\n'
			'[{"content":"Ship","status":"pending","activeForm":"Shipping"}]\n'
			"</todo_list>"
		),
	}
	path.write_text(json.dumps(row) + "\n", encoding="utf-8")
	items = restore_todos_from_transcript(sid)
	assert len(items) == 1
	assert items[0].content == "Ship"


def test_todo_store_agent_key_isolation() -> None:
	from tools.todo_write_tool.todo_write_tool import TodoWriteInput

	store = TodoStore()
	tool_main = TodoWriteTool(store=store, agent_id="main")
	tool_sub = TodoWriteTool(store=store)
	tool_sub.set_todo_store(store)
	tool_sub.set_agent_id("worker-1")
	tool_main.call(
		TodoWriteInput(
			todos=[
				TodoItem(
					content="main task",
					status="pending",
					active_form="Doing main",
				)
			]
		)
	)
	tool_sub.call(
		TodoWriteInput(
			todos=[
				TodoItem(
					content="sub task",
					status="in_progress",
					active_form="Doing sub",
				)
			]
		)
	)
	assert store.get("default")[0].content == "main task"
	assert store.get("agent-worker-1")[0].content == "sub task"


@pytest.mark.asyncio
async def test_execute_uses_injected_store() -> None:
	store = TodoStore()
	tool = TodoWriteTool(store=store)
	tool.set_session_id("s1")
	res = await tool.execute(
		{
			"todos": [
				{
					"content": "Run tests",
					"status": "in_progress",
					"activeForm": "Running tests",
				}
			]
		},
		AbortController(),
	)
	assert not res.is_error
	assert store.get()[0].content == "Run tests"
