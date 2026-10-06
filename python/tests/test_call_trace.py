"""执行起点台账 + hydrate 正向证据测试（问题⑤的结构解：call 级归因）。

守三条：
- **只报正向证据**：有开始记录才说"已进入执行"；无记录/开关关/会话未知 ⇒ 缺席；
- **fail-open**：落盘根不可用、台账读炸 ⇒ 既不抛异常也不写假事实；
- **有界**：台账不会无限增长，裁剪只让结论回落到"无证据"，不伪造证据。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from msgtypes.message import Message  # noqa: E402
from session import call_trace  # noqa: E402
from session.hydrate import _repair_unclosed_tool_uses  # noqa: E402

_UID = "call_abc"
_WRITE_TOOL = "Bash"


def _fresh(monkeypatch, tmp_path) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	monkeypatch.delenv("XEYO_CALL_TRACE", raising=False)


def _unclosed(name: str = _WRITE_TOOL, uid: str = _UID) -> list[Message]:
	"""> 一条 assistant tool_use + 没有配对 result（上一进程中断的形态）。"""
	return [
		Message(role="assistant", content=[{"type": "tool_use", "id": uid, "name": name}])
	]


def _synth_text(monkeypatch, tmp_path, *, session: str | None = "sessA") -> str:
	if session is not None:
		monkeypatch.setattr("engine.t_now_notes.current_session_id", lambda: session)
	out = _repair_unclosed_tool_uses(_unclosed())
	return str(out[-1].content)


# --- 台账本体 ---------------------------------------------------------------


def test_roundtrip_reports_record(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	assert call_trace.record_start("sessA", _UID, _WRITE_TOOL) is True
	row = call_trace.started("sessA", _UID)
	assert row and row["uid"] == _UID and row["name"] == _WRITE_TOOL


def test_disabled_writes_nothing(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	monkeypatch.setenv("XEYO_CALL_TRACE", "0")
	assert call_trace.record_start("sessA", _UID, _WRITE_TOOL) is False
	assert call_trace.started("sessA", _UID) is None
	path = call_trace.trace_path("sessA")
	assert path is not None and not path.exists()


def test_absent_record_is_no_evidence(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	assert call_trace.record_start("sessA", _UID, _WRITE_TOOL) is True
	assert call_trace.started("sessA", "other_call") is None
	assert call_trace.started("other_session", _UID) is None


def test_unwritable_root_is_fail_open(monkeypatch, tmp_path):
	blocked = tmp_path / "not_a_dir"
	blocked.write_text("x", encoding="utf-8")
	monkeypatch.setenv("XEYO_USAGE_DIR", str(blocked))
	monkeypatch.delenv("XEYO_CALL_TRACE", raising=False)
	assert call_trace.record_start("sessA", _UID, _WRITE_TOOL) is False  # 不抛
	assert call_trace.started("sessA", _UID) is None


def test_trim_keeps_tail_and_drops_oldest(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	monkeypatch.setattr(call_trace, "_MAX_BYTES", 0)
	monkeypatch.setattr(call_trace, "_MAX_LINES", 20)
	monkeypatch.setattr(call_trace, "_KEEP_LINES", 8)
	for i in range(30):
		call_trace.record_start("sessA", f"u{i}", _WRITE_TOOL)
	path = call_trace.trace_path("sessA")
	assert path is not None
	lines = path.read_text(encoding="utf-8").splitlines()
	assert len(lines) <= 20
	assert call_trace.started("sessA", "u29") is not None  # 最新仍在
	assert call_trace.started("sessA", "u0") is None  # 旧的被裁 ⇒ 回落为"无证据"


# --- hydrate 侧：只取正向证据 ------------------------------------------------


def test_call_start_fact_reports_confirmed_start(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	call_trace.record_start("sessA", _UID, _WRITE_TOOL)
	text = _synth_text(monkeypatch, tmp_path)
	assert "TOOL_OUTCOME_UNKNOWN" in text
	assert "已进入执行" in text


def test_call_start_fact_absent_without_record(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	text = _synth_text(monkeypatch, tmp_path)
	assert "TOOL_OUTCOME_UNKNOWN" in text
	assert "已进入执行" not in text  # 无记录 ≠ 未开始 ⇒ 什么都不说


def test_call_start_fact_absent_when_trace_disabled(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	call_trace.record_start("sessA", _UID, _WRITE_TOOL)
	monkeypatch.setenv("XEYO_CALL_TRACE", "0")
	text = _synth_text(monkeypatch, tmp_path)
	assert "已进入执行" not in text


def test_call_start_fact_absent_without_session(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	call_trace.record_start("sessA", _UID, _WRITE_TOOL)
	text = _synth_text(monkeypatch, tmp_path, session=None)
	assert "已进入执行" not in text  # 拿不到会话 ⇒ 无证据


def test_readonly_tool_keeps_not_started(monkeypatch, tmp_path):
	_fresh(monkeypatch, tmp_path)
	from tools.meta import READONLY_ALLOW

	call_trace.record_start("sessA", _UID, _WRITE_TOOL)
	name = sorted(READONLY_ALLOW)[0]
	out = _repair_unclosed_tool_uses(_unclosed(name))
	text = str(out[-1].content)
	assert "TOOL_NOT_STARTED" in text
	assert "已进入执行" not in text


# --- 端到端：真实 ToolRegistry.run 是唯一执行起点 ----------------------------


class _Probe:
	"""最小工具替身（与 test_agent_mechanism_boundaries 的 ReadProbe 同形）。"""

	name = "CtProbe"
	is_read_only = staticmethod(lambda: True)
	is_concurrency_safe = staticmethod(lambda: True)

	def schema(self):
		return {
			"name": self.name,
			"description": "probe",
			"parameters": {"type": "object", "properties": {}},
		}

	async def execute(self, input, abort):
		from tools.base_tool import ToolResult

		return ToolResult("ok")


def _registry(tmp_path, session_id: str):
	from engine.permission_coordinator import PermissionCoordinator
	from engine.task_state import SessionTaskState
	from permissions.store import PendingPermissionStore
	from tools.tool_registry import ToolRegistry

	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(_Probe())
	coord = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=SessionTaskState(session_id=session_id),
		session_id=session_id,
		turn_id="t1",
	)
	return reg, coord


def test_registry_run_writes_call_start(monkeypatch, tmp_path):
	"""执行起点落盘：真实 reg.run 路径（带 coordinator.session_id）必须留下开始记录。"""
	import asyncio

	from engine.abort import AbortController
	from msgtypes.message import ToolUse

	_fresh(monkeypatch, tmp_path)
	reg, coord = _registry(tmp_path, "sessZ")
	res = asyncio.run(
		reg.run(
			ToolUse(id="call_e2e", name=_Probe.name, input={}),
			AbortController(),
			coordinator=coord,
			skip_ask=True,
		)
	)
	assert not res.is_error
	row = call_trace.started("sessZ", "call_e2e")
	assert row is not None and row["name"] == _Probe.name


def test_rejected_call_writes_no_record(monkeypatch, tmp_path):
	"""没进入执行的调用不留开始记录（记录只出现在执行起点，否则"已进入执行"就是假证据）。"""
	import asyncio

	from engine.abort import AbortController
	from msgtypes.message import ToolUse

	_fresh(monkeypatch, tmp_path)
	reg, coord = _registry(tmp_path, "sessZ")
	res = asyncio.run(
		reg.run(
			ToolUse(id="call_nope", name="no_such_tool", input={}),
			AbortController(),
			coordinator=coord,
			skip_ask=True,
		)
	)
	assert res.is_error
	assert call_trace.started("sessZ", "call_nope") is None
