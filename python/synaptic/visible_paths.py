"""Conservative removal of exact path literals already visible in conclusions."""
import re
from collections.abc import Iterable


def missing_paths(paths: Iterable[str], text: str) -> tuple[str, ...]:
    # A substring of another filename, absolute path, or stream is not evidence.
    boundary = r"[\w./\\:\-+@$%=&!#~\[\]{},;]"
    return tuple(path for path in paths if not path or
                 re.search(r"(?<!" + boundary + r")" + re.escape(path) +
                           r"(?!" + boundary + r")", text) is None)


def uncovered_path_lines(items, visible_text: str):
    """Keep index entries unless their full keyed path is already visible."""
    return [item for item in items if not item[0].startswith("path:")
            or missing_paths((item[0][5:],), visible_text)]
