"""Deterministic first readable page; full source extent remains a literal fact."""
from bisect import bisect_right
from pathlib import Path
from synaptic.read_budget import MAX_READ_CHARS, numbered_chars, numbered_page_end

# FileRead gates the unnumbered slice; WSC recovery also bounds numbered text.


def line_prefix(text):
    lengths = [0]
    for line in text.split('\n'):
        lengths.append(lengths[-1] + len(line) + 1)
    return tuple(lengths)


def first_page_end(start, end, lengths):
    if not lengths or not (1 <= start <= end < len(lengths)):
        return end
    if numbered_chars(start, start, lengths) > MAX_READ_CHARS:
        # A single numbered line cannot fit the recovery emission bound.
        return end
    cursor, first = start, None
    while cursor <= end:
        stop = min(end, bisect_right(lengths, lengths[cursor-1] + MAX_READ_CHARS + 1) - 1)
        if stop < cursor:
            # The line-addressed interface cannot recover an oversized atomic
            # line. Keep the original declaration, not a false paging guarantee.
            return end
        if first is None:
            first = stop
        cursor = stop + 1
    return numbered_page_end(start, first, lengths)


def prepare_view(cold, path, persist):
    text, ranges = cold.render_text_view()
    if persist:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    return ranges, line_prefix(text)


def declared_extents(renderer, text, extent_re):
    """Known full origin extents; distinct from the first Read's actual slice."""
    out = []
    for match in extent_re.finditer(text):
        first, last = int(match.group('first')), int(match.group('last'))
        offset, limit = int(match.group('offset')), int(match.group('limit'))
        full = (match.group('path'), first, last-first+1)
        if full in renderer._reverse_index() and offset == first and 0 < limit < last-first+1:
            out.append((full, (match.group('path'), offset, limit)))
    return tuple(out)
