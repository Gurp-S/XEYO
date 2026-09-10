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


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
	"""隔离 XEYO_HOME / XEYO_CWD：settings 只看 tmp，绝不读开发者真实配置。

	``_memory_store`` 会合并 home + workspace 两处 settings.json；不隔离的话，本机
	``~/.xeyo/settings.json`` 的残留键会污染 stale/prune 断言。
	"""
	home = tmp_path / "home"
	home.mkdir(exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.delenv("XEYO_CWD", raising=False)
	return home


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


# ---- GUI 暴露面与「显示 == 生效」契约 ----
def test_only_c2_llm_summary_is_gui_exposed() -> None:
	"""产品面板只暴露 C2 摘要 LLM 旁路；其余是测试/评测便捷开关，仅后端可切。"""
	cur = current(None)
	exposed = {k for k, v in cur.items() if v["exposed"]}
	assert exposed == {"XEYO_C2_LLM_SUMMARY"}


def test_dead_switch_reports_ignored_and_effective_default(tmp_path: Path) -> None:
	"""恒关占位键（XEYO_MEMORY_INDEX_LIVE）：settings 写 1 也必须报 ignored + effective=0。

	红线：GUI 按 effective 显示，禁止出现「显示开、实际关」（历史缺陷）。
	"""
	ws = _ws(tmp_path)
	# 直接落盘（走 save 会被注册表语义接受，但运行时本就不读该键）
	save({"XEYO_MEMORY_INDEX_LIVE": "1"}, cwd=str(ws))
	cur = current(str(ws))
	item = cur["XEYO_MEMORY_INDEX_LIVE"]
	assert item["value"] == "1"  # settings 里的字面值确实被记下了
	assert item["ignored"] is True
	assert item["effective"] == "0"  # 运行时真值 = 默认
	assert item["source"] == "ignored"  # 不再谎报 "settings"
	assert item["exposed"] is False


def test_live_switch_reports_effective_equal_value(tmp_path: Path) -> None:
	"""真正被运行时读取的开关：effective == value，source 随 settings/default。"""
	ws = _ws(tmp_path)
	save({"XEYO_C2_LLM_SUMMARY": "1"}, cwd=str(ws))
	item = current(str(ws))["XEYO_C2_LLM_SUMMARY"]
	assert item["ignored"] is False
	assert item["effective"] == "1"
	assert item["source"] == "settings"

	# settings 未指定 → 默认，仍是 effective == value
	ws2 = _ws(tmp_path / "other")
	item2 = current(str(ws2))["XEYO_C2_LLM_SUMMARY"]
	assert item2["effective"] == "0"
	assert item2["source"] == "default"


# ---- 残留键清理（缺陷②）----
_STALE = {
	"XEYO_MEMORY_RERANK_PREFERENCE": "1",
	"XEYO_MEMORY_SQLITE_INDEX": "1",
	"XEYO_CACHE_COOLDOWN_OMEGA": "1",
	"XEYO_C2_GATE": "1",
}


def _write_settings_with_stale(ws: Path, extra: dict | None = None) -> Path:
	path = ws / ".xeyo" / "settings.json"
	data = {"enabled_extensions": True, "memory": dict(_STALE, **({"XEYO_L5": "v61"} if extra is None else extra))}
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	return path


def test_stale_keys_is_readonly(tmp_path: Path) -> None:
	from memory.memory_switches import stale_keys

	ws = _ws(tmp_path)
	path = _write_settings_with_stale(ws)
	before = path.read_text(encoding="utf-8")
	assert stale_keys(str(ws)) == sorted(_STALE)
	assert path.read_text(encoding="utf-8") == before  # 只读：不写盘


def test_prune_stale_removes_only_stale_and_keeps_valid(tmp_path: Path) -> None:
	from memory.memory_switches import prune_stale, stale_keys

	ws = _ws(tmp_path)
	path = _write_settings_with_stale(ws)
	removed = prune_stale(str(ws))
	assert removed == sorted(_STALE)
	data = json.loads(path.read_text(encoding="utf-8"))
	assert data["memory"] == {"XEYO_L5": "v61"}  # 有效键保留
	assert data["enabled_extensions"] is True  # 其他段不碰
	assert stale_keys(str(ws)) == []
	# 无残留时零写入：内容逐字节不变
	before = path.read_text(encoding="utf-8")
	assert prune_stale(str(ws)) == []
	assert path.read_text(encoding="utf-8") == before


def test_save_prunes_stale_keys(tmp_path: Path) -> None:
	"""保存任一开关时顺带清掉残留键（GUI「立即清理」= POST 空 updates）。"""
	ws = _ws(tmp_path)
	path = _write_settings_with_stale(ws)
	save({"XEYO_C2_LLM_SUMMARY": "1"}, cwd=str(ws))
	data = json.loads(path.read_text(encoding="utf-8"))
	assert set(data["memory"]) == {"XEYO_C2_LLM_SUMMARY", "XEYO_L5"}


def test_api_reports_stale_and_prunes_on_post(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	_write_settings_with_stale(ws)
	with TestClient(app) as c:
		r = c.get(f"/v1/settings/memory?workspace={ws}")
		assert r.status_code == 200, r.text
		get_body = r.json()
		assert get_body["ok"] is True
		assert sorted(get_body["stale"]) == sorted(_STALE)

		r2 = c.post(f"/v1/settings/memory?workspace={ws}", json={"updates": {}})
		assert r2.status_code == 200, r2.text
		post_body = r2.json()
		assert post_body["ok"] is True
		assert sorted(post_body["pruned"]) == sorted(_STALE)
		assert post_body["stale"] == []
		assert (ws / ".xeyo" / "settings.json").read_text(encoding="utf-8").count("XEYO_C2_GATE") == 0
