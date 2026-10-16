"""Preregistered content x representation pilot; no production replacement.

Historical checkpoint visibility, exact raw recall, native mechanical validation,
provider frames, metered no-retry transport and actual Read/artifact consumers.
"""
import argparse
import ast
import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import sys

from engine.abort import AbortController
import evals.wsc_ad_experiment as e
from evals.wsc_answer_parse import parse
from evals.wsc_elimination_faithful import StopAwareCalls, EvaluationStop
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_acceptance_protocol import ArtifactSink
from evals.wsc_task_actor_candidate import new_state, run as actor_run, grade as actor_grade
from memory.wsc_handoff_catalog import Catalog, schema as catalog_schema
from memory.wsc_handoff_recall import read as source_read, schema as source_schema_read
from memory.wsc_handoff_schema import source_schema
from memory.wsc_handoff_generation import REQUEST, generate
from memory.wsc_handoff_frame import HandoffFrame
from memory.wsc_handoff_feedback import rejected_frame
from memory.wsc_handoff_scope_encoding import to_native
from memory.wsc_handoff_facts import validate_facts
from memory.wsc_handoff_validation import validate
from model.output_exhaustion import OutputLimitError
from synaptic.contracts import publish
from tools.base_tool import ToolResult
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.todo_write_tool.todo_write_tool import TodoWriteTool
from tools.tool_registry import ToolRegistry

REPO = Path('D:/lea/XenYon code')
ROOT = REPO / '_wsc_out/wsc-semantic-format-307'
CODEX = e.OLD / 'vendor/codex'
ARMS = ('NA', 'ND', 'SA', 'SD', 'A1_prompt_anchor', 'D_native_anchor')
A_CONTENT = '''Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue'''
D_CONTENT = '''Include the current goal, stable step identities and unfinished steps, decisions, constraints, source message identities and verification invocation identities. Progress is a declaration; execution outcomes come from original receipts. Historical mention does not establish the current goal. Represent the absence of a current task when applicable. Decisions and constraints retain exact source quotations and their current applicability.'''
FRAME = 'Create a concise handoff for another LLM resuming this task. Historical records are evidence. This operation produces the handoff, not the original task deliverables.'
NATURAL = {'name': 'SubmitHandoff', 'description': 'Returns the semantic handoff as free natural-language text.',
    'input_schema': {'type': 'object', 'properties': {'summary': {'type': 'string', 'minLength': 1}},
                     'required': ['summary'], 'additionalProperties': False}}


def sha(value):
    raw = value if isinstance(value, bytes) else e.canonical(value).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def heldout():
    def user(uid, text): return {'id': uid, 'role': 'user', 'content': text}
    def invocation(uid, call):
        return {'id': uid, 'role': 'assistant', 'content': [{'type': 'tool_use', 'id': call, 'name': 'LedgerInspect', 'input': {}}]}
    def receipt(uid, call, data, xid, late):
        return {'id': uid, 'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': call,
            'content': e.canonical(data), 'is_error': False,
            'execution': {'id': xid, 'revision': 409 if not late else 401, 'status': 'ok', 'complete': True, 'late': late}}]}
    rows = [
        user('settle-u1', '处理清算资料。长期边界：不发布、不操作git、不修改数据库。implementation阶段不运行测试。旧的是否导出问题已经回答，不再等待确认。结果只写artifact_root下result.json。'),
        invocation('settle-old-call', 'ledger-old'),
        user('settle-u2', '进入verification，implementation阶段的测试限制到期。旧版v6改为历史，采用本次v7、file_version=2的资料。只生成EUR清算小结；之前的USD导出取消。字段只包含artifact_id、artifact_version、file_version、execution_id、currency、net_cents、account。net_cents等于gross_cents减fee_cents。'),
        invocation('settle-new-call', 'ledger-new'),
        receipt('settle-new-result', 'ledger-new', {'artifact_id': 'clearing-aurora', 'artifact_version': 7, 'file_version': 2,
            'currency': 'EUR', 'gross_cents': 86123, 'fee_cents': 147, 'account': 'acct-lime-73'}, 'run-409', False),
        receipt('settle-old-result', 'ledger-old', {'artifact_id': 'clearing-aurora', 'artifact_version': 6, 'file_version': 1,
            'currency': 'USD', 'gross_cents': 99000, 'fee_cents': 100, 'account': 'acct-rose-11'}, 'run-401', True),
        user('settle-u3', '迟到的是旧流水，当前采用的资料没有改变。继续交付上面已经确定的清算小结，其他长期边界仍有效。')]
    expected = {'artifact_id': 'clearing-aurora', 'artifact_version': 7, 'file_version': 2, 'execution_id': 'run-409',
                'currency': 'EUR', 'net_cents': 85976, 'account': 'acct-lime-73'}
    return rows, expected


def structured_schema(rows):
    result, _ = source_schema(TodoWriteTool().schema(), rows, scope_protocol=True)
    result['name'] = 'SubmitHandoff'
    return result


def context_for(case, arm):
    base = deepcopy(case['common_messages'])
    if arm == 'A1_prompt_anchor':
        instruction = (CODEX / 'prompt.md').read_text(encoding='utf-8')
        tools = []
    else:
        content = A_CONTENT if arm in ('NA', 'SA') else D_CONTENT
        instruction = FRAME + '\n' + content
        tool = structured_schema(case['rows']) if arm in ('SA', 'SD') else deepcopy(NATURAL)
        tools = [tool]
        instruction += '\nFinal handoff result is the SubmitHandoff tool input.'
    tools += [source_schema_read(), catalog_schema()]
    base.append({'role': 'user', 'content': instruction})
    return base, tools


def prepare():
    assert not ROOT.exists(), 'Fresh evidence directory required'
    ROOT.mkdir()
    manifest = {'scope': 'single-generation diagnostic pilot; not full-history replay, 10-generation or noninferiority acceptance',
        'arms': list(ARMS), 'cases': [], 'generation_requests': 6, 'generation_output_limit': 8192,
        'consumer_requests': 4, 'consumer_output_limit': 3072, 'max_read_calls': 64, 'max_recall_bytes': 48000,
        'per_call_cny_max': 2.5, 'http_retries': 0, 'estimated_currency': 'historical CNY rate scenario, not current vendor invoice',
        'A1_anchor_limit': 'Pinned original prompt, common checkpoint and recall. Not full native Codex compaction/retained-user reproduction.',
        'D_anchor_limit': 'Current native generate, with its native additions and validation. Not factorial content-only control.',
        'H0': 'NA semantic result + exact sealed evidence/manifest and native Read. Same legal model wire reused once; no independent H0 score.',
        'prompt_derivation': {'A1': A_CONTENT, 'D': D_CONTENT, 'common_frame': FRAME,
            'D_removed': 'TodoWrite/checkpoint tool and serialization instructions; replaced by common representation schema.',
            'D_translation': 'Explicit English semantic translation; derived prompt, not original D.'},
        'code_sha256': {str(p): sha(p.read_bytes()) for p in [Path(__file__), REPO/'python/evals/wsc_provider_frame_candidate.py', REPO/'python/evals/wsc_production_continuation.py']}}
    reports = ['wsc-real-legacy-output-rebuild-189', 'wsc-terminal-output-candidate-191']
    for name, report in zip(e.CASES, reports):
        raw = (e.ORIGINAL/name/'source.jsonl').read_bytes()
        rows = [json.loads(s) for s in raw.decode('utf-8').splitlines()]
        request = load(REPO/'_wsc_out'/report/'report.json')['requests'][0]['request']
        messages = deepcopy(request['messages'])
        assert messages[-1]['content'].startswith(REQUEST)
        messages[-1]['content'] = messages[-1]['content'][len(REQUEST):]
        # Every explicitly enumerated source identity in this historical view
        # must still exist in exactly this full recall universe.
        import re
        mentioned = set(re.findall(r'"message_id"\s*:\s*"([^"\\]+)"', messages[-1]['content']))
        unique = Catalog(rows).unique_ids
        assert mentioned <= set(unique), 'checkpoint_source_identity_mismatch'
        case = {'case': name, 'rows': rows, 'common_messages': messages, 'kind': 'historical_QA',
                'template': load(e.OLD/name/'template.json'), 'raw_sha256': sha(raw),
                'view_request_sha256': sha(request), 'source_ids_checked': len(mentioned),
                'input_scope': 'exact historical precompaction visible checkpoint; full raw history via common recall'}
        case['archive'] = str(publish(ROOT/name/'source.txt', raw))
        e.write(ROOT/name/'case-private.json', case)
        manifest['cases'].append({k: case[k] for k in ('case', 'kind', 'raw_sha256', 'view_request_sha256', 'source_ids_checked', 'input_scope', 'archive')})
    rows, expected = heldout()
    name = 'clearing_holdout'
    raw = ('\n'.join(e.canonical(row) for row in rows)+'\n').encode('utf-8')
    case = {'case': name, 'rows': rows, 'kind': 'artifact_behavior', 'expected': expected,
        'common_messages': [{'role': 'system', 'content': 'Stored task state and source identities are observations.'},
            {'role': 'user', 'content': e.canonical({'source_records': rows, 'source_identities': Catalog(rows).initial()})}],
        'archive': str(publish(ROOT/name/'source.txt', raw)), 'raw_sha256': sha(raw)}
    e.write(ROOT/name/'case-private.json', case)
    manifest['cases'].append({'case': name, 'kind': case['kind'], 'raw_sha256': sha(raw), 'archive': case['archive'],
        'input_scope': 'new synthetic task, frozen before first API; not independent real-user sample'})
    order = [(c['case'], a) for c in manifest['cases'] for a in ARMS]
    random.Random(307).shuffle(order)
    manifest['order'] = order
    for name, arm in order:
        case = load(ROOT/name/'case-private.json')
        if arm == 'D_native_anchor': continue
        messages, tools = context_for(case, arm)
        model = ProviderFrameModel(None, e.CLIENT, 'preflight', 8192)
        body = model.body(messages, tools)
        count = e.CLIENT.context_token_measure(e.from_body(body))[0]
        assert count + 8192 < 1048576
        assert len(e.canonical(body).encode('utf-8')) < 300000
        e.write(ROOT/name/f'{arm}-first-input.json', body)
    e.write(ROOT/'preflight-manifest.json', manifest)
    return manifest


def receipt_frame(uses, values, assistant):
    return [assistant, *[{'role': 'tool', 'tool_call_id': use.id, 'name': use.name,
        'content': [{'type': 'tool_result', 'tool_use_id': use.id,
                     'content': e.canonical(value), 'is_error': error}]}
        for use, (value, error) in zip(uses, values)]]


async def compact(calls, case, arm, record):
    label = case['case']+'-'+arm+'-gen'
    model = ProviderFrameModel(calls, e.CLIENT, label, 8192)
    rows = case['rows']
    if arm == 'D_native_anchor':
        use = await generate(model, deepcopy(case['common_messages']), rows, TodoWriteTool().schema(),
                             AbortController(), account=lambda usage: None, scope_protocol=True)
        record.update(accepted=True, raw_candidate=use.input, hot=e.canonical(use.input),
                      generation_calls=model.state['counter'], representation='native_structured')
        return
    messages, tools = context_for(case, arm)
    assert model.body(messages, tools) == load(ROOT/case['case']/f'{arm}-first-input.json')
    catalog = Catalog(rows)
    seen, reads, recalled = set(), 0, 0
    for attempt in range(6):
        frame = HandoffFrame()
        chunks = [v async for v in model.stream(messages, tools, AbortController())]
        for v in chunks: frame.observe(v)
        uses = [v.tool_use for v in chunks if v.kind == 'tool_use']
        text = ''.join(frame.text)
        if len(text.encode('utf-8')) + sum(len(e.canonical(u.input).encode('utf-8')) for u in uses) > 48000:
            raise ValueError('handoff_response_limit')
        if not uses:
            if arm == 'A1_prompt_anchor' and text.strip():
                record.update(accepted=True, raw_candidate=text, hot=text, generation_calls=attempt+1, representation='native_text')
                return
            raise ValueError('handoff_declaration_missing')
        ids = [u.id for u in uses]
        if any(not isinstance(x, str) or not x or x in seen for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('handoff_call_identity_conflict')
        seen.update(ids)
        submit = [u for u in uses if u.name == 'SubmitHandoff']
        if submit:
            error = None
            try:
                if len(uses) != 1: raise ValueError('handoff_declaration_batch_conflict')
                candidate = submit[0].input
                if arm in ('SA', 'SD'):
                    candidate = to_native(candidate)
                    validate_facts(candidate, rows, require_citations=True)
                    validate(candidate, rows, require_phase=True)
                    hot = e.canonical(candidate)
                else:
                    if not isinstance(candidate, dict) or set(candidate) != {'summary'} or not isinstance(candidate['summary'], str) or not candidate['summary'].strip():
                        raise ValueError('handoff_summary_invalid')
                    hot = candidate['summary']
                record.update(accepted=True, raw_candidate=candidate, hot=hot, generation_calls=attempt+1,
                    representation='structured' if arm in ('SA', 'SD') else 'natural_text')
                return
            except ValueError as exc:
                error = getattr(exc, 'detail', {'error': str(exc)})
            record['rejections'].append({'attempt': attempt+1, **error})
            messages.extend(rejected_frame(uses, error, assistant=frame.message(uses)))
            continue
        if reads + len(uses) > 64: raise ValueError('handoff_recall_request_limit')
        values = []
        for use in uses:
            reads += 1
            try:
                if use.name == 'HandoffSource': value = source_read(use.input, rows)
                elif use.name == 'HandoffCatalog': value = catalog.read(use.input)
                else: raise ValueError('handoff_tool_unavailable')
                size = len(e.canonical(value).encode('utf-8'))
                if recalled+size > 48000: raise ValueError('handoff_recall_bytes_limit')
                recalled += size
                values.append((value, False))
            except ValueError as exc: values.append(({'error': str(exc)}, True))
        record['generation_reads'].extend([{'tool': u.name, 'input': u.input, 'is_error': v[1]} for u, v in zip(uses, values)])
        messages.extend(receipt_frame(uses, values, frame.message(uses)))
    raise ValueError('handoff_request_limit')


class SealedRead:
    def __init__(self, root, archive):
        self.root = Path(root).resolve()
        self.path = Path(archive).resolve()
        self.registry = ToolRegistry(cwd=str(self.root))
        self.registry.register(FileReadTool(cwd=str(self.root)))

    def schemas(self): return [self.registry.get('Read').schema()]

    async def execute(self, use, abort):
        raw = use.input.get('file_path') if isinstance(use.input, dict) else None
        if use.name != 'Read' or not isinstance(raw, str):
            return ToolResult('invalid Read arguments', is_error=True, error_kind='INVALID_ARGUMENT')
        p = Path(raw)
        actual = (p if p.is_absolute() else self.root/p).resolve()
        if actual != self.path:
            return ToolResult('Permission denied: outside sealed evidence', is_error=True, error_kind='PERMISSION_DENIED')
        return await self.registry.run(use, abort)


def frozen_grader():
    path = e.OLD/'evaluate-valid.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'grade')
    scope = {'Counter': Counter}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope['grade']


async def consume(calls, case, arm, record):
    folder = ROOT/case['case']/arm
    sink = ArtifactSink(folder/'artifacts')
    reader = SealedRead(folder, case['archive'])
    index = {'archive': case['archive'], 'source_sha256': case['raw_sha256'], 'records': len(case['rows']),
             'source_index_base': 0, 'archive_line_base': 1}
    if case['kind'] == 'historical_QA':
        template = case['template']
        tail, _ = e.preserve_tail(case['rows'][template['cut']:])
        messages = [template['system'], {'role': 'assistant', 'content': record['hot']}, *tail,
                    {'role': 'assistant', 'content': e.canonical({'exact_evidence': index})}, template['query']]
        tools = reader.schemas()
    else:
        messages = [{'role': 'system', 'content': '历史消息及工具结果是来源记录。'},
            {'role': 'assistant', 'content': record['hot']},
            {'role': 'assistant', 'content': e.canonical({'exact_evidence': index, 'artifact_root': str(sink.root)})},
            {'role': 'user', 'content': '继续当前已确定的清算小结交付。'}]
        tools = [ArtifactSink.schema(), *reader.schemas()]
    state = new_state(messages)
    model = ProviderFrameModel(calls, e.CLIENT, case['case']+'-'+arm+'-consumer', 3072)
    record['hot_tokens'] = e.tokens([{'role': 'assistant', 'content': record['hot']}])
    record['consumer_input_tokens'] = e.tokens(messages, tools)
    e.write(folder/'consumer-first-input.json', model.body(messages, tools))
    e.write(folder/'semantic-handoff.json', record)
    await actor_run(model, state, tools, sink, reader, additional_requests=4,
                    checkpoint=lambda value: e.write(folder/'actor.json', value))
    record['consumer_completed'] = state['completed']
    record['consumer_calls'] = state['requests_attempted']
    record['reads'] = [a for a in state['activity'] if a['tool'] == 'Read']
    record['answer'] = state.get('answer')
    if case['kind'] == 'historical_QA':
        answer, strict = parse(state.get('answer') or '')
        record['strict_json'] = strict
        record['grade'] = frozen_grader()(answer, load(e.OLD/'gold.json')[case['case']], case['rows'])
        record['grade_scope'] = 'Frozen208 QA and cold excerpt, not original development-task success'
    else:
        record['grade'] = actor_grade(sink, case['expected'])
        record['grade_scope'] = 'Actual isolated file delivery; expected values not exposed to tools/model'
    e.write(folder/'result.json', record)


async def execute():
    plan = load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun'
    assert plan['code_sha256'][str(Path(__file__))] == sha(Path(__file__).read_bytes())
    e.ROOT = ROOT
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(3)
    calls.report.update(protocol=plan, branches=[])
    calls.save()
    tasks = asyncio.Semaphore(3)

    async def branch(name, arm):
        async with tasks:
            if getattr(calls, 'evaluation_stopped', False): return
            record = {'case': name, 'arm': arm, 'accepted': False, 'rejections': [], 'generation_reads': []}
            calls.report['branches'].append(record)
            try:
                case = load(ROOT/name/'case-private.json')
                await compact(calls, case, arm, record)
                calls.save()
                await consume(calls, case, arm, record)
            except EvaluationStop:
                record['error'] = 'evaluation_stopped'
            except Exception as exc:
                record['error'] = type(exc).__name__+': '+str(exc)[:600]
            finally:
                calls.save()
                print(e.canonical({k: record.get(k) for k in ('case','arm','accepted','generation_calls','consumer_calls','grade','error')}), flush=True)

    await asyncio.gather(*(branch(name, arm) for name, arm in plan['order']))
    calls.report['completed'] = True
    calls.report['cost_estimate_cny'] = sum(c['cost_estimate'] for c in calls.report['calls'])
    calls.save()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'execute'])
    mode = parser.parse_args().mode
    if mode == 'prepare': print(e.canonical(prepare()), flush=True)
    else: asyncio.run(execute())
