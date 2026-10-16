"""Cold identity/range directory; no semantic ranking or lifecycle inference."""
from synaptic.textutil import tool_use_blocks, tool_result_blocks


def records(views):
    """Each view supplies (name, readable path, rows, exact rendered spans).

    Duplicate execution identities retain all receipts. Row position identifies
    an occurrence; an index entry does not certify semantic support or currency.
    """
    result = [{'format': 'wsc_evidence_index_v1',
               'views': {name: path.as_posix() for name, path, _, _ in views},
               'records': {name: len(rows) for name, _, rows, _ in views},
               'discovery': {'content': 'Grep(pattern=<regex>, path=<views path>, output_mode="content") returns matching source lines.',
                             'identity': 'Grep on this directory matches message_id and invocation identities.',
                             'read': 'Read(file_path=<views path>, offset=<line>, limit=<lines>) returns exact source records; oversized records use json_chunks.'}}]
    for name, path, rows, spans in views:
        if len(rows) != len(spans):
            raise ValueError('semantic_evidence_span_mismatch')
        for ordinal, (row, (offset, limit)) in enumerate(zip(rows, spans)):
            item = {'view': name, 'source': ordinal,
                    'message_id': row.get('message_id') or row.get('id'),
                    'role': row.get('role'), 'file_path': path.as_posix(),
                    'offset': offset, 'limit': limit}
            for key, blocks, field in (
                ('tool_call_ids', tool_use_blocks(row), 'id'),
                ('tool_result_call_ids', tool_result_blocks(row), 'tool_use_id'),
            ):
                ids = [block[field] for block in blocks if isinstance(block.get(field), str) and block[field]]
                if ids:
                    item[key] = ids
            result.append(item)
    return result
