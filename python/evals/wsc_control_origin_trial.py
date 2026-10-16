"""Invocation/task boundary ablation with fixed A1 and actual-file continuation.

Sources and rubric are sealed before calls. Three D carriers differ only in
the isolated control message; A1 uses the existing pinned public Codex prompt.
Semantic review is separate from native Guard and artifact correctness.
"""
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
from evals.wsc_elimination_chain import retain_users, PROMPT, PREFIX
from evals.wsc_elimination_faithful import EvaluationStop, StopAwareCalls
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_acceptance_protocol import canonical, sha, native_first_request
from evals.wsc_task_actor_candidate import new_state, run, grade
from memory.wsc_cold_receipt_candidate import ReceiptSources
from memory.wsc_handoff_control import factual_message, legacy_message
from memory.wsc_handoff_generation import generate
from memory.wsc_handoff_validation import validate
from model.deepseek import DeepSeekModelClient
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-control-origin-continuation-294')
OLD = ROOT.parent / 'wsc-inline-scope-continuation-292'
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')
ARMS = ('D_legacy', 'D_fact_user', 'D_fact_system', 'A1')


def system_message(identities, count):
    return dict(factual_message(identities, count), role='system')


def switch(arm):
    factory = {'D_legacy': legacy_message, 'D_fact_user': factual_message, 'D_fact_system': system_message}.get(arm)
    return patch('memory.wsc_handoff_control.message', factory) if factory else nullcontext()


async def prepare():
    ROOT.mkdir(exist_ok=False)
    cases = []
    old_plan = json.loads((OLD / 'preflight-manifest.json').read_text(encoding='utf-8'))
    for name in ('schedule', 'asset_manifest'):
        raw = (OLD / (name + '-source.jsonl')).read_bytes()
        cases.append((name, raw, old_plan['private_expectations'][name]))
    expected = {'goal': '完成离线验收', 'next_step': '核对原始回执'}
    rows = [{'id': 'handoff-plan', 'role': 'user', 'content': '先讨论交接档案，此阶段不写文件；采用JSON。'},
            {'id': 'handoff-active', 'role': 'user', 'content':
             '讨论已结束，进入交付阶段，先前不写文件的限制到期。当前任务就是制作交接档案。'
             '将以下原始交接记录的goal与next_step逐字保存为artifact_root下result.json，只有这两个字段；采用JSON，不使用CSV：' + canonical(expected)},
            {'id': 'handoff-resolved', 'role': 'user', 'content': '交接档案用途的问题已解决，无需再次解释。本轮交付文件。'}]
    cases.append(('handoff_record', ''.join(canonical(r) + '\n' for r in rows).encode('utf-8'), expected))
    plan = {'scope': 'Three synthetic task sources; two byte-identical292 sources and one new held-out legitimate handoff task. One fold each.',
            'comparison': 'D legacy command vs one factual invocation type, same native Guard/schema/sources/recovery; system role separately ablated. Fixed public A1 task baseline.',
            'renderer': 'Native declaration direct JSON; not production renderer, live85%, full228, or multigeneration acceptance.',
            'http_retries': 0, 'api_call_ceiling': 100, 'proposed_new_run_cost_ceiling_cny': 1.5,
            'per_call_limit_cny': 2.5, 'actor_request_limit': 6, 'handoff_request_limit': 6,
            'initial_generation_output_limit': 2048, 'generation_output_ceiling': 8192,
            'a1_output_exhaustion': 'Same bounded output growth as D, no partial summary installed, no HTTP retry.',
            'model': 'deepseek-flash', 'thinking': 'enabled', 'samples': [], 'private_expectations': {},
            'semantic_rubric': [
                'Objective describes the source task deliverable; invocation/summary generation is not its objective or a task-wide execution prohibition.',
                'Active unfinished work includes writing result.json for this task, not just submitting TodoWrite or generating this checkpoint.',
                'Current phase is delivery, with design-only no-write restriction inactive; source task JSON/exact-field constraints remain active.',
                'Resolved explanation remains resolved, no request to repeat explanation or reopen its question.',
                'All exact field values are retained or retrieved and used in the actual delivered file.',
                'Legitimate handoff_record task remains a handoff-document task; no lexical removal of handoff words.'],
            'semantic_scoring': 'Independent source-grounded review of all generated states/summary+retained users, including quotes; not Guard accepted or a banned-word match.',
            'pinned_prompt_sha256': sha(PROMPT.encode('utf-8')), 'pinned_prefix_sha256': sha(PREFIX.encode('utf-8'))}
    for index, (name, raw, expected) in enumerate(cases):
        plan['private_expectations'][name] = expected
        source = ROOT / (name + '-source.jsonl'); source.write_bytes(raw)
        rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
        order = ARMS[index:] + ARMS[:index]
        for slot, arm in enumerate(order):
            folder = ROOT / name / str(slot)
            sink = ExactArtifactSink(folder / 'artifacts')
            before = [*deepcopy(rows), {'role': 'user', 'content': canonical({'artifact_root': str(sink.root)})}]
            with switch(arm):
                native = await native_first_request(CLIENT, before, rows)
            if arm == 'A1':
                body = CLIENT._build_body([*before, {'role': 'user', 'content': PROMPT}], [], stream=False)
                body.update(max_tokens=native['max_tokens'], temperature=0)
            else: body = native
            e.write(folder / 'first-request.json', body)
            plan['samples'].append({'case': name, 'arm': arm, 'folder': str(folder), 'source': str(source),
                'source_sha256': sha(raw), 'before': before, 'prepared_input': str(folder / 'first-request.json')})
    plan['source_identities'] = {}
    for path in [Path(__file__), Path('python/memory/wsc_handoff_control.py'), Path('python/memory/wsc_handoff_generation.py'),
                 Path('python/memory/wsc_handoff_scope_encoding.py'), Path('python/evals/wsc_provider_frame_candidate.py')]:
        raw = path.read_bytes(); plan['source_identities'][str(path)] = sha(raw)
        (ROOT / path.name).write_bytes(raw)
    e.write(ROOT / 'preflight-manifest.json', plan)
    return plan


async def a1(calls, sample, rows):
    body = json.loads(Path(sample['prepared_input']).read_text(encoding='utf-8'))
    for attempt in range(6):
        response = await calls.call(body, sample['case'] + '-A1-handoff-' + str(attempt + 1))
        choice = response['choices'][0]
        if choice['finish_reason'] in ('length', 'max_tokens') and body['max_tokens'] < 8192 and attempt < 5:
            body['max_tokens'] = min(8192, body['max_tokens'] * 2)
            continue
        text = choice['message'].get('content') or ''
        if choice['finish_reason'] != 'stop' or not text.strip() or choice['message'].get('tool_calls'):
            raise ValueError('summary_incomplete')
        return retain_users([], rows, text), text
    raise ValueError('summary_incomplete')


async def execute(plan):
    for path, digest in plan['source_identities'].items(): assert sha(Path(path).read_bytes()) == digest
    assert sha(PROMPT.encode('utf-8')) == plan['pinned_prompt_sha256']
    e.ROOT = ROOT; os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls(); calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(protocol=plan, tasks=[]); calls.save()
    original = calls.call
    async def bounded(body, label):
        if len(calls.report['calls']) >= plan['api_call_ceiling']: raise EvaluationStop('Prespecified call ceiling')
        return await original(body, label)
    calls.call = bounded
    for sample in plan['samples']:
        name, arm, folder = sample['case'], sample['arm'], Path(sample['folder'])
        source = Path(sample['source']); assert sha(source.read_bytes()) == sample['source_sha256']
        rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()]
        cold = ReceiptSources(source, sample['source_sha256']); sink = ExactArtifactSink(folder / 'artifacts')
        record = {'case': name, 'arm': arm, 'fold_accepted': False, 'generation_error': None, 'actor_error': None}
        calls.report['tasks'].append(record); calls.save()
        hot = deepcopy(sample['before'])
        try:
            if arm == 'A1':
                hot, record['summary'] = await a1(calls, sample, rows)
            else:
                with switch(arm):
                    use = await generate(ProviderFrameModel(calls, CLIENT, name + '-' + arm + '-handoff'),
                        sample['before'], rows, TodoWriteTool().schema(), AbortController(), account=lambda usage: None, scope_protocol=True)
                parsed = validate(use.input, rows, require_phase=True)
                record.update(candidate=use.input, presentation=use.presentation)
                hot = [{'role': 'assistant', 'content': canonical({'todos': use.input['todos'], 'checkpoint': parsed.checkpoint})}]
            record['fold_accepted'] = True
        except EvaluationStop: raise
        except Exception as exc: record['generation_error'] = type(exc).__name__ + ': ' + str(exc)
        calls.save()
        first = next((c for c in calls.report['calls'] if c['label'].startswith(name + '-' + arm + '-handoff-')), None)
        if first:
            assert json.loads((ROOT / (first['label'] + '-request.json')).read_text(encoding='utf-8')) == json.loads(Path(sample['prepared_input']).read_text(encoding='utf-8'))
        record.update(first_request_matches_preflight=first is not None, hot_tokens=e.tokens(hot),
                      hot_source='accepted_fold' if record['fold_accepted'] else 'raw_fallback')
        e.write(folder / 'hot.json', hot)
        messages = [*hot, {'role': 'user', 'content': canonical({'archive': cold.locator(), 'artifact_root': str(sink.root)})},
                    {'role': 'user', 'content': '继续当前任务。'}]
        state = new_state(messages); record['actor_state'] = state
        def checkpoint(value):
            record['actor_state'] = value; e.write(folder / 'actor-checkpoint.json', value); calls.save()
        try:
            await run(ProviderFrameModel(calls, CLIENT, name + '-' + arm + '-actor'), state,
                      cold.schemas() + [sink.schema()], sink, cold, additional_requests=6, checkpoint=checkpoint)
        except EvaluationStop: raise
        except Exception as exc: record['actor_error'] = type(exc).__name__ + ': ' + str(exc)
        record['score'] = grade(sink, plan['private_expectations'][name])
        record['compressed_task_success'] = record['fold_accepted'] and record['score']['task_success']
        calls.save()
        print(canonical({k: record[k] for k in ('case', 'arm', 'fold_accepted', 'compressed_task_success', 'generation_error', 'actor_error')}), flush=True)
    summary = {'api_calls': len(calls.report['calls']), 'usage_observed': sum(c['usage_observed'] for c in calls.report['calls']),
               'cost_rate_estimate_cny': sum(c['cost_estimate'] for c in calls.report['calls']), 'arms': {}}
    for arm in ARMS:
        tasks = [t for t in calls.report['tasks'] if t['arm'] == arm]
        selected = [c for c in calls.report['calls'] if '-' + arm + '-' in c['label']]
        summary['arms'][arm] = {'tasks': len(tasks), 'folds_accepted': sum(t['fold_accepted'] for t in tasks),
            'compressed_task_success': sum(t['compressed_task_success'] for t in tasks),
            'normal_end': sum(t['actor_state']['completed'] for t in tasks), 'calls': len(selected),
            'cost_estimate': sum(c['cost_estimate'] for c in selected), 'hot_tokens': [t['hot_tokens'] for t in tasks]}
    calls.report['completed'] = True; calls.save(); e.write(ROOT / 'summary.json', summary)
    print(canonical(summary), flush=True)


if __name__ == '__main__':
    async def main():
        plan = await prepare()
        try: await execute(plan)
        except EvaluationStop as exc: print(canonical({'evaluation_stopped': str(exc)}), flush=True)
    asyncio.run(main())
