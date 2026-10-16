"""Exact source publication with bounded readable records and media ownership."""
import json


def _records(path, rows):
    from synaptic.contracts import publish as seal
    from synaptic.chunked_recovery import encoded_members
    from synaptic.coldstore import ColdStore
    texts = [json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')) for row in rows]
    raw = seal(path, ('\n'.join(texts) + '\n').encode('utf-8'))
    readable, lines = raw, len(texts)
    encoding = 'jsonl'
    spans = [(index + 1, 1) for index in range(len(texts))]
    # Existing chunk encoding preserves offsets, checksum and exact string
    # content. Unlike a single oversized JSONL record, every page is readable.
    if any(len(text) > 16000 for text in texts):
        cold = ColdStore(texts=dict(enumerate(texts)))
        rendered = [encoded_members(cold, [index]) if len(text) > 16000 else text
                    for index, text in enumerate(texts)]
        spans, offset = [], 1
        for record in rendered:
            count = record.count('\n') + 1
            spans.append((offset, count))
            offset += count
        body = '\n'.join(rendered) + '\n'
        readable = seal(path.with_name(path.stem + '-readable.txt'), body.encode('utf-8'))
        lines = body.count('\n')
        encoding = 'jsonl; oversized_records=json_chunks'
    return raw, readable, lines, encoding, spans


def publish(rows, cut, working, root, *, original_rows=None, evidence_paths=None):
    from memory.wsc_projection import _view_path_for
    from memory.wsc_media_archive import images
    from memory.wsc_media_directory import pin
    from memory.wsc_semantic_originals import validate
    validate(rows, original_rows)
    path = _view_path_for(str(root), working.session_id)
    raw, readable, lines, encoding, spans = _records(path, rows)
    objects = {str(raw), str(readable)}
    views = [('compression', readable, rows, spans)]
    if original_rows is not None:
        original, view, count, form, spans = _records(path.with_name(path.stem + '-original.jsonl'), original_rows)
        objects.update((str(original), str(view)))
        views.append(('original', view, original_rows, spans))
    from memory.wsc_evidence_index import records
    index, index_view, count, form, _ = _records(path.with_name(path.stem + '-evidence-index.jsonl'), records(views))
    objects.update((str(index), str(index_view)))
    entrance = (f"证据定位目录: Read(file_path={index_view.as_posix()!r}, offset=1, limit=1) "
                f"span=1-{count}; 含原文路径与消息/调用身份定位，Grep按内容搜索，Read精确读取。")
    media = pin(rows, cut, cwd=root, session=working.session_id, source_layout=working.compression_source_layout)
    required = any(list(images(row.get('content'))) for row in rows[:cut]
                   if row.get('role') in {'user', 'human', 'tool'})
    if required and media is None:
        raise ValueError('semantic_media_archive_unavailable')
    if media:
        entrance += '\n' + media.text
        objects.update(media.evidence_paths)
    if evidence_paths is not None:
        evidence_paths.update(objects)
    return raw, entrance
