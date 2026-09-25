"""生产者→采集→规则的最小闭环：审计行由**真实写入者**产生，不由测试手写。

本会话在同一族上连抓四条"规则读的字段没人写"：``notice.channel`` 上凭空被读的
``kind_detail``、``llm.failure`` 的 ``code`` 与采集读的 ``error_code``、
``tool_failure`` 证据 detail 里缺失的 ``error_kind``、``permission.*`` 行缺的
``tool_use_id``。的共同点是：诊断层的单测自己捏审计行，所以生产者改名字、漏字段、
或不写时**没有任何东西会变红**，规则只是在生产里悄悄变成恒不命中的死码。

这里反过来：调用真实的写入者（ToolRegistry / PermissionCoordinator / TurnRunner）
落到同一个 tmp 审计文件，再让采集器与规则集去读。断言的是"这条规则在这条链路上
真的能命中"，不是"规则读到测试给的字段时会命中"。
"""

from __future__ import annotations

import json

import pytest

import audit.log as audit_mod
from audit.log import AuditLog, reset_default_audit_log
from diagnostics.collect import collect_run
from diagnostics.fault_split import ENVIRONMENT, attribute_fault
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, UNKNOWN
from diagnostics.rules import evaluate_run
from engine.abort import AbortController
from engine.execution_context import ExecutionContext
from engine.permission_coordinator import PermissionCoordinator
from engine.task_state import SessionTaskState
from engine.turn_runner import TurnRunner
from msgtypes.message import ToolUse
from permissions.policy import set_agent_mode
from permissions.store import PendingPermissionStore, USER_CHOICE_ALLOW
from tools.base_tool import Tool, ToolResult
from tools.tool_registry import ToolRegistry

_SESSION = "s-roundtrip"
_TURN = "t-roundtrip"


@pytest.fixture()
def audit_log(tmp_path):
	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	audit_mod._default = log
	yield log
	reset_default_audit_log()


@pytest.fixture()
def execution_context():
	from engine.workspace_context import bind_workspace_context

	ctx = ExecutionContext(session_id=_SESSION, cwd=".", trace_id=_TURN)
	with bind_workspace_context(ctx):
		yield ctx


class _FailingTool(Tool):
	@property
	def name(self) -> str:  # type: ignore[override]
		return "roundtrip_fail"

	def schema(self) -> dict:
		return {"name": self.name}

	async def execute(self, inp, abort) -> ToolResult:
		# 显式带 error_kind：真实的工具会给出分类，规则与归属都得读得到它。
		return ToolResult(content="no such file", is_error=True, error_kind="NOT_FOUND")


@pytest.mark.asyncio
async def test_real_tool_failure_reaches_the_rule_and_the_attribution(audit_log, execution_context) -> None:
	"""真实 tool.finished 行 → tool_failure 已确认 → 归属落到外部世界。

	这一条同时钉住三处：生产者写的 error_kind 要能被采集读出（96df1ec 之前 detail
	里没有它，归属表在生产里覆盖率 0）；规则要按轮次取到自己的调用；
	_ENVIRONMENT_KINDS 那张表要真的参与定责。
	"""
	set_agent_mode(None)
	reg = ToolRegistry(cwd=".")
	reg.register(_FailingTool())
	for i in range(3):
		# skip_ask：用户在审批面板点"允许"之后，引擎就是带 skip_ask 重跑同一次调用
		# （query_loop 的既有路径）。不带它的话未注册策略的工具名会停在 ASK，
		# 一行 tool.* 都不会产生 —— 那是另一条链路（下面 permission 用例钉它）。
		res = await reg.run(
			ToolUse(id=f"u{i}", name="roundtrip_fail", input={}),
			AbortController(),
			skip_ask=True,
		)
		assert res.is_error is True and res.error_kind == "NOT_FOUND"

	rows = [r for r in audit_log.read_all() if str(r.get("kind")) == "tool.finished"]
	assert len(rows) == 3, "生产者没落够行，后面的断言就都是空的"
	assert {str(r.get("session_id")) for r in rows} == {_SESSION}
	assert {str(r.get("turn_id")) for r in rows} == {_TURN}

	run = collect_run(_SESSION, _TURN, audit_path=str(audit_log.path))
	findings = evaluate_run(run)
	failures = [f for f in findings if f.rule_id == "tool_failure"]
	assert failures, "真实审计行没能命中 tool_failure：规则在链路上是死的"
	assert failures[0].status == CONFIRMED_FAULT
	assert "error_kind=NOT_FOUND" in failures[0].evidence[0].detail
	assert attribute_fault(run, findings)["responsibility"] == ENVIRONMENT
	# 同一批真实行还须喂到重复失败规则：三次同签名 ⇒ 只算可疑信号，不宣称死循环。
	repeats = [f for f in findings if f.rule_id == "repeated_failure"]
	assert repeats and repeats[0].status == SUSPECTED_CAUSE


@pytest.mark.asyncio
async def test_real_wire_drop_ledger_row_reaches_the_gap_rule(audit_log, execution_context) -> None:
	"""出口护栏丢的行由 ``usage.ledger.record_wire_drop`` 落账 → wire_gap 必须读得到。

	钉的是 join 键：账本行不带 session_id，采集只能拿 ``ids`` 与本运行的 tool_use id
	求交（collect._collect_wire_drops）。生产者改字段名、或采集读错键，这条就断 ——
	而本机平时连 wire_drops.jsonl 都没有，规则看起来"正常地不命中"。
	"""
	from usage.ledger import record_wire_drop, wire_drops_path

	set_agent_mode(None)
	reg = ToolRegistry(cwd=".")
	reg.register(_FailingTool())
	await reg.run(
		ToolUse(id="u-drop", name="roundtrip_fail", input={}),
		AbortController(),
		skip_ask=True,
	)
	record_wire_drop(dropped_ids=["u-drop"], target="wire")
	assert wire_drops_path().is_file()

	run = collect_run(_SESSION, _TURN, audit_path=str(audit_log.path))
	gaps = [f for f in evaluate_run(run) if f.rule_id == "wire_gap" and f.boundary == "adapter"]
	assert gaps, "真实丢行账本没能命中 wire_gap：最后一公里仍是盲区"
	assert gaps[0].status == CONFIRMED_FAULT
	assert "u-drop" in gaps[0].evidence[0].detail


@pytest.mark.asyncio
async def test_real_permission_timeout_is_not_blamed(audit_log, execution_context) -> None:
	"""真实的超时分支（coordinator.wait）落的行为未定，而不是"已确认"。

	顺带钉住关联身份：超时行必须带 tool_use_id（88ce099 只钉了 request/resolve
	两个写入点，超时分支是第三个写入点）。
	"""
	set_agent_mode(None)
	store = PendingPermissionStore(ttl_seconds=0)
	coord = PermissionCoordinator(
		store=store,
		task_state=SessionTaskState(session_id=_SESSION),
		session_id=_SESSION,
		turn_id=_TURN,
	)
	rid = coord.request(
		tool_name="roundtrip_fail",
		tool_input={},
		reason="needs_confirmation",
		prompt="Allow?",
		tool_use_id="u-ask",
	)
	assert await coord.wait(rid, timeout=0.05) == "timeout"

	rows = [r for r in audit_log.read_all() if str(r.get("kind")) == "permission.resolved"]
	assert rows and rows[0].get("outcome") == "timeout"
	assert rows[0].get("tool_use_id") == "u-ask", "超时分支丢了关联身份：审批与调用断开"

	run = collect_run(_SESSION, _TURN, audit_path=str(audit_log.path))
	perm = [f for f in evaluate_run(run) if f.rule_id == "permission_block"]
	assert perm, "真实权限行没能命中 permission_block：规则在链路上是死的"
	assert all(f.status == UNKNOWN for f in perm), "超时不能被判成已确认故障"


@pytest.mark.asyncio
async def test_real_stream_gap_frame_leaves_a_readable_audit_row(audit_log) -> None:
	"""环形缓冲挤掉旧帧的那次连接，必须在审计里留下可读的缺口（21674f0）。"""

	class _FakePool:
		def end(self, session_id: str, lease_id: int | None = None) -> None:
			_ = (session_id, lease_id)

	from engine import turn_runner as tr

	_saved = tr._MAX_BUFFERED_FRAMES
	tr._MAX_BUFFERED_FRAMES = 1
	try:
		runner = TurnRunner(_FakePool())

		async def producer():
			for n in range(1, 4):
				yield (n, f'data: {{"n":{n}}}\n\n'.encode(), "delta")
			yield (4, b"data: [DONE]\n\n", "done")

		await runner.start(
			session_id=_SESSION,
			lease_id=1,
			model="m",
			goal_text="g",
			user_message_id="u1",
			producer=producer,
			turn_id=_TURN,
		)
		await runner.wait_done(_SESSION, timeout=2.0)
		frames = [f async for f in runner.subscribe(_SESSION, cursor=0)]
	finally:
		tr._MAX_BUFFERED_FRAMES = _saved

	assert any(b"stream_gap" in f for f in frames), json.dumps([f[:40] for f in frames])

	run = collect_run(_SESSION, _TURN, audit_path=str(audit_log.path))
	gaps = [f for f in evaluate_run(run) if f.rule_id == "wire_gap"]
	assert gaps, "发过缺口帧却没有可读的缺口证据：sse_gui 边界仍是盲区"
	assert gaps[0].status == SUSPECTED_CAUSE
	assert gaps[0].boundary == "sse_gui"
