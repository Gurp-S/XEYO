"""Turn identity checks and actions share the turn lifecycle lock.

Lock order: inbox -> runner -> pool. Never acquire inbox from a runner callback.
"""
from __future__ import annotations

import uuid


class TurnMismatch(ValueError):
    pass


def _current_locked(runner, session_id, expected_turn_id):
    turn = runner._turn_locked(session_id)
    if (not expected_turn_id or turn is None or turn.done.is_set()
            or getattr(turn, 'finalizing', False) or turn.turn_id != expected_turn_id):
        raise TurnMismatch("target turn is no longer active")
    return turn


def interrupt_turn(runner, pool, registry, session_id, expected_turn_id):
    from server.inbox_registry import InboxPersistenceError

    pause_error = False
    with registry._lock:
        with runner._tlock:
            turn = _current_locked(runner, session_id, expected_turn_id)
            if not pool.interrupt(session_id, expected_lease_id=turn.lease_id):
                raise TurnMismatch("target turn lease is no longer active")
            turn.status = "stopping"
            turn.stop_reason = "user_stop"
            turn.revision += 1
            registry._ensure_loaded_locked(session_id)
            registry._paused.add(session_id)
            if not registry._persist_session_locked(session_id):
                registry._reconcile_pending.add(session_id)
                pause_error = True
    # _persist captures a snapshot under the non-reentrant lifecycle lock and
    # fences its write by turn identity/revision. Never call it while holding
    # lifecycle or inbox locks: interrupt's worker would deadlock the loop.
    runner._persist(turn, force_durable=True)
    if pause_error:
        raise InboxPersistenceError(session_id)
    return {"ok": True, "turn_id": expected_turn_id}


def submit_to_turn(registry, session_id, text, *, media_refs, message_id, expected_turn_id):
    from engine import t_now_steer
    from engine.turn_runner import get_turn_runner
    from server.inbox_registry import InboxItem
    from server.pending_input_identity import find_pending_input

    runner = get_turn_runner()
    with registry._lock:
        with runner._tlock:
            _current_locked(runner, session_id, expected_turn_id)
            registry._ensure_loaded_locked(session_id)
            existing = find_pending_input(registry, session_id, text, media_refs, message_id)
            if existing:
                return existing, existing.state in ("delivering", "delivered")
            if len(registry._inflight.get(session_id, {})) >= t_now_steer.MAX_QUEUED_PER_SESSION:
                return None
            before = registry._capture_session_locked(session_id)
            registry._next_sequence += 1
            mid = message_id or uuid.uuid4().hex
            item = InboxItem(queue_id=uuid.uuid4().hex[:12], text=text.strip(),
                             media_refs=list(media_refs), message_id=mid, delivery_id=mid,
                             state="delivering", sequence=registry._next_sequence)
            registry._inflight.setdefault(session_id, {})[item.queue_id] = item
            registry._persist_or_restore_locked(session_id, before)
            admitted = t_now_steer.push(session_id, text, images=media_refs, message_id=mid, persist_pending=False)
    if admitted:
        return item, True
    registry.restore_boundary_delivery(session_id, mid)
    return item, False
