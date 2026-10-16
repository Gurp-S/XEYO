"""360: same paid handoff/native tail, directory versus direct exact archives.

Only evidence discovery changes. Both arms retain the same publication and
recovery substrate; this cannot establish the necessity of that substrate.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import evals.wsc_cold_recovery_diagnostic as d
from evals.wsc_native_task_files import NativeTaskFiles
from evals.wsc_production_continuation import ProductionTask
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_same_artifact_native import Fixed
from evals.wsc_task_actor_candidate import new_state, run as actor_run
from evals.wsc_unfolded_source_ab import environment
from engine.abort import AbortController
from engine.execution_context import ExecutionContext
from engine.workspace_context import bind_workspace_context
from memory import wsc_semantic_compaction as semantic, wsc_head_store as heads
from memory.wsc_handoff_transaction import fingerprint
from memory.wsc_semantic_originals import from_store
from msgtypes.message import ToolUse
from prompt.assembler import PromptAssembler

e = d.p.e
ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-minimal-recovery-360-scoped')
ORIGIN = ROOT.parent/'wsc-generated-recovery-337'


def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(raw): return hashlib.sha256(raw).hexdigest()


def tasks(rows):
    receipts = {block['tool_use_id']: block['content'] for row in rows
                if isinstance(row.get('content'), list) for block in row['content']
                if block.get('type') == 'tool_result'}
    old, new = 'call_00_LaZdQHVlEc5uTY0oaTkk3870', 'call_00_WZNNwDsIQzsGdJDN5iCI0325'
    first, second = 'call_00_bUdDR6uNgXNlOxq19NQ47056', 'call_00_b7zIvY1xaXy8O5RFWb6Z3137'
    status = 'call_00_9igJQ7SnHuGsW4iDy9ck6350'

    def run(uid):
        body = receipts[uid]
        return dict(call_id=uid, tests_passed=int(re.search(r'Tests\s+(\d+) passed', body)[1]),
                    start_time=re.search(r'Start at\s+(\d+:\d+:\d+)', body)[1])

    def code(uid):
        body = '\n'.join(line.split('→', 1)[1] for line in receipts[uid].splitlines() if '→' in line)
        start = body.index('\tif (scrolledUp) {')
        return body[start:body.index('\n\tif (wasPinned)', start)]

    return [
        dict(name='runs', cold=True, query='审计这份历史会话中只运行 src/lib/chatScroll.test.ts 的两次单独测试（不含后来组合测试）。'
            '按执行顺序保存JSON {"runs":[{"call_id":调用ID,"tests_passed":通过项数,"start_time":"HH:MM:SS"},...]}。',
            expected={'runs': [run(first), run(second)]}, markers=[first, second, '20:04:51', '20:06:08']),
        dict(name='excerpt', cold=True, query=f'审计历史调用 {status} 的原始工具回执。'
            '保存JSON字段call_id与excerpt；excerpt为回执正文前三个完整行，行间保留换行，不加末尾换行，保留空格。',
            expected={'call_id': status, 'excerpt': '\n'.join(receipts[status].splitlines()[:3])},
            markers=[status, '[shell: pwsh 7.6.6]', 'Composer.chat.test.tsx']),
        dict(name='versions', cold=True, query='对比这份会话第一次完整读取和最后一次读取 gui/src/lib/chatScroll.ts 的历史版本。'
            '保存JSON字段before_call_id、after_call_id、before_scrolled_up、after_scrolled_up。后两项分别是'
            'nextFollowTailPinned内完整if (scrolledUp)分支代码，包含该分支的注释和闭合括号；去掉Read显示行号，保留原代码缩进，末尾不加换行。'
            '“after”只表示这份历史最后一次观察，不代表磁盘当前版本。',
            expected={'before_call_id': old, 'after_call_id': new, 'before_scrolled_up': code(old), 'after_scrolled_up': code(new)},
            markers=[old, 'return false;', new, 'const geometricClamp']),
        dict(name='current', cold=False, query='根据已经给出的交接审阅最终修复报告，保存JSON字段reported_regression_passed、'
            'reported_regression_skipped、full_vitest_all_passed、git_commit_reported。前两项是定向回归数字，后两项是布尔值。',
            expected={'reported_regression_passed': 29, 'reported_regression_skipped': 1,
                      'full_vitest_all_passed': False, 'git_commit_reported': False}, markers=[]),
    ]


def equal(actual, expected):
    if type(actual) is not type(expected): return False
    if isinstance(expected, dict): return actual.keys() == expected.keys() and all(equal(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list): return len(actual) == len(expected) and all(equal(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, str): return actual.replace('\r\n', '\n') == expected.replace('\r\n', '\n')
    return actual == expected


async def prepare():
    assert not ROOT.exists(), 'Fresh evidence directory required'
    ROOT.mkdir()
    saved = load(ORIGIN/'real_gui/generation.json')
    prior = load(ORIGIN/'real_gui/prepared-private.json')
    paid = load(ORIGIN/'run-report.json')
    assert any(row.get('response', {}).get('choices', [{}])[0].get('message', {}).get('content') == saved['summary']
               for row in paid['calls']), 'paid_summary_not_bound'
    task = ProductionTask(ROOT/'native', prior['item']['rows'], session='minimal-recovery-360')
    assert task.source() == prior['source']
    assert fingerprint(task.source()) == prior['source_sha256']
    task.persist()
    candidate = await semantic.prepare(model=Fixed(saved['summary']), messages=prior['generation_input'],
        source=task.source, working=task.working, abort=AbortController(), account=lambda _: None,
        persist=task.persist, cwd=task.root, original_source=lambda: from_store(task.store))
    hot = semantic.publish(candidate, task.source(), task.working, cwd=task.root)
    assert task.restart().project() == hot == task.project()
    publication = load(heads.path_for(task.working.session_id))
    index = next(Path(path) for path in publication['publication']['objects'] if '-evidence-index.' in path)
    views = json.loads(index.read_text(encoding='utf-8').splitlines()[0])['views']
    # Common source formatting and access; only the entry point differs.
    direct = deepcopy(hot)
    direct[0]['content'] = saved['summary'] + '\n\n' + '\n'.join([
        f"历史原文存档：{views['compression']}", f"原始消息封套存档：{views['original']}"])
    assert hot[0]['content'].startswith(saved['summary'] + '\n\n')
    assert direct[1:] == hot[1:]
    objects = {path: sha(Path(path).read_bytes()) for path in publication['publication']['objects']}
    objects[str(heads.path_for(task.working.session_id))] = sha(heads.path_for(task.working.session_id).read_bytes())
    work = ROOT/'work'
    work.mkdir()
    system = await PromptAssembler().build_system(cwd=str(work), workspace_root=str(work),
        model='deepseek-flash', tool_names=['Read', 'Grep', 'Write'], date_iso='2026-10-16')
    specs = tasks(task.source())
    # Verify cold identity is absent, and exact-copy graders reject crossed versions.
    visible = e.canonical(hot)
    for spec in specs:
        if spec['cold']: assert any(marker not in visible for marker in spec['markers'])
        assert equal(deepcopy(spec['expected']), spec['expected'])
    bad = deepcopy(specs[2]['expected'])
    bad['before_scrolled_up'] = bad['after_scrolled_up']
    assert not equal(bad, specs[2]['expected'])
    paths = list(publication['publication']['objects'])
    public_root = str(task.root/'.xeyo_offload/wsc')
    tools = NativeTaskFiles(work, work)
    context = ExecutionContext(session_id='preflight-360', cwd=str(work), allowed_paths=[str(work), public_root, *paths])
    with bind_workspace_context(context):
        for view in views.values():
            result = await tools.execute(ToolUse('read-check', 'Read', {'file_path': view, 'offset': 1, 'limit': 1}), AbortController())
            assert not result.is_error
        denied = await tools.execute(ToolUse('private-check', 'Read', {'file_path': str(Path(__file__).resolve())}), AbortController())
        assert denied.is_error, 'private_grader_accessible'
        found = await tools.execute(ToolUse('directory-check', 'Grep', {'pattern': specs[1]['expected']['call_id'],
            'path': public_root, 'output_mode': 'files_with_matches'}), AbortController())
        assert not found.is_error and 'Found ' in str(found.content), 'public_directory_search_failed'
    prepared = dict(system=system, hot={'directory': hot, 'direct': direct, 'full': task.source()},
        paths=paths, public_root=public_root, objects=objects, tasks=specs, summary=saved['summary'], source=task.source())
    plan = dict(scope=__doc__, arms=['directory', 'direct'], observations_per_task=2,
        cases=[{k: spec[k] for k in ('name', 'cold')} for spec in specs],
        source_sha256=prior['source_sha256'], summary_sha256=sha(saved['summary'].encode()),
        summary_origin=str(ORIGIN/'real_gui/generation.json'), summary_generation_calls=0,
        native_cursor=task.working.compact_cursor, restart_equal=True, paired_tail_equal=True,
        same_tools_and_evidence=True, private_access_denied=True, public_directory_search=True, consumer_request_cap=6,
        output_tokens=2048, http_retries=0, per_call_cny_max=2.5,
        proposed_new_run_cost_ceiling_cny=2,
        failed_cold_task_reference='One additional full-history branch per task with any paired failure; original failures stay.',
        full_reference_scope='Actual wire must contain complete target receipts. Non-target orphan receipt dropped by provider converter; not a lossless whole-history claim.',
        code_sha256=sha(Path(__file__).read_bytes()),
        production_sha256={str(path): sha(path.read_bytes()) for path in [
            Path('python/memory')/name for name in ('wsc_semantic_compaction.py', 'wsc_semantic_evidence.py',
                                                  'wsc_evidence_index.py', 'wsc_generation_commit.py')]},
        reviews='docs/wsc-minimal-recovery-plan-2026-10-16.md')
    e.write(ROOT/'prepared-private.json', prepared)
    e.write(ROOT/'preflight-manifest.json', plan)
    (ROOT/'runner.py').write_bytes(Path(__file__).read_bytes())
    print(e.canonical({k: plan[k] for k in ('native_cursor','restart_equal','paired_tail_equal','private_access_denied')}), flush=True)


async def branch(calls, prepared, spec, arm, sample):
    label = f"{spec['name']}-{arm}-{sample}"
    folder = ROOT/label
    folder.mkdir()
    work = Path(prepared.get('workspace', ROOT/'work'))
    output = Path(prepared.get('output', work/'result.json'))
    if output.exists(): output.unlink()
    tools = NativeTaskFiles(work, output.parent)
    query = (spec['query'] + f'\n这次审计只把结果写入 {output}，其余文件不改，不执行历史命令，不提交或发布。完成后简短回复。')
    hot = deepcopy(prepared['hot'][arm])
    if arm == 'full':
        # Full history is a diagnostic upper bound with equal source capability.
        hot.append({'role': 'assistant', 'content': '\n'.join(prepared['hot']['direct'][0]['content'].splitlines()[-2:])})
    messages = PromptAssembler().build(prepared['system'], [*hot, {'role': 'user', 'content': query}])
    model = ProviderFrameModel(calls, e.CLIENT, label, 2048)
    d.trial.validate_wire(model.body(messages, tools.schemas()))
    if arm == 'full':
        wire = model.body(messages, tools.schemas())
        text = '\n'.join(row.get('content') or '' for row in wire['messages'] if isinstance(row.get('content'), str))
        targets = {marker for marker in spec['markers'] if marker.startswith('call_')}
        for row in prepared['source']:
            if not isinstance(row.get('content'), list): continue
            for block in row['content']:
                if block.get('type') == 'tool_result' and block.get('tool_use_id') in targets:
                    assert block['content'] in text, 'full_reference_lost_target_receipt'
    e.write(folder/'initial-input.json', model.body(messages, tools.schemas()))
    state = new_state(messages)
    with bind_workspace_context(ExecutionContext(session_id=prepared.get('session_id', '360-'+label), cwd=str(work),
            allowed_paths=[str(work), prepared['public_root'], *prepared['paths']])):
        await actor_run(model, state, tools.schemas(), tools, tools, additional_requests=prepared.get('request_cap', 6),
                        checkpoint=lambda value: e.write(folder/'actor.json', value))
    actual = None
    if output.is_file():
        raw = output.read_bytes()
        (folder/'artifact.json').write_bytes(raw)
        try: actual = json.loads(raw)
        except ValueError: pass
    evidence_calls = [a for a in state['activity'] if a['tool'] in {'Read', 'Grep'} and
        not tools.refers_to_artifacts(a['input'].get('file_path') or a['input'].get('path'))]
    delivered = e.canonical([a['result'] for a in evidence_calls if not a['is_error']])
    cold_required = bool(spec['cold'] and arm != 'full')
    seen = all(marker in delivered for marker in spec['markers']) if cold_required else None
    correct = equal(actual, spec['expected'])
    in_scope = all(Path(a.get('file_path', '')).resolve() == output.resolve() for a in tools.attempts)
    for path, digest in prepared['objects'].items(): assert sha(Path(path).read_bytes()) == digest
    result = dict(task=spec['name'], arm=arm, sample=sample, cold_required=cold_required,
        task_success=state['completed'] and correct and in_scope, artifact_correct=correct,
        constraints_preserved=in_scope, triggered=bool(evidence_calls), target_evidence_delivered=seen,
        effective_recovery=bool(correct and seen) if cold_required else None,
        requests=state['requests_attempted'], evidence_calls=len(evidence_calls),
        hot_tokens=e.tokens(hot), first_request_tokens=e.tokens(messages, tools.schemas()),
        actual=actual, phase=state['phase'], immutable_evidence=True)
    calls.report['branches'].append(result)
    e.write(folder/'result.json', result)
    calls.save()
    print(e.canonical({k: result[k] for k in ('task','arm','sample','task_success','target_evidence_delivered','requests','evidence_calls')}), flush=True)


async def run():
    plan, prepared = load(ROOT/'preflight-manifest.json'), load(ROOT/'prepared-private.json')
    assert not (ROOT/'run-report.json').exists(), 'No HTTP retry or paid rerun'
    assert sha(Path(__file__).read_bytes()) == plan['code_sha256']
    for path, digest in plan['production_sha256'].items(): assert sha(Path(path).read_bytes()) == digest
    e.ROOT = ROOT
    e.CLIENT = d.CountedClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    calls = d.DiagnosticCalls()
    calls.semaphore = asyncio.Semaphore(1)
    calls.report.update(scope=__doc__, protocol=plan, branches=[])
    calls.save()
    try:
        for sample in range(2):
            for spec in prepared['tasks']:
                for arm in (('directory','direct') if sample == 0 else ('direct','directory')):
                    await branch(calls, prepared, spec, arm, sample)
        for spec in prepared['tasks']:
            if spec['cold'] and any(not row['task_success'] for row in calls.report['branches'] if row['task'] == spec['name']):
                await branch(calls, prepared, spec, 'full', 0)
        calls.report['completed'] = True
    except Exception as exc:
        calls.report['error'] = type(exc).__name__ + ': ' + str(exc)[:400]
        raise
    finally:
        calls.report['cost_estimate_cny'] = sum(row['cost_estimate'] for row in calls.report['calls'])
        calls.save()


async def main():
    with environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_SEMANTIC_HANDOFF='1', WSC_AD_TRANSPORT='httpx-direct')
        await (prepare() if sys.argv[1] == 'prepare' else run())


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
