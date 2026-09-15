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
def manual_compact(body: CompactBody) -> dict[str, Any]:
	"""手动 /compact：强制 C2 投影游标前进；不改 JSONL。"""
	from memory.runtime import force_compact
	from memory.working import flush

	engine = _pool.get_if_present(body.session_id)
	if engine is None:
		raise HTTPException(status_code=404, detail="session not found")
	session = engine._session  # noqa: SLF001
	msgs = session.messages.as_api_messages()
	if len(msgs) < 4:
		return {
			"ok": False,
			"reason": "too_short",
			"compact_cursor": session.working.compact_cursor,
		}
	before = int(session.working.compact_cursor or 0)
	force_compact(msgs, session.working)
	flush(session.session_id, session.working)
	after = int(session.working.compact_cursor or 0)
	preview = (session.working.c2_summary_text or "")[:240]
	return {
		"ok": True,
		"compact_cursor": after,
		"advanced": after > before,
		"c2_summary_chars": len(session.working.c2_summary_text or ""),
		"c2_summary_preview": preview,
		"last_action": session.working.last_action,
	}
