"""Drop lines that carry no decision-relevant information.

Patterns are fixed and testable: ANSI escapes, carriage-return progress lines,
pytest progress dots, and runs of blank lines. Nothing is inferred.
"""
import re

from .registry import Action, already_denoised, is_control, pointer_for, replace, row_size

ID = "strip_noise_lines"
REVERSIBLE = "exact"

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
DOTS = re.compile(r"^[.sFE]{8,}$")
BLANKS = re.compile(r"\n{3,}")


def clean(text: str) -> str:
    out = []
    for line in text.split("\n"):
        if "\r" in line:
            line = line.split("\r")[-1]
        line = ANSI.sub("", line)
        if DOTS.match(line.strip()):
            continue
        out.append(line)
    return BLANKS.sub("\n\n", "\n".join(out))


def apply(rows):
    result, actions = [], []
    for row in rows:
        text = row.get("text")
        if is_control(row) or already_denoised(row) or not isinstance(text, str):
            result.append(row)
            continue
        cleaned = clean(text)
        if cleaned == text:
            result.append(row)
            continue
        removed = text.count("\n") - cleaned.count("\n")
        if removed:
            cleaned = f"{cleaned}\n[denoise: strip_noise_lines removed {removed} lines]"
        before = row_size(row)
        updated = replace(row, text=cleaned)
        actions.append(Action(ID, row["id"], before, row_size(updated), pointer_for(row, ID)))
        result.append(updated)
    return result, actions
