"""单文件读命令的目标判定：cat / type / gc / Get-Content [-n] <唯一文件>。

从 ``tools/bash_tool/dup_redirect`` 提炼的公共判据——bash 路由（Bash→Read 重定向）、
读观测身份（``synaptic/filestate``）与卡面 target（``synaptic/prune``）必须同源：
两边各写一份"这条命令读的是哪个文件"就会漂移，而漂移的后果正是"标签与命令指向
两个不同文件"（现场：``Bash runtime.py 完成`` 的命令是 ``Get-Content l5_flag.py``）。

零依赖纯函数模块（common 层），tools 与 synaptic 都可 import。
判据原则（宁缺勿猜——无法精确判定一律 None）：
- 必须是无元字符的单命令：``| < > & ; ` ^ % $(`` 换行出现即 None；
- 目标命令只在读白名单内，且参数形状完全匹配；
- 文件路径参数不得含通配符（* ?），设备名（nul/con/...）不算文件。
"""

from __future__ import annotations

import re

#: 命令链/管道/重定向/换行等元字符：出现即视为复合命令，目标不可判。
METACHARS = re.compile(r"[|<>;&`^%]|\$\(|\n")

#: Windows 设备名（cat nul / type nul 常见于占位操作，非文件读）。
DEVICE_NAMES = re.compile(r"^(nul|null|con|prn|aux|lpt[1-9]|com[1-9])$", re.I)

#: 文件名/路径里的通配符——出现即放弃（shell 展开多文件，目标不唯一）。
WILDCARD = re.compile(r"[*?]")

#: 整文件读命令白名单。
READ_VERBS = ("cat", "type", "gc", "get-content")


def tokens(command: str) -> list[str]:
	"""按空白切词：保留引号内空格，不做 shell 转义解释（Windows 反斜杠路径安全）。"""
	out: list[str] = []
	cur: list[str] = []
	quote: str | None = None
	for ch in command:
		if quote:
			if ch == quote:
				quote = None
			else:
				cur.append(ch)
		elif ch in "\"'":
			quote = ch
		elif ch.isspace():
			if cur:
				out.append("".join(cur))
				cur = []
		else:
			cur.append(ch)
	if cur:
		out.append("".join(cur))
	return out


def read_positional(token_list: list[str], start: int) -> str | None:
	"""取唯一的位置参数（文件路径）；多参数/含通配符/设备名/未知标志 → None。"""
	path: str | None = None
	for tok in token_list[start:]:
		if tok in ("-n", "--number"):
			continue
		if tok.startswith("-"):
			return None
		if path is not None:
			return None
		if WILDCARD.search(tok) or DEVICE_NAMES.match(tok):
			return None
		path = tok
	return path


def single_file_target(command: str | None) -> str | None:
	"""整文件读命令的目标路径；无法唯一判定返回 None。"""
	if not isinstance(command, str) or not command.strip():
		return None
	if METACHARS.search(command):
		return None
	token_list = tokens(command.strip())
	if not token_list or token_list[0].lower() not in READ_VERBS:
		return None
	return read_positional(token_list, 1)
