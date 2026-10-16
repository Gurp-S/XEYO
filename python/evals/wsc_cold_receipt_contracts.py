"""Receipt recovery contracts and paid-source audit; no model/API calls."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from memory.wsc_cold_locator_candidate import AddressedSources
from memory.wsc_cold_receipt_candidate import ReceiptSources, canonical, METADATA_BYTES

ROOT = Path('D:/lea/XenYon code/_wsc_out') / os.environ.get('WSC_RECEIPT_CONTRACT_RUN','wsc-D-receipt-envelope-258')


def main():
    assert not (ROOT / 'contracts.json').exists()
    ROOT.mkdir(exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'source.jsonl'
        execution = {'id': 'opaque-execution', 'revision': 12, 'late': False, 'complete': True, 'status': 'ok'}
        one = {'type': 'tool_result', 'tool_use_id': 'one', 'content': '中文 exact result', 'is_error': False, 'execution': execution}
        rows = [{'id': 'single', 'role': 'tool', 'content': [one]},
            {'id': 'mixed', 'role': 'tool', 'content': [one, {'type': 'tool_result', 'tool_use_id': 'two', 'content': 'other', 'is_error': True, 'execution': None}]},
            {'id': 'user', 'role': 'user', 'content': 'plain text'},
            {'id': 'large', 'role': 'tool', 'content': [{**one, 'execution': {**execution, 'extra': '大' * METADATA_BYTES}}]},
            {'id': 'unknown', 'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': 'unknown', 'content': 'ok'}]},
            {'id': 'structured', 'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': 'media',
                'content': [{'type': 'image', 'source': {'type': 'base64', 'data': 'test-only'}}], 'execution': execution}]}]
        raw = ''.join(canonical(row) + '\n' for row in rows).encode()
        path.write_bytes(raw)
        seal = hashlib.sha256(raw).hexdigest()
        old, new = AddressedSources(path, seal), ReceiptSources(path, seal)
        args = {'message_id': 'single', 'offset': 0, 'limit': 9}
        before = deepcopy(args)
        value = new.source(args)
        assert {k: v for k, v in value.items() if k != 'receipt'} == old.source(args)
        assert value['receipt']['metadata']['execution'] == execution
        assert args == before and value['receipt']['metadata']['execution']['late'] is False
        checks.append('decoded_payload_and_exact_execution_identity_retained')
        value['receipt']['metadata']['execution']['revision'] = 99
        assert new.source(args)['receipt']['metadata']['execution'] == execution
        checks.append('returned_metadata_does_not_mutate_sealed_archive_or_reader')
        selected = new.source({'source_index': 1, 'call_id': 'two', 'offset': 0, 'limit': 9})
        assert selected['receipt']['metadata']['execution'] is None and selected['receipt']['metadata']['is_error'] is True
        unknown = new.source({'message_id': 'unknown', 'offset': 0, 'limit': 9})
        assert 'execution' not in unknown['receipt']['metadata']
        checks.append('mixed_call_selection_and_null_missing_metadata_not_defaulted')
        large = new.source({'message_id': 'large', 'offset': 0, 'limit': 9})
        assert large['receipt']['complete'] is False and 'metadata' not in large['receipt']
        text, offset = '', 0
        for _ in range(20):
            page = new.source({'message_id': 'large', 'view': 'record', 'offset': offset, 'limit': 4096})
            text += page['content']
            if page['next_offset'] is None: break
            offset = page['next_offset']
        assert text == canonical(rows[3]) and json.loads(text) == rows[3]
        assert hashlib.sha256(text.encode()).hexdigest() == page['source_sha256']
        checks.append('oversize_metadata_explicit_defer_and_lossless_paged_record_recovery')
        for args in ({'message_id': 'single', 'view': 'record', 'query': 'opaque-execution', 'limit': 50},
                     {'source_index': 0, 'view': 'record', 'offset': 2, 'limit': 5}):
            result = new.source(args)
            assert result['representation'] == 'source_record_json'
            if 'content' in result:
                assert result['content'] == canonical(rows[0])[result['offset']:result['offset']+len(result['content'])]
            else:
                assert all(p['content'] == canonical(rows[0])[p['offset']:p['end_offset']] for p in result['passages'])
        checks.append('source_record_unicode_offsets_and_literal_passages_exact')
        structured=new.source({'message_id':'structured','view':'record','offset':0,'limit':4096})
        assert json.loads(structured['content'])==rows[5]
        checks.append('structured_and_media_payload_source_json_recoverable')
        assert new.source({'message_id': 'user', 'offset': 0, 'limit': 5}) == old.source({'message_id': 'user', 'offset': 0, 'limit': 5})
        assert new.catalog({'start': 0, 'limit': 5}) == old.catalog({'start': 0, 'limit': 5})
        checks.append('text_source_and_catalog_unchanged')
        for args in ({'message_id': 'single', 'view': 'bad', 'offset': 0, 'limit': 5},
                     {'source_index': 0, 'message_id': 'single', 'view': 'record', 'offset': 0, 'limit': 5},
                     {'message_id': 'mixed', 'call_id': 'missing', 'offset': 0, 'limit': 5},
                     {'message_id': 'single', 'offset': -1, 'limit': 5}):
            try: new.source(args)
            except ValueError: pass
            else: raise AssertionError(('invalid accepted', args))
        checks.append('view_range_and_source_identity_failures_stay_closed')
        assert new.reopen().source({'message_id': 'single', 'offset': 0, 'limit': 9})['receipt']['metadata']['execution'] == execution
        assert path.read_bytes() == raw
        checks.append('restart_and_original_archive_bytes_preserved')
    old_run = ROOT.parent / 'wsc-D-consumer-mode-255'
    plan = json.loads((old_run / 'preflight-manifest.json').read_text(encoding='utf-8'))
    audits = []
    for sample in plan['samples']:
        if sample['arm'] != 'D_slot' or sample['mode'] != 'enabled': continue
        cold = ReceiptSources(sample['source'], sample['source_sha256'])
        for version in (1, 2):
            uid = sample['case'] + f'-probe-call-r{version}-receipt'
            args = {'message_id': uid, 'offset': 0, 'limit': 4096}
            prior = AddressedSources(sample['source'], sample['source_sha256']).source(args)
            value = cold.source(args)
            assert 'execution' not in prior
            assert value['receipt']['metadata']['execution']['id'] == sample['case'] + f'-execution-r{version}'
            assert value['receipt']['metadata']['execution']['revision'] == version
            assert value['receipt']['metadata']['execution']['late'] is (version == 1)
            audits.append({'case': sample['case'], 'message_id': uid, 'old_metadata_missing': True,
                'metadata_recovered': True, 'metadata': value['receipt']['metadata'],
                'payload_unchanged': value['content'] == prior['content']})
    result = {'checks': checks, 'audits': audits, 'api_calls': 0,
        'nonclaim': 'Mechanical completeness only; no consumer/semantic success or production admission.'}
    (ROOT / 'contracts.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': len(checks), 'real_receipt_audits': len(audits), 'api_calls': 0}))


if __name__ == '__main__': main()
