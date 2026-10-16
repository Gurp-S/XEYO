"""337 actual semantic generation, restart and artifact-based recovery tasks."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

import evals.wsc_cold_recovery_diagnostic as d
from memory.wsc_semantic_originals import from_store
from prompt.assembler import PromptAssembler

p, trial = d.p, d.trial
ROOT = d.ROOT.parent / 'wsc-generated-recovery-337'
REAL = d.ROOT.parent / 'wsc-semantic-format-307/completed_waiting_authority/case-private.json'


def datasets():
    result = []
    for case in d.cases():
        archived = [dict(record_id=f"archive-{case['name']}-{i}",
                         code=hashlib.sha256(f"337:{case['name']}:{i}".encode()).hexdigest()[:14],
                         sample_count=103 + i * 97) for i in range(60)]
        rows = [dict(id=f'archive-{i}', role='user', content='已结案的历史登记：'+p.e.canonical(record))
                for i, record in enumerate(archived)]
        if case.get('old'):
            rows[10] = dict(id='old-config', role='user', content=case['old'])
        rows[37] = dict(id=case['target_id'], role='user', content=case['source'])
        rows.append(dict(id='current', role='user', content=case['request']))
        history = archived[17]
        result.append(dict(name=case['name'], kind='controlled', rows=rows, tasks=[
            dict(name='current', query=case['query'], expected=case['expected'], needles=case['needles']),
            dict(name='historical', query=f"本轮只核对已结案登记{history['record_id']}，不重开旧任务。返回record_id、code、sample_count。",
                 expected=history, needles=[history['code']])]))
    original = p.load(REAL)
    rows = original['rows']
    body = rows[2]['content'][0]['content']
    excerpt = '\n'.join(body.splitlines()[:3])
    result.append(dict(name='real_gui', kind='real_transcript', rows=rows,
                       original_file=str(REAL), original_sha256=p.sha(REAL.read_bytes()), tasks=[
        dict(name='current', query='只审阅原会话的最终修复报告，不执行历史命令。返回reported_regression_passed、reported_regression_skipped、full_vitest_all_passed、git_commit_reported。前两项是定向回归数字，后两项是布尔值。',
             expected=dict(reported_regression_passed=29, reported_regression_skipped=1,
                           full_vitest_all_passed=False, git_commit_reported=False), needles=[]),
        dict(name='historical', query='只核对历史Bash调用call_00_9igJQ7SnHuGsW4iDy9ck6350的原始工具回执。返回excerpt：正文解码后的前三个完整行，行间保留换行，不加末尾换行；不执行该历史命令。',
             expected=dict(excerpt=excerpt), needles=[excerpt])]))
    return result


async def system_for(root):
    return await PromptAssembler().build_system(cwd=str(root), workspace_root=str(root),
        model='deepseek-flash', tool_names=['Read', 'Grep', 'ArtifactWrite'])


def task_messages(system, history, spec, artifact_root):
    query = (spec['query'] + '\n将这个JSON对象保存到artifact_root下的result.json；完成后回复简短状态。')
    return PromptAssembler().build(system, [*deepcopy(history),
        dict(role='user', content='artifact_root='+str(artifact_root)), dict(role='user', content=query)])


async def prepare():
    assert not (ROOT/'preflight-manifest.json').exists(), 'Existing preflight'
    ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    with trial.t.environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_SEMANTIC_HANDOFF='1')
        for item in datasets():
            root = ROOT/item['name']
            task = d.ProductionTask(root, item['rows'], session='generated337-'+item['name'])
            task.persist()
            source = task.source()
            initial = task.project()
            assert task.working.compact_cursor == 0
            system = await system_for(root)
            generation_input = PromptAssembler().build(system, initial)
            # No future queries or expected answers are included here.
            model = p.ProviderFrameModel(None, p.e.CLIENT, 'preflight', 4096)
            trial.validate_wire(model.body(generation_input, []))
            prepared = dict(item=item, source=source, source_sha256=d.fingerprint(source),
                            initial=initial, system=system, generation_input=generation_input)
            p.e.write(root/'prepared-private.json', prepared)
            p.e.write(root/'generation-visible-input.json', generation_input)
            record = dict(name=item['name'], kind=item['kind'], source_count=len(source),
                          cut=d.semantic.boundary(source, task.working), source_sha256=d.fingerprint(source),
                          initial_reference_tokens=p.e.tokens(generation_input), source_reference_tokens=p.e.tokens(source))
            assert record['cut'] > 0
            records.append(record)
    plan = dict(scope=__doc__, cases=records, arms=['full', 'wsc'], consumer_max_requests=6,
                generation_output_tokens=4096, consumer_output_tokens=2048,
                http_retries=0, per_call_cny_max=2.5, proposed_new_run_cost_ceiling_cny=2,
                code_sha256=p.sha(Path(__file__).read_bytes()), dependency_sha256=p.sha(Path(d.__file__).read_bytes()),
                reviews='docs/wsc-generated-recovery-plan-2026-10-15.md',
                scope_limits=['one actual compression per source; no 10-generation or A1-comparison claim',
                              'three controlled cases and one existing real source; not an independent holdout',
                              'actual native generation/publication and read/write actor, not live query_loop'])
    p.e.write(ROOT/'preflight-manifest.json', plan)
    print(json.dumps(plan, ensure_ascii=False), flush=True)


async def consume(calls, task, publication, history, system, spec, arm, case, summary):
    root = ROOT/case
    reader = d.Reader(task, publication['publication'])
    sink = trial.t.ExactArtifactSink(root/'artifacts'/spec['name'])
    messages = task_messages(system, history, spec, sink.root)
    tools = [sink.schema(), *reader.schemas()]
    label = f"{case}-{spec['name']}-{arm}"
    model = p.ProviderFrameModel(calls, p.e.CLIENT, label, 2048)
    body = model.body(messages, tools)
    trial.validate_wire(body)
    p.e.write(root/(label+'-initial-input.json'), body)
    state = trial.t.new_state(messages)
    await trial.t.actor_run(model, state, tools, sink, reader, additional_requests=6,
                            checkpoint=lambda value: p.e.write(root/(label+'-actor.json'), value))
    score = trial.t.artifact_grade(sink, spec['expected'])
    output = sink.root/'result.json'
    saved = None
    if output.is_file():
        raw = output.read_bytes()
        (root/(label+'-artifact.json')).write_bytes(raw)
        try:
            saved = json.loads(raw)
        except ValueError:
            pass
    # Canonical JSON escapes newlines; search decoded source content, not JSON encoding.
    def texts(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for child in value: yield from texts(child)
        elif isinstance(value, dict):
            for child in value.values(): yield from texts(child)
    visible = '\n'.join(texts(history))
    cold_required = bool(spec['needles']) and not all(value in visible for value in spec['needles'])
    reads = [a for a in state['activity'] if a['tool'] in ('Read', 'Grep')]
    seen = any(not a['is_error'] and all(value in '\n'.join(texts(a['result'])) for value in spec['needles'])
               for a in reads) if spec['needles'] else None
    result = dict(case=case, task=spec['name'], arm=arm, task_success=score['task_success'],
                  artifact=score, output=saved, requests=state['requests_attempted'], phase=state['phase'],
                  read_calls=len(reads), read_errors=sum(a['is_error'] for a in reads),
                  required_literals_in_summary=all(value in summary for value in spec['needles']) if spec['needles'] else None,
                  cold_required=cold_required, source_seen=seen,
                  effective_recovery=bool(score['task_success'] and seen) if cold_required else None,
                  hot_reference_tokens=p.e.tokens(history), request_reference_tokens=p.e.tokens(messages, tools))
    calls.report['results'].append(result)
    calls.save()
    print(json.dumps(result, ensure_ascii=False), flush=True)


async def run():
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun'
    plan = p.load(ROOT/'preflight-manifest.json')
    assert plan['code_sha256'] == p.sha(Path(__file__).read_bytes())
    assert plan['dependency_sha256'] == p.sha(Path(d.__file__).read_bytes())
    calls = d.DiagnosticCalls()
    calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(protocol=plan, scope=__doc__, generations=[], results=[])
    with trial.t.environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_SEMANTIC_HANDOFF='1', WSC_AD_TRANSPORT='httpx-direct')
        for case in plan['cases']:
            name = case['name']
            root = ROOT/name
            prepared = p.load(root/'prepared-private.json')
            item = prepared['item']
            if item.get('original_file'):
                assert p.sha(Path(item['original_file']).read_bytes()) == item['original_sha256']
            task = d.ProductionTask(root, [], session='generated337-'+name).restart()
            assert d.fingerprint(task.source()) == prepared['source_sha256']
            assert task.project() == prepared['initial']
            model = p.ProviderFrameModel(calls, p.e.CLIENT, name+'-generation', 4096)
            candidate = await d.semantic.prepare(model=model, messages=prepared['generation_input'], source=task.source,
                working=task.working, abort=d.AbortController(), account=lambda _: None,
                persist=task.persist, cwd=root, original_source=lambda: from_store(task.store))
            assert candidate is not None
            hot = d.semantic.publish(candidate, task.source(), task.working, cwd=root)
            publication = p.load(d.heads.path_for(task.working.session_id))
            restarted = task.restart()
            assert restarted.project() == hot
            task = restarted
            frozen = d.heads.path_for(task.working.session_id).read_bytes()
            objects = {path: p.sha(Path(path).read_bytes()) for path in publication['publication']['objects']}
            generation = dict(case=name, cut=candidate['cut'], requests=model.state['counter'],
                              summary=candidate['text'], summary_reference_tokens=p.e.tokens([dict(role='assistant',content=candidate['text'])]),
                              hot_reference_tokens=p.e.tokens(hot), restart_equal=True, objects=objects)
            calls.report['generations'].append(generation)
            p.e.write(root/'generation.json', generation)
            p.e.write(root/'publication.json', publication)
            p.e.write(root/'published-hot.json', hot)
            calls.save()
            print(json.dumps({key:generation[key] for key in ('case','cut','requests','summary_reference_tokens','hot_reference_tokens','restart_equal')}),flush=True)
            for spec in item['tasks']:
                for arm, history in [('full',prepared['source']), ('wsc',hot)]:
                    await consume(calls, task, publication, history, prepared['system'], spec, arm, name, candidate['text'])
            assert task.project() == hot and d.heads.path_for(task.working.session_id).read_bytes() == frozen
            assert all(p.sha(Path(path).read_bytes()) == digest for path,digest in objects.items())
    calls.report['completed'] = True
    calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
    calls.save()
    print(json.dumps({'calls': len(calls.report['calls']), 'cost_estimate_cny': calls.report['cost_estimate_cny']}),flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare','run'])
    mode = parser.parse_args().mode
    p.e.ROOT = ROOT
    p.e.CLIENT = d.CountedClient(api_key='not-sent',model='deepseek-flash',thinking='disabled')
    asyncio.run(prepare() if mode=='prepare' else run())
