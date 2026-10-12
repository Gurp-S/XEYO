"""Model use of a bound actual result arriving after a real offline fold.

Synthetic same-source control and two WSC channels; not a live 85% run.
No tools execute remotely. Every arm uses the same original goal and result.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from evals.wsc_drift_budget import Budget
from evals.wsc_unfolded_source_ab import environment


def fixture(media=False):
    from session.hydrate import messages_from_rows
    from session.transcript_blobs import message_fields
    goal = ('任务编号 reconciliation-125。只核对pending.txt的实际ledger_total与基线100，'
            'sample_total只是示例。输出JSON字段task_id、ledger_total、delta（实际减基线）、'
            'evidence_call_id、result_status（observed或unknown）。')
    if media:
        goal += ' 实际回执附图中的数字另存image_number，不能用正文数字替代。'
    rows = [{'id': 'goal', 'role': 'user', 'content': goal},
            {'id': 'invoke-pending', 'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'pending', 'name': 'Read',
                 'input': {'file_path': 'pending.txt'}}]}]
    recovered = [message_fields(item) for item in messages_from_rows(rows, session_id='semantic-recovery-125')]
    assert len(recovered) == 3
    return recovered + [{'id': f'work-{index}', 'role': 'assistant',
                         'content': f'观察记录{index}：sample_total=173。' + 'field ' * 200}
                        for index in range(24)]


def actual(media=False):
    body = 'report=pending.txt\nledger_total=137\nsample_total=173'
    if media:
        import base64
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont
        picture = Image.new('RGB', (200, 200), 'white')
        ImageDraw.Draw(picture).text((24, 50), '211',
            font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 80), fill='black')
        buffer = BytesIO()
        picture.save(buffer, format='PNG')
        body = [{'type': 'text', 'text': body}, {'type': 'image_url', 'image_url': {
            'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')}}]
    return {'id': 'actual-pending', 'role': 'tool', 'tool_call_id': 'pending', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'pending', 'is_error': False,
         'execution': {'complete': True},
         'content': body}]}


def acceptance(answer, media=False):
    try:
        value = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', answer.strip()))
    except (TypeError, ValueError):
        return {'valid_json': False, 'passed': False}
    if not isinstance(value, dict):
        return {'valid_json': False, 'passed': False}
    checks = {'valid_json': True, 'task': value.get('task_id') == 'reconciliation-125',
              'actual': value.get('ledger_total') == 137, 'delta': value.get('delta') == 37,
              'identity': value.get('evidence_call_id') == 'pending',
              'status': value.get('result_status') == 'observed'}
    if media:
        checks['image'] = value.get('image_number') == 211
    return {**checks, 'passed': all(checks.values())}


def run(output, key_file, execute=False, media=False):
    from evals.client import chat
    import evals.client as eval_client
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory import wsc_projection
    from model.deepseek import DeepSeekModelClient
    from model.context_input import from_body
    from memory.wsc_timing import request_measure
    from prompt.assembler import PromptAssembler
    from session.late_result_guard import request_conflict
    from session.late_result_projection import project
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source, reports, budget = fixture(media), [], Budget(total=0.4)
    original = deepcopy(source)
    source_hash = hashlib.sha256(json.dumps(source, ensure_ascii=False).encode()).hexdigest()
    arms = [('fallback_folded', False), ('native_folded', True)]
    if not media:
        arms.insert(0, ('unfolded', None))
    for label, native in arms:
        folder = output / label
        folder.mkdir()
        with environment(folder):
            os.environ['XEYO_LATE_RESULT_PROJECTION'] = '1'
            report = {'label': label, 'synthetic_source': True, 'source_sha256': source_hash,
                      'compression_exercised': native is not None}
            extended = source + [actual(media)]
            if native is None:
                current = project(extended)
                report['cursor'] = 0
            else:
                os.environ['XEYO_WSC'] = str(int(native))
                working = WorkingSnapshot(session_id='semantic-' + label)
                wsc_projection._STATE.pop(working.session_id, None)
                before = force_compact(source, working, cwd=folder)
                cursor = working.compact_cursor
                assert cursor > 3, 'original invocation not folded'
                current = project_for_model(extended, working, cwd=folder,
                                            capacity_managed=True, context_limit=1000000)
                assert current[0] == before[0] and working.compact_cursor == cursor
                flush(working.session_id, working)
                wsc_projection._STATE.pop(working.session_id, None)
                restored = hydrate(working.session_id, source_layout=working.compression_source_layout)
                replay = project_for_model(extended, restored, cwd=folder,
                                           capacity_managed=True, context_limit=1000000)
                assert replay == current
                report.update(cursor=cursor, head_unchanged=True, restart_equal=True)
                (folder / 'before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
            assert request_conflict(current) is None and source == original
            messages = PromptAssembler().build('本会话的工具记录包含调用身份、状态和结果正文。', current)
            # Recent prompt refers to the task; it does not supply missing fields or answers.
            messages.append({'role': 'user', 'content': '继续当前核对，输出约定的JSON。'})
            client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
            body = client._build_body(messages, [], stream=False)
            body.update(max_tokens=384, temperature=0)
            if media:
                image_count = sum(part.get('type') == 'image_url'
                    for message in body['messages'] if isinstance(message.get('content'), list)
                    for part in message['content'])
                assert image_count == 1, 'late image missing or duplicated on wire'
                report['wire_image_count'] = image_count
            assert client.context_input(messages, []) == from_body(body)
            measured = request_measure(messages, [], context_limit=1000000, model=client)
            report['measurement'] = {**measured.facts(), 'encoded_input_equal': True}
            (folder / 'request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
            (folder / 'projection.json').write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
            report.update(source_unchanged=True, guard=None)
            if execute:
                keys = re.findall(r'sk-[A-Za-z0-9_-]{16,}', key_file.read_text(encoding='utf-8-sig'))
                if len(keys) != 1:
                    raise ValueError('key_file_format_ambiguous')
                # Reserve twice the output allowance; input admission uses a byte bound.
                entry = budget.admit(body, 768)
                prior_key, prior_url = os.environ.get('DEEPSEEK_API_KEY'), eval_client.BASE_URL
                try:
                    os.environ['DEEPSEEK_API_KEY'] = keys[0]
                    eval_client.BASE_URL = 'https://api.deepseek.com'
                    captured = chat(messages, model='deepseek-flash', thinking='disabled',
                                    max_tokens=384, temperature=0, retries=0, timeout=45, capture_wire=True)
                    assert captured['request'] == body
                    response = captured['response']
                    (folder / 'response.json').write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
                    budget.settle(entry, response.get('usage'))
                    answer = response['choices'][0]['message'].get('content') or ''
                    report.update(answer=answer, usage=response.get('usage'), acceptance=acceptance(answer, media))
                    prompt = (response.get('usage') or {}).get('prompt_tokens')
                    if isinstance(prompt, int) and prompt > 0:
                        report['measurement'].update(provider_prompt_tokens=prompt,
                            error_percent=round(100 * (measured.input_tokens - prompt) / prompt, 2))
                except Exception as exc:
                    report.update(error=type(exc).__name__, acceptance={'passed': False})
                finally:
                    eval_client.BASE_URL = prior_url
                    if prior_key is None:
                        os.environ.pop('DEEPSEEK_API_KEY', None)
                    else:
                        os.environ['DEEPSEEK_API_KEY'] = prior_key
            reports.append(report)
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'scope': __doc__, 'executed': execute, 'arms': reports,
               'cost_peak_rate_estimate': budget.spent_upper, 'budget_entries': budget.entries}
    (output / 'report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--media', action='store_true')
    args = parser.parse_args()
    report = run(args.output, args.key_file, args.execute, args.media)
    print(json.dumps({'executed': report['executed'], 'cost_peak_rate_estimate': report['cost_peak_rate_estimate'],
                      'arms': [{key: arm.get(key) for key in ('label', 'cursor', 'head_unchanged', 'acceptance', 'error')}
                               for arm in report['arms']]}, ensure_ascii=False))
