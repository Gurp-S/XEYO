"""Reconcile a failed append by stable row IDs before the next explicit write."""
import json
from pathlib import Path


def reconcile_retry(path: Path, sources: list[Path], lines: list[str]) -> list[str]:
    """Called under the existing disk lock; preserve every complete stored row."""
    known = set()
    for source in sources:
        if not source.is_file():
            continue
        with source.open('rb') as stream:
            while raw := stream.readline():
                offset = stream.tell() - len(raw)
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    # Only an incomplete final append can be repaired here.
                    if source == path and not raw.endswith(b'\n'):
                        with path.open('r+b') as repair:
                            repair.truncate(offset)
                    continue
                if isinstance(row, dict) and row.get('id'):
                    known.add(row['id'])
                if source == path and not raw.endswith(b'\n'):
                    with path.open('ab') as repair:
                        repair.write(b'\n')
    output = []
    for line in lines:
        row = json.loads(line)
        identity = row.get('id') if isinstance(row, dict) else None
        if identity and identity in known:
            continue
        output.append(line)
        if identity:
            known.add(identity)
    return output
