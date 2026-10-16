"""Offline evaluation contracts and rejection/restart evidence; zero API calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re
from unittest.mock import patch

import httpx
import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
from evals.wsc_ad_candidate import commit_candidate,evidence,persist_state,read_state,digest
from evals.wsc_d_handoff_shell_control import extract_d
from memory.wsc_execution_boundary import fold_cut,protect

ROOT=e.ROOT.parent/'wsc-elimination-offline-234'


async def transport_contracts():
    # Do not instantiate Calls: tests need no real credentials or network.
    calls=f.StopAwareCalls.__new__(f.StopAwareCalls);calls.report={};calls.save=lambda:None
    count=0
    async def refused(*args,**kwargs):
        nonlocal count;count+=1
        response=httpx.Response(402,request=httpx.Request('POST','https://api.deepseek.com/chat/completions'))
        raise httpx.HTTPStatusError('Payment required',request=response.request,response=response)
    with patch.object(e.Calls,'call',refused):
        for label in ('first','second'):
            try:await calls.call({},label)
            except f.EvaluationStop:pass
            else:raise AssertionError('Stopped run dispatched a request')
    assert count==1 and calls.report['stopped_at']=='first'
    return {'payment_stop_checks':2,'parent_transport_invocations':count,'real_http_calls':0}


def main():
    ROOT.mkdir(exist_ok=True);assert not (ROOT/'contracts.json').exists()
    pattern=r'(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{24,}'
    credential='sk-'+'X'*32
    examples=[('long_noise_task-source-read-1-1-invocation',False),(credential,True),
              ('"'+credential+'"',True),('Authorization: Bearer '+credential,True),('sk-short',False)]
    for text,expected in examples:assert bool(re.search(pattern,text))==expected
    plan=f.c.load(ROOT.parent/'wsc-elimination-faithful-233/preflight-manifest.json');boundary=[]
    for case in plan['cases']:
        rows=[]
        for n,events in enumerate(case['events']):
            rows.extend(events);cut=fold_cut(rows)
            assert events[0]['id'] not in {r['id'] for r in rows[cut:]}
            boundary.append({'case':case['case'],'fold':n+1,'cut':cut,'tail_records':len(rows)-cut,'task_event_actually_compressed':True})
    # An isolated handoff is not a main-model consumption receipt for a late result.
    rows=[{'role':'user','content':'task'},
          {'role':'assistant','content':[{'type':'tool_use','id':'r1','name':'Read','input':{}}]},
          {'role':'assistant','content':'Other work'},
          {'role':'tool','content':[{'type':'tool_result','tool_use_id':'r1','content':'late'}]},
          {'role':'assistant','content':[{'type':'tool_use','id':'h1','name':'TodoWrite','input':{}}]},
          {'role':'tool','content':[{'type':'tool_result','tool_use_id':'h1','content':'stored','execution':{'compaction_handoff':True}}]}]
    assert protect(rows,len(rows))==1
    control=f.c.load(ROOT.parent/'wsc-elimination-230/incremental-D-D2-control.json')
    recovery=[]
    for name in e.CASES:
        folder=ROOT.parent/'wsc-D-shell-224'/name
        prior=read_state(folder/'D2-state.json')
        rawrows=[json.loads(s) for s in (e.ORIGINAL/name/'source.jsonl').read_text(encoding='utf-8').splitlines()]
        _,decl,_,_,_=extract_d(e.ORIGINAL/name);store=evidence(rawrows+decl)
        valid=f.c.load(folder/'IR-candidate.json');valid['baseline']=prior['checkpoint_id']
        for pair in control['pairs']:
            if pair['case']!=name or not pair['D_accepted'] or pair['D2_accepted']:continue
            assert pair['prior_state_sha256']==pair['after_state_sha256']==digest(prior)
            checkpoint=ROOT/(name+'-'+pair['mutation']+'-restored.json')
            persist_state(checkpoint,prior);restored=read_state(checkpoint)
            after,errors,accepted=commit_candidate(restored,deepcopy(valid),store,'AD2',reference_policy='event')
            assert accepted and not errors and after['checkpoint_id']==prior['checkpoint_id']+1
            recovery.append({'case':name,'rejected_mutation':pair['mutation'],'rejected_state_unchanged':True,
                             'restart_round_trip':True,'unchanged_legal_candidate_accepted_after_restart':True,
                             'semantic_task_continuation_tested':False})
    result={'credential_pattern_cases':len(examples),'tail_boundary_cases':boundary,'isolated_handoff_does_not_consume_late_result':True,
            'transport':asyncio.run(transport_contracts()),'rejection_recovery':recovery,
            'scope':'Evaluation contracts only; unchanged-state recovery is not completion of rejected legal task transitions. Zero API.'}
    e.write(ROOT/'contracts.json',result)
    print(json.dumps({'credential_cases':len(examples),'tail_cases':len(boundary),'late_boundary_cases':1,
                      'payment_stop_checks':2,'rejection_restart_cases':len(recovery),'api_calls':0}))


if __name__=='__main__':main()
