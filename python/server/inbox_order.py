"""Atomic reordering of queued items; delivery receipts and identities stay intact."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from server.inbox_registry import InboxRegistry


def reorder_pending(registry: InboxRegistry, session_id: str, expected: list[str], order: list[str]) -> bool:
	if len(order) != len(set(order)) or set(expected) != set(order):
		return False
	with registry._lock:
		registry._ensure_loaded_locked(session_id)
		queue = registry._queues.get(session_id, [])
		pending = [item for item in queue if item.state == "queued"]
		if [item.queue_id for item in pending] != expected:
			return False
		if order == expected:
			return True
		before = registry._capture_session_locked(session_id)
		by_id = {item.queue_id: item for item in pending}
		positions = iter(sorted(item.sequence for item in pending))
		for queue_id in order:
			by_id[queue_id].sequence = next(positions)
		queue.sort(key=lambda item: item.sequence)
		registry._persist_or_restore_locked(session_id, before)
		return True
