"""D-native handoff reused under V3/V3.1 shells. No semantic generation call.

Only explicit native declarations are mapped. Goal lifecycle stays UNKNOWN
because TodoWrite's objective has no goal lifecycle field. Reported progress is
not an assertion that executions passed or that pending steps are authorized.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
from evals.wsc_ad_candidate import (canonical, commit_candidate, digest, evidence,
    initial, persist_state, read_state)
from evals.wsc_ad_matched_continuation import evaluate


def extract_d(folder):
    original=json.loads((folder/'D-runtime-messages.json').read_text(encoding='utf-8'))[1]['content']
    semantic, _=json.JSONDecoder().raw_decode(original)
    declaration=json.loads((folder/'declaration.json').read_text(encoding='utf-8'))
    calls=[(row,b) for row in declaration for b in row.get('content',[])
        if isinstance(b,dict) and b.get('type')=='tool_use' and b.get('name')=='TodoWrite']
    assert len(calls)==1
    invocation,call=calls[0]
    receipts=[row for row in declaration if any(isinstance(b,dict) and b.get('type')=='tool_result'
        and b.get('tool_use_id')==call['id'] and not b.get('is_error') for b in row.get('content',[]))]
    assert len(receipts)==1,'D handoff receipt identity missing'
    assert semantic['checkpoint']==call['input']['checkpoint']
    return semantic,declaration,invocation,receipts[0],call['id']


def candidate_from_d(name,semantic,store,receipt_id):
    cp=semantic['checkpoint'];phase=cp.get('phase_state') or {};facts=[]
    def refs(ids):
        return [{'event_id':uid,'content_hash':store[uid]['hash'],'sequence':store[uid]['sequence']} for uid in ids]
    def add(uid,kind,content,status,scope,ids):
        facts.append({'fact_id':uid,'kind':kind,'content':content,'status':status,'scope':scope,'evidence_refs':refs(ids)})
    add('d:objective','request',cp['objective'],'UNKNOWN',{'kind':'TASK'},[receipt_id])
    for field,kind in [('constraints','constraint'),('decisions','decision')]:
        native_scopes=phase.get('fact_scopes',{}).get(field,[])
        if native_scopes:assert len(native_scopes)==len(cp[field])
        for i,native in enumerate(cp[field]):
            tag=native_scopes[i] if native_scopes else {'kind':'task'}
            scope={'kind':tag['kind'].upper()}
            if scope['kind']!='TASK':scope['id']=tag.get('phase_id') or phase['current_phase_id']
            uid='d:'+field+':'+digest(native)[:16]
            add(uid,kind,native['quote'],'ACTIVE',scope,[native['source_message_id']])
    add('d:phase','progress',canonical({'declared_phase_state':phase}),'UNKNOWN',{'kind':'TASK'},[receipt_id])
    for native in semantic['todos']:
        # Preserve the full status, active form and output exactly once.
        status='RESOLVED' if native['status']=='completed' else 'ACTIVE'
        add('d:todo:'+native['id'],'progress',canonical({'progress_basis':'declared','todo':native}),status,{'kind':'TASK'},[receipt_id])
    add('d:verification','progress',canonical({'declared_verification_call_ids':cp.get('verification_call_ids',[]),
        'verification_basis':'source-bound declarations, not all-passed'}),'UNKNOWN',{'kind':'TASK'},[receipt_id])
    return {'baseline':0,'goal_id':name,'source_cursor':len(store)-1,'facts':facts}


def exact_execution_bindings(rows,ids):
    result=[]
    for uid in ids:
        calls=[];receipts=[]
        for row in rows:
            for b in row.get('content',[]) if isinstance(row.get('content'),list) else []:
                if b.get('type')=='tool_use' and b.get('id')==uid:calls.append(row['id'])
                if b.get('type')=='tool_result' and b.get('tool_use_id')==uid:
                    receipts.append({'event_id':row['id'],'is_error':bool(b.get('is_error')),'execution':b.get('execution')})
        if len(calls)!=1 or not receipts:raise ValueError('D verification execution identity ambiguous: '+uid)
        result.append({'call_id':uid,'invocation_event':calls[0],'result_events':receipts})
    return result


def prepare(root):
    report=[]
    for name in e.CASES:
        original=e.ORIGINAL/name;folder=root/name;folder.mkdir(exist_ok=True)
        raw=(original/'source.jsonl').read_bytes();source=folder/('source-'+hashlib.sha256(raw).hexdigest()+'.jsonl')
        e.exact_archive(source,raw)
        semantic,decl,inv,receipt,call_id=extract_d(original)
        decl_bytes=(original/'declaration.json').read_bytes();decl_path=folder/('declaration-'+hashlib.sha256(decl_bytes).hexdigest()+'.json')
        e.exact_archive(decl_path,decl_bytes)
        rows=[json.loads(x) for x in raw.decode('utf-8').splitlines()];store=evidence(rows+decl)
        candidate=candidate_from_d(name,semantic,store,receipt['id'])
        bindings=exact_execution_bindings(rows,semantic['checkpoint'].get('verification_call_ids',[]))
        e.write(folder/'D-native-semantic.json',semantic);e.write(folder/'IR-candidate.json',candidate);e.write(folder/'execution-bindings.json',bindings)
        item={'case':name,'handoff_call_id':call_id,'handoff_receipt_id':receipt['id'],
            'semantic_sha256':digest(semantic),'source_sha256':hashlib.sha256(raw).hexdigest(),'declaration_sha256':hashlib.sha256(decl_bytes).hexdigest(),
            'facts':len(candidate['facts']),'verification_bindings':len(bindings),'generation_api_calls':0,'variants':{}}
        for label,mode in [('D1','AD1'),('D2','AD2')]:
            c=deepcopy(candidate)
            if mode=='AD1':c['changes']=[{'action':'add','fact':f} for f in c.pop('facts')]
            state,errors,accepted=commit_candidate(initial(name),c,store,mode,reference_policy='event')
            assert accepted and not errors,(name,label,errors)
            persist_state(folder/f'{label}-state.json',state);assert read_state(folder/f'{label}-state.json')==state
            # Provenance stays durable; hashes are execution checks, not hot prose.
            visible=deepcopy(state)
            for f in visible['facts']:
                f['evidence_refs']=[{'event_id':r['event_id']} for r in f['evidence_refs']]
            head=json.loads(e.render(visible,rows+decl,mode,source))
            head['progress_basis']='declared';head['handoff_receipt']=receipt['id'];head['declaration_archive']=str(decl_path)
            # Source locators for declaration events refer to the actual separate
            # JSON evidence object, not invented lines beyond source.jsonl.
            for entry in head.get('evidence_map',[]):
                for ref in entry['locators']:
                    if ref['event_id'] in {r['id'] for r in decl}:
                        ref.pop('line',None);ref['path']=str(decl_path)
                    else:ref['path']=str(source)
            text=canonical(head);(folder/f'{label}-head.txt').write_text(text,encoding='utf-8')
            item['variants'][label]={'hot_tokens':e.tokens([{'role':'assistant','content':text}]),
                'state_sha256':digest(state),'state_round_trip':True,'all_D_constraints_retained':len([f for f in state['facts'] if f['kind']=='constraint'])==len(semantic['checkpoint']['constraints'])}
        assert item['variants']['D1']['state_sha256']==item['variants']['D2']['state_sha256']
        report.append(item)
    e.write(root/'prepare-report.json',report);return report


def prepare_native_projection(root):
    """Keep D's semantic bytes; evidence hashes stay in the cold guard state.

    Archive addresses occur once. V3.1's small index uses archive IDs, not a
    repeated full path for each fact. This is a renderer ablation only.
    """
    previous=root.parent/'wsc-D-shell-224';report=[]
    for name in e.CASES:
        folder=root/name;folder.mkdir(exist_ok=True)
        old=json.loads((e.ORIGINAL/name/'D-runtime-messages.json').read_text(encoding='utf-8'))[1]['content']
        semantic,end=json.JSONDecoder().raw_decode(old);prefix=old[:end]
        source=next((previous/name).glob('source-*.jsonl'));decl=next((previous/name).glob('declaration-*.json'))
        rows=[json.loads(x) for x in source.read_text(encoding='utf-8').splitlines()]
        declaration=json.loads(decl.read_text(encoding='utf-8'));combined=rows+declaration
        state=read_state(previous/name/'D2-state.json')
        archives={'source':str(source),'declaration':str(decl)}
        receipt=next(r['id'] for r in declaration if r['role']=='tool')
        common=prefix+'\n'+canonical({'archives':archives,'handoff_receipt':receipt,'progress_basis':'declared'})
        item={'case':name,'native_semantic_sha256':digest(semantic),'same_committed_state_sha256':digest(state),'variants':{}}
        for label in ['D1','D2']:
            text=common
            if label=='D1':
                raw=json.loads(e.render(state,combined,'AD1',source))['protected_raw_anchors']
                locators={}
                for i,row in enumerate(combined):
                    locators[row['id']]={'archive':'source','line':i+1} if i<len(rows) else {'archive':'declaration','event_id':row['id']}
                index=[{'fact_id':f['fact_id'],'status':f['status'],'hint':f['content'][:100],
                    'evidence_refs':[{'event_id':r['event_id'],**locators[r['event_id']]} for r in f['evidence_refs']]} for f in state['facts']]
                text+='\n'+canonical({'protected_raw_anchors':raw,'evidence_map':index})
            # JSONDecoder stops before the factual shell; the native semantic
            # object and literal initial bytes are preserved without rewriting.
            restored,_=json.JSONDecoder().raw_decode(text)
            assert restored==semantic and text.startswith(prefix)
            (folder/f'{label}-head.txt').write_text(text,encoding='utf-8')
            item['variants'][label]={'hot_tokens':e.tokens([{'role':'assistant','content':text}]),
                'native_semantic_bytes_equal':True,'common_prefix_characters':len(common),
                'source_address_occurrences':text.count(canonical(str(source))[1:-1]),
                'declaration_address_occurrences':text.count(canonical(str(decl))[1:-1])}
            assert text.count(canonical(str(source))[1:-1])==1 and text.count(canonical(str(decl))[1:-1])==1
        report.append(item)
    e.write(root/'prepare-report.json',report);return report


async def main():
    run=os.environ.get('WSC_D_SHELL_RUN','wsc-D-shell-224')
    assert run in {'wsc-D-shell-224','wsc-D-shell-225'}
    e.ROOT=e.ROOT.parent/run;e.ROOT.mkdir(exist_ok=True)
    assert not (e.ROOT/'run-report.json').exists(),'No paid rerun'
    os.environ.update(WSC_AD_TRANSPORT='httpx-direct',WSC_AD_HEAD_ROOT=run,
        WSC_AD_ARCHIVE_ROOT='wsc-D-shell-224',WSC_AD_DROP_PRIVATE_REASONING='1',
        WSC_AD_SEMANTIC_ONLY='1',WSC_AD_CONTINUATION_LIMIT='1536')
    prep=prepare_native_projection(e.ROOT) if run=='wsc-D-shell-225' else prepare(e.ROOT)
    calls=e.Calls();calls.semaphore=asyncio.Semaphore(1)
    calls.report['protocol']='Exact native D handoff reused. Deterministic bridge into V3.1/V3, no A1 prompt, no semantic rewrite, no new semantic API. Same semantic-only query as221/222.'
    calls.report['prepare']=prep
    calls.report['renderer']='native D prefix + address-once index' if run=='wsc-D-shell-225' else 'generic StateFact bridge'
    for name in e.CASES:
        for mode in ['D1','D2']:
            try:await evaluate(calls,name,mode)
            except Exception as exc:calls.report['errors'].append({'case':name,'mode':mode,'error':type(exc).__name__+': '+str(exc)[:180]})
            calls.save()
    print(canonical({'calls':len(calls.report['calls']),'cost':sum(c['cost_estimate'] for c in calls.report['calls']),'errors':calls.report['errors']}),flush=True)


if __name__=='__main__':asyncio.run(main())
