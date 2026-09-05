"""微信文件传输助手 FastAPI 路由。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from channels import api as remote_api
from channels.filehelper import broadcast as fh_broadcast
from channels.filehelper.service import get_bridge, start, status_payload, stop
from model.openai_compat import PROVIDER_PRESETS
from server.local_gate import loopback_or_remote_token
from server.session_pool import ModelConfig

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "server" / "static" / "filehelper"

# T33：本机放行；LAN 直连须携带 XEYO_REMOTE_TOKEN。
router = APIRouter(tags=["filehelper"], dependencies=[Depends(loopback_or_remote_token)])


class FileHelperStartBody(BaseModel):
	api_key: str | None = None
	provider: str | None = None
	model: str | None = None
	base_url: str | None = None


def _model_cfg_from_body(body: FileHelperStartBody | None) -> ModelConfig | None:
	if body is None:
		return None
	# 仅本地 provider 允许缺 Key；其余 provider 必须提供 key。
	if not (body.api_key or "").strip() and (body.provider or "deepseek").strip().lower() != "local":
		return None
	provider = (body.provider or "deepseek").strip().lower()
	if provider not in PROVIDER_PRESETS:
		raise HTTPException(400, f"unsupported provider: {provider}")
	base = (body.base_url or "").strip() or PROVIDER_PRESETS[provider]["base_url"]
	model = (body.model or "").strip() or "deepseek-chat"
	return ModelConfig(
		provider=provider,
		# 本地 provider 使用占位 Key。
		api_key=(body.api_key or "").strip() or "local",
		base_url=base.rstrip("/"),
		model=model,
	)


@router.get("/v1/filehelper/status")
async def filehelper_status(
	after: str = Query(default=""),
	omit_jobs: str = Query(default=""),
	stream_from: int | None = Query(default=None),
) -> dict[str, object]:
	return status_payload(
		remote_api.get_store(),
		after_id=after,
		omit_jobs=omit_jobs.strip() in {"1", "true", "yes"},
		stream_from=stream_from,
	)


@router.get("/v1/filehelper/events")
async def filehelper_events() -> StreamingResponse:
	async def event_stream():
		q = await fh_broadcast.subscribe()
		try:
			yield fh_broadcast.format_sse("state", status_payload(remote_api.get_store(), omit_jobs=True))
			while True:
				try:
					item = await asyncio.wait_for(q.get(), timeout=30.0)
				except asyncio.TimeoutError:
					yield ": ping\n\n"
					continue
				if item is None:
					break
				event, data = item
				yield fh_broadcast.format_sse(event, data)
		finally:
			await fh_broadcast.unsubscribe(q)

	return StreamingResponse(
		event_stream(),
		media_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
		},
	)


@router.get("/v1/filehelper/qr.png")
async def filehelper_qr():
	png = get_bridge().qr_png()
	if not png:
		raise HTTPException(404, "qr not available")
	return Response(
		content=png,
		media_type="image/png",
		headers={"Cache-Control": "no-store"},
	)


@router.post("/v1/filehelper/start")
async def filehelper_start(body: FileHelperStartBody | None = None) -> dict[str, object]:
	runner = remote_api.get_runner()
	if runner is None:
		raise HTTPException(503, "remote runner not initialized")
	try:
		await start(runner, remote_api.get_store(), model_cfg=_model_cfg_from_body(body))
	except RuntimeError as e:
		raise HTTPException(503, str(e)) from e
	return status_payload(remote_api.get_store())


@router.post("/v1/filehelper/stop")
async def filehelper_stop() -> dict[str, object]:
	await stop(remote_api.get_runner())
	return status_payload(remote_api.get_store())


@router.get("/filehelper/")
@router.get("/filehelper")
async def filehelper_page():
	index = STATIC_DIR / "index.html"
	if not index.is_file():
		raise HTTPException(404, "filehelper UI not found")
	return FileResponse(index)
