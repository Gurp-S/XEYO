"""Bind an outcome-unknown observation and its unique later actual result."""
from collections import defaultdict
import hashlib
import json


def field(message, key, default=None):
    return message.get(key, default) if isinstance(message, dict) else getattr(message, key, default)


def identity(message):
    return field(message, "message_id") or field(message, "id", "")


def uses(message):
    content = field(message, "content")
    return [block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"] if field(message, "role") == "assistant" and isinstance(content, list) else []


def observation(origin, uid):
    matches = [block for block in uses(origin) if str(block.get("id", "")) == str(uid)]
    if len(matches) != 1 or not identity(origin):
        return None
    body = json.dumps(matches[0], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"kind": "outcome_unknown", "origin_message_id": identity(origin),
            "invocation_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def supersessions(messages):
    """Map (actual row, call id) to its uniquely bound recovery observation.

    No string matching, generic incomplete exception, or duplicate collapse.
    """
    calls, results = defaultdict(list), defaultdict(list)
    for index, message in enumerate(messages):
        for block in uses(message):
            if block.get("id"):
                calls[str(block["id"])].append((index, block))
        content = field(message, "content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                    results[str(block["tool_use_id"])].append((index, block))
    found = {}
    for uid, receipts in results.items():
        if len(receipts) != 2 or len(calls[uid]) != 1:
            continue
        call_index, _call = calls[uid][0]
        (prior_index, prior), (actual_index, actual) = receipts
        if not call_index < prior_index < actual_index:
            continue
        execution = prior.get("execution")
        if (not isinstance(execution, dict) or execution.get("complete") is not False
                or prior.get("is_error") is not True or not identity(messages[prior_index])):
            continue
        expected = observation(messages[call_index], uid)
        if expected is None or execution.get("recovery_observation") != expected:
            continue
        if isinstance(actual.get("execution"), dict) and "recovery_observation" in actual["execution"]:
            continue
        # The observation closes the original native batch; an intervening
        # ordinary event would already be a different sequence boundary.
        if any(field(message, "role") != "tool"
               for message in messages[call_index + 1:prior_index]):
            continue
        found[(actual_index, uid)] = prior_index
    return found


def projected_supplements(messages):
    """Read-only factual rows from the complete, validated archival source.

    This proves the link even when the original call is outside the hot tail.
    The same projection supplies pairing and emission; failure keeps the
    original conservative boundaries rather than inventing a cold binding.
    """
    from session.late_result_projection import enabled, project
    if not enabled():
        return {}
    links = supersessions(messages)
    if not links:
        return {}
    projected = project(messages)
    return {index: projected[index] for index, _uid in links
            if projected[index] != messages[index]}
