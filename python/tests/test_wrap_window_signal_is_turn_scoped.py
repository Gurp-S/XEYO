"""收尾窗广播是**回合内**信号，循环出口必须把它关掉。

`engine/wrap_window.py` 自己写的不变量：「未武装墙钟 / 未进入收尾窗时
``in_wrap_window()`` 恒 False」，并且导出了 `clear_wrap_window()`。
10-04 实测：全仓 `clear_wrap_window` **零调用者**，而 `query_loop.py:931`
每轮刷新一次（含 inactive）——于是"从收尾窗里退出循环"的那条出口
（预算/宽限耗尽 → `StoppedEvent` 早退，发生在本轮刷新之前）把 `active=True`
留在上下文里没人收。

危害有具体消费方：`tools/bash_tool/bash_tool.py::effective_promote_ms` 读到
`in_wrap_window()=True` 且 `remaining_s=None`（配额型收尾窗）⇒ 长命令族的晋升阈值
从 45000ms 变成 **1ms**，之后同上下文里每条 `make/pip/pytest/cargo` 都立刻转后台、
模型拿不到正文。而这条路是活的：Agent 工具是 `await run_subagent(...)`
（同 task 直接 await，不是 create_task ⇒ **共享同一份 context**），
子 Agent 预算短、更容易在收尾窗里结束，回到父上下文时就带着残留的 active。

修法一行（在 `engine/query_loop.py`，该文件此刻被并发会话占用）：
把整轮循环体包进 `try/finally`，`finally` 里 `clear_wrap_window()`；
或在进入循环前取 `_SLOT` 的 token、退出时 reset。
修好后本文件的 xfail 会 XPASS 当场红 ⇒ 逼摘标记。

**10-05 已修**：`engine/query_loop.py::query_loop` 套 `_wrap_window_scoped`
装饰器——进入前 `snapshot_wrap_window()`（取还原令牌），退出（含异常 / aclose）
时 `reset_wrap_window(token)` 恢复进入前的值；嵌套循环因此把内层状态还原成
父上下文的值。两条 strict xfail 已摘牌（本文件 4 passed）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from engine.wrap_window import clear_wrap_window, in_wrap_window, wrap_state
from model.chunks import ModelChunk
from msgtypes.message import ToolUse, user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.catalog import build_default_registry


def _promote_ms(cmd: str, base_ms: int) -> int:
	"""延迟导入 Bash 模块。

	该模块正被并发会话逐秒改写，模块级 import 会把一次中间态语法错
	放大成"本文件四条全红"（10-04 在他们的跑测归档里真发生过一次），
	而我这两条 strict xfail 才是本文件的靶心。
	"""
	from tools.bash_tool.bash_tool import effective_promote_ms

	return effective_promote_ms(cmd, base_ms)


@pytest.fixture(autouse=True)
def _pin_ambient_inputs():
	"""本文件的夹具依赖两件事：工具真的被执行、预算真的走到收尾窗。

	两者都可能被前序测试留在**主上下文**里的 ambient 状态打断——全量跑时我的
	正向自证红过一次、独立跑绿（10-04）。⇒ 自己钉住审批档，
	并出声报告入场时的收尾窗残留（谁漏的让谁现形，而不是让我的门替它背红）。
	"""
	from permissions.policy import set_permission_mode

	set_permission_mode("never")
	leftover = wrap_state()
	assert not leftover.active, f"入场时收尾窗已被前序测试泄漏残留：{leftover}"
	yield
	clear_wrap_window()
	set_permission_mode(None)


class _AlwaysCallsTools:
	"""每轮都调一个快工具，把循环推到预算耗尽 ⇒ 必然从收尾窗里退出。"""

	def __init__(self) -> None:
		self.n = 0

	async def stream(self, messages, tools, abort) -> AsyncIterator[ModelChunk]:
		self.n += 1
		yield ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(id=f"c{self.n}", name="getTime", input={}),
		)


async def _run_loop(tmp_path: Path, max_turns: int) -> list[str]:
	client = _AlwaysCallsTools()
	store = MessageStore([user_message("一直调工具，直到预算耗尽")])
	events: list[str] = []
	async for ev in query_loop(
		store=store,
		model=client,
		tools=build_default_registry(cwd=str(tmp_path)),
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=max_turns),
	):
		events.append(type(ev).__name__)
	return events


@pytest.mark.asyncio
async def test_control_the_wrap_signal_really_fires(tmp_path) -> None:
	"""前置自证：这个夹具确实走进过收尾窗（否则下面的断言是恒真）。"""
	client = _AlwaysCallsTools()
	store = MessageStore([user_message("一直调工具，直到预算耗尽")])
	saw_wrap = False
	seen: list[str] = []
	async for ev in query_loop(
		store=store,
		model=client,
		tools=build_default_registry(cwd=str(tmp_path)),
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=1),
	):
		seen.append(type(ev).__name__)
		saw_wrap = saw_wrap or in_wrap_window()
	# 诊断要带在身上：全量跑红过一次却没有原因，下次必须自己说清是哪一步没走到。
	assert saw_wrap, f"夹具没走到收尾窗（其它断言会空转）events={seen}"
	assert "StoppedEvent" in seen, f"预算耗尽应以此事件收尾 events={seen}"


@pytest.mark.asyncio
async def test_npm_style_long_command_is_not_backgrounded_after_loop(tmp_path) -> None:
	"""循环正常结束（非收尾窗出口）时不残留——这条今天就该过。"""
	# 只用 1 轮文本收尾：模型第一次就交文本，循环不在收尾窗里退出
	class _AnswerOnce:
		async def stream(self, messages, tools, abort) -> AsyncIterator[ModelChunk]:
			yield ModelChunk(kind="text_delta", text="收工")

	store = MessageStore([user_message("一句话回答")])
	async for _ in query_loop(
		store=store,
		model=_AnswerOnce(),
		tools=build_default_registry(cwd=str(tmp_path)),
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		pass
	assert in_wrap_window() is False
	assert _promote_ms("make -j4", 45_000) == 45_000


@pytest.mark.asyncio
async def test_wrap_signal_is_cleared_when_the_loop_exits(tmp_path) -> None:
	await _run_loop(tmp_path, max_turns=1)
	assert wrap_state().active is False, wrap_state()
	assert in_wrap_window() is False


@pytest.mark.asyncio
async def test_nested_loop_does_not_leave_parent_in_wrap_window(tmp_path) -> None:
	"""模拟 Agent 工具的通路：在父上下文里直接 await 一次内层循环。"""
	assert in_wrap_window() is False
	await _run_loop(tmp_path / "sub", max_turns=1)
	assert in_wrap_window() is False, "内层循环把父上下文留在了收尾窗里"
	assert _promote_ms("pytest -q", 45_000) == 45_000
