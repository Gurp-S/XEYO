"""Stage working cursor changes until emitted media entrances cover retirement.

The existing caller serializes session mutation. Immutable orphan publications
may remain on refusal; this module never deletes or repairs cold artifacts.
"""
from copy import deepcopy
import ast
import json
from pathlib import Path


def fold(operation, messages, working, **kwargs):
    from memory.wsc_media_archive import images
    from memory.wsc_publication import _READ
    from memory.wsc_head_store import region_seal
    from synaptic.contracts import verify_object
    staged = deepcopy(working)
    emitted = operation(messages, staged, **kwargs)
    if staged.compact_cursor > working.compact_cursor:
        required = {(index, location) for index, row in enumerate(messages[:staged.compact_cursor])
                    if row.get('role') in {'user', 'human', 'tool'}
                    for location, _, _ in images(row.get('content'), '$.content', row.get('tool_call_id'))}
        if required:
            covered = set()
            seals = {}
            head = emitted[0].get('content', '') if emitted else ''
            for match in _READ.finditer(head if isinstance(head, str) else ''):
                if 'media-index.v-sha256-' not in match.group(1):
                    continue
                name = ast.literal_eval(match.group(1))
                path = Path(name)
                if not path.name.startswith('media-index.v-sha256-'):
                    continue
                if not path.is_absolute():
                    path = Path(kwargs.get('cwd') or '.') / path
                if not verify_object(path):
                    raise ValueError('media_fold_catalog_unsealed')
                for line in path.read_text(encoding='utf-8').splitlines():
                    record = json.loads(line)
                    end = record['region_end']
                    layout = staged.compression_source_layout
                    if type(end) is not int or not staged.compact_cursor <= end <= len(messages):
                        raise ValueError('media_fold_catalog_source_mismatch')
                    if end not in seals:
                        seals[end] = region_seal(messages, end, source_layout=layout)
                    if (record['session_id'] != staged.session_id
                            or record['source_layout'] != layout
                            or record['source_seal'] != seals[end]):
                        raise ValueError('media_fold_catalog_source_mismatch')
                    covered.add((record['source_index'], record['content_path']))
            if not required <= covered:
                raise ValueError('media_fold_catalog_coverage_missing')
    working.__dict__.update(staged.__dict__)
    return emitted
