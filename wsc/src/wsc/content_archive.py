"""Opt-in immutable cold objects shared by publications of one bound session."""
from pathlib import Path
import os
import tempfile

from . import evidence
from .contracts import digest, require


def publish_object(path, payload):
    """Expose only complete bytes; a competing writer can never replace an object."""
    path = Path(path)
    require(not path.is_symlink(), "evidence_path_symlink")
    if path.exists():
        require(path.read_bytes() == payload, "evidence_object_conflict")
        return
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Both names are in the same filesystem. link is an atomic no-replace
            # publication, unlike rename which overwrites on some platforms.
            os.link(temporary, path)
        except FileExistsError:
            require(not path.is_symlink(), "evidence_path_symlink")
            require(path.read_bytes() == payload, "evidence_object_conflict")
    finally:
        temporary.unlink(missing_ok=True)


def export_sources(store, access, source_ids, directory, *, write_object=None):
    binding = {"format": "wsc.cold-objects/1", "session_id": store.session_id,
               "workspace": store.workspace}
    objects = Path(directory).resolve() / digest(binding)
    return evidence.export_sources(store, access, source_ids, objects, write_object=write_object or publish_object)
