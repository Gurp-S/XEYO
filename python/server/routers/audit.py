"""审计查询域：GET /v1/audit/events。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from audit.log import default_audit_log
from engine.trace_graph import TraceGraph
from server.deps import api_error
from server.routers.sessions import require_session_id

router = APIRouter(tags=["audit"])


def _session_key(value: str | None) -> str | None:
	"""给了 session_id 就必须是真的。

	``AuditLog.query`` 把值 strip 后为空当作"不过滤"，所以一个空格就能把
	"这个会话的证据"变成整库导出——而 /v1/audit/trace 还会把未 strip 的原值
	再传给 TraceGraph 比对，两份口径不一致时结果是空快照。
	"""
	if value is None:
		return None
	return require_session_id(value)


def _kind_key(value: str | None) -> str | None:
	if value is None:
		return None
	if not value.strip():
		raise api_error(422, "kind is blank", "invalid_request")
	return value.strip()


@router.get("/v1/audit/events")
def list_audit_events(
	session_id: str | None = Query(default=None),
	kind: str | None = Query(
		default=None,
		description="精确 kind，或以 '.' 结尾的前缀（如 permission.）",
	),
	since_ts: float | None = Query(default=None, ge=0),
	until_ts: float | None = Query(default=None, ge=0),
	limit: int = Query(default=100, ge=1, le=1000),
	offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
	"""读取 append-only 审计 JSONL（新→旧）。β3 身份落地后再加 scope 鉴权。"""
	sid = _session_key(session_id)
	kind_clean = _kind_key(kind)
	events = default_audit_log().query(
		session_id=sid,
		kind=kind_clean,
		since_ts=since_ts,
		until_ts=until_ts,
		limit=limit,
		offset=offset,
	)
	return {
		"events": events,
		"count": len(events),
		"limit": limit,
		"offset": offset,
		# 作用域要能被调用方读出来：省略 session_id 与"按会话查"是两回事。
		"scope": "session" if sid else "all_sessions",
		"session_id": sid or "",
	}


@router.get("/v1/audit/trace")
def get_audit_trace(
	session_id: str = Query(..., min_length=1),
	since_ts: float | None = Query(default=None, ge=0),
	until_ts: float | None = Query(default=None, ge=0),
	limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
	"""返回指定 session 的脱敏运行证据链。"""
	sid = require_session_id(session_id)
	rows = default_audit_log().query(
		session_id=sid,
		since_ts=since_ts,
		until_ts=until_ts,
		limit=limit,
	)
	return TraceGraph.from_audit_rows(
		rows,
		session_id=sid,
		max_events=limit,
	).snapshot()
