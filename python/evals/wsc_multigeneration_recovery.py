"""338 own-output A1/WSC chains and withheld, matched full-source cold probes."""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import evals.wsc_cold_recovery_diagnostic as d
from evals.wsc_generated_recovery import system_for
from evals.wsc_observation_role_chain import idempotent_grade
from memory.wsc_semantic_evidence import publish as publish_evidence
from memory.wsc_semantic_generation import generate
from memory.wsc_semantic_originals import from_store
from memory.working import flush
from prompt.assembler import PromptAssembler

p, t = d.p, d.trial.t
ROOT = d.ROOT.parent / 'wsc-multigeneration-recovery-338'
ARMS = ('A1', 'wsc')


def stages():
    events = t.scenario()
    events[0]['request'] += '产物和最终状态对象仅含约定字段，不增加其他字段。'
    for n in range(11, 15):
        event = deepcopy(events[9])
        data = dict(batch_id='transit-coral', revision=n-6, file_version=1,
                    total_bytes=700000+n*5317, delivered_bytes=100000+n*2711,
                    lane='amber-'+str(n), checksum_label='check-'+str(401+n*17))
        call = 'current-read-'+str(n)
        event.update(stage=n, refresh=True, data=data, source_call_id=call,
                     restart_before=n in (12,14), checkpoint=False,
                     request=f'继续当前verification/full清单工作，current.json更新为revision={n-6}、file_version=1。其他状态与长期边界不变。')
        event['expected_artifact'] = {k:data[k] for k in ('batch_id','revision','file_version','lane','checksum_label')}
        event['expected_artifact'].update(source_call_id=call, remaining_bytes=data['total_bytes']-data['delivered_bytes'])
        events.append(event)
    return events


def probes():
    return [
        dict(name='early_archive', call='bootstrap-2', expected=dict(source_call_id='bootstrap-2',
             batch_id='archived-2', revision=2, file_version=1, total_bytes=1201942,
             delivered_bytes=402, lane='archive', checksum_label='archived-2')),
        dict(name='superseded', call='current-read-1', expected=dict(source_call_id='current-read-1',
             batch_id='transit-coral', revision=1, file_version=1, total_bytes=705317,
             delivered_bytes=102711, lane='amber-1', checksum_label='check-418')),
        dict(name='late_identity', call='late-read', expected=dict(source_call_id='late-read',
             batch_id='transit-coral', revision=0, file_version=1, total_bytes=9999999,
             delivered_bytes=0, lane='old', checksum_label='obsolete'))]


def texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value: yield from texts(child)
    elif isinstance(value, dict):
        for child in value.values(): yield from texts(child)


def evidence(task):
    objects = set()
    _, entrance = publish_evidence(task.source(), int(task.working.compact_cursor or 0),
        task.working, task.root, original_rows=from_store(task.store), evidence_paths=objects)
    return dict(objects=sorted(objects)), entrance


def incoming_view(task, pending):
    # The canonical store still owns invocation identity after A1 removes it
    # from hot history. Normalize arrivals against that store, not an orphan
    # receipt alone; retain_users still sees original roles, not this view.
    from session.late_result_projection import project
    projected = {row.get('message_id') or row.get('id'):row for row in project(task.source())}
    return [projected.get(row.get('message_id') or row.get('id'),row) for row in pending]


async def consume(calls, task, history, system, publication, label, query, expected, artifact_root):
    sink = t.ExactArtifactSink(artifact_root)
    artifact = sink.root/'result.json'
    before = p.sha(artifact.read_bytes()) if artifact.is_file() else None
    reader = d.Reader(task, publication)
    reader.paths.update(path.resolve() for path in (task.root/'inputs').glob('*.json'))
    reader.paths.add(artifact.resolve())
    facts = dict(artifact_root=str(sink.root), read_scope='已发布证据文件、inputs内JSON文件和result.json；目录枚举未开放')
    messages = PromptAssembler().build(system, [*deepcopy(history), dict(role='user', content=p.e.canonical(facts)),
                                               dict(role='user', content=query)])
    tools = [sink.schema(), *reader.schemas()]
    model = p.ProviderFrameModel(calls, p.e.CLIENT, label, 2048)
    body = model.body(messages, tools)
    d.trial.validate_wire(body)
    folder = ROOT/'observations'/label
    folder.mkdir(parents=True,exist_ok=True)
    p.e.write(folder/'input.json', body)
    state = t.new_state(messages)
    await t.actor_run(model, state, tools, sink, reader, additional_requests=6,
                     checkpoint=lambda value:p.e.write(folder/'actor.json',value))
    score = idempotent_grade(sink, expected, before)
    answer, _ = p.parse(state.get('answer') or '')
    if artifact.is_file():
        p.e.write(folder/'artifact-bytes.json', dict(utf8=artifact.read_text(encoding='utf-8')))
    result = dict(task_success=score['task_success'], score=score, answer=answer,
                  requests=state['requests_attempted'], phase=state['phase'], activity=state['activity'],
                  hot_reference_tokens=p.e.tokens(PromptAssembler().build('',history)),
                  request_reference_tokens=p.e.tokens(messages, tools))
    p.e.write(folder/'result.json', result)
    return result, state['pending_messages'][len(messages):]


async def branch(calls, arm):
    root = ROOT/'workspaces'/arm
    task = t.ProductionTask(root, [], session='recovery338-'+arm)
    await t.bootstrap(task)
    system = await system_for(root)
    hot, pending, delayed = [], deepcopy(task.source()), None
    publications, folds = [], 0
    for event in stages():
        n = event['stage']
        record = dict(arm=arm, event=n, published=False, actual_folds=folds)
        calls.report['events'].append(record)
        if event['restart_before']:
            task.persist(); flush(task.working.session_id, task.working)
            before = task.project(); task = task.restart()
            assert task.project() == before
            record['restart_equal'] = True
        events = [dict(id='external-user-'+str(n), role='user', content=event['request'])]
        t.append(task, events)
        if n == 1:
            old = root/'inputs/late-old.json'
            old.write_text(p.e.canonical({k:v for k,v in probes()[2]['expected'].items() if k!='source_call_id'}),encoding='utf-8')
            inv, delayed = await t.execute_read(task,'late-read',old,late=True)
            t.append(task,[inv]); events.append(inv)
        if event['refresh']:
            path = root/'inputs/current.json'
            path.write_text(p.e.canonical(event['data']),encoding='utf-8')
            inv, receipt = await t.execute_read(task,event['source_call_id'],path)
            t.append(task,[inv,receipt]); events.extend([inv,receipt])
        if n == 3:
            t.append(task,[delayed]); events.append(delayed)
        pending.extend(deepcopy(events))
        source = deepcopy(task.source())
        visible = PromptAssembler().build(system,[*hot,*incoming_view(task,pending)] if arm=='A1' else task.project())
        model = p.ProviderFrameModel(calls,p.e.CLIENT,f'{arm}-e{n}-generation',4096)
        cursor_before = int(task.working.compact_cursor or 0)
        try:
            if arm == 'A1':
                summary = await generate(model,visible,d.AbortController(),account=lambda _:None)
                hot = t.retain_users(hot,pending,summary)
                record['published'] = True
            else:
                candidate = await d.semantic.prepare(model=model,messages=visible,source=task.source,
                    working=task.working,abort=d.AbortController(),account=lambda _:None,persist=task.persist,
                    cwd=root,original_source=lambda:from_store(task.store))
                if candidate is not None:
                    hot = d.semantic.publish(candidate,task.source(),task.working,cwd=root)
                    record['published'] = True
                else:
                    hot = task.project()
        except p.EvaluationStop:
            raise
        except Exception as exc:
            if not d.semantic.resumable_failure(exc) or task.source()!=source: raise
            record['generation_failure'] = str(exc)
            if arm!='A1':hot=task.project()
        if record['published']:
            pending=[]; folds+=1
        record.update(actual_folds=folds,cursor_before=cursor_before,cursor_after=int(task.working.compact_cursor or 0),
                      generation_requests=model.state['counter'])
        if arm=='wsc' and record['published']:
            assert record['cursor_after'] > cursor_before
        if arm=='A1':
            publication, entrance = evidence(task)
            history = [*hot,*incoming_view(task,pending),dict(role='user',content=entrance)]
        else:
            publication = p.load(d.heads.path_for(task.working.session_id))['publication']
            history = hot
        object_hashes = {path:p.sha(Path(path).read_bytes()) for path in publication['objects']}
        publications.append(object_hashes)
        headpath = d.heads.path_for(task.working.session_id)
        frozen = headpath.read_bytes() if arm=='wsc' else None
        result, actual = await consume(calls,task,history,system,publication,f'{arm}-e{n}-task',
            '继续当前这一轮工作；最终回复使用此前约定的状态JSON。', event['expected_artifact'],root/'artifacts')
        record.update(result)
        record['state_correct'] = sum(type(result['answer'].get(k)) is type(v) and result['answer'][k]==v
                                      for k,v in event['expected_state'].items())
        record['state_total'] = len(event['expected_state'])
        t.append(task,actual);pending.extend(deepcopy(actual))
        assert frozen is None or headpath.read_bytes()==frozen
        assert all(p.sha(Path(path).read_bytes())==sha for path,sha in object_hashes.items())
        record['frozen_equal'] = True
        calls.save()
        print(json.dumps({k:record[k] for k in ('arm','event','actual_folds','task_success','state_correct')},ensure_ascii=False),flush=True)
    task.persist();flush(task.working.session_id,task.working)
    before=task.project();task=task.restart();assert task.project()==before
    # Capture before the withheld questions; neither probe answers nor gold enter the chain.
    hot_history = [*hot,*incoming_view(task,pending)] if arm=='A1' else task.project()
    publication, entrance = evidence(task)
    if arm=='A1':hot_history.append(dict(role='user',content=entrance))
    else:
        prior = p.load(d.heads.path_for(task.working.session_id))['publication']['objects']
        publication['objects'] = sorted(set(publication['objects']).union(prior))
    for spec in probes():
        fields=', '.join(spec['expected'])
        query=(f"本轮只审计历史Read调用{spec['call']}当时返回的JSON资料，不重开历史任务、不把旧版本当当前值。"
               f'仅写入这些字段：{fields}；source_call_id为该Read的调用ID。保存到artifact_root/result.json。完成后简短回复。')
        for condition,history in [('compressed',hot_history),('full',[*task.source(),dict(role='user',content=entrance)])]:
            label=f'{arm}-{spec["name"]}-{condition}'
            result,_=await consume(calls,task,history,system,publication,label,query,spec['expected'],ROOT/'probe-artifacts'/label)
            needles=[spec['call'],spec['expected']['checksum_label']]
            needed=not all(value in '\n'.join(texts(history)) for value in needles)
            reads=[a for a in result['activity'] if a['tool'] in ('Read','Grep')]
            seen=any(not a['is_error'] and all(value in '\n'.join(texts(a['result'])) for value in needles) for a in reads)
            row=dict(arm=arm,case=spec['name'],condition=condition,cold_needed=needed,read_calls=len(reads),
                     read_errors=sum(a['is_error'] for a in reads),source_seen=seen,
                     effective_recovery=bool(seen and result['task_success']) if needed else None,**result)
            calls.report['probes'].append(row);calls.save()
            print(json.dumps({k:row[k] for k in ('arm','case','condition','task_success','cold_needed','effective_recovery')},ensure_ascii=False),flush=True)
    assert all(p.sha(Path(path).read_bytes())==sha for objects in publications for path,sha in objects.items())


async def main(mode):
    p.e.ROOT=ROOT
    p.e.CLIENT=d.CountedClient(api_key='not-sent',model='deepseek-flash',thinking='disabled')
    if mode=='prepare':
        assert not ROOT.exists(), 'Fresh evidence directory required'
        ROOT.mkdir(parents=True)
        from memory.wsc_semantic_generation import PROMPT
        assert PROMPT.strip()==t.PROMPT.strip()
        plan=dict(scope=__doc__,arms=ARMS,events=14,consumer_requests=6,http_retries=0,per_call_cny_max=2.5,
                  proposed_new_run_cost_ceiling_cny=2,model='deepseek-flash',generation_max_tokens=4096,consumer_max_tokens=2048,
                  code_sha256=p.sha(Path(__file__).read_bytes()),prompt_sha256=p.sha(t.PROMPT.encode()),
                  reviews='docs/wsc-multigeneration-recovery-plan-2026-10-15.md',
                  dependencies={str(Path(module.__file__)):p.sha(Path(module.__file__).read_bytes())
                                for module in (d,d.trial,t,p,d.semantic)},
                  baseline='A1 public-local prompt and 20k approximate retained users; equal readonly evidence, not Codex product',
                  actual_folds='count accepted publications, not events',probes='withheld until after all14 events; full-source matched probes')
        p.e.write(ROOT/'preflight-manifest.json',plan)
        p.e.write(ROOT/'private-scenario.json',dict(events=stages(),probes=probes()))
        print(json.dumps(plan),flush=True);return
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun'
    plan=p.load(ROOT/'preflight-manifest.json');assert plan['code_sha256']==p.sha(Path(__file__).read_bytes())
    assert all(p.sha(Path(path).read_bytes())==sha for path,sha in plan['dependencies'].items())
    calls=d.DiagnosticCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol=plan,scope=__doc__,events=[],probes=[])
    with t.environment(ROOT):
        os.environ.update(XEYO_WSC='1',XEYO_WSC_HEAD_STORE='1',XEYO_WSC_SEMANTIC_HANDOFF='1',WSC_AD_TRANSPORT='httpx-direct')
        for arm in ARMS:await branch(calls,arm)
    calls.report['completed']=True
    calls.report['cost_estimate_cny']=sum(row['cost_estimate'] for row in calls.report['calls'])
    calls.save()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run'])
    asyncio.run(main(parser.parse_args().mode))
