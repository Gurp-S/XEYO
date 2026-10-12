"""Bounded changed-content facts retained through the model projection."""
import re

_DIFF = re.compile(r"^```diff\r?\n([\s\S]*?)^```[ \t]*", re.IGNORECASE | re.MULTILINE)
MAX_CHARS = 1800
MAX_LINES = 24


def compact(content):
    def replace(match):
        lines = match.group(1).splitlines()
        # Keep range and actual changed lines, rather than unchanged context.
        changed = []
        in_hunk = False
        for line in lines:
            if line.startswith("@@"):
                in_hunk = True
            if in_hunk and line.startswith(("@@", "+", "-")):
                changed.append(line)
        shown = []
        length = 0
        for line in changed:
            if len(shown) >= MAX_LINES or length + len(line) + 1 > MAX_CHARS:
                break
            shown.append(line)
            length += len(line) + 1
        complete = len(shown) == len(changed) and not any("omitted]" in line for line in lines)
        return ("\n<mutation_diff>\n" + "\n".join(shown) +
                f"\ncomplete={str(complete).lower()}; shown_lines={len(shown)}; "
                f"available_lines={len(changed)}; source=original_tool_result\n</mutation_diff>")
    return _DIFF.sub(replace, content)
