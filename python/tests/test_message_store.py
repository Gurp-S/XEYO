import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session.message_store import MessageStore
from msgtypes.message import (
	Message,
	ToolUse,
	assistant_text_message,
	system_note,
	tool_result_message,
	user_message,
)
from engine.query_loop import _fill_missing_tool_results


def test_append_order():
	s = MessageStore()
	s.append(user_message("hi"))
	s.append(assistant_text_message("yo"))
	assert len(s) == 2
	assert s.items[0].role == "user"
	assert s.as_api_messages()[0]["role"] == "user"


def test_as_api_messages_keeps_tool_role_and_call_id():
	s = MessageStore()
	s.append(user_message("find files"))
	s.append(
		assistant_text_message(
			"",
			[ToolUse(id="call_1", name="Glob", input={"pattern": "*.py"})],
		)
	)
	s.append(tool_result_message("call_1", "Glob", "a.py\nb.py"))
	api = s.as_api_messages()
	assert api[-1]["role"] == "tool"
	assert api[-1]["tool_call_id"] == "call_1"
	assert api[-1]["name"] == "Glob"
	assert api[-2]["role"] == "assistant"


def test_t_now_projection_keeps_latest_note_per_key():
	s = MessageStore()
	s.append(user_message("start"))
	s.append(system_note("# Goal\nA", key="goal", fp="fp-a"))
	s.append(system_note("# Goal\nB", key="goal", fp="fp-b"))

	api = s.as_api_messages()
	assert [row["content"] for row in api] == ["start", "# Goal\nB"]
	assert s.note_fingerprints() == {("goal", "fp-b")}
	# append-only 历史仍保留旧版本，投影过滤不改写留痕面。
	assert len([m for m in s.items if m.note_key == "goal"]) == 2


def test_note_fingerprints_start_uses_projection_index_after_note_fold():
	s = MessageStore(
		[
			Message(role="user", content="start"),
			system_note("# Goal A", key="goal", fp="fp-a"),
			Message(role="assistant", content="middle"),
			system_note("# Goal B", key="goal", fp="fp-b"),
		]
	)
	# Model projection = [user, assistant, latest goal]; compact_cursor=2 starts
	# at the latest goal. Internal history index 3 must not be used here.
	assert s.note_fingerprints(start=2) == {("goal", "fp-b")}
	assert s.note_fingerprints(start=3) == set()


def test_fill_missing_tool_results_only_gaps():
	s = MessageStore()
	uses = [
		ToolUse(id="a", name="Glob", input={}),
		ToolUse(id="b", name="Read", input={}),
	]
	s.append(assistant_text_message("", uses))
	s.append(tool_result_message("a", "Glob", "ok"))
	_fill_missing_tool_results(s, uses, "aborted")
	tool_ids = [m.tool_call_id for m in s.items if m.role == "tool"]
	assert tool_ids == ["a", "b"]
	gap = [m for m in s.items if m.role == "tool" and m.tool_call_id == "b"][0]
	assert "[tool aborted]" in str(gap.content)


def test_repair_inserts_tools_before_next_user():
	from engine.query_loop import _repair_unpaired_tool_calls

	s = MessageStore()
	s.append(user_message("first"))
	s.append(
		assistant_text_message(
			"",
			[ToolUse(id="c1", name="Glob", input={})],
		)
	)
	s.append(user_message("测试你所有的工具"))
	_repair_unpaired_tool_calls(s)
	roles = [m.role for m in s.items]
	assert roles == ["user", "assistant", "tool", "user"]
	assert s.items[2].tool_call_id == "c1"


if __name__ == "__main__":
	test_append_order()
	test_as_api_messages_keeps_tool_role_and_call_id()
	test_fill_missing_tool_results_only_gaps()
	test_repair_inserts_tools_before_next_user()
	print("ok")
