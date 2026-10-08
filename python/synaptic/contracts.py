"""Opt-in, immutable WSC publication contracts; no model-visible directives."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

ENV = "XEYO_WSC_STATE_CONTRACTS"
_OBJECT = re.compile(r"\.v-sha256-([a-f0-9]{64})\.txt$")


def enabled() -> bool:
    from synaptic.request_plane import enabled as requests_enabled
    from synaptic.failure_facts import enabled as failures_enabled
    return requests_enabled() or failures_enabled() or os.environ.get(ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_path(path, data: bytes) -> Path:
    p = Path(path)
    stem = p.stem.split(".v-sha256-", 1)[0].split(".pending-", 1)[0]
    return p.with_name(f"{stem}.v-sha256-{digest(data)}.txt")


def verify_object(path) -> str:
    p = Path(path)
    m = _OBJECT.search(p.name)
    if m and digest(p.read_bytes()) != m.group(1):
        raise ValueError("stale_view: content digest mismatch")
    return m.group(1) if m else ""


def publish(path, data: bytes) -> Path:
    """Complete bytes first, then link atomically without replacing any object."""
    target = object_path(path, data)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".wsc-publish-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError:
            verify_object(target)
        if target.read_bytes() != data:
            raise ValueError("stale_view: object collision")
    finally:
        Path(tmp).unlink(missing_ok=True)
    return target


def finalize(text, state, cold, pending, ref, *, persist):
    """Replace only this build's unpublished reference, never old references."""
    data = cold.render_text_view()[0].encode("utf-8")
    target = publish(pending, data) if persist else object_path(pending, data)
    new_ref = Path(ref).with_name(target.name).as_posix()
    def swap(value):
        return value.replace(ref, new_ref)
    text = swap(text)
    state.full_text = swap(state.full_text)
    state.journal = tuple((h, swap(line)) for h, line in state.journal)
    state.seg_text = {k: swap(v) for k, v in state.seg_text.items()}
    state.emitted = {k: swap(v) for k, v in state.emitted.items()}
    return text, str(target), new_ref
