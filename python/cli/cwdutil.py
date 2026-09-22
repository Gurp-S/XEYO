"""Workspace cwd helpers."""

from __future__ import annotations

import os
from pathlib import Path

from extension.config import publish_workspace_cwd
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
	"""Pick a workspace directory **and publish it** to the settings layer.

	Order: ``--cwd`` / explicit → ``XEYO_CWD`` → config ``last_cwd`` → process
	cwd → parent of ``python/`` when that is the CWD (click-to-use).

	发布这一步不是可选的：home + workspace 分层的 ``settings.json`` 只有拿到工作区
	才会合并 workspace 那一半，而下游（memory 开关 / localmodels / mcp_manager）
	够不着入口的 ``--cwd``。以前只有 ``cli serve`` 手工设 ``XEYO_CWD``，于是
	``chat`` / ``attach`` / ``coord`` 以及脚本与评测里**工作区级开关静默失效**。
	把发布收进本函数，任何调用方（含以后新增的子命令）都不可能再漏。

	``apply_to_environ`` 同理且更隐蔽：``settings.memory`` 是开关的**唯一权威**，
	但读开关的下游（``memory.wsc_projection.live_enabled`` 等）读的是 ``os.environ``，
	中间这座桥以前只在 ``server/__main__`` 与 ``routers/control`` 里调 ⇒ GUI 生效、
	CLI / 脚本 / 离线评测里同一个 ``XEYO_WSC=1`` **静默无效**。桥必须跟着工作区一起发布。
	只写 settings 里明确出现的键，用户自己在 shell / .bat 里设的值不被覆盖。
	"""
	cwd = _pick_cwd(
		explicit, allow_package_fallback=allow_package_fallback, persist=persist
	)
	publish_workspace_cwd(cwd)
	try:
		from memory.memory_switches import apply_to_environ

		apply_to_environ(cwd)
	except Exception:  # noqa: BLE001 - 桥失败不许让取工作区这件事跟着失败
		pass
	return cwd


def _pick_cwd(
	explicit: str | None = None,
	*,
	allow_package_fallback: bool = True,
	persist: bool = False,
) -> str:
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
