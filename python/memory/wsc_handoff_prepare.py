"""Shared handoff generation and commit admission, within the caller's budget.

The caller admits the first model request and supplies its actual request rows.
This operation admits subsequent requests, reads and the eventual task write.
It neither folds history nor creates a separate budget or model configuration.
"""


async def prepare(*, model, messages, source, store, tools, abort, budget, account, persist,
                  guard=None, publish_guard=None, session_id=""):
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit

    task_tool = tools.get("TodoWrite")
    if persist is None or task_tool is None:
        raise ValueError("handoff_commit_unavailable")

    def check_budget():
        if guard is not None:
            guard()
        if budget.over_budget:
            raise ValueError("budget_usd")
        if budget.over_token_budget():
            raise ValueError("budget")

    def admit_next():
        check_budget()
        if not budget.prepare_next_turn():
            raise ValueError("handoff_model_budget_exhausted")
        budget.begin_turn()

    def admit_tool():
        check_budget()
        if not budget.begin_tool_call():
            raise ValueError("handoff_tool_budget_exhausted")

    async def generate_state(captured):
        check_budget()
        return await generate(model, messages, captured, task_tool.schema(), abort,
                              account=account, admit_next=admit_next,
                              admit_read=admit_tool, scope_protocol=True)

    return await commit(source=source, generate=generate_state, store=store,
                        tools=tools, abort=abort, persist=persist,
                        require_phase=True, admit_write=admit_tool,
                        publish_guard=publish_guard, session_id=session_id)
