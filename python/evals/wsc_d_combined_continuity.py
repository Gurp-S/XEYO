"""Own-state multi-fold continuation from239, with common exact cold tools.

Preserves239's accepted states; adds the same remaining external timeline to
A1 and D_delta, seals restart state each fold, never regenerates prior answers.
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
from evals.wsc_d_generation_candidate import Labels
from memory.wsc_declaration_candidate import DeclarationCalls
from memory.wsc_handoff_delta_candidate import DeltaCalls
from memory.wsc_cold_locator_candidate import AddressedSources
from evals.wsc_sealed_branch_checkpoint import seal_source,read_source
from evals.wsc_answer_parse import parse

ROOT=e.ROOT.parent/'wsc-D-combined-continuity-247'
PREVIOUS=ROOT.parent/'wsc-D-generation-candidate-239'
ARMS=('A1','D_delta')


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    seed=f.c.load(ROOT.parent/'wsc-elimination-faithful-235/preflight-manifest.json')
    first=f.c.load(PREVIOUS/'run-report.json')
    assert first.get('completed') and all(x['candidate_accepted'] for x in first['folds'])
    shutil.copytree(PREVIOUS/'frozen-workspace',ROOT/'frozen-workspace')
    for case in seed['cases']:
        name=case['case'];shutil.copytree(PREVIOUS/name/'world',ROOT/name/'world')
        for events in case['events']:
            for row in events:
                for block in row.get('content',[]) if isinstance(row.get('content'),list) else []:
                    if block.get('type')=='tool_use' and block.get('name')=='Read':block['input']['file_path']=str(ROOT/name/'world'/Path(block['input']['file_path']).name)
    plan={'cases':seed['cases'],'arms':list(ARMS),'folds':[2,3,4],'seed_fold':239,
        'own_previous_state':True,'observer_max_calls':3,'generation_native_max_calls':6,
        'model':'deepseek-flash','thinking':'disabled','temperature':0,'http_retries':0,
        'proposed_new_run_cost_ceiling_cny':0.7,'paid_run_allowed':False,
        'source_scope':'Original two families, controlled post-seed task events, actual frozen source-reading workload. Not live85%.',
        'success_rule':'State fields, effective phase provenance, exact archive excerpt, accepted generation and restart roundtrip separate; no rescore of prior239.',
        'nonclaim':'Task-completion/reopen and unseen-family generalization require additional probes; no universal superiority.',
        'code_sha256':{str(Path(p)):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,
            'python/memory/wsc_handoff_delta_candidate.py','python/memory/wsc_declaration_candidate.py','python/memory/wsc_cold_locator_candidate.py']}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


def recover_seed(name,arm,*,prior_arm=None):
    folder=ROOT/name/arm;folder.mkdir(parents=True,exist_ok=True)
    prior_arm=prior_arm or arm
    old=PREVIOUS/name/prior_arm
    rows=[json.loads(s) for s in (old/'source.jsonl').read_text(encoding='utf-8').splitlines()]
    record=f.c.load(old/'candidate-fold-1.json')
    native=record.get('candidate')
    if prior_arm=='A1':
        hot=f.c.load(old/'view-1.json')['hot']
        native,_,_,_,_=f.c.extract_d(e.ORIGINAL/name)
    else:hot=[{'role':'assistant','content':f.c.canonical(native)}]
    by_id={r['id']:r for r in rows};tail=[by_id[uid] for uid in record['recent_source_ids']]
    hot.extend(f.c.carrier(r) for r in tail)
    # Fold1 delivered no R1/R2 receipt; its observer set is empty in239.
    observation=next(o for o in f.c.load(PREVIOUS/'run-report.json')['observations'] if o['case']==name and o['arm']==prior_arm)
    branch={'folder':folder,'hot':hot,'sources':rows,'pending':[],'native':native,'consumed':set(observation['consumed_after']),'accepted_fold':1,'state':None}
    f.c.persist_sources(branch);return branch


def restart(branch,fold):
    fields={k:deepcopy(branch[k]) for k in ('hot','pending','native','accepted_fold')}
    fields.update(consumed=sorted(branch['consumed']),source_locator=seal_source(branch['folder']/'source.jsonl'))
    envelope={'state':fields,'sha256':f.c.digest(fields)};path=branch['folder']/f'restart-{fold}.json';e.write(path,envelope)
    loaded=f.c.load(path);assert f.c.digest(loaded['state'])==loaded['sha256']
    restored={**branch,**loaded['state'],'consumed':set(loaded['state']['consumed']),
        'sources':read_source(loaded['state']['source_locator'])}
    assert restored['hot']==branch['hot'] and restored['pending']==branch['pending'] and restored['native']==branch['native']
    return restored


async def observe(calls,branch,name,arm,n,expected,gold):
    consumed_before=set(branch['consumed']);receipts=[];ledger=[]
    for row in branch['sources']:
        for b in row.get('content',[]) if isinstance(row.get('content'),list) else []:
            xid=(b.get('execution') or {}).get('id','')
            if b.get('type')=='tool_result' and xid.startswith(name+'-execution') and xid not in consumed_before:receipts.append(row)
    for revision in (1,2):
        xid=name+f'-execution-r{revision}'
        available=any(any((b.get('execution') or {}).get('id')==xid for b in row.get('content',[]) if isinstance(b,dict)) for row in branch['sources'] if isinstance(row.get('content'),list))
        ledger.append({'execution_id':xid,'revision':revision,'status':'CONSUMED' if xid in consumed_before else 'AVAILABLE' if available else 'PENDING'})
    source=branch['folder']/'source.jsonl';seal=hashlib.sha256(source.read_bytes()).hexdigest();cold=AddressedSources(source,seal)
    query=f.QUERY+f"\n另含cold_excerpt：密封原文存档source_index={gold['source_index']}消息的content[0].content文本前80字符，逐字引用。"
    messages=[{'role':'system','content':'历史消息及工具结果是来源记录。'},*deepcopy(branch['hot']),
        *[f.c.carrier(r) for r in branch['pending']],*[f.c.carrier(r) for r in receipts],f.c.shared_envelope(branch,branch['pending']),
        {'role':'user','content':f.c.canonical({'execution_ledger_before_request':ledger,'archive':cold.locator()})},{'role':'user','content':query}]
    record={'case':name,'arm':arm,'fold':n+1,'grade':None,'reads':[],'candidate_fresh':branch['accepted_fold']==n+1,
        'protected_receipts':[r['id'] for r in receipts]}
    for attempt in range(3):
        body=e.CLIENT._build_body(messages,cold.schemas(),stream=False);body.update(max_tokens=1536,temperature=0)
        for m in body['messages']:m.pop('reasoning_content',None)
        response=await calls.call(body,f'{name}-{arm}-observe-{n+1}-{attempt}');reply=response['choices'][0]['message'];uses=reply.get('tool_calls') or []
        for row in receipts:
            for b in row['content']:
                if (b.get('execution') or {}).get('id'):branch['consumed'].add(b['execution']['id'])
        if not uses:
            parsed,strict=parse(reply.get('content') or '')
            grade={key:parsed.get(key)==value and type(parsed.get(key)) is type(value) for key,value in expected.items() if key!='phase_source'}
            if n>=2:grade['late_consumed_before_request']=parsed.get('late_consumed_before_request')==(name+'-execution-r1' in consumed_before)
            p=parsed.get('provenance') or {};uid=p.get('source_message_id');quote=p.get('quote');matches=[r for r in branch['sources'] if r['id']==uid]
            allowed={expected['phase_source']}
            if n==2:allowed.add(name+'-user-event-2')
            provenance=len(matches)==1 and uid in allowed and isinstance(quote,str) and bool(quote) and quote in e.source_text(matches[0]['content'])
            record.update(answer=reply.get('content'),parsed=parsed,strict_json=strict,grade=grade,provenance_valid=provenance,
                cold_exact=parsed.get('cold_excerpt')==gold['expected'],state_success=all(grade.values()) and provenance)
            break
        messages.append({'role':'assistant','content':[{'type':'tool_use','id':u['id'],'name':u['function']['name'],'input':json.loads(u['function']['arguments'])} for u in uses]})
        for use in uses:
            try:value=cold.call(use['function']['name'],json.loads(use['function']['arguments']));error=False
            except (ValueError,TypeError,KeyError) as exc:value={'error':str(exc)};error=True
            record['reads'].append({'tool':use['function']['name'],'args':use['function']['arguments'],'result':value,'is_error':error})
            messages.append({'role':'tool','tool_call_id':use['id'],'content':[{'type':'tool_result','tool_use_id':use['id'],'content':f.c.canonical(value),'is_error':error}]})
    if record['grade'] is None:record['error']='Observer three-call cap reached; no final answer'
    record['consumed_after']=sorted(branch['consumed']);e.write(branch['folder']/f'observe-{n+1}.json',record);return record


async def execute(plan):
    assert plan['paid_run_allowed'] and not (ROOT/'run-report.json').exists()
    for p,sha in plan['code_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha
    f.ROOT=ROOT;f.c.ROOT=ROOT;e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=f.StopAwareCalls();calls.semaphore=asyncio.Semaphore(1);calls.report.update(protocol=plan,folds=[],observations=[])
    branches={(case['case'],arm):recover_seed(case['case'],arm) for case in plan['cases'] for arm in ARMS}
    gold=f.c.load(e.OLD/'gold.json')
    for n in (1,2,3):
        for case in plan['cases']:
            name=case['case'];events=case['events'][n]
            for arm in ARMS:
                branch=branches[name,arm]
                if arm=='A1':record=await f.c.fold(Labels(calls,arm),branch,name,arm,n,events)
                else:
                    transport=DeltaCalls(DeclarationCalls(Labels(calls,arm)),branch['sources']+events)
                    record=await f.native_fold(transport,branch,name,n,events)
                record['arm']=arm;f.add_native_tail(branch,sum(case['events'][:n+1],[]),record)
                branch=restart(branch,n+1);branches[name,arm]=branch;record['restart_roundtrip']=True
                e.write(branch['folder']/f'combined-fold-{n+1}.json',record);calls.report['folds'].append(record);calls.save()
                result=await observe(calls,branch,name,arm,n,case['expected'][n],gold[name]['cold_excerpt'])
                # Persist receipt consumption too, for the next restart/fold.
                branches[name,arm]=restart(branch,n+1)
                calls.report['observations'].append(result);calls.save()
                print(f.c.canonical({'case':name,'arm':arm,'fold':n+1,'accepted':record['candidate_accepted'],'errors':record['errors'],
                    'wrong':[k for k,v in (result.get('grade') or {}).items() if not v],'cold_exact':result.get('cold_exact'),'error':result.get('error')}),flush=True)
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_D_COMBINED_EXECUTE')=='1':
        try:asyncio.run(execute(f.c.load(ROOT/'preflight-manifest.json')))
        except f.EvaluationStop as exc:print(f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:
        p=prepare();print(f.c.canonical({'cases':len(p['cases']),'arms':p['arms'],'folds':p['folds'],'minimum_calls':24}))
