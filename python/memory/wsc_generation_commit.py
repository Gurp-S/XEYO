"""One durable context-publication boundary for all production WSC generators.

Callers serialize session mutation. Builders may publish immutable objects and
the compatibility head cache, but only this boundary commits the working cursor.
"""
from copy import deepcopy


def commit(messages, working, *, cwd, build, guard=None):
    from memory import wsc_head_store as hs, wsc_projection as wp, working as snapshots
    from memory.wsc_committed_head import KEY, pin, retain_previous
    from memory.wsc_handoff_transaction import fingerprint
    from memory.wsc_semantic_binding import capture, verify
    root = wp._cwd_of(cwd)
    binding, source = capture(root, working), fingerprint(messages)
    key = wp._state_key(working.session_id, root)

    def check():
        if guard:
            guard()
        verify(binding, root, working)
        if fingerprint(messages) != source:
            raise ValueError('publication_source_changed')

    check()
    retain_previous(working, messages, root)
    staged = deepcopy(working)
    published = False
    try:
        emitted = build(staged)
        check()
        if staged.compact_cursor == working.compact_cursor:
            return emitted
        frozen = hs.load(staged.session_id, cwd=str(root), cursor=staged.compact_cursor,
                         messages=messages, source_layout=staged.compression_source_layout)
        if (staged.compact_cursor < working.compact_cursor or frozen is None or not emitted
                or emitted[0].get('content') != frozen.text):
            raise ValueError('publication_generation_not_verified')
        staged.wsc_timing_state = {**staged.wsc_timing_state, KEY: pin(staged, messages, root)}
        check()

        def committed(durable):
            return (durable.compact_cursor == staged.compact_cursor
                    and durable.c1_frozen_until == staged.c1_frozen_until
                    and durable.c2_summary_text == staged.c2_summary_text
                    and durable.c2_evidence_paths == staged.c2_evidence_paths
                    and durable.wsc_timing_state.get(KEY) == staged.wsc_timing_state[KEY])

        try:
            written = snapshots.flush(staged.session_id, staged)
        except BaseException:
            # A write may finish before its caller is interrupted. Adopt that
            # complete commit so caller-finally cannot overwrite it with old state.
            durable = snapshots.hydrate(staged.session_id, source_layout=staged.compression_source_layout)
            if committed(durable):
                working.__dict__.update(staged.__dict__)
                published = True
            raise
        if written:
            # os.replace is the commit point. A subsequent verification-read
            # failure cannot make caller-finally roll back that completed write.
            working.__dict__.update(staged.__dict__)
            published = True
        durable = snapshots.hydrate(staged.session_id, source_layout=staged.compression_source_layout)
        if not committed(durable):
            raise ValueError('publication_working_not_durable')
        working.__dict__.update(staged.__dict__)
        published = True
        return emitted
    finally:
        # Failed builders may have installed an uncommitted process cache.
        # Successful publication retains its already verified projection.
        if not published:
            wp._STATE.pop(key, None)
