"""Fixed accepted heads plus already-selected result bodies; paid controls reused.

This screen changes only one factual projection frame. It does not regenerate
handoffs, add semantic instructions, or use gold to choose a result.
"""
from copy import deepcopy
import asyncio
import hashlib
import os
from pathlib import Path

import evals.wsc_d_consumer_mode_diagnostic as consumer
from memory.wsc_verification_result_candidate import materialize

ROOT=consumer.ROOT.parent/'wsc-D-selected-result-screen-263'


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    old_plan=consumer.f.c.load(consumer.ROOT/'preflight-manifest.json')
    old_report=consumer.f.c.load(consumer.ROOT/'run-report.json')
    samples=[]
    for prior in old_plan['samples']:
        if prior['arm']!='D_slot' or prior['mode']!='disabled':continue
        case=prior['case'];parent=consumer.ROOT/(case+'-D_slot-disabled-observer-0-request.json')
        body=consumer.f.c.load(parent);original=deepcopy(body)
        folder=Path(prior['source']).parent
        state=consumer.f.c.load(folder/'restart-3.json')['state']
        source=Path(state['source_locator']['path']);raw=source.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==state['source_locator']['sha256']==prior['source_sha256']
        rows=[consumer.json.loads(s) for s in raw.decode('utf-8').splitlines() if s.strip()]
        packet=materialize(rows,state['native']['checkpoint'])
        body['messages'].insert(-1,{'role':'user','content':consumer.f.c.canonical({'declared_verification_result_observations':packet})})
        without=deepcopy(body);without['messages'].pop(-2);assert without==original
        path=ROOT/(case+'-input.json');consumer.e.write(path,body)
        baseline=next(o for o in old_report['observations'] if all(o[k]==prior[k] for k in ('case','arm','mode')))
        samples.append({**prior,'arm':'D_grounded','input':str(path),'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'parent_request':str(parent),'parent_sha256':hashlib.sha256(parent.read_bytes()).hexdigest(),
            'source':str(source),'source_sha256':state['source_locator']['sha256'],
            'paid_baseline':baseline,'projection_bytes':len(consumer.f.c.canonical(packet).encode()),
            'projection_tokens_estimate':consumer.e.tokens([body['messages'][-2]]),
            'input_tokens_estimate':consumer.e.tokens(body['messages'],[]),
            'one_frame_only':True})
    paths=[__file__,'python/memory/wsc_verification_result_candidate.py',
        'python/evals/wsc_d_consumer_mode_diagnostic.py','python/memory/wsc_cold_locator_candidate.py',
        'python/evals/wsc_ad_experiment.py','python/evals/wsc_elimination_faithful.py']
    plan={'samples':samples,'paid_run_allowed':True,'max_requests_per_sample':3,
        'output_limit':4096,'http_retries':0,'proposed_new_run_cost_ceiling_cny':None,
        'hypothesis':'Literal bounded results for model-selected IDs improve continuity beyond identities alone.',
        'single_change':'One source-bound projection frame; no prompt, mode, schema, question or handoff change.',
        'control_policy':'Reuse255 disabled paid observations unchanged; not a contemporaneous replicated confidence estimate.',
        'nonclaim':'Fixed-head screen, not successful new handoff/10fold/holdout/original228 acceptance; added projection overhead separately reported.',
        'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}}
    consumer.e.write(ROOT/'preflight-manifest.json',plan);return plan


async def execute(plan):
    consumer.ROOT=ROOT
    await consumer.execute(plan)


if __name__=='__main__':
    if os.environ.get('WSC_SELECTED_RESULT_EXECUTE')=='1':
        try:asyncio.run(execute(consumer.f.c.load(ROOT/'preflight-manifest.json')))
        except consumer.f.EvaluationStop as exc:print(consumer.f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(consumer.f.c.canonical({'prepared':len(prepare()['samples']),'api_calls':0}))
