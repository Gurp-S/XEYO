"""Isolated E patch protocol. No semantic inference or automatic fact retirement."""
from copy import deepcopy
import hashlib,json
from synaptic.todo_snapshot import latest_todo_snapshot
from synaptic.task_phase import applicable
from tools.todo_write_tool.todo_write_tool import parse_input,TodoWriteTool,_merge_todos
from tools.todo_write_tool.types import todo_item_from_raw

def fact_id(field,fact):
    return 'f'+hashlib.sha256(json.dumps([field,fact],ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]

def registry(checkpoint):
    phase=checkpoint.get('phase_state',{});scopes=phase.get('fact_scopes',{})
    return [{'id':fact_id(field,fact),'field':field,'index':i,'scope':deepcopy(scopes.get(field,[{'kind':'task'}]*len(checkpoint.get(field,[])))[i])}
            for field in ['constraints','decisions'] for i,fact in enumerate(checkpoint.get(field,[]))]

def schema():
    ids={'type':'array','items':{'type':'string'}}
    return {'name':'TodoWrite','description':'Declared task-state updates. Unmentioned committed facts remain stored. New facts have an exact source quote and explicit task/phase applicability. retire_facts removes only named committed facts with declared event witnesses. Execution binds the update to the captured state version. Initial state includes objective, phase and todos. Verification IDs identify observed completed calls; pending executions are separate engine facts.','input_schema':{'type':'object','additionalProperties':False,'properties':{
      'objective':{'type':'string'},'phase':{'type':'object','properties':{'id':{'type':'string'},'name':{'type':'string'},'source_message_ids':ids},'required':['id','name','source_message_ids']},
      'todos':deepcopy(TodoWriteTool().schema()['input_schema']['properties']['todos']),
      'task_status':{'enum':['active','completed','cleared']},'context_message_ids':ids,
      'add_facts':{'type':'array','items':{'type':'object','properties':{'field':{'enum':['constraints','decisions']},'source_message_id':{'type':'string'},'quote':{'type':'string'},'scope':{'enum':['task','phase']},'phase_id':{'type':'string'}},'required':['field','source_message_id','quote','scope']}},
      'retire_facts':{'type':'array','items':{'type':'object','properties':{'id':{'type':'string'},'event_message_ids':ids},'required':['id','event_message_ids']}},
      'add_verification_call_ids':ids
    }}}

def normalize(raw,sources):
    allowed={'objective','phase','todos','task_status','context_message_ids','add_facts','retire_facts','add_verification_call_ids'}
    if not isinstance(raw,dict) or set(raw)-allowed:raise ValueError('invalid_state_patch_fields')
    prior=latest_todo_snapshot(sources);cp=deepcopy(prior.checkpoint or {})
    if not cp and not {'objective','phase','todos'}<=set(raw):raise ValueError('initial_state_fields_missing')
    cp.setdefault('decisions',[]);cp.setdefault('constraints',[]);cp.setdefault('context_message_ids',[]);cp.setdefault('verification_call_ids',[])
    phase_state=deepcopy(cp.get('phase_state',{'phases':[],'fact_scopes':{'constraints':[],'decisions':[]}}))
    if 'phase' in raw:
        p=deepcopy(raw['phase'])
        if not isinstance(p,dict) or set(p)!={'id','name','source_message_ids'}:raise ValueError('invalid_patch_phase')
        phase_state['phases']=[v for v in phase_state['phases'] if v['id']!=p['id']]+[p];phase_state['current_phase_id']=p['id']
    if 'objective' in raw:cp['objective']=raw['objective']
    current=phase_state['current_phase_id'];scopes=phase_state['fact_scopes'];retired=[]
    by_id={r['id']:r for r in registry(cp)} if cp.get('phase_state') else {}
    for entry in raw.get('retire_facts',[]):
        old=by_id.get(entry['id'])
        if old is None:raise ValueError('retired_fact_id_not_found')
        field=old['field'];fact=cp[field][old['index']];retired.append({'field':field,'quote':fact['quote'],'event_message_ids':entry['event_message_ids']})
    removed={(r['field'],r['quote']) for r in retired}
    for field in ['constraints','decisions']:
        kept=[(f,s) for f,s in zip(cp[field],scopes[field]) if (field,f['quote']) not in removed]
        cp[field]=[f for f,s in kept];scopes[field]=[s for f,s in kept]
    for entry in raw.get('add_facts',[]):
        if entry.get('field') not in {'constraints','decisions'} or entry.get('scope') not in {'task','phase'}:raise ValueError('invalid_patch_fact')
        field=entry['field'];fact={'source_message_id':entry['source_message_id'],'quote':entry['quote']}
        scope={'kind':'task'} if entry['scope']=='task' else {'kind':'phase','phase_id':entry.get('phase_id') or current}
        if fact in cp[field]:
            if scopes[field][cp[field].index(fact)]!=scope:raise ValueError('fact_scope_change_requires_retirement')
        else:cp[field].append(fact);scopes[field].append(scope)
    cp['verification_call_ids']=list(dict.fromkeys([*cp['verification_call_ids'],*raw.get('add_verification_call_ids',[])]))
    active=list(raw.get('context_message_ids',phase_state.get('active_context_message_ids',[])))
    for phase in phase_state['phases']:
        if phase['id']==current:active=list(dict.fromkeys([*active,*phase['source_message_ids']]))
    cp['context_message_ids']=list(dict.fromkeys([*cp['context_message_ids'],*active,*[i for p in phase_state['phases'] for i in p['source_message_ids']],*[f['source_message_id'] for field in ['constraints','decisions'] for f in cp[field]]]))
    phase_state['active_context_message_ids']=active;cp['phase_state']=phase_state
    todos=list(prior.records)
    if 'todos' in raw:
        parsed=parse_input({'todos':raw['todos']})
        if isinstance(parsed,dict):raise ValueError(parsed['message'])
        previous=[todo_item_from_raw(v) for v in todos]
        todos=[t.to_dict() for t in _merge_todos([t for t in previous if t],parsed.todos)]
    status=raw.get('task_status')
    if status=='completed':
        for item in todos:item['status']='completed'
    elif status=='cleared':todos=[]
    elif status=='active' and not any(t['status']!='completed' for t in todos):raise ValueError('active_state_without_active_steps')
    elif status not in {None,'active'}:raise ValueError('invalid_patch_task_status')
    normalized={'todos':todos,'checkpoint':cp,'merge':False}
    if retired:
        if not prior.observed or not prior.active_count:raise ValueError('retirement_without_active_base')
        normalized['fact_disposition']={'base_checkpoint_message_id':sources[prior.source]['id'],'retired_facts':retired}
    return normalized
