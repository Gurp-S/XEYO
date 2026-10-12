"""Require a subsequent witnessed declaration when fact applicability grows."""


def source_ranges(fact, field, sources):
    if not isinstance(fact, dict):
        return None
    from synaptic.task_fact_sources import resolve, source_text
    chain = resolve(sources, fact['source_message_id'], field, fact['quote'])
    if not chain:
        return None
    text = source_text(sources[chain[-1]])
    if text is None:
        return None
    quote, ranges, offset = fact['quote'], [], 0
    while True:
        start = text.find(quote, offset)
        if start < 0:
            break
        ranges.append((start, start + len(quote)))
        offset = start + 1
    return chain[-1], ranges


def same_fact_region(before, after, field, sources):
    left, right = source_ranges(before, field, sources), source_ranges(after, field, sources)
    if left is not None and right is not None:
        return left[0] == right[0] and any(a < d and c < b for a, b in left[1] for c, d in right[1])
    # Legacy declarations without citation ranges retain their exact-value boundary.
    quote = lambda fact: fact if isinstance(fact, str) else fact['quote']
    return quote(before) == quote(after)


def expanded_facts(before, after, sources):
    phase_before, phase_after = before['phase_state'], after['phase_state']
    expanded = []
    for field in ('decisions', 'constraints'):
        for fact, scope in zip(after[field], phase_after['fact_scopes'][field]):
            quote = fact if isinstance(fact, str) else fact['quote']
            for previous, old in zip(before[field], phase_before['fact_scopes'][field]):
                if old['kind'] == 'task' or not same_fact_region(previous, fact, field, sources):
                    continue
                widened = scope['kind'] == 'task'
                reactivated = (old['phase_id'] != phase_before['current_phase_id']
                               and scope['kind'] == 'phase' and scope['phase_id'] == phase_after['current_phase_id'])
                rebound = scope['kind'] == 'phase' and scope['phase_id'] != old['phase_id']
                if widened or reactivated or rebound:
                    expanded.append({'field': field, 'quote': quote})
                    break
    return expanded


def validate(checkpoint, sources, prior, indices, observed_source):
    from memory.wsc_handoff_phase import PhaseError
    if not prior.active_count or not prior.checkpoint or 'phase_state' not in prior.checkpoint:
        return
    if 'phase_state' not in checkpoint:
        raise PhaseError('handoff_phase_state_required', field='checkpoint.phase_state',
                         base_checkpoint_source=prior.checkpoint_source)
    expanded = expanded_facts(prior.checkpoint, checkpoint, sources)
    if not expanded:
        return
    phase = checkpoint['phase_state']
    current = next(record for record in phase['phases'] if record['id'] == phase['current_phase_id'])
    if not any(indices[uid][0] > prior.checkpoint_source and observed_source(sources, indices[uid][0])
               for uid in current['source_message_ids']):
        raise PhaseError('handoff_fact_applicability_event_missing', expanded_facts=expanded,
                         base_checkpoint_source=prior.checkpoint_source, current_phase_id=phase['current_phase_id'])
