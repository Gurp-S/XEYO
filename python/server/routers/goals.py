"""Goal 域路由（T9/41 号）：会话目标可查 / 可收敛 / 可 armed 续跑。

41 号新增：GET 附 driver 投影、PATCH action=edit、POST round-driver（arm/disarm）。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.goal_state import (
	CANDIDATE_ACTIVE,
	GoalConflict,
	GoalStore,
	STATUS_ABANDONED,
	STATUS_ACTIVE,
	STATUS_COMPLETED,
	STATUS_PAUSED,
	candidate_is_pending,
)
from server.deps import _pool
from server.local_gate import require_loopback

# T33：goal 面（含 PATCH 删除/收敛）仅 loopback。
router = APIRouter(tags=["goal"], dependencies=[Depends(require_loopback)])


def _store_for(session_id: str) -> GoalStore:
	cwd = _pool.session_cwd(session_id) or _pool.cwd
	return GoalStore(cwd)


def _current_or_empty(session_id: str) -> dict[str, Any]:
	store = _store_for(session_id)
	goal = store.current(session_id)
	if goal is None:
		return {}
	return goal.to_dict()


@router.get("/v1/sessions/{session_id}/goal")
def get_goal(session_id: str) -> dict[str, Any]:
	"""T9/41 号：当前会话绑定的目标（未绑定返回 {}，不报错）。

	bound 时 additive 附 ``driver`` 投影（armed 态——41 号 §9.4，XEYO 有意比
	默认实现多暴露；无 driver 记录时默认 disarmed）。
	"""
	goal = _current_or_empty(session_id)
	if goal:
		try:
			from server.goal_round_driver import get_goal_round_driver

			goal = {
				**goal,
				"driver": get_goal_round_driver().snapshot(session_id)
				or {
					"activation": "disarmed",
					"pending": False,
					"active_round": None,
				},
			}
		except Exception:  # noqa: BLE001
			pass
	return goal


class GoalPatch(BaseModel):
	action: Literal[
		"confirm_complete", "continue", "drop", "reopen", "new", "edit",
		"pause", "resume",
	]
	#: PATCH revision CAS：miss 时返回 409 附当前 goal（客户端重读再提交，禁盲写）。
	revision: int | None = Field(default=None, ge=1)
	#: action=new / edit 时的目标标题/正文；其它 action 忽略。
	title: str | None = Field(default=None, max_length=200)
	text: str | None = Field(default=None, max_length=4000)
	#: action=edit 时的 per-goal 轮次上限（0 = 回落全局默认）；其它 action 忽略。
	max_rounds: int | None = Field(default=None, ge=0)


@router.patch("/v1/sessions/{session_id}/goal")
async def patch_goal(session_id: str, body: GoalPatch) -> dict[str, Any]:
	"""T9/41 号：对会话绑定目标施加动作。

	- confirm_complete：置 completed（带 revision CAS）。
	- continue：取消候选（pending_complete=False，保持 active）。
	- drop：置 abandoned。
	- reopen：置 active + 清候选（blocked_reason 一并清空）。
	- new：新建目标并重绑（忽略旧 revision）。
	- edit：编辑 title / text / max_rounds（edit 动词，CAS）。

	2026-09-05：改 async def（sync def 跑线程池，GoalStore 同步 API 的 ``_run``
	会各起一个事件循环且 driver ``poke`` 拿不到 loop）——统一走 ``*_async`` 存储层；
	恢复 active 的动作（continue/reopen/resume）后若 driver 已 armed 则补一次预约。
	"""
	from server.goal_round_driver import get_goal_round_driver

	store = _store_for(session_id)
	cur = store.current(session_id)
	if body.action == "new":
		if not (body.text or "").strip():
			raise HTTPException(400, "action=new requires text")
		goal = await store.create_and_bind_async(
			title=(body.title or (body.text or "")[:48]),
			text=body.text or "",
			session_id=session_id,
			owner=session_id,
			origin="api",
		)
		return goal.to_dict()

	if cur is None:
		raise HTTPException(404, "no goal bound to this session")
	back_to_active = False
	try:
		if body.action == "confirm_complete":
			goal = await store.transition_async(
				cur.goal_id, STATUS_COMPLETED, revision=body.revision
			)
		elif body.action == "continue":
			goal = await store.transition_async(
				cur.goal_id,
				STATUS_ACTIVE,
				revision=body.revision,
				set_pending_complete=False,
			)
			back_to_active = True
		elif body.action == "drop":
			goal = await store.transition_async(
				cur.goal_id, STATUS_ABANDONED, revision=body.revision
			)
		elif body.action == "reopen":
			goal = await store.transition_async(
				cur.goal_id,
				STATUS_ACTIVE,
				revision=body.revision,
				set_pending_complete=False,
			)
			back_to_active = True
		elif body.action == "pause":
			goal = await store.transition_async(
				cur.goal_id, STATUS_PAUSED, revision=body.revision
			)
		elif body.action == "resume":
			goal = await store.transition_async(
				cur.goal_id,
				STATUS_ACTIVE,
				revision=body.revision,
				set_pending_complete=False,
			)
			back_to_active = True
		elif body.action == "edit":
			goal = await store.update_async(
				cur.goal_id,
				revision=body.revision,
				title=body.title,
				text=body.text,
				max_rounds=body.max_rounds,
			)
		else:  # pragma: no cover
			raise HTTPException(400, f"unsupported action: {body.action}")
	except GoalConflict as exc:
		# 带当前 goal 供客户端刷新再提交。
		return _conflict_response(exc.goal)
	if back_to_active:
		# 2026-09-05 补接线：armed 的 driver 在 goal 回到 active 后能立即续跑，
		# 不必等下一次 turn settlement。无事件循环（不该发生，async 端点）时静默。
		try:
			get_goal_round_driver().poke(session_id)
		except Exception:  # noqa: BLE001
			pass
	return goal.to_dict()


class RoundDriverAction(BaseModel):
	"""41 号 round-driver 控制面（arm/disarm；内存态，不落盘）。"""

	action: Literal["arm", "disarm"]
	#: arm 时可选覆写 per-goal 轮次上限（先 CAS edit 再 armed；0 = 回落全局默认）。
	max_rounds: int | None = Field(default=None, ge=0)


@router.post("/v1/sessions/{session_id}/goal/round-driver")
async def post_goal_round_driver(
	session_id: str, body: RoundDriverAction
) -> dict[str, Any]:
	"""41 号：armed 显式开关（冻结口径 2：绝不随 goal 创建自动 armed）。

	- arm：须绑定 active goal（404/409）；可选 max_rounds 先 CAS edit；空闲则
	  立即预约下一轮（预约不消耗轮号）。
	- disarm：清内存 armed + 作废在途预约；不杀轮中 turn、不改 goal 落盘状态。
	响应：``{goal, driver}``（whole-value 快照，GUI 据此整卡刷新）。
	"""
	from server.goal_round_driver import get_goal_round_driver

	driver = get_goal_round_driver()
	store = _store_for(session_id)
	if body.action == "arm":
		cur = store.current(session_id)
		if cur is None:
			raise HTTPException(404, "no goal bound to this session")
		if cur.status != STATUS_ACTIVE:
			raise HTTPException(
				409, f"goal is {cur.status}; only active goals can be armed"
			)
		if body.max_rounds is not None:
			try:
				await store.update_async(
					cur.goal_id, revision=cur.revision, max_rounds=body.max_rounds
				)
			except GoalConflict as exc:
				return _conflict_response(exc.goal)
		snap = driver.arm(session_id)
	else:
		snap = driver.disarm(session_id)
	goal = store.current(session_id)
	return {
		"goal": goal.to_dict() if goal is not None else {},
		"driver": snap,
	}


def _conflict_response(goal) -> dict[str, Any]:
	"""构造 409 goal_revision_conflict 响应（附当前 goal）。"""
	result = {
		"error": "goal_revision_conflict",
		"goal": goal.to_dict(),
	}
	raise HTTPException(409, detail=result)
