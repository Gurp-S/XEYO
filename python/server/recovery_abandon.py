"""Identity-checked, serialized recovery abandonment."""

import json
import time

from engine import turn_snapshot
from engine.turn_runner import get_turn_runner
from server.deps import api_error
from server.session_write_guard import require_writable_session


def abandon_recovery(session_id: str, turn_id: str, *, busy: bool) -> dict:
	require_writable_session(session_id)
	public = get_turn_runner().get_public(session_id)
	if busy or (public and (public.turn_id != turn_id or public.status not in {"recovery_required", "stopped"})):
		raise api_error(409, "recovery turn is no longer current", "recovery_conflict")
	path = turn_snapshot.path_for(session_id)
	# All snapshot writers use this lock. A new turn cannot be overwritten
	# between the identity check and the durable replacement.
	with turn_snapshot._serialized_flush(path):
		snap = turn_snapshot.hydrate(session_id)
		if snap is None or snap.turn_id != turn_id or snap.status not in {"recovery_required", "stopped"}:
			raise api_error(409, "recovery turn is no longer current", "recovery_conflict")
		if snap.status == "recovery_required":
			snap.status = "stopped"
			snap.stop_reason = "user_abandon"
			snap.waiting_permission = False
			snap.revision += 1
			snap.updated_at = time.time()
			try:
				turn_snapshot._atomic_write(path, json.dumps(snap.to_dict(), ensure_ascii=False), durable=True)
			except OSError as exc:
				raise api_error(503, "recovery state could not be persisted", "recovery_unavailable") from exc
		return {"ok": True, "status": snap.status, "turn_id": snap.turn_id}
