"""Factual wire view for uniquely paired, non-adjacent receipts."""
import json
import os
from collections import Counter

from msgtypes.message import Message
from session.late_result_guard import displaced_calls, call_counts
from session.result_identity import result_ids

ENV = 'XEYO_LATE_RESULT_PROJECTION'


def enabled():
    return os.environ.get(ENV, '1').lower().strip() in {'1', 'true', 'on', 'yes'}


def inline_image(block):
    if not isinstance(block, dict) or block.get('type') != 'image_url':
        return False
    image = block.get('image_url')
    url = image.get('url') if isinstance(image, dict) else None
    # Both existing provider encoders accept this shared inline shape.
    # Other references need their own materialization/ownership contract.
    return (isinstance(url, str) and url.startswith('data:image/')
            and ';base64,' in url and bool(url.partition(';base64,')[2]))


def image_source(block):
    if inline_image(block):
        return True
    if not isinstance(block, dict) or block.get('type') != 'image_url':
        return False
    image = block.get('image_url')
    url = image.get('url') if isinstance(image, dict) else None
    from media_store import is_media_ref
    return isinstance(url, str) and url.startswith('xeyo-media://') and is_media_ref(url)


def result_body_supported(body):
    return isinstance(body, str) or (isinstance(body, list) and all(
        isinstance(block, dict) and (
            block.get('type') == 'text' and isinstance(block.get('text'), str)
            or image_source(block)) for block in body))


def receipt_blocks(content, call_id):
    """Envelope-bound content is one result, including a structured body.

    Explicit result blocks retain their row-level siblings and identities.
    A flat content array bound by the envelope is the result body itself.
    """
    if isinstance(content, list) and any(
            isinstance(block, dict) and block.get('type') == 'tool_result' for block in content):
        return content
    return [{'type': 'tool_result', 'tool_use_id': call_id, 'content': content}]


def media_header(row, ids, *, call_id=None, block_index=None, image_index):
    binding = {'source_message_id': row.get('message_id') or row.get('id'),
               'projected_message_image_index': image_index}
    if call_id is None:
        binding.update(binding='source_message', call_ids=ids, block_index=block_index)
    else:
        binding.update(binding='result_body', call_id=call_id, block_index=block_index)
    return {'type': 'text', 'text': 'Recorded source media: ' + json.dumps(binding, ensure_ascii=False)}


def native_structured_result(block, uid, row, ids, *, image_index):
    """Native identity remains native; media travels with its exact binding.

    Both wire encoders stringify native result bodies. Serialize text blocks
    losslessly and replace image payloads with position references; transport
    the actual image blocks separately instead of stringifying base64.
    """
    body, media = [], []
    for index, part in enumerate(block['content']):
        if image_source(part):
            body.append({'type': 'image', 'source_block_index': index})
            media.extend([media_header(row, ids, call_id=uid, block_index=index, image_index=image_index), part])
            image_index += 1
        else:
            body.append(part)
    return dict(block, content=json.dumps(body, ensure_ascii=False)), media


def supported(items):
    calls = call_counts(items)
    from session.recovery_result_chain import supersessions
    supplements = supersessions(items)
    results = Counter(uid for index, item in enumerate(items) for uid in result_ids(item)
                      if uid and (index, uid) not in supplements)
    displaced = set(displaced_calls(items))
    if (any('' in result_ids(item) for item in items)
            or any(count != 1 for count in calls.values()) or any(count != 1 for count in results.values())
            or any(uid not in calls for uid in results)
            or any(uid not in results and uid not in displaced for uid in calls)):
        return False
    late = displaced
    for index, item in enumerate(items):
        if not result_ids(item):
            continue
        if item.role not in {'tool', 'user'}:
            return False
        blocks = receipt_blocks(item.content, item.tool_call_id)
        if not any(isinstance(block, dict) and (
                str(block.get('tool_use_id') or item.tool_call_id or '') in late
                or (index, str(block.get('tool_use_id') or item.tool_call_id or '')) in supplements) for block in blocks):
            continue
        if not all(isinstance(block, dict) and (
                   block.get('type') == 'tool_result' and result_body_supported(block.get('content'))
                   or block.get('type') == 'text' and isinstance(block.get('text'), str)
                   or image_source(block)) for block in blocks):
            return False
    return True


def project(rows):
    if not enabled():
        return rows
    items = [Message(role=row['role'], content=row.get('content', ''), id=row.get('message_id') or row.get('id') or '',
                     tool_call_id=row.get('tool_call_id'), name=row.get('name'), note_key=row.get('note_key', '')) for row in rows]
    late = set(displaced_calls(items))
    from session.recovery_result_chain import supersessions
    supplements = supersessions(items)
    if (not late and not supplements) or not supported(items):
        return rows
    names = {str(block['id']): block.get('name') for item in items
             if item.role == 'assistant' and isinstance(item.content, list)
             for block in item.content if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('id')}
    out = []
    for row_index, row in enumerate(rows):
        content = row.get('content')
        if row.get('role') == 'assistant' and isinstance(content, list):
            blocks = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_use' and str(block.get('id')) in late:
                    blocks.append({'type': 'text', 'text': 'Recorded tool invocation: ' + json.dumps({
                        'source_message_id': row.get('message_id') or row.get('id'),
                        'call_id': block.get('id'), 'name': block.get('name'), 'input': block.get('input')}, ensure_ascii=False)})
                else:
                    blocks.append(block)
            out.append(dict(row, content=blocks))
        elif row.get('role') in {'tool', 'user'}:
            blocks = receipt_blocks(content, row.get('tool_call_id'))
            ids = [str(block.get('tool_use_id') or row.get('tool_call_id') or '') for block in blocks
                   if isinstance(block, dict) and block.get('type') == 'tool_result']
            if any(uid in late or (row_index, uid) in supplements for uid in ids):
                rendered = []
                image_index = 0
                for source_index, block in enumerate(blocks):
                    uid = str(block.get('tool_use_id') or row.get('tool_call_id') or '')
                    if block.get('type') != 'tool_result':
                        if image_source(block):
                            rendered.append(media_header(row, ids, block_index=source_index, image_index=image_index))
                            image_index += 1
                        rendered.append(block)
                        continue
                    if uid not in late and (row_index, uid) not in supplements:
                        if isinstance(block.get('content'), list):
                            native, media = native_structured_result(block, uid, row, ids, image_index=image_index)
                            image_index += sum(image_source(part) for part in block['content'])
                            rendered.append(native)
                            rendered.extend(media)
                        else:
                            rendered.append(block)
                        continue
                    meta = {'source_message_id': row.get('message_id') or row.get('id'), 'call_id': uid,
                            'name': names.get(uid),
                            'arrival': 'non_adjacent',
                            'is_error': bool(block.get('is_error'))}
                    prior_index = supplements.get((row_index, uid))
                    if prior_index is not None:
                        meta.update(arrival='after_recovery_observation',
                                    recovery_observation_kind='outcome_unknown',
                                    recovery_observation_message_id=items[prior_index].id)
                    body = block.get('content', '')
                    header = 'Recorded tool result: ' + json.dumps(meta, ensure_ascii=False)
                    if isinstance(body, list):
                        rendered.append({'type': 'text', 'text': header})
                        for index, part in enumerate(body):
                            if image_source(part):
                                rendered.append(media_header(row, ids, call_id=uid, block_index=index, image_index=image_index))
                                image_index += 1
                            rendered.append(part)
                    else:
                        rendered.append({'type': 'text', 'text': header + '\n' + body})
                # Native receipts precede the factual/media carrier on the
                # wire. Ordering of the canonical stored row is untouched.
                native = [block for block in rendered if block.get('type') == 'tool_result']
                facts = [block for block in rendered if block.get('type') != 'tool_result']
                recorded = {**row, 'role': 'user', 'content': native + facts}
                recorded.pop('tool_call_id', None)
                out.append(recorded)
            else:
                out.append(row)
        else:
            out.append(row)
    return out
