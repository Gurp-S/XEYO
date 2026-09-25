"""Usage 域路由：厂商模型列表、用量报表、余额查询。

诚实性口径（2026-09-25 真实数据普查后钉在本文件，改端点前先读）：

1. 缺数据只能表达成「未记录」，不得变成 0，也不得算进「完整」合计。
2. 在截断集（账本行数上限 / 默认 30 日窗口）上算出的合计必须自报 partial 与分母。
3. 「该过滤键无数据」与「账本缺失 / 不可读」必须是两个可区分的响应。
4. 金额的计价口径（estimate vs 真实账单）不得被端点丢掉；本端点按 v4 不输出金额，
   于是把「有价 / 有行无价 / 无行」三分类以事实形式上报，前端据此判断能不能画钱。
5. 出现过但为空白的过滤参数必须边界 422，不得 strip 成空串后退化成全量查询。

本文件读 `usage.ledger._read_events()`（私有）是有意的：它自带
(路径, mtime, size) 缓存，query_usage 刚刚解析过 ⇒ 复用它是零额外成本，
而重新解析会在生产账本上双份开销；账号身份过滤复用同一次读取。
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Header, Query

from common.errors import friendly_error
from server.deps import _extract_bearer, _resolve_base_url, api_error

router = APIRouter(tags=["usage"])


# ---------- 通用小工具：只认「真数值」 ----------

def _num(v: Any) -> float | None:
	"""数值才算数值：bool / None / 空串 / 「abc」一律 None（绝不吞成 0）。"""
	if v is None or isinstance(v, bool):
		return None
	if isinstance(v, (int, float)):
		f = float(v)
		return None if f != f else f
	if isinstance(v, str):
		s = v.strip()
		if not s:
			return None
		try:
			f = float(s)
		except ValueError:
			return None
		return None if f != f else f
	return None


def _require_filter_token(name: str, raw: str | None) -> str | None:
	"""过滤参数的边界校验：出现过但去空白后为空 ⇒ 422。

	为什么必须在边界挡（真实数据实测，非理论担忧）：下游
	``usage.ledger.query_usage`` 用的是 ``want = (value or "").strip()``，
	空白串 strip 后成空 ⇒ 整个过滤条件消失，查询静默扩到全量行。
	本机账本 ``provider="   "`` 返回 15583 笔（= 无过滤全厂商），
	而真按 deepseek 过滤只有 11660 笔 —— 差额 3923 笔被贴上了 DeepSeek 的标签。
	"""
	if raw is None:
		return None
	stripped = raw.strip()
	if not stripped:
		raise api_error(
			422,
			f"missing_value_for_filter: parameter {name} is blank after trimming",
			"invalid_request_error",
		)
	return stripped


# ---------- 账本诚实性事实 ----------

def _row_limit() -> int:
	"""账本读取上限（ledger._MAX_LINES）；动态读，避免与 ledger 双份常量。"""
	from usage import ledger as _ledger

	try:
		return max(1, int(getattr(_ledger, "_MAX_LINES", 80_000)))
	except (TypeError, ValueError):
		return 80_000


def _count_raw_lines(path) -> tuple[int | None, str]:
	"""二进制数原始行数（含空行 —— 与 ledger 的下标口径同分母）。"""
	try:
		size = path.stat().st_size
	except OSError:
		return None, "unreadable"
	lines = 0
	last = b"\n"
	try:
		with path.open("rb") as f:
			while True:
				chunk = f.read(1 << 20)
				if not chunk:
					break
				lines += chunk.count(b"\n")
				last = chunk[-1:]
	except OSError:
		return None, "unreadable"
	if size and last not in (b"\n", b""):
		lines += 1
	return lines, "ok"


def _scan_skipped_lines(path) -> int:
	"""原始行数与解析行数不一致时才做的精确补扫：数坏 JSON / 空行。"""
	try:
		raw = path.read_text(encoding="utf-8", errors="replace")
	except OSError:
		return 0
	bad = 0
	for line in raw.splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			row = json.loads(line)
		except json.JSONDecodeError:
			bad += 1
			continue
		if not isinstance(row, dict):
			bad += 1
	return bad


def _local_store_status() -> dict[str, Any]:
	"""账本存储状态：区分「没有这个文件」「读不动」「空文件」「有货」。

	这一层是端点自己看得见的唯一真相：ledger._read_events 对上述四种一律
	返回 []，所以不在此处标注，客户端就会把「无账本」当成「零用量」。
	"""
	from usage import ledger as _ledger

	out: dict[str, Any] = {
		"store": "ok",
		"store_raw_lines": None,
		"lines_within_read_limit": None,
		"store_unparsable_lines": 0,
		"store_blank_lines": 0,
		"read_row_limit": _row_limit(),
		"rows_read": 0,
		"lines_beyond_read_limit": 0,
		"truncated_by_read_limit": False,
	}
	try:
		path = _ledger.events_path()
	except Exception:  # noqa: BLE001 — 路径解析失败也不能把端点炸成 500
		out["store"] = "unreadable_store"
		return out
	if not path.exists():
		out["store"] = "missing_store"
		return out
	raw_lines, status = _count_raw_lines(path)
	if status != "ok":
		out["store"] = "unreadable_store"
		return out
	out["store_raw_lines"] = raw_lines
	limit = out["read_row_limit"]
	out["lines_beyond_read_limit"] = max(0, int(raw_lines or 0) - limit)
	out["truncated_by_read_limit"] = out["lines_beyond_read_limit"] > 0
	try:
		events = _ledger._read_events()
	except Exception:  # noqa: BLE001
		out["store"] = "unreadable_store"
		return out
	rows = len(events) if isinstance(events, list) else 0
	out["rows_read"] = rows
	out["lines_within_read_limit"] = max(
		0, int(raw_lines or 0) - out["lines_beyond_read_limit"]
	)
	if rows != out["lines_within_read_limit"]:
		# 读得动但行数对不上：只有坏 JSON / 非 dict 行才是真丢数据，其余是空行。
		out["store_unparsable_lines"] = _scan_skipped_lines(path)
		out["store_blank_lines"] = max(
			0, out["lines_within_read_limit"] - rows - out["store_unparsable_lines"]
		)
	if rows == 0:
		out["store"] = "empty_store"
	return out


def _inspect_local_rows(day_ids: list[str]) -> dict[str, Any]:
	"""逐行分类（不聚合、不替模型下结论）：窗口内外 / 字段可否解析 / 有无价格。"""
	from usage import ledger as _ledger

	block: dict[str, Any] = {
		"rows_in_window": 0,
		"rows_outside_window": 0,
		"rows_without_day": 0,
		"rows_with_unreadable_counters": 0,
		"rows_missing_counter_keys": 0,
		"counter_field_absent": {},
		"counter_field_unreadable": {},
	}
	try:
		events = _ledger._read_events()
	except Exception:  # noqa: BLE001
		return block
	if not isinstance(events, list):
		return block
	day_set = {str(d) for d in day_ids}
	fields = ("cache_hit", "cache_miss", "output")
	absent: dict[str, int] = {f: 0 for f in fields}
	unreadable: dict[str, int] = {f: 0 for f in fields}
	for ev in events:
		if not isinstance(ev, dict):
			continue
		day = str(ev.get("day") or "")
		if not day:
			block["rows_without_day"] += 1
		elif day not in day_set:
			block["rows_outside_window"] += 1
		else:
			block["rows_in_window"] += 1
		bad_field = False
		miss_field = False
		for f in fields:
			if f not in ev or ev.get(f) is None:
				absent[f] += 1
				miss_field = True
			elif _num(ev.get(f)) is None:
				unreadable[f] += 1
				bad_field = True
		if bad_field:
			block["rows_with_unreadable_counters"] += 1
		if miss_field:
			block["rows_missing_counter_keys"] += 1
	block["counter_field_absent"] = absent
	block["counter_field_unreadable"] = unreadable
	return block


def _money_accounting() -> dict[str, Any]:
	"""三分类事实：有数值价格 / 有行但无价 / 根本没行。

	本端点按 v4 不输出金额（用户裁定：金额看官方费用中心），所以这里只报
	「账本里到底有没有价、计价口径是什么」，绝不把无价行加成 0 后称已计价。
	"""
	from usage import ledger as _ledger

	out: dict[str, Any] = {
		"reported": False,
		"reason": "v4_local_ui_reports_no_amount",
		"rows_with_numeric_cost": 0,
		"rows_with_zero_cost": 0,
		"rows_missing_cost_key": 0,
		"rows_with_unreadable_cost": 0,
		"cost_basis_counts": {},
		"cost_basis_labels": ("api", "estimate"),
		"rows_total": 0,
		"priced_complete": False,
	}
	try:
		events = _ledger._read_events()
	except Exception:  # noqa: BLE001
		return out
	if not isinstance(events, list):
		return out
	basis: dict[str, int] = {}
	for ev in events:
		if not isinstance(ev, dict):
			continue
		if "cost_cny" not in ev:
			out["rows_missing_cost_key"] += 1
		else:
			n = _num(ev.get("cost_cny"))
			if n is None:
				out["rows_with_unreadable_cost"] += 1
			else:
				out["rows_with_numeric_cost"] += 1
				if n == 0:
					out["rows_with_zero_cost"] += 1
		src = ev.get("cost_source")
		label = str(src).strip() if src is not None and str(src).strip() else "unlabelled"
		basis[label] = basis.get(label, 0) + 1
	out["cost_basis_counts"] = basis
	out["rows_total"] = len(events)
	# 「已计价」只在每一行都有可解析数值时才成立；无价行不许按 0 计入。
	out["priced_complete"] = (
		out["rows_with_numeric_cost"] == out["rows_total"] and out["rows_total"] > 0
	)
	return out


def _build_integrity(
	*,
	report: dict[str, Any],
	local: dict[str, Any],
	store: dict[str, Any],
	rows: dict[str, Any],
	requested_days: int,
) -> dict[str, Any]:
	"""把上面的事实收敛成一份「这份合计到底完不完整」的判据。"""
	day_ids = [str(d) for d in (report.get("days") or [])]
	local_totals = local.get("totals") if isinstance(local.get("totals"), dict) else {}
	rows_counted_local = _num(local_totals.get("requests"))
	ints: dict[str, Any] = {
		**store,
		**rows,
		"window_days": len(day_ids),
		"window_requested_days": requested_days,
		"window_start": day_ids[0] if day_ids else None,
		"window_end": day_ids[-1] if day_ids else None,
		"rows_counted_local": int(rows_counted_local) if rows_counted_local is not None else None,
		# keys 由 ledger 在过滤 **之前** 收集（真实数据实测：deepseek 30 日窗口
		# 只计 11660 笔，keys 却列出全账本 20 个指纹）⇒ 必须标注它的分母，
		# 否则这份清单会被读成「本次查询命中的 Key 列表」。
		"keys_reported": len(report.get("keys") or []),
		"keys_scope": "store_wide_not_query_scoped",
		"partial_reasons": [],
	}
	reasons: list[str] = []
	if ints["store"] != "ok":
		reasons.append(f"store_{ints['store']}")
	if ints["truncated_by_read_limit"]:
		reasons.append("read_row_limit_exceeded")
	if ints["store_unparsable_lines"]:
		reasons.append("unparsable_lines_in_store")
	if ints["rows_outside_window"]:
		reasons.append("day_window_excludes_stored_rows")
	if ints["rows_without_day"]:
		reasons.append("rows_without_day_field")
	if ints["rows_with_unreadable_counters"]:
		reasons.append("rows_with_unreadable_counters")
	# 窗口切片不是全量：账本里还有窗口外的行就必须标 partial（修 A2）。
	ints["partial_reasons"] = reasons
	ints["complete"] = not reasons
	return ints


# ---------- 端点 ----------

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
	legacy_key_fallback: bool = Query(default=True),
	authorization: str | None = Header(default=None),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
	"""厂商用量为权威；厂商拿不到时用本机按官方 usage 记的账。

	响应额外挂三份事实（只增键，不改既有键语义）：
	- ``filters``：本轮真正生效的过滤条件（空白 X-Provider 会被记成未生效）；
	- ``data_integrity``：账本状态 + 行数分母 + partial 判据；
	- ``money``：有价 / 有行无价 / 无行 的三分类与计价口径。
	"""
	from usage.combine import compose_usage_report, report_has_usage
	from usage.ledger import key_identity, query_usage
	from usage.vendor import fetch_vendor_usage

	# ① 边界：空白过滤参数 422，绝不 strip 后静默扩到全量（修 A5）。
	model_f = _require_filter_token("model", model)
	provider_f = _require_filter_token("provider", provider)
	key_f = _require_filter_token("key_fp", key_fp)

	api_key = _extract_bearer(authorization)
	hdr_provider = (x_provider or "").strip()
	provider_filter_applied = bool(provider_f or hdr_provider)
	# 头出现过但为空白 ⇒ 无法据此判定厂商 ⇒ 本地账本不按厂商过滤，
	# 也不静默回落 deepseek 后把全厂商合计贴成 DeepSeek（修 A5 的标签侧）。
	prov = (provider_f or hdr_provider or "deepseek").lower()
	# 与 /v1/models、/v1/usage/balance 同口径：base_url 必须过 SSRF 门，
	# 否则本机任意进程可借服务端把用户 API key 发往任意地址。
	base_url = _resolve_base_url(prov, x_base_url)
	vendor = fetch_vendor_usage(
		api_key=api_key,
		provider=prov,
		base_url=base_url,
		days=days,
		model=model_f,
		key_fp=key_f,
	)
	local = query_usage(
		days=days,
		model=model_f,
		provider=prov if provider_filter_applied else "",
		key_fp=key_f,
		key_id=(key_identity(api_key) or None) if key_f else None,
		legacy_key_fallback=legacy_key_fallback,
	)
	report = compose_usage_report(vendor, local)

	# ② 计价/来源口径不得被端点丢掉（修 A4 的口径侧）：combine 里 totals 与
	#    models 可以一个来自厂商、一个来自本机，而 source 只写了 totals 那一侧。
	vendor_ok = bool(vendor.get("vendor_ok"))
	totals_from_vendor = vendor_ok and report_has_usage(vendor)
	models_from_vendor = vendor_ok and bool(vendor.get("models"))
	if totals_from_vendor != models_from_vendor:
		report["source"] = "mixed"
	report["source_basis"] = {
		"totals": "vendor" if totals_from_vendor else "local",
		"models": "vendor" if models_from_vendor else "local",
		"vendor_ok": vendor.get("vendor_ok"),
		"vendor_error": vendor.get("vendor_error"),
	}

	# ③ 账本与行级事实（修 A1 / A2 / A3）。
	store = _local_store_status()
	day_ids = [str(d) for d in (report.get("days") or [])]
	rows = _inspect_local_rows(day_ids)
	report["filters"] = {
		"model": model_f,
		"provider": prov,
		"provider_filter_applied": provider_filter_applied,
		"key_fp": key_f if legacy_key_fallback else None,
		"key_id_filter_applied": bool(api_key and key_f),
		"legacy_key_fallback": legacy_key_fallback,
		"days": days,
	}
	report["data_integrity"] = _build_integrity(
		report=report,
		local=local,
		store=store,
		rows=rows,
		requested_days=days,
	)
	report["money"] = _money_accounting()
	return report


def _amount_status(raw: Any) -> tuple[Any, str]:
	"""厂商金额的规范化：可解析才透传原样值，否则 (None, 状态)。

	原样透传字符串是关键 —— 端点不做任何 float 运算 ⇒ 不会把「0.004」这类
	小金额在累加 / 舍入里吞成 0（本文件唯一的金额出口就是这里）。
	"""
	if raw is None:
		return None, "absent"
	if isinstance(raw, bool):
		return None, "not_a_number"
	if isinstance(raw, (int, float)):
		f = float(raw)
		if f != f:
			return None, "not_a_number"
		return (None, "negative") if f < 0 else (raw, "ok")
	text = str(raw).strip()
	if not text:
		return None, "empty"
	try:
		n = Decimal(text)
	except (InvalidOperation, ValueError):
		return None, "not_a_number"
	if not n.is_finite():
		return None, "not_a_number"
	if n < 0:
		return None, "negative"
	return raw, "ok"


_BALANCE_FIELDS = ("total_balance", "granted_balance", "topped_up_balance")


@router.get("/v1/usage/balance")
def get_usage_balance(
	authorization: str | None = Header(default=None),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
	"""代理 DeepSeek /user/balance；其它厂商返回 available=false。

	诚实性口径：货币标签只转述厂商给的值，缺失就是 null（旧实现补「CNY」，
	前端据此把美元余额画成 ¥）；只有拿到可解析数值才 available=true（旧实现
	在拿到一个 dict 行时就报 true，total_balance 为空串时前端渲染成裸「¥」）。
	"""
	api_key = _extract_bearer(authorization)
	provider = (x_provider or "deepseek").strip().lower()
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

	if not isinstance(payload, dict):
		return {
			"available": False,
			"reason": "unexpected_payload_shape",
			"is_available": None,
			"raw": payload,
		}

	infos = payload.get("balance_infos")
	rows = [r for r in infos if isinstance(r, dict)] if isinstance(infos, list) else []
	present = sorted(
		{
			str(r.get("currency") or "").strip().upper()
			for r in rows
			if str(r.get("currency") or "").strip()
		}
	)
	is_available = payload.get("is_available")

	def _unavailable(reason: str, currency: str | None) -> dict[str, Any]:
		return {
			"available": False,
			"reason": reason,
			"is_available": is_available,
			"currency": currency,
			"currency_source": "vendor_row" if currency else "absent",
			"currencies_in_response": present,
			"balance_rows": len(rows),
			"amount_status": {f: "absent" for f in _BALANCE_FIELDS},
		}

	if not rows:
		return _unavailable("no_balance_rows", None)

	cny_rows = [
		r
		for r in rows
		if str(r.get("currency") or "").strip().upper() == "CNY"
	]
	if cny_rows:
		row = cny_rows[0]
		currency = str(row.get("currency") or "").strip().upper()
		currency_source = "vendor_row"
	elif all(not str(r.get("currency") or "").strip() for r in rows) and len(rows) == 1:
		# 单行且厂商压根没写货币：数字可以给，但**不补标签**（前端据此不应声称币种）。
		row = rows[0]
		currency = None
		currency_source = "absent"
	else:
		# 只有非 CNY 行（或多行且无货币标签）⇒ 不拿它冒充本币余额。
		other = [
			{
				"currency": str(r.get("currency") or "").strip().upper() or None,
				**{f: r.get(f) for f in _BALANCE_FIELDS},
			}
			for r in rows
		]
		resp = _unavailable("no_cny_row", None)
		resp["other_currency_rows"] = other
		return resp

	values: dict[str, Any] = {}
	status: dict[str, str] = {}
	for f in _BALANCE_FIELDS:
		val, st = _amount_status(row.get(f))
		values[f] = val
		status[f] = st
	numerics = sum(1 for f in _BALANCE_FIELDS if status[f] == "ok")

	if is_available is False:
		resp = _unavailable("vendor_reports_unavailable", currency)
		resp["amount_status"] = status
		return resp
	if numerics == 0:
		resp = _unavailable("no_numeric_balance", currency)
		resp["amount_status"] = status
		return resp

	out: dict[str, Any] = {
		"available": True,
		"is_available": is_available,
		"currency": currency,
		"currency_source": currency_source,
		"currencies_in_response": present,
		"balance_rows": len(rows),
		"amount_status": status,
		"numeric_balance_fields": numerics,
		"fields_incomplete": any(status[f] != "ok" for f in _BALANCE_FIELDS),
		**values,
	}
	return out
