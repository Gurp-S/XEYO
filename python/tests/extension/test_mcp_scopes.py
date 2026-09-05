"""F1 mcp_scopes：三来源优先级、企业 deny、信任读取。

运行：``py -3.11 -m pytest tests/extension/test_mcp_scopes.py -q``
"""

from __future__ import annotations

import json

import pytest

from extension import mcp_scopes as scopes
from extension.config import load_ext_config


@pytest.fixture
def home(monkeypatch, tmp_path):
	home = tmp_path / "home"
	monkeypatch.setenv("XEYO_HOME", str(home))
	return home


def _write(ws, *, scope=None, spec=None, trust=None, settings=None):
	"""写项目/user scope 或信任文件。"""
	if spec:
		rel = {"project": ".xeyo/mcp.json", "user": None}
		if scope == "project":
			p = ws / ".xeyo" / "mcp.json"
			p.parent.mkdir(parents=True, exist_ok=True)
			p.write_text(json.dumps({"servers": spec}), encoding="utf-8")
		elif scope == "user":
			# user scope 在 XEYO_HOME 下。
			root = _home_root()
			p = root / "mcp.json"
			p.parent.mkdir(parents=True, exist_ok=True)
			p.write_text(json.dumps({"servers": spec}), encoding="utf-8")
	if trust:
		p = ws / ".xeyo" / "mcp-trust.json"
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text(json.dumps(trust), encoding="utf-8")
	if settings:
		p = ws / ".xeyo" / "settings.json"
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text(json.dumps(settings), encoding="utf-8")


def _home_root():
	from memory.instruction import xeyo_home

	return xeyo_home()


def _server(**kw):
	d = {"command": "npx", "args": []}
	d.update(kw)
	return d


def test_three_source_priority_project_wins(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write(ws, settings={"enabled_extensions": True})
	# plugin / user / project 同 id → project 胜出。
	_write(ws, scope="project", spec={"fs": _server(command="project-cmd")})
	_write(ws, scope="user", spec={"fs": _server(command="user-cmd")})
	cfg = load_ext_config(str(ws))
	specs = scopes.collect_mcp_specs(str(ws), config=cfg)
	assert specs["fs"]["command"] == "project-cmd"
	assert specs["fs"]["_scope"] == "project"


def test_user_over_plugin(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write(ws, settings={"enabled_extensions": True})
	_write(ws, scope="user", spec={"fs": _server(command="user-cmd")})
	cfg = load_ext_config(str(ws))
	specs = scopes.collect_mcp_specs(str(ws), config=cfg)
	assert specs["fs"]["command"] == "user-cmd"
	assert specs["fs"]["_scope"] == "user"


def test_enterprise_server_deny_veto(home, tmp_path, monkeypatch):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write(ws, settings={"enabled_extensions": True})
	_write(ws, scope="project", spec={"fs": _server(), "evil": _server()})
	pol_path = ws / "policy.json"
	monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(pol_path))
	pol_path.write_text(json.dumps({"mcp_server_deny": ["evil"]}), encoding="utf-8")
	cfg = load_ext_config(str(ws))
	specs = scopes.collect_mcp_specs(str(ws), config=cfg)
	assert "evil" not in specs
	assert "fs" in specs


def test_mcp_tool_deny_patterns(home, tmp_path, monkeypatch):
	pol_path = tmp_path / "policy.json"
	monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(pol_path))
	pol_path.write_text(
		json.dumps({"mcp_tool_deny": ["server/read", "other/*"]}), encoding="utf-8"
	)
	assert scopes.mcp_tool_denied("server", "read") is True
	assert scopes.mcp_tool_denied("other", "anything") is True
	assert scopes.mcp_tool_denied("server", "write") is False


def test_bad_policy_falls_back_defaults(home, tmp_path, monkeypatch):
	pol_path = tmp_path / "policy.json"
	monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(pol_path))
	pol_path.write_text("{not json", encoding="utf-8")
	pol = scopes.load_enterprise_policy()
	assert pol["mcp_server_deny"] == []
	assert pol["mcp_tool_deny"] == []


def test_trust_project_requires_approval(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	spec = _server()
	spec["_scope"] = "project"
	spec["_requires_trust"] = True
	spec["command"] = "npx"
	# 未批准 → False（不会 spawn）。
	assert scopes.is_server_trusted(str(ws), spec) is False
	# 批准（按声明 hash）→ True。
	h = scopes.declaration_hash(spec)
	_write(ws, trust={h: {"approved": True}})
	assert scopes.is_server_trusted(str(ws), spec) is True


def test_trust_user_plugin_exempt(home):
	# user/plugin scope 免批。
	spec = _server()
	spec["_scope"] = "user"
	spec["_requires_trust"] = False
	assert scopes.is_server_trusted(None, spec) is True


def test_declaration_hash_is_canonical(home, tmp_path):
	a = _server()
	a["_scope"] = "project"
	a["env"] = {"A": "1"}
	b = _server()
	b["env"] = {"A": "1"}
	b["_scope"] = "project"
	# 键序无关：规范序列化同一身份。
	assert scopes.declaration_hash(a) == scopes.declaration_hash(
		{"_scope": "project", "_requires_trust": True, **b}
	)
