"""Offline full-window request preparation with the pinned official counter.

No provider request or model handoff. Current one-row task has no eligible
history: the real compactor must keep it, including above the 85% start.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from time import perf_counter


def run(output, models, selected=None):
    from engine.abort import AbortController
    from evals.wsc_unfolded_source_ab import environment
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    from memory.wsc_counted_input import CountedInput
    from memory.wsc_request_timing import prepare_counted
    from memory.wsc_timing import delivered, notification, request_measure
    from model.context_input import from_body
    from model.deepseek import DeepSeekModelClient
    from model.deepseek_count import BASIS
    from prompt.assembler import PromptAssembler
    raw = models.read_bytes()
    entry = next(item for item in json.loads(raw)['data'] if item['id'] == 'deepseek-flash')
    capacity = entry['context_window']
    assert isinstance(capacity, int) and capacity > 0
    output.mkdir(parents=True, exist_ok=False)
    schemas = [{'name': 'Read', 'description': 'Reads stored text.', 'input_schema': {
        'type': 'object', 'properties': {'file_path': {'type': 'string'}}}}]
    reports = []
    threshold80, threshold85 = (capacity * 80 + 99) // 100, (capacity * 85 + 99) // 100
    cases = [('ordinary20k', 20000), ('below80', threshold80 - 64),
             ('above80', threshold80 + 64), ('below85', threshold85 - 64),
             ('above85', threshold85 + 64), ('near_limit', capacity - 128),
             ('exceeds_limit', capacity + 64), ('output_reserve_exceeds', capacity - 32)]
    if selected:
        assert set(selected) <= {label for label, _ in cases}, 'unknown case'
        cases = [(label, target) for label, target in cases if label in selected]
    for label, target in cases:
        folder = output / label
        folder.mkdir()
        with environment(folder):
            working = WorkingSnapshot(session_id='capacity-' + label)
            model = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash',
                base_url='https://api.deepseek.com', thinking='disabled')
            model.context_limit, model._max_tokens = capacity, 64
            model.last_usage = {'prompt_tokens': capacity * 9}
            assembler = PromptAssembler()
            build = lambda rows: assembler.build('Current stored task.', rows)
            def rows_for(n):
                return [{'role': 'user', 'id': 'current-task', 'content':
                    'Current objective: preserve this source observation.\n' + 'field ' * n}]
            n, measured = target, None
            started = perf_counter()
            for _ in range(3):
                rows = rows_for(n)
                measured = request_measure(build(rows), schemas, context_limit=capacity, model=model)
                assert measured.basis == BASIS, 'reference unavailable: no byte-estimate benchmark'
                if measured.input_tokens == target:
                    break
                n += target - measured.input_tokens
            assert measured.input_tokens == target
            original = deepcopy(rows)
            count = CountedInput(model, AbortController())
            fold_calls = []
            def compact():
                fold_calls.append(working.compact_cursor)
                return force_compact(rows, working, cwd=folder)
            def render(value, text):
                return value + [{'role': 'user', 'note_key': 'context_capacity', 'content': text}]
            error, prepared = None, None
            try:
                prepared = asyncio.run(prepare_counted(rows, schemas, working,
                    context_limit=capacity, build=build, render=render, compact=compact, model=count))
            except ValueError as exc:
                error = str(exc)
            facts = working.wsc_timing_state['last_request_admission']
            expected_folds = int(target >= threshold85)
            assert len(fold_calls) == expected_folds
            assert rows == original and working.compact_cursor == 0
            assert (error is not None) == (label in {'exceeds_limit', 'output_reserve_exceeds'})
            assert facts['automatic_attempts'] == expected_folds
            assert model.last_usage == {'prompt_tokens': capacity * 9}
            report = {'label': label, 'capacity': capacity, 'target_reference_tokens': target,
                'source_bytes': len(rows[0]['content'].encode()), 'seconds': round(perf_counter() - started, 3),
                'facts': facts, 'compactor_calls': len(fold_calls), 'source_unchanged': True,
                'cursor': working.compact_cursor, 'error': error}
            if prepared is not None:
                body = model._build_body(prepared.messages, schemas, stream=False)
                assert from_body(body) == model.context_input(prepared.messages, schemas)
                assert sum('上下文已达80%' in str(row.get('content')) for row in prepared.messages) == int(target >= threshold80)
                if prepared.delivery_key is not None:
                    delivered(working, prepared.delivery_key)
                    text, _, _ = notification(build(rows), schemas, working, context_limit=capacity, model=count)
                    assert not text
                report.update(encoded_input_equal=True, notice_delivered_once=prepared.delivery_key is not None,
                    request_sha256=hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest())
            reports.append(report)
            (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'scope': __doc__, 'capacity_metadata_sha256': hashlib.sha256(raw).hexdigest(),
        'capacity_metadata_path': str(models.resolve()), 'cases': reports, 'api_calls': 0, 'cost': 0}
    (output / 'report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--case', action='append')
    args = parser.parse_args()
    report = run(args.output.resolve(), args.models, args.case)
    print(json.dumps({'api_calls': 0, 'cases': [{k: case[k] for k in
        ('label', 'capacity', 'target_reference_tokens', 'seconds', 'compactor_calls', 'error')}
        for case in report['cases']]}, ensure_ascii=False))
