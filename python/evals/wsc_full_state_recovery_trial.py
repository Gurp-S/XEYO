"""Recover a real rejected declaration using its exact paid prefix.

The original schema stays fixed to isolate mechanical recovery. Prefix length
and remaining slots are recorded per cohort, within the native six requests.
Paid requests are byte-checked and replayed free; old scores stay intact.
"""
import asyncio
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

from engine.abort import AbortController
import evals.wsc_ad_experiment as e
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_elimination_faithful import EvaluationStop, StopAwareCalls
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_actor_candidate import new_state, run, grade
from evals.wsc_task_acceptance_protocol import canonical, sha
from memory.wsc_cold_receipt_candidate import ReceiptSources
from memory.wsc_handoff_control import split_messages
from memory.wsc_handoff_generation import generate
from memory.wsc_handoff_validation import validate
from model.deepseek import DeepSeekModelClient
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

RUN = os.environ.get('WSC_RECOVERY_RUN', 'wsc-full-state-recovery-299')
assert RUN in {'wsc-full-state-recovery-299', 'wsc-batch-recovery-302'}
ROOT = Path('D:/lea/XenYon code/_wsc_out') / RUN
BATCH = RUN.endswith('302')
OLD = ROOT.parent / ('wsc-split-control-fixed-schema-300' if BATCH else 'wsc-split-control-continuation-296')
CASE = 'handoff_record' if BATCH else 'asset_manifest'
PREFIX_COUNT = 2 if BATCH else 4
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')


def old_schema():
    manifest = json.loads((OLD / 'preflight-manifest.json').read_text(encoding='utf-8'))
    path = OLD / 'wsc_handoff_generation.py'
    assert sha(path.read_bytes()) == manifest['source_identities'][str(Path('python/memory/wsc_handoff_generation.py'))]
    spec = importlib.util.spec_from_file_location('sealed_generation296', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.source_schema


class CapturedNext(BaseException):
    pass


async def preflight_prefix(plan, prefix):
    sample = plan['sample']
    rows = [json.loads(line) for line in Path(sample['source']).read_text(encoding='utf-8').splitlines()]
    class Capture:
        def __init__(self): self.index = 0; self.next_body = None
        async def call(self, body, label):
            index = self.index; self.index += 1
            if index >= len(prefix):
                self.next_body = deepcopy(body)
                raise CapturedNext()
            old = prefix[index]; path = OLD / (old['label'] + '-request.json')
            assert sha(path.read_bytes()) == old['request_sha256']
            assert body == json.loads(path.read_text(encoding='utf-8'))
            return deepcopy(old['response'])
    capture = Capture()
    with patch('memory.wsc_handoff_generation.source_schema', old_schema()), patch('memory.wsc_handoff_control.messages', split_messages):
        try:
            await generate(ProviderFrameModel(capture, CLIENT, 'preflight'), sample['before'], rows,
                TodoWriteTool().schema(), AbortController(), account=lambda usage: None, scope_protocol=True)
        except CapturedNext: pass
    assert capture.index == len(prefix) + 1 and capture.next_body is not None
    e.write(ROOT / 'next-input.json', capture.next_body)
    return {'paid_prefix_requests_equal': len(prefix), 'next_request_captured': True, 'new_api_calls': 0}


async def prepare():
    ROOT.mkdir(exist_ok=False)
    previous = json.loads((OLD / 'run-report.json').read_text(encoding='utf-8'))
    manifest = previous['protocol']
    sample = next(s for s in manifest['samples'] if s['case'] == CASE and s['arm'] == 'D_split')
    prefix = [c for c in previous['calls'] if c['label'].startswith(CASE + '-D_split-handoff-')]
    assert len(prefix) == PREFIX_COUNT and all(c['usage_observed'] for c in prefix)
    old_schema()  # Adapter/source preparation errors precede any paid transport.
    plan = {'scope': __doc__, 'sample': sample, 'prefix_labels': [c['label'] for c in prefix],
            'proposed_new_run_cost_ceiling_cny': 0.4, 'per_call_limit_cny': 2.5, 'http_retries': 0,
            'native_max_requests': 6, 'old_paid_prefix_requests': len(prefix), 'remaining_new_generation_requests': 6 - len(prefix),
            'actor_max_requests': 6, 'new_api_call_ceiling': 12 - len(prefix),
            'schema_condition': 'Original cohort schema unchanged for exact prefix replay; complete-state schema has separate contract evidence.',
            'artifact_scope': 'New isolated artifact_root after repaired declaration; original cohort artifacts and scores remain untouched.',
            'expected_artifact': manifest['private_expectations'][CASE], 'source_identities': {}}
    for path in [Path(__file__), Path('python/memory/wsc_handoff_generation.py'), Path('python/memory/wsc_handoff_schema.py'),
                 Path('python/memory/wsc_handoff_validation.py'), Path('python/memory/wsc_handoff_control.py'),
                 Path('python/memory/wsc_handoff_batch.py')]:
        raw = path.read_bytes(); plan['source_identities'][str(path)] = sha(raw)
        (ROOT / path.name).write_bytes(raw)
    plan['prefix_preflight'] = await preflight_prefix(plan, prefix)
    e.write(ROOT / 'preflight-manifest.json', plan)
    return plan


async def execute(plan):
    assert not (ROOT / 'run-report.json').exists()
    for path, digest in plan['source_identities'].items(): assert sha(Path(path).read_bytes()) == digest
    previous = json.loads((OLD / 'run-report.json').read_text(encoding='utf-8'))
    prefix = [next(c for c in previous['calls'] if c['label'] == label) for label in plan['prefix_labels']]
    sample = plan['sample']; source = Path(sample['source'])
    assert sha(source.read_bytes()) == sample['source_sha256']
    rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()]
    schema_adapter = old_schema()
    next_input = json.loads((ROOT / 'next-input.json').read_text(encoding='utf-8'))
    e.ROOT = ROOT; os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls(); calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(protocol=plan, paid_prefix_replays=[], fold_accepted=False); calls.save()
    original = calls.call
    async def bounded(body, label):
        if len(calls.report['calls']) >= plan['new_api_call_ceiling']: raise EvaluationStop('New call ceiling reached')
        return await original(body, label)
    calls.call = bounded
    class Prefix:
        def __init__(self): self.index = 0
        async def call(self, body, label):
            index = self.index; self.index += 1
            if index >= len(prefix):
                if index == len(prefix): assert body == next_input, 'Prepared continuation changed'
                return await calls.call(body, label)
            old = prefix[index]
            path = OLD / (old['label'] + '-request.json')
            assert sha(path.read_bytes()) == old['request_sha256']
            assert body == json.loads(path.read_text(encoding='utf-8')), 'Paid prefix request changed'
            calls.report['paid_prefix_replays'].append({'old_label': old['label'], 'request_body_equal': True,
                                                        'request_sha256': old['request_sha256'], 'new_api': False})
            calls.save()
            return deepcopy(old['response'])
    transport = Prefix()
    try:
        with patch('memory.wsc_handoff_generation.source_schema', schema_adapter), patch('memory.wsc_handoff_control.messages', split_messages):
            use = await generate(ProviderFrameModel(transport, CLIENT, 'recovered-handoff'), sample['before'], rows,
                TodoWriteTool().schema(), AbortController(), account=lambda usage: None, scope_protocol=True)
        parsed = validate(use.input, rows, require_phase=True)
        calls.report.update(fold_accepted=True, candidate=use.input, presentation=use.presentation)
        hot = [{'role': 'assistant', 'content': canonical({'todos': use.input['todos'], 'checkpoint': parsed.checkpoint})}]
    except EvaluationStop: raise
    except Exception as exc:
        calls.report['generation_error'] = type(exc).__name__ + ': ' + str(exc)
        calls.report['completed'] = True
        calls.save()
        raise  # This diagnostic does not pay for a raw-fallback task on setup failure.
    calls.save()
    sink = ExactArtifactSink(ROOT / 'artifacts')
    cold = ReceiptSources(source, sample['source_sha256'])
    messages = [*hot, {'role': 'user', 'content': canonical({'archive': cold.locator(), 'artifact_root': str(sink.root)})},
                {'role': 'user', 'content': '继续当前任务。'}]
    state = new_state(messages)
    def checkpoint(value):
        calls.report['actor_state'] = value; e.write(ROOT / 'actor-checkpoint.json', value); calls.save()
    try:
        await run(ProviderFrameModel(calls, CLIENT, 'recovered-actor'), state, cold.schemas() + [sink.schema()],
                  sink, cold, additional_requests=6, checkpoint=checkpoint)
    except EvaluationStop: raise
    except Exception as exc: calls.report['actor_error'] = type(exc).__name__ + ': ' + str(exc)
    score = grade(sink, plan['expected_artifact'])
    calls.report.update(score=score, compressed_task_success=calls.report['fold_accepted'] and score['task_success'], completed=True)
    calls.save()
    result = {'fold_accepted': calls.report['fold_accepted'], 'compressed_task_success': calls.report['compressed_task_success'],
              'normal_end': state['completed'], 'paid_prefix_replays': len(calls.report['paid_prefix_replays']),
              'new_api_calls': len(calls.report['calls']), 'new_usage': sum(c['usage_observed'] for c in calls.report['calls']),
              'new_cost_rate_estimate_cny': sum(c['cost_estimate'] for c in calls.report['calls']),
              'generation_error': calls.report.get('generation_error'), 'actor_error': calls.report.get('actor_error')}
    e.write(ROOT / 'summary.json', result); print(canonical(result), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--execute', action='store_true'); args = parser.parse_args()
    if not args.execute:
        asyncio.run(prepare()); print(canonical({'prepared': str(ROOT), 'new_api_calls': 0}))
    else:
        try: asyncio.run(execute(json.loads((ROOT / 'preflight-manifest.json').read_text(encoding='utf-8'))))
        except EvaluationStop as exc: print(canonical({'evaluation_stopped': str(exc)}), flush=True)
