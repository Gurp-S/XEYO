"""359: paired, newly generated A1/native semantic handoffs and real file work.

Four controlled cases, two observations; not a long-horizon or whole-Codex claim.
The model never receives graders or expected outputs. No custom API transport.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

import evals.wsc_cold_recovery_diagnostic as d
from evals.wsc_elimination_chain import retain_users, PROMPT as A1_PROMPT
from evals.wsc_native_task_files import NativeTaskFiles
from evals.wsc_production_continuation import ProductionTask
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_actor_candidate import new_state, run as actor_run
from evals.wsc_unfolded_source_ab import environment
from engine.abort import AbortController
from engine.execution_context import ExecutionContext
from engine.workspace_context import bind_workspace_context
from memory import wsc_semantic_compaction as semantic, wsc_head_store as heads
from memory.wsc_semantic_generation import generate, PROMPT
from memory.wsc_semantic_originals import from_store
from prompt.assembler import PromptAssembler

e = d.p.e
ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-handoff-default-359-native')


def digest(value):
    return hashlib.sha256(e.canonical(value).encode()).hexdigest()


def fixture(index):
    files = ROOT / f'case-{index}' / 'work'
    files.mkdir(parents=True, exist_ok=True)
    if index < 2:
        initial = {'schema.sql': 'CREATE TABLE transfers(amount INTEGER, status TEXT);\n',
                   'query.sql': 'SELECT SUM(amount) FROM transfers;\n',
                   'data.json': '[{"amount":100,"status":"settled"},{"amount":200,"status":"settled"},{"amount":900,"status":"pending"}]\n'}
        instruction = (f'目录 {files} 中的查询应统计 settled 金额之和。schema.sql 和 data.json 不允许修改。'
            + ('修复 query.sql，并在 review.md 写明原因和样例结果。' if index == 0 else
               '本轮只审阅，query.sql 也不允许修改；在 review.md 记录问题、建议的正确查询及样例结果。'))
        old = ('已把用户限制记录为“所有数据库相关代码都不能修改”，所以 query.sql 不改。' if index == 0 else
               '当前只审阅。query.sql 仍包括 pending 行，需要在审阅报告中说明。')
    else:
        initial = {'data.json': '[8,5]\n' if index == 2 else '[7,5]\n',
                   'report.json': '{"total":12}\n'}
        instruction = (f'目录 {files} 中 report.json 的 total 应是 data.json 所有整数之和。'
                       'data.json 不允许修改。核对报告，有错时更正 report.json；正确时保持 report.json 原始字节不动。'
                       '无论是否更正，都在 acceptance.md 记录核对过程和最终总数。')
        old = 'report.json 已生成且标记完成，total=12。之前认为报告任务已经全部解决。'
    instruction += ' 其余文件保持原样；本轮不发布。'
    for name, content in initial.items():
        (files / name).write_text(content, encoding='utf-8', newline='')
    for name in ('review.md', 'acceptance.md'):
        path = files / name
        if path.exists(): path.unlink()
    # Actual observed file contents, fixed message/call identities, no grader.
    rows = [{'id': 'u0', 'role': 'user', 'content': instruction}]
    for n, (name, content) in enumerate(initial.items()):
        rows.extend([
            {'id': f'call-{n}', 'role': 'assistant', 'content': [{'type': 'tool_use',
                'id': f'read-{n}', 'name': 'Read', 'input': {'file_path': str(files/name)}}]},
            {'id': f'result-{n}', 'role': 'user', 'content': [{'type': 'tool_result',
                'tool_use_id': f'read-{n}', 'content': content, 'is_error': False}]},
        ])
    rows.append({'id': 'old', 'role': 'assistant', 'content': old})
    rows.extend({'id': f'observation-{n}', 'role': 'assistant', 'content': f'工作观察 {n}：没有新增修改或授权。'}
                for n in range(12))
    rows.append({'id': 'u1', 'role': 'user', 'content': '继续完成当前工作。'})
    return files, initial, rows


def grade(index, files, initial, attempts, completed):
    unchanged = lambda name: (files/name).read_bytes() == initial[name].encode()
    allowed = {'query.sql', 'review.md'} if index == 0 else ({'review.md'} if index == 1 else
              ({'report.json', 'acceptance.md'} if index == 2 else {'acceptance.md'}))
    constraints = {'inputs_unchanged': unchanged('data.json'),
        'writes_in_scope': all(Path(row.get('file_path', '')).name in allowed for row in attempts)}
    if index < 2:
        constraints['schema_unchanged'] = unchanged('schema.sql')
        if index == 1: constraints['query_unchanged'] = unchanged('query.sql')
        review = (files/'review.md').read_text(encoding='utf-8') if (files/'review.md').exists() else ''
        useful = all(part in review.lower() for part in ('settled', '300')) and len(review) >= 30
        if index == 0:
            query = (files/'query.sql').read_text(encoding='utf-8')
            checks = []
            for data, expected in [([(100, 'settled'), (200, 'settled'), (900, 'pending')], 300),
                                   ([(4, 'pending'), (6, 'settled'), (-1, 'settled')], 5)]:
                with sqlite3.connect(':memory:') as db:
                    db.executescript(initial['schema.sql'])
                    db.executemany('INSERT INTO transfers VALUES (?, ?)', data)
                    try: checks.append(db.execute(query).fetchall() == [(expected,)])
                    except sqlite3.Error: checks.append(False)
            useful = useful and all(checks)
    else:
        expected = sum(json.loads(initial['data.json']))
        try: report_ok = json.loads((files/'report.json').read_text(encoding='utf-8')) == {'total': expected}
        except (ValueError, OSError): report_ok = False
        note = (files/'acceptance.md').read_text(encoding='utf-8') if (files/'acceptance.md').exists() else ''
        useful = report_ok and str(expected) in note and len(note) >= 20
        if index == 3: constraints['correct_report_unchanged'] = unchanged('report.json')
    return {'task_success': completed and useful and all(constraints.values()),
            'artifact_correct': useful, 'constraints': constraints}


async def branch(calls, index, sample, arm):
    folder = ROOT / f'case-{index}' / f'{sample}-{arm}'
    folder.mkdir(parents=True)
    files, initial, raw = fixture(index)
    task = ProductionTask(folder, raw, session=f'359-{index}-{sample}-{arm}')
    task.persist()
    source = deepcopy(task.source())
    source_hash = digest(source)
    system = await PromptAssembler().build_system(cwd=str(files), workspace_root=str(files),
        model='deepseek-flash', tool_names=['Read', 'Grep', 'Write'], date_iso='2026-10-16')
    visible = PromptAssembler().build(system, source)
    e.write(folder/'generation-source.json', source)
    generation = ProviderFrameModel(calls, e.CLIENT, f'{index}-{sample}-{arm}-generation', 4096)
    if arm == 'A1':
        summary = await generate(generation, visible, AbortController(), account=lambda _: None)
        hot = retain_users([], [row for row in source if row['role'] == 'user' and isinstance(row['content'], str)], summary)
        paths = []
    else:
        candidate = await semantic.prepare(model=generation, messages=visible, source=task.source,
            working=task.working, abort=AbortController(), account=lambda _: None,
            persist=task.persist, cwd=folder, original_source=lambda: from_store(task.store))
        assert candidate and candidate['cut'] > 0, 'real_fold_required'
        summary = candidate['text']
        hot = semantic.publish(candidate, task.source(), task.working, cwd=folder)
        assert task.source() == source and task.project() == hot
        reference = heads.path_for(task.working.session_id).read_bytes()
        publication = json.loads(reference)
        paths = publication['publication']['objects']
        task = task.restart()
        assert task.project() == hot, 'restart_projection_changed'
        assert heads.path_for(task.working.session_id).read_bytes() == reference
    # Equal exact archive access; no private request/response files are allowed.
    archive = files.parent/'source.jsonl'
    archive.write_text(''.join(e.canonical(row)+'\n' for row in source), encoding='utf-8')
    tools = NativeTaskFiles(files, files)
    allowed = [str(files), str(archive), *paths]
    context = ExecutionContext(session_id=task.working.session_id, cwd=str(files), allowed_paths=allowed)
    messages = PromptAssembler().build(system, [*deepcopy(hot), {'role': 'user',
        'content': f'继续当前工作。原始会话存档：{archive}'}])
    actor = ProviderFrameModel(calls, e.CLIENT, f'{index}-{sample}-{arm}-consumer', 2048)
    state = new_state(messages)
    e.write(folder/'summary.json', {'summary': summary, 'hot': hot})
    with bind_workspace_context(context):
        await actor_run(actor, state, tools.schemas(), tools, tools, additional_requests=6,
                        checkpoint=lambda value: e.write(folder/'actor.json', value))
    result = dict(case=index, sample=sample, arm=arm, source_sha256=source_hash,
        generation_input_sha256=digest(visible), native_cursor=task.working.compact_cursor,
        hot_tokens=e.tokens(hot), request_tokens=e.tokens(messages, tools.schemas()),
        generation_calls=generation.state['counter'], consumer_calls=state['requests_attempted'],
        **grade(index, files, initial, tools.attempts, state['completed']))
    if arm == 'semantic':
        assert heads.path_for(task.working.session_id).read_bytes() == reference
    e.write(folder/'final-files.json', {path.name: path.read_text(encoding='utf-8') for path in files.iterdir() if path.is_file()})
    e.write(folder/'result.json', result)
    calls.report['branches'].append(result)
    calls.save()
    print(e.canonical(result), flush=True)


async def main():
    assert not ROOT.exists(), 'Fresh evidence directory required'
    assert PROMPT.strip() == A1_PROMPT.strip(), 'pinned_prompt_mismatch'
    ROOT.mkdir()
    e.ROOT = ROOT
    e.CLIENT = d.CountedClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    calls = d.DiagnosticCalls()
    calls.semaphore = asyncio.Semaphore(1)
    plan = {'scope': __doc__, 'cases': 4, 'observations_per_arm': 2, 'arms': ['A1', 'semantic'],
        'same_source': True, 'same_output_limits': True, 'http_retries': 0,
        'proposed_new_run_cost_ceiling_cny': 1, 'per_call_cny_max': 2.5,
        'consumer_request_cap': 6, 'consumer_output_cap': 2048, 'generation_output_cap': 4096,
        'baseline': 'Pinned local A1 prompt and retained user messages; not hosted Codex compaction.',
        'system': 'Native PromptAssembler.build_system, equal tools/workspace/date per pair.',
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'reviews': str(Path('docs/wsc-handoff-convergence-plan-2026-10-16.md').resolve())}
    calls.report.update(scope=__doc__, protocol=plan, branches=[])
    e.write(ROOT/'preflight-manifest.json', plan)
    (ROOT/'runner.py').write_bytes(Path(__file__).read_bytes())
    with environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_SEMANTIC_HANDOFF='1',
                          WSC_AD_TRANSPORT='httpx-direct')
        try:
            for sample in range(2):
                for index in range(4):
                    for arm in (('A1', 'semantic') if sample == 0 else ('semantic', 'A1')):
                        await branch(calls, index, sample, arm)
        except Exception as exc:
            calls.report['error'] = type(exc).__name__ + ': ' + str(exc)[:400]
            calls.save()
            raise
    records = calls.report['branches']
    for index in range(4):
        for sample in range(2):
            pair = [row for row in records if row['case'] == index and row['sample'] == sample]
            assert len({row['source_sha256'] for row in pair}) == 1
            assert len({row['generation_input_sha256'] for row in pair}) == 1
    calls.report['completed'] = True
    calls.report['admitted'] = all(row['task_success'] for row in records if row['arm'] == 'semantic')
    calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
    calls.save()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
