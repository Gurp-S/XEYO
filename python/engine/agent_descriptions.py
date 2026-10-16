"""Compact capability facts for the managed agent surface."""
DESCRIPTIONS = {
    "Agent": "Starts a session agent. Writers default to retained worktrees; agent_apply publishes separately. Background defaults true; reuse preserves history/scope. agent_control manages attempts.",
    "agent_send": "Durable same-session message to an agent or parent. Runtime binds sender. Delivery occurs at model boundaries or after resume. message_id deduplicates; attempt_id fences the recipient.",
    "agent_control": "Lists, inspects, waits for, interrupts or resumes session agents by attempt_id. Only the parent starts/stops attempts; resume retains history and scope.",
    "agent_apply": "Publishes a completed agent worktree with exact attempt_id and current write permission. Destination versions must match; the Git index is preserved.",
}
