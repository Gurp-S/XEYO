"""Glob 空结果的范围说明必须与实际 argv 行为一致。

旧文案承诺 ".gitignore/.ignore … are respected"。实测（2026-09-25）恰好相反：
Glob 的检索面本身就是正向 ``--glob <pattern>``，而正向 glob 在 ripgrep 里压过
ignore 规则 ⇒ 被 .gitignore 挡掉的文件这里照样列出。说错范围比不说更坏：模型
会拿这句话去解释"Glob 看得到而 Grep 搜不到"，得出反的结论。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.glob_tool.glob_tool import GlobTool, clear_glob_cache


@pytest.fixture(autouse=True)
def _no_cache_between_cases():
	clear_glob_cache()
	yield
	clear_glob_cache()


@pytest.fixture
def work(tmp_path: Path) -> Path:
	(tmp_path / "keep.py").write_text("a = 1\n", encoding="utf-8")
	(tmp_path / "shadowed.py").write_text("b = 2\n", encoding="utf-8")
	(tmp_path / ".gitignore").write_text("shadowed.py\n", encoding="utf-8")
	(tmp_path / "agent_hidden.py").write_text("c = 3\n", encoding="utf-8")
	(tmp_path / ".agentignore").write_text("agent_hidden.py\n", encoding="utf-8")
	(nm := tmp_path / "node_modules").mkdir()
	(nm / "dep_copy.py").write_text("d = 4\n", encoding="utf-8")
	return tmp_path


async def _names(work: Path, pattern: str) -> list[str]:
	r = await GlobTool(cwd=str(work)).execute(
		{"pattern": pattern, "path": "."}, AbortController()
	)
	assert not r.is_error, r.content
	return [ln.strip() for ln in (r.content or "").splitlines() if ln.strip().endswith(".py")]


@pytest.mark.asyncio
async def test_ignore_files_do_not_hide_from_a_name_listing(work: Path) -> None:
	assert "shadowed.py" in await _names(work, "shadowed.py")
	# 对照组：同一次调用链没坏，普通文件也列得出
	assert "keep.py" in await _names(work, "keep.py")


@pytest.mark.asyncio
async def test_agentignore_and_heavy_dirs_are_actually_excluded(work: Path) -> None:
	names = await _names(work, "*.py")
	assert "agent_hidden.py" not in names, names
	assert not any("node_modules" in n for n in names), names
	assert "keep.py" in names and "shadowed.py" in names, names


@pytest.mark.asyncio
async def test_empty_result_states_the_real_scope(work: Path) -> None:
	r = await GlobTool(cwd=str(work)).execute(
		{"pattern": "zzz_absent_name.py", "path": "."}, AbortController()
	)
	text = r.content or ""
	assert "No files found" in text, text
	# 两条承诺都必须是真的：.agentignore 生效、ignore 文件不挡路
	assert ".agentignore names" in text, text
	assert "do not hide files from it" in text, text
