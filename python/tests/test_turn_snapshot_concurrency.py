from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import threading
import time

from engine import turn_snapshot


def test_concurrent_flushes_for_one_session_are_serialized(tmp_path, monkeypatch, caplog):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	real_replace = turn_snapshot.os.replace
	observed_sources: list[str] = []
	active_replaces = 0
	max_active_replaces = 0
	state_lock = threading.Lock()
	start = threading.Barrier(8)

	def observed_replace(src: str | Path, dst: str | Path) -> None:
		nonlocal active_replaces, max_active_replaces
		with state_lock:
			active_replaces += 1
			max_active_replaces = max(max_active_replaces, active_replaces)
			observed_sources.append(Path(src).name)
		try:
			# Keep the replace window open so unsynchronized flushes overlap reliably.
			time.sleep(0.01)
			real_replace(src, dst)
		finally:
			with state_lock:
				active_replaces -= 1

	monkeypatch.setattr(turn_snapshot.os, "replace", observed_replace)

	def flush_one(revision: int) -> None:
		start.wait(timeout=5)
		turn_snapshot.flush(
			turn_snapshot.TurnSnapshot(
				session_id="sess_snapshot_concurrent",
				turn_id=f"turn-{revision}",
				revision=revision,
			)
		)

	with caplog.at_level(logging.WARNING, logger="xeyo.turn_snapshot"):
		with ThreadPoolExecutor(max_workers=8) as executor:
			list(executor.map(flush_one, range(8)))

	assert max_active_replaces == 1
	assert len(observed_sources) == 8
	assert len(set(observed_sources)) == 8
	assert not turn_snapshot._FLUSH_LOCKS
	loaded = turn_snapshot.hydrate("sess_snapshot_concurrent")
	assert loaded is not None
	assert loaded.revision in range(8)
	assert not [path for path in tmp_path.iterdir() if path.name.endswith(".tmp")]
	assert not [
		record
		for record in caplog.records
		if record.name == "xeyo.turn_snapshot" and record.levelno >= logging.WARNING
	]


def test_failed_replace_cleans_unique_temp_file(tmp_path, monkeypatch, caplog):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	turn_snapshot.flush(
		turn_snapshot.TurnSnapshot(
			session_id="sess_snapshot_replace_failure",
			turn_id="persisted",
			status="running",
		)
	)

	def fail_replace(_src: str | Path, _dst: str | Path) -> None:
		raise PermissionError("simulated replace failure")

	monkeypatch.setattr(turn_snapshot.os, "replace", fail_replace)
	with caplog.at_level(logging.WARNING, logger="xeyo.turn_snapshot"):
		turn_snapshot.flush(
			turn_snapshot.TurnSnapshot(
				session_id="sess_snapshot_replace_failure",
				turn_id="not-persisted",
				status="stopped",
			)
		)

	loaded = turn_snapshot.hydrate("sess_snapshot_replace_failure")
	assert loaded is not None
	assert loaded.turn_id == "persisted"
	assert not [path for path in tmp_path.iterdir() if path.name.endswith(".tmp")]
	assert any(
		record.name == "xeyo.turn_snapshot"
		and record.levelno >= logging.WARNING
		and "turn snapshot flush failed" in record.getMessage()
		for record in caplog.records
	)


def test_flush_fsyncs_before_replace(tmp_path, monkeypatch):
	"""落盘原语必须 fsync：原子替换只保证原子性、不保证持久性（09-10 P1-6）。

	sidecar 是重启 recovery 的权威状态源；断电丢内容会把 crashed 判定变错。
	与 transcript 落盘（flush+fsync）同口径。
	"""
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	calls: list[str] = []
	real_fsync = turn_snapshot.os.fsync

	def spy(fd: int) -> None:
		calls.append("fsync")
		real_fsync(fd)

	monkeypatch.setattr(turn_snapshot.os, "fsync", spy)
	turn_snapshot.flush(
		turn_snapshot.TurnSnapshot(session_id="sess_fsync_gate", turn_id="t1")
	)
	assert calls == ["fsync"], calls


def test_active_flushes_are_throttled_but_terminal_is_durable(tmp_path, monkeypatch):
	"""逐帧活动态刷写不逐次 fsync；终态必 fsync（P1-6 的性能-持久化分档）。

	一场流式回合有 600+ 次逐帧 `_persist`（2026-10-05 实测 628 次）；逐次
	FlushFileBuffers 会把毫秒级整写推成秒级。恢复判定读的是**终态**快照，
	活动态中间刷写被后续覆盖、无独立持久价值。
	"""
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	calls: list[int] = []
	real_fsync = turn_snapshot.os.fsync

	def spy(fd: int) -> None:
		calls.append(1)
		real_fsync(fd)

	monkeypatch.setattr(turn_snapshot.os, "fsync", spy)
	active = turn_snapshot.TurnSnapshot(
		session_id="sess_throttle_gate", turn_id="t1", status="running"
	)
	turn_snapshot.flush(active)  # 新路径首刷 ⇒ 必 fsync
	assert len(calls) == 1
	active.revision = 2
	turn_snapshot.flush(active)  # 窗口内活动态 ⇒ 不 fsync
	assert len(calls) == 1
	active.status = "succeeded"
	turn_snapshot.flush(active)  # 终态 ⇒ 必 fsync
	assert len(calls) == 2
