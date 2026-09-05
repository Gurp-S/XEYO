"""TodoWrite 结构化输出契约：SSE 可直接消费，不再只靠交互文本反解析。"""

from __future__ import annotations

import pytest

from engine.abort import AbortController
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


@pytest.mark.asyncio
async def test_execute_emits_structured_todos() -> None:
	tool = TodoWriteTool()
	abort = AbortController()
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
		abort,
	)
	assert res.is_error is False
	assert res.todos is not None
	assert res.todos[0]["status"] == "in_progress"
	assert "activeForm" in res.todos[0]
	# 模型仍能看到人类文本 + <todo_list> 标签，但 UI 无需再反解析。
	assert "<todo_list>" in res.content


@pytest.mark.asyncio
async def test_execute_empty_todos_emits_empty() -> None:
	tool = TodoWriteTool()
	abort = AbortController()
	res = await tool.execute({"todos": []}, abort)
	assert res.is_error is False
	assert res.todos == []
	assert "empty" in res.content.lower()
