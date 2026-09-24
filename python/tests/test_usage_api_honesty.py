"""usage 端点的诚实性回归（2026-09-25 真实数据普查后的 5 类缺陷）。

运行:
  py -3.11 -m pytest tests/test_usage_api_honesty.py -q

铁律：缺数据必须是「未记录」，不能是 0；截断/窗口切片必须自报 partial；
「无此 key 的数据」与「账本缺失/不可读」必须可区分；货币与计价口径不得被补出来；
空白过滤参数必须 422。全部用例走 tmp_path 账本，不碰 ~/.xeyo。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app


def _client() -> TestClient:
	return TestClient(app)


def _today(days_ago: int = 0) -> str:
	from usage.pricing import BJ

	return (datetime.now(tz=BJ).date() - timedelta(days=days_ago)).isoformat()


def _row(
	*,
	day: str | None = None,
	model: str = "deepseek-v4-flash",
	vendor: str = "deepseek",
	key_fp: str = "…abcd",
	hit: object = 100,
	miss: object = 10,
	out: object = 5,
	cost: object = 0.02,
	cost_source: object = "estimate",
) -> dict:
	row: dict = {
		"ts": 1_760_000_000.0,
		"day": day if day is not None else _today(),
		"provider": "deepseek",
		"vendor": vendor,
		"model": model,
		"key_fp": key_fp,
		"cache_hit": hit,
		"cache_miss": miss,
		"output": out,
	}
	if cost is not _MISSING:
		row["cost_cny"] = cost
	if cost_source is not _MISSING:
		row["cost_source"] = cost_source
	return row


_MISSING = object()


@pytest.fixture()
def store(tmp_path, monkeypatch: pytest.MonkeyPatch):
	"""把本机账本钉进 tmp，并默认把厂商接口桩成「不可用」（只看本地口径）。"""
	usage_dir = tmp_path / "usage"
	monkeypatch.setenv("XEYO_USAGE_DIR", str(usage_dir))
	from usage import ledger

	monkeypatch.setattr(ledger, "_events_cache", None)

	_vendor_off = {
		"vendor_ok": False,
		"vendor_error": "stub_off",
		"source": "vendor",
		"days": [],
		"totals": {},
		"series": [],
		"models": [],
		"keys": [],
	}
	monkeypatch.setattr(
		"usage.vendor.fetch_vendor_usage",
		lambda **kw: dict(_vendor_off),
	)

	def _write(rows: list[dict] | str) -> Path:
		usage_dir.mkdir(parents=True, exist_ok=True)
		path = ledger.events_path()
		if isinstance(rows, str):
			path.write_text(rows, encoding="utf-8")
		else:
			path.write_text(
				"".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
				encoding="utf-8",
			)
		monkeypatch.setattr(ledger, "_events_cache", None)
		return path

	_write.__name__ = "write_events"
	return _write


def _get_usage(c: TestClient, **params) -> dict:
	r = c.get("/v1/usage", params=params)
	assert r.status_code == 200, r.text
	return r.json()


# ---------- 缺陷 5：空白过滤参数静默扩成全量查询 ----------


@pytest.mark.parametrize("param", ["model", "provider", "key_fp"])
def test_blank_filter_param_is_rejected_not_widened(store, param: str) -> None:
	store([_row(), _row(model="other", vendor="zhipu", key_fp="…ffff")])
	c = _client()
	for blank in (" ", "   ", "\t", "  \n "):
		r = c.get("/v1/usage", params={"days": 30, param: blank})
		assert r.status_code == 422, (param, blank, r.status_code, r.text)
		err = r.json().get("error") or {}
		msg = str(err.get("message") or r.json())
		assert param in msg, msg
		assert err.get("type") == "invalid_request_error", err


def test_real_filter_still_works_after_edge_guard(store) -> None:
	store([_row(), _row(vendor="zhipu", model="glm-4"), _row(vendor="zhipu", model="glm-4")])
	body = _get_usage(_client(), days=30, provider="zhipu")
	assert body["filters"]["provider_filter_applied"] is True
	assert body["data_integrity"]["rows_counted_local"] == 2


def test_store_wide_keys_list_is_labelled_with_its_real_denominator(store) -> None:
	"""ledger 的 keys 是过滤 **前** 收集的：查询只命中 1 笔时清单仍是全账本的。

	ledger.py 不在本次可改范围，所以端点必须把分母说出来，不能让
	「本次查询命中的 Key」这一读法成立。
	"""
	store([_row(key_fp="…aaaa"), _row(key_fp="…bbbb")])
	body = _get_usage(_client(), days=30, key_fp="…aaaa")
	integrity = body["data_integrity"]
	assert integrity["rows_counted_local"] == 1
	assert integrity["keys_reported"] == 2
	assert integrity["keys_scope"] == "store_wide_not_query_scoped"


def test_blank_provider_header_marks_filter_as_not_applied(store) -> None:
	"""头部空白不能被静默回落成 deepseek 后把全厂商合计贴成 DeepSeek。"""
	store([_row(), _row(vendor="zhipu", model="glm-4")])
	c = _client()
	r = c.get("/v1/usage?days=30", headers={"X-Provider": "   "})
	assert r.status_code == 200, r.text
	body = r.json()
	assert body["filters"]["provider_filter_applied"] is False
	assert body["data_integrity"]["rows_counted_local"] == 2


# ---------- 缺陷 1：缺失 / 空串 / 非数值的价与量被吞成 0 并计入「已计价」 ----------


def test_absent_and_unreadable_cost_never_counted_as_priced(store) -> None:
	store(
		[
			_row(cost=0.25),                                  # 有数值价
			_row(cost=_MISSING),                              # 有行无 cost 键
			_row(cost=None),                                  # 显式 null
			_row(cost=""),                                    # 空串
			_row(cost="abc"),                                 # 非数值
			_row(cost=0),                                     # 真 0（必须与「无价」区分）
		]
	)
	body = _get_usage(_client(), days=30)
	money = body["money"]
	assert money["rows_with_numeric_cost"] == 2          # 0.25 + 真 0
	assert money["rows_with_zero_cost"] == 1
	assert money["rows_missing_cost_key"] == 1
	assert money["rows_with_unreadable_cost"] == 3       # None / "" / "abc"
	assert money["reported"] is False
	assert money["priced_complete"] is False
	assert money["rows_total"] == 6
	# 端点按 v4 不出金额：不得有任何可被渲染成 ¥0 的金额字段。
	assert "cost_cny" not in json.dumps(body["totals"])
	assert body["data_integrity"]["rows_counted_local"] == 6


def test_all_priced_store_can_claim_priced_complete(store) -> None:
	store([_row(cost=0.25), _row(cost=0.02)])
	body = _get_usage(_client(), days=30)
	assert body["money"]["priced_complete"] is True
	assert body["money"]["rows_with_unreadable_cost"] == 0


def test_cost_basis_label_survives_the_endpoint(store) -> None:
	"""计价口径（api 真实账单 vs estimate 估算）不能被端点丢掉。"""
	store(
		[
			_row(cost_source="api"),
			_row(cost_source="api"),
			_row(cost_source="estimate"),
			_row(cost_source=_MISSING),                    # 真实账本里确有 2 行无标签
			_row(cost_source="   "),
		]
	)
	body = _get_usage(_client(), days=30)
	basis = body["money"]["cost_basis_counts"]
	assert basis["api"] == 2
	assert basis["estimate"] == 1
	assert basis["unlabelled"] == 2
	assert "api" in body["money"]["cost_basis_labels"]


def test_unreadable_counter_fields_are_declared_not_silently_zeroed(store) -> None:
	store(
		[
			_row(),
			_row(hit="", miss="x", out=None),
		]
	)
	body = _get_usage(_client(), days=30)
	integrity = body["data_integrity"]
	# ledger 会把坏值 _as_int 成 0 后仍把该行算进 requests —— 端点必须说出来。
	assert integrity["rows_with_unreadable_counters"] == 1
	assert integrity["counter_field_unreadable"]["cache_hit"] == 1
	assert integrity["counter_field_unreadable"]["cache_miss"] == 1
	assert integrity["counter_field_absent"]["output"] == 1
	assert "rows_with_unreadable_counters" in integrity["partial_reasons"]
	assert body["totals"]["requests"] == 2


# ---------- 缺陷 2：截断集 / 窗口切片被当成全量合计 ----------


def test_default_day_window_is_labelled_partial(store) -> None:
	store([_row(), _row(day=_today(200))])
	body = _get_usage(_client(), days=30)
	integrity = body["data_integrity"]
	assert integrity["rows_in_window"] == 1
	assert integrity["rows_outside_window"] == 1
	assert "day_window_excludes_stored_rows" in integrity["partial_reasons"]
	assert integrity["complete"] is False
	assert integrity["window_days"] == 30


def test_full_window_report_can_claim_complete(store) -> None:
	store([_row(), _row(day=_today(200))])
	body = _get_usage(_client(), days=366)
	integrity = body["data_integrity"]
	assert integrity["partial_reasons"] == []
	assert integrity["complete"] is True
	assert integrity["rows_counted_local"] == 2


def test_row_read_limit_truncation_is_reported_with_denominator(store, monkeypatch) -> None:
	"""账本行数上限（生产 80_000，append-only ⇒ 丢的是最新行）必须自报。"""
	from usage import ledger

	monkeypatch.setattr(ledger, "_MAX_LINES", 2)
	store([_row(cost=float(i) / 100) for i in range(1, 6)])
	body = _get_usage(_client(), days=30)
	integrity = body["data_integrity"]
	assert integrity["read_row_limit"] == 2
	assert integrity["store_raw_lines"] == 5
	assert integrity["rows_read"] == 2
	assert integrity["lines_beyond_read_limit"] == 3
	assert integrity["truncated_by_read_limit"] is True
	assert "read_row_limit_exceeded" in integrity["partial_reasons"]
	assert integrity["complete"] is False
	# 合计只覆盖了 2 行，却仍是「totals」—— 分母必须写在同一份 payload 里。
	assert body["totals"]["requests"] == 2


def test_unparsable_lines_are_counted_separately_from_blank_lines(store) -> None:
	store(
		"".join(
			[
				json.dumps(_row()) + "\n",
				"{ this is not json\n",
				"\n",
			]
		)
	)
	body = _get_usage(_client(), days=30)
	integrity = body["data_integrity"]
	assert integrity["rows_read"] == 1
	assert integrity["store_unparsable_lines"] == 1
	assert integrity["store_blank_lines"] == 1
	assert "unparsable_lines_in_store" in integrity["partial_reasons"]


# ---------- 缺陷 3：无数据 vs 账本缺失/不可读 ----------


def test_missing_store_is_distinguishable_from_key_with_no_rows(store) -> None:
	c = _client()
	# ① 账本压根不存在
	body_missing = _get_usage(c, days=30)
	assert body_missing["data_integrity"]["store"] == "missing_store"
	assert body_missing["totals"]["requests"] == 0
	assert body_missing["data_integrity"]["complete"] is False
	assert "store_missing_store" in body_missing["data_integrity"]["partial_reasons"]
	# ② 账本有货，但过滤键无数据 —— 与 ① 必须是两个可区分的响应
	store([_row(), _row(key_fp="…ffff")])
	body_nokey = _get_usage(c, days=30, key_fp="…zzzz")
	assert body_nokey["data_integrity"]["store"] == "ok"
	assert body_nokey["data_integrity"]["rows_read"] == 2
	assert body_nokey["totals"]["requests"] == 0
	assert body_nokey["data_integrity"]["rows_counted_local"] == 0
	assert body_nokey["filters"]["key_fp"] == "…zzzz"


def test_empty_store_file_is_its_own_status(store) -> None:
	store("")
	body = _get_usage(_client(), days=30)
	assert body["data_integrity"]["store"] == "empty_store"
	assert body["data_integrity"]["complete"] is False


def test_unreadable_store_is_not_reported_as_zero_usage(store) -> None:
	"""账本读不动（这里用目录冒充文件，跨平台确定）⇒ 必须是 unreadable，不是 0。"""
	from usage import ledger

	store([_row()])
	path = ledger.events_path()
	path.unlink()
	path.mkdir()
	body = _get_usage(_client(), days=30)
	integrity = body["data_integrity"]
	assert integrity["store"] == "unreadable_store"
	assert integrity["rows_counted_local"] == 0
	assert "store_unreadable_store" in integrity["partial_reasons"]
	assert integrity["complete"] is False


def test_balance_endpoint_distinguishes_reasons(monkeypatch) -> None:
	c = _client()
	r = c.get("/v1/usage/balance")
	assert r.status_code == 200
	body = r.json()
	assert body["available"] is False
	assert body["reason"] == "missing_key"
	r2 = c.get("/v1/usage/balance", headers={"X-Provider": "zhipu", "Authorization": "Bearer k"})
	assert r2.json()["reason"] == "unsupported_provider"


# ---------- 缺陷 4：货币与金额口径 ----------


class _Resp:
	def __init__(self, payload: object) -> None:
		self._raw = json.dumps(payload).encode("utf-8")

	def read(self) -> bytes:
		return self._raw

	def __enter__(self):
		return self

	def __exit__(self, *a):
		return False


def _patch_balance(monkeypatch, payload: object) -> None:
	import urllib.request as ur

	monkeypatch.setattr(ur, "urlopen", lambda req, timeout=None: _Resp(payload))


def _get_balance() -> dict:
	r = _client().get(
		"/v1/usage/balance",
		headers={"Authorization": "Bearer sk-test-0001"},
	)
	assert r.status_code == 200, r.text
	return r.json()


def test_balance_currency_is_not_invented(monkeypatch) -> None:
	"""只有 USD 行时不得冒充 CNY 余额（前端会把 currency 缺失当 CNY 画 ¥）。"""
	_patch_balance(
		monkeypatch,
		{
			"is_available": True,
			"balance_infos": [
				{"currency": "USD", "total_balance": "1.20", "granted_balance": "0", "topped_up_balance": "1.20"}
			],
		},
	)
	body = _get_balance()
	assert body["available"] is False
	assert body["reason"] == "no_cny_row"
	assert body["currency"] is None
	assert body["currencies_in_response"] == ["USD"]
	assert body["other_currency_rows"][0]["currency"] == "USD"


def test_balance_single_unlabelled_row_keeps_amount_without_claiming_currency(monkeypatch) -> None:
	_patch_balance(
		monkeypatch,
		{"is_available": True, "balance_infos": [{"total_balance": "8.50"}]},
	)
	body = _get_balance()
	assert body["available"] is True
	assert body["total_balance"] == "8.50"
	assert body["currency"] is None
	assert body["currency_source"] == "absent"


def test_balance_empty_or_nonnumeric_amounts_stay_unknown(monkeypatch) -> None:
	"""空串 / 非数值 / null 一律 None + 状态标签，绝不落到 0 或裸货币符号。"""
	_patch_balance(
		monkeypatch,
		{
			"is_available": True,
			"balance_infos": [
				{
					"currency": "CNY",
					"total_balance": "0.004",
					"granted_balance": "",
					"topped_up_balance": "N/A",
				}
			],
		},
	)
	body = _get_balance()
	assert body["available"] is True
	assert body["total_balance"] == "0.004"        # 原样透传，不做 float 舍入
	assert body["granted_balance"] is None
	assert body["topped_up_balance"] is None
	assert body["amount_status"]["total_balance"] == "ok"
	assert body["amount_status"]["granted_balance"] == "empty"
	assert body["amount_status"]["topped_up_balance"] == "not_a_number"
	assert body["fields_incomplete"] is True
	assert body["numeric_balance_fields"] == 1


def test_balance_all_unreadable_is_not_available(monkeypatch) -> None:
	_patch_balance(
		monkeypatch,
		{
			"is_available": True,
			"balance_infos": [
				{"currency": "CNY", "total_balance": "", "granted_balance": None, "topped_up_balance": "-3"}
			],
		},
	)
	body = _get_balance()
	assert body["available"] is False
	assert body["reason"] == "no_numeric_balance"
	assert body["amount_status"]["topped_up_balance"] == "negative"
	assert "total_balance" not in body or body.get("total_balance") is None


def test_balance_respects_vendor_is_available_false(monkeypatch) -> None:
	_patch_balance(
		monkeypatch,
		{
			"is_available": False,
			"balance_infos": [
				{"currency": "CNY", "total_balance": "0", "granted_balance": "0", "topped_up_balance": "0"}
			],
		},
	)
	body = _get_balance()
	assert body["available"] is False
	assert body["reason"] == "vendor_reports_unavailable"
	assert body["is_available"] is False


def test_balance_non_dict_payload_is_shaped(monkeypatch) -> None:
	_patch_balance(monkeypatch, ["unexpected", "list"])
	body = _get_balance()
	assert body["available"] is False
	assert body["reason"] == "unexpected_payload_shape"


# ---------- 缺陷 4（口径侧）：来源标签不得把本机记账说成厂商权威 ----------


def test_source_becomes_mixed_when_models_and_totals_differ(store, monkeypatch) -> None:
	"""combine 允许 totals 取厂商、models 取本机；旧 payload 只写 source=vendor。"""
	from usage.vendor import _bucket_view

	vendor_report = {
		"vendor_ok": True,
		"vendor_error": "",
		"source": "vendor",
		"days": [],
		"totals": _bucket_view({"requests": 50, "cache_hit": 10, "cache_miss": 5, "output": 2}),
		"series": [],
		"models": [],                                   # 厂商没给模型拆分
		"keys": [],
	}
	monkeypatch.setattr(
		"usage.vendor.fetch_vendor_usage",
		lambda **kw: dict(vendor_report),
	)
	store([_row()])
	body = _get_usage(_client(), days=30)
	assert body["source"] == "mixed"
	assert body["source_basis"]["totals"] == "vendor"
	assert body["source_basis"]["models"] == "local"


def test_source_stays_single_basis(store) -> None:
	store([_row()])
	body = _get_usage(_client(), days=30)
	assert body["source"] == "local"
	assert body["source_basis"]["totals"] == "local"
	assert body["source_basis"]["models"] == "local"
