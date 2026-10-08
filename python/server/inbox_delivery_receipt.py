"""Release inbox ownership after a user message lands at a sampling boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
	from server.inbox_registry import InboxRegistry


def restore_boundary_delivery(
	registry: InboxRegistry, session_id: str, message_id: str
) -> bool:
	"""Return an undelivered steer to its original queue slot, atomically."""
	if not message_id:
		return False
	with registry._lock:
		registry._ensure_loaded_locked(session_id)
		inflight = registry._inflight.get(session_id, {})
		items = [item for item in inflight.values() if item.delivery_id == message_id]
		if not items:
			return False
		before = registry._capture_session_locked(session_id)
		queue = registry._queues.setdefault(session_id, [])
		for item in items:
			inflight.pop(item.queue_id)
			item.state = "queued"
			item.delivery_id = None
			queue.append(item)
		queue.sort(key=lambda item: item.sequence)
		if not inflight:
			registry._inflight.pop(session_id, None)
		registry._persist_or_restore_locked(session_id, before)
		return True


def finish_boundary_delivery(
	registry: InboxRegistry, session_id: str, message_ids: Iterable[str]
) -> int:
	ids = {str(mid).strip() for mid in message_ids if str(mid).strip()}
	if not ids:
		return 0
	with registry._lock:
		registry._ensure_loaded_locked(session_id)
		items = [
			item
			for item in registry._inflight.get(session_id, {}).values()
			if item.delivery_id in ids
		]
	# Registry uses a non-reentrant lock; its completion method owns its lock.
	registry._finish_delivering(session_id, items)
	return len(items)
