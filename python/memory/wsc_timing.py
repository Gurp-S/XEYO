"""Model-owned ordinary compaction; declared capacity owns the hard boundary.

No age, economics, absolute token watermark, or archived-history size admits
an automatic fold here. Measurements are current-request estimates, never
presented as provider receipts. Output reserve is not input occupancy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from memory.token import token_len


def enabled() -> bool:
    return True


@dataclass(frozen=True)
class Timing:
    input_tokens: int
    capacity: int
    basis: str
    action: str
    notify: bool

    def facts(self) -> dict:
        return {"input_tokens": self.input_tokens, "context_limit": self.capacity,
                "basis": self.basis, "timing_action": self.action,
                "capacity_known": self.capacity > 0, "notify": self.notify}


def decide(input_tokens: int, capacity: int | None, *, model_requested=False,
           basis="current_request", notified=False) -> Timing:
    tokens = max(0, int(input_tokens or 0))
    limit = max(0, int(capacity or 0))
    # Integer cross multiplication prevents floor rounding from admitting a
    # request below the actual threshold on small/non-round capacities.
    forced = limit > 0 and tokens * 100 >= limit * 85
    notify = limit > 0 and tokens * 100 >= limit * 80 and not notified
    action = "capacity" if forced else "model" if model_requested else "keep"
    return Timing(tokens, limit, basis, action, notify)


def measure(emitted, working, *, context_limit, system_prompt="", tool_tokens=0) -> Timing:
    projected = token_len(json.dumps(emitted, ensure_ascii=False, separators=(",", ":")))
    overhead = token_len(system_prompt or "") + max(0, int(tool_tokens or 0))
    manifest = getattr(working, "last_projection_manifest", None) or {}
    cursor = int(getattr(working, "compact_cursor", 0) or 0)
    if (manifest.get("compact_cursor") == cursor
            and manifest.get("context_receipt_cursor") == cursor
            and manifest.get("context_receipt_basis") == "provider_current_request"):
        estimate = int(manifest.get("estimated_tokens", 0) or 0)
        actual = int(getattr(working, "last_prompt_tokens", 0) or 0)
        if estimate > 0 and actual > 0:
            overhead = max(overhead, actual - estimate)
    return decide(projected + overhead, context_limit,
                  basis="current_emission_estimate_with_matching_receipt_overhead")


def accepted_request(messages, working):
    """Only a paired successful execution receipt can request a fold.

    Neither historic prose, a tool name in a quotation, nor an unreturned
    invocation can do so. The consumed id is durable in the working sidecar.
    """
    state = getattr(working, "wsc_timing_state", {}) or {}
    handled = state.get("handled_request")
    calls = set()
    request = None
    for row in messages[max(0, int(getattr(working, "compact_cursor", 0) or 0)):]:
        content = row.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if row.get("role") == "assistant" and block.get("type") == "tool_use" and block.get("name") == "Compact":
                calls.add(block.get("id"))
            if block.get("type") != "tool_result" or block.get("is_error"):
                continue
            identity = block.get("tool_use_id")
            execution = block.get("execution") or {}
            if not isinstance(execution, dict):
                continue
            accepted = execution.get("compaction_request") or {}
            if (identity and identity in calls
                    and execution.get("status") == "ok"
                    and accepted == {"version": 1, "accepted": True}):
                request = identity
    return request if request != handled else None


def request_measure(api_messages, schemas, *, context_limit, model=None):
    source = {"messages": api_messages, "tools": schemas}
    basis = "complete_request_utf8_quarters_estimate"
    normalize = getattr(model, "context_input", None)
    if callable(normalize):
        source = normalize(api_messages, schemas)
        basis = "provider_normalized_input_utf8_quarters_estimate"
    tokens = token_len(json.dumps(source, ensure_ascii=False, separators=(",", ":")))
    return decide(tokens, context_limit, basis=basis)


def notification(api_messages, schemas, working, *, context_limit, model=None):
    """Final input estimate includes system/T_now/schema; no output reserve.

    Returns a delivery key without committing it. A failed provider request
    must not consume a notification. The sender commits only after success.
    """
    result = request_measure(api_messages, schemas, context_limit=context_limit, model=model)
    key = [int(getattr(working, "compact_cursor", 0) or 0), result.capacity]
    state = getattr(working, "wsc_timing_state", {}) or {}
    if result.notify and state.get("notification_delivered") != key:
        return "上下文已达80%（当前完整请求估算）", key, result
    return "", None, result


def delivered(working, key):
    if key is not None:
        working.wsc_timing_state = {**working.wsc_timing_state, "notification_delivered": key}
