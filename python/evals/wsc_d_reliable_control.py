"""Predeclared matched D/A1/D1/D2 continuation control, separate from recovery.

No semantic regeneration, no privileged hydration, no production imports.
Identical wire bodies share one observation; network failures are not retried.
"""
import asyncio
from collections import defaultdict
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random

import evals.wsc_ad_experiment as e
from evals.wsc_ad_candidate import canonical, evidence, read_state, digest, commit_candidate, initial, persist_state
from evals.wsc_d_handoff_shell_control import extract_d, candidate_from_d

RUN='wsc-reliable-control-228'
ROOT=e.ROOT.parent/RUN
LABELS=('D','A1','D1','D2')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def measure_hot(messages):
    return e.tokens(messages)


def compact_index(native,rows,decl):
    by_id={r['id']:r for r in rows+decl};line={r['id']:i+1 for i,r in enumerate(rows)}
    groups=defaultdict(list);cp=native['checkpoint']
    for uid in cp['context_message_ids']:groups[uid].append('context')
    for field in ('constraints','decisions'):
        for i,item in enumerate(cp[field]):groups[item['source_message_id']].append(field+'['+str(i)+']')
    receipt=next(r['id'] for r in decl if r['role']=='tool');groups[receipt].append('handoff')
    for hint_limit in (60,30,0):
        entries=[]
        for uid,subjects in groups.items():
            row=by_id[uid]
            loc={'archive':'source','line':line[uid]} if uid in line else {'archive':'declaration','event_id':uid}
            entries.append({'event_id':uid,'subjects':subjects,'locator':loc,'hint':e.source_text(row['content'])[:hint_limit]})
        size=e.tokens([{'role':'assistant','content':canonical(entries)}])
        if size<=2048:return entries,{'index_budget':2048,'index_tokens':size,'hint_characters':hint_limit}
    raise ValueError('required_index_locators_exceed_budget')


def prepare():
    ROOT.mkdir(exist_ok=True)
    manifest={'protocol_version':1,'source_cases':[],'samples_per_unique_request':3,'arms':list(LABELS),
        'primary':'Semantic QA over two fixed real-source cases, original questions. No model retrieval tools for any arm.',
        'scoring':'Original grades retained. Published batch2 ambiguity excluded from primary; authorization unknown separately classified, never rescored.',
        'nonclaims':['Not a native Codex-model comparison','Not autonomous cold retrieval','Not multi-fold task success or full V3/V3.1 implementation'],
        'same_query_system_tail_parameters':True,'special_hydration':False,'request_aliases':[],'requests':[]}
    for name in e.CASES:
        folder=ROOT/name;folder.mkdir(exist_ok=True)
        raw=(e.ORIGINAL/name/'source.jsonl').read_bytes()
        assert raw==(e.OLD/name/'source.jsonl').read_bytes()
        source=folder/('source-'+hashlib.sha256(raw).hexdigest()+'.jsonl');e.exact_archive(source,raw)
        native,decl,_,receipt,_=extract_d(e.ORIGINAL/name)
        decl_raw=(e.ORIGINAL/name/'declaration.json').read_bytes()
        declaration=folder/('declaration-'+hashlib.sha256(decl_raw).hexdigest()+'.json');e.exact_archive(declaration,decl_raw)
        original=load(e.ORIGINAL/name/'D-runtime-messages.json')[1]['content']
        decoded,end=json.JSONDecoder().raw_decode(original);assert decoded==native
        native_text=original[:end]
        rows=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
        store=evidence(rows+decl);state=read_state(e.ROOT.parent/'wsc-D-shell-224'/name/'D2-state.json')
        for fact in state['facts']:
            for ref in fact['evidence_refs']:assert store[ref['event_id']]['hash']==ref['content_hash']
        verified={}
        for mode in ('AD1','AD2'):
            candidate=candidate_from_d(name,native,store,receipt['id'])
            if mode=='AD1':candidate['changes']=[{'action':'add','fact':fact} for fact in candidate.pop('facts')]
            committed,errors,accepted=commit_candidate(initial(name),candidate,store,mode,reference_policy='event')
            assert accepted and not errors
            persist_state(folder/(mode+'-committed-cold-state.json'),committed)
            assert read_state(folder/(mode+'-committed-cold-state.json'))==committed
            verified[mode]=committed
        assert verified['AD1']==verified['AD2']==state
        # Native fields not modeled by StateFact remain bound cold metadata.
        native_refs=set(native['checkpoint']['context_message_ids'])
        native_refs.update(native['checkpoint']['phase_state']['active_context_message_ids'])
        assert native_refs<=set(store)
        e.write(folder/'committed-native-checkpoint.json',{'native':native,'sha256':digest(native),
            'context_source_hashes':{uid:store[uid]['hash'] for uid in sorted(native_refs)}})
        # Guard IR is cold. Native checkpoint preserves every field and ID.
        assert load(e.ROOT.parent/'wsc-D-shell-224'/name/'D-native-semantic.json')==native
        index,index_info=compact_index(native,rows,decl)
        anchors=[];raw_size=0
        for row in reversed(rows):
            if row['role']!='user':continue
            size=e.tokens([row])
            if raw_size+size>8000:break
            anchors.append(row);raw_size+=size
        anchors.reverse()
        template=load(e.OLD/name/'template.json');cut=template['cut'];tail,carriers=e.preserve_tail(rows[cut:])
        old_a1=load(e.OLD/name/'A1-runtime-messages.json')
        a1=old_a1[1:len(old_a1)-len(rows[cut:])-2]
        assert a1 and all(isinstance(m['content'],str) for m in a1)
        heads={'D':[{'role':'assistant','content':native_text}], 'D2':[{'role':'assistant','content':native_text}],
            'D1':[{'role':'assistant','content':native_text+'\n'+canonical({'protected_raw_anchors':anchors,'evidence_map':index})}],
            'A1':a1}
        common={'role':'user','content':canonical({'archives':{'source':{'path':str(source),'sha256':hashlib.sha256(raw).hexdigest(),'records':len(rows)},
            'declaration':{'path':str(declaration),'sha256':hashlib.sha256(decl_raw).hexdigest()}},'progress_basis':'declared'})}
        bodies={}
        for label,hot in heads.items():
            messages=[template['system'],*hot,*tail,common,template['query']]
            body=e.CLIENT._build_body(messages,[],stream=False);body.update(max_tokens=1536,temperature=0)
            for m in body['messages']:m.pop('reasoning_content',None)
            assert body['messages'][0]==template['system'] and body['messages'][-1]==template['query']
            bodies[label]=body;e.write(folder/(label+'-prepared-request.json'),body)
        assert canonical(bodies['D'])==canonical(bodies['D2'])
        manifest['request_aliases'].append({'case':name,'labels':['D','D2'],'reason':'Exact request byte equality. One observation, not two independent samples.'})
        case={'case':name,'source_sha256':hashlib.sha256(raw).hexdigest(),'native_checkpoint_sha256':digest(native),'all_native_fields_preserved':True,
            'A1_native_hot_retained':True,'index':index_info,'anchor_token_budget_sum':raw_size,'historical_result_carriers':carriers,'arms':{}}
        for label,body in bodies.items():
            count=e.CLIENT.context_token_measure(e.from_body(body))[0]
            upper=min(((len(canonical(body).encode())+8192)*2+1536*8)/1e6,(1048576*2+1536*8)/1e6)
            case['arms'][label]={'hot_tokens':measure_hot(heads[label]),'request_token_estimate':count,'request_sha256':digest(body),
                'admission_upper_cny':upper,'prepared_request':str(folder/(label+'-prepared-request.json'))}
        manifest['source_cases'].append(case)
    manifest['ordered_plan']=[{'sample':s,'case':name,'label':label} for s in range(3) for name in e.CASES for label in ('D','A1','D1')]
    random.Random(228).shuffle(manifest['ordered_plan'])
    manifest['calls']=len(manifest['ordered_plan'])
    manifest['total_no_hit_peak_estimate']=sum(case['arms'][label]['request_token_estimate']*2/1e6+1536*8/1e6 for case in manifest['source_cases'] for label in ('D','A1','D1'))*3
    manifest['sum_admission_upper']=sum(case['arms'][label]['admission_upper_cny'] for case in manifest['source_cases'] for label in ('D','A1','D1'))*3
    e.write(ROOT/'preflight-manifest.json',manifest)
    return manifest


async def execute(manifest):
    assert not (ROOT/'run-report.json').exists(),'No paid rerun'
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct';calls=e.Calls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=manifest,scope='Predeclared semantic-only matched control. Failures retained; no HTTP retries.')
    spec=importlib.util.spec_from_file_location('grading228',e.OLD/'evaluate-valid.py');grader=importlib.util.module_from_spec(spec);spec.loader.exec_module(grader)
    gold=load(e.OLD/'gold.json')
    for item in manifest['ordered_plan']:
        case,label,sample=item['case'],item['label'],item['sample'];name=f'{case}-{label}-sample-{sample}'
        body=load(ROOT/case/(label+'-prepared-request.json'))
        assert digest(body)==next(c for c in manifest['source_cases'] if c['case']==case)['arms'][label]['request_sha256']
        result={**item,'grade':None,'alias_labels':['D','D2'] if label=='D' else [label]};calls.report['arms'].append(result)
        try:
            response=await calls.call(body,name);choice=response['choices'][0];answer=choice['message'].get('content') or ''
            parsed,strict=grader.parse(answer);rows=[json.loads(x) for x in (e.OLD/case/'source.jsonl').read_text(encoding='utf-8').splitlines()]
            result.update(answer=answer,parsed=parsed,strict_json=strict,finish_reason=choice['finish_reason'],grade=grader.grade(parsed,gold[case],rows))
        except Exception as exc:
            result['error']=type(exc).__name__+': '+str(exc)[:180];calls.report['errors'].append({**item,'error':result['error']})
            if 'evaluation_budget_exceeded' in str(exc):calls.save();break
        calls.save();print(canonical({'case':case,'label':label,'sample':sample,'grade':result.get('grade'),'error':result.get('error')}),flush=True)
    print(canonical({'calls':len(calls.report['calls']),'usage':sum(bool(c.get('usage_observed')) for c in calls.report['calls'])}),flush=True)


if __name__=='__main__':
    if os.environ.get('WSC_RELIABLE_EXECUTE')=='1':asyncio.run(execute(load(ROOT/'preflight-manifest.json')))
    else:
        manifest=prepare()
        print(canonical({'cases':manifest['source_cases'],'calls':manifest['calls'],'no_hit_peak_estimate':manifest['total_no_hit_peak_estimate'],'sum_admission_upper':manifest['sum_admission_upper']}))
