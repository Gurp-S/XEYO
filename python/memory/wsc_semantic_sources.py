"""Generation-only alternatives from an already verified installed head."""
from copy import deepcopy


def inputs(messages, working, source, *, cwd=None):
    from memory.wsc_semantic_input import for_generation
    from session.late_result_projection import project
    from synaptic.receipt_render import projection_enabled, render

    body = for_generation(messages, working, source, cwd=cwd)
    index = next((i for i, row in enumerate(body) if row.get('role') != 'system'), len(body))
    normalized = project(source)
    if body is messages:
        # A rejected installed head can expose the entire original history.
        # Normalize only an exact source match, never arbitrary caller material.
        if body[index:] == normalized and projection_enabled():
            return [*body[:index], *render(normalized)], None
        return body, None
    # for_generation replaced only a verified, leading engine-owned head.
    # The surrounding request may contain control/presentation not in source.
    prefix = normalized[:working.compact_cursor]
    # Match the existing emission without re-rendering its already frozen tail.
    if projection_enabled():
        prefix = render(prefix)
    restored = [*body[:index], *prefix, *body[index+1:]]
    return body, deepcopy(restored)
