# -*- coding: utf-8 -*-
"""容器工作面接线 + T_now/窗口修正的纯函数契约（2026-09-16）。

覆盖本轮改动的**可判定内核**（不发网络、不起容器）：
- ``container_fs.to_container_path`` / ``_host_shaped_to_container`` 路径归一；
- ``grep_tool.rg_fallback`` 的 rg→grep 映射（含两处"静默改语义"陷阱）；
- ``memory.runtime.reasoning_tokens_in_context`` 思考态体积估算；
- ``bash_tool.promote_threshold_for`` 晋升阈值与命令超时联动。

容器**真实行为**另行用真容器端到端验证过（见改动说明），此处只锁纯函数。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---- 路径归一：坐标系分裂的最隐蔽一环 -------------------------------------

def test_to_container_path_strips_windows_drive() -> None:
	from tools.container_fs import to_container_path

	assert to_container_path("/app/src") == "/app/src"
	assert to_container_path(r"\app\src") == "/app/src"
	if os.name == "nt":
		# 工具层 abspath 的产物：D:\app\src → /app/src（否则容器里必然找不到）
		assert to_container_path(r"D:\app\src") == "/app/src"
		assert to_container_path("D:/app/x.py") == "/app/x.py"


def test_host_shaped_to_container_never_mangles_regex() -> None:
	"""只认驱动器绝对路径：正则里的 \\b / \\d 必须原样保留。"""
	from tools.container_fs import _host_shaped_to_container as fix

	if os.name == "nt":
		assert fix(r"D:\app\src") == "/app/src"
	assert fix(r"\bPASSWORD\b") == r"\bPASSWORD\b"
	assert fix(r"\bfoo\b.*\d+") == r"\bfoo\b.*\d+"
	assert fix("a\\b") == "a\\b"


# ---- rg → grep 映射 --------------------------------------------------------

def _flags(**kw):
	from tools.grep_tool.grep_tool import GrepInput, build_rg_args
	from tools.grep_tool.rg_fallback import _map_to_grep_flags

	return _map_to_grep_flags(build_rg_args(GrepInput(**kw)))


def test_rg_fallback_maps_three_output_modes() -> None:
	assert "-l" in _flags(pattern="x", output_mode="files_with_matches")
	assert "-c" in _flags(pattern="x", output_mode="count")
	assert "-n" in _flags(pattern="x", output_mode="content", show_line_numbers=True)
	assert "-i" in _flags(pattern="x", output_mode="content", case_insensitive=True)


def test_rg_fallback_rejects_unmappable() -> None:
	"""映射不出逐字等价语义 → None（宁可不给结果，也不给改过语义的结果）。"""
	from tools.grep_tool.grep_tool import GrepInput, build_rg_args
	from tools.grep_tool.rg_fallback import grep_argv_from_rg

	assert grep_argv_from_rg(build_rg_args(GrepInput(pattern="x", multiline=True)), "/a") is None
	assert grep_argv_from_rg(build_rg_args(GrepInput(pattern="x", type="py")), "/a") is None


def test_rg_fallback_excludes_cover_files_and_dirs() -> None:
	"""排除项必须同时排文件与目录：只发 --exclude-dir 会让密钥文件重新出现。"""
	flags = _flags(pattern="x", output_mode="content")
	assert "--exclude=credentials.json" in flags
	assert "--exclude-dir=credentials.json" in flags
	assert "--exclude=*.pem" in flags


def test_rg_fallback_rejects_path_positive_glob() -> None:
	"""含 / 的正向 glob 在 GNU grep 里没有等价物（--include 只匹配 basename）。"""
	from tools.grep_tool.grep_tool import GrepInput, build_rg_args
	from tools.grep_tool.rg_fallback import grep_argv_from_rg

	assert grep_argv_from_rg(build_rg_args(GrepInput(pattern="x", glob="src/*.py")), "/a") is None
	# 纯 basename glob 可以映射
	assert grep_argv_from_rg(build_rg_args(GrepInput(pattern="x", glob="*.py")), "/a") is not None


def test_pipeline_used_only_when_include_present() -> None:
	"""GNU grep 里 --exclude 会让 --include 失效 → 有 include 必须走 find 管道。"""
	from tools.grep_tool.grep_tool import GrepInput, build_rg_args
	from tools.grep_tool.rg_fallback import pipeline_from_rg

	with_inc = pipeline_from_rg(build_rg_args(GrepInput(pattern="x", glob="*.py")), "/app")
	without = pipeline_from_rg(build_rg_args(GrepInput(pattern="x")), "/app")
	assert without is None  # 无 include → 直接 grep，少一层 find
	assert with_inc is not None and with_inc.startswith("find ")
	assert " -print0 | xargs -0 -r " in with_inc
	assert " -name '*.py'" in with_inc
	# find 的转义括号必须带空格（否则报 "paths must precede expression"）
	assert " \\( " in with_inc and " \\)" in with_inc


# ---- 思考态体积估算（水位表补盲） ------------------------------------------

def test_reasoning_tokens_in_context_shapes() -> None:
	from memory.runtime import reasoning_tokens_in_context as R

	# 字段式（OpenAI 化之后）
	assert R([{"role": "assistant", "reasoning_content": "y" * 8000}]) == 2000
	# 块式（内部 Message 的 content 数组）
	assert R([{"role": "assistant", "content": [{"type": "reasoning", "text": "x" * 4000}]}]) == 1000
	# 无 reasoning / 坏结构 → 0（fail-open，不改变既有判定）
	assert R([{"role": "user", "content": "hi"}]) == 0
	assert R(object()) == 0


# ---- 工具调用上限 / 晋升阈值 ------------------------------------------------

def test_promote_threshold_scales_below_command_timeout(monkeypatch) -> None:
	from tools.bash_tool.bash_tool import promote_threshold_for

	monkeypatch.delenv("XEYO_BASH_PROMOTE_MS", raising=False)
	assert promote_threshold_for("echo hi", 120_000) == 96_000
	assert promote_threshold_for("make -j4", 300_000) == 240_000
	assert promote_threshold_for("cargo build", 420_000) == 300_000
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "0")
	assert promote_threshold_for("make -j4", 300_000) == 0


# ---- 最小工作面 ------------------------------------------------------------

def test_minimal_surface_contents(monkeypatch) -> None:
	from tools.catalog import MINIMAL_SURFACE_TOOLS

	for name in ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent"):
		assert name in MINIMAL_SURFACE_TOOLS
	# job 三件套是后台晋升的配套（缺了模型拿到 job_id 无法取回输出）
	for name in ("job_output", "job_list", "job_kill"):
		assert name in MINIMAL_SURFACE_TOOLS


def test_deepseek_window_is_not_64k(monkeypatch) -> None:
	"""回归守卫：65536 是已确认缺陷值；窗口塌缩会把压缩触发点压到 ~1.1 万 token。"""
	monkeypatch.delenv("XEYO_CONTEXT_LIMIT", raising=False)
	from engine.query_engine import CONSERVATIVE_CONTEXT_WINDOW, _default_context_limit

	assert _default_context_limit("deepseek", "deepseek-flash") == 1_000_000
	assert _default_context_limit("deepseek", "deepseek-未知") == CONSERVATIVE_CONTEXT_WINDOW
	assert CONSERVATIVE_CONTEXT_WINDOW > 65_536
