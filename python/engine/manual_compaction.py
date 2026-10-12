"""Manual compression using the same declaration transaction as the query loop.

The caller owns session exclusion. Ownership and pending-stop callbacks are
provided by pooled callers; the in-process CLI serializes its commands.
"""


async def compact(engine, *, cwd=None, guard=None, pending_stop=None):
    from uuid import uuid4
    from engine.abort import CancellationScope
    from engine.budget import DEFAULT_MAX_TURNS, DEFAULT_MAX_TOOL_CALLING, max_budget_usd_from_env
    from engine.execution_context import ExecutionContext
    from engine.workspace_context import bind_workspace_context
    from memory.runtime import force_compact
    from memory.wsc_pressure_admission import keep_emission
    from memory.working import collect_from_tools, flush
    from memory.wsc_handoff_prepare import prepare
    from memory.wsc_handoff_scope import needs_refresh
    from memory.wsc_handoff_transaction import persist_session
    from memory.wsc_source_transition import prepare_compression_source
    from session.compression_source import compression_messages
    from synaptic.todo_snapshot import latest_todo_snapshot

    session = engine._session
    snap, store, budget = session.working, session.messages, session.budget
    cfg = engine._config
    cwd = cwd or session.cwd or cfg["cwd"]
    # No await separates installation from consumption of a pooled pending stop.
    abort = CancellationScope(label="manual-compact")
    session.abort = engine._abort_controller = abort
    if pending_stop is not None and pending_stop():
        abort.abort()

    def check():
        if guard is not None:
            guard()
        abort.raise_if_aborted()

    def source():
        check()
        return compression_messages(store, snap)

    def persist():
        # Cancellation stops new execution, not publication of an already
        # returned tool fact. Ownership still fences all durable writes.
        if guard is not None:
            guard()
        persist_session(session)

    check()
    prepare_compression_source(store, snap, cwd=cwd, fold=False)
    raw = source()
    if len(raw) < 4:
        return {"ok": False, "reason": "too_short", "compact_cursor": snap.compact_cursor}
    before = int(snap.compact_cursor or 0)
    persist()  # Source durability precedes declaration and archive retirement.
    if needs_refresh(raw, latest_todo_snapshot(raw)):
        trace_id = "manual-compact-" + uuid4().hex
        usd_limit = cfg.get("max_budget_usd")
        if usd_limit is None:
            usd_limit = cfg.get("max_budget")
        if usd_limit is None:
            usd_limit = max_budget_usd_from_env()
        budget.reset_for_new_submit(max_turns=int(cfg.get("max_turns") or DEFAULT_MAX_TURNS),
            max_tool_calling=int(cfg.get("max_tool_calling") or DEFAULT_MAX_TOOL_CALLING),
            usd_limit=usd_limit, provider=engine._provider, model=engine._model_name)
        context = engine._runtime_context
        if context is None:
            context = ExecutionContext(session_id=session.session_id, cwd=cwd,
                permission_profile=engine._permission_profile, runtime="unknown", trace_id=trace_id)
        else:
            context = context.evolve(cwd=cwd, trace_id=trace_id, model_request_id="", projection_id="")
        with bind_workspace_context(context):
            system = await engine._prompt.build_system(cwd=cwd,
                model=cfg.get("user_specified_model") or "deepseek", tools=cfg["tools"],
                custom_system_prompt=cfg.get("custom_system_prompt"),
                append_system_prompt=cfg.get("append_system_prompt"), date_iso=engine._date_iso)
            check()
            # Rendering this dedicated request cannot authorize a fold, even
            # when the caller has disabled model timing or the WSC side path.
            rows = keep_emission(source(), snap, cwd=cwd)
            if not budget.prepare_next_turn():
                raise ValueError("handoff_model_budget_exhausted")
            budget.begin_turn()
            committed = await prepare(model=engine._model,
                messages=engine._prompt.build(system, rows), source=source, store=store,
                tools=engine._tools, abort=abort, budget=budget,
                account=budget.add_usage, persist=persist, guard=check,
                publish_guard=guard, session_id=session.session_id)
            snap.wsc_timing_state = {**snap.wsc_timing_state, "last_handoff_commit": committed}
    check()
    force_compact(source(), snap, cwd=cwd)
    collect_from_tools(snap, engine._tools)
    check()
    flush(session.session_id, snap)
    after = int(snap.compact_cursor or 0)
    return {"ok": True, "compact_cursor": after, "advanced": after > before,
        "c2_summary_chars": len(snap.c2_summary_text or ""),
        "c2_summary_preview": (snap.c2_summary_text or "")[:240],
        "last_action": snap.last_action, "budget": engine.budget_snapshot()}
