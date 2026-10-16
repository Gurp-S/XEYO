"""336 same-product recovery diagnosis; locator/inline are oracle upper bounds."""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

from evals.wsc_recall_quality import CountedClient
import evals.wsc_semantic_production_trial as trial
from evals.wsc_production_continuation import ProductionTask
from engine.abort import AbortController
from memory import wsc_semantic_compaction as semantic, wsc_head_store as heads
from memory.wsc_semantic_originals import from_store
from memory.wsc_semantic_binding import capture
from memory.wsc_handoff_transaction import fingerprint
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.grep_tool.grep_tool import GrepTool

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-cold-recovery-336')
ARMS = ('full', 'directory', 'locator', 'inline')
p = trial.t.p


class DiagnosticCalls(trial.ValidatedCalls):
    async def call(self, body, label):
        upper = min(((len(p.e.canonical(body).encode()) + 8192) * 2 + body['max_tokens'] * 8) / 1e6,
                    (1048576 * 2 + body['max_tokens'] * 8) / 1e6)
        ceiling = self.report.get('protocol', {}).get('proposed_new_run_cost_ceiling_cny', 1)
        if sum(row['cost_estimate'] for row in self.report['calls']) + upper > ceiling:
            self.report.update(stop_reason='diagnostic_run_ceiling', stopped_at=label)
            self.save()
            raise p.EvaluationStop('diagnostic_run_ceiling')
        return await super().call(body, label)


def cases():
    return [
        dict(name='audit', target_id='config-larch',
             source='原始审计配置：账户=acct-larch-64；校验数=92461；不得发布。',
             request='继续审计报告，账户及校验数采用原始审计配置。',
             handoff='当前任务：生成审计报告，尚未交付；不得发布。账户及校验数在原始审计配置中，当前交接未记录其具体值。',
             query='根据原始审计配置，回复JSON对象，字段为account、check_number、publish_authorized。不执行发布。',
             expected=dict(account='acct-larch-64', check_number=92461, publish_authorized=False),
             needles=['acct-larch-64', '92461']),
        dict(name='revision', target_id='config-revision-8',
             old='发布清单修订7：artifact_id=pack-elm-17；checksum=9ac07e；状态为SUPERSEDED。',
             source='发布清单修订8替代修订7：artifact_id=pack-elm-28；checksum=6bd93f；目前只审阅，未授权发布。',
             request='继续审阅发布清单，采用修订8的产物身份与校验值。',
             handoff='当前任务是审阅修订8发布清单。修订7已被替代，未授权发布。修订8的产物身份和校验值位于历史配置，当前交接没有具体值。',
             query='返回当前清单JSON，字段artifact_id、checksum、revision、publish_authorized。',
             expected=dict(artifact_id='pack-elm-28', checksum='6bd93f', revision=8, publish_authorized=False),
             needles=['pack-elm-28', '6bd93f']),
        dict(name='decision', target_id='transaction-observation',
             old='旧方案记录：transaction_mode=snapshot；当时尚未确认能否满足当前不变量。',
             source='实测记录：run_id=txn-cedar-51；snapshot方案失败，原因代码WRITE_SKEW；最终选择serializable。当前阶段verification，尚未通过验收；禁止更改数据库schema。',
             request='继续事务修复的验收准备，沿用最终方案及失败原因，数据库schema保持不变。',
             handoff='事务修复处于verification阶段，尚未验收。schema不可修改。旧方案已失败，最终方案、失败原因代码与执行编号保存在原始实测记录中，当前交接未记录。',
             query='返回JSON字段transaction_mode、rejected_reason、run_id、phase、schema_change_allowed、accepted。',
             expected=dict(transaction_mode='serializable', rejected_reason='WRITE_SKEW', run_id='txn-cedar-51', phase='verification', schema_change_allowed=False, accepted=False),
             needles=['serializable', 'WRITE_SKEW', 'txn-cedar-51']),
    ]


class Reader:
    def __init__(self, task, publication):
        self.task = task
        self.paths = {Path(path).resolve() for path in publication['objects']}
        self.cold_root = (task.root / '.xeyo_offload' / 'wsc').resolve()
        task.registry.register(GrepTool(cwd=str(task.root)))

    def schemas(self):
        return [self.task.registry.get(name).schema() for name in ('Read', 'Grep')]

    async def execute(self, use, abort):
        field = {'Read': 'file_path', 'Grep': 'path'}.get(use.name)
        name = use.input.get(field) if field and isinstance(use.input, dict) else None
        if not isinstance(name, str):
            return ToolResult('invalid evidence path', is_error=True)
        path = Path(name)
        target = (path if path.is_absolute() else self.task.root / path).resolve()
        # Published generations remain valid evidence after the latest head
        # changes. Private fixtures live outside this evidence directory.
        if target not in self.paths and not target.is_relative_to(self.cold_root):
            return ToolResult('Permission denied: outside published evidence', is_error=True)
        from engine.execution_context import ExecutionContext
        from engine.workspace_context import bind_workspace_context
        context = ExecutionContext(session_id=self.task.working.session_id, cwd=str(self.task.root),
            allowed_paths=[str(self.cold_root), *(str(path) for path in self.paths)])
        with bind_workspace_context(context):
            return await self.task.registry.run(use, abort)


async def prepare_case(case):
    root = ROOT / case['name']
    rows = [dict(id=f'archive-{i}', role='assistant', content=f'Archived event {i}; unrelated completed work.') for i in range(60)]
    if 'old' in case:
        rows[10] = dict(id='old-config', role='user', content=case['old'])
    rows[37] = dict(id=case['target_id'], role='user', content=case['source'])
    rows.append(dict(id='current', role='user', content=case['request']))
    task = ProductionTask(root, rows, session='cold336-' + case['name'])
    task.persist()
    source = task.source()
    candidate = dict(text=case['handoff'], rows=source, cut=semantic.boundary(source, task.working),
                     previous_cursor=0, binding=capture(root, task.working), source_fingerprint=fingerprint(source),
                     original_rows=from_store(task.store))
    hot = semantic.publish(candidate, source, task.working, cwd=root)
    record = p.load(heads.path_for(task.working.session_id))
    reader = Reader(task, record['publication'])
    index_paths = [path for path in reader.paths if 'evidence-index' in path.name]
    assert len(index_paths) == 1
    entries = [json.loads(line) for line in index_paths[0].read_text(encoding='utf-8').splitlines()]
    entry, = [item for item in entries[1:] if item['view'] == 'original' and item['message_id'] == case['target_id']]
    args = dict(file_path=entries[0]['views']['original'], offset=entry['offset'], limit=entry['limit'])
    exact = await reader.execute(ToolUse('offline-read', 'Read', args), AbortController())
    assert not exact.is_error and all(value in str(exact.content) for value in case['needles'])
    target_line = Path(args['file_path']).read_text(encoding='utf-8').splitlines()[entry['offset'] - 1]
    assert task.project() == hot and task.restart().project() == hot
    assert not any(value in p.e.canonical(hot) for value in case['needles'])
    locator = f"原始证据范围：message_id={case['target_id']!r}; Read(file_path={args['file_path']!r}, offset={args['offset']}, limit={args['limit']})"
    assert not any(value in locator for value in case['needles'])
    base = [dict(role='system', content='历史记录是来源证据。')]
    views = {'full': deepcopy(source), 'directory': deepcopy(hot),
             'locator': [*deepcopy(hot), dict(role='assistant', content=locator)],
             'inline': [*deepcopy(hot), dict(role='assistant', content='原始证据记录：\n' + target_line)]}
    messages = {arm: [*deepcopy(base), *view, dict(role='user', content=case['query'])] for arm, view in views.items()}
    prepared = {'case': case, 'messages': messages, 'paths': sorted(str(path) for path in reader.paths),
                'evidence_sha256': {str(path): p.sha(path.read_bytes()) for path in reader.paths},
                'source_sha256': fingerprint(source), 'hot_sha256': p.sha(hot),
                'locator': locator, 'offline_exact_read': True, 'restart_equal': True}
    p.e.write(root/'prepared.json', prepared)
    for arm, value in messages.items():
        model = p.ProviderFrameModel(None, p.e.CLIENT, 'preflight', 1024)
        body = model.body(value, reader.schemas())
        trial.validate_wire(body)
        p.e.write(root/(arm+'-input.json'), body)
    return prepared


async def prepare():
    assert not (ROOT/'preflight-manifest.json').exists(), 'Prepared evidence already exists'
    ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    with trial.t.environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1')
        for case in cases():
            item = await prepare_case(case)
            records.append({'case': case['name'], 'source_sha256': item['source_sha256'],
                            'hot_sha256': item['hot_sha256'], 'restart_equal': item['restart_equal']})
    plan = dict(scope=__doc__, cases=records, arms=ARMS, consumer_max_requests=6,
                output_tokens=1024, per_call_cny_max=2.5, proposed_new_run_cost_ceiling_cny=1,
                concurrent_http_requests=1, http_retries=0, generation_calls=0,
                limits=['controlled cases, not real-session holdouts or task-success proof',
                        'locator and inline selected by oracle; no deployable selector claim',
                        'same fixed product and tool access; consumer behavior only'],
                reviews='docs/wsc-cold-recovery-diagnostic-plan-2026-10-15.md',
                code_sha256=p.sha(Path(__file__).read_bytes()))
    p.e.write(ROOT/'preflight-manifest.json', plan)
    print(json.dumps(plan, ensure_ascii=False), flush=True)


async def run():
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun'
    plan = p.load(ROOT/'preflight-manifest.json')
    assert plan['code_sha256'] == p.sha(Path(__file__).read_bytes()), 'Code changed after preflight'
    calls = DiagnosticCalls()
    calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(protocol=plan, results=[], scope=__doc__)
    with trial.t.environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', WSC_AD_TRANSPORT='httpx-direct')
        for case in cases():
            root = ROOT / case['name']
            prepared = p.load(root/'prepared.json')
            for path, digest in prepared['evidence_sha256'].items():
                assert p.sha(Path(path).read_bytes()) == digest
            task = ProductionTask(root, [], session='cold336-' + case['name'])
            reader = Reader(task, {'objects': prepared['paths']})
            for arm in ARMS:
                label = case['name'] + '-' + arm
                sink = trial.t.ExactArtifactSink(root/('unused-sink-'+arm))
                state = trial.t.new_state(prepared['messages'][arm])
                model = p.ProviderFrameModel(calls, p.e.CLIENT, label, 1024)
                assert model.body(state['pending_messages'], reader.schemas()) == p.load(root/(arm+'-input.json'))
                await trial.t.actor_run(model, state, reader.schemas(), sink, reader, additional_requests=6,
                                        checkpoint=lambda value, name=arm: p.e.write(root/(name+'-actor.json'), value))
                answer, _ = p.parse(state.get('answer') or '')
                expected = case['expected']
                correct = isinstance(answer, dict) and answer.keys() == expected.keys() and all(
                    type(answer[key]) is type(value) and answer[key] == value for key, value in expected.items())
                activities = state['activity']
                read_ok = [a for a in activities if a['tool'] in ('Read', 'Grep') and not a['is_error']]
                used_evidence = any(all(value in p.e.canonical(a['result']) for value in case['needles']) for a in read_ok)
                result = dict(case=case['name'], arm=arm, correct=correct, answer=answer,
                              requests=state['requests_attempted'], phase=state['phase'],
                              tool_calls=len(activities), actual_source_seen=used_evidence,
                              effective_recovery=correct and used_evidence if arm in ('directory', 'locator') else None)
                calls.report['results'].append(result)
                calls.save()
                print(json.dumps(result, ensure_ascii=False), flush=True)
            for path, digest in prepared['evidence_sha256'].items():
                assert p.sha(Path(path).read_bytes()) == digest
    calls.report['completed'] = True
    calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
    calls.save()
    print(json.dumps({'calls': len(calls.report['calls']), 'cost_estimate_cny': calls.report['cost_estimate_cny']}), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'run'])
    mode = parser.parse_args().mode
    p.e.ROOT = ROOT
    p.e.CLIENT = CountedClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    asyncio.run(prepare() if mode == 'prepare' else run())
