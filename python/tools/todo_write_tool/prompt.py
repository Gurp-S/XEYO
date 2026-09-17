from tools.todo_write_tool.constants import TODO_WRITE_TOOL_NAME

DESCRIPTION = (
	f"Session todo list for multi-step work. Exactly one item may be in_progress. "
	f"Each item: id (stable; auto-filled if omitted), content (task text), "
	f"activeForm (continuous), status pending|in_progress|completed. "
	f"merge=true updates by id (keeps unmatched old items); omit/false = full replace. "
	f"The UI reflects {TODO_WRITE_TOOL_NAME} writes."
)
