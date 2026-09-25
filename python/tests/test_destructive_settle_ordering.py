"""结算标志的发布顺序：``settled`` 必须晚于账本真正落定。

起因是 ``test_start_background_guard_settles`` 的偶发红：那条用例先轮询
``plan.settled``、再断言每条操作已经 ``completed``。旧实现先置位、再在锁**外**
跑 transition，于是「settled=True 但操作还是 started」这个窗口真实存在，
机器一忙就被踩到。这里把顺序钉死，并锁住并发结算只跑一次。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rewind.context import RewindExecutionContext  # noqa: E402
from rewind.journal import OperationJournal  # noqa: E402
from rewind.snapshot import SnapshotStore  # noqa: E402
from tools.bash_tool.destructive_guard import (  # noqa: E402
	plan_destructive_snapshot,
	settle_destructive_plan,
)


def _ctx(tmp_path: Path, session_id: str = "s-settle") -> RewindExecutionContext:
	return RewindExecutionContext(
		session_id=session_id,
		turn_id="turn-1",
		revision_id=None,
		journal=OperationJournal(
			session_id, sessions_dir=tmp_path / "sessions", enabled=True
		),
		snapshots=SnapshotStore(
			session_id, root=tmp_path / "snapshots", enabled=True
		),
	)


def _plan(tmp_path: Path):
	ws = tmp_path / "ws"
	ws.mkdir(parents=True, exist_ok=True)
	(ws / "a.txt").write_bytes(b"A")
	(ws / "b.txt").write_bytes(b"B")
	ctx = _ctx(tmp_path)
	plan = plan_destructive_snapshot("rm a.txt b.txt", str(ws), ctx)
	assert plan is not None
	return ctx, plan


def test_settled_is_published_only_after_the_ledger_settles(tmp_path, monkeypatch):
	ctx, plan = _plan(tmp_path)
	assert plan.operation_ids

	seen: list[bool] = []
	real = ctx.journal.transition_operation

	def spy(operation_id, status, **kw):
		# 结算进行中标志必须还是 False：置位早于这里，观察者就能读到 started。
		seen.append(plan.settled)
		return real(operation_id, status, **kw)

	monkeypatch.setattr(ctx.journal, "transition_operation", spy)

	settle_destructive_plan(plan, executed=True)

	assert seen == [False] * len(seen)
	assert plan.settled is True
	for op_id in plan.operation_ids:
		assert ctx.journal.get_operation(op_id).status == "completed"


def test_concurrent_settle_transitions_the_ledger_exactly_once(tmp_path):
	ctx, plan = _plan(tmp_path)
	real = ctx.journal.transition_operation
	calls: list[str] = []
	lock = threading.Lock()

	def spy(operation_id, status, **kw):
		with lock:
			calls.append(operation_id)
		return real(operation_id, status, **kw)

	ctx.journal.transition_operation = spy  # type: ignore[method-assign]
	barrier = threading.Barrier(2)

	def worker() -> None:
		barrier.wait(timeout=5)
		settle_destructive_plan(plan, executed=True)

	threads = [threading.Thread(target=worker) for _ in range(2)]
	for t in threads:
		t.start()
	for t in threads:
		t.join(timeout=15)

	assert plan.settled is True
	# 第二个结算者要等锁、看到已 settled 后直接返回：账本不被走两遍。
	assert sorted(calls) == sorted(plan.operation_ids)


def test_a_failing_transition_still_settles_the_rest(tmp_path, monkeypatch):
	"""fail-open 纪律：单条 transition 抛错不能卡住其余结算，也不能不发布 settled。"""
	ctx, plan = _plan(tmp_path)
	assert len(plan.operation_ids) >= 2
	real = ctx.journal.transition_operation
	first = plan.operation_ids[0]

	def spy(operation_id, status, **kw):
		if operation_id == first:
			raise RuntimeError("journal busy")
		return real(operation_id, status, **kw)

	monkeypatch.setattr(ctx.journal, "transition_operation", spy)

	settle_destructive_plan(plan, executed=True)

	assert plan.settled is True
	assert ctx.journal.get_operation(plan.operation_ids[-1]).status == "completed"
