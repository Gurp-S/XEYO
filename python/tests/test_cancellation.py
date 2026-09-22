"""取消树契约：父级传播、子级隔离和 job scope 绑定。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import Aborted, AbortController, CancellationScope
from engine.cancellation import cancel_session_scope, get_session_scope
from server.job_registry import JobRegistry, STATUS_SUCCEEDED


def test_parent_abort_propagates_to_descendants_once() -> None:
	root = CancellationScope(label="session:s1")
	turn = root.child(label="turn:t1")
	tool = turn.child(label="tool:bash")
	reasons: list[str] = []
	tool.on_abort(reasons.append)

	assert root.abort("user_stop") is True
	assert root.abort("late") is False
	assert turn.aborted and tool.aborted
	assert tool.reason == "user_stop"
	assert reasons == ["user_stop"]
	with pytest.raises(Aborted, match="user_stop"):
		tool.raise_if_aborted()


def test_child_abort_does_not_abort_parent() -> None:
	root = AbortController()
	child = root.child(label="tool:timeout")

	child.abort("timeout")

	assert child.aborted
	assert child.reason == "timeout"
	assert not root.aborted


def test_listener_registered_after_abort_runs_immediately() -> None:
	root = AbortController()
	root.abort("shutdown")
	seen: list[str] = []
	root.on_abort(seen.append)
	assert seen == ["shutdown"]


def test_job_scope_inherits_explicit_parent() -> None:
	reg = JobRegistry()
	parent = CancellationScope(label="turn:t1")
	started = False
	job_ref = {"id": ""}

	def producer(push):  # type: ignore[no-untyped-def]
		nonlocal started
		started = True
		while not job_ref["id"] or not reg._aborts[job_ref["id"]].aborted:
			time.sleep(0.005)
		return STATUS_SUCCEEDED, "cancelled by parent"

	job_id, err = reg.start(
		kind="probe",
		label="scope",
		owner_session_id="s1",
		producer=producer,
		parent_abort=parent,
	)
	assert job_id and err == ""
	job_ref["id"] = job_id
	deadline = time.time() + 1
	while not started and time.time() < deadline:
		time.sleep(0.005)
	parent.abort("turn_stopped")
	deadline = time.time() + 1
	while reg._jobs[job_id].status == "running" and time.time() < deadline:
		time.sleep(0.005)

	assert reg._aborts[job_id].aborted
	assert reg._jobs[job_id].status == STATUS_SUCCEEDED


def test_detached_job_has_own_scope() -> None:
	reg = JobRegistry()
	parent = CancellationScope(label="turn:t1")
	job_id, err = reg.start(
		kind="probe",
		label="detached",
		owner_session_id="s1",
		producer=lambda push: (STATUS_SUCCEEDED, ""),
	)
	assert job_id and err == ""
	parent.abort("turn_stopped")
	# producer is intentionally detached; its scope must not inherit this parent.
	assert not reg._aborts[job_id].aborted


def test_session_scope_closes_detached_children() -> None:
	sid = "s-cancel-tree"
	root = get_session_scope(sid)
	job = root.child(label="job:bash-1")

	assert cancel_session_scope(sid, "session_deleted")
	assert job.aborted
	assert job.reason == "session_deleted"
	# Reusing the id after deletion receives a fresh root, not a poisoned one.
	fresh = get_session_scope(sid)
	assert not fresh.aborted
	cancel_session_scope(sid)
