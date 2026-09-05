"""T9：Goal 状态机实体 + 持久化存储 + revision CAS。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from engine.goal_state import (
	STATUS_ACTIVE,
	STATUS_BLOCKED,
	STATUS_COMPLETED,
	STATUS_ABANDONED,
	Goal,
	GoalConflict,
	GoalStore,
	candidate_is_pending,
	derive_candidate,
	resolve_session_goal,
	can_transition,
)


@pytest.fixture()
def store(tmp_path: Path) -> GoalStore:
	return GoalStore(str(tmp_path))


def test_goal_roundtrip(store: GoalStore) -> None:
	g = store.create(title="t", text="do x", owner="s1", origin="user")
	assert g.goal_id
	assert g.status == STATUS_ACTIVE
	assert g.revision == 1
	loaded = store.load(g.goal_id)
	assert loaded is not None
	assert loaded.title == "t"
	assert loaded.text == "do x"
	assert loaded.owner == "s1"
	assert loaded.revision == 1


def test_transition_legal_and_revision_bump(store: GoalStore) -> None:
	g = store.create(title="t", text="x")
	# active -> blocked 合法，revision 增
	b = store.transition(g.goal_id, STATUS_BLOCKED)
	assert b.status == STATUS_BLOCKED
	assert b.revision == g.revision + 1
	# blocked -> active 合法
	a = store.transition(g.goal_id, STATUS_ACTIVE)
	assert a.status == STATUS_ACTIVE
	# completed 终态
	c = store.transition(g.goal_id, STATUS_COMPLETED)
	assert c.status == STATUS_COMPLETED
	# completed -> active 非法：记日志并保持原状
	back = store.transition(g.goal_id, STATUS_ACTIVE)
	assert back.status == STATUS_COMPLETED
	assert back.revision == c.revision


def test_pending_complete_is_flag_not_status(store: GoalStore) -> None:
	g = store.create(title="t", text="x")
	g2 = store.transition(
		g.goal_id, STATUS_ACTIVE, set_pending_complete=True
	)
	assert g2.status == STATUS_ACTIVE
	assert g2.pending_complete is True
	# 取消候选
	g3 = store.transition(g.goal_id, STATUS_ACTIVE, set_pending_complete=False)
	assert g3.pending_complete is False


def test_cas_revision_conflict(store: GoalStore) -> None:
	g = store.create(title="t", text="x")
	# active -> completed 合法（revision 2）；再用过期 revision 1 转换 → CAS 冲突
	ok = store.transition(g.goal_id, STATUS_COMPLETED, revision=g.revision)
	assert ok.status == STATUS_COMPLETED
	assert ok.revision == g.revision + 1
	with pytest.raises(GoalConflict):
		store.transition(g.goal_id, STATUS_ABANDONED, revision=g.revision)


def test_cas_revision_conflict_carry_current(store: GoalStore) -> None:
	g = store.create(title="t", text="x")
	# 另一处已推进到 blocked，revision=2
	store.transition(g.goal_id, STATUS_BLOCKED, revision=g.revision)
	with pytest.raises(GoalConflict) as exc_info:
		# 拿过期 revision 1 去 PATCH（客户端应读 body.current 再重试）
		store.transition(g.goal_id, STATUS_COMPLETED, revision=1)
	assert exc_info.value.goal.status == STATUS_BLOCKED
	assert exc_info.value.goal.revision == 2


def test_bind_current_unbind(store: GoalStore) -> None:
	g = store.create(title="t", text="x")
	store.bind("sess-a", g.goal_id)
	assert store.current("sess-a") is not None
	assert store.current("sess-a").goal_id == g.goal_id
	store.unbind("sess-a")
	assert store.current("sess-a") is None


def test_persist_survives_new_store_instance(tmp_path: Path) -> None:
	"""重启可查：用新的 GoalStore 实例（同路径）能读到盘上 goal（不自动续跑）。"""
	s1 = GoalStore(str(tmp_path))
	g = s1.create(title="t", text="x")
	s1.bind("sess-a", g.goal_id)
	s2 = GoalStore(str(tmp_path))
	loaded = s2.load(g.goal_id)
	assert loaded is not None
	assert loaded.status == STATUS_ACTIVE  # 仍在 active，不会因重启自动 completed
	assert s2.current("sess-a").goal_id == g.goal_id


def test_bad_goal_file_skipped(tmp_path: Path) -> None:
	store = GoalStore(str(tmp_path))
	g = store.create(title="t", text="x")
	# 破坏文件
	path = store._goal_path(g.goal_id)
	path.write_text("{not json", encoding="utf-8")
	assert store.load(g.goal_id) is None
	assert store.list_all() == []


def test_can_transition_table() -> None:
	assert can_transition(STATUS_ACTIVE, STATUS_BLOCKED)
	assert can_transition(STATUS_BLOCKED, STATUS_ACTIVE)
	assert can_transition(STATUS_ACTIVE, STATUS_ABANDONED)
	assert can_transition(STATUS_ABANDONED, STATUS_ACTIVE)
	assert not can_transition(STATUS_COMPLETED, STATUS_ACTIVE)
	assert not can_transition(STATUS_ACTIVE, STATUS_ACTIVE)


def test_derive_candidate_priority() -> None:
	# todos 全 done 优先
	assert derive_candidate(turn_succeeded=True, todos_all_done=True) == "todos_all_done"
	assert derive_candidate(turn_succeeded=True, todos_all_done=True, multi_agent_all_succeeded=True) == "todos_all_done"
	# 多 Agent all_succeeded
	assert derive_candidate(multi_agent_all_succeeded=True) == "batch_awaiting_synthesis"
	# 合成
	assert derive_candidate(synthesis_succeeded=True) == "synthesis_done"
	# 无候选
	assert derive_candidate() == "active"
	assert derive_candidate(turn_succeeded=True) == "active"


def test_candidate_is_pending() -> None:
	assert candidate_is_pending("todos_all_done") is True
	assert candidate_is_pending("batch_awaiting_synthesis") is True
	assert candidate_is_pending("active") is False


def test_resolve_session_goal_bind_priority(tmp_path) -> None:
	"""resume 链：有绑定优先于 derived。"""
	store = GoalStore(str(tmp_path))
	g = store.create(title="t", text="x")
	store.bind("sess-a", g.goal_id)
	msgs = [{"role": "user", "content": "do y"}]
	got, source = resolve_session_goal(store, "sess-a", msgs)
	assert source == "bind"
	assert got.goal_id == g.goal_id


def test_resolve_session_goal_derived_from_previous_user(tmp_path) -> None:
	"""无绑定时回退到上一个实质用户目标（跳过续跑口令）。"""
	store = GoalStore(str(tmp_path))
	msgs = [
		{"role": "user", "content": "重构模块"},
		{"role": "assistant", "content": "ok"},
		{"role": "user", "content": "继续"},
	]
	got, source = resolve_session_goal(store, "sess-a", msgs)
	assert source == "derived"
	assert got.text == "重构模块"


def test_resolve_session_goal_none(tmp_path) -> None:
	store = GoalStore(str(tmp_path))
	got, source = resolve_session_goal(store, "sess-a", [])
	assert source == "none"
	assert got is None


def test_async_transition_works_in_loop(store: GoalStore) -> None:
	"""在运行事件循环中，_xxx_async 可被 await，锁串行化。"""

	async def main() -> None:
		await store._create_async(
			Goal(goal_id="g1", title="t", text="x", revision=1)
		)
		await store._transition_async("g1", STATUS_BLOCKED, None, None)
		assert store.load("g1").status == STATUS_BLOCKED

	asyncio.run(main())


def _has_goal(out: list[dict]) -> bool:
	# 兼容两种声道：legacy=text 块；env_channel（方案A）=伪对 tool_result 正文
	for m in out:
		content = m.get("content")
		if isinstance(content, str):
			if "# Goal（background only）" in content:
				return True
		elif isinstance(content, list):
			for block in content:
				if not isinstance(block, dict):
					continue
				if "# Goal（background only）" in str(block.get("text") or ""):
					return True
				if block.get("type") == "tool_result" and "# Goal（background only）" in str(block.get("content") or ""):
					return True
	return False


def test_goal_block_injected_only_when_nonempty() -> None:
	"""T9：T_now Goal 块（# Goal（background only））仅在非空时注入，子代理不注入。"""
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	msgs = [{"role": "user", "content": "hi"}]
	# 空 goal → 不注入
	out0 = run_pre_llm_inject(
		msgs, InjectContext(working=None, cwd="", goal="", include_memory_index=False)
	)
	assert not _has_goal(out0)
	# 非空 goal → 注入
	block = "# Goal（background only）\n目标：重构模块；状态：已阻塞（依赖未就绪）。"
	out1 = run_pre_llm_inject(
		msgs, InjectContext(working=None, cwd="", goal=block, include_memory_index=False)
	)
	assert _has_goal(out1)
	# 子代理上下文不注入
	out2 = run_pre_llm_inject(
		msgs,
		InjectContext(
			working=None, cwd="", goal=block, subagent=True, include_memory_index=False
		),
	)
	assert not _has_goal(out2)
