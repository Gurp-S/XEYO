from collections import deque

from server.routers.sessions import _persisted_thought_keys, _side_row_to_ui


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


def test_side_row_to_ui_projects_reasoning_as_thought_before_text() -> None:
	"""带 reasoning 的纯文本轮：思考态由投影直出，且排在正文之前。"""
	row = {
		"role": "assistant",
		"content": [
			{"type": "reasoning", "text": "先看看 assistant_text_message"},
			{"type": "text", "text": "找到了根源"},
		],
		"id": "a1",
		"ts": 2.0,
	}
	out = _side_row_to_ui(row, 0, deque())
	assert [m["id"] for m in out] == ["a1#r0", "a1"]
	assert out[0]["role"] == "assistant"
	assert out[0]["isThought"] is True
	assert out[0]["text"] == "先看看 assistant_text_message"
	assert out[0]["createdAt"] == 2000
	assert out[1].get("isThought") is None
	assert out[1]["text"] == "找到了根源"


def test_side_row_to_ui_tool_turn_keeps_thought_and_call_pairing() -> None:
	"""工具轮（reasoning+tool_use，占真实 transcript 的 65%）：此前整轮返回空 ⇒ 思考态丢失。"""
	rows = [
		{
			"role": "assistant",
			"content": [
				{"type": "reasoning", "text": "要 grep 一下"},
				{
					"type": "tool_use",
					"id": "c1",
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
			"content": [
				{"type": "tool_result", "tool_use_id": "c1", "content": "hit"}
			],
			"id": "t1",
			"ts": 3.0,
		},
	]
	messages: list[dict] = []
	pending: deque[dict] = deque()
	for i, row in enumerate(rows):
		messages.extend(_side_row_to_ui(row, i, pending))
	assert [m["role"] for m in messages] == ["assistant", "tool"]
	assert messages[0]["isThought"] is True
	assert messages[0]["text"] == "要 grep 一下"
	# tool_use 仍必须入队，否则工具行的 toolInput 配对断掉。
	assert messages[1]["toolName"] == "Grep"
	assert messages[1]["toolInput"] == '{"pattern": "foo"}'
	assert messages[1]["text"] == "hit"


def test_side_row_to_ui_pure_reasoning_turn_renders_thought_only() -> None:
	"""纯思考轮（无 text / 无工具）：不再返回空数组。"""
	row = {
		"role": "assistant",
		"content": [{"type": "reasoning", "text": "只思考、不落正文"}],
		"id": "a1",
		"ts": 2.0,
	}
	out = _side_row_to_ui(row, 0, deque())
	assert len(out) == 1
	assert out[0]["isThought"] is True
	assert out[0]["text"] == "只思考、不落正文"


def test_side_row_to_ui_tool_only_turn_still_returns_nothing() -> None:
	"""无 reasoning 的纯工具轮行为不变（真实数据里 229 行）。"""
	row = {
		"role": "assistant",
		"content": [
			{"type": "tool_use", "id": "c1", "name": "Read", "input": {"p": "x"}}
		],
		"id": "a1",
		"ts": 2.0,
	}
	pending: deque[dict] = deque()
	assert _side_row_to_ui(row, 0, pending) == []
	assert len(pending) == 1


def test_side_row_to_ui_skips_reasoning_already_persisted_as_ui_thought() -> None:
	"""已落盘的 ui_thought 行（带 think 耗时）优先，投影不重复出同文本 Thought。"""
	rows = [
		{
			"role": "assistant",
			"content": [
				{"type": "reasoning", "text": "同一段思考"},
				{"type": "text", "text": "正文"},
			],
			"id": "a1",
			"ts": 2.0,
		},
		# 前端 debounce 批量落盘：位置可以远离所属轮次。
		{
			"role": "ui_thought",
			"content": "\n同一段思考  ",
			"id": "thought-x",
			"ts": 9.0,
			"thought_ms": 900,
		},
	]
	keys = _persisted_thought_keys(rows)
	assert keys == {"同一段思考"}
	out: list[dict] = []
	pending: deque[dict] = deque()
	for i, row in enumerate(rows):
		out.extend(_side_row_to_ui(row, i, pending, persisted_thoughts=keys))
	assert [m["id"] for m in out] == ["a1", "thought-x"]
	assert out[1]["isThought"] is True
	assert out[1]["thoughtMs"] == 900


def test_side_row_to_ui_projects_when_no_persisted_thought_matches() -> None:
	"""_persisted_thought_keys 只认 ui_thought 行；其它 role 不参与去重。"""
	rows = [
		{"role": "user", "content": "忘了", "id": "u1", "ts": 1.0},
		{
			"role": "assistant",
			"content": [
				{"type": "reasoning", "text": "忘了"},
				{"type": "text", "text": "同样文本"},
			],
			"id": "a1",
			"ts": 2.0,
		},
	]
	keys = _persisted_thought_keys(rows)
	assert keys == set()
	out: list[dict] = []
	pending: deque[dict] = deque()
	for i, row in enumerate(rows):
		out.extend(_side_row_to_ui(row, i, pending, persisted_thoughts=keys))
	assert [m["id"] for m in out] == ["u1", "a1#r0", "a1"]
