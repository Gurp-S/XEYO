"""Message body certificates for accepted rows, independent of visibility.

Inline bodies occupy only a digest. Existing blob descriptors resolve lazily
on a collision, through the same strict reader used by execution recovery.
This index certifies identity, not fsync; the writer owns durability.
"""
import hashlib
import json
import threading

_lock = threading.RLock()
_bodies = {}
_loaded = set()


def key(path):
    return str(path.resolve())


def digest(fields):
    value = dict(fields)
    # Retraction is an execution-view flag, not a mutation of source text.
    for field in ('ts', 'content_ref', 'content_hash', 'content_bytes', 'note_retracted'):
        value.pop(field, None)
    if value.get('note_key'):
        # Legacy note rows restore missing kind/fp as empty strings.
        value.setdefault('note_kind', '')
        value.setdefault('note_fp', '')
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def observe(path, rows):
    with _lock:
        index = _bodies.setdefault(key(path), {})
        for row in rows:
            identity = row.get('id')
            if not isinstance(identity, str) or not identity:
                continue
            value = (dict(row) if row.get('content') is None and row.get('content_ref')
                     else digest(row))
            versions = index.setdefault(identity, [])
            if value not in versions:
                versions.append(value)


def loaded(path):
    with _lock:
        _loaded.add(key(path))


def check(path, identity, actual):
    # All callers hold _lock; no disk writer takes this lock.
    versions = _bodies.get(key(path), {}).get(identity)
    if not versions:
        raise ValueError('transcript_message_identity_unconfirmed')
    from session.transcript_blobs import resolve_transcript_row
    for position, expected in enumerate(versions):
        if isinstance(expected, dict):
            expected = digest(resolve_transcript_row(expected, path, strict=True))
            versions[position] = expected
        if expected != actual:
            raise ValueError('transcript_message_identity_conflict')


def validate_known(path, messages, known):
    from session.transcript_blobs import message_fields
    collisions = [message for message in messages if message.id and message.id in known]
    if not collisions:
        return
    with _lock:
        if key(path) not in _loaded:
            from session.record_transcript import _load_written_ids
            _load_written_ids(path)
        for message in collisions:
            check(path, message.id, digest(message_fields(message)))


def accepted(path, rows):
    """Reserve immutable bodies after serialization, before IDs/queue acceptance."""
    from session.transcript_blobs import resolve_transcript_row
    with _lock:
        index = _bodies.setdefault(key(path), {})
        # Certify the serialized snapshot, not a live Message that a caller
        # could mutate after serialization. Blob references remain strict.
        values = []
        for line in rows:
            row = json.loads(line)
            values.append((row['id'], digest(resolve_transcript_row(row, path, strict=True))))
        for identity, actual in values:
            if identity in index:
                check(path, identity, actual)
        for identity, actual in values:
            index.setdefault(identity, [actual])
