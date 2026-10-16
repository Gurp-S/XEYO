"""361: fixed semantic product, optional identity directory alongside raw views.

Reuses the 360 native publication, actor and grading; no production switch.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

from evals import wsc_minimal_recovery_trial as base

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-recovery-entry-361')
e = base.e


def entrance(views, index):
    return '\n'.join((f"历史原文存档：{views['compression']}",
                      f"原始消息封套存档：{views['original']}",
                      f"消息/调用身份定位目录：{index.as_posix()}"))


async def prepare():
    await base.prepare()
    prepared = base.load(ROOT/'prepared-private.json')
    plan = base.load(ROOT/'preflight-manifest.json')
    index = next(Path(path) for path in prepared['paths'] if '-evidence-index.' in path)
    views = json.loads(index.read_text(encoding='utf-8').splitlines()[0])['views']
    hybrid = deepcopy(prepared['hot']['directory'])
    hybrid[0]['content'] = prepared['summary'] + '\n\n' + entrance(views, index)
    assert hybrid[0]['content'].startswith(prepared['hot']['direct'][0]['content'] + '\n')
    assert hybrid[1:] == prepared['hot']['direct'][1:] == prepared['hot']['directory'][1:]
    prepared['hot']['hybrid'] = hybrid
    del prepared['hot']['full']
    plan.update(scope=__doc__, arms=['directory','direct','hybrid'], trajectories=24,
        failed_cold_task_reference='No additional full-history call; 360 diagnostic retained separately.',
        code_sha256=base.sha(Path(__file__).read_bytes()),
        base_code_sha256=base.sha(Path(base.__file__).read_bytes()),
        reviews='docs/wsc-recovery-entry-plan-2026-10-16.md')
    e.write(ROOT/'prepared-private.json', prepared)
    e.write(ROOT/'preflight-manifest.json', plan)
    (ROOT/'runner.py').write_bytes(Path(__file__).read_bytes())
    (ROOT/'base-runner.py').write_bytes(Path(base.__file__).read_bytes())


def audit(prepared, report):
    receipts = {b['tool_use_id']: b['content'] for row in prepared['source']
                if isinstance(row.get('content'), list) for b in row['content']
                if b.get('type') == 'tool_result'}
    for branch in report['branches']:
        spec = next(s for s in prepared['tasks'] if s['name'] == branch['task'])
        if not spec['cold']:
            continue
        actor = base.load(ROOT/f"{branch['task']}-{branch['arm']}-{branch['sample']}"/'actor.json')
        texts = [a['result'].get('content','') for a in actor['activity']
                 if a['tool'] in ('Read','Grep') and not a['is_error']]
        targets = [m for m in spec['markers'] if m.startswith('call_')]
        branch['complete_target_receipts_delivered'] = all(any(
            uid in text and json.dumps(receipts[uid], ensure_ascii=False)[1:-1] in text
            for text in texts) for uid in targets)


async def run():
    prepared, plan = base.load(ROOT/'prepared-private.json'), base.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun or HTTP retry'
    assert base.sha(Path(__file__).read_bytes()) == plan['code_sha256']
    assert base.sha(Path(base.__file__).read_bytes()) == plan['base_code_sha256']
    for path, digest in plan['production_sha256'].items():
        assert base.sha(Path(path).read_bytes()) == digest
    e.ROOT = ROOT
    e.CLIENT = base.d.CountedClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    calls = base.d.DiagnosticCalls()
    calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(scope=__doc__, protocol=plan, branches=[])
    calls.save()
    try:
        arms = plan['arms']
        for sample in range(2):
            for number, spec in enumerate(prepared['tasks']):
                start = (sample + number) % len(arms)
                order = arms[start:] + arms[:start]
                if sample:
                    order = order[::-1]
                for arm in order:
                    await base.branch(calls, prepared, spec, arm, sample)
        audit(prepared, calls.report)
        calls.report['completed'] = True
    except Exception as exc:
        calls.report['error'] = type(exc).__name__ + ': ' + str(exc)[:400]
        raise
    finally:
        calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
        calls.save()


async def main():
    base.ROOT = ROOT
    with base.environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_SEMANTIC_HANDOFF='1',
                          WSC_AD_TRANSPORT='httpx-direct')
        await (prepare() if sys.argv[1] == 'prepare' else run())


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
