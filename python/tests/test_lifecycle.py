from __future__ import annotations

from engine.budget import BudgetTracker
from engine.lifecycle import AgentLifecycle


def test_lifecycle_finalization_only_rejects_new_agent() -> None:
	lifecycle = AgentLifecycle()
	lifecycle.enter_finalizing("max_turns")
	assert lifecycle.phase == "finalizing"
	assert lifecycle.permits_tool("Read")
	assert lifecycle.permits_tool("Write")
	assert not lifecycle.permits_tool("Agent")


def test_lifecycle_wall_pressure_requires_armed_deadline() -> None:
	lifecycle = AgentLifecycle(finalization_reserve_s=30)
	lifecycle.observe_wall(10, armed=False)
	assert lifecycle.phase == "running"
	lifecycle.observe_wall(10, armed=True)
	assert lifecycle.phase == "budget_pressure"


def test_lifecycle_has_explicit_verification_phase() -> None:
	lifecycle = AgentLifecycle()
	lifecycle.begin_verifying()
	assert lifecycle.phase == "verifying"
	lifecycle.finish("succeeded", "verified")
	assert lifecycle.phase == "succeeded"


def test_budget_grace_enters_lifecycle_and_terminal_is_recorded() -> None:
	budget = BudgetTracker(max_turns=1)
	assert budget.lifecycle_snapshot()["phase"] == "running"
	assert budget.prepare_next_turn()
	budget.begin_turn()
	assert budget.prepare_next_turn()
	assert budget.lifecycle_snapshot()["phase"] == "finalizing"
	assert budget.lifecycle_snapshot()["reason"] == "max_turns"
	budget.mark_terminal("succeeded", "final text delivered")
	assert budget.lifecycle_snapshot()["phase"] == "succeeded"
