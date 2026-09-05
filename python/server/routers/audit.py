"""审计查询域：GET /v1/audit/events。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from audit.log import default_audit_log

router = APIRouter(tags=["audit"])


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
	events = default_audit_log().query(
		session_id=session_id,
		kind=kind,
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
	}
