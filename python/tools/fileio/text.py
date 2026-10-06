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


def _routed_container() -> str:
	"""活动容器路由；宿主路由返回空串（路由模块不可用也视为宿主）。"""
	try:
		from tools.container_fs import active_container

		return active_container()
	except Exception:  # noqa: BLE001
		return ""


def get_mtime_ms(path: str) -> int:
	"""floor(mtimeMs)。

	容器路由（2026-09-16）：取**容器内**的 mtime——引擎的新鲜度/冲突判定否则会
	拿宿主空目录的时间戳去比容器文件，永远判错。
	"""
	if _routed_container():
		from tools.container_fs import mtime_ms

		ms = mtime_ms(path)
		if ms is None:
			raise FileNotFoundError(path)
		return ms
	return math.floor(os.path.getmtime(path) * 1000)


def normalize_newlines(content: str) -> str:
	return content.replace("\r\n", "\n").replace("\r", "\n")


def detect_line_endings(raw: bytes | str) -> LineEnding:
	text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
	return "CRLF" if "\r\n" in text else "LF"


def _read_raw_bytes(path: str) -> bytes:
	"""按活动路由取原始字节（容器路由 → 容器内；否则宿主）。"""
	if _routed_container():
		from tools.container_fs import read_bytes

		data = read_bytes(path)
		if data is None:
			raise FileNotFoundError(path)
		return data
	with open(path, "rb") as f:
		return f.read()


class UndecodableFileError(ValueError):
	"""正文无法逐字节无损还原时的拒读。

	读侧一旦用 ``errors="replace"``，解不出的字节就变成 ``\\ufffd``，而 Edit 是整文件
	写回 ⇒ 模型改一行 ASCII 就把用户的中文正文重写掉，回执还报 success。拒读把"看不清"
	如实交回调用方，不伪装成"这个文件没有内容"。
	"""


#: 与 ``common/child_text._CODECS`` 同口径（utf-8 → gbk → cp1252）。这里比子进程输出
#: 多一道要求：解码结果必须能编码回**同一串字节**——"能解码"不等于"不丢数据"。
#: utf-16-le 走上面 BOM 分支；utf-16-be / UTF-32 / 其它码页一律拒读（写回补不回 BOM）。
_ROUNDTRIP_CODECS = ("utf-8", "gbk", "cp1252")


def _decode_roundtrip(data: bytes, path: str) -> tuple[str, str]:
	nul = data.find(b"\x00")
	if nul != -1:
		raise UndecodableFileError(
			f"cannot read {path}: NUL byte at offset {nul} (binary)"
		)
	for codec in _ROUNDTRIP_CODECS:
		try:
			text = data.decode(codec)
		except UnicodeDecodeError:
			continue
		if text.encode(codec) == data:
			return text, codec
	raise UndecodableFileError(
		f"cannot read {path}: none of {'/'.join(_ROUNDTRIP_CODECS)} round-trips the bytes"
	)


def read_text_file(path: str) -> tuple[str, LineEnding, str]:
	"""
	读取文本文件。
	返回 (normalized_LF_content, original_line_endings, encoding_name)。

	容器路由（2026-09-16）：工作面在容器里时读容器——本函数是 Read / Edit /
	Write / NotebookEdit 的**共用汇聚点**，在此接线四处同时生效。

	编码（2026-10-03）：只接受能逐字节还原的解码；解不出抛
	``UndecodableFileError``，由各工具转成 ``is_error`` 回执，绝不写替换符。
	"""
	data = _read_raw_bytes(path)
	if len(data) >= 2 and data[0] == 0xFF and data[1] == 0xFE:
		encoding = "utf-16-le"
		text = data.decode("utf-16-le")
		# BOM 不是内容：残留 \ufeff 会在 Edit old_string 匹配、哈希、
		# 每次写回时累积多一个 BOM。
		if text.startswith("\ufeff"):
			text = text[1:]
	else:
		text, encoding = _decode_roundtrip(data, path)
		if text.startswith("\ufeff"):
			text = text[1:]
			# BOM 是**文件的属性**，不是正文：报成 utf-8-sig，写回时由编码器补回来
			# ——与上面 utf-16-le 分支同一口径。此前这里只报 "utf-8"，而 Edit 是
			# 整文件写回 ⇒ 模型改一行 ASCII 就把用户文件的 BOM 剥掉；PowerShell 5.1
			# 与 Excel 在没有 BOM 时会按 ANSI 解读，中文列名直接看成乱码。
			encoding = "utf-8-sig"
	endings = detect_line_endings(text)
	return normalize_newlines(text), endings, encoding


def write_text_file(
	path: str,
	content: str,
	*,
	encoding: str = "utf-8",
	line_endings: LineEnding = "LF",
) -> None:
	"""写入文本；按 line_endings 还原换行。

	容器路由（2026-09-16）：字节落到**容器内**；容器分支失败抛错，绝不静默回落
	宿主（"报了成功、文件却去了另一个文件系统"是本轮在消灭的失败形态）。
	"""
	to_write = normalize_newlines(content)
	if line_endings == "CRLF":
		to_write = "\r\n".join(to_write.split("\n"))
	# utf-16-le 编码器不写 BOM：不带 BOM 的 UTF-16 文件下一次 Read 检测
	# 不到编码（首字节不是 FF FE），会按 utf-8 解码成乱码。原文件带 BOM
	# （Read 就是靠它识别的），写回时必须补上。
	if encoding == "utf-16-le":
		payload = b"\xff\xfe" + to_write.encode("utf-16-le")
	else:
		# 严格编码：正文里有该码页表示不了的字符（如往 GBK 文件里塞 emoji）时抛
		# UnicodeEncodeError，由工具转成 is_error 回执。此前这里是
		# ``errors="replace"`` ⇒ 静默把字符写成 ``?`` 并报成功。
		payload = to_write.encode(encoding)
	if _routed_container():
		from tools.container_fs import write_bytes

		if not write_bytes(path, payload):
			raise OSError(f"container write failed: {path}")
		return
	parent = os.path.dirname(path)
	if parent:
		os.makedirs(parent, exist_ok=True)
	# 字节先编好再开文件：`open(path, "w")` 会先截断目标，正文里若有该码页表示不了
	# 的字符，抛错时用户文件已被清成空文件。
	with open(path, "wb") as f:
		f.write(payload)


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
	# old_string 的行尾形态可能与磁盘正文不一致（file_content 是 read_text_file
	# 的 LF 归一契约；模型侧可能带 \r\n）⇒ 先按 LF 归一找一遍，回取文件里的真实
	# 片段。弯引号归一在同一条链上做（否则"CRLF + 弯引号"的输入仍报 not found）。
	lf_search = normalize_newlines(search_string)
	candidates = (
		(search_string, lf_search) if lf_search != search_string else (search_string,)
	)
	for cand in candidates:
		idx = file_content.find(cand)
		if idx != -1:
			return file_content[idx : idx + len(cand)]
	normalized_search = normalize_quotes(lf_search)
	normalized_file = normalize_quotes(file_content)
	idx = normalized_file.find(normalized_search)
	if idx != -1:
		return file_content[idx : idx + len(normalized_search)]
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
