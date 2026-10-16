"""Two-domain wire-only ablation; actual files judged outside model inputs.

No A1 ranking, production renderer claim, or multi-generation claim. Both arms
use current native generation/Guard/recovery, differing only in scope encoding.
"""
import asyncio
from contextlib import ExitStack
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
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-inline-scope-continuation-292')
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')


def switch(arm):
    stack = ExitStack()
    if arm == 'D_parallel':
        stack.enter_context(patch('memory.wsc_handoff_scope_encoding.schema', side_effect=deepcopy))
        stack.enter_context(patch('memory.wsc_handoff_scope_encoding.to_native', side_effect=deepcopy))
    return stack


async def prepare():
    ROOT.mkdir(exist_ok=False)
    cases = [
        ('schedule', {'ticket': 'SHIFT-59273', 'start_time': '07:35', 'zone': 'Asia/Tokyo'},
         '生成排班核验文件', '时区字符串保持原值；时间使用24小时HH:MM格式；仅交付result.json。'),
        ('asset_manifest', {'asset': 'BANNER-68419', 'sha256': 'bd63c29a48ef7105', 'format': 'webp'},
         '生成素材清单核验文件', '校验码逐字保留；格式名使用小写；仅交付result.json。')]
    plan = {'scope': 'Two new synthetic domains; one actual fold each, not live production or A1 comparison.',
            'single_change': 'Quote/scope wire co-location; same current native Guard, prompt, sources and recovery.',
            'http_retries': 0, 'api_call_ceiling': 48, 'run_cost_ceiling_cny': 1.0,
            'per_call_ceiling_cny': 2.5, 'model': 'deepseek-flash', 'thinking': 'enabled',
            'handoff_request_limit': 6, 'actor_request_limit': 6, 'samples': [], 'private_expectations': {}}
    for index, (name, expected, objective, constraints) in enumerate(cases):
        plan['private_expectations'][name] = expected
        rows = [
            {'id': name + '-design', 'role': 'user', 'content':
             '先讨论方案，此阶段不写文件。决定输出JSON，不输出CSV。'},
            {'id': name + '-active', 'role': 'user', 'content':
             '设计结束，现在进入交付阶段，之前不写文件的限制到期。' + objective + '。' + constraints +
             '保留JSON输出的决定。只从以下原始资料选取对应的三个字段，逐字保存为artifact_root下result.json：' + canonical(expected)},
            {'id': name + '-resolved', 'role': 'user', 'content':
             '字段解释问题已经确认并解决，无需再次解释。本轮交付文件，其他要求保持。'}]
        source = ROOT / (name + '-source.jsonl')
        source.write_bytes(''.join(canonical(row) + '\n' for row in rows).encode('utf-8'))
        for slot in range(2):
            arm = ('D_parallel', 'D_inline')[slot if index == 0 else 1 - slot]
            folder = ROOT / name / str(slot)
            sink = ExactArtifactSink(folder / 'artifacts')
            before = [*deepcopy(rows), {'role': 'user', 'content': canonical({'artifact_root': str(sink.root)})}]
            with switch(arm):
                body = await native_first_request(CLIENT, before, rows)
            e.write(folder / 'first-request.json', body)
            plan['samples'].append({'case': name, 'arm': arm, 'folder': str(folder), 'source': str(source),
                'source_sha256': sha(source.read_bytes()), 'before': before,
                'prepared_input': str(folder / 'first-request.json')})
    paths = [Path(__file__), Path('python/memory/wsc_handoff_scope_encoding.py'),
             Path('python/memory/wsc_handoff_generation.py'), Path('python/evals/wsc_provider_frame_candidate.py')]
    plan['source_identities'] = {}
    for path in paths:
        raw = path.read_bytes()
        plan['source_identities'][str(path)] = sha(raw)
        (ROOT / path.name).write_bytes(raw)
    e.write(ROOT / 'preflight-manifest.json', plan)
    return plan


async def execute(plan):
    for path, digest in plan['source_identities'].items(): assert sha(Path(path).read_bytes()) == digest
    e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(1)
    original = calls.call
    async def bounded(body, label):
        upper = ((len(e.canonical(body).encode('utf-8')) + 8192) * 2 + body['max_tokens'] * 8) / 1e6
        spent = sum(c['cost_estimate'] for c in calls.report['calls'])
        if len(calls.report['calls']) >= plan['api_call_ceiling'] or spent + upper > plan['run_cost_ceiling_cny']:
            raise EvaluationStop('Prespecified bounded run admission')
        return await original(body, label)
    calls.call = bounded
    calls.report.update(protocol=plan, tasks=[])
    calls.save()
    for sample in plan['samples']:
        name, arm, folder = sample['case'], sample['arm'], Path(sample['folder'])
        source = Path(sample['source'])
        assert sha(source.read_bytes()) == sample['source_sha256']
        rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()]
        cold = ReceiptSources(source, sample['source_sha256'])
        sink = ExactArtifactSink(folder / 'artifacts')
        record = {'case': name, 'arm': arm, 'fold_accepted': False, 'generation_error': None, 'actor_error': None}
        calls.report['tasks'].append(record)
        hot = deepcopy(sample['before'])
        try:
            with switch(arm):
                use = await generate(ProviderFrameModel(calls, CLIENT, name + '-' + arm + '-handoff'),
                    sample['before'], rows, TodoWriteTool().schema(), AbortController(),
                    account=lambda usage: None, scope_protocol=True)
            parsed = validate(use.input, rows, require_phase=True)
            record.update(fold_accepted=True, candidate=use.input, presentation=use.presentation)
            hot = [{'role': 'assistant', 'content': canonical({'todos': use.input['todos'], 'checkpoint': parsed.checkpoint})}]
        except EvaluationStop: raise
        except Exception as exc: record['generation_error'] = type(exc).__name__ + ': ' + str(exc)
        calls.save()
        first = next((c for c in calls.report['calls'] if c['label'].startswith(name + '-' + arm + '-handoff-')), None)
        if first is not None:
            actual = json.loads((ROOT / (first['label'] + '-request.json')).read_text(encoding='utf-8'))
            assert actual == json.loads(Path(sample['prepared_input']).read_text(encoding='utf-8'))
        record.update(first_request_matches_preflight=first is not None, hot_tokens=e.tokens(hot),
                      hot_source='accepted_fold' if record['fold_accepted'] else 'raw_fallback')
        e.write(folder / 'hot.json', hot)
        messages = [*hot, {'role': 'user', 'content': canonical({'archive': cold.locator(), 'artifact_root': str(sink.root)})},
                    {'role': 'user', 'content': '继续当前任务。'}]
        actor = ProviderFrameModel(calls, CLIENT, name + '-' + arm + '-actor')
        state = new_state(messages)
        record['actor_state'] = state
        def checkpoint(value):
            record['actor_state'] = value
            e.write(folder / 'actor-checkpoint.json', value)
            calls.save()
        try:
            await run(actor, state, cold.schemas() + [sink.schema()], sink, cold, additional_requests=6, checkpoint=checkpoint)
        except EvaluationStop: raise
        except Exception as exc: record['actor_error'] = type(exc).__name__ + ': ' + str(exc)
        record['score'] = grade(sink, plan['private_expectations'][name])
        record['compressed_task_success'] = record['fold_accepted'] and record['score']['task_success']
        calls.save()
        print(canonical({k: record[k] for k in ('case', 'arm', 'fold_accepted', 'compressed_task_success', 'generation_error', 'actor_error')}), flush=True)
    summary = {'api_calls': len(calls.report['calls']), 'usage_observed': sum(c['usage_observed'] for c in calls.report['calls']),
               'cost_rate_estimate_cny': sum(c['cost_estimate'] for c in calls.report['calls']), 'arms': {}}
    for arm in ('D_parallel', 'D_inline'):
        tasks = [t for t in calls.report['tasks'] if t['arm'] == arm]
        selected = [c for c in calls.report['calls'] if '-' + arm + '-' in c['label']]
        summary['arms'][arm] = {'folds_accepted': sum(t['fold_accepted'] for t in tasks),
            'compressed_task_success': sum(t['compressed_task_success'] for t in tasks),
            'normal_end': sum(t['actor_state']['completed'] for t in tasks),
            'calls': len(selected), 'cost_estimate': sum(c['cost_estimate'] for c in selected),
            'hot_tokens': [t['hot_tokens'] for t in tasks]}
    calls.report['completed'] = True
    calls.save()
    e.write(ROOT / 'summary.json', summary)
    print(canonical(summary), flush=True)


if __name__ == '__main__':
    async def main():
        plan = await prepare()
        try: await execute(plan)
        except EvaluationStop as exc: print(canonical({'evaluation_stopped': str(exc)}), flush=True)
    asyncio.run(main())
