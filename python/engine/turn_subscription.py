"""Bind replay cursors to their execution; a session alone is not an identity."""
import json


def rejection(expected, turn):
    if not expected:
        return None
    if turn is None or turn.turn_id != expected:
        return 'turn_mismatch'
    if turn.status == 'recovery_required':
        return 'recovery_required'
    return None


def rejection_frame(reason):
    return ('data: '+json.dumps({'error': {'type': reason, 'message': reason}})+'\n\n').encode()
