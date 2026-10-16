"""Matched consumer-mode diagnostic on fixed accepted A1/D heads, no refolding."""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
from evals.wsc_answer_parse import parse
from memory.wsc_cold_locator_candidate import AddressedSources

ROOT=e.ROOT.parent/'wsc-D-consumer-mode-255'
PREVIOUS=ROOT.parent/'wsc-D-fact-reference-254'
ARMS=('A1','D_slot')
MODES=('disabled','enabled')
SNAPSHOT='late_consumed_before_request 对应本题开始时的账本快照，不对应召回过程中的后续模型调用。'


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    parent=f.c.load(PREVIOUS/'preflight-manifest.json');samples=[]
    for case in parent['cases']:
        name=case['case']
        for arm in ARMS:
            original=f.c.load(PREVIOUS/(name+'-'+arm+'-observe-3-0-request.json'))
            folder=PREVIOUS/name/arm;source=folder/'source.jsonl'
            seal=hashlib.sha256(source.read_bytes()).hexdigest()
            expected=deepcopy(case['expected'][2]);expected.pop('phase_source')
            obs=f.c.load(folder/'observe-3.json')
            # The fixed query snapshot was actually presented in the old first
            # observer request. It is not recomputed after the source fork.
            ledger=next(json.loads(m['content'])['execution_ledger_before_request']
                for m in original['messages'] if isinstance(m.get('content'),str) and m['content'].startswith('{"archive":'))
            expected['late_consumed_before_request']=next(x['status']=='CONSUMED' for x in ledger if x['execution_id']==name+'-execution-r1')
            for mode in MODES:
                body=deepcopy(original);body.update(max_tokens=4096,thinking={'type':mode},tool_choice='auto')
                body.pop('reasoning_effort',None)
                body['messages'][-1]['content']+='\n'+SNAPSHOT
                for m in body['messages']:
                    if m['role']=='assistant':m.setdefault('reasoning_content','')
                path=ROOT/(name+'-'+arm+'-'+mode+'-input.json');e.write(path,body)
                samples.append({'case':name,'arm':arm,'mode':mode,'input':str(path),
                    'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'source':str(source),'source_sha256':seal,'expected':expected,
                    'phase_sources':[name+'-user-event-3',name+'-user-event-2'],
                    'comparison_parent':str(PREVIOUS/(name+'-'+arm+'-observe-3-0-request.json'))})
    plan={'samples':samples,'model':'deepseek-flash','modes':list(MODES),'max_requests_per_sample':3,
        'output_limit':4096,'http_retries':0,'paid_run_allowed':False,'proposed_new_run_cost_ceiling_cny':None,
        'hypothesis':'Fixed compressed heads with mode-only change distinguish recovery/judgment capability from compaction generation.',
        'common_protocol_changes':'4096 output and explicit initial-question ledger snapshot for both modes; old1536/snapshot-ambiguous grades not directly compared.',
        'official_protocol':'https://api-docs.deepseek.com/guides/thinking_mode/',
        'reasoning_replay':'Full returned assistant reasoning_content preserved on all tool continuations; no required tool choice in thinking mode.',
        'nonclaim':'No handoff generation, no production/model default change, no whole-goal acceptance.',
        'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,
            'python/evals/wsc_ad_experiment.py','python/evals/wsc_elimination_faithful.py','python/evals/wsc_answer_parse.py',
            'python/memory/wsc_cold_locator_candidate.py']}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


async def execute(plan):
    assert plan['paid_run_allowed'] and not (ROOT/'run-report.json').exists()
    for p,sha in plan['code_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=f.StopAwareCalls();calls.semaphore=asyncio.Semaphore(2)
    calls.report.update(protocol=plan,observations=[])
    gold=f.c.load(e.OLD/'gold.json')
    async def one(sample):
        name=sample['case'];path=Path(sample['input'])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==sample['input_sha256']
        body=f.c.load(path);cold=AddressedSources(sample['source'],sample['source_sha256'])
        rows=[json.loads(s) for s in Path(sample['source']).read_text(encoding='utf-8').splitlines()]
        record={**sample,'grade':None,'reads':[],'state_success':False,'cold_exact':False}
        try:
            for n in range(plan['max_requests_per_sample']):
                answer=await calls.call(body,f"{name}-{sample['arm']}-{sample['mode']}-observer-{n}")
                choice=answer['choices'][0];reply=choice['message'];uses=reply.get('tool_calls') or []
                if not uses:
                    parsed,strict=parse(reply.get('content') or '')
                    if not isinstance(parsed,dict):parsed={}
                    grade={key:type(parsed.get(key)) is type(value) and parsed.get(key)==value for key,value in sample['expected'].items()}
                    p=parsed.get('provenance') or {};uid=p.get('source_message_id');quote=p.get('quote')
                    found=[r for r in rows if r['id']==uid]
                    provenance=len(found)==1 and uid in sample['phase_sources'] and isinstance(quote,str) and bool(quote) and quote in e.source_text(found[0]['content'])
                    record.update(parsed=parsed,strict_json=strict,grade=grade,provenance_valid=provenance,
                        state_success=all(grade.values()) and provenance,
                        cold_exact=parsed.get('cold_excerpt')==gold[name]['cold_excerpt']['expected'],finish_reason=choice['finish_reason'])
                    if choice['finish_reason']=='length':record['error']='Output truncated; not retried'
                    break
                # Keep the provider's exact thought and tool-call fields, not
                # reconstructed messages that lose reasoning_content.
                body['messages'].append(deepcopy(reply))
                for use in uses:
                    try:value=cold.call(use['function']['name'],json.loads(use['function']['arguments']));error=False
                    except (ValueError,KeyError,TypeError) as exc:value={'error':str(exc)};error=True
                    record['reads'].append({'tool':use['function']['name'],'args':use['function']['arguments'],'is_error':error})
                    body['messages'].append({'role':'tool','tool_call_id':use['id'],'content':f.c.canonical(value)})
            if record['grade'] is None:record['error']='Three-request cap; no final answer'
        finally:
            calls.report['observations'].append(record);calls.save()
        print(f.c.canonical({'case':name,'arm':sample['arm'],'mode':sample['mode'],
            'state_success':record['state_success'],'cold_exact':record['cold_exact'],'reads':len(record['reads']),
            'wrong':[k for k,v in (record.get('grade') or {}).items() if not v],'error':record.get('error')}),flush=True)
    results=await asyncio.gather(*(one(s) for s in plan['samples']),return_exceptions=True)
    for result in results:
        if isinstance(result,BaseException):raise result
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_CONSUMER_EXECUTE')=='1':
        try:asyncio.run(execute(f.c.load(ROOT/'preflight-manifest.json')))
        except f.EvaluationStop as exc:print(f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(f.c.canonical({'prepared':len(prepare()['samples'])}))
