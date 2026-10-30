"""Collapse runs of identical lines, which is what a repeating traceback looks like."""
from .registry import Action, already_denoised, is_control, pointer_for, replace, row_size

ID = "collapse_stack"
REVERSIBLE = "exact"

MIN_RUN = 3


def collapse(text: str) -> str:
    lines = text.split("\n")
    out, index = [], 0
    while index < len(lines):
        line = lines[index]
        run = 1
        while index + run < len(lines) and lines[index + run] == line:
            run += 1
        if run >= MIN_RUN and line.strip():
            out.append(f"{line}  [x{run}]")
        else:
            out.extend([line] * run)
        index += run
    return "\n".join(out)


def apply(rows):
    result, actions = [], []
    for row in rows:
        text = row.get("text")
        if is_control(row) or already_denoised(row) or not isinstance(text, str):
            result.append(row)
            continue
        collapsed = collapse(text)
        if collapsed == text:
            result.append(row)
            continue
        before = row_size(row)
        updated = replace(row, text=collapsed)
        actions.append(Action(ID, row["id"], before, row_size(updated), pointer_for(row, ID)))
        result.append(updated)
    return result, actions
