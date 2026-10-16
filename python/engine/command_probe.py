"""Narrow Windows PATH once; shutil.which remains the executable authority."""
from __future__ import annotations

import os
import shutil
from collections.abc import Mapping


def _candidate_paths(names: tuple[str, ...]) -> dict[str, str | None]:
    if not names:
        return {}
    source = os.environ.get("PATH")
    if os.name != "nt" or not source:
        return dict.fromkeys(names, source)
    selected: dict[str, list[str]] = {name: [] for name in names}
    folded = {name: name.casefold() for name in names}
    prefixes = tuple(folded.values())
    seen: set[str] = set()
    for directory in source.split(os.pathsep):
        key = os.path.normcase(directory)
        if key in seen:
            continue
        seen.add(key)
        remaining = set(names)
        try:
            with os.scandir(directory or os.curdir) as entries:
                for index, entry in enumerate(entries):
                    # A prefix is deliberately permissive: PATHEXT, execution
                    # permissions, directories and symlinks stay shutil's job.
                    # Bound work in huge directories by retaining them as-is.
                    filename = entry.name.casefold()
                    if index < 4096 and not filename.startswith(prefixes):
                        continue
                    matches = {name for name in remaining
                               if index >= 4096 or filename.startswith(folded[name])}
                    for name in matches:
                        selected[name].append(directory or os.curdir)
                    remaining.difference_update(matches)
                    if not remaining:
                        break
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            # Listing permission need not imply permission to execute a known
            # path. Preserve the original lookup on any enumeration failure.
            for name in remaining:
                selected[name].append(directory or os.curdir)
    # Keep one original directory when no candidates exist: PATH='' disables
    # shutil's platform/version-specific implicit current-directory search.
    # An explicit empty component of the original PATH means the current dir.
    fallback = source.split(os.pathsep)[0] or os.curdir
    return {name: os.pathsep.join(paths) or fallback for name, paths in selected.items()}


def probe_commands(groups: Mapping[str, tuple[str, ...]]) -> dict[str, bool]:
    """Fresh facts per call; no cross-turn or process-wide negative cache."""
    paths = _candidate_paths(tuple(name for names in groups.values() for name in names))
    return {key: any(shutil.which(name, path=paths[name]) for name in names)
            for key, names in groups.items()}
