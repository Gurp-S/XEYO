"""Retention compaction preserves unchanged journal and index generations."""
import json
import os
from pathlib import Path
from memory import journal


def compact_journal(workspace_id: str, path: Path, ttl_seconds: float) -> int:
    if not path.is_file():
        return 0
    now = journal._now()
    keep: list[str] = []
    removed = 0
    dirty = False
    last_seq = 0
    with journal._lock_for(path):
        with path.open("rb") as handle:
            for raw in handle:
                line = raw.decode("utf-8", errors="ignore").strip()
                dirty |= raw != (line + "\n").encode("utf-8")
                if not line:
                    dirty = True
                    continue
                try:
                    rec = journal._from_dict(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                    dirty = True
                    continue
                if (now - rec.ts) > ttl_seconds:
                    removed += 1
                else:
                    keep.append(line)
                    last_seq = rec.seq
        if not removed and not dirty:
            # Keep the source generation intact; repair a missing/stale index only.
            index = journal._index_path(workspace_id)
            fresh = journal._row_stat(index) == (len(keep), last_seq) if keep else index.is_file() and index.stat().st_size == 0
            if not fresh:
                try:
                    journal.rebuild_index(workspace_id)
                except OSError as exc:
                    journal._discard_stale_index(workspace_id, exc)
            return 0
        # 重写为仅保留的条目（append-only 语义在清理时临时放宽，属运维操作）
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            for line in keep:
                handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        # Keep appenders excluded until the derived index represents the exact
        # replaced journal generation.
        try:
            journal.rebuild_index(workspace_id)
        except OSError as exc:
            journal._discard_stale_index(workspace_id, exc)
    return removed

