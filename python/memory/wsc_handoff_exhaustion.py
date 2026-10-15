"""A larger bounded declaration allowance for explicit provider exhaustion."""
import os

from memory.wsc_handoff_output_budget import MAX_TOKENS
from memory.wsc_handoff_output_retry import ENV
from model.output_exhaustion import OutputLimitError


def next_limit(error, reserved):
    if os.environ.get(ENV, '1').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None
    if not isinstance(error, OutputLimitError) or type(reserved) is not int or not 0 < reserved < MAX_TOKENS:
        return None
    return min(MAX_TOKENS, reserved * 2)
