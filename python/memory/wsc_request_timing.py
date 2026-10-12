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


def assemble(projected, schemas, working, *, context_limit, build, render, model=None):
    """Assemble once, including a pending notice, without admitting a fold.

    The caller can use this exact request to decide whether a declaration is
    required, then pass it to prepare without rendering a second notice frame.
    """
    messages = build(projected)
    text, key, _ = notification(messages, schemas, working, context_limit=context_limit, model=model)
    if text:
        rendered = render(projected, text)
        if rendered != projected:
            return rendered, build(rendered), key
    return projected, messages, None


def prepare(projected, schemas, working, *, context_limit, build, render, compact, model=None,
            initial_assembly=None, model_requested=False):
    attempts = 0
    before = int(working.compact_cursor or 0)

    def assemble_current(rows):
        return assemble(rows, schemas, working, context_limit=context_limit,
                        build=build, render=render, model=model)

    rows, messages, key = initial_assembly if initial_assembly is not None else assemble_current(projected)
    initial = request_measure(messages, schemas, context_limit=context_limit, model=model)
    fold_requested = initial.action == "capacity" or model_requested
    if fold_requested:
        attempts = int(initial.action == "capacity")
        # Rebuild from the new projection, not from the already injected
        # capacity notice. Capacity/notice identity then use the new cursor.
        rows, messages, key = assemble_current(compact())
    final = request_measure(messages, schemas, context_limit=context_limit, model=model)
    return finish(rows, messages, key, schemas, working, model, initial, final,
                  before, attempts, fold_requested, model_requested)


async def assemble_counted(projected, schemas, working, *, context_limit, build, render, model):
    await model.prime(build(projected), schemas)
    assembled = assemble(projected, schemas, working, context_limit=context_limit,
                         build=build, render=render, model=model)
    await model.prime(assembled[1], schemas)
    return assembled


async def prepare_counted(projected, schemas, working, *, context_limit, build, render,
                          compact, model, initial_assembly=None, model_requested=False):
    before = int(working.compact_cursor or 0)
    async def current(rows):
        return await assemble_counted(rows, schemas, working, context_limit=context_limit,
                                      build=build, render=render, model=model)
    rows, messages, key = initial_assembly if initial_assembly is not None else await current(projected)
    initial = request_measure(messages, schemas, context_limit=context_limit, model=model)
    fold_requested = initial.action == "capacity" or model_requested
    attempts = int(initial.action == "capacity")
    if fold_requested:
        rows, messages, key = await current(compact())
    final = request_measure(messages, schemas, context_limit=context_limit, model=model)
    return finish(rows, messages, key, schemas, working, model, initial, final,
                  before, attempts, fold_requested, model_requested)


def finish(rows, messages, key, schemas, working, model, initial, final,
           before, attempts, fold_requested, model_requested):
    output_measure = getattr(model, 'context_output_limit', None)
    output_limit = output_measure(messages, schemas) if callable(output_measure) else None
    output_known = isinstance(output_limit, int) and not isinstance(output_limit, bool) and output_limit > 0
    output_reserve = output_limit if output_known else 0
    facts = {"before": initial.facts(), "after": final.facts(),
             "output_reserve_tokens": output_reserve if output_known else None,
             "output_reserve_basis": "provider_request_output_limit" if output_known else "unknown",
             "automatic_attempts": attempts,
             "model_requested": bool(model_requested),
             "fold_attempts": int(bool(fold_requested)),
             "cursor_advanced": int(working.compact_cursor or 0) > before,
             "outcome": "compacted" if int(working.compact_cursor or 0) > before else "no_eligible_history" if fold_requested else "keep"}
    working.wsc_timing_state = {**working.wsc_timing_state, "last_request_admission": facts}
    if final.capacity > 0 and final.input_tokens >= final.capacity:
        facts["outcome"] = "capacity_exceeded"
        raise ValueError(f"context_capacity_exceeded: estimated_input={final.input_tokens} capacity={final.capacity}")
    if final.capacity > 0 and output_known and final.input_tokens + output_reserve > final.capacity:
        facts['outcome'] = 'capacity_exceeded'
        raise ValueError(f"context_capacity_exceeded: estimated_input={final.input_tokens} output_reserve={output_reserve} capacity={final.capacity}")
    return Prepared(rows, messages, key, facts)
