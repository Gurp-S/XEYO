"""runtime checkpoint 旁路契约。"""

from __future__ import annotations

import pytest

from engine.runtime_checkpoint import RuntimeCheckpointStore
from engine.runtime_recovery import compare_runtime_checkpoint


def test_checkpoint_round_trip_is_atomic_and_versioned(tmp_path) -> None:  # type: ignore[no-untyped-def]
	store = RuntimeCheckpointStore("s1", enabled=True, sessions_dir=tmp_path)
	snapshot = {
		"session_id": "s1",
		"context": {"runtime": "local", "tool_schema_hash": "sha256:x"},
		"jobs": [],
	}

	assert store.save(snapshot)
	assert store.load() == snapshot
	assert store.path.is_file()
	assert not store.path.with_name("runtime.json.tmp").exists()


def test_checkpoint_disabled_does_not_write(tmp_path) -> None:  # type: ignore[no-untyped-def]
	store = RuntimeCheckpointStore("s2", enabled=False, sessions_dir=tmp_path)
	assert store.save({"session_id": "s2"}) is False
	assert store.load() is None
	assert not store.path.exists()


def test_runtime_recovery_marks_missing_processes_as_drift(tmp_path) -> None:  # type: ignore[no-untyped-def]
	report = compare_runtime_checkpoint(
		{
			"context": {
				"runtime": "docker",
				"container_id": "c-old",
				"runtime_profile_id": "profile:p1",
			},
			"jobs": [{"job_id": "j1", "status": "running"}],
		},
		{
			"context": {
				"runtime": "docker",
				"container_id": "c-new",
				"runtime_profile_id": "profile:p1",
			},
			"jobs": [],
		},
	)
	assert report.state == "drifted"
	assert report.requires_manual_action is True
	assert "container_id" in report.differences
	assert "active_jobs_not_present" in report.differences


@pytest.mark.asyncio
async def test_query_engine_checks_previous_checkpoint_before_start_save(tmp_path) -> None:  # type: ignore[no-untyped-def]
	"""turn-start save 不能先覆盖掉上一运行面的漂移证据。"""
	from engine.query_engine import build_default_engine

	first = build_default_engine(
		cwd=str(tmp_path),
		model_backend="fake",
		runtime_checkpoint=True,
		session_id="checkpoint-recovery-test",
		runtime="docker",
		container_id="container-old",
	)
	async for _ in first.submit("hello"):
		pass

	second = build_default_engine(
		cwd=str(tmp_path),
		model_backend="fake",
		runtime_checkpoint=True,
		session_id="checkpoint-recovery-test",
		runtime="docker",
		container_id="container-new",
	)
	async for _ in second.submit("hello"):
		pass

	recovery = second.runtime_snapshot()["recovery"]
	assert recovery["checked"] is True
	assert recovery["state"] == "drifted"
	assert "container_id" in recovery["differences"]
