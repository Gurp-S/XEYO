"""Native D/pinned A1 initial-fold artifact control; no production compaction."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path

from engine.abort import AbortController
import evals.wsc_ad_experiment as e
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_elimination_chain import retain_users, PREFIX, PROMPT
from evals.wsc_elimination_faithful import EvaluationStop, StopAwareCalls
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_actor_candidate import new_state, run, grade
from evals.wsc_task_acceptance_protocol import scenarios, visible_sources, canonical, sha, native_first_request
from memory.wsc_cold_receipt_candidate import ReceiptSources
from memory.wsc_handoff_generation import generate
from memory.wsc_handoff_validation import validate
from model.deepseek import DeepSeekModelClient
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-task-first-fold-280')
OLD = ROOT.parent / 'wsc-task-acceptance-270'
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')


def prepare():
    ROOT.mkdir(exist_ok=False)
    previous = json.loads((OLD / 'preflight-manifest.json').read_text(encoding='utf-8'))
    plan = {'scope': 'Two synthetic initial-fold artifact tasks; not production or original 228 acceptance.',
            'generation': 'D actual native generate/validate/private TodoWrite; A1 pinned Codex prompt+retain_users.',
            'D_renderer': 'Native checkpoint direct JSON, same faithful experimental renderer; not production applicable.',
            'thinking': 'enabled', 'actor_output_limit': 4096, 'actor_call_limit': 6,
            'ordinary_or_85_percent_trigger_test': False, 'http_retries': 0, 'samples': []}
    for index, (case, old) in enumerate(zip(scenarios(), previous['cases'])):
        rows = visible_sources(case, 1)
        raw = Path(old['archive']).read_bytes()
        assert sha(raw) == old['source_sha256']
        assert rows == [json.loads(line) for line in raw.decode('utf-8').splitlines()]
        source = ROOT / (case['case'] + '-sealed-source.jsonl')
        source.write_bytes(raw)
        normalized = []
        for arm in ('A1', 'D'):
            slot = index if arm == 'A1' else 1 - index
            folder = ROOT / case['case'] / str(slot)
            folder.mkdir(parents=True)
            sink = ExactArtifactSink(folder / 'artifacts')
            cold = ReceiptSources(source, old['source_sha256'])
            envelope = {'source_records': rows, 'archive': cold.locator(), 'artifact_root': str(sink.root)}
            visible = [{'role': 'user', 'content': canonical(envelope)}]
            d = asyncio.run(native_first_request(CLIENT, visible, rows))
            a = CLIENT._build_body([*visible, {'role': 'user', 'content': PROMPT}], [], stream=False)
            a.update(max_tokens=d['max_tokens'], temperature=0)
            body = d if arm == 'D' else a
            normalized.append({**envelope, 'artifact_root': '@OUTPUT_ROOT'})
            e.write(folder / 'generation-prepared.json', body)
            plan['samples'].append({'case': case['case'], 'arm': arm, 'slot': slot, 'folder': str(folder),
                'source': str(source), 'source_sha256': old['source_sha256'], 'generation_input': str(folder / 'generation-prepared.json'),
                'generation_sha256': sha((folder / 'generation-prepared.json').read_bytes()),
                'initial_generation_output_limit': body['max_tokens'], 'visible': visible})
        assert normalized[0] == normalized[1]
    plan['pinned_prompt_sha256'] = sha(PROMPT.encode('utf-8'))
    plan['pinned_prefix_sha256'] = sha(PREFIX.encode('utf-8'))
    plan['source_identities'] = {}
    for path in [Path(__file__), Path('python/evals/wsc_task_actor_candidate.py'), Path('python/evals/wsc_provider_frame_candidate.py'),
                 Path('python/memory/wsc_handoff_generation.py'), Path('python/memory/wsc_handoff_validation.py')]:
        raw = path.read_bytes(); plan['source_identities'][str(path)] = sha(raw)
        (ROOT / path.name).write_bytes(raw)
    e.write(ROOT / 'preflight-manifest.json', plan)
    return plan


async def execute(plan):
    gate = json.loads((ROOT.parent / 'wsc-actor-contracts-278/report.json').read_text(encoding='utf-8'))
    assert gate['passed'] == gate['total'] == 13
    for path, digest in plan['source_identities'].items(): assert sha(Path(path).read_bytes()) == digest
    e.ROOT = ROOT; os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls(); calls.semaphore = asyncio.Semaphore(2)
    calls.report.update(protocol=plan, tasks=[])

    async def one(sample):
        name, arm = sample['case'], sample['arm']; folder = Path(sample['folder'])
        scenario = next(c for c in scenarios() if c['case'] == name)
        rows = visible_sources(scenario, 1)
        assert sha(Path(sample['source']).read_bytes()) == sample['source_sha256']
        cold = ReceiptSources(sample['source'], sample['source_sha256'])
        sink = ExactArtifactSink(folder / 'artifacts')
        record = {'case': name, 'arm': arm, 'fold_accepted': False, 'generation_error': None, 'actor_error': None}
        calls.report['tasks'].append(record)
        before = deepcopy(sample['visible']); hot = deepcopy(before)
        try:
            if arm == 'D':
                model = ProviderFrameModel(calls, CLIENT, name + '-D-handoff')
                use = await generate(model, before, rows, TodoWriteTool().schema(), AbortController(),
                                     account=lambda usage: None, scope_protocol=True)
                parsed = validate(use.input, rows, require_phase=True)
                tool = TodoWriteTool()
                receipt = tool.map_tool_result_to_content(tool.call(parsed))
                native = {'todos': use.input['todos'], 'checkpoint': parsed.checkpoint}
                hot = [{'role': 'assistant', 'content': canonical(native)}]
                record.update(native=native, candidate=use.input, declaration_receipt=receipt, presentation=use.presentation)
                first = next(c for c in calls.report['calls'] if c['label'].startswith(name + '-D-handoff-'))
                actual = json.loads((ROOT / (first['label'] + '-request.json')).read_text(encoding='utf-8'))
                prepared = json.loads(Path(sample['generation_input']).read_text(encoding='utf-8'))
                assert actual == prepared, 'Native preparation changed before paid first request'
            else:
                prepared = json.loads(Path(sample['generation_input']).read_text(encoding='utf-8'))
                assert sha(Path(sample['generation_input']).read_bytes()) == sample['generation_sha256']
                response = await calls.call(prepared, name + '-A1-handoff')
                choice = response['choices'][0]; text = choice['message'].get('content') or ''
                if choice['finish_reason'] != 'stop' or not text.strip(): raise ValueError('summary_incomplete')
                hot = retain_users([], rows, text)
                record['summary'] = text
            record['fold_accepted'] = True
        except EvaluationStop:
            record['generation_error'] = 'Run stopped by payment or admission'; calls.save(); return
        except Exception as exc:
            record['generation_error'] = type(exc).__name__ + ': ' + str(exc)
            hot = deepcopy(before)
        common = {'role': 'user', 'content': canonical({'archive': cold.locator(), 'artifact_root': str(sink.root)})}
        messages = [*hot, common, {'role': 'user', 'content': '继续当前任务。'}]
        tools = cold.schemas() + [sink.schema()]
        actor_model = ProviderFrameModel(calls, CLIENT, name + '-' + arm + '-actor')
        record.update(hot_tokens=e.tokens(hot), hot_source='accepted_fold' if record['fold_accepted'] else 'raw_fallback',
                      first_actor_request_token_estimate=CLIENT.context_token_measure(actor_model.context_input(messages, tools))[0])
        e.write(folder / 'hot.json', hot)
        record['actor_state'] = new_state(messages)
        def checkpoint(value):
            record['actor_state'] = value
            e.write(folder / 'actor-checkpoint.json', value)
            calls.save()
        try:
            await run(actor_model, record['actor_state'], tools, sink, cold, additional_requests=6, checkpoint=checkpoint)
        except EvaluationStop: record['actor_error'] = 'Run stopped by payment or admission'
        except Exception as exc: record['actor_error'] = type(exc).__name__ + ': ' + str(exc)
        record['score'] = grade(sink, scenario['steps'][0]['expected_artifact'])
        record['successful_compressed_task'] = record['fold_accepted'] and record['score']['task_success']
        calls.save()
        print(json.dumps({'case': name, 'arm': arm, 'fold_accepted': record['fold_accepted'],
                          'task_success': record['score']['task_success'], 'actor_completed': record['actor_state']['completed'],
                          'generation_error': record['generation_error'], 'actor_error': record['actor_error']}), flush=True)

    await asyncio.gather(*(one(s) for s in plan['samples']))
    summary = {'api_calls': len(calls.report['calls']), 'usage_observed': sum(c['usage_observed'] for c in calls.report['calls']),
               'cost_rate_estimate_cny': sum(c['cost_estimate'] for c in calls.report['calls']), 'arms': {}}
    for arm in ('A1', 'D'):
        tasks = [t for t in calls.report['tasks'] if t['arm'] == arm]
        summary['arms'][arm] = {'folds_accepted': sum(t['fold_accepted'] for t in tasks), 'tasks': len(tasks),
             'compressed_task_success': sum(t.get('successful_compressed_task', False) for t in tasks),
             'raw_fallback_task_success': sum(not t['fold_accepted'] and t.get('score', {}).get('task_success', False) for t in tasks),
             'actor_completed': sum(t.get('actor_state', {}).get('completed', False) for t in tasks)}
    e.write(ROOT / 'summary.json', summary); calls.save(); print(json.dumps(summary), flush=True)


if __name__ == '__main__': asyncio.run(execute(prepare()))
