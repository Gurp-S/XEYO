from tools.file_read_tool.prompt import FILE_READ_TOOL_NAME

FILE_EDIT_TOOL_NAME = "Edit"

DESCRIPTION = f"""Replaces an exact string in a file. Existing-file edits require a prior {FILE_READ_TOOL_NAME} result.
old_string matches file text exactly and excludes Read's line-number prefix.
Non-unique matches require additional context or replace_all=true. Edit creates no new file."""
