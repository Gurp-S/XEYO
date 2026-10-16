"""Fresh GLM generation/QA on the two sealed real-source checkpoints.

Original full histories remain cold; generator visibility is the same archived
checkpoint for all arms, not a claimed full-history or native Codex replay.
"""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys

from evals import wsc_glm_trial as g
from evals import wsc_semantic_format_pilot as p
from evals.wsc_semantic_projection_pair import CommonPublishedRead
from evals.wsc_production_continuation import ProductionTask
from evals.wsc_ten_generation_task import retain_users, ExactArtifactSink, new_state, actor_run
from evals.wsc_unfolded_source_ab import environment
from engine.abort import AbortController
from memory import wsc_semantic_compaction as semantic
from memory.wsc_semantic_generation import generate as generate_summary
from memory.wsc_handoff_generation import generate as generate_d
from memory.wsc_compaction_failure import recoverable
from prompt.assembler import PromptAssembler

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-glm-real-sources-324')
ORIGIN = ROOT.parent/'wsc-semantic-format-307'
ARMS = ('A1', 'D_production', 'semantic_production')


def prepare():
    assert not ROOT.exists()
    ROOT.mkdir()
    g.configure()
    plan = {'scope': __doc__, 'model': g.MODEL, 'arms': ARMS, 'cases': [],
        'generation_output_limit': 4096, 'consumer_output_limit': 4096, 'consumer_requests': 6,
        'thinking': 'enabled', 'reasoning_effort': 'low', 'temperature': 0.1, 'http_retries': 0,
        'reviews': [
            'Same original checkpoint visibility and same raw archive for all three arms; fresh same-model generations.',
            'Original A1 retained-user policy, current native D transaction/fold, actual semantic publication; no evaluation head substituted for production.',
            'Actual Read receipts and frozen field grader. Historical QA is not original development-task delivery; ambiguous batch2 scope reported separately.'],
        'code_sha256': {str(f):p.sha(f.read_bytes()) for f in [Path(__file__), Path(g.__file__)]}}
    for name in p.e.CASES:
        case = p.load(ORIGIN/name/'case-private.json')
        assert p.sha(Path(case['archive']).read_bytes()) == case['raw_sha256']
        plan['cases'].append({'case':name, 'raw_sha256':case['raw_sha256'],
                              'view_sha256':p.sha(case['common_messages'])})
        assert all(isinstance(r['content'],str) for r in case['rows'] if r['role']=='user')
    p.e.write(ROOT/'preflight-manifest.json', plan)
    print('Prepared two real sources x three arms; no API calls.', flush=True)


async def branch(calls, case, arm):
    folder = ROOT/case['case']/arm
    task = ProductionTask(folder, case['rows'], session='glm324-'+case['case']+'-'+arm)
    task.persist()
    record = {'case':case['case'], 'arm':arm, 'accepted':False}
    calls.report['branches'].append(record)
    try:
        source = deepcopy(task.source())
        visible = deepcopy(case['common_messages'])
        model = g.Frame(calls, p.e.CLIENT, case['case']+'-'+arm+'-gen', 4096)
        objects = [case['archive']]
        if arm == 'A1':
            text = await generate_summary(model, visible, AbortController(), account=lambda _:None)
            hot = retain_users([], case['rows'], text)
            record['accepted'] = True
        elif arm == 'D_production':
            async def declare(captured):
                return await generate_d(model, visible, captured, task.registry.get('TodoWrite').schema(),
                    AbortController(), account=lambda _:None, scope_protocol=True)
            try:
                record['commit'] = await task.commit(declare)
            except Exception as exc:
                if not recoverable(exc) or task.source() != source: raise
                record['generation_failure'] = str(exc)
                hot = task.project()
            else:
                publication = task.fold()
                hot = publication['hot']
                objects.extend(publication['head']['publication']['objects'])
                p.e.write(folder/'publication.json', publication)
                record['accepted'] = True
        else:
            from memory.wsc_semantic_originals import from_store
            try:
                candidate = await semantic.prepare(model=model, messages=visible, source=task.source,
                    working=task.working, abort=AbortController(), account=lambda _:None, persist=task.persist, cwd=folder,
                    original_source=lambda: from_store(task.store))
            except Exception as exc:
                if not recoverable(exc) or task.source() != source: raise
                record['generation_failure'] = str(exc)
                candidate = None
            hot = task.project() if candidate is None else semantic.publish(candidate, task.source(), task.working, cwd=folder)
            if candidate is not None:
                from memory.wsc_head_store import path_for
                publication = p.load(path_for(task.working.session_id))
                objects.extend(publication['publication']['objects'])
                p.e.write(folder/'publication.json', publication)
                record['accepted'] = True
        if arm != 'A1':
            assert hot == task.project() == task.restart().project()
            record['restart_equal'] = True
        reader = CommonPublishedRead(objects)
        messages = PromptAssembler().build(case['template']['system']['content'], [*hot,
            {'role':'user', 'content':p.e.canonical({'exact_evidence':{'archive':case['archive'],
                'source_sha256':case['raw_sha256'], 'records':len(case['rows']), 'archive_line_base':1}})},
            case['template']['query']])
        model = g.Frame(calls, p.e.CLIENT, case['case']+'-'+arm+'-consumer', 4096)
        p.e.write(folder/'first-consumer-input.json', model.body(messages, reader.schemas()))
        p.e.write(folder/'projection.json', hot)
        record['hot_utf8_bytes'] = len(p.e.canonical(hot).encode('utf-8'))
        state = new_state(messages)
        await actor_run(model, state, reader.schemas(), ExactArtifactSink(folder/'artifacts'), reader,
            additional_requests=6, checkpoint=lambda value:p.e.write(folder/'actor.json',value))
        answer, strict = p.parse(state.get('answer') or '')
        record.update(answer=answer, strict_json=strict, consumer_calls=state['requests_attempted'],
            reads=state['activity'], grade=p.frozen_grader()(answer,p.load(p.e.OLD/'gold.json')[case['case']],case['rows']))
    except p.EvaluationStop:
        record['error'] = 'evaluation_stopped'
    except Exception as exc:
        record['error'] = type(exc).__name__+': '+str(exc)[:600]
    finally:
        p.e.write(folder/'result.json',record);calls.save()
        print(p.e.canonical({k:record.get(k) for k in ('case','arm','accepted','grade','error')}),flush=True)


async def execute():
    plan = p.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists()
    assert all(p.sha(Path(name).read_bytes())==digest for name,digest in plan['code_sha256'].items())
    g.configure();p.e.ROOT=ROOT
    calls = g.Calls();calls.report['protocol']=plan
    with environment(ROOT):
        os.environ.update(XEYO_WSC='1',XEYO_WSC_HEAD_STORE='1',XEYO_WSC_MEDIA_ARCHIVE='1')
        for name in p.e.CASES:
            case=p.load(ORIGIN/name/'case-private.json')
            for arm in ARMS:
                if calls.evaluation_stopped: break
                await branch(calls,case,arm)
    calls.report['completed']=not calls.evaluation_stopped
    calls.save()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if '--prepare' in sys.argv: prepare()
    else: asyncio.run(execute())
