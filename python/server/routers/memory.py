"""Memory plane HTTP：列表 / 手动 compact。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from server.deps import _pool

router = APIRouter(tags=["memory"])


class CompactBody(BaseModel):
	session_id: str = Field(min_length=1)


def _cwd() -> str:
	return str(getattr(_pool, "cwd", "") or ".")


@router.get("/v1/memory/notes")
def list_notes(
	scope: str = Query(default=""),
	limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
	"""侧栏：列出 active 笔记（工作区 + user）。"""
	from memory.memdir import load_notes_for_search, workspace_id

	wsid = workspace_id(_cwd())
	notes = [
		n
		for n in load_notes_for_search(wsid, scope=scope or "")
		if n.status == "active"
	]
	notes.sort(
		key=lambda n: (n.last_used_at or n.updated_at or n.created_at or "", n.confidence),
		reverse=True,
	)
	rows = []
	for n in notes[:limit]:
		rows.append(
			{
				"id": n.id,
				"type": n.type,
				"scope": n.scope,
				"title": n.title,
				"content": n.content[:500],
				"confidence": n.confidence,
				"last_used_at": n.last_used_at,
				"updated_at": n.updated_at,
			}
		)
	return {"workspace_id": wsid, "notes": rows}


@router.post("/v1/memory/compact")
async def manual_compact(body: CompactBody) -> dict[str, Any]:
	"""手动压缩：追加可核验交接后推进投影，既有原文不改。"""
	from engine.manual_compaction import compact
	from engine.turn_runner import get_turn_runner
	from server.session_operation import keep_lease

	engine = _pool.get_if_present(body.session_id)
	if engine is None:
		raise HTTPException(status_code=404, detail="session not found")
	if get_turn_runner().is_running(body.session_id):
		raise HTTPException(status_code=409, detail="session busy")
	lease_id = _pool.try_begin(body.session_id)
	if lease_id is None:
		raise HTTPException(status_code=409, detail="session busy")
	try:
		# Resolve the engine after acquiring ownership: an idle engine can
		# have been replaced/evicted since the initial existence check.
		engine = _pool.get_if_present(body.session_id)
		if engine is None:
			raise HTTPException(status_code=404, detail="session not found")
		compact_cwd = getattr(_pool, "session_cwd", lambda sid: None)(body.session_id) or _cwd()
		async with keep_lease(_pool, body.session_id, lease_id) as guard:
			return await compact(engine, cwd=compact_cwd, guard=guard,
				pending_stop=lambda: _pool.take_pending_interrupt(body.session_id))
	finally:
		_pool.end(body.session_id, lease_id)
