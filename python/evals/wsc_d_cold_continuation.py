"""Separate two-turn extension after cold241's common four-call ceiling.

Preserves capped failures; resumes exact last tool transcript, no HTTP retries.
No regenerated answers, altered queries, or gold-driven source presentation.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
from evals.wsc_elimination_faithful import StopAwareCalls,EvaluationStop
from memory.wsc_cold_source_candidate import ColdSources

ROOT=e.ROOT.parent/'wsc-D-cold-continuation-242'
OLD=ROOT.parent/'wsc-D-cold-candidate-241'


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    report=json.loads((OLD/'run-report.json').read_text(encoding='utf-8'));samples=[]
    for obs in report['observations']:
        if obs['grade'] is not None:continue
        name,arm=obs['case'],obs['arm'];label=f'{name}-{arm}-cold-3'
        call=next(c for c in report['calls'] if c['label']==label)
        body=json.loads((OLD/(label+'-request.json')).read_text(encoding='utf-8'))
        reply=call['response']['choices'][0]['message'];uses=reply['tool_calls']
        receipts=obs['reads'][-len(uses):]
        assert len(receipts)==len(uses)
        body['messages'].append(reply)
        for use,receipt in zip(uses,receipts):
            assert use['function']['name']==receipt['tool'] and use['function']['arguments']==receipt['arguments']
            body['messages'].append({'role':'tool','tool_call_id':use['id'],'content':json.dumps(receipt['result'],ensure_ascii=False,separators=(',',':'))})
        path=ROOT/(name+'-'+arm+'-prepared.json');e.write(path,body)
        case=next(c for c in report['protocol']['cases'] if c['case']==name)
        samples.append({'case':name,'arm':arm,'input':str(path),'source':case['source'],'sha256':case['sha256']})
    plan={'samples':samples,'maximum_additional_calls':2,'previous_calls_per_sample':4,
          'preserve_original_capped_results':True,'query_and_head_unchanged':True,'http_retries':0,
          'proposed_new_run_cost_ceiling_cny':0.3,'paid_run_allowed':False}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


async def execute(plan):
    assert plan['paid_run_allowed'] and not (ROOT/'run-report.json').exists()
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct';calls=StopAwareCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=plan,observations=[])
    spec=importlib.util.spec_from_file_location('cold_extension_grade',e.OLD/'evaluate-valid.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    gold=json.loads((e.OLD/'gold.json').read_text(encoding='utf-8'))
    for sample in plan['samples']:
        body=json.loads(Path(sample['input']).read_text(encoding='utf-8'));cold=ColdSources(sample['source'],sample['sha256'])
        rows=[json.loads(s) for s in Path(sample['source']).read_text(encoding='utf-8').splitlines()]
        record={**sample,'grade':None,'reads':[]};calls.report['observations'].append(record)
        for n in range(2):
            result=await calls.call(body,f"{sample['case']}-{sample['arm']}-extension-{n}")
            choice=result['choices'][0];reply=choice['message'];uses=reply.get('tool_calls') or []
            if not uses:
                parsed,strict=g.parse(reply.get('content') or '')
                record.update(answer=reply.get('content'),parsed=parsed,strict_json=strict,grade=g.grade(parsed,gold[sample['case']],rows));break
            body['messages'].append(reply)
            for use in uses:
                try:value=cold.call(use['function']['name'],json.loads(use['function']['arguments']));error=False
                except (ValueError,TypeError,KeyError) as exc:value={'error':str(exc)};error=True
                record['reads'].append({'tool':use['function']['name'],'arguments':use['function']['arguments'],'result':value,'is_error':error})
                body['messages'].append({'role':'tool','tool_call_id':use['id'],'content':json.dumps(value,ensure_ascii=False,separators=(',',':'))})
            calls.save()
        if record['grade'] is None:record['error']='Six total calls reached; no answer'
        e.write(ROOT/(sample['case']+'-'+sample['arm']+'-pending.json'),body)
        calls.save();print(e.canonical({'case':sample['case'],'arm':sample['arm'],'grade':record['grade'],'error':record.get('error')}),flush=True)
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_COLD_EXTENSION_EXECUTE')=='1':
        try:asyncio.run(execute(json.loads((ROOT/'preflight-manifest.json').read_text(encoding='utf-8'))))
        except EvaluationStop as exc:print(e.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:
        p=prepare();print(e.canonical({'samples':len(p['samples']),'maximum_added_calls':6}))
