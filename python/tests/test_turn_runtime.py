"""TurnRuntime：回合预算/收尾状态机契约。"""

from __future__ import annotations

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.turn_runtime import TurnRuntime


def test_turn_runtime_exposes_wrap_then_budget_stop() -> None:
	runtime = TurnRuntime(
		budget=BudgetTracker(max_turns=1),
		abort=AbortController(),
		wrap_quota_left=2,
	)

	# 初始请求 + 三个 grace 请求都属于可继续的真实模型回合。
	for _ in range(4):
		assert runtime.prepare_next_turn() == "continue"
		runtime.begin_turn()

	assert runtime.prepare_next_turn() == "wrap_up"
	assert runtime.forced_wrap_up is True
	assert runtime.prepare_next_turn() == "stop_budget"


def test_turn_runtime_owns_wrap_quota_and_lifecycle_gate() -> None:
	runtime = TurnRuntime(
		budget=BudgetTracker(),
		abort=AbortController(),
		wrap_quota_left=2,
		forced_wrap_up=True,
	)
	assert runtime.consume_wrap_quota() is True
	assert runtime.consume_wrap_quota() is True
	assert runtime.consume_wrap_quota() is False
	assert runtime.permits_tool("Write") is True
	assert runtime.permits_tool("Agent") is False


def test_turn_runtime_abort_is_checked_before_budget() -> None:
	abort = AbortController()
	runtime = TurnRuntime(
		budget=BudgetTracker(),
		abort=abort,
		wrap_quota_left=0,
	)
	abort.abort(reason="session_deleted")
	assert runtime.prepare_next_turn() == "stop_aborted"
