"""远程消息 channel 的 FastAPI 路由。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from channels.auth import remote_enabled, verify_remote_token
from channels.jobs import JobStore
from channels.runner import FinalOnlyRunner, default_remote_session_id

# 限制远程用户文本（与 chat completions 同量级）。
_MAX_REMOTE_CHARS = 100_000

STATIC_REMOTE_DIR = Path(__file__).resolve().parent.parent / "server" / "static" / "remote"

router = APIRouter(tags=["remote"])

_store = JobStore()
_runner: FinalOnlyRunner | None = None


def init_remote(pool) -> None:  # type: ignore[no-untyped-def]
	"""将 SessionPool 接入远程 runner（应用启动时调用一次）。"""
	global _runner
	_runner = FinalOnlyRunner(pool, _store)


def get_runner() -> FinalOnlyRunner | None:
	return _runner


def get_store() -> JobStore:
	return _store


def _require_auth(
	authorization: str | None,
	x_remote_token: str | None,
) -> None:
	try:
		verify_remote_token(authorization, x_remote_token)
	except ValueError as e:
		code = str(e)
		if code == "disabled":
			raise HTTPException(503, "remote channel disabled; set XEYO_REMOTE_TOKEN") from e
		raise HTTPException(401, "invalid or missing remote token") from e


def _get_runner() -> FinalOnlyRunner:
	if _runner is None:
		raise HTTPException(503, "remote channel not initialized")
	return _runner


class RemoteMessageBody(BaseModel):
	text: str
	session_id: str | None = None
	media_refs: list[str] = Field(default_factory=list, max_length=8)


@router.get("/v1/remote/health")
async def remote_health() -> dict[str, object]:
	return {
		"enabled": remote_enabled(),
		"token_configured": remote_enabled(),
		"default_session_id": default_remote_session_id(),
	}


@router.post("/v1/remote/messages", status_code=202)
async def remote_messages(
	body: RemoteMessageBody,
	authorization: str | None = Header(default=None),
	x_remote_token: str | None = Header(default=None, alias="X-Remote-Token"),
):
	_require_auth(authorization, x_remote_token)
	text = (body.text or "").strip()
	if not text:
		raise HTTPException(400, "text is required")
	if len(text) > _MAX_REMOTE_CHARS:
		raise HTTPException(
			413,
			f"text too large ({len(text)} > {_MAX_REMOTE_CHARS} chars)",
		)
	session_id = (body.session_id or "").strip() or default_remote_session_id()
	from media_store import media_exists

	media_refs: list[str] = []
	for ref in body.media_refs:
		value = str(ref or "").strip()
		if value and not media_exists(value):
			raise HTTPException(400, f"media_ref not found: {value}")
		if value:
			media_refs.append(value)
	job_id = _get_runner().enqueue(
		session_id=session_id,
		text=text,
		images=media_refs or None,
	)
	return JSONResponse(
		status_code=202,
		content={
			"job_id": job_id,
			"session_id": session_id,
			"status": "queued",
		},
	)


@router.get("/v1/remote/jobs/{job_id}")
async def remote_job(
	job_id: str,
	authorization: str | None = Header(default=None),
	x_remote_token: str | None = Header(default=None, alias="X-Remote-Token"),
):
	_require_auth(authorization, x_remote_token)
	rec = _store.get(job_id)
	if rec is None:
		raise HTTPException(404, "job not found")
	return rec.to_public()


@router.get("/remote/")
@router.get("/remote")
async def remote_page():
	index = STATIC_REMOTE_DIR / "index.html"
	if not index.is_file():
		raise HTTPException(404, "remote UI not found")
	return FileResponse(index)
