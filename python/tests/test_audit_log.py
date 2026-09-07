"""审计日志（P1-1 最小集）契约测试。

覆盖：
- AuditLog JSONL 追加 / 坏行容忍 / 默认路径环境变量
- registry.run ALLOW → tool.started + tool.finished
- registry.run DENY → permission.denied
- coordinator request/resolve/timeout → permission.pending / permission.resolved
"""

from __future__ import annotations


import pytest

from audit.log import AuditLog, default_audit_log, reset_default_audit_log
from engine.abort import AbortController
from engine.permission_coordinator import PermissionCoordinator
from engine.task_state import SessionTaskState
from msgtypes.message import ToolUse
from permissions.policy import set_agent_mode
from permissions.store import PendingPermissionStore
from tools.base_tool import Tool, ToolResult
from tools.tool_registry import ToolRegistry


class _EchoTool(Tool):
	@property
	def name(self) -> str:  # type: ignore[override]
		return "echo"

	def schema(self) -> dict:
		return {"name": self.name}

	async def execute(self, inp, abort) -> ToolResult:
		return ToolResult(content="ok", is_error=False)


class _DenyTool(Tool):
	@property
	def name(self) -> str:  # type: ignore[override]
		return "Bash"

	def schema(self) -> dict:
		return {"name": self.name}

	async def execute(self, inp, abort) -> ToolResult:
		return ToolResult(content="", is_error=False)


@pytest.fixture()
def audit_log(tmp_path):
	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	import audit.log as mod

	mod._default = log  # 直接注入默认实例
	yield log
	reset_default_audit_log()


def _registry() -> ToolRegistry:
	reg = ToolRegistry(cwd=".")
	reg.register(_EchoTool())
	reg.register(_DenyTool())
	return reg


def test_audit_log_appends_jsonl_and_tolerates_bad_lines(tmp_path):
	path = tmp_path / "sub" / "audit.jsonl"
	log = AuditLog(path)
	log.record("tool.started", session_id="s1", tool_name="Echo")
	log.record("tool.finished", session_id="s1", duration_ms=3)
	path.open("a", encoding="utf-8").write("not-json\n")
	rows = log.read_all()
	assert [r["kind"] for r in rows] == ["tool.started", "tool.finished"]
	assert rows[0]["session_id"] == "s1"


def test_default_audit_log_env_path(tmp_path, monkeypatch):
	reset_default_audit_log()
	monkeypatch.setenv("XEYO_AUDIT_LOG", str(tmp_path / "env.jsonl"))
	assert default_audit_log().path == tmp_path / "env.jsonl"


def test_audit_log_query_newest_first_and_filters(tmp_path):
	path = tmp_path / "q.jsonl"
	log = AuditLog(path)
	path.write_text(
		'{"ts":1.0,"kind":"tool.started","session_id":"a"}\n'
		'{"ts":2.0,"kind":"tool.finished","session_id":"a"}\n'
		'{"ts":3.0,"kind":"tool.started","session_id":"b"}\n',
		encoding="utf-8",
	)
	rows = log.query(session_id="a", kind="tool.", limit=10)
	assert [r["kind"] for r in rows] == ["tool.finished", "tool.started"]
	assert log.query(since_ts=2.5)[0]["session_id"] == "b"
	assert log.query(limit=1, offset=1)[0]["kind"] == "tool.finished"


@pytest.mark.asyncio
async def test_allow_records_tool_started_finished(audit_log):
	set_agent_mode(None)
	reg = _registry()
	result = await reg.run(
		ToolUse(id="u1", name="echo", input={}), AbortController()
	)
	assert result.is_error is False
	kinds = [r["kind"] for r in audit_log.read_all()]
	assert kinds == ["tool.started", "tool.finished"]


@pytest.mark.asyncio
async def test_deny_records_permission_denied(audit_log):
	set_agent_mode(None)
	reg = _registry()
	result = await reg.run(
		ToolUse(id="u2", name="Bash", input={"command": "shutdown /s"}),
		AbortController(),
	)
	assert result.is_error is True
	rows = audit_log.read_all()
	assert len(rows) == 1
	row = rows[0]
	assert row["kind"] == "permission.denied"
	assert row["tool_name"] == "Bash"
	assert row["reason"] == "system_power"


@pytest.mark.asyncio
async def test_coordinator_records_pending_and_resolved(audit_log):
	st = SessionTaskState(session_id="s")
	coord = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=st,
		session_id="s",
		turn_id="t1",
	)
	rid = coord.request(
		tool_name="Bash",
		tool_input={"command": "echo hi"},
		reason="needs_confirmation",
		prompt="Run echo hi?",
		matched_rule="bash_policy_ask",
		command_summary="echo hi",
	)
	assert coord.resolve(rid, True, actor="desktop") is True
	rows = audit_log.read_all()
	kinds = [(r["kind"], r.get("outcome")) for r in rows]
	assert kinds == [
		("permission.pending", None),
		("permission.resolved", "user_decided"),
	]
	assert rows[0]["matched_rule"] == "bash_policy_ask"
	assert rows[0]["command_summary"] == "echo hi"
	assert rows[1]["actor"] == "desktop"
	assert rows[1]["approved"] is True
	assert rows[1]["matched_rule"] == "bash_policy_ask"


def test_audit_record_redacts_command_summary(audit_log):
	audit_log.record(
		"permission.pending",
		session_id="s",
		command_summary="export TOKEN=sk-abcdefghijklmnopqrstuvwxyz012345",
	)
	row = audit_log.read_all()[0]
	assert "***" in row["command_summary"]
	assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in row["command_summary"]


@pytest.mark.asyncio
async def test_store_resolve_writes_resolved_audit(audit_log):
	"""桌面/微信直调 store.resolve 也必须落 permission.resolved。"""
	store = PendingPermissionStore()
	req = store.create(
		session_id="s",
		turn_id="t1",
		tool_name="Bash",
		tool_input={"command": "ls"},
		reason="needs_confirmation",
		prompt="?",
		matched_rule="bash_policy_ask",
		command_summary="ls",
	)
	assert store.resolve(req.request_id, True, actor="filehelper") is True
	resolved = [r for r in audit_log.read_all() if r["kind"] == "permission.resolved"]
	assert len(resolved) == 1
	assert resolved[0]["actor"] == "filehelper"
	assert resolved[0]["approved"] is True
	assert resolved[0]["matched_rule"] == "bash_policy_ask"


@pytest.mark.asyncio
async def test_timeout_records_resolved_once(audit_log):
	st = SessionTaskState(session_id="s")
	store = PendingPermissionStore(ttl_seconds=0.05)
	coord = PermissionCoordinator(
		store=store, task_state=st, session_id="s", turn_id="t1"
	)
	rid = coord.request(
		tool_name="Write",
		tool_input={"file_path": "a.txt"},
		reason="needs_confirmation",
		prompt="p",
	)
	approved = await coord.wait(rid, timeout=0.2)
	assert approved == "timeout"
	outcomes = [
		r.get("outcome")
		for r in audit_log.read_all()
		if r["kind"] == "permission.resolved"
	]
	assert outcomes == ["timeout"]
