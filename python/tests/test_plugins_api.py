"""插件控制路径：``/v1/plugins`` GET / install / update / remove / market。

- loopback 门禁（LAN 拒绝）；
- 安装在扩展层主开关关时 fail-closed；
- 本地安装 → 插件根 + lockfile + 视图含 registered / drift；
- 同名重复安装 → 拒绝；卸载缺失 → False；
- market：默认关返回空；开 + 企业白名单过滤。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app

_LAN = ("203.0.113.7", 55555)


def _mk_plugin(tmp: Path, name: str = "demo") -> Path:
	d = tmp / "src" / name
	d.mkdir(parents=True, exist_ok=True)
	(d / "plugin.json").write_text(
		json.dumps({"name": name, "version": "0.1.0", "skills": ["skills/a"]}),
		encoding="utf-8",
	)
	(d / "skills" / "a").mkdir(parents=True)
	(d / "skills" / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
	return d


def _enable(ws: Path) -> None:
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	data = json.loads(p.read_text()) if p.exists() else {}
	data["enabled_extensions"] = True
	p.write_text(json.dumps(data), encoding="utf-8")


def test_plugins_rejected_from_lan() -> None:
	with TestClient(app, client=_LAN) as c:
		assert c.get("/v1/plugins").status_code == 403
		assert c.post("/v1/plugins/install", json={"source": "demo"}).status_code == 403


def test_plugins_view_defaults(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	ws = tmp_path / "ws"
	ws.mkdir()
	with TestClient(app) as c:
		r = c.get(f"/v1/plugins?workspace={ws}")
		assert r.status_code == 200, r.text
		body = r.json()
	assert body["ok"] is True
	assert body["enabled_extensions"] is False
	assert body["plugin_market"] is False
	assert body["plugins"] == []


def test_install_local_plugin(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	src = _mk_plugin(tmp_path)
	with TestClient(app) as c:
		r = c.post(f"/v1/plugins/install?workspace={ws}", json={"source": str(src)})
		assert r.status_code == 200, r.text
		body = r.json()
	assert body["ok"] is True, body
	assert body["installed"]["name"] == "demo"
	assert "demo" in body["registered"]
	assert (ws / ".xeyo" / "plugins" / "demo" / "plugin.json").is_file()
	assert body["drift"] == []


def test_install_requires_extensions_on(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	ws = tmp_path / "ws"
	ws.mkdir()
	src = _mk_plugin(tmp_path)
	with TestClient(app) as c:
		r = c.post(f"/v1/plugins/install?workspace={ws}", json={"source": str(src)})
		body = r.json()
	assert body["ok"] is False
	assert "扩展层" in body["message"]


def test_install_duplicate_rejected(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	src = _mk_plugin(tmp_path)
	with TestClient(app) as c:
		c.post(f"/v1/plugins/install?workspace={ws}", json={"source": str(src)})
		r2 = c.post(f"/v1/plugins/install?workspace={ws}", json={"source": str(src)})
		assert r2.status_code == 200
		assert r2.json()["ok"] is False
		assert "already" in r2.json()["message"].lower() or "已" in r2.json()["message"]


def test_remove_plugin(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	src = _mk_plugin(tmp_path)
	with TestClient(app) as c:
		c.post(f"/v1/plugins/install?workspace={ws}", json={"source": str(src)})
		r = c.post(f"/v1/plugins/remove?workspace={ws}", json={"name": "demo"})
		assert r.status_code == 200, r.text
		body = r.json()
	assert body["ok"] is True
	assert body["removed"] == "demo"
	assert body["existed"] is True
	assert not (ws / ".xeyo" / "plugins" / "demo").exists()
	with TestClient(app) as c:
		r2 = c.get(f"/v1/plugins?workspace={ws}")
		assert r2.json()["plugins"] == []


def test_slash_plugins_install(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	src = _mk_plugin(tmp_path)
	from slash.dispatch import DispatchContext, dispatch

	ctx = DispatchContext(session_id="s1", workspace=str(ws))
	res = dispatch("/plugins", f"install {src}", ctx=ctx)
	assert res.handled and res.result["ok"] is True, res.message
	assert res.result["name"] == "demo"
	assert (ws / ".xeyo" / "plugins" / "demo" / "plugin.json").is_file()
	# 扩展层关时 fail-closed
	(ws / ".xeyo" / "settings.json").write_text(json.dumps({}), encoding="utf-8")
	res2 = dispatch("/plugins", f"install {src}", ctx=ctx)
	assert res2.handled and res2.result["ok"] is False


def test_market_off_then_on(tmp_path, monkeypatch):
	home = tmp_path / "home"
	home.mkdir()
	monkeypatch.setenv("XEYO_HOME", str(home))
	ws = tmp_path / "ws"
	ws.mkdir()
	# registry 文件 + 白名单。
	(home / "plugin-market.json").write_text(
		json.dumps({"version": 1, "sources": [
			{"name": "a", "source": "github:o/a"},
			{"name": "b", "source": "github:o/b"},
		]}),
		encoding="utf-8",
	)
	with TestClient(app) as c:
		# 默认 market 关 → 空。
		r = c.get(f"/v1/plugins/market?workspace={ws}")
		assert r.json()["enabled"] is False and r.json()["sources"] == []
		# 开 market（扩展层主开关已开）
		_enable(ws)
		(ws / ".xeyo" / "settings.json").write_text(
			json.dumps({"enabled_extensions": True, "plugin_market": True}), encoding="utf-8"
		)
		# 企业白名单只放行 o/a。
		from extension.mcp_scopes import _default_enterprise_policy

		pol = _default_enterprise_policy()
		pol["plugin_market_allow"] = ["github:o/a"]
		(home / "policy.json").write_text(json.dumps(pol), encoding="utf-8")
		monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(home / "policy.json"))
		r2 = c.get(f"/v1/plugins/market?workspace={ws}")
		body = r2.json()
		assert body["enabled"] is True
		assert [s["source"] for s in body["sources"]] == ["github:o/a"]
