"""交互命令预检（快速失败）— 只拦「会挂在等 TTY/编辑器」的形态。

职责边界（冻结）：
- 危险操作分级（rm -rf / chmod 等）归 ``permissions/bash_policy`` 的 ASK/DENY，
  本层不做危险判断、不重复拦截。
- 运行环境事实：stdin=DEVNULL —— 等 stdin 的提示会立即 EOF，不会挂；真正会挂的
  是等 TTY/编辑器的形态：全屏编辑器/分页器、git 编辑器类子命令、容器工具 -it。
- 原则：**宁漏勿误伤**。已知漏判（接受）：shell 别名/函数、``--interactive``/
  ``--tty`` 长旗标、``sh -c "vim …"`` 包裹、git 全路径调用。
  误伤零容忍：``python -m pytest``/``npm install`` 等常规命令必须放行
  （tests/test_precheck.py 作回归锁）。
"""

from __future__ import annotations

import re

from tools.bash_tool.semantics import (
	_git_subcommand,
	_split_segment,
	extract_base_command,
)

#: 全屏 TTY 程序：非交互管道里必然无意义，会挂到 timeout
_FULLSCREEN = frozenset({
	"vim", "nvim", "vi", "nano", "pico", "emacs",
	"less", "more", "most", "man", "top", "htop", "btop",
})

#: 会因 -it 分配 TTY 而挂起的容器/集群工具
_TTY_TOOLS = frozenset({"docker", "podman", "nerdctl", "kubectl", "docker-compose"})

#: 短旗标里带 m/F 的组合（-m / -am / -F / -aF …）都算"给了提交信息"
_COMMIT_MSG_RE = re.compile(r"^-[A-Za-z]*[mF]")


def _segments(cmd: str) -> list[str]:
	"""按 && || | ; 轻量切段（仅判定用，非安全边界）。"""
	segs = _split_segment(cmd)
	return segs if segs else [cmd]


def _fullscreen_block(cmd: str) -> str | None:
	for seg in _segments(cmd):
		base = extract_base_command(seg)
		if base in _FULLSCREEN:
			return (
				f"'{base}' takes over the TTY and cannot run in a non-interactive "
				"pipeline; it will hang until timeout"
			)
	return None


def _tty_flag_block(cmd: str) -> str | None:
	for seg in _segments(cmd):
		base = extract_base_command(seg)
		if base not in _TTY_TOOLS:
			continue
		toks = set(seg.split())
		if "-it" in toks or "-ti" in toks or ("-i" in toks and "-t" in toks):
			return (
				f"{base} with -it allocates a TTY and will hang; drop -t "
				"(keep -i for piped stdin) or pass a non-interactive command"
			)
	return None


def _has_commit_style_msg(toks: list[str]) -> bool:
	"""-m/-F 及组合短旗标（-am 等）或对应长旗标均视为已给信息。"""
	for t in toks[1:]:
		if t.startswith("--"):
			if t.split("=", 1)[0] in (
				"--message", "--file", "--template",
				"--reuse-message", "--reedit-message", "--no-edit",
			):
				return True
		elif t.startswith("-") and _COMMIT_MSG_RE.match(t):
			return True
	return False


def _has_flag(toks: list[str], *flags: str) -> bool:
	return any(t.startswith(flags) for t in toks[1:])


def _git_editor_block(cmd: str) -> str | None:
	for seg in _segments(cmd):
		toks = seg.split()
		if not toks or toks[0].lower() != "git":
			continue
		sub = _git_subcommand(seg)
		if sub == "commit":
			if _has_commit_style_msg(toks) or _has_flag(toks, "-C"):
				continue
			return "git commit without -m/-F opens an editor and will hang; add -m <msg>"
		if sub == "merge":
			if _has_commit_style_msg(toks) or _has_flag(
				toks, "--ff-only", "--abort", "--quit", "--continue"
			):
				continue
			return "git merge may open an editor; add --no-edit (or -m <msg>)"
		if sub == "tag":
			if not _has_flag(toks, "-a", "--annotate", "-s", "--sign"):
				continue  # 轻量 tag 不开编辑器
			if _has_commit_style_msg(toks):
				continue
			return "annotated git tag without -m opens an editor; add -m <msg>"
		if sub == "rebase" and _has_flag(toks, "-i", "--interactive"):
			return "git rebase -i is interactive; use a non-interactive rebase"
	return None


def precheck_command(command: str) -> tuple[bool, str | None]:
	"""预检：返回 (can_execute, 拦截原因)。只拦 TTY 挂起形态，宁漏勿误伤。"""
	cmd = (command or "").strip()
	if not cmd:
		return True, None
	for check in (_fullscreen_block, _tty_flag_block, _git_editor_block):
		reason = check(cmd)
		if reason:
			return False, reason
	return True, None
