"""362: fixed paid handoff, native directory entry; only cold rendering differs."""
import asyncio
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from evals import wsc_minimal_recovery_trial as base
from memory import wsc_semantic_evidence as evidence

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-readable-evidence-362')
BASELINE = ROOT.parent/'wsc-readable-362-baseline/wsc_semantic_evidence.py'
e = base.e


async def prepare():
    assert not ROOT.exists(), 'Fresh evidence required'
    ROOT.mkdir()
    spec = importlib.util.spec_from_file_location('sealed_before', BASELINE)
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)
    arms = {}
    current = evidence.publish
    for arm, publish in (('before', before.publish), ('after', current)):
        base.ROOT = ROOT/arm
        with base.environment(base.ROOT):
            os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_SEMANTIC_HANDOFF='1')
            with patch.object(evidence, 'publish', publish):
                await base.prepare()
        prepared = base.load(base.ROOT/'prepared-private.json')
        prepared['hot'] = {arm: prepared['hot']['directory']}
        arms[arm] = prepared
    assert arms['before']['source'] == arms['after']['source']
    assert arms['before']['summary'] == arms['after']['summary']
    assert arms['before']['hot']['before'][1:] == arms['after']['hot']['after'][1:]
    (ROOT/'work').mkdir()
    system = await base.PromptAssembler().build_system(cwd=str(ROOT/'work'), workspace_root=str(ROOT/'work'),
        model='deepseek-flash', tool_names=['Read','Grep','Write'], date_iso='2026-10-16')
    for item in arms.values():
        item['system'] = system
    plan = base.load(ROOT/'after/preflight-manifest.json')
    plan.update(scope=__doc__, arms=list(arms), trajectories=16,
        failed_cold_task_reference='No additional paid reference or rerun; prior reference retained separately.',
        code_sha256=base.sha(Path(__file__).read_bytes()), base_code_sha256=base.sha(Path(base.__file__).read_bytes()),
        baseline_sha256=base.sha(BASELINE.read_bytes()),
        reviews='docs/wsc-readable-evidence-plan-2026-10-16.md')
    plan['production_sha256']['python/memory/wsc_evidence_readable.py'] = base.sha(Path('python/memory/wsc_evidence_readable.py').read_bytes())
    e.write(ROOT/'prepared-private.json', arms)
    e.write(ROOT/'preflight-manifest.json', plan)
    (ROOT/'runner.py').write_bytes(Path(__file__).read_bytes())
    (ROOT/'base-runner.py').write_bytes(Path(base.__file__).read_bytes())


async def run():
    arms, plan = base.load(ROOT/'prepared-private.json'), base.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun or HTTP retry'
    assert base.sha(Path(__file__).read_bytes()) == plan['code_sha256']
    assert base.sha(Path(base.__file__).read_bytes()) == plan['base_code_sha256']
    assert base.sha(BASELINE.read_bytes()) == plan['baseline_sha256']
    for path, digest in plan['production_sha256'].items():
        assert base.sha(Path(path).read_bytes()) == digest
    base.ROOT = e.ROOT = ROOT
    e.CLIENT = base.d.CountedClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    calls = base.d.DiagnosticCalls()
    calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(scope=__doc__, protocol=plan, branches=[])
    calls.save()
    try:
        for sample in range(2):
            for number, task in enumerate(arms['before']['tasks']):
                order = ('before','after') if (sample+number) % 2 == 0 else ('after','before')
                for arm in order:
                    await base.branch(calls, arms[arm], task, arm, sample)
        for item in arms.values():
            for path, digest in item['objects'].items():
                assert base.sha(Path(path).read_bytes()) == digest
        calls.report['completed'] = True
    except Exception as exc:
        calls.report['error'] = type(exc).__name__ + ': ' + str(exc)[:400]
        raise
    finally:
        calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
        calls.save()


async def main():
    with base.environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_SEMANTIC_HANDOFF='1',
                          WSC_AD_TRANSPORT='httpx-direct')
        await (prepare() if sys.argv[1] == 'prepare' else run())


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
