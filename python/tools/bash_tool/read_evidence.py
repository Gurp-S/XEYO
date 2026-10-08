"""Bash 侧「整文件读」证据的采集（弱基线，语义在 ``tools.fileio.read_state``）。

只认**单路径 + 整文件 + 输出未被截断**三件同时成立：

- ``cat a.py`` / ``Get-Content a.py`` / ``type a.py`` 这类整文件读；
- 带管道 / 重定向 / 命令串联（``cat a.py | head``、``rg x a.py``、``cat a.py > b``）一律不认
  ——它们只保证"看到了某一部分"；
- 工具输出出现截断标记（``[output truncated …]`` / ``[middle truncated]``）也不认。

理由：这层证据的用途是回答"模型看到的是不是当前全文"。允许"看到一半"当基线，等于给
盲改开门（Edit 仍要 ``old_string`` 命中，但那是第二道门，不是第一道）。
"""

from __future__ import annotations

import os

#: 整文件读命令（小写比较；``gc`` = PowerShell ``Get-Content`` 别名）。
_READ_COMMANDS: frozenset[str] = frozenset({"cat", "type", "get-content", "gc"})

#: 出现任一字符即不视为"简单整文件读"。
_METACHARS: tuple[str, ...] = ("|", ">", "<", ";", "&&", "&", "`", "$(")

#: 输出被截断的标记（见 tools/bash_tool/truncate.py）。
_TRUNCATION_MARKS: tuple[str, ...] = ("[output truncated", "[middle truncated]")


def whole_file_read_paths(command: str, *, cwd: str) -> list[str]:
	"""命令若是单路径整文件读 → 返回绝对路径；否则空列表。"""
	text = str(command or "").strip()
	if not text or any(mark in text for mark in _METACHARS):
		return []
	tokens = text.split()
	if not tokens or tokens[0].lower() not in _READ_COMMANDS:
		return []
	rest = [tok for tok in tokens[1:] if not tok.startswith("-")]
	if len(rest) != 1:
		return []
	target = rest[0].strip().strip('"').strip("'")
	if not target or any(ch in target for ch in "*?["):
		return []
	path = target if os.path.isabs(target) else os.path.join(cwd or ".", target)
	return [os.path.abspath(path)]


def paths_in_output(command: str, *, cwd: str, content: str) -> list[str]:
	"""整文件读命令且输出未截断时，返回应登记的路径。"""
	paths = whole_file_read_paths(command, cwd=cwd)
	if not paths:
		return []
	body = str(content or "")
	if any(mark in body for mark in _TRUNCATION_MARKS):
		return []
	return paths


def note(command: str, *, cwd: str, content: str, is_error: bool) -> list[str]:
	"""登记证据（fail-open：任何异常都吞掉，读写守卫不该被采集面拖垮）。"""
	if is_error:
		return []
	try:
		paths = paths_in_output(command, cwd=cwd, content=content)
		if not paths:
			return []
		from tools.fileio.read_state import record_bash_read

		lines = str(content or "").count("\n") + 1
		for path in paths:
			try:
				mtime_ms = int(os.stat(path).st_mtime * 1000)
			except OSError:
				continue
			record_bash_read(path, mtime_ms=mtime_ms, whole_file=True, lines=lines)
		return paths
	except Exception:  # noqa: BLE001
		return []
