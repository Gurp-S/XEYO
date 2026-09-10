"""Usage 域路由：厂商模型列表、用量报表、余额查询。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Query

from common.errors import friendly_error
from server.deps import _extract_bearer, _resolve_base_url

router = APIRouter(tags=["usage"])

@router.get("/v1/models")
def list_models(
	authorization: str | None = Header(default=None),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
	"""代理厂商 GET /models，不以本地目录为数据源。"""
	from model.vendor_models import fetch_vendor_models

	api_key = _extract_bearer(authorization)
	provider = (x_provider or "deepseek").lower()
	base_url = _resolve_base_url(provider, x_base_url)
	return fetch_vendor_models(api_key=api_key, provider=provider, base_url=base_url)


@router.get("/v1/usage")
def get_usage(
	days: int = Query(default=30, ge=1, le=366),
	model: str | None = Query(default=None),
	provider: str | None = Query(default=None),
	key_fp: str | None = Query(default=None),
	authorization: str | None = Header(default=None),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
	"""厂商用量为权威；厂商拿不到时用本机按官方 usage 记的账。"""
	from usage.combine import compose_usage_report
	from usage.ledger import query_usage
	from usage.vendor import fetch_vendor_usage

	api_key = _extract_bearer(authorization)
	prov = (provider or x_provider or "deepseek").lower()
	# 与 /v1/models、/v1/usage/balance 同口径：base_url 必须过 SSRF 门，
	# 否则本机任意进程可借服务端把用户 API key 发往任意地址。
	base_url = _resolve_base_url(prov, x_base_url)
	vendor = fetch_vendor_usage(
		api_key=api_key,
		provider=prov,
		base_url=base_url,
		days=days,
		model=model,
		key_fp=key_fp,
	)
	local = query_usage(
		days=days,
		model=model,
		provider=prov,
		key_fp=key_fp,
	)
	return compose_usage_report(vendor, local)


@router.get("/v1/usage/balance")
def get_usage_balance(
	authorization: str | None = Header(default=None),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
	"""代理 DeepSeek /user/balance；其它厂商返回 available=false。"""
	api_key = _extract_bearer(authorization)
	provider = (x_provider or "deepseek").lower()
	if provider != "deepseek":
		return {"available": False, "reason": "unsupported_provider"}
	if not api_key:
		return {"available": False, "reason": "missing_key"}

	base = _resolve_base_url(provider, x_base_url)
	root = base.rstrip("/")
	if root.endswith("/v1"):
		root = root[: -len("/v1")]
	url = f"{root}/user/balance"
	try:
		from urllib.request import Request, urlopen

		req = Request(
			url,
			headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
			method="GET",
		)
		with urlopen(req, timeout=8) as resp:
			payload = json.loads(resp.read().decode("utf-8", errors="replace"))
	except Exception as e:  # noqa: BLE001
		return {"available": False, "reason": friendly_error(e)}

	infos = payload.get("balance_infos") if isinstance(payload, dict) else None
	cny = None
	if isinstance(infos, list):
		for row in infos:
			if isinstance(row, dict) and str(row.get("currency") or "").upper() == "CNY":
				cny = row
				break
		if cny is None and infos and isinstance(infos[0], dict):
			cny = infos[0]
	if not isinstance(cny, dict):
		return {
			"available": bool(payload.get("is_available")) if isinstance(payload, dict) else False,
			"is_available": payload.get("is_available") if isinstance(payload, dict) else None,
			"raw": payload,
		}
	return {
		"available": True,
		"is_available": payload.get("is_available") if isinstance(payload, dict) else None,
		"currency": cny.get("currency") or "CNY",
		"total_balance": cny.get("total_balance"),
		"granted_balance": cny.get("granted_balance"),
		"topped_up_balance": cny.get("topped_up_balance"),
	}
