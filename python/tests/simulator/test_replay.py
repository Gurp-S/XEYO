"""JSONL replay vs engine.compact.project."""

from __future__ import annotations

import json
from pathlib import Path

from memory.simulator.replay import (
	count_corrections,
	replay_messages,
	replay_path,
	tool_loop_flags,
)
from memory.simulator.scenarios import list_scenarios


def test_replay_synthetic_as_jsonl(tmp_path: Path):
	sc = next(s for s in list_scenarios(smoke=True) if s.id == "short:3")
	p = tmp_path / "s.jsonl"
	ts = 1_700_000_000.0
	with p.open("w", encoding="utf-8") as f:
		for i, m in enumerate(sc.messages):
			row = {
				"id": f"id{i}",
				"role": m["role"],
				"content": m["content"],
				"ts": ts + i,
			}
			f.write(json.dumps(row, ensure_ascii=False) + "\n")
	rs = replay_path(p)
	assert rs.turns
	assert all(t.predicted in ("keep", "C1", "C2", "L4") for t in rs.turns)
	assert all(t.baseline_tokens > 0 for t in rs.turns)
	assert all(t.v61_tokens > 0 for t in rs.turns)


def test_correction_and_loop_heuristics():
	msgs = [
		{"role": "user", "content": "请读 A.py"},
		{
			"role": "assistant",
			"content": [
				{"type": "tool_use", "id": "1", "name": "Read", "input": {"path": "A.py"}},
			],
		},
		{
			"role": "assistant",
			"content": [
				{"type": "tool_use", "id": "2", "name": "Read", "input": {"path": "A.py"}},
			],
		},
		{
			"role": "assistant",
			"content": [
				{"type": "tool_use", "id": "3", "name": "Read", "input": {"path": "A.py"}},
			],
		},
		{"role": "user", "content": "你已经做过了，不是这个文件"},
	]
	assert count_corrections(msgs) == 1
	flags = tool_loop_flags(msgs)
	assert flags["same_read_ge3"] == 1


def test_replay_messages_keep_on_short():
	sc = next(s for s in list_scenarios(smoke=True) if s.id == "short:2")
	rs = replay_messages(sc.messages, session_id="t")
	assert rs.turns
	assert rs.turns[0].predicted == "keep"


def test_estimate_remaining_respects_r_cap():
	"""r_cap 接线：R 估计按 params.r_cap 封顶（不再硬编码 24）。"""
	from memory.simulator.params import Params
	from memory.simulator.replay import estimate_remaining

	msgs = [{"role": "user", "content": f"q{i}"} for i in range(30)]
	# 30 轮 ⇒ 深度估计 = max(4, 16-30//8) = 13；默认 r_cap=24 不干预（行为保持不变）
	assert estimate_remaining(msgs) == 13
	assert estimate_remaining(msgs, Params(r_cap=24)) == 13
	assert estimate_remaining(msgs, Params(r_cap=9)) == 9
	assert estimate_remaining(msgs, Params(r_cap=5)) == 5
	assert estimate_remaining([{"role": "user", "content": "就这样"}], Params(r_cap=9)) == 1
