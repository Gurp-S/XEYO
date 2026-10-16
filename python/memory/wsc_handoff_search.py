"""Bounded exact passages around literal source matches, never semantic ranking."""
MAX_MATCHES = 4


def passages(text, query, limit):
    total = text.count(query)
    count = min(MAX_MATCHES, total, limit // len(query))
    if not count:
        return {"matches_total": total, "unreturned_match_count": total, "passages": [], "text_complete": False}
    width = limit // count
    spans, cursor = [], 0
    for _ in range(count):
        found = text.find(query, cursor)
        cursor = found + len(query)
        before = min(96, (width - len(query)) // 2)
        start = max(0, found - before)
        end = min(len(text), start + width)
        start = max(0, end - width)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    # Window centres are not the set of returned matches: neighbouring hits
    # may also be fully visible. Count against the same non-overlapping search
    # used by str.count, without changing passages or materialising every hit.
    covered, cursor = 0, 0
    while cursor < spans[-1][1]:
        found = text.find(query, cursor)
        if found < 0 or found + len(query) > spans[-1][1]:
            break
        if any(start <= found and found + len(query) <= end for start, end in spans):
            covered += 1
        cursor = found + len(query)
    return {"matches_total": total, "unreturned_match_count": total - covered,
            "passages": [{"offset": start, "end_offset": end, "content": text[start:end]} for start, end in spans],
            "text_complete": spans == [[0, len(text)]]}
