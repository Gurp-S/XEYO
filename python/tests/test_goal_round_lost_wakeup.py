"""Goal 自动续跑的丢唤醒回归（2026-10-13）。

结构性根因与 JobRegistry 的丢唤醒**同形**：`_schedule` 用"在途任务是否存在"
去重，于是"快 turn 的 settlement 落在旧 `_round_task` 尚未结束"时，这次预约
请求被旧 pending 吃掉 —— goal 仍 `armed`、仍 active，但**自动执行静默停摆**。

正确判据（Monitor 语义）：去重看"队列空"，不看"任务在跑"。
本文件在修复前必须失败。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.goal_round_driver import _DriverState, GoalRoundDriver  # noqa: E402

SID = "s-goal-wakeup"


@pytest.mark.asyncio
async def test_fast_settlement_during_pending_round_is_not_lost(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""第一轮在 `_submit_round` 内部就收到 succeeded ⇒ 必须再排一轮。"""
	driver = GoalRoundDriver()
	st = driver._states.setdefault(SID, _DriverState())
	st.armed = True

	monkeypatch.setattr("server.goal_round_driver._ROUND_DEBOUNCE_S", 0.01)
	monkeypatch.setattr(driver, "_session_root", lambda _sid: "")

	submits = 0
	seen_tasks: list[object] = []

	async def fake_precheck(_sid: str):
		return (SimpleNamespace(goal_id="g1", rounds=0, revision=1), 10)

	async def fake_submit(_sid: str, _gid: str, _round: int, _cap: int) -> bool:
		nonlocal submits
		submits += 1
		seen_tasks.append(asyncio.current_task())
		if submits == 1:
			# 关键时序：detached turn 极快结束，而当前 `_round_task` 还没 finally。
			await driver.on_turn_settled(SID, "succeeded", "")
		return True

	monkeypatch.setattr(driver, "_precheck", fake_precheck)
	monkeypatch.setattr(driver, "_submit_round", fake_submit)

	driver._schedule(SID)
	first = st.pending
	assert first is not None, "预约未建立"

	await first
	await asyncio.sleep(0.15)

	# 本质不变量 = "预约请求没被丢掉"：必须有第二次提交，且它跑在一个**新**任务上。
	assert submits >= 2, "快结算被旧 pending 吃掉：goal 静默停摆"
	assert len({id(t) for t in seen_tasks}) >= 2, "重排必须是一个新任务，不是复用旧任务"


@pytest.mark.asyncio
async def test_settlement_does_not_reschedule_when_disarmed(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""反向不变量：disarm 后不得因为"补排"而复活预约。"""
	driver = GoalRoundDriver()
	st = driver._states.setdefault(SID, _DriverState())
	st.armed = False

	monkeypatch.setattr("server.goal_round_driver._ROUND_DEBOUNCE_S", 0.01)
	monkeypatch.setattr(driver, "_session_root", lambda _sid: "")

	async def fake_submit(_sid: str, _gid: str, _round: int, _cap: int) -> bool:
		await driver.on_turn_settled(SID, "succeeded", "")
		return True

	monkeypatch.setattr(
		driver, "_precheck", lambda _sid: _async_value((SimpleNamespace(goal_id="g1", rounds=0, revision=1), 10))
	)
	monkeypatch.setattr(driver, "_submit_round", fake_submit)

	# 未 arm ⇒ 不应产生任何预约
	driver._schedule(SID)
	assert st.pending is None
	await asyncio.sleep(0.05)
	assert st.pending is None, "disarmed 状态不得被 settlement 复活"


async def _async_value(v):
	return v
