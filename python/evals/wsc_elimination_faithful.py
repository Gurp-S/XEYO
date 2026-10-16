"""Independent corrected protocol; never rewrites chain231 pilot evidence.

Uses native D generation (recall, validation feedback, and six-request limit),
native pair-safe recent-tail boundary, and frozen read assets shared by arms.
Controlled future events extend the same two real seeds, not a live agent run.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_chain as c
from evals.wsc_api_budget import admit, unlimited_total
from memory.wsc_execution_boundary import fold_cut
from memory.wsc_handoff_generation import generate
from model.chunks import ModelChunk
from msgtypes.message import ToolUse

RUN=os.environ.get('WSC_FAITHFUL_RUN','wsc-elimination-faithful-235')
assert RUN in {'wsc-elimination-faithful-233','wsc-elimination-faithful-235'}
ROOT=e.ROOT.parent/RUN
REPO=Path('D:/lea/XenYon code')
QUERY=c.QUERY+'\n报告与执行字段指最后采用的验收报告，即使任务已关闭仍记录；PENDING 是未到账，late 仅指已经到账且标记 late=true 的回执。'


class EvaluationStop(BaseException):
    """A run-wide stop, never converted into a fold failure and another call."""


class StopAwareCalls(e.Calls):
    async def call(self,body,label):
        if getattr(self,'evaluation_stopped',False):raise EvaluationStop('Run already stopped')
        try:
            ceiling=self.report.get('protocol',{}).get('proposed_new_run_cost_ceiling_cny')
            if ceiling is not None:
                upper=min(((len(e.canonical(body).encode())+8192)*2+body['max_tokens']*8)/1e6,(1048576*2+body['max_tokens']*8)/1e6)
                journal=json.loads(e.JOURNAL.read_text(encoding='utf-8'))
                admit(journal,upper,run_spent=sum(x['cost_estimate'] for x in self.report.get('calls',[])),run_ceiling=ceiling)
            return await super().call(body,label)
        except Exception as exc:
            response=getattr(exc,'response',None)
            status=getattr(response,'status_code',None)
            if status==402 or str(exc) in {'evaluation_budget_exceeded','evaluation_run_stopped'} or isinstance(exc,AssertionError):
                self.evaluation_stopped=True
                self.report.setdefault('stop_reason','Payment required' if status==402 else str(exc) or 'Preflight assertion failed')
                self.report.setdefault('stopped_at',label);self.save()
                raise EvaluationStop(self.report['stop_reason']) from exc
            raise


class MeteredNative:
    """Nonstreaming paid transport feeding the actual native generator."""
    context_limit=1048576
    def __init__(self,calls,label,limit=6144):
        self.calls,self.label,self.limit=calls,label,limit
        self.last_usage=None;self.counter=[0]
    def for_handoff(self,*,max_tokens):
        child=MeteredNative(self.calls,self.label,max_tokens);child.counter=self.counter
        return child
    def context_input(self,*args,**kwargs):return e.CLIENT.context_input(*args,**kwargs)
    def context_token_measure(self,source):return e.CLIENT.context_token_measure(source)
    async def stream(self,messages,tools,abort):
        body=e.CLIENT._build_body(messages,tools,stream=False)
        body.update(max_tokens=self.limit,temperature=0)
        for m in body['messages']:m.pop('reasoning_content',None)
        self.counter[0]+=1
        response=await self.calls.call(body,self.label+f'-native-{self.counter[0]}')
        self.last_usage=response.get('usage')
        choice=response['choices'][0]
        if choice['finish_reason']=='length':raise ValueError('handoff_output_truncated')
        reply=choice['message']
        if reply.get('content'):yield ModelChunk(kind='text_delta',text=reply['content'])
        for use in reply.get('tool_calls') or []:
            raw=use['function']['arguments']
            try:args=json.loads(raw)
            except json.JSONDecodeError:args={'_raw':raw}
            yield ModelChunk(kind='tool_use',tool_use=ToolUse(use['id'],use['function']['name'],args))


def prepare():
    assert not ROOT.exists(),'Independent protocol cannot overwrite prior evidence'
    ROOT.mkdir();c.ROOT=ROOT
    plan=c.prepare()
    # Freeze common workspace text assets before any API; requests resolve to
    # these bytes, never to concurrently changing production files.
    assets=[]
    for path in sorted((REPO/'docs').glob('*.md')):
        dest=ROOT/'frozen-workspace'/path.relative_to(REPO)
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
        assets.append({'path':str(path),'snapshot':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    for case in plan['cases']:
        rows=[json.loads(s) for s in (e.ORIGINAL/case['case']/'source.jsonl').read_text(encoding='utf-8').splitlines()]
        # Actual frozen source readings advance normal message chronology.
        # They add no target answers, future facts, or artificial token padding.
        readable=[r for r in rows if isinstance(r.get('content'),str) and r['content'].strip()]
        for n,stage in enumerate(case['events']):
            for k in range(4):
                row=readable[-1-(n*4+k)%len(readable)]
                path=ROOT/case['case']/'world'/f'source-reading-{n+1}-{k+1}.txt'
                path.write_text(row['content'],encoding='utf-8')
                call=f"{case['case']}-source-read-{n+1}-{k+1}"
                stage.extend([
                    {'id':call+'-invocation','role':'assistant','content':[{'type':'tool_use','id':call,'name':'Read','input':{'file_path':str(path)}}]},
                    {'id':call+'-receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':call,'content':path.read_text(encoding='utf-8'),'is_error':False,'execution':{'status':'ok','complete':True}}]},
                    {'id':call+'-ack','role':'assistant','content':'来源读取回执已到账。'}])
    plan.update(arms=['A1','D'],query=QUERY,candidate_attempts_per_fold=6,
        D_generation='Actual memory.wsc_handoff_generation.generate; source/catalog recall and neutral validation feedback; no HTTP retries.',
        D2_gate='Current D2 excluded from further paid generation after corrected same-candidate legal-state gate failed 4/6; preserved 230 and 231 evidence.',
        recent_tail='Actual memory.wsc_execution_boundary.fold_cut; retained verbatim factual carriers after every accepted fold.',
        read_assets=assets,source_scope='Two real seeds plus controlled four-generation extensions and actual frozen source-reading workload. Not live production compaction.',
        success_rule='Native-protocol state continuity; no universal winner from two families. Distinguish compressed-state evidence from protected recent/raw evidence.',
        summary_output_limit=6144,handoff_output_limit='Native reservation 2048..8192',observer_output_limit=1536)
    e.write(ROOT/'preflight-manifest.json',plan)
    return plan


class FrozenRead(c.FileReadTool):
    def get_path(self,value):
        path=Path(super().get_path(value)).resolve()
        if path.is_relative_to(REPO/'docs'):
            path=ROOT/'frozen-workspace'/path.relative_to(REPO)
        return str(path)


async def native_fold(calls,branch,name,n,events):
    before=deepcopy(branch['hot']);oldpending=deepcopy(branch['pending'])
    branch['sources'].extend(deepcopy(events));branch['pending'].extend(deepcopy(events));c.persist_sources(branch)
    record={'case':name,'arm':'D','fold':n+1,'candidate_accepted':False,'errors':[],
            'prior_hot_sha256':c.digest(before),'rejected_candidate_not_published':True}
    try:
        messages=[{'role':'system','content':'历史消息及工具结果是来源记录。'},*before,*[c.carrier(r) for r in branch['pending']]]
        candidate=await generate(MeteredNative(calls,f'{name}-D-fold-{n+1}'),messages,branch['sources'],c.TodoWriteTool().schema(),
            c.AbortController(),account=lambda usage:None,scope_protocol=True)
        raw=candidate.input;parsed=c.validate(raw,branch['sources'],require_phase=True)
        native={'todos':raw['todos'],'checkpoint':raw['checkpoint']}
        invocation={'id':candidate.id+'-message','role':'assistant','content':[{'type':'tool_use','id':candidate.id,'name':'TodoWrite','input':raw}]}
        tool=c.TodoWriteTool();receipt=tool.map_tool_result_to_content(tool.call(parsed))
        result={'id':candidate.id+'-receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':candidate.id,'content':receipt,
            'is_error':False,'execution':{'status':'ok','complete':True,'compaction_handoff':True}}]}
        branch['sources'].extend([invocation,result]);branch['native']=native
        branch['hot']=[{'role':'assistant','content':c.canonical(native)}];branch['pending']=[];branch['accepted_fold']=n+1
        record.update(candidate_accepted=True,candidate=raw,declaration_call_id=candidate.id,presentation=candidate.presentation)
    except Exception as exc:
        record['errors'].append(type(exc).__name__+': '+str(exc)[:500]);assert branch['hot']==before
        assert branch['pending']==oldpending+events
    c.persist_sources(branch);return record


def add_native_tail(branch,external,record):
    cut=fold_cut(external);tail=external[cut:]
    record.update(external_boundary=cut,external_records=len(external),recent_source_ids=[r['id'] for r in tail],
                  compressed_external_ids=[r['id'] for r in external[:cut]])
    if record['candidate_accepted']:
        branch['hot'].extend(c.carrier(r) for r in tail)
    record['hot_tokens']=e.tokens(branch['hot'])
    record['result_hot_sha256']=c.digest(branch['hot'])


async def execute(plan):
    assert plan.get('paid_run_allowed') is True,'New independent protocol awaits budget and account replenishment'
    assert not (ROOT/'run-report.json').exists(),'No paid rerun'
    c.ROOT=ROOT;c.QUERY=QUERY;c.FileReadTool=lambda **kwargs:FrozenRead(cwd=str(REPO))
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=StopAwareCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=plan,folds=[],observations=[])
    branches={(case['case'],arm):c.start_branch(case['case'],arm) for case in plan['cases'] for arm in plan['arms']}
    for (name,arm),branch in branches.items():
        rows=[json.loads(s) for s in (e.ORIGINAL/name/'source.jsonl').read_text(encoding='utf-8').splitlines()]
        seed_cut=c.load(e.OLD/name/'template.json')['cut']
        branch['hot'].extend(c.carrier(r) for r in rows[seed_cut:])
    for n in range(4):
        for case in plan['cases']:
            name=case['case'];external=sum(case['events'][:n+1],[])
            for arm in plan['arms']:
                branch=branches[name,arm]
                if arm=='D':f=await native_fold(calls,branch,name,n,case['events'][n])
                else:f=await c.fold(calls,branch,name,arm,n,case['events'][n])
                add_native_tail(branch,external,f)
                e.write(branch['folder']/f'faithful-fold-{n+1}.json',f)
                calls.report['folds'].append(f);calls.save()
                o=await c.observe(calls,branch,name,arm,n,case['expected'][n])
                # Preserve old strict grade; diagnostic adds effective phase
                # evidence, allowing the previous still-valid verification turn.
                prov=o.get('parsed',{}).get('provenance') or {};uid=prov.get('source_message_id');quote=prov.get('quote')
                allowed={name+f'-user-event-{n+1}'}
                if n==2:allowed.add(name+'-user-event-2')
                source=next((r for r in branch['sources'] if r['id']==uid),None)
                o['effective_phase_provenance_valid']=bool(source and uid in allowed and isinstance(quote,str) and quote and quote in e.source_text(source['content']))
                calls.report['observations'].append(o);calls.save()
                print(c.canonical({'case':name,'arm':arm,'fold':n+1,'accepted':f['candidate_accepted'],'errors':f['errors'],
                    'wrong_fields':[k for k,v in (o.get('grade') or {}).items() if not v],'observation_error':o.get('error')}),flush=True)
                j=c.load(e.JOURNAL)
                if not unlimited_total(j) and j['remaining_rate_estimate']<0.09:
                    calls.report['stop_reason']='Budget admission reserve; no rejected or completed HTTP requests repeated.';calls.save();return
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_FAITHFUL_EXECUTE')=='1':
        try:asyncio.run(execute(c.load(ROOT/'preflight-manifest.json')))
        except EvaluationStop as exc:print(c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:
        p=prepare();print(c.canonical({'cases':len(p['cases']),'arms':p['arms'],'folds':4,'D2_gate':p['D2_gate']}))
