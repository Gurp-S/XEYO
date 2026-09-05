"""T27：aging 默认态与文档一致（默认关；开关走 settings.memory，env 不参与）。"""

from __future__ import annotations

import pytest

from engine.aging import ENV_KEY, aging_enabled


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_CWD", str(tmp_path))
	return tmp_path


def test_default_off(isolated) -> None:
	assert aging_enabled() is False


def test_explicit_on(isolated) -> None:
	from memory import memory_switches

	for v in ("1", "true", "on", "yes"):
		memory_switches.save({ENV_KEY: v}, cwd=str(isolated))
		assert aging_enabled() is True, v


def test_explicit_off(isolated) -> None:
	from memory import memory_switches

	for v in ("0", "false", "off", "no"):
		memory_switches.save({ENV_KEY: v}, cwd=str(isolated))
		assert aging_enabled() is False, v
