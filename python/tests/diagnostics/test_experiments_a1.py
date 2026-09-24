"""A1 的三条硬性质：只改一个变量、不执行工具、不越界声称任务成功。"""

from __future__ import annotations

import pytest

from diagnostics.experiments import a1
from diagnostics.experiments.manifest import SingleVariableViolation
from diagnostics.experiments.reservation import Ledger
from diagnostics.experiments.reservation import clear_ledger_errors
from model.chunks import ModelChunk
from msgtypes.message import ToolUse


class SpyClient:
	"""记录每次收到的请求面；yield 一段文本 + 一个 tool_use（A1 必须只收不执行）。"""

	def __init__(self, *, text: str = "hello", with_tool: bool = True) -> None:
		self.calls: list[dict] = []
		self._text = text
		self._with_tool = with_tool

	async def stream(self, messages, tools, abort):
		self.calls.append({"messages": [dict(m) for m in messages], "tools": list(tools)})
		for ch in self._text:
			yield ModelChunk(kind="text_delta", text=ch)
		if self._with_tool:
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(id="call_1", name="echo", input={"text": "x"}),
			)


class ExplodingRegistry:
	"""任何一次工具执行都会炸：A1 走的是"只保留工具协议"的路径，不该碰它。"""

	def __init__(self) -> None:
		self.used = 0

	def schemas(self) -> list[dict]:
		return [{"name": "echo", "description": "d", "input_schema": {"type": "object"}}]

	async def run(self, *args, **kwargs):  # pragma: no cover — 被调用即测试失败
		self.used += 1
		raise AssertionError("A1 must never execute a tool call")


def _checkpoint(**over: object) -> a1.Checkpoint:
	base = a1.Checkpoint(
		blocks={"identity": "ID", "compact": "OLD"},
		block_order=["identity", "compact"],
		messages=[{"role": "user", "content": "do it"}],
		tools=[{"name": "echo", "description": "d", "input_schema": {}}],
		model="fake",
		provider="fake",
		params={"temperature": 0.3},
	)
	for key, value in over.items():
		setattr(base, key, value)
	return base


def test_run_pair_rejects_second_differing_variable() -> None:
	spy = SpyClient()
	with pytest.raises(SingleVariableViolation) as exc:
		a1.run_pair(
			checkpoint=_checkpoint(),
			variants={
				"A": {"blocks": {"compact": "OLD"}},
				"B": {"blocks": {"compact": "NEW"}, "params": {"temperature": 0.9}},
			},
			allowed_differences=["blocks.compact"],
			client=spy,
		)
	assert exc.value.comparability["ok"] is False
	assert "params.temperature" in exc.value.comparability["undeclared"][0]["path"]
	# 闸门在发请求之前：一臂都没跑
	assert spy.calls == []


def test_tool_definitions_changing_is_a_second_variable() -> None:
	with pytest.raises(SingleVariableViolation):
		a1.run_pair(
			checkpoint=_checkpoint(),
			variants={
				"A": {"blocks": {"compact": "OLD"}},
				"B": {"blocks": {"compact": "NEW"}, "tools": [{"name": "Read"}]},
			},
			client=SpyClient(),
		)


def test_history_length_change_is_a_second_variable() -> None:
	with pytest.raises(SingleVariableViolation):
		a1.run_pair(
			checkpoint=_checkpoint(),
			variants={
				"A": {"blocks": {"compact": "OLD"}},
				"B": {
					"blocks": {"compact": "NEW"},
					"messages": [
						{"role": "user", "content": "do it"},
						{"role": "assistant", "content": "ok"},
					],
				},
			},
			client=SpyClient(),
		)


def test_identical_arms_are_refused_as_no_difference() -> None:
	with pytest.raises(SingleVariableViolation) as exc:
		a1.run_pair(
			checkpoint=_checkpoint(),
			variants={"A": {"blocks": {"compact": "SAME"}}, "B": {"blocks": {"compact": "SAME"}}},
			client=SpyClient(),
		)
	assert "no_difference" in [r["code"] for r in exc.value.comparability["reasons"]]


def test_declared_block_that_does_not_exist_is_refused() -> None:
	with pytest.raises(SingleVariableViolation) as exc:
		a1.run_pair(
			checkpoint=_checkpoint(),
			variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
			allowed_differences=["blocks.nope"],
			client=SpyClient(),
		)
	assert "declared_difference_absent" in [r["code"] for r in exc.value.comparability["reasons"]]


def test_tool_calls_are_collected_but_never_executed() -> None:
	spy = SpyClient()
	registry = ExplodingRegistry()
	result = a1.run_pair(
		checkpoint=_checkpoint(tools=registry.schemas()),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=spy,
		experiment_id="exp_a1",
	)
	assert registry.used == 0
	assert result["tool_calls_executed_total"] == 0
	for arm in ("A", "B"):
		response = result["arms"][arm]["response"]
		assert len(response["tool_calls"]) == 1
		assert response["tool_calls"][0]["name"] == "echo"
		assert response["tool_calls_executed"] == 0
	# 工具协议仍在请求里，但请求里没出现任何 tool_result（未被执行过）
	assert spy.calls[0]["tools"]
	for call in spy.calls:
		assert not any("tool_result" in str(m.get("content")) for m in call["messages"])
	assert len(spy.calls) == 2


def test_experiment_markers_never_enter_the_request() -> None:
	spy = SpyClient()
	result = a1.run_pair(
		checkpoint=_checkpoint(),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=spy,
		experiment_id="exp_marker_42",
	)
	blob = str(spy.calls)
	assert "exp_marker_42" not in blob
	assert result["arms"]["A"]["sent"] is True


def test_marker_leak_in_block_text_is_refused_before_request() -> None:
	spy = SpyClient()
	with pytest.raises(a1.MarkerLeakError):
		a1.run_pair(
			checkpoint=_checkpoint(),
			variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "see exp_leak_1"}}},
			client=spy,
			experiment_id="exp_leak_1",
		)
	assert spy.calls == []


def test_structural_scoring_reports_facts_not_task_success() -> None:
	result = a1.run_pair(
		checkpoint=_checkpoint(),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=SpyClient(text="same"),
	)
	pairing = result["pairing"]
	assert pairing["identical_output"] is True
	assert pairing["different_output"] is False
	assert result["claims"]["task_success"] is False
	assert "整题" in result["does_not_answer"]
	assert "旧提示词" in result["caveat"]

	diverging = a1.run_pair(
		checkpoint=_checkpoint(),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=SpyClient(text="alpha", with_tool=False),
	)
	# 两臂跑的是同一个客户端：文本相同 ⇒ 结构判分只说"相同/不同"，不说谁更好
	assert diverging["pairing"]["identical_output"] is True
	assert "更好" not in diverging["pairing"]["statement"]


def test_different_tool_choice_is_scored_structurally() -> None:
	class ToolOnlyClient:
		def __init__(self) -> None:
			self.n = 0

		async def stream(self, messages, tools, abort):
			self.n += 1
			name = "echo" if self.n == 1 else "Read"
			yield ModelChunk(kind="tool_use", tool_use=ToolUse(id="c", name=name, input={}))

	result = a1.run_pair(
		checkpoint=_checkpoint(),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=ToolOnlyClient(),
	)
	features = {f["feature"]: f for f in result["pairing"]["features"]}
	assert features["tool_names"]["equal"] is False
	assert result["pairing"]["identical_output"] is False
	assert result["pairing"]["different_output"] is True


def test_reservation_denial_stops_the_second_arm_without_requesting() -> None:
	clear_ledger_errors()
	ledger = Ledger(
		"exp_a1_budget",
		cap_cny=0.9,
		price={"status": "ok", "currency": "CNY", "rates": {"hit": 1.0, "miss": 1.0, "out": 1.0}},
		provider="fake",
		model="fake",
	)
	assert ledger.open()["allowed"] is True
	spy = SpyClient()
	result = a1.run_pair(
		checkpoint=_checkpoint(),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=spy,
		budget=ledger,
		experiment_id="exp_a1_budget",
		max_input_tokens=500_000,
		max_output_tokens=100_000,
	)
	assert len(spy.calls) == 1  # 只有 A 臂真的发出去了
	assert result["arms"]["A"]["sent"] is True
	assert result["arms"]["B"]["sent"] is False
	assert result["arms"]["B"]["invalid"] is True
	assert "budget_exhausted" in result["arms"]["B"]["error"]


def test_unknown_usage_keeps_reservation_after_pair() -> None:
	clear_ledger_errors()
	ledger = Ledger(
		"exp_a1_usage",
		cap_cny=10.0,
		price={"status": "ok", "currency": "CNY", "rates": {"hit": 0.02, "miss": 1.0, "out": 4.0}},
		provider="fake",
		model="fake",
	)
	ledger.open()
	a1.run_pair(
		checkpoint=_checkpoint(),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=SpyClient(),
		budget=ledger,
		experiment_id="exp_a1_usage",
		max_input_tokens=10_000,
		max_output_tokens=1_000,
	)
	state = ledger.state()
	# FakeModelClient 不报 usage ⇒ 两次预留都必须全额留在账上
	assert state["requests_settled"] == 2
	assert state["unknown_usage_keys"]
	assert state["settled_cny"] > 0
	assert state["held_cny"] == 0


def test_variant_with_unknown_key_is_refused() -> None:
	with pytest.raises(a1.A1Error):
		a1.apply_variant(_checkpoint(), {"system_prompt": "nope"})


def test_build_request_does_not_mutate_checkpoint() -> None:
	cp = _checkpoint()
	before = cp.blocks["compact"]
	a1.build_request(cp)
	cp.messages.append({"role": "user", "content": "injected"})
	assert cp.blocks["compact"] == before
	rebuilt = a1.build_request(_checkpoint())
	assert len(rebuilt["messages"]) == 2  # system + 1 条历史


def test_markdown_shows_both_arms_side_by_side() -> None:
	result = a1.run_pair(
		checkpoint=_checkpoint(),
		variants={"A": {"blocks": {"compact": "OLD"}}, "B": {"blocks": {"compact": "NEW"}}},
		client=SpyClient(text="ok"),
	)
	text = a1.to_markdown(result)
	assert "### 臂 A" in text and "### 臂 B" in text
	assert "工具调用未执行" in text
