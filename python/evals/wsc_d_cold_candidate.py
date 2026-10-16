"""Common cold-source interface for original A1/D heads; unchanged QA scoring.

Tools availability is a separately registered protocol, not a silent rescore
of no-tools228. Original heads remain byte-identical and generation is excluded.
"""
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
from evals.wsc_elimination_faithful import StopAwareCalls,EvaluationStop
from memory.wsc_cold_source_candidate import ColdSources
from memory.wsc_cold_discovery_candidate import DiscoverableSources
from memory.wsc_cold_locator_candidate import AddressedSources

RUN=os.environ.get('WSC_D_COLD_RUN','wsc-D-cold-candidate-241')
assert RUN in {'wsc-D-cold-candidate-241','wsc-D-cold-discovery-244','wsc-D-cold-isolation-245','wsc-D-cold-locator-246'}
ROOT=e.ROOT.parent/RUN
SOURCE_CLASS=AddressedSources if RUN.endswith('246') else DiscoverableSources if RUN.endswith(('244','245')) else ColdSources
BASE=ROOT.parent/'wsc-reliable-control-228'


def prepare():
    assert not ROOT.exists(),'No experiment overwrite'
    ROOT.mkdir();cases=[]
    for name in e.CASES:
        inputs={arm:json.loads((BASE/name/(arm+'-prepared-request.json')).read_text(encoding='utf-8')) for arm in ['A1','D']}
        source=next((BASE/name).glob('source-*.jsonl'))
        seal=hashlib.sha256(source.read_bytes()).hexdigest()
        for arm,body in inputs.items():
            body=deepcopy(body);body['tools']=e.CLIENT._build_body([],SOURCE_CLASS.schemas(),stream=False)['tools']
            body['tool_choice']='auto'
            if RUN.endswith(('245','246')):
                original_query=body['messages'][-1]['content']
                body['messages'][-1]['content']='输出JSON对象，字段cold_excerpt：'+original_query.split('另外字段cold_excerpt：',1)[1]
            e.write(ROOT/(name+'-'+arm+'-input.json'),body)
        cases.append({'case':name,'source':str(source),'sha256':seal})
    plan={'objective':'Autonomous exact cold recall using same source tools for A1/D, original heads and questions.',
        'cases':cases,'arms':['A1','D'],'samples_per_case_arm':1,'max_calls_per_sample':4,
        'model':'deepseek-flash','thinking':'disabled','temperature':0,'http_retries':0,
        'proposed_new_run_cost_ceiling_cny':0.5,'paid_run_allowed':False,
        'nonclaim':'Single sample per real family, tools protocol differs from228; head generation and new D delta not evaluated here.',
        'candidate_delta':('Cold-only same245 question; SourceRead accepts explicit sealed archive index in addition to source ID. No source hydration or head change.' if RUN.endswith('246') else
            'Cold-excerpt-only question to isolate exact copying/cold capability; combined QA failure retained and not ranked by this unit.' if RUN.endswith('245') else
            'Exact bounded previews in requested directory pages; message ID namespace described; no hot-state/text-question changes.' if RUN.endswith('244') else None),
        'code_sha256':{str(Path(path)):hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in [__file__,'python/memory/wsc_cold_source_candidate.py','python/memory/wsc_cold_discovery_candidate.py','python/memory/wsc_cold_locator_candidate.py']}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


async def execute(plan):
    assert plan['paid_run_allowed'] is True and not (ROOT/'run-report.json').exists()
    for path,seal in plan['code_sha256'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==seal
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct';calls=StopAwareCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=plan,observations=[])
    spec=importlib.util.spec_from_file_location('cold_grading',e.OLD/'evaluate-valid.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    gold=json.loads((e.OLD/'gold.json').read_text(encoding='utf-8'))
    for case in plan['cases']:
        name=case['case'];cold=SOURCE_CLASS(case['source'],case['sha256'])
        rows=[json.loads(s) for s in Path(case['source']).read_text(encoding='utf-8').splitlines()]
        for arm in plan['arms']:
            body=json.loads((ROOT/(name+'-'+arm+'-input.json')).read_text(encoding='utf-8'))
            record={'case':name,'arm':arm,'reads':[],'grade':None};calls.report['observations'].append(record)
            for n in range(4):
                response=await calls.call(body,f'{name}-{arm}-cold-{n}');choice=response['choices'][0];reply=choice['message'];uses=reply.get('tool_calls') or []
                if not uses:
                    parsed,strict=g.parse(reply.get('content') or '')
                    record.update(answer=reply.get('content'),parsed=parsed,strict_json=strict,finish_reason=choice['finish_reason'],grade=g.grade(parsed,gold[name],rows));break
                body['messages'].append(reply)
                for use in uses:
                    try:
                        args=json.loads(use['function']['arguments']);value=cold.call(use['function']['name'],args);error=False
                    except (ValueError,TypeError,KeyError) as exc:value={'error':str(exc)};error=True
                    record['reads'].append({'tool':use['function']['name'],'arguments':use['function']['arguments'],'result':value,'is_error':error})
                    body['messages'].append({'role':'tool','tool_call_id':use['id'],'content':json.dumps(value,ensure_ascii=False,separators=(',',':'))})
                calls.save()
            if record['grade'] is None:record['error']='Four-call sample limit reached; no answer'
            calls.save()
            print(e.canonical({'case':name,'arm':arm,'grade':record['grade'],'reads':len(record['reads']),'error':record.get('error')}),flush=True)
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_COLD_EXECUTE')=='1':
        try:asyncio.run(execute(json.loads((ROOT/'preflight-manifest.json').read_text(encoding='utf-8'))))
        except EvaluationStop as exc:print(e.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:
        p=prepare();print(e.canonical({'cases':len(p['cases']),'arms':p['arms'],'max_calls':16}))
