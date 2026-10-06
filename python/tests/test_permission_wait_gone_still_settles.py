"""权限等待的**两条**收尾路径都必须复位状态、留下审计、发出事件。

`PermissionCoordinator.request()` 把会话状态置为
``waiting_permission`` + ``interruptible=False``。`wait()` 有两种"没人答"的形状：

1. store 返回**未决项**（正常到期）⇒ 原实现会补 resolved 审计、复位 running、发事件；
2. store 返回 **None**（项已被 `_prune()` 摘掉：过期剪枝 / 会话清理；
   GUI 轮询 pending 也算触发点）⇒ 原实现**直接 return**，于是
   会话永远停在 ``waiting_permission`` 且 ``interruptible=False``
   （授权卡不消失、中断被判定不可打断），并且这一枪的审批终态一条 resolved 都没有。

10-04 实测：走 (2) 时 `task_state.status` 仍是 `waiting_permission`、审计 0 行、事件 0 条。
修法只补齐"状态与留痕"，**判定不变**（两条路径都返回 ``timeout`` = 按拒绝处理）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.permission_coordinator as pc  # noqa: E402
from engine.permission_coordinator import PermissionCoordinator  # noqa: E402
from engine.task_state import SessionTaskState  # noqa: E402
from permissions.store import PendingPermissionStore  # noqa: E402


class _AuditRecorder:
	def __init__(self) -> None:
		self.rows: list[tuple[str, dict[str, Any]]] = []

	def record(self, kind: str, **fields: Any) -> None:
		self.rows.append((kind, fields))


@pytest.fixture()
def recorder(monkeypatch) -> _AuditRecorder:
	rec = _AuditRecorder()
	# 不碰用户真实账本（今天的另一条教训：进程内跑测也要隔离落盘根）
	monkeypatch.setattr(pc, "default_audit_log", lambda: rec)
	return rec


def _mk(store: PendingPermissionStore, recorder: _AuditRecorder):
	state = SessionTaskState(session_id="s-1")
	emitted: list[Any] = []
	coord = PermissionCoordinator(
		store=store,
		task_state=state,
		session_id="s-1",
		turn_id="t-1",
		on_event=emitted.append,
	)
	return coord, state, emitted


def _create(store: PendingPermissionStore, rid: str) -> Any:
	return store.create(
		session_id="s-1",
		turn_id="t-1",
		tool_name="Bash",
		tool_input={"command": "rm -rf build"},
		reason="needs_confirmation",
		prompt="允许执行？",
		request_id=rid,
	)


@pytest.mark.asyncio
async def test_control_unresolved_timeout_already_settles(recorder) -> None:
	"""对照：正常到期这条今天就该收尾齐全——修法不许把它改坏。"""
	store = PendingPermissionStore(ttl_seconds=0.02)
	coord, state, emitted = _mk(store, recorder)
	_create(store, "r-ctrl")
	assert (await coord.wait("r-ctrl", timeout=0.05)) == "timeout"
	assert state.status == "running", state
	assert state.interruptible is True, state
	assert [type(e).__name__ for e in emitted][-1] == "PermissionResolvedEvent", emitted
	assert [k for k, _ in recorder.rows if k == "permission.resolved"], recorder.rows


@pytest.mark.asyncio
async def test_vanished_item_still_settles_state_and_ledger(recorder) -> None:
	"""项被剪掉之后（真实竞态：另一枪 create 触发 `_prune()`），收尾也必须齐全。"""
	store = PendingPermissionStore(ttl_seconds=0.01)
	coord, state, emitted = _mk(store, recorder)
	_create(store, "r-gone")
	coord.request(
		tool_name="Write",
		tool_input={"file_path": "a.txt"},
		reason="needs_confirmation",
		prompt="允许写？",
	)
	assert state.status == "waiting_permission", state  # 前置：request 确实置了挂起态
	time.sleep(0.05)
	_create(store, "r-prune-trigger")  # create() 内部 _prune() 把已过期的 r-gone 摘掉
	assert store.get("r-gone") is None, "夹具没让项真的消失，本断言会空转"

	before_rows = len([k for k, _ in recorder.rows if k == "permission.resolved"])
	assert (await coord.wait("r-gone", timeout=0.05)) == "timeout"

	assert state.status == "running", f"会话被留在 {state.status}"
	assert state.interruptible is True, state
	resolved = [e for e in emitted if type(e).__name__ == "PermissionResolvedEvent"]
	assert resolved, emitted
	assert resolved[-1].approved is False, resolved[-1]
	assert len([k for k, _ in recorder.rows if k == "permission.resolved"]) == before_rows + 1, (
		recorder.rows
	)


@pytest.mark.asyncio
async def test_unknown_request_id_is_not_silent(recorder) -> None:
	"""同一条分支的另一入口：id 从来不存在（会话清理后直调）。"""
	store = PendingPermissionStore(ttl_seconds=60)
	coord, state, emitted = _mk(store, recorder)
	coord.request(
		tool_name="Bash",
		tool_input={"command": "make"},
		reason="needs_confirmation",
		prompt="允许执行？",
	)
	assert state.status == "waiting_permission"
	assert (await coord.wait("no-such-id", timeout=0.01)) == "timeout"
	assert state.status == "running", state
	assert state.interruptible is True, state
	assert [e for e in emitted if type(e).__name__ == "PermissionResolvedEvent"], emitted
