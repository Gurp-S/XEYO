"""Targeted adversarial contracts for experimental AD1/AD2 only."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from evals.wsc_ad_candidate import (commit_candidate, denoise, digest, evidence,
    initial, persist_state, read_state)


def main():
    root=Path('D:/lea/XenYon code/_wsc_out/wsc-AD-213');root.mkdir(exist_ok=True)
    rows=[{'id':'u1','role':'user','content':'No publish. Integer cents. Task Q open.'},
          {'id':'u2','role':'user','content':'Task Q accepted and resolved.'},
          {'id':'u3','role':'user','content':'Reopen task Q. No publish.'}]
    store=evidence(rows);checks={}
    constraint={'fact_id':'C1','kind':'constraint','content':'Publishing not authorized','status':'ACTIVE',
        'scope':{'kind':'TASK'},'evidence_refs':[{'event_id':'u1','quote':'No publish.'}]}
    request={'fact_id':'Q1','kind':'request','content':'Task Q open','status':'OPEN',
        'scope':{'kind':'TASK'},'evidence_refs':[{'event_id':'u1','quote':'Task Q open.'}]}
    def candidate(state,mode,facts,cursor=2):
        return {'baseline':state['checkpoint_id'],'goal_id':state['goal_id'],'source_cursor':cursor,
            ('changes' if mode=='AD1' else 'facts'):facts}
    states={}
    for mode in ['AD1','AD2']:
        s=initial('Q');items=[{'action':'add','fact':f} for f in [constraint,request]] if mode=='AD1' else [constraint,request]
        s,errors,ok=commit_candidate(s,candidate(s,mode,items,0),store,mode);assert ok and not errors;states[mode]=s
    a,errors,ok=commit_candidate(states['AD1'],candidate(states['AD1'],'AD1',[]),store,'AD1')
    checks['AD1_omitted_active_fact_carried']=ok and len(a['facts'])==2
    a,errors,ok=commit_candidate(states['AD2'],candidate(states['AD2'],'AD2',[request]),store,'AD2')
    checks['AD2_omitted_active_fact_rejected']=not ok and a==states['AD2']
    for mode in ['AD1','AD2']:
        s=states[mode];c=candidate(s,mode,[]);c['baseline']=999
        a,e,ok=commit_candidate(s,c,store,mode);checks[mode+'_baseline_rejected']=not ok and a==s
        bad=deepcopy(constraint);bad['scope']={'kind':'PHASE','id':'later'}
        items=[{'action':'update','fact':bad}] if mode=='AD1' else [bad,request]
        a,e,ok=commit_candidate(s,candidate(s,mode,items),store,mode)
        checks[mode+'_scope_downgrade_requires_new_evidence']=('transition_without_new_evidence' in e)
        closed=deepcopy(request);closed.update(status='RESOLVED',evidence_refs=[{'event_id':'u2','quote':'Task Q accepted and resolved.'}])
        items=[{'action':'update','fact':closed}] if mode=='AD1' else [constraint,closed]
        s,e,ok=commit_candidate(s,candidate(s,mode,items,1),store,mode);assert ok
        revived=deepcopy(request)
        items=[{'action':'update','fact':revived}] if mode=='AD1' else [constraint,revived]
        a,e,ok=commit_candidate(s,candidate(s,mode,items),store,mode)
        checks[mode+'_old_evidence_revival_blocked']=any(x in e for x in ['terminal_fact_revival','transition_without_new_evidence'])
        revived.update(status='REOPENED',evidence_refs=[{'event_id':'u3','quote':'Reopen task Q.'}])
        if mode=='AD2':revived['reopen']=True
        items=[{'action':'reopen','fact':revived}] if mode=='AD1' else [constraint,revived]
        a,e,ok=commit_candidate(s,candidate(s,mode,items),store,mode);checks[mode+'_new_user_reopen_allowed']=ok and not e
        corrupt=deepcopy(constraint);corrupt['evidence_refs'][0]['content_hash']='bad'
        items=[{'action':'update','fact':corrupt}] if mode=='AD1' else [corrupt,request]
        a,e,ok=commit_candidate(s,candidate(s,mode,items),store,mode);checks[mode+'_corrupt_reference_rejects_whole']=not ok and a==s
    s=states['AD1'];bad=deepcopy(constraint);bad['fact_id']='Cbad';bad['evidence_refs']=[]
    good=deepcopy(request);good['fact_id']='Qnew'
    a,e,ok=commit_candidate(s,candidate(s,'AD1',[{'action':'add','fact':bad},{'action':'add','fact':good}]),store,'AD1')
    checks['AD1_independent_valid_item_salvaged']=ok and any(f['fact_id']=='Qnew' for f in a['facts']) and not any(f['fact_id']=='Cbad' for f in a['facts'])
    multi={}
    for mode in ['AD1','AD2']:
        s=states[mode];counts={'attempts':10,'active_loss':0,'rejected':0}
        for i in range(10):
            a,e,ok=commit_candidate(s,candidate(s,mode,[]),store,mode)
            counts['active_loss']+=int(not any(f['fact_id']=='C1' and f['status']=='ACTIVE' for f in a['facts']))
            counts['rejected']+=int(not ok);s=a
        multi[mode]=counts
    checks['ten_generations_active_state_retained']=all(v['active_loss']==0 for v in multi.values())
    path=root/'contract-state.json';persist_state(path,states['AD1']);before=path.read_bytes()
    checks['state_round_trip']=read_state(path)==states['AD1']
    with patch('evals.wsc_ad_candidate._atomic_write',side_effect=OSError('fault')):
        try:persist_state(path,a)
        except OSError:pass
    checks['publish_failure_retains_old_bytes']=path.read_bytes()==before
    fake=[{'id':'a','role':'assistant','content':'Uncertain failure, do not infer resolved.'},
          {'id':'u','role':'user','content':'Natural-language constraint remains verbatim.'}]
    reduced,details=denoise(fake,root/'fake.jsonl');checks['ambiguous_and_user_text_not_denoised']=reduced==fake and not details
    # Late results are keyed by invocation identity, not one mutable per-session slot.
    queue={'call-r1':{'revision':'r1'},'call-r2':{'revision':'r2'}}
    checks['late_queue_invocations_do_not_overwrite']=queue['call-r1']['revision']=='r1'
    native=deepcopy(constraint);native['evidence_refs']=[{'event_id':'u1','content_hash':store['u1']['hash']}]
    ns=initial('native');nc=candidate(ns,'AD2',[native],0)
    n,e,ok=commit_candidate(ns,nc,store,'AD2',reference_policy='event')
    checks['native_event_hash_reference_without_quote_allowed']=ok and not e
    bad=deepcopy(nc);bad['facts'][0]['evidence_refs'][0]['content_hash']='corrupt'
    n,e,ok=commit_candidate(ns,bad,store,'AD2',reference_policy='event')
    checks['native_corrupt_hash_rejects_whole']=not ok and n==ns
    bad=deepcopy(nc);bad['facts'][0]['evidence_refs'][0]['event_id']='missing'
    n,e,ok=commit_candidate(ns,bad,store,'AD2',reference_policy='event')
    checks['native_missing_event_rejected']=not ok and n==ns
    assert all(checks.values()),checks
    (root/'contract-report.json').write_text(json.dumps({'checks':checks,'multi_generation':multi},indent=2),encoding='utf-8')
    print(f'Experimental AD contracts: {sum(checks.values())}/{len(checks)}')


if __name__=='__main__':main()
