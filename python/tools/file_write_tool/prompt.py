from tools.file_read_tool.prompt import FILE_READ_TOOL_NAME

FILE_WRITE_TOOL_NAME = "Write"

DESCRIPTION = f"""Creates or overwrites a file. Existing-file writes require a prior {FILE_READ_TOOL_NAME} result.
Write supports new files and full rewrites; Edit performs exact string replacements."""
