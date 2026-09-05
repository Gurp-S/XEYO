"""一阶段轻量机制收益对比（离线，无 API 调用）。

对比融入前 vs 融入后的 token（chars//4）与工具轮次，口径对齐
bench_codeindex_benefit.py。

用法：cd python && python scripts/bench_phase1_benefit.py
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from engine.abort import AbortController  # noqa: E402
from permissions.policy import set_code_compact, set_code_mode  # noqa: E402
from prompt.pre_llm_inject import (  # noqa: E402
	T_NOW_EXTRA_BUDGET,
	code_compact_block,
)
from tools.bash_tool.cmd_compact import compact_command_output  # noqa: E402
from tools.file_read_tool.file_read_tool import FileReadTool  # noqa: E402
from tools.git_tool import GitTool  # noqa: E402
from tools.grep_tool.grep_tool import GrepTool  # noqa: E402


def tokens(text: str) -> int:
	return max(1, len(text) // 4) if text else 0


def _pad_fixture(lines: list[str], min_chars: int = 4500) -> str:
	text = "\n".join(lines)
	if len(text) >= min_chars:
		return text
	filler = ("ok filler line\n" * ((min_chars - len(text)) // 15 + 1))
	return text + "\n" + filler


def bench_rtk() -> list[tuple[str, int, int, float]]:
	rows: list[tuple[str, int, int, float]] = []

	# pytest：大量 PASSED + 1 FAILURE
	body = [f"tests/test_a.py::test_{i} PASSED" for i in range(100)]
	body += [
		"=========================== FAILURES ===========================",
		"_______________________ test_boom ________________________",
		"Traceback (most recent call last):",
		'  File "tests/test_a.py", line 3, in test_boom',
		"    assert False",
		"E       AssertionError",
		"===================== 100 passed, 1 failed =====================",
	]
	raw = _pad_fixture(body)
	after = compact_command_output("pytest -q", raw)
	assert "Traceback" in after or "AssertionError" in after
	t0, t1 = tokens(raw), tokens(after)
	rows.append(("pytest", t0, t1, 1 - t1 / t0 if t0 else 0.0))

	# git log
	log_lines = [f"{hex(i)[2:].zfill(7)} 2026-01-01 subject line {i}" for i in range(200)]
	raw = _pad_fixture(log_lines)
	after = compact_command_output("git log -n 200", raw)
	t0, t1 = tokens(raw), tokens(after)
	rows.append(("git_log", t0, t1, 1 - t1 / t0 if t0 else 0.0))

	# tsc
	tsc = [
		f"src/a.ts({i},1): error TS2322: Type mismatch {i}" for i in range(80)
	]
	raw = _pad_fixture(tsc)
	after = compact_command_output("npx tsc --noEmit", raw)
	t0, t1 = tokens(raw), tokens(after)
	rows.append(("tsc", t0, t1, 1 - t1 / t0 if t0 else 0.0))

	return rows


async def bench_pack() -> tuple[int, int, int, int, bool]:
	"""前：symbol + grep + read helpers；后：pack=true。返回 (calls_before, tok_before, calls_after, tok_after, ok)."""
	target = REPO_ROOT / "python" / "tools" / "bash_tool" / "cmd_compact.py"
	symbol = "compact_command_output"
	reader = FileReadTool(cwd=str(REPO_ROOT))
	greper = GrepTool(cwd=str(REPO_ROOT))

	# before
	r1 = await reader.execute(
		{"file_path": str(target), "symbol": symbol}, AbortController()
	)
	r2 = await greper.execute(
		{
			"pattern": "detect_family|_compact_",
			"path": str(target.parent),
			"output_mode": "symbols",
			"head_limit": 20,
		},
		AbortController(),
	)
	r3 = await reader.execute(
		{"file_path": str(target), "symbol": "detect_family"}, AbortController()
	)
	before_calls = 3
	before_tok = tokens(r1.content) + tokens(r2.content) + tokens(r3.content)

	# after
	rp = await reader.execute(
		{"file_path": str(target), "symbol": symbol, "pack": True},
		AbortController(),
	)
	after_calls = 1
	after_tok = tokens(rp.content)
	ok = (not rp.is_error) and ("compact_command_output" in rp.content or "## body" in rp.content)
	return before_calls, before_tok, after_calls, after_tok, ok


async def bench_git_touched() -> tuple[int, int, int, int, bool]:
	if shutil.which("git") is None:
		return 0, 0, 0, 0, False
	with tempfile.TemporaryDirectory() as td:
		root = Path(td)
		subprocess.run(["git", "init", "-q"], cwd=root, check=True)
		subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=root, check=True)
		subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
		mod = root / "mod.py"
		mod.write_text(
			"def keep():\n\treturn 1\n\n\ndef target():\n\treturn 2\n\n\ndef other():\n\treturn 3\n",
			encoding="utf-8",
		)
		subprocess.run(["git", "add", "."], cwd=root, check=True)
		subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
		mod.write_text(
			"def keep():\n\treturn 1\n\n\ndef target():\n\treturn 99\n\n\ndef other():\n\treturn 3\n",
			encoding="utf-8",
		)

		tool = GitTool(cwd=str(root))
		# 融入前：裸 summary（无 touched）+ 全量 diff + Grep symbols
		s0 = await tool.execute({"action": "summary"}, AbortController())
		old_summary = s0.content.split("touched:")[0].rstrip()
		diff_proc = subprocess.run(
			["git", "diff", "HEAD"],
			cwd=root,
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="replace",
			check=False,
		)
		g = GrepTool(cwd=str(root))
		gs = await g.execute(
			{"pattern": "def ", "path": str(root), "output_mode": "symbols", "head_limit": 20},
			AbortController(),
		)
		before_tok = tokens(old_summary) + tokens(diff_proc.stdout or "") + tokens(gs.content)
		before_calls = 3

		# 融入后：仅 summary（含 touched）
		after_tok = tokens(s0.content)
		after_calls = 1
		ok = "touched:" in s0.content and "target" in s0.content
		return before_calls, before_tok, after_calls, after_tok, ok


def bench_code_compact() -> list[tuple[str, int]]:
	rows: list[tuple[str, int]] = []
	set_code_compact(False)
	rows.append(("off", tokens(code_compact_block() or "")))
	for mode in ("lite", "full", "ultra"):
		set_code_compact(True)
		set_code_mode(mode)
		rows.append((mode, tokens(code_compact_block())))
	set_code_compact(False)
	set_code_mode(None)
	return rows


def main() -> None:
	print("=== Phase-1 benefit (before vs after) ===\n")

	print("1) rtk / Bash stdout")
	print(f"{'family':<12} {'before':>8} {'after':>8} {'save':>8}")
	for fam, b, a, save in bench_rtk():
		print(f"{fam:<12} {b:8d} {a:8d} {save:7.1%}")

	print("\n2) Read pack")
	bc, bt, ac, at, ok = asyncio.run(bench_pack())
	print(f"{'metric':<12} {'before':>8} {'after':>8}")
	print(f"{'calls':<12} {bc:8d} {ac:8d}")
	print(f"{'tokens':<12} {bt:8d} {at:8d}")
	print(f"accuracy_ok={ok}  save_tokens={(1 - at / bt) if bt else 0:.1%}")

	print("\n3) Git touched")
	bc, bt, ac, at, ok = asyncio.run(bench_git_touched())
	print(f"{'metric':<12} {'before':>8} {'after':>8}")
	print(f"{'calls':<12} {bc:8d} {ac:8d}")
	print(f"{'tokens':<12} {bt:8d} {at:8d}")
	print(f"hit_target={ok}  save_tokens={(1 - at / bt) if bt else 0:.1%}")

	print("\n4) code_compact inject overhead")
	print(f"{'mode':<8} {'tokens':>8}  budget={T_NOW_EXTRA_BUDGET}")
	for mode, tok in bench_code_compact():
		print(f"{mode:<8} {tok:8d}")

	print("\nDone.")


if __name__ == "__main__":
	main()
