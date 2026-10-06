"""hydrate 合成结果的「事实侧」约束测试（问题⑤：把"未知"收窄为可核对事实）。

守两条：
- **不报空事实**：进程台账默认关（``XEYO_PROC_LEDGER`` 未开），关着时"无记录"是
  机制没开造成的空事实——报出去就是假信息，必须缺席；
- **fail-open**：台账读失败/探活异常 ⇒ 只是这句缺席，合成结果照旧生成（该结果的
  第一职责是"给中断的 tool_use 补一条确定性应答"，不能被附注拖垮）。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from msgtypes.message import Message
from session.hydrate import _repair_unclosed_tool_uses

_WRITE_TOOL = "Bash"


def _unclosed(name: str = _WRITE_TOOL, uid: str = "c1") -> list[Message]:
	"""> 一条 assistant tool_use + 没有配对 result（上一进程中断的形态）。"""
	return [
		Message(
			role="assistant",
			content=[{"type": "tool_use", "id": uid, "name": name}],
		)
	]


def _synth_text(name: str = _WRITE_TOOL) -> str:
	out = _repair_unclosed_tool_uses(_unclosed(name))
	return str(out[-1].content)


def test_ledger_disabled_contributes_no_fact(monkeypatch):
	"""台账关着 ⇒ 不加那半句（否则是假信息）。"""
	monkeypatch.delenv("XEYO_PROC_LEDGER", raising=False)
	text = _synth_text()
	assert "TOOL_OUTCOME_UNKNOWN" in text
	assert "进程台账" not in text


def test_ledger_enabled_reports_alive_objects(monkeypatch):
	from engine import process_ledger

	monkeypatch.setattr(process_ledger, "ledger_enabled", lambda: True)
	monkeypatch.setattr(
		process_ledger,
		"leftovers",
		lambda **_: [types.SimpleNamespace(pid=4321, cmdline="pwsh -Command sleep 300")],
	)
	text = _synth_text()
	assert "进程台账" in text
	assert "pid=4321" in text


def test_ledger_enabled_without_leftovers_says_so(monkeypatch):
	from engine import process_ledger

	monkeypatch.setattr(process_ledger, "ledger_enabled", lambda: True)
	monkeypatch.setattr(process_ledger, "leftovers", lambda **_: [])
	assert "无存活对象" in _synth_text()


def test_ledger_failure_is_silent(monkeypatch):
	"""台账读炸了 ⇒ 这一句缺席，合成结果照旧（fail-open）。"""
	from engine import process_ledger

	def boom(**_):
		raise RuntimeError("ledger exploded")

	monkeypatch.setattr(process_ledger, "ledger_enabled", lambda: True)
	monkeypatch.setattr(process_ledger, "leftovers", boom)
	text = _synth_text()
	assert "TOOL_OUTCOME_UNKNOWN" in text
	assert "进程台账" not in text


def test_readonly_tool_keeps_not_started_without_ledger_fact(monkeypatch):
	"""只读工具走"未执行"那一支：事实更强，不该再挂台账注脚。"""
	from tools.meta import READONLY_ALLOW

	monkeypatch.setattr("engine.process_ledger.ledger_enabled", lambda: True)
	monkeypatch.setattr("engine.process_ledger.leftovers", lambda **_: [])
	name = sorted(READONLY_ALLOW)[0]
	text = _synth_text(name)
	assert "TOOL_NOT_STARTED" in text
	assert "进程台账" not in text
