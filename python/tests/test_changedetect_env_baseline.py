"""changedetect 环境基线：宿主会话桥进来的开关不得漂移 L0/L1 快照（2026-10-07）。

背景：agent / 受限容器会话会把项目级开关桥进进程，`surface check` 于是报出与产品
无关的"变化"（实测 XEYO_TOOL_DENY=Agent ⇒ L0 4 处 / L1 3 处）——这类红会诱使人
顺手 `update`，把被 deny 的机器钉成新基线。本文件钉住"基线必须消掉该漂移"。
"""

from __future__ import annotations

import os

from evals.changedetect import env_baseline, surface


def test_pin_reports_and_clears(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_TOOL_DENY", "Agent")
	monkeypatch.setenv("XEYO_T_NOW_SKIP", "env_facts")
	cleared = env_baseline.pin()
	assert [name for name, _, _ in cleared] == ["XEYO_TOOL_DENY", "XEYO_T_NOW_SKIP"]
	assert [value for _, value, _ in cleared] == ["Agent", "env_facts"]
	assert "XEYO_TOOL_DENY" not in os.environ
	assert "XEYO_T_NOW_SKIP" not in os.environ


def test_pin_is_silent_on_clean_env(monkeypatch) -> None:
	"""默认面环境下不产生输出（能静默就不说话）。"""
	for name, _why in env_baseline.PINS:
		monkeypatch.delenv(name, raising=False)
	assert env_baseline.pin() == []


def test_pin_removes_tool_surface_drift(monkeypatch) -> None:
	"""真回归：deny 造成的工具面漂移必须被基线消掉，且与干净环境逐字节一致。"""
	for name, _why in env_baseline.PINS:
		monkeypatch.delenv(name, raising=False)
	clean = [(a.name, a.sha) for a in surface.collect(groups={"tools"})]

	monkeypatch.setenv("XEYO_TOOL_DENY", "Agent")
	assert [(a.name, a.sha) for a in surface.collect(groups={"tools"})] != clean, (
		"前提失败：该 env 本应漂移工具面（否则本测试测不到东西）"
	)

	env_baseline.pin()
	assert [(a.name, a.sha) for a in surface.collect(groups={"tools"})] == clean
