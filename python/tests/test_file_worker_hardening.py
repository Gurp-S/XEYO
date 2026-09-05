"""文件工人稳固：空 scope 零写面、scope 规范化、WriteStore 拒旁路、工人无 ASK。"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.scheduler import Task, batch_tool_whitelist, build_tool_whitelist
from engine.subagent_runner import subagent_budgets_for_scope
from permissions.policy import evaluate_policy
from permissions.write_scope import normalize_worker_scope, write_scope
from tools.meta import WRITE_PATH_TOOLS


def test_empty_scope_whitelist_strips_all_write_path_tools():
	wl = build_tool_whitelist(Task(id="t1", desc="ro", scope=[]))
	assert "Write" not in wl
	assert "Edit" not in wl
	assert "NotebookEdit" not in wl
	assert WRITE_PATH_TOOLS.isdisjoint(wl)
	assert "Read" in wl
	assert "Grep" in wl
	assert "Bash" in wl  # Phase 2 基线；策略沙箱另限命令
	assert "Git" in wl


def test_scoped_whitelist_keeps_write_edit():
	wl = build_tool_whitelist(Task(id="t1", desc="rw", scope=["src/"]))
	assert "Write" in wl
	assert "Edit" in wl
	assert "Bash" in wl
	assert "Git" in wl


def test_batch_whitelist_intersection_keeps_ro_safe():
	tasks = [
		Task(id="a", desc="ro", scope=[]),
		Task(id="b", desc="rw", scope=["src/"]),
	]
	shared = batch_tool_whitelist(tasks)
	assert WRITE_PATH_TOOLS.isdisjoint(shared)
	# 调度仍按任务裁剪
	assert "Write" in build_tool_whitelist(tasks[1])
	assert "Write" not in build_tool_whitelist(tasks[0])


def test_normalize_worker_scope_broad_dot(tmp_path: Path):
	paths, ro, reason = normalize_worker_scope(["."], cwd=str(tmp_path))
	assert paths == []
	assert ro is True
	assert reason == "scope_too_broad"


def test_normalize_worker_scope_relpath(tmp_path: Path):
	(tmp_path / "src").mkdir()
	paths, ro, reason = normalize_worker_scope(["src"], cwd=str(tmp_path))
	assert paths == ["src"]
	assert ro is False
	assert reason == ""


def test_write_store_required_under_write_scope(tmp_path: Path):
	from tools.file_write_tool.file_write_tool import FileWriteTool
	from tools.fileio.read_state import ReadFileState

	tool = FileWriteTool(cwd=str(tmp_path), read_state=ReadFileState())
	target = str(tmp_path / "a.txt")
	with write_scope(["."]):
		with pytest.raises(RuntimeError, match="write_store required"):
			tool._persist(target, "hi", encoding="utf-8", line_endings="LF")


def test_worker_write_policy_no_ask(tmp_path: Path):
	from permissions.policy import PermissionDecision

	f = tmp_path / "src" / "a.py"
	f.parent.mkdir(parents=True)
	f.write_text("x=1\n", encoding="utf-8")
	with write_scope(["src"]):
		dec = evaluate_policy(
			"Write",
			{"file_path": str(f), "content": "x=2\n"},
			cwd=str(tmp_path),
		)
	assert dec.decision == PermissionDecision.ALLOW
	assert dec.matched_rule == "worker_no_ask"


def test_worker_empty_scope_write_denied(tmp_path: Path):
	from permissions.policy import PermissionDecision

	f = tmp_path / "a.py"
	f.write_text("x=1\n", encoding="utf-8")
	with write_scope([]):
		dec = evaluate_policy(
			"Write",
			{"file_path": str(f), "content": "x=2\n"},
			cwd=str(tmp_path),
		)
	assert dec.decision == PermissionDecision.DENY
	assert "write_scope" in (dec.matched_rule or "")


def test_ro_budgets_lower_than_rw():
	ro_t, ro_c = subagent_budgets_for_scope([])
	rw_t, rw_c = subagent_budgets_for_scope(["src/"])
	# 只读工人轮次上限必须低于可写工人（省钱）；两者都已被整体上调。
	assert ro_t < rw_t
	assert ro_c < rw_c
	assert rw_t >= ro_t
	assert rw_c >= ro_c


def test_detect_write_conflict_message():
	from engine.subagent_runner import _detect_write_stale
	from types import SimpleNamespace

	msgs = [
		SimpleNamespace(
			role="tool",
			content="write conflict (stale): File has been unexpectedly modified",
		)
	]
	assert _detect_write_stale(msgs) is True


def test_worker_bash_readonly_allow_else_deny(tmp_path: Path):
	from permissions.policy import PermissionDecision

	with write_scope(["src"]):
		ok = evaluate_policy(
			"Bash", {"command": "echo hi"}, cwd=str(tmp_path)
		)
		askish = evaluate_policy(
			"Bash", {"command": "python app.py"}, cwd=str(tmp_path)
		)
		git_ro = evaluate_policy(
			"Bash", {"command": "git status"}, cwd=str(tmp_path)
		)
	assert ok.decision == PermissionDecision.ALLOW
	assert ok.matched_rule == "worker_bash_readonly"
	assert askish.decision == PermissionDecision.DENY
	assert askish.matched_rule == "worker_bash_deny"
	assert git_ro.decision == PermissionDecision.ALLOW
	assert git_ro.matched_rule == "worker_bash_readonly"


def test_main_bash_still_asks_without_write_scope(tmp_path: Path):
	from permissions.policy import PermissionDecision

	# 主会话（无 write_scope）：非只读仍 ASK，不被工人沙箱误伤
	r = evaluate_policy(
		"Bash", {"command": "python app.py"}, cwd=str(tmp_path)
	)
	assert r.decision == PermissionDecision.ASK
	# 出厂缺省 bash=default：非只读（python app.py）走 default-ask，
	# matched_rule=bash_default_ask（与 T26 只读白名单仅 default 生效一致）。
	assert r.matched_rule == "bash_default_ask"


def test_worker_bash_timeout_clamped():
	from tools.bash_tool.bash_tool import (
		WORKER_BASH_DEFAULT_TIMEOUT_MS,
		WORKER_BASH_MAX_TIMEOUT_MS,
		clamp_timeout_ms,
	)

	assert clamp_timeout_ms(None) == 120_000  # 主会话默认
	with write_scope(["src"]):
		assert clamp_timeout_ms(None) == WORKER_BASH_DEFAULT_TIMEOUT_MS
		assert clamp_timeout_ms(999_999) == WORKER_BASH_MAX_TIMEOUT_MS
		assert clamp_timeout_ms(5_000) == 5_000
