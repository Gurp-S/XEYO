"""Neutralize host paths before error text leaves the core.

Error codes are already opaque, but ``WSCError`` accepts arbitrary messages and
durable notes are persisted verbatim. A path or a long command line inside one
of those strings would surface in ``status`` and on the CLI's stderr, so the two
exit points run text through :func:`redact` first.
"""
import re

_ROOT = '<workspace>'
_PATH = re.compile(r'(?:[A-Za-z]:\\|\\\\)[^\s"\'<>|]*|(?<!\w)/[^\s"\'<>|]*/[^\s"\'<>|]*')


def redact(value, *, roots=(), limit=240) -> str:
    """Replace host paths with placeholders and cap the remaining text."""
    text = value if isinstance(value, str) else repr(value)
    for root in roots:
        if root:
            text = text.replace(str(root), _ROOT)
    text = _PATH.sub('<path>', text)
    return text[:limit]
