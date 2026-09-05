from tools.todo_write_tool.constants import TODO_WRITE_TOOL_NAME

DESCRIPTION = (
	f"Session todo list. Use for multi-step work (3+ steps); "
	f"skip trivial single tasks. Exactly one item in_progress. "
	f"Each item: id (stable; auto-filled if omitted), content (imperative), "
	f"activeForm (continuous), status pending|in_progress|completed. "
	f"merge=true updates by id (keeps unmatched old items); omit/false = full replace. "
	f"Call {TODO_WRITE_TOOL_NAME} as soon as a step finishes so the UI updates."
)
