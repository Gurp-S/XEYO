"""Describe the span frontend's actual independent retention choices."""
from copy import deepcopy

from .selection_effects import FULL_SOURCE_EFFECT, SPAN_EFFECT

__all__ = ["FULL_SOURCE_EFFECT", "SPAN_EFFECT", "span_facts"]


def span_facts(facts):
    if facts.get('schema')=='wsc.projected_selection_facts/1':
        from .projected_selection_facts import span_facts as projected_span_facts
        return projected_span_facts(facts)
    result = deepcopy(facts)
    effects = result['selection_effects']
    effects.pop('quotes', None)
    effects['source_ids'] = FULL_SOURCE_EFFECT
    effects['span_refs'] = SPAN_EFFECT
    return result
