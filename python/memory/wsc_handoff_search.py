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
    return {"matches_total": total, "unreturned_match_count": total - count,
            "passages": [{"offset": start, "end_offset": end, "content": text[start:end]} for start, end in spans],
            "text_complete": spans == [[0, len(text)]]}
