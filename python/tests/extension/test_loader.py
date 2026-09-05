"""插件发现 / 合并 / 去重 / 坏清单跳过。

G136: 插件激活的来源判定以 lockfile 安装期登记为准——manifest 自声明
``source_type`` 不可再免批；未登记(手工拷贝)插件按远程 fail-closed。
"""

from __future__ import annotations

import json
from pathlib import Path

from extension.config import load_ext_config
from extension.loader import discover_plugins, loaded_plugins_with_errors
from extension.plugin_store import default_lock_path, install as lock_install


def _mk_plugin(
	root: Path,
	name: str,
	*,
	body: dict | None = None,
	enabled: bool = True,
	register_local: bool = True,
) -> Path:
	"""造插件目录;``register_local`` 时同时登记 workspace/home lockfile(local)。"""
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	manifest = body or {
		"name": name,
		"version": "0.1.0",
		"description": f"{name} desc",
		"skills": ["skills/a"],
		"enabled": enabled,
	}
	(d / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
	(d / "skills" / "a").mkdir(parents=True)
	(d / "skills" / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
	if register_local:
		lock_install(
			default_lock_path(_scope_of(root)),
			name=name,
			source=f"local:{root}",
			source_type="local",
			plugin_path=d,
		)
	return d


def _scope_of(plugins_root: Path) -> str:
	"""plugins_root 形如 <scope>/.xeyo/plugins → 返回 <scope> 的字符串(供 default_lock_path)。"""
	return str((plugins_root / ".." / "..").resolve())


def _enable(ws: Path, name: str, enabled: bool = True) -> None:
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	data = json.loads(p.read_text()) if p.exists() else {}
	data["enabled_extensions"] = True
	data.setdefault("plugins", {})[name] = {"enabled": enabled}
	p.write_text(json.dumps(data), encoding="utf-8")


def test_discover_workspace_plugin(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_mk_plugin(ws / ".xeyo" / "plugins", "demo")
	_enable(ws, "demo")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	names = [(p.name, p.enabled, p.source_scope) for p in plugs]
	assert ("demo", True, "workspace") in names


def test_disabled_plugin_not_enabled(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_mk_plugin(ws / ".xeyo" / "plugins", "off")
	_enable(ws, "off", enabled=False)
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	got = {p.name: p.enabled for p in plugs}
	assert got.get("off") is False


def test_workspace_overrides_home_same_name(monkeypatch, tmp_path):
	home = tmp_path / "home"
	_mk_plugin(home / ".xeyo" / "plugins", "dup", body={"name": "dup"})
	monkeypatch.setenv("XEYO_HOME", str(home))
	ws = tmp_path / "ws"
	ws.mkdir()
	_mk_plugin(ws / ".xeyo" / "plugins", "dup")
	_enable(ws, "dup")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	dup = [p for p in plugs if p.name == "dup"][0]
	assert dup.source_scope == "workspace"  # 同名以 workspace 为准


def test_bad_manifest_skipped(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	bad = ws / ".xeyo" / "plugins" / "bad"
	bad.mkdir(parents=True)
	(bad / "plugin.json").write_text("{bad", encoding="utf-8")
	plugs, errs = loaded_plugins_with_errors(str(ws))
	assert plugs == []
	assert any("bad" in e for e in errs)


def test_unregistered_remote_claimed_plugin_disabled(tmp_path):
	"""G136: 未登记且 manifest 声明 github 的目录 → fail-closed 禁用(需批准)。"""
	ws = tmp_path / "ws"
	ws.mkdir()
	_mk_plugin(
		ws / ".xeyo" / "plugins",
		"spoof",
		body={
			"name": "spoof",
			"version": "0.1.0",
			"description": "x",
			"source_type": "github",
			"skills": ["skills/a"],
			"enabled": True,
		},
		register_local=False,
	)
	_enable(ws, "spoof")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	assert {p.name: p.enabled for p in plugs}["spoof"] is False


def test_github_installed_manifest_local_claim_still_disabled(tmp_path):
	"""G136: github 安装(lock=github)后,即使 manifest 被改成 local 声明也免不了批。"""
	ws = tmp_path / "ws"
	ws.mkdir()
	root = ws / ".xeyo" / "plugins"
	_mk_plugin(
		root,
		"evildo",
		body={
			"name": "evildo",
			"version": "0.1.0",
			"description": "x",
			"source_type": "local",  # 上游/攻击者自声明
			"skills": ["skills/a"],
			"enabled": True,
		},
		register_local=False,
	)
	# 以真实 github 安装登记(仿真 install_from_github 的 lock 写入)
	lock_install(
		default_lock_path(str(ws)),
		name="evildo",
		source="github:evil/repo",
		source_type="github",
		plugin_path=root / "evildo",
	)
	_enable(ws, "evildo")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	assert {p.name: p.enabled for p in plugs}["evildo"] is False


def test_registered_github_approved_active(tmp_path):
	from extension.plugin_fetcher import set_plugin_trusted

	ws = tmp_path / "ws"
	ws.mkdir()
	root = ws / ".xeyo" / "plugins"
	_mk_plugin(root, "trusted", register_local=False)
	lock_install(
		default_lock_path(str(ws)),
		name="trusted",
		source="github:good/repo",
		source_type="github",
		plugin_path=root / "trusted",
	)
	set_plugin_trusted(str(ws), "trusted", approved=True)
	_enable(ws, "trusted")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	assert {p.name: p.enabled for p in plugs}["trusted"] is True


def test_lock_local_overrides_manifest_remote_claim(tmp_path):
	"""G136 双向:lock 登记 local 的插件,manifest 乱写 github 也应激活(local 免批)。"""
	ws = tmp_path / "ws"
	ws.mkdir()
	root = ws / ".xeyo" / "plugins"
	_mk_plugin(
		root,
		"mislabeled",
		body={
			"name": "mislabeled",
			"version": "0.1.0",
			"description": "x",
			"source_type": "github",  # 与真实安装相悖的声明
			"skills": ["skills/a"],
			"enabled": True,
		},
		register_local=False,
	)
	lock_install(
		default_lock_path(str(ws)),
		name="mislabeled",
		source=f"local:{root}",
		source_type="local",  # 真实安装期来源
		plugin_path=root / "mislabeled",
	)
	_enable(ws, "mislabeled")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	assert {p.name: p.enabled for p in plugs}["mislabeled"] is True
