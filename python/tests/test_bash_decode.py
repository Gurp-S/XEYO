"""BashTool.runner 输出解码：UTF-8 优先、GBK/OEM 回退（根治 cmd dir 中文乱码）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bash_tool.runner import _decode


def test_decode_ascii() -> None:
	assert _decode(b"hello\nworld") == "hello\nworld"


def test_decode_utf8_chinese() -> None:
	assert _decode("设计文档".encode("utf-8")) == "设计文档"


def test_decode_gbk_chinese_fallback() -> None:
	# cmd dir 在中文 Windows 输出 GBK；非 UTF-8 → 回退 GBK，不产生乱码
	assert _decode("设计文档".encode("gbk")) == "设计文档"


def test_decode_cp1252_fallback() -> None:
	# 拉丁系统 OEM（cp1252）字节 → 回退可解；不抛异常
	assert "caf" in _decode("café".encode("cp1252"))


def test_decode_empty_and_binary() -> None:
	assert _decode(b"") == ""
	# 无法识别编码的字节：不抛异常，按 replace 给出可读字符串
	assert isinstance(_decode(b"\xff\xfe\x00\x81"), str)
