"""权限挂起—恢复（store + coordinator）契约测试。"""

from __future__ import annotations

import asyncio

import pytest

from engine.abort import AbortController
from engine.permission_coordinator import PermissionCoordinator
from engine.task_state import SessionTaskState
from msgtypes.events import PermissionPendingEvent, PermissionResolvedEvent
from msgtypes.message import ToolUse
from permissions.store import PendingPermissionStore
from permissions.store import default_permission_store
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


def _coordinator() -> tuple[PermissionCoordinator, list[object]]:
	emitted: list[object] = []
	st = SessionTaskState(session_id="s")
	coord = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=st,
		session_id="s",
		turn_id="t1",
		on_event=emitted.append,
	)
	return coord, emitted


@pytest.mark.asyncio
async def test_request_publishes_pending_and_sets_state() -> None:
	coord, emitted = _coordinator()
	request_id = coord.request(
		tool_name="Write",
		tool_input={"file_path": "a.txt"},
		reason="needs_confirmation",
		prompt="Write to a.txt?",
	)
	assert request_id
	assert coord.task_state.status == "waiting_permission"
	assert coord.task_state.current_tool == "Write"
	assert any(isinstance(e, PermissionPendingEvent) for e in emitted)


@pytest.mark.asyncio
async def test_resolve_then_wait_returns_approved(tmp_path, monkeypatch) -> None:
	from audit.log import AuditLog, reset_default_audit_log
	import audit.log as audit_mod

	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	audit_mod._default = log
	try:
		coord, emitted = _coordinator()
		rid = coord.request(
			tool_name="Bash",
			tool_input={"command": "echo hi"},
			reason="needs_confirmation",
			prompt="Run?",
			matched_rule="bash_policy_ask",
			command_summary="echo hi",
		)
		# 先启动等待任务，再确认。
		async def _wait() -> str:
			return await coord.wait(rid, timeout=2.0)

		waiting = asyncio.create_task(_wait())
		assert coord.resolve(rid, True, actor="desktop") is True
		assert await waiting == "allow"
		assert coord.task_state.status == "running"
		assert any(isinstance(e, PermissionResolvedEvent) for e in emitted)
		kinds = [r["kind"] for r in log.read_all()]
		assert "permission.pending" in kinds
		assert kinds.count("permission.resolved") == 1
		resolved = next(r for r in log.read_all() if r["kind"] == "permission.resolved")
		assert resolved["matched_rule"] == "bash_policy_ask"
		assert resolved["command_summary"] == "echo hi"
		assert resolved["approved"] is True
	finally:
		reset_default_audit_log()


@pytest.mark.asyncio
async def test_resolve_is_idempotent() -> None:
	coord, _ = _coordinator()
	rid = coord.request(
		tool_name="Write",
		tool_input={"file_path": "a.txt"},
		reason="needs_confirmation",
		prompt="Write to a.txt?",
	)
	assert coord.resolve(rid, False) is True
	assert coord.resolve(rid, True) is False  # 已处理，第二次拒绝


@pytest.mark.asyncio
async def test_timeout_waits_then_defaults_deny() -> None:
	coord, _ = _coordinator()
	rid = coord.request(
		tool_name="Write",
		tool_input={"file_path": "a.txt"},
		reason="needs_confirmation",
		prompt="Write to a.txt?",
	)
	choice = await coord.wait(rid, timeout=0.05)
	assert choice == "timeout"  # 超时默认拒绝
	assert coord.task_state.status == "running"


class _StubTool:
	name = "MysteryTool"

	def __init__(self) -> None:
		self.calls: list[object] = []

	def schema(self) -> dict[str, object]:
		return {
			"name": self.name,
			"description": "stub",
			"input_schema": {"type": "object", "properties": {}},
		}

	async def execute(
		self, input: dict[str, object], abort: AbortController
	) -> ToolResult:
		self.calls.append(input)
		return ToolResult(content="ran", is_error=False)


@pytest.mark.asyncio
async def test_registry_ask_pending_then_skip_ask(tmp_path) -> None:
	tool = _StubTool()
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(tool)
	coord = PermissionCoordinator(
		store=default_permission_store(),
		task_state=SessionTaskState(session_id="s"),
		session_id="s",
		turn_id="t1",
	)
	abort = AbortController()
	result = await reg.run(
		ToolUse(id="1", name="MysteryTool", input={}),
		abort,
		coordinator=coord,
	)
	assert result.metadata is not None
	rid = result.metadata["permission_pending"]
	assert rid
	assert tool.calls == []  # ask 时不执行
	assert default_permission_store().resolve(str(rid), True) is True
	result2 = await reg.run(
		ToolUse(id="1", name="MysteryTool", input={}),
		abort,
		coordinator=coord,
		skip_ask=True,
	)
	assert tool.calls == [{}]
	assert result2.is_error is False


@pytest.mark.asyncio
async def test_registry_ask_without_coordinator_errors(tmp_path) -> None:
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(_StubTool())
	abort = AbortController()
	result = await reg.run(
		ToolUse(id="1", name="MysteryTool", input={}),
		abort,
	)
	assert result.is_error


@pytest.mark.asyncio
async def test_write_skip_ask_after_approve_on_dangerous_path(
	tmp_path, monkeypatch
) -> None:
	"""用户确认后 skip_ask 不得再被工具内 enforce_decision 打回 DENY。

	T12 起 .git/ 是受保护元数据（硬 DENY，不再走 ASK）；skip_ask 语义改用
	mode=always（每写必问）验证——确认后 skip_ask 应真正写入。
	"""
	from tools.file_read_tool.file_read_tool import FileReadTool
	from tools.file_write_tool.file_write_tool import FileWriteTool

	monkeypatch.setenv("XEYO_PERMISSION_MODE", "always")
	target = tmp_path / "config.txt"
	target.write_text("old", encoding="utf-8")
	reg = ToolRegistry(cwd=str(tmp_path))
	read_tool = FileReadTool(cwd=str(tmp_path))
	write_tool = FileWriteTool(cwd=str(tmp_path))
	# 共享 ReadFileState，满足 Write 的「先读后写」契约
	write_tool.set_read_file_state(read_tool._read_state)  # type: ignore[attr-defined]
	reg.register(read_tool)
	reg.register(write_tool)
	abort = AbortController()
	# 每写必问模式读：正常放行（读不受 mode=always 影响）
	read_ok = await reg.run(
		ToolUse(id="0", name="Read", input={"file_path": str(target)}),
		abort,
	)
	assert not read_ok.is_error, read_ok.content
	# 写：ASK 挂起 → skip_ask 应真正写入（而非 permission denied）
	pending = await reg.run(
		ToolUse(
			id="1",
			name="Write",
			input={"file_path": str(target), "content": "new"},
		),
		abort,
	)
	assert pending.is_error or (
		pending.metadata and pending.metadata.get("permission_pending")
	)
	result = await reg.run(
		ToolUse(
			id="1",
			name="Write",
			input={"file_path": str(target), "content": "new"},
		),
		abort,
		skip_ask=True,
	)
	assert not result.is_error, result.content
	assert "permission denied" not in result.content.lower()
	assert target.read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_cancel_pending_releases_wait_immediately() -> None:
	"""interrupt 路径：cancel 把挂起审批按取消处理，等待者即刻返回而非等 TTL。"""
	coord, _ = _coordinator()
	rid = coord.request(
		tool_name="Bash",
		tool_input={"command": "ls"},
		reason="needs_confirmation",
		prompt="Run ls?",
	)
	waiter = asyncio.create_task(coord.wait(rid))
	await asyncio.sleep(0)  # 让 waiter 挂到 Event 上
	assert coord.cancel_pending() == 1
	# wait 返回 choice 字符串（deny/timeout/...）；cancel 按拒绝处理 → deny
	assert await asyncio.wait_for(waiter, timeout=1.0) in ("deny", "timeout")
	item = coord.store.get(rid)
	assert item is not None and item.resolved and item.outcome == "aborted"
	# 幂等：再取消无未决项。
	assert coord.cancel_pending() == 0


@pytest.mark.asyncio
async def test_cancel_only_touches_same_session() -> None:
	coord_a, _ = _coordinator()
	coord_b, _ = _coordinator()
	# _coordinator 固定 session_id="s"；手工建一个不同会话。
	from engine.task_state import SessionTaskState as _Sts

	coord_other = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=_Sts(session_id="other"),
		session_id="other",
		turn_id="t",
	)
	rid_a = coord_a.request(
		tool_name="Bash", tool_input={}, reason="r", prompt="p"
	)
	rid_b = coord_other.request(
		tool_name="Bash", tool_input={}, reason="r", prompt="p"
	)
	assert coord_a.cancel_pending() == 1
	assert coord_a.store.get(rid_a).resolved is True  # type: ignore[union-attr]
	assert coord_other.store.get(rid_b).resolved is False  # type: ignore[union-attr]
