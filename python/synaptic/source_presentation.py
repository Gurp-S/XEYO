"""Validate observed source ranges independently of the engine or model."""
import hashlib
from synaptic.task_fact_sources import source_text


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def merge(ranges):
    result = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


class Coverage:
    def __init__(self, sources):
        identities = {}
        for row in sources:
            uid = row.get("message_id") or row.get("id")
            if uid:
                identities.setdefault(str(uid), []).append(row)
        self.texts = {uid: source_text(rows[0]) for uid, rows in identities.items()
                      if len(rows) == 1 and source_text(rows[0]) is not None}
        self.ranges = {}

    def full(self, uid):
        if uid in self.texts:
            self.ranges[uid] = [[0, len(self.texts[uid])]]

    def source_result(self, value):
        uid = value.get("message_id")
        text = self.texts.get(uid)
        if text is None:
            return
        passages = value.get("passages", []) if "query" in value else [value]
        for passage in passages:
            start, content = passage.get("offset"), passage.get("content")
            if type(start) is not int or not isinstance(content, str):
                continue
            end = start + len(content)
            if 0 <= start <= end <= len(text) and text[start:end] == content:
                self.ranges[uid] = merge(self.ranges.get(uid, []) + [[start, end]])

    def record(self, identities):
        result = []
        for uid in dict.fromkeys(identities):
            text = self.texts.get(uid)
            if text is None:
                continue
            ranges = merge(self.ranges.get(uid, []))
            result.append({"message_id": uid, "source_sha256": digest(text),
                           "total_characters": len(text), "presented_ranges": ranges,
                           "complete": ranges == [[0, len(text)]]})
        return {"version": 1, "scope": "isolated_handoff_request", "sources": result}


def validated(value, sources):
    """Reject malformed or stale engine metadata, without accepting completeness flags."""
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("sources"), list):
        raise ValueError("handoff_source_presentation_invalid")
    tracker = Coverage(sources)
    identities = []
    for row in value["sources"]:
        if not isinstance(row, dict):
            raise ValueError("handoff_source_presentation_invalid")
        uid = row.get("message_id")
        text = tracker.texts.get(uid) if isinstance(uid, str) else None
        ranges = row.get("presented_ranges")
        if (text is None or uid in identities or row.get("source_sha256") != digest(text)
                or row.get("total_characters") != len(text) or not isinstance(ranges, list)
                or len(ranges) > 64):
            raise ValueError("handoff_source_presentation_invalid")
        for span in ranges:
            if (not isinstance(span, list) or len(span) != 2 or any(type(x) is not int for x in span)
                    or not 0 <= span[0] <= span[1] <= len(text)):
                raise ValueError("handoff_source_presentation_invalid")
        tracker.ranges[uid] = merge(ranges)
        identities.append(uid)
    return tracker.record(identities)
