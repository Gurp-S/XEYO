"""Workspace cwd helpers."""

from __future__ import annotations

import os
from pathlib import Path

from session.workspace_path import (
	boot_ui_cwd,
	is_python_package_root,
	python_package_root,
	resolve_physical_cwd,
)


def _looks_like_project_root(path: str) -> bool:
	"""Heuristic: monorepo / app root rather than the engine package itself."""
	p = Path(path)
	markers = (
		"gui",
		"README.md",
		"pyproject.toml",
		"package.json",
		".git",
		"XEYO.bat",
		"XEYO-CLI.bat",
	)
	return any((p / m).exists() for m in markers)


def package_parent_workspace() -> str | None:
	"""If CWD is python/, prefer the repo parent when it looks like a project."""
	pkg = python_package_root()
	parent = str(Path(pkg).parent)
	if parent and _looks_like_project_root(parent) and not is_python_package_root(parent):
		return os.path.realpath(parent)
	return None


def try_resolve_workspace(path: str) -> str | None:
	"""Resolve a user-typed workspace; None if invalid or is the package root."""
	raw = (path or "").strip()
	if not raw:
		return None
	try:
		cwd = resolve_physical_cwd(raw)
	except (OSError, ValueError):
		return None
	if is_python_package_root(cwd):
		return None
	return cwd


def resolve_cwd(
	explicit: str | None = None,
	*,
	allow_package_fallback: bool = True,
	persist: bool = False,
) -> str:
	"""Pick a workspace directory.

	Order: ``--cwd`` / explicit → ``XEYO_CWD`` → config ``last_cwd`` → process
	cwd → parent of ``python/`` when that is the CWD (click-to-use).
	"""
	if explicit and explicit.strip():
		cwd = resolve_physical_cwd(explicit.strip())
		if is_python_package_root(cwd):
			raise SystemExit(
				"Refusing to use the python/ package root as workspace. "
				"Pass --cwd to your project, or set XEYO_CWD."
			)
		if persist:
			_remember_cwd(cwd)
		return cwd

	boot = boot_ui_cwd()
	if boot:
		if persist:
			_remember_cwd(boot)
		return boot

	# 上次成功 chat/setup 记住的工作区。
	try:
		from cli.config_store import load_config

		last = (load_config().last_cwd or "").strip()
	except Exception:
		last = ""
	if last:
		got = try_resolve_workspace(last)
		if got:
			return got

	cwd = resolve_physical_cwd(os.getcwd())
	if is_python_package_root(cwd):
		if allow_package_fallback:
			parent = package_parent_workspace()
			if parent:
				if persist:
					_remember_cwd(parent)
				return parent
		raise SystemExit(
			"Refusing to use the python/ package root as workspace. "
			"Pass --cwd to your project, or set XEYO_CWD."
		)
	if persist:
		_remember_cwd(cwd)
	return cwd


def _remember_cwd(cwd: str) -> None:
	try:
		from cli.config_store import load_config, save_config

		cfg = load_config()
		if (cfg.last_cwd or "") == cwd:
			return
		cfg.last_cwd = cwd
		save_config(cfg)
	except Exception:
		pass


def ensure_utf8_stdio() -> None:
	try:
		import sys

		sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
		sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
		sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
	except Exception:
		pass
