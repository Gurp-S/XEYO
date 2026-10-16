"""Independent paired two-fold evidence retention trial; no prompt edits."""
import asyncio
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
import evals.wsc_d_combined_continuity as combined
from evals.wsc_d_generation_candidate import Labels
from memory.wsc_declaration_candidate import DeclarationCalls
from memory.wsc_handoff_delta_candidate import DeltaCalls
from memory.wsc_observation_schema_candidate import ObservationCalls

ROOT=e.ROOT.parent/'wsc-D-observation-continuity-251'
ARMS=('A1','D_delta','D_observations')


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    previous=combined.PREVIOUS
    old=f.c.load(ROOT.parent/'wsc-elimination-faithful-235/preflight-manifest.json')
    shutil.copytree(previous/'frozen-workspace',ROOT/'frozen-workspace')
    for case in old['cases']:
        name=case['case'];shutil.copytree(previous/name/'world',ROOT/name/'world')
        for stage in case['events']:
            for row in stage:
                for block in row.get('content',[]) if isinstance(row.get('content'),list) else []:
                    if block.get('type')=='tool_use' and block.get('name')=='Read':
                        block['input']['file_path']=str(ROOT/name/'world'/Path(block['input']['file_path']).name)
    paths=[__file__,'python/memory/wsc_observation_schema_candidate.py',
        'python/memory/wsc_handoff_generation.py','python/evals/wsc_d_combined_continuity.py',
        'python/evals/wsc_elimination_faithful.py','python/evals/wsc_ad_experiment.py',
        'python/synaptic/task_observations.py','python/evals/wsc_answer_parse.py']
    plan={'cases':old['cases'],'arms':list(ARMS),'folds':[2,3],'seed_fold':239,
        'hypothesis':'Exposing existing exact result observations preserves model-selected working evidence before it leaves recent context.',
        'single_change':'D_observations adds only optional native observations schema; identical D seed, generator, prompt, validator, tail, source/catalog and observer tools.',
        'protocol':'Every arm owns its subsequent state and consumption ledger; native6 generation requests and3 observer requests; stop on402.',
        'nonclaim':'Two controlled extensions after a real-derived seed; not 10 folds, live85%, holdout generalization or original228 acceptance.',
        'model':'deepseek-flash','temperature':0,'http_retries':0,'proposed_new_run_cost_ceiling_cny':None,
        'paid_run_allowed':False,'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


def seeds(plan):
    combined.ROOT=ROOT
    branches={}
    for case in plan['cases']:
        name=case['case']
        for arm in ('A1','D_delta'):
            branches[name,arm]=combined.restart(combined.recover_seed(name,arm),1)
        base=branches[name,'D_delta'];clone=deepcopy(base)
        clone['folder']=ROOT/name/'D_observations';clone['folder'].mkdir()
        f.c.persist_sources(clone)
        branches[name,'D_observations']=combined.restart(clone,1)
        assert base['hot']==clone['hot'] and base['native']==clone['native'] and base['sources']==clone['sources']
        e.write(ROOT/name/'seed-proof.json',{'D_seed_identical':True,
            'hot_sha256':f.c.digest(base['hot']),'native_sha256':f.c.digest(base['native']),
            'source_bytes_identical':(base['folder']/'source.jsonl').read_bytes()==(clone['folder']/'source.jsonl').read_bytes()})
    return branches


async def execute(plan,*,transport_factory=None,seed_factory=None):
    assert plan['paid_run_allowed'] and not (ROOT/'run-report.json').exists()
    for p,sha in plan['code_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha
    assert 'observations' not in f.c.TodoWriteTool().schema()['input_schema']['properties']['checkpoint']['properties']
    e.ROOT=ROOT;f.ROOT=ROOT;f.c.ROOT=ROOT;combined.ROOT=ROOT
    os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    parallelism=plan.get('branch_parallelism',1)
    assert parallelism in (1,2)
    calls=f.StopAwareCalls();calls.semaphore=asyncio.Semaphore(parallelism)
    calls.report.update(protocol=plan,folds=[],observations=[])
    branches=(seed_factory or seeds)(plan);gold=f.c.load(e.OLD/'gold.json')
    async def one(case,arm,n):
        name=case['case'];branch=branches[name,arm]
        try:
            if arm=='A1':record=await f.c.fold(Labels(calls,arm),branch,name,arm,n,case['events'][n])
            else:
                if transport_factory is not None:
                    transport=transport_factory(Labels(calls,arm),branch['sources']+case['events'][n],arm)
                else:
                    transport=Labels(calls,arm)
                    if arm=='D_observations':transport=ObservationCalls(transport)
                    transport=DeltaCalls(DeclarationCalls(transport),branch['sources']+case['events'][n])
                record=await f.native_fold(transport,branch,name,n,case['events'][n])
            record['arm']=arm;f.add_native_tail(branch,sum(case['events'][:n+1],[]),record)
            branch=combined.restart(branch,n+1);branches[name,arm]=branch
            record['restart_roundtrip']=True
            e.write(branch['folder']/f'fold-{n+1}-result.json',record)
            calls.report['folds'].append(record);calls.save()
            observation=await combined.observe(calls,branch,name,arm,n,case['expected'][n],gold[name]['cold_excerpt'])
            calls.report['observations'].append(observation);calls.save()
            print(f.c.canonical({'case':name,'arm':arm,'fold':n+1,'accepted':record['candidate_accepted'],
                'result_observations':len((record.get('candidate') or {}).get('checkpoint',{}).get('observations',[])),
                'errors':record['errors'],'wrong':[k for k,v in (observation.get('grade') or {}).items() if not v],
                'cold_exact':observation.get('cold_exact'),'observer_error':observation.get('error')}),flush=True)
        except f.EvaluationStop as exc:
            e.write(branch['folder']/f'stop-{n+1}.json',{'error':str(exc),'accepted_fold':branch['accepted_fold'],
                'pending_source_ids':[r['id'] for r in branch['pending']],'hot_sha256':f.c.digest(branch['hot'])})
            raise
        finally:
            # A payment/transport stop must not lose already appended events.
            f.c.persist_sources(branch)
            branches[name,arm]=combined.restart(branch,n+1)
    for n in (1,2):
        jobs=[(case,arm) for case in plan['cases'] for arm in ARMS]
        if parallelism==1:
            for case,arm in jobs:await one(case,arm,n)
        else:
            # Let admitted in-flight requests settle; queued calls check the
            # shared stop flag before reservation/sending. No HTTP resends.
            outcomes=await asyncio.gather(*(one(case,arm,n) for case,arm in jobs),return_exceptions=True)
            for result in outcomes:
                if isinstance(result,BaseException):raise result
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_OBSERVATION_EXECUTE')=='1':
        try:asyncio.run(execute(f.c.load(ROOT/'preflight-manifest.json')))
        except f.EvaluationStop as exc:print(f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(f.c.canonical({'prepared':prepare()['arms']}))
