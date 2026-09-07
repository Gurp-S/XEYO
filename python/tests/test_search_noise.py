import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tools.fileio.excludes import excluded_dir_globs, search_excluded_dirs
from tools.glob_tool.glob_tool import GlobTool, GlobOutput
from tools.grep_tool.grep_tool import GrepInput, GrepOutput, GrepTool, build_rg_args, run_ripgrep


# ====== 排除目录配置 ======

def test_search_excludes_cover_vcs_and_heavy():
	dirs = search_excluded_dirs()
	assert ".git" in dirs and ".svn" in dirs
	assert "node_modules" in dirs
	assert ".pnpm-store" in dirs
	assert "__pycache__" in dirs
	# 构建产物
	assert "dist" in dirs and "target" in dirs


def test_search_excludes_env_append(monkeypatch):
	monkeypatch.setenv("XEYO_SEARCH_EXCLUDE", "vendor,custom_cache")
	dirs = search_excluded_dirs()
	assert "vendor" in dirs and "custom_cache" in dirs and "node_modules" in dirs
	# 去重且不破坏默认
	monkeypatch.setenv("XEYO_SEARCH_EXCLUDE", "node_modules,extra")
	dirs2 = search_excluded_dirs()
	assert dirs2.count("node_modules") == 1 and "extra" in dirs2


def test_excluded_dir_globs_shape():
	globs = excluded_dir_globs()
	# 参数形如 [("--glob","!dir"), ...]
	assert globs[0] == "--glob"
	assert globs[1].startswith("!")
	flat = set(globs[1::2])
	assert "!node_modules" in flat and "!.git" in flat


# ====== Grep 参数包含排除项 ======

def test_build_rg_args_includes_excludes():
	args = build_rg_args(GrepInput(pattern="hello", output_mode="content"))
	assert "--glob" in args
	assert "!node_modules" in args and "!.git" in args
	# 排除项不与用户 glob 冲突；用户 pattern 保留
	assert "hello" in args
	# 没把用户传入的 type/glob 冲掉
	assert "--max-columns" in args


# ====== Grep 结果提示 ======

def test_grep_empty_content_gets_case_tip():
	out = GrepOutput(mode="content", num_files=0, content="", num_lines=0)
	text = GrepTool.map_tool_result_to_content(out)
	assert "No matches found" in text
	assert "case-insensitive" in text and "-i" in text


def test_grep_files_with_matches_empty_gets_tip():
	out = GrepOutput(mode="files_with_matches", num_files=0, filenames=[])
	text = GrepTool.map_tool_result_to_content(out)
	assert "No files found" in text
	assert "case-insensitive" in text


def test_grep_files_with_matches_few_gets_content_tip():
	out = GrepOutput(mode="files_with_matches", num_files=1, filenames=["gui/src/lib/a.ts"])
	text = GrepTool.map_tool_result_to_content(out)
	assert 'output_mode="content"' in text


def test_grep_files_with_matches_many_no_tip():
	out = GrepOutput(
		mode="files_with_matches",
		num_files=3,
		filenames=["a.ts", "b.ts", "c.ts"],
	)
	text = GrepTool.map_tool_result_to_content(out)
	assert 'output_mode="content"' not in text


def test_grep_content_nonempty_no_case_tip():
	out = GrepOutput(mode="content", num_files=0, content="a.ts:1:hello", num_lines=1)
	text = GrepTool.map_tool_result_to_content(out)
	assert "case-insensitive" not in text


# ====== Glob 空结果提示 ======

def test_glob_empty_gets_tip():
	out = GlobOutput(filenames=[], duration_ms=1.0, num_files=0, truncated=False)
	text = GlobTool.map_tool_result_to_content(out)
	assert "No files found" in text
	assert "node_modules" in text


# ====== 集成：ripgrep 实际排除 node_modules ======

@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_ripgrep_excludes_node_modules(tmp_path):
	needle = "XEYO_NEEDLE_42"
	(root := tmp_path / "ws").mkdir()
	(root / "src").mkdir()
	(root / "node_modules" / "some-dep").mkdir(parents=True)
	(root / "src" / "a.py").write_text(f"x = '{needle}'", encoding="utf-8")
	(root / "node_modules" / "some-dep" / "pkg.py").write_text(
		f"y = '{needle}'", encoding="utf-8"
	)

	args = build_rg_args(GrepInput(pattern=needle, output_mode="files_with_matches"))
	hits = run_ripgrep(args, str(root))

	rel = {os.path.relpath(h, str(root)).replace("\\", "/") for h in hits}
	assert "src/a.py" in rel
	assert not any(("node_modules" in r) for r in rel)


# ====== abort 杀死 rg 子进程 ======

@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_abort_returns_immediately_without_running_ripgrep(tmp_path):
	import time as _time

	from engine.abort import AbortController
	from tools.fileio.rg_subprocess import run_ripgrep_lines

	abort = AbortController()
	abort.abort()
	started = _time.monotonic()
	lines = run_ripgrep_lines(
		["rg", "--files", "."],
		cwd=str(tmp_path),
		timeout_seconds=10.0,
		abort=abort,
	)
	assert lines == []
	assert _time.monotonic() - started < 5.0


# ====== 长行 content 预览（替代 [Omitted long matching line]）======

@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_content_mode_previews_long_lines(tmp_path):
	from tools.grep_tool.grep_tool import GrepTool

	f = tmp_path / "long.txt"
	f.write_text(("a" * 200) + "XEYO_LONG_NEEDLE" + ("b" * 900), encoding="utf-8")

	inp = GrepInput(pattern="XEYO_LONG_NEEDLE", path=str(tmp_path), output_mode="content")
	out = GrepTool.map_tool_result_to_content(GrepTool.call(GrepTool(), inp))
	assert "[Omitted long matching line]" not in out
	assert "XEYO_LONG_NEEDLE" in out


if __name__ == "__main__":
	import pytest

	raise SystemExit(pytest.main([__file__, "-q"]))
