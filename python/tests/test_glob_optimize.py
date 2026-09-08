"""Glob 轻量优化：大小写重试、过宽摘要、folded、空结果引导、硬上限、TTL 缓存、统计、.agentignore。"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.fileio.read_state import ReadFileState
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


# ====== 新鲜度列（方案 D，默认开；XEYO_GLOB_SUMMARY_FRESH=0 显式关）======


@pytest.mark.asyncio
async def test_summary_fresh_default_on(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""默认（env 不设）：零 tracked 目录即显示 untracked + newest。"""
	monkeypatch.delenv("XEYO_GLOB_SUMMARY_FRESH", raising=False)
	import subprocess

	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
	(tmp_path / "docs").mkdir()
	(tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	assert "untracked" in r.content
	assert "newest" in r.content


@pytest.mark.asyncio
async def test_summary_fresh_flag_off_keeps_old_format(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""显式 =0：摘要与旧行为逐字节同构——无 newest 段。"""
	monkeypatch.setenv("XEYO_GLOB_SUMMARY_FRESH", "0")
	(tmp_path / "docs").mkdir()
	(tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	assert "newest" not in r.content
	assert "(1 files)" in r.content


@pytest.mark.asyncio
async def test_summary_fresh_shows_newest_date(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""方案 D：日期只在零 tracked 目录显示（untracked 标记亮出），tracked 权威区静默。"""
	monkeypatch.setenv("XEYO_GLOB_SUMMARY_FRESH", "1")
	import os
	import subprocess
	import time as _time

	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
	docs = tmp_path / "docs"
	docs.mkdir()
	(docs / "old-design.md").write_text("x", encoding="utf-8")
	old_ts = _time.mktime(_time.strptime("2026-01-01", "%Y-%m-%d"))
	os.utime(docs / "old-design.md", (old_ts, old_ts))
	gui = tmp_path / "gui"
	gui.mkdir()
	(gui / "new.tsx").write_text("x", encoding="utf-8")  # mtime = 现在
	# gui 收编（git add 进 index 即 tracked，无需 commit）；docs 保持未收编
	subprocess.run(["git", "add", "gui/new.tsx"], cwd=tmp_path, check=True, capture_output=True)
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	lines = r.content.splitlines()
	gui_line = next(ln for ln in lines if ln.startswith("gui/"))
	assert gui_line == "gui/  (1 files)"  # 权威区静默：无 untracked、无日期
	docs_line = next(ln for ln in lines if ln.startswith("docs/"))
	assert docs_line == "docs/  (1 files · untracked · newest 2026-01-01)"  # 草稿区：标记+日期


@pytest.mark.asyncio
async def test_summary_fresh_count_sort_unchanged(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""开关开：排序语义不变——仍按文件数降序，新鲜度只是列。"""
	monkeypatch.setenv("XEYO_GLOB_SUMMARY_FRESH", "1")
	import subprocess

	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
	big = tmp_path / "big"
	big.mkdir()
	for i in range(5):
		(big / f"f{i}.py").write_text("x", encoding="utf-8")
	small = tmp_path / "small"
	small.mkdir()
	(small / "a.py").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	assert r.content.index("big/") < r.content.index("small/")
	assert "untracked · newest" in r.content


@pytest.mark.asyncio
async def test_summary_fresh_stat_failure_graceful(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""stat 全失败：untracked 标记仍在（分区事实），仅 newest 段如实省略。"""
	monkeypatch.setenv("XEYO_GLOB_SUMMARY_FRESH", "1")
	import subprocess

	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
	(tmp_path / "docs").mkdir()
	(tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	import tools.glob_tool.glob_tool as gt

	orig = gt._stat_mtime_safe
	gt._stat_mtime_safe = lambda p: 0.0  # 模拟 stat 全失败
	try:
		r = await tool.execute({"pattern": "**/*"}, AbortController())
	finally:
		gt._stat_mtime_safe = orig
	assert not r.is_error
	assert "docs/  (1 files · untracked)" in r.content
	assert "newest" not in r.content


@pytest.mark.asyncio
async def test_summary_fresh_non_git_silent(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""非 git 工作区：无人的策展事实 → 日期与标记整体静默（旧格式）。"""
	monkeypatch.setenv("XEYO_GLOB_SUMMARY_FRESH", "1")
	(tmp_path / "docs").mkdir()
	(tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	assert "untracked" not in r.content
	assert "newest" not in r.content
	assert "(1 files)" in r.content


@pytest.mark.asyncio
async def test_summary_fresh_mixed_dir_untracked_count(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""B2（2026-09-09 改语义）：混合目录只报 untracked 计数——纯 git 状态事实，
	不带日期（权威区 mtime 是噪声，B2 不重蹈覆辙）。"""
	monkeypatch.setenv("XEYO_GLOB_SUMMARY_FRESH", "1")
	import subprocess

	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
	mixed = tmp_path / "mixed"
	mixed.mkdir()
	(mixed / "a.py").write_text("x", encoding="utf-8")
	(mixed / "b.py").write_text("x", encoding="utf-8")
	subprocess.run(["git", "add", "mixed/a.py"], cwd=tmp_path, check=True, capture_output=True)
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	mixed_line = next(ln for ln in r.content.splitlines() if ln.startswith("mixed/"))
	assert mixed_line == "mixed/  (2 files · 1 untracked)"


@pytest.mark.asyncio
async def test_summary_fresh_fully_tracked_dir_silent(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""全 tracked 目录 → 静默（无任何列）。"""
	monkeypatch.setenv("XEYO_GLOB_SUMMARY_FRESH", "1")
	import subprocess

	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
	full = tmp_path / "full"
	full.mkdir()
	(full / "a.py").write_text("x", encoding="utf-8")
	(full / "b.py").write_text("x", encoding="utf-8")
	subprocess.run(["git", "add", "full/"], cwd=tmp_path, check=True, capture_output=True)
	tool = GlobTool(cwd=str(tmp_path))
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	full_line = next(ln for ln in r.content.splitlines() if ln.startswith("full/"))
	assert full_line == "full/  (2 files)"


# ====== A1（2026-09-09）：Write/Edit 落盘后失效 Glob 缓存 ======


@pytest.mark.asyncio
async def test_write_invalidates_glob_cache(tmp_path: Path) -> None:
	"""A1：写新文件后 Glob 立即可见——此前 clear_glob_cache 零调用者，
	60s TTL 内缓存命中会藏住新文件（"存在但找不到"幽灵）。"""
	from tools.file_write_tool.file_write_tool import FileWriteTool

	tool = GlobTool(cwd=str(tmp_path))
	await tool.execute({"pattern": "**/*"}, AbortController())  # 预热缓存
	writer = FileWriteTool(cwd=str(tmp_path))
	w = await writer.execute(
		{"file_path": str(tmp_path / "subdir2" / "newfile.txt"), "content": "x\n"},
		AbortController(),
	)
	assert not w.is_error
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	# 缓存已失效 → 重扫 → 新目录行出现（命中旧缓存则 subdir2 不可能存在）
	assert r.metadata.get("cached") is not True
	assert "subdir2/" in r.content


@pytest.mark.asyncio
async def test_edit_invalidates_glob_cache(tmp_path: Path) -> None:
	"""A1：Edit 改动后 Glob 缓存同样失效（Edit 有自己的 _persist 漏斗）。"""
	from tools.file_edit_tool.file_edit_tool import FileEditTool
	from tools.file_read_tool.file_read_tool import FileReadTool

	target = tmp_path / "code.py"
	target.write_text("alpha = 1\n", encoding="utf-8")
	state = ReadFileState()
	reader = FileReadTool(cwd=str(tmp_path))
	reader.set_read_file_state(state)
	editor = FileEditTool(cwd=str(tmp_path))
	editor.set_read_file_state(state)
	tool = GlobTool(cwd=str(tmp_path))
	await tool.execute({"pattern": "**/*"}, AbortController())  # 预热缓存
	await reader.execute({"file_path": str(target)}, AbortController())
	e = await editor.execute(
		{
			"file_path": str(target),
			"old_string": "alpha = 1",
			"new_string": "alpha = 1\nbeta_marker = 2",
		},
		AbortController(),
	)
	assert not e.is_error
	r = await tool.execute({"pattern": "**/*"}, AbortController())
	# 缓存已失效会重扫——折叠视图里能见到新内容（文件名不变，验证缓存
	# 失效用 mtime 侧证：清空缓存重扫 = 第二次调用不报 cached）
	assert r.metadata.get("cached") is not True or "beta_marker" in r.content


# ====== Bash 门控失效（A1 扩展，2026-09-09）：写类 Bash 命令清搜索缓存 ======


def test_bash_classifier_readonly_vs_mutating() -> None:
	"""fail-closed 门控：白名单全命中→不清;显式写/解释器/未知/命令替换→清。"""
	from tools.bash_tool.bash_tool import _command_may_mutate_workspace

	mutate = _command_may_mutate_workspace
	# 保留缓存（自信只读）
	assert mutate("rg foo src/") is False
	assert mutate("git status") is False
	assert mutate("git log --oneline -5") is False
	assert mutate("ls -la") is False
	assert mutate("cat a.txt | wc -l") is False
	# 清缓存（显式写）
	assert mutate("echo hi > out.txt") is True
	assert mutate("sed -i 's/a/b/' f.py") is True
	assert mutate("npm install") is True
	assert mutate("git commit -m x") is True
	assert mutate("git checkout main") is True
	# 清缓存（解释器/未知/替换/多行）
	assert mutate("python script.py") is True
	assert mutate("pytest -q") is True
	assert mutate("echo $(python write.py)") is True
	assert mutate("foo --bar") is True
	assert mutate("ls\nrm x") is True


@pytest.mark.asyncio
async def test_bash_write_invalidates_glob_cache(tmp_path: Path) -> None:
	"""集成：Bash 写文件后 Glob 立即可见（此前 60s 幽灵窗口）。"""
	from tools.bash_tool.bash_tool import BashTool

	glob_tool = GlobTool(cwd=str(tmp_path))
	await glob_tool.execute({"pattern": "**/*"}, AbortController())  # 预热缓存
	bash = BashTool(cwd=str(tmp_path))
	r = await bash.execute(
		{"command": f"mkdir {tmp_path / 'bg_dir'}; echo hi > {tmp_path / 'bg_dir' / 'x.txt'}"},
		AbortController(),
	)
	assert not r.is_error
	r2 = await glob_tool.execute({"pattern": "**/*"}, AbortController())
	assert r2.metadata.get("cached") is not True
	assert "bg_dir/" in r2.content


@pytest.mark.asyncio
async def test_bash_readonly_keeps_glob_cache(tmp_path: Path) -> None:
	"""只读 Bash 命令不失效缓存——下次 Glob 仍命中（省重算）。"""
	from tools.bash_tool.bash_tool import BashTool

	(tmp_path / "seed.txt").write_text("x", encoding="utf-8")
	glob_tool = GlobTool(cwd=str(tmp_path))
	await glob_tool.execute({"pattern": "**/*"}, AbortController())  # 预热
	bash = BashTool(cwd=str(tmp_path))
	r = await bash.execute({"command": "ls"}, AbortController())
	assert not r.is_error
	r2 = await glob_tool.execute({"pattern": "**/*"}, AbortController())
	assert r2.metadata.get("cached") is True
