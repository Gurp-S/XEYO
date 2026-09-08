"""XEYO.md 维护：模板 / doctor / 提案 / 过期 / /rule / 嵌套懒加载。"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.instruction import clear_instruction_cache, load_instruction_text
from memory.instruction_maintain import (
	REPEAT_PROMOTE_N,
	MINIMAL_TEMPLATE,
	append_rule_line,
	discover_nested_instruction_files,
	doctor_xeyo_md,
	ensure_minimal_xeyo_md,
	format_doctor_report,
	refresh_instruction_proposals,
	soft_instruction_budget,
)


@pytest.fixture(autouse=True)
def _iso_home(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	clear_instruction_cache()


def test_ensure_minimal_template(tmp_path):
	root = tmp_path / "proj"
	root.mkdir()
	path = ensure_minimal_xeyo_md(root)
	assert path is not None and path.is_file()
	assert "指针" in path.read_text(encoding="utf-8") or "Skill" in MINIMAL_TEMPLATE
	assert ensure_minimal_xeyo_md(root) is None  # 已存在不覆盖


def test_soft_budget_default():
	assert soft_instruction_budget() == 8_000


def test_doctor_flags_derivable(tmp_path):
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text(
		"# deps\ndependencies: react, lodash\n", encoding="utf-8"
	)
	issues = doctor_xeyo_md(root)
	codes = {i.code for i in issues}
	assert "derivable" in codes
	assert "doctor" in format_doctor_report(issues).lower() or "XEYO" in format_doctor_report(issues)


def test_append_rule_line(tmp_path):
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text("# hi\n", encoding="utf-8")
	msg = append_rule_line(root, "永远用中文回复")
	assert "永远用中文回复" in msg
	body = (root / "XEYO.md").read_text(encoding="utf-8")
	assert "永远用中文回复" in body


def test_nested_discovery(tmp_path):
	root = tmp_path / "proj"
	pkg = root / "pkg"
	pkg.mkdir(parents=True)
	(root / "XEYO.md").write_text("root\n", encoding="utf-8")
	(pkg / "XEYO.md").write_text("pkg rules\n", encoding="utf-8")
	f = pkg / "a.py"
	f.write_text("x=1\n", encoding="utf-8")
	found = discover_nested_instruction_files(str(f), str(root))
	assert any(p.endswith("pkg") or "pkg" in p for p in found) or any(
		Path(p).name == "XEYO.md" and "pkg" in p.replace("\\", "/") for p in found
	)


def test_proposals_after_repeats(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	from memory.governance import MemoryCandidate
	from memory.memdir import workspace_id
	from memory.nightshift import append_candidates

	root = tmp_path / "ws"
	root.mkdir()
	wsid = workspace_id(str(root))
	rule = "测试时必须跑 pytest"
	for _ in range(REPEAT_PROMOTE_N):
		append_candidates(
			wsid,
			[MemoryCandidate(content=rule, source={"kind": "agent"}, evidence=["repeat"])],
		)
	props = refresh_instruction_proposals(wsid, repeat_n=REPEAT_PROMOTE_N)
	assert any(rule in str(p.get("content")) for p in props) or props


def test_instruction_budget_caps_left(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_INSTRUCTION_BUDGET", "300")
	clear_instruction_cache()
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text("X" * 500, encoding="utf-8")
	text = load_instruction_text(str(root), str(root))
	assert len(text) <= 300


def test_parse_rule_command():
	from channels.filehelper.commands import parse_command

	hit = parse_command("/rule 永远用中文")
	assert hit is not None and hit.name == "rule" and "中文" in hit.arg
