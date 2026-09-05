"""NightShift：锁、tombstone 零复活、不在 query_loop 里 await。"""

from __future__ import annotations

from memory.governance import MemoryCandidate, parse_and_validate
from memory.memdir import (
	append_tombstone,
	load_index_text,
	load_notes,
	rewrite_index,
	workspace_id,
	write_note,
)
from memory.governance import forget as make_tombstone
from memory.nightshift import (
	NightShiftState,
	_run_async,
	has_lock,
	load_candidates,
	maybe_schedule,
	release_lock,
	run,
	save_candidates,
	should_run,
)


def test_no_lock_skips(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	assert has_lock(wsid) is True
	assert has_lock(wsid) is False
	release_lock(wsid)
	assert has_lock(wsid) is True
	release_lock(wsid)


def test_forget_not_resurrected(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	note = parse_and_validate(
		{
			"id": "mem_keep",
			"type": "feedback",
			"source": {"kind": "user"},
			"confidence": 1.0,
			"status": "deleted",
			"scope": "workspace",
			"title": "测试必须打真库",
		},
		"测试必须打真库",
	)
	write_note(note, wsid=wsid)
	append_tombstone(make_tombstone("mem_keep"), wsid=wsid)
	rewrite_index(load_notes(wsid), wsid=wsid)
	save_candidates(
		wsid,
		[
			MemoryCandidate(
				content="测试必须打真库",
				source={"kind": "nightshift", "id": "mem_keep"},
				evidence=["repeat", "repeat:2"],
			),
			MemoryCandidate(
				content="测试必须打真库",
				source={"kind": "user"},
				evidence=["user_confirm"],
			),
		],
	)
	run(wsid)
	idx = load_index_text(wsid)
	assert "mem_keep" not in idx
	notes = {n.id: n for n in load_notes(wsid)}
	assert notes["mem_keep"].status == "deleted"
	assert all(
		n.status != "active" or "测试必须打真库" not in n.content
		for n in notes.values()
	)


def test_should_run_not_gated_on_session_count():
	state = NightShiftState(candidate_count=21)
	assert should_run(state, "ws") is True
	fresh = NightShiftState()
	assert should_run(fresh, "ws") is True  # never ran → 超过 24h 视作该跑


def test_should_run_when_promotable_within_24h(tmp_path, monkeypatch):
	"""24h 内但有可晋升候选 → 仍应整理（否则跨会话永远搜不到收割）。"""
	from datetime import datetime, timezone, timedelta

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	save_candidates(
		wsid,
		[
			MemoryCandidate(
				content="本仓库前端用 pnpm，测试用 pytest",
				source={"kind": "agent", "session_id": "s1"},
				evidence=["main_harvest"],
			)
		],
	)
	recent = NightShiftState(
		last_consolidated_at=datetime.now(timezone.utc) - timedelta(hours=1),
		candidate_count=1,
	)
	assert should_run(recent, wsid) is True


def test_agent_harvest_promotes(tmp_path, monkeypatch):
	"""subagent_marker 候选以 confidence=0.6 晋升进 topics。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	save_candidates(
		wsid,
		[
			MemoryCandidate(
				content="本仓库测试用 pytest",
				source={"kind": "agent", "session_id": "s1"},
				evidence=["subagent_marker"],
			)
		],
	)
	run(wsid)
	notes = {n.content: n for n in load_notes(wsid) if n.status == "active"}
	assert "本仓库测试用 pytest" in notes
	assert notes["本仓库测试用 pytest"].confidence == 0.6
	idx = load_index_text(wsid)
	assert "pytest" in idx


def test_stale_lock_reclaimed(tmp_path, monkeypatch):
	"""持有者 PID 已死 → 可回收锁再取得。"""
	import os
	from pathlib import Path

	import memory.nightshift as ns

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	ns.ensure_layout(wsid)
	lock = ns.memdir_root(wsid) / ".nightshift.lock"
	lock.write_text("99999999\n", encoding="utf-8")
	old = 1_000_000.0
	os.utime(lock, (old, old))
	assert ns.has_lock(wsid) is True
	ns.release_lock(wsid)


def test_run_only_proposes_never_writes_xeyo(tmp_path, monkeypatch):
	"""NightShift 只产提案：绝不静默改写 XEYO.md 正文。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	(xeyo := root / "XEYO.md").write_text("# 人的宪法\n永远用中文。\n", encoding="utf-8")
	wsid = workspace_id(str(root))
	save_candidates(
		wsid,
		[
			MemoryCandidate(
				content="测试必须跑 pytest",
				source={"kind": "agent", "session_id": "s1"},
				evidence=["repeat", "repeat:2", "repeat:3"],
			)
		],
	)
	run(wsid)
	# XEYO.md 字节不变
	assert xeyo.read_text(encoding="utf-8") == "# 人的宪法\n永远用中文。\n"
	# 提案落地到 proposals jsonl（非正文）
	from memory.memdir import memdir_root

	propsf = memdir_root(wsid) / "instruction_proposals.jsonl"
	assert propsf.is_file()
	assert "测试必须跑 pytest" in propsf.read_text(encoding="utf-8")


def test_maybe_schedule_after_stop_only(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	maybe_schedule(workspace_id=wsid, after_stop=False)
	# after_stop False 不得整理出索引文件以外的副作用；无锁文件即可
	from memory.memdir import memdir_root

	assert not (memdir_root(wsid) / ".nightshift.lock").exists()


def test_promote_rate_limit_caps_per_run(tmp_path, monkeypatch):
	"""P1-2 晋升限频：单轮最多晋升 cap 条，剩余留 candidate 等下轮。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.setenv("XEYO_MEMORY_PROMOTE_MAX_PER_RUN", "2")
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	save_candidates(
		wsid,
		[
			MemoryCandidate(
				content=f"事实 {i}",
				source={"kind": "agent", "session_id": f"s{i}"},
				evidence=["main_harvest"],
			)
			for i in range(5)
		],
	)
	run(wsid)
	notes = load_notes(wsid)
	promoted = [n for n in notes if n.status == "active"]
	assert len(promoted) == 2
	# 剩余 3 条仍在 candidates.jsonl（未丢、等下轮）
	leftover = [c.content for c in load_candidates(wsid)]
	assert len(leftover) == 3


def test_promote_rate_limit_infinite_by_default(tmp_path, monkeypatch):
	"""默认不设小上限（默认 8）：5 条全晋升。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.delenv("XEYO_MEMORY_PROMOTE_MAX_PER_RUN", raising=False)
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	save_candidates(
		wsid,
		[
			MemoryCandidate(
				content=f"事实 {i}",
				source={"kind": "agent", "session_id": f"s{i}"},
				evidence=["main_harvest"],
			)
			for i in range(5)
		],
	)
	run(wsid)
	notes = load_notes(wsid)
	assert len([n for n in notes if n.status == "active"]) == 5


def test_should_run_cooldown_blocks_routine(tmp_path, monkeypatch):
	"""P2-1 成功冷却：6h 内例行触发（超阈/体积）被压制；急件（Forget/冲突）不被压制。"""
	from datetime import datetime, timedelta, timezone

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.setenv("XEYO_MEMORY_COOLDOWN_HOURS", "6")
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	recent = NightShiftState(
		last_consolidated_at=datetime.now(timezone.utc) - timedelta(hours=1),
		candidate_count=21,  # 超阈但仅例行触发
	)
	assert should_run(recent, wsid) is False  # 冷却压制例行
	urgent = NightShiftState(
		last_consolidated_at=datetime.now(timezone.utc) - timedelta(hours=1),
		candidate_count=0,
		pending_forget_or_conflict=True,
	)
	assert should_run(urgent, wsid) is True  # 急件不被冷却压制


def test_followup_chain_converges_until_all_promoted(tmp_path, monkeypatch):
	"""P2-1 常驻收敛链：限频截留的可晋升候选在 0 延迟下自动续轮，直到全部晋升。"""
	import asyncio

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.setenv("XEYO_MEMORY_PROMOTE_MAX_PER_RUN", "2")
	monkeypatch.setenv("XEYO_MEMORY_FOLLOWUP_DELAY", "0")
	monkeypatch.setenv("XEYO_MEMORY_FOLLOWUP_MAX_CHAIN", "2")
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	save_candidates(
		wsid,
		[
			MemoryCandidate(
				content=f"事实 {i}",
				source={"kind": "agent", "session_id": f"s{i}"},
				evidence=["main_harvest"],
			)
			for i in range(5)
		],
	)
	asyncio.run(_run_async(wsid))
	notes = load_notes(wsid)
	assert len([n for n in notes if n.status == "active"]) == 5
	assert load_candidates(wsid) == []
