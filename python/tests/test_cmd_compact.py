"""Bash cmd_compact：命令族识别 + stdout 语义压缩夹具测试。"""

from __future__ import annotations

from tools.bash_tool.cmd_compact import compact_command_output, detect_family


def _pad(text: str, min_chars: int = 4500) -> str:
	"""夹具需超过 MIN_CHARS 才会触发压缩。"""
	if len(text) >= min_chars:
		return text
	filler = ("ok line filler " * 20 + "\n") * ((min_chars - len(text)) // 40 + 1)
	return text + "\n" + filler


def test_detect_family() -> None:
	assert detect_family("pytest -q") == "pytest"
	assert detect_family("python -m pytest tests/") == "pytest"
	assert detect_family("npx vitest run") == "vitest"
	assert detect_family("npm test") == "vitest"
	assert detect_family("cargo test") == "cargo_test"
	assert detect_family("go test ./...") == "go_test"
	assert detect_family("npx tsc --noEmit") == "tsc"
	assert detect_family("ruff check .") == "lint"
	assert detect_family("git status") == "git"
	assert detect_family("cargo build") == "build"
	assert detect_family("echo hello") == "unknown"


def test_short_output_passthrough() -> None:
	raw = "short\n"
	assert compact_command_output("pytest", raw) == raw


def test_unknown_command_passthrough() -> None:
	raw = _pad("lots of text\n" * 200)
	assert compact_command_output("echo hi", raw) == raw


def test_pytest_keeps_failures_drops_passes() -> None:
	body = []
	for i in range(80):
		body.append(f"tests/test_a.py::test_{i} PASSED")
	body.append("=========================== FAILURES ===========================")
	body.append("_______________________ test_boom ________________________")
	body.append("    def test_boom():")
	body.append(">       assert False")
	body.append("E       AssertionError")
	body.append("Traceback (most recent call last):")
	body.append('  File "tests/test_a.py", line 3, in test_boom')
	body.append("    assert False")
	body.append("===================== 80 passed, 1 failed =====================")
	raw = _pad("\n".join(body))
	out = compact_command_output("pytest -q", raw)
	assert "[compacted pytest]" in out
	assert "1 failed" in out or "failed" in out
	assert "Traceback" in out or "AssertionError" in out
	assert "test_boom" in out
	# PASS 行不应成片保留
	assert out.count("PASSED") < 5


def test_tsc_groups_by_file() -> None:
	lines = []
	for i in range(30):
		lines.append(f"src/a.ts({i+1},1): error TS2322: Type 'string' is not assignable.")
	for i in range(10):
		lines.append(f"src/b.ts({i+1},2): error TS2304: Cannot find name 'x'.")
	raw = _pad("\n".join(lines))
	out = compact_command_output("npx tsc --noEmit", raw)
	assert "[compacted tsc]" in out
	assert "src/a.ts" in out
	assert "src/b.ts" in out
	assert "issues" in out


def test_git_status_compact() -> None:
	lines = ["## main...origin/main"]
	for i in range(100):
		lines.append(f" M file_{i}.py")
	for i in range(50):
		lines.append(f"?? new_{i}.txt")
	raw = _pad("\n".join(lines))
	out = compact_command_output("git status --porcelain -b", raw)
	assert "[compacted git]" in out
	assert "branch:" in out
	assert "dirty:" in out


def test_build_ok_tail_only() -> None:
	lines = [f"compiling module_{i}..." for i in range(200)]
	lines.append("Finished release [optimized] target(s) in 42.0s")
	raw = _pad("\n".join(lines))
	out = compact_command_output("cargo build --release", raw)
	assert "[compacted build]" in out
	assert "Finished release" in out
	assert out.count("compiling") < 20
