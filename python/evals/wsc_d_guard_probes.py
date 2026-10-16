"""Offline guard countercontrols on actual retained D state; no API calls.

New witness is synthetic and explicitly carries no retirement/reopen command.
These probes identify prototype boundaries, not model semantic accuracy.
"""
from copy import deepcopy
from pathlib import Path
import json

from evals.wsc_ad_candidate import commit_candidate, evidence
from evals.wsc_d_reliable_control import ROOT, LABELS, load
import evals.wsc_ad_experiment as e


def probe():
    results=[]
    for name in e.CASES:
        folder=ROOT/name;source=next(folder.glob('source-*.jsonl'));decl_path=next(folder.glob('declaration-*.json'))
        rows=[json.loads(s) for s in source.read_text(encoding='utf-8').splitlines()]+load(decl_path)
        rows.append({'id':'synthetic-review-witness-'+name,'role':'user','content':'现在给我当前进度。'})
        store=evidence(rows);witness=rows[-1]['id']
        ref={'event_id':witness,'content_hash':store[witness]['hash'],'sequence':store[witness]['sequence']}
        state=load(folder/'AD2-committed-cold-state.json')['state']
        for mode in ('AD1','AD2'):
            for mutation in ('wrong_baseline','wrong_hash','missing_source','drop_active_fact','terminal_revival_without_new_source',
                             'unsupported_constraint_shortening','unrelated_user_terminal_reopen','nonexistent_phase_scope'):
                target=next(f for f in state['facts'] if f['kind']=='constraint')
                if 'terminal' in mutation:
                    matches=[f for f in state['facts'] if f['status']=='RESOLVED']
                    if not matches:continue
                    target=matches[0]
                facts=deepcopy(state['facts']);selected=next(f for f in facts if f['fact_id']==target['fact_id'])
                actions={}
                if mutation=='wrong_hash':selected['evidence_refs'][0]['content_hash']='0'*64
                elif mutation=='missing_source':selected['evidence_refs'][0]['event_id']='does-not-exist'
                elif mutation=='drop_active_fact':facts=[f for f in facts if f['fact_id']!=target['fact_id']]
                elif mutation=='terminal_revival_without_new_source':selected['status']='ACTIVE'
                elif mutation=='unsupported_constraint_shortening':
                    selected['content']='只保留原约束中的一个片段';selected['evidence_refs']=[deepcopy(ref)]
                elif mutation=='unrelated_user_terminal_reopen':
                    selected['status']='ACTIVE';selected['evidence_refs']=[deepcopy(ref)]
                    actions[selected['fact_id']]='reopen';selected['reopen']=True
                elif mutation=='nonexistent_phase_scope':
                    selected['scope']={'kind':'PHASE','id':'phase-does-not-exist'};selected['evidence_refs']=[deepcopy(ref)]
                candidate={'baseline':state['checkpoint_id']+(mutation=='wrong_baseline'),'goal_id':state['goal_id'],
                    'source_cursor':len(store)-1}
                if mode=='AD1':candidate['changes']=[{'action':actions.get(f['fact_id'],'update'),'fact':f} for f in facts]
                else:candidate['facts']=facts
                after,errors,accepted=commit_candidate(state,candidate,store,mode,reference_policy='event')
                actual=next((f for f in after['facts'] if f['fact_id']==target['fact_id']),None)
                content_preserved=actual is not None and all(actual[k]==target[k] for k in ('content','status','scope','evidence_refs'))
                result={'case':name,'mode':mode,'mutation':mutation,'accepted':accepted,'errors':errors,
                    'target_preserved':content_preserved,'checkpoint_before':state['checkpoint_id'],'checkpoint_after':after['checkpoint_id'],
                    'witness_kind':'synthetic progress query, no retirement/reopen authorization'}
                results.append(result)
    out={'scope':'Actual prototype mechanical guard checks and limitations; not whole architecture/model benchmark.',
         'probes':results,'contracts':{},'gaps':{}}
    for r in results:
        bucket='gaps' if r['mutation'] in {'unsupported_constraint_shortening','unrelated_user_terminal_reopen','nonexistent_phase_scope'} else 'contracts'
        counts=out[bucket].setdefault(r['mutation'],{'count':0,'target_preserved':0})
        counts['count']+=1;counts['target_preserved']+=int(r['target_preserved'])
    (ROOT/'guard-probes.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    return out


if __name__=='__main__':
    result=probe();print(json.dumps({k:v for k,v in result.items() if k!='probes'},ensure_ascii=False))
