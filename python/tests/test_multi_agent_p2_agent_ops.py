"""P2 #7/#8：单子 Agent 取消注册表 + Agent 工具指标。"""

from __future__ import annotations

from pathlib import Path

from engine.abort import AbortController, LinkedAbortController
from engine.live_agents import (
	abort_live_agent,
	clear_all_for_tests,
	is_live_agent,
	register_live_agent,
	unregister_live_agent,
)
from usage import multi_agent_metrics as mam


def test_live_agent_abort_isolated():
	clear_all_for_tests()
	parent = AbortController()
	child_a = LinkedAbortController(parent)
	child_b = LinkedAbortController(parent)
	register_live_agent("sess1", "agent-a", child_a)
	register_live_agent("sess1", "agent-b", child_b)
	assert is_live_agent("sess1", "agent-a")
	assert abort_live_agent("sess1", "agent-a") is True
	assert child_a.aborted is True
	assert child_b.aborted is False
	assert parent.aborted is False
	unregister_live_agent("sess1", "agent-a")
	unregister_live_agent("sess1", "agent-b")
	assert abort_live_agent("sess1", "agent-a") is False
	clear_all_for_tests()


def test_clear_sidechain_removes_transcript(tmp_path: Path, monkeypatch):
	from engine import subagent_runner as sr

	main = "sess-clear"
	aid = "agent-t-abc"
	monkeypatch.setattr(
		sr,
		"_sidechain_dir",
		lambda _sid: tmp_path / "agents",
	)
	d = tmp_path / "agents"
	d.mkdir(parents=True)
	(d / f"{aid}.jsonl").write_text('{"x":1}\n', encoding="utf-8")
	(d / f"{aid}.working.json").write_text("{}", encoding="utf-8")
	(d / f"{aid}.meta.json").write_text('{"agent_id":"x"}', encoding="utf-8")
	sr.clear_sidechain(main, aid)
	assert not (d / f"{aid}.jsonl").is_file()
	assert not (d / f"{aid}.working.json").is_file()
	assert (d / f"{aid}.meta.json").is_file()


def test_upsert_meta_marks_empty_scope_readonly(tmp_path: Path, monkeypatch):
	from engine import subagent_runner as sr

	monkeypatch.setattr(sr, "_sidechain_dir", lambda _sid: tmp_path / "agents")
	sr.upsert_subagent_meta(
		"sess-ro",
		agent_id="agent-ro",
		task_desc="read stuff",
		status="running",
		write_scope=[],
	)
	meta = __import__("json").loads(
		(tmp_path / "agents" / "agent-ro.meta.json").read_text(encoding="utf-8")
	)
	assert meta["read_only"] is True
	assert meta["write_scope"] == []
	sr.upsert_subagent_meta(
		"sess-ro",
		agent_id="agent-rw",
		task_desc="write stuff",
		status="running",
		write_scope=["src/"],
	)
	meta2 = __import__("json").loads(
		(tmp_path / "agents" / "agent-rw.meta.json").read_text(encoding="utf-8")
	)
	assert meta2["read_only"] is False
	assert meta2["write_scope"] == ["src/"]


def test_agent_tool_metrics_roundtrip(tmp_path: Path, monkeypatch):
	monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path))
	mam.record_agent_tool_start(
		session_id="s1",
		agent_id="a1",
		task_id="t1",
		desc="probe",
	)
	mam.record_agent_tool_end(
		session_id="s1",
		agent_id="a1",
		task_id="t1",
		status="done",
		duration_ms=42,
	)
	events = mam.read_events()
	kinds = [e.get("kind") for e in events]
	assert "agent_tool_start" in kinds
	assert "agent_tool_end" in kinds
	end = next(e for e in events if e.get("kind") == "agent_tool_end")
	assert end.get("status") == "done"
	assert end.get("duration_ms") == 42
