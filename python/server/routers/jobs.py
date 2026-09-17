"""Jobs 域路由（42 号 P0）：会话后台任务只读快照（GUI 播种 / 轻量轮询）。

42 号 §8 的现实化：SSE ``jobs`` 帧只在 turn 流存活时可发；owner turn 结束后的
结算变化靠本端点轮询补齐（与 41 号 GoalDock 同款取舍）。UI 零 RPC——列表行
不做流直读、不做人类中断（冻结口径 6）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from server.local_gate import require_loopback
from server.deps import api_error

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_loopback)])


@router.get("/v1/sessions/{session_id}/jobs")
def list_jobs(session_id: str) -> dict[str, Any]:
	"""owner 快照：活跃行在前（startedAt 升序），终态行在后（finishedAt 降序）。

	无任何任务返回空列表（GUI 据此隐藏角标）。附加 ``wake_budget_left`` 供
	GUI 展示唤醒余量（可选字段，GUI 不消费也不报错）。
	"""
	try:
		from server.job_registry import get_job_registry

		reg = get_job_registry()
		return {
			"jobs": reg.snapshot_list(session_id),
			"version": reg.version(),
			"wake_budget_left": reg.wake_budget_left(session_id),
		}
	except Exception:  # noqa: BLE001 — 降级为空集
		return {"jobs": [], "version": 0, "wake_budget_left": 0}


@router.get("/v1/sessions/{session_id}/jobs/{job_id}/output")
def job_output_peek(session_id: str, job_id: str) -> dict[str, Any]:
	"""GUI 只读窥视单个任务的终端输出（ring 全量 + 截断标志）。

	与模型侧 ``job_output``（单游标增量消费 + reported 置位）严格分离：
	本端点不消费游标、不影响通知管线，可重复轮询。未知/越权 → 404。
	"""
	from server.job_registry import get_job_registry

	sid = (session_id or "").strip()
	jid = (job_id or "").strip()
	if not sid or not jid:
		raise api_error(400, "session_id and job_id required", "invalid_request")
	peek = get_job_registry().peek_output(jid, sid)
	if peek is None:
		raise api_error(404, "job not found", "job_not_found")
	return peek
