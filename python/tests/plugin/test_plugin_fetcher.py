"""plugin_fetcher：来源解析 / 本地安装 / min_xeyo / 供应链env剥离 / 信任 / 卸载归属。

github 安装通过 monkeypatch 伪造 ``subprocess.run`` 返回预置 git 目录，
避免真实网络 / git 依赖；只测 XEYO 自身装配逻辑。
"""

from pathlib import Path

import pytest

from extension.errors import PluginConflictError, PluginError
from extension.plugin_fetcher import (
	install_from_path,
	install_from_spec,
	is_plugin_trusted,
	parse_source,
	plugin_declaration_hash,
	plugins_root,
	remove_plugin,
	scrub_git_env,
	set_plugin_trusted,
)


def _mk_plugin(root: Path, name: str, *, min_xeyo: str = "") -> Path:
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	body = {"name": name, "version": "0.1.0", "skills": ["skills/a"]}
	if min_xeyo:
		body["min_xeyo"] = min_xeyo
	(d / "plugin.json").write_text(__import__("json").dumps(body), encoding="utf-8")
	(d / "skills").mkdir()
	(d / "skills" / "a").mkdir()
	(d / "skills" / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
	return d


def test_parse_source_github():
	p = parse_source("github:owner/repo@v1.2")
	assert p["source_type"] == "github"
	assert p["ref"] == "v1.2"
	p2 = parse_source("owner/repo")
	assert p2["source_type"] == "github"
	assert p2["source"] == "github:owner/repo"


def test_parse_source_local_path():
	assert parse_source("/abs/path")["source_type"] == "local"
	assert parse_source("./rel")["source_type"] == "local"


def test_parse_source_npm():
	p = parse_source("npm:my-pkg")
	assert p["source_type"] == "npm"


def test_scrub_git_env_strips_git_vars():
	env = {"GIT_DIR": "/x", "PATH": "/usr/bin", "GIT_OPTIONAL_LOCKS": "1"}
	out = scrub_git_env(env)
	assert "GIT_DIR" not in out
	assert out["PATH"] == "/usr/bin"
	assert out["GIT_OPTIONAL_LOCKS"] == "0"  # 强制安全项


def test_install_from_path(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	src = _mk_plugin(tmp_path / "src", "demo")
	entry = install_from_path(str(ws), str(src))
	assert entry["name"] == "demo"
	assert (plugins_root(str(ws)) / "demo" / "plugin.json").is_file()


def test_install_from_path_same_name_conflict(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	src = _mk_plugin(tmp_path / "src", "demo")
	install_from_path(str(ws), str(src))
	with pytest.raises(PluginConflictError):
		install_from_path(str(ws), str(src))


def test_install_min_xeyo_unsupported(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	src = _mk_plugin(tmp_path / "src", "future", min_xeyo="99.0.0")
	with pytest.raises(PluginError):
		install_from_path(str(ws), str(src))


def test_install_from_spec_dispatch_local(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	src = _mk_plugin(tmp_path / "src", "demo")
	res = install_from_spec(str(ws), str(src))
	assert res["name"] == "demo"


def test_install_from_spec_npm_not_enabled(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	with pytest.raises(PluginError):
		install_from_spec(str(ws), "npm:whatever")


def test_trust_fail_closed_local_and_remote(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	# 本地免批
	assert is_plugin_trusted(str(tmp_path), "demo", source_type="local") is True
	# 远程默认未受信
	assert is_plugin_trusted(str(tmp_path), "demo", source_type="github") is False
	set_plugin_trusted(str(tmp_path), "demo", approved=True)
	assert is_plugin_trusted(str(tmp_path), "demo", source_type="github") is True


def test_remove_plugin_ownership(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	src = _mk_plugin(tmp_path / "src", "demo")
	install_from_path(str(ws), str(src))
	# 归属校验：owner_source 不匹配 → 拒绝；正确 → 删除。
	with pytest.raises(PluginConflictError):
		remove_plugin(str(ws), "demo", owner_source="github:o/r")
	ok = remove_plugin(str(ws), "demo", owner_source=str(src))
	assert ok is True
	assert not (plugins_root(str(ws)) / "demo").exists()


def test_plugin_declaration_hash_deterministic():
	a = plugin_declaration_hash({"name": "x", "version": "1.0"})
	b = plugin_declaration_hash({"version": "1.0", "name": "x"})
	assert a == b
