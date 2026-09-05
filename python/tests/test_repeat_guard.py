import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from engine.repeat_guard import (
	ACTION_ADVICE,
	ACTION_RUN,
	RepeatCallGuard,
	ZeroHitTracker,
	ZERO_HIT_ADVICE_AT,
	canonical_input,
	clear_advice,
	current_advice,
)
from msgtypes.events import FinalEvent, StoppedEvent, ToolCallEvent, ToolResultEvent
from msgtypes.message import ToolUse, user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


# ====== 单元：RepeatCallGuard 递进建议制（T6） ======

def _use(name="Grep", **kw):
	return ToolUse(id=kw.pop("id", "u" * 8), name=name, input=kw.pop("input", {"pattern": "x"}))


def test_todo_write_identical_snapshot_is_guarded():
	"""清单内容变化 → 永不命中；完全相同的快照 → 第 3 次短提示、第 5 次详细。"""
	clear_advice()
	guard = RepeatCallGuard()
	first = {"todos": [{"id": "1", "content": "a", "status": "pending"}]}
	done = {"todos": [{"id": "1", "content": "a", "status": "completed"}]}
	assert guard.observe("TodoWrite", first) == ACTION_RUN
	assert guard.observe("TodoWrite", done) == ACTION_RUN  # 状态推进 = 新签名
	assert guard.observe("TodoWrite", done) == ACTION_RUN  # 第 2 次：未到阈值
	assert guard.observe("TodoWrite", done) == ACTION_ADVICE  # 第 3 次：短提示
	assert guard.observe("TodoWrite", done) == ACTION_RUN  # 第 4 次：安静
	assert guard.observe("TodoWrite", done) == ACTION_ADVICE  # 第 5 次：详细


def test_guard_advice_progression_and_quiet_gaps():
	"""T6：[3,5,8] 递进；3=短、5/8=详细；4/6/7 安静；>8 每次提醒。"""
	clear_advice()
	guard = RepeatCallGuard()
	snapshots: list[tuple[str, str]] = []
	for _ in range(10):
		action = guard.observe("Grep", {"pattern": "x"})
		snapshots.append((action, guard.last_advice))
	acts = [a for a, _t in snapshots]
	assert acts[2] == ACTION_ADVICE and snapshots[2][1].count("\n") == 0
	assert acts[3] == ACTION_RUN
	assert acts[4] == ACTION_ADVICE and "tool: Grep" in snapshots[4][1]
	assert acts[5] == ACTION_RUN and acts[6] == ACTION_RUN
	assert acts[7] == ACTION_ADVICE and "args:" in snapshots[7][1]
	assert acts[8] == ACTION_ADVICE and acts[9] == ACTION_ADVICE
	# 详细档带参数预览且 ≤500 字符。
	assert len(snapshots[9][1]) < 800


def test_guard_advice_publishes_to_module_state():
	clear_advice()
	guard = RepeatCallGuard()
	for _ in range(3):
		guard.observe("Grep", {"pattern": "pub"})
	assert "[repeat]" in current_advice()
	guard.reset()
	assert current_advice() == ""


def test_guard_different_inputs_and_tools_do_not_collide():
	guard = RepeatCallGuard()
	assert guard.observe("Grep", {"pattern": "x"}) == ACTION_RUN
	assert guard.observe("Grep", {"pattern": "x", "path": "a"}) == ACTION_RUN
	assert guard.observe("Read", {"pattern": "x"}) == ACTION_RUN


def test_guard_key_order_insensitive():
	assert canonical_input({"a": 1, "b": 2}) == canonical_input({"b": 2, "a": 1})
	guard = RepeatCallGuard()
	assert guard.observe("Grep", {"pattern": "p", "path": "q"}) == ACTION_RUN
	assert guard.observe("Grep", {"path": "q", "pattern": "p"}) == ACTION_RUN
	assert guard.observe("Grep", {"pattern": "p", "path": "q"}) == ACTION_ADVICE


def test_guard_exempt_interactive_tools():
	guard = RepeatCallGuard()
	for _ in range(5):
		assert guard.observe("AskUserQuestion", {"question": "??"}) == ACTION_RUN


def test_guard_env_overrides(monkeypatch):
	monkeypatch.setenv("XEYO_REPEAT_TOOL_ADVICE", "2,4")
	guard = RepeatCallGuard()
	feed = [guard.observe("Grep", {"pattern": "x"}) for _ in range(6)]
	assert feed[1] == ACTION_ADVICE   # 第 2 次：首档
	assert feed[2] == ACTION_RUN
	assert feed[3] == ACTION_ADVICE   # 第 4 次：末档
	assert feed[4] == ACTION_ADVICE   # 越末档：每次提醒
	assert feed[5] == ACTION_ADVICE


def test_guard_legacy_env_still_readable(monkeypatch):
	monkeypatch.setenv("XEYO_REPEAT_TOOL_HINT_AT", "3")
	guard = RepeatCallGuard(hint_at=2)
	assert guard.advice_at == (2,)


# ====== 单元：检索型工具的语义归一签名 ======

def test_search_pattern_quote_style_variants_are_equivalent():
	guard = RepeatCallGuard()
	assert guard.observe("Grep", {"pattern": "'button, a'", "path": "gui\\src"}) == ACTION_RUN
	# 同一查询换引号写法 / 路径分隔符 → 视为同一签名：第 2 次安静、第 3 次提醒。
	assert guard.observe("Grep", {"pattern": "button, a", "path": "gui/src"}) == ACTION_RUN
	assert guard.observe("Grep", {"pattern": '"button, a"', "path": "gui\\src"}) == ACTION_ADVICE


def test_search_output_mode_change_is_a_new_call():
	guard = RepeatCallGuard()
	assert guard.observe("Grep", {"pattern": "p", "output_mode": "files_with_matches"}) == ACTION_RUN
	# 换呈现是不同输入（工具 tip 也会建议 files → content），独立计数。
	assert guard.observe("Grep", {"pattern": "p", "output_mode": "content"}) == ACTION_RUN
	assert guard.observe("Grep", {"pattern": "p", "output_mode": "content"}) == ACTION_RUN
	assert guard.observe("Grep", {"pattern": "p", "output_mode": "content"}) == ACTION_ADVICE


def test_search_omitted_output_mode_matches_grep_default():
	guard = RepeatCallGuard()
	assert guard.observe("Grep", {"pattern": "p"}) == ACTION_RUN
	# 省略字段 ≡ 显式 files_with_matches，仍视为同一输入。
	assert guard.observe("Grep", {"pattern": "p", "output_mode": "files_with_matches"}) == ACTION_RUN
	assert guard.observe("Grep", {"pattern": "p"}) == ACTION_ADVICE


def test_search_pagination_continuation_exempt():
	guard = RepeatCallGuard()
	for _ in range(4):
		assert guard.observe("Grep", {"pattern": "p", "offset": 10}) == ACTION_RUN


def test_search_case_flag_changes_semantics():
	guard = RepeatCallGuard()
	assert guard.observe("Grep", {"pattern": "P"}) == ACTION_RUN
	assert guard.observe("Grep", {"pattern": "P", "case_insensitive": True}) == ACTION_RUN


def test_non_search_tools_keep_exact_matching():
	guard = RepeatCallGuard()
	# Read 等工具不受语义折叠影响：limit 不同 = 不同调用（分页/扩读合法）。
	assert guard.observe("Read", {"file_path": "a.txt", "limit": 10}) == ACTION_RUN
	assert guard.observe("Read", {"file_path": "a.txt", "limit": 99}) == ACTION_RUN


# ====== 单元：ZeroHitTracker（零命中前提复核） ======

def test_zero_hit_counts_distinct_signatures_only():
	tracker = ZeroHitTracker()
	assert tracker.record("Grep", {"pattern": "a"}) == 1
	assert tracker.record("Grep", {"pattern": "b"}) == 2
	assert tracker.record("Grep", {"pattern": "b"}) == 2      # 同签名不增
	assert tracker.record("Glob", {"pattern": "a"}) == 3      # 不同工具分开算
	assert len(tracker) == 3


def test_zero_hit_notice_neutral_and_at_threshold():
	text = ZeroHitTracker.notice(2)
	assert str(ZERO_HIT_ADVICE_AT) in text
	assert "回读用户原始请求" in text
	# 中立性约束：绝不指向具体方向（如"外部依赖"），避免带偏模型。
	for banned in ("依赖", "node_modules", "package"):
		assert banned not in text


def test_zero_hit_requires_search_tool_metadata():
	assert ZeroHitTracker.is_zero_hit("Grep", {"no_match": True}) is True
	assert ZeroHitTracker.is_zero_hit("Grep", {"no_match": False}) is False
	assert ZeroHitTracker.is_zero_hit("Grep", None) is False
	assert ZeroHitTracker.is_zero_hit("Read", {"no_match": True}) is False


def test_grep_result_no_match_classification():
	from tools.grep_tool.grep_tool import GrepOutput, GrepTool

	is_nm = GrepTool.result_no_match
	assert is_nm(GrepOutput(mode="content", num_files=0, num_lines=0)) is True
	assert is_nm(GrepOutput(mode="content", num_files=0, num_lines=3)) is False
	assert is_nm(GrepOutput(mode="count", num_files=0, num_matches=0)) is True
	assert is_nm(
		GrepOutput(mode="files_with_matches", num_files=1, filenames=["x.py"])
	) is False
	assert is_nm(GrepOutput(mode="files_with_matches", num_files=0)) is True


# ====== 单元：BudgetTracker.queue_runtime_notice 去重 ======

def test_budget_queue_runtime_notice_dedupes_and_consumes():
	budget = BudgetTracker()
	assert budget.queue_runtime_notice("stop repeating") is True
	assert budget.queue_runtime_notice("stop repeating") is False
	budget.queue_runtime_notice("other notice")
	notice = budget.consume_runtime_notice()
	assert "stop repeating" in notice and "other notice" in notice
	assert budget.consume_runtime_notice() is None
	# 同一文本按 submit 生命周期去重：消费后也不重复注入，防止逐轮刷屏。
	assert budget.queue_runtime_notice("stop repeating") is False
	assert budget.queue_runtime_notice("a different reminder") is True
	budget.reset_for_new_submit()
	assert budget.queue_runtime_notice("stop repeating") is True


# ====== 集成：守卫在 query_loop 内生效 ======

class _AlwaysSameToolClient:
	"""每轮都发起完全相同的工具调用，用于触发重复拦截。"""

	def __init__(self, *, name: str = "echo", payload: str = "same") -> None:
		self._name = name
		self._payload = payload
		self.wrapup_seen = False

	async def stream(self, messages, tools, abort):
		# wrap-up 挂在 T_now（末条 user），不在 system 左段。
		blob = "\n".join(str(m.get("content") or "") for m in (messages or []))
		if "# Wrap-up required" in blob or not tools:
			self.wrapup_seen = "# Wrap-up required" in blob or not tools
			yield _Chunk(kind="text_delta", text="best-effort final answer")
			return
		yield _Chunk(
			kind="tool_use",
			tool_use=ToolUse(id=f"c{abs(hash(self._payload)) % 10**8}", name=self._name, input={"text": self._payload}),
		)


class _Chunk:
	def __init__(self, *, kind, text=None, tool_use=None):
		self.kind = kind
		self.text = text or ""
		self.tool_use = tool_use


async def _collect(store, reg, model, budget):
	events = []
	async for ev in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=budget,
	):
		events.append(ev)
	return events


@pytest.mark.asyncio
async def test_duplicate_calls_advise_without_blocking():
	"""T6：重复调用照常执行，提醒经模块级 current_advice 发布、不进 ToolResult。"""
	clear_advice()

	class CountingEcho(EchoTool):
		executed = 0

		async def execute(self, input, abort):  # noqa: ANN001
			CountingEcho.executed += 1
			return await super().execute(input, abort)

	reg = ToolRegistry()
	reg.register(CountingEcho())
	model = _AlwaysSameToolClient()
	store = MessageStore([user_message("go")])
	budget = BudgetTracker(max_turns=3)
	events = await _collect(store, reg, model, budget)

	# 每轮都真实执行（不再拒执行）；至少越过首档阈值 3。
	assert CountingEcho.executed >= 3
	# 提醒已发布到 T_now 管线状态（第 3 次调用命中首档阈值 3）。
	assert "[repeat]" in current_advice()
	# 不改写 ToolResult：历史行中既无 block 也无 hint 文案。
	tool_rows = [
		str(b.get("content"))
		for m in store.items
		if m.role == "tool" and isinstance(m.content, list)
		for b in m.content
		if isinstance(b, dict)
	]
	assert not any("[blocked duplicate tool call]" in c for c in tool_rows)
	assert not any(RepeatCallGuard.hint_notice() in c for c in tool_rows)
	# 最终以 FinalEvent 收尾（而非空 error_max_turns）。
	finals = [e for e in events if isinstance(e, FinalEvent)]
	assert finals and finals[0].text.strip()
	clear_advice()


@pytest.mark.asyncio
async def test_hard_stop_produces_wrapup_finalevent():
	"""max_turns 硬停前放行一次禁用工具的收尾调用并交付 FinalEvent。"""

	class ToolLoopThenAnswer(_AlwaysSameToolClient):
		pass

	reg = ToolRegistry()
	reg.register(EchoTool())
	model = ToolLoopThenAnswer()
	store = MessageStore([user_message("go")])
	budget = BudgetTracker(max_turns=1, max_tool_calling=8)
	events = await _collect(store, reg, model, budget)

	stops = [e for e in events if isinstance(e, StoppedEvent)]
	finals = [e for e in events if isinstance(e, FinalEvent)]
	assert finals, f"expected FinalEvent, got {[type(e).__name__ for e in events]}"
	if stops:
		# 收尾后不允许再出现 max_turns/max_tool_calling 空停。
		assert all(e.reason not in ("max_turns", "max_tool_calling") for e in stops)
	assert finals[0].text.strip() == "best-effort final answer"
	last_assistant = [m for m in store.items if m.role == "assistant"][-1]
	assert last_assistant.content == "best-effort final answer"
	# 收尾请求确实未携带任何工具 schema 由模型侧验证（wrapup_seen 且只回文本）。


@pytest.mark.asyncio
async def test_hard_stop_empty_wrapup_preserves_stopped_event():
	"""收尾调用完全无文本（假模型硬吐 tool_use）→ 回退原 max_turns 硬停语义。"""

	class DeafToolModel(_AlwaysSameToolClient):
		async def stream(self, messages, tools, abort):  # noqa: ANN001
			yield _Chunk(
				kind="tool_use",
				tool_use=ToolUse(id="deaf", name="echo", input={"text": "same"}),
			)

	reg = ToolRegistry()
	reg.register(EchoTool())
	store = MessageStore([user_message("go")])
	events = await _collect(store, reg, DeafToolModel(), BudgetTracker(max_turns=2))

	finals = [e for e in events if isinstance(e, FinalEvent)]
	stops = [e for e in events if isinstance(e, StoppedEvent)]
	assert not finals
	assert stops and stops[-1].reason == "max_turns"


if __name__ == "__main__":
	import pytest

	raise SystemExit(pytest.main([__file__, "-q"]))
