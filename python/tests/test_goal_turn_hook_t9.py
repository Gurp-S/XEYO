"""T9/41 号 turn 结束钩子 —— flush→候选派生（只记账，不调度）。

覆盖：
- 成功 turn + todo 全 done → 置 pending_complete（候选，非自动完成）。
- 成功 turn + todo 未全 done → 保持 active（不置候选、不写盘）。
- 41 号语义修正：**人类轮不消耗 cap**——rounds 只由 round driver 的
  ``admit_round_async`` 推进，turn 钩子不再改轮次。
- 无绑定 goal / 非成功 turn → 钩子 no-op（不抛、不改状态）。
- ``admit_round_async`` CAS + cap 软置候选 + ``create_and_bind_async`` 持久化。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.goal_state import (  # noqa: E402
	GOAL_ROUND_CAP,
	GoalConflict,
	GoalStore,
	candidate_is_pending,
	derive_candidate,
)
from engine.query_engine import QueryEngine  # noqa: E402
from model.chunks import ModelChunk  # noqa: E402
from msgtypes.events import ResultEvent  # noqa: E402
from tools.echo import EchoTool  # noqa: E402
from tools.todo_write_tool.store import DEFAULT_TODO_KEY  # noqa: E402
from tools.todo_write_tool.todo_write_tool import TodoWriteTool  # noqa: E402
from tools.todo_write_tool.types import TodoItem  # noqa: E402
from tools.tool_registry import ToolRegistry  # noqa: E402


class TextModel:
	"""每次返回一段最终文本（成功 turn）。"""

	def __init__(self) -> None:
		self.calls = 0

	async def stream(self, messages, tools, abort):  # noqa: ANN001
		self.calls += 1
		abort.raise_if_aborted()
		yield ModelChunk(kind="text_delta", text="完成了目标")
		return


class EmptyTextModel(TextModel):
	"""返回空文本，使 turn 不以「有文本成功」收尾。"""

	async def stream(self, messages, tools, abort):  # noqa: ANN001
		self.calls += 1
		abort.raise_if_aborted()
		yield ModelChunk(kind="text_delta", text="")
		return


def _engine(tmp_path: Path, session_id: str, model: object) -> tuple[QueryEngine, TodoWriteTool]:
	reg = ToolRegistry()
	reg.register(EchoTool())
	tw = TodoWriteTool(cwd=str(tmp_path), session_id=session_id)
	reg.register(tw)
	eng = QueryEngine(
		{
			"cwd": str(tmp_path),
			"tools": reg,
			"model_client": model,  # type: ignore[typeddict-item]
			"session_id": session_id,
			"max_turns": 4,
			"max_tool_calling": 16,
		}
	)
	return eng, tw


def _set_todos(tw: TodoWriteTool, statuses: list[str]) -> None:
	items = [
		TodoItem(content=f"task {i}", status=s, active_form=f"doing {i}", id=f"t{i}")
		for i, s in enumerate(statuses)
	]
	# 直接灌进工具共享 store（与 TodoStore 的 default key 对齐）。
	tw._store.set(items, key=DEFAULT_TODO_KEY)


async def _submit(eng: QueryEngine, text: str = "do the work"):
	events = [e async for e in eng.submit(text)]
	success = [e for e in events if isinstance(e, ResultEvent) and not e.is_error]
	return events, success


@pytest.mark.asyncio
async def test_success_turn_with_todos_done_sets_pending_complete(tmp_path: Path) -> None:
	sid = "sess-todos-done"
	eng, tw = _engine(tmp_path, sid, TextModel())
	gstore = GoalStore(str(tmp_path))
	goal = await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)
	_set_todos(tw, ["completed", "completed"])

	events, success = await _submit(eng)
	assert success, "turn 应以 success 收尾"

	cur = gstore.current(sid)
	assert cur is not None
	assert cur.pending_complete is True, "todo 全 done 应置候选"
	assert cur.status == "active", "候选是标志不是状态；不得自动 completed"
	assert cur.rounds == 1, "41 号：人类轮不消耗 cap，rounds 保持初值"


@pytest.mark.asyncio
async def test_success_turn_with_todos_incomplete_stays_active(tmp_path: Path) -> None:
	sid = "sess-todos-incomplete"
	eng, tw = _engine(tmp_path, sid, TextModel())
	gstore = GoalStore(str(tmp_path))
	await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)
	_set_todos(tw, ["completed", "in_progress"])

	_, success = await _submit(eng)
	assert success

	cur = gstore.current(sid)
	assert cur is not None
	assert cur.pending_complete is False, "非全 done 不置候选"
	assert cur.revision == 1, "候选无变化 → 不写盘、不 bump revision（GUI ref 稳定）"


@pytest.mark.asyncio
async def test_hook_human_turns_never_advance_rounds(tmp_path: Path) -> None:
	"""41 号：rounds 只由 driver admit 推进——人类成功轮多次也不 +1。"""
	sid = "sess-rounds"
	eng, tw = _engine(tmp_path, sid, TextModel())
	gstore = GoalStore(str(tmp_path))
	await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)
	_set_todos(tw, ["pending"])

	for _ in range(3):
		await _submit(eng)

	cur = gstore.current(sid)
	assert cur is not None
	assert cur.rounds == 1, "3 次人类成功 submit → rounds 不变"


@pytest.mark.asyncio
async def test_hook_noop_when_no_goal_bound(tmp_path: Path) -> None:
	sid = "sess-no-goal"
	eng, tw = _engine(tmp_path, sid, TextModel())
	_set_todos(tw, ["completed"])

	events, success = await _submit(eng)
	assert success
	# 无绑定 goal → 不抛、不改任何状态。
	gstore = GoalStore(str(tmp_path))
	assert gstore.current(sid) is None


@pytest.mark.asyncio
async def test_hook_noop_on_non_success_turn(tmp_path: Path) -> None:
	sid = "sess-empty-text"
	eng, _tw = _engine(tmp_path, sid, EmptyTextModel())
	gstore = GoalStore(str(tmp_path))
	goal = await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)

	await _submit(eng)
	cur = gstore.current(sid)
	assert cur is not None
	assert cur.pending_complete is False, "非成功 turn 不置候选"
	assert cur.rounds == 1, "非成功 turn 不推进轮次"
	assert cur.revision == goal.revision, "非成功 turn 不改写 goal"


@pytest.mark.asyncio
async def test_admit_round_cap_soft_locks_candidate_at_cap(tmp_path: Path) -> None:
	"""41 号 admit_round：CAS 推进轮次；超 cap 软置候选（不硬停/自动完成）。"""
	sid = "sess-cap"
	gstore = GoalStore(str(tmp_path))
	goal = await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)
	cap = 4

	# 准入到 cap 内（rounds 1 → 4，pending 仍 False）。
	g = goal
	for _ in range(cap - 1):
		g = await gstore.admit_round_async(
			g.goal_id, revision=g.revision, cap=cap
		)
	assert g.rounds == cap
	assert g.pending_complete is False
	assert g.status == "active"

	# 第 cap+1 次准入 → rounds 超限 → 软置候选（仍 active，等用户确认）。
	g = await gstore.admit_round_async(g.goal_id, revision=g.revision, cap=cap)
	assert g.rounds == cap + 1
	assert g.pending_complete is True
	assert g.status == "active"


@pytest.mark.asyncio
async def test_admit_round_cas_miss_does_not_consume(tmp_path: Path) -> None:
	sid = "sess-cas"
	gstore = GoalStore(str(tmp_path))
	goal = await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)
	with pytest.raises(GoalConflict):
		await gstore.admit_round_async(
			goal.goal_id, revision=goal.revision + 5, cap=GOAL_ROUND_CAP
		)
	cur = gstore.load(goal.goal_id)
	assert cur is not None
	assert cur.rounds == 1, "CAS miss：预约作废，轮号不消耗"


@pytest.mark.asyncio
async def test_admit_round_noop_on_terminal_goal(tmp_path: Path) -> None:
	sid = "sess-terminal"
	gstore = GoalStore(str(tmp_path))
	goal = await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)
	await gstore.transition_async(goal.goal_id, "completed", revision=goal.revision)
	g = await gstore.admit_round_async(
		goal.goal_id, revision=gstore.load(goal.goal_id).revision, cap=GOAL_ROUND_CAP
	)
	assert g.status == "completed"
	assert g.rounds == 1, "终态不再计轮"


@pytest.mark.asyncio
async def test_create_and_bind_async_persists_and_binds(tmp_path: Path) -> None:
	sid = "sess-async-bind"
	gstore = GoalStore(str(tmp_path))
	goal = await gstore.create_and_bind_async(
		title="goal", text="goal text", origin="submit", session_id=sid
	)
	# 落盘 + 绑定可从一个新的 store 实例读到（重启可查）。
	gstore2 = GoalStore(str(tmp_path))
	cur = gstore2.current(sid)
	assert cur is not None
	assert cur.goal_id == goal.goal_id
	assert cur.title == "goal"
	assert cur.rounds == 1


def test_derive_candidate_helper_still_consistent() -> None:
	assert derive_candidate(turn_succeeded=True, todos_all_done=True) == "todos_all_done"
	assert candidate_is_pending(derive_candidate(turn_succeeded=True, todos_all_done=True)) is True
	assert candidate_is_pending(derive_candidate(turn_succeeded=True, todos_all_done=False)) is False
