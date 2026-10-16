"""Continue the paid 275 config branch, preserving the old three-call failure."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_elimination_faithful import EvaluationStop, StopAwareCalls
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_actor_candidate import adopt_paid_frames, new_state, run, grade
from evals.wsc_task_acceptance_protocol import scenarios, sha
from memory.wsc_cold_receipt_candidate import ReceiptSources
from model.deepseek import DeepSeekModelClient

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-task-paid-resume-279')
OLD = ROOT.parent / 'wsc-task-uncompressed-275'


async def main():
    ROOT.mkdir(exist_ok=False)
    old_report = json.loads((OLD / 'run-report.json').read_text(encoding='utf-8'))
    old_plan = json.loads((OLD / 'preflight-manifest.json').read_text(encoding='utf-8'))
    saved = next(r for r in old_report['task_results'] if r['case'] == 'config_conversion')
    assert saved['requests'] == 3 and not saved['completed'] and not saved['write_attempts']
    paid = [r for r in old_report['calls'] if r['label'].startswith('config_conversion-provider-')]
    assert len(paid) == 3 and all(r['usage_observed'] for r in paid)
    for call in paid:
        assert sha((OLD / (call['label'] + '-request.json')).read_bytes()) == call['request_sha256']
    initial = json.loads((OLD / 'config_conversion-prepared-input.json').read_text(encoding='utf-8'))
    envelope = json.loads(initial['messages'][0]['content'])
    sink = ExactArtifactSink(envelope['artifact_root'])
    assert not (sink.root / 'result.json').exists()
    item = next(r for r in old_plan['cases'] if r['case'] == 'config_conversion')
    source_plan = json.loads((ROOT.parent / 'wsc-task-acceptance-270/preflight-manifest.json').read_text(encoding='utf-8'))
    archive = next(r for r in source_plan['cases'] if r['case'] == 'config_conversion')['archive']
    cold = ReceiptSources(archive, item['source_sha256'])
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')
    e.ROOT = ROOT; os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls(); calls.semaphore = asyncio.Semaphore(1)
    model = ProviderFrameModel(calls, client, 'config_conversion')
    adopt_paid_frames(model, paid)
    state = new_state(saved['pending_messages'])
    state.update(activity=deepcopy(saved['activity']), requests_attempted=3)
    tools = cold.schemas() + [sink.schema()]
    pending = model.body(state['pending_messages'], tools)
    last = json.loads((OLD / (paid[-1]['label'] + '-request.json')).read_text(encoding='utf-8'))
    assert pending['messages'][:len(last['messages'])] == last['messages']
    assert {k:v for k,v in pending.items() if k != 'messages'} == {k:v for k,v in last.items() if k != 'messages'}
    plan = {'scope': 'New logical continuation only; old three-request score unchanged.', 'reused_calls': 3,
            'additional_call_limit': 3, 'extended_total_limit': 6, 'output_limit': 4096,
            'thinking': 'enabled', 'cold_interface_unchanged': True, 'http_retries': 0,
            'prefix_verified_equal': True, 'code_sha256': {p:sha(Path(p).read_bytes()) for p in
            [__file__, 'python/evals/wsc_task_actor_candidate.py', 'python/evals/wsc_artifact_bytes_candidate.py',
             'python/evals/wsc_provider_frame_candidate.py']}}
    e.write(ROOT / 'preflight-manifest.json', plan)
    calls.report.update(protocol=plan, actor_state=state)
    def checkpoint(value): calls.report['actor_state'] = value; calls.save()
    try:
        await run(model, state, tools, sink, cold, additional_requests=3, checkpoint=checkpoint)
    except EvaluationStop:
        calls.report['error'] = 'Run stopped by payment or admission'
    except Exception as exc:
        calls.report['error'] = type(exc).__name__ + ': ' + str(exc)
    expected = next(c for c in scenarios() if c['case'] == 'config_conversion')['steps'][0]['expected_artifact']
    score = grade(sink, expected)
    calls.report['score'] = score; calls.save()
    rows = calls.report['calls']
    summary = {'new_api_calls': len(rows), 'usage_observed': sum(r['usage_observed'] for r in rows),
        'cost_rate_estimate_cny': sum(r['cost_estimate'] for r in rows), 'task_success': score['task_success'],
        'actor_completed': state['completed'], 'total_actor_requests': state['requests_attempted'],
        'old_three_request_result_unchanged': True}
    e.write(ROOT / 'summary.json', summary)
    print(json.dumps(summary))


if __name__ == '__main__': asyncio.run(main())
