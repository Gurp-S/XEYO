"""会话持久化开关与路径 — 对齐 Claude isSessionPersistenceDisabled / session 文件。"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_SAFE_CHAR = re.compile(r"[A-Za-z0-9._-]")
_MAX_FILENAME = 180


def is_session_persistence_disabled(
        *,
        session_flag: bool | None = None,
) -> bool:
    """是否禁用写盘。

	优先级:
	  1) 显式传入的 session_flag（SessionState 上的开关）
	  2) 环境变量 XEYO_NO_SESSION_PERSISTENCE=1/true/yes
	"""
    if session_flag:
        return True
    env = os.environ.get("XEYO_NO_SESSION_PERSISTENCE", "").strip().lower()
    return env in ("1", "true", "yes", "on")


def should_persist(*, session_flag: bool | None = None) -> bool:
    return not is_session_persistence_disabled(session_flag=session_flag)


def default_sessions_dir() -> Path:
    """默认目录: ~/.xeyo/sessions/（可用 XEYO_SESSIONS_DIR 覆盖）。"""
    override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xeyo" / "sessions"


def safe_session_filename(session_id: str) -> str:
    """会话键 → 稳定文件名：``:`` → ``__``，其余非法字符 → ``_``。"""
    raw = session_id or ""
    parts: list[str] = []
    for ch in raw:
        if ch == ":":
            parts.append("__")
        elif _SAFE_CHAR.match(ch):
            parts.append(ch)
        else:
            parts.append("_")
    name = "".join(parts).strip("._") or "session"
    if len(name) > _MAX_FILENAME:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        name = name[:160].rstrip("._-") + "_" + digest
    return name


def transcript_path(session_id: str, *, sessions_dir: Path | None = None) -> Path:
    root = sessions_dir or default_sessions_dir()
    return root / f"{safe_session_filename(session_id)}.jsonl"
