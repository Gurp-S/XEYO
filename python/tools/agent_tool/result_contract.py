"""Lossless child identity and result adaptation at the Agent tool boundary."""
from __future__ import annotations

import copy


def model_identity(client, *, provider="", model=""):
    return (
        str(getattr(client, "provider", "") or provider or ""),
        str(getattr(client, "_model", "") or getattr(client, "model", "") or model or ""),
    )


def child_client(client):
    # Provider clients store last_usage and request trace fields on themselves.
    # The transport may be shared, the per-call observation owner may not.
    return copy.copy(client)


def adapt_result(result, output_type):
    return output_type(
        conclusion=result.conclusion, files_touched=result.files_touched,
        memories=result.memories, is_error=result.is_error or getattr(result, "stop_reason", "") in {"budget", "budget_usd"},
        turns_used=int(getattr(result, "turns_used", 0) or 0),
        max_turns=int(getattr(result, "max_turns", 0) or 0),
        had_write_stale=bool(getattr(result, "had_write_stale", False)),
        tokens_used=int(getattr(result, "tokens_used", 0) or 0),
        cost_cny=getattr(result, "cost_cny", None),
        cost_partial=bool(getattr(result, "cost_partial", False)),
        stop_reason=str(getattr(result, "stop_reason", "") or ""),
    )
