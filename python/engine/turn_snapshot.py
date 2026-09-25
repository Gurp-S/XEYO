"""TurnSnapshot — 会话级可恢复 turn 状态（与 messages / working.json 并列）。

与 SessionTaskState（进程内权威状态机）不同：本模块落盘，供刷新 reattach / 重启 recovery。
"""

from __future__ import annotations

from _thread import LockType
from contextlib import contextmanager
import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal

_logger = logging.getLogger("xeyo.turn_snapshot")

TurnStatus = Literal[
	"queued",
	"running",
	"waiting_permission",
	"stopping",
	"stopped",
	"succeeded",
	"failed",
	"recovery_required",
]

_ACTIVE = frozenset({"queued", "running", "waiting_permission", "stopping"})

# Flushes can come from the async turn runner and sync FastAPI worker threads.
# Keep a short-lived lock per snapshot path so overlapping writes cannot share a
# temporary file or replace the destination while another flush is in progress.
_FLUSH_LOCKS_GUARD = threading.Lock()
_FLUSH_LOCKS: dict[str, tuple[LockType, int]] = {}


@contextmanager
def _serialized_flush(path: Path) -> Iterator[None]:
	key = os.path.normcase(str(path.absolute()))
	with _FLUSH_LOCKS_GUARD:
		entry = _FLUSH_LOCKS.get(key)
		if entry is None:
			lock = threading.Lock()
			_FLUSH_LOCKS[key] = (lock, 1)
		else:
			lock, users = entry
			_FLUSH_LOCKS[key] = (lock, users + 1)

	acquired = False
	try:
		lock.acquire()
		acquired = True
		yield
	finally:
		try:
			if acquired:
				lock.release()
		finally:
			with _FLUSH_LOCKS_GUARD:
				current = _FLUSH_LOCKS.get(key)
				if current is not None and current[0] is lock:
					if current[1] <= 1:
						_FLUSH_LOCKS.pop(key, None)
					else:
						_FLUSH_LOCKS[key] = (lock, current[1] - 1)


def _atomic_write(path: Path, payload: str) -> None:
	fd, tmp_name = tempfile.mkstemp(
		prefix=f".{path.name}.",
		suffix=".tmp",
		dir=str(path.parent),
	)
	tmp = Path(tmp_name)
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			fd = -1
			handle.write(payload)
		os.replace(tmp, path)
	finally:
		if fd >= 0:
			try:
				os.close(fd)
			except OSError:
				pass
		try:
			tmp.unlink()
		except FileNotFoundError:
			pass
		except OSError:
			_logger.debug("turn snapshot temp cleanup failed name=%s", tmp.name, exc_info=True)


@dataclass
class TurnSnapshot:
	session_id: str = ""
	turn_id: str = ""
	status: TurnStatus = "succeeded"
	goal_text: str = ""
	last_user_message_id: str = ""
	revision: int = 0
	last_event_id: int = 0
	incomplete_tool_uses: list[str] = field(default_factory=list)
	active_agent_ids: list[str] = field(default_factory=list)
	stop_reason: str = ""
	waiting_permission: bool = False
	model: str = ""
	updated_at: float = 0.0

	def is_active(self) -> bool:
		return self.status in _ACTIVE

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


def _sessions_dir() -> Path:
	override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
	if override:
		return Path(override).expanduser()
	return Path.home() / ".xeyo" / "sessions"


def _safe_name(session_id: str) -> str:
	raw = session_id or "session"
	parts: list[str] = []
	for ch in raw:
		if ch == ":":
			parts.append("__")
		elif ch.isalnum() or ch in "._-":
			parts.append(ch)
		else:
			parts.append("_")
	return "".join(parts).strip("._") or "session"


def path_for(session_id: str) -> Path:
	return _sessions_dir() / f"{_safe_name(session_id)}.turn.json"


def hydrate(session_id: str) -> TurnSnapshot | None:
	path = path_for(session_id)
	if not path.is_file():
		return None
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except Exception:  # noqa: BLE001
		_logger.warning("turn snapshot read failed session=%s", session_id, exc_info=True)
		return None
	if not isinstance(raw, dict):
		return None
	status = str(raw.get("status") or "succeeded")
	if status not in {
		"queued",
		"running",
		"waiting_permission",
		"stopping",
		"stopped",
		"succeeded",
		"failed",
		"recovery_required",
	}:
		status = "succeeded"
	return TurnSnapshot(
		session_id=str(raw.get("session_id") or session_id),
		turn_id=str(raw.get("turn_id") or ""),
		status=status,  # type: ignore[arg-type]
		goal_text=str(raw.get("goal_text") or ""),
		last_user_message_id=str(raw.get("last_user_message_id") or ""),
		revision=int(raw.get("revision") or 0),
		last_event_id=int(raw.get("last_event_id") or 0),
		incomplete_tool_uses=[
			str(x) for x in (raw.get("incomplete_tool_uses") or []) if x
		],
		active_agent_ids=[
			str(x) for x in (raw.get("active_agent_ids") or []) if x
		],
		stop_reason=str(raw.get("stop_reason") or ""),
		waiting_permission=bool(raw.get("waiting_permission")),
		model=str(raw.get("model") or ""),
		updated_at=float(raw.get("updated_at") or 0),
	)


def flush(snap: TurnSnapshot) -> None:
	"""原子写回 sidecar。"""
	import time

	if not snap.session_id:
		return
	path = path_for(snap.session_id)
	try:
		with _serialized_flush(path):
			snap.updated_at = time.time()
			path.parent.mkdir(parents=True, exist_ok=True)
			payload = json.dumps(snap.to_dict(), ensure_ascii=False, indent=None)
			_atomic_write(path, payload)
	except Exception:  # noqa: BLE001
		_logger.warning(
			"turn snapshot flush failed session=%s", snap.session_id, exc_info=True
		)


def clear(session_id: str) -> None:
	path = path_for(session_id)
	try:
		if path.is_file():
			path.unlink()
	except Exception:  # noqa: BLE001
		_logger.debug("turn snapshot clear failed", exc_info=True)


def list_recoverable() -> list[TurnSnapshot]:
	"""扫描 sessions 目录中可恢复 / 需确认的 turn。"""
	root = _sessions_dir()
	if not root.is_dir():
		return []
	out: list[TurnSnapshot] = []
	for path in root.glob("*.turn.json"):
		sid = path.name[: -len(".turn.json")]
		snap = hydrate(sid)
		if snap is None:
			continue
		if snap.is_active() or snap.status == "recovery_required":
			out.append(snap)
	return out


def mark_crashed_as_recovery(snap: TurnSnapshot) -> TurnSnapshot:
	"""进程重启后：原 running/stopping → recovery_required。"""
	if snap.status in {"running", "stopping", "queued"}:
		if snap.waiting_permission:
			snap.status = "recovery_required"
			snap.stop_reason = snap.stop_reason or "restart_while_waiting_permission"
		else:
			snap.status = "recovery_required"
			snap.stop_reason = snap.stop_reason or "process_restart"
		flush(snap)
	elif snap.status == "waiting_permission":
		snap.status = "recovery_required"
		snap.stop_reason = snap.stop_reason or "restart_while_waiting_permission"
		flush(snap)
	return snap
