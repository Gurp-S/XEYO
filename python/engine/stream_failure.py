"""Settle observed usage and preserve interrupted output before a stream exits."""
from engine.terminal_settlement import settle_tool_exit
from msgtypes.events import UsageEvent
from msgtypes.message import assistant_text_message
from usage.money import round_money8
from usage.pricing import split_usage


def failed_attempt_usage(model, budget, working):
    usage = getattr(model, "last_usage", None)
    if not isinstance(usage, dict):
        return None
    budget.add_usage(usage)
    hit, miss, out = split_usage(usage)
    return UsageEvent(
        prompt_tokens=hit + miss, completion_tokens=out,
        cache_hit_tokens=hit, cache_miss_tokens=miss,
        tokens=budget.last_usage_tokens, used_tokens=budget.used_tokens,
        usd=round_money8(budget.last_usage_usd), used_usd=round(budget.used_usd, 8),
        cny=round_money8(budget.last_usage_cny), used_cny=round(budget.used_cny, 8),
        cost_source=budget.last_cost_source, usd_limit=budget.usd_limit,
        unpriced_turns=budget.usd_unpriced_turns, budget_gate_note=budget.usd_gate_note,
        context_tokens=getattr(model, "last_context_tokens", None) or hit + miss,
        context_limit=getattr(model, "context_limit", None), context_breakdown=None,
        compact_cursor=int(working.compact_cursor or 0),
        last_action=str(working.last_action or ""), c2_summary_chars=0,
    )


def persist_interrupted_anchor(store, narration_gate, tool_uses, reasoning="", reasoning_blocks=None):
    partial, _flush = narration_gate.finish(has_tools=bool(tool_uses))
    narration = narration_gate.drain_narration()
    partial = (partial or "").strip()
    if not partial and not tool_uses and not narration and not reasoning and not reasoning_blocks:
        return False
    store.append(assistant_text_message(
        partial, tool_uses or None, interrupted=True,
        narration=narration, reasoning=reasoning, reasoning_blocks=reasoning_blocks,
    ))
    return True


async def settle_failed_stream(store, narration_gate, tool_uses, early, results, *, reason, reasoning="", reasoning_blocks=None):
    interrupted = persist_interrupted_anchor(store, narration_gate, tool_uses, reasoning, reasoning_blocks)
    events = await settle_tool_exit(store, tool_uses, early, results, reason=reason)
    return interrupted, events
