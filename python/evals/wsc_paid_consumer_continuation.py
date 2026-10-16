"""Resume unanswered, already-paid consumer turns without HTTP replay.

Original request messages and the full returned reasoning/tool calls are kept.
Only new read-only tool receipts and subsequent requests are appended. This is
a separately scored request-quota extension, not a repair of historical scores.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
from evals.wsc_answer_parse import parse
from memory.wsc_cold_locator_candidate import AddressedSources

ROOT = e.ROOT.parent / 'wsc-D-paid-continuation-257'
OLD = ROOT.parent / 'wsc-D-consumer-mode-255'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def append_receipts(body, reply, cold):
    uses = reply.get('tool_calls') or []
    assert uses, 'Only unanswered tool turns can resume without replaying HTTP'
    before = deepcopy(body['messages'])
    body['messages'].append(deepcopy(reply))
    reads = []
    for use in uses:
        try:
            value = cold.call(use['function']['name'], json.loads(use['function']['arguments']))
            error = False
        except (ValueError, KeyError, TypeError) as exc:
            value = {'error': str(exc)}
            error = True
        body['messages'].append({'role': 'tool', 'tool_call_id': use['id'], 'content': f.c.canonical(value)})
        reads.append({'tool': use['function']['name'], 'args': use['function']['arguments'], 'is_error': error})
    assert body['messages'][:len(before)] == before
    return reads


def prepare():
    assert not ROOT.exists()
    ROOT.mkdir()
    old_report = load(OLD / 'run-report.json')
    old_plan = load(OLD / 'preflight-manifest.json')
    samples = []
    for arm in ('A1', 'D_slot'):
        sample = next(s for s in old_plan['samples'] if (s['case'], s['arm'], s['mode']) == ('long_noise_task', arm, 'enabled'))
        previous = next(o for o in old_report['observations'] if all(o[k] == sample[k] for k in ('case', 'arm', 'mode')))
        assert previous['error'] == 'Three-request cap; no final answer'
        label = f"{sample['case']}-{arm}-enabled-observer-2"
        paid = next(c for c in old_report['calls'] if c['label'] == label)
        assert paid['usage_observed']
        request = OLD / (label + '-request.json')
        body = load(request)
        assert digest(request) == paid['request_sha256']
        original = deepcopy(body)
        cold = AddressedSources(sample['source'], sample['source_sha256'])
        reads = append_receipts(body, paid['response']['choices'][0]['message'], cold)
        assert not any(r['is_error'] for r in reads)
        assert {k: v for k, v in body.items() if k != 'messages'} == {k: v for k, v in original.items() if k != 'messages'}
        new = ROOT / (arm + '-pending-input.json')
        e.write(new, body)
        samples.append({**sample, 'input': str(new), 'input_sha256': digest(new), 'parent_request': str(request),
            'parent_request_sha256': digest(request), 'paid_response_id': paid['response']['id'],
            'original_request_count': 3, 'pending_reads': reads, 'prefix_unchanged': True})
    files = [__file__, 'python/evals/wsc_ad_experiment.py', 'python/evals/wsc_elimination_faithful.py',
        'python/memory/wsc_cold_locator_candidate.py', 'python/memory/wsc_cold_source_candidate.py']
    plan = {'samples': samples, 'paid_run_allowed': True, 'max_additional_requests_per_sample': 3,
        'original_request_limit': 3, 'extended_total_request_limit': 6, 'output_limit_unchanged': 4096,
        'http_retries': 0, 'old_results_unchanged': True, 'no_new_handoff_generation': True,
        'candidate_read_default_used': False,
        'proposed_new_run_cost_ceiling_cny': None,
        'intent': 'Spend only on previously unsent logical continuations with exact already-paid prefix; extend both arms equally.',
        'nonclaim': 'Not the original three-request protocol, not an independent task or a read-interface A/B.',
        'code_sha256': {p: digest(p) for p in files}}
    e.write(ROOT / 'preflight-manifest.json', plan)
    return plan


async def execute(plan, *, reader_factory=None):
    assert plan['paid_run_allowed'] and not (ROOT / 'run-report.json').exists()
    for path, seal in plan['code_sha256'].items():
        assert digest(path) == seal
    e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = f.StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(2)
    calls.report.update(protocol=plan, observations=[])
    gold = load(e.OLD / 'gold.json')

    async def one(sample):
        path = Path(sample['input'])
        assert digest(path) == sample['input_sha256']
        body = load(path)
        cold = (reader_factory(sample) if reader_factory is not None
            else AddressedSources(sample['source'], sample['source_sha256']))
        rows = [json.loads(s) for s in Path(sample['source']).read_text(encoding='utf-8').splitlines()]
        record = {**sample, 'reads': [], 'grade': None, 'state_success': False, 'cold_exact': False}
        try:
            for n in range(plan['max_additional_requests_per_sample']):
                answer = await calls.call(body, sample['arm'] + f'-new-continuation-{n}')
                choice = answer['choices'][0]
                reply = choice['message']
                if choice['finish_reason'] == 'length':
                    record.update(error='Output truncated; not retried', finish_reason='length')
                    break
                if not reply.get('tool_calls'):
                    value, strict = parse(reply.get('content') or '')
                    parsed = value if isinstance(value, dict) else {}
                    grade = {k: type(parsed.get(k)) is type(v) and parsed.get(k) == v for k, v in sample['expected'].items()}
                    provenance = parsed.get('provenance') or {}
                    uid, quote = provenance.get('source_message_id'), provenance.get('quote')
                    found = [r for r in rows if r['id'] == uid]
                    valid = len(found) == 1 and uid in sample['phase_sources'] and isinstance(quote, str) and bool(quote) and quote in e.source_text(found[0]['content'])
                    record.update(parsed=parsed, strict_json=strict, grade=grade, provenance_valid=valid,
                        state_success=all(grade.values()) and valid,
                        cold_exact=parsed.get('cold_excerpt') == gold[sample['case']]['cold_excerpt']['expected'],
                        finish_reason=choice['finish_reason'])
                    break
                record['reads'].extend(append_receipts(body, reply, cold))
            if record['grade'] is None and 'error' not in record:
                record['error'] = 'Extended six-request cap; no final answer'
        finally:
            # Pending receipts survive any payment/run stop, without discarding
            # the previous paid response or requiring another HTTP generation.
            e.write(ROOT / (sample['arm'] + '-pending-state.json'), body)
            calls.report['observations'].append(record)
            calls.save()
        print(f.c.canonical({'arm': sample['arm'], 'state_success': record['state_success'],
            'cold_exact': record['cold_exact'], 'grade': record['grade'], 'error': record.get('error')}), flush=True)

    results = await asyncio.gather(*(one(s) for s in plan['samples']), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    calls.report['completed'] = True
    calls.save()


if __name__ == '__main__':
    if os.environ.get('WSC_PAID_CONTINUATION_EXECUTE') == '1':
        try:
            asyncio.run(execute(load(ROOT / 'preflight-manifest.json')))
        except f.EvaluationStop as exc:
            print(f.c.canonical({'evaluation_stopped': str(exc)}), flush=True)
    else:
        print(f.c.canonical({'prepared': len(prepare()['samples']), 'api_calls': 0}))
