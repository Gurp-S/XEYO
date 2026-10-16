"""Reuse Windows directory enumeration metadata for dense filename matches."""
import os
from collections import defaultdict


def sort_by_mtime(files, root, stat_mtime):
    times = {}
    if os.name == "nt":
        parents = defaultdict(list)
        for rel in files:
            full = os.path.join(root, rel)
            parents[os.path.dirname(full)].append((rel, os.path.basename(full)))
        for parent, matches in parents.items():
            if len(matches) < 8:
                continue
            wanted = {name: rel for rel, name in matches}
            try:
                with os.scandir(parent) as entries:
                    for entry in entries:
                        rel = wanted.pop(entry.name, None)
                        if rel is not None:
                            try:
                                times[rel] = entry.stat().st_mtime
                            except OSError:
                                pass
                        if not wanted:
                            break
            except OSError:
                pass
    def key(rel):
        mtime = times[rel] if rel in times else stat_mtime(os.path.join(root, rel))
        normal = rel.replace("\\", "/")
        return mtime, normal.casefold(), normal
    files.sort(key=key, reverse=True)
