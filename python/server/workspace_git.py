"""工作区 Git 只读服务：status / log / branches / 单文件 diff。

针对「XEYO 工作区」的 git 分区与功能区 Git 面板，只读、有超时、不污染用户仓库
（GIT_TERMINAL_PROMPT=0，绝无交互）；仅作用于工作区根目录的仓库。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

_GIT_TIMEOUT_S = 20
_DIFF_MAX_CHARS = 400_000
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}

# porcelain 首字符 → 中文标签
_INDEX_LABELS = {"M": "修改", "A": "新增", "D": "删除", "R": "重命名", "C": "复制", "U": "冲突", "?": "未知"}
_WORKTREE_LABELS = {"M": "修改", "D": "删除", "U": "冲突", "?": "未跟踪"}


class GitBinaryMissing(RuntimeError):
	"""系统未安装 git 或不在 PATH 中。"""


class GitError(RuntimeError):
	"""未识别的 git 失败（非超时、非仓库缺失）。"""


def _env() -> dict[str, str]:
	env = os.environ.copy()
	env["GIT_TERMINAL_PROMPT"] = "0"
	env.setdefault("GIT_OPTIONAL_LOCKS", "0")
	env["GIT_PAGER"] = "cat"
	return env


def _run_git(root: Path, args: list[str], timeout: int = _GIT_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
	if not (root / ".git").exists():
		raise GitError("not a git repository")
	try:
		return subprocess.run(
			["git", "-C", str(root), "-c", "color.ui=false", "-c", "core.quotepath=false", *args],
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="replace",
			timeout=timeout,
			env=_env(),
			cwd=str(root),
			check=False,
		)
	except FileNotFoundError as e:
		raise GitBinaryMissing("git 未安装或不在 PATH 中") from e
	except subprocess.TimeoutExpired as e:
		raise GitError("git 超时") from e


def _check(root: Path) -> Path:
	root = Path(root).expanduser().resolve()
	if not root.is_dir():
		raise FileNotFoundError(f"workspace not found: {root}")
	return root


def is_repo(cwd: str) -> bool:
	root = Path(cwd).expanduser().resolve()
	# 避免只差一个文件就误判：用 git rev-parse --is-inside-work-tree 判断。
	if not (root / ".git").exists():
		return False
	try:
		proc = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
		return proc.returncode == 0
	except (GitBinaryMissing, GitError):
		return False


def _porcelain(paths: list[str]) -> dict[str, Any]:
	staged: list[dict[str, Any]] = []
	unstaged: list[dict[str, Any]] = []
	untracked: list[dict[str, Any]] = []
	for line in paths:
		if len(line) < 4:
			continue
		x, y, entry = line[0], line[1], line[3:]
		if " -> " in entry:
			entry = entry.rsplit(" -> ", 1)[-1]
		if x == "?" and y == "?":
			untracked.append({"path": entry, "status": "未跟踪"})
			continue
		item: dict[str, Any] = {
			"path": entry,
			"index": x,
			"worktree": y,
			"status": (x == " " or x == "?") and _WORKTREE_LABELS.get(y) or _INDEX_LABELS.get(x),
		}
		if x != " " and x != "?":
			staged.append(item)
		if y != " " and y != "?":
			unstaged.append(item)
	return {"staged": staged, "unstaged": unstaged, "untracked": untracked}


def read_git_status(cwd: str) -> dict[str, Any]:
	"""单次 git 调用同时取回状态与分支（status -b 的 ## 头行）。

	原实现为 is_repo + status + rev-parse branch + rev-parse HEAD 共 4 个
	子进程，Windows 上每次 ~300ms；前端面板轮询时开销被放大。现在只 spawn
	一次；HEAD 短哈希不再随本端点返回。
	"""
	root = _check(cwd)
	if not (root / ".git").exists():
		return {"ok": True, "repo": False, "cwd": str(root)}
	result = _run_git(
		root,
		["status", "--porcelain=v1", "-b", "--untracked-files=all"],
		timeout=10,
	)
	if result.returncode != 0:
		err = (result.stderr or result.stdout or "").lower()
		if "not a git repository" in err:
			return {"ok": True, "repo": False, "cwd": str(root)}
		raise GitError((result.stderr or result.stdout or "git status failed")[:500])
	branch = ""
	entry_lines: list[str] = []
	for line in result.stdout.splitlines():
		if line.startswith("## "):
			info = line[3:].strip()
			if info.startswith("HEAD"):  # detach / 无提交仓库
				branch = "(no branch)"
			else:
				branch = info.split("...", 1)[0].split(" ", 1)[0] or "(no branch)"
			continue
		entry_lines.append(line)
	porcelain = _porcelain(entry_lines)
	return {
		"ok": True,
		"repo": True,
		"cwd": str(root),
		"branch": branch or "(no branch)",
		"head": "",
		"clean": not (porcelain["staged"] or porcelain["unstaged"] or porcelain["untracked"]),
		"counts": {
			"staged": len(porcelain["staged"]),
			"unstaged": len(porcelain["unstaged"]),
			"untracked": len(porcelain["untracked"]),
		},
		**porcelain,
	}


def read_git_log(cwd: str, limit: int = 20) -> dict[str, Any]:
	root = _check(cwd)
	if not is_repo(cwd):
		return {"ok": True, "repo": False, "cwd": str(root), "commits": []}
	result = _run_git(
		root,
		[
			"log",
			"-n",
			str(max(1, min(limit, 500))),
			"--pretty=format:%H%x01%h%x01%an%x01%ad%x01%s",
			"--date=format:%Y-%m-%d %H:%M",
		],
		timeout=15,
	)
	if result.returncode != 0:
		raise GitError((result.stderr or "git log failed")[:500])
	commits: list[dict[str, Any]] = []
	for line in result.stdout.splitlines():
		parts = line.split("\x01")
		if len(parts) < 5:
			continue
		commits.append(
			{
				"hash": parts[0],
				"short": parts[1],
				"author": parts[2],
				"date": parts[3],
				"subject": parts[4],
			}
		)
	return {"ok": True, "repo": True, "cwd": str(root), "commits": commits}


def read_git_branches(cwd: str) -> dict[str, Any]:
	root = _check(cwd)
	if not is_repo(cwd):
		return {"ok": True, "repo": False, "cwd": str(root), "current": None, "branches": []}
	result = _run_git(root, ["branch", "--format=%(HEAD)%09%(refname:short)"], timeout=10)
	if result.returncode != 0:
		raise GitError((result.stderr or "git branch failed")[:500])
	branches: list[str] = []
	current: str | None = None
	for line in result.stdout.splitlines():
		if not line.strip():
			continue
		mark, rest = line.split("\t", 1) if "\t" in line else (" ", line)
		rest = rest.strip()
		if not rest:
			continue
		branches.append(rest)
		if mark.strip() == "*":
			current = rest
	return {"ok": True, "repo": True, "cwd": str(root), "current": current, "branches": branches}


def _looks_binary(sample: bytes) -> bool:
	if not sample:
		return False
	if b"\x00" in sample:
		return True
	ctrl = sum(1 for b in sample if b < 9 or 13 < b < 32)
	return ctrl / max(len(sample), 1) > 0.3


def read_file_diff(cwd: str, rel: str) -> dict[str, Any]:
	"""单文件 vs HEAD 的统一 diff（含暂存+未暂存）。未跟踪文件合成 +diff。"""
	root = _check(cwd)
	from server.workspace_fs import resolve_in_workspace

	target = resolve_in_workspace(cwd, rel)
	if not target.is_file():
		raise FileNotFoundError(f"file not found: {target}")
	if not is_repo(cwd):
		return {"ok": True, "repo": False, "path": rel, "kind": "none", "diff": None}
	try:
		relative = target.relative_to(root)
	except ValueError:
		raise PermissionError("path outside workspace")
	posix = relative.as_posix()

	# 未跟踪：合成 “new file” diff。
	tracked = _run_git(root, ["ls-files", "--error-unmatch", "--", posix], timeout=10)
	untracked = tracked.returncode != 0
	if untracked:
		raw = target.read_bytes()
		if target.suffix.lower() in _IMAGE_EXT or _looks_binary(raw[:8192]):
			return {"ok": True, "repo": True, "path": posix, "kind": "binary", "diff": None}
		text = raw.decode("utf-8", errors="replace")
		lines = text.splitlines()
		diff_lines = [
			f"diff --git a/{posix} b/{posix}",
			"new file mode 100644",
			"--- /dev/null",
			f"+++ b/{posix}",
		]
		diff_lines.append(f"@@ -0,0 +1,{len(lines)} @@")
		diff_lines.extend(f"+{line}" for line in lines[: _DIFF_MAX_CHARS // 2])
		diff = "\n".join(diff_lines)
		return {"ok": True, "repo": True, "path": posix, "kind": "untracked", "diff": diff[: _DIFF_MAX_CHARS]}

	result = _run_git(
		root,
		["diff", "--no-ext-diff", "--no-color", "--unified=3", "HEAD", "--", posix],
		timeout=15,
	)
	if result.returncode != 0:
		raise GitError((result.stderr or "git diff failed")[:500])
	return {
		"ok": True,
		"repo": True,
		"path": posix,
		"kind": "diff" if result.stdout.strip() else "unchanged",
		"diff": (result.stdout.strip() + ("\n" if result.stdout.strip() else ""))[: _DIFF_MAX_CHARS],
	}


def _list_untracked(root: Path) -> list[str]:
	"""未跟踪文件路径（独立只读子进程，可与 diff 并行）。失败返回空列表。"""
	try:
		ut = _run_git(
			root,
			["ls-files", "--others", "--exclude-standard"],
			timeout=10,
		)
		if ut.returncode == 0:
			return [ln.strip().replace("\\", "/") for ln in ut.stdout.splitlines() if ln.strip()]
	except (GitBinaryMissing, GitError):
		pass
	return []


def _diff_hunks_text(root: Path) -> str | None:
	"""相对 HEAD 的 --unified=0 diff 文本（独立只读子进程）。失败返回 None。"""
	try:
		result = _run_git(
			root,
			["diff", "--no-ext-diff", "--no-color", "--unified=0", "HEAD"],
			timeout=15,
		)
	except (GitBinaryMissing, GitError):
		return None
	if result.returncode != 0:
		return None
	return result.stdout


def read_changed_hunks(cwd: str) -> dict[str, Any]:
	"""相对 HEAD 的变更行号范围（含暂存+工作区）；未跟踪文件只列路径。

	返回::
	  {
	    "ok": True, "repo": True,
	    "hunks": { "path/to.py": [(start, end), ...], ... },  # 1-indexed 含
	    "untracked": ["new.py", ...],
	  }
	失败/非仓库时返回空 hunks（调用方应降级）。
	"""
	root = _check(cwd)
	if not (root / ".git").exists():
		return {"ok": True, "repo": False, "hunks": {}, "untracked": []}

	hunks: dict[str, list[tuple[int, int]]] = {}

	# ls-files 与 diff 相互独立：并行跑，省掉一次串行进程开销（大仓库 ~40ms）。
	# 只读 git 命令并发安全（编辑器常驻 status 就是这个模式）。
	from concurrent.futures import ThreadPoolExecutor

	with ThreadPoolExecutor(max_workers=2) as pool:
		fut_ut = pool.submit(_list_untracked, root)
		fut_diff = pool.submit(_diff_hunks_text, root)
		untracked = fut_ut.result()
		diff_text = fut_diff.result()

	if diff_text is None:
		return {"ok": True, "repo": True, "hunks": {}, "untracked": untracked[:50]}

	current: str | None = None
	for line in diff_text.splitlines():
		if line.startswith("diff --git "):
			# 形如 diff --git a/path b/path 的头行
			parts = line.split(" b/", 1)
			if len(parts) == 2:
				current = parts[1].strip()
				hunks.setdefault(current, [])
			else:
				current = None
			continue
		if line.startswith("+++ b/"):
			current = line[6:].strip()
			if current != "/dev/null":
				hunks.setdefault(current, [])
			continue
		if current is None or current == "/dev/null":
			continue
		# hunk 头 @@ -old,count +new,count @@ 或 @@ -old +new @@
		if line.startswith("@@"):
			rng = _parse_unified_new_range(line)
			if rng is not None:
				hunks.setdefault(current, []).append(rng)

	# 删除空文件键
	hunks = {k: v for k, v in hunks.items() if v and k != "/dev/null"}
	return {
		"ok": True,
		"repo": True,
		"hunks": hunks,
		"untracked": untracked[:50],
	}


def _parse_unified_new_range(hunk_header: str) -> tuple[int, int] | None:
	"""从 @@ -a,b +c,d @@ 解析新文件侧 (start, end)，1-indexed 含端点。"""
	import re

	m = re.search(r"\+(\d+)(?:,(\d+))?", hunk_header)
	if not m:
		return None
	start = int(m.group(1))
	count = int(m.group(2)) if m.group(2) is not None else 1
	if count <= 0:
		# 纯删除：无新行
		return None
	return (start, start + count - 1)
