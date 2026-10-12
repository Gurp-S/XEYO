"""Small paired API check of receipt use; synthetic, not a compression eval."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from evals.wsc_drift_budget import Budget


def fixture(late):
    rows = [
        {'id': 'old', 'role': 'user', 'content': '旧任务：修复登录超时。'},
        {'id': 'switch', 'role': 'user', 'content': '登录任务已作废。当前任务只核对两份只读报告：以实际结果中 ledger_total 为准，忽略 sample_total。输出 JSON，字段 left、right、difference（right-left）、old_goal_status（closed）、evidence_call_ids（对应调用 ID 列表）。不执行任何修复。'},
        {'id': 'read-pair', 'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'left-call', 'name': 'Read', 'input': {'file_path': 'left-report'}},
            {'type': 'tool_use', 'id': 'right-call', 'name': 'Read', 'input': {'file_path': 'right-report'}}]},
    ]
    if late:
        rows.append({'id': 'pending', 'role': 'assistant', 'content': '两份只读报告尚未返回。'})
    rows.append({'id': 'actual-arrival', 'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'left-call', 'content': 'report=left\nledger_total=137\nsample_total=173'},
        {'type': 'tool_result', 'tool_use_id': 'right-call', 'content': 'report=right\nledger_total=211\nsample_total=281'}]})
    return rows


def acceptance(answer):
    try:
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', answer.strip())
        value = json.loads(clean)
    except (ValueError, TypeError):
        return {'valid_json': False, 'passed': False}
    checks = {'valid_json': isinstance(value, dict)}
    if isinstance(value, dict):
        checks.update(left=value.get('left') == 137, right=value.get('right') == 211,
                      difference=value.get('difference') == 74,
                      old_goal_closed=value.get('old_goal_status') == 'closed',
                      identities=isinstance(value.get('evidence_call_ids'), list)
                      and sorted(value['evidence_call_ids']) == ['left-call', 'right-call'])
    checks['passed'] = all(checks.values())
    return checks


def run(output, key_file, execute=False):
    from evals.client import chat
    from model.deepseek import DeepSeekModelClient
    from prompt.assembler import PromptAssembler
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.compression_source import compression_messages
    from session.late_result_projection import ENV, project, supported
    from memory.working import WorkingSnapshot
    output.mkdir(parents=True, exist_ok=False)
    prior_flag, prior_key = os.environ.get(ENV), os.environ.get('DEEPSEEK_API_KEY')
    budget, reports = Budget(total=0.15), []
    try:
        if execute:
            keys = re.findall(r'sk-[A-Za-z0-9_-]{16,}', key_file.read_text(encoding='utf-8-sig'))
            if len(keys) != 1:
                raise ValueError('key_file_format_ambiguous')
            os.environ['DEEPSEEK_API_KEY'] = keys[0]
        for label, late in [('adjacent_control', False), ('late_candidate', True)]:
            os.environ[ENV] = str(int(late))
            source = fixture(late)
            original = deepcopy(source)
            store = MessageStore(messages_from_rows(source))
            assert len(store.items) == len(source) and supported(store.items)
            rows = compression_messages(store, WorkingSnapshot())
            before = project(rows[:-1]) if late else None
            projected = project(rows)
            prefix_equal = not late or before == projected[:-1]
            assert prefix_equal
            messages = PromptAssembler().build('本会话的工具均为只读，工具记录含调用身份和结果正文。', rows)
            body = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')._build_body(messages, [], stream=False)
            body['max_tokens'] = 384
            body['temperature'] = 0
            report = {'label': label, 'synthetic_source': True, 'compression_exercised': False,
                      'source_sha256': hashlib.sha256(json.dumps(source, ensure_ascii=False).encode()).hexdigest(),
                      'source_unchanged': source == original, 'append_prefix_equal': prefix_equal}
            (output / (label + '-request.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
            if execute:
                entry = budget.admit(body, 384)
                try:
                    captured = chat(messages, model='deepseek-flash', thinking='disabled', max_tokens=384,
                                    temperature=0, retries=0, timeout=45, capture_wire=True)
                    response = captured['response']
                    (output / (label + '-response.json')).write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
                    budget.settle(entry, response.get('usage'))
                    answer = response['choices'][0]['message'].get('content') or ''
                    report.update(answer=answer, usage=response.get('usage'), acceptance=acceptance(answer))
                except Exception as exc:
                    # Do not persist provider detail or credentials on failures.
                    report.update(error=type(exc).__name__, acceptance={'passed': False})
            reports.append(report)
            (output / (label + '-report.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        for name, prior in [(ENV, prior_flag), ('DEEPSEEK_API_KEY', prior_key)]:
            if prior is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prior
    summary = {'scope': __doc__, 'executed': execute, 'arms': reports,
               'cost_upper': budget.spent_upper, 'budget_entries': budget.entries}
    (output / 'report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    summary = run(args.output, args.key_file, args.execute)
    print(json.dumps({'executed': summary['executed'], 'cost_upper': summary['cost_upper'],
                      'arms': [{'label': arm['label'], 'acceptance': arm.get('acceptance'), 'error': arm.get('error')}
                               for arm in summary['arms']]}, ensure_ascii=False))
