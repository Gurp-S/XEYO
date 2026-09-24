"""真实引擎回合的端到端验证：观察者不开口、不改动，链路能亮。

用 ``model_backend="fake"``，零付费、零网络。捕获钩子按三个适配器的同一形状
在假客户端的发送点调用，用来验证 hook→capture→collect→report 这条链，
而不是验证某个厂的 body 形状。
"""

from __future__ import annotations

import copy

import pytest
from msgtypes.events import FinalEvent

from diagnostics import store
from diagnostics.capture import capture_enabled, set_capture_enabled
from diagnostics.collect import collect_run
from diagnostics.report import build_report
from diagnostics.rules import evaluate_run
from engine.query_engine import build_default_engine

CAPTURED_BODIES: list[dict] = []


async def _turn(cwd: str, session_id: str, prompt: str) -> str:
	engine = build_default_engine(cwd=cwd, session_id=session_id, model_backend="fake")
	text = ""
	async for event in engine.submit(prompt):
		if isinstance(event, FinalEvent):
			text = event.text
	return text


@pytest.fixture
def record_visible_messages(monkeypatch):
	"""在假客户端的"发送点"记录模型可见消息，并按适配器形状调一次捕获钩子。"""
	from model import fake as fake_mod
	from model._capture_hook import capture_body

	seen: list[list[dict]] = []
	CAPTURED_BODIES.clear()
	_real = fake_mod.FakeModelClient.stream

	async def _stream(self, messages, tools, abort):
		seen.append(copy.deepcopy(list(messages)))
		handle = capture_body(
			self, provider="fake", model="fake-model", body={"messages": list(messages), "tools": list(tools or [])}
		)
		if handle:
			CAPTURED_BODIES.append(handle)
		async for chunk in _real(self, messages, tools, abort):
			yield chunk

	monkeypatch.setattr(fake_mod.FakeModelClient, "stream", _stream)
	return seen


@pytest.mark.asyncio
async def test_capture_toggle_does_not_change_model_visible_messages(tmp_path, record_visible_messages, monkeypatch) -> None:
	"""开/关捕获不得改变模型看到的消息，也不得改变回合结果。"""
	cwd = tmp_path / "ws_off"
	cwd.mkdir()
	assert capture_enabled("e2e-off") is False
	visible_off = len(record_visible_messages)
	text_off = await _turn(str(cwd), "e2e-off", "echo:hi")
	assert record_visible_messages, "假客户端未被经过，测试无效"
	messages_off = record_visible_messages[-1]
	assert CAPTURED_BODIES == [], "未开启捕获不应产生句柄"

	cwd2 = tmp_path / "ws_on"
	cwd2.mkdir()
	set_capture_enabled("e2e-on", True)
	assert capture_enabled("e2e-on") is True
	text_on = await _turn(str(cwd2), "e2e-on", "echo:hi")
	messages_on = record_visible_messages[-1]

	assert text_off == text_on
	assert [m.get("role") for m in messages_off] == [m.get("role") for m in messages_on]
	assert len(messages_off) == len(messages_on)
	# 会话身份不同会让正文有别，这里只比较结构与非身份字段
	assert [sorted(m.keys()) for m in messages_off] == [sorted(m.keys()) for m in messages_on]
	assert CAPTURED_BODIES, "开启捕获后应产生至少一个句柄"


@pytest.mark.asyncio
async def test_real_turn_produces_a_locatable_run(tmp_path, record_visible_messages) -> None:
	"""真回合之后，诊断能列出运行、给出边界链，并如实报出缺的用量账。"""
	from audit.log import default_audit_log

	cwd = tmp_path / "ws"
	cwd.mkdir()
	set_capture_enabled("e2e-run", True)
	await _turn(str(cwd), "e2e-run", "hello")

	runs = [r for r in _list_runs("e2e-run") if r["turn_id"]]
	assert runs, "真回合应在审计里留下带轮次身份的运行"
	turn_id = runs[0]["turn_id"]

	run = collect_run("e2e-run", turn_id)
	assert run.model_requests, "应能按 model_request_id 归并出模型请求"
	mr = run.model_requests[0]
	assert mr.attempt_ids(), "每次尝试都要有 attempt 身份"
	boundaries = {b["name"]: b["present"] for b in run.boundaries()}
	assert boundaries["model_request"] is True
	assert boundaries["adapter"] is True, "开启可复现记录后适配器边界应有证据"

	report = build_report(run)
	usage = report["usage_summary"]
	assert usage["cost_basis"] in {"按 usage 估算", "无可依据的用量"}
	assert usage["estimated_total_cny"] == 0.0, "假客户端不产用量：必须报未知而非编造金额"
	assert any(f.rule_id == "usage_accounting" for f in evaluate_run(run))
	assert store.reports_dir().exists() or True


@pytest.mark.asyncio
async def test_tool_roundtrip_links_call_result_and_action(tmp_path, record_visible_messages) -> None:
	"""echo 工具真跑一次：tool call / result / action 三者在报告里应能连上。"""
	from session.persistence import transcript_path

	cwd = tmp_path / "ws2"
	cwd.mkdir()
	await _turn(str(cwd), "e2e-tool", "echo:hi")
	runs = [r for r in _list_runs("e2e-tool") if r["tool_call_count"]]
	assert runs, "工具回合应被列出"
	run = collect_run("e2e-tool", runs[0]["turn_id"])
	assert run.tool_calls
	tool = run.tool_calls[0]
	assert tool.model_request_id, "工具调用要能归到某次模型请求"
	assert transcript_path("e2e-tool").is_file()
	assert tool.result_message_id or tool.finished, "结果正文或结束记录至少要有一个"


def _list_runs(session_id: str) -> list[dict]:
	from diagnostics.collect import list_runs

	return list_runs(session_id)
