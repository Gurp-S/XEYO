"""GlobTool — 查找文件（ripgrep 核心 + XEYO schema/execute）。

轻量优化（仍零新工具）：
1. ignore 过滤：rg 默认尊重 .gitignore/.ignore；另挂载工作区/搜索根的
   `.agentignore`（--ignore-file，gitignore 语法，不依赖 git 仓库）；
2. 空结果且 pattern 含字母 → case-insensitive（--iglob）重试；
3. 过宽 pattern（* / ** / **/*）→ 一层目录摘要，禁止 newest-100 泄洪；
4. detail=folded 或命中偏多时按目录折叠；
5. 空结果引导：改文件名 / 设 path，明确禁止再 glob **/*；
6. head_limit 硬上限 120：超限截断并提示"缩小 glob 表达式"，不可调大；
7. 60s TTL 内存缓存：相同 (pattern, root, limit, offset) 不重复扫盘；
8. 统计：累计查询/缓存命中/贪婪 pattern/截断/命中文件数（glob_stats()），
   并随 ToolResult.metadata 上报单次 num_files/truncated/cached。

# 读权限：走 permissions.filesystem 路径狱；ASK 仅信 registry preapproved。
# TODO: [路径] 绝对路径 pattern 拆分 baseDir + relativePattern
"""

from __future__ import annotations

import asyncio
import difflib
import os
import subprocess
import threading
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

from engine.abort import AbortController
from permissions import filesystem
from tools.base_tool import ToolResult
from tools.fileio.excludes import agentignore_args, excluded_dir_globs
from tools.fileio.rg_subprocess import RipgrepRunnerError, run_ripgrep_lines
from tools.glob_tool.prompt import DESCRIPTION, GLOB_TOOL_NAME

FILE_NOT_FOUND_CWD_NOTE = "Current working directory:"
DEFAULT_LIMIT = 120
# 硬上限：head_limit 传更大值也会被压回，防止一次查询泄洪全库
HARD_MAX_LIMIT = 120
# 超过该命中数且未显式 detail=paths 时自动折叠
_AUTO_FOLD_THRESHOLD = 40
_MAX_FOLD_DIRS = 50
_MAX_SUMMARY_DIRS = 60

# --- 内存 TTL 缓存：相同查询 60s 内直接返回，不重复扫盘 ---
_GLOB_CACHE_TTL_S = 60.0
_GLOB_CACHE_MAX = 128
_glob_cache: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
_glob_cache_lock = threading.Lock()

# --- 统计：监控 agent 命中量与贪婪 glob 习惯 ---
_stats_lock = threading.Lock()
_glob_stats: dict[str, int] = {
	"queries": 0,
	"cache_hits": 0,
	"broad_patterns": 0,
	"truncated": 0,
	"case_retries": 0,
	"files_returned": 0,
	"total_matches": 0,
	"miss_suggestions": 0,
}

# 空结果处置：禁止暗示去 list 全库
_NO_FILES_TIP = (
	"\n\nNo matches. Next steps (do NOT glob `**/*` to explore the repo):\n"
	"- Widen the *name* pattern (e.g. `*Map*` / `*map*.tsx`), not the tree;\n"
	"- Set path to a known subtree (e.g. path=\"gui\");\n"
	"- node_modules/.git/dist and other heavy dirs are already excluded; "
	".gitignore/.ignore and a workspace `.agentignore` are respected;\n"
	"- Do NOT fall back to Bash find/ls to enumerate files — narrow this Glob instead;\n"
	"- Check spelling; case is retried automatically when the first pass is empty."
)


def _truncation_note(shown: int, limit: int, total: int, next_off: int) -> str:
	return (
		f"\nToo many matches (匹配过多，请缩小 glob 表达式): showing {shown} of "
		f"{total} — narrow the glob pattern (add a name/extension fragment, "
		"e.g. `*Map*.tsx`) or set `path` to a subtree instead of paging. "
		f"head_limit is hard-capped at {limit}; next offset={next_off} only if "
		"you truly need the next slice."
	)

def clear_glob_cache() -> None:
	with _glob_cache_lock:
		_glob_cache.clear()


def _glob_cache_get(key: tuple) -> Any | None:
	now = time.monotonic()
	with _glob_cache_lock:
		item = _glob_cache.get(key)
		if item is None:
			return None
		expires_at, value = item
		if now >= expires_at:
			_glob_cache.pop(key, None)
			return None
		_glob_cache.move_to_end(key)
		return value


def _glob_cache_put(key: tuple, value: Any) -> None:
	with _glob_cache_lock:
		_glob_cache[key] = (time.monotonic() + _GLOB_CACHE_TTL_S, value)
		_glob_cache.move_to_end(key)
		while len(_glob_cache) > _GLOB_CACHE_MAX:
			_glob_cache.popitem(last=False)


def glob_stats() -> dict[str, int]:
	"""累计统计快照：queries / cache_hits / broad_patterns（贪婪 glob）/ truncated /
	case_retries / files_returned / total_matches / miss_suggestions。供遥测或 router 暴露。"""
	with _stats_lock:
		return dict(_glob_stats)


def reset_glob_stats() -> None:
	with _stats_lock:
		for k in _glob_stats:
			_glob_stats[k] = 0


def _bump_stat(key: str, n: int = 1) -> None:
	with _stats_lock:
		_glob_stats[key] = _glob_stats.get(key, 0) + n


def _aborted(abort: "AbortController | None") -> bool:
	return abort is not None and bool(getattr(abort, "aborted", False))


_BROAD_EXACT = frozenset({
	"*",
	"**",
	"**/*",
	"**/**",
	"./*",
	"./**",
	"./**/*",
	"./**/**",
})


def get_cwd() -> str:
	return os.getcwd()


def expand_path(path: str) -> str:
	return os.path.abspath(os.path.expanduser(path))


def to_relative_path(path: str, base: Optional[str] = None) -> str:
	if base is None:
		base = get_cwd()
	try:
		return os.path.relpath(path, base)
	except ValueError:
		return path


def suggest_path_under_cwd(target_path: str, *, cwd: str | None = None) -> Optional[str]:
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
			if os.path.isdir(full) and name.lower() == want_name:
				return full
	except OSError:
		pass
	return None


def check_read_permission_for_tool(*args: Any, **kwargs: Any) -> bool:
	return filesystem.check_read_permission_for_tool(*args, **kwargs)


def is_broad_pattern(pattern: str) -> bool:
	"""过宽/贪婪：文件名部分没有固定名字线索（去掉 * 后不含任何字母数字）。

	目录前缀不豁免——`gui/**/*` 和 `**/*` 一样是全子树泄洪，判断落在
	最后一段（文件名部分）上：`**/*.tsx`、`*Map*` 有名字线索 → 放行；
	`gui/**/*`、`src/**`、`*.*`、`?` 无名字线索 → 贪婪，返回目录摘要。
	"""
	p = (pattern or "").strip().replace("\\", "/")
	if not p:
		return True
	while p.startswith("./"):
		p = p[2:]
	if p in _BROAD_EXACT:
		return True
	base = p.rsplit("/", 1)[-1]
	if not any(ch.isalnum() for ch in base.replace("*", "")):
		return True
	return False


def split_pattern_prefix(pattern: str) -> tuple[str, str]:
	"""拆出前导字面目录前缀与剩余名字 pattern：`gui/**/*` → ("gui", "**/*")。

	前缀段不含通配符即视为字面目录；遇到第一个带 `*?[` 的段即停。
	"""
	p = (pattern or "").strip().replace("\\", "/")
	while p.startswith("./"):
		p = p[2:]
	segs = p.split("/")
	prefix_segs: list[str] = []
	for seg in segs[:-1]:
		if not seg or any(ch in seg for ch in "*?["):
			break
		prefix_segs.append(seg)
	if not prefix_segs:
		return "", p
	return "/".join(prefix_segs), "/".join(segs[len(prefix_segs):])


def _pattern_has_letters(pattern: str) -> bool:
	return any(ch.isalpha() for ch in (pattern or ""))


def _exclusion_args(
	root_dir: str,
	ignore_roots: tuple[str, ...],
	*,
	case_insensitive: bool,
) -> list[str]:
	"""内置排除 + .agentignore 过滤参数。

	rg 中 ``--iglob`` 白名单与 ``--glob`` 排除属不同集合、互不按"后者优先"
	覆盖（大小写重试趟的 iglob 白名单会穿透前置排除项），因此 case-insensitive
	时把全部排除项再以 ``--iglob !rule`` 形式后置补一遍，保证压住白名单。
	"""
	args = excluded_dir_globs() + agentignore_args(root_dir, *ignore_roots)
	if case_insensitive:
		for flag, pat in zip(args[::2], args[1::2]):
			if flag == "--glob" and pat.startswith("!"):
				args += ["--iglob", pat]
	return args


def _summary_fresh_enabled() -> bool:
	"""目录摘要新鲜度列（2026-09-09 并入主链路）：默认开，XEYO_GLOB_SUMMARY_FRESH=0 显式关。

	旁路期（默认关）已验证：根级摘要 +0 token（全仓 tracked 静默逐字节一致）、
	scoped 下钻才在零 tracked 目录浮现 `untracked · newest 日期`。默认开无回归面。
	"""
	return os.environ.get("XEYO_GLOB_SUMMARY_FRESH", "1").strip() != "0"


def _stat_mtime_safe(path: str) -> float:
	"""stat 失败（文件被删/权限）返回 0.0，调用方以 0 视为"无数据"。"""
	try:
		return os.stat(path).st_mtime
	except OSError:
		return 0.0


def _tracked_files(root_dir: str) -> set[str] | None:
	"""git index 内的跟踪文件相对路径集合（normcase 归一）。

	方案 D（2026-09-09）：git 跟踪是唯一确定性的"人的策展事实"——文件被
	commit 过 = 人主动声明它是仓库正式状态。git 不可用 / 非 repo → None，
	调用方据此整体静默（无策展事实，日期失去正当性前提）。
	"""
	try:
		proc = subprocess.run(
			["git", "ls-files", "-z"],
			cwd=root_dir,
			capture_output=True,
			timeout=10.0,
		)
	except (OSError, subprocess.SubprocessError):
		return None
	if proc.returncode != 0:
		return None
	out: set[str] = set()
	for raw in proc.stdout.decode("utf-8", "replace").split("\0"):
		if not raw:
			continue
		out.add(os.path.normcase(raw.replace("\\", "/")))
	return out


def summarize_root_dirs(
	root_dir: str,
	*,
	abort: AbortController | None = None,
	ignore_roots: tuple[str, ...] = (),
) -> str:
	"""一层目录 + 文件数（用 rg --files 聚合，尊重排除清单与 .agentignore）。"""
	cmd = ["rg", "--files", "--hidden"]
	cmd.extend(excluded_dir_globs())
	cmd.extend(agentignore_args(root_dir, *ignore_roots))
	cmd.append(".")
	# 新鲜度列（默认开，XEYO_GLOB_SUMMARY_FRESH=0 关），方案 D git 跟踪态分区：
	# 日期只在"人未收编区"（目录内零文件被 git 跟踪）显示——tracked 文件
	# 是人主动 commit 的策展事实，权威区日期是噪声（定稿冻结/代码日均
	# churn）；草稿区没有任何权威版本，"哪版最新"是唯一有意义的迭代问题。
	# 非 git 工作区 → 整体静默（无策展事实，日期失去正当性前提）。
	# 不用目录自身 mtime——Windows 上它只反映直接子项增删，深层修改不
	# 更新，浅信号会给错信息；逐文件 stat 是唯一真值来源。
	fresh = _summary_fresh_enabled()
	# ls-files 与 rg 并行：两者是独立只读子进程，串行白等 ~130ms。
	# 在 rg 启动前先把 git 子进程放出去，rg 扫描期间 git 同步跑。
	tracked_future = None
	pool: ThreadPoolExecutor | None = None
	if fresh:
		pool = ThreadPoolExecutor(max_workers=1)
		tracked_future = pool.submit(_tracked_files, root_dir)
	try:
		all_files = run_ripgrep_lines(
			cmd,
			cwd=root_dir,
			timeout_seconds=30.0,
			abort=abort,
			timeout_message=(
				"Glob directory summary timed out after 30 seconds. "
				"Try a more specific path."
			),
		)
	except RipgrepRunnerError as e:
		raise RuntimeError(str(e)) from e
	finally:
		if pool is not None:
			pool.shutdown(wait=True)  # ls-files ~130ms，rg 期间已跑完，此处不阻塞
	tracked: set[str] | None = tracked_future.result() if tracked_future else None
	if fresh and tracked is None:
		fresh = False  # 非 git / git 不可用 → 全静默
	counts: dict[str, int] = defaultdict(int)
	root_files = 0
	newest: dict[str, float] = {}
	root_newest = 0.0
	tracked_tops: dict[str, int] = defaultdict(int)
	tracked_root = 0
	scanned = 0
	for rel in all_files:
		norm = rel.replace("\\", "/").lstrip("./")
		if not norm:
			continue
		# stat 与 tracked 匹配用未剥点路径——lstrip("./") 会把隐藏目录
		# `.github/` 的名字改成 `github/`（字符级剥离，不是路径语义）。
		# 但 rg 输出可能带 `./` 前缀，直接 normcase 进 tracked 集合必不
		# 匹配（`./mixed/a.py` vs `mixed/a.py`）——所以只按路径语义循环
		# 剥前导 `./`，保留 `.github` 的点。显示名维持 lstrip 既有契约。
		stat_norm = rel.replace("\\", "/")
		while stat_norm.startswith("./"):
			stat_norm = stat_norm[2:]
		if "/" in norm:
			top = norm.split("/", 1)[0] + "/"
			counts[top] += 1
			if fresh and tracked is not None and os.path.normcase(stat_norm) in tracked:
				tracked_tops[top] += 1
		else:
			root_files += 1
			if fresh and tracked is not None and os.path.normcase(stat_norm) in tracked:
				tracked_root += 1

	if fresh and tracked is not None:
		# 两遍法：tracked 目录的 newest 永不显示（_fresh_col 对 >0 静默），
		# 对它们逐文件 stat 是纯浪费。第二遍只 stat 零 tracked 目录 + 根文件
		# （同样仅 tracked_root==0 时才用得上）——输出与全量 stat 逐字节一致。
		zero_tops = {t for t in counts if tracked_tops.get(t, 0) == 0}
		need_root = tracked_root == 0
		for rel in all_files:
			norm = rel.replace("\\", "/").lstrip("./")
			if not norm:
				continue
			stat_norm = rel.replace("\\", "/")
			while stat_norm.startswith("./"):
				stat_norm = stat_norm[2:]
			if "/" in norm:
				top = norm.split("/", 1)[0] + "/"
				if top not in zero_tops:
					continue
				m = _stat_mtime_safe(os.path.join(root_dir, stat_norm))
				if m > newest.get(top, 0.0):
					newest[top] = m
			else:
				if not need_root:
					continue
				m = _stat_mtime_safe(os.path.join(root_dir, stat_norm))
				if m > root_newest:
					root_newest = m
			scanned += 1
			if scanned % 1000 == 0 and _aborted(abort):
				fresh = False  # 中止 → 新鲜度整体省略，摘要退回旧格式
				newest.clear()
				root_newest = 0.0
				break

	def _fresh_col(tracked_count: int, total: int, n: float) -> str:
		if not fresh or tracked is None:
			return ""  # 非 git / 中止 → 静默
		untracked = total - tracked_count
		if tracked_count > 0:
			# 混合目录（B2，2026-09-09）：只报 untracked 计数——纯 git 状态
			# 事实，不带日期（权威区 mtime 是噪声，B2 不重蹈覆辙）。仅真有
			# 未收编文件时付 ~3 tok。
			if untracked > 0:
				return f" · {untracked} untracked"
			return ""  # 权威区（人已 commit）→ 静默
		col = " · untracked"  # 零 tracked：亮出分区事实 + newest（草稿区唯一有意义的问题）
		if n > 0:
			col += f" · newest {time.strftime('%Y-%m-%d', time.localtime(n))}"
		return col

	lines = [
		"Pattern too broad (no file-name fragment, e.g. `*` / `**/*` / "
		"`gui/**/*`) — showing one-level directory summary instead of listing files.",
		"Set path or a name pattern (e.g. `*Map*.tsx`, path=\"gui\").",
		"[STOP] Do NOT use Bash (find/ls/dir) to enumerate files instead — "
		"retry Glob with a name fragment or path.",
		"",
		f"root: {root_dir}",
		f"total files scanned: {len(all_files)}",
	]
	if root_files:
		lines.append(f"./  ({root_files} files{_fresh_col(tracked_root, root_files, root_newest)})")
	for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_MAX_SUMMARY_DIRS]:
		lines.append(
			f"{name}  ({n} files{_fresh_col(tracked_tops.get(name, 0), n, newest.get(name, 0.0))})"
		)
	if len(counts) > _MAX_SUMMARY_DIRS:
		lines.append(f"… +{len(counts) - _MAX_SUMMARY_DIRS} more directories")
	return "\n".join(lines)


def fold_filenames(filenames: list[str], *, max_dirs: int = _MAX_FOLD_DIRS) -> str:
	"""按父目录折叠：dir/ (n files) + 样例。"""
	by_dir: dict[str, list[str]] = defaultdict(list)
	for rel in filenames:
		norm = rel.replace("\\", "/")
		parent = norm.rsplit("/", 1)[0] if "/" in norm else "."
		by_dir[parent].append(norm)

	lines: list[str] = [
		f"Folded view: {len(filenames)} files in {len(by_dir)} directories "
		"(use detail=\"paths\" for a flat list, or narrow path/pattern)."
	]
	items = sorted(by_dir.items(), key=lambda kv: (-len(kv[1]), kv[0]))
	for i, (parent, files) in enumerate(items):
		if i >= max_dirs:
			lines.append(f"… +{len(items) - i} more directories")
			break
		label = parent if parent.endswith("/") or parent == "." else parent + "/"
		lines.append(f"{label}  ({len(files)} files)")
		for sample in files[:3]:
			lines.append(f"  {sample}")
		if len(files) > 3:
			lines.append(f"  … +{len(files) - 3} more")
	return "\n".join(lines)


def _fuzzy_dir_name(target: str, names: list[str]) -> Optional[str]:
	"""匹配与目标最接近的目录名（大小写不敏感，优先前缀/后缀包含）。

	用于 “doc → docs” 这类常见拼写偏差：先按相似度排序，prefix 命中额外加分。
	"""
	low = target.lower()
	best: Optional[str] = None
	best_score = 0.0
	for name in names:
		ln = name.lower()
		score = difflib.SequenceMatcher(None, low, ln).ratio()
		if ln.startswith(low) or low.startswith(ln):
			score += 0.5
		if score > best_score:
			best_score = score
			best = name
	if best is None or best_score < 0.6:
		return None
	return best


def _near_miss_directory(abs_path: str, cwd: str) -> Optional[str]:
	"""``abs_path`` 不存在时，向上找最近存在的祖先，模糊匹配其子目录名，返回近似目录。

	覆盖 workspace 内常见的 ``path="doc"``（实际为 ``docs/``）这类拼写偏差。
	只做本地 os.listdir（无子进程），成本极低。
	"""
	probe = os.path.abspath(abs_path)
	existing = probe
	missing_seg = ""
	while not os.path.exists(existing):
		parent = os.path.dirname(existing)
		if parent == existing:
			break
		missing_seg = os.path.basename(existing)
		existing = parent
	if not missing_seg:
		return None
	try:
		names = [
			name
			for name in os.listdir(existing)
			if os.path.isdir(os.path.join(existing, name))
		]
	except OSError:
		return None
	best = _fuzzy_dir_name(missing_seg, names)
	if best is None:
		return None
	return os.path.join(existing, best)


def _relaxed_glob_suggestion(
	pattern: str,
	root: str,
	*,
	cwd: str,
	limit: int = 5,
) -> Optional[str]:
	"""空结果时用放宽的 glob 反推“真实的目录 + 文件”，拼一句 Did you mean 提示。

	只放宽 ``_``/``-`` 分隔符并把名字锚到任意深度（``doc/agent_b.md`` →
	``**/agent*b.md``），一次命中即可同时纠正目录与文件名两处错位。只发生在
	无匹配分支，命中为空或过吵（无名字线索）则静默返回 None。
	"""
	norm = (pattern or "").strip().replace("\\", "/")
	while norm.startswith("./"):
		norm = norm[2:]
	if not norm or is_broad_pattern(norm):
		return None
	last = norm.rsplit("/", 1)[-1]
	if is_broad_pattern(last):
		return None
	fuzzy_last = last.replace("_", "*").replace("-", "*")
	prefix, _rest = split_pattern_prefix(norm)
	if prefix and os.path.isdir(os.path.join(root, prefix)):
		relaxed = f"{prefix}/**/{fuzzy_last}"
	else:
		relaxed = f"**/{fuzzy_last}"
	try:
		hits, _truncated, _total, _spill = perform_glob(
			pattern=relaxed,
			root_dir=root,
			limit=limit,
			offset=0,
			abort=None,
			case_insensitive=True,
			ignore_roots=(cwd,),
		)
	except RipgrepRunnerError:
		return None
	if not hits:
		return None
	rel_hits = [to_relative_path(os.path.join(root, h), root) for h in hits][:limit]
	dirs = sorted({os.path.dirname(h).replace("\\", "/") or "." for h in rel_hits})
	lines = ["Did you mean:"]
	lines.extend(f"  {h}" for h in rel_hits)
	if prefix and dirs and not any(
		(d == prefix) or d.endswith("/" + prefix) for d in dirs
	):
		lines.append(f"  (searched `{prefix}/`; closest match is under `{dirs[0]}/`)")
	_bump_stat("miss_suggestions")
	return "\n".join(lines)


@dataclass
class GlobInput:
	pattern: str
	path: Optional[str] = None
	head_limit: int = DEFAULT_LIMIT
	offset: int = 0
	detail: str = "auto"  # auto | paths | folded


@dataclass
class GlobOutput:
	filenames: list[str]
	duration_ms: float
	num_files: int
	truncated: bool
	head_limit: int = DEFAULT_LIMIT
	offset: int = 0
	# 预渲染给模型的正文（目录摘要 / folded）；None 则用扁平路径
	rendered: str | None = None
	case_insensitive_retry: bool = False
	broad_summary: bool = False
	folded: bool = False
	cached: bool = False
	total_matches: int = 0
	notes: list[str] = field(default_factory=list)
	suggestion: str | None = None
	# 超限时完整排序列表落盘路径（spill），模型可 Read 回取；None 表示未落盘
	spill_path: str | None = None


def prompt() -> str:
	return DESCRIPTION.strip()


def perform_glob(
	pattern: str,
	root_dir: str,
	*,
	limit: int = DEFAULT_LIMIT,
	offset: int = 0,
	abort: "AbortController | None" = None,
	case_insensitive: bool = False,
	ignore_roots: tuple[str, ...] = (),
	session_id: str = "",
) -> tuple[list[str], bool, int, str | None]:
	"""通过 ripgrep 列出匹配 glob 模式的文件。

	返回 ``(切片, 是否截断, 命中总数, spill_path)``：当命中数超过请求切片且传入
	``session_id`` 时，把完整排序列表落盘到 spill（供模型 Read 回取超限部分），
	否则 ``spill_path`` 为 ``None``。
	"""
	glob_flag = "--iglob" if case_insensitive else "--glob"
	cmd = [
		"rg",
		"--files",
		glob_flag,
		pattern,
		"--sort",
		"modified",
		"--hidden",
	]
	cmd.extend(
		_exclusion_args(root_dir, ignore_roots, case_insensitive=case_insensitive)
	)
	cmd.append(".")
	try:
		all_files = run_ripgrep_lines(
			cmd,
			cwd=root_dir,
			timeout_seconds=30.0,
			abort=abort,
			timeout_message=(
				"Glob search timed out after 30 seconds. "
				"The pattern may match many files; try a more specific "
				"path or pattern."
			),
		)
	except RipgrepRunnerError as e:
		raise RuntimeError(str(e)) from e

	all_files.reverse()
	total = len(all_files)
	sliced = all_files[offset : offset + limit]
	truncated = total > offset + limit
	spill_path: str | None = None
	if truncated and session_id and all_files:
		try:
			from tools.spill import save_text

			spill_path = save_text(session_id, "\n".join(all_files)).path
		except Exception:  # noqa: BLE001 — spill 失败：仅无 full-list 引用，不报错
			spill_path = None
	return sliced, truncated, total, spill_path


class GlobTool:
	name = GLOB_TOOL_NAME
	search_hint = "find files by name pattern or wildcard"
	max_result_size_chars = 100_000

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
						"description": (
							'Glob by name, e.g. "*Map*.tsx" or "src/**/*Button*.ts". '
							"Do NOT use `**/*` or directory-scoped `gui/**/*` to "
							"explore — any pattern without a file-name fragment "
							"returns a directory summary only. Always include a "
							"name/extension fragment + optional path."
						),
					},
					"path": {
						"type": "string",
						"description": (
							"Search root (any allowed directory; default cwd). "
							"Set when the subtree is known—does not lock you to src/."
							' Do not pass "undefined" or "null".'
						),
					},
					"head_limit": {
						"type": "integer",
						"description": (
							f"Max files to return. Default {HARD_MAX_LIMIT}, hard cap "
							f"{HARD_MAX_LIMIT} (larger values are clamped). If truncated, "
							"narrow the pattern/path; offset pages a specific slice."
						),
						"default": DEFAULT_LIMIT,
						"minimum": 1,
						"maximum": HARD_MAX_LIMIT,
					},
					"offset": {
						"type": "integer",
						"description": (
							"Skip this many matches before returning (default 0). "
							"Use after a truncated page."
						),
						"default": 0,
						"minimum": 0,
					},
					"detail": {
						"type": "string",
						"enum": ["auto", "paths", "folded"],
						"description": (
							"auto (default): fold by directory when many hits; "
							"paths: flat list; folded: always group by parent dir."
						),
						"default": "auto",
					},
				},
				"required": ["pattern"],
			},
		}

	def get_path(self, input_data: GlobInput) -> str:
		if input_data.path:
			p = input_data.path.strip()
			if not os.path.isabs(p):
				p = os.path.join(self._cwd, p)
			return expand_path(p)
		return self._cwd

	def validate_input(self, input_data: GlobInput) -> dict[str, Any]:
		if not input_data.pattern or not str(input_data.pattern).strip():
			return {
				"result": False,
				"message": "pattern is required",
				"errorCode": 0,
			}
		if input_data.detail not in ("auto", "paths", "folded"):
			return {
				"result": False,
				"message": 'detail must be "auto", "paths", or "folded"',
				"errorCode": 3,
			}

		if not input_data.path:
			return {"result": True}

		raw = str(input_data.path).strip()
		if raw.lower() in ("undefined", "null", ""):
			return {"result": True}

		abs_path = self.get_path(GlobInput(pattern=input_data.pattern, path=raw))
		if abs_path.startswith("\\\\") or abs_path.startswith("//"):
			return {"result": True}

		if not os.path.exists(abs_path):
			suggestion = _near_miss_directory(abs_path, cwd=self._cwd)
			message = (
				f"Directory does not exist: {raw}. "
				f"{FILE_NOT_FOUND_CWD_NOTE} {self._cwd}."
			)
			if suggestion:
				rel = to_relative_path(suggestion, self._cwd)
				message += f" Did you mean {rel}?"
			return {"result": False, "message": message, "errorCode": 1}

		if not os.path.isdir(abs_path):
			return {
				"result": False,
				"message": f"Path is not a directory: {raw}",
				"errorCode": 2,
			}
		return {"result": True}

	def check_permissions(self, input_data: GlobInput, context: Any = None) -> bool:
		return check_read_permission_for_tool(self, input_data, context)

	def call(
		self,
		input_data: GlobInput,
		*,
		limit: int | None = None,
		offset: int | None = None,
		abort: AbortController | None = None,
		session_id: str = "",
	) -> GlobOutput:
		start = time.time()
		root = self.get_path(input_data)
		head_limit = limit if limit is not None else input_data.head_limit
		head_limit = max(1, min(HARD_MAX_LIMIT, int(head_limit or DEFAULT_LIMIT)))
		off = offset if offset is not None else input_data.offset
		off = max(0, int(off or 0))
		pattern = input_data.pattern.strip()
		detail = input_data.detail or "auto"

		# --- 2) 过宽 pattern → 目录摘要（贪婪 glob：计数 + 缓存） ---
		if is_broad_pattern(pattern):
			_bump_stat("queries")
			_bump_stat("broad_patterns")
			# 带字面目录前缀（如 gui/**/*）时，摘要限定到该子树
			prefix, _rest = split_pattern_prefix(pattern)
			summary_root = root
			scope_note = ""
			if prefix:
				candidate = os.path.join(root, prefix)
				if os.path.isdir(candidate):
					summary_root = candidate
					scope_note = (
						f"\nPattern scope: `{prefix}/` — the summary covers only "
						f'that subtree. To search it, set path="{prefix}" with a '
						f"name pattern (e.g. `{prefix}/**/*.<ext>`)."
					)
			summary_key: tuple = ("summary", summary_root)
			cached_text = _glob_cache_get(summary_key)
			if cached_text is not None:
				_bump_stat("cache_hits")
				text = cached_text
			else:
				text = summarize_root_dirs(
					summary_root, abort=abort, ignore_roots=(self._cwd,)
				)
				if not _aborted(abort):
					_glob_cache_put(summary_key, text)
			if scope_note:
				text = text + scope_note
			return GlobOutput(
				filenames=[],
				duration_ms=(time.time() - start) * 1000,
				num_files=0,
				truncated=False,
				head_limit=head_limit,
				offset=off,
				rendered=text,
				broad_summary=True,
				cached=cached_text is not None,
			)

		_bump_stat("queries")
		# --- 4) TTL 缓存：相同 (pattern, root, limit, offset) 60s 内不重扫 ---
		# 大小写重试的结果一并烘焙进缓存：命中即零磁盘扫描。
		scan_key: tuple = ("files", pattern, root, head_limit, off)
		cached_scan = _glob_cache_get(scan_key)
		case_retry = False
		spill_path: str | None = None
		if cached_scan is not None:
			files, truncated, total, case_retry, spill_path = cached_scan
			_bump_stat("cache_hits")
		else:
			files, truncated, total, spill_path = perform_glob(
				pattern=pattern,
				root_dir=root,
				limit=head_limit,
				offset=off,
				abort=abort,
				case_insensitive=False,
				ignore_roots=(self._cwd,),
				session_id=session_id,
			)
			# --- 1) 空结果 + 含字母 → iglob 重试 ---
			if not files and off == 0 and _pattern_has_letters(pattern):
				files, truncated, total, spill_path = perform_glob(
					pattern=pattern,
					root_dir=root,
					limit=head_limit,
					offset=off,
					abort=abort,
					case_insensitive=True,
					ignore_roots=(self._cwd,),
					session_id=session_id,
				)
				case_retry = bool(files)
				if case_retry:
					_bump_stat("case_retries")
			if not _aborted(abort):
				_glob_cache_put(
					scan_key, (files, truncated, total, case_retry, spill_path)
				)

		# --- 5) 统计：磁盘命中量只计真实扫描；files_returned 计每次交付 ---
		if cached_scan is None:
			_bump_stat("total_matches", total)
		_bump_stat("files_returned", len(files))
		if truncated:
			_bump_stat("truncated")

		filenames = [to_relative_path(os.path.join(root, f), root) for f in files]
		notes: list[str] = []
		if case_retry:
			notes.append(
				"(Case-insensitive retry: first pass had 0 matches; "
				"showing --iglob results.)"
			)

		# --- 3) 折叠 ---
		use_fold = False
		if filenames:
			if detail == "folded":
				use_fold = True
			elif detail == "auto" and len(filenames) >= _AUTO_FOLD_THRESHOLD:
				use_fold = True
			elif detail == "auto" and "**" in pattern.replace("\\", "/") and len(filenames) >= 20:
				use_fold = True

		rendered: str | None = None
		if use_fold:
			rendered = fold_filenames(filenames)
			if notes:
				rendered = "\n".join(notes) + "\n\n" + rendered
			if truncated:
				rendered += _truncation_note(
					len(filenames), head_limit, total, off + head_limit
				)

		suggestion = None
		if not filenames:
			sug_key = ("suggestion", pattern, root, self._cwd)
			cached_sug = _glob_cache_get(sug_key)
			if cached_sug is not None:
				suggestion = cached_sug[1]
			else:
				suggestion = _relaxed_glob_suggestion(pattern, root, cwd=self._cwd)
				# 空结果建议会再触发一次放松 pattern 的全量扫描；缓存该结果
				# （含 None，避免相同无匹配查询 60s 内重复扫盘）。
				_glob_cache_put(sug_key, (suggestion is not None, suggestion))

		return GlobOutput(
			filenames=filenames,
			duration_ms=(time.time() - start) * 1000,
			num_files=len(filenames),
			truncated=truncated,
			head_limit=head_limit,
			offset=off,
			rendered=rendered,
			case_insensitive_retry=case_retry,
			folded=use_fold,
			cached=cached_scan is not None,
			total_matches=total,
			notes=notes,
			suggestion=suggestion,
			spill_path=spill_path,
		)

	@staticmethod
	def map_tool_result_to_content(output: GlobOutput) -> str:
		if output.rendered is not None:
			text = output.rendered
		elif not output.filenames:
			text = "No files found" + _NO_FILES_TIP
			if output.suggestion:
				text += "\n\n" + output.suggestion
		else:
			lines = list(output.notes)
			if not output.truncated:
				found = output.num_files
				lines.append(f"Found {found} file{'s' if found != 1 else ''}")
			lines += list(output.filenames)
			if output.truncated:
				lines.append(
					_truncation_note(
						len(output.filenames),
						output.head_limit,
						output.total_matches or len(output.filenames),
						output.offset + output.head_limit,
					).lstrip("\n")
					+ " Do not fall back to `**/*`."
				)
			text = "\n".join(lines)
		if output.spill_path and output.total_matches:
			text += (
				f"\n\nComplete match list ({output.total_matches} paths) saved to: "
				f"{output.spill_path} — use Read to open."
			)
		return text

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()

		raw_path = input.get("path")
		path: str | None
		if isinstance(raw_path, str) and raw_path.strip().lower() not in (
			"",
			"undefined",
			"null",
		):
			path = raw_path.strip()
		else:
			path = None

		head_limit = DEFAULT_LIMIT
		raw_limit = input.get("head_limit", input.get("limit"))
		if raw_limit is not None and raw_limit != "":
			try:
				head_limit = max(1, min(HARD_MAX_LIMIT, int(raw_limit)))
			except (TypeError, ValueError):
				head_limit = DEFAULT_LIMIT

		offset = 0
		raw_offset = input.get("offset")
		if raw_offset is not None and raw_offset != "":
			try:
				offset = max(0, int(raw_offset))
			except (TypeError, ValueError):
				offset = 0

		detail_raw = str(input.get("detail") or "auto").strip().lower()
		detail = detail_raw if detail_raw in ("auto", "paths", "folded") else "auto"

		glob_input = GlobInput(
			pattern=str(input.get("pattern") or ""),
			path=path,
			head_limit=head_limit,
			offset=offset,
			detail=detail,
		)

		validation = self.validate_input(glob_input)
		if not validation.get("result"):
			return ToolResult(
				content=str(validation.get("message") or "invalid input"),
				is_error=True,
			)

		if not self.check_permissions(glob_input):
			return ToolResult(content="permission denied", is_error=True)

		abort.raise_if_aborted()
		from engine.workspace_context import get_workspace_context

		_wctx = get_workspace_context()
		session_id = _wctx.session_id if _wctx is not None else ""
		try:
			output = await asyncio.to_thread(
				self.call,
				glob_input,
				limit=head_limit,
				offset=offset,
				abort=abort,
				session_id=session_id,
			)
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=str(e), is_error=True)

		abort.raise_if_aborted()
		# metadata 恒上报单次命中量（GUI/遥测可消费）；键保持向后兼容
		meta: dict[str, Any] = {
			"num_files": output.num_files,
			"truncated": output.truncated,
			"cached": output.cached,
		}
		if output.total_matches:
			meta["total_matches"] = output.total_matches
		if output.broad_summary:
			meta["glob_kind"] = "dir_summary"
			meta["greedy_pattern"] = True
		elif output.folded:
			meta["glob_kind"] = "folded"
		elif not output.filenames:
			meta["no_match"] = True
			if output.suggestion:
				meta["suggestion"] = True
		if output.case_insensitive_retry:
			meta["case_insensitive_retry"] = True
		if output.spill_path:
			meta["glob_full_list_path"] = output.spill_path
		return ToolResult(
			content=self.map_tool_result_to_content(output),
			metadata=meta,
		)
