"""New independent fold3 experiment: atomic scope encoding only, A1 control."""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
import evals.wsc_d_combined_continuity as combined
from evals.wsc_d_generation_candidate import Labels
from memory.wsc_declaration_candidate import DeclarationCalls
from memory.wsc_handoff_delta_candidate import DeltaCalls
from memory.wsc_scoped_fact_candidate import ScopedCalls

ROOT=e.ROOT.parent/'wsc-D-scoped-generation-250'
SEED=ROOT.parent/'wsc-D-combined-continuity-247'
ARMS=('A1','D_delta','D_scoped')


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    old=f.c.load(SEED/'preflight-manifest.json')
    shutil.copytree(SEED/'frozen-workspace',ROOT/'frozen-workspace')
    for case in old['cases']:
        name=case['case'];shutil.copytree(SEED/name/'world',ROOT/name/'world')
        for row in case['events'][2]:
            for block in row.get('content',[]) if isinstance(row.get('content'),list) else []:
                if block.get('type')=='tool_use' and block.get('name')=='Read':
                    block['input']['file_path']=str(ROOT/name/'world'/Path(block['input']['file_path']).name)
    plan={'cases':old['cases'],'arms':list(ARMS),'folds':[3],
        'hypothesis':'Co-locating quote and scope eliminates independent-array cardinality failures without choosing semantic applicability.',
        'single_change':'D_scoped changes only TodoWrite wire representation; same D prior state, native validator, prompt, source delta, output and call limits.',
        'baseline':'A1 uses its own247 fold2 state; D arms share D247 fold2 state. Independent new generation; prior failures preserved.',
        'paid_run_allowed':False,'http_retries':0,'observer_max_calls':3,'generation_native_max_calls':6,
        'model':'deepseek-flash','temperature':0,'proposed_new_run_cost_ceiling_cny':None,
        'expected_nonclaim':'No observation schema change or evidence hydration. Missing selected result content may still fail task quality.',
        'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,
            'python/memory/wsc_scoped_fact_candidate.py','python/evals/wsc_elimination_faithful.py',
            'python/evals/wsc_d_combined_continuity.py','python/evals/wsc_ad_experiment.py']}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


def seed(name,arm):
    prior_arm='A1' if arm=='A1' else 'D_delta'
    old=SEED/name/prior_arm
    state=f.c.load(old/'restart-2.json')['state']
    source_lines=(old/'source.jsonl').read_bytes().splitlines(keepends=True)
    rows=[json.loads(s) for s in source_lines]
    # Later source appends invalidated247's old mutable seal. Reconstruct its
    # exact chronological prefix and verify against the originally saved hash.
    cut=next(i for i,r in enumerate(rows) if r['id']==name+'-user-event-3')
    rows=rows[:cut]
    raw=b''.join(source_lines[:cut])
    assert hashlib.sha256(raw).hexdigest()==state['source_sha256']
    folder=ROOT/name/arm;folder.mkdir(exist_ok=True)
    branch={'folder':folder,'sources':rows,'state':None,**{k:deepcopy(state[k]) for k in ('hot','pending','native','accepted_fold')},
        'consumed':set(state['consumed'])}
    f.c.persist_sources(branch)
    branch=combined.restart(branch,2)
    e.write(folder/'seed-proof.json',{'source_prefix_sha256_verified':True,'hot_sha256':f.c.digest(branch['hot']),
        'source_records':len(rows),'prior_arm':prior_arm,'prior_fold':2})
    return branch


async def execute(plan):
    assert plan['paid_run_allowed']
    for p,sha in plan['code_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha
    e.ROOT=ROOT;f.ROOT=ROOT;f.c.ROOT=ROOT;combined.ROOT=ROOT
    os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    class DurableCalls(f.StopAwareCalls):
        async def call(self,body,label):
            prior=[x for x in self.report.get('calls',[]) if x['label']==label]
            if prior:
                assert len(prior)==1 and prior[0].get('response') and not prior[0].get('error'),'No resend of ambiguous prior request'
                path=ROOT/(label+'-request.json')
                assert hashlib.sha256(path.read_bytes()).hexdigest()==prior[0]['request_sha256']
                assert e.canonical(f.c.load(path))==e.canonical(body),'Recovery request mismatch'
                self.report.setdefault('offline_response_replays',[]).append(label);self.save()
                return deepcopy(prior[0]['response'])
            return await super().call(body,label)
    calls=DurableCalls();calls.semaphore=asyncio.Semaphore(1)
    if (ROOT/'run-report.json').exists():
        calls.report=f.c.load(ROOT/'run-report.json')
        assert not calls.report.get('completed') and not calls.report.get('stop_reason')
        calls.report.setdefault('protocol_recoveries',[]).append({'reason':'Pure parser replaces legacy import-time finite budget initialization; preserve paid responses.'})
    else:calls.report.update(protocol=plan,folds=[],observations=[],encoding=[])
    gold=f.c.load(e.OLD/'gold.json')
    for case in plan['cases']:
        name=case['case']
        for arm in ARMS:
            if any(x['case']==name and x['arm']==arm for x in calls.report['observations']):continue
            branch=seed(name,arm)
            existing=next((x for x in calls.report['folds'] if x['case']==name and x['arm']==arm),None)
            if existing is not None:
                record=existing
                saved=f.c.load(branch['folder']/'restart-3.json')['state']
                branch.update({k:deepcopy(saved[k]) for k in ('hot','pending','native','accepted_fold')})
                branch.update(consumed=set(saved['consumed']),sources=combined.read_source(saved['source_locator']))
                f.c.persist_sources(branch)
            elif arm=='A1':record=await f.c.fold(Labels(calls,arm),branch,name,arm,2,case['events'][2])
            else:
                transport=Labels(calls,arm)
                scoped=None
                if arm=='D_scoped':scoped=ScopedCalls(transport);transport=scoped
                transport=DeltaCalls(DeclarationCalls(transport),branch['sources']+case['events'][2])
                record=await f.native_fold(transport,branch,name,2,case['events'][2])
                if scoped is not None:calls.report['encoding'].append({'case':name,'audit':scoped.audit})
            record['arm']=arm
            if existing is None:f.add_native_tail(branch,sum(case['events'][:3],[]),record)
            branch=combined.restart(branch,3)
            record['restart_roundtrip']=True;e.write(branch['folder']/'fold-3-result.json',record)
            if existing is None:calls.report['folds'].append(record)
            calls.save()
            observation=await combined.observe(calls,branch,name,arm,2,case['expected'][2],gold[name]['cold_excerpt'])
            combined.restart(branch,3);calls.report['observations'].append(observation);calls.save()
            print(f.c.canonical({'case':name,'arm':arm,'accepted':record['candidate_accepted'],'errors':record['errors'],
                'wrong':[k for k,v in (observation.get('grade') or {}).items() if not v],'cold_exact':observation.get('cold_exact')}),flush=True)
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_SCOPED_EXECUTE')=='1':
        try:asyncio.run(execute(f.c.load(ROOT/'preflight-manifest.json')))
        except f.EvaluationStop as exc:print(f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(f.c.canonical({'prepared':prepare()['arms']}))
