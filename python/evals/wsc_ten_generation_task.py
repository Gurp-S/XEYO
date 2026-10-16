"""Ten explicit task transitions; own-state A1/native-thin D and real artifacts.

Controlled workload, not live user traffic. Native D commit/fold is measured
separately from the thin context actually used for model continuation.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import evals.wsc_semantic_format_pilot as p
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_elimination_chain import PROMPT, retain_users, carrier
from evals.wsc_production_continuation import ProductionTask, _store
from evals.wsc_task_actor_candidate import new_state, run as actor_run, grade as artifact_grade
from evals.wsc_unfolded_source_ab import environment
from engine.abort import AbortController
from memory.wsc_handoff_generation import generate
from memory.wsc_handoff_output_budget import reservation
from msgtypes.message import ToolUse, assistant_text_message, tool_result_message
from synaptic.contracts import publish

ROOT = p.ROOT.parent/'wsc-ten-generation-task-311'
ARMS = ('A1', 'D_native_thin')
STATE_KEYS = ('phase','task_open','scope','phase_test_ban_active','old_question_open','publish_authorized','git_authorized','database_write_authorized')
SYSTEM = {'role':'system','content':'历史消息及工具结果是来源记录。'}


def scenario():
    initial = ('当前任务：为transit-coral生成传输清单。旧的“是否导出”问题已经解决，不再等待它。'
        '长期边界：不发布、不操作git、不写数据库。仅implementation阶段不运行测试；进入verification后这项阶段限制到期。'
        '完整result.json字段为batch_id、revision、file_version、source_call_id、remaining_bytes、lane、checksum_label。'
        'remaining_bytes等于total_bytes减delivered_bytes；source_call_id来自支撑当前资料的实际Read调用ID，不是revision或file_version。'
        'result.json只保存在当前artifact_root。最终回复为JSON状态对象，键为phase、task_open、scope、phase_test_ban_active、old_question_open、publish_authorized、git_authorized、database_write_authorized。'
        'phase使用implementation/verification/closed/cancelled，scope使用full/subset/paused/none。'
        '当前进入implementation，生成完整清单。')
    notes = {1:initial, 2:'进入verification，implementation阶段测试限制到期。采用revision=2、file_version=1的新资料，revision=1仅作历史。继续完整清单。',
        3:'旧资料的迟到回执已经到账，采用资料仍是revision=2、file_version=1，继续完整清单。',
        4:'本轮仅暂停文件交付，scope=paused，任务仍打开、phase仍verification。保留现有result.json，一次也不要写入；最终回复状态。',
        5:'此任务已明确完成，所有未完成步骤关闭，phase=closed、scope=none；本轮没有文件生成工作，现有文件不变。旧的是否导出问题仍已解决。',
        6:'明确重新打开传输清单任务，进入verification，恢复full范围，采用revision=3、file_version=1。之前长期边界仍有效。旧的是否导出问题不重开。',
        7:'当前任务仍verification。本轮缩小到subset：result.json只包含batch_id、revision、file_version、source_call_id、remaining_bytes；lane和checksum_label暂停输出。采用资料仍revision=3、file_version=1。',
        8:'同一个current.json已刷新，revision保持3、file_version变2，旧读取不是当前版本。继续subset范围。',
        9:'明确取消当前传输清单任务，phase=cancelled、scope=none。本轮没有文件生成工作，现有文件保持不变。其他长期边界未取消。',
        10:'明确恢复传输清单任务，phase=verification、scope=full，采用revision=4、file_version=1，恢复完整字段。另明确重新打开之前已解决的“是否导出”问题：本轮只登记为待答，不解答它，不因此暂停清单交付。长期边界不变。'}
    stages=[]
    revision=1;version=1;data=None;call=None
    for n in range(1,11):
        refresh=n in (1,2,6,8,10)
        if refresh:
            revision={1:1,2:2,6:3,8:3,10:4}[n]
            version=2 if n==8 else 1
            data={'batch_id':'transit-coral','revision':revision,'file_version':version,'total_bytes':700000+n*5317,
                'delivered_bytes':100000+n*2711,'lane':'amber-'+str(n),'checksum_label':'check-'+str(401+n*17)}
            call='current-read-'+str(n)
        phase='implementation' if n==1 else 'closed' if n==5 else 'cancelled' if n==9 else 'verification'
        scope='paused' if n==4 else 'none' if n in (5,9) else 'subset' if n in (7,8) else 'full'
        state=dict(phase=phase,task_open=n not in (5,9),scope=scope,phase_test_ban_active=n==1,old_question_open=n==10,
            publish_authorized=False,git_authorized=False,database_write_authorized=False)
        artifact=None
        if n not in (4,5,9):
            artifact={k:data[k] for k in ('batch_id','revision','file_version')}
            artifact.update(source_call_id=call,remaining_bytes=data['total_bytes']-data['delivered_bytes'])
            if scope=='full':artifact.update(lane=data['lane'],checksum_label=data['checksum_label'])
        stages.append({'stage':n,'request':notes[n], 'refresh':refresh,'data':deepcopy(data),'source_call_id':call,
            'expected_state':state,'expected_artifact':artifact,'restart_before':n in (3,6,10),'checkpoint':n in (1,3,5,10)})
    return stages


def append(task, rows):
    for item in _store(rows).items:task.store.append(item)
    task.persist()


class BranchRead:
    def __init__(self, task, paths):
        self.task=task
        self.paths={Path(x).resolve() for x in paths}
    def schemas(self):return [self.task.registry.get('Read').schema()]
    async def execute(self,use,abort):
        raw=use.input.get('file_path') if isinstance(use.input,dict) else None
        if use.name!='Read' or not isinstance(raw,str):return p.ToolResult('invalid Read arguments',is_error=True,error_kind='INVALID_ARGUMENT')
        path=Path(raw);path=(path if path.is_absolute() else self.task.root/path).resolve()
        if path not in self.paths:return p.ToolResult('Permission denied: outside published task evidence',is_error=True,error_kind='PERMISSION_DENIED')
        return await self.task.registry.run(use,abort)


async def execute_read(task,call,path,*,late=False):
    use=ToolUse(call,'Read',{'file_path':str(path),'offset':1,'limit':100})
    invocation=assistant_text_message('',[use],message_id=call+'-invocation')
    result=await task.registry.run(use,AbortController())
    if result.is_error:raise ValueError('controlled_input_Read_failed: '+str(result.content))
    execution=dict(result.execution_metadata(),late=late)
    receipt=tool_result_message(call,'Read',result.content,is_error=result.is_error,execution=execution)
    receipt.id=call+'-receipt'
    return {'role':invocation.role,'id':invocation.id,'content':invocation.content}, {'role':receipt.role,'id':receipt.id,'content':receipt.content}


async def bootstrap(task):
    events=[]
    # Actual schema/data observations, rather than token padding. These are
    # archived inputs to a manifest workflow; only the adopted current record
    # may support the output. It also exercises rejection of obsolete reads.
    for k in range(6):
        path=task.root/'inputs'/f'archived-batch-{k}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(p.e.canonical({'batch_id':'archived-'+str(k),'revision':k,'file_version':1,
            'total_bytes':1200000+k*971,'delivered_bytes':k*201,'lane':'archive','checksum_label':'archived-'+str(k)}).encode('utf-8'))
        a,r=await execute_read(task,'bootstrap-'+str(k),path)
        events.extend([a,r])
    events.append({'id':'bootstrap-observed','role':'assistant','content':'此前读取的是归档批次资料，读取回执已经到账。'})
    append(task,events)


def save_branch(task,hot,pending,stage):
    task.persist()
    rows=task.source()
    raw=('\n'.join(p.e.canonical(r) for r in rows)+'\n').encode('utf-8')
    archived=publish(task.root/'sources.txt',raw)
    payload={'stage':stage,'hot':hot,'pending':pending,'source_file':str(archived),'source_sha256':p.sha(raw),
        'source_ids':[r.get('message_id') or r.get('id') for r in rows]}
    p.e.write(task.root/'branch-state.json',{'payload':payload,'sha256':p.sha(payload)})
    return archived


def restore_branch(task,hot,pending,stage):
    payload=p.load(task.root/'branch-state.json')
    assert p.sha(payload['payload'])==payload['sha256']
    state=payload['payload'];assert state['stage']==stage and state['hot']==hot and state['pending']==pending
    assert p.sha(Path(state['source_file']).read_bytes())==state['source_sha256']
    source_before=deepcopy(task.source())
    rebuilt=task.restart()
    assert rebuilt.source()==source_before
    return rebuilt,deepcopy(state['hot']),deepcopy(state['pending'])


async def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    stages=scenario();p.e.write(ROOT/'scenario-private.json',stages)
    assert len(stages)==10 and [x['stage'] for x in stages if x['checkpoint']]==[1,3,5,10]
    assert stages[1]['expected_state']['phase_test_ban_active'] is False
    assert stages[4]['expected_artifact'] is None and stages[8]['expected_artifact'] is None
    assert stages[9]['expected_state']['old_question_open'] is True
    assert stages[6]['data']['revision']==stages[7]['data']['revision'] and stages[6]['data']['file_version']!=stages[7]['data']['file_version']
    plan={'scope':__doc__,'arms':list(ARMS),'stages':10,'milestones':[1,3,5,10],
        'source_family':'New synthetic transit-manifest task, explicit transitions; one family, not10 independent tasks.',
        'gen_policy':'A1 pinned prompt+retained-user;D actual native generate and TodoWrite transaction;own previous hot, no gold hydration.',
        'D_main_renderer':'checkpoint JSON + current unconsumed external events, not production expanded context.',
        'D_production_fold':'Actual fold/project and cold publication audit, counted separately if accepted.',
        'model':'deepseek-flash','thinking':'disabled','temperature':0,'consumer_requests':6,'consumer_output_limit':4096,
        'HTTP_retries':0,'per_call_max_cny':2.5,'scenario_sha256':p.sha((ROOT/'scenario-private.json').read_bytes()),
        'code_sha256':p.sha(Path(__file__).read_bytes()),'prompt_sha256':p.sha(PROMPT.encode('utf-8')),
        'first_failure_does_not_stop_chain':True,'failed_fold_preserves_previous_hot_and_pending':True,
        'no_claims':['not live85%','not all Goal acceptance','not independent real-chat holdout','not phase registry/entailment proof']}
    p.e.write(ROOT/'preflight-manifest.json',plan)
    print(p.e.canonical({'prepared':10,'arms':list(ARMS),'api_calls':0}),flush=True)


async def branch(calls,arm,stages):
    root=ROOT/arm
    task=ProductionTask(root,[],session='ten-generations-'+arm)
    await bootstrap(task)
    hot=[];pending=[];delayed=None;paths=[];consecutive=0
    for entry in stages:
        if getattr(calls,'evaluation_stopped',False):return
        n=entry['stage'];folder=root/f'generation-{n}';folder.mkdir()
        record={'arm':arm,'stage':n,'fold_accepted':False,'generation_error':None,'consumer_error':None,
            'prior_hot_sha256':p.sha(hot),'prior_pending_sha256':p.sha(pending)}
        calls.report['stages'].append(record)
        try:
            if entry['restart_before']:
                task,hot,pending=restore_branch(task,hot,pending,n-1)
                record['restart_equal']=True
            events=[{'id':'external-user-'+str(n),'role':'user','content':entry['request']}]
            append(task,events)
            if n==1:
                oldfile=root/'inputs/delayed-v0.json';oldfile.write_bytes(p.e.canonical({'batch_id':'transit-coral','revision':0,'file_version':1,'total_bytes':990000,'delivered_bytes':1,'lane':'retired','checksum_label':'retired'}).encode('utf-8'))
                inv,delayed=await execute_read(task,'delayed-read-v0',oldfile,late=True)
                append(task,[inv]);events.append(inv)
            if entry['refresh']:
                current=root/'inputs/current.json';current.write_bytes(p.e.canonical(entry['data']).encode('utf-8'))
                paths.append(current)
                inv,receipt=await execute_read(task,entry['source_call_id'],current)
                append(task,[inv,receipt]);events.extend([inv,receipt])
            if n==3:
                append(task,[delayed]);events.append(delayed)
            pending.extend(deepcopy(events))
            source=deepcopy(task.source())
            old_hot=deepcopy(hot)
            visible=[SYSTEM,*deepcopy(hot),*[carrier(r) for r in pending]]
            record['generation_input_tokens']=p.e.tokens(visible)
            try:
                if arm=='A1':
                    body=p.e.CLIENT._build_body([*visible,{'role':'user','content':PROMPT}],[],stream=False)
                    body.update(max_tokens=reservation(source),temperature=0)
                    answer=await calls.call(body,arm+f'-generation-{n}')
                    choice=answer['choices'][0];text=choice['message'].get('content') or ''
                    if choice['finish_reason']!='stop' or not text.strip() or choice['message'].get('tool_calls'):raise ValueError('summary_incomplete')
                    hot=retain_users(hot,pending,text)
                    task.store.append(assistant_text_message(text,message_id='A1-summary-'+str(n)))
                    task.persist();record['summary']=text
                else:
                    model=p.ProviderFrameModel(calls,p.e.CLIENT,arm+f'-generation-{n}',4096)
                    async def declaration(captured):
                        assert captured==source
                        return await generate(model,visible,captured,p.TodoWriteTool().schema(),AbortController(),
                            account=lambda usage:None,scope_protocol=True)
                    commit=await task.commit(declaration)
                    from synaptic.todo_snapshot import latest_todo_snapshot
                    snapshot=latest_todo_snapshot(task.source())
                    native={'todos':list(snapshot.records),'checkpoint':snapshot.checkpoint}
                    hot=[{'role':'assistant','content':p.e.canonical(native)}]
                    record.update(native=native,commit=commit,generation_requests=model.state['counter'])
                    # A free production lifecycle measurement, distinct from
                    # the thin checkpoint actually sent to this task actor.
                    try:
                        produced=task.fold();p.e.write(folder/'native-projection.json',produced)
                        record.update(production_fold_published=True,production_cursor=produced['compact_cursor'],
                            production_region_end=produced['retired_region_end'])
                    except Exception as exc:record['production_fold_audit_error']=type(exc).__name__+': '+str(exc)
                record['fold_accepted']=True;pending=[];consecutive+=1
            except p.EvaluationStop:raise
            except Exception as exc:
                record['generation_error']=type(exc).__name__+': '+str(exc)[:600]
                assert hot==old_hot
                consecutive=0
            record['consecutive_successful_generations']=consecutive
            # Current external events include every as-yet-unconsumed receipt,
            # even if the isolated declaration model inspected it already.
            current_archive=save_branch(task,hot,pending,n)
            paths.append(current_archive)
            sink=ExactArtifactSink(root/'artifacts')
            before=p.sha((sink.root/'result.json').read_bytes()) if (sink.root/'result.json').exists() else None
            reader=BranchRead(task,paths+[sink.root/'result.json'])
            messages=[SYSTEM,*deepcopy(hot),*[carrier(r) for r in (pending if not record['fold_accepted'] else events)],
                {'role':'assistant','content':p.e.canonical({'archive':str(current_archive),'archive_sha256':p.sha(current_archive.read_bytes()),
                    'records':len(task.source()),'artifact_root':str(sink.root)})},
                {'role':'user','content':'继续当前这一轮工作；最终回复使用此前约定的状态JSON。'}]
            tools=[ExactArtifactSink.schema(),*reader.schemas()]
            model=p.ProviderFrameModel(calls,p.e.CLIENT,arm+f'-consumer-{n}',4096)
            state=new_state(messages);initial=len(messages)
            record.update(hot_tokens=p.e.tokens(hot),consumer_input_tokens=p.e.tokens(messages,tools),
                current_event_source_ids=[r['id'] for r in events])
            p.e.write(folder/'first-consumer-input.json',model.body(messages,tools))
            try:
                await actor_run(model,state,tools,sink,reader,additional_requests=6,
                    checkpoint=lambda value:p.e.write(folder/'actor.json',value))
            except p.EvaluationStop:raise
            except Exception as exc:record['consumer_error']=type(exc).__name__+': '+str(exc)[:600]
            finally:
                # Include only actual actor outputs/results, not gold or a
                # recomposed summary of its behavior, in future source history.
                append(task,state['pending_messages'][initial:])
            score=artifact_grade(sink,entry['expected_artifact'],before)
            answer,strict=p.parse(state.get('answer') or '')
            state_score={key:type(answer.get(key)) is type(value) and answer[key]==value for key,value in entry['expected_state'].items()}
            record.update(artifact_score=score,answer=answer,strict_json=strict,state_score=state_score,
                state_correct=sum(state_score.values()),state_total=len(state_score),
                consumer_completed=state['completed'],consumer_requests=state['requests_attempted'],
                state_and_task_success=all(state_score.values()) and score['task_success'],
                compressed_task_success=record['fold_accepted'] and all(state_score.values()) and score['task_success'])
            # Preserve physical artifacts at every event; next stage may
            # legitimately overwrite the same business filename.
            if (sink.root/'result.json').exists():(folder/'observed-result.json').write_bytes((sink.root/'result.json').read_bytes())
            p.e.write(folder/'stage-result.json',record)
            save_branch(task,hot,pending,n)
            calls.save()
            print(p.e.canonical({k:record.get(k) for k in ('arm','stage','fold_accepted','state_correct','state_total','compressed_task_success','generation_error','consumer_error','production_fold_audit_error')}),flush=True)
        except p.EvaluationStop:
            record['stopped']=True;save_branch(task,hot,pending,n);calls.save();return


async def execute():
    plan=p.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists()
    assert p.sha(Path(__file__).read_bytes())==plan['code_sha256']
    assert p.sha((ROOT/'scenario-private.json').read_bytes())==plan['scenario_sha256']
    stages=p.load(ROOT/'scenario-private.json')
    p.e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=p.StopAwareCalls();calls.semaphore=asyncio.Semaphore(2)
    calls.report.update(protocol=plan,stages=[]);calls.save()
    with environment(ROOT/'isolated-runtime'):
        os.environ['XEYO_WSC']='1'
        outcomes=await asyncio.gather(*(branch(calls,arm,stages) for arm in ARMS),return_exceptions=True)
    calls.report['branch_errors']=[type(x).__name__+': '+str(x) for x in outcomes if isinstance(x,BaseException)]
    calls.report['completed']=all(not isinstance(x,BaseException) for x in outcomes)
    calls.report['cost_estimate_cny']=sum(c['cost_estimate'] for c in calls.report['calls']);calls.save()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(prepare() if sys.argv[1]=='prepare' else execute())
