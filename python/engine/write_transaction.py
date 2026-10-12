"""Cooperative local write locks and exact-content preconditions.

All instances and local XEYO processes share this lock domain. Other programs
and container writers do not acquire these locks; no external CAS claim.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import threading

_LOCKS = tuple(threading.RLock() for _ in range(64))


@contextmanager
def path_lock(path):
    from engine.write_store import _routed_container
    route = _routed_container()
    key = route + ":" + os.path.normcase(os.path.realpath(path))
    digest = hashlib.sha256(key.encode()).hexdigest()
    with _LOCKS[int(digest[:8], 16) % len(_LOCKS)]:
        if route:
            # A host lock cannot coordinate independent container processes.
            yield
            return
        directory = Path(tempfile.gettempdir()) / "xeyo-write-locks"
        directory.mkdir(exist_ok=True)
        with (directory / digest).open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def verify_observed_base(tool, path, content):
    """A complete prior observation is compared by content, never by mtime alone.

    Absent/partial observations keep the existing no-prior-Read contract.
    """
    from engine.write_store import _content_hash_text
    entry = tool._read_state.get(path)
    if entry is None or entry.is_partial_view or entry.offset is not None or entry.limit is not None:
        return
    expected = _content_hash_text(entry.content) if entry.content_known else entry.content_hash
    if expected and (content is None or _content_hash_text(content) != expected):
        raise RuntimeError("stale: content differs from the recorded full-file observation")


def persist_candidate(tool, path, content, *, encoding, line_endings):
    from tools.fileio.text import normalize_newlines, read_text_file
    from tools.fileio import fsprobe
    from engine.write_store import WriteStore, ChangeIntent, EditOp, _content_hash_text
    from permissions.write_scope import get_write_scope
    if tool._write_store is None and get_write_scope() is not None:
        raise RuntimeError("write_store required for sub-agent writes")
    explicit_base = hasattr(tool, "_mutation_base")
    expected = getattr(tool, "_mutation_base", None)
    # Edit validate->call cache is the expected candidate base, not a fresh read.
    if not explicit_base and expected is None and hasattr(tool, "_last_file_content"):
        expected = tool._last_file_content
    if not explicit_base and expected is None:
        entry = tool._read_state.get(path)
        if entry is not None and entry.content_known:
            expected = entry.content
    if expected is None and fsprobe.exists(path):
        raise RuntimeError("missing_base: candidate has no recorded source version")
    verify_observed_base(tool, path, expected)
    annotation = {"session_id": getattr(tool, "_session_id", ""), "expected_absent": expected is None, "tool_name": tool.name,
                  "validation_policy": getattr(tool, "_validation_policy", "draft")}
    # Do not manufacture a content baseline for a sidecar containing only a hash.
    entry = tool._read_state.get(path)
    base = _content_hash_text(expected) if expected is not None else ""
    if entry is not None and not entry.content_known and entry.content_hash:
        base = entry.content_hash
    normalized = normalize_newlines(content)
    encoded_text = normalized.replace("\n", "\r\n") if line_endings == "CRLF" else normalized
    store = tool._write_store or WriteStore(tool._cwd, allowed_paths=(path,))
    result = store.submit_sync(ChangeIntent(
        agent_id=tool._agent_id, ops=[EditOp(path=path, new_content=encoded_text)],
        base_hashes={path: base}, annotation=annotation, encoding=encoding))
    if not result.ok:
        raise RuntimeError(f"write conflict ({result.reason}): {result.detail}")
    tool._mutation_checks = {**result.checks, "operation_id": result.operation_id, "after_version": result.version}
    tool._mutation_operation_id = result.operation_id
    from tools.glob_tool.glob_tool import clear_glob_cache
    clear_glob_cache()
    return result.journal_warning
