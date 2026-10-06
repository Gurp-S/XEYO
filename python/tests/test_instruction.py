"""L1 XEYO.md 注入 system（M-L1）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from memory.instruction import clear_instruction_cache, load_instruction_text
from prompt.assembler import PromptAssembler
from prompt.system_prompt import assemble_system_prompt, fetch_system_prompt_parts


def test_workspace_xeyo_md_in_text(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text("永远用中文回复", encoding="utf-8")
	text = load_instruction_text(str(root), str(root))
	assert "永远用中文回复" in text


def test_later_file_overrides(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	home = tmp_path / "home"
	home.mkdir()
	(home / "XEYO.md").write_text("reply in english", encoding="utf-8")
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text("永远用中文回复", encoding="utf-8")
	text = load_instruction_text(str(root), str(root))
	assert text.index("永远用中文回复") > text.index("reply in english")


def test_include_cycle_dropped(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()
	a = root / "a.md"
	b = root / "b.md"
	a.write_text("@include b.md\nA", encoding="utf-8")
	b.write_text("@include a.md\nB", encoding="utf-8")
	(root / "XEYO.md").write_text("@include a.md\nROOT", encoding="utf-8")
	text = load_instruction_text(str(root), str(root))
	assert "ROOT" in text


def test_system_prompt_contains_instruction_and_keeps_custom(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text("永远用中文回复", encoding="utf-8")

	async def _run() -> str:
		parts = await fetch_system_prompt_parts(
			cwd=str(root),
			model="deepseek",
			tool_names=["echo"],
			custom_system_prompt="extra vendor hint",
		)
		return assemble_system_prompt(
			parts,
			custom_system_prompt="extra vendor hint",
			include_context_blocks=True,
		)

	text = asyncio.run(_run())
	assert "永远用中文回复" in text
	assert "你是 XEYO" in text
	assert "extra vendor hint" in text
	assert text.index("永远用中文回复") < text.index("extra vendor hint")
	assert text.count("你是 XEYO") == 1


def test_assembler_default_includes_instructions(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text("永远用中文回复", encoding="utf-8")

	async def _run() -> str:
		return await PromptAssembler().build_system(
			cwd=str(root),
			model="deepseek",
			tool_names=["echo"],
			custom_system_prompt="only custom would have swallowed this before",
		)

	text = asyncio.run(_run())
	assert "永远用中文回复" in text
	assert "你是 XEYO" in text
	assert text.count("你是 XEYO") == 1


def _proj(tmp_path: Path) -> Path:
	root = tmp_path / "proj"
	root.mkdir()
	return root


def test_cache_hit_returns_same_without_reread(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = _proj(tmp_path)
	(root / "XEYO.md").write_text("永远用中文回复", encoding="utf-8")
	clear_instruction_cache()
	t1 = load_instruction_text(str(root), str(root))
	t2 = load_instruction_text(str(root), str(root))
	assert t1 == t2
	assert "永远用中文回复" in t1


def test_cache_invalidates_on_file_change(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = _proj(tmp_path)
	f = root / "XEYO.md"
	f.write_text("v1 中文", encoding="utf-8")
	clear_instruction_cache()
	assert "v1 中文" in load_instruction_text(str(root), str(root))
	f.write_text("v2 中文", encoding="utf-8")
	# size 变化也触发签名失效，即使 mtime 落在同一纳秒
	assert "v2 中文" in load_instruction_text(str(root), str(root))


def test_cache_invalidates_on_new_rules_file(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = _proj(tmp_path)
	rules = root / ".xeyo" / "rules"
	rules.mkdir(parents=True)
	(root / "XEYO.md").write_text("base", encoding="utf-8")
	clear_instruction_cache()
	load_instruction_text(str(root), str(root))
	(rules / "extra.md").write_text("新增规则", encoding="utf-8")
	assert "新增规则" in load_instruction_text(str(root), str(root))


def test_cache_invalidates_on_include_target_change(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = _proj(tmp_path)
	(root / "inc.md").write_text("inc-v1", encoding="utf-8")
	(root / "XEYO.md").write_text("@include inc.md\nROOT", encoding="utf-8")
	clear_instruction_cache()
	t1 = load_instruction_text(str(root), str(root))
	assert "inc-v1" in t1
	(root / "inc.md").write_text("inc-v2", encoding="utf-8")
	t2 = load_instruction_text(str(root), str(root))
	assert "inc-v2" in t2


def test_clear_instruction_cache_forces_reload(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = _proj(tmp_path)
	f = root / "XEYO.md"
	f.write_text("a", encoding="utf-8")
	clear_instruction_cache()
	load_instruction_text(str(root), str(root))
	clear_instruction_cache()
	f.write_text("b", encoding="utf-8")
	assert "b" in load_instruction_text(str(root), str(root))


def test_paths_frontmatter_filters_by_cwd(tmp_path, monkeypatch):
	from memory.instruction import clear_instruction_cache, load_instruction_text

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	gui = root / "gui"
	gui.mkdir(parents=True)
	(root / "XEYO.md").write_text("core-always", encoding="utf-8")
	rules = root / ".xeyo" / "rules"
	rules.mkdir(parents=True)
	(rules / "gui-only.md").write_text(
		"---\npaths:\n  - gui/**\n---\ngui-scoped-rule\n",
		encoding="utf-8",
	)
	clear_instruction_cache()
	at_root = load_instruction_text(str(root), str(root))
	assert "core-always" in at_root
	assert "gui-scoped-rule" not in at_root
	clear_instruction_cache()
	at_gui = load_instruction_text(str(gui), str(root))
	assert "core-always" in at_gui
	assert "gui-scoped-rule" in at_gui


_EMPTY_TEMPLATE = (
	"# XEYO 项目说明（指针式，保持简短）\n\n"
	"## 常用命令\n- 测试：\n- 构建：\n\n"
	"## 指针（细则不内联；需要时用 Read / Skill）\n- 架构：\n"
)


def test_unfilled_template_is_not_injected(tmp_path, monkeypatch):
	"""未填过的自动模板不进注入（现场：外层与内层两份逐字相同的空模板）。

	信息量为零却造成「这里有项目指引」的错觉——模型为此白读 AGENTS.md/docs 找
	一份不存在的指引（sess_musrbw08_n9tly2 第 1 轮实录）。
	"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text(_EMPTY_TEMPLATE, encoding="utf-8")
	text = load_instruction_text(str(root), str(root))
	assert "常用命令" not in text
	assert "架构：" not in text


def test_partially_filled_template_is_injected(tmp_path, monkeypatch):
	"""反向断言：填了任意一条就不许滤（宁放勿滤）。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text(
		_EMPTY_TEMPLATE.replace("- 构建：", "- 构建：py -3.11 -m pytest"),
		encoding="utf-8",
	)
	text = load_instruction_text(str(root), str(root))
	assert "py -3.11 -m pytest" in text


def test_exact_generated_template_is_not_injected(tmp_path, monkeypatch):
	"""逐字等于自动模板（含 skills 指引行）也不注入——模板不是规范，填过才是。

	现场：python/XEYO.md 与 ensure_minimal_xeyo_md 落盘的模板逐字相同（无人填过），
	却被当规范注入。
	"""
	from memory.instruction import MINIMAL_TEMPLATE

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()
	(root / "XEYO.md").write_text(MINIMAL_TEMPLATE, encoding="utf-8")
	text = load_instruction_text(str(root), str(root))
	assert "常用命令" not in text
	assert "长流程（发版等）" not in text
