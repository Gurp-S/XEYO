"""扩展层 manifest 解析与校验。"""

from pathlib import Path

import pytest

from extension.errors import ManifestError
from extension.manifest import load_manifest, version_at_least


def _write(root: Path, name: str, content: str) -> Path:
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	(d / "plugin.json").write_text(content, encoding="utf-8")
	return d


def test_load_valid_manifest(tmp_path):
	root = _write(
		tmp_path,
		"ok",
		'{"name":"ok","version":"0.1.0","description":"d","skills":["skills/a"]}',
	)
	(root / "skills" / "a").mkdir(parents=True)
	(root / "skills" / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
	p = load_manifest(root)
	assert p.name == "ok"
	assert len(p.skill_dirs) == 1
	assert p.skill_dirs[0].name == "a"
	assert p.prompt_paths == ()


def test_missing_plugin_json(tmp_path):
	with pytest.raises(ManifestError):
		load_manifest(tmp_path / "nope")


def test_bad_json(tmp_path):
	root = _write(tmp_path, "bad", "{not json")
	with pytest.raises(ManifestError):
		load_manifest(root)


def test_invalid_path_escaping(tmp_path):
	# ../ 逃逸被拒
	root = _write(tmp_path, "esc", '{"name":"esc","skills":["../evil"]}')
	with pytest.raises(ManifestError):
		load_manifest(root)


def test_requires_at_least_one(tmp_path):
	root = _write(tmp_path, "empty", '{"name":"empty"}')
	with pytest.raises(ManifestError):
		load_manifest(root)


def test_invalid_name(tmp_path):
	root = _write(tmp_path, "bad-name!", '{"name":"bad-name!","skills":["s"]}')
	with pytest.raises(ManifestError):
		load_manifest(root)


def test_version_at_least():
	assert version_at_least("0.1.0", "0.1.0")
	assert version_at_least("0.2.0", "0.1.0")
	assert version_at_least("1.0.0", "0.9.9")
	assert not version_at_least("0.1.0", "0.2.0")


def test_mcp_spec_parsed(tmp_path):
	root = _write(
		tmp_path,
		"m",
		'{"name":"m","mcp_servers":[{"id":"fs","command":"npx","args":["-y","x"],"tools_policy":"outbound_ask"}]}',
	)
	p = load_manifest(root)
	assert len(p.manifest.mcp_servers) == 1
	assert p.manifest.mcp_servers[0].tools_policy == "outbound_ask"
	assert p.manifest.mcp_servers[0].auto_start is True
