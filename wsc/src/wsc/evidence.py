"""Exact evidence access with current authorization and explicit read scope."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import stat

from .contracts import AccessCheck, digest, encode, require
from .store import Store


_REPARSE_POINT = 0x400
_COMPARE_CHUNK_BYTES = 65536


def source_row(db, source_id: str) -> dict:
    row = db.execute("SELECT seq,data,digest FROM events WHERE id=?", (source_id,)).fetchone()
    require(row is not None, "source_unavailable")
    data = json.loads(row["data"])
    require(digest(data) == row["digest"], "source_integrity_mismatch")
    return {"seq": row["seq"], **data}


def authorize(store: Store, access: AccessCheck, source_id: str, action="read") -> None:
    require(access(store.session_id, source_id, action) is True, "Permission denied: source")


def read(store: Store, access: AccessCheck, source_id: str, *, offset=0, limit=None) -> dict:
    authorize(store, access, source_id)
    require(type(offset) is int and offset >= 0, "invalid_offset")
    require(limit is None or (type(limit) is int and limit >= 0), "invalid_limit")
    with store.connect() as db:
        record = source_row(db, source_id)
    require(record["kind"] != "opaque", "opaque_source_public_read_unavailable")
    # Native wire values, not claimed original transport bytes.
    payload = encode(record["payload"]).encode("utf-8")
    chunk = payload[offset:] if limit is None else payload[offset:offset + limit]
    authorize(store, access, source_id)
    return {"source_id": source_id, "content": chunk, "offset": offset,
            "length": len(chunk), "total_bytes": len(payload),
            "complete": offset == 0 and len(chunk) == len(payload),
            "read_sha256": sha256(chunk).hexdigest(),
            "object_sha256": sha256(payload).hexdigest(),
            "representation": "canonical_native_json_value",
            "observed_at": record["observed_at"]}


def link_like(path: Path) -> bool:
    """Symlinks and Windows reparse points, junctions included. Absent paths are not links."""
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def same_bytes(path: Path, payload: bytes) -> bool:
    """Compare in bounded chunks; the whole object is never read into memory."""
    if path.stat().st_size != len(payload):
        return False
    offset = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(_COMPARE_CHUNK_BYTES)
            if not chunk:
                return offset == len(payload)
            if chunk != payload[offset:offset + len(chunk)]:
                return False
            offset += len(chunk)


def write_once(path: Path, payload: bytes, *, sync: bool = True) -> None:
    """Never replaces an existing evidence object or follows a link leaf.

    sync=False skips the per-object flush; the caller then owns the durability of
    the batch, for example one directory fsync after the last object.
    """
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            if sync:
                os.fsync(stream.fileno())
    except FileExistsError:
        # O_EXCL / CREATE_NEW already refuse an existing entry, including a link
        # leaf; this branch decides whether it is a link or a different object.
        require(not link_like(path), "evidence_path_symlink")
        require(same_bytes(path, payload), "evidence_object_conflict")


def export_sources(store: Store, access: AccessCheck, source_ids: list[str], directory: Path,
                   *, write_object=write_once) -> dict:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    locators = {}
    with store.connect() as db:
        for key in source_ids:
            authorize(store, access, key, "export")
            record = source_row(db, key)
            raw = encode(record["payload"]).encode("utf-8")
            name = sha256(raw).hexdigest() + ".json"
            target = directory / name
            write_object(target, raw)
            locator = {"source_id": key, "file_path": str(target), "sha256": sha256(raw).hexdigest(),
                       "representation": "canonical_native_json_value", "observed_at": record["observed_at"]}
            if record["text"] is not None:
                text = record["text"].encode("utf-8")
                text_path = directory / (sha256(text).hexdigest() + ".txt")
                write_object(text_path, text)
                locator["readable_path"] = str(text_path)
                locator["readable_sha256"] = sha256(text).hexdigest()
            locators[key] = locator
    return locators
