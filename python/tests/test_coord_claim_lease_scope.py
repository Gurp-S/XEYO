"""认领失败时不许把同 worker 其他在途任务的写域一起放开。

现场（读码 + 实测 2026-10-03）：
- `coord/store.acquire_scope` 对**同 owner** 是"续约合并"语义：新路径并进现有租约，
  且返回的是**首条同 owner 租约的对象**（`replace(l, paths=…)` ⇒ lease_id 沿用旧的）；
  它的兄弟函数 `release_scope_paths` 的 docstring 自己写明了理由：
  「同 owner 的多任务租约会合并成一条……因此释放必须按路径粒度，而不是整条租约
  ——否则误放同 worker 其他在途任务的 scope」。
- 但 `Planner.claim_next` / `Planner.claim_specific` 在"这个候选被别人抢走"的分支上
  用的正是整条释放 `release_scope(root, lease.lease_id, worker_id)`。

后果（本门两条断言）：worker 认领失败一次，就把它**正在做的其他任务**的写域保护
全部撤掉；别的 worker 于是能认领相交任务 ⇒ 两个进程同时写同一批文件（后写覆盖前写，
且 write_store 的 stale 判定也失去"谁在写"的依据）。TTL 是 10 分钟，兜不住这种主动释放。
"""

from __future__ import annotations

import pytest

from coord.file_store import CoordFileStore
from coord.planner import Planner


@pytest.fixture
def env(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	store = CoordFileStore(ws)
	return ws, store, Planner(ws, store), str(ws)


def _paths_of(store, root, owner: str) -> set[str]:
	got: set[str] = set()
	for lease in store.active_leases(root):
		if lease.owner == owner:
			got.update(lease.paths)
	return got


def test_lost_claim_must_not_release_other_tasks_scope(env) -> None:
	ws, store, planner, root = env
	planner.plan_round([
		{"title": "A", "scope": ["src/a.py"]},
		{"title": "B", "scope": ["src/b.py"]},
	])

	# w1 正常认领 A（此后它持有覆盖 src/a.py 的租约，并正在做 A）
	t1 = planner.claim_next(root=root, worker_id="w1", base_commit="b0")
	assert t1 is not None and t1.title == "A"
	assert "src/a.py" in _paths_of(store, root, "w1")

	# 竞态：下一次认领时该任务被别的 worker 抢走（claim_task 返回 None）。
	# 这是这条分支存在的唯一理由，不是伪造——真实窗口就是"租约拿到了、认领输了"。
	real = store.claim_task
	calls = {"n": 0}

	def lose_race(task_id, worker_id, base_commit=""):
		calls["n"] += 1
		return None

	monkeyclaim = real  # 保留引用，避免别的用例受影响
	store.claim_task = lose_race  # type: ignore[method-assign]
	try:
		assert planner.claim_next(root=root, worker_id="w1", base_commit="b0") is None
		assert calls["n"] >= 1, "没走到认领失败分支 ⇒ 这条门测不到东西"
	finally:
		store.claim_task = monkeyclaim  # type: ignore[method-assign]

	# 关键：输了竞态只该放开 B 的 scope，w1 仍在做 A ⇒ src/a.py 必须还在保护里
	assert "src/a.py" in _paths_of(store, root, "w1"), (
		f"认领失败一次就撤掉了 w1 全部在途写域：{_paths_of(store, root, 'w1')}"
	)
	assert "src/b.py" not in _paths_of(store, root, "w1"), "输掉的候选自己的 scope 应被放开"


@pytest.mark.xfail(
	strict=True,
	reason=(
		"已登记的设计限制（2026-10-03，待拍）：本次把整条释放改成按候选路径释放以后，"
		"同 worker 的两个任务若 scope **重叠**（planner 不禁止：同 owner 之间不算冲突），"
		"输掉其中一个仍会把另一个在途任务共用的路径一并放开。彻底修需要"
		"**按任务引用计数**的租约（每条路径记 owner+task_id 的持有集合），那是机制改动。"
		"⇒ 修好引用计数后这条会 XPASS 报红，逼着摘掉本标记。"
	),
)
def test_overlapping_task_cannot_be_claimed_while_other_worker_is_working(env) -> None:
	"""上一后果的可执行版本：w1 还在做 A 时，w2 不得认领相交 scope 的新任务。"""
	ws, store, planner, root = env
	planner.plan_round([{"title": "A", "scope": ["src/a.py"]}])
	assert planner.claim_next(root=root, worker_id="w1", base_commit="b0") is not None

	# 让 w1 再输一次竞态（没有任何可认领任务时不会触发释放，这里用一个相交的新任务）
	planner.plan_round([{"title": "D", "scope": ["src/a.py"]}])
	real = store.claim_task
	store.claim_task = lambda *a, **k: None  # type: ignore[assignment]
	try:
		planner.claim_next(root=root, worker_id="w1", base_commit="b0")
	finally:
		store.claim_task = real  # type: ignore[method-assign]

	# D 仍是 pending：如果 w1 的保护被整体撤掉，w2 就能认领与 A 相交的 D
	t2 = planner.claim_next(root=root, worker_id="w2", base_commit="b0")
	assert t2 is None, "w1 正在做 src/a.py，w2 却认领到了同一 scope 的任务（并行写同一批文件）"
