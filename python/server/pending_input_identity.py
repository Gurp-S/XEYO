"""One durable pending owner per explicit client input identity."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from server.inbox_registry import InboxItem, InboxRegistry


class InputIdentityConflict(ValueError):
	"""An existing input identity has different content."""


def find_pending_input(
	registry: InboxRegistry, session_id: str, text: str,
	media_refs: list[str], message_id: str | None,
) -> InboxItem | None:
	"""Caller holds the registry lock; text alone never identifies a retry."""
	if not message_id:
		return None
	owned = [*registry._queues.get(session_id, []),
		*registry._inflight.get(session_id, {}).values(),
		*registry._completed.get(session_id, {}).values()]
	for existing in owned:
		if existing.message_id != message_id:
			continue
		if existing.text != text.strip() or existing.media_refs != media_refs:
			raise InputIdentityConflict("message_id already has different content")
		return existing
	return None
