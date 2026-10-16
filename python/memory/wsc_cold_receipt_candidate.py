"""Lossless receipt identity alongside a bounded decoded-payload view.

Receipt metadata is copied from the uniquely selected sealed source block.
No execution, status, version or applicability is inferred from result text.
An explicit record view exposes canonical source JSON through native ranges.
"""
from copy import deepcopy
import hashlib
import json

from memory.wsc_cold_locator_candidate import AddressedSources
from memory.wsc_handoff_recall import read
from synaptic.textutil import tool_result_blocks

METADATA_BYTES = 8192


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class ReceiptSources(AddressedSources):
    def source(self, arguments):
        if not isinstance(arguments, dict):
            raise ValueError('handoff_source_invalid_arguments')
        args = deepcopy(arguments)
        view = args.pop('view', 'payload')
        if view not in ('payload', 'record'):
            raise ValueError('cold_source_view_invalid')
        if view == 'record':
            # A record view does not decode a tool payload: structured/media
            # payloads are valid source JSON too. Reuse the shared locator and
            # native argument/uniqueness checks before reading the JSON view.
            native,index = self.resolve_locator(args)
            validated = read(native,self._sources)
            if index is None:
                index=next(i for i,r in enumerate(self._sources)
                    if str(r.get('message_id') or r.get('id'))==validated['message_id'])
            row=self._sources[index]
            text = canonical(row)
            value = read(native, [{'id': validated['message_id'], 'role': 'assistant', 'content': text}])
            return {**value, 'role': row.get('role'), 'source_index': index,
                'source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'archive_sha256': self.sha256,
                'representation': 'source_record_json'}
        # Payload identity/range checks stay native, including ambiguous IDs.
        result = super().source(args)
        row = self._sources[result['source_index']]
        if result.get('representation') != 'tool_result_text':
            return result
        blocks = [b for b in tool_result_blocks(row) if b.get('tool_use_id') == result['tool_call_id']]
        if len(blocks) != 1:
            raise ValueError('cold_result_source_not_unique')
        metadata = {k: deepcopy(v) for k, v in blocks[0].items() if k != 'content'}
        encoded = canonical(metadata).encode('utf-8')
        receipt = {'sha256': hashlib.sha256(encoded).hexdigest(),
            'complete': len(encoded) <= METADATA_BYTES,
            'source_record': {'message_id': result['message_id'], 'view': 'record'}}
        if receipt['complete']:
            receipt['metadata'] = metadata
        else:
            receipt['metadata_bytes'] = len(encoded)
        return {**result, 'receipt': receipt}

    @staticmethod
    def schemas():
        schemas = AddressedSources.schemas()
        schema = schemas[1]['input_schema']
        schema['properties']['view'] = {'type': 'string', 'enum': ['payload', 'record'], 'default': 'payload',
            'description': 'payload returns decoded result text; record returns canonical sealed source JSON.'}
        return schemas


class RecordSources(ReceiptSources):
    """Matched control: record recovery without automatic receipt metadata."""
    def source(self, arguments):
        value = super().source(arguments)
        value.pop('receipt', None)
        return value
