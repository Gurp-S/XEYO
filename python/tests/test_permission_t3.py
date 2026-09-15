"""T3 回归：权限挂起风险分级 TTL、intent、统一文案、审计配对。"""

from __future__ import annotations

import asyncio

import pytest

from permissions.pending_ttl import (
	CANCELLED_COPY,
	PENDING_DANGER_TTL_SECONDS,
	PENDING_PANEL_TTL_SECONDS,
	REJECTED_COPY,
	UNAVAILABLE_COPY,
	intent_for,
	ttl_for_request,
)


# ---------- 风险分级 TTL ----------


def test_ttl_plain_permission_is_180s():
	assert ttl_for_request(reason="needs_confirmation") == PENDING_PANEL_TTL_SECONDS


def test_ttl_danger_reason_is_60s():
	assert (
		ttl_for_request(reason="dangerous_path", matched_rule="write_risk_ask")
		== PENDING_DANGER_TTL_SECONDS
	)
	assert (
		ttl_for_request(reason="protected_metadata")
		== PENDING_DANGER_TTL_SECONDS
	)
	assert ttl_for_request(matched_rule="bash_secret_deny", reason="ask") == (
		PENDING_DANGER_TTL_SECONDS
	)


def test_intent_choice_vs_confirm():
	assert intent_for(choices=("deny", "remind", "allow")) == "choice"
	assert intent_for(choices=()) == "confirm"
	assert intent_for() == "confirm"


# ---------- store 分级 ----------


@pytest.mark.asyncio
async def test_store_creates_risk_graded_expiry():
	from permissions.store import PendingPermissionStore

	store = PendingPermissionStore()
	danger = store.create(
		session_id="s",
		turn_id="t",
		tool_name="Bash",
		tool_input={},
		reason="dangerous_path",
		prompt="p",
	)
	plain = store.create(
		session_id="s",
		turn_id="t",
		tool_name="Write",
		tool_input={},
		reason="needs_confirmation",
		prompt="p",
	)
	assert danger.expires_at is not None and plain.expires_at is not None
	gap = (plain.expires_at or 0) - (danger.expires_at or 0)
	assert gap == pytest.approx(
		PENDING_PANEL_TTL_SECONDS - PENDING_DANGER_TTL_SECONDS, abs=1.0
	)


@pytest.mark.asyncio
async def test_store_wait_without_expiry_never_times_out_early():
	"""显式 TTL<=0（交互式语义）→ wait 不因 expires_at 提前返回。"""
	from permissions.store import PendingPermissionStore

	store = PendingPermissionStore(ttl_seconds=0)
	item = store.create(
		session_id="s",
		turn_id="t",
		tool_name="AskUserQuestion",
		tool_input={},
		reason="interactive",
		prompt="?",
	)
	assert item.expires_at is None
	waiter = asyncio.create_task(store.wait(item.request_id))
	await asyncio.sleep(0.05)
	assert not waiter.done()  # 仍未超时
	store.resolve(item.request_id, approved=True, actor="t")
	assert (await asyncio.wait_for(waiter, timeout=1.0)).resolved is True


@pytest.mark.asyncio
async def test_store_wait_times_out_at_graded_ttl():
	from permissions.store import PendingPermissionStore

	store = PendingPermissionStore(ttl_seconds=0.05)
	item = store.create(
		session_id="s",
		turn_id="t",
		tool_name="Bash",
		tool_input={},
		reason="dangerous_path",
		prompt="p",
	)
	res = await asyncio.wait_for(store.wait(item.request_id), timeout=2.0)
	assert res is not None and not res.resolved  # 超时但未 resolve


# ---------- 统一文案 ----------


def test_unified_copies_are_distinct_and_nonempty():
	assert REJECTED_COPY and CANCELLED_COPY and UNAVAILABLE_COPY
	assert len({REJECTED_COPY, CANCELLED_COPY, UNAVAILABLE_COPY}) == 3


# ---------- 审计配对（pending ↔ resolved，ALLOW 也审计）----------


@pytest.mark.asyncio
async def test_allow_is_audited_paired_with_pending(tmp_path):
	from audit.log import AuditLog, reset_default_audit_log

	log_path = tmp_path / "audit.jsonl"
	reset_default_audit_log()
	import audit.log as audit_mod

	audit_mod._default = AuditLog(log_path)  # type: ignore[attr-defined]
	from engine.task_state import SessionTaskState
	from engine.permission_coordinator import PermissionCoordinator
	from permissions.store import PendingPermissionStore

	coord = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=SessionTaskState(session_id="s-t3"),
		session_id="s-t3",
		turn_id="t",
	)
	rid = coord.request(
		tool_name="Bash", tool_input={}, reason="r", prompt="p"
	)
	coord.resolve(rid, approved=True, actor="desktop")
	rows = [__import__("json").loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
	kinds = [r["kind"] for r in rows]
	assert "permission.pending" in kinds and "permission.resolved" in kinds
	assert kinds.index("permission.pending") < kinds.index("permission.resolved")
	resolved = next(r for r in rows if r["kind"] == "permission.resolved")
	assert resolved["approved"] is True  # ALLOW 同样入审计
	# intent 默认 confirm（无 choices）。
	pending = next(r for r in rows if r["kind"] == "permission.pending")


def test_pending_event_intent_default_and_choice():
	from msgtypes.events import PermissionPendingEvent

	ev = PermissionPendingEvent(
		request_id="r", tool_name="Bash", tool_input={}, reason="r", prompt="p"
	)
	assert ev.intent == "confirm"
	ev2 = PermissionPendingEvent(
		request_id="r",
		tool_name="Bash",
		tool_input={},
		reason="r",
		prompt="p",
		choices=["deny", "remind", "allow"],
		intent="choice",
	)
	assert ev2.intent == "choice"


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))
