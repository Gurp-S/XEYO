"""Independent split/legacy source-controlled trial; reuses294 task protocol."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import evals.wsc_control_origin_trial as trial
from memory.wsc_handoff_control import legacy_messages, split_messages

RUN = os.environ.get('WSC_SPLIT_RUN', 'wsc-split-control-continuation-296')
assert RUN in {'wsc-split-control-continuation-296', 'wsc-split-control-fixed-schema-300'}
ROOT = Path('D:/lea/XenYon code/_wsc_out') / RUN


def switch(arm):
    return patch('memory.wsc_handoff_control.messages',
                 split_messages if arm == 'D_split' else legacy_messages)


def configure():
    trial.ROOT = ROOT
    trial.ARMS = ('D_legacy', 'D_split')
    trial.switch = switch


async def prepare():
    configure()
    plan = await trial.prepare()
    plan.update(comparison='Independent same-source legacy vs split carriers, same current Guard, schema, recovery and actor. No A1 resampling or historical score pooling.',
                proposed_new_run_cost_ceiling_cny=0.8,
                api_call_ceiling=60,
                role_content_ablation='294 separately measures legacy user command, factual user and factual system; those raw failures and scores remain unchanged.',
                objective='Source task objective, unfinished write, delivery applicability, constraints, resolved question and physical artifact must all remain correct.')
    if RUN.endswith('300'):
        plan['independent_cohort'] = ('Both arms use297 complete-state schema and bounded mechanical recovery. '
            'Only invocation carriers differ; old294/296/298/299 failures and scores are not pooled or overwritten.')
    path = Path(__file__); raw = path.read_bytes()
    plan['source_identities'][str(path)] = trial.sha(raw)
    (ROOT / path.name).write_bytes(raw)
    trial.e.write(ROOT / 'preflight-manifest.json', plan)
    return plan


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        plan = await prepare()
        print(json.dumps({'prepared': str(ROOT), 'samples': len(plan['samples']), 'api_calls': 0}), flush=True)
        return
    configure()
    assert not (ROOT / 'run-report.json').exists(), 'Existing run evidence cannot be restarted'
    plan = json.loads((ROOT / 'preflight-manifest.json').read_text(encoding='utf-8'))
    try: await trial.execute(plan)
    except trial.EvaluationStop as exc: print(json.dumps({'evaluation_stopped': str(exc)}), flush=True)


if __name__ == '__main__': asyncio.run(main())
