"""Bound inline invocation payloads without truncating their stored originals."""
import json


def invocation(value, source, remaining, *, item_bytes=2048):
    size = len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))
    inline = size <= min(item_bytes, remaining)
    return {"input_source": source, "input_bytes": size, "input_inline": inline,
            **({"input": value} if inline else {})}, remaining - size if inline else remaining
