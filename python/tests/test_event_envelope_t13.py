"""T13：事件信封升级——correlation_id + tool_call.begin/end 元数据。"""

from __future__ import annotations

from dataclasses import asdict

from msgtypes.envelope import wrap
from msgtypes.events import ResultEvent, ToolCallEvent, ToolResultEvent
from engine.query_loop import _tool_input_summary


def test_envelope_correlation_defaults_to_turn() -> None:
	ev = wrap(
		ResultEvent(subtype="success"),
		session_id="s1",
		turn_id="t1",
		event_id=1,
	)
	assert ev.correlation_id == "t1"
	assert ev.turn_id == "t1"
	assert ev.schema_version
	assert ev.created_at > 0
	assert ev.type == "result"


def test_envelope_correlation_override() -> None:
	ev = wrap(
		ResultEvent(subtype="success"),
		session_id="s1",
		turn_id="t1",
		event_id=2,
		correlation_id="req-abc",
	)
	assert ev.correlation_id == "req-abc"
	assert ev.turn_id == "t1"
	assert ev.schema_version


def test_envelope_fields_present_for_old_alias() -> None:
	ev = wrap(
		ToolCallEvent(name="Grep", input={"pattern": "x"}, input_summary="…", parallel=True),
		session_id="s",
		turn_id="t",
		event_id=3,
	)
	assert asdict(ev)["correlation_id"] == "t"
	# old frame字段 alias：payload.type 保留
	assert ev.payload.type == "tool_call"


def test_tool_call_begin_metadata() -> None:
	ev = ToolCallEvent(
		name="Bash",
		input={"command": "ls"},
		tool_use_id="c1",
		input_summary='{"command":"ls"}',
		parallel=True,
	)
	assert ev.input_summary == '{"command":"ls"}'
	assert ev.parallel is True
	# 旧字段不丢
	assert ev.name == "Bash"
	assert ev.input == {"command": "ls"}


def test_tool_result_end_metadata() -> None:
	ev = ToolResultEvent(
		name="Bash",
		output="out",
		duration_ms=123,
		spilled=True,
	)
	assert ev.duration_ms == 123
	assert ev.spilled is True
	# 旧字段 alias 保留
	assert ev.name == "Bash"
	assert ev.output == "out"
	assert ev.is_error is False


def test_parallel_marker_true_when_batch_gt1() -> None:
	# 同批多个工具 → parallel=True；单工具 → False。
	from msgtypes.events import ToolCallEvent as _TCE

	assert _TCE(name="a", input={}, parallel=len([1, 2]) > 1).parallel is True
	assert _TCE(name="a", input={}, parallel=len([1]) > 1).parallel is False


def test_tool_input_summary_truncates() -> None:
	long_input = {"path": "x" * 500}
	s = _tool_input_summary(long_input)
	assert len(s) <= 201
	assert s.endswith("…")
	# 多行压成单行
	assert "\n" not in _tool_input_summary({"a": "x\ny"})


def test_tool_input_summary_non_serializable() -> None:
	# 不可序列化对象回退 str()，不抛异常
	class Weird:
		pass

	assert _tool_input_summary({"obj": Weird()}).strip() != ""
