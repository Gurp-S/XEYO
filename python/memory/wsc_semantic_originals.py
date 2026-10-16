"""Original message envelopes stay separate from derived compression rows."""
from copy import deepcopy


def from_store(store):
    from session.transcript_blobs import message_fields
    return [deepcopy(message_fields(item)) for item in store.items]


def validate(rows, originals):
    if originals is None:
        return
    identities = {}
    for row in originals:
        uid = row.get('id')
        if not isinstance(uid, str) or not uid or uid in identities:
            raise ValueError('semantic_original_identity_invalid')
        identities[uid] = row
    for row in rows:
        uid = row.get('message_id') or row.get('id')
        origin = identities.get(uid)
        if origin is None or origin.get('role') != row.get('role'):
            raise ValueError('semantic_original_source_unbound')
