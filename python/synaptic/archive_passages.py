"""Bounded exact search evidence inside authoritative cold-source ranges."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def matched_lines(content, path, cwd):
    """Only rg's anchored locations for the searched file, never body numbers."""
    path, cwd = Path(path).resolve(), Path(cwd).resolve()
    names = {str(path).replace("\\", "/")}
    if path.is_relative_to(cwd):
        names.add(path.relative_to(cwd).as_posix())
    result = []
    for line in str(content).splitlines():
        normalized = line.replace("\\", "/")
        for name in names:
            prefix = name + ":"
            if normalized.startswith(prefix):
                match = re.match(r"(\d+):", normalized[len(prefix):])
                if match:
                    result.append(int(match[1]))
                break
    return sorted(set(result))


def source_ranges(cold, rows=()):
    from synaptic.textutil import message_text
    text, ranges = cold.render_text_view()
    records = []
    for index, body in cold.texts.items():
        start, end = ranges[f"node://{index}"]
        normalized = body.replace("\r\n", "\n").replace("\r", "\n")
        record = {"source": f"node://{index}", "source_lines": [start, end],
                  "source_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
        if index < len(rows):
            row = rows[index]
            content = message_text(row)
            if content.replace("\r\n", "\n").replace("\r", "\n") == normalized:
                record.update(message_id=row.get("message_id") or row.get("id"), role=row.get("role"))
        records.append(record)
    return text, records


def passages(text, sources, matched_lines, *, byte_budget=24000, per_passage_bytes=1800):
    lines = text.split("\n")
    records, used, seen = [], 0, set()
    matches = sorted(set(matched_lines))
    for hit in matches:
        owner = next((source for source in sources if source["source_lines"][0] <= hit <= source["source_lines"][1]), None)
        if owner is None:
            continue  # Never infer ownership from a user-authored '#node' line.
        first, last = owner["source_lines"]
        headings, fence = [], None
        for position in range(first, last + 1):
            line = lines[position - 1]
            marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
            if marker:
                token = marker[1]
                if fence is None:
                    fence = (token[0], len(token))
                elif token[0] == fence[0] and len(token) >= fence[1]:
                    fence = None
                continue
            heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line) if fence is None else None
            if heading:
                headings.append((position, len(heading[1]), heading[2]))
        ancestors = []
        for position, depth, title in headings:
            if position > hit:
                break
            while ancestors and ancestors[-1][1] >= depth:
                ancestors.pop()
            ancestors.append((position, depth, title))
        section_start, depth = (ancestors[-1][0], ancestors[-1][1]) if ancestors else (first, 0)
        section_end = next((position - 1 for position, level, _ in headings if position > hit and level <= depth), last)
        start, end = section_start, section_end
        body = "\n".join(lines[start - 1:end])
        if len(body.encode("utf-8")) > per_passage_bytes:
            start = end = hit
            body = lines[hit - 1]
            if len(body.encode("utf-8")) > per_passage_bytes:
                continue  # A long line remains exactly recallable by its source range.
            for _ in range(24):
                grew = False
                for candidate in (start - 1, end + 1):
                    if not section_start <= candidate <= section_end:
                        continue
                    lo, hi = min(start, candidate), max(end, candidate)
                    value = "\n".join(lines[lo - 1:hi])
                    if len(value.encode("utf-8")) <= per_passage_bytes:
                        start, end, body, grew = lo, hi, value, True
                if not grew:
                    break
        identity = (owner["source"], start, end)
        if identity in seen:
            continue
        record = {**owner, "section_path": [{"line": position, "title": title} for position, _, title in ancestors],
                  "section_lines": [section_start, section_end], "returned_lines": [start, end],
                  "section_complete": start == section_start and end == section_end, "content": body}
        size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if used + size > byte_budget:
            break
        records.append(record)
        used += size
        seen.add(identity)
    return {"source_passages": records, "matched_lines": matches,
            "uncovered_match_lines": [hit for hit in matches if not any(record["returned_lines"][0] <= hit <= record["returned_lines"][1] for record in records)],
            "returned_bytes": used, "byte_budget": byte_budget}
