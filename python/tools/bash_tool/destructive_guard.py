"""Destructive-command before-snapshot guard（#14 Phase A 地基）。

此前只有 file_write/file_edit/notebook_edit 走 record_file_mutation 留 before
快照；bash rm/mv/del 一类破坏性命令不留任何可恢复痕迹，「可恢复提示」是空话。
本模块在命令执行前：

1. 解析命令段里的破坏性目标（rm/unlink/mv/move/del/erase/rd/rmdir/deltree/
   Remove-Item/ri），目标必须存在且位于 realpath(cwd) 之内（目录递归展开）；
2. 逐文件 ``snapshots.put_bytes`` before 快照（sha256 寻址，幂等）；
3. ``journal.start_operation`` 记 ``operation_type="bash_destructive"``、
   ``inverse_kind="restore_snapshot"``、``after_hash=None``，状态停在 started；
4. 命令有结局后由调用方 ``settle_destructive_plan``：执行过 → completed
   （含被中断/超时——破坏可能已部分发生，恢复到 before 仍正确）；没执行 →
   cancelled。

纪律（与 rewind 全家桶对齐）：
- **全链路 fail-open**：解析/快照/日志任一异常只降级为「不保护」，绝不阻断
  Bash 工具本身（call 是 Bash 唯一执行路径）；
- 上限可调：``XEYO_DESTRUCTIVE_SNAPSHOT_MAX_FILES``（默认 50）、
  ``XEYO_DESTRUCTIVE_SNAPSHOT_MAX_BYTES``（单文件字节上限，默认 10MB）；
- 总开关 ``XEYO_DESTRUCTIVE_SNAPSHOT=0`` 直接禁用。

Phase A 已知缺口（明确不做，后续 Phase 补）：
- registry 后台 job 直通路径（jobs_bridge 生产者线程无 rewind contextvars）
  不快照；仅 registry 登记失败落回日志文件后台的路径覆盖；
- run_isolated / docker 路由下目标在容器临时目录内，天然不满足 cwd 包含
  检查，不快照（也不应在宿主快照）。
"""

from __future__ import annotations

import glob as _glob
import logging
import os
import re
import shlex
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # rewind 依赖链异常时 Bash 工具必须仍可用 → 一律 fail-open
	from rewind.context import RewindExecutionContext, current_context
	from rewind.models import SnapshotManifest
except Exception:  # noqa: BLE001
	RewindExecutionContext = None  # type: ignore[assignment,misc]
	current_context = None  # type: ignore[assignment]
	SnapshotManifest = None  # type: ignore[assignment,misc]

_log = logging.getLogger(__name__)

_DISABLE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})

#: 破坏性程序名（小写、去 .exe、去路径前缀后匹配）。`ri` = Remove-Item 别名。
DESTRUCTIVE_PROGRAMS = frozenset({
	"rm", "unlink", "mv", "move", "del", "erase", "rd", "rmdir",
	"deltree", "remove-item", "ri",
})
#: POSIX 语义家族：`/x` 是路径不是旗标；`-x` 是旗标。
_POSIX_FAMILY = frozenset({"rm", "unlink", "mv"})
#: Windows/cmd/pwsh 语义家族：`-x` 与 `/x` 都按旗标跳过。
_WINDOWS_FAMILY = frozenset({
	"del", "erase", "rd", "rmdir", "deltree", "move", "remove-item", "ri",
})
#: 前缀程序（其后才是真命令）。
_PREFIX_PROGRAMS = frozenset({"sudo", "command", "env", "time", "nice", "nohup"})
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: 命令段切分：复合操作符 + 管道 + 换行。
_SEG_SPLIT = re.compile(r"&&|\|\||[;\n|&]")
#: 重定向 token（连同其后的目标名一起跳过，防止把重定向文件当删除目标）。
_REDIR_TOKENS = frozenset({">>", ">", "<", "2>", "2>>", "&>"})

DEFAULT_MAX_FILES = 50
DEFAULT_MAX_FILE_BYTES = 10_000_000


@dataclass
class GuardEntry:
	"""一个已完成 before 快照的文件。"""

	path: str
	snapshot_id: str
	content_hash: str
	size_bytes: int


@dataclass
class DestructivePlan:
	"""一次破坏性命令的快照计划；由执行路径持有并在结局后结算。"""

	command: str
	cwd: str
	ctx: Any  # RewindExecutionContext；rewind 导入失败时本模块整体降级
	entries: list[GuardEntry] = field(default_factory=list)
	operation_ids: list[str] = field(default_factory=list)
	skipped_count: int = 0
	settled: bool = False
	_settle_lock: threading.Lock = field(
		default_factory=threading.Lock, repr=False, compare=False
	)


def guard_enabled() -> bool:
	value = os.environ.get("XEYO_DESTRUCTIVE_SNAPSHOT", "1").strip().lower()
	return value not in _DISABLE_VALUES


def max_files() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_DESTRUCTIVE_SNAPSHOT_MAX_FILES", "")))
	except ValueError:
		return DEFAULT_MAX_FILES


def max_file_bytes() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_DESTRUCTIVE_SNAPSHOT_MAX_BYTES", "")))
	except ValueError:
		return DEFAULT_MAX_FILE_BYTES


def _program_name(token: str) -> str:
	name = token.strip().lower().replace("\\", "/")
	name = name.rsplit("/", 1)[-1]
	if name.endswith(".exe"):
		name = name[:-4]
	return name


def _segment_tokens(segment: str) -> list[str]:
	"""切 token；`#` 起始的裸 token 视为注释起点（raw token 判定，引号内不算）。"""
	try:
		raw = shlex.split(segment, posix=False)
	except ValueError:
		raw = segment.split()
	tokens: list[str] = []
	for tok in raw:
		if tok.startswith("#"):
			break
		if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
			tok = tok[1:-1]
		if tok:
			tokens.append(tok)
	return tokens


def _targets_in_segment(segment: str) -> list[str]:
	"""从单个命令段提取破坏性命令的目标 token（不解析路径、不查存在性）。"""
	tokens = _segment_tokens(segment)
	if not tokens:
		return []
	idx = 0
	while idx < len(tokens):  # 前缀：VAR=value / sudo / env / time …
		tok = tokens[idx]
		if _ENV_ASSIGN_RE.match(tok) or tok.lower() in _PREFIX_PROGRAMS:
			idx += 1
			continue
		break
	if idx >= len(tokens):
		return []
	prog = _program_name(tokens[idx])
	if prog not in DESTRUCTIVE_PROGRAMS:
		return []
	windows = prog in _WINDOWS_FAMILY
	targets: list[str] = []
	skip_next = False
	for tok in tokens[idx + 1:]:
		if skip_next:
			skip_next = False
			continue
		if tok in _REDIR_TOKENS:
			skip_next = True
			continue
		if tok.startswith("-"):
			# `-x` 旗标（两家族一致；`--` 也落在此处）。
			continue
		if windows and tok.startswith("/"):
			# cmd/pwsh 旗标（/q /s /y …）；POSIX 家族里 `/x` 是路径，不在此拦。
			continue
		targets.append(tok)
	return targets


def _expand_targets(raw_targets: list[str], cwd: str) -> list[str]:
	"""token → 绝对路径候选。glob 展开、`~` 展开；含 `$`/`%` 的变量形态跳过。"""
	out: list[str] = []
	per_glob_cap = max_files()
	for tok in raw_targets:
		if "$" in tok or "%" in tok:
			continue
		tok = os.path.expanduser(tok)
		if any(ch in tok for ch in "*?["):
			pattern = tok if os.path.isabs(tok) else os.path.join(cwd, tok)
			try:
				matches = sorted(_glob.glob(pattern))
			except Exception:  # noqa: BLE001 — 非法 pattern 等
				matches = []
			for match in matches[:per_glob_cap]:
				out.append(match if os.path.isabs(match) else os.path.abspath(match))
			continue
		path = tok if os.path.isabs(tok) else os.path.join(cwd, tok)
		out.append(os.path.abspath(path))
	return out


def _contained(path_real: str, root_real: str) -> bool:
	try:
		return os.path.commonpath([path_real, root_real]) == root_real
	except ValueError:  # Windows 跨盘符等
		return False


def plan_destructive_snapshot(
	command: str,
	cwd: str,
	ctx: Any = None,
) -> DestructivePlan | None:
	"""解析破坏性目标并做 before 快照；返回 None = 本命令不保护。"""

	try:
		return _plan(command, cwd, ctx)
	except Exception:  # noqa: BLE001 — fail-open：保护失效绝不能拖垮 Bash 工具
		_log.warning("destructive guard plan failed; fail-open", exc_info=True)
		return None


def _plan(command: str, cwd: str, ctx: Any) -> DestructivePlan | None:
	if current_context is None or RewindExecutionContext is None:
		return None
	if not guard_enabled():
		return None
	if ctx is None:
		ctx = current_context()
	if ctx is None or not ctx.enabled:
		return None
	if not cwd:
		return None

	raw_targets: list[str] = []
	for segment in _SEG_SPLIT.split(command or ""):
		raw_targets.extend(_targets_in_segment(segment))
	if not raw_targets:
		return None

	root_real = os.path.realpath(cwd)
	file_cap = max_files()
	byte_cap = max_file_bytes()
	entries: list[GuardEntry] = []
	operation_ids: list[str] = []
	skipped = 0
	seen: set[str] = set()

	def _snapshot_file(file_path: str) -> bool:
		"""成功返回 True；任何失败返回 False（计入 skipped）。"""
		nonlocal skipped
		try:
			if os.path.getsize(file_path) > byte_cap:
				skipped += 1
				return False
			data = Path(file_path).read_bytes()
		except OSError:
			skipped += 1
			return False
		manifest = ctx.snapshots.put_bytes(
			data,
			source_path=file_path,
			content_kind="binary",
			metadata={"role": "before", "guard": "bash_destructive"},
		)
		if manifest is None:
			skipped += 1
			return False
		record = ctx.journal.start_operation(
			turn_id=ctx.turn_id,
			revision_id=ctx.revision_id,
			tool_name="bash",
			operation_type="bash_destructive",
			path=file_path,
			before_hash=manifest.content_hash,
			after_hash=None,
			inverse_kind="restore_snapshot",
			inverse_payload={
				"file_existed_before": True,
				"before_snapshot_id": manifest.snapshot_id,
				"before_content_hash": manifest.content_hash,
				"source_path": file_path,
				"size_bytes": len(data),
				"command": (command or "")[:500],
			},
			metadata={"guard": "bash_destructive", "cwd": cwd},
		)
		if record is None:
			skipped += 1
			return False
		operation_ids.append(record.operation_id)
		entries.append(
			GuardEntry(
				path=file_path,
				snapshot_id=manifest.snapshot_id,
				content_hash=manifest.content_hash,
				size_bytes=len(data),
			)
		)
		return True

	for candidate in _expand_targets(raw_targets, cwd):
		if len(entries) >= file_cap:
			skipped += 1
			continue
		try:
			real = os.path.realpath(candidate)
		except OSError:
			continue
		if real in seen or not _contained(real, root_real):
			continue
		if os.path.isdir(real):
			for dirpath, _dirnames, filenames in os.walk(real):
				for name in sorted(filenames):
					if len(entries) >= file_cap:
						break
					file_path = os.path.join(dirpath, name)
					file_real = os.path.realpath(file_path)
					if file_real in seen:
						continue
					seen.add(file_real)
					_snapshot_file(file_real)
				if len(entries) >= file_cap:
					break
		elif os.path.isfile(real):
			seen.add(real)
			_snapshot_file(real)

	if not entries:
		return None
	ctx.operation_ids.extend(operation_ids)
	return DestructivePlan(
		command=command,
		cwd=cwd,
		ctx=ctx,
		entries=entries,
		operation_ids=operation_ids,
		skipped_count=skipped,
	)


def settle_destructive_plan(plan: DestructivePlan | None, *, executed: bool) -> None:
	"""命令有结局后结算 started 操作。executed=False → cancelled。fail-open。

	被中断/超时的命令仍按 completed 结算：破坏可能已部分发生，
	「恢复到 before 快照」依旧是正确的逆操作。
	"""

	if plan is None or plan.settled:
		return
	with plan._settle_lock:
		if plan.settled:
			return
		plan.settled = True
	status = "completed" if executed else "cancelled"
	for op_id in plan.operation_ids:
		try:
			plan.ctx.journal.transition_operation(op_id, status)
		except Exception:  # noqa: BLE001 — 单条失败不影响其余结算
			_log.warning("destructive guard settle failed for %s", op_id, exc_info=True)


__all__ = [
	"DestructivePlan",
	"GuardEntry",
	"DESTRUCTIVE_PROGRAMS",
	"guard_enabled",
	"plan_destructive_snapshot",
	"settle_destructive_plan",
]
