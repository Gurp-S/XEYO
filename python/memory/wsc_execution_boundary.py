"""Keep the last tool-response frame outside a newly built WSC head."""
from synaptic.textutil import tool_use_blocks, tool_result_blocks


def enabled():
    return True


def _side_path_enabled():
    from memory.wsc_main_policy import enabled
    return enabled()


def optional_boundary(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def protect(messages, requested):
    if not enabled():
        return requested
    calls = {}
    from session.recovery_result_chain import projected_supplements, supersessions
    projected = projected_supplements(messages)
    supplemental_ids = {key for key in supersessions(messages) if key[0] in projected} if projected else set()
    for index, message in enumerate(messages):
        for use in tool_use_blocks(message):
            uid = use.get("id")
            if isinstance(uid, (str, int)) and uid:
                calls.setdefault(uid, []).append(index)
    # A declaration generated in the isolated compaction call is not a task
    # model consumption receipt. Attribute it only to one matching invocation;
    # ambiguous identities retain the conservative existing boundary.
    isolated = set()
    for message in messages:
        for result in tool_result_blocks(message):
            execution = result.get("execution")
            if not isinstance(execution, dict):
                continue
            if not (execution.get("compaction_handoff") is True
                    or isinstance(execution.get("handoff_source_presentation"), dict)):
                continue
            uid = result.get("tool_use_id")
            origins = calls.get(uid, ()) if isinstance(uid, (str, int)) else ()
            if len(origins) == 1:
                isolated.add((origins[0], uid))

    def declaration_frame(index):
        uses = tool_use_blocks(messages[index])
        return bool(uses) and all(use.get("name") == "TodoWrite"
            and isinstance(use.get("id"), (str, int))
            and (index, use.get("id")) in isolated for use in uses)

    latest = next((index for index in range(len(messages) - 1, -1, -1)
                   if messages[index].get("role") == "assistant"
                   and not declaration_frame(index)), None)
    boundary = requested
    if latest is not None and tool_use_blocks(messages[latest]):
        boundary = min(boundary, latest)
    # Consumption is ordered by receipt arrival, not invocation age. A late
    # result can follow a newer assistant text/parallel invocation; that newer
    # turn could not have consumed the result before it existed.
    for index, message in enumerate(messages):
        if latest is not None and index <= latest:
            continue
        for result in tool_result_blocks(message):
            uid = result.get("tool_use_id")
            origins = () if (index, str(uid)) in supplemental_ids else (
                calls.get(uid, ()) if isinstance(uid, (str, int)) else ())
            # Ambiguous identity retains every possible earlier invocation.
            # Missing identity retains the receipt without inventing a call.
            boundary = min(boundary, index, *origins)
    return boundary


def restore_tail(emitted, messages, base=0, head_offset=0, *, from_index=None):
    if not enabled():
        return emitted
    boundary = protect(messages, len(messages)) if from_index is None else from_index
    if boundary == len(messages):
        return emitted
    result = list(emitted)
    for index in range(max(base, boundary), len(messages)):
        position = index - base + head_offset
        if position < len(result):
            result[position] = messages[index]
    from session.recovery_result_chain import projected_supplements, identity
    supplements = projected_supplements(messages)
    if supplements:
        counts = {}
        for message in messages:
            uid = identity(message)
            counts[uid] = counts.get(uid, 0) + 1
        replacements = {identity(messages[index]): row for index, row in supplements.items()
                        if identity(messages[index]) and counts[identity(messages[index])] == 1}
        result = [replacements.get(identity(row), row) for row in result]
    return result


def fold_cut(messages):
    """An explicit fold must not inherit an unbounded three-tool-round tail.

    Preserve the existing recent-message floor and whole unconsumed batch.
    Pair safety protects every consumed invocation/result crossing the cut.
    This chooses a boundary only; projection and task-state rendering do not
    change, and no idle request can invoke this function to initiate a fold.
    """
    from engine.compact import KEEP_TAIL_MESSAGES, keep_tail_cut
    from memory.runtime import pair_safe_cut
    recent = max(0, len(messages) - KEEP_TAIL_MESSAGES)
    return protect(messages, pair_safe_cut(messages, max(keep_tail_cut(messages), recent)))


def unfolded(projected, messages, working, *, fold=False):
    if not enabled():
        return projected
    boundary = optional_boundary(getattr(working, "c0_response_tail_from", None))
    if fold or boundary is None or boundary > len(messages):
        boundary = protect(messages, len(messages))
        working.c0_response_tail_from = boundary
    from synaptic.receipt_render import projection_enabled, render
    restored = restore_tail(projected, messages, from_index=boundary)
    return render(restored) if projection_enabled() else restored
