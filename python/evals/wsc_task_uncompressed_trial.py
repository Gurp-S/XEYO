"""Artifact-task calibration using the frozen P0 initial inputs, no compaction."""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from engine.abort import AbortController
import evals.wsc_ad_experiment as e
from evals.wsc_elimination_faithful import EvaluationStop, StopAwareCalls
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_acceptance_protocol import ArtifactSink, judge, scenarios, sha
from memory.wsc_cold_receipt_candidate import ReceiptSources
from model.deepseek import DeepSeekModelClient
from msgtypes.message import assistant_text_message

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-task-uncompressed-275')
SOURCE = ROOT.parent / 'wsc-task-acceptance-270'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


async def actor(model, messages, tools, sink, cold):
    """Three admitted model calls; actual writes are judged outside the model."""
    request = deepcopy(messages)
    activity = []
    for turn in range(3):
        chunks = [chunk async for chunk in model.stream(request, tools, AbortController())]
        uses = [chunk.tool_use for chunk in chunks if chunk.kind == 'tool_use']
        text = ''.join(chunk.text for chunk in chunks if chunk.kind == 'text_delta')
        thought = ''.join(chunk.text for chunk in chunks if chunk.kind == 'reasoning_delta')
        row = assistant_text_message(text, uses, reasoning=thought)
        request.append({'role': row.role, 'content': row.content})
        if not uses:
            return {'completed': True, 'answer': text, 'activity': activity, 'requests': turn + 1,
                    'pending_messages': request}
        for use in uses:
            error = False
            try:
                value = sink.call(use.input) if use.name == 'ArtifactWrite' else cold.call(use.name, use.input)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                value, error = {'error': str(exc)}, True
            activity.append({'call_id': use.id, 'tool': use.name, 'input': use.input, 'is_error': error, 'result': value})
            request.append({'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': use.id,
                            'content': json.dumps(value, ensure_ascii=False), 'is_error': error}]})
    return {'completed': False, 'reason': 'Three-request cap', 'activity': activity, 'requests': 3,
            'pending_messages': request}


async def execute():
    ROOT.mkdir(exist_ok=False)
    manifest = json.loads((SOURCE / 'preflight-manifest.json').read_text(encoding='utf-8'))
    assert manifest['code_sha256'] == sha(Path('python/evals/wsc_task_acceptance_protocol.py').read_bytes())
    assert json.loads((ROOT.parent / 'wsc-provider-frame-contracts-273/report.json').read_text(encoding='utf-8'))['passed'] == 16
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')
    plan = {'scope': 'Uncompressed two independent synthetic task domains; not WSC or A1/D comparison.',
            'parent': str(SOURCE), 'thinking': 'enabled', 'output_limit': 4096, 'call_limit_per_case': 3,
            'http_retries': 0, 'oracle_outside_model': True, 'production_changes': 0, 'cases': []}
    prepared = []
    for case, item in zip(scenarios(), manifest['cases']):
        info = item['inputs']['uncompressed-actor']
        original = Path(info['path']).read_bytes()
        assert sha(original) == info['sha256']
        body = json.loads(original)
        body['thinking'] = {'type': 'enabled'}
        assert set(k for k in body if body[k] != json.loads(original).get(k)) == {'thinking'}
        initial = ROOT / (case['case'] + '-prepared-input.json')
        save(initial, body)
        plan['cases'].append({'case': case['case'], 'input': str(initial), 'sha256': sha(initial.read_bytes()),
                              'original_input_sha256': info['sha256'], 'source_sha256': item['source_sha256']})
        prepared.append((case, item, body))
    sources = []
    for path in (Path(__file__), Path('python/evals/wsc_provider_frame_candidate.py'), Path('python/evals/wsc_task_acceptance_protocol.py')):
        raw = path.read_bytes()
        (ROOT / path.name).write_bytes(raw)
        sources.append({'path': str(path.resolve()), 'sha256': sha(raw)})
    plan['source_identities'] = sources
    save(ROOT / 'preflight-manifest.json', plan)
    e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(2)
    calls.report.update(protocol=plan, task_results=[])

    async def one(case, item, body):
        cold = ReceiptSources(item['archive'], item['source_sha256'])
        envelope = json.loads(body['messages'][0]['content'])
        sink = ArtifactSink(envelope['artifact_root'])
        assert not (sink.root / 'result.json').exists(), 'No previous artifact is a fresh task success'
        tools = cold.schemas() + [sink.schema()]
        model = ProviderFrameModel(calls, client, case['case'])
        record = {'case': case['case'], 'compressed': False, 'artifact_success': False}
        calls.report['task_results'].append(record)
        try:
            result = await actor(model, body['messages'], tools, sink, cold)
            record.update(result)
        except EvaluationStop:
            record['error'] = 'Run stopped by payment or admission'
        except Exception as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)
        score = judge(sink, case['steps'][0]['expected_artifact'])
        record.update(artifact_success=score['success'], external_judge=score, write_attempts=sink.attempts)
        calls.save()

    await asyncio.gather(*(one(*item) for item in prepared))
    calls.save()
    paid = calls.report['calls']
    summary = {'api_calls': len(paid), 'usage_observed': sum(c['usage_observed'] for c in paid),
               'cost_rate_estimate_cny': sum(c['cost_estimate'] for c in paid),
               'successful_actual_artifacts': sum(r['artifact_success'] for r in calls.report['task_results']),
               'tasks': len(calls.report['task_results']), 'http_retries': 0,
               'nonclaim': 'Calibration only; no compaction quality or method ranking.'}
    save(ROOT / 'summary.json', summary)
    print(json.dumps(summary))


if __name__ == '__main__':
    asyncio.run(execute())
