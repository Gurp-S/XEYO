"""#10 写去重 + #11 语法错误提示闭环 单元测试（FileWriteTool 直通路径）。

#10 判定：内容与磁盘一致 → 跳过落盘（unchanged=True、write_text_file 不再被调）。
#11 判定：新内容引入解析错误且旧内容无错 → syntax_hint 含行/列（旧也错 → 不唠叨）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.file_write_tool import file_write_tool as fwt_mod
from tools.file_write_tool.file_write_tool import FileWriteTool, WriteInput


def test_identical_write_is_skipped(tmp_path, monkeypatch):
	tool = FileWriteTool(cwd=str(tmp_path))
	path = str(tmp_path / "a.txt")

	calls = []
	orig = fwt_mod.write_text_file

	def counting_write(path_, content, **kw):
		calls.append((path_, content))
		return orig(path_, content, **kw)

	# 模块顶层 `from tools.fileio.text import write_text_file` 绑定在 fwt_mod 上，
	# 必须 patch fwt_mod.write_text_file 而不是 fileio.text 命名空间。
	monkeypatch.setattr(fwt_mod, "write_text_file", counting_write)

	first = tool.call(WriteInput(file_path=path, content="hello\nworld\n"))
	assert not first.unchanged and len(calls) == 1

	second = tool.call(WriteInput(file_path=path, content="hello\nworld\n"))
	assert second.unchanged is True, "#10 去重失效：相同内容未跳过写盘"
	assert len(calls) == 1, "去重后仍发生第二次落盘"
	assert "unchanged" in FileWriteTool.map_tool_result_to_content(second).lower()

	# 内容确实不同 → 照常写
	third = tool.call(WriteInput(file_path=path, content="changed\n"))
	assert third.unchanged is False and len(calls) == 2


def test_py_syntax_hint_on_new_error(tmp_path):
	tool = FileWriteTool(cwd=str(tmp_path))
	path = str(tmp_path / "m.py")
	ok = tool.call(WriteInput(file_path=path, content="def f():\n    return 1\n"))
	assert ok.syntax_hint == ""
	bad = tool.call(
		WriteInput(file_path=path, content="def f(:\n    return 1\n")
	)
	assert bad.syntax_hint, "#11 失效：新引入 Python 语法错误没有提示"
	assert "Python syntax error" in bad.syntax_hint
	assert "syntax_hint" in FileWriteTool.map_tool_result_to_content(bad)


def test_json_syntax_hint_with_line_column(tmp_path):
	tool = FileWriteTool(cwd=str(tmp_path))
	path = str(tmp_path / "c.json")
	tool.call(WriteInput(file_path=path, content='{"a": 1}\n'))
	bad = tool.call(WriteInput(file_path=path, content='{"a": 1,}\n'))
	assert bad.syntax_hint, "#11 失效：坏 JSON 无行列提示"
	assert "JSON parse error at line 1" in bad.syntax_hint


def test_no_hint_when_old_content_already_broken(tmp_path):
	"""旧内容本就语法错 → 增量原则：不唠叨（避免对烂文件每次写入刷屏）。"""
	tool = FileWriteTool(cwd=str(tmp_path))
	path = str(tmp_path / "e.json")
	tool.call(WriteInput(file_path=path, content='{"broken": }\n'))  # 先写坏
	again = tool.call(WriteInput(file_path=path, content='{"broken": ,}\n'))  # 仍坏
	assert again.syntax_hint == ""
