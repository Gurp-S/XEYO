"""335 own-output ten-generation before/after, plus cold recovery diagnostics.

Uses actual production generation/publication and the existing artifact actor.
Historical baseline functions are loaded from the pre-edit snapshot. No retries.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import evals.wsc_semantic_production_trial as trial
from evals.wsc_recall_projection import ROOT, baseline
from model.deepseek import DeepSeekModelClient
from memory.token import token_len


class CountedClient(DeepSeekModelClient):
    def context_token_measure(self, source):
        measured = super().context_token_measure(source)
        return measured or (token_len(json.dumps(source, ensure_ascii=False)), 'utf8_quarter_estimate')


def configure():
    from memory import wsc_semantic_generation as generation, wsc_semantic_compaction as compaction
    from memory import wsc_semantic_evidence as evidence, wsc_evidence_index as index
    modules = [generation, compaction, evidence, index]
    methods = ['generate', 'prepare', 'publish', 'records']
    current = [getattr(m, key) for m, key in zip(modules, methods)]
    old = [getattr(baseline(m.__name__), key) for m, key in zip(modules, methods)]
    def activate(before):
        for m, key, value in zip(modules, methods, old if before else current): setattr(m, key, value)
    return activate


async def cold(calls, arm, *, recall):
    """Missing value is available only in the exact source, not the hot state."""
    from memory.wsc_semantic_generation import generate
    from engine.abort import AbortController
    p = trial.t.p
    rows = [{'id': f'noise-{i}', 'role': 'assistant', 'content': f'Archive event {i}; completed unrelated task.'} for i in range(40)]
    rows.insert(17, {'id': 'report-config', 'role': 'user', 'content': '审计报告的账户标识为acct-cedar-29，校验数=85317；报告不得发布。'})
    rows.append({'id': 'current-request', 'role': 'user', 'content': '继续生成审计报告，账户标识和校验数以原始配置为准。'})
    visible = [{'role': 'assistant', 'content': '当前任务是生成审计报告；账户标识和校验数在原始配置中，当前交接没有记录具体值。不得发布。'}]
    model = p.ProviderFrameModel(calls, p.e.CLIENT, arm+'-cold-generator', 1024)
    text = await generate(model, visible, AbortController(), sources=rows if recall else None,
                          account=lambda _: None, output_tokens=1024) if recall else await generate(
                              model, visible, AbortController(), account=lambda _: None, output_tokens=1024)
    record = {'arm': arm, 'summary': text, 'requests': model.state['counter'],
        'account_retained': 'acct-cedar-29' in text, 'exact_value_retained': '85317' in text}
    calls.report.setdefault('cold_generation', []).append(record); calls.save()


async def main():
    p = trial.t.p
    root = ROOT / 'api'
    assert not root.exists(), 'No paid rerun'
    root.mkdir()
    trial.ROOT = root; p.e.ROOT = root
    p.e.CLIENT = CountedClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    os.environ['WSC_AD_READ_TIMEOUT'] = '55'
    plan = {'scope': __doc__, 'arms': ['semantic_before', 'semantic_after'], 'events': trial.t.scenario(),
        'concurrent_http_requests': 1, 'http_retries': 0, 'per_call_cny_max': 2.5,
        'pricing': {'source': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
                    'peak_cny_per_million': {'miss': 2, 'hit': .04, 'output': 8},
                    'cost_report': 'peak-rate upper estimate; off-peak is half; not an invoice'},
        'trigger': 'Each event explicitly invokes native compaction; no reliance on small task reaching85%.',
        'scope_limits': ['one controlled task family, not ten independent tasks',
                         'actual source projection/restart; not live query_loop85% admission',
                         'cold generation diagnostic is separate from multi-generation task score'],
        'quality_gate': 'No lower task/state/concrete-value quality than paired before; no extra stale revivals.',
        'source_code_sha256': p.sha(Path(__file__).read_bytes())}
    p.e.write(root/'preflight-manifest.json', plan)
    calls = trial.ValidatedCalls(); calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(protocol=plan, branches=[])
    activate = configure()
    with trial.t.environment(root):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1')
        for before, arm in [(True, 'semantic_before'), (False, 'semantic_after')]:
            activate(before)
            await trial.branch(calls, arm)
            if getattr(calls, 'evaluation_stopped', False): break
            await cold(calls, arm, recall=not before)
    activate(False)
    calls.report['completed'] = not getattr(calls, 'evaluation_stopped', False)
    calls.report['cost_estimate_cny'] = sum(c['cost_estimate'] for c in calls.report['calls'])
    calls.save()
    print(json.dumps({'completed': calls.report['completed'], 'calls': len(calls.report['calls']),
                      'cost_peak_cny': calls.report['cost_estimate_cny']}), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
