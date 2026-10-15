"""Sidepath exact image assets and immutable source catalog, no wire injection.

Uses existing media ownership/storage and WSC atomic publication. Tool inputs
are not observations; remote references are preserved without downloading.
"""
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

ENV = 'XEYO_WSC_MEDIA_ARCHIVE'


def images(content, path='$', call_id=None):
    if isinstance(content, list):
        for index, block in enumerate(content):
            yield from images(block, f'{path}[{index}]', call_id)
    elif isinstance(content, dict):
        if content.get('type') == 'image_url':
            value = content.get('image_url')
            if isinstance(value, dict) and isinstance(value.get('url'), str):
                yield path, call_id, value['url']
        elif content.get('type') == 'tool_result':
            yield from images(content.get('content'), path + '.content', content.get('tool_use_id'))


def create(messages, region_end, *, cwd, session, source_layout='latest-notes-v1'):
    if os.environ.get(ENV, '').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None
    from media_store import save_image, media_path, is_media_ref
    from synaptic.contracts import publish
    from memory.wsc_head_store import region_seal
    from memory.wsc_source_layout import validate
    validate(source_layout)
    if type(region_end) is not int or not 0 <= region_end <= len(messages):
        raise ValueError('invalid_media_archive_boundary')
    seal = region_seal(messages, region_end, source_layout=source_layout)
    counts = Counter(row.get('message_id') or row.get('id') for row in messages)
    records = []
    for index, row in enumerate(messages[:region_end]):
        if row.get('role') not in {'user', 'human', 'tool'}:
            continue
        uid = row.get('message_id') or row.get('id')
        for location, call_id, url in images(row.get('content'), '$.content', row.get('tool_call_id')):
            record = {'source_index': index, 'source_message_id': uid if uid and counts[uid] == 1 else None,
                      'source_role': row['role'], 'content_path': location, 'declared_call_id': call_id}
            if url.startswith('data:image/') and ';base64,' in url:
                header, encoded = url.split(';base64,', 1)
                raw = base64.b64decode(encoded, validate=True)
                asset = save_image(raw, declared_mime=header.removeprefix('data:'))
                reference = asset.media_ref
                expected = hashlib.sha256(raw).hexdigest()
            elif is_media_ref(url):
                reference = url
                expected = reference.rsplit('://', 1)[1]
            else:
                record.update(availability='reference_only', original_reference=url)
                records.append(record)
                continue
            path = media_path(reference)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('stale_media_archive: content digest mismatch')
            record.update(availability='owned_exact_asset', media_ref=reference,
                          sha256=expected, image_path=str(path))
            records.append(record)
    if not records:
        return None
    data = ''.join(json.dumps({'session_id': session, 'source_layout': source_layout,
                              'source_seal': seal, 'region_end': region_end, **record}, ensure_ascii=False, sort_keys=True) + '\n'
                   for record in records).encode('utf-8')
    path = publish(Path(cwd) / '.xeyo_offload/wsc/media-index.txt', data)
    return {'path': str(path), 'records': records, 'count': len(records)}
