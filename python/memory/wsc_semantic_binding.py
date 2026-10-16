"""Mechanical candidate identity and factual presentation of bound control state."""
from pathlib import Path
import json


def capture(cwd, working):
    from memory.wsc_goal_source import snapshot
    from memory.wsc_handoff_transaction import fingerprint
    root = str(Path(cwd or '.').resolve())
    goal = snapshot(root, working.session_id)
    fact = None if goal is None else {key: goal.get(key) for key in ('goal_id', 'revision', 'status', 'text')}
    return {'cwd': root, 'session_id': working.session_id,
            'source_layout': working.compression_source_layout,
            'cursor': int(working.compact_cursor or 0),
            'head_fingerprint': fingerprint(working.c2_summary_text), 'goal': fact}


def verify(binding, cwd, working):
    if not isinstance(binding, dict) or binding != capture(cwd, working):
        raise ValueError('semantic_control_changed')


def goal_text(binding):
    goal = binding['goal']
    if goal is None:
        return ''
    fact = dict(goal)
    if fact['status'] in {'completed', 'abandoned'}:
        fact['text'] = ''
    return '[BOUND_GOAL_STATE]\n' + json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
