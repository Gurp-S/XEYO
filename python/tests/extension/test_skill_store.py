"""skills-lock.json 读写与漂移检测。"""

from pathlib import Path

from extension.skill_store import (
	default_lock_path,
	detect_drift,
	hash_skill_file,
	install,
	load_skills,
	read_lock,
	remove,
	write_lock,
)


def _mk_skill(root: Path, name: str, body: str = "body") -> Path:
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	(d / "SKILL.md").write_text(body, encoding="utf-8")
	return d / "SKILL.md"


def test_read_default_empty(tmp_path):
	lock = read_lock(tmp_path / "skills-lock.json")
	assert lock["skills"] == {}


def test_install_and_load(tmp_path):
	skill_md = _mk_skill(tmp_path, "react-doctor")
	e = install(
		tmp_path / "skills-lock.json",
		name="react-doctor",
		source="millionco/react-doctor",
		source_type="github",
		skill_path=skill_md,
	)
	assert e["computedHash"] == hash_skill_file(skill_md)
	skills = load_skills(tmp_path / "skills-lock.json")
	assert "react-doctor" in skills
	assert skills["react-doctor"]["sourceType"] == "github"


def test_remove(tmp_path):
	skill_md = _mk_skill(tmp_path, "x")
	lock = tmp_path / "skills-lock.json"
	install(lock, name="x", source="s", source_type="local", skill_path=skill_md)
	assert remove(lock, name="x") is True
	assert remove(lock, name="x") is False
	assert load_skills(lock) == {}


def test_detect_drift(tmp_path):
	skill_md = _mk_skill(tmp_path, "y")
	lock = tmp_path / "skills-lock.json"
	install(lock, name="y", source="s", source_type="local", skill_path=skill_md)
	assert detect_drift(lock) == []
	# 改内容 → 漂移
	skill_md.write_text("changed", encoding="utf-8")
	drift = detect_drift(lock)
	assert len(drift) == 1
	assert drift[0]["name"] == "y"


def test_write_lock_roundtrip(tmp_path):
	lock = tmp_path / "skills-lock.json"
	write_lock(lock, {"version": 1, "skills": {}})
	assert read_lock(lock)["version"] == 1


def test_default_lock_path_in_home(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	p = default_lock_path(None)
	assert p.name == "skills-lock.json"
	assert p.parent == tmp_path
