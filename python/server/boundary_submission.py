"""Durable ownership for direct steer, separate from delivered transcript rows."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from server.pending_input_identity import find_pending_input

if TYPE_CHECKING:
	from server.inbox_registry import InboxItem, InboxRegistry


def submit_boundary(
	registry: InboxRegistry,
	session_id: str,
	text: str,
	*,
	media_refs: list[str],
	message_id: str | None,
) -> tuple[InboxItem, bool] | None:
	"""Persist before exposure; failed boundary admission retains the same inbox owner.

	Direct steer keeps its existing text allowance and bounded boundary capacity.
	The recovery owner uses inbox persistence, not the smaller ordinary enqueue limit.
	"""
	from engine import t_now_steer
	from server.inbox_registry import InboxItem

	with registry._lock:
		registry._ensure_loaded_locked(session_id)
		existing = find_pending_input(registry, session_id, text, media_refs, message_id)
		if existing:
			return existing, existing.state in ("delivering", "delivered")
		if len(registry._inflight.get(session_id, {})) >= t_now_steer.MAX_QUEUED_PER_SESSION:
			return None
		before = registry._capture_session_locked(session_id)
		registry._next_sequence += 1
		mid = message_id or uuid.uuid4().hex
		item = InboxItem(
			queue_id=uuid.uuid4().hex[:12], text=text.strip(),
			media_refs=list(media_refs), message_id=mid, delivery_id=mid,
			state="delivering", sequence=registry._next_sequence,
		)
		registry._inflight.setdefault(session_id, {})[item.queue_id] = item
		registry._persist_or_restore_locked(session_id, before)
	if t_now_steer.push(session_id, text, images=media_refs, message_id=mid, persist_pending=False):
		# The busy observation may precede the final settlement callback. If that
		# callback already ran before push, it cannot see this pending boundary.
		if registry._session_idle(session_id):
			from server.steer_settle_fallback import fallback_pending

			if fallback_pending(session_id):
				return item, False
		return item, True
	# Admission failed, but the request already has durable queue ownership.
	# Preserve it in its original sequence, without a second enqueue or text limit.
	registry.restore_boundary_delivery(session_id, mid)
	return item, False
