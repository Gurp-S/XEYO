"""A recorded external observation is data, not a new assistant action.

Evaluation carrier only. Native model/tool frames use their own protocol.
Original source identity, speaker and content stay inside the literal capsule.
"""
import json


def carrier(row):
    if row['role'] == 'user':
        return {'role': 'user', 'content': row['content']}
    return {'role': 'user', 'content': json.dumps({'source_record': row},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'))}
