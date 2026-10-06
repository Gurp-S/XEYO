"""Explicit source migration after a confirmed frozen-source revision.

No default activation. Coordinates are reset rather than reinterpreted, while
history and cold originals remain intact. Call before cursor baselines.
"""
from weakref import WeakKeyDictionary

from memory.wsc_source_layout import APPEND, LEGACY, reset_compression

_checked = WeakKeyDictionary()


def invalid_frozen_source(cached, messages):
    if cached is None or not cached.source_seal:
        return False
    from memory.wsc_head_store import region_seal
    return cached.source_seal != region_seal(messages, cached.region_end,
        source_layout=getattr(cached, "source_layout", LEGACY))


def invalid_persisted_source(working, messages, cwd):
    from memory.wsc_head_store import source_changed
    return source_changed(working.session_id, cwd=cwd,
                          cursor=working.compact_cursor, messages=messages)


def prepare_compression_source(store, working, *, cwd, fold=True, carrier=None):
    from memory.wsc_source_policy import configure_source
    if carrier is None:
        from prompt.t_now_strategy import resolve_t_now_strategy
        carrier = resolve_t_now_strategy()
    if not configure_source(working, cwd=cwd, carrier=carrier):
        return False
    if getattr(working, "compression_source_layout", LEGACY) != LEGACY:
        return False
    from memory import wsc_projection as wp
    from session.compression_source import compression_messages
    rows = compression_messages(store, working)
    previous = _checked.get(store)
    cursor = int(working.compact_cursor or 0)
    if previous is not None and previous[0] is rows and previous[1] is working and previous[2:] == (cwd, cursor):
        return False
    _checked[store] = (rows, working, cwd, cursor)
    key = wp._state_key(working.session_id, cwd)
    cached = wp._STATE.get(key)
    invalid = (invalid_frozen_source(cached, rows) if cached is not None else
               invalid_persisted_source(working, rows, cwd))
    if not invalid:
        return False
    reset_compression(working)
    working.compression_source_layout = APPEND
    wp._STATE.pop(key, None)
    if fold:
        from memory.runtime import force_compact
        force_compact(compression_messages(store, working), working, cwd=cwd)
    return True
