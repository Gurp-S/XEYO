"""文件工具共享的路径辅助函数。"""

from __future__ import annotations

import os
from typing import Optional

from tools.fileio import fsprobe as _fsprobe

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
	if _fsprobe.routed():
		return _suggest_path_in_container(target_path, cwd or get_cwd())
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


def _suggest_path_in_container(target_path: str, cwd: str) -> Optional[str]:
	"""同名路径提示的容器工作面实现。"""
	import posixpath

	from tools.container_fs import listdir, to_container_path

	container_cwd = posixpath.normpath(to_container_path(cwd))
	container_target = posixpath.normpath(to_container_path(target_path))
	parent = posixpath.dirname(posixpath.realpath(container_cwd))
	parent_prefix = "/" if parent == "/" else parent + "/"
	if (
		(not container_target.startswith(parent_prefix))
		or container_target == container_cwd
		or container_target.startswith(container_cwd + "/")
	):
		return None
	want_name = posixpath.basename(container_target).lower()
	for name in listdir(container_cwd) or []:
		if name.lower() == want_name:
			return posixpath.join(container_cwd, name)
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
