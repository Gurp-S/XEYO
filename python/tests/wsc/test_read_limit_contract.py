"""WSC recovery declarations use the actual Read limits, not defaults as caps."""
import asyncio
from tools.file_read_tool.file_read_tool import FileReadTool
from tests.wsc.test_cold_read_view import _abort, _read, _strip_line_numbers


def test_explicit_line_limit_above_default_is_executable(tmp_path):
    view = tmp_path / 'cold.txt'
    text = '\n'.join(f'r{i}' for i in range(2100))
    view.write_text(text, encoding='utf-8')
    received = _strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view, offset=1, limit=2100))
    assert received == text


def test_single_line_above_token_limit_cannot_be_fixed_by_line_paging(tmp_path):
    view = tmp_path / 'cold.txt'
    view.write_text('x' * 100004, encoding='utf-8')
    returned = asyncio.run(FileReadTool(cwd=str(tmp_path)).execute(
        {'file_path': str(view), 'offset': 1, 'limit': 1}, _abort()))
    assert returned.is_error
    assert 'exceeds maximum allowed tokens' in returned.content
