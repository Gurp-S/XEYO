from tools.file_read_tool.prompt import FILE_READ_TOOL_NAME

FILE_WRITE_TOOL_NAME = "Write"

DESCRIPTION = f"""Create or overwrite a file. Existing files require {FILE_READ_TOOL_NAME} first.
Prefer Edit for small changes; Write for new files or full rewrites."""
