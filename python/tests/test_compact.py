import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.compact import (
	KEEP_TAIL_MESSAGES,
	MAX_TOOL_RESULT_CHARS,
	TRUNCATE_SUFFIX,
	_iter_tool_result_blocks,
	_message_chars,
	project,
)
from engine.query_loop import query_loop
from model.fake import FakeModelClient
from msgtypes.events import FinalEvent
from msgtypes.message import user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry

import pytest


def _assistant_use(uid: str, name: str) -> dict:
	return {
		"role": "assistant",
		"content": [
			{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}},
		],
	}


def _tool_result_user(uid: str, content: str) -> dict:
	return {
		"role": "user",
		"content": [
			{
				"type": "tool_result",
				"tool_use_id": uid,
				"content": content,
				"is_error": False,
			}
		],
	}


def test_project_does_not_mutate_input():
	uid = "call_1"
	blob = "x" * 20_000
	history = [
		{"role": "user", "content": "找 py"},
		_assistant_use(uid, "Grep"),
		_tool_result_user(uid, blob),
	]
	project(history)
	assert history[2]["content"][0]["content"] == blob


def test_c0_truncates_oversized_keep_full_read():
	uid = "call_read"
	blob = "R" * 20_000
	history = [
		{"role": "user", "content": "读文件"},
		_assistant_use(uid, "Read"),
		_tool_result_user(uid, blob),
	]
	out = project(history)
	got = out[2]["content"][0]["content"]
	# C0 改为首尾保留：中间省略，总长约 MAX_TOOL_RESULT_CHARS。
	assert "…[truncated]…" in got
	assert got.startswith("R")
	assert got.endswith("R")
	assert len(got) <= MAX_TOOL_RESULT_CHARS + 20
	assert blob not in got


def test_c1_freezes_before_frozen_until_keeps_tail():
	history: list[dict] = [{"role": "user", "content": "开始"}]
	for i in range(7):
		uid = f"grep_{i}"
		history.append(_assistant_use(uid, "Grep"))
		history.append(_tool_result_user(uid, ("g%d\n" % i) * 10_000))
	read_bodies = []
	for i in range(3):
		uid = f"read_{i}"
		body = f"READ_MARKER_{i}\n" + ("r" * 200)
		read_bodies.append(body)
		history.append(_assistant_use(uid, "Read"))
		history.append(_tool_result_user(uid, body))

	# frozen_until=0（尚未 C1）：旧结果也保留原文，投影只做 C0
	out_all = project(history)
	kept_all = [
		block["content"]
		for msg in out_all
		for block in _iter_tool_result_blocks(msg)
	]
	assert kept_all[0].startswith("g0")
	assert any("READ_MARKER_0" in str(c) for c in kept_all)

	# C1 冻结：frozen_until 之前的全部占位，尾部（KEEP_TAIL_MESSAGES 条）保留原文
	frozen = max(0, len(history) - KEEP_TAIL_MESSAGES)
	out = project(history, frozen_until=frozen)
	assert _message_chars(out) < 80_000
	kept = [
		block["content"]
		for msg in out
		for block in _iter_tool_result_blocks(msg)
	]
	for body in read_bodies:
		assert body in kept
	# 存根前缀双格式兼容:flag 关=legacy "[compacted]",开="[elided ...]"(老化规格)
	assert any(
		isinstance(c, str) and (c.startswith("[compacted] Grep:") or c.startswith("[elided Grep"))
		for c in kept
	)
	assert kept[0].startswith(("[compacted] Grep:", "[elided Grep"))
	# 冻结边界只前进：同样输入重复投影字节不变
	assert project(history, frozen_until=frozen) == out


def test_project_is_deterministic():
	uid = "call_1"
	history = [
		{"role": "user", "content": "找 py"},
		_assistant_use(uid, "Grep"),
		_tool_result_user(uid, "x" * 20_000),
	]
	assert project(history) == project(history)


@pytest.mark.asyncio
async def test_query_loop_echo_still_works():
	store = MessageStore([user_message("echo:hi")])
	reg = ToolRegistry()
	reg.register(EchoTool())
	events = []
	async for ev in query_loop(
		store=store,
		model=FakeModelClient(),
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		events.append(ev)
	finals = [e for e in events if isinstance(e, FinalEvent)]
	assert finals and finals[0].text == "echoed: hi"
	# 权威 store 仍是全文（echo 很短，投影与原文一致）
	assert any(
		"hi" in str(getattr(m, "content", "")) for m in store.items
	)


def test_should_force_compact_on_pressure_threshold(monkeypatch):
	from memory.runtime import should_force_compact_on_pressure

	monkeypatch.delenv("XEYO_CONTEXT_COMPACT_RATIO", raising=False)
	assert not should_force_compact_on_pressure(prompt_tokens=0, context_limit=128_000)
	assert not should_force_compact_on_pressure(prompt_tokens=100_000, context_limit=128_000)
	assert should_force_compact_on_pressure(prompt_tokens=121_600, context_limit=128_000)
	assert should_force_compact_on_pressure(
		prompt_tokens=100_000, context_limit=128_000, ratio=0.7
	)
	monkeypatch.setenv("XEYO_CONTEXT_COMPACT_RATIO", "0.8")
	from memory.runtime import context_compact_ratio

	assert context_compact_ratio() == 0.8
	assert should_force_compact_on_pressure(prompt_tokens=102_400, context_limit=128_000)


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))
