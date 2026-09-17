"""GrepTool — 内容搜索（ripgrep 核心 + XEYO schema/execute）。"""

# 读权限：走 permissions.filesystem 路径狱；ASK 仅信 registry preapproved。
# abort→杀 rg：已由 fileio.rg_subprocess 的 abort watcher 覆盖。
# TODO: [ignore] 挂载 .agentignore（glob_tool 已接，grep 尚未）与用户 deny 路径接入

from __future__ import annotations

import asyncio
import os
from tools.fileio import fsprobe as _fsprobe
from tools.container_fs import display_cwd as _cfs_display_cwd
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from engine.abort import AbortController
from permissions import filesystem
from tools.base_tool import ToolResult
from codeindex.symbols import iter_symbols
from tools.fileio import content_index
from tools.fileio.excludes import excluded_dir_globs
from tools.fileio.rg_subprocess import (
	RG_MISSING_IN_CONTAINER,
	RipgrepRunnerError,
	run_ripgrep_lines,
)
from tools.grep_tool.prompt import DESCRIPTION, GREP_TOOL_NAME

FILE_NOT_FOUND_CWD_NOTE = "Current working directory:"

# 空结果时追加的处置提示（大小写/范围）。
_NO_MATCH_TIP = (
	"\n\nNo matches. case_insensitive=true enables a case-insensitive pass; "
	"path and glob restrict the searched files (for example path=\"gui/src\" "
	"or glob=\"*.tsx\")."
)
# files_with_matches 命中少时提醒改用 content 模式，避免额外 Read。
_SMALL_FILES_TIP = (
	"\n\noutput_mode=\"content\" returns matching lines; "
	"output_mode=\"files_with_matches\" returns matching file paths."
)

# 默认 head_limit；显式传 0 表示不限制
DEFAULT_HEAD_LIMIT = 250

# 防止 base64 / 压缩单行刷爆上下文
MAX_COLUMNS = 500

RG_TIMEOUT_SECONDS = 30

OutputMode = Literal["content", "files_with_matches", "count", "symbols"]
VALID_OUTPUT_MODES = frozenset({"content", "files_with_matches", "count", "symbols"})

# symbols 模式单次调用累计符号上限（防误扫巨型目录拖死调用）
MAX_SCAN_SYMBOLS = 200_000


def get_cwd() -> str:
	from engine.workspace_context import get_cwd as ws_get_cwd

	return ws_get_cwd()


def expand_path(path: str) -> str:
	return os.path.abspath(os.path.expanduser(path))


def to_relative_path(path: str, base: Optional[str] = None) -> str:
	"""将绝对路径转为相对路径；跨盘符等失败时返回原路径。"""
	if base is None:
		base = get_cwd()
	try:
		return os.path.relpath(path, base)
	except ValueError:
		return path


def suggest_path_under_cwd(target_path: str, *, cwd: str | None = None) -> Optional[str]:
	"""用户访问 cwd 父目录越界时，尝试在 cwd 下找同名目录/文件作为提示。"""
	cwd = cwd or get_cwd()
	cwd_parent = os.path.dirname(os.path.realpath(cwd))
	try:
		rp = os.path.realpath(target_path)
	except OSError:
		rp = os.path.abspath(target_path)
	sep = os.sep
	if cwd_parent == sep:
		parent_prefix = sep
	else:
		parent_prefix = cwd_parent + sep
	if (not rp.startswith(parent_prefix)) or rp.startswith(cwd + sep) or rp == cwd:
		return None
	want_name = os.path.basename(rp).lower()
	try:
		for name in os.listdir(cwd):
			full = os.path.join(cwd, name)
			if name.lower() == want_name:
				return full
	except OSError:
		pass
	return None


def check_read_permission_for_tool(*args: Any, **kwargs: Any) -> bool:
	"""工具级读权限入口（转发到 permissions.filesystem）。"""
	return filesystem.check_read_permission_for_tool(*args, **kwargs)


def _coerce_bool(value: Any, default: bool = False) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	if isinstance(value, str):
		s = value.strip().lower()
		if s in ("true", "1", "yes", "on"):
			return True
		if s in ("false", "0", "no", "off", ""):
			return False
	return default


def _coerce_optional_int(value: Any) -> int | None:
	if value is None or value == "":
		return None
	if isinstance(value, bool):
		return int(value)
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value)
	if isinstance(value, str):
		s = value.strip()
		if not s:
			return None
		try:
			return int(float(s))
		except ValueError:
			return None
	return None


def apply_head_limit(
	items: list[str],
	limit: int | None,
	offset: int = 0,
) -> tuple[list[str], int | None]:
	"""
	分页截断。limit=0 表示不限制；未指定则用 DEFAULT_HEAD_LIMIT。
	仅在真正发生截断时返回 applied_limit，便于模型分页。
	"""
	safe_offset = max(0, offset or 0)
	if limit == 0:
		return items[safe_offset:], None
	effective = DEFAULT_HEAD_LIMIT if limit is None else limit
	if effective < 0:
		effective = DEFAULT_HEAD_LIMIT
	sliced = items[safe_offset : safe_offset + effective]
	was_truncated = len(items) - safe_offset > effective
	return sliced, (effective if was_truncated else None)


def format_limit_info(
	applied_limit: int | None,
	applied_offset: int | None,
) -> str:
	parts: list[str] = []
	if applied_limit is not None:
		parts.append(f"limit: {applied_limit}")
	if applied_offset:
		parts.append(f"offset: {applied_offset}")
	return ", ".join(parts)


def _plural(n: int, word: str) -> str:
	return word if n == 1 else f"{word}s"


def split_glob_patterns(glob: str) -> list[str]:
	"""
	拆分 glob 参数：空格分隔；无花括号时再按逗号拆。
	保留 `{a,b}` 这类 brace 模式不被逗号拆坏。
	"""
	patterns: list[str] = []
	for raw in glob.split():
		if "{" in raw and "}" in raw:
			patterns.append(raw)
		else:
			patterns.extend(p for p in raw.split(",") if p)
	return [p for p in patterns if p]


def build_rg_args(input_data: "GrepInput") -> list[str]:
	"""把 GrepInput 编译为 ripgrep argv（不含最终 path 目标）。"""
	mode = input_data.output_mode or "files_with_matches"
	args: list[str] = ["--hidden"]

	args.extend(excluded_dir_globs())

	args.extend(["--max-columns", str(MAX_COLUMNS)])
	# content 模式下长行显示行首预览，替代 "[Omitted long matching line]"，
	# 让模型无需额外 Read 就能看到命中内容开头。
	if mode == "content":
		args.append("--max-columns-preview")

	if input_data.multiline:
		args.extend(["-U", "--multiline-dotall"])

	if input_data.case_insensitive:
		args.append("-i")

	if mode == "files_with_matches":
		args.append("-l")
	elif mode == "count":
		args.append("-c")

	if mode == "content" and input_data.show_line_numbers:
		args.append("-n")

	if mode == "content":
		ctx = input_data.context
		if ctx is not None:
			args.extend(["-C", str(ctx)])
		elif input_data.context_c is not None:
			args.extend(["-C", str(input_data.context_c)])
		else:
			if input_data.context_before is not None:
				args.extend(["-B", str(input_data.context_before)])
			if input_data.context_after is not None:
				args.extend(["-A", str(input_data.context_after)])

	pattern = input_data.pattern
	# 以 - 开头的 pattern 必须用 -e，避免被当成 rg 选项
	if pattern.startswith("-"):
		args.extend(["-e", pattern])
	else:
		args.append(pattern)

	if input_data.type:
		args.extend(["--type", input_data.type])

	if input_data.glob:
		for g in split_glob_patterns(input_data.glob):
			args.extend(["--glob", g])

	return args


def run_ripgrep(
	args: list[str],
	target: str,
	*,
	timeout: int = RG_TIMEOUT_SECONDS,
	abort: AbortController | None = None,
	files: list[str] | None = None,
) -> list[str]:
	"""执行 rg；exit 0/1 为成功，其余抛错。abort/超时会杀死子进程。

	``files`` 给定（索引候选集，可为空）时，把它作为显式目标文件列表传给 rg，
	从而把扫描面收窄到候选集合（由索引预筛 + rg 精确验证双保险）。
	"""
	if files is not None:
		cmd = ["rg", *args, *files]
	else:
		cmd = ["rg", *args, target]
	try:
		return run_ripgrep_lines(
			cmd,
			timeout_seconds=float(timeout),
			abort=abort,
			timeout_message=(
				f"Ripgrep search timed out after {timeout} seconds. "
				"The search may have matched files but did not complete in time. "
				"Try searching a more specific path or pattern."
			),
		)
	except RipgrepRunnerError as e:
		# 容器路由已在 run_ripgrep_lines 汇聚点接线。任务镜像**全部没有 rg**
		#（2026-09-16 抽样实测 5/5），故这里回退到容器内 GNU grep——输出形状与
		# rg 逐字同形（path:line:content / path:count / path），解析层无需改动。
		# 映射不出逐字等价语义时保持原错误：宁可不给结果，也不给改过语义的结果。
		if RG_MISSING_IN_CONTAINER not in str(e):
			raise RuntimeError(str(e)) from e
		from tools.container_fs import active_container as _ac
		from tools.grep_tool.rg_fallback import grep_argv_from_rg, pipeline_from_rg

		if not _ac():
			raise RuntimeError(str(e)) from e
		# 带正向 glob 时必须走 find|grep 管道：GNU grep 里只要出现 --exclude，
		# --include 就失效（实测 grep 3.11），直接用会把不该搜的文件也搜进来。
		pipeline = pipeline_from_rg(args, target)
		if pipeline is not None:
			from tools.container_fs import container_exec as _cexec

			probed = _cexec(pipeline, timeout_s=float(timeout) + 5.0, separate=True)
			if probed is None:
				raise RuntimeError(str(e)) from e
			code, out, err = probed
			if code >= 2 and not out.strip():
				raise RuntimeError(
					f"grep fallback error: {(err or '').strip() or f'exit {code}'}"
				) from e
			return [
				line.replace("\r", "")
				for line in (out or "").splitlines()
				if line.strip()
			]
		mapped = grep_argv_from_rg(args, target)
		if mapped is None:
			raise RuntimeError(
				"ripgrep is not installed in the task container and this search "
				"cannot be mapped to the available grep backend."
			) from e
		from tools.container_fs import run_argv as _run_argv

		probed = _run_argv(["grep", *mapped], timeout_s=float(timeout))
		if probed is None:
			raise RuntimeError(str(e)) from e
		code, out, err = probed
		if code >= 2:
			raise RuntimeError(f"grep error: {(err or '').strip() or f'exit {code}'}") from e
		return [
			line.replace("\r", "")
			for line in (out or "").splitlines()
			if line.strip()
		]


def _split_rg_path_prefix(line: str) -> tuple[str, str] | None:
	"""
	拆分 rg 输出的 path 前缀与剩余部分。
	Windows 盘符路径（C:\\...）需跳过驱动器冒号，避免把 D: 当成分隔符。
	"""
	start = 0
	if re.match(r"^[A-Za-z]:[\\/]", line):
		start = 2
	elif line.startswith("\\\\") or line.startswith("//"):
		start = 2
	colon = line.find(":", start)
	if colon <= 0:
		return None
	return line[:colon], line[colon:]


def _relativize_content_line(line: str, base: str) -> str:
	"""content 行格式: path:content 或 path:num:content。"""
	parts = _split_rg_path_prefix(line)
	if parts is None:
		return line
	file_path, rest = parts
	if os.path.isabs(file_path) or re.match(r"^[A-Za-z]:[\\/]", file_path):
		return to_relative_path(file_path, base) + rest
	return line


def _relativize_count_line(line: str, base: str) -> str:
	"""count 行格式: path:count（取最后一个冒号）。"""
	colon = line.rfind(":")
	if colon <= 0:
		return line
	file_path = line[:colon]
	count_part = line[colon:]
	if os.path.isabs(file_path) or re.match(r"^[A-Za-z]:[\\/]", file_path):
		return to_relative_path(file_path, base) + count_part
	return line


def _content_line_sort_key(line: str) -> tuple[str, int]:
	"""content 行确定性排序键：先按路径、再按行号（rg 遍历序不稳定）。"""
	parts = _split_rg_path_prefix(line)
	if parts is None:
		return (line, 0)
	file_path, rest = parts
	m = re.match(r":(\d+):", rest)
	num = int(m.group(1)) if m else 0
	return (file_path.replace("\\", "/").lower(), num)


def _count_line_sort_key(line: str) -> tuple[str]:
	"""count 行确定性排序键：按路径。"""
	colon = line.rfind(":")
	if colon <= 0:
		return (line,)
	return (line[:colon].replace("\\", "/").lower(),)


@dataclass
class GrepInput:
	pattern: str
	path: Optional[str] = None
	glob: Optional[str] = None
	output_mode: OutputMode = "files_with_matches"
	type: Optional[str] = None
	head_limit: Optional[int] = None
	offset: int = 0
	multiline: bool = False
	case_insensitive: bool = False
	show_line_numbers: bool = True
	context_before: Optional[int] = None
	context_after: Optional[int] = None
	context_c: Optional[int] = None
	context: Optional[int] = None
	# symbols 模式扩展
	kinds: Optional[list[str]] = None          # 按符号类型过滤（class/method/function/...）
	detail: str = "signatures"                  # signatures | folded（折叠方法到容器行）


@dataclass
class GrepOutput:
	mode: OutputMode
	num_files: int
	filenames: list[str] = field(default_factory=list)
	content: Optional[str] = None
	num_lines: Optional[int] = None
	num_matches: Optional[int] = None
	applied_limit: Optional[int] = None
	applied_offset: Optional[int] = None


def prompt() -> str:
	return DESCRIPTION.strip()


class GrepTool:
	name = GREP_TOOL_NAME
	search_hint = "search file contents with regex (ripgrep)"
	max_result_size_chars = 20_000

	def __init__(self, *, cwd: str = ".") -> None:
		self._cwd = os.path.abspath(cwd or ".")

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": prompt(),
			"input_schema": {
				"type": "object",
				"properties": {
					"pattern": {
						"type": "string",
						"description": "Regex to search in file contents",
					},
					"path": {
						"type": "string",
						"description": "File or directory (default: cwd)",
					},
					"glob": {
						"type": "string",
						"description": 'Filter files, e.g. "*.js" (rg --glob)',
					},
					"output_mode": {
						"type": "string",
						"enum": ["content", "files_with_matches", "count", "symbols"],
						"description": (
							'content | files_with_matches (default) | count | '
							"symbols (list matching symbol definitions with "
							"signatures)."
						),
					},
					"kinds": {
						"type": "array",
						"items": {
							"type": "string",
							"enum": ["class", "method", "function", "interface", "enum", "type"],
						},
						"description": "symbols mode only: filter by symbol kind, e.g. ['class', 'interface'] for structure-only view",
					},
					"detail": {
						"type": "string",
						"enum": ["signatures", "folded"],
						"description": (
							"symbols mode only: folded groups methods under their "
							"container line (class X (12 members)); signatures returns "
							"individual symbol signatures"
						),
					},
					"-B": {
						"type": "number",
						"description": "Lines before match (content mode)",
					},
					"-A": {
						"type": "number",
						"description": "Lines after match (content mode)",
					},
					"-C": {
						"type": "number",
						"description": "Alias for context",
					},
					"context": {
						"type": "number",
						"description": "Lines before and after (content mode)",
					},
					"-n": {
						"type": "boolean",
						"description": "Show line numbers (content mode; default true)",
					},
					"-i": {
						"type": "boolean",
						"description": "Case insensitive",
					},
					"type": {
						"type": "string",
						"description": "rg --type (js, py, rust, …)",
					},
					"head_limit": {
						"type": "number",
						"description": "Max entries (default 250; 0 = unlimited)",
					},
					"offset": {
						"type": "number",
						"description": "Skip first N entries (default 0)",
					},
					"multiline": {
						"type": "boolean",
						"description": "Dot matches newlines (rg -U; default false)",
					},
				},
				"required": ["pattern"],
			},
		}

	def get_path(self, input_data: GrepInput) -> str:
		if input_data.path:
			p = input_data.path.strip()
			if not os.path.isabs(p):
				p = os.path.join(self._cwd, p)
			return expand_path(p)
		return self._cwd

	def validate_input(self, input_data: GrepInput) -> dict[str, Any]:
		if not input_data.pattern or not str(input_data.pattern).strip():
			return {
				"result": False,
				"message": "pattern is required",
				"errorCode": 0,
			}

		mode = input_data.output_mode or "files_with_matches"
		if mode not in VALID_OUTPUT_MODES:
			return {
				"result": False,
				"message": (
					f"invalid output_mode: {mode!r}; "
					'expected "content", "files_with_matches", "count", or "symbols"'
				),
				"errorCode": 3,
			}

		if mode == "symbols":
			if input_data.detail not in ("signatures", "folded"):
				return {
					"result": False,
					"message": (
						f"invalid detail: {input_data.detail!r}; "
						'expected "signatures" or "folded"'
					),
					"errorCode": 3,
				}
			valid_kinds = {"class", "method", "function", "interface", "enum", "type"}
			if input_data.kinds is not None:
				bad = [k for k in input_data.kinds if k.lower() not in valid_kinds]
				if bad:
					return {
						"result": False,
						"message": (
							f"invalid kinds: {bad}; valid: "
							"class, method, function, interface, enum, type"
						),
						"errorCode": 3,
					}

		if input_data.offset is not None and input_data.offset < 0:
			return {
				"result": False,
				"message": "offset must be >= 0",
				"errorCode": 4,
			}

		if not input_data.path:
			return {"result": True}

		raw = str(input_data.path).strip()
		if raw.lower() in ("undefined", "null", ""):
			return {"result": True}

		abs_path = self.get_path(GrepInput(pattern=input_data.pattern, path=raw))
		# 安全：跳过 UNC，避免不必要的文件系统探测 / NTLM 凭据泄漏
		if abs_path.startswith("\\\\") or abs_path.startswith("//"):
			return {"result": True}

		if not _fsprobe.exists(abs_path):
			suggestion = suggest_path_under_cwd(abs_path, cwd=self._cwd)
			message = (
				f"Path does not exist: {raw}. "
				f"{FILE_NOT_FOUND_CWD_NOTE} {_cfs_display_cwd(self._cwd)}."
			)
			if suggestion:
				message += f" Nearest existing path: {suggestion}."
			return {"result": False, "message": message, "errorCode": 1}

		return {"result": True}

	def check_permissions(self, input_data: GrepInput, context: Any = None) -> bool:
		return check_read_permission_for_tool(self, input_data, context)

	def call(self, input_data: GrepInput, *, abort: AbortController | None = None) -> GrepOutput:
		absolute_path = self.get_path(input_data)
		mode: OutputMode = input_data.output_mode or "files_with_matches"

		if mode == "symbols":
			return self._call_symbols(input_data, absolute_path)

		args = build_rg_args(input_data)
		offset = max(0, input_data.offset or 0)

		# files_with_matches 字面量检索：用内容索引预筛候选文件，把 rg 扫描面从全库
		# 收窄到候选集（索引为完整超集 + rg 精确验证 → 仍是“确切匹配”）。
		# 任何索引不可用/异常/候选为空 → 回退全量 rg（fail-open，不改正确性）。
		#
		# 容器路由（2026-09-16）：**必须跳过预筛**。索引是按**宿主**文件系统建的，
		# 而工作面在容器里 ⇒ 候选集恒为空 ⇒ 直接返回"零命中"。那正是"静默错答"
		# （比报错更坏）：模型会以为文件里没有这个词。
		_index_usable = True
		try:
			from tools.container_fs import active_container as _ac

			_index_usable = not bool(_ac())
		except Exception:  # noqa: BLE001 — 路由模块不可用视为宿主
			_index_usable = True
		index_prefiltered = False
		if (
			_index_usable
			and mode == "files_with_matches"
			and content_index.is_literal(input_data.pattern)
			and not input_data.glob
			and not input_data.type
			and _fsprobe.isdir(absolute_path)
		):
			cands = content_index.lookup(absolute_path, input_data.pattern)
			if cands is not None:
				index_prefiltered = True
				if not cands:
					# 候选为空 = 索引（完整超集）证明无文件可含该字面量 → 直接零命中。
					return GrepOutput(
						mode="files_with_matches",
						num_files=0,
						filenames=[],
						applied_limit=None,
						applied_offset=offset if offset > 0 else None,
					)
				results = run_ripgrep(
					args,
					absolute_path,
					files=[os.path.normpath(os.path.join(absolute_path, c)) for c in cands],
					abort=abort,
				)

		if not index_prefiltered:
			results = run_ripgrep(args, absolute_path, abort=abort)

		if mode == "content":
			# 确定序：先按 (路径, 行号) 排好再分页，避免 rg 遍历序跨调用漂移。
			results.sort(key=_content_line_sort_key)
			limited, applied_limit = apply_head_limit(
				results, input_data.head_limit, offset
			)
			final_lines = [
				_relativize_content_line(line, self._cwd) for line in limited
			]
			return GrepOutput(
				mode="content",
				num_files=0,
				filenames=[],
				content="\n".join(final_lines),
				num_lines=len(final_lines),
				applied_limit=applied_limit,
				applied_offset=offset if offset > 0 else None,
			)

		if mode == "count":
			# 确定序：按路径排序后再分页（count 模式输出本身无序）。
			results.sort(key=_count_line_sort_key)
			limited, applied_limit = apply_head_limit(
				results, input_data.head_limit, offset
			)
			final_lines = [
				_relativize_count_line(line, self._cwd) for line in limited
			]
			total_matches = 0
			file_count = 0
			for line in final_lines:
				colon = line.rfind(":")
				if colon <= 0:
					continue
				try:
					total_matches += int(line[colon + 1 :])
					file_count += 1
				except ValueError:
					continue
			return GrepOutput(
				mode="count",
				num_files=file_count,
				filenames=[],
				content="\n".join(final_lines),
				num_matches=total_matches,
				applied_limit=applied_limit,
				applied_offset=offset if offset > 0 else None,
			)

		# files_with_matches：统一、确定的排序（按相对路径字母序）。
		# 旧实现逐文件 getmtime 再按 mtime 排序：每文件一次系统调用，且 mtime
		# 序跨运行不稳定；改为路径序——零 syscall、可复现，利于模型分页。
		results.sort(key=lambda p: to_relative_path(p, self._cwd).lower())
		limited, applied_limit = apply_head_limit(
			results, input_data.head_limit, offset
		)
		relative = [to_relative_path(p, self._cwd) for p in limited]
		return GrepOutput(
			mode="files_with_matches",
			filenames=relative,
			num_files=len(relative),
			applied_limit=applied_limit,
			applied_offset=offset if offset > 0 else None,
		)

	def _call_symbols(self, input_data: GrepInput, absolute_path: str) -> GrepOutput:
		"""symbols 模式：符号索引过滤（不调 rg）。pattern 按符号名匹配。

		detail="folded" 时方法折叠进容器行（类只出一行 + 成员数），
		供全仓库概览；下钻用 path 收窄 / kinds 过滤 / Read symbol。
		"""
		import fnmatch

		glob_patterns = (
			split_glob_patterns(input_data.glob) if input_data.glob else None
		)
		kind_filter = (
			{k.lower() for k in input_data.kinds} if input_data.kinds else None
		)
		folded = input_data.detail == "folded"

		def glob_ok(file_path: str) -> bool:
			if not glob_patterns:
				return True
			base = os.path.basename(file_path)
			return any(
				fnmatch.fnmatch(base, g) or fnmatch.fnmatch(file_path, g)
				for g in glob_patterns
			)

		def kind_ok(sym_kind: str) -> bool:
			return kind_filter is None or sym_kind.lower() in kind_filter

		lines: list[str] = []
		count = 0
		any_folded = False
		# iter_symbols 按文件序产出；按文件缓冲后做折叠/过滤
		buf_path: str | None = None
		buf: list = []

		def flush() -> None:
			nonlocal count, any_folded
			if not buf:
				return
			if folded:
				# 嵌套判定用行号范围包含（parent 字段在 object-literal 方法等
				# 场景下为 None，不可靠）：被另一符号完整包含 → 折叠隐藏
				def is_nested(s) -> bool:
					return any(
						t is not s
						and t.start <= s.start and s.end <= t.end
						and (t.start, t.end) != (s.start, s.end)
						for t in buf
					)

				for s in buf:
					if not kind_ok(s.kind):
						continue
					if is_nested(s):
						any_folded = True
						continue
					n_members = sum(1 for t in buf if t is not s and s.start <= t.start and t.end <= s.end)
					rel = to_relative_path(buf_path, self._cwd)
					if n_members > 0:
						lines.append(
							f"{rel}:{s.start}: {s.signature} "
							f"[+{n_members} members: containing scope available]"
						)
					else:
						lines.append(f"{rel}:{s.start}: {s.signature}")
					count += 1
			else:
				for s in buf:
					if not kind_ok(s.kind):
						continue
					rel = to_relative_path(buf_path, self._cwd)
					lines.append(f"{rel}:{s.start}: {s.signature}")
					count += 1

		for file_path, sym in iter_symbols(
			absolute_path,
			input_data.pattern,
			ignore_case=input_data.case_insensitive,
			max_symbols=MAX_SCAN_SYMBOLS,
		):
			if not glob_ok(file_path):
				continue
			if file_path != buf_path:
				flush()
				buf_path, buf = file_path, []
			buf.append(sym)
		flush()

		offset = max(0, input_data.offset or 0)
		limited, applied_limit = apply_head_limit(lines, input_data.head_limit, offset)
		if any_folded and applied_limit is None:
			# 折叠模式尾部提示如何展开（仅在实际折叠过且未被分页截断时）
			limited = limited + [
				"\n[folded view: methods hidden inside containers; "
				'path and output_mode="symbols" address individual files; '
				'Read symbol="Class.method" returns a symbol body]'
			]
		return GrepOutput(
			mode="symbols",
			num_files=0,
			filenames=[],
			content="\n".join(limited),
			num_lines=len(limited),
			num_matches=count,
			applied_limit=applied_limit,
			applied_offset=offset if offset > 0 else None,
		)

	@staticmethod
	def map_tool_result_to_content(output: GrepOutput) -> str:
		"""转化为给模型看的文本结果。"""
		limit_info = format_limit_info(output.applied_limit, output.applied_offset)

		if output.mode == "content":
			body = output.content or "No matches found"
			if limit_info:
				body = f"{body}\n\n[Showing results with pagination = {limit_info}]"
			if not output.content:
				body = body + _NO_MATCH_TIP
			return body

		if output.mode == "count":
			raw = output.content or "No matches found"
			matches = output.num_matches or 0
			files = output.num_files or 0
			if matches == 0:
				raw = raw + _NO_MATCH_TIP
			summary = (
				f"\n\nFound {matches} total "
				f"{'occurrence' if matches == 1 else 'occurrences'} across "
				f"{files} {_plural(files, 'file')}."
			)
			if limit_info:
				summary = summary[:-1] + f" with pagination = {limit_info}"
			return raw + summary

		if output.mode == "symbols":
			if not output.content:
				return "No symbols found" + _NO_MATCH_TIP
			matches = output.num_matches or 0
			summary = f"\n\nFound {matches} {_plural(matches, 'symbol')} matched."
			if limit_info:
				summary = f"{summary} Pagination: {limit_info}; head_limit, path, and glob define the returned segment."
			return output.content + summary

		# files_with_matches 模式
		if output.num_files == 0:
			return "No files found" + _NO_MATCH_TIP
		header = f"Found {output.num_files} {_plural(output.num_files, 'file')}"
		if limit_info:
			header = f"{header} {limit_info}"
		body = header + "\n" + "\n".join(output.filenames)
		# 命中很少、且仍未用 content 模式 → 提醒直接看匹配行，避免一次文件一次 Read。
		if output.num_files <= 2:
			body = body + _SMALL_FILES_TIP
		return body

	@staticmethod
	def result_no_match(output: GrepOutput) -> bool:
		"""是否为合法执行但零命中（供 query_loop 零命中前提复核用）。"""
		if output.mode == "content":
			return not (output.num_lines or 0)
		if output.mode == "symbols":
			return not (output.num_lines or 0)
		if output.mode == "count":
			return not (output.num_matches or 0)
		return not len(output.filenames)

	def parse_input(self, raw: dict[str, Any]) -> GrepInput:
		"""从模型 JSON 参数解析 GrepInput（兼容 -i/-n/-A/-B/-C 与别名）。"""
		raw_path = raw.get("path")
		path: str | None
		if isinstance(raw_path, str) and raw_path.strip().lower() not in (
			"",
			"undefined",
			"null",
		):
			path = raw_path.strip()
		else:
			path = None

		raw_glob = raw.get("glob")
		glob = (
			raw_glob.strip()
			if isinstance(raw_glob, str) and raw_glob.strip()
			else None
		)

		raw_mode = raw.get("output_mode") or "files_with_matches"
		mode_str = str(raw_mode).strip() if raw_mode is not None else "files_with_matches"
		# 非法 mode 原样保留，由 validate_input 报错
		mode = mode_str  # type: OutputMode

		raw_type = raw.get("type")
		file_type = (
			raw_type.strip()
			if isinstance(raw_type, str) and raw_type.strip()
			else None
		)

		# -i 优先；兼容 stub 里的 case_insensitive
		case_insensitive = _coerce_bool(
			raw["-i"] if "-i" in raw else raw.get("case_insensitive"),
			False,
		)
		show_line_numbers = _coerce_bool(
			raw["-n"] if "-n" in raw else raw.get("show_line_numbers"),
			True,
		)

		raw_kinds = raw.get("kinds")
		kinds: list[str] | None = None
		if isinstance(raw_kinds, list):
			parsed = [str(k).strip() for k in raw_kinds if str(k).strip()]
			kinds = parsed or None
		raw_detail = raw.get("detail")
		detail = str(raw_detail).strip() if isinstance(raw_detail, str) and raw_detail.strip() else "signatures"

		return GrepInput(
			pattern=str(raw.get("pattern") or ""),
			path=path,
			glob=glob,
			output_mode=mode,
			type=file_type,
			head_limit=_coerce_optional_int(raw.get("head_limit")),
			offset=_coerce_optional_int(raw.get("offset")) or 0,
			multiline=_coerce_bool(raw.get("multiline"), False),
			case_insensitive=case_insensitive,
			show_line_numbers=show_line_numbers,
			context_before=_coerce_optional_int(raw.get("-B")),
			context_after=_coerce_optional_int(raw.get("-A")),
			context_c=_coerce_optional_int(raw.get("-C")),
			context=_coerce_optional_int(raw.get("context")),
			kinds=kinds,
			detail=detail,
		)

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		"""XEYO 入口：校验 → 权限 → call → ToolResult。"""
		abort.raise_if_aborted()

		grep_input = self.parse_input(input)

		validation = self.validate_input(grep_input)
		if not validation.get("result"):
			return ToolResult(
				content=str(validation.get("message") or "invalid input"),
				is_error=True,
			)

		if not self.check_permissions(grep_input):
			return ToolResult(content="permission denied", is_error=True)

		abort.raise_if_aborted()
		try:
			# P0: rg 子进程是同步阻塞，挪出事件循环；abort 传入以杀死子进程。
			output = await asyncio.to_thread(self.call, grep_input, abort=abort)
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=str(e), is_error=True)

		abort.raise_if_aborted()
		return ToolResult(
			content=self.map_tool_result_to_content(output),
			metadata={"no_match": True} if self.result_no_match(output) else None,
		)
