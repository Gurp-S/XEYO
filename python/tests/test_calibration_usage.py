"""点2：逐枪校准观测管道（observe → calibration_events.jsonl → HitRecord）。"""

from __future__ import annotations

import pytest

from memory.observe import observe_shot
from memory.simulator.calibration import hit_records_from_events
from memory.working import WorkingSnapshot
from usage.ledger import read_calibration_events, record_calibration_shot


def test_record_and_read_calibration_shot(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_calibration_shot(
		session_id="s1",
		request_id="r1",
		provider="deepseek",
		model="m1",
		action="keep",
		cache_age=0.0,
		lcp=640,
		predicted_hit=608.0,
		observed_hit=640.0,
		prompt_tokens=1000,
		output_tokens=50,
		context_length=1000,
		conversation_length=3,
		tool_result_size=4000,
	)
	rows = read_calibration_events()
	assert len(rows) == 1
	ev = rows[0]
	assert ev["action"] == "keep"
	assert ev["LCP"] == 640
	assert ev["observed_hit"] == 640.0
	assert ev["conversation_length"] == 3
	assert ev["tool_result_size"] == 4000


def test_observe_shot_records_and_advances_last_x_sent(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	snap = WorkingSnapshot(session_id="s1")
	snap.last_action = "keep"
	projected = [{"role": "user", "content": "hello"}]
	observe_shot(snap, projected, hit=10, miss=5, out=3, context_tokens=15, turn=1)
	rows = read_calibration_events()
	assert len(rows) == 1
	ev = rows[0]
	assert ev["session_id"] == "s1"
	assert ev["action"] == "keep"
	assert ev["observed_hit"] == 10.0
	assert ev["prompt_tokens"] == 15
	assert snap.last_x_sent  # 已记录本轮投影，供下一枪 LCP


def test_observe_two_shots_lcp_nonzero(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	snap = WorkingSnapshot(session_id="s1")
	snap.last_action = "keep"
	base = [{"role": "user", "content": "x" * 100}]
	follow = [
		{"role": "user", "content": "x" * 100},
		{"role": "assistant", "content": "hi"},
	]
	observe_shot(snap, base, hit=0, miss=10, out=0, context_tokens=10, turn=1)
	observe_shot(snap, follow, hit=5, miss=10, out=0, context_tokens=15, turn=2)
	rows = read_calibration_events()
	assert len(rows) == 2
	# 第二枪与第一枪有共同前缀 → LCP > 0（而非恒 0）
	assert rows[1]["LCP"] > 0
	assert rows[1]["observed_hit"] == 5.0


def test_hit_records_from_events_roundtrip(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_calibration_shot(
		session_id="s1",
		action="C2",
		lcp=0,
		predicted_hit=0.0,
		observed_hit=128.0,
		prompt_tokens=2000,
		output_tokens=10,
		context_length=2000,
		conversation_length=6,
		tool_result_size=8000,
	)
	rows = hit_records_from_events()
	assert len(rows) == 1
	r = rows[0]
	assert r.action == "C2"
	assert r.LCP == 0
	assert r.observed_hit == 128.0
	assert r.conversation_length == 6
	assert r.tool_result_size == 8000


@pytest.mark.asyncio
async def test_query_loop_records_calibration_events(tmp_path, monkeypatch, mem_switch):
	"""热路径集成：每次模型请求都会追加一条校准观测（action=project 默认通道）。"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	# gate 默认开（2026-09）会让投影走 decide（action=keep）；本测试验证
	# 「默认通道记录 project 观测」→ 显式关 gate。
	mem_switch(XEYO_C2_GATE="0")
	from engine.abort import AbortController
	from engine.budget import BudgetTracker
	from engine.query_loop import query_loop
	from model.fake import FakeModelClient
	from msgtypes.events import FinalEvent
	from msgtypes.message import user_message
	from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
	from session.message_store import MessageStore
	from tools.echo import EchoTool
	from tools.tool_registry import ToolRegistry

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
	assert any(isinstance(e, FinalEvent) for e in events)
	rows = read_calibration_events()
	assert len(rows) >= 1
	assert rows[0]["action"] == "project"


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))