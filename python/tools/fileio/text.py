"""文本读写与 Edit 字符串匹配。"""

from __future__ import annotations

import math
import os
from typing import Literal

LineEnding = Literal["LF", "CRLF"]

LEFT_SINGLE_CURLY = "\u2018"
RIGHT_SINGLE_CURLY = "\u2019"
LEFT_DOUBLE_CURLY = "\u201c"
RIGHT_DOUBLE_CURLY = "\u201d"


def get_mtime_ms(path: str) -> int:
	"""floor(mtimeMs)。"""
	return math.floor(os.path.getmtime(path) * 1000)


def normalize_newlines(content: str) -> str:
	return content.replace("\r\n", "\n").replace("\r", "\n")


def detect_line_endings(raw: bytes | str) -> LineEnding:
	text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
	return "CRLF" if "\r\n" in text else "LF"


def read_text_file(path: str) -> tuple[str, LineEnding, str]:
	"""
	读取文本文件。
	返回 (normalized_LF_content, original_line_endings, encoding_name)。
	"""
	with open(path, "rb") as f:
		data = f.read()
	encoding = "utf-8"
	if len(data) >= 2 and data[0] == 0xFF and data[1] == 0xFE:
		encoding = "utf-16-le"
		text = data.decode("utf-16-le")
		# BOM 不是内容：残留 \ufeff 会在 Edit old_string 匹配、哈希、
		# 每次写回时累积多一个 BOM。
		if text.startswith("\ufeff"):
			text = text[1:]
	else:
		text = data.decode("utf-8", errors="replace")
		if text.startswith("\ufeff"):
			text = text[1:]
	endings = detect_line_endings(text)
	return normalize_newlines(text), endings, encoding


def write_text_file(
	path: str,
	content: str,
	*,
	encoding: str = "utf-8",
	line_endings: LineEnding = "LF",
) -> None:
	"""写入文本；按 line_endings 还原换行。"""
	to_write = normalize_newlines(content)
	if line_endings == "CRLF":
		to_write = "\r\n".join(to_write.split("\n"))
	parent = os.path.dirname(path)
	if parent:
		os.makedirs(parent, exist_ok=True)
	# utf-16-le 编码器不写 BOM：不带 BOM 的 UTF-16 文件下一次 Read 检测
	# 不到编码（首字节不是 FF FE），会按 utf-8 解码成乱码。原文件带 BOM
	# （Read 就是靠它识别的），写回时必须补上。
	if encoding == "utf-16-le":
		with open(path, "wb") as f:
			f.write(b"\xff\xfe" + to_write.encode("utf-16-le"))
		return
	with open(path, "w", encoding=encoding, newline="") as f:
		f.write(to_write)


def add_line_numbers(content: str, *, start_line: int = 1) -> str:
	"""cat -n 风格：spaces + line number + arrow。"""
	if not content:
		return ""
	lines = content.split("\n")
	out: list[str] = []
	for i, line in enumerate(lines):
		num = str(i + start_line)
		if len(num) >= 6:
			out.append(f"{num}\u2192{line}")
		else:
			out.append(f"{num.rjust(6)}\u2192{line}")
	return "\n".join(out)


def normalize_quotes(s: str) -> str:
	return (
		s.replace(LEFT_SINGLE_CURLY, "'")
		.replace(RIGHT_SINGLE_CURLY, "'")
		.replace(LEFT_DOUBLE_CURLY, '"')
		.replace(RIGHT_DOUBLE_CURLY, '"')
	)


def find_actual_string(file_content: str, search_string: str) -> str | None:
	if search_string in file_content:
		return search_string
	normalized_search = normalize_quotes(search_string)
	normalized_file = normalize_quotes(file_content)
	idx = normalized_file.find(normalized_search)
	if idx != -1:
		return file_content[idx : idx + len(search_string)]
	return None


def _is_opening_context(chars: list[str], index: int) -> bool:
	if index == 0:
		return True
	prev = chars[index - 1]
	return prev in (" ", "\t", "\n", "\r", "(", "[", "{", "\u2014", "\u2013")


def _apply_curly_double(s: str) -> str:
	chars = list(s)
	result: list[str] = []
	for i, ch in enumerate(chars):
		if ch == '"':
			result.append(
				LEFT_DOUBLE_CURLY if _is_opening_context(chars, i) else RIGHT_DOUBLE_CURLY
			)
		else:
			result.append(ch)
	return "".join(result)


def _apply_curly_single(s: str) -> str:
	chars = list(s)
	result: list[str] = []
	for i, ch in enumerate(chars):
		if ch == "'":
			prev = chars[i - 1] if i > 0 else None
			nxt = chars[i + 1] if i < len(chars) - 1 else None
			if prev and nxt and prev.isalpha() and nxt.isalpha():
				result.append(RIGHT_SINGLE_CURLY)
			else:
				result.append(
					LEFT_SINGLE_CURLY
					if _is_opening_context(chars, i)
					else RIGHT_SINGLE_CURLY
				)
		else:
			result.append(ch)
	return "".join(result)


def preserve_quote_style(
	old_string: str, actual_old_string: str, new_string: str
) -> str:
	if old_string == actual_old_string:
		return new_string
	has_double = (
		LEFT_DOUBLE_CURLY in actual_old_string or RIGHT_DOUBLE_CURLY in actual_old_string
	)
	has_single = (
		LEFT_SINGLE_CURLY in actual_old_string or RIGHT_SINGLE_CURLY in actual_old_string
	)
	result = new_string
	if has_double:
		result = _apply_curly_double(result)
	if has_single:
		result = _apply_curly_single(result)
	return result


def apply_edit_to_file(
	original: str,
	old_string: str,
	new_string: str,
	*,
	replace_all: bool = False,
) -> str:
	if old_string == "":
		return new_string

	def _once(content: str, search: str, replace: str) -> str:
		return content.replace(search, replace, 1)

	def _all(content: str, search: str, replace: str) -> str:
		return content.replace(search, replace)

	fn = _all if replace_all else _once
	if new_string != "":
		return fn(original, old_string, new_string)

	strip_nl = (not old_string.endswith("\n")) and (old_string + "\n") in original
	if strip_nl:
		return fn(original, old_string + "\n", new_string)
	return fn(original, old_string, new_string)
