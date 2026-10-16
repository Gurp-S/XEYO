"""Zero-API cold-read contract and original paid-tool replay, no regrading."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import tempfile

from memory.wsc_cold_default_range_candidate import DefaultRangeSources
from memory.wsc_cold_locator_candidate import AddressedSources

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-D-default-range-256')
OLD = ROOT.parent / 'wsc-D-consumer-mode-255'


def main():
    assert not (ROOT / 'contracts.json').exists()
    ROOT.mkdir(exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / 'sources.jsonl'
        rows = [{'id': 'u', 'role': 'user', 'content': '中文前缀 first second'},
                {'id': 'r', 'role': 'tool', 'content': [
                    {'type': 'tool_result', 'tool_use_id': 'call', 'content': 'exact result'}]}]
        raw = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode()
        source.write_bytes(raw)
        seal = hashlib.sha256(raw).hexdigest()
        old = AddressedSources(source, seal)
        new = DefaultRangeSources(source, seal)
        for locator in ({'message_id': 'u'}, {'source_index': 0}):
            args = {**locator, 'limit': 4}
            before = deepcopy(args)
            assert new.source(args) == old.source({**args, 'offset': 0})
            assert args == before
        checks.append('omitted_range_exact_prefix_both_locators_without_input_mutation')
        for selector in ({'offset': 2}, {'query': 'second'}):
            args = {'message_id': 'u', 'limit': 10, **selector}
            assert new.source(args) == old.source(args)
        checks.append('explicit_offset_and_literal_query_unchanged')
        assert new.source({'message_id': 'r', 'call_id': 'call', 'limit': 12}) == old.source(
            {'message_id': 'r', 'call_id': 'call', 'limit': 12, 'offset': 0})
        checks.append('exact_tool_result_payload_binding_unchanged')
        invalid = [None, {}, {'message_id': 'u', 'limit': 4, 'offset': True},
            {'message_id': 'u', 'limit': 4, 'offset': -1},
            {'message_id': 'u', 'limit': 4, 'offset': 0, 'query': '中'},
            {'message_id': 'u', 'source_index': 0, 'limit': 4},
            {'source_index': 9, 'limit': 4}, {'message_id': 'missing', 'limit': 4},
            {'message_id': 'u', 'limit': 0}, {'message_id': 'u', 'limit': 4097},
            {'message_id': 'r', 'call_id': 'wrong', 'limit': 4},
            {'message_id': 'u', 'limit': 4, 'unknown': 'x'}]
        for args in invalid:
            try: new.source(args)
            except ValueError: pass
            else: raise AssertionError(('invalid accepted', args))
        checks.append('invalid_locator_selector_limit_and_call_identity_rejected')
        original = AddressedSources.schemas()
        schema = new.schemas()
        wire = schema[1]['input_schema']
        assert wire['required'] == ['limit']
        assert wire['allOf'][0] == original[1]['input_schema']['allOf'][0]
        assert wire['allOf'][1] == {'not': {'required': ['offset', 'query']}}
        assert wire['additionalProperties'] is False
        assert wire['properties']['offset']['default'] == 0
        assert original == AddressedSources.schemas()
        assert schema[0] == original[0]
        checks.append('published_schema_agrees_with_range_and_locator_contract')
        assert new.reopen().source({'message_id': 'u', 'limit': 4}) == new.source({'message_id': 'u', 'limit': 4})
        assert source.read_bytes() == raw
        try: DefaultRangeSources(source, '0' * 64)
        except ValueError: pass
        else: raise AssertionError('seal mismatch accepted')
        checks.append('seal_restart_and_archive_immutability')
    plan = json.loads((OLD / 'preflight-manifest.json').read_text(encoding='utf-8'))
    report = json.loads((OLD / 'run-report.json').read_text(encoding='utf-8'))
    replays = []
    for record in report['observations']:
        sample = next(s for s in plan['samples'] if all(s[k] == record[k] for k in ('case', 'arm', 'mode')))
        old = AddressedSources(sample['source'], sample['source_sha256'])
        new = DefaultRangeSources(sample['source'], sample['source_sha256'])
        for use in record['reads']:
            args = json.loads(use['args'])
            try: before = old.call(use['tool'], args); error_before = None
            except ValueError as exc: before = None; error_before = str(exc)
            try: after = new.call(use['tool'], args); error_after = None
            except ValueError as exc: after = None; error_after = str(exc)
            if error_before is None: assert before == after
            if error_before is not None and error_after is None:
                assert use['tool'] == 'SourceRead' and 'offset' not in args and 'query' not in args
                assert after == old.call(use['tool'], {**args, 'offset': 0})
            replays.append({'case': record['case'], 'arm': record['arm'], 'mode': record['mode'],
                'tool': use['tool'], 'arguments': args, 'old_error': error_before, 'new_error': error_after,
                'exact_output_sha256': hashlib.sha256(json.dumps(after, ensure_ascii=False, sort_keys=True).encode()).hexdigest() if after is not None else None})
    checks.append('all_original_successful_paid_tool_calls_byte_equivalent')
    result = {'checks': checks, 'replays': replays, 'api_calls': 0,
        'old_errors': sum(r['old_error'] is not None for r in replays),
        'new_errors': sum(r['new_error'] is not None for r in replays),
        'nonclaim': 'Offline interface improvement only; no model continuation, task success, or production admission.'}
    (ROOT / 'contracts.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'replays'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
