"""跨域共享依赖：单例池、统一错误构造、鉴权/供应商解析、媒体引用校验。

依赖方向约束：本模块不得 import 任何 router / app（app → routers → deps）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from model.openai_compat import PROVIDER_PRESETS
from session.workspace_path import boot_ui_cwd, xeyo_data_root
from server.session_pool import SessionPool

# hydrate 前限制客户端提供的先前回合（字符数 / 消息数）。
_MAX_PRIOR_MESSAGES = 80
_MAX_PRIOR_CHARS = 100_000
# 限制最新用户回合（#9）。
_MAX_USER_CHARS = 100_000

CWD = boot_ui_cwd()
UPLOAD_DIR = Path(os.environ.get("XEYO_UPLOAD_DIR") or (xeyo_data_root() / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_pool = SessionPool(cwd=CWD)

_STATUS_ERROR_TYPE = {
	400: "invalid_request",
	401: "authentication_error",
	403: "permission_error",
	404: "not_found",
	409: "session_busy",
	413: "invalid_request",
	502: "model_error",
	503: "server_error",
	500: "server_error",
}


def error_body(message: str, err_type: str) -> dict[str, Any]:
	"""统一 API / SSE 错误结构：{error:{message,type}}。"""
	return {"error": {"message": message, "type": err_type}}


def _error_type_for_status(status: int) -> str:
	return _STATUS_ERROR_TYPE.get(status, "server_error")


def api_error(status: int, message: str, err_type: str | None = None) -> HTTPException:
	"""抛出 HTTPException，其 handler 输出统一错误体。"""
	return HTTPException(
		status_code=status,
		detail={
			"message": message,
			"type": err_type or _error_type_for_status(status),
		},
	)


def _extract_bearer(authorization: str | None) -> str:
	if not authorization:
		return ""
	parts = authorization.split(" ", 1)
	if len(parts) == 2 and parts[0].lower() == "bearer":
		return parts[1].strip()
	return authorization.strip()


def _resolve_base_url(provider: str, base_url: str | None) -> str:
	if base_url and base_url.strip():
		return base_url.strip().rstrip("/")
	preset = PROVIDER_PRESETS.get(provider, {})
	return preset.get("base_url", "https://api.openai.com/v1").rstrip("/")


def local_model_enabled() -> bool:
	"""provider="local"（本地 llama.cpp 等）需显式开启：XEYO_ALLOW_LOCAL_MODEL=1。

	开启后仍允许空 API key（本地推理服务通常不校验）。默认关闭，
	避免生产环境残留免鉴权的本地通道。
	"""
	return os.environ.get("XEYO_ALLOW_LOCAL_MODEL", "").strip().lower() in (
		"1",
		"true",
		"yes",
		"on",
	)


def fake_model_enabled() -> bool:
	"""provider="fake"（FakeModelClient，HTTP 全栈测试用）需显式开启。

	与 ``local_model_enabled`` 同款门禁：``XEYO_ALLOW_FAKE_MODEL=1`` 才放行，
	默认关闭，避免生产环境残留免鉴权的 fake 通道。
	"""
	return os.environ.get("XEYO_ALLOW_FAKE_MODEL", "").strip().lower() in (
		"1",
		"true",
		"yes",
		"on",
	)


def _validated_media_refs(raw: list[str] | None) -> list[str]:
	"""只接受本机媒体存储生成的引用，禁止客户端伪造任意路径 URL。"""
	if not raw:
		return []
	from media_store import media_exists

	refs: list[str] = []
	for value in raw:
		ref = str(value or "").strip()
		if not ref:
			continue
		if not media_exists(ref):
			raise api_error(400, f"media_ref not found: {ref}")
		refs.append(ref)
	return refs
