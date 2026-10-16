"""Same-corpus V3.1/V3 prototypes; bounded parallel API and durable usage ledger."""
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import urllib.request
import tempfile

from engine.abort import AbortController
from engine.turn_snapshot import _atomic_write
from evals.wsc_ad_candidate import (ACTIVE, canonical, commit_candidate, denoise,
    digest, evidence, initial, persist_state, prompt, read_state, source_text)
from model.deepseek import DeepSeekModelClient
from model.context_input import from_body
from evals.wsc_api_budget import admit, charge, unlimited_total
from tools.file_read_tool.file_read_tool import FileReadTool

ROOT = Path('D:/lea/XenYon code/_wsc_out')/os.environ.get('WSC_AD_RUN','wsc-AD-213')
assert ROOT.parent == Path('D:/lea/XenYon code/_wsc_out') and ROOT.name in {'wsc-AD-213','wsc-AD-214'}
GENERATION_LIMIT = int(os.environ.get('WSC_AD_OUTPUT_LIMIT','4096'))
OLD = ROOT.parent/'wsc-expanded-208'
ORIGINAL = ROOT.parent/'wsc-four-arm-206'
JOURNAL = ROOT.parent/'api-budget-one-yuan-2026-10-12.json'
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
CASES = ['long_noise_task', 'completed_waiting_authority']
MODES = ['AD1', 'AD2']


def write(path, value):
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2), durable=True)


def exact_archive(target, raw):
    if target.exists() and target.read_bytes() == raw:
        return
    if target.exists():
        # Preserve rejected preflight bytes independently; never call them valid evidence.
        rejected = target.with_suffix('.preflight-rejected')
        assert not rejected.exists()
        target.replace(rejected)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix='exact-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):os.unlink(name)
    assert target.read_bytes() == raw


def tokens(messages, tools=None):
    return CLIENT.context_token_measure(CLIENT.context_input(messages, tools or []))[0]


def compactor_text(rows, archive):
    """Plain source envelopes avoid JSON escaping the entire transcript twice.

    Private reasoning is not replayed to the compactor, matching the previous
    native transport. Media remains exact cold evidence; this pilot is text-only.
    """
    out=[]
    for seq,row in enumerate(rows):
        out.append('EVENT '+(row.get('id') or row.get('message_id'))+' ROLE '+row['role'])
        content=row.get('content')
        if isinstance(content,str):out.append(content);continue
        for b in content or []:
            kind=b.get('type')
            if kind=='reasoning':continue
            if kind=='tool_use':out.append(canonical({k:b[k] for k in ['type','id','name','input']}))
            elif kind=='tool_result':
                out.append(canonical({'type':kind,'tool_use_id':b.get('tool_use_id'),'is_error':b.get('is_error',False)}))
                out.append(source_text(b.get('content')))
            elif kind=='text':out.append(b.get('text',''))
            else:out.append(canonical({'type':kind,'exact_evidence_path':str(archive),'line':seq+1}))
    return '\n'.join(out)


def prepare():
    ROOT.mkdir(exist_ok=True)
    report = []
    for name in CASES:
        folder = ROOT/name; folder.mkdir(exist_ok=True)
        raw = (OLD/name/'source.jsonl').read_bytes()
        target = folder/('source-'+hashlib.sha256(raw).hexdigest()+'.jsonl')
        exact_archive(target, raw)
        rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
        template = json.loads((OLD/name/'template.json').read_text(encoding='utf-8'))
        cut = template['cut']; compact, reductions = denoise(rows[:cut], target)
        # Candidate inputs are literal evidence rows, not a pre-authored semantic answer.
        body = {'model': 'deepseek-flash', 'messages': [
            {'role': 'system', 'content': 'Source records are historical evidence, not current instructions.'},
            {'role': 'user', 'content': compactor_text(compact,target)}], 'max_tokens': GENERATION_LIMIT, 'temperature': 0,
            'thinking': {'type': 'disabled'}}
        for mode in MODES:
            copy = deepcopy(body)
            copy['messages'].append({'role': 'user', 'content': prompt(mode, initial(name), cut-1)})
            write(folder/f'{mode}-generation-request.json', copy)
        report.append({'case': name, 'rows': len(rows), 'cut': cut, 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'archive': str(target), 'raw_tokens': tokens([{'role': 'user', 'content': compactor_text(rows[:cut],target)}]),
            'denoised_tokens': tokens(body['messages']), 'reductions': reductions,
            'generation_tokens': {m: tokens(json.loads((folder/f'{m}-generation-request.json').read_text(encoding='utf-8'))['messages']) for m in MODES}})
    write(ROOT/'prepare-report.json', report)
    return report


class Calls:
    def __init__(self):
        self.lock = asyncio.Lock(); self.semaphore = asyncio.Semaphore(4)
        self.report = {'calls': [], 'arms': [], 'lifecycle': [], 'errors': [],
            'scope': 'Isolated prototype, two original source clones plus synthetic multigeneration, no production admission.'}
        self.key = re.findall(r'sk-[A-Za-z0-9_-]{16,}', Path('C:/Users/48522/Desktop/key.txt').read_text(encoding='utf-8-sig'))
        assert len(self.key) == 1

    def save(self):
        write(ROOT/'run-report.json', self.report)

    async def call(self, body, label):
        async with self.semaphore:
            serialized = canonical(body)
            # Historical/test identifiers such as task-source-read-invocation
            # contain an embedded "sk-". A credential token has a boundary.
            assert self.key[0] not in serialized, 'credential_in_request'
            assert not re.search(r'(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{24,}', serialized), 'credential_like_token_in_request'
            count = CLIENT.context_token_measure(from_body(body))[0]
            limit = body['max_tokens']
            if count+limit > 1048576:
                raise ValueError('model_capacity_estimate_exceeded')
            size = len(canonical(body).encode())
            upper = min(((size+8192)*2+limit*8)/1e6, (1048576*2+limit*8)/1e6)
            async with self.lock:
                if getattr(self, 'evaluation_stopped', False):
                    raise ValueError('evaluation_run_stopped')
                journal = json.loads(JOURNAL.read_text(encoding='utf-8'))
                if not unlimited_total(journal):
                    assert journal['authorized_new_budget_cny'] >= 24
                admit(journal, upper)
                request = ROOT/(label+'-request.json')
                assert not request.exists(), 'No paid rerun'
                write(request, body)
                entry = {'label': label, 'admitted_cny_upper': upper, 'usage_observed': False,
                    'cost_estimate': upper, 'request_sha256': hashlib.sha256(request.read_bytes()).hexdigest(),
                    'input_token_estimate': count, 'output_limit': limit}
                self.report['calls'].append(entry)
                charge(journal, upper)
                journal['entries'].append(str(request)); write(JOURNAL, journal); self.save()
            def send():
                if os.environ.get('WSC_AD_TRANSPORT') in {'httpx','httpx-direct'}:
                    import httpx
                    import time
                    direct=os.environ.get('WSC_AD_TRANSPORT')=='httpx-direct'
                    read_timeout = float(os.environ.get('WSC_AD_READ_TIMEOUT', '55'))
                    if not 0 < read_timeout <= 600:
                        raise ValueError('invalid_evaluation_read_timeout')
                    started = time.monotonic()
                    entry['transport'] = {'read_timeout_seconds': read_timeout, 'direct': direct,
                                          'http_retries': 0}
                    with httpx.Client(timeout=httpx.Timeout(read_timeout, connect=20, write=55, pool=20), trust_env=not direct,
                            transport=httpx.HTTPTransport(retries=0,trust_env=not direct)) as transport:
                        try:
                            response=transport.post('https://api.deepseek.com/chat/completions',
                                content=canonical(body).encode(), headers={'Authorization':'Bearer '+self.key[0], 'Content-Type':'application/json'})
                            entry['transport'].update(status_code=response.status_code, headers={
                                name: value for name, value in response.headers.items() if name.lower() in {
                                    'x-request-id', 'request-id', 'x-trace-id', 'trace-id', 'server',
                                    'date', 'retry-after', 'content-type', 'cf-ray'}})
                            if response.is_error:
                                entry['transport']['error_body'] = response.text.replace(self.key[0], '[REDACTED]')[:16000]
                            response.raise_for_status()
                            return response.json()
                        finally:
                            entry['transport']['elapsed_seconds'] = round(time.monotonic() - started, 3)
                request = urllib.request.Request('https://api.deepseek.com/chat/completions',
                    data=canonical(body).encode(), headers={'Authorization': 'Bearer '+self.key[0], 'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=55) as response:
                    return json.loads(response.read())
            try:
                answer = await asyncio.to_thread(send)
            except Exception as exc:
                async with self.lock:
                    entry['error'] = type(exc).__name__+': '+str(exc)[:180]; self.save()
                raise
            async with self.lock:
                entry['response'] = answer
                usage = answer.get('usage')
                if usage and 'prompt_tokens' in usage and 'completion_tokens' in usage:
                    p=usage['prompt_tokens']; h=usage.get('prompt_cache_hit_tokens', 0); o=usage['completion_tokens']
                    cost=(max(0,p-h)*2+h*.04+o*8)/1e6
                    entry.update(usage_observed=True, cost_estimate=cost)
                    journal=json.loads(JOURNAL.read_text(encoding='utf-8'))
                    charge(journal, cost-upper)
                    write(JOURNAL,journal)
                    assert cost <= upper and cost <= 2.5
                self.save()
            return answer


def parse_candidate(answer):
    choice=answer['choices'][0]
    if choice['finish_reason'] != 'stop' or choice['message'].get('tool_calls'):
        raise ValueError('candidate_incomplete')
    text=choice['message'].get('content','').strip()
    if text.startswith('```'):
        text='\n'.join(text.splitlines()[1:-1])
    return json.loads(text)


def render(state, rows, mode, archive):
    head={'work_state':state, 'evidence_archive':str(archive), 'source_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    if mode == 'AD1':
        used=[]; cost=0
        for row in reversed(rows):
            if row['role'] != 'user': continue
            size=tokens([row])
            if cost+size > 8000: break
            used.append(row);cost+=size
        head['protected_raw_anchors']=list(reversed(used))
        head['evidence_map']=[{'fact_id':f['fact_id'],'status':f['status'],'hint':f['content'][:100],
            'locators':[{'event_id':r['event_id'],'line':next(i+1 for i,v in enumerate(rows) if (v.get('id') or v.get('message_id'))==r['event_id'])} for r in f['evidence_refs']]} for f in state['facts']]
    return canonical(head)


def preserve_tail(rows):
    """All replayed tool activity is evidence, not new callable tool activity.

    Providers can prune historical calls whose names are absent from the current
    Read-only schema, even when source call/result pairs were intact.
    """
    out=[];carriers=[]
    for row in rows:
        content=row.get('content');blocks=content if isinstance(content,list) else []
        results=[b for b in blocks if b.get('type')=='tool_result']
        if row['role']=='tool' and results:
            out.append({'role':'user','content':canonical({'historical_tool_observation':row})})
            carriers.append(row.get('id') or row.get('message_id'))
        elif row['role']=='assistant' and any(b.get('type')=='tool_use' for b in blocks):
            copy=deepcopy(row)
            copy['content']=[{'type':'text','text':canonical({'historical_tool_invocation':b})}
                if b.get('type')=='tool_use' else b for b in blocks]
            out.append(copy)
        else:out.append(row)
    return out,carriers


async def real_arm(calls, prep, mode):
    name=prep['case']; folder=ROOT/name
    rows=[json.loads(x) for x in Path(prep['archive']).read_text(encoding='utf-8').splitlines()]
    template=json.loads((OLD/name/'template.json').read_text(encoding='utf-8'));cut=template['cut']
    state=initial(name); store=evidence(rows[:cut]); errors=[]; accepted=False
    result={'case':name,'mode':mode,'reads':[],'answer':None,'grade':None}
    calls.report['arms'].append(result)
    try:
        body=json.loads((folder/f'{mode}-generation-request.json').read_text(encoding='utf-8'))
        answer=await calls.call(body,f'{name}-{mode}-generation')
        candidate=parse_candidate(answer);write(folder/f'{mode}-candidate.json',candidate)
        state,errors,accepted=commit_candidate(state,candidate,store,mode)
    except Exception as exc:
        errors.append(type(exc).__name__+': '+str(exc)[:180])
    result.update(candidate_accepted=accepted,guard_errors=errors,committed_facts=len(state['facts']))
    # Full evidence remains when initial state is rejected; no fake compaction score.
    if not accepted:
        result['not_run_reason']='initial_state_rejected; original evidence retained'; calls.save(); return
    persist_state(folder/f'{mode}-state.json',state);assert read_state(folder/f'{mode}-state.json')==state
    head=render(state,rows[:cut],mode,Path(prep['archive']))
    (folder/f'{mode}-head.txt').write_text(head,encoding='utf-8')
    result['hot_tokens']=tokens([{'role':'assistant','content':head}])
    tail=rows[cut:]
    if ROOT.name=='wsc-AD-215':
        tail,carriers=preserve_tail(tail);result['historical_result_carriers']=carriers
    messages=[template['system'],{'role':'assistant','content':head},*tail,template['archive']]
    result['auto_rehydration']=[]
    if mode == 'AD1':
        # Explicit source_index match only, before generation; no use of gold.
        match=re.search(r'source_index=(\d+)',template['query']['content'])
        if match and int(match.group(1))<len(rows):
            i=int(match.group(1));row=rows[i]
            block={'source_index':i,'event_id':row.get('id') or row.get('message_id'),
                'content_hash':digest(row),'decoded_text_start':source_text(row['content'])[:5000],
                'exact_locator':{'path':prep['archive'],'line':i+1}}
            messages.append({'role':'user','content':canonical({'recovered_evidence':block})})
            result['auto_rehydration']=[{'source_index':i,'tokens':tokens([messages[-1]])}]
    messages.append(template['query']); frozen=head
    reader=FileReadTool(cwd=str(folder)); reader.set_vision_enabled(True)
    old_reader=FileReadTool(cwd=str(ORIGINAL/name));old_reader.set_vision_enabled(True)
    search={'name':'SearchEvidence','description':'Literal search of immutable source events. Returns source IDs, locations and exact text excerpts.',
        'input_schema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}
    tools=[reader.schema()]+([search] if mode=='AD1' else [])
    spec=importlib.util.spec_from_file_location('ad_grading',OLD/'evaluate-valid.py'); grading=importlib.util.module_from_spec(spec);spec.loader.exec_module(grading)
    truth=json.loads((OLD/'gold.json').read_text(encoding='utf-8'))[name]
    result['full_request_tokens']=tokens(messages,tools)
    for turn in range(4):
        body=CLIENT._build_body(messages,tools,stream=False);body.update(max_tokens=1536,temperature=0)
        try:answer=await calls.call(body,f'{name}-{mode}-continuation-{turn}')
        except Exception as exc:result['runtime_error']=type(exc).__name__+': '+str(exc)[:180];break
        reply=answer['choices'][0]['message'];uses=reply.get('tool_calls') or []
        if not uses:
            result['answer']=reply.get('content') or '';value,strict=grading.parse(result['answer'])
            result['parsed']=value;result['grade']=grading.grade(value,truth,rows);result['strict_json']=strict
            result['finish_reason']=answer['choices'][0]['finish_reason'];break
        blocks=[]
        for use in uses[:12]:
            try:args=json.loads(use['function']['arguments'])
            except ValueError:args={}
            blocks.append({'type':'tool_use','id':use['id'],'name':use['function']['name'],'input':args})
        if len(uses)>12:result['runtime_error']='tool_batch_capacity_exceeded';break
        messages.append({'role':'assistant','content':blocks})
        for b in blocks:
            content='Tool unavailable';err=True
            try:
                if b['name']=='SearchEvidence' and mode=='AD1':
                    query=b['input']['query'];hits=[]
                    if not isinstance(query,str) or not query:raise ValueError('empty_search_query')
                    for seq,row in enumerate(rows):
                        text=source_text(row['content'])
                        if query.casefold() in text.casefold() or query==(row.get('id') or row.get('message_id')):
                            index=text.casefold().find(query.casefold());hits.append({'event_id':row.get('id') or row.get('message_id'),
                                'line':seq+1,'path':prep['archive'],'excerpt':text[max(0,index-300):max(0,index-300)+2000]})
                        if len(hits)==5:break
                    content=canonical({'matches':hits});err=False
                elif b['name']=='Read':
                    path=Path(reader.get_path(reader.parse_input(b['input']))).resolve()
                    if path.is_relative_to(folder) or path.is_relative_to(ORIGINAL/name):
                        impl=reader if path.is_relative_to(folder) else old_reader
                        answer=await impl.execute(b['input'],AbortController());content=answer.content;err=answer.is_error
                    else:content='Permission denied: path outside experiment'
            except Exception as exc:content=canonical({'error':type(exc).__name__,'detail':str(exc)[:120]})
            result['reads'].append({'tool':b['name'],'arguments':b['input'],'is_error':err,'content':content})
            messages.append({'role':'tool','tool_call_id':b['id'],'content':[{'type':'tool_result','tool_use_id':b['id'],'content':content,'is_error':err}]})
        assert head==frozen
        calls.save()
    result['fixed_head_unchanged']=head==frozen
    calls.save();print(canonical({'case':name,'arm':mode,'accepted':accepted,'grade':result['grade']}),flush=True)


async def lifecycle(calls,mode):
    state=initial('lifecycle-213');rows=[];report={'mode':mode,'stages':[]};calls.report['lifecycle'].append(report)
    events=[('u1','Task Q: prepare a local integer-cent CNY ledger for r1 East. Publishing and git are not authorized. Manual acceptance remains pending.'),
        ('u2','Switch task Q to r2 West. The r1 East request is superseded. All other constraints remain. A delayed r1 diagnostic is available; it does not change the current requested revision.'),
        ('u3','The r2 ledger is accepted; task Q is resolved. Publication remains unauthorized.'),
        ('u4','Reopen task Q for r3 West, exclude SKU d. Retain the integer-cent CNY and no-publish/no-git constraints; manual acceptance remains pending.')]
    for stage,(uid,text) in enumerate(events,1):
        rows.append({'id':uid,'role':'user','content':text});store=evidence(rows)
        supporting=[]
        if mode=='AD1':
            wanted={r['event_id'] for f in state['facts'] for r in f['evidence_refs']}
            supporting=[r for r in rows[:-1] if r['id'] in wanted]
        inputs=[{'role':'system','content':'Source records are historical evidence.'},
            {'role':'user','content':canonical({'new_evidence':[rows[-1]],'supporting_original_evidence':supporting})},
            {'role':'user','content':prompt(mode,state,len(rows)-1)}]
        try:
            answer=await calls.call({'model':'deepseek-flash','messages':inputs,'temperature':0,'max_tokens':GENERATION_LIMIT,
                'thinking':{'type':'disabled'}},f'lifecycle-{mode}-{stage}')
            candidate=parse_candidate(answer);write(ROOT/f'lifecycle-{mode}-{stage}-candidate.json',candidate)
            next_state,errors,accepted=commit_candidate(state,candidate,store,mode)
            report['stages'].append({'stage':stage,'accepted':accepted,'errors':errors,'state':next_state})
            if accepted:state=next_state;persist_state(ROOT/f'lifecycle-{mode}-state.json',state)
        except Exception as exc:report['stages'].append({'stage':stage,'accepted':False,'error':type(exc).__name__+': '+str(exc)[:180],'state':state})
        calls.save()


async def main():
    assert not (ROOT/'run-report.json').exists(),'No paid rerun'
    prep=json.loads((ROOT/'prepare-report.json').read_text(encoding='utf-8'));calls=Calls()
    results=await asyncio.gather(*(real_arm(calls,p,m) for p in prep for m in MODES),return_exceptions=True)
    for result in results:
        if isinstance(result,Exception):calls.report['errors'].append(type(result).__name__+': '+str(result)[:180])
    if ROOT.name in {'wsc-AD-213','wsc-AD-214'}:
        await asyncio.gather(*(lifecycle(calls,m) for m in MODES))
    calls.save()
    print(canonical({'calls':len(calls.report['calls']),'cost':sum(c['cost_estimate'] for c in calls.report['calls']),
        'arms':len(calls.report['arms']),'errors':calls.report['errors']}),flush=True)


if __name__=='__main__':
    import sys
    if '--prepare' in sys.argv:print(canonical(prepare()),flush=True)
    else:asyncio.run(main())
