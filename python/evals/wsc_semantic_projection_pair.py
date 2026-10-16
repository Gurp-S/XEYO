"""Actual native emission vs the same checkpoint, with identical native tail."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys

import evals.wsc_semantic_format_pilot as p
from evals.wsc_semantic_format_consumer_recheck import AccessibleSealedRead
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_production_continuation import ProductionTask, PublishedRead
from evals.wsc_unfolded_source_ab import environment
from evals.wsc_task_actor_candidate import new_state, run as actor_run
from engine.abort import AbortController
from msgtypes.message import ToolUse

ROOT = p.ROOT.parent/'wsc-factorial-projection-pair-309'
SOURCE = p.ROOT


class CommonPublishedRead(AccessibleSealedRead):
    def __init__(self, paths):
        self.paths = {Path(x).resolve() for x in paths}
        super().__init__(ROOT, next(iter(self.paths)))
        self.root = ROOT.parent
        self.registry = p.ToolRegistry(cwd=str(self.root))
        self.registry.register(p.FileReadTool(cwd=str(self.root)))

    async def execute(self, use, abort):
        name = use.input.get('file_path') if isinstance(use.input, dict) else None
        if use.name != 'Read' or not isinstance(name, str):
            return p.ToolResult('invalid Read arguments', is_error=True, error_kind='INVALID_ARGUMENT')
        requested = Path(name)
        requested = (requested if requested.is_absolute() else self.root/requested).resolve()
        if requested not in self.paths:
            return p.ToolResult('Permission denied: outside published evidence', is_error=True, error_kind='PERMISSION_DENIED')
        return await self.registry.run(use, abort)


async def prepare():
    assert not ROOT.exists()
    ROOT.mkdir()
    case = p.load(SOURCE/'completed_waiting_authority/case-private.json')
    old = p.load(SOURCE/'run-report.json')
    selected = next(r for r in old['branches'] if r['case'] == case['case'] and r['arm'] == 'SD')
    assert selected['accepted']
    native = selected['raw_candidate']
    location = ROOT/'native'
    with environment(location):
        os.environ['XEYO_WSC'] = '1'
        task = ProductionTask(location, case['rows'], session='307-SD-projection-pair')
        async def declare(rows):
            assert [r.get('message_id') or r.get('id') for r in rows] == [r.get('message_id') or r.get('id') for r in case['rows']]
            return ToolUse('309-recommit-SD', 'TodoWrite', deepcopy(native))
        commit = await task.commit(declare)
        projected = task.fold()
        restored = task.restart()
        assert restored.project() == projected['hot']
        published = PublishedRead(task, projected['head'])
        path = next(iter(published.allowed))
        result = await published.execute(ToolUse('309-free-read', 'Read', {'file_path': str(path), 'offset': 1, 'limit': 5}), AbortController())
        assert not result.is_error
        p.e.write(ROOT/'native-projection.json', projected)
    paths = list(projected['head']['publication']['objects']) + [case['archive']]
    reader = CommonPublishedRead(paths)
    # Same source capability and exact recent messages; only the first head
    # differs. The actual producer creates the full head, not this evaluator.
    metadata = {'role': 'assistant', 'content': p.e.canonical({'exact_evidence': {
        'archive': case['archive'], 'source_sha256': case['raw_sha256'], 'source_index_base': 0,
        'archive_line_base': 1, 'additional_published_objects': paths[:-1]}})}
    production = [case['template']['system'], *deepcopy(projected['hot']), metadata, case['template']['query']]
    thin = deepcopy(production)
    thin[1] = {'role': 'assistant', 'content': selected['hot']}
    assert thin[:1] == production[:1] and thin[2:] == production[2:]
    plan = {'scope': __doc__, 'source_case': case['case'], 'source_arm': 'SD', 'checkpoint_sha256': p.sha(native),
        'source_raw_sha256': case['raw_sha256'], 'paths': paths, 'case': case['case'], 'requests_per_arm': 4,
        'output_limit': 3072, 'same_tail_and_query': True, 'actual_native_publication': True,
        'native_commit': commit, 'restart_projection_equal': True, 'actual_published_Read': not result.is_error,
        'code_sha256': p.sha(Path(__file__).read_bytes()), 'inputs': {}}
    for arm, messages in [('thin', thin), ('production', production)]:
        model = p.ProviderFrameModel(None, p.e.CLIENT, arm, 3072)
        body = model.body(messages, reader.schemas())
        p.e.write(ROOT/f'{arm}-messages.json', messages)
        p.e.write(ROOT/f'{arm}-first-input.json', body)
        plan['inputs'][arm] = {'input_tokens': p.e.tokens(messages, reader.schemas()),
            'head_tokens': p.e.tokens([messages[1]]), 'request_sha256': p.sha(body)}
    p.e.write(ROOT/'preflight-manifest.json', plan)
    print(p.e.canonical({'preflight': plan['inputs'], 'same_tail_and_query': True, 'native_Read_restart': True}), flush=True)


async def execute():
    plan = p.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists()
    assert plan['code_sha256'] == p.sha(Path(__file__).read_bytes())
    p.e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = p.StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(2)
    calls.report.update(protocol=plan, branches=[])
    calls.save()

    async def branch(arm):
        record = {'arm': arm}
        calls.report['branches'].append(record)
        try:
            messages = p.load(ROOT/f'{arm}-messages.json')
            reader = CommonPublishedRead(plan['paths'])
            sink = ExactArtifactSink(ROOT/arm/'artifacts')
            model = p.ProviderFrameModel(calls, p.e.CLIENT, 'projection-'+arm, 3072)
            assert model.body(messages, reader.schemas()) == p.load(ROOT/f'{arm}-first-input.json')
            state = new_state(messages)
            await actor_run(model, state, reader.schemas(), sink, reader, additional_requests=4,
                checkpoint=lambda value: p.e.write(ROOT/arm/'actor.json', value))
            case = p.load(SOURCE/plan['case']/'case-private.json')
            answer, strict = p.parse(state.get('answer') or '')
            record.update(answer=answer, strict_json=strict, consumer_calls=state['requests_attempted'],
                reads=state['activity'], grade=p.frozen_grader()(answer, p.load(p.e.OLD/'gold.json')[plan['case']], case['rows']))
        except p.EvaluationStop: record['error'] = 'evaluation_stopped'
        except Exception as exc: record['error'] = type(exc).__name__+': '+str(exc)
        finally:
            calls.save()
            print(p.e.canonical(record), flush=True)
    await asyncio.gather(branch('thin'), branch('production'))
    calls.report['completed'] = True
    calls.report['cost_estimate_cny'] = sum(c['cost_estimate'] for c in calls.report['calls'])
    calls.save()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(prepare() if sys.argv[1] == 'prepare' else execute())
