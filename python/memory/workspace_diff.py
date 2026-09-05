"""workspace_diff — 晋升佐证：工作区「相对上次成功晋升基线」的改动 diff。

- 记忆域内维护基线（XEYO 用 ``nightshift.json`` 记 baseline_sha，非 git 仓库）；
- 晋升时生成一次 ``~/.xeyo/memory/{wsid}/phase2_workspace_diff.md``，4MB 字符边界截断
  （``[workspace diff truncated at N bytes]`` 尾部标记）；
- **只在 NightShift 晋升时做一次**（红线②：绝不做每轮 git 重比对）；
- git 不可用 / 非 git 工作区 / 无改动 → 返回 None / 空路径集（无佐证即不降权，
  原门禁行为不变 —— 红线①）。

本模块不做任何晋升决策；决策仍在 governance.can_promote。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

MAX_BYTES = 4 * 1024 * 1024
ARTIFACT_NAME = "phase2_workspace_diff.md"

# 候选正文/证据里的路径 token：优先带目录/反斜杠的路径，再兜底裸文件名
# （裸文件名要求形如 a.py 的扩展名形态，避免把 v2.3 之类的版本号当路径）。
_PATH_TOKEN = re.compile(
	r"[\\/][\w.\-\\/]+?\.\w{1,8}"
	r"|[\w.\-]+(?:/[\w.\-]+)+\.\w{1,8}"
	r"|\b[A-Za-z_][\w\-]*\.[A-Za-z]\w{0,7}\b"
)


@dataclass
class WorkspaceDiff:
	"""一次收集的改动佐证：路径集 + 有界正文 + 是否截断。"""

	paths: list[str] = field(default_factory=list)
	text: str = ""
	truncated: bool = False
	baseline_sha: str = ""
	head_sha: str = ""


def _run_git(cwd: Path, args: list[str], *, timeout: float = 10.0) -> str | None:
	"""跑 git 命令；任何失败返回 None（尽力而为，绝不阻塞/不抛）。"""
	try:
		proc = subprocess.run(
			["git", "-C", str(cwd), *args],
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="replace",
			timeout=timeout,
		)
	except (OSError, subprocess.SubprocessError):
		return None
	if proc.returncode != 0:
		return None
	return proc.stdout or ""


def git_head(cwd: str | None) -> str:
	"""当前 HEAD sha；非 git 返回空串。"""
	if not cwd:
		return ""
	out = _run_git(Path(cwd), ["rev-parse", "--verify", "HEAD"])
	return (out or "").strip().splitlines()[0] if out else ""


def _changed_paths(cwd: Path, baseline_sha: str) -> list[str]:
	"""相对基线的改动路径：``git diff --name-only <base>``（含基线后的提交与未提交）
	+ ``status --porcelain``（兜底 untracked / 重命名）。无基线时只列工作区未提交改动。

	输出统一为仓库相对路径（porcelain 的引号/重命名格式按需剥离）。
	"""
	paths: list[str] = []
	if baseline_sha:
		out = _run_git(cwd, ["diff", "--name-only", baseline_sha])
	else:
		out = _run_git(cwd, ["diff", "--name-only", "HEAD"])
	if out:
		paths.extend(p for p in out.splitlines() if p.strip())
	# 工作区改动（staged + unstaged + untracked）
	porcelain = _run_git(cwd, ["status", "--porcelain"])
	if porcelain:
		for line in porcelain.splitlines():
			if len(line) < 4:
				continue
			raw = line[3:].strip()
			if raw.startswith('"') or raw.startswith("'") or " -> " in raw:
				# 重命名/引号路径：取箭头后或去引号
				if " -> " in raw:
					raw = raw.split(" -> ", 1)[1]
			raw = raw.strip('"').strip("'")
			if raw and raw not in paths:
				paths.append(raw)
	return paths


def _bounded_text(text: str, *, max_bytes: int = MAX_BYTES) -> tuple[str, bool]:
	"""按字节截断到 max_bytes（utf-8 边界安全：忽略不完整尾部字符）；截断时追加标记。"""
	if not text:
		return text, False
	if len(text.encode("utf-8")) <= max_bytes:
		return text, False
	chunk = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
	return chunk.rstrip() + "\n[workspace diff truncated at %d bytes]\n" % max_bytes, True


def _diff_text(cwd: Path, baseline_sha: str, *, max_bytes: int = MAX_BYTES) -> tuple[str, bool]:
	"""相对基线的有界 unified diff 文本（基线..当前工作树，含未提交改动）。"""
	target = [baseline_sha] if baseline_sha else ["HEAD"]
	out = _run_git(cwd, ["diff", "--stat", *target])
	if out:
		stat = out.rstrip() + "\n\n"
	else:
		stat = ""
	body = _run_git(cwd, ["diff", *target]) or ""
	# 上界：stat 与 body 合计受 max 限制
	text = "# Memory workspace diff (evidence aid)\n\n" + stat
	if len(text) + len(body) > max_bytes:
		allowed = max(0, max_bytes - len(text))
		body, _trunc = _bounded_text(body, max_bytes=allowed)
		return text + body, True
	return text + body, False


def collect(cwd: str | None, baseline_sha: str = "", *, max_bytes: int = MAX_BYTES) -> WorkspaceDiff | None:
	"""收集一次改动佐证；非 git / 不可用 / 无改动 → 返回 None（无证据、不降权）。"""
	if not cwd or not Path(cwd).is_dir():
		return None
	root = Path(cwd)
	head = git_head(str(root))
	if not head:
		return None
	paths = _changed_paths(root, baseline_sha)
	if not paths:
		return None
	text, truncated = _diff_text(root, baseline_sha, max_bytes=max_bytes)
	return WorkspaceDiff(
		paths=paths,
		text=text,
		truncated=truncated,
		baseline_sha=baseline_sha,
		head_sha=head,
	)


# --------------------------------------------------------------------------- #
# 记忆域内的 diff 工件（~/.xeyo/memory/{wsid}/phase2_workspace_diff.md）
# --------------------------------------------------------------------------- #


def _artifact_path(wsid: str) -> Path:
	from memory.memdir import memdir_root

	return memdir_root(wsid) / ARTIFACT_NAME


def write_artifact(wsid: str, diff: WorkspaceDiff) -> Path | None:
	"""把佐证写入工件（原子替换）；失败返回 None（增强项，不阻塞）。"""
	if diff is None:
		return None
	try:
		path = _artifact_path(wsid)
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(".md.tmp")
		tmp.write_text(diff.text, encoding="utf-8")
		os.replace(tmp, path)
		return path
	except OSError:
		return None


def remove_artifact(wsid: str) -> None:
	"""删除工件（基线推进后清除，防止旧证据混入下一次）。"""
	try:
		_artifact_path(wsid).unlink(missing_ok=True)
	except OSError:
		pass


def load_artifact_paths(wsid: str) -> set[str]:
	"""读工件里的路径集（粗粒度：匹配所有形如 a/b.c 的行 token）。"""
	path = _artifact_path(wsid)
	if not path.is_file():
		return set()
	try:
		raw = path.read_text(encoding="utf-8")
	except OSError:
		return set()
	out: set[str] = set()
	for line in raw.splitlines():
		s = line.strip()
		if s.startswith("- ") and " " in s and "\t" not in s:
			s = s[2:]
		m = _PATH_TOKEN.search(s)
		if m:
			out.add(m.group(0).strip("/\\").replace("\\", "/"))
	return out


def candidate_path_tokens(content: str, evidence: Iterable[str]) -> set[str]:
	"""从候选正文与证据里抽路径 token（供 diff 命中判定）。"""
	out: set[str] = set()
	for src in (content or "", *(e or "" for e in evidence)):
		if not src:
			continue
		if src.startswith("path:"):
			out.add(src[len("path:") :].strip().replace("\\", "/"))
			continue
		for m in _PATH_TOKEN.findall(src):
			out.add(m.strip("/\\").replace("\\", "/"))
	return out


def matches(candidate_paths: set[str], diff_paths: set[str]) -> bool:
	"""路径命中判定：精确 / 后缀包含 / 基线名相等（裸文件名 >=5 字符才比，防误报）。

	- 候选 token 与 diff 路径逐条比对（都按仓库相对路径归一化）；
	- ``cp == dp`` 或 ``dp`` 以 ``/cp`` 结尾 → 命中；
	- 基名相等且基名长度 >= 5（如 run.py / src/run.py 命中；v2.py 这类短名不误伤）。
	"""
	if not candidate_paths or not diff_paths:
		return False
	for cp in candidate_paths:
		cp = (cp or "").strip().lstrip("/").replace("\\", "/")
		if not cp:
			continue
		base = cp.split("/")[-1]
		for dp in diff_paths:
			d = (dp or "").strip().lstrip("/").replace("\\", "/")
			if not d:
				continue
			if cp == d or d.endswith("/" + cp):
				return True
			db = d.split("/")[-1]
			if base == db and len(base) >= 5:
				return True
	return False
