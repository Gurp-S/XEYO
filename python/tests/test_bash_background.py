"""Bash 后台任务：abort / cancel 绑定。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from tools.bash_tool.background import cancel_background, start_background


def test_background_respects_parent_abort(tmp_path: Path) -> None:
	abort = AbortController()
	# 长睡眠命令；立刻 abort 应标记 interrupted
	h = start_background(
		"python -c \"import time; time.sleep(30)\"",
		cwd=str(tmp_path),
		timeout_ms=60_000,
		abort=abort,
	)
	time.sleep(0.15)
	abort.abort()
	deadline = time.time() + 5
	log = Path(h.log_path)
	while time.time() < deadline:
		if log.is_file():
			text = log.read_text(encoding="utf-8", errors="replace")
			if "interrupted" in text or "completed" in text or "timed_out" in text:
				assert "interrupted" in text
				return
		time.sleep(0.05)
	raise AssertionError(f"background task did not finish: {log.read_text(encoding='utf-8', errors='replace') if log.is_file() else 'missing'}")


def test_cancel_background_by_task_id(tmp_path: Path) -> None:
	h = start_background(
		"python -c \"import time; time.sleep(30)\"",
		cwd=str(tmp_path),
		timeout_ms=60_000,
		abort=None,
	)
	time.sleep(0.15)
	assert cancel_background(h.task_id) is True
	deadline = time.time() + 5
	log = Path(h.log_path)
	while time.time() < deadline:
		text = log.read_text(encoding="utf-8", errors="replace")
		if "interrupted" in text:
			return
		time.sleep(0.05)
	raise AssertionError("cancel_background did not interrupt task")
