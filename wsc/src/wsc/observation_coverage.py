"""Prove same-source public text is already present in a rendered checkpoint.

Only redundant inline text is omitted. Evidence keys, exact archived excerpts,
ranges, observation times and current-reference results remain unchanged.
"""
from copy import deepcopy
from hashlib import sha256
from .contracts import encode


def coverage(excerpt, source, rendered, locator):
    if not source or excerpt.get("basis") != "public_text" or excerpt.get("path") not in ([], ()):
        return None
    text, public = excerpt.get("text"), source.get("text")
    start, end = excerpt.get("start"), excerpt.get("end")
    if (not isinstance(text, str) or not isinstance(public, str) or type(start) is not int
            or type(end) is not int or not 0 <= start < end <= len(public)
            or public[start:end] != text or sha256(text.encode()).hexdigest() != excerpt.get("text_sha256")
            or excerpt.get("observed_at") != source.get("observed_at")
            or excerpt.get("call_id") != source.get("call_id")
            or locator.get("source_id") != source.get("id")
            or locator.get("basis") != "public_text" or locator.get("path") not in ([], ())
            or locator.get("start") != start or locator.get("end") != end
            or locator.get("sha256") != excerpt.get("text_sha256")
            or locator.get("observed_at") != excerpt.get("observed_at")):
        return None
    if source.get("kind") == "message":
        index = rendered["message_index"]
        item = rendered["items"][index]
        content = item.get("content", [])
        # Multi-part messages can introduce boundaries; no equivalence is assumed.
        if (item != source["payload"] or len(content) != 1 or not isinstance(content[0], dict)
                or content[0].get("type") not in {"input_text", "output_text"}
                or content[0].get("text") != public):
            return None
        return {"kind": "retained_message", "checkpoint_item_index": index}
    if source.get("kind") == "opaque":
        return None
    for index, item in enumerate(rendered["historical_excerpts"]):
        if (item["source_id"] == source["id"] and item["text"] == public
                and item["observed_at"] == source.get("observed_at")):
            return {"kind": "historical_excerpts", "index": index}
    return None


def covered_facts(body, items, facts):
    """Return a copy; unchanged text is the fallback whenever proof is absent."""
    result = deepcopy(facts)
    sources, message_indices = {}, {}
    count = 0
    for source in (body or {}).get("sources", []):
        sources[source["id"]] = source
        if source["kind"] == "message":
            message_indices[source["id"]] = count
            count += 1
    excerpts = {e["key"]: e for e in (body or {}).get("excerpts", [])}
    for observation in result.get("observations", []):
        excerpt = excerpts[observation["key"]]
        source = sources.get(excerpt["source_id"])
        proof = coverage(excerpt, source, {"items": items,
            "message_index": message_indices.get(excerpt["source_id"]),
            "historical_excerpts": result["historical_excerpts"]}, observation["source"])
        if proof is not None and observation["text"] == excerpt["text"]:
            candidate = {k: v for k, v in observation.items() if k != "text"}
            candidate["inline_coverage"] = proof
            if len(encode(candidate).encode("utf-8")) < len(encode(observation).encode("utf-8")):
                observation.clear()
                observation.update(candidate)
    return result
