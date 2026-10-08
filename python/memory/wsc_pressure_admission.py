"""Ordinary WSC pressure admission measured on the current keep emission."""
from __future__ import annotations

import json
from memory.token import token_len


def keep_emission(messages, working, *, summary_provider=None, cwd=None):
    if int(getattr(working, "compact_cursor", 0) or 0) > 0:
        from memory.runtime import apply_c2_messages
        return apply_c2_messages(messages, working, summary_provider=summary_provider, cwd=cwd)
    from engine.compact import project
    from synaptic.task_checkpoint import restore_receipts
    frozen = int(getattr(working, "c1_frozen_until", 0) or 0)
    result = project(messages, frozen_until=frozen, cwd=cwd)
    from memory.wsc_execution_boundary import unfolded
    return unfolded(restore_receipts([{}] + result, messages, 0, frozen)[1:], messages, working)


def assess(emitted, working, *, context_limit, system_prompt, params):
    """Never count archived messages as current window occupancy.

    The byte estimate is calibrated by the last matching emission manifest;
    absent measurement uses the declared system and output reserve. It is an
    estimate, not a provider tokenizer receipt. Unknown capacity is explicit.
    """
    payload = json.dumps(emitted, ensure_ascii=False, separators=(",", ":"))
    projected = token_len(payload)
    overhead = token_len(system_prompt or "") + max(0, int(getattr(params, "reserve_tokens", 0) or 0))
    manifest = getattr(working, "last_projection_manifest", None) or {}
    cursor = int(getattr(working, "compact_cursor", 0) or 0)
    if (manifest.get("compact_cursor") == cursor
            and manifest.get("context_receipt_cursor") == cursor
            and manifest.get("context_receipt_basis") == "provider_current_request"):
        old_estimate = int(manifest.get("estimated_tokens", 0) or 0)
        old_actual = int(getattr(working, "last_prompt_tokens", 0) or 0)
        if old_estimate > 0 and old_actual > 0:
            overhead = max(overhead, old_actual - old_estimate)
    forecast = projected + overhead
    from memory.wsc_watermark import soft_watermark_tokens
    from memory.runtime import should_force_compact_on_pressure
    watermark = soft_watermark_tokens()
    pressure = should_force_compact_on_pressure(prompt_tokens=forecast,
        context_limit=context_limit, working=working, params=params)
    admitted = pressure or (watermark > 0 and forecast >= watermark)
    return {"admitted": admitted, "reason": "current_projection_pressure" if admitted else "current_projection_below_pressure",
            "projected_tokens": projected, "overhead_tokens": overhead,
            "forecast_tokens": forecast, "context_limit": int(context_limit or 0),
            "capacity_known": bool(context_limit and int(context_limit) > 0),
            "basis": "keep_emission_utf8_quarters_with_matching_receipt_overhead"}
