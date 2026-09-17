import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.compact import (
	KEEP_TAIL_MESSAGES,
	MAX_TOOL_RESULT_CHARS,
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
	"""压力门阈值**按窗口推导**：触发点 = 窗口 − 固定预留（实测 54,199）。

	历史：本用例原先断言冻结的 0.80 口径（阈值 0.95），在压力门改为窗口几何
	推导后失效（既有红）。现按当前语义重写，并把"小窗口下触发点塌缩"这一
	缺陷形态钉成回归守卫——2026-09-16 实测：窗口 65536 时触发点只有 11,337
	token，等于每道长任务从开头就在压缩上下文。
	"""
	from memory.runtime import should_force_compact_on_pressure

	monkeypatch.delenv("XEYO_CONTEXT_COMPACT_RATIO", raising=False)
	assert not should_force_compact_on_pressure(prompt_tokens=0, context_limit=128_000)
	# 窗口−预留 ≈ 73,801：其下不压、其上压
	assert not should_force_compact_on_pressure(prompt_tokens=73_000, context_limit=128_000)
	assert should_force_compact_on_pressure(prompt_tokens=74_500, context_limit=128_000)
	# 显式 ratio 仍可覆盖（与窗口无关）
	assert should_force_compact_on_pressure(
		prompt_tokens=100_000, context_limit=128_000, ratio=0.7
	)
	assert not should_force_compact_on_pressure(
		prompt_tokens=100_000, context_limit=128_000, ratio=0.95
	)
	monkeypatch.setenv("XEYO_CONTEXT_COMPACT_RATIO", "0.8")
	from memory.runtime import context_compact_ratio

	assert context_compact_ratio() == 0.8


def test_pressure_cliff_collapses_on_small_window() -> None:
	"""回归守卫：小窗口下触发点塌缩 ⇒ 引擎会从头压缩上下文。

	65536（2026-09-16 之前的 deepseek 硬编码值）触发点仅 11,337 token；真实窗口
	1M 时触发点 945,801（单题内不可能达到）。这条守卫存在的意义是：任何把窗口
	默认值调回 64k 量级的改动，都会在 CI 里立刻变红。
	"""
	from memory.runtime import should_force_compact_on_pressure as S

	def cliff(window: int) -> int:
		lo, hi = 1, window
		while lo < hi:
			mid = (lo + hi) // 2
			if S(prompt_tokens=mid, context_limit=window):
				hi = mid
			else:
				lo = mid + 1
		return lo

	old = cliff(65_536)
	real = cliff(1_000_000)
	assert old < 12_000, f"64k 窗口下触发点应约 1.1 万，实测 {old}"
	assert real > 900_000, f"1M 窗口下触发点应约 94.6 万，实测 {real}"


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))
