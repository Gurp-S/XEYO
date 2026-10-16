"""Same ten-event task: pinned A1, production D, native semantic publication.

Consumers receive the actual published projection, not a substitute checkpoint.
The common actor is a controlled execution harness; query-loop error admission
is independently exercised by test_semantic_production, not claimed here.
"""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys

import evals.wsc_ten_generation_task as t
from evals.wsc_observation_role_chain import idempotent_grade
from memory import wsc_semantic_compaction as semantic
from memory.wsc_semantic_generation import generate as generate_summary
from memory.wsc_handoff_generation import generate as generate_d
from memory.working import flush
from prompt.assembler import PromptAssembler

ROOT = t.ROOT.parent / os.environ.get('WSC_SEMANTIC_TRIAL_RUN', 'wsc-semantic-production-317')
ARMS = ('A1', 'D_production', 'semantic_production')


def validate_wire(body):
    from model.context_input import from_body
    source = from_body(body)
    measured = t.p.e.CLIENT.context_token_measure(source)
    count = measured[0] if measured is not None else len(t.p.e.canonical(source).encode('utf-8'))
    assert count + body.get('max_tokens', 4096) <= 1048576, 'provider_request_exceeds_capacity'
    pending, seen = set(), set()
    for row in body['messages']:
        if row['role'] == 'tool':
            uid = row.get('tool_call_id')
            assert uid in pending, 'unpaired_provider_receipt'
            pending.remove(uid)
        else:
            assert not pending, 'interrupted_provider_tool_batch'
            ids = [call['id'] for call in row.get('tool_calls', [])]
            assert len(ids) == len(set(ids)) and not seen.intersection(ids), 'duplicate_provider_call'
            pending.update(ids); seen.update(ids)
    assert not pending, 'incomplete_provider_tool_batch'


class ValidatedCalls(t.p.StopAwareCalls):
    async def call(self, body, label):
        try:
            validate_wire(body)
            return await super().call(body, label)
        except Exception as exc:
            self.evaluation_stopped = True
            self.report.setdefault('stop_reason', type(exc).__name__ + ': ' + str(exc)[:500])
            self.report.setdefault('stopped_at', label)
            self.save()
            raise t.p.EvaluationStop(self.report['stop_reason']) from exc


async def branch(calls, arm):
    root = ROOT / arm
    task = t.ProductionTask(root, [], session=ROOT.name + '-' + arm)
    await t.bootstrap(task)
    hot, pending, delayed, paths = [], deepcopy(task.source()), None, []
    for entry in t.scenario():
        if getattr(calls, 'evaluation_stopped', False): return
        n = entry['stage']; folder = root / f'generation-{n}'
        folder.mkdir(parents=True)
        record = {'arm': arm, 'stage': n, 'accepted': False, 'task_success': False,
                  'state_correct': 0, 'state_total': 8}
        calls.report['branches'].append(record)
        try:
            if entry['restart_before']:
                task.persist(); flush(task.working.session_id, task.working)
                before = task.project(); task = task.restart()
                assert task.project() == before
                record['restart_equal'] = True
            events = [{'id': 'external-user-' + str(n), 'role': 'user', 'content': entry['request']}]
            t.append(task, events)
            if n == 1:
                old = root/'inputs/late-old.json'
                old.write_bytes(t.p.e.canonical({'batch_id': 'transit-coral', 'revision': 0, 'file_version': 1,
                    'total_bytes': 9999999, 'delivered_bytes': 0, 'lane': 'old', 'checksum_label': 'obsolete'}).encode())
                invocation, delayed = await t.execute_read(task, 'late-read', old, late=True)
                t.append(task, [invocation]); events.append(invocation)
            if entry['refresh']:
                current = root/'inputs/current.json'
                current.write_bytes(t.p.e.canonical(entry['data']).encode())
                invocation, receipt = await t.execute_read(task, entry['source_call_id'], current)
                t.append(task, [invocation, receipt]); events.extend([invocation, receipt])
            if n == 3:
                t.append(task, [delayed]); events.append(delayed)
            pending.extend(deepcopy(events))
            source = deepcopy(task.source())
            visible = PromptAssembler().build(t.SYSTEM['content'],
                [*hot, *pending] if arm == 'A1' else task.project())
            model = t.p.ProviderFrameModel(calls, t.p.e.CLIENT, arm + f'-g{n}-generation', 4096)
            if arm == 'A1':
                summary = await generate_summary(model, visible, t.AbortController(), account=lambda _: None)
                hot = t.retain_users(hot, pending, summary)
                record['accepted'] = True
            elif arm == 'D_production':
                async def declare(captured):
                    return await generate_d(model, visible, captured, task.registry.get('TodoWrite').schema(),
                        t.AbortController(), account=lambda _: None, scope_protocol=True)
                try:
                    record['commit'] = await task.commit(declare)
                except Exception as exc:
                    from memory.wsc_compaction_failure import recoverable
                    if not recoverable(exc) or task.source() != source: raise
                    record['generation_failure'] = str(exc)
                    hot = task.project()
                else:
                    publication = task.fold()
                    hot = publication['hot']
                    paths.extend(publication['head']['publication']['objects'])
                    t.p.e.write(folder/'publication.json', publication)
                    record['accepted'] = True
            else:
                from memory.wsc_semantic_originals import from_store
                try:
                    candidate = await semantic.prepare(model=model, messages=visible, source=task.source,
                        working=task.working, abort=t.AbortController(), account=lambda _: None, persist=task.persist, cwd=task.root,
                        original_source=lambda: from_store(task.store))
                except Exception as exc:
                    if not semantic.resumable_failure(exc) or task.source() != source: raise
                    candidate = None
                    record['generation_failure'] = str(exc)
                if candidate is None:
                    hot = task.project()
                else:
                    hot = semantic.publish(candidate, task.source(), task.working, cwd=task.root)
                    assert hot == task.project()
                    from memory.wsc_head_store import path_for
                    publication = t.p.load(path_for(task.working.session_id))
                    paths.extend(publication['publication']['objects'])
                    t.p.e.write(folder/'publication.json', publication)
                    record['accepted'] = True
            if record['accepted']: pending = []
            archive = t.publish(root/'evidence.txt', (''.join(t.p.e.canonical(row)+'\n' for row in task.source())).encode())
            paths.append(archive)
            sink = t.ExactArtifactSink(root/'artifacts')
            artifact = sink.root/'result.json'
            old_hash = t.p.sha(artifact.read_bytes()) if artifact.exists() else None
            reader = t.BranchRead(task, paths + [artifact])
            messages = PromptAssembler().build(t.SYSTEM['content'], [*deepcopy(hot),
                {'role': 'user', 'content': t.p.e.canonical({'artifact_root': str(sink.root),
                    'exact_evidence': {'archive': str(archive), 'records': len(task.source())}})},
                {'role': 'user', 'content': '继续当前这一轮工作；最终回复使用此前约定的状态JSON。'}])
            tools = [t.ExactArtifactSink.schema(), *reader.schemas()]
            actor = t.p.ProviderFrameModel(calls, t.p.e.CLIENT, arm+f'-g{n}-consumer', 4096)
            state = t.new_state(messages); initial = len(messages)
            record.update(hot_tokens=t.p.e.tokens(hot), request_tokens=t.p.e.tokens(messages, tools))
            t.p.e.write(folder/'first-consumer-input.json', actor.body(messages, tools))
            await t.actor_run(actor, state, tools, sink, reader, additional_requests=6,
                checkpoint=lambda value: t.p.e.write(folder/'actor.json', value))
            actual = state['pending_messages'][initial:]
            t.append(task, actual); pending.extend(deepcopy(actual))
            answer, strict = t.p.parse(state.get('answer') or '')
            score = idempotent_grade(sink, entry['expected_artifact'], old_hash)
            record.update(task_success=score['task_success'], artifact_score=score, answer=answer,
                state_correct=sum(type(answer.get(k)) is type(v) and answer[k] == v for k,v in entry['expected_state'].items()),
                consumer_calls=state['requests_attempted'], activity=state['activity'])
        except t.p.EvaluationStop:
            record['error'] = 'evaluation_stopped'; calls.save(); return
        except Exception as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)[:500]
        finally:
            task.persist(); flush(task.working.session_id, task.working)
            t.p.e.write(folder/'result.json', record); calls.save()
            print(t.p.e.canonical({k: record.get(k) for k in ('arm','stage','accepted','state_correct','task_success','error')}), flush=True)


async def main():
    assert not ROOT.exists(), 'Fresh evidence directory required'
    ROOT.mkdir()
    t.p.e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = ValidatedCalls(); calls.semaphore = asyncio.Semaphore(1)
    plan = {'scope': __doc__, 'arms': ARMS, 'events': t.scenario(), 'http_retries': 0, 'per_call_cny_max': 2.5,
        'concurrent_http_requests': 1,
        'D_production_anchor': 'Current structured generation/full projection, including admitted unchanged-source generation failure continuation. Earlier 315-317 baseline and results remain immutable.',
        'semantic_failed_generation': 'Unchanged source retained; consumer still admitted by full request capacity.',
        'reviews': ['Separate semantic generation from TodoWrite. Same prompt for A1 and semantic, no conclusion repair.',
                    'Native publish/read/restart; current D and natural path retain source on eligible generation failure, with full request capacity check.',
                    'Own-state 10 stages, equal actor quota and artifact judge, original failures retained.'],
        'code_sha256': t.p.sha(Path(__file__).read_bytes())}
    t.p.e.write(ROOT/'preflight-manifest.json', plan)
    calls.report.update(protocol=plan, branches=[])
    with t.environment(ROOT):
        os.environ['XEYO_WSC'] = '1'
        os.environ['XEYO_WSC_HEAD_STORE'] = '1'
        await asyncio.gather(*(branch(calls, arm) for arm in ARMS))
    calls.report['completed'] = not getattr(calls, 'evaluation_stopped', False)
    calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
    calls.save()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
