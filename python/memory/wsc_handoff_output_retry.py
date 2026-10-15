"""Bounded output-exhaustion recovery; no semantic repair or extra requests.

Default enabled after same-source recovery and normal-wire A/B evidence;
an explicit zero retains the previous fixed-reservation retry behavior.
"""
import os
from memory.wsc_handoff_output_budget import MAX_TOKENS

ENV = 'XEYO_WSC_HANDOFF_OUTPUT_RETRY'


def expanded(error, usage, reserved):
    if os.environ.get(ENV, '1').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None
    if error != 'handoff_invalid_json' or not isinstance(usage, dict):
        return None
    completion = usage.get('completion_tokens')
    if type(completion) is not int or completion < reserved or reserved >= MAX_TOKENS:
        return None
    return min(MAX_TOKENS, reserved * 2)
