"""Shared execution-layer check for writes to archived sessions."""

from server.deps import api_error


def require_writable_session(session_id: str) -> None:
	from engine.title import read_archive

	if read_archive(session_id) is not None:
		raise api_error(409, "Permission denied: session is archived", "session_archived")
