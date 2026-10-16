"""Task-scoped spending ledger, inherited by child tasks and follow-up cycles.

Admission uses settled usage. Already in-flight provider requests may exceed the
limit; unpriced usage remains explicitly unknown, never an invented zero price.
"""
from __future__ import annotations

import threading
from contextlib import aclosing
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps

from engine.flag_definitions import enabled


@dataclass
class SharedBudget:
    usd_limit: float | None
    token_limit: int | None
    used_usd: float = 0.0
    used_tokens: int = 0
    unpriced_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def settle(self, tokens: int, usd: float | None) -> None:
        with self._lock:
            self.used_tokens += max(0, tokens)
            if usd is None:
                self.unpriced_calls += 1
            else:
                self.used_usd += max(0.0, usd)

    def snapshot(self) -> dict:
        with self._lock:
            return {"used_usd": self.used_usd, "used_tokens": self.used_tokens,
                    "usd_limit": self.usd_limit, "token_limit": self.token_limit,
                    "unpriced_calls": self.unpriced_calls}

    def stop_reason(self) -> str:
        with self._lock:
            if self.usd_limit is not None and self.used_usd >= self.usd_limit:
                return "budget_usd"
            if self.token_limit is not None and self.used_tokens >= self.token_limit:
                return "budget"
        return ""


current_budget: ContextVar[SharedBudget | None] = ContextVar("shared_agent_budget", default=None)


def inherit_budget():
    return current_budget.get() if enabled("XEYO_SHARED_AGENT_BUDGET") else None


def task_budget_scope(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        budget = kwargs["budget"]
        if not enabled("XEYO_SHARED_AGENT_BUDGET"):
            async with aclosing(function(*args, **kwargs)) as events:
                async for event in events:
                    yield event
            return
        shared = current_budget.get() or budget.shared_budget
        if shared is None:
            shared = SharedBudget(budget.usd_limit, budget.max_tokens,
                                  budget.used_usd, budget.used_tokens, budget.usd_unpriced_turns)
        budget.shared_budget = shared
        token = current_budget.set(shared)
        try:
            async with aclosing(function(*args, **kwargs)) as events:
                async for event in events:
                    yield event
        finally:
            current_budget.reset(token)
    return wrapped


def stop_event(budget):
    from msgtypes.events import StoppedEvent
    return StoppedEvent(reason="budget_usd" if budget.over_budget else "budget",
                        budget_used_usd=budget.total_used_usd,
                        budget_limit_usd=budget.shared_budget.usd_limit if budget.shared_budget else budget.usd_limit)

