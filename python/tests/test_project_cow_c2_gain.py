"""投影 copy-on-write + C2 收益门去全量物化。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.compact import project
from memory.runtime import _c2_gain_enough
from memory.working import WorkingSnapshot


def _assistant_use(uid: str, name: str) -> dict:
	return {
		"role": "assistant",
		"content": [
			{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}},
		],
	}


def _tool_result(uid: str, content: str) -> dict:
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


def test_project_shares_unchanged_messages():
	history = [
		{"role": "user", "content": "hello"},
		{"role": "assistant", "content": "hi"},
		_assistant_use("g0", "Grep"),
		_tool_result("g0", "short result"),
	]
	out = project(history)
	assert out[0] is history[0]
	assert out[1] is history[1]
	assert out[2] is history[2]
	# 短 tool_result、未冻结：内容不变，消息对象共享
	assert out[3] is history[3]


def test_project_copies_only_when_c0_or_c1():
	blob = "x" * 20_000
	history = [
		{"role": "user", "content": "start"},
		_assistant_use("g0", "Grep"),
		_tool_result("g0", blob),
		{"role": "assistant", "content": "done"},
	]
	out = project(history)
	assert out[0] is history[0]
	assert out[1] is history[1]
	assert out[3] is history[3]
	assert out[2] is not history[2]
	assert history[2]["content"][0]["content"] == blob
	assert "…[truncated]…" in out[2]["content"][0]["content"]


def test_project_c1_does_not_mutate_input(monkeypatch, mem_switch):
	mem_switch(XEYO_TOOL_AGING="0")
	history = [
		{"role": "user", "content": "start"},
		_assistant_use("g0", "Grep"),
		_tool_result("g0", "line1\nline2"),
		{"role": "user", "content": "tail"},
	]
	body = history[2]["content"][0]["content"]
	out = project(history, frozen_until=3)
	assert out[2] is not history[2]
	assert history[2]["content"][0]["content"] is body
	assert out[2]["content"][0]["content"].startswith("[compacted] Grep:")


def test_c2_gain_enough_uses_chars_not_project(monkeypatch):
	"""收益门不得再 project + dumps 全量投影。"""

	def _boom(*_a, **_k):
		raise AssertionError("project must not be called from _c2_gain_enough")

	monkeypatch.setattr("engine.compact.project", _boom)
	# 也挡 runtime 里若仍有惰性 import
	import engine.compact as compact_mod

	monkeypatch.setattr(compact_mod, "project", _boom)

	# 左区很大、摘要很小 → 收益门通过
	left = [{"role": "user", "content": "L" * 8_000} for _ in range(3)]
	tail = [{"role": "user", "content": "tail"}]
	messages = left + tail
	working = WorkingSnapshot(compact_cursor=0)
	params = SimpleNamespace(c2_min_gain_chars=4000, c2_min_save_ratio=0.25)
	assert _c2_gain_enough(messages, working, len(left), params) is True

	# 左区几乎不比摘要大 → 拒
	tiny = [{"role": "user", "content": "x"}]
	assert _c2_gain_enough(tiny + tail, working, 1, params) is False

	# 右尾占绝大部分 → 尺寸比拒（摘要+尾 ≈ 全量）
	huge_tail = [{"role": "user", "content": "T" * 50_000}]
	small_left = [{"role": "user", "content": "L" * 5_000}]
	assert (
		_c2_gain_enough(small_left + huge_tail, working, 1, params) is False
	)
