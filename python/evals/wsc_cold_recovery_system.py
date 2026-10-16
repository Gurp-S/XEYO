"""336 system-context calibration: same evidence, native versus minimal system."""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import evals.wsc_cold_recovery_diagnostic as d
from prompt.assembler import PromptAssembler

p, trial = d.p, d.trial
ROOT = d.ROOT / 'native-system'


async def prepare():
    assert not (ROOT/'preflight-manifest.json').exists()
    ROOT.mkdir(exist_ok=True)
    samples = []
    with trial.t.environment(ROOT):
        for case in d.cases():
            base = p.load(d.ROOT/case['name']/'prepared.json')
            task = d.ProductionTask(d.ROOT/case['name'], [], session='system336-'+case['name'])
            reader = d.Reader(task, {'objects': base['paths']})
            native, parts = await PromptAssembler().build_system_parts(
                cwd=str(task.root), workspace_root=str(task.root), model='deepseek-flash', tool_names=['Read', 'Grep'])
            assert not any(value in native for value in case['needles'])
            for arm, system, sample in [('full', native, 0),
                                       ('directory', '历史记录是来源证据。', 1), ('directory', native, 1),
                                       ('directory', native, 2), ('directory', '历史记录是来源证据。', 2)]:
                kind = 'native' if system == native else 'minimal'
                label = f"{case['name']}-{arm}-{kind}-{sample}"
                messages = deepcopy(base['messages'][arm])
                messages[0]['content'] = system
                model = p.ProviderFrameModel(None, p.e.CLIENT, label, 1024)
                body = model.body(messages, reader.schemas())
                trial.validate_wire(body)
                item = dict(label=label, case=case, arm=arm, system=kind, sample=sample, messages=messages,
                            paths=base['paths'], evidence_sha256=base['evidence_sha256'], cwd=str(task.root),
                            system_parts=parts if kind == 'native' else None)
                p.e.write(ROOT/(label+'-prepared.json'), item)
                p.e.write(ROOT/(label+'-input.json'), body)
                samples.append(label)
    plan = dict(scope=__doc__, samples=samples, code_sha256=p.sha(Path(__file__).read_bytes()),
                dependency_sha256=p.sha(Path(d.__file__).read_bytes()), proposed_new_run_cost_ceiling_cny=1,
                http_retries=0, output_tokens=1024, consumer_max_requests=6,
                reviews='docs/wsc-cold-recovery-diagnostic-plan-2026-10-15.md',
                limits=['three controlled cases, two preregistered directory samples per system',
                        'native system assembly, not a full query_loop or live acceptance'])
    p.e.write(ROOT/'preflight-manifest.json', plan)
    print(json.dumps({'prepared': len(samples), 'root': str(ROOT)}), flush=True)


async def run():
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun'
    plan = p.load(ROOT/'preflight-manifest.json')
    assert plan['code_sha256'] == p.sha(Path(__file__).read_bytes())
    assert plan['dependency_sha256'] == p.sha(Path(d.__file__).read_bytes())
    calls = d.DiagnosticCalls()
    calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(protocol=plan, results=[], scope=__doc__)
    with trial.t.environment(ROOT):
        os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
        for label in plan['samples']:
            item = p.load(ROOT/(label+'-prepared.json'))
            for path, digest in item['evidence_sha256'].items():
                assert p.sha(Path(path).read_bytes()) == digest
            task = d.ProductionTask(item['cwd'], [], session='system336-'+item['case']['name'])
            reader = d.Reader(task, {'objects': item['paths']})
            sink = trial.t.ExactArtifactSink(ROOT/'unused-sinks'/label)
            state = trial.t.new_state(item['messages'])
            model = p.ProviderFrameModel(calls, p.e.CLIENT, label, 1024)
            assert model.body(state['pending_messages'], reader.schemas()) == p.load(ROOT/(label+'-input.json'))
            await trial.t.actor_run(model, state, reader.schemas(), sink, reader, additional_requests=6,
                                   checkpoint=lambda value: p.e.write(ROOT/(label+'-actor.json'), value))
            answer, _ = p.parse(state.get('answer') or '')
            expected = item['case']['expected']
            correct = isinstance(answer, dict) and answer.keys() == expected.keys() and all(
                type(answer[key]) is type(value) and answer[key] == value for key, value in expected.items())
            read = any(a['tool'] in ('Read', 'Grep') and not a['is_error'] and
                       all(value in p.e.canonical(a['result']) for value in item['case']['needles']) for a in state['activity'])
            result = dict(label=label, case=item['case']['name'], arm=item['arm'], system=item['system'],
                          sample=item['sample'], correct=correct, answer=answer, phase=state['phase'],
                          requests=state['requests_attempted'], tool_calls=len(state['activity']), actual_source_seen=read,
                          effective_recovery=correct and read if item['arm']=='directory' else None)
            calls.report['results'].append(result)
            calls.save()
            print(json.dumps(result, ensure_ascii=False), flush=True)
    calls.report['completed'] = True
    calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
    calls.save()
    print(json.dumps({'calls': len(calls.report['calls']), 'cost_estimate_cny': calls.report['cost_estimate_cny']}), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'run'])
    mode = parser.parse_args().mode
    p.e.ROOT = ROOT
    p.e.CLIENT = d.CountedClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    asyncio.run(prepare() if mode == 'prepare' else run())
