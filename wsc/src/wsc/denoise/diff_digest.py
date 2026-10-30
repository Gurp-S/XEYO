"""Reduce a unified diff to its shape: file headers, hunk headers, line counts."""
from .registry import Action, already_denoised, is_control, pointer_for, replace, row_size

ID = "diff_digest"
REVERSIBLE = "exact"

MIN_LINES = 12


def looks_like_diff(lines) -> bool:
    return sum(1 for line in lines if line.startswith(("diff --git ", "@@ ", "+++ ", "--- "))) >= 2


def digest(text: str) -> str:
    lines = text.split("\n")
    if len(lines) < MIN_LINES or not looks_like_diff(lines):
        return text
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    kept = [line for line in lines if line.startswith(("diff --git ", "@@ ", "+++ ", "--- ", "index "))]
    kept.append(f"[diff body omitted: +{added} -{removed} lines]")
    return "\n".join(kept)


def apply(rows):
    result, actions = [], []
    for row in rows:
        text = row.get("text")
        if is_control(row) or already_denoised(row) or not isinstance(text, str):
            result.append(row)
            continue
        reduced = digest(text)
        if reduced == text:
            result.append(row)
            continue
        before = row_size(row)
        updated = replace(row, text=reduced)
        actions.append(Action(ID, row["id"], before, row_size(updated), pointer_for(row, ID)))
        result.append(updated)
    return result, actions
