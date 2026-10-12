"""Reconcile a failed append by stable row IDs before the next explicit write."""
import json
from pathlib import Path


def pending_messages(messages, known):
    """Deduplicate a new batch without silently discarding different bodies."""
    from session.transcript_blobs import message_fields
    pending, identities = [], {}
    for message in messages:
        if not message.id or message.id in known:
            continue
        if message.id in identities:
            # Normal batches keep references only; serialize for comparison
            # only on an actual collision, before any blob publication.
            def body(value):
                return json.dumps(message_fields(value), ensure_ascii=False,
                                  sort_keys=True, separators=(',', ':'))
            if body(identities[message.id]) != body(message):
                raise ValueError('transcript_message_identity_conflict')
            continue
        identities[message.id] = message
        pending.append(message)
    return pending


def row_body(row, anchor):
    """Identity ignores append time and inline/blob representation only."""
    from session.transcript_blobs import resolve_transcript_row
    value = dict(resolve_transcript_row(row, anchor, strict=True))
    for key in ('ts', 'content_ref', 'content_hash', 'content_bytes'):
        value.pop(key, None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def needs_tail_repair(path: Path) -> bool:
    """A restarted writer has no in-memory failure flag for a partial append."""
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            if not stream.tell():
                return False
            stream.seek(-1, 2)
            return stream.read(1) != b'\n'
    except FileNotFoundError:
        return False


def reconcile_retry(path: Path, sources: list[Path], lines: list[str]) -> list[str]:
    """Called under the existing disk lock; preserve every complete stored row."""
    wanted = set()
    for line in lines:
        incoming = json.loads(line)
        identity = incoming.get('id') if isinstance(incoming, dict) else None
        if isinstance(identity, str) and identity:
            wanted.add(identity)
    known = {}
    for source in sources:
        if not source.is_file():
            continue
        with source.open('rb') as stream:
            while raw := stream.readline():
                offset = stream.tell() - len(raw)
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw.decode('utf-8'))
                except (ValueError, UnicodeDecodeError) as exc:
                    # Only an incomplete final append can be repaired here.
                    if source == path and not raw.endswith(b'\n'):
                        with path.open('r+b') as repair:
                            repair.truncate(offset)
                        continue
                    raise ValueError(f'transcript_corrupt_row: offset={offset}') from exc
                if not isinstance(row, dict):
                    raise ValueError(f'transcript_invalid_row: offset={offset}')
                identity = row.get('id')
                if isinstance(identity, str) and identity in wanted:
                    known.setdefault(identity, []).append(row)
                if source == path and not raw.endswith(b'\n'):
                    with path.open('ab') as repair:
                        repair.write(b'\n')
    output = []
    for line in lines:
        row = json.loads(line)
        identity = row.get('id') if isinstance(row, dict) else None
        if identity and identity in known:
            # A retry confirms the same source body, not merely that an ID
            # exists somewhere in the merged log. Decode only colliding rows;
            # unrelated archived blobs are outside this retry's workset.
            body = row_body(row, path)
            if any(row_body(previous, path) != body for previous in known[identity]):
                raise ValueError('transcript_message_identity_conflict')
            continue
        output.append(line)
        if identity:
            known[identity] = [row]
    return output
