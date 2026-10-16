"""HTTP agent commands enter the same policy and budget boundary as tools."""
import copy
import uuid

from engine.workspace_context import ExecutionContext, bind_workspace_context
from engine.shared_budget import SharedBudget, current_budget
from msgtypes.message import ToolUse


async def retry(engine, session_id, request, abort):
    registry = engine._tools
    tool = registry.get("Agent")
    # Compatibility for adapters that expose tools as a mapping.
    if not hasattr(registry, "run"):
        from tools.tool_registry import ToolRegistry
        registry = ToolRegistry(cwd=tool._cwd)
        registry.register(tool)
    cfg = getattr(engine, "config", {}) or {}
    ctx = copy.deepcopy(getattr(engine, "_runtime_context", None))
    if ctx is None:
        runtime = cfg.get("runtime") or ("docker" if cfg.get("container_id") else "local")
        ctx = ExecutionContext(session_id, tool._cwd, allowed_paths=[tool._cwd],
            runtime=runtime, container_id=cfg.get("container_id") or "")
    ctx.session_id = session_id
    ctx.permission_profile = engine.permission_profile
    ctx.model_request_id = ctx.projection_id = ""
    budget = getattr(getattr(engine, "_session", None), "budget", None)
    shared = getattr(budget, "shared_budget", None)
    if shared is None:
        shared = SharedBudget(cfg.get("max_budget_usd", cfg.get("max_budget")), cfg.get("max_tokens"))
        if budget is not None:
            budget.shared_budget = shared
    token = current_budget.set(shared)
    try:
        with bind_workspace_context(ctx):
            # The retry button explicitly requests this spawn; DENY still wins.
            return await registry.run(ToolUse("http-retry-" + uuid.uuid4().hex, "Agent", request),
                                      abort, skip_ask=True)
    finally:
        current_budget.reset(token)
