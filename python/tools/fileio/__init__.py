"""Read / Write / Edit 工具共享的文件系统辅助函数。"""

from tools.fileio.paths import (
	FILE_NOT_FOUND_CWD_NOTE,
	expand_path,
	find_similar_file,
	get_cwd,
	suggest_path_under_cwd,
	to_relative_path,
)
from tools.fileio.read_state import FileStateEntry, ReadFileState
from tools.fileio.text import (
	add_line_numbers,
	apply_edit_to_file,
	detect_line_endings,
	find_actual_string,
	get_mtime_ms,
	normalize_newlines,
	preserve_quote_style,
	read_text_file,
	write_text_file,
)

__all__ = [
	"FILE_NOT_FOUND_CWD_NOTE",
	"FileStateEntry",
	"ReadFileState",
	"add_line_numbers",
	"apply_edit_to_file",
	"detect_line_endings",
	"expand_path",
	"find_actual_string",
	"find_similar_file",
	"get_cwd",
	"get_mtime_ms",
	"normalize_newlines",
	"preserve_quote_style",
	"read_text_file",
	"suggest_path_under_cwd",
	"to_relative_path",
	"write_text_file",
]
