"""Pin an already verified head through the existing atomic working snapshot.

The mutable head file remains a compatibility cache. Its replacement cannot
destroy the generation selected by a committed working cursor.
"""
from copy import deepcopy

KEY = 'committed_head_ref'


def pin(working, messages, cwd):
    from memory import wsc_head_store as hs
    from synaptic.contracts import publish
    path = hs.path_for(working.session_id)
    reference = str(publish(path, path.read_bytes()))
    head = hs.load(working.session_id, cwd=str(cwd), cursor=working.compact_cursor,
                   messages=messages, source_layout=working.compression_source_layout,
                   record_path=reference)
    if head is None:
        raise ValueError('committed_head_not_verified')
    return {'cursor': working.compact_cursor, 'path': reference}


def retain_previous(working, messages, cwd):
    """Migrate a verified pre-reference generation before replacing its cache."""
    if not working.compact_cursor:
        return
    from memory import wsc_head_store as hs
    from memory.working import flush, hydrate
    ref = working.wsc_timing_state.get(KEY)
    args = dict(cwd=str(cwd), cursor=working.compact_cursor, messages=messages,
                source_layout=working.compression_source_layout)
    if (isinstance(ref, dict) and ref.get('cursor') == working.compact_cursor
            and isinstance(ref.get('path'), str) and ref['path']
            and hs.load(working.session_id, **args, record_path=ref.get('path')) is not None):
        return
    if hs.load(working.session_id, **args) is None:
        return  # No verified old generation; full-source recovery remains valid.
    reference = pin(working, messages, cwd)
    staged = deepcopy(working)
    staged.wsc_timing_state = {**staged.wsc_timing_state, KEY: reference}
    flush(staged.session_id, staged)
    durable = hydrate(staged.session_id, source_layout=staged.compression_source_layout)
    if durable.compact_cursor != working.compact_cursor or durable.wsc_timing_state.get(KEY) != reference:
        raise ValueError('committed_head_reference_not_durable')
    working.wsc_timing_state = staged.wsc_timing_state
