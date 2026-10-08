"""Atomic disk snapshots for the user inbox queue.

This is queue recovery state, not model context. Pending user messages stay out of
the transcript until the delivery path commits them there.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from session.persistence import (
	default_sessions_dir,
	should_persist,
	transcript_path,
)
from session.record_transcript import transcript_read_paths

_logger = logging.getLogger("xeyo.inbox.persistence")
_VERSION = 1


def inbox_state_path(session_id: str) -> Path:
	# Session ids are not filename-safe identities (e.g. ':' and '__' normalize
	# to the same path). A private hash namespace keeps every session isolated.
	key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
	return default_sessions_dir() / ".inbox" / f"{key}.json"


def load_inbox_snapshot(session_id: str) -> dict[str, Any]:
	if not should_persist():
		return {"items": [], "paused": False}
	path = inbox_state_path(session_id)
	try:
		with path.open("r", encoding="utf-8") as handle:
			payload = json.load(handle)
	except FileNotFoundError:
		return {"items": [], "paused": False}
	except (OSError, json.JSONDecodeError) as exc:
		_logger.warning("inbox state read failed sid=%s path=%s", session_id, path, exc_info=True)
		raise InboxStateReadError(session_id) from exc
	if (
		not isinstance(payload, dict)
		or payload.get("version") != _VERSION
		or payload.get("session_id") != session_id
		or not isinstance(payload.get("items"), list)
		or not isinstance(payload.get("paused", False), bool)
	):
		_logger.warning("inbox state has an unsupported shape sid=%s path=%s", session_id, path)
		raise InboxStateReadError(session_id)
	return {"items": [item for item in payload["items"] if isinstance(item, dict)],
		"paused": payload.get("paused", False)}


def load_inbox_state(session_id: str) -> list[dict[str, Any]]:
	return load_inbox_snapshot(session_id)["items"]


class InboxStateReadError(RuntimeError):
	"""Persisted queue state could not be trusted or read."""

	def __init__(self, session_id: str) -> None:
		self.session_id = session_id
		super().__init__(f"inbox state unavailable for session {session_id}")


def save_inbox_state(session_id: str, items: list[dict[str, Any]], paused: bool = False) -> bool:
	if not should_persist():
		return True
	path = inbox_state_path(session_id)
	if not items and not paused:
		return delete_inbox_state(session_id)

	tmp = path.with_name(path.name + ".tmp")
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		with tmp.open("w", encoding="utf-8", newline="") as handle:
			json.dump(
				{"version": _VERSION, "session_id": session_id, "items": items, **({"paused": True} if paused else {})},
				handle,
				ensure_ascii=False,
				separators=(",", ":"),
			)
			handle.flush()
			os.fsync(handle.fileno())
		os.replace(tmp, path)
		return True
	except (OSError, TypeError, ValueError):
		_logger.warning("inbox state write failed sid=%s path=%s", session_id, path, exc_info=True)
		try:
			tmp.unlink(missing_ok=True)
		except OSError:
			pass
		return False


def delete_inbox_state(session_id: str) -> bool:
	"""Remove durable state even when persistence has since been disabled."""
	path = inbox_state_path(session_id)
	try:
		path.unlink(missing_ok=True)
		path.with_name(path.name + ".tmp").unlink(missing_ok=True)
		return True
	except OSError:
		_logger.warning("inbox state clear failed sid=%s path=%s", session_id, path, exc_info=True)
		return False


def transcript_message_ids(session_id: str, targets: set[str]) -> set[str]:
	"""Find only requested ids, avoiding a full transcript-sized id set."""
	if not targets:
		return set()
	needles = {message_id: json.dumps(message_id, ensure_ascii=False).encode("utf-8") for message_id in targets}
	found: set[str] = set()
	paths = transcript_read_paths(transcript_path(session_id))
	# A delivering row is normally at the active transcript tail. Scan newest files
	# first and stop as soon as every anchor has been found.
	for path in reversed(paths):
		try:
			with path.open("rb") as handle:
				for line in handle:
					candidates = [
						message_id
						for message_id, needle in needles.items()
						if message_id not in found and needle in line
					]
					if not candidates:
						continue
					try:
						row = json.loads(line)
					except (UnicodeDecodeError, json.JSONDecodeError):
						continue
					message_id = row.get("id") if isinstance(row, dict) else None
					if message_id in candidates:
						found.add(message_id)
						if found == targets:
							return found
		except OSError:
			continue
	return found
