"""Existing SourceRead capability ablation on unchanged308 handoff messages."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys

import evals.wsc_semantic_format_pilot as p
from evals.wsc_semantic_format_consumer_recheck import AccessibleSealedRead
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_task_actor_candidate import new_state, run as actor_run, grade as actor_grade
from memory.wsc_cold_receipt_candidate import ReceiptSources
from engine.abort import AbortController
from msgtypes.message import ToolUse

ROOT = p.ROOT.parent/'wsc-source-read-continuation-310'
GENERATION = p.ROOT
BASELINE = ROOT.parent/'wsc-factorial-consumer-correction-308'


class RootMappedSink(ExactArtifactSink):
    """Same logical artifact namespace; a fresh physical sandbox owns writes."""
    def __init__(self, logical_root, physical_root):
        self.logical_root = Path(logical_root).resolve()
        super().__init__(physical_root)

    def call(self, args):
        mapped = deepcopy(args)
        if isinstance(mapped, dict) and isinstance(mapped.get('file_path'), str):
            requested = Path(mapped['file_path'])
            logical = (requested if requested.is_absolute() else self.logical_root/requested).resolve()
            if logical.is_relative_to(self.logical_root):
                mapped['file_path'] = str(self.root/logical.relative_to(self.logical_root))
            else:
                # Preserve the exact rejected attempt rather than allowing a
                # path that happens to lie inside the physical sandbox.
                self.attempts.append(deepcopy(args))
                raise ValueError('Permission denied: outside artifact_root')
        receipt = super().call(mapped)
        return {**receipt, 'file_path': str(self.logical_root/Path(receipt['file_path']).relative_to(self.root))}


class SourceReadAdapter(AccessibleSealedRead):
    def __init__(self, root, archive, seal):
        super().__init__(root, archive)
        self.sources = ReceiptSources(archive, seal)

    def schemas(self):
        return [*super().schemas(), self.sources.schemas()[1]]

    async def execute(self, use, abort):
        if use.name != 'SourceRead':
            return await super().execute(use, abort)
        if abort.aborted: raise ValueError('source_read_cancelled')
        return self.sources.source(use.input)


async def prepare():
    assert not ROOT.exists()
    ROOT.mkdir()
    old = p.load(BASELINE/'run-report.json')
    assert old['completed'] and len(old['branches']) == 14
    checks = []
    for name in p.e.CASES:
        case = p.load(GENERATION/name/'case-private.json')
        reader = ReceiptSources(case['archive'], case['raw_sha256'])
        target = p.load(p.e.OLD/'gold.json')[name]['cold_excerpt']
        result = reader.source({'source_index': target['source_index'], 'offset': 0, 'limit': 80})
        exact = case['rows'][target['source_index']]['content'][0]['content'][:80]
        # Old208's frozen expected excerpt is shorter than80 in its long case;
        # retain that strict score rather than changing the reference here.
        assert result['content'] == exact
        assert reader.reopen().source({'source_index': target['source_index'], 'offset': 0, 'limit': 80}) == result
        for invalid in ({'source_index': True}, {'source_index': -1}, {'source_index': len(case['rows'])},
                        {'source_index': 0, 'message_id': case['rows'][0].get('id') or case['rows'][0].get('message_id')}):
            try: reader.source({**invalid, 'offset': 0, 'limit': 80})
            except ValueError: pass
            else: raise AssertionError('invalid_source_locator_accepted')
        checks.append({'case': name, 'source_exact': True, 'restart_equal': True, 'invalid_addresses_rejected': 4,
            'raw_first80_characters': len(exact), 'legacy_gold_characters': len(target['expected']),
            'gold_exactly_first80': exact == target['expected']})
    newcase = p.load(GENERATION/'clearing_holdout/case-private.json')
    source = ReceiptSources(newcase['archive'], newcase['raw_sha256'])
    receipt = source.source({'message_id': 'settle-new-result', 'offset': 0, 'limit': 4096})
    assert receipt['receipt']['metadata']['execution']['id'] == 'run-409'
    assert receipt['representation'] == 'tool_result_text'
    try: ReceiptSources(newcase['archive'], '0'*64)
    except ValueError: pass
    else: raise AssertionError('bad_seal_accepted')
    sink = RootMappedSink(ROOT/'logical', ROOT/'physical-free-check')
    sink.call({'file_path': str(ROOT/'logical/result.json'), 'content': '{\n"v":1\n}\n'})
    assert (sink.root/'result.json').read_bytes() == b'{\n"v":1\n}\n'
    assert not (ROOT/'logical/result.json').exists()
    try: sink.call({'file_path': str(sink.root/'illegal.json'), 'content': '{}'})
    except ValueError: pass
    else: raise AssertionError('physical_namespace_bypassed_logical_scope')
    plan = {'scope': __doc__, 'prior_report_sha256': p.sha((BASELINE/'run-report.json').read_bytes()),
        'generation_report_sha256': p.sha((GENERATION/'run-report.json').read_bytes()),
        'free_checks': checks, 'receipt_execution_identity_exact': True, 'wrong_seal_rejected': True,
        'root_mapping_multiline_and_scope_checked': True, 'source_read_only_schema_added': True,
        'same_messages': True, 'requests_per_consumer': 4, 'output_limit': 3072, 'http_retries': 0,
        'new_generation_calls': 0, 'code_sha256': p.sha(Path(__file__).read_bytes()),
        'need_evidence': '8 historical QA +3 structured artifact cases need cold data;3 natural artifact cases have required data hot',
        'samples': [{'case': r['case'], 'arm': r['arm'], 'hot_sha256': p.sha(r['hot']),
            'needs_cold': r['case'] != 'clearing_holdout' or r['representation'] in ('structured','native_structured')} for r in old['branches']]}
    p.e.write(ROOT/'preflight-manifest.json', plan)
    print(p.e.canonical({'free_checks': checks, 'consumers': len(plan['samples']), 'new_generations': 0}), flush=True)


async def execute():
    plan = p.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists()
    assert plan['code_sha256'] == p.sha(Path(__file__).read_bytes())
    assert plan['prior_report_sha256'] == p.sha((BASELINE/'run-report.json').read_bytes())
    p.e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = p.StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(3)
    calls.report.update(protocol=plan, branches=[])
    calls.save()
    sem = asyncio.Semaphore(3)
    old = p.load(BASELINE/'run-report.json')

    async def branch(prior):
        async with sem:
            if getattr(calls, 'evaluation_stopped', False): return
            name, arm = prior['case'], prior['arm']
            rec = {'case': name, 'arm': arm, 'hot_sha256': p.sha(prior['hot'])}
            calls.report['branches'].append(rec)
            try:
                case = p.load(GENERATION/name/'case-private.json')
                prepared = p.load(BASELINE/name/arm/'consumer-first-input.json')
                actor = p.load(BASELINE/name/arm/'actor.json')
                # Native message form from before the first model call.
                # state pending_messages was appended later; use the original
                # wire length to take only those initial native messages.
                native = actor['pending_messages'][:len(prepared['messages'])]
                assert p.e.CLIENT._build_body(native, [], stream=False)['messages'] == prepared['messages']
                logical = BASELINE/name/arm/'artifacts'
                sink = RootMappedSink(logical, ROOT/name/arm/'artifacts')
                reader = SourceReadAdapter(ROOT/name/arm, case['archive'], case['raw_sha256'])
                tools = reader.schemas()
                if case['kind'] == 'artifact_behavior': tools.insert(0, ExactArtifactSink.schema())
                model = p.ProviderFrameModel(calls, p.e.CLIENT, name+'-'+arm+'-recovery', 3072)
                body = model.body(native, tools)
                assert body['messages'] == prepared['messages']
                assert body['tools'][:-1] == prepared['tools']
                p.e.write(ROOT/name/arm/'first-input.json', body)
                state = new_state(native)
                await actor_run(model, state, tools, sink, reader, additional_requests=4,
                    checkpoint=lambda value: p.e.write(ROOT/name/arm/'actor.json', value))
                rec.update(consumer_calls=state['requests_attempted'], reads=state['activity'], answer=state.get('answer'),
                    completed=state['completed'])
                if case['kind'] == 'historical_QA':
                    answer, strict = p.parse(state.get('answer') or '')
                    rec.update(parsed=answer, strict_json=strict,
                        grade=p.frozen_grader()(answer, p.load(p.e.OLD/'gold.json')[name], case['rows']))
                    idx=p.load(p.e.OLD/'gold.json')[name]['cold_excerpt']['source_index']
                    correct=case['rows'][idx]['content'][0]['content'][:80]
                    rec['exact_raw_first80'] = answer.get('cold_excerpt') == correct
                else: rec['grade'] = actor_grade(sink, case['expected'])
            except p.EvaluationStop: rec['error'] = 'evaluation_stopped'
            except Exception as exc: rec['error'] = type(exc).__name__+': '+str(exc)[:500]
            finally:
                calls.save()
                print(p.e.canonical({k:rec.get(k) for k in ('case','arm','grade','exact_raw_first80','error')}), flush=True)

    await asyncio.gather(*(branch(r) for r in old['branches']))
    calls.report['completed'] = True
    calls.report['cost_estimate_cny'] = sum(x['cost_estimate'] for x in calls.report['calls'])
    calls.save()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(prepare() if sys.argv[1] == 'prepare' else execute())
