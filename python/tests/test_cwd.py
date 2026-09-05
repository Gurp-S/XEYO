from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

from session.cwd import get_cwd, get_original_cwd, reset_cwd_for_tests, set_cwd
from session.state import SessionState


def test_set_cwd_resolves_and_get_cwd(tmp_path: Path):
	reset_cwd_for_tests()
	physical = set_cwd(str(tmp_path), set_as_original=True)
	assert Path(physical) == tmp_path.resolve()
	assert get_cwd() == physical
	assert get_original_cwd() == physical


def test_set_cwd_relative(tmp_path: Path):
	reset_cwd_for_tests()
	set_cwd(str(tmp_path), set_as_original=True)
	sub = tmp_path / "sub"
	sub.mkdir()
	physical = set_cwd("sub")
	assert Path(physical) == sub.resolve()
	assert get_cwd() == physical


def test_set_cwd_missing_raises(tmp_path: Path):
	reset_cwd_for_tests()
	set_cwd(str(tmp_path))
	try:
		set_cwd("no_such_dir_xyz")
		assert False, "expected FileNotFoundError"
	except FileNotFoundError:
		pass


def test_session_state_apply_cwd(tmp_path: Path):
	reset_cwd_for_tests()
	state = SessionState(cwd=str(tmp_path))
	assert Path(state.cwd) == tmp_path.resolve()
	sub = tmp_path / "a"
	sub.mkdir()
	state.apply_cwd("a")
	assert Path(state.cwd) == sub.resolve()


def test_default_no_os_chdir(tmp_path: Path):
	reset_cwd_for_tests()
	before = os.getcwd()
	set_cwd(str(tmp_path))
	assert os.getcwd() == before
	assert get_cwd() == str(tmp_path.resolve())
