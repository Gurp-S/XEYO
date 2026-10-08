"""Final assembled request owns both capacity admission and notice delivery.

One automatic attempt per preparation. The trigger is not a target size:
fixed schemas/current task may alone exceed 85%, and a no-op must not spin
or pretend to have compacted. Storage/source mutation belongs to the caller.
"""
from dataclasses import dataclass

from memory.wsc_timing import notification, request_measure


@dataclass
class Prepared:
    projected: list
    messages: list
    delivery_key: list | None
    facts: dict


def prepare(projected, schemas, working, *, context_limit, build, render, compact, model=None):
    attempts = 0
    before = int(working.compact_cursor or 0)

    def assemble(rows):
        messages = build(rows)
        text, key, _ = notification(messages, schemas, working, context_limit=context_limit, model=model)
        if text:
            rendered = render(rows, text)
            if rendered != rows:
                return rendered, build(rendered), key
        return rows, messages, None

    rows, messages, key = assemble(projected)
    initial = request_measure(messages, schemas, context_limit=context_limit, model=model)
    if initial.action == "capacity":
        attempts = 1
        # Rebuild from the new projection, not from the already injected
        # capacity notice. Capacity/notice identity then use the new cursor.
        rows, messages, key = assemble(compact())
    final = request_measure(messages, schemas, context_limit=context_limit, model=model)
    facts = {"before": initial.facts(), "after": final.facts(),
             "automatic_attempts": attempts,
             "cursor_advanced": int(working.compact_cursor or 0) > before,
             "outcome": "compacted" if int(working.compact_cursor or 0) > before else "no_eligible_history" if attempts else "keep"}
    working.wsc_timing_state = {**working.wsc_timing_state, "last_request_admission": facts}
    return Prepared(rows, messages, key, facts)
