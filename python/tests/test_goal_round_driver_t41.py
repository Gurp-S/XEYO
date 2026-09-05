"""41 号 goal round driver：admit/mark 语义 + armed 状态机 + settlement 接线。

覆盖（41 号 §12 P0 部分）：
- admit_round CAS / cap 软锁 / CAS miss 不消耗 / 终态 no-op（钩子测试已有部分，
  此处补 per-goal max_rounds 解析与 update/edit）。
- settlement：failed → blocked(reason) + disarm；stopped/cancelled → disarm；
  succeeded + armed → 预约 → 防抖 → 复检 → 合成轮 → admit（进 turn 才计轮）。
- 让位：yield_to_human 取消在途预约（不消耗轮号、不触发提交）。
- cap 到顶 / 候选存在 / disarmed → 不再预约。
- turn_runner settlement 槽：终态派发到 listener（succeeded）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.goal_state import (  # noqa: E402
	GoalConflict,
	GoalStore,
	resolved_max_rounds,
)
from server.goal_round_driver import (  # noqa: E402
	_DriverState,
	GoalRoundDriver,
	default_goal_round_cap,
)


class _FakePool:
	"""goals.py 同款取根：session_cwd 未钉 → cwd。"""

	def __init__(self, cwd: str) -> None:
		self.cwd = cwd
		self._cwds: dict[str, str] = {}

	def session_cwd(self, session_id: str) -> str | None:
		return self._cwds.get(session_id) or None


@pytest.fixture()
def cap32(monkeypatch: pytest.MonkeyPatch) -> int:
	monkeypatch.setattr(
		"server.goal_round_driver.default_goal_round_cap", lambda: 32
	)
	return 32


@pytest.fixture()
def fast_debounce(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr("server.goal_round_driver._ROUND_DEBOUNCE_S", 0.01)


@pytest.fixture()
def store(tmp_path: Path) -> GoalStore:
	return GoalStore(str(tmp_path))


def _armed_driver(tmp_path: Path, sid: str) -> GoalRoundDriver:
	d = GoalRoundDriver()
	d._pool = _FakePool(str(tmp_path))
	d._turn_running = lambda s: False  # type: ignore[method-assign]
	d._states[sid] = _DriverState(armed=True)
	return d


async def _drain_pending(driver: GoalRoundDriver, sid: str) -> None:
	st = driver._states.get(sid)
	if st is not None and st.pending is not None:
		await asyncio.wait_for(asyncio.shield(st.pending), timeout=5)


# ---------------------------------------------------------------------------
# goal_state：max_rounds 解析 / update 编辑 / blocked_reason
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolved_max_rounds_per_goal_overrides_default(
	store: GoalStore, cap32: int
) -> None:
	g = await store.create_and_bind_async(
		title="t", text="x", session_id="s-resolve"
	)
	assert resolved_max_rounds(g, cap32) == cap32
	await store.update_async(g.goal_id, revision=g.revision, max_rounds=7)
	g2 = store.load(g.goal_id)
	assert g2 is not None and resolved_max_rounds(g2, cap32) == 7
	await store.update_async(g2.goal_id, revision=g2.revision, max_rounds=0)
	g3 = store.load(g.goal_id)
	assert g3 is not None and resolved_max_rounds(g3, cap32) == cap32


def test_default_goal_round_cap_positive() -> None:
	assert default_goal_round_cap() >= 1


@pytest.mark.asyncio
async def test_update_async_edits_fields_and_cas(store: GoalStore) -> None:
	g = await store.create_and_bind_async(
		title="t", text="x", session_id="s-edit"
	)
	rev0 = g.revision
	# 无变化 → 不写不 bump。
	same = await store.update_async(g.goal_id, revision=g.revision, title="t")
	assert same.revision == rev0
	# 有变化 → bump。
	edited = await store.update_async(
		g.goal_id, revision=g.revision, title="新标题", max_rounds=9
	)
	assert edited.title == "新标题"
	assert edited.max_rounds == 9
	assert edited.revision == rev0 + 1
	# CAS miss。
	with pytest.raises(GoalConflict):
		await store.update_async(
			g.goal_id, revision=rev0, title="过期写"
		)


@pytest.mark.asyncio
async def test_transition_blocked_reason_set_and_cleared(
	store: GoalStore,
) -> None:
	g = await store.create_and_bind_async(
		title="t", text="x", session_id="s-blocked"
	)
	b = await store.transition_async(
		g.goal_id, "blocked", revision=g.revision, blocked_reason="provider_error"
	)
	assert b.status == "blocked"
	assert b.blocked_reason == "provider_error"
	a = await store.transition_async(b.goal_id, "active", revision=b.revision)
	assert a.status == "active"
	assert a.blocked_reason == "", "恢复 active 清空 blocked_reason"


@pytest.mark.asyncio
async def test_mark_candidate_no_write_when_unchanged(store: GoalStore) -> None:
	g = await store.create_and_bind_async(
		title="t", text="x", session_id="s-mark"
	)
	rev0 = g.revision
	same = await store.mark_candidate_async(
		g.goal_id, revision=g.revision, pending_complete=False
	)
	assert same.revision == rev0, "标志无变化不写"
	set_ = await store.mark_candidate_async(
		g.goal_id, revision=g.revision, pending_complete=True
	)
	assert set_.pending_complete is True
	assert set_.revision == rev0 + 1


# ---------------------------------------------------------------------------
# driver：settlement 状态机
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_settlement_failed_marks_blocked_and_disarms(
	store: GoalStore, tmp_path: Path
) -> None:
	sid = "s-fail"
	await store.create_and_bind_async(title="t", text="x", session_id=sid)
	driver = _armed_driver(tmp_path, sid)

	await driver.on_turn_settled(sid, "failed", "provider_error")

	cur = store.current(sid)
	assert cur is not None
	assert cur.status == "blocked"
	assert cur.blocked_reason == "provider_error", "38 号触发点 #2 补记账"
	assert driver.snapshot(sid)["activation"] == "disarmed"


@pytest.mark.asyncio
async def test_settlement_user_stop_disarms_keeps_active(
	store: GoalStore, tmp_path: Path
) -> None:
	sid = "s-stop"
	await store.create_and_bind_async(title="t", text="x", session_id=sid)
	driver = _armed_driver(tmp_path, sid)

	await driver.on_turn_settled(sid, "stopped", "user_stop")

	cur = store.current(sid)
	assert cur is not None
	assert cur.status == "active", "用户停不置 blocked"
	assert driver.snapshot(sid)["activation"] == "disarmed"


@pytest.mark.asyncio
async def test_settlement_succeeded_schedules_and_admits_round(
	store: GoalStore, tmp_path: Path, fast_debounce: None, cap32: int
) -> None:
	sid = "s-round"
	goal = await store.create_and_bind_async(title="t", text="x", session_id=sid)
	submits: list[tuple[str, int, int]] = []

	async def fake_submit(session_id: str, goal_id: str, round_no: int, cap: int) -> bool:
		submits.append((goal_id, round_no, cap))
		return True

	driver = _armed_driver(tmp_path, sid)
	driver._submit_round = fake_submit  # type: ignore[method-assign]

	await driver.on_turn_settled(sid, "succeeded", "")
	st = driver._states[sid]
	assert st.pending is not None, "armed + succeeded → 预约"
	await _drain_pending(driver, sid)

	assert submits == [(goal.goal_id, 1, cap32)], "首轮 = 第 rounds 轮（1）"
	cur = store.current(sid)
	assert cur is not None
	assert cur.rounds == 2, "进 turn 才 admit（rounds 1 → 2）"
	assert driver.snapshot(sid)["active_round"] is None, "轮后清 active_round"


@pytest.mark.asyncio
async def test_settlement_disarmed_never_schedules(
	store: GoalStore, tmp_path: Path
) -> None:
	sid = "s-disarmed"
	await store.create_and_bind_async(title="t", text="x", session_id=sid)
	driver = _armed_driver(tmp_path, sid)
	driver._states[sid].armed = False

	await driver.on_turn_settled(sid, "succeeded", "")

	assert driver._states[sid].pending is None


@pytest.mark.asyncio
async def test_cap_or_candidate_stops_scheduling(
	store: GoalStore, tmp_path: Path, fast_debounce: None
) -> None:
	sid = "s-cap"
	goal = await store.create_and_bind_async(title="t", text="x", session_id=sid)
	await store.update_async(goal.goal_id, revision=goal.revision, max_rounds=2)
	# 轮次推到超限：两次 admit → rounds=3 > 2 → pending_complete 软锁。
	g2 = store.load(goal.goal_id)
	assert g2 is not None
	await store.admit_round_async(g2.goal_id, revision=g2.revision, cap=2)
	g3 = store.load(goal.goal_id)
	assert g3 is not None
	await store.admit_round_async(g3.goal_id, revision=g3.revision, cap=2)
	cur = store.load(goal.goal_id)
	assert cur is not None and cur.pending_complete is True

	submits: list[Any] = []

	async def fake_submit(session_id: str, goal_id: str, round_no: int, cap: int) -> bool:
		submits.append((goal_id, round_no, cap))
		return True

	driver = _armed_driver(tmp_path, sid)
	driver._submit_round = fake_submit  # type: ignore[method-assign]
	await driver.on_turn_settled(sid, "succeeded", "")
	await _drain_pending(driver, sid)
	assert submits == [], "超 cap / 有候选 → 不再预约"


@pytest.mark.asyncio
async def test_yield_to_human_cancels_pending_without_submit(
	store: GoalStore, tmp_path: Path, fast_debounce: None
) -> None:
	sid = "s-yield"
	await store.create_and_bind_async(title="t", text="x", session_id=sid)
	submits: list[Any] = []

	async def fake_submit(session_id: str, goal_id: str, round_no: int, cap: int) -> bool:
		submits.append((goal_id, round_no, cap))
		return True

	driver = _armed_driver(tmp_path, sid)
	driver._submit_round = fake_submit  # type: ignore[method-assign]
	await driver.on_turn_settled(sid, "succeeded", "")
	st = driver._states[sid]
	assert st.pending is not None

	driver.yield_to_human(sid)
	await asyncio.sleep(0.02)

	assert st.pending is None
	assert submits == [], "让位作废预约，不提交不消耗"
	cur = store.current(sid)
	assert cur is not None and cur.rounds == 1


@pytest.mark.asyncio
async def test_arm_when_idle_schedules_first_round(
	store: GoalStore, tmp_path: Path, fast_debounce: None, cap32: int
) -> None:
	sid = "s-arm"
	goal = await store.create_and_bind_async(title="t", text="x", session_id=sid)
	submits: list[tuple[str, int, int]] = []

	async def fake_submit(session_id: str, goal_id: str, round_no: int, cap: int) -> bool:
		submits.append((goal_id, round_no, cap))
		return True

	driver = GoalRoundDriver()
	driver._pool = _FakePool(str(tmp_path))
	driver._turn_running = lambda s: False  # type: ignore[method-assign]
	driver._submit_round = fake_submit  # type: ignore[method-assign]

	snap = driver.arm(sid)
	assert snap["activation"] == "armed"
	assert driver._states[sid].pending is not None, "armed 且空闲 → 立即预约"
	await _drain_pending(driver, sid)

	assert submits == [(goal.goal_id, 1, cap32)]


@pytest.mark.asyncio
async def test_round_without_request_env_aborts_cleanly(
	store: GoalStore, tmp_path: Path, fast_debounce: None
) -> None:
	sid = "s-noenv"
	await store.create_and_bind_async(title="t", text="x", session_id=sid)
	driver = _armed_driver(tmp_path, sid)
	await driver.on_turn_settled(sid, "succeeded", "")
	await _drain_pending(driver, sid)
	cur = store.current(sid)
	assert cur is not None
	assert cur.rounds == 1, "无请求环境 → 合成轮放弃，不计轮"
	assert driver.snapshot(sid)["active_round"] is None


@pytest.mark.asyncio
async def test_disarm_cancels_pending(store: GoalStore, tmp_path: Path) -> None:
	sid = "s-disarm"
	await store.create_and_bind_async(title="t", text="x", session_id=sid)
	driver = _armed_driver(tmp_path, sid)
	st = driver._states[sid]
	st.pending = asyncio.create_task(asyncio.sleep(30))

	snap = driver.disarm(sid)

	assert snap["activation"] == "disarmed"
	assert st.pending is None
	await asyncio.sleep(0.01)  # 让取消落地
	assert driver.snapshot(sid)["pending"] is False


# ---------------------------------------------------------------------------
# turn_runner settlement 槽
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_turn_runner_dispatches_settlement_listener() -> None:
	from engine.turn_runner import TurnRunner, set_turn_settlement_listener

	class _Pool:
		def try_begin(self, sid: str) -> int:
			return 1

		def touch_busy(self, sid: str) -> None:
			pass

		def end(self, sid: str, lease_id: int) -> None:
			pass

	async def producer():
		yield (1, b'data: {"x"}\n\n', "delta")

	events: list[tuple[str, str, str]] = []
	done = asyncio.Event()

	async def listener(sid: str, final_status: str, stop_reason: str) -> None:
		events.append((sid, final_status, stop_reason))
		done.set()

	set_turn_settlement_listener(listener)
	try:
		runner = TurnRunner(_Pool())
		await runner.start(
			session_id="s-listen",
			lease_id=1,
			model="m",
			goal_text="",
			user_message_id="u1",
			producer=producer,
		)
		await asyncio.wait_for(done.wait(), timeout=5)
		assert events and events[0][0] == "s-listen"
		assert events[0][1] == "succeeded"
		assert events[0][2] == ""
	finally:
		set_turn_settlement_listener(None)
