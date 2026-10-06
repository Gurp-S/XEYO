"""Terminal event construction shared by ordinary and finalization turns."""
from engine.budget import BudgetTracker
from msgtypes.events import FinalEvent, StoppedEvent
from usage.money import round_money8


def completion_event(
    text: str,
    budget: BudgetTracker,
    *,
    hit: int,
    miss: int,
    out: int,
    forced_wrap_up: bool = False,
) -> FinalEvent | StoppedEvent:
    if forced_wrap_up:
        text = text.strip()
        if not text:
            return StoppedEvent(reason=budget.hard_stop_reason or "max_turns")
    return FinalEvent(
        text=text,
        prompt_tokens=hit + miss,
        completion_tokens=out,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        usd=round_money8(budget.last_usage_usd),
        used_usd=round(budget.used_usd, 8),
        usd_limit=budget.usd_limit,
    )
