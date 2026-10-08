"""Queue stop is durable execution state, independent of snapshot reads."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from server.inbox_registry import InboxRegistry


def pause_queue(registry: InboxRegistry, session_id: str) -> None:
	from server.inbox_registry import InboxPersistenceError

	with registry._lock:
		registry._ensure_loaded_locked(session_id)
		registry._paused.add(session_id)
		if not registry._persist_session_locked(session_id):
			# Hold remains in memory; failed durability cannot turn into execution.
			registry._reconcile_pending.add(session_id)
			raise InboxPersistenceError(session_id)
