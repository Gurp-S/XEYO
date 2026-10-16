"""Small same-source native D vs declaration-channel candidate, A1 baseline.

Independent experiment after the user changed the objective; never resumes235.
No prompt edits, oracle-filled checkpoints, HTTP retries, or production writes.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
from memory.wsc_declaration_candidate import DeclarationCalls
from memory.wsc_handoff_delta_candidate import DeltaCalls

RUN=os.environ.get('WSC_D_GENERATION_RUN','wsc-D-generation-candidate-237')
assert RUN in {'wsc-D-generation-candidate-237','wsc-D-generation-candidate-239'}
ROOT=e.ROOT.parent/RUN
SEED=ROOT.parent/'wsc-elimination-faithful-235'
ARMS=('A1','D_declaration','D_delta') if RUN.endswith('239') else ('A1','D','D_candidate')


class Labels:
    def __init__(self,calls,arm):self.calls,self.arm=calls,arm
    async def call(self,body,label):return await self.calls.call(body,label+'-'+self.arm)


def prepare():
    assert not ROOT.exists(),'No experiment overwrite'
    ROOT.mkdir();base=f.c.load(SEED/'preflight-manifest.json')
    shutil.copytree(SEED/'frozen-workspace',ROOT/'frozen-workspace')
    cases=[]
    for case in base['cases']:
        name=case['case'];world=ROOT/name/'world'
        shutil.copytree(SEED/name/'world',world)
        events=deepcopy(case['events'][0])
        for row in events:
            for block in row.get('content',[]) if isinstance(row.get('content'),list) else []:
                if block.get('type')=='tool_use' and block.get('name')=='Read':
                    block['input']['file_path']=str(world/Path(block['input']['file_path']).name)
        cases.append({'case':name,'events':events,'expected':case['expected'][0]})
    plan={'objective':'Optimize D with A1 baseline; protocol-output candidate only.',
        'cases':cases,'arms':list(ARMS),'folds':1,'model':'deepseek-flash','thinking':'disabled','temperature':0,
        'D_generation':'Actual native generator, existing six-request/source-read/feedback limits.',
        'candidate_delta':('Both D arms require tool output. D_delta additionally presents exact text events after committed checkpoint; no semantic inference or answers.'
                           if RUN.endswith('239') else 'Only tool_choice auto -> required in isolated D generation; no tool/schema/prompt changes.'),
        'source_scope':'Same two real seeds plus first controlled extension and frozen-source readings from235.',
        'A1_method':'Same pinned Codex summary prompt and original user-retention policy; freshly generated, not reused scoring.',
        'http_retries':0,'observer_calls':2,'proposed_new_run_cost_ceiling_cny':1,
        'minimum_calls':12,'maximum_calls':40,'paid_run_allowed':False,
        'nonclaim':'Two source families and one fold cannot prove multigeneration quality or autonomous cold recall.',
        'code_sha256':{str(Path(path)):hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in [__file__,
            'python/memory/wsc_declaration_candidate.py','python/memory/wsc_handoff_delta_candidate.py','python/evals/wsc_elimination_faithful.py']}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


async def execute(plan):
    assert plan['paid_run_allowed'] is True
    assert not (ROOT/'run-report.json').exists(),'No paid rerun'
    for path,seal in plan['code_sha256'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==seal
    f.ROOT=ROOT;f.c.ROOT=ROOT;f.c.QUERY=f.QUERY;f.c.FileReadTool=lambda **kwargs:f.FrozenRead(cwd=str(f.REPO))
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=f.StopAwareCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=plan,folds=[],observations=[])
    for case in plan['cases']:
        name=case['case']
        for arm in ARMS:
            branch=f.c.start_branch(name,'A1' if arm=='A1' else arm)
            rows=[json.loads(s) for s in (e.ORIGINAL/name/'source.jsonl').read_text(encoding='utf-8').splitlines()]
            seed_cut=f.c.load(e.OLD/name/'template.json')['cut']
            branch['hot'].extend(f.c.carrier(r) for r in rows[seed_cut:])
            if arm=='A1':record=await f.c.fold(Labels(calls,arm),branch,name,'A1',0,case['events'])
            else:
                transport=Labels(calls,arm)
                if arm in {'D_candidate','D_declaration','D_delta'}:transport=DeclarationCalls(transport)
                if arm=='D_delta':transport=DeltaCalls(transport,branch['sources']+case['events'])
                record=await f.native_fold(transport,branch,name,0,case['events'])
            record['arm']=arm
            f.add_native_tail(branch,case['events'],record)
            e.write(branch['folder']/'candidate-fold-1.json',record)
            calls.report['folds'].append(record);calls.save()
            observation=await f.c.observe(calls,branch,name,arm,0,case['expected'])
            calls.report['observations'].append(observation);calls.save()
            print(f.c.canonical({'case':name,'arm':arm,'accepted':record['candidate_accepted'],
                'errors':record['errors'],'wrong_fields':[k for k,v in (observation.get('grade') or {}).items() if not v],
                'observation_error':observation.get('error')}),flush=True)
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_CANDIDATE_EXECUTE')=='1':
        try:asyncio.run(execute(f.c.load(ROOT/'preflight-manifest.json')))
        except f.EvaluationStop as exc:print(f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:
        p=prepare();print(f.c.canonical({'cases':len(p['cases']),'arms':p['arms'],'minimum_calls':p['minimum_calls']}))
