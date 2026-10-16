"""Matched phase3 full-delta reference, separates missing context from judgment."""
import asyncio
from copy import deepcopy
import hashlib
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
import evals.wsc_d_combined_continuity as combined

ROOT=e.ROOT.parent/'wsc-D-unfolded-control-252'
PREVIOUS=ROOT.parent/'wsc-D-observation-continuity-251'


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    old=f.c.load(PREVIOUS/'preflight-manifest.json')
    assert f.c.load(PREVIOUS/'run-report.json')['completed']
    plan={'cases':old['cases'],'arms':['unfolded_delta'],'folds':[3],
        'hypothesis':'Original model receives all post-seed events without folding; valid current result remains directly visible alongside late old result.',
        'comparison':'Same239 D seed,251 external events, common query/cold tools. D251 consumed ledger after phase2 is mechanically copied; no model answer or gold in context.',
        'limits':'Same3 observer requests, no handoff calls, no HTTP retry, per-call<=2.5 CNY, stop402.',
        'nonclaim':'Delta-preserving reference after an already compacted real seed, not full original1M history or task success.',
        'paid_run_allowed':False,'proposed_new_run_cost_ceiling_cny':None,
        'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,
            'python/evals/wsc_d_combined_continuity.py','python/evals/wsc_elimination_faithful.py',
            'python/evals/wsc_ad_experiment.py','python/evals/wsc_answer_parse.py']}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


async def execute(plan):
    assert plan['paid_run_allowed'] and not (ROOT/'run-report.json').exists()
    for p,sha in plan['code_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha
    e.ROOT=ROOT;f.ROOT=ROOT;f.c.ROOT=ROOT;combined.ROOT=ROOT
    os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=f.StopAwareCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=plan,observations=[],controls=[])
    gold=f.c.load(e.OLD/'gold.json')
    for case in plan['cases']:
        name=case['case']
        branch=combined.recover_seed(name,'D_delta')
        # Rename only the evaluation folder pointer; preserve original239 seed.
        folder=ROOT/name/'unfolded_delta';folder.mkdir()
        branch['folder']=folder
        phase2=f.c.load(PREVIOUS/name/'D_delta/restart-2.json')['state']
        branch['consumed']=set(phase2['consumed'])
        branch['sources'].extend(deepcopy(sum(case['events'][1:3],[])))
        branch['hot'].extend(f.c.carrier(r) for r in sum(case['events'][1:3],[]))
        branch['accepted_fold']=3
        f.c.persist_sources(branch);branch=combined.restart(branch,3)
        record={'case':name,'hot_tokens':e.tokens(branch['hot']),
            'postseed_event_ids':[r['id'] for r in sum(case['events'][1:3],[])],
            'consumption_source':str(PREVIOUS/name/'D_delta/restart-2.json'),
            'source_locator':f.c.load(folder/'restart-3.json')['state']['source_locator'],
            'reference_type':'No post-seed folding, not generated checkpoint'}
        calls.report['controls'].append(record);calls.save()
        result=await combined.observe(calls,branch,name,'unfolded_delta',2,case['expected'][2],gold[name]['cold_excerpt'])
        calls.report['observations'].append(result);calls.save()
        print(f.c.canonical({'case':name,'state_success':result.get('state_success'),
            'wrong':[k for k,v in (result.get('grade') or {}).items() if not v],
            'cold_exact':result.get('cold_exact'),'error':result.get('error')}),flush=True)
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_UNFOLDED_EXECUTE')=='1':
        try:asyncio.run(execute(f.c.load(ROOT/'preflight-manifest.json')))
        except f.EvaluationStop as exc:print(f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(f.c.canonical({'prepared':prepare()['arms']}))
