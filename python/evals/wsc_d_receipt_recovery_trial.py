"""Matched receipt-envelope ablation from one already-paid unanswered turn."""
from copy import deepcopy
import asyncio
import os
from pathlib import Path

import evals.wsc_paid_consumer_continuation as base
from memory.wsc_cold_receipt_candidate import RecordSources, ReceiptSources

ROOT = base.ROOT.parent / 'wsc-D-receipt-recovery-260'
ARMS = ('record_only', 'receipt_envelope')


def prepare():
    assert not ROOT.exists()
    ROOT.mkdir()
    old_plan = base.load(base.OLD / 'preflight-manifest.json')
    old_report = base.load(base.OLD / 'run-report.json')
    sample = next(s for s in old_plan['samples'] if (s['case'], s['arm'], s['mode']) == ('long_noise_task','D_slot','enabled'))
    label = sample['case'] + '-D_slot-enabled-observer-2'
    paid = next(c for c in old_report['calls'] if c['label'] == label)
    parent = base.OLD / (label + '-request.json')
    assert paid['usage_observed'] and base.digest(parent) == paid['request_sha256']
    original = base.load(parent)
    samples, bodies = [], []
    for arm, cls in zip(ARMS, (RecordSources, ReceiptSources)):
        cold = cls(sample['source'], sample['source_sha256'])
        body = deepcopy(original)
        # Record recovery is a common interface change, isolated from the one
        # tested change: automatic exact metadata on decoded result reads.
        body['tools'] = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
            'parameters': t['input_schema']}} for t in cold.schemas()]
        reads = base.append_receipts(body, paid['response']['choices'][0]['message'], cold)
        assert not any(r['is_error'] for r in reads)
        path = ROOT / (arm + '-pending-input.json')
        base.e.write(path, body)
        samples.append({**sample, 'arm': arm, 'input': str(path), 'input_sha256': base.digest(path),
            'parent_request': str(parent), 'parent_request_sha256': base.digest(parent),
            'paid_response_id': paid['response']['id'], 'original_request_count': 3,
            'pending_reads': reads, 'prefix_unchanged': body['messages'][:len(original['messages'])] == original['messages']})
        bodies.append(body)
    left, right = deepcopy(bodies)
    for b in (left, right):
        for message in b['messages'][len(original['messages'])+1:]:
            value = base.json.loads(message['content'])
            value.pop('receipt',None)
            message['content'] = base.f.c.canonical(value)
    assert left == right
    files = [__file__, 'python/evals/wsc_paid_consumer_continuation.py',
        'python/memory/wsc_cold_receipt_candidate.py', 'python/memory/wsc_cold_locator_candidate.py',
        'python/memory/wsc_cold_source_candidate.py', 'python/evals/wsc_ad_experiment.py',
        'python/evals/wsc_elimination_faithful.py']
    plan = {'samples': samples, 'paid_run_allowed': True, 'max_additional_requests_per_sample': 3,
        'extended_total_request_limit': 6, 'output_limit_unchanged': 4096, 'http_retries': 0,
        'proposed_new_run_cost_ceiling_cny': None,
        'hypothesis': 'Literal receipt identity/late metadata reduces execution ambiguity without semantic selection.',
        'single_change': 'Only automatic receipt metadata on payload reads; both arms have identical optional full-record access.',
        'common_protocol_change': 'Both add record view, compared separately from historical257 and no full-chain/cost winner inferred.',
        'code_sha256': {p: base.digest(p) for p in files}, 'no_new_handoff_generation': True,
        'nonclaim': 'One consumer branch, not multi-fold semantic optimization, holdout or production admission.',
        'offline_pair_checks': {'same_prepaid_prefix': True, 'same_schema': True, 'only_receipt_output_differs': True}}
    base.e.write(ROOT/'preflight-manifest.json',plan)
    return plan


async def execute(plan):
    base.ROOT = ROOT
    await base.execute(plan, reader_factory=lambda s: (ReceiptSources if s['arm']=='receipt_envelope' else RecordSources)(s['source'],s['source_sha256']))


if __name__ == '__main__':
    if os.environ.get('WSC_RECEIPT_RECOVERY_EXECUTE') == '1':
        try: asyncio.run(execute(base.load(ROOT/'preflight-manifest.json')))
        except base.f.EvaluationStop as exc: print(base.f.c.canonical({'evaluation_stopped': str(exc)}),flush=True)
    else: print(base.f.c.canonical({'prepared': len(prepare()['samples']), 'api_calls': 0}))
