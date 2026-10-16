"""Paired external-observation role test on immutable paid311 consumer states."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import evals.wsc_ten_generation_task as t
from evals.wsc_source_read_continuation import RootMappedSink
from evals.wsc_task_actor_candidate import new_state, run as actor_run, grade as actor_grade
from engine.abort import AbortController
from msgtypes.message import ToolUse

ROOT=t.ROOT.parent/'wsc-observation-role-ablation-312'
OLD=t.ROOT


class MappedRead:
    def __init__(self,task,logical,allowed):
        self.task=task;self.logical=Path(logical).resolve();self.allowed=set(allowed)
    def schemas(self):return [self.task.registry.get('Read').schema()]
    async def execute(self,use,abort):
        raw=use.input.get('file_path') if isinstance(use.input,dict) else None
        if use.name!='Read' or not isinstance(raw,str):return t.p.ToolResult('invalid Read arguments',is_error=True,error_kind='INVALID_ARGUMENT')
        path=Path(raw);logical=(path if path.is_absolute() else self.logical/path).resolve()
        if not logical.is_relative_to(self.logical):return t.p.ToolResult('Permission denied: outside published task evidence',is_error=True,error_kind='PERMISSION_DENIED')
        rel=logical.relative_to(self.logical).as_posix()
        if rel not in self.allowed:return t.p.ToolResult('Permission denied: outside published task evidence',is_error=True,error_kind='PERMISSION_DENIED')
        actual=self.task.root/rel
        return await self.task.registry.run(ToolUse(use.id,'Read',{**use.input,'file_path':str(actual)}),abort)


def setup(n,role,sample,*,free=False):
    prefix=ROOT/('free' if free else 'cases')/f'g{n}-{role}-{sample}'
    prefix.mkdir(parents=True,exist_ok=False)
    oldfolder=OLD/'D_native_thin'
    original=t.p.load(oldfolder/f'generation-{n}/first-consumer-input.json')
    actor=t.p.load(oldfolder/f'generation-{n}/actor.json')
    native=deepcopy(actor['pending_messages'][:len(original['messages'])])
    assert t.p.e.CLIENT._build_body(native,[],stream=False)['messages']==original['messages']
    changed=[]
    for idx,row in enumerate(native):
        text=row.get('content')
        if row['role']=='assistant' and isinstance(text,str):
            try:value=json.loads(text)
            except ValueError:continue
            if isinstance(value,dict) and set(value)=={'source_record'}:
                changed.append(idx)
                if role=='user':row['role']='user'
    assert changed
    task=t.ProductionTask(prefix,[],session=f'role-{n}-{role}-{sample}')
    stage=t.p.load(OLD/'scenario-private.json')[n-1]
    current=prefix/'inputs/current.json';current.parent.mkdir(parents=True)
    current.write_bytes(t.p.e.canonical(stage['data']).encode('utf-8'))
    allowed={'inputs/current.json','artifacts/result.json'}
    known_original=None
    for path in oldfolder.glob('sources.v-sha256-*.txt'):
        rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
        user_stages=[int((r.get('message_id') or r.get('id')).removeprefix('external-user-')) for r in rows
            if str(r.get('message_id') or r.get('id')).startswith('external-user-')]
        if user_stages and max(user_stages)>n:continue
        (prefix/path.name).write_bytes(path.read_bytes());allowed.add(path.name)
        if any((r.get('message_id') or r.get('id'))==stage['source_call_id']+'-receipt' for r in rows):
            known_original=rows
    assert known_original is not None
    recorded=next(r for r in known_original if (r.get('message_id') or r.get('id'))==stage['source_call_id']+'-receipt')
    assert t.p.e.canonical(stage['data']) in recorded['content'][0]['content']
    sink=RootMappedSink(oldfolder/'artifacts',prefix/'artifacts')
    if n>1:
        prior=oldfolder/f'generation-{n-1}/observed-result.json'
        if prior.exists():(sink.root/'result.json').write_bytes(prior.read_bytes())
    reader=MappedRead(task,oldfolder,allowed)
    tools=[sink.schema(),*reader.schemas()]
    model=t.p.ProviderFrameModel(None,t.p.e.CLIENT,'prepare',4096)
    body=model.body(native,tools)
    if role=='assistant':assert body==original
    else:
        compare=deepcopy(body)
        for idx in changed:compare['messages'][idx]['role']='assistant'
        assert compare==original
    return prefix,native,tools,reader,sink,body,stage,changed


async def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    plan={'scope':__doc__,'states':[1,6],'roles':['assistant','user'],'samples':2,'consumer_requests':6,
        'output_limit':4096,'http_retries':0,'new_handoff_calls':0,'only_change':'outer source_record carrier role',
        'source_run_sha256':t.p.sha((OLD/'run-report.json').read_bytes()),'code_sha256':t.p.sha(Path(__file__).read_bytes()),'inputs':[]}
    for n in (1,6):
        for role in ('assistant','user'):
            for sample in range(2):
                folder,msg,tools,reader,sink,body,stage,changed=setup(n,role,sample)
                t.p.e.write(folder/'messages.json',msg);t.p.e.write(folder/'first-input.json',body)
                t.p.e.write(folder/'allowed.json',sorted(reader.allowed))
                plan['inputs'].append({'stage':n,'role':role,'sample':sample,'folder':str(folder),'request_sha256':t.p.sha(body),'changed_indices':changed})
    folder,msg,tools,reader,sink,body,stage,_=setup(1,'assistant',9,free=True)
    original=OLD/'D_native_thin/inputs/current.json'
    result=await reader.execute(ToolUse('free-old','Read',{'file_path':str(original)}),AbortController())
    assert not result.is_error and t.p.e.canonical(stage['data']) in result.content
    denied=await reader.execute(ToolUse('free-private','Read',{'file_path':str(OLD/'scenario-private.json')}),AbortController())
    assert denied.is_error
    sink.call({'file_path':str(OLD/'D_native_thin/artifacts/result.json'),'content':'{}\n'})
    assert (sink.root/'result.json').read_bytes()==b'{}\n'
    plan['free_checks']={'old_file_time_restored_from_actual_receipt':True,'private_oracle_denied':True,'logical_write_isolated':True,'baseline_wire_exact':True,'candidate_only_outer_role':True}
    t.p.e.write(ROOT/'preflight-manifest.json',plan)
    print(t.p.e.canonical({'prepared':len(plan['inputs']),'checks':plan['free_checks']}),flush=True)


async def execute():
    plan=t.p.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists()
    assert plan['code_sha256']==t.p.sha(Path(__file__).read_bytes())
    t.p.e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=t.p.StopAwareCalls();calls.semaphore=asyncio.Semaphore(2)
    calls.report.update(protocol=plan,observations=[]);calls.save()
    sem=asyncio.Semaphore(2)
    async def one(item):
        async with sem:
            if getattr(calls,'evaluation_stopped',False):return
            rec={k:item[k] for k in ('stage','role','sample')};calls.report['observations'].append(rec)
            try:
                folder=Path(item['folder']);msg=t.p.load(folder/'messages.json')
                task=t.ProductionTask(folder,[],session='role-paid-'+str(item['stage'])+'-'+item['role']+'-'+str(item['sample']))
                sink=RootMappedSink(OLD/'D_native_thin/artifacts',folder/'artifacts')
                reader=MappedRead(task,OLD/'D_native_thin',set(t.p.load(folder/'allowed.json')))
                tools=[sink.schema(),*reader.schemas()]
                label=f"g{item['stage']}-{item['role']}-{item['sample']}"
                model=t.p.ProviderFrameModel(calls,t.p.e.CLIENT,label,4096)
                assert model.body(msg,tools)==t.p.load(folder/'first-input.json')
                state=new_state(msg)
                await actor_run(model,state,tools,sink,reader,additional_requests=6,
                    checkpoint=lambda v:t.p.e.write(folder/'actor.json',v))
                expected=t.p.load(OLD/'scenario-private.json')[item['stage']-1]
                grade=actor_grade(sink,expected['expected_artifact'])
                answer,_=t.p.parse(state.get('answer') or '')
                state_grade={k:type(answer.get(k)) is type(v) and answer[k]==v for k,v in expected['expected_state'].items()}
                rec.update(artifact_score=grade,state_score=state_grade,state_correct=sum(state_grade.values()),
                    actual_tool_calls=len(state['activity']),consumer_calls=state['requests_attempted'],
                    answer=state.get('answer'),success=all(state_grade.values()) and grade['task_success'])
            except t.p.EvaluationStop:rec['error']='evaluation_stopped'
            except Exception as exc:rec['error']=type(exc).__name__+': '+str(exc)[:500]
            finally:calls.save();print(t.p.e.canonical(rec),flush=True)
    await asyncio.gather(*(one(x) for x in plan['inputs']))
    calls.report['completed']=True;calls.report['cost_estimate_cny']=sum(x['cost_estimate'] for x in calls.report['calls']);calls.save()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(prepare() if sys.argv[1]=='prepare' else execute())
