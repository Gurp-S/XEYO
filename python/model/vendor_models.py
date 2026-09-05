"""向厂商 GET /models 拉模型列表（厂商为权威）。"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from common.errors import NetworkError, friendly_error


def _as_int(v: Any) -> int:
	try:
		return int(v)
	except (TypeError, ValueError):
		return 0


def _pick_context(row: dict[str, Any]) -> int | None:
	for key in (
		"context_length",
		"context_window",
		"max_context_tokens",
		"max_model_len",
		"max_input_tokens",
		"max_sequence_length",
	):
		n = _as_int(row.get(key))
		if n > 0:
			return n
	# OpenRouter 把窗口放在 top_provider.context_length；部分厂商放 metadata
	for nested in ("metadata", "top_provider"):
		meta = row.get(nested)
		if isinstance(meta, dict):
			found = _pick_context(meta)
			if found is not None:
				return found
	return None


def _pick_max_output(row: dict[str, Any]) -> int | None:
	"""取厂商给出的最大输出 tokens（无则 None）。"""
	for key in (
		"max_output_tokens",
		"max_completion_tokens",
		"max_tokens",
		"max_output",
		"output_token_limit",
	):
		n = _as_int(row.get(key))
		if n > 0:
			return n
	for nested in ("metadata", "top_provider"):
		meta = row.get(nested)
		if isinstance(meta, dict):
			found = _pick_max_output(meta)
			if found is not None:
				return found
	return None


def _pick_pricing(row: dict[str, Any]) -> dict[str, Any] | None:
	for key in ("pricing", "price", "prices"):
		val = row.get(key)
		if isinstance(val, dict) and val:
			return val
	return None


def _pick_modes(row: dict[str, Any], *, provider: str) -> dict[str, Any]:
	modes: dict[str, Any] = {}
	raw = row.get("modes") or row.get("supported_modes") or row.get("capabilities")
	if isinstance(raw, dict):
		modes.update(raw)
	# 厂商可能用布尔表达 thinking 能力（smoke-test #9）：true=仅思考/false=不支持
	thinking = row.get("thinking") or row.get("supported_thinking")
	if isinstance(thinking, bool):
		modes["thinking"] = [{"id": "enabled", "label": "思考"}] if thinking else []
	elif thinking is not None and "thinking" not in modes:
		modes["thinking"] = thinking
	# DeepSeek 官方 Chat Completions 文档：thinking + reasoning_effort。
	# smoke-test #9 修正：只对 DeepSeek 家族模型注入（避免第三方兼容网关在
	# deepseek provider 下暴露的非 DeepSeek 模型被强制加上"必须有"的 thinking 开关）。
	if (
		provider == "deepseek"
		and "deepseek" in str(row.get("id") or row.get("model") or "").lower()
		and "thinking" not in modes
	):
		modes["thinking"] = [
			{"id": "disabled", "label": "非思考"},
			{"id": "enabled", "label": "思考"},
		]
		modes["reasoning_effort"] = [
			{"id": "low", "label": "low"},
			{"id": "high", "label": "high"},
			{"id": "max", "label": "max"},
		]
	return modes


def normalize_vendor_model(row: dict[str, Any], *, provider: str, index: int) -> dict[str, Any]:
	mid = str(row.get("id") or row.get("model") or "").strip()
	created = _as_int(row.get("created") or row.get("created_at") or row.get("updated_at"))
	out: dict[str, Any] = {
		"id": mid,
		"object": row.get("object") or "model",
		"owned_by": row.get("owned_by") or provider,
		"created": created,
		"index": index,
		"label": str(row.get("label") or row.get("name") or mid),
		"context_length": _pick_context(row),
		"max_output_tokens": _pick_max_output(row),
		"pricing": _pick_pricing(row),
		"modes": _pick_modes(row, provider=provider),
	}
	# 透传厂商其余字段，避免丢掉未映射信息
	for k, v in row.items():
		if k not in out:
			out[k] = v
	return out


def parse_vendor_models_payload(payload: Any, *, provider: str) -> list[dict[str, Any]]:
	rows: list[Any]
	if isinstance(payload, dict):
		data = payload.get("data") or payload.get("models") or []
		rows = data if isinstance(data, list) else []
	elif isinstance(payload, list):
		rows = payload
	else:
		rows = []
	out: list[dict[str, Any]] = []
	for i, row in enumerate(rows):
		if not isinstance(row, dict):
			continue
		item = normalize_vendor_model(row, provider=provider, index=i)
		if item["id"]:
			out.append(item)
	out.sort(key=lambda m: (-int(m.get("created") or 0), int(m.get("index") or 0)))
	return out


def _http_json(url: str, headers: dict[str, str], timeout: float = 12.0) -> tuple[int, Any]:
	req = Request(url, headers=headers, method="GET")
	try:
		with urlopen(req, timeout=timeout) as resp:
			raw = resp.read().decode("utf-8", errors="replace")
			status = int(getattr(resp, "status", 200) or 200)
	except HTTPError as e:
		raw = e.read().decode("utf-8", errors="replace")
		status = int(e.code)
	except URLError as e:
		raise NetworkError(str(e)) from e
	try:
		payload = json.loads(raw) if raw else None
	except json.JSONDecodeError as e:
		raise RuntimeError(f"invalid json from {url}: {e}") from e
	return status, payload


def fetch_vendor_models(
	*,
	api_key: str,
	provider: str,
	base_url: str,
) -> dict[str, Any]:
	prov = (provider or "deepseek").strip().lower()
	key = (api_key or "").strip()
	if not key:
		# 本地 provider 无需 Key：仅 provider=="local" 允许免 Key，其余须提供 key。
		if prov == "local":
			key = "local"
		else:
			return {
				"object": "list",
				"source": "vendor",
				"vendor_ok": False,
				"vendor_error": "missing_key",
				"data": [],
			}
	root = (base_url or "").rstrip("/")
	if not root:
		return {
			"object": "list",
			"source": "vendor",
			"vendor_ok": False,
			"vendor_error": "missing_base_url",
			"data": [],
		}
	url = f"{root}/models"
	try:
		st, payload = _http_json(
			url,
			{
				"Authorization": f"Bearer {key}",
				"Accept": "application/json",
			},
		)
		if st >= 400:
			msg = ""
			if isinstance(payload, dict):
				err = payload.get("error")
				if isinstance(err, dict):
					msg = str(err.get("message") or "")
				elif payload.get("msg"):
					msg = str(payload.get("msg"))
			raise RuntimeError(msg or f"HTTP {st}")
		data = parse_vendor_models_payload(payload, provider=prov)
		return {
			"object": "list",
			"source": "vendor",
			"vendor_ok": True,
			"vendor_error": "",
			"data": data,
		}
	except Exception as e:  # noqa: BLE001
		return {
			"object": "list",
			"source": "vendor",
			"vendor_ok": False,
			"vendor_error": friendly_error(e),
			"data": [],
		}
