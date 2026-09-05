from __future__ import annotations

import asyncio

import pytest

from engine.plan import PlanEngine


@pytest.mark.asyncio
async def test_plan_engine_resolve_approves_waiting_plan() -> None:
	engine = PlanEngine(ttl_seconds=5)
	pending = engine.create(
		session_id="s1",
		turn_id="t1",
		plan="1. Read\n2. Fix",
	)

	async def approve() -> None:
		await asyncio.sleep(0)
		assert engine.resolve(pending.request_id, True, actor="desktop")

	approved = asyncio.create_task(engine.wait(pending.request_id))
	await approve()
	resolved = await approved
	assert resolved is not None
	assert resolved.approved is True
	assert resolved.actor == "desktop"
	assert engine.resolve(pending.request_id, False) is False


@pytest.mark.asyncio
async def test_plan_engine_timeout_resolves_empty() -> None:
	engine = PlanEngine(ttl_seconds=0.01)
	pending = engine.create(
		session_id="s1",
		turn_id="t1",
		plan="plan",
	)
	resolved = await engine.wait(pending.request_id, timeout=0.01)
	assert resolved is not None
	assert resolved.approved is None
	assert not resolved.resolved
