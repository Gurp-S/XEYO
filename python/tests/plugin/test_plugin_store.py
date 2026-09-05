"""plugin_store：安装/冲突/更新/卸载归属/漂移/目录哈希。"""

from pathlib import Path

import pytest

from extension.errors import PluginConflictError
from extension.plugin_store import (
	default_lock_path,
	detect_drift,
	dir_hash,
	install,
	read_lock,
	remove,
	update,
)


def _mk_plugin_root(root: Path, name: str) -> Path:
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	(d / "plugin.json").write_text('{"name":"%s","version":"0.1.0"}' % name, encoding="utf-8")
	(d / "readme.md").write_text("# hello", encoding="utf-8")
	return d


def test_install_records_entry(tmp_path):
	lock = tmp_path / "plugins-lock.json"
	src = _mk_plugin_root(tmp_path / "src", "demo")
	entry = install(lock, name="demo", source="local", source_type="local", plugin_path=src)
	assert entry["name"] == "demo"
	assert entry["computedHash"]
	got = read_lock(lock)["plugins"]["demo"]
	assert got["source"] == "local"
	assert got["path"].endswith("demo")


def test_install_same_name_conflict(tmp_path):
	lock = tmp_path / "plugins-lock.json"
	src = _mk_plugin_root(tmp_path / "src", "demo")
	install(lock, name="demo", source="local", source_type="local", plugin_path=src)
	with pytest.raises(PluginConflictError):
		install(lock, name="demo", source="github:o/r", source_type="github", plugin_path=src)


def test_update_overrides(tmp_path):
	lock = tmp_path / "plugins-lock.json"
	src = _mk_plugin_root(tmp_path / "src", "demo")
	install(lock, name="demo", source="local", source_type="local", plugin_path=src)
	(src / "new.md").write_text("x", encoding="utf-8")
	update(lock, name="demo", source="local", source_type="local", plugin_path=src)
	got = read_lock(lock)["plugins"]["demo"]
	assert got["source"] == "local"


def test_remove_and_ownership(tmp_path):
	lock = tmp_path / "plugins-lock.json"
	src = _mk_plugin_root(tmp_path / "src", "demo")
	install(lock, name="demo", source="local", source_type="local", plugin_path=src)
	assert remove(lock, name="demo", owner_source="local") is True
	assert "demo" not in read_lock(lock)["plugins"]
	# 再删不存在 → False
	assert remove(lock, name="demo", owner_source="local") is False


def test_remove_ownership_mismatch(tmp_path):
	lock = tmp_path / "plugins-lock.json"
	src = _mk_plugin_root(tmp_path / "src", "demo")
	install(lock, name="demo", source="local", source_type="local", plugin_path=src)
	with pytest.raises(PluginConflictError):
		remove(lock, name="demo", owner_source="github:o/r")


def test_detect_drift(tmp_path):
	lock = tmp_path / "plugins-lock.json"
	installed = tmp_path / ".xeyo" / "plugins" / "demo"
	installed.parent.mkdir(parents=True)
	src = _mk_plugin_root(tmp_path / "src", "demo")
	import shutil

	shutil.copytree(src, installed)
	install(lock, name="demo", source="local", source_type="local", plugin_path=installed)
	# 一开始无漂移
	assert detect_drift(lock) == []
	# 改文件 → 漂移
	(installed / "plugin.json").write_text('{"name":"demo","version":"0.2.0"}', encoding="utf-8")
	assert len(detect_drift(lock)) == 1


def test_dir_hash_changes_on_content(tmp_path):
	d = _mk_plugin_root(tmp_path / "d", "p")
	h1 = dir_hash(d)
	(d / "extra.md").write_text("z", encoding="utf-8")
	h2 = dir_hash(d)
	assert h1 != h2
	assert dir_hash(tmp_path / "nonexistent") == ""


def test_default_lock_path_shape(tmp_path):
	p = default_lock_path(str(tmp_path))
	assert p.parent.name == ".xeyo"
	assert p.name == "plugins-lock.json"
