"""文件工具共享的路径辅助函数（对齐 Glob/Grep / Claude expandPath）。"""

from __future__ import annotations

import os
from typing import Optional

FILE_NOT_FOUND_CWD_NOTE = "Current working directory:"


def get_cwd() -> str:
	from engine.workspace_context import get_cwd as ws_get_cwd

	return ws_get_cwd()


def expand_path(path: str, *, cwd: str | None = None) -> str:
	"""展开 ~ / 相对路径为绝对路径，并规范化分隔符。"""
	base = cwd or get_cwd()
	p = os.path.expanduser(str(path).strip())
	if not os.path.isabs(p):
		p = os.path.join(base, p)
	return os.path.abspath(p)


def to_relative_path(path: str, base: Optional[str] = None) -> str:
	if base is None:
		base = get_cwd()
	try:
		return os.path.relpath(path, base)
	except ValueError:
		return path


def suggest_path_under_cwd(target_path: str, *, cwd: str | None = None) -> Optional[str]:
	cwd = cwd or get_cwd()
	cwd_parent = os.path.dirname(os.path.realpath(cwd))
	try:
		rp = os.path.realpath(target_path)
	except OSError:
		rp = os.path.abspath(target_path)
	sep = os.sep
	parent_prefix = sep if cwd_parent == sep else cwd_parent + sep
	if (not rp.startswith(parent_prefix)) or rp.startswith(cwd + sep) or rp == cwd:
		return None
	want_name = os.path.basename(rp).lower()
	try:
		for name in os.listdir(cwd):
			full = os.path.join(cwd, name)
			if name.lower() == want_name:
				return full
	except OSError:
		pass
	return None


def find_similar_file(file_path: str) -> Optional[str]:
	"""同目录下找同名不同扩展名的文件（ENOENT 提示）。"""
	directory = os.path.dirname(file_path) or "."
	stem = os.path.splitext(os.path.basename(file_path))[0].lower()
	if not stem:
		return None
	try:
		for name in os.listdir(directory):
			full = os.path.join(directory, name)
			if not os.path.isfile(full):
				continue
			if os.path.splitext(name)[0].lower() == stem and full != file_path:
				return full
	except OSError:
		pass
	return None
