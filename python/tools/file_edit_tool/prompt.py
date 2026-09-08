from tools.file_read_tool.prompt import FILE_READ_TOOL_NAME

FILE_EDIT_TOOL_NAME = "Edit"

DESCRIPTION = f"""Exact string replace in a file. Must {FILE_READ_TOOL_NAME} first.
Match old_string exactly as in the file (never include Read's line-number prefix).
If not unique, add context or set replace_all=true. Prefer Edit over creating new files."""
