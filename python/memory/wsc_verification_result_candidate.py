"""Bounded whole results for verification identities already selected by model.

No semantic ranking or current-result inference. Native invocation/receipt
pairing and recovery supersession remain authoritative. Deferred results keep
their source locators; the original checkpoint and archive are never changed.
"""
from copy import deepcopy
import hashlib
import json

from synaptic.task_checkpoint import validate
from synaptic.task_verification import collect
from synaptic.textutil import tool_result_blocks

MAX_PAYLOAD_BYTES = 2048
MAX_PACKET_BYTES = 8192


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def materialize(sources, checkpoint):
    checkpoint = validate(checkpoint)
    ids = checkpoint['verification_call_ids']
    observed, unknown, _ = collect(sources, ids, len(sources), inline_bytes=0)
    selected, deferred = [], []
    # Chronology is a physical source order, not semantic applicability. Late
    # receipt metadata is copied too; a recent result is not marked current.
    for item in sorted(observed, key=lambda item: item['source'], reverse=True):
        row = sources[item['source']]
        block = next(b for b in tool_result_blocks(row) if b.get('tool_use_id') == item['call_id'])
        payload = block.get('content')
        encoded = canonical(payload).encode('utf-8')
        entry = {'call_id': item['call_id'], 'source_message_id': row.get('message_id') or row.get('id'),
            'source_index': item['source'], 'payload_sha256': hashlib.sha256(encoded).hexdigest(),
            'receipt_metadata': {k: deepcopy(v) for k,v in block.items() if k != 'content'},
            'result': deepcopy(payload)}
        prospective = {'results': selected+[entry], 'deferred_call_ids': ids, 'unresolved': unknown}
        if (len(encoded) <= MAX_PAYLOAD_BYTES and entry['source_message_id']
                and len(canonical(prospective).encode('utf-8')) <= MAX_PACKET_BYTES):
            selected.append(entry)
        else:
            deferred.append(item['call_id'])
    result = {'results': selected, 'deferred_call_ids': deferred, 'unresolved': unknown}
    if len(canonical(result).encode('utf-8')) > MAX_PACKET_BYTES:
        raise ValueError('verification_result_packet_exceeds_budget')
    return result
