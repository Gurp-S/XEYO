"""Bounded output reservation from the already committed task declaration.

UTF-8 bytes provide a conservative payload allowance, not a tokenizer count.
Unknown new facts can still exhaust this bound; truncated output never commits.
"""
import json

MIN_TOKENS = 2048
MAX_TOKENS = 8192
FRAMING_TOKENS = 1024


def reservation(sources):
    from synaptic.todo_snapshot import latest_todo_snapshot
    state = latest_todo_snapshot(sources)
    if not state.observed:
        return MIN_TOKENS
    payload = {'todos': list(state.records), 'checkpoint': state.checkpoint}
    size = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    rounded = ((size + FRAMING_TOKENS + 1023) // 1024) * 1024
    return min(MAX_TOKENS, max(MIN_TOKENS, rounded))
