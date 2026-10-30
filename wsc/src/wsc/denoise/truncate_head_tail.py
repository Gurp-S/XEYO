"""Keep the head and tail of a long text; the middle becomes a hash and a length."""
from hashlib import sha256

from .registry import Action, already_denoised, is_control, pointer_for, replace, row_size

ID = "truncate_head_tail"
REVERSIBLE = "exact"

MAX_CHARS = 4096
HEAD = 2048
TAIL = 1024


def apply(rows):
    result, actions = [], []
    for row in rows:
        text = row.get("text")
        if is_control(row) or not isinstance(text, str) or len(text) <= MAX_CHARS:
            result.append(row)
            continue
        middle = text[HEAD:len(text) - TAIL]
        marker = (f"\n[... {len(middle)} chars omitted, sha256={sha256(middle.encode()).hexdigest()} ...]\n")
        trimmed = text[:HEAD] + marker + text[-TAIL:]
        before = row_size(row)
        updated = replace(row, text=trimmed)
        actions.append(Action(ID, row["id"], before, row_size(updated), pointer_for(row, ID)))
        result.append(updated)
    return result, actions
