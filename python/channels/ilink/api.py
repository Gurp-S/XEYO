"""ClawBot / iLink FastAPI 路由。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from channels import api as remote_api
from channels.ilink import broadcast as il_broadcast
from channels.ilink.service import get_bridge, start, status_payload, stop
from model.openai_compat import PROVIDER_PRESETS
from server.local_gate import loopback_or_remote_token
from server.session_pool import ModelConfig

# T33：本机放行；LAN 直连须携带 XEYO_REMOTE_TOKEN。
router = APIRouter(tags=["ilink"], dependencies=[Depends(loopback_or_remote_token)])


class ILinkStartBody(BaseModel):
	api_key: str | None = None
	provider: str | None = None
	model: str | None = None
	base_url: str | None = None


def _model_cfg_from_body(body: ILinkStartBody | None) -> ModelConfig | None:
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


@router.get("/v1/ilink/status")
async def ilink_status(
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


@router.get("/v1/ilink/events")
async def ilink_events() -> StreamingResponse:
	async def event_stream():
		q = await il_broadcast.subscribe()
		try:
			yield il_broadcast.format_sse(
				"state",
				status_payload(remote_api.get_store(), omit_jobs=True),
			)
			while True:
				try:
					item = await asyncio.wait_for(q.get(), timeout=30.0)
				except asyncio.TimeoutError:
					yield ": ping\n\n"
					continue
				if item is None:
					break
				event, data = item
				yield il_broadcast.format_sse(event, data)
		finally:
			await il_broadcast.unsubscribe(q)

	return StreamingResponse(
		event_stream(),
		media_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
		},
	)


@router.get("/v1/ilink/qr.png")
async def ilink_qr():
	b = get_bridge()
	blob = b.qr_png()
	if not blob:
		raise HTTPException(404, "qr not available")
	return Response(
		content=blob,
		media_type=b.qr_mime(),
		headers={"Cache-Control": "no-store"},
	)


@router.post("/v1/ilink/start")
async def ilink_start(body: ILinkStartBody | None = None) -> dict[str, object]:
	runner = remote_api.get_runner()
	if runner is None:
		raise HTTPException(503, "remote runner not initialized")
	try:
		await start(runner, remote_api.get_store(), model_cfg=_model_cfg_from_body(body))
	except RuntimeError as e:
		raise HTTPException(503, str(e)) from e
	return status_payload(remote_api.get_store())


@router.post("/v1/ilink/stop")
async def ilink_stop() -> dict[str, object]:
	await stop(remote_api.get_runner())
	return status_payload(remote_api.get_store())
