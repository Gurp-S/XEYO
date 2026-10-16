"""Experimental single-record applicability; normalize into existing checkpoint.

The model still declares facts, scope and retirement. The engine assembles
parallel native fields and binds retirement to the captured state version.
"""
from copy import deepcopy
from synaptic.todo_snapshot import latest_todo_snapshot
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


def schema():
    todos=deepcopy(TodoWriteTool().schema()['input_schema']['properties']['todos'])
    ids={'type':'array','items':{'type':'string'},'maxItems':16}
    fact={'type':'object','description':'Exact quoted decision/constraint from a human or text source; execution evidence is referenced separately by verification_call_ids.','properties':{'source_message_id':{'type':'string'},'quote':{'type':'string'},'scope':{'enum':['task','phase']},'phase_id':{'type':'string'}},'required':['source_message_id','quote','scope'],'additionalProperties':False}
    phase={'type':'object','properties':{'id':{'type':'string'},'name':{'type':'string'},'source_message_ids':ids},'required':['id','name','source_message_ids'],'additionalProperties':False}
    properties={'todos':todos,'objective':{'type':'string'},'phase':phase,'context_message_ids':ids,'constraints':{'type':'array','items':fact,'maxItems':16},'decisions':{'type':'array','items':fact,'maxItems':16},'verification_call_ids':{'type':'array','items':{'type':'string'}},'retired_facts':{'type':'array','items':{'type':'object','properties':{'field':{'enum':['constraints','decisions']},'quote':{'type':'string'},'event_message_ids':ids},'required':['field','quote','event_message_ids']}}}
    return {'name':'TodoWrite','description':'Full task declaration. Each fact includes its exact source quote and task/phase applicability in one record. Phase applicability without phase_id names the submitted current phase. Historical phase provenance remains stored. Verification IDs refer to observed tool calls. Retirement is explicitly declared; execution binds it to the captured committed-state version.','input_schema':{'type':'object','properties':properties,'required':['todos','objective','phase','context_message_ids','constraints','decisions','verification_call_ids'],'additionalProperties':False}}


def normalize(raw,sources):
    if not isinstance(raw,dict):raise ValueError('invalid_flat_state')
    required={'todos','objective','phase','context_message_ids','constraints','decisions','verification_call_ids'}
    if required-set(raw) or set(raw)-required-{'retired_facts'}:raise ValueError('invalid_flat_state_fields')
    if not isinstance(raw['phase'],dict) or set(raw['phase'])!={'id','name','source_message_ids'}:raise ValueError('invalid_flat_phase')
    for field in ['constraints','decisions']:
        if not isinstance(raw[field],list):raise ValueError('invalid_flat_facts')
        for fact in raw[field]:
            if not isinstance(fact,dict) or not {'source_message_id','quote','scope'}<=set(fact) or set(fact)-{'source_message_id','quote','scope','phase_id'} or fact['scope'] not in {'task','phase'}:raise ValueError('invalid_flat_fact_scope')
    prior=latest_todo_snapshot(sources);old=prior.checkpoint or {}
    phase=deepcopy(raw['phase']);phases=deepcopy(old.get('phase_state',{}).get('phases',[]))
    phases=[p for p in phases if p['id']!=phase['id']]+[phase]
    contexts=list(dict.fromkeys([*old.get('context_message_ids',[]),*raw['context_message_ids'],*[u for p in phases for u in p['source_message_ids']],*[f['source_message_id'] for field in ['constraints','decisions'] for f in raw[field]]]))
    cp={'objective':raw['objective'],'context_message_ids':contexts,'verification_call_ids':deepcopy(raw['verification_call_ids'])}
    scopes={}
    for field in ['constraints','decisions']:
        cp[field]=[{'source_message_id':f['source_message_id'],'quote':f['quote']} for f in raw[field]]
        scopes[field]=[{'kind':'task'} if f['scope']=='task' else {'kind':'phase','phase_id':f.get('phase_id') or phase['id']} for f in raw[field]]
    cp['phase_state']={'current_phase_id':phase['id'],'phases':phases,'active_context_message_ids':deepcopy(raw['context_message_ids']),'fact_scopes':scopes}
    normalized={'todos':deepcopy(raw['todos']),'checkpoint':cp,'merge':False}
    if raw.get('retired_facts'):
        if not prior.observed:raise ValueError('retirement_without_committed_base')
        normalized['fact_disposition']={'base_checkpoint_message_id':sources[prior.source]['id'],'retired_facts':deepcopy(raw['retired_facts'])}
    return normalized
