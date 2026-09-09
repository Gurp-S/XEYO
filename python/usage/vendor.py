"""向厂商拉取用量（能拿到时作为权威数据源）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from usage.attribution import canonical_vendor

BJ = timezone(timedelta(hours=8))

_USAGE_TYPES = {
	"PROMPT_CACHE_HIT_TOKEN": "cache_hit",
	"PROMPT_CACHE_MISS_TOKEN": "cache_miss",
	"RESPONSE_TOKEN": "output",
	"COMPLETION_TOKEN": "output",
	"REQUEST": "requests",
}


def _day_list(days: int, *, end: date | None = None) -> list[str]:
	span = max(1, min(366, int(days)))
	last = end or datetime.now(tz=BJ).date()
	start = last - timedelta(days=span - 1)
	cur = start
	out: list[str] = []
	while cur <= last:
		out.append(cur.isoformat())
		cur += timedelta(days=1)
	return out


def _hit_rate(hit: Any, miss: Any) -> float | None:
	"""与 usage.ledger._hit_rate 同口径（v4：无金额）。"""
	try:
		h, m = max(0, int(hit or 0)), max(0, int(miss or 0))
	except (TypeError, ValueError):
		return None
	if h + m <= 0:
		return None
	return round(h / (h + m) * 100.0, 1)


def _bucket_view(bucket: dict[str, Any]) -> dict[str, Any]:
	"""渲染对外口径：三分类 + input_total + hit_rate，无金额/吞吐大数（dsh S1）。"""
	try:
		h = max(0, int(bucket.get("cache_hit") or 0))
		m = max(0, int(bucket.get("cache_miss") or 0))
		o = max(0, int(bucket.get("output") or 0))
		r = max(0, int(bucket.get("requests") or 0))
	except (TypeError, ValueError):
		h = m = o = r = 0
	return {
		"requests": r,
		"input_hit": h,
		"input_miss": m,
		"output": o,
		"input_total": h + m,
		"hit_rate": _hit_rate(h, m),
	}


def _empty_bucket() -> dict[str, int]:
	return {
		"requests": 0,
		"cache_hit": 0,
		"cache_miss": 0,
		"output": 0,
	}


def _empty_report(
	days: int,
	*,
	vendor_ok: bool,
	vendor_error: str,
	provider: str = "",
) -> dict[str, Any]:
	day_ids = _day_list(days)
	eb = _empty_bucket()
	return {
		"days": day_ids,
		"totals": _bucket_view(eb),
		"source": "vendor" if vendor_ok else "local",
		"vendor_ok": vendor_ok,
		"vendor_error": vendor_error,
		"provider": provider,
		"series": _series_from(day_ids, {}),
		"models": [],
		"keys": [],
	}


def _series_from(
	days: list[str],
	by_day: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for d in days:
		b = by_day.get(d) or _empty_bucket()
		point = _bucket_view(b)
		point["day"] = d
		out.append(point)
	return out


def _as_num(v: Any) -> float:
	if v is None or v == "":
		return 0.0
	try:
		return float(v)
	except (TypeError, ValueError):
		return 0.0


def _http_json(
	url: str,
	headers: dict[str, str],
	timeout: float = 12.0,
) -> tuple[int, Any]:
	req = Request(url, headers=headers, method="GET")
	try:
		with urlopen(req, timeout=timeout) as resp:
			raw = resp.read().decode("utf-8", errors="replace")
			status = int(getattr(resp, "status", 200) or 200)
	except HTTPError as e:
		raw = e.read().decode("utf-8", errors="replace")
		status = int(e.code)
	except URLError as e:
		raise RuntimeError(f"network: {e}") from e
	try:
		payload = json.loads(raw) if raw else None
	except json.JSONDecodeError as e:
		raise RuntimeError(f"invalid json from {url}: {e}") from e
	return status, payload


def _unwrap_platform(payload: Any) -> Any:
	if not isinstance(payload, dict):
		raise RuntimeError("unexpected platform payload")
	code = payload.get("code")
	if code not in (0, "0", None):
		msg = str(payload.get("msg") or payload.get("message") or f"code {code}")
		raise RuntimeError(msg)
	data = payload.get("data")
	if not isinstance(data, dict):
		return data
	biz_code = data.get("biz_code")
	if biz_code not in (0, "0", None):
		raise RuntimeError(str(data.get("biz_msg") or f"biz_code {biz_code}"))
	return data.get("biz_data", data)


def parse_platform_amount(payload: Any) -> list[dict[str, Any]]:
	"""把 platform amount 拆成按日+模型的桶列表。"""
	biz = _unwrap_platform(payload) if isinstance(payload, dict) and "code" in payload else payload
	if isinstance(biz, list):
		biz = biz[0] if biz and isinstance(biz[0], dict) else {}
	if not isinstance(biz, dict):
		return []
	days = biz.get("days") or biz.get("daily") or []
	if not isinstance(days, list):
		return []
	rows: list[dict[str, Any]] = []
	for day in days:
		if not isinstance(day, dict):
			continue
		iso = str(day.get("date") or day.get("day") or "")[:10]
		if len(iso) < 10:
			continue
		models = day.get("data") or day.get("models") or []
		if not isinstance(models, list):
			continue
		for item in models:
			if not isinstance(item, dict):
				continue
			mid = str(item.get("model") or item.get("model_name") or "unknown")
			bucket = _empty_bucket()
			usages = item.get("usage") or item.get("usages") or []
			if isinstance(usages, list):
				prompt = 0.0
				for u in usages:
					if not isinstance(u, dict):
						continue
					kind = str(u.get("type") or u.get("name") or "").upper()
					amt = _as_num(u.get("amount") or u.get("value") or u.get("count"))
					field = _USAGE_TYPES.get(kind)
					if field == "requests":
						bucket["requests"] = int(bucket["requests"]) + int(amt)
					elif field:
						bucket[field] = int(bucket[field]) + int(amt)
					elif kind in ("PROMPT_TOKEN", "PROMPT_TOKENS", "INPUT_TOKEN"):
						prompt += amt
				if int(bucket["cache_hit"]) + int(bucket["cache_miss"]) == 0 and prompt:
					bucket["cache_miss"] = int(prompt)
			rows.append({"day": iso, "model": mid, "bucket": bucket})
	return rows


def parse_platform_cost(payload: Any) -> list[dict[str, Any]]:
	biz = _unwrap_platform(payload) if isinstance(payload, dict) and "code" in payload else payload
	if isinstance(biz, list):
		chunks = [x for x in biz if isinstance(x, dict)]
	elif isinstance(biz, dict):
		chunks = [biz]
	else:
		return []
	rows: list[dict[str, Any]] = []
	for chunk in chunks:
		days = chunk.get("days") or chunk.get("daily") or []
		if not isinstance(days, list):
			continue
		for day in days:
			if not isinstance(day, dict):
				continue
			iso = str(day.get("date") or day.get("day") or "")[:10]
			if len(iso) < 10:
				continue
			models = day.get("data") or day.get("models") or []
			if not isinstance(models, list):
				continue
			for item in models:
				if not isinstance(item, dict):
					continue
				mid = str(item.get("model") or item.get("model_name") or "unknown")
				cost = _as_num(item.get("cost") or item.get("amount") or item.get("total"))
				usages = item.get("usage") or item.get("usages") or []
				if isinstance(usages, list):
					for u in usages:
						if not isinstance(u, dict):
							continue
						cost += _as_num(u.get("amount") or u.get("value") or u.get("cost"))
				rows.append({"day": iso, "model": mid, "cost": cost})
	return rows


def _merge_report(
	*,
	days: int,
	provider: str,
	amount_rows: list[dict[str, Any]],
	cost_rows: list[dict[str, Any]],
	model: str | None,
	end: date | None = None,
) -> dict[str, Any]:
	"""按日+模型聚合 amount 桶成统一报告（v4 无金额）。

	``cost_rows`` 保留形参以兼容厂商解析接口，但 **不再累计/输出**（本地界面不出现
	金额；厂商账单请在官方费用中心查看 —— 用户裁定）。
	"""
	_ = cost_rows
	day_ids = _day_list(days, end=end)
	day_set = set(day_ids)
	want = (model or "").strip()
	by_day: dict[str, dict[str, int]] = {}
	by_model: dict[str, dict[str, dict[str, int]]] = {}
	model_totals: dict[str, dict[str, int]] = {}
	totals = _empty_bucket()
	_KEYS = ("requests", "cache_hit", "cache_miss", "output")

	def take(mid: str, iso: str) -> dict[str, int]:
		slot = by_model.setdefault(mid, {})
		return slot.setdefault(iso, _empty_bucket())

	for row in amount_rows:
		iso = str(row.get("day") or "")
		mid = str(row.get("model") or "unknown")
		if iso not in day_set:
			continue
		if want and mid != want:
			continue
		src = row.get("bucket") or _empty_bucket()
		b = take(mid, iso)
		day_b = by_day.setdefault(iso, _empty_bucket())
		mt = model_totals.setdefault(mid, _empty_bucket())
		for k in _KEYS:
			v = int(src.get(k) or 0)
			b[k] = int(b[k]) + v
			day_b[k] = int(day_b[k]) + v
			totals[k] = int(totals[k]) + v
			mt[k] = int(mt[k]) + v

	models: list[dict[str, Any]] = []
	for mid, tot in sorted(
		model_totals.items(),
		# v4：与账本同排序 —— 输入未命中(新增内容)降序。
		key=lambda kv: (-int(kv[1].get("cache_miss") or 0), -int(kv[1].get("requests") or 0), kv[0]),
	):
		# 与账本一致：models[].provider 携带模型真实厂商 id（P0-1），不再写通道名。
		vendor = canonical_vendor(model=mid, provider=provider)
		mv = _bucket_view(tot)
		mv.update(
			{
				"provider": vendor,
				"vendor": vendor,
				"model": mid,
				"series": _series_from(day_ids, by_model.get(mid, {})),
			}
		)
		models.append(mv)

	return {
		"days": day_ids,
		"totals": _bucket_view(totals),
		"source": "vendor",
		"vendor_ok": True,
		"vendor_error": "",
		"provider": provider,
		"series": _series_from(day_ids, by_day),
		"models": models,
		"keys": [],
	}


def _fetch_deepseek(
	*,
	api_key: str,
	days: int,
	model: str | None,
) -> dict[str, Any]:
	# Bearer API Key 调不通 platform 网页用量（只开放 /user/balance）。
	# 再请求只会卡在超时/非法 JSON，看板结果仍是本地记账，故不发这次 HTTP。
	_ = (api_key, model)
	return _empty_report(
		days,
		vendor_ok=False,
		vendor_error=(
			"DeepSeek 未向 API Key 开放历史用量接口；"
			"官方目前只有 /user/balance。"
		),
		provider="deepseek",
	)


def parse_openai_usage_page(payload: Any, *, provider: str = "openai") -> tuple[
	list[dict[str, Any]],
	list[dict[str, Any]],
]:
	if not isinstance(payload, dict):
		return [], []
	buckets = payload.get("data")
	if not isinstance(buckets, list):
		return [], []
	amount_rows: list[dict[str, Any]] = []
	cost_rows: list[dict[str, Any]] = []
	for bucket in buckets:
		if not isinstance(bucket, dict):
			continue
		start = bucket.get("start_time")
		iso = ""
		if isinstance(start, (int, float)):
			iso = datetime.fromtimestamp(float(start), tz=BJ).date().isoformat()
		results = bucket.get("results")
		if not isinstance(results, list):
			continue
		for item in results:
			if not isinstance(item, dict):
				continue
			mid = str(item.get("model") or "unknown")
			b = _empty_bucket()
			inp = int(_as_num(item.get("input_tokens")))
			cached = int(_as_num(item.get("input_cached_tokens")))
			out = int(_as_num(item.get("output_tokens")))
			b["cache_hit"] = cached
			b["cache_miss"] = max(0, inp - cached)
			b["output"] = out
			b["requests"] = int(_as_num(item.get("num_model_requests") or item.get("num_requests")))
			amount_rows.append({"day": iso, "model": mid, "bucket": b, "provider": provider})
			cost = _as_num(item.get("amount") or item.get("cost"))
			if cost:
				cost_rows.append({"day": iso, "model": mid, "cost": cost})
	return amount_rows, cost_rows


def _fetch_openai(
	*,
	api_key: str,
	base_url: str,
	days: int,
	model: str | None,
) -> dict[str, Any]:
	root = (base_url or "https://api.openai.com/v1").rstrip("/")
	end = datetime.now(tz=timezone.utc)
	start = end - timedelta(days=max(1, days))
	qs = urlencode(
		{
			"start_time": int(start.timestamp()),
			"end_time": int(end.timestamp()),
			"bucket_width": "1d",
			"group_by[]": "model",
		}
	)
	url = f"{root}/organization/usage/completions?{qs}"
	headers = {
		"Authorization": f"Bearer {api_key}",
		"Accept": "application/json",
	}
	st, payload = _http_json(url, headers)
	if st >= 400:
		msg = ""
		if isinstance(payload, dict):
			err = payload.get("error")
			if isinstance(err, dict):
				msg = str(err.get("message") or "")
		raise RuntimeError(msg or f"HTTP {st}（OpenAI 用量接口通常需要组织 Admin Key）")
	amount_rows, cost_rows = parse_openai_usage_page(payload)
	return _merge_report(
		days=days,
		provider="openai",
		amount_rows=amount_rows,
		cost_rows=cost_rows,
		model=model,
	)


def fetch_vendor_usage(
	*,
	api_key: str,
	provider: str,
	base_url: str | None = None,
	days: int = 30,
	model: str | None = None,
	key_fp: str | None = None,
) -> dict[str, Any]:
	_ = key_fp  # 厂商按日接口一般不到 Key 粒度
	prov = (provider or "deepseek").strip().lower()
	key = (api_key or "").strip()
	if not key:
		return _empty_report(days, vendor_ok=False, vendor_error="missing_key", provider=prov)
	try:
		if prov == "deepseek":
			return _fetch_deepseek(api_key=key, days=days, model=model)
		if prov == "openai":
			return _fetch_openai(
				api_key=key,
				base_url=base_url or "https://api.openai.com/v1",
				days=days,
				model=model,
			)
		return _empty_report(
			days,
			vendor_ok=False,
			vendor_error="unsupported_provider",
			provider=prov,
		)
	except Exception as e:  # noqa: BLE001
		rep = _empty_report(days, vendor_ok=False, vendor_error=str(e), provider=prov)
		return rep
