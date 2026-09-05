"""T4 回归：未闭合 tool_use 的 hydrate 合成 + transcript 强制刷盘。"""

from __future__ import annotations

import asyncio

import pytest

from session.hydrate import (
	messages_from_rows,
	_repair_unclosed_tool_uses,
)
from session.record_transcript import flush_transcript
from session.persistence import transcript_path


def _assistant_with_uses(*uses: tuple[str, str]):
	blocks = [
		{"type": "text", "text": "我来查一下。"},
		*[
			{"type": "tool_use", "id": uid, "name": name, "input": {}}
			for uid, name in uses
		],
	]
	return {"role": "assistant", "content": blocks, "id": "a1"}


def _tool_row(uid: str, name: str):
	return {
		"role": "tool",
		"tool_call_id": uid,
		"name": name,
		"content": [{"type": "tool_result", "tool_use_id": uid, "content": "ok"}],
		"id": f"t-{uid}",
	}


def test_unclosed_readonly_tool_gets_not_started():
	rows = [_assistant_with_uses(("u1", "Read"))]
	msgs = messages_from_rows(rows)
	last = msgs[-1]
	assert last.role == "tool"
	assert "TOOL_NOT_STARTED" in str(last.content)


def test_unclosed_write_tool_gets_outcome_unknown():
	rows = [_assistant_with_uses(("u2", "Bash"), ("u3", "Write"))]
	msgs = messages_from_rows(rows)
	synth = [m for m in msgs if m.role == "tool"]
	assert len(synth) == 2
	texts = [str(m.content) for m in synth]
	assert any("TOOL_OUTCOME_UNKNOWN" in t for t in texts)
	# 未闭合结果标记为 error（fail-closed，促使模型先核实）。
	assert all(
		any(b.get("is_error") for b in m.content if isinstance(b, dict))
		for m in synth
	)


def test_closed_tool_uses_not_touched():
	rows = [_assistant_with_uses(("u1", "Bash")), _tool_row("u1", "Bash")]
	msgs = messages_from_rows(rows)
	assert len(msgs) == 2
	assert "ok" in str(msgs[-1].content)


def test_mixed_closed_and_unclosed():
	rows = [
		_assistant_with_uses(("u1", "Grep"), ("u2", "Edit")),
		_tool_row("u1", "Grep"),
	]
	msgs = messages_from_rows(rows)
	tool_msgs = [m for m in msgs if m.role == "tool"]
	assert len(tool_msgs) == 2
	assert tool_msgs[0].name == "Grep" and tool_msgs[0].tool_call_id == "u1"  # 原有结果保持在前
	assert "TOOL_OUTCOME_UNKNOWN" in str(tool_msgs[-1].content)


def test_repair_is_stable_on_clean_transcript():
	rows = [
		{"role": "user", "content": "hi", "id": "m1"},
		_assistant_with_uses(("u1", "Read")),
		_tool_row("u1", "Read"),
		{"role": "assistant", "content": "done", "id": "a2"},
	]
	msgs = messages_from_rows(rows)
	assert len(msgs) == 4
	assert all(m.role != "tool" or "TOOL_" not in str(m.content) for m in msgs)


@pytest.mark.asyncio
async def test_flush_transcript_safe_under_no_session():
	"""_safe_flush_transcript 在无活动 session 时静默（不抛异常）。"""
	from engine.query_loop import _safe_flush_transcript

	await asyncio.to_thread(flush_transcript)  # 直接 flush 不抛
	_safe_flush_transcript()  # 包装层同样不抛


def test_flush_before_model_request_wiring_exists():
	"""静态守护：query_loop 必须在 model.stream 前调用 _safe_flush_transcript。"""
	import inspect

	from engine import query_loop

	src = inspect.getsource(query_loop)
	stream_idx = src.find("model.stream(api_messages")
	flush_idx = src.rfind("_safe_flush_transcript()", 0, stream_idx)
	assert flush_idx != -1
	# 副作用工具前也必须刷盘。
	call_idx = src.find("if not is_concurrency_safe(tools, tu.name):")
	assert call_idx != -1
	assert src.find("_safe_flush_transcript()", call_idx) != -1


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))
