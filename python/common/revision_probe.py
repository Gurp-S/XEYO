"""从源码所在目录查询 Git 修订；不依赖固定的仓库嵌套层级。"""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_revision(source_dir: Path) -> str:
	"""返回源码所属仓库的短修订号；无 Git、无仓库或超时均返回空串。"""
	try:
		process = subprocess.run(
			["git", "-C", str(source_dir), "rev-parse", "--short", "HEAD"],
			capture_output=True,
			text=True,
			encoding="ascii",
			errors="replace",
			timeout=5,
		)
	except (OSError, subprocess.SubprocessError):
		return ""
	return process.stdout.strip() if process.returncode == 0 else ""
