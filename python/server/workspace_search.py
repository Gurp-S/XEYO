"""Breadth-first filename search using directory-entry metadata."""
import os
from collections import deque
from pathlib import Path


def search(root, query, limit, *, excluded, max_depth, relative):
    hits = []
    q = (query or "").strip().lower()
    frontier = deque([(root, 0)]) if q else deque()
    while frontier:
        folder, depth = frontier.popleft()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.name in excluded:
                        continue
                    try:
                        is_dir = entry.is_dir()
                    except OSError:
                        continue
                    if q in entry.name.lower():
                        try:
                            size = None if is_dir else entry.stat().st_size
                        except OSError:
                            size = None
                        hits.append(dict(name=entry.name, path=relative(root, Path(entry.path)),
                                         kind="dir" if is_dir else "file", size=size))
                        if len(hits) >= limit:
                            return dict(cwd=str(root), query=query, hits=hits, truncated=True)
                    if is_dir and depth < max_depth:
                        frontier.append((entry.path, depth + 1))
        except OSError:
            continue
    return dict(cwd=str(root), query=query, hits=hits, truncated=False)
