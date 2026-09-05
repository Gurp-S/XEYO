"""Resolve and validate workspace roots without process-global cwd."""

from __future__ import annotations

import os
from pathlib import Path


def python_package_root() -> str:
	return os.path.realpath(str(Path(__file__).resolve().parent.parent))


def is_python_package_root(path: str) -> bool:
	raw = (path or "").strip()
	if not raw:
		return False
	try:
		return os.path.realpath(raw) == python_package_root()
	except OSError:
		return False


def resolve_physical_cwd(path: str, relative_to: str | None = None) -> str:
	raw = (path or "").strip()
	if not raw:
		raise ValueError("cwd path is empty")
	base = relative_to if relative_to is not None else os.getcwd()
	expanded = os.path.expanduser(raw)
	if os.path.isabs(expanded):
		resolved = os.path.abspath(expanded)
	else:
		resolved = os.path.abspath(os.path.join(base, expanded))
	if not os.path.exists(resolved):
		raise FileNotFoundError(f'Path "{resolved}" does not exist')
	if not os.path.isdir(resolved):
		raise NotADirectoryError(f'Path "{resolved}" is not a directory')
	return os.path.realpath(resolved)


def boot_ui_cwd() -> str:
	"""Explorer cwd at process start. Never treat the Python package as a workspace."""
	raw = os.environ.get("XEYO_CWD", "").strip()
	if not raw:
		return ""
	try:
		physical = resolve_physical_cwd(raw)
	except (OSError, ValueError):
		return ""
	if is_python_package_root(physical):
		return ""
	return physical


def xeyo_data_root() -> Path:
	for key in ("XEYO_DATA_DIR", "XEYO_HOME"):
		configured = os.environ.get(key, "").strip()
		if configured:
			return Path(configured).expanduser()
	return Path.home() / ".xeyo"
