"""Explicit root-based collection; incomplete root inventories never delete."""
from pathlib import Path
from synaptic.contracts import verify_object


def collect(directory, referenced, *, inventory_complete=False, dry_run=True):
    root = Path(directory).resolve()
    if not inventory_complete:
        return {"status": "incomplete_roots", "candidates": [], "deleted": []}
    roots = {Path(p).resolve() for p in referenced}
    candidates = []
    for path in sorted(root.glob("*.v-sha256-*.txt")):
        resolved = path.resolve()
        if resolved.parent != root or resolved in roots:
            continue
        verify_object(path)
        candidates.append(path)
    deleted = []
    if not dry_run:
        for path in candidates:
            path.unlink()
            deleted.append(str(path))
    return {"status": "dry_run" if dry_run else "collected", "candidates": [str(p) for p in candidates], "deleted": deleted}
