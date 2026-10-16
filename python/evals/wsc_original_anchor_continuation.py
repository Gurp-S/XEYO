"""Small held-out original-source recovery ablation; bounded paid execution."""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import patch

from engine.abort import AbortController
import evals.wsc_ad_experiment as e
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_elimination_faithful import EvaluationStop, StopAwareCalls
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_acceptance_protocol import canonical, sha, native_first_request
from evals.wsc_task_actor_candidate import new_state, run, grade
from memory.wsc_cold_receipt_candidate import ReceiptSources
from memory.wsc_handoff_generation import generate
from memory.wsc_handoff_validation import validate
from model.deepseek import DeepSeekModelClient
from synaptic.todo_snapshot import latest_todo_snapshot
from tests.wsc.test_handoff_original_anchors import chained, QUOTE
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

RUN = os.environ.get('WSC_ANCHOR_RUN', 'wsc-original-anchor-continuation-285')
assert RUN in {'wsc-original-anchor-continuation-285', 'wsc-original-anchor-continuation-287',
               'wsc-original-anchor-continuation-289'}
ROOT = Path('D:/lea/XenYon code/_wsc_out') / RUN
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')


def switch(arm):
    return patch('memory.wsc_handoff_anchors.materialize', return_value=None) if arm == 'D_without_original' else nullcontext()


async def prepare():
    ROOT.mkdir(exist_ok=False)
    cases = [('payment_receipt', {'reason': '支付接入验收未覆盖失败回执', 'receipt_id': 'PAY-683917'}),
             ('reconciliation_receipt', {'reason': '跨币种对账缺少原始依据', 'receipt_id': 'FX-520684'})]
    plan = {'scope': 'Two new synthetic recovery tasks, one payment domain; not live XEYO, real transcript or 10 model compactions.',
            'comparison': 'Same validated three-layer native quote ancestry; only original-anchor materializer is disabled in baseline.',
            'fold': 'Actual native generate and validation, then native checkpoint direct JSON; not full production renderer.',
            'model': 'deepseek-flash', 'thinking': 'enabled', 'initial_output_limit': 2048,
            'actor_output_limit': 4096, 'actor_request_limit': 6, 'handoff_request_limit': 6,
            'http_retries': 0, 'api_call_ceiling': 48, 'per_call_cny_limit': 2.5,
            'proposed_new_run_cost_ceiling_cny': 1.0 if RUN.endswith('289') else 0.6,
            'score': 'External exact two-field artifact and actual current write; compressed and raw-fallback success separate.',
            'api_calls_in_preparation': 0, 'samples': [], 'private_expectations': {name: expected for name, expected in cases}}
    if RUN.endswith('289'):
        plan['preparation_correction'] = ('285/287 native task fixture included unrelated WSC checklist text. '
            'Those runs remain mixed-state stress evidence. This independent run uses an internally consistent payment task; no old result is rescored.')
    for index, (name, expected) in enumerate(cases):
        rows, _ = chained(3)
        rows[0]['content'] = QUOTE + '\n原始验收资料=' + canonical(expected)
        event = {'id': 'delivery-request', 'role': 'user', 'content':
                 '现在继续核对现有验收。result.json尚未生成：将原始验收资料中的reason和receipt_id逐字保存为artifact_root下result.json，仅这两个字段。本轮交付该文件。'}
        rows.append(event)
        source = ROOT / (name + '-sealed-source.jsonl')
        source.write_bytes(''.join(canonical(row) + '\n' for row in rows).encode('utf-8'))
        seal = sha(source.read_bytes())
        snap = latest_todo_snapshot(rows)
        if RUN.endswith('289'):
            assert all('支付接入验收' in item['content'] and item.get('output') == 'result.json' for item in snap.records)
            assert not any('第二批' in item['content'] or '工具、类别' in item['content'] for item in snap.records)
        previous = {'todos': list(snap.records), 'checkpoint': snap.checkpoint}
        for slot in range(2):
            arm = ('D_without_original', 'D_original')[slot if index == 0 else 1 - slot]
            folder = ROOT / name / str(slot)
            sink = ExactArtifactSink(folder / 'artifacts')
            cold = ReceiptSources(source, seal)
            before = [{'role': 'assistant', 'content': canonical(previous)}, deepcopy(event),
                      {'role': 'user', 'content': canonical({'archive': cold.locator(), 'artifact_root': str(sink.root)})}]
            with switch(arm):
                body = await native_first_request(CLIENT, before, rows)
            e.write(folder / 'prepared-first-request.json', body)
            plan['samples'].append({'case': name, 'arm': arm, 'folder': str(folder),
                'source': str(source), 'source_sha256': seal, 'before': before,
                'prepared_input': str(folder / 'prepared-first-request.json'),
                'prepared_sha256': sha((folder / 'prepared-first-request.json').read_bytes())})
    paths = [Path(__file__), Path('python/tests/wsc/test_handoff_original_anchors.py'),
             Path('python/memory/wsc_handoff_generation.py'), Path('python/memory/wsc_handoff_anchors.py'),
             Path('python/memory/wsc_handoff_exhaustion.py'), Path('python/model/output_exhaustion.py'),
             Path('python/model/stream_end.py'),
             Path('python/evals/wsc_task_actor_candidate.py'), Path('python/evals/wsc_provider_frame_candidate.py')]
    plan['source_identities'] = {}
    for path in paths:
        raw = path.read_bytes()
        plan['source_identities'][str(path)] = sha(raw)
        (ROOT / path.name).write_bytes(raw)
    e.write(ROOT / 'preflight-manifest.json', plan)
    return plan


async def execute(plan):
    for path, digest in plan['source_identities'].items():
        assert sha(Path(path).read_bytes()) == digest
    e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(1)
    # The normal ledger retains all unknown reserves; the additional run cap
    # below also applies when cumulative authorization is unlimited.
    original_call = calls.call
    async def bounded(body, label):
        upper = min(((len(e.canonical(body).encode('utf-8')) + 8192) * 2 + body['max_tokens'] * 8) / 1e6,
                    (1048576 * 2 + body['max_tokens'] * 8) / 1e6)
        spent = sum(c['cost_estimate'] for c in calls.report['calls'])
        if len(calls.report['calls']) >= plan['api_call_ceiling'] or spent + upper > plan['proposed_new_run_cost_ceiling_cny']:
            raise EvaluationStop('Prespecified small-run ceiling reached')
        return await original_call(body, label)
    calls.call = bounded
    calls.report.update(protocol=plan, tasks=[])
    calls.save()
    for sample in plan['samples']:
        folder, arm, name = Path(sample['folder']), sample['arm'], sample['case']
        source = Path(sample['source'])
        assert sha(source.read_bytes()) == sample['source_sha256']
        rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()]
        cold = ReceiptSources(source, sample['source_sha256'])
        sink = ExactArtifactSink(folder / 'artifacts')
        record = {'case': name, 'arm': arm, 'fold_accepted': False, 'generation_error': None, 'actor_error': None}
        calls.report['tasks'].append(record)
        hot = deepcopy(sample['before'])
        model = ProviderFrameModel(calls, CLIENT, name + '-' + arm + '-handoff')
        try:
            with switch(arm):
                use = await generate(model, sample['before'], rows, TodoWriteTool().schema(), AbortController(),
                                     account=lambda usage: None, scope_protocol=True)
            parsed = validate(use.input, rows, require_phase=True)
            tool = TodoWriteTool()
            receipt = tool.map_tool_result_to_content(tool.call(parsed))
            native = {'todos': use.input['todos'], 'checkpoint': parsed.checkpoint}
            hot = [{'role': 'assistant', 'content': canonical(native)}]
            record.update(fold_accepted=True, candidate=use.input, declaration_receipt=receipt, presentation=use.presentation)
        except EvaluationStop:
            raise
        except Exception as exc:
            record['generation_error'] = type(exc).__name__ + ': ' + str(exc)
        first = next((c for c in calls.report['calls'] if c['label'].startswith(name + '-' + arm + '-handoff-')), None)
        if first:
            actual = json.loads((ROOT / (first['label'] + '-request.json')).read_text(encoding='utf-8'))
            assert sha(Path(sample['prepared_input']).read_bytes()) == sample['prepared_sha256']
            assert actual == json.loads(Path(sample['prepared_input']).read_text(encoding='utf-8'))
            record['first_request_matches_preflight'] = True
        messages = [*hot, {'role': 'user', 'content': canonical({'archive': cold.locator(), 'artifact_root': str(sink.root)})},
                    {'role': 'user', 'content': '继续当前任务。'}]
        record.update(hot_tokens=e.tokens(hot), hot_source='accepted_fold' if record['fold_accepted'] else 'raw_fallback')
        e.write(folder / 'hot.json', hot)
        actor = ProviderFrameModel(calls, CLIENT, name + '-' + arm + '-actor')
        state = new_state(messages)
        record['actor_state'] = state
        def checkpoint(value):
            record['actor_state'] = value
            e.write(folder / 'actor-checkpoint.json', value)
            calls.save()
        try:
            await run(actor, state, cold.schemas() + [sink.schema()], sink, cold, additional_requests=6, checkpoint=checkpoint)
        except EvaluationStop:
            raise
        except Exception as exc:
            record['actor_error'] = type(exc).__name__ + ': ' + str(exc)
        record['score'] = grade(sink, plan['private_expectations'][name])
        record['compressed_task_success'] = record['fold_accepted'] and record['score']['task_success']
        calls.save()
        print(json.dumps({'case': name, 'arm': arm, 'fold': record['fold_accepted'],
                          'task_success': record['score']['task_success'], 'completed': state['completed'],
                          'generation_error': record['generation_error'], 'actor_error': record['actor_error']}), flush=True)
    summary = {'api_calls': len(calls.report['calls']), 'usage_observed': sum(c['usage_observed'] for c in calls.report['calls']),
               'cost_rate_estimate_cny': sum(c['cost_estimate'] for c in calls.report['calls']), 'arms': {}}
    for arm in ('D_without_original', 'D_original'):
        tasks = [t for t in calls.report['tasks'] if t['arm'] == arm]
        summary['arms'][arm] = {'tasks': len(tasks), 'folds_accepted': sum(t['fold_accepted'] for t in tasks),
            'compressed_task_success': sum(t['compressed_task_success'] for t in tasks),
            'all_artifact_success': sum(t['score']['task_success'] for t in tasks),
            'normal_end': sum(t['actor_state']['completed'] for t in tasks)}
    calls.report['completed'] = True
    calls.save()
    e.write(ROOT / 'summary.json', summary)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    async def main():
        plan = await prepare()
        try:
            await execute(plan)
        except EvaluationStop as exc:
            print(json.dumps({'evaluation_stopped': str(exc)}), flush=True)
    asyncio.run(main())
