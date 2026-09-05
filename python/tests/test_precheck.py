"""预检（快速失败）行为锁定：宁漏勿误伤。

第一版预检曾把 python/npm install/pip install 整体拉黑（误杀），
本文件是对"不许再误杀"的回归锁。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bash_tool.precheck import precheck_command


def _blocked(cmd: str) -> None:
	ok, reason = precheck_command(cmd)
	assert not ok, f"expected block: {cmd!r}"
	assert reason, f"block without reason: {cmd!r}"


def _allowed(cmd: str) -> None:
	ok, reason = precheck_command(cmd)
	assert ok, f"expected allow, got {reason!r}: {cmd!r}"


# ---- 高危误伤回归：这些必须放行（第一版曾全部误杀）----

def test_allow_common_noninteractive() -> None:
	_allowed("python -m pytest tests/ -q")
	_allowed("py -3.11 -m pytest")
	_allowed("python tools/scripts/export_manifest.py")
	_allowed("npm install")
	_allowed("npm install left-pad")
	_allowed("pip install -r requirements.txt")
	_allowed("cargo build --release")
	_allowed("git status")
	_allowed("echo hi && python -m pytest")


def test_allow_git_with_message() -> None:
	_allowed('git commit -m "fix: x"')
	_allowed('git commit -am "fix: x"')
	_allowed("git commit --amend --no-edit")
	_allowed("git commit -C HEAD")
	_allowed("git merge main --no-edit")
	_allowed("git merge --ff-only main")
	_allowed("git tag v1.0")
	_allowed("git tag -a v1.0 -m release")
	_allowed("git rebase main")


def test_allow_container_without_tty() -> None:
	_allowed("docker exec -i c1 cat /etc/hosts")
	_allowed("docker run --rm alpine echo hi")


# ---- 必须拦截：等 TTY/编辑器的形态 ----

def test_block_fullscreen_tty() -> None:
	_blocked("vim src/a.py")
	_blocked("less big.log")
	_blocked("top")
	_blocked("git log | less")


def test_block_git_editor_paths() -> None:
	_blocked("git commit")
	_blocked("git commit --amend")
	_blocked("git tag -a v1")
	_blocked("git rebase -i HEAD~3")
	_blocked("echo hi && git commit")  # 复合段里的 git 也要拦


def test_block_container_tty() -> None:
	_blocked("docker run -it alpine sh")
	_blocked("kubectl exec -it pod -- sh")


def test_empty_command_passes() -> None:
	_allowed("")
	_allowed("   ")
