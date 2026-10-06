"""Preserve explicitly identified WSC cold-view recovery receipts after C0/C1."""
import os
from pathlib import Path
from synaptic.read_budget import MAX_READ_CHARS

MAX_RECOVERY_CHARS = MAX_READ_CHARS


def normalized(path, cwd):
    try:
        value = Path(path)
        if not value.is_absolute():
            value = Path(cwd)/value
        return os.path.normcase(str(value.resolve()))
    except (OSError, ValueError, RuntimeError, TypeError):
        return None


def restore(emitted, messages, base, frozen_attr, *, cwd, view_path):
    if not view_path:
        return emitted
    known = normalized(view_path, cwd)
    if known is None:
        return emitted
    calls = {}
    ambiguous = set()
    for index, message in enumerate(messages):
        if message.get('role') != 'assistant' or not isinstance(message.get('content'), list):
            continue
        for block in message['content']:
            if not isinstance(block, dict) or block.get('type') != 'tool_use':
                continue
            uid = block.get('id')
            if not isinstance(uid, str) or not uid:
                continue
            if uid in calls:
                ambiguous.add(uid)
            calls[uid] = (index, block)
    for index in range(max(base, frozen_attr), len(messages)):
        raw = messages[index]
        if raw.get('role') != 'user' or not isinstance(raw.get('content'), list):
            continue
        projected = emitted[index-base+1]
        if not isinstance(projected.get('content'), list) or len(projected['content']) != len(raw['content']):
            continue
        replacements = []
        for position, block in enumerate(raw['content']):
            if not isinstance(block, dict) or block.get('type') != 'tool_result' or block.get('is_error') is not False:
                continue
            uid = block.get('tool_use_id')
            if not isinstance(uid, str) or not uid:
                continue
            call = calls.get(uid)
            if uid in ambiguous or call is None or not (base <= call[0] < index):
                continue
            use = call[1]
            args = use.get('input')
            if use.get('name') != 'Read' or not isinstance(args, dict) or not isinstance(args.get('file_path'), str):
                continue
            source = normalized(args['file_path'], cwd)
            from memory.wsc_continuation import prior_generation

            if source != known and (source is None or not prior_generation(known, source)):
                continue
            content = block.get('content')
            if not isinstance(content, str) or len(content) > MAX_RECOVERY_CHARS:
                continue
            if isinstance(projected['content'][position], dict) and projected['content'][position].get('content') != content:
                replacements.append((position, block))
        if replacements:
            changed = dict(projected)
            changed['content'] = list(projected['content'])
            for position, block in replacements:
                changed['content'][position] = block
            emitted[index-base+1] = changed
    return emitted
