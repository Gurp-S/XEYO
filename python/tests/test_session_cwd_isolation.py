"""Per-session cwd isolation and UI workspace must not evict engines."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from msgtypes.message import user_message
from server.session_pool import CwdConflictError, ModelConfig, SessionPool
from session.workspace_path import boot_ui_cwd, python_package_root


def _cfg() -> ModelConfig:
	return ModelConfig(
		provider="deepseek",
		api_key="k",
		base_url="https://example.com/v1",
		model="m1",
	)


def test_two_sessions_keep_distinct_cwd(tmp_path: Path) -> None:
	a = tmp_path / "a"
	b = tmp_path / "b"
	a.mkdir()
	b.mkdir()
	(a / "only_a.txt").write_text("A", encoding="utf-8")
	(b / "only_b.txt").write_text("B", encoding="utf-8")
	pool = SessionPool(cwd=str(a), busy_stale_sec=600)
	e1 = pool.get_or_create("s1", _cfg(), cwd=str(a))
	e2 = pool.get_or_create("s2", _cfg(), cwd=str(b))
	assert os.path.realpath(e1.config["cwd"]) == os.path.realpath(a)
	assert os.path.realpath(e2.config["cwd"]) == os.path.realpath(b)
	assert e1.config["tools"].cwd != e2.config["tools"].cwd

	def _read(engine, name: str) -> str:
		root = engine.config["cwd"]
		return Path(root, name).read_text(encoding="utf-8")

	with ThreadPoolExecutor(max_workers=2) as ex:
		fa = ex.submit(_read, e1, "only_a.txt")
		fb = ex.submit(_read, e2, "only_b.txt")
		assert fa.result() == "A"
		assert fb.result() == "B"
		assert not Path(e1.config["cwd"], "only_b.txt").exists()
		assert not Path(e2.config["cwd"], "only_a.txt").exists()


def test_ui_set_cwd_does_not_evict_engines(tmp_path: Path) -> None:
	a = tmp_path / "a"
	ui = tmp_path / "ui"
	a.mkdir()
	ui.mkdir()
	pool = SessionPool(cwd=str(a), busy_stale_sec=600)
	eng = pool.get_or_create("s1", _cfg(), initial_messages=[user_message("hi")])
	pool.set_cwd(str(ui))
	assert pool.get_if_present("s1") is eng
	assert os.path.realpath(pool.cwd) == os.path.realpath(ui)
	assert os.path.realpath(eng.config["cwd"]) == os.path.realpath(a)


def test_session_cwd_conflict(tmp_path: Path) -> None:
	a = tmp_path / "a"
	b = tmp_path / "b"
	a.mkdir()
	b.mkdir()
	pool = SessionPool(cwd=str(a), busy_stale_sec=600)
	pool.get_or_create("s1", _cfg(), cwd=str(a))
	with pytest.raises(CwdConflictError):
		pool.get_or_create("s1", _cfg(), cwd=str(b))


def test_python_package_root_rejected_as_workspace(tmp_path: Path) -> None:
	pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
	with pytest.raises(ValueError, match="python package"):
		pool.set_cwd(python_package_root())


def test_boot_ui_cwd_rejects_python_root(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_CWD", python_package_root())
	assert boot_ui_cwd() == ""


def test_boot_ui_cwd_accepts_user_folder(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_CWD", str(tmp_path))
	assert os.path.realpath(boot_ui_cwd()) == os.path.realpath(tmp_path)
