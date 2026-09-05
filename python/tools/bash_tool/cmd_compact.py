"""Bash stdout 语义压缩（rtk 机制自研移植）。

在 truncate_for_model 之前跑：识别命令族 → 压噪声保信号。
未识别 / 输出过短 → 原样；失败路径绝不丢掉 traceback/error。
"""

from __future__ import annotations

import re
from typing import Callable

# 短于该字符数不压（避免对已经很短的输出再包一层）
_MIN_CHARS = 4_000
_TAIL_BUILD_LINES = 12
_MAX_GROUPED_FILES = 40

_Family = str  # pytest | vitest | cargo_test | go_test | tsc | lint | git | build | unknown

_CMD_PATTERNS: list[tuple[re.Pattern[str], _Family]] = [
	(re.compile(r"(?i)(?:^|[\s;&|])(?:python(?:\d+(?:\.\d+)?)?\s+-m\s+)?pytest\b"), "pytest"),
	(re.compile(r"(?i)(?:^|[\s;&|])(?:npx\s+|pnpm\s+|yarn\s+|npm\s+(?:exec\s+)?)?vitest\b"), "vitest"),
	(re.compile(r"(?i)(?:^|[\s;&|])(?:npx\s+|pnpm\s+|yarn\s+)?jest\b"), "vitest"),
	(re.compile(r"(?i)(?:npm|pnpm|yarn)\s+test\b"), "vitest"),
	(re.compile(r"(?i)(?:^|[\s;&|])cargo\s+test\b"), "cargo_test"),
	(re.compile(r"(?i)(?:^|[\s;&|])go\s+test\b"), "go_test"),
	(re.compile(r"(?i)(?:^|[\s;&|])(?:npx\s+)?tsc\b"), "tsc"),
	(re.compile(r"(?i)(?:^|[\s;&|])(?:npx\s+|pnpm\s+|yarn\s+)?(?:eslint|ruff|biome)\b"), "lint"),
	(re.compile(r"(?i)(?:^|[\s;&|])git\s+(?:status|log|diff)\b"), "git"),
	(re.compile(r"(?i)(?:^|[\s;&|])cargo\s+(?:build|clippy)\b"), "build"),
	(re.compile(r"(?i)(?:npm|pnpm|yarn)\s+run\s+build\b"), "build"),
]

_PYTEST_FAIL_START = re.compile(
	r"^(={5,}\s*FAILURES\s*={5,}|_{3,}\s+\S+.*_{3,}|E\s+|FAILED\s+\S+)",
	re.MULTILINE,
)
_PYTEST_SUMMARY = re.compile(
	r"=+\s*((?:\d+\s+\w+,?\s*)+)\s*=+",
)
_PASSED_LINE = re.compile(r"(?i)^\s*(?:PASSED|PASS|ok)\b")
_FAILED_LINE = re.compile(r"(?i)^\s*(?:FAILED|FAIL|ERROR)\b")
_TRACE_HINT = re.compile(r"(?i)(traceback|exception|error:|FAILED|FAILURES)")


def detect_family(command: str) -> _Family:
	cmd = (command or "").strip()
	if not cmd:
		return "unknown"
	for pat, fam in _CMD_PATTERNS:
		if pat.search(cmd):
			return fam
	return "unknown"


def compact_command_output(command: str, stdout: str) -> str:
	"""返回给模型看的压缩文本；不改原命令、不落盘。"""
	text = stdout if stdout is not None else ""
	if len(text) < _MIN_CHARS:
		return text
	family = detect_family(command)
	if family == "unknown":
		return text

	handlers: dict[_Family, Callable[[str], str]] = {
		"pytest": _compact_pytest,
		"vitest": _compact_test_runner,
		"cargo_test": _compact_test_runner,
		"go_test": _compact_test_runner,
		"tsc": _compact_tsc,
		"lint": _compact_lint,
		"git": _compact_git,
		"build": _compact_build,
	}
	handler = handlers.get(family)
	if handler is None:
		return text
	compacted = handler(text)
	if compacted == text:
		return text
	# 失败夹具必须仍含错误信号
	if _TRACE_HINT.search(text) and not _TRACE_HINT.search(compacted):
		return text
	return compacted.rstrip() + f"\n\n[compacted {family}]"


def _compact_pytest(text: str) -> str:
	lines = text.replace("\r\n", "\n").split("\n")
	passed = failed = skipped = errors = 0
	failure_blocks: list[str] = []
	in_failures = False
	buf: list[str] = []

	for ln in lines:
		if re.match(r"^={5,}\s*FAILURES\s*={5,}", ln):
			in_failures = True
			if buf:
				failure_blocks.append("\n".join(buf))
				buf = []
			buf.append(ln)
			continue
		if in_failures:
			if re.match(r"^={5,}\s*\d+", ln) or re.match(r"^={5,}\s*short test summary", ln, re.I):
				if buf:
					failure_blocks.append("\n".join(buf))
					buf = []
				in_failures = False
			else:
				buf.append(ln)
				continue
		m = re.search(r"(\d+)\s+passed", ln, re.I)
		if m:
			passed = max(passed, int(m.group(1)))
		m = re.search(r"(\d+)\s+failed", ln, re.I)
		if m:
			failed = max(failed, int(m.group(1)))
		m = re.search(r"(\d+)\s+skipped", ln, re.I)
		if m:
			skipped = max(skipped, int(m.group(1)))
		m = re.search(r"(\d+)\s+error", ln, re.I)
		if m:
			errors = max(errors, int(m.group(1)))

	if buf:
		failure_blocks.append("\n".join(buf))

	# 无 summary 时从 PASSED/FAILED 行粗估
	if passed == 0 and failed == 0 and errors == 0:
		for ln in lines:
			if _PASSED_LINE.search(ln):
				passed += 1
			elif _FAILED_LINE.search(ln):
				failed += 1

	parts: list[str] = []
	summary_bits = []
	if passed:
		summary_bits.append(f"{passed} passed")
	if failed:
		summary_bits.append(f"{failed} failed")
	if errors:
		summary_bits.append(f"{errors} errors")
	if skipped:
		summary_bits.append(f"{skipped} skipped")
	if summary_bits:
		parts.append("summary: " + ", ".join(summary_bits))
	else:
		parts.append("summary: (no counts parsed)")

	if failure_blocks:
		parts.append("")
		parts.append("==== FAILURES ====")
		# 每个失败块最多保留尾部 80 行（traceback 通常在尾部）
		for block in failure_blocks[:8]:
			blines = block.split("\n")
			if len(blines) > 80:
				blines = blines[:5] + ["…"] + blines[-75:]
			parts.append("\n".join(blines))
			parts.append("")
	elif failed or errors:
		# 没解析到 FAILURES 段：保留含 FAILED/Error/Traceback 的行
		err_lines = [
			ln for ln in lines
			if _FAILED_LINE.search(ln) or _TRACE_HINT.search(ln) or ln.startswith("E ")
		]
		if err_lines:
			parts.append("")
			parts.extend(err_lines[:200])

	return "\n".join(parts).rstrip() + "\n"


def _compact_test_runner(text: str) -> str:
	"""vitest / jest / cargo test / go test：保留失败 + 计数。"""
	lines = text.replace("\r\n", "\n").split("\n")
	passed = failed = 0
	keep: list[str] = []
	for ln in lines:
		if _PASSED_LINE.search(ln) or re.search(r"(?i)\bPASS\b", ln):
			passed += 1
			continue
		if _FAILED_LINE.search(ln) or re.search(r"(?i)\bFAIL\b", ln) or _TRACE_HINT.search(ln):
			failed += 1
			keep.append(ln)
			continue
		# cargo 输出：test xxx ... ok / FAILED
		m = re.match(r"^test\s+\S+.*\.\.\.\s*(ok|FAILED|ignored)", ln, re.I)
		if m:
			if m.group(1).lower() == "ok":
				passed += 1
			elif m.group(1).lower() == "failed":
				failed += 1
				keep.append(ln)
			continue
		# go test 输出 FAIL / --- FAIL
		if re.match(r"^---\s+FAIL:", ln) or re.match(r"^FAIL\t", ln):
			failed += 1
			keep.append(ln)
			continue
		if re.match(r"^---\s+PASS:", ln) or re.match(r"^ok\t", ln):
			passed += 1
			continue
		# 保留堆栈续行（缩进 / 文件:行）
		if keep and (ln.startswith(" ") or ln.startswith("\t") or re.match(r"^\s+at\s+", ln)):
			keep.append(ln)

	# 也扫 summary 行
	for ln in lines:
		m = re.search(r"(\d+)\s+passed", ln, re.I)
		if m:
			passed = max(passed, int(m.group(1)))
		m = re.search(r"(\d+)\s+failed", ln, re.I)
		if m:
			failed = max(failed, int(m.group(1)))
		m = re.search(r"(\d+)\s+passed;\s*(\d+)\s+failed", ln, re.I)
		if m:
			passed = max(passed, int(m.group(1)))
			failed = max(failed, int(m.group(2)))

	parts = [f"summary: {passed} passed, {failed} failed"]
	if keep:
		parts.append("")
		parts.extend(keep[:300])
	return "\n".join(parts).rstrip() + "\n"


def _compact_tsc(text: str) -> str:
	"""按文件分组 tsc 错误。"""
	lines = text.replace("\r\n", "\n").split("\n")
	# path(line,col): error TSxxxx: msg  或  path:line:col - error
	by_file: dict[str, list[str]] = {}
	other: list[str] = []
	pat = re.compile(r"^([^\s(]+?)(?:\((\d+),(\d+)\)|:(\d+):(\d+))\s*:\s*(.+)$")
	for ln in lines:
		s = ln.strip()
		if not s:
			continue
		m = pat.match(s)
		if m:
			path = m.group(1)
			by_file.setdefault(path, []).append(s)
		elif re.search(r"(?i)error\s+TS\d+", s) or "error" in s.lower():
			other.append(s)

	if not by_file and not other:
		return text

	parts = [f"tsc: {sum(len(v) for v in by_file.values()) + len(other)} issues in {len(by_file)} files"]
	for i, (path, errs) in enumerate(by_file.items()):
		if i >= _MAX_GROUPED_FILES:
			parts.append(f"… +{len(by_file) - i} more files")
			break
		parts.append(f"{path}: {len(errs)}")
		parts.extend(f"  {e}" for e in errs[:8])
		if len(errs) > 8:
			parts.append(f"  … +{len(errs) - 8} more")
	parts.extend(other[:40])
	return "\n".join(parts).rstrip() + "\n"


def _compact_lint(text: str) -> str:
	"""eslint / ruff / biome：按文件或规则分组。"""
	lines = text.replace("\r\n", "\n").split("\n")
	by_file: dict[str, list[str]] = {}
	# eslint stylish: /path/file.js 然后缩进行
	current: str | None = None
	for ln in lines:
		if not ln.strip():
			continue
		# 无缩进的路径行
		if not ln.startswith(" ") and not ln.startswith("\t") and (
			"/" in ln or "\\" in ln or ln.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))
		):
			current = ln.strip().rstrip(":")
			by_file.setdefault(current, [])
			continue
		if current is not None and (ln.startswith(" ") or ln.startswith("\t")):
			by_file[current].append(ln.strip())
			continue
		# ruff 输出：path:line:col: CODE message
		m = re.match(r"^(\S+?):(\d+):\d+:\s+(\S+)\s+(.+)$", ln.strip())
		if m:
			by_file.setdefault(m.group(1), []).append(ln.strip())
			continue

	if not by_file:
		# 退化：只留含 error/warning 的行
		keep = [ln for ln in lines if re.search(r"(?i)error|warning|✗|×", ln)]
		if not keep:
			return text
		return "\n".join(keep[:200]).rstrip() + "\n"

	n = sum(len(v) for v in by_file.values())
	parts = [f"lint: {n} issues in {len(by_file)} files"]
	for i, (path, errs) in enumerate(by_file.items()):
		if i >= _MAX_GROUPED_FILES:
			parts.append(f"… +{len(by_file) - i} more files")
			break
		parts.append(f"{path}: {len(errs)}")
		parts.extend(f"  {e}" for e in errs[:6])
		if len(errs) > 6:
			parts.append(f"  … +{len(errs) - 6} more")
	return "\n".join(parts).rstrip() + "\n"


def _compact_git(text: str) -> str:
	"""git status/log/diff：紧凑化。"""
	lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip() != ""]
	# status --porcelain 或长格式 status
	if any(ln.startswith("## ") or re.match(r"^(M|A|D|R|\?\?)\s", ln) for ln in lines):
		staged = unstaged = untracked = 0
		branch = ""
		samples: list[str] = []
		for ln in lines:
			if ln.startswith("## "):
				branch = ln[3:].split("...")[0].strip()
				continue
			if ln.startswith("??"):
				untracked += 1
			elif len(ln) >= 2 and ln[0] in "MADRC":
				staged += 1
			elif len(ln) >= 2 and ln[1] in "MADRC":
				unstaged += 1
			if len(samples) < 30:
				samples.append(ln)
		parts = []
		if branch:
			parts.append(f"branch: {branch}")
		parts.append(f"dirty: staged={staged} unstaged={unstaged} untracked={untracked}")
		parts.extend(samples)
		return "\n".join(parts).rstrip() + "\n"

	# git log：只留 hash + subject 风格行，截断到 40
	logish = [ln for ln in lines if re.match(r"^[0-9a-f]{7,}\b", ln) or ln.startswith("commit ")]
	if logish:
		out = logish[:40]
		if len(logish) > 40:
			out.append(f"… +{len(logish) - 40} more commits")
		return "\n".join(out).rstrip() + "\n"

	# diff：减 context——只留文件头 + +/-/@@ 行
	diff_keep = [
		ln for ln in lines
		if ln.startswith(("diff ", "index ", "---", "+++", "@@", "+", "-"))
		and not ln.startswith(("+++ /dev/null", "--- /dev/null"))
	]
	# 去掉纯上下文（不以 + - @ 开头的已在上面滤掉）；进一步限制总行
	if len(diff_keep) >= 20:
		if len(diff_keep) > 400:
			head, tail = diff_keep[:200], diff_keep[-100:]
			return "\n".join(head + [f"… {len(diff_keep) - 300} lines omitted …"] + tail).rstrip() + "\n"
		return "\n".join(diff_keep).rstrip() + "\n"

	return text


def _compact_build(text: str) -> str:
	"""构建：成功留末几行；有错误保留 error 块 + 末尾。"""
	lines = text.replace("\r\n", "\n").split("\n")
	err_idx = [i for i, ln in enumerate(lines) if _TRACE_HINT.search(ln)]
	if err_idx:
		chunks: list[str] = []
		for i in err_idx[:12]:
			start = max(0, i - 2)
			end = min(len(lines), i + 15)
			chunks.extend(lines[start:end])
			chunks.append("──")
		tail = lines[-_TAIL_BUILD_LINES:]
		return "\n".join(chunks + ["", "… tail …"] + tail).rstrip() + "\n"
	tail = lines[-_TAIL_BUILD_LINES:]
	return "\n".join(["build: ok (output compacted to tail)", *tail]).rstrip() + "\n"
