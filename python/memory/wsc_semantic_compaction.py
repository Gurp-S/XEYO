"""Semantic generation and native immutable publication, not a task-state writer.

The caller serializes session mutation. Source capture and durable generation
publication precede retirement. Semantic handoff is the WSC default; explicit
XEYO_WSC_SEMANTIC_HANDOFF=0 retains legacy D for engineering comparisons.
"""
from copy import deepcopy
import os
from pathlib import Path


def enabled():
    from memory.wsc_projection import live_enabled
    return live_enabled() and os.environ.get('XEYO_WSC_SEMANTIC_HANDOFF', '1').strip().lower() in {'1', 'true', 'yes', 'on'}


def boundary(rows, working):
    from memory.wsc_execution_boundary import fold_cut
    return max(int(working.compact_cursor or 0), fold_cut(rows))


async def prepare(*, model, messages, source, working, abort, account, persist, guard=None, cwd=None,
                  original_source=None, budget=None):
    from memory.wsc_handoff_transaction import fingerprint
    from memory.wsc_semantic_generation import generate
    if guard:
        guard()
    abort.raise_if_aborted()
    from memory.wsc_semantic_binding import capture, verify, goal_text
    binding = capture(cwd, working)
    captured = deepcopy(source())
    originals = deepcopy(original_source()) if original_source is not None else None
    from memory.wsc_semantic_originals import validate as validate_originals
    validate_originals(captured, originals)
    cut = boundary(captured, working)
    if cut <= int(working.compact_cursor or 0):
        return None
    if persist is None:
        raise ValueError('semantic_source_persistence_unavailable')
    persist()
    from memory.wsc_semantic_sources import inputs
    messages, alternative = inputs(messages, working, captured, cwd=cwd)
    control = goal_text(binding)
    visible = [*messages, {'role': 'assistant', 'content': control}] if control else messages
    if alternative is not None and control:
        alternative = [*alternative, {'role': 'assistant', 'content': control}]
    captured_fingerprint = fingerprint(captured)
    def check():
        if guard: guard()
        abort.raise_if_aborted()
        verify(binding, cwd, working)
        if fingerprint(source()) != captured_fingerprint:
            raise ValueError('semantic_source_changed')
        if budget is not None:
            from memory.wsc_handoff_budget import check_usage
            check_usage(budget)
    def admit_next():
        check()
        if budget is not None:
            if not budget.prepare_next_turn(): raise ValueError('handoff_model_budget_exhausted')
            budget.begin_turn()
    def admit_read():
        check()
        if budget is not None and not budget.begin_tool_call():
            raise ValueError('handoff_tool_budget_exhausted')
    try:
        text = await generate(model, visible, abort, account=account, sources=captured,
                              admit_next=admit_next, admit_read=admit_read, guard=check,
                              alternative_messages=alternative)
    except Exception as exc:
        if guard:
            guard()
        abort.raise_if_aborted()
        verify(binding, cwd, working)
        from memory.wsc_compaction_failure import mark_generation_failure
        mark_generation_failure(exc)
        raise
    if guard:
        guard()
    abort.raise_if_aborted()
    verify(binding, cwd, working)
    current_fingerprint = fingerprint(source())
    if current_fingerprint != captured_fingerprint:
        raise ValueError('semantic_source_changed')
    if original_source is not None and fingerprint(original_source()) != fingerprint(originals):
        raise ValueError('semantic_original_source_changed')
    return {'text': text, 'rows': captured, 'cut': cut,
            'original_rows': originals,
            'previous_cursor': binding['cursor'], 'binding': binding,
            'source_fingerprint': captured_fingerprint}


def publish(candidate, messages, working, *, cwd, guard=None):
    from memory.wsc_handoff_transaction import fingerprint
    if guard:
        guard()
    if candidate is None:
        from memory.wsc_pressure_admission import keep_emission
        return keep_emission(messages, working, cwd=cwd)
    from memory.wsc_semantic_binding import verify
    verify(candidate.get('binding'), cwd, working)
    if (fingerprint(messages) != candidate['source_fingerprint']
            or int(working.compact_cursor or 0) != candidate['previous_cursor']):
        raise ValueError('semantic_publication_source_changed')
    cut = candidate['cut']
    if not int(working.compact_cursor or 0) < cut <= boundary(messages, working):
        raise ValueError('semantic_publication_boundary_invalid')
    root = Path(cwd).resolve()
    from memory.wsc_generation_commit import commit
    return commit(messages, working, cwd=root, guard=guard,
        build=lambda staged: _publish(candidate, messages, staged, root))


def _publish(candidate, messages, staged, root):
    from memory import wsc_head_store as hs, wsc_projection as wp
    from memory.wsc_execution_boundary import protect
    from memory.wsc_semantic_binding import verify, goal_text
    from memory.wsc_semantic_evidence import publish as publish_evidence
    cut = candidate['cut']
    objects = set()
    archive, entrance = publish_evidence(messages, cut, staged, root,
        original_rows=candidate.get('original_rows'), evidence_paths=objects)
    # A comparison baseline must describe facts actually installed in the
    # model context, never a newer control snapshot read after generation.
    verify(candidate['binding'], root, staged)
    control = goal_text(candidate['binding'])
    head = '\n\n'.join(part for part in (candidate['text'], control, entrance) if part)
    goal = candidate['binding']['goal'] or {}
    lifecycle = {key: goal.get(key) for key in ('goal_id', 'revision', 'status')}
    lifecycle.update(goal=str(goal.get('text') or '') if goal.get('status') in {'active', 'paused', 'blocked'} else '',
                     response_tail_from=protect(messages, len(messages)),
                     semantic_checkpoint={'version': 1, 'source_fingerprint': candidate['source_fingerprint'],
                                          'source_count': len(messages), 'semantic_status': 'SEMANTIC_UNVERIFIED',
                                          'body_chars': len(candidate['text'])})
    staged.compact_cursor = cut
    staged.last_action = 'C2'
    staged.c2_summary_text = head
    staged.wsc_timing_state = {**staged.wsc_timing_state, 'last_semantic_commit': lifecycle['semantic_checkpoint']}
    layout = staged.compression_source_layout
    if not hs.save(staged.session_id, text=head, cwd=str(root), cursor=cut, region_end=cut,
                   messages=messages, source_layout=layout, view_path=str(archive), lifecycle=lifecycle,
                   evidence_paths=tuple(objects)):
        raise ValueError('semantic_publication_failed')
    wp._STATE.pop(wp._state_key(staged.session_id, root), None)
    # Same native reuse/emission path used after process restart.
    return wp.project_c2_messages(messages, staged, cwd=root)


def resumable_failure(exc):
    from memory.wsc_compaction_failure import recoverable
    return recoverable(exc)
