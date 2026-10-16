"""Four controlled future folds on two real-source seeds, native A1/D/D2.

Each branch consumes only its own previous projection and identical new events.
Observer answers are forked measurements, not injected back into task history.
Original history remains cold; exact unconsumed results are shared hard safety.
"""
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
from evals.wsc_ad_candidate import canonical, digest, evidence, commit_candidate, read_state, persist_state
from evals.wsc_d_handoff_shell_control import extract_d, candidate_from_d
from memory.wsc_handoff_generation import REQUEST, source_schema
from memory.wsc_handoff_bindings import basis
from memory.wsc_handoff_workset import materialize
from memory.wsc_handoff_validation import validate
from tools.todo_write_tool.todo_write_tool import TodoWriteTool
from tools.file_read_tool.file_read_tool import FileReadTool
from engine.abort import AbortController
from evals.wsc_source_observation import carrier

ROOT=e.ROOT.parent/'wsc-elimination-chain-231'
VENDOR=e.OLD/'vendor/codex'
PREFIX=(VENDOR/'summary_prefix.md').read_text(encoding='utf-8').strip()+'\n'
PROMPT=(VENDOR/'prompt.md').read_text(encoding='utf-8')
PHASES=('implementation','verification','verification','closed')
QUERY=('核对来源记录当前状态，输出JSON对象：phase（implementation/verification/closed）；task_open；closed_question_open（历史ChatGPT前台启动问题是否仍待处理）；'
       'publish_authorized；git_authorized；phase_test_ban_active；current_report_version；'
       'selected_execution_id；selected_value；late_execution_id；late_revision；'
       'late_consumed_before_request；provenance（支撑当前阶段的一条原文引用，含source_message_id和quote）；'
       'next_actions（当前仍获授权且未完成的动作数组）。selected_execution_id指支撑当前报告版本、回执已经到账的执行；没有到账回执为null。'
       'late字段指已到账的迟到回执，没有时为null；consumed_before_request按本次请求发送前账本状态。未知为null。历史提议、完成事项与当前任务分别记录。')


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def retain_users(hot,events,summary):
    candidates=[m for m in hot if m['role']=='user' and isinstance(m['content'],str) and not m['content'].startswith(PREFIX)]
    candidates.extend({'role':'user','content':r['content']} for r in events if r['role']=='user')
    selected=[];remaining=20000
    for row in reversed(candidates):
        text=row['content'];cost=math.ceil(len(text.encode())/4)
        if cost>remaining:
            cap=remaining*4;raw=text.encode();half=cap//2
            text=raw[:half+cap%2].decode(errors='ignore')+f'…{math.ceil((len(raw)-cap)/4)} tokens truncated…'+raw[-half:].decode(errors='ignore')
            selected.append({'role':'user','content':text});break
        selected.append(deepcopy(row));remaining-=cost
        if not remaining:break
    return list(reversed(selected))+[{'role':'user','content':PREFIX+summary}]


def fixture(name):
    events=[];expected=[];base=ROOT/name/'world';base.mkdir(parents=True,exist_ok=True)
    # Actual local artifact versions support result values. The model only observes.
    for rev,value in [(1,731),(2,947)]:
        (base/f'report-v{rev}.json').write_text(canonical({'revision':rev,'value':value}),encoding='utf-8')
    x1=name+'-execution-r1';x2=name+'-execution-r2'
    for n in range(4):
        uid=name+f'-user-event-{n+1}'
        if n==0:
            text=('历史 ChatGPT 前台启动问题已经解决，不再重做。当前原任务继续，进入 implementation 阶段。'
                  '长期约束：不发布、不操作git；仅 implementation 阶段不运行测试。当前采用报告版本1。')
        elif n==1:
            text=('进入 verification 阶段，implementation 阶段的不运行测试限制到期，仅允许相关验证子集。'
                  '报告版本1已被版本2替代，版本1仅作历史。原任务继续，不发布、不操作git。')
        elif n==2:
            text='仍处于 verification，继续核对版本2的证据。历史已解决问题不重做，长期约束不变。'
        else:
            text='原任务全部验收完成，所有未完成步骤均关闭，当前阶段 closed；不重开历史问题。没有发布或git授权，等待新任务。'
        stage=[{'id':uid,'role':'user','content':text}]
        if n in (0,1):
            rev=n+1;xid=x1 if n==0 else x2;call=name+f'-probe-call-r{rev}'
            stage.append({'id':call+'-source','role':'assistant','content':[{'type':'tool_use','id':call,'name':'LocalEvidenceProbe','input':{'revision':rev,'execution_id':xid}}]})
            if n==1:
                stage.append({'id':call+'-receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':call,'is_error':False,
                    'content':(base/'report-v2.json').read_text(encoding='utf-8'),
                    'execution':{'id':xid,'status':'ok','complete':True,'revision':2,'late':False}}]})
        if n==2:
            call=name+'-probe-call-r1'
            stage.append({'id':call+'-receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':call,'is_error':False,
                'content':(base/'report-v1.json').read_text(encoding='utf-8'),
                'execution':{'id':x1,'status':'ok','complete':True,'revision':1,'late':True}}]})
        events.append(stage)
        expected.append({'phase':PHASES[n],'task_open':n<3,'closed_question_open':False,'publish_authorized':False,'git_authorized':False,
            'phase_test_ban_active':n==0,'current_report_version':1 if n==0 else 2,
            'selected_execution_id':None if n==0 else x2,'selected_value':None if n==0 else 947,
            'late_execution_id':x1 if n>=2 else None,'late_revision':1 if n>=2 else None,
            'late_consumed_before_request':False if n==2 else True if n==3 else None,'phase_source':uid})
    return {'case':name,'events':events,'expected':expected,'world_path':str(base)}


def prepare():
    ROOT.mkdir(exist_ok=True);plan={'scope':__doc__,'cases':[fixture(n) for n in e.CASES],
        'arms':['A1','D','D2'],'folds':4,'model':'deepseek-flash','thinking':'disabled','temperature':0,
        'handoff_output_limit':6144,'summary_output_limit':6144,'observer_output_limit':1536,
        'http_retries':0,'candidate_attempts_per_fold':1,'observer_max_calls':2,
        'D2_definition':'Native D validation plus current native-to-StateFact bridge and whole-state AD2 guard, corrected baseline version.',
        'isolation':'Same controlled external event chronology. Each arm keeps own checkpoint, declarations, pending tail and result consumption ledger.',
        'source_scope':'Two real-source seeds; future controlled extensions, not historical provider replay or live85% test.',
        'success_rule':'State freshness and observer task correctness separate. Fatal revival/constraint/scope/execution errors disqualify current implementation; otherwise correctness then measured extra complexity/cost.',
        'nonclaim':'Two source families and four folds cannot establish universal superiority. Prototype failures are separated from architecture hypotheses.'}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


def start_branch(name,label):
    folder=ROOT/name/label;folder.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(s) for s in (e.ORIGINAL/name/'source.jsonl').read_text(encoding='utf-8').splitlines()]
    native,decl,_,receipt,_=extract_d(e.ORIGINAL/name)
    if label=='A1':
        old=load(e.OLD/name/'A1-runtime-messages.json');t=load(e.OLD/name/'template.json')
        hot=old[1:len(old)-len(rows[t['cut']:])-2];sources=rows
    else:hot=[{'role':'assistant','content':canonical(native)}];sources=rows+decl
    state=read_state(e.ROOT.parent/'wsc-D-shell-224'/name/'D2-state.json') if label=='D2' else None
    return {'folder':folder,'hot':hot,'sources':sources,'pending':[],'state':state,'consumed':set(),'native':native,'accepted_fold':0}


def shared_envelope(branch,events):
    # No source content or oracle answer is inserted into this identity envelope.
    sources=branch['sources'];indices={r['id']:i+1 for i,r in enumerate(sources)}
    native=branch['native'];uids=set((native.get('checkpoint') or {}).get('context_message_ids',[]))
    uids.update(r['id'] for r in events)
    uids.update(r['id'] for r in sources if '-user-event-' in r['id'] or '-probe-call-' in r['id'])
    return {'role':'user','content':canonical({'source_identities':[{'id':uid,'line':indices[uid]} for uid in sorted(uids) if uid in indices],
        'exact_archive':str(branch['folder']/'source.jsonl'),'progress_basis':'declared'})}


def persist_sources(branch):
    raw=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in branch['sources'])
    e.write(branch['folder']/'source-envelope.json',{'sha256':hashlib.sha256(raw.encode()).hexdigest(),'records':len(branch['sources'])})
    (branch['folder']/'source.jsonl').write_text(raw,encoding='utf-8')


async def fold(calls,branch,name,label,n,events):
    before=deepcopy(branch['hot']);branch['sources'].extend(deepcopy(events));branch['pending'].extend(deepcopy(events));persist_sources(branch)
    visible=[{'role':'system','content':'历史消息及工具结果是来源记录。'},*before,*[carrier(r) for r in branch['pending']],shared_envelope(branch,branch['pending'])]
    record={'case':name,'arm':label,'fold':n+1,'candidate_accepted':False,'errors':[],'rejected_candidate_not_published':True,
        'prior_hot_sha256':digest(before),'pending_events':len(branch['pending'])}
    if label=='A1':
        body=e.CLIENT._build_body([*visible,{'role':'user','content':PROMPT}],[],stream=False);body.update(max_tokens=6144,temperature=0)
    else:
        tool,identities=source_schema(TodoWriteTool().schema(),branch['sources'],scope_protocol=True)
        previous=basis(branch['sources']);workset=materialize(branch['sources'])
        request=REQUEST+'\n来源身份='+json.dumps(identities,ensure_ascii=False)+'\n已提交上下文绑定='+json.dumps(previous,ensure_ascii=False)+'\n已绑定任务来源原文='+json.dumps(workset,ensure_ascii=False)
        body=e.CLIENT._build_body([*visible,{'role':'user','content':request}],[tool],stream=False)
        body.update(max_tokens=6144,temperature=0,tool_choice={'type':'function','function':{'name':'TodoWrite'}})
    for m in body['messages']:m.pop('reasoning_content',None)
    try:
        response=await calls.call(body,f'{name}-{label}-fold-{n+1}');choice=response['choices'][0]
        if label=='A1':
            text=choice['message'].get('content') or ''
            if choice['finish_reason']!='stop' or not text.strip():raise ValueError('summary_incomplete')
            branch['hot']=retain_users(before,branch['pending'],text);branch['pending']=[]
            record.update(candidate_accepted=True,summary=text)
        else:
            uses=choice['message'].get('tool_calls') or []
            if choice['finish_reason']!='tool_calls' or len(uses)!=1 or uses[0]['function']['name']!='TodoWrite':raise ValueError('handoff_incomplete')
            use=uses[0];raw=json.loads(use['function']['arguments']);record['candidate']=raw
            parsed=validate(raw,branch['sources'],require_phase=True)
            native={'todos':raw['todos'],'checkpoint':raw['checkpoint']}
            invocation={'id':use['id']+'-message','role':'assistant','content':[{'type':'tool_use','id':use['id'],'name':'TodoWrite','input':raw}]}
            if label=='D2':
                # Proposal exists durably, but no successful runtime receipt yet.
                proposal=deepcopy(invocation);store=evidence(branch['sources']+[proposal])
                candidate=candidate_from_d(name,native,store,proposal['id']);candidate['baseline']=branch['state']['checkpoint_id']
                state,errors,accepted=commit_candidate(branch['state'],candidate,store,'AD2',reference_policy='event')
                record['added_guard_errors']=errors
                if not accepted:raise ValueError('D2_candidate_rejected: '+','.join(errors))
                branch['state']=state;persist_state(branch['folder']/f'guard-state-fold-{n+1}.json',state)
            tool=TodoWriteTool();receipt=tool.map_tool_result_to_content(tool.call(parsed))
            result={'id':use['id']+'-receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':use['id'],'content':receipt,'is_error':False,'execution':{'status':'ok','complete':True}}]}
            branch['sources'].extend([invocation,result]);branch['native']=native
            branch['hot']=[{'role':'assistant','content':canonical(native)}];branch['pending']=[]
            record.update(candidate_accepted=True,declaration_call_id=use['id'])
        branch['accepted_fold']=n+1
    except Exception as exc:
        record['errors'].append(type(exc).__name__+': '+str(exc)[:400])
        assert branch['hot']==before
    record['hot_tokens']=e.tokens(branch['hot']);record['result_hot_sha256']=digest(branch['hot']);record['pending_after']=len(branch['pending'])
    persist_sources(branch);e.write(branch['folder']/f'fold-{n+1}.json',record);e.write(branch['folder']/f'view-{n+1}.json',{'hot':branch['hot'],'pending':branch['pending'],'accepted_fold':branch['accepted_fold']})
    return record


async def observe(calls,branch,name,label,n,expected):
    consumed_before=set(branch['consumed'])
    receipts=[]
    for row in branch['sources']:
        for block in row.get('content',[]) if isinstance(row.get('content'),list) else []:
            execution=block.get('execution') or {}
            if block.get('type')=='tool_result' and execution.get('id', '').startswith(name+'-execution') and execution['id'] not in branch['consumed']:receipts.append(row)
    ledger=[]
    for rev in (1,2):
        xid=name+f'-execution-r{rev}';available=any(any((b.get('execution') or {}).get('id')==xid for b in r.get('content',[]) if isinstance(b,dict)) for r in branch['sources'] if isinstance(r.get('content'),list))
        if (rev==1 and n>=0) or (rev==2 and n>=1):ledger.append({'execution_id':xid,'revision':rev,'status':'CONSUMED' if xid in branch['consumed'] else 'AVAILABLE' if available else 'PENDING'})
    messages=[{'role':'system','content':'历史消息及工具结果是来源记录。'},*deepcopy(branch['hot']),*[carrier(r) for r in branch['pending']],
        *[carrier(r) for r in receipts],shared_envelope(branch,branch['pending']),{'role':'user','content':canonical({'execution_ledger_before_request':ledger})},
        {'role':'user','content':QUERY}]
    reader=FileReadTool(cwd=str(branch['folder']));tools=[reader.schema()]
    record={'case':name,'arm':label,'fold':n+1,'reads':[],'grade':None,'candidate_fresh':branch['accepted_fold']==n+1,'protected_receipt_ids':[r['id'] for r in receipts]}
    spec=importlib.util.spec_from_file_location('chain_grader',e.OLD/'evaluate-valid.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    try:
        for attempt in range(2):
            body=e.CLIENT._build_body(messages,tools,stream=False);body.update(max_tokens=1536,temperature=0)
            for m in body['messages']:m.pop('reasoning_content',None)
            response=await calls.call(body,f'{name}-{label}-observe-{n+1}-{attempt}');reply=response['choices'][0]['message'];uses=reply.get('tool_calls') or []
            # Main observer did receive exact preserved receipts in a successful request.
            for row in receipts:
                for b in row['content']:
                    if (b.get('execution') or {}).get('id'):branch['consumed'].add(b['execution']['id'])
            if not uses:
                parsed,strict=g.parse(reply.get('content') or '');fields={k:parsed.get(k)==v and type(parsed.get(k)) is type(v) for k,v in expected.items() if k!='phase_source'}
                # The pre-send late status is branch-local and measured, not assumed.
                if n>=2:fields['late_consumed_before_request']=parsed.get('late_consumed_before_request')==(name+'-execution-r1' in consumed_before)
                prov=parsed.get('provenance') or {};uid=prov.get('source_message_id');quote=prov.get('quote')
                matches=[r for r in branch['sources'] if r['id']==uid]
                provenance=len(matches)==1 and isinstance(quote,str) and bool(quote) and quote in e.source_text(matches[0]['content']) and uid==expected['phase_source']
                record.update(answer=reply.get('content'),parsed=parsed,strict_json=strict,grade=fields,provenance_valid=provenance,
                    task_success=all(fields.values()) and provenance and (n<3 or parsed.get('next_actions')==[]))
                break
            messages.append({'role':'assistant','content':[{'type':'tool_use','id':u['id'],'name':u['function']['name'],'input':json.loads(u['function']['arguments'])} for u in uses]})
            for use in uses:
                args=json.loads(use['function']['arguments']);path=Path(reader.get_path(reader.parse_input(args))).resolve()
                if use['function']['name']!='Read' or not path.is_relative_to(ROOT):content='Permission denied: outside isolated experiment';error=True
                else:
                    result=await reader.execute(args,AbortController());content=result.content;error=result.is_error
                record['reads'].append({'arguments':args,'is_error':error,'content':content})
                messages.append({'role':'tool','tool_call_id':use['id'],'content':[{'type':'tool_result','tool_use_id':use['id'],'content':content,'is_error':error}]})
    except Exception as exc:record['error']=type(exc).__name__+': '+str(exc)[:250]
    record['consumed_after']=sorted(branch['consumed']);e.write(branch['folder']/f'observe-{n+1}.json',record)
    return record


async def execute(plan):
    assert not (ROOT/'run-report.json').exists(),'No paid rerun'
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct';calls=e.Calls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=plan,folds=[],observations=[],source_scope=plan['source_scope'])
    branches={(name,label):start_branch(name,label) for name in e.CASES for label in ('A1','D','D2')}
    for n in range(4):
        for case in plan['cases']:
            for label in ('A1','D','D2'):
                branch=branches[case['case'],label]
                f=await fold(calls,branch,case['case'],label,n,case['events'][n]);calls.report['folds'].append(f);calls.save()
                o=await observe(calls,branch,case['case'],label,n,case['expected'][n]);calls.report['observations'].append(o);calls.save()
                print(canonical({'case':case['case'],'arm':label,'fold':n+1,'accepted':f['candidate_accepted'],'fold_errors':f['errors'],
                    'observer_grade':o.get('grade'),'observer_error':o.get('error')}),flush=True)
                journal=load(e.JOURNAL)
                if journal['remaining_rate_estimate']<0.06:
                    calls.report['stop_reason']='budget_admission_remaining';calls.save();return
    calls.report['completed']=True;calls.save();print(canonical({'calls':len(calls.report['calls']),'usage':sum(bool(c.get('usage_observed')) for c in calls.report['calls'])}),flush=True)


if __name__=='__main__':
    if os.environ.get('WSC_ELIMINATION_EXECUTE')=='1':asyncio.run(execute(load(ROOT/'preflight-manifest.json')))
    else:
        plan=prepare();print(canonical({'cases':len(plan['cases']),'folds':plan['folds'],'arms':plan['arms'],'estimated_minimum_calls':48}))
