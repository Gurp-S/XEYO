"""插件安装的两条硬门：目录落点必须封在插件根内；update 必须让账本跟着文件走。

起因（逐条对应下面的测试）：
* ``manifest`` 的 name 字符集 ``[a-zA-Z0-9_.-]`` 放行 ``..``，而 ``_copy_install`` 把
  这个名字直接拼进路径并 ``shutil.rmtree`` —— ``plugins_root/..`` 就是工作区的
  ``.xeyo`` 整体，等于一个任意目录删除原语。
* ``_copy_install`` 在 ``allow_update`` 下删旧-copy 新之后仍调 ``plugin_store.install``
  （同名即冲突），于是磁盘已经换体、lockfile 还留旧 hash：路由报失败，
  ``detect_drift`` 从此常亮。``plugin_store.update`` 当时是死代码。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from extension import plugin_fetcher
from extension.errors import PluginError
from extension.manifest import PluginManifest
from extension.plugin_fetcher import (
	install_from_path,
	plugins_root,
	update_from_registry,
)
from extension.plugin_store import (
	default_lock_path,
	detect_drift,
	dir_hash,
	load_plugins,
)


def _mk_plugin(root: Path, name: str, *, body: str = "# A") -> Path:
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	(d / "plugin.json").write_text(
		json.dumps({"name": name, "version": "0.1.0", "skills": ["skills/a"]}),
		encoding="utf-8",
	)
	(d / "skills" / "a").mkdir(parents=True)
	(d / "skills" / "a" / "SKILL.md").write_text(body, encoding="utf-8")
	return d


def _ws(tmp_path: Path) -> Path:
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True)
	return ws


def _fake(name: str):
	"""伪装 validate_manifest 的返回：只有 name 是错的，其余一律合法。"""
	return SimpleNamespace(name=name, manifest=SimpleNamespace(min_xeyo=""))


# --------------------------------------------------------------------------- #
# 门 1：manifest 不许把 `.`/`..` 这类"只有点"的名字当合法插件名
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["..", ".", "..."])
def test_manifest_rejects_dot_only_names(bad):
	with pytest.raises(ValidationError):
		PluginManifest(name=bad, skills=["skills/a"])


def test_manifest_still_accepts_ordinary_dotted_names():
	assert PluginManifest(name="my.plugin", skills=["skills/a"]).name == "my.plugin"


# --------------------------------------------------------------------------- #
# 门 2：就算名字绕过 manifest，落点校验也必须拦住 rmtree
# --------------------------------------------------------------------------- #

def test_containment_guard_survives_a_forged_manifest_name(tmp_path, monkeypatch):
	"""直接伪造 validate_manifest 的返回值 ⇒ 只可能由落点校验救人。"""
	ws = _ws(tmp_path)
	canary = ws / ".xeyo" / "canary"
	canary.mkdir()
	(canary / "keepme.txt").write_text("x", encoding="utf-8")

	src = _mk_plugin(tmp_path / "src", "whatever")
	monkeypatch.setattr(
		plugin_fetcher, "validate_manifest", lambda _p: _fake("..")
	)

	with pytest.raises(PluginError, match="unsafe plugin install destination"):
		install_from_path(str(ws), str(src), allow_update=True)

	assert canary.is_dir(), "落点校验失效：`.xeyo` 目录被删了"
	assert (canary / "keepme.txt").is_file()


@pytest.mark.parametrize("bad", ["..", ".", "a/b", r"C:\Windows"])
def test_copy_install_refuses_unsafe_destination(tmp_path, monkeypatch, bad):
	"""断言错因：同名冲突也是 PluginError，不能靠它蒙过落点校验。"""
	ws = _ws(tmp_path)
	src = _mk_plugin(tmp_path / "src", "whatever")
	monkeypatch.setattr(plugin_fetcher, "validate_manifest", lambda _p: _fake(bad))

	with pytest.raises(PluginError, match="unsafe plugin install destination"):
		install_from_path(str(ws), str(src))


# --------------------------------------------------------------------------- #
# 门 3：update 语义必须让 lockfile 跟着磁盘走
# --------------------------------------------------------------------------- #

def test_update_rewrites_lockfile_hash_and_leaves_no_drift(tmp_path):
	ws = _ws(tmp_path)
	src = _mk_plugin(tmp_path / "src", "demo", body="# old")

	entry = install_from_path(str(ws), str(src))
	assert entry["name"] == "demo"
	assert load_plugins(default_lock_path(str(ws)))["demo"]["computedHash"]

	src.joinpath("skills", "a", "SKILL.md").write_text("# new", encoding="utf-8")

	updated = install_from_path(str(ws), str(src), allow_update=True)

	target = plugins_root(str(ws)) / "demo"
	assert updated["computedHash"] == dir_hash(target), "update 之后账本 hash 仍是旧值"
	lock = default_lock_path(str(ws))
	assert load_plugins(lock)["demo"]["computedHash"] == updated["computedHash"]
	assert detect_drift(lock) == []


def test_update_from_registry_succeeds_and_reports_state(tmp_path):
	ws = _ws(tmp_path)
	src = _mk_plugin(tmp_path / "src", "demo", body="# v1")
	install_from_path(str(ws), str(src))

	src.joinpath("skills", "a", "SKILL.md").write_text("# v2", encoding="utf-8")

	entry = update_from_registry(str(ws), "demo")
	target = plugins_root(str(ws)) / "demo"
	assert entry["computedHash"] == dir_hash(target)
	assert (target / "skills" / "a" / "SKILL.md").read_text(encoding="utf-8") == "# v2"


def test_fresh_install_of_same_name_still_conflicts(tmp_path):
	"""allow_update=False 的冲突门不许因为新逻辑被削弱。"""
	ws = _ws(tmp_path)
	src = _mk_plugin(tmp_path / "src", "demo")
	install_from_path(str(ws), str(src))
	with pytest.raises(PluginError):
		install_from_path(str(ws), str(src))
	assert (plugins_root(str(ws)) / "demo").is_dir()
