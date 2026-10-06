"""E2E（进程内真引擎，无付费调用）：回合中途按停 ⇒ 落库历史必须仍是厂商合法形状。

厂商按两条配对规则校验请求体：
1. ``role=tool`` 必须是紧邻前置 assistant ``tool_calls`` 的应答；
2. assistant 带了 ``tool_calls`` 就必须每个 id 都有后续 ``role=tool``。
按停落在"工具正在跑"的那一刻是最危险的窗口：工具没返回结果，引擎又要接着发下一枪。
``session/hydrate._repair_unclosed_tool_uses`` 只在**读档**时补位；进程内被打断的这一轮
若留下悬空 ``tool_calls``，下一枪当场 400（不是重启后才坏）。

这里用真的 ``query_loop`` + ``MessageStore.as_api_messages`` + ``normalize_messages_for_openai``
走完整链，只把模型换成仓库自带的 ``FakeModelClient``、工具换成一个"挂在 abort 上"的工具。
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from model._openai_common import normalize_messages_for_openai, prune_orphan_tool_rows
from model.fake import FakeModelClient
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry
from msgtypes.message import assistant_text_message, tool_result_message, user_message


class _HangingTool:
	"""name=echo ⇒ 命中 FakeModelClient 的规则 #2（用户文本以 "echo:" 开头就发起 tool_use）。

	执行体一直等到被中止——真实长任务（Bash / 子进程 / 网络）都是轮询 abort。
	"""

	name = "echo"

	def __init__(self) -> None:
		self.started = asyncio.Event()
		self.interrupted = asyncio.Event()

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		return {
			"name": "echo",
			"description": "hang until aborted",
			"input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
		}

	async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
		self.started.set()
		while not abort.aborted:
			await asyncio.sleep(0.01)
		self.interrupted.set()
		abort.raise_if_aborted()
		return ToolResult(content="unreachable")


def _wire(store: MessageStore) -> list[dict]:
	return normalize_messages_for_openai(store.as_api_messages(), provider="deepseek", model="x")


def _dangling(wire: list[dict]) -> list[str]:
	"""assistant 的 tool_calls 里，后面没有对应 role=tool 应答的 id。"""
	out: list[str] = []
	i = 0
	while i < len(wire):
		m = wire[i]
		if m.get("role") == "assistant" and m.get("tool_calls"):
			need = {str(c.get("id")) for c in m["tool_calls"] if c.get("id")}
			got: set[str] = set()
			j = i + 1
			while j < len(wire) and wire[j].get("role") == "tool":
				got.add(str(wire[j].get("tool_call_id") or ""))
				j += 1
			out.extend(sorted(need - got))
			i = j
			continue
		i += 1
	return out


def test_invariant_checks_catch_the_bad_shapes():
	"""两条不变量的正控：故意造坏历史，检查器必须点名（否则上面的断言是装饰）。"""
	from msgtypes.message import ToolUse

	calls = [ToolUse(id="call_A", name="echo", input={"text": "x"})]
	# 悬空调用：assistant 带 tool_use，后面没有任何 role=tool
	bad = MessageStore([user_message("go"), assistant_text_message("", tool_uses=calls)])
	assert _dangling(_wire(bad)) == ["call_A"]
	# 双向校：补上应答就必须变干净（防"恒红"也算过）
	good = MessageStore([
		user_message("go"),
		assistant_text_message("", tool_uses=calls),
		tool_result_message("call_A", "echo", "done"),
	])
	assert _dangling(_wire(good)) == []
	assert prune_orphan_tool_rows(_wire(good))[1] == []
	# 无主结果：凭空多一条 role=tool ⇒ 必须进不了发射投影
	# （实测由 `MessageStore.as_api_messages` 的 `discard_unpaired_tool_results` 就拦住，
	#   最后一公里守卫因此不必出手——两层的口径都要校，缺一层就是裸奔）
	orphan = MessageStore([user_message("go"), tool_result_message("call_Z", "echo", "stray")])
	orphan_wire = _wire(orphan)
	assert [r.get("role") for r in orphan_wire] == ["user"], orphan_wire
	assert prune_orphan_tool_rows(orphan_wire)[1] == []


@pytest.mark.asyncio
async def test_interrupt_mid_tool_keeps_history_provider_valid():
	"""判据落在被量的对象上：发射投影（不是内部列表长度、不是事件计数）。"""
	store = MessageStore([user_message("echo: hi")])
	tool = _HangingTool()
	reg = ToolRegistry()
	reg.register(tool)
	abort = AbortController()

	async def drive() -> list[object]:
		evs: list[object] = []
		async for ev in query_loop(
			store=store,
			model=FakeModelClient(),
			tools=reg,
			prompt=PromptAssembler(),
			system_prompt=DEFAULT_SYSTEM,
			abort=abort,
			budget=BudgetTracker(max_turns=4),
		):
			evs.append(ev)
		return evs

	task = asyncio.create_task(drive())
	# 前置自证：工具确实起来了（否则这条门测的是"从没走到那一步"）。
	await asyncio.wait_for(tool.started.wait(), timeout=5.0)
	abort.abort()
	try:
		events = await asyncio.wait_for(task, timeout=15.0)
	except Exception:  # noqa: BLE001 — 中止可以正常收尾，也可以抛 Aborted；两种都接受
		events = []

	assert tool.interrupted.is_set(), "工具没被真正中止 ⇒ 这条用例没走到目标分支"

	# 1) 不许有无主 tool 行（守卫若丢弃会打日志，这里要求它一次都不必出手）
	_, dropped = prune_orphan_tool_rows(_wire(store))
	assert dropped == [], f"投影里有无主 tool 行，被最后一公里守卫吃掉：{dropped}"

	# 2) 不许有悬空 tool_calls —— 按停最常见的坏形状
	wire = _wire(store)
	dangle = _dangling(wire)
	assert dangle == [], (
		f"被打断的 tool_call 没有终态应答，下一枪必被厂商拒（400）：{dangle}"
	)

	# 3) 被打断的那一次调用必须在历史里留下可判定的终结（不能"没发生"）
	tool_rows = [m for m in store.items if m.role == "tool"]
	assert tool_rows, "按停后一条工具结果都没有 ⇒ 模型看不到自己那次调用的下场"
	kinds = " ".join(str(getattr(m, "name", "") or "") for m in tool_rows)
	body = " ".join(
		str(b.get("content") if isinstance(b, dict) else "") [:400]
		for b in (tool_rows[-1].content if isinstance(tool_rows[-1].content, list) else [])
	)
	assert "abort" in (kinds + body).lower() or "interrupt" in (kinds + body).lower() or "not started" in body.lower() or "unknown" in body.lower(), (
		f"工具结果没写明这次调用是被中止的：{body[:200]!r}"
	)
	assert isinstance(events, list)
