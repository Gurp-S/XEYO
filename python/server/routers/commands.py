"""Slash 命令路由：``POST /v1/slash``。

GUI / CLI-TS 通过该端点执行 ``handler=server`` 的斜杠命令；CLI-Py 与远程通道
进程内直接调 :func:`slash.dispatch`，不走 HTTP。

鉴权与 ``/v1/chat/completions`` 同源（Bearer API key + loopback 门禁）。
命令**不通模型、不改 MessageStore / JSONL**；模式/精简/模型/主题/审批等
client 命令由发起面本地处理，本端点直接拒收。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from server.deps import _extract_bearer, _resolve_base_url
from server.local_gate import require_loopback
from slash.dispatch import CommandResult, DispatchContext, dispatch_command
from slash.registry import get_command

router = APIRouter(tags=["slash"])


class SlashRequest(BaseModel):
	name: str = Field(max_length=64)
	arg: str = Field(default="", max_length=4000)
	session_id: str | None = Field(default=None, max_length=128)
	workspace: str | None = Field(default=None, max_length=1024)
	provider: str | None = Field(default=None, max_length=32)
	base_url: str | None = Field(default=None, max_length=512)
	model: str | None = Field(default=None, max_length=128)


@router.post("/v1/slash")
def slash_command(
	body: SlashRequest,
	request: Request,
	authorization: str | None = Header(default=None),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
	require_loopback(request)
	cmd = get_command(body.name)
	if cmd is None:
		result = CommandResult(
			handled=False, kind="unknown", message=f"未知命令 /{body.name}，试试 /help。"
		)
	elif cmd.handler != "server":
		result = CommandResult(
			handled=False,
			kind="unknown",
			message=f"/{cmd.name} 由界面本地处理，不应发送到服务端。",
		)
	else:
		provider = (body.provider or x_provider or "deepseek").lower()
		ctx = DispatchContext(
			session_id=(body.session_id or "").strip(),
			workspace=(body.workspace or "").strip(),
			provider=provider,
			api_key=_extract_bearer(authorization) or "",
			base_url=_resolve_base_url(provider, body.base_url or x_base_url) or "",
			model=(body.model or "").strip(),
		)
		result = dispatch_command(cmd, body.arg, ctx=ctx)
	if result.result is not None and not isinstance(result.result, dict):
		result.result = {"value": result.result}
	return {
		"handled": result.handled,
		"kind": result.kind,
		"message": result.message,
		"result": result.result,
	}


class SlashParseRequest(BaseModel):
	text: str = Field(default="", max_length=100_000)
	surfaces: list[str] = Field(default_factory=list)


@router.post("/v1/slash/parse")
def slash_parse(body: SlashParseRequest, request: Request) -> dict[str, Any]:
	"""轻量解析：各面用于未知命令判定（不执行任何 handler）。"""
	require_loopback(request)
	from slash.registry import parse_slash as _parse

	cmd, arg = _parse(body.text)
	if cmd is None:
		text = (body.text or "").strip()
		if text.startswith("/"):
			unknown = text[1:].strip()
			return {"handled": False, "unknown": True, "name": unknown.split(None, 1)[0] if unknown else ""}
		return {"handled": False, "unknown": False, "name": ""}
	return {
		"handled": True,
		"unknown": False,
		"name": cmd.name,
		"handler": cmd.handler,
		"arg": arg,
		"when": cmd.when,
	}
