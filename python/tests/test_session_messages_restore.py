from collections import deque

from server.routers.sessions import _side_row_to_ui


def test_side_row_to_ui_expands_tool_rows() -> None:
	rows = [
		{"role": "user", "content": "find foo", "id": "u1", "ts": 1.0},
		{
			"role": "assistant",
			"content": [
				{"type": "text", "text": "searching"},
				{
					"type": "tool_use",
					"id": "call-1",
					"name": "Grep",
					"input": {"pattern": "foo"},
				},
			],
			"id": "a1",
			"ts": 2.0,
		},
		{
			"role": "tool",
			"name": "Grep",
			"content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "match"}],
			"id": "t1",
			"ts": 3.0,
		},
		{"role": "assistant", "content": "done", "id": "a2", "ts": 4.0},
	]
	messages: list[dict] = []
	pending: deque[dict] = deque()
	for i, row in enumerate(rows):
		messages.extend(_side_row_to_ui(row, i, pending))

	assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
	assert messages[0]["text"] == "find foo"
	assert messages[1]["text"] == "searching"
	assert messages[2]["toolName"] == "Grep"
	assert messages[2]["text"] == "match"
	assert messages[3]["text"] == "done"


def test_side_row_to_ui_restores_ui_thought() -> None:
	row = {
		"role": "ui_thought",
		"content": "Let me search the codebase.",
		"id": "thought-abc",
		"ts": 2.5,
		"thought_ms": 1800,
	}
	out = _side_row_to_ui(row, 0, deque())
	assert len(out) == 1
	msg = out[0]
	assert msg["role"] == "assistant"
	assert msg["isThought"] is True
	assert msg["text"] == "Let me search the codebase."
	assert msg["thoughtMs"] == 1800
	assert msg["createdAt"] == 2500
