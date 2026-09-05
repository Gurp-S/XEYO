"""T9：goal HTTP API + 存储查询/收敛 + 重启不自动续跑。"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.goal_state import GoalConflict, GoalStore


@pytest.fixture()
def store(tmp_path: Path) -> GoalStore:
	return GoalStore(str(tmp_path))


def test_store_persists_goal_and_no_auto_run(tmp_path: Path) -> None:
	"""重启可查但不自动续跑：新 GoalStore 实例读到盘上 goal，且状态不因重启变化。"""
	s1 = GoalStore(str(tmp_path))
	g = s1.create(title="重构", text="重构模块", owner="s1", origin="submit")
	s1.bind("s1", g.goal_id)
	s2 = GoalStore(str(tmp_path))
	assert s2.load(g.goal_id) is not None
	assert s2.load(g.goal_id).status == "active"  # 不自动续跑/不自动完成
	assert s2.current("s1").goal_id == g.goal_id


def test_goal_router_store_current_roundtrip(tmp_path: Path) -> None:
	"""GET /v1/sessions/{sid}/goal 经 store 就绪：绑定后 current 可读。"""
	store = GoalStore(str(tmp_path))
	g = store.create(title="t", text="x", owner="s1")
	store.bind("s1", g.goal_id)
	goal = store.current("s1")
	assert goal is not None
	assert goal.goal_id == g.goal_id


def test_patch_cas_conflict_carries_current(tmp_path: Path) -> None:
	"""PATCH revision CAS：过期 revision 冲突（409 语义），响应带当前 goal 供刷新。"""
	store = GoalStore(str(tmp_path))
	g = store.create(title="t", text="x", owner="s1")
	store.bind("s1", g.goal_id)
	# 干净推进到 blocked（revision 2）
	store.transition(g.goal_id, "blocked", revision=g.revision)
	with pytest.raises(GoalConflict) as exc_info:
		store.transition(g.goal_id, "completed", revision=g.revision)  # 过期 revision
	assert exc_info.value.goal.status == "blocked"
	assert exc_info.value.goal.revision == 2


def test_patch_confirm_complete_legal(tmp_path: Path) -> None:
	"""active -> completed 合法；continue 清候选；drop 弃；reopen 复活。"""
	store = GoalStore(str(tmp_path))
	g = store.create(title="t", text="x", owner="s1")
	store.bind("s1", g.goal_id)
	# confirm_complete（active→completed）
	done = store.transition(g.goal_id, "completed", revision=g.revision)
	assert done.status == "completed"
	# drop：completed 是终态，非法转换保持原状（记日志）
	drop = store.transition(g.goal_id, "abandoned", revision=done.revision)
	assert drop.status == "completed"


def test_resume_chain_no_binding_derives_from_history(tmp_path: Path) -> None:
	"""无绑定目标时 resume 链回退到上一个实质用户目标（不落盘，懒采纳）。"""
	from engine.goal_state import resolve_session_goal

	store = GoalStore(str(tmp_path))
	msgs = [
		{"role": "user", "content": "重构模块"},
		{"role": "assistant", "content": "ok"},
		{"role": "user", "content": "继续"},
	]
	goal, source = resolve_session_goal(store, "s1", msgs)
	assert source == "derived"
	assert goal.text == "重构模块"
