"""Jobs 域路由（42 号 P0）：会话后台任务快照（GUI 播种 / 轻量轮询）+ 人类停止（F1）。

42 号 §8 的现实化：SSE ``jobs`` 帧只在 turn 流存活时可发；owner turn 结束后的
结算变化靠本端点轮询补齐（与 41 号 GoalDock 同款取舍）。**10-07 更新**：原
「不做人类中断（冻结口径 6）」已由 F1 落地作废——模型有 ``job_kill``、人类
现在也有 ``POST …/jobs/{job_id}/kill``（同一执行路径：容器优先、registry 回落；
owner=路径会话 id，越权=404 与模型侧同规）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from server.local_gate import require_loopback
from server.deps import api_error
from server.routers.sessions import require_session_id

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_loopback)])


@router.get("/v1/sessions/{session_id}/jobs")
def list_jobs(session_id: str) -> dict[str, Any]:
	"""owner 快照：活跃行在前（startedAt 升序），终态行在后（finishedAt 降序）。

	无任何任务返回空列表（GUI 据此隐藏角标）。附加 ``wake_budget_left`` 供
	GUI 展示唤醒余量（可选字段，GUI 不消费也不报错）。

	会话 id 在边缘按固定点校验：``snapshot_list`` 会对 caller 传入的 id 做
	``strip()``，于是 ``"victim "`` 归一化后命中 ``"victim"`` 的真实任务集——
	一次带尾空白的查询就读走别人的后台任务快照。歧义 id 一律 422。
	"""
	sid = require_session_id(session_id)
	try:
		from server.job_registry import get_job_registry

		reg = get_job_registry()
		return {
			"jobs": reg.snapshot_list(sid),
			"version": reg.version(),
			"wake_budget_left": reg.wake_budget_left(sid),
		}
	except Exception:  # noqa: BLE001 — 降级为空集（422 已在 try 外抛出，不会被吞）
		return {"jobs": [], "version": 0, "wake_budget_left": 0}


@router.get("/v1/sessions/{session_id}/jobs/{job_id}/output")
def job_output_peek(session_id: str, job_id: str) -> dict[str, Any]:
	"""GUI 只读窥视单个任务的终端输出（ring 全量 + 截断标志）。

	与模型侧 ``job_output``（单游标增量消费 + reported 置位）严格分离：
	本端点不消费游标、不影响通知管线，可重复轮询。未知/越权 → 404。

	会话 id 同 ``list_jobs``：``peek_output`` 以 ``strip()`` 后的 id 比对 owner，
	故尾空白会让查询落进他人任务；歧义 id 在边缘 422，绝不静默清洗。
	"""
	from server.job_registry import get_job_registry

	sid = require_session_id(session_id)
	jid = job_id or ""
	if not jid.strip() or jid != jid.strip():
		raise api_error(422, "job_id is blank or has surrounding whitespace", "invalid_request")
	peek = get_job_registry().peek_output(jid, sid)
	if peek is None:
		raise api_error(404, "job not found", "job_not_found")
	return peek


@router.post("/v1/sessions/{session_id}/jobs/{job_id}/kill")
def kill_job(session_id: str, job_id: str) -> dict[str, Any]:
	"""人类侧停止一条后台任务（F1：模型能 kill、人也能 kill，同一执行路径）。

	容器后台优先、registry 回落——与模型侧 ``JobKillTool`` 完全同轨；owner =
	路径里的会话 id（人类即 owner，无会话上下文可借）。越权/未知 → 404（registry
	的 owner 比对返回 unknown，绝不静默命中他人任务）；终态任务原样回报「already」。
	"""
	sid = require_session_id(session_id)
	jid = job_id or ""
	if not jid.strip() or jid != jid.strip():
		raise api_error(
			422, "job_id is blank or has surrounding whitespace", "invalid_request"
		)
	try:
		from tools.bash_tool.bash_tool import cancel_docker_bg, docker_bg_snapshot

		docker_hit = any(j["job_id"] == jid for j in docker_bg_snapshot())
	except Exception:  # noqa: BLE001 — 容器面不可用则回落 registry
		docker_hit = False
	if docker_hit:
		try:
			msg = cancel_docker_bg(jid, "user_stop")
		except Exception as exc:  # noqa: BLE001
			raise api_error(
				500, f"cancel failed: {type(exc).__name__}", "job_cancel_failed"
			) from exc
		if msg is None:
			raise api_error(404, "job not found", "job_not_found")
		return {"ok": True, "job_id": jid, "message": msg}
	from server.job_registry import get_job_registry

	try:
		msg = get_job_registry().kill(jid, sid, "user_stop")
	except Exception as exc:  # noqa: BLE001
		raise api_error(
			500, f"kill failed: {type(exc).__name__}", "job_cancel_failed"
		) from exc
	if msg.startswith("unknown job"):
		raise api_error(404, "job not found", "job_not_found")
	return {"ok": True, "job_id": jid, "message": msg}
