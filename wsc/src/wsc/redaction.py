"""Neutralize host paths before error text leaves the core.

Error codes are already opaque, but ``WSCError`` accepts arbitrary messages and
durable notes are persisted verbatim. A path or a long command line inside one
of those strings would surface in ``status`` and on the CLI's stderr, so the two
exit points run text through :func:`redact` first.

Redaction is deliberately narrow. URLs are never rewritten (``http://host/a/b``
is not a local path), and a bare relative reference such as ``docs/readme.md``
is kept unless the surrounding text marks it as an I/O target (``open``,
``read``, ``missing``...). Absolute, home, UNC, drive and explicit ``./`` or
``../`` paths are always rewritten, because those cannot be anything but host
locations.
"""
import re

_ROOT = '<workspace>'
_URL = re.compile(r'\b[A-Za-z][A-Za-z0-9+.-]*://[^\s"\'<>|]+')
_PATH = re.compile(
    r'(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s"\'<>|]*'                  # drive, not a URL scheme
    r'|\\\\[^\s"\'<>|]*'                                           # UNC
    r'|~[\\/][^\s"\'<>|]*'                                         # home-relative
    r'|\.{1,2}[\\/][^\s"\'<>|]+'                                   # explicit relative
    r'|(?<![\w:/])/(?:[^\s"\'<>|]*/)+[^\s"\'<>|]*'                 # absolute POSIX, 2+ segments
)
_RELATIVE = re.compile(r'(?<![\w.\\/-])(?:[\w.-]+[\\/])+[\w-]+\.[A-Za-z0-9]{1,8}(?![A-Za-z0-9])')
# Rewrite a bare relative path only when the text says it is an I/O target.
_CUE = re.compile(r'\b(?:open(?:ed|ing)?|read|write|load|save|stat|access|missing|path|file|'
                  r'dir(?:ectory)?|cannot|failed|error|at)\b[^\n]{0,24}$', re.I)


def redact(value, *, roots=(), limit=240) -> str:
    """Replace host paths with placeholders and cap the remaining text."""
    text = value if isinstance(value, str) else repr(value)
    for root in roots:
        if root:
            text = text.replace(str(root), _ROOT)
    text = _PATH.sub('<path>', text)
    urls = [match.span() for match in _URL.finditer(text)]

    def replace(match):
        if any(match.start() < end and begin < match.end() for begin, end in urls):
            return match.group(0)
        if not _CUE.search(text[max(0, match.start() - 40):match.start()]):
            return match.group(0)
        return '<path>'

    return _RELATIVE.sub(replace, text)[:limit]
