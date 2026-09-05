"""记忆系统开关：设置持久化 + 运行时 os.environ 桥接 + /v1/settings/memory 端点。

运行：``py -3.11 -m pytest tests/test_memory_switches.py -q``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memory.memory_switches import (
	MEMORY_SWITCHES,
	apply_to_environ,
	current,
	save,
)
from server.app import app

_LAN = ("203.0.113.9", 55555)


def _ws(tmp_path: Path) -> Path:
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True, exist_ok=True)
	return ws


# ---- 模块层 ----
def test_defaults_when_unset(monkeypatch) -> None:
	for key, *_ in MEMORY_SWITCHES:
		monkeypatch.delenv(key, raising=False)
	cur = current(None)
	assert cur["XEYO_L5"]["value"] == "project"
	# 2026-09-06 固化：C2_GATE / V61_PARETO/SI/DYNAMIC_R / Path A 三公式已删除（v61 默认开启后冗余）
	assert "XEYO_C2_GATE" not in cur
	assert "XEYO_V61_PARETO" not in cur
	assert cur["XEYO_TOOL_AGING"]["value"] == "0"


def test_env_ignored_when_settings_absent(monkeypatch) -> None:
	"""环境变量不再参与：即使设置了合法值，settings 缺省也落默认（彻底禁 env）。"""
	for key, *_ in MEMORY_SWITCHES:
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv("XEYO_C2_GATE", "0")
	cur = current(None)
	assert "XEYO_C2_GATE" not in cur  # 已删键：env / settings 均不生效（固化恒 True）


def test_save_and_settings_win(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	save({"XEYO_TOOL_AGING": True}, cwd=str(ws))
	data = json.loads((ws / ".xeyo" / "settings.json").read_text(encoding="utf-8"))
	assert data["memory"]["XEYO_TOOL_AGING"] == "1"
	cur = current(str(ws))
	assert cur["XEYO_TOOL_AGING"]["value"] == "1"
	assert cur["XEYO_TOOL_AGING"]["source"] == "settings"


def test_apply_to_environ_sets_runtime_env(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	save({"XEYO_TOOL_AGING": "1"}, cwd=str(ws))
	ws2 = _ws(tmp_path / "other")
	applied = apply_to_environ(str(ws))
	assert applied.get("XEYO_TOOL_AGING") == "1"


def test_reject_illegal_value(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with pytest.raises(ValueError):
		save({"XEYO_L5": "bogus"}, cwd=str(ws))


# ---- API 层 ----
def test_memory_get(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		r = c.get(f"/v1/settings/memory?workspace={ws}")
		assert r.status_code == 200, r.text
		body = r.json()
	assert body["ok"] is True
	assert body["switches"]["XEYO_TOOL_AGING"]["value"] in ("0", "1")


def test_memory_post_saves_and_applies(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		r = c.post(
			f"/v1/settings/memory?workspace={ws}",
			json={"updates": {"XEYO_TOOL_AGING": True}},
		)
		assert r.status_code == 200, r.text
		body = r.json()
	assert body["ok"] is True
	assert body["memory"]["XEYO_TOOL_AGING"] == "1"
	assert body["switches"]["XEYO_TOOL_AGING"]["value"] == "1"


def test_memory_post_unknown_switch(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		r = c.post(
			f"/v1/settings/memory?workspace={ws}",
			json={"updates": {"XEYO_NOPE": "1"}},
		)
		assert r.status_code == 200
		body = r.json()
	assert body["ok"] is False


def test_memory_rejected_from_lan() -> None:
	with TestClient(app, client=_LAN) as c:
		assert c.get("/v1/settings/memory").status_code == 403
		assert c.post("/v1/settings/memory", json={}).status_code == 403
		assert c.post("/v1/settings/memory/snapshot").status_code == 403
