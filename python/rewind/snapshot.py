"""Content-addressed snapshots used by reversible file operations."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from rewind import is_rewind_enabled
from rewind.models import SnapshotManifest


class SnapshotStore:
    """Store text and binary snapshots by SHA-256.

    The write is atomic and idempotent. A snapshot manifest is returned even
    when the content already exists, so journal entries can retain stable
    references without copying file contents into JSONL.
    """

    def __init__(
        self,
        session_id: str,
        *,
        root: Path | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.session_id = str(session_id or "").strip()
        if not self.session_id:
            raise ValueError("session_id is required")
        override = os.environ.get("XEYO_SNAPSHOTS_DIR", "").strip()
        self.root = (root or Path(override).expanduser() if override else root) or (
            Path.home() / ".xeyo" / "snapshots"
        )
        self.enabled = is_rewind_enabled() if enabled is None else bool(enabled)

    def put_bytes(
        self,
        data: bytes,
        *,
        source_path: str | None = None,
        encoding: str | None = None,
        line_endings: str | None = None,
        content_kind: str = "binary",
        metadata: dict[str, Any] | None = None,
    ) -> SnapshotManifest | None:
        if not self.enabled:
            return None
        if content_kind not in {"text", "binary"}:
            raise ValueError("content_kind must be 'text' or 'binary'")
        content_hash = hashlib.sha256(data).hexdigest()
        target = self.root / content_hash
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            fd, temp_name = tempfile.mkstemp(prefix=f".{content_hash}.", dir=str(self.root))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, target)
            finally:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
        return SnapshotManifest(
            session_id=self.session_id,
            content_hash=content_hash,
            size_bytes=len(data),
            encoding=encoding or ("utf-8" if content_kind == "text" else "binary"),
            line_endings=line_endings or "",
            source_path=source_path,
            content_kind=content_kind,
            storage_path=str(target),
            metadata=dict(metadata or {}),
        )

    def put_text(
        self,
        content: str,
        *,
        source_path: str | None = None,
        encoding: str = "utf-8",
        line_endings: str = "LF",
        metadata: dict[str, Any] | None = None,
    ) -> SnapshotManifest | None:
        return self.put_bytes(
            content.encode(encoding),
            source_path=source_path,
            encoding=encoding,
            line_endings=line_endings,
            content_kind="text",
            metadata=metadata,
        )

    def get_bytes(self, content_hash: str) -> bytes:
        if not self.enabled:
            raise RuntimeError("rewind snapshots are disabled")
        target = self.root / str(content_hash)
        if not target.is_file():
            raise FileNotFoundError(f"snapshot not found: {content_hash}")
        data = target.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != content_hash:
            raise IOError(f"snapshot hash mismatch: expected {content_hash}, got {actual}")
        return data

    def get_text(self, content_hash: str, *, encoding: str = "utf-8") -> str:
        return self.get_bytes(content_hash).decode(encoding)


__all__ = ["SnapshotStore"]
