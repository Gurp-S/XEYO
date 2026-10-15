"""Publish an explicit fallback generation through the existing head contract."""


def _install(messages, working, boundary, cwd, text, view_path, lifecycle):
    from memory import wsc_projection, wsc_head_store
    session = str(getattr(working, 'session_id', '') or '-')
    pinned = wsc_projection._cwd_of(cwd)
    layout = getattr(working, 'compression_source_layout', 'latest-notes-v1')
    cursor = int(working.compact_cursor)
    saved = wsc_head_store.save(session, text=text, cwd=pinned,
        cursor=cursor, region_end=boundary, messages=messages, source_layout=layout,
        view_path=view_path, lifecycle=lifecycle)
    if not saved:
        return None
    frozen = wsc_projection._restore_frozen(session, cursor, messages, pinned, source_layout=layout)
    if frozen is None:
        return None
    key = wsc_projection._state_key(session, pinned)
    if len(wsc_projection._STATE) >= wsc_projection._MAX_STATE and key not in wsc_projection._STATE:
        wsc_projection._STATE.pop(next(iter(wsc_projection._STATE)))
    wsc_projection._STATE[key] = frozen
    return frozen


def rebind(cached, messages, working, cwd):
    """Explicit no-gain fold: same head/boundary, newly authorized cursor."""
    from memory.wsc_head_store import enabled as store_enabled
    from synaptic.contracts import enabled as contracts_enabled
    if not store_enabled() or not contracts_enabled():
        return cached
    return _install(messages, working, cached.region_end, cwd,
                    cached.head, cached.view_path, cached.lifecycle)


def emit(messages, working, boundary, cwd, *, new_generation):
    from memory import wsc_projection, wsc_head_store
    from synaptic.contracts import enabled as contracts_enabled
    if (not new_generation or not wsc_projection.live_enabled()
            or not contracts_enabled() or not wsc_head_store.enabled()):
        return None
    try:
        from memory.wsc_execution_boundary import protect
        from memory.wsc_goal_source import snapshot
        session = str(getattr(working, 'session_id', '') or '-')
        pinned = wsc_projection._cwd_of(cwd)
        observed = snapshot(pinned, session) or {}
        lifecycle = {key: observed.get(key) for key in ('goal_id', 'revision', 'status')}
        lifecycle['goal'] = (str(observed.get('text') or '')
                             if observed.get('status') in {'active', 'paused', 'blocked'} else '')
        lifecycle['response_tail_from'] = protect(messages, len(messages))
        frozen = _install(messages, working, boundary, cwd, working.c2_summary_text, '', lifecycle)
        if frozen is None:
            return list(messages)
        return wsc_projection._emit(frozen.head, messages, frozen.region_end,
            int(working.c1_frozen_until or 0), cwd=pinned, view_path=frozen.view_path,
            session=session, lifecycle=frozen.lifecycle, source_layout=frozen.source_layout)
    except Exception as exc:
        from memory.wsc_goal_events import GoalEventLedgerError
        if isinstance(exc, GoalEventLedgerError):
            raise
        from memory.wsc_diagnostics import record
        record('fallback_publication', exc, session=str(getattr(working, 'session_id', '')))
        return list(messages)
