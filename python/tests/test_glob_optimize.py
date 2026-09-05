"""Glob 轻量优化：大小写重试、过宽摘要、folded、空结果引导、硬上限、TTL 缓存、统计、.agentignore。"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.glob_tool.glob_tool import (
	HARD_MAX_LIMIT,
	GlobTool,
	clear_glob_cache,
	fold_filenames,
	glob_stats,
	is_broad_pattern,
	reset_glob_stats,
)


@pytest.fixture(autouse=True)
def _fresh_cache_and_stats():
	"""缓存/统计是模块级状态，测试间必须清场。"""
	clear_glob_cache()
	reset_glob_stats()
	yield
	clear_glob_cache()
	reset_glob_stats()


def test_is_broad_pattern() -> None:
	assert is_broad_pattern("*")
	assert is_broad_pattern("**")
	assert is_broad_pattern("**/*")
	assert is_broad_pattern("./**/*")
	assert is_broad_pattern("**/*.*")
	# 目录前缀不豁免：文件名部分无名字线索仍是贪婪
	assert is_broad_pattern("gui/**/*")
	assert is_broad_pattern("gui/*")
	assert is_broad_pattern("gui/**")
	assert is_broad_pattern("src/components/**")
	assert not is_broad_pattern("**/*.py")
	assert not is_broad_pattern("gui/**/*.tsx")
	assert not is_broad_pattern("*Map*")
	assert not is_broad_pattern("src/**/*Button*.tsx")


def test_split_pattern_prefix() -> None:
	from tools.glob_tool.glob_tool import split_pattern_prefix

	assert split_pattern_prefix("gui/**/*") == ("gui", "**/*")
	assert split_pattern_prefix("src/components/**") == ("src/components", "**")
	assert split_pattern_prefix("**/*.py") == ("", "**/*.py")
	assert split_pattern_prefix("*Map*") == ("", "*Map*")
	# 前缀段含通配符则不拆
	assert split_pattern_prefix("gui-*/**/*.ts") == ("", "gui-*/**/*.ts")


def test_fold_filenames() -> None:
	files = [
		"gui/a.tsx",
		"gui/b.tsx",
		"gui/c.tsx",
		"gui/d.tsx",
		"python/x.py",
	]
	text = fold_filenames(files)
	assert "Folded view" in text
	assert "gui/" in text
	assert "4 files" in text
	assert "python/" in text


@pytest.mark.asyncio
async def test_broad_pattern_returns_dir_summary(tmp_path: Path) -> None:
	(tmp_path / "gui").mkdir()
	(tmp_path / "gui" / "App.tsx").write_text("x", encoding="utf-8")
	(tmp_path / "python").mkdir()
	(tmp_path / "python" / "a.py").write_text("y", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	assert not r.is_error
	assert "too broad" in r.content.lower() or "directory summary" in r.content.lower()
	assert "Do NOT" in r.content or "name pattern" in r.content.lower() or "Set path" in r.content
	# 软拒后禁止绕道 Bash 枚举
	assert "Bash" in r.content and "find/ls" in r.content
	# 不应是扁平文件清单占主导
	assert r.metadata and r.metadata.get("glob_kind") == "dir_summary"


@pytest.mark.asyncio
async def test_scoped_greedy_returns_prefix_summary(tmp_path: Path) -> None:
	"""`gui/**/*` 带目录前缀也按贪婪拦截，摘要限定到 gui/ 子树。"""
	gui = tmp_path / "gui"
	(gui / "src").mkdir(parents=True)
	(gui / "src" / "App.tsx").write_text("x", encoding="utf-8")
	(tmp_path / "python").mkdir()
	(tmp_path / "python" / "a.py").write_text("y", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "gui/**/*"}, AbortController())
	assert not r.is_error
	assert r.metadata and r.metadata.get("glob_kind") == "dir_summary"
	assert r.metadata.get("greedy_pattern") is True
	# 摘要限定在 gui/ 子树：不应出现 python/ 的内容，也不应列文件清单
	assert "python" not in r.content
	assert "App.tsx" not in r.content
	assert "gui/" in r.content  # scope 提示
	# stats：贪婪计数 +1
	assert glob_stats()["broad_patterns"] == 1


@pytest.mark.asyncio
async def test_case_insensitive_retry(tmp_path: Path) -> None:
	(tmp_path / "AgentMapPanel.tsx").write_text("export {}", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	# 小写 map 对大小写敏感应 miss，然后 iglob 命中
	r = await tool.execute({"pattern": "*map*"}, AbortController())
	assert not r.is_error
	assert "AgentMapPanel.tsx" in r.content
	assert "Case-insensitive" in r.content or (
		r.metadata and r.metadata.get("case_insensitive_retry")
	)


@pytest.mark.asyncio
async def test_empty_hint_discourages_starstar(tmp_path: Path) -> None:
	(tmp_path / "readme.md").write_text("hi", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "*NoSuchThingXYZ*"}, AbortController())
	assert not r.is_error
	assert "No files found" in r.content or "No matches" in r.content
	assert "**/*" in r.content  # 明确写不要用
	assert "Do NOT" in r.content or "do NOT" in r.content
	# 空结果同样禁止绕道 Bash 枚举
	assert "Bash find/ls" in r.content


@pytest.mark.asyncio
async def test_auto_fold_many_hits(tmp_path: Path) -> None:
	d = tmp_path / "pkg"
	d.mkdir()
	for i in range(45):
		(d / f"f{i}.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*.py", "detail": "auto"}, AbortController())
	assert not r.is_error
	assert "Folded view" in r.content
	assert r.metadata and r.metadata.get("glob_kind") == "folded"


@pytest.mark.asyncio
async def test_detail_paths_keeps_flat(tmp_path: Path) -> None:
	d = tmp_path / "pkg"
	d.mkdir()
	for i in range(45):
		(d / f"f{i}.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute(
		{"pattern": "**/*.py", "detail": "paths", "head_limit": 50},
		AbortController(),
	)
	assert not r.is_error
	assert "Folded view" not in r.content
	assert "f0.py" in r.content


# ====== head_limit 硬上限 120 ======


@pytest.mark.asyncio
async def test_hard_limit_clamped_and_too_many_message(tmp_path: Path) -> None:
	d = tmp_path / "pkg"
	d.mkdir()
	for i in range(130):
		(d / f"f{i:03d}.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute(
		{"pattern": "**/*.py", "detail": "paths", "head_limit": 500},
		AbortController(),
	)
	assert not r.is_error
	# 硬上限：传 500 也被压回 120
	assert r.metadata and r.metadata["num_files"] == HARD_MAX_LIMIT
	assert r.metadata["truncated"] is True
	assert r.metadata["total_matches"] == 130
	# 提示"匹配过多，请缩小 glob 表达式"
	assert "Too many matches" in r.content
	assert "narrow the glob pattern" in r.content


# ====== 60s TTL 缓存 ======


@pytest.mark.asyncio
async def test_ttl_cache_second_call_hits(tmp_path: Path) -> None:
	(tmp_path / "a.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r1 = await tool.execute({"pattern": "*.py", "detail": "paths"}, AbortController())
	assert r1.metadata and r1.metadata["cached"] is False
	# 相同查询：第二次直接命中缓存
	r2 = await tool.execute({"pattern": "*.py", "detail": "paths"}, AbortController())
	assert r2.metadata and r2.metadata["cached"] is True
	assert r2.content == r1.content
	# 不同 offset = 不同 key，不命中
	r3 = await tool.execute(
		{"pattern": "*.py", "detail": "paths", "offset": 1}, AbortController()
	)
	assert r3.metadata and r3.metadata["cached"] is False
	stats = glob_stats()
	assert stats["queries"] == 3
	assert stats["cache_hits"] == 1


@pytest.mark.asyncio
async def test_broad_summary_also_cached(tmp_path: Path) -> None:
	(tmp_path / "sub").mkdir()
	(tmp_path / "sub" / "x.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r1 = await tool.execute({"pattern": "**/*"}, AbortController())
	r2 = await tool.execute({"pattern": "**/*"}, AbortController())
	assert r1.metadata and r1.metadata.get("glob_kind") == "dir_summary"
	assert r2.metadata and r2.metadata["cached"] is True
	assert r1.content == r2.content


# ====== .agentignore 过滤 ======


@pytest.mark.asyncio
async def test_agentignore_filters_results(tmp_path: Path) -> None:
	(tmp_path / ".agentignore").write_text("*.log\nbuild_out/\n", encoding="utf-8")
	(tmp_path / "a.log").write_text("x", encoding="utf-8")
	(tmp_path / "b.py").write_text("x", encoding="utf-8")
	(tmp_path / "build_out").mkdir()
	(tmp_path / "build_out" / "c.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	# build_out/ 与 *.log 被 .agentignore 排除
	r = await tool.execute(
		{"pattern": "**/*.py", "detail": "paths"}, AbortController()
	)
	assert not r.is_error
	assert "b.py" in r.content
	assert "c.py" not in r.content
	assert "build_out" not in r.content
	# *.log 同样被排除（空结果）
	r2 = await tool.execute({"pattern": "*.log", "detail": "paths"}, AbortController())
	assert not r2.is_error
	assert "a.log" not in r2.content


# ====== 统计上报 ======


@pytest.mark.asyncio
async def test_glob_stats_counts_hits_and_greedy(tmp_path: Path) -> None:
	(tmp_path / "a.py").write_text("x", encoding="utf-8")
	(tmp_path / "b.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	await tool.execute({"pattern": "*.py", "detail": "paths"}, AbortController())
	await tool.execute({"pattern": "**/*"}, AbortController())  # 贪婪
	await tool.execute({"pattern": "*.py", "detail": "paths"}, AbortController())  # 缓存
	stats = glob_stats()
	assert stats["queries"] == 3
	assert stats["cache_hits"] == 1
	assert stats["broad_patterns"] == 1
	assert stats["files_returned"] == 4  # 两次 *.py 各交付 2 个文件（含缓存命中）
	assert stats["total_matches"] == 2  # 磁盘命中只计真实扫描
