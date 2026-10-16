"""Stage working cursor changes until emitted media entrances cover retirement.

The existing caller serializes session mutation. Immutable orphan publications
may remain on refusal; this module never deletes or repairs cold artifacts.
"""
from copy import deepcopy
import json
from pathlib import Path


def fold(operation, messages, working, **kwargs):
    from memory.wsc_media_archive import images
    from memory.wsc_head_store import region_seal, load
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
            frozen = load(staged.session_id, cwd=str(kwargs.get('cwd') or ''),
                          cursor=staged.compact_cursor, messages=messages,
                          source_layout=staged.compression_source_layout)
            references = frozen.evidence_paths if frozen is not None else staged.c2_evidence_paths
            for name in references:
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
                    # A retained head can reference an earlier valid catalog.
                    # Coverage is the union of exact sources, not catalog age.
                    if (type(end) is not int or not 0 < end <= len(messages)
                            or type(record.get('source_index')) is not int
                            or not 0 <= record['source_index'] < end):
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
