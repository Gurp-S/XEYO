"""Optional exact at-rest projection costs; no semantic retention decisions."""
from .contracts import encode,require
from .selection_effects import SPAN_EFFECT
from .selection_facts import describe as legacy_describe
from .source_reference_view import MODE,project
from .view_budget import mandatory_sources

SCHEMA='wsc.projected_selection_facts/1'


def empty_body(prefix,mode=MODE):
    return dict(sources=project(mandatory_sources(prefix),mode),understandings=[],clues=[],source_projection=mode)


def describe(prefix,max_view_bytes,*,mode=MODE):
    facts=legacy_describe(project(prefix,mode),max_view_bytes)
    facts.update(schema=SCHEMA,source_projection=mode,
        mandatory_empty_view_bytes=len(encode(empty_body(prefix,mode)).encode('utf-8')),
        measurement_scope='Prepared-view JSON in UTF-8 with the registered source projection. Message payloads remain inline; non-message payloads use bound source references. Public text remains inline. Not model tokens, hydrated adapter bytes or external storage.')
    facts['selection_effects']['source_ids']='Selected source records use the registered at-rest projection; repeated identities occur once. Message payloads remain inline; non-message payloads remain in the bound source store. Projection does not remove the public text of a selected source.'
    return facts


def admit(prefix,max_view_bytes,*,mode=MODE):
    require(all(r['kind']!='opaque' for r in mandatory_sources(prefix)),'opaque_hot_selection_unavailable')
    require(len(encode(empty_body(prefix,mode)).encode('utf-8'))<=max_view_bytes,'mandatory_view_byte_budget_exhausted')


def span_facts(facts):
    # The frontend describes spans, but cannot overwrite the storage contract.
    from copy import deepcopy
    require(facts.get('schema')==SCHEMA and facts.get('source_projection')==MODE,'projected_selection_facts_invalid')
    result=deepcopy(facts);result['selection_effects'].pop('quotes',None)
    result['selection_effects']['span_refs']=SPAN_EFFECT
    return result
