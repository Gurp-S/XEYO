"""Resolve explicit verification IDs for active and terminal declarations alike."""
import json

from synaptic.textutil import tool_use_blocks, tool_result_blocks


def collect(messages, call_ids, before, *, inline_bytes=16000):
    uses, results = {}, {}
    for index, message in enumerate(messages[:before]):
        for block in tool_use_blocks(message):
            uid = block.get("id")
            if isinstance(uid, (str, int)) and uid:
                uses.setdefault(uid, []).append((index, block))
        for block in tool_result_blocks(message):
            uid = block.get("tool_use_id")
            if isinstance(uid, (str, int)) and uid:
                results.setdefault(uid, []).append((index, block))
    observations, unknown, nodes = [], [], []
    remaining = inline_bytes
    for uid in call_ids:
        calls, receipts = uses.get(uid, []), results.get(uid, [])
        if len(calls) != 1 or len(receipts) != 1 or calls[0][0] >= receipts[0][0]:
            unknown.append({"call_id": uid, "reason": "missing_or_ambiguous"})
            continue
        index, receipt = receipts[0]
        payload = receipt.get("content")
        size = len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        inline = size <= min(2048, remaining)
        remaining -= size if inline else 0
        observations.append({"call_id": uid, "source": index, "tool": calls[0][1].get("name"),
            "input": calls[0][1].get("input"), "is_error": receipt.get("is_error"),
            "execution": receipt.get("execution"), "result_bytes": size, "result_inline": inline,
            **({"result": payload} if inline else {})})
        nodes.extend((calls[0][0], index))
    return observations, unknown, tuple(dict.fromkeys(nodes))
